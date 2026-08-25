# Codex Phase 7 UIA hardening — third stacked review boundary

Status: **UNAPPROVED STACKED DRAFT**. Owner: **Codex session, 2026-08-25**.

Base: `codex/phase7-core-wiring-draft` (PR #12). This slice contains no
registry, Core route, workflow, dependency, bootstrap, Command Center, or
startup change. It hardens only the proposed adapter and its tests.

## Files in this slice

- `aletheia/computer.py`
- `tests/test_computer.py`
- `tests/test_computer_uia.py`
- `docs/CODEX_PHASE7_UIA_HARDENING_REVIEW.md`

## Reviewable safety decisions

1. Plans are capped at 50 steps; typed text, executable names, arguments,
   selector strings, and timeouts have explicit bounds.
2. Executable/argument control characters and invalid/oversized regular
   expressions are rejected before approval lookup or desktop access.
3. `set_text` now fails the run if exact UIA readback does not match.
4. `close_window` waits until the named window no longer exists instead of
   reporting that a close was merely requested.
5. Journal evidence is allowlisted to action/verification/process metadata.
   Typed or observed content and arbitrary backend fields are omitted.
6. Backend exception messages are returned to the approved local caller but
   are not persisted in the journal.
7. Non-object backend evidence is a verification failure.
8. Mock UIA tests assert named selectors and the UIA Invoke pattern; any
   attempted `click_input` coordinate/input fallback fails the test.
9. Application arguments are assembled with `subprocess.list2cmdline`; no
   shell execution path is added.

## Evidence

Twenty-six focused tests pass locally with ResourceWarnings treated as errors.
Five of those directly exercise the Windows backend contract through mocked
`pywinauto` objects. This remains unit/transport evidence, not a claim that a
real Windows desktop acceptance run passed.

The commit carries `[skip ci]` intentionally: until draft PR #13 is reviewed
and merged, the base workflow still duplicates runs and omits Playwright.
