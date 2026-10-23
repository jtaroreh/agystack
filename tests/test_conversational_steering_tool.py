#!/usr/bin/env python3
"""
Unit tests for conversational mailbox steering tool.
Covers:
1. Text steering instruction delivery to worker mailbox in GCS.
2. Pre-tool hook intercepting steering instruction and emitting STEER_APPLIED.
3. ABORT command handling emitting ABORT_REQUESTED.
4. Broadcast steering instruction to all workers.
5. Target out of range error (exit code 1).
6. Dashboard reflecting steer pending status.
7. Idempotent re-delivery preventing duplicate execution via sequence numbers.
8. GCS network timeout retry logic.
9. Worker prompt injecting custom steer context.
10. Mailbox cleanup upon session completion.
11. Steering delivery latency probe <= 600ms (baseline 250ms).
"""

import asyncio
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure scripts directory is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from storage_messenger import (
    MailboxEnvelope,
    MessageStatus,
    MessageType,
    StorageMessenger,
    retry_gcs_operation,
)
from steer_cloud_task import (
    is_abort_command,
    steer_task,
    validate_instruction,
    validate_seq,
    validate_task_target,
)
from cloud_dispatch import (
    SwarmDashboardWriter,
    TaskDashboardState,
    cleanup_session,
    handle_mailbox_steer,
)
from cloud_worker import StagnancyTracker, create_agent_hooks


class FakeHookResult:
    def __init__(self, allow=True, error_message=None, custom_context=None):
        self.allow = allow
        self.error_message = error_message
        self.custom_context = custom_context


class FakeHooks:
    def pre_tool_call_decide(self, fn):
        return fn

    def post_tool_call(self, fn):
        return fn


