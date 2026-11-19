import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "setup-agystack" / "scripts"))
import setup_runtime


@contextlib.contextmanager
def isolated_home():
    with tempfile.TemporaryDirectory() as tmp_home:
        clean_env = os.environ.copy()
        clean_env["HOME"] = tmp_home
        clean_env.pop("ANTIGRAVITY_APP_DATA_DIR", None)
        clean_env.pop("ANTIGRAVITY_CONVERSATION_ID", None)
        with patch.dict(os.environ, clean_env, clear=True):
            yield Path(tmp_home).resolve()


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
            return MagicMock(returncode=1, stdout="", stderr="")

        mock_run_cmd.side_effect = fake_run

        deps = setup_runtime.check_dependencies()

        self.assertEqual(set(deps.keys()), {"bun", "gh", "gt"})

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

    @patch("setup_runtime.run_cmd")
    def test_check_dependencies_missing_all(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(returncode=127, stdout="", stderr="command not found")

        deps = setup_runtime.check_dependencies()

        self.assertEqual(set(deps.keys()), {"bun", "gh", "gt"})
        for tool in ["bun", "gh", "gt"]:
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
        }

        with isolated_home() as tmp_home:
            with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
                with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                    with self.assertRaises(SystemExit) as cm:
                        setup_runtime.main()
                    self.assertEqual(cm.exception.code, 0)
                    output = json.loads(mock_out.getvalue().strip())
                    self.assertEqual(
                        set(output.keys()),
                        {
                            "bun",
                            "gh",
                            "gt",
                            "platform",
                            "safety_hook",
                            "artifact_dir",
                            "model_config",
                            "skill_collisions",
                            "status",
                        },
                    )
                    self.assertEqual(output["status"], "OK")
                    self.assertTrue(output["bun"]["ok"])
                    self.assertTrue(output["gh"]["ok"])
                    self.assertTrue(output["skill_collisions"]["ok"])
                    self.assertFalse(output["skill_collisions"]["collision"])
                    self.assertTrue(Path(output["artifact_dir"]["path"]).is_relative_to(tmp_home))

    @patch("setup_runtime.check_dependencies")
    def test_doctor_main_exit_failure_missing_gh(self, mock_check_deps):
        mock_check_deps.return_value = {
            "bun": {"installed": True, "version": "1.3.14", "ok": True, "error": None, "required": True},
            "gh": {"installed": False, "version": None, "ok": False, "error": "gh not found", "required": True},
            "gt": {"installed": True, "version": "0.21.0", "ok": True, "error": None, "required": False},
        }

        with isolated_home():
            with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
                with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                    with self.assertRaises(SystemExit) as cm:
                        setup_runtime.main()
                    self.assertEqual(cm.exception.code, 1)
                    output = json.loads(mock_out.getvalue().strip())
                    self.assertEqual(output["status"], "ERROR")

    @patch("setup_runtime.check_dependencies")
    def test_doctor_main_exit_failure_bun_sub_v1(self, mock_check_deps):
        mock_check_deps.return_value = {
            "bun": {"installed": True, "version": "0.8.0", "ok": False, "error": "v1.0+ required", "required": True},
            "gh": {"installed": True, "version": "2.97.0", "ok": True, "error": None, "required": True},
        }

        with isolated_home():
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
        }
        with isolated_home():
            with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
                with patch("sys.stdout", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as cm:
                        setup_runtime.main()
                    self.assertEqual(cm.exception.code, 0)

            mock_check_deps.return_value = {
                "bun": {"installed": True, "version": "1.3.14", "ok": True, "error": None, "required": True},
                "gh": {"installed": False, "version": None, "ok": False, "error": "gh not found", "required": True},
                "gt": {"installed": True, "version": "0.21.0", "ok": True, "error": None, "required": False},
            }
            with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
                with patch("sys.stdout", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as cm:
                        setup_runtime.main()
                    self.assertEqual(cm.exception.code, 1)


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
            hook_path=REPO_ROOT / "skills" / "poteto-mode" / "scripts" / "hooks" / "pre_tool_safety.py",
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
        res = setup_runtime.parse_model_config(config_path=REPO_ROOT / "agystack-models.md")
        self.assertTrue(res["installed"])
        self.assertTrue(res["ok"])
        self.assertGreater(res["roles_count"], 0)
        self.assertIn("arena runners", res["roles"])
        self.assertEqual(res["roles"]["arena runners"], ["inherit", "flash", "pro"])
        self.assertNotIn("swarm workers", res["roles"])
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

    def test_parse_model_config_precedence_workspace_and_plugin_over_home(self):
        with isolated_home() as tmp_home, tempfile.TemporaryDirectory() as tmp_ws:
            home_cfg = tmp_home / ".gemini" / "config" / "plugins" / "agystack" / "agystack-models.md"
            home_cfg.parent.mkdir(parents=True, exist_ok=True)
            home_cfg.write_text("feature: flash_lite\n", encoding="utf-8")

            ws_dir = Path(tmp_ws).resolve()
            prev_cwd = Path.cwd()
            try:
                os.chdir(ws_dir)
                # Without a workspace config, owning plugin root wins over $HOME
                plugin_res = setup_runtime.parse_model_config()
                self.assertTrue(plugin_res["ok"])
                self.assertEqual(plugin_res["path"], str((REPO_ROOT / "agystack-models.md").resolve()))
                self.assertNotIn("swarm workers", plugin_res["roles"])

                # Workspace-local .agents/plugins/agystack/agystack-models.md wins over both
                ws_cfg = ws_dir / ".agents" / "plugins" / "agystack" / "agystack-models.md"
                ws_cfg.parent.mkdir(parents=True, exist_ok=True)
                ws_cfg.write_text("feature: pro\n", encoding="utf-8")

                ws_res = setup_runtime.parse_model_config()
                self.assertTrue(ws_res["ok"])
                self.assertEqual(ws_res["path"], str(ws_cfg.resolve()))
                self.assertEqual(ws_res["roles"]["feature"], ["pro"])
            finally:
                os.chdir(prev_cwd)

    def test_check_skill_collisions_absent(self):
        with tempfile.TemporaryDirectory() as tmp_root:
            (Path(tmp_root) / "skills" / "poteto-mode").mkdir(parents=True, exist_ok=True)
            res = setup_runtime.check_skill_collisions(plugin_root=tmp_root)
            self.assertTrue(res["ok"])
            self.assertFalse(res["collision"])
            self.assertIsNone(res["error"])
            self.assertTrue(res["required"])
            self.assertEqual(res["path"], str((Path(tmp_root).resolve() / "skills" / "swarm")))

        repo_res = setup_runtime.check_skill_collisions()
        self.assertTrue(repo_res["ok"])
        self.assertFalse(repo_res["collision"])

    def test_check_skill_collisions_present(self):
        with tempfile.TemporaryDirectory() as tmp_root:
            swarm_dir = Path(tmp_root) / "skills" / "swarm"
            swarm_dir.mkdir(parents=True, exist_ok=True)
            res = setup_runtime.check_skill_collisions(plugin_root=tmp_root)
            self.assertFalse(res["ok"])
            self.assertTrue(res["collision"])
            self.assertTrue(res["required"])
            self.assertEqual(res["path"], str(swarm_dir.resolve()))
            self.assertIn("Legacy skills/swarm directory shadows Antigravity built-in swarm", res["error"])
            self.assertIn(str(swarm_dir.resolve()), res["error"])

    def test_check_platform_all_passing(self):
        with isolated_home() as tmp_home:
            res = setup_runtime.check_platform()
            self.assertTrue(res["ok"])
            self.assertTrue(res["hook_contract"]["ok"])
            self.assertEqual(res["hook_contract"]["decision"], "deny")
            self.assertTrue(res["artifact_dir"]["ok"])
            self.assertTrue(res["artifact_dir"]["writable"])
            self.assertTrue(Path(res["artifact_dir"]["path"]).is_relative_to(tmp_home))
            self.assertTrue(res["model_config"]["ok"])
            self.assertEqual(res["model_config"]["path"], str((REPO_ROOT / "agystack-models.md").resolve()))
            self.assertTrue(res["skill_collisions"]["ok"])
            self.assertFalse(res["skill_collisions"]["collision"])

    def test_doctor_platform_overall_status_ok_exit_0(self):
        with isolated_home() as tmp_home:
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
                    self.assertTrue(Path(report["artifact_dir"]["path"]).is_relative_to(tmp_home))
                    self.assertEqual(report["model_config"]["path"], str((REPO_ROOT / "agystack-models.md").resolve()))
                    self.assertIn("arena runners", report["model_config"]["roles"])
                    self.assertNotIn("swarm workers", report["model_config"]["roles"])
                    self.assertTrue(report["skill_collisions"]["ok"])

    def test_doctor_platform_failure_exits_1(self):
        with isolated_home():
            with patch(
                "setup_runtime.check_hook_contract",
                return_value={"ok": False, "required": True, "error": "Hook failure"},
            ):
                with patch("sys.argv", ["setup_runtime.py", "--doctor"]):
                    with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                        with self.assertRaises(SystemExit) as cm:
                            setup_runtime.main()
                        self.assertEqual(cm.exception.code, 1)
                        report = json.loads(mock_out.getvalue().strip())
                        self.assertEqual(report["status"], "ERROR")
                        self.assertFalse(report["platform"]["ok"])


if __name__ == "__main__":
    unittest.main()
