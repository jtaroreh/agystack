import json
import os
import shlex
import subprocess
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/swarm/scripts"
sys.path.insert(0, str(SCRIPTS))
import cloud_dispatch
import cloud_worker
import result_harvester
import storage_uploader
from worker import partner_engine


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Reporting `[STATUS: PASS]` now would be false. The correct status is [STATUS: BLOCKED]", "ISSUES"),
        ("Deprecated `[STATUS: PASS]`\n[STATUS: BLOCKED]", "BLOCKED"),
        ("Finished.\n[STATUS: PASS]", "PASS"),
        ("[STATUS: PASS]\n[STATUS: BLOCKED]", "ISSUES"),
        ("[STATUS: PASS]\n[STATUS: PASS]", "ISSUES"),
        ("```text\n[STATUS: PASS]\n```", "ISSUES"),
        ("~~~\n[STATUS: PASS]\n~~~\n[STATUS: BLOCKED]", "BLOCKED"),
        ("> [STATUS: PASS]", "ISSUES"),
        ('"[STATUS: PASS]"', "ISSUES"),
        ("`[STATUS: PASS]`", "ISSUES"),
        ("[STATUS: PASS] trailing prose", "ISSUES"),
        ("[STATUS: DEV_IMPROVED]", "ISSUES"),
        ("[STATUS: PASS]\nMore prose", "ISSUES"),
        ("[STATUS: MAYBE]", "ISSUES"),
        ("[status: issues]\n[STATUS: PASS]", "ISSUES"),
        ("[STATUS PASS]\n[STATUS: PASS]", "ISSUES"),
        ("    [STATUS: PASS]", "ISSUES"),
    ],
)
def test_strict_terminal_status(text, expected):
    for evaluate in (cloud_worker.evaluate_agent_status, partner_engine._evaluate_agent_status):
        assert evaluate(text)[0] == expected


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "1.5", "oops", None])
def test_invalid_execution_limits(bad):
    from worker.execution import resolve_execution_limits

    with pytest.raises(ValueError):
        resolve_execution_limits({"max_agent_turns": bad}, environ={})


def test_limits_precedence_and_immutability():
    from dataclasses import FrozenInstanceError
    from worker.execution import resolve_execution_limits

    limits = resolve_execution_limits(
        {"verify_timeout_s": 41},
        runtime={"max_agent_turns": 31, "command_timeout_s": 500},
        environ={"AGYSTACK_MAX_AGENT_TURNS": "32", "COMMAND_TIMEOUT": "600"},
        cli={"max_agent_turns": 33},
    )
    assert (limits.max_agent_turns, limits.command_timeout_s, limits.verify_timeout_s) == (33, 600, 41)
    with pytest.raises(FrozenInstanceError):
        limits.max_agent_turns = 2
    with pytest.raises(ValueError):
        resolve_execution_limits({"unexpected": 5}, environ={})
    with pytest.raises(ValueError):
        resolve_execution_limits([], environ={})
    with pytest.raises(ValueError):
        resolve_execution_limits(runtime=None, environ={})
    assert resolve_execution_limits(environ={}).command_timeout_s == 300
    assert resolve_execution_limits(environ={}, command_default=900).command_timeout_s == 900


