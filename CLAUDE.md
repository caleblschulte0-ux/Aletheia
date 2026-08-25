# Aletheia — notes for Claude sessions

Aletheia is the hub of a fleet of repos under one operator. It observes the
whole fleet, briefs the humans and the agents, and hosts the contracts by
which the agents cooperate. It inherits its working culture from
`Shorts-pipeline/CLAUDE.md`; the rules below are the local constitution.

## Rule zero (inherited): if you can fix it, fix it — do not just name it

Same ruling as Shorts-pipeline, 2026-08-01. A finding you could have fixed
and didn't is worse than no finding. Never build a capability and leave it
unwired — everything in this repo either has a real caller or is listed in
`docs/ROADMAP.md` as a ticket, explicitly and honestly.

## What Aletheia is — and the line it does not cross

Aletheia **observes and coordinates; it does not operate**. The pulse reads
other repos, it never writes to them, dispatches their workflows, or edits
their state. Each fleet repo keeps its own gates, its own brains, its own
doctrine — the Shorts-pipeline showrunner, the trader's guardrails —
and nothing here may reach in and override them. If Aletheia ever grows an
"act on a repo" capability (ROADMAP ticket A7), it goes through that repo's
own front door (a workflow dispatch, a PR) with the same authority any
outside caller has, never a bypass.

## `config/fleet.json` is the ONLY place the fleet's composition lives

Which repos exist, their roles and status, which agents act in them, what
the pulse watches — all of it, resolved through `aletheia/fleet.py`:

```bash
python -m aletheia.fleet             # every repo, one line
python -m aletheia.fleet --validate
python -m aletheia.fleet --markdown  # the README table
```

Never write the fleet's shape anywhere else. The README table is generated
and `tests/test_fleet.py` fails if it drifts. A missing or invalid registry
fails CLOSED — no caller guesses a fleet.

Adding a repo to the fleet = one entry in that file (plus `FLEET_TOKEN`
scope for the pulse). Nothing else should need editing; if it does, that is
a bug in Aletheia, fix Aletheia.

## The pulse never lies by omission

`aletheia/pulse.py` writes `state/pulse/latest.json` + `briefing.md`. Its
contract: **every repo in the registry appears in every pulse.** A repo the
source cannot reach is recorded with its error and health `unknown` — never
skipped, never guessed green. Local mode (`--local ROOT`) honestly marks
workflow runs "unavailable offline". Health is derived (`_health`), never
asserted, and `tests/test_pulse.py` holds the derivation.

`pulse.yml` runs it on a schedule with `FLEET_TOKEN` (a read-only
fine-grained PAT across the fleet — the default `GITHUB_TOKEN` sees only
this repo). Without the secret the pulse still runs and says exactly what
it could not see.

## The capabilities — each wired, each with a line it does not cross

Built 2026-08-25 on the operator's ask ("Aletheia needs capabilities of
its own"). Every one has a real caller today; every one is journaled.

- **The journal** (`aletheia/journal.py` → `state/journal/journal.jsonl`)
  is Aletheia's durable memory: rulings, health transitions, actions,
  briefs, plan changes. Append-only with the same standing as the posted
  logs — never edit or prune an entry. Writers: suggestions rulings, the
  pulse (transitions), the sentinel, the brief, plans, front-door
  actions, and `python -m aletheia.journal add` for operator notes.
- **The sentinel** (`aletheia/sentinel.py`, run by `pulse.yml`) notices.
  The pulse now carries `transitions` (health changes vs the previous
  pulse) and `alerts` (active repos red or unreachable); the sentinel
  reconciles ONE rolling "🚨 Fleet alert" issue on THIS repo — opens on
  fault, comments on change, closes on recovery. It is the smoke
  detector, not the fire brigade: it never dispatches, never fixes,
  never touches another repo.
- **The morning brief** (`aletheia/brief.py`, run daily by `brief.yml`)
  composes "here is your empire" — vitals with day-over-day deltas from
  pulse history, transitions, open plans, the ChatGPT inbox, the
  journal's last 24h — into `state/brief/` and a rolling "☀️ Fleet
  brief" issue whose daily comment is the notification. Composition is
  pure and tested; delivery degrades honestly without a token.
- **Front-door actions** (`aletheia/act.py`) are Aletheia's hands, and
  the registry is the whole safety model: a repo's `front_door` grant
  lists exactly which workflows may be dispatched and whether issues may
  be filed. The default grant is stingy (only Aletheia's own workflows
  are dispatchable; issues on active repos). Widening it is a
  `config/fleet.json` change reviewed like any other — never a code path
  around the check, which runs BEFORE any network call. Callers are the
  operator and interactive Claude sessions; nothing autonomous acts.
- **Plans** (`aletheia/plans.py` → `plans/*.json`) hold large-scale
  intent as data with a lifecycle (open/done/dropped; steps
  todo/doing/done/blocked, each optionally aimed at a fleet repo). The
  pulse embeds a summary, so the wall and the brief both show what is in
  motion. Validated in CI; every mutation journaled.

## WHO MAY EDIT — Claude, and only Claude (fleet-wide)

The operator's standing ruling, same as Shorts-pipeline: **Claude is the
only agent that edits code**, in this repo and every fleet repo. ChatGPT's
seat is `exchange/`:

- ChatGPT **reads** `state/pulse/briefing.md` and anything else public.
- ChatGPT **writes** only `exchange/suggestions/*.json` — prose findings
  (bug / fix / idea / plan). The validator refuses payload keys (`patch`,
  `diff`, `code`, …) and oversized files; a suggestion is *about* the code,
  never the code.
- **Claude rules** on each suggestion in the operator's vocabulary —
  `doing / not_doing / later / in_progress / done` — with a real
  `--because`, kept durable in `exchange/verdicts.json`. Nothing is ever
  applied automatically.

```bash
python -m aletheia.suggestions validate
python -m aletheia.suggestions list --state new
python -m aletheia.suggestions rule <id> doing --because "..."
```

## The interface is the CENTERPIECE — and still a pure view

Operator ruling 2026-08-25: the interface is not a status page, it is the
wall — projected behind the operator's monitors, the visible face of
everything they've built. Treat its craft accordingly: cinematic,
ambient, legible from across a room. But two rules keep its ambition
honest:

- **It stays a static single file** rendering `state/pulse/latest.json` —
  zero build step, zero dependencies, zero server — so it can never
  disagree with the pulse and never breaks in a way the pulse doesn't
  already show. Smarts (new numbers, new probes) go in the COLLECTOR and
  the registry's `vitals`, then the wall renders them.
- **Status is never color-alone.** Every health dot travels with its word
  (OPERATIONAL / FAULT / NO TELEMETRY / DORMANT) — the red/green pair is
  not CVD-safe by itself and a wall display is read at a glance.

It deliberately commits to one dark look (it is a projection surface, not
a document), auto-refreshes, and shows honest staleness (`PULSE STALE`)
when the pulse is old. An INTERACTIVE command surface — buttons, chat,
approvals — is ticket A8 and a different artifact; do not grow controls
into this page quietly.

## Storage rules

Small JSON and markdown only; no media, nothing over 256KB.
`state/pulse/history/` keeps one small file per day. `exchange/verdicts.json`
is durable ruling state — append/update, never prune to tidy up.

## Branch discipline

Interactive sessions work on `claude/*` branches and push there. There is
no auto-merge in this repo; merges to `main` are deliberate.
