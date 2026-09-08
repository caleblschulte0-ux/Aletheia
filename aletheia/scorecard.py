"""What the local model has actually earned, per kind of work.

The evidence store behind adaptive routing. It answers one question -
*may the local model be authoritative for this task type yet?* - from
recorded performance rather than from anybody's opinion, and it is
willing to take the answer away again.

Three things shape it.

**Latency is a promotion gate, not a footnote.** The usual version of
this system assumes local is the fast option and the frontier is the slow
one; on this machine that is only true for short answers. Measured
2026-09-08: local qwen3:8b answered "who wrote Dune" in 2.4s and a
two-sentence email in 12.1s, against ~3.6s for a subscription round trip,
because CPU generation is paid per token where a round trip is paid once.
A local model that is 97% as good and four times slower has not earned
anything - promoting it would make his experience worse while the
scoreboard said it was getting better. So `LATENCY_MARGIN` is a hard gate
alongside quality.

**Certification is keyed to the MODEL, not the task.** A fingerprint of
the model identity is stored with the evidence; when it changes - a new
pull, a requantisation, a different model entirely - the old evidence
describes something that no longer exists and the capability drops back
to LEARNING. Evidence is about a thing, and the thing changed.

**Metadata only.** No prompts, no answers, no context - only the task
type, whether it worked, whether it agreed, and how long it took. That is
what lets this run without the training-capture opt-in, which exists
because credential redaction is not privacy redaction. The full
teacher/student corpus stays behind `training_data.capture_enabled()`
where he put it.

Everything here fails OPEN: an unreadable store, a corrupt file, a
missing key and an unexpected exception all resolve to UNPROVEN, which
means the frontier answers. A broken scoreboard must never break a
request, and must never silently hand work to an unproven model.
"""
from __future__ import annotations

import datetime as dt
import json
import threading

from aletheia import stateio

#: Statuses, weakest first. Order is meaningful: `_AT_LEAST` compares by it.
UNPROVEN = "UNPROVEN"
LEARNING = "LEARNING"
CANDIDATE = "CANDIDATE"
CERTIFIED = "CERTIFIED"
PROBATION = "PROBATION"

STATUSES = (UNPROVEN, LEARNING, CANDIDATE, CERTIFIED, PROBATION)

#: How the router should behave for each status.
ROUTE_FRONTIER = "frontier_authoritative_local_shadow"
ROUTE_HEDGED = "hedged"
ROUTE_LOCAL = "local_authoritative_frontier_fallback"

#: Promotion thresholds. Deliberately conservative, and deliberately
#: constants so the tests can be exact about them.
LEARNING_AFTER = 5           # enough to have seen it work at all
CANDIDATE_ATTEMPTS = 30
CANDIDATE_VALID = 0.95
CANDIDATE_AGREEMENT = 0.93
CERTIFIED_ATTEMPTS = 100
CERTIFIED_VALID = 0.97
CERTIFIED_AGREEMENT = 0.96
MAX_CORRECTION_RATE = 0.05

#: Local may be at most this multiple of the frontier's median latency and
#: still certify. Above 1.0 because a small slowdown is worth the privacy
#: and independence; not far above it, because he notices seconds.
LATENCY_MARGIN = 1.25

#: Demotion. A certified capability that starts failing goes to PROBATION
#: rather than quietly staying certified.
DEMOTE_WINDOW = 20
DEMOTE_FAILURE_RATE = 0.15
DEMOTE_CORRECTION_RATE = 0.15

#: Keep files small and recent-weighted: only the last N outcomes matter
#: for demotion, and only the last N latencies for the median.
RECENT = 50

#: Past this multiple of the frontier's median, shadowing this task type
#: is spending his CPU to learn something that can never be acted on.
#:
#: Set as twice LATENCY_MARGIN rather than picked: the margin is the bar
#: for promotion, so a task type sitting far above it has no realistic
#: path to certification however good its answers are, and every further
#: shadow is CPU spent to re-learn that. Left with real headroom above
#: the margin because timings move - a busy machine, a cold model, a slow
#: round trip - and giving up on learning should need clearer evidence
#: than declining to promote. Measured here: writing runs 12.1s against
#: 3.6s (3.4x, gives up), simple_qa 2.4s against 3.6s (0.7x, keeps going).
GIVE_UP_FACTOR = LATENCY_MARGIN * 2.0

