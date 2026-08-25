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
| 6 | Command Center V1 | **PARTIAL** (interim) | The intercom IS the interim command channel (BUILT, 15 command kinds incl. halt/approve/remember); the real interactive surface needs the local Core |
| 6+ | Local Core runtime on the Windows PC | **TICKET** — on the critical path | Modular monolith adopting the same contracts/stores; unblocks every rung-4+ adapter |
| 7 | Windows computer control V0 | **BLOCKED** by local Core | `computer.control` NOT_BUILT in registry; accessibility-first per §13 |
| 8 | Browser control | **BLOCKED** by local Core | `browser.control` NOT_BUILT; dedicated authenticated profile per §14 |
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

1. **Phase 6+ — Local Core bootstrap on the Windows PC** (task
   `local-core-bootstrap`): a small persistent Python service adopting
   the same contracts/stores (the repo remains the durable memory),
   serving the internal API the Command Center, voice, and rungs 4–7
   need. The single biggest unblock left.
2. **Phase 7/8 — Computer + browser control V0** on that Core (task
   `computer-browser-v0`): accessibility-first Windows control and a
   dedicated browser profile — the two primitives that most expand the
   reachable world (§138).
3. **Phase 6 — Command Center V1** on that Core (task
   `command-center-v1`): conversation + task queue + approval center.
4. **First live delegation round-trip**: approve a real work order,
   have a Claude session complete it with evidence, orchestrator folds
   it back — flips `agent.delegate` from EXPERIMENTAL to AVAILABLE.
5. **Phase 13 — Email vertical slice** (task `email-vertical-slice`):
   read/draft/approve/send/verify behind `operator_always`.

## Non-goals, on the record

- No model API keys as a requirement (§6); no cookie theft, no
  reverse-engineered endpoints — subscription clients or honest
  degradation.
- No authority bundled with ability (§70); no gate weakened to ship
  more, anywhere in the fleet.
- No Jarvis theater (§107): nothing renders as live that isn't.
- Spending, agreements, disclosures, destructive actions: always
  operator-confirmed (§56 L4) — no phase changes that.
