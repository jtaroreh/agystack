---
name: agystack
description: agystack's agentic engineering framework and rigor mode. Runs poteto-mode playbooks, isolated subagents, and cloud swarms. Use for /agystack, agystack, or rigorous engineering on Antigravity.
mode: true
icon: rocket
color: blue
reminder: New task? Playbook match or rigor needed -> apply /agystack or /poteto-mode. Casual turn or user opts out -> don't.
---

# agystack

agystack is an agentic engineering framework for Antigravity, executing under `poteto-mode` rigor.

When invoked as `/agystack`, this skill immediately activates the `poteto-mode` skill ([skills/poteto-mode/SKILL.md](../poteto-mode/SKILL.md)) and its full playbook engine.

## Non-negotiables

1. Read [skills/poteto-mode/SKILL.md](../poteto-mode/SKILL.md) in full, including its Non-negotiables and inline Principles.
2. Match the task to one of the twenty-three playbooks in `skills/poteto-mode/playbooks/`.
3. Follow the Subagent Delegation Invariant. Delegate all non-trivial code edits (> 50 lines, multi-file changes) to `poteto-agent` via `invoke_subagent`.
4. Output native Antigravity Artifacts in `<appDataDir>/brain/<conversation-id>/` (`implementation_plan.md`, `walkthrough.md`, `<topic>_report.md`).
5. Write unslopped prose framed for the consumer and the maintainer.
