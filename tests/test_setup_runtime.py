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
        self.assertEqual(len(deps), 3)
        for pkg in ["google-cloud-storage", "google-genai", "google-cloud-run"]:
            self.assertIn(pkg, deps)
            self.assertTrue(deps[pkg]["installed"])
            self.assertTrue(deps[pkg]["ok"])
            self.assertEqual(deps[pkg]["version"], "1.2.3")
            self.assertIsNone(deps[pkg]["error"])

    def test_check_python_dependencies_missing_import(self):
        def fake_import(name):
            raise ImportError(f"No module named {name}")

        deps = setup_runtime.check_python_dependencies(import_fn=fake_import)
        for pkg in ["google-cloud-storage", "google-genai", "google-cloud-run"]:
            self.assertFalse(deps[pkg]["installed"])
            self.assertTrue(deps[pkg]["ok"])
            self.assertIsNone(deps[pkg]["version"])
            self.assertIn(f"pip install {pkg}", deps[pkg]["error"])

    def test_check_python_dependencies_unexpected_exception(self):
        def fake_import(name):
            raise RuntimeError("Unexpected import failure")

        deps = setup_runtime.check_python_dependencies(import_fn=fake_import)
        for pkg in ["google-cloud-storage", "google-genai", "google-cloud-run"]:
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


if __name__ == "__main__":
    unittest.main()
