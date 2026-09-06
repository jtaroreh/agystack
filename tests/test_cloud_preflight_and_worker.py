import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "setup-agystack" / "scripts"))
import setup_runtime
import cloud_worker
from cloud_worker import (
    clean_repo_url,
    clone_and_checkout_task,
    download_manifest,
    emit_milestone,
    execute_task,
    is_candidate_file,
    parse_task_manifest,
    resolve_worker_branch,
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
        self.assertNotIn("--parallelism", " ".join(cmd_async))
        self.assertNotIn("--max-retries", " ".join(cmd_async))

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
        self.assertNotIn("--parallelism", " ".join(cmd_sync))
        self.assertNotIn("--max-retries", " ".join(cmd_sync))

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

    def test_agent_mode_passes_poteto_system_prompt_to_config(self):
        mock_ag = MagicMock()
        mock_config = MagicMock()
        mock_ag.LocalAgentConfig = mock_config
        mock_ag.CapabilitiesConfig = MagicMock()
        mock_ag.policy.allow_all = MagicMock()

        mock_agent_instance = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = AsyncMock(return_value="[STATUS: PASS] completed successfully")
        mock_agent_instance.chat = AsyncMock(return_value=mock_resp)

        mock_agent_cm = MagicMock()
        mock_agent_cm.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_cm.__aexit__ = AsyncMock(return_value=None)
        mock_ag.Agent = MagicMock(return_value=mock_agent_cm)

        modules_patch = {
            "google": MagicMock(),
            "google.antigravity": mock_ag,
        }
        with patch.dict(sys.modules, modules_patch):
            status, output = execute_task(
                task_item={"type": "agent"},
                task_brief="Implement PR-5",
                repo_dir=self.repo_dir,
                model_override="gemini-3.8-flash",
                api_key="test-key",
            )
            self.assertEqual(status, "PASS")
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            self.assertIn("system_prompt", call_kwargs)
            self.assertIn("poteto", call_kwargs["system_prompt"].lower())
            self.assertIn("surgical", call_kwargs["system_prompt"].lower())
            self.assertIn("unslopped", call_kwargs["system_prompt"].lower())

    def test_agent_mode_env_var_overrides_poteto_system_prompt(self):
        mock_ag = MagicMock()
        mock_config = MagicMock()
        mock_ag.LocalAgentConfig = mock_config
        mock_ag.CapabilitiesConfig = MagicMock()
        mock_ag.policy.allow_all = MagicMock()

        mock_agent_instance = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = AsyncMock(return_value="[STATUS: PASS] done")
        mock_agent_instance.chat = AsyncMock(return_value=mock_resp)

        mock_agent_cm = MagicMock()
        mock_agent_cm.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_cm.__aexit__ = AsyncMock(return_value=None)
        mock_ag.Agent = MagicMock(return_value=mock_agent_cm)

        modules_patch = {
            "google": MagicMock(),
            "google.antigravity": mock_ag,
        }
        custom_prompt = "Custom system prompt for worker override"
        with patch.dict(sys.modules, modules_patch), patch.dict(os.environ, {"AGYSTACK_WORKER_SYSTEM_PROMPT": custom_prompt}):
            status, output = execute_task(
                task_item={"type": "agent"},
                task_brief="Custom prompt task",
                repo_dir=self.repo_dir,
                model_override="gemini-3.8-flash",
                api_key="test-key",
            )
            self.assertEqual(status, "PASS")
            call_kwargs = mock_config.call_args[1]
            self.assertEqual(call_kwargs.get("system_prompt"), custom_prompt)

    def test_agent_mode_typeerror_fallback_pops_optional_keys(self):
        mock_ag = MagicMock()
        mock_ag.CapabilitiesConfig = MagicMock()
        mock_ag.policy.allow_all = MagicMock()

        def fake_local_agent_config(**kwargs):
            if "system_prompt" in kwargs or "custom_tools" in kwargs:
                raise TypeError("unsupported parameter")
            return MagicMock()

        mock_ag.LocalAgentConfig = MagicMock(side_effect=fake_local_agent_config)

        mock_agent_instance = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = AsyncMock(return_value="[STATUS: PASS] fallback success")
        mock_agent_instance.chat = AsyncMock(return_value=mock_resp)

        mock_agent_cm = MagicMock()
        mock_agent_cm.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_cm.__aexit__ = AsyncMock(return_value=None)
        mock_ag.Agent = MagicMock(return_value=mock_agent_cm)

        modules_patch = {
            "google": MagicMock(),
            "google.antigravity": mock_ag,
        }
        with patch.dict(sys.modules, modules_patch):
            status, output = execute_task(
                task_item={"type": "agent"},
                task_brief="Implement PR-5 with fallback",
                repo_dir=self.repo_dir,
                model_override="gemini-3.8-flash",
                api_key="test-key",
            )
            self.assertEqual(status, "PASS")
            self.assertEqual(mock_ag.LocalAgentConfig.call_count, 2)
            fallback_kwargs = mock_ag.LocalAgentConfig.call_args[1]
            self.assertNotIn("system_prompt", fallback_kwargs)
            self.assertNotIn("custom_tools", fallback_kwargs)


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
            gcs_bucket="test-bucket",
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
            gcs_bucket="test-bucket",
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
                gcs_bucket="test-bucket",
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
        with patch("cloud_worker.subprocess.run", wraps=subprocess.run) as mock_subproc:
            clone_and_checkout_task(
                repo_url=str(source_repo_dir),
                gh_token=fake_token,
                branch_name="worker-7",
                repo_dir=worker_dest,
            )
            clone_calls = [call[0][0] for call in mock_subproc.call_args_list if "clone" in call[0][0]]
            self.assertTrue(len(clone_calls) > 0)
            for cmd in clone_calls:
                for arg in cmd:
                    self.assertNotIn(fake_token, arg)

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

    def test_zero_push_architecture_omits_git_push(self):
        self.assertFalse(hasattr(cloud_worker, "push_candidate_branch"))

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
        self.assertFalse(any(arg.startswith("--set-secrets=") for arg in cmd))
        self.assertFalse(any(arg.startswith("--parallelism=") for arg in cmd))
        self.assertFalse(any(arg.startswith("--max-retries=") for arg in cmd))

        # 2. Supports set_secrets argument without passing to execute
        cmd_str = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=1,
            parallelism=1,
            region="us-central1",
            project="test-proj",
            env_vars={},
            set_secrets="GEMINI_API_KEY=my-secret:latest",
        )
        self.assertNotIn("--set-secrets", " ".join(cmd_str))

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

    def test_build_gcloud_command_secrets_mapping_strips_env_vars(self):
        # Test that when secrets_mapping={"GH_TOKEN": "gh-token:latest", "GEMINI_API_KEY": "gemini-key:latest"} is passed,
        # GH_TOKEN and GEMINI_API_KEY are in --set-secrets and completely absent from --update-env-vars.
        cmd = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=2,
            parallelism=2,
            region="us-central1",
            project="test-proj",
            env_vars={
                "REPO_URL": "https://github.com/test/repo.git",
                "GH_TOKEN": "ghp_secret_token_123",
                "GEMINI_API_KEY": "AIzaSySecretGeminiKey456",
                "APP_ENV": "production",
            },
            secrets_mapping={
                "GH_TOKEN": "gh-token:latest",
                "GEMINI_API_KEY": "gemini-key:latest",
            },
        )
        self.assertFalse(any(arg.startswith("--set-secrets=") for arg in cmd))

        update_env_arg = next((arg for arg in cmd if arg.startswith("--update-env-vars=")), "")
        self.assertIn("APP_ENV=production", update_env_arg)
        self.assertIn("REPO_URL=https://github.com/test/repo.git", update_env_arg)
        self.assertNotIn("GH_TOKEN", update_env_arg)
        self.assertNotIn("ghp_secret_token_123", update_env_arg)
        self.assertNotIn("GEMINI_API_KEY", update_env_arg)
        self.assertNotIn("AIzaSySecretGeminiKey456", update_env_arg)

    def test_build_gcloud_command_set_secrets_string_strips_env_vars(self):
        # Test that when set_secrets="GH_TOKEN=gh-token:latest" is passed,
        # GH_TOKEN is in --set-secrets and absent from --update-env-vars.
        cmd = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=1,
            parallelism=1,
            region="us-central1",
            project="test-proj",
            env_vars={
                "REPO_URL": "https://github.com/test/repo.git",
                "GH_TOKEN": "ghp_secret_token_123",
                "OTHER_VAR": "val",
            },
            set_secrets="GH_TOKEN=gh-token:latest",
        )
        self.assertFalse(any(arg.startswith("--set-secrets=") for arg in cmd))

        update_env_arg = next((arg for arg in cmd if arg.startswith("--update-env-vars=")), "")
        self.assertIn("OTHER_VAR=val", update_env_arg)
        self.assertNotIn("GH_TOKEN", update_env_arg)
        self.assertNotIn("ghp_secret_token_123", update_env_arg)

    def test_build_gcloud_command_vertex_mode_completely_absent_from_update_env_vars(self):
        # Test that in Vertex AI mode, GEMINI_API_KEY is completely absent from --update-env-vars.
        cmd = build_gcloud_command(
            job_name="test-worker-job",
            tasks_count=1,
            parallelism=1,
            region="us-central1",
            project="test-proj",
            env_vars={
                "REPO_URL": "https://github.com/test/repo.git",
                "GEMINI_API_KEY": "AIzaSySuperSecretKey",
                "EXTRA_VAR": "extra",
            },
            auth_mode="vertex",
        )
        update_env_arg = next((arg for arg in cmd if arg.startswith("--update-env-vars=")), "")
        self.assertIn("EXTRA_VAR=extra", update_env_arg)
        self.assertNotIn("GEMINI_API_KEY", update_env_arg)
        self.assertNotIn("AIzaSySuperSecretKey", update_env_arg)

        # Also verify when USE_VERTEX_AI=1 in env_vars
        cmd_env = build_gcloud_command(
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
        update_env_env = next((arg for arg in cmd_env if arg.startswith("--update-env-vars=")), "")
        self.assertNotIn("GEMINI_API_KEY", update_env_env)
        self.assertNotIn("AIzaSySuperSecretKey", update_env_env)

    def test_cli_dispatch_omits_secrets_from_env_vars_when_using_set_secrets_or_runtime_config(self):
        dispatch_script = Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts" / "cloud_dispatch.py"
        manifest_path = self.temp_dir / "manifest_empty.json"
        manifest_path.write_text("[]", encoding="utf-8")

        # 1. CLI flag --set-secrets removes GH_TOKEN and GEMINI_API_KEY from env_vars and update-env-vars
        cmd = [
            sys.executable,
            str(dispatch_script),
            "--dry-run",
            "--manifest", str(manifest_path),
            "--repo", "https://github.com/test/repo.git",
            "--set-secrets", "GH_TOKEN=gh-token:latest,GEMINI_API_KEY=gemini-key:latest",
            "--project", "test-project",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env=dict(os.environ, GH_TOKEN="secret_gh_tok", GEMINI_API_KEY="secret_gem_key"),
        )
        payload = json.loads(res.stdout)
        env_vars = payload["env_vars"]
        self.assertNotIn("GH_TOKEN", env_vars)
        self.assertNotIn("GEMINI_API_KEY", env_vars)
        gcloud_cmd = payload["gcloud_command"]
        self.assertNotIn("--set-secrets=", gcloud_cmd)
        self.assertNotIn("--parallelism=", gcloud_cmd)
        self.assertNotIn("--max-retries=", gcloud_cmd)
        self.assertNotIn("secret_gh_tok", gcloud_cmd)
        self.assertNotIn("secret_gem_key", gcloud_cmd)
        for part in gcloud_cmd.split():
            if part.startswith("--update-env-vars="):
                self.assertNotIn("GH_TOKEN", part)
                self.assertNotIn("GEMINI_API_KEY", part)

        # 2. runtime_cfg default secrets in agystack-runtime.json
        cfg_file = self.temp_dir / "agystack-runtime.json"
        cfg_file.write_text(json.dumps({
            "secrets": {
                "GH_TOKEN": "gh-token:latest",
                "GEMINI_API_KEY": "gemini-key:latest",
            }
        }), encoding="utf-8")
        cmd_cfg = [
            sys.executable,
            str(dispatch_script),
            "--dry-run",
            "--manifest", str(manifest_path),
            "--repo", "https://github.com/test/repo.git",
            "--project", "test-project",
        ]
        res_cfg = subprocess.run(
            cmd_cfg,
            capture_output=True,
            text=True,
            check=True,
            cwd=str(self.temp_dir),
            env=dict(os.environ, GH_TOKEN="secret_gh_tok", GEMINI_API_KEY="secret_gem_key"),
        )
        payload_cfg = json.loads(res_cfg.stdout)
        self.assertNotIn("GH_TOKEN", payload_cfg["env_vars"])
        self.assertNotIn("GEMINI_API_KEY", payload_cfg["env_vars"])
        gcloud_cmd_cfg = payload_cfg["gcloud_command"]
        self.assertNotIn("--set-secrets=", gcloud_cmd_cfg)
        self.assertNotIn("--parallelism=", gcloud_cmd_cfg)
        self.assertNotIn("--max-retries=", gcloud_cmd_cfg)

    @patch("cloud_worker.run_command")
    def test_clone_and_checkout_task_passes_base_branch(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone_and_checkout_task(
            repo_url="https://github.com/test-org/test-repo.git",
            gh_token="test-token",
            branch_name="worker-1",
            repo_dir=Path("/tmp/fake-dir"),
            base_branch="feature/custom-base",
        )
        clone_calls = [call[0][0] for call in mock_run.call_args_list if len(call[0][0]) > 1 and "clone" in call[0][0]]
        self.assertTrue(len(clone_calls) > 0)
        clone_cmd = clone_calls[0]
        self.assertIn("--branch", clone_cmd)
        branch_idx = clone_cmd.index("--branch")
        self.assertEqual(clone_cmd[branch_idx + 1], "feature/custom-base")

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_run_preflight_with_base_branch_probe_and_missing_rejection(self, mock_subproc, mock_urlopen):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = ""
        mock_subproc.return_value = mock_res

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"candidates": []}'
        mock_resp.headers = {}
        mock_urlopen.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            run_preflight(
                repo_url="https://github.com/test/repo.git",
                gh_token="gh-token",
                use_vertex=False,
                gemini_api_key="AIzaTestKey",
                project="test-proj",
                region="us-central1",
                model="gemini-3.8-flash",
                dry_run=True,
                base_branch="non-existent-branch",
            )
        self.assertIn("Base branch 'non-existent-branch' not found on remote origin", str(ctx.exception))

        call_args = mock_subproc.call_args[0][0]
        self.assertEqual(call_args[0:2], ["git", "-c"])
        self.assertIn("ls-remote", call_args)
        self.assertIn("--heads", call_args)
        self.assertEqual(call_args[-1], "non-existent-branch")

        mock_res.stdout = "abc1234567890abcdef\trefs/heads/valid-branch\n"
        run_preflight(
            repo_url="https://github.com/test/repo.git",
            gh_token="gh-token",
            use_vertex=False,
            gemini_api_key="AIzaTestKey",
            project="test-proj",
            region="us-central1",
            model="gemini-3.8-flash",
            dry_run=True,
            base_branch="valid-branch",
        )

    def test_manifest_and_session_branch_resolution(self):
        with patch.dict(os.environ, {"SWARM_SESSION_ID": "session-xyz-123"}):
            branch = resolve_worker_branch(task_item={}, task_index=3)
            self.assertEqual(branch, "agystack/session-xyz-123/worker-3")

        with patch.dict(os.environ, {"SWARM_SESSION_ID": "session-xyz-123"}):
            branch_override = resolve_worker_branch(task_item={"branch": "custom-override-branch"}, task_index=3)
            self.assertEqual(branch_override, "custom-override-branch")

        with patch.dict(os.environ, {}, clear=True):
            branch_fallback = resolve_worker_branch(task_item={}, task_index=2)
            self.assertEqual(branch_fallback, "worker-2")


class TestSetupRuntimeProvisioner(unittest.TestCase):
    def setUp(self):
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_obj.name)

    def tearDown(self):
        self.temp_dir_obj.cleanup()

    @patch("setup_runtime.run_cmd")
    def test_enable_apis_includes_storage(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")
        setup_runtime.enable_apis("my-project-123")
        mock_run_cmd.assert_called_once()
        cmd = mock_run_cmd.call_args[0][0]
        self.assertEqual(cmd[0:3], ["gcloud", "services", "enable"])
        self.assertIn("storage.googleapis.com", cmd)
        self.assertIn("run.googleapis.com", cmd)
        self.assertIn("artifactregistry.googleapis.com", cmd)
        self.assertIn("cloudbuild.googleapis.com", cmd)
        self.assertIn("aiplatform.googleapis.com", cmd)
        self.assertIn("--project=my-project-123", cmd)

    @patch("setup_runtime.run_cmd")
    def test_ensure_gcs_bucket_creates_if_not_exists(self, mock_run_cmd):
        describe_res = MagicMock(returncode=1, stdout="", stderr="Bucket not found")
        create_res = MagicMock(returncode=0, stdout="", stderr="")
        mock_run_cmd.side_effect = [describe_res, create_res]

        bucket_name = setup_runtime.ensure_gcs_bucket("my-new-bucket", "my-project-123", "us-central1")
        self.assertEqual(bucket_name, "my-new-bucket")
        self.assertEqual(mock_run_cmd.call_count, 2)
        describe_cmd = mock_run_cmd.call_args_list[0][0][0]
        self.assertEqual(describe_cmd, ["gcloud", "storage", "buckets", "describe", "gs://my-new-bucket"])
        create_cmd = mock_run_cmd.call_args_list[1][0][0]
        self.assertEqual(
            create_cmd,
            ["gcloud", "storage", "buckets", "create", "gs://my-new-bucket", "--project=my-project-123", "--location=us-central1"]
        )

    @patch("setup_runtime.run_cmd")
    def test_ensure_gcs_bucket_skips_if_exists(self, mock_run_cmd):
        describe_res = MagicMock(returncode=0, stdout="{}", stderr="")
        mock_run_cmd.return_value = describe_res

        bucket_name = setup_runtime.ensure_gcs_bucket("gs://my-existing-bucket", "my-project-123", "us-central1")
        self.assertEqual(bucket_name, "my-existing-bucket")
        self.assertEqual(mock_run_cmd.call_count, 1)
        describe_cmd = mock_run_cmd.call_args[0][0]
        self.assertEqual(describe_cmd, ["gcloud", "storage", "buckets", "describe", "gs://my-existing-bucket"])

    @patch("setup_runtime.run_cmd")
    def test_configure_iam_permissions_default_compute_sa(self, mock_run_cmd):
        project_desc_res = MagicMock(returncode=0, stdout="9876543210\n", stderr="")
        bind_aiplatform_res = MagicMock(returncode=0, stdout="", stderr="")
        bind_storage_res = MagicMock(returncode=0, stdout="", stderr="")
        mock_run_cmd.side_effect = [project_desc_res, bind_aiplatform_res, bind_storage_res]

        sa = setup_runtime.configure_iam_permissions("my-project-123")
        self.assertEqual(sa, "9876543210-compute@developer.gserviceaccount.com")
        self.assertEqual(mock_run_cmd.call_count, 3)

        desc_cmd = mock_run_cmd.call_args_list[0][0][0]
        self.assertEqual(desc_cmd, ["gcloud", "projects", "describe", "my-project-123", "--format=value(projectNumber)"])

        bind1 = mock_run_cmd.call_args_list[1][0][0]
        self.assertEqual(
            bind1,
            [
                "gcloud", "projects", "add-iam-policy-binding", "my-project-123",
                "--member=serviceAccount:9876543210-compute@developer.gserviceaccount.com",
                "--role=roles/aiplatform.user"
            ]
        )

        bind2 = mock_run_cmd.call_args_list[2][0][0]
        self.assertEqual(
            bind2,
            [
                "gcloud", "projects", "add-iam-policy-binding", "my-project-123",
                "--member=serviceAccount:9876543210-compute@developer.gserviceaccount.com",
                "--role=roles/storage.objectAdmin"
            ]
        )

    @patch("setup_runtime.run_cmd")
    def test_configure_iam_permissions_custom_sa(self, mock_run_cmd):
        bind_aiplatform_res = MagicMock(returncode=0, stdout="", stderr="")
        bind_storage_res = MagicMock(returncode=0, stdout="", stderr="")
        mock_run_cmd.side_effect = [bind_aiplatform_res, bind_storage_res]

        sa = setup_runtime.configure_iam_permissions("my-project-123", "custom-runner@my-project-123.iam.gserviceaccount.com")
        self.assertEqual(sa, "custom-runner@my-project-123.iam.gserviceaccount.com")
        self.assertEqual(mock_run_cmd.call_count, 2)

        bind1 = mock_run_cmd.call_args_list[0][0][0]
        self.assertEqual(
            bind1,
            [
                "gcloud", "projects", "add-iam-policy-binding", "my-project-123",
                "--member=serviceAccount:custom-runner@my-project-123.iam.gserviceaccount.com",
                "--role=roles/aiplatform.user"
            ]
        )

        bind2 = mock_run_cmd.call_args_list[1][0][0]
        self.assertEqual(
            bind2,
            [
                "gcloud", "projects", "add-iam-policy-binding", "my-project-123",
                "--member=serviceAccount:custom-runner@my-project-123.iam.gserviceaccount.com",
                "--role=roles/storage.objectAdmin"
            ]
        )

    @patch("setup_runtime.run_cmd")
    def test_build_and_deploy_worker_creates_job_with_memory_and_cpu(self, mock_run_cmd):
        repo_desc_res = MagicMock(returncode=0, stdout="", stderr="")
        build_res = MagicMock(returncode=0, stdout="", stderr="")
        job_desc_res = MagicMock(returncode=1, stdout="", stderr="Job not found")
        job_create_res = MagicMock(returncode=0, stdout="", stderr="")
        mock_run_cmd.side_effect = [repo_desc_res, build_res, job_desc_res, job_create_res]

        setup_runtime.build_and_deploy_worker(
            project_id="my-project-123",
            region="us-central1",
            image_tag="us-central1-docker.pkg.dev/my-project-123/agystack/worker:latest",
            scripts_dir="skills/swarm/scripts",
            service_account="custom-sa@example.com",
        )

        job_cmd = mock_run_cmd.call_args_list[-1][0][0]
        self.assertEqual(job_cmd[0:4], ["gcloud", "run", "jobs", "create"])
        self.assertIn("--memory=2Gi", job_cmd)
        self.assertIn("--cpu=2", job_cmd)
        self.assertIn("--parallelism=100", job_cmd)
        self.assertIn("--max-retries=0", job_cmd)
        self.assertIn("--image=us-central1-docker.pkg.dev/my-project-123/agystack/worker:latest", job_cmd)
        self.assertIn("--region=us-central1", job_cmd)
        self.assertIn("--project=my-project-123", job_cmd)
        self.assertIn("--service-account=custom-sa@example.com", job_cmd)

    @patch("setup_runtime.run_cmd")
    def test_build_and_deploy_worker_updates_job_with_memory_and_cpu(self, mock_run_cmd):
        repo_desc_res = MagicMock(returncode=0, stdout="", stderr="")
        build_res = MagicMock(returncode=0, stdout="", stderr="")
        job_desc_res = MagicMock(returncode=0, stdout="{}", stderr="")
        job_update_res = MagicMock(returncode=0, stdout="", stderr="")
        mock_run_cmd.side_effect = [repo_desc_res, build_res, job_desc_res, job_update_res]

        setup_runtime.build_and_deploy_worker(
            project_id="my-project-123",
            region="us-central1",
            image_tag="us-central1-docker.pkg.dev/my-project-123/agystack/worker:latest",
            scripts_dir="skills/swarm/scripts",
            service_account="custom-sa@example.com",
        )

        job_cmd = mock_run_cmd.call_args_list[-1][0][0]
        self.assertEqual(job_cmd[0:4], ["gcloud", "run", "jobs", "update"])
        self.assertIn("--memory=2Gi", job_cmd)
        self.assertIn("--cpu=2", job_cmd)
        self.assertIn("--parallelism=100", job_cmd)
        self.assertIn("--max-retries=0", job_cmd)
        self.assertIn("--service-account=custom-sa@example.com", job_cmd)

    def test_write_runtime_config_persists_gcs_bucket(self):
        target_file = self.temp_dir / "agystack-runtime.json"
        config = setup_runtime.write_runtime_config(
            project_id="test-proj",
            region="us-central1",
            job_name="agystack-swarm-worker",
            image_tag="us-central1-docker.pkg.dev/test-proj/agystack/worker:latest",
            auth_mode="vertex",
            gcs_bucket="test-proj-swarm-results",
            target_paths=[target_file],
            service_account="test-sa@developer.gserviceaccount.com",
        )

        self.assertEqual(config["gcs_bucket"], "test-proj-swarm-results")
        self.assertEqual(config["auth_mode"], "vertex")
        self.assertEqual(config["runtime"], "cloud-run")
        self.assertEqual(config["service_account"], "test-sa@developer.gserviceaccount.com")

        loaded = json.loads(target_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["gcs_bucket"], "test-proj-swarm-results")
        self.assertEqual(loaded["job_name"], "agystack-swarm-worker")
        self.assertEqual(loaded["parallelism"], 100)
        self.assertEqual(loaded["service_account"], "test-sa@developer.gserviceaccount.com")

    @patch("setup_runtime.write_runtime_config")
    @patch("setup_runtime.run_cmd")
    def test_run_provisioning_full_flow(self, mock_run_cmd, mock_write_cfg):
        mock_run_cmd.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # enable_apis
            MagicMock(returncode=1, stdout="", stderr=""),  # bucket describe
            MagicMock(returncode=0, stdout="", stderr=""),  # bucket create
            MagicMock(returncode=0, stdout="", stderr=""),  # role binding aiplatform
            MagicMock(returncode=0, stdout="", stderr=""),  # role binding storage
            MagicMock(returncode=0, stdout="", stderr=""),  # repo describe
            MagicMock(returncode=0, stdout="", stderr=""),  # builds submit
            MagicMock(returncode=1, stdout="", stderr=""),  # job describe (1 => create)
            MagicMock(returncode=0, stdout="", stderr=""),  # job create
        ]

        summary = setup_runtime.run_provisioning(
            project_id="test-proj-full",
            region="us-central1",
            scripts_dir="skills/swarm/scripts",
            bucket_name="custom-bucket",
            service_account="custom-sa@developer.gserviceaccount.com",
        )

        all_cmds = [call[0][0] for call in mock_run_cmd.call_args_list]

        api_cmd = next(cmd for cmd in all_cmds if cmd[0:3] == ["gcloud", "services", "enable"])
        self.assertIn("storage.googleapis.com", api_cmd)

        bucket_create_cmd = next(cmd for cmd in all_cmds if len(cmd) > 3 and cmd[0:4] == ["gcloud", "storage", "buckets", "create"])
        self.assertIn("gs://custom-bucket", bucket_create_cmd)
        self.assertIn("--project=test-proj-full", bucket_create_cmd)

        iam_cmds = [cmd for cmd in all_cmds if len(cmd) > 3 and cmd[0:3] == ["gcloud", "projects", "add-iam-policy-binding"]]
        self.assertEqual(len(iam_cmds), 2)
        roles_bound = {next(arg.split("=")[1] for arg in cmd if arg.startswith("--role=")) for cmd in iam_cmds}
        self.assertEqual(roles_bound, {"roles/aiplatform.user", "roles/storage.objectAdmin"})

        job_create_cmd = next(cmd for cmd in all_cmds if len(cmd) > 3 and cmd[0:4] == ["gcloud", "run", "jobs", "create"])
        self.assertIn("--memory=2Gi", job_create_cmd)
        self.assertIn("--cpu=2", job_create_cmd)
        self.assertIn("--service-account=custom-sa@developer.gserviceaccount.com", job_create_cmd)

        mock_write_cfg.assert_called_once()
        self.assertEqual(mock_write_cfg.call_args[1].get("gcs_bucket"), "custom-bucket")
        self.assertEqual(mock_write_cfg.call_args[1].get("service_account"), "custom-sa@developer.gserviceaccount.com")
        self.assertEqual(summary.get("service_account"), "custom-sa@developer.gserviceaccount.com")


if __name__ == "__main__":
    unittest.main()

