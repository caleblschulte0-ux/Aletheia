# Codex Phase 7 interruptibility — fifth stacked review boundary

Status: **UNAPPROVED STACKED DRAFT**. Owner: **Codex session, 2026-08-25**.

Base: `codex/phase7-observation-draft` (PR #15). This layer changes only the
proposed adapter and focused tests. It remains inactive on `main`.

## Problem closed

The prior draft checked the kill switch before each action, but a UI Automation
wait could block for its full timeout before noticing a new halt. Aletheia's
stop command should interrupt a stalled accessibility lookup promptly.

## Proposed behavior

- window, control, and window-close waits poll in intervals no longer than
  0.5 seconds;
- the kill switch is checked before every poll;
- only pywinauto's timeout exception is retried; other adapter failures surface
  immediately;
- each step remains capped at 60 seconds;
- the sum of declared/default waits in one plan is capped at 300 seconds;
- `open_app` no longer accepts an ignored timeout field.

## Evidence

Thirty-three focused tests pass locally with ResourceWarnings treated as
errors. New mock-UIA tests prove a timed-out poll retries, a halt during that
wait interrupts before another UIA call, and close verification also uses the
short polling interval.

The one commit carries `[skip ci]` solely to avoid notification noise while
CI repair PR #13 remains an unmerged review draft.
