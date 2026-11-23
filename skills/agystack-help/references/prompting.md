# Word the prompt

A prompt states the intent and the check for done. The playbook supplies the steps, so a few plain sentences beat a spec.

## Put in

- The goal. Say what is broken or what you want changed.
- The done check. Give a condition that can pass or fail. Vague goals like "make it better" and bare durations are not checks.
- The proof to show. Ask for real command output, screenshots or carousels in `walkthrough.md`, the stored value, or a before and after measurement.
- What you already know. A symptom, repro step, log line, or link saves the agent a search.
- Real constraints. Phrases like `"repro first"`, `"don't change any code yet"`, `"zero behavior change"`, and `"let me review before proceeding"` steer playbook selection and gates.

## Leave out

- The how. State what to achieve and leave room for the agent to find a better path.
- A manual list of skills or steps. Hand-written sequences drop or reorder steps the playbook already runs. Name a skill only to override one choice.
- Your guess at the root cause before the agent restates the problem. Leading with a theory narrows the search prematurely.

## Load the context first

- For a noisy report, ask the agent to restate the underlying issue in plain words before editing code. Misreadings show up before any diff exists.
- In a fresh chat, run `/recall` over earlier chats and shared records on the topic before handing over new input.
- Before changing unfamiliar code, ask `/how` for current mechanics and `/why` for the reasons behind the design.
- Ask `/teach` to argue for a choice, such as `"convince me it fixes the cause and not the symptom"`. An argument is easier to test than a summary.

## Design before the plan

- Never take the first design. Ask for prototypes of two or three options with screenshots or timings in `prototype_review.md` and pick from evidence.
- Let prototypes answer open behavioral or layout questions instead of reviewing an abstract plan adversarially, because reviewers invent risks without runnable code.
- For a shared package or API, ask for the README or a tutorial first and build back to the code. The doc becomes the target the agent checks itself against.
- Ask for a written `implementation_plan.md` or multi-PR plan only after the design settles, with every step ending in concrete proof.

## Follow up short

- `"do it"`, `"continue"`, and `"keep going until done"` are complete follow-up prompts once the active chat holds the task.
- Open with `"new task"` whenever the subject shifts so the sticky `/agystack` or `/poteto-mode` session re-matches instead of treating a question as the next build step.

## Before stepping away

- Say `"im going to bed"` or `"im stepping away"` so the agent pauses only on irreversible actions.
- Pair `/goal` with `schedule` for overnight runs, or use `/loop <goal> --verify "<command>"` for inner-loop verification hillclimbs where one command exit code defines success.
- Ask for a fresh git worktree (or `Workspace: "branch"`) off a named base.
- Pre-answer blocking questions such as `"don't ask me before committing"`.
- Ask for a `decisions.tsv` trail via `/show-me-your-work` so you can audit decisions in the morning.
- Include an escape hatch such as `"if you're truly stuck after a few hours, stop and write up why"`.

## Steer in one line

- Restate the goal directly, such as `"i said the goal is to repro. i did not ask for a fix yet."`
- Name a principle directly, such as `"apply prove it works. show me the real output, not the build log."`
- Naming a principle works because `/poteto-mode` reads the principle index at task start and reports which decision the rule changed.
