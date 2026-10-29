---
name: principle-fix-root-causes
description: "Apply when debugging. Trace each symptom to its root cause and fix it there; reproduce first, ask why until you reach it, resist nil-check guards that silence crashes."
disable-model-invocation: true
---

# Fix Root Causes

When debugging, do not paper over symptoms. Trace every problem to its root cause and fix it there.

**Why:** Symptom fixes accumulate. Each workaround makes the system harder to reason about, and the real bug remains. Root-cause fixes are slower upfront but reduce total debugging time.

## Legitimate vs. Illegitimate State

Differentiate legitimate state from illegitimate state before deciding how to handle an unexpected condition:

- **Legitimate state.** Normal edge cases, legitimate empty values, valid network dropouts, and valid domain boundaries. The system must accommodate and handle these natively through structured control flow and resilient fallback paths.
- **Illegitimate state.** Invariant violations, corrupt records, broken pointers, desynced mirrors, and impossible enum values. Never silence illegitimate states with defensive null-checks, default fallbacks, or swallow-and-continue guards downstream. Silencing an illegitimate state lets corruption spread far from the defect that produced it.

## Always-On Cheap Signal

Place cheap, always-on assertions or invariant guards at the exact boundary where state is created or enters the system. Invalid state must fail fast and loudly at the source.

- Validate inputs, deserialized payloads, and constructed models at creation time.
- If an illegitimate state enters internal code, reject or panic immediately with diagnostic details rather than carrying on in a degraded state.
- Keep guards cheap enough to run permanently in production. An always-on cheap signal catches regressions immediately instead of masking them behind silent fallbacks.
- If the deciding fact took a deep dig to find, propose the cheap, always-on signal that would have shown it at first look.

## Pattern

- Reproduce first. If you cannot reproduce it, you cannot verify your fix.
- Ask "why" until you hit the root cause.
- Resist the urge to add guards. Adding a nil check to silence a crash without fixing why the value was nil is a symptom fix.
- If a workaround needs a paragraph-long comment to justify it, the code is wrong. Fix the code, not the comment.
- Check for the pattern, not just the instance. Grep for the same pattern across the codebase and fix all instances.
- When stuck, instrument. Add logging and inspect actual error outputs rather than guessing.

## Restart Bugs: Suspect State Before Code

Code does not change between runs. State does. When something fails after restart, suspect stale persistent state first: config files, caches, lock files, serialized state. If clearing a state file restores behavior, prioritize state validation and cleanup as the fix.
