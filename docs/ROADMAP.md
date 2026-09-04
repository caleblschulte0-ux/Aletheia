# Aletheia roadmap — the playbook's phases, honestly marked

North star and phase definitions: `docs/PLAYBOOK.md` (§§113–137).
Component-level detail: `docs/ARCHITECTURE.md`. Rule zero applies: BUILT
means code with a real caller and tests in this repo; nothing is marked
above its truth. Statuses: **BUILT** · **PARTIAL** · **IN PROGRESS** ·
**TICKET** · **BLOCKED** (with what blocks it).

| Phase | What | Status | Evidence / blocker |
|---|---|---|---|
| 0 | Refoundation — repo tells the truth about what Aletheia is | **BUILT** (2026-08-25) | PLAYBOOK.md, ARCHITECTURE.md, rewritten CLAUDE.md/README, this file |
| 1 | Core data contracts | **BUILT** v0 | `aletheia/contracts.py` (7 contracts, all enums); `tests/test_contracts.py` |
| 2 | Capability registry | **BUILT** v0 | `config/capabilities.json` + `aletheia/capabilities.py`; CI-validated; every entry names caller or ticket |
| 3 | Durable task engine | **BUILT** v0 | `aletheia/tasks.py` → `state/tasks/`; lifecycle/deps/retries; restart-survival tested; creatable by voice via intercom |
| 4 | Policy engine (risk, authority, approval objects, kill switch) | **BUILT** v1 | `aletheia/policy.py`: durable approvals (issue-published, decided by owner comment via `approvals.yml` or by voice), kill switch enforced in act/intercom/director, fail-closed on corrupt state; 8 tests. **2026-08-27:** L3 delegated authority is now CONSUMED, not merely recorded — `policy.request(capability=...)` spends an eligible grant and writes a claim receipt, so an approval he already gave is not asked again. `authority.allows` re-reads the registry at spend time, so a grant edited on disk to name a high-risk capability still buys nothing: §56 L4 holds structurally, and a test asserts every capability that spends, sends, binds or destroys is declared ungrantable |
| 5 | Orchestrator V1 (goal → deterministic plan → tasks → verify) | **BUILT** v1 | `aletheia/orchestrator.py`: compile open goals to dependency-chained tasks, evidence-gated step completion (§30 in code), runs every pulse; 7 tests. **2026-08-27 — AI-authored planning arrived** and did not replace this: `aletheia/planner.py` lets a reasoning provider PROPOSE, and every proposed step still passes `intercom.validate_kind_args` and the registry before it can run. `aletheia/reasoner.py` is the provider `brain.py` had been specified for since August and never had — the Claude CLI on the operator's own subscription, no API key (§6), `--tools ""` so it can emit text and nothing else |
| 6 | Command Center V1 | **BUILT** v1 | `interface/command.html` served by the Core: approvals with approve/deny, live task queue, 15-kind command composer, HALT/RESUME, receipts — every button the same gated grammar as the intercom. The intercom remains the remote/voice channel |
| 6+ | Local Core runtime on the Windows PC | **BUILT** v1 — **RUNNING, and now permanent** | `aletheia/core.py` + `aletheia/sync.py` + `aletheia/supervisor.py`: persistent stdlib service, internal API (§110), serves wall + Command Center, executes commands through intercom grammar + policy gates, loopback-only; sync loop pulls commands / executes PC-only kinds / pushes receipts; SELF-UPDATING (a merge to main restarts the Core onto the new code within a sync beat) and SUPERVISED (crash -> bounded-backoff relaunch; `supervisor install` = hidden at-logon task). One command on the PC: the bootstrap in docs/SETUP.md. **2026-08-27 — always-on:** she had been DEAD for six hours (Core aborted 12:42:05Z mid self-update; a single at-logon trigger; he never logged off; nothing noticed). `aletheia/autostart.py` holds the always-on contract as a pure function over a task's live settings — repeating watchdog, unbounded, power-blind, restarting, IgnoreNew — and `aletheia/liveness.py` makes downtime a measured fact rather than a silence. Proven live: both processes killed at 14:15:47Z, Core answering again at 14:15:59Z, room voice at 14:16:05Z |
| 7 | Windows computer control V0 | **EXPERIMENTAL** — code merged, unverified on Windows | `aletheia/computer.py` + Core `POST /api/computer`: typed plans, accessibility-only (screen coordinates refused), approvals bound to a sha256 of the exact plan and consumed once, halt re-checked before setup and every step, bounded waits/observation, redacted audit. 41 hermetic tests with an injected backend. **The UIA backend has never run on Windows** — `scripts/phase7_accept_notepad.ps1` is the acceptance run that decides AVAILABLE vs repair. Authored by Codex (PRs #11–16), reviewed and corrected by Claude |
| 8 | Browser control | **BUILT** v1 | `aletheia/browse.py`: persistent authorized profile, `read_page`/`screenshot` open, `interact` gated behind an APPROVED approval and refused before the browser opens; halt-aware; playwright optional with honest degradation. 12 hermetic tests drive real Chromium against a loopback fixture — including an approved form fill + submit |
| 9 | Agent Director (programmatic delegation to Claude/Codex) | **BUILT** v1 (dispatch) | `aletheia/director.py`: approval-gated work orders carrying the full §67 contract, filed automatically each pulse for READY assigned tasks; dependency chains on disk; 6 tests. EXPERIMENTAL until the first live round-trip; programmatic worker WAKE-UP still each app's own scheduled tasks |
| 10 | Voice V0 (room) | **BUILT** v0 (2026-08-26) | `aletheia/voice_room.py`: local wake word ('Thea') via vosk offline + grammar-constrained spotter, software AGC for this PC's quiet mic array, SAPI mouth, POST /api/voice through the same gates; runs as Windows task 'AletheiaVoice' at logon. PROVEN by machine self-test: she heard her own speakers say her name and answered out loud |
| 11 | Audio Router | **BUILT** v1 — live-proven | The control plane (`aletheia/audio_router.py`) shipped with only a declared fake backend, which is why it sat EXPERIMENTAL. `aletheia/audio_windows.py` is the real one: a PortAudio stream pair per approved route, and a route counts as active only when FRAMES HAVE MOVED since the last look — a stream that opened and went silent reads as dead, not as a bridge. No virtual cable needed; Bluetooth Hands-Free endpoints are ordinary devices. **Live 2026-08-27:** activation refused while PENDING, then approved and run mic → headphone jack: 41,600 frames in / 40,960 out, stopped clean |
| 12 | Phone V0 (call app ↔ audio ↔ conversation) | **EXPERIMENTAL** — every piece built and verified except the call itself | `aletheia/phone_v0.py` was a complete controller with NO caller in the repo; `aletheia/phone_cli.py` is the front door it never had, and it refuses rather than ever handing a caller a fake transport. `aletheia/phone_windows.py` dials through Phone Link to the paired iPhone via a `tel:` URI aimed at its AUMID — the protocol default here is Skype for Business, so a naive dial opens the wrong app and places no call. CONNECTED means Hands-Free endpoints ACTIVE in BOTH directions (MMDevice), after a first version wrongly read endpoint *presence* and reported a live call with none in progress. DTMF and hangup are unimplemented and say so. `phone_cli ready` → True on the PC. **The one thing left is a supervised test call to a safe number — outward-facing, so it is the operator's to authorize** |
| 13 | Email vertical slice | **BUILT** v0 code — NEEDS_CONFIGURATION | `aletheia/mail.py`: check unread by voice; 'Thea, email <name> that ...' -> local draft (gitignored — repo is public) + approval bound to a sha256 of the exact content -> 'Thea, approve' -> the Core sends it next tick and writes a receipt. Edited-after-approval refused; unknown recipient refused, never guessed; DENIED retires the draft. 15 tests. Needs ALETHEIA_MAIL_ADDRESS + app password on the PC |
| 14 | Calendar + contacts | **BUILT** v1 code — **NEEDS_CONFIGURATION** | `aletheia/contacts.py` + `aletheia/calendar.py` + `aletheia/meetings.py` (ChatGPT PR #29, Claude-reviewed). **2026-08-27 — the providers arrived** (ChatGPT `calendar-providers-v1`, Claude-reviewed): `aletheia/calendar_auth.py` runs a one-time local desktop OAuth consent (system browser, PKCE-S256, constant-time state, one loopback callback, no code/token ever printed or committed), and `calendar_live.py` picks ONE source of truth — an official Google/Graph provider when configured, the secret-ICS fallback otherwise, never both against the same account. `runtime.tick` refreshes it each beat. `calendar.read` stays NEEDS_CONFIGURATION until he authorizes an account; `calendar.write` stays EXPERIMENTAL and operator_always until one write round-trips live |
| 15 | Multi-capability scheduling | **BUILT** v1 — the orchestration milestone | `aletheia/scheduling.py`: "set up a meeting with X next week" as a durable negotiation that survives Tuesday (§27). Contacts, calendar slots, a gated email offer, a reply expectation, an interpreted answer and a hash-bound calendar write — every part existed and none were joined up. It SEQUENCES approvals and never substitutes for one: sending stays operator_always, booking stays operator_always. An APPROVED send approval is not "sent" — only the delivery marker is (§30). Anything ambiguous ends at NEEDS_OPERATOR, because booking the wrong hour of someone else's week is not recoverable. Honest gap named rather than hidden: `email.read_body` is NOT_BUILT (mail reads headers only, on purpose), so she sees that a reply landed and asks him to relay the words |
| 16 | Memory V1 (identity/preferences/people/orgs with provenance) | **BUILT** v1 | `aletheia/memory.py` → `memory/`: four domains, provenance on every entry, correction-learning (§46) records what it replaced, "why do you think that" answerable; writable by voice (`remember`); 6 tests. Richer person/org schemas later |
| 17 | Event bus + watchers | **BUILT** v0 | `aletheia/events.py` (ChatGPT PR #28, reviewed + repaired by Claude): immutable one-file-per-event bus + durable watchers with exactly-once triggers, PRIVATE by default (subjects carry personal facts; repo is public). Wired: core_tick emits sync-health events; `runtime.process_new_events` turns watcher triggers into notifications. 13+ tests |
| 18 | Room devices (Home Assistant) | **BUILT** v1 code — **NEEDS_CONFIGURATION** | `aletheia/hass.py`: the provider `room.plan()` had been ending at (`READY_FOR_PROVIDER`) since Phase 18 with nothing behind it. Home Assistant's REST API — one hub the operator already owns, not twelve vendor clouds (§152). Reading entity state is ungated; a scene needs an APPROVED approval, refuses any device not observed ONLINE, and re-reads the kill switch between devices. `runtime.tick` refreshes reachability each beat when configured, honest no-op when not. Needs `ALETHEIA_HASS_URL` + `ALETHEIA_HASS_TOKEN`: the code is real, the token is his to create |
| 19 | Proactive Aletheia (SURFACE/NOTIFY/ACT tiers) | **BUILT** v1 — NOTIFY built, judgment opt-in | `aletheia/proactive.py` + `aletheia/notifications.py` (deterministic rules, cooldown, dedupe) — unchanged. **2026-08-27 — judgment** (ChatGPT `situational-context-v1`, Claude-reviewed): `aletheia/situational.py` assembles a bounded private NOW (bodies omitted, room state allow-listed, whole records dropped under byte pressure rather than JSON sliced), and `aletheia/advisor.py` lets a tool-less provider judge ONE event as IGNORE / NOTIFY / SUGGEST. DISABLED by default — building a proactive brain is not permission to send every event through a model. A SUGGEST publishes a notification and a referent; it is not an Intent and not an approval, so the ACT tier is still proposal-only and the operator must still ask (§70) |
| 20 | Self-expanding capabilities | **BUILT** v0 (gap loop) | `aletheia/gaps.py` + `runtime.reconcile_task_gaps` each Core beat: a task requiring a non-AVAILABLE capability is paused with the gap named, build/configure/verify work is materialized idempotently, and the original resumes when the registry closes the gap. `aletheia/handler.py` persists handle-it requests across the gap. Tests prove pause→materialize→resume |
| 21 | Mobile (iPhone surface) | **BUILT** v1 code — **NEEDS_CONFIGURATION** | `interface/mobile.html` + `mobile.js`, and as of 2026-08-27 a transport that can actually carry them: `aletheia/access.py`. Off-loopback listening requires BOTH a minted token (sha256-stored, scoped, expiring, rate-limited) AND a TLS certificate, and refuses without either — port 8777 is never simply exposed. A `read` token answers GET and nothing else. Loopback stays unauthenticated: same trust boundary as V0. NEEDS_CONFIGURATION until he mints a token and supplies a cert (`tailscale cert` also solves reaching home without opening a port) |
| 22 | Broad expansion (travel, shopping, finance visibility, …) | **BUILT** v1 — one primitive, one boundary kept shut | ChatGPT PR #30 (reviewed line-by-line): places, documents, shopping, subscriptions, finance (read-only), vehicles, travel, reservations — all private-state models driven by `python -m aletheia.assistant`. **2026-08-27:** the last mile is `aletheia/errands.py` — ONE approval-bound, evidence-verified web errand rather than five merchant integrations (§152). purchase.execute, reservation.book and subscription.cancel are the same errand with different kinds, EXPERIMENTAL until each round-trips live. Authorization binds to sha256{site, kind, steps, ceiling}; a spending errand checks the LARGEST money figure on the page against its ceiling BEFORE clicking; §143's boundaries (bank step-up, one-time codes, CAPTCHA, signatures, ID, biometrics, consent) stop the errand and hand him the remainder. `finance.transact` stays NOT_BUILT **by decision** — there the boundary IS the mechanism — and `finance.hand_off` is the other half of §143: the whole movement prepared, the authorization left to him |

## Systems layer (2026-08-26, ChatGPT PRs #28–30 reviewed + integrated)

Under explicit operator authorization, ChatGPT drafted a repo-only
systems layer; Claude reviewed every line, repaired the defects (see
the journal), built the missing wiring, and integrated it:

- **Scheduler** (`aletheia/scheduler.py`): durable once/interval/daily/
  weekly schedules, timezone-aware, idempotent occurrence claims — due
  commands revalidate through the intercom grammar and the same gates
  as voice, inside every Core sync beat (`runtime.run_due_schedules`).
- **Communications** (`aletheia/communications.py`): channel-neutral
  threads/messages + reply expectations; `runtime.evaluate_replies`
  turns REPLIED/OVERDUE transitions into notifications.
- **Action records** (`aletheia/outcomes.py`): hash-bound plans,
  attempts separate from verification, evidence-gated VERIFIED (§30).
- **Current state** (`aletheia/current_state.py`): the canonical NOW —
  Core `GET /api/state`, `assistant state`.
- **Delegated authority** (`aletheia/authority.py`): EXPERIMENTAL —
  grant records work, but no acting path consumes them; wiring
  consumption would widen authority and waits on an operator ruling.
- **Assistant CLI** (`aletheia/assistant.py`): the operator front door
  giving every personal-OS verb a real caller (rule zero).

## PC bring-up of the catch-up build (2026-09-02)

The 2026-09-01 cloud build (missions, agendas, research, the workspace,
media, the script sandbox, desktop observation) had never run on the
operator's PC. A local session ran every command for real and fixed what
broke — none of it visible to a hermetic suite that was green throughout:

- `python` on the machine PATH is 3.9 (the package refuses it); 3.12 is
  installed and `py` resolves to it. Use `py -m aletheia...` or fix the
  machine PATH order (needs an elevated shell).
- The workspace default (`~/Aletheia`) was this repository's checkout:
  the first `file_write` was refused at the 2,000-file ceiling, and any
  file she wrote would have blocked the Core's sync as "a person's
  uncommitted work". Default is now `~/Documents/Aletheia`; a repository
  (or anything inside one) is refused as a root.
- Every new intercom kind (file_*, media_*, computer_observe, research)
  referenced a name that did not exist (NameError), and the agenda called
  `.get()` on the string every ordinary kind answers with — so the first
  live agenda reported its only step "failed". Both fixed; kinds answer
  with a line, a missing tool is `unavailable`, not an error.
- The script brief said "return ONLY the program" and its caller appended
  "return JSON"; the model returned the program, fenced, and was refused.
  One brief now, plus a text fallback.
- Research: DuckDuckGo's HTML endpoint serves the headless browser a
  captcha; Bing an unrendered shell with links for another query; and
  five 6,000-char extracts overflow the reasoner's 8 KB context. Engines
  now fall through (DuckDuckGo → Wikipedia search → Bing, redirects
  unwrapped), thin pages yield nothing, extracts shrink to fit.
- The code-trust grant from 2026-08-30 predated machine binding and was
  refused as unbound; re-minted locally with its remaining budget.
- A mission authorized an agenda regardless of its kind; `mission.covers`
  now scopes a mission to the capability its record names.
- Console output with an em dash or an odd window-title glyph crashed
  `print()` under cp1252; streams now replace rather than raise.

Promoted on live evidence (see each entry's `verification`): mission.run,
agenda.execute, file.author, research.answer, computer.observe,
media.edit (ffmpeg 9.0.1 installed; a real trim, source hash unchanged).
Still EXPERIMENTAL: code.autonomous — one full sweep reached the proposal
stage on three public repositories and the proposer declined each inside
its 7,000-character context; no PR yet.

Two capabilities the cloud sandbox could not build, authorized by the
operator in his own words (journaled `operator:authorization`):

- **computer.act** (`computer_do`): unattended hands — open, focus, type,
  press — with committing/destructive controls refused back to the
  hash-bound approval, never skipped; the live label re-read before every
  press; shells never opened; HALT between steps. Verified live on
  Notepad (four steps, exact text verified) and a `Send` plan refused.
- **task.script** (`do_task`): the planner compiles an ask no kind
  matched into a sandboxed program instead of only a gap; the sandbox is
  unchanged. Verified live: "rename every .md file ... uppercase"
  compiled to file_list + do_task and ran under a mission.

### Second build, same day (2026-09-02, "you keep building")

- **code.autonomous can now act, and says why when it does not.** Six
  files / 48 KB of context with a per-call reasoner ceiling; the prompt on
  stdin (Windows' 32 K command-line cap killed the first big context);
  the model chooses which files to read from a manifest; a grant slot is
  spent only when a PR is actually opened; machine-made issues (bots,
  fleet alerts, watchdogs, tracking issues) are skipped; declines are
  recorded and not re-asked; a CI repair gets the failing job's log,
  anchored on the error. Four live sweeps: every decline was a correct
  diagnosis (a watchdog doing its job; a CLI weekly-limit outage). Still
  EXPERIMENTAL until a PR exists for the operator to read.
- **email.read_body** built and promoted: one unread message's text by
  sender or subject, exactly one match or a question back, mailbox
  readonly, body never journaled. Live: a real body read, still unseen.
- **Desktop hands** gained `hotkey` (safe table only: clipboard, undo,
  find, save, navigation, escape, tab; never Enter/Delete/Alt+F4) and
  `select` (committing guard on the value). Hotkeys verified live in
  Notepad; select hermetically only, and the registry says so.

### Third build, same day (2026-09-02, "if it's not Jarvis yet, you're not done")

The measure was a battery: sixteen arbitrary asks — "what's going on",
"remind me tomorrow at 9am", "open Notepad and write a haiku", "text
Brant", "turn off the lights", "book a table" — compiled through the
planner on the operator's PC, then the hands plan that had failed twice
the day before rerun until it passed. What the battery found, all fixed:

- **A successful plan crashed on the way out.** Fifteen of sixteen
  planner calls returned a correct plan and died in
  `TemporaryDirectory` cleanup: Windows still held the CLI's empty
  working directory for a moment (`PermissionError`). The reasoner now
  discards its directory with bounded retries, never raises over it,
  and sweeps what an earlier call had to leave behind.
- **"Tomorrow at 9am" was the wrong day and the wrong hour.** The
  planner was told only the UTC instant; at 20:00 in Chicago it was
  already the 3rd in UTC, and it answered `2026-09-04T09:00:00Z`.
  `aletheia/localtime.py` is the operator's clock (memory
  `identity.timezone` → `ALETHEIA_TZ` → the America/Chicago the repo
  already assumed); the planner is told his local time and the rule, and
  the same ask now compiles to `2026-09-03T09:00:00-05:00`. The
  hard-coded zone in the intercom and voice paths is gone.
- **"Text Brant" named the wrong gap and offered a fake attempt.** No
  `message.send` existed, so the model reached for `intercom.relay` and
  the unmatched-ask rule compiled a sandboxed program — which has no
  network and could text nobody. `message.send` is registered NOT_BUILT
  with its ticket (Phone Link through the hands, Send refused to the
  approval); the plan now says exactly that and offers no program.
- **"Unavailable" hid its reason.** Eight calls in the parallel battery
  were refused by the CLI and the gateway reported only that both paths
  were unavailable. Both causes now travel with the refusal.
- **Research asked twice in a day lost its second report**
  (`FileExistsError`, journaled as an alert). The second report takes
  the time of day in its id.
- **The hands could not find a dialog that was on screen.** Windows 11
  titles it "Save as" and the plan said "Save As"; worse, under UI
  Automation an app's dialog is a child of its owner, not a top-level
  window, and `Desktop.window()` searches only the top level. Titles
  now match case-insensitively (lookup only — the committing guard
  still reads the live label), the direct Window children of every
  top-level window are searched, and a found window is anchored by
  handle for the rest of the step so a retitle mid-step cannot lose it.
  `select "All files"` then failed because the control holds
  `"All files "` — trailing space; select now reads the control's real
  items and picks the one a person means, refusing two candidates and
  refusing a prefix that reaches a committing word the plan never said.
  The eight-step plan COMPLETED unattended (run hands-39a87325ab11).
  Pillow, which window screenshots need, was missing and is now part of
  finish-setup.
- **"Open Notepad and write a haiku" through the agenda** — the whole
  loop, said in words. The planner followed its own `computer_do` note
  and the note's examples were false on this PC: `title_re: "Notepad"`
  is anchored at the start by pywinauto and cannot find
  "Untitled - Notepad" (patterns now search the title, case-insensitive);
  `control_type: "Edit"` names a control Windows 11 Notepad calls a
  `Document` (when a selector names only a text-entry type, both are
  tried — a planner cannot see the screen); Notepad reopens its last
  tabs, so the note now says to send ctrl+n first; and the verifier
  refused a haiku that was on screen in full because Notepad reports
  line breaks as `\r` (compared with line endings normalized — every
  character a person wrote is still checked). Asked a third time with
  the first haiku's Notepad still open, Windows 11 Notepad opened a
  second window from the same process and "Notepad" named both: the
  active window is the one he means, then a window of a process the
  run started, and otherwise the ambiguity is refused, not guessed.
  Live: run hands-be17492072b9 wrote all three lines into a fresh tab;
  the rerun after these fixes is the evidence line in the registry.
- **A program was offered where setup was the answer.** "Turn off the
  lights" and "what's on my calendar tomorrow" compiled to a sandboxed
  program beside their gaps, because room.scene and calendar.read are
  NEEDS_CONFIGURATION and the unmatched-ask rule only excluded
  authority-shaped gaps. A sandbox with no network reaches neither a
  light nor a calendar; she has those verbs and they need his token or
  his consent. A program is now offered only for NOT_BUILT, for an id
  the registry has never heard of, and for a kind the model invented.
  The sequential 16-ask battery afterwards: 16/16 compiled, none
  degraded, every reminder in his offset, every gap named honestly.
- A sync test read the developer's uncommitted edits out of the live
  checkout (`stale_code_files` is right for the Core, wrong for the
  pull-path tests) and is scoped out there.

Registry revision 46. Not a new capability among them: the day's work
was the distance between "the capability exists" and "he says it and it
happens", which is the only distance that counts.

### The loop (2026-09-02, "i dont need 16 commands")

Shown a list of sixteen asks that worked, the operator named the actual
standard: *"i need to know i can ask this anything and it will do it or
route it to the right place ... find and apply to 10 jobs for me and it
gets it done ... or i give it a video and say edit this whatever it may
be."* Three of his real asks were put through the planner. All three came
back as a question with **zero steps**. Two causes, both now fixed.

**She was never told who he is.** The situational snapshot handed to the
planner contained her own bookkeeping — her tasks, her capability gaps,
nine unread notices, a broken Shorts pipeline — and nothing about the man
asking. Asked to find him a job it could not know his field, and had no
way to look. `situational.snapshot()` now carries an `operator` block:
his remembered identity and preferences, the NAMES she can resolve in
people/organizations (names only — a phone number is not needed to plan
and does not go in a prompt; `contacts.resolve` reads details at
execution behind its own gates), the documents she holds, and the files
in his workspace. The planner prompt says to look there before asking,
and to say what it checked when it must ask anyway (§98). Immediately
visible: "edit this video" went from "where is it?" to "I don't see a
captions file in the workspace (only sample.mp4, sample.sha256 and a
clips folder)" — it looked first.

**Nothing could look, then decide.** `agenda` compiles ONE plan from ONE
sentence and runs it straight through; `mission` is a budget and an
authorization, not a loop. So the shape every real task needs — look at
what is there → act → look at what happened → decide again — did not
exist anywhere, and "cut this video down" could only ever be a question
because there was no "and then". `aletheia/pursue.py` is that loop, and
it inherits every gate rather than re-deriving one (money, forbidden
kinds, per-step `intercom.execute_command`, HALT before each round and
each step, the mission budget). Its bounds are the design: 6 rounds, 6
steps a round, 24 a goal, a stop on a verbatim-repeated command, and a
stop after two consecutive barren rounds — one is survivable on purpose,
because a failure is information the next round should use (§31).

Live, on a goal that cannot be done without looking: round 1 probed
sample.mp4 (6.0s) and its blind trim failed; round 2 used what round 1
learned — "half of 6.0s" — and wrote a 3.000000s file with the source
hash unchanged. `goal.pursue` is registered EXPERIMENTAL on that
evidence: one goal shape has round-tripped, which is not yet a sample.
Registry revision 47.

**What this does not yet make true.** "Find and apply to 10 jobs" still
ends at a named gap, correctly: submitting an application is a binding
statement about his own work history, `errand.run` is EXPERIMENTAL, and
Submit is operator_always by design. The loop can find postings, tailor a
resume and fill the forms; the last click stays his. And the operator
block is only as useful as what is in memory, which today holds five
facts copied from the playbook in August — the next unlock is his own,
and it costs a conversation rather than a credential.

### Security review, verified and acted on (2026-09-03)

The operator brought a SWOT/security review written by ChatGPT and said to
act on what was good in it rather than take it at face value. Every claim
below was checked against the code before anything changed; four were real
and are fixed, and the rest are recorded honestly with what is verified
and what it would cost.

**Fixed, each with a regression test that fails on the old code:**

1. **Browser interaction was a confused deputy.** `browse.interact` checked
   only that its approval was APPROVED — never that it was issued for THIS
   url and THESE steps. Any approved id authorized any browser action, so
   an approval to click "Next" on one site could be handed to a plan that
   pressed "Place order" on another. The errand layer did its own hash
   check and was safe; nothing else was, and "every caller remembers" is
   what a confused-deputy bug is made of. The binding now lives in the
   primitive (§61, §70).
2. **A spending errand could overspend its ceiling.** The ceiling was
   compared with the page BEFORE the steps ran; then the whole sequence,
   irreversible click included, ran with no re-read. A $40 cart that
   becomes $75 at checkout passed. The docstring claimed the ceiling was
   "checked twice" — the second check was a §143 boundary check on the
   after-text, not a money check. Spending errands are refused at run time
   until the two-phase checkout verifier exists. No spending errand had
   ever run live, so nothing was lost.
3. **The room microphone was an authentication device.** Voice already
   refused to widen standing authority — a television or a guest could say
   it — and then accepted "approve" for whatever was pending, with no risk
   check at all. If that was an email send or a live errand, the room
   approved it. Voice now refuses high-risk and operator_always approvals
   and fails closed on an approval whose risk it cannot read. It keeps
   HALT, which is the one thing a room should always be able to say.
4. **Training capture defaulted to ON** with a 512 MB budget, keeping
   prompts, context and responses. Its redaction is CREDENTIAL redaction,
   which is not privacy redaction: the store would accumulate his
   relationships, finances, health and calendar — precisely the corpus
   worth stealing from a personal machine. Default is now OFF.

**Verified, real, and NOT yet fixed** — each needs either his decision or
a build larger than one session, and none should be forgotten:

- **The control plane is a public repository.** `caleblschulte0-ux/Aletheia`
  is PUBLIC and the journal, approvals, receipts and operator quotes sync
  through it. Confirmed. Private operational state belongs on a private
  transport; code can stay public. This is the largest architectural item.
- **`main` is unprotected and the Core auto-updates from it.** Branch
  protection is off, the latest commit is unsigned, and `core_tick`
  restarts onto whatever code appears. Anything with GitHub write access
  therefore has code execution on his PC. Protection is his setting to
  make; a signed promotion channel is the code half.
- **Loopback is treated as authenticated.** The Core accepts unauthenticated
  requests on 127.0.0.1, and `/api/command` can approve and resume. Any
  process running as him inherits that. Localhost proves origin, not
  authorization.
- **Secrets live in ordinary JSON.** `~/.aletheia/mail.json` holds an app
  password. `secret_store` (DPAPI) exists and is EXPERIMENTAL; the mail
  path does not use it.
- **`open_app` can launch interpreters through the approval path.** Work
  Sessions block shells; the underlying hash-bound `computer.execute` does
  not, so an approved plan can start one. Code execution should be its own
  capability, not an argument to app-launching.
- **Information-flow labels do not exist.** Nothing marks a bank balance
  or a private message as SENSITIVE, so nothing structurally prevents such
  a value reaching an outbound channel. This is the review's best idea and
  the correct answer to "I don't want it blackmailing me": make it
  impossible by construction rather than by asking a model to behave.

Registry revision 48.

## Doing things on websites (2026-09-04) — `web.task`, EXPERIMENTAL

His ruling, and it reframed the whole thing: *"this applying to jobs
thing is an example — it's an example of something where you need to
access a document on my computer, do multiple steps on a browser, shit
like that."* Hand-built verticals were the defect. `apply_run` drives a
job application and nothing else, and the next request needing six
clicks would have wanted another module and another week.

`aletheia/webtask.py` is the general thing underneath: look at the page,
do one step, look again, bounded — his profile and his files available,
and three refusals that make it safe to point at a live site (a typed
value must come from his profile or his own sentence, checked in code;
the first committing button ends the run and becomes ONE approval; money
stops it with no approval offered at all).

What made it real was pointing it at pages instead of reasoning about
them. Every one of these was a live failure first:

| what a real site does | what it did before |
|---|---|
| the form is three PAGES | the press re-opened the last one and typed page one's fields into it — two thirds of an application left on the server |
| the form is in an IFRAME | *"I don't see any form fields"*, standing on the page |
| "Apply" is a LINK that opens a NEW TAB | described the page she was still on |
| the controls are DIVS, no ids, no `<select>` | saw the box to type a city into and none of the four cities |
| a SIGN-IN wall | typed his email into the username box, then gave up |
| a CAPTCHA | burned the budget |

All six are handled and proved end to end against real Chromium
(`tests/test_webtask_real_pages.py`: careers page → new tab → iframe →
filled → approved → the server receives every field). The route is the
unit, not the page; the approval binds to where the route starts and
carries its digest, so a changed route cannot inherit an old yes; and
the press is consumed in the journal, so re-running the same goal cannot
silently apply twice.

And the loop closes: `runtime.press_approved_web_tasks` presses what he
approved on the next beat. Before that the capability ended in a
question nobody could answer — she stopped at the button, said "confirm
it and I will press it", and the only thing on earth that could press it
was a command line.

EXPERIMENTAL, honestly: every proof is against fixture servers on
loopback. It becomes AVAILABLE when a real employer's confirmation comes
back for something he asked for.

## Next five engineering milestones (priority order, per §137)

The five gaps between Aletheia and the thing she is supposed to be were
closed on 2026-08-27 (see the phase rows above and the journal). What is
left is not architecture — it is the handful of credentials and live
round-trips that only the operator can supply. Each one flips a registry
entry on real evidence, not on more code.

1. **Give her the room** (`room.scene`, NEEDS_CONFIGURATION): create a
   long-lived token in Home Assistant, set `ALETHEIA_HASS_URL` and
   `ALETHEIA_HASS_TOKEN` on the PC, then `python -m aletheia.hass observe`
   and one approved scene. The adapter and its gates are built and tested.
2. **Give her the phone** (`access.remote`, NEEDS_CONFIGURATION):
   `tailscale cert <name>` (which also gets you home without opening a
   port), then `python -m aletheia.access mint "iPhone"` and start the
   Core with `--host`/`--tls-cert`/`--tls-key`. Mint `read` first and live
   with it a while before minting `full`.
3. **The first live errand** (`errand.run`, `purchase.execute`,
   `reservation.book`, `subscription.cancel` — all EXPERIMENTAL): one real
   cancellation is the cheapest honest test, since it spends nothing and
   still proves the whole path. EXPERIMENTAL until one round-trips with a
   merchant's own confirmation; that evidence is what promotes them.
4. **Calendar providers** (`calendar.read` NEEDS_CONFIGURATION,
   `calendar.write` EXPERIMENTAL): the local models and the ICS mirror are
   built; a live Google/Outlook adapter is the remaining work, and it is
   the last thing standing between Phase 15's scheduling test and a real
   dentist appointment.
5. **Phase 12 — Phone V0** on the now-permanent Core: the audio router is
   EXPERIMENTAL against a hermetic backend and has never touched a real
   Windows device. `scripts/phase11_accept_audio.ps1` on the PC decides
   AVAILABLE or repair.
6. **Pair the iPhone with Phone Link** (`message.send`, NOT_BUILT — added
   2026-09-02 when "text Brant" had nothing honest to name): Phone Link
   is installed and running on the PC but sits at its onboarding screen
   with no phone paired. Pairing is a QR scan and a Bluetooth handshake —
   physical, his. With a paired phone the adapter is composable from
   what exists (contacts.resolve, computer.act to compose, the Send
   control refused to a hash-bound approval, the thread read back as
   verification), and "Text him back" becomes a build, not a boundary.

## Non-goals, on the record

- No model API keys as a requirement (§6); no cookie theft, no
  reverse-engineered endpoints — subscription clients or honest
  degradation.
- No authority bundled with ability (§70); no gate weakened to ship
  more, anywhere in the fleet.
- No Jarvis theater (§107): nothing renders as live that isn't.
- Spending, agreements, disclosures, destructive actions: always
  operator-confirmed (§56 L4) — no phase changes that.
