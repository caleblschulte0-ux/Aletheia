# Aletheia Brief: Project Continuity + Project Reboot Readiness

Operator-supplied brief, 2026-09-16, kept verbatim in substance so every
session builds from the same target. It follows `docs/JARVIS_BRIEF.md`
(built as waves 1-4 on 2026-09-15/16).

**The main engineering goal: "I should never not be able to work on my projects."**

## Core clarification

There are two separate things here. Do not merge them conceptually or
architecturally.

### 1. Project Continuity

A permanent Aletheia capability. If Claude, Codex, ChatGPT or another
frontier model is unavailable, rate-limited, out of usage or temporarily
failing, Aletheia should not become useless. It may become less capable and
may defer genuinely difficult work, but it should keep making progress
wherever possible using local models, deterministic tools, repository
access, terminal/code tools, browser tools, existing project state, tests,
logs, task queues, retries and fallbacks.

This applies to all projects, not just Aletheia. If a project has a small
bug, a failed scheduled task, a broken path, a simple script issue, a
malformed config value, a small UI regression or another bounded problem,
Aletheia should have enough local coding capability to investigate it and
safely fix it without needing Claude or Codex every time.

### 2. Project Reboot

Not an Aletheia coding project and not the same thing as Project
Continuity. It will be one of the first major real-world missions he gives
Aletheia once the system is ready: *"I do not like the life I am currently
living. Help me change it."* It may involve finding a job (including jobs
buried on employer and regional sites), applying, researching places to
move, finding housing, contacting landlords/realtors/recruiters/hiring
managers, following up, putting interviews/tours/deadlines/reminders in his
calendar, researching cities, organizing decisions, tracking progress over
weeks or months, noticing what he is forgetting, managing logistics, and
many unrelated tasks that cannot be known in advance. That list is
illustrative, not a schema.

**Do not hard-code Project Reboot into Aletheia.** Make Aletheia general
enough that it can succeed. Project Reboot is a proving ground for the
architecture. Do not create `project_reboot.py`.

## Part I: finish the incomplete architectural work

Keep the architecture. Aletheia is the permanent system; models are
replaceable workers.

