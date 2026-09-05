import io
import json
import os
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"))
from cloud_worker import (
    emit_milestone,
    execute_task,
    is_candidate_file,
)
from cloud_dispatch import (
    build_gcloud_command,
    monitor_execution,
    parse_milestone_log,
    parse_worker_logs,
    resolve_swarm_model,
    run_preflight,
)


class TestCloudWorkerGuardrails(unittest.TestCase):
    def test_candidate_file_filter_languages(self):
        # Legitimate candidate source files across Python, TS/JS, Go, and Rust
        self.assertTrue(is_candidate_file("src/main.py"))
        self.assertTrue(is_candidate_file("backend/app/service.py"))
        self.assertTrue(is_candidate_file("src/index.ts"))
        self.assertTrue(is_candidate_file("ui/components/App.tsx"))
        self.assertTrue(is_candidate_file("cmd/server/main.go"))
        self.assertTrue(is_candidate_file("pkg/api/handler.go"))
        self.assertTrue(is_candidate_file("src/ordering/mod.rs"))
        self.assertTrue(is_candidate_file("candidate-worker/src/lib.rs"))
        self.assertTrue(is_candidate_file("src/nested_dissection.rs"))

    def test_candidate_file_filter_default_excludes(self):
        # Default ignored directories
        ignored_dir_files = [
            ".git/config",
            ".agents/skills/tool.py",
            ".agystack/runtime.json",
            "node_modules/react/index.js",
            "target/debug/app",
            "vendor/cache/pkg.gem",
            ".cargo/config.toml",
            "dist/index.js",
            "build/lib.so",
            ".venv/bin/activate",
            "__pycache__/app.cpython-311.pyc",
        ]
        for f in ignored_dir_files:
            self.assertFalse(is_candidate_file(f), f"Expected {f} to be excluded by default dir rules.")

        # Default exact excluded files
        exact_files = ["rust-toolchain", "rust-toolchain.toml", "Cargo.lock"]
        for f in exact_files:
            self.assertFalse(is_candidate_file(f), f"Expected exact file {f} to be excluded.")

    def test_candidate_file_filter_custom_includes_and_excludes(self):
        # Custom candidate list
        explicit_candidates = ["src/model/", "scripts/eval.py"]
        self.assertTrue(is_candidate_file("src/model/transformer.py", explicit_candidates=explicit_candidates))
        self.assertTrue(is_candidate_file("scripts/eval.py", explicit_candidates=explicit_candidates))
        self.assertFalse(is_candidate_file("src/other/worker.py", explicit_candidates=explicit_candidates))
        self.assertFalse(is_candidate_file("main.py", explicit_candidates=explicit_candidates))

        # Custom excludes list
        explicit_excludes = ["src/generated/", "proto/"]
        self.assertFalse(is_candidate_file("src/generated/types.ts", explicit_excludes=explicit_excludes))
        self.assertFalse(is_candidate_file("proto/service.pb.go", explicit_excludes=explicit_excludes))
        self.assertTrue(is_candidate_file("src/valid.ts", explicit_excludes=explicit_excludes))

    def test_parse_worker_logs(self):
        log_sample = """
================================================================================
[STATUS: PASS]
Evidence:
- Task Index: 0
- Branch: worker-0
- Commit SHA: abc1234
Summary:
Optimized Subtree Round 5 gating successfully.
================================================================================
"""
        parsed = parse_worker_logs(log_sample)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["status"], "PASS")
        self.assertIn("Optimized Subtree Round 5", parsed[0]["summary"])

    def test_emit_milestone_formatting(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            emit_milestone(0, "BOOTING")
            self.assertEqual(mock_out.getvalue(), "[MILESTONE] [TASK 0] [PHASE: BOOTING]\n")

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            emit_milestone(3, "RUNNING_AGENT", "Antigravity SDK agent turn 1")
            self.assertEqual(
                mock_out.getvalue(),
                "[MILESTONE] [TASK 3] [PHASE: RUNNING_AGENT] Antigravity SDK agent turn 1\n",
            )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            emit_milestone(1, "COMPLETE", "PASS")
            self.assertEqual(mock_out.getvalue(), "[MILESTONE] [TASK 1] [PHASE: COMPLETE] PASS\n")

    def test_parse_milestone_log(self):
        res = parse_milestone_log("[MILESTONE] [TASK 0] [PHASE: BOOTING]")
        self.assertIsNotNone(res)
        self.assertEqual(res["task_index"], "0")
        self.assertEqual(res["phase"], "BOOTING")
        self.assertEqual(res["detail"], "")

        res = parse_milestone_log("[MILESTONE] [TASK 2] [PHASE: COMPLETE] PASS")
        self.assertIsNotNone(res)
        self.assertEqual(res["task_index"], "2")
        self.assertEqual(res["phase"], "COMPLETE")
        self.assertEqual(res["detail"], "PASS")

        res = parse_milestone_log(
            "2026-09-04T22:30:00.123Z [MILESTONE]  [TASK 5]  [PHASE: RUNNING_AGENT]  evaluating slice 0..10"
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["task_index"], "5")
        self.assertEqual(res["phase"], "RUNNING_AGENT")
        self.assertEqual(res["detail"], "evaluating slice 0..10")

        self.assertIsNone(parse_milestone_log("Building candidate worker..."))
        self.assertIsNone(parse_milestone_log("[STATUS: PASS]"))

    def test_build_gcloud_command_sync_and_async(self):
        cmd_async = build_gcloud_command(
            job_name="test-swarm-job",
            tasks_count=4,
            parallelism=10,
            region="us-central1",
            project="test-project",
            env_vars={"KEY1": "VAL1"},
            wait=False,
            max_retries=0,
        )
        self.assertIn("--async", cmd_async)
        self.assertNotIn("--wait", cmd_async)
        self.assertIn("--tasks=4", cmd_async)
        self.assertIn("--max-retries=0", cmd_async)

        cmd_sync = build_gcloud_command(
            job_name="test-swarm-job",
            tasks_count=4,
            parallelism=10,
            region="us-central1",
            project="test-project",
            env_vars={"KEY1": "VAL1"},
            wait=True,
            max_retries=2,
        )
        self.assertIn("--wait", cmd_sync)
        self.assertNotIn("--async", cmd_sync)
        self.assertIn("--max-retries=2", cmd_sync)

    @patch("subprocess.run")
    def test_monitor_execution_under_threshold(self, mock_subproc):
        describe_output = json.dumps({
            "metadata": {"name": "test-exec-123"},
            "status": {
                "conditions": [{"type": "Completed", "status": "True"}],
                "succeededCount": 2,
            },
        })
        logging_output = "[MILESTONE] [TASK 0] [PHASE: BOOTING]\n[MILESTONE] [TASK 0] [PHASE: COMPLETE] PASS\n"

        def fake_run(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "describe" in cmd:
                m.stdout = describe_output
            elif "logging" in cmd:
                m.stdout = logging_output
            else:
                m.stdout = ""
            return m

        mock_subproc.side_effect = fake_run

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            desc = monitor_execution(
                execution_name="test-exec-123",
                project="test-proj",
                region="us-central1",
                task_count=2,
                poll_interval=0.01,
            )
            out = mock_out.getvalue()
            self.assertIn("[MILESTONE] [TASK 0] [PHASE: BOOTING]", out)
            self.assertIn("[MILESTONE] [TASK 0] [PHASE: COMPLETE] PASS", out)
            self.assertIsNotNone(desc)

    @patch("subprocess.run")
    def test_monitor_execution_over_threshold(self, mock_subproc):
        describe_output = json.dumps({
            "metadata": {"name": "test-exec-456"},
            "status": {
                "conditions": [{"type": "Completed", "status": "True"}],
                "succeededCount": 5,
                "runningCount": 0,
                "failedCount": 0,
            },
        })

        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = describe_output
        mock_subproc.return_value = mock_res

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            desc = monitor_execution(
                execution_name="test-exec-456",
                project="test-proj",
                region="us-central1",
                task_count=5,
                poll_interval=0.01,
            )
            out = mock_out.getvalue()
            self.assertIn("[Cloud Swarm] Progress: 5/5 succeeded, 0 running, 0 failed.", out)
            self.assertIsNotNone(desc)


class TestTaskExecutionAndValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_command_runner_success(self):
        task_item = {"type": "command", "command": "echo 'command test output'"}
        status, output = execute_task(
            task_item=task_item,
            task_brief="",
            repo_dir=self.repo_dir,
            model_override="",
            api_key="",
        )
        self.assertEqual(status, "PASS")
        self.assertIn("command test output", output)

    def test_command_runner_failure(self):
        task_item = {"type": "command", "command": "echo 'failing command' >&2; exit 1"}
        status, output = execute_task(
            task_item=task_item,
            task_brief="",
            repo_dir=self.repo_dir,
            model_override="",
            api_key="",
        )
        self.assertEqual(status, "ISSUES")
        self.assertIn("failing command", output)


class TestPreflightGlobalAndRegionalURL(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_preflight_vertex_global_url_and_headers(self, mock_subproc, mock_urlopen):
        def fake_run(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "print-access-token" in cmd:
                m.stdout = "token-xyz\n"
            else:
                m.stdout = "HEAD\n"
            return m
        mock_subproc.side_effect = fake_run

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        run_preflight(
            repo_url="https://github.com/test/repo.git",
            gh_token="gh-token",
            use_vertex=True,
            gemini_api_key="",
            project="my-gcp-project",
            region="us-central1",
            model="gemini-3.8-flash",
            dry_run=False,
        )

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(
            req.full_url,
            "https://aiplatform.googleapis.com/v1/projects/my-gcp-project/locations/global/publishers/google/models/gemini-3.8-flash:generateContent",
        )
        self.assertEqual(req.get_header("X-goog-user-project"), "my-gcp-project")
        self.assertEqual(req.get_header("Authorization"), "Bearer token-xyz")

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_preflight_vertex_regional_url_and_headers(self, mock_subproc, mock_urlopen):
        def fake_run(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "print-access-token" in cmd:
                m.stdout = "token-xyz\n"
            else:
                m.stdout = "HEAD\n"
            return m
        mock_subproc.side_effect = fake_run

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        run_preflight(
            repo_url="https://github.com/test/repo.git",
            gh_token="gh-token",
            use_vertex=True,
            gemini_api_key="",
            project="my-gcp-project",
            region="europe-west4",
            model="gemini-1.5-flash",
            dry_run=False,
        )

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(
            req.full_url,
            "https://europe-west4-aiplatform.googleapis.com/v1/projects/my-gcp-project/locations/europe-west4/publishers/google/models/gemini-1.5-flash:generateContent",
        )
        self.assertEqual(req.get_header("X-goog-user-project"), "my-gcp-project")

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_preflight_free_tier_indicator_rejection(self, mock_subproc, mock_urlopen):
        mock_subproc.return_value = MagicMock(returncode=0, stdout="HEAD\n")

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"error": "rate limit <= 5 rpm"}'
        mock_resp.headers = {"x-rate-limit": "5rpm"}
        mock_urlopen.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            run_preflight(
                repo_url="https://github.com/test/repo.git",
                gh_token="gh-token",
                use_vertex=False,
                gemini_api_key="AIzaTestKey",
                project="",
                region="us-central1",
                model="gemini-3.8-flash",
                dry_run=False,
            )
        self.assertIn("Free-tier Gemini API key detected", str(ctx.exception))

    def test_resolve_swarm_model_cli_override(self):
        # Direct CLI override takes highest precedence
        self.assertEqual(resolve_swarm_model(cli_model="gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(resolve_swarm_model(cli_model="gemini-3.7-flash"), "gemini-3.7-flash")

    def test_resolve_swarm_model_tier_mappings(self):
        # Tiers map to concrete Cloud Run / Vertex AI models
        self.assertEqual(resolve_swarm_model(cli_model="pro"), "gemini-3.1-pro")
        self.assertEqual(resolve_swarm_model(cli_model="flash"), "gemini-3.8-flash")
        self.assertEqual(resolve_swarm_model(cli_model="flash_lite"), "gemini-3.1-flash-lite")
        self.assertEqual(resolve_swarm_model(cli_model="inherit"), "gemini-3.8-flash")

    def test_resolve_swarm_model_runtime_config_and_agystack_models(self):
        # Explicit model in runtime config
        self.assertEqual(resolve_swarm_model(runtime_model="gemini-2.5-pro"), "gemini-2.5-pro")

        # When runtime config is 'inherit', it resolves to role or default
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write("# Model config\nswarm workers: pro\n")
            f_path = Path(f.name)
        try:
            resolved = resolve_swarm_model(runtime_model="inherit", agystack_models_path=f_path)
            self.assertEqual(resolved, "gemini-3.1-pro")
        finally:
            f_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
