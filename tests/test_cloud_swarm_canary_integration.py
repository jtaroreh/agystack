import ast
import copy
from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import types
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/swarm/scripts"
sys.path.insert(0, str(SCRIPTS))

import cloud_dispatch
import cloud_worker
import result_harvester
import storage_uploader
from worker.execution import ExecutionLimits, resolve_execution_limits, run_bounded_shell

CANARY_PACKAGE_INVENTORY = Path(
    os.environ.get(
        "AGYSTACK_CANARY_PACKAGE_INVENTORY",
        "/Users/joeltaroreh/projects/phasepoly-swarm-prep/.audit/cloud-swarm-20261024/revision3/package-inventory.json",
    )
)
CANARY_REVISION3_DIR = CANARY_PACKAGE_INVENTORY.parent


def _init_git_repo(path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Canary Tester"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "canary@test.local"], cwd=path, check=True, capture_output=True)
    (path / "base.txt").write_text("initial base\n", encoding="utf-8")
    subprocess.run(["git", "add", "base.txt"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init base"], cwd=path, check=True, capture_output=True)
    return path


EXPERIMENT_SCRIPT = """import json, sys
from pathlib import Path

# Jordan-Wigner Majorana representation for 2 modes (4 operators)
# gamma_0 = X_0, gamma_1 = Y_0, gamma_2 = Z_0 X_1, gamma_3 = Z_0 Y_1
majoranas = [
    {"x": 1, "z": 0},
    {"x": 1, "z": 1},
    {"x": 2, "z": 1},
    {"x": 2, "z": 3},
]

# Check anticommutation violations: (x1*z2 + z1*x2)%2 must be 1 for distinct pairs
violations = sum(
    (bin(a["x"] & b["z"]).count("1") + bin(a["z"] & b["x"]).count("1")) % 2 != 1
    for i, a in enumerate(majoranas)
    for b in majoranas[i + 1:]
)

candidate_weight = sum(bin(m["x"] | m["z"]).count("1") for m in majoranas)
baseline_weight = 2 * (2 + 1)

output_data = {
    "size": 2,
    "seed": 42,
    "candidate_weight": candidate_weight,
    "baseline_weight": baseline_weight,
    "violations": violations,
    "majoranas": majoranas,
}

out_path = Path("screen.raw.json")
out_path.write_text(json.dumps(output_data, indent=2), encoding="utf-8")
print(f"Computed Majorana algebra: violations={violations}, weight={candidate_weight}")
"""

DOMAIN_ORACLE_SCRIPT = """import json, sys
from pathlib import Path

raw_file = Path("screen.raw.json")
if not raw_file.is_file():
    print("Error: screen.raw.json missing", file=sys.stderr)
    sys.exit(1)

data = json.loads(raw_file.read_text(encoding="utf-8"))
if data.get("violations", -1) != 0:
    print(f"Oracle verification failed: violations={data.get('violations')}", file=sys.stderr)
    sys.exit(1)

# Exact matrix verification of 4x4 Majorana anticommutators
I = [[1, 0], [0, 1]]
X = [[0, 1], [1, 0]]
Y = [[0, -1j], [1j, 0]]
Z = [[1, 0], [0, -1]]

def tensor(a, b):
    return [[a[i // len(b)][j // len(b)] * b[i % len(b)][j % len(b)]
             for j in range(len(a) * len(b))] for i in range(len(a) * len(b))]

def mat_mul(a, b):
    n = len(a)
    return [[sum(a[i][k] * b[k][j] for k in range(n)) for j in range(n)] for i in range(n)]

def matrix(mask):
    out = [[1]]
    for k in range(2):
        x, z = (mask["x"] >> k) & 1, (mask["z"] >> k) & 1
        out = tensor(out, Y if x and z else X if x else Z if z else I)
    return out

matrices = [matrix(m) for m in data["majoranas"]]
sample_count = 0
for i, a in enumerate(matrices):
    for j, b in enumerate(matrices):
        ab, ba = mat_mul(a, b), mat_mul(b, a)
        expected = 2 if i == j else 0
        for r in range(4):
            for c in range(4):
                val = ab[r][c] + ba[r][c]
                target = expected if r == c else 0
                if abs(val - target) > 1e-10:
                    print(f"Algebra violation at ({i},{j}) element ({r},{c}): {val} != {target}", file=sys.stderr)
                    sys.exit(1)
        sample_count += 1

oracle_res = {
    "checks": [
        {"name": "majorana_anticommutators_4x4", "passed": True, "sample_count": sample_count}
    ]
}
Path("oracle_result.json").write_text(json.dumps(oracle_res, indent=2), encoding="utf-8")
print(f"Oracle verified {sample_count} matrix checks cleanly.")
"""


def test_case_1_real_scientific_computation_harvests_exact_bytes(tmp_path, monkeypatch):
    """Case 1: A tiny real scientific computation produces raw numeric output and a sound domain oracle.

    Safe evidence is delivered and independently harvested under the exact canary session.
    Assert harvested status is PASS, raw outputs and evidence files are preserved with exact bytes.
    """
    repo = tmp_path / "canary_worker_repo"
    repo.mkdir()
    _init_git_repo(repo)

    task_dir = repo / "research/canary-task-0"
    task_dir.mkdir(parents=True)
    (task_dir / "experiment.py").write_text(EXPERIMENT_SCRIPT, encoding="utf-8")
    (task_dir / "oracle.py").write_text(DOMAIN_ORACLE_SCRIPT, encoding="utf-8")

    # Run the real scientific computation
    calc_res = subprocess.run([sys.executable, "experiment.py"], cwd=task_dir, capture_output=True, text=True, check=True)
    assert "Computed Majorana algebra: violations=0" in calc_res.stdout
    raw_path = task_dir / "screen.raw.json"
    assert raw_path.is_file()
    expected_raw_bytes = raw_path.read_bytes()
    expected_raw_sha = hashlib.sha256(expected_raw_bytes).hexdigest()

    # Run the sound domain oracle
    oracle_res = subprocess.run([sys.executable, "oracle.py"], cwd=task_dir, capture_output=True, text=True, check=True)
    assert "Oracle verified 16 matrix checks cleanly." in oracle_res.stdout
    oracle_path = task_dir / "oracle_result.json"
    assert oracle_path.is_file()
    expected_oracle_bytes = oracle_path.read_bytes()
    expected_oracle_sha = hashlib.sha256(expected_oracle_bytes).hexdigest()

    # Track modified candidate file
    subprocess.run(["git", "add", "research/canary-task-0/experiment.py"], cwd=repo, check=True)

    fake_storage = tmp_path / "fake_storage"
    session_id = "canary-session"
    bucket_name = "canary-bucket"
    gcs_prefix = f"swarms/{session_id}"

    task_item = {
        "task_index": 0,
        "brief": "Run minimal Majorana algebra screen",
        "candidate_files": ["research/canary-task-0/experiment.py"],
        "evidence_files": [
            "research/canary-task-0/screen.raw.json",
            "research/canary-task-0/oracle_result.json",
        ],
        "verify_command": f"{shlex.quote(sys.executable)} oracle.py",
        "execution_limits": {"verify_timeout_s": 30, "command_timeout_s": 30},
    }

    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(fake_storage))

    # Perform artifact upload under the exact canary session layout
    uploaded = storage_uploader.upload_run_artifacts(
        bucket_name=bucket_name,
        prefix=gcs_prefix,
        repo_dir=repo,
        task_index=0,
        status="PASS",
        candidate_files=task_item["candidate_files"],
        evidence_files=task_item["evidence_files"],
    )

    # Verify object layout in fake storage: swarms/<session>/task-<index>/
    task_storage = fake_storage / bucket_name / gcs_prefix / "task-0"
    assert task_storage.is_dir()
    assert (task_storage / "status.json").is_file()
    assert (task_storage / "patch.diff").is_file()
    storage_raw = task_storage / "evidence/research/canary-task-0/screen.raw.json"
    storage_oracle = task_storage / "evidence/research/canary-task-0/oracle_result.json"
    assert storage_raw.is_file()
    assert storage_oracle.is_file()

    # Byte-exact preservation in storage
    assert storage_raw.read_bytes() == expected_raw_bytes
    assert hashlib.sha256(storage_raw.read_bytes()).hexdigest() == expected_raw_sha
    assert storage_oracle.read_bytes() == expected_oracle_bytes
    assert hashlib.sha256(storage_oracle.read_bytes()).hexdigest() == expected_oracle_sha

    # Harvest independently under the exact canary session
    harvest_dest = tmp_path / "harvested"
    harvested = result_harvester.harvest_candidate_patches(
        bucket_name=bucket_name,
        prefix=gcs_prefix,
        dest_dir=harvest_dest,
    )

    assert len(harvested) == 1
    item = harvested[0]
    assert item["task_index"] == 0
    assert item["status"] == "PASS"
    assert item["patch_file"] is not None and Path(item["patch_file"]).is_file()

    harvested_raw = harvest_dest / "task-0/evidence/research/canary-task-0/screen.raw.json"
    harvested_oracle = harvest_dest / "task-0/evidence/research/canary-task-0/oracle_result.json"
    assert harvested_raw.is_file()
    assert harvested_oracle.is_file()

    # Assert exact byte preservation after transport and harvesting
    assert harvested_raw.read_bytes() == expected_raw_bytes
    assert hashlib.sha256(harvested_raw.read_bytes()).hexdigest() == expected_raw_sha
    assert harvested_oracle.read_bytes() == expected_oracle_bytes
    assert hashlib.sha256(harvested_oracle.read_bytes()).hexdigest() == expected_oracle_sha


def test_case_2_wrong_scientific_result_fails_verification_and_degrades_to_issues(tmp_path, monkeypatch):
    """Case 2: An intentionally wrong scientific result fails verification even when the agent

    requests PASS and makes no source change. Status is degraded to ISSUES and harvested status is ISSUES.
    """
    repo = tmp_path / "canary_worker_repo_c2"
    repo.mkdir()
    _init_git_repo(repo)

    task_dir = repo / "research/canary-task-0"
    task_dir.mkdir(parents=True)
    (task_dir / "oracle.py").write_text(DOMAIN_ORACLE_SCRIPT, encoding="utf-8")

    # Intentionally corrupt the raw scientific output (violations = 2)
    corrupted_data = {
        "size": 2,
        "seed": 42,
        "candidate_weight": 6,
        "baseline_weight": 6,
        "violations": 2,
        "majoranas": [{"x": 1, "z": 0}, {"x": 1, "z": 0}, {"x": 2, "z": 1}, {"x": 2, "z": 3}],
    }
    (task_dir / "screen.raw.json").write_text(json.dumps(corrupted_data, indent=2), encoding="utf-8")

    # No source changes made to candidate files
    fake_storage = tmp_path / "fake_storage"
    session_id = "canary-session"
    bucket_name = "canary-bucket"
    gcs_prefix = f"swarms/{session_id}"

    task_item = {
        "task_index": 0,
        "brief": "Run screen with corrupted algebra",
        "candidate_files": ["research/canary-task-0/calc.py"],
        "evidence_files": ["research/canary-task-0/screen.raw.json"],
        "verify_command": f"{shlex.quote(sys.executable)} research/canary-task-0/oracle.py",
        "execution_limits": {"verify_timeout_s": 10},
    }

    monkeypatch.setenv("REPO_URL", "https://example.com/repo")
    monkeypatch.setenv("TASK_MANIFEST", json.dumps([task_item]))
    monkeypatch.setenv("USE_VERTEX_AI", "1")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "0")
    monkeypatch.setenv("SWARM_SESSION_ID", session_id)
    monkeypatch.setenv("GCS_RESULTS_BUCKET", bucket_name)
    monkeypatch.setenv("GCS_BUCKET", bucket_name)
    monkeypatch.setenv("GCS_PREFIX", gcs_prefix)
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(fake_storage))
    monkeypatch.setattr(cloud_worker.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_clone(**kwargs):
        dest_repo = kwargs["repo_dir"]
        _init_git_repo(dest_repo)
        t_dir = dest_repo / "research/canary-task-0"
        t_dir.mkdir(parents=True, exist_ok=True)
        (t_dir / "oracle.py").write_text(DOMAIN_ORACLE_SCRIPT, encoding="utf-8")
        corrupted_data = {
            "size": 2,
            "seed": 42,
            "candidate_weight": 6,
            "baseline_weight": 6,
            "violations": 2,
            "majoranas": [{"x": 1, "z": 0}, {"x": 1, "z": 0}, {"x": 2, "z": 1}, {"x": 2, "z": 3}],
        }
        (t_dir / "screen.raw.json").write_text(json.dumps(corrupted_data, indent=2), encoding="utf-8")

    # Mock execute_task so agent requests PASS without modifying candidate files
    def fake_execute(**kwargs):
        return "PASS", "Agent claimed pass with no source changes."

    monkeypatch.setattr(cloud_worker, "clone_and_checkout_task", fake_clone)
    monkeypatch.setattr(cloud_worker, "execute_task", fake_execute)
    monkeypatch.setattr(cloud_worker, "StorageMessenger", None)

    orig_cwd = os.getcwd()
    try:
        # cloud_worker.main() should run, run verify_command which fails, degrade to ISSUES, and exit(1)
        with pytest.raises(SystemExit) as exc_info:
            cloud_worker.main()
        assert exc_info.value.code == 1
    finally:
        os.chdir(orig_cwd)

    # Check status.json locally in the task repo and in storage
    active_repo = tmp_path / "repo-task-0"
    status_file = active_repo / "status.json"
    assert status_file.is_file()
    status_data = json.loads(status_file.read_text(encoding="utf-8"))
    assert status_data["status"] == "ISSUES"
    assert "Verification:" in status_data["summary"]

    # Harvest and verify that harvested status is ISSUES and patch is quarantined
    harvest_dest = tmp_path / "harvested_c2"
    harvested = result_harvester.harvest_candidate_patches(
        bucket_name=bucket_name,
        prefix=gcs_prefix,
        dest_dir=harvest_dest,
    )
    assert len(harvested) == 1
    assert harvested[0]["task_index"] == 0
    assert harvested[0]["status"] == "ISSUES"
    assert harvested[0]["patch_file"] is None


def test_case_3_command_timeout_diagnostics_retained_no_orphans_issues(tmp_path):
    """Case 3: A bounded command times out (e.g. 1s timeout on a 3s sleep).

    Diagnostics retain partial output, child processes terminate without orphans, status is not PASS.
    """
    repo = tmp_path / "canary_worker_repo_c3"
    repo.mkdir()
    _init_git_repo(repo)

    child_script = (
        "import os, time; "
        "open('child.pid', 'w').write(str(os.getpid())); "
        "time.sleep(4); "
        "open('survived.txt', 'w').write('orphaned');"
    )
    command = (
        f"echo 'partial-stdout-line-1'; echo 'partial-stderr-line-1' >&2; "
        f"{shlex.quote(sys.executable)} -c {shlex.quote(child_script)}"
    )

    res, output = run_bounded_shell(command, repo, timeout_s=1, label="canary-timeout")

    # Command timed out -> exit code 124
    assert res.returncode == 124
    assert "Command timed out after 1 seconds" in res.stderr
    assert "partial-stdout-line-1" in output
    assert "partial-stderr-line-1" in output

    # Diagnostics retained in log file
    diag_logs = list((repo / ".agystack/diagnostics").glob("canary-timeout-*.log"))
    assert len(diag_logs) == 1
    log_content = diag_logs[0].read_text(encoding="utf-8")
    assert "partial-stdout-line-1" in log_content
    assert "partial-stderr-line-1" in log_content

    # Child process was terminated without orphans
    pid_file = repo / "child.pid"
    assert pid_file.is_file()
    child_pid = int(pid_file.read_text(encoding="utf-8").strip())

    time.sleep(1.0)
    assert not (repo / "survived.txt").exists()

    # Check process table: process should not be actively running
    proc_check = subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)], capture_output=True, text=True)
    stat = proc_check.stdout.strip()
    assert not stat or stat.startswith("Z")  # Dead or zombie


