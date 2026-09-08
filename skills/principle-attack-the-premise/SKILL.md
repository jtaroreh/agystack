---
name: principle-attack-the-premise
description: "Apply when handed a problem, constraint, or design you are tempted to accept as given. Ask if the premise is false, the constraint is self-imposed, or a simpler framing eliminates the work entirely."
disable-model-invocation: true
---

# Attack the Premise

Before solving a problem, ask whether the premise is valid. The highest-leverage engineering decision is often not how to build something, but recognizing that building it is unnecessary.

**Why:** Engineers naturally optimize within the constraints they are handed. Many constraints are accidents of history, misunderstandings, or self-imposed boundaries. Accepting false premises produces complex workarounds for problems that should not exist.

**Pattern:** When handed a requirement, question, or design constraint, ask:
1. Is the stated problem the actual problem?
2. Is the constraint real, or assumed?
3. What happens if we do nothing or delete the thing causing the problem?
4. Is there an entirely different framing where this requirement disappears?

Question constraints:
- "We need a cache here" -> Why is the underlying operation slow? Can we make it fast enough that caching is redundant?
- "We need to support both formats" -> Why? Can we migrate to one format and delete the other?
- "We need a background queue for this" -> Can it be synchronous and fast instead?
- "How do we make this migration backwards-compatible?" -> Do we actually have external callers, or can we migrate all call sites atomically?

Premise checks:
- Distinguish hard external constraints (hardware limits, physics, external API contracts) from internal choices.
- Challenge "we have always done it this way" and "the user asked for X" (when the user actually wants Y and X was their guessed solution).
- If a simpler approach exists that violates an assumed constraint, surface the tradeoff explicitly rather than quietly building the complex solution.