@pytest.mark.parametrize("provider", ["claude", "fable", "deepseek"])
@pytest.mark.parametrize("finish", [True, False])
@pytest.mark.parametrize("source", ["task", "keyword"])
def test_provider_turn_limits_and_final_response(tmp_path, provider, finish, source):
    (tmp_path / "note.txt").write_text("still working")
    tool = {"type": "tool_use", "id": "read", "name": "read_file", "input": {"path": "note.txt"}}
    responses = []
    for turn in range(33):
        final = finish and turn == 32
        text = "Finished.\n[STATUS: PASS]" if final else "[STATUS: PASS]"
        if provider == "deepseek":
            fc = SimpleNamespace(name="read_file", args={"path": "note.txt"})
            responses.append(SimpleNamespace(text=text, candidates=[], function_calls=[] if final else [fc]))
        else:
            responses.append(SimpleNamespace(content=[{"type": "text", "text": text}] + ([] if final else [tool])))
    sdk = MagicMock()
    if provider == "claude":
        request = sdk.AnthropicVertex.return_value.messages.create
        entry = partner_engine.execute_claude_model_agent
        getter = "_get_anthropic"
    elif provider == "fable":
        request = sdk.Endpoint.return_value.predict
        entry = partner_engine.execute_fable_model_agent
        getter = "_get_aiplatform"
    else:
        request = sdk.Client.return_value.models.generate_content
        entry = partner_engine.execute_deepseek_model_agent
        getter = "_get_genai"
    request.side_effect = responses
    with patch.object(partner_engine, getter, return_value=sdk):
        if source == "task":
            status, summary = entry(provider, "work", tmp_path, task_item={"execution_limits": {"max_agent_turns": 33}})
        else:
            from worker.execution import ExecutionLimits

            model = {"claude": "claude-3-opus@20240229", "fable": "fable-5-1", "deepseek": "deepseek"}[provider]
            status, summary = cloud_worker.execute_task(
                {},
                "work",
                tmp_path,
                model,
                "",
                limits=ExecutionLimits(max_agent_turns=33),
            )
    assert request.call_count == 33
    assert status == ("PASS" if finish else "ISSUES")
    if not finish:
        assert "limit=33" in summary
        assert "consumed=33" in summary
        assert "read_file" in summary
        assert "last_response" in summary


@pytest.mark.parametrize("suffix", ["& wait", "| cat", "&"])
def test_timeout_keeps_output_and_kills_descendants(tmp_path, suffix):
    from worker.execution import ExecutionLimits

    child = "import os,time; open('child.pid','w').write(str(os.getpid())); time.sleep(2); open('survived', 'w').write('bad')"
    command = (
        f"echo partial-output; echo partial-error >&2; {shlex.quote(sys.executable)} -c {shlex.quote(child)} {suffix}"
    )
    output = partner_engine.execute_workspace_tool(
        "run_command",
        {"command": command},
        tmp_path,
        limits=ExecutionLimits(command_timeout_s=1),
    )
    assert "timed out" in output.lower()
    assert "partial-output" in output
    assert "partial-error" in output
    logs = list((tmp_path / ".agystack/diagnostics").glob("*.log"))
    assert logs and "partial-output" in logs[0].read_text()
    child_pid = int((tmp_path / "child.pid").read_text())
    time.sleep(1.5)
    assert not (tmp_path / "survived").exists()
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)], capture_output=True, text=True)
    assert not state.stdout.strip() or state.stdout.strip().startswith("Z")


def test_command_pipeline_failure_is_not_hidden(tmp_path):
    status, _ = cloud_worker.execute_task({"type": "command", "command": "false | tail -n 1"}, "", tmp_path, "", "")
    assert status == "ISSUES"


