# Cloud Run Model Heterogeneity and Observability plan

This program equips agystack with Vertex AI Model Garden multi-provider execution and native IDE subagent observability for Cloud Run swarms.
Four pull requests deliver model routing, shadow transcript projection, live dashboard artifacts, and conversational steering.

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, a file, a log line, a screenshot, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs `skills/poteto-mode/playbooks/autopilot-stack.md`. The operator reviews gate artifacts and lands the Graphite stack.

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Arm the program

- [ ] State the protocol and this plan to the operator, then stop. Start execution only on the operator's explicit go.
- [ ] On the operator's go, arm a `/goal` with this exact text. "Deploy Vertex AI Model Garden routing and shadow transcript projection in four PRs, verifying unit, live, and perf for each, with operator review on interaction gates and Graphite merge."
- [ ] Read these from trunk at program start. Re-read them at every tick.
  - [ ] `git show origin/main:skills/poteto-mode/playbooks/autopilot-stack.md`
  - [ ] `git show origin/main:skills/swarm/SKILL.md`
  - [ ] `git show origin/main:skills/poteto-mode/playbooks/opening-a-pr.md`
- [ ] Arm the 30-minute audit tick via the Antigravity `schedule` tool (`CronExpression="*/30 * * * *"` or recurring timer). Never leave the cadence to memory.
- [ ] Use this tick prompt, verbatim. "Re-read the execution playbook from trunk and the armed /goal. Audit the operation against both and fix drift in this tick. Probe every active lane and judge progress by side effects only. Stand down a stuck lane and dispatch its replacement now. Post a status message to the operator in chat when state changes, a gate blocks, or merges land (or update the status artifact if unchanged), with the queue table of PR, owner, state, and head SHA, the verdicts since the last tick, what merged, open operator gates, and blockers. Then conclude the tick and yield the turn immediately with zero tool calls."
- [ ] On the operator's hold or stand-down, send every owner a zero-writes order at once.

### Spawn owners

- [ ] Spawn one owner per PR with the full lifecycle the execution playbook names.
- [ ] Follow this dependency graph. Start dependent work only after its parent merges, or base it on the parent branch when the execution playbook stacks.
  - [ ] PR 1 and PR 2 both branch from `main`.
  - [ ] PR 3 after PR 2.
  - [ ] PR 4 after PR 3.
- [ ] Hold the file boundaries. PR 1 touches worker container files. PR 2 and PR 3 touch dispatcher telemetry files. PR 4 touches coordinator skill files.
- [ ] Hold the review gate. PR 2 and PR 3 change developer interaction. They wait for the operator's review in chat with screenshots and a video before merge.

### PR mechanics, for every PR

- [ ] Open the PR ready, never draft, with `gh pr create` and `draft: false`, or with Graphite `gt` for a stack.
- [ ] Run the repo's lint and typecheck once before the PR-facing push. Push with hooks on.
- [ ] Run `/deslop` before each commit and `/no-comments` before review.
- [ ] Triage every Bugbot and security-reviewer comment per `../references/bugbot-triage.md`.
- [ ] Rebase onto current trunk before the initial code-ready report, keeping merge base during fix rounds and rebasing only on conflicts or at merge prep.

### Verdict and merge, for every PR

- [ ] At the merge-ready head SHA, run the swarm per `skills/swarm/SKILL.md`. One gates lane. The ten live lanes from the PR's **Verify, live** block. The perf lane from its **Verify, perf** block. One audit lane that reads the diff and the receipts and distrusts the PR body.
- [ ] Clean only when every lane is `PASS`. Findings go back to the owner. A new head gets a fresh swarm and a fresh verdict.
- [ ] The root appends the PR to the Graphite stack and the operator lands it.

### Boot recipe, for every live lane

Each live lane runs on its own branch or worktree at the PR head. Drive through browser subagent tools, CLI runners, or project verification skills.

- [ ] `git fetch origin <head-branch> && git checkout <head SHA>`.
- [ ] Run Python virtual environment setup via `.venv/bin/activate`.
- [ ] Deliver input only through the control skill commands and CLI invocations.
- [ ] Save every screenshot to `/tmp/swarm-<pr-id>/worker-<n>/<slug>.png` and return the paths with the report.

