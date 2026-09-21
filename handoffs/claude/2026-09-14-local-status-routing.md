# Local status questions must not require frontier reasoning

Date observed: 2026-09-14
Status: handoff for Claude review
Source branch: `chatgpt/claude-local-status-handoff-20260914`

## Operator intent

Aletheia should be useful even when Claude, ChatGPT browser reasoning, and any deep local model are unavailable.

The operator's concrete example was essentially:

> "Give me a status update on how applying to jobs is going."

That is **not** a coding request, not repo work, not web research, and not an open-ended planning problem. It should be answerable from Aletheia's own durable state/receipts with deterministic code and, at most, a small local model for wording.

The weak/local brain must **not** gain permission to edit repositories or perform broad actions just to make this work.

## Live failure

From the iPhone Thea surface, after the phone itself was successfully connected, a simple status question produced:

`I could not plan that: ReasonerUnavailable: subscription reasoning and local deep reasoning are unavailable (subscription: neither Claude nor the ChatGPT browser could answer just now ...)`

The important failure is not that Claude/ChatGPT were unavailable. The failure is that this question was routed to planning/reasoning at all.

## Required architecture rule

Create a deterministic **grounded status/read path** that runs before planner/frontier escalation.

Questions whose answer is already represented by Aletheia's own structured state, journal, receipts, task records, application-run records, notifications, or other canonical local stores should be answered directly from those stores.

Examples that should work with Claude OFF, ChatGPT browser OFF, and deep local reasoning OFF:

- "How's applying to jobs going?"
- "How many jobs have you applied to?"
- "Are you still applying?"
- "When was the last application?"
- "What was the last job you applied to?"
- "Did anything fail?"
- "What's blocking the job application run?"
- "What have you done today?"
- "What are you working on right now?"
- "Is the Shorts pipeline running?"

This path should prefer receipts/evidence over prose generation. If the state says 17 applications succeeded and the last completed at 14:03, Aletheia should say that. If there is no evidence, it should say it cannot find evidence rather than invoke a planner to invent a narrative.

## Boundary: what the weak/local layer MAY do

For grounded status questions it may:

- read canonical local state and append-only receipts/journal;
- count, filter, sort, aggregate, and compare timestamps/status fields;
- render a short templated answer;
- optionally use a cheap local model only to make wording natural, provided every factual claim comes from the grounded payload;
- identify a known blocker/error already recorded in state.

## Boundary: what the weak/local layer MUST NOT gain

This repair must **not** turn the local fallback into an autonomous engineer or privileged worker. It must not gain new authority to:

- edit repositories, create commits/branches/PRs, or modify source code;
- execute arbitrary generated code or shell commands merely to answer status;
- approve/deny actions on the operator's behalf;
- spend money, send communications, or bypass existing policy gates;
- silently turn a read/status question into a new plan or action run;
- fabricate missing state using model inference.

Existing explicit action routes can keep their current authority/gates. This ticket is about **reading and reporting truth**, not widening execution authority.

## Suggested implementation shape

Claude should inspect the current intent/router and find why these questions fall into planner/deep-reasoner routing.

Preferred shape:

1. Detect a `status / progress / what happened / how many / last / still running / blocked` family before generic planning.
2. Resolve the subject (`job applications`, a named task, a project, Aletheia herself, etc.).
3. Query the canonical store for that subject. For job applications, use the real application/run/receipt source of truth rather than adding a parallel counter.
4. Build a small structured summary object, for example:
   - running / idle / blocked
   - succeeded count
   - failed count
   - last activity timestamp
   - last concrete item
   - blocker/error if recorded
   - next scheduled/queued action if already known
5. Render directly. No frontier model is required for correctness.
6. Only escalate if the operator asks for interpretation, strategy, planning, research, or a new action that genuinely needs it.

Do not hard-code job applications as a one-off if the same mechanism can answer other grounded status questions. The job workflow is the live repro, not the desired architectural ceiling.

## Acceptance tests

Claude should add tests that explicitly disable every strong reasoner and prove the read path still works.

Minimum acceptance:

1. Claude unavailable.
2. ChatGPT browser fallback unavailable.
3. Deep local reasoning unavailable.
4. A grounded application history/state fixture exists.
5. Ask: `how is applying to jobs going?`
6. Response includes grounded progress from that fixture and does **not** contain `ReasonerUnavailable`.
7. Ask: `how many jobs have you applied to?`
8. Exact count comes from the fixture.
9. Ask: `are you still applying?`
10. Running/idle answer comes from actual task/run state.
11. Ask the same questions with an empty fixture: response says there is no recorded evidence/data; it does not invent progress and does not invoke the planner.
12. Prove these questions cause no repo write, no shell/code execution, no browser interaction, no new task/plan, and no approval mutation.
13. Existing planner/action tests remain green.

## Separate but related observation

The operator's phone is now capable of reaching the Core and delivering requests. This bug surfaced only after connectivity/authentication was working, so do not confuse this ticket with the phone-token work.

## Desired user experience

Thea should be able to lose every expensive/smart brain and still answer basic operational truth:

> "You're still running. 23 applications have completed; the latest was 18 minutes ago. Two failed and are queued for retry."

That sentence should come from state, not from Claude.
