import json
import os
import shlex
import subprocess
import sys
import time
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


@pytest.mark.parametrize("text, expected", [
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
])
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
    assert resolve_execution_limits(environ={}).command_timeout_s == 300
    assert resolve_execution_limits(environ={}, command_default=900).command_timeout_s == 900


@pytest.mark.parametrize("provider", ["claude", "fable", "deepseek"])
@pytest.mark.parametrize("finish", [True, False])
def test_provider_turn_limits_and_final_response(tmp_path, provider, finish):
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
        status, summary = entry(provider, "work", tmp_path, task_item={"execution_limits": {"max_agent_turns": 33}})
    assert request.call_count == 33
    assert status == ("PASS" if finish else "ISSUES")
    if not finish:
        assert "limit=33" in summary
        assert "consumed=33" in summary
        assert "read_file" in summary
        assert "last_response" in summary


def test_timeout_keeps_output_and_kills_descendants(tmp_path):
    from worker.execution import ExecutionLimits
    child = "import time; time.sleep(2); open('survived', 'w').write('bad')"
    command = f"echo partial-output; echo partial-error >&2; {shlex.quote(sys.executable)} -c {shlex.quote(child)} & wait"
    output = partner_engine.execute_workspace_tool(
        "run_command", {"command": command}, tmp_path,
        limits=ExecutionLimits(command_timeout_s=1),
    )
    assert "timed out" in output.lower()
    assert "partial-output" in output
    assert "partial-error" in output
    logs = list((tmp_path / ".agystack/diagnostics").glob("*.log"))
    assert logs and "partial-output" in logs[0].read_text()
    time.sleep(1.5)
    assert not (tmp_path / "survived").exists()


def test_command_pipeline_failure_is_not_hidden(tmp_path):
    status, _ = cloud_worker.execute_task(
        {"type": "command", "command": "false | tail -n 1"}, "", tmp_path, "", ""
    )
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


@pytest.mark.parametrize("status, candidate", [("BLOCKED", True), ("ISSUES", True), ("PASS", False)])
def test_worker_finalization_preserves_evidence(worker_repo, tmp_path, monkeypatch, status, candidate):
    storage = tmp_path / "storage"
    task = {"brief": "work", "evidence_files": ["results/proof.txt"],
            "verify_command": "echo verifier-ran > verification.txt; exit 1"}
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
    assert published["status"] == ("ISSUES" if status == "PASS" else status)
    assert (target / "evidence/results/proof.txt").read_text() == "partial proof"
    assert not (target / "patch.diff").exists()
    if candidate:
        assert "+value = 2" in (target / "partial.patch.diff").read_text()
    else:
        assert (worker_repo / "verification.txt").is_file()
    harvested = result_harvester.harvest_candidate_patches("test-bucket", "run", tmp_path / "harvest")
    assert len(harvested) == 1
    assert harvested[0]["status"] == published["status"]
    assert not harvested[0]["patch_file"]
    assert (tmp_path / "harvest/task-0/evidence/results/proof.txt").is_file()


@pytest.mark.parametrize("reports", [[], [{"task_index": 0, "status": "PASS"}],
    [{"task_index": 0, "status": "PASS"}, {"task_index": 1, "status": "UNKNOWN"}],
    [{"task_index": 0, "status": "PASS"}, {"task_index": 0, "status": "PASS"}]])
def test_dispatch_requires_complete_terminal_coverage(reports):
    assert cloud_dispatch.failed_task_count(reports, 2) > 0


def test_dispatch_complete_pass():
    assert cloud_dispatch.failed_task_count([
        {"task_index": 0, "status": "PASS"}, {"task_index": 1, "status": "PASS"}
    ], 2) == 0
