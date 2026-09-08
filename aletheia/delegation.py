"""Should this be a team at all? Usually not.

A runtime that can assemble workers will assemble them for everything
unless something says no, and a team is the most expensive thing this
system can do: minutes, where the fast lane answers in milliseconds. The
failure mode is not "too few agents". It is four workers deliberating
over what time it is.

So this is written as a series of REFUSALS, and delegation is what is
left when none of them fire.

THE ORDER MATTERS, cheapest first:

1. **Does it need a model at all?** `quick` answers from a store and
   `voice.interpret` compiles a command. Either one means the answer
   costs nothing, and a team would be minutes spent reaching the same
   place. This catches most of what he says.
2. **Is it one small thing?** One verb, one object, no comparison — one
   worker, or no worker.
3. **Would the workers differ?** Delegation buys independence. Asking
   three workers the same question with the same context gets three
   copies of one answer, more slowly, and then a synthesis that reports
   false consensus.

What survives all three is the shape a team is actually for: a decision
with sides, a review that should be adversarial, research with separable
strands.

IT RETURNS A REASON EITHER WAY. "No, because `quick` already answers
this" is a fact he can check, and a delegation decision he cannot inspect
is one he has to trust. Nothing here calls a model to decide whether to
call a model.
"""
from __future__ import annotations

import re

from aletheia import agents

# The words a person uses when they want more than one opinion. Each is
# an ASK for independence rather than a topic that happens to be hard.
WANTS_INDEPENDENCE = re.compile(
    r"\b(?:opinions?|second opinion|independent|independently|"
    r"different (?:views?|angles?|takes?|opinions?)|"
    r"(?:argue|debate|disagree|tear (?:it|this) apart|"
    r"poke holes|red[- ]team|stress[- ]test)|"
    r"pros and cons|both sides|devil'?s advocate|"
    r"have (?:someone|somebody|another) (?:check|review|verify|look))\b",
    re.IGNORECASE)

# A decision, rather than a lookup. "Should we" is the shape.
A_DECISION = re.compile(
    r"^\s*(?:should (?:we|i|he|she|they)|is it worth|"
    r"would it be better|do you think we should|"
    r"what(?:'s| is) the best (?:way|approach|option)|"
    r"which (?:should|would) (?:we|i))\b",
    re.IGNORECASE)

# Separable strands: he named more than one concern in one breath.
AND_ALSO = re.compile(r"\b(?:and also|as well as|plus|along with|"
                      r"and then|,\s*and\b)", re.IGNORECASE)

# Below this a request is one thing, whatever words it uses.
SHORT_ENOUGH_TO_BE_SIMPLE = 8


def _already_answered(request: str) -> str:
    """The name of the cheap path that handles this, or ""."""
    try:
        from aletheia import quick
        if quick.answer(request):
            return "quick"
    except Exception:
        pass
    try:
        from aletheia import voice
        got = voice.interpret(request) or {}
        kind = (got.get("command") or {}).get("kind")
        if kind and kind != "intent":
            return f"the {kind} verb"
        if got.get("say") and not kind:
            return "a direct answer"
    except Exception:
        pass
    return ""


def decide(request: str) -> dict:
    """{delegate, why, roles} — and `why` is readable either way.

    Deterministic on purpose. Asking a model whether to ask a model
    costs the round trip the decision exists to avoid, and makes the
    reason something he has to take on faith.
    """
    text = " ".join(str(request or "").split())
    if not text:
        return {"delegate": False, "why": "there is nothing to work on",
                "roles": []}

    cheap = _already_answered(text)
    if cheap:
        return {"delegate": False,
                "why": f"{cheap} already answers this — a team would be "
                       "minutes to reach the same place",
                "roles": []}

    words = len(text.split())
    wants_independence = bool(WANTS_INDEPENDENCE.search(text))
    is_decision = bool(A_DECISION.search(text))
    many_strands = bool(AND_ALSO.search(text))

    if words < SHORT_ENOUGH_TO_BE_SIMPLE and not wants_independence:
        return {"delegate": False,
                "why": "it is one small thing; one worker is the whole job",
                "roles": []}

    if not (wants_independence or is_decision or many_strands):
        return {"delegate": False,
                "why": "nothing here would differ between workers — three "
                       "copies of one answer, more slowly",
                "roles": []}

    # What survives is genuinely a team. Roles are chosen so the workers
    # DISAGREE: the same question three times is not independence.
    roles: list[str] = []
    if is_decision or wants_independence:
        roles = ["the case for", "the case against", "what would have to be true"]
    if many_strands and not roles:
        roles = ["research", "risks"]
    if wants_independence and not is_decision and not many_strands:
        roles = ["a first answer", "an adversarial review of it"]

    # Never more than the machine can actually run at once. A plan for
    # five workers on hardware that refuses half of them is a plan to
    # discover that under load.
    roles = roles[:max(2, agents.MAX_PARALLEL + 1)]

    reasons = []
    if wants_independence:
        reasons.append("he asked for independent views")
    if is_decision:
        reasons.append("it is a decision with sides")
    if many_strands:
        reasons.append("it has separable strands")
    return {"delegate": True, "why": " and ".join(reasons), "roles": roles}


def spoken(decision: dict) -> str:
    """Said out loud, because he should hear WHY she is taking minutes."""
    if not decision.get("delegate"):
        return f"Answering that directly — {decision.get('why', '')}."
    from aletheia import speech
    roles = decision.get("roles") or []
    return (f"Putting {speech.count_phrase(len(roles), 'worker')} on that — "
            f"{decision.get('why')}. This takes a few minutes.")
