"""The intercom — ChatGPT is the operator's voice; this is what hears it.

The operator talks to ChatGPT (the app — voice mode, phone, unlimited,
no API keys). ChatGPT reads the fleet's truth straight from this repo and,
when the operator asks for an ACTION, relays it as one small JSON file in
`exchange/commands/`. `intercom.yml` fires on that push, validates the
command, executes it through the SAME gates the operator would use at a
keyboard, and writes a `<id>.result.json` receipt next to it. ChatGPT
reads the receipt and tells the operator what happened. Contract for the
ChatGPT side: `exchange/INTERCOM.md`.

What keeps this sane (the constitution holds):

- **ChatGPT still never writes code.** A command names a KIND and
  arguments — never a file path, never a script, never a diff. Unknown
  kinds and extra payload keys are refused.
- **The registry still gates the hands.** `dispatch` and `issue` run
  through `aletheia.act`, which checks `front_door` BEFORE any network
  call. A relayed command can do nothing a registry grant doesn't allow.
- **Every command must quote the operator** (`operator_quote`), every
  execution is journaled, and every receipt is committed. A hallucinated
  command is bounded by the allowlist (worst case today: a pulse re-run,
  an issue, a note, a plan edit, a re-rulable ruling, or a read-only page
  visit / screenshot on the PC) and leaves a paper trail the operator
  sees in the next brief.
- **Results are idempotent**: a command with a receipt is never run twice.
- **Two runners, one directory, zero races**: LOCAL_KINDS (below) need
  the operator's PC and are executed only by the local Core's sync loop;
  everything else is executed only by the Actions runner. The partition
  is static, so no command ever has two possible executors. Browser
  INTERACTION is not a kind at all — it needs an approval bound to exact
  steps (`aletheia.browse.interact`), which a relayed voice command
  cannot carry.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from aletheia import act, gh, journal, localtime, plans, policy, speech, suggestions, tasks
from aletheia.fleet import REPO_ROOT, load_fleet

COMMANDS_DIR = REPO_ROOT / "exchange" / "commands"
MAX_BYTES = 8_192
ACTOR = "operator-via-intercom"

REQUIRED_KEYS = {"id", "filed", "by", "relayed_from", "operator_quote", "command"}

# kind -> exactly these argument keys (a set means required; OPTIONAL maps allow omission)
KIND_ARGS: dict[str, tuple[set[str], set[str]]] = {
    "note":          ({"text"}, set()),
    "dispatch":      ({"repo", "workflow"}, {"ref"}),
    "issue":         ({"repo", "title"}, {"body"}),
    "rule":          ({"id", "state", "because"}, set()),
    "plan_new":      ({"slug", "title", "goal"}, set()),
    "plan_add_step": ({"slug", "text"}, {"repo"}),
    "plan_step":     ({"slug", "n", "state"}, set()),
    "plan_set":      ({"slug", "state"}, {"because"}),
    # His projects, by saying so (aletheia.charters). QUEUED, not done: a
    # new one is drafted by the project loop and waits for his "yes" on the
    # brief; a step or a drop is applied there too, within half an hour.
    "project_new":   ({"idea"}, set()),
    "project_step":  ({"project", "text"}, set()),
    "project_drop":  ({"project"}, set()),
    # His LONG missions, by saying so (aletheia.programs): an objective that
    # runs for weeks, drafted by a model into outcomes, workstreams and tasks,
    # and inert until his own "confirm". `mission_activity` is what a recurring
    # activity's schedule fires; nothing he says means it.
    "mission_new":      ({"objective"}, set()),
    "mission_add":      ({"text"}, {"mission"}),
    "mission_confirm":  (set(), {"mission"}),
    "missions":         (set(), {"which", "about"}),
    "mission_activity": ({"mission", "activity"}, set()),
    # "Work on my projects." (aletheia.project_work): a bounded work session over
    # every queue - what can run now runs, what cannot is investigated or waits
    # with its reason. `work_report` is how he asks what came of it.
    "work_projects":    (set(), {"minutes"}),
    "work_report":      (set(), {"about"}),
    # "Study these and improve my project." (aletheia.studies): research ->
    # comparison -> evidence-backed changes he decides on -> execution through
    # the existing safe paths -> measurement. `study_decide` and
    # `study_confirm` are HIS words only (PLANNER_FORBIDDEN).
    "study_new":        ({"words"}, {"project", "path"}),
    "studies":          (set(), {"which", "about"}),
    "study_decide":     ({"choice"}, {"which", "study", "words"}),
    "study_confirm":    (set(), {"study"}),
    "task_new":      ({"id", "description"}, {"goal", "worker", "deadline"}),
    "task_status":   ({"id", "state"}, {"note"}),
    # She could CREATE a task by voice and change its status, and had no
    # verb for "what are my tasks" — so the commonest question about the
    # store went to the planner every time: 8.5 seconds, and markdown
    # bullets read out loud.
    "tasks":         (set(), {"which"}),
    # "mark the passport one done" — by what he CALLS it, because he does
    # not know its id and should never have to.
    "task_done":     ({"which"}, set()),
    # "Move the plumber to Friday", "delete call the plumber", "rename the
    # plumber one to call Joe": one task found by his words, changed once.
    # Exactly one of the three.
    "task_change":   ({"which"}, {"deadline", "description", "drop"}),
    "halt":          (set(), {"reason"}),
    # 2026-09-23: "Restart her", one tap, on the page that says her
    # heartbeat is old. Exits the way a code update does and the
    # supervisor brings her back; unsupervised, she hands off to one.
    "restart":       (set(), {"reason"}),
    # 2026-09-23: "Try the update now" on the health line that says she is
    # behind. One beat of her own sync loop, and what happened in words.
    "update_now":    (set(), {"reason"}),
    "resume":        (set(), set()),
    # The WINDOW BUTTON, which is not the kill switch. `halt` keeps her
    # running and refusing to act; this stops the Core, the room
    # microphone and the project loop, and the watchdog leaves her shut.
    # Voice could reach `halt` and had no way at all to reach this one.
    "close":         (set(), {"reason"}),
    "open":          (set(), set()),
    # "Is any of this on?" was a question he could only answer by reading
    # a process list and Task Scheduler side by side.
    "running":       (set(), set()),
    "approve":       ({"id"}, set()),
    "deny":          ({"id"}, {"because"}),
    "remember":      ({"domain", "key", "value"}, {"memory_kind"}),
    # 2026-09-23: what the job hunt steers by, in his words, and read back.
    "preference_set": ({"field", "value"}, set()),
    "preferences":   (set(), set()),
    # UNWIRED SINCE THE DAY IT WAS WRITTEN. `memory.forget` is a real
    # function in `aletheia.memory` with no kind, no registry entry and no
    # phrasing, so "forget my landlord" reached the planner — which
    # INVENTED the identifier `memory.forget`, filed a build task for a
    # thing that already exists, and read the id out loud. Rule zero:
    # never build a capability and leave it unwired.
    "forget":        ({"about"}, {"domain"}),
    "browse_read":   ({"url"}, set()),
    "research":      ({"question"}, set()),
    # she can produce something now, not just say things
    "file_write":    ({"path", "text"}, {"why"}),
    # Writing something that has to be WRITTEN, not pasted. See below.
    "compose":       ({"path", "what"}, {"sources", "why"}),
    "file_edit":     ({"path", "find", "replace"}, {"why"}),
    "file_read":     ({"path"}, {"anywhere"}),
    "file_list":     (set(), {"subdir"}),
    # Finding a file of HIS, anywhere he keeps things. `file_list` lists
    # the one directory she owns and `file_read` needs a path he does not
    # have; between them there was no way to answer "what's in my
    # downloads" or "find that lease PDF" at all.
    "file_find":     (set(), {"query", "place", "since"}),
    # How much is in one of his folders. Asked out loud she compiled a
    # two-step File Explorer plan and asked for approval to run it, while
    # holding every one of those numbers already.
    "file_size":     ({"place"}, set()),
    # Ordinary file operations she did not have a verb for. Both keep a
    # version first, so both are reversible with `workspace restore`.
    "file_delete":   ({"path"}, {"why"}),
    "file_move":     ({"path", "to"}, {"why"}),
    # "How many jobs are open at Anthropic" / "find me react jobs in
    # Austin" — LOOKING, with nothing prepared and nothing sent. The
    # planner had no verb for this, so it reached for `research`, which
    # drives a browser at the open web: 94 seconds to fail at a question
    # `jobs.search` answers from the boards' own APIs in three.
    "jobs":          (set(), {"role", "where", "count", "company"}),
    # Everything up to the submit, which stays his. See aletheia.applications.
    "apply_prepare": ({"role"}, {"count", "where", "resume"}),
    # What she has actually applied to. `apply_run` has recorded every
    # staged and submitted application since it was written, and asking
    # about them out loud got "I don't have a record of jobs you've
    # applied to — no application tracker" — false the moment there is
    # one, and unfalsifiable to him.
    "applications":  (set(), set()),
    # "What's my mum's number", "what are you watching for". Both stores
    # had a writer, a reader in their own module, and no way for him to
    # ASK — `contact_add` and `watch_email_from` are the writers.
    "contacts":      (set(), {"which", "asked"}),
    "watches":       (set(), set()),
    # "What drafts do I have" and "delete the draft" (2026-10-07): the held
    # drafts read, and one put away unsent.
    "drafts":        (set(), set()),
    "draft_discard": (set(), {"which"}),
    # "apply to ten jobs with this resume" — the whole thing, one call.
    "apply_campaign": (set(), {"role", "count", "where", "resume"}),
    "apply_pause":   (set(), {"reason"}),
    # His answer to one question the staged applications wait on.
    "apply_answer": ({"question", "answer"}, set()),
    # What an employer DID about one he sent. His words, 2026-09-11: "it
    # should track the application as well not just apply".
    "apply_outcome": ({"which", "outcome"}, {"note"}),
    # 2026-09-23: "Try it again" on the notice that says a send failed.
    "apply_retry":   ({"which"}, set()),
    # The catch-all for "go do this on a website" — any number of steps.
    "web_task":      ({"goal"}, {"url", "budget"}),
    # "try that again" after a site refused one — the ONLY case where
    # running it again is safe, because a refusal means nothing was taken.
    "web_task_retry": (set(), {"run_id"}),
    # "here are the answers, carry on" — she picks the run back up rather
    # than starting the form again and asking the same questions.
    "web_task_answer": (set(), {"run_id", "answers"}),
    # "cancel my gym membership" — she goes to the page it is managed on,
    # gets as far as the button, and waits for him like anything else.
    "subscription_cancel": ({"subscription"}, {"url"}),
    # eyes on the desktop, never hands: mutation keeps its own approval
    "computer_observe": (set(), {"window"}),
    # video and audio: the source is never touched, output lands in the workspace
    "media_probe":   ({"source"}, set()),
    "media_trim":    ({"source", "out"}, {"start", "end", "duration"}),
    "media_join":    ({"sources", "out"}, set()),
    "media_audio":   ({"source", "out"}, set()),
    "media_captions": ({"source", "subtitles", "out"}, set()),
    "media_convert": ({"source", "out"}, {"height"}),
    "browse_shot":   ({"url"}, set()),
    # Photographing the DESKTOP, where browse_shot photographs a web
    # page. "active" is the monitor holding the focused window: this
    # PC runs three screens as one 5760x1080 desktop, so capturing
    # all of it and fitting the long edge into 1024 gave a 1024x192
    # smear. "What is on my screen" means the one he is looking at.
    "screenshot":    (set(), {"monitor"}),
    # Recording ONE window to a video file on the PC (2026-09-11). window is
    # its title or a unique part of it; the file is never uploaded.
    "screen_record": ({"window"}, {"name", "max_seconds"}),
    "screen_record_stop": (set(), set()),
    "recording":     (set(), set()),
    "email_check":   (set(), set()),
    # his recent texts on the Google Voice number, newest first; who narrows
    # to one sender. Reads a page, sends nothing (2026-10-07).
    "texts_read":    (set(), {"who"}),
    # the text of ONE unread message, named by sender or subject; exactly
    # one match or a question back, never a guess (2026-09-02)
    "email_read":    ({"which"}, set()),
    "email_draft":   ({"to", "body"}, {"subject"}),
    # The most-asked-for thing she could not do — thirteen times in the
    # demand ledger, in his own words. Same shape as email_draft: it
    # writes a draft and an approval and sends nothing.
    "message_send":  ({"to", "body"}, set()),
    # A CONVERSATION, not a one-off message (continuity brief IV.15,
    # aletheia.conversations): the thread keeps the recipient, what was asked,
    # the reply and the follow-up date, so "did they reply" has an answer.
    # Drafting sends nothing; the send waits for his yes (or a grant he gave).
    "thread_draft":  ({"to"}, {"about", "body", "subject"}),
    "thread_status": (set(), {"which"}),
    "thread_send":   ({"thread"}, set()),
    "thread_followup": ({"thread"}, set()),
    # His calendar as agency (IV.16, aletheia.calendar_reasoning).
    "calendar_find_free": ({"when"}, {"minutes", "location", "purpose", "part"}),
    "calendar_hold": ({"title", "start"}, {"end", "minutes", "location", "thread", "replaces", "was_title"}),
    "hold_release":  ({"title", "start"}, set()),
    "calendar_propose": ({"thread"}, {"when", "minutes", "location"}),
    # Word and Excel. The suffix picks the format; `content` is blocks
    # for a .docx and rows for a .xlsx.
    "doc_make":      ({"path", "content"}, {"sheet_name", "why"}),
    # The agent runtime, said out loud. `agent_new` is the only one that
    # adds capacity, so it is the only one that is world-tier.
    # The room microphone. `mic_on` is a BUTTON, never a sentence.
    # His ChatGPT subscription as a second worker. Granting ADDS
    # capacity, so it is world-tier by falling through; stopping only
    # ever reduces, so it is routine and never waits.
    # Transport for whatever is playing. LOCAL: it presses keys on
    # his own machine.
    "music":         ({"action"}, {"level"}),
    "chatgpt":       (set(), set()),
    "chatgpt_on":    (set(), {"hours"}),
    "chatgpt_off":   (set(), set()),
    "mic":           (set(), set()),
    "mic_on":        (set(), set()),
    "mic_off":       (set(), set()),
    # "Handled": a red project he has dealt with stops being shouted until
    # the next reading shows a DIFFERENT fault. His tap; a model that could
    # mark faults handled is a model that can hide them.
    "fault_ack":     ({"repo"}, set()),
    # "Clear": a browser mission stopped on him is left, on his tap. Never a
    # model's - a model that can clear walls can clear his questions too.
    "mission_leave": ({"which"}, set()),
    # "Open it": the page a browser mission stopped on (a CAPTCHA, a sign-in,
    # a question only he can answer), opened in HIS browser on his PC so he
    # can do his part. `which` is the mission or the application, never a
    # free address - nothing a model says can open a page on his screen.
    "open_page":     ({"which"}, set()),
    # Looking at the actual PICTURE of his screen, rather than reading it
    # as text. A screenshot cannot be redacted the way perception.screen
    # redacts a window title, so it gets the microphone's treatment: off
    # by default, his to switch on, dead on restart.
    "eyes":          (set(), set()),
    "eyes_on":       (set(), {"hours"}),
    "eyes_off":      (set(), set()),
    "agents":        (set(), set()),
    "agent_new":     ({"name", "mission"}, {"project", "agent_type"}),
    "agent_stop":    ({"which"}, set()),
    "agents_pause":  (set(), set()),
    # personal-OS verbs (2026-08-26): PC-private state, so all LOCAL_KINDS
    # `replaces` is the text of the reminder this one moves ("make that 4").
    "remind_at":       ({"at", "text"}, {"replaces"}),
    "remind_daily":    ({"time", "text"}, {"tz", "every", "replaces"}),
    "remind_monthly":  ({"day", "time", "text"}, {"tz"}),
    # "Every hour", "every 30 minutes": within the day, from now.
    "remind_every":    ({"minutes", "text"}, {"replaces"}),
    # "every Monday at 8, take the bins out". `scheduler` has had a
    # `weekly` kind since it was written and the GRAMMAR could not say it,
    # so "remind me every monday to take out the trash" compiled to a
    # generic `do_task` under a summary that promised a weekly reminder.
    # A capability nothing can ask for is not a capability.
    "remind_weekly":   ({"days", "time", "text"}, {"tz", "every", "replaces"}),
    # "What reminders do I have" / "stop reminding me about the bins".
    # `scheduler` has listed and disabled schedules since it was written;
    # asking for either OUT LOUD compiled a gap called `reminder.cancel`
    # and an executable step in the same breath, so she said "1 step ready
    # — Cancel a reminder. Say approve to run it. I can't reminder.cancel
    # yet."
    "reminders":       (set(), {"which"}),
    # "Snooze that for an hour." The notice is put away and comes BACK —
    # a notification he has read and cannot act on yet is the commonest
    # thing in the room, and "I can't do that yet" was the answer.
    "notify_snooze":   ({"minutes"}, {"which", "quiet"}),
    "reminder_off":    ({"which"}, {"once"}),
    "reminder_on":     ({"which"}, set()),
    "watch_email_from": ({"who"}, set()),
    "notify_operator": ({"text"}, {"priority"}),
    "notify_check":    (set(), set()),
    "notify_clear":    (set(), set()),
    # His "undo that": `which` is optional words naming the act; nothing means the newest.
    "undo":            (set(), {"which"}),
    # His interview window ("set my interview window to 2 to 4"): his words
    # only, never a compiler's guess at his hours. `interview_status` reads it.
    "interview_window_set": ({"start", "end"}, {"timezone"}),
    "interview_status":     (set(), set()),
    # Instagram (his words, 2026-09-24: "automatically post stuff to Instagram").
    # A post reaches the world, so it is world-tier and an approval of his.
    # `media` is a public https address OR a file on his PC. It was
    # `image_url`, which stopped being honest the moment video and local
    # files worked; the caption and a forced media_type are optional.
    "instagram_post":  ({"media"}, {"caption", "media_type"}),
    "instagram_posts": (set(), set()),
    "announce_set":    ({"on"}, {"quiet_from", "quiet_until"}),
    # `part` is morning/afternoon/evening. He says it constantly and it
    # used to be dropped in silence — see `_free_sentence`.
    "free_time":       ({"day"}, {"tz", "minutes", "part", "at"}),
    # Either an email or a phone, and at least one of them - a contact she
    # cannot reach is not a contact. `email` stopped being required when
    # texting needed a number: `contacts.create` had supported phones all
    # along, and the grammar was the only thing that did not.
    "contact_add":     ({"name"}, {"email", "phone", "alias"}),
    "contact_remove":  ({"name"}, set()),
    # The slot for everything that is not a slot (2026-08-27). `text` is
    # whatever the operator actually said; aletheia.planner compiles it
    # into steps expressed in the kinds ABOVE, and every one of those is
    # validated here like any other command. This kind widens what can be
    # SAID, never what may be DONE.
    "intent":          ({"text"}, set()),
    # Reading the screen (Phase §86). LOCAL: the accessibility tree only
    # exists on the PC, and the observation is redacted before it travels.
    "screen_ask":      ({"question"}, {"window"}),
    # ---- verbs she already had and you could not ask for -----------------
    # 72 capabilities were AVAILABLE and 29 were reachable by voice. Every
    # kind below fronts a capability that was already built, tested and
    # registered, with a real CLI caller — and was unreachable from the one
    # channel he actually uses. Adding a kind here widens the PLANNER too:
    # its prompt is generated from KIND_ARGS, so an arbitrary sentence can
    # now be compiled into any of these as well (§152 — composition).
    "meet":            ({"person"}, {"from_day", "to_day", "minutes", "purpose"}),
    "recall":          ({"about"}, {"domain"}),
    "brief":           (set(), set()),
    "handle":          ({"text"}, set()),
    "travel_time":     ({"place"}, set()),
    "place_add":       ({"name", "address"}, set()),
    "shopping_add":    ({"item"}, {"budget", "replaces", "moved_from"}),
    # Reading the list back, and taking something off it. `shopping_add`
    # shipped without either, so she confirmed "Added to the shopping
    # list: milk" and then said she had no shopping list.
    "shopping_list":   (set(), set()),
    "shopping_off":    ({"item"}, set()),
    # HIS OWN NAMED LISTS - packing, gift ideas, movies to watch. The
    # shopping list stays its own store (buying is its own path).
    "list_new":        ({"list"}, set()),
    # `moved_from` is the list it comes off ("move chicken to the shopping
    # list"): "shopping" or one of his named lists.
    "list_add":        ({"list", "item"}, {"moved_from"}),
    "list_read":       (set(), {"list"}),
    "list_off":        ({"list", "item"}, set()),
    # HIS STOPWATCH - counts up until he says stop (a timer counts down).
    "stopwatch":       ({"action"}, set()),
    "stopwatch_read":  (set(), set()),
    # HOW FAST SHE TALKS - his word, read by both of her voices.
    "speaking_pace":      ({"action"}, set()),
    "speaking_pace_read": (set(), set()),
    "subscriptions":   (set(), set()),
    # `about` says which half of the same store he asked about — balance
    # or spending — so the empty-store answer does not report a balance to
    # a man who asked what he spent.
    "money":           (set(), {"about"}),
    "car":             (set(), {"vehicle"}),
    "projects":        (set(), set()),
    # Reading what she may do without asking. Deliberately read-only: see
    # aletheia/standing.py — GRANTING authority is not something she takes
    # from an unauthenticated room microphone.
    "authority_status": (set(), set()),
    # "what do you still need from me?" — read-only; it checks, it configures
    # nothing. Every credential remains the operator's to create.
    "setup_status":     (set(), {"about"}),
    # ---- 2026-09-02, both operator-authorized in his own words -----------
    # Desktop HANDS, not just eyes: a typed step list run through
    # aletheia.computer.act. Any control whose label commits or destroys
    # (Send, Delete, Pay, Purchase, Confirm, Submit, Format, Uninstall,
    # Empty Trash ...) is refused there and bounced to the hash-bound
    # approval in computer.execute — refused, never skipped.
    "computer_do":      ({"steps"}, {"why"}),
    # The slot for a request no kind fits: she writes a small program and
    # runs it in the sandbox (aletheia.script — import whitelist, no
    # network, no subprocess, fresh environment, source saved first).
    "do_task":          ({"request"}, {"label"}),
}

# Argument shapes the bare grammar cannot say. The planner's prompt is
# generated from KIND_ARGS and these together, so the model learns the
# shape of a step list from the registry rather than from a guess.
KIND_NOTES: dict[str, str] = {
    "instagram_post": (
        'Publish ONE picture or reel with a caption to his Instagram account: media is either a '
        'public https address or a path to a file on his PC (a JPEG or PNG picture, an MP4 video), '
        'caption the words under it (2200 characters at most, line breaks and hashtags kept), '
        'media_type optional and only to force IMAGE or REELS. It reaches the world, so it always '
        'waits for his approval; refused in words when Instagram is not set up yet (the setup is '
        'his: professional account, Meta developer app, one connect command).'),
    "instagram_posts": (
        'What she has posted to Instagram, newest first, from her own ledger - "what have you '
        'posted to Instagram", "did the post go out".'),
    "interview_window_set": (
        'His interview hours: start and end as "HH:MM" on his clock (timezone optional). Never '
        'compiled by a planner - only his own sentence sets it.'),
    "interview_status": (
        'Whether she books interviews on her own and in what hours - "what\'s my interview '
        'window", "are you booking interviews".'),
    "undo": (
        'His "undo that" / "take that back": reverse the newest thing she did on her own '
        '(a task she added, a note, a file version, a branch). Only her own reversible acts; '
        'his decisions and anything that reached the world are refused by name. Never compiled '
        'by a planner - it is forbidden there; only his words reach it.'),
    "preference_set": (
        'Change one thing the job hunt steers by, in his words: field is one of '
        'work_wanted, work_not_wanted, desired_pay, notice_period, willing_to_relocate; '
        'value is what he said. The two lists accumulate; the single facts are replaced. '
        'His own words about himself, never a plan\'s guess.'),
    "preferences": ('What the job hunt steers by right now, read back in his words.'),
    "mission_new": (
        "Start a LONG mission from his words - something that takes weeks or months and "
        "spans several parts of his life (\"help me change X over the next six months\"). "
        "objective is his sentence. She drafts outcomes, workstreams and questions for him; "
        "nothing runs until he confirms."),
    "mission_add": (
        "Something he adds to his long mission: an answer to its questions, a choice for "
        "one of its decisions, or a change. text is his words; mission names which one "
        "when he has several."),
    "mission_confirm": (
        "His yes to a drafted long mission (or a drafted change to one). Only when he "
        "plainly says to start or confirm it."),
    "missions": (
        "How his long missions are going: outcomes, what is running, what is waiting "
        "and why, and the decisions that are his. about=waiting lists only what is "
        "waiting and what wakes it; about=steps shows each unfinished task's steps, for "
        "fixing one that will not move; which names one mission."),
    "mission_activity": (
        "Fired by a long mission's recurring schedule to start this occurrence of its "
        "activity. Never compiled from something he says."),
    "work_projects": (
        "He asks her to work on his projects now (\"work on my projects\", \"keep working on my "
        "stuff\", \"what can you get done right now\"). She runs a bounded work session: whatever "
        "can run now within her authority runs, harder work is investigated and queued for a "
        "stronger model, and what waits says why. minutes bounds it (default 25)."),
    "work_report": (
        "What her work session did: finished, investigated, handed to him, what waits and on "
        "whom. Read only."),
    "study_new": (
        "He asks her to study things that do better than a project of his and improve it (\"study "
        "X, Y and Z and improve my <project>\"). words is his whole sentence; project names the "
        "project when the sentence does not; path is its folder when he gives one. She reads them "
        "and his project the same way, measures the differences and proposes changes he decides on."),
    "studies": (
        "How a study is going, what it found and what it proposes to change (\"how's the study "
        "going\", \"what did you find\", \"what should we change\"). about is found, change or "
        "empty. Read only."),
    "study_decide": (
        "HIS decision on a study's proposal or measured change: choice is accept, reject, reshape, "
        "keep, revert or iterate; which names it (\"the first one\", \"2\"); words are his reshape "
        "words. Never compiled by the planner."),
    "study_confirm": (
        "His yes to comparables she found by searching, before she reads them. Never compiled by "
        "the planner."),
    "screen_record": (
        "Start recording ONE window to an MP4 on this PC - never the whole desktop, never "
        "uploaded. window is its title or a unique part of it (computer_observe lists them); "
        "name is the file name; max_seconds caps it at 300. Bring the window up and "
        "full-screen it BEFORE starting: what is recorded is that window's rectangle."),
    "screen_record_stop": (
        "Stop the recording that is running; says where the file is and how long it is."),
    "recording": (
        "Whether a screen recording is running, of which window, and to which file."),
    "notify_snooze": (
        'Put a notification away and bring it BACK. minutes is how long; '
        'which is optional and defaults to the most recent unread one, '
        'because "snooze that" always means the thing that just spoke. '
        'quiet=true (do not disturb, "I\'m in a meeting") also keeps her '
        'from speaking up for those minutes.'),
    "contacts": (
        'Who he has saved, and how to reach them. which is optional and '
        'narrows by name or alias — use it for "what is my mum\'s '
        'number". asked is optional, "email" or "number": the one he asked '
        'for is said first, or said missing. `contact_add` is the writer.'),
    "contact_remove": (
        'Take someone out of his contacts. name is who he said; she finds the '
        'one contact that matches and asks if two do. Hidden, not deleted: '
        'adding them again brings them back.'),
    "watches": (
        'What she is waiting to tell him about — the watchers '
        '`watch_email_from` creates. Nothing to do with browsing.'),
    "drafts": (
        'The email drafts she is holding for him, unsent: who each is to and what about.'),
    "draft_discard": (
        'Put one held email draft away unsent: "delete the draft", "scrap the email to Dana". which is any '
        'words from its subject or who it is to; with none it is the newest. Kept and marked, never sent.'),
    "applications": (
        'What he has applied to through her — sent, and staged waiting on '
        'him. Use it for "what have I applied to"; `jobs` is the opposite '
        'direction, searching boards for new ones.'),
    "shopping_list": (
        'What is on his shopping list, read from the store. Use it for '
        '"what do I need from the shop" as well — it is the same list.'),
    "list_new": (
        'Start one of his own named lists - "make a list called packing". '
        'Not for shopping, tasks or reminders: those have their own verbs.'),
    "list_add": (
        'Put lines on one of his named lists, starting it if it is new - '
        '"add socks to my packing list". item may name several things.'),
    "list_read": (
        'Read one of his named lists, or with no list name say which lists '
        'he has.'),
    "stopwatch": (
        'His stopwatch: action is start, stop or reset. "Start a stopwatch", '
        '"stop the stopwatch". A countdown is a timer (remind_at), not this.'),
    "stopwatch_read": (
        'What his stopwatch says right now - "how long has the stopwatch been running".'),
    "speaking_pace": (
        'How fast she talks out loud: action is slower, faster or normal. '
        '"Talk slower", "speak faster", "talk normally".'),
    "speaking_pace_read": (
        'How fast she is talking now - "how fast are you talking".'),
    "list_off": (
        'Take a line off one of his named lists, or "everything" to clear '
        'it. Lines are marked done, not deleted.'),
    "shopping_off": (
        'Take something off the shopping list. item is the words he used; '
        'she finds the one entry that matches and asks him if two do. It '
        'is cancelled, not deleted.'),
    "reminders": (
        'What reminders are set, read straight from the schedule store. '
        'which is optional and narrows by the words of the reminder. Use '
        'this rather than answering from context: the store is the only '
        'thing that knows.'),
    "reminder_on": (
        'Put back a reminder he stopped. which is the words he used for '
        'it, or "all reminders" for every one stopped in the last day; a '
        'one-off whose time has gone by stays off and says so.'),
    "reminder_off": (
        'Stop a reminder he has set. which is the words he used for it '
        '("the bins", "the gym one"); she finds the one reminder that '
        'matches and asks him which if two do. It is DISABLED, not '
        'deleted, so it can be put back. once ("today", "tomorrow" or '
        '"next") skips just that one time of a repeating reminder.'),
    "remind_every": (
        'A reminder that repeats within the day - "every hour to drink '
        'water", "every 30 minutes". minutes is 15 to 720; the first one '
        'is that long from now.'),
    "remind_monthly": (
        'A reminder that repeats once a month - "on the 1st of every month '
        'to pay rent". day is the day of the month, 1-31 (a short month '
        'uses its last day), time is 24-hour HH:MM in his timezone.'),
    "remind_weekly": (
        'A reminder that repeats on named days — "every Monday", "every '
        'weekday at 7", "Tuesdays and Thursdays". days is a list of day '
        'names (or "weekdays"/"weekend"), time is 24-hour HH:MM in his '
        'timezone. Use THIS rather than remind_at when he says every, each '
        'or a plural day: a single-shot reminder under a summary promising '
        'a weekly one is a promise the step cannot keep. If he names no '
        'time, use 09:00 — the confirmation says it back to him.'),
    "subscription_cancel": (
        'Cancel a recurring charge she is tracking. subscription is its id '
        '(python -m aletheia.assistant subscriptions lists them), url is the '
        'page it is managed on and is REQUIRED the first time — she will not '
        'guess a cancellation URL, because guessing one is how you end up on '
        'a page wearing his bank\'s colours that somebody else owns. She '
        'drives to the button and waits for his confirmation like any other '
        'irreversible thing, and the subscription is only marked CANCELLED '
        'when the merchant itself says so.'),
    "web_task_answer": (
        'Use this when he ANSWERS something she asked while doing a web '
        'task — "the salary one, put 120000", "tell them I heard about it '
        'from a friend". answers is a mapping from the question she asked '
        '(any distinctive part of its label) to his answer, and run_id is '
        'optional: with none she takes the run that is waiting. She puts '
        'the page back the way she left it, types his answers, and carries '
        'on to the same button and the same one confirmation. Use it for '
        '"carry on" with no answers too, when she simply ran out of steps.'),
    "web_task_retry": (
        'Use this when he says "try that again" about something a website '
        'REFUSED — a form handed back with "phone must be 10 digits", a '
        'submission that bounced. She re-reads what the site said, fixes it, '
        'and brings him a NEW confirmation; it is never a way to press '
        'something twice, because a refusal means nothing was accepted. '
        'run_id is optional: with none she takes the most recent refusal.'),
    "web_task": (
        'THE CATCH-ALL for anything that means "go do this on a website" and '
        'has no kind of its own: fill in this form, renew this thing, '
        'download that statement, book the slot, update the address. goal is '
        'his request in his own words (they matter: a value she types must '
        'come from his profile or from his sentence, and anything else is '
        'refused in code, not discouraged in a prompt), url is where to '
        'start. She looks at the page, does one step, looks again, up to a '
        'budget. She attaches his own files when a form wants one. She stops '
        'at the first button that submits, sends, confirms or deletes and '
        'hands him ONE approval carrying that exact page, that exact button '
        'and everything typed to get there. Anything that spends money stops '
        'the run with no approval offered. Use this rather than inventing a '
        'gap when the request is a website he could do himself with a mouse.'),
    "apply_campaign": (
        'THE ONE TO USE for "apply to N jobs" / "apply to these jobs with my '
        'resume". It reads the resume he named (or finds it), learns his '
        'details from it, finds real openings, FOLLOWS EACH POSTING TO ITS '
        'APPLICATION FORM, fills every form, attaches the resume, and holds '
        'each one for his confirmation — asking the questions only he can '
        'answer ONCE across all of them rather than once per job. It submits '
        'nothing: each application waits as an ordinary approval he taps. '
        'role is OPTIONAL: omit it and she works out the jobs that fit from his '
        'resume. count at most 10, where an optional location, "remote" or '
        '"anywhere", resume a path (omit and she finds it). It runs in the '
        'background and tells him when the applications are ready. Prefer '
        'this over apply_prepare, which only writes a packet and does not '
        'touch the form.'),
    "fault_ack": (
        'Mark a red project handled - his tap on "Handled" beside a fault on '
        'the fleet. repo names the project as the page does. It stays quiet '
        'while the readings show the same fault and is said again the moment '
        'a different one appears. His own tap or words only, never a plan step.'),
    "mission_leave": (
        'Clear a browser mission that stopped on him - his tap on "Clear" on a '
        'card that says stopped at a CAPTCHA, a sign-in, a question. It is left, '
        'its application closed quietly, and never pressed again. which is the '
        'mission as the page names it. His own tap or words only, never a plan step.'),
    "open_page": (
        'Open, in his own browser on his PC, the page a browser mission stopped '
        'on - a CAPTCHA, a sign-in, a question only he can answer - so he can do '
        'his part; she carries on from where it stopped. which is the mission or '
        'the application as the page names it. His tap on "Open it", never a '
        'plan step, and never a free address.'),
    "update_now": (
        'Try to update her code now - his tap on "Try the update now" when the '
        'health line says she has been behind for a while. One beat of the sync '
        'loop; says whether it took. Only his own words or his own tap say it.'),
    "restart": (
        'Restart the Core - his tap on "Restart her" when the page says her '
        'heartbeat is old or newer code is on disk. Back in about a minute. '
        'Only his own words or his own tap say it.'),
    "apply_pause": (
        'His "stop applying for now": no new batch of applications starts '
        'until he says start applying again. Not the kill switch - everything '
        'else keeps going, and a batch already running finishes. reason is '
        'optional ("for today"). Only his own words say it.'),
    "apply_retry": (
        'Try a failed application again: it goes back to waiting with a fresh '
        'approval and the next beat sends it. which is the employer, the job or '
        'the record as she names it. Twice at most; then it needs his eyes. '
        'His tap or his words, never a plan step.'),
    "apply_outcome": (
        'What an employer did about an application he already sent. which names '
        'it the way he does (the employer, the job, or the application id); '
        'outcome is one of replied, interview, offer, rejected, closed; note is '
        'anything he said about it ("Tuesday at 10"). Use it for "Tebra rejected '
        'my application", "I have an interview with Gong". It never sends '
        'anything and never changes an application\'s own state.'),
    "apply_answer": (
        'His answer to ONE question the staged job applications are waiting '
        'on ("the relocation question is yes", "tell them I have a bachelor\'s '
        'degree"). question is the question in his words, answer is his answer. '
        'It is matched to the waiting question and every application that asked '
        'it is filled and brought back for his confirmation.'),
    "apply_prepare": (
        'Use for "apply to N jobs for me". It finds real postings, reads '
        'them, and writes a PACKET per job into her workspace — the posting '
        'as read, a cover letter written against it and his resume, and a '
        'checklist — then files a task per application. It SUBMITS NOTHING '
        'and never can: a submitted application is a real message to a real '
        'employer under his name with no undo, and four separate gates '
        'refuse it. Do not add a step that tries to submit; say in the '
        'summary that the last step is his. role is the kind of job ("senior '
        'backend engineer"), count is at most 10, where is an optional '
        'location or "remote", resume is a workspace path.'),
    "compose": (
        'USE THIS, NOT file_write, whenever the content has to be WRITTEN '
        'rather than pasted — "write me a note about X", "summarise my '
        'resume into three bullets", "draft a cover letter". `what` is the '
        'instruction in one sentence ("a three-bullet summary of his '
        'resume, plain language"); `sources` is a JSON LIST of file paths '
        'to read first (at most 3), workspace-relative or absolute; `path` '
        'is where to save it, relative to her workspace. The prose is '
        'written when the step RUNS, so the sources are actually read '
        'first. file_write is only for text you already have verbatim: '
        'used for authoring it produces a placeholder — "Three-bullet '
        'summary of resume, generated from the resume content retrieved '
        'above" is a real thing it wrote into a real file.'),
    "announce_set": (
        'on is a boolean: true lets her SPEAK UP unasked in the room when '
        'something urgent or important is waiting, false goes back to '
        'answering only when asked. quiet_from/quiet_until are "HH:MM" local '
        'times she stays silent between. Use it for "tell me when something '
        'needs me", "stop talking to me unless I ask", "no announcements '
        'after ten".'),
    "computer_do": (
        "steps is a JSON LIST of step objects, each one of: "
        '{"action":"open_app","app":"notepad.exe","arguments":[]} | '
        '{"action":"wait_window","window":{"title_re":"Notepad"}} | '
        '{"action":"focus_window","window":{...}} | '
        '{"action":"set_text","window":{...},"control":{"control_type":"Edit"},"text":"..."} | '
        '{"action":"invoke","window":{...},"control":{"title":"Save"}} (presses a button, flips a '
        'checkbox or switch, or opens a drop-down, named by its visible label) | '
        '{"action":"hotkey","window":{...},"keys":"ctrl+s"} (safe keys only: clipboard, '
        'undo, find, save, navigation, escape, tab — never enter/delete/alt+f4) | '
        '{"action":"select","window":{...},"control":{"control_type":"ComboBox"},"value":"UTF-8"} | '
        '{"action":"pause","seconds":3} (waits up to 10 seconds, touches nothing, names no window). '
        "Selectors use title, title_re, class_name, auto_id, control_type (a control "
        "also best_match) — never screen coordinates. A window title_re matches anywhere in the title, ignoring case. A text area is control_type Edit or Document (either finds it). set_text REPLACES the control's whole text: to add to what is there, write the whole new text. Windows 11 Notepad reopens its last tabs on launch: to write fresh text, send hotkey ctrl+n after wait_window, then set_text. A control labelled Send, "
        "Delete, Pay, Purchase, Confirm, Submit, Post, Format, Uninstall or Empty Trash "
        "is never pressed on its own: a plan that presses one becomes ONE approval he "
        "gives for that exact plan, naming the press. Name such a control by its visible "
        "title, and do not plan around it."),
    "do_task": (
        "request is the ask in plain words. She writes a small Python program "
        "(standard library only, no network, no subprocess, workspace files only) "
        "and runs it. Use this ONLY when no other kind does the job."),
    "thread_draft": (
        'Start a CONVERSATION by email and draft its first message: "email the landlord about the '
        'listing", "write to the clinic asking if they take my insurance". to is who (a contact, a name '
        'she has written to before, or an address); about is what it is about in his words; body only '
        'when he dictated the exact words. She keeps the thread: the reply, the questions still open and '
        'when to follow up. It SENDS NOTHING - the message waits for his approval.'),
    "thread_status": (
        'Did they reply, and what happens next, read from the conversation she keeps: "did the landlord '
        'reply", "any word from the recruiter", "did they get back to me". which is who or what it was '
        'about; omit it (or "they") for the most recent conversation.'),
    "thread_send": (
        'Send the message on a conversation that he has ALREADY approved, now rather than on the next '
        'beat. thread is who or what it is about. It never approves anything.'),
    "thread_followup": (
        'Follow up on a conversation that has gone quiet: "follow up with the landlord", "nudge the '
        'recruiter". She re-asks only what was already asked; it waits for his approval unless he gave '
        'standing permission for follow-ups on that conversation.'),
    "calendar_find_free": (
        'When he is free across a stretch of days, around what is already on his calendar (with travel '
        'time when places are known): "when am I free next week for a tour", "what does Thursday look '
        'like". when is today, tomorrow, a weekday, this week, next week, this weekend or a date; minutes '
        'is how long; location where it is; part morning/afternoon/evening.'),
    "calendar_hold": (
        'Pencil something into HIS calendar as tentative, in her own calendar model (nothing is sent, '
        'nothing goes onto a live calendar): "hold Friday at 10 for the tour". start is ISO-8601 in his '
        'timezone; end or minutes; location; thread links it to a conversation; replaces is the start of '
        'his own hold with the same title that this one moves ("make it 8"); was_title is that hold\'s old '
        'title when this renames it ("rename my Thursday meeting to standup"). It refuses when it '
        'clashes and says with what.'),
    "place_add": (
        'Remember where one of his places is: "my work address is 5 Market St", "the gym is at 20 Oak '
        'Ave". name is what he calls it, address what he said. Saying it again updates it.'),
    "hold_release": (
        'Take one of HER OWN tentative holds off his calendar model - one she pencilled in, never an '
        'event of his live calendar: "cancel my meeting with Sam" after she held it. title and start '
        'are the hold\'s own. Released, not deleted: its history is kept.'),
    "calendar_propose": (
        'Offer times to the other person in a conversation: "suggest some times to the landlord next '
        'week". thread is who it is with; when the stretch of days; minutes; location. It drafts the '
        'reply with free times and waits for his approval, because offering his hours commits him.'),
    "texts_read": (
        'His recent texts on his Google Voice number: "read my last text", "did Sam text me". '
        'who is a sender name to narrow to. Reads only; texts on his own phone stay there.'),
    "email_read": (
        "which is a sender name/address or a subject fragment; it must match exactly "
        "one UNREAD message (otherwise she asks which). Use email_check first to see "
        "what is unread."),
}

# Kinds that need the operator's PC (a real browser, later the desktop).
# The partition is STATIC and disjoint on purpose: the Actions runner
# executes every kind NOT in this set; the local Core executes ONLY the
# kinds in it. Two runners share the commands directory, and receipts are
# the idempotency mechanism — a static partition is what guarantees no
# command can ever be executed by both sides in a race. A local kind with
# no receipt is honestly PENDING: the PC hasn't picked it up (Core off or
# offline), and ChatGPT should say exactly that, not invent an outcome.
LOCAL_KINDS = {"browse_read", "browse_shot", "screenshot", "email_check", "email_read", "email_draft",
               # her browser profile, signed in to Google Voice, is on the PC
               "texts_read",
               # the job hunt's pause marker lives in the PC's private state
               "apply_pause",
               # her unattended ledger, and the stores an undo reverses, are on the PC
               "undo",
               # the Instagram token is in the PC's vault; the ledger beside it
               "instagram_post", "instagram_posts",
               # his interview switch and window live in the PC's private state
               "interview_window_set", "interview_status",
               # a recording is a process and a file on this PC
               "screen_record", "screen_record_stop", "recording",
               # the workspace is a directory on his PC
               "doc_make",
               # what he asks about his projects queues in private state on the PC
               "project_new", "project_step", "project_drop",
               # his long missions live in private state on the PC
               "mission_new", "mission_add", "mission_confirm", "missions", "mission_activity",
               # a work session checks projects out, runs tests and asks her own model: this PC
               "work_projects", "work_report",
               # a study reads his project folder and keeps its evidence in private state here
               "study_new", "studies", "study_decide", "study_confirm",
               # Phone Link is paired to his iPhone on THIS machine;
               # Actions cannot text anybody.
               "message_send", "music",
               # her conversations and his calendar model are private state on the PC
               "thread_draft", "thread_status", "thread_send", "thread_followup",
               "calendar_find_free", "calendar_hold", "hold_release", "calendar_propose",
               # research only READS pages, but it reads them with the
               # operator's browser, so it belongs to the PC runner
               "research",
               # the workspace is a directory on his PC; Actions cannot see it
               "file_write", "file_edit", "file_read", "file_list", "file_find",
               "file_size", "compose",
               "file_delete", "file_move",
               # reads the open web and writes into her workspace: both PC
               "apply_prepare", "apply_campaign", "apply_answer", "applications",
               "apply_outcome",
               "web_task", "web_task_retry",
               "subscription_cancel", "web_task_answer",
               "computer_observe",
               # ffmpeg and his media files live on the PC
               "media_probe", "media_trim", "media_join", "media_audio",
               "media_captions", "media_convert",
               "remind_at", "remind_daily", "remind_weekly", "remind_monthly", "remind_every",
               "reminders", "reminder_off", "reminder_on", "notify_snooze",
               "watch_email_from", "notify_check",
               "notify_clear", "free_time", "contact_add", "contact_remove", "notify_operator",
               "intent", "screen_ask",
               # every private-state verb below lives on the PC
               "meet", "recall", "forget", "handle", "travel_time", "place_add", "shopping_add",
               "shopping_list", "shopping_off", "contacts", "watches", "drafts", "draft_discard",
               "list_new", "list_add", "list_read", "list_off", "stopwatch", "stopwatch_read",
               "speaking_pace", "speaking_pace_read",
               "subscriptions", "money", "car", "projects", "authority_status", "setup_status",
               # the desktop and the sandbox are both on his PC
               "computer_do", "do_task",
               # the room that speaks, and the config it reads, are on the PC
               "announce_set"}


# Kinds that only LOOK. Nothing here changes the world, sends anything, or
# commits the operator to something, so a plan made only of these needs no
# approval — asking him to authorise "tell me the time" is how an approval
# queue becomes noise he stops reading.
READ_ONLY_KINDS = frozenset({
    "instagram_posts", "interview_status",
    # Asking whether she is on changes nothing and must stay answerable
    # while she is halted, closed, or halfway between the two.
    "running",
    "preferences",
    # And so must "what are your workers doing" — knowing what is running
    # is most urgent exactly when something has gone wrong.
    "agents",
    # "Is the microphone on" must be answerable at any time, in any
    # state. It is the question he is most entitled to a straight answer
    # to, and it changes nothing by being asked.
    "mic",
    # "Can you see my screen" is a question about a switch, and he is
    # entitled to a straight answer whenever he asks it.
    "eyes",
    # "Are you using my ChatGPT" must be answerable at any moment: it is
    # his account, and the question is one he is entitled to a straight
    # answer to whatever else is happening.
    "chatgpt",
    "note", "notify_check", "free_time", "brief", "subscriptions", "money",
    # Reads public job boards. Prepares nothing, sends nothing.
    "jobs", "tasks", "reminders", "shopping_list", "applications", "list_read", "stopwatch_read",
    "speaking_pace_read",
    "contacts", "watches", "drafts",
    "projects", "car", "recall", "travel_time", "browse_read", "browse_shot",
    # how his long missions stand and what they wait on changes nothing
    "missions",
    # what a work session did is read from its receipts
    "work_report",
    # what a study found and proposes is read from its record
    "studies",
    # reads public pages and writes a document; commits him to nothing
    "research",
    # looking at his own files commits him to nothing
    "file_read", "file_list", "file_find", "file_size",
    # looking at his own screen commits him to nothing either
    "computer_observe",
    # and photographing it commits him to nothing: the file stays on the
    # PC under cache/, which is gitignored, exactly like browse_shot's
    "screenshot",
    # whether a recording is running changes nothing
    "recording",
    # reading what a media file IS changes nothing
    "media_probe",
    "email_check", "email_read", "screen_ask", "authority_status", "setup_status",
    # reading the texts page changes nothing
    "texts_read",
    # Reading her own conversation records and his free time changes nothing.
    "thread_status", "calendar_find_free",
})


# Local, reversible, private, and reaching nobody but him. A routine step
# writes to his own machine and can be undone by saying the opposite.
# Nothing here spends, sends, publishes, or binds him to anything.
ROUTINE_KINDS = frozenset({
    "task_new", "task_status", "plan_new", "plan_add_step", "plan_step",
    "preference_set",
    # Taking back one of her own reversible acts reaches nobody; the act
    # itself was routine, and only his word gets here (PLANNER_FORBIDDEN).
    "undo",
    # His interview hours, in his own store; reversible by saying another.
    "interview_window_set",
    # His "handled" on a red project: one private row beside the pulse.
    "fault_ack",
    # His "Clear" on a browser mission: its record left, nothing pressed.
    "mission_leave",
    # A page opened in his own browser, on his PC, from a record she holds.
    "open_page",
    # Starting and stopping a capped recording of one window, to a file on
    # his PC that goes nowhere.
    "screen_record", "screen_record_stop",
    "plan_set", "remind_at", "remind_daily", "remind_weekly", "remind_monthly", "remind_every",
    # Queuing what he said about his projects: one private local file, and
    # nothing new starts from it until he says yes to the draft it becomes.
    "project_new", "project_step", "project_drop",
    # A long mission is the same shape: his words queue a private draft, his
    # confirm makes it active, and every step that reaches anyone still asks
    # him through its own approval. A schedule starting an activity's
    # occurrence only adds a task to that private record.
    "mission_new", "mission_add", "mission_confirm", "mission_activity",
    # Starting a work session on his say-so. It grants nothing: each item it runs
    # goes through the gates that item already has (the broker, handoffs, the
    # repair tier's branch-and-PR rule, rehearsal), and nothing world-touching
    # happens without its own approval.
    "work_projects",
    # A study reads public pages politely and his own project, and proposes; his
    # decision on a proposal is recorded here, and an accepted change runs only
    # through paths that already have their gates (a branch, a packet, a handoff).
    "study_new", "study_decide", "study_confirm",
    # Disabling a reminder is reversible by saying the opposite, which is
    # the whole test for this tier — the schedule is disabled, never
    # deleted, so "actually put that back" is one command.
    "reminder_off", "reminder_on", "shopping_off", "notify_snooze", "notify_operator",
    # His own named lists: the same act on the same kind of store.
    "list_new", "list_add", "list_off",
    # His stopwatch: one small record of his own, reset by one word.
    "stopwatch",
    # How fast she talks: one number of his, put back by "talk normally".
    "speaking_pace",
    # Writes one file inside her own workspace: reversible, reaches
    # nobody, and the workspace keeps the previous version. Same tier as
    # `file_write`, which it sits beside.
    "doc_make",
    # Stopping a worker only ever REDUCES what is running, and a stop
    # that waits for an approval arrives after the thing it was meant to
    # prevent. Creating one is world-tier; stopping one is not.
    "agent_stop", "agents_pause",
    # CLOSING the microphone only ever reduces what is listening, so it
    # is routine and never waits. Opening it is world-tier by falling
    # through, and forbidden to the planner besides.
    "mic_off", "chatgpt_off", "eyes_off",
    # Pressing pause is as reversible as pressing play, and a media
    # key reaches nobody outside the room.
    "music",
    # Ticking a task off. It was left out when it was added — an
    # OVERSIGHT, not a gate: `task_status` sets ANY status including
    # COMPLETED and has always been routine, so the narrower verb was
    # asking for approval while the general one did not.
    "task_done",
    # Moving, renaming or dropping one of HIS tasks is the same act on the
    # same store as ticking it off.
    "task_change",
    # `forget` sits beside `remember` because it is the same act on the
    # same private store, and putting it anywhere else would mean she can
    # be told something without an approval and needs one to be told to
    # drop it. It is the one act with no undo, though, so the receipt says
    # WHAT went rather than just "forgotten".
    "notify_clear", "remember", "forget", "contact_add", "contact_remove", "place_add", "shopping_add",
    # reversible by saying the opposite, reaches nobody but him, and its
    # own default is silence
    "announce_set",
    "watch_email_from", "handle",
    # Writing a file in her own workspace is local and REVERSIBLE: every
    # write keeps the previous version, so an undo always exists. The
    # boundary that makes this routine rather than world-touching is
    # aletheia.workspace — she cannot write outside her own directory.
    "file_write", "file_edit",
    # Composing is a file_write whose text she writes instead of pastes:
    # same directory, same version history, same undo. Nothing wider.
    "compose",
    # A conversation's DRAFT, a follow-up draft, a time proposal draft and a
    # tentative hold in her own calendar model: private, reversible, reaching
    # nobody. Every one of them that would SEND waits on its own hash-bound
    # approval (email.send / email.followup), so this tier authorizes writing
    # it down and nothing past that.
    "thread_draft", "thread_followup", "calendar_hold", "hold_release", "calendar_propose",
    # A held email draft put away unsent: kept and marked, reaching nobody.
    "draft_discard",
    # Deleting and moving keep a version FIRST, so both are undoable. A
    # delete that cannot lose anything is a shelf, not a shredder.
    "file_delete", "file_move",
    # Application packets are files and tasks; the one irreversible step in
    # a job application is deliberately not in this kind at all.
    "apply_prepare",
    # Filling forms and staging approvals. It sends nothing on its own:
    # every application still waits for the approval he taps, per job.
    "apply_campaign",
    # His answer, put into the waiting forms: they come back for his
    # confirmation exactly as before, and nothing is sent.
    "apply_answer",
    # A note on his own record of what an employer did. Sends nothing,
    # changes no application's state.
    "apply_outcome",
    # Media edits always write a NEW file and never touch the source, so
    # the worst case is a spare file in her workspace.
    "media_trim", "media_join", "media_audio", "media_captions",
    "media_convert",
})

# Everything else is WORLD-TOUCHING and is never granted away: dispatch and
# issue reach other repositories, email_draft and meet reach another person,
# browse_shot writes a file, halt/resume/approve/deny are the controls
# themselves. The classification FAILS CLOSED — a kind added tomorrow and
# forgotten here is treated as world-touching, which is the safe mistake.
TIER_READ, TIER_ROUTINE, TIER_WORLD = "read", "routine", "world"


def _agent_id(name: str) -> str:
    """A spoken name -> a filesystem-safe id, deduped against what exists."""
    import re as _re
    from aletheia import agents
    base = _re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:40]
    base = base or "worker"
    candidate, n = base, 2
    while agents.exists(candidate):
        candidate, n = f"{base}-{n}", n + 1
    return candidate


#: Read-only kinds that PRODUCE something he would want back later: a
#: remembered note, a picture on disk, a written document. They need no
#: authority, which is why they are read-only, and they are still things
#: she DID - so they journal as actions and appear in "what did you do
#: today". Everything else read-only merely answers a question.
MAKES_SOMETHING = frozenset({"note", "screenshot", "browse_shot", "research"})


def only_answers(kind: str) -> bool:
    """Did this change nothing but tell him something?

    Used to decide whether the journal records an ACTION or an EVENT.
    Deliberately conservative in one direction: an unlisted kind counts
    as work, so a new verb shows up in her account of the day until
    somebody decides it should not. Missing real work is the worse
    error - it is how a store gets a writer and no reader.
    """
    return kind in READ_ONLY_KINDS and kind not in MAKES_SOMETHING


def tier(kind: str) -> str:
    """How much authority one command really needs."""
    if kind in READ_ONLY_KINDS:
        return TIER_READ
    if kind in ROUTINE_KINDS:
        return TIER_ROUTINE
    return TIER_WORLD


def plan_tier(kinds) -> str:
    """The tier of a whole plan: its most demanding step, always.

    One world-touching step makes the entire plan world-touching. A plan is
    not a menu he approves parts of; it runs as a sequence, so it is
    authorised as a whole at the level of its riskiest member.
    """
    tiers = {tier(k) for k in kinds}
    if TIER_WORLD in tiers:
        return TIER_WORLD
    if TIER_ROUTINE in tiers:
        return TIER_ROUTINE
    return TIER_READ


class Unavailable(RuntimeError):
    """The kind is real but this machine cannot do it right now — a tool or
    backend is missing (no ffmpeg, no pywinauto). Not a refusal: nothing
    said no; and not an error: nothing broke. Callers report it as such."""


def _steps_of(cmd: dict):
    """computer_do carries a step LIST; a relayed command may carry it as
    JSON text. Either way it is decoded here, once, before validation."""
    steps = cmd.get("steps")
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except json.JSONDecodeError:
            return None
    return steps


# Kinds the PLANNER is not shown and may not emit.
#
# Every one of them is reached by its own direct path in `aletheia.voice`,
# BEFORE the planner is ever called: "stop everything" and "resume" match
# their own regexes, and so do "approve" and "deny". So the planner does
# not need them — and being able to emit them is pure downside, because a
# compiler that turns English into command names can be led there by a
# word that merely LOOKS like one.
#
# Found by running the sentence, 2026-09-03. "Summarize my resume into
# three bullets and save it as summary.md" compiled to
#
#     [{"kind": "resume"}, {"kind": "file_write", ...}]
#
# — a step that LIFTS HER KILL SWITCH, marked EXECUTABLE and validating
# clean, because the English noun "résumé" and the kind name `resume` are
# the same six letters. The same door is open on `approve`: a sentence
# containing "approve" could compile into granting an approval, which is
# the self-authorization hole every other refusal in this system is built
# to keep shut.
#
# This mirrors `agenda.FORBIDDEN_KINDS` on purpose. An agenda may not run
# them; the planner may not even name them.
PLANNER_FORBIDDEN = frozenset({
    "halt", "resume",      # a kill switch a compiler can trip is decoration
    "restart",             # and so is a restart button
    "apply_retry",         # a second send is his tap, never a plan's guess
    "update_now",          # and a pull of her own code is his tap, not a plan step
    "fault_ack",           # a fault marked handled by a model is a fault hidden
    "mission_leave",       # clearing a card that waits on him is his tap
    "undo",                # taking back one of her own acts is his word, never a compiler's
    "interview_window_set",  # his hours are his to say; a guess here books interviews at the wrong time
    "open_page",           # a page on his screen is his tap, never a compiler's
    "apply_pause",         # "stop applying" is his word, never a compiler's guess
    "approve", "deny",     # self-authorization, from an ambiguous word
    # Same rule, same reason. "Close the browser tab", "open my resume"
    # and "shut the door" are ordinary sentences full of these words, and
    # a compiler that turns English into command names can be led there.
    # Every phrasing that means the SWITCH is matched in `voice` before
    # the planner is ever called.
    "close", "open",
    # A microphone a model can open is not a microphone that is off. His
    # ruling: it is a button he presses, and the planner is not a button.
    "mic_on",
    # And a model may not decide to start sending pictures of his screen
    # off the machine. Same reason as the microphone, higher stakes: a
    # screenshot carries whatever happened to be on screen, and unlike
    # window text it cannot be redacted on the way out.
    "eyes_on",
    # A study's proposal is accepted, kept or reverted on HIS words, and the
    # comparables she found are read on his yes: a compiler that turns "sure,
    # whatever" into an acceptance decides for him.
    "study_decide", "study_confirm",
})


# Arguments whose value is a CLOSED SET, and the module that owns it.
#
# The grammar the planner is shown is generated from `KIND_ARGS`, which
# gives argument NAMES and nothing else — so an argument that only accepts
# four values looked, from the prompt, like free text. It guessed
# reasonably and wrongly: `remember` with domain "family" (the real ones
# are identity/preferences/people/organizations) and memory_kind "fact"
# (the real ones are explicit/inferred/temporary). Both passed
# `validate_kind_args`, which checked that the ARGUMENT was allowed and
# never what was in it, so the step was marked EXECUTABLE, approved, and
# then died at execution with a bare ValueError. "Remember my sister is
# Mia" — the most ordinary sentence an assistant hears — did nothing.
#
# Resolved from the owning module at call time, never copied: a second
# copy of an enum in a prompt is a copy that disagrees with the validator
# the day someone adds a value.
def _enum(module_name: str, attribute: str):
    def read():
        import importlib
        return sorted(getattr(importlib.import_module(module_name), attribute))
    return read


KIND_ENUMS: dict[str, dict[str, object]] = {
    "remember": {"domain": _enum("aletheia.memory", "DOMAINS"),
                 "memory_kind": _enum("aletheia.memory", "KINDS")},
    "preference_set": {"field": _enum("aletheia.profile", "PREFERENCE_FIELDS")},
    "task_status": {"state": _enum("aletheia.contracts", "TASK_STATES")},
    "rule": {"state": _enum("aletheia.suggestions", "VALID_STATES")},
    "plan_set": {"state": _enum("aletheia.plans", "PLAN_STATES")},
    "plan_step": {"state": _enum("aletheia.plans", "STEP_STATES")},
    "stopwatch": {"action": _enum("aletheia.stopwatch", "ACTIONS")},
    "speaking_pace": {"action": _enum("aletheia.speaking_pace", "ACTIONS")},
}


def allowed_values(kind: str, arg: str) -> list[str] | None:
    """The closed set for one argument, read from the code that enforces it."""
    reader = KIND_ENUMS.get(kind, {}).get(arg)
    if reader is None:
        return None
    try:
        return list(reader())
    except Exception:
        return None


def _enum_problems(cmd: dict) -> list[str]:
    out = []
    for arg, reader in KIND_ENUMS.get(cmd.get("kind"), {}).items():
        if arg not in cmd:
            continue
        allowed = allowed_values(cmd["kind"], arg)
        if allowed is None:
            continue
        if cmd[arg] not in allowed:
            out.append(f"{cmd['kind']}: {arg}={cmd[arg]!r} is not one of "
                       f"{allowed}")
    return out


def validate_kind_args(cmd, fleet: dict) -> list[str]:
    """Validate the inner command object (kind + args). Shared with the
    local Core's /api/command — one grammar, every channel."""
    problems: list[str] = []
    if not isinstance(cmd, dict) or "kind" not in cmd:
        return ["command must be an object with a kind"]
    kind = cmd["kind"]
    if kind not in KIND_ARGS:
        return [f"kind {kind!r} not in {sorted(KIND_ARGS)} — "
                "commands are named slots, never arbitrary asks"]
    required, optional = KIND_ARGS[kind]
    args = set(cmd) - {"kind"}
    if required - args:
        problems.append(f"{kind}: missing args {sorted(required - args)}")
    if args - required - optional:
        problems.append(f"{kind}: unexpected args {sorted(args - required - optional)}")
    # A closed-set argument is checked HERE, where a bad value becomes a
    # refusal the planner can see and repair, rather than an exception with
    # an approval already spent on it.
    problems += _enum_problems(cmd)
    repo = cmd.get("repo")
    if repo is not None and repo != "fleet" and repo not in fleet["repos"]:
        problems.append(f"repo {repo!r} is not 'fleet' or a fleet registry key")
    url = cmd.get("url")
    if url is not None and not (isinstance(url, str)
                                and url.startswith(("http://", "https://"))):
        problems.append(f"{kind}: url must be an http(s) URL")
    if kind == "computer_do" and "steps" in cmd:
        # The desktop plan is validated at the grammar gate, not first at
        # the desktop: a committing control is named here as a refusal the
        # planner can show, rather than discovered with a window open.
        from aletheia import computer
        steps = _steps_of(cmd)
        if not isinstance(steps, list):
            problems.append("computer_do: steps must be a JSON list of step objects")
        else:
            problems += [f"computer_do: {p}" for p in computer.validate_steps(steps)]
            if not problems:
                try:
                    computer.check_act_plan(steps)
                except computer.ApprovalRequired as exc:
                    problems.append(f"computer_do: {exc}")
    if kind == "do_task" and not str(cmd.get("request") or "").strip():
        problems.append("do_task: request must be non-empty text")
    return problems


