# ChatGPT Phase 11/12 draft — Claude review + live acceptance

**UNAPPROVED CHATGPT CODE. Do not merge without Claude line-by-line review.**

Branch: `chatgpt/repo-only-finish-v2`  
Base when created: `cf10a03` (Claude's live Phase 10 room-voice completion).

## What this draft actually builds

### Phase 11 — audio-router control plane

`aletheia/audio_router.py` provides:

- private route plans (`state/private/audio`), never raw audio;
- explicit physical/virtual endpoint metadata and bounded route topology;
- duplicate/self-route/direct-feedback refusal;
- sha256 binding of the exact route plan;
- a separate operator approval before activation;
- kill-switch checks before provider side effects;
- provider observation required before a route session is called ACTIVE;
- provider-match checks on observe/stop;
- cleanup allowed while halted;
- read-only `sounddevice` inventory;
- an injected `AudioBackend` protocol and a deterministic fake used only by tests.

`aletheia/audio_cli.py` is deliberately read-only with respect to live routing: inventory, build a private logical plan from JSON, and validate/show a plan.

`scripts/phase11_accept_audio.ps1` is a read-only Windows probe. It changes no audio settings and explicitly says inventory is not routing acceptance.

### Phase 12 — Phone V0 session seam

`aletheia/phone_v0.py` sits on top of Claude-reviewed `aletheia.calls` rather than replacing its authorization model.

A phone session cannot become PREPARED unless:

1. `calls.execution_envelope()` proves the exact call plan has its operator approval;
2. the mandatory Aletheia AI identity disclosure is intact;
3. a separately approved audio session is verified ACTIVE;
4. that audio plan's purpose is exactly `phone_bridge`;
5. the selected call transport matches the session's recorded provider.

Dial discipline:

- state is durably changed to DIALING **before** the external dial call;
- a crash/failure after that claim can never silently redial;
- halt is checked again immediately before dialing and keypad actions;
- keypad input is bounded to `0-9*#`;
- the approved maximum call duration is enforced by observation;
- provider terminal states trigger call + audio cleanup;
- hangup/route-stop remain allowed while halted;
- ending a call writes `verified: false`: call completion is not outcome completion.

`InMemoryCallTransport` is a hermetic test double only.

## What this draft DOES NOT build or claim

- no real Windows system-audio routing backend;
- no VB-CABLE/VoiceMeeter configuration automation;
- no Google Voice/Phone Link/other desktop call-app dialer;
- no ChatGPT Voice app bridge;
- no live call was placed;
- no live audio route was activated;
- no capability authority was widened;
- no `main` change.

The repo-only controller can therefore be accepted while the world-touching pieces remain unverified.

## Proposed capability truth if Claude accepts the code

Do **not** mark `phone.call` AVAILABLE. Suggested registry shape:

- `audio.route` — **EXPERIMENTAL**, medium risk, operator_always; module `aletheia.audio_router`; notes: policy/control plane built, no live Windows routing provider accepted yet.
- `phone.session.control` — **EXPERIMENTAL**, high risk, operator_always; module `aletheia.phone_v0`; notes: exact dual-gate session orchestration tested with an injected fake, no real call transport accepted yet.
- `phone.call` — remain **NOT_BUILT** until a real call provider is implemented and live-tested; update its note to say call authorization + session orchestration exist, while actual dial transport is the missing world-touching half.

This split avoids the old Phase 7 mistake where an implemented seam and an actual live capability were conflated.

## Required Claude review

Review every line of:

- `aletheia/audio_router.py`
- `aletheia/audio_cli.py`
- `aletheia/phone_v0.py`
- `tests/test_audio_phone_v0.py`
- `scripts/phase11_accept_audio.ps1`
- this document

Specific attacks to repeat or strengthen:

- plan tampering after approval;
- approval for another audio plan;
- halt racing activation/dial/keypad;
- backend claiming only some routes became active;
- backend/provider substitution after prepare;
- process death after DIALING claim but before handle persistence;
- duplicate dial attempt;
- phone session using a non-phone audio plan;
- identity-disclosure alteration;
- terminal provider state leaving audio active;
- call time-budget overrun;
- transport reports hangup but is not actually ended;
- raw audio or contact data leaking into git-tracked state.

## Live Phase 11 acceptance after merge/review

1. Run `powershell -ExecutionPolicy Bypass -File scripts/phase11_accept_audio.ps1` on the operator PC.
2. Record the physical input/output devices and any reviewed virtual-audio endpoints.
3. Choose/implement the Windows routing backend; do not guess device indexes in committed code.
4. Create one harmless route plan using scratch/loopback audio, not an active phone call.
5. Operator approves that exact route-plan hash.
6. Activate, observe every route ACTIVE, then stop and observe inactive.
7. Reboot/restart and confirm stale ACTIVE state fails closed rather than being assumed live.
8. Only then consider `audio.route` AVAILABLE.

## Live Phone V0 acceptance after Phase 11

1. Implement/review one real call transport using the adapter ladder (official/local client first; OS/browser/UIA fallback only when necessary).
2. Use a test destination appropriate for acceptance; do not call a real third party merely to prove the stack.
3. Create the exact call plan and exact audio plan; operator approves both.
4. Prove dial happens once, AI identity disclosure is spoken before substantive conversation, operator monitoring works, keypad works, and halt can immediately prevent further acting while hangup still works.
5. Verify outcome truth separately from transport completion.
6. Record measured latency/echo/feedback/failure behavior; Phone V0 stays EXPERIMENTAL until those are acceptable.

## CI truth

The first full-repository run at commit `c364853` (core modules + failure-mode tests) passed. Later hardening commits require their own green CI before this draft is handed back as review-ready.
