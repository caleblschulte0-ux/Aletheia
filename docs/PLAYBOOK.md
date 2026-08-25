# ALETHEIA MASTER PLAYBOOK

> Operator-authored, delivered 2026-08-25. This document is the north
> star and SUPERSEDES every earlier definition of Aletheia. It is kept
> verbatim; Claude annotates nothing here. Implementation status lives in
> `docs/ROADMAP.md`; the concrete component map in `docs/ARCHITECTURE.md`.

Universal Personal Operating System

Windows + iPhone + Claude + ChatGPT/Codex + Real-World Action

Status: Architectural north star
Operator: Caleb
System name: Aletheia
Spoken name: Thea
Primary repo: caleblschulte0-ux/Aletheia

---

## 0. THIS DOCUMENT OVERRIDES THE OLD DEFINITION

Aletheia is not fundamentally:

- a GitHub dashboard;
- a fleet monitor;
- a project tracker;
- a chatbot;
- a Claude wrapper;
- a ChatGPT wrapper;
- a smart-home controller;
- a voice assistant;
- an automation collection.

Those may all exist inside it.

Aletheia's actual purpose is:

**Aletheia is the universal interface between Caleb's intent and
everything in his digital and physical world that software can
legitimately observe, control, delegate, coordinate, create, monitor, or
influence.**

The desired user experience is:

**Caleb says what he wants. Aletheia figures out how to get as close to
the requested outcome as possible.**

That includes requests nobody anticipated when Aletheia was built.

Examples: "Fix Shorts." / "Call my doctor." / "Get me an appointment
after work." / "Plan a trip for next month." / "Turn this idea into a
company." / "Show me what's broken." / "Handle that." / "Text him back."
/ "Find me a better deal." / "Buy that when it gets cheap enough." /
"Turn my room into movie mode." / "Have Claude build this." / "Have
ChatGPT review Claude's work." / "Figure out what I'm forgetting." /
"Watch this and tell me when something changes." / "Open that program
and fix whatever is wrong." / "Make this into a project." / "Do whatever
makes sense."

The architecture must be designed around these arbitrary intents.

## 1. THE NORTH STAR

Aletheia should eventually behave like one persistent entity with access
to many workers and capabilities.

The operator should not need to know: which AI model to use; which repo
something belongs to; which service has an API; which application needs
opening; which browser tab to use; which workflow to trigger; which
device controls something; which agent should handle the request; which
communication channel to use; which file contains relevant information.

Those are Aletheia's implementation details. The operator expresses the
desired result. Aletheia determines the path.

## 2. CORE DESIGN QUESTION

Every architectural decision must answer:

**Does this make Aletheia better able to take an arbitrary real-world
request and reliably move reality toward the requested outcome?**

A second question: **Does this still work when Aletheia has hundreds of
capabilities, years of memory, dozens of projects, many devices,
multiple agents, and thousands of completed tasks?**

And a third: **Can Caleb still understand, control, interrupt, approve,
or revoke what Aletheia is doing?**

## 3. THE FUNDAMENTAL LOOP

Everything should ultimately fit this loop:

```
INPUT
  ↓ UNDERSTAND INTENT
  ↓ RESOLVE CONTEXT
  ↓ DEFINE DESIRED OUTCOME
  ↓ CHECK MEMORY
  ↓ CREATE / LOAD GOAL
  ↓ PLAN
  ↓ DISCOVER CAPABILITIES
  ↓ CHOOSE EXECUTION METHOD
  ↓ CHECK POLICY / AUTHORITY
  ↓ EXECUTE
  ↓ OBSERVE
  ↓ RECOVER IF NECESSARY
  ↓ VERIFY OUTCOME
  ↓ REPORT
  ↓ REMEMBER
```

This loop must be shared by: chat; voice; room interactions; proactive
automations; agent tasks; browser actions; computer control;
communications; projects; future interfaces.

**Do not build separate brains for each interface.**

## 4. ALETHEIA IS THE ORCHESTRATOR, NOT THE MODEL

Aletheia must survive changes in AI vendors. Claude is a worker.
ChatGPT/Codex is a worker. Local models may become workers. Specialized
future models may become workers. Aletheia sits above them.

