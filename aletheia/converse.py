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
import sys

from aletheia import journal, policy, reasoner, stateio

ACTOR = "aletheia-converse"

THREAD_PATH = stateio.private_dir("conversation") / "recent.json"
KEEP_TURNS = 8              # what travels with the next question
MAX_QUESTION_CHARS = 4_000
MAX_ANSWER_CHARS = 6_000

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

What you know about right now travels with the question under CONTEXT:
what you are working on, what is waiting for him, what he asked you to
remember. Use it when it is relevant and ignore it when it is not. Do not
recite it back at him.

You do not take actions in this reply. If answering properly means doing
something — sending, writing a file, changing anything — say what you
would do and let him ask for it."""


class ConverseError(RuntimeError):
    pass


def _thread() -> list[dict]:
    try:
        value = stateio.read_json(THREAD_PATH)
    except (OSError, ValueError):
        return []
    turns = value.get("turns") if isinstance(value, dict) else None
    return turns if isinstance(turns, list) else []


def _remember_turn(question: str, answer: str) -> None:
    """Keep the last few exchanges so 'what about the other one?' resolves.

    Bounded hard: an unbounded transcript turns every question into a slow,
    expensive one, and the tail of it stops being relevant long before it
    stops being sent.
    """
    turns = _thread()
    turns.append({"at": stateio.utcnow(), "you": question[:600],
                  "her": answer[:900]})
    stateio.write_json_atomic(THREAD_PATH, {"turns": turns[-KEEP_TURNS:]})


def forget() -> None:
    """Drop the thread. A new subject should not inherit the last one."""
    stateio.write_json_atomic(THREAD_PATH, {"turns": []})


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


def answer(question: str, *, think=None, include_thread: bool = True) -> dict:
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

    prompt = question
    if context.get("situation") or context.get("recent_exchanges"):
        prompt = (question + "\n\nCONTEXT (yours, not his — use only what is "
                  "relevant):\n"
                  + json.dumps(context, ensure_ascii=False, indent=1)[:6_000])

    try:
        said = think(SYSTEM, prompt, model=reasoner.PLAN_MODEL)
    except Exception as exc:
        raise ConverseError(
            f"I could not reach a model to answer that ({type(exc).__name__}). "
            "Everything else still works.") from None
    said = str(said or "").strip()[:MAX_ANSWER_CHARS]
    if not said:
        raise ConverseError("the model returned nothing")

    _remember_turn(question, said)
    # The question and answer are HIS. The journal records that a
    # conversation happened and how long the answer was — not what he
    # asked and not what she said.
    journal.append("action", "converse",
                   f"answered a question ({len(question)} chars in, "
                   f"{len(said)} out)", actor=ACTOR)
    return {"question": question, "answer": said, "at": stateio.utcnow()}


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
        print(answer(args.question)["answer"])
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
