# agystack on Antigravity

This plugin is agystack. For any non-trivial engineering task (a bug, a feature, a refactor, an investigation, a PR, overnight or autonomous work), read and follow the `poteto-mode` skill before the first real step. Casual chat, a one-line answer, or an explicit opt-out skips it.
 
## Subagent Delegation Invariant

Mirroring pstack in Cursor, enforce strict separation between coordination and code execution:

1. **Mandatory Subagent Delegation for Code Writes:** You MUST delegate all non-trivial code modifications, feature implementations, bug fixes, and refactoring to a subagent (`invoke_subagent` with `TypeName: "poteto-agent"` or configured role model) in an isolated context window. The parent agent operates as coordinator: planning, reviewing the subagent's diffs, running verification, and communicating with the user using unslopped prose. Pass purely technical specs, interfaces, and test criteria to the subagent so its context remains unburdened by conversational prose guidelines. A subagent already running as a delegate, or executing in an environment where subagent spawning is disallowed (such as `allow_subagents=False` in cloud workers or subagents without nesting tools), satisfies this invariant by executing and owning the diff directly.
   - **Non-Trivial Delegation Threshold:**
     - **Trivial edits (permitted directly by coordinator):** <= 3 lines, single flag or constant adjustments, `.gitignore` entries, markdown documentation, and scratch scripts in `scratch/`.
     - **Non-trivial edits (mandatory delegation to `poteto-agent`):** > 15 lines, new function/class definitions, multi-file code modifications, core business logic changes.
     - **User override:** Explicit user instructions for direct execution ("do this directly", "no subagents") allow coordinator writes.
2. **Mandatory Subagent Fan-Out:** You MUST invoke distinct background subagents via `invoke_subagent` for:
   - **Code reviews and adversarial interrogation (`/interrogate`):** Dispatch concurrent reviewers across distinct model tiers (`pro`, `flash`, `inherit`). Simulating reviewer personas in the parent context is strictly forbidden.
   - **Multi-candidate design and code bakeoffs (`/arena`):** Dispatch parallel subagents in isolated workspaces or scratch paths.
   - **High-volume exploration sweeps and test matrices (`/swarm`):** Offload large payload reads to subagents to guard the main context window.
   - **Blinded behavioral evaluations (`/eval`):** Run candidate attempts through blinded subagents.
   - **Cross-model decision audits (`/show-me-your-work`):** Dispatch an independent subagent on a different model family to audit the decision log.
3. **Candidate Integration Invariant:** Parallel candidate diffs from swarms, arenas, or subagent fan-outs must never be bulk-merged. The coordinator must evaluate candidate branches in isolation, rank them by delta, and graft winning modifications sequentially—verifying and benchmarking each change independently before attempting the next (`principle-sequence-verifiable-units`).
4. **Subagent Reactive Wakeup and Watchdog Timeout Invariant:** Antigravity subagents run asynchronously in isolated background sessions. They do NOT stream chat text to the coordinator and will ONLY wake the parent when they explicitly invoke `send_message`.
   - **Mechanical Turn Yielding:** Immediately after dispatching local subagents via `invoke_subagent`, the coordinator MUST yield the turn by outputting a progress message with ZERO tool calls (`tool_calls: []`).
   - **Continuous Busy-Wait Prohibited:** The coordinator must NEVER run rapid status polling loops (`manage_subagents(list)` every few seconds), must NEVER tail child `transcript.jsonl` files during the wait phase, and must NEVER attach status tool calls to turns intended to wait.
   - **Mandatory Global Watchdog Deadline:** To guard against hung workers, host crashes, or workers that go idle without messaging, the coordinator MUST arm a single unconditional global watchdog timer before yielding:
     `schedule(DurationSeconds: 300..600, Prompt="Watchdog: subagents timed out", TimerCondition: "never")`
     Because `TimerCondition: "never"` is used, incremental completions wake the coordinator reactively without cancelling the timer.
   - **Quorum & Teardown Protocol:** On incremental worker completions, record findings and yield immediately (zero tool calls) if workers remain pending. Once all workers arrive, cancel the active watchdog timer via `manage_task(Action: "kill", TaskId: <timer_task_id>)` before synthesizing.
   - **Timeout Diagnosis:** The coordinator calls `manage_subagents(Action: "list")` ONLY when the watchdog timer fires or an explicit failure occurs. If a worker is in `error` or `idle` without messaging, terminate it (`manage_subagents(Action: "kill", ConversationIds: [<id>])`) and proceed with partial results. Child transcripts may only be read for post-mortem diagnostics, never while waiting.
   - **Primitive Boundary:** Active heartbeat polling (every 60-120s) applies strictly to external CLI/Cloud Run subprocesses (`run_command`, `cloud_dispatch.py`), NEVER to local Antigravity subagents (`invoke_subagent`).
