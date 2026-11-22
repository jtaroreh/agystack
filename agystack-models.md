# agystack model configuration. One line per role. Delete a line to fall back to the skill default.
# Only Gemini 4 models are permitted (never use legacy `flash` or `pro` tiers):
# - gemini-4-neon-{low,medium,high,xhigh}     (Primary preference: balanced frontier reasoning & coding; default thought_level: high)
# - gemini-4-argon-{low,medium,high}           (Deep logic, multi-step math, and strict situational oversight; default thought_level: high)
# - gemini-4-hydrogen-{low,medium,high,xhigh}  (High-speed, high-efficiency execution, exploration, and swarm workers; default thought_level: medium)
#
# When invoking Antigravity's native `invoke_subagent` (whose schema only accepts `inherit` / `flash` / `pro` / `flash_lite`),
# always pass `Model: "inherit"` instead of `flash` or `pro`, or use `delegate_task` / `swarm` to target the exact Gemini 4 model + thought_level.

feature, refactoring: gemini-4-neon-high
bug-fix: gemini-4-neon-xhigh
perf-issue: gemini-4-neon-xhigh
hillclimb: gemini-4-neon-xhigh
judgment and prose: gemini-4-neon-xhigh
hardest tasks: gemini-4-neon-xhigh
how explorer: gemini-4-hydrogen-medium
how explainer: gemini-4-neon-high
why investigators: gemini-4-hydrogen-medium
why synthesizer: gemini-4-neon-xhigh
reflect tooling: gemini-4-neon-high
reflect judgment, divergent, synthesizer: gemini-4-neon-xhigh
arena runners: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-medium
arena cross-judge pool: gemini-4-neon-xhigh, gemini-4-argon-high
swarm workers: gemini-4-hydrogen-medium
architect runners: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-medium
interrogate reviewers: gemini-4-neon-high, gemini-4-argon-high, gemini-4-hydrogen-medium



