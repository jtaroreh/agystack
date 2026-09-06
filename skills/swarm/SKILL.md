---
name: swarm
description: "Fan out N parallel workers, drain them, and return one report. Use for /swarm, 'swarm this', or parallel coverage, races, gauntlets, and exploration."
---

# Swarm

Fan out N parallel workers locally or across Google Cloud Run. Workers cover separate slices or race the same brief. The parent coordinator waits, aggregates, and returns one consolidated report.

## Start

Open a todolist with one entry per phase before launching anything.

1. Frame
2. Fan out
3. Aggregate
4. Report

## Phase A: Frame

1. State the done predicate and the deliverable artifact or report.
2. Choose the shape: partition into slices, race N workers on identical briefs, or mix both. For a race, declare `first pass`, `rank all`, or `best-of`.
3. Set N. N is total workers.
4. Pick worker model from `swarm workers` in `~/.gemini/config/plugins/agystack/rules/agystack-models.md` (default: `flash`).
5. Check execution runtime:
   - If N <= 8 and runtime is local: use local subagents.
   - If N > 8 or `agystack-runtime.json` specifies `"runtime": "cloud-run"`: use Cloud Run dispatch.

## Phase B: Fan out

### Local Subagents (N <= 8)

Spawn all N workers in one `invoke_subagent` call with `TypeName: "poteto-agent"` (or `"self"`), `Role: "Swarm Worker (<slice>)"`, `Workspace: "branch"`, and the configured model.

### Cloud Run Dispatch (N > 8 or Cloud Run Runtime)

Cloud Run swarms enable parallel execution across dozens or hundreds of container tasks.

**Quota & Auth Prerequisites:**
- **Paid Tier API Key or Vertex AI:** Cloud Run swarms require either a paid Google AI Studio tier (Pay-as-you-go / Tier 1+) or verified Vertex AI permissions (`roles/aiplatform.user` on the target project). Free-tier API keys (5 RPM) are prohibited as parallel container workers will immediately exhaust quota and fail.
- **Git Authentication:** A valid GitHub token (`gh auth token` or `GH_TOKEN` / `GITHUB_TOKEN`) with push access to the repository.

**Dispatch Workflow:**

1. **Prepare Task Manifest:**
   Create a manifest JSON array at `<appDataDir>/brain/<conversation-id>/scratch/swarm-<slug>/manifest.json`.
   The manifest supports both autonomous agent coding (`"type": "agent"`, default) and direct command execution (`"type": "command"` for sweeps/benchmarks), along with optional `"verify_command"` and `"candidate_files"`:
   ```json
   [
     {
       "task_index": 0,
       "type": "agent",
       "branch": "worker-0",
       "brief": "Implement hypothesis A in src/ordering/mod.rs and verify with test suite.",
       "verify_command": "cargo test --release",
       "candidate_files": ["src/ordering/mod.rs"]
     },
     {
       "task_index": 1,
       "type": "command",
       "command": "python3 evaluate_slice.py --slice 0..50"
     }
   ]
   ```

2. **Execute Active Pre-Flight Check:**
   Run active pre-flight validation to ensure credentials, git remotes, and model endpoints are reachable before spinning up compute:
   ```bash
   python3 "${AGYSTACK_DISPATCH_SCRIPT:-$HOME/.gemini/config/plugins/agystack/skills/swarm/scripts/cloud_dispatch.py}" --preflight --model gemini-3.8-flash --vertex
   ```
   (Pre-flight runs automatically by default during dispatch unless `--no-preflight` is specified.)

3. **Launch the Swarm & Stream Real-Time Milestones:**
   Launch cloud dispatch CLI with unbuffered streaming and zero retries to fail broken hypotheses fast:
   ```bash
   python3 "${AGYSTACK_DISPATCH_SCRIPT:-$HOME/.gemini/config/plugins/agystack/skills/swarm/scripts/cloud_dispatch.py}" \
     --manifest <manifest-path> \
     --tasks <N> \
     --parallelism 100 \
     --max-retries 0 \
     --model gemini-3.8-flash \
     --vertex
   ```
   Pass `--vertex` to enable Vertex AI mode (IAM / ADC authentication) instead of Google AI Studio API key. When `agystack-runtime.json` specifies `"auth_mode": "vertex"`, workers authenticate via Google Cloud IAM/ADC without requiring `GEMINI_API_KEY`.
   The dispatcher automatically executes pre-flight checks, retrieves `GH_TOKEN` via `gh auth token`, executes the Cloud Run Job with `--max-retries 0`, streams real-time unbuffered `[MILESTONE]` execution progress directly to stdout as events occur, and aggregates final candidate commits into a summary report. Dispatchers and coordinators must never block passively on buffered command execution.

Every brief stands alone. Include goal, scope, exact slice, verification command, and expected report format (`[STATUS: SMOKE_PASS|DEV_IMPROVED|REGRESSED|BLOCKED]` with evidence).

## Phase C: Aggregate & Early Harvest

1. For local workers: collect terminal reports from `invoke_subagent`.
2. For cloud workers: `cloud_dispatch.py` parses structured container logs and provides an aggregated status table. Actively poll and fetch remote worker branches as tasks progress (`git fetch origin "refs/heads/worker-*:refs/remotes/origin/worker-*"`) and inspect storage manifests (`gs://<bucket>/task-*`).
3. Apply selection rule (first pass, rank all, best-of) with early candidate evaluation: evaluate winning branches as soon as they appear without waiting for 100% completion or hanging stragglers.
4. Build a compact result table, one-line evidenced issues, and explicit dropouts.
5. **Candidate Integration Protocol:** When multiple worker branches succeed, rank candidates by isolated score delta descending. Cherry-pick candidate #1 onto the target trunk and run verification. If verified, re-baseline and evaluate candidate #2 against the updated trunk. Never compose or merge multiple worker branches simultaneously without intermediate verification (`principle-sequence-verifiable-units`).

## Phase D: Report

Return one consolidated in-chat report with the table, issue one-liners, gaps or dropouts, and the race rule when used.
