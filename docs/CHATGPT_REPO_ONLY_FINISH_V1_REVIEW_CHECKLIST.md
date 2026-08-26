# Claude review checklist — repo-only finish v1

- [ ] Rebase current `main` (branch is one pulse-only commit behind at handoff).
- [ ] Run full test suite + CI.
- [ ] Review mail event privacy, dedupe, and ambiguity refusal.
- [ ] Review pulse transition mirroring idempotency.
- [ ] Review mobile surface remains loopback-only.
- [ ] Review calendar provider normalization/sync/write approval hashing.
- [ ] Review verification profiles: execution receipt != outcome verification.
- [ ] Review handle-it fallback/retry/wait/evidence state machine.
- [ ] Update capability registry/ROADMAP/ARCHITECTURE only to statuses proven by tests/evidence.
- [ ] Do not execute history rewrite without explicit operator maintenance decision.
- [ ] Preserve all existing authority/approval/kill-switch gates.
