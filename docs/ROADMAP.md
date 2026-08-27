# Aletheia roadmap — the playbook's phases, honestly marked

North star and phase definitions: `docs/PLAYBOOK.md` (§§113–137).
Component-level detail: `docs/ARCHITECTURE.md`. Rule zero applies: BUILT
means code with a real caller and tests in this repo; nothing is marked
above its truth. Statuses: **BUILT** · **PARTIAL** · **IN PROGRESS** ·
**TICKET** · **BLOCKED** (with what blocks it).

| Phase | What | Status | Evidence / blocker |
|---|---|---|---|
| 0 | Refoundation — repo tells the truth about what Aletheia is | **BUILT** (2026-08-25) | PLAYBOOK.md, ARCHITECTURE.md, rewritten CLAUDE.md/README, this file |
| 1 | Core data contracts | **BUILT** v0 | `aletheia/contracts.py` (7 contracts, all enums); `tests/test_contracts.py` |
| 2 | Capability registry | **BUILT** v0 | `config/capabilities.json` + `aletheia/capabilities.py`; CI-validated; every entry names caller or ticket |
| 3 | Durable task engine | **BUILT** v0 | `aletheia/tasks.py` → `state/tasks/`; lifecycle/deps/retries; restart-survival tested; creatable by voice via intercom |
| 4 | Policy engine (risk, authority, approval objects, kill switch) | **BUILT** v1 | `aletheia/policy.py`: durable approvals (issue-published, decided by owner comment via `approvals.yml` or by voice), kill switch enforced in act/intercom/director, fail-closed on corrupt state; 8 tests. **2026-08-27:** L3 delegated authority is now CONSUMED, not merely recorded — `policy.request(capability=...)` spends an eligible grant and writes a claim receipt, so an approval he already gave is not asked again. `authority.allows` re-reads the registry at spend time, so a grant edited on disk to name a high-risk capability still buys nothing: §56 L4 holds structurally, and a test asserts every capability that spends, sends, binds or destroys is declared ungrantable |
| 5 | Orchestrator V1 (goal → deterministic plan → tasks → verify) | **BUILT** v1 | `aletheia/orchestrator.py`: compile open goals to dependency-chained tasks, evidence-gated step completion (§30 in code), runs every pulse; 7 tests. **2026-08-27 — AI-authored planning arrived** and did not replace this: `aletheia/planner.py` lets a reasoning provider PROPOSE, and every proposed step still passes `intercom.validate_kind_args` and the registry before it can run. `aletheia/reasoner.py` is the provider `brain.py` had been specified for since August and never had — the Claude CLI on the operator's own subscription, no API key (§6), `--tools ""` so it can emit text and nothing else |
| 6 | Command Center V1 | **BUILT** v1 | `interface/command.html` served by the Core: approvals with approve/deny, live task queue, 15-kind command composer, HALT/RESUME, receipts — every button the same gated grammar as the intercom. The intercom remains the remote/voice channel |
| 6+ | Local Core runtime on the Windows PC | **BUILT** v1 — **RUNNING, and now permanent** | `aletheia/core.py` + `aletheia/sync.py` + `aletheia/supervisor.py`: persistent stdlib service, internal API (§110), serves wall + Command Center, executes commands through intercom grammar + policy gates, loopback-only; sync loop pulls commands / executes PC-only kinds / pushes receipts; SELF-UPDATING (a merge to main restarts the Core onto the new code within a sync beat) and SUPERVISED (crash -> bounded-backoff relaunch; `supervisor install` = hidden at-logon task). One command on the PC: the bootstrap in docs/SETUP.md. **2026-08-27 — always-on:** she had been DEAD for six hours (Core aborted 12:42:05Z mid self-update; a single at-logon trigger; he never logged off; nothing noticed). `aletheia/autostart.py` holds the always-on contract as a pure function over a task's live settings — repeating watchdog, unbounded, power-blind, restarting, IgnoreNew — and `aletheia/liveness.py` makes downtime a measured fact rather than a silence. Proven live: both processes killed at 14:15:47Z, Core answering again at 14:15:59Z, room voice at 14:16:05Z |
| 7 | Windows computer control V0 | **EXPERIMENTAL** — code merged, unverified on Windows | `aletheia/computer.py` + Core `POST /api/computer`: typed plans, accessibility-only (screen coordinates refused), approvals bound to a sha256 of the exact plan and consumed once, halt re-checked before setup and every step, bounded waits/observation, redacted audit. 41 hermetic tests with an injected backend. **The UIA backend has never run on Windows** — `scripts/phase7_accept_notepad.ps1` is the acceptance run that decides AVAILABLE vs repair. Authored by Codex (PRs #11–16), reviewed and corrected by Claude |
| 8 | Browser control | **BUILT** v1 | `aletheia/browse.py`: persistent authorized profile, `read_page`/`screenshot` open, `interact` gated behind an APPROVED approval and refused before the browser opens; halt-aware; playwright optional with honest degradation. 12 hermetic tests drive real Chromium against a loopback fixture — including an approved form fill + submit |
| 9 | Agent Director (programmatic delegation to Claude/Codex) | **BUILT** v1 (dispatch) | `aletheia/director.py`: approval-gated work orders carrying the full §67 contract, filed automatically each pulse for READY assigned tasks; dependency chains on disk; 6 tests. EXPERIMENTAL until the first live round-trip; programmatic worker WAKE-UP still each app's own scheduled tasks |
| 10 | Voice V0 (room) | **BUILT** v0 (2026-08-26) | `aletheia/voice_room.py`: local wake word ('Thea') via vosk offline + grammar-constrained spotter, software AGC for this PC's quiet mic array, SAPI mouth, POST /api/voice through the same gates; runs as Windows task 'AletheiaVoice' at logon. PROVEN by machine self-test: she heard her own speakers say her name and answered out loud |
| 11 | Audio Router | **BUILT** v1 — live-proven | The control plane (`aletheia/audio_router.py`) shipped with only a declared fake backend, which is why it sat EXPERIMENTAL. `aletheia/audio_windows.py` is the real one: a PortAudio stream pair per approved route, and a route counts as active only when FRAMES HAVE MOVED since the last look — a stream that opened and went silent reads as dead, not as a bridge. No virtual cable needed; Bluetooth Hands-Free endpoints are ordinary devices. **Live 2026-08-27:** activation refused while PENDING, then approved and run mic → headphone jack: 41,600 frames in / 40,960 out, stopped clean |
| 12 | Phone V0 (call app ↔ audio ↔ conversation) | **EXPERIMENTAL** — every piece built and verified except the call itself | `aletheia/phone_v0.py` was a complete controller with NO caller in the repo; `aletheia/phone_cli.py` is the front door it never had, and it refuses rather than ever handing a caller a fake transport. `aletheia/phone_windows.py` dials through Phone Link to the paired iPhone via a `tel:` URI aimed at its AUMID — the protocol default here is Skype for Business, so a naive dial opens the wrong app and places no call. CONNECTED means Hands-Free endpoints ACTIVE in BOTH directions (MMDevice), after a first version wrongly read endpoint *presence* and reported a live call with none in progress. DTMF and hangup are unimplemented and say so. `phone_cli ready` → True on the PC. **The one thing left is a supervised test call to a safe number — outward-facing, so it is the operator's to authorize** |
| 13 | Email vertical slice | **BUILT** v0 code — NEEDS_CONFIGURATION | `aletheia/mail.py`: check unread by voice; 'Thea, email <name> that ...' -> local draft (gitignored — repo is public) + approval bound to a sha256 of the exact content -> 'Thea, approve' -> the Core sends it next tick and writes a receipt. Edited-after-approval refused; unknown recipient refused, never guessed; DENIED retires the draft. 15 tests. Needs ALETHEIA_MAIL_ADDRESS + app password on the PC |
| 14 | Calendar + contacts | **BUILT** v1 code — **NEEDS_CONFIGURATION** | `aletheia/contacts.py` + `aletheia/calendar.py` + `aletheia/meetings.py` (ChatGPT PR #29, Claude-reviewed). **2026-08-27 — the providers arrived** (ChatGPT `calendar-providers-v1`, Claude-reviewed): `aletheia/calendar_auth.py` runs a one-time local desktop OAuth consent (system browser, PKCE-S256, constant-time state, one loopback callback, no code/token ever printed or committed), and `calendar_live.py` picks ONE source of truth — an official Google/Graph provider when configured, the secret-ICS fallback otherwise, never both against the same account. `runtime.tick` refreshes it each beat. `calendar.read` stays NEEDS_CONFIGURATION until he authorizes an account; `calendar.write` stays EXPERIMENTAL and operator_always until one write round-trips live |
| 15 | Multi-capability scheduling | **BUILT** v1 — the orchestration milestone | `aletheia/scheduling.py`: "set up a meeting with X next week" as a durable negotiation that survives Tuesday (§27). Contacts, calendar slots, a gated email offer, a reply expectation, an interpreted answer and a hash-bound calendar write — every part existed and none were joined up. It SEQUENCES approvals and never substitutes for one: sending stays operator_always, booking stays operator_always. An APPROVED send approval is not "sent" — only the delivery marker is (§30). Anything ambiguous ends at NEEDS_OPERATOR, because booking the wrong hour of someone else's week is not recoverable. Honest gap named rather than hidden: `email.read_body` is NOT_BUILT (mail reads headers only, on purpose), so she sees that a reply landed and asks him to relay the words |
| 16 | Memory V1 (identity/preferences/people/orgs with provenance) | **BUILT** v1 | `aletheia/memory.py` → `memory/`: four domains, provenance on every entry, correction-learning (§46) records what it replaced, "why do you think that" answerable; writable by voice (`remember`); 6 tests. Richer person/org schemas later |
| 17 | Event bus + watchers | **BUILT** v0 | `aletheia/events.py` (ChatGPT PR #28, reviewed + repaired by Claude): immutable one-file-per-event bus + durable watchers with exactly-once triggers, PRIVATE by default (subjects carry personal facts; repo is public). Wired: core_tick emits sync-health events; `runtime.process_new_events` turns watcher triggers into notifications. 13+ tests |
| 18 | Room devices (Home Assistant) | **BUILT** v1 code — **NEEDS_CONFIGURATION** | `aletheia/hass.py`: the provider `room.plan()` had been ending at (`READY_FOR_PROVIDER`) since Phase 18 with nothing behind it. Home Assistant's REST API — one hub the operator already owns, not twelve vendor clouds (§152). Reading entity state is ungated; a scene needs an APPROVED approval, refuses any device not observed ONLINE, and re-reads the kill switch between devices. `runtime.tick` refreshes reachability each beat when configured, honest no-op when not. Needs `ALETHEIA_HASS_URL` + `ALETHEIA_HASS_TOKEN`: the code is real, the token is his to create |
| 19 | Proactive Aletheia (SURFACE/NOTIFY/ACT tiers) | **BUILT** v1 — NOTIFY built, judgment opt-in | `aletheia/proactive.py` + `aletheia/notifications.py` (deterministic rules, cooldown, dedupe) — unchanged. **2026-08-27 — judgment** (ChatGPT `situational-context-v1`, Claude-reviewed): `aletheia/situational.py` assembles a bounded private NOW (bodies omitted, room state allow-listed, whole records dropped under byte pressure rather than JSON sliced), and `aletheia/advisor.py` lets a tool-less provider judge ONE event as IGNORE / NOTIFY / SUGGEST. DISABLED by default — building a proactive brain is not permission to send every event through a model. A SUGGEST publishes a notification and a referent; it is not an Intent and not an approval, so the ACT tier is still proposal-only and the operator must still ask (§70) |
| 20 | Self-expanding capabilities | **BUILT** v0 (gap loop) | `aletheia/gaps.py` + `runtime.reconcile_task_gaps` each Core beat: a task requiring a non-AVAILABLE capability is paused with the gap named, build/configure/verify work is materialized idempotently, and the original resumes when the registry closes the gap. `aletheia/handler.py` persists handle-it requests across the gap. Tests prove pause→materialize→resume |
| 21 | Mobile (iPhone surface) | **BUILT** v1 code — **NEEDS_CONFIGURATION** | `interface/mobile.html` + `mobile.js`, and as of 2026-08-27 a transport that can actually carry them: `aletheia/access.py`. Off-loopback listening requires BOTH a minted token (sha256-stored, scoped, expiring, rate-limited) AND a TLS certificate, and refuses without either — port 8777 is never simply exposed. A `read` token answers GET and nothing else. Loopback stays unauthenticated: same trust boundary as V0. NEEDS_CONFIGURATION until he mints a token and supplies a cert (`tailscale cert` also solves reaching home without opening a port) |
| 22 | Broad expansion (travel, shopping, finance visibility, …) | **BUILT** v1 — one primitive, one boundary kept shut | ChatGPT PR #30 (reviewed line-by-line): places, documents, shopping, subscriptions, finance (read-only), vehicles, travel, reservations — all private-state models driven by `python -m aletheia.assistant`. **2026-08-27:** the last mile is `aletheia/errands.py` — ONE approval-bound, evidence-verified web errand rather than five merchant integrations (§152). purchase.execute, reservation.book and subscription.cancel are the same errand with different kinds, EXPERIMENTAL until each round-trips live. Authorization binds to sha256{site, kind, steps, ceiling}; a spending errand checks the LARGEST money figure on the page against its ceiling BEFORE clicking; §143's boundaries (bank step-up, one-time codes, CAPTCHA, signatures, ID, biometrics, consent) stop the errand and hand him the remainder. `finance.transact` stays NOT_BUILT **by decision** — there the boundary IS the mechanism — and `finance.hand_off` is the other half of §143: the whole movement prepared, the authorization left to him |

## Systems layer (2026-08-26, ChatGPT PRs #28–30 reviewed + integrated)

Under explicit operator authorization, ChatGPT drafted a repo-only
systems layer; Claude reviewed every line, repaired the defects (see
the journal), built the missing wiring, and integrated it:

- **Scheduler** (`aletheia/scheduler.py`): durable once/interval/daily/
  weekly schedules, timezone-aware, idempotent occurrence claims — due
  commands revalidate through the intercom grammar and the same gates
  as voice, inside every Core sync beat (`runtime.run_due_schedules`).
- **Communications** (`aletheia/communications.py`): channel-neutral
  threads/messages + reply expectations; `runtime.evaluate_replies`
  turns REPLIED/OVERDUE transitions into notifications.
- **Action records** (`aletheia/outcomes.py`): hash-bound plans,
  attempts separate from verification, evidence-gated VERIFIED (§30).
- **Current state** (`aletheia/current_state.py`): the canonical NOW —
  Core `GET /api/state`, `assistant state`.
- **Delegated authority** (`aletheia/authority.py`): EXPERIMENTAL —
  grant records work, but no acting path consumes them; wiring
  consumption would widen authority and waits on an operator ruling.
- **Assistant CLI** (`aletheia/assistant.py`): the operator front door
  giving every personal-OS verb a real caller (rule zero).

## Next five engineering milestones (priority order, per §137)

The five gaps between Aletheia and the thing she is supposed to be were
closed on 2026-08-27 (see the phase rows above and the journal). What is
left is not architecture — it is the handful of credentials and live
round-trips that only the operator can supply. Each one flips a registry
entry on real evidence, not on more code.

1. **Give her the room** (`room.scene`, NEEDS_CONFIGURATION): create a
   long-lived token in Home Assistant, set `ALETHEIA_HASS_URL` and
   `ALETHEIA_HASS_TOKEN` on the PC, then `python -m aletheia.hass observe`
   and one approved scene. The adapter and its gates are built and tested.
2. **Give her the phone** (`access.remote`, NEEDS_CONFIGURATION):
   `tailscale cert <name>` (which also gets you home without opening a
   port), then `python -m aletheia.access mint "iPhone"` and start the
   Core with `--host`/`--tls-cert`/`--tls-key`. Mint `read` first and live
   with it a while before minting `full`.
3. **The first live errand** (`errand.run`, `purchase.execute`,
   `reservation.book`, `subscription.cancel` — all EXPERIMENTAL): one real
   cancellation is the cheapest honest test, since it spends nothing and
   still proves the whole path. EXPERIMENTAL until one round-trips with a
   merchant's own confirmation; that evidence is what promotes them.
4. **Calendar providers** (`calendar.read` NEEDS_CONFIGURATION,
   `calendar.write` EXPERIMENTAL): the local models and the ICS mirror are
   built; a live Google/Outlook adapter is the remaining work, and it is
   the last thing standing between Phase 15's scheduling test and a real
   dentist appointment.
5. **Phase 12 — Phone V0** on the now-permanent Core: the audio router is
   EXPERIMENTAL against a hermetic backend and has never touched a real
   Windows device. `scripts/phase11_accept_audio.ps1` on the PC decides
   AVAILABLE or repair.

## Non-goals, on the record

- No model API keys as a requirement (§6); no cookie theft, no
  reverse-engineered endpoints — subscription clients or honest
  degradation.
- No authority bundled with ability (§70); no gate weakened to ship
  more, anywhere in the fleet.
- No Jarvis theater (§107): nothing renders as live that isn't.
- Spending, agreements, disclosures, destructive actions: always
  operator-confirmed (§56 L4) — no phase changes that.
