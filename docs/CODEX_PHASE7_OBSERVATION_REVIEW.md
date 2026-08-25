# Codex Phase 7 observation slice — fourth stacked review boundary

Status: **UNAPPROVED STACKED DRAFT**. Owner: **Codex session, 2026-08-25**.

Base: `codex/phase7-uia-hardening-draft` (PR #14). This layer adds bounded
accessibility-tree observation and window screenshot evidence without adding
coordinate control, visual clicking, arbitrary paths, or activation on
`main`.

## Files in this slice

- `aletheia/computer.py`
- `tests/test_computer.py`
- `tests/test_computer_uia.py`
- `docs/CODEX_PHASE7_OBSERVATION_REVIEW.md`

## Proposed actions

- `list_windows` — returns bounded UIA metadata for top-level windows.
- `inspect_controls` — returns bounded UIA metadata below one named window.
- `screenshot_window` — captures only one named window to
  `cache/computer-captures/<simple-name>.png`.

All three remain inside the exact-plan, single-use, operator approval gate.
Window/control names can be sensitive, so returned observation collections are
omitted from journal evidence. Only action/count/verification/path metadata may
be journaled.

## Screenshot constraints

- simple PNG basename only; both slash styles and traversal are refused;
- fixed gitignored capture directory;
- existing files and symlinks are refused, so evidence is never overwritten;
- the result is verified by the PNG signature before success is reported.

## Evidence

Thirty-one focused tests pass locally with ResourceWarnings treated as errors.
Mock UIA tests exercise bounded window listing, bounded control inspection,
capture-directory confinement, PNG verification, and no-overwrite behavior.
This remains mocked evidence; no claim of a real Windows desktop run.

The single commit carries `[skip ci]` to avoid notification noise while CI
repair PR #13 remains an unmerged Claude-review draft.
