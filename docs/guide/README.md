# The agystack guide

agystack works best when you stop micromanaging the agent. You describe what you want and how you will know it is done. `/agystack` and `/poteto-mode` pick the playbook, run the other skills as the steps need them, and show you the evidence. This guide teaches that habit with realistic prompts.

Here is what you will learn.

1. [Set up agystack](./01-setup.md). Install the plugin and pick your models.
2. [Route work through `/poteto-mode`](./02-poteto-mode.md). Give it a goal and watch it pick a playbook.
3. [Understand the code](./03-understand.md). A read-only investigation, then `/how`, `/why`, `/teach`, and `/recall` before you edit anything.
4. [Design the change](./04-design.md). `/architect`, `/arena`, `/cloud-swarm`, `/interrogate`, prototypes, and plans before code locks in a shape.
5. [Build and clean the change](./05-build-and-clean.md). The build playbooks, `/tdd`, `/deslop`, `/unslop`, and `/no-comments`.
6. [Verify and ship](./06-verify-and-ship.md). Prove behavior on the real app, formally verify what tests rarely reach, vet numbers with `/benchmark-checklist`, then open a focused PR and drive it to merged.
7. [Run work while you sleep](./07-overnight.md). Trust before loops, an overnight contract using `/goal` and `schedule`, a decision log you can audit, and playbooks that scale past one agent.
8. [Steer with principle names](./08-principles.md). The 24 names that redirect an agent mid-task.
9. [Make it yours](./09-make-it-yours.md). Your own mode, `/correct` for repeated mistakes, and how to test a skill change.
10. [Recipes and pitfalls](./10-recipes-and-pitfalls.md). Prompts to copy and mistakes to skip.

Read the pages in order the first time. After that, each page stands alone.

When you are stuck, or cannot tell which skill fits, type [`/agystack-help`](../../skills/agystack-help/SKILL.md) with your question.

```text
/agystack-help which skill should i use to review this branch?
```

It answers without editing files, hands you a prompt to send, and links the skill or guide page the answer came from. It stays read-only and does not start the work, because an agystack run spends real tokens, so you send the prompt when ready.

## If you only remember one thing

Give the agent a goal and a way to check it, in your own words.

```text
/poteto-mode the export writes duplicate rows when a retry lands mid-run. repro first, then fix and verify.
```

You do not need to name a playbook or list skills. `"repro first"` and a checkable outcome are all the routing signal `/poteto-mode` needs. It matches the Bug fix playbook, copies the steps into a todo list, and calls the right skills as each step fires.

Next, [Set up agystack](./01-setup.md).
