# Claude repair queue

This directory is a **handoff area only**. It exists so Claude can come back later, review specific failures found live, and decide what belongs on `main`.

Rules for this area:

- Nothing in here is production authority.
- Do not merge a proposed fix just because ChatGPT wrote the handoff.
- Reproduce the live failure, inspect the current architecture, then implement the smallest structural fix.
- Preserve Aletheia's safety boundaries. A weaker/local brain may answer simple grounded questions, but it does **not** gain repo-editing, coding, shell, spending, sending, or approval-bypass authority.

Current queue:

1. `2026-09-14-local-status-routing.md` — simple grounded status questions are incorrectly escalating into frontier/deep reasoning. The motivating live failure was asking for a status update on autonomous job applications while Claude/ChatGPT reasoning were unavailable.
