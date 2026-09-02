---
name: setup-agystack
description: Configure models and execution runtime for agystack. Configures Antigravity model tiers per role and Cloud Run runtime settings for up to 100+ parallel workers.
---

# Setup agystack

Configure model tiers in `~/.gemini/config/plugins/agystack/rules/agystack-models.md` and execution runtime in `~/.gemini/config/plugins/agystack/agystack-runtime.json` (or workspace `.agents/plugins/agystack/`).

## Steps

### 1. Select execution runtime

Choose the execution runtime for parallel swarms:
- **Local Runtime (Default):** Runs via native `invoke_subagent` in Antigravity for up to 8 concurrent workers. Zero cloud setup required.
- **Cloud Run Runtime:** Runs via Google Cloud Run Jobs for 10 to 100+ parallel workers in isolated container instances.

If Cloud Run is selected:
1. Verify Google Cloud SDK authentication:
   ```bash
   gcloud auth list
   ```
2. Set your active GCP project:
   ```bash
   gcloud config set project <project-id>
   ```
3. Enable required Cloud APIs:
   ```bash
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com
   ```
4. Build and push the worker container image:
   ```bash
   gcloud artifacts repositories create agystack --repository-format=docker --location=us-central1
   gcloud builds submit --tag us-central1-docker.pkg.dev/<project-id>/agystack/cloud-worker:latest skills/swarm/scripts/
   ```
5. Create the Cloud Run Job:
   ```bash
   gcloud run jobs create agystack-swarm-worker \
     --image=us-central1-docker.pkg.dev/<project-id>/agystack/cloud-worker:latest \
     --region=us-central1 \
     --tasks=1 \
     --task-timeout=30m
   ```
6. Ensure `GEMINI_API_KEY` is exported in your environment.
7. Write `~/.gemini/config/plugins/agystack/agystack-runtime.json`:
   ```json
   {
     "runtime": "cloud-run",
     "project_id": "<project-id>",
     "region": "us-central1",
     "job_name": "agystack-swarm-worker",
     "image_uri": "us-central1-docker.pkg.dev/<project-id>/agystack/cloud-worker:latest",
     "parallelism": 100
   }
   ```

### 2. Detect available models

Enumerate the model tiers you can pass to `invoke_subagent`:
- `pro`: High-capability tier (maximum reasoning budget for complex code, architecture, and hard tasks)
- `flash`: Balanced fast tier (fast execution for exploration and standard generation)
- `flash_lite`: Lightweight tier (minimal latency for quick lookups)
- `inherit` (or `auto`): Inherit parent chat model

### 3. Load current state

If `~/.gemini/config/plugins/agystack/rules/agystack-models.md` exists, read its current role assignments. Otherwise start from skill defaults.

### 4. Map and confirm

Show every role with its model tier and confirm:
- Single roles: `feature, refactoring`, `bug-fix`, `perf-issue`, `hillclimb`, `swarm workers`
- Panel roles: `how critics`, `arena runners`, `architect runners`, `interrogate reviewers`

### 5. Write the model rule

Write `~/.gemini/config/plugins/agystack/rules/agystack-models.md`:

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

Confirm that the model rule and runtime settings are active for new sessions.

### 7. Offer a verification skill (optional)

If the project lacks an end-to-end verification harness, offer `/create-verification-skill`.
