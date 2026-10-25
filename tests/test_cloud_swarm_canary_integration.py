import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/swarm/scripts"
sys.path.insert(0, str(SCRIPTS))

import cloud_dispatch
import cloud_worker
import result_harvester
import storage_uploader


def _init_git_repo(path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@test.local"], cwd=path, check=True, capture_output=True)
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "base.txt"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def test_end_to_end_safe_evidence_transport_and_nested_layout(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    deep_evidence = repo / "nested/domain/oracle/checks.json"
    deep_evidence.parent.mkdir(parents=True)
    raw_payload = json.dumps({"status": "verified", "checks": [1, 2, 3], "score": 0.98}, indent=2).encode("utf-8")
    deep_evidence.write_bytes(raw_payload)
    raw_sha = hashlib.sha256(raw_payload).hexdigest()

    (repo / "solution.py").write_text("result = 42\n", encoding="utf-8")
    subprocess.run(["git", "add", "solution.py"], cwd=repo, check=True)

    fake_storage = tmp_path / "storage"
    session_id, bucket = "canary-session", "canary-bucket"
    prefix = f"swarms/{session_id}"
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(fake_storage))

    uploaded = storage_uploader.upload_run_artifacts(
        bucket_name=bucket,
        prefix=prefix,
        repo_dir=repo,
        task_index=0,
        status="PASS",
        candidate_files=["solution.py"],
        evidence_files=["nested/domain/oracle/checks.json"],
    )

    storage_evidence = fake_storage / bucket / prefix / "task-0/evidence/nested/domain/oracle/checks.json"
    assert storage_evidence.is_file()
    assert storage_evidence.read_bytes() == raw_payload
    assert hashlib.sha256(storage_evidence.read_bytes()).hexdigest() == raw_sha
    assert (fake_storage / bucket / prefix / "task-0/status.json").is_file()
    assert (fake_storage / bucket / prefix / "task-0/patch.diff").is_file()

    harvest_dest = tmp_path / "harvest"
    harvested = result_harvester.harvest_candidate_patches(bucket_name=bucket, prefix=prefix, dest_dir=harvest_dest)
    assert len(harvested) == 1
    assert harvested[0]["task_index"] == 0
    assert harvested[0]["status"] == "PASS"
    assert harvested[0]["patch_file"] is not None and Path(harvested[0]["patch_file"]).is_file()

    harvested_evidence = harvest_dest / "task-0/evidence/nested/domain/oracle/checks.json"
    assert harvested_evidence.is_file()
    assert harvested_evidence.read_bytes() == raw_payload
    assert hashlib.sha256(harvested_evidence.read_bytes()).hexdigest() == raw_sha


def test_failed_verification_degrades_to_issues_and_quarantines_patch(tmp_path, monkeypatch):
    fake_storage = tmp_path / "storage_c2"
    session_id, bucket = "canary-session-c2", "canary-bucket"
    prefix = f"swarms/{session_id}"

    task_item = {
        "task_index": 0,
        "brief": "Run task with failing verification",
        "candidate_files": ["research/task-0/calc.py"],
        "evidence_files": [],
        "verify_command": f"{shlex.quote(sys.executable)} research/task-0/oracle.py",
        "execution_limits": {"verify_timeout_s": 10},
    }

    env_vars = {
        "REPO_URL": "https://example.com/repo",
        "TASK_MANIFEST": json.dumps([task_item]),
        "USE_VERTEX_AI": "1",
        "CLOUD_RUN_TASK_INDEX": "0",
        "SWARM_SESSION_ID": session_id,
        "GCS_RESULTS_BUCKET": bucket,
        "GCS_BUCKET": bucket,
        "GCS_PREFIX": prefix,
        "STORAGE_MESSENGER_LOCAL_DIR": str(fake_storage),
    }
    for k, v in env_vars.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(cloud_worker.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_clone(**kwargs):
        dest_repo = kwargs["repo_dir"]
        _init_git_repo(dest_repo)
        t_dir = dest_repo / "research/task-0"
        t_dir.mkdir(parents=True, exist_ok=True)
        (t_dir / "oracle.py").write_text("import sys; sys.exit(1)\n", encoding="utf-8")

    monkeypatch.setattr(cloud_worker, "clone_and_checkout_task", fake_clone)
    monkeypatch.setattr(cloud_worker, "execute_task", lambda **kw: ("PASS", "Agent claimed pass."))
    monkeypatch.setattr(cloud_worker, "StorageMessenger", None)

    orig_cwd = os.getcwd()
    try:
        with pytest.raises(SystemExit) as exc_info:
            cloud_worker.main()
        assert exc_info.value.code == 1
    finally:
        os.chdir(orig_cwd)

    status_data = json.loads((tmp_path / "repo-task-0/status.json").read_text(encoding="utf-8"))
    assert status_data["status"] == "ISSUES"
    assert "Verification:" in status_data["summary"]

    harvested = result_harvester.harvest_candidate_patches(
        bucket_name=bucket, prefix=prefix, dest_dir=tmp_path / "harvest_c2"
    )
    assert len(harvested) == 1
    assert harvested[0]["task_index"] == 0
    assert harvested[0]["status"] == "ISSUES"
    assert harvested[0]["patch_file"] is None


@pytest.mark.parametrize(
    "cand_files,fail_file,files,err_msg",
    [
        (
            ["cand.py"],
            "score.json",
            {"cand.py": "x = 1\n", "score.json": json.dumps({"score": 0.95})},
            "score.json upload failed",
        ),
        ([], "results.tsv", {"results.tsv": "metric\tval\nscore\t0.9\n"}, "results.tsv upload failed"),
    ],
)
def test_upload_failures_degrade_to_issues(tmp_path, cand_files, fail_file, files, err_msg):
    fake_storage = tmp_path / "storage"
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8")

    def mock_upload(b, obj_name, file_path):
        if fail_file in str(obj_name):
            return False
        dest = fake_storage / b / obj_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)
        return True

    slug = fail_file.replace(".", "-")
    prefix = f"swarms/canary-{slug}"
    with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(fake_storage)}):
        with patch.object(storage_uploader, "upload_to_gcs", side_effect=mock_upload):
            uploaded = storage_uploader.upload_run_artifacts(
                bucket_name="canary-bucket",
                prefix=prefix,
                repo_dir=repo,
                task_index=0,
                status="PASS",
                candidate_files=cand_files,
            )
        assert fail_file not in uploaded
        status_data = json.loads((repo / "status.json").read_text(encoding="utf-8"))
        assert status_data["status"] == "ISSUES"
        assert any(err_msg in err for err in status_data["delivery_errors"])

        harvested = result_harvester.harvest_candidate_patches("canary-bucket", prefix, tmp_path / "harvest")
        assert len(harvested) == 1
        assert harvested[0]["status"] == "ISSUES"
        assert harvested[0]["patch_file"] is None


