#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Union


def get_oauth_token() -> Optional[str]:
    env_token = os.environ.get("GCS_OAUTH_TOKEN") or os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                token = payload.get("access_token")
                if token:
                    return token
    except Exception:
        pass

    try:
        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
        )
        credentials.refresh(google.auth.transport.requests.Request())
        if credentials.token:
            return credentials.token
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        token = res.stdout.strip()
        if token:
            return token
    except Exception:
        pass

    return None


def upload_to_gcs(bucket_name: str, object_name: str, local_file_path: Path) -> bool:
    path = Path(local_file_path)
    if not path.is_file():
        return False

    local_dir = os.environ.get("STORAGE_MESSENGER_LOCAL_DIR")
    if local_dir:
        dest = Path(local_dir) / bucket_name / object_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(path, dest)
        return True

    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_filename(str(path))
        return True
    except ImportError:
        pass
    except Exception as exc:
        print(
            f"Warning: google.cloud.storage upload failed: {exc}, falling back to REST API",
            file=sys.stderr,
        )

    token = get_oauth_token()
    if not token:
        print("Error: Unable to acquire GCP OAuth token for GCS upload", file=sys.stderr)
        return False

    encoded_bucket = urllib.parse.quote(bucket_name, safe="")
    encoded_name = urllib.parse.quote(object_name, safe="")
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{encoded_bucket}/o?uploadType=media&name={encoded_name}"

    try:
        data = path.read_bytes()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        print(
            f"Error uploading {path} to gs://{bucket_name}/{object_name}: {exc}",
            file=sys.stderr,
        )
        return False


def upload_artifact(
    bucket_name: str,
    object_name: str,
    content: Union[str, bytes, Path],
    content_type: str = "application/json",
) -> bool:
    """Uploads an artifact (string content, bytes, or file path) to GCS."""
    if isinstance(content, Path) or (isinstance(content, str) and os.path.isfile(content)):
        return upload_to_gcs(bucket_name, object_name, Path(content))

    data_bytes = content.encode("utf-8") if isinstance(content, str) else content

    local_dir = os.environ.get("STORAGE_MESSENGER_LOCAL_DIR")
    if local_dir:
        dest = Path(local_dir) / bucket_name / object_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data_bytes)
        return True

    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(data_bytes, content_type=content_type)
        return True
    except Exception:
        pass

    token = get_oauth_token()
    if token:
        encoded_bucket = urllib.parse.quote(bucket_name, safe="")
        encoded_name = urllib.parse.quote(object_name, safe="")
        url = f"https://storage.googleapis.com/upload/storage/v1/b/{encoded_bucket}/o?uploadType=media&name={encoded_name}"
        try:
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": content_type,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if 200 <= resp.status < 300:
                    return True
        except Exception:
            pass

    try:
        import tempfile

        with tempfile.NamedTemporaryFile("wb", delete=False) as tf:
            tf.write(data_bytes)
            tf_path = Path(tf.name)
        try:
            res = subprocess.run(
                ["gcloud", "storage", "cp", str(tf_path), f"gs://{bucket_name}/{object_name}"],
                capture_output=True,
                check=False,
                timeout=15,
            )
            if res.returncode == 0:
                return True
        finally:
            tf_path.unlink(missing_ok=True)
    except Exception:
        pass

    return False


def _generate_git_patch(repo_dir: Path, candidate_files: Optional[List[str]] = None) -> str:
    if not (repo_dir / ".git").exists():
        return ""
    try:
        add_cmd = ["git", "add", "-N"]
        if candidate_files:
            add_cmd.extend(["--"] + candidate_files)
        else:
            add_cmd.append(".")
        subprocess.run(
            add_cmd,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        pass

    scope = ["--"] + candidate_files if candidate_files else []
    commands = [
        ["git", "diff", "HEAD~1", "HEAD"] + scope,
        ["git", "diff", "origin/main", "HEAD"] + scope,
        ["git", "diff", "HEAD"] + scope,
        ["git", "diff", "--cached"] + scope,
        ["git", "diff"] + scope,
    ]
    for cmd in commands:
        try:
            res = subprocess.run(
                cmd,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout
        except Exception:
            continue
    return ""


def upload_run_artifacts(
    bucket_name: str,
    prefix: str,
    repo_dir: Path,
    task_index: int,
    status: str = "UNKNOWN",
    candidate_files: Optional[List[str]] = None,
) -> Dict[str, str]:
    repo = Path(repo_dir)
    clean_prefix = prefix.strip().strip("/")
    task_dir = f"task-{task_index}"
    target_prefix = f"{clean_prefix}/{task_dir}" if clean_prefix else task_dir

    uploaded: Dict[str, str] = {}

    status_path = repo / "status.json"
    if status_path.is_file():
        dest = f"{target_prefix}/status.json"
        if upload_to_gcs(bucket_name, dest, status_path):
            uploaded["status.json"] = f"gs://{bucket_name}/{dest}"

    score_path = repo / "score.json"
    if score_path.is_file():
        dest = f"{target_prefix}/score.json"
        if upload_to_gcs(bucket_name, dest, score_path):
            uploaded["score.json"] = f"gs://{bucket_name}/{dest}"

    results_path = repo / "results.tsv"
    if results_path.is_file():
        dest = f"{target_prefix}/results.tsv"
        if upload_to_gcs(bucket_name, dest, results_path):
            uploaded["results.tsv"] = f"gs://{bucket_name}/{dest}"

    # Under zero-push architecture, patch.diff is only generated and uploaded when status == "PASS"
    if status == "PASS":
        patch_path = repo / "patch.diff"
        if not patch_path.is_file():
            patch_content = _generate_git_patch(repo, candidate_files=candidate_files)
            if patch_content:
                patch_path.write_text(patch_content, encoding="utf-8")

        if patch_path.is_file() and patch_path.stat().st_size > 0:
            dest = f"{target_prefix}/patch.diff"
            if upload_to_gcs(bucket_name, dest, patch_path):
                uploaded["patch.diff"] = f"gs://{bucket_name}/{dest}"

    return uploaded
