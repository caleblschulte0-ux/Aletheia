"""What KIND of work is this, and who should do it.

Phase 1 of the routing plan: a cheap deterministic classifier and one
table of provider preference. No model is asked which model to use -
paying a frontier round trip to choose a frontier model is the thing
this exists to avoid.

The behaviour change here is deliberately narrow, and it is the one the
plan calls out: **producing words is not a project.** "Write me an email
to Brant" was classified `working` and sent to the planner, which costs
25-80s and compiles a plan for something that is one answer. "Write and
send Brant an email" still goes to the planner, because the sending is
real work that has to pass the gates. The distinction is whether
anything LEAVES: a verb that delivers, publishes or persists.

The provider preferences are measured on his PC rather than assumed
(2026-09-08, ollama at 100% CPU, no GPU):

    "who wrote Dune"            local qwen3:8b   2.4s
    "capital of Iceland"        local qwen3:8b   3.1s
    "why does thunder happen"   local qwen3:8b   8.1s
    a two-sentence email        local qwen3:8b  12.1s
    any of the above            claude.cli      ~3.6s (round trip dominated)

So local is genuinely competitive for SHORT factual answers and loses
badly as soon as the output gets long - CPU generation is paid per token,
where a subscription call is paid per round trip. That is why simple_qa
prefers local and everything wordy does not, and it is a fact about this
machine rather than a fact about the models: a GPU would reorder this
table, which is why it is a table.

Nothing here grants authority. Choosing who REASONS never changes what
may be DONE - that stays with the capability registry, the approval
policy and the gates, whoever answered.
"""
from __future__ import annotations

import re

#: The kinds of work worth telling apart. Deliberately short: a category
#: nothing routes differently is a category that only costs maintenance.
TASK_TYPES = (
    "local_state",      # she already knows; no model at all
    "simple_qa",        # a short factual answer
    "explanation",      # a paragraph that explains something
    "writing",          # produce prose he asked for
    "rewrite",          # change prose he already has
    "summarization",    # shorten something
    "coding",           # write or reason about code
    "debugging",        # find out why something is broken
    "research",         # go and find out, from the world
    "planning",         # multi-step work with tools
    "action",           # do something that touches the world
    "unknown",
)

#: Who to ask first, and who to fall back to. One table, per the plan:
#: preference must not be scattered through the code. "local" appears
#: first ONLY where it measured faster than a round trip.
TASK_PROVIDER_POLICY: dict[str, tuple[str, ...]] = {
    "simple_qa":     ("local", "claude", "chatgpt"),
    "local_state":   (),                     # answered with no model
    "explanation":   ("claude", "chatgpt", "local"),
    "writing":       ("chatgpt", "claude", "local"),
    "rewrite":       ("chatgpt", "claude", "local"),
    "summarization": ("chatgpt", "claude", "local"),
    "coding":        ("claude", "chatgpt", "local"),
    "debugging":     ("claude", "chatgpt", "local"),
    "research":      ("claude", "chatgpt", "local"),
    "planning":      ("claude", "chatgpt", "local"),
    "action":        ("claude", "chatgpt", "local"),
    "unknown":       ("claude", "chatgpt", "local"),
}

# --- the words that decide -------------------------------------------

#: Producing words. Leading the sentence, these mean "give me prose".
_MAKES_WORDS = (
    r"write|draft|compose|pen|word|rewrite|reword|rephrase|paraphrase"
    r"|polish|tighten|shorten|lengthen|proofread|punch up|clean up"
    r"|summari[sz]e|recap|condense|translate|caption|title|name"
)

#: Changing words he already has, rather than producing new ones.
_CHANGES_WORDS = (
    r"rewrite|reword|rephrase|paraphrase|polish|tighten|shorten|lengthen"
    r"|proofread|punch up|clean up|edit|fix up|make (?:this|it|that)"
)

_SUMMARISES = r"summari[sz]e|recap|condense|tl;?dr"

#: THE line. A writing request that also delivers is not a writing
#: request - it is work, and work goes through the planner and the gates.
#:
#: Split in two because half of these words are also NOUNS, and the first
#: version got "write me an email to Brant" wrong for exactly that reason:
#: it saw "email", called the request an action, and sent the very
#: sentence this module exists to rescue back to the planner.
_DELIVERS_ALWAYS = re.compile(
    r"\b(?:send|sends|sending|publish|publishes|publishing|upload|uploads"
    r"|uploading|submit|submits|submitting|deliver|delivers|delivering"
    r"|commit|commits|push|pushes|tweet|tweets|dm|reply|replies|respond"
    r"|responds|forward|forwards)\b", re.IGNORECASE)

