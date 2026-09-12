### Shipping

**You own what lands. Verify each PR independently, land only the verified run from the root, then keep your hands off the queue.** For "land the stack", "ship it", "enable merge when ready", or the second half of a stack that **Babysit** already drove to green.

This is the half after `playbooks/babysit.md`. Babysit makes a stack mergeable. Shipping decides what is actually safe to merge and lets Graphite drain it. Green is not safe, and the gap between those two words is where this playbook lives.

1. **Verify every PR independently before arming anything.** One subagent per PR, not batched, each exercising the real surface (browser subagent or CLI runner as the change demands) against parent versus head. Each returns `PASS`, `PASS+NOTES` or `FAIL` and posts that verdict on its own PR so the record outlives the chat. Safe means a verdict from an agent that did not write the code. CI green is not a verdict, and an approving bot review is not a verdict. Standardize PR status checks on unpiped `gh pr view <number> --json reviewDecision,statusCheckRollup -q .reviewDecision` rather than shell pipes.
2. **Land only the contiguous verified run rooted at the bottom.** Walk up from the lowest unmerged PR and stop at the first one without a passing verdict, where both `PASS` and `PASS+NOTES` pass. A verified PR sitting above an unverified one is not landable, because merging it would pull the gap in underneath it. Report the ceiling as a PR number and say what breaks the chain.
3. **Re-check that the verdicts still describe the code.** A restack rewrites every SHA above it and silently invalidates every verdict without touching a single check. Compare `git patch-id` at the verdict SHA against the current head before trusting an older verdict, and re-verify anything that actually drifted. Twenty-one verdicts went stale this way in one run with no signal at all.
4. **Arm merge automation appropriate to your branch structure:**
   - **Standard GitHub PRs (independent branches targeting trunk):** Enable auto-merge directly via GitHub CLI:
     ```bash
     gh pr merge <number> --auto --squash # (or --merge / --rebase)
     ```
   - **Native GitHub Stacks (stacked branches without Graphite):**
     Merge the verified run sequentially from trunk outwards. Merge the root PR first (`gh pr merge <root-pr> --squash`). Once merged into main, retarget and re-verify the next child branch against main, then merge. Repeat sequentially up to the verified ceiling.
   - **Graphite Stacks (stacked PRs with Graphite):** Arm merge-when-ready through Graphite, and pass `--always` (a no-op submit skips the Graphite update and silently arms nothing):
     ```bash
     gt submit --merge-when-ready --always --update-only --no-interactive
     ```
5. **Auto-merge safety on stacked branches.** For branch stacks, never enable GitHub native auto-merge on intermediate child PRs that target unmerged parent branches. Intermediate stack children target unprotected parent branches and read `CLEAN`, so GitHub would merge children into parents immediately and collapse the stack into itself. Only arm auto-merge on the root PR targeting protected trunk. For standalone PRs targeting trunk, GitHub auto-merge is safe and recommended.
6. **Do not read `autoMergeRequest` as proof that MWR is armed.** When using Graphite, it stays off until Graphite reaches that PR at the queue front, so an unarmed reading is meaningless and acting on it leads to re-submitting branches that were already fine. Confirm arming from Graphite's own state, and if you cannot, say so rather than inferring it.
7. **Once the queue is draining, stop touching the stack.** No `gt sync`, no restack, no speculative pushes, and no `gt submit --stack`, which reaches downstack into PRs that are mid-merge. Even a plain `gt submit` can retarget a base if local Graphite tracking has diverged, so never run `gt` from a branch whose parentage you have not just checked. Independent work gets re-parented onto trunk and shipped on its own.
8. **Watch the drain, do not drive it.** Arm the watcher in queued mode over the verified run and hold it under autonomous execution (via the `schedule` tool or `/goal`), re-armed after any verdict you act on, until COMPLETE at the ceiling. ADVANCE is progress, not termination. Bases retarget as each PR merges. Report each merge and the new ceiling. If the queue stalls, diagnose before mutating, because a stalled queue and a broken stack look identical from the outside.
9. **Stop at the ceiling.** When the verified run is merged, report what landed, what the next unverified PR is, and what verifying it would take. Extending the run is a new pass through step 1, not a judgment call you make at 3am.

**Reply:** the verified run and its ceiling, each PR's verdict and who produced it, what you armed and how you confirmed it, what landed, and what the next gap needs.
