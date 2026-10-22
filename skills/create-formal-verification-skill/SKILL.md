---
name: create-formal-verification-skill
description: "Generate and apply formal specification models (TLA+, Alloy, Dafny, or state-machine model checkers) strictly for high-consequence concurrency, distributed consensus, complex state machines, and parsers."
disable-model-invocation: true
---

# Create Formal Verification Skill

Generate project-local formal verification specifications and model checkers for high-consequence algorithms. Formal methods verify invariants mathematically across entire state spaces. They carry high authoring and maintenance costs, so strict gating is mandatory.

## Applicability Gating Criteria

Before authoring a formal specification or model checking harness, evaluate the target system against the gating criteria.

### Strictly Reserved Targets

Formal verification is strictly reserved for these high-consequence domains:
1. **Concurrency protocols:** Multi-threaded synchronization primitives, lockless data structures, and non-blocking algorithms where interleavings defy testing.
2. **Distributed consensus:** Raft, Paxos, leader election, quorum replication, and split-brain recovery protocols under network partitions.
3. **Complex state machines:** Multi-actor lifecycle transitions with concurrent events, timeout hazards, and asynchronous state resets.
4. **Critical parsers and serializers:** Untrusted input decoders, binary serialization boundaries, and cryptographic envelope validators where ambiguity introduces security vulnerabilities.

### Reject Non-Applicable Targets

Immediately reject requests to formally verify non-applicable targets:
- Ordinary CRUD APIs and database mutation endpoints.
- Standard UI components, view layouts, styling systems, and render loops.
- Simple linear business logic and sequential request-response handlers.
- Routine configuration parsers, environment loaders, and CLI option parsing.

When a target is non-applicable, reject formal verification immediately. Redirect to standard automated unit tests, integration harnesses, property-based testing, or verification skills (`/create-verification-skill`).

## Authoring Process for Applicable Targets

When a target satisfies the gating criteria, proceed with model authoring:

1. **Define state and actions.** Name state variables and state boundaries. Formulate explicit next-state relations.
2. **Specify safety invariants.** State properties that must never be violated (such as mutual exclusion or absence of deadlocks).
3. **Specify liveness properties.** State conditions that must eventually occur (such as request fulfillment or eventual consensus).
4. **Run model checker.** Model check finite state configurations to exhaustively search for counterexamples.
5. **Map counterexamples to code.** Translate any model checker counterexample directly into a reproducible unit test in the target codebase.
