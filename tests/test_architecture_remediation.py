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


if __name__ == "__main__":
    unittest.main()
