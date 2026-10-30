import concurrent.futures
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"))

from cloud_dispatch import (
    ShadowTranscriptProjector,
    cleanup_session,
    format_conversation_url,
    get_task_brain_dir,
    get_task_conversation_id,
    initialize_shadow_transcript,
    is_telemetry_line,
    parse_telemetry_line,
    resolve_app_data_dir,
)
from transcript_projector import (
    ShadowTranscriptProjector as ShadowTranscriptProjectorDirect,
    cleanup_session as cleanup_session_direct,
    format_conversation_url as format_conversation_url_direct,
    get_task_brain_dir as get_task_brain_dir_direct,
    get_task_conversation_id as get_task_conversation_id_direct,
    initialize_shadow_transcript as initialize_shadow_transcript_direct,
    is_telemetry_line as is_telemetry_line_direct,
    parse_telemetry_line as parse_telemetry_line_direct,
    resolve_app_data_dir as resolve_app_data_dir_direct,
)
from cloud_worker import (
    TokenShield,
    emit_agent_response,
    emit_milestone,
    emit_telemetry,
    emit_thought,
    emit_tool_invocation,
    emit_tool_result,
    emit_user_input,
)


class TestShadowTranscriptProjection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp()).resolve()
        self.app_data_dir = self.temp_dir / "antigravity"
        self.session_id = f"test-sess-{int(time.time() * 1000)}"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initialization_of_shadow_transcript_directory_and_file(self):
        task_index = 0
        brief = "Implement feature XYZ"
        primary_file, system_file = initialize_shadow_transcript(
            session_id=self.session_id,
            task_index=task_index,
            task_brief=brief,
            app_data_dir=self.app_data_dir,
        )

        expected_task_dir = self.app_data_dir / "brain" / f"cloud-{self.session_id}-task-{task_index}"
        self.assertTrue(expected_task_dir.is_dir())
        self.assertTrue(primary_file.is_file())
        self.assertTrue(system_file.is_file())
        self.assertEqual(primary_file, expected_task_dir / "transcript.jsonl")
        self.assertEqual(system_file, expected_task_dir / ".system_generated" / "logs" / "transcript.jsonl")

        primary_content = primary_file.read_text(encoding="utf-8").strip()
        system_content = system_file.read_text(encoding="utf-8").strip()
        self.assertEqual(primary_content, system_content)

        entry = json.loads(primary_content)
        self.assertEqual(entry["step_index"], 0)
        self.assertEqual(entry["source"], "USER")
        self.assertEqual(entry["type"], "USER_INPUT")
        self.assertEqual(entry["status"], "DONE")
        self.assertEqual(entry["content"], brief)
        self.assertTrue("created_at" in entry)

    def test_agent_thought_projection_into_planner_response(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
        )
        projector.init_task(0, task_brief="Initial user prompt")

        thought_line = f'[TELEMETRY] [TASK 0] {{"timestamp": {time.time()}, "event": "thought", "thought": "Analyzing system constraints"}}'
        projector.process_log_line(thought_line)

        primary, system = projector.get_transcript_files(0)
        lines = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual(len(lines), 2)
        planner_entry = lines[1]
        self.assertEqual(planner_entry["step_index"], 1)
        self.assertEqual(planner_entry["source"], "MODEL")
        self.assertEqual(planner_entry["type"], "PLANNER_RESPONSE")
        self.assertEqual(planner_entry["status"], "DONE")
        self.assertEqual(planner_entry["thinking"], "Analyzing system constraints")
        self.assertEqual(planner_entry["tool_calls"], [])

        second_thought_line = f'[TELEMETRY] [TASK 0] {{"timestamp": {time.time()}, "event": "thought", "thought": "Selecting architecture"}}'
        projector.process_log_line(second_thought_line)

        updated_lines = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(updated_lines), 2)
        self.assertIn("Analyzing system constraints", updated_lines[1]["thinking"])
        self.assertIn("Selecting architecture", updated_lines[1]["thinking"])

    def test_tool_call_argument_and_execution_output_projection(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
        )
        projector.init_task(0, task_brief="Tool execution test")

        call_line = (
            f'[TELEMETRY] [TASK 0] {{"timestamp": {time.time()}, "event": "tool_call", '
            f'"tool_name": "run_command", "args": {{"CommandLine": "pytest"}}, "call_id": "call_1"}}'
        )
        projector.process_log_line(call_line)

        result_line = (
            f'[TELEMETRY] [TASK 0] {{"timestamp": {time.time()}, "event": "tool_result", '
            f'"tool_name": "run_command", "output": "3 passed in 0.2s", "success": true, '
            f'"call_id": "call_1", "duration_s": 0.2}}'
        )
        projector.process_log_line(result_line)

        primary, _ = projector.get_transcript_files(0)
        entries = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual(len(entries), 3)

        planner_entry = entries[1]
        self.assertEqual(planner_entry["step_index"], 1)
        self.assertEqual(planner_entry["type"], "PLANNER_RESPONSE")
        self.assertEqual(len(planner_entry["tool_calls"]), 1)
        self.assertEqual(planner_entry["tool_calls"][0]["name"], "run_command")
        self.assertEqual(planner_entry["tool_calls"][0]["args"], {"CommandLine": "pytest"})
        self.assertEqual(planner_entry["tool_calls"][0]["id"], "call_1")

        tool_entry = entries[2]
        self.assertEqual(tool_entry["step_index"], 2)
        self.assertEqual(tool_entry["source"], "TOOL")
        self.assertEqual(tool_entry["type"], "TOOL_RESPONSE")
        self.assertEqual(tool_entry["tool_name"], "run_command")
        self.assertEqual(tool_entry["output"], "3 passed in 0.2s")
        self.assertEqual(tool_entry["content"], "3 passed in 0.2s")
        self.assertTrue(tool_entry["success"])
        self.assertEqual(tool_entry["call_id"], "call_1")

    def test_clickable_conversation_url_generation(self):
        url = format_conversation_url(self.session_id, 3)
        self.assertEqual(url, f"conversation://cloud-{self.session_id}-task-3")

        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=4,
        )
        self.assertEqual(
            projector.get_conversation_url(3),
            f"conversation://cloud-{self.session_id}-task-3",
        )
        self.assertTrue(url.startswith("conversation://cloud-"))

    def test_token_shield_stdout_contains_milestones_only(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            with TokenShield(task_index=1):
                emit_milestone(1, "BOOTING", "Container initialized")
                print("Raw model thought token stream leaking into stdout...")
                emit_thought(1, "Direct model thought emission")
                emit_milestone(1, "RUNNING_AGENT", "Turn 1")
                emit_tool_invocation(1, "grep_search", {"query": "SECRET"})
                print("Detailed tool output payload exceeding terminal limits: {'raw': 'data'}")
                emit_tool_result(1, "grep_search", "match found", success=True)
                emit_milestone(1, "COMPLETED", "Task finished")

            stdout_content = mock_stdout.getvalue()

        stdout_lines = [line.strip() for line in stdout_content.splitlines() if line.strip()]
        self.assertGreaterEqual(len(stdout_lines), 3)

        for line in stdout_lines:
            self.assertTrue(
                line.startswith("[MILESTONE]"),
                f"Non-milestone leaked to terminal stdout: {line}",
            )

        self.assertNotIn("Raw model thought token stream leaking into stdout", stdout_content)
        self.assertNotIn("Detailed tool output payload exceeding terminal limits", stdout_content)
        self.assertNotIn("Direct model thought emission", stdout_content)

    def test_concurrent_transcript_writes_across_8_workers(self):
        worker_count = 8
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=worker_count,
        )

        def worker_task(task_index: int):
            projector.init_task(task_index, task_brief=f"Concurrent task brief {task_index}")
            for step in range(5):
                t_log = time.time()
                thought_line = (
                    f'[TELEMETRY] [TASK {task_index}] {{"timestamp": {t_log}, "event": "thought", '
                    f'"thought": "Worker {task_index} step {step} thinking"}}'
                )
                projector.process_log_line(thought_line)

                call_line = (
                    f'[TELEMETRY] [TASK {task_index}] {{"timestamp": {t_log}, "event": "tool_call", '
                    f'"tool_name": "worker_tool", "args": {{"step": {step}}}, "call_id": "c_{task_index}_{step}"}}'
                )
                projector.process_log_line(call_line)

                res_line = (
                    f'[TELEMETRY] [TASK {task_index}] {{"timestamp": {t_log}, "event": "tool_result", '
                    f'"tool_name": "worker_tool", "output": "res_{task_index}_{step}", "success": true, '
                    f'"call_id": "c_{task_index}_{step}"}}'
                )
                projector.process_log_line(res_line)

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(worker_task, idx) for idx in range(worker_count)]
            concurrent.futures.wait(futures)

        for task_index in range(worker_count):
            primary, system = projector.get_transcript_files(task_index)
            self.assertTrue(primary.is_file())
            self.assertTrue(system.is_file())

            primary_lines = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
            system_lines = [json.loads(line) for line in system.read_text(encoding="utf-8").splitlines() if line.strip()]

            self.assertEqual(len(primary_lines), len(system_lines))
            self.assertEqual(len(primary_lines), 11)

            step_indices = [entry["step_index"] for entry in primary_lines]
            self.assertEqual(step_indices, list(range(11)))

            for entry in primary_lines:
                if entry["type"] == "TOOL_RESPONSE":
                    self.assertIn(f"res_{task_index}_", entry["output"])

    def test_corrupted_log_parsing_recovery(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
        )
        projector.init_task(0, task_brief="Resilience test")

        corrupted_lines = [
            "[TELEMETRY] [TASK 0] {malformed json: true,",
            "[TELEMETRY] [TASK 0] truncated string payload \"abc",
            "[TELEMETRY] not json data at all",
            "[TELEMETRY] [TASK invalid] {\"event\": \"thought\"}",
            "[TELEMETRY] [TASK 0] [\"unexpected\", \"list\"]",
            "",
            "   ",
            "[MILESTONE] [TASK 0] [PHASE: UNRELATED] ignore this",
            ">> unhandled container exception line <<",
        ]

        for corrupted in corrupted_lines:
            result = projector.process_log_line(corrupted)
            self.assertIsNone(result)

        valid_line = (
            f'[TELEMETRY] [TASK 0] {{"timestamp": {time.time()}, "event": "thought", '
            f'"thought": "Recovered from corrupted stream"}}'
        )
        res = projector.process_log_line(valid_line)
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "PLANNER_RESPONSE")
        self.assertEqual(res["thinking"], "Recovered from corrupted stream")

        primary, _ = projector.get_transcript_files(0)
        entries = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]["thinking"], "Recovered from corrupted stream")

    def test_native_antigravity_schema_compliance(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
        )
        projector.init_task(0, task_brief="Verify schema compliance")

        t0 = time.time()
        projector.process_log_line(
            f'[TELEMETRY] [TASK 0] {{"timestamp": {t0}, "event": "thought", "thought": "Refactoring step"}}'
        )
        projector.process_log_line(
            f'[TELEMETRY] [TASK 0] {{"timestamp": {t0}, "event": "tool_call", "tool_name": "view_file", '
            f'"args": {{"path": "lib.py"}}, "call_id": "c_1"}}'
        )
        projector.process_log_line(
            f'[TELEMETRY] [TASK 0] {{"timestamp": {t0}, "event": "tool_result", "tool_name": "view_file", '
            f'"output": "def foo(): pass", "success": true, "call_id": "c_1"}}'
        )

        primary, _ = projector.get_transcript_files(0)
        entries = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(entries), 3)

        u = entries[0]
        self.assertEqual(u["step_index"], 0)
        self.assertEqual(u["source"], "USER")
        self.assertEqual(u["type"], "USER_INPUT")
        self.assertEqual(u["status"], "DONE")
        self.assertIsInstance(u["content"], str)
        datetime.fromisoformat(u["created_at"].replace("Z", "+00:00"))

        p = entries[1]
        self.assertEqual(p["step_index"], 1)
        self.assertEqual(p["source"], "MODEL")
        self.assertEqual(p["type"], "PLANNER_RESPONSE")
        self.assertEqual(p["status"], "DONE")
        self.assertIsInstance(p["thinking"], str)
        self.assertIsInstance(p["tool_calls"], list)
        self.assertEqual(p["tool_calls"][0]["name"], "view_file")
        self.assertEqual(p["tool_calls"][0]["args"], {"path": "lib.py"})
        datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))

        t = entries[2]
        self.assertEqual(t["step_index"], 2)
        self.assertEqual(t["source"], "TOOL")
        self.assertEqual(t["type"], "TOOL_RESPONSE")
        self.assertEqual(t["status"], "DONE")
        self.assertEqual(t["tool_name"], "view_file")
        self.assertEqual(t["output"], "def foo(): pass")
        self.assertTrue(t["success"])
        datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))

    def test_preservation_of_transcripts_during_and_after_session_cleanup(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=3,
        )
        for i in range(3):
            projector.init_task(i, task_brief=f"Preservation task {i}")
            projector.process_log_line(
                f'[TELEMETRY] [TASK {i}] {{"timestamp": {time.time()}, "event": "thought", "thought": "Running {i}"}}'
            )

        brain_dir = self.app_data_dir / "brain"
        task_dirs = list(brain_dir.glob(f"cloud-{self.session_id}-task-*"))
        self.assertEqual(len(task_dirs), 3)

        temp_scratch = Path(self.temp_dir) / "temp_scratch"
        temp_scratch.mkdir(parents=True, exist_ok=True)
        (temp_scratch / "temp_artifact.txt").write_text("transient", encoding="utf-8")

        cleanup_res = cleanup_session(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            preserve_transcripts=True,
            temp_dir=temp_scratch,
        )

        self.assertTrue(cleanup_res["transcripts_preserved"])
        self.assertEqual(len(cleanup_res["preserved_directories"]), 3)
        self.assertFalse(temp_scratch.exists())

        for task_dir in task_dirs:
            self.assertTrue(task_dir.is_dir())
            primary = task_dir / "transcript.jsonl"
            system = task_dir / ".system_generated" / "logs" / "transcript.jsonl"
            self.assertTrue(primary.is_file())
            self.assertTrue(system.is_file())
            lines = [line for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 2)

    def test_telemetry_projection_latency_probe(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
        )
        projector.init_task(0, task_brief="Latency probe task")

        baseline_delay_s = 2.0
        event_time = time.time() - baseline_delay_s
        telemetry_line = (
            f'[TELEMETRY] [TASK 0] {{"timestamp": {event_time}, "event": "thought", '
            f'"thought": "Latency verification thought"}}'
        )

        measured_latency = projector.measure_projection_latency(telemetry_line)
        self.assertIsNotNone(measured_latency)
        self.assertLessEqual(measured_latency, 3.5)
        self.assertGreaterEqual(measured_latency, 1.8)

        last_latency = projector.get_last_latency()
        self.assertEqual(measured_latency, last_latency)

        iso_time = datetime.now(timezone.utc).isoformat()
        iso_line = (
            f'[TELEMETRY] [TASK 0] {{"timestamp": "{iso_time}", "event": "thought", '
            f'"thought": "ISO timestamp latency test"}}'
        )
        iso_latency = projector.measure_projection_latency(iso_line)
        self.assertIsNotNone(iso_latency)
        self.assertLessEqual(iso_latency, 3.5)

    def test_backwards_compatible_module_exports(self):
        self.assertIs(ShadowTranscriptProjector, ShadowTranscriptProjectorDirect)
        self.assertIs(initialize_shadow_transcript, initialize_shadow_transcript_direct)
        self.assertIs(cleanup_session, cleanup_session_direct)
        self.assertIs(format_conversation_url, format_conversation_url_direct)
        self.assertIs(get_task_brain_dir, get_task_brain_dir_direct)
        self.assertIs(get_task_conversation_id, get_task_conversation_id_direct)
        self.assertIs(is_telemetry_line, is_telemetry_line_direct)
        self.assertIs(parse_telemetry_line, parse_telemetry_line_direct)
        self.assertIs(resolve_app_data_dir, resolve_app_data_dir_direct)

    def test_atomic_file_replacement_in_update_last_entry(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
        )
        projector.init_task(0, task_brief="Atomic file replacement test")
        primary, system = projector.get_transcript_files(0)

        t0 = time.time()
        projector.process_log_line(
            f'[TELEMETRY] [TASK 0] {{"timestamp": {t0}, "event": "thought", "thought": "Original thought"}}'
        )

        updated_entry = {
            "step_index": 1,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "thinking": "Atomically replaced thought content",
            "tool_calls": [],
            "content": "Updated content",
        }

        with patch("os.replace", wraps=os.replace) as mock_replace:
            projector._update_last_entry(0, updated_entry)
            self.assertEqual(mock_replace.call_count, 2)

        temp_files_primary = list(primary.parent.glob("tmp*"))
        temp_files_system = list(system.parent.glob("tmp*"))
        self.assertEqual(len(temp_files_primary), 0)
        self.assertEqual(len(temp_files_system), 0)

        primary_lines = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
        system_lines = [json.loads(line) for line in system.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(primary_lines), 2)
        self.assertEqual(len(system_lines), 2)
        self.assertEqual(primary_lines[1]["thinking"], "Atomically replaced thought content")
        self.assertEqual(system_lines[1]["thinking"], "Atomically replaced thought content")

    def test_per_task_lock_concurrency(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=2,
        )
        lock_0 = projector._get_task_lock(0)
        lock_1 = projector._get_task_lock(1)

        self.assertIsInstance(lock_0, type(threading.Lock()))
        self.assertIsInstance(lock_1, type(threading.Lock()))
        self.assertIsNot(lock_0, lock_1)

        acquired_0 = lock_0.acquire(blocking=False)
        self.assertTrue(acquired_0)

        task_1_completed = threading.Event()

        def run_task_1():
            projector.init_task(1, task_brief="Task 1 independent progress")
            task_1_completed.set()

        t = threading.Thread(target=run_task_1)
        t.start()
        t.join(timeout=2.0)
        self.assertTrue(task_1_completed.is_set())

        lock_0.release()

    def test_tokenshield_credential_regex_redaction(self):
        mock_telemetry_out = io.StringIO()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            shield = TokenShield(task_index=0, telemetry_stream=mock_telemetry_out)
            fake_ghp = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyzAB"
            fake_aiza = "AIza" + "SyD-1234567890abcdefABCDEF123456789"
            fake_oauth = "ya29." + "a0AfH6SMCxyz123_456-789"
            fake_bearer = "Bearer " + "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
            fake_ghp_thought = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            with shield:
                shield.emit_milestone("START", "Container booted")
                print(f"Leaking GitHub token {fake_ghp} in terminal")
                print(f"Leaking Google AIza key {fake_aiza} in terminal")
                print(f"Leaking OAuth token {fake_oauth} in terminal")
                print(f"Leaking auth header {fake_bearer} in terminal")
                shield.emit_thought(f"Internal thought with {fake_ghp_thought}")

        stdout_content = mock_stdout.getvalue()
        telemetry_content = mock_telemetry_out.getvalue()

        self.assertIn("[MILESTONE]", stdout_content)
        self.assertNotIn("ghp_", stdout_content)
        self.assertNotIn("AIza", stdout_content)
        self.assertNotIn("ya29", stdout_content)
        self.assertNotIn("Bearer", stdout_content)

        for thought in shield.captured_thoughts:
            self.assertNotIn("ghp_1234567890", thought)
            self.assertNotIn("AIzaSyD", thought)
            self.assertNotIn("ya29.a0Af", thought)
            self.assertNotIn("Bearer eyJhbGciOi", thought)
            self.assertIn("[REDACTED]", thought)

        self.assertNotIn("ghp_1234567890", telemetry_content)
        self.assertNotIn("AIzaSyD", telemetry_content)
        self.assertNotIn("ya29.a0Af", telemetry_content)
        self.assertNotIn("Bearer eyJhbGciOi", telemetry_content)
        self.assertIn("[REDACTED]", telemetry_content)

    def test_tokenshield_stdout_restoration_on_exception(self):
        orig_stdout = sys.stdout
        try:
            with TokenShield(task_index=0):
                self.assertIsInstance(sys.stdout, TokenShield)
                raise RuntimeError("Forced exception inside TokenShield context")
        except RuntimeError:
            pass
        self.assertIs(sys.stdout, orig_stdout)

        try:
            with TokenShield(task_index=0) as shield:
                with patch.object(shield, "_handle_non_milestone", side_effect=ValueError("Flush crash")):
                    print("Unflushed message before crash")
        except ValueError:
            pass
        self.assertIs(sys.stdout, orig_stdout)

    def test_deduplication_of_identical_telemetry_events(self):
        projector = ShadowTranscriptProjector(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
        )
        projector.init_task(0, task_brief="Deduplication test")

        fixed_ts = 1700000000.123
        thought_line = (
            f'[TELEMETRY] [TASK 0] {{"timestamp": {fixed_ts}, "event": "thought", '
            f'"thought": "Dedup test thinking statement"}}'
        )

        res1 = projector.process_log_line(thought_line)
        self.assertIsNotNone(res1)
        self.assertEqual(res1["type"], "PLANNER_RESPONSE")

        res2 = projector.process_log_line(thought_line)
        self.assertIsNone(res2)

        expected_event_key = (0, "thought", "", fixed_ts)
        self.assertIn(expected_event_key, projector._seen_events)

        primary, _ = projector.get_transcript_files(0)
        lines = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["thinking"].count("Dedup test thinking statement"), 1)

        call_line = (
            f'[TELEMETRY] [TASK 0] {{"timestamp": {fixed_ts + 1}, "event": "tool_call", '
            f'"tool_name": "test_tool", "call_id": "c_dedup_1", "args": {{"p": 1}}}}'
        )
        c1 = projector.process_log_line(call_line)
        self.assertIsNotNone(c1)
        c2 = projector.process_log_line(call_line)
        self.assertIsNone(c2)

        expected_call_key = (0, "tool_call", "c_dedup_1", fixed_ts + 1)
        self.assertIn(expected_call_key, projector._seen_events)

        lines_after_call = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines_after_call[1]["tool_calls"]), 1)


if __name__ == "__main__":
    unittest.main()