1. **Remove remaining direct subscription dependencies.** The reasoning
   gateway's policies are right (routine = local first; standard = frontier
   first with local fallback; critical = frontier required). Some systems
   still call subscription reasoning directly (the generic browser decision
   loop; the autonomous code worker's proposal/review path). Audit for
   others and migrate where appropriate. A subsystem requests a CLASS of
   reasoning, not a company/model: `reason(task, policy="routine")`, not
   `ask_claude(...)` or `subscription_json(...)`, unless an operation is
   deliberately frontier-required. Classify; do not blindly replace.

## Part II: "I should never not be able to work on my projects" (primary)

2. **Explicit capability requirements for work.** Tasks state what they
   require (local reasoning, frontier reasoning, browser, filesystem,
   terminal, GitHub, email, calendar, user approval, login, external reply,
   user decision, payment, code execution...). Aletheia understands "I
   cannot do this particular step right now", not "I cannot work".
3. **Non-blocking work queues.** If Task A needs Claude and Claude is out,
   checkpoint A and continue to B. Blocked work is durable and resumable.
   Useful states: READY, RUNNING, BLOCKED_MODEL, BLOCKED_USER,
   BLOCKED_LOGIN, BLOCKED_EXTERNAL, RETRY_LATER, NEEDS_STRONGER_MODEL, DONE,
   FAILED (use whatever vocabulary fits; the behaviour matters).
4. **A real local small-fix coding path.** Keep the code worker's safety
   properties: protected files, no autonomous authority widening, bounded
   file count/context, exact base commit, branches/PRs not silent
   default-branch mutation, kill-switch checks, prompt-injection separation,
   validation, review, testing/evidence, no secret exposure. Add a bounded
   LOCAL repair tier for: obvious tracebacks, typos, broken paths, simple
   data-transformation bugs, one/few-file regressions, narrow failing unit
   tests, minor UI bugs, config parsing bugs, simple scheduled-task
   failures, straightforward import/API mismatches. NOT for: major
   architecture, auth, permission/security, authority, migrations, sweeping
   refactors, major dependency changes, unclear multi-system failures,
   Aletheia's own core safety boundaries (escalate those). Loop: observe ->
   gather evidence -> reproduce -> bounded cause -> branch -> smallest repair
   -> targeted test -> broader relevant tests -> inspect diff -> verify the
   original failure is resolved -> PR/checkpoint -> record. Below a
   reasonable confidence, stop and escalate.
5. **Local AI investigates even when it should not implement.** Inspect
   logs, locate files, reproduce, reduce test cases, identify suspect
   commits, collect code, summarize evidence, prepare a debugging packet,
   queue a task for the stronger model with that packet.
6. **Capability-gap behaviour.** "No tool for this" is not the end. Classify
   the outcome: another existing tool, a browser path, a local workaround,
   ask Caleb, wait for an external event, install/configure a capability,
   queue a small capability addition, queue a larger one for Codex/Claude,
   or refuse because policy forbids it. A next action, not a dead end. Not
   unrestricted self-modification: expansion goes through the existing
   safety architecture.

## Part III: other gaps from the previous review

7. **Browser model-independence.** Keep jobs-as-a-skill, semantic page
   understanding, structured targets, verification after action, durable
   checkpoints, no "clicked means succeeded", approval and anti-bot
   boundaries. Route browser reasoning through the common reasoning layer;
   routine navigation works locally, hard pages escalate.
8. **"Apply anywhere" needs real proof.** Prove the generic/no-adapter path
   against multiple real sites: unfamiliar career pages and ATSs, custom
   forms, account walls, multi-page forms, optional and required unknown
   questions, uploads, email verification, SMS/MFA boundaries, CAPTCHA,
   submit confirmation, crash/restart/resume, duplicate prevention. Jobs
   are a stress test, not the architecture.
9. **Consolidate the tool/capability model** toward one declarative source
   of truth, gradually, without destabilizing working safety systems.
10. **Carefully expand low-risk autonomy.** Move from "reads autonomous,
    writes ask Caleb" toward consequence-based authority: temporary local
    workspaces, fixing a project in a branch, drafts, tasks, internal
    project state, rescheduling its own queued work, notes, running tests,
    preparing PRs and other reversible actions may run under standing or
    bounded authority. Money, binding commitments, destructive operations,
    outward communications and authority changes keep their approval rules.
    Do not weaken existing safety.

## Part IV: Project Reboot readiness (general infrastructure only)

11. **A long-duration mission concept above bounded missions** (Campaign /
    Program / LongTermMission; the name does not matter): mission ->
    outcomes -> workstreams -> projects -> tasks -> recurring activities ->
    monitoring -> waiting states -> decisions -> completed results. Persists
    across restarts and model outages.
12. **Do not predefine what a mission means.** No hard-coded categories
    (career, housing, health, finances, social). Structure is discovered
    from the mission and the discussion with him, as measurable outcomes and
    workstreams.
13. **Cross-domain tool composition.** "Find me a new job" composes web
    discovery, employer discovery, job analysis, profile data, browser,
    tracking, email, calendar, follow-ups. "Find somewhere else to live"
    composes research, listings, neighbourhood data, maps, cost comparison,
    messaging agents, scheduling tours, calendar, reminders, reply tracking.
    No special "new life" code: compose capabilities dynamically.
14. **Waiting and follow-up are first-class.** Waiting for a recruiter, a
    landlord, a result, a showing date, a model, Caleb, tomorrow, a
    verification, any external condition: states, not failures. Remember
    them, wake them when appropriate, keep working meanwhile.
15. **Usable outbound communication.** Draft -> identify recipient ->
    understand history -> send under the correct approval/standing-authority
    rule -> monitor for reply -> understand it -> decide next action -> follow
    up. Do not loosen safety casually, and do not make every mundane message
    require rebuilding context by hand.
16. **Calendar/event handling as general agency.** Interviews, tours,
    events, appointments, reminders, deadlines, follow-up dates, travel
    windows; reason about conflicts and long-running deadlines. General
    calendar capability, not mission-specific code.

## Part V: continuity rules (architectural principles)

1. External AI availability affects capability level, not whether Aletheia exists.
2. One blocked task must never block unrelated executable work.
3. Every unfinished task has a reason it is unfinished and a next condition/action.
4. Local models handle boring work; frontier models are reserved for work where their extra intelligence materially matters.
5. Investigate before escalating: never spend Claude/Codex turns discovering what Aletheia could have collected itself.
6. Small failures become small repairs, not mission-ending events.
7. Long-running work survives process exits, machine restarts, model outages and individual task failures.
8. Jobs, Project Reboot, Barkly, Shorts, aquarium AI and every other project are use cases, not the architecture.

## Acceptance tests (before calling this phase complete)

- **A. Frontier models unavailable.** Claude/Codex/ChatGPT disabled; "work on
  my projects". She inventories available work, completes what she can
  locally, investigates harder tasks, queues what genuinely needs stronger
  reasoning with specific blocked reasons, and does not stop.
- **B. Simple project bug, frontier unavailable.** A real bounded failure:
  she finds it, gathers evidence, makes a narrow local repair, tests and
  verifies it, creates a safe checkpoint/PR per policy, records it.
- **C. Hard bug, frontier unavailable.** She investigates, reproduces if
  possible, narrows the cause, prepares evidence, marks it
  NEEDS_STRONGER_MODEL, and continues other useful work.
- **D. Generic browser task.** An unfamiliar website and a benign multi-step
  objective: local reasoning handles ordinary navigation, actions are
  verified, restart/resume works, no job-specific code.
- **E. Project Reboot simulation (no Reboot logic).** A simulated broad
  objective across unrelated domains (research, contact someone, schedule
  something, track a response, web research, several waiting tasks at
  once): she decomposes it with general capabilities, keeps durable state,
  continues executable work, and tracks what is waiting and why. Build a
  small generic long-term mission layer if needed.

## Final target

He opens Aletheia and says **"Work on my projects."** and she finds
productive work even with Claude and Codex unavailable. Later he says
**"Project Reboot. I don't like the life I'm living. Help me change it."**
and she has the general planning, browser, communication, calendar, memory,
task management, local reasoning, fallback and long-running mission
infrastructure to actually attempt it. The first is being built now; the
second proves whether it was built correctly.

## Addendum, 2026-09-17: research -> strategy -> execution -> measurement

His words: *"Aletheia needs a general research → strategy → execution →
measurement capability. I should be able to say something like, 'These three
AI YouTube channels are doing way better than ours. Study them deeply, figure
out what they do better, and improve our channel,' and have that trigger
substantial research, comparison against our own project, evidence-backed
hypotheses, actual project changes/experiments, and later measurement."*

*"Do NOT build YouTube-specific architecture. This same pattern should work for
Barkly competitors, products, websites, businesses, etc. The current project
loop is good at fixing known defects; make sure Aletheia can also turn external
research into justified project direction and then execute it safely."*

So, as general capability (no domain-specific code; YouTube, Barkly, products,
websites and businesses are use cases):

- **Research**: study named or discovered comparables deeply (browser, web
  read, research, public APIs where they exist), with provenance for every
  observation; open-world content stays untrusted data.
- **Compare**: the same lens applied to his own project (its repo, its public
  surface, its own metrics), so differences are measured, not asserted.
- **Strategy**: evidence-backed hypotheses, each naming the evidence, the
  expected effect, the metric that would show it, and the cost/risk; ranked;
  he can accept, reject or reshape them.
- **Execution**: accepted hypotheses become real project changes or
  experiments through the existing safe paths (charter steps, local repair or
  the frontier code path, branches/PRs, approvals for anything outward-facing),
  with a baseline recorded before the change.
- **Measurement**: later, the metric is read again on a schedule (durable
  waits), compared with the baseline, and the result feeds back into the
  strategy (keep, revert, iterate) and into memory.
