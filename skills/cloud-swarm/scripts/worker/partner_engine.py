#!/usr/bin/env python3
"""
Partner model engine for Vertex AI Model Garden endpoints (Claude and Fable).
Handles model alias resolution, workspace tool execution with pre-tool safety
interception, AnthropicVertex client integration, and autonomous turn loops.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .execution import ExecutionLimits, evaluate_agent_status as _evaluate_agent_status, exhaustion_result, limits_for_task, run_bounded_shell

try:
    from pre_tool_safety import evaluate_safety
except ImportError:
    try:
        hooks_dir = Path(__file__).resolve().parent.parent.parent.parent / "poteto-mode" / "scripts" / "hooks"
        if hooks_dir.is_dir() and str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))
        from pre_tool_safety import evaluate_safety
    except Exception:
        evaluate_safety = None

DEFAULT_PARTNER_SYSTEM_PROMPT = """You are a specialized poteto coding delegate for agystack executing inside an isolated cloud worker container.
You implement surgical code edits, run test suites, verify outputs, and keep code and diffs clean and unslopped.

Guidelines:
1. Implement the requested task directly and surgically in the workspace.
2. Maintain high engineering rigor: run test suites and verification commands before completing.
3. Keep diffs minimal and clean. Avoid narrating comments or speculative code.
4. End your final response with exactly one standalone unquoted line, outside code fences: [STATUS: PASS], [STATUS: ISSUES], or [STATUS: BLOCKED].
"""


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
    if cw and hasattr(cw, "emit_thought") and cw.emit_thought is not emit_thought:
        return cw.emit_thought(task_index_or_thought, thought, *args, **kwargs)
    if thought is None and isinstance(task_index_or_thought, str):
        task_idx = 0
        th = task_index_or_thought
    elif isinstance(task_index_or_thought, int):
        task_idx = task_index_or_thought
        th = thought or ""
    else:
        task_idx = 0
        th = str(task_index_or_thought)
    print(f"[THOUGHT] [TASK {task_idx}] {th}", flush=True)


def emit_tool_invocation(task_index: int, tool_name: str, tool_input: Any = None, *args: Any, **kwargs: Any) -> None:
    cw = sys.modules.get("cloud_worker")
    if cw and hasattr(cw, "emit_tool_invocation") and cw.emit_tool_invocation is not emit_tool_invocation:
        return cw.emit_tool_invocation(task_index, tool_name, tool_input, *args, **kwargs)
    if isinstance(tool_input, dict):
        args_summary = ", ".join(f"{k}={v!r}" for k, v in tool_input.items())
    else:
        args_summary = str(tool_input)
    print(f"[TOOL_INVOCATION] [TASK {task_index}] [{tool_name}] {args_summary}", flush=True)
    emit_milestone(task_index, "TOOL_START", f"{tool_name}: {args_summary[:60]}")


def emit_tool_result(task_index: int, tool_name: str, result: Any = "", *args: Any, **kwargs: Any) -> None:
    cw = sys.modules.get("cloud_worker")
    if cw and hasattr(cw, "emit_tool_result") and cw.emit_tool_result is not emit_tool_result:
        return cw.emit_tool_result(task_index, tool_name, result, *args, **kwargs)
    res_str = str(result)
    summary = res_str[:200] if len(res_str) > 200 else res_str
    print(f"[TOOL_RESULT] [TASK {task_index}] [{tool_name}] {summary}", flush=True)
    emit_milestone(task_index, "TOOL_END", f"{tool_name}")


PARTNER_MODEL_ALIASES = {
    # Claude 3.7 Sonnet
    "claude-3-7-sonnet": "claude-3-7-sonnet@20250219",
    "claude-3.7-sonnet": "claude-3-7-sonnet@20250219",
    "claude-3-7-sonnet@20250219": "claude-3-7-sonnet@20250219",
    "sonnet-3.7": "claude-3-7-sonnet@20250219",
    "sonnet-3-7": "claude-3-7-sonnet@20250219",
    "publishers/anthropic/models/claude-3-7-sonnet": "claude-3-7-sonnet@20250219",
    "publishers/anthropic/models/claude-3.7-sonnet": "claude-3-7-sonnet@20250219",
    "publishers/anthropic/models/claude-3-7-sonnet@20250219": "claude-3-7-sonnet@20250219",

    # Claude 3.5 Sonnet
    "claude-3-5-sonnet": "claude-3-5-sonnet-v2@20241022",
    "claude-3.5-sonnet": "claude-3-5-sonnet-v2@20241022",
    "claude-3-5-sonnet-v2@20241022": "claude-3-5-sonnet-v2@20241022",
    "claude-3.5-sonnet-v2@20241022": "claude-3-5-sonnet-v2@20241022",
    "claude-3-5-sonnet-v2": "claude-3-5-sonnet-v2@20241022",
    "claude-3.5-sonnet-v2": "claude-3-5-sonnet-v2@20241022",
    "sonnet-5.5": "claude-3-5-sonnet-v2@20241022",
    "sonnet-5-5": "claude-3-5-sonnet-v2@20241022",
    "claude-5-5-sonnet": "claude-3-5-sonnet-v2@20241022",
    "claude-5.5-sonnet": "claude-3-5-sonnet-v2@20241022",
    "publishers/anthropic/models/claude-3-5-sonnet": "claude-3-5-sonnet-v2@20241022",
    "publishers/anthropic/models/claude-3.5-sonnet": "claude-3-5-sonnet-v2@20241022",
    "publishers/anthropic/models/claude-3-5-sonnet-v2@20241022": "claude-3-5-sonnet-v2@20241022",
    "publishers/anthropic/models/claude-5-5-sonnet": "claude-3-5-sonnet-v2@20241022",
    "publishers/anthropic/models/claude-5.5-sonnet": "claude-3-5-sonnet-v2@20241022",

    # Claude 3.5 Haiku
    "claude-3-5-haiku": "claude-3-5-haiku@20241022",
    "claude-3.5-haiku": "claude-3-5-haiku@20241022",
    "claude-3-5-haiku@20241022": "claude-3-5-haiku@20241022",
    "claude-3.5-haiku@20241022": "claude-3-5-haiku@20241022",
    "haiku-3.5": "claude-3-5-haiku@20241022",
    "haiku-3-5": "claude-3-5-haiku@20241022",
    "publishers/anthropic/models/claude-3-5-haiku": "claude-3-5-haiku@20241022",
    "publishers/anthropic/models/claude-3.5-haiku": "claude-3-5-haiku@20241022",
    "publishers/anthropic/models/claude-3-5-haiku@20241022": "claude-3-5-haiku@20241022",

    # Claude 3 Opus
    "claude-3-opus": "claude-3-opus@20240229",
    "claude-3-opus@20240229": "claude-3-opus@20240229",
    "opus-3": "claude-3-opus@20240229",
    "opus-5.5": "claude-3-opus@20240229",
    "opus-5-5": "claude-3-opus@20240229",
    "claude-5-5-opus": "claude-3-opus@20240229",
    "claude-5.5-opus": "claude-3-opus@20240229",
    "publishers/anthropic/models/claude-3-opus": "claude-3-opus@20240229",
    "publishers/anthropic/models/claude-3-opus@20240229": "claude-3-opus@20240229",
    "publishers/anthropic/models/claude-5-5-opus": "claude-3-opus@20240229",
    "publishers/anthropic/models/claude-5.5-opus": "claude-3-opus@20240229",

    # Fable
    "fable": "fable-5-1",
    "fable-5-1": "fable-5-1",
    "fable-5.1": "fable-5-1",
    "publishers/fable/models/fable-5-1": "fable-5-1",
    "publishers/fable/models/fable-5.1": "fable-5-1",

    # DeepSeek Model Garden
    "deepseek": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
    "deepseek-flash": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
    "deepseek-4.1": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
    "deepseek-v4.1": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
    "deepseek-4.1-flash": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
    "deepseek-v4.1-flash-maas": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
    "deepseek-v4.1-flash-maas@001": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
    "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
}

PARTNER_MODELS = {
    "claude-3-7-sonnet@20250219",
    "claude-3-5-sonnet-v2@20241022",
    "claude-3-5-haiku@20241022",
    "claude-3-opus@20240229",
    "fable-5-1",
    "fable",
}


def is_deepseek_model(model: str) -> bool:
    if not model:
        return False
    return "deepseek" in model.lower().strip()


def is_partner_model(model: str) -> bool:
    if not model:
        return False
    m = model.lower().strip()
    if is_deepseek_model(m):
        return False
    if m in PARTNER_MODELS or m in PARTNER_MODEL_ALIASES:
        return True
    if (
        m.startswith("publishers/anthropic/")
        or m.startswith("publishers/fable/")
    ):
        return True
    if (
        m.startswith("claude-")
        or m.startswith("sonnet-")
        or m.startswith("opus-")
        or m.startswith("haiku-")
        or m.startswith("fable-")
        or m == "fable"
    ):
        return True
    return False


def is_fable_model(model: str) -> bool:
    if not model:
        return False
    m = model.lower().strip()
    return "fable" in m


def measure_partner_client_startup(
    project: Optional[str] = None,
    region: Optional[str] = None,
) -> float:
    t0 = time.perf_counter()
    import anthropic

    resolved_project = (
        project
        or os.environ.get("VERTEXAI_PROJECT")
        or os.environ.get("GCP_PROJECT")
        or os.environ.get("PROJECT_ID")
        or None
    )
    resolved_region = (
        region
        or os.environ.get("VERTEXAI_LOCATION")
        or os.environ.get("GCP_REGION")
        or os.environ.get("REGION")
        or "us-central1"
    )
    _ = anthropic.AnthropicVertex(project_id=resolved_project, region=resolved_region)
    return time.perf_counter() - t0


WORKSPACE_TOOLS = [
    {
        "name": "read_file",
        "description": "Read file contents from the workspace repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the workspace repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "content": {"type": "string", "description": "File contents to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact target string with replacement string in a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "target": {"type": "string", "description": "Exact text to find and replace"},
                "replacement": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "target", "replacement"],
        },
    },
    {
        "name": "run_command",
        "description": "Execute a shell command within the repository root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command string to execute"},
            },
            "required": ["command"],
        },
    },
]


def _safe_resolve_repo_path(repo_dir: Path, rel_path: str) -> Optional[Path]:
    try:
        resolved_repo = repo_dir.resolve()
        clean_rel = rel_path.lstrip("/\\")
        candidate = (resolved_repo / clean_rel).resolve()
        if candidate == resolved_repo or resolved_repo in candidate.parents:
            return candidate
        return None
    except Exception:
        return None


def execute_workspace_tool(tool_name: str, tool_input: Dict[str, Any], repo_dir: Path, *, limits: Optional[ExecutionLimits] = None) -> str:
    try:
        if tool_name == "read_file":
            path_str = str(tool_input.get("path", "")).strip()
            if not path_str:
                return "Error: missing \x27path\x27 parameter for read_file."
            target_path = _safe_resolve_repo_path(repo_dir, path_str)
            if target_path is None:
                return f"Error: path \x27{path_str}\x27 is outside repository directory."
            if not target_path.exists():
                return f"Error: file \x27{path_str}\x27 does not exist."
            if not target_path.is_file():
                return f"Error: \x27{path_str}\x27 is not a regular file."
            return target_path.read_text(encoding="utf-8", errors="replace")

        elif tool_name == "write_file":
            path_str = str(tool_input.get("path", "")).strip()
            if not path_str:
                return "Error: missing \x27path\x27 parameter for write_file."
            content = tool_input.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            target_path = _safe_resolve_repo_path(repo_dir, path_str)
            if target_path is None:
                return f"Error: path \x27{path_str}\x27 is outside repository directory."
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to {path_str}."

        elif tool_name == "edit_file":
            path_str = str(tool_input.get("path", "")).strip()
            if not path_str:
                return "Error: missing \x27path\x27 parameter for edit_file."
            target = tool_input.get("target")
            replacement = tool_input.get("replacement")
            if target is None or replacement is None:
                return "Error: edit_file requires both \x27target\x27 and \x27replacement\x27 parameters."
            target_str = str(target)
            replacement_str = str(replacement)
            target_path = _safe_resolve_repo_path(repo_dir, path_str)
            if target_path is None:
                return f"Error: path \x27{path_str}\x27 is outside repository directory."
            if not target_path.exists() or not target_path.is_file():
                return f"Error: file \x27{path_str}\x27 does not exist."
            content = target_path.read_text(encoding="utf-8", errors="replace")
            if target_str not in content:
                return f"Error: target string not found in \x27{path_str}\x27."
            new_content = content.replace(target_str, replacement_str, 1)
            target_path.write_text(new_content, encoding="utf-8")
            return f"Successfully edited \x27{path_str}\x27."

        elif tool_name == "run_command":
            cmd = tool_input.get("command") or tool_input.get("cmd", "")
            if not cmd:
                return "Error: missing \x27command\x27 parameter for run_command."
            cmd_str = str(cmd)

            # Security Interception: evaluate command safety before execution
            if evaluate_safety is not None:
                safety_res = evaluate_safety(cmd_str, is_headless=True)
                if isinstance(safety_res, dict) and safety_res.get("decision") in ("deny", "reject"):
                    reason = safety_res.get("reason", "Destructive command rejected.")
                    return f"Error: Command blocked by safety policy ({safety_res.get('decision')}): {reason}"

            limits = limits or limits_for_task(None)
            _, output = run_bounded_shell(cmd_str, repo_dir, limits.command_timeout_s)
            return output

        else:
            return f"Error: unknown tool \x27{tool_name}\x27."
    except Exception as exc:
        return f"Error executing tool \x27{tool_name}\x27: {exc}"


def _extract_thought(block: Any) -> Optional[str]:
    if isinstance(block, dict):
        if block.get("type") == "thinking" and block.get("thinking"):
            return str(block["thinking"])
        if block.get("thought"):
            return str(block["thought"])
        return None
    b_type = getattr(block, "type", None)
    if b_type == "thinking":
        thinking = getattr(block, "thinking", None)
        if isinstance(thinking, str) and thinking:
            return thinking
    thinking = getattr(block, "thinking", None)
    if isinstance(thinking, str) and thinking:
        return thinking
    return None


def _extract_tool_use(block: Any) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    if isinstance(block, dict):
        if block.get("type") == "tool_use":
            tool_id = str(block.get("id", ""))
            tool_name = str(block.get("name", ""))
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                tool_input = {}
            return tool_id, tool_name, tool_input
        return None
    b_type = getattr(block, "type", None)
    if b_type == "tool_use":
        tool_id = getattr(block, "id", "")
        if not isinstance(tool_id, str):
            tool_id = str(tool_id)
        tool_name = getattr(block, "name", "")
        if not isinstance(tool_name, str):
            tool_name = str(tool_name)
        tool_input = getattr(block, "input", {})
        if not isinstance(tool_input, dict):
            try:
                tool_input = dict(tool_input)
            except Exception:
                tool_input = {}
        return tool_id, tool_name, tool_input
    return None


def _extract_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        return str(block.get("text", ""))
    t = getattr(block, "text", None)
    if isinstance(t, str):
        return t
    return ""


def _get_anthropic():
    if "anthropic" in sys.modules:
        mod = sys.modules["anthropic"]
        if mod is not None:
            return mod
        return None
    try:
        import anthropic
        return anthropic
    except (ImportError, AttributeError):
        return None


def _get_aiplatform():
    if "google.cloud.aiplatform" in sys.modules:
        mod = sys.modules["google.cloud.aiplatform"]
        if mod is not None:
            return mod
        return None
    try:
        from google.cloud import aiplatform
        return aiplatform
    except (ImportError, AttributeError):
        pass
    try:
        import google.cloud.aiplatform as aiplatform
        return aiplatform
    except (ImportError, AttributeError):
        return None


def _get_genai():
    if "google.genai" in sys.modules:
        mod = sys.modules["google.genai"]
        if mod is not None:
            return mod
        return None
    try:
        from google import genai
        return genai
    except (ImportError, AttributeError):
        pass
    try:
        import google.genai as genai
        return genai
    except (ImportError, AttributeError):
        return None


def execute_claude_model_agent(
    model: str,
    task_brief: str,
    repo_dir: Path,
    task_item: Any = None,
    task_index: int = 0,
    project: Optional[str] = None,
    location: Optional[str] = None,
    messenger: Optional[Any] = None,
    *,
    limits: Optional[ExecutionLimits] = None,
) -> Tuple[str, str]:
    limits = limits or limits_for_task(task_item)
    anthropic = _get_anthropic()
    if anthropic is None:
        return "BLOCKED", "Missing dependency: anthropic[vertex] Python package is not installed."

    resolved_project = (
        project
        or os.environ.get("VERTEXAI_PROJECT")
        or os.environ.get("GCP_PROJECT")
        or os.environ.get("PROJECT_ID")
        or None
    )
    resolved_region = (
        location
        or os.environ.get("VERTEXAI_LOCATION")
        or os.environ.get("GCP_REGION")
        or os.environ.get("REGION")
        or "us-central1"
    )

    try:
        client = anthropic.AnthropicVertex(
            project_id=resolved_project,
            region=resolved_region,
        )
        system_prompt = (
            os.environ.get("AGYSTACK_WORKER_SYSTEM_PROMPT")
            or DEFAULT_PARTNER_SYSTEM_PROMPT
        )
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": task_brief}
        ]
        max_turns = limits.max_agent_turns
        consumed = 0
        last_tool = ""
        last_text = ""

        for turn in range(max_turns):
            last_text = ""
            consumed += 1
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=WORKSPACE_TOOLS,
            )

            content_blocks = []
            if hasattr(response, "content") and response.content:
                content_blocks = response.content
            elif isinstance(response, list):
                content_blocks = response

            thinking_text = ""
            tool_uses = []
            text_parts = []

            for block in content_blocks:
                th = _extract_thought(block)
                if th:
                    thinking_text += th + "\n"

                tu = _extract_tool_use(block)
                if tu:
                    tool_uses.append(tu)

                txt = _extract_text(block)
                if txt:
                    text_parts.append(txt)

            if thinking_text.strip():
                emit_thought(task_index, thinking_text.strip())

            if text_parts:
                last_text = "\n".join(text_parts)

            if not tool_uses:
                if not last_text:
                    if isinstance(response, str):
                        last_text = response
                    elif hasattr(response, "text") and isinstance(response.text, str):
                        last_text = response.text
                return _evaluate_agent_status(last_text)

            messages.append({
                "role": "assistant",
                "content": response.content if hasattr(response, "content") else content_blocks,
            })

            tool_results = []
            for tool_id, tool_name, tool_input in tool_uses:
                emit_tool_invocation(task_index, tool_name, tool_input)
                last_tool = tool_name
                result_str = execute_workspace_tool(tool_name, tool_input, repo_dir, limits=limits)
                emit_tool_result(task_index, tool_name, result_str)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_str,
                })

            messages.append({
                "role": "user",
                "content": tool_results,
            })

        return exhaustion_result(repo_dir, max_turns, consumed, last_tool, last_text)
    except Exception as exc:
        return "ISSUES", f"Partner model execution exception: {exc}"


def execute_fable_model_agent(
    model: str,
    task_brief: str,
    repo_dir: Path,
    task_item: Any = None,
    task_index: int = 0,
    project: Optional[str] = None,
    location: Optional[str] = None,
    messenger: Optional[Any] = None,
    *,
    limits: Optional[ExecutionLimits] = None,
) -> Tuple[str, str]:
    limits = limits or limits_for_task(task_item)

    aiplatform = _get_aiplatform()
    if aiplatform is None:
        return "BLOCKED", "Missing dependency: google-cloud-aiplatform Python package is not installed."

    resolved_project = (
        project
        or os.environ.get("VERTEXAI_PROJECT")
        or os.environ.get("GCP_PROJECT")
        or os.environ.get("PROJECT_ID")
        or None
    )
    resolved_region = (
        location
        or os.environ.get("VERTEXAI_LOCATION")
        or os.environ.get("GCP_REGION")
        or os.environ.get("REGION")
        or "us-central1"
    )

    try:
        if hasattr(aiplatform, "init"):
            aiplatform.init(project=resolved_project, location=resolved_region)

        endpoint = None
        if hasattr(aiplatform, "Endpoint"):
            try:
                endpoint = aiplatform.Endpoint(endpoint_name=model)
            except TypeError:
                try:
                    endpoint = aiplatform.Endpoint(model)
                except Exception:
                    endpoint = None
            except Exception:
                endpoint = None

        system_prompt = (
            os.environ.get("AGYSTACK_WORKER_SYSTEM_PROMPT")
            or DEFAULT_PARTNER_SYSTEM_PROMPT
        )
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": task_brief}
        ]
        max_turns = limits.max_agent_turns
        consumed = 0
        last_tool = ""
        last_text = ""

        for turn in range(max_turns):
            last_text = ""
            response = None
            consumed += 1
            if endpoint is not None and hasattr(endpoint, "predict"):
                response = endpoint.predict(
                    instances=[{
                        "prompt": task_brief if turn == 0 else "",
                        "messages": messages,
                        "system": system_prompt,
                    }],
                    parameters={"tools": WORKSPACE_TOOLS},
                )
            elif hasattr(aiplatform, "predict"):
                response = aiplatform.predict(
                    endpoint=model,
                    instances=[{"messages": messages}],
                )
            else:
                return "ISSUES", "Vertex Model Garden predict API client not available on aiplatform."

            content_blocks = []
            if hasattr(response, "content") and response.content:
                content_blocks = response.content
            elif hasattr(response, "predictions") and response.predictions:
                for pred in response.predictions:
                    if isinstance(pred, dict) and "content" in pred:
                        c = pred["content"]
                        if isinstance(c, list):
                            content_blocks.extend(c)
                        else:
                            content_blocks.append(c)
                    else:
                        content_blocks.append(pred)
            elif isinstance(response, list):
                content_blocks = response

            thinking_text = ""
            tool_uses = []
            text_parts = []

            for block in content_blocks:
                th = _extract_thought(block)
                if th:
                    thinking_text += th + "\n"

                tu = _extract_tool_use(block)
                if tu:
                    tool_uses.append(tu)

                txt = _extract_text(block)
                if txt:
                    text_parts.append(txt)

            if thinking_text.strip():
                emit_thought(task_index, thinking_text.strip())

            if text_parts:
                last_text = "\n".join(text_parts)

            if not tool_uses:
                if not last_text:
                    if isinstance(response, str):
                        last_text = response
                    elif hasattr(response, "text") and isinstance(response.text, str):
                        last_text = response.text
                    elif hasattr(response, "predictions") and response.predictions:
                        p0 = response.predictions[0]
                        if isinstance(p0, str):
                            last_text = p0
                        elif isinstance(p0, dict) and "text" in p0:
                            last_text = str(p0["text"])
                return _evaluate_agent_status(last_text)

            messages.append({
                "role": "assistant",
                "content": content_blocks,
            })

            tool_results = []
            for tool_id, tool_name, tool_input in tool_uses:
                emit_tool_invocation(task_index, tool_name, tool_input)
                last_tool = tool_name
                result_str = execute_workspace_tool(tool_name, tool_input, repo_dir, limits=limits)
                emit_tool_result(task_index, tool_name, result_str)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_str,
                })

            messages.append({
                "role": "user",
                "content": tool_results,
            })

        return exhaustion_result(repo_dir, max_turns, consumed, last_tool, last_text)
    except Exception as exc:
        return "ISSUES", f"Vertex Model Garden Fable execution exception: {exc}"


def execute_deepseek_model_agent(
    model: str,
    task_brief: str,
    repo_dir: Path,
    task_item: Any = None,
    task_index: int = 0,
    project: Optional[str] = None,
    location: Optional[str] = None,
    messenger: Optional[Any] = None,
    *,
    limits: Optional[ExecutionLimits] = None,
) -> Tuple[str, str]:
    limits = limits or limits_for_task(task_item)
    genai = _get_genai()
    if genai is None:
        return "BLOCKED", "Missing dependency: google-genai Python package is not installed."

    resolved_project = (
        project
        or os.environ.get("VERTEXAI_PROJECT")
        or os.environ.get("GCP_PROJECT")
        or os.environ.get("PROJECT_ID")
        or None
    )
    resolved_location = os.environ.get("VERTEXAI_LOCATION") or "global"

    if not model.startswith("publishers/"):
        model = PARTNER_MODEL_ALIASES.get(model.lower()) or "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas"

    try:
        import re

        client_kwargs = {
            "vertexai": True,
            "project": resolved_project,
            "location": resolved_location,
        }
        if hasattr(genai.types, "HttpOptions"):
            client_kwargs["http_options"] = genai.types.HttpOptions(timeout=120000)

        client = genai.Client(**client_kwargs)

        function_declarations = [
            genai.types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["input_schema"],
            )
            for t in WORKSPACE_TOOLS
        ]
        tool = genai.types.Tool(function_declarations=function_declarations)

        system_prompt = (
            os.environ.get("AGYSTACK_WORKER_SYSTEM_PROMPT")
            or DEFAULT_PARTNER_SYSTEM_PROMPT
        )
        config = genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[tool],
            temperature=0.0,
        )

        contents: List[Any] = [
            genai.types.Content(
                role="user",
                parts=[genai.types.Part.from_text(text=task_brief)],
            )
        ]
        max_turns = limits.max_agent_turns
        consumed = 0
        last_tool = ""
        last_text = ""

        for turn in range(max_turns):
            if consumed >= max_turns:
                return exhaustion_result(repo_dir, max_turns, consumed, last_tool, last_text)
            last_text = ""
            response = None
            for attempt in range(5):
                if consumed >= max_turns:
                    return exhaustion_result(repo_dir, max_turns, consumed, last_tool, last_text)
                try:
                    consumed += 1
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=config,
                    )
                    break
                except Exception as call_exc:
                    err_str = str(call_exc).lower()
                    if (
                        "503" in err_str
                        or "unavailable" in err_str
                        or "429" in err_str
                        or "resource_exhausted" in err_str
                        or "deadline" in err_str
                        or "connection" in err_str
                    ) and attempt < 4 and consumed < max_turns:
                        backoff = (2 ** attempt) * 2
                        emit_milestone(task_index, "RETRY", f"Transient {call_exc}; retrying in {backoff}s (attempt {attempt + 1}/5)...")
                        time.sleep(backoff)
                    elif consumed >= max_turns:
                        return exhaustion_result(repo_dir, max_turns, consumed, last_tool, str(call_exc))
                    else:
                        raise

            candidate_parts = []
            if hasattr(response, "candidates") and response.candidates:
                c0 = response.candidates[0]
                if hasattr(c0, "content") and c0.content:
                    candidate_parts = getattr(c0.content, "parts", []) or []

            # Handle thoughts: check part.thought or <think>...</think> in text
            for part in candidate_parts:
                th = getattr(part, "thought", None)
                if th:
                    if isinstance(th, str) and th.strip():
                        emit_thought(task_index, th.strip())
                    elif isinstance(th, bool) and getattr(part, "text", None):
                        emit_thought(task_index, str(part.text).strip())

                ptxt = getattr(part, "text", None)
                if ptxt and isinstance(ptxt, str) and not th:
                    for m in re.finditer(r"<think>(.*?)</think>", ptxt, re.DOTALL):
                        val = m.group(1).strip()
                        if val:
                            emit_thought(task_index, val)

            # Check function calls
            func_calls = []
            if hasattr(response, "function_calls") and response.function_calls:
                func_calls = response.function_calls
            else:
                for part in candidate_parts:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        func_calls.append(fc)

            try:
                response_text = getattr(response, "text", "")
                last_text = response_text if isinstance(response_text, str) else ""
            except Exception:
                last_text = ""

            if not func_calls:
                resp_text = None
                try:
                    resp_text = getattr(response, "text", None)
                except Exception:
                    pass

                if resp_text and isinstance(resp_text, str) and not candidate_parts:
                    for m in re.finditer(r"<think>(.*?)</think>", resp_text, re.DOTALL):
                        val = m.group(1).strip()
                        if val:
                            emit_thought(task_index, val)

                if resp_text and isinstance(resp_text, str) and resp_text.strip():
                    last_text = resp_text
                elif candidate_parts:
                    text_pieces = [
                        getattr(p, "text", "") for p in candidate_parts if getattr(p, "text", None)
                    ]
                    last_text = "\n".join(text_pieces).strip()

                if not last_text and consumed >= max_turns:
                    return exhaustion_result(repo_dir, max_turns, consumed, last_tool, last_text)
                if not last_text:
                    contents.append(genai.types.Content(
                        role="model",
                        parts=[genai.types.Part.from_text(text="")]
                    ))
                    contents.append(genai.types.Content(
                        role="user",
                        parts=[genai.types.Part.from_text(text="Give your final summary. End with exactly one standalone unquoted status line outside code fences, [STATUS: PASS], [STATUS: ISSUES], or [STATUS: BLOCKED].")]
                    ))
                    continue

                cleaned_text = re.sub(r"<think>.*?</think>", "", last_text, flags=re.DOTALL).strip()
                return _evaluate_agent_status(cleaned_text)

            # Filter out empty text parts so DeepSeek does not echo empty text on next turn
            clean_parts = [
                p for p in candidate_parts
                if not (getattr(p, "text", None) == "" and not getattr(p, "function_call", None))
            ]
            contents.append(genai.types.Content(role="model", parts=clean_parts))

            # Execute workspace tools and append user response parts
            response_parts = []
            for fc in func_calls:
                tool_name = getattr(fc, "name", "")
                tool_input = getattr(fc, "args", {})
                if not isinstance(tool_input, dict):
                    try:
                        tool_input = dict(tool_input)
                    except Exception:
                        tool_input = {}
                emit_tool_invocation(task_index, tool_name, tool_input)
                last_tool = tool_name
                result_str = execute_workspace_tool(tool_name, tool_input, repo_dir, limits=limits)
                emit_tool_result(task_index, tool_name, result_str)
                response_parts.append(
                    genai.types.Part.from_function_response(
                        name=tool_name,
                        response={"result": result_str},
                    )
                )

            contents.append(genai.types.Content(role="user", parts=response_parts))

        return exhaustion_result(repo_dir, max_turns, consumed, last_tool, last_text)
    except Exception as exc:
        return "ISSUES", f"DeepSeek model execution exception: {exc}"


def execute_partner_model_agent(
    model: str,
    task_brief: str,
    repo_dir: Path,
    task_item: Any = None,
    task_index: int = 0,
    project: Optional[str] = None,
    location: Optional[str] = None,
    messenger: Optional[Any] = None,
    *,
    limits: Optional[ExecutionLimits] = None,
) -> Tuple[str, str]:
    limits = limits or limits_for_task(task_item)
    if is_deepseek_model(model):
        return execute_deepseek_model_agent(
            model=model,
            task_brief=task_brief,
            repo_dir=repo_dir,
            task_item=task_item,
            task_index=task_index,
            project=project,
            location=location,
            messenger=messenger,
            limits=limits,
        )
    if is_fable_model(model):
        return execute_fable_model_agent(
            model=model,
            task_brief=task_brief,
            repo_dir=repo_dir,
            task_item=task_item,
            task_index=task_index,
            project=project,
            location=location,
            messenger=messenger,
            limits=limits,
        )
    return execute_claude_model_agent(
        model=model,
        task_brief=task_brief,
        repo_dir=repo_dir,
        task_item=task_item,
        task_index=task_index,
        project=project,
        location=location,
        messenger=messenger,
        limits=limits,
    )