5. **Planning and Deliverable Artifact Scoping Matrix:**
   - **Interactive State-Changing Playbooks (`Feature`, `Refactoring`, `Multi-phase`):** Mandatory `implementation_plan.md` with `RequestFeedback: true` before coding; mandatory `walkthrough.md` with pass receipts upon completion.
   - **Autonomous & Hillclimb Playbooks (`Autonomous run`, `Hillclimb`, `Swarm`, `/goal`, `/loop`):** Unattended throughput invariant. Use `RequestFeedback: false`. Domain deliverables (`decision_trail.md`, `score.json`, `receipts/`) take precedence without interactive blocking.
   - **Read-Only Investigation Playbooks (`Investigation`, `How`, `Why`, `Runtime Forensics`):** Produces `investigation_report.md` with `RequestFeedback: false`.

## Cloud Swarm Invariants

Cloud Run swarms orchestrate massive parallel worker execution across container instances:

1. **Mandatory Pre-Flight Quota & Auth Check:** Cloud Run swarms must verify model availability and paid/unmetered quota tier before spinning up containers. Free-tier API keys (5 RPM) are prohibited. The dispatcher must verify that credentials can sustain the swarm workload without rate-limiting before incurring compute overhead.
2. **Model Endpoint Scoping:** Google hosts Gemini 3 series models (`gemini-3.8-flash`, `gemini-3.7-flash`, etc.) exclusively on the global Vertex AI endpoint (`aiplatform.googleapis.com` with `locations/global`). Regional endpoints return HTTP 404 for Gemini 3.x. Always route Gemini 3.x requests to `global` and supply the `X-Goog-User-Project` header.
3. **Patch-over-GCS Candidate Delivery & Ghost Commit Prohibition:** Cloud workers operate under a zero-push architecture and must never push to git remote branches directly. When execution yields a verified `PASS` with candidate source modifications outside bootstrap scaffolding, workers generate a `patch.diff` and upload run artifacts (`score.json`, `patch.diff`, `results.tsv`) directly to GCS under `swarms/<session_id>/task-<i>/`. The coordinator harvests patches from GCS, ranks candidate solutions by score delta, and applies the winning `patch.diff` locally. Cloud workers must never upload unverified infrastructure scaffolding or error-state changes as candidate patches.
4. **Active Liveness & Non-Blocking Monitoring (Cloud Run Swarms Only):** Applies strictly to external detached jobs (`cloud_dispatch.py --no-wait`) monitored via background CLI tasks. This NEVER applies to native local Antigravity subagents (`invoke_subagent`), which must follow the event-driven reactive wakeup invariant (zero polling). Swarm dispatchers must never block synchronously on buffered command execution (`subprocess.run` with `--wait` and `capture_output=True`). The parent coordinator must maintain an active heartbeat schedule (every 60-120s), polling Cloud Run execution conditions, streaming milestone logs, and checking git remotes. Never remain passive behind a monolithic background task.
5. **Straggler Independence & Early Candidate Harvesting:** Speculative candidate swarms must configure zero retries (`--max-retries=0`) so broken hypotheses fail fast. Coordinators monitor Cloud Run task completion and inspect storage manifests (`gs://<bucket>/swarms/<session_id>/task-*`). As soon as a candidate achieves a verified score win, the coordinator harvests the patch and advances it immediately rather than waiting for slow or hanging stragglers.

## Surface Precedence Hierarchy

Always use the most direct, deterministic tool surface for each task:

1. **Filesystem Tools (`view_file`, `grep_search`, `find_by_name`)**: Ground truth for code, configs, AST, tests, and repo docs. Never use a browser or UI tools to view, search, or scroll through code or repository files.
2. **CLI / Runtime Tools (`run_command`)**: Test suites, API endpoints, build/server logs, process lifecycles, and exit codes.
3. **Browser Tools (`browser_subagent` / Chrome DevTools MCP)**: Strictly for live UI interaction, DOM layout, CSS styles, user events, and rendered visual screenshots.

Per-role models live in `agystack-models.md` next to this file. `/setup-agystack` rewrites that file.
