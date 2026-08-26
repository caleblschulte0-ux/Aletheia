# ChatGPT repo-only finish v1 — Claude handoff

**UNAPPROVED CHATGPT DRAFT. Claude line-by-line review required before anything lands on `main`.**

Operator asked ChatGPT to build items 1–6 from the repo-only backlog, then asked to wrap immediately because Claude is back online. This document is the stop-point. Do not assume every item is finished merely because code exists.

## Branch

`chatgpt/repo-only-finish-v1`

Cut from `main` at `dfe8024384a2e26697dc893bc3f7864c9b671786`.
At handoff, `main` is one commit ahead (`afc7a11056dff6f1cd31afe62b1dc08797f1166e`, a pulse/state refresh only). Rebase/merge current `main` before final review so generated state does not become a fake conflict.

## What was built

### 1. Real event producers
- `aletheia.mail.poll_events()` turns newly observed unread headers into deduped private `mail.received` events.
- Exact sender/subject correlation can record an inbound communication and satisfy an existing reply expectation; ambiguous matches emit an ambiguity event rather than guessing.
- `aletheia.runtime.mirror_pulse_events()` converts new fleet health transitions from `state/pulse/latest.json` into private `fleet.health_changed` events, with an idempotent cursor.
- The runtime tick polls mail, mirrors pulse transitions, then feeds the existing watcher/proactive consumer path.
- Tests: `tests/test_mail_events.py`, `tests/test_runtime_producers.py`.

### 2. Phase 21 mobile web surface
- `interface/mobile.html` + `interface/mobile.js` provide a phone-first Core surface using existing loopback APIs: current state, unread notifications, approvals, tasks, quick commands, notification ACK.
- It does not expose the Core beyond loopback and does not add authentication theater.
- Tests: `tests/test_mobile_surface.py`.

### 3. Calendar provider boundary
- `aletheia/calendar_provider.py` defines a provider-neutral normalized event contract, deterministic sync planning, conflict/import semantics, write-plan hashing, and approval-bound write proposals.
- `aletheia/calendar_provider_cli.py` is a thin local caller for fixture/provider-boundary testing.
- No Google/Outlook adapter or credentials are claimed.
- Tests: `tests/test_calendar_provider.py`.

### 4. Verification/recovery layer
- `aletheia/verification.py` wraps the existing `outcomes.py` ActionRecord store instead of inventing a second audit system.
- Capability verification profiles distinguish execution evidence from actual outcome proof.
- Runtime schedules create ActionRecords; durable receipts can be reconciled into private ActionRecords where safe.
- Tests: `tests/test_verification_profiles.py`, `tests/test_verification_reconciliation.py`.

### 5. Handle-it expansion
- `aletheia/handler.py` upgraded from READY/BLOCKED only into a bounded state machine with candidate plans/fallbacks, capability-based path selection, WAITING_EXTERNAL, retry scheduling via existing recovery policy, AWAITING_VERIFICATION, evidence-gated completion, and reconciliation/resumption.
- `aletheia/handle_cli.py` exposes the richer state machine without bypassing gates.
- Runtime calls `handler.reconcile_all()` each beat.
- Tests: `tests/test_handler_v2.py`.

### 6. Truth/privacy cleanup
- Stale PR #30 was closed and annotated as integrated-via-Claude-review, not directly merged.
- `docs/PRIVACY_HISTORY_REWRITE.md` documents a **non-destructive plan only** for the address that remains in public git history; ChatGPT did not rewrite history or force-push.
- `tests/test_public_privacy.py` guards that current public people memory contains no email-like address and private runtime roots remain gitignored/untracked.

## What Claude should finish/check

1. Rebase/merge the one pulse-only `main` commit first.
2. Run the full repository test suite and CI; ChatGPT did not get an authoritative full-suite result before the operator asked to wrap.
3. Review `mail.poll_events()` privacy and correlation semantics carefully. Header fingerprints must not leak addresses into committed state; ambiguous correlations must remain fail-closed.
4. Review runtime ordering and load: mail polling every Core beat may be too frequent for a live mailbox. If so, add a bounded poll interval/cursor rather than removing the producer.
5. Decide whether the calendar provider boundary should be registered as a separate EXPERIMENTAL/AVAILABLE-local capability and wire the CLI into the canonical assistant front door if that matches the architecture.
6. Review verification profile semantics. An execution receipt is not automatically goal verification; keep that distinction explicit.
7. Review the expanded handler state transitions and retry semantics against task/recovery contracts; no path may self-authorize a world-touching action.
8. Mobile surface should remain loopback-only until a real authenticated remote/mobile transport exists. Do not expose port 8777 to LAN/Internet as a shortcut.
9. Update `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, and `config/capabilities.json` only after tests and review establish the truthful statuses.
10. If the operator wants the old address removed from GitHub history, follow `docs/PRIVACY_HISTORY_REWRITE.md` as a coordinated maintenance operation; do not do it casually while the live Core is syncing.

## Explicit non-changes

- No merge to `main`.
- No force push or history rewrite.
- No delegated-authority consumption was wired into acting paths.
- No purchase/payment/subscription-cancel/reservation-book executor was added.
- No Google/Outlook credentials/provider, Home Assistant provider, phone/audio system, or new external-service credentials were added.
- No weakening of `operator_always`, kill switch, approval binding, or browser/computer gates.

Claude may amend, split, reject, or replace any part. The branch is a review surface, not system truth until reviewed and integrated.
