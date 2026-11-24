---
name: agystack-help
description: Guides users through agystack setup, /agystack and /poteto-mode, and picking the skill, playbook, or principle for a task. Type /agystack-help with a question.
disable-model-invocation: true
---

# Agystack help

Answer the user's question about agystack, hand them a prompt they can send, and link the file the answer came from. Keep every help turn strictly read-only. Do not edit files, run mutations, or start the work when the user asks a question, because an agystack run spends tokens and changes repository state. Let the user send the prompt when ready.

A message that asks for work, such as "use agystack to fix this bug", is not a help question. Read [`agystack`](../agystack/SKILL.md) or [`poteto-mode`](../poteto-mode/SKILL.md), execute the task under it, and note once that both stay active as sticky modes for the conversation.

This file maps questions to the skills and guide pages that hold the answers. Those files own the details. Read the file you route to before quoting it, and trust it when it disagrees with this map. Give installed plugin users the public copy when they cannot open plugin internals, using `https://github.com/jtaroreh/agystack/blob/main/` followed by the repo-relative path.

## Find out what they need

Infer the need from the message and the conversation. A named situation, such as "which skill reviews a PR?", goes straight to its section. If the need is still unclear, ask one multiple-choice question via `ask_question` with these options, then answer only the section they pick.

- Get set up
- Start a task with `/agystack` or `/poteto-mode`
- Pick a skill for a situation
- Fix a run that went wrong
- Make agystack my own

Inspect the live Antigravity setup before answering, and mention state only when it changes the answer.

- Read `agystack-models.md` at `~/.gemini/config/plugins/agystack/agystack-models.md`, `.agents/plugins/agystack/agystack-models.md`, or the plugin root to see configured role model tiers (`inherit`, `flash`, `pro`, `flash_lite`). Missing user overrides mean roles fall back to skill defaults.
- Read `agystack-runtime.json` at `~/.gemini/config/plugins/agystack/agystack-runtime.json` or `.agents/plugins/agystack/agystack-runtime.json` when the question touches Cloud Run swarms.
- Run the read-only doctor check when diagnosing setup or prerequisites, using `python3 skills/setup-agystack/scripts/setup_runtime.py --doctor` or dynamic discovery across `~/.gemini/config/plugins/agystack` and `.agents/plugins/agystack`. It checks `bun`, `gh`, `gt`, `gcloud`, `agystack-models.md`, the safety hook contract, the brain artifact directory, and legacy `skills/swarm/` collisions.
- Check [`hooks.json.example`](../../hooks.json.example) against `.agents/hooks.json` or `~/.gemini/config/hooks.json` when the question touches automatic formatting, command safety, or coordinator delegation guards.
- Check `.agents/skills/verify-*` in the workspace when the question involves proving app behavior (`/create-verification-skill` or `/maintain-verification-skill`) or formal properties (`/create-formal-verification-skill` or `/maintain-formal-verification-skill`). When a formal verification skill exists and covered code changed past its recorded sync-commit SHA, mention `/maintain-formal-verification-skill` if the question touches that code.

When custom model roles are missing and it matters (new user, setup or cost question, or model-dependent answer), ask once via `ask_question` whether to configure roles now or later. If the need is also unclear, ask both questions together. Offer two choices.

- **Now.** Give them `/setup-agystack` to run, and answer their question too.
- **Later.** Answer their question, and add one line noting that roles use their defaults until they run `/setup-agystack`.

## Get set up

1. Install agystack with `agy plugin install agystack`, through **Customizations > Marketplace** in the Antigravity UI, or by cloning into `~/.gemini/config/plugins/agystack` (global) or `.agents/plugins/agystack` (workspace-local).
2. Run [`/setup-agystack`](../setup-agystack/SKILL.md). It runs `setup_runtime.py --doctor`, explains local subagents versus on-demand Cloud Run swarms, maps model tiers per role in `agystack-models.md` (and writes `agystack-runtime.json` when Cloud Run is selected), and offers `/create-verification-skill` or `/create-formal-verification-skill` when missing.
3. Optionally enable lifecycle hooks by copying [`hooks.json.example`](../../hooks.json.example) to `.agents/hooks.json` or `~/.gemini/config/hooks.json`.
4. Start a real task with `/agystack` or `/poteto-mode`, a goal, and a check that can pass or fail.

