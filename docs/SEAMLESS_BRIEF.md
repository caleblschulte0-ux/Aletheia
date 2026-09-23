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

- **2026-09-23, overnight (his brief: "work nonstop through the night...
  hardening, more like Jarvis, handle more when the frontier models are out,
  UX, design like a designer").** What landed, each measured on his PC:
  - *The no-frontier floor was broken two silent ways.* The local-run ring
    (`state/private/local-ai/recent.json`) showed every pursuit pass answering
    in 145-511 s until 01:44Z and every one failing at ~15 s after: with the
    frontier "available" but answering nothing, the gateway handed her own
    model the leftover of a frontier-shaped budget (#158, `last_rung_s`:
    background always gets the background ceiling). And the pool's failover
    was fast->deep, so the 27b that never fits was tried and the 4b never
    was (#157, down the rungs). 97 "nobody could think" events in one night.
  - *Jobs without his tap.* His words: "this can apply to jobs without my
    permission... that's the whole point." The 09-12 grant had expired 09-19
    in silence and the beat's claim id was one the store refuses (#148);
    `standing jobs on` at his keyboard, a year, his words on the grant; a
    missing grant is said once with the command. Live since 03:15Z.
  - *The wall is links, the Thea page is the place, a tap answers now* (#147);
    *one click on every sentence that names a problem* (#149: `restart`,
    banner/health/notice/mission-card actions, answer box on a form's
    question); *one box never two* (#159); *design pass 1 and 2* from
    screenshots (#151, #156).
  - *Form reading:* a website's menu is never a question (#150); a page that
    was never a form is CLOSED not FAILED, and the brief carries the job
    hunt (#154).
  - *Sentences swept with every frontier off:* morning shapes (#152),
    three verbs (#153), status/focus/outcomes (#155), small facts and a
    refusal in words (#156), what her model was doing (#160).
  - *Not done, said plainly:* Lever `/apply` pages fill nothing and stop on
    "resume upload did not finish" (unprobed); `update_now`, `apply_retry`,
    `apply_questions`, `frontier_on` still need a kind; the poll interval and
    the Core's per-poll recompute; a multi-day unattended stretch has not
    been observed since these landed.

- **2026-09-23 — the wall is links, the Thea page is the place.** His
  words: *"if I click on shorts pipeline, something should pop up... [the
  wall] shouldn't have any capability that the command center doesn't...
  it needs to be a lot more responsive."* Audited first: the wall had ONE
  link and it 404'd on Pages; the Thea page could not see a repository or
  a fault at all (no route); every poll was two serialized waves and a
  5 s cache under a 15 s poll; "what exactly?" and "Not now" each cost a
  four-request round trip; an approved row stayed until the next poll.
  Fixed as one change (PR #147): every wall element links into the Thea
  page (relative), a folded fleet section reads the same pulse and a wall
  link opens that card, one request wave, repaint-from-last-answer with
  zero requests per shown-only tap, changed-markup-only writes, optimistic
  decisions. The render test found "approval:ap-1: APPROVED" in "What
  she's done" the first time it really tapped Approve; the journal line is
  a sentence now. Not yet: the poll interval itself (15 s) and the Core's
  per-poll recompute of the needs list; a phone tap on a wall link when
  the wall is the published Pages copy (no Core there, said on the page).
- **2026-09-23, 00:30 — everything that needed him, cleared on his word.**
  *"if it's job related and it's just applying to a job, approve it. And
  if you can't approve it, clear it."* 44 submissions approved, 22
  non-submission approvals denied (Create Account, About Us, Language…),
  42 applications stopped on a question only he could answer closed —
  through her own local door, journaled as his decision. Open question
  for him: standing rule or tonight's pile.
- **2026-09-22 evening — two more sweeps with every frontier off** (PRs
  #145–#146): 26 more sentence classes — the volume KeyError, four
  machine readings her own model had denied (disk, internet, open
  windows, address), lock / a named folder / close on the desktop, the
  reminders-schedule-tasks questions, "say that again", "you're wrong",
  "milk and eggs" as two rows, "clear the list", "when I get home", "call
  the dentist" (a door she lacks, said with the three she has).

- **2026-09-21 — a hundred and seven sentences with every model off.**
  His words: *"I just want to be able to talk at it and no matter what I
  say it will get stuff done."* Two probes through the real voice door in
  a sandbox with the Claude CLI hidden from the PATH, no Codex and no
  Ollama - the worst day the PC can have. Every sentence that came back
  "I can't think" or "kept for later" was a defect in something already
  built, and each got a fix and a test (`tests/test_seventy_sentences.py`):
  a reminder that only took a digit, a wake-up set for six in the
  evening, an errand read as a file search, a question read as "I did
  it", her own build tasks read out as his list, a fact she could not
  store without a model, a refusal swallowed into a shrug, a weather
  question dropped for a planner, unit conversions in the other word
  order, the week, greetings, thanks, "why are you slow", "I'm home",
  "goodnight". And a rule may now ANSWER outright when a fact on disk
  settles the ask - no resume, no number for his sister - so nothing is
  kept for a model that could not do better. Run it yourself:
  `python -m aletheia.talk --sandbox` with the model binaries off the
  PATH, and read what the room would hear.

- **2026-09-22 — the floor, when nobody else can think.** His words:
  *"it really needs to be able to handle a lot when there's no frontier
  model available."* Measured on his laptop with both subscriptions
  resting and a job batch running, and fixed as classes (PRs #130–#134):
  background local calls get the background budget (a nameless one got a
  conversation's 12 s); the job hunt's own local calls are work, not a
  conversation that pre-empts everything; Codex-out falls through; her own
  model is held to quoting in the pursuit; even evidence shares; a `small`
  model (qwen3:4b) under the fast one, fetched by her own self-healing —
  which now runs first in the beat instead of being skipped at its end;
  one heavy thing at a time when she is alone; and research: picking a
  query needs no model, alone it is background work carried as a
  follow-up, and the seam that dropped the word "background" carries it.
  The pursuit's own floor: qwen3:8b 557 s cold / 157 s warm, one honest
  sentence; qwen3:4b 562 s cold beside a batch, a grounded reading. A
  research question alone beside a batch is still more than ten minutes
  end to end — carried as a follow-up now, so the answer reaches him
  when it exists instead of the door timing out with her mid-read.

- **2026-09-21 — the update that stayed stuck for three days.** The first
  look at his PC after the week's merges: the Core there was running
  Thursday's code, 85 commits behind, with the page saying everything was
  running. Conflict markers left in the legacy journal by an autostash
  replay, a second clone left inside the checkout by a recovery, two
  supervisors and two Cores on one port, the always-on task disabled.
  Every one of those is now a class she handles herself
  (`sync.resolve_conflict_markers`, `sync.finish_owned_rebase`, the
  stray-clone exemption, `core.OneCoreServer`, `core.bind_or_yield`) and
  the one that cannot be handled is at least SAID
  (`running.update_stuck`: "I haven't managed to update myself for 3
  days — 85 newer changes waiting"). Steps 2–4 are still his to run;
  this is the kind of thing they exist to find.

- **2026-09-21 — the rung that never runs out.** His words: *"it's to the
  point I can say whatever I want and it will do stuff even when no
  frontier models are available."* Three rungs now: the frontier; her own
  model, shown a shortlist; and, under both, `aletheia/rule_planner.py`,
  which compiles a sentence a rule owns whole from its words in a
  millisecond with no model at all, through every gate a model's plan goes
  through, and says it took the sentence literally. Rules run BEFORE her
  model, so a plain sentence never waits on Ollama. And her own model
  repairs itself (`local_model_pool.ensure`): Ollama stopped is started, a
  missing model is fetched in the background, once, from activation and
  from every beat of the Core. What no rule owns and no model can plan is
  still kept and re-planned when a model is back; it is never guessed at.

- **2026-09-21 — step 2 begun, from the page and the probe, not the
  source.** The one page was rendered at a phone's width and a desk's and
  she was asked five ordinary things with every model down. Seven
  defects, fixed at the source with a test each
  (`tests/test_the_page_reads_like_a_person_wrote_it.py`): the reply when
  nobody can think was a log line; the standing nudge put a command in a
  spoken sentence; a plan with a gap offered and refused the same thing in
  one breath; a provider name scrubbed out of a "done" line left "Answered
  with on, from"; a "Work inventory" card sat above the one task it
  inventoried; "Next" repeated "Doing"; two health boxes said one fact
  twice. Still his to find: what a real day on the real phone shows,
  which no render here can.

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
