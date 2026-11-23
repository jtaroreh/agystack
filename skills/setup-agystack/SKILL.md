---
name: setup-agystack
description: Configure models and execution runtime for agystack. Configures Antigravity model tiers per role and Cloud Run runtime settings for up to 100+ parallel workers.
---

# Setup agystack

Configure model tiers in `~/.gemini/config/plugins/agystack/agystack-models.md` and execution runtime in `~/.gemini/config/plugins/agystack/agystack-runtime.json` (or workspace `.agents/plugins/agystack/`).

## Prerequisites

- `bun` (v1.0+) is mandatory for PR babysitting (`watch-pr`) and multi-agent orchestration (`orch`). Node.js is not supported.
- `gh` (GitHub CLI) is required for PR automation and preflight checks.
- `gt` (Graphite CLI) is recommended for stacked PRs.
- `google-cloud-storage`, `google-genai`, and `google-cloud-run` are optional Python libraries for GCS artifact storage, preflight checks, and Cloud Run job monitoring.

During setup, verify dependencies automatically via `--doctor`:

```bash
python3 "$(find ~/.gemini/config/plugins/agystack .agents/plugins/agystack skills/setup-agystack -name "setup_runtime.py" 2>/dev/null | head -1)" --doctor
```

## Steps

### 1. Select execution runtime

Choose the execution runtime for parallel swarms:
- **Local Runtime (Default):** Runs via native `invoke_subagent` in Antigravity for up to 8 concurrent workers. Zero cloud setup required.
- **Cloud Run Runtime:** Runs via Google Cloud Run Jobs for 10 to 100+ parallel workers in isolated container instances. Cloud Run is strictly an on-demand batch runner. It only spins up containers when you explicitly trigger `/cloud-swarm` (or ask to swarm a task across many parallel workers). It does not run continuously and is never an always-on server. It costs $0 when idle. Daily tasks (pair programming, routine edits, bug fixes, refactoring, code reviews via `/interrogate`, and local subagents) always run locally on your machine.

**CRITICAL INSTRUCTION FOR AI AGENT WHEN PRESENTING RUNTIME CHOICE:**
When presenting the runtime choice to the user, explicitly explain the cost and execution model before asking them to choose:
1. Explain that Cloud Run is strictly an on-demand batch runner. It only spins up containers when the user explicitly triggers `/cloud-swarm` (or asks to swarm a task across many parallel workers).
2. Clarify that Cloud Run does NOT run continuously and is never an always-on server.
3. State that Cloud Run costs $0 when idle.
4. Reassure the user that daily tasks (pair programming, routine edits, bug fixes, refactoring, code reviews via `/interrogate`, and local subagents) ALWAYS run locally on their machine.

If Cloud Run is selected:
**CRITICAL INSTRUCTION FOR AI AGENT FOR PROVISIONING:** NEVER print manual bash commands with placeholders (like `<your-gcp-project-id>`) for the user to run. You MUST directly execute the setup commands yourself using `python3 "$(find ~/.gemini/config/plugins/agystack .agents/plugins/agystack skills/setup-agystack -name "setup_runtime.py" 2>/dev/null | head -1)"` right here in the chat environment.

1. **Verify Quotas and Permissions:**
   - **Google AI Studio API Key:** If using `GEMINI_API_KEY`, verify that paid billing (Pay-as-you-go / Tier 1+) is enabled on the AI Studio project. Free-tier API keys (capped at 5 requests per minute) are strictly prohibited for swarms because parallel workers will hit immediate rate limits.
   - **Vertex AI Mode:** If using Vertex AI mode, verify that the GCP project has the Vertex AI API enabled (`aiplatform.googleapis.com`) and that the active user or service account has the Vertex AI User role (`roles/aiplatform.user`).
   - **Model Availability:** Gemini 3 series models (`gemini-3.8-flash`) require global routing (`aiplatform.googleapis.com` with `locations/global`). Regional endpoints return HTTP 404 for Gemini 3.x.
