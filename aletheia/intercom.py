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
    "halt":          (set(), {"reason"}),
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
    "browse_read":   ({"url"}, set()),
    "research":      ({"question"}, set()),
    # she can produce something now, not just say things
    "file_write":    ({"path", "text"}, {"why"}),
    # Writing something that has to be WRITTEN, not pasted. See below.
    "compose":       ({"path", "what"}, {"sources", "why"}),
    "file_edit":     ({"path", "find", "replace"}, {"why"}),
    "file_read":     ({"path"}, {"anywhere"}),
    "file_list":     (set(), {"subdir"}),
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
    "contacts":      (set(), {"which"}),
    "watches":       (set(), set()),
    # "apply to ten jobs with this resume" — the whole thing, one call.
    "apply_campaign": ({"role"}, {"count", "where", "resume"}),
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
    "email_check":   (set(), set()),
    # the text of ONE unread message, named by sender or subject; exactly
    # one match or a question back, never a guess (2026-09-02)
    "email_read":    ({"which"}, set()),
    "email_draft":   ({"to", "body"}, {"subject"}),
    # The most-asked-for thing she could not do — thirteen times in the
    # demand ledger, in his own words. Same shape as email_draft: it
    # writes a draft and an approval and sends nothing.
    "message_send":  ({"to", "body"}, set()),
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
    "music":         ({"action"}, set()),
    "chatgpt":       (set(), set()),
    "chatgpt_on":    (set(), {"hours"}),
    "chatgpt_off":   (set(), set()),
    "mic":           (set(), set()),
    "mic_on":        (set(), set()),
    "mic_off":       (set(), set()),
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
    "remind_at":       ({"at", "text"}, set()),
    "remind_daily":    ({"time", "text"}, {"tz"}),
    # "every Monday at 8, take the bins out". `scheduler` has had a
    # `weekly` kind since it was written and the GRAMMAR could not say it,
    # so "remind me every monday to take out the trash" compiled to a
    # generic `do_task` under a summary that promised a weekly reminder.
    # A capability nothing can ask for is not a capability.
    "remind_weekly":   ({"days", "time", "text"}, {"tz"}),
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
    "notify_snooze":   ({"minutes"}, {"which"}),
    "reminder_off":    ({"which"}, set()),
    "watch_email_from": ({"who"}, set()),
    "notify_operator": ({"text"}, {"priority"}),
    "notify_check":    (set(), set()),
    "notify_clear":    (set(), set()),
    "announce_set":    ({"on"}, {"quiet_from", "quiet_until"}),
    # `part` is morning/afternoon/evening. He says it constantly and it
    # used to be dropped in silence — see `_free_sentence`.
    "free_time":       ({"day"}, {"tz", "minutes", "part"}),
    "contact_add":     ({"name", "email"}, {"alias"}),
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
    "shopping_add":    ({"item"}, {"budget"}),
    # Reading the list back, and taking something off it. `shopping_add`
    # shipped without either, so she confirmed "Added to the shopping
    # list: milk" and then said she had no shopping list.
    "shopping_list":   (set(), set()),
    "shopping_off":    ({"item"}, set()),
    "subscriptions":   (set(), set()),
    "money":           (set(), set()),
    "car":             (set(), {"vehicle"}),
    "projects":        (set(), set()),
    # Reading what she may do without asking. Deliberately read-only: see
    # aletheia/standing.py — GRANTING authority is not something she takes
    # from an unauthenticated room microphone.
    "authority_status": (set(), set()),
    # "what do you still need from me?" — read-only; it checks, it configures
    # nothing. Every credential remains the operator's to create.
    "setup_status":     (set(), set()),
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
    "notify_snooze": (
        'Put a notification away and bring it BACK. minutes is how long; '
        'which is optional and defaults to the most recent unread one, '
        'because "snooze that" always means the thing that just spoke.'),
    "contacts": (
        'Who he has saved, and how to reach them. which is optional and '
        'narrows by name or alias — use it for "what is my mum\'s '
        'number". `contact_add` is the writer.'),
    "watches": (
        'What she is waiting to tell him about — the watchers '
        '`watch_email_from` creates. Nothing to do with browsing.'),
    "applications": (
        'What he has applied to through her — sent, and staged waiting on '
        'him. Use it for "what have I applied to"; `jobs` is the opposite '
        'direction, searching boards for new ones.'),
    "shopping_list": (
        'What is on his shopping list, read from the store. Use it for '
        '"what do I need from the shop" as well — it is the same list.'),
    "shopping_off": (
        'Take something off the shopping list. item is the words he used; '
        'she finds the one entry that matches and asks him if two do. It '
        'is cancelled, not deleted.'),
    "reminders": (
        'What reminders are set, read straight from the schedule store. '
        'which is optional and narrows by the words of the reminder. Use '
        'this rather than answering from context: the store is the only '
        'thing that knows.'),
    "reminder_off": (
        'Stop a reminder he has set. which is the words he used for it '
        '("the bins", "the gym one"); she finds the one reminder that '
        'matches and asks him which if two do. It is DISABLED, not '
        'deleted, so it can be put back.'),
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
        'role is the kind of job, count at most 10, where an optional '
        'location or "remote", resume a path (omit and she finds it). Prefer '
        'this over apply_prepare, which only writes a packet and does not '
        'touch the form.'),
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
        '{"action":"invoke","window":{...},"control":{"title":"Save"}} | '
        '{"action":"hotkey","window":{...},"keys":"ctrl+s"} (safe keys only: clipboard, '
        'undo, find, save, navigation, escape, tab — never enter/delete/alt+f4) | '
        '{"action":"select","window":{...},"control":{"control_type":"ComboBox"},"value":"UTF-8"}. '
        "Selectors use title, title_re, class_name, auto_id, control_type (a control "
        "also best_match) — never screen coordinates. A window title_re matches anywhere in the title, ignoring case. A text area is control_type Edit or Document (either finds it). Windows 11 Notepad reopens its last tabs on launch: to write fresh text, send hotkey ctrl+n after wait_window, then set_text. A control labelled Send, "
        "Delete, Pay, Purchase, Confirm, Submit, Format, Uninstall or Empty Trash "
        "is refused and needs his approval; do not plan around it."),
    "do_task": (
        "request is the ask in plain words. She writes a small Python program "
        "(standard library only, no network, no subprocess, workspace files only) "
        "and runs it. Use this ONLY when no other kind does the job."),
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
               # the workspace is a directory on his PC
               "doc_make",
               # Phone Link is paired to his iPhone on THIS machine;
               # Actions cannot text anybody.
               "message_send", "music",
               # research only READS pages, but it reads them with the
               # operator's browser, so it belongs to the PC runner
               "research",
               # the workspace is a directory on his PC; Actions cannot see it
               "file_write", "file_edit", "file_read", "file_list", "compose",
               "file_delete", "file_move",
               # reads the open web and writes into her workspace: both PC
               "apply_prepare", "apply_campaign", "applications",
               "web_task", "web_task_retry",
               "subscription_cancel", "web_task_answer",
               "computer_observe",
               # ffmpeg and his media files live on the PC
               "media_probe", "media_trim", "media_join", "media_audio",
               "media_captions", "media_convert",
               "remind_at", "remind_daily", "remind_weekly",
               "reminders", "reminder_off", "notify_snooze",
               "watch_email_from", "notify_check",
               "notify_clear", "free_time", "contact_add", "notify_operator",
               "intent", "screen_ask",
               # every private-state verb below lives on the PC
               "meet", "recall", "handle", "travel_time", "shopping_add",
               "shopping_list", "shopping_off", "contacts", "watches",
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
    # Asking whether she is on changes nothing and must stay answerable
    # while she is halted, closed, or halfway between the two.
    "running",
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
    "jobs", "tasks", "reminders", "shopping_list", "applications",
    "contacts", "watches",
    "projects", "car", "recall", "travel_time", "browse_read", "browse_shot",
    # reads public pages and writes a document; commits him to nothing
    "research",
    # looking at his own files commits him to nothing
    "file_read", "file_list",
    # looking at his own screen commits him to nothing either
    "computer_observe",
    # and photographing it commits him to nothing: the file stays on the
    # PC under cache/, which is gitignored, exactly like browse_shot's
    "screenshot",
    # reading what a media file IS changes nothing
    "media_probe",
    "email_check", "email_read", "screen_ask", "authority_status", "setup_status",
})


