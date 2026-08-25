# Aletheia

ἀλήθεια — "unconcealment." Spoken name: **Thea**.

Aletheia is Caleb's personal operating system in the making: a
local-first, model-independent orchestration layer between his intent
and everything software can legitimately observe, control, delegate,
coordinate, create, monitor, or influence. The end state: **he says what
he wants; Aletheia figures out how to move reality toward it** — across
Windows, iPhone, the room, the fleet of repos, and the people and
services around him.

The full vision is the operator's master playbook —
**`docs/PLAYBOOK.md`** — which supersedes every earlier definition.
`docs/ARCHITECTURE.md` maps it onto the code that exists;
`docs/ROADMAP.md` tracks the phases honestly. The constitution for
sessions working here is `CLAUDE.md`.

## What works today

- **The local Core + Command Center** — `python -m aletheia.core` on
  your PC starts Aletheia as a persistent service: the wall at `/`, the
  interactive Command Center at `/command.html` (live task queue,
  approvals with approve/deny buttons, HALT/RESUME kill switch, a
  15-kind command composer), and the internal API every future
  interface shares. Loopback-only until authentication exists.
- **The intercom** — talk to Thea through ChatGPT (voice or text, your
  subscription, zero API keys). It reads Aletheia's truth from this repo
  and relays your asks as validated commands; a workflow executes them
  through registry gates and writes receipts back. Contract + setup:
  `exchange/INTERCOM.md`.
- **A truthful capability registry** — `python -m aletheia.capabilities`
  answers "what can you do?" from `config/capabilities.json`:
  what's AVAILABLE (with its real caller), what NEEDS_CONFIGURATION,
  what's honestly NOT_BUILT yet.
- **A durable task engine** — `python -m aletheia.tasks`: work that
  outlives conversations, with the full lifecycle (a call nobody
  answered is WAITING_EXTERNAL, not forgotten), dependencies, retries.
- **Goals as data** — `python -m aletheia.plans`: multi-step intent with
  tracked steps, surfaced on the wall and in the brief.
- **The Fleet Observatory** — the pulse watches every repo (commits, CI,
  state files, vitals like paper-trading P&L and videos shipped); the
  sentinel opens/closes a fleet-alert issue by itself; a morning brief
  with day-over-day deltas lands daily.
- **Memory** — `python -m aletheia.journal`: an append-only record of
  every decision, action, alert, and ruling, searchable from anywhere.
- **The wall** — `interface/` — Ambient Aletheia: the cinematic room
  projection rendering the pulse (orbital fleet map, vitals, plans,
  tasks, alerts, activity ticker).

## The fleet (one sensory organ, not the identity)

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

## Commands

```bash
python -m aletheia.capabilities          # what can Thea do? (the honest answer)
python -m aletheia.tasks list            # durable work in flight
python -m aletheia.plans list            # goals in motion
python -m aletheia.journal search <term> # the memory
python -m aletheia.pulse                 # observe the fleet (token) / --local ROOT offline
python -m aletheia.brief                 # compose the morning brief
python -m aletheia.act grants            # what the registries let Aletheia touch
python -m aletheia.intercom list         # relayed commands + receipts
python -m aletheia.suggestions list      # ChatGPT's advice + rulings
python -m unittest discover tests        # the whole suite, stdlib only
```

## Setup that needs the operator

1. Merge the working branch; add the **`FLEET_TOKEN`** secret
   (fine-grained PAT, read contents+actions across the fleet) so the
   pulse sees everything.
2. Enable **GitHub Pages** (main, root) → the wall lives at
   `…github.io/Aletheia/interface/`, fullscreen on the projector.
3. Create the **ChatGPT Project** per `exchange/INTERCOM.md` → Thea
   gains her voice: unlimited conversation, no API keys.
