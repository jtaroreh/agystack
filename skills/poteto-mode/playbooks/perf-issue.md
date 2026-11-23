### Perf issue

**You own the measurement story. Plan, review, verify the numbers.** Tie every fix to a measurement, don't read source instead of measuring.

1. Capture a baseline trace via the matching control skill. Vet the baseline, and each later number, with the **benchmark-checklist** skill.
2. Trace the code to ground hypotheses. Don't claim a perf ceiling without running it first.
   Try the performance mantras in order, cheapest first:
   1. Don't do it. Stop work whose result nothing uses rather than cheapening it.
   2. Do it, but don't do it again.
   3. Do it less.
   4. Do it later.
   5. Do it when they're not looking.
   6. Do it concurrently.
   7. Do it cheaper.

   When an earlier mantra meets the target, stop.
3. Plan the fix from the trace. If it crosses a function boundary, `architect` first. Delegate implementation via `invoke_subagent` using your configured `perf-issue` model (default `inherit`; see `agystack-models.md`); review the diff. Capture a post-fix trace.
   Apply the **sequence-verifiable-units** principle skill, verifying each attempt before trying the next.
4. Parse and compare the artifacts (JSON to sqlite, diff). "Inconclusive" or wrong-surface is not a pass; flag it. Run the **benchmark-checklist** skill and apply the **explain-the-number** principle (**principle-explain-the-number**) before claiming wins or publishing numbers. Name the physical bottleneck and hardware/kernel root cause rather than guessing from code. Publish the full comparative analysis, charts, and trace diffs to `<appDataDir>/brain/<conversation-id>/perf_report.md` (or `walkthrough.md`) artifact.
5. Cite the measurement in the PR.
6. Run **Opening a PR**.

For sustained improvement against a metric rather than a one-off fix, use the Hillclimb playbook (`playbooks/hillclimb.md`).

**Reply:** point to `perf_report.md` (or `walkthrough.md`) and the PR. Summarize baseline number, post-fix number, and delta in concise declarative sentences. Trace breakdowns live in the artifact.
