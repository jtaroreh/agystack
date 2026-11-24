# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
#
# Supported Model Identifiers:
# 1. Universal Tiers (Default, compatible with Gemini 4 Hydrogen/Neon/Carbon, Orchestrator, and any active parent session model):
#    - inherit    (Runs on the active parent chat session model, e.g. Gemini 4 Neon, Gemini 4 Carbon, Gemini 4 Hydrogen, or Orchestrator)
#    - pro        (High-capability tier: deep reasoning, large refactors, complex design)
#    - flash      (Fast / balanced reasoning tier: exploration, reading, standard generation)
#    - flash_lite (Lightweight tier: fast mechanical scans and lookups)
#
# 2. Gemini 4 Effort-Balanced Identifiers (Automatically translated at each tool boundary):
#    - gemini-4-neon-{low,medium,high,xhigh}     (512K context; maps to 'pro' on invoke_subagent, 'gemini-4-neon' on /cloud-swarm, exact ID on native swarm)
#    - gemini-4-carbon-{low,medium,high}         (maps to 'pro' on invoke_subagent, 'gemini-4-carbon' on /cloud-swarm, exact ID on native swarm)
#    - gemini-4-hydrogen-{low,medium,high,xhigh} (default on all plans; maps to 'flash' on invoke_subagent, 'gemini-4-hydrogen' on /cloud-swarm, exact ID on native swarm)
#    - Legacy aliases retained for compatibility (leaving Nov 30, 2026): gemini-4-argon-{low,medium,high}, gemini-3.8-flash-{low,medium,high}, Claude 4.6, GPT-OSS-120b.
#    - Partner models (paid plans): Claude Opus 5.5 (thinking), Claude Sonnet 5.5 (thinking).
#    - Orchestrator mode: pairs a frontier planner (Gemini 4 Neon, Gemini 4 Carbon, or Claude Opus 5.5; Enterprise pairs Gemini 4 Carbon High + Gemini 4 Hydrogen High) with a fast executor (Gemini 4 Hydrogen or Claude Sonnet 5.5).

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

