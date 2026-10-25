#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "swarm" / "scripts"))

import storage_uploader
import cloud_worker


class TestForkUrlResolution(unittest.TestCase):
    def test_authenticated_url_ssh(self):
        url = cloud_worker.build_authenticated_git_url("git@github.com:Layr-Labs/matrices-fast.git", "test_tok")
        self.assertEqual(url, "https://x-access-token:test_tok@github.com/Layr-Labs/matrices-fast.git")

    def test_authenticated_url_https(self):
        url = cloud_worker.build_authenticated_git_url("https://github.com/user/fork-repo.git", "test_tok")
        self.assertEqual(url, "https://x-access-token:test_tok@github.com/user/fork-repo.git")

    def test_authenticated_url_shorthand(self):
        url = cloud_worker.build_authenticated_git_url("my-org/my-repo", "test_tok")
        self.assertEqual(url, "https://x-access-token:test_tok@github.com/my-org/my-repo.git")


class TestArtifactDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("storage_uploader.upload_to_gcs")
    def test_upload_run_artifacts_all_files(self, mock_upload):
        mock_upload.return_value = True

        score_file = self.repo_dir / "score.json"
        score_file.write_text('{"score": 0.85, "geomean_fill_ratio": 0.92}', encoding="utf-8")

        tsv_file = self.repo_dir / "results.tsv"
        tsv_file.write_text("id\tmetric\n1\t0.9\n", encoding="utf-8")

        diff_file = self.repo_dir / "patch.diff"
        diff_file.write_text("--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")

        results = storage_uploader.upload_run_artifacts(
            bucket_name="test-bucket",
            prefix="runs/experiment-1",
            repo_dir=self.repo_dir,
            task_index=3,
            status="PASS",
        )

        self.assertIn("score.json", results)
        self.assertIn("results.tsv", results)
        self.assertIn("patch.diff", results)
        self.assertEqual(results["score.json"], "gs://test-bucket/runs/experiment-1/task-3/score.json")
        self.assertEqual(results["results.tsv"], "gs://test-bucket/runs/experiment-1/task-3/results.tsv")
        self.assertEqual(results["patch.diff"], "gs://test-bucket/runs/experiment-1/task-3/patch.diff")

    @patch("storage_uploader.upload_to_gcs")
    def test_upload_run_artifacts_empty_prefix(self, mock_upload):
        mock_upload.return_value = True

        score_file = self.repo_dir / "score.json"
        score_file.write_text('{"score": 0.85}', encoding="utf-8")

        results = storage_uploader.upload_run_artifacts(
            bucket_name="test-bucket",
            prefix="",
            repo_dir=self.repo_dir,
            task_index=0,
        )

        self.assertEqual(results["score.json"], "gs://test-bucket/task-0/score.json")

    @patch("storage_uploader.upload_to_gcs")
    @patch("storage_uploader._generate_git_patch")
    def test_upload_run_artifacts_generates_patch(self, mock_gen_patch, mock_upload):
        mock_upload.return_value = True
        mock_gen_patch.return_value = "diff --git a/test b/test\n+new line"

        score_file = self.repo_dir / "score.json"
        score_file.write_text('{"score": 0.9}', encoding="utf-8")

        results = storage_uploader.upload_run_artifacts(
            bucket_name="test-bucket",
            prefix="test-prefix",
            repo_dir=self.repo_dir,
            task_index=1,
            status="PASS",
        )

        self.assertIn("patch.diff", results)
        self.assertTrue((self.repo_dir / "patch.diff").is_file())
        self.assertEqual(
            (self.repo_dir / "patch.diff").read_text(encoding="utf-8"), "diff --git a/test b/test\n+new line"
        )


