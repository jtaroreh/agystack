# Antigravity tool, model, and path map

agystack was ported from pstack for Antigravity. On Antigravity, resolve every Cursor name in a skill through this table before acting. Do not invent Cursor tools.

## Tools

| Skill says | Do this on Antigravity |
| --- | --- |
| `Task` tool | `invoke_subagent` |
| `subagent_type: generalPurpose` | Built-in `self` (clone of the parent) |
| `subagent_type: "poteto-agent"` | Custom agent `poteto-agent` |
| `subagent_type: "Comment Sicko"` | Custom agent `comment-sicko` |
| `readonly: true` | Built-in `research` subagent, or `self` told not to write files |
| `readonly: false` | `self` or `poteto-agent` with the normal toolset |
| `run_in_background: true` | Default. Antigravity subagents already run concurrently |
| `environment: "cloud"` | `workspace: branch` (isolated git worktree) |
| `environment: "local"` | `workspace: inherit` |
| Parallel fan-out (several `Task` calls in one message) | Several `invoke_subagent` calls in one turn |
| `AskQuestion` | Ask in the reply with numbered options. No structured picker exists |
| Cursor `/loop` | Keep going in this session, or use Antigravity scheduled tasks (`/schedule`) |
| `/deslop` | Bundled natively in this plugin under `skills/deslop/SKILL.md` |
| `control-cli` (CLI/TUI proof) | `run_command` / `manage_task` or project-local verify skill (`/create-verification-skill`) |
| `control-ui` (Web/UI proof) | Native `browser_subagent` / Chrome DevTools MCP or project-local verify skill |
| `/create-skill` | Standard Antigravity skill structure (`skills/<name>/SKILL.md`) guided by `agy-customizations` |

Do not put a `tools:` allowlist on `poteto-agent` or `comment-sicko`. A misspelled tool name can hang the subagent.

## Models

Antigravity subagent `model` is a tier, not a Cursor slug: `flash`, `pro`, or `inherit`.

| Cursor default | Antigravity tier |
| --- | --- |
| `grok-4.6-fast-xhigh` (fast mechanical code) | `flash` |
| `gpt-5.6-sol-max` (precise instruction following) | `pro` |
| `claude-fable-5-thinking-max` (judgment and prose) | `pro` |
| `claude-opus-5-thinking-xhigh` (hardest tasks) | `pro` |
| `inherit-parent` or `auto` | `inherit` (omit model / inherit parent) |

Read per-role overrides from `~/.gemini/config/plugins/agystack/rules/agystack-models.md` (or `.agents/plugins/agystack/rules/agystack-models.md`). If a line is missing, use the table above.

Gemini is one family, so a four-model Cursor panel collapses. Keep panels diverse by tier: `pro`, `flash`, `inherit`. One subagent still runs per list entry. If `invoke_subagent` rejects a value, pick the closest available tier and continue. Do not block the task on the slug.

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
