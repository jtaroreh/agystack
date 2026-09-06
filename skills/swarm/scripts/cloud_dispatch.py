#!/usr/bin/env python3
"""
CLI dispatcher script called by /swarm or /orchestrate to launch Cloud Run Job
for parallel swarm agent execution.
Constructs and executes gcloud run jobs execute, streams status, and aggregates results.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from storage_messenger import StorageMessenger
except ImportError:
    StorageMessenger = None


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


def build_authenticated_git_url(repo_url: str, gh_token: str) -> str:
    repo_clean = repo_url.strip()
    if repo_clean.startswith("git@github.com:"):
        path = repo_clean[len("git@github.com:") :]
        return f"https://x-access-token:{gh_token}@github.com/{path}"
    if repo_clean.startswith("https://"):
        parsed = urllib.parse.urlsplit(repo_clean)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        return f"https://x-access-token:{gh_token}@{netloc}{parsed.path}"
    if repo_clean.startswith("http://"):
        parsed = urllib.parse.urlsplit(repo_clean)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        return f"http://x-access-token:{gh_token}@{netloc}{parsed.path}"
    if "/" in repo_clean and not repo_clean.startswith("/"):
        return f"https://x-access-token:{gh_token}@github.com/{repo_clean.rstrip('.git')}.git"
    return repo_clean


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
    max_retries: int = 0,
) -> List[str]:
    cmd = ["gcloud", "run", "jobs", "execute", job_name]
    cmd.append(f"--tasks={tasks_count}")
    if parallelism > 0:
        cmd.append(f"--parallelism={parallelism}")
    cmd.append(f"--max-retries={max_retries}")
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


MILESTONE_REGEX = re.compile(
    r"\[MILESTONE\]\s+\[TASK\s+(\d+)\]\s+\[PHASE:\s*([^\]]+)\](?:\s+(.*))?"
)


def parse_milestone_log(line: str) -> Optional[Dict[str, str]]:
    m = MILESTONE_REGEX.search(line)
    if not m:
        return None
    return {
        "task_index": m.group(1),
        "phase": m.group(2).strip(),
        "detail": m.group(3).strip() if m.group(3) else "",
    }


def monitor_execution(
    execution_name: str,
    project: Optional[str],
    region: str,
    task_count: int,
    poll_interval: float = 4,
) -> Optional[Dict[str, Any]]:
    seen_log_entries = set()
    last_counts = None
    desc_data: Optional[Dict[str, Any]] = None

    while True:
        try:
            describe_cmd = [
                "gcloud",
                "run",
                "jobs",
                "executions",
                "describe",
                execution_name,
                f"--region={region}",
                "--format=json",
            ]
            if project:
                describe_cmd.append(f"--project={project}")

            res = subprocess.run(
                describe_cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                time.sleep(poll_interval)
                continue

            desc_data = json.loads(res.stdout)
            status = desc_data.get("status", {}) if isinstance(desc_data, dict) else {}

            if task_count <= 4:
                log_filter = f'labels."run.googleapis.com/execution_name"="{execution_name}"'
                log_cmd = [
                    "gcloud",
                    "logging",
                    "read",
                    log_filter,
                    "--limit=500",
                    "--format=value(textPayload)",
                    "--order=asc",
                ]
                if project:
                    log_cmd.extend(["--project", project])

                try:
                    log_res = subprocess.run(
                        log_cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if log_res.returncode == 0 and log_res.stdout:
                        for line in log_res.stdout.splitlines():
                            line_str = line.strip()
                            if not line_str:
                                continue
                            if line_str in seen_log_entries:
                                continue
                            if any(
                                k in line_str
                                for k in [
                                    "[MILESTONE]",
                                    "[STATUS:",
                                    "PASS",
                                    "SMOKE_PASS",
                                    "DEV_IMPROVED",
                                    "REGRESSED",
                                    "ISSUES",
                                    "BLOCKED",
                                ]
                            ):
                                seen_log_entries.add(line_str)
                                if "WAITING_FOR_ORCHESTRATOR" in line_str:
                                    print(f"[WAITING_FOR_ORCHESTRATOR] >>> {line_str} <<<", flush=True)
                                else:
                                    print(line_str, flush=True)
                except Exception:
                    pass
            else:
                succeeded = status.get("succeededCount", 0)
                running = status.get("runningCount", 0)
                failed = status.get("failedCount", 0)
                current_counts = (succeeded, running, failed)
                if current_counts != last_counts:
                    last_counts = current_counts
                    print(
                        f"[Cloud Swarm] Progress: {succeeded}/{task_count} succeeded, {running} running, {failed} failed.",
                        flush=True,
                    )

            conditions = status.get("conditions", []) if isinstance(status, dict) else []
            is_completed = False
            for cond in conditions:
                if isinstance(cond, dict) and cond.get("type") == "Completed":
                    c_status = str(cond.get("status", "")).strip()
                    if c_status in ("True", "False"):
                        is_completed = True
                        break

            if is_completed:
                if task_count <= 4:
                    log_filter = f'labels."run.googleapis.com/execution_name"="{execution_name}"'
                    log_cmd = [
                        "gcloud",
                        "logging",
                        "read",
                        log_filter,
                        "--limit=500",
                        "--format=value(textPayload)",
                        "--order=asc",
                    ]
                    if project:
                        log_cmd.extend(["--project", project])
                    try:
                        log_res = subprocess.run(
                            log_cmd,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if log_res.returncode == 0 and log_res.stdout:
                            for line in log_res.stdout.splitlines():
                                line_str = line.strip()
                                if not line_str or line_str in seen_log_entries:
                                    continue
                                if any(
                                    k in line_str
                                    for k in [
                                        "[MILESTONE]",
                                        "[STATUS:",
                                        "PASS",
                                        "SMOKE_PASS",
                                        "DEV_IMPROVED",
                                        "REGRESSED",
                                        "ISSUES",
                                        "BLOCKED",
                                    ]
                                ):
                                    seen_log_entries.add(line_str)
                                    print(line_str, flush=True)
                    except Exception:
                        pass
                break

        except Exception:
            pass

        time.sleep(poll_interval)

    return desc_data


def run_preflight(
    repo_url: str,
    gh_token: str,
    use_vertex: bool,
    gemini_api_key: str,
    project: Optional[str],
    region: str,
    model: str,
    dry_run: bool = False,
    vertex_location: Optional[str] = None,
) -> None:
    print("[PRE-FLIGHT] Verifying cloud swarm credentials, quota tiers, and repository access...", flush=True)

    if not vertex_location:
        vertex_location = "global" if model.startswith(("gemini-2.5", "gemini-3")) else region

    # 1. Git Authentication & Repository Accessibility Check
    if not repo_url:
        raise RuntimeError("Git repo URL could not be determined.")

    if not gh_token:
        raise RuntimeError(
            "GH_TOKEN could not be resolved from environment or `gh auth token`.\n"
            "Cloud swarm workers require a valid GitHub token to clone and push candidate branches."
        )

    auth_url = build_authenticated_git_url(repo_url, gh_token)
    try:
        subprocess.run(
            ["git", "ls-remote", auth_url, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        print(f"  [PASS] Git remote authentication & repository accessibility verified ({repo_url}).")
    except subprocess.CalledProcessError as exc:
        err_msg = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
        raise RuntimeError(
            f"Git repository accessibility check failed for '{repo_url}'.\n"
            f"git ls-remote exited with code {exc.returncode}: {err_msg.strip()}\n"
            "Please verify GH_TOKEN permissions and repository URL."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Timed out connecting to git repository '{repo_url}'.") from exc
    except Exception as exc:
        raise RuntimeError(f"Git remote accessibility error: {exc}") from exc

    # 2. Model & Quota Tier Check
    if use_vertex:
        token_cmd = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if token_cmd.returncode != 0 or not token_cmd.stdout.strip():
            raise RuntimeError(
                "Failed to obtain gcloud access token for Vertex AI mode.\n"
                f"gcloud error: {token_cmd.stderr.strip()}\n"
                "Run `gcloud auth login` or `gcloud auth application-default login`."
            )
        access_token = token_cmd.stdout.strip()

        if not project:
            raise RuntimeError(
                "GCP project ID is required for Vertex AI mode (--project or agystack-runtime.json)."
            )

        if vertex_location == "global":
            probe_url = f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/{model}:generateContent"
        else:
            probe_url = f"https://{vertex_location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{vertex_location}/publishers/google/models/{model}:generateContent"
        req_data = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": project,
        }
        req = urllib.request.Request(
            probe_url,
            data=req_data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                pass
            print(f"  [PASS] Vertex AI credentials and publisher model '{model}' verified in {vertex_location} (project: {project}).")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 403:
                raise RuntimeError(
                    f"Vertex AI probe returned 403 Forbidden for project '{project}' in location '{vertex_location}'.\n"
                    f"Server Response:\n{err_body}\n"
                    "Required Permissions:\n"
                    "- Ensure active principal has the 'Vertex AI User' role (roles/aiplatform.user).\n"
                    f"- Ensure Vertex AI API (aiplatform.googleapis.com) is enabled on project '{project}'."
                ) from exc
            elif exc.code == 404:
                raise RuntimeError(
                    f"Vertex AI publisher model '{model}' not found in location '{vertex_location}' (404 Not Found).\n"
                    f"Server Response:\n{err_body}\n"
                    f"Verify that model '{model}' is supported and published in location '{vertex_location}'."
                ) from exc
            else:
                raise RuntimeError(
                    f"Vertex AI probe failed with HTTP {exc.code} for project '{project}' in location '{vertex_location}':\n{err_body}"
                ) from exc
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"Vertex AI connection error: {exc}") from exc
    else:
        if not gemini_api_key:
            if dry_run:
                print("  [DRY-RUN] GEMINI_API_KEY not set; skipping live quota ping during dry-run.")
                return
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is required when not in Vertex AI mode."
            )

        probe_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
        req_data = json.dumps({
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }).encode("utf-8")
        req = urllib.request.Request(
            probe_url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        free_tier_indicators = [
            "freetier",
            "free_tier",
            "free-tier",
            "free_tier_requests",
            "5 rpm",
            "5rpm",
            "rate limit <= 5 rpm",
            "5 requests per minute",
        ]

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_text = resp.read().decode("utf-8", errors="replace")
                combined = (resp_text + " " + str(resp.headers)).lower()
                matched = next((ind for ind in free_tier_indicators if ind in combined), None)
                if matched:
                    raise RuntimeError(
                        f"Free-tier Gemini API key detected ('{matched}' found in response).\n"
                        "Free-tier keys are limited to 5 requests per minute (RPM) and cannot support parallel swarms.\n"
                        "Cloud Run swarms require a paid Google AI Studio tier (Pay-as-you-go / Tier 1+) or Vertex AI (--vertex)."
                    )
            print(f"  [PASS] Gemini API key validated (paid tier / model '{model}' accessible).")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            combined_err = (err_body + " " + str(exc.headers)).lower()
            matched = next((ind for ind in free_tier_indicators if ind in combined_err), None)
            if matched or exc.code == 429:
                detail_msg = f" ('{matched}' detected)" if matched else ""
                raise RuntimeError(
                    f"Gemini API rate-limit/quota restriction detected{detail_msg} (HTTP {exc.code}).\n"
                    f"Details:\n{err_body}\n"
                    "Free-tier API keys (5 RPM) cannot support parallel swarms.\n"
                    "Upgrade your Google AI Studio key to paid/unmetered billing (Pay-as-you-go / Tier 1+) or use Vertex AI (--vertex)."
                ) from exc
            else:
                raise RuntimeError(
                    f"Gemini API request failed with HTTP {exc.code}:\n{err_body}"
                ) from exc
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"Gemini API ping failed: {exc}") from exc


def resolve_swarm_model(
    cli_model: Optional[str] = None,
    runtime_model: Optional[str] = None,
    agystack_models_path: Optional[Path] = None,
) -> str:
    if cli_model and cli_model.strip():
        chosen = cli_model.strip()
    elif runtime_model and runtime_model.strip() and runtime_model.strip().lower() != "inherit":
        chosen = runtime_model.strip()
    else:
        role_model = None
        paths_to_check = [
            agystack_models_path,
            Path("agystack-models.md"),
            Path("rules/agystack-models.md"),
            Path(".agents/plugins/agystack/rules/agystack-models.md"),
            Path(os.path.expanduser("~/.gemini/config/plugins/agystack/rules/agystack-models.md")),
        ]
        for p in paths_to_check:
            if p and p.is_file():
                try:
                    for line in p.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("#") or not line:
                            continue
                        if ":" in line:
                            role, m = line.split(":", 1)
                            if "swarm worker" in role.lower():
                                role_model = m.strip().split(",")[0].strip()
                                break
                    if role_model:
                        break
                except Exception:
                    pass
        chosen = role_model or "inherit"

    tier_map = {
        "inherit": "gemini-3.8-flash",
        "flash": "gemini-3.8-flash",
        "pro": "gemini-3.1-pro",
        "flash_lite": "gemini-3.1-flash-lite",
    }
    return tier_map.get(chosen.lower(), chosen)


def handle_mailbox_list(
    session_id: str,
    bucket_name: Optional[str] = None,
    messenger: Optional[Any] = None,
) -> List[Any]:
    if messenger is None:
        if not bucket_name:
            runtime_cfg = find_runtime_config() or {}
            bucket_name = runtime_cfg.get("gcs_bucket") or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        if not bucket_name:
            print("Error: GCS bucket name must be specified via --gcs-bucket, GCS_BUCKET, or agystack-runtime.json", file=sys.stderr)
            sys.exit(1)
        if StorageMessenger is None:
            print("Error: StorageMessenger is not available", file=sys.stderr)
            sys.exit(1)
        messenger = StorageMessenger(bucket_name=bucket_name, session_id=session_id, is_worker=False)

    pending = messenger.list_pending_questions()
    if not pending:
        print(f"No pending questions for session '{session_id}'.")
    else:
        print(f"\nPending questions for session '{session_id}':")
        print(f"{'TASK':<6} | {'SEQ':<5} | {'TIMESTAMP':<20} | {'QUESTION'}")
        print("-" * 75)
        for q in pending:
            q_text = q.payload.get("question", "")
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(q.timestamp))
            print(f"{q.task_index:<6} | {q.seq:<5} | {ts_str:<20} | {q_text}")
    return pending


def handle_mailbox_reply(
    task_index: int,
    seq: int,
    text: str,
    session_id: str,
    bucket_name: Optional[str] = None,
    messenger: Optional[Any] = None,
) -> Any:
    if messenger is None:
        if not bucket_name:
            runtime_cfg = find_runtime_config() or {}
            bucket_name = runtime_cfg.get("gcs_bucket") or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        if not bucket_name:
            print("Error: GCS bucket name must be specified via --gcs-bucket, GCS_BUCKET, or agystack-runtime.json", file=sys.stderr)
            sys.exit(1)
        if StorageMessenger is None:
            print("Error: StorageMessenger is not available", file=sys.stderr)
            sys.exit(1)
        messenger = StorageMessenger(bucket_name=bucket_name, session_id=session_id, is_worker=False)

    reply_env = messenger.send_reply(task_index=task_index, seq=seq, reply_text=text)
    print(f"Reply sent to task {task_index} (seq {seq}): {text}")
    return reply_env


def handle_mailbox_steer(
    task_index: int,
    text: str,
    session_id: str,
    bucket_name: Optional[str] = None,
    messenger: Optional[Any] = None,
) -> Any:
    if messenger is None:
        if not bucket_name:
            runtime_cfg = find_runtime_config() or {}
            bucket_name = runtime_cfg.get("gcs_bucket") or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        if not bucket_name:
            print("Error: GCS bucket name must be specified via --gcs-bucket, GCS_BUCKET, or agystack-runtime.json", file=sys.stderr)
            sys.exit(1)
        if StorageMessenger is None:
            print("Error: StorageMessenger is not available", file=sys.stderr)
            sys.exit(1)
        messenger = StorageMessenger(bucket_name=bucket_name, session_id=session_id, is_worker=False)

    steer_env = messenger.send_steer(task_index=task_index, instruction=text)
    print(f"Steer instruction sent to task {task_index} (seq {steer_env.seq}): {text}")
    return steer_env


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
    parser.add_argument("--max-retries", type=int, default=0, help="Max retry attempts per task (default: 0 for fast fail).")
    parser.add_argument("--job-name", type=str, help="Cloud Run Job name.")
    parser.add_argument("--region", type=str, help="GCP region (e.g. us-central1).")
    parser.add_argument("--project", type=str, help="GCP project ID.")
    parser.add_argument("--model", type=str, help="Model override for workers (default: inherit).")
    parser.add_argument("--vertex", action="store_true", help="Enable Vertex AI mode.")
    parser.add_argument("--vertex-location", type=str, default=None, help="Vertex AI location (e.g. global or us-central1).")
    parser.add_argument("--preflight", action="store_true", help="Run pre-flight quota, auth, and git connectivity checks.")
    parser.add_argument("--no-preflight", action="store_true", help="Skip pre-flight checks.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload and command without executing.")
    parser.add_argument("--wait", dest="wait", action="store_true", help="Wait synchronously for job completion.")
    parser.add_argument("--no-wait", dest="wait", action="store_false", help="Do not wait for job completion (default).")
    parser.add_argument("--session", "--session-id", dest="session_id", type=str, help="Swarm session ID (default: swarm-<timestamp>).")
    parser.add_argument("--orchestrator-timeout", type=float, default=600.0, help="Timeout in seconds for orchestrator replies (default: 600.0).")
    parser.set_defaults(wait=False)

    subparsers = parser.add_subparsers(dest="subcommand", help="Optional subcommand")
    mailbox_parser = subparsers.add_parser("mailbox", help="Interact with worker mailboxes")
    mailbox_subparsers = mailbox_parser.add_subparsers(dest="mailbox_action", help="Mailbox action")

    # mailbox list
    list_p = mailbox_subparsers.add_parser("list", help="List pending questions across workers")
    list_p.add_argument("--session", type=str, help="Session ID")
    list_p.add_argument("--gcs-bucket", type=str, help="GCS bucket name")

    # mailbox reply
    reply_p = mailbox_subparsers.add_parser("reply", help="Reply to a worker question")
    reply_p.add_argument("--task", type=int, required=True, help="Task index")
    reply_p.add_argument("--seq", type=int, required=True, help="Sequence number of the question")
    reply_p.add_argument("--text", type=str, required=True, help="Reply text")
    reply_p.add_argument("--session", type=str, help="Session ID")
    reply_p.add_argument("--gcs-bucket", type=str, help="GCS bucket name")

    # mailbox steer
    steer_p = mailbox_subparsers.add_parser("steer", help="Send a steering instruction to a worker")
    steer_p.add_argument("--task", type=int, required=True, help="Task index")
    steer_p.add_argument("--text", type=str, required=True, help="Steering instruction text")
    steer_p.add_argument("--session", type=str, help="Session ID")
    steer_p.add_argument("--gcs-bucket", type=str, help="GCS bucket name")

    args = parser.parse_args()

    if args.subcommand == "mailbox":
        runtime_cfg = find_runtime_config() or {}
        session_id = args.session or os.environ.get("SWARM_SESSION_ID") or os.environ.get("SESSION_ID") or "default"
        bkt = args.gcs_bucket or runtime_cfg.get("gcs_bucket") or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        if args.mailbox_action == "list":
            handle_mailbox_list(session_id=session_id, bucket_name=bkt)
        elif args.mailbox_action == "reply":
            handle_mailbox_reply(task_index=args.task, seq=args.seq, text=args.text, session_id=session_id, bucket_name=bkt)
        elif args.mailbox_action == "steer":
            handle_mailbox_steer(task_index=args.task, text=args.text, session_id=session_id, bucket_name=bkt)
        else:
            mailbox_parser.print_help()
        return

    runtime_cfg = find_runtime_config() or {}
    job_name = args.job_name or runtime_cfg.get("job_name") or "agystack-swarm-worker"
    region = args.region or runtime_cfg.get("region") or "us-central1"
    project = args.project or runtime_cfg.get("project_id")
    parallelism = args.parallelism if args.parallelism != 100 else runtime_cfg.get("parallelism", 100)
    use_vertex = args.vertex or runtime_cfg.get("auth_mode") == "vertex" or runtime_cfg.get("vertex") is True
    model = resolve_swarm_model(cli_model=args.model, runtime_model=runtime_cfg.get("model"))
    vertex_location = args.vertex_location or runtime_cfg.get("vertex_location") or ("global" if model.startswith(("gemini-2.5", "gemini-3")) else region)

    repo_url = args.repo or get_git_remote_url()
    gh_token = get_gh_token()
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    should_run_preflight = args.preflight or (not args.no_preflight and not args.dry_run)
    if should_run_preflight:
        try:
            run_preflight(
                repo_url=repo_url,
                gh_token=gh_token,
                use_vertex=use_vertex,
                gemini_api_key=gemini_api_key,
                project=project,
                region=region,
                model=model,
                dry_run=args.dry_run,
                vertex_location=vertex_location,
            )
        except RuntimeError as exc:
            print(f"Error [Pre-Flight]: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.preflight and not args.dry_run:
            print("Pre-flight checks passed successfully.")
            return

    if not repo_url:
        print("Error: Git repo URL not provided and could not be inferred from remote.origin.url", file=sys.stderr)
        sys.exit(1)

    if not gh_token:
        print("Error: GH_TOKEN could not be resolved from environment or `gh auth token`", file=sys.stderr)
        sys.exit(1)

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
        env_vars["VERTEXAI_LOCATION"] = vertex_location

    session_id = args.session_id or f"swarm-{int(time.time())}"
    env_vars["SWARM_SESSION_ID"] = session_id
    env_vars["SESSION_ID"] = session_id
    if args.orchestrator_timeout:
        env_vars["ORCHESTRATOR_TIMEOUT"] = str(args.orchestrator_timeout)

    gcs_bucket = args.gcs_bucket or runtime_cfg.get("gcs_bucket", "")
    gcs_prefix = args.gcs_prefix or runtime_cfg.get("gcs_prefix", "")
    if gcs_bucket:
        env_vars["GCS_BUCKET"] = gcs_bucket
        env_vars["GCS_RESULTS_BUCKET"] = gcs_bucket
        if gcs_prefix:
            env_vars["GCS_PREFIX"] = gcs_prefix

    if manifest_serialized:
        env_vars["TASK_MANIFEST"] = manifest_serialized
    if model:
        env_vars["MODEL_OVERRIDE"] = model

    dispatch_cmd = build_gcloud_command(
        job_name=job_name,
        tasks_count=task_count,
        parallelism=parallelism,
        region=region,
        project=project,
        env_vars=env_vars,
        wait=False,
        max_retries=args.max_retries,
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
            max_retries=args.max_retries,
        )
        payload = {
            "job_name": job_name,
            "tasks_count": task_count,
            "parallelism": parallelism,
            "max_retries": args.max_retries,
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
            dispatch_cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        execution_name = None
        if proc.stdout:
            try:
                json_data = json.loads(proc.stdout)
                if isinstance(json_data, dict):
                    execution_name = json_data.get("metadata", {}).get("name") or json_data.get("name")
            except Exception:
                pass
        if not execution_name:
            m = re.search(r"\[([a-zA-Z0-9_\-]+)\]", proc.stderr + " " + proc.stdout)
            if m:
                execution_name = m.group(1)

        if not args.wait:
            if execution_name:
                print(f"Execution: {execution_name}")
            else:
                print("Dispatched Cloud Run Job execution asynchronously.")
            return

        if execution_name:
            print(f"Monitoring execution '{execution_name}' in region '{region}'...")
            monitor_execution(
                execution_name=execution_name,
                project=project,
                region=region,
                task_count=task_count,
            )

        print("Job execution completed successfully.")

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
