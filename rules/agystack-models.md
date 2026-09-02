# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
# Antigravity invoke_subagent model tiers:
# - inherit    (Runs on the active parent chat session model, e.g. Gemini 3.7 Flash High)
# - pro        (High-capability tier: deep reasoning, large refactors, complex design)
# - flash      (Fast / balanced reasoning tier: exploration, reading, standard generation)
# - flash_lite (Lightweight tier: fast mechanical scans and lookups)

feature, refactoring: pro
bug-fix: pro
perf-issue: pro
hillclimb: pro
judgment and prose: pro
hardest tasks: pro
how explorer: flash
how explainer: pro
how critics: pro, flash, inherit
why investigators: flash
why synthesizer: pro
reflect tooling: pro
reflect judgment, divergent, synthesizer: pro
arena runners: pro, flash, inherit
arena cross-judge pool: pro, flash, inherit
swarm workers: flash
architect runners: pro, flash, inherit
interrogate reviewers: pro, flash, inherit