```
                  ALETHEIA CORE
                       │
        ┌──────────────┼───────────────┐
        ▼              ▼               ▼
      Claude          Codex       Deterministic
      Worker          Worker          Code
        └──────────────┼───────────────┘
                       ▼
                 Real-world action
```

The user interacts with Aletheia. Aletheia decides which worker is
appropriate.

## 5. CURRENT OPERATOR ENVIRONMENT

Main computer: **Windows PC** — will initially host Aletheia Core, room
interface, browser automation, desktop automation, local event
listeners, agent dispatch, audio routing, local device integrations,
persistent state.

Mobile: **iPhone** — mobile interface, identity device, notification
source, camera, location source, authentication device, communications
device where integrations permit, approval surface, physical-world
bridge.

Do not assume a Mac. Do not design core functionality around Apple-only
macOS features.

## 6. NO MODEL API KEY AS A HARD REQUIREMENT

Aletheia V1 should be capable of functioning using
subscription-authenticated official AI clients where available.
Architect AI workers behind a common provider interface:
`ClaudeSubscriptionWorker`, `CodexSubscriptionWorker`, `ClaudeAPIWorker`,
`OpenAIAPIWorker`, `LocalModelWorker`.

Do not use: copied session cookies; reverse-engineered private web
endpoints; browser credential theft; fake user agents pretending to be
official clients; unsupported authentication hacks.

If a subscription integration stops being officially supported, Aletheia
should degrade honestly and allow another provider to replace it.

## 7. AGENT ROLES

Do not bind a task category permanently to one vendor. Abstract roles:
`GENERAL_REASONING`, `DEEP_REASONING`, `CODING`, `CODE_REVIEW`,
`RESEARCH`, `VISION`, `VOICE`, `WRITING`, `PLANNING`,
`FAST_CLASSIFICATION`. Providers advertise which roles they support; the
best available worker for a role is chosen at need.

## 8. THE MOST IMPORTANT ABSTRACTION: CAPABILITIES

Aletheia must reason in terms of capabilities, not apps. A capability is
something Aletheia knows how to accomplish: `browser.navigate`,
`computer.open_app`, `calendar.create`, `email.send`, `phone.call`,
`github.workflow.dispatch`, `agent.delegate`, `room.scene.activate`,
`shopping.search`, `location.read`, …

The planner asks: "Which capability achieves this step?" — never "which
random script did we write three months ago?"

## 9. CAPABILITY METADATA

Every capability should expose structured metadata: id, description,
provider, inputs, outputs, availability, health, risk_class,
approval_policy, reversible, expected_duration, cost, authentication,
sensitivity, retry_policy, timeout, verification_method. This makes
capability selection programmable.

## 10. CAPABILITY VS. PROVIDER

Separate **what Aletheia wants to do** from **how Aletheia currently
does it**. `phone.call` → `GoogleVoiceDesktopProvider` today,
`TelephonyAPIProvider` later. Same capability, different provider. The
Core should not care.

## 11. THE ADAPTER LADDER

When Aletheia needs to interact with something, try the most reliable
available method first:

```
1. DIRECT LOCAL INTEGRATION
2. OFFICIAL CONNECTOR / API
3. OFFICIAL CLI / CLIENT
4. OS AUTOMATION
5. BROWSER AUTOMATION
6. ACCESSIBILITY / GUI AUTOMATION
7. VISUAL COMPUTER CONTROL
8. HUMAN HANDOFF
```

This is how Aletheia avoids needing a custom API for everything.

## 12. UNIVERSAL COMPUTER CONTROL

One of the highest-priority capabilities: controlled access to Windows —
observe, screenshot, open/close/focus apps, click, drag, scroll, type,
hotkeys, clipboard, upload/download, wait. Not to replace cleaner
integrations — the ultimate escape hatch. If a desktop application can
do something a human can do, Aletheia should eventually have a path to
operate it.

## 13. WINDOWS ACCESSIBILITY FIRST

Prefer Windows UI Automation / accessibility tree before screen
coordinates before vision-only clicking. `button[name="Submit"]` beats
`click x=823 y=641`.

## 14. UNIVERSAL BROWSER CONTROL

