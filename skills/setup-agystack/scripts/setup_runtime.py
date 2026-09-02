import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

def run_cmd(cmd, check=True, capture_output=True):
    try:
        res = subprocess.run(cmd, check=check, capture_output=capture_output, text=True)
        return res
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
        f"--project={project_id}"
    ])

def build_and_deploy_worker(project_id, region, image_tag, scripts_dir):
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
    
    print("Submitting Cloud Build...")
    run_cmd([
        "gcloud", "builds", "submit",
        f"--tag={image_tag}",
        scripts_dir,
        f"--project={project_id}"
    ], capture_output=False)
    
    print("Creating/Updating Cloud Run Job...")
    res = run_cmd([
        "gcloud", "run", "jobs", "describe", "agystack-swarm-worker",
        f"--region={region}",
        f"--project={project_id}"
    ], check=False)
    
    action = "update" if res.returncode == 0 else "create"
    run_cmd([
        "gcloud", "run", "jobs", action, "agystack-swarm-worker",
        f"--image={image_tag}",
        f"--region={region}",
        f"--project={project_id}",
        "--tasks=1",
        "--task-timeout=30m"
    ])

def write_runtime_config(project_id, region, job_name, image_tag):
    config = {
        "project_id": project_id,
        "region": region,
        "job_name": job_name,
        "image": image_tag
    }
    
    paths = [
        Path.home() / ".gemini" / "config" / "plugins" / "agystack" / "agystack-runtime.json",
        Path.cwd() / ".agents" / "plugins" / "agystack" / "agystack-runtime.json"
    ]
    
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Wrote configuration to {p}")

def main():
    parser = argparse.ArgumentParser(description="AgyStack Runtime Setup Helper")
    parser.add_argument("--check", action="store_true", help="Check gcloud status")
    parser.add_argument("--list-projects", action="store_true", help="List accessible GCP projects")
    parser.add_argument("--project", type=str, help="Use existing project ID")
    parser.add_argument("--create-project", type=str, help="Create a new project ID")
    parser.add_argument("--region", type=str, default="us-central1", help="GCP Region (default us-central1)")
    parser.add_argument("--auto-provision", action="store_true", help="Enable APIs, build, deploy, and configure")
    parser.add_argument("--scripts-dir", type=str, default=".", help="Directory containing Dockerfile for worker")
    
    args = parser.parse_args()
    
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
                
        print(f"Starting auto-provisioning for project: {project_id}")
        enable_apis(project_id)
        image_tag = f"{args.region}-docker.pkg.dev/{project_id}/agystack/worker:latest"
        build_and_deploy_worker(project_id, args.region, image_tag, args.scripts_dir)
        write_runtime_config(project_id, args.region, "agystack-swarm-worker", image_tag)
        print("Auto-provisioning complete.")

if __name__ == "__main__":
    main()
