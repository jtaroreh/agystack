---
name: setup-pstack
description: Configure which models pstack uses per role. Detects your available Antigravity model tiers and writes an always-applied rule that overrides the skill defaults. Use for /setup-pstack, "configure pstack models", or changing pstack's model choices.
---

# Setup pstack

Write `~/.gemini/config/plugins/pstack/rules/pstack-models.md`, an always-applied rule that sets pstack's model per role. The skills read it and fall back to their inline defaults (mapped through `skills/poteto-mode/references/antigravity-tools.md`) when a line is absent, so this is an override layer, not a requirement.

On Antigravity, values are subagent tiers: `flash`, `pro`, and `inherit`. Cursor slugs such as `grok-4.6-fast-xhigh` are invalid here.

## Steps

### 1. Detect available models

Enumerate the model tiers you can pass to `invoke_subagent` in this session. Antigravity's documented tiers are `flash`, `pro`, and `inherit`. If the session also exposes named Gemini slugs (for example Gemini Flash, Gemini Pro, Gemini Next), record those too and map each to the closest tier. Never write a real slug you have not confirmed is available. The aliases `inherit`, `inherit-parent`, and `auto` are always valid and all mean: this role runs on the parent chat model.

### 2. Load current state

The default role-to-model mapping is the rule shape shown in step 5 below. If `~/.gemini/config/plugins/pstack/rules/pstack-models.md` already exists, read it and treat its values as the current choices. Otherwise start from those defaults.

### 3. Map and confirm

Show every role with its current model, marking any real slug not in the detected set as needing a choice. Ask whether to accept as-is or change specific roles, offering the detected tiers plus `inherit` and `auto` as the options. Ask with numbered options in the reply. For panel roles (how critics, arena runners, architect runners, interrogate reviewers) the value is a list, and one subagent runs per entry, alias entries included, so the list length sets the count. `arena cross-judge pool` is also a list, but Arena selects one value from it whose tier differs from the parent's when possible. `swarm workers` is the default model for every worker unless a race or comparison assigns another model per arm.

Gemini is one family. Keep panels diverse by tier (`pro`, `flash`, `inherit`) rather than repeating the same tier four times.

### 4. Validate

Every real slug written must be in the detected set; `inherit`, `inherit-parent`, and `auto` always pass. If a chosen real slug is not available, stop and ask again. A rule pointing at a model the user cannot use breaks every delegation that reads it.

### 5. Write the rule

Write `~/.gemini/config/plugins/pstack/rules/pstack-models.md` with one line per role, using the same labels poteto-mode uses. Overwrite the whole file so re-runs stay idempotent. Shape:

```
# pstack model configuration. One line per role. Delete a line to fall back to the skill default.
# Values are Antigravity subagent tiers: flash, pro, inherit.
# `inherit` or `auto` as a value: the role runs on the parent chat model.
# Alias entries in a panel list still count toward its fan-out.
feature, refactoring: flash
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