class TestGCSUploadFallback(unittest.TestCase):
    def setUp(self):
        self.prev_local = os.environ.pop("STORAGE_MESSENGER_LOCAL_DIR", None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "sample.txt"
        self.test_file.write_text("test artifact payload", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()
        if self.prev_local is not None:
            os.environ["STORAGE_MESSENGER_LOCAL_DIR"] = self.prev_local

    def test_upload_to_gcs_nonexistent_file(self):
        missing = Path(self.temp_dir.name) / "does_not_exist.txt"
        self.assertFalse(storage_uploader.upload_to_gcs("bkt", "obj", missing))

    @patch("urllib.request.urlopen")
    @patch("storage_uploader.get_oauth_token")
    def test_upload_to_gcs_rest_api_fallback(self, mock_token, mock_urlopen):
        mock_token.return_value = "mock_bearer_token"
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with patch.dict(sys.modules, {"google.cloud": None, "google.cloud.storage": None}):
            res = storage_uploader.upload_to_gcs("my-bucket", "artifacts/sample.txt", self.test_file)
            self.assertTrue(res)

            req = mock_urlopen.call_args[0][0]
            self.assertIn("https://storage.googleapis.com/upload/storage/v1/b/my-bucket/o", req.full_url)
            self.assertEqual(req.headers.get("Authorization"), "Bearer mock_bearer_token")

    @patch("urllib.request.urlopen")
    def test_get_oauth_token_from_metadata(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"access_token": "metadata_token_123"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with patch.dict(os.environ, {}, clear=True):
            token = storage_uploader.get_oauth_token()
            self.assertEqual(token, "metadata_token_123")

    @patch("storage_uploader.get_oauth_token")
    def test_upload_to_gcs_no_token_failure(self, mock_token):
        mock_token.return_value = None
        with patch.dict(sys.modules, {"google.cloud": None, "google.cloud.storage": None}):
            res = storage_uploader.upload_to_gcs("my-bucket", "obj.txt", self.test_file)
            self.assertFalse(res)


class TestScoreParsing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_score_metrics_flat(self):
        score_file = self.repo_dir / "score.json"
        score_file.write_text(
            json.dumps({"score": 0.8123, "accuracy": 0.9412, "latency_ms": 12.5}),
            encoding="utf-8",
        )

        score, accuracy, latency_ms = cloud_worker.parse_score_metrics(self.repo_dir)
        self.assertAlmostEqual(score, 0.8123)
        self.assertAlmostEqual(accuracy, 0.9412)
        self.assertAlmostEqual(latency_ms, 12.5)

    def test_parse_score_metrics_nested(self):
        score_file = self.repo_dir / "score.json"
        data = {
            "score": 0.844936,
            "metrics": {
                "accuracy": 0.944537,
                "latency_ms": 15.2,
            },
        }
        score_file.write_text(json.dumps(data), encoding="utf-8")

        score, accuracy, latency_ms = cloud_worker.parse_score_metrics(self.repo_dir)
        self.assertAlmostEqual(score, 0.844936)
        self.assertAlmostEqual(accuracy, 0.944537)
        self.assertAlmostEqual(latency_ms, 15.2)

    def test_parse_score_metrics_missing(self):
        score, accuracy, latency_ms = cloud_worker.parse_score_metrics(self.repo_dir)
        self.assertIsNone(score)
        self.assertIsNone(accuracy)
        self.assertIsNone(latency_ms)


class TestEvidenceCredentialSafeguards(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        subprocess.run(["git", "init"], cwd=self.repo_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.local"], cwd=self.repo_dir, capture_output=True, check=True
        )
        (self.repo_dir / "app.py").write_text("print('hello')\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=self.repo_dir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo_dir, capture_output=True, check=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("storage_uploader.upload_to_gcs")
    def test_evidence_with_credentials_rejected_and_degrades_pass(self, mock_upload):
        uploaded_payloads = {}

        def spy_upload(bucket, obj, path):
            uploaded_payloads[obj] = Path(path).read_bytes()
            return True

        mock_upload.side_effect = spy_upload

        safe_file = self.repo_dir / "safe.txt"
        safe_bytes = b"safe measurement: 42\n"
        safe_file.write_bytes(safe_bytes)

        evidence_file = self.repo_dir / "proof.txt"
        secret_token = "ghp_" + "a" * 36
        cred_bytes = f"run log with sensitive token: {secret_token}\n".encode("utf-8")
        evidence_file.write_bytes(cred_bytes)

        results = storage_uploader.upload_run_artifacts(
            bucket_name="test-bucket",
            prefix="runs/exp1",
            repo_dir=self.repo_dir,
            task_index=0,
            status="PASS",
            evidence_files=["safe.txt", "proof.txt"],
        )

        self.assertEqual(safe_file.read_bytes(), safe_bytes)
        self.assertEqual(evidence_file.read_bytes(), cred_bytes)
        self.assertNotIn("evidence/proof.txt", results)
        self.assertIn("evidence/safe.txt", results)
        self.assertEqual(
            uploaded_payloads.get("runs/exp1/task-0/evidence/safe.txt"),
            safe_bytes,
        )

        secret_bytes = secret_token.encode("utf-8")
        for obj, payload in uploaded_payloads.items():
            self.assertNotIn(
                secret_bytes,
                payload,
                f"Synthetic secret leaked in outbound upload for {obj}",
            )

        status_file = self.repo_dir / "status.json"
        self.assertTrue(status_file.is_file())
        status_data = json.loads(status_file.read_text(encoding="utf-8"))
        self.assertEqual(status_data["status"], "ISSUES")
        self.assertIn("credentials", status_data.get("evidence", ""))

    @patch("storage_uploader.upload_to_gcs")
    def test_sensitive_filenames_rejected(self, mock_upload):
        mock_upload.return_value = True

        sensitive_names = [
            ".env",
            "server.pem",
            "private.key",
            "id_rsa",
            "id_ed25519",
            "credentials.json",
            "token.json",
        ]
        for name in sensitive_names:
            file_path = self.repo_dir / name
            file_path.write_text("dummy sensitive data\n", encoding="utf-8")
            self.assertTrue(
                storage_uploader.is_sensitive_path(file_path, self.repo_dir),
                f"{name} should be recognized as sensitive path",
            )

        # Also verify symlink is recognized as sensitive path
        target_file = self.repo_dir / "target.txt"
        target_file.write_text("target", encoding="utf-8")
        symlink_file = self.repo_dir / "symlink_file.txt"
        symlink_file.symlink_to(target_file)
        self.assertTrue(
            storage_uploader.is_sensitive_path(symlink_file, self.repo_dir),
            "Symlink should be recognized as sensitive path",
        )

        # When passed as evidence_files, all sensitive files must be rejected and status degraded
        results = storage_uploader.upload_run_artifacts(
            bucket_name="test-bucket",
            prefix="runs/exp1",
            repo_dir=self.repo_dir,
            task_index=0,
            status="PASS",
            evidence_files=sensitive_names + ["symlink_file.txt"],
        )

        for name in sensitive_names:
            self.assertNotIn(f"evidence/{name}", results)
        self.assertNotIn("evidence/symlink_file.txt", results)

        status_file = self.repo_dir / "status.json"
        status_data = json.loads(status_file.read_text(encoding="utf-8"))
        self.assertEqual(status_data["status"], "ISSUES")

    @patch("storage_uploader.upload_to_gcs", return_value=True)
    def test_sensitive_directory_symlink_rejected_and_degrades_pass(self, mock_upload):
        external = self.repo_dir.parent / "external_sensitive"
        external.mkdir(exist_ok=True)
        (external / "leak.log").write_text("secret")

        for location in ["evidence", "diagnostics"]:
            with self.subTest(location=location):
                status_file = self.repo_dir / "status.json"
                if status_file.exists():
                    status_file.unlink()

                evidence_files = []
                if location == "evidence":
                    ev_dir = self.repo_dir / "ev_tree"
                    ev_dir.mkdir(exist_ok=True)
                    (ev_dir / "safe.txt").write_text("admitted bytes")
                    (ev_dir / "sym_dir").symlink_to(external)
                    evidence_files = ["ev_tree"]
                else:
                    diag_dir = self.repo_dir / ".agystack/diagnostics"
                    diag_dir.parent.mkdir(parents=True, exist_ok=True)
                    diag_dir.symlink_to(external)

                artifacts = storage_uploader.upload_run_artifacts(
                    "bucket",
                    "run",
                    self.repo_dir,
                    0,
                    status="PASS",
                    evidence_files=evidence_files,
                )
                self.assertNotIn("evidence/ev_tree/sym_dir/leak.log", artifacts)
                self.assertNotIn("evidence/.agystack/diagnostics/leak.log", artifacts)
                status_data = json.loads(status_file.read_text(encoding="utf-8"))
                self.assertEqual(status_data["status"], "ISSUES")
                self.assertTrue(status_data.get("delivery_errors"))
                self.assertEqual((external / "leak.log").read_text(), "secret")
                if location == "evidence":
                    self.assertEqual((self.repo_dir / "ev_tree/safe.txt").read_text(), "admitted bytes")
                    self.assertIn("evidence/ev_tree/safe.txt", artifacts)
                    (self.repo_dir / "ev_tree/sym_dir").unlink()
                    (self.repo_dir / "ev_tree/safe.txt").unlink()
                    (self.repo_dir / "ev_tree").rmdir()
                else:
                    (self.repo_dir / ".agystack/diagnostics").unlink()

    @patch("storage_uploader.upload_to_gcs", return_value=True)
    @patch("storage_uploader._generate_git_patch", return_value="replacement patch")
    def test_patch_symlink_rejected_before_regeneration(self, mock_generate, mock_upload):
        target = self.repo_dir / "untouched.txt"
        target.write_bytes(b"original bytes")
        for status, name in [("PASS", "patch.diff"), ("ISSUES", "partial.patch.diff")]:
            with self.subTest(status=status):
                sym_path = self.repo_dir / name
                sym_path.symlink_to(target)
                artifacts = storage_uploader.upload_run_artifacts(
                    "bucket",
                    "run",
                    self.repo_dir,
                    0,
                    status,
                    ["app.py"],
                )
                self.assertEqual(target.read_bytes(), b"original bytes")
                self.assertNotIn(name, artifacts)
                self.assertEqual(json.loads((self.repo_dir / "status.json").read_text())["status"], "ISSUES")
                sym_path.unlink()
        mock_generate.assert_not_called()

    @patch("storage_uploader.upload_to_gcs")
    def test_failed_score_or_results_upload_degrades_pass_to_issues(self, mock_upload):
        score_file = self.repo_dir / "score.json"
        score_file.write_text(json.dumps({"score": 0.95}), encoding="utf-8")

        tsv_file = self.repo_dir / "results.tsv"
        tsv_file.write_text("metric\tvalue\nscore\t0.95\n", encoding="utf-8")

        # 1. Test score.json upload failure
        def fail_score_upload(bkt, dest, path):
            if "score.json" in str(dest):
                return False
            return True

        mock_upload.side_effect = fail_score_upload

        results = storage_uploader.upload_run_artifacts(
            bucket_name="test-bucket",
            prefix="runs/exp1",
            repo_dir=self.repo_dir,
            task_index=0,
            status="PASS",
        )

        self.assertNotIn("score.json", results)
        status_file = self.repo_dir / "status.json"
        status_data = json.loads(status_file.read_text(encoding="utf-8"))
        self.assertEqual(status_data["status"], "ISSUES")
        self.assertIn("score.json upload failed", status_data.get("evidence", ""))

        # 2. Test results.tsv upload failure
        def fail_results_upload(bkt, dest, path):
            if "results.tsv" in str(dest):
                return False
            return True

        mock_upload.side_effect = fail_results_upload

        results = storage_uploader.upload_run_artifacts(
            bucket_name="test-bucket",
            prefix="runs/exp1",
            repo_dir=self.repo_dir,
            task_index=0,
            status="PASS",
        )

        self.assertNotIn("results.tsv", results)
        status_data = json.loads(status_file.read_text(encoding="utf-8"))
        self.assertEqual(status_data["status"], "ISSUES")
        self.assertIn("results.tsv upload failed", status_data.get("evidence", ""))


if __name__ == "__main__":
    unittest.main()
