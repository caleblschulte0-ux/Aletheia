# Aletheia architecture — the concrete map

North star: `docs/PLAYBOOK.md` (operator-authored, supersedes everything
older). This file maps the playbook onto what exists in this repo TODAY
and what runs where. Status vocabulary is the capability registry's:
BUILT here means code with a real caller and tests; everything else is
named honestly.

## The one loop

Every interface feeds the same loop (Playbook §3): intent → context →
outcome → memory → goal → plan → capabilities → policy → execute →
observe → recover → verify → report → remember. Today's walking skeleton
of that loop is:

```
operator ──► ChatGPT app (voice/text, subscription, no API keys)
                │ reads truth (raw files)      │ relays commands
                ▼                              ▼
        state/… briefs, pulse          exchange/commands/<id>.json
                ▲                              │ intercom.yml
                │                              ▼
        receipts, journal ◄── validate → policy gates → execute → journal
```

The local Core on the Windows PC (Phase 6+) replaces the transport
(GitHub push/CI) with a persistent local service — the objects flowing
through the loop are the same, which is why the contracts come first.

## Components, honestly

| Playbook component | Where it lives today | Status |
|---|---|---|
| **Data contracts** (§111) | `aletheia/contracts.py` — Capability, Provider, Goal, Task, Agent, Approval, ActionRecord; enums live only here | BUILT (v0) |
| **Capability registry** (§8–10, 104) | `config/capabilities.json` via `aletheia/capabilities.py`; answers "what can you do" truthfully | BUILT (v0) |
| **Task engine** (§27–29) | `aletheia/tasks.py` → `state/tasks/*.json`; §28 lifecycle, dependencies, attempts, derived readiness, journaled | BUILT (v0, file-backed) |
| **Goals / planner data** (§34–36) | `aletheia/plans.py` → `plans/*.json` (the Goal contract's store) | BUILT (data layer; planning intelligence is Phase 5) |
| **Policy / authority** (§55–58) | Embryo: `front_door` grants in `config/fleet.json` checked by `aletheia/act.py` before any network call; `approval_policy` declared per capability; Approval contract defined | PARTIAL — full policy engine is Phase 4 |
| **Audit** (§63) | `aletheia/journal.py` → `state/journal/journal.jsonl`, append-only; every capability that acts writes to it | BUILT (v0; ActionRecord adoption pending) |
| **Memory** (§38–46) | The journal (episodic) + plans (projects). Structured domains (identity, preferences, people, organizations) | JOURNAL BUILT; domains are Phase 16 |
| **Fleet Observatory** (§37) | `aletheia/fleet.py` + `aletheia/pulse.py` + vitals — the repo-sensing organ; `pulse.yml` 6-hourly | BUILT |
| **Sentinel / attention** (§54) | `aletheia/sentinel.py`: transitions + alerts → rolling alert issue (NOTIFY tier only) | BUILT (v0 of the attention model) |
| **Morning brief** | `aletheia/brief.py` + `brief.yml` → committed digest + rolling issue | BUILT |
| **Intercom** (voice v0 transport, §6/§66) | `exchange/INTERCOM.md` + `aletheia/intercom.py` + `intercom.yml`: ChatGPT relays operator commands, gated execution, receipts | BUILT — needs operator's ChatGPT Project setup |
| **Front-door actions** | `aletheia/act.py` (dispatch/issue through registry grants) | BUILT |
| **Ambient wall** (§88–89) | `interface/index.html` — pure view of the pulse (now incl. plans/tasks/alerts) | BUILT; re-aim at "current focus" model as Core grows |
| **Command Center** (§90) | `interface/command.html` served by the Core: approvals, live tasks, UNREAD notifications with ACK, command composer over `/api/kinds`, HALT/RESUME | BUILT v1 |
| **Core runtime on Windows** (§108–110) | `aletheia/core.py` + `sync.py` + `supervisor.py`: loopback API, wall + Command Center, sync loop executing PC-only kinds, self-updating under the supervisor. Each beat also runs `runtime.tick` (below) | BUILT v1 |
| **Computer control** (§12–13) | `aletheia/computer.py` + Core `POST /api/computer` (Codex PRs #11–16, Claude-reviewed) | EXPERIMENTAL — awaits the Windows acceptance run |
| **Browser control** (§14) | `aletheia/browse.py`: read open, interact approval-gated; real-Chromium tests | BUILT v1 |
| **Agent Director** (§64–67) | Interim: workers run as each app's own sessions/scheduled tasks (proven daily in Shorts-pipeline); `agent.delegate` EXPERIMENTAL | Phase 9 makes delegation programmatic |
| **Voice / wake / audio router** (§22–26) | — | Phases 10–11 |
| **Phone V0** (§17–21) | — | Phase 12; needs the local PC (audio routing cannot run in CI) |
| **Event bus / watchers** (§51–52) | `aletheia/events.py` (private one-file-per-event bus, durable watchers) consumed by `runtime.process_new_events` → notifications; core_tick emits sync-health events | BUILT v0 |
| **Memory domains / people / orgs** | `aletheia/memory.py` → `memory/` (provenance, correction-learning) + `aletheia/contacts.py` (private, ambiguity-safe) | BUILT v1 |
| **Room / devices** (§83–85) | `aletheia/devices.py` + `aletheia/room.py`: registry + scene PLANS (`READY_FOR_PROVIDER`); no live provider yet | PARTIAL — adapter NOT_BUILT |
| **Self-expanding capabilities** (§69–70) | `aletheia/gaps.py` + `runtime.reconcile_task_gaps` every Core beat: gap-blocked tasks pause with the gap named, build/configure work materializes idempotently, originals resume when the registry closes the gap | BUILT v0 |

### The systems layer (2026-08-26)

One runtime beat (`aletheia/runtime.py`, run inside every `core_tick`)
drives the durable systems added by ChatGPT PRs #28–30 after Claude's
line-by-line review:

| System | Module | Notes |
|---|---|---|
| Schedules | `aletheia/scheduler.py` | once/interval/daily/weekly, tz-aware, idempotent occurrence claims; due commands revalidate through the intercom grammar + gates |
| Reply expectations | `aletheia/communications.py` | REPLIED/OVERDUE transitions → notifications |
| Notifications | `aletheia/notifications.py` | private center; Core API + Command Center panel + `assistant ack` |
| Action records | `aletheia/outcomes.py` | hash-bound plans, evidence-gated VERIFIED (§30) |
| Current state | `aletheia/current_state.py` | `GET /api/state`; aggregates, never invents |
| Proactive rules | `aletheia/proactive.py` | bounded proposals with cooldown; never executes |
| Capability gaps | `aletheia/gaps.py` + `handler.py` | assess → materialize → resume |
| Delegated authority | `aletheia/authority.py` | EXPERIMENTAL: records only — nothing consumes grants; consuming would widen authority and awaits an operator ruling |
| Personal-OS stores | places, documents, shopping, subscriptions, finance, vehicles, travel, reservations | private visibility/planning; world-touching halves NOT_BUILT operator_always |
| Operator front door | `aletheia/assistant.py` | the CLI giving every verb a real caller (rule zero) |

## The worker model (§4–7)

Aletheia is the orchestrator; models are workers behind providers:

- **claude.session** — Claude via the operator's subscription (Claude
  Code sessions, scheduled Routines, headless brains inside fleet
  repos). Roles: CODING, CODE_REVIEW, DEEP_REASONING, PLANNING. The only
  worker that edits code, per the constitution.
- **chatgpt.app** — ChatGPT via the operator's subscription (Projects,
  scheduled tasks, GitHub connector, Voice). Roles: VOICE,
  GENERAL_REASONING, RESEARCH, WRITING, CODE_REVIEW-as-advisor. Writes
  only its two exchange lanes (suggestions, commands).
