# Antigravity tool, model, and path map

agystack was ported from pstack for Antigravity. On Antigravity, resolve every Cursor name in a skill through this table before acting. Do not invent Cursor tools.

## Tools

| Skill says | Do this on Antigravity |
| --- | --- |
| `Task` tool | `invoke_subagent` (or custom plugin agent / `start_subagent`) |
| `subagent_type: generalPurpose` | Built-in `self` (clone of the parent) |
| `subagent_type: "poteto-agent"` | Custom agent `poteto-agent` |
| `subagent_type: "Comment Sicko"` | Custom agent `comment-sicko` |
| `readonly: true` | Built-in `research` subagent, or `self` told not to write files |
| `readonly: false` | `self` or `poteto-agent` with the normal toolset |
| `run_in_background: true` | Default. Antigravity subagents and background commands run concurrently |
| `environment: "cloud"` / Worktree sandbox (`.cursor/worktrees/`) | `skills/poteto-mode/scripts/worktree-spawn.sh` (or `workspace: branch`) |
| `environment: "local"` | `workspace: inherit` |
| Parallel fan-out (several `Task` calls in one message) | Several subagent invocations in one turn |
| `AskQuestion` | `ask_question` tool or structured options via `skills/poteto-mode/references/decision-protocol.md` |
| Cursor `/loop` | Autonomous loop via `skills/loop/SKILL.md` (wrapping `schedule`) or `/goal` |
| Glob rules (`.cursor/rules/*.mdc`) | `rules/rule-manifest.json` via `skills/poteto-mode/scripts/route-rules.mjs` |
| Background tasks / processes | `run_command` (async) + `manage_task` (status/kill) with reactive wakeup |
| `/deslop` | Bundled natively in this plugin under `skills/deslop/SKILL.md` |
| `control-cli` (CLI/TUI proof) | `run_command` / `manage_task` or project-local verify skill (`/create-verification-skill`) |
| `control-ui` (Web/UI proof) | Native `browser_subagent` / Chrome DevTools MCP or project-local verify skill |
| `/create-skill` | Standard Antigravity skill structure (`skills/<name>/SKILL.md`) guided by `agy-customizations` |
| Scratch / temporary storage | `<appDataDir>/brain/<conversation-id>/scratch/` or workspace scratch dir (never `/tmp/`) |
| Plans / Design documents / RFCs | Antigravity Artifacts: `<appDataDir>/brain/<conversation-id>/implementation_plan.md` (or `<topic>_spec.md`) via `write_to_file` with `ArtifactMetadata` |
| Verification receipts / Walkthroughs | Antigravity Artifacts: `<appDataDir>/brain/<conversation-id>/walkthrough.md` |
| Extensive reports / Forensic dumps | Dedicated Artifacts: `<appDataDir>/brain/<conversation-id>/<name>_report.md` |
| Media embedding in artifacts | Copy media to `<appDataDir>/brain/<conversation-id>/` then embed with `![caption](/absolute/path)` |

Do not put a `tools:` allowlist on `poteto-agent` or `comment-sicko`. A misspelled tool name can hang the subagent.

## Antigravity Artifact System

Antigravity features a first-class visual Artifact system. Artifacts are markdown documents persisted in `<appDataDir>/brain/<conversation-id>/`. Use artifacts to deliver rich technical plans, deep investigation findings, benchmarks, visual comparisons, and verification receipts without bloating the chat context window.

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

## Models

Antigravity subagents use the official Gemini 3.7 Flash thinking tiers (with optional external review routing per `skills/poteto-mode/references/mcp-model-routing.md`):

- `gemini-3.7-flash-high` (High thinking: max reasoning for complex coding, architecture, and difficult bugs)
- `gemini-3.7-flash-medium` (Medium thinking: balanced reasoning for reviews and explanations)
- `gemini-3.7-flash-low` (Low thinking: fast with light reasoning checks)
- `gemini-3.7-flash-fast` (Fast / No thinking: zero-latency token generation for bulk scanning)
- `inherit` / `auto` (Inherits active model from parent chat session)

| Cursor default | Antigravity choice |
| --- | --- |
| `grok-4.6-fast-xhigh` (fast mechanical code) | `gemini-3.7-flash-fast` |
| `gpt-5.6-sol-max` (precise instruction following) | `gemini-3.7-flash-high` |
| `claude-fable-5-thinking-max` (judgment and prose) | `gemini-3.7-flash-high` |
| `claude-opus-5-thinking-xhigh` (hardest tasks) | `gemini-3.7-flash-high` |
| `inherit-parent` or `auto` | `inherit` (omit model / inherit parent) |

Read per-role overrides from `~/.gemini/config/plugins/agystack/rules/agystack-models.md` (or `.agents/plugins/agystack/rules/agystack-models.md`). If a line is missing, use the table above. For external model MCP routing, see `skills/poteto-mode/references/mcp-model-routing.md`.

Keep panels diverse across available options (`gemini-3.7-flash-high`, `gemini-3.7-flash-medium`, `inherit`). One subagent still runs per list entry. If `invoke_subagent` rejects a value, pick the closest available model and continue. Do not block the task on the slug.

## Paths

| Cursor path | Antigravity path |
| --- | --- |
| `~/.cursor/rules/pstack-models.mdc` | `~/.gemini/config/plugins/agystack/rules/agystack-models.md` |
| `~/.cursor/projects/<slug>/agent-transcripts/` | `~/.gemini/antigravity-ide/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` (IDE). Also `~/.gemini/antigravity/brain/` for Antigravity 2.0. The hook payload's `transcriptPath` is authoritative for the current session. |
| `.cursor/skills/` | `.agents/skills/` in the project, or this plugin's `skills/` |
| `~/.cursor/skills/` | `~/.gemini/config/skills/` or `~/.gemini/config/plugins/agystack/skills/` |

Never glob `~/.cursor/projects/*/`. That is Cursor chat history, not this product.

## Custom agents in this plugin

- `poteto-agent`: code-writing delegates inside a playbook. Reads poteto-mode first.
- `comment-sicko`: read-only comment review. Spawned by `/no-comments`.
