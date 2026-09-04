---
name: swarm
description: "Fan out N parallel workers, drain them, and return one report. Use for /swarm, 'swarm this', or parallel coverage, races, gauntlets, and exploration."
disable-model-invocation: true
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

1. Write the array of task briefs to a JSON manifest:
   `<appDataDir>/brain/<conversation-id>/scratch/swarm-<slug>/manifest.json`
2. Launch cloud dispatch CLI:
   ```bash
   python3 "$(find ~/.gemini/config/plugins/agystack .agents/plugins/agystack skills/swarm -name "cloud_dispatch.py" 2>/dev/null | head -1)" --manifest <manifest-path> --tasks <N> --parallelism 100
   ```
   Pass `--vertex` to enable Vertex AI mode (IAM / ADC authentication) instead of Google AI Studio API key. When `agystack-runtime.json` specifies `"auth_mode": "vertex"`, workers authenticate via Google Cloud IAM/ADC without requiring `GEMINI_API_KEY`.
3. The dispatcher automatically retrieves `GH_TOKEN` via `gh auth token`, configures authentication (`GEMINI_API_KEY` or Vertex AI IAM/ADC), executes the Cloud Run Job, and streams output.

Every brief stands alone. Include goal, scope, exact slice, verification command, and expected report format (`[STATUS: PASS|ISSUES|BLOCKED]` with evidence).

## Phase C: Aggregate

1. For local workers: collect terminal reports from `invoke_subagent`.
2. For cloud workers: `cloud_dispatch.py` parses structured container logs and provides an aggregated status table. Fetch worker branches (`git fetch origin`) to inspect code changes on `worker-{task_index}`.
3. Apply selection rule (first pass, rank all, best-of).
4. Build a compact result table, one-line evidenced issues, and explicit dropouts.

## Phase D: Report

Return one consolidated in-chat report with the table, issue one-liners, gaps or dropouts, and the race rule when used.
