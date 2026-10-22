#!/usr/bin/env python3
"""
Swarm Dashboard module for tracking cloud execution progress, state badges,
console deep links, and live dashboard markdown generation.
"""

import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from transcript_projector import (
        format_conversation_url,
        is_telemetry_line,
        parse_telemetry_line,
        resolve_app_data_dir,
    )
except ImportError:
    from skills.swarm.scripts.transcript_projector import (
        format_conversation_url,
        is_telemetry_line,
        parse_telemetry_line,
        resolve_app_data_dir,
    )

STATUS_BADGES: Dict[str, str] = {
    "QUEUED": "⏳ Queued",
    "Queued": "⏳ Queued",
    "queued": "⏳ Queued",
    "PENDING": "⏳ Queued",
    "Pending": "⏳ Queued",
    "RUNNING": "🔄 Running",
    "Running": "🔄 Running",
    "running": "🔄 Running",
    "IN_PROGRESS": "🔄 Running",
    "PASS": "🟢 PASS",
    "Pass": "🟢 PASS",
    "pass": "🟢 PASS",
    "PASSED": "🟢 PASS",
    "SUCCESS": "🟢 PASS",
    "ISSUES": "⚠️ ISSUES",
    "Issues": "⚠️ ISSUES",
    "issues": "⚠️ ISSUES",
    "WARNING": "⚠️ ISSUES",
    "FAILED": "⚠️ ISSUES",
    "FAILURE": "⚠️ ISSUES",
    "BLOCKED": "🔴 BLOCKED",
    "Blocked": "🔴 BLOCKED",
    "blocked": "🔴 BLOCKED",
}


def colorize(text: str, color_code: str, use_color: Optional[bool] = None) -> str:
    """Wrap text in ANSI color escape codes if color is enabled."""
    if use_color is None:
        use_color = (
            sys.stdout.isatty()
            and not os.environ.get("NO_COLOR")
            and os.environ.get("TERM") != "dumb"
        )
    if not use_color:
        return text
    return f"{color_code}{text}\033[0m"


def format_status_badge(status: str) -> str:
    cleaned = (status or "").strip()
    return STATUS_BADGES.get(cleaned, STATUS_BADGES.get(cleaned.upper(), f"❓ {cleaned}"))


def format_elapsed_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    sec_int = int(seconds)
    if sec_int < 60:
        return f"{sec_int}s"
    minutes = sec_int // 60
    rem_secs = sec_int % 60
    if minutes < 60:
        return f"{minutes}m {rem_secs:02d}s"
    hours = minutes // 60
    rem_mins = minutes % 60
    return f"{hours}h {rem_mins:02d}m {rem_secs:02d}s"


def format_tool_snippet(tool_name: str, args: Any = None, max_len: int = 60) -> str:
    if not tool_name:
        return "-"
    if not args:
        snippet = f"{tool_name}()"
    elif isinstance(args, dict):
        primary_keys = [
            "CommandLine",
            "command",
            "cmd",
            "AbsolutePath",
            "TargetFile",
            "path",
            "Query",
            "pattern",
            "query",
            "toolAction",
        ]
        picked = None
        for k in primary_keys:
            if k in args and args[k] is not None:
                val = str(args[k]).strip()
                picked = f"{k}={repr(val)}"
                break
        if not picked:
            items = []
            for k, v in args.items():
                items.append(f"{k}={repr(str(v).strip())}")
            picked = ", ".join(items)
        snippet = f"{tool_name}({picked})"
    elif isinstance(args, str):
        snippet = f"{tool_name}({args})"
    else:
        snippet = f"{tool_name}({json.dumps(args, default=str)})"

    snippet = snippet.replace("\n", " ").replace("|", "\\|").strip()
    if len(snippet) > max_len:
        snippet = snippet[: max_len - 3] + "..."
    return f"`{snippet}`"


def format_cloud_run_execution_url(
    execution_name: str,
    project: Optional[str] = None,
    region: Optional[str] = None,
) -> str:
    exec_clean = (execution_name or "").strip()
    if region:
        url = f"https://console.cloud.google.com/run/jobs/executions/details/{region.strip()}/{exec_clean}"
    else:
        url = f"https://console.cloud.google.com/run/jobs/executions/details/{exec_clean}"
    if project:
        url += f"?project={project.strip()}"
    return url


format_cloud_run_url = format_cloud_run_execution_url


