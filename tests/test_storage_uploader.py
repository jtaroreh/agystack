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

    def test_fork_repo_override_logic(self):
        with patch.dict(os.environ, {"FORK_REPO_URL": "https://github.com/myfork/matrices-fast.git"}):
            fork_url = os.environ.get("FORK_REPO_URL", "").strip()
            self.assertEqual(fork_url, "https://github.com/myfork/matrices-fast.git")


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
        self.assertEqual((self.repo_dir / "patch.diff").read_text(encoding="utf-8"), "diff --git a/test b/test\n+new line")


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


TestStructuredOutputParsing = TestScoreParsing


if __name__ == "__main__":
    unittest.main()
