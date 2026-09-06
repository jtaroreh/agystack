#!/usr/bin/env python3
"""
End-to-end simulation scenario for Google Antigravity Cloud Run Swarms.
Exercises Vertex AI pre-flight probing, simulated pipeline codebase setup,
manifest generation, cloud_worker milestone lifecycles, StorageMessenger
bidirectional question/reply and steering, candidate guardrail enforcement,
verification testing, and score harvesting.
"""

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cloud_worker import (
    emit_milestone,
    is_candidate_file,
    parse_porcelain_status,
)
from cloud_dispatch import (
    handle_mailbox_reply,
    handle_mailbox_steer,
    parse_milestone_log,
    parse_worker_logs,
)
from storage_messenger import StorageMessenger


def probe_vertex_ai(
    project: str,
    model: str,
    location: str = "global",
    timeout: float = 15.0,
) -> bool:
    token_cmd = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if token_cmd.returncode != 0 or not token_cmd.stdout.strip():
        raise RuntimeError(
            "Failed to obtain gcloud access token for Vertex AI live probe.\n"
            f"gcloud error: {token_cmd.stderr.strip()}"
        )
    access_token = token_cmd.stdout.strip()

    if location == "global":
        probe_url = f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/{model}:generateContent"
    else:
        probe_url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent"

    req_data = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project,
    }
    req = urllib.request.Request(
        probe_url,
        data=req_data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            pass
        print(f"[PASS] Vertex AI credentials and publisher model '{model}' verified in {location} (project: {project}).", flush=True)
        return True
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Vertex AI probe failed with HTTP {exc.code} for project '{project}' in location '{location}':\n{err_body}"
        ) from exc


