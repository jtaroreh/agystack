---
name: principle-test-behavior-not-implementation
description: "Apply when writing or reviewing tests. Test what the system does from the outside (inputs, outputs, observable behavior, invariants), not how it is structured internally (private methods, call counts, internal state)."
disable-model-invocation: true
---

# Test Behavior, Not Implementation

Write tests against observable behavior and contracts, not internal implementation details. Tests should survive refactoring without changes.

**Why:** Tests coupled to internal details (mocking internal methods, asserting specific call counts, inspecting private state) break when code is refactored, even when behavior is unchanged. This creates test maintenance burden and discourages refactoring.

**Pattern:** Ask: "If I rewrote the internals completely, would this test still pass?"

Good tests:
- Treat the unit or subsystem as a black box with defined inputs and outputs.
- Test contracts, invariants, and edge cases.
- Use public APIs and observable side effects.
- Verify state through public query methods or final output artifacts.

Avoid:
- Mocking functions you own (prefer real instances or lightweight fakes).
- Asserting on internal call counts or execution order when order is not part of the contract.
- Asserting on exact internal data structures rather than the public result.
- Writing tests that duplicate the implementation logic.

Refactoring test:
- If changing internal implementation breaks tests while the feature still works, the tests were testing implementation, not behavior.
- Rewrite the brittle tests to assert on public outcomes before proceeding with the refactor.
