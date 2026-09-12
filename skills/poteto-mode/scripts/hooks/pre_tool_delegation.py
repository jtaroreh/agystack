#!/usr/bin/env python3
"""
Antigravity PreToolUse lifecycle hook for coordinator code delegation.
Intercepts direct write_to_file and replace_file_content tool calls in coordinator sessions
and enforces delegation of non-trivial code edits (>50 lines) to poteto-agent.
Outputs {} and exits 0 on all safe/allowed code paths. Never crashes.
"""

import json
import os
import re
import sys
from pathlib import Path


def is_truthy(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def is_falsy(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in ("0", "false", "no", "off")


def is_subagent_environment() -> bool:
    """Check if environment indicates execution inside a subagent session."""
    if os.environ.get("ANTIGRAVITY_SUBAGENT_ID"):
        return True
    if is_truthy(os.environ.get("SUBAGENT")):
        return True
    if is_truthy(os.environ.get("IS_SUBAGENT")):
        return True
    if os.environ.get("CLOUD_RUN_TASK_INDEX"):
        # Cloud Run workers are task execution delegates (allow_subagents=False)
        return True
    return False


def is_headless_environment() -> bool:
    """Check if execution is running in headless, automated, or CI environment."""
    if is_truthy(os.environ.get("NON_INTERACTIVE")):
        return True
    if is_truthy(os.environ.get("CI")):
        return True
    return False


def is_subagents_disabled_in_headless() -> bool:
    """Check if subagent invocation is explicitly disabled in headless environment."""
    if is_truthy(os.environ.get("HEADLESS_NO_SUBAGENTS")):
        return True
    if is_falsy(os.environ.get("ALLOW_SUBAGENTS")):
        return True
    return False


def is_subagent_transcript(transcript_path: str | None) -> bool:
    """Check if transcript file contains subagent prompts in its first message."""
    if not transcript_path:
        return False
    try:
        t_path = Path(transcript_path).expanduser().resolve()
        if not t_path.is_file():
            return False

        # First, check Antigravity conversation database if accessible:
        try:
            cid = t_path.parent.parent.parent.name
            conv_db = (
                t_path.parent.parent.parent.parent.parent
                / "conversations"
                / f"{cid}.db"
            )
            if conv_db.is_file():
                import sqlite3

                with sqlite3.connect(str(conv_db)) as con:
                    row = (
                        con.cursor()
                        .execute("SELECT * FROM trajectory_metadata_blob;")
                        .fetchone()
                    )
                    blob = row[1] if row and len(row) > 1 else b""
                    if isinstance(blob, bytes) and (
                        b"poteto-agent" in blob or b"adversarial reviewer" in blob
                    ):
                        return True
        except Exception:
            pass

        # Second, inspect Step 0 (the initial prompt) only from transcript.jsonl:
        with open(t_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    step_type = data.get("type")
                    step_source = data.get("source")
                    if step_source in ("MODEL", "SYSTEM") and step_type not in (
                        "USER_INPUT",
                        None,
                    ):
                        continue
                    content = str(data.get("content", "")).lower()
                    if "poteto-agent" in content or "adversarial reviewer" in content:
                        return True
                    break
                except Exception:
                    continue
    except Exception:
        pass
    return False


DIRECT_OVERRIDE_PATTERN = re.compile(
    r"\b(?:do\s+this\s+directly|no\s+subagents?|without\s+subagents?|execute\s+directly|edit\s+directly|write\s+directly|direct\s+execution|user\s+override)\b",
    re.IGNORECASE,
)


def has_user_direct_override(transcript_path: str | None) -> bool:
    """Check if user explicitly instructed direct execution via environment or transcript."""
    if is_truthy(os.environ.get("USER_OVERRIDE")):
        return True
    if is_truthy(os.environ.get("DIRECT_EXECUTION")):
        return True
    if is_truthy(os.environ.get("NO_SUBAGENTS")):
        return True

    if not transcript_path:
        return False

    try:
        t_path = Path(transcript_path).expanduser().resolve()
        if not t_path.is_file():
            return False

        with open(t_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]

        recent_lines = lines[-50:] if len(lines) > 50 else lines
        for line in reversed(recent_lines):
            try:
                data = json.loads(line)
                step_source = data.get("source")
                step_type = data.get("type")
                if step_source in ("MODEL", "SYSTEM") or step_type in (
                    "PLANNER_RESPONSE",
                    "GENERIC",
                    "SYSTEM_MESSAGE",
                    "CHECKPOINT",
                ):
                    continue
                if step_type and step_type != "USER_INPUT":
                    continue
                if step_source and step_source not in ("USER_EXPLICIT", "USER"):
                    continue

                content = data.get("content", "")
                text_chunks = []
                if isinstance(content, str):
                    text_chunks.append(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            text_chunks.append(str(item["text"]))
                        elif isinstance(item, str):
                            text_chunks.append(item)
                full_text = " ".join(text_chunks)
                if DIRECT_OVERRIDE_PATTERN.search(full_text):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def count_code_lines(content: str) -> int:
    """Count lines of code in content string."""
    if not content:
        return 0
    return len(content.splitlines())


def evaluate_delegation(
    tool_name: str,
    target_file: str,
    content: str,
    transcript_path: str | None,
    target_content: str = "",
) -> dict:
    """Evaluate whether the tool call is permitted directly or must be delegated."""
    if tool_name not in ("write_to_file", "replace_file_content"):
        return {}

    clean_path = target_file.strip().strip("'\"").replace("\\", "/")
    if not clean_path:
        return {}

    # Permitted markdown
    if clean_path.lower().endswith((".md", ".markdown")):
        return {}

    # Permitted files (.gitignore, score.json, results.tsv)
    file_name = Path(clean_path).name.lower()
    if file_name == ".gitignore" or file_name in ("score.json", "results.tsv"):
        return {}

    # Permitted brain store directory
    if ".gemini/antigravity/brain" in clean_path or ".antigravity/brain" in clean_path:
        return {}

    # Safe scratch / slices / receipts directory resolution
    try:
        abs_target = Path(clean_path).expanduser().resolve()
        cwd = Path.cwd().resolve()
        rel_target = abs_target.relative_to(cwd)
        if rel_target.parts and rel_target.parts[0] in ("scratch", ".slices", "receipts"):
            return {}
    except Exception:
        parts = Path(clean_path).parts
        if parts and parts[0] in ("scratch", ".slices", "receipts"):
            return {}

    # Deletion line counting
    replacement_lines = count_code_lines(content)
    target_lines = count_code_lines(target_content) if tool_name == "replace_file_content" else 0
    line_count = max(replacement_lines, target_lines)

    # Trivial check (<= 50 lines allowed directly for both existing and new files)
    if line_count <= 50:
        return {}

    # Subagent or user direct override check
    if (
        is_subagent_environment()
        or is_subagent_transcript(transcript_path)
        or has_user_direct_override(transcript_path)
    ):
        return {}

    # Non-trivial check (>50 lines)
    is_non_trivial = line_count > 50

    if not is_non_trivial:
        return {}

    # Headless / CI environments
    if is_headless_environment():
        if is_subagents_disabled_in_headless():
            return {}
        return {
            "decision": "reject",
            "reason": (
                "Coordinator Code Delegation Invariant: Non-trivial source code modifications "
                "(>50 lines) must be delegated to a poteto-agent subagent via invoke_subagent."
            ),
        }

    # Interactive environments
    return {
        "decision": "force_ask",
        "reason": (
            "Coordinator Code Delegation Invariant: Non-trivial source code modification "
            "(>50 lines) detected in coordinator session. Confirm direct execution or delegate "
            "to poteto-agent via invoke_subagent."
        ),
    }


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            sys.stdout.write("{}\n")
            sys.exit(0)

        payload = json.loads(raw_input)
        tool_call = payload.get("toolCall", {})
        tool_name = tool_call.get("name")

        if tool_name not in ("write_to_file", "replace_file_content"):
            sys.stdout.write("{}\n")
            sys.exit(0)

        args = tool_call.get("args", {})
        target_file = (
            args.get("TargetFile")
            or args.get("target_file")
            or args.get("AbsolutePath")
            or args.get("FilePath")
            or args.get("path")
            or ""
        )

        content = (
            args.get("CodeContent")
            or args.get("code_content")
            or args.get("Content")
            or args.get("content")
            or args.get("ReplacementContent")
            or args.get("replacement_content")
            or args.get("NewContent")
            or args.get("new_content")
            or args.get("Replacement")
            or args.get("replacement")
            or ""
        )

        target_content = (
            args.get("TargetContent")
            or args.get("target_content")
            or args.get("OldContent")
            or args.get("old_content")
            or ""
        )

        transcript_path = (
            payload.get("transcriptPath")
            or payload.get("transcript_path")
            or args.get("transcriptPath")
            or args.get("transcript_path")
        )

        result = evaluate_delegation(
            tool_name=tool_name,
            target_file=target_file,
            content=content,
            transcript_path=transcript_path,
            target_content=target_content,
        )
        sys.stdout.write(json.dumps(result) + "\n")
        sys.exit(0)
    except Exception:
        sys.stdout.write("{}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
