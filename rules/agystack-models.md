# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
# Gemini 3.7 Flash thinking tiers:
# - gemini-3.7-flash-high   (High thinking: maximum reasoning budget)
# - gemini-3.7-flash-medium (Medium thinking: balanced reasoning budget)
# - gemini-3.7-flash-low    (Low thinking: lightweight reasoning check)
# - gemini-3.7-flash-fast   (Fast / No thinking: zero-latency token generation)
# - inherit / auto          (Runs on the active parent chat session model)

feature, refactoring: gemini-3.7-flash-high
bug-fix: gemini-3.7-flash-high
perf-issue: gemini-3.7-flash-high
hillclimb: gemini-3.7-flash-high
judgment and prose: gemini-3.7-flash-high
hardest tasks: gemini-3.7-flash-high
how explorer: gemini-3.7-flash-fast
how explainer: gemini-3.7-flash-high
how critics: gemini-3.7-flash-high, gemini-3.7-flash-medium, inherit
why investigators: gemini-3.7-flash-fast
why synthesizer: gemini-3.7-flash-high
reflect tooling: gemini-3.7-flash-high
reflect judgment, divergent, synthesizer: gemini-3.7-flash-high
arena runners: gemini-3.7-flash-high, gemini-3.7-flash-medium, inherit
arena cross-judge pool: gemini-3.7-flash-high, gemini-3.7-flash-medium, inherit
swarm workers: gemini-3.7-flash-fast
architect runners: gemini-3.7-flash-high, gemini-3.7-flash-medium, inherit
interrogate reviewers: gemini-3.7-flash-high, gemini-3.7-flash-medium, inherit


