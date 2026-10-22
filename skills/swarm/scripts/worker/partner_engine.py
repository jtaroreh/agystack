#!/usr/bin/env python3
"""
Partner model engine for Vertex AI Model Garden endpoints (Claude and Fable).
Handles model alias resolution, workspace tool execution with pre-tool safety
interception, AnthropicVertex client integration, and autonomous turn loops.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
}

PARTNER_MODELS = {
    "claude-3-7-sonnet@20250219",
    "claude-3-5-sonnet-v2@20241022",
    "claude-3-5-haiku@20241022",
    "claude-3-opus@20240229",
    "fable-5-1",
    "fable",
}


def is_partner_model(model: str) -> bool:
    if not model:
        return False
    m = model.lower().strip()
    if m in PARTNER_MODELS or m in PARTNER_MODEL_ALIASES:
        return True
    if m.startswith("publishers/anthropic/") or m.startswith("publishers/fable/"):
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


def execute_workspace_tool(tool_name: str, tool_input: Dict[str, Any], repo_dir: Path) -> str:
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
                    return f"Error: Command blocked by safety policy ({safety_res.get(decision)}): {reason}"

            timeout = int(os.environ.get("COMMAND_TIMEOUT", "300"))
            try:
                res = subprocess.run(
                    cmd_str,
                    shell=True,
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                output = res.stdout
                if res.stderr:
                    if output:
                        output += "\n" + res.stderr
                    else:
                        output = res.stderr
                return f"Exit code {res.returncode}:\n{output}"
            except subprocess.TimeoutExpired:
                return f"Error: command timed out after {timeout} seconds: {cmd_str}"
            except Exception as e:
                return f"Error executing command: {e}"

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


def execute_claude_model_agent(
    model: str,
    task_brief: str,
    repo_dir: Path,
    task_item: Any = None,
    task_index: int = 0,
    project: Optional[str] = None,
    location: Optional[str] = None,
    messenger: Optional[Any] = None,
) -> Tuple[str, str]:
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
            or "You are a specialized poteto coding delegate for agystack."
        )
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": task_brief}
        ]
        max_turns = 30
        last_text = ""

        for turn in range(max_turns):
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
                result_str = execute_workspace_tool(tool_name, tool_input, repo_dir)
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

        return _evaluate_agent_status(last_text)
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
) -> Tuple[str, str]:

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
            or "You are a specialized poteto coding delegate for agystack."
        )
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": task_brief}
        ]
        max_turns = 30
        last_text = ""

        for turn in range(max_turns):
            response = None
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
                result_str = execute_workspace_tool(tool_name, tool_input, repo_dir)
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

        return _evaluate_agent_status(last_text)
    except Exception as exc:
        return "ISSUES", f"Vertex Model Garden Fable execution exception: {exc}"


def execute_partner_model_agent(
    model: str,
    task_brief: str,
    repo_dir: Path,
    task_item: Any = None,
    task_index: int = 0,
    project: Optional[str] = None,
    location: Optional[str] = None,
    messenger: Optional[Any] = None,
) -> Tuple[str, str]:
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
    )


def _evaluate_agent_status(agent_text: str) -> Tuple[str, str]:
    import re
    match = re.search(r"\[STATUS:\s*(PASS|ISSUES|BLOCKED|DEV_IMPROVED)\s*\]", agent_text, re.IGNORECASE)
    if match:
        st = match.group(1).upper()
        if st == "DEV_IMPROVED":
            return "PASS", agent_text
        return st, agent_text
    return "ISSUES", agent_text
