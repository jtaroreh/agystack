---
name: correct
description: "Find the mistakes agents keep repeating in this repo and make each one impossible. Try architecture first, then types, then a lint or hook whose error names the fix, then behavioral tests, and write docs last. Prove each check fails on a real past mistake. Use for /correct."
---

# Correct

The operator keeps correcting agents in this repo for the same mistakes. Change the repo so the next agent cannot make them.

Assume every contributor is an agent that sees only the files it opened, copies the nearest example, and takes the shortest path that compiles. Design the repo so a change that looks right from one file is right for the whole repo.

## Find the mistake classes

Read recent commits, reverts, review comments, `rules/AGENTS.md`, and comments that explain workarounds. Group mistakes into classes (`Constraint misunderstanding`, `Hallucinated APIs`, `Fragile patterns`, `Regressions`).

**A class counts once it has happened twice.**

## Fix each class at the highest level that works

1. **Eliminate it with architecture.** Make illegal states unrepresentable. Give each piece of state one owner and each task one supported way. Hide internals so the wrong import fails, replace hand-synced lists with one source of truth, and delete dead ways an agent would copy.
2. **Enforce it with types and static checks.** Make invalid invocations fail compilation. If bad code still compiles, add a lint or CI check whose error names the file, type, or function to use instead. If the pattern is already common, fail only when a change adds more.
3. **Add hooks, linters, and behavioral tests.** Enforce tool boundaries with Antigravity lifecycle hooks (`hooks.json.example`) and test observable behavior (`tests/`). Fix or delete any test that still passes when the behavior breaks, or fails when only internals change.
4. **Write docs or agent rules last, only for judgment calls.** Nothing fails automatically when an agent skips `rules/AGENTS.md` or skill prose.

## Fix and prove

1. Reproduce and fix the most frequent mistake classes now, one commit each.
2. **Prove each new check fails on a real past mistake.**
3. Run the same verification command locally and in CI (`make ci`).
4. **Exception expiry rule.** Exceptions go on the offending line with a reason, an expiry date, and a human's approval.

## Keep the rule-to-enforcer table

Pair each recurring rule with what enforces it automatically. When the operator corrects you, fix the mistake and add the rule. If the rule already existed without enforcement, that is a repeat, so enforce it at the highest level in the same change. Drop a rule once its mistake cannot happen.

| Rule or Invariant | Automated Enforcer | Verification |
| --- | --- | --- |
| Coordinator delegates code writes `> 50` lines to `poteto-agent` | `hooks.json.example` (`agystack-delegation` -> `pre_tool_delegation.py`) | `tests/test_hooks.py`, `tests/test_reactive_coordination_rules.py` |
| Destructive CLI commands (`rm`, trunk force-push, `drop database`) gated | `hooks.json.example` (`agystack-safety` -> `pre_tool_safety.py`) | `tests/test_hooks.py` |
| Deterministic post-write formatting on `.py`, `.ts`, `.tsx`, `.js`, and `.jsx` | `hooks.json.example` (`agystack-formatter` -> `post_tool_lint.py`) | `tests/test_hooks.py` |
| Zero Cursor leaks and `agystack-models.md` role key parity | Static scanner in `tests/test_antigravity_invariants.py` | `pytest -v tests/test_antigravity_invariants.py` |
| Reactive wakeup (`TimerCondition: "never"`, `ZERO tool calls`, `send_message`) | Contract assertions in `tests/test_reactive_coordination_rules.py` | `pytest -v tests/test_reactive_coordination_rules.py` |
| Skill catalog, principle count, and `/swarm` non-collision (`cloud-swarm`) | Catalog checks in `tests/test_skill_catalog.py` | `pytest -v tests/test_skill_catalog.py` |
| Agent `inheritCustomizations: false` and registered tool list | Frontmatter checks in `tests/test_agent_definitions.py` | `pytest -v tests/test_agent_definitions.py` |
| Manifest semver parity, hook paths, and zip hygiene | `tests/test_plugin_manifest.py` and `scripts/package-plugin.sh --test` | `make package-check` |

**Reply:** list each mistake class with its evidence, the hierarchy level you picked, and why a higher level did not work.
