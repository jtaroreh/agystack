import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

def run_cmd(cmd, check=True, capture_output=True):
    try:
        res = subprocess.run(cmd, check=check, capture_output=capture_output, text=True)
        return res
    except FileNotFoundError as e:
        if check:
            print(f"Command not found: {cmd[0]}", file=sys.stderr)
            sys.exit(1)
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr=str(e))
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(cmd)}\nError: {e.stderr}", file=sys.stderr)
        if check:
            sys.exit(1)
        return e

def check_gcloud():
    res = run_cmd(["gcloud", "--version"], check=False)
    if res.returncode != 0:
        return {"installed": False, "account": None}
    
    res = run_cmd(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], check=False)
    account = res.stdout.strip()
    return {"installed": True, "account": account if account else None}

def _parse_version(stdout):
    if not stdout:
        return None
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(stdout).strip())
    if match:
        patch = int(match.group(3)) if match.group(3) is not None else 0
        return match.group(0), int(match.group(1)), int(match.group(2)), patch
    return None


DEPENDENCY_SPECS = (
    {
        "name": "bun",
        "cmd": ["bun", "--version"],
        "required": True,
        "notes": "Mandatory runtime for orchestration and babysitting",
        "missing_error": "bun is not installed or not found on PATH",
        "min_major": 1,
        "min_error": "Bun version 1.0+ required, found {version_str}",
    },
    {
        "name": "gh",
        "cmd": ["gh", "--version"],
        "required": True,
        "notes": "Required for PR automation and preflight checks",
        "missing_error": "gh (GitHub CLI) is not installed or not found on PATH",
    },
    {
        "name": "gt",
        "cmd": ["gt", "--version"],
        "required": False,
        "notes": "Recommended for stacked PRs",
        "missing_error": "gt (Graphite CLI) is not installed",
    },
    {
        "name": "gcloud",
        "cmd": ["gcloud", "--version"],
        "required": False,
        "notes": "Required for Cloud Run parallel worker runtime",
        "missing_error": "gcloud is not installed",
    },
)

PYTHON_DEPENDENCY_SPECS = (
    {
        "name": "google.cloud.storage",
        "package": "google-cloud-storage",
        "required": False,
        "notes": "Required for GCS swarm artifact storage and patch harvesting",
    },
    {
        "name": "google.genai",
        "package": "google-genai",
        "required": False,
        "notes": "Required for Gemini API preflight probes and standalone models",
    },
    {
        "name": "google.cloud.run_v2",
        "package": "google-cloud-run",
        "required": False,
        "notes": "Optional client library for Cloud Run job monitoring",
    },
)


def check_python_dependencies(import_fn=None):
    if import_fn is None:
        import importlib
        import_fn = importlib.import_module

    deps = {}
    for spec in PYTHON_DEPENDENCY_SPECS:
        name = spec["name"]
        pkg = spec["package"]
        notes = spec.get("notes", "")
        required = spec.get("required", False)
        try:
            mod = import_fn(name)
            ver = getattr(mod, "__version__", "installed")
            deps[pkg] = {
                "installed": True,
                "version": ver if isinstance(ver, str) else "installed",
                "ok": True,
                "error": None,
                "notes": notes,
                "required": required,
            }
        except ImportError:
            deps[pkg] = {
                "installed": False,
                "version": None,
                "ok": not required,
                "error": f"Python package '{pkg}' is not installed (run: pip install {pkg})",
                "notes": notes,
                "required": required,
            }
        except Exception as exc:
            deps[pkg] = {
                "installed": False,
                "version": None,
                "ok": not required,
                "error": f"Failed to import '{name}': {exc}",
                "notes": notes,
                "required": required,
            }
    return deps


