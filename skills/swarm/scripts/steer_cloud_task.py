#!/usr/bin/env python3
"""
CLI utility and programmatic helper for conversational mailbox steering.
Provides structured envelope validation (task index, instruction text,
ABORT commands, sequence numbers) and dispatches steering instructions
to in-flight Cloud Run swarm worker mailboxes in GCS.
"""

import argparse
import os
from pathlib import Path
import sys
from typing import Any, List, Optional, Union

# Ensure sibling scripts directory is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from storage_messenger import MailboxEnvelope, StorageMessenger
except ImportError:
    StorageMessenger = None  # type: ignore
    MailboxEnvelope = None  # type: ignore


def validate_task_target(
    task: Union[int, str],
    max_tasks: Optional[int] = None,
) -> Union[int, str]:
    """
    Validates the target task parameter.
    Accepts positive integers or 'all' for broadcast steering.
    Raises ValueError on out-of-range or negative indices.
    """
    if isinstance(task, str):
        cleaned = task.strip().lower()
        if cleaned == "all":
            return "all"
        try:
            task_idx = int(cleaned)
        except ValueError:
            raise ValueError(f"Invalid task target '{task}': must be an integer index or 'all'")
    elif isinstance(task, int):
        task_idx = task
    else:
        raise ValueError(f"Invalid task target type: {type(task)}")

    if task_idx < 0:
        raise ValueError(f"Task index cannot be negative: {task_idx}")

    if max_tasks is not None and task_idx >= max_tasks:
        raise ValueError(f"Target task index {task_idx} is out of range (total tasks: {max_tasks})")

    return task_idx


def validate_instruction(instruction: str) -> str:
    """
    Validates steering instruction text.
    Ensures non-empty and trimmed string.
    """
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Steering instruction text must be a non-empty string")
    return instruction.strip()


def is_abort_command(instruction: str) -> bool:
    """
    Checks if the instruction represents an abort or cancel command.
    """
    trimmed = instruction.strip().upper()
    return trimmed.startswith("ABORT") or trimmed.startswith("CANCEL")


def validate_seq(seq: int) -> int:
    """
    Validates sequence numbers to enforce monotonicity.
    """
    if not isinstance(seq, int) or seq < 1:
        raise ValueError(f"Sequence number must be a positive integer >= 1, got {seq}")
    return seq


def steer_task(
    task: Union[int, str],
    instruction: str,
    session_id: str,
    bucket_name: Optional[str] = None,
    messenger: Optional[Any] = None,
    max_tasks: Optional[int] = None,
    dashboard_writer: Optional[Any] = None,
) -> List[Any]:
    """
    Programmatic helper to deliver conversational steering instructions.
    Validates inputs, connects to worker mailboxes via GCS, logs standardized
    delivery messages, updates dashboard if present, and returns the delivered envelopes.
    """
    valid_target = validate_task_target(task, max_tasks=max_tasks)
    valid_instruction = validate_instruction(instruction)

    if messenger is None:
        if not bucket_name:
            bucket_name = (
                os.environ.get("GCS_BUCKET")
                or os.environ.get("GCS_RESULTS_BUCKET")
                or ""
            )
        if not bucket_name:
            raise ValueError("GCS bucket name must be specified via bucket_name or GCS_BUCKET environment variable")
        if StorageMessenger is None:
            raise RuntimeError("StorageMessenger is not available")
        messenger = StorageMessenger(
            bucket_name=bucket_name,
            session_id=session_id,
            is_worker=False,
        )

    delivered_envelopes: List[Any] = []

    if valid_target == "all":
        # Broadcast to all tasks
        target_tasks: List[int] = []
        if hasattr(messenger, "discover_tasks"):
            target_tasks = messenger.discover_tasks()

        if not target_tasks and max_tasks is not None:
            target_tasks = list(range(max_tasks))

        if not target_tasks:
            raise RuntimeError("Broadcast steering failed: No tasks discovered")

        for t_idx in target_tasks:
            env = messenger.send_steer(task_index=t_idx, instruction=valid_instruction)
            validate_seq(env.seq)
            print(f"[STEER] Instruction delivered to task-{t_idx} mailbox in GCS")
            if dashboard_writer and hasattr(dashboard_writer, "update_task_steer"):
                dashboard_writer.update_task_steer(t_idx, valid_instruction)
                if hasattr(dashboard_writer, "write"):
                    try:
                        dashboard_writer.write()
                    except Exception:
                        pass
            delivered_envelopes.append(env)
    else:
        task_idx = int(valid_target)
        env = messenger.send_steer(task_index=task_idx, instruction=valid_instruction)
        validate_seq(env.seq)
        print(f"[STEER] Instruction delivered to task-{task_idx} mailbox in GCS")
        if dashboard_writer and hasattr(dashboard_writer, "update_task_steer"):
            dashboard_writer.update_task_steer(task_idx, valid_instruction)
            if hasattr(dashboard_writer, "write"):
                try:
                    dashboard_writer.write()
                except Exception:
                    pass
        delivered_envelopes.append(env)

    return delivered_envelopes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Steer Cloud Run swarm workers via conversational GCS mailboxes.",
    )
    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="Task index (e.g. 0, 1) or 'all' to broadcast to all workers",
    )
    parser.add_argument(
        "--instruction",
        "--text",
        dest="instruction",
        type=str,
        default=None,
        help="Steering instruction string (or ABORT/CANCEL directive)",
    )
    parser.add_argument(
        "--abort",
        action="store_true",
        help="Shortcut to send an ABORT directive",
    )
    parser.add_argument(
        "--session",
        "--session-id",
        dest="session_id",
        type=str,
        default=None,
        help="Swarm session ID",
    )
    parser.add_argument(
        "--gcs-bucket",
        type=str,
        default=None,
        help="GCS bucket name for run artifacts",
    )
    parser.add_argument(
        "--task-count",
        "--max-tasks",
        dest="max_tasks",
        type=int,
        default=None,
        help="Total task count in the swarm run (for out-of-range bounds checking)",
    )

    args = parser.parse_args()

    instruction = args.instruction
    if args.abort:
        instruction = instruction or "ABORT immediately requested by orchestrator"

    if not instruction:
        print("Error: Steering instruction must be specified via --instruction or --abort", file=sys.stderr)
        sys.exit(1)

    session_id = (
        args.session_id
        or os.environ.get("SWARM_SESSION_ID")
        or os.environ.get("SESSION_ID")
        or "default"
    )

    bucket_name = (
        args.gcs_bucket
        or os.environ.get("GCS_BUCKET")
        or os.environ.get("GCS_RESULTS_BUCKET")
    )

    try:
        steer_task(
            task=args.task,
            instruction=instruction,
            session_id=session_id,
            bucket_name=bucket_name,
            max_tasks=args.max_tasks,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error delivering steering instruction: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
