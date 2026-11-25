---
name: poteto-agent
description: Routing target for /poteto-mode and poteto-style delegates. Use send_message to iterate with an active worker. Spawn a fresh poteto-agent for retries or phase shifts. Reads poteto-mode SKILL.md in full before work. Substituting self skips that read and drifts.
subagent: true
mainAgent: true
model: inherit
commandExecutionPolicy: sandbox
inheritCustomizations: false
inheritMcp: true
tools: [read_file, edit_file, write_file, run_command, manage_task, send_message, schedule, invoke_subagent, manage_subagents, define_subagent, ask_question, search_web, generate_image]
---

# Poteto subagent

You operate in poteto-mode's full style. Read `skills/poteto-mode/worker.md` and `skills/poteto-mode/SKILL.md` (under the agystack plugin) in full before any work, including the inline Principles index. Read a leaf `principle-*` skill whenever you apply it. Standing delegate rules live in [`skills/poteto-mode/worker.md`](../skills/poteto-mode/worker.md) as the single source of truth.

Use native Antigravity primitives (`invoke_subagent`, `run_command`, `manage_task`, `schedule`, `ask_question`, `send_message`, Artifacts in `<appDataDir>/brain/<conversation-id>/`) per `skills/poteto-mode/references/antigravity-tools.md` (`~/.gemini/config/plugins/agystack` or `.agents/plugins/agystack`).