def check_dependencies(run_cmd_fn=None, include_python=True, import_fn=None):
    if run_cmd_fn is None:
        run_cmd_fn = run_cmd

    deps = {}
    for spec in DEPENDENCY_SPECS:
        name = spec["name"]
        cmd = spec["cmd"]
        required = spec.get("required", False)
        notes = spec.get("notes", "")
        missing_error = spec.get("missing_error", f"{name} is not installed")

        try:
            res = run_cmd_fn(cmd, check=False)
        except FileNotFoundError:
            deps[name] = {
                "installed": False,
                "version": None,
                "ok": False,
                "error": missing_error,
                "notes": notes,
                "required": required,
            }
            continue
        except Exception as e:
            deps[name] = {
                "installed": False,
                "version": None,
                "ok": False,
                "error": f"Failed to execute {name}: {e}",
                "notes": notes,
                "required": required,
            }
            continue

        returncode = getattr(res, "returncode", 1)
        stdout = getattr(res, "stdout", "") or ""
        stderr = getattr(res, "stderr", "") or ""
        if isinstance(stderr, str):
            stderr = stderr.strip()

        if returncode == 0:
            parsed = _parse_version(stdout)
            if parsed:
                version_str, major, _, _ = parsed
                min_major = spec.get("min_major")
                if min_major is not None and major is not None and major < min_major:
                    min_error_template = spec.get(
                        "min_error",
                        f"{name.capitalize()} version {min_major}.0+ required, found {{version_str}}"
                    )
                    deps[name] = {
                        "installed": True,
                        "version": version_str,
                        "ok": False,
                        "error": min_error_template.format(version_str=version_str),
                        "notes": notes,
                        "required": required,
                    }
                else:
                    deps[name] = {
                        "installed": True,
                        "version": version_str,
                        "ok": True,
                        "error": None,
                        "notes": notes,
                        "required": required,
                    }
            else:
                deps[name] = {
                    "installed": True,
                    "version": None,
                    "ok": False,
                    "error": f"Failed to parse {name} version from output",
                    "notes": notes,
                    "required": required,
                }
        elif returncode == 127:
            deps[name] = {
                "installed": False,
                "version": None,
                "ok": False,
                "error": missing_error,
                "notes": notes,
                "required": required,
            }
        else:
            deps[name] = {
                "installed": False,
                "version": None,
                "ok": False,
                "error": stderr if stderr else missing_error,
                "notes": notes,
                "required": required,
            }

    if include_python:
        py_deps = check_python_dependencies(import_fn=import_fn)
        deps.update(py_deps)

    return deps

def get_active_project():
    res = run_cmd(["gcloud", "config", "get-value", "project"], check=False)
    project = res.stdout.strip()
    return project if project else None

def list_projects():
    res = run_cmd(["gcloud", "projects", "list", "--format=json"], check=False)
    if res.returncode != 0:
        return []
    try:
        projects = json.loads(res.stdout.strip())
        return [{"projectId": p.get("projectId"), "name": p.get("name")} for p in projects]
    except json.JSONDecodeError:
        return []

def create_project(project_id):
    print(f"Creating project {project_id}...")
    run_cmd(["gcloud", "projects", "create", project_id])
    print("Setting active project...")
    run_cmd(["gcloud", "config", "set", "project", project_id])

def enable_apis(project_id):
    print(f"Enabling APIs for {project_id}...")
    run_cmd([
        "gcloud", "services", "enable",
        "run.googleapis.com",
        "artifactregistry.googleapis.com",
        "cloudbuild.googleapis.com",
        "aiplatform.googleapis.com",
        "storage.googleapis.com",
        "secretmanager.googleapis.com",
        f"--project={project_id}"
    ])

def ensure_gcs_bucket(bucket_name, project_id, region="us-central1"):
    clean_name = bucket_name[5:] if bucket_name.startswith("gs://") else bucket_name
    clean_name = clean_name.strip("/")
    bucket_uri = f"gs://{clean_name}"
    print(f"Checking if GCS bucket exists: {bucket_uri}...")
    res = run_cmd(["gcloud", "storage", "buckets", "describe", bucket_uri], check=False)
    if res.returncode != 0:
        print(f"Bucket {bucket_uri} does not exist. Creating in {region} for project {project_id}...")
        run_cmd([
            "gcloud", "storage", "buckets", "create", bucket_uri,
            f"--project={project_id}",
            f"--location={region}"
        ])
    else:
        print(f"Bucket {bucket_uri} already exists.")
    return clean_name

def get_project_number(project_id):
    res = run_cmd(["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"], check=False)
    if getattr(res, "returncode", 1) == 0:
        stdout = getattr(res, "stdout", "")
        if isinstance(stdout, str) and stdout.strip():
            return stdout.strip()
        elif stdout and not isinstance(stdout, str):
            val = str(stdout).strip()
            if val and "MagicMock" not in val:
                return val
    return None

def configure_iam_permissions(project_id, service_account=None):
    if not service_account:
        project_num = get_project_number(project_id)
        if project_num:
            service_account = f"{project_num}-compute@developer.gserviceaccount.com"
        else:
            service_account = f"{project_id}-compute@developer.gserviceaccount.com"

    member = service_account if service_account.startswith("serviceAccount:") else f"serviceAccount:{service_account}"
    roles = ["roles/aiplatform.user", "roles/storage.objectAdmin", "roles/secretmanager.secretAccessor"]
    for role in roles:
        print(f"Binding IAM role {role} to {member} in project {project_id}...")
        run_cmd([
            "gcloud", "projects", "add-iam-policy-binding", project_id,
            f"--member={member}",
            f"--role={role}"
        ])
    return service_account

