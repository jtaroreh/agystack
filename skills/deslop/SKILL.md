---
name: deslop
description: Clean AI slop and defensiveness out of code and diffs before commit. Strips narrating comments, redundant guards, speculative error handling, unused abstractions, and dead compatibility code.
---

# Deslop

Clean AI patterns, excessive defensiveness, and unnecessary bloat out of code and git diffs before committing.

While [`/unslop`](../unslop/SKILL.md) cleans human/agent prose and [`/no-comments`](../no-comments/SKILL.md) strips comments before review, `/deslop` operates directly on application code and diffs.

## Process

1. **Inspect the diff.** Run `git diff` against your base branch or `HEAD~1`. Focus on newly added or modified lines.
2. **Scan for code slop patterns** (see checklist below).
3. **Refactor and simplify.** Delete defensive bloat, eliminate speculative layers, and restore direct, obvious code.
4. **Verify correctness.** Run tests, typechecks, or linters to prove the streamlined code still works.

---

## Code Slop Patterns to Detect and Fix

### 1. Defensive Over-Engineering
- **Redundant null/undefined checks:** Checking variables that internal types or preceding guards guarantee cannot be null. Trust internal invariants; concentrate validation at external boundaries (`principle-boundary-discipline`).
- **Try-catch swallows:** Wrapping synchronous or infallible calls in `try...catch` blocks that swallow errors or return fallback values silently.
- **Speculative error handling:** Catching errors that cannot happen in normal flow rather than letting real failures surface (`principle-fix-root-causes`).

### 2. Speculative Flexibility
- **Unrequested configuration:** Adding options objects, configurable flags, or generalized plugin systems for single-use logic (`principle-laziness-protocol`).
- **One-caller abstractions:** Creating helper functions, interfaces, or wrapper classes used in exactly one place with no likelihood of reuse (`principle-minimize-reader-load`).
- **Premature type parameterization:** Introducing complex generic type parameters where concrete types suffice.

### 3. Narrating and Placeholder Comments
- **Obvious narration:** `// check if user exists`, `// return the result`, `// loop through items`. Delete them immediately.
- **Section banner comments:** `// ===================== HELPERS =====================`. Remove them.
- **Commented-out code:** Dead code blocks left "just in case". Delete them; git history preserves past code (`principle-subtract-before-you-add`).

### 4. Artificial AI Code Tells
- **Intermediate variable churn:** Assigning a value to a temporary variable only to immediately return or pass it once:
  ```ts
  // Slop
  const result = calculateTotal(items);
  return result;
  
  // Clean
  return calculateTotal(items);
  ```
- **Redundant type assertions:** Overusing `as any`, `as unknown as T`, or unnecessary non-null assertions `!` when proper typing or narrowing makes the code type-safe (`principle-type-system-discipline`).
- **Verbose conditional boilerplate:** Using 10-line `if/else` ladders where a simple ternary, dictionary lookup, or early return is cleaner.

### 5. Lingering Debug and Scratch Artifacts
- Leftover `console.log`, `print()`, `dbg!()`, or ad-hoc benchmark timers.
- Temporary test fixtures or scratch files committed by mistake.

---

## Output / Reply

State:
- Files cleaned and line delta (e.g. `-45 lines`).
- Types of slop removed (e.g., redundant null guards, one-caller helper collapsed, narrating comments stripped).
- Verification command run to confirm tests and types remain green.