def test_session_prefix_isolation_and_coverage(tmp_path, monkeypatch):
    fake_storage = tmp_path / "storage"
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(fake_storage))

    for sub, idx, score, p_text in [
        ("canary/task-0", 0, 0.80, "diff --git a/canary b/canary\n+canary"),
        ("canary-other/task-1", 1, 0.99, "diff --git a/sibling b/sibling\n+sibling"),
    ]:
        td = fake_storage / "bucket/swarms" / sub
        td.mkdir(parents=True)
        (td / "status.json").write_text(json.dumps({"task_index": idx, "status": "PASS", "score": score}))
        (td / "patch.diff").write_text(p_text)

    harvested = result_harvester.harvest_candidate_patches("bucket", "swarms/canary", tmp_path / "harvest")
    assert len(harvested) == 1
    assert (harvested[0]["task_index"], harvested[0]["score"]) == (0, 0.80)
    assert Path(harvested[0]["patch_file"]).read_text() == "diff --git a/canary b/canary\n+canary"
    assert cloud_dispatch.failed_task_count(harvested, 2) == 1

    blobs = {
        "swarms/canary/task-0/status.json": json.dumps({"task_index": 0, "status": "PASS", "score": 0.80}),
        "swarms/canary/task-0/patch.diff": "canary patch",
        "swarms/canary-other/task-1/status.json": json.dumps({"task_index": 1, "status": "PASS", "score": 0.99}),
        "swarms/canary-other/task-1/patch.diff": "sibling patch",
    }

    class Blob:
        def __init__(self, name, payload):
            self.name, self.payload = name, payload

        def download_to_filename(self, filename):
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            Path(filename).write_text(self.payload, encoding="utf-8")

    mock_storage = MagicMock()
    mock_storage.Client.return_value.bucket.return_value.list_blobs.side_effect = lambda prefix="": [
        Blob(k, v) for k, v in blobs.items() if k.startswith(prefix)
    ]

    modules = {
        "google": types.SimpleNamespace(cloud=types.SimpleNamespace(storage=mock_storage)),
        "google.cloud": types.SimpleNamespace(storage=mock_storage),
        "google.cloud.storage": mock_storage,
    }
    with patch.dict(sys.modules, modules):
        monkeypatch.delenv("STORAGE_MESSENGER_LOCAL_DIR", raising=False)
        gcs_results = result_harvester.harvest_candidate_patches("bucket", "swarms/canary", tmp_path / "harvest_gcs")

    assert len(gcs_results) == 1
    assert (gcs_results[0]["task_index"], gcs_results[0]["score"]) == (0, 0.80)
    assert Path(gcs_results[0]["patch_file"]).read_text() == "canary patch"
