---
name: loop
description: "Run iterative verification hillclimbs against a concrete test command using Antigravity reactive scheduling. Use for /loop, 'loop until green', or automated hypothesis testing with a verification predicate."
---

# Loop

Run iterative verification loops and hillclimbs on Antigravity without manual polling.

## How It Works

The `/loop` skill drives discrete edits against a verification command (`--verify "<command>"`).
It maintains iteration state in `<appDataDir>/brain/<conversation-id>/scratch/loop/state.json`.
It uses the native Antigravity `schedule` tool to manage reactive iteration delays.

For open-ended autonomous tasks where no single bash exit code determines completion, use the `/goal` slash command or the Autonomous run playbook instead.
For standing background jobs or periodic status checks, use the `schedule` tool directly.

## Invocation

Format:
`/loop <goal> --verify "<command>" [--max-iterations N] [--interval S]`

Default values:
- `max-iterations`: 10
- `interval`: 30 seconds

## State Machine

The loop maintains durability through structured state transitions.
The file `state.json` records git revision, active task ID, iteration counters, and status.
During execution, state.json records git revision for each step.

1. **Frame.** Read target files. Generate baseline evidence by executing the verify command via `run_command` or bash. Record initial state in `<appDataDir>/brain/<conversation-id>/scratch/loop/state.json`. Record the current `git_revision` from `git rev-parse HEAD`.
2. **Step.** Apply one discrete edit or hypothesis. Update `git_revision` if a commit or checkpoint is created.
3. **Verify.** Run the verification command. Capture stdout, stderr, and exit code.
4. **Decide.**
   - When verify passes, log success, mark status `CONVERGED`, and finish.
   - When verify fails and iterations remain, record the delta, revert regressions if hillclimbing, and set a reactive timer using `schedule(DurationSeconds=interval, Prompt="Loop iteration wakeup for <goal>", TimerCondition="never")`. Update `state.json` with the returned `task_id` and next iteration count.
   - Stop calling tools immediately after scheduling to end the turn and let the timer fire.
   - When budget is reached, mark status `EXHAUSTED` and hand back to the user with a summary table.
5. **Wakeup.** On schedule trigger, the agent reactively wakes up, reads `state.json`, and executes the next step.

## Crash and Restart Recovery

The loop recovers gracefully across crashes, context compactions, or server restarts:

1. **State restoration.** On session startup or resume, read `<appDataDir>/brain/<conversation-id>/scratch/loop/state.json`.
2. **Revision verification.** Compare `git rev-parse HEAD` with the recorded `git_revision`. If the working tree has drifted, reset to the recorded revision before proceeding.
3. **Deduplication.** Inspect the recorded `task_id` in `state.json`. Use `manage_task` with `Action: "list"` or `Action: "status"` to inspect pending scheduled tasks.
4. **Orphan cleanup.** Kill stale or orphaned timers using `manage_task` with `Action: "kill"` to prevent duplicate wakeups.
5. **Execution resumption.** Resume iteration from the restored state machine position without repeating finished work.

## Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `goal` | Description of the desired state | Required |
| `--verify` | Command that exits 0 on success | Required |
| `--max-iterations` | Maximum number of attempts | 10 |
| `--interval` | Delay between iterations in seconds | 30 |