## Route Vertex AI partner models in cloud worker container (PR 1)

**Depends on.** None.

**Files.**

- [ ] Edit `skills/swarm/scripts/requirements.txt`.
- [ ] Edit `skills/swarm/scripts/Dockerfile`.
- [ ] Edit `skills/swarm/scripts/cloud_worker.py`.
- [ ] Edit `skills/setup-agystack/scripts/setup_runtime.py`.
- [ ] Create `tests/test_cloud_worker_vertex_partner.py`.

**Build.**

- [ ] Add `anthropic[vertex]>=0.40.0` to `requirements.txt` and install it in Dockerfile.
- [ ] Add generic partner model dispatcher in `cloud_worker.py` routing Sonnet 5.5, Opus 5.5, and Fable 5.1 via Vertex ADC.
- [ ] Add Model Garden partner model preflight probe in `setup_runtime.py`.

**You see.**

- [ ] `cloud_worker.py` prints `[MILESTONE] [TASK 0] [PHASE: RUNNING_AGENT] Vertex Model Garden agent (claude-5-5-sonnet)`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Unit tests for Claude 5.5 and Fable 5.1 model alias resolution and Vertex partner client initialization. Run `pytest tests/test_cloud_worker_vertex_partner.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `flash` at the PR head, per the boot recipe.

- [ ] Lane 1. Resolve `claude-5-5-sonnet` alias. Save `/tmp/swarm-pr-1/worker-1/alias-sonnet-5-5.png`. Pass when alias resolves to Vertex publisher path.
- [ ] Lane 2. Resolve `claude-5-5-opus` alias. Save `/tmp/swarm-pr-1/worker-2/alias-opus-5-5.png`. Pass when alias resolves to Vertex publisher path.
- [ ] Lane 3. Fallback when partner model SDK missing. Save `/tmp/swarm-pr-1/worker-3/missing-sdk.png`. Pass when worker returns BLOCKED status with diagnostic.
- [ ] Lane 4. Verify ADC project pass-through. Save `/tmp/swarm-pr-1/worker-4/adc-project.png`. Pass when project matches GCP environment.
- [ ] Lane 5. Verify ADC region selection. Save `/tmp/swarm-pr-1/worker-5/adc-region.png`. Pass when region falls back to us-central1.
- [ ] Lane 6. Test harness mock execution. Save `/tmp/swarm-pr-1/worker-6/mock-execution.png`. Pass when dummy task exits with STATUS PASS.
- [ ] Lane 7. Manifest with mixed Gemini, Claude 5.5, and Fable 5.1 tasks. Save `/tmp/swarm-pr-1/worker-7/mixed-manifest.png`. Pass when task router picks correct client per task.
- [ ] Lane 8. Preflight validation of Model Garden permissions. Save `/tmp/swarm-pr-1/worker-8/preflight-probe.png`. Pass when check-model-garden flag succeeds.
- [ ] Lane 9. Zero-push git preservation under Claude agent. Save `/tmp/swarm-pr-1/worker-9/zero-push.png`. Pass when no git push runs.
- [ ] Lane 10. Candidate diff harvesting under Claude task. Save `/tmp/swarm-pr-1/worker-10/patch-harvest.png`. Pass when candidate patch diff is generated.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Worker startup overhead before model dispatch.
- [ ] Probe. Measure elapsed time between container boot and model client creation in `cloud_worker.py`.
- [ ] Baseline. Record trunk worker startup latency of 1.4 seconds.
- [ ] Rule. Head startup latency must not exceed 2.0 seconds.

**Review gate.** None. PR 1 is not review-gated.

**Merge.**

- [ ] Root clean verdict at head SHA.
- [ ] Bugbot triage complete.
- [ ] Rebased onto main with patch-id unchanged.
- [ ] Operator appends to stack.

## Project cloud worker telemetry into local shadow transcripts (PR 2)

**Depends on.** None.

**Files.**

- [ ] Edit `skills/swarm/scripts/cloud_worker.py`.
- [ ] Edit `skills/swarm/scripts/cloud_dispatch.py`.
- [ ] Create `tests/test_shadow_transcript_projection.py`.

**Build.**

- [ ] Emit structured JSON telemetry for tool calls and thoughts in `cloud_worker.py`.
- [ ] In `cloud_dispatch.py`, create `<appDataDir>/brain/cloud-<session_id>-task-<index>/` directory with valid `transcript.jsonl`.
- [ ] Print clickable `conversation://cloud-<session_id>-task-<index>` links in dispatch logs.