@pytest.fixture
def worker_repo(tmp_path):
    repo = tmp_path / "repo-task-0"
    repo.mkdir()
    for args in (["init"], ["config", "user.email", "test@example.com"], ["config", "user.name", "Test"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "service.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    return repo


@pytest.mark.parametrize(
    "status, candidate, verify",
    [
        ("BLOCKED", True, "exit 1"),
        ("ISSUES", True, "exit 1"),
        ("PASS", False, "exit 1"),
        ("PASS", False, "exit 0"),
        ("PASS", True, "exit 1"),
        ("PASS", False, "sleep 2"),
    ],
)
def test_worker_finalization_preserves_evidence(worker_repo, tmp_path, monkeypatch, status, candidate, verify, capsys):
    storage = tmp_path / "storage"
    task = {
        "brief": "work",
        "candidate_files": ["service.py"],
        "evidence_files": ["results/proof.txt"],
        "verify_command": f"echo verifier-ran > verification.txt; {verify}",
        "execution_limits": {"verify_timeout_s": 1},
    }
    monkeypatch.setenv("REPO_URL", "https://example.com/repo")
    monkeypatch.setenv("TASK_MANIFEST", json.dumps([task]))
    monkeypatch.setenv("USE_VERTEX_AI", "1")
    monkeypatch.setenv("GCS_BUCKET", "test-bucket")
    monkeypatch.setenv("GCS_PREFIX", "run")
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(storage))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cloud_worker.tempfile, "gettempdir", lambda: str(tmp_path))

    def clone(**kwargs):
        repo = kwargs["repo_dir"]
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        for key, value in [("user.email", "test@example.com"), ("user.name", "Test")]:
            subprocess.run(["git", "config", key, value], cwd=repo, check=True)
        (repo / "service.py").write_text("value = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)

    def execute(**kwargs):
        repo = kwargs["repo_dir"]
        if candidate:
            (repo / "service.py").write_text("value = 2\n")
        (repo / "results").mkdir()
        (repo / "results/proof.txt").write_text("partial proof")
        return status, "work summary"

    monkeypatch.setattr(cloud_worker, "clone_and_checkout_task", clone)
    monkeypatch.setattr(cloud_worker, "execute_task", execute)
    monkeypatch.setattr(cloud_worker, "StorageMessenger", None)
    try:
        cloud_worker.main()
    except SystemExit as exc:
        assert exc.code == 1
    target = storage / "test-bucket/run/task-0"
    published = json.loads((target / "status.json").read_text())
    expected = "PASS" if status == "PASS" and verify == "exit 0" else "ISSUES" if status == "PASS" else status
    assert published["status"] == expected
    report = cloud_dispatch.parse_worker_logs(capsys.readouterr().out)
    assert len(report) == 1 and report[0]["status"] == expected and report[0]["task_index"] == 0
    assert (target / "evidence/results/proof.txt").read_text() == "partial proof"
    assert not (target / "patch.diff").exists()
    if candidate:
        assert "+value = 2" in (target / "partial.patch.diff").read_text()
    if status == "PASS":
        assert (worker_repo / "verification.txt").is_file()
        assert list((target / "evidence/.agystack/diagnostics").glob("verification-*.log"))
    harvested = result_harvester.harvest_candidate_patches("test-bucket", "run", tmp_path / "harvest")
    assert len(harvested) == 1
    assert harvested[0]["status"] == published["status"]
    assert not harvested[0]["patch_file"]
    assert (tmp_path / "harvest/task-0/evidence/results/proof.txt").is_file()


@pytest.mark.parametrize(
    "reports",
    [
        [],
        [{"task_index": 0, "status": "PASS"}],
        [{"task_index": 0, "status": "PASS"}, {"task_index": 1, "status": "UNKNOWN"}],
        [{"task_index": 0, "status": "PASS"}, {"task_index": 0, "status": "PASS"}],
    ],
)
def test_dispatch_requires_complete_terminal_coverage(reports):
    assert cloud_dispatch.failed_task_count(reports, 2) > 0


def test_dispatch_complete_pass():
    assert (
        cloud_dispatch.failed_task_count([{"task_index": 0, "status": "PASS"}, {"task_index": 1, "status": "PASS"}], 2)
        == 0
    )


@pytest.mark.parametrize("limits", [None, [], {"extra": 3}, {"max_agent_turns": "40"}, {"max_agent_turns": True}])
def test_dispatch_rejects_invalid_task_limits_before_launch(tmp_path, limits):
    command = [
        sys.executable,
        str(SCRIPTS / "cloud_dispatch.py"),
        "--dry-run",
        "--repo",
        "https://example.com/repo",
        "--vertex",
        "--project",
        "test",
        "--manifest",
        json.dumps([{"brief": "work", "execution_limits": limits}]),
    ]
    env = dict(os.environ, GH_TOKEN="fake-test-token")
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "execution_limits" in result.stderr or "positive integer" in result.stderr


def test_dispatch_cli_env_runtime_precedence(tmp_path):
    (tmp_path / "agystack-runtime.json").write_text(
        json.dumps({"execution_limits": {"max_agent_turns": 40, "command_timeout_s": 500, "verify_timeout_s": 501}})
    )
    env = dict(os.environ, AGYSTACK_MAX_AGENT_TURNS="41", COMMAND_TIMEOUT="600", GH_TOKEN="fake-test-token")
    env.pop("VERIFY_TIMEOUT", None)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "cloud_dispatch.py"),
            "--dry-run",
            "--repo",
            "https://example.com/repo",
            "--vertex",
            "--project",
            "test",
            "--max-agent-turns",
            "42",
            "--verify-timeout",
            "601",
            "--manifest",
            json.dumps([{"brief": "work", "execution_limits": {"max_agent_turns": 43}}]),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["env_vars"]["AGYSTACK_MAX_AGENT_TURNS"] == "42"
    assert payload["env_vars"]["COMMAND_TIMEOUT"] == "600"
    assert payload["env_vars"]["VERIFY_TIMEOUT"] == "601"