def test_case_4_synthetic_credentials_in_evidence_rejected_intact_on_disk_issues(tmp_path):
    """Case 4: A synthetic credential (e.g. AIza... or ghp_... token pattern) in declared evidence

    is rejected. The safe artifact's bytes remain intact on disk, no credential appears in published objects
    or diagnostics, delivery_errors records the error, and status is degraded to ISSUES.
    """
    repo = tmp_path / "canary_worker_repo_c4"
    repo.mkdir()
    _init_git_repo(repo)

    evidence_dir = repo / "research/canary-task-0"
    evidence_dir.mkdir(parents=True)

    # 1. Safe artifact
    safe_file = evidence_dir / "safe_computation.json"
    safe_content = json.dumps({"metric": "majorana_parity", "value": 1.0, "clean": True}, indent=2)
    safe_file.write_text(safe_content, encoding="utf-8")
    safe_bytes_before = safe_file.read_bytes()
    safe_sha_before = hashlib.sha256(safe_bytes_before).hexdigest()

    # 2. File with synthetic credentials
    secret_ghp = "ghp_" + "C" * 36
    secret_aiza = "AIza" + "D" * 35
    cred_file = evidence_dir / "leaked_evidence.txt"
    cred_content = f"Debug log containing sensitive tokens: {secret_ghp} and {secret_aiza}\n"
    cred_file.write_text(cred_content, encoding="utf-8")

    fake_storage = tmp_path / "fake_storage"
    session_id = "canary-session"
    bucket_name = "canary-bucket"
    gcs_prefix = f"swarms/{session_id}"

    with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(fake_storage)}):
        results = storage_uploader.upload_run_artifacts(
            bucket_name=bucket_name,
            prefix=gcs_prefix,
            repo_dir=repo,
            task_index=0,
            status="PASS",
            evidence_files=[
                "research/canary-task-0/safe_computation.json",
                "research/canary-task-0/leaked_evidence.txt",
            ],
        )

        # Safe artifact bytes remain intact on disk
        assert safe_file.read_bytes() == safe_bytes_before
        assert hashlib.sha256(safe_file.read_bytes()).hexdigest() == safe_sha_before

        # Credential file on disk is not silently modified or wiped
        assert cred_file.read_text(encoding="utf-8") == cred_content

        # Credential file was REJECTED from uploaded artifacts
        assert "evidence/research/canary-task-0/leaked_evidence.txt" not in results
        assert "evidence/research/canary-task-0/safe_computation.json" in results

        # No credential appears anywhere in published objects in storage
        task_storage = fake_storage / bucket_name / gcs_prefix / "task-0"
        assert task_storage.is_dir()
        for pub_file in task_storage.rglob("*"):
            if pub_file.is_file():
                content = pub_file.read_text(encoding="utf-8", errors="ignore")
                assert secret_ghp not in content
                assert secret_aiza not in content

        # Diagnostics do not leak credentials
        diag_dir = repo / ".agystack/diagnostics"
        if diag_dir.is_dir():
            for dfile in diag_dir.glob("*.log"):
                dcontent = dfile.read_text(encoding="utf-8", errors="ignore")
                assert secret_ghp not in dcontent
                assert secret_aiza not in dcontent

        # delivery_errors in status.json records the error and status is degraded to ISSUES
        status_file = repo / "status.json"
        assert status_file.is_file()
        status_data = json.loads(status_file.read_text(encoding="utf-8"))
        assert status_data["status"] == "ISSUES"
        assert "delivery_errors" in status_data
        assert any("contains credentials" in err for err in status_data["delivery_errors"])

        # Harvested status is ISSUES
        harvested = result_harvester.harvest_candidate_patches(
            bucket_name=bucket_name,
            prefix=gcs_prefix,
            dest_dir=tmp_path / "harvest_c4",
        )
        assert len(harvested) == 1
        assert harvested[0]["status"] == "ISSUES"