def setup_simulation_repo(base_dir: Path) -> Tuple[Path, Path]:
    origin_dir = base_dir / "origin.git"
    work_dir = base_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init", "-b", "main"], cwd=work_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Antigravity Simulation"], cwd=work_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "bot@antigravity.google"], cwd=work_dir, check=True, capture_output=True)

    pipeline_dir = work_dir / "src" / "pipeline"
    tests_dir = work_dir / "tests"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (pipeline_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")

    (pipeline_dir / "packet_filter.py").write_text(
        "class PacketFilter:\n"
        "    def __init__(self, allowed_ports=None):\n"
        "        self.allowed_ports = set(allowed_ports or [80, 443, 8080])\n\n"
        "    def filter_packets(self, packets):\n"
        "        accepted = []\n"
        "        for pkt in packets:\n"
        "            port = pkt.get('port')\n"
        "            if port in self.allowed_ports:\n"
        "                accepted.append(pkt)\n"
        "        return accepted\n",
        encoding="utf-8",
    )
    (tests_dir / "test_packet_filter.py").write_text(
        "import unittest\n"
        "from src.pipeline.packet_filter import PacketFilter\n\n"
        "class TestPacketFilter(unittest.TestCase):\n"
        "    def test_filter_allowed_ports(self):\n"
        "        pf = PacketFilter(allowed_ports=[80, 443])\n"
        "        packets = [{'id': 1, 'port': 80}, {'id': 2, 'port': 22}, {'id': 3, 'port': 443}]\n"
        "        result = pf.filter_packets(packets)\n"
        "        self.assertEqual(len(result), 2)\n"
        "        self.assertEqual([p['id'] for p in result], [1, 3])\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )

    (pipeline_dir / "transform.py").write_text(
        "class PacketTransform:\n"
        "    def __init__(self, scale=1.0):\n"
        "        self.scale = scale\n\n"
        "    def transform_payload(self, values):\n"
        "        return [int(v * self.scale) for v in values]\n",
        encoding="utf-8",
    )
    (tests_dir / "test_transform.py").write_text(
        "import unittest\n"
        "from src.pipeline.transform import PacketTransform\n\n"
        "class TestPacketTransform(unittest.TestCase):\n"
        "    def test_transform_payload(self):\n"
        "        pt = PacketTransform(scale=2.0)\n"
        "        values = [1, 2, 3, 4]\n"
        "        self.assertEqual(pt.transform_payload(values), [2, 4, 6, 8])\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )

    (pipeline_dir / "router.py").write_text(
        "class PacketRouter:\n"
        "    def __init__(self, routes=None):\n"
        "        self.routes = routes or {'internal': 'node-1', 'external': 'gateway-1'}\n\n"
        "    def route_packet(self, packet):\n"
        "        dest_type = packet.get('type', 'external')\n"
        "        if dest_type in self.routes:\n"
        "            return self.routes[dest_type]\n"
        "        return 'drop'\n",
        encoding="utf-8",
    )
    (tests_dir / "test_router.py").write_text(
        "import unittest\n"
        "from src.pipeline.router import PacketRouter\n\n"
        "class TestPacketRouter(unittest.TestCase):\n"
        "    def test_route_packet(self):\n"
        "        router = PacketRouter()\n"
        "        self.assertEqual(router.route_packet({'type': 'internal'}), 'node-1')\n"
        "        self.assertEqual(router.route_packet({'type': 'external'}), 'gateway-1')\n"
        "        self.assertEqual(router.route_packet({'type': 'unknown'}), 'drop')\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=work_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial pipeline codebase"], cwd=work_dir, check=True, capture_output=True)

    subprocess.run(["git", "clone", "--bare", str(work_dir), str(origin_dir)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin_dir)], cwd=work_dir, check=True, capture_output=True)

    return origin_dir, work_dir


def build_simulation_manifest(tasks_count: int = 3) -> List[Dict[str, Any]]:
    tasks = [
        {
            "task_index": 0,
            "brief": "Cache-locality optimization for packet_filter.py",
            "candidate_files": ["src/pipeline/packet_filter.py"],
            "exclude_files": [".agystack/", ".git/"],
            "verify_command": "python3 -m unittest discover tests",
            "optimization_type": "cache_locality",
        },
        {
            "task_index": 1,
            "brief": "SIMD vectorized loop unrolling for transform.py",
            "candidate_files": ["src/pipeline/transform.py"],
            "exclude_files": [".agystack/", ".git/"],
            "verify_command": "python3 -m unittest discover tests",
            "optimization_type": "simd_unroll",
        },
        {
            "task_index": 2,
            "brief": "Branch-pruning early exit for router.py",
            "candidate_files": ["src/pipeline/router.py"],
            "exclude_files": [".agystack/", ".git/"],
            "verify_command": "python3 -m unittest discover tests",
            "optimization_type": "branch_pruning",
        },
    ]
    return tasks[:tasks_count]


def check_gcs_accessible(bucket_name: str, session_id: str) -> bool:
    try:
        test_msg = StorageMessenger(
            bucket_name=bucket_name,
            session_id=session_id,
            task_index=0,
            is_worker=True,
        )
        probe_blob = test_msg.bucket.blob(f"swarm-{session_id}/probe.txt")
        probe_blob.upload_from_string("probe_ok")
        return probe_blob.exists()
    except Exception:
        return False


def execute_simulated_task(
    task_item: Dict[str, Any],
    origin_repo_url: str,
    base_dir: Path,
    session_id: str,
    gcs_bucket: str,
    orchestrator_messenger: StorageMessenger,
    use_local_storage: bool = False,
) -> str:
    task_index = task_item["task_index"]
    branch_name = f"worker-{task_index}"
    worker_repo_dir = base_dir / f"worker-repo-{task_index}"

    log_buffer = io.StringIO()

    def log_and_emit(phase: str, detail: str = "") -> None:
        emit_milestone(task_index, phase, detail)
        line = f"[MILESTONE] [TASK {task_index}] [PHASE: {phase}]"
        if detail:
            line += f" {detail}"
        log_buffer.write(line + "\n")

    log_and_emit("BOOTING")

    subprocess.run(["git", "clone", origin_repo_url, str(worker_repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Antigravity Cloud Worker"], cwd=worker_repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "bot@antigravity.google"], cwd=worker_repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-B", branch_name], cwd=worker_repo_dir, check=True, capture_output=True)

    log_and_emit("REPO_READY")
    log_and_emit("RUNNING_AGENT", f"Worker executing brief: {task_item['brief']}")

    worker_messenger = StorageMessenger(
        bucket_name=gcs_bucket,
        session_id=session_id,
        task_index=task_index,
        is_worker=True,
    )

    opt_type = task_item.get("optimization_type")
    if opt_type == "cache_locality":
        target_file = worker_repo_dir / "src" / "pipeline" / "packet_filter.py"
        target_file.write_text(
            "class PacketFilter:\n"
            "    def __init__(self, allowed_ports=None):\n"
            "        self._allowed_ports_cache = frozenset(allowed_ports or [80, 443, 8080])\n\n"
            "    def filter_packets(self, packets):\n"
            "        cache = self._allowed_ports_cache\n"
            "        return [pkt for pkt in packets if pkt.get('port') in cache]\n",
            encoding="utf-8",
        )
    elif opt_type == "simd_unroll":
        steer_text = "Align vectors to 64-byte boundaries and unroll loop by factor 4"
        handle_mailbox_steer(
            task_index=task_index,
            text=steer_text,
            session_id=session_id,
            bucket_name=gcs_bucket,
            messenger=orchestrator_messenger,
        )
        steer_envelopes = worker_messenger.check_steer_instructions()
        for s_env in steer_envelopes:
            instruction = s_env.payload.get("instruction") or s_env.payload.get("text") or ""
            log_and_emit("STEER_RECEIVED", instruction[:80])

        target_file = worker_repo_dir / "src" / "pipeline" / "transform.py"
        target_file.write_text(
            "class PacketTransform:\n"
            "    def __init__(self, scale=1.0):\n"
            "        self.scale = scale\n\n"
            "    def transform_payload(self, values):\n"
            "        scale = self.scale\n"
            "        length = len(values)\n"
            "        result = [0] * length\n"
            "        rem = length % 4\n"
            "        limit = length - rem\n"
            "        for i in range(0, limit, 4):\n"
            "            result[i] = int(values[i] * scale)\n"
            "            result[i + 1] = int(values[i + 1] * scale)\n"
            "            result[i + 2] = int(values[i + 2] * scale)\n"
            "            result[i + 3] = int(values[i + 3] * scale)\n"
            "        for i in range(limit, length):\n"
            "            result[i] = int(values[i] * scale)\n"
            "        return result\n",
            encoding="utf-8",
        )
    elif opt_type == "branch_pruning":
        q_text = "Should unroutable packets drop immediately or fallback?"
        log_and_emit("WAITING_FOR_ORCHESTRATOR", q_text[:80])
        q_env = worker_messenger.send_question(question=q_text, context="router early exit")
        reply_text = "Drop unknown packets immediately with early exit return."
        handle_mailbox_reply(
            task_index=task_index,
            seq=q_env.seq,
            text=reply_text,
            session_id=session_id,
            bucket_name=gcs_bucket,
            messenger=orchestrator_messenger,
        )
        delivered_reply = worker_messenger.wait_for_reply(seq=q_env.seq, timeout_seconds=10.0)
        assert delivered_reply == reply_text, "Failed to receive matching reply from orchestrator"
        log_and_emit("ORCHESTRATOR_REPLY_RECEIVED", f"Seq {q_env.seq}")

        target_file = worker_repo_dir / "src" / "pipeline" / "router.py"
        target_file.write_text(
            "class PacketRouter:\n"
            "    def __init__(self, routes=None):\n"
            "        self.routes = routes or {'internal': 'node-1', 'external': 'gateway-1'}\n\n"
            "    def route_packet(self, packet):\n"
            "        if not packet:\n"
            "            return 'drop'\n"
            "        dest_type = packet.get('type')\n"
            "        if not dest_type:\n"
            "            return 'drop'\n"
            "        return self.routes.get(dest_type, 'drop')\n",
            encoding="utf-8",
        )

    for cand in task_item["candidate_files"]:
        assert is_candidate_file(cand, explicit_candidates=task_item["candidate_files"], explicit_excludes=task_item["exclude_files"])
    assert not is_candidate_file(".agystack/runtime.json", explicit_candidates=task_item["candidate_files"], explicit_excludes=task_item["exclude_files"])
    assert not is_candidate_file(".git/config", explicit_candidates=task_item["candidate_files"], explicit_excludes=task_item["exclude_files"])

    log_and_emit("VALIDATING_CANDIDATE")
    run_env = dict(os.environ, PYTHONPATH=str(worker_repo_dir))
    verify_proc = subprocess.run(
        task_item["verify_command"],
        shell=True,
        cwd=worker_repo_dir,
        capture_output=True,
        text=True,
        env=run_env,
    )
    if verify_proc.returncode != 0:
        raise RuntimeError(f"Task {task_index} verification failed:\n{verify_proc.stderr}")

    score_val = 98.0 + (task_index * 0.5)
    score_data = {
        "task_index": task_index,
        "score": score_val,
        "fill_ratio": 1.0,
        "status": "PASS",
        "metrics": {
            "score": score_val,
            "fill_ratio": 1.0,
        },
    }
    score_file = worker_repo_dir / "score.json"
    score_file.write_text(json.dumps(score_data, indent=2), encoding="utf-8")

    status_res = subprocess.run(["git", "status", "--porcelain"], cwd=worker_repo_dir, capture_output=True, text=True, check=True)
    modified_files = parse_porcelain_status(status_res.stdout)
    for m_file in modified_files:
        if is_candidate_file(m_file, explicit_candidates=task_item["candidate_files"], explicit_excludes=task_item["exclude_files"]):
            subprocess.run(["git", "add", "--", m_file], cwd=worker_repo_dir, check=True, capture_output=True)

    subprocess.run(["git", "commit", "-m", f"worker-{task_index}: {task_item['brief']}"], cwd=worker_repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", branch_name, "--force"], cwd=worker_repo_dir, check=True, capture_output=True)

    commit_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worker_repo_dir, capture_output=True, text=True, check=True).stdout.strip()[:7]
    diff_stat = subprocess.run(["git", "diff", "--stat", "HEAD~1", "HEAD"], cwd=worker_repo_dir, capture_output=True, text=True, check=True).stdout.strip()

    log_and_emit("COMPLETE", "PASS")

    report_block = (
        "\n================================================================================\n"
        "[STATUS: PASS]\n"
        "Evidence:\n"
        f"- Task Index: {task_index}\n"
        f"- Branch: {branch_name}\n"
        f"- Commit SHA: {commit_sha}\n"
        "- Changes Pushed: True\n"
        f"- Score: {score_val}\n"
        "- Fill Ratio: 1.0\n"
        f"- Slice JSON: {json.dumps(score_data)}\n"
        f"- Diff Stat:\n{diff_stat}\n"
        "Summary:\n"
        f"{task_item['brief']} completed and verified cleanly.\n"
        "================================================================================\n"
    )
    print(report_block, flush=True)
    log_buffer.write(report_block)

    return log_buffer.getvalue()


def run_simulation(
    model: str = "gemini-2.5-flash",
    project: str = "example-agystack-project",
    gcs_bucket: str = "example-swarm-results",
    tasks: int = 3,
    skip_live_probe: bool = True,
    temp_base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    print("=" * 80)
    print("STARTING CLOUD RUN SWARM SIMULATION SCENARIO")
    print(f"Model: {model} | Project: {project} | GCS Bucket: {gcs_bucket} | Tasks: {tasks}")
    print("=" * 80)

    if not skip_live_probe:
        print("[PRE-FLIGHT] Initiating live Vertex AI publisher model availability probe...")
        try:
            probe_vertex_ai(project=project, model=model, location="global")
        except Exception as exc:
            print(f"Warning: Live Vertex AI probe failed ({exc}).", file=sys.stderr)
            raise
    else:
        print("[PRE-FLIGHT] Live Vertex AI probe skipped (--skip-live-probe).", flush=True)

    cleanup_dir = False
    if temp_base_dir is None:
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="swarm-sim-")
        base_dir = Path(temp_dir_obj.name)
        cleanup_dir = True
    else:
        base_dir = temp_base_dir

    try:
        origin_dir, _ = setup_simulation_repo(base_dir)
        manifest = build_simulation_manifest(tasks_count=tasks)

        session_id = f"sim-{int(time.time())}"
        use_local_storage = False
        prev_local_storage = os.environ.get("STORAGE_MESSENGER_LOCAL_DIR")
        if not check_gcs_accessible(gcs_bucket, session_id):
            use_local_storage = True
            local_storage_dir = base_dir / "simulated_gcs"
            local_storage_dir.mkdir(parents=True, exist_ok=True)
            os.environ["STORAGE_MESSENGER_LOCAL_DIR"] = str(local_storage_dir)
            print(f"Notice: GCS bucket '{gcs_bucket}' not directly accessible; using StorageMessenger local adapter.", flush=True)

        orchestrator_messenger = StorageMessenger(
            bucket_name=gcs_bucket,
            session_id=session_id,
            is_worker=False,
        )

        all_worker_logs = []
        for task_item in manifest:
            task_log = execute_simulated_task(
                task_item=task_item,
                origin_repo_url=str(origin_dir),
                base_dir=base_dir,
                session_id=session_id,
                gcs_bucket=gcs_bucket,
                orchestrator_messenger=orchestrator_messenger,
                use_local_storage=use_local_storage,
            )
            all_worker_logs.append(task_log)

        combined_logs = "\n".join(all_worker_logs)
        parsed_results = parse_worker_logs(combined_logs)

        harvested_slices = []
        for item in parsed_results:
            for ev_line in item.get("evidence", "").splitlines():
                if ev_line.strip().startswith("- Slice JSON:"):
                    raw_json = ev_line.strip().split("- Slice JSON:", 1)[1].strip()
                    try:
                        harvested_slices.append(json.loads(raw_json))
                    except Exception:
                        pass

        out_slices_file = Path(".slices/harvested_scores.json")
        out_slices_file.parent.mkdir(parents=True, exist_ok=True)
        out_slices_file.write_text(json.dumps(harvested_slices, indent=2), encoding="utf-8")
        print(f"\nHarvested {len(harvested_slices)} slice scores to {out_slices_file}")

        milestones = []
        for line in combined_logs.splitlines():
            pm = parse_milestone_log(line)
            if pm:
                milestones.append(pm)

        print("\n" + "=" * 80)
        print(f"WORKER MILESTONE SUMMARY ({len(milestones)} events captured)")
        print("=" * 80)
        print(f"{'Task':<6} | {'Phase':<28} | {'Detail'}")
        print("-" * 80)
        for m in milestones:
            print(f"{m['task_index']:<6} | {m['phase']:<28} | {m['detail']}")

        print("\n" + "=" * 80)
        print("SWARM SIMULATION REPORT: Cloud Run Agent Swarm")
        print("=" * 80)
        print(f"{'Task':<8} | {'Status':<10} | {'Summary'}")
        print("-" * 80)
        pass_count = 0
        for i, item in enumerate(parsed_results):
            st = item.get("status", "UNKNOWN")
            sm = item.get("summary", "").replace("\n", " ")[:60]
            if st == "PASS":
                pass_count += 1
            print(f"{i:<8} | {st:<10} | {sm}")
        print("=" * 80)
        print(f"Total: {len(parsed_results)} | PASS: {pass_count} | ISSUES: 0 | BLOCKED: 0")
        print("=" * 80)

        return {
            "status": "PASS" if pass_count == len(manifest) else "ISSUES",
            "tasks": len(manifest),
            "harvested_scores": harvested_slices,
            "parsed_results": parsed_results,
            "milestones": milestones,
        }
    finally:
        if 'prev_local_storage' in locals() and prev_local_storage is not None:
            os.environ["STORAGE_MESSENGER_LOCAL_DIR"] = prev_local_storage
        elif "STORAGE_MESSENGER_LOCAL_DIR" in os.environ:
            del os.environ["STORAGE_MESSENGER_LOCAL_DIR"]
        if cleanup_dir:
            temp_dir_obj.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate Cloud Run agent swarm execution.")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash", help="Model override (default: gemini-2.5-flash).")
    parser.add_argument("--project", type=str, default="example-agystack-project", help="GCP project ID (default: example-agystack-project).")
    parser.add_argument("--gcs-bucket", type=str, default="example-swarm-results", help="GCS bucket name (default: example-swarm-results).")
    parser.add_argument("--tasks", type=int, default=3, help="Number of tasks to simulate (default: 3).")
    parser.add_argument("--skip-live-probe", action="store_true", default=True, help="Skip live Vertex AI network probe (default: True).")
    parser.add_argument("--live-probe", dest="skip_live_probe", action="store_false", help="Run live Vertex AI network probe.")

    args = parser.parse_args()

    result = run_simulation(
        model=args.model,
        project=args.project,
        gcs_bucket=args.gcs_bucket,
        tasks=args.tasks,
        skip_live_probe=args.skip_live_probe,
    )

    if result["status"] == "PASS":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
