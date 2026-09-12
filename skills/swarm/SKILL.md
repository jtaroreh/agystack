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
   - If `agystack-runtime.json` does not exist or specifies `"runtime": "local"`, use local subagents for N <= 8.
   - If N > 8 or `agystack-runtime.json` specifies `"runtime": "cloud-run"`, use Cloud Run dispatch.

## Phase B: Fan out

### Local Subagents (N <= 8)

Spawn all N workers in one `invoke_subagent` call with `TypeName: "poteto-agent"` (or `"self"`), `Role: "Swarm Worker (<slice>)"`, `Workspace: "branch"`, and the configured model. In each worker prompt, explicitly provide `{PARENT_CONVERSATION_ID}` and mandate that upon task completion, the worker MUST invoke `send_message` with `Recipient: "{PARENT_CONVERSATION_ID}"` to deliver its slice status and findings (mirroring `skills/interrogate/references/reviewer-prompt.md`) so the coordinator receives reactive wakeups without timing out.

**Reactive Dispatch & Watchdog Protocol:**
- **Turn 1 (Dispatch & Arm):** Dispatch local workers via `invoke_subagent` and arm a single global watchdog deadline using `schedule(DurationSeconds: 300..600, Prompt="Watchdog: swarm workers timed out", TimerCondition: "never")`.
- **Turn 2 (Yield):** Output a status update with ZERO tool calls (`tool_calls: []`). Never run busy polling loops on local subagents.
- **Incremental Arrivals:** On each worker arrival via `send_message`, record slice results and yield immediately with ZERO tool calls if workers remain active.
- **Teardown & Completion:** Once all N workers complete, cancel the watchdog timer via `manage_task(Action: "kill", TaskId: <timer_task_id>)` and proceed to Phase C. If the watchdog fires, diagnose via `manage_subagents(Action: "list")`, terminate unresponsive workers (`manage_subagents(Action: "kill", ConversationIds: [<id>])`), and aggregate available slice results.

### Cloud Run Dispatch (N > 8 or Cloud Run Runtime)

Cloud Run swarms enable parallel execution across dozens or hundreds of container tasks.

**Quota & Auth Prerequisites:**
- **Paid Tier API Key or Vertex AI:** Cloud Run swarms require either a paid Google AI Studio tier (Pay-as-you-go / Tier 1+) or verified Vertex AI permissions (`roles/aiplatform.user` on the target project). Free-tier API keys (5 RPM) are prohibited as parallel container workers will immediately exhaust quota and fail.
- **Git Authentication:** A valid GitHub token (`gh auth token` or `GH_TOKEN` / `GITHUB_TOKEN`) with repository clone access. Under the zero-push architecture, cloud containers do not require git push access.

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
   Run active pre-flight validation to ensure credentials, git remotes, model endpoints, and GCS buckets are reachable before spinning up compute:
   ```bash
   python3 "${AGYSTACK_DISPATCH_SCRIPT:-$(find -L "$HOME/.gemini/config/plugins/agystack" ".agents/plugins/agystack" "skills/swarm/scripts" -name cloud_dispatch.py 2>/dev/null | head -n 1)}" --preflight --gcs-bucket <bucket> --model gemini-3.8-flash --vertex
   ```
   (Pre-flight runs automatically by default during dispatch unless `--no-preflight` is specified.)

