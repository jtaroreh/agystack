---
name: setup-agystack
description: Configure Antigravity model tiers per role for agystack and run local environment doctor checks.
---

# Setup agystack

Configure model tiers in `~/.gemini/config/plugins/agystack/agystack-models.md` (or workspace `.agents/plugins/agystack/agystack-models.md`).

## Prerequisites

- `bun` (v1.0+) is mandatory for PR babysitting (`watch-pr`) and TypeScript script tests (Node.js is used for `check-plan.mjs`).
- `gh` (GitHub CLI) is required for PR automation and preflight checks.
- `gt` (Graphite CLI) is recommended for stacked PRs.

During setup, verify dependencies and platform health automatically via `--doctor`:

```bash
python3 "$(find ~/.gemini/config/plugins/agystack .agents/plugins/agystack skills/setup-agystack -name "setup_runtime.py" 2>/dev/null | head -1)" --doctor
```

## Steps

### 1. Detect available models

Enumerate the Antigravity model tiers you can pass to `invoke_subagent`:

- `pro`: High-capability tier (maximum reasoning budget for complex code, architecture, and hard tasks)
- `flash`: Balanced fast tier (fast execution for exploration and standard generation)
- `flash_lite`: Lightweight tier (minimal latency for quick lookups)
- `inherit` (or `auto`): Inherit parent chat model

### 2. Load current state

If `~/.gemini/config/plugins/agystack/agystack-models.md` exists (or `.agents/plugins/agystack/agystack-models.md` for a workspace-local install), read its current role assignments. Otherwise start from skill defaults. If upgrading from an older install, remove any obsolete `swarm workers` line when rewriting `agystack-models.md`.

### 3. Map and confirm

Show every role with its model tier and confirm:
- Single roles: `feature, refactoring`, `bug-fix`, `perf-issue`, `hillclimb`, `judgment and prose`, `hardest tasks`
- Workflow roles: `how explorer`, `how explainer`, `why investigators`, `why synthesizer`, `reflect tooling`, `reflect judgment, divergent, synthesizer`
- Panel roles: `arena runners`, `arena cross-judge pool`, `architect runners`, `interrogate reviewers`

### 4. Write the model rule

Write to `.agents/plugins/agystack/agystack-models.md` if installed workspace-locally, otherwise `~/.gemini/config/plugins/agystack/agystack-models.md`:

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
why investigators: flash
why synthesizer: pro
reflect tooling: pro
reflect judgment, divergent, synthesizer: pro
arena runners: pro, flash, inherit
arena cross-judge pool: pro, flash, inherit
architect runners: pro, flash, inherit
interrogate reviewers: pro, flash, inherit
```

### 5. Confirm

Confirm that the model rule is active for new sessions and `--doctor` reports `"status": "OK"`.

### 6. Offer a verification skill (optional)

If the project lacks an end-to-end verification harness, offer `/create-verification-skill`.
