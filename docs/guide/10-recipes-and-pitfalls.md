# Recipes and pitfalls

Prompts worth copying, then the mistakes everyone makes once. Swap in your own paths and finish conditions. The recipes are deliberately informal. That is how they get typed in practice, and the skills read intent fine.

![She tastes a finished dish while robots cook from a recipe box, with pinned cards reading /how, /tdd, and /loop above the counter.](./images/recipes.jpg)

## Understand an unfamiliar subsystem

```text
use /how first to understand how this initialization works. then use /why to figure out why it broke recently.
```

Mechanics first, history second. Each skill's report names the sources it searched, so you know what the answer is grounded in.

## Restate a noisy report before touching code

```text
/poteto-mode read this thread. restate the underlying issue in your own words, in plain english. don't change any code yet.
```

A misreading shows up in the restatement, where it costs one message to fix. Keep your own theory to yourself until the agent states its own. [`/in-your-own-words`](../../skills/in-your-own-words/SKILL.md) asks for the restatement alone, with no playbook.

## Sharpen a prompt before you send it

```text
/sharpen write the onboarding doc for the new billing service.
```

[`/sharpen`](../../skills/sharpen/SKILL.md) names what a top practitioner would add that you did not ask for, the raw material they start from, their tools, and an external check that proves the result. It returns the rewritten prompt without running the task. Send the rewrite when it looks right.

## Prototype before you pick

```text
/poteto-mode prototype a few options for the settings layout. put them behind a switcher and capture screenshots of each in prototype_review.md.
```

You pick from running variants, not descriptions. The agent settles layout and timing questions through live observation.

## Turn a settled design into a plan

```text
/poteto-mode turn this design into a plan. small verifiable PRs, each with its own proof.
```

Ask only after the design settles. The plan (`implementation_plan.md`) is the deliverable, checked with `check-plan.mjs`, and execution waits for your go.

## Get a second opinion on a design

```text
ask /arena for a second opinion on this thread and our approach
```

Your current design becomes one candidate among several, and the synthesis tells you whether the panel found something stronger or confirmed what you had. Cheap insurance before a costly commitment.

## Check independent slices in parallel

```text
/cloud-swarm check every package under packages/ against its check.sh. one worker per package. one report.
```

Each worker owns one package. The parent waits for every slice and returns one `PASS`, `ISSUES`, or `BLOCKED` report instead of raw worker dumps. For 8 or fewer packages, ask for a local `invoke_subagent` fan-out; for agents collaborating on a shared board, use Antigravity's native `/swarm`.

## Review a branch skeptically

```text
/interrogate the whole branch, but skeptically. don't change anything yet. no nitpicks unless it's an actual bug or regression in behavior.
```

The qualifiers do real work. `"don't change anything yet"` keeps the pass read-only, the nitpick filter focuses on real defects, and every surviving finding requires a working repro command. Read the `Dismissed` bucket in `adversarial_review.md` too.

## Fix a bug through a failing test

```text
/poteto-mode repro the duplicate write first. if there's a cheap test path, /tdd it. then fix and rerun.
```

`"if there's a cheap test path"` matters. Forcing a test through brittle mocks proves less than running the real command, and the playbook is allowed to say so.

## Repro and fix a report with proof

```text
/poteto-mode repro this with /verify-<app>. if it repros on main, fix it and attach before-and-after screenshots in walkthrough.md.
```

`"if it repros on main"` lets the run stop early when the bug is already gone. The visual receipt in `walkthrough.md` lets you check the fix before reading the diff.

## Prove a property tests rarely reach

```text
/create-formal-verification-skill the retry queue. a message must never be delivered twice.
```

You get one property checked across every case in a stated scope, a counterexample in your code's terms if the code breaks it, and a project skill (`.agents/skills/verify-<area>/SKILL.md`) the next agent runs on future edits.

## Vet a number before you post it

```text
/benchmark-checklist vet this 40% speedup before it goes in the pr description
```

