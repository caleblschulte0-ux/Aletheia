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
| **Command Center** (§90) | — | Phase 6 (the intercom is the interim command channel) |
| **Core runtime on Windows** (§108–110) | — | Phase 6+; contracts/task store designed to be adopted by it |
| **Computer control** (§12–13) | — | Phase 7, `computer.control` NOT_BUILT in registry |
| **Browser control** (§14) | — | Phase 8, `browser.control` NOT_BUILT |
| **Agent Director** (§64–67) | Interim: workers run as each app's own sessions/scheduled tasks (proven daily in Shorts-pipeline); `agent.delegate` EXPERIMENTAL | Phase 9 makes delegation programmatic |
| **Voice / wake / audio router** (§22–26) | — | Phases 10–11 |
| **Phone V0** (§17–21) | — | Phase 12; needs the local PC (audio routing cannot run in CI) |
| **Event bus / watchers** (§51–52) | Embryo: pulse `transitions` are the first event type; PR-event wakes exist per-repo | Phase 17 |
| **Memory domains / people / orgs** | — | Phase 16 |
| **Room / devices** (§83–85) | — | Phase 18 |
| **Self-expanding capabilities** (§69–70) | The loop exists socially: gap → suggestion/plan/task → Claude session builds → registry entry. Not yet automatic | Phase 20 |

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
- `exchange/` — the ChatGPT worker's two lanes: suggestions (advice) and
  commands (relayed operator asks) + receipts
- `interface/` — the ambient wall (pure view)
- `docs/` — playbook (north star), this map, roadmap, exchange contracts

## Security posture (§59–63)

Fail closed on missing/invalid registries; capability-scoped grants
(`front_door`, `approval_policy`) checked before network calls; no
secrets in the repo (Actions secrets only); append-only audit via the
journal; ability separated from permission (§70) — building a capability
never grants it. The kill switch (§62) and full Approval Center are
Phase 4/6 work and are listed NOT_BUILT until then.