def ensure_secret_manager(project_id, secret_name="agystack-gh-token", secret_val=None, service_account=None):
    print(f"Ensuring Secret Manager secret: {secret_name}...")
    res = run_cmd(["gcloud", "secrets", "describe", secret_name, f"--project={project_id}"], check=False)
    if getattr(res, "returncode", 1) != 0:
        print(f"Creating secret {secret_name} in project {project_id}...")
        run_cmd([
            "gcloud", "secrets", "create", secret_name,
            "--replication-policy=automatic",
            f"--project={project_id}"
        ])
    if secret_val:
        print(f"Adding new version to secret {secret_name}...")
        run_cmd([
            "gcloud", "secrets", "versions", "add", secret_name,
            "--data-file=-",
            f"--project={project_id}"
        ], check=False)
    if service_account:
        member = service_account if service_account.startswith("serviceAccount:") else f"serviceAccount:{service_account}"
        print(f"Binding roles/secretmanager.secretAccessor to {member} for {secret_name}...")
        run_cmd([
            "gcloud", "secrets", "add-iam-policy-binding", secret_name,
            f"--member={member}",
            "--role=roles/secretmanager.secretAccessor",
            f"--project={project_id}"
        ], check=False)
    return secret_name

def build_and_deploy_worker(project_id, region, image_tag, scripts_dir, job_name="agystack-swarm-worker", service_account=None):
    print(f"Creating Artifact Registry repository in {region}...")
    res = run_cmd([
        "gcloud", "artifacts", "repositories", "describe", "agystack",
        f"--location={region}",
        f"--project={project_id}"
    ], check=False)
    
    if res.returncode != 0:
        run_cmd([
            "gcloud", "artifacts", "repositories", "create", "agystack",
            "--repository-format=docker",
            f"--location={region}",
            f"--project={project_id}"
        ])
    
    staged_dirs = []
    scripts_path = Path(scripts_dir).resolve()
    repo_root = scripts_path.parents[2] if len(scripts_path.parents) >= 3 else scripts_path
    ignored_patterns = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".venv",
        "venv",
    }
    try:
        for folder in ("skills", "rules", "agents"):
            src = repo_root / folder
            dst = scripts_path / folder
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            if src.is_dir():
                dst_resolved = dst.resolve()

                def _ignore_copy(directory, contents):
                    dir_p = Path(directory).resolve()
                    ignored = set()
                    for item in contents:
                        if item in ignored_patterns:
                            ignored.add(item)
                            continue
                        resolved_item = (dir_p / item).resolve()
                        if resolved_item == dst_resolved or resolved_item == scripts_path:
                            ignored.add(item)
                    return ignored

                shutil.copytree(src, dst, ignore=_ignore_copy)
                staged_dirs.append(dst)

        print("Submitting Cloud Build...")
        run_cmd([
            "gcloud", "builds", "submit",
            f"--tag={image_tag}",
            scripts_dir,
            f"--project={project_id}"
        ], capture_output=False)
    finally:
        for staged in staged_dirs:
            try:
                shutil.rmtree(staged, ignore_errors=True)
            except Exception:
                pass
    
    print("Creating/Updating Cloud Run Job...")
    res = run_cmd([
        "gcloud", "run", "jobs", "describe", job_name,
        f"--region={region}",
        f"--project={project_id}"
    ], check=False)
    
    action = "update" if res.returncode == 0 else "create"
    cmd = [
        "gcloud", "run", "jobs", action, job_name,
        f"--image={image_tag}",
        f"--region={region}",
        f"--project={project_id}",
        "--tasks=1",
        "--task-timeout=30m",
        "--memory=2Gi",
        "--cpu=2",
        "--parallelism=16",
        "--max-retries=0",
    ]
    if service_account:
        cmd.append(f"--service-account={service_account}")
    run_cmd(cmd)

def write_runtime_config(project_id, region, job_name, image_tag, auth_mode="vertex", gcs_bucket="", vertex_location="global", target_paths=None, service_account=None, secrets=None):
    config = {
        "runtime": "cloud-run",
        "project_id": project_id,
        "region": region,
        "job_name": job_name,
        "image": image_tag,
        "parallelism": 16,
        "model": "inherit",
        "auth_mode": auth_mode,
        "vertex_location": vertex_location,
        "gcs_bucket": gcs_bucket if gcs_bucket is not None else "",
    }
    if service_account:
        config["service_account"] = service_account
    if secrets:
        config["secrets"] = secrets
    
    paths = target_paths or [
        Path.home() / ".gemini" / "config" / "plugins" / "agystack" / "agystack-runtime.json"
    ]
    
    for p in paths:
        p = Path(p)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"Wrote configuration to {p}")
        except Exception as e:
            print(f"Notice: Could not write to {p}: {e}")
    return config

