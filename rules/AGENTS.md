# agystack on Antigravity

This plugin is agystack. For any non-trivial engineering task (a bug, a feature, a refactor, an investigation, a PR, overnight or autonomous work), read and follow the `poteto-mode` skill before the first real step. Casual chat, a one-line answer, or an explicit opt-out skips it.

When an agystack skill names Cursor's `Task` tool, a `subagent_type`, a Cursor model slug, `AskQuestion`, or a `~/.cursor/` path, resolve it through `skills/poteto-mode/references/antigravity-tools.md` in this plugin. Do not call Cursor tools.

## Subagent Delegation Invariant

Use subagents deliberately where they provide genuine engineering leverage, and execute directly when work is local:

1. **Mandatory Subagent Fan-Out:** You MUST invoke distinct background subagents via `invoke_subagent` for:
   - **Code reviews and adversarial interrogation (`/interrogate`):** Dispatch concurrent reviewers across distinct model tiers (`pro`, `flash`, `inherit`). Simulating reviewer personas in the parent context is strictly forbidden.
   - **Multi-candidate design and code bakeoffs (`/arena`):** Dispatch parallel subagents in isolated workspaces or scratch paths.
   - **High-volume exploration sweeps and test matrices (`/swarm`):** Offload large payload reads to subagents to guard the main context window.
   - **Blinded behavioral evaluations (`/eval`):** Run candidate attempts through blinded subagents.
   - **Cross-model decision audits (`/show-me-your-work`):** Dispatch an independent subagent on a different model family to audit the decision log.
2. **Direct Local Execution:** For standard feature implementations, surgical bug fixes, refactoring, and single-turn commands, execute directly in the parent context without spawning subagents.

Per-role models live in `agystack-models.md` next to this file. `/setup-agystack` (or `/setup-pstack`) rewrites that file.
