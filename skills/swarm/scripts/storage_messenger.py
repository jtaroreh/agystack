#!/usr/bin/env python3
"""
Storage messenger for bidirectional orchestrator-to-cloud-agent communication.
Provides mailbox envelope domain models, atomic outbox/inbox object routing over GCS,
and a local directory adapter for unit testing.
"""

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union
import urllib.error
import urllib.parse
import urllib.request


class MessageType(str, Enum):
    QUESTION = "question"
    REPLY = "reply"
    STEER = "steer"
    STATUS = "status"


class MessageStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    TIMED_OUT = "timed_out"


@dataclass
class MailboxEnvelope:
    session_id: str
    task_index: int
    seq: int
    msg_type: MessageType
    sender: str
    recipient: str
    timestamp: float
    payload: Dict[str, Any]
    status: MessageStatus = MessageStatus.PENDING
    reply_to_seq: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_index": self.task_index,
            "seq": self.seq,
            "msg_type": self.msg_type.value if isinstance(self.msg_type, Enum) else str(self.msg_type),
            "sender": self.sender,
            "recipient": self.recipient,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "status": self.status.value if isinstance(self.status, Enum) else str(self.status),
            "reply_to_seq": self.reply_to_seq,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MailboxEnvelope":
        raw_type = data.get("msg_type", MessageType.QUESTION)
        msg_type = MessageType(raw_type) if isinstance(raw_type, str) else raw_type
        raw_status = data.get("status", MessageStatus.PENDING)
        status = MessageStatus(raw_status) if isinstance(raw_status, str) else raw_status

        return cls(
            session_id=str(data.get("session_id", "")),
            task_index=int(data.get("task_index", 0)),
            seq=int(data.get("seq", 0)),
            msg_type=msg_type,
            sender=str(data.get("sender", "")),
            recipient=str(data.get("recipient", "")),
            timestamp=float(data.get("timestamp", time.time())),
            payload=dict(data.get("payload", {})),
            status=status,
            reply_to_seq=data.get("reply_to_seq"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "MailboxEnvelope":
        return cls.from_dict(json.loads(json_str))


class _GcsRestBlob:
    def __init__(self, bucket_name: str, name: str, token: str):
        self.bucket_name = bucket_name
        self.name = name.replace("\\", "/")
        self.token = token

    def exists(self) -> bool:
        encoded_bkt = urllib.parse.quote(self.bucket_name, safe="")
        encoded_name = urllib.parse.quote(self.name, safe="")
        url = f"https://storage.googleapis.com/storage/v1/b/{encoded_bkt}/o/{encoded_name}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            return False
        except Exception:
            return False

    def upload_from_string(self, data: str, content_type: str = "application/json") -> None:
        encoded_bkt = urllib.parse.quote(self.bucket_name, safe="")
        encoded_name = urllib.parse.quote(self.name, safe="")
        url = f"https://storage.googleapis.com/upload/storage/v1/b/{encoded_bkt}/o?uploadType=media&name={encoded_name}"
        req = urllib.request.Request(
            url,
            data=data.encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": content_type},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"GCS upload failed with status {resp.status}")

    def download_as_text(self) -> str:
        encoded_bkt = urllib.parse.quote(self.bucket_name, safe="")
        encoded_name = urllib.parse.quote(self.name, safe="")
        url = f"https://storage.googleapis.com/storage/v1/b/{encoded_bkt}/o/{encoded_name}?alt=media"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"}, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")


class _GcsRestBucket:
    def __init__(self, name: str, token: str):
        self.name = name
        self.token = token

    def blob(self, name: str) -> _GcsRestBlob:
        return _GcsRestBlob(self.name, name, self.token)

    def list_blobs(self, prefix: str = "") -> List[_GcsRestBlob]:
        encoded_bkt = urllib.parse.quote(self.name, safe="")
        url = f"https://storage.googleapis.com/storage/v1/b/{encoded_bkt}/o"
        if prefix:
            encoded_prefix = urllib.parse.quote(prefix, safe="")
            url += f"?prefix={encoded_prefix}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                blobs = []
                for it in items:
                    name = it.get("name", "")
                    blobs.append(_GcsRestBlob(self.name, name, self.token))
                return sorted(blobs, key=lambda b: b.name)
        except Exception:
            return []


class _GcsRestClient:
    def __init__(self, token: str):
        self.token = token

    def bucket(self, name: str) -> _GcsRestBucket:
        return _GcsRestBucket(name, self.token)


class _LocalBlob:
    def __init__(self, root: Path, name: str):
        self.root = root
        self.name = name.replace("\\", "/")
        self.path = root / self.name

    def exists(self) -> bool:
        return self.path.is_file()

    def upload_from_string(self, data: str, content_type: str = "application/json") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(data, encoding="utf-8")

    def download_as_text(self) -> str:
        return self.path.read_text(encoding="utf-8")


class _LocalBucket:
    def __init__(self, root: Path):
        self.root = root

    def blob(self, name: str) -> _LocalBlob:
        return _LocalBlob(self.root, name)

    def list_blobs(self, prefix: str = "") -> List[_LocalBlob]:
        if not self.root.exists():
            return []
        clean_prefix = prefix.strip("/")
        blobs: List[_LocalBlob] = []
        pattern = f"{clean_prefix}*" if clean_prefix else "*"
        for p in self.root.glob(pattern):
            if p.is_file():
                rel = str(p.relative_to(self.root)).replace("\\", "/")
                blobs.append(_LocalBlob(self.root, rel))
        recursive_pattern = f"{clean_prefix}/**/*" if clean_prefix else "**/*"
        for p in self.root.glob(recursive_pattern):
            if p.is_file():
                rel = str(p.relative_to(self.root)).replace("\\", "/")
                if not any(b.name == rel for b in blobs):
                    blobs.append(_LocalBlob(self.root, rel))
        return sorted(blobs, key=lambda b: b.name)


class _LocalClient:
    def __init__(self, local_dir: Union[str, Path]):
        self.root = Path(local_dir)

    def bucket(self, name: str) -> _LocalBucket:
        return _LocalBucket(self.root / name)


class StorageMessenger:
    def __init__(
        self,
        bucket_name: str,
        session_id: str,
        task_index: int = 0,
        is_worker: bool = True,
        storage_client: Optional[Any] = None,
        local_dir: Optional[Union[str, Path]] = None,
    ):
        self.bucket_name = bucket_name.strip()
        self.session_id = session_id.strip() or "default"
        self.task_index = task_index
        self.is_worker = is_worker
        self._seen_steer_seqs: set = set()
        self._current_question_seq = 0

        # Setup client
        env_local = os.environ.get("STORAGE_MESSENGER_LOCAL_DIR")
        if local_dir:
            self.client = _LocalClient(local_dir)
        elif storage_client is not None:
            self.client = storage_client
        elif env_local:
            self.client = _LocalClient(env_local)
        else:
            try:
                from google.cloud import storage
                self.client = storage.Client()
            except Exception:
                token = None
                try:
                    import storage_uploader
                    token = storage_uploader.get_oauth_token()
                except Exception:
                    pass
                if token:
                    self.client = _GcsRestClient(token)
                else:
                    if bool(os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_TASK_INDEX")):
                        raise RuntimeError("GCS credentials unavailable in Cloud Run environment; cannot use local fallback")
                    import tempfile
                    self.client = _LocalClient(Path(tempfile.gettempdir()) / "agystack_storage")

        self.bucket = self.client.bucket(self.bucket_name)

        if self.is_worker:
            self._sync_existing_question_seq()

    def _session_prefix(self) -> str:
        if self.session_id.startswith("swarm-"):
            return self.session_id
        return f"swarm-{self.session_id}"

    def _outbox_question_path(self, task_index: int, seq: int) -> str:
        return f"{self._session_prefix()}/tasks/task-{task_index}/outbox/{seq:04d}_question.json"

    def _inbox_reply_path(self, task_index: int, seq: int) -> str:
        return f"{self._session_prefix()}/tasks/task-{task_index}/inbox/{seq:04d}_reply.json"

    def _inbox_steer_path(self, task_index: int, seq: int) -> str:
        return f"{self._session_prefix()}/tasks/task-{task_index}/inbox/{seq:04d}_steer.json"

    def _sync_existing_question_seq(self) -> None:
        prefix = f"{self._session_prefix()}/tasks/task-{self.task_index}/outbox/"
        try:
            blobs = self.bucket.list_blobs(prefix=prefix)
            max_seq = 0
            for b in blobs:
                name = getattr(b, "name", "")
                if "_question.json" in name:
                    base = name.split("/")[-1]
                    try:
                        seq_val = int(base.split("_")[0])
                        if seq_val > max_seq:
                            max_seq = seq_val
                    except ValueError:
                        pass
            self._current_question_seq = max_seq
        except Exception:
            pass

    def send_question(self, question: str, context: str = "") -> MailboxEnvelope:
        self._current_question_seq += 1
        seq = self._current_question_seq

        envelope = MailboxEnvelope(
            session_id=self.session_id,
            task_index=self.task_index,
            seq=seq,
            msg_type=MessageType.QUESTION,
            sender=f"worker-{self.task_index}",
            recipient="orchestrator",
            timestamp=time.time(),
            payload={"question": question, "context": context},
            status=MessageStatus.PENDING,
        )

        obj_path = self._outbox_question_path(self.task_index, seq)
        blob = self.bucket.blob(obj_path)
        blob.upload_from_string(envelope.to_json(), content_type="application/json")
        return envelope

    def wait_for_reply(
        self,
        seq: int,
        timeout_seconds: float = 600.0,
        poll_interval: float = 1.0,
    ) -> Optional[str]:
        obj_path = self._inbox_reply_path(self.task_index, seq)
        start_time = time.time()

        while (time.time() - start_time) < timeout_seconds:
            blob = self.bucket.blob(obj_path)
            if blob.exists():
                try:
                    content = blob.download_as_text()
                    envelope = MailboxEnvelope.from_json(content)
                    reply_text = (
                        envelope.payload.get("reply")
                        or envelope.payload.get("text")
                        or envelope.payload.get("answer")
                        or ""
                    )
                    try:
                        ack_env = MailboxEnvelope(
                            session_id=envelope.session_id,
                            task_index=envelope.task_index,
                            seq=envelope.seq,
                            msg_type=envelope.msg_type,
                            sender=envelope.sender,
                            recipient=envelope.recipient,
                            timestamp=envelope.timestamp,
                            payload=envelope.payload,
                            status=MessageStatus.ACKNOWLEDGED,
                            reply_to_seq=envelope.reply_to_seq,
                        )
                        blob.upload_from_string(ack_env.to_json(), content_type="application/json")
                    except Exception:
                        pass
                    return str(reply_text)
                except Exception:
                    pass
            time.sleep(poll_interval)

        return None

    def check_steer_instructions(self) -> List[MailboxEnvelope]:
        prefix = f"{self._session_prefix()}/tasks/task-{self.task_index}/inbox/"
        try:
            blobs = self.bucket.list_blobs(prefix=prefix)
        except Exception:
            return []

        steer_envelopes: List[MailboxEnvelope] = []
        for b in blobs:
            name = getattr(b, "name", "")
            if name.endswith("_steer.json"):
                try:
                    content = b.download_as_text()
                    envelope = MailboxEnvelope.from_json(content)
                    if envelope.seq not in self._seen_steer_seqs:
                        self._seen_steer_seqs.add(envelope.seq)
                        steer_envelopes.append(envelope)
                        try:
                            ack_env = MailboxEnvelope(
                                session_id=envelope.session_id,
                                task_index=envelope.task_index,
                                seq=envelope.seq,
                                msg_type=envelope.msg_type,
                                sender=envelope.sender,
                                recipient=envelope.recipient,
                                timestamp=envelope.timestamp,
                                payload=envelope.payload,
                                status=MessageStatus.ACKNOWLEDGED,
                                reply_to_seq=envelope.reply_to_seq,
                            )
                            b.upload_from_string(ack_env.to_json(), content_type="application/json")
                        except Exception:
                            pass
                except Exception:
                    continue

        steer_envelopes.sort(key=lambda env: env.seq)
        return steer_envelopes

    def list_pending_questions(self) -> List[MailboxEnvelope]:
        prefix = f"{self._session_prefix()}/tasks/"
        try:
            blobs = self.bucket.list_blobs(prefix=prefix)
        except Exception:
            return []

        question_blobs = [b for b in blobs if getattr(b, "name", "").endswith("_question.json")]
        pending_questions: List[MailboxEnvelope] = []

        for qb in question_blobs:
            try:
                content = qb.download_as_text()
                envelope = MailboxEnvelope.from_json(content)
                reply_path = self._inbox_reply_path(envelope.task_index, envelope.seq)
                reply_blob = self.bucket.blob(reply_path)
                if not reply_blob.exists() and envelope.status != MessageStatus.TIMED_OUT:
                    pending_questions.append(envelope)
            except Exception:
                continue

        pending_questions.sort(key=lambda env: (env.task_index, env.seq))
        return pending_questions

    def send_reply(self, task_index: int, seq: int, reply_text: str) -> MailboxEnvelope:
        envelope = MailboxEnvelope(
            session_id=self.session_id,
            task_index=task_index,
            seq=seq,
            msg_type=MessageType.REPLY,
            sender="orchestrator",
            recipient=f"worker-{task_index}",
            timestamp=time.time(),
            payload={"reply": reply_text, "text": reply_text},
            status=MessageStatus.PENDING,
            reply_to_seq=seq,
        )

        obj_path = self._inbox_reply_path(task_index, seq)
        blob = self.bucket.blob(obj_path)
        blob.upload_from_string(envelope.to_json(), content_type="application/json")
        return envelope

    def send_steer(self, task_index: int, instruction: str) -> MailboxEnvelope:
        prefix = f"{self._session_prefix()}/tasks/task-{task_index}/inbox/"
        max_seq = 0
        try:
            blobs = self.bucket.list_blobs(prefix=prefix)
            for b in blobs:
                name = getattr(b, "name", "")
                if "_steer.json" in name:
                    base = name.split("/")[-1]
                    try:
                        seq_val = int(base.split("_")[0])
                        if seq_val > max_seq:
                            max_seq = seq_val
                    except ValueError:
                        pass
        except Exception:
            pass

        steer_seq = max_seq + 1
        envelope = MailboxEnvelope(
            session_id=self.session_id,
            task_index=task_index,
            seq=steer_seq,
            msg_type=MessageType.STEER,
            sender="orchestrator",
            recipient=f"worker-{task_index}",
            timestamp=time.time(),
            payload={"instruction": instruction, "text": instruction},
            status=MessageStatus.PENDING,
        )

        obj_path = self._inbox_steer_path(task_index, steer_seq)
        blob = self.bucket.blob(obj_path)
        blob.upload_from_string(envelope.to_json(), content_type="application/json")
        return envelope
