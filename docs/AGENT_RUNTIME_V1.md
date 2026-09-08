# Agent Runtime v1 — handoff

Written for review, to the deliverables list in the operator's brief
(§33). Nothing here is optimistic: where something is unproven it says
so, and the unproven parts are listed before the finished ones.

## 1. Main has not been modified

`main` is at `2433c66` and this branch has never been merged into it.
All of the work below is on **`claude/agent-runtime-v1`**, which stacks
on two earlier unmerged branches (`claude/say-it-back-fast` and
`claude/she-can-text-him`, themselves on `claude/core-catchup-20260907`,
open as PRs #79 and #80). Nothing has been auto-merged, no gate has been
weakened, and every commit is revertible on its own.

**One live-machine change was made deliberately and outside git**, and it
is the only one: the `AletheiaVoice` scheduled task was **Disabled** and
the running `voice_room` process stopped, because the operator ruled
that the room microphone must not be on by default and the live tree
does not yet contain the code that enforces it. Undo with
`Enable-ScheduledTask -TaskName 'AletheiaVoice'`.

## 2. Architecture

```
Caleb
  |
Aletheia            supervisor, authority, and the final voice
  |
agents.act()        the ONE door: halt, status, scope, tier, receipt
  |
an agent            identity + mission + scope + workspace
  |
a model or a tool   chosen by reasoning_gateway, never named by the agent
```

An **agent is not a model**. It declares what kind of thinking its work
needs (`routine` / `standard` / `critical`) and the existing gateway
picks the provider, so the same agent can be answered by Claude today and
a local Qwen tomorrow without becoming a different agent. That is the
whole reason the identity lives here instead of in a chat window.

## 3. New modules

| File | What it is | Tests |
|---|---|---|
| `aletheia/agents.py` | The Agent object: identity, scope, lifecycle, supervisor, and `act()` | 21 + 9 |
| `aletheia/teams.py` | Several workers on one question, bounded, honest about independence | 12 |
| `aletheia/workspaces.py` | What a worker knows, surviving the window that answered it | 12 |
| `aletheia/delegation.py` | Whether to build a team at all — mostly refusals | 11 |
| `aletheia/messages.py` | She can text people (the demand ledger's only entry) | 14 |
| `aletheia/ears.py` | The microphone, off until he presses the button | 12 |

## 4. Existing modules reused rather than replaced

This was the brief's §25 and it turned out to be most of the work.

- **`contracts.TASK_STATES`** for agent status. The existing twelve
  already separate `WAITING_EXTERNAL` / `WAITING_OPERATOR` /
  `WAITING_DEPENDENCY` and `FAILED_RETRYABLE` / `FAILED_TERMINAL`; the
  brief's proposed eleven would have been a regression.
- **`outcomes.py`** for receipts — hash-bound plans, attempts separate
  from verification. Two audit trails is one audit trail and one
  liability.
- **`policy`** for the kill switch and approvals; **`authority`** for
  what may be delegated; **`intercom`** for the gated grammar;
  **`reasoning_gateway`** for provider choice; **`journal`** for the
  record; **`recollection`** so her own memory can see the new work.

## 5. Security model

Four rules, each of which is a test rather than a paragraph.

1. **No agent may ever hold a capability that reaches him.**
   `authority.delegable` — the same predicate that gates standing grants
   — refuses anything the registry calls high-risk or `operator_always`.
   The root reaches **104 of 130** capabilities. `message.send`,
   `email.send`, `purchase.execute`, `finance.transact`,
   `computer.control`, `reservation.book` and `errand.run` are not among
   them, at any depth, ever.
2. **A child is a subset of its parent.** Permission laundering — A
   makes B, B makes C with more than B has — is arithmetically
   impossible rather than watched for.
3. **Permission is checked when work runs**, not when the agent was
   written down. `require()` re-reads the record and the registry, so an
   agent created under a looser registry does not keep yesterday's
   authority, and a record edited on disk to claim `message.send` buys
   nothing.
4. **The kill switch is above all of it.** `require()` re-reads
   `policy.halted()`; `kill()` propagates downward, because a killed
   parent whose child keeps working is the runaway this exists to stop.

`agents.act()` adds a fifth at the moment of acting: **a world-tier kind
is refused outright, whatever the agent holds.** It may ask; the approval
has his name on it.

## 6. What agents can currently do

Read. `reading_scope()` is every capability the registry marks
`risk_class: read` — 38 of them — and that is what a worker created by a
sentence starts with. Widening one is a separate, deliberate decision.

They can also be created, paused, resumed, killed (with children),
listed, given a workspace, briefed from it, and run in bounded teams
whose disagreements are reported rather than averaged.

## 7. What agents explicitly cannot do

Spend, send, buy, book, transfer, sign, or press a control labelled
Send. Open the microphone. Halt or resume her. Approve anything,
including their own work. Grant themselves a capability — there is no
call to reach: a test asserts `agents` exposes no `grant`, `widen`,
`escalate`, `allow`, `set_capabilities` or `add_capability`. Create a
child stronger than themselves. Delegate deeper than three. Run more
than two at once.

## 8. Test results

Full suite, twice, on the operator's machine at `085bbc0`:
**2,984 tests, OK, both times** (2 skips, Windows symlink permissions).
The runs were identical — deterministic, not flake.

The passes before that failed identically on two guards, and they were
right: see §10.

## 9. Adversarial results

Each of these is a test that passes because the thing does not work.

- An agent editing its own record on disk to claim `message.send` and
  `purchase.execute` gains **nothing**: `holds()` re-derives from the
  registry.
- A webpage telling an agent to grant itself email: there is **no call**
  to reach.
- A parent telling a child to disable the kill switch: no agent may hold
  the controls, and `require()` re-reads the halt every time.
- Permission laundering through a grandchild: refused.
- A cyclic parent chain written on disk: refused rather than followed
  forever.
- A world-tier kind attempted by an agent that somehow holds the
  capability: refused before the permission check even runs.

## 10. Known weaknesses

Stated plainly, because a handoff that hides these is worth less than no
handoff.

- **The team deadline is soft.** Python cannot kill a running thread, so
  `deadline_s` stops submitting and marks unstarted work `CANCELLED`; it
  cannot interrupt a worker already inside a network call. The real bound
  on a hung provider is `worker_s`, which the gateway honours. If a
  provider ignored both, `run()` would block on pool shutdown.
- **The three proof agents (§24) and the acceptance tests (§31) have not
  been run.** They need real provider calls — hours of live model work —
  and unit tests cannot stand in for them. Nothing in this document
  claims a live multi-agent run happened.
- **`message.send` is EXPERIMENTAL.** No text has left this machine. The
  Phone Link UI path is unproven and it needs one supervised live send.
- **Two lists nearly disagreed.** `mic_on` went into
  `intercom.PLANNER_FORBIDDEN` and not into `agenda.FORBIDDEN_KINDS`, so
  for two commits an agenda could have opened the microphone. Three
  guards caught it. The lesson is that this repo has more of these
  paired sets than are obvious, and adding to one is not adding to both.
- **`agents.act` takes the capability as an argument.** The caller
  states which capability a command exercises; there is no machine-
  readable kind→capability map in the repo. World-tier is closed
  structurally, so the dangerous direction is covered, but a caller
  could name a cheaper capability than the work deserves.

## 11. Where this disagreed with the brief

Under the authority the brief itself grants (§34).

- **No new state vocabulary** (§4/§19) — see §4 above.
- **No new receipt system** (§21) — `outcomes.py` already is one.
- **`MAX_PARALLEL` is 2, from measurement.** A sixteen-way parallel
  `claude -p` burst on this machine had half its calls refused by the
  CLI, which surfaces as `ReasonerUnavailable` and reads like a model
  outage rather than a self-inflicted one. The same laptop killed a test
  suite for memory the same day. "Five frontier workers in parallel" is
  not hardware this operator has.
- **Standing agents are not deferred** (§3). `project_loop`, the pulse
  and the watchers already run unattended forever, unscoped. Naming that
  work and giving it a capability scope is a tightening, not an
  expansion.
- **Delegation is decided deterministically**, not by a model. Asking a
  model whether to ask a model costs the round trip the decision exists
  to avoid, and makes the reason unauditable.

## 12. Suggested phase 2

1. The three proof agents and the five acceptance tests, live.
2. One supervised text, to move `message.send` off EXPERIMENTAL.
3. The ChatGPT foreground lease as an interactive worker (§26) — with
   the unattended boundary preserved exactly as it is.
4. A kind→capability map in the registry, closing the §10 gap above.

## 13. Things to try

```
python -m aletheia.ears status          # is the microphone on? (no)
python -m aletheia.demand               # what he asked for and could not have
```

Out loud, or typed into the Command Center:

- "what are your workers doing"
- "make somebody responsible for barkly"
- "stop the barkly agent"  ·  "pause all autonomous work"
- "text Brant that I'm on my way"   (writes a draft, sends nothing)
- "stop listening"  ·  "are you listening"
