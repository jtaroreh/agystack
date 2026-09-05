#!/usr/bin/env python3
import json
import math
import subprocess
import sys
from typing import Any, Dict, List, Optional


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
            if mb <= ma and sb <= sa and (mb < ma or sb < sa):
                dominated = True
                break
        if not dominated:
            frontier.append(trial_a)

    frontier.sort(
        key=lambda t: (
            _extract_metric_value(t, metric_key),
            _extract_metric_value(t, secondary_key),
        )
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
