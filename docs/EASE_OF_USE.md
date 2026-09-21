# Aletheia Ease-of-Use Pass

Operator brief, 2026-09-18, after the architecture build (docs/JARVIS_BRIEF.md,
docs/CONTINUITY_BRIEF.md). His words: **"The big architecture build is
finished. Do not start another major architecture project."**

**This pass is about one thing: make Aletheia extremely easy and pleasant for
Caleb to actually use every day.** Use what already exists. Consolidate and
polish rather than inventing new systems.

## The six outcomes

1. **One simple Thea interface.** Phone and PC feel like the same product. He
   never sees JSON, internal command names, model names, ids, branches or
   developer terminology in normal use. The main experience is: Ask Thea /
   what she's doing / what needs Caleb / what she finished.
2. **The phone actually useful.** Secure use from his iPhone away from the PC,
   voice and text both, clear connected / offline / reconnecting states, and no
   remembering ports, IP addresses or setup steps.
3. **Voice feels good.** Improve the room and phone voice with the speech
   systems already built: natural short responses, follow-up conversation that
   works, he can interrupt her, and never a technical string or a giant
   paragraph read aloud.
4. **Human communication.** Every response answers: what happened, what it
   means, what happens next. "What are you doing?" gives a simple truthful
   answer. Errors, blockers and approvals are written for a normal person.
5. **Simple attention management.** ONE "Needs you" place for everything that
   genuinely requires him. One clean activity/history view. Notify only when
   something important finishes, fails, changes, or actually needs him; routine
   reversible work happens quietly.
6. **No maintenance friction.** She starts automatically and recovers from
   ordinary crashes herself. A simple health view when something is broken.
   Normal operation never requires GitHub, PowerShell, Claude, Codex or ChatGPT.

## Hard scope rule

**Do not turn these six outcomes into six new frameworks.** Reuse the existing
phone UI, mobile UI, PWA, voice system, current-state system, notifications,
approvals and work engine. Delete or consolidate duplicate surfaces where
useful. A focused UX/product pass, not another five-day rebuild.

**If a change does not make his actual experience noticeably easier, do not
build it.**

At the end, test on the real PC and iPhone with a few normal requests, and fix
the obvious friction.

## The standard

He opens or talks to Thea, tells her what he wants, understands what she is
doing, answers the occasional thing she genuinely needs, and otherwise forgets
the machinery exists.
