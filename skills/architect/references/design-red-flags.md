# Design red flags

Screen every candidate before synthesis. A red flag is a reason to revise or reject the shape.

## Shallow module

A shallow module exposes a large interface while hiding little complexity. Judge depth by the capability and policy hidden behind the public surface relative to the size of that surface. Prefer a simple interface backed by substantial behavior.

Do not confuse a deep module with a deep call chain. A deep call chain scatters understanding across layers. A deep module concentrates capability behind one interface.

Look for these signs:

- Callers coordinate several methods to complete one operation.
- Public options expose internal stages or implementation choices.
- Learning the interface does not save the caller from learning the implementation.

## Information leakage

Information leakage makes multiple modules depend on the same internal decision. A representation, policy, or protocol detail appears in more than one place, so changing it requires coordinated edits.

Public re-exports of transport or wire types are leakage. Parse external data into domain types behind the interface. Keep storage schemas, framework objects, and protocol details private.

## Temporal decomposition

Temporal decomposition organizes modules by execution order instead of the knowledge they own. Separate load, validate, transform, and save stages often repeat one representation and its invariants across several boundaries.

Group code around domain knowledge and ownership. Methods that run at different times can still belong to one module when they protect the same decisions.

## Pass-through method

A pass-through method forwards the same arguments to another method with the same shape. It adds a layer without hiding complexity.

Remove it or move responsibility to the module that can complete the operation. Keep a forwarding boundary only when it adds policy, adaptation, or a distinct abstraction.

## Split ownership

Two components, services, or stores both claim responsibility for updating, deleting, or syncing the same state. Split ownership leads to drift, race conditions, and split-brain failures.

Assign a single authoritative owner for every piece of state. Other components must query or request mutations strictly through that single owner.

## Two ways to do one task

Exposing multiple paths, methods, or APIs to perform the same semantic operation causes maintenance drift, uneven validation, and cognitive load. Fixes and invariants applied to one path are inevitably missed in the alternate path.

Provide exactly one canonical way to perform each task. Deprecate and delete redundant alternatives.

## Importable internals

Exposing or importing private helpers, internal models, or raw state across module boundaries instead of communicating strictly through defined public boundaries causes tight coupling and fragile refactoring.

Enforce boundary discipline. Keep internal representations private to the package. Expose only explicit, typed public contracts.

## Hand-synced lists

Multiple hardcoded lists, enums, switch statements, or mappings across files that must be manually synchronized by hand whenever an item changes. Hand-synced lists invite subtle bugs because maintainers and agents inevitably miss remote sites during updates.

Prefer derivation, a single source of truth, or code generation. Derive secondary collections and mappings directly from the primary definition.
