---
name: interrogate
description: "Use for \"interrogate\", \"adversarial review\", \"multi-model review\", \"challenge this\", \"stress test this code\", \"find blind spots\", or \"tear this apart\". Multiple LLM reviewers challenge changes from independent angles."
---

# Interrogate

Spawn independent adversarial reviewers across configured model tiers to break a change or design. Multi-model consensus is high-confidence signal; lone-model findings are lower-confidence but still evaluated. The deliverable is a verdict in `<appDataDir>/brain/<conversation-id>/adversarial_review.md` (`RequestFeedback: false`). Do not auto-apply edits.

## Step 1. Frame Scope and Intent

Identify target files or the full branch diff from merge base through the working tree (`git diff main...HEAD`). State what the change intends to accomplish from the user request, commits, and PR context. Reviewers test whether the code satisfies this intent without regressions.

## Step 2. Dispatch Reviewers in Isolated Branches

Launch all reviewers in a single turn via `invoke_subagent`. Never simulate reviewer personas in-context. Read `interrogate reviewers` from `~/.gemini/config/plugins/agystack/agystack-models.md` (or `.agents/plugins/agystack/agystack-models.md`), defaulting to `inherit`, `flash`, and `pro` (translating Gemini 4 effort-suffixed entries to `pro`, `inherit`, `flash`, falling back to `inherit` on single-tier accounts or HTTP 429).

For each reviewer:
- `TypeName`: `self` (or `research` for read-only design review)
- `Role`: `Adversarial Reviewer (<model tier>)`
- `Model`: configured tier
- `Workspace`: `"branch"` (copying uncommitted scope changes into each branch worktree so repros stay isolated)

Give each reviewer the scope, stated intent, `{PARENT_CONVERSATION_ID}`, and four concrete audit lenses:
- **Idempotency & Crash Recovery.** Re-execution safety, retries, and partial-failure reconciliation.
- **Concurrency & Races.** Shared mutable state serialization, lock invariants, and TOCTOU hazards.
- **Boundary Discipline.** External input validation at system boundaries versus internal type trust.
- **Contract vs Symptom.** Root-cause fixes versus shallow guard clauses or dual legacy paths.

Require each reviewer to prove every behavioral defect with an executable repro command (failing test, script, or shell one-liner) run in its own worktree, reporting title, exact command, observed output, and expected output. High-severity non-deterministic or structural defects that cannot be deterministically reproduced (such as race windows or crash-recovery gaps) may be reported only under the `unverified-structural` tag with exact `file:line` and concrete failure mechanism. Style, naming, and subjective nitpicks are banned. Require every reviewer to report via `send_message` with `Recipient: "{PARENT_CONVERSATION_ID}"`.

### Reactive Dispatch and Watchdog Protocol

1. **Dispatch and arm.** Launch all reviewers in one turn and arm one unconditional watchdog:
   `schedule(DurationSeconds: 300..600, Prompt="Watchdog: interrogate reviewers timed out", TimerCondition: "never")`
2. **Yield turn.** Output a brief status and call ZERO tools (`tool_calls: []`). Never poll with `manage_subagents(list)`.
3. **Partial wakeups.** On each arriving `send_message`, record findings and yield with ZERO tools while reviewers remain pending.
4. **Full arrival.** Cancel the timer with `manage_task(Action: "kill", TaskId: <timer_task_id>)` and proceed to Step 3.
5. **Watchdog timeout fallback.** If the watchdog fires, inspect `manage_subagents(Action: "list")`, kill unresponsive workers via `manage_subagents(Action: "kill", ConversationIds: [<id>])`, and proceed with `N-1` or surviving reports, noting any dropout in the verdict.

## Step 3. Proof-by-Run Gate and Synthesis

- **Verified repro rerun.** Rerun every behavioral repro command yourself via `run_command`. Mark a finding `verified` only when the rerun reproduces the failure against the codebase and breaks the stated intent. Drop findings whose repro fails to trigger or lacks an executable command.
- **Unverified-structural exception.** Keep `unverified-structural` findings strictly separate from `verified` repros, accepting them only for high-severity structural or concurrency defects backed by exact `file:line` and a concrete execution path. Drop all style nitpicks, hypotheticals blocked upstream, and "I would have done it differently" preferences.
- **Consensus and agreement map.** Deduplicate overlapping issues, highlight multi-model consensus, isolate lone-model findings, and record direct disagreements.

## Step 4. Lead Judgment and Verdict

Classify surviving findings with pragmatic engineering judgment:
- **Act on.** Critical defects (`verified` repros or high-severity `unverified-structural` flaws) blocking landing.
- **Consider.** Valid architectural or behavioral tradeoffs worth operator attention.
- **Noted.** Low-impact or context-dependent observations.
- **Dismissed.** Failed repros, false positives, nitpicks, or missing-context claims, each with a brief rationale.

Write `<appDataDir>/brain/<conversation-id>/adversarial_review.md` (`RequestFeedback: false`) and link it in chat with: **Intent**, **Reviewers** (model, counts, dropouts), **Act on**, **Consider**, **Noted**, **Dismissed**, and **Agreement Map**.