def test_deepseek_retries_consume_request_limit(tmp_path):
    sdk = MagicMock()
    request = sdk.Client.return_value.models.generate_content
    request.side_effect = RuntimeError("503 unavailable")
    with patch.object(partner_engine, "_get_genai", return_value=sdk), patch.object(partner_engine.time, "sleep"):
        status, summary = partner_engine.execute_deepseek_model_agent(
            "deepseek",
            "work",
            tmp_path,
            task_item={"execution_limits": {"max_agent_turns": 2}},
        )
    assert request.call_count == 2
    assert status == "ISSUES"
    assert "limit=2" in summary and "consumed=2" in summary


@pytest.mark.parametrize("provider", ["claude", "fable"])
def test_empty_final_response_cannot_reuse_previous_pass(tmp_path, provider):
    sdk = MagicMock()
    tool = {"type": "tool_use", "id": "read", "name": "read_file", "input": {"path": "absent.txt"}}
    responses = [
        SimpleNamespace(content=[{"type": "text", "text": "[STATUS: PASS]"}, tool]),
        SimpleNamespace(content=[]),
    ]
    if provider == "claude":
        sdk.AnthropicVertex.return_value.messages.create.side_effect = responses
        entry, getter = partner_engine.execute_claude_model_agent, "_get_anthropic"
    else:
        sdk.Endpoint.return_value.predict.side_effect = responses
        entry, getter = partner_engine.execute_fable_model_agent, "_get_aiplatform"
    with patch.object(partner_engine, getter, return_value=sdk):
        assert entry(provider, "work", tmp_path)[0] == "ISSUES"


def test_evidence_failure_downgrades_before_status_publication(worker_repo):
    (worker_repo / "service.py").write_text("value = 2\n")
    (worker_repo / "proof.txt").write_text("proof")
    published = []

    def upload(bucket, name, path):
        published.append((name, path.read_text()))
        return not name.endswith("proof.txt")

    with patch.object(storage_uploader, "upload_to_gcs", side_effect=upload):
        artifacts = storage_uploader.upload_run_artifacts(
            "bucket",
            "run",
            worker_repo,
            0,
            "PASS",
            ["service.py"],
            evidence_files=["proof.txt"],
        )
    assert published[-1][0].endswith("/status.json")
    assert json.loads(published[-1][1])["status"] == "ISSUES"
    assert "patch.diff" not in artifacts
    assert "partial.patch.diff" in artifacts


