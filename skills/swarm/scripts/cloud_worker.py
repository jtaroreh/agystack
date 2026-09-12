#!/usr/bin/env python3
"""
Cloud worker entrypoint executed inside Cloud Run Job container instances.
Reads task parameters from environment, clones the repo on an isolated branch,
executes the task brief via Google Antigravity SDK Agent or direct command runner,
validates changes via verification command, commits candidate changes locally,
delivers candidate patches via GCS under zero-push architecture,
and outputs a structured report.
"""

from dataclasses import dataclass, field
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from storage_messenger import StorageMessenger
except ImportError:
    StorageMessenger = None

POTETO_WORKER_SYSTEM_PROMPT = """You are a specialized poteto coding delegate for agystack executing inside an isolated cloud worker container.
You implement surgical code edits, run test suites, verify outputs, and keep code and diffs clean and unslopped.

Guidelines:
1. Implement the requested task directly and surgically in the workspace.
2. Maintain high engineering rigor: run test suites and verification commands before completing.
3. Keep diffs minimal and clean. Avoid narrating comments or speculative code.
4. Conclude with a clear summary and status ([STATUS: PASS] or [STATUS: ISSUES]).
"""


def emit_milestone(task_index: int, phase: str, detail: str = "") -> None:
    msg = f"[MILESTONE] [TASK {task_index}] [PHASE: {phase}]"
    if detail:
        msg += f" {detail}"
    print(msg, flush=True)


@dataclass
class ToolInvocationRecord:
    tool_name: str
    args_hash: str
    output_hash: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_s: float = 0.0
    success: bool = True
    args_summary: str = ""

    @classmethod
    def create(cls, tool_name: str, args: Any = None) -> "ToolInvocationRecord":
        args = args if args is not None else {}
        try:
            canonical = json.dumps(args, sort_keys=True, default=str)
        except Exception:
            canonical = str(args)
        args_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        if isinstance(args, dict):
            args_summary = ", ".join(f"{k}={v!r}" for k, v in args.items())
        else:
            args_summary = str(args)
        return cls(
            tool_name=tool_name,
            args_hash=args_hash,
            output_hash="",
            timestamp=time.time(),
            duration_s=0.0,
            success=True,
            args_summary=args_summary,
        )


class StagnancyTracker:
    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self.window: List[ToolInvocationRecord] = []
        self._last_key: Optional[Tuple[str, str]] = None
        self._consecutive_count: int = 0

    def record_start(self, record: Any) -> Tuple[bool, int, str]:
        try:
            if not isinstance(record, ToolInvocationRecord):
                return False, 1, ""

            key = (record.tool_name, record.args_hash)
            if self._last_key == key:
                self._consecutive_count += 1
            else:
                self._last_key = key
                self._consecutive_count = 1

            self.window.append(record)
            if len(self.window) > self.window_size:
                self.window.pop(0)

            is_stagnant = self._consecutive_count >= 3
            warning = ""
            if is_stagnant:
                warning = (
                    f"Warning: Tool '{record.tool_name}' has been executed {self._consecutive_count} "
                    f"consecutive times with identical arguments. You may be stuck in a loop; "
                    f"consider trying an alternative tool or different parameters."
                )
            return is_stagnant, self._consecutive_count, warning
        except Exception:
            return False, 1, ""

    def record_result(
        self,
        tool_name: str,
        args_hash: str,
        output: Any,
        success: bool,
        duration_s: float,
    ) -> None:
        try:
            out_str = output if isinstance(output, str) else str(output)
            out_hash = hashlib.sha256(out_str.encode("utf-8")).hexdigest()[:12]
            for rec in reversed(self.window):
                if rec.tool_name == tool_name and rec.args_hash == args_hash:
                    rec.output_hash = out_hash
                    rec.success = success
                    rec.duration_s = duration_s
                    break
        except Exception:
            pass


