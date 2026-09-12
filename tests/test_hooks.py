import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = (
    REPO_ROOT / "skills" / "poteto-mode" / "scripts" / "hooks" / "post_tool_lint.py"
)
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


def run_safety_hook(
    stdin_data: str, env: dict | None = None
) -> subprocess.CompletedProcess:
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
        self.assertTrue(
            HOOK_SCRIPT.is_file(), f"Hook script does not exist at {HOOK_SCRIPT}"
        )

    def test_non_matching_tool(self):
        payload = {
            "toolCall": {
                "name": "view_file",
                "args": {
                    "AbsolutePath": str(REPO_ROOT / "README.md")
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
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
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

    def test_replace_file_content_never_formats(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            temp_py = Path(tmp_dir) / "sample_replace.py"
            temp_py.write_text("x=1;y=2\n", encoding="utf-8")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": str(temp_py),
                    },
                }
            }
            result = run_hook(json.dumps(payload))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout.strip()), {})
            self.assertEqual(temp_py.read_text(encoding="utf-8"), "x=1;y=2\n")

    def test_outside_workspace_ignored(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_py = Path(tmp_dir) / "outside.py"
            temp_py.write_text("x=1;y=2\n", encoding="utf-8")

            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(temp_py),
                    },
                }
            }
            result = run_hook(json.dumps(payload))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout.strip()), {})
            self.assertEqual(temp_py.read_text(encoding="utf-8"), "x=1;y=2\n")

    def test_json_excluded_from_formatting(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            temp_json = Path(tmp_dir) / "config.json"
            raw = '{\n  // keep comment\n  "foo": "bar"\n}\n'
            temp_json.write_text(raw, encoding="utf-8")

            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(temp_json),
                    },
                }
            }
            result = run_hook(json.dumps(payload))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout.strip()), {})
            self.assertEqual(temp_json.read_text(encoding="utf-8"), raw)

    def test_argument_aliases(self):
        aliases = ["TargetFile", "target_file", "AbsolutePath", "FilePath", "path"]
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            for idx, alias in enumerate(aliases):
                temp_py = Path(tmp_dir) / f"sample_{idx}.py"
                temp_py.write_text("a=10;b=20\n", encoding="utf-8")
                payload = {
                    "toolCall": {
                        "name": "write_to_file",
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
            'grep -ri "drop database" migrations/',
            "pytest -k test_drop_database",
            'git log --grep="drop database"',
            'cat test.sql | grep "drop database"',
            'find . -name "*.sql" -exec grep "drop database" {} +',
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
            "rm -rf /etc",
            "rm -rf /usr",
            "rm -rf /var",
            "rm -rf ~",
            "rm -rf $HOME",
            "git push --force origin main",
            "git push -f origin main",
            "git push origin main -f",
            "git push origin main --force",
            "git push --force",
            "git push -f origin",
            "git push origin -f",
            "git -C /tmp push -f origin main",
            "git -c user.name=bot push --force origin main",
            "git push origin --delete main",
            "git push origin --delete master",
            "git push origin :main",
            "git push origin :master",
            "git push origin :refs/heads/main",
            "git push origin +main",
            "git push +master",
            "git push origin +HEAD:main",
            "git push +refs/heads/main",
            'drop database "testdb"',
            "drop database `testdb`",
            "drop database testdb",
            "DROP DATABASE production",
            'psql -c "DROP DATABASE testdb"',
            'mysql -e "drop database testdb"',
            'echo "DROP DATABASE testdb" | psql',
            'bash -c "rm -rf /"',
            "sh -c 'git push --force origin main'",
            'zsh -c "rm -rf /etc"',
            'eval "rm -rf /"',
            "bash -c 'psql -c \"DROP DATABASE prod\"'",
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
            "rm -rf /etc",
            "git push origin main -f",
            "git push --force",
            'bash -c "rm -rf /"',
            'drop database "testdb"',
            'psql -c "DROP DATABASE prod"',
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
        safe_commands = [
            "git status",
            'grep -ri "drop database" .',
            "pytest -k test_drop_database",
        ]
        for cmd in safe_commands:
            payload = {
                "toolCall": {
                    "name": "run_command",
                    "args": {"command": cmd},
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


DELEGATION_HOOK_SCRIPT = (
    REPO_ROOT / "skills" / "poteto-mode" / "scripts" / "hooks" / "pre_tool_delegation.py"
)


def run_delegation_hook(
    stdin_data: str, env: dict | None = None
) -> subprocess.CompletedProcess:
    run_env = os.environ.copy()
    run_env.pop("NON_INTERACTIVE", None)
    run_env.pop("CI", None)
    run_env.pop("CLOUD_RUN_TASK_INDEX", None)
    run_env.pop("SUBAGENT", None)
    run_env.pop("IS_SUBAGENT", None)
    run_env.pop("ANTIGRAVITY_SUBAGENT_ID", None)
    run_env.pop("HEADLESS_NO_SUBAGENTS", None)
    run_env.pop("ALLOW_SUBAGENTS", None)
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(DELEGATION_HOOK_SCRIPT)],
        input=stdin_data,
        capture_output=True,
        text=True,
        check=False,
        env=run_env,
    )


class TestPreToolDelegationHook(unittest.TestCase):
    def test_delegation_hook_script_exists(self):
        self.assertTrue(
            DELEGATION_HOOK_SCRIPT.is_file(),
            f"Delegation hook script does not exist at {DELEGATION_HOOK_SCRIPT}",
        )

    def test_markdown_files_allowed(self):
        large_markdown = "# Markdown Title\n" + "\n".join(
            f"- Item {i}" for i in range(25)
        )
        for ext in [".md", ".markdown"]:
            for tool in ["write_to_file", "replace_file_content"]:
                with self.subTest(ext=ext, tool=tool):
                    payload = {
                        "toolCall": {
                            "name": tool,
                            "args": {
                                "TargetFile": f"docs/spec{ext}",
                                "CodeContent": large_markdown,
                            },
                        }
                    }
                    result = run_delegation_hook(json.dumps(payload))
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_scratch_and_slices_files_allowed(self):
        large_code = "\n".join(f"x_{i} = {i}" for i in range(25))
        scratch_paths = [
            "scratch/test_script.py",
            ".slices/slice_1.py",
            "receipts/summary.txt",
        ]
        for path in scratch_paths:
            with self.subTest(path=path):
                payload = {
                    "toolCall": {
                        "name": "write_to_file",
                        "args": {
                            "TargetFile": path,
                            "CodeContent": large_code,
                        },
                    }
                }
                result = run_delegation_hook(json.dumps(payload))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_scratch_path_isolation_no_false_positive(self):
        large_code = "\n".join(f"x_{i} = {i}" for i in range(25))
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "/some/project_scratch/file.py",
                    "CodeContent": large_code,
                },
            }
        }
        result = run_delegation_hook(json.dumps(payload))
        self.assertEqual(result.returncode, 0)
        parsed = json.loads(result.stdout.strip())
        self.assertEqual(parsed.get("decision"), "force_ask")

    def test_permitted_special_files(self):
        large_content = "\n".join(f"line_{i}" for i in range(25))
        special_files = [".gitignore", "score.json", "results.tsv"]
        for f in special_files:
            with self.subTest(file=f):
                payload = {
                    "toolCall": {
                        "name": "write_to_file",
                        "args": {
                            "TargetFile": f,
                            "CodeContent": large_content,
                        },
                    }
                }
                result = run_delegation_hook(json.dumps(payload))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_replace_file_content_large_target_content_flagged(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            existing_file = Path(tmp_dir) / "target_mod.py"
            existing_file.write_text("orig\n", encoding="utf-8")
            large_target_content = "\n".join(f"line_{i} = {i}" for i in range(60))
            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": str(existing_file),
                        "ReplacementContent": "single_line = 1\n",
                        "TargetContent": large_target_content,
                    },
                }
            }
            result = run_delegation_hook(json.dumps(payload))
            self.assertEqual(result.returncode, 0)
            parsed = json.loads(result.stdout.strip())
            self.assertEqual(parsed.get("decision"), "force_ask")

    def test_trivial_edits_allowed(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            existing_file = Path(tmp_dir) / "mod.py"
            existing_file.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")

            for lines_count in [1, 2, 3, 25, 50]:
                content = "\n".join(f"val_{i} = {i}" for i in range(lines_count))
                with self.subTest(lines_count=lines_count):
                    payload = {
                        "toolCall": {
                            "name": "replace_file_content",
                            "args": {
                                "TargetFile": str(existing_file),
                                "ReplacementContent": content,
                            },
                        }
                    }
                    result = run_delegation_hook(json.dumps(payload))
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_nontrivial_code_edits_interactive_force_ask(self):
        large_code = "\n".join(f"def func_{i}(): pass" for i in range(60))
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            existing_file = Path(tmp_dir) / "existing.py"
            existing_file.write_text("def base(): pass\n", encoding="utf-8")
            new_file = Path(tmp_dir) / "brand_new.py"

            payload_new = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(new_file),
                        "CodeContent": "def a(): pass\ndef b(): pass\ndef c(): pass\ndef d(): pass\n",
                    },
                }
            }
            res_new = run_delegation_hook(json.dumps(payload_new))
            self.assertEqual(res_new.returncode, 0)
            parsed_new = json.loads(res_new.stdout.strip())
            self.assertEqual(parsed_new.get("decision"), "force_ask")
            self.assertIn(
                "Coordinator Code Delegation Invariant", parsed_new.get("reason", "")
            )

            payload_replace = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": str(existing_file),
                        "ReplacementContent": large_code,
                    },
                }
            }
            res_rep = run_delegation_hook(json.dumps(payload_replace))
            self.assertEqual(res_rep.returncode, 0)
            parsed_rep = json.loads(res_rep.stdout.strip())
            self.assertEqual(parsed_rep.get("decision"), "force_ask")
            self.assertIn(
                "Coordinator Code Delegation Invariant", parsed_rep.get("reason", "")
            )

    def test_nontrivial_code_edits_headless_reject(self):
        large_code = "\n".join(f"var_{i} = {i}" for i in range(60))
        headless_envs = [
            {"NON_INTERACTIVE": "1"},
            {"CI": "1"},
            {"CI": "true"},
        ]
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            target_py = Path(tmp_dir) / "feature.py"
            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(target_py),
                        "CodeContent": large_code,
                    },
                }
            }
            for env in headless_envs:
                with self.subTest(env=env):
                    result = run_delegation_hook(json.dumps(payload), env=env)
                    self.assertEqual(result.returncode, 0)
                    parsed = json.loads(result.stdout.strip())
                    self.assertEqual(parsed.get("decision"), "reject")
                    self.assertIn(
                        "Coordinator Code Delegation Invariant",
                        parsed.get("reason", ""),
                    )

    def test_forty_five_line_helper_replacement_allowed(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            existing_file = Path(tmp_dir) / "helper.py"
            existing_file.write_text("def helper():\n    pass\n", encoding="utf-8")
            helper_replacement = "\n".join(f"    line_{i} = {i}" for i in range(45))
            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": str(existing_file),
                        "ReplacementContent": f"def helper():\n{helper_replacement}\n",
                    },
                }
            }
            result = run_delegation_hook(json.dumps(payload))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_cloud_run_task_permits_writes(self):
        large_code = "\n".join(f"var_{i} = {i}" for i in range(25))
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            target_py = Path(tmp_dir) / "cloud_task_file.py"
            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(target_py),
                        "CodeContent": large_code,
                    },
                }
            }
            result = run_delegation_hook(
                json.dumps(payload), env={"CLOUD_RUN_TASK_INDEX": "0"}
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_coordinator_prompt_does_not_bypass(self):
        large_code = "\n".join(f"var_{i} = {i}" for i in range(25))
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            target_py = Path(tmp_dir) / "feature_code.py"
            transcript_file = Path(tmp_dir) / "coordinator_transcript.jsonl"
            first_msg = {
                "step_index": 0,
                "content": "You are an engineer tasked with implementing the feature.\nYour task is to refactor the auth system.",
            }
            transcript_file.write_text(json.dumps(first_msg) + "\n", encoding="utf-8")

            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(target_py),
                        "CodeContent": large_code,
                    },
                },
                "transcriptPath": str(transcript_file),
            }
            result = run_delegation_hook(json.dumps(payload))
            self.assertEqual(result.returncode, 0)
            parsed = json.loads(result.stdout.strip())
            self.assertEqual(parsed.get("decision"), "force_ask")

    def test_subagent_env_bypass(self):
        large_code = "\n".join(f"var_{i} = {i}" for i in range(25))
        subagent_envs = [
            {"SUBAGENT": "1"},
            {"IS_SUBAGENT": "1"},
            {"ANTIGRAVITY_SUBAGENT_ID": "agent-xyz-987"},
        ]
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            target_py = Path(tmp_dir) / "subagent_work.py"
            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(target_py),
                        "CodeContent": large_code,
                    },
                }
            }
            for env in subagent_envs:
                with self.subTest(env=env):
                    result = run_delegation_hook(json.dumps(payload), env=env)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_subagent_transcript_bypass(self):
        large_code = "\n".join(f"var_{i} = {i}" for i in range(25))
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            target_py = Path(tmp_dir) / "subagent_file.py"
            transcript_file = Path(tmp_dir) / "transcript.jsonl"
            first_msg = {
                "step_index": 0,
                "content": "poteto-agent, surgical code implementation delegate.\nTask is to write code.",
            }
            transcript_file.write_text(json.dumps(first_msg) + "\n", encoding="utf-8")

            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(target_py),
                        "CodeContent": large_code,
                    },
                },
                "transcriptPath": str(transcript_file),
            }
            result = run_delegation_hook(json.dumps(payload))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_headless_bypass_when_subagents_disabled(self):
        large_code = "\n".join(f"var_{i} = {i}" for i in range(25))
        bypass_envs = [
            {"NON_INTERACTIVE": "1", "HEADLESS_NO_SUBAGENTS": "1"},
            {"CI": "true", "ALLOW_SUBAGENTS": "0"},
            {"NON_INTERACTIVE": "1", "ALLOW_SUBAGENTS": "false"},
        ]
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            target_py = Path(tmp_dir) / "headless_code.py"
            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(target_py),
                        "CodeContent": large_code,
                    },
                }
            }
            for env in bypass_envs:
                with self.subTest(env=env):
                    result = run_delegation_hook(json.dumps(payload), env=env)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_empty_and_invalid_json(self):
        for invalid_input in ["", "   \n", "invalid json {{}}", '{"unclosed": ']:
            with self.subTest(invalid_input=invalid_input):
                result = run_delegation_hook(invalid_input)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_non_matching_tool(self):
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"command": "echo test"},
            }
        }
        result = run_delegation_hook(json.dumps(payload))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_argument_aliases(self):
        aliases = ["TargetFile", "target_file", "AbsolutePath", "FilePath", "path"]
        for alias in aliases:
            with self.subTest(alias=alias):
                payload = {
                    "toolCall": {
                        "name": "write_to_file",
                        "args": {
                            alias: "scratch/test.py",
                            "CodeContent": "print('hello')",
                        },
                    }
                }
                result = run_delegation_hook(json.dumps(payload))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout.strip()), {})


if __name__ == "__main__":
    unittest.main()