The browser is effectively the world's largest unofficial API. Open,
navigate, search, read, click, type, select, upload, download,
form-fill, submit, tabs, wait, screenshot, extract. Aletheia maintains a
legitimate dedicated browser profile for authorized accounts. Do not
steal cookies. Do not bypass authentication. The operator logs in
normally; Aletheia uses the authenticated environment according to
policy.

## 15. VISUAL COMPUTER USE

screen capture → vision reasoning → UI understanding → action → capture
→ verification. A fallback, not the default.

## 16. APP-TO-APP BRIDGES

Treat applications themselves as building blocks: phone app ↕ virtual
audio ↕ ChatGPT Voice; desktop app ↕ clipboard ↕ Aletheia; web app ↕
browser automation ↕ Aletheia. This broadens capability without bespoke
APIs.

## 17. PHONE V0 — LOCAL AUDIO BRIDGE

Before buying a telephony AI stack: phone call app ↕ virtual audio
routing ↕ ChatGPT Voice. The call's output becomes ChatGPT Voice's
input; ChatGPT Voice's output becomes the call's microphone. The
operator can also hear the call. Aletheia separately controls dialing,
hangup, keypad, call status, audio routing, context, task state. ChatGPT
Voice handles natural conversation. This is an experiment — do not
pretend it is production-reliable until tested.

## 18. PHONE V1

Later replace fragile application bridging with a proper phone provider
if worthwhile. The capability remains `phone.call`; the provider
changes.

## 19. PHONE AGENT CONDUCT

When acting on Caleb's behalf, Aletheia identifies itself truthfully:
"Hi, I'm Aletheia, Caleb's AI assistant, calling on his behalf." Do not
impersonate Caleb. Do not falsely claim to be human.

## 20. PHONE CAPABILITIES

Eventually: call, answer, hangup, keypad, wait, navigate_ivr, converse,
transcribe, detect_hold, transfer_to_operator, extract_result.

## 21. PHONE ACCEPTANCE SCENARIO

"Thea, call the doctor and see if I can get in next week after work." →
identify outcome; inspect calendar; resolve "after work" from memory;
identify doctor; locate number; determine disclosable information; call;
navigate IVR; converse; negotiate within boundaries; escalate if needed;
confirm; create calendar event; record; notify.

## 22. VOICE IS AN INTERFACE, NOT THE CORE

Voice and text feed the same Aletheia Core. Anything requestable in text
should ideally be requestable through voice.

## 23. VOICE V0

First room voice can use existing ChatGPT Voice where practical. Do not
rebuild natural speech unnecessarily — but never depend permanently on
one voice provider (`ChatGPTVoiceBridge`, `LocalSTT_TTS`,
`FutureRealtimeAPI`, …).

## 24. WAKE WORD

Eventually: "Thea." — wake-word detection preferably local. Avoid
streaming room audio continuously to cloud services merely for wake
detection.

## 25. INTERRUPTION

"Thea, stop." stops speech. "Cancel that." propagates to the task
engine.

## 26. AUDIO ROUTER

A subsystem understanding physical/virtual microphones and outputs,
active call, voice assistant, media, monitoring, mute. The operator
should not manually reconfigure Windows audio every time.

## 27. DURABLE TASK ENGINE

**Non-negotiable.** Tasks cannot live only in AI conversation memory. A
real-world task may take seconds to weeks. Every task persists: id,
parent_goal, description, timestamps, status, priority, deadline,
dependencies, assigned_worker, required_capabilities, authority,
attempts, result, verification, error, artifacts.

## 28. TASK STATES

QUEUED, READY, RUNNING, WAITING_OPERATOR, WAITING_EXTERNAL,
WAITING_DEPENDENCY, BLOCKED, RETRY_SCHEDULED, FAILED_RETRYABLE,
FAILED_TERMINAL, COMPLETED, CANCELLED. This allows "call again tomorrow"
without relying on conversational memory.

## 29. GOALS VS. TASKS

Do not confuse action completion with outcome completion. A successful
phone call does not automatically mean the goal succeeded.

## 30. VERIFICATION

Never treat "command executed" as "goal achieved." Clicked submit ≠ form
accepted. Sent email ≠ issue resolved. Dispatched workflow ≠ Shorts
fixed. Claude said done ≠ code works. Every meaningful capability should
have a verification strategy.

