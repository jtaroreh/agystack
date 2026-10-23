import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "swarm" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "setup-agystack" / "scripts"))

import cloud_worker
import setup_runtime
from cloud_worker import (
    emit_thought,
    emit_tool_invocation,
    emit_tool_result,
    execute_deepseek_model_agent,
    execute_partner_model_agent,
    execute_task,
    execute_workspace_tool,
    is_deepseek_model,
    is_partner_model,
    measure_partner_client_startup,
    resolve_worker_model,
)
from setup_runtime import check_model_garden


class TestVertexPartnerModelResolution(unittest.TestCase):
    def test_alias_resolution_sonnet(self):
        aliases = [
            "claude-3-5-sonnet-v2@20241022",
            "claude-3-5-sonnet-v2@20241022",
            "sonnet-5.5",
            "sonnet-5-5",
            "publishers/anthropic/models/claude-3-5-sonnet-v2@20241022",
        ]
        for alias in aliases:
            resolved = resolve_worker_model(alias)
            self.assertEqual(resolved, "claude-3-5-sonnet-v2@20241022")
            self.assertTrue(is_partner_model(resolved))

    def test_alias_resolution_opus(self):
        aliases = [
            "claude-3-opus@20240229",
            "claude-3-opus@20240229",
            "opus-5.5",
            "opus-5-5",
            "publishers/anthropic/models/claude-3-opus@20240229",
        ]
        for alias in aliases:
            resolved = resolve_worker_model(alias)
            self.assertEqual(resolved, "claude-3-opus@20240229")
            self.assertTrue(is_partner_model(resolved))

    def test_alias_resolution_fable(self):
        aliases = [
            "fable-5-1",
            "fable-5.1",
            "publishers/fable/models/fable-5-1",
            "publishers/fable/models/fable-5.1",
        ]
        for alias in aliases:
            resolved = resolve_worker_model(alias)
            self.assertEqual(resolved, "fable-5-1")
            self.assertTrue(is_partner_model(resolved))

    def test_alias_resolution_deepseek(self):
        aliases = [
            "deepseek",
            "deepseek-flash",
            "deepseek-4.1",
            "deepseek-v4.1",
            "deepseek-4.1-flash",
            "deepseek-v4.1-flash-maas",
            "deepseek-v4.1-flash-maas@001",
            "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas",
        ]
        canonical = "publishers/deepseek-ai/models/deepseek-v4.1-flash-maas"
        for alias in aliases:
            resolved = resolve_worker_model(alias)
            self.assertEqual(resolved, canonical)
            self.assertTrue(is_deepseek_model(resolved))
            self.assertFalse(is_partner_model(resolved))

    def test_gemini_models_are_not_partner_models(self):
        gemini_models = [
            "gemini-3.8-flash",
            "gemini-3.1-pro",
            "gemini-3.1-flash-lite",
            "gemini-4-argon",
            "argon",
            "flash",
            "pro",
        ]
        for model in gemini_models:
            resolved = resolve_worker_model(model)
            self.assertFalse(is_partner_model(resolved))

    def test_task_item_model_override(self):
        task_item = {"model": "sonnet-5.5"}
        resolved = resolve_worker_model(task_item=task_item)
        self.assertEqual(resolved, "claude-3-5-sonnet-v2@20241022")
        self.assertTrue(is_partner_model(resolved))


