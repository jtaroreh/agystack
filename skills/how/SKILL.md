---
name: how
description: "Use for \"how does X work\", code walkthroughs before changing something, and placement / ownership / layering questions (\"where should this live\", \"which package owns this\", \"is this the right layer\"). Explains subsystem architecture, runtime flow, onboarding mental models. Use why for motivation."
---

# How

Explore the codebase to answer "how does X work?" questions and deliver a senior-engineer mental model.

If the scope is ambiguous, state your interpretation and explore. The user can redirect.

## 1. Classify complexity

- **Narrow** (single module, utility, or localized flow): spawn 1 `research` subagent via `invoke_subagent` (`Role: "Codebase Explorer"`, `Workspace: "inherit"`, `Model`: configured `how explorer` model, default `flash`) to trace and explain in one pass.
- **Cross-cutting** (multi-package flow, subsystem architecture, or ownership across layers): split into 2 to 4 distinct slices (data model/state, request path, configuration/boundaries) and spawn all `research` subagents concurrently in one turn (`Role: "Subsystem Explorer (<slice>)"`, `Workspace: "inherit"`, `Model`: configured `how explorer` model, default `flash`).

Each explorer has read-only access and returns traced call chains, data shapes, `file:line` citations, and non-obvious edge cases.

## 2. Synthesize and present

For cross-cutting questions, the coordinator reconciles the explorer findings directly, resolving contradictions and weaving slices into one coherent mental model without spawning a separate explainer subagent.

For narrow questions, present directly in chat. For cross-cutting subsystems, write the full explanation to `<appDataDir>/brain/<conversation-id>/architecture_explanation.md` (or `<subsystem>_architecture.md`) with `ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: false }`, then share an executive summary in chat with a link to the artifact.

Include:
- **Overview.** Purpose, scope, and why it exists.
- **Key concepts.** Core types, abstractions, and boundaries.
- **How it works.** Step-by-step runtime and data flow with `file:line` references.
- **Where things live.** Concise directory and file map.
- **Gotchas.** Edge cases, constraints, and hazards.
