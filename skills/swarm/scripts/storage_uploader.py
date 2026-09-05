#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional


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


def _generate_git_patch(repo_dir: Path) -> str:
    if not (repo_dir / ".git").exists():
        return ""
    commands = [
        ["git", "diff", "HEAD~1", "HEAD"],
        ["git", "diff", "origin/main", "HEAD"],
        ["git", "diff", "HEAD"],
        ["git", "diff"],
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
) -> Dict[str, str]:
    repo = Path(repo_dir)
    clean_prefix = prefix.strip().strip("/")
    task_dir = f"task-{task_index}"
    target_prefix = f"{clean_prefix}/{task_dir}" if clean_prefix else task_dir

    uploaded: Dict[str, str] = {}

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

    patch_path = repo / "patch.diff"
    if not patch_path.is_file():
        patch_content = _generate_git_patch(repo)
        if patch_content:
            patch_path.write_text(patch_content, encoding="utf-8")

    if patch_path.is_file() and patch_path.stat().st_size > 0:
        dest = f"{target_prefix}/patch.diff"
        if upload_to_gcs(bucket_name, dest, patch_path):
            uploaded["patch.diff"] = f"gs://{bucket_name}/{dest}"

    return uploaded