def validate_command(path: Path, fleet: dict) -> list[str]:
    """Every problem with one command file; empty list = valid."""
    problems: list[str] = []
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        problems.append(f"{len(raw)} bytes — over the {MAX_BYTES} cap")
    try:
        c = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return problems + [f"not valid JSON: {exc}"]
    if not isinstance(c, dict):
        return problems + ["top level must be an object"]
    missing = REQUIRED_KEYS - set(c)
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
    if set(c) - REQUIRED_KEYS:
        problems.append(f"unexpected keys: {sorted(set(c) - REQUIRED_KEYS)}")
    if c.get("id") != path.stem:
        problems.append(f"id {c.get('id')!r} must match filename stem {path.stem!r}")
    if c.get("by") != "chatgpt" or c.get("relayed_from") != "operator":
        problems.append("by must be 'chatgpt' and relayed_from 'operator' — "
                        "the intercom relays the operator's words, nothing else")
    if not str(c.get("operator_quote", "")).strip():
        problems.append("operator_quote is required — the command must carry the operator's words")
    return problems + validate_kind_args(c.get("command"), fleet)


# 9-to-5, which is the window `calendar.free_slots` looks at. Said out
# loud only when the answer is empty BECAUSE he asked about hours she
# never sees — "nothing free this evening" is misleading on its own.
WORK_HOURS_NOTE = "I only look at your working hours, nine to five"


