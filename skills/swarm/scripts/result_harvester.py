#!/usr/bin/env python3
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def _extract_metric_value(trial: Dict[str, Any], key: str) -> Optional[float]:
    if key in trial and trial[key] is not None:
        try:
            return float(trial[key])
        except (ValueError, TypeError):
            pass
    metrics = trial.get("metrics")
    if isinstance(metrics, dict) and key in metrics and metrics[key] is not None:
        try:
            return float(metrics[key])
        except (ValueError, TypeError):
            pass
    return None


def extract_pareto_frontier(
    trials: List[Dict[str, Any]],
    metric_key: str = "score",
    secondary_key: str = "fill_ratio",
    maximize: bool = True,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    points: List[tuple] = []

    for trial in trials:
        if not isinstance(trial, dict):
            continue
        m = _extract_metric_value(trial, metric_key)
        s = _extract_metric_value(trial, secondary_key)
        if m is not None and s is not None and not math.isnan(m) and not math.isnan(s):
            candidates.append(trial)
            points.append((m, s))

    frontier: List[Dict[str, Any]] = []
    for i, trial_a in enumerate(candidates):
        ma, sa = points[i]
        dominated = False
        for j, trial_b in enumerate(candidates):
            if i == j:
                continue
            mb, sb = points[j]
            if maximize:
                if mb >= ma and sb >= sa and (mb > ma or sb > sa):
                    dominated = True
                    break
            else:
                if mb <= ma and sb <= sa and (mb < ma or sb < sa):
                    dominated = True
                    break
        if not dominated:
            frontier.append(trial_a)

    frontier.sort(
        key=lambda t: (
            _extract_metric_value(t, metric_key),
            _extract_metric_value(t, secondary_key),
        ),
        reverse=maximize,
    )
    return frontier


def harvest_gcs_results(
    bucket_name: str,
    prefix: str,
    target_filename: str = "score.json",
) -> List[Dict[str, Any]]:
    clean_prefix = prefix.strip("/")
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=clean_prefix)
        results: List[Dict[str, Any]] = []
        for blob in blobs:
            if blob.name.endswith(target_filename):
                payload = json.loads(blob.download_as_text(encoding="utf-8"))
                results.append(payload)
        return results
    except ImportError:
        pass
    except Exception as exc:
        print(f"Notice: GCS client listing failed ({exc}), falling back to gcloud CLI", file=sys.stderr)

    ls_target = f"gs://{bucket_name}/{clean_prefix}/**/{target_filename}" if clean_prefix else f"gs://{bucket_name}/**/{target_filename}"
    cmd = ["gcloud", "storage", "cat", ls_target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        results = []
        decoder = json.JSONDecoder()
        content = proc.stdout.strip()
        idx = 0
        while idx < len(content):
            while idx < len(content) and content[idx].isspace():
                idx += 1
            if idx >= len(content):
                break
            obj, end_idx = decoder.raw_decode(content[idx:])
            results.append(obj)
            idx += end_idx
        return results
    except Exception:
        return []


def harvest_candidate_patches(
    bucket_name: str,
    prefix: str,
    dest_dir: Union[Path, str],
    baseline_score: Optional[float] = None,
    sort_by_delta: bool = True,
) -> List[Dict[str, Any]]:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    clean_prefix = prefix.strip("/")
    tasks_found: Dict[int, Dict[str, Any]] = {}

    local_dir = os.environ.get("STORAGE_MESSENGER_LOCAL_DIR")
    if local_dir:
        src_base = Path(local_dir) / bucket_name / clean_prefix
        if src_base.is_dir():
            for task_folder in sorted(src_base.iterdir()):
                if not task_folder.is_dir():
                    continue
                m = re.search(r"task-(\d+)", task_folder.name)
                if not m:
                    continue
                task_idx = int(m.group(1))
                target_task_dir = dest / f"task-{task_idx}"
                target_task_dir.mkdir(parents=True, exist_ok=True)
                score_src = task_folder / "score.json"
                patch_src = task_folder / "patch.diff"
                status_src = task_folder / "status.json"
                sf = None
                pf = None
                stf = None
                if score_src.is_file():
                    target_score = target_task_dir / "score.json"
                    shutil.copy2(score_src, target_score)
                    sf = target_score
                if patch_src.is_file():
                    target_patch = target_task_dir / "patch.diff"
                    shutil.copy2(patch_src, target_patch)
                    pf = target_patch
                if status_src.is_file():
                    target_status = target_task_dir / "status.json"
                    shutil.copy2(status_src, target_status)
                    stf = target_status
                tasks_found[task_idx] = {"score_file": sf, "patch_file": pf, "status_file": stf}

    if not tasks_found:
        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blobs = bucket.list_blobs(prefix=clean_prefix)
            for blob in blobs:
                m = re.search(r"task-(\d+)/([^/]+)$", blob.name)
                if not m:
                    continue
                task_idx = int(m.group(1))
                filename = m.group(2)
                if filename not in ("score.json", "patch.diff", "status.json"):
                    continue
                if task_idx not in tasks_found:
                    tasks_found[task_idx] = {}
                target_task_dir = dest / f"task-{task_idx}"
                target_task_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_task_dir / filename
                blob.download_to_filename(str(target_file))
                if filename == "score.json":
                    tasks_found[task_idx]["score_file"] = target_file
                elif filename == "patch.diff":
                    tasks_found[task_idx]["patch_file"] = target_file
                elif filename == "status.json":
                    tasks_found[task_idx]["status_file"] = target_file
        except Exception:
            pass

    if not tasks_found:
        src_uri = f"gs://{bucket_name}/{clean_prefix}/*"
        try:
            subprocess.run(
                ["gcloud", "storage", "cp", "-r", src_uri, str(dest)],
                capture_output=True,
                check=False,
            )
            for item in dest.glob("task-*"):
                if item.is_dir():
                    m = re.search(r"task-(\d+)", item.name)
                    if m:
                        task_idx = int(m.group(1))
                        sf = item / "score.json"
                        pf = item / "patch.diff"
                        stf = item / "status.json"
                        tasks_found[task_idx] = {
                            "score_file": sf if sf.is_file() else None,
                            "patch_file": pf if pf.is_file() else None,
                            "status_file": stf if stf.is_file() else None,
                        }
        except Exception:
            pass

    results = []
    for task_idx in sorted(tasks_found.keys()):
        info = tasks_found[task_idx]
        score_file = info.get("score_file")
        patch_file = info.get("patch_file")
        status_file = info.get("status_file")
        score = None
        status = "UNKNOWN"
        summary = ""
        candidate_files = []

        if score_file and Path(score_file).is_file():
            try:
                data = json.loads(Path(score_file).read_text(encoding="utf-8"))
                score = data.get("score")
                status = data.get("status", "PASS" if score is not None else "UNKNOWN")
            except Exception:
                pass

        if status_file and Path(status_file).is_file():
            try:
                st_data = json.loads(Path(status_file).read_text(encoding="utf-8"))
                if "status" in st_data and st_data["status"]:
                    status = st_data["status"]
                if "score" in st_data and st_data["score"] is not None:
                    score = st_data["score"]
                summary = st_data.get("summary", "")
                candidate_files = st_data.get("candidate_files", [])
            except Exception:
                pass

        score_delta = None
        if isinstance(score, (int, float)) and isinstance(baseline_score, (int, float)):
            score_delta = round(float(score) - float(baseline_score), 4)

        results.append({
            "task_index": task_idx,
            "score": score,
            "score_delta": score_delta,
            "status": status,
            "summary": summary,
            "candidate_files": candidate_files,
            "patch_file": str(patch_file) if patch_file else None,
            "score_file": str(score_file) if score_file else None,
            "status_file": str(status_file) if status_file else None,
        })

    if sort_by_delta:
        def sort_key(r):
            is_pass = 1 if r.get("status") == "PASS" else 0
            metric = r.get("score_delta") if r.get("score_delta") is not None else r.get("score")
            has_metric = 1 if (metric is not None and not math.isnan(metric)) else 0
            metric_val = metric if has_metric else float("-inf")
            task_idx = r.get("task_index") if isinstance(r.get("task_index"), int) else 999999
            return (-is_pass, -has_metric, -metric_val, task_idx)

        results.sort(key=sort_key)

    return results
