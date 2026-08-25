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
| 4 | Policy engine (risk, authority, approval objects, kill switch) | **PARTIAL** | Working embryo: `front_door` grants + `approval_policy` declarations + pre-network checks (`aletheia/act.py`). Missing: Approval store/lifecycle, delegated-authority rules (§56 L3), kill switch |
| 5 | Orchestrator V1 (goal → deterministic plan → tasks → verify) | **TICKET** | Contracts + task engine ready for it; next major build |
| 6 | Command Center V1 | **PARTIAL** (interim) | The intercom IS the interim command channel (BUILT); the real interactive surface needs the local Core |
| 6+ | Local Core runtime on the Windows PC | **TICKET** — on the critical path | Modular monolith adopting the same contracts/stores; unblocks every rung-4+ adapter |
| 7 | Windows computer control V0 | **BLOCKED** by local Core | `computer.control` NOT_BUILT in registry; accessibility-first per §13 |
| 8 | Browser control | **BLOCKED** by local Core | `browser.control` NOT_BUILT; dedicated authenticated profile per §14 |
| 9 | Agent Director (programmatic delegation to Claude/Codex) | **PARTIAL** | Delegation works socially today (each app's sessions + scheduled tasks, proven daily in Shorts-pipeline); `agent.delegate` EXPERIMENTAL; durable cross-agent dependency chains not yet dispatched by Aletheia itself |
| 10 | Voice V0 (room) | **TICKET** | Interim: ChatGPT Voice through the intercom's Project is voice-to-Thea today, minus wake word |
| 11 | Audio Router | **BLOCKED** by local Core | Windows-only subsystem |
| 12 | Phone V0 (call app ↔ virtual audio ↔ ChatGPT Voice) | **BLOCKED** by local Core + Phase 11 | EXPERIMENTAL until measured per §126; conduct rules §19 already doctrine |
| 13 | Email vertical slice | **TICKET** | read/draft/approve/send/verify; `email.send` NOT_BUILT, `operator_always` |
| 14 | Calendar + contacts | **TICKET** | `calendar.read` NOT_BUILT |
| 15 | Multi-capability scheduling | **BLOCKED** by 13+14 | the first big orchestration acceptance test |
| 16 | Memory V1 (identity/preferences/people/orgs with provenance) | **TICKET** | journal (episodic) BUILT; structured domains not |
| 17 | Event bus + watchers | **PARTIAL** embryo | pulse `transitions` are the first events; sentinel is the first watcher; general bus/watcher store not built |
| 18 | Room devices (Home Assistant) | **BLOCKED** by local Core | `room.scene` NOT_BUILT |
| 19 | Proactive Aletheia (SURFACE/NOTIFY/ACT tiers) | **PARTIAL** | sentinel + brief cover LOG/NOTIFY; ACT tier waits on Phase 4 policy |
| 20 | Self-expanding capabilities | **PARTIAL** (social loop) | gap → suggestion/plan/task → Claude builds → registry entry works with humans in the loop; automatic gap-to-task not built |
| 21 | Mobile (iPhone surface) | **TICKET** | approvals/notifications/voice/camera; furthest out with Phase 22 |
| 22 | Broad expansion (travel, shopping, finance visibility, …) | **TICKET** | only after primitives hold |

## Next five engineering milestones (priority order, per §137)

1. **Phase 4 — Policy engine v1**: Approval objects with a durable store
   (`state/approvals/`), `operator_once/always` flows through the
   intercom ("Approve?" → receipt), delegated-authority grants, kill
   switch (`aletheia stop-everything`), refusal + bypass tests.
2. **Phase 5 — Orchestrator v1**: deterministic goal→plan→tasks
   compiler over existing capabilities with per-step verification; first
   acceptance: "fix Shorts" decomposed into observable, verifiable tasks.
3. **Phase 9 — Agent Director v1**: task-engine-driven delegation files
   the work order (issue/branch) for a Claude session and tracks the
   dependency chain across restarts; acceptance test §153-3/4.
4. **Phase 6+ — Local Core bootstrap on the Windows PC**: a small
   persistent Python service adopting the same contracts/stores (repo
   remains the durable memory), serving the internal API the Command
   Center, voice, and rungs 4–7 need.
5. **Phase 7/8 — Computer + browser control V0** on that Core:
   accessibility-first Windows control and a dedicated browser profile —
   the two primitives that most expand the reachable world (§138).

## Non-goals, on the record

- No model API keys as a requirement (§6); no cookie theft, no
  reverse-engineered endpoints — subscription clients or honest
  degradation.
- No authority bundled with ability (§70); no gate weakened to ship
  more, anywhere in the fleet.
- No Jarvis theater (§107): nothing renders as live that isn't.
- Spending, agreements, disclosures, destructive actions: always
  operator-confirmed (§56 L4) — no phase changes that.
