# Antigravity tool, model, and path map

agystack is built natively for Google Antigravity. Use standard Antigravity primitives for all agent actions.

## Tools

| Cursor / pstack legacy | Antigravity Native Tool & Argument |
| --- | --- |
| `Task` tool | `invoke_subagent` with `Subagents: [{ TypeName, Role, Prompt, Model, Workspace }]` |
| `subagent_type: generalPurpose` | `TypeName: "self"` (clone of parent context and capabilities) |
| `subagent_type: "poteto-agent"` | `TypeName: "poteto-agent"` |
| `subagent_type: "Comment Sicko"` | `TypeName: "comment-sicko"` |
| `readonly: true` exploration | `TypeName: "research"` (read-only search, view, grep, and web tools) |
| `readonly: false` general work | `TypeName: "self"` or `TypeName: "poteto-agent"` |
| `run_in_background: true` | Default. Antigravity subagents and background commands run concurrently |
| Worktree sandbox (`.cursor/worktrees/`) | `Workspace: "branch"` (isolated git branch/worktree) or `Workspace: "share"` |
| `environment: "local"` | `Workspace: "inherit"` (default parent workspace) |
| Parallel fan-out | Single `invoke_subagent` call with multiple entries in `Subagents` array |
| `AskQuestion` | `ask_question` tool for interactive questions |
| Background Wake / Scheduling | `schedule` tool (one-shot timer `DurationSeconds` or recurring `CronExpression`) |
| Autonomous Run / Predicate | `/goal` slash command or `Autonomous run` playbook |
| Program Orchestration | Orchestrate playbook (`playbooks/orchestrate.md`) with `orch` CLI |
| Iterative Metric Optimization | `/loop <goal> --verify "<command>"` via `skills/loop/SKILL.md` |
| Background processes | `run_command` (async) + `manage_task` (status/kill/input) with reactive wakeup |
| `/deslop` | Bundled natively in this plugin under `skills/deslop/SKILL.md` |
| Automated test suites | `run_command` (`bun test`, `cargo test`, `pytest`, `vitest`, `go test`) |
| `control-cli` (CLI/TUI proof) | `run_command` (async background) + `manage_task` (`send_input`, `status`, `kill`) or project-local verify skill (`/create-verification-skill`) |
| `control-ui` (Web/UI proof) | Chrome DevTools MCP (`browser_subagent`) and `read_url_content` (or project-local verify skill) |
| Visual parity / UI diffs | `generate_image` / visual diffs / artifact carousels (`<!-- slide -->`) |
| Performance traces / Benchmarks | Profiling capture (`cpuprofile`, `trace`, heap snapshot) via `run_command` + dedicated `perf_report.md` artifact |
| Scratch / temporary storage | `<appDataDir>/brain/<conversation-id>/scratch/` or workspace scratch dir (never `/tmp/`) |
| Plans / Design documents / RFCs | Antigravity Artifacts: `<appDataDir>/brain/<conversation-id>/implementation_plan.md` via `write_to_file` with `ArtifactMetadata` |
| Verification receipts / Walkthroughs | Antigravity Artifacts: `<appDataDir>/brain/<conversation-id>/walkthrough.md` |
| Extensive reports / Forensic dumps | Dedicated Artifacts: `<appDataDir>/brain/<conversation-id>/<name>_report.md` |
| Media embedding in artifacts | Copy media to `<appDataDir>/brain/<conversation-id>/` then embed with `![caption](/absolute/path)` |

Do not put a `tools:` allowlist on `poteto-agent` or `comment-sicko`.

## Antigravity Artifact System

Antigravity has a native visual artifact system. Artifacts are markdown or HTML documents persisted in `<appDataDir>/brain/<conversation-id>/`. The `<appDataDir>` token is injected into system context by Antigravity (e.g. `~/.gemini/antigravity` or `/Users/<user>/.gemini/antigravity`). Use artifacts to deliver rich technical plans, deep investigation findings, benchmarks, visual comparisons, and verification receipts without bloating the chat context window.

