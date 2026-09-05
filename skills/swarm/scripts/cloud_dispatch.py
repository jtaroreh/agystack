#!/usr/bin/env python3
"""
CLI dispatcher script called by /swarm or /orchestrate to launch Cloud Run Job
for parallel swarm agent execution.
Constructs and executes gcloud run jobs execute, streams status, and aggregates results.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def find_runtime_config() -> Optional[Dict[str, Any]]:
    paths_to_check = [
        Path("agystack-runtime.json"),
        Path(".agents/plugins/agystack/agystack-runtime.json"),
        Path(os.path.expanduser("~/.gemini/config/plugins/agystack/agystack-runtime.json")),
    ]
    for path in paths_to_check:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                print(f"Warning: Failed to parse runtime config at {path}: {exc}", file=sys.stderr)
    return None


def get_git_remote_url() -> str:
    try:
        res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return ""


def get_gh_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if token.strip():
        return token.strip()
    try:
        res = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
        )
        token = res.stdout.strip()
        if token:
            return token
    except Exception:
        pass
    return ""


def load_manifest(manifest_path_or_str: str) -> List[Any]:
    if not manifest_path_or_str:
        return []
    p = Path(manifest_path_or_str)
    if p.is_file():
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.loads(manifest_path_or_str)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "tasks" in data and isinstance(data["tasks"], list):
            return data["tasks"]
        if "briefs" in data and isinstance(data["briefs"], list):
            return data["briefs"]
        return [data]
    return [data]


def build_gcloud_command(
    job_name: str,
    tasks_count: int,
    parallelism: int,
    region: str,
    project: Optional[str],
    env_vars: Dict[str, str],
    wait: bool = True,
) -> List[str]:
    cmd = ["gcloud", "run", "jobs", "execute", job_name]
    cmd.append(f"--tasks={tasks_count}")
    cmd.append(f"--region={region}")
    if project:
        cmd.append(f"--project={project}")
    if wait:
        cmd.append("--wait")
    else:
        cmd.append("--async")
    cmd.append("--format=json")

    env_pairs = []
    for k, v in env_vars.items():
        env_pairs.append(f"{k}={v}")
    if env_pairs:
        cmd.append(f"--update-env-vars=^##^{ '##'.join(env_pairs) }")

    return cmd


def parse_worker_logs(log_output: str) -> List[Dict[str, Any]]:
    results = []
    current_status = ""
    current_evidence: List[str] = []
    current_summary: List[str] = []
    mode = None

    for line in log_output.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("[STATUS:"):
            if current_status:
                results.append({
                    "status": current_status,
                    "evidence": "\n".join(current_evidence),
                    "summary": "\n".join(current_summary),
                })
            current_status = trimmed.split("[STATUS:")[1].split("]")[0].strip()
            current_evidence = []
            current_summary = []
            mode = None
        elif trimmed == "Evidence:":
            mode = "evidence"
        elif trimmed == "Summary:":
            mode = "summary"
        elif trimmed.startswith("=" * 10):
            mode = None
        else:
            if mode == "evidence":
                current_evidence.append(line)
            elif mode == "summary":
                current_summary.append(line)

    if current_status:
        results.append({
            "status": current_status,
            "evidence": "\n".join(current_evidence),
            "summary": "\n".join(current_summary),
        })

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch parallel Cloud Run swarm workers.")
    parser.add_argument("--manifest", type=str, help="Path to manifest JSON or JSON string.")
    parser.add_argument("--seed-lottery", type=int, help="Generate N coprime seed lottery tasks.")
    parser.add_argument("--gcs-bucket", type=str, help="GCS bucket name for run artifacts.")
    parser.add_argument("--gcs-prefix", type=str, default="", help="GCS object prefix.")
    parser.add_argument("--harvest-gcs", type=str, help="GCS prefix to harvest results after execution.")
    parser.add_argument("--repo", type=str, help="Git repository URL.")
    parser.add_argument("--tasks", type=int, help="Task count override.")
    parser.add_argument("--parallelism", type=int, default=100, help="Concurrency limit (default: 100).")
    parser.add_argument("--job-name", type=str, help="Cloud Run Job name.")
    parser.add_argument("--region", type=str, help="GCP region (e.g. us-central1).")
    parser.add_argument("--project", type=str, help="GCP project ID.")
    parser.add_argument("--model", type=str, help="Model override for workers.")
    parser.add_argument("--vertex", action="store_true", help="Enable Vertex AI mode.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload and command without executing.")
    parser.add_argument("--no-wait", dest="wait", action="store_false", help="Do not wait for job completion.")
    parser.set_defaults(wait=True)

    args = parser.parse_args()

    runtime_cfg = find_runtime_config() or {}
    job_name = args.job_name or runtime_cfg.get("job_name") or "agystack-swarm-worker"
    region = args.region or runtime_cfg.get("region") or "us-central1"
    project = args.project or runtime_cfg.get("project_id")
    parallelism = args.parallelism if args.parallelism != 100 else runtime_cfg.get("parallelism", 100)
    use_vertex = args.vertex or runtime_cfg.get("auth_mode") == "vertex" or runtime_cfg.get("vertex") is True
    model = args.model or runtime_cfg.get("model") or "gemini-3.8-flash"

    repo_url = args.repo or get_git_remote_url()
    if not repo_url:
        print("Error: Git repo URL not provided and could not be inferred from remote.origin.url", file=sys.stderr)
        sys.exit(1)

    gh_token = get_gh_token()
    if not gh_token:
        print("Error: GH_TOKEN could not be resolved from environment or `gh auth token`", file=sys.stderr)
        sys.exit(1)

    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not use_vertex and not gemini_api_key and not args.dry_run:
        print("Error: GEMINI_API_KEY environment variable is required when not in Vertex AI mode.", file=sys.stderr)
        sys.exit(1)

    tasks_list: List[Any] = []
    sys.path.insert(0, str(Path(__file__).parent))

    if args.seed_lottery:
        from manifest_generator import generate_seed_lottery
        tasks_list = generate_seed_lottery(seeds_count=args.seed_lottery)
    elif args.manifest:
        try:
            tasks_list = load_manifest(args.manifest)
        except Exception as exc:
            print(f"Error: Failed to load manifest: {exc}", file=sys.stderr)
            sys.exit(1)

    task_count = args.tasks or (len(tasks_list) if tasks_list else 1)
    manifest_serialized = json.dumps(tasks_list) if tasks_list else ""

    env_vars = {
        "REPO_URL": repo_url,
        "GH_TOKEN": gh_token,
    }
    if gemini_api_key:
        env_vars["GEMINI_API_KEY"] = gemini_api_key
    elif args.dry_run and not use_vertex:
        env_vars["GEMINI_API_KEY"] = "DRY_RUN_KEY"

    if use_vertex:
        env_vars["USE_VERTEX_AI"] = "1"
        if project:
            env_vars["VERTEXAI_PROJECT"] = project
        if region:
            env_vars["VERTEXAI_LOCATION"] = region

    gcs_bucket = args.gcs_bucket or runtime_cfg.get("gcs_bucket", "")
    gcs_prefix = args.gcs_prefix or runtime_cfg.get("gcs_prefix", "")
    if gcs_bucket:
        env_vars["GCS_RESULTS_BUCKET"] = gcs_bucket
        if gcs_prefix:
            env_vars["GCS_PREFIX"] = gcs_prefix

    if manifest_serialized:
        env_vars["TASK_MANIFEST"] = manifest_serialized
    if model:
        env_vars["MODEL_OVERRIDE"] = model

    gcloud_cmd = build_gcloud_command(
        job_name=job_name,
        tasks_count=task_count,
        parallelism=parallelism,
        region=region,
        project=project,
        env_vars=env_vars,
        wait=args.wait,
    )

    if args.dry_run:
        display_env = dict(env_vars)
        if display_env.get("GH_TOKEN"):
            display_env["GH_TOKEN"] = "REDACTED"
        if display_env.get("GEMINI_API_KEY"):
            display_env["GEMINI_API_KEY"] = "REDACTED"
        display_cmd = build_gcloud_command(
            job_name=job_name,
            tasks_count=task_count,
            parallelism=parallelism,
            region=region,
            project=project,
            env_vars=display_env,
            wait=args.wait,
        )
        payload = {
            "job_name": job_name,
            "tasks_count": task_count,
            "parallelism": parallelism,
            "region": region,
            "project": project,
            "env_vars": display_env,
            "gcloud_command": " ".join(display_cmd),
        }
        print(json.dumps(payload, indent=2))
        return

    print(f"Launching Cloud Run Job '{job_name}' with {task_count} tasks (parallelism: {parallelism})...")
    try:
        proc = subprocess.run(
            gcloud_cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        print("Job execution completed successfully.")

        execution_name = None
        if proc.stdout:
            try:
                json_data = json.loads(proc.stdout)
                if isinstance(json_data, dict):
                    execution_name = json_data.get("metadata", {}).get("name") or json_data.get("name")
            except Exception:
                pass

        logs_content = proc.stdout + "\n" + proc.stderr
        log_cmd_str = ""
        if execution_name:
            time.sleep(5)
            log_filter = f'resource.type="cloud_run_job" AND labels."run.googleapis.com/execution_name"="{execution_name}"'
            log_read_args = [
                "gcloud",
                "logging",
                "read",
                log_filter,
                "--limit=2000",
                "--format=value(textPayload)",
                "--order=asc",
            ]
            log_cmd_str = f"gcloud logging read '{log_filter}' --limit=2000 --format=\"value(textPayload)\" --order=asc"
            if project:
                log_read_args.extend(["--project", project])
                log_cmd_str += f" --project={project}"

            for attempt in range(2):
                try:
                    log_res = subprocess.run(
                        log_read_args,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if log_res.stdout:
                        logs_content = log_res.stdout
                        if "- Slice JSON:" in log_res.stdout:
                            break
                    time.sleep(5)
                except Exception as exc:
                    print(f"Warning: Failed to fetch container logs: {exc}", file=sys.stderr)

        parsed_results = parse_worker_logs(logs_content)
        
        print("\n" + "=" * 80)
        print(f"SWARM EXECUTION REPORT: {job_name}")
        print("=" * 80)
        print(f"{'Task':<8} | {'Status':<10} | {'Summary'}")
        print("-" * 80)
        pass_count = 0
        issues_count = 0
        blocked_count = 0

        for i, item in enumerate(parsed_results):
            st = item.get("status", "UNKNOWN")
            sm = item.get("summary", "").replace("\n", " ")[:60]
            if st == "PASS":
                pass_count += 1
            elif st == "ISSUES":
                issues_count += 1
            elif st == "BLOCKED":
                blocked_count += 1
            print(f"{i:<8} | {st:<10} | {sm}")

        if not parsed_results:
            print(f"Total tasks: {task_count}.")
            if execution_name:
                print(f"Execution: {execution_name}")
                print(f"No container logs returned yet. Run the following command to view traces:\n  {log_cmd_str}")
            else:
                print("Review Cloud Run console logs for per-container traces.")
        else:
            print("=" * 80)
            print(f"Total: {len(parsed_results)} | PASS: {pass_count} | ISSUES: {issues_count} | BLOCKED: {blocked_count}")
            print("=" * 80)

        harvested_slices = []
        for item in parsed_results:
            for ev_line in item.get("evidence", "").splitlines():
                if ev_line.strip().startswith("- Slice JSON:"):
                    raw_json = ev_line.strip().split("- Slice JSON:", 1)[1].strip()
                    try:
                        harvested_slices.append(json.loads(raw_json))
                    except Exception:
                        pass
        if harvested_slices:
            out_slices_file = Path(".slices/harvested_scores.json")
            out_slices_file.parent.mkdir(parents=True, exist_ok=True)
            out_slices_file.write_text(json.dumps(harvested_slices, indent=2), encoding="utf-8")
            print(f"Harvested {len(harvested_slices)} slice scores to {out_slices_file}")

        harvest_target = args.harvest_gcs or (gcs_prefix if gcs_bucket else None)
        if harvest_target is not None and gcs_bucket:
            from result_harvester import harvest_gcs_results
            harvested_data = harvest_gcs_results(bucket_name=gcs_bucket, prefix=harvest_target)
            print(f"\nHarvested {len(harvested_data)} task result payloads from gs://{gcs_bucket}/{harvest_target}")

    except subprocess.CalledProcessError as exc:
        err_out = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
        print(f"Error executing Cloud Run job: {err_out}", file=sys.stderr)
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
