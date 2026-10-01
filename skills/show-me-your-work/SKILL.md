---
name: show-me-your-work
description: "Keep a reviewable decision trail for long-running or unattended work: a TSV log with one row per decision (what, why, evidence, result). Local by default; commit it when a reviewer needs the trail to trust the result. Use for /show-me-your-work, autonomous or multi-phase runs, or work a human reviews after stepping away."
disable-model-invocation: true
---

# Show me your work

For work a human reviews after the fact, a decision trail lets them reconstruct what was decided, why, and on what evidence, without rerunning the work or reading the whole transcript. Keep one canonical log so the trail is consistent and a future agent can find it.

## The format

A single TSV file, one row per decision. TSV because GitHub renders it as a sortable table, `column -s$'\t' -t` and spreadsheets read it, and a row appends with one command. Cells stay single-line. Evidence is a pointer, not prose. Invariant: `decisions.tsv` must contain only raw unformatted text (UUID strings, no markdown links) to preserve tabular TSV parsing and spreadsheet compatibility.

Copy `references/decision-log-template.tsv` (the header row) to start a clean log. Columns:

- **ts.** ISO8601 timestamp. The timeline axis.
- **phase.** The phase or workstream.
- **decision.** What was chosen or done, one line.
- **why.** The reason in plain words. If a principle drove it, say it plainly (`explored options first, this was a one-way door`), not as a jargon tag.
- **evidence.** A link or path that proves it: commit SHA, PR number, `file:line`, or an artifact, trace, or screenshot path. Never a paragraph.
- **result.** The outcome or predicate state: `tests green`, `reverted`, `pixel-diff 0`, `INCONCLUSIVE`, `open`.

An example, plain-spoken so a reviewer reads it at a glance. This is illustration only; don't copy these rows into a real log.

```
ts	phase	decision	why	evidence	result
2026-05-24T09:02:00Z	frame	counted the work first, about 100 components and roughly 75 hours	wanted to know the size before starting a long run	commit 3a9f1c2	found 5 things to sort out before starting
2026-05-24T09:40:00Z	harness	took screenshots of the old version before changing anything	so we can compare old against new and catch any visual change	scripts/snapshot.sh, baseline/	saved 120 reference screenshots
2026-05-24T11:15:00Z	widget	moved the widget styles over without changing how it looks	keep the change small and the result identical	commit 7c21e0a, pixel-diff 0	looks identical, tests pass
2026-05-24T12:30:00Z	widget	threw out a helper's work because its screenshots were blank	checked the real files instead of trusting its summary	worktree reset	reverted, tightened the instructions for next time
```

## Logging a row

Write each entry the way you'd tell a teammate what you did. Plain words, concrete actions, no AI speak or abstract jargon (the **unslop** skill applies to log text too). A reviewer should understand each row without decoding it.

Use the helper so rows stay well-formed: `$(find ~/.gemini/config/plugins/agystack .agents/plugins/agystack skills/show-me-your-work -name "log.sh" -type f 2>/dev/null | head -1) <logfile> <phase> <decision> <why> <evidence> <result>` (or `scripts/log.sh`). It stamps `ts`, writes the header on first use, strips stray tabs/newlines, and prefixes any cell starting with `=`, `+`, `-`, or `@` with a single quote so a reviewer opening the log in a spreadsheet doesn't trigger formula execution. A bare `printf` appending a row works too, but mind those same bytes if cells come from generated or user-supplied text.

Log decision points and checkpoints, not every action: a fork chosen, a unit completed with its verification result, a pivot or revert with its trigger, a blocker surfaced, a gate fixed. For loop runs, one row per iteration. Skip the trivial and self-evident.

## Where it lives

On Antigravity, store the raw TSV log at `<appDataDir>/brain/<conversation-id>/decisions.tsv`. When presenting to the human or closing a run, render a companion markdown artifact `<appDataDir>/brain/<conversation-id>/decision_trail.md` with `ArtifactMetadata` displaying the formatted table, timeline charts, and cross-model review notes. Companion markdown artifacts (`decision_trail.md`) can link to referenced conversations using `[Session](conversation://<id>) (<id>)`.

