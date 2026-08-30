# Multi-Model Provider Routing

agystack uses official Gemini 3.7 Flash thinking tiers as its native default.

## Optional External MCP Routing

For teams that configure external model MCP servers (such as Claude or OpenAI proxies), agystack supports routing adversarial critique panels through those external endpoints.

### Configuration

In `~/.gemini/config/plugins/agystack/rules/agystack-models.md`, specify MCP provider tags for review roles:

```text
how critics: mcp:claude-3-7-sonnet, gemini-3.7-flash-high, inherit
interrogate reviewers: mcp:gpt-4o, mcp:claude-3-7-sonnet, gemini-3.7-flash-high
arena runners: gemini-3.7-flash-high, gemini-3.7-flash-medium, inherit
```

### Fallback Behavior

If the named MCP tool is unavailable or fails authentication, the runner falls back immediately to `gemini-3.7-flash-high`. It logs the fallback in the task notes and never blocks execution.
