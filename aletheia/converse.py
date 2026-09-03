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
import json
import re
import sys
from pathlib import Path

from aletheia import journal, policy, reasoner, stateio, workspace

ACTOR = "aletheia-converse"

THREAD_PATH = stateio.private_dir("conversation") / "recent.json"

# Memory is trimmed by SIZE, not by a turn count. Eight turns of one-line
# answers is nothing; eight turns of long ones is a slow expensive question
# every time. What matters is how much travels, so that is what is bounded.
KEEP_TURNS = 24
MAX_THREAD_CHARS = 12_000

MAX_QUESTION_CHARS = 4_000
MAX_ANSWER_CHARS = 6_000

# A thoughtful answer takes longer than an interpretation. The default 90s
# is sized for classifying a sentence; a real reply to a real question is
# allowed three minutes before we call it a failure.
TIMEOUT_S = 180.0

# Files she may pull in when he names one. Two, because "compare these"
# is common and "read my whole folder" is a different request with a
# different tool (research/script), not a chat message.
MAX_ATTACHED = 2
MAX_ATTACHED_CHARS = 30_000

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

You do not take actions in this reply. If answering properly means doing
something — sending, writing a file, changing anything — say what you
would do and let him ask for it."""


class ConverseError(RuntimeError):
    pass


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


def _remember_turn(question: str, answer: str) -> None:
    """Keep the last few exchanges so 'what about the other one?' resolves."""
    turns = _thread()
    turns.append({"at": stateio.utcnow(), "you": question[:600],
                  "her": answer[:900]})
    stateio.write_json_atomic(THREAD_PATH, {"turns": _trim(turns)})


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

READABLE_SUFFIXES = frozenset(workspace.TEXT_SUFFIXES)

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


def attachments(question: str) -> tuple[list[dict], list[str]]:
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
    budget = MAX_ATTACHED_CHARS
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


def situation() -> dict:
    """What she is actually doing, for a question that might be about it.

    Every part is best-effort: a conversation must not fail because the
    mission store is mid-write or a module is unavailable. Missing context
    makes an answer thinner, never absent.
    """
    facts = {}
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
        live_tasks = [t["description"] for t in tasks.all_tasks()
                      if t["status"] not in ("COMPLETED", "CANCELLED",
                                             "FAILED_TERMINAL")][:6]
        if live_tasks:
            facts["open_tasks"] = live_tasks
    except Exception:
        pass
    try:
        halted = policy.halted()
        if halted:
            facts["halted"] = halted.get("reason") or True
    except Exception:
        pass
    return facts


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
    think = think or reasoner.infer_text

    context = {"now": stateio.utcnow(), "situation": situation()}
    if include_thread:
        recent = _thread()
        if recent:
            context["recent_exchanges"] = recent

    files, unreadable = ([], []) if not read_files else attachments(question)

    sections = []
    for handle in files:
        sections.append(
            f"--- FILE HE NAMED: {handle['named']} (read from {handle['path']}) "
            f"---\n{handle['text']}")
    if unreadable:
        sections.append(
            "--- COULD NOT READ ---\n"
            + "\n".join(unreadable)
            + "\nTell him this plainly. Do not answer as though you had read "
              "it, and do not guess what it probably says.")
    if context.get("situation") or context.get("recent_exchanges"):
        sections.append(
            "--- CONTEXT (yours, not his — use only what is relevant) ---\n"
            + json.dumps(context, ensure_ascii=False, indent=1)[:6_000])

    prompt = question + ("\n\n" + "\n\n".join(sections) if sections else "")

    try:
        said = think(SYSTEM, prompt, model=reasoner.PLAN_MODEL,
                     timeout_s=TIMEOUT_S)
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

    _remember_turn(question, said)
    # The question and answer are HIS. The journal records that a
    # conversation happened, how long the answer was, and how many files she
    # opened — not what he asked and not what she said.
    journal.append("action", "converse",
                   f"answered a question ({len(question)} chars in, "
                   f"{len(said)} out, {len(files)} file(s) read)", actor=ACTOR)
    return {"question": question, "answer": said, "at": stateio.utcnow(),
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
