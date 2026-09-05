#!/usr/bin/env python3
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"))

from storage_messenger import (
    MailboxEnvelope,
    MessageStatus,
    MessageType,
    StorageMessenger,
)
from cloud_worker import create_ask_orchestrator_tool
from cloud_dispatch import (
    handle_mailbox_list,
    handle_mailbox_reply,
    handle_mailbox_steer,
)


class TestStorageMessenger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.temp_dir.name)
        self.bucket_name = "test-swarm-bucket"
        self.session_id = "test-session-001"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_envelope_serialization_and_deserialization(self):
        envelope = MailboxEnvelope(
            session_id="session-xyz",
            task_index=3,
            seq=7,
            msg_type=MessageType.QUESTION,
            sender="worker-3",
            recipient="orchestrator",
            timestamp=1725500000.0,
            payload={"question": "Should I refactor auth v1?", "context": "14 callers"},
            status=MessageStatus.PENDING,
            reply_to_seq=None,
        )

        d = envelope.to_dict()
        self.assertEqual(d["session_id"], "session-xyz")
        self.assertEqual(d["task_index"], 3)
        self.assertEqual(d["seq"], 7)
        self.assertEqual(d["msg_type"], "question")
        self.assertEqual(d["status"], "pending")
        self.assertEqual(d["payload"]["question"], "Should I refactor auth v1?")

        json_str = envelope.to_json()
        restored = MailboxEnvelope.from_json(json_str)
        self.assertEqual(restored.session_id, envelope.session_id)
        self.assertEqual(restored.task_index, envelope.task_index)
        self.assertEqual(restored.seq, envelope.seq)
        self.assertEqual(restored.msg_type, MessageType.QUESTION)
        self.assertEqual(restored.status, MessageStatus.PENDING)
        self.assertEqual(restored.payload, envelope.payload)

    def test_monotonic_sequence_numbers(self):
        worker_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=1,
            is_worker=True,
            local_dir=self.storage_root,
        )

        q1 = worker_messenger.send_question("Question 1")
        self.assertEqual(q1.seq, 1)

        q2 = worker_messenger.send_question("Question 2")
        self.assertEqual(q2.seq, 2)

        q3 = worker_messenger.send_question("Question 3")
        self.assertEqual(q3.seq, 3)

        expected_q1_path = (
            self.storage_root
            / self.bucket_name
            / f"swarm-{self.session_id}"
            / "tasks"
            / "task-1"
            / "outbox"
            / "0001_question.json"
        )
        self.assertTrue(expected_q1_path.is_file())

    def test_question_send_and_wait_reply_success(self):
        worker_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=2,
            is_worker=True,
            local_dir=self.storage_root,
        )
        orchestrator_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            is_worker=False,
            local_dir=self.storage_root,
        )

        q_env = worker_messenger.send_question("Need approval to delete old API")
        self.assertEqual(q_env.seq, 1)

        # Orchestrator sends reply
        reply_env = orchestrator_messenger.send_reply(
            task_index=2,
            seq=q_env.seq,
            reply_text="Approved. Proceed with deletion.",
        )
        self.assertEqual(reply_env.reply_to_seq, 1)

        # Worker waits and gets reply
        received_reply = worker_messenger.wait_for_reply(seq=1, timeout_seconds=2.0, poll_interval=0.01)
        self.assertEqual(received_reply, "Approved. Proceed with deletion.")

    def test_wait_reply_timeout(self):
        worker_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=4,
            is_worker=True,
            local_dir=self.storage_root,
        )

        worker_messenger.send_question("Unanswered question")
        received_reply = worker_messenger.wait_for_reply(seq=1, timeout_seconds=0.05, poll_interval=0.01)
        self.assertIsNone(received_reply)

    def test_create_ask_orchestrator_tool_success(self):
        worker_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=0,
            is_worker=True,
            local_dir=self.storage_root,
        )
        orchestrator_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            is_worker=False,
            local_dir=self.storage_root,
        )

        tool = create_ask_orchestrator_tool(worker_messenger, task_index=0, timeout_seconds=2.0)

        # Simulate async reply
        orchestrator_messenger.send_reply(task_index=0, seq=1, reply_text="Use schema v2.")

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            ans = asyncio.run(tool("Which schema should I use?"))
            self.assertEqual(ans, "Use schema v2.")
            output = mock_out.getvalue()
            self.assertIn("WAITING_FOR_ORCHESTRATOR", output)
            self.assertIn("ORCHESTRATOR_REPLY_RECEIVED", output)

    def test_create_ask_orchestrator_tool_timeout(self):
        worker_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=0,
            is_worker=True,
            local_dir=self.storage_root,
        )

        tool = create_ask_orchestrator_tool(worker_messenger, task_index=0, timeout_seconds=0.05)

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            ans = asyncio.run(tool("Is anyone there?"))
            self.assertIn("Orchestrator did not respond within timeout", ans)
            output = mock_out.getvalue()
            self.assertIn("ORCHESTRATOR_TIMEOUT", output)

    def test_steer_queuing_and_retrieval(self):
        worker_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=3,
            is_worker=True,
            local_dir=self.storage_root,
        )
        orchestrator_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            is_worker=False,
            local_dir=self.storage_root,
        )

        # Send two steering instructions
        orchestrator_messenger.send_steer(task_index=3, instruction="Fix unit tests first.")
        orchestrator_messenger.send_steer(task_index=3, instruction="Do not modify Cargo.lock.")

        # Worker retrieves steer instructions
        steer_msgs = worker_messenger.check_steer_instructions()
        self.assertEqual(len(steer_msgs), 2)
        self.assertEqual(steer_msgs[0].payload["instruction"], "Fix unit tests first.")
        self.assertEqual(steer_msgs[1].payload["instruction"], "Do not modify Cargo.lock.")

        # Second check returns empty because already processed
        steer_msgs_2 = worker_messenger.check_steer_instructions()
        self.assertEqual(len(steer_msgs_2), 0)

        # Adding a third steer instruction returns only the third
        orchestrator_messenger.send_steer(task_index=3, instruction="Run integration tests.")
        steer_msgs_3 = worker_messenger.check_steer_instructions()
        self.assertEqual(len(steer_msgs_3), 1)
        self.assertEqual(steer_msgs_3[0].payload["instruction"], "Run integration tests.")

    def test_list_pending_questions(self):
        w0 = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=0,
            is_worker=True,
            local_dir=self.storage_root,
        )
        w1 = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=1,
            is_worker=True,
            local_dir=self.storage_root,
        )
        orchestrator = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            is_worker=False,
            local_dir=self.storage_root,
        )

        w0.send_question("Question from task 0")
        w1.send_question("Question from task 1")

        pending = orchestrator.list_pending_questions()
        self.assertEqual(len(pending), 2)

        # Answer task 0's question
        orchestrator.send_reply(task_index=0, seq=1, reply_text="Answer to task 0")

        # Now only task 1 is pending
        pending_after = orchestrator.list_pending_questions()
        self.assertEqual(len(pending_after), 1)
        self.assertEqual(pending_after[0].task_index, 1)

    def test_cli_handle_mailbox_list(self):
        worker = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=2,
            is_worker=True,
            local_dir=self.storage_root,
        )
        worker.send_question("Test question from task 2")

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            pending = handle_mailbox_list(
                session_id=self.session_id,
                bucket_name=self.bucket_name,
                messenger=StorageMessenger(
                    bucket_name=self.bucket_name,
                    session_id=self.session_id,
                    is_worker=False,
                    local_dir=self.storage_root,
                ),
            )
            self.assertEqual(len(pending), 1)
            self.assertIn("Test question from task 2", mock_out.getvalue())

    def test_cli_handle_mailbox_reply(self):
        worker = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=5,
            is_worker=True,
            local_dir=self.storage_root,
        )
        worker.send_question("Pending approval")

        orch_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            is_worker=False,
            local_dir=self.storage_root,
        )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            env = handle_mailbox_reply(
                task_index=5,
                seq=1,
                text="Approved for merge",
                session_id=self.session_id,
                bucket_name=self.bucket_name,
                messenger=orch_messenger,
            )
            self.assertEqual(env.payload["reply"], "Approved for merge")
            self.assertIn("Reply sent to task 5", mock_out.getvalue())

        reply = worker.wait_for_reply(seq=1, timeout_seconds=1.0, poll_interval=0.01)
        self.assertEqual(reply, "Approved for merge")

    def test_cli_handle_mailbox_steer(self):
        worker = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            task_index=1,
            is_worker=True,
            local_dir=self.storage_root,
        )
        orch_messenger = StorageMessenger(
            bucket_name=self.bucket_name,
            session_id=self.session_id,
            is_worker=False,
            local_dir=self.storage_root,
        )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            env = handle_mailbox_steer(
                task_index=1,
                text="Focus on latency reduction",
                session_id=self.session_id,
                bucket_name=self.bucket_name,
                messenger=orch_messenger,
            )
            self.assertEqual(env.payload["instruction"], "Focus on latency reduction")
            self.assertIn("Steer instruction sent to task 1", mock_out.getvalue())

        steers = worker.check_steer_instructions()
        self.assertEqual(len(steers), 1)
        self.assertEqual(steers[0].payload["instruction"], "Focus on latency reduction")

    def test_mock_gcs_storage_client(self):
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True
        mock_blob.download_as_text.return_value = json.dumps({
            "session_id": "mock-sess",
            "task_index": 0,
            "seq": 1,
            "msg_type": "reply",
            "sender": "orchestrator",
            "recipient": "worker-0",
            "timestamp": time.time(),
            "payload": {"reply": "Mock reply"},
            "status": "pending",
        })

        messenger = StorageMessenger(
            bucket_name="gcp-bucket",
            session_id="mock-sess",
            task_index=0,
            is_worker=True,
            storage_client=mock_client,
        )

        reply = messenger.wait_for_reply(seq=1, timeout_seconds=1.0, poll_interval=0.01)
        self.assertEqual(reply, "Mock reply")
        mock_client.bucket.assert_called_with("gcp-bucket")


if __name__ == "__main__":
    unittest.main()
