### Visual parity

**You own pixel-exact equivalence. The baseline is the spec; you do not touch it.** For "make X match Y exactly", styling-system migrations, porting a UI across frameworks. Equivalence is verified by image diff, not by eye.

1. Establish the baseline first, before any migration: a visual regression harness that screenshots the current component across its states, plus the target when matching two implementations. No baseline, no parity claim. A blocking prerequisite, not a follow-up.
2. Anti-shortcut clauses, stated and held: no harness modifications, no baseline tampering, no component restructuring to make a diff pass. If the baseline looks wrong, stop and ask, don't edit it.
3. Migrate one component at a time. Each is an independent artifact, so parallelize across worktrees, one owner per component (the **separate-before-serializing-shared-state** principle skill). Shared primitives migrate first as a blocking phase.
4. Verify each component against its baseline via image diff on the matching surface via the control skill. A nonzero diff is a fail; investigate the pixel delta, don't wave it through. `/loop` per component until the diff is zero. Copy comparison images to `<appDataDir>/brain/<conversation-id>/` and publish `<appDataDir>/brain/<conversation-id>/visual_parity_report.md` (or `walkthrough.md`) artifact with side-by-side or `carousel` image diffs.
5. Run **Opening a PR** per component or per safe batch.

**Reply:** point to `visual_parity_report.md` (or `walkthrough.md`) and the PR. Summarize components migrated, diff results, and baseline harness location in concise declarative sentences. Image diffs and carousels live in the artifact.
