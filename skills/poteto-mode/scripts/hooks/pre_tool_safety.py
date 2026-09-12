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
import subprocess
import sys
from pathlib import Path

DROP_DATABASE_PATTERN = re.compile(
    r"\bdrop\s+database\b(?:\s+if\s+exists)?\s+([`\"'\[]?\w+[`\"'\]]?)", re.IGNORECASE
)

PROTECTED_PATHS = {
    "/",
    "/*",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/lib",
    "/boot",
    "/dev",
    "/home",
    "/root",
    "~",
    "$HOME",
}

CANONICAL_DIRS = [
    Path("/"),
    Path("/etc"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/var"),
    Path("/lib"),
    Path("/boot"),
    Path("/dev"),
    Path("/home"),
    Path("/root"),
    Path.home().resolve(),
]

DB_CLIENTS = {"psql", "mysql", "sqlite3", "mariadb", "mongosh", "sqlcmd"}
READ_ONLY_COMMANDS = {
    "grep",
    "rg",
    "find",
    "cat",
    "bat",
    "head",
    "tail",
    "less",
    "more",
    "pytest",
    "git",
}


def get_all_commands(command: str, max_depth: int = 5) -> list[str]:
    """
    Extract subcommands split by shell operators and detect subshell invocations
    (sh -c, bash -c, zsh -c, eval), recursively returning all nested command strings.
    """
    results = [command]
    if max_depth <= 0:
        return results

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

        for i, token in enumerate(tokens):
            verb = token.split("/")[-1]
            if verb in ("sh", "bash", "zsh", "dash", "ksh") and i + 1 < len(tokens):
                next_arg = tokens[i + 1]
                if next_arg == "-c" and i + 2 < len(tokens) or (
                    next_arg.startswith("-")
                    and "c" in next_arg[1:]
                    and i + 2 < len(tokens)
                ):
                    inner = tokens[i + 2]
                    results.extend(get_all_commands(inner, max_depth - 1))
            elif verb == "eval" and i + 1 < len(tokens):
                inner = " ".join(tokens[i + 1 :])
                results.extend(get_all_commands(inner, max_depth - 1))

    return results


def is_protected_target(clean_arg: str) -> bool:
    if clean_arg in PROTECTED_PATHS:
        return True
    if clean_arg.endswith("/*") and clean_arg[:-2] in PROTECTED_PATHS:
        return True
    if clean_arg == "$HOME":
        return True
    try:
        resolved = Path(clean_arg).expanduser().resolve()
        if resolved == Path("/"):
            return True
        for p in CANONICAL_DIRS:
            try:
                if resolved == p.resolve():
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def is_root_deletion(command: str) -> bool:
    """
    Detect rm with recursive (-r, -R, --recursive) and force (-f, --force) flags
    targeting protected system paths (/, /etc, /usr, ~, $HOME, etc.) or using --no-preserve-root.
    Recursively inspects subshells.
    """
    for cmd in get_all_commands(command):
        subcommands = re.split(r"(?:&&|\|\||[;\n&|])", cmd)
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

            rm_indices = [
                i for i, t in enumerate(tokens) if t == "rm" or t.endswith("/rm")
            ]
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

                has_protected = any(is_protected_target(t) for t in targets)

                if (has_r and has_f and has_protected) or (
                    has_no_preserve and (has_protected or not targets)
                ):
                    return True
    return False


def get_current_branch() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0:
            branch = proc.stdout.strip()
            if branch:
                return branch
    except Exception:
        pass

    try:
        head_file = Path(".git/HEAD")
        if head_file.is_file():
            content = head_file.read_text(encoding="utf-8").strip()
            if content.startswith("ref: refs/heads/"):
                return content.split("ref: refs/heads/")[-1].strip()
    except Exception:
        pass

    return ""


def is_trunk_ref(ref: str) -> bool:
    clean = ref.lstrip("+").lstrip(":")
    dest = clean.split(":")[-1]
    if dest in ("main", "master", "refs/heads/main", "refs/heads/master"):
        return True
    if dest.endswith(("/main", "/master")):
        if dest.startswith("refs/heads/"):
            return dest[len("refs/heads/") :] in ("main", "master")
        if dest.startswith(("remotes/", "origin/")):
            return dest.split("/")[-1] in ("main", "master")
    return False


def is_trunk_force_push(command: str) -> bool:
    """
    Detect git push where force or branch deletion targets main or master.
    Handles global git flags, unqualified force-pushes, and subshells.
    """
    for cmd in get_all_commands(command):
        subcommands = re.split(r"(?:&&|\|\||[;\n&|])", cmd)
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

            git_indices = [
                i for i, t in enumerate(tokens) if t == "git" or t.endswith("/git")
            ]
            for idx in git_indices:
                push_idx = None
                for j in range(idx + 1, len(tokens)):
                    if tokens[j] == "push":
                        push_idx = j
                        break
                    if not tokens[j].startswith("-"):
                        if j > idx + 1 and tokens[j - 1] in (
                            "-C",
                            "-c",
                            "--git-dir",
                            "--work-tree",
                            "--namespace",
                        ):
                            continue
                        break

                if push_idx is None:
                    continue

                push_args = tokens[push_idx + 1 :]
                has_force = False
                has_delete = False
                has_plus_trunk = False
                targets = []
                expect_delete_target = False

                for arg in push_args:
                    if arg in ("--delete", "-d"):
                        expect_delete_target = True
                    elif arg.startswith("--delete="):
                        del_target = arg.split("=", 1)[-1]
                        if is_trunk_ref(del_target):
                            has_delete = True
                    elif expect_delete_target and not arg.startswith("-"):
                        if is_trunk_ref(arg):
                            has_delete = True
                        expect_delete_target = False
                    elif arg in ("--force", "-f"):
                        has_force = True
                    elif arg.startswith(("--force-with-lease", "--force-if-includes")):
                        pass
                    elif arg.startswith("-") and not arg.startswith("--"):
                        chars = set(arg[1:])
                        if "f" in chars:
                            has_force = True
                        if "d" in chars:
                            expect_delete_target = True
                    elif arg.startswith(":"):
                        if is_trunk_ref(arg):
                            has_delete = True
                    elif arg.startswith("+"):
                        if is_trunk_ref(arg):
                            has_plus_trunk = True
                    else:
                        if not arg.startswith("-"):
                            clean_ref = arg.split(":")[-1].split("/")[-1]
                            if (clean_ref != "origin" and is_trunk_ref(arg)) or (
                                clean_ref not in ("origin", "upstream")
                            ):
                                targets.append(arg)

                if has_delete or has_plus_trunk:
                    return True

                if has_force:
                    if any(is_trunk_ref(t) for t in targets):
                        return True
                    if not targets:
                        curr_branch = get_current_branch()
                        if curr_branch in ("main", "master", ""):
                            return True
    return False


def is_drop_database(command: str) -> bool:
    """
    Detect drop database statement when executed via a known database client
    (psql, mysql, sqlite3, mariadb, mongosh, sqlcmd), direct 'drop' command verb,
    or SQL execution flags (-c, -e) piped to a database client.
    Never matches read-only commands like grep, rg, find, cat, pytest, git log.
    """
    for cmd in get_all_commands(command):
        if not DROP_DATABASE_PATTERN.search(cmd):
            continue

        pipe_segments = cmd.split("|")
        pipe_tokens = []
        for segment in pipe_segments:
            seg = segment.strip()
            if not seg:
                continue
            try:
                toks = shlex.split(seg)
            except Exception:
                toks = seg.split()
            if toks:
                pipe_tokens.append(toks)

        if not pipe_tokens:
            continue

        has_db_client = False
        for toks in pipe_tokens:
            verb = toks[0].split("/")[-1].lower()
            if verb in DB_CLIENTS:
                has_db_client = True
                break

        first_verb = pipe_tokens[0][0].split("/")[-1].lower()

        if first_verb in READ_ONLY_COMMANDS and not has_db_client:
            continue

        if first_verb == "drop":
            return True

        if has_db_client:
            return True

        all_toks = [t for toks in pipe_tokens for t in toks]
        if (
            any(
                t in ("-c", "-e", "-Q")
                or (t.startswith("-") and ("c" in t[1:] or "e" in t[1:]))
                for t in all_toks
            )
            and first_verb not in READ_ONLY_COMMANDS
        ):
            return True

    return False


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
    return bool(os.environ.get("CLOUD_RUN_TASK_INDEX"))


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
        command = (
            args.get("command") or args.get("CommandLine") or args.get("Command") or ""
        )

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
