# Set up agystack

In this page you install the plugin, pick which models agystack uses, and run your first task. Setup is one command plus a short conversation.

## Prerequisites

`bun` (version 1.0+) or `node` is required for PR babysitting (`watch-pr`) and multi-agent orchestration (`orch`).

## Install the plugin

Install agystack globally or for a specific workspace:

```bash
# Option A: Global installation (recommended - applies across all projects)
git clone https://github.com/jtaroreh/agystack ~/.gemini/config/plugins/agystack

# Option B: Workspace-only installation (applies to current project)
git clone https://github.com/jtaroreh/agystack .agents/plugins/agystack
```

Restart Antigravity or start a new chat so it discovers the plugin.

## Pick your models

Run:

```text
/setup-agystack
```

[`/setup-agystack`](../../skills/setup-agystack/SKILL.md) (or `/setup-pstack`) detects the models you have access to, shows you each role (code delegates, judgment, the review panels), and asks what you want. Answer the questions. It writes `~/.gemini/config/plugins/agystack/rules/agystack-models.md`, a small rule every agystack skill reads.

You only override what you care about. A role with no line in the rule keeps the skill's default. To restore a default later, delete that role's line, or just run `/setup-agystack` again.

You might be wondering what happens if you use Auto. Set a role to `inherit-parent` or `auto` and agystack omits the subagent `model` field, so the subagent inherits your parent chat model. Both values mean the same thing, and neither is a model slug. For a panel role the value is a list, and one subagent runs per entry, so the list length sets the panel size. Setup also configures `swarm workers`, the default model for every `/swarm` worker unless a race names a model for each arm.

## Accept the verification offer, or don't

At the end of setup, `/setup-agystack` looks for a way to prove app behavior in your project, either a `verify-*` skill or an existing harness. If it finds neither, it offers once to generate one with [`/create-verification-skill`](../../skills/create-verification-skill/SKILL.md).

Say yes and it writes `.agents/skills/verify-<app>/`, a project-local skill that teaches agents to drive your app the way a user does. It proves the skill works once before handing it over. Say no and setup moves on. You can run `/create-verification-skill` yourself any time. [Verify and ship](./06-verify-and-ship.md#create-a-project-verification-skill) covers when it earns its place.

After setup, start a new chat. The model rule applies to new sessions.

## Run your first task

Pick something real but small, and describe it the way you'd describe it to a colleague:

```text
/poteto-mode add a --json flag to this command. text output stays byte-identical. verify both.
```

Watch the todo list. The first item is always "read the Principles section". The rest are the matched playbook's steps copied in, the Feature playbook for this prompt. If `/poteto-mode` skips a step, the step stays in the list with `skip: <reason>`, so you can see what it chose not to do.

From here you can type normal follow-ups. `/poteto-mode` is sticky. It stays on for the conversation until you opt out by saying so.

Next: [Route work through `/poteto-mode`](./02-poteto-mode.md).