- **Deterministic code** — the modules in `aletheia/` and fleet-repo
  pipelines; preferred whenever judgment isn't needed (adapter ladder
  rung 1).

No model API keys anywhere; if a subscription surface changes, the
provider entry degrades honestly and another can replace it (§6).

## The adapter ladder here (§11)

Today's rungs in use: (1) local modules, (2) official APIs with the
operator's tokens (GitHub), (3) official clients (the two AI apps'
own scheduled tasks/connectors). Rungs 4–7 (OS, browser, GUI, visual
control) arrive with the local Core — they can never run from CI, which
is the deepest reason the Windows runtime is on the critical path.

## Storage map

- `config/` — declared truth: fleet registry, capability registry
- `plans/` — Goal store (authored intent, validated in CI)
- `state/` — run truth, CI-writable: pulse, briefs, journal, tasks
- `state/private/` — GITIGNORED per-machine runtime state (events,
  watchers, schedules, notifications, contacts, calendar, projects,
  and every other personal store): personal facts never enter the
  public repo; move it with `ALETHEIA_PRIVATE_STATE`
- `exchange/` — the ChatGPT worker's two UNGATED lanes: suggestions
  (advice) and commands (relayed operator asks) + receipts. Neither
  carries code; a worker the operator has explicitly authorized to edit
  uses a branch and a PR like Claude does (CLAUDE.md, "the gate is
  PERMISSION, not identity")
- `interface/` — the ambient wall (pure view)
- `docs/` — playbook (north star), this map, roadmap, exchange contracts

## Security posture (§59–63)

Fail closed on missing/invalid registries; capability-scoped grants
(`front_door`, `approval_policy`) checked before network calls; no
secrets in the repo (Actions secrets only); append-only audit via the
journal; ability separated from permission (§70) — building a capability
never grants it. The kill switch (§62) and full Approval Center are
Phase 4/6 work and are listed NOT_BUILT until then.
