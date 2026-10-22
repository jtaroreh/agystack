---
name: correct
description: Structured repository hardening against agent mistakes. Classifies recurring defects and enforces the fix hierarchy where architecture and structural checks precede rules and prompts.
---

# Correct

Harden repositories against recurring agent mistakes and systemic defects.
When an agent makes an error, do not simply patch the immediate failure or add an ad-hoc instruction.
Classify the defect and enforce structural defenses at the highest level of the fix hierarchy.

## Mistake Classification

Group mistakes into distinct classes to identify appropriate structural countermeasures:

- **Constraint misunderstanding.** The agent ignores instructions, misinterprets bounds, or violates system constraints.
- **Hallucinated APIs.** The agent invents parameters, functions, flags, or tools that do not exist in the platform or runtime.
- **Fragile patterns.** The agent uses brittle regex parsing, race-prone file operations, unstructured text extraction, or unvalidated assumptions.
- **Regressions.** The agent breaks previously working tests, overwrites unrelated code, or reverts recent fixes.

## Fix Hierarchy

When remediating an agent defect, apply solutions at the highest possible layer in the fix hierarchy.
Architecture and structural checks precede rules and prompt instructions:

1. **Architecture.** Make illegal states unrepresentable. Enforce structural boundaries, capability restrictions, and invariants by construction.
2. **Type checks.** Statically typed schemas, discriminated unions, and compiler gates that fail immediately on invalid invocations.
3. **Linter and automated tests.** Deterministic static analysis, linters, pre-commit hooks, and behavioral unit tests that catch errors in automated loops.
4. **Instructions and prompts.** Guidelines and prompt instructions are the last line of defense, never the first.

## Hardening Process

Follow these steps to remediate mistakes:

1. Reproduce the mistake with an automated test or deterministic reproduction script.
2. Classify the mistake into its category.
3. Determine the highest applicable layer in the fix hierarchy.
4. Implement the structural guard such as a typed interface, lint rule, or architectural boundary.
5. Verify that the failure is blocked before falling back to prompt prose.
