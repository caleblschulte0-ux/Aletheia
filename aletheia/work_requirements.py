"""Can this step run RIGHT NOW? One live check per requirement, cached.

His continuity brief, Part II.2: work states what it requires, and Aletheia
understands "I cannot do this particular step right now", not "I cannot work".
The names are `work_states.REQUIREMENTS`; this module answers each one.

INSTALLED IS NOT WORKING (CLAUDE.md). Where the real attempt is cheap it is made
(a TCP connect for the network, a GitHub token verified against the API, Ollama's
own listing); where it is expensive (a browser loading a page) it is made only
when `probe=True` and the result is cached, in memory and in private state, so a
beat does not launch a browser every minute and a restart does not forget. With
`probe=False` (the read-only inventory) an expensive check reports its last real
result, or says plainly that it is unverified.

Two kinds of requirement:

- WORLD requirements (reasoning, browser, network, github, email, calendar,
  filesystem, terminal, code_execution) are facts about the machine and accounts.
- ITEM requirements (user_approval, user_decision, login, external_reply,
  payment) are facts about ONE piece of work: satisfied only by evidence the item
  itself carries (an APPROVED approval id, his recorded decision, a reply that
  arrived). She never satisfies them for herself: an approval she cannot see is
  not an approval, and `payment` is never satisfied by her at all - money is his.

Every check returns {"requirement", "ok", "why", "live", "checked_at",
"blocked_state", "wake", "not_before"}. Never raises.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import socket
import sys
import time
from typing import Any, Callable

from aletheia import stateio, work_states as ws

#: Seconds a world check stays fresh.
TTL_S = {
    "local_reasoning": 60.0, "frontier_reasoning": 60.0, "reasoning": 60.0,
    "browser": 1800.0, "network": 120.0, "github": 1800.0, "email": 300.0,
    "calendar": 300.0, "filesystem": 300.0, "terminal": 600.0, "code_execution": 600.0,
}
#: How long a transient failure waits before the picker looks again.
RETRY_AFTER = {"browser": dt.timedelta(minutes=30), "network": dt.timedelta(minutes=5),
               "filesystem": dt.timedelta(minutes=10), "terminal": dt.timedelta(minutes=10),
               "code_execution": dt.timedelta(minutes=10)}
NETWORK_PROBE = ("api.github.com", 443)
ITEM_REQUIREMENTS = {"user_approval", "user_decision", "login", "external_reply", "payment"}

_MEMO: dict[str, tuple[float, dict]] = {}


def cache_path():
    return stateio.private_dir("work") / "requirements.json"


def _now(now: dt.datetime | None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _result(req: str, ok: bool, why: str, *, live: bool, now: dt.datetime,
            wake: str = "", not_before: dt.datetime | None = None) -> dict:
    blocked = None if ok else ws.BLOCKED_BY.get(req, ws.BLOCKED_EXTERNAL)
    if not ok and blocked == ws.RETRY_LATER and not_before is None:
        not_before = now + RETRY_AFTER.get(req, dt.timedelta(minutes=15))
    return {"requirement": req, "ok": bool(ok), "why": str(why)[:240], "live": bool(live),
            "checked_at": _stamp(now), "blocked_state": blocked, "wake": "" if ok else wake,
            "not_before": _stamp(not_before) if (not ok and not_before) else None}


# ---- world checks: each returns (ok, why, live, wake, not_before) ------------------

def _local(now: dt.datetime, probe: bool):
    from aletheia import local_model_pool, model_pool_config
    if not model_pool_config.enabled():
        return False, "her own model is switched off", True, "when local reasoning is switched on", None
    if not local_model_pool.reachable():
        return False, "her own model is not running (Ollama did not answer)", True, \
            "when Ollama is running", None
    room = local_model_pool.room_for_role("fast")
    if not room.get("fits", True):
        return False, str(room.get("why") or "not enough free memory for her own model"), True, \
            "when memory frees up", now + dt.timedelta(minutes=10)
    return True, f"her own model answers ({room.get('model') or 'fast role'})", True, "", None


def _frontier(now: dt.datetime, probe: bool):
    from aletheia import reasoning_gateway
    status = reasoning_gateway.frontier_status(now)
    return status["ok"], status["why"], False, status["wake"], status["resets_at"]


def _browser(now: dt.datetime, probe: bool):
    from aletheia import browse
    ok, why = browse.available()
    if not ok:
        return False, f"no browser installed ({why})", True, "when a browser is installed", None
    if not probe:
        return None
    ok, why = browse.reachable()
    return ok, why, True, "when a page loads again", None


def _network(now: dt.datetime, probe: bool):
    try:
        with socket.create_connection(NETWORK_PROBE, timeout=3.0):
            pass
        return True, f"reached {NETWORK_PROBE[0]}", True, "", None
    except OSError as exc:
        return False, f"could not reach {NETWORK_PROBE[0]} ({type(exc).__name__})", True, \
            "when the internet is reachable", None


def _github(now: dt.datetime, probe: bool):
    from aletheia import gh
    try:
        token = gh.token()
    except Exception:
        token = None
    if not token:
        return False, "no GitHub token is stored", True, "when he stores a GitHub token", None
    # One HTTPS call, cached for half an hour: cheap enough to be real.
    try:
        from aletheia import github_auth
        who = github_auth._verify(token)
        return True, f"token verified for {who.get('login') or 'his account'}", True, "", None
    except Exception as exc:
        return False, f"the stored GitHub token did not verify ({type(exc).__name__})", True, \
            "when he refreshes the GitHub token", None


def _email(now: dt.datetime, probe: bool):
    from aletheia import mail
    ok, why = mail.available()
    return ok, why, False, "when mail is set up", None


def _calendar(now: dt.datetime, probe: bool):
    from aletheia import calendar_live
    ok, why = calendar_live.available()
    if ok:
        return True, why, False, "", None
    try:
        from aletheia import ics
        if ics._config().get("feeds"):
            return True, "a calendar feed is configured", False, "", None
    except Exception:
        pass
    return False, why, False, "when a calendar is connected", None


def _filesystem(now: dt.datetime, probe: bool):
    root = stateio.private_root()
    target = root if root.exists() else root.parent
    if os.access(target, os.W_OK):
        return True, "her private state is writable", True, "", None
    return False, f"{target} is not writable", True, "when her state directory is writable", None


def _terminal(now: dt.datetime, probe: bool):
    exe = sys.executable
    if exe and os.path.exists(exe):
        return True, "a local interpreter can run", True, "", None
    return False, "no local interpreter found", True, "when Python is available", None


WORLD: dict[str, Callable[[dt.datetime, bool], Any]] = {
    "local_reasoning": _local,
    "frontier_reasoning": _frontier,
    "browser": _browser,
    "network": _network,
    "github": _github,
    "email": _email,
    "calendar": _calendar,
    "filesystem": _filesystem,
    "terminal": _terminal,
    "code_execution": _terminal,
}


def _load_cache() -> dict:
    try:
        value = json.loads(cache_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(req: str, result: dict) -> None:
    try:
        cache = _load_cache()
        cache[req] = result
        cache_path().parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(cache_path(), cache)
    except Exception:
        pass


def _fresh(result: dict, req: str, now: dt.datetime) -> bool:
    try:
        at = dt.datetime.strptime(result["checked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (KeyError, ValueError, TypeError):
        return False
    return (now - at).total_seconds() < TTL_S.get(req, 300.0)


def world(req: str, *, now: dt.datetime | None = None, probe: bool = False,
          persist: bool = False, fresh: bool = False) -> dict:
    """The live answer for one world requirement. Never raises."""
    now = _now(now)
    if req == "reasoning":
        local = world("local_reasoning", now=now, probe=probe, persist=persist, fresh=fresh)
        if local["ok"]:
            return {**local, "requirement": "reasoning"}
        frontier = world("frontier_reasoning", now=now, probe=probe, persist=persist, fresh=fresh)
        if frontier["ok"]:
            return {**frontier, "requirement": "reasoning"}
        return _result("reasoning", False, f"{frontier['why']}; and {local['why']}", live=True, now=now,
                       wake="when any model can think", not_before=_parse(frontier.get("not_before")))
    clock = time.monotonic()
    hit = _MEMO.get(req)
    if hit and not fresh and clock - hit[0] < TTL_S.get(req, 300.0):
        return dict(hit[1])
    fn = WORLD.get(req)
    if fn is None:
        return _result(req, False, f"{req} is not a world requirement", live=False, now=now)
    try:
        said = fn(now, probe)
    except Exception as exc:  # noqa: BLE001
        said = (False, f"{req} could not be checked ({type(exc).__name__})", False,
                f"when {req} can be checked", None)
    if said is None:
        # An expensive check not run in this mode: the last real answer, or honest doubt.
        cached = _load_cache().get(req)
        if isinstance(cached, dict) and _fresh(cached, req, now):
            return {**cached, "cached": True}
        result = _result(req, True, f"{req} is installed but not verified live recently", live=False,
                         now=now)
        result["unverified"] = True
        return result
    ok, why, live, wake, not_before = said
    result = _result(req, ok, why, live=live, now=now, wake=wake, not_before=not_before)
    _MEMO[req] = (clock, dict(result))
    if persist and live:
        _save_cache(req, result)
    return result


def _parse(stamp) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


# ---- item checks -------------------------------------------------------------------

def _approval_state(approval_id: str) -> str:
    try:
        from aletheia import policy
        for row in policy.all_approvals():
            if str(row.get("id")) == str(approval_id):
                return str(row.get("state") or "")
    except Exception:
        pass
    return ""


def item_check(req: str, item: dict, *, now: dt.datetime | None = None) -> dict:
    """An ITEM requirement, satisfied only by evidence the item carries."""
    now = _now(now)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    if req == "payment":
        return _result(req, False, "it moves money, and only Caleb spends money", live=False, now=now,
                       wake="when Caleb does the paying himself")
    if req == "user_approval":
        approval = str(evidence.get("approval") or item.get("approval") or "")
        state = _approval_state(approval) if approval else ""
        if state == "APPROVED":
            return _result(req, True, f"approval {approval} is APPROVED", live=True, now=now)
        why = (f"approval {approval} is {state or 'not found'}" if approval
               else "it needs Caleb's approval and none has been asked for yet")
        return _result(req, False, why, live=bool(approval), now=now, wake="when Caleb approves it")
    if req == "user_decision":
        if evidence.get("decision"):
            return _result(req, True, "Caleb decided", live=False, now=now)
        return _result(req, False, "it needs a decision only Caleb can make", live=False, now=now,
                       wake="when Caleb decides")
    if req == "login":
        if evidence.get("signed_in"):
            return _result(req, True, "a signed-in session is on record", live=False, now=now)
        return _result(req, False, "it needs a signed-in account session", live=False, now=now,
                       wake="when Caleb signs in")
    if req == "external_reply":
        if evidence.get("replied"):
            return _result(req, True, "the reply arrived", live=False, now=now)
        return _result(req, False, "it is waiting for someone else to answer", live=False, now=now,
                       wake="when the reply arrives")
    return _result(req, False, f"{req} is not an item requirement", live=False, now=now)


def check(req: str, item: dict | None = None, *, now: dt.datetime | None = None,
          probe: bool = False, persist: bool = False) -> dict:
    if req not in ws.REQUIREMENTS:
        return _result(req, False, f"unknown requirement {req!r}", live=False, now=_now(now),
                       wake="when the requirement is named correctly")
    if req in ITEM_REQUIREMENTS:
        return item_check(req, item or {}, now=now)
    return world(req, now=now, probe=probe, persist=persist)


def unmet(requires, item: dict | None = None, *, now: dt.datetime | None = None,
          probe: bool = False, persist: bool = False) -> list[dict]:
    """The requirements that are NOT satisfied now, in the order given."""
    out = []
    for req in dict.fromkeys(requires or []):
        result = check(req, item, now=now, probe=probe, persist=persist)
        if not result["ok"]:
            out.append(result)
    return out


def availability(*, now: dt.datetime | None = None, probe: bool = False,
                 persist: bool = False) -> dict[str, dict]:
    """Every world requirement's answer now, for the inventory and the screen."""
    return {req: world(req, now=now, probe=probe, persist=persist)
            for req in ("local_reasoning", "frontier_reasoning", "reasoning", "browser", "network",
                        "github", "email", "calendar", "filesystem", "terminal", "code_execution")}


def forget() -> None:
    _MEMO.clear()