def test_case_5_failed_score_or_results_upload_produces_delivery_errors_and_issues(tmp_path):
    """Case 5: A failed score or results upload produces delivery errors and ISSUES.

    Test both candidate files and no-change tasks.
    """
    fake_storage = tmp_path / "fake_storage_c5"
    bucket_name = "canary-bucket"

    # 5a: With candidate files
    repo_cand = tmp_path / "canary_worker_repo_c5_cand"
    repo_cand.mkdir()
    _init_git_repo(repo_cand)

    (repo_cand / "experiment.py").write_text("updated = True\n", encoding="utf-8")
    (repo_cand / "score.json").write_text(json.dumps({"score": 0.95}), encoding="utf-8")
    (repo_cand / "results.tsv").write_text("metric\tvalue\nscore\t0.95\n", encoding="utf-8")

    def fail_score_upload(bucket, obj_name, file_path):
        if "score.json" in str(obj_name):
            return False
        # Save to local storage for realistic harvesting
        dest = fake_storage / bucket / obj_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)
        return True

    prefix_cand = "swarms/canary-session-cand"
    with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(fake_storage)}):
        with patch.object(storage_uploader, "upload_to_gcs", side_effect=fail_score_upload):
            uploaded_cand = storage_uploader.upload_run_artifacts(
                bucket_name=bucket_name,
                prefix=prefix_cand,
                repo_dir=repo_cand,
                task_index=0,
                status="PASS",
                candidate_files=["experiment.py"],
            )

        assert "score.json" not in uploaded_cand
        status_file_cand = repo_cand / "status.json"
        status_data_cand = json.loads(status_file_cand.read_text(encoding="utf-8"))
        assert status_data_cand["status"] == "ISSUES"
        assert "delivery_errors" in status_data_cand
        assert any("score.json upload failed" in err for err in status_data_cand["delivery_errors"])

        harvested_cand = result_harvester.harvest_candidate_patches(
            bucket_name=bucket_name,
            prefix=prefix_cand,
            dest_dir=tmp_path / "harvest_c5_cand",
        )
        assert len(harvested_cand) == 1
        assert harvested_cand[0]["status"] == "ISSUES"
        # Non-PASS candidate patch is quarantined and not promoted
        assert harvested_cand[0]["patch_file"] is None

    # 5b: No-change tasks (clean working directory, no candidate files modified)
    repo_clean = tmp_path / "canary_worker_repo_c5_clean"
    repo_clean.mkdir()
    _init_git_repo(repo_clean)

    (repo_clean / "score.json").write_text(json.dumps({"score": 0.90}), encoding="utf-8")
    (repo_clean / "results.tsv").write_text("metric\tvalue\nscore\t0.90\n", encoding="utf-8")

    def fail_results_upload(bucket, obj_name, file_path):
        if "results.tsv" in str(obj_name):
            return False
        dest = fake_storage / bucket / obj_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)
        return True

    prefix_clean = "swarms/canary-session-clean"
    with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(fake_storage)}):
        with patch.object(storage_uploader, "upload_to_gcs", side_effect=fail_results_upload):
            uploaded_clean = storage_uploader.upload_run_artifacts(
                bucket_name=bucket_name,
                prefix=prefix_clean,
                repo_dir=repo_clean,
                task_index=0,
                status="PASS",
                candidate_files=[],
            )

        assert "results.tsv" not in uploaded_clean
        status_file_clean = repo_clean / "status.json"
        status_data_clean = json.loads(status_file_clean.read_text(encoding="utf-8"))
        assert status_data_clean["status"] == "ISSUES"
        assert "delivery_errors" in status_data_clean
        assert any("results.tsv upload failed" in err for err in status_data_clean["delivery_errors"])

        harvested_clean = result_harvester.harvest_candidate_patches(
            bucket_name=bucket_name,
            prefix=prefix_clean,
            dest_dir=tmp_path / "harvest_c5_clean",
        )
        assert len(harvested_clean) == 1
        assert harvested_clean[0]["status"] == "ISSUES"
        assert harvested_clean[0]["patch_file"] is None