Pass `ArtifactMetadata` as an argument to the `write_to_file` tool call when creating or updating artifacts:
`ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: true|false }`

### Standard Artifact Types

1. **Implementation Plan (`implementation_plan.md`)**:
   - Path: `<appDataDir>/brain/<conversation-id>/implementation_plan.md`
   - Purpose: Detailed design document, component changes (`[MODIFY]`, `[NEW]`, `[DELETE]`), user review items, and verification plan.
   - Metadata: `ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: true }` when awaiting user approval.
2. **Walkthrough (`walkthrough.md`)**:
   - Path: `<appDataDir>/brain/<conversation-id>/walkthrough.md`
   - Purpose: End-of-task verification proof, changes completed, tests executed, and visual receipts.
3. **Domain Reports & Deliverables**:
   - Investigation reports: `investigation_report.md` or `<subsystem>_investigation.md`
   - Architecture specs & ADRs: `architecture_design.md` or `design_sketch.md`
   - Performance & benchmarks: `perf_report.md` or `hillclimb_report.md`
   - Runtime & trace forensics: `forensics_report.md`
   - Decision trail: `decisions.tsv` paired with a human-readable `decision_trail.md`
   - Multi-phase plans: `multi_phase_plan.md`

### Rich Formatting Capabilities

- **GitHub Alerts**: Use `> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`, and `> [!CAUTION]`.
- **Mermaid Diagrams**: Fenced code blocks with `mermaid` language tag for state machines, architectures, and flows.
- **Carousels**: Four backticks with `carousel` language identifier and `<!-- slide -->` separators for side-by-side or sequential comparisons.
- **File Links**: Always use clickable GitHub markdown links with `file://` scheme and basenames (e.g. `[server.ts](file:///path/to/server.ts#L10-L25)`).
- **Media Embedding**: Copy any screenshot, trace plot, or video into `<appDataDir>/brain/<conversation-id>/` first, then embed using `![caption](/absolute/path/to/media.png)`.
- **LaTeX Math**: Use KaTeX syntax (`\$` for literal dollars, `\(...\)` for inline math, `\[...\]` for display math).

### Chat Pointer Discipline

When creating or updating an artifact:
- **Do NOT dump the full artifact contents in the chat message.**
- Point to the artifact using a markdown link with its basename (`[implementation_plan.md](file:///path)`).
- Provide a crisp, unslopped summary of key decisions, trade-offs, or open questions requiring human input.

## Verification Harness Matrix

Every playbook completion requires concrete proof on the real target surface before declaring done. Never rely on simulated output or self-report.

| Test Surface | Antigravity Tooling & Primitives | Artifact & Evidence Receipt | Key Invariants |
| --- | --- | --- | --- |
| **Automated test suites** | `run_command` (`bun test`, `cargo test`, `pytest`, `vitest`, `go test`) | Embed stdout/stderr exit codes and test run stats in `walkthrough.md` | Run real test runner commands against workspace code; do not mock or skip tests. |
| **CLI / TUI interactive** | `run_command` (async background) + `manage_task` (`send_input`, `status`, `kill`) | Capture interactive terminal logs and exit codes in `walkthrough.md` | Verify interactive prompts, ANSI escapes, signals, and exit statuses end-to-end. |
| **Web UI / Browser** | Chrome DevTools MCP (`browser_subagent`) and `read_url_content` / HTTP checks | Save DOM snapshots, console logs, and screenshots into `<appDataDir>/brain/<conversation-id>/` | Probe live server over CDP or HTTP; confirm layout, navigation, and console error absence. |
| **Visual parity** | `generate_image` / visual diffs / screenshot captures | Carousel slides (`carousel` code blocks with `<!-- slide -->`) in `walkthrough.md` | Side-by-side before/after comparison with 0 pixel drift or deliberate design delta. |
| **Performance traces** | Profiling capture (`cpuprofile`, `trace`, `spindump`, heap snapshot) via `run_command` | Dedicated `perf_report.md` artifact with flamegraph/metric delta tables | Measure against baseline; log before/after timing and resource deltas. |
| **Verification receipts** | `write_to_file` with `ArtifactMetadata` | `walkthrough.md` artifact at `<appDataDir>/brain/<conversation-id>/walkthrough.md` | Required for all completed multi-step work before handoff. |