def create_agent_hooks(
    messenger: Optional[Any],
    task_index: int,
    tracker: StagnancyTracker,
    hooks_module: Optional[Any] = None,
    types_module: Optional[Any] = None,
) -> List[Any]:
    h = hooks_module
    t = types_module
    if h is None or t is None:
        try:
            from google.antigravity.hooks import hooks as mod_hooks
            from google.antigravity import types as mod_types

            h = h or mod_hooks
            t = t or mod_types
        except (ImportError, AttributeError):
            pass

    if h is None or t is None:
        return []

    in_flight: List[Dict[str, Any]] = []

    @h.pre_tool_call_decide
    async def pre_tool_call_decide(tool_call: Any) -> Any:
        steer_context = None
        if messenger and hasattr(messenger, "check_steer_instructions"):
            try:
                steer_envelopes = messenger.check_steer_instructions() or []
            except Exception:
                steer_envelopes = []
            for item in steer_envelopes:
                instruction = ""
                if isinstance(item, str):
                    instruction = item
                elif isinstance(item, dict):
                    instruction = item.get("instruction") or item.get("text") or ""
                elif hasattr(item, "payload") and isinstance(item.payload, dict):
                    instruction = item.payload.get("instruction") or item.payload.get("text") or ""
                elif hasattr(item, "instruction"):
                    instruction = getattr(item, "instruction", "")

                if not instruction:
                    continue

                trimmed = instruction.strip()
                if trimmed.startswith("ABORT") or trimmed.startswith("CANCEL"):
                    emit_milestone(task_index, "ABORT_REQUESTED", instruction)
                    try:
                        return t.HookResult(
                            allow=False,
                            error_message=f"Execution aborted by orchestrator: {instruction}",
                        )
                    except TypeError:
                        return t.HookResult(allow=False)
                else:
                    emit_milestone(task_index, "STEER_APPLIED", instruction)
                    steer_context = instruction

        tool_name = getattr(tool_call, "name", "tool")
        tool_args = getattr(tool_call, "args", {})
        record = ToolInvocationRecord.create(tool_name, tool_args)
        is_stagnant, count, warning = tracker.record_start(record)
        in_flight.append({
            "tool_name": tool_name,
            "args_hash": record.args_hash,
            "t0": time.time(),
            "id": id(tool_call),
        })

        emit_milestone(task_index, "TOOL_START", f"{tool_name}: {record.args_summary[:60]}")

        if is_stagnant:
            emit_milestone(task_index, "POTENTIAL_LOOP", f"{tool_name} (repeated {count}x)")
            print(
                f"[ALARM] [TASK {task_index}] [POTENTIAL_LOOP] Tool '{tool_name}' repeated {count} times with identical inputs.",
                flush=True,
            )
            try:
                return t.HookResult(allow=True, custom_context=warning)
            except TypeError:
                return t.HookResult(allow=True)

        if steer_context:
            try:
                return t.HookResult(allow=True, custom_context=steer_context)
            except TypeError:
                return t.HookResult(allow=True)

        return t.HookResult(allow=True)

    @h.post_tool_call
    async def post_tool_call(data: Any) -> None:
        matched = None
        call_obj = getattr(data, "call", None)
        data_id = getattr(data, "id", None) or (getattr(call_obj, "id", None) if call_obj else None)
        data_name = getattr(data, "name", getattr(data, "tool_name", None))
        if data_name is None and call_obj is not None:
            data_name = getattr(call_obj, "name", getattr(call_obj, "tool_name", None))

        match_idx = -1
        for idx, entry in enumerate(in_flight):
            if data_id is not None and entry.get("id") == data_id:
                match_idx = idx
                break
            if entry.get("id") == id(data) or (call_obj is not None and entry.get("id") == id(call_obj)):
                match_idx = idx
                break
            if data_name and entry.get("tool_name") == data_name:
                match_idx = idx
                break

        if match_idx != -1:
            matched = in_flight.pop(match_idx)
        elif in_flight:
            matched = in_flight.pop(0)

        if matched:
            tool_name = matched["tool_name"]
            args_hash = matched["args_hash"]
            t0 = matched.get("t0")
            duration_s = max(0.0, time.time() - t0) if t0 is not None else 0.0
        else:
            tool_name = getattr(data, "name", getattr(data, "tool_name", "tool"))
            args_hash = ""
            duration_s = 0.0

        output = getattr(data, "output", getattr(data, "result", data))
        error = getattr(data, "error", None)
        success = (error is None) and not isinstance(data, Exception)

        tracker.record_result(tool_name, args_hash, output, success, duration_s)
        emit_milestone(task_index, "TOOL_END", f"{tool_name} in {duration_s:.1f}s")

    hooks_to_register = [pre_tool_call_decide, post_tool_call]
    if hasattr(h, "on_tool_error"):
        @h.on_tool_error
        async def on_tool_error(error: Any) -> Any:
            if in_flight:
                matched = in_flight.pop(0)
                t0 = matched.get("t0")
                duration_s = max(0.0, time.time() - t0) if t0 is not None else 0.0
                tracker.record_result(
                    matched["tool_name"],
                    matched["args_hash"],
                    str(error),
                    False,
                    duration_s,
                )
                emit_milestone(task_index, "TOOL_ERROR", f"{matched['tool_name']}: {str(error)[:60]}")
            else:
                emit_milestone(task_index, "TOOL_ERROR", str(error)[:80])
            return None
        hooks_to_register.append(on_tool_error)

    return hooks_to_register


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


