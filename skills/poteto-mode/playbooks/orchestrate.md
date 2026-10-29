### Orchestrate

**You own the program, never the code. Author briefs, drain the queue, keep the frontier green, decide.** For a whole project handed to one standing coordinator chat: multi-day, many stacked PRs, dozens to hundreds of subagents, the human checking in twice a day instead of every five minutes. One task driven to a predicate is Autonomous run. One ambitious run needing a bespoke workflow is figure-it-out. Route here when the work outlives any single agent. Work one agent could finish inside the session's budget is not a program; measured head-to-head, this playbook's ceremony turned a half-hour 12-unit job into 1 landed unit while a plain agent landed all 12. Below that line, route to Autonomous run.

Ceremony must scale with the program. Every gate below prices in coordinator minutes; on cheap near-identical units, collapse it as each section directs rather than paying list price.

Three rules carry the rest.

- Completions are queue events, not interrupts.
- Every spawn and every resume carries the standing orders verbatim.
- The brief is the product. A vague brief fails quietly, because a worker cannot ask you a question.

Open a todolist with the steps below copied in verbatim. A step you skip stays listed with `skip: <reason>`.

#### Roles and placement

- **Coordinator (this chat).** Local. Frames, authors briefs, drains the inbox, owns the human report, makes judgment calls. It never authors or edits code: conflicted merges, restacks, and code changes are always tasks. Mechanically landing a verified unit (fast-forward or clean cherry-pick of a worker's commit, then push) is bookkeeping the coordinator may do itself on repos where local git is cheap; queueing finished work behind an idle stacker is how a deadline harvests nothing. The loop is agentic end to end. Agents are spawned, resumed, and drained through native Antigravity subagents (`invoke_subagent` with `TypeName: "poteto-agent"`, or background commands). State reads and writes go through native brain artifacts (`notes.md`, `ledger.md`, `decision_trail.md`) at drain points to conserve context.
- **Sub-coordinator.** Always local, durable, one per track, and only when the program exceeds what one coordinator's drains can manage. A track the coordinator can drain itself needs no middle layer: each nested layer re-pays a full orientation preamble, and a blocking sub-coordinator hides its children while the parent idles. Owns its track's units and boards, authors its workers' briefs, spawns its own workers and verifiers (nesting works to depth 3, and a nested spawn has the full subagent schema including `workspace: branch`). Rolls up aggregates at wave boundaries; never forwards raw child reports. Cap in-flight children at what one drain can process, roughly ten, as a rolling window; never as blocking batches, which cost the slowest child of every batch.
- **Worker / verifier.** Isolated branch/worktree (`workspace: branch`) unless the task needs shared local state: browser/CLI runtime verification; reading local transcripts; simulators and local IDE state; auth that exists only locally. Isolated agents cannot read uncommitted local store, so their briefs inline what they need or point at repo paths. Prefer fewer, broader workers; one writer per worktree or branch (principle-separate-before-serializing-shared-state). Run a unit's verifier on a different model tier from its worker.

Depth stays at coordinator, track, worker. Author the track decomposition per project (build, landing, and verification are common cuts, not a required shape); hard-coded swarm trees were tried and parked as too rigid.

#### Store layout

Create `orchestrate/<project-slug>/` in the current agent's brain artifact store (e.g. `<appDataDir>/brain/<conversation-id>/orchestrate/<project-slug>/` or `.agents/orchestrate/<project-slug>/`). Every file has exactly one writer; owners publish facts, readers aggregate at read time. Bookkeeping uses native markdown documents and tables, staying readable and auditable directly in Antigravity:

- `preferences.md` is the standing-orders register: numbered lines, one constraint each (model policy, stack shape and count, verification bar, forbidden paths, escalation policy). Paste it verbatim into every spawn and every resume; directives decay across resumes, and each dropped one costs a human turn. When you catch yourself restating an instruction, append the line before you act (principle-encode-lessons-in-structure).
- `notes.md` is the durable PR, issue, and unit registry. Tracks unit status, track assignments, head SHAs, and active branches in markdown tables.
- `frontier.md` is the computed merge frontier, per Stack safety.
- `ledger.md` is the verification ledger, per Verification.
- `gates.md` parks human gates (question, options, default on no answer) so a completion flood cannot wipe interactive state.
- `decision_trail.md` is the trail via the show-me-your-work skill.
- `status.md` is derived from `notes.md` and `ledger.md` at each drain, never hand-maintained; regenerate it from the tables instead of narrating events into it, because hand-churned boards get rewritten on every event and go unreadable.

#### The brief

Your prompts to agents are your only product, and a sloppy brief compounds into slop across the whole tree. Every spawn carries all of it; a field you cannot fill is a unit you have not scoped yet.

```
GOAL         one sentence, the outcome, executable by a stranger with no chat access
SCOPE        paths this unit may write; paths it may not; its exclusive worktree or branch
CONTEXT      pointers to files and PRs; upstream reports pasted in full when this unit
             depends on them, because workers cannot see siblings
ACCEPTANCE   checkable criteria, one per line
VERIFY       exact commands or the control-skill path, plus known gotchas
TIMEBOX      rough cap on runtime; on expiry, return partial findings and stop rather than run on
FORBIDDEN    no gt, no rebase, no force-push, no fixes outside scope, plus unit-specific bans
REPORT       status, branch, head SHA, PRs, verdict, what you actually ran, deviations,
             suggested follow-ups
STANDING     <preferences.md pasted verbatim>
```

Size the brief to the unit. A one-command unit gets the template collapsed to a paragraph that still names goal, scope, the verify command, and the report shape; a 4KB scaffold around a two-line edit costs more to write and obey than the edit. Local spawns may reference the standing-orders file by store path; verbatim paste is for cloud spawns and every resume.

A sub-coordinator brief adds its track boundary and unit list, its spawn budget with the cloud default and the local exception list, the drain protocol, and the rollup format (per child: name, status, PR, head SHA, verdict, one line; plus track status and frontier delta).

A dependency is a context relay, not just ordering: undeclared upstream context makes the worker guess. Missing fields are a refuse-to-spawn condition. Audit one sampled worker brief per sub-coordinator per wave, concurrently with the wave it samples, never as a gate in front of it; a failing brief stops that track and fixes the sub-coordinator's instructions, not just the worker, because brief quality decays late in a run. Never resume-chain a brief; respawn fresh with consolidated scope.

#### Steps

1. **Frame.** State the done predicate as something countable ("all 126 units merged, each ledger-verified `unit-test-verified` or better"). Quantify scope: units, rough effort, expected stacks, and the wall-clock budget. If one agent could finish inside that budget, stop here and run Autonomous run instead. Collapsing must not depend on another document being present: it means do the work directly in this session, plain workers where they help, verification inline, landing as you go, and none of the store, register, or pilot machinery below. Schedule landing against the budget: by roughly 70% of it, stop spawning and land what is verified, because finished-but-unlanded work counts as zero. Name the tracks per project. A contested decomposition or one-way door goes through the arena skill before the pilot. Present the framing once; reversible prep proceeds without waiting.
2. **Install the runtime.** Initialize the orchestrate artifact directory (`<appDataDir>/brain/<conversation-id>/orchestrate/<project-slug>/`). Open the trail via the show-me-your-work skill (`decision_trail.md`), write the standing orders (`preferences.md`) before any spawn, and seed `frontier.md` and `notes.md` from existing branches and PRs using `gh pr list`.
3. **Pilot.** Push one unit through the whole path: brief, worker, verification, stack entry, ledger row, merge. The pilot exists to falsify the brief template, the verify recipe, and the unit size while that costs one agent instead of fifty. Fix the contract from pilot evidence before any fan-out. Scale the pilot to the unit: on programs of near-identical cheap units, the first unit is the pilot, run as a normal unit with its verify command inline, and fan-out starts the moment it lands. The dedicated pilot pipeline (separate verifier agent, audit gate) is for expensive or novel unit shapes, not for clone-units where a serialized pilot has nothing to falsify.
4. **Scale.** Spawn a rolling window of workers up to the in-flight cap via `invoke_subagent` (`TypeName: "poteto-agent"`), refilling as children finish; blocking batches pay the slowest child of every batch. Spawn track sub-coordinators only past the one-drain threshold in Roles. Recompute ready work after each drain; relay upstream reports into downstream briefs; keep sibling communication upward only. The sampled brief audit runs alongside the wave it samples and stops the next refill on failure, not the current one.
5. **Drain.** Run the queue discipline below at every drain point.
6. **Land.** Landing is continuous, never a terminal phase: integration starts with the first verified unit and runs alongside the remaining waves. On heavy repos the stacker is a standing role from wave one, integrating as units verify; on repos where local git is cheap, the coordinator lands verified units itself per Roles. Keep the frontier green before upper-stack work; Stack safety governs. Advance `frontier.md` only on merge or reported new head SHAs.
7. **Close.** Drain final subagent messages, reconcile every spawned agent to a terminal row in `notes.md` (done, abandoned, zombie-reconciled), confirm the predicate on the real artifact, confirm every landed PR has a verdict for its current head SHA in `ledger.md`, audit the trail per show-me-your-work including its cross-model review, encode recurring corrections into `preferences.md` or the brief template. Leave the store intact; it is the postmortem.

#### Queue and drain

- On a completion notification (`send_message` from worker), log the completion pointer in `notes.md` and return to what you were doing. Never deep-review inline; a completion that needs review becomes a verifier unit. Never review a diff inside a drain.
- Drain in batches at four points: the end of a critical section, a track rollup, a frontier watcher wake (arm it via `/schedule` or `/goal`, with a long heartbeat fallback), and before a human report. Process pending notifications from subagents. Arrivals during a drain wait for the next one.
- Critical sections you finish first: authoring a brief, a stack operation, a conflict decision, writing a gate, updating ledger or frontier.
- Each drain classifies every arrival (landed, needs-verify, failed, zombie, noise), updates rows in `notes.md` and `ledger.md`, refreshes `status.md`, then spawns the next wave in one message.
- Account for every spawned child at its track's rollup: arrived, respawned, or its scope explicitly absorbed. Silently redoing a missing child's work hides both the wasted spend and the coverage gap its result existed to close.
- A drain turn ends with three lines: counts against the states, what changed, gates open. Detail lives in `status.md`; the full reply contract applies at checkpoints and close.

#### Stack safety

- The frontier is a computed object, never narrative. Recompute `frontier.md` via `gh pr` or `gt` after every merge and stack mutation because GitHub base refs drift mid-restack while stack tracking is authoritative: ordered PR list, branch names, head SHAs, a generation number, the lowest unmerged PR.
- Exactly one stacker per stack may run stack operations, serialized within its stack; record the holder in the standing orders.
- Workers never rebase and never run `gt`. Babysitters follow `playbooks/babysit.md`, one per stack, scoped to one immutable frontier generation; they report conflicts to the stacker rather than restacking.
- PR closes and retargets go through the stacker only; closing a base PR orphans every chain above it. Merges and stack surgery are units with briefs like any other.
- One retro watcher follows merged PRs for reverts, post-merge CI breaks, and orphaned follow-ups.

#### Verification

Scale verification to the unit. When VERIFY is a single cheap command, the worker runs it and reports the output, and the coordinator spot-checks receipts; a dedicated verifier agent (on a different model family than the worker) is for units whose verification is expensive, judgment-laden, or high-blast-radius. A verifier agent whose entire product would be rerunning one command is ceremony, not verification.

Record verdicts in `ledger.md`, one row per verdict, keyed by PR number plus head SHA: `live-ui-verified | unit-test-verified | type-check-only | verifier-blocked | verifier-failed`. CI green is an input to a verdict, not a verdict. Behavioral work needs better than `type-check-only`. `verifier-blocked` is not a pass; respawn when the environment heals. `verifier-failed` gets a fix unit, not a re-verify. A worker may self-report; a verifier overrides it on the same key. A new head SHA voids the row, so re-verify after restack. The ledger answers "was this verified", not memory and not the transcript.

A unit is not done until its output is externalized the moment it lands, never batched to the end of the run: a worker pushes its branch, a verifier writes its ledger row, receipts land in the store. Work that exists only on one VM when that VM dies was never done.

#### Liveness and failure

- Never resume an agent to check on it; a resume restarts an idle agent. Probe read-only: `ledger.md`, `notes.md`, `gh`, pushed branches, the background agent's status via `manage_task` or reactive wakeup messages. Transcript mtime is not liveness.
- A silent death gets a synthetic postmortem row in `notes.md` (unit, failure mode, last evidence, options). Replan on evidence as it arrives; never wait for full quiescence.
- Retry by mode: cap-hit or oom, respawn with smaller scope; network-drop, retry as-is; tool-error, retry on a different model; unknown, retry once. Two retries, then abandon the unit and replan around it.
- A zombie that returns hours late reconciles against the current frontier and ledger before anything is accepted; the world moved while it slept. Salvage unique findings through a fresh unit, never a blind merge.
- When continued spawning would produce garbage tree-wide (bad upstream output, broken acceptance, dead infra), write a stop line at the top of the standing orders, let in-flight work finish, fix the cause, clear it.
- Bound your own infra retries the same way you bound a child's. After a few consecutive tool aborts, stop retrying: write a terminal handoff to durable state (what is done, where it lives, the exact command to resume) and end the run. Hours of retry loops against a dead executor produce nothing a handoff would not.
- After an agent session restart: local agents are dead, cloud work is not. Re-read the standing orders and `notes.md`, recompute the frontier, reattach cloud work by PR and branch rather than agent id, respawn one sub-coordinator per track from its stored brief plus current state, drain, resume.

#### Escalation

Reaches the human, batched into the status page rather than per item: irreversible actions (force-push to shared branches, deploys, deletions, closing someone else's PR), genuine product or preference calls no experiment settles, a standing order that contradicts observed reality, a program-level dead end that survived a replan. Park each as a `gates.md` entry before asking (using the `ask_question` tool for interactive choices or numbered replies in the status page), and route work around it.

Never reaches the human: frontier nudges, restack mechanics, retries, CI flake triage, review-thread triage, format fixes, scope the brief already forbids (refuse and continue), and "should I keep going". When in doubt, act and log; deferring is the measured failure mode.

Mid-run discoveries fix only what blocks the frontier. Everything else parks in follow-ups; at this fan-out a small scope leak multiplies into PRs nobody asked for.

**Reply:** point to `status.md` and `decision_trail.md` artifacts. At checkpoints and close, summarize the predicate and count against it from `notes.md` and `ledger.md`, tracks and what each landed, the frontier (PR list plus SHAs), verdicts summary, what was abandoned and why, gates awaiting the human (the only asks), and the trail path in concise declarative sentences. Numbers from tables, not narrative. Include PR links.
