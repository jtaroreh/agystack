---
name: create-formal-verification-skill
description: "Generate a project-local skill that formally verifies the code where a bug costs the most and tests reach the least, in any language, with whichever verification tool fits. Use for /create-formal-verification-skill, \"model-check this race\", \"prove this invariant\", or when concurrency, retries, state machines, parsers, or unsafe code need more than tests."
disable-model-invocation: true
---

# Create a formal verification skill

A test checks the cases someone thought to write. Formal verification checks every case in a stated scope: every interleaving in a model, every input up to a bound, or every input. This skill finds the target in the repo where a bug costs the most, verifies its key invariant, and leaves a project-local skill that lets the next agent recheck changes cold, mid-task.

## Choose the target from the code

Answer from the codebase first, and ask the user only what you cannot observe. If the user named an area or bug, start there.

Use this four-domain quick selector to gate formal methods against their maintenance cost:

- **Concurrency protocols.** Synchronization primitives, lockless structures, and interleavings that tests miss.
- **Distributed consensus.** Leader election, quorum replication, split-brain recovery, and partition tolerance.
- **Complex state machines.** Multi-actor lifecycles with concurrent events, retries, timeouts, and asynchronous resets.
- **Critical parsers and serializers.** Untrusted input decoders, binary framing, and cryptographic envelope checks.

If the target is routine CRUD endpoints, standard UI layouts and render loops, linear request handlers, or simple option parsers, reject formal verification and point to standard tests or [`/create-verification-skill`](../create-verification-skill/SKILL.md). For applicable work, pick the strongest promise whose violation harms users and defies unit tests, not the easiest module to model.

## Let the question choose the tool

Pick the lowest-cost tool that answers the question:

- **Event ordering and concurrency.** Use a model checker over a faithful small model; TLA+ is the default in any language.
- **Input-level safety or data-structure invariants.** Use an SMT-backed verifier or prover that checks the real code (such as memory safety or overflow). If none exists for the language, test the real code with generated inputs instead of modeling a pure function by hand.
- **Unbounded size properties.** Use a proof assistant when no finite bound suffices.

Prefer a tool the repo's developers can install and run locally, and record why you chose it.

## What makes it good

- **Code-to-model traceability and indivisible step fidelity.** Every state, action, and rule in the model points to code a reviewer can open. What the verification treats as one indivisible step must be one indivisible step in the code. Use the repo's real symbol and module names.
- **Able to fail.** A check that has never failed proves nothing. Prove every property catches a broken variant (such as a removed guard or reordered step).
- **Findings stay findings.** When current code breaks a property, report the counterexample in the code's terms. Never weaken the property or model to force a pass, and never edit product code unless the user asks.
- **Honest about scope.** State the verified bounds, assumptions, and exclusions explicitly.
- **Readable without the tool.** State each property and its harm in one plain sentence, and narrate counterexamples as short steps in the code's words.
- **Cheap to rerun.** One command, pinned or reproducible tool versions, and fast execution so agents rerun it on relevant edits.
- **Kept in step with the code.** Record the coverage map (files and functions covered) and the sync-commit SHA where verification last matched the code.

## Generate the verify skill

Write a project-local skill (such as `.agents/skills/verify-<area>/SKILL.md`) with YAML frontmatter containing `name` and `description` so the skill registers.

From that skill alone, the next agent must be able to see whether an edit touches covered code, run the check, distinguish a code bug from a modeling error, and update the verification when behavior intentionally changes. Include:

- The **coverage map** (exact files, functions, bounds, and assumptions).
- The **sync-commit SHA** (`git rev-parse HEAD` once verified), with instructions to advance it only after confirming the verification still describes the code at the new commit.
- Real repo commands, paths, and identifiers with zero placeholders.

If the check uses a TLA+ model, direct the next agent to read every run with [`/statechart`](../statechart/SKILL.md) by name. It extracts shortest counterexample paths on failures and draws the state graph on passes. Never hardcode `/statechart`'s internal script flags or paths into the generated skill, because releases evolve independently.

## Prove it before you hand off

Run the generated skill's instructions end to end as the next agent would against a temporary scratch change in the real code that breaks the property. Confirm the check catches the break, then revert the scratch change and confirm the check returns to baseline (passing, or failing only on the findings you are reporting). If the skill misses the break or fails to run, fix the skill or verification, not the scratch change.

## Report and hand off

Write the full verification report to the Antigravity Brain Artifact `<appDataDir>/brain/<conversation-id>/formal_verification_report.md` (`ArtifactMetadata` with `UserFacing: true` and `RequestFeedback: false`). Record:

- Verified properties and harms in plain sentences.
- Tool choice rationale, bounds, assumptions, and exclusions.
- Findings and counterexamples in the code's terms.
- Coverage map, sync-commit SHA, rerun command, and the scratch-break mutation receipt.

In chat, summarize the result, name any close second target if you spotted one, link `[formal_verification_report.md](file://<appDataDir>/brain/<conversation-id>/formal_verification_report.md)`, and point the user to [`/maintain-formal-verification-skill`](../maintain-formal-verification-skill/SKILL.md) for catching future code drift.
