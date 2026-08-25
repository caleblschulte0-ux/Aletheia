# Aletheia roadmap — built vs. ticket, honestly

The operator's stated destination (2026-08-25): *"a Jarvis type character
who can make my life a lot easier in a lot of different ways … being able
to actually call people and set stuff up and plan large scale stuff … at
some point build an actual interface to interact with stuff like that."*

This file is the ledger of that ambition. Rule zero applies: a row here is
either **built** (it has a real caller today) or a **ticket** (it does not
exist yet, and nothing in the repo pretends it does). Build tickets one at
a time, each earning its slot; when one ships, move it up and say what
wired it.

## Built

| # | Capability | What wires it |
|---|---|---|
| A1 | Fleet registry — one source of truth for what exists | `config/fleet.json` via `aletheia/fleet.py`; README table generated; `tests/test_fleet.py` |
| A2 | Fleet pulse — live status of every repo, honest about blind spots | `aletheia/pulse.py`; `pulse.yml` (scheduled); `tests/test_pulse.py` |
| A3 | The wall — cinematic fleet display (operator ruling 2026-08-25: this is the centerpiece, projected behind the monitors) | `interface/index.html` reading `state/pulse/latest.json`; orbital fleet map, live clock, vitals, activity ticker; GitHub Pages-ready |
| A3b | Vitals in the pulse — real numbers (paper P&L, win rate, positions, videos posted per channel) declared in the registry, probed generically | `vitals` in `config/fleet.json`; `_vitals` in `aletheia/pulse.py`; `tests/test_pulse.py` |
| A4 | ChatGPT advisory seat — suggestions in, rulings out, never code | `exchange/` contract; `aletheia/suggestions.py`; CI validation; `tests/test_suggestions.py` |
| A5 | Morning briefing, delivered — daily digest with day-over-day deltas, plus the sentinel alerting on faults/recovery in real time | `aletheia/brief.py` + `brief.yml` (rolling "☀️ Fleet brief" issue); `aletheia/sentinel.py` in `pulse.yml` (rolling "🚨 Fleet alert" issue); `tests/test_capabilities.py` |
| A6 | Cross-repo memory — the journal | `aletheia/journal.py` → `state/journal/journal.jsonl`; written by rulings, transitions, sentinel, brief, plans, actions; searchable CLI |
| A7 | Acting through front doors — registry-gated dispatch + issue filing | `aletheia/act.py`; `front_door` grants in `config/fleet.json` (stingy by default; widening = registry change); refusal tested |
| A9 | Planner, first cut — plans as tracked data, surfaced on the wall and in the brief | `aletheia/plans.py` → `plans/*.json`; pulse embeds summary; CI validates; first real plan: `light-up-the-wall` |

## Tickets

Ordered roughly by leverage-per-effort. Each names what it NEEDS — the
honest blocker — so a session picking one up knows where to start.

| # | Ticket | What it is | Needs |
|---|---|---|---|
| A8 | **The real interface** | What the operator asked for out loud: a place to talk to Aletheia and press buttons — chat + dashboard + approve/deny queues (e.g. the trader's pending sells surfaced here). The wall stays a pure view; this is a separate command surface. | A design decision first: static Pages + GitHub issues as the command channel (free, slow — `aletheia.act` and the alert/brief issues are the primitives) vs. a small hosted app (costs money, real-time). Prototype the free path first. |
| A9b | **Planner doctrine** | A9's data layer exists; what's missing is the thinking: how a goal ("launch the Etsy shop") gets decomposed well — milestone shapes, review cadence, when the brief escalates a stalled plan. | A doctrine doc + a few real plans lived through, not code. |
| A7b | **Cross-repo dispatch, granted** | The mechanism is built and refuses everything not in the registry. Turning it on for real targets (e.g. re-running a failed fleet workflow from here) is a grant, not a build. | Operator decision per grant in `config/fleet.json`; `FLEET_TOKEN` upgraded to actions:write for those repos. |
| A10 | **Outbound comms — email** | Draft/send email on the operator's behalf for "set stuff up" tasks, with an approval gate exactly like the trader's significant-sell gate: Aletheia drafts, operator approves, then it sends. | Gmail access from a Claude session (connector exists); the approval-queue mechanism from A8. Never auto-send in v1. |
| A11 | **Outbound comms — voice/calls** | "Actually call people." Real telephony: outbound calls with a synthesized voice, transcripts into the journal. | This is the one that genuinely can't be free: a telephony provider (e.g. Twilio) + speech synthesis = a paid account. Operator decision to fund it. Everything before it works without new spend. |
| A12 | **New-repo onboarding kit** | `python -m aletheia.onboard <repo>`: adds the registry entry, a starter CLAUDE.md inheriting the constitution, and CI stubs — so every future repo is born into the fleet. | A2 stable across a few weeks of pulses first, so the kit encodes proven shape rather than guesses. |

## Non-goals, on the record

- **No second brain per repo.** Fleet repos keep their own agents and
  gates; Aletheia observes and coordinates (CLAUDE.md, "the line").
- **No paid API spend by default.** The whole design rides scheduled tasks
  in the Claude and ChatGPT apps plus GitHub Actions, like the
  Shorts-pipeline exchange. Tickets that require spend (A11) say so and
  wait for the operator.
- **No autonomy over money.** Nothing here will ever place, approve, or
  route a trade; that stays entirely inside schwab-trader's own guardrails.
