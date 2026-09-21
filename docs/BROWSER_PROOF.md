# "Apply anywhere": what the general browser loop actually did on real sites

Continuity wave C3a, 2026-09-17 (`docs/CONTINUITY_BRIEF.md` Part III items 7
and 8, and acceptance scenario D). Everything below is a RUN, not a test: the
same `browser_loop.pursue` that `web_task` calls, driven against live public
pages from this laptop, in ASSISTED mode, with headless Chromium.

**What was never done here.** No application was submitted. No account was
created. Nothing was approved by Aletheia or by this session on his behalf —
the one press in this document is on a public practice form, with fake data,
through a rehearsal of his approval in a throwaway state (§ "The one press").

## How the runs were isolated

- A sandbox private state, journal, approvals directory, workspace and browser
  profile, all in a scratch directory; his own `state/private` was read only
  once, read-only, to check that no posting used here appears in his
  application records (none does).
- A FAKE identity: "Jordan Testperson", jordan.testperson@example.com,
  (605) 555-0142, a made-up Sioux Falls address, and a throwaway one-page
  sample PDF resume generated for these runs. His name, resume, email, phone
  and accounts were never used, and no mailbox was read (the code source was a
  stub that answers "this is a rehearsal").
- `ALETHEIA_FRONTIER_OFF=1` for every run: Claude/Codex/ChatGPT unavailable, so
  any model decision is her own (`ollama:qwen3:8b`).
- One headless Chromium at a time, its own profile (never his Chrome profile),
  closed after each run; a handful of page loads per site.

## The proof matrix

Final pass, on the code as committed in this wave. "Stages" are the mission's
own checkpoints; "stop" is the named boundary; timings are wall-clock for the
whole run on a CPU-only laptop.

| site (domain) | system | stages reached | stop | time | what was filled |
|---|---|---|---|---|---|
| recruiting.paylocity.com | Paylocity (unfamiliar ATS) | posting -> apply wizard "Step 1 of 3" -> filled | QUESTIONS (3) | 49 s | first/last/preferred name, email, mobile + home phone, city, county, zip, resume x2 boxes |
| localsplash.applytojob.com | JazzHR (unfamiliar ATS) | posting+form -> filled | CAPTCHA (visible reCAPTCHA), with 5 questions named and "then 'SUBMIT APPLICATION' is next" | 13 s | first/last name, email, phone, city, state, resume |
| cornerstone.bamboohr.com | BambooHR (unfamiliar ATS, SPA) | posting -> application -> filled | CAPTCHA (visible reCAPTCHA), 6 questions named | 42 s | first/last name, email, phone, city, zip, resume |
| uhaul.wd1.myworkdayjobs.com | Workday (account wall + 6-step wizard) | posting -> Apply -> Apply Manually -> account form filled | ACCOUNT_CREATION_APPROVAL (pending; nothing pressed) | 35 s | email + a generated password held only in the vault |
| recruiting.ultipro.com | UKG/UltiPro (unfamiliar ATS) | posting | POSTING_CLOSED ("Closed: April 7, 2026") | 18 s | nothing (correctly) |
| epic.avature.net | Avature (unfamiliar ATS) | "How would you like to apply?" -> registration form -> filled | QUESTIONS (7: education block) | 25 s | email, confirm email, phone, first/preferred/last name, country, resume |
| janestreet.com | the company's own custom form | form -> filled | QUESTIONS (6) -> after answers, SUBMIT_APPROVAL (pending) | 16 s (+18 s after answers) | legal first/preferred/last name, email, confirm email, phone, employer, major, three Yes/No radios, school email, resume |
| columbusks.gov | a city's own WordPress/Divi application | form -> filled | QUESTIONS (8) | 23 s | last name, first name, phone |

