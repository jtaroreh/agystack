---
name: why
description: "Use for 'why does X work this way', 'why we picked Y', design rationale, regressions, postmortems, or data-backed thresholds. Discovers available MCPs and queries each evidence category (source control, issue tracker, long-form docs, real-time chat, infrastructure observability, error tracking, product analytics warehouse) in parallel, then returns a cited read on decisions and tradeoffs. Use how for runtime behavior."
---

# Why

Investigate the motivation, business constraints, and historical intent behind code. Companion to `how`: `how` explains runtime mechanics; `why` uncovers what forces shaped the design.

## Operating Posture & Core Epistemics

Operate as a rigorous historical investigator. Evidence precedes narrative.

- **Cite everything.** Every factual claim must reference a specific commit hash, PR number, ticket ID, document URL, chat permalink, or code comment. Uncited claims are labeled as inference.
- **Precision over polish.** Quote exact sources rather than smoothing into narrative.
- **Separate facts from inferences.** Use direct language only for explicit evidence. Use hedged phrasing ("appears to", "likely", "suggests") when inferring intent.
- **Surface contradictions.** Present conflicting sources side by side without picking favorites.
- **Document gaps.** Report searched sources that returned empty. A null result is valuable evidence.
- **Multiple hypotheses.** When evidence supports multiple interpretations, present each with its supporting and contrary evidence.

Follow the epistemics and confidence framework in `references/epistemics.md`.

## Step 1. Understand Target and Question

Identify the target code and the core question (design rationale, alternatives considered, defensive motivation, dead-code status, or archaeological history). If ambiguous, state your best-guess interpretation and proceed.

## Step 2. Establish Code Anchor

Anchor the investigation in concrete git history before spawning investigators:

```bash
# Blame target lines for last-touch commits
git blame -L <start>,<end> <file>

# Full file history through renames
git log --follow -p -- <file>

# Last N commits touching the file
git log --oneline -20 -- <file>

# Inspect commit message
git log -1 --format=%B <commit>

# Fetch PR metadata and review discussions
gh pr view <number> --json title,body,author,createdAt,mergedAt,labels,closingIssuesReferences,comments,reviews
```

Extract symbols, commit hashes, PR numbers, and referenced ticket IDs to seed investigator subagents.

## Step 3. Spawn Parallel Investigators

Default to querying all available evidence categories in parallel. Inspect available MCPs and map them to the seven categories:

1. **Source control history** (git, `gh`): Commits, PR reviews, inline comments, tests.
2. **Issue / ticket tracker** (Linear, Jira, GitHub Issues): Tickets, client requests, milestones, labels.
3. **Long-form documents** (Notion, Confluence, Google Docs): PRDs, RFCs, design docs, ADRs, postmortems.
4. **Real-time team chat** (Slack, Discord, Teams): Deliberations, incident channels, real-time Q&A.
5. **Infrastructure observability** (Datadog, New Relic, Grafana): Metric spikes, monitors, dashboards, alerts.
6. **Error / exception tracking** (Sentry, Rollbar, Bugsnag): Exceptions, stack traces, release regressions.
7. **Product analytics warehouse** (Databricks, Snowflake, BigQuery): Telemetry, feature-flag exposures, thresholds.

Launch matching investigators concurrently via `invoke_subagent`:
- `TypeName`: `self` (or `poteto-agent`)
- `Role`: `<Category> Investigator`
- `Model`: configured why-investigators model (default `flash`)
- `Workspace`: `inherit`

Each investigator receives:
1. `references/investigator-prompt.md`
2. Category playbook `references/sources/<source>.md`
3. Cross-cutting `references/sources/incident-postmortem.md` if code looks defensive (null guards, timeouts, retries)
4. Code anchor context from Step 2
5. User question

### Skipping an Investigator

Skip a category only with explicit written justification in the final coverage map:
- No matching MCP available in the environment (document as a coverage gap).
- Source is provably irrelevant (e.g. error tracking for an offline build tool).

## Step 4. Synthesize

Spawn one synthesizer subagent via `invoke_subagent`:
- `TypeName`: `self` (or `poteto-agent`)
- `Role`: `Historical Synthesizer`
- `Model`: configured why-synthesizer model (default `pro`)
- `Workspace`: `inherit`

The synthesizer receives investigator findings, code anchor, user question, `references/epistemics.md`, and `references/synthesizer-prompt.md`. It outputs a confidence-weighted, evidence-cited narrative.

## Step 5. Present

Write the full cited report, hypotheses, and coverage map to `<appDataDir>/brain/<conversation-id>/decision_rationale_report.md` (or `<topic>_why.md`) with `ArtifactMetadata: { Summary: "...", UserFacing: true, RequestFeedback: false }`. Present an executive summary in chat and link to the artifact. Preserve all calibrated confidence language.

### Output Format

- **The Question.** Restatement of the user inquiry.
- **The Code in Question.** File paths, line ranges, and key symbols.
- **What We Found (direct evidence).** Bulleted claims with explicit citations (commits, PRs, tickets, docs).
- **What We Can Reasonably Infer.** Inferences supported by indirect evidence, stating the deduction chain with hedged language.
- **Competing Hypotheses.** Alternative explanations with evidence for and against.
- **What We Don't Know.** Unresolved questions and null results from searched sources.
- **Sources Consulted.** Coverage map with one line per investigator:
  `- <Source>: <what was searched>. <what was found, or "no relevant results," or "skipped: reason">.`

If the inquiry precedes code modifications, summarize findings as a Preserve / Change / Avoid / Risk constraint set.

## Common Failure Modes

- Confident storytelling without direct citations.
- Citing code mechanics as evidence of its own intent.
- Recency bias assuming the latest commit reflects original intent.
- Sycophantic confirmation of user-suggested explanations.
- Skipping the gaps section or omitting null search results.
- Grouping multiple MCPs under a single investigator.

## Reference Files

- `references/epistemics.md`: Confidence tiers and phrasing guide.
- `references/investigator-prompt.md`: Prompt template for investigator subagents.
- `references/source-playbook.md`: Category playbook index.
- `references/sources/*.md`: Category-specific playbooks and `incident-postmortem.md`.
- `references/synthesizer-prompt.md`: Synthesizer prompt template and rubric.
