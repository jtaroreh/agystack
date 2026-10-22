---
name: sharpen
description: Task calibration and expert scoping. Calibrates constraints, retains outside checks, challenges premises, and avoids premature lock-in.
---

# Sharpen

Calibrate task scopes, clarify boundaries, and eliminate ungrounded assumptions before implementation begins.
Avoid taking requested specifications as rigid immutables when a cleaner framing achieves superior outcomes.

## Calibrate Constraints

Distinguish between genuine system invariants and arbitrary assumptions.
Challenge constraints that add complexity without providing safety or user value.
Expand the solution space before narrowing to a specific approach.
Verify whether proposed limits reflect real physical bottlenecks or legacy artifacts.

## Retain Outside Checks

Never eliminate external independent verifiers or third-party validation gates.
An outside check is retained to ensure objective evaluation.
Internal self-assessments cannot substitute for external test suites, compiler gates, or independent review subagents.
When simplifying architectures or pruning workflows, keep the outside check intact.

## Challenge Premises

Apply foundational thinking before accepting problem statements as given.
Ask whether the underlying premise is flawed or if a simpler framing eliminates the required work.
Test foundational assumptions with quick empirical probes rather than speculative debate.

## Avoid Premature Lock-in

Do not commit to rigid designs or deep abstractions before observing runtime behavior.
Build lightweight prototypes or throwaway sketches to explore competing alternatives.
Keep interfaces minimal and defer irreversible decisions until concrete evidence confirms the path.