**You see.**

- [ ] `cloud_dispatch.py` creates local `transcript.jsonl` containing `USER_INPUT`, `PLANNER_RESPONSE`, and `TOOL_RESPONSE` entries.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Unit tests for JSONL transcript formatting and incremental event appending. Run `pytest tests/test_shadow_transcript_projection.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `flash` at the PR head, per the boot recipe.

- [ ] Lane 1. Initialize shadow transcript on task dispatch. Save `/tmp/swarm-pr-2/worker-1/init-transcript.png`. Pass when directory and transcript exist.
- [ ] Lane 2. Project agent thought tokens into PLANNER_RESPONSE. Save `/tmp/swarm-pr-2/worker-2/thought-projection.png`. Pass when thoughts appear in JSONL.
- [ ] Lane 3. Project tool call arguments. Save `/tmp/swarm-pr-2/worker-3/tool-args.png`. Pass when tool call args match JSON schema.
- [ ] Lane 4. Project tool execution output. Save `/tmp/swarm-pr-2/worker-4/tool-output.png`. Pass when tool response status is recorded.
- [ ] Lane 5. Clickable conversation URL generation. Save `/tmp/swarm-pr-2/worker-5/conv-url.png`. Pass when URL formats as `conversation://cloud-...`.
- [ ] Lane 6. Ensure zero stdout token flooding. Save `/tmp/swarm-pr-2/worker-6/token-shield.png`. Pass when stdout only contains milestones.
- [ ] Lane 7. Handle concurrent transcript writes across 8 workers. Save `/tmp/swarm-pr-2/worker-7/concurrency.png`. Pass when no file lock collisions occur.
- [ ] Lane 8. Corrupted log recovery. Save `/tmp/swarm-pr-2/worker-8/log-corruption.png`. Pass when parser skips malformed lines gracefully.
- [ ] Lane 9. Antigravity transcript schema compliance. Save `/tmp/swarm-pr-2/worker-9/schema-check.png`. Pass when fields match native transcript format.
- [ ] Lane 10. Final session cleanup preserves transcript. Save `/tmp/swarm-pr-2/worker-10/cleanup.png`. Pass when transcript remains after container exits.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Telemetry projection latency from Cloud Logging to local disk.
- [ ] Probe. Measure delay between milestone log timestamp and local file write timestamp.
- [ ] Baseline. Record polling loop interval baseline of 2.0 seconds.
- [ ] Rule. Telemetry projection latency must remain under 3.5 seconds.

**Review gate.** The operator reviews before merge.

- [ ] Copy lane 5 screenshot into `/tmp/media/pr-2-review-conv-link.png`.
- [ ] Record a 30 to 60 second video showing the conversation link opening in Antigravity inspector. Save as `/tmp/media/pr-2-review.mp4`.
- [ ] Post the screenshot and video in chat for operator review.

**Merge.**

- [ ] Root clean verdict at head SHA.
- [ ] Bugbot triage complete.
- [ ] Rebased onto main with patch-id unchanged.
- [ ] Operator appends to stack.

## Maintain live markdown swarm dashboard and console deep links (PR 3)

**Depends on.** PR 2.

**Files.**

- [ ] Edit `skills/swarm/scripts/cloud_dispatch.py`.
- [ ] Create `tests/test_swarm_dashboard_generation.py`.

**Build.**

- [ ] Add `SwarmDashboardWriter` class in `cloud_dispatch.py` writing `<appDataDir>/brain/<conversation-id>/swarm_dashboard.md`.
- [ ] Render tabular view with task index, model name, active tool, elapsed time, status badge, and conversation link.
- [ ] Format Google Cloud Console deep links for execution run and pre-filtered Cloud Logging queries.

**You see.**

