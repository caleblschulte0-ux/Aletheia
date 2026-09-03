"""She answers the question. Not a plan for it — the answer.

The gap this closes is the one that decides whether she can replace a
chat assistant, and it is not a small one.

Every ask reaching her went through `planner.compile()`, which turns
English into COMMAND STEPS. That is exactly right for "remind me Tuesday"
and exactly wrong for "explain this to me", "which of these should I
pick", "write me a paragraph about X". For those the planner returns
`intent: "answer"` with nothing executable, `intents.propose` retires the
record, and `spoken()` falls through to `plan.summary` — a one-line
restatement of the question. She was an executor with no mouth: ask her
anything a person would ask an assistant and she hands back a gist.

So this is the second half of her. `planner` decides WHAT KIND of thing
was asked; when the answer is "he wants an answer", the question comes
here and gets one, from the same subscription the rest of her runs on.

Three things it does that a bare model call would not:

- **It knows who it is talking to and what it is.** The system prompt
  carries her name, the fact that she is his, and the standing rule that
  she says what she does not know rather than filling the gap. A model
  answering as nobody in particular is the thing he already has two of.
- **It knows what she has been doing.** What is running, what needs him,
  what he asked her to remember. "What was I meant to do about the
  trader?" is a question about HIS state, and a chat assistant elsewhere
  cannot answer it at all. This is the part that makes her worth using
  over them.
- **It is not a memory hole.** The last few exchanges travel with the
  question, so "what about the other one?" means something. Bounded on
  purpose: a transcript that grows forever becomes a slow, expensive way
  to ask a simple question.

What it deliberately does NOT do: act. Nothing here executes a command,
writes a file, or spends anything. If the answer implies work, she says
so and the ordinary planner path takes it — the gates stay exactly where
they were.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import threading
from pathlib import Path

from aletheia import journal, policy, reasoner, stateio, workspace

ACTOR = "aletheia-converse"

THREAD_PATH = stateio.private_dir("conversation") / "recent.json"

# Memory is trimmed by SIZE, not by a turn count. Eight turns of one-line
# answers is nothing; eight turns of long ones is a slow expensive question
# every time. What matters is how much travels, so that is what is bounded.
KEEP_TURNS = 24
MAX_THREAD_CHARS = 6_000

MAX_QUESTION_CHARS = 4_000
MAX_ANSWER_CHARS = 6_000

# THE HARD CEILING, and it is not ours: `reasoner.validate_input` refuses
# any prompt over `brain.MAX_TEXT` (16,000 characters) before the CLI is
# even started, and the refusal is a bare ValueError that reads, by the time
# it reaches the phone, as "I could not reach a model". So a 20 KB document
# would not have produced a worse answer — it would have produced NO answer
# and no hint of why. Everything below is budgeted to stay under it.
MAX_PROMPT_CHARS = 15_000
MAX_CONTEXT_CHARS = 4_000
# Always kept for the context even when a large file is open: whether she is
# halted, and what time it is where he is, must never be the thing that got
# squeezed out by a spreadsheet.
MIN_CONTEXT_CHARS = 1_200
SECTION_OVERHEAD = 500

# A thoughtful answer takes longer than an interpretation. The default 90s
# is sized for classifying a sentence; a real reply to a real question is
# allowed three minutes before we call it a failure.
TIMEOUT_S = 180.0

# Files she may pull in when he names one. Two, because "compare these"
# is common and "read my whole folder" is a different request with a
# different tool (research/script), not a chat message.
MAX_ATTACHED = 2
# Sized to FIT, not to a round number: see MAX_PROMPT_CHARS. A longer file
# is truncated and says so, which is a worse answer; the alternative was no
# answer at all.
MAX_ATTACHED_CHARS = 9_000

# How long a file she just read stays open for the next question. A
# follow-up comes in seconds; a document from an hour ago is a different
# subject and carrying it forward is just cost.
CARRY_FILE_S = 1_800.0

SYSTEM = """You are Thea — Aletheia — Caleb's own assistant, running on his
machine. You are answering him directly, in conversation.

