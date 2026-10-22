---
name: principle-attack-the-premise
description: "Apply when handed a problem, constraint, or design you are tempted to accept as given. Ask if the premise is false, the constraint is self-imposed, or a simpler framing eliminates the work entirely."
disable-model-invocation: true
---

# Attack the Premise

Before solving a problem, ask whether the premise is valid. The highest-leverage engineering decision is often not how to build something, but recognizing that building it is unnecessary.

**Why:** Engineers naturally optimize within the constraints they are handed. Many constraints are accidents of history, misunderstandings, or self-imposed boundaries. Accepting false premises produces complex workarounds for problems that should not exist.

## Test the Shared Assumption Directly

When debating between Option A and Option B, uncover the hidden shared premise. Debates over competing implementations often take an unproven assumption for granted.

1. **Uncover the hidden premise.** Identify what both Option A and Option B assume to be true. Both options might assume that an operation is too slow, that dual writes are necessary, or that backward compatibility must be maintained indefinitely.
2. **Test the shared assumption directly.** Run a spike, profile the operation, or take a direct empirical measurement before debating implementation details. A 10-minute microbenchmark or prototype can prove whether the assumed constraint exists in reality.
3. **Reject false dilemmas.** If direct testing disproves the premise, discard both Option A and Option B. A simpler framing eliminates unnecessary complexity and deletes the need for either implementation.

## Questions to Ask

When handed a requirement, question, or design constraint, ask:
1. Is the stated problem the actual problem?
2. Is the constraint real, or assumed?
3. What happens if we do nothing or delete the component causing the problem?
4. Is there an entirely different framing where this requirement disappears?

## Common False Premises

- "We need a cache here." Why is the underlying operation slow? Profile it first. Make it fast enough that caching is redundant.
- "We need to support both formats." Why? Verify whether external callers exist. Migrate all internal call sites and delete the legacy format.
- "We need a background queue for this." Can the operation be made synchronous and fast instead? Measure the actual latency before adding queue infrastructure.
- "How do we make this migration backwards-compatible?" Check if all consumers are within the same repository. Migrate call sites atomically instead of building a compatibility layer.

## Premise Checks

- Distinguish hard external constraints (hardware limits, physics, external API contracts) from internal choices.
- Challenge "we have always done it this way" and "the user asked for X" (when the user wants Y and X was their guessed solution).
- If direct measurement proves an assumed constraint false, surface the finding immediately rather than quietly implementing the complex solution.