class TestVertexPartnerExecution(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        subprocess.run(["git", "init"], cwd=self.repo_dir, check=True, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_sdk_fallback_blocked(self):
        with patch.dict(sys.modules, {"anthropic": None}):
            status, summary = execute_task(
                task_item={"model": "claude-3-5-sonnet-v2@20241022"},
                task_brief="Implement task",
                repo_dir=self.repo_dir,
                model_override="claude-3-5-sonnet-v2@20241022",
                api_key="",
            )
            self.assertEqual(status, "BLOCKED")
            self.assertEqual(
                summary,
                "Missing dependency: anthropic[vertex] Python package is not installed.",
            )

    def test_adc_project_and_region_pass_through(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "[STATUS: PASS] Work verified."
        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.AnthropicVertex.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            status, summary = execute_task(
                task_item={"model": "claude-3-5-sonnet-v2@20241022"},
                task_brief="Implement task",
                repo_dir=self.repo_dir,
                model_override="claude-3-5-sonnet-v2@20241022",
                api_key="",
                project="custom-prod-project",
                location="europe-west1",
            )
            self.assertEqual(status, "PASS")
            mock_anthropic.AnthropicVertex.assert_called_once_with(
                project_id="custom-prod-project",
                region="europe-west1",
            )

    def test_adc_env_var_precedence_and_us_central1_fallback(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "[STATUS: PASS] Success."
        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.AnthropicVertex.return_value = mock_client

        env = {
            "GCP_PROJECT": "env-gcp-project",
            "REGION": "",
            "VERTEXAI_LOCATION": "",
            "GCP_REGION": "",
        }
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}), patch.dict(os.environ, env):
            status, _ = execute_task(
                task_item={"model": "claude-3-opus@20240229"},
                task_brief="Implement task",
                repo_dir=self.repo_dir,
                model_override="claude-3-opus@20240229",
                api_key="",
            )
            self.assertEqual(status, "PASS")
            mock_anthropic.AnthropicVertex.assert_called_once_with(
                project_id="env-gcp-project",
                region="us-central1",
            )

    def test_missing_aiplatform_fallback_blocked_for_fable(self):
        with patch.dict(sys.modules, {"google.cloud.aiplatform": None}):
            status, summary = execute_task(
                task_item={"model": "fable-5-1"},
                task_brief="Implement fable task",
                repo_dir=self.repo_dir,
                model_override="fable-5-1",
                api_key="",
            )
            self.assertEqual(status, "BLOCKED")
            self.assertEqual(
                summary,
                "Missing dependency: google-cloud-aiplatform Python package is not installed.",
            )

    def test_missing_genai_fallback_blocked_for_deepseek(self):
        with patch.dict(sys.modules, {"google.genai": None}):
            status, summary = execute_task(
                task_item={"model": "deepseek"},
                task_brief="Implement deepseek task",
                repo_dir=self.repo_dir,
                model_override="deepseek",
                api_key="",
            )
            self.assertEqual(status, "BLOCKED")
            self.assertEqual(
                summary,
                "Missing dependency: google-genai Python package is not installed.",
            )

    def test_milestone_emission_partner_model(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "[STATUS: PASS] Done."
        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.AnthropicVertex.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}), patch(
            "cloud_worker.emit_milestone"
        ) as mock_milestone:
            status, _ = execute_task(
                task_item={"model": "claude-3-5-sonnet-v2@20241022"},
                task_brief="Execute brief",
                repo_dir=self.repo_dir,
                model_override="claude-3-5-sonnet-v2@20241022",
                api_key="",
                task_index=2,
            )
            self.assertEqual(status, "PASS")
            mock_milestone.assert_called_with(
                2, "RUNNING_AGENT", "Vertex Model Garden agent (claude-3-5-sonnet-v2@20241022)"
            )

    def test_milestone_emission_fable_model(self):
        mock_aiplatform = MagicMock()
        mock_endpoint = MagicMock()
        mock_resp = MagicMock()
        mock_resp.predictions = ["[STATUS: PASS] Done."]
        mock_endpoint.predict.return_value = mock_resp
        mock_aiplatform.Endpoint.return_value = mock_endpoint

        with patch.dict(sys.modules, {"google.cloud.aiplatform": mock_aiplatform}), patch(
            "cloud_worker.emit_milestone"
        ) as mock_milestone:
            status, _ = execute_task(
                task_item={"model": "fable-5-1"},
                task_brief="Execute brief",
                repo_dir=self.repo_dir,
                model_override="fable-5-1",
                api_key="",
                task_index=2,
            )
            self.assertEqual(status, "PASS")
            mock_milestone.assert_called_with(
                2, "RUNNING_AGENT", "Vertex Model Garden agent (fable-5-1)"
            )

    def test_milestone_emission_deepseek_model(self):
        mock_genai = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "[STATUS: PASS] DeepSeek done."
        mock_resp.function_calls = []
        mock_resp.candidates = [
            MagicMock(
                content=MagicMock(
                    parts=[
                        MagicMock(
                            text="[STATUS: PASS] DeepSeek done.",
                            thought=None,
                            function_call=None,
                        )
                    ]
                )
            )
        ]
        mock_client.models.generate_content.return_value = mock_resp
        mock_genai.Client.return_value = mock_client

        with patch.dict(sys.modules, {"google.genai": mock_genai}), patch(
            "cloud_worker.emit_milestone"
        ) as mock_milestone:
            status, _ = execute_task(
                task_item={"model": "deepseek"},
                task_brief="Execute brief",
                repo_dir=self.repo_dir,
                model_override="deepseek",
                api_key="",
                task_index=2,
            )
            self.assertEqual(status, "PASS")
            mock_milestone.assert_called_with(
                2,
                "RUNNING_AGENT",
                "Vertex Model Garden agent (publishers/deepseek-ai/models/deepseek-v4.1-flash-maas)",
            )

    def test_autonomous_tool_calling_loop_writes_files_and_passes(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()

        block_think = MagicMock()
        block_think.type = "thinking"
        block_think.thinking = "I need to write solution.py"

        block_tool1 = MagicMock()
        block_tool1.type = "tool_use"
        block_tool1.id = "call_write_1"
        block_tool1.name = "write_file"
        block_tool1.input = {"path": "solution.py", "content": "def solve(): return 42\n"}

        resp0 = MagicMock()
        resp0.content = [block_think, block_tool1]

        block_tool2 = MagicMock()
        block_tool2.type = "tool_use"
        block_tool2.id = "call_cmd_2"
        block_tool2.name = "run_command"
        block_tool2.input = {"command": "python3 -c 'import solution; assert solution.solve() == 42'"}

        resp1 = MagicMock()
        resp1.content = [block_tool2]

        block_final = MagicMock()
        block_final.text = "[STATUS: PASS] Solution implemented and tests pass."

        resp2 = MagicMock()
        resp2.content = [block_final]

        mock_client.messages.create.side_effect = [resp0, resp1, resp2]
        mock_anthropic.AnthropicVertex.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}), patch(
            "cloud_worker.emit_thought"
        ) as mock_thought, patch("cloud_worker.emit_tool_invocation") as mock_inv, patch(
            "cloud_worker.emit_tool_result"
        ) as mock_res:
            status, summary = execute_task(
                task_item={"model": "claude-3-5-sonnet-v2@20241022"},
                task_brief="Implement solve in solution.py",
                repo_dir=self.repo_dir,
                model_override="claude-3-5-sonnet-v2@20241022",
                api_key="",
                task_index=1,
            )
            self.assertEqual(status, "PASS")
            self.assertIn("Solution implemented and tests pass.", summary)

            solution_file = self.repo_dir / "solution.py"
            self.assertTrue(solution_file.is_file())
            self.assertEqual(solution_file.read_text(encoding="utf-8"), "def solve(): return 42\n")

            git_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("solution.py", git_res.stdout)

            mock_thought.assert_called_once_with(1, "I need to write solution.py")
            self.assertEqual(mock_inv.call_count, 2)
            mock_inv.assert_any_call(1, "write_file", {"path": "solution.py", "content": "def solve(): return 42\n"})
            mock_inv.assert_any_call(1, "run_command", {"command": "python3 -c 'import solution; assert solution.solve() == 42'"})
            self.assertEqual(mock_res.call_count, 2)

    def test_autonomous_tool_calling_loop_deepseek(self):
        mock_genai = MagicMock()
        mock_client = MagicMock()

        def fake_content(role=None, parts=None):
            c = MagicMock()
            c.role = role
            c.parts = parts
            return c
        mock_genai.types.Content.side_effect = fake_content

        # Turn 0: DeepSeek emits a thought and calls write_file
        fc1 = MagicMock()
        fc1.name = "write_file"
        fc1.args = {"path": "deepseek_solution.py", "content": "def deepseek_fn(): return 100\n"}

        part_think = MagicMock()
        part_think.thought = "Thinking about deepseek solution"
        part_think.text = "<think>Thinking about deepseek solution</think>"
        part_think.function_call = None

        part_call1 = MagicMock()
        part_call1.thought = None
        part_call1.text = None
        part_call1.function_call = fc1

        resp0 = MagicMock()
        resp0.function_calls = [fc1]
        cand0 = MagicMock()
        cand0.content = MagicMock(parts=[part_think, part_call1])
        resp0.candidates = [cand0]

        # Turn 1: DeepSeek finishes with PASS
        part_final = MagicMock()
        part_final.thought = None
        part_final.text = "[STATUS: PASS] DeepSeek solution implemented."
        part_final.function_call = None

        resp1 = MagicMock()
        resp1.function_calls = []
        cand1 = MagicMock()
        cand1.content = MagicMock(parts=[part_final])
        resp1.candidates = [cand1]
        resp1.text = "[STATUS: PASS] DeepSeek solution implemented."

        mock_client.models.generate_content.side_effect = [resp0, resp1]
        mock_genai.Client.return_value = mock_client

        with patch.dict(sys.modules, {"google.genai": mock_genai}), patch(
            "cloud_worker.emit_thought"
        ) as mock_thought, patch("cloud_worker.emit_tool_invocation") as mock_inv, patch(
            "cloud_worker.emit_tool_result"
        ) as mock_res:
            status, summary = execute_task(
                task_item={"model": "deepseek-v4.1-flash"},
                task_brief="Implement deepseek solution",
                repo_dir=self.repo_dir,
                model_override="deepseek-v4.1-flash",
                api_key="",
                task_index=2,
            )
            self.assertEqual(status, "PASS")
            self.assertIn("DeepSeek solution implemented.", summary)

            solution_file = self.repo_dir / "deepseek_solution.py"
            self.assertTrue(solution_file.is_file())
            self.assertEqual(
                solution_file.read_text(encoding="utf-8"), "def deepseek_fn(): return 100\n"
            )

            mock_thought.assert_called_with(2, "Thinking about deepseek solution")
            mock_inv.assert_called_once_with(
                2,
                "write_file",
                {"path": "deepseek_solution.py", "content": "def deepseek_fn(): return 100\n"},
            )
            self.assertEqual(mock_res.call_count, 1)

            # Verify that the turn sent to generate_content used role="model" (not "assistant")
            second_call_contents = mock_client.models.generate_content.call_args_list[1][1]["contents"]
            self.assertEqual(second_call_contents[1].role, "model")

    def test_autonomous_tool_calling_loop_edit_and_read_file(self):
        readme = self.repo_dir / "README.md"
        readme.write_text("Hello World\n", encoding="utf-8")

        mock_anthropic = MagicMock()
        mock_client = MagicMock()

        block_read = MagicMock()
        block_read.type = "tool_use"
        block_read.id = "call_read"
        block_read.name = "read_file"
        block_read.input = {"path": "README.md"}
        resp0 = MagicMock()
        resp0.content = [block_read]

        block_edit = MagicMock()
        block_edit.type = "tool_use"
        block_edit.id = "call_edit"
        block_edit.name = "edit_file"
        block_edit.input = {"path": "README.md", "target": "World", "replacement": "Agystack"}
        resp1 = MagicMock()
        resp1.content = [block_edit]

        block_final = MagicMock()
        block_final.text = "[STATUS: PASS] Readme edited."
        resp2 = MagicMock()
        resp2.content = [block_final]

        mock_client.messages.create.side_effect = [resp0, resp1, resp2]
        mock_anthropic.AnthropicVertex.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            status, _ = execute_task(
                task_item={"model": "claude-3-opus@20240229"},
                task_brief="Update README",
                repo_dir=self.repo_dir,
                model_override="claude-3-opus@20240229",
                api_key="",
                task_index=0,
            )
            self.assertEqual(status, "PASS")
            self.assertEqual(readme.read_text(encoding="utf-8"), "Hello Agystack\n")

    def test_workspace_tool_path_traversal_prevention(self):
        res_read = execute_workspace_tool("read_file", {"path": "../../etc/passwd"}, self.repo_dir)
        self.assertIn("outside repository directory", res_read)

        res_write = execute_workspace_tool("write_file", {"path": "../evil.py", "content": "bad"}, self.repo_dir)
        self.assertIn("outside repository directory", res_write)

        res_edit = execute_workspace_tool("edit_file", {"path": "../evil.py", "target": "a", "replacement": "b"}, self.repo_dir)
        self.assertIn("outside repository directory", res_edit)


