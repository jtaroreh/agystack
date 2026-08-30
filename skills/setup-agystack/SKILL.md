---
name: setup-agystack
description: Configure which models agystack uses per role. Detects your available Antigravity model tiers and writes an always-applied rule that overrides the skill defaults. Use for /setup-agystack, /setup-pstack, "configure agystack models", or changing agystack's model choices.
---

# Setup agystack

Write `~/.gemini/config/plugins/agystack/rules/agystack-models.md` (or workspace `.agents/plugins/agystack/rules/agystack-models.md`), an always-applied rule that sets agystack's model per role. The skills read it and fall back to their inline defaults (mapped through `skills/poteto-mode/references/antigravity-tools.md`) when a line is absent, so this is an override layer, not a requirement.

On Antigravity, subagent values use official model tiers (`pro`, `flash`, `flash_lite`) or `inherit` (parent session model). Legacy Cursor slugs (e.g. `grok-4.6-fast-xhigh`, `claude-fable-5-thinking-max`) and outdated model tiers are invalid.

## Steps

### 1. Detect available models

Enumerate the model tiers you can pass to `invoke_subagent` in this session. The official options are:
- `pro`: High-capability tier (maximum reasoning budget for complex code, architecture, and hard tasks)
- `flash`: Balanced fast tier (fast execution for exploration and standard generation)
- `flash_lite`: Lightweight tier (minimal latency for quick lookups)
- `inherit` (or `auto`): Inherit parent chat model

Never write a real slug you have not confirmed is available.

### 2. Load current state

The default role-to-model mapping is the rule shape shown in step 5 below. If `~/.gemini/config/plugins/agystack/rules/agystack-models.md` already exists, read it and treat its values as the current choices. Otherwise start from those defaults.

### 3. Map and confirm

Show every role with its current model, marking any unknown or outdated slug not in the detected set as needing a choice. Ask whether to accept as-is or change specific roles, offering the official tiers (`pro`, `flash`, `flash_lite`, `inherit`, `auto`) as choices. Ask with numbered options in the reply. For panel roles (how critics, arena runners, architect runners, interrogate reviewers) the value is a list, and one subagent runs per entry, alias entries included, so the list length sets the count. `arena cross-judge pool` is also a list, but Arena selects one value from it whose tier differs from the parent's when possible. `swarm workers` is the default model for every worker unless a race or comparison assigns another model per arm.

Keep panels diverse across available tiers (`pro`, `flash`, `inherit`) rather than repeating the exact same model four times.

### 4. Validate

Every real slug written must be in the detected set; `inherit`, `inherit-parent`, and `auto` always pass. If a chosen model is not available, stop and ask again. A rule pointing at an invalid or outdated model breaks every delegation that reads it.

### 5. Write the rule

Write `~/.gemini/config/plugins/agystack/rules/agystack-models.md` with one line per role, using the same labels poteto-mode uses. Overwrite the whole file so re-runs stay idempotent. Shape:

```
# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
# Antigravity model tiers for invoke_subagent:
# - pro        (High-capability tier: deep reasoning, large refactors, complex design)
# - flash      (Balanced fast tier: exploration, reading, standard code generation)
# - flash_lite (Lightweight tier: fast mechanical lookups)
# - inherit    (Runs on the active parent chat session model)

feature, refactoring: pro
bug-fix: pro
perf-issue: pro
hillclimb: pro
judgment and prose: pro
hardest tasks: pro
how explorer: flash
how explainer: pro
how critics: pro, flash, inherit
why investigators: flash
why synthesizer: pro
reflect tooling: pro
reflect judgment, divergent, synthesizer: pro
arena runners: pro, flash, inherit
arena cross-judge pool: pro, flash, inherit
swarm workers: flash
architect runners: pro, flash, inherit
interrogate reviewers: pro, flash, inherit
```

### 6. Confirm

Tell the user the rule was written and that it applies to new sessions. Re-running this skill updates it.

### 7. Offer a verification skill (optional)

Check whether the project has a way to drive the real app for proof (a `verify-*` skill, or an existing harness). If not, offer once: "want a project-local verification skill, so agents can drive the app the way a user does and prove changes work? I can generate one with /create-verification-skill." On yes, invoke `/create-verification-skill`. On no, move on without pushing.
