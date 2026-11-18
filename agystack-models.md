# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
# 2026.11 Google Gemini 4 Core Model Matrix & Orchestrator (Ultra 5x/20x tiers):
# - Orchestrator (dynamic scheduling mode): Dynamic multi-model collaboration & task handoff
# - Gemini 4 Carbon (heavy reasoning & planning): Flagship reasoning with Low/Medium/High thinking depth
# - Gemini 4 Argon (systems & software engineering): Frontier reasoning for continuous agent workflows
# - Gemini 4 Hydrogen (high-speed execution & verification): Fast subtask execution & automated verification

feature, refactoring: gemini-4-argon
bug-fix: gemini-4-argon
perf-issue: gemini-4-argon
hillclimb: gemini-4-carbon
judgment and prose: gemini-4-carbon
hardest tasks: gemini-4-carbon
how explorer: gemini-4-hydrogen
how explainer: gemini-4-argon
why investigators: gemini-4-hydrogen
why synthesizer: gemini-4-argon
reflect tooling: gemini-4-argon
reflect judgment, divergent, synthesizer: gemini-4-carbon
arena runners: gemini-4-carbon, gemini-4-argon, orchestrator
arena cross-judge pool: gemini-4-carbon, gemini-4-argon, orchestrator
swarm workers: gemini-4-hydrogen
architect runners: gemini-4-carbon, gemini-4-argon, orchestrator
interrogate reviewers: gemini-4-carbon, gemini-4-argon, orchestrator