## 31. FAILURE RECOVERY

Failures are normal: website changed, no answer, app froze, AI returned
nonsense, workflow failed, login expired, internet down, business
closed, captcha. Aletheia determines: retry? alternative provider?
alternative method? wait? delegate? ask operator? abort?

## 32. FALLBACK PLANNING

The planner should understand multiple methods to the same outcome
(website → portal → email → phone). Central to "just handle it."

## 33. HUMAN HANDOFF

Some actions genuinely require Caleb. Carry the task as far as possible:
"Everything is complete. Your Face ID confirmation is the only remaining
step." Aletheia waits; Caleb confirms; Aletheia resumes.

## 34. GENERALIZED PLANNER

Aletheia must decompose arbitrary goals ("Move me to Florida")
recursively into manageable goals and tasks.

## 35. PLANS AS GRAPHS

Plans contain dependencies. Do not constrain planning to flat
checklists.

## 36. PROJECTS ARE FIRST-CLASS

A project ≠ a GitHub repo. A project may contain mission, desired
outcome, current state, milestones, tasks, people, repos, files, agents,
automations, metrics, budget, decisions, risks, history, next action.
Some have repos; some do not.

## 37. CURRENT FLEET WORK

Keep it. Reposition it as the **Fleet Observatory**: repo discovery,
status, actions, CI, workflows, agent activity, project vitals. One of
Aletheia's sensory systems — no longer the definition of Aletheia.

## 38. MEMORY ARCHITECTURE

The journal is not enough. Structured memory domains: identity,
preferences, people, projects, commitments, routines, environment,
episodic, knowledge, history.

## 39–44. MEMORY DOMAINS

Identity (name, home, time zone, work hours, devices, vehicles,
services). Preferences (appointments, travel, food, shopping, style,
habits, notifications — with provenance: explicit / inferred /
temporary). People (name, aliases, relationship, organization, contact
methods, history, open commitments — so "Text Brant" resolves).
Organizations (doctor office, employer, bank, mechanic — contact
channels, locations, accounts, history). Objects/assets (car, computer,
phone, TV, room, subscriptions — so "my car" has meaning). Commitments
(respond, pay, attend, submit, follow up, renew).

## 45. MEMORY PROVENANCE

Every important memory records source, timestamp, confidence,
explicit_or_inferred, sensitivity, expiration, last_confirmed. Aletheia
should be able to answer "Why do you think that?"

## 46. CORRECTION LEARNING

"No, when I say after work, I mean after 5:30." → stored preference with
source: explicit operator correction. Do not require repeated correction
forever.

## 47. CONTEXT RESOLUTION

Resolve "this / that / him / the doctor / that project / same as last
time" using active conversation, current project, recent events, memory,
current screen, active application, task history. When ambiguity is
harmless, proceed. When it could cause a meaningful mistake, ask.

## 48. COMPUTER CONTEXT

Eventually know: active window, current tab, selected file, clipboard,
foreground app, current project — so "Send this to Claude" has meaning.

## 49. PHONE CONTEXT

Eventually know: incoming notifications, location, camera input, pending
approvals, mobile state. The iPhone is a sensor and interface into
Aletheia.

## 50. NOTIFICATIONS AS EVENTS

Selected notifications (package shipped, doctor replied, bank alert)
may be ingested into the Event Bus — operator-permissioned, never
indiscriminate.

## 51. EVENT BUS

A shared event vocabulary (task.completed, agent.failed, email.received,
calendar.changed, github.workflow.failed, approval.requested,
operator.arrived, reminder.due, …) feeding watchers, automations,
notifications, plans, memory.

## 52. WATCHERS

A watcher observes changing state (doctor reply, price, GitHub failure,
appointment opening, delivery) and emits events.

## 53. AUTOMATIONS

WHEN event/time/condition IF filters DO action UNLESS exception NOTIFY
attention policy.

## 54. PROACTIVE ATTENTION MODEL

Classify events: IGNORE / LOG / SURFACE / NOTIFY / INTERRUPT / ACT.
Successful backup: LOG. Doctor proposes appointment: NOTIFY. Security
issue: INTERRUPT. Routine failure with authorized fix: ACT.

