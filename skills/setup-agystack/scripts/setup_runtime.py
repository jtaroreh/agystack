import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd, check=False, capture_output=True):
    try:
        return subprocess.run(cmd, check=False, capture_output=capture_output, text=True)
    except FileNotFoundError as e:
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr=str(e))


def _parse_version(stdout):
    if not stdout:
        return None
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(stdout).strip())
    if match:
        patch = int(match.group(3)) if match.group(3) is not None else 0
        return match.group(0), int(match.group(1)), int(match.group(2)), patch
    return None


DEPENDENCY_SPECS = (
    {
        "name": "bun",
        "cmd": ["bun", "--version"],
        "required": True,
        "notes": "Mandatory runtime for PR babysitting (watch-pr) and TypeScript script tests",
        "missing_error": "bun is not installed or not found on PATH",
        "min_major": 1,
        "min_error": "Bun version 1.0+ required, found {version_str}",
    },
    {
        "name": "gh",
        "cmd": ["gh", "--version"],
        "required": True,
        "notes": "Required for PR automation and preflight checks",
        "missing_error": "gh (GitHub CLI) is not installed or not found on PATH",
    },
    {
        "name": "gt",
        "cmd": ["gt", "--version"],
        "required": False,
        "notes": "Recommended for stacked PRs",
        "missing_error": "gt (Graphite CLI) is not installed",
    },
)


def check_dependencies(run_cmd_fn=None):
    if run_cmd_fn is None:
        run_cmd_fn = run_cmd

    deps = {}
    for spec in DEPENDENCY_SPECS:
        name = spec["name"]
        cmd = spec["cmd"]
        required = spec.get("required", False)
        notes = spec.get("notes", "")
        missing_error = spec.get("missing_error", f"{name} is not installed")

        try:
            res = run_cmd_fn(cmd, check=False)
        except FileNotFoundError:
            deps[name] = {
                "installed": False,
                "version": None,
                "ok": False,
                "error": missing_error,
                "notes": notes,
                "required": required,
            }
            continue
        except Exception as e:
            deps[name] = {
                "installed": False,
                "version": None,
                "ok": False,
                "error": f"Failed to execute {name}: {e}",
                "notes": notes,
                "required": required,
            }
            continue

        returncode = getattr(res, "returncode", 1)
        stdout = getattr(res, "stdout", "") or ""
        stderr = getattr(res, "stderr", "") or ""
        if isinstance(stderr, str):
            stderr = stderr.strip()

        if returncode == 0:
            parsed = _parse_version(stdout)
            if parsed:
                version_str, major, _, _ = parsed
                min_major = spec.get("min_major")
                if min_major is not None and major is not None and major < min_major:
                    min_error_template = spec.get(
                        "min_error",
                        f"{name.capitalize()} version {min_major}.0+ required, found {{version_str}}",
                    )
                    deps[name] = {
                        "installed": True,
                        "version": version_str,
                        "ok": False,
                        "error": min_error_template.format(version_str=version_str),
                        "notes": notes,
                        "required": required,
                    }
                else:
                    deps[name] = {
                        "installed": True,
                        "version": version_str,
                        "ok": True,
                        "error": None,
                        "notes": notes,
                        "required": required,
                    }
            else:
                deps[name] = {
                    "installed": True,
                    "version": None,
                    "ok": False,
                    "error": f"Failed to parse {name} version from output",
                    "notes": notes,
                    "required": required,
                }
        elif returncode == 127:
            deps[name] = {
                "installed": False,
                "version": None,
                "ok": False,
                "error": missing_error,
                "notes": notes,
                "required": required,
            }
        else:
            deps[name] = {
                "installed": False,
                "version": None,
                "ok": False,
                "error": stderr if stderr else missing_error,
                "notes": notes,
                "required": required,
            }

    return deps


