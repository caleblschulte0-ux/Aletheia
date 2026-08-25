# exchange/ — ChatGPT's seat at the fleet table

The no-API-key path for ChatGPT to contribute to the fleet, mirroring the
contract proved out in Shorts-pipeline: **ChatGPT reads and suggests;
Claude rules and builds; nothing is applied automatically.**

## What ChatGPT reads

- `state/pulse/briefing.md` — the current fleet briefing (raw GitHub URL
  works from a ChatGPT scheduled task).
- `state/pulse/latest.json` — the same truth, machine-readable.
- Any fleet repo's public files, if it wants to dig.

## What ChatGPT writes

Exactly one thing: suggestion files in `exchange/suggestions/`, one JSON
object per file, filename `<id>.json` where `id` matches the `id` field.

```json
{
  "id": "20260825-trader-watchdog-gap",
  "filed": "2026-08-25T13:00:00Z",
  "by": "chatgpt",
  "repo": "schwab_trader",
  "kind": "bug",
  "title": "Watchdog cannot see a stalled sell brain",
  "detail": "Plain prose: what you saw, why it matters, what you would do.",
  "evidence": "Optional: file paths, run links, numbers you checked."
}
```

- `repo` is a key from `config/fleet.json` (or `"fleet"` for cross-cutting).
- `kind` is `bug`, `fix`, `idea`, or `plan`.
- **No code.** Keys like `patch`, `diff`, `code`, `files`, `content`,
  `script` are refused by the validator, as is anything over 16KB. A
  suggestion is prose about the code; changing code is Claude's alone.

Validation runs in CI on every push touching this directory:
`python -m aletheia.suggestions validate`.

## What happens next

A Claude session rules on each suggestion and the ruling is durable in
`exchange/verdicts.json`, keyed by id:

```bash
python -m aletheia.suggestions list --state new
python -m aletheia.suggestions rule 20260825-trader-watchdog-gap doing --because "confirmed against trader.yml history"
```

States are the operator's vocabulary: `doing`, `not_doing`, `later`,
`in_progress`, `done`. The `because` is quoted back — a bare "no" just gets
re-argued. A re-filed suggestion meets its old ruling; re-open it by saying
what changed, not by rewording it.
