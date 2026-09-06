#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SWARM_SCRIPTS = REPO_ROOT / "skills" / "swarm" / "scripts"
sys.path.insert(0, str(SWARM_SCRIPTS))

import cloud_dispatch
import cloud_worker
import result_harvester
import storage_messenger
import storage_uploader


class TestArchitectureRemediation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_argument_resolution_parallelism_and_gcs_prefix(self):
        dispatch_script = SWARM_SCRIPTS / "cloud_dispatch.py"
        manifest_file = self.tmp_path / "manifest.json"
        manifest_file.write_text("[]", encoding="utf-8")

        # 1. Test CLI --parallelism 100 overrides runtime config default
        cfg_file = self.tmp_path / "agystack-runtime.json"
        cfg_file.write_text(
            json.dumps({"parallelism": 25, "gcs_bucket": "test-bkt"}),
            encoding="utf-8",
        )

        cmd = [
            sys.executable,
            str(dispatch_script),
            "--dry-run",
            "--manifest", str(manifest_file),
            "--repo", "https://github.com/test/repo.git",
            "--project", "test-project",
            "--session", "sess-12345",
            "--parallelism", "100",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=str(self.tmp_path),
            env=dict(os.environ, GH_TOKEN="fake_tok", GEMINI_API_KEY="fake_key"),
        )
        payload = json.loads(res.stdout)
        self.assertEqual(payload["parallelism"], 100)
        # Default prefix derivation when --gcs-prefix is not passed
        self.assertEqual(payload["env_vars"].get("GCS_PREFIX"), "swarms/sess-12345")

        # 2. Test fallback to runtime config when --parallelism is omitted
        cmd_fallback = [
            sys.executable,
            str(dispatch_script),
            "--dry-run",
            "--manifest", str(manifest_file),
            "--repo", "https://github.com/test/repo.git",
            "--project", "test-project",
            "--session", "sess-fallback",
        ]
        res_fb = subprocess.run(
            cmd_fallback,
            capture_output=True,
            text=True,
            check=True,
            cwd=str(self.tmp_path),
            env=dict(os.environ, GH_TOKEN="fake_tok", GEMINI_API_KEY="fake_key"),
        )
        payload_fb = json.loads(res_fb.stdout)
        self.assertEqual(payload_fb["parallelism"], 25)
        self.assertEqual(payload_fb["env_vars"].get("GCS_PREFIX"), "swarms/sess-fallback")

    def test_strict_status_regex_parsing(self):
        # 1. Exact valid tokens
        status, _ = cloud_worker.evaluate_agent_status("Finished work. [STATUS: PASS]")
        self.assertEqual(status, "PASS")

        status, _ = cloud_worker.evaluate_agent_status("[STATUS: ISSUES]\nFound some edge cases")
        self.assertEqual(status, "ISSUES")

        status, _ = cloud_worker.evaluate_agent_status("[STATUS:  BLOCKED ] Out of quota")
        self.assertEqual(status, "BLOCKED")

        # Case-insensitive
        status, _ = cloud_worker.evaluate_agent_status("[status: pass]")
        self.assertEqual(status, "PASS")

        # Support DEV_IMPROVED mapped to PASS
        status, _ = cloud_worker.evaluate_agent_status("[STATUS: DEV_IMPROVED]\nCandidate improved score")
        self.assertEqual(status, "PASS")

        # 2. False positives without strict token must fall back to ISSUES
        status, _ = cloud_worker.evaluate_agent_status("I hope this passes and does not fail password test.")
        self.assertEqual(status, "ISSUES")

        status, _ = cloud_worker.evaluate_agent_status("STATUS: PASS (no brackets)")
        self.assertEqual(status, "ISSUES")

    def test_build_gcloud_command_omits_parallelism_max_retries_and_secrets(self):
        cmd = cloud_dispatch.build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=10,
            parallelism=50,
            region="us-central1",
            project="test-proj",
            env_vars={"FOO": "BAR"},
            wait=True,
            max_retries=3,
            set_secrets="MY_SECRET=sec:1",
        )
        self.assertEqual(cmd[0:5], ["gcloud", "run", "jobs", "execute", "test-worker-job"])
        self.assertIn("--tasks=10", cmd)
        self.assertIn("--region=us-central1", cmd)
        self.assertIn("--project=test-proj", cmd)
        self.assertIn("--wait", cmd)
        self.assertIn("--format=json", cmd)

        # Explicitly absent from execute command
        self.assertFalse(any(arg.startswith("--parallelism") for arg in cmd))
        self.assertFalse(any(arg.startswith("--max-retries") for arg in cmd))
        self.assertFalse(any(arg.startswith("--set-secrets") for arg in cmd))

    def test_harvest_candidate_patches(self):
        # Setup mock local storage directory
        mock_storage = self.tmp_path / "mock_gcs"
        bucket = "test-bucket"
        prefix = "swarms/session-42"
        task0_dir = mock_storage / bucket / prefix / "task-0"
        task1_dir = mock_storage / bucket / prefix / "task-1"
        task0_dir.mkdir(parents=True, exist_ok=True)
        task1_dir.mkdir(parents=True, exist_ok=True)

        (task0_dir / "score.json").write_text(json.dumps({"score": 98.2, "status": "PASS"}), encoding="utf-8")
        (task0_dir / "patch.diff").write_text("--- a/foo\n+++ b/foo\n+pass", encoding="utf-8")

        (task1_dir / "score.json").write_text(json.dumps({"score": 45.0, "status": "ISSUES"}), encoding="utf-8")
        (task1_dir / "patch.diff").write_text("--- a/bar\n+++ b/bar\n+fail", encoding="utf-8")

        dest_dir = self.tmp_path / "downloaded_patches"

        with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(mock_storage)}):
            results = result_harvester.harvest_candidate_patches(
                bucket_name=bucket,
                prefix=prefix,
                dest_dir=dest_dir,
            )

        self.assertEqual(len(results), 2)
        r0 = results[0]
        self.assertEqual(r0["task_index"], 0)
        self.assertEqual(r0["score"], 98.2)
        self.assertEqual(r0["status"], "PASS")
        self.assertTrue(Path(r0["patch_file"]).is_file())
        self.assertTrue(Path(r0["score_file"]).is_file())
        self.assertEqual(Path(r0["patch_file"]).read_text(encoding="utf-8"), "--- a/foo\n+++ b/foo\n+pass")

        r1 = results[1]
        self.assertEqual(r1["task_index"], 1)
        self.assertEqual(r1["score"], 45.0)
        self.assertEqual(r1["status"], "ISSUES")

    def test_status_json_upload_and_harvesting(self):
        mock_storage = self.tmp_path / "mock_gcs"
        bucket = "test-bucket"
        prefix = "swarms/session-status"
        task_dir = mock_storage / bucket / prefix / "task-0"
        task_dir.mkdir(parents=True, exist_ok=True)

        status_payload = {
            "task_index": 0,
            "status": "PASS",
            "summary": "Completed cache locality optimization",
            "score": 99.4,
            "candidate_files": ["src/pipeline/packet_filter.py"],
            "session_id": "session-status",
        }
        (task_dir / "status.json").write_text(json.dumps(status_payload), encoding="utf-8")
        (task_dir / "patch.diff").write_text("--- a/foo\n+++ b/foo\n+fast", encoding="utf-8")

        dest_dir = self.tmp_path / "downloaded_status"
        with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(mock_storage)}):
            results = result_harvester.harvest_candidate_patches(
                bucket_name=bucket,
                prefix=prefix,
                dest_dir=dest_dir,
            )

        self.assertEqual(len(results), 1)
        r0 = results[0]
        self.assertEqual(r0["task_index"], 0)
        self.assertEqual(r0["status"], "PASS")
        self.assertEqual(r0["score"], 99.4)
        self.assertEqual(r0["summary"], "Completed cache locality optimization")
        self.assertEqual(r0["candidate_files"], ["src/pipeline/packet_filter.py"])
        self.assertTrue(Path(r0["status_file"]).is_file())
        self.assertTrue(Path(r0["patch_file"]).is_file())

    def test_parse_worker_logs_extracts_task_index(self):
        sample_log = (
            "Some preamble\n"
            "================================================================================\n"
            "[STATUS: PASS]\n"
            "Evidence:\n"
            "- Task Index: 7\n"
            "- Branch: worker-7\n"
            "- Commit SHA: deadbeef\n"
            "Summary:\n"
            "Task 7 completed successfully.\n"
            "================================================================================\n"
            "[STATUS: ISSUES]\n"
            "Evidence:\n"
            "- Task Index: 12\n"
            "- Branch: worker-12\n"
            "Summary:\n"
            "Task 12 encountered test failure.\n"
            "================================================================================\n"
        )
        parsed = cloud_dispatch.parse_worker_logs(sample_log)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["status"], "PASS")
        self.assertEqual(parsed[0]["task_index"], 7)
        self.assertIn("Task 7 completed", parsed[0]["summary"])

        self.assertEqual(parsed[1]["status"], "ISSUES")
        self.assertEqual(parsed[1]["task_index"], 12)
        self.assertIn("Task 12 encountered", parsed[1]["summary"])

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_run_preflight_uses_credential_helper_and_clean_url(self, mock_run, mock_urlopen):
        mock_run.return_value = MagicMock(returncode=0, stdout="HEAD\n")
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"candidates": []}'
        mock_resp.headers = {}
        mock_urlopen.return_value = mock_resp

        cloud_dispatch.run_preflight(
            repo_url="https://x-access-token:leaked@github.com/myorg/myrepo.git",
            gh_token="secret_token_12345",
            use_vertex=False,
            gemini_api_key="key",
            project="test-proj",
            region="us-central1",
            model="gemini-2.5-flash",
            dry_run=False,
            gcs_bucket="test-bucket",
        )

        self.assertTrue(mock_run.called)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "git")
        self.assertEqual(cmd[1], "-c")
        self.assertIn("credential.helper=!f() { echo password=secret_token_12345; }; f", cmd[2])
        self.assertEqual(cmd[3], "ls-remote")
        self.assertEqual(cmd[4], "https://github.com/myorg/myrepo.git")
        self.assertEqual(cmd[5], "HEAD")

    def test_storage_messenger_raises_in_cloud_run_without_creds(self):
        env_override = {
            "K_SERVICE": "agystack-worker",
            "CLOUD_RUN_TASK_INDEX": "0",
        }
        with patch.dict(os.environ, env_override, clear=False):
            with patch("storage_uploader.get_oauth_token", return_value=None):
                with patch.dict(sys.modules, {"google.cloud": None, "google.cloud.storage": None}):
                    with self.assertRaises(RuntimeError) as ctx:
                        storage_messenger.StorageMessenger(
                            bucket_name="test-bkt",
                            session_id="sess-test",
                            task_index=0,
                        )
                    self.assertIn("GCS credentials unavailable in Cloud Run environment", str(ctx.exception))

    def test_live_cloud_bidirectional_skips_when_live_bucket_unset(self):
        cmd = [
            sys.executable,
            "-m", "unittest",
            "tests/test_live_cloud_bidirectional.py",
        ]
        clean_env = {k: v for k, v in os.environ.items() if k != "AGYSTACK_LIVE_BUCKET"}
        res = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=clean_env,
        )
        self.assertEqual(res.returncode, 0, f"Test failed with output:\n{res.stderr}\n{res.stdout}")
        self.assertIn("skipped=3", res.stderr + res.stdout)

    def test_script_resolver_path_resolution_in_skill_md(self):
        skill_md = REPO_ROOT / "skills" / "swarm" / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        resolver_pattern = 'find -L "$HOME/.gemini/config/plugins/agystack" ".agents/plugins/agystack" "skills/swarm/scripts" -name cloud_dispatch.py'
        self.assertIn(resolver_pattern, content)

    def test_run_preflight_missing_gcs_bucket_fails_fast(self):
        with self.assertRaises(RuntimeError) as ctx:
            cloud_dispatch.run_preflight(
                repo_url="https://github.com/test/repo.git",
                gh_token="secret_token",
                use_vertex=False,
                gemini_api_key="key",
                project="test-proj",
                region="us-central1",
                model="gemini-3.8-flash",
                dry_run=False,
                gcs_bucket=None,
            )
        self.assertIn("Cloud Run swarms require a GCS bucket", str(ctx.exception))

    def test_upload_run_artifacts_only_generates_patch_when_pass(self):
        repo_test = self.tmp_path / "test_repo"
        repo_test.mkdir(parents=True, exist_ok=True)
        (repo_test / ".git").mkdir()
        (repo_test / "app.py").write_text("print('hello')", encoding="utf-8")

        mock_storage = self.tmp_path / "mock_gcs_upload"
        with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(mock_storage)}):
            with patch("storage_uploader._generate_git_patch", return_value="diff --git a/app.py"):
                # ISSUES status must not generate or upload patch.diff
                res_issues = storage_uploader.upload_run_artifacts(
                    bucket_name="test-bkt",
                    prefix="swarms/test-run",
                    repo_dir=repo_test,
                    task_index=0,
                    status="ISSUES",
                )
                self.assertNotIn("patch.diff", res_issues)
                self.assertFalse((repo_test / "patch.diff").exists())

                # PASS status must generate and upload patch.diff
                res_pass = storage_uploader.upload_run_artifacts(
                    bucket_name="test-bkt",
                    prefix="swarms/test-run",
                    repo_dir=repo_test,
                    task_index=0,
                    status="PASS",
                )
                self.assertIn("patch.diff", res_pass)
                self.assertTrue((repo_test / "patch.diff").exists())

    def test_scoped_git_patch_generation_honors_candidate_files(self):
        repo_dir = self.tmp_path / "git_scope_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, check=True)

        target_file = repo_dir / "target.py"
        target_file.write_text("v1", encoding="utf-8")
        junk_file = repo_dir / "junk.log"
        junk_file.write_text("junk", encoding="utf-8")

        subprocess.run(["git", "add", "target.py", "junk.log"], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

        target_file.write_text("v2", encoding="utf-8")
        junk_file.write_text("junk modified", encoding="utf-8")

        patch_content = storage_uploader._generate_git_patch(repo_dir, candidate_files=["target.py"])
        self.assertIn("target.py", patch_content)
        self.assertNotIn("junk.log", patch_content)

    def test_harvest_candidate_patches_score_delta_ranking(self):
        mock_storage = self.tmp_path / "mock_delta_gcs"
        bucket = "test-delta-bucket"
        prefix = "swarms/delta-session"

        t0 = mock_storage / bucket / prefix / "task-0"
        t1 = mock_storage / bucket / prefix / "task-1"
        t2 = mock_storage / bucket / prefix / "task-2"
        t3 = mock_storage / bucket / prefix / "task-3"
        for t in (t0, t1, t2, t3):
            t.mkdir(parents=True, exist_ok=True)

        (t0 / "score.json").write_text(json.dumps({"score": 90.0, "status": "PASS"}), encoding="utf-8")
        (t1 / "score.json").write_text(json.dumps({"score": 95.0, "status": "PASS"}), encoding="utf-8")
        (t2 / "score.json").write_text(json.dumps({"score": 99.0, "status": "ISSUES"}), encoding="utf-8")
        (t3 / "status.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

        dest_dir = self.tmp_path / "harvest_delta_out"
        with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(mock_storage)}):
            ranked = result_harvester.harvest_candidate_patches(
                bucket_name=bucket,
                prefix=prefix,
                dest_dir=dest_dir,
                baseline_score=88.0,
                sort_by_delta=True,
            )

        self.assertEqual(len(ranked), 4)
        # Rank 1: Task 1 (PASS, delta +7.0)
        self.assertEqual(ranked[0]["task_index"], 1)
        self.assertEqual(ranked[0]["score_delta"], 7.0)
        self.assertEqual(ranked[0]["status"], "PASS")

        # Rank 2: Task 0 (PASS, delta +2.0)
        self.assertEqual(ranked[1]["task_index"], 0)
        self.assertEqual(ranked[1]["score_delta"], 2.0)
        self.assertEqual(ranked[1]["status"], "PASS")

        # Rank 3: Task 3 (PASS, score None)
        self.assertEqual(ranked[2]["task_index"], 3)
        self.assertEqual(ranked[2]["status"], "PASS")

        # Rank 4: Task 2 (ISSUES, delta +11.0, sorted after PASS)
        self.assertEqual(ranked[3]["task_index"], 2)
        self.assertEqual(ranked[3]["status"], "ISSUES")

    def test_harvest_session_cli_standalone(self):
        dispatch_script = SWARM_SCRIPTS / "cloud_dispatch.py"
        mock_storage = self.tmp_path / "mock_cli_gcs"
        bucket = "test-cli-bkt"
        session_id = "sess-cli-harvest"

        task_dir = mock_storage / bucket / f"swarms/{session_id}" / "task-0"
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "score.json").write_text(json.dumps({"score": 92.5, "status": "PASS"}), encoding="utf-8")
        (task_dir / "patch.diff").write_text("--- a/f\n+++ b/f\n+ok", encoding="utf-8")

        cmd = [
            sys.executable,
            str(dispatch_script),
            "--harvest-session", session_id,
            "--gcs-bucket", bucket,
            "--baseline-score", "90.0",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=str(self.tmp_path),
            env=dict(os.environ, STORAGE_MESSENGER_LOCAL_DIR=str(mock_storage)),
        )
        self.assertIn("CANDIDATE PATCHES (RANKED):", res.stdout)
        self.assertIn("Winning Candidate #1", res.stdout)
        self.assertIn("+2.5000", res.stdout)

    def test_worker_fail_closed_on_upload_failure(self):
        worker_dir = self.tmp_path / "worker_fail_repo"
        worker_dir.mkdir(parents=True, exist_ok=True)
        (worker_dir / ".git").mkdir()
        (worker_dir / "target.py").write_text("v2", encoding="utf-8")
        status_file = worker_dir / "status.json"
        status_file.write_text(json.dumps({"status": "PASS", "task_index": 0}), encoding="utf-8")

        mock_storage = self.tmp_path / "mock_gcs_fail"

        # When patch.diff fails to upload, upload_run_artifacts must override status to ISSUES
        with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(mock_storage)}):
            with patch("storage_uploader._generate_git_patch", return_value="diff --git a/target.py"):
                with patch("storage_uploader.upload_to_gcs") as mock_upload:
                    # Let status.json upload succeed, but patch.diff upload fail
                    def fake_upload(bkt, dest, path):
                        if "patch.diff" in str(dest):
                            return False
                        return True

                    mock_upload.side_effect = fake_upload

                    uploaded = storage_uploader.upload_run_artifacts(
                        bucket_name="test-bkt",
                        prefix="swarms/test-atomic",
                        repo_dir=worker_dir,
                        task_index=0,
                        status="PASS",
                        candidate_files=["target.py"],
                    )

                    # patch.diff must not be in uploaded
                    self.assertNotIn("patch.diff", uploaded)
                    # status.json on disk must be updated to ISSUES
                    saved_status = json.loads(status_file.read_text(encoding="utf-8"))
                    self.assertEqual(saved_status.get("status"), "ISSUES")
                    self.assertIn("failed to upload", saved_status.get("evidence", ""))

    def test_generate_git_patch_omits_head_commit_when_commit_sha_is_none(self):
        repo_dir = self.tmp_path / "patch_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / ".git").mkdir()

        executed_cmds = []

        def fake_run(cmd, *args, **kwargs):
            executed_cmds.append(cmd)
            m = MagicMock()
            m.returncode = 0
            m.stdout = "diff --git a/mod.py\n+change"
            return m

        with patch("subprocess.run", side_effect=fake_run):
            # When commit_sha is None, must NOT diff HEAD~1 HEAD
            patch_content = storage_uploader._generate_git_patch(
                repo_dir=repo_dir,
                candidate_files=["mod.py"],
                commit_sha=None,
            )
            self.assertTrue(patch_content)
            for cmd in executed_cmds:
                cmd_str = " ".join(cmd)
                self.assertNotIn("HEAD~1", cmd_str)

        # When commit_sha IS provided, must diff {sha}~1 {sha}
        executed_cmds.clear()
        with patch("subprocess.run", side_effect=fake_run):
            patch_content = storage_uploader._generate_git_patch(
                repo_dir=repo_dir,
                candidate_files=["mod.py"],
                commit_sha="a1b2c3d",
            )
            self.assertTrue(patch_content)
            found_sha_diff = any("a1b2c3d~1" in cmd and "a1b2c3d" in cmd for cmd in executed_cmds)
            self.assertTrue(found_sha_diff)

    def test_result_harvester_sorts_non_numeric_and_nan_metrics(self):
        mock_storage = self.tmp_path / "mock_nan_gcs"
        bucket = "test-nan-bucket"
        prefix = "swarms/nan-session"

        t0 = mock_storage / bucket / prefix / "task-0"
        t1 = mock_storage / bucket / prefix / "task-1"
        t2 = mock_storage / bucket / prefix / "task-2"
        t3 = mock_storage / bucket / prefix / "task-3"
        for t in (t0, t1, t2, t3):
            t.mkdir(parents=True, exist_ok=True)

        # Task 0: string score "N/A"
        (t0 / "score.json").write_text(json.dumps({"score": "N/A", "status": "PASS"}), encoding="utf-8")
        # Task 1: valid float score 95.0
        (t1 / "score.json").write_text(json.dumps({"score": 95.0, "status": "PASS"}), encoding="utf-8")
        # Task 2: None score
        (t2 / "status.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        # Task 3: valid float score 99.0
        (t3 / "score.json").write_text(json.dumps({"score": 99.0, "status": "PASS"}), encoding="utf-8")

        dest_dir = self.tmp_path / "harvest_nan_out"
        with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(mock_storage)}):
            # Must not raise TypeError: must be real number, not str
            results = result_harvester.harvest_candidate_patches(
                bucket_name=bucket,
                prefix=prefix,
                dest_dir=dest_dir,
                sort_by_delta=True,
            )

        self.assertEqual(len(results), 4)
        self.assertEqual(results[0]["task_index"], 3)
        self.assertEqual(results[0]["score"], 99.0)
        self.assertEqual(results[1]["task_index"], 1)
        self.assertEqual(results[1]["score"], 95.0)

    def test_monitor_execution_detects_completed_false(self):
        failed_describe_output = json.dumps({
            "metadata": {"name": "test-exec-failed"},
            "status": {
                "conditions": [
                    {
                        "type": "Completed",
                        "status": "False",
                        "reason": "TasksFailed",
                        "message": "1 of 2 tasks failed in execution",
                    }
                ],
                "succeededCount": 1,
                "failedCount": 1,
            },
        })

        def fake_run(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "describe" in cmd:
                m.stdout = failed_describe_output
            elif "logging" in cmd:
                m.stdout = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            res = cloud_dispatch.monitor_execution(
                execution_name="test-exec-failed",
                project="test-proj",
                region="us-central1",
                task_count=2,
                poll_interval=0.01,
            )
            self.assertFalse(res.succeeded)
            self.assertIn("failed", res.error.lower())
            self.assertIsNotNone(res.data)

    def test_candidate_table_notice_when_no_passing_patches(self):
        import io
        patches = [
            {"task_index": 0, "status": "ISSUES", "score": 80.0, "patch_file": "path/0.diff"},
            {"task_index": 1, "status": "ISSUES", "score": 75.0, "patch_file": "path/1.diff"},
        ]
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cloud_dispatch.print_candidate_patches_table(patches)
            out = mock_out.getvalue()
            self.assertIn("Notice: No passing candidate patches produced.", out)
            self.assertNotIn("1*", out)
            self.assertNotIn("Winning Candidate", out)

    def test_recover_session_id_from_execution(self):
        describe_output = json.dumps({
            "metadata": {"name": "test-exec-123"},
            "spec": {
                "template": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "env": [
                                            {"name": "REPO_URL", "value": "https://github.com/foo/bar.git"},
                                            {"name": "SWARM_SESSION_ID", "value": "recovered-session-999"},
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        })

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=describe_output)
            session = cloud_dispatch.recover_session_id_from_execution("test-exec-123", region="us-central1")
            self.assertEqual(session, "recovered-session-999")

    def test_cloud_worker_fail_closed_in_cloud_mode_without_gcs_bucket(self):
        worker_repo = self.tmp_path / "worker_cloud_repo"
        worker_repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=worker_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=worker_repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=worker_repo, check=True)
        (worker_repo / "app.py").write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=worker_repo, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=worker_repo, check=True)

        env = {
            "CLOUD_RUN_TASK_INDEX": "0",
            "SWARM_SESSION_ID": "sess-fail-closed",
            "REPO_URL": "https://github.com/test/repo.git",
            "GEMINI_API_KEY": "fake_key",
            "TASK_BRIEF": "Optimize app.py",
        }

        def fake_clone(repo_url, gh_token, branch_name, repo_dir, base_branch=None):
            # Mirror the worker_repo
            import shutil
            for item in worker_repo.iterdir():
                if item.is_dir():
                    shutil.copytree(item, repo_dir / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, repo_dir / item.name)

        def fake_execute(*args, **kwargs):
            # Modify app.py
            repo_dir = kwargs.get("repo_dir")
            (repo_dir / "app.py").write_text("v2", encoding="utf-8")
            return ("PASS", "Work completed successfully")

        with patch.dict(os.environ, env, clear=True):
            with patch("cloud_worker.clone_and_checkout_task", side_effect=fake_clone):
                with patch("cloud_worker.execute_task", side_effect=fake_execute):
                    import io
                    with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                        cloud_worker.main()
                        out = mock_out.getvalue()
                        self.assertIn("[STATUS: ISSUES]", out)
                        self.assertIn("Fail-closed: No GCS bucket configured", out)


if __name__ == "__main__":
    unittest.main()
