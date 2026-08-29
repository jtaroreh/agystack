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
| `environment: "cloud"` | `workspace: branch` (isolated git worktree) |
| `environment: "local"` | `workspace: inherit` |
| Parallel fan-out (several `Task` calls in one message) | Several subagent invocations in one turn |
| `AskQuestion` | `ask_question` tool (native interactive modal with options) or numbered options in reply |
| Cursor `/loop` | Antigravity scheduled tasks (`schedule` tool / `/schedule`) or `/goal` |
| Background tasks / processes | `run_command` (async) + `manage_task` (status/kill) with reactive wakeup |
| `/deslop` | Bundled natively in this plugin under `skills/deslop/SKILL.md` |
| `control-cli` (CLI/TUI proof) | `run_command` / `manage_task` or project-local verify skill (`/create-verification-skill`) |
| `control-ui` (Web/UI proof) | Native `browser_subagent` / Chrome DevTools MCP or project-local verify skill |
| `/create-skill` | Standard Antigravity skill structure (`skills/<name>/SKILL.md`) guided by `agy-customizations` |
| Scratch / temporary storage | `<appDataDir>/brain/<conversation-id>/scratch/` or workspace scratch dir (never `/tmp/`) |

Do not put a `tools:` allowlist on `poteto-agent` or `comment-sicko`. A misspelled tool name can hang the subagent.

## Models

Antigravity subagents use the official Gemini 3.7 Flash thinking tiers:

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

Read per-role overrides from `~/.gemini/config/plugins/agystack/rules/agystack-models.md` (or `.agents/plugins/agystack/rules/agystack-models.md`). If a line is missing, use the table above.

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