def test_case_6_sibling_prefix_isolation(tmp_path, monkeypatch):
    """Case 6: Sibling prefix isolation: swarms/canary-other/ cannot satisfy canary coverage

    or contribute a promotable patch in result_harvester.
    """
    fake_storage = tmp_path / "storage"
    canary_dir = fake_storage / "bucket/swarms/canary/task-0"
    canary_dir.mkdir(parents=True)
    (canary_dir / "status.json").write_text(json.dumps({"task_index": 0, "status": "PASS", "score": 0.80}))
    (canary_dir / "score.json").write_text(json.dumps({"score": 0.80}))
    (canary_dir / "patch.diff").write_text("diff --git a/canary b/canary\n+canary")

    sibling_dir = fake_storage / "bucket/swarms/canary-other/task-1"
    sibling_dir.mkdir(parents=True)
    (sibling_dir / "status.json").write_text(json.dumps({"task_index": 1, "status": "PASS", "score": 0.99}))
    (sibling_dir / "score.json").write_text(json.dumps({"score": 0.99}))
    (sibling_dir / "patch.diff").write_text("diff --git a/sibling b/sibling\n+sibling")

    sibling_task0 = fake_storage / "bucket/swarms/canary-other/task-0"
    sibling_task0.mkdir(parents=True)
    (sibling_task0 / "status.json").write_text(json.dumps({"task_index": 0, "status": "PASS", "score": 0.99}))

    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(fake_storage))

    # Harvest for swarms/canary
    harvest_dest = tmp_path / "harvest"
    harvested = result_harvester.harvest_candidate_patches("bucket", "swarms/canary", harvest_dest)

    # Must contain ONLY task-0 from canary, score 0.80
    assert len(harvested) == 1
    assert harvested[0]["task_index"] == 0
    assert harvested[0]["score"] == 0.80
    assert Path(harvested[0]["patch_file"]).read_text() == "diff --git a/canary b/canary\n+canary"

    # Sibling prefix canary-other cannot satisfy canary coverage if 2 tasks are expected
    assert cloud_dispatch.failed_task_count(harvested, 2) == 1

    # Also test GCS mock with trailing-slash prefix isolation
    monkeypatch.delenv("STORAGE_MESSENGER_LOCAL_DIR", raising=False)
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
    mock_storage.Client.return_value.bucket.return_value.list_blobs.side_effect = (
        lambda prefix="": [Blob(k, v) for k, v in blobs.items() if k.startswith(prefix)]
    )

    google_mod = types.ModuleType("google")
    cloud_mod = types.ModuleType("google.cloud")
    google_mod.cloud = cloud_mod
    cloud_mod.storage = mock_storage

    with patch.dict(sys.modules, {"google": google_mod, "google.cloud": cloud_mod, "google.cloud.storage": mock_storage}):
        harvest_gcs = tmp_path / "harvest_gcs"
        gcs_results = result_harvester.harvest_candidate_patches("bucket", "swarms/canary", harvest_gcs)

    assert len(gcs_results) == 1
    assert gcs_results[0]["task_index"] == 0
    assert gcs_results[0]["score"] == 0.80
    assert Path(gcs_results[0]["patch_file"]).read_text() == "canary patch"


def test_task_level_execution_limits_override_cli_env_runtime_defaults():
    """Verify that task-level execution limits override CLI, environment, runtime config, and defaults.

    Also verify immutability and rejection of invalid values.
    """
    # 1. Defaults
    default_limits = resolve_execution_limits(environ={})
    assert (default_limits.max_agent_turns, default_limits.command_timeout_s, default_limits.verify_timeout_s) == (30, 300, 300)

    # 2. Runtime overrides defaults
    runtime_limits = resolve_execution_limits(
        environ={},
        runtime={"max_agent_turns": 40, "command_timeout_s": 350},
    )
    assert (runtime_limits.max_agent_turns, runtime_limits.command_timeout_s, runtime_limits.verify_timeout_s) == (40, 350, 300)

    # 3. Environment overrides runtime
    env_limits = resolve_execution_limits(
        environ={"AGYSTACK_MAX_AGENT_TURNS": "50", "COMMAND_TIMEOUT": "450"},
        runtime={"max_agent_turns": 40, "command_timeout_s": 350},
    )
    assert (env_limits.max_agent_turns, env_limits.command_timeout_s, env_limits.verify_timeout_s) == (50, 450, 300)

    # 4. CLI overrides environment
    cli_limits = resolve_execution_limits(
        environ={"AGYSTACK_MAX_AGENT_TURNS": "50", "COMMAND_TIMEOUT": "450"},
        runtime={"max_agent_turns": 40, "command_timeout_s": 350},
        cli={"max_agent_turns": 60},
    )
    assert (cli_limits.max_agent_turns, cli_limits.command_timeout_s, cli_limits.verify_timeout_s) == (60, 450, 300)

    # 5. Task-level limits override CLI, environment, runtime, and defaults
    task_limits = resolve_execution_limits(
        {"max_agent_turns": 80, "command_timeout_s": 700, "verify_timeout_s": 900},
        environ={"AGYSTACK_MAX_AGENT_TURNS": "50", "COMMAND_TIMEOUT": "450", "VERIFY_TIMEOUT": "550"},
        runtime={"max_agent_turns": 40, "command_timeout_s": 350, "verify_timeout_s": 400},
        cli={"max_agent_turns": 60, "command_timeout_s": 500},
    )
    assert (task_limits.max_agent_turns, task_limits.command_timeout_s, task_limits.verify_timeout_s) == (80, 700, 900)

    # Immutability
    with pytest.raises(FrozenInstanceError):
        task_limits.max_agent_turns = 100

    # Invalid values rejected
    for invalid in [0, -1, True, False, 2.5, "ten", None]:
        with pytest.raises(ValueError):
            resolve_execution_limits({"max_agent_turns": invalid}, environ={})


def test_fake_storage_reproduces_layout_trailing_slash_and_nested_paths(tmp_path, monkeypatch):
    """Verify fake storage reproduces swarms/<session>/task-<index>/ layout, trailing-slash list prefixes,

    and nested task paths with exact byte preservation.
    """
    repo = tmp_path / "layout_repo"
    repo.mkdir()
    _init_git_repo(repo)

    # Create nested evidence directories and files
    deep_evidence = repo / "nested/domain/oracle/checks.json"
    deep_evidence.parent.mkdir(parents=True)
    deep_content = json.dumps({"depth": 3, "oracle_verified": True}, indent=2)
    deep_evidence.write_text(deep_content, encoding="utf-8")

    fake_storage = tmp_path / "fake_storage"
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(fake_storage))

    session_id = "canary-layout-session"
    bucket_name = "test-layout-bucket"
    prefix = f"swarms/{session_id}"

    storage_uploader.upload_run_artifacts(
        bucket_name=bucket_name,
        prefix=prefix,
        repo_dir=repo,
        task_index=0,
        status="PASS",
        evidence_files=["nested/domain/oracle/checks.json"],
    )

    # Verify exact layout in fake storage
    expected_storage_path = (
        fake_storage
        / bucket_name
        / prefix
        / "task-0"
        / "evidence/nested/domain/oracle/checks.json"
    )
    assert expected_storage_path.is_file()
    assert expected_storage_path.read_text(encoding="utf-8") == deep_content

    # Harvest nested paths
    harvest_dest = tmp_path / "harvest_layout"
    harvested = result_harvester.harvest_candidate_patches(bucket_name, prefix, harvest_dest)
    assert len(harvested) == 1
    harvested_nested = harvest_dest / "task-0/evidence/nested/domain/oracle/checks.json"
    assert harvested_nested.is_file()
    assert harvested_nested.read_text(encoding="utf-8") == deep_content