def test_missing_status_file_never_promotes_score_or_patch(tmp_path, monkeypatch):
    source = tmp_path / "storage/bucket/run/task-0"
    source.mkdir(parents=True)
    (source / "score.json").write_text(json.dumps({"score": 999, "status": "PASS"}))
    (source / "patch.diff").write_text("candidate")
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(tmp_path / "storage"))
    results = result_harvester.harvest_candidate_patches("bucket", "run", tmp_path / "harvest")
    assert results[0]["status"] == "UNKNOWN"
    assert results[0]["patch_file"] is None


def test_shell_output_is_bounded_and_credentials_scrubbed(tmp_path):
    from worker.execution import run_bounded_shell

    secret = "AIza" + "a" * 35
    script = f"print('x' * 400000); print('{secret}'); print('last-line')"
    result, output = run_bounded_shell(f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}", tmp_path, 5)
    assert result.returncode == 0
    assert len(output) < 17000
    log = next((tmp_path / ".agystack/diagnostics").glob("*.log"))
    assert log.stat().st_size < 263000
    assert secret not in output and secret not in log.read_text()
    assert "[REDACTED]" in output and "last-line" in output


@pytest.mark.parametrize("mode", ["complete", "missing", "unknown"])
def test_attach_requires_all_worker_statuses(tmp_path, monkeypatch, mode, capsys):
    storage = tmp_path / "storage"
    for index in range(2 if mode != "missing" else 1):
        directory = storage / f"bucket/swarms/run/task-{index}"
        directory.mkdir(parents=True)
        status = "UNKNOWN" if mode == "unknown" and index == 1 else "PASS"
        (directory / "status.json").write_text(json.dumps({"task_index": index, "status": status}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(storage))
    monkeypatch.setattr(
        sys,
        "argv",
        ["cloud_dispatch.py", "--wait-execution", "execution", "--session", "run", "--gcs-bucket", "bucket"],
    )
    monkeypatch.setattr(cloud_dispatch, "wait_for_execution", lambda **kwargs: ({"spec": {"taskCount": 2}}, True, None))
    monkeypatch.setenv("ANTIGRAVITY_APP_DATA_DIR", str(tmp_path / "app-data"))
    if mode == "complete":
        cloud_dispatch.main()
    else:
        with pytest.raises(SystemExit) as exc:
            cloud_dispatch.main()
        assert exc.value.code == 1


def test_sdk_harvest_downloads_nested_partial_evidence(tmp_path, monkeypatch):
    payloads = {
        "run/task-0/status.json": json.dumps({"status": "BLOCKED"}),
        "run/task-0/partial.patch.diff": "partial diff",
        "run/task-0/evidence/results/proof.txt": "proof",
        "run/task-0/evidence/.agystack/diagnostics/timeout.log": "partial output",
    }

    class Blob:
        def __init__(self, name, payload):
            self.name, self.payload = name, payload

        def download_to_filename(self, filename):
            Path(filename).write_text(self.payload)

    storage = MagicMock()
    storage.Client.return_value.bucket.return_value.list_blobs.return_value = [
        Blob(name, value) for name, value in payloads.items()
    ]
    monkeypatch.delenv("STORAGE_MESSENGER_LOCAL_DIR", raising=False)
    google_mod = types.ModuleType("google")
    cloud_mod = types.ModuleType("google.cloud")
    google_mod.cloud = cloud_mod
    cloud_mod.storage = storage
    with patch.dict(
        sys.modules,
        {
            "google": google_mod,
            "google.cloud": cloud_mod,
            "google.cloud.storage": storage,
        },
    ):
        results = result_harvester.harvest_candidate_patches("bucket", "run", tmp_path / "harvest")
    assert results[0]["status"] == "BLOCKED"
    assert results[0]["patch_file"] is None
    assert Path(results[0]["partial_patch_file"]).read_text() == "partial diff"
    assert (tmp_path / "harvest/task-0/evidence/results/proof.txt").read_text() == "proof"
    assert (tmp_path / "harvest/task-0/evidence/.agystack/diagnostics/timeout.log").read_text() == "partial output"


@pytest.mark.parametrize("expected_count", [None, 2])
def test_standalone_harvest_quarantines_incomplete_coverage(tmp_path, monkeypatch, expected_count):
    source = tmp_path / "storage/bucket/run/task-0"
    source.mkdir(parents=True)
    (source / "status.json").write_text(json.dumps({"status": "PASS"}))
    (source / "patch.diff").write_text("candidate")
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(tmp_path / "storage"))
    command = [
        sys.executable,
        str(SCRIPTS / "cloud_dispatch.py"),
        "--harvest-session",
        "run",
        "--gcs-prefix",
        "run",
        "--gcs-bucket",
        "bucket",
    ]
    if expected_count:
        command += ["--tasks", str(expected_count)]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert "Quarantined Candidate" in result.stdout
    assert "Winning Candidate" not in result.stdout


