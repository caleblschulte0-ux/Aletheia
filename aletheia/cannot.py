"""Saying "I can't do that yet" in half a second instead of forty.

"Set a timer for ten minutes" took a planner round trip — twenty-five to
eighty seconds on this machine — to come back with "I can't do
timer.set yet; filed 1 build task". He waited most of a minute to be
told no. Every one of those is worse than a fast no, and there are
several a day: timers, music, the lights, the weather.

This is `quick`'s argument applied to REFUSALS. `quick` removed the
round trip for things she already knows; the round trip for things she
already knows she cannot do is the same waste, and it is more annoying
because the answer is a disappointment either way. A slow no is a no he
had to wait for.

THREE RULES, and the last one is why this is safe.

**It reads the registry.** Nothing here has a hard-coded list of what
she cannot do — the sentence patterns name a CAPABILITY, and whether
she can do it is looked up. The day `media.play` becomes AVAILABLE, the
pattern stops firing and the sentence goes to the planner that can now
serve it. A refusal frozen in code would still be refusing next year.

**It still counts.** `demand.record` is how "what should we build next"
is answered, and the planner path fed it. Skipping the planner must not
mean his asks stop being counted — that would make the thing he wants
most look like the thing he stopped asking for, which CLAUDE.md warns
about in as many words.

**It says what would make it work.** NOT_BUILT and
NEEDS_CONFIGURATION are different answers to him: one is "this does not
exist yet", the other is "this exists and needs a token from you". The
second is a thing he can fix in five minutes, and telling him so is the
whole difference between a dead end and a next step.
"""
from __future__ import annotations

import re

# (what he said, the capability it needs, how she says no).
#
# Narrow and anchored, the same discipline as `quick`: a sentence that
# only LOOKS like one of these must fall through to the planner, which
# is slower and much better at ambiguity.
WISHES: tuple[tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"^set (?:a |an )?(?:timer|alarm)\b"
                r"|^(?:wake me|time me)\b"
                r"|^start (?:a )?(?:timer|stopwatch)\b", re.I),
     "timer.set", "set timers"),
    (re.compile(r"^(?:play|put on|pause|skip|stop) (?:some |the |my )?"
                r"(?:music|a song|songs|spotify|a playlist|the playlist)\b"
                r"|^play (?:me )?(?:something|anything)\b", re.I),
     "media.play", "play music"),
    # An adjective or two in the middle is how a person names a light:
    # "the KITCHEN lights", "the bedroom lamp". Only the bare "the
    # lights" matched, which is not how anybody with more than one room
    # says it. Bounded at two words so "turn off the tap in the kitchen
    # sink" cannot wander into it.
    (re.compile(r"^(?:turn|switch) (?:on|off) (?:the |my )?(?:\w+ ){0,2}(?:lights?|lamp"
                r"|heating|heat|ac|air con\w*|thermostat|fan|tv)\b"
                r"|^(?:dim|brighten) the lights?\b"
                r"|^set the (?:thermostat|temperature)\b", re.I),
     "room.scene", "control the lights and devices"),
    (re.compile(r"^(?:what'?s|hows?|how is) the weather\b"
                r"|^(?:is it|will it be) (?:going to )?(?:rain|snow|sunny|cold|hot)\b"
                r"|^what'?s the (?:forecast|temperature) (?:today|tomorrow|outside)\b",
                re.I),
     "weather.read", "check the weather"),
)


def _status(capability: str) -> str | None:
    """What the registry says, or None if it does not know the id.

    An unknown id is not a refusal: a pattern naming a capability that
    does not exist is a bug in the pattern, and the planner is a better
    place to be wrong than a confident no.
    """
    try:
        from aletheia import capabilities
        return capabilities.get(capability)["status"]
    except Exception:
        return None


def answer(said: str) -> str | None:
    """A fast, honest no — or None, which means let the planner try.

    Never raises. A shortcut that can break a request is worse than no
    shortcut, because the slow path was working.
    """
    text = " ".join(str(said or "").split())
    if not text:
        return None
    try:
        for pattern, capability, doing in WISHES:
            if not pattern.match(text):
                continue
            status = _status(capability)
            if status in ("AVAILABLE", "EXPERIMENTAL", None):
                # She can do it, or the registry does not know the id.
                # Either way this is not the place to answer.
                return None
            _count_it(capability, text, status)
            if status == "NEEDS_CONFIGURATION":
                return (f"I can {doing} — it just needs setting up first. "
                        "Say \"what do you still need from me\" and I'll "
                        "tell you exactly what.")
            return (f"I can't {doing} yet. It's on the list, and I've "
                    "counted that you asked.")
    except Exception:
        return None
    return None


def _count_it(capability: str, said: str, status: str) -> None:
    """His ask, in his own words, in the ledger that decides what to build.

    The planner path recorded this. Skipping the planner must not mean
    his asks stop being counted — that would make the thing he wants
    most look like the thing he stopped asking for.
    """
    try:
        from aletheia import demand
        demand.record(capability, said, status=status, source="fast-refusal")
    except Exception:
        pass
