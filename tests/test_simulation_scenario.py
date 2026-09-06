#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cloud_dispatch import run_preflight
from cloud_worker import is_candidate_file
from simulate_cloud_swarm import (
    build_simulation_manifest,
    probe_vertex_ai,
    run_simulation,
    setup_simulation_repo,
)


class TestCloudDispatchGemini25Preflight(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_gemini_25_flash_routes_to_vertex_global(self, mock_subproc, mock_urlopen):
        def fake_run(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "print-access-token" in cmd:
                m.stdout = "token-test-25\n"
            else:
                m.stdout = "HEAD\n"
            return m

        mock_subproc.side_effect = fake_run
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        run_preflight(
            repo_url="https://github.com/test/repo.git",
            gh_token="test-token",
            use_vertex=True,
            gemini_api_key="",
            project="test-proj-25",
            region="us-central1",
            model="gemini-2.5-flash",
            dry_run=False,
        )

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(
            req.full_url,
            "https://aiplatform.googleapis.com/v1/projects/test-proj-25/locations/global/publishers/google/models/gemini-2.5-flash:generateContent",
        )
        self.assertEqual(req.get_header("X-goog-user-project"), "test-proj-25")

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_gemini_25_pro_routes_to_vertex_global(self, mock_subproc, mock_urlopen):
        def fake_run(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "print-access-token" in cmd:
                m.stdout = "token-test-pro\n"
            else:
                m.stdout = "HEAD\n"
            return m

        mock_subproc.side_effect = fake_run
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        run_preflight(
            repo_url="https://github.com/test/repo.git",
            gh_token="test-token",
            use_vertex=True,
            gemini_api_key="",
            project="test-proj-pro",
            region="europe-west4",
            model="gemini-2.5-pro",
            dry_run=False,
        )

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(
            req.full_url,
            "https://aiplatform.googleapis.com/v1/projects/test-proj-pro/locations/global/publishers/google/models/gemini-2.5-pro:generateContent",
        )

    def test_cli_argument_handler_vertex_location_resolution(self):
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "cloud_dispatch.py"),
            "--dry-run",
            "--repo", "https://github.com/test/repo.git",
            "--model", "gemini-2.5-flash",
            "--vertex",
            "--project", "test-project",
            "--tasks", "1",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=dict(os.environ, GH_TOKEN="test_token"))
        payload = json.loads(res.stdout)
        self.assertEqual(payload["env_vars"].get("VERTEXAI_LOCATION"), "global")


class TestSimulationScenarioWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir_obj.name)

    def tearDown(self):
        self.temp_dir_obj.cleanup()

    def test_setup_simulation_repo(self):
        origin_dir, work_dir = setup_simulation_repo(self.base_dir)
        self.assertTrue(origin_dir.is_dir())
        self.assertTrue((work_dir / "src" / "pipeline" / "packet_filter.py").is_file())
        self.assertTrue((work_dir / "src" / "pipeline" / "transform.py").is_file())
        self.assertTrue((work_dir / "src" / "pipeline" / "router.py").is_file())
        self.assertTrue((work_dir / "tests" / "test_packet_filter.py").is_file())
        self.assertTrue((work_dir / "tests" / "test_transform.py").is_file())
        self.assertTrue((work_dir / "tests" / "test_router.py").is_file())

        run_env = dict(os.environ, PYTHONPATH=str(work_dir))
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "tests"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            env=run_env,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Ran 3 tests", res.stderr)

    def test_manifest_generation_and_guardrails(self):
        manifest = build_simulation_manifest(tasks_count=3)
        self.assertEqual(len(manifest), 3)

        self.assertEqual(manifest[0]["candidate_files"], ["src/pipeline/packet_filter.py"])
        self.assertEqual(manifest[1]["candidate_files"], ["src/pipeline/transform.py"])
        self.assertEqual(manifest[2]["candidate_files"], ["src/pipeline/router.py"])

        for task in manifest:
            cand = task["candidate_files"][0]
            self.assertTrue(is_candidate_file(cand, explicit_candidates=task["candidate_files"], explicit_excludes=task["exclude_files"]))
            self.assertFalse(is_candidate_file(".agystack/setup.sh", explicit_candidates=task["candidate_files"], explicit_excludes=task["exclude_files"]))
            self.assertFalse(is_candidate_file(".git/HEAD", explicit_candidates=task["candidate_files"], explicit_excludes=task["exclude_files"]))

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_probe_vertex_ai_success(self, mock_subproc, mock_urlopen):
        mock_subproc.return_value = MagicMock(returncode=0, stdout="test-access-token\n")
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        probe_ok = probe_vertex_ai(project="test-proj", model="gemini-2.5-flash", location="global")
        self.assertTrue(probe_ok)
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(
            req.full_url,
            "https://aiplatform.googleapis.com/v1/projects/test-proj/locations/global/publishers/google/models/gemini-2.5-flash:generateContent",
        )

    def test_end_to_end_simulation_run(self):
        result = run_simulation(
            model="gemini-2.5-flash",
            project="test-agystack-project",
            gcs_bucket="test-swarm-results",
            tasks=3,
            skip_live_probe=True,
            temp_base_dir=self.base_dir,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["tasks"], 3)
        self.assertEqual(len(result["harvested_scores"]), 3)

        out_slices = Path(".slices/harvested_scores.json")
        self.assertTrue(out_slices.is_file())
        with open(out_slices, "r", encoding="utf-8") as f:
            slices_data = json.load(f)
        self.assertEqual(len(slices_data), 3)

        phases = [m["phase"] for m in result["milestones"]]
        expected_phases = [
            "BOOTING",
            "REPO_READY",
            "RUNNING_AGENT",
            "STEER_RECEIVED",
            "WAITING_FOR_ORCHESTRATOR",
            "ORCHESTRATOR_REPLY_RECEIVED",
            "VALIDATING_CANDIDATE",
            "COMPLETE",
        ]
        for ep in expected_phases:
            self.assertIn(ep, phases, f"Missing expected milestone phase: {ep}")

    def test_cli_execution_clean_exit(self):
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "simulate_cloud_swarm.py"),
            "--skip-live-probe",
            "--tasks", "3",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"CLI exited with {proc.returncode}:\n{proc.stderr}")
        self.assertIn("SWARM SIMULATION REPORT", proc.stdout)
        self.assertIn("[STATUS: PASS]", proc.stdout)


if __name__ == "__main__":
    unittest.main()