How you answer:
- Say the thing. Lead with the answer, then the reasoning if it earns its
  place. No preamble, no "great question", no restating what he asked.
- Be as long as the question deserves and no longer. A factual question
  gets a sentence. A judgement call gets the shape of the decision.
- Plain words. He is smart and busy; he is not asking to be impressed.
- If you do not know, say so plainly, and say what would settle it. Never
  fill the gap with something that sounds right. He can check, and the
  whole point of you is that he does not have to.
- You are not a search engine and you are not pretending to browse. If
  something needs current information you do not have, say that and offer
  to look it up — he can ask you to research it, which really reads pages.
- When he names a file, its real contents travel with the question under
  FILE HE NAMED. Work from what it actually says, and quote it when that
  is the answer. If a file could not be read you are told which one and
  why under COULD NOT READ — say so, and do not answer as though you had
  opened it. A confident paragraph about a document she never saw is the
  worst thing she can produce.

What you know about right now travels with the question under CONTEXT:
what you are working on, what is waiting for him, what he asked you to
remember. Use it when it is relevant and ignore it when it is not. Do not
recite it back at him.

WHAT YOU CAN DO IS NOT SOMETHING YOU KNOW — IT IS SOMETHING YOU LOOK UP.
When the question is about your own abilities, a WHAT I CAN DO block
travels with it, read from your capability registry at the moment he
asked. Every claim about what you can or cannot do comes from that block:

- AVAILABLE means it really works; say so plainly.
- NEEDS_CONFIGURATION is not "I can't" — it is "not yet", and the block
  carries the exact command. Give it to him.
- EXPERIMENTAL means it exists and you have not proven it. Say that;
  do not describe it in the same voice as something you use daily.
- NOT_BUILT means it does not exist. Do not soften it into a maybe.
- If the block does not cover what he asked, say you would have to check
  rather than guessing. You are the one system in his life that is not
  allowed to be plausibly wrong about itself.

