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
| A3 | Static dashboard | `interface/index.html` reading `state/pulse/latest.json`; GitHub Pages-ready |
| A4 | ChatGPT advisory seat — suggestions in, rulings out, never code | `exchange/` contract; `aletheia/suggestions.py`; CI validation; `tests/test_suggestions.py` |

## Tickets

Ordered roughly by leverage-per-effort. Each names what it NEEDS — the
honest blocker — so a session picking one up knows where to start.

| # | Ticket | What it is | Needs |
|---|---|---|---|
| A5 | **Morning fleet briefing, delivered** | A scheduled Claude task reads the pulse and messages the operator a short "here is your empire this morning" — money made/lost (paper), videos shipped, anything red — instead of the operator opening dashboards. | A Claude scheduled task (in the Claude app, like Shorts-pipeline's Routine) reading `state/pulse/briefing.md`; a delivery channel the operator picks (the task's own chat, or email once A7 lands). |
| A6 | **Cross-repo memory** | A durable journal of operator decisions and fleet events (`state/journal/`), so any session in any repo can ask "what did we decide about X" without archaeology across six CLAUDE.mds. | A write contract (who appends, schema) and a search CLI. No external services. |
| A7 | **Acting through front doors** | Aletheia-initiated actions on fleet repos — dispatch a workflow, open an issue, file a PR — always via each repo's own gates, never a bypass (see CLAUDE.md). Unlocks "set stuff up" asks. | `FLEET_TOKEN` upgraded to a scoped write PAT (operator decision — start read-only); a per-action allowlist in the registry. |
| A8 | **The real interface** | What the operator asked for out loud: a place to talk to Aletheia and press buttons — chat + dashboard + approve/deny queues (e.g. the trader's pending sells surfaced here). | A design decision first: static Pages + GitHub issues as the command channel (free, slow) vs. a small hosted app (costs money, real-time). Prototype the free path first. |
| A9 | **Large-scale planner** | Goal in ("launch the Etsy shop"), plan out: milestones decomposed into tickets across fleet repos, tracked in the journal, chased by the briefing. | A6 first (plans need durable memory); then a planning doctrine doc, not code. |
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