- [ ] `swarm_dashboard.md` artifact updates every polling tick with live task statuses and deep links.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Unit tests for markdown table generation, badge rendering, and console URL escaping. Run `pytest tests/test_swarm_dashboard_generation.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `flash` at the PR head, per the boot recipe.

- [ ] Lane 1. Render initial pending table on dispatch. Save `/tmp/swarm-pr-3/worker-1/dashboard-init.png`. Pass when all tasks show Queued status.
- [ ] Lane 2. Update phase transition to RUNNING_AGENT. Save `/tmp/swarm-pr-3/worker-2/phase-running.png`. Pass when status badge changes to Running.
- [ ] Lane 3. Update current tool name and args snippet. Save `/tmp/swarm-pr-3/worker-3/tool-update.png`. Pass when active tool column updates.
- [ ] Lane 4. Update elapsed timer column. Save `/tmp/swarm-pr-3/worker-4/elapsed-time.png`. Pass when elapsed seconds increment accurately.
- [ ] Lane 5. Render PASS badge on task completion. Save `/tmp/swarm-pr-3/worker-5/status-pass.png`. Pass when green badge renders.
- [ ] Lane 6. Render ISSUES badge on test failure. Save `/tmp/swarm-pr-3/worker-6/status-fail.png`. Pass when warning badge renders.
- [ ] Lane 7. Generate Cloud Run Execution console link. Save `/tmp/swarm-pr-3/worker-7/link-execution.png`. Pass when URL contains project and execution name.
- [ ] Lane 8. Generate pre-filtered Cloud Logging link. Save `/tmp/swarm-pr-3/worker-8/link-logging.png`. Pass when URL contains log query filter.
- [ ] Lane 9. Generate GCS artifact folder link. Save `/tmp/swarm-pr-3/worker-9/link-gcs.png`. Pass when URL points to session prefix.
- [ ] Lane 10. Atomic write replacement prevents partial reads. Save `/tmp/swarm-pr-3/worker-10/atomic-write.png`. Pass when write uses temporary file rename.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Markdown dashboard write time.
- [ ] Probe. Benchmark time taken to format and write `swarm_dashboard.md` across 32 tasks.
- [ ] Baseline. Measure trunk disk write baseline of 5 milliseconds.
- [ ] Rule. Dashboard write time must stay under 25 milliseconds.

**Review gate.** The operator reviews before merge.

- [ ] Copy lane 5 screenshot into `/tmp/media/pr-3-review-dashboard.png`.
- [ ] Record a 30 to 60 second video showing the live dashboard updating during a test run. Save as `/tmp/media/pr-3-review.mp4`.
- [ ] Post the screenshot and video in chat for operator review.

**Merge.**

- [ ] Root clean verdict at head SHA.
- [ ] Bugbot triage complete.
- [ ] Rebased onto main with patch-id unchanged.
- [ ] Operator appends to stack.

## Conversational mailbox steering tool for coordinator (PR 4)

**Depends on.** PR 3.

**Files.**

- [ ] Edit `skills/swarm/scripts/cloud_dispatch.py`.
- [ ] Edit `skills/swarm/SKILL.md`.
- [ ] Create `skills/swarm/scripts/steer_cloud_task.py`.
- [ ] Create `tests/test_conversational_steering_tool.py`.

**Build.**

- [ ] Add CLI subcommand `cloud_dispatch.py steer --task <index> --instruction "<text>"`.
- [ ] Wrap steering call in `steer_cloud_task.py` with structured envelope validation.
- [ ] Update `skills/swarm/SKILL.md` to document conversational steering protocol.

**You see.**

- [ ] Coordinator posts steer instruction and receives `[STEER] Instruction delivered to task-1 mailbox in GCS`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Unit tests for steering CLI validation, GCS envelope generation, and abort token handling. Run `pytest tests/test_conversational_steering_tool.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `flash` at the PR head, per the boot recipe.

