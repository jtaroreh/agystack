---
name: architect
description: "Sketch types, signatures, and module structure before code, then stay in the loop while implementation fills in. Use for /architect, 'architect this', 'design this', or non-trivial work where jumping to code would lock in the wrong shape."
---

# Architect

Design before implementing. Sketch caller usage, types, function signatures, and module boundaries with `not implemented` bodies before writing logic. Open a todolist with all five phases before starting so none disappear silently: `1. Ground`, `2. Sketch`, `3. Agree`, `4. Implement`, `5. Scrap`.

## Phase A: Ground

Build a traced mental model of every system the change touches via the **how** skill. Naming files is not grounding. Run **why** when redefining ownership or layering, and **interrogate** when existing structure is the constraint. Skip Phase A only for genuinely greenfield work. If requirements are completely ambiguous upfront, the human may run `/grill-me`; once `/architect` begins, explore autonomously against code ground truth.

## Phase B: Sketch

Write the **caller's usage first**, then derive types, function signatures, and module boundaries from it.

Design it twice: produce at least **two structurally distinct whole-shape candidates** before choosing (per **principle-exhaust-the-design-space**), not point fixes inside one shape. For large or contested designs, route candidate exploration through the **arena** skill using configured `arena runners` (translating Gemini 4 effort-suffixed entries to `pro`, `inherit`, `flash`, falling back to `inherit` on single-tier accounts or HTTP 429).

Screen every candidate against Ousterhout design red flags before selecting or synthesizing, rejecting or revising violations:
- **Shallow modules.** Large public surface hiding little complexity; prefer deep interfaces that concentrate capability over deep call chains.
- **Information leakage.** Multiple modules sharing an internal representation, protocol, or wire format; parse external data at the boundary and keep internals private.
- **Temporal decomposition.** Splitting modules by execution order (load, validate, save) instead of domain knowledge and single state ownership.
- **Pass-through methods.** Forwarding layers that add no policy, adaptation, or abstraction; collapse them or move responsibility.

## Phase C: Agree (Opt-in)

Default: proceed directly to Phase D with no human checkpoint. Pause for sign-off only when the invoker explicitly requests a checkpoint (for example, "/architect with checkpoint"). The chosen sketch can ship as its own scaffold commit (per **principle-foundational-thinking** and **principle-outcome-oriented-execution**). Run **interrogate** on the sketch when adversarial pressure is warranted. Treat human pushback as Phase A evidence: re-ground and re-sketch.

## Phase D: Implement

Fill in `not implemented` bodies against the sketch contract. Treat deviations as signal, not friction to absorb silently. When a function needs an unanticipated parameter or branch, surface whether the sketch was wrong, a requirement was missed, or the implementation is overreaching.

## Phase E: Scrap

When implementation reveals a *pattern* of friction the sketch cannot absorb, throw it out rather than bolting on fixes (per **principle-redesign-from-first-principles** and **principle-fix-root-causes**). Concrete triggers:
- The same workaround shape repeating across unrelated code.
- Multiple unrelated edge cases requiring special-case branches.
- Escape hatches (`any`, casts, always-set optionals) needed just to compile.
- Reaching for locks when the sketch assumed unshared state.
- Callers needing internal rules to use the abstraction.
- Two or more independent Phase D deviations of the same shape.

Recovery loop:
1. Re-run **how** over what was built so implementation lessons enter as ground truth.
2. Redesign as if the new constraints were day-one assumptions.
3. Subtract before adding (per **principle-subtract-before-you-add**): the new sketch starts smaller than the old one.
4. Return to Phase B (and `/arena` if large or contested).

## Output

Publish the caller-first usage sketch, type/signature definitions, module map, red-flag check, and synthesis decision to `<appDataDir>/brain/<conversation-id>/architecture_design.md` (`ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: true }`).
