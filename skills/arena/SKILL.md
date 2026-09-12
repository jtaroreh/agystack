---
name: arena
description: "Spawn N parallel candidates at the same task, pick a base, graft the strongest parts of the losers into it. Use for /arena, 'arena this', 'throw it in the arena', or when one attempt at a non-trivial artifact would lock in the wrong shape."
---

# Arena

Fan out N parallel attempts at the same task. Read every candidate end to end. Pick the strongest as the base. Graft the best ideas from the others into it. Verify the synthesized result.

## Start

Open a todolist with one entry per phase before launching anything. The arena runs autonomously and the list keeps phases from silently disappearing.

1. Frame
2. Fan out
3. Cross-judge
4. Pick
5. Graft
6. Verify

## Phase A: Frame

The N candidates will receive the same prompt, so the prompt is the contract. Get it right before spawning anything.

1. State the artifact each candidate is producing.
2. Derive the rubric. State what success looks like for *this* task, then turn it into 3-6 concrete gradeable criteria. Concrete: `Adds a --dry-run flag that skips writes`. Vague: `code is correct`. The rubric is the picker's tool in Phase D; candidates only see the task.
3. Pick the runners. Use `arena runners` from `~/.gemini/config/plugins/agystack/rules/agystack-models.md` when present. Otherwise default to a diverse panel across available tiers: `pro`, `flash`, `inherit`. Spawn more when the arena covers multiple design directions. Same model N times when the work is generation-bound rather than judgment-sensitive.
4. Assign output paths and workspaces. Each candidate runs in an isolated git branch/worktree via `Workspace: "branch"` (or writes to its own scratch path `<appDataDir>/brain/<conversation-id>/scratch/arena-<slug>/candidate-<n>/`). N candidates writing to the same path without isolation is shared mutable state and fails the **separate-before-serializing-shared-state** principle skill test.

## Phase B: Fan out

Spawn all N subagents in one turn using `invoke_subagent` with `Workspace: "branch"` (never simulate candidate outputs in the parent context), each with `TypeName: "self"` (or `"poteto-agent"`), the task, the path to the shared grounding, its own output path, and instructions to produce both the artifact and a short rationale.\n\nIn each candidate prompt, explicitly provide `{PARENT_CONVERSATION_ID}` and mandate that upon completion, the candidate MUST invoke `send_message` with `Recipient: "{PARENT_CONVERSATION_ID}"` and a summary of findings (mirroring `skills/interrogate/references/reviewer-prompt.md`) so the coordinator receives reactive wakeups without timing out.

The rationale is mandatory. Without it, the parent cannot tell whether a candidate's structure is principled or accidental, which makes Phase E grafting unreliable. Each rationale names the alternatives the candidate considered and what it rejected.

### Reactive Dispatch & Watchdog Protocol
1. **Turn 1 (Dispatch & Arm):** In the dispatch turn, launch candidate subagents via `invoke_subagent` and arm a single global watchdog deadline:
   `schedule(DurationSeconds: 300..600, Prompt="Watchdog: arena candidates timed out", TimerCondition: "never")`
2. **Turn 2 (Mechanical Yield):** Output an update message with ZERO tool calls (`tool_calls: []`). Busy polling via `manage_subagents(list)` is strictly prohibited.
3. **Partial Arrivals:** When a candidate reports via `send_message`, record its artifact and yield immediately with ZERO tool calls if other candidates remain running.
4. **Full Arrival:** When all N candidates have completed, cancel the watchdog timer via `manage_task(Action: "kill", TaskId: <timer_task_id>)` and proceed to Phase C.
5. **Timeout Fallback:** If the watchdog fires, inspect worker statuses via `manage_subagents(Action: "list")`, terminate hanging candidates, proceed with N-k candidates, and note dropouts in the synthesis record.

## Phase C: Cross-judge

After all Phase B candidates complete, choose one model from the `arena cross-judge pool` in `~/.gemini/config/plugins/agystack/rules/agystack-models.md` when present. Otherwise choose a distinct tier from `pro`, `flash`, `inherit`. Prefer a different model tier from the parent's. Spawn one judge subagent via `invoke_subagent` (`TypeName: "research"`, `Role: "Arena Cross-Judge"`) on that model. It sees the rubric and the candidates by path label, scores each criterion, and recommends a base with rationale. It runs in parallel with the parent's reading in Phase D, not with the candidates themselves. Spawning while candidates are still writing means the judge sees partial or empty outputs and reports them as dropouts.

## Phase D: Pick a base

Read every candidate end to end before picking. Skimming N candidates surfaces only the candidate whose surface looks most familiar.

Score each candidate against the rubric criterion by criterion, not on holistic feel. Compare against the cross-judge. Agreement on the base confirms the pick. Disagreement means one of you is biased or the rubric was ambiguous. Read both rationales before deciding.

Pick the base on which candidate a future maintainer can extend most easily without breaking invariants. Prefer the cleaner boundary or smaller surface area when two feel tied, per the Laziness Protocol.

Record the pick and the reason in a short synthesis note alongside the base artifact, including the cross-judge's verdict.

## Phase E: Graft

Walk each losing candidate once more and identify what is worth porting into the base. The signal is usually one or two things per candidate, not most of it.

Grafts must be folded in sequentially, one candidate at a time (`principle-sequence-verifiable-units`), per the **redesign-from-first-principles** principle skill. Don't paste mechanically or merge bulk patches across candidates. The result has to remain coherent under one mental model:
- For each graft: apply the candidate's minimal diff to the base and verify immediately against existing tests and the evaluation rubric.
- If verification passes, accept the graft and proceed to the next candidate. If it regresses or introduces destructive interference, revert immediately.

Record accepted grafts and rejected candidates individually, noting what was grafted from which candidate and why rejections occurred (`principle-sequence-verifiable-units`). The rejection notes are the highest-signal part of the record. Future readers learn from what you considered and dropped, not just what you kept.

When N candidates converge on the same shape, that is a strong agreement signal. Note the convergence in the record and ship the consensus shape. No graft is needed. When N candidates wildly diverge, Phase A was under-specified. Reframe and re-run rather than averaging the divergence.

## Phase F: Verify

The synthesized artifact has to hold up under the same scrutiny as any other output, per the **prove-it-works** principle skill. The arena does not earn you a pass.

If verification surfaces a problem the arena did not catch, either Phase A was wrong (re-frame and re-run) or one candidate caught it and you missed the graft (go back to Phase E). Don't paper over.

## Outputs

One synthesized artifact. One synthesis note alongside, naming the base, the grafts (with source candidate), the rejections, the dropouts if any, and the verification result. On Antigravity, publish the final synthesis package to `<appDataDir>/brain/<conversation-id>/arena_synthesis.md` with `ArtifactMetadata` and link to it in the chat reply. Candidate drafts stay under `<appDataDir>/brain/<conversation-id>/scratch/arena-<slug>/`.
