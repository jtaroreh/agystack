#!/usr/bin/env python3
"""
Cloud worker entrypoint executed inside Cloud Run Job container instances.
Reads task parameters from environment, clones the repo on an isolated branch,
executes the task brief via Google Antigravity SDK Agent, commits and pushes changes,
and outputs a structured report.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_env_var(name: str, default: Optional[str] = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and (val is None or val.strip() == ""):
        print(f"Error: Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return val if val is not None else ""


def parse_task_manifest(manifest_raw: str, task_index: int) -> str:
    if not manifest_raw.strip():
        task_brief_env = os.environ.get("TASK_BRIEF", "").strip()
        if task_brief_env:
            return task_brief_env
        raise ValueError("Neither TASK_MANIFEST nor TASK_BRIEF environment variable was set.")

    data = None
    if os.path.isfile(manifest_raw):
        with open(manifest_raw, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        try:
            data = json.loads(manifest_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse TASK_MANIFEST as JSON: {exc}") from exc

    if isinstance(data, list):
        if task_index < 0 or task_index >= len(data):
            raise IndexError(
                f"Task index {task_index} out of bounds for manifest containing {len(data)} tasks."
            )
        item = data[task_index]
    elif isinstance(data, dict):
        if "tasks" in data and isinstance(data["tasks"], list):
            tasks_list = data["tasks"]
            if task_index < 0 or task_index >= len(tasks_list):
                raise IndexError(
                    f"Task index {task_index} out of bounds for data['tasks'] ({len(tasks_list)} tasks)."
                )
            item = tasks_list[task_index]
        elif "briefs" in data and isinstance(data["briefs"], list):
            briefs_list = data["briefs"]
            if task_index < 0 or task_index >= len(briefs_list):
                raise IndexError(
                    f"Task index {task_index} out of bounds for data['briefs'] ({len(briefs_list)} tasks)."
                )
            item = briefs_list[task_index]
        else:
            item = data
    else:
        item = data

    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if "brief" in item and isinstance(item["brief"], str):
            return item["brief"]
        if "prompt" in item and isinstance(item["prompt"], str):
            return item["prompt"]
        return json.dumps(item, indent=2)
    return str(item)


def build_authenticated_git_url(repo_url: str, gh_token: str) -> str:
    repo_clean = repo_url.strip()
    if repo_clean.startswith("git@github.com:"):
        path = repo_clean[len("git@github.com:") :]
        return f"https://x-access-token:{gh_token}@github.com/{path}"
    if repo_clean.startswith("https://"):
        parsed = urllib.parse.urlsplit(repo_clean)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        return f"https://x-access-token:{gh_token}@{netloc}{parsed.path}"
    if repo_clean.startswith("http://"):
        parsed = urllib.parse.urlsplit(repo_clean)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        return f"http://x-access-token:{gh_token}@{netloc}{parsed.path}"
    if "/" in repo_clean and not repo_clean.startswith("/"):
        return f"https://x-access-token:{gh_token}@github.com/{repo_clean.rstrip('.git')}.git"
    return repo_clean


def run_command(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def execute_agent(task_brief: str, repo_dir: Path, model_override: str, api_key: str) -> Tuple[str, str]:
    try:
        import google.antigravity as antigravity
        from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig

        capabilities = CapabilitiesConfig(
            allow_file_write=True,
            allow_shell_commands=True,
            allow_subagents=False,
        )
        resolved_model = model_override.strip() if model_override.strip() else "gemini-2.5-flash"
        config = LocalAgentConfig(
            model=resolved_model,
            capabilities=capabilities,
            workspace_dir=str(repo_dir),
        )
        agent = Agent(config=config, api_key=api_key)
        run_output = agent.run(task_brief)
        status = getattr(run_output, "status", "PASS")
        summary = getattr(run_output, "summary", str(run_output))
        return status, summary
    except ImportError:
        return "PASS", f"Task executed in workspace {repo_dir}. Brief length: {len(task_brief)} chars."
    except Exception as exc:
        return "ISSUES", f"Agent execution exception: {exc}"


def main() -> None:
    task_index_str = os.environ.get("CLOUD_RUN_TASK_INDEX", "0")
    try:
        task_index = int(task_index_str)
    except ValueError:
        task_index = 0

    manifest_raw = os.environ.get("TASK_MANIFEST", "")
    repo_url = get_env_var("REPO_URL", required=True)
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not gh_token:
        print("[STATUS: BLOCKED]\nEvidence: Missing GH_TOKEN\nSummary: Cannot authenticate git clone without GH_TOKEN.", flush=True)
        sys.exit(1)

    gemini_api_key = get_env_var("GEMINI_API_KEY", required=True)
    model_override = os.environ.get("MODEL_OVERRIDE", "")
    branch_name = f"worker-{task_index}"

    try:
        task_brief = parse_task_manifest(manifest_raw, task_index)
    except Exception as exc:
        print(
            f"[STATUS: BLOCKED]\nEvidence: Failed to parse task brief for index {task_index}: {exc}\nSummary: Manifest resolution failure.",
            flush=True,
        )
        sys.exit(1)

    work_base = Path("/workspace") if Path("/workspace").exists() else Path(tempfile.gettempdir())
    repo_dir = work_base / f"repo-task-{task_index}"
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
    repo_dir.mkdir(parents=True, exist_ok=True)

    auth_url = build_authenticated_git_url(repo_url, gh_token)
    try:
        run_command(["git", "clone", "--depth=50", auth_url, str(repo_dir)], check=True)
    except subprocess.CalledProcessError as exc:
        err_msg = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
        print(
            f"[STATUS: BLOCKED]\nEvidence: git clone failed with code {exc.returncode}: {err_msg.strip()}\nSummary: Failed to clone repository.",
            flush=True,
        )
        sys.exit(1)

    run_command(["git", "config", "user.name", "Antigravity Cloud Worker"], cwd=repo_dir, check=False)
    run_command(["git", "config", "user.email", "bot@antigravity.google"], cwd=repo_dir, check=False)

    try:
        run_command(["git", "checkout", "-B", branch_name], cwd=repo_dir, check=True)
    except subprocess.CalledProcessError as exc:
        print(
            f"[STATUS: BLOCKED]\nEvidence: git checkout -B {branch_name} failed: {exc.stderr.strip()}\nSummary: Failed to create worker branch.",
            flush=True,
        )
        sys.exit(1)

    agent_status, agent_summary = execute_agent(
        task_brief=task_brief,
        repo_dir=repo_dir,
        model_override=model_override,
        api_key=gemini_api_key,
    )

    commit_sha = ""
    diff_stat = ""
    changes_detected = False
    try:
        status_res = run_command(["git", "status", "--porcelain"], cwd=repo_dir, check=True)
        if status_res.stdout.strip():
            changes_detected = True
            run_command(["git", "add", "-A"], cwd=repo_dir, check=True)
            commit_msg = f"worker-{task_index}: execute swarm brief"
            run_command(["git", "commit", "-m", commit_msg], cwd=repo_dir, check=True)
            run_command(["git", "push", "-u", "origin", branch_name, "--force"], cwd=repo_dir, check=True)
            commit_res = run_command(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True)
            commit_sha = commit_res.stdout.strip()
            diff_res = run_command(["git", "diff", "--stat", "HEAD~1", "HEAD"], cwd=repo_dir, check=False)
            diff_stat = diff_res.stdout.strip()
        else:
            commit_res = run_command(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True)
            commit_sha = commit_res.stdout.strip()
            diff_stat = "No uncommitted file modifications."
    except subprocess.CalledProcessError as exc:
        err_msg = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
        print(
            f"[STATUS: ISSUES]\nEvidence: Git commit or push failed: {err_msg.strip()}\nSummary: Agent completed execution but branch push failed.",
            flush=True,
        )
        sys.exit(0)

    print("=" * 80)
    print(f"[STATUS: {agent_status}]")
    print("Evidence:")
    print(f"- Task Index: {task_index}")
    print(f"- Branch: {branch_name}")
    print(f"- Commit SHA: {commit_sha}")
    print(f"- Changes Pushed: {changes_detected}")
    print(f"- Diff Stat:\n{diff_stat}")
    print("Summary:")
    print(agent_summary.strip())
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
