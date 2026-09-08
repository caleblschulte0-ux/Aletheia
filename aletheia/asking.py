"""Telling a question from a job, without asking a model which it is.

*"if I ask what's the capital of Iceland, it should come back within five
seconds and tell me Reykjavik. But if I ask it, hey, go do major work on
my repos, then it can be like, okay, I'm thinking, give me a sec."*

Two expectations, and until now everything that was not in `quick` got
the same treatment: the PLANNER, 25-80 seconds on this machine, with a
fifteen-kilobyte grammar prompt describing every capability she has —
in order to conclude that "what's the capital of Iceland" is a question.
And then `converse` ran anyway to actually answer it. Two round trips,
and the expensive one existed only to classify.

That is the same defect `quick` was written for, one layer up. `quick`
removed the round trip for things she already knows; this removes the
PLANNING round trip for things that need no plan.

    "what's the capital of Iceland"   -> converse            ~4s
    "go do major work on my repos"    -> planner, and say so  minutes

THE RULE IS THE SAME ONE AS `quick`: when in doubt it says nothing.
Returning False sends the sentence to the planner, which is slower and
much better at ambiguity. A question misread as a job costs him seconds;
a JOB misread as a question costs him the work not happening, and he
would not find out until he checked. So the test is deliberately narrow
and biased toward the planner.

It never calls a model. Asking a model whether to ask a model is the
round trip this exists to remove.
"""
from __future__ import annotations

import re

# How a person opens a question. Anchored: this is the FIRST thing said,
# after filler is stripped, so "what should I do about the boiler" is a
# question and "tell Dana what time it is" is not.
OPENERS = re.compile(
    r"^(?:what|whats|what's|who|whose|whom|when|where|why|how|which|"
    r"is|are|was|were|does|do|did|can|could|should|would|will|"
    r"tell me about|explain|describe|define|remind me what|"
    r"do you know|any idea|got any idea)\b",
    re.IGNORECASE)

# A verb that means WORK, wherever it appears. If one of these is in the
# sentence it goes to the planner however it opens — "what's the best way
# to email Dana" is a request to email Dana with a question mark on it.
#
# Biased long on purpose: a job misread as a question is the expensive
# mistake, and every word here costs at most one slow answer.
DOING = re.compile(
    r"\b(?:send|email|e-mail|text|message|call|dial|"
    r"buy|purchase|order|pay|book|reserve|schedule|cancel|subscribe|"
    r"remind|snooze|add|put|remove|delete|clear|move|rename|"
    r"create|make me|build|write|draft|compose|edit|fix|refactor|"
    r"deploy|push|merge|commit|run|execute|install|uninstall|"
    r"open|close|start|stop|halt|resume|launch|restart|"
    r"apply|submit|upload|download|scrape|crawl|"
    r"research|investigate|look into|dig into|find me|go get|"
    r"organise|organize|plan|arrange|set up|set a|book me|"
    r"check my|read my|list my|show me my|go do|handle|take care of|"
    r"work on|do major|update|change|convert|trim|join)\b",
    re.IGNORECASE)

# Her own state is `quick`'s job, and anything about HIS stores is a read
# she has a verb for. Neither belongs here: this is for the world.
ABOUT_HER_OR_HIS_STORES = re.compile(
    r"\b(?:you|your|yourself|my|mine|our|i)\b", re.IGNORECASE)

# Long enough to be a project brief rather than a question, whatever
# words it opens with.
MAX_WORDS = 30


def is_a_plain_question(said: str) -> bool:
    """Can this be answered in one breath, with no plan and no tools?

    False is the safe answer and the default. Everything uncertain goes
    to the planner, which is slower and better at ambiguity.
    """
    text = " ".join(str(said or "").split())
    if not text:
        return False
    try:
        from aletheia.voice import _without_preamble
        text = _without_preamble(text.lower().rstrip("?.! "))
    except Exception:
        text = text.lower().rstrip("?.! ")

    if len(text.split()) > MAX_WORDS:
        return False
    if not OPENERS.match(text):
        return False
    if DOING.search(text):
        return False
    # "What do you think of my plan" needs her stores and her memory; the
    # planner path carries those. This lane is for the world outside her.
    if ABOUT_HER_OR_HIS_STORES.search(text):
        return False
    return True


def expectation(said: str) -> str:
    """Which of the three speeds this sentence should feel like.

    Named for what he will experience rather than for what runs:
    "instant" is a file read, "quick" is one model round trip, and
    "working" is the one where she has to say she is thinking.
    """
    try:
        from aletheia import quick
        if quick.answer(said):
            return "instant"
    except Exception:
        pass
    return "quick" if is_a_plain_question(said) else "working"