# What "open" means when he asks what is on his list.
# Words that carry no signal when he points at a task: "the passport ONE",
# "the dentist TASK". Matching on these makes every task a candidate.
TASK_STOP = frozenset("""the one task thing item that this those these my me
mine your a an and or of to for it its please just now""".split())

OPEN_TASK_STATES = ("QUEUED", "READY", "RUNNING", "BLOCKED",
                    "WAITING_OPERATOR", "WAITING_EXTERNAL",
                    "WAITING_DEPENDENCY", "RETRY_SCHEDULED")


def _open_tasks() -> list[dict]:
    """HIS open tasks. Her own build tickets (gap work filed for a worker)
    are not on his list, whatever store they share (`tasks.is_his`)."""
    from aletheia import tasks as tasks_mod
    return [t for t in tasks_mod.all_tasks()
            if str(t.get("status", "")).upper() in OPEN_TASK_STATES and tasks_mod.is_his(t)]


def _tasks_answer(which: str = "") -> str:
    """"What are my tasks" — a sentence, from the store, with no model.

    It used to reach the planner and come back as markdown bullets with
    the sentences run together: "Two open: - Call the dentist\n- Renew
    your passport No due dates attached to either."
    """
    from aletheia import speech
    rows = _open_tasks()
    if which:
        needle = which.casefold()
        rows = [t for t in rows
                if needle in str(t.get("description", "")).casefold()
                or needle in str(t.get("id", "")).casefold()]
        if not rows:
            return f"Nothing on your list matches {str(which).strip()}."
    if not rows:
        # "Add milk to my list", then "what's on my list": "Nothing on your
        # list" - the milk was on the other one.
        if _shopping_items():
            return "Nothing on your task list. " + shopping_answer()
        return "Nothing on your list."
    said = speech.and_list([_task_words(t) for t in rows[:5]])
    more = f", and {len(rows) - 5} more" if len(rows) > 5 else ""
    return f"{speech.count_phrase(len(rows), 'thing')} on your list: {said}{more}."


def _task_words(task: dict) -> str:
    """One task, with its deadline if it has one.

    Splitting "by Friday" out of the description made the deadline REAL —
    `tasks.due` can surface it on the beat now — and would have made it
    inaudible if the list did not say it back.
    """
    from aletheia import speech, tasks as tasks_mod
    words = str(task.get("description") or task["id"])[:70]
    when = tasks_mod.parse_deadline(task.get("deadline"))
    if not when:
        return words
    said = speech.humanize_time(when.isoformat())
    # "due Friday at 11:59 pm" is the end-of-day default, not a time he set.
    if said.endswith(" at 11:59 pm"):
        said = said[: -len(" at 11:59 pm")]
    # No comma: `and_list` already uses commas, and "renew my passport,
    # due Friday and submit the form, due tomorrow" is unparseable by ear.
    return f"{words} due {said}"


REMINDER_KINDS = {"once": "remind_at", "daily": "remind_daily",
                  "weekly": "remind_weekly", "monthly": "remind_monthly",
                  # "every other day" / "every 2 weeks": the interval kind,
                  # and only when its command tells him something.
                  "interval": "remind_daily"}


def _reminder_schedules() -> list[dict]:
    """Every ENABLED schedule that exists to tell him something.

    A schedule whose command is `notify_operator` is a reminder; anything
    else on the same store is automation he did not ask to hear about.
    """
    from aletheia import scheduler
    out = []
    for spec in scheduler.all_schedules():
        if not spec.get("enabled", True):
            continue
        if str((spec.get("command") or {}).get("kind")) != "notify_operator":
            continue
        if spec.get("kind") in REMINDER_KINDS:
            out.append(spec)
    return out