WHAT YOU DID IS NOT SOMETHING YOU REMEMBER — IT IS SOMETHING YOU CHECK.
When he asks about your own past ("did you send it?", "what did you do
today?", "why is that paused?"), a WHAT I ACTUALLY DID block travels with
the question, read from the journal. Only say you did something if a line
in it says you did. The journal is append-only and every action writes to
it, so an empty block means it did not happen — say that plainly rather
than producing a sentence that sounds like it did. Never invent a time, a
recipient, or an outcome. This is the one place where a confident wrong
answer is indistinguishable from a right one until he goes and checks.

You do not take actions in this reply. If answering properly means doing
something — sending, writing a file, changing anything — say what you
would do and let him ask for it."""


class ConverseError(RuntimeError):
    pass


# The Core is a ThreadingHTTPServer and its beat runs on another thread, so
# two questions really can land at once — the phone and the room. Remembering
# a turn is read-modify-write on one small file, and the loser of that race
# silently loses his exchange. One process, one lock.
_THREAD_LOCK = threading.Lock()


def _trim(turns: list[dict]) -> list[dict]:
    """Newest-first until the size budget runs out, then back into order.

    A turn count alone is the wrong bound. Twenty-four one-line exchanges
    are nothing; twenty-four long ones are a slow, expensive question every
    single time, and the oldest of them stopped being relevant long before
    it stopped being sent. So the count is a ceiling and the SIZE is the
    real limit. The most recent turn always survives, even if it alone is
    over budget — dropping the thing he just said is never the right
    answer to "this is too long".
    """
    kept: list[dict] = []
    total = 0
    for turn in reversed(turns[-KEEP_TURNS:]):
        if not isinstance(turn, dict):
            continue
        size = len(str(turn.get("you", ""))) + len(str(turn.get("her", "")))
        if kept and total + size > MAX_THREAD_CHARS:
            break
        kept.append(turn)
        total += size
    kept.reverse()
    return kept


def _thread() -> list[dict]:
    try:
        value = stateio.read_json(THREAD_PATH)
    except (OSError, ValueError):
        return []
    turns = value.get("turns") if isinstance(value, dict) else None
    # Trimmed on the way OUT as well as in, so a file written by an older
    # build (or grown by hand) cannot push an oversized thread at the model.
    return _trim(turns) if isinstance(turns, list) else []


def _remember_turn(question: str, answer: str,
                   files: list[str] | None = None) -> None:
    """Keep the last few exchanges so 'what about the other one?' resolves."""
    turn = {"at": stateio.utcnow(), "you": question[:600], "her": answer[:900]}
    if files:
        # PATHS, never contents: the thread is a small file and a resume in
        # it would be both huge and a copy of his document living somewhere
        # he did not put it. The next turn re-reads from the original.
        turn["files"] = files[:MAX_ATTACHED]
    with _THREAD_LOCK:
        turns = _thread()
        turns.append(turn)
        stateio.write_json_atomic(THREAD_PATH, {"turns": _trim(turns)})


def _carried_over(turns: list[dict]) -> list[str]:
    """The file she read a moment ago, still open for the next question.

    "Look at resume.md" then "make the second bullet stronger" is one
    conversation, and the second half named no file — so without this she
    goes blind again mid-thread and answers from a 900-character summary of
    her own last reply. Only the MOST RECENT turn carries, and only for a
    little while: a document from an hour ago is a different subject.
    """
    if not turns:
        return []
    last = turns[-1]
    files = last.get("files") if isinstance(last, dict) else None
    if not isinstance(files, list) or not files:
        return []
    try:
        from aletheia import localtime
        when = localtime.parse_utc(str(last.get("at", "")))
        age = (dt.datetime.now(dt.timezone.utc) - when).total_seconds()
    except Exception:
        return []
    if age > CARRY_FILE_S:
        return []
    return [str(f) for f in files[:MAX_ATTACHED]]


def recent(limit: int = 3) -> list[dict]:
    """The last few exchanges, for anything that has to resolve "do that".

    Public because the PLANNER needs it. A question answered in
    conversation is very often followed by an instruction that only makes
    sense against it — "do that", "yes, go ahead", "the second one" — and
    the planner had no path to the conversation at all, so those came back
    as clarifying questions about what "that" meant. He had just said.

    Short on purpose: this is for resolving a referent, not for re-reading
    the whole discussion, and every character of it costs a planning prompt.
    """
    out = []
    for turn in _thread()[-max(0, int(limit)):]:
        if isinstance(turn, dict):
            out.append({"at": str(turn.get("at", ""))[:40],
                        "he_asked": str(turn.get("you", ""))[:240],
                        "she_answered": str(turn.get("her", ""))[:240]})
    return out


def forget() -> None:
    """Drop the thread. A new subject should not inherit the last one."""
    stateio.write_json_atomic(THREAD_PATH, {"turns": []})


# ---- files he names ------------------------------------------------------
#
# "Look at my resume and tell me what's weak" was, until now, a question
# answered blind: she had no way to notice that `resume.md` was a FILE and
# not a word, so she wrote a confident paragraph about a document she had
# never opened. That is the single worst failure available to her, because
# it is indistinguishable from the real thing until he checks.
#
# Reading is the safe half of `workspace` (see its module docstring: she
# may read what he names anywhere; she may only WRITE inside her own
# directory), so this adds no authority — it just makes her use the eyes
# she already had.

# What she may READ, which is wider than what she may write — and now
# includes the formats his real documents are actually in. "Look at my
# resume.pdf" was, until today, a file she could not open.
READABLE_SUFFIXES = frozenset(workspace.TEXT_SUFFIXES
                              | {".pdf", ".docx", ".dotx"})

# A DELIBERATE reference, not a passing mention. Either the token carries a
# path separator or a `~`, or the sentence asks her to look at something.
# Without this, "the bug is in converse.py" would produce "I couldn't find
# converse.py" — noise attached to an answer that did not need the file.
_LOOK = re.compile(
    r"\b(read|reads?|reading|look|looks?|looking|open|opens?|check|checks?|"
    r"review|reviews?|summari[sz]e|attached?|attach|go through|"
    r"in my|from my|my file)\b", re.I)
_QUOTED = re.compile(r"[\"'`]([^\"'`\n]{1,200})[\"'`]")
_BARE = re.compile(r"[~A-Za-z0-9_.\-/\\:]{2,200}")
_TRAILING = "\"'`,;:!?)]}>"


def _suffix(token: str) -> str:
    head, dot, tail = token.replace("\\", "/").rpartition(".")
    return ("." + tail.casefold()) if dot and head else ""


def _candidates(question: str) -> list[str]:
    """Every token in the question that is shaped like a readable file."""
    seen: list[str] = []
    raw = [m.group(1) for m in _QUOTED.finditer(question)]
    raw += [m.group(0) for m in _BARE.finditer(question)]
    for token in raw:
        token = token.strip().rstrip(_TRAILING).strip()
        if token and _suffix(token) in READABLE_SUFFIXES and token not in seen:
            seen.append(token)
    return seen


def _open_named(token: str) -> dict:
    """Find the file he meant. Her workspace first, then the path as given,
    then the same path under his home — "Documents/resume.md" is a thing a
    person says, and the Core's working directory is not where he is."""
    normalized = token.replace("\\", "/")
    rooted = (normalized.startswith(("/", "~"))
              or (len(normalized) > 1 and normalized[1] == ":"))
    tries = [lambda: workspace.read(token),
             lambda: workspace.read(token, anywhere=True)]
    if not rooted:
        tries.append(lambda: workspace.read(str(Path.home() / normalized),
                                            anywhere=True))
    # A MISS and a REFUSAL are different answers and he needs the second one
    # verbatim: "there is no such file" versus "it is 4 MB" or "it is not
    # UTF-8". Reporting the last attempt's error blindly named a path he
    # never mentioned ("/root/notes.md is not a file") — true, useless, and
    # it exposed where she went looking.
    refusals: list[str] = []
    for attempt in tries:
        try:
            return attempt()
        except workspace.OutsideWorkspace:
            continue                  # wrong lane for this token; try the next
        except workspace.WorkspaceError as exc:
            message = str(exc)
            if "is not a file" not in message:
                refusals.append(message)   # found it, cannot use it — say why
        except Exception as exc:      # noqa: BLE001
            refusals.append(f"{type(exc).__name__}: {exc}")
    if refusals:
        raise FileNotFoundError(refusals[0])
    raise FileNotFoundError(
        "she looked in her workspace, at that path, and under your home "
        "folder — there is no such file")


def attachments(question: str, *, budget: int = MAX_ATTACHED_CHARS
                ) -> tuple[list[dict], list[str]]:
    """Files named in the question, actually read — and what could not be.

    Returns (read, problems). `problems` is never silently dropped: it
    travels with the question so the answer says which file it is missing
    instead of writing around the hole.
    """
    named = _candidates(question)
    if not named:
        return [], []
    asked_to_look = bool(_LOOK.search(question))
    read: list[dict] = []
    problems: list[str] = []
    budget = min(int(budget), MAX_ATTACHED_CHARS)
    for token in named:
        explicit = (asked_to_look or "/" in token or "\\" in token
                    or token.startswith("~"))
        if len(read) >= MAX_ATTACHED:
            if explicit:
                problems.append(
                    f"{token} — she reads at most {MAX_ATTACHED} files in one "
                    "question; ask about this one on its own")
            continue
        if budget <= 0:
            if explicit:
                problems.append(f"{token} — no room left after the earlier files")
            continue
        try:
            got = _open_named(token)
        except Exception as exc:      # noqa: BLE001
            if explicit:
                problems.append(f"{token} — {exc}")
            continue
        text = str(got.get("text", ""))
        if len(text) > budget:
            text = (text[:budget]
                    + f"\n[... truncated here; the file is {got.get('bytes', 0):,} "
                      "bytes and she was only given the start of it]")
        budget -= len(text)
        read.append({"named": token, "path": got.get("path", token), "text": text})
    return read, problems


def _todays_events(limit: int = 8) -> list[str]:
    """What is on his calendar between now and the end of his day.

    Bounded to today on purpose: the whole calendar is a different question
    with a different tool. This is the part that makes "am I free tonight?"
    answerable at all instead of deferred back to him.
    """
    from aletheia import calendar, localtime
    now = dt.datetime.now(dt.timezone.utc)
    here = localtime.operator_tz()
    today = now.astimezone(here).date()
    rows = []
    for event in calendar.all_events():
        if event.get("status") == "CANCELLED":
            continue
        try:
            start = calendar.parse_time(event["start"]).astimezone(here)
        except Exception:
            continue
        if start.date() != today:
            continue
        rows.append((start, f"{start.strftime('%H:%M')} {event.get('title', '')}"))
    rows.sort(key=lambda row: row[0])
    return [text for _, text in rows[:limit]]


def situation() -> dict:
    """What she is actually doing, for a question that might be about it.

    Every part is best-effort: a conversation must not fail because the
    mission store is mid-write or a module is unavailable. Missing context
    makes an answer thinner, never absent.
    """
    facts: dict = {}
    # HIS time, not UTC. "What's on today?" answered against a UTC clock is
    # wrong for six hours out of every twenty-four, and wrong in the way
    # that looks right.
    try:
        from aletheia import localtime
        facts["clock"] = localtime.describe_now()
    except Exception:
        pass
    try:
        from aletheia import mission
        live = mission.status()
        if live.get("running"):
            facts["working_on"] = {"goal": live.get("goal"),
                                   "done": live.get("used"),
                                   "budget": live.get("budget")}
    except Exception:
        pass
    try:
        pending = [a for a in policy.all_approvals() if a["state"] == "PENDING"]
        if pending:
            facts["waiting_on_him"] = [a.get("requested_action") or a["id"]
                                       for a in pending[:5]]
    except Exception:
        pass
    try:
        from aletheia import tasks
        live_tasks = []
        for task in tasks.all_tasks():
            if task["status"] in ("COMPLETED", "CANCELLED", "FAILED_TERMINAL"):
                continue
            # WITH its deadline: "what have I got due?" is a different
            # question from "what am I working on", and without the date
            # she could only answer the second one.
            line = task["description"]
            if task.get("deadline"):
                line += f" (due {task['deadline']})"
            live_tasks.append(line)
            if len(live_tasks) >= 6:
                break
        if live_tasks:
            facts["open_tasks"] = live_tasks
    except Exception:
        pass
    try:
        facts["today"] = _todays_events()
        if not facts["today"]:
            facts.pop("today")
    except Exception:
        pass
    try:
        halted = policy.halted()
        if halted:
            facts["halted"] = halted.get("reason") or True
    except Exception:
        pass
    try:
        from aletheia import demand
        keeps_asking = demand.notable()
        if keeps_asking:
            facts["he_keeps_asking_for"] = [
                {"capability": h["capability"], "times": h["times"],
                 "status": h["status"]} for h in keeps_asking[:5]]
    except Exception:
        pass
    # LAST because it is the biggest and the least urgent: if the context has
    # to be cut to fit, the thing to lose is a remembered preference, never
    # the fact that she is halted. Recall by exact key is fine for code and
    # useless in conversation — he says "what's my sister's name", not
    # "recall people.sister" — so all of it travels and she picks.
    try:
        from aletheia import memory
        known = memory.everything()
        if known:
            facts["remembered"] = known
    except Exception:
        pass
    return facts


def _fit(context: dict, limit: int = MAX_CONTEXT_CHARS) -> str:
    """Serialise the context, dropping whole facts until it fits.

    Slicing the JSON string was the obvious version and the wrong one: it
    hands the model a truncated object that stops mid-key, and what it cuts
    is whatever happens to be last — which, once memory and the calendar
    joined, was "she is halted". Facts are dropped WHOLE, least urgent
    first, and what went is said out loud rather than silently missing.
    """
    dropped: list[str] = []
    facts = dict(context.get("situation") or {})
    body = dict(context)
    while True:
        body["situation"] = facts
        if dropped:
            body["context_trimmed"] = dropped
        text = json.dumps(body, ensure_ascii=False, indent=1)
        if len(text) <= limit or not facts:
            return text[:limit]
        # reversed insertion order: `situation` is built most-urgent-first
        victim = list(facts)[-1]
        facts.pop(victim)
        dropped.append(victim)
        if not facts:
            # Facts exhausted and still over: give up the OLDEST exchanges,
            # one at a time, rather than slicing the JSON mid-key.
            older = body.get("recent_exchanges")
            while (isinstance(older, list) and older
                   and len(json.dumps(body, ensure_ascii=False, indent=1)) > limit):
                older.pop(0)
                dropped.append("an older exchange")


def answer(question: str, *, think=None, include_thread: bool = True,
           read_files: bool = True) -> dict:
    """One question, one answer. Nothing is executed."""
    question = str(question or "").strip()
    if not question:
        raise ValueError("a question is required")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question must be under {MAX_QUESTION_CHARS} characters")
    # Halt means she stops working. Answering a question is not work, and a
    # halted assistant that also goes mute is harder to get back from — the
    # explanation of why everything stopped is exactly what he needs then.
    #
    # `subscription_text`, not `infer_text`: the CLI first and the browser
    # session behind it. Planning, filing, reminding and research have had
    # two paths since they were written; conversation had one, so an expired
    # Claude login would have taken out the only half of her he talks to
    # while everything else carried on normally.
    think = think or reasoner.subscription_text

    context = {"now": stateio.utcnow(), "situation": situation()}
    if include_thread:
        recent = _thread()
        if recent:
            context["recent_exchanges"] = recent

    # What is left for a file, once the question and a floor for the context
    # are paid for. Computed BEFORE reading rather than trimmed after, so a
    # long document is truncated with an honest marker instead of pushing the
    # whole prompt over the reasoner's ceiling and returning nothing.
    room = MAX_PROMPT_CHARS - len(question) - MIN_CONTEXT_CHARS - SECTION_OVERHEAD
    files, unreadable, carried = [], [], False
    if read_files and room > 0:
        files, unreadable = attachments(question, budget=room)
        if not files and not unreadable and include_thread:
            # He named no file THIS time. If she was just reading one, it is
            # still the subject: "make the second bullet stronger" is the
            # same conversation as "look at resume.md".
            again = _carried_over(_thread())
            if again:
                files, _gone = attachments(" ".join(again), budget=room)
                # A carried file that has since moved is NOT worth telling
                # him about: he did not ask for it this time, and "could not
                # read C:/…/resume.md" attached to an unrelated answer reads
                # like a malfunction. It simply stops being carried.
                carried = bool(files)

    sections = []
    for handle in files:
        sections.append(
            (f"--- STILL OPEN FROM A MOMENT AGO: {handle['path']} ---\n"
             if carried else
             f"--- FILE HE NAMED: {handle['named']} (read from {handle['path']}) "
             f"---\n")
            + handle["text"])
    # What she can actually do, read from the registry at the moment he
    # asked. Without this the most likely question of the whole evening —
    # "can you...?" — was answered by a model reasoning from its general
    # idea of what an assistant probably does (§104, §106). Most of those
    # answers would have been RIGHT, which is exactly what makes the wrong
    # ones impossible to spot.
    try:
        from aletheia import self_knowledge
        about_her = self_knowledge.for_question(question)
    except Exception:
        about_her = {}
    if about_her.get("matches"):
        # A "can you...?" about something not AVAILABLE is demand too, and
        # it never reaches the planner at all — he asks, she says not yet,
        # and until now that was the end of it.
        try:
            from aletheia import demand
            top = about_her["matches"][0]
            if top["status"] != "AVAILABLE":
                demand.record(top["capability"], question,
                              status=top["status"], source="converse")
        except Exception:
            pass
    if about_her:
        sections.append(
            "--- WHAT I CAN DO (my registry, read just now — quote it, do not "
            "improve on it) ---\n"
            + json.dumps(about_her, ensure_ascii=False, indent=1)[:3_500])

    # What she actually did. Without it, "did you send that email?" is
    # answered by a model producing a plausible sentence, and a made-up
    # "yes, at 2:15" is indistinguishable from a true one until he opens
    # his sent folder.
    try:
        from aletheia import recollection
        her_past = recollection.for_question(question)
    except Exception:
        her_past = {}
    if her_past:
        sections.append(
            "--- WHAT I ACTUALLY DID (my journal, read just now) ---\n"
            + json.dumps(her_past, ensure_ascii=False, indent=1)[:3_500])

    if unreadable:
        sections.append(
            "--- COULD NOT READ ---\n"
            + "\n".join(unreadable)
            + "\nTell him this plainly. Do not answer as though you had read "
              "it, and do not guess what it probably says.")
    spent = sum(len(part) for part in sections)
    if context.get("situation") or context.get("recent_exchanges"):
        left = max(MIN_CONTEXT_CHARS,
                   min(MAX_CONTEXT_CHARS,
                       MAX_PROMPT_CHARS - len(question) - spent - SECTION_OVERHEAD))
        sections.append(
            "--- CONTEXT (yours, not his — use only what is relevant) ---\n"
            + _fit(context, left))

    prompt = question + ("\n\n" + "\n\n".join(sections) if sections else "")
    if len(prompt) > MAX_PROMPT_CHARS:
        # Belt and braces. Every path above is budgeted, so reaching here is
        # a bug — but a bug that silently returns nothing is worse than one
        # that returns a slightly short prompt, and the arithmetic must never
        # be the reason she cannot answer at all.
        prompt = prompt[:MAX_PROMPT_CHARS - 60] + "\n[... context truncated]"

    try:
        said = think(SYSTEM, prompt, model=reasoner.PLAN_MODEL,
                     timeout_s=TIMEOUT_S)
        # A test's `think` hands back a plain string; the real one hands back
        # (answer, provider) so she can say which mouth spoke. Both are
        # accepted rather than forcing every caller to fake a tuple.
        provider = ""
        if isinstance(said, tuple) and len(said) == 2:
            said, provider = said
    except Exception as exc:
        # The reason is CARRIED, not swallowed into a type name. "Claude CLI
        # is not on PATH" tells him what to do; "ReasonerUnavailable" tells
        # him a class exists. Found while hardening this path: the old
        # message printed only the type and dropped the one useful sentence.
        why = str(exc).strip() or type(exc).__name__
        raise ConverseError(f"I could not reach a model to answer that: {why}."
                            + (" Sign the Claude CLI in on this machine and "
                               "ask again." if "PATH" in why or "CLI" in why
                               else "")
                            + " Everything else still works.") from None
    said = str(said or "").strip()[:MAX_ANSWER_CHARS]
    if not said:
        raise ConverseError("the model returned nothing")

    _remember_turn(question, said, [handle["path"] for handle in files])
    # The question and answer are HIS. The journal records that a
    # conversation happened, how long the answer was, and how many files she
    # opened — not what he asked and not what she said.
    journal.append("action", "converse",
                   f"answered a question ({len(question)} chars in, "
                   f"{len(said)} out, {len(files)} file(s) read"
                   + (f", via {provider}" if provider else "") + ")",
                   actor=ACTOR)
    return {"question": question, "answer": said, "at": stateio.utcnow(),
            "provider": provider,
            "files_read": [handle["path"] for handle in files],
            "unreadable": unreadable}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ask Thea something.")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--forget", action="store_true",
                    help="drop the recent thread before answering")
    args = ap.parse_args(argv)
    if args.forget:
        forget()
        if not args.question:
            print("Thread cleared.")
            return 0
    if not args.question:
        ap.error("a question is required")
    try:
        out = answer(args.question)
        for path in out["files_read"]:
            print(f"[read {path}]", file=sys.stderr)
        for miss in out["unreadable"]:
            print(f"[could not read {miss}]", file=sys.stderr)
        print(out["answer"])
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