Installing changes nothing until a skill or hook runs. The [README](../../README.md) and [guide page 1](../../docs/guide/01-setup.md) cover setup details. Offer to word their first prompt together using [`references/prompting.md`](references/prompting.md).

If cost is the worry, explain where tokens go and how to spend fewer. agystack spends extra tokens on subagents and multi-model review panels (`interrogate`, `arena`, `architect`). Rerun `/setup-agystack` or edit `agystack-models.md` to route explorers and workers to `flash` or `flash_lite`. Setting a role to `inherit` (or `auto`) runs that role on the parent chat model. Shortening a panel list runs fewer subagents because one subagent spawns per entry. Daily tasks and local fan-outs of 8 or fewer workers always run locally via `invoke_subagent`. Cloud Run (`/cloud-swarm`) spins up only on explicit swarm invocation and costs `$0` when idle.

## Start a task with `/agystack` or `/poteto-mode`

`/agystack` and `/poteto-mode` are twin entry points that both load [`poteto-mode`](../poteto-mode/SKILL.md). Both match the task to one of 23 playbooks, copy its steps into the todo list, delegate non-trivial code edits (`> 50` lines or multi-file changes) to `poteto-agent` via `invoke_subagent`, and write deliverables (`implementation_plan.md`, `walkthrough.md`, domain reports) under `<appDataDir>/brain/<conversation-id>/`.

A good prompt states the goal and how to verify completion. Leave out a hand-written sequence of skills, because listing skills drops or reorders steps the playbook keeps. Read [`references/prompting.md`](references/prompting.md) before helping word a prompt. [Guide page 2](../../docs/guide/02-poteto-mode.md) has examples.

Both `/agystack` and `/poteto-mode` stay active as sticky modes for the conversation. Say `"new task"` mid-chat to re-match a fresh playbook, or opt out explicitly on casual turns. To get the same style from a custom subagent you spawn directly, pass `TypeName: "poteto-agent"`.

## Route across Antigravity slash commands and agystack skills

Antigravity separates user-facing slash commands from programmatic agent primitives (`invoke_subagent`, `run_command`, `schedule`, `ask_question`). See [`antigravity-tools.md`](../poteto-mode/references/antigravity-tools.md). Users type slash commands in chat; agents execute skills and programmatic primitives.

### Antigravity slash commands and native capabilities

| Command or capability | When to use |
|---|---|
| `/agystack` or `/poteto-mode` | Run any non-trivial task under the 23 playbooks and 24 principles |
| **Orchestrator** (model mode) | Pair a frontier planner (`Gemini 4 Neon`/`Carbon`/`Claude Opus 5.5`) with a fast executor (`Gemini 4 Hydrogen`/`Claude Sonnet 5.5`) in one conversation |
| `/run-workflow` (`run_workflow`) | Run predictable scripted `parallel()` / `pipeline()` sweeps across files or packages, or staged reviewer-fixer loops |
| `/goal` with `schedule` | Drive overnight autonomous tasks, queue drains, and periodic audit ticks |
| `/loop` with `--verify` | Run an inner-loop verification hillclimb against a command that exits `0` on success |
| `/schedule` | Set one-shot wakeups (`DurationSeconds`) or recurring cron triggers (`CronExpression`) |
| `/boost` | Trigger Antigravity's native multi-stage deep reasoning pipeline for hard problems |
| `/teamwork` | Run Antigravity's native collaborative team roles across long-horizon multi-milestone projects |
| Native `/swarm` | Coordinate Antigravity agents that collaborate on a shared message board (opt-in; never invoked unprompted outside `/swarm`) |

