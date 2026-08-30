# Aletheia

ἀλήθεια — "unconcealment." Spoken name: **Thea**.

Aletheia is Caleb's personal operating system in the making: a
local-first, model-independent orchestration layer between his intent
and everything software can legitimately observe, control, delegate,
coordinate, create, monitor, or influence. The end state: **he says what
he wants; Aletheia figures out how to move reality toward it** — across
Windows, iPhone, the room, the fleet of repos, and the people and
services around him.

**New here / coming back? Start with `docs/SETUP.md`** — three steps
stand between this repo and Aletheia running.

The full vision is the operator's master playbook —
**`docs/PLAYBOOK.md`** — which supersedes every earlier definition.
`docs/ARCHITECTURE.md` maps it onto the code that exists;
`docs/ROADMAP.md` tracks the phases honestly. The constitution for
sessions working here is `CLAUDE.md`. Local-model activation and rollback
are documented in `docs/LOCAL_AI.md`.

## What works today

- **She is simply on.** `python -m aletheia.supervisor install` registers
  the Core and the room voice as always-on Windows tasks: a logon
  trigger, a watchdog every five minutes, no execution time limit, and
  power transitions that cannot kill her. Any death is repaired in
  minutes without a human — proven by killing both processes and timing
  the return (12 seconds). `python -m aletheia.supervisor status` answers
  "is she up, and is the registration one she can survive inside?", and
  an outage she comes back from is journaled with its duration instead of
  passing in silence.
- **The local Core + Command Center** — the wall at `/`, the interactive
  Command Center at `/command.html` (live task queue, approvals with
  approve/deny buttons, HALT/RESUME kill switch, the command composer),
  and the internal API every interface shares. Loopback by default;
  reaching it from a phone needs a minted token AND a TLS certificate
  (`python -m aletheia.access mint`), and refuses without either.
- **Say anything.** An ask that fits no command slot is no longer
  journaled and forgotten: `aletheia.planner` compiles it into steps
  expressed in the ordinary grammar, and every step still passes the same
  validator and the same gates. A model proposes; the registries and the
  gates dispose. She answers in about 50ms from local state, says
  "working on that" for anything that needs thinking, and speaks the real
  answer when it exists.
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
- **The last mile** — `python -m aletheia.errands`: one approval-bound
  web errand covering buying, booking and cancelling, executed through
  the browser gate and bound to a hash of exactly what you authorized. A
  spending errand checks the page's real total against its ceiling before
  it clicks anything, and stops dead at the boundaries that are yours
  alone — a bank step-up, a one-time code, a signature, an ID check —
  handing you what is left rather than pretending.

## The fleet (one sensory organ, not the identity)

<!-- regenerate with `python -m aletheia.fleet --markdown` -->
<!-- BEGIN GENERATED FLEET -->
| Repo | Role | Status | Summary |
|---|---|---|---|
| `Aletheia` | hub | active | The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox. |
| `Shorts-pipeline` | youtube-automation | active | Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange. |
| `schwab-trader` | trading-bot | active | Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them. |
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
python -m aletheia.supervisor status     # is she up, and will she stay up?
python -m aletheia.planner "<anything>"  # an arbitrary ask -> a gated plan
python -m aletheia.intents list          # asks in flight, with their approvals
python -m aletheia.errands list          # errands in the world
python -m aletheia.access list           # credentials that can reach her
python -m aletheia.suggestions list      # ChatGPT's advice + rulings
python -m aletheia.local_ai status       # local models, routing, capture quota
python -m aletheia.local_ai deactivate   # immediate machine-local rollback
python -m unittest discover -s tests -t .   # the whole suite, stdlib only
```

## Setup that needs the operator

**One command tells you where you stand:**

```bash
python -m aletheia.setup      # or just ask her: "Thea, what do you still need from me?"
```

Every item is checked live — a real IMAP login, a real request to the hub,
a real token round-trip — so nothing claims to be configured on faith. It
also names how long each one takes, so "your side" is a known quantity
rather than an open question.

What is left is credentials and live round-trips, not architecture — see
`docs/ROADMAP.md` for the five, each of which flips a registry entry on
real evidence. Home Assistant needs a token before she can touch the
room; a TLS certificate and a minted token before a phone can reach her.

Three steps, all in **`docs/SETUP.md`**:

1. **Pages** — Settings → Pages → Source: *GitHub Actions* (the wall goes
   live; the workflow is already written and waiting)
2. **Thea's voice** — paste `exchange/CHATGPT_PROJECT.md` into a ChatGPT
   Project; unlimited conversation, no API keys
3. **The Core** — one PowerShell line (`scripts/bootstrap.ps1`) starts
   Aletheia on the PC

`main` is merged and CI is green; the pulse, brief, sentinel, director
and intercom have all been verified running live on it.
