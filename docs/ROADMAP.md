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
| 6+ | Local Core runtime on the Windows PC | **BUILT** v0 code — **WAITING_OPERATOR** to run it | `aletheia/core.py`: persistent stdlib service, internal API (§110), serves wall + Command Center, executes commands through intercom grammar + policy gates, loopback-only (no auth yet, refuses wider binds); 7 live-HTTP tests. Start with `python -m aletheia.core` on the PC |
| 7 | Windows computer control V0 | **BLOCKED** by local Core | `computer.control` NOT_BUILT in registry; accessibility-first per §13 |
| 8 | Browser control | **BUILT** v1 | `aletheia/browse.py`: persistent authorized profile, `read_page`/`screenshot` open, `interact` gated behind an APPROVED approval and refused before the browser opens; halt-aware; playwright optional with honest degradation. 12 hermetic tests drive real Chromium against a loopback fixture — including an approved form fill + submit |
| 9 | Agent Director (programmatic delegation to Claude/Codex) | **BUILT** v1 (dispatch) | `aletheia/director.py`: approval-gated work orders carrying the full §67 contract, filed automatically each pulse for READY assigned tasks; dependency chains on disk; 6 tests. EXPERIMENTAL until the first live round-trip; programmatic worker WAKE-UP still each app's own scheduled tasks |
| 10 | Voice V0 (room) | **TICKET** | Interim: ChatGPT Voice through the intercom's Project is voice-to-Thea today, minus wake word |
| 11 | Audio Router | **BLOCKED** by local Core | Windows-only subsystem |
| 12 | Phone V0 (call app ↔ virtual audio ↔ ChatGPT Voice) | **BLOCKED** by local Core + Phase 11 | EXPERIMENTAL until measured per §126; conduct rules §19 already doctrine |
| 13 | Email vertical slice | **TICKET** | read/draft/approve/send/verify; `email.send` NOT_BUILT, `operator_always` |
| 14 | Calendar + contacts | **TICKET** | `calendar.read` NOT_BUILT |
| 15 | Multi-capability scheduling | **BLOCKED** by 13+14 | the first big orchestration acceptance test |
| 16 | Memory V1 (identity/preferences/people/orgs with provenance) | **BUILT** v1 | `aletheia/memory.py` → `memory/`: four domains, provenance on every entry, correction-learning (§46) records what it replaced, "why do you think that" answerable; writable by voice (`remember`); 6 tests. Richer person/org schemas later |
| 17 | Event bus + watchers | **PARTIAL** embryo | pulse `transitions` are the first events; sentinel is the first watcher; general bus/watcher store not built |
| 18 | Room devices (Home Assistant) | **BLOCKED** by local Core | `room.scene` NOT_BUILT |
| 19 | Proactive Aletheia (SURFACE/NOTIFY/ACT tiers) | **PARTIAL** | sentinel + brief cover LOG/NOTIFY; ACT tier waits on Phase 4 policy |
| 20 | Self-expanding capabilities | **PARTIAL** (social loop) | gap → suggestion/plan/task → Claude builds → registry entry works with humans in the loop; automatic gap-to-task not built |
| 21 | Mobile (iPhone surface) | **TICKET** | approvals/notifications/voice/camera; furthest out with Phase 22 |
| 22 | Broad expansion (travel, shopping, finance visibility, …) | **TICKET** | only after primitives hold |

## Next five engineering milestones (priority order, per §137)

1. **Run the Core on the PC + first live round-trips** (task
   `local-core-bootstrap`, WAITING_OPERATOR) — also what makes browser
   control usable by voice, since the intercom executes in Actions where
   no browser exists (task `core-processes-commands`): `git clone` +
   `python -m aletheia.core` on the Windows PC; then one real intercom
   command and one approved work order completed with evidence — flips
   `intercom.relay` and `agent.delegate` to AVAILABLE.
2. **Phase 7 — Windows computer control V0** on the running Core (task
   `computer-v0`): accessibility-first, the other half of §138. Written
   against a live Core so it can be verified rather than guessed.
3. **Phase 13 — Email vertical slice** (task `email-vertical-slice`):
   read/draft/approve/send/verify behind `operator_always`, using the
   now-real Approval Center.
4. **Phase 10/11 — Voice wake + audio router** on the PC: "Thea" →
   local wake → Core; the prerequisite for Phone V0 (Phase 12).
5. **Phase 17 — Event bus + watchers**: generalize pulse transitions
   into a shared event vocabulary with durable watchers ("tell me when
   they reply").

## Non-goals, on the record

- No model API keys as a requirement (§6); no cookie theft, no
  reverse-engineered endpoints — subscription clients or honest
  degradation.
- No authority bundled with ability (§70); no gate weakened to ship
  more, anywhere in the fleet.
- No Jarvis theater (§107): nothing renders as live that isn't.
- Spending, agreements, disclosures, destructive actions: always
  operator-confirmed (§56 L4) — no phase changes that.
