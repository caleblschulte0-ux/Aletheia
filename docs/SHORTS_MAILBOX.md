# The Shorts mailbox worker

**Door shut (2026-10-07).** Built and tested, and not granted: the words the
grant quoted were said in another project, which this one cannot confirm, so
`config/fleet.json` carries no `answers` door for Shorts until he says yes here.
`kick()` reports "no answers grant" and writes nothing. The grant as drafted is
in `config/capabilities.json` (`shorts.mailbox.answer`, notes) and in the
test's `GRANT`.

Shorts-pipeline files three kinds of question it cannot answer inside its own
run, and has accepted Aletheia's answers to all three since 2026-09-30
(`"by": "aletheia:<route>"`; its own `docs/REVIEW_MAILBOX.md`):

| mailbox | the question | Aletheia's answer | who decides |
|---|---|---|---|
| `exchange/reviews/` | a held render's frames + the SHOWRUNNER's grading prompt | `<id>.verdict.json`: the judge's GRADES (anchors + hard checks), never ship/block/score | Shorts' `assemble_verdict` + `showrunner_gate.decide`, then its claim step |
| `exchange/rewrites/` | a held story's words, its data, the gate's rules | `<id>.answer.json`: new words, same segments | Shorts' `rewrite_mailbox.validate` and the same gate |
| `exchange/asks/` | a text question no backend of its own could answer | merged into `<date>.answers.json` | the caller that parses the answer, exactly as a model's reply |

## The ruling

Caleb, 2026-10-07T01:22Z, in his Claude project thread:

> "Alethea may write files into a shorts review, rewrite, and ask mailbox. ...
> That's certified by me. Every 30 minutes is unnecessary. We only post in the
> morning, so maybe it needs to run two, three times in the morning, and that's it"

It is recorded as a reviewed registry edit: `config/fleet.json`
`repos.shorts_pipeline.front_door.answers` (the three folders) with
`answers_ruling` (his words, when, where) beside it. The fleet validator
refuses an `answers` prefix outside `exchange/`, the whole of `exchange/`, or
an `answers` grant without his words. The capability is
`shorts.mailbox.answer` in `config/capabilities.json`, EXPERIMENTAL until a
live answer has round-tripped through Shorts' claim step.

## What it may write, checked before any network call

`aletheia.act.check_answer_path`: a path under a granted prefix AND ending
`.verdict.json`, `.answer.json` or `.answers.json`. A request, an `OPEN.json`
index, a `.done.json`, any other folder, any code: refused, zero API calls.
`act.put_answer` also re-reads the kill switch and the closed marker, refuses
a `[skip ci]` message (the push is what runs Shorts' claim workflow), never
overwrites an answer that is already there (a request is answered once) except
the asks file, which it MERGES into, keeping every answer already present, and
retries a sha conflict once. Every write is journaled
(`repo:shorts_pipeline`), and a round that wrote anything is one OUTWARD row in
the autonomy ledger. Commit message: `exchange: mailbox round <YYYYMMDD> (aletheia)`.

## When it runs: his mornings, with nothing for him to do

1. The Core's beat (`runtime.tick`, `guarded("shorts_mailbox", ...)`) calls
   `shorts_mailbox.kick`, which is cheap: inside a morning slot on his clock
   (06:30, 08:00, 09:30 America/Chicago via `aletheia.localtime`, each open
   for an hour), with the grant present, not halted or closed, no round
   running, and this slot's receipt not yet claimed, it claims the receipt
   (`state/private/shorts-mailbox/receipts/<date>-<slot>.json`, created
   exclusively; never more than three a morning) and LAUNCHES
   `python -m aletheia.shorts_mailbox once --slot <date>-<slot>` as a detached
   process (`proc.spawn_detached`). No model is asked inside the beat. A launch
   that fails gives the slot back for the next beat.
2. The round (`main`) drops the ChatGPT browser lease first, checks closed /
   halted / grant / token, takes a lock so two rounds never overlap, does
   bounded work inside 75 minutes, writes `latest.json` and exits 0:
   - up to 4 REVIEWS from `OPEN.json` (newest first, already the newest cut of
     each story): frames and contact sheet fetched only from Shorts'
     `preview-renders` branch into a throwaway folder; graded by Claude CLI
     (Read tool only, working directory = that folder, skipped while Claude is
     known to be resting), then Codex (`codex exec --image ...`, read-only
     sandbox). There is no local vision model: if neither can look, the review
     waits for the next round. Grades are validated against the showrunner's
     own schema before anything is written - a malformed verdict would become
     a HOLD that burns the request.
   - up to 6 REWRITES, skipping any story whose video still has an open
     review (new words first would upload the old video under a new title);
     Claude -> Codex -> her own model (`reasoner.work_json_with_provider`),
     each answer pre-checked against the request's own rules (caps read from
     its PACE rule, one sentence per say, every number derivable from that
     beat's data with Shorts' own `beat_match` arithmetic, no new names);
     when unsure, skipped.
   - only with time left: up to 10 ASKS from the newest batch.
3. `python -m aletheia.shorts_mailbox status` shows the slots, today's
   rounds, a running round and the last report;
   `python -m aletheia.shorts_mailbox once --force` runs one round by hand.

## Not yet verified live

- No answer has round-tripped through Shorts' claim step yet.
- `codex exec --image` has not been run on his PC (the flag is in the Codex
  CLI; the argv is tested, the behaviour is not).
- The detached launch from the Core under `pythonw` on Windows has not been
  watched live (same flags as the local-model helper it now shares).
- Writes need a GitHub token with contents:write on Shorts-pipeline
  (`FLEET_TOKEN`, or the `github.fleet` secret); without one a round says so
  in `latest.json` and writes nothing.
