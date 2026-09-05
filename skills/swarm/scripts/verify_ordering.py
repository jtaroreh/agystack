#!/usr/bin/env python3
"""
Unified verification harness for matrices.fast.
Provides progressive tiered verification for autonomous coding agents and swarms:
  Tier 0: Purity scan, anti-pattern linting, and Cargo check (<1s)
  Tier 1: Unit tests (bijection, determinism, work bounds) (<2s)
  Tier 2: Timing headroom probe (<1.0s worst-case limit against 2.0s watchdog)
  Tier 3: Quick smoke evaluation (SSI_MAX_MATRIX_N) (~15s)
  Tier 4: Full benchmark scoring (300 matrices) (~2-3min)
  Pre-submit: Validates submission note, score improvement (>=1 bip), and parameters.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
WARN = "\033[93m[WARN]\033[0m"
INFO = "\033[94m[INFO]\033[0m"

MIN_NOTE_BYTES = 5 * 1024  # 5 KiB
MAX_NOTE_BYTES = 100 * 1024  # 100 KiB
MIN_SCORE_IMPROVEMENT_BIPS = 1  # 0.0001 (0.01%)


def find_repo_root() -> Path:
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if (p / "benchmark.json").exists() and (p / "src" / "ordering").is_dir():
            return p
        if (p / "matrices-fast" / "benchmark.json").exists():
            return p / "matrices-fast"
    return cur


def run_command(cmd: list[str], cwd: Path, env: dict | None = None) -> tuple[int, str, str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=full_env)
    return p.returncode, p.stdout, p.stderr


def lint_ordering_source(repo_root: Path) -> tuple[bool, list[str], list[str]]:
    """Static anti-pattern and determinism linter for src/ordering/."""
    ordering_dir = repo_root / "src" / "ordering"
    errors = []
    warnings = []

    mod_rs = ordering_dir / "mod.rs"
    if not mod_rs.exists():
        errors.append("src/ordering/mod.rs does not exist")
        return False, errors, warnings

    mod_text = mod_rs.read_text()
    if not re.search(r"pub\s+fn\s+order\s*\(\s*pattern\s*:\s*&Pattern\s*\)\s*->\s*Vec<usize>", mod_text):
        errors.append("Missing required export: pub fn order(pattern: &Pattern) -> Vec<usize> in src/ordering/mod.rs")

    for rs_file in ordering_dir.rglob("*.rs"):
        if rs_file.name == "probe.rs":
            continue
        rel_path = rs_file.relative_to(repo_root)
        content = rs_file.read_text()

        # Check for forbidden unsafe code
        if re.search(r"\bunsafe\s*\{", content):
            errors.append(f"Forbidden unsafe block found in {rel_path}")

        # Check for non-deterministic time/entropy calls
        if "SystemTime::now" in content or "thread_rng" in content:
            errors.append(f"Non-deterministic entropy or clock call found in {rel_path}. order() must be pure and deterministic!")

        # Check for network or filesystem access
        if "std::fs" in content or "std::net" in content:
            errors.append(f"Forbidden host I/O (std::fs / std::net) found in {rel_path}. Grader runs in a network-denied sandbox!")

        # Check for unseeded random patterns
        if "rand::random" in content:
            errors.append(f"Unseeded rand::random() call in {rel_path}")

        # Warning for iterating over standard HashMap/HashSet without explicit sorting
        if re.search(r"for\s+.*\s+in\s+&?(hash_map|hash_set|map|set)\b", content, re.IGNORECASE):
            warnings.append(f"Potential iteration over HashMap/HashSet in {rel_path}. Ensure keys are sorted to prevent determinism failures.")

    return len(errors) == 0, errors, warnings


def tier0_purity_check(repo_root: Path) -> tuple[bool, str]:
    print(f"\n{INFO} === Tier 0: Purity & Dependency Scan ===")
    
    # 1. Static ordering source lint
    ok, errors, warnings = lint_ordering_source(repo_root)
    for w in warnings:
        print(f"{WARN} [lint warning] {w}")
    if not ok:
        for err in errors:
            print(f"{FAIL} [lint error] {err}")
        return False, f"Static ordering linter failed with {len(errors)} errors"
    print(f"{PASS} Static ordering linter passed (valid entrypoint, no unsafe, no I/O, deterministic)")

    # 2. Doctor diagnostic
    doctor_script = repo_root / ".agents" / "skills" / "verify-matrices-fast" / "scripts" / "doctor.py"
    if doctor_script.exists():
        code, stdout, stderr = run_command([sys.executable, str(doctor_script)], repo_root)
        if code != 0:
            return False, f"Doctor check failed:\n{stdout}\n{stderr}"

    # 3. Cargo check candidate worker
    code, stdout, stderr = run_command(["cargo", "check", "-p", "ssi-candidate-worker"], repo_root)
    if code != 0:
        return False, f"Cargo check failed:\n{stderr or stdout}"
    print(f"{PASS} Tier 0 passed: Pure Rust source, valid deps, compiles cleanly.")
    return True, "Tier 0 passed"


def tier1_unit_tests(repo_root: Path) -> tuple[bool, str]:
    print(f"\n{INFO} === Tier 1: Unit & Determinism Verification ===")
    t0 = time.time()
    code, stdout, stderr = run_command(
        ["cargo", "test", "-p", "ssi-candidate-worker", "--release"],
        repo_root
    )
    elapsed = time.time() - t0
    if code != 0:
        return False, f"Unit tests failed (took {elapsed:.2f}s):\n{stdout}\n{stderr}"

    match = re.search(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed", stdout)
    summary = match.group(0) if match else f"exit {code}"
    print(f"{PASS} Tier 1 passed in {elapsed:.2f}s: {summary}")
    print(f"       (Verified: bijection of 0..n, strict determinism, empty/singleton edge cases)")
    return True, summary


def tier2_timing_check(
    repo_root: Path,
    max_allowed_worst_sec: float = 1.0,
    slice_file: Path | None = None,
) -> tuple[bool, str]:
    print(f"\n{INFO} === Tier 2: Timing Headroom Probe ===")
    print(f"Targeting worst-case local order() runtime <= {max_allowed_worst_sec:.2f}s (against strict 2.0s cap)")
    t0 = time.time()
    env = {}
    if slice_file:
        env["SSI_CORPUS_FILE"] = str(slice_file.resolve())
    code, stdout, stderr = run_command(
        ["cargo", "test", "-p", "ssi-candidate-worker", "--release", "--", "--ignored", "--nocapture", "--test-threads=1", "probe_timing_and_score"],
        repo_root,
        env=env,
    )
    elapsed = time.time() - t0
    if code != 0:
        return False, f"Timing probe failed (took {elapsed:.2f}s):\n{stdout}\n{stderr}"

    lines = stdout.splitlines()
    slowest = []
    in_tsv = False
    for line in lines:
        if "--- every order() call, slowest first (TSV) ---" in line:
            in_tsv = True
            continue
        if in_tsv and line.startswith("matrices under") or in_tsv and "--- per-bucket ---" in line:
            in_tsv = False
            continue
        if in_tsv and line and not line.startswith("secs"):
            parts = line.split("\t")
            if len(parts) >= 5:
                try:
                    sec = float(parts[0])
                    mat = parts[1]
                    n_dim = int(parts[2])
                    nnz = int(parts[3])
                    ratio = float(parts[4])
                    slowest.append((sec, mat, n_dim, nnz, ratio))
                except ValueError:
                    pass

    if not slowest:
        return False, "Could not parse timing probe TSV output"

    worst_sec, worst_mat, worst_n, worst_nnz, worst_ratio = slowest[0]
    print(f"Top 3 slowest matrices on this machine:")
    for s, m, n, nnz, r in slowest[:3]:
        print(f"  - {m:25} {s:6.3f}s (n={n}, nnz={nnz}, ratio={r:.4f})")

    if worst_sec > 2.0:
        msg = f"Watchdog SIGKILL violation! Worst matrix {worst_mat} took {worst_sec:.3f}s (> 2.0s hard cap)"
        print(f"{FAIL} {msg}")
        return False, msg
    elif worst_sec > max_allowed_worst_sec:
        msg = f"Headroom warning: Worst matrix {worst_mat} took {worst_sec:.3f}s (> recommended {max_allowed_worst_sec:.2f}s). High risk of hidden timeout!"
        print(f"{WARN} {msg}")
        return True, msg
    else:
        msg = f"Safe headroom: Worst matrix {worst_mat} took {worst_sec:.3f}s (<= {max_allowed_worst_sec:.2f}s limit)"
        print(f"{PASS} {msg}")
        return True, msg


def tier3_smoke_eval(repo_root: Path, max_n: int = 1000) -> tuple[bool, dict]:
    print(f"\n{INFO} === Tier 3: Quick Smoke Evaluation (SSI_MAX_MATRIX_N={max_n}) ===")
    t0 = time.time()

    build_code, b_out, b_err = run_command(["bash", "scripts/local-candidate-build.sh"], repo_root)
    if build_code != 0:
        return False, {"error": f"Sandboxed candidate build failed:\n{b_out}\n{b_err}"}

    code, stdout, stderr = run_command(
        ["cargo", "run", "--release", "--offline", "--locked", "--", "--note", f"smoke n<={max_n}"],
        repo_root,
        env={"SSI_MAX_MATRIX_N": str(max_n)}
    )
    elapsed = time.time() - t0
    if code != 0:
        return False, {"error": f"Smoke run failed in {elapsed:.2f}s:\n{stdout}\n{stderr}"}

    score_json_path = repo_root / "score.json"
    if not score_json_path.exists():
        return False, {"error": "score.json not produced"}

    data = json.loads(score_json_path.read_text())
    score = data.get("score")
    metrics = data.get("metrics", {})
    fill_ratio = metrics.get("geomean_fill_ratio")
    print(f"{PASS} Tier 3 smoke evaluation completed in {elapsed:.2f}s")
    print(f"       Sub-corpus Score: {score:.6f} | Fill: {fill_ratio:.6f}")
    return True, data


def tier4_full_eval(repo_root: Path, baseline_score: float | None = None) -> tuple[bool, dict]:
    print(f"\n{INFO} === Tier 4: Full Benchmark Scoring (300 matrices) ===")
    print("Executing sandboxed build and 300-matrix scoring with 2.0s per-matrix watchdog...")
    t0 = time.time()

    code, stdout, stderr = run_command(["yukon", "run"], repo_root)
    elapsed = time.time() - t0
    if code != 0:
        return False, {"error": f"yukon run failed in {elapsed:.2f}s:\n{stdout}\n{stderr}"}

    score_json_path = repo_root / "score.json"
    if not score_json_path.exists():
        return False, {"error": "score.json was not generated"}

    data = json.loads(score_json_path.read_text())
    score = data.get("score")
    metrics = data.get("metrics", {})
    fill_ratio = metrics.get("geomean_fill_ratio")
    buckets = metrics.get("buckets", {})

    print(f"\n{PASS} Full evaluation completed in {elapsed:.2f}s")
    print(f"       Score (weighted geomean flop ratio): {score:.6f}")
    print(f"       Tiebreak (fill ratio):               {fill_ratio:.6f}")
    print("       Per-Bucket Breakdown:")
    for b_name in ["lt_1k", "1k_10k", "gt_10k"]:
        if b_name in buckets:
            b_info = buckets[b_name]
            print(f"         - {b_name:8}: count={b_info.get('count', 0):3}, flop_geomean={b_info.get('geomean_flop_ratio', 0.0):.6f}, fill_geomean={b_info.get('geomean_fill_ratio', 0.0):.6f}")

    if baseline_score is not None:
        delta = score - baseline_score
        bips = (baseline_score - score) / baseline_score * 10000
        print(f"\nDelta vs Baseline ({baseline_score:.6f}): {delta:+.6f} ({bips:+.2f} bips)")
        if delta < 0:
            print(f"{PASS} Improvement detected! (Lower is better)")
        else:
            print(f"{WARN} No improvement vs baseline.")

    return True, data


def check_submission_readiness(
    repo_root: Path,
    note_file_path: Path,
    model: str,
    harness: str,
    frontier_score: float
) -> tuple[bool, str]:
    print(f"\n{INFO} === Pre-Submission Verification Gate ===")

    if not note_file_path.exists():
        return False, f"Note file does not exist: {note_file_path}"

    note_size = note_file_path.stat().st_size
    print(f"Note file: {note_file_path} ({note_size} bytes)")
    if note_size < MIN_NOTE_BYTES:
        return False, f"Note file is too short ({note_size} bytes < 5 KiB minimum requirement)"
    if note_size > MAX_NOTE_BYTES:
        return False, f"Note file is too large ({note_size} bytes > 100 KiB maximum limit)"

    note_content = note_file_path.read_text()
    secret_patterns = [r"ykn_[a-f0-9]{32,}", r"ghp_[a-zA-Z0-9]{36}", r"sk-[a-zA-Z0-9]{32,}"]
    for pat in secret_patterns:
        if re.search(pat, note_content):
            return False, "Submission note contains sensitive token or API key pattern!"

    score_json = repo_root / "score.json"
    if not score_json.exists():
        return False, "score.json not found. Run full benchmark evaluation first."
    data = json.loads(score_json.read_text())
    cand_score = data.get("score")
    if cand_score is None:
        return False, "No score found in score.json"

    delta = cand_score - frontier_score
    bips = (frontier_score - cand_score) / frontier_score * 10000
    print(f"Candidate Score: {cand_score:.6f} vs Frontier: {frontier_score:.6f} (Delta: {delta:+.6f}, {bips:.2f} bips)")
    if bips < MIN_SCORE_IMPROVEMENT_BIPS:
        return False, f"Score improvement ({bips:.2f} bips) is below the minimum promotion threshold of {MIN_SCORE_IMPROVEMENT_BIPS} bip (-0.0001)."

    if not model or len(model.split()) < 2:
        return False, f"Invalid model '{model}'. Must specify exact, fully qualified version (e.g. 'Gemini 3.8 Flash', 'Claude Opus 4.8')."
    if not harness:
        return False, "Harness name must be specified (e.g. 'Antigravity', 'Codex', 'Claude Code')."

    code, stdout, stderr = run_command(["git", "status", "--porcelain"], repo_root)
    non_editable_dirty = []
    allowed_names = ["results.tsv", "score.json", note_file_path.name]
    for line in stdout.splitlines():
        filepath = line[3:].strip()
        if (
            not filepath.startswith("src/ordering")
            and not filepath.startswith(".agents")
            and filepath not in allowed_names
        ):
            non_editable_dirty.append(filepath)

    if non_editable_dirty:
        return False, f"Dirty non-editable files in working tree: {non_editable_dirty}. Yukon only accepts edits to src/ordering/."

    submit_cmd = (
        f"yukon submit --note-file {note_file_path.resolve()} "
        f"--model \"{model}\" --harness \"{harness}\""
    )
    print(f"\n{PASS} Pre-submission validation PASSED!")
    print(f"Ready to submit with command:\n  {submit_cmd}")
    return True, submit_cmd


def run_slice_eval(
    repo_root: Path,
    slice_spec: str,
    num_slices: int = 30,
    run_timing: bool = False,
    max_allowed_worst_sec: float = 1.0,
) -> tuple[bool, dict]:
    try:
        from swarm_slice import extract_slice_corpus, parse_slice_spec, compute_bucketed_geomean
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from swarm_slice import extract_slice_corpus, parse_slice_spec, compute_bucketed_geomean

    start_idx, end_idx = parse_slice_spec(
        spec=slice_spec,
        num_slices=num_slices,
    )
    count = end_idx - start_idx
    print(f"\n{INFO} === Swarm Slice Evaluation: indices {start_idx}..{end_idx} (count {count}) ===")

    slice_dir = repo_root / ".slices"
    slice_dir.mkdir(parents=True, exist_ok=True)
    slice_file = slice_dir / f"slice_{start_idx}_{end_idx}.jsonl"
    extract_slice_corpus(start_idx=start_idx, end_idx=end_idx, output_path=slice_file)

    if run_timing:
        ok, msg = tier2_timing_check(repo_root, max_allowed_worst_sec=max_allowed_worst_sec, slice_file=slice_file)
        return ok, {"timing_msg": msg, "start_idx": start_idx, "end_idx": end_idx, "count": count}

    # 1. Profile timing headroom and gather exact per-bucket breakdown on this slice
    probe_code, p_out, _ = run_command(
        ["cargo", "test", "-p", "ssi-candidate-worker", "--release", "--", "--ignored", "--nocapture", "--test-threads=1", "probe_timing_and_score"],
        repo_root,
        env={"SSI_CORPUS_FILE": str(slice_file.resolve())},
    )
    bucket_acc = {"lt_1k": {"ratios": []}, "1k_10k": {"ratios": []}, "gt_10k": {"ratios": []}}
    slowest_row = None
    in_tsv = False
    for line in p_out.splitlines():
        if "--- every order() call, slowest first (TSV) ---" in line:
            in_tsv = True
            continue
        if in_tsv and line.startswith("matrices under") or in_tsv and "--- per-bucket ---" in line:
            in_tsv = False
            continue
        if in_tsv and line and not line.startswith("secs"):
            parts = line.split("\t")
            if len(parts) >= 5:
                try:
                    sec = float(parts[0])
                    mat = parts[1]
                    n_dim = int(parts[2])
                    nnz = int(parts[3])
                    ratio = float(parts[4])
                    if slowest_row is None:
                        slowest_row = (sec, mat, n_dim, nnz, ratio)
                    b_key = "lt_1k" if n_dim < 1000 else ("1k_10k" if n_dim < 10000 else "gt_10k")
                    bucket_acc[b_key]["ratios"].append(ratio)
                except ValueError:
                    pass

    enriched = compute_bucketed_geomean(bucket_acc)
    if slowest_row:
        s_sec, s_mat, s_n, s_nnz, s_r = slowest_row
        print(f"Headroom probe: Slowest matrix in slice is '{s_mat}' at {s_sec:.3f}s (n={s_n}, nnz={s_nnz}, ratio={s_r:.4f})")

    # 2. Build candidate
    if os.environ.get("SSI_ALLOW_UNSANDBOXED_WORKER") == "1":
        build_code, b_out, b_err = run_command(
            ["cargo", "build", "--release", "-p", "ssi-candidate-worker", "--offline", "--locked"],
            repo_root,
        )
    else:
        build_code, b_out, b_err = run_command(["bash", "scripts/local-candidate-build.sh"], repo_root)

    if build_code != 0:
        return False, {"error": f"Candidate build failed:\n{b_out}\n{b_err}"}

    # Re-verify slice_file exists before cargo run (in case build touched it)
    if not slice_file.exists():
        extract_slice_corpus(start_idx=start_idx, end_idx=end_idx, output_path=slice_file)

    # 3. Score under sandboxed watchdog
    t0 = time.time()
    env = {"SSI_CORPUS_FILE": str(slice_file.resolve())}
    if "SSI_ALLOW_UNSANDBOXED_WORKER" in os.environ:
        env["SSI_ALLOW_UNSANDBOXED_WORKER"] = os.environ["SSI_ALLOW_UNSANDBOXED_WORKER"]

    code, stdout, stderr = run_command(
        ["cargo", "run", "--release", "--offline", "--locked", "--", "--note", f"swarm slice {start_idx}..{end_idx}"],
        repo_root,
        env=env,
    )
    elapsed = time.time() - t0

    if code != 0:
        if "exceeded the 2.0s per-matrix cap and was killed" in stdout or "Timeout" in stdout:
            print(f"{FAIL} Watchdog SIGKILL timeout on slice {start_idx}..{end_idx}!")
        return False, {"error": f"Slice evaluation failed in {elapsed:.2f}s:\n{stdout}\n{stderr}", "stdout": stdout}

    score_json_path = repo_root / "score.json"
    if not score_json_path.exists():
        return False, {"error": "score.json was not generated"}

    raw_data = json.loads(score_json_path.read_text())
    raw_data["metrics"]["buckets"] = enriched["metrics"]["buckets"]
    raw_data["metrics"]["weights"] = enriched["metrics"]["weights"]
    raw_data["metrics"]["matrices"] = enriched["metrics"]["matrices"]
    raw_data["slice_metadata"] = {
        "start_idx": start_idx,
        "end_idx": end_idx,
        "count": count,
        "elapsed_sec": elapsed,
        "slowest_matrix": {
            "name": slowest_row[1] if slowest_row else None,
            "seconds": slowest_row[0] if slowest_row else None,
        },
    }
    score_json_path.write_text(json.dumps(raw_data, indent=2))
    score = raw_data.get("score")
    fill = raw_data.get("metrics", {}).get("geomean_fill_ratio")
    print(f"{PASS} Slice evaluation completed in {elapsed:.2f}s (evaluated {count} matrices)")
    if score is not None:
        print(f"       Score: {score:.6f} | Fill Ratio: {fill:.6f}")
    return True, raw_data


def run_swarm_eval(
    repo_root: Path,
    num_slices: int = 30,
    dry_run: bool = True,
    gcs_bucket: str | None = None,
    gcs_prefix: str | None = None,
) -> tuple[bool, dict]:
    try:
        from swarm_slice import generate_matrix_slices
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from swarm_slice import generate_matrix_slices

    slices = generate_matrix_slices(num_slices=num_slices)
    print(f"\n{INFO} === Cloud Swarm Evaluation ({num_slices} slices) ===")
    print(f"Generated {len(slices)} tasks partitioning corpus.")

    runtime_paths = [
        repo_root / "agystack-runtime.json",
        Path(os.path.expanduser("~/.gemini/config/plugins/agystack/agystack-runtime.json")),
        Path(os.path.expanduser("~/projects/pstack-agy/agystack-runtime.json")),
    ]
    cfg = {}
    for p in runtime_paths:
        if p.is_file():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    bucket = gcs_bucket or cfg.get("gcs_bucket", "agystack-swarm-results-prod")
    prefix = gcs_prefix or f"swarm-eval-{int(time.time())}"

    dispatch_script = Path(os.path.expanduser("~/projects/pstack-agy/skills/swarm/scripts/cloud_dispatch.py"))
    if not dispatch_script.is_file():
        dispatch_script = Path(os.path.expanduser("~/.gemini/config/plugins/agystack/skills/swarm/scripts/cloud_dispatch.py"))

    manifest_file = repo_root / ".slices" / "swarm_manifest.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps(slices, indent=2))

    cmd = [
        sys.executable,
        str(dispatch_script),
        "--manifest", str(manifest_file),
        "--gcs-bucket", bucket,
        "--gcs-prefix", prefix,
    ]
    if dry_run:
        cmd.append("--dry-run")
        print(f"Executing dry-run dispatch with {manifest_file}...")
        code, stdout, stderr = run_command(cmd, repo_root)
        print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
        return code == 0, {"dry_run": True, "slices": num_slices, "manifest": str(manifest_file)}

    print(f"Launching live swarm execution across {num_slices} workers...")
    code, stdout, stderr = run_command(cmd, repo_root)
    print(stdout)
    if code != 0:
        return False, {"error": stderr or stdout}

    return True, {"live": True, "slices": num_slices}


def main() -> int:
    parser = argparse.ArgumentParser(description="matrices.fast verification harness")
    parser.add_argument("--lint-only", action="store_true", help="Run static anti-pattern linter only (<0.1s)")
    parser.add_argument("--tier0", action="store_true", help="Run Tier 0: purity & cargo check")
    parser.add_argument("--tier1", action="store_true", help="Run Tier 1: unit & determinism tests")
    parser.add_argument("--tier2", action="store_true", help="Run Tier 2: timing headroom probe")
    parser.add_argument("--smoke", type=int, nargs="?", const=1000, default=None, help="Run Tier 3: smoke eval with SSI_MAX_MATRIX_N (default: 1000)")
    parser.add_argument("--full", action="store_true", help="Run Tier 4: full 300-matrix evaluation")
    parser.add_argument("--baseline", type=float, default=0.845048, help="Baseline score for comparison (default: 0.845048)")
    parser.add_argument("--check-submission", action="store_true", help="Validate submission readiness")
    parser.add_argument("--note-file", type=str, help="Path to markdown submission note")
    parser.add_argument("--model", type=str, default="Gemini 3.8 Flash", help="Exact model name for submission")
    parser.add_argument("--harness", type=str, default="Antigravity", help="Harness name for submission")
    parser.add_argument("--swarm-slice", type=str, help="Evaluate specific slice (e.g. '0:10' or index 0..29)")
    parser.add_argument("--swarm-eval", action="store_true", help="Launch distributed 30-slice swarm evaluation")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run dispatch for --swarm-eval")
    parser.add_argument("--num-slices", type=int, default=30, help="Number of slices for swarm operations (default: 30)")
    parser.add_argument("--gcs-bucket", type=str, help="Cloud Storage results bucket override")
    parser.add_argument("--gcs-prefix", type=str, help="Cloud Storage object prefix override")
    parser.add_argument("--json-out", type=str, help="Write verification evidence to JSON file")

    args = parser.parse_args()
    repo_root = find_repo_root()

    evidence = {
        "timestamp": time.time(),
        "repo_root": str(repo_root),
        "results": {}
    }

    if args.lint_only:
        ok, errors, warnings = lint_ordering_source(repo_root)
        for w in warnings:
            print(f"{WARN} [warning] {w}")
        for err in errors:
            print(f"{FAIL} [error] {err}")
        if ok:
            print(f"{PASS} Static linter passed cleanly.")
        return 0 if ok else 1

    if not (args.tier0 or args.tier1 or args.tier2 or args.smoke or args.full or args.check_submission or args.swarm_slice or args.swarm_eval):
        args.tier0 = True
        args.tier1 = True

    overall_success = True

    if args.tier0:
        ok, msg = tier0_purity_check(repo_root)
        evidence["results"]["tier0"] = {"success": ok, "message": msg}
        if not ok:
            overall_success = False

    if args.tier1 and overall_success:
        ok, msg = tier1_unit_tests(repo_root)
        evidence["results"]["tier1"] = {"success": ok, "message": msg}
        if not ok:
            overall_success = False

    if args.swarm_slice and overall_success:
        ok, data = run_slice_eval(
            repo_root=repo_root,
            slice_spec=args.swarm_slice,
            num_slices=args.num_slices,
            run_timing=args.tier2,
        )
        evidence["results"]["swarm_slice"] = {"success": ok, "data": data}
        if not ok:
            overall_success = False
            err_msg = data.get("error", "Slice evaluation failed") if isinstance(data, dict) else str(data)
            print(f"{FAIL} {err_msg}", file=sys.stderr)
    elif args.tier2 and overall_success:
        ok, msg = tier2_timing_check(repo_root)
        evidence["results"]["tier2"] = {"success": ok, "message": msg}
        if not ok:
            overall_success = False

    if args.swarm_eval and overall_success:
        ok, data = run_swarm_eval(
            repo_root=repo_root,
            num_slices=args.num_slices,
            dry_run=args.dry_run or not bool(os.environ.get("LIVE_SWARM")),
            gcs_bucket=args.gcs_bucket,
            gcs_prefix=args.gcs_prefix,
        )
        evidence["results"]["swarm_eval"] = {"success": ok, "data": data}
        if not ok:
            overall_success = False

    if args.smoke is not None and overall_success:
        ok, data = tier3_smoke_eval(repo_root, max_n=args.smoke)
        evidence["results"]["tier3_smoke"] = {"success": ok, "data": data}
        if not ok:
            overall_success = False

    if args.full and overall_success:
        ok, data = tier4_full_eval(repo_root, baseline_score=args.baseline)
        evidence["results"]["tier4_full"] = {"success": ok, "data": data}
        if not ok:
            overall_success = False

    if args.check_submission and overall_success:
        if not args.note_file:
            print(f"{FAIL} --note-file is required for --check-submission")
            overall_success = False
        else:
            ok, cmd = check_submission_readiness(
                repo_root=repo_root,
                note_file_path=Path(args.note_file),
                model=args.model,
                harness=args.harness,
                frontier_score=args.baseline
            )
            evidence["results"]["pre_submit"] = {"success": ok, "command": cmd}
            if not ok:
                overall_success = False

    if args.json_out:
        out_p = Path(args.json_out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(evidence, indent=2))
        print(f"\n{INFO} Evidence written to {out_p}")

    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())
