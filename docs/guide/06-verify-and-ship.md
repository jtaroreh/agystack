# Verify the result and open a PR

"It compiles" is not evidence. The [Prove It Works principle](../../skills/principle-prove-it-works/SKILL.md) makes the agent check the real artifact before reporting success, and your job is to make `"the real artifact"` checkable. This page covers stating a finish condition, vetting a measured number, creating a verification skill for your app, formally verifying properties tests rarely reach, opening the PR, and driving it to merged.

Verification is the slowest step in most agent work, because it is the step that usually waits on a human. Make the agent able to run it, and you stop being the bottleneck. Skip it, and running more agents only produces unchecked diffs faster.

![A prototype plane flies a real test course while she times it with a stopwatch and robots film and checklist the run; the terminal reads verify: pass, evidence: captured.](./images/verification.jpg)

## State the finish condition up front

Put what done means in the first prompt, in whatever words fit.

```text
/poteto-mode add json output to this command. text output stays byte-identical, the json parses, both run against the sample project. show me the evidence.
```

Now the agent has three checks it can run, not a mood to satisfy. When the reply comes back, it links directly to a `walkthrough.md` artifact carrying the exact commands, outputs, and verification receipts. If a check could not run, a good reply says `"inconclusive"`. Treat a confident reply without evidence as a warning sign.

Match the check to the change.

- A CLI change runs the real command.
- A UI change walks the changed flow in the running app. When a view must match a reference pixel for pixel, the [Visual parity playbook](../../skills/poteto-mode/playbooks/visual-parity.md) diffs screenshots against a frozen baseline instead of judging by eye.
- A parser or migration replays a saved input.
- A perf change compares before and after profiles.
- A storage change reads back the written value.

Ask for proof as an artifact you can inspect directly, such as the failing test followed by the passing one, screenshot carousels in `walkthrough.md`, or the trace. If the fix already merged, ask for the same check on `main`. An artifact beats a plausible explanation because you can challenge it without replaying the whole run.

For a small diff you do not fully trust, [`/blast-radius`](../../skills/blast-radius/SKILL.md) finds what it could break elsewhere. It identifies the one fact that makes the change safe and proves that fact by running code rather than arguing for it.

## Vet a measured number with `/benchmark-checklist`

A before-and-after number is the easiest evidence to get wrong by accident. A warm cache, a debug build on one side, or work skipped outside the timed region can fake a convincing speedup. Before you report or act on a number, run the checklist.

```text
/benchmark-checklist vet the export speedup before it goes in the pr
```

[`/benchmark-checklist`](../../skills/benchmark-checklist/SKILL.md) asks seven questions and requires run evidence for each.

1. What limits the number, and why is it not double?
2. Did every side run tuned the way production runs?
3. Does the result break a physical limit, such as disk bandwidth or core count?
4. Did anything error or return wrong output?
5. Does it reproduce over alternating runs, with a median and a range?
6. Does it matter end to end, on the path a user waits on?
7. Did the work actually happen inside the timed region?

The verdict comes back as `faster`, `slower`, `no measurable difference`, or `inconclusive`, with the run count, range, and limiter logged in `perf_report.md`. It reports `inconclusive` when it cannot name the limiter or a side ran untuned. `/poteto-mode` already runs this checklist inside the Perf issue and Hillclimb playbooks, so invoke it directly when you measured outside them or when a speedup looks too good. It is the working form of the [Explain the Number principle](../../skills/principle-explain-the-number/SKILL.md).

## Surface Precedence Hierarchy

When verifying or investigating, enforce strict tool precedence.

1. **Filesystem Tools (`view_file`, `grep_search`, `find_by_name`).** Ground truth for code, configs, AST, tests, and repo docs. Never use a browser or UI tool to view, search, or scroll through code and repository files.
2. **CLI and Runtime Tools (`run_command`).** Test suites, API endpoints, build and server logs, process lifecycles, and exit codes.
3. **Browser Tools (`browser_subagent` and Chrome DevTools MCP).** Strictly for live UI interaction, DOM layout inspection, CSS styles, user events, and rendered visual screenshots.

## Create a project verification skill

