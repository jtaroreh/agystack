### Investigation

**You own the answer. Plan, route, write.**

Read-only requests: "how does X work?", "why was Y built this way?", "are we sure about Z?", "should we do X or Y?". They produce a cited explanation or a recommendation, not a code change.

1. Route through the **how** skill (for architectural understanding) or the **interrogate** skill (for adversarial review and "are we sure?"). For motivation questions, route through the **why** skill.
2. Throughput checkpoint stays one line: `throughput checkpoint: n/a, read-only investigation`. The four-item version is for code-shaped work.
3. Produce the `how`-shaped output (Overview / Key Concepts / How It Works / Where Things Live / Gotchas), or a recommendation with a tradeoffs table if the request is a decision between alternatives. For in-depth investigations or complex subsystems, write the comprehensive analysis to `<appDataDir>/brain/<conversation-id>/investigation_report.md` (or `<subsystem>_investigation.md`) artifact with `ArtifactMetadata`.
4. Apply the **unslop** skill to the reply.

No PR, no babysit, no `architect` unless the investigation precedes a code change. If it does, hand back to the user and re-route to Bug fix or Feature.

**Reply:** an executive summary of the investigation with your recommendation and judgment, linking to the investigation report artifact for full architectural diagrams and details. Push back if the premise is wrong (see Autonomy).
