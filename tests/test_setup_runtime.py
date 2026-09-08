import io
import json
import os
import sys
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


if __name__ == "__main__":
    unittest.main()
