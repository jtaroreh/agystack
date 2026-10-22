---
name: principle-test-behavior-not-implementation
description: "Apply when writing or reviewing tests. Test what the system does from the outside (inputs, outputs, observable behavior, invariants), not how it is structured internally (private methods, call counts, internal state)."
disable-model-invocation: true
---

# Test Behavior, Not Implementation

Write tests against observable behavior and contracts, not internal implementation details. Tests should survive refactoring without changes.

## The Two Imagined Edits

Evaluate any test suite by picturing two deliberate edits:

1. **Break behavior.** If you alter what the system does for callers, a test must break. If all tests pass, the test suite has blind spots.
2. **Change internals.** If you refactor internals (rename private helpers, change algorithms, reorganize internal data structures) without altering the contract or observable behavior, zero tests should break. If tests break, they are testing implementation details.

## Diagnostic Test

Consider the diagnostic test:
"Can you change how it works without changing what it does, and do the tests stay green?"

If the answer is no, the tests are bound to implementation details rather than behavior. Rewrite the brittle tests to assert on public outcomes before refactoring code.

## Good Tests

- Treat the unit or subsystem as a black box with defined inputs and outputs.
- Test contracts, invariants, and edge cases.
- Use public APIs and observable side effects.
- Verify state through public query methods or final output artifacts.

## Anti-patterns

- Mocking functions you own. Prefer real instances or lightweight fakes.
- Asserting on internal call counts or execution order when order is not part of the contract.
- Asserting on exact internal data structures rather than the public result.
- Writing tests that duplicate implementation logic.
