#!/usr/bin/env python3
"""
Antigravity PreToolUse lifecycle hook for scoped destructive command safety.
Intercepts run_command calls and prompts confirmation for destructive patterns
(root deletion, trunk force-push, database drop) in interactive sessions.
In headless/CI/Cloud Run environments, rejects destructive commands with decision: reject.
Outputs {} and exits 0 on all safe code paths. Never crashes.
"""

import json
import os
import re
import shlex
import sys

DROP_DATABASE_PATTERN = re.compile(
    r"\bdrop\s+database\b(?:\s+if\s+exists)?\s+([`\"'\[]?\w+[`\"'\]]?)", re.IGNORECASE
)


def is_root_deletion(command: str) -> bool:
    """
    Detect rm with recursive (-r, -R, --recursive) and force (-f, --force) flags,
    whether combined (-rf, -fr, -Rf, -r -f, -f -r, etc.) targeting /, /*, "/", '/',
    or using --no-preserve-root.
    """
    subcommands = re.split(r"(?:&&|\|\||[;\n&|])", command)
    for subcmd in subcommands:
        subcmd = subcmd.strip()
        if not subcmd:
            continue
        try:
            tokens = shlex.split(subcmd)
        except Exception:
            tokens = subcmd.split()
        if not tokens:
            continue

        rm_indices = [i for i, t in enumerate(tokens) if t == "rm" or t.endswith("/rm")]
        for idx in rm_indices:
            rm_args = tokens[idx + 1 :]
            has_r = False
            has_f = False
            has_no_preserve = False
            targets = []

            for arg in rm_args:
                if arg == "--no-preserve-root":
                    has_no_preserve = True
                elif arg == "--recursive":
                    has_r = True
                elif arg == "--force":
                    has_f = True
                elif arg.startswith("-") and not arg.startswith("--"):
                    chars = set(arg[1:])
                    if "r" in chars or "R" in chars:
                        has_r = True
                    if "f" in chars:
                        has_f = True
                else:
                    clean_arg = arg.strip("'\"")
                    targets.append(clean_arg)

            root_targets = {"/", "/*"}
            is_root_target = any(t in root_targets for t in targets)

            if (has_r and has_f and is_root_target) or (
                has_no_preserve and (is_root_target or not targets)
            ):
                return True
    return False


def is_trunk_force_push(command: str) -> bool:
    """
    Detect git push where --force (excluding --force-with-lease), -f, or leading + refspec
    targets main or master (e.g. origin main, main, master, origin master, +HEAD:main, +refs/heads/main),
    regardless of whether the force flag comes before or after the branch name.
    """
    subcommands = re.split(r"(?:&&|\|\||[;\n&|])", command)
    for subcmd in subcommands:
        subcmd = subcmd.strip()
        if not subcmd:
            continue
        try:
            tokens = shlex.split(subcmd)
        except Exception:
            tokens = subcmd.split()
        if not tokens:
            continue

        git_indices = [i for i, t in enumerate(tokens) if t == "git" or t.endswith("/git")]
        for idx in git_indices:
            if idx + 1 < len(tokens) and tokens[idx + 1] == "push":
                push_args = tokens[idx + 2 :]
                has_force = False
                has_plus_trunk = False
                targets = []

                for arg in push_args:
                    if arg in ("--force", "-f"):
                        has_force = True
                    elif arg.startswith("--force-with-lease"):
                        pass
                    elif arg.startswith("-") and not arg.startswith("--"):
                        chars = set(arg[1:])
                        if "f" in chars:
                            has_force = True
                    elif arg.startswith("+"):
                        ref = arg[1:]
                        dest = ref.split(":")[-1]
                        dest_branch = dest.split("/")[-1]
                        if dest_branch in ("main", "master"):
                            has_plus_trunk = True
                    else:
                        ref = arg
                        dest = ref.split(":")[-1]
                        dest_branch = dest.split("/")[-1]
                        if dest_branch in ("main", "master"):
                            targets.append(dest_branch)

                if has_plus_trunk or (has_force and len(targets) > 0):
                    return True
    return False


def is_drop_database(command: str) -> bool:
    """
    Detect drop database (case-insensitive) including quoted identifiers like "testdb" or `testdb`.
    """
    return bool(DROP_DATABASE_PATTERN.search(command))


def evaluate_safety(command: str, is_headless: bool) -> dict:
    cmd = command.strip()
    if not cmd:
        return {}

    is_destructive = False
    reason_detail = ""

    if is_root_deletion(cmd):
        is_destructive = True
        reason_detail = "recursive root deletion (rm -rf /)"
    elif is_trunk_force_push(cmd):
        is_destructive = True
        reason_detail = "force-push to protected trunk branch (main/master)"
    elif is_drop_database(cmd):
        is_destructive = True
        reason_detail = "drop database statement"

    if is_destructive:
        if is_headless:
            return {
                "decision": "reject",
                "reason": "Destructive command rejected in headless/automated environment.",
            }
        return {
            "decision": "force_ask",
            "reason": f"Destructive command detected: {reason_detail}. Confirm before execution.",
        }

    return {}


def is_headless_environment() -> bool:
    if os.environ.get("NON_INTERACTIVE") == "1":
        return True
    if os.environ.get("CI", "").lower() in ("1", "true"):
        return True
    if os.environ.get("CLOUD_RUN_TASK_INDEX"):
        return True
    return False


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            sys.stdout.write("{}\n")
            sys.exit(0)

        payload = json.loads(raw_input)
        tool_call = payload.get("toolCall", {})
        tool_name = tool_call.get("name")

        if tool_name != "run_command":
            sys.stdout.write("{}\n")
            sys.exit(0)

        args = tool_call.get("args", {})
        command = args.get("command") or args.get("CommandLine") or args.get("Command") or ""

        is_headless = is_headless_environment()
        result = evaluate_safety(command, is_headless=is_headless)
        sys.stdout.write(json.dumps(result) + "\n")
        sys.exit(0)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"PreToolSafetyHook: JSON decode error: {e}\n")
        sys.stdout.write("{}\n")
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"PreToolSafetyHook: Unexpected error: {e}\n")
        sys.stdout.write("{}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