class TestConversationalSteeringTool(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_steer_")
        self.storage_root = Path(self.temp_dir)
        self.bucket_name = "test-steering-bucket"
        self.session_id = f"test-sess-{int(time.time() * 1000)}"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_messenger(self, task_index: int = 0, is_worker: bool = False):
        return StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=task_index,
            is_worker=is_worker,
            local_dir=self.storage_root,
        )

    def test_01_text_steering_instruction_delivery_to_worker_mailbox(self):
        """Verify delivery of text steering instruction to worker inbox envelope in GCS."""
        orch = self._create_messenger(is_worker=False)
        worker = self._create_messenger(task_index=0, is_worker=True)

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            envelope = handle_mailbox_steer(
                task_index=0,
                text="Refactor authentication parser",
                session_id=self.session_id,
                bucket_name=self.bucket_name,
                messenger=orch,
            )

            stdout_val = mock_out.getvalue()
            self.assertIn("[STEER] Instruction delivered to task-0 mailbox in GCS", stdout_val)

        self.assertIsNotNone(envelope)
        self.assertEqual(envelope.task_index, 0)
        self.assertEqual(envelope.seq, 1)
        self.assertEqual(envelope.msg_type, MessageType.STEER)
        self.assertEqual(envelope.payload.get("instruction"), "Refactor authentication parser")

        # Verify disk artifact exists in local GCS inbox
        inbox_file = (
            self.storage_root
            / self.bucket_name
            / "swarms"
            / self.session_id
            / "tasks"
            / "task-0"
            / "inbox"
            / "0001_steer.json"
        )
        self.assertTrue(inbox_file.is_file())

        # Worker picks up steering instruction
        steers = worker.check_steer_instructions()
        self.assertEqual(len(steers), 1)
        self.assertEqual(steers[0].payload.get("instruction"), "Refactor authentication parser")

    def test_02_pre_tool_hook_intercepting_steering_instruction_and_emitting_steer_applied(self):
        """Verify pre-tool hook intercepts steering instruction and emits STEER_APPLIED milestone."""
        orch = self._create_messenger(is_worker=False)
        worker = self._create_messenger(task_index=1, is_worker=True)

        orch.send_steer(task_index=1, instruction="Prioritize latency regression fix")

        fake_hooks = FakeHooks()
        fake_types = MagicMock()
        fake_types.HookResult = FakeHookResult

        tracker = StagnancyTracker()
        hooks = create_agent_hooks(
            messenger=worker,
            task_index=1,
            tracker=tracker,
            hooks_module=fake_hooks,
            types_module=fake_types,
        )
        pre_hook = hooks[0]

        tool_call = MagicMock()
        tool_call.name = "run_command"
        tool_call.args = {"CommandLine": "pytest"}

        with patch("cloud_worker.emit_milestone") as mock_milestone:
            res = asyncio.run(pre_hook(tool_call))
            self.assertTrue(res.allow)
            self.assertEqual(res.custom_context, "Prioritize latency regression fix")
            mock_milestone.assert_any_call(1, "STEER_APPLIED", "Prioritize latency regression fix")

    def test_03_abort_command_handling_emitting_abort_requested(self):
        """Verify ABORT command causes hook to reject execution and emit ABORT_REQUESTED."""
        orch = self._create_messenger(is_worker=False)
        worker = self._create_messenger(task_index=2, is_worker=True)

        orch.send_steer(task_index=2, instruction="ABORT immediately due to resource saturation")

        fake_hooks = FakeHooks()
        fake_types = MagicMock()
        fake_types.HookResult = FakeHookResult

        tracker = StagnancyTracker()
        hooks = create_agent_hooks(
            messenger=worker,
            task_index=2,
            tracker=tracker,
            hooks_module=fake_hooks,
            types_module=fake_types,
        )
        pre_hook = hooks[0]

        tool_call = MagicMock()
        tool_call.name = "replace_file_content"
        tool_call.args = {"TargetFile": "/tmp/test.py"}

        with patch("cloud_worker.emit_milestone") as mock_milestone:
            res = asyncio.run(pre_hook(tool_call))
            self.assertFalse(res.allow)
            self.assertIn("Execution aborted by orchestrator", res.error_message)
            mock_milestone.assert_any_call(
                2, "ABORT_REQUESTED", "ABORT immediately due to resource saturation"
            )

    def test_04_broadcast_steering_instruction_to_all_workers(self):
        """Verify broadcasting instruction to all workers with --task all."""
        orch = self._create_messenger(is_worker=False)
        worker_0 = self._create_messenger(task_index=0, is_worker=True)
        worker_1 = self._create_messenger(task_index=1, is_worker=True)
        worker_2 = self._create_messenger(task_index=2, is_worker=True)

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            envs = steer_task(
                task="all",
                instruction="Switch to strict memory bounds",
                session_id=self.session_id,
                bucket_name=self.bucket_name,
                messenger=orch,
                max_tasks=3,
            )
            stdout_val = mock_out.getvalue()
            self.assertIn("[STEER] Instruction delivered to task-0 mailbox in GCS", stdout_val)
            self.assertIn("[STEER] Instruction delivered to task-1 mailbox in GCS", stdout_val)
            self.assertIn("[STEER] Instruction delivered to task-2 mailbox in GCS", stdout_val)

        self.assertEqual(len(envs), 3)

        # Confirm each worker received the instruction
        for worker in (worker_0, worker_1, worker_2):
            steers = worker.check_steer_instructions()
            self.assertEqual(len(steers), 1)
            self.assertEqual(steers[0].payload.get("instruction"), "Switch to strict memory bounds")

    def test_05_target_out_of_range_error_exit_code_1(self):
        """Verify target out of range errors raise ValueError or exit with code 1."""
        # Validation functions
        with self.assertRaises(ValueError):
            validate_task_target(-1)

        with self.assertRaises(ValueError):
            validate_task_target(5, max_tasks=3)

        with self.assertRaises(ValueError):
            validate_instruction("")

        with self.assertRaises(ValueError):
            validate_seq(0)

        # Test CLI error handling in steer_cloud_task main
        with patch("sys.argv", ["steer_cloud_task.py", "--task", "10", "--instruction", "foo", "--task-count", "2"]), \
             patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            from steer_cloud_task import main as steer_main
            with self.assertRaises(SystemExit) as cm:
                steer_main()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("out of range", mock_err.getvalue())

        # Test CLI error handling in cloud_dispatch steer subcommand
        orch = self._create_messenger(is_worker=False)
        with patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            with self.assertRaises(SystemExit) as cm:
                handle_mailbox_steer(
                    task_index=99,
                    text="Invalid task target",
                    session_id=self.session_id,
                    bucket_name=self.bucket_name,
                    messenger=orch,
                    max_tasks=2,
                )
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("out of range", mock_err.getvalue())

    def test_06_dashboard_reflecting_steer_pending_status(self):
        """Verify SwarmDashboardWriter reflects steer pending status and clears it upon milestone."""
        app_data_dir = self.storage_root / "antigravity"
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            conversation_id=self.session_id,
            app_data_dir=app_data_dir,
            task_count=2,
            model="gemini-3.8-flash",
        )
        writer.update_task_phase(0, "RUNNING_AGENT")

        # Initial render: no steer pending
        initial_render = writer.render()
        self.assertNotIn("STEER_PENDING", initial_render)

        # Dispatch steering instruction to task 0
        orch = self._create_messenger(is_worker=False)
        handle_mailbox_steer(
            task_index=0,
            text="Abort search branch C",
            session_id=self.session_id,
            bucket_name=self.bucket_name,
            messenger=orch,
            dashboard_writer=writer,
        )

        state = writer.get_task_state(0)
        self.assertIsNotNone(state)
        self.assertTrue(state.is_steer_pending)
        self.assertEqual(state.pending_steer, "Abort search branch C")

        # Render shows STEER_PENDING
        steer_render = writer.render()
        self.assertIn("STEER_PENDING: Abort search branch C", steer_render)

        # Worker applies steering instruction and emits STEER_APPLIED milestone
        milestone_line = "[MILESTONE] [TASK 0] [PHASE: STEER_APPLIED] Abort search branch C"
        processed = writer.process_log_line(milestone_line)
        self.assertTrue(processed)

        # Pending steer is cleared and phase updated
        self.assertFalse(state.is_steer_pending)
        self.assertIsNone(state.pending_steer)
        self.assertEqual(state.phase, "STEER_APPLIED")

        cleared_render = writer.render()
        self.assertNotIn("STEER_PENDING", cleared_render)
        self.assertIn("STEER_APPLIED", cleared_render)

    def test_07_idempotent_redelivery_preventing_duplicate_execution_via_sequence_numbers(self):
        """Verify that sequence numbers and acknowledged status prevent duplicate execution."""
        orch = self._create_messenger(is_worker=False)
        worker = self._create_messenger(task_index=0, is_worker=True)

        env1 = orch.send_steer(task_index=0, instruction="First directive")
        self.assertEqual(env1.seq, 1)

        # First check consumes and acknowledges envelope seq 1
        steers = worker.check_steer_instructions()
        self.assertEqual(len(steers), 1)
        self.assertEqual(steers[0].seq, 1)

        # Immediate re-check returns empty list (in-memory deduplication)
        steers_again = worker.check_steer_instructions()
        self.assertEqual(len(steers_again), 0)

        # Re-instantiate worker (simulating crash and recovery)
        recovered_worker = self._create_messenger(task_index=0, is_worker=True)
        # Should not re-deliver already ACKNOWLEDGED envelope seq 1
        steers_recovered = recovered_worker.check_steer_instructions()
        self.assertEqual(len(steers_recovered), 0)

        # Now send a second directive: receives seq 2
        env2 = orch.send_steer(task_index=0, instruction="Second directive")
        self.assertEqual(env2.seq, 2)

        steers_new = recovered_worker.check_steer_instructions()
        self.assertEqual(len(steers_new), 1)
        self.assertEqual(steers_new[0].seq, 2)
        self.assertEqual(steers_new[0].payload.get("instruction"), "Second directive")

    def test_08_gcs_network_timeout_retry_logic(self):
        """Verify exponential backoff retry logic on network timeouts."""
        attempts = 0

        def flaky_gcs_call():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError("Simulated GCS network socket timeout")
            return "SUCCESS"

        result = retry_gcs_operation(
            flaky_gcs_call,
            max_retries=3,
            initial_delay=0.01,
            backoff_factor=1.2,
        )
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(attempts, 3)

        # Test failure when retries exhausted
        always_timeout_attempts = 0

        def persistent_timeout():
            nonlocal always_timeout_attempts
            always_timeout_attempts += 1
            raise TimeoutError("Persistent connection timeout")

        with self.assertRaises(TimeoutError):
            retry_gcs_operation(
                persistent_timeout,
                max_retries=2,
                initial_delay=0.01,
            )
        self.assertEqual(always_timeout_attempts, 3)

    def test_09_worker_prompt_injecting_custom_steer_context(self):
        """Verify that worker hook injects steering instruction as custom_context into model prompt."""
        orch = self._create_messenger(is_worker=False)
        worker = self._create_messenger(task_index=3, is_worker=True)

        steer_text = "Ensure backward compatibility with API v1"
        orch.send_steer(task_index=3, instruction=steer_text)

        fake_hooks = FakeHooks()
        fake_types = MagicMock()
        fake_types.HookResult = FakeHookResult

        tracker = StagnancyTracker()
        hooks = create_agent_hooks(
            messenger=worker,
            task_index=3,
            tracker=tracker,
            hooks_module=fake_hooks,
            types_module=fake_types,
        )
        pre_hook = hooks[0]

        tool_call = MagicMock()
        tool_call.name = "run_command"
        tool_call.args = {"CommandLine": "cargo build"}

        res = asyncio.run(pre_hook(tool_call))
        self.assertTrue(res.allow)
        self.assertEqual(res.custom_context, steer_text)

    def test_10_mailbox_cleanup_upon_session_completion(self):
        """Verify that ephemeral mailbox envelopes are completely purged on session cleanup."""
        orch = self._create_messenger(is_worker=False)
        worker_0 = self._create_messenger(task_index=0, is_worker=True)
        worker_1 = self._create_messenger(task_index=1, is_worker=True)

        # Create outbox and inbox envelopes
        worker_0.send_question("Worker 0 question")
        worker_1.send_question("Worker 1 question")
        orch.send_steer(task_index=0, instruction="Steer 0")
        orch.send_steer(task_index=1, instruction="Steer 1")

        session_tasks_dir = (
            self.storage_root / self.bucket_name / "swarms" / self.session_id / "tasks"
        )
        self.assertTrue(session_tasks_dir.exists())

        # Clean up session
        cleanup_res = cleanup_session(
            session_id=self.session_id,
            bucket_name=self.bucket_name,
            messenger=orch,
        )
        self.assertGreater(cleanup_res.get("mailboxes_cleaned", 0), 0)

        # Verify no questions or steer envelopes remain
        self.assertEqual(len(orch.list_pending_questions()), 0)
        self.assertEqual(len(worker_0.check_steer_instructions()), 0)
        self.assertEqual(len(worker_1.check_steer_instructions()), 0)

    def test_11_steering_delivery_latency_probe_under_600ms(self):
        """Probe steering delivery latency; must be <= 600ms (baseline ~250ms SLA)."""
        orch = self._create_messenger(is_worker=False)

        latencies_ms = []
        iterations = 10
        for i in range(iterations):
            t_start = time.perf_counter()
            steer_task(
                task=0,
                instruction=f"Latency probe iteration {i}",
                session_id=self.session_id,
                messenger=orch,
            )
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            latencies_ms.append(elapsed_ms)

        avg_latency_ms = sum(latencies_ms) / len(latencies_ms)
        max_latency_ms = max(latencies_ms)

        # Assert strict latency SLA under 600ms
        self.assertLessEqual(
            avg_latency_ms,
            600.0,
            f"Average steering delivery latency ({avg_latency_ms:.2f}ms) exceeded 600ms SLA",
        )
        self.assertLessEqual(
            max_latency_ms,
            600.0,
            f"Max steering delivery latency ({max_latency_ms:.2f}ms) exceeded 600ms spike limit",
        )

    def test_12_broadcast_steering_fails_closed_when_no_tasks_discovered(self):
        """Verify that broadcast steering (--task all) raises RuntimeError when no tasks discovered."""
        empty_session = f"empty-sess-{int(time.time() * 1000)}"
        orch = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=empty_session,
            is_worker=False,
            local_dir=self.storage_root,
        )
        with self.assertRaises(RuntimeError) as cm:
            steer_task(
                task="all",
                instruction="Cancel exploration",
                session_id=empty_session,
                messenger=orch,
                max_tasks=None,
            )
        self.assertIn("Broadcast steering failed: No tasks discovered", str(cm.exception))

    def test_13_sequence_resolution_fails_closed_on_persistent_gcs_failure(self):
        """Verify sequence resolution fails closed (RuntimeError) and does not default to 0 on persistent failure."""
        orch = self._create_messenger(is_worker=False)

        # Mock list_blobs to simulate persistent network timeouts
        with patch.object(orch.bucket, "list_blobs", side_effect=TimeoutError("Persistent connection timeout")):
            with self.assertRaises(RuntimeError) as cm:
                orch.send_steer(task_index=0, instruction="Should fail safely", max_retries=1, retry_delay=0.01)
            self.assertIn("GCS sequence resolution failed", str(cm.exception))

    def test_14_storage_prefix_alignment_swarms_hierarchy(self):
        """Verify StorageMessenger normalizes session prefixes to swarms/<session_id>."""
        msg1 = StorageMessenger(bucket_name="bkt", session_id="test-123", is_worker=False, local_dir=self.storage_root)
        self.assertEqual(msg1._session_prefix(), "swarms/test-123")

        msg2 = StorageMessenger(bucket_name="bkt", session_id="swarm-test-123", is_worker=False, local_dir=self.storage_root)
        self.assertEqual(msg2._session_prefix(), "swarms/test-123")

        msg3 = StorageMessenger(bucket_name="bkt", session_id="swarms/test-123", is_worker=False, local_dir=self.storage_root)
        self.assertEqual(msg3._session_prefix(), "swarms/test-123")

    def test_15_steering_context_preserved_alongside_stagnancy_warning(self):
        """Verify that when a tool call is stagnant and steer is pending, both contexts are preserved."""
        orch = self._create_messenger(is_worker=False)
        worker = self._create_messenger(task_index=4, is_worker=True)

        fake_hooks = FakeHooks()
        fake_types = MagicMock()
        fake_types.HookResult = FakeHookResult

        tracker = StagnancyTracker()
        hooks = create_agent_hooks(
            messenger=worker,
            task_index=4,
            tracker=tracker,
            hooks_module=fake_hooks,
            types_module=fake_types,
        )
        pre_hook = hooks[0]

        tool_call = MagicMock()
        tool_call.name = "list_dir"
        tool_call.args = {"DirectoryPath": "/tmp"}

        # Simulate 2 prior calls to establish consecutive call pattern
        asyncio.run(pre_hook(tool_call))
        asyncio.run(pre_hook(tool_call))

        # Deliver steering directive immediately before the stagnant 3rd call
        steer_text = "Pivot to breadth-first search"
        orch.send_steer(task_index=4, instruction=steer_text)

        # Third identical call triggers stagnancy (count >= 3) AND consumes pending steer
        res = asyncio.run(pre_hook(tool_call))
        self.assertTrue(res.allow)
        self.assertIn(steer_text, res.custom_context)
        self.assertIn("consecutive times with identical arguments", res.custom_context)

    def test_16_concurrent_send_steer_collision_retry(self):
        """Simulate two simultaneous send_steer() calls colliding on sequence number,
        verifying both succeed with distinct sequence numbers."""
        import concurrent.futures
        import threading
        from unittest.mock import patch

        orch = self._create_messenger(is_worker=False)
        worker = self._create_messenger(task_index=0, is_worker=True)

        orig_list_blobs = orch.bucket.list_blobs
        barrier = threading.Barrier(2)
        barrier_passed = threading.Event()

        def sync_list_blobs(*args, **kwargs):
            res = orig_list_blobs(*args, **kwargs)
            if not barrier_passed.is_set():
                try:
                    barrier.wait(timeout=3.0)
                    barrier_passed.set()
                except Exception:
                    pass
            return res

        with patch.object(orch.bucket, "list_blobs", side_effect=sync_list_blobs):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f1 = executor.submit(orch.send_steer, 0, "Concurrent directive A")
                f2 = executor.submit(orch.send_steer, 0, "Concurrent directive B")
                env1 = f1.result(timeout=5.0)
                env2 = f2.result(timeout=5.0)

        self.assertIsNotNone(env1)
        self.assertIsNotNone(env2)
        self.assertNotEqual(env1.seq, env2.seq)
        self.assertEqual({env1.seq, env2.seq}, {1, 2})

        steers = worker.check_steer_instructions()
        self.assertEqual(len(steers), 2)
        steer_seqs = {s.seq for s in steers}
        self.assertEqual(steer_seqs, {1, 2})
        instructions = {s.payload.get("instruction") for s in steers}
        self.assertEqual(instructions, {"Concurrent directive A", "Concurrent directive B"})

    def test_17_send_steer_retries_on_precondition_failed_collision(self):
        """Verify send_steer retries when PreconditionFailed (HTTP 412) is raised during upload."""
        from storage_messenger import PreconditionFailed
        from unittest.mock import patch

        orch = self._create_messenger(is_worker=False)
        call_count = 0
        real_blob_factory = orch.bucket.blob

        def mock_blob(name: str):
            blob = real_blob_factory(name)
            orig_upload = blob.upload_from_string

            def mock_upload(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    real_blob_factory(name).upload_from_string("{}", content_type="application/json")
                    raise PreconditionFailed("Simulated HTTP 412 Precondition Failed")
                return orig_upload(*args, **kwargs)

            blob.upload_from_string = mock_upload
            return blob

        with patch.object(orch.bucket, "blob", side_effect=mock_blob):
            env = orch.send_steer(task_index=0, instruction="Retry on 412 test")

        self.assertIsNotNone(env)
        self.assertEqual(env.seq, 2)
        self.assertEqual(call_count, 2)

    def test_18_mailbox_controller_modular_import(self):
        """Verify mailbox CLI handlers are modularly importable from dispatch.mailbox_controller."""
        from dispatch.mailbox_controller import (
            handle_mailbox_list as mc_list,
            handle_mailbox_reply as mc_reply,
            handle_mailbox_steer as mc_steer,
        )
        self.assertTrue(callable(mc_list))
        self.assertTrue(callable(mc_reply))
        self.assertTrue(callable(mc_steer))


if __name__ == "__main__":
    unittest.main()