2. **Check Requirements**: Run `python3 skills/setup-agystack/scripts/setup_runtime.py --check` to verify `gcloud` is available and authenticated.
3. **Select Project**:
   - Query available projects by running `python3 skills/setup-agystack/scripts/setup_runtime.py --list-projects`.
   - Ask the user which project they want to use, or if they want you to create a new one.
4. **Provisioning**: Once a project ID is known, run the full provisioner (do this yourself, do not ask the user to do it!):
   `python3 skills/setup-agystack/scripts/setup_runtime.py --project <PROJECT_ID> --auto-provision --scripts-dir skills/cloud-swarm/scripts`
   (or use `--create-project <PROJECT_ID>` instead of `--project` if creating a new one).

Do not leave the user to do the work. Complete the deployment end-to-end for them. Ensure `GEMINI_API_KEY` is exported in the user's environment with paid tier enabled (Pay-as-you-go), or Vertex AI permissions and global endpoint access are verified.

### 2. Detect available models

Enumerate the model tiers you can pass to `invoke_subagent` (local), `cloud_dispatch.py` (Cloud Run), and native `swarm`:

**Local subagent tiers (`invoke_subagent`):**
- `pro`: High-capability tier (maximum reasoning budget for complex code, architecture, and hard tasks; target for `gemini-4-neon-*`)
- `flash`: Balanced fast tier (fast execution for exploration and standard generation; target for `gemini-4-hydrogen-*` and `gemini-3.8-flash-*`)
- `flash_lite`: Lightweight tier (minimal latency for quick lookups)
- `inherit` (or `auto`): Inherit parent chat model (target for `gemini-4-argon-*` and universal parent inheritance)

**Gemini 4 Effort-Balanced Identifiers (Cross-Surface Compatible):**
- `gemini-4-neon-{low,medium,high,xhigh}`: Frontier reasoning & coding (translates to `pro` on `invoke_subagent`, `gemini-4-neon` on `/cloud-swarm`, exact ID on native `swarm`)
- `gemini-4-argon-{low,medium,high}`: Deep reasoning & systems engineering (translates to `inherit` on `invoke_subagent`, `gemini-4-argon` on `/cloud-swarm`, exact ID on native `swarm`)
- `gemini-4-hydrogen-{low,medium,high,xhigh}`: High-speed execution & verification (translates to `flash` on `invoke_subagent`, `gemini-4-hydrogen` on `/cloud-swarm`, exact ID on native `swarm`)

**Cloud Run swarm model tiers (`cloud_dispatch.py`):**
- **Tier 1 (Zero-Friction MaaS):** `gemini-4-neon`, `gemini-4-argon`, `gemini-4-hydrogen`, `gemini-3.8-flash`, `deepseek-v4.1-flash` (Instant on global Vertex endpoint, zero forms).
- **Tier 2 (Gated Partner MaaS):** `claude-3-7-sonnet`, `claude-3-5-sonnet`, `claude-3-opus` (Requires one-time Console agreement).
- **Tier 3 (Dedicated GPU Endpoint):** Open-weights models like `glm-5-3-flash` requiring dedicated 8x H100/B200 GPU instances.

### 3. Load current state

If `~/.gemini/config/plugins/agystack/agystack-models.md` exists, read its current role assignments. Otherwise start from skill defaults.

### 4. Map and confirm

Present two presets to the user (or allow per-role customization):
- **Preset 1: Universal / Gemini 3.8 Flash Compatible (Default).** Uses universal tiers (`inherit`, `flash`, and `pro`) so sessions running Gemini 3.8 Flash or any active parent model work out of the box without hardcoded model assumptions.
- **Preset 2: Gemini 4 Effort-Balanced (Neon / Argon / Hydrogen).** Uses Gemini 4 effort-suffixed identifiers (`gemini-4-neon-xhigh`, `gemini-4-neon-high`, `gemini-4-argon-high`, and `gemini-4-hydrogen-medium`). Boundary translation automatically maps these to `pro`, `inherit`, and `flash` for `invoke_subagent`, strips effort suffixes to base Vertex AI model IDs (`gemini-4-neon`, `gemini-4-argon`, `gemini-4-hydrogen`) for `/cloud-swarm`, and passes exact effort-suffixed IDs to native `swarm`.