class TestMixedManifestRouting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        subprocess.run(["git", "init"], cwd=self.repo_dir, check=True, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_mixed_manifest_picks_correct_client(self):
        mock_ag = MagicMock()
        mock_config = MagicMock()
        mock_ag.LocalAgentConfig = mock_config
        mock_ag.CapabilitiesConfig = MagicMock()
        mock_ag.policy.allow_all = MagicMock()
        mock_agent_instance = MagicMock()
        mock_ag_resp = MagicMock()
        mock_ag_resp.text = AsyncMock(return_value="[STATUS: PASS] Gemini agent done")
        mock_agent_instance.chat = AsyncMock(return_value=mock_ag_resp)
        mock_agent_cm = MagicMock()
        mock_agent_cm.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_cm.__aexit__ = AsyncMock(return_value=None)
        mock_ag.Agent = MagicMock(return_value=mock_agent_cm)

        mock_anthropic = MagicMock()
        mock_claude_client = MagicMock()
        mock_claude_resp = MagicMock()
        mock_claude_block = MagicMock()
        mock_claude_block.text = "[STATUS: PASS] Claude agent done"
        mock_claude_resp.content = [mock_claude_block]
        mock_claude_client.messages.create.return_value = mock_claude_resp
        mock_anthropic.AnthropicVertex.return_value = mock_claude_client

        mock_aiplatform = MagicMock()
        mock_fable_endpoint = MagicMock()
        mock_fable_resp = MagicMock()
        mock_fable_resp.predictions = ["[STATUS: PASS] Fable agent done"]
        mock_fable_endpoint.predict.return_value = mock_fable_resp
        mock_aiplatform.Endpoint.return_value = mock_fable_endpoint

        modules_patch = {
            "google": MagicMock(),
            "google.antigravity": mock_ag,
            "anthropic": mock_anthropic,
            "google.cloud.aiplatform": mock_aiplatform,
        }

        manifest_tasks = [
            {"model": "gemini-3.8-flash", "brief": "Gemini subtask"},
            {"model": "claude-3-5-sonnet-v2@20241022", "brief": "Claude subtask"},
            {"model": "fable-5-1", "brief": "Fable subtask"},
        ]

        with patch.dict(sys.modules, modules_patch), patch("cloud_worker.emit_milestone") as mock_milestone:
            # Task 0: Gemini
            st0, out0 = execute_task(
                task_item=manifest_tasks[0],
                task_brief=manifest_tasks[0]["brief"],
                repo_dir=self.repo_dir,
                model_override="flash",
                api_key="test-key",
                task_index=0,
            )
            self.assertEqual(st0, "PASS")
            mock_ag.Agent.assert_called_once()
            mock_anthropic.AnthropicVertex.assert_not_called()
            mock_aiplatform.Endpoint.assert_not_called()
            mock_milestone.assert_any_call(0, "RUNNING_AGENT", "Antigravity SDK agent (gemini-3.8-flash)")

            # Task 1: Claude 5.5 Sonnet
            st1, out1 = execute_task(
                task_item=manifest_tasks[1],
                task_brief=manifest_tasks[1]["brief"],
                repo_dir=self.repo_dir,
                model_override="",
                api_key="",
                task_index=1,
            )
            self.assertEqual(st1, "PASS")
            mock_anthropic.AnthropicVertex.assert_called_once()
            mock_aiplatform.Endpoint.assert_not_called()
            mock_milestone.assert_any_call(1, "RUNNING_AGENT", "Vertex Model Garden agent (claude-3-5-sonnet-v2@20241022)")

            # Task 2: Fable 5.1
            st2, out2 = execute_task(
                task_item=manifest_tasks[2],
                task_brief=manifest_tasks[2]["brief"],
                repo_dir=self.repo_dir,
                model_override="",
                api_key="",
                task_index=2,
            )
            self.assertEqual(st2, "PASS")
            self.assertEqual(mock_anthropic.AnthropicVertex.call_count, 1)
            mock_aiplatform.init.assert_called_once()
            mock_aiplatform.Endpoint.assert_called_once_with(endpoint_name="fable-5-1")
            mock_fable_endpoint.predict.assert_called_once()
            mock_milestone.assert_any_call(2, "RUNNING_AGENT", "Vertex Model Garden agent (fable-5-1)")


class TestModelGardenPreflightProbe(unittest.TestCase):
    def test_missing_project_fails(self):
        result = check_model_garden(project_id="", import_fn=lambda name: MagicMock())
        self.assertFalse(result["ok"])
        self.assertIn("No active GCP project", result["error"])

    def test_missing_anthropic_succeeds_with_note(self):
        def fake_import(name):
            if name == "anthropic":
                raise ImportError("No module named 'anthropic'")
            return MagicMock()

        mock_run_cmd = MagicMock(return_value=MagicMock(returncode=0, stdout="Listed 0 items.", stderr=""))
        result = check_model_garden(project_id="test-project", run_cmd_fn=mock_run_cmd, import_fn=fake_import)
        self.assertTrue(result["ok"])
        self.assertFalse(result["anthropic_installed"])
        self.assertEqual(
            result["partner_models_note"],
            "Optional package 'anthropic[vertex]' not installed for Claude partner models.",
        )
        self.assertTrue(result["model_garden_verified"])

    def test_worker_task_manifest_deepseek_enables_vertex_and_global_location(self):
        mock_genai = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "[STATUS: PASS] DeepSeek task done"
        mock_resp.function_calls = []
        mock_resp.candidates = []
        mock_client.models.generate_content.return_value = mock_resp
        mock_genai.Client.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(sys.modules, {"google.genai": mock_genai}):
            repo_dir = Path(tmp_dir)
            task_item = {"brief": "optimize", "model": "deepseek-v4.1-flash"}
            status, summary = execute_task(
                task_item=task_item,
                task_brief="optimize",
                repo_dir=repo_dir,
                model_override="",
                api_key="",
                use_vertex=True,
                location="us-central1",
                task_index=0,
            )
            self.assertEqual(status, "PASS")
            mock_genai.Client.assert_called_once()
            call_kwargs = mock_genai.Client.call_args[1]
            self.assertTrue(call_kwargs.get("vertexai"))
            self.assertEqual(call_kwargs.get("location"), "global")

    def test_successful_probe(self):
        mock_mod = MagicMock()
        mock_mod.AnthropicVertex = MagicMock()
        mock_run_cmd = MagicMock(return_value=MagicMock(returncode=0, stdout="Listed 0 items.", stderr=""))

        result = check_model_garden(
            project_id="test-project",
            region="us-central1",
            run_cmd_fn=mock_run_cmd,
            import_fn=lambda name: mock_mod,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["anthropic_installed"])
        self.assertTrue(result["model_garden_verified"])
        self.assertEqual(result["project_id"], "test-project")
        self.assertEqual(result["region"], "us-central1")
        self.assertIn("gemini-4-argon", result["serverless_models"])
        self.assertIn("deepseek-v4.1-flash-maas", result["serverless_models"])
        self.assertIn("claude-3-5-sonnet-v2@20241022", result["partner_models"])
        self.assertIn("claude-3-opus@20240229", result["partner_models"])
        self.assertIn("fable-5-1", result["partner_models"])
        mock_mod.AnthropicVertex.assert_called_once_with(
            project_id="test-project",
            region="us-central1",
        )
        mock_run_cmd.assert_called_once_with(
            ["gcloud", "ai", "models", "list", "--project=test-project", "--region=us-central1", "--limit=1"],
            check=False,
        )

    def test_client_init_error_fails(self):
        mock_mod = MagicMock()
        mock_mod.AnthropicVertex.side_effect = RuntimeError("ADC credentials expired")

        result = check_model_garden(
            project_id="test-project",
            import_fn=lambda name: mock_mod,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["anthropic_installed"])
        self.assertIn("ADC credentials expired", result["error"])

    def test_probe_iam_failure(self):
        mock_mod = MagicMock()
        mock_run_cmd = MagicMock(return_value=MagicMock(
            returncode=1,
            stdout="",
            stderr="ERROR: (gcloud.ai.models.list) User does not have permission aiplatform.models.list on resource",
        ))
        result = check_model_garden(
            project_id="test-project",
            run_cmd_fn=mock_run_cmd,
            import_fn=lambda name: mock_mod,
        )
        self.assertFalse(result["ok"])
        self.assertIn("Model Garden API check failed", result["error"])
        self.assertIn("permission", result["error"])

    def test_probe_network_or_credential_exception(self):
        mock_mod = MagicMock()
        mock_run_cmd = MagicMock(side_effect=OSError("Network unreachable"))
        result = check_model_garden(
            project_id="test-project",
            run_cmd_fn=mock_run_cmd,
            import_fn=lambda name: mock_mod,
        )
        self.assertFalse(result["ok"])
        self.assertIn("Model Garden API check exception", result["error"])
        self.assertIn("Network unreachable", result["error"])

    def test_cli_check_model_garden(self):
        cmd = [
            sys.executable,
            str(REPO_ROOT / "skills" / "setup-agystack" / "scripts" / "setup_runtime.py"),
            "--check-model-garden",
            "--project=cli-test-project",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertIn("cli-test-project", res.stdout)
        data = json.loads(res.stdout.strip())
        self.assertEqual(data["project_id"], "cli-test-project")


class TestZeroPushAndPatchHarvesting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        subprocess.run(["git", "init"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Worker Bot"],
            cwd=self.repo_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "worker@example.com"],
            cwd=self.repo_dir,
            check=True,
            capture_output=True,
        )

        init_file = self.repo_dir / "service.py"
        init_file.write_text("def run():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "service.py"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo_dir, check=True, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()
        self.storage_dir.cleanup()

    def test_zero_push_and_patch_diff_harvesting(self):
        import storage_uploader

        service_file = self.repo_dir / "service.py"
        service_file.write_text("def run():\n    return 2\n", encoding="utf-8")

        bucket_name = "test-results-bucket"
        session_id = "test-session-zero-push"
        env = {
            "STORAGE_MESSENGER_LOCAL_DIR": self.storage_dir.name,
            "GCS_BUCKET": bucket_name,
            "SWARM_SESSION_ID": session_id,
        }

        with patch.dict(os.environ, env):
            subprocess.run(["git", "add", "service.py"], cwd=self.repo_dir, check=True)
            subprocess.run(["git", "commit", "-m", "worker commit"], cwd=self.repo_dir, check=True)
            commit_res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            commit_sha = commit_res.stdout.strip()

            uris = storage_uploader.upload_run_artifacts(
                bucket_name=bucket_name,
                prefix=f"swarms/{session_id}",
                repo_dir=self.repo_dir,
                task_index=0,
                status="PASS",
                candidate_files=["service.py"],
                commit_sha=commit_sha,
            )

            self.assertIn("patch.diff", uris)
            diff_file = (
                Path(self.storage_dir.name)
                / bucket_name
                / "swarms"
                / session_id
                / "task-0"
                / "patch.diff"
            )
            self.assertTrue(diff_file.is_file())
            content = diff_file.read_text(encoding="utf-8")
            self.assertIn("+    return 2", content)

            git_log = subprocess.run(
                ["git", "remote"], cwd=self.repo_dir, capture_output=True, text=True
            )
            self.assertEqual(git_log.stdout.strip(), "")


class TestStartupLatencyProbe(unittest.TestCase):
    def test_partner_client_startup_overhead(self):
        mock_anthropic = MagicMock()
        mock_anthropic.AnthropicVertex = MagicMock()

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            duration_s = measure_partner_client_startup(
                project="perf-project",
                region="us-central1",
            )
            self.assertLessEqual(duration_s, 2.0)


class TestWorkspaceTools(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        subprocess.run(["git", "init"], cwd=self.repo_dir, check=True, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_workspace_tool_run_command_destructive_blocked_by_safety(self):
        destructive_commands = [
            "rm -rf /",
            "git push origin main -f",
            "git push --force origin main",
            "drop database testdb",
        ]
        for cmd in destructive_commands:
            with self.subTest(cmd=cmd):
                res = execute_workspace_tool("run_command", {"command": cmd}, self.repo_dir)
                self.assertIn("Error: Command blocked by safety policy", res)
                self.assertIn("deny", res.lower())

    def test_workspace_tool_run_command_safe_allowed(self):
        res = execute_workspace_tool("run_command", {"command": "echo safe_test_output"}, self.repo_dir)
        self.assertIn("safe_test_output", res)


class TestCloudWorkerManifestAuth(unittest.TestCase):
    def test_main_deepseek_manifest_enables_vertex_under_adc(self):
        env = {
            "REPO_URL": "https://github.com/example/repo.git",
            "MODEL_OVERRIDE": "",
            "TASK_MANIFEST": json.dumps([{"model": "deepseek", "brief": "solve"}]),
            "GEMINI_API_KEY": "",
            "USE_VERTEX_AI": "",
            "CLOUD_RUN_TASK_INDEX": "0",
        }
        orig_cwd = os.getcwd()
        try:
            with patch.dict(os.environ, env, clear=False), \
                 patch("cloud_worker.clone_and_checkout_task"), \
                 patch("cloud_worker.execute_task", return_value=("PASS", "done")) as mock_exec, \
                 patch("cloud_worker.run_command") as mock_run_cmd, \
                 patch("cloud_worker.parse_score_metrics", return_value=(None, None, None)), \
                 patch("os.chdir"):
                mock_run_cmd.return_value = MagicMock(returncode=0, stdout="")
                with patch("sys.exit"):
                    cloud_worker.main()
                mock_exec.assert_called_once()
                self.assertTrue(mock_exec.call_args[1].get("use_vertex"))
        finally:
            os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()
