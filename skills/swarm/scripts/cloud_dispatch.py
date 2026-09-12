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
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple, Union

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


def clean_repo_url(url: str) -> str:
    """Removes any embedded username:password or token credentials from a repository URL."""
    if not url:
        return ""
    url_clean = url.strip()
    if url_clean.startswith("git@"):
        return url_clean
    if "://" in url_clean:
        parsed = urllib.parse.urlsplit(url_clean)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return url_clean


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


def stage_manifest(
    manifest_data: Any,
    bucket_name: str,
    session_id: str,
    dry_run: bool = False,
) -> Optional[str]:
    """
    Uploads serialized manifest JSON to gs://<bucket_name>/swarms/<session_id>/manifest.json.
    Returns the gs:// URI if successful, or None on failure (falling back to TASK_MANIFEST).
    """
    if not bucket_name:
        return None

    if isinstance(manifest_data, str):
        manifest_json = manifest_data
    else:
        manifest_json = json.dumps(manifest_data)

    if not manifest_json.strip():
        return None

    clean_bucket = bucket_name.strip()
    object_name = f"swarms/{session_id}/manifest.json"
    manifest_uri = f"gs://{clean_bucket}/{object_name}"

    if dry_run:
        return manifest_uri

    # 1. Local testing mock directory
    local_dir = os.environ.get("STORAGE_MESSENGER_LOCAL_DIR")
    if local_dir:
        local_path = Path(local_dir) / clean_bucket / object_name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(manifest_json, encoding="utf-8")
        return manifest_uri

    # 2. Try storage_uploader.upload_artifact or upload_to_gcs
    try:
        import storage_uploader

        if hasattr(storage_uploader, "upload_artifact"):
            if storage_uploader.upload_artifact(clean_bucket, object_name, manifest_json, "application/json"):
                return manifest_uri
    except Exception:
        pass

    # 3. Try google.cloud.storage
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(clean_bucket)
        blob = bucket.blob(object_name)
        blob.upload_from_string(manifest_json, content_type="application/json")
        return manifest_uri
    except Exception:
        pass

    # 4. Try storage_uploader.upload_to_gcs via tempfile
    try:
        import tempfile
        import storage_uploader

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
            tf.write(manifest_json)
            temp_path = Path(tf.name)
        try:
            if storage_uploader.upload_to_gcs(clean_bucket, object_name, temp_path):
                return manifest_uri
        finally:
            temp_path.unlink(missing_ok=True)
    except Exception:
        pass

    # 5. Try gcloud storage cp
    try:
        import tempfile

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
            tf.write(manifest_json)
            temp_path = Path(tf.name)
        try:
            res = subprocess.run(
                ["gcloud", "storage", "cp", str(temp_path), manifest_uri],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if res.returncode == 0:
                return manifest_uri
        finally:
            temp_path.unlink(missing_ok=True)
    except Exception:
        pass

    return None


def extract_secret_keys(*secret_sources: Any) -> Set[str]:
    keys: Set[str] = set()
    for source in secret_sources:
        if not source:
            continue
        if isinstance(source, dict):
            for k in source.keys():
                if k:
                    keys.add(str(k).strip())
        elif isinstance(source, (list, tuple, set)):
            for item in source:
                if not item:
                    continue
                item_str = str(item).strip()
                if "=" in item_str:
                    keys.add(item_str.split("=", 1)[0].strip())
                elif ":" in item_str:
                    keys.add(item_str.split(":", 1)[0].strip())
                elif item_str:
                    keys.add(item_str)
        elif isinstance(source, str):
            for part in source.split(","):
                part = part.strip()
                if not part:
                    continue
                if "=" in part:
                    keys.add(part.split("=", 1)[0].strip())
                elif ":" in part:
                    keys.add(part.split(":", 1)[0].strip())
                elif part:
                    keys.add(part)
    return keys


def build_gcloud_command(
    job_name: str,
    tasks_count: int,
    parallelism: int,
    region: str,
    project: Optional[str],
    env_vars: Dict[str, str],
    wait: bool = True,
    max_retries: int = 0,
    secrets_mapping: Optional[Union[Dict[str, str], List[str], str]] = None,
    set_secrets: Optional[Union[Dict[str, str], List[str], str]] = None,
    auth_mode: Optional[str] = None,
    use_vertex: bool = False,
) -> List[str]:
    if env_vars is None:
        env_vars = {}
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

    # In Vertex AI auth mode, workers use ambient credentials; do not pass GEMINI_API_KEY
    is_vertex = (
        (auth_mode and auth_mode.lower() == "vertex")
        or use_vertex
        or env_vars.get("USE_VERTEX_AI") in ("1", "true", "True")
    )
    clean_env_vars = dict(env_vars)
    if is_vertex:
        clean_env_vars.pop("GEMINI_API_KEY", None)
        clean_env_vars.pop("gemini_api_key", None)

    # Strictly pop any secret key specified in secrets_mapping or set_secrets
    secret_keys = extract_secret_keys(secrets_mapping, set_secrets)
    for sec_key in secret_keys:
        clean_env_vars.pop(sec_key, None)
        clean_env_vars.pop(sec_key.upper(), None)
        clean_env_vars.pop(sec_key.lower(), None)

    env_pairs = []
    for k, v in clean_env_vars.items():
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

    def _flush():
        nonlocal current_status, current_evidence, current_summary
        if current_status:
            evidence_str = "\n".join(current_evidence)
            summary_str = "\n".join(current_summary)
            entry: Dict[str, Any] = {
                "status": current_status,
                "evidence": evidence_str,
                "summary": summary_str,
            }
            m = re.search(r"-\s*Task Index:\s*(\d+)", evidence_str, re.IGNORECASE)
            if m:
                entry["task_index"] = int(m.group(1))
            results.append(entry)

    for line in log_output.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("[STATUS:"):
            _flush()
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

    _flush()
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


class MonitorResult(tuple):
    def __new__(cls, data: Optional[Dict[str, Any]], succeeded: bool, error: Optional[str]):
        return tuple.__new__(cls, (data, succeeded, error))

    @property
    def data(self) -> Optional[Dict[str, Any]]:
        return self[0]

    @property
    def succeeded(self) -> bool:
        return self[1]

    @property
    def error(self) -> Optional[str]:
        return self[2]

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if item in ("data", "desc_data"):
                return self[0]
            elif item in ("succeeded", "execution_succeeded"):
                return self[1]
            elif item in ("error", "failure_msg"):
                return self[2]
            raise KeyError(item)
        return tuple.__getitem__(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


def recover_session_id_from_execution(
    execution_name: str,
    region: str,
    project: Optional[str] = None,
) -> Optional[str]:
    try:
        cmd = [
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
            cmd.append(f"--project={project}")
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0 or not res.stdout:
            return None
        data = json.loads(res.stdout)

        def find_env_val(obj: Any) -> Optional[str]:
            if isinstance(obj, dict):
                if obj.get("name") in ("SWARM_SESSION_ID", "SESSION_ID"):
                    val = obj.get("value")
                    if val:
                        return str(val).strip()
                for v in obj.values():
                    found = find_env_val(v)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = find_env_val(item)
                    if found:
                        return found
            return None

        return find_env_val(data)
    except Exception:
        return None


def monitor_execution(
    execution_name: str,
    project: Optional[str],
    region: str,
    task_count: int,
    poll_interval: float = 4,
    timeout: float = 2700.0,
) -> MonitorResult:
    seen_log_entries = set()
    last_counts = None
    desc_data: Optional[Dict[str, Any]] = None
    execution_succeeded = False
    failure_msg: Optional[str] = None
    start_time = time.time()

    while True:
        if timeout > 0 and (time.time() - start_time) > timeout:
            failure_msg = f"Cloud Run execution monitoring timed out after {timeout} seconds."
            print(f"Warning: {failure_msg}", file=sys.stderr)
            break
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
                print(f"Warning: Execution describe failed (code {res.returncode}): {res.stderr.strip()}", file=sys.stderr)
                time.sleep(poll_interval)
                continue

            desc_data = json.loads(res.stdout)
            status = desc_data.get("status", {}) if isinstance(desc_data, dict) else {}

            log_filter = f'labels."run.googleapis.com/execution_name"="{execution_name}" AND (textPayload:"[MILESTONE]" OR textPayload:"[STATUS:" OR textPayload:"[ALARM]")'
            log_cmd = [
                "gcloud",
                "logging",
                "read",
                log_filter,
                "--limit=1000",
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
                        seen_log_entries.add(line_str)
                        if "[ALARM]" in line_str or "POTENTIAL_LOOP" in line_str:
                            print(f"\033[91;1m[ALARM] >>> {line_str} <<<\033[0m", flush=True)
                        elif "WAITING_FOR_ORCHESTRATOR" in line_str:
                            print(f"[WAITING_FOR_ORCHESTRATOR] >>> {line_str} <<<", flush=True)
                        else:
                            print(line_str, flush=True)
            except Exception:
                pass

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
                if not isinstance(cond, dict):
                    continue
                c_type = cond.get("type")
                c_status = str(cond.get("status", "")).strip()
                c_msg = cond.get("message") or cond.get("reason") or ""
                if c_type == "Completed":
                    if c_status == "True":
                        is_completed = True
                        execution_succeeded = True
                        break
                    elif c_status == "False":
                        is_completed = True
                        execution_succeeded = False
                        failure_msg = c_msg or "Cloud Run execution condition Completed is False"
                        break
                elif c_type == "Failed" or "Fail" in str(c_type):
                    if c_status in ("True", "False"):
                        is_completed = True
                        execution_succeeded = False
                        failure_msg = c_msg or f"Cloud Run execution condition {c_type}={c_status}"
                        break

            if is_completed:
                if failed > 0 and execution_succeeded:
                    execution_succeeded = False
                    if not failure_msg:
                        failure_msg = f"{failed} task(s) failed in Cloud Run execution"

                log_filter = f'labels."run.googleapis.com/execution_name"="{execution_name}" AND (textPayload:"[STATUS:" OR textPayload:"[MILESTONE]" OR textPayload:"Score:" OR textPayload:"PASS" OR textPayload:"[ALARM]")'
                log_cmd = [
                    "gcloud",
                    "logging",
                    "read",
                    log_filter,
                    "--limit=2000",
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
                            seen_log_entries.add(line_str)
                            if "[ALARM]" in line_str or "POTENTIAL_LOOP" in line_str:
                                print(f"\033[91;1m[ALARM] >>> {line_str} <<<\033[0m", flush=True)
                            elif "WAITING_FOR_ORCHESTRATOR" in line_str:
                                print(f"[WAITING_FOR_ORCHESTRATOR] >>> {line_str} <<<", flush=True)
                            else:
                                print(line_str, flush=True)
                except Exception as exc:
                    print(f"Warning: Error reading completion logs: {exc}", file=sys.stderr)
                break

        except Exception as exc:
            print(f"Warning: Exception in monitor_execution: {exc}", file=sys.stderr)

        time.sleep(poll_interval)

    if not execution_succeeded and not failure_msg:
        failure_msg = "Execution did not complete successfully or condition was not met."

    return MonitorResult(desc_data, execution_succeeded, failure_msg)


wait_for_execution = monitor_execution


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
    base_branch: Optional[str] = None,
    gcs_bucket: Optional[str] = None,
    runtime: str = "cloud-run",
) -> None:
    print("[PRE-FLIGHT] Verifying cloud swarm credentials, quota tiers, repository access, and GCS bucket...", flush=True)

    if not dry_run and runtime == "cloud-run" and not gcs_bucket:
        raise RuntimeError(
            "Cloud Run swarms require a GCS bucket to store and deliver candidate patches under the zero-push architecture.\n"
            "Please specify --gcs-bucket <name> or configure 'gcs_bucket' in agystack-runtime.json."
        )

    if not vertex_location:
        vertex_location = "global" if model.startswith(("gemini-2.5", "gemini-3")) else region

    # 1. Git Authentication & Repository Accessibility Check
    if not repo_url:
        raise RuntimeError("Git repo URL could not be determined.")

    if not gh_token:
        raise RuntimeError(
            "GH_TOKEN could not be resolved from environment or `gh auth token`.\n"
            "Cloud swarm workers require a valid GitHub token to clone private repositories."
        )

    clean_url = clean_repo_url(repo_url)
    cred_helper = f"!f() {{ echo password={gh_token}; }}; f"
    probe_target = ["git", "-c", f"credential.helper={cred_helper}", "ls-remote"]
    if base_branch:
        probe_target.extend(["--heads", clean_url, base_branch])
    else:
        probe_target.extend([clean_url, "HEAD"])
    try:
        ls_res = subprocess.run(
            probe_target,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        if base_branch and not ls_res.stdout.strip():
            raise RuntimeError(
                f"Base branch '{base_branch}' not found on remote origin '{clean_repo_url(repo_url)}'.\n"
                f"Please verify the branch name and push it to remote before dispatching cloud swarm workers."
            )
        target_desc = f"base branch '{base_branch}'" if base_branch else "HEAD"
        print(f"  [PASS] Git remote authentication & repository accessibility verified ({repo_url}, {target_desc}).")
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
    parent_model: Optional[str] = None,
) -> str:
    parent = (
        (parent_model and parent_model.strip())
        or os.environ.get("ANTIGRAVITY_MODEL", "").strip()
        or os.environ.get("ACTIVE_PARENT_MODEL", "").strip()
        or os.environ.get("GEMINI_MODEL", "").strip()
        or None
    )

    if cli_model and cli_model.strip():
        chosen = cli_model.strip()
    elif runtime_model and runtime_model.strip() and runtime_model.strip().lower() not in (
        "inherit",
        "auto",
        "inherit-parent",
        "inherit_parent",
    ):
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
        chosen = role_model or (runtime_model.strip() if runtime_model and runtime_model.strip() else "inherit")

    default_model = parent or "gemini-3.8-flash"
    tier_map = {
        "flash": "gemini-3.8-flash",
        "pro": "gemini-3.1-pro",
        "flash_lite": "gemini-3.1-flash-lite",
        "flash-lite": "gemini-3.1-flash-lite",
        "inherit": default_model,
        "auto": default_model,
        "inherit-parent": default_model,
        "inherit_parent": default_model,
    }
    norm_chosen = chosen.lower().replace("_", "-")
    if chosen.lower() in tier_map:
        return tier_map[chosen.lower()]
    if norm_chosen in tier_map:
        return tier_map[norm_chosen]
    return chosen


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


def print_candidate_patches_table(
    harvested_patches: List[Dict[str, Any]],
    baseline_score: Optional[float] = None,
    exec_succeeded: bool = True,
    failed_count: int = 0,
    allow_partial: bool = False,
) -> None:
    if not harvested_patches:
        print("No candidate patches found.")
        return

    is_partial_failure = (not exec_succeeded) or (failed_count > 0)
    if is_partial_failure:
        print("\n" + "*" * 80)
        print(f"[WARNING: SWARM EXECUTION EXPERIENCED PARTIAL FAILURES: {failed_count} TASKS FAILED]")
        print("Some worker tasks failed during execution. Candidate patches below are from a")
        print("partial swarm run and should be carefully verified before promoting.")
        print("*" * 80)

    has_passing = any(
        p.get("status") == "PASS" and p.get("patch_file") and str(p.get("patch_file")) != "None"
        for p in harvested_patches
    )

    print("\n" + "=" * 80)
    print("CANDIDATE PATCHES (RANKED):")
    print("=" * 80)
    print(f"{'Rank':<6} | {'Task':<8} | {'Score':<8} | {'Delta':<10} | {'Status':<16} | {'Patch File'}")
    print("-" * 80)
    for idx, p in enumerate(harvested_patches):
        is_winner = (
            idx == 0
            and p.get("status") == "PASS"
            and bool(p.get("patch_file"))
            and str(p.get("patch_file")) != "None"
        )
        rank_str = f"{idx + 1}*" if (is_winner and not is_partial_failure) else str(idx + 1)
        task_id = p.get("task_index", "?")
        sc = p.get("score")
        sc_str = f"{sc:.2f}" if isinstance(sc, (int, float)) else "N/A"
        delta = p.get("score_delta")
        delta_str = f"{delta:+.4f}" if delta is not None else "N/A"
        st = p.get("status", "UNKNOWN")
        if is_partial_failure and not allow_partial:
            st = f"{st} [PARTIAL]"
        pf = p.get("patch_file") or "None"
        print(f"{rank_str:<6} | {task_id:<8} | {sc_str:<8} | {delta_str:<10} | {st:<16} | {pf}")
    print("=" * 80)
    if (
        harvested_patches
        and harvested_patches[0].get("status") == "PASS"
        and harvested_patches[0].get("patch_file")
        and str(harvested_patches[0].get("patch_file")) != "None"
    ):
        if (not is_partial_failure) or allow_partial:
            print(f"* Winning Candidate #1: {harvested_patches[0]['patch_file']} (apply and verify locally)")
            print("=" * 80)
        else:
            print("Notice: Winning candidate auto-promotion suppressed due to partial swarm failure.")
            print(f"Quarantined Candidate #1: {harvested_patches[0]['patch_file']} (review with caution)")
            print("=" * 80)
    elif not has_passing:
        print("Notice: No passing candidate patches produced.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch parallel Cloud Run swarm workers.")
    parser.add_argument("--manifest", type=str, help="Path to manifest JSON or JSON string.")
    parser.add_argument("--seed-lottery", type=int, help="Generate N coprime seed lottery tasks.")
    parser.add_argument("--gcs-bucket", type=str, help="GCS bucket name for run artifacts.")
    parser.add_argument("--gcs-prefix", type=str, default=None, help="GCS object prefix.")
    parser.add_argument("--harvest-gcs", type=str, help="GCS prefix to harvest results after execution.")
    parser.add_argument("--harvest-session", type=str, default=None, help="Harvest and rank candidate patches for an existing session ID from GCS without launching a new Cloud Run job")
    parser.add_argument("--wait-execution", type=str, default=None, help="Attach to a running Cloud Run execution, stream milestones, and harvest patches")
    parser.add_argument("--baseline-score", type=float, default=None, help="Baseline score float to compute score delta ranking against")
    parser.add_argument("--repo", type=str, help="Git repository URL.")
    parser.add_argument("--tasks", type=int, help="Task count override.")
    parser.add_argument("--parallelism", type=int, default=None, help="Concurrency limit (configured on Cloud Run Job template via setup_runtime.py; execute inherits template setting).")
    parser.add_argument("--max-retries", type=int, default=0, help="Max retry attempts per task (configured on Cloud Run Job template via setup_runtime.py; execute inherits template setting).")
    parser.add_argument("--job-name", type=str, help="Cloud Run Job name.")
    parser.add_argument("--region", type=str, help="GCP region (e.g. us-central1).")
    parser.add_argument("--project", type=str, help="GCP project ID.")
    parser.add_argument("--model", type=str, help="Model override for workers (default: inherit).")
    parser.add_argument("--parent-model", type=str, default=None, help="Parent session model to inherit in swarm workers.")
    parser.add_argument("--vertex", action="store_true", help="Enable Vertex AI mode.")
    parser.add_argument("--vertex-location", type=str, default=None, help="Vertex AI location (e.g. global or us-central1).")
    parser.add_argument("--preflight", action="store_true", help="Run pre-flight quota, auth, and git connectivity checks.")
    parser.add_argument("--no-preflight", action="store_true", help="Skip pre-flight checks.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload and command without executing.")
    parser.add_argument("--wait", dest="wait", action="store_true", help="Wait for job completion, stream milestones, and harvest reports (default).")
    parser.add_argument("--no-wait", dest="wait", action="store_false", help="Do not wait for job completion; dispatch asynchronously.")
    parser.add_argument("--session", "--session-id", dest="session_id", type=str, help="Swarm session ID (default: swarm-<timestamp>).")
    parser.add_argument("--orchestrator-timeout", type=float, default=600.0, help="Timeout in seconds for orchestrator replies (default: 600.0).")
    parser.add_argument("--set-secrets", type=str, help="Comma-separated secrets mapping for Cloud Run Job (e.g. GEMINI_API_KEY=gemini-key:latest).")
    parser.add_argument("--base-branch", type=str, default=None, help="Base branch for workers to checkout (default: remote default branch).")
    parser.add_argument("--ignore-partial-failures", action="store_true", help="Allow promotion of candidate patches from partially-failed swarm executions.")
    parser.set_defaults(wait=True)

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
    parallelism = args.parallelism if args.parallelism is not None else runtime_cfg.get("parallelism", 16)
    use_vertex = args.vertex or runtime_cfg.get("auth_mode") == "vertex" or runtime_cfg.get("vertex") is True
    model = resolve_swarm_model(
        cli_model=args.model,
        runtime_model=runtime_cfg.get("model"),
        parent_model=getattr(args, "parent_model", None),
    )
    vertex_location = args.vertex_location or runtime_cfg.get("vertex_location") or ("global" if model.startswith(("gemini-2.5", "gemini-3")) else region)
    gcs_bucket = args.gcs_bucket if args.gcs_bucket is not None else runtime_cfg.get("gcs_bucket", "")

    if args.harvest_session:
        session_id = args.harvest_session.strip()
        bkt = gcs_bucket or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        if not bkt:
            print("Error: GCS bucket name must be specified via --gcs-bucket, GCS_BUCKET, or agystack-runtime.json", file=sys.stderr)
            sys.exit(1)
        prefix = args.gcs_prefix or f"swarms/{session_id}"
        dest_dir = Path(".slices") / session_id
        try:
            from result_harvester import harvest_candidate_patches
            harvested_patches = harvest_candidate_patches(
                bucket_name=bkt,
                prefix=prefix,
                dest_dir=dest_dir,
                baseline_score=args.baseline_score,
                sort_by_delta=True,
            )
        except Exception as exc:
            print(f"Error: Failed to harvest GCS results for session {session_id}: {exc}", file=sys.stderr)
            sys.exit(1)

        print_candidate_patches_table(harvested_patches, baseline_score=args.baseline_score)
        return

    if args.wait_execution:
        execution_name = args.wait_execution.strip()
        session_id = args.session_id or os.environ.get("SWARM_SESSION_ID") or os.environ.get("SESSION_ID")
        if not session_id:
            recovered_session = recover_session_id_from_execution(
                execution_name=execution_name,
                region=region,
                project=project,
            )
            if recovered_session:
                session_id = recovered_session
            else:
                session_id = f"swarm-{int(time.time())}"

        bkt = gcs_bucket or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        task_count = args.tasks or 1
        print(f"Attaching to Cloud Run execution '{execution_name}' in region '{region}'...")
        desc_data, exec_succeeded, failure_msg = wait_for_execution(
            execution_name=execution_name,
            project=project,
            region=region,
            task_count=task_count,
        )
        if not exec_succeeded:
            print(f"Error: Cloud Run execution '{execution_name}' failed: {failure_msg}", file=sys.stderr)
        else:
            print("Job execution completed.")

        harvest_target = args.harvest_gcs or (args.gcs_prefix or (f"swarms/{session_id}" if bkt else None))
        harvested_patches = []
        if harvest_target is not None and bkt:
            try:
                from result_harvester import harvest_candidate_patches
                dest_dir = Path(".slices") / session_id
                harvested_patches = harvest_candidate_patches(
                    bucket_name=bkt,
                    prefix=harvest_target,
                    dest_dir=dest_dir,
                    baseline_score=args.baseline_score,
                    sort_by_delta=True,
                )
            except Exception as exc:
                print(f"Warning: Failed to harvest GCS results: {exc}", file=sys.stderr)

        if harvested_patches:
            failed_cnt = 0 if exec_succeeded else 1
            print_candidate_patches_table(
                harvested_patches,
                baseline_score=args.baseline_score,
                exec_succeeded=exec_succeeded,
                failed_count=failed_cnt,
                allow_partial=getattr(args, "ignore_partial_failures", False),
            )

        if not exec_succeeded:
            sys.exit(1)
        return

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
                base_branch=args.base_branch,
                gcs_bucket=gcs_bucket,
                runtime=runtime_cfg.get("runtime", "cloud-run"),
            )
        except RuntimeError as exc:
            print(f"Error [Pre-Flight]: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.preflight and not args.dry_run:
            print("Pre-flight checks passed successfully.")
            return

    secrets_mapping: Optional[Dict[str, str]] = None
    if getattr(args, "set_secrets", None):
        secrets_mapping = {}
        for part in args.set_secrets.split(","):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                secrets_mapping[k.strip()] = v.strip()
            elif part:
                secrets_mapping[part] = part
    elif runtime_cfg.get("secrets"):
        cfg_sec = runtime_cfg.get("secrets")
        if isinstance(cfg_sec, dict):
            secrets_mapping = dict(cfg_sec)
        elif isinstance(cfg_sec, str):
            secrets_mapping = {}
            for part in cfg_sec.split(","):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    secrets_mapping[k.strip()] = v.strip()
                elif part:
                    secrets_mapping[part] = part
        elif isinstance(cfg_sec, (list, tuple)):
            secrets_mapping = {}
            for part in cfg_sec:
                part = str(part).strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    secrets_mapping[k.strip()] = v.strip()
                elif part:
                    secrets_mapping[part] = part
    elif runtime_cfg.get("secrets_mapping"):
        cfg_sec = runtime_cfg.get("secrets_mapping")
        if isinstance(cfg_sec, dict):
            secrets_mapping = dict(cfg_sec)

    active_secret_keys = extract_secret_keys(secrets_mapping, getattr(args, "set_secrets", None))

    if not repo_url:
        print("Error: Git repo URL not provided and could not be inferred from remote.origin.url", file=sys.stderr)
        sys.exit(1)

    if not gh_token and "GH_TOKEN" not in active_secret_keys and "gh_token" not in active_secret_keys:
        print("Error: GH_TOKEN could not be resolved from environment or `gh auth token`", file=sys.stderr)
        sys.exit(1)

    if not use_vertex and not gemini_api_key and not args.dry_run and "GEMINI_API_KEY" not in active_secret_keys and "gemini_api_key" not in active_secret_keys:
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
    }
    if "GH_TOKEN" not in active_secret_keys and "gh_token" not in active_secret_keys and gh_token:
        env_vars["GH_TOKEN"] = gh_token

    if not use_vertex and "GEMINI_API_KEY" not in active_secret_keys and "gemini_api_key" not in active_secret_keys:
        if gemini_api_key:
            env_vars["GEMINI_API_KEY"] = gemini_api_key
        elif args.dry_run:
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
    if args.base_branch:
        env_vars["BASE_BRANCH"] = args.base_branch

    gcs_bucket = args.gcs_bucket if args.gcs_bucket is not None else runtime_cfg.get("gcs_bucket", "")
    gcs_prefix = args.gcs_prefix if args.gcs_prefix is not None else runtime_cfg.get("gcs_prefix")
    if not gcs_prefix and session_id:
        gcs_prefix = f"swarms/{session_id}"
    if gcs_bucket:
        env_vars["GCS_BUCKET"] = gcs_bucket
        env_vars["GCS_RESULTS_BUCKET"] = gcs_bucket
    if gcs_prefix:
        env_vars["GCS_PREFIX"] = gcs_prefix

    manifest_uri = None
    if gcs_bucket and manifest_serialized:
        manifest_uri = stage_manifest(
            manifest_data=tasks_list or manifest_serialized,
            bucket_name=gcs_bucket,
            session_id=session_id,
            dry_run=args.dry_run,
        )
        if manifest_uri:
            env_vars["MANIFEST_URI"] = manifest_uri
            if not args.dry_run:
                print(f"Staged swarm manifest at {manifest_uri}", flush=True)

    if not manifest_uri and manifest_serialized:
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
        secrets_mapping=secrets_mapping,
        set_secrets=getattr(args, "set_secrets", None),
        auth_mode="vertex" if use_vertex else "api_key",
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
            secrets_mapping=secrets_mapping,
            set_secrets=getattr(args, "set_secrets", None),
            auth_mode="vertex" if use_vertex else "api_key",
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
        if secrets_mapping:
            payload["secrets_mapping"] = secrets_mapping
        print(json.dumps(payload, indent=2))
        return

    if getattr(args, "set_secrets", None) and not args.dry_run:
        update_cmd = [
            "gcloud", "run", "jobs", "update", job_name,
            f"--region={region}",
            f"--set-secrets={args.set_secrets}",
        ]
        if project:
            update_cmd.append(f"--project={project}")
        try:
            print(f"Updating Cloud Run Job template '{job_name}' with secrets: {args.set_secrets}...")
            subprocess.run(update_cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"Error updating job secrets: {exc.stderr.strip()}", file=sys.stderr)
            sys.exit(exc.returncode)

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
                print(f"Session: {session_id}")
                print(f"To attach: python3 cloud_dispatch.py --wait-execution {execution_name} --session-id {session_id}")
            else:
                print("Dispatched Cloud Run Job execution asynchronously.")
                print(f"Session: {session_id}")
            return

        exec_succeeded = True
        exec_failure_msg = None
        if execution_name:
            print(f"Monitoring execution '{execution_name}' in region '{region}'...")
            _, exec_succeeded, exec_failure_msg = monitor_execution(
                execution_name=execution_name,
                project=project,
                region=region,
                task_count=task_count,
            )
            if not exec_succeeded:
                print(f"Error: Cloud Run execution '{execution_name}' failed: {exec_failure_msg}", file=sys.stderr)
            else:
                print("Job execution completed successfully.")
        else:
            print("Job execution completed.")

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

        harvest_target = args.harvest_gcs or (gcs_prefix if gcs_bucket else None)
        harvested_patches = []
        if harvest_target is not None and gcs_bucket:
            try:
                from result_harvester import harvest_gcs_results, harvest_candidate_patches

                dest_dir = Path(".slices") / session_id
                harvested_patches = harvest_candidate_patches(
                    bucket_name=gcs_bucket,
                    prefix=harvest_target,
                    dest_dir=dest_dir,
                    baseline_score=args.baseline_score,
                    sort_by_delta=True,
                )
            except Exception as exc:
                print(f"Warning: Failed to harvest GCS results: {exc}", file=sys.stderr)

        # Prioritize assembling report from harvested status.json files on GCS
        harvested_with_status = [p for p in harvested_patches if p.get("status_file") and p.get("status") != "UNKNOWN"]
        if harvested_with_status:
            report_items = harvested_patches
        else:
            report_items = parse_worker_logs(logs_content)

        print("\n" + "=" * 80)
        print(f"SWARM EXECUTION REPORT: {job_name}")
        print("=" * 80)
        print(f"{'Task':<8} | {'Status':<10} | {'Summary'}")
        print("-" * 80)
        pass_count = 0
        issues_count = 0
        blocked_count = 0

        for i, item in enumerate(report_items):
            task_id = item.get("task_index", i)
            st = item.get("status", "UNKNOWN")
            sm = item.get("summary", "").replace("\n", " ")[:60]
            if st == "PASS":
                pass_count += 1
            elif st == "ISSUES":
                issues_count += 1
            elif st == "BLOCKED":
                blocked_count += 1
            print(f"{task_id:<8} | {st:<10} | {sm}")

        if not report_items:
            print(f"Total tasks: {task_count}.")
            if execution_name:
                print(f"Execution: {execution_name}")
                print(f"No container logs returned yet. Run the following command to view traces:\n  {log_cmd_str}")
            else:
                print("Review Cloud Run console logs for per-container traces.")
        else:
            print("=" * 80)
            print(f"Total: {len(report_items)} | PASS: {pass_count} | ISSUES: {issues_count} | BLOCKED: {blocked_count}")
            print("=" * 80)

        failed_tasks_count = issues_count + blocked_count
        if not exec_succeeded and failed_tasks_count == 0:
            failed_tasks_count = 1

        if harvested_patches:
            print_candidate_patches_table(
                harvested_patches,
                baseline_score=args.baseline_score,
                exec_succeeded=exec_succeeded,
                failed_count=failed_tasks_count,
                allow_partial=getattr(args, "ignore_partial_failures", False),
            )

        if not exec_succeeded or failed_tasks_count > 0:
            print(f"\n[STATUS: EXECUTION_FAILED] ({failed_tasks_count}/{len(report_items) or task_count} tasks failed; patches harvested with quarantine)")
        else:
            print(f"\n[STATUS: EXECUTION_SUCCESS] (All {len(report_items) or task_count} tasks succeeded)")

        if not exec_succeeded:
            sys.exit(1)

    except subprocess.CalledProcessError as exc:
        err_out = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
        print(f"Error executing Cloud Run job: {err_out}", file=sys.stderr)
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
