# Worktree Isolation Reference

Use worktrees to isolate parallel subagents, swarms, and candidate generation runs.

## Invariant

Never let concurrent agents write to the same working directory. Shared mutable workspace state causes race conditions, corrupted index caches, and overwritten diffs.

## Directory Layout

All ephemeral subagent worktrees live under:
`.agents/worktrees/<task-id>`

Each worktree tracks a dedicated branch:
`agent/<task-id>`

## Lifecycle

1. **Spawn.** Run `bash skills/poteto-mode/scripts/worktree-spawn.sh create <task-id>`.
2. **Execute.** Point the subagent to the absolute path returned by the script.
3. **Inspect.** The coordinator runs tests or reads diffs inside the target path.
4. **Teardown.** Run `bash skills/poteto-mode/scripts/worktree-spawn.sh cleanup <task-id> --force`.
