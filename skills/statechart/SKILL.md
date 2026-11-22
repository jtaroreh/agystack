---
name: statechart
description: "Check a TLA+ model of a system that moves between states, such as a product flow, a protocol, or a service, and render it as a Mermaid stateDiagram-v2 chart, or create an explicitly labeled unverified design sketch. The report gives the shortest path to each state that breaks a rule. Use for /statechart, or to show a bug as a path through states."
disable-model-invocation: true
---

# Statechart

The chart shows how a system moves between states in the reader's words, so the reader can judge whether the behavior is right.

Choose one of two explicit modes before starting:

- **Mode 1 (Verified TLC model).** Use whenever checking a real protocol, concurrency flow, or code model. Run `scripts/statechart` over `.tla` and `.cfg` files, then embed the checked `chart.mmd` (`stateDiagram-v2`) and `report.md` into an Antigravity Brain Artifact.
- **Mode 2 (Unverified design sketch).** Use only when sketching an early idea before writing a spec. Write native Mermaid `stateDiagram-v2` (or `flowchart TD`) directly into the Brain Artifact, and label the artifact heading and body explicitly as an **Unverified Design Sketch**. Never present a Mode 2 sketch as checked or verified.

## Mode 1. Verified TLC model

### Run the compiler

Work in a scratch folder outside the repo, such as `<appDataDir>/brain/<conversation-id>/scratch/` or a temporary directory. Write a TLA+ spec and its config, then run:

```sh
<skill dir>/scripts/statechart SPEC.tla [--config FILE] [--view FILE] [--out DIR]
```

`scripts/statechart.ts` is TypeScript. `scripts/statechart` is a POSIX launcher that selects Node 22.18 to 22.x, Node 23.6+, Bun 1.1.5+, or Deno 2.0+. On native Windows, run `node --disable-warning=ExperimentalWarning <skill dir>/scripts/statechart.ts` with a supported Node version.

The first run installs TLC and Java via `mise` and requires network access.

### Write the spec

- Write every rule the reader agrees to as an `INVARIANT` (or `PROPERTY`). Add state variables if a rule needs information not yet modeled. Never weaken a rule to make it hold.
- Write `Next` as a disjunction of named actions, such as `YouPressPlay \/ YouPressStop`, so TLC labels steps instead of naming every step `Next`.
- A terminal state with no step out fails `NoDeadlock`. When an `INVARIANT` or `PROPERTY` already uses the name `NoDeadlock`, the deadlock check is named `CHECK_DEADLOCK`. Add a self-loop action in `Next` for valid end states, such as `Done == phase \in {"paid", "failed"} /\ UNCHANGED vars`, and label it in `step()`.

### Pick the chart (`--view`)

Put reader-facing phrasing, phase grouping, colors, and chart title in a `--view` module:

- `state(vars)` controls chart shape. Return a string for a flat chart (`export const state = (v) => (v.paid ? "Paid" : "Paying");`), an array for nested parent states (`export const state = (v) => v.main.split(".");`), or a plain object for parallel regions (`export const state = (v) => ({ Playback: v.playback, Volume: v.volume });`). Keep variable names out of labels. In `vars`, TLA+ sequences are objects indexed from `1` (`v.pc[1]`), and sets are arrays.
- `step(action, from, to)` returns an arrow label in the reader's words (for example `"you press play"` or `"the connect fails"`), hiding code and TLA+ action names. Matching labels merge into one arrow. End conditional steps with bracketed conditions (`"you press play [while the file loads]"`), except in regions charts where the compiler already annotates other-region conditions.
- `group(vars)` returns a phase name mapped by `colors` (`blue`, `orange`, `purple`, `yellow`, `teal`, `tan`, or `pink`). Mixed groups behind one chart state leave it uncolored.
- `title` sets the Mermaid chart title string.

Keep `state()`, `group()`, and `step()` pure functions of their arguments because the compiler caches answers once per state or step. Steps staying inside one chart label are not drawn; split the label if that self-step matters.

Aim for about 20 arrows or fewer. Merge equivalent labels first, while preserving every bug-path state and never merging states that break different rules. If the chart stays too busy, return `null` from `step()` to hide noisy steps while obeying four constraints: keep every chart state reachable from a start state, keep at least one outgoing arrow for states that can step, hide all or none of an arrow's steps, and list hidden steps in the handoff.

### Read the report

- States breaking a rule get class `breaks` (all underlying model states break it) or `mayBreak` (some break it), shown in the Legend. In regions charts, a region state gets marked when every combination with it can break a rule, or when a combination breaks a rule and none of its states is marked yet.
- TLC explores past invariant-breaking states unless bounded by small constants, `CONSTRAINT`, or `ACTION_CONSTRAINT`. Past a constraint, TLC checks rules in the immediate next state without exploring further or checking deadlock there.
- With `VIEW` or `SYMMETRY`, TLC collapses equivalent states onto representatives, so arrows can point to a representative state instead of the concrete successor. `report.md` notes this.
- The compiler checks all rules with one worker, then iteratively removes each failing invariant and reruns (capped at 100,000 distinct states after the first break) to uncover further breaks. Rules omitted when a run hits that cap or errors appear under `Rules not checked`.
- `tlc.out` captures TLC's output on the original config, and `tlc-RULE.out` holds traces for broken properties or bugs outside the chart. Running Java with `-XX:+UseParallelGC` avoids a duplicate startup warning line.

### Embed in Brain Artifacts

The compiler draws full charts up to a 500-state budget (measured on the config as written). Above 500 states, `chart.mmd` draws only bug paths, or is omitted when no rules break while `report.md` still records the state count and verdicts.

Write `<appDataDir>/brain/<conversation-id>/statechart_<slug>.md` (`ArtifactMetadata` with `UserFacing: true` and `RequestFeedback: false`), embedding:

1. Header stating **Verified TLC Model** with spec name, bounds, and rerun command.
2. The generated `chart.mmd` inside a `mermaid` fenced block (`stateDiagram-v2`) so Antigravity's native Mermaid renderer displays it directly.
3. The verdict summary and shortest counterexample paths from `report.md`.

For optional standalone SVG export (when the user requests an SVG image or a large chart is hard to inspect inline), follow [`references/render.md`](references/render.md).

### Hand off

Link `[statechart_<slug>.md](file://<appDataDir>/brain/<conversation-id>/statechart_<slug>.md)` in chat. For each bug, include one line naming the rule, the reader-facing sentence for that rule, and the numbered counterexample path from `report.md`. State what the model leaves out, and include the rerun command with a fresh `--out` directory.

When the model represents real code, replay every counterexample path against the real code as an automated test or live reproduction, one step per action. If a step cannot happen in code, assume the model drifted until proven otherwise.

## Mode 2. Unverified design sketch

When exploring an unverified design flow before writing a TLA+ spec, write `<appDataDir>/brain/<conversation-id>/statechart_<slug>.md` (`ArtifactMetadata` with `UserFacing: true` and `RequestFeedback: false`) using native Mermaid `stateDiagram-v2` (or `flowchart TD`):

1. Mark the artifact title and top banner explicitly as **Unverified Design Sketch (Not TLC-Checked)**.
2. Enumerate explicit states, legitimate and invalid transitions, triggers, timeouts, and failure or crash recovery paths.
3. Include a checklist noting error handling, illegitimate-to-steady-state reachability, and candidate tests or TLA+ invariants for promoting the sketch to Mode 1.
