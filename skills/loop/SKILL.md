---
name: loop
description: "Run autonomous iterations against a goal and a verification command using Antigravity reactive scheduling. Use for /loop, 'loop until green', or multi-step autonomous tasks."
disable-model-invocation: true
---

# Loop

Run iterative autonomous work loops on Antigravity without manual polling.

## How It Works

The `/loop` skill wraps Antigravity's `schedule` tool. It maintains execution state in the brain scratch directory and drives iterations until the verification check passes or the iteration budget runs out.

## Invocation

Format:
`/loop <goal> --verify "<command>" [--max-iterations N] [--interval S]`

Default values:
- `max-iterations`: 10
- `interval`: 30 seconds

## State Machine

1. **Frame.** Read target files. Generate baseline evidence by executing the verify command via `manage_task` or bash. Record the state in `<appDataDir>/brain/<conversation-id>/scratch/loop/state.json`.
2. **Step.** Apply one discrete edit or hypothesis.
3. **Verify.** Run the verification command. Capture stdout, stderr, and exit code.
4. **Decide.**
   - If verify passes: log success, mark state `CONVERGED`, and finish.
   - If verify fails and iterations remain: record the delta, revert regressions if hillclimbing, and set a reactive timer using `schedule`.
   - If budget is reached: mark `EXHAUSTED` and hand back to the user with a summary table.
5. **Wakeup.** On schedule trigger, the agent reads `state.json` and executes the next step.

## Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `goal` | Description of the desired state | Required |
| `--verify` | Command that exits 0 on success | Required |
| `--max-iterations` | Maximum number of attempts | 10 |
| `--interval` | Delay between iterations in seconds | 30 |
