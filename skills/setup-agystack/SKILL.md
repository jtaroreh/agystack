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

Enumerate the Gemini 4 models and `thought_level` effort tiers for `delegate_task`, `swarm`, and `cloud_dispatch.py` (never use legacy `flash` or `pro` tiers):

**Permitted Gemini 4 models & effort balancing (`thought_level`):**
- **`gemini-4-neon` (Primary preference — `low`, `medium`, `high` [default], `xhigh`):** Balanced frontier reasoning & coding model. Use `xhigh` for hardest tasks, `bug-fix`, `perf-issue`, `hillclimb`, `judgment and prose`, and synthesis/cross-judging; use `high` for `feature, refactoring`, `how explainer`, and lead panel runners.
- **`gemini-4-argon` (`low`, `medium`, `high` [default]):** Deep logic, multi-step math, and strict situational oversight. Use `high` for diverse panel perspectives (`arena`, `architect`, `interrogate`) and cross-judging.
- **`gemini-4-hydrogen` (`low`, `medium` [default], `high`, `xhigh`):** High-speed, high-efficiency execution. Use `medium` for codebase exploration (`how explorer`, `why investigators`), high-volume `swarm workers`, and fast panel diversity.
- **Native `invoke_subagent` fallback:** When a workflow uses Antigravity's `invoke_subagent` (whose `Model` enum only accepts `inherit` / `flash` / `pro` / `flash_lite`), always pass `Model: "inherit"` (never `flash` or `pro`), or dispatch via `delegate_task` / `swarm` to target the exact Gemini 4 model and `thought_level`.

**Cloud Run swarm model tiers (`cloud_dispatch.py`):**
- **Tier 1 (Zero-Friction MaaS):** `gemini-4-neon`, `gemini-4-argon`, `gemini-4-hydrogen` (Instant on global Vertex endpoint, zero forms).
- **Tier 2 (Gated Partner MaaS):** `claude-3-7-sonnet`, `claude-3-5-sonnet`, `claude-3-opus` (Requires one-time Console agreement).
- **Tier 3 (Dedicated GPU Endpoint):** Open-weights models like `glm-5-3-flash` requiring dedicated 8x H100/B200 GPU instances.

### 3. Load current state

If `~/.gemini/config/plugins/agystack/agystack-models.md` exists, read its current role assignments. Otherwise start from skill defaults.

### 4. Map and confirm

Show every role with its model tier and confirm:
- Single roles: `feature, refactoring`, `bug-fix`, `perf-issue`, `hillclimb`, `swarm workers`
- Panel roles: `arena runners`, `architect runners`, `interrogate reviewers`

### 5. Write the model rule

Write to `.agents/plugins/agystack/agystack-models.md` if installed workspace-locally, otherwise `~/.gemini/config/plugins/agystack/agystack-models.md`:

```
# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
# Only Gemini 4 models are permitted (never use legacy `flash` or `pro` tiers):
# - gemini-4-neon-{low,medium,high,xhigh}     (Primary preference: balanced frontier reasoning & coding)
# - gemini-4-argon-{low,medium,high}           (Deep logic, multi-step math, and strict oversight)
# - gemini-4-hydrogen-{low,medium,high,xhigh}  (High-speed execution, exploration, and swarm workers)

feature, refactoring: gemini-4-neon-high
bug-fix: gemini-4-neon-xhigh
perf-issue: gemini-4-neon-xhigh
hillclimb: gemini-4-neon-xhigh
judgment and prose: gemini-4-neon-xhigh
hardest tasks: gemini-4-neon-xhigh
how explorer: gemini-4-hydrogen-medium
how explainer: gemini-4-neon-high
why investigators: gemini-4-hydrogen-medium
why synthesizer: gemini-4-neon-xhigh
reflect tooling: gemini-4-neon-high
reflect judgment, divergent, synthesizer: gemini-4-neon-xhigh
arena runners: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-medium
arena cross-judge pool: gemini-4-neon-xhigh, gemini-4-argon-high
swarm workers: gemini-4-hydrogen-medium
architect runners: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-medium
interrogate reviewers: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-medium
```

### 6. Confirm

Confirm that the model rule and runtime settings are active for new sessions.

### 7. Offer a verification skill (optional)

If the project lacks an end-to-end verification harness, offer `/create-verification-skill`.
