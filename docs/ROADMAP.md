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
| 4 | Policy engine (risk, authority, approval objects, kill switch) | **BUILT** v1 | `aletheia/policy.py`: durable approvals (issue-published, decided by owner comment via `approvals.yml` or by voice), kill switch enforced in act/intercom/director, fail-closed on corrupt state; 8 tests. Remaining ticket: §56 L3 delegated-authority category rules |
| 5 | Orchestrator V1 (goal → deterministic plan → tasks → verify) | **BUILT** v1 | `aletheia/orchestrator.py`: compile open goals to dependency-chained tasks, evidence-gated step completion (§30 in code), runs every pulse; 7 tests. AI-generated planning is later, per the playbook |
| 6 | Command Center V1 | **BUILT** v1 | `interface/command.html` served by the Core: approvals with approve/deny, live task queue, 15-kind command composer, HALT/RESUME, receipts — every button the same gated grammar as the intercom. The intercom remains the remote/voice channel |
| 6+ | Local Core runtime on the Windows PC | **BUILT** v1 code — **WAITING_OPERATOR** to run it | `aletheia/core.py` + `aletheia/sync.py` + `aletheia/supervisor.py`: persistent stdlib service, internal API (§110), serves wall + Command Center, executes commands through intercom grammar + policy gates, loopback-only; sync loop pulls commands / executes PC-only kinds / pushes receipts; SELF-UPDATING (a merge to main restarts the Core onto the new code within a sync beat) and SUPERVISED (crash -> bounded-backoff relaunch; `supervisor install` = hidden at-logon task). One command on the PC: the bootstrap in docs/SETUP.md |
| 7 | Windows computer control V0 | **EXPERIMENTAL** — code merged, unverified on Windows | `aletheia/computer.py` + Core `POST /api/computer`: typed plans, accessibility-only (screen coordinates refused), approvals bound to a sha256 of the exact plan and consumed once, halt re-checked before setup and every step, bounded waits/observation, redacted audit. 41 hermetic tests with an injected backend. **The UIA backend has never run on Windows** — `scripts/phase7_accept_notepad.ps1` is the acceptance run that decides AVAILABLE vs repair. Authored by Codex (PRs #11–16), reviewed and corrected by Claude |
| 8 | Browser control | **BUILT** v1 | `aletheia/browse.py`: persistent authorized profile, `read_page`/`screenshot` open, `interact` gated behind an APPROVED approval and refused before the browser opens; halt-aware; playwright optional with honest degradation. 12 hermetic tests drive real Chromium against a loopback fixture — including an approved form fill + submit |
| 9 | Agent Director (programmatic delegation to Claude/Codex) | **BUILT** v1 (dispatch) | `aletheia/director.py`: approval-gated work orders carrying the full §67 contract, filed automatically each pulse for READY assigned tasks; dependency chains on disk; 6 tests. EXPERIMENTAL until the first live round-trip; programmatic worker WAKE-UP still each app's own scheduled tasks |
| 10 | Voice V0 (room) | **TICKET** | Interim: ChatGPT Voice through the intercom's Project is voice-to-Thea today, minus wake word |
| 11 | Audio Router | **BLOCKED** by local Core | Windows-only subsystem |
| 12 | Phone V0 (call app ↔ virtual audio ↔ ChatGPT Voice) | **BLOCKED** by local Core + Phase 11 | EXPERIMENTAL until measured per §126; conduct rules §19 already doctrine |
| 13 | Email vertical slice | **BUILT** v0 code — NEEDS_CONFIGURATION | `aletheia/mail.py`: check unread by voice; 'Thea, email <name> that ...' -> local draft (gitignored — repo is public) + approval bound to a sha256 of the exact content -> 'Thea, approve' -> the Core sends it next tick and writes a receipt. Edited-after-approval refused; unknown recipient refused, never guessed; DENIED retires the draft. 15 tests. Needs ALETHEIA_MAIL_ADDRESS + app password on the PC |
| 14 | Calendar + contacts | **PARTIAL** — local models BUILT, providers TICKET | `aletheia/contacts.py` (ambiguity-safe resolution, never guesses) + `aletheia/calendar.py` (aware datetimes, conflicts, buffers, multi-day free-slot search) + `aletheia/meetings.py` (`assistant meet`); authored by ChatGPT (PR #29), reviewed line-by-line by Claude. Live Google/Outlook adapter (`calendar.read`) stays NOT_BUILT |
| 15 | Multi-capability scheduling | **BLOCKED** by 13+14 | the first big orchestration acceptance test |
| 16 | Memory V1 (identity/preferences/people/orgs with provenance) | **BUILT** v1 | `aletheia/memory.py` → `memory/`: four domains, provenance on every entry, correction-learning (§46) records what it replaced, "why do you think that" answerable; writable by voice (`remember`); 6 tests. Richer person/org schemas later |
| 17 | Event bus + watchers | **BUILT** v0 | `aletheia/events.py` (ChatGPT PR #28, reviewed + repaired by Claude): immutable one-file-per-event bus + durable watchers with exactly-once triggers, PRIVATE by default (subjects carry personal facts; repo is public). Wired: core_tick emits sync-health events; `runtime.process_new_events` turns watcher triggers into notifications. 13+ tests |
| 18 | Room devices (Home Assistant) | **BLOCKED** by local Core | `room.scene` NOT_BUILT |
| 19 | Proactive Aletheia (SURFACE/NOTIFY/ACT tiers) | **PARTIAL** — NOTIFY tier BUILT locally | `aletheia/proactive.py` (bounded rules, cooldown, dedupe receipts — PR #29) + `aletheia/notifications.py` (private notification center — PR #30) evaluated against every new bus event each Core beat; Command Center panel + `/api/notifications` + ACK. `enqueue` proposals persist ordinary QUEUED tasks. The ACT tier stays proposal-only |
| 20 | Self-expanding capabilities | **BUILT** v0 (gap loop) | `aletheia/gaps.py` + `runtime.reconcile_task_gaps` each Core beat: a task requiring a non-AVAILABLE capability is paused with the gap named, build/configure/verify work is materialized idempotently, and the original resumes when the registry closes the gap. `aletheia/handler.py` persists handle-it requests across the gap. Tests prove pause→materialize→resume |
| 21 | Mobile (iPhone surface) | **TICKET** | approvals/notifications/voice/camera; furthest out with Phase 22 |
| 22 | Broad expansion (travel, shopping, finance visibility, …) | **PARTIAL** — visibility/planning BUILT, world-touching actions NOT_BUILT | ChatGPT PR #30 (reviewed line-by-line): places, documents, shopping, subscriptions, finance (read-only), vehicles, travel, reservations — all private-state models driven by `python -m aletheia.assistant`. Every real-world half (purchase.execute, reservation.book, subscription.cancel, finance.transact) stays NOT_BUILT high-risk operator_always |

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

1. **Run the Core on the PC + first live round-trips** (task
   `local-core-bootstrap`, WAITING_OPERATOR): `git clone` +
   `python -m aletheia.core` on the Windows PC; then one real intercom
   command and one approved work order completed with evidence — flips
   `intercom.relay` and `agent.delegate` to AVAILABLE. The PC side of
   the intercom is BUILT (task `core-processes-commands`, 2026-08-26):
   the Core's sync loop pulls the repo, executes PC-only kinds
   (`browse_read`/`browse_shot` — the real browser), and pushes
   receipts, verified end to end against a real bare repo. Voice →
   PC-browser needs only the Core running.
2. **Phase 7 — Windows computer control V0** on the running Core (task
   `computer-v0`): accessibility-first, the other half of §138. Written
   against a live Core so it can be verified rather than guessed.
3. **Phase 13 — Email vertical slice** (task `email-vertical-slice`):
   read/draft/approve/send/verify behind `operator_always`, using the
   now-real Approval Center.
4. **Phase 10/11 — Voice wake + audio router** on the PC: "Thea" →
   local wake → Core; the prerequisite for Phone V0 (Phase 12).
5. **Phase 17 — event producers**: the bus, watchers, and consumers
   are BUILT; what remains is richer producers (mail check emitting
   mail.reply events, pulse transitions mirrored as events on the PC)
   so "tell me when they reply" fires from real mail, not just
   manually recorded messages.

## Non-goals, on the record

- No model API keys as a requirement (§6); no cookie theft, no
  reverse-engineered endpoints — subscription clients or honest
  degradation.
- No authority bundled with ability (§70); no gate weakened to ship
  more, anywhere in the fleet.
- No Jarvis theater (§107): nothing renders as live that isn't.
- Spending, agreements, disclosures, destructive actions: always
  operator-confirmed (§56 L4) — no phase changes that.
