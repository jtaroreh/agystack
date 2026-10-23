import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "setup-agystack" / "scripts"))
import setup_runtime


class TestSetupRuntimeDoctor(unittest.TestCase):
    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_all_installed(self, mock_run_cmd):
        def fake_run(cmd, *args, **kwargs):
            tool = cmd[0]
            if tool == "bun":
                return MagicMock(returncode=0, stdout="1.3.14\n", stderr="")
            elif tool == "gh":
                return MagicMock(
                    returncode=0,
                    stdout="gh version 2.97.0 (2026-07-31)\nhttps://github.com/cli/cli/releases/tag/v2.97.0\n",
                    stderr="",
                )
            elif tool == "gt":
                return MagicMock(returncode=0, stdout="Graphite CLI version 0.21.0\n", stderr="")
            elif tool == "gcloud":
                return MagicMock(returncode=0, stdout="Google Cloud SDK 583.0.0\n", stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")

        mock_run_cmd.side_effect = fake_run

        deps = setup_runtime.check_dependencies()

        self.assertTrue(deps["bun"]["installed"])
        self.assertTrue(deps["bun"]["ok"])
        self.assertEqual(deps["bun"]["version"], "1.3.14")
        self.assertIsNone(deps["bun"]["error"])

        self.assertTrue(deps["gh"]["installed"])
        self.assertTrue(deps["gh"]["ok"])
        self.assertEqual(deps["gh"]["version"], "2.97.0")
        self.assertIsNone(deps["gh"]["error"])

        self.assertTrue(deps["gt"]["installed"])
        self.assertTrue(deps["gt"]["ok"])
        self.assertEqual(deps["gt"]["version"], "0.21.0")
        self.assertIsNone(deps["gt"]["error"])

        self.assertTrue(deps["gcloud"]["installed"])
        self.assertTrue(deps["gcloud"]["ok"])
        self.assertEqual(deps["gcloud"]["version"], "583.0.0")
        self.assertIsNone(deps["gcloud"]["error"])

    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_missing_all(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(returncode=127, stdout="", stderr="command not found")

        deps = setup_runtime.check_dependencies()

        for tool in ["bun", "gh", "gt", "gcloud"]:
            self.assertFalse(deps[tool]["installed"], f"{tool} should not be installed")
            self.assertFalse(deps[tool]["ok"], f"{tool} ok should be False")
            self.assertIsNone(deps[tool]["version"])
            self.assertIsNotNone(deps[tool]["error"])

    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_bun_version_too_low(self, mock_run_cmd):
        def fake_run(cmd, *args, **kwargs):
            tool = cmd[0]
            if tool == "bun":
                return MagicMock(returncode=0, stdout="0.9.4\n", stderr="")
            elif tool == "gh":
                return MagicMock(returncode=0, stdout="gh version 2.50.0\n", stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")

        mock_run_cmd.side_effect = fake_run

        deps = setup_runtime.check_dependencies()

        self.assertTrue(deps["bun"]["installed"])
        self.assertEqual(deps["bun"]["version"], "0.9.4")
        self.assertFalse(deps["bun"]["ok"])
        self.assertIn("1.0+", deps["bun"]["error"])

    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_custom_runner(self, mock_run_cmd):
        def custom_runner(cmd, check=False):
            if cmd[0] == "bun":
                return MagicMock(returncode=0, stdout="v1.1.0\n", stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")

        deps = setup_runtime.check_dependencies(run_cmd_fn=custom_runner)
        self.assertTrue(deps["bun"]["installed"])
        self.assertTrue(deps["bun"]["ok"])
        self.assertEqual(deps["bun"]["version"], "1.1.0")
        self.assertFalse(deps["gh"]["installed"])

    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_malformed_version_output(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(
            returncode=0,
            stdout="warning: check updates failed\n",
            stderr="",
        )
        deps = setup_runtime.check_dependencies()
        self.assertTrue(deps["gh"]["installed"])
        self.assertFalse(deps["gh"]["ok"])
        self.assertIsNone(deps["gh"]["version"])
        self.assertIn("Failed to parse gh version", deps["gh"]["error"])

    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_preserves_unexpected_exceptions(self, mock_run_cmd):
        mock_run_cmd.side_effect = PermissionError("Permission denied")
        deps = setup_runtime.check_dependencies()
        self.assertFalse(deps["bun"]["installed"])
        self.assertFalse(deps["bun"]["ok"])
        self.assertIsNone(deps["bun"]["version"])
        self.assertIn("Permission denied", deps["bun"]["error"])
        self.assertNotIn("not found on PATH", deps["bun"]["error"])

    @patch("setup_runtime.check_dependencies")
    def test_doctor_main_exit_success(self, mock_check_deps):
        mock_check_deps.return_value = {
            "bun": {"installed": True, "version": "1.3.14", "ok": True, "error": None, "required": True},
            "gh": {"installed": True, "version": "2.97.0", "ok": True, "error": None, "required": True},
            "gt": {"installed": False, "version": None, "ok": False, "error": "not found", "required": False},
            "gcloud": {"installed": False, "version": None, "ok": False, "error": "not found", "required": False},
        }

        with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    setup_runtime.main()
                self.assertEqual(cm.exception.code, 0)
                output = json.loads(mock_out.getvalue().strip())
                self.assertTrue(output["bun"]["ok"])
                self.assertTrue(output["gh"]["ok"])

    @patch("setup_runtime.check_dependencies")
    def test_doctor_main_exit_failure_missing_gh(self, mock_check_deps):
        mock_check_deps.return_value = {
            "bun": {"installed": True, "version": "1.3.14", "ok": True, "error": None, "required": True},
            "gh": {"installed": False, "version": None, "ok": False, "error": "gh not found", "required": True},
            "gt": {"installed": True, "version": "0.21.0", "ok": True, "error": None, "required": False},
            "gcloud": {"installed": True, "version": "583.0.0", "ok": True, "error": None, "required": False},
        }

        with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as cm:
                    setup_runtime.main()
                self.assertEqual(cm.exception.code, 1)

    @patch("setup_runtime.check_dependencies")
    def test_doctor_main_exit_failure_bun_sub_v1(self, mock_check_deps):
        mock_check_deps.return_value = {
            "bun": {"installed": True, "version": "0.8.0", "ok": False, "error": "v1.0+ required", "required": True},
            "gh": {"installed": True, "version": "2.97.0", "ok": True, "error": None, "required": True},
        }

        with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as cm:
                    setup_runtime.main()
                self.assertEqual(cm.exception.code, 1)

    @patch("setup_runtime.check_dependencies")
    def test_doctor_main_evaluates_all_required_metadata(self, mock_check_deps):
        mock_check_deps.return_value = {
            "bun": {"installed": True, "version": "1.3.14", "ok": True, "error": None, "required": True},
            "gh": {"installed": True, "version": "2.97.0", "ok": True, "error": None, "required": True},
            "gt": {"installed": False, "version": None, "ok": False, "error": "not found", "required": False},
            "gcloud": {"installed": False, "version": None, "ok": False, "error": "not found", "required": False},
        }
        with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as cm:
                    setup_runtime.main()
                self.assertEqual(cm.exception.code, 0)

        mock_check_deps.return_value = {
            "bun": {"installed": True, "version": "1.3.14", "ok": True, "error": None, "required": True},
            "gh": {"installed": False, "version": None, "ok": False, "error": "gh not found", "required": True},
            "gt": {"installed": True, "version": "0.21.0", "ok": True, "error": None, "required": False},
            "gcloud": {"installed": True, "version": "583.0.0", "ok": True, "error": None, "required": False},
        }
        with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as cm:
                    setup_runtime.main()
                self.assertEqual(cm.exception.code, 1)


class TestSetupRuntimeProvisioning(unittest.TestCase):
    @patch("setup_runtime.write_runtime_config")
    @patch("setup_runtime.run_cmd")
    def test_run_provisioning_autoresolves_scripts_dir(self, mock_run_cmd, mock_write_cfg):
        mock_run_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")

        expected_scripts_dir = str(Path(setup_runtime.__file__).resolve().parents[2] / "swarm" / "scripts")
        self.assertTrue(
            (Path(expected_scripts_dir) / "Dockerfile").is_file(),
            f"Expected Dockerfile to exist at {expected_scripts_dir}",
        )

        for invalid_dir in ["", "/nonexistent/invalid/dir", None]:
            mock_run_cmd.reset_mock()
            setup_runtime.run_provisioning(
                project_id="test-proj-autoresolve",
                scripts_dir=invalid_dir,
            )

            all_cmds = [call[0][0] for call in mock_run_cmd.call_args_list]
            build_cmd = next(cmd for cmd in all_cmds if len(cmd) > 2 and cmd[0:3] == ["gcloud", "builds", "submit"])
            self.assertEqual(
                build_cmd[4],
                expected_scripts_dir,
                f"scripts_dir did not resolve to expected directory for input '{invalid_dir}'",
            )

    @patch("setup_runtime.write_runtime_config")
    @patch("setup_runtime.run_cmd")
    def test_run_provisioning_preserves_valid_scripts_dir(self, mock_run_cmd, mock_write_cfg):
        mock_run_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")

        valid_dir = str(Path(setup_runtime.__file__).resolve().parents[2] / "swarm" / "scripts")
        setup_runtime.run_provisioning(
            project_id="test-proj-valid",
            scripts_dir=valid_dir,
        )
        all_cmds = [call[0][0] for call in mock_run_cmd.call_args_list]
        build_cmd = next(cmd for cmd in all_cmds if len(cmd) > 2 and cmd[0:3] == ["gcloud", "builds", "submit"])
        self.assertEqual(build_cmd[4], valid_dir)


class TestSetupRuntimeSecretManager(unittest.TestCase):
    @patch("setup_runtime.run_cmd")
    def test_enable_apis_includes_secretmanager(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")
        setup_runtime.enable_apis("test-proj")
        all_cmds = [call[0][0] for call in mock_run_cmd.call_args_list]
        enable_cmd = next(cmd for cmd in all_cmds if cmd[0:3] == ["gcloud", "services", "enable"])
        self.assertIn("secretmanager.googleapis.com", enable_cmd)

    @patch("setup_runtime.run_cmd")
    def test_ensure_secret_manager_creates_and_binds(self, mock_run_cmd):
        describe_res = MagicMock(returncode=1, stdout="", stderr="Secret not found")
        create_res = MagicMock(returncode=0, stdout="", stderr="")
        bind_res = MagicMock(returncode=0, stdout="", stderr="")
        mock_run_cmd.side_effect = [describe_res, create_res, bind_res]

        secret_name = setup_runtime.ensure_secret_manager(
            project_id="test-proj",
            secret_name="agystack-gh-token",
            service_account="test-sa@developer.gserviceaccount.com",
        )
        self.assertEqual(secret_name, "agystack-gh-token")
        self.assertEqual(mock_run_cmd.call_count, 3)

    @patch("setup_runtime.run_cmd")
    def test_configure_iam_permissions_includes_secret_accessor(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")
        setup_runtime.configure_iam_permissions("test-proj", "sa@developer.gserviceaccount.com")
        all_cmds = [call[0][0] for call in mock_run_cmd.call_args_list]
        roles = [next(arg.split("=")[1] for arg in cmd if arg.startswith("--role=")) for cmd in all_cmds if len(cmd) > 3 and cmd[0:3] == ["gcloud", "projects", "add-iam-policy-binding"]]
        self.assertIn("roles/secretmanager.secretAccessor", roles)


class TestSetupRuntimePythonDependencies(unittest.TestCase):
    def test_check_python_dependencies_all_present(self):
        mock_mod = MagicMock()
        mock_mod.__version__ = "1.2.3"

        def fake_import(name):
            return mock_mod

        deps = setup_runtime.check_python_dependencies(import_fn=fake_import)
        for pkg in ["google-cloud-storage", "google-genai", "google-cloud-run"]:
            self.assertIn("required", deps[pkg])
            self.assertIn(pkg, deps)
            self.assertTrue(deps[pkg]["installed"])
            self.assertTrue(deps[pkg]["ok"])
            self.assertEqual(deps[pkg]["version"], "1.2.3")
            self.assertIsNone(deps[pkg]["error"])

    def test_check_python_dependencies_missing_import(self):
        def fake_import(name):
            raise ImportError(f"No module named {name}")

        deps = setup_runtime.check_python_dependencies(import_fn=fake_import)
        for pkg in ["google-cloud-storage", "google-genai", "google-cloud-run", "anthropic[vertex]"]:
            self.assertFalse(deps[pkg]["installed"])
            self.assertTrue(deps[pkg]["ok"])
            self.assertIsNone(deps[pkg]["version"])
            self.assertIn(f"pip install {pkg}", deps[pkg]["error"])

    def test_check_python_dependencies_unexpected_exception(self):
        def fake_import(name):
            raise RuntimeError("Unexpected import failure")

        deps = setup_runtime.check_python_dependencies(import_fn=fake_import)
        for pkg in ["google-cloud-storage", "google-genai", "google-cloud-run", "anthropic[vertex]"]:
            self.assertFalse(deps[pkg]["installed"])
            self.assertTrue(deps[pkg]["ok"])
            self.assertIn("Unexpected import failure", deps[pkg]["error"])

    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_includes_python(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(returncode=0, stdout="1.0.0\n", stderr="")
        mock_mod = MagicMock()
        mock_mod.__version__ = "2.0.0"

        deps = setup_runtime.check_dependencies(import_fn=lambda name: mock_mod)
        self.assertIn("google-cloud-storage", deps)
        self.assertTrue(deps["google-cloud-storage"]["ok"])

    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_can_exclude_python(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(returncode=0, stdout="1.0.0\n", stderr="")
        deps = setup_runtime.check_dependencies(include_python=False)
        self.assertNotIn("google-cloud-storage", deps)


class TestBuildAndDeployWorkerStaging(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()

        self.skills_dir = self.repo_root / "skills"
        self.swarm_scripts_dir = self.skills_dir / "swarm" / "scripts"
        self.swarm_scripts_dir.mkdir(parents=True, exist_ok=True)
        (self.swarm_scripts_dir / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")

        self.other_skill_dir = self.skills_dir / "poteto-mode"
        self.other_skill_dir.mkdir(parents=True, exist_ok=True)
        (self.other_skill_dir / "SKILL.md").write_text("# Poteto Mode\n", encoding="utf-8")

        (self.skills_dir / ".git").mkdir(parents=True, exist_ok=True)
        (self.skills_dir / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (self.skills_dir / "__pycache__").mkdir(parents=True, exist_ok=True)
        (self.skills_dir / "__pycache__" / "cached.pyc").write_text("bytecode", encoding="utf-8")
        (self.skills_dir / ".pytest_cache").mkdir(parents=True, exist_ok=True)
        (self.skills_dir / ".pytest_cache" / "v").write_text("cache", encoding="utf-8")
        (self.skills_dir / ".ruff_cache").mkdir(parents=True, exist_ok=True)
        (self.skills_dir / ".ruff_cache" / "r").write_text("cache", encoding="utf-8")
        (self.skills_dir / "node_modules").mkdir(parents=True, exist_ok=True)
        (self.skills_dir / "node_modules" / "pkg.json").write_text("{}", encoding="utf-8")
        (self.skills_dir / ".venv").mkdir(parents=True, exist_ok=True)
        (self.skills_dir / ".venv" / "pyvenv.cfg").write_text("home = /bin\n", encoding="utf-8")
        (self.skills_dir / "venv").mkdir(parents=True, exist_ok=True)
        (self.skills_dir / "venv" / "pyvenv.cfg").write_text("home = /bin\n", encoding="utf-8")

        self.rules_dir = self.repo_root / "rules"
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        (self.rules_dir / "AGENTS.md").write_text("# Agent Rules\n", encoding="utf-8")

        self.agents_dir = self.repo_root / "agents"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        (self.agents_dir / "poteto-agent.md").write_text("# Poteto Agent\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("setup_runtime.run_cmd")
    def test_build_and_deploy_worker_staging_no_recursion(self, mock_run_cmd):
        observed_staged = {}

        def fake_run(cmd, *args, **kwargs):
            if len(cmd) > 2 and cmd[0:3] == ["gcloud", "builds", "submit"]:
                staged_skills = self.swarm_scripts_dir / "skills"
                staged_rules = self.swarm_scripts_dir / "rules"
                staged_agents = self.swarm_scripts_dir / "agents"

                observed_staged["staged_skills_exists"] = staged_skills.is_dir()
                observed_staged["staged_rules_exists"] = staged_rules.is_dir()
                observed_staged["staged_agents_exists"] = staged_agents.is_dir()
                observed_staged["other_skill_copied"] = (staged_skills / "poteto-mode" / "SKILL.md").is_file()
                observed_staged["recursion_prevented"] = not (staged_skills / "swarm" / "scripts").exists()
                observed_staged["git_ignored"] = not (staged_skills / ".git").exists()
                observed_staged["pycache_ignored"] = not (staged_skills / "__pycache__").exists()
                observed_staged["pytest_cache_ignored"] = not (staged_skills / ".pytest_cache").exists()
                observed_staged["ruff_cache_ignored"] = not (staged_skills / ".ruff_cache").exists()
                observed_staged["node_modules_ignored"] = not (staged_skills / "node_modules").exists()
                observed_staged["dot_venv_ignored"] = not (staged_skills / ".venv").exists()
                observed_staged["venv_ignored"] = not (staged_skills / "venv").exists()
                observed_staged["rules_file_copied"] = (staged_rules / "AGENTS.md").is_file()
                observed_staged["agents_file_copied"] = (staged_agents / "poteto-agent.md").is_file()
            return MagicMock(returncode=0, stdout="{}", stderr="")

        mock_run_cmd.side_effect = fake_run

        setup_runtime.build_and_deploy_worker(
            project_id="test-proj-staging",
            region="us-central1",
            image_tag="us-central1-docker.pkg.dev/test-proj-staging/agystack/worker:latest",
            scripts_dir=str(self.swarm_scripts_dir),
            job_name="test-job",
        )

        for key, val in observed_staged.items():
            self.assertTrue(val, f"Expected {key} to be True")

        self.assertFalse((self.swarm_scripts_dir / "skills").exists())
        self.assertFalse((self.swarm_scripts_dir / "rules").exists())
        self.assertFalse((self.swarm_scripts_dir / "agents").exists())

    @patch("setup_runtime.run_cmd")
    def test_build_and_deploy_worker_cleans_existing_dst_first(self, mock_run_cmd):
        stale_dst = self.swarm_scripts_dir / "skills"
        stale_dst.mkdir(parents=True, exist_ok=True)
        stale_file = stale_dst / "stale_leftover.txt"
        stale_file.write_text("stale data", encoding="utf-8")

        observed_stale_cleaned = {}

        def fake_run(cmd, *args, **kwargs):
            if len(cmd) > 2 and cmd[0:3] == ["gcloud", "builds", "submit"]:
                staged_skills = self.swarm_scripts_dir / "skills"
                observed_stale_cleaned["stale_cleaned"] = not (staged_skills / "stale_leftover.txt").exists()
                observed_stale_cleaned["new_skill_copied"] = (staged_skills / "poteto-mode" / "SKILL.md").is_file()
            return MagicMock(returncode=0, stdout="{}", stderr="")

        mock_run_cmd.side_effect = fake_run

        setup_runtime.build_and_deploy_worker(
            project_id="test-proj-cleanup",
            region="us-central1",
            image_tag="us-central1-docker.pkg.dev/test-proj-cleanup/agystack/worker:latest",
            scripts_dir=str(self.swarm_scripts_dir),
            job_name="test-job",
        )

        self.assertTrue(observed_stale_cleaned.get("stale_cleaned"))
        self.assertTrue(observed_stale_cleaned.get("new_skill_copied"))
        self.assertFalse((self.swarm_scripts_dir / "skills").exists())

    @patch("setup_runtime.run_cmd")
    def test_build_and_deploy_worker_cleans_staged_dirs_on_error(self, mock_run_cmd):
        def fake_run(cmd, *args, **kwargs):
            if len(cmd) > 2 and cmd[0:3] == ["gcloud", "builds", "submit"]:
                raise RuntimeError("Cloud Build failed abruptly")
            return MagicMock(returncode=0, stdout="{}", stderr="")

        mock_run_cmd.side_effect = fake_run

        with self.assertRaises(RuntimeError):
            setup_runtime.build_and_deploy_worker(
                project_id="test-proj-error",
                region="us-central1",
                image_tag="us-central1-docker.pkg.dev/test-proj-error/agystack/worker:latest",
                scripts_dir=str(self.swarm_scripts_dir),
                job_name="test-job",
            )

        self.assertFalse((self.swarm_scripts_dir / "skills").exists())
        self.assertFalse((self.swarm_scripts_dir / "rules").exists())
        self.assertFalse((self.swarm_scripts_dir / "agents").exists())


class TestSetupRuntimePlatformValidation(unittest.TestCase):
    def test_check_hook_contract_success(self):
        res = setup_runtime.check_hook_contract()
        self.assertTrue(res["installed"])
        self.assertTrue(res["ok"])
        self.assertEqual(res["decision"], "deny")
        self.assertIsNone(res["error"])
        self.assertTrue(res["required"])
        self.assertTrue(Path(res["path"]).is_file())

    def test_check_hook_contract_missing_file(self):
        res = setup_runtime.check_hook_contract(hook_path="/nonexistent/path/pre_tool_safety.py")
        self.assertFalse(res["installed"])
        self.assertFalse(res["ok"])
        self.assertIsNone(res["decision"])
        self.assertIn("not found", res["error"])

    def test_check_hook_contract_unexpected_decision(self):
        fake_proc = MagicMock(returncode=0, stdout=json.dumps({"decision": "allow"}), stderr="")
        res = setup_runtime.check_hook_contract(
            hook_path=Path(__file__).resolve().parent.parent / "skills" / "poteto-mode" / "scripts" / "hooks" / "pre_tool_safety.py",
            run_cmd_fn=lambda *args, **kwargs: fake_proc,
        )
        self.assertTrue(res["installed"])
        self.assertFalse(res["ok"])
        self.assertEqual(res["decision"], "allow")
        self.assertIn("Expected decision 'deny'", res["error"])

    def test_check_artifact_dir_writable_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = setup_runtime.check_artifact_dir(brain_dir=tmp_dir)
            self.assertTrue(res["installed"])
            self.assertTrue(res["ok"])
            self.assertTrue(res["writable"])
            self.assertIsNone(res["error"])
            self.assertEqual(res["path"], str(Path(tmp_dir).resolve()))

    def test_check_artifact_dir_not_writable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(Path, "write_text", side_effect=PermissionError("Permission denied")):
                res = setup_runtime.check_artifact_dir(brain_dir=tmp_dir)
                self.assertTrue(res["installed"])
                self.assertFalse(res["ok"])
                self.assertFalse(res["writable"])
                self.assertIn("not writable", res["error"])

    def test_parse_model_config_success(self):
        res = setup_runtime.parse_model_config()
        self.assertTrue(res["installed"])
        self.assertTrue(res["ok"])
        self.assertGreater(res["roles_count"], 0)
        self.assertIn("arena runners", res["roles"])
        self.assertEqual(res["roles"]["arena runners"], ["inherit", "flash", "pro"])
        self.assertIn("swarm workers", res["roles"])
        self.assertEqual(res["roles"]["swarm workers"], ["flash"])
        self.assertIn("feature", res["roles"])
        self.assertEqual(res["roles"]["feature"], ["inherit"])

    def test_parse_model_config_missing_file(self):
        res = setup_runtime.parse_model_config(config_path="/nonexistent/agystack-models.md")
        self.assertFalse(res["installed"])
        self.assertFalse(res["ok"])
        self.assertEqual(res["roles_count"], 0)
        self.assertIn("not found", res["error"])

    def test_parse_model_config_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            empty_file = Path(tmp_dir) / "agystack-models.md"
            empty_file.write_text("# only comments\n\n", encoding="utf-8")
            res = setup_runtime.parse_model_config(config_path=str(empty_file))
            self.assertTrue(res["installed"])
            self.assertFalse(res["ok"])
            self.assertEqual(res["roles_count"], 0)
            self.assertIn("No model roles defined", res["error"])

    def test_check_platform_all_passing(self):
        res = setup_runtime.check_platform()
        self.assertTrue(res["ok"])
        self.assertTrue(res["hook_contract"]["ok"])
        self.assertEqual(res["hook_contract"]["decision"], "deny")
        self.assertTrue(res["artifact_dir"]["ok"])
        self.assertTrue(res["artifact_dir"]["writable"])
        self.assertTrue(res["model_config"]["ok"])

    def test_doctor_platform_overall_status_ok_exit_0(self):
        with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    setup_runtime.main()
                self.assertEqual(cm.exception.code, 0)
                report = json.loads(mock_out.getvalue().strip())
                self.assertEqual(report["status"], "OK")
                self.assertTrue(report["platform"]["ok"])
                self.assertEqual(report["safety_hook"]["decision"], "deny")
                self.assertTrue(report["artifact_dir"]["writable"])
                self.assertIn("arena runners", report["model_config"]["roles"])

    def test_doctor_platform_failure_exits_1(self):
        with patch("setup_runtime.check_hook_contract", return_value={"ok": False, "required": True, "error": "Hook failure"}):
            with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
                with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                    with self.assertRaises(SystemExit) as cm:
                        setup_runtime.main()
                    self.assertEqual(cm.exception.code, 1)
                    report = json.loads(mock_out.getvalue().strip())
                    self.assertEqual(report["status"], "ERROR")
                    self.assertFalse(report["platform"]["ok"])


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
        bind_secret_res = MagicMock(returncode=0, stdout="", stderr="")
        mock_run_cmd.side_effect = [project_desc_res, bind_aiplatform_res, bind_storage_res, bind_secret_res]

        sa = setup_runtime.configure_iam_permissions("my-project-123")
        self.assertEqual(sa, "9876543210-compute@developer.gserviceaccount.com")
        self.assertEqual(mock_run_cmd.call_count, 4)

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

        bind3 = mock_run_cmd.call_args_list[3][0][0]
        self.assertEqual(
            bind3,
            [
                "gcloud", "projects", "add-iam-policy-binding", "my-project-123",
                "--member=serviceAccount:9876543210-compute@developer.gserviceaccount.com",
                "--role=roles/secretmanager.secretAccessor"
            ]
        )

    @patch("setup_runtime.run_cmd")
    def test_configure_iam_permissions_custom_sa(self, mock_run_cmd):
        bind_aiplatform_res = MagicMock(returncode=0, stdout="", stderr="")
        bind_storage_res = MagicMock(returncode=0, stdout="", stderr="")
        bind_secret_res = MagicMock(returncode=0, stdout="", stderr="")
        mock_run_cmd.side_effect = [bind_aiplatform_res, bind_storage_res, bind_secret_res]

        sa = setup_runtime.configure_iam_permissions("my-project-123", "custom-runner@my-project-123.iam.gserviceaccount.com")
        self.assertEqual(sa, "custom-runner@my-project-123.iam.gserviceaccount.com")
        self.assertEqual(mock_run_cmd.call_count, 3)

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

        bind3 = mock_run_cmd.call_args_list[2][0][0]
        self.assertEqual(
            bind3,
            [
                "gcloud", "projects", "add-iam-policy-binding", "my-project-123",
                "--member=serviceAccount:custom-runner@my-project-123.iam.gserviceaccount.com",
                "--role=roles/secretmanager.secretAccessor"
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
        self.assertIn("--parallelism=16", job_cmd)
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
        self.assertIn("--parallelism=16", job_cmd)
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
        self.assertEqual(loaded["parallelism"], 16)
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
            MagicMock(returncode=0, stdout="", stderr=""),  # role binding secretmanager
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
        self.assertEqual(len(iam_cmds), 3)
        roles_bound = {next(arg.split("=")[1] for arg in cmd if arg.startswith("--role=")) for cmd in iam_cmds}
        self.assertEqual(roles_bound, {"roles/aiplatform.user", "roles/storage.objectAdmin", "roles/secretmanager.secretAccessor"})

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
