---
name: ketchup
description: "Catch the user up on what changed in this chat or autonomous run since their last message, in plain words and small visuals. List every item waiting on them with what they need to decide it from the reply alone. Use for /ketchup."
---

# Ketchup

Catch the user up on what changed in this chat or autonomous run since the last message they wrote before `/ketchup`, and help them understand each change rather than only where it stands. Then lay out every call waiting on them so they can decide from your reply alone. Notifications and subagent results are not user messages. Assume the user remembers their last message and nothing after it.

Use [`/bro`](../bro/SKILL.md)'s voice, in plain words and short sentences without jargon. State what changed for the user rather than how you did it. Say "the tests pass", not "CI is green". Omit commit hashes, file paths, commands, build numbers, and test counts unless the user needs one to act. Call each PR, branch, or agent by a name the user knows. If a fact needs context to make sense, give the context or leave the fact out.

## Gather what changed

- **Read-only turn enforcement.** Keep this turn strictly read-only. Build visuals only from state and artifacts you already have. Do not change code, start an app or job, or post anything.
- **Collect state.** Gather your work since the user's last message, subagent reports, messages from others in this chat, and the current state of each PR, CI run, or agent touched.
- **Verify numbers against source facts.** Check every number you plan to show against the source facts it comes from, including `decisions.tsv`, test logs, and PR metrics. Say so explicitly when you correct one.
- **Action-item qualification.** An action item is a call or step only the user can take, such as a product choice, approval, irreversible action, or missing access, including any still waiting from earlier. Work you can still do yourself is not an action item. Never invent a call to fill the reply. A step the user did not ask for and the work does not need is not an action item unless it is irreversible and waiting on them. Give that one line and no visual.
- **Per-action-item schema.** One call can cover many items, such as PRs awaiting merge. For each action item, collect:
  1. Link or identifier, if available.
  2. What it changes for users.
  3. Your pick and the evidence behind it, placing prerequisite or irreversible steps first.
  4. Risk, even when low, such as `"Low risk. Only the colors change."`. State waiting cost only when worse than a delay, such as a deadline or lost data.
  Write `"unknown"` for any needed fact you do not know.

## Write the reply

Spend words on the calls, not the story. Keep what happened under **100 words**, excluding visuals, and shorter when less happened. Omit work that changed nothing for the user.

- **Scaling word budget (`~30 words per item`).** Give each action item about 30 words (`~30 words per item`). Total length grows with item count. Two items stay well under 150 words excluding visuals, and thirty items take proportionally more. Never cut items or shrink them behind counts or links to stay under a cap. The reply alone must be enough to decide.
- **Opening.** Open with one short sentence naming what waits on the user, or stating that nothing does. If nothing happened and nothing waits, say so and stop.
- **What happened.** Show visuals first, then one short plain bullet per requested item naming outcome and state (`done`, `still running`, `failed`, or `not checked`) plus any bug found and fixed. Never mark work waiting on the user as done. Follow with up to three short lines that change what the user knows or must do, and one line for remaining work you can do yourself.
- **Action items.** Fit the shape to the call:
  - **Single-item call.** One bullet with the call, your pick, user-facing change, evidence, and risk.
  - **Shared call.** State the call and your pick once, then list one bullet per item ordered riskiest first: link and name, user-facing change, evidence, risk, and any item-specific pick override.
  - **Option choice.** Present structured picks so the user can respond with a single token such as `Option A`:
    - **Option A.** Description, user gain, cost, and current state.
    - **Option B.** Alternative, user gain, cost, and current state.
    Costs serve as the risk line. When blocked on external input, state the exact input needed and the default fallback.

## Native Antigravity Artifacts & Visual Layer

Store detailed context in native Antigravity Brain Artifacts under `<appDataDir>/brain/<conversation-id>/` and point with clickable `file://` links instead of dumping artifact bodies into chat:

- `walkthrough.md` for verified changes, test receipts, and visual proof.
- `decisions.tsv` paired with `decision_trail.md` for sequential forks, evidence pointers, and results.
- `implementation_plan.md` for roadmap progress and checked boxes.

### Primary Visual Layer (`carousel` and `generative_ui`)

Use native markdown `carousel` blocks (````carousel ... ```` with `<!-- slide -->` comments) for sequential walkthroughs and before and after progressions, and use `generative_ui` HTML and SVG timeline widgets as the primary visual layer directly in artifacts without external video dependencies such as ffmpeg MP4s.

### Visual Discipline and Media Embedding

- Copy screenshots and recordings to `<appDataDir>/brain/<conversation-id>/` before referencing them, then embed inline alongside a direct link (`![Verification Receipt](file:///path/to/screenshot.png)`). Every receipt must prove a concrete assertion.
- Embed screenshots inline when a change is visible, or mark the summary line `"No screenshot yet"` and describe the on-screen change.
- Keep diagrams and charts factual and small. Use at most six boxes and at most eight words per box. A Markdown table is not a visual. Never invent numbers, draw fake UI screens, or repeat the same fact across visuals and text.

## Periodic Audit Reporting

Use `/ketchup` at the conclusion of periodic audit ticks during autonomous playbooks. An audit tick evaluates progress across subagents, verifies side effects, and outputs a concise ketchup report without context overload.