Do not send overnight audit ticks or standing PR watch loops through `/loop`. Use `/goal` paired with `schedule` for standing autonomous ticks, and reserve [`/loop`](../loop/SKILL.md) strictly for inner-loop verification hillclimbs (`--verify "<command>"`). Use local `invoke_subagent` fan-out for 8 or fewer independent workers, `/run-workflow` for deterministic scripted sweeps (`parallel()` / `pipeline()`), native `/swarm` for shared-board peer collaboration, and [`/cloud-swarm`](../cloud-swarm/SKILL.md) for more than 8 headless workers on Cloud Run.

### agystack skills

The default answer for multi-step engineering work is `/agystack` or `/poteto-mode`, which invokes most other skills automatically when a step needs them. Name a skill directly when the user wants more or less rigor than the playbook provides. Read the target skill before recommending it, and include one example prompt.

| The user wants to | Skill |
|---|---|
| Run any non-trivial task with full Antigravity rigor | [`/agystack`](../agystack/SKILL.md) |
| Run poteto's playbook engine and style directly | [`/poteto-mode`](../poteto-mode/SKILL.md) |
| Check that the agent understood the goal and scope before starting | [`/in-your-own-words`](../in-your-own-words/SKILL.md) |
| Rewrite a prompt deeper, not bigger, with raw inputs and outside checks before sending it | [`/sharpen`](../sharpen/SKILL.md) |
| Understand how code works now, or where new code belongs | [`/how`](../how/SKILL.md) |
| Learn why code is shaped a certain way, or where a threshold came from | [`/why`](../why/SKILL.md) |
| Understand a change or subsystem explained plainly with diagrams | [`/teach`](../teach/SKILL.md) |
| Rebuild working context on a topic from recent chats and shared records | [`/recall`](../recall/SKILL.md) |
| Get a tight status brief under 100 words with artifact links and waiting calls | [`/ketchup`](../ketchup/SKILL.md) |
| Check what a small diff could break outside itself with a live proof | [`/blast-radius`](../blast-radius/SKILL.md) |
| Settle caller usage, types, and module boundaries before coding | [`/architect`](../architect/SKILL.md) |
| Run competing attempts at one brief, score them, and graft the best parts | [`/arena`](../arena/SKILL.md) |
| Fan out more than 8 parallel workers over slices or races on Cloud Run | [`/cloud-swarm`](../cloud-swarm/SKILL.md) |
| Have diverse model tiers challenge a diff and prove bugs with executable repros | [`/interrogate`](../interrogate/SKILL.md) |
| Fix a bug test-first when a cheap local test target exists | [`/tdd`](../tdd/SKILL.md) |
| Apply TypeScript type-system rules to `.ts` or `.tsx` changes | [`typescript-best-practices`](../typescript-best-practices/SKILL.md) |
| Strip defensive bloat, redundant guards, and AI tells from code and diffs before commit | [`/deslop`](../deslop/SKILL.md) |
| Strip unnecessary comments before review using a fresh reviewer (`comment-sicko`) | [`/no-comments`](../no-comments/SKILL.md) |
| Clean AI tells and filler out of prose | [`/unslop`](../unslop/SKILL.md) |
| Write docs, RFCs, readmes, PR descriptions, or commit messages to standard | [`/technical-writing`](../technical-writing/SKILL.md) |
| Restate the last reply in plain human words without jargon | [`/bro`](../bro/SKILL.md) |
| Generate a project-local `verify-<app>` skill and feature map | [`/create-verification-skill`](../create-verification-skill/SKILL.md) |
| Bring a `verify-<app>` skill and feature map back in sync with the app | [`/maintain-verification-skill`](../maintain-verification-skill/SKILL.md) |
| Formally verify concurrency, consensus, state machines, or critical parsers | [`/create-formal-verification-skill`](../create-formal-verification-skill/SKILL.md) |
| Sync a formal verification model or harness after code changes and separate drift from bugs | [`/maintain-formal-verification-skill`](../maintain-formal-verification-skill/SKILL.md) |
| Verify a TLA+ state model into a Mermaid chart with bug paths, or draft a labeled sketch | [`/statechart`](../statechart/SKILL.md) |
| Vet a speedup, latency, or benchmark number against the seven verification questions | [`/benchmark-checklist`](../benchmark-checklist/SKILL.md) |
| Drive iterative edits against a `--verify` command until exit code `0` | [`/loop`](../loop/SKILL.md) |
| Design a bespoke auditable playbook for large or cross-cutting work | [`/figure-it-out`](../figure-it-out/SKILL.md) |
| Keep an append-only `decisions.tsv` trail and cross-model audit during unattended runs | [`/show-me-your-work`](../show-me-your-work/SKILL.md) |
| Configure per-role model tiers and Cloud Run swarm settings | [`/setup-agystack`](../setup-agystack/SKILL.md) |
| Draft a personal `-mode` skill from recent workspace transcripts | [`/automate-me`](../automate-me/SKILL.md) |
| Turn lessons from a completed session into skill edits | [`/reflect`](../reflect/SKILL.md) |
| Stop recurring agent mistakes using architecture, types, hooks, or tests | [`/correct`](../correct/SKILL.md) |
| Get help choosing agystack skills, playbooks, or prompts without starting work | `/agystack-help` |

