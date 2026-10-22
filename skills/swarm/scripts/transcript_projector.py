#!/usr/bin/env python3
"""
Shadow Transcript Projector for Cloud Swarm.

Projects real-time container log telemetry streams into Antigravity session
transcripts located in <app_data_dir>/brain/cloud-<session_id>-task-<task_index>/.
Provides per-task locking, atomic file replacement, and telemetry event deduplication.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

TELEMETRY_REGEX = re.compile(r"^\[TELEMETRY\](?:\s+\[TASK\s+(\d+)\])?\s+(.*)$")


def resolve_app_data_dir(custom_path: Optional[Union[str, Path]] = None) -> Path:
    if custom_path:
        return Path(custom_path).expanduser().resolve()
    env_app_dir = os.environ.get("ANTIGRAVITY_APP_DATA_DIR") or os.environ.get("APP_DATA_DIR")
    if env_app_dir:
        return Path(env_app_dir).expanduser().resolve()
    for cand in [
        Path(os.path.expanduser("~/.gemini/antigravity")),
        Path(os.path.expanduser("~/.gemini/antigravity-ide")),
    ]:
        if cand.exists():
            return cand.resolve()
    return Path(os.path.expanduser("~/.gemini/antigravity")).resolve()


def format_conversation_url(session_id: str, task_index: int) -> str:
    return f"conversation://cloud-{session_id}-task-{task_index}"


def get_task_conversation_id(session_id: str, task_index: int) -> str:
    return f"cloud-{session_id}-task-{task_index}"


def get_task_brain_dir(
    session_id: str,
    task_index: int,
    app_data_dir: Optional[Union[str, Path]] = None,
) -> Path:
    return resolve_app_data_dir(app_data_dir) / "brain" / get_task_conversation_id(session_id, task_index)


def initialize_shadow_transcript(
    session_id: str,
    task_index: int,
    task_brief: str = "",
    app_data_dir: Optional[Union[str, Path]] = None,
) -> Tuple[Path, Path]:
    task_dir = get_task_brain_dir(session_id, task_index, app_data_dir)
    logs_dir = task_dir / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    primary_file = task_dir / "transcript.jsonl"
    system_file = logs_dir / "transcript.jsonl"

    content = ""
    if task_brief:
        user_entry = {
            "step_index": 0,
            "source": "USER",
            "type": "USER_INPUT",
            "status": "DONE",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "content": task_brief,
        }
        content = json.dumps(user_entry) + "\n"

    primary_file.write_text(content, encoding="utf-8")
    system_file.write_text(content, encoding="utf-8")
    return primary_file, system_file


def cleanup_session(
    session_id: str,
    app_data_dir: Optional[Union[str, Path]] = None,
    preserve_transcripts: bool = True,
    temp_dir: Optional[Union[str, Path]] = None,
    bucket_name: Optional[str] = None,
    messenger: Optional[Any] = None,
    clean_mailboxes: bool = True,
) -> Dict[str, Any]:
    app_dir = resolve_app_data_dir(app_data_dir)
    brain_dir = app_dir / "brain"
    preserved_dirs: List[str] = []
    if brain_dir.exists():
        pattern = f"cloud-{session_id}-task-*"
        for task_dir in brain_dir.glob(pattern):
            if task_dir.is_dir():
                preserved_dirs.append(str(task_dir))
    if temp_dir and Path(temp_dir).exists():
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

    mailboxes_cleaned = 0
    if clean_mailboxes:
        if messenger is not None and hasattr(messenger, "cleanup_mailboxes"):
            try:
                mailboxes_cleaned = messenger.cleanup_mailboxes()
            except Exception:
                pass
        elif bucket_name:
            try:
                from storage_messenger import StorageMessenger
                msg = StorageMessenger(
                    bucket_name=bucket_name,
                    session_id=session_id,
                    is_worker=False,
                )
                mailboxes_cleaned = msg.cleanup_mailboxes()
            except Exception:
                pass

    return {
        "session_id": session_id,
        "transcripts_preserved": preserve_transcripts,
        "preserved_directories": preserved_dirs,
        "mailboxes_cleaned": mailboxes_cleaned,
    }


def is_telemetry_line(line: str) -> bool:
    if not line or not isinstance(line, str):
        return False
    s = line.strip()
    return "[TELEMETRY]" in s or '"event":' in s or '"type": "PLANNER_RESPONSE"' in s or '"type":"PLANNER_RESPONSE"' in s


def parse_telemetry_line(line: str) -> Optional[Dict[str, Any]]:
    if not line or not isinstance(line, str):
        return None
    s = line.strip()
    if not s:
        return None

    m = TELEMETRY_REGEX.search(s)
    if m:
        raw_task_idx, json_str = m.group(1), m.group(2)
        try:
            payload = json.loads(json_str)
            if not isinstance(payload, dict):
                return None
            if raw_task_idx is not None and "task_index" not in payload:
                try:
                    payload["task_index"] = int(raw_task_idx)
                except ValueError:
                    return None
            return payload
        except Exception:
            return None

    if s.startswith("{") and s.endswith("}"):
        try:
            payload = json.loads(s)
            if isinstance(payload, dict) and ("event" in payload or "type" in payload):
                return payload
        except Exception:
            return None

    return None


class ShadowTranscriptProjector:
    def __init__(
        self,
        session_id: str,
        app_data_dir: Optional[Union[str, Path]] = None,
        task_count: int = 1,
    ):
        self.session_id = session_id
        self.app_data_dir = resolve_app_data_dir(app_data_dir)
        self.task_count = task_count
        self.projection_latencies: List[float] = []
        self._last_entries: Dict[int, Dict[str, Any]] = {}
        self._states: Dict[int, Dict[str, Any]] = {}
        self._task_locks: Dict[int, threading.Lock] = {}
        self._lock = threading.Lock()
        self._seen_events: Set[Tuple[int, str, Any, Any]] = set()

    def _get_task_lock(self, task_index: int) -> threading.Lock:
        with self._lock:
            if task_index not in self._task_locks:
                self._task_locks[task_index] = threading.Lock()
            return self._task_locks[task_index]

    def get_task_dir(self, task_index: int) -> Path:
        return get_task_brain_dir(self.session_id, task_index, self.app_data_dir)

    def get_transcript_files(self, task_index: int) -> Tuple[Path, Path]:
        task_dir = self.get_task_dir(task_index)
        return task_dir / "transcript.jsonl", task_dir / ".system_generated" / "logs" / "transcript.jsonl"

    def init_task(self, task_index: int, task_brief: str = "") -> Tuple[Path, Path]:
        with self._get_task_lock(task_index):
            primary, system = initialize_shadow_transcript(
                session_id=self.session_id,
                task_index=task_index,
                task_brief=task_brief,
                app_data_dir=self.app_data_dir,
            )
            self._states[task_index] = {
                "step_index": 0 if task_brief else -1,
                "primary_file": primary,
                "system_file": system,
                "task_dir": primary.parent,
            }
            return primary, system

    def _get_or_init_state(self, task_index: int, *, acquire_lock: bool = True) -> Dict[str, Any]:
        if acquire_lock:
            with self._get_task_lock(task_index):
                return self._get_or_init_state(task_index, acquire_lock=False)

        if task_index not in self._states:
            primary, system = self.get_transcript_files(task_index)
            if not primary.exists() or not system.exists():
                initialize_shadow_transcript(self.session_id, task_index, app_data_dir=self.app_data_dir)
            step_idx = -1
            if primary.exists():
                try:
                    for line in primary.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            e = json.loads(line)
                            step_idx = max(step_idx, e.get("step_index", -1))
                except Exception:
                    pass
            self._states[task_index] = {
                "step_index": step_idx,
                "primary_file": primary,
                "system_file": system,
                "task_dir": primary.parent,
            }
        return self._states[task_index]

    def _write_entry(self, task_index: int, entry: Dict[str, Any], *, acquire_lock: bool = True) -> None:
        if acquire_lock:
            with self._get_task_lock(task_index):
                return self._write_entry(task_index, entry, acquire_lock=False)

        self._last_entries[task_index] = entry
        primary, system = self.get_transcript_files(task_index)
        line = json.dumps(entry) + "\n"
        for p in (primary, system):
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()

    def _update_last_entry(self, task_index: int, entry: Dict[str, Any], *, acquire_lock: bool = True) -> None:
        if acquire_lock:
            with self._get_task_lock(task_index):
                return self._update_last_entry(task_index, entry, acquire_lock=False)

        self._last_entries[task_index] = entry
        primary, system = self.get_transcript_files(task_index)
        for p in (primary, system):
            if not p.exists():
                continue
            lines = [line for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
            if lines:
                lines[-1] = json.dumps(entry)
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=p.parent, delete=False, mode="w", encoding="utf-8"
                    ) as tmp:
                        tmp_path = tmp.name
                        tmp.write("\n".join(lines) + "\n")
                        tmp.flush()
                        os.fsync(tmp.fileno())
                    os.replace(tmp_path, p)
                except Exception:
                    if tmp_path and os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                    raise

    def _read_last_entry(self, task_index: int, *, acquire_lock: bool = True) -> Optional[Dict[str, Any]]:
        if acquire_lock:
            with self._get_task_lock(task_index):
                return self._read_last_entry(task_index, acquire_lock=False)

        if task_index in self._last_entries:
            return self._last_entries[task_index]

        primary, _ = self.get_transcript_files(task_index)
        if not primary.exists():
            return None
        lines = [line for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        try:
            return json.loads(lines[-1])
        except Exception:
            return None

    def process_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        try:
            payload = parse_telemetry_line(line)
            if not payload:
                return None

            task_idx = int(payload.get("task_index", 0))
            event = payload.get("event") or payload.get("type", "")
            event_ts = payload.get("timestamp")

            step_index_or_id = payload.get("step_index")
            if step_index_or_id is None:
                step_index_or_id = payload.get("call_id") or payload.get("id") or ""
            if isinstance(step_index_or_id, (dict, list)):
                step_index_or_id = json.dumps(step_index_or_id, sort_keys=True)

            event_key = (task_idx, event, step_index_or_id, event_ts)

            with self._get_task_lock(task_idx):
                with self._lock:
                    if event_key in self._seen_events:
                        return None
                    self._seen_events.add(event_key)

                if event_ts is not None:
                    try:
                        if isinstance(event_ts, (int, float)):
                            t_log = float(event_ts)
                        else:
                            t_log = datetime.fromisoformat(str(event_ts).replace("Z", "+00:00")).timestamp()
                        latency = max(0.0, time.time() - t_log)
                        with self._lock:
                            self.projection_latencies.append(latency)
                    except Exception:
                        pass

                created_at = datetime.now(timezone.utc).isoformat()
                state = self._get_or_init_state(task_idx, acquire_lock=False)
                projected_entry = None

                if event in ("user_input", "USER_INPUT"):
                    last_entry = self._read_last_entry(task_idx, acquire_lock=False)
                    if last_entry and last_entry.get("type") == "USER_INPUT":
                        return last_entry
                    state["step_index"] += 1
                    projected_entry = {
                        "step_index": state["step_index"],
                        "source": "USER",
                        "type": "USER_INPUT",
                        "status": "DONE",
                        "created_at": created_at,
                        "content": payload.get("content", ""),
                    }
                    self._write_entry(task_idx, projected_entry, acquire_lock=False)

                elif event in ("thought", "THOUGHT"):
                    thought_text = payload.get("thought") or payload.get("content", "")
                    last_entry = self._read_last_entry(task_idx, acquire_lock=False)
                    if last_entry and last_entry.get("type") == "PLANNER_RESPONSE" and not last_entry.get("tool_calls"):
                        existing_thought = last_entry.get("thinking", "")
                        last_entry["thinking"] = (
                            f"{existing_thought}\n{thought_text}".strip() if existing_thought else thought_text
                        )
                        self._update_last_entry(task_idx, last_entry, acquire_lock=False)
                        projected_entry = last_entry
                    else:
                        state["step_index"] += 1
                        projected_entry = {
                            "step_index": state["step_index"],
                            "source": "MODEL",
                            "type": "PLANNER_RESPONSE",
                            "status": "DONE",
                            "created_at": created_at,
                            "thinking": thought_text,
                            "tool_calls": [],
                            "content": "",
                        }
                        self._write_entry(task_idx, projected_entry, acquire_lock=False)

                elif event in ("tool_call", "TOOL_CALL"):
                    tool_name = payload.get("tool_name", "tool")
                    tool_args = payload.get("args") or payload.get("tool_args", {})
                    call_id = payload.get("call_id") or f"call_{state['step_index'] + 1}"
                    tool_call_obj = {"name": tool_name, "args": tool_args, "id": call_id}
                    last_entry = self._read_last_entry(task_idx, acquire_lock=False)
                    if last_entry and last_entry.get("type") == "PLANNER_RESPONSE":
                        calls = last_entry.get("tool_calls", [])
                        calls.append(tool_call_obj)
                        last_entry["tool_calls"] = calls
                        self._update_last_entry(task_idx, last_entry, acquire_lock=False)
                        projected_entry = last_entry
                    else:
                        state["step_index"] += 1
                        projected_entry = {
                            "step_index": state["step_index"],
                            "source": "MODEL",
                            "type": "PLANNER_RESPONSE",
                            "status": "DONE",
                            "created_at": created_at,
                            "thinking": "",
                            "tool_calls": [tool_call_obj],
                            "content": "",
                        }
                        self._write_entry(task_idx, projected_entry, acquire_lock=False)

                elif event in ("tool_result", "TOOL_RESPONSE", "tool_response"):
                    tool_name = payload.get("tool_name", "tool")
                    output = payload.get("output", payload.get("result", ""))
                    success = bool(payload.get("success", True))
                    call_id = payload.get("call_id", "")
                    state["step_index"] += 1
                    projected_entry = {
                        "step_index": state["step_index"],
                        "source": "TOOL",
                        "type": "TOOL_RESPONSE",
                        "status": "DONE",
                        "created_at": created_at,
                        "tool_name": tool_name,
                        "content": output if isinstance(output, str) else json.dumps(output, default=str),
                        "output": output,
                        "success": success,
                        "call_id": call_id,
                    }
                    self._write_entry(task_idx, projected_entry, acquire_lock=False)

                elif event in ("agent_response", "AGENT_RESPONSE"):
                    resp_content = payload.get("content", "")
                    last_entry = self._read_last_entry(task_idx, acquire_lock=False)
                    if last_entry and last_entry.get("type") == "PLANNER_RESPONSE" and not last_entry.get("tool_calls"):
                        last_entry["content"] = resp_content
                        self._update_last_entry(task_idx, last_entry, acquire_lock=False)
                        projected_entry = last_entry
                    else:
                        state["step_index"] += 1
                        projected_entry = {
                            "step_index": state["step_index"],
                            "source": "MODEL",
                            "type": "PLANNER_RESPONSE",
                            "status": "DONE",
                            "created_at": created_at,
                            "thinking": "",
                            "tool_calls": [],
                            "content": resp_content,
                        }
                        self._write_entry(task_idx, projected_entry, acquire_lock=False)

                elif event in ("PLANNER_RESPONSE", "planner_response"):
                    state["step_index"] += 1
                    projected_entry = {
                        "step_index": state["step_index"],
                        "source": "MODEL",
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "created_at": created_at,
                        "thinking": payload.get("thinking", ""),
                        "tool_calls": payload.get("tool_calls", []),
                        "content": payload.get("content", ""),
                    }
                    self._write_entry(task_idx, projected_entry, acquire_lock=False)

                return projected_entry
        except Exception:
            return None

    def measure_projection_latency(self, line: str) -> Optional[float]:
        self.process_log_line(line)
        return self.get_last_latency()

    def get_last_latency(self) -> Optional[float]:
        with self._lock:
            return self.projection_latencies[-1] if self.projection_latencies else None

    def get_conversation_url(self, task_index: int) -> str:
        return format_conversation_url(self.session_id, task_index)


__all__ = [
    "TELEMETRY_REGEX",
    "ShadowTranscriptProjector",
    "cleanup_session",
    "format_conversation_url",
    "get_task_brain_dir",
    "get_task_conversation_id",
    "initialize_shadow_transcript",
    "is_telemetry_line",
    "parse_telemetry_line",
    "resolve_app_data_dir",
]