# Local, reversible, private, and reaching nobody but him. A routine step
# writes to his own machine and can be undone by saying the opposite.
# Nothing here spends, sends, publishes, or binds him to anything.
ROUTINE_KINDS = frozenset({
    "task_new", "task_status", "plan_new", "plan_add_step", "plan_step",
    "plan_set", "remind_at", "remind_daily", "remind_weekly",
    # Disabling a reminder is reversible by saying the opposite, which is
    # the whole test for this tier — the schedule is disabled, never
    # deleted, so "actually put that back" is one command.
    "reminder_off", "shopping_off", "notify_snooze", "notify_operator",
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
    "notify_clear", "remember", "contact_add", "shopping_add",
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
    # Deleting and moving keep a version FIRST, so both are undoable. A
    # delete that cannot lose anything is a shelf, not a shredder.
    "file_delete", "file_move",
    # Application packets are files and tasks; the one irreversible step in
    # a job application is deliberately not in this kind at all.
    "apply_prepare",
    # Filling forms and staging approvals. It sends nothing on its own:
    # every application still waits for the approval he taps, per job.
    "apply_campaign",
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
    "task_status": {"state": _enum("aletheia.contracts", "TASK_STATES")},
    "rule": {"state": _enum("aletheia.suggestions", "VALID_STATES")},
    "plan_set": {"state": _enum("aletheia.plans", "PLAN_STATES")},
    "plan_step": {"state": _enum("aletheia.plans", "STEP_STATES")},
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
    from aletheia import tasks as tasks_mod
    return [t for t in tasks_mod.all_tasks()
            if str(t.get("status", "")).upper() in OPEN_TASK_STATES]


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
            return f"Nothing open matching {which!r}."
    if not rows:
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
                  "weekly": "remind_weekly"}


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


def _reminder_words(spec: dict) -> str:
    """One reminder, as he would say it."""
    from aletheia import speech
    text = str((spec.get("command") or {}).get("text") or spec["id"])[:70]
    if spec["kind"] == "once":
        return f"{text} — {speech.humanize_time(str(spec.get('at') or ''))}"
    when = speech.clock_words(str(spec.get("time") or ""))
    if spec["kind"] == "daily":
        return f"{text} — every day at {when}"
    days = _weekday_words(sorted(spec.get("weekdays") or []))
    lead = days if days in ("weekdays", "weekends", "every day") else f"every {days}"
    return f"{text} — {lead} at {when}"


def _reminders_answer(which: str = "") -> str:
    """"What reminders do I have" — from the store, with no model."""
    from aletheia import speech
    rows = _reminder_schedules()
    if which:
        needle = which.casefold()
        rows = [r for r in rows
                if needle in str((r.get("command") or {}).get("text", "")).casefold()]
        if not rows:
            return f"No reminder matching {which!r}."
    if not rows:
        return "You have no reminders set."
    said = speech.and_list([_reminder_words(r) for r in rows[:5]])
    more = f", and {len(rows) - 5} more" if len(rows) > 5 else ""
    return f"{speech.count_phrase(len(rows), 'reminder')}: {said}{more}."


def _one_reminder(which: str):
    """(schedule, why-not) — exactly one reminder he could mean.

    Same rule as `_one_task`: find it by the words he used, refuse to
    guess between two, and never silently pick the first.
    """
    from aletheia import speech
    needle = " ".join(str(which or "").split()).casefold()
    rows = _reminder_schedules()

    def text_of(spec):
        return str((spec.get("command") or {}).get("text", "")).casefold()

    hits = [r for r in rows if needle and needle in text_of(r)]
    if not hits:
        words = [w for w in re.split(r"[^a-z0-9]+", needle)
                 if len(w) > 2 and w not in TASK_STOP and w != "reminder"]
        scored = [(sum(1 for w in words if w in text_of(r)), r) for r in rows]
        best = max((n for n, _r in scored), default=0)
        hits = [r for n, r in scored if n == best and n > 0]
    if not hits:
        return None, (f"No reminder matching {which!r}." if rows
                      else "You have no reminders set.")
    if len(hits) > 1:
        return None, ("Which one — "
                      + speech.or_list([str((r.get("command") or {}).get("text")
                                            or r["id"])[:50] for r in hits[:4]])
                      + "?")
    return hits[0], ""


def _contact_words(contact: dict) -> str:
    """One contact, with whatever she actually has for them."""
    from aletheia import speech
    name = str(contact.get("display_name") or contact["id"])
    reach = [str(v) for v in (list(contact.get("phones") or [])
                              + list(contact.get("emails") or []))[:2] if v]
    return f"{name} — {speech.and_list(reach)}" if reach else name


def _contacts_answer(which: str = "") -> str:
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
        rows = hits
        if not rows:
            return f"I have no contact for {which!r}."
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
    if not rows:
        return "You haven't applied to anything through me yet."
    sent = [r for r in rows if r.get("state") == "SUBMITTED"]
    waiting = [r for r in rows if r.get("state") != "SUBMITTED"]

    def where(record):
        title = str(record.get("page_title") or "").strip()
        return (title or speech.tidy(str(record.get("url") or record.get("id"))))[:60]

    parts = []
    if sent:
        parts.append(f"{speech.count_phrase(len(sent), 'application')} sent: "
                     + speech.and_list([where(r) for r in sent[-5:]]))
    if waiting:
        lead = ("and " if sent else "") + speech.count_phrase(
            len(waiting), "application")
        parts.append(f"{lead} staged and waiting on you: "
                     + speech.and_list([where(r) for r in waiting[-5:]]))
    return ". ".join(parts) + "."


SHOPPING_OPEN = ("RESEARCHING", "SELECTED", "PURCHASE_PROPOSED")


def _shopping_items() -> list[dict]:
    from aletheia import shopping
    return [w for w in shopping.all_workflows()
            if str(w.get("state", "")).upper() in SHOPPING_OPEN]


def free_time_answer(cmd: dict) -> str:
    """When he is free, as one sentence. Public because `quick` answers
    the same question from the same feed, and the sentence should be
    written in exactly one place."""
    import datetime as _dt
    from aletheia import calendar as cal
    tz = cmd.get("tz") or localtime.operator_timezone()
    minutes = int(cmd.get("minutes", 30))
    day = _dt.date.fromisoformat(cmd["day"])
    part = str(cmd.get("part") or "").strip().lower()
    slots = cal.free_slots(day, duration_minutes=minutes, timezone=tz)
    # HE SAID "AFTERNOON". Dropping the qualifier and answering about
    # the whole day answers a different question than the one asked,
    # and he has no way to tell that it happened.
    if part:
        slots = cal.in_part(slots, part)
    return _free_sentence(cal.merge_slots(slots), day, part)


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
        scored = [(sum(1 for w in words
                       if w in str(t.get("description", "")).casefold()), t)
                  for t in rows]
        best = max((n for n, _t in scored), default=0)
        hits = [t for n, t in scored if n == best and n > 0]
    if not hits:
        return None, f"Nothing open matching {which!r}."
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

    when = speech.humanize_time(f"{day.isoformat()}T12:00:00").split(" at ")[0]
    if part:
        # "today evening" is not English. Today takes "this"; every other
        # day keeps its name ("tomorrow afternoon", "Friday morning").
        when = f"this {part}" if when == "today" else f"{when} {part}"
    if not ranges:
        if part in ("evening", "tonight"):
            return f"Nothing free {when} — {WORK_HOURS_NOTE}."
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
    if kind == "tasks":
        return _tasks_answer(cmd.get("which", ""))
    if kind == "task_done":
        from aletheia import tasks as tasks_mod
        found, why = _one_task(cmd["which"])
        if found is None:
            return why
        tasks_mod.set_status(found["id"], "COMPLETED",
                             note=f"marked done: {quote[:120]}")
        return f"marked done — {found.get('description') or found['id']}"
    if kind == "task_new":
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
        from aletheia import webtask
        record = webtask.run(cmd["goal"], start_url=cmd.get("url", ""),
                             budget=int(cmd.get("budget", 16)))
        return webtask.spoken(record)
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
        from aletheia import webtask
        run_id = cmd.get("run_id") or ""
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
        from aletheia import webtask
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
        out = campaign.run(cmd["role"], count=int(cmd.get("count", 5)),
                           where=cmd.get("where", ""),
                           resume=cmd.get("resume", ""))
        said = campaign.spoken(out)
        if out["questions"]:
            said += " I need: " + "; ".join(
                q["label"] for q in out["questions"][:6])
        return said
    if kind == "apply_prepare":
        from aletheia import applications
        out = applications.prepare(
            cmd["role"], count=int(cmd.get("count", 5)),
            where=cmd.get("where", ""),
            resume=cmd.get("resume", "resume.md"))
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
            return (f"wrote {out['path']} ({out['chars']:,} chars)"
                    + ("" if out["created"] else " — previous version kept"))
        if kind == "file_edit":
            out = workspace.edit(cmd["path"], cmd["find"], cmd["replace"],
                                 why=cmd.get("why", ""))
            return f"edited {out['path']} ({out['replacements']} change)"
        if kind == "file_read":
            out = workspace.read(cmd["path"], anywhere=bool(cmd.get("anywhere")))
            return out["text"][:2000]
        rows = workspace.listing(cmd.get("subdir", ""))
        return ", ".join(r["path"] for r in rows[:40]) or "(empty)"

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
        return mail.check_unread()
    if kind == "email_read":
        from aletheia import mail
        message = mail.read_body(cmd["which"])
        body = " ".join(message["text"].split())[:1500] or "(no readable text)"
        return f"From {message['from']} — {message['subject']}: {body}"
    if kind == "email_draft":
        from aletheia import mail
        d = mail.draft(cmd["to"], cmd.get("subject", ""), cmd["body"],
                       requested_via=f"intercom: {quote[:80]}")
        return (f"draft to {d['to_name']} ready — {d['subject']!r}. "
                f"Approval {d['id']} is pending; approving it sends the email.")
    if kind == "music":
        from aletheia import music
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
        sid = "remind-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="once", at=cmd["at"])
        return f"reminder {sid} set for {cmd['at']} — {cmd['text'][:80]!r}"
    if kind == "remind_daily":
        from aletheia import scheduler
        import uuid as _uuid
        sid = "remind-daily-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="daily", timezone=cmd.get("tz") or localtime.operator_timezone(),
                         time=cmd["time"])
        return f"daily reminder {sid} set for {cmd['time']} — {cmd['text'][:80]!r}"
    if kind == "remind_weekly":
        from aletheia import scheduler
        import uuid as _uuid
        days = _weekday_numbers(cmd["days"])
        sid = "remind-weekly-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="weekly",
                         timezone=cmd.get("tz") or localtime.operator_timezone(),
                         time=cmd["time"], weekdays=days)
        return (f"weekly reminder {sid} set for "
                f"{_weekday_words(days)} at {cmd['time']} — {cmd['text'][:80]!r}")
    if kind == "reminders":
        return _reminders_answer(cmd.get("which", ""))
    if kind == "reminder_off":
        from aletheia import scheduler
        found, why = _one_reminder(cmd["which"])
        if found is None:
            raise act.Refused(why)
        # DISABLED, never deleted: "actually put that back" has to be one
        # command, and a deleted schedule cannot be put back at all.
        scheduler.set_enabled(found["id"], False)
        return f"reminder {found['id']} off — {_reminder_words(found)}"
    if kind == "notify_snooze":
        from aletheia import notifications, scheduler
        import uuid as _uuid
        minutes = int(cmd["minutes"])
        if not 1 <= minutes <= 60 * 24 * 7:
            raise act.Refused("snooze it for anything from a minute to a week.")
        found, why = _one_notice(cmd.get("which", ""))
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
                f"{(found.get('body') or found['title'])[:80]!r}")
    if kind == "notify_operator":
        from aletheia import notifications
        notice = notifications.publish("Reminder", cmd["text"], priority="IMPORTANT",
                                       source="reminder")
        return f"reminder surfaced: {notice['id']}"
    if kind == "watch_email_from":
        from aletheia import events as bus, mail as mail_mod
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
        answer = eyes.answer(cmd["question"])
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
        start = cmd.get("from_day") or _dt.date.today().isoformat()
        end = cmd.get("to_day") or (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
        slug = _re.sub(r"[^a-z0-9]+", "-", cmd["person"].lower()).strip("-")[:30]
        record = scheduling.start(
            f"meet-{slug}-{_dt.date.today().isoformat()}"[:60], cmd["person"],
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
            return f"I don't have anything remembered about {about!r}."
        return "; ".join(found[:4])
    if kind == "brief":
        from aletheia import brief, journal as _j, pulse as _p
        import json as _json
        latest = _p.PULSE_DIR / "latest.json"
        current = _json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else {}
        if not current.get("repos"):
            # An unpulsed machine. It used to reach `compose` and raise a
            # bare KeyError, which he heard as "I couldn't: 'generated_at'".
            return ("I haven't collected a pulse yet, so there is no brief to "
                    "give you. `python -m aletheia.pulse` builds one.")
        return brief.compose(current, brief.previous_pulse(current),
                             _j.since(24), 0)
    if kind == "handle":
        from aletheia import handler
        import uuid as _uuid
        request = handler.create(f"handle-{_uuid.uuid4().hex[:8]}", intent=cmd["text"])
        return (f"I'm on it: {request['intent'][:80]}. "
                f"State is {request['state'].lower().replace('_', ' ')}.")
    if kind == "travel_time":
        from aletheia import places
        try:
            destination = places.resolve(cmd["place"])
        except KeyError:
            # `KeyError: "no place matches 'airport'"` reached the room
            # verbatim, quotes and all. He cannot act on that; he can act
            # on being told to name the place once.
            raise act.Refused(
                f"I don't know where {cmd['place']} is. Tell me the address "
                "once and I'll remember it.") from None
        except LookupError:
            raise act.Refused(
                f"More than one place answers to {cmd['place']!r} — which "
                "one do you mean?") from None
        try:
            home = places.resolve("home")
        except Exception:
            return (f"I know {destination['name']}, but I have no place called "
                    "'home' to measure from — add one first.")
        try:
            observed = places.travel_time(home["id"], destination["id"])
        except (ValueError, OSError):
            # §104: never invent a duration. An unobserved trip is unknown.
            return (f"I know {destination['name']} but have never observed a "
                    "journey to it, so any number would be a guess.")
        return (f"{destination['name']}: {observed.get('minutes', '?')} minutes "
                f"observed {observed.get('observed_at', 'previously')}.")
    if kind == "shopping_add":
        from aletheia import shopping
        import re as _re, uuid as _uuid
        slug = _re.sub(r"[^a-z0-9]+", "-", cmd["item"].lower()).strip("-")[:30]
        budget = float(cmd["budget"]) if cmd.get("budget") else None
        workflow = shopping.create(f"shop-{slug}-{_uuid.uuid4().hex[:4]}"[:60],
                                   need=cmd["item"], budget=budget)
        return f"Added to the shopping list: {workflow['need']}."
    if kind == "contacts":
        return _contacts_answer(cmd.get("which", ""))
    if kind == "watches":
        return _watches_answer()
    if kind == "applications":
        return _applications_answer()
    if kind == "shopping_list":
        return shopping_answer()
    if kind == "shopping_off":
        from aletheia import shopping
        found, why = _one_shopping_item(cmd["item"])
        if found is None:
            raise act.Refused(why)
        shopping.cancel(found["id"])
        return f"shopping item {found['id']} off — {found['need']}"
    if kind == "subscriptions":
        from aletheia import subscriptions
        rows = subscriptions.all_subscriptions(active_only=True)
        if not rows:
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
        said = (f"Assets {worth['assets']:.2f}, liabilities {worth['liabilities']:.2f}, "
                f"net {worth['net']:.2f} across "
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
        from aletheia import projects
        rows = [p for p in projects.all_projects()
                if str(p.get("status", "")).upper() not in ("DONE", "CANCELLED")]
        if not rows:
            return "No active projects."
        return f"{len(rows)} active: " + ", ".join(
            f"{p.get('title', p['id'])} ({str(p.get('status','')).lower()})"
            for p in rows[:5])
    if kind == "setup_status":
        from aletheia import setup as _setup
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
    if kind == "contact_add":
        from aletheia import contacts, mail as mail_mod
        import re as _re
        addr, _ = mail_mod.resolve_address(cmd["email"])
        if addr is None or "@" not in addr:
            return f"that didn't sound like an email address: {cmd['email']!r}"
        cid = _re.sub(r"[^a-z0-9]+", "-", cmd["name"].lower()).strip("-") or "person"
        aliases = [cmd["alias"]] if cmd.get("alias") else []
        try:
            contacts.create(cid, cmd["name"].strip(), emails=[addr], aliases=aliases,
                            provenance=f"operator via voice/intercom: {quote[:100]}")
        except FileExistsError:
            contacts.update(cid, emails=[addr])
        return f"remembered {cmd['name']} as {addr} — private contacts only, never the public repo"
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
