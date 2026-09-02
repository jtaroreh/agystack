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
from pathlib import Path
from typing import Any, Dict, List, Optional


def find_runtime_config() -> Optional[Dict[str, Any]]:
    paths_to_check = [
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
    cmd.append(f"--parallelism={parallelism}")
    cmd.append(f"--region={region}")
    if project:
        cmd.append(f"--project={project}")
    if wait:
        cmd.append("--wait")
    cmd.append("--format=json")

    env_pairs = []
    for k, v in env_vars.items():
        escaped_v = v.replace("\\", "\\\\").replace(",", "\\,")
        env_pairs.append(f"{k}={escaped_v}")
    if env_pairs:
        cmd.append(f"--update-env-vars={','.join(env_pairs)}")

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
    parser.add_argument("--repo", type=str, help="Git repository URL.")
    parser.add_argument("--tasks", type=int, help="Task count override.")
    parser.add_argument("--parallelism", type=int, default=100, help="Concurrency limit (default: 100).")
    parser.add_argument("--job-name", type=str, help="Cloud Run Job name.")
    parser.add_argument("--region", type=str, help="GCP region (e.g. us-central1).")
    parser.add_argument("--project", type=str, help="GCP project ID.")
    parser.add_argument("--model", type=str, help="Model override for workers.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload and command without executing.")
    parser.add_argument("--no-wait", dest="wait", action="store_false", help="Do not wait for job completion.")
    parser.set_defaults(wait=True)

    args = parser.parse_args()

    runtime_cfg = find_runtime_config() or {}
    job_name = args.job_name or runtime_cfg.get("job_name") or "agystack-swarm-worker"
    region = args.region or runtime_cfg.get("region") or "us-central1"
    project = args.project or runtime_cfg.get("project_id")
    parallelism = args.parallelism if args.parallelism != 100 else runtime_cfg.get("parallelism", 100)
    model = args.model or runtime_cfg.get("model", "")

    repo_url = args.repo or get_git_remote_url()
    if not repo_url:
        print("Error: Git repo URL not provided and could not be inferred from remote.origin.url", file=sys.stderr)
        sys.exit(1)

    gh_token = get_gh_token()
    if not gh_token:
        print("Error: GH_TOKEN could not be resolved from environment or `gh auth token`", file=sys.stderr)
        sys.exit(1)

    gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_api_key and not args.dry_run:
        print("Error: GEMINI_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)

    tasks_list = []
    if args.manifest:
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
        "GEMINI_API_KEY": gemini_api_key or "DRY_RUN_KEY",
    }
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
        payload = {
            "job_name": job_name,
            "tasks_count": task_count,
            "parallelism": parallelism,
            "region": region,
            "project": project,
            "env_vars": display_env,
            "gcloud_command": " ".join(gcloud_cmd),
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
        parsed_results = parse_worker_logs(proc.stdout + "\n" + proc.stderr)
        
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
            print(f"Total tasks: {task_count}. Review Cloud Run console logs for per-container traces.")
        else:
            print("=" * 80)
            print(f"Total: {len(parsed_results)} | PASS: {pass_count} | ISSUES: {issues_count} | BLOCKED: {blocked_count}")
            print("=" * 80)

    except subprocess.CalledProcessError as exc:
        err_out = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
        print(f"Error executing Cloud Run job: {err_out}", file=sys.stderr)
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