3. **Launch the Swarm & Stream Real-Time Milestones:**
   Launch cloud dispatch CLI with unbuffered streaming and fail-fast candidate evaluation:
   ```bash
   python3 "${AGYSTACK_DISPATCH_SCRIPT:-$(find -L "$HOME/.gemini/config/plugins/agystack" ".agents/plugins/agystack" "skills/swarm/scripts" -name cloud_dispatch.py 2>/dev/null | head -n 1)}" \
     --manifest <manifest-path> \
     --tasks <N> \
     --gcs-bucket <bucket> \
     --model gemini-3.8-flash \
     --vertex
   ```
   Pass `--vertex` to enable Vertex AI mode (IAM / ADC authentication) instead of Google AI Studio API key. When `agystack-runtime.json` specifies `"auth_mode": "vertex"`, workers authenticate via Google Cloud IAM/ADC without requiring `GEMINI_API_KEY`. Concurrency (default 16) and fail-fast zero retries (`--max-retries=0`) are configured directly on the Cloud Run job template during `/setup-agystack` (`setup_runtime.py`).

   **Asynchronous Coordination & Detached Monitoring:**
   When coordinating asynchronously, pass `--no-wait` to `cloud_dispatch.py` to prevent blocking the agent turn:
   ```bash
   # Dispatch asynchronously and return execution handle immediately
   python3 "${AGYSTACK_DISPATCH_SCRIPT:-$(find -L "$HOME/.gemini/config/plugins/agystack" ".agents/plugins/agystack" "skills/swarm/scripts" -name cloud_dispatch.py 2>/dev/null | head -n 1)}" \
     --manifest <manifest-path> \
     --tasks <N> \
     --gcs-bucket <bucket> \
     --no-wait

   # Harvest and rank candidate patches from an existing session without launching compute
   python3 "${AGYSTACK_DISPATCH_SCRIPT:-$(find -L "$HOME/.gemini/config/plugins/agystack" ".agents/plugins/agystack" "skills/swarm/scripts" -name cloud_dispatch.py 2>/dev/null | head -n 1)}" \
     --harvest-session <session_id> --gcs-bucket <bucket> --baseline-score <float>

   # Attach to a running execution to stream milestones and harvest upon completion
   python3 "${AGYSTACK_DISPATCH_SCRIPT:-$(find -L "$HOME/.gemini/config/plugins/agystack" ".agents/plugins/agystack" "skills/swarm/scripts" -name cloud_dispatch.py 2>/dev/null | head -n 1)}" \
     --wait-execution <execution_name> --session <session_id> --gcs-bucket <bucket>
   ```
   The dispatcher automatically executes pre-flight checks, retrieves `GH_TOKEN` via `gh auth token`, executes the Cloud Run Job, streams real-time unbuffered `[MILESTONE]` execution progress directly to stdout as events occur, and aggregates final candidate patches into a ranked summary report. Dispatchers and coordinators must never block passively on buffered command execution.

   **Observability, Loop Alarms & In-Flight Steering:**
   - **Task-Attributed Milestones:** Workers emit streaming stdout milestones formatted as `[MILESTONE] [TASK <i>] [PHASE: <phase>] <detail>`, standardizing progress tracking and capturing internal SDK lifecycle events.
   - **Loop Alarms (StagnancyTracker):** Non-destructive repetitiveness detection alerts on 3 consecutive identical tool invocations (`[ALARM] [TASK <i>] [POTENTIAL_LOOP]`) and injects warnings into model context without terminating execution.
   - **Live Mailbox Steering:** Orchestrators steer in-flight workers via GCS mailbox instructions (`python3 cloud_dispatch.py --session <session_id> --steer <task_index> "ABORT|CANCEL|<instruction>"`). Workers intercept instructions at pre-tool execution to abort cleanly or adapt agent focus.
   - **Subprocess Timeout Guards:** Shell command execution and verification scripts are bounded by explicit environment timeouts (`COMMAND_TIMEOUT`, `VERIFY_TIMEOUT`), preventing hanging processes from stalling container lifecycle.

Every brief stands alone. Include goal, scope, exact slice, verification command, and expected report format (`[STATUS: PASS]`, `[STATUS: ISSUES]`, or `[STATUS: BLOCKED]` with evidence).

## Phase C: Aggregate & Early Harvest

1. For local workers: collect terminal reports from `invoke_subagent`.
2. For cloud workers: `cloud_dispatch.py` automatically harvests candidate patches from GCS into `.slices/<session_id>/task-<i>/` and displays candidate patch file locations in the execution summary.
3. Apply selection rule (first pass, rank all, best-of): rank candidates by score delta descending.
4. **Candidate Integration Protocol:** Apply the winning `patch.diff` to a local worktree (`git apply .slices/<session_id>/task-<i>/patch.diff`), run local verification, and commit. If verified, re-baseline and evaluate subsequent candidates sequentially. Never merge or compose multiple candidate patches simultaneously without intermediate verification (`principle-sequence-verifiable-units`).
5. Build a compact result table, one-line evidenced issues, and explicit dropouts.

## Phase D: Report

Return one consolidated in-chat report with the table, issue one-liners, gaps or dropouts, and the race rule when used.