#: These are also NOUNS: "an email", "a text", "my file", "the post".
#: Trying to exclude them by what precedes them went wrong twice - an
#: article lookahead is not enough, because "write me an email" puts two
#: words between the verb and the noun. The reliable signal is POSITION:
#: one of these is a verb when it LEADS the sentence ("email Brant...",
#: "save this to my desktop") or follows a conjunction ("write it and
#: email her"). Anywhere else it is the thing being written, not the
#: doing of it.
_DELIVERY_NOUNS = (r"email|emails|mail|mails|text|texts|message|messages"
                   r"|post|posts|share|shares|save|saves|store|stores"
                   r"|file|files|print|prints|attach|attaches"
                   r"|schedule|schedules")
_DELIVERS_AS_VERB = re.compile(
    r"(?:^|\b(?:and|then|also|plus)\s+)(?:please\s+)?(?:"
    + _DELIVERY_NOUNS + r")\b", re.IGNORECASE)

#: Reaching outside for current facts. `review` is deliberately absent:
#: it matched "review this function for bugs" and sent a code review to
#: the web. "Reviews OF something" is the sense meant, so it must be
#: written that way rather than as a bare word.
_RESEARCHES = re.compile(
    r"\b(?:research|look up|find out|search for|google|browse|check online"
    r"|latest|current|today'?s|news|price of|reviews? of|reviews? for)\b",
    re.IGNORECASE)

_CODES = re.compile(
    r"\b(?:code|function|class|method|module|script|repo|repository|refactor"
    r"|unit test|tests?|compile|build|api|endpoint|regex|sql|query|bug"
    r"|stack ?trace|exception|traceback|python|javascript|typescript|rust"
    r"|golang|java|css|html)\b", re.IGNORECASE)

#: Something is WRONG. Deliberately without a bare "why is" / "why does":
#: "why does thunder happen" is an explanation, not a fault report, and
#: the first version of this called it debugging. The NEGATIVE forms stay,
#: because "why isn't it working" does mean something broke.
_DEBUGS = re.compile(
    r"\b(?:why (?:isn'?t|doesn'?t|won'?t|can'?t|didn'?t|hasn'?t)"
    r"|broken|failing|fails|failed|crash|crashes|crashed|error|errors"
    r"|bug|not working|stopped working|debug|diagnose|traceback"
    r"|stack ?trace|exception)\b", re.IGNORECASE)

_PLANS = re.compile(
    r"\b(?:overhaul|improve|inspect|audit|fix (?:my|the|up)|clean up my"
    r"|go (?:and )?(?:do|make|fix|improve)|apply to|handle|take care of"
    r"|sort out|deal with|work on|set up|build me|make me a)\b",
    re.IGNORECASE)

_EXPLAINS = re.compile(
    r"^(?:explain|how does|how do|how did|why does|why do|why is|why are"
    r"|what is|what are|what'?s the difference|compare|describe|walk me"
    r"|tell me (?:about|how|why))\b", re.IGNORECASE)

_LEADS_WITH_WRITING = re.compile(
    r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+|i need you to\s+"
    r"|i want you to\s+|help me\s+)?(?:" + _MAKES_WORDS + r")\b",
    re.IGNORECASE)

