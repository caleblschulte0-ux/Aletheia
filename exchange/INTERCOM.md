# The intercom — talking to Aletheia through ChatGPT

The operator talks to ChatGPT (the app: text or voice, phone or desktop,
flat-rate, no API keys). ChatGPT is a **worker wearing the voice** — it is
not Aletheia. It reads Aletheia's truth from this repo, and when the
operator asks for an action, it relays the ask as one small JSON file.
A workflow executes the command through the same registry gates the
operator would use at a keyboard, and writes a receipt ChatGPT reads back.

```
operator speaks ──► ChatGPT (app, voice, unlimited)
                       │ reads truth            │ relays commands
                       ▼                        ▼
        state/pulse/briefing.md        exchange/commands/<id>.json
        state/brief/latest.md                   │  push fires intercom.yml
        state/journal/…, plans/…                ▼
                       ▲               validate → gate → execute → journal
                       │ reads receipt          │
        exchange/commands/<id>.result.json ◄────┘
```

## What ChatGPT reads (raw URLs work from a scheduled task or Project)

- `state/pulse/briefing.md` — current fleet truth
- `state/brief/latest.md` — the morning digest
- `state/pulse/latest.json` — machine-readable, includes alerts/plans
- `plans/*.json`, `state/journal/journal.jsonl` — intent and memory
- `exchange/commands/<id>.result.json` — receipts for relayed commands

## What ChatGPT writes

Exactly two things, ever:

1. Suggestions — `exchange/suggestions/*.json` (see `exchange/README.md`)
2. **Commands** — `exchange/commands/<id>.json`, one relayed operator ask:

```json
{
  "id": "20260825-rerun-pulse",
  "filed": "2026-08-25T16:00:00Z",
  "by": "chatgpt",
  "relayed_from": "operator",
  "operator_quote": "run the pulse again real quick",
  "command": {"kind": "dispatch", "repo": "aletheia", "workflow": "pulse.yml"}
}
```

Command kinds and their arguments (anything else is refused):

| kind | args | does |
|---|---|---|
| `note` | `text` | journal an operator note |
| `dispatch` | `repo`, `workflow`, `ref?` | run a workflow — **only** ones the registry's `front_door` grants |
| `issue` | `repo`, `title`, `body?` | file an issue — only where the registry grants it |
| `rule` | `id`, `state`, `because` | record the operator's ruling on a suggestion |
| `plan_new` | `slug`, `title`, `goal` | open a plan |
| `plan_add_step` | `slug`, `text`, `repo?` | add a step |
| `plan_step` | `slug`, `n`, `state` | move a step (todo/doing/done/blocked) |
| `plan_set` | `slug`, `state`, `because?` | close/drop/reopen a plan |
| `task_new` | `id`, `description`, `goal?`, `worker?`, `deadline?` | create a durable task (survives every conversation) |
| `task_status` | `id`, `state`, `note?` | move a task through its lifecycle |
| `halt` | `reason?` | **the kill switch** — everything acting stops until resume |
| `resume` | — | lift the halt (the only command that executes while halted) |
| `approve` | `id` | approve a pending 🔐 approval by voice |
| `deny` | `id`, `because?` | deny a pending approval |
| `remember` | `domain`, `key`, `value`, `memory_kind?` | store a memory with the operator's words as provenance (domains: identity, preferences, people, organizations) |

While Aletheia is halted, every command except `resume` comes back with a
`halted` receipt — relay that honestly.

Non-negotiables:

- **A command relays the operator's words** — `operator_quote` is required
  and `relayed_from` must be `operator`. ChatGPT never files a command the
  operator didn't ask for.
- **No code, no paths, no payloads.** A command names a kind and its
  arguments. Unknown kinds and extra keys are refused by the validator.
- **The registry still gates the hands.** `dispatch`/`issue` run through
  `aletheia.act`; anything `front_door` doesn't grant comes back `refused`.
- **Receipts are the only truth about execution.** Tell the operator what
  the receipt says, never what you assume happened. `pending` means not
  executed yet (the workflow usually lands it within a minute).

## ChatGPT Project instructions (operator: paste this into a ChatGPT
## Project named "Aletheia" with the GitHub connector enabled)

> You are the voice of **Aletheia** (spoken name: **Thea**), Caleb's
> personal operating system. You are a worker, not the system itself:
> Aletheia's truth lives in the GitHub repo `caleblschulte0-ux/Aletheia`,
> and you never invent state you didn't read there.
>
> When Caleb asks how things are going, read (raw, from branch `main`):
> `state/pulse/briefing.md`, `state/brief/latest.md`, and if he asks about
> plans or history, `plans/` and `state/journal/journal.jsonl`. Answer in
> plain language, lead with what matters (faults first, then money, then
> output), and never guess a number you didn't read.
>
> When Caleb asks you to DO something, check `exchange/INTERCOM.md` in the
> repo for the current command kinds. If his ask maps to one, commit one
> JSON file to `exchange/commands/<id>.json` on `main` exactly per that
> contract — id format `YYYYMMDD-short-slug`, his words in
> `operator_quote`. Then, on your next turn or when he asks, read
> `exchange/commands/<id>.result.json` and tell him what actually
> happened. If there is no receipt yet, say it's still executing.
> If his ask maps to NO kind, say so honestly and file it as a suggestion
> in `exchange/suggestions/` instead — never pretend a capability exists.
>
> You never write any other file in this repo: no code, no workflows, no
> docs, no state. You never file a command Caleb didn't ask for. When
> unsure whether he asked, ask him — one short question.

A daily scheduled task in ChatGPT ("read Aletheia's brief and message me
the highlights") makes Thea speak first every morning; that plus this
Project is the whole setup. No API keys anywhere.