The UI bullet above hides a real requirement. The agent needs a scripted way to drive your app. Antigravity includes native browser automation through `browser_subagent` (Chrome DevTools MCP) alongside process execution, so no external driver package is needed.

Any project needs an app feature map first, generated by `/create-verification-skill`. If your project lacks one, run the generator.

```text
/create-verification-skill
```

[`/create-verification-skill`](../../skills/create-verification-skill/SKILL.md) interviews the repository, not you. It works out what a user touches, how the app launches locally, what drives it (an existing harness first, otherwise native `browser_subagent` / CDP, a PTY or tmux harness, or plain HTTP), what evidence proves behavior, and whether two instances can run side by side. It asks you only what the code cannot answer.

It writes `.agents/skills/verify-<app>/`, agent-facing instructions with exact `Launch`, `Doctor`, `Drive`, `Evidence`, `Cleanup`, and `Helpers` sections, plus a feature map under `features/` indexing what the app does and what observable end state proves each feature works. The skill ships a [worked feature-map example](../../skills/create-verification-skill/references/feature-map-example/README.md) with an index and one file per feature using the four required H2 headings. Before handing it over, the generator proves the skill once end to end (launch, doctor, drive one feature, capture evidence, clean up, and confirm evidence survived cleanup). If that proof fails, do not use the output.

From then on, `"verify it in the app"` is a step any agent can execute in this repo with no setup conversation. Name it in the prompt when you want proof in a specific form.

```text
/poteto-mode build the bulk-archive action. use /verify-<app> to verify your changes and attach screenshots in walkthrough.md.
```

```text
/poteto-mode repro this with /verify-<app>. if it repros on main, fix it and capture before-and-after screenshots.
```

Once the verify skill works, a local `invoke_subagent` fan-out (`<= 8` workers) or [`/cloud-swarm`](../../skills/cloud-swarm/SKILL.md) (`> 8` workers) can split a full pass by feature-map entry and aggregate one report, confirm a perf gain over a larger sample, or fuzz flows before a PR ships.

Treat the verification skill as infrastructure, not a one-off. Commit it so every person and agent drives the app the same way. Then [build the lever](../../skills/principle-build-the-lever/SKILL.md). When agents keep writing throwaway scripts to click through the app, ask for a small control CLI that the skill calls instead. Agents spend fewer tokens, and every run becomes repeatable. A CLI that agents use well has these traits.

- A few composable commands, each doing real work, rather than many thin ones.
- A `--dry-run` option on anything destructive.
- Subcommands that reveal features gradually instead of all at once.
- Error messages that say what to do instead.
- Rich `--help` text.
- Machine-readable output, such as JSON.

Make dev setup repeatable at the same time with seeded data, test users, and one command that brings the environment up cleanly.

## Keep the verification skill honest

Apps change, and feature maps go out of date. Run this regularly, or trigger it on a recurring schedule, so the map stays true to the app.

```text
/maintain-verification-skill
```

[`/maintain-verification-skill`](../../skills/maintain-verification-skill/SKILL.md) audits the generated skill using one read-only source reader per feature in parallel, then one live pass driving every mapped feature. It ends in exactly one of three outcomes (`clean`, `changed`, or `blocked`). It never edits product code. If the live pass catches a product regression, it reports the regression instead of papering over it in docs.

## Prove a property with a formal verification skill

A verification skill proves the paths you drive. Some bugs live on paths nobody drives, such as two retries overlapping, a lock expiring mid-write, or a state change arriving out of order. Tests rarely reach those cases. For concurrency protocols, distributed consensus, complex state machines, or critical parsers where such a bug is costly, run the formal generator.

```text
/create-formal-verification-skill
```

[`/create-formal-verification-skill`](../../skills/create-formal-verification-skill/SKILL.md) picks the target from the code where a break harms users and tests rarely reach the failure case, choosing the strongest promise rather than the easiest module. Name an area or a bug to start there directly.

```text
/create-formal-verification-skill the job lease and retry logic. a job must never run twice at once.
```

The question selects the tool. Event ordering and concurrency use a model checker over a faithful small model, with TLA+ as the default in any language. Input-level safety or data-structure invariants use an SMT-backed verifier on the real code, or generated inputs against the real code when no verifier exists for the language. Unbounded size properties use a proof assistant. The agent records why it chose the tool in `formal_verification_report.md`.

