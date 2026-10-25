#!/usr/bin/env python3
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Union

try:
    from worker.execution import CREDENTIAL_PATTERNS
except ImportError:
    try:
        from skills.swarm.scripts.worker.execution import CREDENTIAL_PATTERNS
    except ImportError:
        CREDENTIAL_PATTERNS = [
            re.compile(r"ghp_[A-Za-z0-9_]{36,}"),
            re.compile(r"AIza[0-9A-Za-z-_]{35}"),
            re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
            re.compile(r"ya29\.[0-9A-Za-z-_]+"),
            re.compile(r"Bearer [A-Za-z0-9_\-\.]+"),
        ]


def is_sensitive_path(path: Path, root: Path) -> bool:
    try:
        p = Path(path)
        root_path = Path(root)
        full_path = p if p.is_absolute() else (root_path / p)
        if os.path.islink(full_path) or full_path.is_symlink():
            return True
        r = root_path.resolve()
        resolved = full_path.resolve()
        curr = full_path.parent
        while curr != root_path and curr.resolve() != r and curr != curr.parent:
            if os.path.islink(curr) or curr.is_symlink():
                return True
            curr = curr.parent
        if r != resolved and r not in resolved.parents:
            return True
        parts = resolved.relative_to(r).parts
        if ".git" in parts or ".git" in p.parts or ".git" in full_path.parts:
            return True
        sensitive_patterns = [
            ".env",
            ".env.*",
            "*.pem",
            "*.key",
            "id_rsa*",
            "id_ed25519*",
            "credentials.json",
            "token.json",
        ]
        for pattern in sensitive_patterns:
            if fnmatch.fnmatch(full_path.name.lower(), pattern.lower()):
                return True
            if fnmatch.fnmatch(resolved.name.lower(), pattern.lower()):
                return True
        for part in parts:
            for pattern in sensitive_patterns:
                if fnmatch.fnmatch(part.lower(), pattern.lower()):
                    return True
        return False
    except Exception:
        return True


def file_contains_credentials(path: Path) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    try:
        content = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            content = p.read_bytes().decode("utf-8", errors="ignore")
        except Exception:
            return False
    for pat in CREDENTIAL_PATTERNS:
        if pat.search(content):
            return True
    return False



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