def resolve_worker_branch(
    task_item: Any,
    task_index: int,
    session_id: Optional[str] = None,
) -> str:
    explicit_branch = task_item.get("branch") if isinstance(task_item, dict) else None
    if explicit_branch and str(explicit_branch).strip():
        return str(explicit_branch).strip()

    if session_id is None:
        session_id = (
            os.environ.get("SWARM_SESSION_ID")
            or os.environ.get("SESSION_ID")
            or ""
        ).strip()
    else:
        session_id = str(session_id).strip()

    if session_id:
        return f"agystack/{session_id}/worker-{task_index}"
    return f"worker-{task_index}"


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
    base_branch: Optional[str] = None,
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
        ]
    else:
        cmd = ["git", "clone", f"--depth={depth}"]
    if base_branch:
        cmd.extend(["--branch", base_branch])
    cmd.extend([clean_url, str(repo_path)])
    run_command(cmd, env=git_env, check=True)
    run_command(["git", "remote", "set-url", "origin", clean_url], cwd=repo_path, check=True)
    run_command(["git", "config", "user.name", "Antigravity Cloud Worker"], cwd=repo_path, check=False)
    run_command(["git", "config", "user.email", "bot@antigravity.google"], cwd=repo_path, check=False)
    run_command(["git", "checkout", "-B", branch_name], cwd=repo_path, check=True)


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
    match = re.search(r"\[STATUS:\s*(PASS|ISSUES|BLOCKED|DEV_IMPROVED)\s*\]", agent_text, re.IGNORECASE)
    if match:
        st = match.group(1).upper()
        if st == "DEV_IMPROVED":
            return "PASS", agent_text
        return st, agent_text
    return "ISSUES", agent_text


