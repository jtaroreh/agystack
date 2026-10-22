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

1. **Artifact.** Define the target output each candidate must produce.
2. **Rubric.** Formulate 3-6 concrete, gradeable criteria (e.g. `Adds a --dry-run flag that skips writes`).
3. **Runners.** Use `arena runners` from `~/.gemini/config/plugins/agystack/rules/agystack-models.md` if configured, or default across available tiers: `pro`, `flash`, `inherit`.
4. **Workspaces.** Assign isolated workspaces via `Workspace: "branch"` or scratch paths (`<appDataDir>/brain/<conversation-id>/scratch/arena-<slug>/candidate-<n>/`) per **principle-separate-before-serializing-shared-state**.

## Phase B: Fan out

Spawn all N subagents in one turn via `invoke_subagent` with `Workspace: "branch"` (never simulate in-context), `TypeName: "self"` (or `"poteto-agent"`), the task, grounding, output path, and instructions for producing the artifact and rationale.

Provide `{PARENT_CONVERSATION_ID}` in each prompt. Candidates MUST invoke `send_message` with `Recipient: "{PARENT_CONVERSATION_ID}"` upon completion to wake the coordinator reactively.

### Reactive Dispatch & Watchdog Protocol

1. **Turn 1 (Dispatch & Arm):** Launch candidate subagents via `invoke_subagent` and arm a single watchdog deadline:
   `schedule(DurationSeconds: 300..600, Prompt="Watchdog: arena candidates timed out", TimerCondition: "never")`
2. **Turn 2 (Mechanical Yield):** Output an update message with ZERO tool calls (`tool_calls: []`). Busy polling via `manage_subagents(list)` is prohibited.
3. **Partial Arrivals:** When a candidate reports via `send_message`, record its artifact and yield immediately with ZERO tool calls if others remain running.
4. **Full Arrival:** When all N candidates report, cancel the watchdog timer via `manage_task(Action: "kill", TaskId: <timer_task_id>)` and proceed to Phase C.
5. **Timeout Fallback:** If the watchdog fires, inspect worker statuses via `manage_subagents(Action: "list")`, terminate hanging candidates (`manage_subagents(Action: "kill", ConversationIds: [<id>])`), and proceed with surviving outputs.

## Phase C: Cross-judge

Spawn one judge subagent via `invoke_subagent` (`TypeName: "research"`, `Role: "Arena Cross-Judge"`) on a distinct tier from `pro`, `flash`, `inherit`. The judge scores candidates against rubric criteria and recommends a base with rationale.

## Phase D: Pick a base

Read every candidate end to end. Score against the rubric, compare against the cross-judge, and select the base that is easiest to extend cleanly per the **principle-laziness-protocol**. Record the choice and rationale.

## Phase E: Graft

Port winning ideas from losing candidates sequentially (`principle-sequence-verifiable-units`) per **principle-redesign-from-first-principles**:
- Apply each candidate's minimal diff to the base and verify immediately against tests and rubric criteria.
- Accept verified grafts; revert immediately if regressions occur.
- Record accepted grafts and explicit rejection reasons.

## Phase F: Verify

Verify the synthesized artifact per **principle-prove-it-works**. If verification fails, re-frame the task or inspect missed candidate solutions.

## Outputs

Publish the final synthesis package to `<appDataDir>/brain/<conversation-id>/arena_synthesis.md` with `ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: false }` and link to it in chat. Candidate drafts remain under `<appDataDir>/brain/<conversation-id>/scratch/arena-<slug>/`.
