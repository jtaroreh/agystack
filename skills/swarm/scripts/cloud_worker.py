#!/usr/bin/env python3
"""
Cloud worker entrypoint executed inside Cloud Run Job container instances.
Reads task parameters from environment, clones the repo on an isolated branch,
executes the task brief via Google Antigravity SDK Agent or direct command runner,
validates changes via verification command, commits and pushes candidate changes,
and outputs a structured report.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from storage_messenger import StorageMessenger
except ImportError:
    StorageMessenger = None


def emit_milestone(task_index: int, phase: str, detail: str = "") -> None:
    msg = f"[MILESTONE] [TASK {task_index}] [PHASE: {phase}]"
    if detail:
        msg += f" {detail}"
    print(msg, flush=True)


def create_ask_orchestrator_tool(
    messenger: Any,
    task_index: int,
    timeout_seconds: float = 600.0,
):
    async def ask_orchestrator(question: str, context: str = "") -> str:
        emit_milestone(task_index, "WAITING_FOR_ORCHESTRATOR", question[:80])
        envelope = messenger.send_question(question=question, context=context)
        reply = messenger.wait_for_reply(seq=envelope.seq, timeout_seconds=timeout_seconds)
        if reply is None:
            emit_milestone(
                task_index,
                "ORCHESTRATOR_TIMEOUT",
                f"Seq {envelope.seq} timed out. Proceeding autonomously.",
            )
            return (
                "Orchestrator did not respond within timeout. "
                "Use your best autonomous judgment and document your assumptions."
            )
        emit_milestone(task_index, "ORCHESTRATOR_REPLY_RECEIVED", f"Seq {envelope.seq}")
        return reply

    return ask_orchestrator


def get_env_var(name: str, default: Optional[str] = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and (val is None or val.strip() == ""):
        print(f"Error: Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return val if val is not None else ""


def download_manifest(manifest_uri: str) -> str:
    """
    Downloads manifest JSON content from a storage URI (e.g. gs://<bucket>/swarms/<session_id>/manifest.json)
    or local path.
    """
    uri = manifest_uri.strip()
    if uri.startswith("file://"):
        return Path(uri[7:]).read_text(encoding="utf-8")
    if os.path.isfile(uri):
        return Path(uri).read_text(encoding="utf-8")

    if not uri.startswith("gs://"):
        raise ValueError(f"Unsupported manifest URI scheme: {manifest_uri}")

    path_part = uri[5:]
    if "/" not in path_part:
        raise ValueError(f"Invalid GCS URI: {manifest_uri}")
    bucket_name, object_name = path_part.split("/", 1)

    # 1. Check local testing mock directory
    local_dir = os.environ.get("STORAGE_MESSENGER_LOCAL_DIR")
    if local_dir:
        local_file = Path(local_dir) / bucket_name / object_name
        if local_file.is_file():
            return local_file.read_text(encoding="utf-8")

    # 2. Try google.cloud.storage
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        return blob.download_as_text()
    except Exception:
        pass

    # 3. Try StorageMessenger client if available
    if StorageMessenger is not None:
        try:
            messenger = StorageMessenger(
                bucket_name=bucket_name,
                session_id="manifest-loader",
                is_worker=False,
            )
            blob = messenger.bucket.blob(object_name)
            if blob.exists():
                return blob.download_as_text()
        except Exception:
            pass

    # 4. Try REST with oauth token from storage_uploader
    token = None
    try:
        import storage_uploader

        token = storage_uploader.get_oauth_token()
    except Exception:
        pass

    if token:
        encoded_bucket = urllib.parse.quote(bucket_name, safe="")
        encoded_name = urllib.parse.quote(object_name, safe="")
        url = f"https://storage.googleapis.com/storage/v1/b/{encoded_bucket}/o/{encoded_name}?alt=media"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    return resp.read().decode("utf-8")
        except Exception:
            pass

    # 5. Try gcloud storage cp
    try:
        res = subprocess.run(
            ["gcloud", "storage", "cp", uri, "-"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if res.returncode == 0 and res.stdout:
            return res.stdout
    except Exception:
        pass

    raise RuntimeError(f"Failed to download manifest from {manifest_uri}")


def parse_task_manifest(
    manifest_raw: Optional[str] = None,
    task_index: int = 0,
    manifest_uri: Optional[str] = None,
) -> Tuple[Any, str]:
    if manifest_uri is None:
        manifest_uri = os.environ.get("MANIFEST_URI", "").strip()

    if manifest_uri and not (manifest_raw and manifest_raw.strip()):
        manifest_raw = download_manifest(manifest_uri)

    if manifest_raw is None:
        manifest_raw = os.environ.get("TASK_MANIFEST", "")

    if not manifest_raw.strip():
        task_brief_env = os.environ.get("TASK_BRIEF", "").strip()
        if task_brief_env:
            return task_brief_env, task_brief_env
        raise ValueError("Neither MANIFEST_URI, TASK_MANIFEST, nor TASK_BRIEF environment variable was set.")

    data = None
    if os.path.isfile(manifest_raw):
        with open(manifest_raw, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        try:
            data = json.loads(manifest_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse TASK_MANIFEST as JSON: {exc}") from exc

    if isinstance(data, list):
        if task_index < 0 or task_index >= len(data):
            raise IndexError(
                f"Task index {task_index} out of bounds for manifest containing {len(data)} tasks."
            )
        item = data[task_index]
    elif isinstance(data, dict):
        if "tasks" in data and isinstance(data["tasks"], list):
            tasks_list = data["tasks"]
            if task_index < 0 or task_index >= len(tasks_list):
                raise IndexError(
                    f"Task index {task_index} out of bounds for data['tasks'] ({len(tasks_list)} tasks)."
                )
            item = tasks_list[task_index]
        elif "briefs" in data and isinstance(data["briefs"], list):
            briefs_list = data["briefs"]
            if task_index < 0 or task_index >= len(briefs_list):
                raise IndexError(
                    f"Task index {task_index} out of bounds for data['briefs'] ({len(briefs_list)} tasks)."
                )
            item = briefs_list[task_index]
        else:
            item = data
    else:
        item = data

    if isinstance(item, str):
        return item, item
    if isinstance(item, dict):
        brief = item.get("brief") or item.get("prompt") or item.get("command") or json.dumps(item, indent=2)
        return item, brief
    return item, str(item)


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


def clone_and_checkout_task(
    repo_url: str,
    gh_token: str,
    branch_name: str,
    repo_dir: Path,
    depth: int = 50,
) -> None:
    """
    Clones the repository using authenticated credentials, scrubs credentials from remote.origin.url
    so tokens are not retained in plaintext in .git/config, configures git identity, and checks out the task branch.
    """
    repo_path = Path(repo_dir)
    clean_url = clean_repo_url(repo_url)
    git_env = os.environ.copy()
    if gh_token:
        git_env["GH_TOKEN"] = gh_token
        cred_helper = '!f() { echo "username=x-access-token"; echo "password=$GH_TOKEN"; }; f'
        cmd = [
            "git",
            "-c", f"credential.helper={cred_helper}",
            "clone",
            f"--depth={depth}",
            clean_url,
            str(repo_path),
        ]
    else:
        cmd = ["git", "clone", f"--depth={depth}", clean_url, str(repo_path)]
    run_command(cmd, env=git_env, check=True)
    run_command(["git", "remote", "set-url", "origin", clean_url], cwd=repo_path, check=True)
    run_command(["git", "config", "user.name", "Antigravity Cloud Worker"], cwd=repo_path, check=False)
    run_command(["git", "config", "user.email", "bot@antigravity.google"], cwd=repo_path, check=False)
    run_command(["git", "checkout", "-B", branch_name], cwd=repo_path, check=True)


def push_candidate_branch(
    repo_dir: Path,
    repo_url: str,
    branch_name: str,
    gh_token: str,
    fork_repo_url: str = "",
) -> None:
    if fork_repo_url:
        clean_fork_url = clean_repo_url(fork_repo_url)
        remotes = run_command(["git", "remote"], cwd=repo_dir, check=False).stdout.split()
        if "fork" in remotes:
            run_command(["git", "remote", "set-url", "fork", clean_fork_url], cwd=repo_dir, check=True)
        else:
            run_command(["git", "remote", "add", "fork", clean_fork_url], cwd=repo_dir, check=True)
        push_target = "fork"
    else:
        push_target = "origin"
        run_command(["git", "remote", "set-url", "origin", clean_repo_url(repo_url)], cwd=repo_dir, check=True)

    git_env = os.environ.copy()
    if gh_token:
        git_env["GH_TOKEN"] = gh_token
        cred_helper = '!f() { echo "username=x-access-token"; echo "password=$GH_TOKEN"; }; f'
        push_cmd = [
            "git",
            "-c", f"credential.helper={cred_helper}",
            "push",
            "-u", push_target, branch_name, "--force",
        ]
    else:
        push_cmd = ["git", "push", "-u", push_target, branch_name, "--force"]

    try:
        run_command(push_cmd, cwd=repo_dir, env=git_env, check=True)
    finally:
        run_command(["git", "remote", "set-url", "origin", clean_repo_url(repo_url)], cwd=repo_dir, check=False)
        if fork_repo_url:
            run_command(["git", "remote", "set-url", "fork", clean_repo_url(fork_repo_url)], cwd=repo_dir, check=False)


def run_command(
    cmd: List[str],
    cwd: Optional[Path] = None,
    check: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


class ScoreMetricsResult(tuple):
    def __new__(cls, score: Optional[float], accuracy: Optional[float], latency_ms: Optional[float]):
        return super().__new__(cls, (score, accuracy, latency_ms))

    @property
    def score(self) -> Optional[float]:
        return self[0]

    @property
    def accuracy(self) -> Optional[float]:
        return self[1]

    @property
    def latency_ms(self) -> Optional[float]:
        return self[2]

    def get(self, key: str, default: Any = None) -> Any:
        if key == "score":
            return self[0] if self[0] is not None else default
        elif key == "accuracy":
            return self[1] if self[1] is not None else default
        elif key == "latency_ms":
            return self[2] if self[2] is not None else default
        return default


def parse_score_metrics(
    repo_dir: Path,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    score_file = repo_dir / "score.json"
    if not score_file.is_file():
        return ScoreMetricsResult(None, None, None)
    try:
        with open(score_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        score = data.get("score")
        metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
        if score is None and "score" in metrics:
            score = metrics.get("score")
        accuracy = (
            data.get("accuracy")
            if data.get("accuracy") is not None
            else metrics.get("accuracy")
        )
        latency_ms = (
            data.get("latency_ms")
            if data.get("latency_ms") is not None
            else metrics.get("latency_ms")
        )
        return ScoreMetricsResult(score, accuracy, latency_ms)
    except Exception:
        return ScoreMetricsResult(None, None, None)


DEFAULT_EXCLUDED_EXACT = {
    ".git",
    ".agystack",
    ".agents",
}

DEFAULT_EXCLUDED_DIRS = (
    ".git",
    ".agents",
    ".agystack",
    "node_modules",
    "target",
    "vendor",
    ".cargo",
    "dist",
    "build",
    ".venv",
    "__pycache__",
)


def is_candidate_file(
    path: str,
    explicit_candidates: Optional[List[str]] = None,
    explicit_excludes: Optional[List[str]] = None,
) -> bool:
    clean = path.strip().strip('"').replace("\\", "/")
    if clean.startswith("./"):
        clean = clean[2:]

    # Check explicit excludes first if provided
    if explicit_excludes:
        for ex in explicit_excludes:
            clean_ex = ex.strip().strip('"').replace("\\", "/")
            if clean_ex.startswith("./"):
                clean_ex = clean_ex[2:]
            clean_ex = clean_ex.rstrip("/")
            if clean == clean_ex or clean.startswith(f"{clean_ex}/"):
                return False

    # Check explicit candidates if provided
    if explicit_candidates is not None:
        matched = False
        for cand in explicit_candidates:
            clean_cand = cand.strip().strip('"').replace("\\", "/")
            if clean_cand.startswith("./"):
                clean_cand = clean_cand[2:]
            clean_cand = clean_cand.rstrip("/")
            if clean == clean_cand or clean.startswith(f"{clean_cand}/"):
                matched = True
                break
        if not matched:
            return False

    # Check default exact excluded files
    if clean in DEFAULT_EXCLUDED_EXACT:
        return False

    # Check default excluded directory prefixes
    for d in DEFAULT_EXCLUDED_DIRS:
        if clean == d or clean.startswith(f"{d}/"):
            return False

    return True


def parse_porcelain_status(stdout: str) -> List[str]:
    modified_files: List[str] = []
    if not stdout or not stdout.strip():
        return modified_files
    for line in stdout.splitlines():
        if len(line) > 3:
            raw_path = line[3:].strip()
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ")[-1].strip()
            if raw_path:
                modified_files.append(raw_path)
    return modified_files


def evaluate_agent_status(agent_text: str) -> Tuple[str, str]:
    upper_text = agent_text.upper()
    if (
        "[STATUS: FAIL]" in upper_text
        or "COMPLETION SUMMARY: FAIL" in upper_text
        or "STATUS: FAIL" in upper_text
        or "PASS" not in upper_text
    ):
        return "ISSUES", agent_text
    return "PASS", agent_text


def execute_task(
    task_item: Any,
    task_brief: str,
    repo_dir: Path,
    model_override: str,
    api_key: str,
    use_vertex: bool = False,
    project: Optional[str] = None,
    location: Optional[str] = None,
    task_index: int = 0,
    messenger: Optional[Any] = None,
    orchestrator_timeout: float = 600.0,
) -> Tuple[str, str]:
    task_type = "agent"
    if isinstance(task_item, dict):
        task_type = task_item.get("type", "agent")

    # Command execution runner
    if task_type == "command":
        cmd_str = ""
        if isinstance(task_item, dict):
            cmd_str = task_item.get("command", "")
        if not cmd_str:
            cmd_str = task_brief

        emit_milestone(task_index, "RUNNING_COMMAND", cmd_str)
        print(f"Executing command task: {cmd_str}", flush=True)
        res = subprocess.run(
            cmd_str,
            shell=True,
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return "PASS", res.stdout
        else:
            err_msg = res.stderr if res.stderr else res.stdout
            return "ISSUES", err_msg

    # General Agent Execution using Google Antigravity SDK
    emit_milestone(task_index, "RUNNING_AGENT", "Antigravity SDK agent")
    try:
        import asyncio
        import google.antigravity as antigravity
        from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig, policy

        capabilities = CapabilitiesConfig(
            allow_file_write=True,
            allow_shell_commands=True,
            allow_subagents=False,
        )
        resolved_model = model_override.strip() if model_override.strip() else "gemini-3.8-flash"
        policies = [policy.allow_all()]

        custom_tools = []
        if messenger:
            ask_tool = create_ask_orchestrator_tool(
                messenger=messenger,
                task_index=task_index,
                timeout_seconds=orchestrator_timeout,
            )
            custom_tools.append(ask_tool)

        config_kwargs = {
            "model": resolved_model,
            "capabilities": capabilities,
            "workspace_dir": str(repo_dir),
            "policies": policies,
        }
        if custom_tools:
            config_kwargs["custom_tools"] = custom_tools

        if use_vertex:
            resolved_project = (
                project
                or os.environ.get("VERTEXAI_PROJECT")
                or os.environ.get("GCP_PROJECT")
                or os.environ.get("PROJECT_ID")
            )
            resolved_location = (
                location
                or os.environ.get("VERTEXAI_LOCATION")
                or os.environ.get("GCP_REGION")
                or os.environ.get("REGION")
                or "us-central1"
            )
            config_kwargs["vertex"] = True
            config_kwargs["project"] = resolved_project
            config_kwargs["location"] = resolved_location
            if api_key:
                config_kwargs["api_key"] = api_key
        else:
            config_kwargs["api_key"] = api_key

        try:
            config = LocalAgentConfig(**config_kwargs)
        except TypeError:
            config_kwargs.pop("custom_tools", None)
            config = LocalAgentConfig(**config_kwargs)

        async def _run_agent_turn() -> str:
            async with Agent(config=config) as agent:
                resp = await agent.chat(task_brief)
                return await resp.text()

        agent_text = asyncio.run(_run_agent_turn())
        return evaluate_agent_status(agent_text)
    except ImportError:
        return "BLOCKED", "Missing dependency: google.antigravity Python package is not installed."
    except Exception as exc:
        return "ISSUES", f"Agent execution exception: {exc}"


def main() -> None:
    task_index_str = os.environ.get("CLOUD_RUN_TASK_INDEX", "0")
    try:
        task_index = int(task_index_str)
    except ValueError:
        task_index = 0

    emit_milestone(task_index, "BOOTING")

    manifest_uri = os.environ.get("MANIFEST_URI", "").strip()
    manifest_raw = os.environ.get("TASK_MANIFEST", "")
    repo_url = get_env_var("REPO_URL", required=True)
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not gh_token:
        emit_milestone(task_index, "COMPLETE", "BLOCKED")
        print("[STATUS: BLOCKED]\nEvidence: Missing GH_TOKEN\nSummary: Cannot authenticate git clone without GH_TOKEN.", flush=True)
        sys.exit(1)

    use_vertex = os.environ.get("USE_VERTEX_AI", "").lower() in ("1", "true", "yes")
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not use_vertex and not gemini_api_key:
        emit_milestone(task_index, "COMPLETE", "BLOCKED")
        print(
            "[STATUS: BLOCKED]\nEvidence: Missing authentication. Neither USE_VERTEX_AI nor GEMINI_API_KEY is provided.\nSummary: Authentication configuration error.",
            flush=True,
        )
        sys.exit(1)

    project = os.environ.get("VERTEXAI_PROJECT") or os.environ.get("GCP_PROJECT") or os.environ.get("PROJECT_ID")
    location = os.environ.get("VERTEXAI_LOCATION") or os.environ.get("GCP_REGION") or os.environ.get("REGION")
    model_override = os.environ.get("MODEL_OVERRIDE", "")
    branch_name = f"worker-{task_index}"

    try:
        task_item, task_brief = parse_task_manifest(
            manifest_raw=manifest_raw,
            task_index=task_index,
            manifest_uri=manifest_uri,
        )
    except Exception as exc:
        emit_milestone(task_index, "COMPLETE", "BLOCKED")
        print(
            f"[STATUS: BLOCKED]\nEvidence: Failed to parse task brief for index {task_index}: {exc}\nSummary: Manifest resolution failure.",
            flush=True,
        )
        sys.exit(1)

    work_base = Path("/workspace") if Path("/workspace").exists() else Path(tempfile.gettempdir())
    repo_dir = work_base / f"repo-task-{task_index}"
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
    repo_dir.mkdir(parents=True, exist_ok=True)

    emit_milestone(task_index, "CLONING_REPO")
    try:
        clone_and_checkout_task(
            repo_url=repo_url,
            gh_token=gh_token,
            branch_name=branch_name,
            repo_dir=repo_dir,
        )
    except subprocess.CalledProcessError as exc:
        emit_milestone(task_index, "COMPLETE", "BLOCKED")
        err_msg = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
        print(
            f"[STATUS: BLOCKED]\nEvidence: git clone failed with code {exc.returncode}: {err_msg.strip()}\nSummary: Failed to clone repository.",
            flush=True,
        )
        sys.exit(1)

    os.chdir(repo_dir)
    emit_milestone(task_index, "REPO_READY")

    # Repository bootstrap hook: check for .agystack/setup.sh or .agents/scripts/bootstrap-worker.sh
    bootstrap_hooks = [
        repo_dir / ".agystack" / "setup.sh",
        repo_dir / ".agents" / "scripts" / "bootstrap-worker.sh",
    ]
    for hook in bootstrap_hooks:
        if hook.is_file():
            emit_milestone(task_index, "BOOTSTRAP_HOOK", str(hook.relative_to(repo_dir)))
            print(f"Executing repository bootstrap hook: {hook}", flush=True)
            hook_proc = subprocess.run(
                ["bash", str(hook)],
                cwd=repo_dir,
                capture_output=True,
                text=True,
            )
            if hook_proc.returncode != 0:
                print(f"Warning: Bootstrap hook {hook.name} exited with code {hook_proc.returncode}:\n{hook_proc.stderr}", file=sys.stderr)
            else:
                print(f"Bootstrap hook {hook.name} completed successfully.", flush=True)
            break

    gcs_bucket = (
        os.environ.get("GCS_BUCKET", "").strip()
        or os.environ.get("GCS_RESULTS_BUCKET", "").strip()
    )
    session_id = (
        os.environ.get("SWARM_SESSION_ID", "").strip()
        or os.environ.get("SESSION_ID", "").strip()
        or "default"
    )
    timeout_str = os.environ.get("ORCHESTRATOR_TIMEOUT", "").strip()
    try:
        orchestrator_timeout = float(timeout_str) if timeout_str else 600.0
    except ValueError:
        orchestrator_timeout = 600.0

    messenger = None
    if gcs_bucket and StorageMessenger is not None:
        try:
            messenger = StorageMessenger(
                bucket_name=gcs_bucket,
                session_id=session_id,
                task_index=task_index,
                is_worker=True,
            )
        except Exception as exc:
            print(f"Warning: Failed to initialize StorageMessenger: {exc}", file=sys.stderr)

    agent_status, agent_summary = execute_task(
        task_item=task_item,
        task_brief=task_brief,
        repo_dir=repo_dir,
        model_override=model_override,
        api_key=gemini_api_key,
        use_vertex=use_vertex,
        project=project,
        location=location,
        task_index=task_index,
        messenger=messenger,
        orchestrator_timeout=orchestrator_timeout,
    )

    if agent_status == "BLOCKED":
        emit_milestone(task_index, "COMPLETE", "BLOCKED")
        print("=" * 80)
        print("[STATUS: BLOCKED]")
        print("Evidence:")
        print(f"- Task Index: {task_index}")
        print(f"- Branch: {branch_name}")
        print("- Commit SHA: N/A")
        print("- Changes Pushed: False")
        print("- Diff Stat:\nExecution blocked before changes.")
        print("Summary:")
        print(agent_summary.strip())
        print("=" * 80, flush=True)
        sys.exit(1)

    score, accuracy, latency_ms = parse_score_metrics(repo_dir)
    gcs_bucket = os.environ.get("GCS_RESULTS_BUCKET", "").strip()
    gcs_prefix = os.environ.get("GCS_PREFIX", "").strip()
    gcs_uris: Dict[str, str] = {}

    commit_sha = ""
    diff_stat = ""
    changes_detected = False
    changes_pushed = False
    push_error: Optional[str] = None

    # Inspect git modifications
    status_res = run_command(["git", "status", "--porcelain"], cwd=repo_dir, check=False)
    modified_files = parse_porcelain_status(status_res.stdout) if status_res.returncode == 0 else []

    explicit_candidates = None
    explicit_excludes = None
    if isinstance(task_item, dict):
        explicit_candidates = task_item.get("candidate_files")
        explicit_excludes = task_item.get("exclude_files")

    candidate_files = [
        f for f in modified_files
        if is_candidate_file(f, explicit_candidates=explicit_candidates, explicit_excludes=explicit_excludes)
    ]

    verify_cmd_str = None
    if isinstance(task_item, dict):
        verify_cmd_str = task_item.get("verify_command")
    if not verify_cmd_str:
        verify_cmd_str = os.environ.get("DEFAULT_VERIFY_COMMAND", "").strip() or None

    # Check steering messages before verification and commit
    steer_messages: List[str] = []
    if messenger:
        try:
            steer_envelopes = messenger.check_steer_instructions()
            for s_env in steer_envelopes:
                instruction = s_env.payload.get("instruction") or s_env.payload.get("text") or ""
                if instruction:
                    steer_messages.append(instruction)
                    emit_milestone(task_index, "STEER_RECEIVED", instruction[:80])
        except Exception as exc:
            print(f"Warning: Failed to check steer instructions: {exc}", file=sys.stderr)

    if steer_messages:
        steer_summary = "; ".join(steer_messages)
        agent_summary += f"\n[Steering Instructions Applied]: {steer_summary}"
        print(f"Notice: Applied {len(steer_messages)} steering instruction(s): {steer_summary}", flush=True)

    # Prevent ghost commits: Only commit and push when agent_status == "PASS" and candidate files exist
    if agent_status == "PASS" and candidate_files:
        emit_milestone(task_index, "VALIDATING_CANDIDATE")
        if verify_cmd_str:
            print(f"Running verification command: {verify_cmd_str}", flush=True)
            test_check = subprocess.run(
                verify_cmd_str,
                shell=True,
                cwd=repo_dir,
                capture_output=True,
                text=True,
            )
            if test_check.returncode != 0:
                agent_status = "ISSUES"
                err_snippet = (test_check.stderr.strip() or test_check.stdout.strip())[-500:]
                diff_stat = f"Commit rejected: Candidate failed verification command (exit code {test_check.returncode}): {err_snippet}"
                print(f"Warning: Candidate modifications failed verification command (exit code {test_check.returncode}). Commit blocked.", file=sys.stderr)

        if agent_status == "PASS":
            try:
                for cand_file in candidate_files:
                    run_command(["git", "add", "--", cand_file], cwd=repo_dir, check=True)
                cached_diff = run_command(["git", "diff", "--cached", "--name-only"], cwd=repo_dir, check=False)
                if not cached_diff.stdout.strip():
                    diff_stat = "Commit skipped: No candidate changes staged."
                    print("Notice: No candidate changes staged; skipping git commit and push.", file=sys.stderr)
                else:
                    changes_detected = True
                    commit_msg = f"worker-{task_index}: execute swarm brief"
                    run_command(["git", "commit", "-m", commit_msg], cwd=repo_dir, check=True)
                    commit_res = run_command(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True)
                    commit_sha = commit_res.stdout.strip()
                    diff_res = run_command(["git", "diff", "--stat", "HEAD~1", "HEAD"], cwd=repo_dir, check=False)
                    diff_stat = diff_res.stdout.strip()
            except subprocess.CalledProcessError as exc:
                err_msg = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
                print(f"Warning: Git commit preparation failed: {err_msg.strip()}", file=sys.stderr)
    elif agent_status != "PASS":
        diff_stat = f"Commit skipped: worker status is {agent_status} (PASS required; ghost commits prohibited)."
        print(f"Notice: Agent status is {agent_status}. Skipping git commit and push.", file=sys.stderr)
    else:
        diff_stat = "Commit skipped: No candidate files modified outside bootstrap scaffolding."
        print("Notice: No candidate modifications outside bootstrap files; skipping git commit and push.", file=sys.stderr)

    if gcs_bucket:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import storage_uploader

            gcs_uris = storage_uploader.upload_run_artifacts(
                bucket_name=gcs_bucket,
                prefix=gcs_prefix,
                repo_dir=repo_dir,
                task_index=task_index,
            )
        except Exception as exc:
            print(f"Warning: GCS upload failed: {exc}", file=sys.stderr)

    if changes_detected:
        fork_repo_url = os.environ.get("FORK_REPO_URL", "").strip()
        try:
            emit_milestone(task_index, "PUSHING_CANDIDATE")
            push_candidate_branch(
                repo_dir=repo_dir,
                repo_url=repo_url,
                branch_name=branch_name,
                gh_token=gh_token,
                fork_repo_url=fork_repo_url,
            )
            changes_pushed = True
        except subprocess.CalledProcessError as exc:
            push_error = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
            changes_pushed = False

    has_gcs_results = bool(gcs_uris) or bool(gcs_bucket)
    has_score_json = (repo_dir / "score.json").is_file()

    if push_error:
        if has_gcs_results or has_score_json:
            print(
                f"Notice: Git push failed ({push_error.strip()}), but result evidence was preserved via GCS/score.json.",
                file=sys.stderr,
            )
        else:
            emit_milestone(task_index, "COMPLETE", "ISSUES")
            print(
                f"[STATUS: ISSUES]\nEvidence: Git commit or push failed: {push_error.strip()}\nSummary: Agent completed execution but branch push failed.",
                flush=True,
            )
            sys.exit(0)

    final_status = agent_status
    emit_milestone(task_index, "COMPLETE", final_status)
    print("=" * 80)
    print(f"[STATUS: {final_status}]")
    print("Evidence:")
    print(f"- Task Index: {task_index}")
    print(f"- Branch: {branch_name}")
    print(f"- Commit SHA: {commit_sha or 'N/A'}")
    print(f"- Changes Pushed: {changes_pushed}")
    if score is not None:
        print(f"- Score: {score}")
    if accuracy is not None:
        print(f"- Accuracy: {accuracy}")
    if latency_ms is not None:
        print(f"- Latency: {latency_ms}ms")
    score_file = repo_dir / "score.json"
    if score_file.is_file():
        try:
            score_data = score_file.read_text(encoding="utf-8").strip()
            print(f"- Slice JSON: {json.dumps(json.loads(score_data))}")
        except Exception:
            pass
    if gcs_uris:
        print(f"- GCS Artifacts: {json.dumps(gcs_uris)}")
    if push_error:
        print(f"- Push Status: Rejected (non-fatal, results captured)\n- Push Error: {push_error.strip()}")
    print(f"- Diff Stat:\n{diff_stat}")
    print("Summary:")
    print(agent_summary.strip())
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
