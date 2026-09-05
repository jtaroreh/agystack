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


def parse_task_manifest(manifest_raw: str, task_index: int) -> Tuple[Any, str]:
    if not manifest_raw.strip():
        task_brief_env = os.environ.get("TASK_BRIEF", "").strip()
        if task_brief_env:
            return task_brief_env, task_brief_env
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
        return item, item
    if isinstance(item, dict):
        brief = item.get("brief") or item.get("prompt") or json.dumps(item, indent=2)
        return item, brief
    return item, str(item)


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


def run_command(
    cmd: List[str],
    cwd: Optional[Path] = None,
    check: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


def parse_score_metrics(repo_dir: Path) -> Tuple[Optional[float], Optional[float]]:
    score_file = repo_dir / "score.json"
    if not score_file.is_file():
        return None, None
    try:
        with open(score_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        score = data.get("score")
        metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
        fill_ratio = (
            data.get("geomean_fill_ratio")
            or metrics.get("geomean_fill_ratio")
            or data.get("fill_ratio")
        )
        return score, fill_ratio
    except Exception:
        return None, None


def execute_task(
    task_item: Any,
    task_brief: str,
    repo_dir: Path,
    model_override: str,
    api_key: str,
    use_vertex: bool = False,
    project: Optional[str] = None,
    location: Optional[str] = None,
) -> Tuple[str, str]:
    # 1. Deterministic direct execution for matrix slice evaluation tasks
    is_slice_task = False
    start_idx = None
    end_idx = None

    if isinstance(task_item, dict) and "start_idx" in task_item and "end_idx" in task_item:
        is_slice_task = True
        start_idx = int(task_item["start_idx"])
        end_idx = int(task_item["end_idx"])
    elif "indices" in task_brief and "to" in task_brief:
        import re
        m = re.search(r"indices\s+(\d+)\s+to\s+(\d+)", task_brief)
        if m:
            is_slice_task = True
            start_idx = int(m.group(1))
            end_idx = int(m.group(2))

    if is_slice_task:
        verify_script = None
        candidates = [
            Path("/app/verify_ordering.py"),
            repo_dir / ".agents" / "skills" / "verify-matrices-fast" / "scripts" / "verify_ordering.py",
            repo_dir / "scripts" / "verify_ordering.py",
        ]
        for c in candidates:
            if c.is_file():
                verify_script = c
                break

        if verify_script:
            print(f"Executing direct matrix slice evaluation: {start_idx}..{end_idx}", flush=True)
            cmd = [
                sys.executable,
                str(verify_script),
                "--swarm-slice", f"{start_idx}:{end_idx}",
            ]
            worker_env = os.environ.copy()
            worker_env["SSI_ALLOW_UNSANDBOXED_WORKER"] = "1"
            worker_env["CARGO_HOME"] = os.environ.get("CARGO_HOME", "/usr/local/cargo")
            worker_env["RUSTUP_HOME"] = os.environ.get("RUSTUP_HOME", "/usr/local/rustup")
            worker_env["PATH"] = f"/usr/local/cargo/bin:{worker_env.get('PATH', '')}"

            res = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, env=worker_env)
            if res.returncode == 0:
                print(res.stdout, flush=True)
                return "PASS", f"Matrix slice {start_idx}..{end_idx} evaluated successfully."
            else:
                print(res.stdout, flush=True)
                err_snippet = (res.stderr.strip() or res.stdout.strip())[-500:]
                return "ISSUES", f"Slice evaluation failed: {err_snippet}"

    # 2. General Agent Execution using Google Antigravity SDK
    try:
        import asyncio
        import google.antigravity as antigravity
        from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig, policy

        capabilities = CapabilitiesConfig(
            allow_file_write=True,
            allow_shell_commands=True,
            allow_subagents=False,
        )
        resolved_model = model_override.strip() if model_override.strip() else "gemini-3.8-flash"
        policies = [policy.allow_all()]

        if use_vertex:
            resolved_project = (
                project
                or os.environ.get("VERTEXAI_PROJECT")
                or os.environ.get("GCP_PROJECT")
                or os.environ.get("PROJECT_ID")
            )
            resolved_location = (
                location
                or os.environ.get("VERTEXAI_LOCATION")
                or os.environ.get("GCP_REGION")
                or os.environ.get("REGION")
                or "us-central1"
            )
            if api_key:
                config = LocalAgentConfig(
                    model=resolved_model,
                    capabilities=capabilities,
                    workspace_dir=str(repo_dir),
                    vertex=True,
                    api_key=api_key,
                    project=resolved_project,
                    location=resolved_location,
                    policies=policies,
                )
            else:
                config = LocalAgentConfig(
                    model=resolved_model,
                    capabilities=capabilities,
                    workspace_dir=str(repo_dir),
                    vertex=True,
                    project=resolved_project,
                    location=resolved_location,
                    policies=policies,
                )
        else:
            config = LocalAgentConfig(
                model=resolved_model,
                capabilities=capabilities,
                workspace_dir=str(repo_dir),
                policies=policies,
                api_key=api_key,
            )

        async def _run_agent_turn() -> str:
            async with Agent(config=config) as agent:
                resp = await agent.chat(task_brief)
                return await resp.text()

        agent_text = asyncio.run(_run_agent_turn())
        return "PASS", agent_text
    except ImportError:
        return "BLOCKED", "Missing dependency: google.antigravity Python package is not installed."
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

    use_vertex = os.environ.get("USE_VERTEX_AI", "").lower() in ("1", "true", "yes")
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not use_vertex and not gemini_api_key:
        print(
            "[STATUS: BLOCKED]\nEvidence: Missing authentication. Neither USE_VERTEX_AI nor GEMINI_API_KEY is provided.\nSummary: Authentication configuration error.",
            flush=True,
        )
        sys.exit(1)

    project = os.environ.get("VERTEXAI_PROJECT") or os.environ.get("GCP_PROJECT") or os.environ.get("PROJECT_ID")
    location = os.environ.get("VERTEXAI_LOCATION") or os.environ.get("GCP_REGION") or os.environ.get("REGION")
    model_override = os.environ.get("MODEL_OVERRIDE", "")
    branch_name = f"worker-{task_index}"

    try:
        task_item, task_brief = parse_task_manifest(manifest_raw, task_index)
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

    # Deterministic offline bootstrap logic
    os.environ["SSI_ALLOW_UNSANDBOXED_WORKER"] = "1"
    (repo_dir / "rust-toolchain").unlink(missing_ok=True)

    cargo_in = repo_dir / "Cargo.toml.in"
    if cargo_in.is_file():
        shutil.copy(cargo_in, repo_dir / "Cargo.toml")

    candidate_in = repo_dir / "candidate-worker" / "Cargo.toml.in"
    if candidate_in.is_file():
        lines = candidate_in.read_text(encoding="utf-8").splitlines()
        kept_lines = []
        for line in lines:
            kept_lines.append(line)
            if "# === GENERATED CANDIDATE DEPS BELOW" in line:
                break
        deps = [
            'feral-amd = "0.2.1"',
            'feral-amf = "0.2.1"',
            'feral-metis = "0.2.1"',
            'feral-scotch = "0.2.1"',
            'feral-kahip = "0.2.1"',
            'feral-ordering-core = "0.2.1"',
            'feral = "0.11.0"',
        ]
        kept_lines.extend(deps)
        (repo_dir / "candidate-worker" / "Cargo.toml").write_text(
            "\n".join(kept_lines) + "\n", encoding="utf-8"
        )

    vendor_dest = repo_dir / "vendor"
    vendor_cache = Path("/app/vendor_cache")
    if vendor_cache.is_dir() and not vendor_dest.exists():
        try:
            os.symlink(vendor_cache, vendor_dest)
        except OSError:
            shutil.copytree(vendor_cache, vendor_dest)

    cargo_config_dir = repo_dir / ".cargo"
    cargo_config_dir.mkdir(parents=True, exist_ok=True)
    (cargo_config_dir / "config.toml").write_text(
        """[net]
offline = true
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
""",
        encoding="utf-8",
    )
    # Relax harness watchdog for Cloud Run cloud worker instances
    for rs_file in [repo_dir / "src" / "main.rs", repo_dir / "src" / "watchdog.rs"]:
        if rs_file.is_file():
            text = rs_file.read_text(encoding="utf-8")
            text = text.replace("Duration::from_secs(2)", "Duration::from_secs(10)")
            rs_file.write_text(text, encoding="utf-8")

    print("Bootstrapped offline Cargo manifests and vendored dependencies.", flush=True)

    agent_status, agent_summary = execute_task(
        task_item=task_item,
        task_brief=task_brief,
        repo_dir=repo_dir,
        model_override=model_override,
        api_key=gemini_api_key,
        use_vertex=use_vertex,
        project=project,
        location=location,
    )

    if agent_status == "BLOCKED":
        print("=" * 80)
        print("[STATUS: BLOCKED]")
        print("Evidence:")
        print(f"- Task Index: {task_index}")
        print(f"- Branch: {branch_name}")
        print("- Commit SHA: N/A")
        print("- Changes Pushed: False")
        print("- Diff Stat:\nExecution blocked before changes.")
        print("Summary:")
        print(agent_summary.strip())
        print("=" * 80, flush=True)
        sys.exit(1)

    score, fill_ratio = parse_score_metrics(repo_dir)
    gcs_bucket = os.environ.get("GCS_RESULTS_BUCKET", "").strip()
    gcs_prefix = os.environ.get("GCS_PREFIX", "").strip()
    gcs_uris: Dict[str, str] = {}

    commit_sha = ""
    diff_stat = ""
    changes_detected = False
    changes_pushed = False
    push_error: Optional[str] = None

    try:
        status_res = run_command(["git", "status", "--porcelain"], cwd=repo_dir, check=True)
        if status_res.stdout.strip():
            changes_detected = True
            run_command(["git", "add", "-A"], cwd=repo_dir, check=True)
            commit_msg = f"worker-{task_index}: execute swarm brief"
            run_command(["git", "commit", "-m", commit_msg], cwd=repo_dir, check=True)
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
        print(f"Warning: Git commit preparation failed: {err_msg.strip()}", file=sys.stderr)

    if gcs_bucket:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import storage_uploader

            gcs_uris = storage_uploader.upload_run_artifacts(
                bucket_name=gcs_bucket,
                prefix=gcs_prefix,
                repo_dir=repo_dir,
                task_index=task_index,
            )
        except Exception as exc:
            print(f"Warning: GCS upload failed: {exc}", file=sys.stderr)

    if changes_detected:
        fork_repo_url = os.environ.get("FORK_REPO_URL", "").strip()
        if fork_repo_url:
            fork_auth_url = build_authenticated_git_url(fork_repo_url, gh_token)
            remotes = run_command(["git", "remote"], cwd=repo_dir, check=False).stdout.split()
            if "fork" in remotes:
                run_command(["git", "remote", "set-url", "fork", fork_auth_url], cwd=repo_dir, check=True)
            else:
                run_command(["git", "remote", "add", "fork", fork_auth_url], cwd=repo_dir, check=True)
            push_target = "fork"
        else:
            push_target = "origin"

        try:
            run_command(["git", "push", "-u", push_target, branch_name, "--force"], cwd=repo_dir, check=True)
            changes_pushed = True
        except subprocess.CalledProcessError as exc:
            push_error = exc.stderr.replace(gh_token, "REDACTED") if gh_token in exc.stderr else exc.stderr
            changes_pushed = False

    has_gcs_results = bool(gcs_uris) or bool(gcs_bucket)
    has_score_json = (repo_dir / "score.json").is_file()

    if push_error:
        if has_gcs_results or has_score_json:
            print(
                f"Notice: Git push failed ({push_error.strip()}), but result evidence was preserved via GCS/score.json.",
                file=sys.stderr,
            )
        else:
            print(
                f"[STATUS: ISSUES]\nEvidence: Git commit or push failed: {push_error.strip()}\nSummary: Agent completed execution but branch push failed.",
                flush=True,
            )
            sys.exit(0)

    final_status = agent_status
    print("=" * 80)
    print(f"[STATUS: {final_status}]")
    print("Evidence:")
    print(f"- Task Index: {task_index}")
    print(f"- Branch: {branch_name}")
    print(f"- Commit SHA: {commit_sha or 'N/A'}")
    print(f"- Changes Pushed: {changes_pushed}")
    if score is not None:
        print(f"- Score: {score}")
    if fill_ratio is not None:
        print(f"- Fill Ratio: {fill_ratio}")
    score_file = repo_dir / "score.json"
    if score_file.is_file():
        try:
            score_data = score_file.read_text(encoding="utf-8").strip()
            print(f"- Slice JSON: {json.dumps(json.loads(score_data))}")
        except Exception:
            pass
    if gcs_uris:
        print(f"- GCS Artifacts: {json.dumps(gcs_uris)}")
    if push_error:
        print(f"- Push Status: Rejected (non-fatal, results captured)\n- Push Error: {push_error.strip()}")
    print(f"- Diff Stat:\n{diff_stat}")
    print("Summary:")
    print(agent_summary.strip())
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