Every property is verified and proven able to fail against a temporary scratch break in real code, because a check that has never failed proves nothing. When current code already breaks a property, the agent reports the counterexample as short steps in the code's terms without weakening the property or silently editing product code.

The generated `.agents/skills/verify-<area>/SKILL.md` records the coverage map (files and functions covered) and the sync-commit SHA where verification last matched the code. After merges or refactors that touched covered code, run [`/maintain-formal-verification-skill`](../../skills/maintain-formal-verification-skill/SKILL.md). It diffs from the sync commit, updates the model or harness from code before rerunning, proves the updated check still catches a scratch break, and assigns `in sync`, `updated`, `bug`, or `blocked` so verification drift never hides a product bug.

## Show the behavior as a statechart

A counterexample in model terms convinces you. A PM or designer who owns the behavior needs to see it in their own words.

```text
/statechart what the user sees when they edit a note offline
```

[`/statechart`](../../skills/statechart/SKILL.md) supports two explicit modes. **Mode 1 (Verified TLC model)** checks a `.tla` and `.cfg` model with TLC via `scripts/statechart`, rendering a Mermaid `stateDiagram-v2` chart (`chart.mmd`) and `report.md` inside `statechart_<slug>.md` so the diagram and checked model cannot drift apart. Reader rules become TLA+ invariants, broken states get marked on the diagram, and the report lists the shortest counterexample path in plain words. When the model describes real code, replay every counterexample path against the real code so modeling drift never reaches the reader as a bug. **Mode 2 (Unverified design sketch)** draws native Mermaid directly for early exploration and labels the artifact explicitly as unverified.

## Open the PR

```text
/poteto-mode open the pr. small ordered commits, evidence in the description.
```

The [Opening a PR playbook](../../skills/poteto-mode/playbooks/opening-a-pr.md) works from a worktree, rebases work into small ordered commits, runs `/deslop` and `/no-comments`, writes a briefing under 40 lines using `/technical-writing` and `/unslop`, and opens the PR ready (`draft: false`) via `gh pr create` by default (or `origin pr create --status open` when Origin resolves the repo; Graphite tracking is optional only). Five narrow PRs beat one fat one, and stacked follow-ups beat a growing branch.

## Drive the PR to merge-ready with Babysit

An open PR starts collecting blockers immediately. Checks fail, reviewers comment, trunk moves. Hand that churn to the [Babysit playbook](../../skills/poteto-mode/playbooks/babysit.md).

```text
/poteto-mode babysit this pr. get it green.
```

Babysit declares its mode (`drive`, `background`, `threads-only`, or `check`) first, watches GitHub PRs via the bundled `watch-pr` tool under `/goal` and `schedule` (or `origin pr checks` on Origin), and takes blockers in order (conflicts, then review threads, then CI). Every known fix batches into one push wave so checks restart once, and Babysit never mutates stack topology or force-pushes shared stacks. Comment triage is skeptical per `bugbot-triage.md`, fixing real catches and posting concrete disproofs on noise threads. When you only want status, ask smaller and Babysit replies without looping.

```text
/poteto-mode check on pr 123. anything outstanding?
```

Babysit stops at merge-ready (`READY` or queued `WAITING`). It never merges or arms auto-merge, because merging is a separate decision.

## Land the stack with Shipping

Green is not the same as safe. When you are ready to land, say so explicitly.

```text
/poteto-mode land the stack.
```

The [Shipping playbook](../../skills/poteto-mode/playbooks/shipping.md) resolves the forge (`gh` by default, or `origin pr` when Origin resolves the repository; Graphite `gt` is never required) and dispatches one fresh `poteto-agent` per PR to prove behavior live on the real surface before arming anything. Then Shipping lands only the contiguous verified run bottom-up, checking `git patch-id` across restacks, keeping intermediate child PRs off `--auto` so they never collapse into an unmerged parent branch, reading each PR back to confirm `mergedAt`, and reporting the first PR that breaks the chain. A verified PR sitting above an unverified one waits, because merging it would pull the gap in underneath.

Next, [Run work while you sleep](./07-overnight.md).