You get `faster`, `slower`, `no measurable difference`, or `inconclusive`, with the run count, range, and physical limiter recorded in `perf_report.md`.

## Stop correcting the same mistake

```text
/correct agents keep adding new config flags without registering them in the schema
```

The fix lands in the repo as architecture, types, hooks (`hooks.json.example`), or tests (`tests/`), so future agents hit the check instead of repeating the mistake.

## Ask how without starting the work

```text
/agystack-help how do i keep agystack active across turns?
```

You get an answer, one prompt to send, and a link to the source file. Nothing runs or changes on disk until you send that prompt.

## Keep a run honest while you're away

```text
im going to bed, keep going autonomously until every fixture passes. do not stop. keep a decision log i can audit in the morning. /goal run until done.
```

The full contract lives on the [overnight page](./07-overnight.md). The short form works once the task and finish condition are already in the conversation.

## Redirect a drifting run

Steering prompts are one line.

```text
i said the goal is to repro. i did not ask for a fix yet.
```

```text
apply prove it works. show me the real output, not the build log.
```

```text
/unslop that, no emdashes
```

You rarely need more words. You need the right name, and [the principles page](./08-principles.md) is the vocabulary.

## Get the reply in plain words

```text
/bro
```

That is the whole prompt. [`/bro`](../../skills/bro/SKILL.md) restates the last message like one human talking to another, without jargon and shorter. Use it when a reply is technically thorough and you still do not know what it said.

## Catch up on a chat you left running

```text
/ketchup
```

[`/ketchup`](../../skills/ketchup/SKILL.md) reports what changed since your last message in plain words under 100 words, pairs it with native `carousel` visuals or screenshots, and lists every decision waiting on you with its pick, evidence, and risk while changing nothing on disk.

## Automated Code Formatting with Antigravity Lifecycle Hooks

Keep generated code formatted cleanly without manual cleanup turns. Enable automatic linting and formatting on every file edit using Antigravity's `PostToolUse` lifecycle hook.

```bash
# Project-local hook
cp hooks.json.example .agents/hooks.json

# Or user-global hook
cp hooks.json.example ~/.gemini/config/hooks.json
```

Whenever an agent uses `write_to_file`, the hook triggers `skills/poteto-mode/scripts/hooks/post_tool_lint.py`, running `ruff format` on Python files, and `prettier --write` or `biome format --write` on JavaScript and TypeScript files if installed (excluding `.json` to preserve comments and never running on `replace_file_content` to prevent line-number drift).

## Destructive Command Guard with Antigravity PreToolUse Hooks

Prevent accidental catastrophic commands in interactive sessions without disrupting autonomous swarms or CI pipelines. Antigravity's `PreToolUse` lifecycle hook intercepts commands before execution and prompts for confirmation if a destructive command pattern is detected.

