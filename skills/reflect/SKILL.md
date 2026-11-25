---
name: reflect
description: Spawn three parallel review subagents over the active transcript, surface learnings, and route each to a concrete edit on an existing skill. Use when the user says reflect.
disable-model-invocation: true
---

# Reflect

Mine the current conversation for durable learnings and route approved findings into skill edits.

Skip when the conversation is trivial, off-topic, or already covered by an existing skill the parent followed. One-offs are not learnings.

## 1. Locate the active transcript

Read the active session transcript at `<appDataDir>/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` (falling back to `transcript_full.jsonl` in the same brain folder). If the path is unavailable, write a tight digest of the session and pass that instead.

## 2. Spawn three reviewers in parallel

Dispatch three concurrent read-only subagents in one `invoke_subagent` turn (`TypeName: "self"` or `"poteto-agent"`, `Workspace: "inherit"`). Pass each prompt template verbatim with the transcript path or digest substituted; reviewers return findings in their response and never edit files.

| Lens | Model role | Prompt template |
|---|---|---|
| Judgment | `reflect judgment` (default `pro`) | `references/judgment-reviewer.md` |
| Tooling | `reflect tooling` (default `pro`) | `references/tooling-reviewer.md` |
| Divergent | `reflect judgment` (default `pro`) | `references/divergent-reviewer.md` |

## 3. Synthesize

Spawn one subagent (`TypeName: "self"` or `"poteto-agent"`, `Role: "Reflect Synthesizer"`, `Model`: configured `reflect judgment` model, default `pro`, `Workspace: "inherit"`) using `references/synthesizer.md` verbatim with all three reviewer outputs inlined. It spot-verifies citations and returns structured **Accepted**, **Rejected**, and **Backlog** lists.

## 4. Structural enforcement check

Review the synthesizer's **Accepted** list before presenting. Move any item better enforced by a lint rule, script, metadata flag, or runtime check to **Backlog** per **principle-encode-lessons-in-structure**.

## 5. Approve and apply

Present the full **Accepted** (problem, proposal, target skill, destination), **Rejected** (reason), and **Backlog** lists, then wait for explicit user approval before editing any skill. Backlog items may be filed to the team tracker directly.

**Read-only plugin guard.** Never edit an installed plugin copy under `~/.gemini/config/plugins/` directly. Before approval, show the writable destination: `.agents/skills/<skill>/` (project-local) or `~/.gemini/config/skills/<skill>/` (user-level). After approval, copy the skill folder there and edit the copy. Never open a PR or push.

For each approved item, follow its routing (`tune description: <skill>`, existing-skill edit through `/unslop`, or `new skill: <kebab-name>` under `.agents/skills/<kebab-name>/SKILL.md`), validate touched skills if a validator is available, and summarize applied edits, new skills, backlog items, and dropped findings in a short list.