## Models

Antigravity subagents use native `invoke_subagent` model tiers:

- `inherit` (Inherits the active parent model, running your current session choice such as Gemini 3.7 Flash High)
- `pro` (High-capability tier)
- `flash` (Balanced fast tier: fast exploration, standard implementation, and reviews)
- `flash_lite` (Lightweight tier: fast mechanical scans and lookups)

| Role / Intent | Antigravity Model Tier |
| --- | --- |
| Primary reasoning / difficult tasks | `inherit` (runs on your active chat model, e.g. Gemini 3.7 Flash High) |
| Fast mechanical scanning / exploration | `flash` or `flash_lite` |
| Deep judgment, prose, architecture | `inherit` or `pro` |
| Multi-model review panels | Diverse combination across `inherit`, `flash`, and `pro` |

Read per-role overrides from `~/.gemini/config/plugins/agystack/rules/agystack-models.md` (or `.agents/plugins/agystack/rules/agystack-models.md`). If a line is missing, use the defaults above.

Keep panels diverse across available tiers (`inherit`, `flash`, `pro`). One subagent runs per list entry.

## Paths

| Artifact / Config | Antigravity Path |
| --- | --- |
| Role models configuration | `~/.gemini/config/plugins/agystack/rules/agystack-models.md` |
| Agent conversation transcripts | `<appDataDir>/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` (or `~/.gemini/antigravity/brain/` / `~/.gemini/antigravity-ide/brain/`) |
| Session artifacts | `<appDataDir>/brain/<conversation-id>/` |
| Project-local skills | `.agents/skills/` in the project, or this plugin's `skills/` |
| User global skills | `~/.gemini/config/skills/` or `~/.gemini/config/plugins/agystack/skills/` |

## Custom agents in this plugin

- `poteto-agent`: code-writing delegates inside a playbook. Reads poteto-mode first.
- `comment-sicko`: read-only comment review. Spawned by `/no-comments`.

## Subagent Execution Policy

Mirroring pstack in Cursor, agystack enforces strict separation between coordinator planning and subagent code execution:

1. **Mandatory Subagent Delegation for Code Writes:** You MUST delegate all non-trivial code modifications, feature implementations, bug fixes, and refactoring to a subagent (`invoke_subagent` with `TypeName: "poteto-agent"` or configured role model) in an isolated context window. The parent agent operates as coordinator: planning, reviewing the subagent's diffs, running verification, and communicating with the user using unslopped prose. Pass purely technical specs, interfaces, and test criteria to the subagent so its context remains unburdened by conversational prose guidelines.
2. **Mandatory Subagent Fan-Out:** You MUST call `invoke_subagent` for:
   - **Adversarial Code Review (`/interrogate`):** Dispatch concurrent reviewers across distinct model tiers (`pro`, `flash`, `inherit`). In-context persona emulation is strictly prohibited.
   - **Design & Candidate Bakeoffs (`/arena`):** Dispatch parallel subagents in isolated workspaces or scratch paths.
   - **Large Payload Sweeps (`/swarm`):** Offload wide search matrices or multi-slice tests to subagents to guard the main context window.
   - **Blinded Behavioral Evals (`/eval`):** Run candidate tasks blindly through isolated subagents.
   - **Cross-Model Trail Audits (`/show-me-your-work`):** Dispatch an independent subagent on a different model tier before closing.

