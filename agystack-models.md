# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
#
# Supported Model Identifiers:
# 1. Universal Tiers (Default, compatible with Gemini 3.8 Flash and any active parent session model):
#    - inherit    (Runs on the active parent chat session model, e.g. Gemini 3.8 Flash High or Gemini 4 Neon)
#    - pro        (High-capability tier: deep reasoning, large refactors, complex design)
#    - flash      (Fast / balanced reasoning tier: exploration, reading, standard generation)
#    - flash_lite (Lightweight tier: fast mechanical scans and lookups)
#
# 2. Gemini 4 Effort-Balanced Identifiers (Automatically translated at each tool boundary):
#    - gemini-4-neon-{low,medium,high,xhigh}     (maps to 'pro' on invoke_subagent, 'gemini-4-neon' on /cloud-swarm, exact ID on native swarm)
#    - gemini-4-argon-{low,medium,high}          (maps to 'inherit' on invoke_subagent, 'gemini-4-argon' on /cloud-swarm, exact ID on native swarm)
#    - gemini-4-hydrogen-{low,medium,high,xhigh} (maps to 'flash' on invoke_subagent, 'gemini-4-hydrogen' on /cloud-swarm, exact ID on native swarm)

feature, refactoring: inherit
bug-fix: inherit
perf-issue: inherit
hillclimb: inherit
judgment and prose: inherit
hardest tasks: inherit
how explorer: flash
how explainer: inherit
why investigators: flash
why synthesizer: inherit
reflect tooling: inherit
reflect judgment, divergent, synthesizer: inherit
arena runners: inherit, flash, pro
arena cross-judge pool: inherit, flash, pro
swarm workers: flash
architect runners: inherit, flash, pro
interrogate reviewers: inherit, flash, pro