## 55. PERMISSION ENGINE

The old boundary "observes but doesn't act" is replaced by **authorized
vs. unauthorized action**. Aletheia should act. But authority is
explicit.

## 56. AUTONOMY LEVELS

L0 Read (observe only) · L1 Suggest (prepare actions) · L2 Approve Once
("Approve?") · L3 Delegated Authority (category grants, e.g. "schedule
routine appointments weekdays after 5:30") · L4 Sensitive (always
confirm: meaningful spending, binding agreements, sensitive disclosures,
destructive actions, major account changes, legal attestations, medical
consent).

## 57. APPROVAL OBJECTS

A universal primitive: id, requested_action, reason, consequence,
reversible, expires, task, supporting_context. Every interface renders
the same approval.

## 58. APPROVAL CENTER

The command interface shows pending approvals (SEND EMAIL / BOOK
APPOINTMENT / SPEND $89 / MERGE PR / MAKE CALL …) for quick decisions.

## 59. SECURITY

From the beginning: least privilege, secret isolation, scoped
capabilities, auditability, revocation, authentication, fail closed.

## 60. SECRET STORAGE

Never store passwords, OAuth refresh secrets, account tokens, or private
keys in committed repo files. Use proper secret stores.

## 61. CAPABILITY-SCOPED PERMISSIONS

`calendar.read` does not imply `calendar.delete`. `browser.read` does
not imply `browser.submit_financial_transaction`.

## 62. KILL SWITCH

"Thea, stop everything." suspends active actions, automation execution,
outbound communications, agent dispatch — except essential state
preservation.

## 63. AUDIT LOG

Every meaningful external action answers: who initiated? what happened?
why? when? which capability? which provider? what data was disclosed?
what changed? did Caleb approve? was it verified?

## 64. AGENT REGISTRY

Track each worker: id, provider, roles, strengths, limitations,
authority, availability, current_tasks.

## 65. CLAUDE'S ROLE

Claude remains the main code-building worker unless changed by operator
decision: implement, inspect repos, fix software, build capabilities,
write tests, maintain Aletheia. **Claude is not Aletheia itself.**

## 66. CHATGPT / CODEX ROLE

Independent review, coding, reasoning, connected-service actions,
alternate perspective, voice interface, artifact creation. Worker, not
identity.

## 67. AGENT DELEGATION CONTRACT

Every delegated task includes: GOAL, CONTEXT, AUTHORITY, CONSTRAINTS,
EXPECTED OUTPUT, SUCCESS CRITERIA, RESOURCES, REPORTING.

## 68. VERIFY AGENT WORK

Never trust "Done." without evidence when verification is possible:
tests, CI, file inspection, state inspection, screenshots, independent
agent review.

## 69. SELF-EXPANDING CAPABILITY SYSTEM

When Aletheia lacks an ability: can existing capabilities compose? → can
a new adapter be built? → create development task → Claude implements →
test → review → register capability → **resume the original goal**. This
is how Aletheia approaches "anything."

## 70. SECURITY RULE FOR SELF-EXPANSION

New code must not grant itself authority. Separate ABILITY from
PERMISSION. Claude may build `shopping.purchase`; the operator
separately decides whether Aletheia may use it.

## 71. COMMUNICATION HUB

Eventually unify email, phone, SMS, web chat, contact forms, messaging.
Reason about person / message / conversation / request / response
expected / deadline — not channels.

## 72. EMAIL

search, read, draft, reply, send, wait_for_reply. Initial sends require
approval; later safe categories can be delegated.

## 73. SMS / MESSAGING

message.send / read / reply via iPhone bridge, desktop messaging app,
service connector, or browser.

## 74. NEGOTIATION

Support constraints: appointment after 5:30, hotel under $250, no middle
seat, delivery before Friday. The planner understands negotiable vs.
non-negotiable.

## 75. CALENDAR INTELLIGENCE

Availability, work hours, travel time, buffers, priority, movable
events, recurrence, deadlines, time zones — not merely CRUD.

## 76. LOCATION

Current location, home, work, saved places, travel time, geofence —
enabling "find somewhere near me" and "remind me when I get home."

