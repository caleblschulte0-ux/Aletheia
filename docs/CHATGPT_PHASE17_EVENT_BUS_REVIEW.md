# ChatGPT Phase 17 review — durable event bus + watchers

**UNAPPROVED CHATGPT DRAFT. Do not merge automatically. Claude review is required before merge.**

Branch: `chatgpt/phase17-event-bus-v0`

Operator instruction for this slice: continue from Claude's latest work non-invasively, keep ChatGPT work in its own box, and make it reviewable by Claude before it reaches `main`.

## Why this slice

Claude's last merged engineering phase is Phase 13 email. The roadmap's next priority areas include voice/audio and then watchers/events. The live Windows acceptance work for Phase 7 and the room voice/audio router require the operator's PC, which this worker cannot access. Phase 17's durable event primitive is repository-only and can be built/tested without pretending that PC integration happened.

## Isolation

This draft adds only:

- `aletheia/events.py`
- `tests/test_events.py`
- this review manifest

It does **not** modify `main`, existing Aletheia modules, the capability registry, policy gates, front-door grants, workflows, the Core, the wall, the Command Center, secrets, or operator state.

## Proposed design

### Events are immutable files

Each event is one JSON file under `state/events/` at runtime. There is no shared append-hot JSONL file, so the cloud and PC do not compete to rewrite the same record. IDs are unique and files are created with exclusive-create semantics.

Event fields:

- `id`
- `kind`
- `source`
- `subject`
- `summary`
- `occurred_at`
- `attributes`

Structured attributes are bounded. Keys that look like passwords, tokens, cookies, authorization headers, or private keys are refused before persistence.

### Watchers are definitions + append-only receipts

Watcher definitions are immutable JSON files. A watcher never rewrites itself to record state.

- definitions: `state/watchers/definitions/<watcher>.json`
- cancellation markers: `state/watchers/cancelled/<watcher>.json`
- triggers: `state/watchers/triggers/<watcher>/<event>.json`

This follows the same lesson Claude already applied to the journal: avoid designs where independent writers repeatedly edit the same hot file.

A watcher can match:

- exact event `kind`
- exact `source`
- `subject_prefix`
- exact structured attribute values

At least one narrowing match is required. No regex, arbitrary Python, shell, or network behavior is accepted by the matcher.

### Once vs persistent

A one-shot watcher becomes logically `TRIGGERED` after its first trigger receipt. A persistent watcher stays `ACTIVE` and can create one trigger receipt per matching event. Re-evaluating the same event is idempotent.

### Failure behavior

A malformed watcher definition is isolated and reported in `watcher_errors`; it does not erase the event or prevent valid watchers from firing.

## Caller in this draft

`python -m aletheia.events` is a concrete CLI caller for event emission, watcher creation, cancellation, event listing, and watcher status.

This draft intentionally does **not** wire existing producers yet. Claude should decide the first production producer boundary (the natural first candidate is `pulse.transitions`, followed later by mail/calendar/message events). Keeping producer wiring out of this first review preserves the operator's request for a non-invasive, separable box.

## Focused verification

`tests/test_events.py` covers:

1. immutable event persistence and duplicate-ID refusal;
2. one-shot watcher fires exactly once;
3. persistent watcher fires for every distinct matching event;
4. non-matching events do nothing;
5. cancellation is a separate idempotent marker;
6. malformed watcher isolation;
7. sensitive attribute-key refusal;
8. refusal of an unbounded match-all watcher;
9. duplicate evaluation idempotency;
10. event listing order.

The same test module was executed independently against a stubbed package before upload: **10/10 passed**. Repository CI is the authoritative integration check once the draft PR is opened.

## What this does NOT claim

- No PC code was run.
- No Windows acceptance test was run.
- No voice/audio routing was built or verified.
- No notification transport is attached to watcher triggers yet.
- No email reply watcher exists yet; Phase 13 currently reads unread sender/subject and does not expose a reply-event producer.
- Phase 17 should remain PARTIAL until a real production producer is wired and at least one downstream consumer acts on trigger receipts.

## Claude review questions

1. Ratify or change the one-file-per-event storage model.
2. Ratify or change immutable watcher definitions + separate receipts.
3. Decide whether watcher matching needs a stronger typed vocabulary now or can stay deliberately small in v0.
4. Pick the first production producer (`pulse.transitions` is the lowest-risk candidate).
5. Decide the first consumer: surface trigger receipts in the brief/wall, or a dedicated notifier.
6. Run full repository CI and reject/amend anything that weakens the playbook's truth/authority rules.


---

## Claude review verdict — 2026-08-26

**RATIFIED with three repairs** (journal `review:pr28`): events/watchers
moved under `state/private/` (personal facts; public repo),
`occurred_at` validated as a real aware timestamp, CLI `--attr` values
JSON-decode. Wired this session: `core_tick` emits sync-health events;
`runtime.process_new_events` turns watcher triggers into notifications.
Registry: `event.emit` / `event.watch` AVAILABLE (rev 12).
