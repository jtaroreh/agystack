---
name: interrogate
description: "Use for \"interrogate\", \"adversarial review\", \"multi-model review\", \"challenge this\", \"stress test this code\", \"find blind spots\", or \"tear this apart\". Multiple LLM reviewers challenge changes from independent angles."
---

# Interrogate

Spawn one reviewer per configured model to adversarially review code changes. Each model gets the same prompt and rubric. The adversarial signal comes from model tier and reasoning depth diversity across thinking budgets (`pro`, `flash`, `inherit`), testing code from different reasoning depths and variance rather than assigned personas. Models differ in blind spots, priors, and reasoning patterns. Agreement across models is high-confidence signal; lone-model findings are worth reading but lower confidence.

The deliverable is a synthesized verdict. Do NOT auto-apply changes.

## Step 1, Determine Scope

Identify what to review from context:

- If the user points at specific files or a diff, use that
- If on a feature branch, run `git diff main...HEAD` (or the appropriate base branch) for the full changeset
- If the user's message references recent work, gather the relevant files

Package the diff (or file contents) plus any surrounding context files the reviewers need to understand the code.

## Step 2, State the Intent

Before spawning reviewers, state the intent explicitly. What is this code trying to accomplish? Derive this from:

- The user's message
- Commit messages
- PR description if one exists
- The code itself

Write one clear paragraph. Reviewers challenge whether the work achieves the intent well, not whether the intent itself is correct. If you're unsure about the intent, ask the user before proceeding.

## Step 3, Spawn Reviewers

Launch all reviewers in a single turn using native `invoke_subagent`. You MUST invoke distinct background subagents; simulating multiple reviewer personas in-context within the parent turn is strictly forbidden. The value of interrogation comes entirely from independent, uninfluenced model evaluation.

Use the `interrogate reviewers` list from `~/.gemini/config/plugins/agystack/rules/agystack-models.md` when present, one reviewer per entry; otherwise use the table defaults.

| Subagent | Default model tier |
|---|---|
| Reviewer A | `pro` |
| Reviewer B | `flash` |
| Reviewer C | `inherit` |

For each reviewer:
- `TypeName`: `research` (or `self`)
- `Role`: `Adversarial Reviewer (<model tier>)`
- `Model`: the configured `interrogate reviewers` entry (or `pro`, `flash`, `inherit`)
- `Workspace`: `inherit`

If a model tier is rejected when you try to spawn the subagent, pick the closest available model tier (`pro`, `flash`, `inherit`), spawn with the valid tier, and open a separate PR to update the configured value or default table. Do not block the review on the slug issue. If the configured value is `inherit` or `auto`, omit `Model` or pass `"inherit"`.

Read `references/reviewer-prompt.md` and fill in the template with:
1. The stated intent
2. The diff or file contents
3. The review rubric from `references/rubric.md`
4. The code-quality lens from `references/code-quality-review.md`
5. The active conversation ID for `{PARENT_CONVERSATION_ID}` (retrieved from system context)

The same filled template goes to all reviewers, so every model applies the code-quality lens.

### Reactive Dispatch & Watchdog Protocol
1. **Turn 1 (Dispatch & Arm Watchdog):** In the same turn, dispatch all reviewers via `invoke_subagent` and arm a single unconditional watchdog deadline:
   `schedule(DurationSeconds: 300..600, Prompt="Watchdog: adversarial reviewers timed out", TimerCondition: "never")`
2. **Turn 2 (Yield Turn):** Immediately output a concise status update to the user and call ZERO tools (`tool_calls: []`). Never run busy-wait polling loops (`manage_subagents(list)`) or read child transcripts.
3. **Partial Wakeups:** When a subagent calls `send_message`, Antigravity reactively resumes the coordinator. Record the reviewer's findings. If reviewers remain pending, yield immediately with ZERO tools (`tool_calls: []`). Do NOT cancel or alter the watchdog timer.
4. **Full Arrival:** When all reviewers have delivered their findings via `send_message`, cancel the watchdog timer via `manage_task(Action: "kill", TaskId: <timer_task_id>)` and proceed directly to Step 4 (Synthesize).
5. **Watchdog Timeout Fallback:** If the watchdog timer fires before all reviewers report, call `manage_subagents(Action: "list")` to inspect status. Terminate non-responsive workers (`manage_subagents(Action: "kill")`) and proceed to synthesize with the surviving results, noting dropouts.

## Step 4, Synthesize

As results come back, build a unified picture:

1. **Parse all findings** from the reviewers
2. **Identify consensus**. Findings raised by 2+ models independently are highest signal.
3. **Identify lone-model findings**. Still worth reading, but weight accordingly.
4. **Deduplicate**. Different models may describe the same issue differently. Merge these and note which models raised it.
5. **Note disagreements**. If one model flags something and another explicitly says the opposite, that's useful context for the verdict.

## Step 5, Lead Judgment

You are the lead reviewer, a pragmatic senior engineer, not a neutral aggregator.

Read `references/lead-judgment.md` for the full framework. Reviewers only see a slice of the codebase. You have the full context (the goal, the constraints, the timeline, which tradeoffs were already considered). Use that context aggressively.

Categorize every finding using these buckets:

- **Act on**. Real issues affecting correctness, security, or maintainability given the actual goals. These would block a real PR.
- **Consider**. Legitimate points, but you're not sure they outweigh the cost of addressing them right now. Worth the user's attention.
- **Noted**. Technically valid but not actionable. Context-dependent, premature optimization, or low-impact given the current stage.
- **Dismissed**. Wrong, nitpicky, or missing context. Brief explanation why.

For each finding, include:
- Which model(s) raised it
- The category (act on / consider / noted / dismissed)
- A one-line rationale for the categorization

## Output Format

For multi-model reviews, write the complete categorized findings, dismissed rationales, and agreement map to an Antigravity artifact `<appDataDir>/brain/<conversation-id>/adversarial_review.md` (or `review_verdict.md`) with `ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: false }`. In the chat reply, present an executive summary (Intent, Reviewers, Act On items) and link directly to the artifact.

Present the verdict in this structure:

### Intent
> [The stated intent paragraph from Step 2]

### Reviewers
- Reviewer [label]: [model name], [N findings] (one bullet per reviewer)

### Act On
[Findings that should be addressed. For each: description, which models raised it, why it matters.]

### Consider
[Findings worth thinking about. For each: description, which models raised it, tradeoff involved.]

### Noted
[Valid but low-priority. Brief list.]

### Dismissed
[Rejected findings with brief rationale. This shows the user what was filtered out and why, so they can override your judgment if they disagree.]

### Agreement Map
[Where did models agree, where did they diverge, and what does the pattern of agreement/disagreement tell us?]