def resolve_worker_model(raw_model: Optional[str] = None, task_item: Any = None) -> str:
    """
    Resolves the worker model for a task, respecting per-task overrides in task_item,
    explicit raw_model / MODEL_OVERRIDE, and resolving tier aliases ('auto', 'inherit',
    'inherit-parent', 'flash', 'flash_lite', 'flash-lite', 'pro').
    """
    candidate = ""
    if (
        isinstance(task_item, dict)
        and task_item.get("model")
        and isinstance(task_item["model"], str)
        and task_item["model"].strip()
    ):
        candidate = task_item["model"].strip()
    elif raw_model and raw_model.strip():
        candidate = raw_model.strip()
    else:
        candidate = os.environ.get("MODEL_OVERRIDE", "").strip()

    default_model = (
        os.environ.get("DEFAULT_SWARM_MODEL", "").strip()
        or os.environ.get("DEFAULT_MODEL", "").strip()
        or "gemini-3.8-flash"
    )

    alias_map = {
        "flash": "gemini-3.8-flash",
        "pro": "gemini-3.1-pro",
        "flash_lite": "gemini-3.1-flash-lite",
        "flash-lite": "gemini-3.1-flash-lite",
        "auto": default_model,
        "inherit": default_model,
        "inherit-parent": default_model,
        "inherit_parent": default_model,
        "": default_model,
    }

    norm = candidate.lower()
    if norm in alias_map:
        return alias_map[norm]
    norm_hyphen = norm.replace("_", "-")
    if norm_hyphen in alias_map:
        return alias_map[norm_hyphen]
    return candidate


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
        timeout = int(os.environ.get("COMMAND_TIMEOUT", "900"))
        try:
            res = subprocess.run(
                cmd_str,
                shell=True,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if res.returncode == 0:
                return "PASS", res.stdout
            else:
                err_msg = res.stderr if res.stderr else res.stdout
                return "ISSUES", err_msg
        except subprocess.TimeoutExpired:
            return "ISSUES", f"Command timed out after {timeout} seconds: {cmd_str}"

    # General Agent Execution using Google Antigravity SDK
    resolved_model = resolve_worker_model(raw_model=model_override, task_item=task_item)
    emit_milestone(task_index, "RUNNING_AGENT", f"Antigravity SDK agent ({resolved_model})")
    try:
        import asyncio
        import google.antigravity as antigravity
        from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig, policy
        try:
            from google.antigravity.hooks import hooks
            from google.antigravity import types
        except (ImportError, AttributeError):
            hooks = None
            types = None

        capabilities = CapabilitiesConfig(
            allow_file_write=True,
            allow_shell_commands=True,
            allow_subagents=False,
        )
        policies = [policy.allow_all()]

        tracker = StagnancyTracker()
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
            "system_prompt": os.environ.get("AGYSTACK_WORKER_SYSTEM_PROMPT") or POTETO_WORKER_SYSTEM_PROMPT,
        }
        if custom_tools:
            config_kwargs["custom_tools"] = custom_tools

        if hooks is not None and types is not None:
            agent_hooks = create_agent_hooks(
                messenger=messenger,
                task_index=task_index,
                tracker=tracker,
                hooks_module=hooks,
                types_module=types,
            )
            if agent_hooks:
                config_kwargs["hooks"] = agent_hooks

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
        except TypeError as exc:
            emit_milestone(task_index, "AGENT_FALLBACK", f"Dropped optional capabilities: {exc}")
            print(
                f"Warning: LocalAgentConfig initialization failed with TypeError ({exc}). "
                "Dropping custom_tools, system_prompt, and hooks for fallback compatibility.",
                file=sys.stderr,
            )
            config_kwargs.pop("custom_tools", None)
            config_kwargs.pop("system_prompt", None)
            config_kwargs.pop("hooks", None)
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

    import logging

    logging.basicConfig(
        level=logging.INFO,
        format=f"[MILESTONE] [TASK {task_index}] [PHASE: %(levelname)s] %(name)s: %(message)s",
        force=True,
    )

    emit_milestone(task_index, "BOOTING")

    manifest_uri = os.environ.get("MANIFEST_URI", "").strip()
    manifest_raw = os.environ.get("TASK_MANIFEST", "")
    repo_url = get_env_var("REPO_URL", required=True)
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not gh_token:
        print("Warning: Missing GH_TOKEN. Proceeding with unauthenticated git operations.", file=sys.stderr)

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

    branch_name = resolve_worker_branch(task_item, task_index)

    base_branch = os.environ.get("BASE_BRANCH", "").strip() or None

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
            base_branch=base_branch,
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

    # Scrub credentials from environment before running bootstrap hooks or agent commands
    for tok_var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if tok_var in os.environ:
            del os.environ[tok_var]

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

    # Prevent ghost commits: Only commit when agent_status == "PASS" and candidate files exist
    if agent_status == "PASS" and candidate_files:
        emit_milestone(task_index, "VALIDATING_CANDIDATE")
        if verify_cmd_str:
            print(f"Running verification command: {verify_cmd_str}", flush=True)
            verify_timeout = int(os.environ.get("VERIFY_TIMEOUT", "300"))
            try:
                test_check = subprocess.run(
                    verify_cmd_str,
                    shell=True,
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    timeout=verify_timeout,
                )
                if test_check.returncode != 0:
                    agent_status = "ISSUES"
                    err_snippet = (test_check.stderr.strip() or test_check.stdout.strip())[-500:]
                    diff_stat = f"Commit rejected: Candidate failed verification command (exit code {test_check.returncode}): {err_snippet}"
                    print(f"Warning: Candidate modifications failed verification command (exit code {test_check.returncode}). Commit blocked.", file=sys.stderr)
            except subprocess.TimeoutExpired:
                agent_status = "ISSUES"
                diff_stat = f"Commit rejected: Candidate verification command timed out after {verify_timeout}s."
                print(f"Warning: Candidate verification command timed out after {verify_timeout}s. Commit blocked.", file=sys.stderr)

        if agent_status == "PASS":
            try:
                for cand_file in candidate_files:
                    run_command(["git", "add", "--", cand_file], cwd=repo_dir, check=True)
                cached_diff = run_command(["git", "diff", "--cached", "--name-only"], cwd=repo_dir, check=False)
                if not cached_diff.stdout.strip():
                    diff_stat = "Commit skipped: No candidate changes staged."
                    print("Notice: No candidate changes staged; skipping git commit.", file=sys.stderr)
                else:
                    changes_detected = True
                    commit_msg = f"worker-{task_index}: execute swarm brief"
                    run_command(["git", "commit", "-m", commit_msg], cwd=repo_dir, check=True)
                    commit_res = run_command(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True)
                    commit_sha = commit_res.stdout.strip()
                    diff_res = run_command(["git", "diff", "--stat", "HEAD~1", "HEAD"], cwd=repo_dir, check=False)
                    diff_stat = diff_res.stdout.strip()
            except subprocess.CalledProcessError as exc:
                agent_status = "ISSUES"
                commit_sha = None
                err_text = (exc.stderr or str(exc)).strip()
                diff_stat = f"Commit failed: {err_text}"
                err_msg = exc.stderr.replace(gh_token, "REDACTED") if gh_token and gh_token in exc.stderr else err_text
                print(f"Warning: Git commit preparation failed: {err_msg}", file=sys.stderr)
    elif agent_status != "PASS":
        diff_stat = f"Commit skipped: worker status is {agent_status} (PASS required; ghost commits prohibited)."
        print(f"Notice: Agent status is {agent_status}. Skipping git commit.", file=sys.stderr)
    else:
        diff_stat = "Commit skipped: No candidate files modified outside bootstrap scaffolding."
        print("Notice: No candidate modifications outside bootstrap files; skipping git commit.", file=sys.stderr)

    final_status = agent_status
    status_payload = {
        "task_index": task_index,
        "status": final_status,
        "summary": agent_summary.strip(),
        "score": score,
        "candidate_files": candidate_files,
        "session_id": session_id,
    }
    status_file = repo_dir / "status.json"
    status_file.write_text(json.dumps(status_payload, indent=2), encoding="utf-8")

    effective_bucket = gcs_bucket or os.environ.get("GCS_BUCKET", "").strip()
    is_cloud = bool(os.environ.get("CLOUD_RUN_TASK_INDEX") or os.environ.get("SWARM_SESSION_ID") or os.environ.get("K_SERVICE"))

    if is_cloud and candidate_files and not effective_bucket:
        final_status = "ISSUES"
        fail_evidence = "Fail-closed: No GCS bucket configured for cloud swarm worker. Candidate patch cannot be delivered under zero-push architecture."
        agent_summary += f"\n{fail_evidence}"
        print(f"Warning: {fail_evidence}", file=sys.stderr)
        status_payload["status"] = final_status
        status_payload["summary"] = agent_summary.strip()
        status_payload["evidence"] = fail_evidence
        status_file.write_text(json.dumps(status_payload, indent=2), encoding="utf-8")

    upload_failed = False
    gcs_uris = {}
    if effective_bucket:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import storage_uploader

            gcs_uris = storage_uploader.upload_run_artifacts(
                bucket_name=effective_bucket,
                prefix=gcs_prefix,
                repo_dir=repo_dir,
                task_index=task_index,
                status=final_status,
                candidate_files=candidate_files,
                commit_sha=commit_sha,
            )
            if gcs_uris:
                emit_milestone(task_index, "ARTIFACTS_UPLOADED")
                print("[MILESTONE] ARTIFACTS_UPLOADED", flush=True)
        except Exception as exc:
            print(f"Warning: GCS upload failed: {exc}", file=sys.stderr)
            upload_failed = True

        # Synchronize local status if storage_uploader overrode it
        if status_file.is_file():
            try:
                disk_status = json.loads(status_file.read_text(encoding="utf-8"))
                if disk_status.get("status") and disk_status.get("status") != final_status:
                    final_status = disk_status.get("status")
            except Exception:
                pass

        # Fail-closed check: if final_status == "PASS" and candidate_files were modified,
        # but upload_run_artifacts() failed to upload patch.diff or status.json to GCS,
        # or if upload explicitly failed, override final_status = "ISSUES".
        if final_status == "PASS" and candidate_files:
            if upload_failed or "patch.diff" not in gcs_uris or "status.json" not in gcs_uris:
                final_status = "ISSUES"
                fail_evidence = "Artifact upload to GCS failed; candidate patch could not be preserved."
                agent_summary += f"\n{fail_evidence}"
                print(f"Warning: {fail_evidence}", file=sys.stderr)
                status_payload["status"] = final_status
                status_payload["summary"] = agent_summary.strip()
                status_payload["evidence"] = fail_evidence
                status_file.write_text(json.dumps(status_payload, indent=2), encoding="utf-8")

    # Zero-push container architecture: cloud workers never push candidate branches to git remote.
    changes_pushed = False

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
    if "status.json" in gcs_uris:
        print(f"- GCS Status: {gcs_uris['status.json']}")
    if "patch.diff" in gcs_uris:
        print(f"- GCS Patch: {gcs_uris['patch.diff']}")
    if "score.json" in gcs_uris:
        print(f"- GCS Score: {gcs_uris['score.json']}")
    print(f"- Diff Stat:\n{diff_stat}")
    print("Summary:")
    print(agent_summary.strip())
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