By default the log is a working artifact, not committed to git. Keep it in the brain store (or `.audit/<task-slug>.tsv` in the repo when several efforts run at once). Most work doesn't need a committed trail; the local artifact keeps the run honest and inspectable.

Commit it to the repository only when the work is ambitious enough that an external reviewer needs the trail in the PR to trust the result (e.g., large cross-language ports or multi-week migrations).

A run is one agent conversation, including its later turns and any summary of it. A pickup, a replacement agent, or a new chat starts a new run. Every run (including the initial run that creates the file) writes an anchor row with phase `start` upon beginning work: phase `start`, decision `Run initiated`, why `Run pickup or new chat`, evidence `<agent-id>`, result `active`. When a run returns to a log in a later turn, it checks the log's most recent phase `start` row; if another run intervened, it logs a new phase `start` row before making new entries. Use phase `start` for nothing else.

## Rules

- One row is one decision or checkpoint. If it doesn't fit on one line, the decision isn't crisp yet.
- Append-only. A wrong call gets a new row that supersedes it. Never edit or delete history.
- Prefer evidence produced by committed scripts over hand-made one-offs, so a reviewer can re-run it (the **encode-lessons-in-structure** principle skill).

## Audit the log against the transcript

At the end of the run, before handing back, check the log told the truth. Read this run's transcript under `<appDataDir>/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` (or `~/.gemini/antigravity/brain/` / `~/.gemini/antigravity-ide/brain/`, or the path provided in context). Walk this run's rows against what actually happened. Each stretch of them begins at one of this run's `start` rows, or at the first data row (row 2, following the TSV header) if this run created the log, and ends at the next `start` row of another run:

- Check that every row maps to a real decision or action.
- Check that each row's evidence resolves and shows what the row claims (anchor rows with phase `start` and result `active`, and retraction rows with result `void`, are synthetic and exempt from file resolution).
- A fork, pivot, or abandoned approach that shaped the work but isn't logged is a gap. Add it.

Correct the log, not the story. The audit never edits or removes a row, even an invented one. When a row records a decision or action with wrong claims or broken evidence, add a row with phase `supersede`, decision `<corrected decision>`, why `Supersedes <target-ts>#<target-decision>: corrected during transcript audit`, evidence pointing to the valid artifact or transcript line, and result `updated`. When a row records an invented or hallucinated action that never happened, add a retraction row: phase `supersede`, decision `Retract row at <target-ts>#<target-decision>`, why `Invented action or not performed`, evidence `retract <target-ts>#<target-decision>`, result `void`. This audit does not check rows outside this run's stretches. If this run's own work shows one of them is wrong, supersede it like any wrong call.

## Cross-model review of the trail

Before handing back, you must spawn a subagent on a different model family from the one that did the work. Self-review is not a substitute; the point is fresh eyes you cannot bring yourself. The subagent reads the audit trail and the run's transcript, then flags what the user should pay attention to. Not a redo of the work, a scan for what's suboptimal or risky.

- Decisions logged with weak or absent evidence.
- Verification steps skipped or claimed without proof in the transcript.
- Choices that look risky in hindsight (premature, scope-creeping, papering over a symptom).
- Gaps the user would otherwise miss on a casual skim.

Every reply for a run that produced a trail ends with an "Attention" section. Lead with the reviewer's model on its own line (`reviewed by <model>`), then list each flag pointing to specific rows or moments. "No flags" is a valid value; the model name is not. The self-audit asks if the log told the truth; this asks what the user should still scrutinize even when it did.

## Reviewing the trail

Read top to bottom, follow the evidence pointers, spot-check. GitHub renders a committed TSV as a table; `column -s$'\t' -t decisions.tsv` renders it in a terminal. A row whose evidence doesn't resolve (except anchor `start` `active` rows and intentional `retract` `void` rows), or whose result is unverified, is the audit catching a gap.

## Composing this skill

Other skills route their audit trail here instead of inventing one. Reference it by name and let it own the format; don't restate the columns.
