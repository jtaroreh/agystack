---
name: interrogate
description: "Use for \"interrogate\", \"adversarial review\", \"multi-model review\", \"challenge this\", \"stress test this code\", \"find blind spots\", or \"tear this apart\". Adversaries try to break a change or design, and only findings proven by a run survive."
disable-model-invocation: true
---

# Interrogate

Adversaries try to break a change or a design. A finding survives only when a run proves it. Report the findings in `<appDataDir>/brain/<conversation-id>/adversarial_review.md` (`RequestFeedback: false`). Do not apply fixes.

## Frame

The scope is what the user names. Otherwise it is the branch diff from its merge base with the base branch, through the working tree. State the intent with the **in-your-own-words** skill, from the user's message, the commits, and the PR description. Ask the user via `ask_question` when the intent is unclear.

## Fan out

Run Phase A steps 3 and 4 and Phase B of the **arena** skill, with four changes:
- Read `interrogate reviewers` from `~/.gemini/config/plugins/agystack/agystack-models.md` (or `.agents/plugins/agystack/agystack-models.md`) in place of `arena runners`, defaulting across diverse Antigravity model tiers (`inherit`, `flash`, `pro`).
- Dispatch concurrent reviewers via `invoke_subagent` in one turn with `TypeName: "self"`, `Workspace: "branch"` (copying the scope's uncommitted changes into each branch worktree). Never simulate reviewer personas in-context. For deterministic scripted review sweeps across many files or packages, Antigravity's native `/run-workflow` (`parallel()`) may be used instead.
- Include `{PARENT_CONVERSATION_ID}` in every reviewer prompt and require each reviewer to call `send_message` with `Recipient: "{PARENT_CONVERSATION_ID}"` upon completion.
- In place of the arena task and rationale, give each adversary the scope, the intent, and this brief:

> Break this change. Prove each finding with a run against the real code, such as a failing test, a repro script, or command output that shows the wrong behavior. For a design or plan, run a prototype or probe the current tree. Keep repros in your own worktree. Report each finding with a title, the exact command, the output it printed, and the output the intent requires. Leave out anything you did not run. That covers style, naming, structure, and risks that need a future change to matter. No findings is a valid result. When done, call `send_message` with `Recipient: "{PARENT_CONVERSATION_ID}"` and your structured findings.

### Reactive Dispatch and Watchdog Protocol

1. **Dispatch and arm.** Launch all reviewer subagents via `invoke_subagent` in one turn and arm one unconditional watchdog deadline:
   `schedule(DurationSeconds: 300..600, Prompt="Watchdog: interrogate reviewers timed out", TimerCondition: "never")`
2. **Mechanical yield.** Yield immediately by replying with ZERO tools (`tool_calls: []`). Never poll with `manage_subagents(list)`.
3. **Partial arrivals.** Record each arriving `send_message` report and yield with zero tool calls if other reviewers remain active.
4. **Full arrival.** Cancel the watchdog timer with `manage_task(Action: "kill", TaskId: <timer_task_id>)` and move to Verify.
5. **Timeout fallback.** If the watchdog fires, inspect statuses with `manage_subagents(Action: "list")`, terminate hanging reviewers with `manage_subagents(Action: "kill", ConversationIds: [<id>])`, and verify all surviving reports.

## Verify

Verify each finding per arena Phase F by rerunning its exact command via `run_command`. Keep a finding only when the output shows the failure and the failure breaks the intent. Drop unproven claims, style or naming nitpicks, and repros that fail to trigger. Merge findings that share a root cause.

Skip arena Phases C, D, and E. Adversaries find different failures, so the verdict keeps every verified finding rather than picking one adversary's list.

## Output

Write `<appDataDir>/brain/<conversation-id>/adversarial_review.md` and link it in your reply with:

- **Intent**: the restatement.
- **Findings**: for each verified finding, the command, its output, how it breaks the intent, and the adversaries that found it. Say "no verified findings" when none survive.
- **Dropped**: for each adversary, the count of dropped findings and why.
