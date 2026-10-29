---
name: interrogate
description: "Use for \"interrogate\", \"adversarial review\", \"multi-model review\", \"challenge this\", \"stress test this code\", \"find blind spots\", or \"tear this apart\". Multiple LLM reviewers challenge changes from independent angles."
---

# Interrogate

Spawn one reviewer per configured model to adversarially review code changes. Independent models evaluate code across thinking budgets (`pro`, `flash`, `inherit`) to surface blind spots. Consensus across models represents high-confidence signal; lone-model findings are lower-confidence but worth noting.

The deliverable is a synthesized verdict. Do not auto-apply edits.

## Step 1. Determine Scope

Identify target files or changesets:
- Specific files or explicit diff from user prompt
- Full feature branch changeset via `git diff main...HEAD` (or appropriate base)

Package the diff and necessary surrounding context files.

## Step 2. State the Intent

State what the code attempts to accomplish based on commit messages, PR descriptions, and code context. Reviewers evaluate whether the implementation achieves this intent without regressions, not whether the intent itself is valid.

## Step 3. Spawn Reviewers

Launch all reviewers in a single turn using `invoke_subagent`. Simulating reviewer personas in-context is strictly prohibited.

Use the `interrogate reviewers` list from `~/.gemini/config/plugins/agystack/agystack-models.md` when present, or fall back to defaults:

| Subagent | Default model tier |
|---|---|
| Reviewer A | `pro` |
| Reviewer B | `flash` |
| Reviewer C | `inherit` |

For each reviewer:
- `TypeName`: `research` (or `self`)
- `Role`: `Adversarial Reviewer (<model tier>)`
- `Model`: configured tier (or `pro`, `flash`, `inherit`)
- `Workspace`: `inherit`

Fill `references/reviewer-prompt.md` with:
1. Stated intent
2. Diff or file contents
3. Rubric from `references/rubric.md`, explicitly injecting concrete audit categories:
   - **Idempotency & Crash Recovery:** Re-execution safety and partial failure state.
   - **Concurrency & Races:** Shared state serialization and lock invariants.
   - **Boundary Discipline:** System boundary validation vs internal type trust.
   - **Contract vs Symptom:** Root cause verification vs shallow guard clauses.
4. Code-quality lens from `references/code-quality-review.md`
5. System `{PARENT_CONVERSATION_ID}` for return routing

### Reactive Dispatch & Watchdog Protocol

1. **Turn 1 (Dispatch & Arm Watchdog):** Dispatch all reviewers via `invoke_subagent` and arm an unconditional watchdog deadline:
   `schedule(DurationSeconds: 300..600, Prompt="Watchdog: adversarial reviewers timed out", TimerCondition: "never")`
2. **Turn 2 (Yield Turn):** Output a status update and call ZERO tools (`tool_calls: []`). Never run busy-wait polling loops (`manage_subagents(list)`).
3. **Partial Wakeups:** On child `send_message`, record findings. If reviewers remain pending, yield immediately with ZERO tools (`tool_calls: []`). Do NOT alter the watchdog timer.
4. **Full Arrival:** When all reviewers report, cancel the timer via `manage_task(Action: "kill", TaskId: <timer_task_id>)` and proceed to Step 4.
5. **Watchdog Timeout Fallback:** If the watchdog fires, inspect `manage_subagents(Action: "list")`, terminate unresponsive workers (`manage_subagents(Action: "kill", ConversationIds: [<id>])`), and synthesize surviving findings.

## Step 4. Empirical Verification Gate & Synthesis

- Parse reviewer findings.
- **Empirical Gate:** Every actionable finding MUST include an executable repro command, curl call, test snippet, or shell one-liner proving the defect or reproducing the failure against the code. Speculative findings lacking executable reproduction are dropped.
- **Lead Verifier Rerun:** The coordinator reruns each repro command using `run_command`. If the command does not reproduce the failure against the codebase, the finding is dropped.
- Identify multi-model consensus (highest confidence).
- Isolate lone-model findings (lower confidence).
- Deduplicate overlapping issues.
- Highlight direct disagreements between models.

## Step 5. Lead Judgment

Classify surviving verified findings using the framework in `references/lead-judgment.md`:
- Filter out "Nitpick Gravity" and subjective preferences ("I would have done it differently").
- **Act on.** Critical defects in correctness, security, or maintainability with verified repros that block landing.
- **Consider.** Valid tradeoffs worth operator attention.
- **Noted.** Context-dependent, premature optimization, or low impact.
- **Dismissed.** Unreproduced findings, false positives, or missing context, with brief rationale.

## Output Format

Write the complete categorized review, rationales, and agreement map to `<appDataDir>/brain/<conversation-id>/adversarial_review.md` (or `review_verdict.md`) with `ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: false }`. Present an executive summary in chat and link to the artifact.

Structure:
- **Intent.** Stated goal of the change.
- **Reviewers.** One bullet per reviewer (model, finding count).
- **Act On.** Findings requiring resolution, with verified repro commands.
- **Consider.** Tradeoffs to evaluate.
- **Noted.** Low-priority items.
- **Dismissed.** Rejected findings with justification.
- **Agreement Map.** Consensus patterns and divergences.
