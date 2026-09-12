#!/usr/bin/env python3
"""
Antigravity PostToolUse lifecycle hook for automatic code formatting and linting.
Triggered strictly on write_to_file. Never formats on replace_file_content.
Outputs {} and exits 0 on all code paths. Never crashes.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def run_formatter(target_path: Path) -> None:
    ext = target_path.suffix.lower()

    if ext == ".py":
        ruff_bin = shutil.which("ruff")
        if ruff_bin:
            try:
                subprocess.run(
                    [ruff_bin, "format", "--silent", str(target_path)],
                    check=False,
                    timeout=10,
                )
            except Exception:
                pass

    elif ext in [".ts", ".tsx", ".js", ".jsx"]:
        prettier_bin = shutil.which("prettier")
        if prettier_bin:
            try:
                subprocess.run(
                    [prettier_bin, "--write", str(target_path)],
                    check=False,
                    timeout=10,
                )
            except Exception:
                pass
        else:
            biome_bin = shutil.which("biome")
            if biome_bin:
                try:
                    subprocess.run(
                        [biome_bin, "format", "--write", str(target_path)],
                        check=False,
                        timeout=10,
                    )
                except Exception:
                    pass


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            sys.stdout.write("{}\n")
            sys.exit(0)

        payload = json.loads(raw_input)
        tool_call = payload.get("toolCall", {})
        tool_name = tool_call.get("name")

        if tool_name != "write_to_file":
            sys.stdout.write("{}\n")
            sys.exit(0)

        args = tool_call.get("args", {})
        target_file = (
            args.get("TargetFile")
            or args.get("target_file")
            or args.get("AbsolutePath")
            or args.get("FilePath")
            or args.get("path")
        )
        if target_file:
            target_path = Path(target_file).expanduser().resolve()
            cwd = Path.cwd().resolve()
            try:
                target_path.relative_to(cwd)
                is_within_cwd = True
            except ValueError:
                is_within_cwd = False

            if is_within_cwd and target_path.is_file():
                run_formatter(target_path)
    except Exception:
        pass

    sys.stdout.write("{}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
