# Codex Phase 7 draft — ownership and review boundary

Status: **UNAPPROVED DRAFT**. Owner: **Codex session, 2026-08-25**.

This branch is deliberately isolated for Claude/operator review. Nothing in
this change is merged into `main`, wired into the Core, enabled at startup, or
declared available in `config/capabilities.json`.

## Codex-owned files

- `aletheia/computer.py`
- `tests/test_computer.py`
- `docs/CODEX_PHASE7_REVIEW.md`

No pre-existing repository file is part of this first slice. Claude can reject
the entire proposal by closing the draft PR or deleting the branch. It can
replace individual commits/files without disentangling them from unrelated
work.

## Safety boundary in this draft

- Every execution requires a durable `APPROVED` approval ID.
- The kill switch is checked before backend creation and before every step.
- The whole plan is validated before approval lookup or desktop access.
- Only named UI Automation selectors are accepted; coordinates are rejected.
- There is no visual-click fallback, shell execution, clipboard action, generic
  keystroke injection, browser action, Core endpoint, or startup hook.
- Every completed or failed step is appended to the journal with run and
  approval identifiers.
- `pywinauto` is optional and imported only on a Windows execution path.

## Evidence supplied by Codex

`tests/test_computer.py` is hermetic and uses an injected fake backend. It
covers approval refusal, malformed-plan refusal, coordinate rejection, ordered
execution, journaling, pre-run halt, mid-run halt, adapter failure, and honest
non-Windows degradation. It does not claim a real Windows UI Automation pass.

## Claude/operator approval checklist

1. Review the action schema and whether approval reuse is acceptable.
2. Review `pywinauto` selectors and verification evidence on Windows.
3. Run the complete repository test suite.
4. Run one local acceptance plan against a harmless app such as Notepad.
5. Decide whether to amend, squash, cherry-pick, or discard the Codex commit.
6. Only after acceptance: wire a Core caller and change `computer.control` from
   `NOT_BUILT` to `EXPERIMENTAL`; do not mark it `AVAILABLE` from unit tests.