- [ ] Lane 1. Deliver text steering instruction to worker inbox. Save `/tmp/swarm-pr-4/worker-1/steer-text.png`. Pass when envelope appears in GCS inbox.
- [ ] Lane 2. Intercept steering instruction in pre-tool hook. Save `/tmp/swarm-pr-4/worker-2/hook-intercept.png`. Pass when milestone STEER_APPLIED emits.
- [ ] Lane 3. Deliver ABORT command to cancel running worker. Save `/tmp/swarm-pr-4/worker-3/steer-abort.png`. Pass when milestone ABORT_REQUESTED emits.
- [ ] Lane 4. Broadcast steering instruction to all active workers. Save `/tmp/swarm-pr-4/worker-4/steer-broadcast.png`. Pass when all worker mailboxes receive envelope.
- [ ] Lane 5. Handle steering target out of range error. Save `/tmp/swarm-pr-4/worker-5/invalid-target.png`. Pass when CLI exits with code 1 and error message.
- [ ] Lane 6. Steer instruction reflected in swarm dashboard. Save `/tmp/swarm-pr-4/worker-6/dashboard-steer.png`. Pass when dashboard row notes steer pending.
- [ ] Lane 7. Idempotent re-delivery of steering envelope. Save `/tmp/swarm-pr-4/worker-7/idempotent-steer.png`. Pass when sequence numbers prevent duplicate execution.
- [ ] Lane 8. Handle GCS network timeout during steering. Save `/tmp/swarm-pr-4/worker-8/network-timeout.png`. Pass when retry logic executes successfully.
- [ ] Lane 9. Verify worker prompt injects custom steer context. Save `/tmp/swarm-pr-4/worker-9/prompt-context.png`. Pass when next tool call receives context.
- [ ] Lane 10. Clean up mailbox envelopes upon session completion. Save `/tmp/swarm-pr-4/worker-10/mailbox-cleanup.png`. Pass when inbox files archive cleanly.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. End-to-end steering delivery latency.
- [ ] Probe. Time taken from CLI steer command invocation to GCS object creation confirmation.
- [ ] Baseline. Measure trunk GCS upload baseline of 250 milliseconds.
- [ ] Rule. Steering delivery latency must not exceed 600 milliseconds.

**Review gate.** None. PR 4 is not review-gated.

**Merge.**

- [ ] Root clean verdict at head SHA.
- [ ] Bugbot triage complete.
- [ ] Rebased onto main with patch-id unchanged.
- [ ] Operator appends to stack.

## Close the program

- [ ] Every box above is checked with its evidence.
- [ ] Disarm the 30-minute audit tick via the Antigravity `manage_task` tool (`Action: "kill"`, `TaskId: <tick-task-id>`).
- [ ] Reply to the operator with the report the execution playbook names.

## Appendix A. Prototype evidence

Prototype runs verified that Antigravity renders external shadow transcripts when JSONL files are placed under `<appDataDir>/brain/cloud-<session_id>-task-<index>/.system_generated/logs/transcript.jsonl`.
Prototype tests also confirmed that `anthropic[vertex]` successfully authenticates using ambient Google Cloud Application Default Credentials in Cloud Run.

## Appendix B. Alternatives rejected

1. Direct IDE plugin for Vertex Model Garden. Rejected because Antigravity's host binary defines `invoke_subagent` model enums and cannot be extended via plugin manifests.
2. Ingesting full worker thoughts into coordinator context. Rejected because 10 parallel workers emitting full tool traces would blow past context limits and consume hundreds of thousands of unnecessary tokens.
3. Requiring separate Anthropic API keys for cloud workers. Rejected because Vertex AI hosts Claude models natively with Google Cloud IAM billing, eliminating external key distribution.

## Appendix C. Risks

1. Vertex AI Anthropic regional quota limits. Mitigated by verifying Model Garden enablement during preflight in `setup_runtime.py`.
2. Cloud Logging poll latency delaying shadow transcript streaming. Mitigated by writing raw milestone updates directly to GCS streaming buffers alongside Cloud Logging.
3. Concurrent writes to shadow transcript files. Mitigated by partitioning directories strictly per task index (`task-0`, `task-1`).

## Appendix D. Links and reading list

- `skills/swarm/scripts/cloud_dispatch.py` (dispatcher execution loop).
- `skills/swarm/scripts/cloud_worker.py` (Cloud Run container worker).
- `skills/swarm/scripts/storage_messenger.py` (GCS mailbox routing).
- Google Cloud Vertex AI Model Garden documentation for Anthropic Claude.
