---
name: loop
description: "Run iterative verification hillclimbs against a concrete test command using Antigravity reactive scheduling. Use for /loop, 'loop until green', or automated hypothesis testing with a verification predicate."
---

# Loop

Run iterative verification loops and hillclimbs on Antigravity without manual polling.

## How It Works

The `/loop` skill drives discrete edits against a verification command (`--verify "<command>"`). It maintains iteration state in `<appDataDir>/brain/<conversation-id>/scratch/loop/state.json` and uses the native Antigravity `schedule` tool to manage reactive iteration delays.

For open-ended autonomous tasks where no single bash exit code determines completion, use the `/goal` slash command or the Autonomous run playbook instead. For standing background jobs or periodic status checks, use the `schedule` tool directly.

## Invocation

Format:
`/loop <goal> --verify "<command>" [--max-iterations N] [--interval S]`

Default values:
- `max-iterations`: 10
- `interval`: 30 seconds

## State Machine

1. **Frame.** Read target files. Generate baseline evidence by executing the verify command via `run_command` or bash. Record the state in `<appDataDir>/brain/<conversation-id>/scratch/loop/state.json`.
2. **Step.** Apply one discrete edit or hypothesis.
3. **Verify.** Run the verification command. Capture stdout, stderr, and exit code.
4. **Decide.**
   - If verify passes: log success, mark state `CONVERGED`, and finish.
   - If verify fails and iterations remain: record the delta, revert regressions if hillclimbing, and set a reactive timer using `schedule(DurationSeconds=interval, Prompt="Loop iteration wakeup for <goal>", TimerCondition="never")`.
   - **IMPORTANT**: Calling `schedule` returns immediately and does not pause execution. You MUST stop calling tools immediately after scheduling to end your turn and let the timer fire.
   - If budget is reached: mark `EXHAUSTED` and hand back to the user with a summary table.
5. **Wakeup.** On schedule trigger, the agent is reactively woken up, reads `state.json`, and executes the next step.

## Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `goal` | Description of the desired state | Required |
| `--verify` | Command that exits 0 on success | Required |
| `--max-iterations` | Maximum number of attempts | 10 |
| `--interval` | Delay between iterations in seconds | 30 |
