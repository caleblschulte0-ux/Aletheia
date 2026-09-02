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
| `browse_read` | `url` (http/https) | **PC-only**: read a page in the PC's real browser — receipt carries title + a text excerpt to speak back |
| `browse_shot` | `url` (http/https) | **PC-only**: screenshot a page; the image stays on the PC (media never enters git), the receipt names its local path |
| `email_check` | — | **PC-only**: unread senders + subjects (read-only, marks nothing) |
| `email_read` | `which` | **PC-only**: the text of ONE unread message named by sender or subject — exactly one match, otherwise she asks which; reading marks nothing |
| `email_draft` | `to`, `body`, `subject?` | **PC-only**: draft an email + file its approval — NOTHING SENDS until the operator approves; `to` is a remembered person's name or a spoken address |
| `remind_at` | `at` (ISO datetime), `text` | **PC-only**: a one-shot reminder — surfaces as a notification at that moment |
| `remind_daily` | `time` (HH:MM), `text`, `tz?` | **PC-only**: a daily reminder (default tz America/Chicago) |
| `watch_email_from` | `who` | **PC-only**: "tell me when email arrives from X" — X must be a known private contact or spoken address; unknown is refused, never guessed |
| `notify_operator` | `text`, `priority?` | **PC-only**: surface a notification to the operator's notification center |
| `notify_check` | — | **PC-only**: speak the unread notifications |
| `notify_clear` | — | **PC-only**: acknowledge all unread notifications |
| `free_time` | `day` (YYYY-MM-DD), `tz?`, `minutes?` | **PC-only**: free slots from the local calendar inside work hours |
| `contact_add` | `name`, `email`, `alias?` | **PC-only**: add a PRIVATE contact (never the public repo); spoken "at/dot" addresses are normalized |
| `research` | `question` | **PC-only**: look into a question with the PC's browser and answer it from real pages, every claim bound to the page it came from; the write-up lands in his documents |
| `file_write` / `file_edit` / `file_read` / `file_list` | `path`, `text` / `path`, `find`, `replace` / `path`, `anywhere?` / `subdir?` | **PC-only**: her own workspace (`~/Documents/Aletheia`) — text formats only, every overwrite keeps the previous version, writing never leaves the workspace; reading may name a file anywhere |
| `computer_observe` | `window?` | **PC-only**: what windows are open, or what controls a window has — eyes only, nothing is touched |
| `computer_do` | `steps`, `why?` | **PC-only**: hands — a JSON list of `open_app` / `wait_window` / `focus_window` / `set_text` / `invoke` steps through Windows UI Automation. Any control labelled Send, Delete, Pay, Purchase, Confirm, Submit, Format, Uninstall, Empty Trash (and siblings) is **refused**, never skipped, and needs the operator's hash-bound approval instead; shells and system tools are never opened |
| `do_task` | `request`, `label?` | **PC-only**: a request no kind covers — she writes a small Python program and runs it in a sandbox (standard-library whitelist, no network, no subprocess, workspace files only, source saved first); the receipt is what the program printed |
| `media_probe` / `media_trim` / `media_join` / `media_audio` / `media_captions` / `media_convert` | `source` / `source`, `out`, `start?`, `end?`, `duration?` / `sources`, `out` / `source`, `out` / `source`, `subtitles`, `out` / `source`, `out`, `height?` | **PC-only**: ffmpeg — every operation writes a NEW file in the workspace and never touches the source |

While Aletheia is halted, every command except `resume` comes back with a
`halted` receipt — relay that honestly.

**PC-only kinds wait for the PC.** Every kind marked PC-only is
executed by the Core running on the operator's computer, not by the cloud
workflow. No receipt means the PC hasn't picked it up yet — the Core is
off or offline. Say exactly that ("your computer hasn't answered yet");
never guess at a page's content, and never treat a missing receipt as
failure. Browser *interaction* (clicking, typing into sites) is
deliberately not a command kind — it requires an approval bound to exact
steps, which a relayed sentence cannot carry.

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

## ChatGPT Project instructions

The ready-to-paste version lives in `exchange/CHATGPT_PROJECT.md` — copy
that file's lower half into the project instructions.

A daily scheduled task in ChatGPT ("read Aletheia's brief and message me
the highlights") makes Thea speak first every morning; that plus this
Project is the whole setup. No API keys anywhere.
