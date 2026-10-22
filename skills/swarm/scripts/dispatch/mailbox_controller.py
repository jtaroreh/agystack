#!/usr/bin/env python3
"""
Mailbox CLI administration and orchestration controller for Cloud Run swarm workers.
Provides commands for listing pending questions, replying to worker questions,
and delivering conversational steering directives to worker mailboxes in GCS.
"""

import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Union

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from storage_messenger import StorageMessenger
except ImportError:
    StorageMessenger = None  # type: ignore


def find_runtime_config() -> Optional[Dict[str, Any]]:
    paths_to_check = [
        Path("agystack-runtime.json"),
        Path(".agents/plugins/agystack/agystack-runtime.json"),
        Path(os.path.expanduser("~/.gemini/config/plugins/agystack/agystack-runtime.json")),
    ]
    for path in paths_to_check:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                print(f"Warning: Failed to parse runtime config at {path}: {exc}", file=sys.stderr)
    return None


def handle_mailbox_list(
    session_id: str,
    bucket_name: Optional[str] = None,
    messenger: Optional[Any] = None,
) -> List[Any]:
    if messenger is None:
        if not bucket_name:
            runtime_cfg = find_runtime_config() or {}
            bucket_name = runtime_cfg.get("gcs_bucket") or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        if not bucket_name:
            print("Error: GCS bucket name must be specified via --gcs-bucket, GCS_BUCKET, or agystack-runtime.json", file=sys.stderr)
            sys.exit(1)
        if StorageMessenger is None:
            print("Error: StorageMessenger is not available", file=sys.stderr)
            sys.exit(1)
        messenger = StorageMessenger(bucket_name=bucket_name, session_id=session_id, is_worker=False)

    pending = messenger.list_pending_questions()
    if not pending:
        print(f"No pending questions for session \x27{session_id}\x27.")
    else:
        print(f"\nPending questions for session \x27{session_id}\x27:")
        print(f"{'TASK':<6} | {'SEQ':<5} | {'TIMESTAMP':<20} | {'QUESTION'}")
        print("-" * 75)
        for q in pending:
            q_text = q.payload.get("question", "")
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(q.timestamp))
            print(f"{q.task_index:<6} | {q.seq:<5} | {ts_str:<20} | {q_text}")
    return pending


def handle_mailbox_reply(
    task_index: int,
    seq: int,
    text: str,
    session_id: str,
    bucket_name: Optional[str] = None,
    messenger: Optional[Any] = None,
) -> Any:
    if messenger is None:
        if not bucket_name:
            runtime_cfg = find_runtime_config() or {}
            bucket_name = runtime_cfg.get("gcs_bucket") or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        if not bucket_name:
            print("Error: GCS bucket name must be specified via --gcs-bucket, GCS_BUCKET, or agystack-runtime.json", file=sys.stderr)
            sys.exit(1)
        if StorageMessenger is None:
            print("Error: StorageMessenger is not available", file=sys.stderr)
            sys.exit(1)
        messenger = StorageMessenger(bucket_name=bucket_name, session_id=session_id, is_worker=False)

    reply_env = messenger.send_reply(task_index=task_index, seq=seq, reply_text=text)
    print(f"Reply sent to task {task_index} (seq {seq}): {text}")
    return reply_env


def handle_mailbox_steer(
    task_index: Union[int, str],
    text: str,
    session_id: str,
    bucket_name: Optional[str] = None,
    messenger: Optional[Any] = None,
    dashboard_writer: Optional[Any] = None,
    max_tasks: Optional[int] = None,
) -> Any:
    if messenger is None:
        if not bucket_name:
            runtime_cfg = find_runtime_config() or {}
            bucket_name = runtime_cfg.get("gcs_bucket") or os.environ.get("GCS_BUCKET") or os.environ.get("GCS_RESULTS_BUCKET")
        if not bucket_name:
            print("Error: GCS bucket name must be specified via --gcs-bucket, GCS_BUCKET, or agystack-runtime.json", file=sys.stderr)
            sys.exit(1)
        if StorageMessenger is None:
            print("Error: StorageMessenger is not available", file=sys.stderr)
            sys.exit(1)
        messenger = StorageMessenger(bucket_name=bucket_name, session_id=session_id, is_worker=False)

    try:
        from steer_cloud_task import steer_task
        envs = steer_task(
            task=task_index,
            instruction=text,
            session_id=session_id,
            bucket_name=bucket_name,
            messenger=messenger,
            max_tasks=max_tasks,
            dashboard_writer=dashboard_writer,
        )
        for env in envs:
            print(f"Steer instruction sent to task {env.task_index} (seq {env.seq}): {text}")
        if isinstance(task_index, str) and task_index.strip().lower() == "all":
            return envs
        return envs[0] if envs else None
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error delivering steering instruction: {exc}", file=sys.stderr)
        sys.exit(1)