def format_cloud_logging_url(
    execution_name: Optional[str] = None,
    project: Optional[str] = None,
    query: Optional[str] = None,
) -> str:
    if query:
        query_str = query.strip()
    elif execution_name:
        query_str = f'labels."run.googleapis.com/execution_name"="{execution_name.strip()}"'
    else:
        query_str = 'resource.type="cloud_run_job"'
    encoded_query = urllib.parse.quote(query_str, safe="")
    url = f"https://console.cloud.google.com/logs/query;query={encoded_query}"
    if project:
        url += f"?project={project.strip()}"
    return url


format_log_viewer_url = format_cloud_logging_url


def format_gcs_console_url(
    bucket: str,
    prefix: str = "",
    project: Optional[str] = None,
) -> str:
    clean_bucket = (bucket or "").strip().removeprefix("gs://").strip("/")
    clean_prefix = (prefix or "").strip().removeprefix("gs://")
    if clean_prefix.startswith(clean_bucket + "/"):
        clean_prefix = clean_prefix[len(clean_bucket) + 1 :]
    clean_prefix = clean_prefix.strip("/")

    # Normalize legacy prefixes: ensure swarms/<session_id> formatting
    if clean_prefix.startswith("swarm-"):
        clean_prefix = f"swarms/{clean_prefix[len('swarm-'):]}"
    elif clean_prefix.startswith("swarm/"):
        clean_prefix = f"swarms/{clean_prefix[len('swarm/'):]}"

    if clean_prefix:
        url = f"https://console.cloud.google.com/storage/browser/{clean_bucket}/{clean_prefix}"
    else:
        url = f"https://console.cloud.google.com/storage/browser/{clean_bucket}"
    if project:
        url += f"?project={project.strip()}"
    return url


format_gcs_url = format_gcs_console_url


def format_monitored_line(line_str: str, use_color: Optional[bool] = None) -> str:
    """Format a monitored Cloud Run log line with alert banners and terminal styling."""
    if use_color is None:
        use_color = (
            sys.stdout.isatty()
            and not os.environ.get("NO_COLOR")
            and os.environ.get("TERM") != "dumb"
        )

    is_alarm = line_str.startswith("[ALARM]")
    is_loop_milestone = line_str.startswith("[MILESTONE]") and "[PHASE: POTENTIAL_LOOP]" in line_str
    if is_alarm:
        content = line_str[len("[ALARM]"):].strip()
        if content.startswith(">>>") and content.endswith("<<<"):
            banner = f"[ALARM] {content}"
        elif content:
            banner = f"[ALARM] >>> {content} <<<"
        else:
            banner = "[ALARM]"
        return colorize(banner, "\033[91;1m", use_color=use_color)

    if is_loop_milestone:
        banner = f"[ALARM] >>> {line_str} <<<"
        return colorize(banner, "\033[91;1m", use_color=use_color)

    is_waiting = (
        line_str.startswith("[WAITING_FOR_ORCHESTRATOR]")
        or line_str.startswith("WAITING_FOR_ORCHESTRATOR")
        or bool(re.match(r"^\[TASK\s+\d+\]\s+WAITING_FOR_ORCHESTRATOR\b", line_str))
    )
    if is_waiting:
        if line_str.startswith("[WAITING_FOR_ORCHESTRATOR]"):
            content = line_str[len("[WAITING_FOR_ORCHESTRATOR]"):].strip()
            if content.startswith(">>>") and content.endswith("<<<"):
                banner = line_str
            elif content:
                banner = f"[WAITING_FOR_ORCHESTRATOR] >>> {content} <<<"
            else:
                banner = "[WAITING_FOR_ORCHESTRATOR]"
        else:
            banner = f"[WAITING_FOR_ORCHESTRATOR] >>> {line_str} <<<"
        return colorize(banner, "\033[93;1m", use_color=use_color)

    return line_str


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


@dataclass
class TaskDashboardState:
    task_index: int
    model: str = "default"
    status: str = "Queued"
    phase: str = "Queued"
    active_tool: Optional[str] = None
    tool_args: Optional[Any] = None
    tool_snippet: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    pending_steer: Optional[str] = None

    @property
    def is_steer_pending(self) -> bool:
        return bool(self.pending_steer)

    def get_badge(self) -> str:
        return format_status_badge(self.status)

    def get_elapsed_seconds(self, now: Optional[float] = None) -> float:
        if self.start_time is None:
            return 0.0
        current = self.end_time if self.end_time is not None else (now if now is not None else time.time())
        return max(0.0, current - self.start_time)

    def get_active_display(self) -> str:
        if self.pending_steer:
            return f"STEER_PENDING: {self.pending_steer}"
        if self.active_tool:
            if self.tool_snippet:
                return self.tool_snippet
            return format_tool_snippet(self.active_tool, self.tool_args)
        if self.phase and self.phase not in ("Queued", "QUEUED"):
            return self.phase
        return "-"