def test_verify_upload_mapping_against_package_inventory(tmp_path):
    """Verify proposed upload mapping locally against the package inventory (package-inventory.json).

    Checks that all listed files exist, sha256 hashes match on disk, and map cleanly to preparation prefixes.
    """
    inventory_path = Path(
        os.environ.get("AGYSTACK_CANARY_PACKAGE_INVENTORY") or CANARY_PACKAGE_INVENTORY
    )
    if not inventory_path.is_file():
        fixture_dir = tmp_path / "canary_fixture"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        packets_dir = fixture_dir / "packets"
        packets_dir.mkdir(parents=True, exist_ok=True)

        inventory_data = {}
        key_files = {
            "bootstrap.py": "#!/usr/bin/env python3\nprint('bootstrapping')\n",
            "verify_research.py": "#!/usr/bin/env python3\nprint('verifying')\n",
            "EVIDENCE_SCHEMA.md": "# Evidence Schema\n",
        }
        for filename, content in key_files.items():
            file_path = fixture_dir / filename
            file_path.write_text(content, encoding="utf-8")
            inventory_data[filename] = hashlib.sha256(file_path.read_bytes()).hexdigest()

        for i in range(1, 25):
            packet_name = f"packets/task-{i:02d}.md"
            packet_path = fixture_dir / packet_name
            packet_path.write_text(f"# Task {i:02d}\n", encoding="utf-8")
            inventory_data[packet_name] = hashlib.sha256(packet_path.read_bytes()).hexdigest()

        inventory_path = fixture_dir / "package-inventory.json"
        inventory_path.write_text(json.dumps(inventory_data, indent=2), encoding="utf-8")
        revision_dir = fixture_dir
    else:
        revision_dir = inventory_path.parent

    assert inventory_path.is_file(), f"Package inventory missing at {inventory_path}"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert len(inventory) >= 27, f"Expected at least 27 inventory files, found {len(inventory)}"

    # Required key files
    assert "bootstrap.py" in inventory
    assert "verify_research.py" in inventory
    assert "EVIDENCE_SCHEMA.md" in inventory
    assert any(re.match(r"^packets/task-\d{2}\.md$", k) for k in inventory)

    canary_session = "phasepoly24-canary-20261025"
    preparation_prefix = f"swarms/{canary_session}/preparation"

    upload_mapping = {}
    for rel_path, expected_sha in inventory.items():
        file_path = revision_dir / rel_path
        assert file_path.is_file(), f"Inventory item {rel_path} does not exist at {file_path}"
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, (
            f"Hash mismatch for {rel_path}: expected {expected_sha}, got {actual_sha}"
        )
        # Proposed destination in bucket
        dest_blob = f"{preparation_prefix}/{rel_path}"
        upload_mapping[rel_path] = dest_blob

    # Verify every destination blob has proper prefix and valid layout
    for rel_path, dest_blob in upload_mapping.items():
        assert dest_blob.startswith(f"{preparation_prefix}/")
        assert ".." not in dest_blob
        assert not dest_blob.endswith("/")


EXPERIMENT_CANARY_SCRIPT = """import argparse, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--size', type=int, required=True)
p.add_argument('--seed', type=int, required=True)
p.add_argument('--output', required=True)
args = p.parse_args()

majoranas = [
    {'x': 1, 'z': 0},
    {'x': 1, 'z': 1},
    {'x': 2, 'z': 1},
    {'x': 2, 'z': 3},
]
if args.size == 1:
    majoranas = majoranas[:2]

violations = sum(
    (bin(a['x'] & b['z']).count('1') + bin(a['z'] & b['x']).count('1')) % 2 != 1
    for i, a in enumerate(majoranas)
    for b in majoranas[i + 1:]
)
weight = sum(bin(m['x'] | m['z']).count('1') for m in majoranas)
out = {
    'size': args.size,
    'seed': args.seed,
    'candidate_weight': weight,
    'baseline_weight': args.size * (args.size + 1),
    'violations': violations,
    'majoranas': majoranas,
}
Path(args.output).write_text(json.dumps(out, indent=2), encoding='utf-8')
"""

DOMAIN_ORACLE_CANARY_SCRIPT = """import json, sys
from pathlib import Path

raw = json.loads(Path('screen.raw.json').read_text(encoding='utf-8'))
I = [[1, 0], [0, 1]]
X = [[0, 1], [1, 0]]
Y = [[0, -1j], [1j, 0]]
Z = [[1, 0], [0, -1]]

def tensor(a, b):
    return [[a[i // len(b)][j // len(b)] * b[i % len(b)][j % len(b)]
             for j in range(len(a) * len(b))] for i in range(len(a) * len(b))]

def mat_mul(a, b):
    n = len(a)
    return [[sum(a[i][k] * b[k][j] for k in range(n)) for j in range(n)] for i in range(n)]

def matrix(mask):
    out = [[1]]
    for k in range(2):
        x, z = (mask['x'] >> k) & 1, (mask['z'] >> k) & 1
        out = tensor(out, Y if x and z else X if x else Z if z else I)
    return out

matrices = [matrix(m) for m in raw['majoranas']]
count = 0
for i, a in enumerate(matrices):
    for j, b in enumerate(matrices):
        ab, ba = mat_mul(a, b), mat_mul(b, a)
        expected = 2 if i == j else 0
        for r in range(4):
            for c in range(4):
                val = ab[r][c] + ba[r][c]
                target = expected if r == c else 0
                assert abs(val - target) < 1e-10
        count += 1

print(json.dumps({'checks': [{'name': 'explicit_matrix_majorana_anticommutators', 'passed': True, 'sample_count': count}]}))
"""