Show every role with its model tier and confirm:
- Single roles: `feature, refactoring`, `bug-fix`, `perf-issue`, `hillclimb`, `judgment and prose`, `hardest tasks`, `how explorer`, `how explainer`, `why investigators`, `why synthesizer`, `reflect tooling`, `reflect judgment, divergent, synthesizer`, `swarm workers`
- Panel roles: `arena runners`, `arena cross-judge pool`, `architect runners`, `interrogate reviewers`

### 5. Write the model rule

Write to `.agents/plugins/agystack/agystack-models.md` if installed workspace-locally, otherwise `~/.gemini/config/plugins/agystack/agystack-models.md`.

**Preset 1: Universal / Gemini 3.8 Flash Compatible (Default):**

```
# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
#
# Supported Model Identifiers:
# 1. Universal Tiers (Default, compatible with Gemini 3.8 Flash and any active parent session model):
#    - inherit    (Runs on the active parent chat session model, e.g. Gemini 3.8 Flash High or Gemini 4 Neon)
#    - pro        (High-capability tier: deep reasoning, large refactors, complex design)
#    - flash      (Fast / balanced reasoning tier: exploration, reading, standard generation)
#    - flash_lite (Lightweight tier: fast mechanical scans and lookups)
#
# 2. Gemini 4 Effort-Balanced Identifiers (Automatically translated at each tool boundary):
#    - gemini-4-neon-{low,medium,high,xhigh}     (maps to 'pro' on invoke_subagent, 'gemini-4-neon' on /cloud-swarm, exact ID on native swarm)
#    - gemini-4-argon-{low,medium,high}          (maps to 'inherit' on invoke_subagent, 'gemini-4-argon' on /cloud-swarm, exact ID on native swarm)
#    - gemini-4-hydrogen-{low,medium,high,xhigh} (maps to 'flash' on invoke_subagent, 'gemini-4-hydrogen' on /cloud-swarm, exact ID on native swarm)

feature, refactoring: inherit
bug-fix: inherit
perf-issue: inherit
hillclimb: inherit
judgment and prose: inherit
hardest tasks: inherit
how explorer: flash
how explainer: inherit
why investigators: flash
why synthesizer: inherit
reflect tooling: inherit
reflect judgment, divergent, synthesizer: inherit
arena runners: inherit, flash, pro
arena cross-judge pool: inherit, flash, pro
swarm workers: flash
architect runners: inherit, flash, pro
interrogate reviewers: inherit, flash, pro
```

**Preset 2: Gemini 4 Effort-Balanced (Neon / Argon / Hydrogen):**

```
feature, refactoring: gemini-4-neon-high
bug-fix: gemini-4-neon-high
perf-issue: gemini-4-argon-high
hillclimb: gemini-4-argon-high
judgment and prose: gemini-4-neon-high
hardest tasks: gemini-4-neon-xhigh
how explorer: gemini-4-hydrogen-medium
how explainer: gemini-4-neon-high
why investigators: gemini-4-hydrogen-medium
why synthesizer: gemini-4-argon-high
reflect tooling: gemini-4-hydrogen-medium
reflect judgment, divergent, synthesizer: gemini-4-neon-high
arena runners: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-high
arena cross-judge pool: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-high
swarm workers: gemini-4-hydrogen-medium
architect runners: gemini-4-neon-xhigh, gemini-4-argon-high, gemini-4-hydrogen-high
interrogate reviewers: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-medium
```

### 6. Confirm

Confirm that the model rule and runtime settings are active for new sessions.

### 7. Offer a verification skill (optional)

If the project lacks an end-to-end verification harness, offer `/create-verification-skill`. For high-consequence concurrency, consensus, complex state machines, or critical parsers, also offer `/create-formal-verification-skill`.