def test_storage_mock_hierarchy_without_google_module(tmp_path, monkeypatch):
    storage = MagicMock()
    google_mod = types.ModuleType("google")
    cloud_mod = types.ModuleType("google.cloud")
    google_mod.cloud = cloud_mod
    cloud_mod.storage = storage

    monkeypatch.delenv("STORAGE_MESSENGER_LOCAL_DIR", raising=False)
    clean_modules = {k: v for k, v in sys.modules.items() if not k.startswith("google")}
    clean_modules["google"] = google_mod
    clean_modules["google.cloud"] = cloud_mod
    clean_modules["google.cloud.storage"] = storage

    with patch.dict(sys.modules, clean_modules, clear=True):
        from google.cloud import storage as resolved_storage

        assert resolved_storage is storage
        storage.Client.return_value.bucket.return_value.list_blobs.return_value = []
        res = result_harvester.harvest_candidate_patches("bkt", "prefix", tmp_path / "dest")
        assert res == []


def test_harvest_candidate_patches_strict_prefix_matching(tmp_path, monkeypatch):
    payloads = {
        "run/task-0/status.json": json.dumps({"status": "PASS"}),
        "run/task-0/score.json": json.dumps({"score": 0.95}),
        "run/task-0/patch.diff": "valid patch",
        # Sibling prefix that starts with 'run' but is not 'run/'
        "run-other/task-1/status.json": json.dumps({"status": "PASS"}),
        "run-other/task-1/score.json": json.dumps({"score": 0.99}),
        "run-other/task-1/patch.diff": "invalid patch",
        # Invalid task naming inside 'run/'
        "run/mytask-2/status.json": json.dumps({"status": "PASS"}),
        "run/task-3-suffix/status.json": json.dumps({"status": "PASS"}),
    }

    class Blob:
        def __init__(self, name, payload):
            self.name, self.payload = name, payload

        def download_to_filename(self, filename):
            Path(filename).write_text(self.payload)

    storage = MagicMock()

    def fake_list_blobs(prefix=""):
        return [Blob(name, val) for name, val in payloads.items() if name.startswith(prefix)]

    storage.Client.return_value.bucket.return_value.list_blobs.side_effect = fake_list_blobs

    google_mod = types.ModuleType("google")
    cloud_mod = types.ModuleType("google.cloud")
    google_mod.cloud = cloud_mod
    cloud_mod.storage = storage

    monkeypatch.delenv("STORAGE_MESSENGER_LOCAL_DIR", raising=False)
    with patch.dict(
        sys.modules,
        {
            "google": google_mod,
            "google.cloud": cloud_mod,
            "google.cloud.storage": storage,
        },
    ):
        results = result_harvester.harvest_candidate_patches("bucket", "run", tmp_path / "harvest")

    assert len(results) == 1
    assert results[0]["task_index"] == 0
    assert results[0]["status"] == "PASS"
    assert results[0]["score"] == 0.95
