#!/usr/bin/env python3
"""
Agent hooks and loop stagnancy tracking for Cloud Run worker container.
"""

from dataclasses import dataclass, field
import hashlib
import json
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


def emit_milestone(task_index: int, phase: str, detail: str = "") -> None:
    cw = sys.modules.get("cloud_worker")
    if cw and hasattr(cw, "emit_milestone") and cw.emit_milestone is not emit_milestone:
        return cw.emit_milestone(task_index, phase, detail)
    msg = f"[MILESTONE] [TASK {task_index}] [PHASE: {phase}]"
    if detail:
        msg += f" {detail}"
    print(msg, flush=True)


def emit_thought(task_index_or_thought: Any, thought: Optional[str] = None, *args: Any, **kwargs: Any) -> None:
    cw = sys.modules.get("cloud_worker")
    if cw and hasattr(cw, "emit_thought"):
        return cw.emit_thought(task_index_or_thought, thought, *args, **kwargs)


def emit_tool_invocation(
    task_index: int,
    tool_name: str,
    args: Any = None,
    call_id: Optional[str] = None,
    *extra_args: Any,
    **kwargs: Any,
) -> None:
    cw = sys.modules.get("cloud_worker")
    if cw and hasattr(cw, "emit_tool_invocation"):
        return cw.emit_tool_invocation(task_index, tool_name, args, call_id=call_id, *extra_args, **kwargs)


def emit_tool_result(
    task_index: int,
    tool_name: str,
    output: Any = "",
    success: bool = True,
    call_id: Optional[str] = None,
    duration_s: float = 0.0,
    *extra_args: Any,
    **kwargs: Any,
) -> None:
    cw = sys.modules.get("cloud_worker")
    if cw and hasattr(cw, "emit_tool_result"):
        return cw.emit_tool_result(
            task_index,
            tool_name,
            output,
            success=success,
            call_id=call_id,
            duration_s=duration_s,
            *extra_args,
            **kwargs,
        )


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
                    f"Warning: Tool \x27{record.tool_name}\x27 has been executed {self._consecutive_count} "
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
        emit_tool_invocation(task_index, tool_name, tool_args, call_id=str(record.args_hash))

        if is_stagnant:
            emit_milestone(task_index, "POTENTIAL_LOOP", f"{tool_name} (repeated {count}x)")
            print(
                f"[ALARM] [TASK {task_index}] [POTENTIAL_LOOP] Tool '{tool_name}' repeated {count} times with identical inputs.",
                flush=True,
            )
            combined_context = f"{steer_context}\n\n{warning}" if steer_context else warning
            try:
                return t.HookResult(allow=True, custom_context=combined_context)
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
        emit_tool_result(
            task_index,
            tool_name,
            output,
            success=success,
            call_id=str(matched.get("id", "")) if matched else "",
            duration_s=duration_s,
        )

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
                emit_tool_result(
                    task_index,
                    matched["tool_name"],
                    str(error),
                    success=False,
                    call_id=str(matched.get("id", "")),
                    duration_s=duration_s,
                )
            else:
                emit_milestone(task_index, "TOOL_ERROR", str(error)[:80])
                emit_tool_result(task_index, "tool", str(error), success=False)
            return None
        hooks_to_register.append(on_tool_error)

    if hasattr(h, "on_thought"):
        @h.on_thought
        async def on_thought(thought_content: Any) -> None:
            emit_thought(task_index, str(thought_content))
        hooks_to_register.append(on_thought)
    elif hasattr(h, "on_model_thought"):
        @h.on_model_thought
        async def on_model_thought(thought_content: Any) -> None:
            emit_thought(task_index, str(thought_content))
        hooks_to_register.append(on_model_thought)

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