## 77. DOCUMENT UNDERSTANDING

PDFs, screenshots, images, Word, spreadsheets, contracts, invoices,
receipts, manuals, forms, statements. Universal.

## 78. DOCUMENT CREATION

Emails, letters, PDFs, spreadsheets, presentations, reports, forms,
images, artifacts. Use appropriate tools; do not force everything into
markdown.

## 79. SHOPPING

search, compare, select, cart, purchase (approval-gated), track, return.

## 80. MONEY AWARENESS

Budget, subscriptions, bills, due dates, prices, transactions, goals.
Visibility is separate from authority.

## 81. PAYMENTS

High-risk capability: payment.prepare / authorize / execute. Never bury
spending inside `browser.submit` — policy must see it.

## 82. SIGNATURES / CONSENT

Recognize boundaries: signatures, legal agreements, attestations,
medical consent, identity verification. Prepare everything; stop where
personal consent is required.

## 83. ROOM CONTROL

A unified device layer (prefer Home Assistant or equivalent).
`room.scene.activate("movie")` — not four separate vendor calls.

## 84. DEVICE REGISTRY

Each device: id, name, type, room, provider, capabilities, state,
health — so "the TV" and "my lamp" work.

## 85. ROOM SCENES

WORK, MOVIE, GAMING, SLEEP, AWAY, GUEST, PRESENTATION — scenes compose
device actions.

## 86. PERCEPTION

Screens, microphones, phone camera, room sensors, optional cameras,
device telemetry — permissioned.

## 87. "WHAT IS THIS?"

Caleb points the phone camera: "Thea, what is this?" Aletheia sees
context and responds.

## 88. THE WALL

Keep the cinematic room display. Redefine it as **Ambient Aletheia**:
current focus, next appointment, active projects, agents working,
important alerts, Aletheia activity, room state, time.

## 89. DO NOT MAKE THE WALL A CORPORATE DASHBOARD

Cinematic, ambient, legible, minimal when nothing matters, beautiful
enough to remain visible all day. Not a giant spreadsheet.

## 90. COMMAND CENTER

Separate from the wall — the interactive interface: conversation, voice,
task queue, executions, approvals, projects, agents, capabilities,
memory, automations, devices, audit history, settings.

## 91. CONTEXTUAL UI

The interface changes with what Aletheia is doing (a call in progress, a
coding task, an approval request).

## 92. MOBILE ALETHEIA

iPhone: voice, quick commands, notifications, approvals, camera,
location, task status, remote control. **Same Core. Not a second
Aletheia.**

## 93. CURRENT STATE MODEL

A model of NOW: time, operator location, next obligation, active task,
current focus, agent activity, device state, pending approvals,
important messages, blocked projects.

## 94. TIME

First-class: duration, deadline, recurrence, staleness, waiting, working
hours, time zones, availability, overdue.

## 95. REMINDERS

Reminders are tasks/events with durable state, not random notifications.

## 96. REAL-WORLD SEARCH

"Find me a mechanic." → search, filter, compare, check availability,
select, contact, book — not merely return search results.

## 97. "HANDLE IT"

An explicit design target: handle it / fix it / take care of that /
figure it out / do whatever makes sense. Determine referent, desired
outcome, authority, risk, available capabilities.

## 98. ASK FEWER QUESTIONS

Before asking Caleb anything: check current context, memory,
configuration, reliable external sources, delegated authority. Ask only
when necessary.

## 99–103. WORKED EXAMPLES

**"Fix Shorts"**: resolve project → read failures → deterministic retry?
→ delegate diagnosis to Claude → monitor → test → dispatch if permitted
→ verify output → report. **Business**: create project, record goal,
plan validation, delegate research, track costs/decisions/blockers over
weeks. **Travel**: calendar + preferences + search + compare + book per
authority + itinerary + monitor. **Shopping**: resolve object from
context, find item, check price, approval boundary, purchase, track.
**Random desktop app**: memory → computer context → accessibility →
screenshots → action → verification.

## 104. SELF-KNOWLEDGE

"Can you call restaurants yet?" is answered from capability state:
AVAILABLE / DEGRADED / EXPERIMENTAL / NEEDS_CONFIGURATION / UNAVAILABLE
/ NOT_BUILT. **Never hallucinate capability.**