class SwarmDashboardWriter:
    def __init__(
        self,
        session_id: str,
        conversation_id: Optional[str] = None,
        app_data_dir: Optional[Union[str, Path]] = None,
        task_count: int = 1,
        project: Optional[str] = None,
        region: Optional[str] = None,
        execution_name: Optional[str] = None,
        gcs_bucket: Optional[str] = None,
        model: Optional[str] = None,
        tasks_list: Optional[List[Any]] = None,
    ):
        self.session_id = session_id
        # Precedence: explicit argument > CONVERSATION_ID env > ANTIGRAVITY_CONVERSATION_ID env > session_id > default
        self.conversation_id = (
            conversation_id
            or os.environ.get("CONVERSATION_ID")
            or os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
            or session_id
            or "default"
        )
        self.app_data_dir = resolve_app_data_dir(app_data_dir)
        self.dashboard_path = self.app_data_dir / "brain" / self.conversation_id / "swarm_dashboard.md"
        self.output_path = self.dashboard_path
        self.task_count = max(1, task_count)
        self.project = project
        self.region = region
        self.execution_name = execution_name
        self.gcs_bucket = gcs_bucket
        self.default_model = model or "default"
        self.tasks_list = tasks_list or []
        self._lock = threading.Lock()
        self._states: Dict[int, TaskDashboardState] = {}
        self._init_tasks()

    def _init_tasks(self) -> None:
        for idx in range(self.task_count):
            task_model = self.default_model
            if self.tasks_list and idx < len(self.tasks_list):
                item = self.tasks_list[idx]
                if isinstance(item, dict):
                    task_model = item.get("model") or item.get("worker_model") or self.default_model
            self._states[idx] = TaskDashboardState(
                task_index=idx,
                model=task_model,
                status="Queued",
                phase="Queued",
            )

    def set_execution_name(self, execution_name: str) -> None:
        with self._lock:
            self.execution_name = execution_name

    def format_cloud_run_execution_url(self, execution_name: Optional[str] = None) -> Optional[str]:
        name = execution_name or self.execution_name
        if not name:
            return None
        return format_cloud_run_execution_url(name, project=self.project, region=self.region)

    def format_cloud_logging_url(self, execution_name: Optional[str] = None) -> str:
        name = execution_name or self.execution_name
        return format_cloud_logging_url(name, project=self.project)

    def format_gcs_console_url(self, prefix: Optional[str] = None) -> Optional[str]:
        if not self.gcs_bucket:
            return None
        pref = prefix if prefix is not None else f"swarms/{self.session_id}"
        return format_gcs_console_url(self.gcs_bucket, pref, project=self.project)

    def get_cloud_run_execution_url(self) -> Optional[str]:
        return self.format_cloud_run_execution_url()

    def get_cloud_logging_url(self) -> str:
        return self.format_cloud_logging_url()

    def get_gcs_console_url(self) -> Optional[str]:
        return self.format_gcs_console_url()

    def get_task_state(self, task_index: int) -> Optional[TaskDashboardState]:
        with self._lock:
            return self._states.get(task_index)

    def get_task_status(self, task_index: int) -> str:
        with self._lock:
            state = self._states.get(task_index)
            return state.status if state else "Queued"

    def get_task_badge(self, task_index: int) -> str:
        with self._lock:
            state = self._states.get(task_index)
            return state.get_badge() if state else "⏳ Queued"

    def update_task_phase(self, task_index: int, phase: str, detail: str = "") -> None:
        with self._lock:
            if task_index not in self._states:
                self._states[task_index] = TaskDashboardState(
                    task_index=task_index,
                    model=self.default_model,
                )
            state = self._states[task_index]
            state.phase = phase
            if phase in (
                "RUNNING_AGENT",
                "RUNNING",
                "STARTING",
                "PREPARING_WORKSPACE",
                "WORKSPACE_PREPARED",
                "BOOTSTRAP",
                "VERIFYING",
                "CLEANUP",
            ):
                if state.status in ("Queued", "QUEUED"):
                    state.status = "Running"
                    if state.start_time is None:
                        state.start_time = time.time()
            elif phase in ("COMPLETED", "FINISHED", "PASS"):
                if state.status not in ("ISSUES", "BLOCKED"):
                    state.status = "PASS"
                if state.end_time is None:
                    state.end_time = time.time()
            if phase in ("STEER_APPLIED", "ABORT_REQUESTED"):
                state.pending_steer = None

    def update_task_steer(self, task_index: int, instruction: str) -> None:
        with self._lock:
            if task_index not in self._states:
                self._states[task_index] = TaskDashboardState(
                    task_index=task_index,
                    model=self.default_model,
                )
            self._states[task_index].pending_steer = instruction

    def clear_task_steer(self, task_index: int) -> None:
        with self._lock:
            if task_index in self._states:
                self._states[task_index].pending_steer = None

    def update_task_tool(
        self,
        task_index: int,
        tool_name: str,
        args: Any = None,
        snippet: Optional[str] = None,
    ) -> None:
        with self._lock:
            if task_index not in self._states:
                self._states[task_index] = TaskDashboardState(
                    task_index=task_index,
                    model=self.default_model,
                )
            state = self._states[task_index]
            state.active_tool = tool_name
            state.tool_args = args
            state.tool_snippet = snippet or format_tool_snippet(tool_name, args)
            if state.status in ("Queued", "QUEUED"):
                state.status = "Running"
                if state.start_time is None:
                    state.start_time = time.time()

    def update_task_status(self, task_index: int, status: str) -> None:
        with self._lock:
            if task_index not in self._states:
                self._states[task_index] = TaskDashboardState(
                    task_index=task_index,
                    model=self.default_model,
                )
            state = self._states[task_index]
            cleaned = status.strip()
            state.status = cleaned
            if cleaned.upper() in ("PASS", "PASSED", "SUCCESS", "ISSUES", "WARNING", "BLOCKED", "FAILED"):
                if state.end_time is None:
                    state.end_time = time.time()
                if state.start_time is None:
                    state.start_time = state.created_at
            elif cleaned.upper() in ("RUNNING", "RUN"):
                if state.start_time is None:
                    state.start_time = time.time()

    def process_log_line(self, line: str) -> bool:
        if not line or not isinstance(line, str):
            return False
        s = line.strip()
        if not s:
            return False

        m = parse_milestone_log(s)
        if m:
            try:
                t_idx = int(m["task_index"])
                phase = m["phase"]
                detail = m.get("detail", "")
                self.update_task_phase(t_idx, phase, detail)
                if phase in ("STEER_APPLIED", "ABORT_REQUESTED"):
                    self.clear_task_steer(t_idx)
                return True
            except Exception:
                pass

        # Check for [STEER] log lines:
        # e.g. "[STEER] Instruction delivered to task-0 mailbox in GCS"
        # e.g. "[STEER] [TASK 0] Abort search"
        if "[STEER]" in s:
            m_steer = re.search(
                r"\[STEER\](?:\s+\[TASK\s+(\d+)\]|\s+Instruction delivered to task-(\d+)|\s+task-(\d+)|\s+Task\s+(\d+))?(?:\s*[:\-]\s*(.*?)(?:\s+mailbox in GCS)?|\s+mailbox in GCS)?$",
                s,
                re.IGNORECASE,
            )
            if m_steer:
                try:
                    idx_str = m_steer.group(1) or m_steer.group(2) or m_steer.group(3) or m_steer.group(4)
                    if idx_str is not None:
                        t_idx = int(idx_str)
                        instruction = (m_steer.group(5) or "").strip()
                        with self._lock:
                            curr = self._states.get(t_idx)
                            inst = instruction or (curr.pending_steer if curr and curr.pending_steer else "Pending")
                        self.update_task_steer(t_idx, inst)
                        return True
                except Exception:
                    pass

        if "STEER_APPLIED" in s or "ABORT_REQUESTED" in s:
            m_steer_act = re.search(r"\b(STEER_APPLIED|ABORT_REQUESTED)\b", s)
            if m_steer_act:
                act = m_steer_act.group(1)
                m_t = re.search(r"\[TASK\s+(\d+)\]", s, re.IGNORECASE) or re.search(r"task-(\d+)", s, re.IGNORECASE)
                if m_t:
                    try:
                        t_idx = int(m_t.group(1))
                        self.clear_task_steer(t_idx)
                        self.update_task_phase(t_idx, act)
                        return True
                    except Exception:
                        pass

        if is_telemetry_line(s):
            try:
                payload = parse_telemetry_line(s)
                if payload:
                    task_idx = int(payload.get("task_index", 0))
                    event = payload.get("event") or payload.get("type", "")
                    if event in ("tool_call", "TOOL_CALL"):
                        t_name = payload.get("tool_name", "tool")
                        t_args = payload.get("args") or payload.get("tool_args", {})
                        self.update_task_tool(task_idx, t_name, t_args)
                        return True
                    elif event in ("tool_result", "TOOL_RESPONSE", "tool_response"):
                        with self._lock:
                            if task_idx in self._states:
                                self._states[task_idx].active_tool = None
                        return True
                    elif event in ("thought", "THOUGHT"):
                        with self._lock:
                            if task_idx in self._states and self._states[task_idx].status in ("Queued", "QUEUED"):
                                self._states[task_idx].status = "Running"
                                if self._states[task_idx].start_time is None:
                                    self._states[task_idx].start_time = time.time()
                        return True
            except Exception:
                pass

        m_status = re.search(r"\[STATUS:\s*([A-Za-z_]+)\s*\]", s, re.IGNORECASE)
        if m_status:
            status_word = m_status.group(1).upper()
            m_task = re.search(r"\[TASK\s+(\d+)\]", s, re.IGNORECASE) or re.search(
                r"-\s*Task Index:\s*(\d+)", s, re.IGNORECASE
            )
            task_idx = int(m_task.group(1)) if m_task else 0
            self.update_task_status(task_idx, status_word)
            return True

        return False

    def render(self, now: Optional[float] = None) -> str:
        with self._lock:
            cr_url = self.format_cloud_run_execution_url()
            log_url = self.format_cloud_logging_url()
            gcs_url = self.format_gcs_console_url()

            lines = []
            lines.append(f"# Swarm Dashboard: `{self.session_id}`\n")
            lines.append("### Google Cloud Console Deep Links\n")
            if cr_url and self.execution_name:
                lines.append(f"- **Cloud Run Execution:** [{self.execution_name}]({cr_url})")
            else:
                lines.append("- **Cloud Run Execution:** `(pending dispatch)`")
            lines.append(f"- **Cloud Logging:** [Pre-filtered Logs]({log_url})")
            if gcs_url and self.gcs_bucket:
                lines.append(f"- **GCS Artifacts:** [gs://{self.gcs_bucket}/swarms/{self.session_id}]({gcs_url})")
            else:
                lines.append("- **GCS Artifacts:** `(pending)`")
            lines.append("")

            counts: Dict[str, int] = {"Queued": 0, "Running": 0, "PASS": 0, "ISSUES": 0, "BLOCKED": 0}
            for state in self._states.values():
                st = state.status.upper()
                if st in ("PASS", "PASSED", "SUCCESS"):
                    counts["PASS"] += 1
                elif st in ("ISSUES", "WARNING", "FAILED", "FAILURE"):
                    counts["ISSUES"] += 1
                elif st in ("BLOCKED",):
                    counts["BLOCKED"] += 1
                elif st in ("RUNNING", "IN_PROGRESS"):
                    counts["Running"] += 1
                else:
                    counts["Queued"] += 1

            summary_parts = [
                f"**Total Tasks:** {len(self._states)}",
                f"**Queued:** {counts['Queued']}",
                f"**Running:** {counts['Running']}",
                f"**PASS:** {counts['PASS']}",
                f"**ISSUES:** {counts['ISSUES']}",
                f"**BLOCKED:** {counts['BLOCKED']}",
            ]
            lines.append(" | ".join(summary_parts) + "\n")

            lines.append(
                "| Task Index | Model | Active Phase / Tool | Elapsed Time | Status Badge | Conversation Deep Link |"
            )
            lines.append("|:---:|:---:|:---|:---:|:---:|:---|")

            sorted_indices = sorted(self._states.keys())
            for idx in sorted_indices:
                st = self._states[idx]
                model = st.model
                active_disp = st.get_active_display()
                elapsed_str = format_elapsed_time(st.get_elapsed_seconds(now=now))
                badge = st.get_badge()
                conv_url = format_conversation_url(self.session_id, idx)
                conv_link = f"[{conv_url}]({conv_url})"
                lines.append(f"| {idx} | {model} | {active_disp} | {elapsed_str} | {badge} | {conv_link} |")

            lines.append("")
            ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            lines.append(f"*Last updated: {ts_str}*")
            return "\n".join(lines) + "\n"

    def write(self, now: Optional[float] = None) -> Path:
        content = self.render(now=now)
        target_path = self.dashboard_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(
            dir=str(target_path.parent),
            prefix=".swarm_dashboard_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, target_path)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            raise
        return target_path


__all__ = [
    "STATUS_BADGES",
    "MILESTONE_REGEX",
    "SwarmDashboardWriter",
    "TaskDashboardState",
    "colorize",
    "format_cloud_logging_url",
    "format_cloud_run_execution_url",
    "format_cloud_run_url",
    "format_elapsed_time",
    "format_gcs_console_url",
    "format_gcs_url",
    "format_log_viewer_url",
    "format_monitored_line",
    "format_status_badge",
    "format_tool_snippet",
    "parse_milestone_log",
]
