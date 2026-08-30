# agystack on Antigravity

This plugin is agystack. For any non-trivial engineering task (a bug, a feature, a refactor, an investigation, a PR, overnight or autonomous work), read and follow the `poteto-mode` skill before the first real step. Casual chat, a one-line answer, or an explicit opt-out skips it.

When an agystack skill names Cursor's `Task` tool, a `subagent_type`, a Cursor model slug, `AskQuestion`, or a `~/.cursor/` path, resolve it through `skills/poteto-mode/references/antigravity-tools.md` in this plugin. Do not call Cursor tools.

## Subagent Delegation Invariant

Mirroring pstack in Cursor, enforce strict separation between coordination and code execution:

1. **Mandatory Subagent Delegation for Code Writes:** You MUST delegate all non-trivial code modifications, feature implementations, bug fixes, and refactoring to a subagent (`invoke_subagent` with `TypeName: "poteto-agent"` or configured role model) in an isolated context window. The parent agent operates as coordinator: planning, reviewing the subagent's diffs, running verification, and communicating with the user using unslopped prose. Pass purely technical specs, interfaces, and test criteria to the subagent so its context remains unburdened by conversational prose guidelines.
2. **Mandatory Subagent Fan-Out:** You MUST invoke distinct background subagents via `invoke_subagent` for:
   - **Code reviews and adversarial interrogation (`/interrogate`):** Dispatch concurrent reviewers across distinct model tiers (`pro`, `flash`, `inherit`). Simulating reviewer personas in the parent context is strictly forbidden.
   - **Multi-candidate design and code bakeoffs (`/arena`):** Dispatch parallel subagents in isolated workspaces or scratch paths.
   - **High-volume exploration sweeps and test matrices (`/swarm`):** Offload large payload reads to subagents to guard the main context window.
   - **Blinded behavioral evaluations (`/eval`):** Run candidate attempts through blinded subagents.
   - **Cross-model decision audits (`/show-me-your-work`):** Dispatch an independent subagent on a different model family to audit the decision log.

Per-role models live in `agystack-models.md` next to this file. `/setup-agystack` (or `/setup-pstack`) rewrites that file.
