"""How fast she talks, set by his word: "talk slower", "speak faster".

"Slower" and "talk slower" went to the planner (2026-10-07), and the room
voice had one speed written into it. One small record in private state - a
step from -3 (slowest) to 3 (fastest), 0 when he has never said - is read
by both mouths: the Windows voice as its Rate, Piper as its length scale.
"""
from __future__ import annotations

from aletheia import stateio

ACTIONS = frozenset({"slower", "faster", "normal"})
LOWEST, HIGHEST = -3, 3
# The Windows voice talked at Rate 1 before there was a setting.
SAPI_AT_NORMAL = 1


def _path():
    return stateio.private_dir("voice") / "pace.json"


def step() -> int:
    """The pace he set, -3..3. 0 when unset or unreadable. Never raises."""
    try:
        value = int((stateio.read_json(_path()) or {}).get("step", 0))
    except Exception:
        return 0
    return max(LOWEST, min(HIGHEST, value))


def sapi_rate() -> int:
    """The Windows voice's Rate (-10..10) for the pace he set."""
    return SAPI_AT_NORMAL + 2 * step()


def piper_length_scale() -> float:
    """Piper's --length_scale: above 1 is slower, below 1 faster."""
    return round(1.15 ** (-step()), 2)


def _words(value: int) -> str:
    if value == 0:
        return "my normal speed"
    how = {1: "a little", 2: "quite a bit", 3: "much"}[abs(value)]
    return f"{how} {'slower' if value < 0 else 'faster'} than normal"


def act(action: str) -> str:
    """Slower, faster or back to normal; the sentence says where it is now."""
    if action not in ACTIONS:
        raise ValueError(f"speaking pace action must be one of {sorted(ACTIONS)}")
    now = step()
    if action == "normal":
        new = 0
    else:
        new = now + (-1 if action == "slower" else 1)
        if new < LOWEST or new > HIGHEST:
            return f"That's already as {'slow' if action == 'slower' else 'fast'} as I go."
    stateio.write_json_atomic(_path(), {"step": new})
    return "Back to my normal speed." if new == 0 else f"Okay - {_words(new)} now."


def spoken() -> str:
    """How fast she is talking. Never raises."""
    return f"I'm talking at {_words(step())}."