def _reminder_words(spec: dict, *, receipt: bool = False) -> str:
    """One reminder, as he would say it."""
    from aletheia import speech
    text = str((spec.get("command") or {}).get("text") or spec["id"])[:70]
    if spec["kind"] == "once":
        timer = re.fullmatch(r"(your .+? timer) is up", text)
        if timer and not receipt:
            # "your 10-minute timer is up — today at 5:10 am" read as if it
            # had already gone off; it is a timer still running.
            return f"{timer.group(1)} — going off {speech.humanize_time(str(spec.get('at') or ''))}"
        return f"{text} — {speech.humanize_time(str(spec.get('at') or ''))}"
    if spec["kind"] == "interval":
        minutes = int(spec.get("every_minutes") or 0)
        if minutes < 1440:
            hours, mins = divmod(minutes, 60)
            span = ("every hour" if minutes == 60 else f"every {hours} hours" if not mins and hours
                    else "every half hour" if minutes == 30 else f"every {minutes} minutes")
            return f"{text} — {span}"
        weeks, days = divmod(minutes // 1440, 7)
        span = (f"every {weeks} weeks" if weeks > 1 and not days else "every week" if weeks == 1 and not days
                else "every other day" if minutes == 2880 else f"every {minutes // 1440} days")
        return f"{text} — {span} at {speech.clock_words(str(spec.get('anchor') or '')[11:16])}"
    when = speech.clock_words(str(spec.get("time") or ""))
    if spec["kind"] == "daily":
        return f"{text} — every day at {when}"
    if spec["kind"] == "monthly":
        return f"{text} — on the {_ordinal(int(spec.get('monthday') or 1))} of every month at {when}"
    days = _weekday_words(sorted(spec.get("weekdays") or []))
    lead = days if days in ("weekdays", "weekends", "every day") else f"every {days}"
    return f"{text} — {lead} at {when}"


def _soonest_first(rows: list) -> list:
    """Reminders in the order they go off ("call mom at 6 pm and check the
    oven at 5:33 am" was read in the order they were made, 2026-10-07)."""
    import datetime as _dt
    from aletheia import scheduler
    now = _dt.datetime.now(_dt.timezone.utc)
    far = now + _dt.timedelta(days=36500)

    def when(spec):
        try:
            return scheduler.next_occurrence(spec, now) or far
        except Exception:
            return far
    return sorted(rows, key=when)


def _reminders_answer(which: str = "") -> str:
    """"What reminders do I have" — from the store, with no model."""
    from aletheia import speech
    rows = _reminder_schedules()
    noun = "reminder"
    if which.casefold() == "recurring":
        # "What are my recurring reminders" listed tonight's one-off too (2026-10-08)
        rows = [r for r in rows if r.get("kind") != "once"]
        if not rows:
            return "You have no repeating reminders set."
        which = ""
    if which:
        needle = which.casefold()
        noun = {"wake up": "alarm", "timer is up": "timer"}.get(needle, "reminder")
        rows = [r for r in rows
                if needle in str((r.get("command") or {}).get("text", "")).casefold()]
        if not rows:
            if noun != "reminder":
                return f"You have no {noun}s set."
            return f"No reminder matching {which!r}."
    if not rows:
        return "You have no reminders set."
    rows = _soonest_first(rows)
    said = speech.and_list([_alarm_words(r, alone=noun == "alarm") for r in rows[:5]])
    more = f", and {len(rows) - 5} more" if len(rows) > 5 else ""
    return f"{speech.count_phrase(len(rows), noun)}: {said}{more}."


def _alarm_words(spec: dict, *, alone: bool = True) -> str:
    """A reminder as he would say it, and an alarm as its time: "tomorrow
    at 6:30 am" in a list of alarms, "alarm — tomorrow at 6:30 am" among
    reminders; never "wake up — tomorrow at 6:30 am"."""
    words = _reminder_words(spec)
    if str((spec.get("command") or {}).get("text") or "").strip().casefold() == "wake up":
        words = re.sub(r"^wake up\s*([—-])\s*", "" if alone else r"alarm \1 ", words, flags=re.IGNORECASE)
    # "1 reminder: take my vitamins" is his phrase in her mouth (2026-10-08).
    from aletheia import speech
    return speech._yours(words)


def _until_next_reminder(sort: str = "reminder") -> str:
    """"How long until my alarm": the gap to the soonest one, in words."""
    import datetime as _dt
    from aletheia import scheduler
    needle = {"alarm": "wake up", "timer": "timer is up"}.get(sort, "")
    rows = [r for r in _reminder_schedules()
            if needle in str((r.get("command") or {}).get("text", "")).casefold()]
    if not rows:
        return f"You have no {sort}s set."
    first = _soonest_first(rows)[0]
    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        at = scheduler.next_occurrence(first, now)
    except Exception:  # noqa: BLE001
        at = None
    if not at:
        return _next_reminder_answer(sort)
    minutes = max(1, int(((at - now).total_seconds() + 30) // 60))
    hours, mins = divmod(minutes, 60)
    # "1 day and 29 minutes" is how nobody says tomorrow morning: under two
    # days it is hours.
    days, hours = divmod(hours, 24) if hours >= 48 else (0, hours)
    parts = [f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in ((days, "day"), (hours, "hour"), (mins, "minute")) if n]
    if days:
        parts = parts[:2]
    gap = " and ".join(parts)
    what = str((first.get("command") or {}).get("text") or "").strip()
    if sort == "alarm" or what == "wake up":
        return f"Your next alarm goes off in {gap}."
    return f"Your next {sort}, {what}, is in {gap}."


def _skip_once(found: dict, once: str) -> str:
    """"Skip tomorrow's pill reminder" (2026-10-08): that one time, and the
    schedule stays on. A one-off has nothing to skip but itself."""
    from aletheia import localtime, scheduler, speech
    if found.get("kind") == "once":
        raise act.Refused(f"that one only goes off once - say \"cancel the {_reminder_words(found).split(' — ')[0]} reminder\" to stop it.")
    tz = localtime.operator_tz()
    now = dt.datetime.now(dt.timezone.utc)
    at = scheduler.next_occurrence(found, now)
    want = {"today": 0, "tonight": 0, "tomorrow": 1}.get(" ".join(once.casefold().split()))
    if want is not None:
        day = dt.datetime.now(tz).date() + dt.timedelta(days=want)
        while at is not None and at.astimezone(tz).date() < day:
            at = scheduler.next_occurrence(found, at)
        if at is None or at.astimezone(tz).date() != day:
            raise act.Refused(f"it doesn't go off {once} - {_reminder_words(found).split(' — ')[-1]}.")
    if at is None:
        raise act.Refused("it has nothing coming up to skip.")
    scheduler.skip_once(found["id"], at)
    words = _reminder_words(found).split(" — ")[0]
    after = scheduler.next_occurrence(scheduler.load(found["id"]), at)
    return (f"reminder {found['id']} skipped — {speech._yours(words)} won't go off "
            f"{speech.humanize_time(at.isoformat())}"
            + (f"; next {speech.humanize_time(after.isoformat())}" if after else ""))


def _next_reminder_answer(sort: str = "reminder") -> str:
    """"When's my next alarm" - the soonest one of that sort, not the list."""
    from aletheia import speech
    needle = {"alarm": "wake up", "timer": "timer is up"}.get(sort, "")
    rows = [r for r in _reminder_schedules()
            if needle in str((r.get("command") or {}).get("text", "")).casefold()]
    if not rows:
        return f"You have no {sort}s set."
    rows = _soonest_first(rows)
    more = f" You have {len(rows) - 1} more after it." if len(rows) > 1 else ""
    said = _reminder_words(rows[0])
    if sort == "alarm" and " — " in said:
        # Every alarm says "wake up"; the time is the answer.
        return f"Your next alarm is {said.split(' — ', 1)[1]}.{more}"
    return f"Your next {sort}: {said}.{more}"


def _reminder_list_words(rows: list) -> str:
    """What he DOES have, for when the one he named is not there."""
    from aletheia import speech
    said = [_reminder_words(r) for r in rows[:4]]
    lead = ("The one you have is" if len(rows) == 1
            else f"The {len(said)} you have are")
    tail = "" if len(rows) <= 4 else f", and {len(rows) - 4} more"
    return f"{lead} {speech.and_list(said)}{tail}."


#: The subject a forgotten note's tombstone carries. `quick._notes` skips a
#: note whose text a later tombstone names.
FORGOTTEN_SUBJECT = "operator:forgotten"


def _forget_note(about: str) -> str:
    """Tombstone the newest note that says what `about` names; return its
    text, or "" when no note matches. Never raises."""
    try:
        from aletheia import journal, quick
        words = [w for w in re.findall(r"[a-z0-9']+", str(about or "").casefold())
                 # "Forget where I parked" names the note by its question
                 # (2026-10-07: "nothing remembered about where I parked").
                 if w not in ("my", "the", "about", "what", "you", "know", "everything",
                              "where", "when", "which", "who", "how", "that")]
        if not words:
            return ""
        for row in quick._notes():
            text = str(row.get("text") or "")
            low = text.casefold()
            if all(w in low for w in words):
                journal.append("note", FORGOTTEN_SUBJECT, text[:300], actor="operator")
                return " ".join(text.split())[:160]
    except Exception:
        return ""
    return ""


def _what_it_is_about(said: str, *, keep_whose: bool = False) -> str:
    """"What I said about Dana" -> "Dana": every lead, in any order. "What you
    know about MY landlord" kept the "my", and "what I said about Dana" was a
    phrase no note holds (2026-10-07). `keep_whose` leaves a leading "my"
    for a note, which says "my sister's name is Dana" in his words."""
    lead = (r"what (?:you know|i (?:said|told you)|i've told you) about |everything (?:you know )?about "
            r"|(?:my |the )?notes? (?:about|on) ")
    if keep_whose:
        return re.sub(r"^(?:" + lead + r")", "", said, flags=re.IGNORECASE) or said
    return re.sub(r"^(?:(?:my|the) |" + lead + r")+", "", said, flags=re.IGNORECASE)


def _remembered_matching(about: str, domain: str | None = None):
    """(domain, key, value) for everything she has that he could mean.

    An empty `about` returns the lot, which is how the miss answer says
    what he DOES have. Matched on the key AND the value, because "forget
    Dana" is as natural as "forget my landlord" and only one of those is
    a key.
    """
    from aletheia import memory
    needle = " ".join(str(about or "").casefold().split())
    # "My landlord" is how he says it; "landlord" is how it is stored.
    # Every lead, in any order: "what you know about MY landlord" kept the
    # "my", and "what I said about Dana" was a phrase no note holds
    # (2026-10-07).
    needle = _what_it_is_about(needle)
    found = []
    for one in memory.DOMAINS if not domain else [domain]:
        try:
            for key, entry in (memory._load(one) or {}).items():
                value = str((entry or {}).get("value", ""))
                if not needle:
                    found.append((one, key, value))
                    continue
                hay = f"{key} {value}".casefold()
                if needle in hay or needle.replace(" ", "") in key.casefold():
                    found.append((one, key, value))
        except Exception:
            continue
    return found


def _reminder_back_on(which: str) -> str:
    """Re-enable what reminder_off disabled: "put that back" (2026-10-07: the
    comments promised one command and there was none)."""
    import datetime as _dt
    from aletheia import scheduler, speech
    now = _dt.datetime.now(_dt.timezone.utc)
    stopped = []
    for spec in scheduler.all_schedules():
        if spec.get("enabled", True) or str((spec.get("command") or {}).get("kind")) != "notify_operator":
            continue
        stopped.append(spec)

    def changed(spec):
        try:
            return _dt.datetime.fromisoformat(str(spec.get("updated_at") or "").replace("Z", "+00:00"))
        except ValueError:
            return _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)

    def still_ahead(spec):
        try:
            # Asked as if it were on: a stopped schedule has no next time.
            return scheduler.next_occurrence({**spec, "enabled": True}, now) is not None
        except Exception:  # noqa: BLE001
            return False

    needle = " ".join(which.casefold().split())
    every = {"all alarms": "wake up", "all timers": "timer is up", "all reminders": ""}.get(needle)
    if every is not None:
        hits = [r for r in stopped if every in str((r.get("command") or {}).get("text") or "").casefold()
                and now - changed(r) <= _dt.timedelta(days=1)]
    else:
        hits = [r for r in stopped if needle and needle in str((r.get("command") or {}).get("text") or "").casefold()]
        if not hits:
            words = [w for w in re.split(r"[^a-z0-9]+", needle) if len(w) > 2 and w not in TASK_STOP and w != "reminder"]
            hits = [r for r in stopped
                    if words and all(w in str((r.get("command") or {}).get("text") or "").casefold() for w in words)]
        hits = sorted(hits, key=changed, reverse=True)[:1]
    if not hits and every is None:
        # "Skip tomorrow's vitamin reminder", then "turn it back on": the
        # reminder never stopped, one time of it was skipped (2026-10-08).
        found, _why = _one_reminder(which)
        if found is not None and found.get("skips"):
            scheduler.unskip(found["id"])
            at = scheduler.next_occurrence(scheduler.load(found["id"]), now)
            return (f"Back on: {speech._yours(_reminder_words(found).split(' — ')[0])}"
                    + (f", next {speech.humanize_time(at.isoformat())}" if at else "") + ".")
    if not hits:
        raise act.Refused("There's no stopped reminder like that to put back." if every is None
                          else "Nothing was stopped in the last day to put back.")
    back, gone = [], []
    for spec in hits:
        (back if still_ahead(spec) else gone).append(spec)
    for spec in back:
        scheduler.set_enabled(spec["id"], True)
    said = []
    if back:
        said.append("Back on: " + speech.and_list([_reminder_words(r) for r in back[:4]])
                    + (f", and {len(back) - 4} more" if len(back) > 4 else "") + ".")
    if gone:
        said.append("Its time has already gone by, so it stays off." if len(gone) == 1 and not back
                    else f"{speech.count_phrase(len(gone), 'other')} had already gone by and stayed off." if back
                    else f"All {len(gone)} had already gone by, so they stay off.")
    return " ".join(said)


def _one_reminder(which: str):
    """(schedule, why-not) — exactly one reminder he could mean.

    Same rule as `_one_task`: find it by the words he used, refuse to
    guess between two, and never silently pick the first.
    """
    from aletheia import speech
    needle = " ".join(str(which or "").split()).casefold()
    rows = _reminder_schedules()
    # "CANCEL MY 6:30 ALARM": with two alarms both saying "wake up", the
    # words cannot tell them apart and the clock can. Only a time that is
    # plainly a time - a colon or am/pm - so "the 5 minute timer" keeps its
    # five as a word.
    clock = re.search(r"(?:^|\s)(?:at )?(\d{1,2})(?::(\d{2}))?\s*(?:(a|p)\.?m\.?|o'?clock)(?=\s|$)"
                      r"|(?:^|\s)(?:at )?(\d{1,2}):(\d{2})(?=\s|$)", needle)
    if clock and rows:
        hour = int(clock.group(1) or clock.group(4))
        minute = int(clock.group(2) or clock.group(5) or 0)
        half = clock.group(3)
        if half == "p" and hour < 12:
            hour += 12
        elif half == "a" and hour == 12:
            hour = 0
        wanted = {f"{hour:02d}:{minute:02d}"}
        if not half and hour < 12:
            wanted.add(f"{hour + 12:02d}:{minute:02d}")
        rest = " ".join((needle[:clock.start()] + " " + needle[clock.end():]).split())
        timed = [r for r in rows if _reminder_clock(r) in wanted]
        if timed:
            if rest:
                worded = [r for r in timed if rest in text_of_reminder(r)]
                timed = worded or timed
            if len(timed) == 1:
                return timed[0], ""
            if not rest:
                # Two at 5 pm and "cancel the 5 o'clock reminder" said "None
                # of your reminders is about 5 o'clock" (2026-10-07) - naming
                # both. The clock is right and only the choice is left.
                timed = _soonest_first(timed)
                when = speech.clock_words(_reminder_clock(timed[0]) or "")
                labels = [str((r.get("command") or {}).get("text") or r["id"])[:50] for r in timed[:4]]
                return None, (f"You have {speech.count_phrase(len(timed), 'reminder')} at {when}: "
                              f"{speech.or_list(labels)}. Which one, or all of them?")
            rows = timed
            needle = rest
        else:
            return None, (f"You have nothing set for {speech.clock_words(sorted(wanted)[0])}. "
                          + _reminder_list_words(rows))

    def text_of(spec):
        return str((spec.get("command") or {}).get("text", "")).casefold()

    # "THE FIRST ONE", after she has just read them out in this order —
    # the same rule `_one_task` already holds, and the same reason: it is
    # how a person names a thing in a list they were just told. Checked
    # before the text match so a reminder whose words happen to contain
    # "first" cannot claim a sentence that is plainly counting.
    where = speech.ordinal_index(needle)
    if where is not None:
        try:
            return rows[where], ""
        except IndexError:
            return None, ("You have no reminders set." if not rows else "You only have "
                          + speech.count_phrase(len(rows), "reminder") + ".")

    # "CANCEL THAT REMINDER" right after setting it (2026-10-07: "None of
    # your reminders is about that", naming the one he had). "That" is the
    # newest one he set; the receipt names it, so a wrong pick is heard.
    if rows and re.fullmatch(r"(?:that|it|this|that one|this one|the last one|the one i just set|the reminder"
                             r"|that reminder|this reminder|the last reminder)", needle):
        return max(rows, key=lambda r: str(r.get("created_at") or "")), ""

    # "DELETE MY REMINDER" (2026-10-07: searched for a reminder about "my").
    # With one set, that is the one; with several, she asks which.
    if needle in ("my", "the", "my reminder", "a reminder", "one"):
        if len(rows) == 1:
            return rows[0], ""
        if rows:
            from aletheia import speech
            said = [_reminder_words(r) for r in _soonest_first(rows)[:4]]
            more = "" if len(rows) <= 4 else f" - or one of {len(rows) - 4} more"
            return None, f"You have {speech.count_phrase(len(rows), 'reminder')}. Which one: {speech.or_list(said)}{more}?"

    hits = [r for r in rows if needle and needle in text_of(r)]
    if not hits:
        words = [w for w in re.split(r"[^a-z0-9]+", needle)
                 if len(w) > 2 and w not in TASK_STOP and w != "reminder"]
        scored = [(sum(1 for w in words if w in text_of(r)), r) for r in rows]
        best = max((n for n, _r in scored), default=0)
        hits = [r for n, r in scored if n == best and n > 0]
    if not hits:
        if not rows:
            return None, "You have no reminders set."
        # AN EMPTY ANSWER STILL PROVES THE STORE. "No reminder matching
        # 'plumber'." is true, is two sentences jammed together once the
        # caller prefixes "I can't do that:", and leaves him with nothing
        # to say next. What he has IS the answer to what he asked.
        # A frame that is grammatical whichever way he phrased it: "cancel
        # the PLUMBER reminder" gives "plumber" and "cancel the reminder
        # about THE DENTIST" gives "the dentist", and "no reminder about
        # plumber" / "no the dentist reminder" is wrong one way or the
        # other. This one takes either.
        return None, (f"None of your reminders is about {which}. "
                      + _reminder_list_words(rows))
    if len(hits) > 1:
        # Soonest first, the order a person would list them in - and the
        # order "the first one" counts in when he answers.
        hits = _soonest_first(hits)
        labels = [str((r.get("command") or {}).get("text") or r["id"])[:50] for r in hits[:4]]
        if len(set(labels)) < len(labels):
            # "Which one - wake up or wake up?" names nothing he can choose
            # between; when the words are the same, the time is the name.
            labels = [_alarm_words(r) for r in hits[:4]]
        return None, "Which one — " + speech.or_list(labels) + "?"
    return hits[0], ""


def _texts_answer(who: str = "") -> str:
    """His recent texts on the Google Voice number, newest first, in words.

    "I can read texts that reach your Google Voice number" was offered
    for a month with no sentence that reached the reader, so "read my last
    text" went to a model that has never seen one.
    """
    from aletheia import gvoice, speech
    state, why = gvoice.check()
    if state == gvoice.NOT_SIGNED_IN:
        raise act.Refused("I'm not signed in to Google Voice in my browser yet. Sign in once on the PC "
                          "(python -m aletheia.browse login https://voice.google.com) and I'll keep it.")
    if state != gvoice.OK:
        raise act.Refused("I couldn't open your Google Voice texts just now.")
    rows = gvoice.recent()
    name = " ".join(str(who or "").split())
    if name:
        rows = [r for r in rows if name.casefold() in str(r.get("from") or "").casefold()]
    if not rows:
        # The parser reads the page's visible text; nothing parsed is not
        # proof nothing came, and saying "no texts" would be a guess.
        return (f"I don't see a text from {name} on your Google Voice page." if name
                else "I couldn't find any texts on your Google Voice page.")
    def one(row):
        body = str(row.get("text") or "").strip()
        return (f"{row.get('from')}, {row.get('when')}: {body}"
                + ("" if body.endswith((".", "?", "!")) else "."))
    lines = [one(r) for r in rows[:3]]
    if len(lines) == 1:
        return "Your last text is from " + lines[0]
    return (f"Your last {speech.count_phrase(len(lines), 'text')}, newest first. From "
            + " From ".join(lines))


def text_of_reminder(spec: dict) -> str:
    return str((spec.get("command") or {}).get("text", "")).casefold()


def _reminder_clock(spec: dict) -> str | None:
    """The local "HH:MM" a reminder goes off at, or None for an interval."""
    from aletheia import speech
    if spec.get("kind") == "once":
        try:
            at = dt.datetime.fromisoformat(str(spec.get("at") or "").replace("Z", "+00:00"))
        except ValueError:
            return None
        if at.tzinfo is not None:
            at = at.astimezone(speech._operator_zone() or None)
        return at.strftime("%H:%M")
    if spec.get("kind") in ("daily", "weekly", "monthly"):
        return str(spec.get("time") or "")[:5] or None
    return None


def _contact_words(contact: dict) -> str:
    """One contact, with whatever she actually has for them."""
    from aletheia import speech
    name = str(contact.get("display_name") or contact["id"])
    name = name[:1].upper() + name[1:]
    # "mia — 6055551234" was read out as a run of digits (2026-10-07).
    reach = [speech._spoken_number(str(v)) for v in list(contact.get("phones") or [])[:2] if v] \
        + [str(v) for v in list(contact.get("emails") or [])[:1] if v]
    return f"{name} — {speech.and_list(reach[:2])}" if reach else name


def _contacts_answer(which: str = "", asked: str = "") -> str:
    """"What's my mum's number" / "who have I got saved"."""
    from aletheia import contacts, speech
    rows = contacts.all_contacts()
    if which:
        # "what's MY MUM's number" — the possessive is his, the name is
        # hers, and a substring match on "my mum" finds a contact called
        # "Mum" never.
        needle = re.sub(r"^(my|our|the)\s+", "", which.casefold().strip())

        def names(contact):
            return [str(contact.get("display_name", "")).casefold(),
                    str(contact.get("id", "")).casefold(),
                    *[str(a).casefold() for a in (contact.get("aliases") or [])]]

        hits = [c for c in rows if any(needle in n for n in names(c) if n)]
        if not hits:
            words = [w for w in re.split(r"[^a-z0-9]+", needle)
                     if len(w) > 2 and w not in TASK_STOP]
            hits = [c for c in rows
                    if any(w in n for w in words for n in names(c) if n)]
        if not hits and re.match(r"(?:my|our)\s", which.casefold().strip()):
            # "What's my sister's number" with Dana saved and "my sister's
            # name is Dana" in his notes (2026-10-07: "no contact for 'my
            # sister'").
            try:
                from aletheia import quick
                named = quick._name_for_relation(which)
            except Exception:  # noqa: BLE001
                named = None
            if named:
                return _contacts_answer(named, asked)
        rows = hits
        if not rows:
            # "The plumber's number is 555 867 5309" kept as a NOTE, then
            # "what's the plumber's number" said she had none and asked him
            # to say exactly what he had said (2026-10-07). A note naming
            # them with a number or an address in it is the answer.
            try:
                from aletheia import quick as _q_note, speech as _sp_note
                wanted = [w for w in re.findall(r"[a-z0-9]+", needle) if w not in ("s", "the", "my", "our")]
                for note in _q_note._notes():
                    said = " ".join(str(note.get("text") or "").split())
                    low_said = said.casefold()
                    if wanted and all(re.search(rf"\b{re.escape(w)}", low_said) for w in wanted) \
                            and re.search(r"\b(?:number|phone|cell|mobile|email|e-mail)\b", low_said) \
                            and re.search(r"\d{3}|@", low_said):
                        return f"You told me: {_sp_note.as_she_says_it(said).rstrip('.')}."
            except Exception:  # noqa: BLE001 - the plain answer below still stands
                pass
            # "I have no contact for 'dana'." (2026-10-07): quotes and his
            # lower case read out, and nothing said how to fix it.
            who = " ".join(str(which).split())
            his = re.sub(r"^(?:my|our)\s+", "your ", who, flags=re.I)
            if who.islower() and not his.startswith("your ") and not re.match(r"the\s", who):
                his = who.title()
            says = re.sub(r"^your ", "my ", his)
            return (f"I don't have a number or email for {his} yet. "
                    f"Say \"{says}'s number is\" and the number, and I'll keep it.")
        if len(rows) == 1:
            # "What's Mia's number" is a question about one person: answered
            # as a sentence, not as a list of one.
            one = rows[0]
            name = str(one.get("display_name") or one["id"])
            name = name[:1].upper() + name[1:]
            phones = [speech._spoken_number(str(v)) for v in (one.get("phones") or []) if v]
            emails = [str(v) for v in (one.get("emails") or []) if v]
            # "What's my sister's email" answered with her NUMBER (2026-10-07):
            # asked for one of the two, that one first, or that it is missing.
            if asked == "email":
                return (f"{name}'s email is {emails[0]}." if emails
                        else f"I don't have an email for {name}" + (f" - only the number, {phones[0]}." if phones else ".")
                        + f" Say \"{name}'s email is\" and it, and I'll keep it.")
            if asked == "number":
                return (f"{name}'s number is {phones[0]}." if phones
                        else f"I don't have a number for {name}" + (f" - only the email, {emails[0]}." if emails else ".")
                        + f" Say \"{name}'s number is\" and it, and I'll keep it.")
            if phones and emails:
                return f"{name}'s number is {phones[0]}, and their email is {emails[0]}."
            if phones:
                return f"{name}'s number is {phones[0]}."
            if emails:
                # "What's Sam's email" was answered "I have an email for
                # Sam ... but no phone number" - the answer second (2026-10-07).
                return f"{name}'s email is {emails[0]}. I don't have a number for them."
            return f"I have {name} saved, but no number or email for them."
    if not rows:
        return "You have no contacts saved with me."
    said = speech.and_list([_contact_words(c) for c in rows[:6]])
    more = f", and {len(rows) - 6} more" if len(rows) > 6 else ""
    return f"{speech.count_phrase(len(rows), 'contact')}: {said}{more}."


def _watches_answer() -> str:
    """What she is waiting to tell him about."""
    from aletheia import events as bus, speech
    live = []
    for watcher in bus.list_watchers():
        try:
            if bus.watcher_state(watcher) != "ACTIVE":
                continue
        except Exception:
            continue
        note = str(watcher.get("note") or "").strip()
        # The note is written as "operator asked: tell me when ..." — the
        # half after the colon is the sentence.
        live.append((note.split(":", 1)[-1].strip() or watcher["id"])[:70])
    if not live:
        return "I'm not watching for anything at the moment."
    return (f"{speech.count_phrase(len(live), 'thing')} I'm watching for: "
            + speech.and_list(live[:5]) + ".")


def _one_notice(which: str = ""):
    """(notice, why-not) — the one he means by "that", or a question.

    With no words, the most recent UNREAD notice: "snooze THAT" always
    means the thing that just spoke.
    """
    from aletheia import notifications, speech
    rows = [n for n in notifications.all_notifications(state="UNREAD", limit=50)]
    if not rows:
        # "Snooze that" a turn after setting one (2026-10-08): nothing has
        # gone off, so say which is next and how to push it.
        try:
            from aletheia import quick
            nxt = next((r for r in quick._coming() if r[2] == "reminder"), None)
        except Exception:
            nxt = None
        if nxt:
            # An alarm is a "wake up" reminder underneath; he calls it his alarm.
            what = "your next alarm" if nxt[1].strip().casefold() == "wake up" else f"your next reminder, {nxt[1].rstrip('.')},"
            return None, (f"Nothing has gone off yet - {what} is "
                          f"{speech.humanize_time(nxt[0].isoformat())}. Say \"move it to\" and a time to push it.")
        return None, "Nothing is waiting to be snoozed."
    needle = " ".join(str(which or "").split()).casefold()
    if not needle or needle in ("that", "it", "this", "them"):
        return sorted(rows, key=lambda n: str(n.get("created_at", "")))[-1], ""

    def haystack(notice):
        return (str(notice.get("title", "")) + " "
                + str(notice.get("body", ""))).casefold()

    hits = [n for n in rows if needle in haystack(n)]
    if not hits:
        words = [w for w in re.split(r"[^a-z0-9]+", needle)
                 if len(w) > 2 and w not in TASK_STOP]
        scored = [(sum(1 for w in words if w in haystack(n)), n) for n in rows]
        best = max((c for c, _n in scored), default=0)
        hits = [n for c, n in scored if c == best and c > 0]
    if not hits:
        return None, f"Nothing waiting matches {which!r}."
    if len(hits) > 1:
        return None, ("Which one — "
                      + speech.or_list([str(n.get("body") or n["title"])[:50]
                                        for n in hits[:4]]) + "?")
    return hits[0], ""


def _applications_answer() -> str:
    """"What have I applied to" — from the application records."""
    from aletheia import apply_run, speech
    rows = apply_run.all_runs()
    # What today's looking FOUND, beside what was sent - the discovery summary
    # has a writer in the campaign and this is where he hears it.
    try:
        from aletheia import job_discovery
        found_today = job_discovery.today()
        found_line = job_discovery.spoken(found_today) if found_today else ""
    except Exception:
        found_line = ""
    if not rows:
        return " ".join(x for x in ("You haven't applied to anything through me yet.", found_line) if x)
    sent = [r for r in rows if r.get("state") == "SUBMITTED"]
    waiting = [r for r in rows if r.get("state") != "SUBMITTED"]

    def where(record):
        # the JOB, now that the campaign keeps it: "Account Executive at
        # Tebra", not the form's page title. An outcome he told her about
        # belongs with it - that is the difference between a list of things
        # he did and a record of where each one stands.
        said = apply_run.describe(record)[:60]
        outcome = str(record.get("outcome") or "")
        return f"{said} — {outcome}" if outcome else said

    parts = []
    if sent:
        parts.append(f"{speech.count_phrase(len(sent), 'application')} sent: "
                     + speech.and_list([where(r) for r in sent[-5:]]))
    if waiting:
        lead = ("and " if sent else "") + speech.count_phrase(
            len(waiting), "application")
        parts.append(f"{lead} staged and waiting on you: "
                     + speech.and_list([where(r) for r in waiting[-5:]]))
    # WHEN, said the way a person says it, and only once: a date inside every
    # item would put commas inside an and_list, which is unparseable by ear.
    newest = max(rows, key=lambda r: str(r.get("submitted_at") or r.get("staged_at") or ""))
    when = _day_words(newest.get("submitted_at") or newest.get("staged_at"))
    if when:
        parts.append(f"The most recent was {apply_run.describe(newest)[:60]} {when}")
    return ". ".join(parts) + "." + (f" {found_line}" if found_line else "")


def _day_words(stamp: object) -> str:
    """"today", "yesterday", "on 9 September" — never a timestamp out loud."""
    import datetime as _dt
    try:
        day = _dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        day = (day.astimezone(localtime.operator_tz()) if day.tzinfo else day).date()
    except (TypeError, ValueError):
        return ""
    today = localtime.today()
    if day == today:
        return "today"
    if (today - day).days == 1:
        return "yesterday"
    return "on " + f"{day.day} {day.strftime('%B')}"


SHOPPING_OPEN = ("RESEARCHING", "SELECTED", "PURCHASE_PROPOSED")


#: What "take everything off the list" is allowed to say.
SHOPPING_EVERYTHING = frozenset({"everything", "all", "all of it", "the whole list",
                                 "the lot", "it all", "the list"})


#: Things whose NAME has "and" in it. Short on purpose: anything not here
#: that is two single words ("milk and eggs") is two rows.
#: Things that are a whole item said as one word, for telling a spoken run
#: of them ("milk eggs and bread") from one thing with a long name.
GROCERY_WORDS = frozenset("""
milk eggs bread butter cheese yogurt cream coffee tea sugar flour salt pepper rice pasta
beans cereal oatmeal apples bananas oranges lemons limes grapes berries strawberries
blueberries avocados tomatoes potatoes onions garlic carrots lettuce spinach broccoli
celery cucumbers peppers mushrooms corn chicken beef pork bacon ham turkey sausage fish
salmon tuna shrimp tofu juice water soda beer wine chips crackers cookies honey jam
ketchup mustard mayo mayonnaise oil vinegar soap shampoo toothpaste deodorant detergent
napkins batteries foil diapers wipes razors lightbulbs nuts almonds peanuts popcorn
salsa hummus tortillas bagels muffins granola ice candy chocolate gum bleach sponges
""".split())

SHOPPING_ONE_THING = ("mac and cheese", "macaroni and cheese", "half and half", "fish and chips",
                      "salt and vinegar", "sweet and sour", "peanut butter and jelly",
                      "chips and salsa", "rice and beans", "pb and j", "pb&j")


def shopping_items_of(said: str) -> list[str]:
    """The things one sentence adds. "Milk and eggs" is two rows; "salt and
    vinegar chips" is one, because a side with a space in it is a name and
    not a list. A comma list is always a list. Never empty."""
    text = " ".join(str(said or "").split()).strip()
    if not text:
        return [text]
    # One dish with "and" in its name is one row, wherever it sits in a list:
    # "add mac and cheese" put "mac" and "cheese" on the list (2026-10-07).
    keep = {}
    for i, dish in enumerate(sorted(SHOPPING_ONE_THING, key=len, reverse=True)):
        hit = re.search(r"\b" + re.escape(dish) + r"\b", text, re.IGNORECASE)
        if hit:
            token = f"\x00{i}\x00"
            keep[token] = hit.group(0)
            text = text[:hit.start()] + token + text[hit.end():]
    if keep:
        def back(part):
            for token, dish in keep.items():
                part = part.replace(token, dish)
            return part
        return [back(p) for p in shopping_items_of(text)]
    if "," in text:
        parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", text) if p.strip()]
        return parts or [text]
    parts = [p.strip() for p in re.split(r"\s+(?:and|&)\s+", text) if p.strip()]
    # "Socks and a hat" is two things: an article is not part of the name
    # (2026-10-07: one row called "socks and a hat").
    if len(parts) >= 2 and all(" " not in re.sub(r"^(?:a|an|some|the|my) ", "", p, flags=re.IGNORECASE) for p in parts):
        return parts
    # "MILK EGGS AND BREAD": speech-to-text writes no commas, so a spoken
    # list arrives as words run together before its last "and". Split the
    # run only when every word in it is a thing on its own, and only before
    # the last "and" - "salt and vinegar chips" keeps its name.
    if len(parts) == 2 and " " not in parts[1] and parts[1].casefold() in GROCERY_WORDS:
        run = parts[0].split()
        if len(run) >= 2 and all(w.casefold() in GROCERY_WORDS for w in run):
            return run + [parts[1]]
    # "Paper towels and dish soap", "paper towels and milk" (2026-10-08: to
    # the planner as one thing): a name runs on AFTER its "and" ("salt and
    # vinegar chips"), so a side that is already two words before it ends.
    # Only a two-word side: "peanut butter eggs and bread" is not sure enough.
    if len(parts) >= 2 and len(re.sub(r"^(?:a|an|some|the|my) ", "", parts[0], flags=re.IGNORECASE).split()) == 2 \
            and all(len(p.split()) <= 3 for p in parts):
        return parts
    return [text]


def _shopping_items() -> list[dict]:
    from aletheia import shopping
    return [w for w in shopping.all_workflows()
            if str(w.get("state", "")).upper() in SHOPPING_OPEN]


def _mail_or_refuse(mail_mod) -> None:
    """Mail that is not set up is a REFUSAL, said with the setup words -
    not "That failed: ..." (bottom rung 2026-09-24). A draft is not gated
    here: it is held in her ledger whether or not the inbox is reachable."""
    ok, why = mail_mod.available()
    if not ok:
        raise act.Refused(str(why))


def _undo_answer(cmd: dict) -> str:
    """"Undo that": the newest thing she did on her own that can be taken
    back, or the one his words name. Only her own reversible acts; an
    outward one and a decision of his are refused by name (autonomy.undo).
    Bottom rung, 2026-09-24: "undo that" went to nobody."""
    from aletheia import autonomy, speech
    which = " ".join(str(cmd.get("which") or "").split()).casefold()
    # HIS OWN LAST ASK FIRST. "Add a task to call the plumber" then "undo
    # that" means the task, not the ledger of what she did unasked.
    if not which or which in ("that", "it", "the last thing", "the last one", "last"):
        taken = _undo_his_last_ask()
        if taken:
            return taken
    rows = [r for r in autonomy.recent(hours=48, limit=50)
            if not r.get("undone") and (r.get("undo") or {}).get("how") not in (None, autonomy.NONE)
            and not str(r.get("decided_by") or "").strip() and not autonomy.is_outward(r)]
    if which and which not in ("that", "it", "the last thing", "the last one", "last"):
        words = [w for w in re.findall(r"[a-z0-9']+", which) if len(w) > 2]
        rows = [r for r in rows if any(w in autonomy.said_line(r).casefold() for w in words)] or []
        if not rows:
            return f"I have nothing of my own to take back that matches {which}."
    if not rows:
        return ("Nothing to undo: I haven't done anything on my own in the last two days that I could "
                "take back.")
    row = rows[0]
    try:
        out = autonomy.undo(str(row["id"]), via="operator-via-intercom")
    except autonomy.UndoRefused as exc:
        return f"I can't take that one back: {speech.plainly(str(exc))}"
    said = str(out.get("said") or "").rstrip(".")
    return f"Undone: {said}." if out.get("undone") else str(out.get("said") or "Nothing changed.")


#: What he asks for by voice that can be taken straight back, by kind.
_TASK_LEAD = re.compile(
    r"^(?:call|phone|ring|email|text|message|write|pay|book|fix|send|check|finish|schedule|cancel|renew|"
    r"return|pick up|drop off|clean|wash|mow|file|submit|apply|follow up|chase|ask|tell|order|buy|get|"
    r"print|sign|read|review|update|install|set up|back up|look into|look up|talk to|meet|visit|water|take|make|do)\b")


def task_parts(description: str) -> list[str]:
    """"call mom, pay rent and buy stamps" -> the three things to do; one
    item when it is not plainly a list of separate things to do."""
    text = " ".join(str(description or "").split())
    if "," not in text and " and " not in text:
        return [text]
    parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", text) if p.strip()]
    if len(parts) < 2 or not all(_TASK_LEAD.match(p.casefold()) for p in parts):
        return [text]
    return parts


UNDOES_HIS_ASK = ("task_new", "shopping_add", "list_add", "remind_at", "remind_daily", "remind_weekly", "remind_monthly",
                  "remind_every",
                  "calendar_hold", "file_write", "note")


def _undo_his_last_ask() -> str | None:
    """Reverse the last thing HE asked for, read back from the thread and
    re-interpreted by the same deterministic layer that ran it: a task is
    cancelled, a list item taken off, a reminder switched off, a hold
    released, a written file put back. None when his last turn was not one
    of those (the caller then looks at her own unattended ledger)."""
    try:
        from aletheia import converse, voice
        turns = converse.recent(limit=4)
    except Exception:
        return None
    for turn in reversed(turns or []):
        said = " ".join(str(turn.get("he_asked") or "").split())
        if not said:
            continue
        try:
            command = (voice.interpret(f"thea {said}") or {}).get("command") or {}
        except Exception:
            return None
        kind = str(command.get("kind") or "")
        if kind == "undo":
            continue                        # his previous undo; look one further back
        # "Mark it done", then "undo that" (2026-10-08: "Nothing to undo").
        # A finished task never changes again, so it goes back on as itself.
        done = re.match(r"Done: (.+?)\.$", str(turn.get("she_answered") or "").strip())
        if done:
            what = done.group(1).strip()
            try:
                import time as _time
                slug = re.sub(r"[^a-z0-9]+", "-", what.casefold()).strip("-")[:32] or "task"
                execute_command({"kind": "task_new", "id": f"{slug}-{int(_time.time()) % 100000}",
                                 "description": what}, {}, quote="undo that")
            except act.Refused as exc:
                from aletheia import speech
                return f"I couldn't put {what} back on your list: {speech.plainly(str(exc))}"
            return f"Undone: {what} is back on your list."
        # A QUESTION in between changes nothing: "put lunch on Friday",
        # "who is it with", "cancel it" means the lunch (2026-10-07).
        # A note is journaled at the read-only tier, so it read as a question
        # here and "remember my locker is 42", "undo that" found nothing to
        # undo (2026-10-07). A kind this can reverse was never only asked.
        if kind not in UNDOES_HIS_ASK and voice._only_asked(said, command):
            continue
        # "Remove everything from the list", then "undo that" (2026-10-07:
        # "nothing to undo"). Taking things off is undone by putting back
        # the rows that turn cancelled - kept, not deleted, for this.
        # Deliberately not in UNDOES_HIS_ASK: "take that off the list"
        # after a removal must never put it back on.
        # By the answer, not the re-read: "remove milk" only reads as a
        # removal while milk is on the list, and now it isn't.
        if re.match(r"Took (?:it|\S+ things?) off (?:your|the) shopping list:", str(turn.get("she_answered") or "")):
            return _put_back_on_the_list(str(turn.get("she_answered") or ""))
        if kind not in UNDOES_HIS_ASK and str(turn.get("she_answered") or "").strip() == "Noted.":
            # "No, it's 24" was a note only in the light of the turn before
            # it, and reads as nothing on its own now. "Noted." is said for
            # a note and nothing else: the newest one is what it kept.
            newest = next(iter(_quick_notes()), None)
            if newest:
                kind, command = "note", {"kind": "note", "text": newest.get("text")}
        if kind not in UNDOES_HIS_ASK:
            return None
        if kind == "shopping_add" and "already on" in str(turn.get("she_answered") or "") \
                and "Added to" not in str(turn.get("she_answered") or ""):
            # "Add milk" with milk already there added nothing; undoing it
            # must not take off the milk he put there before.
            return "That added nothing - it was already on your shopping list, so I've left it there."
        return _reverse_his_ask(kind, command)
    return None


def _put_back_on_the_list(answer: str) -> str:
    """What the last removal took off the shopping list, put back: the
    things its answer named, and - past the six an answer names - the rows
    cancelled with them. Anything already back on the list is left alone."""
    import datetime as dt
    from aletheia import shopping, speech
    listed = re.sub(r"^Took (?:it|\S+ things?) off (?:your|the) shopping list: ", "", answer).rstrip(".")
    more = re.search(r", and \d+ more$", listed)
    listed = re.sub(r",? and \d+ more$", "", listed)
    names = [n.strip() for n in re.split(r", | and ", listed) if n.strip()]
    if more:
        now = dt.datetime.now(dt.timezone.utc)
        stamps = []
        for row in shopping.all_workflows():
            try:
                at = dt.datetime.fromisoformat(str(row.get("updated_at") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if row.get("state") == "CANCELLED" and (now - at).total_seconds() <= 900:
                stamps.append((at, str(row.get("need") or "").strip()))
        if stamps:
            newest = max(at for at, _n in stamps)
            names += [n for at, n in stamps if n and (newest - at).total_seconds() <= 5 and n not in names]
    open_now = {str(r.get("need") or "").strip().casefold() for r in _shopping_items()}
    back = [n for n in names if n.casefold() not in open_now]
    if not back:
        return "That's already back on the shopping list." if names else "I couldn't tell what came off the list to put it back."
    for need in back:
        execute_command({"kind": "shopping_add", "item": need}, {}, quote="undo that")
    return f"Undone: put {speech.and_list(back)} back on the shopping list."


def _reverse_his_ask(kind: str, command: dict) -> str:
    from aletheia import speech
    if kind == "task_new":
        from aletheia import tasks
        desc = str(command.get("description") or "").strip()
        parts = task_parts(desc) if not command.get("deadline") else [desc]
        gone = []
        for part in (parts if len(parts) > 1 else [desc]):
            match = [t for t in tasks.all_tasks()
                     if str(t.get("description") or "").strip().casefold() == part.casefold()
                     and t.get("status") not in ("DONE", "CANCELLED")]
            if match:
                tasks.set_status(match[-1]["id"], "CANCELLED", "undone: you took it back")
                gone.append(part)
        if not gone:
            return f"That task ({desc}) is already gone."
        if len(gone) > 1:
            return f"Undone: cancelled the tasks {speech.and_list(gone)}."
        return f"Undone: cancelled the task {gone[0]}."
    if kind == "list_add":
        from aletheia import lists
        name = str(command.get("list") or "")
        gone = []
        for item in shopping_items_of(str(command.get("item") or "")):
            taken, _why = lists.take_off(name, item)
            gone.extend(taken)
        if not gone:
            return f"I couldn't find that on your {name} list to take it back off."
        return f"Undone: took {speech.and_list(gone)} back off your {name} list."
    if kind == "shopping_add":
        item = str(command.get("item") or "").strip()
        try:
            execute_command({"kind": "shopping_off", "item": item}, {}, quote="undo that")
        except act.Refused as exc:
            return f"I couldn't take {item} off the list: {speech.plainly(str(exc))}"
        return f"Undone: took {item} back off the shopping list."
    if kind in ("remind_at", "remind_daily", "remind_weekly", "remind_monthly", "remind_every"):
        from aletheia import scheduler
        text = str(command.get("text") or "").strip()
        found, why = _one_reminder(text)
        if found is None:
            return f"I couldn't find that reminder to switch off: {speech.plainly(str(why))}"
        scheduler.set_enabled(found["id"], False)
        return f"Undone: the reminder to {text} is off."
    if kind == "calendar_hold":
        from aletheia import calendar_reasoning
        title, start = str(command.get("title") or ""), str(command.get("start") or "")
        try:
            calendar_reasoning.release_hold(calendar_reasoning.hold_id(title, start), why="undone: you took it back")
        except Exception as exc:  # noqa: BLE001
            return f"I couldn't release that hold: {speech.plainly(str(exc))}"
        return f"Undone: released the hold for {title}."
    if kind == "file_write":
        from aletheia import workspace
        path = str(command.get("path") or "")
        kept = workspace.versions(path)
        if len(kept) > 1:
            workspace.restore(kept[-1])
            return f"Undone: put back the version of {path} from before."
        workspace.remove(path, why="undone: you took it back")
        return f"Undone: removed {path}; a copy is kept if you want it back."
    if kind == "note":
        # The journal is append-only; a note is taken back with the same
        # tombstone "forget" writes, which every reader honours.
        text = " ".join(str(command.get("text") or "").split())
        newest = next((" ".join(str(r.get("text") or "").split()) for r in _quick_notes()
                       if " ".join(str(r.get("text") or "").split()).casefold() == text.casefold()), "")
        if not newest:
            return "That note is already gone."
        from aletheia import journal
        journal.append("note", FORGOTTEN_SUBJECT, newest[:300], actor="operator")
        return f"Undone: I've forgotten {speech.as_she_says_it(newest).rstrip('.')}."
    return "Nothing to undo."


def _quick_notes() -> list:
    try:
        from aletheia import quick
        return quick._notes()
    except Exception:  # noqa: BLE001
        return []


def free_time_answer(cmd: dict) -> str:
    """When he is free, as one sentence. Public because `quick` answers
    the same question from the same feed, and the sentence should be
    written in exactly one place."""
    import datetime as _dt
    from aletheia import calendar as cal
    tz = cmd.get("tz") or localtime.operator_timezone()
    minutes = int(cmd.get("minutes", 30))
    day = _dt.date.fromisoformat(cmd["day"])
    if cmd.get("at"):
        return _free_at(cal, day, str(cmd["at"]), minutes, tz)
    part = str(cmd.get("part") or "").strip().lower()
    if part in ("evening", "tonight", "night"):
        # "Am I free Friday evening" answered "nothing free - I only look at
        # your working hours" (2026-09-24): a question about the evening,
        # answered about the office. The evening is looked at as the evening.
        low, high = cal.DAY_PARTS.get("evening", (17, 22))
        slots = cal.free_slots(day, duration_minutes=minutes, timezone=tz,
                               work_start=_dt.time(low, 0), work_end=_dt.time(high, 0))
    else:
        slots = cal.free_slots(day, duration_minutes=minutes, timezone=tz)
    # HE SAID "AFTERNOON". Dropping the qualifier and answering about
    # the whole day answers a different question than the one asked,
    # and he has no way to tell that it happened.
    if part:
        slots = cal.in_part(slots, part)
    ranges = cal.merge_slots(slots)
    # "When's my next free hour" at 2:30 pm said "Free today 9 am to 5 pm"
    # (2026-10-07): the morning was already gone. Today starts now.
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        if day != now.astimezone(localtime.operator_tz()).date():
            raise ValueError("not today")
        kept = []
        for a, b in ranges:
            end = _dt.datetime.fromisoformat(b)
            if end.astimezone(_dt.timezone.utc) <= now + _dt.timedelta(minutes=minutes):
                continue
            begin = _dt.datetime.fromisoformat(a)
            if begin.astimezone(_dt.timezone.utc) < now:
                step = now.astimezone(begin.tzinfo)
                step = step.replace(second=0, microsecond=0) + _dt.timedelta(minutes=(15 - step.minute % 15) % 15)
                a = step.isoformat()
            kept.append((a, b))
        # "Am I busy today" at 5 pm with nothing on the calendar said
        # "Nothing free today" (2026-10-07): the working hours were over,
        # not filled. Then the rest of the evening is the answer.
        if ranges and not kept and not part:
            later = []
            for event in cal.all_events():
                if str(event.get("status") or "").upper() == "CANCELLED":
                    continue
                try:
                    start = cal.parse_time(event["start"])
                except (KeyError, TypeError, ValueError):
                    continue
                local = start.astimezone(localtime.operator_tz())
                if start > now and local.date() == day:
                    later.append((local, str(event.get("title") or "something")))
            if not later:
                return ("Your working hours are over and nothing else is on your calendar today - you're free."
                        + _nothing_on_it_at_all(cal, day))
            first = min(later)
            clock = first[0].strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
            return f"Your working hours are over. Still to come today: {first[1]} at {clock}."
        ranges = kept
    except (TypeError, ValueError):
        pass
    said = _free_sentence(ranges, day, part)
    # AN EMPTY CALENDAR AND THE WRONG CALENDAR GIVE THE SAME ANSWER.
    # "Free tomorrow afternoon 12 pm to 5 pm", said with no hedge, when
    # the connected feed holds ZERO events for two months in either
    # direction. His own setup audit already says this out loud — "'am I
    # free?' will answer yes to every hour. If that is wrong, the
    # schedule lives on a different calendar than the feed given" — and
    # the person who needs that sentence is not reading the audit, he is
    # standing in a room being told he is free.
    #
    # Only when it is COMPLETELY empty. A quiet week is a fact about his
    # week; nothing at all, ever, is a fact about the connection.
    return said + _nothing_on_it_at_all(cal, day)


def _free_at(cal, day, hhmm: str, minutes: int, tz: str) -> str:
    """"Am I free Friday at 10": yes or no for THAT time, and what is in it.

    Asked about one moment, it answers about that moment - not with the
    day's working-hours windows, which say nothing about 7 pm.
    """
    import datetime as _dt
    from zoneinfo import ZoneInfo
    hour, minute = map(int, hhmm.split(":"))
    start = _dt.datetime.combine(day, _dt.time(hour, minute), tzinfo=ZoneInfo(tz))
    end = start + _dt.timedelta(minutes=minutes)
    when = (start.strftime("%I:%M %p").lstrip("0").replace(":00", "").replace("AM", "am").replace("PM", "pm")
            + " on " + start.strftime("%A"))
    busy = cal.conflicts(start.isoformat(), end.isoformat())
    if busy:
        first = busy[0]
        title = str(first.get("title") or "something")
        # "You have meeting then" (2026-10-08): a bare noun takes its article.
        if re.fullmatch(r"(?:meeting|call|appointment|interview|lunch meeting|dentist appointment|doctor's appointment"
                        r"|doctor appointment|haircut|class|practice|game|session|event|hold)", title.casefold()):
            title = ("an " if title[0].casefold() in "aeiou" else "a ") + title
        return f"You have {title} then ({when})."
    # No "yes" or "no": "am I BUSY at 3" reaches here as the same command
    # as "am I free at 3", and "Yes, you're free" answered it backwards
    # (2026-10-07). The fact alone answers both.
    return f"You're free at {when}." + _nothing_on_it_at_all(cal, day)


#: How far either side of the day in question counts as "his calendar has
#: nothing on it at all". Wide enough that a genuinely quiet fortnight
#: does not trip it.
EMPTY_CALENDAR_DAYS = 45


def _nothing_on_it_at_all(cal, day) -> str:
    """The caveat, or nothing. Never raises: a hedge that breaks the
    sentence it hedges is worse than no hedge."""
    import datetime as _dt
    try:
        rows = cal.all_events()
    except Exception:
        return ""
    window = _dt.timedelta(days=EMPTY_CALENDAR_DAYS)
    for row in rows or []:
        stamp = str(row.get("start") or row.get("starts_at") or "")[:10]
        try:
            when = _dt.date.fromisoformat(stamp)
        except ValueError:
            # Unreadable is not empty. Say nothing rather than claim the
            # calendar is bare because one row would not parse.
            return ""
        if abs(when - day) <= window:
            return ""
    return (" Though there is nothing on your calendar at all for weeks "
            "either side, so if that sounds wrong, I may be reading a "
            "different calendar than the one you use.")


def _list_called(name: str) -> str:
    return "shopping list" if str(name).strip().casefold() == "shopping" else f"{name} list"


def _moved_off(cmd: dict) -> list[str]:
    """What came off the list it was moved FROM, once it is on the new one.
    Nothing raised: the add has already happened, and a line that was not
    on the old list is simply not said to have moved."""
    source = " ".join(str(cmd.get("moved_from") or "").split())
    if not source:
        return []
    try:
        if source.casefold() == "shopping":
            found, _why = _one_shopping_item(str(cmd["item"]))
            if found is None:
                return []
            from aletheia import shopping
            shopping.cancel(found["id"])
            return [str(found.get("need") or cmd["item"])]
        from aletheia import lists
        taken, _why = lists.take_off(source, str(cmd["item"]))
        return list(taken)
    except Exception:  # noqa: BLE001
        return []


def _named_list(kind: str, cmd: dict) -> str:
    """His own named lists, each answer a sentence."""
    from aletheia import lists
    name = " ".join(str(cmd.get("list") or "").split())
    if kind == "list_read" and not name:
        held = lists.all_lists()
        shopping = len(_shopping_items())
        # "What lists do I have" left out the one with the apples on it.
        also = f" And your shopping list has {speech.count_phrase(shopping, 'thing')}." if shopping else ""
        if not held:
            if shopping:
                return f"Just your shopping list, with {speech.count_phrase(shopping, 'thing')} on it."
            return "You don't have any lists of your own yet. Say \"make a list called packing\" to start one."
        return ("Your lists: " + speech.and_list(
            [f"{h['name']} ({speech.count_phrase(h['open'], 'thing') if h['open'] else 'empty'})" for h in held]) + "." + also)
    if not lists.is_named_list(name):
        raise act.Refused(f"{name or 'That'} isn't a list of its own - the shopping list, tasks and reminders "
                          "each have their own words.")
    if kind == "list_new":
        _held, new = lists.create(name)
        return (f"Started your {name} list." if new else f"You already have a {name} list.") + \
            f" Say \"add ... to my {name} list\"."
    if kind == "list_add":
        added = lists.add(name, shopping_items_of(str(cmd["item"])))
        moved = _moved_off(cmd)
        if moved:
            return f"Moved {speech.and_list(moved)} from your {_list_called(cmd['moved_from'])} to your {name} list."
        if not added:
            return f"That's already on your {name} list."
        # "a scarf for my sister" is read back as his: "for your sister" (2026-10-08)
        said_back = re.sub(r"\bmy\b", "your", speech.and_list(added))
        return f"Added to your {name} list: {said_back}."
    if kind == "list_off" and str(cmd["item"]).strip().lower() in ("the list", "the whole list", "the list itself"):
        had = lists.drop(name)
        if had is None:
            return f"You don't have a {name} list."
        return (f"Deleted your {name} list" + (f" and the {speech.count_phrase(had, 'thing')} on it" if had else "")
                + f". Say \"make a list called {name}\" to start it again.")
    if kind == "list_off":
        clearing = str(cmd["item"]).strip().lower() in SHOPPING_EVERYTHING
        taken, why = lists.take_off(name, str(cmd["item"]))
        if not taken:
            return f"Your {name} list is already empty." if clearing and lists.exists(name) else why
        if clearing:
            return f"Cleared your {name} list - {speech.count_phrase(len(taken), 'thing')} off it."
        return f"Took it off your {name} list: {speech.and_list(taken[:6])}" + \
            (f" and {len(taken) - 6} more." if len(taken) > 6 else ".")
    rows = lists.items(name)
    if rows is None:
        # "add ... to my packing list" starts one by itself (2026-10-08: the
        # sentence offered was a step he does not need).
        return f"Nothing's on a {name} list yet. Say \"add\" and what goes on it \"to my {name} list\", and I'll start one."
    if not rows:
        return f"Your {name} list is empty."
    # "Sunscreen and my charger" read his own words back as hers (2026-10-08).
    # Only a leading "my": a title ("I Am Legend") is never rewritten.
    shown = [re.sub(r"^[Mm]y ", "your ", str(r)) for r in rows[:10]] + ([f"{len(rows) - 10} more"] if len(rows) > 10 else [])
    return f"{speech.count_phrase(len(rows), 'thing')} on your {name} list: {speech.and_list(shown)}."


def shopping_answer() -> str:
    """His shopping list as one sentence. Public because `quick` answers
    "what's on my shopping list" from the same store, and the sentence
    should be written in exactly one place."""
    from aletheia import speech
    rows = _shopping_items()
    if not rows:
        return "Nothing on your shopping list."
    named = [str(w.get("need") or w["id"])[:60] for w in rows[:8]]
    # `and_list` already supplies the conjunction; appending ", and N more"
    # after it read "milk, eggs and bread, and 2 more". The overflow is
    # just the last item in the list.
    if len(rows) > 8:
        named.append(f"{len(rows) - 8} more")
    return (f"{speech.count_phrase(len(rows), 'thing')} on your shopping "
            f"list: {speech.and_list(named)}.")


def _one_shopping_item(which: str):
    """(workflow, why-not) — exactly one thing on the list he could mean."""
    from aletheia import speech
    needle = " ".join(str(which or "").split()).casefold()
    rows = _shopping_items()
    hits = [w for w in rows if needle and needle in str(w.get("need", "")).casefold()]
    if not hits:
        words = [w for w in re.split(r"[^a-z0-9]+", needle)
                 if len(w) > 2 and w not in TASK_STOP]
        scored = [(sum(1 for word in words
                       if word in str(w.get("need", "")).casefold()), w)
                  for w in rows]
        best = max((n for n, _w in scored), default=0)
        hits = [w for n, w in scored if n == best and n > 0]
    if not hits:
        return None, (f"Nothing on your shopping list matching {which!r}."
                      if rows else "Nothing on your shopping list.")
    # "Add milk" twice, then "I bought milk": "Which one — milk or milk?"
    # (2026-10-07). The thing named exactly is the one meant, and two
    # rows saying the same thing are one thing.
    exact = [w for w in hits if " ".join(str(w.get("need", "")).split()).casefold() == needle]
    if exact:
        hits = exact
    if len({" ".join(str(w.get("need", "")).split()).casefold() for w in hits}) == 1:
        return hits[0], ""
    if len(hits) > 1:
        return None, ("Which one — "
                      + speech.or_list([str(w.get("need") or w["id"])[:50]
                                        for w in hits[:4]]) + "?")
    return hits[0], ""


def _one_task(which: str):
    """(task, why-not) — exactly one open task he could mean, or a question.

    Refusing to guess between two is right; refusing to look one up by the
    words he used is not, and "mark the passport one done" is how anybody
    says it.
    """
    from aletheia import speech
    needle = " ".join(str(which or "").split()).casefold()
    rows = _open_tasks()
    # "THE FIRST ONE", after she has just read them out in this order.
    # Checked before the text match so a task whose words happen to
    # contain "first" cannot claim a sentence that is plainly counting.
    where = speech.ordinal_index(needle)
    if where is not None:
        try:
            return rows[where], ""
        except IndexError:
            # "There are only 0 things on your list" (2026-10-07).
            if not rows:
                return None, "Your list is empty."
            return None, (f"There {'is' if len(rows) == 1 else 'are'} only "
                          + speech.count_phrase(len(rows), "thing")
                          + " on your list.")
    # "THE OTHER ONE", after one of two was ticked off: with one task left
    # open, that is the one (2026-10-07: "Nothing open matching 'other'").
    if re.fullmatch(r"(?:the )?other(?: one)?", needle):
        if len(rows) == 1:
            return rows[0], ""
        if not rows:
            return None, "Nothing on your list is open."
        return None, ("Which one — " + speech.or_list([str(t.get("description") or t["id"])[:50]
                                                      for t in rows[:4]]) + "?")
    hits = [t for t in rows
            if needle and (needle in str(t.get("description", "")).casefold()
                           or needle in str(t.get("id", "")).casefold())]
    if not hits:
        # One word of his is enough to find it — "the passport one". Score
        # by how many of his CONTENT words a task contains and take the
        # best, because "the passport one" also contains "the" and "one",
        # and matching on those makes every task a candidate.
        words = [w for w in re.split(r"[^a-z0-9]+", needle)
                 if len(w) > 2 and w not in TASK_STOP]
        # Every word of his has to be in it: "I finished the budget report"
        # ticked off "ask Lisa about the budget" on "budget" alone
        # (2026-10-08), which is worse than not finding it. "Calling" is
        # still "call": a word counts with its ending taken off too.
        def _in(w, desc):
            return w in desc or any(len(d) >= 3 and w.startswith(d) and w[len(d):] in ("s", "es", "ed", "d", "ing", "ling", "ning")
                                    for d in re.split(r"[^a-z0-9]+", desc))
        scored = [(sum(1 for w in words
                       if _in(w, str(t.get("description", "")).casefold())), t)
                  for t in rows]
        best = max((n for n, _t in scored), default=0)
        hits = [t for n, t in scored if n == best and n > 0 and n == len(words)]
    if not hits:
        # "Nothing open matching 'call the vet'" read its quote marks out (2026-10-07).
        return None, f"Nothing on your list matches {str(which).strip()}."
    if len(hits) > 1:
        return None, ("Which one — "
                      + speech.or_list([str(t.get("description") or t["id"])[:50]
                                        for t in hits[:4]]) + "?")
    return hits[0], ""


def _jobs_answer(cmd: dict) -> str:
    """"How many jobs are open at Anthropic" / "find me react jobs in Austin".

    Both used to reach `research`, which drives a browser at the open web:
    ninety-four seconds to fail at a question the boards' own APIs answer in
    three. A role, a company, or neither — a bare company count needs no
    role at all, and demanding one is why the planner could not use this.
    """
    from aletheia import jobs as jobs_mod, speech
    role = str(cmd.get("role") or "").strip()
    company = str(cmd.get("company") or "").strip()
    where = str(cmd.get("where") or "").strip()
    count = max(1, min(int(cmd.get("count", 5)), 20))

    if company and not role:
        # A count for one employer: no search terms involved at all.
        wanted = [b for b in jobs_mod.boards()
                  if company.casefold() in str(b.get("company", "")).casefold()
                  or company.casefold() == str(b.get("token", "")).casefold()]
        if not wanted:
            return (f"I don't follow a board for {company} — "
                    f"{jobs_mod.BOARDS_PATH.name} is where they're listed, "
                    "and adding one is a line.")
        rows = []
        for board in wanted:
            try:
                provider = jobs_mod.PROVIDERS[board["provider"]]
                rows.append((board.get("company", board["token"]),
                             len(provider(board))))
            except Exception as exc:
                rows.append((board.get("company", board["token"]),
                             f"({type(exc).__name__})"))
        return speech.and_list(
            [f"{name}: {n} open" if isinstance(n, int) else f"{name}: {n}"
             for name, n in rows]) + "."

    if not role:
        return ("What kind of role? I search 36 company boards, so "
                "\"software engineer\" or \"designer\" narrows it.")

    found = jobs_mod.search(role, where=where, limit=count * 4)
    matches = found["matches"]
    if company:
        matches = [j for j in matches
                   if company.casefold() in j["company"].casefold()]
    if where:
        # HE NAMED A PLACE. `search` only PENALISES a mismatch, so "react
        # jobs in Austin" came back led by Toronto and San Francisco. A
        # ranking is not a filter, and naming a city he did not ask for is
        # the same defect as dropping "afternoon".
        place = where.casefold()
        matches = [j for j in matches
                   if place in j["location"].casefold()
                   or "remote" in j["location"].casefold()]
    if not matches:
        somewhere = f" in {where}" if where else ""
        at = f" at {company}" if company else ""
        return (f"Nothing open for {role}{at}{somewhere} on the "
                f"{found['searched']} boards I can apply to.")
    lines = [f"{j['company']}: {j['title']} ({j['location'][:60]})"
             for j in matches[:count]]
    where_said = f" in {where}" if where else ""
    head = (f"{speech.count_phrase(len(matches), 'match', 'matches')} for "
            f"{role}{where_said}.")
    failed = [f.get("company") or f["board"] for f in found["failed"]]
    tail = (f" ({speech.count_phrase(len(failed), 'board')} didn't answer.)"
            if failed else "")
    return f"{head} {'; '.join(lines)}.{tail}"


def _approval_words(approval, fallback_id: str) -> str:
    """What he just said yes to, in words rather than a hex id."""
    try:
        from aletheia import voice
        said = voice.approval_label(approval or {})
        if said:
            return said
    except Exception:
        pass
    return "the pending one"


def _free_sentence(ranges: list, day, part: str) -> str:
    """Availability as a person would say it.

    It used to answer "free on 2026-09-07 at 09:00, 09:15, 09:30, 09:45
    and more": a date nobody says out loud, followed by the first four
    fifteen-minute steps of the search that produced it. The stretches of
    free time are the answer; the steps are how they were computed. And
    when he asked about the AFTERNOON, the nine o'clock in that sentence
    was the giveaway that his qualifier had been dropped entirely.
    """
    import datetime as _dt
    from aletheia import speech

    def clock(stamp: str) -> str:
        moment = _dt.datetime.fromisoformat(stamp)
        text = moment.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
        return text.replace(" AM", " am").replace(" PM", " pm")

    # His noon, not the process's: a naive stamp was read against UTC, so
    # after 7 pm in Chicago tomorrow was "this morning" (2026-10-08).
    noon = _dt.datetime.combine(day, _dt.time(12, 0), tzinfo=localtime.operator_tz())
    when = speech.humanize_time(noon.isoformat()).split(" at ")[0]
    if part:
        # "today evening" is not English. Today takes "this"; every other
        # day keeps its name ("tomorrow afternoon", "Friday morning").
        # "Free this tonight" (2026-10-07): tonight already says which day.
        if part == "tonight":
            when = "tonight" if when == "today" else f"{when} night"
        else:
            when = f"this {part}" if when == "today" else f"{when} {part}"
    if not ranges:
        return f"Nothing free {when}."
    said = speech.and_list([f"{clock(a)} to {clock(b)}" for a, b in ranges[:3]])
    more = ", and a couple more" if len(ranges) > 3 else ""
    return f"Free {when} {said}{more}."


# A REHEARSAL, not a run. `talk --sandbox` moves every store somewhere
# throwaway — and moving a store does not stop an email leaving, a
# workflow dispatching, or a browser pressing Submit on a real site.
# Auditing her on his own machine would have SENT things, and the word
# "sandbox" says otherwise.
#
# An environment variable rather than an argument, because the refusal
# has to hold for every path underneath — the Core's beat, an approved
# intent running later, a plan step — not just the sentence that started
# it.
REHEARSAL = "ALETHEIA_REHEARSAL"

# Kinds that do not touch the world THEMSELVES — they compile a plan and
# run its steps back through this same function, where each one is
# checked on its own. Refusing the container would refuse the planner
# entirely, and then a rehearsal could only exercise the handful of
# sentences that happen to have a deterministic verb.
# `intent` compiles a plan and runs its steps back through here.
# `handle` only PERSISTS a request; the Core executes its candidate
# commands later, through this same function. Neither reaches the world
# itself. (`agenda` and `mission` are modules, not intercom kinds — the
# test below is what caught me listing them.)
#
# `approve` and `deny` are the same shape and were MISSING, which cost the
# audit its most important path: saying "approve" in a rehearsal answered
# "this is a rehearsal — approve is gated as world-touching", so the whole
# approve -> execute -> receipt loop could never be exercised at all, and
# the next question came back "No — that was a rehearsal, not a real
# save." Approving is a decision about a plan; the plan's steps then come
# back through here one at a time and a world-touching one is still
# refused. Nothing about who may approve changes — `approve` stays in
# PLANNER_FORBIDDEN, so she still cannot approve her own work.
CONTAINERS = frozenset({"intent", "handle", "approve", "deny"})


def rehearsing() -> bool:
    import os
    return os.environ.get(REHEARSAL, "").strip().lower() in ("1", "true", "yes")


WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday",
                 "saturday", "sunday")
WEEKDAY_WORDS = {name: n for n, name in enumerate(WEEKDAY_NAMES)}
WEEKDAY_WORDS.update({name[:3]: n for n, name in enumerate(WEEKDAY_NAMES)})
WEEKDAY_GROUPS = {"weekday": [0, 1, 2, 3, 4], "weekdays": [0, 1, 2, 3, 4],
                  "weekend": [5, 6], "weekends": [5, 6],
                  "day": list(range(7)), "everyday": list(range(7))}


def _weekday_numbers(days) -> list[int]:
    """Whatever he or the planner called the days -> [0..6], Monday first.

    Accepts the numbers, the words, the abbreviations and the two groups
    that are not days at all ("weekdays", "the weekend"). Refuses rather
    than guessing: a reminder on the wrong day is worse than none, and
    the caller can ask him again in one sentence.
    """
    if isinstance(days, (str, int)):
        days = [days]
    out: list[int] = []
    for day in list(days or []):
        if isinstance(day, bool):
            raise act.Refused(f"{day!r} is not a day of the week")
        if isinstance(day, int):
            if day not in range(7):
                raise act.Refused(f"{day} is not a day of the week (0-6)")
            out.append(day)
            continue
        word = str(day).strip().lower().rstrip(",.").lstrip("on ")
        if word in WEEKDAY_GROUPS:
            out.extend(WEEKDAY_GROUPS[word])
        elif word in WEEKDAY_WORDS:
            out.append(WEEKDAY_WORDS[word])
        else:
            raise act.Refused(f"{day!r} is not a day of the week")
    unique = sorted(set(out))
    if not unique:
        raise act.Refused("a weekly reminder needs at least one day")
    return unique


def _first_at(hhmm: str, tz: str | None = None, *, weekday: int | None = None) -> str:
    """The next HH:MM in his timezone (on that weekday, if one is given), as
    an ISO instant: where an every-N reminder starts counting from."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(tz or localtime.operator_timezone())
    now = _dt.datetime.now(zone)
    hour, minute = map(int, str(hhmm).split(":"))
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    while at <= now or (weekday is not None and at.weekday() != weekday):
        at += _dt.timedelta(days=1)
    return at.isoformat()


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _weekday_words(days: list[int]) -> str:
    """[0, 2] -> "Monday and Wednesday". Said out loud, so it is a phrase."""
    from aletheia import speech
    if days == [0, 1, 2, 3, 4]:
        return "weekdays"
    if days == [5, 6]:
        return "weekends"
    if len(days) == 7:
        return "every day"
    return speech.and_list([WEEKDAY_NAMES[d].capitalize() for d in days])


def _mission_command(kind: str, cmd: dict, quote: str) -> str:
    """His long missions (aletheia.programs), said and answered in sentences."""
    from aletheia import programs
    via = ACTOR
    words = " ".join(str(quote or "").split())[:300]
    if kind == "missions":
        if str(cmd.get("about") or "").strip().lower() == "waiting":
            return programs.spoken_waiting(cmd.get("which", ""))
        if str(cmd.get("about") or "").strip().lower() == "steps":
            return programs.spoken_steps(cmd.get("which", ""))
        return programs.spoken_status(cmd.get("which", ""))
    if kind == "mission_activity":
        made = programs.activity_due(cmd["mission"], cmd["activity"])
        return (f"started this round of {made['title']}" if made.get("made")
                else f"nothing to start: {made.get('why')}")
    if kind == "mission_new":
        record = programs.propose(cmd["objective"], via=via)
        return (f"Got it. I'll shape that into a mission - the outcomes, the workstreams and the "
                f"questions only you can answer - and bring the draft back before anything starts.")
    found = programs.find(cmd.get("mission", ""))
    if found is None:
        return "You don't have a long mission yet. Say start a mission, and what it is for."
    if kind == "mission_confirm":
        try:
            record = programs.confirm(found["id"], words=words or "confirm", via=via)
        except programs.ProgramError as exc:
            return f"Nothing to confirm: {exc}."
        live = sum(1 for t in record.get("tasks") or [] if t.get("state") == "READY")
        return (f"{record['title']} is on. {live} task{'s' if live != 1 else ''} can start now; "
                "anything that reaches another person still asks you first.")
    said = programs.add_words(found["id"], cmd["text"], via=via)
    became = said.get("became")
    if became == "decision":
        return f"Noted: {said['choice']}."
    if became == "answer":
        left = said.get("remaining", 0)
        return ("Thanks. " + (f"{left} more question{'s' if left != 1 else ''} before the draft is ready."
                              if left else "I'll redraft the mission with your answers."))
    if became == "retry":
        return f"Trying {said['task']} again."
    if became == "revision":
        return f"I'll draft that change to {found['title']} and check it with you before it takes effect."
    return f"Added to the draft of {found['title']}; I'll fold it in."


def _projects_answer() -> str:
    """Every kind of project he has, in one sentence.

    The charters she is carrying, the drafts waiting for his yes, what he
    asked for that is not drafted yet, and the private project records.
    Until 2026-09-10 this read only the private records, so "my projects"
    would have answered "No active projects" over four charters being
    built - a store with a writer and no reader, the defect CLAUDE.md names.
    """
    from aletheia import charters, projects
    parts = []
    charter_rows = [p for p in plans.all_plans() if plans.is_charter(p)]
    live = [p for p in charter_rows if p.get("state") == "open"]
    drafts = [p for p in charter_rows if p.get("state") == "proposed"]
    if live:
        parts.append("I'm carrying " + speech.and_list([
            f"{p['title']} ({plans.progress(p)[0]} of {plans.progress(p)[1]} steps done)"
            for p in live[:6]]))
    if drafts:
        parts.append("waiting for your yes: " + speech.and_list(
            [str(p["title"]) for p in drafts[:4]]))
    queued = charters.pending()
    if queued:
        parts.append("still to draft or apply: " + speech.and_list(
            [q.get("text") or q.get("project") or "one ask" for q in queued[:4]]))
    rows = [p for p in projects.all_projects()
            if str(p.get("status", "")).upper() not in ("DONE", "CANCELLED")]
    if rows:
        parts.append(f"{len(rows)} active: " + ", ".join(
            f"{p.get('title', p['id'])} ({str(p.get('status','')).lower()})"
            for p in rows[:5]))
    if not parts:
        return "No active projects."
    said = ". ".join(parts) + "."
    return said[0].upper() + said[1:]


def _carry_hold_reminders(old: dict, new: dict) -> int:
    """A reminder she set "the day before" a hold says the hold's time in
    its words ("dentist appointment Tuesday at 3 pm"). When the hold moves,
    the reminder moves the same distance and says the new time, or it
    would fire with the old one (2026-10-08). Returns how many moved."""
    import datetime as _dt
    import uuid as _uuid
    from aletheia import calendar as _calendar, scheduler

    def words(event, start):
        clock = start.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
        return f"{event.get('title')} {start.strftime('%A')} at {clock}"
    try:
        tz = localtime.operator_tz()
        was = _calendar.parse_time(old["start"]).astimezone(tz)
        now = _calendar.parse_time(new["start"]).astimezone(tz)
    except (KeyError, TypeError, ValueError):
        return 0
    if was == now:
        return 0
    said, moved = words(old, was), 0
    for spec in scheduler.all_schedules():
        command = spec.get("command") or {}
        if spec.get("kind") != "once" or not spec.get("enabled") or command.get("text") != said:
            continue
        try:
            at = _dt.datetime.fromisoformat(str(spec.get("at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=tz)
        when = at + (now - was)
        if when <= _dt.datetime.now(tz) or when >= now:
            continue
        scheduler.set_enabled(spec["id"], False)
        scheduler.create("remind-" + _uuid.uuid4().hex[:8], {**command, "text": words(new, now)},
                         kind="once", at=when.isoformat())
        moved += 1
    return moved


def execute_command(cmd: dict, fleet: dict, request=gh.request, quote: str = "") -> str:
    """Run one validated command. Returns a human-readable detail line.
    Raises act.Refused / ValueError / KeyError — the caller records them."""
    kind = cmd["kind"]
    if rehearsing() and tier(kind) == TIER_WORLD and kind not in CONTAINERS:
        # Everything local still runs, so the rehearsal exercises the real
        # planner, the real gates and the real stores. Only the last inch
        # into the world is withheld.
        # "reaches the world" was a claim about the KIND, and it is not
        # true of all of them: `email_draft` and `meet` are world-TIER
        # because of what they lead to, and themselves only write a local
        # file and stage an approval. The refusal says what it actually
        # knows — the tier — rather than asserting a mechanism it has not
        # checked. Whether those two belong in a lower tier is a registry
        # decision, not one to take inside a refusal.
        raise act.Refused(
            f"this is a rehearsal — {kind} is gated as world-touching, so it "
            "was not run. Everything local happened for real.")
    if kind == "preference_set":
        from aletheia import profile
        try:
            return profile.steer_by(cmd["field"], cmd["value"], quote=quote)
        except ValueError as exc:
            raise act.Refused(str(exc))
    if kind == "preferences":
        from aletheia import profile
        return profile.preferences_words()
    if kind == "note":
        journal.append("note", "operator", cmd["text"], actor=ACTOR)
        return "journaled"
    if kind == "dispatch":
        act.dispatch(fleet, cmd["repo"], cmd["workflow"], cmd.get("ref"), request=request)
        return f"dispatched {cmd['workflow']} on {cmd['repo']}"
    if kind == "issue":
        issue = act.file_issue(fleet, cmd["repo"], cmd["title"], cmd.get("body", ""), request=request)
        return f"filed issue #{(issue or {}).get('number', '?')} on {cmd['repo']}"
    if kind == "rule":
        suggestions.rule(cmd["id"], cmd["state"], cmd["because"], actor=ACTOR)
        return f"suggestion {cmd['id']} -> {cmd['state']}"
    if kind == "plan_new":
        plans.new_plan(cmd["slug"], cmd["title"], cmd["goal"])
        return f"plan {cmd['slug']} opened"
    if kind == "plan_add_step":
        plan = plans.add_step(cmd["slug"], cmd["text"], cmd.get("repo"))
        return f"plan {cmd['slug']} step {len(plan['steps'])} added"
    if kind == "plan_step":
        plans.set_step(cmd["slug"], int(cmd["n"]), cmd["state"])
        return f"plan {cmd['slug']} step {cmd['n']} -> {cmd['state']}"
    if kind == "plan_set":
        plans.set_plan(cmd["slug"], cmd["state"], cmd.get("because", ""))
        return f"plan {cmd['slug']} -> {cmd['state']}"
    if kind == "project_new":
        from aletheia import charters
        charters.ask("new", text=cmd["idea"], via=ACTOR)
        return (f"Got it. I'll draft {cmd['idea']} as a project and send it to "
                "your phone to say yes to, usually within half an hour.")
    if kind in ("project_step", "project_drop"):
        from aletheia import charters
        found, why = plans.find_charter(cmd["project"])
        if found is None:
            return why
        if kind == "project_step":
            charters.ask("step", text=cmd["text"], project=found["slug"], via=ACTOR)
            whose = "yours" if plans.infer_owner(cmd["text"]) == plans.CALEB else "mine"
            return (f"Adding to {found['title']}: {cmd['text']} ({whose}). "
                    "It'll be on the list within half an hour.")
        charters.ask("drop", project=found["slug"], via=ACTOR)
        return (f"Dropping {found['title']}. The builder will leave it alone "
                "within half an hour.")
    if kind in ("mission_new", "mission_add", "mission_confirm", "missions", "mission_activity"):
        return _mission_command(kind, cmd, quote)
    if kind == "work_projects":
        from aletheia import project_work
        minutes = None
        try:
            minutes = float(cmd["minutes"]) if cmd.get("minutes") not in (None, "") else None
        except (TypeError, ValueError):
            minutes = None
        return project_work.start(via=ACTOR, words=quote, minutes=minutes)["said"]
    if kind == "work_report":
        from aletheia import project_work
        return project_work.spoken_status(str(cmd.get("about") or ""))
    if kind in ("study_new", "studies", "study_decide", "study_confirm"):
        from aletheia import study_run
        return study_run.command(kind, cmd, quote=quote, via=ACTOR)
    if kind == "tasks":
        return _tasks_answer(cmd.get("which", ""))
    if kind == "task_done":
        from aletheia import tasks as tasks_mod
        found, why = _one_task(cmd["which"])
        if found is None and str(why).startswith("Nothing"):
            # "Mark milk done" with milk on the shopping list and no task
            # about it (2026-10-07): the thing he means is the one there.
            item, _not = _one_shopping_item(cmd["which"])
            if item is not None:
                execute_command({"kind": "shopping_off", "item": str(item.get("need") or "")}, fleet, quote=quote)
                return f"Took it off your shopping list: {item.get('need')}."
            # "I finished Dune" with Dune on his watch list (2026-10-07: it
            # stayed there, noted as if it were news). Only a line that IS
            # the thing he named - never a word inside another line.
            from aletheia import lists as lists_mod
            # "I finished reading Dune" is Dune (2026-10-08: it stayed on
            # his reading list).
            named = re.sub(r"^(?:reading|watching|listening to|playing) ", "", " ".join(str(cmd["which"]).split()), flags=re.I)
            wanted = re.sub(r"^(?:a|an|the|my) ", "", named.casefold())
            for held in lists_mod.all_lists():
                lines = lists_mod.items(held["name"]) or []
                if any(re.sub(r"^(?:a|an|the|my) ", "", " ".join(line.casefold().split())) == wanted for line in lines):
                    taken, _why = lists_mod.take_off(held["name"], named)
                    if taken:
                        return f"Nice - took it off your {held['name']} list: {speech.and_list(taken)}."
            # "I finished the report" with no task about it said "Nothing
            # open matching 'report'" and kept nothing (2026-10-07). Said as
            # a fact, it is kept as one, so "when did I finish" can answer.
            # The quote carries where it was said ("spoken to the wall: ..."):
            # his sentence is the part from "I" on.
            said = re.search(r"\b(?:i|i've|i have) (?:just )?(?:finished|done|did|completed|wrapped up)\b.*$",
                             " ".join(str(quote or "").split()), re.IGNORECASE)
            if said:
                execute_command({"kind": "note", "text": said.group(0).strip().strip('"')}, fleet, quote=quote)
                # "I finished Atomic Habits", a book he said he was reading,
                # got "that wasn't on your task list" (2026-10-08).
                try:
                    from aletheia import quick as _quick
                    title = re.escape(re.sub(r"^(?:reading|watching) ", "", " ".join(str(cmd["which"]).split()), flags=re.I))
                    was = next((m.group(1) for r in _quick._notes()[:40]
                                for m in [re.search(rf"\b(?:reading|watching|listening to|playing) ({title})\b",
                                                    " ".join(str(r.get("text") or "").split()), re.I)] if m), None)
                except Exception:
                    was = None
                if was:
                    return f"Nice - that's {was} finished. I've noted it."
                return "Nice. That wasn't on your task list, so I've noted it."
        if found is None:
            return why
        tasks_mod.set_status(found["id"], "COMPLETED",
                             note=f"marked done: {quote[:120]}")
        return f"marked done — {found.get('description') or found['id']}"
    if kind == "task_change":
        from aletheia import tasks as tasks_mod
        asked = [k for k in ("deadline", "description", "drop") if cmd.get(k)]
        if len(asked) != 1:
            raise act.Refused("Tell me one change at a time: a new day, a new name, or to drop it.")
        found, why = _one_task(cmd["which"])
        if found is None:
            return why
        what = found.get("description") or found["id"]
        if cmd.get("drop"):
            tasks_mod.set_status(found["id"], "CANCELLED", note=f"dropped: {quote[:120]}")
            return f"dropped — {what}"
        if cmd.get("description"):
            tasks_mod.describe(found["id"], str(cmd["description"]))
            return f"renamed — {what} -> {cmd['description']}"
        if tasks_mod.parse_deadline(cmd["deadline"]) is None:
            raise act.Refused(f"I couldn't read {cmd['deadline']!r} as a day.")
        made = tasks_mod.set_deadline(found["id"], str(cmd["deadline"]))
        return f"moved — {_task_words(made)}"
    if kind == "task_new" and len(task_parts(cmd["description"])) > 1 and not cmd.get("deadline"):
        # "Add call mom, pay rent and buy stamps to my to do list" was ONE
        # task with all three in it (2026-10-07). Each thing to do is its own.
        made_parts = []
        for part in task_parts(cmd["description"]):
            slug = re.sub(r"[^a-z0-9]+", "-", part.lower()).strip("-")[:40] or "task"
            taken = {t["id"] for t in tasks.all_tasks()}
            while slug in taken:
                slug = f"{slug}-2"
            tasks.create(slug, part, goal=cmd.get("goal"), assigned_worker=cmd.get("worker"))
            made_parts.append(part)
        return f"{len(made_parts)} tasks queued — {speech.and_list(made_parts)}"
    if kind == "task_new":
        # "Add a task to call mom" twice made two (2026-10-08), and the list
        # read "call mom and call mom". The same open task is one task.
        same = [t for t in tasks.all_tasks()
                if " ".join(str(t.get("description") or "").split()).casefold() == " ".join(str(cmd["description"]).split()).casefold()
                and t.get("status") not in ("DONE", "CANCELLED")
                and (not cmd.get("deadline") or t.get("deadline") == cmd.get("deadline"))]
        if same:
            return f"task {same[-1]['id']} already open — {_task_words(same[-1])}"
        made = tasks.create(cmd["id"], cmd["description"], goal=cmd.get("goal"),
                            assigned_worker=cmd.get("worker"),
                            deadline=cmd.get("deadline"))
        # The DEADLINE in the confirmation, because he just said one and
        # the whole point of a confirmation is that he can catch it being
        # wrong in one syllable.
        return f"task {cmd['id']} queued — {_task_words(made)}"
    if kind == "task_status":
        t = tasks.set_status(cmd["id"], cmd["state"], cmd.get("note", ""))
        return f"task {cmd['id']} -> {t['status']}"
    if kind == "halt":
        policy.halt(cmd.get("reason", ""), via=ACTOR)
        return "KILL SWITCH ON — nothing acts until resume"
    if kind == "resume":
        policy.resume(via=ACTOR)
        return "resumed"
    if kind == "update_now":
        from aletheia import core as _core
        ok, said = _core.request_update_now(cmd.get("reason") or "asked through the intercom")
        if not ok and said.startswith("nothing is running"):
            raise act.Refused(said)
        return said
    if kind == "restart":
        from aletheia import core as _core
        if not _core.request_restart(cmd.get("reason") or "asked through the intercom"):
            raise act.Refused("nothing is running that could restart - start her from the PC")
        return "restarting - back in about a minute"
    if kind == "close":
        from aletheia import closed
        closed.close(cmd.get("reason", ""))
        return ("closing — the Core finishes what it is holding, the room "
                "stops listening, and I stay shut until you open me")
    if kind == "open":
        from aletheia import closed
        if closed.open_again():
            return "open — I come back within five minutes"
        return "I was not closed"
    if kind == "running":
        from aletheia import running
        return running.headline(running.snapshot())
    if kind == "approve":
        # "approval intent-0a06bbb663 -> APPROVED" was the receipt, and the
        # room heard "approval -> APPROVED" once the id was stripped: an
        # arrow, out loud, saying nothing about WHAT he just authorised.
        decided = policy.decide(cmd["id"], "APPROVED", via=ACTOR)
        return f"approved — {_approval_words(decided, cmd['id'])}"
    if kind == "deny":
        decided = policy.decide(cmd["id"], "DENIED", via=ACTOR,
                                because=cmd.get("because", ""))
        return f"denied — {_approval_words(decided, cmd['id'])}"
    if kind == "remember":
        from aletheia import memory
        memory.remember(cmd["domain"], cmd["key"], cmd["value"],
                        source=f"operator via intercom: {quote[:120]}",
                        kind=cmd.get("memory_kind", "explicit"))
        return f"remembered {cmd['domain']}.{cmd['key']}"
    if kind == "forget":
        # `speech` is NOT imported here. It is a module-level name, and an
        # import of it anywhere in this function makes it LOCAL to the whole
        # function: every earlier branch that says `speech.` (computer_do,
        # among others) then raised UnboundLocalError. Found by the full suite.
        from aletheia import memory
        about = " ".join(str(cmd.get("about") or "").split())
        # "Forget that my boss is Karen" (2026-10-08): "that" introduces it.
        about = re.sub(r"^that (?=(?:my|our|the|i|i'm|we)\b)", "", about, flags=re.IGNORECASE)
        about = _what_it_is_about(about, keep_whose=True)
        hits = _remembered_matching(about, cmd.get("domain"))
        if not hits:
            # A NOTE IS FORGETTABLE TOO. "Remember that my sister's name is
            # Dana" is kept as a note, "what's my sister's name" reads it
            # back, and "forget my sister's name" said she had nothing
            # (2026-09-24). The journal is append-only, so a forgotten note
            # gets a tombstone line the readers honour.
            gone = _forget_note(about)
            if not gone:
                # "Forget the plumber note" (2026-10-07): "note" is what it
                # is, not what it says.
                bare = re.sub(r"^(?:the|my|that) |\s+(?:note|reminder|thing)s?$", "", about, flags=re.IGNORECASE).strip()
                gone = _forget_note(bare) if bare and bare != about else ""
            if gone:
                return f"Forgotten: {speech.as_she_says_it(gone)}."
            # AN EMPTY ANSWER STILL PROVES THE STORE, and here it matters
            # twice: "I forgot it" about something she never had would
            # leave him believing a fact is gone that is still there.
            known = _remembered_matching("", None)
            if not known:
                return f"I have nothing remembered about {about}."
            return (f"I have nothing remembered about {about}. "
                    f"What I do have is "
                    + speech.and_list([k for _d, k, _v in known[:6]])
                    + ("." if len(known) <= 6
                       else f", and {len(known) - 6} more."))
        if len(hits) > 1:
            return ("Which one - "
                    + speech.or_list([k for _d, k, _v in hits[:4]]) + "?")
        domain, key, value = hits[0]
        memory.forget(domain, key, via=f"operator via intercom: {quote[:80]}")
        # SAY WHAT WENT. "Forgotten" alone is unverifiable by ear, and
        # this is the one act in the system with no undo - `remember`
        # keeps what it replaced, and forgetting keeps nothing.
        return f"forgot {key} - it was {value}"
    if kind.startswith("media_"):
        from aletheia import media
        ok, why = media.available()
        if not ok:
            raise Unavailable(why)
        if kind == "media_probe":
            info = media.probe(cmd["source"])
            return (f"{info['seconds']:.1f}s, {info['bytes']:,} bytes, "
                    f"video={info['video']}, audio={info['audio']}")
        if kind == "media_trim":
            out = media.trim(cmd["source"], cmd["out"], start=cmd.get("start", "0"),
                             end=cmd.get("end"), duration=cmd.get("duration"))
        elif kind == "media_join":
            sources = cmd["sources"]
            if isinstance(sources, str):
                sources = [s.strip() for s in sources.split(",") if s.strip()]
            out = media.join(sources, cmd["out"])
        elif kind == "media_audio":
            out = media.extract_audio(cmd["source"], cmd["out"])
        elif kind == "media_captions":
            out = media.burn_subtitles(cmd["source"], cmd["subtitles"], cmd["out"])
        elif kind == "media_convert":
            height = cmd.get("height")
            out = media.convert(cmd["source"], cmd["out"],
                                height=int(height) if height is not None else None)
        else:
            # A bare `else` meant every future media kind landed in
            # `convert`: add "media_speed" to the grammar and she would
            # silently transcode instead, with a receipt saying she had
            # done it. Naming the last branch makes the drift a failure.
            raise ValueError(f"no handler for media kind {kind!r}")
        return (f"{out['what']} -> {out['path']} ({out['bytes']:,} bytes) "
                "— source untouched")

    if kind == "computer_observe":
        from aletheia import computer
        ok, why = computer.available()
        if not ok:
            raise Unavailable(why)
        window = cmd.get("window")
        steps = ([{"action": "inspect_controls", "window": {"title_re": re.escape(window)}}]
                 if window else [{"action": "list_windows"}])
        result = computer.observe(steps)
        found = result["steps"][0]["evidence"]
        rows = found.get("windows") or found.get("controls") or []
        names = [r.get("name") for r in rows if r.get("name")]
        head = (f"{found.get('count', len(rows))} "
                f"{'controls in ' + repr(window) if window else 'windows'}")
        return head + (": " + "; ".join(names[:25]) if names else "")

    if kind == "computer_do":
        from aletheia import computer
        ok, why = computer.available()
        if not ok:
            raise Unavailable(why)
        steps = _steps_of(cmd)
        result = computer.act(steps, requested_by=f"intercom: {quote[:80]}" if quote else "intercom")
        did = ", ".join(str(s.get("action")) for s in steps[:12])
        return (f"did {speech.count_phrase(result['steps_done'], 'desktop step')} "
                f"[{did}] — run {result['run_id']}"
                + (f" — {cmd['why'][:120]}" if cmd.get("why") else ""))

    if kind == "web_task":
        # THE GENERAL LOOP when there is a page to start from
        # (`browser_route.engine_for`); the older loop for a search or a
        # download. Same gates either way: spending refused, one hash-bound
        # approval at the committing button, every stop in the demand ledger.
        from aletheia import browser_route
        return browser_route.run(cmd["goal"], url=cmd.get("url", ""),
                                 budget=int(cmd.get("budget", 16)))
    if kind == "subscription_cancel":
        from aletheia import subscriptions, webtask
        if cmd.get("url"):
            subscriptions.set_url(cmd["subscription"], cmd["url"])
        row = subscriptions.start_cancellation(cmd["subscription"])
        if row.get("blocked_on"):
            return row["blocked_on"]
        try:
            return webtask.spoken(webtask.load_run(row["web_task"]))
        except Exception:
            return f"{row['merchant']}: {row.get('cancel_state', 'started')}"
    if kind == "web_task_answer":
        from aletheia import browser_route, webtask
        run_id = cmd.get("run_id") or ""
        mission = browser_route.waiting_mission(run_id)
        if mission is not None:
            given = cmd.get("answers") or {}
            if not isinstance(given, dict):
                return "answers must be a mapping of question to answer"
            return browser_route.answer(mission, given)
        if not run_id:
            waiting = [r for r in webtask.all_runs()
                       if r.get("state") in webtask.PICKABLE]
            if not waiting:
                return "nothing of mine is waiting on you"
            run_id = waiting[-1]["id"]
        given = cmd.get("answers") or {}
        if not isinstance(given, dict):
            return "answers must be a mapping of question to answer"
        return webtask.spoken(webtask.carry_on(run_id, answers=given))
    if kind == "web_task_retry":
        # The site refused it. "Try that again" now means something: she
        # reads what it said, fixes it, and brings him a NEW confirmation.
        from aletheia import browser_route, webtask
        mission = browser_route.rejected_mission(cmd.get("run_id") or "")
        if mission is not None:
            return browser_route.retry(mission)
        if cmd.get("run_id"):
            record = webtask.retry(cmd["run_id"])
        else:
            refused = webtask.all_runs("REJECTED")
            if not refused:
                return "nothing was refused — there is nothing to try again"
            record = webtask.retry(refused[-1]["id"])
        return webtask.spoken(record)
    if kind == "apply_campaign":
        from aletheia import campaign
        # IN ITS OWN PROCESS. Ten real forms take far longer than a sentence
        # is waited on, so she starts it, says so, and tells him when the
        # applications are ready (campaign.start). A rehearsal starts
        # nothing: it would open real employer pages.
        if rehearsing():
            return ("This is a rehearsal, so I didn't start: a job search opens "
                    "real employer pages and fills real forms.")
        from aletheia import apply_forever
        lifted = apply_forever.resume_hunt(via=f"intercom: {quote[:80]}")
        started = campaign.start(cmd.get("role", ""), count=int(cmd.get("count", 5)),
                                 where=cmd.get("where", ""), resume=cmd.get("resume", ""))
        return ("Back on it. " if lifted else "") + campaign.started_words(started)
    if kind == "apply_pause":
        from aletheia import apply_forever, campaign
        held = apply_forever.pause(cmd.get("reason", ""), via=f"intercom: {quote[:80]}")
        running_batch = campaign.running()
        return ("Okay — no more applications until you say start applying"
                + (f" ({held['reason']})" if held.get("reason") else "")
                + (". The batch already running finishes first." if running_batch else "."))
    if kind == "apply_retry":
        from aletheia import apply_run
        if rehearsing():
            return "This is a rehearsal, so I didn't change any application."
        matches = [m for m in apply_run.find(cmd["which"]) if m.get("state") == "FAILED"] or apply_run.find(cmd["which"])
        if not matches:
            return f"I don't have an application matching {cmd['which']!r}."
        if len(matches) > 1:
            return ("More than one matches — "
                    + speech.or_list([apply_run.describe(m) for m in matches[:4]]) + "?")
        try:
            record = apply_run.retry(matches[0]["id"], via=ACTOR)
        except apply_run.ApplyError as exc:
            raise act.Refused(speech.plainly(str(exc)))
        return f"I'll try {apply_run.describe(record)} again on the next beat."
    if kind == "apply_outcome":
        from aletheia import apply_run
        matches = apply_run.find(cmd["which"])
        if not matches:
            return (f"I don't have an application matching {cmd['which']!r}. "
                    "Ask me what you have applied to and name it the way I say it.")
        if len(matches) > 1:
            return ("More than one matches — "
                    + speech.or_list([apply_run.describe(m) for m in matches[:4]]) + "?")
        record = apply_run.mark(matches[0]["id"], cmd["outcome"], note=cmd.get("note", ""))
        last = record["outcomes"][-1]
        return (f"Noted on {apply_run.describe(record)}: {last['outcome']}"
                + (f" — {last['note']}" if last["note"] else "") + ".")
    if kind == "apply_answer":
        from aletheia import campaign
        if rehearsing():
            return "This is a rehearsal, so I didn't change any application."
        return campaign.answer_words(campaign.start_answer(cmd["question"], cmd["answer"]))
    if kind == "apply_prepare":
        from aletheia import applications
        out = applications.prepare(
            cmd["role"], count=int(cmd.get("count", 5)),
            where=cmd.get("where", ""),
            # NOT "resume.md": that file was a fiction from a test, and live
            # 2026-09-11 the packet path died on it while `find_resume` was
            # sitting there able to find his actual resume.
            resume=cmd.get("resume", ""))
        return applications.spoken(out)
    if kind == "file_delete":
        from aletheia import workspace
        out = workspace.remove(cmd["path"], why=cmd.get("why", ""))
        return (f"deleted {cmd['path']}"
                + (f" — the previous version is kept as {out['kept']}"
                   if out.get("kept") else ""))
    if kind == "file_move":
        from aletheia import workspace
        out = workspace.move(cmd["path"], cmd["to"], why=cmd.get("why", ""))
        return (f"moved {cmd['path']} to {cmd['to']}"
                + (" — what was there is kept in the version history"
                   if out.get("replaced") else ""))
    if kind in ("file_write", "file_edit", "file_read", "file_list"):
        from aletheia import workspace
        if kind == "file_write":
            out = workspace.write(cmd["path"], cmd["text"], why=cmd.get("why", ""))
            # A sentence, not a receipt: "wrote notes.md (5 chars)" was read out.
            return (f"Wrote {out['path']} in my workspace"
                    + ("." if out["created"] else "; the previous version is kept."))
        if kind == "file_edit":
            out = workspace.edit(cmd["path"], cmd["find"], cmd["replace"],
                                 why=cmd.get("why", ""))
            return f"edited {out['path']} ({out['replacements']} change)"
        if kind == "file_read":
            want = str(cmd.get("path") or "")
            try:
                out = workspace.read(want, anywhere=bool(cmd.get("anywhere")))
            except Exception as exc:
                # A NAME IS NOT A PATH, and he only ever has the name. She
                # writes code into `<workspace>/code/`, then offered "say
                # read rename_files.py" — and reading it failed, because
                # the name resolves against the workspace ROOT. An OFFER
                # is a claim about ability. `file.find` is how she turns a
                # name into a path now; if it finds nothing, the original
                # refusal is the honest one and is what he hears.
                from aletheia import files as files_mod
                found = files_mod.newest(want)
                if not found:
                    raise
                out = workspace.read(found["path"], anywhere=True)
            # A PROGRAM IS NOT PROSE, on the way back either. Reciting
            # fifteen lines of Python is the same two minutes of nothing
            # that `codeblocks` exists to stop, arriving through the other
            # door — and "go through it" means what it does, not every
            # character of it. A .md or .txt is a document and is read.
            from aletheia import codeblocks
            name = str(out.get("path") or want).replace("\\", "/").split("/")[-1]
            if codeblocks.is_code(name):
                return codeblocks.describe(out["text"], name)
            return out["text"][:2000]
        rows = workspace.listing(cmd.get("subdir", ""))
        if not rows:
            # An empty store still proves the store: "(empty)" out loud is
            # a bare parenthesis, and it reads as "you have no files"
            # rather than "the directory I write into is new".
            # Said TO him, so first person: "her workspace" read out by her
            # is somebody else's (2026-10-07).
            where = cmd.get("subdir") or "my workspace"
            return (f"Nothing in {where} yet - that's the folder I write into, "
                    f"not where your own files are.")
        return ", ".join(r["path"] for r in rows[:40])

    if kind == "file_find":
        from aletheia import files as files_mod
        try:
            result = files_mod.search(str(cmd.get("query") or ""),
                                      place=str(cmd.get("place") or ""),
                                      since=str(cmd.get("since") or ""))
        except files_mod.FilesError as exc:
            # Said in English: this is read out in a room.
            return str(exc)
        return files_mod.spoken(result)

    if kind == "file_size":
        from aletheia import files as files_mod
        try:
            return files_mod.size_spoken(files_mod.folder_size(cmd["place"]))
        except files_mod.FilesError as exc:
            return str(exc)

    if kind == "research":
        from aletheia import research as research_mod
        report = research_mod.run(cmd["question"])
        return research_mod.spoken(report)

    if kind == "do_task":
        from aletheia import script
        result = script.run(cmd["request"], label=cmd.get("label") or "task")
        if result.get("state") == "AWAITING_YOU":
            # It wrote a program that DELETES. Saved, readable, run nothing.
            return result["say"]
        return f"{script.spoken(result)} [program: {result['program']}]"
    if kind == "browse_read":
        from aletheia import browse
        page = browse.read_page(cmd["url"])
        excerpt = " ".join(page["text"].split())[:1200]
        return f"read {page['url']} — {page['title'][:100]} :: {excerpt}"
    if kind == "email_check":
        from aletheia import mail
        _mail_or_refuse(mail)
        return mail.check_unread()
    if kind == "texts_read":
        return _texts_answer(str(cmd.get("who") or ""))
    if kind == "email_read":
        from aletheia import mail
        _mail_or_refuse(mail)
        message = mail.read_body(cmd["which"])
        body = " ".join(message["text"].split())[:1500] or "(no readable text)"
        return f"From {message['from']} — {message['subject']}: {body}"
    if kind == "email_draft":
        from aletheia import mail
        d = mail.draft(cmd["to"], cmd.get("subject", ""), cmd["body"],
                       requested_via=f"intercom: {quote[:80]}")
        return (f"draft to {d['to_name']} ready — {d['subject']!r}. "
                f"Approval {d['id']} is pending; approving it sends the email.")
    if kind == "thread_draft":
        from aletheia import conversations
        if not (str(cmd.get("about") or "").strip() or str(cmd.get("body") or "").strip()):
            raise act.Refused("say what the email should be about")
        thread = conversations.start(cmd["to"], about=cmd.get("about") or "", body=cmd.get("body"),
                                     subject=cmd.get("subject"), via=f"intercom: {quote[:80]}")
        return conversations.spoken(thread)
    if kind == "thread_status":
        from aletheia import conversations
        return conversations.status_words(cmd.get("which") or "")
    if kind == "thread_send":
        from aletheia import conversations
        try:
            thread = conversations.resolve_thread(cmd["thread"])
        except LookupError as exc:
            raise act.Refused(str(exc)) from None
        done = conversations.send_approved(only_thread=thread["id"])
        sent = [r for r in done if r.get("outcome") == "sent"]
        if sent:
            return f"Sent the email to {conversations._name(thread)}."
        waiting = next((r.get("detail") for r in done if r.get("detail")), "")
        return (f"Nothing went to {conversations._name(thread)}: "
                + (waiting or "no message there has your approval yet") + ".")
    if kind == "thread_followup":
        from aletheia import conversations
        try:
            thread = conversations.resolve_thread(cmd["thread"])
            return conversations.spoken(conversations.followup(thread["id"]))
        except (LookupError, conversations.ConversationError) as exc:
            raise act.Refused(str(exc)) from None
    if kind == "calendar_find_free":
        from aletheia import calendar_reasoning
        try:
            first, last = calendar_reasoning.window(cmd["when"])
        except ValueError as exc:
            raise act.Refused(str(exc)) from None
        minutes = int(cmd.get("minutes") or 60)
        slots = calendar_reasoning.find_free(first, last, minutes=minutes, location=cmd.get("location") or None,
                                             part=cmd.get("part") or None)
        said = calendar_reasoning.free_words(slots, first=first, last=last, purpose=cmd.get("purpose") or "")
        held = [h for h in calendar_reasoning.upcoming_holds()
                if first.isoformat() <= h["start"][:10] <= last.isoformat()]
        if held:
            said += " Pencilled in already: " + speech.and_list(
                [f"{h['title']} {calendar_reasoning.human(h['start'])}" for h in held[:3]]) + "."
        return said
    if kind == "hold_release":
        from aletheia import calendar as _calendar, calendar_reasoning
        event_id = calendar_reasoning.hold_id(cmd["title"], str(cmd["start"]))
        try:
            held = _calendar.load(event_id)
        except (OSError, ValueError):
            held = None
        if not held or held.get("status") == "CANCELLED":
            return f"hold none released — there's no hold for {cmd['title']} at that time"
        calendar_reasoning.release_hold(event_id, why="released: he cancelled it")
        return f"hold {event_id} released — {held.get('title')} {calendar_reasoning.human(held['start'])}"
    if kind == "calendar_hold":
        from aletheia import calendar_reasoning
        import datetime as _dt
        try:
            start = _dt.datetime.fromisoformat(str(cmd["start"]).replace("Z", "+00:00"))
        except ValueError:
            raise act.Refused(f"I couldn't read {cmd['start']!r} as a time") from None
        if start.tzinfo is None:
            start = start.replace(tzinfo=localtime.operator_tz())
        if cmd.get("end"):
            end = _dt.datetime.fromisoformat(str(cmd["end"]).replace("Z", "+00:00"))
            end = end if end.tzinfo else end.replace(tzinfo=localtime.operator_tz())
        else:
            end = start + _dt.timedelta(minutes=int(cmd.get("minutes") or 60))
        # "Make it 8": the hold he just made, moved. The old one is released
        # first (so it cannot clash with its own new time) and put back if
        # the new time is refused - he is never left with neither.
        old = None
        if cmd.get("replaces"):
            try:
                from aletheia import calendar as _calendar
                old_id = calendar_reasoning.hold_id(cmd.get("was_title") or cmd["title"], str(cmd["replaces"]),
                                                    cmd.get("thread") or "")
                old = _calendar.load(old_id)
                if old and old.get("status") != "CANCELLED":
                    calendar_reasoning.release_hold(old_id, why="moved: he gave it a new time")
                else:
                    old = None
            except Exception:  # noqa: BLE001
                old = None
        held = calendar_reasoning.hold(cmd["title"], start.isoformat(), end.isoformat(),
                                       location=cmd.get("location") or None, thread_id=cmd.get("thread") or "")
        if not held.get("event"):
            if old:
                calendar_reasoning.hold(cmd.get("was_title") or cmd["title"], str(old["start"]), str(old["end"]),
                                        location=old.get("location") or None, thread_id=cmd.get("thread") or "")
            raise act.Refused(f"I didn't pencil that in: {held.get('why')}")
        # "Block off 2 to 4" was confirmed as "at 2 pm" alone (2026-10-07):
        # a length he named is said back, so a wrong one is caught by ear.
        until = ""
        if cmd.get("minutes") and int(cmd["minutes"]) != 60:
            ends = calendar_reasoning.human(held["event"].get("end") or end.isoformat())
            until = f" until {ends.split(' at ', 1)[1]}" if " at " in ends else ""
        when = calendar_reasoning.human(held['event']['start'])
        if until and " at " in when:
            when = when.replace(" at ", " from ", 1)
        if old and cmd.get("was_title") and str(old.get("start")) == str(held["event"].get("start")):
            return (f"Renamed {cmd['was_title']} to {held['event']['title']}, {when}{until}, "
                    "tentative, on your calendar here only.")
        # The same hold said twice is already there (2026-10-08: "Pencilled in
        # dentist" twice read as two appointments).
        if not old and not held.get("created"):
            title = held["event"]["title"]
            return f"{title[:1].upper() + title[1:]} is already on your calendar, {when}{until}."
        carried = _carry_hold_reminders(old, held["event"]) if old else 0
        try:
            same_start = bool(old) and _dt.datetime.fromisoformat(str(old["start"]).replace("Z", "+00:00")) == \
                _dt.datetime.fromisoformat(str(held["event"]["start"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            same_start = False
        # "It's at Olive Garden", "make it 30 minutes" (2026-10-08) changed
        # where or how long, and were confirmed as "Moved ... to" a time
        # that had not moved.
        title = held["event"]["title"]
        if same_start and cmd.get("location") and cmd.get("location") != old.get("location"):
            return f"{title[:1].upper() + title[1:]} is at {cmd['location']}, {when}."
        if same_start and str(old.get("end")) != str(held["event"].get("end")):
            from aletheia import speech as _speech
            length = int((end - start).total_seconds() // 60)
            said = (_speech.count_phrase(length // 60, "hour") if length % 60 == 0 else
                    "an hour and a half" if length == 90 else _speech.count_phrase(length, "minute"))
            return f"{title[:1].upper() + title[1:]} is {said} now, {when}{until}."
        return (f"{'Moved' if old else 'Pencilled in'} {held['event']['title']} "
                f"{'to ' if old else ''}{when}{until}, "
                "tentative, on your calendar here only."
                + (" Your reminder moved with it." if carried == 1 else
                   f" Your {carried} reminders moved with it." if carried else ""))
    if kind == "calendar_propose":
        from aletheia import conversations
        try:
            thread = conversations.resolve_thread(cmd["thread"])
            after = conversations.propose_times(thread["id"], when=cmd.get("when") or "next week",
                                                minutes=int(cmd["minutes"]) if cmd.get("minutes") else None,
                                                location=cmd.get("location") or None)
        except (LookupError, ValueError) as exc:
            raise act.Refused(str(exc)) from None
        times = speech.or_list([s["human"] for s in after["scheduling"]["slots"]])
        return (f"I drafted a reply to {conversations._name(after)} offering {times}. "
                "It's waiting for your okay.")
    if kind == "music":
        from aletheia import music
        if cmd["action"] == "volume_set":
            try:
                return music.set_volume(int(cmd.get("level")))
            except (TypeError, ValueError):
                raise act.Refused("I need a number for the volume, nought to a hundred.") from None
        return music.control(cmd["action"])
    if kind == "chatgpt":
        from aletheia import second_opinion
        return second_opinion.spoken()
    if kind == "chatgpt_on":
        from aletheia import second_opinion
        hours = cmd.get("hours") or second_opinion.DEFAULT_HOURS
        second_opinion.grant(int(hours),
                             via=f"operator: {quote[:60]}" if quote else "operator")
        return second_opinion.spoken()
    if kind == "chatgpt_off":
        from aletheia import second_opinion
        second_opinion.revoke(via=f"operator: {quote[:60]}" if quote else "operator")
        return second_opinion.spoken()
    if kind == "mic":
        from aletheia import ears
        return ears.spoken()
    if kind == "fault_ack":
        from aletheia import faults
        if rehearsing():
            return "This is a rehearsal, so I didn't mark anything handled."
        try:
            return faults.ack(cmd["repo"], quote=quote)
        except ValueError as exc:
            raise act.Refused(str(exc))
    if kind == "mission_leave":
        from aletheia import apply_run, browser_mission
        if rehearsing():
            return "This is a rehearsal, so I didn't clear anything."
        which = str(cmd["which"] or "").strip()
        if which.startswith("browser:"):
            which = which[len("browser:"):]
        try:
            record = browser_mission.leave(which, "you cleared it", via=ACTOR)
        except KeyError:
            raise act.Refused(f"I don't have a browser mission matching {which!r}.")
        try:
            apply_run.close_left_missions([record])
        except Exception:
            pass
        goal = " ".join(str(record.get("goal") or which).split())[:80]
        return f"Cleared. I've left {goal}; nothing more happens on it."
    if kind == "open_page":
        from aletheia import open_it
        if rehearsing():
            return "This is a rehearsal, so I didn't open anything."
        try:
            opened = open_it.open_for(cmd["which"])
        except open_it.NothingToOpen as exc:
            raise act.Refused(str(exc))
        return opened["said"]
    if kind == "mic_on":
        from aletheia import ears
        ears.turn_on(via=f"command centre: {quote[:60]}" if quote else "command centre")
        # A BUTTON DOES THE THING. Setting the flag and starting nothing
        # would have him press MIC, hear silence, and conclude it is
        # broken — on a machine where the listener is not already up,
        # which is every machine now that it does not start itself.
        started, detail = ears.start_room()
        if not started:
            return ("The microphone is on, but I could not start the "
                    f"listener — {detail}. Nothing is listening yet.")
        return ("The microphone is on. It closes when she closes or the "
                "machine restarts — it never comes back by itself.")
    if kind == "mic_off":
        from aletheia import ears
        ears.turn_off(via=f"voice: {quote[:60]}" if quote else "operator")
        ears.stop_room()
        return "The microphone is off. Nothing is listening."
    if kind == "agents":
        from aletheia import agents
        return agents.spoken_roster()
    if kind == "agent_stop":
        from aletheia import agents
        which = str(cmd["which"]).strip()
        matches = [a for a in agents.all_agents()
                   if a["status"] not in agents.FINISHED
                   and (which.casefold() in a["id"].casefold()
                        or which.casefold() in str(a.get("name", "")).casefold())]
        if not matches:
            return f"No worker called {which}."
        if len(matches) > 1:
            # `speech` is imported at module scope. A local `from ... import`
            # here would make the name local to this WHOLE function and
            # break every other branch that uses it — which is exactly
            # what it did to `computer_do`.
            return ("More than one matches — "
                    + speech.or_list([a["name"] for a in matches[:4]]) + "?")
        stopped = agents.kill(matches[0]["id"], why=f"by voice: {quote[:60]}")
        extra = len(stopped) - 1
        return (f"Stopped {matches[0]['name']}."
                + (f" And {extra} working under it." if extra else ""))
    if kind == "agents_pause":
        from aletheia import agents
        stopped = agents.kill_all(why=f"by voice: {quote[:60]}")
        if not stopped:
            return "Nothing was running."
        return f"Stopped {len(stopped)} worker{'s' if len(stopped) != 1 else ''}."
    if kind == "agent_new":
        from aletheia import agents
        made = agents.spawn(
            _agent_id(cmd["name"]), name=cmd["name"], mission=cmd["mission"],
            agent_type=cmd.get("agent_type", "project"),
            project=cmd.get("project", ""),
            # The starting scope is READ-ONLY on purpose. A worker created
            # by a sentence begins able to look and not to touch; widening
            # it is a separate decision, made once he knows what it is for.
            #
            # This said `grantable(READ_ONLY_KINDS)` first — intercom KINDS
            # where registry CAPABILITY IDS were wanted. Every id was
            # unknown, all of them were dropped, and the agent was created
            # holding nothing at all: safe by accident, meaningless on
            # purpose. `risk_class == "read"` is the registry's own word.
            capabilities=agents.reading_scope())
        return (f"{made['name']} exists — {made['mission'][:90]}. "
                f"It can read and nothing else until you widen it.")
    if kind == "doc_make":
        from aletheia import officedocs
        content = cmd["content"]
        if not isinstance(content, list) or not content:
            raise ValueError("content must be a non-empty list — blocks for a "
                             "document, rows for a spreadsheet")
        suffix = str(cmd["path"]).lower().rsplit(".", 1)[-1]
        if suffix == "pptx":
            # A dict is a slide with bullets; a bare string is a slide
            # that is only a title, which is what a planner produces for
            # a section break.
            slides = [c if isinstance(c, dict) else {"title": str(c)}
                      for c in content]
            made = officedocs.save(cmd["path"], slides=slides,
                                   why=cmd.get("why", ""))
        elif suffix == "xlsx":
            made = officedocs.save(cmd["path"], rows=content,
                                   sheet_name=cmd.get("sheet_name", "Sheet1"),
                                   why=cmd.get("why", ""))
        else:
            # A list of strings is a document of plain paragraphs, which
            # is what a planner produces when it has not been asked for
            # headings; a list of dicts carries styles.
            blocks = [b if isinstance(b, dict) else {"text": b} for b in content]
            made = officedocs.save(cmd["path"], blocks=blocks,
                                   why=cmd.get("why", ""))
        name = made["path"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        return (f"wrote {name} — {made['kind']}, "
                f"{made['bytes']} bytes, and it reads back correctly")
    if kind == "message_send":
        from aletheia import messages
        d = messages.draft(cmd["to"], cmd["body"],
                           requested_via=f"intercom: {quote[:80]}")
        # The number is not read back: he knows who Brant is, and a phone
        # number spoken aloud in a room is his to say, not hers.
        return (f"text to {d['to_name']} ready. Approval {d['id']} is "
                f"pending; approving it sends it from your phone.")
    if kind == "browse_shot":
        from aletheia import browse
        out = REPO_ROOT / "cache" / "browser-captures"
        out.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = out / f"shot-{stamp}.png"
        browse.screenshot(cmd["url"], target)
        # media never enters git — the capture stays on the PC, named here
        return f"screenshot of {cmd['url']} saved on the PC at {target}"
    if kind == "screen_record":
        from aletheia import screenrec
        try:
            out = screenrec.start(str(cmd.get("window") or ""), name=str(cmd.get("name") or ""),
                                  max_seconds=int(cmd.get("max_seconds") or screenrec.MAX_SECONDS))
        except (screenrec.RecordingError, ValueError) as exc:
            return f"I couldn't start recording - {exc}."
        if not out.get("started"):
            return (f"I'm already recording {out['already'].get('window')!r}; "
                    "say stop recording first.")
        return (f"Recording {out['window']!r} to {out['path']}. It stops by itself after "
                f"{out['max_seconds']} seconds, or when you say stop recording.")
    if kind == "screen_record_stop":
        from aletheia import screenrec
        out = screenrec.stop()
        if not out.get("stopped"):
            return "I'm not recording anything."
        length = f", {out['seconds']:.0f} seconds long" if out.get("seconds") else ""
        return f"Stopped. The video is at {out['path']}{length}."
    if kind == "recording":
        from aletheia import screenrec
        running = screenrec.current()
        if not running:
            return "I'm not recording anything."
        return (f"I'm recording {running.get('window')!r} to {running.get('path')}, "
                f"started {running.get('started_at')}.")
    if kind == "screenshot":
        from aletheia import screen
        wanted = str(cmd.get("monitor") or "active").strip().lower()
        if wanted not in screen.MONITORS:
            return (f"I can photograph the active screen, the primary one, "
                    f"or all of them - not {wanted!r}.")
        try:
            shot = screen.capture(monitor=wanted)
        except screen.ScreenUnavailable as exc:
            # Said in English: this sentence is read out in a room.
            return f"I couldn't take a screenshot - {exc}."
        out = REPO_ROOT / "cache" / "screen-captures"
        out.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = out / f"screen-{stamp}.png"
        target.write_bytes(shot.png)
        journal.append("action", ACTOR,
                       f"took a screenshot of the {wanted} screen "
                       f"({shot.width}x{shot.height}) -> {target}",
                       actor=ACTOR)
        # The NAME, not the path: a Windows path read out loud is unusable,
        # and the full location is in the journal line above.
        where = "your screen" if wanted == "active" else f"the {wanted} screen"
        return f"Took a screenshot of {where}. It's saved as {target.name}."
    if kind == "remind_at":
        from aletheia import scheduler
        import re as _re, uuid as _uuid
        moved = ""
        if cmd.get("replaces"):
            # "Make that 4": the old reminder goes off (never deleted) before
            # the new one is set, so he is not reminded twice.
            found, _why = _one_reminder(str(cmd["replaces"]))
            if found is not None:
                scheduler.set_enabled(found["id"], False)
                moved = " (moved)"
        else:
            # "Set an alarm for 6" twice made two 6 am alarms, and "cancel my
            # alarm" then asked "tomorrow at 6 am or tomorrow at 6 am?"
            # (2026-10-08). The same words at the same moment are one reminder.
            import datetime as _dt
            for spec in _reminder_schedules():
                try:
                    same = spec.get("kind") == "once" and _dt.datetime.fromisoformat(str(spec.get("at"))) == _dt.datetime.fromisoformat(str(cmd["at"]))
                except (TypeError, ValueError):
                    same = False
                if same and " ".join(str((spec.get("command") or {}).get("text") or "").split()).casefold() == " ".join(str(cmd["text"]).split()).casefold():
                    return f"reminder {spec.get('id')} set for {cmd['at']} — {cmd['text'][:80]!r} (already set)"
        sid = "remind-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="once", at=cmd["at"])
        return f"reminder {sid} set for {cmd['at']} — {cmd['text'][:80]!r}{moved}"
    if kind == "remind_daily" and cmd.get("every") not in (None, 1, "1"):
        # "EVERY OTHER DAY", "every 3 days": the interval kind, anchored at
        # the next time it comes round in his timezone.
        from aletheia import scheduler
        import uuid as _uuid
        every = int(cmd["every"])
        if not 2 <= every <= 90:
            raise act.Refused("I can repeat a reminder every 2 to 90 days.")
        sid = "remind-every-" + _uuid.uuid4().hex[:8]
        anchor = _first_at(cmd["time"], cmd.get("tz"))
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="interval", every_minutes=every * 1440, anchor=anchor)
        return f"reminder {sid} set every {every} days from {anchor} — {cmd['text'][:80]!r}"
    if kind == "remind_every":
        from aletheia import scheduler
        import datetime as _dt, uuid as _uuid
        minutes = int(cmd["minutes"])
        if not 15 <= minutes <= 720:
            raise act.Refused("I can repeat a reminder every 15 minutes to every 12 hours within the day.")
        if cmd.get("replaces"):
            # "Change it to every hour" (2026-10-08): the one he just set,
            # stopped (kept, so it can be put back) and set again.
            old, _why = _one_reminder(str(cmd["replaces"]))
            if old is not None and old.get("kind") == "interval":
                scheduler.set_enabled(old["id"], False)
        sid = "remind-every-" + _uuid.uuid4().hex[:8]
        anchor = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=minutes)).replace(microsecond=0)
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="interval", every_minutes=minutes, anchor=anchor.isoformat())
        return f"reminder {sid} set every {minutes} minutes from {anchor.isoformat()} — {cmd['text'][:80]!r}"
    if kind == "remind_monthly":
        from aletheia import scheduler
        import uuid as _uuid
        day = int(cmd["day"])
        if not 1 <= day <= 31:
            raise act.Refused("a day of the month is 1 to 31.")
        sid = "remind-monthly-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="monthly", timezone=cmd.get("tz") or localtime.operator_timezone(),
                         time=cmd["time"], monthday=day)
        return f"monthly reminder {sid} set for day {day} at {cmd['time']} — {cmd['text'][:80]!r}"
    if kind == "remind_daily":
        from aletheia import scheduler
        import uuid as _uuid
        moved = ""
        if cmd.get("replaces"):
            # "Change my pill reminder to 9": the daily one moves, and the
            # old time goes off (never deleted) so he is not reminded twice.
            found, _why = _one_reminder(str(cmd["replaces"]))
            if found is not None:
                scheduler.set_enabled(found["id"], False)
                moved = " (moved)"
        sid = "remind-daily-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="daily", timezone=cmd.get("tz") or localtime.operator_timezone(),
                         time=cmd["time"])
        return f"daily reminder {sid} set for {cmd['time']} — {cmd['text'][:80]!r}{moved}"
    if kind == "remind_weekly" and cmd.get("every") not in (None, 1, "1"):
        # "EVERY OTHER MONDAY", "every 2 weeks": one day, the interval kind.
        from aletheia import scheduler
        import uuid as _uuid
        every = int(cmd["every"])
        days = _weekday_numbers(cmd["days"])
        if len(days) != 1 or not 2 <= every <= 12:
            raise act.Refused("I can repeat a reminder every 2 to 12 weeks on one day.")
        sid = "remind-every-" + _uuid.uuid4().hex[:8]
        anchor = _first_at(cmd["time"], cmd.get("tz"), weekday=days[0])
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="interval", every_minutes=every * 10080, anchor=anchor)
        return (f"reminder {sid} set every {every} weeks on {_weekday_words(days)} "
                f"from {anchor} — {cmd['text'][:80]!r}")
    if kind == "remind_weekly":
        from aletheia import scheduler
        import uuid as _uuid
        days = _weekday_numbers(cmd["days"])
        if cmd.get("replaces"):
            # "Change my alarm to 6:15" with only a weekday alarm set
            # (2026-10-08): the old time goes off (never deleted).
            found, _why = _one_reminder(str(cmd["replaces"]))
            if found is not None and found.get("kind") == "weekly":
                scheduler.set_enabled(found["id"], False)
        sid = "remind-weekly-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="weekly",
                         timezone=cmd.get("tz") or localtime.operator_timezone(),
                         time=cmd["time"], weekdays=days)
        return (f"weekly reminder {sid} set for "
                f"{_weekday_words(days)} at {cmd['time']} — {cmd['text'][:80]!r}")
    if kind == "reminders":
        return _reminders_answer(cmd.get("which", ""))
    if kind == "reminder_on":
        return _reminder_back_on(str(cmd["which"]))
    if kind == "reminder_off":
        from aletheia import scheduler
        # "TURN OFF ALL MY ALARMS" - every one of that sort, each disabled
        # (never deleted), so each can be put back. Only the three sorts he
        # can name: alarms, timers, or everything that reminds him.
        every = {"all alarms": "wake up", "all timers": "timer is up", "all reminders": ""}.get(
            " ".join(str(cmd["which"]).casefold().split()))
        if every is not None:
            rows = [r for r in _reminder_schedules()
                    if every in str((r.get("command") or {}).get("text") or "").casefold()]
            if not rows:
                return f"reminder none off — you have no {cmd['which'][4:]} set"
            for row in rows:
                scheduler.set_enabled(row["id"], False)
            return (f"reminder {len(rows)} off — {speech.count_phrase(len(rows), cmd['which'][4:].rstrip('s'))}: "
                    + speech.and_list([_reminder_words(r) for r in rows[:4]]))
        # "All of them" to "2 reminders are at 5 pm ... Which one, or all of
        # them?": every reminder at that time, each disabled.
        at = re.fullmatch(r"all at (\d{2}:\d{2})", " ".join(str(cmd["which"]).split()))
        if at:
            rows = [r for r in _reminder_schedules() if _reminder_clock(r) == at.group(1)]
            if not rows:
                return f"reminder none off — you have nothing set for {speech.clock_words(at.group(1))}"
            for row in rows:
                scheduler.set_enabled(row["id"], False)
            return (f"reminder {len(rows)} off — {speech.count_phrase(len(rows), 'reminder')}: "
                    + speech.and_list([_reminder_words(r) for r in rows[:4]]))
        found, why = _one_reminder(cmd["which"])
        if found is None:
            raise act.Refused(why)
        if cmd.get("once"):
            return _skip_once(found, str(cmd["once"]))
        # DISABLED, never deleted: "actually put that back" has to be one
        # command, and a deleted schedule cannot be put back at all.
        scheduler.set_enabled(found["id"], False)
        return f"reminder {found['id']} off — {_reminder_words(found, receipt=True)}"
    if kind == "notify_snooze":
        from aletheia import notifications, scheduler
        import uuid as _uuid
        minutes = int(cmd["minutes"])
        if not 1 <= minutes <= 60 * 24 * 7:
            raise act.Refused("snooze it for anything from a minute to a week.")
        found, why = _one_notice(cmd.get("which", ""))
        hushed = ""
        if cmd.get("quiet"):
            from aletheia import announce
            until = announce.hush(minutes, via="operator")
            hushed = f"quiet until {until.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            if not announce.load_config().get("enabled"):
                hushed += " (speaking first is off anyway)"
            if found is None:
                return hushed
        if found is None:
            raise act.Refused(why)
        when = (dt.datetime.now(dt.timezone.utc)
                + dt.timedelta(minutes=minutes)).replace(microsecond=0)
        sid = "snooze-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator",
                               "text": found.get("body") or found["title"]},
                         kind="once", at=when.isoformat())
        # READ, not acknowledged: he has not dealt with it, he has
        # deferred it, and it is coming back to say so.
        notifications.set_state(found["id"], "READ")
        return (f"snoozed {sid} until {when.isoformat()} — "
                f"{(found.get('body') or found['title'])[:80]!r}") + (f"; {hushed}" if hushed else "")
    if kind == "notify_operator":
        from aletheia import notifications
        notice = notifications.publish("Reminder", cmd["text"], priority="IMPORTANT",
                                       about=notifications.NEEDS_YOU,
                                       source="reminder")
        return f"reminder surfaced: {notice['id']}"
    if kind == "watch_email_from":
        from aletheia import events as bus, mail as mail_mod
        # Not gated on mail being set up: a watch is a standing rule that
        # starts working the moment the inbox is reachable.
        addr, name = mail_mod.resolve_address(cmd["who"])
        if addr is None:
            return (f"I don't know an address for {name!r} — say "
                    f"'remember person {name} <their address>' first")
        watcher = bus.create_watcher(
            {"kind": "mail.received", "attributes": {"sender": addr.casefold()}},
            note=f"operator asked: tell me when email arrives from {name}",
            created_by="operator-voice", once=True)
        return f"watching for email from {name} — I'll tell you once ({watcher['id']})"
    if kind == "notify_check":
        from aletheia import notifications
        unread = notifications.all_notifications(state="UNREAD")
        if not unread:
            return "Nothing new."
        parts = [f"{n['title']}: {n['body'][:80]}" for n in unread[:5]]
        head = f"{len(unread)} notification{'s' if len(unread) != 1 else ''}. "
        return head + " — ".join(parts)
    if kind == "eyes":
        from aletheia import eyes
        return eyes.spoken()
    if kind == "eyes_on":
        from aletheia import eyes
        eyes.grant(int(cmd.get("hours") or eyes.DEFAULT_HOURS))
        return eyes.spoken()
    if kind == "eyes_off":
        from aletheia import eyes
        eyes.revoke()
        return ("I've stopped looking at the actual picture of your screen. "
                "I can still read what's on it as text.")
    if kind == "screen_ask":
        from aletheia import eyes, perception
        window = ({"title_re": re.escape(cmd["window"])} if cmd.get("window")
                  else None)
        if window is not None:
            # A question aimed at ONE named window is a question about
            # that window's controls, which is what the tree is for.
            return perception.describe(cmd["question"], window=window)["answer"]
        # The ladder: read it as text, and look at the picture only if
        # that genuinely could not answer and he has switched looking on.
        try:
            answer = eyes.answer(cmd["question"])
        except eyes.EyesUnavailable as exc:
            # "NotGranted: I couldn't read that from the screen text, and
            # looking at the actual picture is switched off" reached the
            # room with the class name in front (2026-09-24). A switch
            # that is off is a refusal, said in its own words.
            raise act.Refused(str(exc)) from None
        said = answer["answer"]
        if answer.get("could_look") is False:
            # Do not leave him wondering why she was vague.
            said += (" I couldn't tell from the screen text - if you want me "
                     "to look at the actual picture, say \"look at my screen\".")
        return said
    if kind == "intent":
        from aletheia import intents
        record = intents.propose(cmd["text"], quote=quote, fleet=fleet)
        return intents.spoken(record)
    if kind == "meet":
        from aletheia import scheduling
        import datetime as _dt, re as _re
        today = localtime.today()
        start = cmd.get("from_day") or today.isoformat()
        end = cmd.get("to_day") or (today + _dt.timedelta(days=7)).isoformat()
        slug = _re.sub(r"[^a-z0-9]+", "-", cmd["person"].lower()).strip("-")[:30]
        record = scheduling.start(
            f"meet-{slug}-{today.isoformat()}"[:60], cmd["person"],
            start_day=start, end_day=end, timezone=localtime.operator_timezone(),
            duration_minutes=int(cmd.get("minutes", 30)),
            purpose=cmd.get("purpose", ""))
        return scheduling.spoken(record)
    if kind == "recall":
        from aletheia import memory
        about = cmd["about"]
        found = []
        domains = [cmd["domain"]] if cmd.get("domain") else sorted(memory.DOMAINS)
        for domain in domains:
            try:
                value = memory.recall(domain, about)
            except Exception:
                value = None
            if value is not None:
                found.append(f"{domain}: {value}")
        if not found:
            # He says "what's my landlord's name"; it is stored under
            # "landlord". Exact key first, then the loose match `forget`
            # already uses, on key and value.
            loose = " ".join(str(about).split())
            loose = re.sub(r"'s (?:name|number|phone|email|address|birthday)$", "", loose,
                           flags=re.I).strip()
            for one, key, value in _remembered_matching(loose, cmd.get("domain"))[:4]:
                found.append(f"{one}: {key} is {value}")
        if not found:
            # "My sister's name is Jenna" is a NOTE, and "what do you know
            # about Jenna" read only the remembered facts and said there was
            # nothing (2026-10-07) - a store with a writer and no reader.
            # Her contacts and his notes are asked too.
            try:
                from aletheia import quick
                said = quick._who_named(str(about))
            except Exception:
                said = None
            if said:
                return said
            # "about my mom" is "about your mom" in her mouth (2026-10-07).
            return f"I don't have anything remembered about {re.sub(r'^my ', 'your ', str(about).strip())}."
        return "; ".join(found[:4])
    if kind == "brief":
        from aletheia import brief, journal as _j, pulse as _p
        import json as _json
        latest = _p.PULSE_DIR / "latest.json"
        current = _json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else {}
        if not current.get("repos"):
            # An unpulsed machine. It used to reach `compose` and raise a
            # bare KeyError, which he heard as "I couldn't: 'generated_at'".
            # No command out loud: the reading comes on its own, every few
            # hours, from the fleet's own workflow.
            # "Catch me up" with no fleet reading still has HIS day to tell
            # (2026-10-07: it said there was nothing to give).
            try:
                from aletheia import quick
                his_day = " ".join(x for x in (quick._waiting(), quick._plan_today()) if x)
            except Exception:
                his_day = ""
            if his_day:
                return his_day + " No fleet reading yet; one comes on its own within a few hours."
            return ("I haven't got a fleet reading yet, so there is no brief to "
                    "give you. One comes on its own within a few hours.")
        return brief.compose(current, brief.previous_pulse(current),
                             _j.since(24), 0)
    if kind == "handle":
        from aletheia import handler
        import uuid as _uuid
        request = handler.create(f"handle-{_uuid.uuid4().hex[:8]}", intent=cmd["text"])
        return (f"I'm on it: {request['intent'][:80]}. "
                f"State is {request['state'].lower().replace('_', ' ')}.")
    if kind == "place_add":
        from aletheia import places
        import re as _re
        name = " ".join(str(cmd["name"]).split())
        address = " ".join(str(cmd["address"]).split()).rstrip(".")
        pid = _re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "place"
        try:
            places.create(pid, name, address=address, provenance=f"operator via voice/intercom: {quote[:100]}")
        except FileExistsError:
            places.update(pid, address=address)
        return f"place {pid} saved — {name}: {address}"
    if kind == "travel_time":
        from aletheia import places
        try:
            try:
                destination = places.resolve(cmd["place"])
            except KeyError:
                # "how long to the gym" asks for "the gym"; he saved "gym".
                bare = re.sub(r"^(?:the|my|our) ", "", " ".join(str(cmd["place"]).casefold().split()))
                if bare == " ".join(str(cmd["place"]).casefold().split()):
                    raise
                destination = places.resolve(bare)
        except KeyError:
            # `KeyError: "no place matches 'airport'"` reached the room
            # verbatim, quotes and all. He cannot act on that; he can act
            # on being told to name the place once.
            place = str(cmd["place"])
            # "the chicago" (2026-10-07): a city is a NAME, and a name takes
            # its capitals and no article. Only an ordinary place noun - the
            # airport, the gym - is "the" one.
            try:
                from aletheia import quick as _quick
                common = set(_quick._COMMON_PLACES)
            except Exception:  # noqa: BLE001
                common = set()
            if place in ("work", "home", "school", "church"):
                named = place
            elif re.fullmatch(r"[a-z]+", place) and place in common:
                named = f"the {place}"
            elif re.fullmatch(r"[a-z][a-z .'-]*", place) and not re.match(r"(?:the|my|our|a|an) ", place):
                named = " ".join(w[:1].upper() + w[1:] for w in place.split())
            else:
                named = place
            # "How far is my mom's house" said "I don't know where my mom's
            # house is" one breath after "my mom lives at 12 Oak St"
            # (2026-10-07), and "how far is Kate's house" the same after
            # "Kate lives at 44 Pine St" (2026-10-08). Her words say "your",
            # and what he told her is offered back as the sentence that saves it.
            spoken = re.sub(r"^my ", "your ", named)
            whose = re.fullmatch(r"(my )?([a-z][a-z' ]{1,25}?)'s (?:house|place|home|apartment)", named, re.IGNORECASE)
            if whose:
                try:
                    from aletheia import quick as _quick
                    for row in _quick._notes():
                        told = re.fullmatch(r"(?:my )?" + re.escape(whose.group(2)) + r" lives (?:at|on) (.+?)\.?",
                                            " ".join(str(row.get("text") or "").split()), re.IGNORECASE)
                        if told:
                            owner, _, noun = named.partition("'s ")
                            say_it = f"{owner}'s {noun.casefold()}"
                            who = (f"your {whose.group(2)}" if whose.group(1)
                                   else whose.group(2)[:1].upper() + whose.group(2)[1:])
                            raise act.Refused(
                                f"You told me {who} lives at {told.group(1)}, but it isn't one of your "
                                f"saved places. Say \"{say_it} is at {told.group(1)}\" and I'll measure to it.") from None
                except act.Refused:
                    raise
                except Exception:  # noqa: BLE001
                    pass
            if named[:1].isupper() and named not in ("work", "home"):
                raise act.Refused(
                    f"I can only measure to places you've saved, and {named} isn't one. If it's somewhere "
                    f"you go, say \"{named} is at\" and the address, and I'll remember it.") from None
            raise act.Refused(
                f"I don't know where {spoken} is. Say \"{named} is at\" and the address, "
                "and I'll remember it.") from None
        except LookupError:
            raise act.Refused(
                f"More than one place answers to {cmd['place']!r} — which "
                "one do you mean?") from None
        said = places.called(destination["name"])
        where = (f"{said[:1].upper()}{said[1:]} is at {destination['address']}"
                 if destination.get("address") else f"I know {destination['name']}")
        try:
            home = places.resolve("home")
        except Exception:
            home = None
        observed = None
        if home:
            try:
                observed = places.travel_time(home["id"], destination["id"])
            except (ValueError, OSError):
                observed = None
        if not observed:
            # §104: never invent a duration. An unobserved trip is unknown,
            # but where it is is not, and that is half of what he asked.
            if not home:
                # "My address is 12 Oak Street" is kept as his address, not
                # as a place (2026-10-07), and this said there was no home
                # address one breath after he gave it.
                try:
                    from aletheia import memory as _memory
                    his = _memory.recall("identity", "address")
                except Exception:  # noqa: BLE001
                    his = None
                if his:
                    return f"{where}. I've never timed the trip from home, so I won't guess how long it takes."
                return f"{where}. I have no home address to measure from, so I won't guess how long it takes."
            return f"{where}. I've never timed the trip there, so I won't guess how long it takes."
        return (f"{destination['name']}: {observed.get('minutes', '?')} minutes "
                f"observed {observed.get('observed_at', 'previously')}.")
    if kind == "shopping_add":
        from aletheia import shopping
        import re as _re, uuid as _uuid
        budget = float(cmd["budget"]) if cmd.get("budget") else None
        # "Add eggs", then "no, I meant milk": the item he just added comes
        # off, and only when it really is on the list.
        swapped = ""
        if cmd.get("replaces"):
            try:
                execute_command({"kind": "shopping_off", "item": str(cmd["replaces"])}, fleet, quote=quote)
                swapped = str(cmd["replaces"])
            except Exception:  # noqa: BLE001
                swapped = ""
        added, already = [], []
        on_it = {" ".join(str(r.get("need", "")).split()).casefold() for r in _shopping_items()}
        for item in shopping_items_of(cmd["item"]):
            # "Add milk" with milk already on it made two milks (2026-10-07).
            if " ".join(item.split()).casefold() in on_it and not swapped:
                already.append(item)
                continue
            on_it.add(" ".join(item.split()).casefold())
            slug = _re.sub(r"[^a-z0-9]+", "-", item.lower()).strip("-")[:30]
            workflow = shopping.create(f"shop-{slug}-{_uuid.uuid4().hex[:4]}"[:60],
                                       need=item, budget=budget)
            added.append(str(workflow["need"]))
        if swapped:
            return f"Swapped {swapped} for {speech.and_list(added)} on the shopping list."
        if cmd.get("moved_from"):
            moved = _moved_off(cmd)
            if moved:
                return f"Moved {speech.and_list(moved)} from your {_list_called(cmd['moved_from'])} to the shopping list."
        if not added:
            return f"Already on your shopping list: {speech.and_list(already)}."
        return (f"Added to the shopping list: {speech.and_list(added)}."
                + (f" Already on it: {speech.and_list(already)}." if already else ""))
    if kind == "contacts":
        return _contacts_answer(cmd.get("which", ""), cmd.get("asked", ""))
    if kind == "watches":
        return _watches_answer()
    if kind == "drafts":
        from aletheia import mail
        return mail.held_drafts_words()
    if kind == "draft_discard":
        from aletheia import mail
        gone, why = mail.discard(str(cmd.get("which") or ""), via=ACTOR)
        if gone is None:
            raise act.Refused(why)
        return f"draft {gone['id']} discarded — {gone.get('subject')!r} to {gone.get('to_name') or gone.get('to')}"
    if kind == "applications":
        return _applications_answer()
    if kind == "shopping_list":
        return shopping_answer()
    if kind == "stopwatch":
        from aletheia import stopwatch
        return stopwatch.act(str(cmd["action"]))
    if kind == "stopwatch_read":
        from aletheia import stopwatch
        return stopwatch.spoken()
    if kind == "speaking_pace":
        from aletheia import speaking_pace
        return speaking_pace.act(str(cmd["action"]))
    if kind == "speaking_pace_read":
        from aletheia import speaking_pace
        return speaking_pace.spoken()
    if kind in ("list_new", "list_add", "list_read", "list_off"):
        return _named_list(kind, cmd)
    if kind == "shopping_off":
        from aletheia import shopping
        if str(cmd["item"]).casefold().strip() in SHOPPING_EVERYTHING:
            # "Clear the shopping list" planned two steps for two minutes on
            # her own model (2026-09-22). Every row is cancelled, not
            # deleted, the way one is.
            rows = _shopping_items()
            for row in rows:
                shopping.cancel(row["id"])
            if not rows:
                return "The shopping list was already empty."
            return (f"Took {speech.count_phrase(len(rows), 'thing')} off the shopping list: "
                    f"{speech.and_list([str(r.get('need', '')) for r in rows[:6]])}"
                    + (f", and {len(rows) - 6} more" if len(rows) > 6 else "") + ".")
        found, why = _one_shopping_item(cmd["item"])
        if found is None:
            raise act.Refused(why)
        shopping.cancel(found["id"])
        same = " ".join(str(found.get("need", "")).split()).casefold()
        for row in _shopping_items():
            if row.get("id") != found["id"] and " ".join(str(row.get("need", "")).split()).casefold() == same:
                shopping.cancel(row["id"])
        return f"shopping item {found['id']} off — {found['need']}"
    if kind == "subscriptions":
        from aletheia import subscriptions
        rows = subscriptions.all_subscriptions(active_only=True)
        if not rows:
            # "My Netflix is 15 a month" is a note (2026-10-07), and this
            # said "No subscriptions are being tracked" beside it - a
            # writer with no reader. What he told her is the answer.
            try:
                from aletheia import quick as _quick
                told = _quick._cost_mine("what are my bills")
            except Exception:  # noqa: BLE001
                told = None
            # "What bills are due" beside a task "pay the water bill, due
            # Friday" (2026-10-08): the bill on his list is a bill.
            bills = [t for t in _open_tasks() if re.search(r"\b(?:bills?|rent|mortgage|invoice|payment)\b",
                                                         str(t.get("description") or ""), re.IGNORECASE)]
            listed = ("On your list: " + speech.and_list([_task_words(t) for t in bills[:4]]) + ".") if bills else ""
            # "My Netflix renews on the 12th", "I cancelled Hulu" (2026-10-08:
            # "what subscriptions do I have" said none were tracked beside them).
            try:
                from aletheia import quick as _quick
                services = [line for line in _quick._said_lines(
                    r"\b(?:netflix|hulu|spotify|disney\+|disney plus|hbo|youtube (?:tv|premium)|amazon prime|prime video"
                    r"|apple (?:tv|music|one)|paramount\+?|peacock|audible|game pass|playstation plus|icloud)\b", 4)
                    if line.casefold() not in (told or "").casefold()]
            except Exception:  # noqa: BLE001
                services = []
            if services:
                said = "You told me: " + speech.and_list(services) + "."
                listed = said + (" " + listed if listed else "")
            if told:
                return ("I'm not tracking any subscriptions, but " + told[:1].lower() + told[1:]
                        + (" " + listed if listed else ""))
            if listed:
                return "I'm not tracking any subscriptions. " + listed
            return "No subscriptions are being tracked."
        monthly = [subscriptions.monthly_equivalent(r) for r in rows]
        total = sum(m for m in monthly if m)
        names = ", ".join(str(r.get("merchant", "?")) for r in rows[:5])
        return (f"{len(rows)} active: {names}."
                + (f" About {total:.2f} a month." if total else ""))
    if kind == "money":
        from aletheia import finance
        worth = finance.net_worth()
        pending = finance.handoffs()
        from aletheia import speech as _speech
        if not worth["accounts"]:
            # NOTHING IS CONNECTED, and "assets 0.00 across 0 accounts"
            # implies there are accounts and they are empty. An empty
            # store still proves the store - it says which of the two
            # this is, and what would change it.
            #
            # "A balance to give you" presumes the question. Spending
            # questions arrive here too now, and answering "I don't have a
            # balance" to "what did I spend this month" is the small
            # version of the same defect: an answer to a question he did
            # not ask.
            about = "spending" if cmd.get("about") == "spending" else "balance"
            said = (f"You haven't got any accounts recorded, so I have no "
                    f"{about} to report. There's no bank connected - "
                    f"I can only hold what you or I record.")
            if about == "spending":
                # The way to record it, said where he asked (2026-10-08).
                said = ("You haven't told me anything you spent, and there's no bank connected. "
                        "Tell me as you go - \"I spent 40 on gas\" - and I'll add it up.")
            if about == "balance":
                # "My checking account has 2400" is a note (2026-10-07), and
                # this said nothing was recorded one breath later.
                try:
                    from aletheia import quick as _quick
                    said = _quick.balances_told() or said
                except Exception:  # noqa: BLE001
                    pass
        else:
            said = (f"Assets {worth['assets']:,.2f}, liabilities "
                    f"{worth['liabilities']:,.2f}, net {worth['net']:,.2f} "
                    f"across "
                    f"{_speech.count_phrase(worth['accounts'], 'account')}.")
        if pending:
            said += (f" {_speech.count_phrase(len(pending), 'payment')} "
                     "waiting for you to authorize.")
        return said
    if kind == "car":
        from aletheia import vehicles
        rows = vehicles.all_vehicles()
        if cmd.get("vehicle"):
            wanted = cmd["vehicle"].lower()
            rows = [r for r in rows
                    if wanted in str(r.get("name", "")).lower() or wanted == r.get("id")]
        if not rows:
            return "No vehicle is being tracked yet."
        parts = []
        for row in rows[:3]:
            overdue = vehicles.due(row["id"])
            name = row.get("name") or row["id"]
            if overdue:
                what = ", ".join(str(d.get("description", "service"))[:40]
                                 for d in overdue[:3])
                parts.append(f"{name}: {what}")
            else:
                parts.append(f"{name}: nothing due")
        return "; ".join(parts)
    if kind == "projects":
        return _projects_answer()
    if kind == "setup_status":
        from aletheia import setup as _setup
        if cmd.get("about"):
            return _setup.spoken_about(str(cmd["about"]))
        return _setup.spoken()
    if kind == "authority_status":
        from aletheia import standing
        return standing.spoken()
    if kind == "compose":
        from aletheia import compose as composer
        sources = cmd.get("sources") or []
        if isinstance(sources, str):
            sources = [s.strip() for s in sources.split(",") if s.strip()]
        receipt = composer.compose(cmd["what"], cmd["path"],
                                   sources=list(sources), why=cmd.get("why", ""))
        return composer.spoken(receipt)
    if kind == "announce_set":
        from aletheia import announce
        on = cmd["on"]
        if isinstance(on, str):
            on = on.strip().lower() in ("true", "yes", "on", "1")
        announce.set_enabled(bool(on), via="operator-via-intercom")
        if cmd.get("quiet_from") and cmd.get("quiet_until"):
            announce.set_quiet_hours(cmd["quiet_from"], cmd["quiet_until"],
                                     via="operator-via-intercom")
        return announce.spoken()
    if kind == "undo":
        return _undo_answer(cmd)
    if kind == "instagram_post":
        from aletheia import instagram
        # (A rehearsal never reaches here: the world-tier gate above refuses
        # first, so a sandbox cannot post.)
        ready, why = instagram.available()
        if not ready:
            raise act.Refused(why)
        try:
            row = instagram.publish(cmd.get("media") or "",
                                    cmd.get("caption") or "",
                                    media_type=cmd.get("media_type") or "")
        except RuntimeError as exc:
            raise act.Refused(str(exc)) from None
        what = "a reel" if row.get("kind") == "REELS" else "a picture"
        first = str(row.get("caption") or "").splitlines()[0][:80] if row.get("caption") else ""
        return f"Posted {what} to Instagram" + (f": {first}" if first else ".")
    if kind == "instagram_posts":
        from aletheia import instagram
        return instagram.spoken_posts()
    if kind == "interview_window_set":
        from aletheia import interviews
        try:
            interviews.set_window(str(cmd["start"]), str(cmd["end"]), cmd.get("timezone") or None)
        except ValueError as exc:
            raise act.Refused(str(exc)) from None
        state = interviews.status()
        return (f"Interviews go {interviews.window_words(state['window'])} on weekdays now"
                + ("." if state["on"] else ", once booking is switched on."))
    if kind == "interview_status":
        from aletheia import interviews
        return interviews.spoken()
    if kind == "notify_clear":
        from aletheia import notifications
        unread = notifications.all_notifications(state="UNREAD")
        for n in unread:
            notifications.set_state(n["id"], "ACKNOWLEDGED")
        return f"cleared {len(unread)} notification{'s' if len(unread) != 1 else ''}"
    if kind == "jobs":
        return _jobs_answer(cmd)
    if kind == "free_time":
        return free_time_answer(cmd)
    if kind == "contact_remove":
        from aletheia import contacts
        rows = contacts.all_contacts()
        try:
            person = contacts.resolve(cmd["name"], rows)
        except (KeyError, ValueError):
            return f"contact none removed — you have no contact called {cmd['name']}"
        except LookupError:
            raise act.Refused(f"More than one contact answers to {cmd['name']} - which one?") from None
        contacts.update(person["id"], tags=sorted(set(person.get("tags") or []) | {contacts.REMOVED}))
        return f"contact {person['id']} removed — {person.get('display_name') or person['id']}"
    if kind == "contact_add":
        from aletheia import contacts, mail as mail_mod, messages as _messages
        import re as _re
        addr = phone = None
        if cmd.get("email"):
            addr, _ = mail_mod.resolve_address(cmd["email"])
            if addr is None or "@" not in addr:
                return (f"{cmd['email']} doesn't look like an email address to me. Say it like "
                        "\"sam at example dot com\" and I'll save it.")
        if cmd.get("phone"):
            phone = _messages.normalize_number(cmd["phone"])
            if not _messages.looks_like_a_number(phone):
                return (f"{cmd['phone']} doesn't look like a whole phone number. Say it with the area code, "
                        "like \"312 555 1234\", and I'll save it.")
        if not addr and not phone:
            # A contact she cannot reach is not a contact, and saying so
            # is better than storing a name that fails at send time.
            return (f"I need an email address or a phone number for "
                    f"{cmd['name']} before I can remember them.")
        cid = _re.sub(r"[^a-z0-9]+", "-", cmd["name"].lower()).strip("-") or "person"
        aliases = [cmd["alias"]] if cmd.get("alias") else []
        try:
            contacts.create(cid, cmd["name"].strip(),
                            emails=[addr] if addr else [],
                            phones=[phone] if phone else [],
                            aliases=aliases,
                            provenance=f"operator via voice/intercom: {quote[:100]}")
        except FileExistsError:
            # Taken out earlier and said again: back in, as he says it now.
            changes = {"tags": [t for t in (contacts.load(cid).get("tags") or []) if t != contacts.REMOVED]}
            if addr:
                changes["emails"] = [addr]
            if phone:
                changes["phones"] = [phone]
            contacts.update(cid, **changes)
        reached = " and ".join(x for x in (addr, phone) if x)
        return (f"remembered {cmd['name']} as {reached} — private contacts "
                "only, never the public repo")
    raise ValueError(f"unhandled kind {kind!r}")  # unreachable after validation


def _result_path(path: Path) -> Path:
    return path.with_name(path.stem + ".result.json")


def _peek_kind(path: Path) -> str | None:
    """The command's kind, or None when unreadable (side: cloud receipts those)."""
    try:
        c = json.loads(path.read_text(encoding="utf-8"))
        kind = c.get("command", {}).get("kind")
        return kind if isinstance(kind, str) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return None


def _on_side(path: Path, side: str) -> bool:
    kind = _peek_kind(path)
    if side == "local":
        return kind in LOCAL_KINDS
    # cloud takes everything else, including unreadable files (it owns the
    # invalid-receipt path so garbage never sits pending forever)
    return kind not in LOCAL_KINDS


def pending(commands_dir: Path | None = None, side: str | None = None) -> list[Path]:
    d = commands_dir or COMMANDS_DIR
    if not d.is_dir():
        return []
    paths = [p for p in sorted(d.glob("*.json"))
             if not p.name.endswith(".result.json") and not _result_path(p).exists()]
    if side is not None:
        paths = [p for p in paths if _on_side(p, side)]
    return paths


def run_pending(fleet: dict, request=gh.request, commands_dir: Path | None = None,
                side: str = "cloud") -> list[dict]:
    """Validate + execute every receipt-less command on this side; write receipts.

    side="cloud" (the Actions runner) executes every kind except
    LOCAL_KINDS, which it leaves untouched — no receipt, honestly pending
    for the PC. side="local" (the Core) executes only LOCAL_KINDS. The
    static partition means a command has exactly one possible executor.
    """
    results = []
    for path in pending(commands_dir, side=side):
        result: dict = {
            "id": path.stem,
            "executed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        problems = validate_command(path, fleet)
        if problems:
            result["outcome"] = "invalid"
            result["detail"] = "; ".join(problems)
        else:
            c = json.loads(path.read_text(encoding="utf-8"))
            # the kill switch holds everything except the resume that lifts it
            if policy.halted() and c["command"]["kind"] != "resume":
                result["outcome"] = "halted"
                result["detail"] = "Aletheia is halted — only a resume command executes"
                _write_receipt_and_journal(path, result)
                results.append(result)
                continue
            try:
                result["outcome"] = "done"
                result["detail"] = execute_command(c["command"], fleet, request=request,
                                                   quote=c.get("operator_quote", ""))
            except act.Refused as exc:
                result["outcome"] = "refused"
                result["detail"] = str(exc)
            except Unavailable as exc:
                result["outcome"] = "unavailable"
                result["detail"] = str(exc)
            except Exception as exc:
                result["outcome"] = "error"
                result["detail"] = f"{type(exc).__name__}: {exc}"
        _write_receipt_and_journal(path, result)
        results.append(result)
    return results


def _write_receipt_and_journal(path: Path, result: dict) -> None:
    # A RECEIPT IS COMMITTED, and its `detail` is whatever the capability
    # said — which for a web task is text read off a page, and for an
    # error is an exception message carrying whatever was being handled.
    # `sensitivity` is the same scrubber the journal uses, at the other
    # place his words reach a public repository.
    from aletheia import sensitivity
    detail, hidden = sensitivity.scrub(str(result.get("detail", "")))
    result = {**result, "detail": detail}
    if hidden:
        result["redacted"] = hidden
    _result_path(path).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    journal.append("action", f"intercom:{path.stem}",
                   f"{result['outcome']} — {result['detail']}", actor=ACTOR)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Execute relayed operator commands.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    runp = sub.add_parser("run")
    runp.add_argument("--side", choices=["cloud", "local"], default="cloud",
                      help="cloud (Actions, default) or local (the PC Core)")
    sub.add_parser("list")
    args = ap.parse_args(argv)

    fleet = load_fleet()
    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

    if args.cmd == "validate":
        bad = 0
        todo = pending()
        for path in todo:
            problems = validate_command(path, fleet)
            if problems:
                bad += 1
                print(f"INVALID {path.name}: " + "; ".join(problems))
            else:
                print(f"ok      {path.name}")
        print(f"{speech.count_phrase(len(todo), 'pending command')}, {bad} invalid")
        return 1 if bad else 0

    if args.cmd == "list":
        for path in sorted(COMMANDS_DIR.glob("*.json")):
            if path.name.endswith(".result.json"):
                continue
            rp = _result_path(path)
            if rp.exists():
                r = json.loads(rp.read_text(encoding="utf-8"))
                print(f"[{r['outcome']:7}] {path.stem}  {r['detail']}")
            else:
                side = "local" if _on_side(path, "local") else "cloud"
                print(f"[pending] {path.stem}  (waiting on {side})")
        return 0

    results = run_pending(fleet, side=args.side)
    for r in results:
        print(f"{r['id']}: {r['outcome']} — {r['detail']}")
    if not results:
        print("no pending commands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