```json
{
  "agystack-safety": {
    "PreToolUse": [
      {
        "matcher": "run_command",
        "hooks": [
          {
            "type": "command",
            "command": "python3 skills/poteto-mode/scripts/hooks/pre_tool_safety.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The hook evaluates `run_command` invocations for destructive signatures.
- Root deletion (`rm -rf /`, `--no-preserve-root`)
- Force-pushing to protected trunk branches (`git push --force origin main`, `git push origin +master`), while explicitly allowing `--force-with-lease` on feature branches
- Dropping databases (`drop database <name>`)

When running in headless environments (`NON_INTERACTIVE="1"`, `CI="true"`, or `CLOUD_RUN_TASK_INDEX` in Cloud Run worker containers), the hook automatically rejects destructive commands (`"decision": "reject"`) to prevent catastrophic corruption in unattended runs or automated test suites.

To activate, copy or merge [`hooks.json.example`](../../hooks.json.example) into `.agents/hooks.json` (project-local) or `~/.gemini/config/hooks.json` (user-global).

## Coordinator Code Delegation Guard with Antigravity PreToolUse Hooks

Enforce the Coordinator Code Delegation Invariant deterministically. Antigravity's `PreToolUse` lifecycle hook intercepts direct code modification attempts by coordinator sessions and prompts for confirmation or delegates to a `poteto-agent` subagent.

```json
{
  "agystack-delegation": {
    "PreToolUse": [
      {
        "matcher": "write_to_file|replace_file_content",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.gemini/config/plugins/agystack/skills/poteto-mode/scripts/hooks/pre_tool_delegation.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The hook intercepts `write_to_file` and `replace_file_content` to keep coordinator contexts clean.
- Permits markdown deliverables (`*.md`, `*.markdown`) and scratch/slice files (`scratch/*`, `.slices/*`) immediately.
- Permits trivial surgical edits (<= 50 lines of code on a single existing file) directly.
- Bypasses checks for active subagents (`SUBAGENT=1`, `IS_SUBAGENT=1`, or child transcript detection).
- In headless/CI environments (`NON_INTERACTIVE="1"`, `CI="1"`, `CLOUD_RUN_TASK_INDEX`), rejects non-trivial direct code writes (`decision: reject`) unless subagents are disabled (`HEADLESS_NO_SUBAGENTS="1"`).
- In interactive sessions, prompts the user (`decision: force_ask`) on non-trivial writes (>50 lines on single existing files or creating new source files), preventing accidental coordinator bloat while providing an override when direct execution is explicitly desired.

## The pitfalls

- **Enumerating skills in the prompt.** `"use /architect then /arena then /interrogate"` reorders steps the playbook already sequences. State the goal and constraints. Name a skill only to override a default.
- **A vague finish condition.** `"make it better"` gives `/loop` or `/goal` nothing to check. `/loop` requires a `--verify` command that exits `0`, and `/goal` requires a checkable predicate or artifact. Give a command or artifact that can pass or fail.
- **Leading with your theory of the cause.** The agent searches wherever you pointed. Ask it to restate the problem first, then share your hunch.
- **Taking the first design.** One attempt locks in the first shape the model thought of. Ask for prototypes or `/architect` and pick from evidence.
- **Polishing an abstract plan.** Adversarial review of a plan with no code behind it invents risks that never happen. Settle open questions with prototypes, then review what got built.
- **Parallel agents in one worktree.** They overwrite each other and the diff becomes archaeology. Dispatch isolated subagents (`Workspace: "branch"`) or say `"own worktree per attempt"`.
- **Looping before you trust the loop.** A loop that cannot verify its own work only produces unchecked work faster. Get the verification skill working first.
- **Trusting an unvetted number.** A warm cache or a skipped code path can fake a speedup. Run `/benchmark-checklist` before reporting the number.
- **Correcting the same mistake by hand.** A correction in chat helps one run. `/correct` hardens the repo so no later run repeats it.
- **Using `/arena` for coverage.** `/arena` repeats one design or code brief, then picks a base and grafts the best parts. Local `invoke_subagent` fan-out (`<= 8`), `/cloud-swarm` (`> 8`), or native `/swarm` (shared board) handles slice coverage and races.
- **Accepting every review comment.** Bots and humans both file real catches and noise in one list. `/interrogate` keeps findings proven by executable repros and lists `Dismissed` items with reasons, and you can override either way.
- **Treating `auto` as a model slug.** `auto` and `inherit` mean `"omit the model field or pass inherit so the subagent inherits the parent chat model."` [Setup](./01-setup.md) covers the roles.
- **Reporting success off a green build.** A build proves it compiles. Ask for the real command, flow, stored value, or profile, and expect the evidence in `walkthrough.md`.
- **Writing a `SKILL.md` freehand.** Route it through the [Authoring or modifying a skill playbook](../../skills/poteto-mode/playbooks/authoring-a-skill.md) so validation and review happen.

That is the guide. If you skipped ahead, go back to [setup](./01-setup.md) and run one real task. The habits stick from use, not from reading.

Back to the [guide index](./README.md).
