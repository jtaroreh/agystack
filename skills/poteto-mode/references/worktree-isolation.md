# Worktree Isolation Reference

Use native Antigravity workspace modes to isolate parallel subagents, swarms, and candidate generation runs.

## Invariant

Never let concurrent agents write to the same working directory. Shared mutable workspace state causes race conditions, corrupted index caches, and overwritten diffs.

## Host Workspace Modes

Antigravity manages workspace isolation natively via `Workspace` parameters in `invoke_subagent`.

- `Workspace: "branch"`. Spawns the subagent inside an isolated git branch and worktree. Use this for concurrent writers, swarms, candidate bakeoffs, and unverified diff exploration.
- `Workspace: "share"`. Spawns the subagent inside a shared branch environment with controlled concurrent access.
- `Workspace: "inherit"`. Spawns the subagent in the parent workspace directory. Use this for read-only workers or single sequential editors.

## Lifecycle

1. **Spawn.** Invoke `invoke_subagent` with `Workspace: "branch"`.
2. **Execute.** The subagent executes inside its isolated workspace root automatically.
3. **Inspect.** The coordinator reviews diffs and test results produced by the subagent.
4. **Teardown.** Teardown is host-managed on subagent exit via subagent management primitives.