def _load_canary_manifest_and_revision_dir(tmp_path: Path):
    manifest_path = CANARY_REVISION3_DIR / "canary-manifest.json"
    if manifest_path.is_file():
        revision_dir = CANARY_REVISION3_DIR
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest, revision_dir

    # Fallback fixture if revision3 is missing
    fixture_dir = tmp_path / "canary_fallback_fixture"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    packets_dir = fixture_dir / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)

    task_packet = packets_dir / "task-01.md"
    task_packet.write_text(
        "You own the standalone canary verification screen.\n"
        "Scientific pursuit (verdict: pursue) requires meeting your declared scientific acceptance rule with verified controls.\n",
        encoding="utf-8",
    )
    packet_sha = hashlib.sha256(task_packet.read_bytes()).hexdigest()

    schema_file = fixture_dir / "EVIDENCE_SCHEMA.md"
    schema_file.write_text("# Evidence Schema\n", encoding="utf-8")
    schema_sha = hashlib.sha256(schema_file.read_bytes()).hexdigest()

    verifier_file = fixture_dir / "verify_research.py"
    verifier_code = (
        "import argparse, json, subprocess, sys\n"
        "from pathlib import Path\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--task-dir', required=True)\n"
        "p.add_argument('--expected-json', required=True)\n"
        "args = p.parse_args()\n"
        "td = Path(args.task_dir)\n"
        "rep = json.loads((td / 'report.json').read_text())\n"
        "dc = json.loads((td / 'domain_check.json').read_text())\n"
        "res = subprocess.run(dc['oracle_command'], cwd=td, capture_output=True)\n"
        "if res.returncode != 0: sys.exit(1)\n"
        "if rep.get('baseline_gate', {}).get('exit_code') != 0: sys.exit(1)\n"
        "if rep.get('target_modified') and rep.get('final_gate', {}).get('exit_code') != 0: sys.exit(1)\n"
        "print(json.dumps({'execution_status': 'PASS'}))\n"
    )
    verifier_file.write_text(verifier_code, encoding="utf-8")
    verifier_sha = hashlib.sha256(verifier_file.read_bytes()).hexdigest()

    bootstrap_file = fixture_dir / "bootstrap.py"
    bootstrap_code = (
        "import hashlib, json, re\n"
        "from pathlib import Path\n\n"
        "def sha(path):\n"
        "    return hashlib.sha256(Path(path).read_bytes()).hexdigest()\n\n"
        "def main(config):\n"
        "    from google.cloud import storage\n"
        "    assert re.fullmatch(r'task-(?:0[1-9]|1[0-9]|2[0-4])', config['task_id'])\n"
        "    bucket = storage.Client(project=config['project']).bucket(config['bucket'])\n"
        "    output = Path.cwd() / 'research' / config['task_id']\n"
        "    output.mkdir(parents=True, exist_ok=True)\n"
        "    archive = Path('/tmp/phasepoly-source.tar.gz')\n"
        "    bucket.blob(config['prefix'] + '/source.tar.gz').download_to_filename(archive)\n"
        "    assert sha(archive) == config['source_sha256']\n"
        "    package = config['preparation_prefix']\n"
        "    for remote, local, digest in [\n"
        "        ('verify_research.py', 'verify_research.py', config['verifier_sha256']),\n"
        "        ('EVIDENCE_SCHEMA.md', 'EVIDENCE_SCHEMA.md', config['schema_sha256']),\n"
        "        ('packets/' + config['task_id'] + '.md', 'context.md', config['context_packet_sha256']),\n"
        "    ]:\n"
        "        path = output / local\n"
        "        bucket.blob(package + '/' + remote).download_to_filename(path)\n"
        "        assert sha(path) == digest\n"
    )
    bootstrap_file.write_text(bootstrap_code, encoding="utf-8")
    bootstrap_sha = hashlib.sha256(bootstrap_file.read_bytes()).hexdigest()

    task_config = {
        "project": "agystack-test-deepseek-88",
        "bucket": "agystack-test-deepseek-88-swarm-results",
        "prefix": "swarms/phasepoly24-general-20261024/source",
        "environment_prefix": "swarms/phasepoly24-20261024/source",
        "source_sha256": "2e9de7d3064b8a7d3510f57510f1ad9eb4c8faecbed3e3a2c9a474ef7a746444",
        "environment_sha256": "480d7dba8cd2bd44c0465cdfc33974e3f4681542c8bed65bfc7b7e608b1f03f7",
        "brief_document_sha256": "21fc20120b31d2269ddc6d137d2a56f8811f6d94ec037a20fcbf0e9afd28a70e",
        "session": "phasepoly24-canary-20261025",
        "preparation_prefix": "swarms/phasepoly24-canary-20261025/preparation",
        "output_prefix": "swarms/phasepoly24-canary-20261025/evidence",
        "source_base_commit": "d2966d02409a0c7ac749636b97b9e95947c10a9a",
        "execution_limits": {"max_agent_turns": 30, "command_timeout_s": 300, "verify_timeout_s": 120},
        "container_timeout_s": 1800,
        "profile": "canary",
        "task_id": "task-01",
        "context_packet_sha256": packet_sha,
        "entry_points": ["python/exact_decode.py"],
        "verifier_sha256": verifier_sha,
        "schema_sha256": schema_sha,
    }

    loader = (
        "from google.cloud import storage; import hashlib,subprocess,sys; "
        "p='/tmp/phasepoly-bootstrap-r3.py'; "
        f"storage.Client(project='agystack-test-deepseek-88').bucket('agystack-test-deepseek-88-swarm-results')"
        f".blob('swarms/phasepoly24-canary-20261025/preparation/bootstrap.py').download_to_filename(p); "
        f"assert hashlib.sha256(open(p,'rb').read()).hexdigest()=={bootstrap_sha!r}; "
        f"subprocess.run([sys.executable,p,{json.dumps(task_config, separators=(',', ':'))!r}],check=True)"
    )
    expected_prov = {
        "task_id": "task-01",
        "session": "phasepoly24-canary-20261025",
        "source_sha256": "2e9de7d3064b8a7d3510f57510f1ad9eb4c8faecbed3e3a2c9a474ef7a746444",
        "source_base_commit": "d2966d02409a0c7ac749636b97b9e95947c10a9a",
        "brief_document_sha256": "21fc20120b31d2269ddc6d137d2a56f8811f6d94ec037a20fcbf0e9afd28a70e",
        "context_packet_sha256": packet_sha,
    }
    brief = (
        "You own the standalone canary verification screen for Phase 3 deployment handoff.\n"
        + task_packet.read_text(encoding="utf-8")
        + "\nBOOTSTRAP COMMAND\npython3 -c "
        + shlex.quote(loader)
        + "\nOUTPUT_PREFIX=swarms/phasepoly24-canary-20261025/evidence/task-01\nPROVENANCE="
        + json.dumps(expected_prov, separators=(",", ":"))
        + "\n"
    )
    verifier_path = "research/task-01/verify_research.py"
    verify_argv = ["python3", verifier_path, "--task-dir", "research/task-01",
                   "--expected-json", json.dumps(expected_prov, separators=(",", ":"))]
    guarded_verify = (
        "import hashlib,subprocess; "
        f"assert hashlib.sha256(open({verifier_path!r},'rb').read()).hexdigest()=={verifier_sha!r}; "
        f"subprocess.run({verify_argv!r},check=True)"
    )
    manifest = [{
        "task_index": 0,
        "type": "agent",
        "model": "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
        "branch": "phasepoly-r3-canary-task-01",
        "brief": brief,
        "candidate_files": ["research/task-01"],
        "evidence_files": ["research/task-01"],
        "execution_limits": {"max_agent_turns": 30, "command_timeout_s": 300, "verify_timeout_s": 120},
        "verify_command": "python3 -c " + shlex.quote(guarded_verify),
    }]
    (fixture_dir / "canary-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest, fixture_dir


def _extract_bootstrap_config(brief: str) -> dict:
    bootstrap_cmd = brief.split("BOOTSTRAP COMMAND\n")[1].split("\nOUTPUT_PREFIX=")[0]
    code = shlex.split(bootstrap_cmd)[2]
    calls = [
        n for n in ast.walk(ast.parse(code))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
    ]
    return json.loads(ast.literal_eval(calls[0].args[0].elts[2]))


def _run_mocked_bootstrap(revision_dir: Path, config: dict, repo_dir: Path, *, missing_blobs: set = None, corrupted_blobs: dict = None):
    missing = missing_blobs or set()
    corrupted = corrupted_blobs or {}

    spec = importlib.util.spec_from_file_location("canary_bootstrap", revision_dir / "bootstrap.py")
    boot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boot)

    buf_source = io.BytesIO()
    with tarfile.open(fileobj=buf_source, mode="w:gz") as tf:
        ti1 = tarfile.TarInfo(name="docs/CLOUD_SWARM_RESEARCH_PATHS.md")
        c1 = b"Portfolio text\n"
        ti1.size = len(c1)
        tf.addfile(ti1, io.BytesIO(c1))
        ti2 = tarfile.TarInfo(name="python/exact_decode.py")
        c2 = b"def decode(): pass\n"
        ti2.size = len(c2)
        tf.addfile(ti2, io.BytesIO(c2))
    source_bytes = buf_source.getvalue()

    buf_env = io.BytesIO()
    with tarfile.open(fileobj=buf_env, mode="w:gz") as tf:
        ti = tarfile.TarInfo(name="phasepoly-runtime/README")
        c = b"runtime\n"
        ti.size = len(c)
        tf.addfile(ti, io.BytesIO(c))
    env_bytes = buf_env.getvalue()

    class MockBlob:
        def __init__(self, name: str):
            self.name = name

        def download_to_filename(self, filename: str):
            dest = Path(filename)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if any(m in self.name for m in missing):
                raise FileNotFoundError(f"Blob {self.name} missing in mock storage")
            if any(k in self.name for k in corrupted):
                key = next(k for k in corrupted if k in self.name)
                dest.write_bytes(corrupted[key])
                return
            if self.name.endswith("source.tar.gz"):
                dest.write_bytes(source_bytes)
            elif self.name.endswith("environment.tar.gz"):
                dest.write_bytes(env_bytes)
            elif self.name.endswith("verify_research.py"):
                dest.write_bytes((revision_dir / "verify_research.py").read_bytes())
            elif self.name.endswith("EVIDENCE_SCHEMA.md"):
                dest.write_bytes((revision_dir / "EVIDENCE_SCHEMA.md").read_bytes())
            elif "packets/" in self.name:
                packet_name = self.name.split("packets/")[1]
                src = revision_dir / "packets" / packet_name
                if not src.is_file():
                    raise FileNotFoundError(f"Packet not found: {src}")
                dest.write_bytes(src.read_bytes())
            else:
                raise ValueError(f"Unknown blob {self.name}")

        def download_as_text(self):
            if any(m in self.name for m in missing):
                raise FileNotFoundError(f"Blob {self.name} missing in mock storage")
            if self.name.endswith("environment.json"):
                return json.dumps({"environment_sha256": config.get("environment_sha256", "")})
            raise ValueError(f"Unknown blob for text download: {self.name}")

    class MockBucket:
        def blob(self, name: str):
            return MockBlob(name)

    class MockStorageClient:
        def __init__(self, project=None):
            pass

        def bucket(self, name: str):
            return MockBucket()

    mock_google = types.ModuleType("google")
    mock_gcloud = types.ModuleType("google.cloud")
    mock_storage = types.ModuleType("google.cloud.storage")
    mock_storage.Client = MockStorageClient
    mock_gcloud.storage = mock_storage
    mock_google.cloud = mock_gcloud

    orig_sha = getattr(boot, "sha", lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest())
    def patched_sha(path):
        p = Path(path)
        if p.name == "phasepoly-source.tar.gz":
            return config.get("source_sha256", orig_sha(p))
        if p.name == "phasepoly-environment.tar.gz":
            return config.get("environment_sha256", orig_sha(p))
        if p.name == "CLOUD_SWARM_RESEARCH_PATHS.md":
            return config.get("brief_document_sha256", orig_sha(p))
        return orig_sha(p)

    boot.sha = patched_sha

    orig_run = subprocess.run
    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd == ["make", "check"]:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="Baseline make check passed\n")
        return orig_run(cmd, *args, **kwargs)

    orig_cwd = os.getcwd()
    os.chdir(repo_dir)
    try:
        with patch.dict(sys.modules, {"google": mock_google, "google.cloud": mock_gcloud, "google.cloud.storage": mock_storage}):
            with patch("subprocess.run", side_effect=patched_run):
                boot.main(config)
    finally:
        os.chdir(orig_cwd)


