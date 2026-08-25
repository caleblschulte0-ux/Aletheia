# Aletheia

Omniscience, but make it open source.

ἀλήθεια — "unconcealment". Aletheia is the hub that links every repo in the
fleet: one registry of what exists, one **pulse** of what is actually true
right now, one interface to look at it, and one seat where ChatGPT
contributes without ever touching code. It is the foundation the larger
assistant ("Jarvis") capabilities bolt onto — see `docs/ROADMAP.md` for
what is built and what is a ticket.

## The fleet

<!-- regenerate with `python -m aletheia.fleet --markdown` -->
<!-- BEGIN GENERATED FLEET -->
| Repo | Role | Status | Summary |
|---|---|---|---|
| `Aletheia` | hub | active | The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox. |
| `Shorts-pipeline` | youtube-automation | active | Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange. |
| `schwab-trader` | trading-bot | active | Guardrailed paper-trading day-trading bot for Charles Schwab: separate Claude BUY and SELL brains, executor on GitHub Actions, significance-gated sell approvals. |
| `Money_Machine` | unbuilt | stub | Empty stub — nothing but a README. No behaviour to observe yet. |
| `etsy_maker` | unbuilt | stub | Empty stub — nothing but a README. No behaviour to observe yet. |
| `fosstester` | unbuilt | stub | Empty stub — nothing but a README. No behaviour to observe yet. |
<!-- END GENERATED FLEET -->

That table is generated from `config/fleet.json` — the **only** place the
fleet's composition lives. `tests/test_fleet.py` fails if it drifts.

## How it works

```
config/fleet.json          the registry: repos, roles, agents, what to watch
        │
        ▼
aletheia/pulse.py          walks every repo (GitHub API in CI, local clones
        │                  offline) → state/pulse/latest.json + briefing.md
        ▼
interface/index.html       static dashboard reading latest.json — no build,
        │                  no server, works on GitHub Pages
        ▼
exchange/suggestions/      ChatGPT reads the briefing, files suggestions;
                           Claude rules on them (doing / not_doing / later)
```

## Commands

```bash
python -m aletheia.fleet                 # one line per repo
python -m aletheia.fleet --validate      # registry structural check
python -m aletheia.fleet --markdown      # the table above
python -m aletheia.pulse                 # collect via GitHub API (needs token)
python -m aletheia.pulse --local ~/repos # collect from sibling clones, offline
python -m aletheia.suggestions validate  # check ChatGPT's inbox
python -m aletheia.suggestions list      # suggestions + rulings
python -m aletheia.suggestions rule <id> doing --because "..."
python -m unittest discover tests        # the whole test suite, no deps
```

## Setup that needs the operator

- **`FLEET_TOKEN` repository secret** — a fine-grained PAT with read access
  (contents + actions) to every fleet repo. Without it, `pulse.yml` still
  runs but only sees Aletheia itself; every other repo shows up in the
  pulse as unreachable, by name, honestly.
- **GitHub Pages** (optional) — enable Pages on this repo, root of `main`,
  and `interface/` becomes a live dashboard at
  `https://caleblschulte0-ux.github.io/Aletheia/interface/`.

## Rules

The constitution is `CLAUDE.md`. The short version: Claude is the only
agent that edits code, anywhere in the fleet; ChatGPT files suggestions
through `exchange/` and they are ruled on, never auto-applied; the pulse
observes the fleet and never operates it; and every capability in this repo
is wired to a caller or honestly labelled a ticket.
