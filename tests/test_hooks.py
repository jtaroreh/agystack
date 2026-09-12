import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = REPO_ROOT / "skills" / "poteto-mode" / "scripts" / "hooks" / "post_tool_lint.py"
SAFETY_HOOK_SCRIPT = (
    REPO_ROOT / "skills" / "poteto-mode" / "scripts" / "hooks" / "pre_tool_safety.py"
)


def run_hook(stdin_data: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=stdin_data,
        capture_output=True,
        text=True,
        check=False,
    )


def run_safety_hook(stdin_data: str, env: dict = None) -> subprocess.CompletedProcess:
    run_env = os.environ.copy()
    run_env.pop("NON_INTERACTIVE", None)
    run_env.pop("CI", None)
    run_env.pop("CLOUD_RUN_TASK_INDEX", None)
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(SAFETY_HOOK_SCRIPT)],
        input=stdin_data,
        capture_output=True,
        text=True,
        check=False,
        env=run_env,
    )


class TestPostToolLintHook(unittest.TestCase):
    def test_hook_script_exists(self):
        self.assertTrue(HOOK_SCRIPT.is_file(), f"Hook script does not exist at {HOOK_SCRIPT}")

    def test_non_matching_tool(self):
        payload = {
            "toolCall": {
                "name": "view_file",
                "args": {
                    "AbsolutePath": "/Users/joeltaroreh/projects/pstack-agy/README.md"
                },
            }
        }
        result = run_hook(json.dumps(payload))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_invalid_json_on_stdin(self):
        result = run_hook("invalid json payload {{}}")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_empty_stdin(self):
        result = run_hook("")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_formatter_formats_unformatted_python(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_py = Path(tmp_dir) / "sample.py"
            temp_py.write_text("x=1;y=2\n", encoding="utf-8")

            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(temp_py),
                        "CodeContent": "x=1;y=2\n",
                    },
                }
            }
            result = run_hook(json.dumps(payload))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout.strip()), {})

            if shutil.which("ruff"):
                formatted_content = temp_py.read_text(encoding="utf-8")
                self.assertNotEqual(formatted_content, "x=1;y=2\n")
                self.assertIn("x = 1", formatted_content)
                self.assertIn("y = 2", formatted_content)

    def test_argument_aliases(self):
        aliases = ["TargetFile", "target_file", "AbsolutePath", "FilePath", "path"]
        with tempfile.TemporaryDirectory() as tmp_dir:
            for idx, alias in enumerate(aliases):
                temp_py = Path(tmp_dir) / f"sample_{idx}.py"
                temp_py.write_text("a=10;b=20\n", encoding="utf-8")
                payload = {
                    "toolCall": {
                        "name": "replace_file_content",
                        "args": {
                            alias: str(temp_py),
                        },
                    }
                }
                result = run_hook(json.dumps(payload))
                self.assertEqual(result.returncode, 0)
                if shutil.which("ruff"):
                    self.assertIn("a = 10", temp_py.read_text(encoding="utf-8"))


class TestPreToolSafetyHook(unittest.TestCase):
    def test_safety_hook_script_exists(self):
        self.assertTrue(
            SAFETY_HOOK_SCRIPT.is_file(),
            f"Safety hook script does not exist at {SAFETY_HOOK_SCRIPT}",
        )

    def test_safety_hook_safe_commands(self):
        safe_commands = [
            "pytest",
            "git status",
            "git push --force-with-lease origin feat/branch",
            "git push origin feat/branch -f",
            "rm -rf /tmp/scratch",
            "ls -la",
            "echo 'hello world'",
        ]
        for cmd in safe_commands:
            with self.subTest(cmd=cmd):
                payload = {
                    "toolCall": {
                        "name": "run_command",
                        "args": {"command": cmd},
                    }
                }
                result = run_safety_hook(json.dumps(payload))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_safety_hook_destructive_commands_interactive(self):
        destructive_commands = [
            "rm -rf /",
            "rm -fr /",
            "rm -Rf /",
            "rm -rf /*",
            "rm -r -f /",
            "rm -f -r /",
            "rm --recursive --force /",
            "rm --no-preserve-root /",
            'rm -rf "/"',
            "rm -rf '/*'",
            "git push --force origin main",
            "git push -f origin main",
            "git push origin main -f",
            "git push origin main --force",
            "git push origin +main",
            "git push +master",
            "git push origin +HEAD:main",
            "git push +refs/heads/main",
            'drop database "testdb"',
            "drop database `testdb`",
            "drop database testdb",
            "DROP DATABASE production",
        ]
        for cmd in destructive_commands:
            with self.subTest(cmd=cmd):
                payload = {
                    "toolCall": {
                        "name": "run_command",
                        "args": {"command": cmd},
                    }
                }
                result = run_safety_hook(json.dumps(payload))
                self.assertEqual(result.returncode, 0)
                parsed = json.loads(result.stdout.strip())
                self.assertEqual(
                    parsed.get("decision"),
                    "force_ask",
                    f"Command failed to prompt: {cmd}",
                )
                self.assertIn("Destructive command detected", parsed.get("reason", ""))

    def test_safety_hook_headless_rejects_destructive(self):
        headless_envs = [
            {"NON_INTERACTIVE": "1"},
            {"CI": "true"},
            {"CI": "1"},
            {"CLOUD_RUN_TASK_INDEX": "0"},
        ]
        destructive_commands = [
            "rm -rf /",
            "git push origin main -f",
            'drop database "testdb"',
        ]
        for env in headless_envs:
            for cmd in destructive_commands:
                with self.subTest(env=env, cmd=cmd):
                    payload = {
                        "toolCall": {
                            "name": "run_command",
                            "args": {"command": cmd},
                        }
                    }
                    result = run_safety_hook(json.dumps(payload), env=env)
                    self.assertEqual(result.returncode, 0)
                    parsed = json.loads(result.stdout.strip())
                    self.assertEqual(
                        parsed.get("decision"),
                        "reject",
                        f"Failed rejection in {env} for {cmd}",
                    )
                    self.assertEqual(
                        parsed.get("reason"),
                        "Destructive command rejected in headless/automated environment.",
                    )

    def test_safety_hook_headless_allows_safe(self):
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"command": "git status"},
            }
        }
        result = run_safety_hook(json.dumps(payload), env={"CI": "true"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_safety_hook_non_matching_tools(self):
        for tool_name in ["write_to_file", "view_file", "find_by_name"]:
            with self.subTest(tool_name=tool_name):
                payload = {
                    "toolCall": {
                        "name": tool_name,
                        "args": {"command": "rm -rf /"},
                    }
                }
                result = run_safety_hook(json.dumps(payload))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_safety_hook_invalid_json(self):
        result = run_safety_hook("invalid json payload {{}}")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.strip()), {})
        self.assertIn("JSON decode", result.stderr)

    def test_safety_hook_empty_stdin(self):
        result = run_safety_hook("")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.strip()), {})


if __name__ == "__main__":
    unittest.main()
