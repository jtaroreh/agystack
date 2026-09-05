# agystack on Antigravity

This plugin is agystack. For any non-trivial engineering task (a bug, a feature, a refactor, an investigation, a PR, overnight or autonomous work), read and follow the `poteto-mode` skill before the first real step. Casual chat, a one-line answer, or an explicit opt-out skips it.
 
## Subagent Delegation Invariant

Mirroring pstack in Cursor, enforce strict separation between coordination and code execution:

1. **Mandatory Subagent Delegation for Code Writes:** You MUST delegate all non-trivial code modifications, feature implementations, bug fixes, and refactoring to a subagent (`invoke_subagent` with `TypeName: "poteto-agent"` or configured role model) in an isolated context window. The parent agent operates as coordinator: planning, reviewing the subagent's diffs, running verification, and communicating with the user using unslopped prose. Pass purely technical specs, interfaces, and test criteria to the subagent so its context remains unburdened by conversational prose guidelines. A subagent already running as a delegate, or executing in an environment where subagent spawning is disallowed (such as `allow_subagents=False` in cloud workers or subagents without nesting tools), satisfies this invariant by executing and owning the diff directly.
2. **Mandatory Subagent Fan-Out:** You MUST invoke distinct background subagents via `invoke_subagent` for:
   - **Code reviews and adversarial interrogation (`/interrogate`):** Dispatch concurrent reviewers across distinct model tiers (`pro`, `flash`, `inherit`). Simulating reviewer personas in the parent context is strictly forbidden.
   - **Multi-candidate design and code bakeoffs (`/arena`):** Dispatch parallel subagents in isolated workspaces or scratch paths.
   - **High-volume exploration sweeps and test matrices (`/swarm`):** Offload large payload reads to subagents to guard the main context window.
   - **Blinded behavioral evaluations (`/eval`):** Run candidate attempts through blinded subagents.
   - **Cross-model decision audits (`/show-me-your-work`):** Dispatch an independent subagent on a different model family to audit the decision log.

## Cloud Swarm Invariants

Cloud Run swarms orchestrate massive parallel worker execution across container instances:

1. **Mandatory Pre-Flight Quota & Auth Check:** Cloud Run swarms must verify model availability and paid/unmetered quota tier before spinning up containers. Free-tier API keys (5 RPM) are prohibited. The dispatcher must verify that credentials can sustain the swarm workload without rate-limiting before incurring compute overhead.
2. **Model Endpoint Scoping:** Google hosts Gemini 3 series models (`gemini-3.8-flash`, `gemini-3.7-flash`, etc.) exclusively on the global Vertex AI endpoint (`aiplatform.googleapis.com` with `locations/global`). Regional endpoints return HTTP 404 for Gemini 3.x. Always route Gemini 3.x requests to `global` and supply the `X-Goog-User-Project` header.
3. **Branch Purity & Ghost Commit Prohibition:** Cloud workers must never push unverified infrastructure scaffolding or error-state changes as candidate commits. Changes may only be committed and pushed to worker branches when execution yields a verified `PASS` and modifies legitimate candidate source files outside bootstrap scaffolding. Revert harness modifications before diff evaluation.
4. **Active Liveness & Non-Blocking Monitoring:** Swarm dispatchers must never block synchronously on buffered command execution (`subprocess.run` with `--wait` and `capture_output=True`). The parent coordinator must maintain an active heartbeat schedule (every 60-120s), polling Cloud Run execution conditions, streaming milestone logs, and checking git remotes. Never remain passive behind a monolithic background task.
5. **Straggler Independence & Early Candidate Harvesting:** Speculative candidate swarms must configure zero retries (`--max-retries=0`) so broken hypotheses fail fast. Coordinators must periodically poll remote worker branches (`git ls-remote origin "worker-*"`) and storage manifests (`gs://<bucket>/task-*`). As soon as a candidate achieves a verified score win, the coordinator should harvest and advance it immediately rather than waiting for slow or hanging stragglers.

## Surface Precedence Hierarchy

Always use the most direct, deterministic tool surface for each task:

1. **Filesystem Tools (`view_file`, `grep_search`, `find_by_name`)**: Ground truth for code, configs, AST, tests, and repo docs. Never use a browser or UI tools to view, search, or scroll through code or repository files.
2. **CLI / Runtime Tools (`run_command`)**: Test suites, API endpoints, build/server logs, process lifecycles, and exit codes.
3. **Browser Tools (`browser_subagent` / Chrome DevTools MCP)**: Strictly for live UI interaction, DOM layout, CSS styles, user events, and rendered visual screenshots.

Per-role models live in `agystack-models.md` next to this file. `/setup-agystack` (or `/setup-pstack`) rewrites that file.
