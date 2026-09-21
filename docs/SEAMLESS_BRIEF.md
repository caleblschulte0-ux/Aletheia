# Aletheia — From Capable to Seamless

Operator brief, 2026-09-21, relayed by the operator from ChatGPT after the
2026-09-19 live failures. **This brief changes the definition of "done".**
Kept here as a working summary of its twenty sections, in the order he
gave them; where a sentence is his it is quoted, the rest is paraphrase.

## The definition of done

Done is **several normal days in which Caleb uses Aletheia without acting
as her sysadmin**: no PowerShell, no reading logs, no restarting her, no
re-entering something she had already been told, no question she could
have settled herself. A green test suite is evidence, not done. A feature
that works when phrased one way and not another is not built.

## Hard rule

**Do not rebuild Aletheia.** Connect, fix, simplify and delete before
adding architecture. The architecture build is finished
(docs/EASE_OF_USE.md); this pass finishes what exists.

## The twenty sections, short

1. **Wording must not gate capability.** "Start applying." works exactly
   like "Apply to 8 jobs for me." with no frontier model in the loop.
2. **Survive model outages** with graceful degradation and honest words:
   what she can still do, what waits, and why.
3. **Local AI and private state survive updates.** An explicit lifecycle
   independent of git: migrate, verify before retiring the old install,
   roll back on failure. Never lose what he told her.
4. **"On it" is a promise.** Every ask that starts background work leaves
   a durable record with truthful states; "what are you doing" answers
   from that record, and it is never IDLE a second after "on it".
5. **Finish the action loop to the outcome** — not "command executed"
   but the receipt, the confirmation page, the reply.
6. **Stop handing him solvable questions.** A clarifying question is a
   defect unless the answer genuinely is his alone.
7. **Harden the generic browser on real failures** — fix the class each
   incident belongs to, never the incident.
8. **Durable continuation**: work outlives the conversation, the process
   and the reboot.
9. **Fix the upgrade and start-up path**: a real Windows PowerShell 5.1
   parse in CI; never stop the old services before the new code is proved.
10. **Finish the UX pass**: one Thea surface with Now / Needs you /
    Done-and-history, human error wording, providers invisible.
11. **The phone voice path** works end to end.
12. **The room voice** works end to end.
13. **Remove duplicate UX.**
14. **Acceptance is outcome-based, in real life**: real asks on the real
    PC and phone, by him.
15. **Mandatory regression tests for every 2026-09-19 failure.**
16. **A friction ledger**: every time he had to do something a normal
    person should not, record it and treat it as a defect.
17. **Do not hide failures.** A failure said plainly beats a quiet retry.
18. **Every message answers what happened, what it means, what happens
    next.**
19. **She keeps thinking when the subscriptions are out**, and says whose
    answer it is.
20. **The build order** is fixed:
    1. Repair today's proven seams: natural wording, local-model
       persistence, private-state and update continuity, truthful running
       state, Windows bring-up.
    2. Finish the UX pass.
    3. Abuse it in real life.
    4. A final reliability run: several normal days.

## Where it stands (kept honest, newest first)

- **2026-09-21 — step 1 built** (PR #120): every PowerShell script pure
  ASCII and parsed by Windows PowerShell 5.1 in CI; the one-liner fetches
  `live`; a failed local-AI activation never turns an earlier one off;
  the bring-up downloads the update and snapshots private state BEFORE
  stopping anything and holds the checkout to it after
  (`aletheia/continuity.py`); grounded status questions answered from
  the stores with every model off (`quick.status_of`); his ordinary
  phrasings for starting and continuing the job hunt reach
  `apply_campaign` with no model. The friction ledger (§16) is
  `aletheia/friction.py`, with five real writers and two readers.
- **Steps 2–4 are his to run and mine to fix**: they need the real PC,
  the real phone and real days. What each one finds goes in the friction
  ledger and comes back here as a fix to a class, never an incident.