#: Do not give up on a handful of samples; a cold model load is not proof.
GIVE_UP_AFTER = 12

#: Risk classes. Strong performance on casual questions must not promote
#: local authority for work that can hurt.
RISK_LOW, RISK_NORMAL, RISK_HIGH, RISK_CRITICAL = (
    "low", "normal", "high", "critical")

#: HIGH and CRITICAL never certify from evidence alone.
CERTIFIABLE_RISK = {RISK_LOW, RISK_NORMAL}

#: Per task type. Anything that reasons about code, plans work or touches
#: the world stays with the frontier however good local looks on trivia.
TASK_RISK = {
    "simple_qa": RISK_LOW,
    "explanation": RISK_LOW,
    "summarization": RISK_NORMAL,
    "writing": RISK_NORMAL,
    "rewrite": RISK_NORMAL,
    "research": RISK_HIGH,
    "coding": RISK_HIGH,
    "debugging": RISK_HIGH,
    "planning": RISK_CRITICAL,
    "action": RISK_CRITICAL,
    "unknown": RISK_CRITICAL,
}

_LOCK = threading.Lock()


def risk_of(task_type: str) -> str:
    return TASK_RISK.get(str(task_type), RISK_CRITICAL)


def store_dir():
    return stateio.private_dir("routing")


def _path(task_type: str):
    return store_dir() / f"{stateio.safe_id(str(task_type), name='task type')}.json"


def _blank(task_type: str, fingerprint: str) -> dict:
    return {"version": 1, "task_type": str(task_type), "fingerprint": fingerprint,
            "attempts": 0, "valid": 0, "agreed": 0, "compared": 0,
            "corrections": 0, "timeouts": 0,
            "recent": [], "local_ms": [], "frontier_ms": [],
            "status": UNPROVEN, "probation_reason": "",
            "updated_at": stateio.utcnow()}


def read(task_type: str) -> dict:
    """Never raises. An unreadable scoreboard means UNPROVEN."""
    try:
        value = stateio.read_json(_path(task_type))
        if isinstance(value, dict) and value.get("version") == 1:
            return value
    except (OSError, ValueError, TypeError):
        pass
    return _blank(task_type, "")


def _median(values: list[int | float]) -> float | None:
    numbers = sorted(v for v in values if isinstance(v, (int, float))
                     and not isinstance(v, bool))
    if not numbers:
        return None
    middle = len(numbers) // 2
    if len(numbers) % 2:
        return float(numbers[middle])
    return (numbers[middle - 1] + numbers[middle]) / 2.0


def _rate(part: int, whole: int) -> float:
    return (part / whole) if whole else 0.0


def latency_verdict(record: dict) -> tuple[bool, str]:
    """Is local fast enough to be worth handing the work to?

    The gate this system usually forgets. Returns (ok, why) so the reason
    can be shown in diagnostics rather than inferred from a boolean.
    """
    local = _median(record.get("local_ms") or [])
    frontier = _median(record.get("frontier_ms") or [])
    if local is None:
        return False, "no local timings yet"
    if frontier is None:
        # Nothing to compare against. Do not certify on faith.
        return False, "no frontier timings to compare against"
    if local <= frontier * LATENCY_MARGIN:
        return True, f"local {local:.0f}ms vs frontier {frontier:.0f}ms"
    return False, (f"local {local:.0f}ms is slower than "
                   f"{LATENCY_MARGIN:g}x frontier {frontier:.0f}ms")


def worth_shadowing(task_type: str) -> tuple[bool, str]:
    """Should a background student still attempt this kind of work?

    Never raises: when in doubt, shadow. Losing a training example is
    cheap and refusing to learn is not, so only clear evidence stops it.
    """
    try:
        record = read(task_type)
        if record.get("status") == CERTIFIED:
            return False, "already certified; local is answering these"
        local = _median(record.get("local_ms") or [])
        frontier = _median(record.get("frontier_ms") or [])
        samples = min(len(record.get("local_ms") or []),
                      len(record.get("frontier_ms") or []))
        if local is None or frontier is None or samples < GIVE_UP_AFTER:
            return True, "still gathering"
        if local > frontier * GIVE_UP_FACTOR:
            return False, (f"local median {local:.0f}ms is more than "
                           f"{GIVE_UP_FACTOR:g}x the frontier's {frontier:.0f}ms "
                           f"on this hardware")
        return True, "still competitive"
    except Exception:
        return True, "no evidence either way"