def check_hook_contract(hook_path=None, run_cmd_fn=None):
    if hook_path:
        paths = [Path(hook_path)]
    else:
        paths = [
            Path("skills/poteto-mode/scripts/hooks/pre_tool_safety.py"),
            Path(__file__).resolve().parents[3] / "skills" / "poteto-mode" / "scripts" / "hooks" / "pre_tool_safety.py",
            Path.home()
            / ".gemini"
            / "config"
            / "plugins"
            / "agystack"
            / "skills"
            / "poteto-mode"
            / "scripts"
            / "hooks"
            / "pre_tool_safety.py",
            Path(".agents/plugins/agystack/skills/poteto-mode/scripts/hooks/pre_tool_safety.py"),
        ]

    target = None
    for p in paths:
        if p and p.is_file():
            target = p.resolve()
            break

    if target is None:
        return {
            "installed": False,
            "ok": False,
            "path": None,
            "decision": None,
            "error": "Safety hook script (pre_tool_safety.py) not found",
            "required": True,
        }

    payload = json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "rm -rf /"}}})

    env = os.environ.copy()
    env["NON_INTERACTIVE"] = "1"

    try:
        if run_cmd_fn:
            res = run_cmd_fn([sys.executable, str(target)], input=payload, env=env)
        else:
            res = subprocess.run(
                [sys.executable, str(target)],
                input=payload,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

        stdout = getattr(res, "stdout", "") or ""
        decision = None
        try:
            data = json.loads(stdout.strip())
            decision = data.get("decision")
        except Exception:
            pass

        if decision == "deny":
            return {
                "installed": True,
                "ok": True,
                "path": str(target),
                "decision": "deny",
                "error": None,
                "required": True,
            }
        else:
            return {
                "installed": True,
                "ok": False,
                "path": str(target),
                "decision": decision,
                "error": f"Expected decision 'deny', got '{decision}'. Output: {stdout.strip()}",
                "required": True,
            }
    except Exception as e:
        return {
            "installed": False,
            "ok": False,
            "path": str(target),
            "decision": None,
            "error": f"Failed to execute safety hook: {e}",
            "required": True,
        }


def check_artifact_dir(brain_dir=None):
    if brain_dir:
        candidates = [Path(brain_dir)]
    else:
        candidates = []
        if os.environ.get("ANTIGRAVITY_APP_DATA_DIR"):
            candidates.append(Path(os.environ["ANTIGRAVITY_APP_DATA_DIR"]) / "brain")
        candidates.extend(
            [
                Path.home() / ".gemini" / "antigravity" / "brain",
                Path.home() / ".gemini" / "antigravity-ide" / "brain",
            ]
        )
        if os.environ.get("ANTIGRAVITY_CONVERSATION_ID") and os.environ.get("ANTIGRAVITY_APP_DATA_DIR"):
            candidates.append(
                Path(os.environ["ANTIGRAVITY_APP_DATA_DIR"]) / "brain" / os.environ["ANTIGRAVITY_CONVERSATION_ID"]
            )

    target = None
    for cand in candidates:
        if cand.exists() and cand.is_dir():
            target = cand.resolve()
            break

    if target is None:
        default_target = candidates[0] if candidates else (Path.home() / ".gemini" / "antigravity" / "brain")
        try:
            default_target.mkdir(parents=True, exist_ok=True)
            if default_target.is_dir():
                target = default_target.resolve()
        except Exception:
            pass

    if target is None or not target.is_dir():
        return {
            "installed": False,
            "ok": False,
            "path": str(candidates[0]) if candidates else None,
            "writable": False,
            "error": "Artifact brain directory does not exist and could not be created",
            "required": True,
        }

    try:
        probe = target / f".probe_write_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        writable = True
        error = None
    except Exception as e:
        writable = False
        error = f"Artifact brain directory is not writable: {e}"

    return {
        "installed": True,
        "ok": writable,
        "path": str(target),
        "writable": writable,
        "error": error,
        "required": True,
    }


def parse_model_config(config_path=None):
    if config_path:
        paths = [Path(config_path)]
    else:
        plugin_root = Path(__file__).resolve().parents[3]
        global_root = Path.home() / ".gemini" / "config" / "plugins" / "agystack"
        paths = [
            Path(".agents/plugins/agystack/agystack-models.md"),
            Path("agystack-models.md"),
            plugin_root / "agystack-models.md",
            global_root / "agystack-models.md",
            Path(".agents/plugins/agystack/rules/agystack-models.md"),
            Path("rules/agystack-models.md"),
            plugin_root / "rules" / "agystack-models.md",
            global_root / "rules" / "agystack-models.md",
        ]

    target = None
    for p in paths:
        if p and p.is_file():
            target = p.resolve()
            break

    if target is None:
        return {
            "installed": False,
            "ok": False,
            "path": None,
            "roles": {},
            "roles_count": 0,
            "error": "Model configuration file (agystack-models.md) not found",
            "required": True,
        }

    roles = {}
    try:
        content = target.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                role_part, model_part = line.split(":", 1)
                models = [x.strip() for x in model_part.split(",") if x.strip()]
                roles[role_part.strip()] = models
                for r in role_part.split(","):
                    r_clean = r.strip()
                    if r_clean and r_clean not in roles:
                        roles[r_clean] = models

        return {
            "installed": True,
            "ok": bool(roles),
            "path": str(target),
            "roles": roles,
            "roles_count": len(roles),
            "error": None if roles else "No model roles defined in configuration",
            "required": True,
        }
    except Exception as e:
        return {
            "installed": False,
            "ok": False,
            "path": str(target),
            "roles": {},
            "roles_count": 0,
            "error": f"Failed to parse model configuration: {e}",
            "required": True,
        }


def check_skill_collisions(plugin_root=None):
    root = Path(plugin_root).resolve() if plugin_root else Path(__file__).resolve().parents[3]
    swarm_path = root / "skills" / "swarm"
    if swarm_path.exists():
        return {
            "ok": False,
            "path": str(swarm_path),
            "collision": True,
            "error": f"Legacy skills/swarm directory shadows Antigravity built-in swarm; remove {swarm_path}",
            "required": True,
        }
    return {
        "ok": True,
        "path": str(swarm_path),
        "collision": False,
        "error": None,
        "required": True,
    }


def check_platform(hook_path=None, brain_dir=None, model_config_path=None, plugin_root=None, run_cmd_fn=None):
    hook_result = check_hook_contract(hook_path=hook_path, run_cmd_fn=run_cmd_fn)
    artifact_result = check_artifact_dir(brain_dir=brain_dir)
    model_result = parse_model_config(config_path=model_config_path)
    collision_result = check_skill_collisions(plugin_root=plugin_root)

    checks = {
        "hook_contract": hook_result,
        "artifact_dir": artifact_result,
        "model_config": model_result,
        "skill_collisions": collision_result,
    }
    all_ok = all(c.get("ok", False) for c in checks.values() if isinstance(c, dict) and c.get("required"))
    checks["ok"] = all_ok
    return checks


def run_doctor(run_cmd_fn=None, hook_path=None, brain_dir=None, model_config_path=None, plugin_root=None):
    deps = check_dependencies(run_cmd_fn=run_cmd_fn)
    platform = check_platform(
        hook_path=hook_path,
        brain_dir=brain_dir,
        model_config_path=model_config_path,
        plugin_root=plugin_root,
        run_cmd_fn=run_cmd_fn,
    )

    result = dict(deps)
    result["platform"] = platform
    result["safety_hook"] = platform["hook_contract"]
    result["artifact_dir"] = platform["artifact_dir"]
    result["model_config"] = platform["model_config"]
    result["skill_collisions"] = platform["skill_collisions"]

    all_deps_ok = all(dep.get("ok", False) for dep in deps.values() if isinstance(dep, dict) and dep.get("required"))
    platform_ok = platform.get("ok", False)
    overall_ok = all_deps_ok and platform_ok
    result["status"] = "OK" if overall_ok else "ERROR"
    return result, overall_ok


def main():
    parser = argparse.ArgumentParser(description="AgyStack Runtime Setup Helper")
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check dependencies and Antigravity platform health and report status",
    )

    args = parser.parse_args()

    if args.doctor:
        report, overall_ok = run_doctor()
        print(json.dumps(report, indent=2))
        sys.exit(0 if overall_ok else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
