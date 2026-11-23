### Opening a PR

Invoked at the end of every other playbook.

**Branch and workspace isolation.** Work from a clean branch off main. For subagent fan-out, delegate using native `Workspace: "branch"`. The host manages branch isolation and worktree lifecycle automatically. Dirty branch with unrelated work: patch out, start from a fresh branch off main, apply. Snarled branch: reset from main, redo minimally.

**Commits.** Commit liberally and rebase into small, ordered commits before opening PRs. Each commit is a future PR: landable and ordered to tell the story. Amend when the fix belongs in a just-made commit. Create a new commit when separable.

**PRs.** Run `/deslop` over the diff before commit. Run `/no-comments` before review. Write every PR title, PR description, and commit body with `/technical-writing`, then apply `/unslop`. Apply every technical-writing layer except Diátaxis. Use one word for each action, keep articles, and avoid `-ing` when a plain verb works.

**Titles.** Use Conventional Commits in the form `type(scope): subject`. Use `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, or `perf` as the type. Use the changed area, such as `agystack` or `poteto-mode`, as the scope. Keep the subject short and imperative. Apply the same `/technical-writing` and `/unslop` pass as the body. Name a real symbol when one carries the change. For example, `fix(agystack): retarget opening-a-pr babysit trigger`. Do not add a trailing period.

**Descriptions.** Keep the PR body as a one-minute briefing of at most 40 lines using these sections in order. Drop a section when it is empty. Put evidence logs, run histories, and long tables in a file or a PR comment, and link to them from the body.

- `## Why`. State the intent, the user goal, and why this approach fits.
- `## What changed`. Summarize the concrete behavior and file-level delta before the diff details.
- `## Scope`. State facts from the diff. Name real symbols and paths. Name both sides of a rename or retarget. State what is in and out when the boundary matters.
- `## Tradeoffs`. State real choices and rejected alternatives a reviewer would otherwise ask about. Skip this section when there are none.
- `## Blast Radius`. State who and what the change touches. Explain why the change is safe or risky. If main is red without the fix, name the continuing cost.
- `## Verification`. State how you ran each check and its rigor. Name the real path, such as browser subagent recording, CLI test harness, or targeted unit tests. State the outcome of each check, not only the command name.

After these sections, attach videos or screenshots when they prove a claim. Do not use `## Summary` or `## Test plan` boilerplate. A commit body does not restate its subject.

**Size and stacks.** Prefer five narrow PRs to one large PR. Resolve the forge once: use `gh pr create` by default, or `origin pr create --status open` when `command -v origin` succeeds and Origin resolves the repository. Never require Graphite (`gt`), though optional Graphite tracking may be kept visible when the operator uses it. Stack follow-ups by base branch, branching from `main` only for independent work, and rebase on `main` before substantial stack work.

**Readiness.** Open every PR ready, never as a draft. PR tools often default to draft, so pass `draft: false` (or omit `--draft` in `gh pr create`, and pass `--status open` in `origin pr create`). If a PR still opens as a draft, run the forge's ready command, such as `gh pr ready <number>`. Run unpiped `gh pr view <number> --json state,isDraft,url -q .url` (or `origin pr view <number>`) before referring to PR status. Never use shell pipes.

**Babysit.** Opening a PR does not start a babysit. Post the URL and keep building. Finish the phase or stack first. Run a separate babysit pass only when the user asks for one after the whole stack exists. A babysit for each new PR stalls the build and spends checks on commits that later waves restart. Push back when feedback drifts from intent.

A subagent that opens a PR runs `interrogate`, `/deslop`, and `/no-comments`, and posts the URL. Then it returns to the parent without babysitting, unless it is an Autopilot-full or Autopilot-stack owner. That owner's brief assigns the babysit loop and is the ask `playbooks/babysit.md` waits for. The owner starts the loop after its code-ready report and reports merge-ready or `STACK-READY` as its playbook says. The rules here and in `playbooks/babysit.md` that hold babysitting until a whole stack is built do not apply to that owner.
