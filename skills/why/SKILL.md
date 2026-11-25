---
name: why
description: "Use for 'why does X work this way', 'why we picked Y', design rationale, regressions, postmortems, or data-backed thresholds. Discovers available MCPs and queries each evidence category (source control, issue tracker, long-form docs, real-time chat, infrastructure observability, error tracking, product analytics warehouse) in parallel, then returns a cited read on decisions and tradeoffs. Use how for runtime behavior."
---

# Why

Answer from the record, not the code. Companion to `how`: `how` explains runtime mechanics, `why` uncovers the constraints and decisions that shaped the design.

## Epistemics

- **Cite direct evidence.** Every factual claim cites a commit hash, PR number, ticket ID, doc URL, chat permalink, or code comment. Never cite code mechanics as proof of author intent.
- **Separate inference from fact.** Use direct language only for explicit citations. Mark deductions with hedged language ("appears to", "likely", "suggests") and show the chain.
- **Keep competing hypotheses and contradictions visible.** When sources disagree or multiple explanations fit, present each with supporting and contrary evidence instead of smoothing into one narrative. Treat a user's embedded hypothesis as one candidate to test, not a conclusion to confirm.
- **Report null results explicitly.** List every searched source that returned empty and every skipped category with its reason. An empty search is evidence.

## Step 1. Anchor in Git History

Identify the target code and question, then anchor in git before fanning out:

```bash
git blame -L <start>,<end> <file>
git log --follow -p -- <file>
gh pr view <number> --json title,body,author,createdAt,mergedAt,labels,closingIssuesReferences,comments,reviews
```

Extract symbols, commit hashes, PR numbers, and ticket IDs to seed investigators.

## Step 2. Parallel Investigator Dispatch

Inspect available MCPs and map them to the seven evidence categories:
1. **Source control** (git, `gh`): commits, PR reviews, inline comments, tests.
2. **Issue tracker** (Linear, Jira, GitHub Issues): tickets, requests, milestones.
3. **Long-form docs** (Notion, Confluence, Google Docs): PRDs, RFCs, ADRs, postmortems.
4. **Real-time chat** (Slack, Discord, Teams): deliberations, incident channels, Q&A.
5. **Observability** (Datadog, New Relic, Grafana): metrics, monitors, dashboards, alerts.
6. **Error tracking** (Sentry, Rollbar, Bugsnag): exceptions, stack traces, release regressions.
7. **Product analytics** (Databricks, Snowflake, BigQuery): telemetry, feature flags, thresholds.

Launch one investigator per available category in a single turn via `invoke_subagent` (`TypeName: "self"`, `Role: "<Category> Investigator"`, `Model`: configured `why investigators` default `flash`, `Workspace: "inherit"`). Never group multiple MCPs under one investigator. Pass the git anchor, question, and `{PARENT_CONVERSATION_ID}`, requiring each investigator to reply via `send_message` with `Recipient: "{PARENT_CONVERSATION_ID}"`. For defensive code (guards, retries, timeouts, rate limits), include incident and postmortem queries. Skip a category only when no MCP exists or it is provably irrelevant, and record the reason.

### Reactive Wakeup and Watchdog

1. Dispatch all investigators in one turn and arm one watchdog: `schedule(DurationSeconds: 300..600, Prompt="Watchdog: why investigators timed out", TimerCondition: "never")`.
2. Yield immediately with ZERO tools (`tool_calls: []`). Never poll with `manage_subagents(list)`.
3. On each arriving `send_message`, record findings and yield with ZERO tools while others remain active.
4. When all arrive, cancel the timer with `manage_task(Action: "kill", TaskId: <timer_task_id>)`. If the watchdog fires, kill unresponsive workers via `manage_subagents` and synthesize surviving reports (proceeding with `N-1` or remaining coverage and logging any dropout as a coverage gap).

## Step 3. Synthesize and Present

Synthesize investigator reports directly in the coordinator. Write the full report to `<appDataDir>/brain/<conversation-id>/decision_rationale_report.md` (`RequestFeedback: false`) and link it in chat with:
- **Question and Anchor.** Target files, lines, symbols, and question.
- **Direct Evidence.** Cited claims from commits, PRs, tickets, docs, or chat.
- **Inferences.** Hedged deductions with explicit reasoning chains.
- **Competing Hypotheses.** Alternative explanations with evidence for and against.
- **Gaps and Null Results.** Unresolved questions and empty searches.
- **Sources Consulted.** One line per category: searched query and result, `"no relevant results"`, or `"skipped: <reason>"`.

When the investigation precedes code edits, close with a **Preserve / Change / Avoid / Risk** constraint summary.
