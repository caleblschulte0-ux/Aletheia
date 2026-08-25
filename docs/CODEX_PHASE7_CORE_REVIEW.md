# Codex Phase 7 Core wiring — stacked review boundary

Status: **UNAPPROVED STACKED DRAFT**. Owner: **Codex session, 2026-08-25**.

This slice is intentionally based on, and separate from,
`codex/phase7-windows-control-v0`. Its pull request must target that branch,
not `main`. Rejecting this layer leaves the lower adapter proposal intact;
rejecting both leaves `main` unchanged.

## Files in this stacked slice

- `aletheia/computer.py` — exact-plan approval binding and single-use claims.
- `aletheia/core.py` — loopback-only status and execution endpoints.
- `tests/test_computer.py` — approval mismatch/reuse tests.
- `tests/test_core_computer.py` — live loopback HTTP safety tests.
- `scripts/phase7_accept_notepad.ps1` — requests approval for the exact plan.
- `docs/CODEX_PHASE7_CORE_REVIEW.md` — this ownership manifest.

The Core file is pre-existing repository code, so this slice is kept out of the
lower additive-only PR and bundled as one reviewable commit.

## Security decisions for Claude to challenge

1. An approval's `requested_action` must equal
   `computer.control:<sha256(canonical plan JSON)>`. An approval for any other
   plan or capability is refused.
2. A STARTED journal record consumes that approval. Success, partial failure,
   restart, or retry never turns one approval into a reusable desktop token.
3. Claiming is process-locked to prevent two Core request threads from using
   the same approval concurrently.
4. Plan validation, halt checks, approval checks, and claim journaling all
   happen before backend construction.
5. The Core binds loopback as before, caps request bodies at 64 KiB, rejects
   unknown fields, and supplies `requested_by` itself rather than trusting the
   caller.
6. HTTP outcomes distinguish invalid (400), unapproved (403), halted (409),
   unavailable adapter (503), and unexpected error (500).
7. `GET /api/computer/status` reads the registry's real status. This slice
   does not change that status from `NOT_BUILT`.

## Evidence

Seventeen hermetic tests pass locally, including live HTTP round-trips through
an ephemeral loopback Core. They prove gate ordering and transport behavior,
not real Windows UI Automation. No workflow, dependency list, registry,
Command Center, bootstrap path, or startup behavior changes in this layer.

## Deliberate stop gate

Do not target `main`, expose the endpoint beyond loopback, add automatic
dependency installation, wire Command Center buttons, or promote
`computer.control` until the harmless Windows acceptance receipt exists and
Claude/operator review accepts both draft layers.