Coverage against the brief: two unfamiliar ATSs and more (Paylocity, JazzHR,
BambooHR, UltiPro, Avature, Workday); two custom employer/government forms
(Jane Street, City of Columbus KS); an account wall (Workday); a multi-page
wizard (Paylocity "Step 1 of 3", Workday's 6 steps behind the account); optional
and required unknown questions everywhere (asked, never invented); a resume
upload on five of the eight; CAPTCHA boundaries on two; a closed posting.
Email verification did not appear before any of these boundaries, so that path
is covered by the fixture tests plus the post-submit code continuation
(`finish_verification`) rather than by a live site here. LinkedIn and Indeed
were not touched (manual-only in the seed).

**Nothing lied.** Every stop names the page, the exact remaining step and, where
questions remain, the site's own words for them. Two wordings were defects and
are fixed: "press ''" (a nameless icon button) and "Everything is filled in" on
a form whose required fields the readers could not see.

## Crash, restart, resume

The process tree (python + Chromium) was killed with `taskkill /F /T` mid-run:

- **Workday**, killed 25 s in, right after the Apply click: on disk the mission
  was RUNNING with one route step and two checkpoints. Resumed in a fresh
  process, it replayed that click, went on through "Apply Manually" to the
  account form, and stopped at the same ACCOUNT_CREATION_APPROVAL. 39 s.
- **Avature**, killed after the resume was attached: on disk, one attachment
  and two checkpoints. The resume replayed the upload (not a second one),
  filled the registration form and stopped at the same QUESTIONS. 30 s.
- **Paylocity**, killed after the Apply click: resumed, refilled nothing that
  was already there, and stopped on the same three typeahead questions.
- **Scenario D** (below), killed mid-decision.

Two defects this found: a mission resumed seconds after a kill could not open a
browser at all (the dying Chromium still held the profile), and a resumed
mission clicked the link it had just replayed. Both fixed.

## Duplicate prevention

At the Workday ACCOUNT_CREATION_APPROVAL, with the approval PENDING:

- `pursue` with the same goal and page returned the same mission, same
  approval, in 0.1 s, opening no browser;
- `resume(force=True)` did the same — no second approval was filed (the
  approvals directory was byte-identical before and after);
- `browser_loop.commit` refused: "approval ... is PENDING — nothing was pressed".

After the one real press (below), a second `commit` was refused ("was already
pressed at ... — confirmed") and re-running the goal returned DONE with no new
approval and no second POST. The site's log confirms one submission.

## The one press: press -> receipt verified, end to end on a live site

Site: `https://formy-project.herokuapp.com/form`, a public practice form whose
only purpose is automation practice. Fake data only; nothing about him was
sent, which is why this press did not need his approval.

1. The loop filled first name, last name, job title, years of experience and
   date, and stopped at SUBMIT_APPROVAL: *"Everything is filled in. The last
   step is a button that says 'Submit' — confirm it and I will press it."*
   The approval object was PENDING; nothing had been pressed.
2. The approval was granted as the OPERATOR would, through the documented CLI,
   against the sandboxed approvals directory:
   `python -m aletheia.policy decide <id> APPROVED --because "REHEARSAL of
   Caleb's approval by the C3a session, sandboxed private state, public
   practice form, fake data; not his approval"`. It is a rehearsal of his
   approval, not his approval, and it never touched his real approvals.
3. `browser_loop.commit` then ran the existing press path: the approval was
   checked usable, bound to the route's digest, consumed once in the journal,
   `submit_clicked` written to disk BEFORE the click, the route replayed in a
   fresh browser, the button pressed.
4. The site answered at `/thanks`: "Thanks for submitting your form / The form
   was successfully submitted!" — read back, classified SUCCESS, verdict
   `confirmed`, checkpoints `submit_clicked -> receipt_verified -> done`, one
   POST, one screenshot kept.

That is evidence that the press-and-verify path works end to end on a live
site. It is not evidence that a real application can be sent, and nothing here
claims that.

It also found a defect worth the whole exercise: the evidence was read from the
form a moment before the site's script navigated to the confirmation, and on a
fixture that navigates 700 ms after the click the same timing read the form
"still there" as REJECTED — the one verdict that allows a second press. Both
press paths now wait for the page to change before reading it.

## Scenario D: an unfamiliar site, a multi-step objective, the frontier off

**The site**: `books.toscrape.com`, a public sandbox shop nobody here had
driven before, no job code anywhere (the general skill, no `job_skill`).
**The objective**: *"open the page for the book Meditations in the philosophy
category and tell me its price"* — three pages deep, no search box.
**The setup**: `ALETHEIA_FRONTIER_OFF=1`, her own model warmed first
(`qwen3:8b`, kept loaded with `ALETHEIA_LOCAL_AI_KEEP_ALIVE=30m`), all calls
sequential, CPU only.

What happened, in order:

| step | page | who decided | what | time |
|---|---|---|---|---|
| 1 | the shop's front page | the page's own words | followed "Philosophy" | ~24 s (incl. browser start) |
| — | — | — | **process tree killed** (`taskkill /F /T`) 29.5 s in | — |
| — | — | — | on disk: RUNNING, 1 route step, 2 checkpoints | — |
| 2 | resumed in a new process | — | replayed the Philosophy click | 24 s |
| 3 | the Philosophy category | the page's own words | followed "Meditations" | 12 s |
| 4 | the Meditations page | `ollama:qwen3:8b` | "this is the page the goal asked for" | ~15 s |

Result: DONE, with the page itself as the evidence — title "Meditations | Books
to Scrape", url `/catalogue/meditations_33/index.html`, and the text that
carries the answer ("£25.89, In stock"). 53 s from the resume. Every action was
verified by looking again (one `observed` checkpoint per page); nothing was
pressed; no job code ran.

**What it took to get there, honestly.** Four earlier attempts at the same kind
of objective did NOT finish, and each failure was a defect in the general layer,
now fixed: a killed browser blocked the next launch; the page reader kept only
the first 40 links, which on a category page is the sidebar, so the books were
invisible; a list's "next" outranked asking anybody, so she walked the shop one
page at a time; her model chose the page it was already on, then "Add to basket"
(now SPEND, refused); and nothing recognised arrival, so a correct walk kept
walking.

**What her own model costs here, measured.** A fresh page's routine decision is
~400 prompt tokens at ~7 tokens/s on this CPU: 50-60 s, which does NOT fit the
routine class's 45 s ceiling, so with the frontier off the decision goes to the
standard class's local bridge (measured 79 s end to end). Warm, with the prefix
cached, decisions came back in 6-40 s. The arrival question is small and cheap
(~15 s). The 27B "deep" model never fits this laptop, as before.

**What her own model is not good at, measured.** Asked to find one book among a
thousand with no category named ("open the product page of the book called
Meditations"), qwen3:8b wandered — Mystery, Historical Fiction, Home, Classics,
Philosophy, Nonfiction — confidently, five to twenty steps, never picking the
book. The loop never lied about it: every stop said where it was and that
nothing on the page moved toward the goal, and the circle guards stopped it.
That is the honest shape of local-only navigation on this machine: it follows
the goal's own words well, and it guesses badly when the page does not contain
them.


## Defects found live, and where each was fixed

Everything below was found by these runs and fixed in the general layer (page
states, the loop, the two page readers, the press path) or in the job skill —
never as a special case for one site. Each has a regression test in
`tests/test_browser_loop_anywhere.py` (or `tests/test_continuity_gateway.py`).

1. A cookie banner's toggles made a job posting read as a FORM, and its
   nameless icon button became the button he was asked to approve ("press ''").
2. A read-only "Link to This Job" box did the same on BambooHR.
3. `formfill` read the id `info.firstName` as one blob containing "name", so
   the full name went into First, Middle, Last and Preferred name.
4. Boxes whose labels are not tied to them were nameless to the loop; they are
   named from their id's words now ("info first name", "university email").
5. Search-as-you-type boxes were typed into and left, which throws the answer
   away; they are chosen from the menu now, and a widget already showing a
   choice is not reported as blocking.
6. "How much experience do you have providing customer service over the phone?"
   got his phone number.
7. A question marked required only by an asterisk was never asked.
8. A SHARE button outranked the form's "Submit Application"; the CAPTCHA stop
   named a dropdown as the next step.
9. An answer the page would not take was silently dropped instead of becoming a
   question.
10. The one unnamed file box on a resume page (no id, no name) was invisible,
    so no resume went on.
11. Workday's dialog renumbered every target and the same Apply was clicked
    until the page stopped responding.
12. The vault password she had just typed was in the observation a model would
    be shown.
13. A closed posting had no Apply, and her own model wandered into
    "Accessibility Accommodation for Applicants" (180 s per guess).
14. A country list cut at 40 options "had no United States".
15. A select's value was compared as its option's code, so a resumed form chose
    the same option again.
16. Third-party sign-ins ("Apply With LinkedIn", "Dropbox", "Indeed Resume")
    were treated as buttons to approve.
17. A submit button carrying `class="g-recaptcha"` (the invisible check bound to
    it) read as a CAPTCHA wall.
18. CSS-styled radios timed out on their invisible input (20 s each).
19. An answered radio group was asked again after his answer.
20. A visible, worded, required box was dropped as a "twin" of another field.
21. Divi's `data-required_mark="required"` fields were invisible to both
    readers, so an approval said "everything is filled in" with most boxes
    empty.
22. "City, State, Zip Code" got only the zip — and the bad alias it taught the
    site skill outlived the fix.
23. The post-press evidence was read before the site's answer arrived.
24. A killed browser blocked the next launch; a resumed mission re-clicked a
    replayed link.
25. The routine decision prompt was long enough to be routed to the local model
    that does not fit this laptop.
26. A long page never showed her model the target it needed; her model then
    chose the page it was already on, nineteen times.

## What is still in the way (not fixed here)

- **Paylocity's State menu** answers "No Results Found" to typed search, so the
  state stays empty and becomes a question. Its address box is an address
  autocomplete, which has no suggestion for a made-up street — honest for a
  fake identity, unknown for a real one.
- **A CAPTCHA is still his**, on JazzHR and BambooHR; the loop fills everything
  else first and says exactly what remains.
- **Her own model is slow and sometimes wrong on this laptop.** A fresh page
  costs ~50-60 s of prompt reading at ~7 tokens/s, which does not fit the
  routine class's 45 s ceiling; with the frontier off, the decision then goes to
  the standard class's local bridge (~80 s). Twice it was confidently wrong on a
  long list of links.
- **An account wall is where a real application stops** until he approves
  creating an account; nothing in this wave pressed one.
- **No live site asked for an emailed code before a boundary**, so the
  post-submit code continuation is proved by fixtures, not by a live run.

## Proposal for the capability registry (not applied)

`web.task` should STAY **EXPERIMENTAL**. The evidence in this document does not
meet the bar for AVAILABLE:

- what is proved live: the no-adapter path reaches, reads and fills real
  application forms on eight unfamiliar sites, stops at precisely named
  boundaries, survives being killed, refuses a second approval and a second
  press, and presses-and-verifies end to end on a practice form;
- what is NOT proved: an approved press on a real employer's form, and a
  receipt from one. Every real site here ended at a boundary that is his by
  design (questions, a CAPTCHA, an account wall, a closed posting).

What would justify promotion, and can only be his to authorise: one real
application sent through this loop on his approval, with the site's own
confirmation read back (`receipt_verified`), followed by a second site with a
different system. Until then the registry entry is accurate as it stands, and
this document is the evidence behind it.

## How to re-run any of this

The runs were driven by throwaway scripts in the session scratchpad (not part
of the repo): a sandboxed runner, a kill-and-resume harness, an answer harness,
and the two-phase press rehearsal. Everything they call is the product itself —
`browser_route.skill_for`, `browser_loop.pursue`, `browser_loop.resume`,
`browser_loop.commit`, `aletheia.policy decide` — so the same sequence can be
run again from a fresh state with no fixture code.
