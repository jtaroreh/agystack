# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
# Values are Antigravity subagent tiers: flash, pro, inherit.
# `inherit` or `auto`: the role runs on the parent chat model.
# Alias entries in a panel list still count toward its fan-out.
feature, refactoring: inherit
bug-fix: inherit
perf-issue: inherit
hillclimb: inherit
judgment and prose: inherit
hardest tasks: inherit
how explorer: flash
how explainer: inherit
how critics: inherit, flash, inherit
why investigators: flash
why synthesizer: inherit
reflect tooling: inherit
reflect judgment, divergent, synthesizer: inherit
arena runners: inherit, flash, inherit
arena cross-judge pool: inherit, flash, inherit
swarm workers: flash
architect runners: inherit, flash, inherit
interrogate reviewers: inherit, flash, inherit
