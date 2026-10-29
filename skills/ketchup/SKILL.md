---
name: ketchup
description: Catch up on autonomous runs, background tasks, and unread transcripts. Generates concise summaries under 100 words with native Antigravity Artifact links, visual receipts, and selectable action items.
---

# Ketchup

Catch up on autonomous runs, unattended tasks, and background execution without reading lengthy transcripts.

## Strict Concise Summary Format

Executive summaries must remain strictly under 100 words.
Deliver the core status in plain declarative sentences.
Name the current goal, the completed phase, any active blockers, and the next step.
Avoid narrative filler and conversational preamble.
Detailed logs belong in companion artifacts rather than the chat summary.

## Action Items and Decisions Formatting

Format pending decisions and open questions so the user can easily select options or picks.
Present choices as structured options labeled with clear tags:

- **Option A.** Description of the first choice and its immediate tradeoff.
- **Option B.** Description of the alternative choice and its immediate tradeoff.

The user can respond with a single token or pick such as Option A.
Do not ask open-ended questions when a structured pick settles the fork.
When an action is blocked on external input, state the exact input required and the default fallback.

## Native Antigravity Artifacts & Visual Progress

Deliver comprehensive context through native Antigravity Artifacts in `<appDataDir>/brain/<conversation-id>/`.
Point to artifacts using clickable file links.
Do not dump artifact bodies into chat responses.
Key companion artifacts include:

- `walkthrough.md` for verified changes and test receipts.
- `decision_trail.md` for sequential forks, rationales, and results.
- `implementation_plan.md` for roadmap progress and checked boxes.

### Visual Progress Carousels and Generative UI
Use native markdown carousels (````carousel ... ````) with `<!-- slide -->` comments for sequential visual walkthroughs and before/after progressions.
Embed `generative_ui` HTML/SVG timeline widgets for visual progress rendering directly in artifacts without external video compilation dependencies like ffmpeg MP4s.

## Visual Media Embedding

Link or embed visual media directly to provide immediate visual receipts.
Always copy screenshots and recordings to `<appDataDir>/brain/<conversation-id>/` before referencing them.
Screenshots are linked or embedded using standard Markdown syntax:

`![Verification Receipt](file:///path/to/screenshot.png)`

Provide direct file links alongside embeds so the user can open them in external viewers.
Every visual receipt must prove a concrete assertion such as passing gates or rendered UI states.

## Periodic Audit Reporting

Use `/ketchup` at the conclusion of periodic audit ticks during autonomous playbooks.
An audit tick evaluates progress across subagents, verifies side effects, and outputs a concise ketchup report.
This practice keeps the operator informed without context overload.