def note_skip(task_type: str, why: str) -> None:
    """Record that a shadow was skipped, so it can be explained later."""
    try:
        with _LOCK:
            current = read(task_type)
            current["skips"] = int(current.get("skips") or 0) + 1
            current["last_skip"] = str(why)[:200]
            current["updated_at"] = stateio.utcnow()
            stateio.write_json_atomic(_path(task_type), current)
    except Exception:
        pass


def _should_demote(record: dict) -> str:
    recent = [bool(x) for x in (record.get("recent") or [])][-DEMOTE_WINDOW:]
    if len(recent) < DEMOTE_WINDOW:
        return ""
    failures = _rate(sum(1 for ok in recent if not ok), len(recent))
    if failures > DEMOTE_FAILURE_RATE:
        return f"recent failure rate {failures:.0%}"
    corrections = _rate(int(record.get("corrections") or 0),
                        max(1, int(record.get("attempts") or 0)))
    if corrections > DEMOTE_CORRECTION_RATE:
        return f"correction rate {corrections:.0%}"
    return ""


def _earned(record: dict, task_type: str) -> tuple[str, str]:
    """The status this evidence supports, and why. Pure - no I/O."""
    attempts = int(record.get("attempts") or 0)
    if attempts < LEARNING_AFTER:
        return UNPROVEN, f"only {attempts} attempts"

    risk = risk_of(task_type)
    valid = _rate(int(record.get("valid") or 0), attempts)
    compared = int(record.get("compared") or 0)
    agreement = _rate(int(record.get("agreed") or 0), compared)
    corrections = _rate(int(record.get("corrections") or 0), attempts)
    fast_enough, why_latency = latency_verdict(record)

    if corrections > MAX_CORRECTION_RATE:
        return LEARNING, f"correction rate {corrections:.0%}"

    meets_certified = (attempts >= CERTIFIED_ATTEMPTS
                       and valid >= CERTIFIED_VALID
                       and compared >= CERTIFIED_ATTEMPTS // 2
                       and agreement >= CERTIFIED_AGREEMENT)
    meets_candidate = (attempts >= CANDIDATE_ATTEMPTS
                       and valid >= CANDIDATE_VALID
                       and compared >= CANDIDATE_ATTEMPTS // 2
                       and agreement >= CANDIDATE_AGREEMENT)

    if meets_certified and risk not in CERTIFIABLE_RISK:
        # Earned on the numbers; refused on the stakes.
        return CANDIDATE, f"{risk} risk never certifies from evidence alone"
    if meets_certified and not fast_enough:
        return CANDIDATE, why_latency
    if meets_certified:
        return CERTIFIED, why_latency
    if meets_candidate:
        return CANDIDATE, f"valid {valid:.0%}, agreement {agreement:.0%}"
    return LEARNING, f"{attempts} attempts, valid {valid:.0%}"


def status(task_type: str, *, fingerprint: str | None = None) -> str:
    """What the local model may do for this task type right now."""
    try:
        record = read(task_type)
        if fingerprint and record.get("fingerprint") not in ("", fingerprint):
            # The evidence describes a model that is no longer installed.
            return LEARNING
        if record.get("status") == PROBATION:
            return PROBATION
        return _earned(record, task_type)[0]
    except Exception:
        return UNPROVEN


def route_for(task_type: str, *, fingerprint: str | None = None) -> str:
    """How to run this request, given what local has earned."""
    current = status(task_type, fingerprint=fingerprint)
    if current == CERTIFIED:
        return ROUTE_LOCAL
    if current == CANDIDATE:
        return ROUTE_HEDGED
    return ROUTE_FRONTIER