_LEADS_WITH_CHANGE = re.compile(
    r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?(?:"
    + _CHANGES_WORDS + r")\b", re.IGNORECASE)

_LEADS_WITH_SUMMARY = re.compile(
    r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?(?:"
    + _SUMMARISES + r")\b", re.IGNORECASE)

#: An explanation that is really a coding question: it asks how to DO
#: something in code, rather than what something is.
_ASKS_HOW_TO_CODE = re.compile(
    r"\b(?:how (?:do|would|can) (?:i|you|we)|how to)\b.{0,60}"
    r"\b(?:code|function|class|method|script|regex|sql|query|api|test|tests"
    r"|python|javascript|typescript|rust|golang|java|css|html)\b",
    re.IGNORECASE)

#: Short and factual: the shape local is actually fast at. A COMPARISON
#: is not one, however it opens - "what's the difference between rust and
#: go" was claimed by the leading "what" and labelled a short fact.
_COMPARES = re.compile(
    r"\b(?:difference|differences|compare|compared|versus|vs\.?|better than"
    r"|pros and cons|trade-?offs?)\b", re.IGNORECASE)

_SHORT_FACT = re.compile(
    r"^(?:who|what|when|where|which|how many|how much|how long|how far"
    r"|how old)\b", re.IGNORECASE)


def _normal(said: str) -> str:
    return " ".join(str(said or "").split())


def _is_a_short_fact(text: str) -> bool:
    """Opens like a short question AND is not asking for a comparison."""
    return bool(_SHORT_FACT.match(text)) and not _COMPARES.search(text)


def delivers(said: str) -> bool:
    """Does this ask for the words to go somewhere as well as exist?

    "Write me an email to Brant" does not. "Write and send Brant an
    email" does, and so does "draft it and save it to my desktop".
    """
    text = _normal(said)
    return bool(_DELIVERS_ALWAYS.search(text)
                or _DELIVERS_AS_VERB.search(text))


def task_type(said: str) -> str:
    """Cheap, deterministic, and biased toward the more capable route."""
    text = _normal(said)
    if not text:
        return "unknown"

    # Work first: a sentence that delivers or plans is work even when it
    # is phrased with a writing verb. Wrong in this direction costs a
    # round trip; wrong in the other costs the job not happening.
    if _PLANS.search(text) and not _LEADS_WITH_WRITING.match(text):
        return "planning"
    # Anything that delivers is an action, whether or not a writing verb
    # introduced it: "write and send Brant an email" and the bare "text
    # Brant that I'm late" are both work that has to pass the gates.
    # RUNNING what was written counts too - "write a script and run it"
    # and "write a function and add it to utils.py" both leave the page.
    if delivers(text) or _RUNS_IT.search(text):
        return "action"
    if _RESEARCHES.search(text):
        return "research"

    if _LEADS_WITH_SUMMARY.match(text):
        return "summarization"
    if _LEADS_WITH_CHANGE.match(text):
        return "rewrite"
    if _LEADS_WITH_WRITING.match(text):
        # "write me a function that..." is code, whoever asked for it.
        return "coding" if _CODES.search(text) else "writing"

    if _DEBUGS.search(text):
        return "debugging"
    if _EXPLAINS.match(text):
        # Checked BEFORE the code words: "what's the difference between
        # rust and go" is an explanation that happens to name languages,
        # and mislabelling it taught the scorecard about the wrong
        # category. "How do I write a decorator" stays coding below.
        if _is_a_short_fact(text):
            return "simple_qa"
        if not _ASKS_HOW_TO_CODE.search(text):
            return "explanation"
    if _CODES.search(text):
        return "coding"
    if _EXPLAINS.match(text):
        # "what is X" is a short fact; "explain X" is a paragraph.
        return "simple_qa" if _is_a_short_fact(text) else "explanation"
    if _is_a_short_fact(text):
        return "simple_qa"
    return "unknown"


def providers_for(said_or_type: str) -> tuple[str, ...]:
    """Preference order for this work, most preferred first."""
    kind = (said_or_type if said_or_type in TASK_PROVIDER_POLICY
            else task_type(said_or_type))
    return TASK_PROVIDER_POLICY.get(kind, TASK_PROVIDER_POLICY["unknown"])


#: Asking for code to be RUN is not asking for code.
_RUNS_IT = re.compile(
    r"\b(?:and )?(?:run|execute|apply|install|deploy|build it|test it"
    r"|add (?:it )?to|put (?:it|this) in)\b", re.IGNORECASE)

#: Task types whose whole product is the answer itself. Asking for one is
#: not starting a project, and routing it through the planner costs
#: 25-80s to compile steps for something that is one round trip.
ANSWER_IS_THE_WHOLE_JOB = frozenset({
    "simple_qa", "explanation", "writing", "rewrite", "summarization",
})


def answerable_directly(said: str) -> bool:
    """May this skip the planner and simply be answered?

    Deliberately conservative, and it has to stay that way: this decides
    whether real work silently becomes a chat reply. Anything that
    delivers, plans, researches or touches the world is excluded above by
    `task_type` before it can reach here.

    Code counts when he asked for the CODE. "Write a python function to
    parse dates" produces text and delivers nothing - the same shape as
    "write me an email", and it was compiling a plan. "Write a script and
    run it" delivers, so it still plans.
    """
    kind = task_type(said)
    if kind in ANSWER_IS_THE_WHOLE_JOB:
        return True
    if kind == "coding" and _LEADS_WITH_WRITING.match(_normal(said)):
        return not delivers(said) and not _RUNS_IT.search(_normal(said))
    return False


def explain(said: str) -> dict:
    """What the router decided and why - for diagnostics, never speech."""
    kind = task_type(said)
    return {"said": _normal(said)[:120], "task_type": kind,
            "delivers": delivers(said),
            "answer_is_the_whole_job": kind in ANSWER_IS_THE_WHOLE_JOB,
            "providers": list(providers_for(kind))}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Show how a request routes.")
    ap.add_argument("said", nargs="+")
    args = ap.parse_args(argv)
    print(json.dumps(explain(" ".join(args.said)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