def run_provisioning(
    project_id,
    region="us-central1",
    image_tag=None,
    scripts_dir=".",
    bucket_name=None,
    service_account=None,
    job_name="agystack-swarm-worker",
    auth_mode="vertex",
    gh_token=None,
    secret_name=None,
    secrets=None,
):
    if image_tag and (Path(image_tag).is_dir() or ("/" in image_tag and not (":" in image_tag or "docker.pkg.dev" in image_tag or "gcr.io" in image_tag))):
        scripts_dir = image_tag
        image_tag = None
    if not image_tag:
        image_tag = f"{region}-docker.pkg.dev/{project_id}/agystack/worker:latest"
    if not bucket_name:
        bucket_name = f"{project_id}-swarm-results"

    if not scripts_dir or not (Path(scripts_dir) / "Dockerfile").is_file():
        candidate = Path(__file__).resolve().parents[2] / "swarm" / "scripts"
        if (candidate / "Dockerfile").is_file():
            scripts_dir = str(candidate)

    print(f"Starting auto-provisioning for project: {project_id}")
    enable_apis(project_id)
    ensure_gcs_bucket(bucket_name, project_id, region)
    sa_email = configure_iam_permissions(project_id, service_account)
    
    configured_secrets = dict(secrets) if isinstance(secrets, dict) else {}
    if gh_token or secret_name:
        sec_name = secret_name or "agystack-gh-token"
        ensure_secret_manager(project_id, secret_name=sec_name, secret_val=gh_token, service_account=sa_email)
        configured_secrets["GH_TOKEN"] = f"{sec_name}:latest"

    build_and_deploy_worker(project_id, region, image_tag, scripts_dir, job_name=job_name, service_account=sa_email)
    write_runtime_config(
        project_id=project_id,
        region=region,
        job_name=job_name,
        image_tag=image_tag,
        auth_mode=auth_mode,
        gcs_bucket=bucket_name,
        service_account=sa_email,
        secrets=configured_secrets if configured_secrets else None,
    )
    print("Auto-provisioning complete.")
    return {
        "project_id": project_id,
        "region": region,
        "job_name": job_name,
        "image": image_tag,
        "gcs_bucket": bucket_name,
        "service_account": sa_email,
        "secrets": configured_secrets if configured_secrets else None,
    }

def main():
    parser = argparse.ArgumentParser(description="AgyStack Runtime Setup Helper")
    parser.add_argument("--doctor", action="store_true", help="Check dependencies (bun, gh, gt, gcloud) and report status")
    parser.add_argument("--check", action="store_true", help="Check gcloud status")
    parser.add_argument("--list-projects", action="store_true", help="List accessible GCP projects")
    parser.add_argument("--project", type=str, help="Use existing project ID")
    parser.add_argument("--create-project", type=str, help="Create a new project ID")
    parser.add_argument("--region", type=str, default="us-central1", help="GCP Region (default us-central1)")
    parser.add_argument("--auto-provision", action="store_true", help="Enable APIs, build, deploy, and configure")
    parser.add_argument("--scripts-dir", type=str, default=".", help="Directory containing Dockerfile for worker")
    parser.add_argument("--bucket", type=str, help="GCS bucket name for swarm results")
    parser.add_argument("--service-account", type=str, help="Cloud Run compute service account")
    
    args = parser.parse_args()
    
    if args.doctor:
        deps = check_dependencies()
        print(json.dumps(deps, indent=2))
        all_required_ok = all(dep.get("ok", False) for dep in deps.values() if dep.get("required"))
        sys.exit(0 if all_required_ok else 1)

    if args.check:
        status = check_gcloud()
        status["active_project"] = get_active_project()
        print(json.dumps(status, indent=2))
        return
        
    if args.list_projects:
        projects = list_projects()
        print(json.dumps(projects, indent=2))
        return
        
    project_id = args.project
    if args.create_project:
        create_project(args.create_project)
        project_id = args.create_project
    
    if args.auto_provision:
        if not project_id:
            project_id = get_active_project()
            if not project_id:
                print("Error: No project specified and no active project found. Use --project or --create-project.")
                sys.exit(1)
                
        run_provisioning(
            project_id=project_id,
            region=args.region,
            scripts_dir=args.scripts_dir,
            bucket_name=getattr(args, "bucket", None),
            service_account=getattr(args, "service_account", None),
        )

if __name__ == "__main__":
    main()
