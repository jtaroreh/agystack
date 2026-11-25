# Prompts worth copying

Swap in real paths, skills, and finish checks. Informal wording works.

## Understand

- `/agystack read <thread>. restate the underlying issue in your own words, in plain english.`
- `/in-your-own-words <long or messy ask>`
- `/reframe <description of what you're building>`
- `/sharpen <the prompt you're about to send>`
- `/poteto-mode investigate why <symptom>. give me what we know, what data you used, and your best hypotheses. don't change any code yet.`
- `use /how to understand <subsystem>. then use /why to find out why it broke recently.`
- `/recall my work on <topic> from last week, then read <issue>.`
- `/teach me why you implemented it this way and not <other way>. what did you trade off?`
- `/poteto-mode take over this branch. read the decision log, find what's done, and continue. don't redo finished work.`

## Build

- Bug fix with repro first via `/poteto-mode <symptom>. repro first, then fix and verify.`
- App bug using a generated verify skill via `/poteto-mode repro this with /verify-<app>. if it repros on main, fix it and capture screenshots in walkthrough.md.`
- Cheap local test bug via `/poteto-mode repro <bug> first. if there's a cheap test path, /tdd it. then fix and rerun.`
- Feature preserving existing behavior via `/poteto-mode add <behavior>. <current output> stays byte-identical. verify both.`
- Behavior-preserving refactor via `/poteto-mode move <code> into one module, zero behavior change. record the current output first and prove it's unchanged after.`
- Measured performance fix via `/poteto-mode <operation> takes <time> on <fixture>. trace it, fix the measured cause, show me before and after.`

## Design and plan

- `/poteto-mode prototype a few options for <feature>. capture screenshots or timings in prototype_review.md for me to compare.`
- `/poteto-mode we need <feature>. /architect it first, and answer open questions with prototypes. let me review before proceeding.`
- `/poteto-mode write a tutorial for how i would use <new package> first. then /teach me why it beats the current one.`
- `ask /arena for a second opinion on this thread and our approach.`
- `/poteto-mode turn this design into a plan. small verifiable PRs, each with its own verification steps.`
- `/poteto-mode plan the migration of <library> to <target>. small verifiable PRs. the result must match the original exactly, bugs included.`

## Review and ship

- `/interrogate the whole branch, but skeptically. don't change anything yet. no nitpicks unless it's a real bug or regression.` Read the `Dismissed` bucket in `adversarial_review.md` too.
- `/create-formal-verification-skill prove <property> holds in <module>, even when <steps> interleave or retry.` After merges or refactors in covered code, run `/maintain-formal-verification-skill`.
- `/statechart what the user sees when <flow>.`
- `/benchmark-checklist vet the speedup before it goes in the pr description.`
- `/cloud-swarm check every package under <dir> against its check script. one worker per package. one report.` For 8 or fewer packages, ask for a local `invoke_subagent` fan-out.
- `/poteto-mode open the pr. small ordered commits, evidence in the description.`
- `/poteto-mode babysit this pr. get it green.` For status only, use `/poteto-mode check on pr <number>. anything outstanding?`
- `/poteto-mode land the stack.`

## Away and back

- Overnight autonomous run using `/goal` and `schedule` via `/poteto-mode im going to bed. <goal> in a fresh worktree off <base>. done means <checks>. keep a decision log. don't ask me before committing. /goal run until done. if you're truly stuck after a few hours, stop and write up why.`
- Inner-loop verification hillclimb via `/loop <goal> --verify "<command>" --max-iterations 10`
- `/show-me-your-work catch me up on what you did last night.` Read its `Attention` section first.
- `/ketchup` catches you up on this chat since your last message and lists every waiting call decidable from the reply.
- `/ketchup-video` renders a short subtitled slide video of what happened above the waiting calls.
- `/poteto-mode full autopilot on this queue. each item is independent.`
- `/poteto-mode autopilot these changes, but don't merge. i'll land them.`
- `/reflect capture what we learned so the next run doesn't repeat it.` Approve only edits that change a future decision.
- `/correct agents keep <recurring mistake>`
- `/bro` restates the last reply in plain words.
- `/agystack-help which skill fits <situation>?` answers without starting edits or spending run tokens.
