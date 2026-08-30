# Rule Routing Reference

Use rule routing to attach domain constraints to subagents without polluting root prompts.

## Process

1. In step 1 of any playbook (such as Feature, Bug fix, or Architect), identify the target file paths.
2. Run `node skills/poteto-mode/scripts/route-rules.mjs rules/rule-manifest.json <file-paths...>`.
3. Extract the `constraints` arrays from the matched rules.
4. Prepend these constraints directly to the delegate subagent prompt under a `## Subsystem Constraints` header.
