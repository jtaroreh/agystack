# Multi-Model Provider Routing

agystack uses native Antigravity model tiers (`pro`, `flash`, `flash_lite`, `inherit`) as its default.

## Optional External MCP Routing

For teams that configure external model MCP servers (such as Claude or OpenAI proxies), agystack supports routing adversarial critique panels through those external endpoints.

### Configuration

In `~/.gemini/config/plugins/agystack/rules/agystack-models.md`, specify MCP provider tags for review roles:

```text
how critics: mcp:claude-3-7-sonnet, pro, inherit
interrogate reviewers: mcp:gpt-4o, mcp:claude-3-7-sonnet, pro
arena runners: pro, flash, inherit
```

### Fallback Behavior

If the named MCP tool is unavailable or fails authentication, the runner falls back immediately to `pro`. It logs the fallback in the task notes and never blocks execution.
