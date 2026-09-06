import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"))
from cloud_worker import (
    clean_repo_url,
    clone_and_checkout_task,
    download_manifest,
    emit_milestone,
    execute_task,
    is_candidate_file,
    parse_task_manifest,
)
from cloud_dispatch import (
    build_gcloud_command,
    monitor_execution,
    parse_milestone_log,
    parse_worker_logs,
    resolve_swarm_model,
    run_preflight,
    stage_manifest,
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
        exact_files = [".git", ".agystack", ".agents"]
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
        self.assertIn("--parallelism=10", cmd_async)
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
        self.assertIn("--parallelism=10", cmd_sync)
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


class TestSecureSwarmAndManifestStaging(unittest.TestCase):
    def setUp(self):
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_obj.name)

    def tearDown(self):
        self.temp_dir_obj.cleanup()

    def test_manifest_staging_avoids_large_task_manifest_env(self):
        # 1. Test stage_manifest uploads to gs://<bucket>/swarms/<session_id>/manifest.json
        large_tasks = [{"task_id": i, "brief": f"Task number {i} with substantial description " * 20} for i in range(50)]
        manifest_serialized = json.dumps(large_tasks)
        self.assertGreater(len(manifest_serialized), 32 * 1024)

        with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(self.temp_dir)}):
            staged_uri = stage_manifest(
                manifest_data=large_tasks,
                bucket_name="my-manifest-bucket",
                session_id="session-test-42",
            )
            self.assertEqual(staged_uri, "gs://my-manifest-bucket/swarms/session-test-42/manifest.json")
            staged_file = self.temp_dir / "my-manifest-bucket" / "swarms" / "session-test-42" / "manifest.json"
            self.assertTrue(staged_file.is_file())
            loaded = json.loads(staged_file.read_text(encoding="utf-8"))
            self.assertEqual(len(loaded), 50)
            self.assertEqual(loaded[0]["task_id"], 0)

        # 2. Test CLI dispatcher sets MANIFEST_URI and omits TASK_MANIFEST when bucket is provided
        manifest_path = self.temp_dir / "manifest.json"
        manifest_path.write_text(manifest_serialized, encoding="utf-8")

        dispatch_script = Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts" / "cloud_dispatch.py"
        cmd = [
            sys.executable,
            str(dispatch_script),
            "--dry-run",
            "--manifest", str(manifest_path),
            "--gcs-bucket", "my-manifest-bucket",
            "--session-id", "session-test-42",
            "--repo", "https://github.com/test/repo.git",
            "--vertex",
            "--project", "test-project",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=dict(os.environ, GH_TOKEN="test_tok"))
        payload = json.loads(res.stdout)
        env_vars = payload["env_vars"]

        self.assertIn("MANIFEST_URI", env_vars)
        self.assertEqual(env_vars["MANIFEST_URI"], "gs://my-manifest-bucket/swarms/session-test-42/manifest.json")
        self.assertNotIn("TASK_MANIFEST", env_vars)

        # 3. Test that when no GCS bucket is provided, it falls back to TASK_MANIFEST
        cmd_no_bkt = [
            sys.executable,
            str(dispatch_script),
            "--dry-run",
            "--manifest", str(manifest_path),
            "--gcs-bucket", "",
            "--repo", "https://github.com/test/repo.git",
            "--vertex",
            "--project", "test-project",
        ]
        res_no_bkt = subprocess.run(cmd_no_bkt, capture_output=True, text=True, check=True, env=dict(os.environ, GH_TOKEN="test_tok"))
        payload_no_bkt = json.loads(res_no_bkt.stdout)
        env_vars_no_bkt = payload_no_bkt["env_vars"]

        self.assertIn("TASK_MANIFEST", env_vars_no_bkt)
        self.assertNotIn("MANIFEST_URI", env_vars_no_bkt)

    def test_worker_loads_tasks_from_manifest_uri(self):
        tasks = [
            {"brief": "Implement secure storage staging", "candidate_files": ["dispatch.py"]},
            {"command": "pytest -q tests/test_secure.py"},
        ]
        bkt = "test-worker-bucket"
        sess = "swarm-worker-1"
        target_file = self.temp_dir / bkt / "swarms" / sess / "manifest.json"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(json.dumps(tasks), encoding="utf-8")

        manifest_uri = f"gs://{bkt}/swarms/{sess}/manifest.json"

        with patch.dict(os.environ, {
            "STORAGE_MESSENGER_LOCAL_DIR": str(self.temp_dir),
            "MANIFEST_URI": manifest_uri,
        }, clear=False):
            os.environ.pop("TASK_MANIFEST", None)
            os.environ.pop("TASK_BRIEF", None)

            # Worker loads task index 0
            item0, brief0 = parse_task_manifest(task_index=0)
            self.assertEqual(brief0, "Implement secure storage staging")
            self.assertEqual(item0["candidate_files"], ["dispatch.py"])

            # Worker loads task index 1
            item1, brief1 = parse_task_manifest(task_index=1)
            self.assertEqual(brief1, "pytest -q tests/test_secure.py")

            # Out of bounds index
            with self.assertRaises(IndexError):
                parse_task_manifest(task_index=2)

        # Test download_manifest directly
        with patch.dict(os.environ, {"STORAGE_MESSENGER_LOCAL_DIR": str(self.temp_dir)}):
            content = download_manifest(manifest_uri)
            self.assertEqual(json.loads(content), tasks)

    def test_git_clone_scrubs_tokens_from_remote_origin_url(self):
        # 1. Test clean_repo_url helper directly
        token_url = "https://x-access-token:ghp_999SECRETTOKEN999@github.com/my-org/my-repo.git"
        cleaned = clean_repo_url(token_url)
        self.assertEqual(cleaned, "https://github.com/my-org/my-repo.git")
        self.assertNotIn("ghp_999SECRETTOKEN999", cleaned)
        self.assertNotIn("x-access-token", cleaned)

        # 2. Test clone_and_checkout_task on an actual git repo
        source_repo_dir = self.temp_dir / "source-repo"
        source_repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=source_repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=source_repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "user@test.org"], cwd=source_repo_dir, check=True)
        (source_repo_dir / "README.md").write_text("# Test Repo", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=source_repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=source_repo_dir, check=True)

        worker_dest = self.temp_dir / "cloned-worker-repo"
        fake_token = "ghp_VERYSECRETTOKEN123456789"
        clone_and_checkout_task(
            repo_url=str(source_repo_dir),
            gh_token=fake_token,
            branch_name="worker-7",
            repo_dir=worker_dest,
        )

        # Inspect .git/config in cloned repo
        git_config_path = worker_dest / ".git" / "config"
        self.assertTrue(git_config_path.is_file())
        config_text = git_config_path.read_text(encoding="utf-8")
        self.assertNotIn(fake_token, config_text)
        self.assertNotIn("x-access-token", config_text)

        # Verify remote.origin.url matches clean URL
        res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=worker_dest,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(res.stdout.strip(), str(source_repo_dir))

        # Verify checkout branch
        branch_res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=worker_dest,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(branch_res.stdout.strip(), "worker-7")

    def test_build_gcloud_command_supports_set_secrets_and_vertex_mode(self):
        # 1. Supports --set-secrets with dict mapping
        cmd = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=5,
            parallelism=5,
            region="us-central1",
            project="test-proj",
            env_vars={"REPO_URL": "https://github.com/test/repo.git"},
            secrets_mapping={
                "GEMINI_API_KEY": "gemini-key:latest",
                "SLACK_WEBHOOK": "slack-secret:1",
            },
        )
        self.assertTrue(any(arg.startswith("--set-secrets=") for arg in cmd))
        set_secrets_arg = next(arg for arg in cmd if arg.startswith("--set-secrets="))
        self.assertIn("GEMINI_API_KEY=gemini-key:latest", set_secrets_arg)
        self.assertIn("SLACK_WEBHOOK=slack-secret:1", set_secrets_arg)

        # 2. Supports --set-secrets with string argument
        cmd_str = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=1,
            parallelism=1,
            region="us-central1",
            project="test-proj",
            env_vars={},
            set_secrets="GEMINI_API_KEY=my-secret:latest",
        )
        self.assertIn("--set-secrets=GEMINI_API_KEY=my-secret:latest", cmd_str)

        # 3. Omits GEMINI_API_KEY in Vertex AI mode via auth_mode="vertex"
        cmd_vertex = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=1,
            parallelism=1,
            region="us-central1",
            project="test-proj",
            env_vars={
                "GEMINI_API_KEY": "AIzaSySuperSecretKey",
                "REPO_URL": "https://github.com/test/repo.git",
            },
            auth_mode="vertex",
        )
        cmd_vertex_str = " ".join(cmd_vertex)
        self.assertNotIn("AIzaSySuperSecretKey", cmd_vertex_str)
        self.assertNotIn("GEMINI_API_KEY", cmd_vertex_str)

        # 4. Omits GEMINI_API_KEY when USE_VERTEX_AI is in env_vars
        cmd_vertex_env = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=1,
            parallelism=1,
            region="us-central1",
            project="test-proj",
            env_vars={
                "GEMINI_API_KEY": "AIzaSySuperSecretKey",
                "USE_VERTEX_AI": "1",
            },
        )
        self.assertNotIn("AIzaSySuperSecretKey", " ".join(cmd_vertex_env))

        # 5. Preserves GEMINI_API_KEY in non-Vertex mode
        cmd_studio = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=1,
            parallelism=1,
            region="us-central1",
            project="test-proj",
            env_vars={
                "GEMINI_API_KEY": "AIzaSySuperSecretKey",
                "REPO_URL": "https://github.com/test/repo.git",
            },
            auth_mode="api_key",
        )
        self.assertIn("GEMINI_API_KEY=AIzaSySuperSecretKey", " ".join(cmd_studio))


if __name__ == "__main__":
    unittest.main()