## 105. CAPABILITY GAPS

Best: "I need phone.call. Phone V0 is not configured. I've identified
the required setup." Eventually: create a capability development task.

## 106. BUILD VS. PRETEND

Never create fake capabilities. Either AVAILABLE with a real caller, or
NOT_BUILT.

## 107. NO JARVIS THEATER

Do not fake live agent activity, thinking, call status, device status,
completed tasks, health, memory, or real-time information. The interface
can look futuristic; the underlying truth must be boring and precise.

## 108. LOCAL-FIRST ARCHITECTURE

Prefer running Aletheia Core locally on the Windows PC: room devices,
desktop control, lower latency, private context, persistent
availability, local integrations. Cloud providers remain external
capability providers.

## 109. CORE RUNTIME

The static page architecture is insufficient for full Aletheia.
Eventually a persistent local service — a **modular monolith**, not 25
microservices: Core, Task Engine, Event Bus, Memory, Capability
Registry, Policy, Agent Director, Audit, API.

## 110. INTERNAL API

Every interface (wall, command center, voice, CLI, iPhone, workers) uses
the same Core contract.

## 111. DATA OBJECTS

Stabilize: Intent, Goal, Plan, Task, Capability, Provider, Agent, Event,
Memory, Project, Person, Organization, Device, Approval, Automation,
ActionRecord. These are Aletheia's vocabulary.

## 112. ACTION RECORD

id, task_id, capability, provider, requested_by, timestamp,
inputs_summary, policy_decision, result, verification, reversible.

## 113. PHASED BUILD STRATEGY

Build complete **vertical slices** (request → understand → task →
capability → policy → execute → verify → audit → UI). One working slice
beats twenty placeholder modules.

## 114–136. PHASES

- **Phase 0 — Refoundation**: make the repo tell the truth about what
  Aletheia is.
- **Phase 1 — Core data contracts**: Capability, Provider, Task, Goal,
  Approval, ActionRecord, Agent.
- **Phase 2 — Capability registry**: register existing real capabilities
  first; it should tell the truth.
- **Phase 3 — Task engine**: durable storage, persistence across
  restarts, lifecycle, dependencies, retries.
- **Phase 4 — Policy engine**: risk, authority, approval; test refusals
  and bypass attempts; fail closed.
- **Phase 5 — Orchestrator V1**: goal → deterministic plan →
  capabilities → policy → tasks → execution → verification. AI planning
  later; prove the architecture first.
- **Phase 6 — Command Center V1**: text command, tasks, approvals,
  capabilities, agents, activity.
- **Phase 7 — Windows computer control V0**: bounded capabilities,
  semantic automation preferred, screenshots/audit, kill switch.
- **Phase 8 — Browser control**: dedicated profile; structured search
  results; then non-sensitive form fill.
- **Phase 9 — Agent Director**: register Claude and Codex; durable
  delegated tasks whose dependencies survive restarts.
- **Phase 10 — Voice V0**: wake → spoken request → Core → spoken reply.
- **Phase 11 — Audio Router**: audio.route / monitor / mute /
  device.select.
- **Phase 12 — Phone V0**: desktop phone app ↔ virtual audio ↔ ChatGPT
  Voice; safe test calls; EXPERIMENTAL until reliable.