def record(task_type: str, *, fingerprint: str = "", ok: bool = True,
           agreed: bool | None = None, local_ms: int | None = None,
           frontier_ms: int | None = None, corrected: bool = False,
           timed_out: bool = False) -> dict:
    """Add one outcome. Never raises: evidence is not worth a failed reply.

    `agreed` is None when there was nothing to compare against, which is
    different from disagreeing and must not be counted as either.
    """
    try:
        with _LOCK:
            current = read(task_type)
            if fingerprint and current.get("fingerprint") != fingerprint:
                if current.get("fingerprint"):
                    # The model changed. Old numbers describe something
                    # else; keep none of them rather than average across.
                    current = _blank(task_type, fingerprint)
                else:
                    current["fingerprint"] = fingerprint

            current["attempts"] = int(current.get("attempts") or 0) + 1
            if ok:
                current["valid"] = int(current.get("valid") or 0) + 1
            if agreed is not None:
                current["compared"] = int(current.get("compared") or 0) + 1
                if agreed:
                    current["agreed"] = int(current.get("agreed") or 0) + 1
            if corrected:
                current["corrections"] = int(current.get("corrections") or 0) + 1
            if timed_out:
                current["timeouts"] = int(current.get("timeouts") or 0) + 1

            recent = list(current.get("recent") or [])
            recent.append(bool(ok))
            current["recent"] = recent[-RECENT:]

            for key, value in (("local_ms", local_ms), ("frontier_ms", frontier_ms)):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    samples = list(current.get(key) or [])
                    samples.append(int(value))
                    current[key] = samples[-RECENT:]

            reason = _should_demote(current)
            was = current.get("status")
            if reason and was == CERTIFIED:
                current["status"] = PROBATION
                current["probation_reason"] = reason
            elif current.get("status") != PROBATION:
                current["status"] = _earned(current, task_type)[0]

            current["updated_at"] = stateio.utcnow()
            stateio.write_json_atomic(_path(task_type), current)
            return current
    except Exception:
        return {}


def probation(task_type: str, reason: str = "set by the operator") -> dict:
    """Send a capability back to the frontier by hand."""
    try:
        with _LOCK:
            current = read(task_type)
            current["status"] = PROBATION
            current["probation_reason"] = str(reason)[:200]
            current["updated_at"] = stateio.utcnow()
            stateio.write_json_atomic(_path(task_type), current)
            return current
    except Exception:
        return {}


def reset(task_type: str) -> dict:
    """Forget everything about this task type and start again."""
    try:
        with _LOCK:
            blank = _blank(task_type, "")
            stateio.write_json_atomic(_path(task_type), blank)
            return blank
    except Exception:
        return {}


def explain(task_type: str, *, fingerprint: str | None = None) -> dict:
    """Everything a diagnostic should show. Never speech."""
    current = read(task_type)
    attempts = int(current.get("attempts") or 0)
    compared = int(current.get("compared") or 0)
    earned, why = _earned(current, task_type)
    fast_enough, why_latency = latency_verdict(current)
    live = status(task_type, fingerprint=fingerprint)
    return {
        "task_type": task_type,
        "status": live,
        "route": route_for(task_type, fingerprint=fingerprint),
        "risk": risk_of(task_type),
        "attempts": attempts,
        "valid_rate": round(_rate(int(current.get("valid") or 0), attempts), 3),
        "compared": compared,
        "agreement": round(_rate(int(current.get("agreed") or 0), compared), 3),
        "correction_rate": round(
            _rate(int(current.get("corrections") or 0), attempts), 3),
        "timeouts": int(current.get("timeouts") or 0),
        "local_median_ms": _median(current.get("local_ms") or []),
        "frontier_median_ms": _median(current.get("frontier_ms") or []),
        "fast_enough": fast_enough,
        "why": current.get("probation_reason") if live == PROBATION else why,
        "why_latency": why_latency,
        "fingerprint": current.get("fingerprint") or "",
        "shadowing": worth_shadowing(task_type)[0],
        "why_not_shadowing": (None if worth_shadowing(task_type)[0]
                              else worth_shadowing(task_type)[1]),
        "skips": int(current.get("skips") or 0),
        "updated_at": current.get("updated_at"),
    }


def everything(*, fingerprint: str | None = None) -> dict:
    """Every task type that has any evidence, plus the ones that do not."""
    from aletheia import routing
    out = {}
    for kind in routing.TASK_TYPES:
        if kind == "local_state":
            continue          # answered with no model; nothing to score
        out[kind] = explain(kind, fingerprint=fingerprint)
    return out
