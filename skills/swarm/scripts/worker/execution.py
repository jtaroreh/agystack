"""Execution boundaries shared by cloud workers and dispatch."""

import os
import re
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

LIMIT_ENV = {
    "max_agent_turns": "AGYSTACK_MAX_AGENT_TURNS",
    "command_timeout_s": "COMMAND_TIMEOUT",
    "verify_timeout_s": "VERIFY_TIMEOUT",
}
TERMINAL_STATES = frozenset({"PASS", "ISSUES", "BLOCKED"})
_UNSET = object()


def _positive_int(value, name):
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        value = int(value)
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class ExecutionLimits:
    max_agent_turns: int = 30
    command_timeout_s: int = 300
    verify_timeout_s: int = 300

    def __post_init__(self):
        for field in fields(self):
            if type(getattr(self, field.name)) is not int:
                raise ValueError(f"{field.name} must be a positive integer")
            _positive_int(getattr(self, field.name), field.name)


def _limit_fields(value):
    if not isinstance(value, Mapping):
        raise ValueError("execution_limits must be an object")
    unknown = value.keys() - LIMIT_ENV.keys()
    if unknown:
        raise ValueError(f"Unknown execution_limits fields: {sorted(unknown)}")
    for name, raw in value.items():
        if type(raw) is not int:
            raise ValueError(f"{name} must be a positive integer")
    return {name: _positive_int(raw, name) for name, raw in value.items()}


def resolve_execution_limits(task_limits=_UNSET, *, environ=None, runtime=_UNSET, cli=_UNSET, command_default=300):
    env = os.environ if environ is None else environ
    values = dict(max_agent_turns=30, command_timeout_s=command_default, verify_timeout_s=300)
    if runtime is not _UNSET:
        values.update(_limit_fields(runtime))
    values.update({name: _positive_int(env[key], key) for name, key in LIMIT_ENV.items() if key in env})
    if cli is not _UNSET:
        values.update(_limit_fields(cli))
    if task_limits is not _UNSET:
        values.update(_limit_fields(task_limits))
    return ExecutionLimits(**values)


def limits_for_task(task_item, *, command_default=300):
    overrides = task_item.get("execution_limits", {}) if isinstance(task_item, dict) else {}
    return resolve_execution_limits(overrides, command_default=command_default)


def evaluate_agent_status(agent_text):
    declarations = []
    lines = agent_text.rstrip().splitlines()
    fence = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and stripped == token:
                fence = None
            continue
        if fence is not None or line.startswith(("    ", "\t")):
            continue
        match = re.fullmatch(r"\[STATUS: (PASS|ISSUES|BLOCKED)\]", stripped)
        if match:
            declarations.append((index, match.group(1)))
        elif re.fullmatch(r"\[STATUS\b.*\]", stripped, re.IGNORECASE):
            declarations.append((index, "ISSUES"))
    if len(declarations) == 1 and declarations[0][0] == len(lines) - 1:
        return declarations[0][1], agent_text
    return "ISSUES", agent_text


CREDENTIAL_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9_]{36,}"),
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
    re.compile(r"ya29\.[0-9A-Za-z-_]+"),
    re.compile(r"Bearer [A-Za-z0-9_\-\.]+"),
]


def scrub_credentials(text):
    for pattern in CREDENTIAL_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def write_diagnostic(repo_dir, name, text):
    directory = Path(repo_dir) / ".agystack/diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-{uuid.uuid4().hex}.log"
    path.write_text(scrub_credentials(text)[-262144:], encoding="utf-8")
    return path


def exhaustion_result(repo_dir, limit, consumed, last_tool, last_response):
    summary = (
        f"Agent turn limit exhausted: limit={limit}, consumed={consumed}, "
        f"last_tool={last_tool or 'none'}, last_response={last_response[-4096:]!r}"
    )
    summary = scrub_credentials(summary)
    write_diagnostic(repo_dir, "agent-exhaustion", summary)
    return "ISSUES", summary


def run_bounded_shell(command, repo_dir, timeout_s, *, label="command"):
    buffers = [bytearray(), bytearray()]
    shell_args = ["bash", "-o", "pipefail", "-c", command] if os.name == "posix" else command
    try:
        process = subprocess.Popen(
            shell_args,
            shell=os.name != "posix",
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        error = scrub_credentials(str(exc))
        log_path = write_diagnostic(repo_dir, label, f"Command could not start: {error}")
        return subprocess.CompletedProcess(command, 127, "", error), f"Exit code 127: {error}\nLog: {log_path}"

    def drain(stream, buffer):
        with stream:
            while chunk := os.read(stream.fileno(), 8192):
                buffer.extend(chunk)
                del buffer[:-131072]

    readers = [
        threading.Thread(target=drain, args=(stream, buffer), daemon=True)
        for stream, buffer in zip((process.stdout, process.stderr), buffers)
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    deadline = time.monotonic() + timeout_s
    try:
        process.wait(timeout=timeout_s)
        for reader in readers:
            reader.join(timeout=max(0, deadline - time.monotonic()))
        if any(reader.is_alive() for reader in readers):
            raise subprocess.TimeoutExpired(command, timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()
    for reader in readers:
        reader.join(timeout=1)
    stdout, stderr = [scrub_credentials(bytes(buffer).decode("utf-8", errors="replace")) for buffer in buffers]
    if timed_out:
        stderr += f"\nCommand timed out after {timeout_s} seconds."
    returncode = 124 if timed_out else process.returncode
    output = f"Exit code {returncode}:\n{stdout}\n{stderr}"
    log_path = write_diagnostic(repo_dir, label, output)
    excerpt = f"Exit code {returncode}:\n{stdout[-8192:]}\n{stderr[-8192:]}\nLog: {log_path}"
    return subprocess.CompletedProcess(command, returncode, stdout, stderr), excerpt