def _populate_valid_research_artifacts(repo_dir: Path, config: dict):
    task_dir = repo_dir / "research" / config["task_id"]
    task_dir.mkdir(parents=True, exist_ok=True)

    (task_dir / "experiment.py").write_text(EXPERIMENT_CANARY_SCRIPT, encoding="utf-8")
    (task_dir / "oracle.py").write_text(DOMAIN_ORACLE_CANARY_SCRIPT, encoding="utf-8")

    cmd_sanity = ["python3", "experiment.py", "--size", "1", "--seed", "0", "--output", "sanity.raw.json"]
    cmd_screen = ["python3", "experiment.py", "--size", "2", "--seed", "1", "--output", "screen.raw.json"]

    subprocess.run(cmd_sanity, cwd=task_dir, capture_output=True, text=True, check=True)
    subprocess.run(cmd_screen, cwd=task_dir, capture_output=True, text=True, check=True)

    commands = [
        {"argv": cmd_sanity, "timeout_s": 10, "output_files": ["sanity.raw.json"]},
        {"argv": cmd_screen, "timeout_s": 10, "output_files": ["screen.raw.json"]},
    ]

    res_oracle = subprocess.run(["python3", "oracle.py"], cwd=task_dir, capture_output=True, text=True, check=True)
    checks_data = json.loads(res_oracle.stdout)["checks"]

    contract = {
        "task_id": config["task_id"],
        "hypothesis": "Canary screen verifies 2-mode Majorana algebra anticommutators without violations.",
        "corpus": {"kind": "synthetic", "description": "Jordan-Wigner Majorana representation on 1 and 2 modes.", "evidence_files": ["screen.raw.json"]},
        "sizes": [1, 2],
        "seeds": [0, 1],
        "controls": ["Jordan-Wigner canonical algebra"],
        "metrics": ["violations", "candidate_weight", "baseline_weight"],
        "acceptance_rule": "Zero anticommutator violations across all matrix pairs.",
        "compute_limits": {"max_size": 2, "max_steps": 10, "max_samples": 3, "wall_time_s": 30, "cpu_time_s": 30},
        "commands": commands,
        "sanity_case": {"size": 1, "max_steps": 5, "max_samples": 1, "command": commands[0]},
    }
    (task_dir / "contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")

    contract_sha = hashlib.sha256((task_dir / "contract.json").read_bytes()).hexdigest()

    runs = [
        {
            "kind": "sanity",
            "command": commands[0],
            "seed": 0,
            "size": 1,
            "steps": 1,
            "samples": 1,
            "exit_code": 0,
            "duration_s": 0.05,
            "output_files": ["sanity.raw.json"],
            "metrics": json.loads((task_dir / "sanity.raw.json").read_text(encoding="utf-8")),
        },
        {
            "kind": "screen",
            "command": commands[1],
            "seed": 1,
            "size": 2,
            "steps": 2,
            "samples": 2,
            "exit_code": 0,
            "duration_s": 0.05,
            "output_files": ["screen.raw.json"],
            "metrics": json.loads((task_dir / "screen.raw.json").read_text(encoding="utf-8")),
        },
    ]
    for r in runs:
        r["metrics"] = {k: r["metrics"][k] for k in contract["metrics"]}

    experiment = {
        "contract_sha256": contract_sha,
        "sample_counts": {"sanity": 1, "screen": 2},
        "exit_codes": [0, 0],
        "runs": runs,
    }
    (task_dir / "experiment.json").write_text(json.dumps(experiment, indent=2), encoding="utf-8")

    domain_check = {
        "oracle_command": ["python3", "oracle.py"],
        "timeout_s": 10,
        "exit_code": 0,
        "evidence_files": ["oracle.py", "screen.raw.json"],
        "checks": checks_data,
    }
    (task_dir / "domain_check.json").write_text(json.dumps(domain_check, indent=2), encoding="utf-8")

    (task_dir / "baseline.log").write_text("Baseline make check passed\n", encoding="utf-8")
    (task_dir / "baseline.json").write_text(json.dumps({"exit_code": 0, "command": ["make", "check"]}), encoding="utf-8")
    (task_dir / "report.md").write_text("# Canary Report\nMajorana screen verified.\n", encoding="utf-8")

    provenance_keys = ["task_id", "session", "source_sha256", "source_base_commit", "brief_document_sha256", "context_packet_sha256"]
    prov = {k: config[k] for k in provenance_keys}
    (task_dir / "provenance.json").write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")

    report = {
        "schema_version": 1,
        **prov,
        "title": "Canary Majorana Algebra Screen",
        "model": "local-canary-tester",
        "hypothesis": contract["hypothesis"],
        "execution_status": "PASS",
        "verdict": "pursue",
        "rl_eligibility": "ineligible",
        "contract_sha256": contract_sha,
        "experiment_commands": commands,
        "seeds": [0, 1],
        "sample_counts": {"sanity": 1, "screen": 2},
        "target_modified": False,
        "baseline_gate": {"status": "pass", "exit_code": 0, "evidence_files": ["baseline.log"]},
        "final_gate": {"status": "not_required", "evidence_files": ["baseline.log"]},
        "four_rl_gates": [
            {"gate_id": i, "status": "unresolved", "reason": "Canary screen does not train RL.", "evidence_files": ["experiment.json"]}
            for i in range(1, 5)
        ],
        "premise_audit": [
            {"statement": "Majorana algebra holds on tiny instances.", "status": "supported", "evidence_files": ["domain_check.json"]}
        ],
        "findings": [
            {"statement": "Zero anticommutator violations in 16 checks.", "evidence_files": ["screen.raw.json"]}
        ],
        "witness_files": ["oracle.py", "screen.raw.json"],
        "limitations": ["Synthetic small Majorana fixture."],
        "closest_prior_work": ["Jordan-Wigner canonical transformation."],
        "next_decisive_experiment": {
            "question": "Does 3-mode Majorana algebra scale?",
            "argv": ["python3", "oracle.py"],
            "acceptance_rule": "Zero violations.",
            "compute_limits": contract["compute_limits"],
        },
        "machine": {"platform": sys.platform, "versions": {"python": sys.version.split()[0]}},
    }

    art_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in task_dir.iterdir()
        if p.is_file() and p.name != "report.json"
    }
    report["artifact_sha256"] = art_hashes
    (task_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def test_end_to_end_generated_canary_manifest_execution(tmp_path):
    """Test 1: Verify manifest structure of canary-manifest.json."""
    manifest, _ = _load_canary_manifest_and_revision_dir(tmp_path)
    assert len(manifest) == 1
    task = manifest[0]
    assert task["task_index"] == 0
    assert task["branch"] == "phasepoly-r3-canary-task-01"
    assert task["execution_limits"] == {
        "max_agent_turns": 30,
        "command_timeout_s": 300,
        "verify_timeout_s": 120,
    }
    assert "BOOTSTRAP COMMAND" in task["brief"]
    assert "PROVENANCE" in task["brief"]

    verify_cmd = task["verify_command"]
    vcode = shlex.split(verify_cmd)[2]
    assert "assert hashlib.sha256(open('research/task-01/verify_research.py','rb').read()).hexdigest()==" in vcode
    assert "subprocess.run(['python3', 'research/task-01/verify_research.py'" in vcode
    assert "check=True" in vcode
    compile(vcode, "canary-verifier", "exec")


def test_e2e_canary_manifest_pass(tmp_path, monkeypatch):
    """Positive End-to-End Case: Complete local execution path from bootstrap to verifier,

    artifact upload, and result harvesting.
    """
    manifest, rev_dir = _load_canary_manifest_and_revision_dir(tmp_path)
    task_item = manifest[0]

    repo = tmp_path / "repo_e2e_pass"
    repo.mkdir()
    _init_git_repo(repo)

    config = _extract_bootstrap_config(task_item["brief"])

    _run_mocked_bootstrap(rev_dir, config, repo)

    task_dir = repo / "research" / config["task_id"]
    assert task_dir.is_dir()

    verifier_file = task_dir / "verify_research.py"
    schema_file = task_dir / "EVIDENCE_SCHEMA.md"
    context_file = task_dir / "context.md"

    assert verifier_file.is_file()
    assert hashlib.sha256(verifier_file.read_bytes()).hexdigest() == config["verifier_sha256"]
    assert schema_file.is_file()
    assert hashlib.sha256(schema_file.read_bytes()).hexdigest() == config["schema_sha256"]
    assert context_file.is_file()
    assert hashlib.sha256(context_file.read_bytes()).hexdigest() == config["context_packet_sha256"]

    context_text = context_file.read_text(encoding="utf-8")
    assert (
        "Scientific pursuit (verdict: pursue) requires meeting your declared scientific acceptance rule with verified controls."
        in context_text
    )

    _populate_valid_research_artifacts(repo, config)

    subprocess.run(["git", "add", "research/task-01"], cwd=repo, check=True)

    vcode = shlex.split(task_item["verify_command"])[2]
    res_verify = subprocess.run([sys.executable, "-c", vcode], cwd=repo, capture_output=True, text=True)
    assert res_verify.returncode == 0, f"Verifier failed:\nSTDOUT: {res_verify.stdout}\nSTDERR: {res_verify.stderr}"

    v_data = json.loads(res_verify.stdout)
    assert v_data.get("execution_status") == "PASS"

    fake_storage = tmp_path / "fake_storage_pass"
    bucket_name = "canary-bucket"
    session_id = "phasepoly24-canary-20261025"
    gcs_prefix = f"swarms/{session_id}"
    monkeypatch.setenv("STORAGE_MESSENGER_LOCAL_DIR", str(fake_storage))

    expected_raw = task_dir / "screen.raw.json"
    expected_raw_bytes = expected_raw.read_bytes()

    storage_uploader.upload_run_artifacts(
        bucket_name=bucket_name,
        prefix=gcs_prefix,
        repo_dir=repo,
        task_index=0,
        status="PASS",
        candidate_files=task_item["candidate_files"],
        evidence_files=task_item["evidence_files"],
    )

    harvest_dest = tmp_path / "harvest_pass"
    harvested = result_harvester.harvest_candidate_patches(
        bucket_name=bucket_name,
        prefix=gcs_prefix,
        dest_dir=harvest_dest,
    )
    assert len(harvested) == 1
    assert harvested[0]["task_index"] == 0
    assert harvested[0]["status"] == "PASS"

    harvested_raw = harvest_dest / "task-0/evidence/research/task-01/screen.raw.json"
    assert harvested_raw.is_file()
    assert harvested_raw.read_bytes() == expected_raw_bytes


def test_e2e_canary_negative_task00_mismatch(tmp_path):
    """Negative control: config['task_id'] = 'task-00' reproduces the old task-00 bug and raises AssertionError."""
    manifest, rev_dir = _load_canary_manifest_and_revision_dir(tmp_path)
    config = _extract_bootstrap_config(manifest[0]["brief"])
    config["task_id"] = "task-00"

    repo = tmp_path / "repo_task00"
    repo.mkdir()
    _init_git_repo(repo)

    with pytest.raises(AssertionError):
        _run_mocked_bootstrap(rev_dir, config, repo)


def test_e2e_canary_negative_missing_packet(tmp_path):
    """Negative control: missing packets/task-01.md in storage causes bootstrap to fail before setup completes."""
    manifest, rev_dir = _load_canary_manifest_and_revision_dir(tmp_path)
    config = _extract_bootstrap_config(manifest[0]["brief"])

    repo = tmp_path / "repo_missing_packet"
    repo.mkdir()
    _init_git_repo(repo)

    with pytest.raises((FileNotFoundError, Exception)):
        _run_mocked_bootstrap(rev_dir, config, repo, missing_blobs={"packets/task-01.md"})

    task_dir = repo / "research" / config["task_id"]
    assert not (task_dir / "context.md").exists()


def test_e2e_canary_negative_tampered_packet(tmp_path):
    """Negative control: altered packet bytes in storage causes sha mismatch and raises AssertionError."""
    manifest, rev_dir = _load_canary_manifest_and_revision_dir(tmp_path)
    config = _extract_bootstrap_config(manifest[0]["brief"])

    repo = tmp_path / "repo_tampered_packet"
    repo.mkdir()
    _init_git_repo(repo)

    with pytest.raises(AssertionError):
        _run_mocked_bootstrap(
            rev_dir,
            config,
            repo,
            corrupted_blobs={"packets/task-01.md": b"# Tampered packet bytes\n"},
        )


def test_e2e_canary_negative_wrong_scientific_result(tmp_path):
    """Negative control: oracle fails or outputs passed: False, verify_command exits non-zero."""
    manifest, rev_dir = _load_canary_manifest_and_revision_dir(tmp_path)
    task_item = manifest[0]
    config = _extract_bootstrap_config(task_item["brief"])

    repo = tmp_path / "repo_wrong_sci"
    repo.mkdir()
    _init_git_repo(repo)

    _run_mocked_bootstrap(rev_dir, config, repo)
    report = _populate_valid_research_artifacts(repo, config)

    task_dir = repo / "research" / config["task_id"]
    (task_dir / "oracle.py").write_text("import sys\nprint('Domain oracle failure', file=sys.stderr)\nsys.exit(1)\n", encoding="utf-8")
    report["artifact_sha256"]["oracle.py"] = hashlib.sha256((task_dir / "oracle.py").read_bytes()).hexdigest()
    (task_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    vcode = shlex.split(task_item["verify_command"])[2]
    result = subprocess.run([sys.executable, "-c", vcode], cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0


def test_e2e_canary_negative_missing_baseline_gate(tmp_path):
    """Negative control: baseline_gate['exit_code'] = 1 causes verify_command to exit non-zero."""
    manifest, rev_dir = _load_canary_manifest_and_revision_dir(tmp_path)
    task_item = manifest[0]
    config = _extract_bootstrap_config(task_item["brief"])

    repo = tmp_path / "repo_bad_baseline"
    repo.mkdir()
    _init_git_repo(repo)

    _run_mocked_bootstrap(rev_dir, config, repo)
    report = _populate_valid_research_artifacts(repo, config)

    task_dir = repo / "research" / config["task_id"]
    report["baseline_gate"]["exit_code"] = 1
    (task_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    vcode = shlex.split(task_item["verify_command"])[2]
    result = subprocess.run([sys.executable, "-c", vcode], cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0


def test_e2e_canary_negative_failed_final_gate_after_edits(tmp_path):
    """Negative control: target_modified = True and final_gate['exit_code'] = 1 causes verify_command to exit non-zero."""
    manifest, rev_dir = _load_canary_manifest_and_revision_dir(tmp_path)
    task_item = manifest[0]
    config = _extract_bootstrap_config(task_item["brief"])

    repo = tmp_path / "repo_bad_final"
    repo.mkdir()
    _init_git_repo(repo)

    _run_mocked_bootstrap(rev_dir, config, repo)
    report = _populate_valid_research_artifacts(repo, config)

    task_dir = repo / "research" / config["task_id"]
    report["target_modified"] = True
    report["final_gate"]["exit_code"] = 1
    report["final_gate"]["status"] = "fail"
    (task_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    vcode = shlex.split(task_item["verify_command"])[2]
    result = subprocess.run([sys.executable, "-c", vcode], cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0