If another skill directory appears under `skills/` or `.agents/skills/` that is missing from this table, read its `SKILL.md` frontmatter and route by its `description`. Principles live in `skills/principle-*/` and are covered below.

Close calls worth keeping straight.

- `/how` explains current code mechanics, `/why` explains historical reasons, and `/teach` runs one or both into one plain explanation.
- `/arena` runs the same brief across candidates and grafts winners. Local `invoke_subagent` fan-out covers `<= 8` slice or race workers. Native `/swarm` handles shared-board collaboration. `/cloud-swarm` scales `> 8` headless slice or race workers on Cloud Run.
- `/interrogate` challenges the diff with adversarial models and drops unreproduced findings. `/blast-radius` checks what could break outside the diff and proves one safety invariant by running code.
- `/recall` rebuilds context across recent chats and shared records. `/ketchup` summarizes only what changed in the active conversation since the user's last message. Resuming one specific branch or checkpoint uses the [Session pickup playbook](../poteto-mode/playbooks/session-pickup.md).
- `/figure-it-out` designs a bespoke rigorous run when no bundled playbook fits. The [Autonomous run playbook](../poteto-mode/playbooks/autonomous-run.md) drives one predicate to completion.
- `/goal` with `schedule` runs overnight work and periodic audit ticks. [`/loop`](../loop/SKILL.md) runs iterative verification hillclimbs tied to `--verify "<command>"`.
- [`/deslop`](../deslop/SKILL.md) cleans code and diffs, [`/unslop`](../unslop/SKILL.md) cleans prose, and [`/no-comments`](../no-comments/SKILL.md) strips comments through `comment-sicko`.

## Playbooks and principles

Playbooks are step lists inside `skills/poteto-mode/playbooks/`, not slash commands. Describing the task under `/agystack` or `/poteto-mode` picks one automatically, and these phrases route directly.

- `"babysit this pr"` or `"check on pr 123"` runs [Babysit](../poteto-mode/playbooks/babysit.md). It declares a mode (`drive`, `background`, `threads-only`, or `check`), stops at merge-ready, and never merges.
- `"land the stack"` runs [Shipping](../poteto-mode/playbooks/shipping.md), which verifies each PR independently and lands only the contiguous verified run bottom-up via `gh` (or `origin pr`).
- `"take over this branch"` runs [Session pickup](../poteto-mode/playbooks/session-pickup.md).
- `"pause safely"` runs [Pause safely](../poteto-mode/playbooks/pause-safely.md).
- `"full autopilot on this queue"` runs [Autopilot-full](../poteto-mode/playbooks/autopilot-full.md). `"autopilot, don't merge"` runs [Autopilot-stack](../poteto-mode/playbooks/autopilot-stack.md).
- `"orchestrate"` for multi-day multi-stack programs runs [Orchestrate](../poteto-mode/playbooks/orchestrate.md).
- `"run the eval playbook"` runs [Eval](../poteto-mode/playbooks/eval.md).

