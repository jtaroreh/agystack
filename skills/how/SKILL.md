---
name: how
description: "Use for \"how does X work\", code walkthroughs before changing something, and placement / ownership / layering questions (\"where should this live\", \"which package owns this\", \"is this the right layer\"). Explains subsystem architecture, runtime flow, onboarding mental models. Use why for motivation."
---

# How

Explore the codebase to explain architecture, subsystem mechanics, and runtime flow. Deliver clear mental models at the level of an onboarding senior engineer.

## Step 1. Understand the Question and Assess Complexity

Identify target scope from the request (subsystem, feature flow, architectural overview, or runtime trace). State your interpretation if ambiguous.

Classify complexity:
- **Simple** (single module, utility, or narrow function): Explainer explores and explains directly in one pass. Skip explorers; go to Step 2b.
- **Complex** (cross-cutting subsystem, multi-package flow, full architecture): Spawn parallel explorer agents first. Go to Step 2a.

## Step 2a. Explore (complex questions)

Decompose the subsystem into 2-4 distinct exploration slices (e.g. data model/state, request path/enforcement, configuration/metrics).

Spawn all explorers concurrently in a single `invoke_subagent` call:
- `TypeName`: `research`
- `Role`: `Subsystem Explorer (<slice>)`
- `Model`: configured how-explorer model (default `flash`)
- `Workspace`: `inherit`

Each explorer receives `references/explorer-prompt.md` and its assigned slice. Explorers trace call chains, data flow, types, and non-obvious behaviors, returning structured findings. Proceed to Step 3.

## Step 2b. Direct Explain (simple questions)

Spawn a single subagent via `invoke_subagent`:
- `TypeName`: `research`
- `Role`: `Architecture Explainer`
- `Model`: configured how-explainer model (default `pro`)
- `Workspace`: `inherit`

The agent explores code directly and writes the explanation per `references/explainer-prompt.md`. Proceed to Step 4.

## Step 3. Synthesize (complex questions)

Once all explorers return, spawn a synthesizer via `invoke_subagent`:
- `TypeName`: `self` (or `poteto-agent`)
- `Role`: `Architecture Synthesizer`
- `Model`: configured how-explainer model (default `pro`)
- `Workspace`: `inherit`

The synthesizer reconciles findings, resolves contradictions, and weaves slices into a unified explanation per `references/explainer-prompt.md`.

## Step 4. Present

For complex subsystems, write the full explanation to `<appDataDir>/brain/<conversation-id>/architecture_explanation.md` (or `<subsystem>_architecture.md`) with `ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: false }`. Present an executive summary in chat and link to the artifact. For simple questions, present directly in chat.

### Output Format

- **Overview.** Purpose, scope, and why it exists.
- **Key Concepts.** Core types, abstractions, and services.
- **How It Works.** Step-by-step runtime flow, data flow, decision branches, and file/symbol references.
- **Where Things Live.** Concise directory and file map.
- **Gotchas.** Edge cases, non-obvious constraints, and known hazards.