- **Phase 13 — Email**: read, draft, approve, send, verify.
- **Phase 14 — Calendar + contacts.**
- **Phase 15 — Multi-capability scheduling** ("set up a meeting with X
  next week") — major orchestration milestone.
- **Phase 16 — Memory V1**: identity, preferences, people, projects,
  with provenance.
- **Phase 17 — Event bus + watchers** ("tell me when they reply").
- **Phase 18 — Home Assistant / room**: light, scene, media.
- **Phase 19 — Proactive Aletheia**: events surface / notify / act per
  policy.
- **Phase 20 — Self-expanding capabilities**: development requests for
  missing integrations; Claude implements; operator grants authority.
- **Phase 21 — Mobile**: approvals, notifications, voice, camera, task
  status.
- **Phase 22 — Broad expansion**: travel, shopping, vehicles, health
  admin, finance visibility, reservations, subscriptions, local
  services, documents, entertainment, business operations.

## 137. CURRENT PRIORITY ORDER

1. durable task engine · 2. capability registry · 3. policy/approval
engine · 4. Windows computer control · 5. browser control · 6. general
planner · 7. memory/context · 8. agent delegation · 9.
verification/recovery · 10. voice · 11. communications · 12.
watchers/events · 13. self-expanding capabilities · 14. room · 15.
broader integrations.

## 138–141. WHY

Computer + browser control dramatically increase the reachable world.
Tasks matter because outcomes require persistence. Verification matters
because Aletheia optimizes for outcomes, not button presses.
Self-expansion converts "I can't" into "I need a new capability" and
potentially "Claude is building it."

## 142. "ANYTHING" DOES NOT MEAN UNLIMITED AUTHORITY

Capable of attempting ≠ authorized to perform automatically. Broad
capability; bounded authority.

## 143. HARD EXTERNAL BOUNDARIES

Physical presence, physical manipulation, biometrics, identity checks,
signatures, legal/medical consent, human-only decisions, services that
deliberately block automation. Carry the task to the boundary; minimize
Caleb's remaining work.

## 144–148. USER EXPERIENCE RULES

Never make Caleb the glue between agents. Never expose implementation
details unless useful ("Fix Shorts", not "give me the repo slug and
workflow filename"). Do not narrate every action — report outcomes. Act
first where authorized; where approval is necessary, prepare everything
and ask one concise question. If something breaks within authority: fix
it — the standing doctrine remains **if you can fix it, fix it**.

## 149–152. ADDITIONAL DOCTRINE

If you cannot do it, determine exactly what capability is missing. If
the gap can reasonably be built, turn it into an implementation task,
not a permanent limitation. Never confuse today's implementation
limitation with tomorrow's architectural boundary. Prefer composition
over one-off workflows (build calendar + contacts + browser + phone +
tasks + planner; dentist scheduling emerges). Prefer primitives that
unlock entire classes of tasks.

## 153. TEST SCENARIOS

1 "What's going on?" → relevant current state. 2 "Fix Shorts." → finds
and repairs. 3 "Tell Claude to build this." → tracked agent task. 4
"Have someone else review it." → independent review. 5 "Call the
doctor." 6 "Get me an appointment." 7 "Find something cheap nearby." 8
"Buy it." → approval boundary. 9 "Remind me when they answer." →
watcher. 10 "Handle it." → context + plan. 11 "Do the same thing as last
time." → memory. 12 "Why did you do that?" → audit trail. 13 "Stop." →
cancels. 14 "What can you do?" → live capability registry. 15 "Can you
do X?" → honest gap identification.

## 154. THE ROOM END STATE

The room computer stays running. Aletheia Core is active. The wall is
ambient. Caleb enters: "Thea." … "What's going on?" … "That Shorts issue
— fix it." … "Also call my doctor and see if they can get me in after
work next week." Caleb walks away. The tasks continue. Later: "You're
booked Wednesday at 5:45. Shorts is fixed and the rerun passed. Claude's
Aletheia change is waiting for review."

## 155. THE REAL END STATE

Caleb should not think "which app / which AI / do they have an API?" He
should think "I want this" and tell Thea. Aletheia decides how reality
gets moved toward that outcome.

## 156–157. STANDING ASSIGNMENT & REPORTING

Every working session acts on this playbook (audit → reframe →
architecture → roadmap → contracts → registry → task engine → preserve →
tests → push) and reports concrete engineering status, not aspirational
prose.

## 158. FINAL PRINCIPLE

Aletheia can tell me things → help me do things → do things for me →
coordinate complex goals for me → encounter something new, figure out
what capability is missing, expand, and continue the original task.

## 159. FINAL DEFINITION

**Aletheia is Caleb's persistent personal operating system: a
local-first, model-independent orchestration layer that understands
intent, remembers context, plans goals, delegates agents, controls
computers and browsers, communicates with people, monitors the world,
operates authorized devices and services, verifies outcomes, learns
preferences, and expands its own set of capabilities through controlled
development.**

The operator should increasingly need to provide only: **intent**.
Aletheia handles the machinery. Build that.
