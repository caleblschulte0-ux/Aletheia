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

from aletheia import act, gh, journal, localtime, plans, policy, suggestions, tasks
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
    "halt":          (set(), {"reason"}),
    "resume":        (set(), set()),
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
    # Everything up to the submit, which stays his. See aletheia.applications.
    "apply_prepare": ({"role"}, {"count", "where", "resume"}),
    # "apply to ten jobs with this resume" — the whole thing, one call.
    "apply_campaign": ({"role"}, {"count", "where", "resume"}),
    # The catch-all for "go do this on a website" — any number of steps.
    "web_task":      ({"goal"}, {"url", "budget"}),
    # "try that again" after a site refused one — the ONLY case where
    # running it again is safe, because a refusal means nothing was taken.
    "web_task_retry": (set(), {"run_id"}),
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
    "email_check":   (set(), set()),
    # the text of ONE unread message, named by sender or subject; exactly
    # one match or a question back, never a guess (2026-09-02)
    "email_read":    ({"which"}, set()),
    "email_draft":   ({"to", "body"}, {"subject"}),
    # personal-OS verbs (2026-08-26): PC-private state, so all LOCAL_KINDS
    "remind_at":       ({"at", "text"}, set()),
    "remind_daily":    ({"time", "text"}, {"tz"}),
    "watch_email_from": ({"who"}, set()),
    "notify_operator": ({"text"}, {"priority"}),
    "notify_check":    (set(), set()),
    "notify_clear":    (set(), set()),
    "announce_set":    ({"on"}, {"quiet_from", "quiet_until"}),
    "free_time":       ({"day"}, {"tz", "minutes"}),
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
LOCAL_KINDS = {"browse_read", "browse_shot", "email_check", "email_read", "email_draft",
               # research only READS pages, but it reads them with the
               # operator's browser, so it belongs to the PC runner
               "research",
               # the workspace is a directory on his PC; Actions cannot see it
               "file_write", "file_edit", "file_read", "file_list", "compose",
               "file_delete", "file_move",
               # reads the open web and writes into her workspace: both PC
               "apply_prepare", "apply_campaign", "web_task", "web_task_retry",
               "computer_observe",
               # ffmpeg and his media files live on the PC
               "media_probe", "media_trim", "media_join", "media_audio",
               "media_captions", "media_convert",
               "remind_at", "remind_daily", "watch_email_from", "notify_check",
               "notify_clear", "free_time", "contact_add", "notify_operator",
               "intent", "screen_ask",
               # every private-state verb below lives on the PC
               "meet", "recall", "handle", "travel_time", "shopping_add",
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
    "note", "notify_check", "free_time", "brief", "subscriptions", "money",
    "projects", "car", "recall", "travel_time", "browse_read", "browse_shot",
    # reads public pages and writes a document; commits him to nothing
    "research",
    # looking at his own files commits him to nothing
    "file_read", "file_list",
    # looking at his own screen commits him to nothing either
    "computer_observe",
    # reading what a media file IS changes nothing
    "media_probe",
    "email_check", "email_read", "screen_ask", "authority_status", "setup_status",
})


# Local, reversible, private, and reaching nobody but him. A routine step
# writes to his own machine and can be undone by saying the opposite.
# Nothing here spends, sends, publishes, or binds him to anything.
ROUTINE_KINDS = frozenset({
    "task_new", "task_status", "plan_new", "plan_add_step", "plan_step",
    "plan_set", "remind_at", "remind_daily", "notify_operator",
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


def execute_command(cmd: dict, fleet: dict, request=gh.request, quote: str = "") -> str:
    """Run one validated command. Returns a human-readable detail line.
    Raises act.Refused / ValueError / KeyError — the caller records them."""
    kind = cmd["kind"]
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
    if kind == "task_new":
        tasks.create(cmd["id"], cmd["description"], goal=cmd.get("goal"),
                     assigned_worker=cmd.get("worker"), deadline=cmd.get("deadline"))
        return f"task {cmd['id']} queued"
    if kind == "task_status":
        t = tasks.set_status(cmd["id"], cmd["state"], cmd.get("note", ""))
        return f"task {cmd['id']} -> {t['status']}"
    if kind == "halt":
        policy.halt(cmd.get("reason", ""), via=ACTOR)
        return "KILL SWITCH ON — nothing acts until resume"
    if kind == "resume":
        policy.resume(via=ACTOR)
        return "resumed"
    if kind == "approve":
        policy.decide(cmd["id"], "APPROVED", via=ACTOR)
        return f"approval {cmd['id']} -> APPROVED"
    if kind == "deny":
        policy.decide(cmd["id"], "DENIED", via=ACTOR, because=cmd.get("because", ""))
        return f"approval {cmd['id']} -> DENIED"
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
        else:
            height = cmd.get("height")
            out = media.convert(cmd["source"], cmd["out"],
                                height=int(height) if height is not None else None)
        return f"{out['what']} -> {out['path']} ({out['bytes']:,} bytes) — source untouched"

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
        return (f"did {result['steps_done']} desktop step(s) [{did}] — run {result['run_id']}"
                + (f" — {cmd['why'][:120]}" if cmd.get("why") else ""))

    if kind == "web_task":
        from aletheia import webtask
        record = webtask.run(cmd["goal"], start_url=cmd.get("url", ""),
                             budget=int(cmd.get("budget", 16)))
        return webtask.spoken(record)
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
    if kind == "browse_shot":
        from aletheia import browse
        out = REPO_ROOT / "cache" / "browser-captures"
        out.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = out / f"shot-{stamp}.png"
        browse.screenshot(cmd["url"], target)
        # media never enters git — the capture stays on the PC, named here
        return f"screenshot of {cmd['url']} saved on the PC at {target}"
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
    if kind == "screen_ask":
        from aletheia import perception
        window = ({"title_re": re.escape(cmd["window"])} if cmd.get("window")
                  else None)
        answer = perception.describe(cmd["question"], window=window)
        return answer["answer"]
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
        destination = places.resolve(cmd["place"])
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
        said = (f"Assets {worth['assets']:.2f}, liabilities {worth['liabilities']:.2f}, "
                f"net {worth['net']:.2f} across {worth['accounts']} account(s).")
        if pending:
            said += f" {len(pending)} payment(s) waiting for you to authorize."
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
    if kind == "free_time":
        import datetime as _dt
        from aletheia import calendar as cal
        tz = cmd.get("tz") or localtime.operator_timezone()
        minutes = int(cmd.get("minutes", 30))
        day = _dt.date.fromisoformat(cmd["day"])
        slots = cal.free_slots(day, duration_minutes=minutes, timezone=tz)
        if not slots:
            return f"no free {minutes}-minute slot on {cmd['day']} inside work hours"
        spoken = ", ".join(s0[0][11:16] for s0 in slots[:4])
        return f"free on {cmd['day']} at {spoken}" + (" and more" if len(slots) > 4 else "")
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
        print(f"{len(todo)} pending command(s), {bad} invalid")
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
