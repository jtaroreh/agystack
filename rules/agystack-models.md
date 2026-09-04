# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
# Antigravity invoke_subagent model tiers:
# - inherit    (Runs on the active parent chat session model, e.g. Gemini 3.8 Flash High)
# - pro        (High-capability tier: deep reasoning, large refactors, complex design)
# - flash      (Fast / balanced reasoning tier: exploration, reading, standard generation)
# - flash_lite (Lightweight tier: fast mechanical scans and lookups)

feature, refactoring: inherit
bug-fix: inherit
perf-issue: inherit
hillclimb: inherit
judgment and prose: inherit
hardest tasks: inherit
how explorer: flash
how explainer: inherit
how critics: inherit, flash, pro
why investigators: flash
why synthesizer: inherit
reflect tooling: inherit
reflect judgment, divergent, synthesizer: inherit
arena runners: inherit, flash, pro
arena cross-judge pool: inherit, flash, pro
swarm workers: flash
architect runners: inherit, flash, pro
interrogate reviewers: inherit, flash, pro



