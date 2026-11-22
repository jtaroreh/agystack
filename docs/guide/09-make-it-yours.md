# Make it yours

poteto-mode is one person's style. The machinery underneath (playbooks, routing, model roles) works just as well wearing yours. This page covers generating a personal mode, capturing lessons from a session, fixing the repo so agents stop repeating mistakes, authoring a focused skill, and testing a skill change before you trust it.

Start smaller than you think. You do not need many skills on day one, or even this whole plugin. Prompt plainly, watch where agents fail, and add a skill or a check when the same failure shows up twice.

## Generate your own mode with `/automate-me`

```text
/automate-me
```

You do not describe your style, because [`/automate-me`](../../skills/automate-me/SKILL.md) reads it out of your history. It mines your recent transcripts in the active workspace for repeated preferences across replies, delegation, verification, code, prose, and process, then asks which patterns are really you. It drafts `.agents/skills/<your-name>-mode/SKILL.md` (or `~/.gemini/config/skills/<your-name>-mode/`), formats standard YAML frontmatter, runs the draft through [`/unslop`](../../skills/unslop/SKILL.md), and opens a PR from a worktree so you review it like any other change.

Run it again whenever your habits drift.

```text
/automate-me update my mode skill with everything since its last edit
```

Update mode mines only the history since the skill last changed. It keeps rules you have not contradicted, revises the ones with new evidence, and adds sections only for genuinely new patterns.

## Capture a session's lessons with `/reflect`

Right after a task that taught you something, run `/reflect`.

```text
/reflect that took way too long. capture what we learned so the next run doesn't repeat it.
```

[`/reflect`](../../skills/reflect/SKILL.md) sends the transcript to three parallel reviewers, then a synthesizer sorts proposals into `Accepted`, `Rejected`, and `Backlog` and waits for your approval before editing any skill. Approve a proposal only if it would change a future decision. One weird session is an anecdote, not a rule.

## Fix the environment with `/correct`

When you keep correcting agents for the same mistake, the fix belongs in the repo, not in your next prompt. Rank the options by how reliably they enforce the rule.

1. Eliminate the mistake with architecture or a better data structure.
2. Enforce it with types, static checks, or Antigravity lifecycle hooks ([`hooks.json.example`](../../hooks.json.example)) and linters whose error messages name the fix.
3. Catch it with behavioral tests under `tests/`.
4. Write it down in `rules/AGENTS.md` or skill prose last. Nothing fails automatically when an agent skips text.

Human review is not on the list. A reviewer catching the same mistake on every PR is the symptom this solves. Run [`/correct`](../../skills/correct/SKILL.md) with a specific pattern or with no arguments.

```text
/correct agents keep calling the database client directly instead of going through the repository layer
```

It reads recent commits, reverts, review comments, `rules/AGENTS.md`, and workaround comments, then groups repeated failures into classes (a class counts once it happens twice). It fixes the top classes one commit each at the highest level that works, proves each new check fails on a real past mistake, and maintains a rule-to-enforcer table so unenforced rules stand out immediately. Run `/correct` with no arguments to surface repeated mistake classes from repo history on its own. `/reflect` improves skills from one session, while `/correct` changes the repo so a mistake class cannot return.

## Author a focused skill

When you already know the workflow you want to capture, ask the mode to draft it.

```text
/poteto-mode write a skill for verifying database migrations in this repo
```

Writing a skill matches the [Authoring or modifying a skill playbook](../../skills/poteto-mode/playbooks/authoring-a-skill.md), which drafts the standard Antigravity `SKILL.md` layout, validates YAML frontmatter and links, and ships the result through the Opening a PR playbook. Agent-facing prose has a higher bar than human prose, because an unhelpful sentence becomes an instruction some future agent follows. Let the playbook hold that bar rather than writing a `SKILL.md` freehand.

Two special cases have their own generators. A skill that drives your app and proves behavior is a verification skill, built with [`/create-verification-skill`](../../skills/create-verification-skill/SKILL.md) and kept honest with [`/maintain-verification-skill`](../../skills/maintain-verification-skill/SKILL.md). A skill that checks properties with a model checker, prover, or code-level verifier uses [`/create-formal-verification-skill`](../../skills/create-formal-verification-skill/SKILL.md) and [`/maintain-formal-verification-skill`](../../skills/maintain-formal-verification-skill/SKILL.md). [Verify and ship](./06-verify-and-ship.md#prove-a-property-with-a-formal-verification-skill) covers both kinds.

## Write docs to a standard with `/technical-writing`

Skills are not the only prose you ship. For docs, RFCs, readmes, PR descriptions, and commit messages, run `/technical-writing`.

```text
/technical-writing review the readme changes
```

[`/technical-writing`](../../skills/technical-writing/SKILL.md) applies a layered standard aimed at prose a tired engineer understands on the first read. It picks the document's mode first (tutorial, how-to, reference, or explanation), then works sentence by sentence on actor clarity, single-thought pacing, and removing ambiguity. Use it to review what you or an agent wrote, or name it up front when asking for a doc.

## Test a skill change blind

A skill edit affects every future session, so test it like an experiment. The same goes for adopting someone else's skill; check that it improves agent behavior on your real tasks before keeping it.

```text
/poteto-mode run the eval playbook on this skill change. same task for both variants, candidates stay blind.
```

When a skill keeps missing something you know it should catch, update and test it in one task.

```text
/poteto-mode update the review skill so it flags missing migrations, and eval the change.
```

Asking for the eval up front prevents overfitting to a single bad chat. The [Eval playbook](../../skills/poteto-mode/playbooks/eval.md) is built around the observer effect. An agent that knows it is being evaluated behaves differently. Candidate subagents receive an organic task in sanitized directories, never see the words `"eval"` or `"candidate"`, and never know about sibling candidates. One judge scores all outputs under neutral labels, grading chain-following from files actually read rather than self-reports.

Read every output yourself before accepting the verdict. If you disagree with the judge, suspect the rubric before you suspect your judgment.

**Pitfall.** Do not edit a skill mid-task because it is misbehaving. Fix it in its own PR and keep the task moving. A skill edit tangled into feature work is invisible to review and impossible to evaluate cleanly.

Next, [Recipes and pitfalls](./10-recipes-and-pitfalls.md).