def _generate_git_patch(
    repo_dir: Path,
    candidate_files: Optional[List[str]] = None,
    commit_sha: Optional[str] = None,
) -> str:
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
    if commit_sha and str(commit_sha).strip():
        sha = str(commit_sha).strip()
        commands = [
            ["git", "diff", f"{sha}~1", sha] + scope,
        ]
    else:
        # If commit_sha is NOT provided (commit failed or uncommitted changes),
        # do NOT diff HEAD~1 HEAD to avoid leaking unrelated commits.
        commands = [
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
    commit_sha: Optional[str] = None,
    *,
    evidence_files: Optional[List[str]] = None,
) -> Dict[str, str]:
    repo = Path(repo_dir)
    clean_prefix = prefix.strip().strip("/")
    task_dir = f"task-{task_index}"
    target_prefix = f"{clean_prefix}/{task_dir}" if clean_prefix else task_dir

    uploaded: Dict[str, str] = {}

    delivery_errors: List[str] = []
    proposed_pass = status == "PASS"
    evidence_paths: List[Path] = []
    root = repo.resolve()

    for relative in evidence_files or []:
        raw_path = root / relative
        if is_sensitive_path(raw_path, root):
            delivery_errors.append(f"Evidence path is sensitive or outside repository: {relative}")
            continue
        path = raw_path.resolve()
        if is_sensitive_path(path, root):
            delivery_errors.append(f"Evidence path is sensitive or outside repository: {relative}")
            continue
        if path.is_dir():
            for child in path.rglob("*"):
                if is_sensitive_path(child, root):
                    delivery_errors.append(
                        f"Evidence path is sensitive or outside repository: {child.relative_to(root).as_posix() if root in child.resolve().parents else child}"
                    )
                elif child.is_file():
                    evidence_paths.append(child)
        elif path.is_file():
            evidence_paths.append(path)
        else:
            delivery_errors.append(f"Evidence file missing: {relative}")

    diagnostics = root / ".agystack/diagnostics"
    if diagnostics.is_dir():
        for diag in diagnostics.glob("*.log"):
            if is_sensitive_path(diag, root):
                delivery_errors.append(f"Diagnostic path is sensitive: {diag.name}")
            elif diag.is_file():
                evidence_paths.append(diag)

    for path in sorted(set(evidence_paths)):
        resolved = path.resolve()
        if not resolved.is_file():
            continue
        rel_name = path.relative_to(root).as_posix() if root in resolved.parents else path.name
        if is_sensitive_path(path, root):
            delivery_errors.append(f"Evidence path is sensitive: {rel_name}")
            continue
        if file_contains_credentials(path):
            delivery_errors.append(f"Evidence file contains credentials: {rel_name}")
            continue

        name = f"evidence/{rel_name}"
        dest = f"{target_prefix}/{name}"
        if upload_to_gcs(bucket_name, dest, path):
            uploaded[name] = f"gs://{bucket_name}/{dest}"
        else:
            delivery_errors.append(f"Evidence upload failed: {name}")

    if delivery_errors and proposed_pass:
        status = "ISSUES"

    patch_uploaded = False
    if candidate_files or (status == "PASS" and candidate_files is None):
        patch_name = "patch.diff" if status == "PASS" else "partial.patch.diff"
        patch_path = repo / patch_name
        if candidate_files or not patch_path.is_file():
            patch_content = _generate_git_patch(repo, candidate_files=candidate_files, commit_sha=commit_sha)
            if patch_content:
                patch_path.write_text(patch_content, encoding="utf-8")

        if patch_path.is_file() and patch_path.stat().st_size > 0:
            if is_sensitive_path(patch_path, root):
                delivery_errors.append(f"Candidate patch path is sensitive: {patch_name}")
            elif file_contains_credentials(patch_path):
                delivery_errors.append(f"Candidate patch contains credentials: {patch_name}")
            else:
                dest = f"{target_prefix}/{patch_name}"
                if upload_to_gcs(bucket_name, dest, patch_path):
                    uploaded[patch_name] = f"gs://{bucket_name}/{dest}"
                    patch_uploaded = True
                else:
                    delivery_errors.append(f"Candidate patch upload failed: {patch_name}")

        if candidate_files and not patch_uploaded:
            delivery_errors.append("Candidate patch failed to upload or is missing under zero-push delivery.")
            if status == "PASS":
                status = "ISSUES"

    # Upload score.json and results.tsv
    score_path = repo / "score.json"
    if score_path.is_file():
        if is_sensitive_path(score_path, root):
            delivery_errors.append("score.json is a sensitive path")
        elif file_contains_credentials(score_path):
            delivery_errors.append("score.json contains credentials")
        else:
            dest = f"{target_prefix}/score.json"
            if upload_to_gcs(bucket_name, dest, score_path):
                uploaded["score.json"] = f"gs://{bucket_name}/{dest}"
            else:
                delivery_errors.append("score.json upload failed")

    results_path = repo / "results.tsv"
    if results_path.is_file():
        if is_sensitive_path(results_path, root):
            delivery_errors.append("results.tsv is a sensitive path")
        elif file_contains_credentials(results_path):
            delivery_errors.append("results.tsv contains credentials")
        else:
            dest = f"{target_prefix}/results.tsv"
            if upload_to_gcs(bucket_name, dest, results_path):
                uploaded["results.tsv"] = f"gs://{bucket_name}/{dest}"
            else:
                delivery_errors.append("results.tsv upload failed")

    # Finalize delivery_errors and degrade status from PASS to ISSUES if delivery_errors is non-empty
    if delivery_errors and status == "PASS":
        status = "ISSUES"

    # Write and upload status.json LAST with the finalized status.
    status_path = repo / "status.json"
    status_data = {}
    if status_path.is_file():
        try:
            status_data = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            status_data = {}
    status_data["task_index"] = task_index
    status_data["status"] = status
    status_data["artifacts"] = uploaded
    if delivery_errors:
        status_data["evidence"] = "\n".join(delivery_errors)
        status_data["delivery_errors"] = delivery_errors
    else:
        status_data.pop("delivery_errors", None)
    status_path.write_text(json.dumps(status_data, indent=2), encoding="utf-8")

    dest = f"{target_prefix}/status.json"
    if upload_to_gcs(bucket_name, dest, status_path):
        uploaded["status.json"] = f"gs://{bucket_name}/{dest}"
    else:
        delivery_errors.append("status.json upload failed")

    return uploaded