The Playbooks section of [`poteto-mode`](../poteto-mode/SKILL.md) lists all 23 playbooks. [Guide page 6](../../docs/guide/06-verify-and-ship.md) covers verification, opening PRs, babysitting, and shipping.

agystack has no standalone planning skill because Antigravity provides native `implementation_plan.md` artifacts. For phased or stacked multi-PR work, asking `/agystack` or `/poteto-mode` for a plan triggers the [Multi-phase plan playbook](../poteto-mode/playbooks/multi-phase-plan.md), which writes the plan without implementing it and checks it with `node skills/poteto-mode/scripts/check-plan.mjs`. For design forks, [Prototype](../poteto-mode/playbooks/prototype.md) or `/architect` settles questions in code first.

Principles are 24 single-rule skills that `/poteto-mode` reads and cites alongside the decision changed. Users rarely invoke them with slashes; steer by naming the principle instead (such as `"apply prove it works. show me the real output"`). [Guide page 8](../../docs/guide/08-principles.md) indexes all 24.

## Fix a run that went wrong

| Symptom | Fix |
|---|---|
| A follow-up question got pulled into the last task | Say `"new task"` so the sticky mode matches a fresh playbook, or opt out explicitly. |
| A model override had no effect | Check `agystack-models.md` with `setup_runtime.py --doctor` and start a new session so the updated config loads. |
| Native `/swarm` collides with an old swarm folder | Check `setup_runtime.py --doctor` and delete any leftover `skills/swarm/` directory from pre-0.17.0 archives. |
| An overnight run drifted or exited without finishing | Move standing work from `/loop` to `/goal` with `schedule` and a checkable predicate, or keep `/loop` strictly on `--verify "<command>"`. See [guide page 7](../../docs/guide/07-overnight.md). |
| Parallel subagents overwrote each other's files | Dispatch isolated workers with `Workspace: "branch"` or fresh worktrees, or run large sweeps on `/cloud-swarm`. |
| Runs cost more tokens than expected | Set explorer and worker roles to `flash` or `flash_lite` in `agystack-models.md`, shorten panel lists, and reserve `/cloud-swarm` for `> 8` workers. |
| The reply declared victory from a passing build | Ask for the real command, live flow receipt in `walkthrough.md`, stored value, or profile via `prove-it-works`. |
| `/interrogate` dropped an issue you care about | Read the `Dismissed` section in `adversarial_review.md`; findings without a working repro command are dropped unless you override. |
| A lifecycle hook blocked a direct edit or command | Check [`hooks.json.example`](../../hooks.json.example); `pre_tool_delegation.py` asks or blocks non-trivial coordinator edits over 50 lines unless delegated to `poteto-agent`. |

For mid-run steering, [`references/prompting.md`](references/prompting.md) has one-line redirects. [Guide page 10](../../docs/guide/10-recipes-and-pitfalls.md) lists recipes, lifecycle hooks, and common pitfalls.

## Make agystack my own

- [`/automate-me`](../automate-me/SKILL.md) mines workspace brain transcripts to draft a personal `-mode` skill.
- [`/reflect`](../reflect/SKILL.md) turns session lessons into candidate skill edits waiting on your approval.
- [`/correct`](../correct/SKILL.md) fixes recurring mistakes in repo architecture, types, hooks (`hooks.json.example`), or tests (`tests/`).
- `/agystack write a skill for <workflow>` runs [Authoring or modifying a skill](../poteto-mode/playbooks/authoring-a-skill.md), and [Eval](../poteto-mode/playbooks/eval.md) tests skill changes blind.
- Fix any broken skill in its own PR rather than inside unrelated feature work.

[Guide page 9](../../docs/guide/09-make-it-yours.md) covers each workflow.

## Reply

Lead with the direct answer. Include at most one example prompt in a code block, adapted from [`references/recipes.md`](references/recipes.md) when one fits, followed by a link to that file and the source skill or guide page. Keep the reply concise unless the user asked for the full map, and make zero edits during a help turn.
