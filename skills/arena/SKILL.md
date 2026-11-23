---
name: arena
description: "Spawn N parallel candidates at the same task, pick a base, graft the strongest parts of the losers into it. Use for /arena, 'arena this', 'throw it in the arena', or when one attempt at a non-trivial artifact would lock in the wrong shape."
---

# Arena

Fan out N parallel attempts at the same task. Read every candidate end to end, pick the strongest base, graft the best ideas from other candidates, and verify the synthesized result.

## Start

Open a todolist tracking the operational phases:
1. Frame
2. Fan out
3. Cross-judge
4. Pick
5. Graft
6. Verify

## Phase A: Frame

Every candidate receives the same prompt, so the prompt is the contract.

1. **Artifact.** Define the target output each candidate produces.
2. **Rubric.** Formulate 3 to 6 concrete, gradeable criteria for this task, such as `Adds a --dry-run flag that skips writes`. Candidates see only the task. The picker uses the rubric in Phase D.
3. **Runners.** Read `arena runners` from `~/.gemini/config/plugins/agystack/agystack-models.md` (or `.agents/plugins/agystack/agystack-models.md`), defaulting across `inherit`, `flash`, and `pro`. An `inherit` or `auto` entry runs on the parent session's model (`Model: "inherit"`). If `invoke_subagent` rejects a tier or slot, use the nearest valid tier or drop the seat, keep at least two runners, and note the fallback. Repeat one model tier when the work is generation-bound rather than judgment-sensitive.
4. **Workspaces.** Assign isolated workspaces via `Workspace: "branch"` or scratch paths (`<appDataDir>/brain/<conversation-id>/scratch/arena-<slug>/candidate-<n>/`) per **principle-separate-before-serializing-shared-state**.

## Phase B: Fan out

Spawn all N subagents in one turn via `invoke_subagent` with `Workspace: "branch"` (never simulate in-context), `TypeName: "self"` (or `"poteto-agent"`), the task, grounding path, output path, and instructions to produce the artifact plus a short rationale naming alternatives considered and rejected. If a candidate produces no output or drops out, proceed with `N-1` and record the dropout.

Provide `{PARENT_CONVERSATION_ID}` in each prompt. Candidates MUST invoke `send_message` with `Recipient: "{PARENT_CONVERSATION_ID}"` upon completion to wake the coordinator reactively.

### Reactive Dispatch & Watchdog Protocol

1. **Turn 1 (Dispatch and Arm).** Launch candidate subagents via `invoke_subagent` and arm a single watchdog deadline:
   `schedule(DurationSeconds: 300..600, Prompt="Watchdog: arena candidates timed out", TimerCondition: "never")`
2. **Turn 2 (Mechanical Yield).** Output an update message with ZERO tool calls (`tool_calls: []`). Busy polling via `manage_subagents(list)` is prohibited.
3. **Partial Arrivals.** When a candidate reports via `send_message`, record its artifact and yield immediately with ZERO tool calls if others remain running.
4. **Full Arrival.** When all N candidates report, cancel the watchdog timer via `manage_task(Action: "kill", TaskId: <timer_task_id>)` and proceed to Phase C.
5. **Timeout Fallback.** If the watchdog fires, inspect worker statuses via `manage_subagents(Action: "list")`, terminate hanging candidates (`manage_subagents(Action: "kill", ConversationIds: [<id>])`), and proceed with surviving outputs.

## Phase C: Cross-judge

After Phase B finishes, spawn one judge subagent via `invoke_subagent` (`TypeName: "research"`, `Role: "Arena Cross-Judge"`). Read `arena cross-judge pool` from `~/.gemini/config/plugins/agystack/agystack-models.md` (default `inherit, flash, pro`). Enforce model-tier and family diversity. Select a model from a different family than the parent session when cross-family models are configured, and pick a distinct Antigravity tier (`pro`, `flash`, or `inherit`) from the candidate draft majority (for example, `Model: "pro"` when candidates drafted on `flash`). If the parent model is unknown or `invoke_subagent` rejects a pool entry, fall back to the next pool entry or skip Phase C, and record whether the tier and family diversity check ran or was skipped.

Pass `{PARENT_CONVERSATION_ID}` so the judge wakes the coordinator via `send_message`, using the same `TimerCondition: "never"` watchdog and ZERO tool calls yield while waiting. While you read in Phase D, the judge scores each candidate by path label on every rubric criterion and recommends a base with rationale.

## Phase D: Pick a base

Read every candidate end to end before picking. Score each against the rubric criterion by criterion rather than on holistic feel, and compare with the cross-judge verdict when Phase C ran. Agreement confirms the pick. Disagreement means one of you is biased or the rubric was ambiguous, so read both rationales before deciding.

Pick the base a future maintainer can extend most easily without breaking invariants. When two feel tied, prefer the cleaner boundary or smaller API per **principle-laziness-protocol**.

## Phase E: Graft

First apply the convergence-vs-divergence gate:

- **Convergence.** If candidates converge on one shape, that is strong agreement. Record the convergence and ship the consensus shape with no graft needed.
- **Divergence.** If candidates wildly diverge, Phase A was under-specified. Reframe the artifact and rubric and re-run Phase B instead of averaging the divergence.

When candidates share a clear base with distinct wins elsewhere, walk each losing candidate once more for what is worth porting (usually one or two ideas per candidate, not most of it). Fold each graft into the base sequentially (**principle-sequence-verifiable-units**) and by hand per **principle-redesign-from-first-principles**:

- Apply one minimal diff to the base, verify immediately against tests and rubric criteria, and revert on regression.
- Record accepted grafts, source candidates, and explicit rejection reasons.

## Phase F: Verify

Verify the synthesized artifact per **principle-prove-it-works**. If verification finds a problem the arena missed, either Phase A was wrong (reframe and re-run) or a candidate caught it and you missed the graft (return to Phase E). Do not paper over it.

## Outputs

Publish the final synthesis package to `<appDataDir>/brain/<conversation-id>/arena_synthesis.md` with `ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: false }` and link to it in chat. Record the base choice and rationale, cross-judge verdict (or why Phase C skipped it, plus tier and family diversity status), convergence or divergence outcomes, any dropouts, each graft with its source candidate, rejected ideas with reasons, and the verification result. Candidate drafts remain under `<appDataDir>/brain/<conversation-id>/scratch/arena-<slug>/`.
