"""No tool for this step is not the end: it is a next action (continuity brief II.6).

When a step has no tool, Aletheia classifies what happens next into one of
`work_states.GAP_OUTCOMES` and records it as a durable work item
(`work_engine.add`, kind "gap") carrying that next action. On a later beat the
engine runs the item, which takes the action THROUGH THE EXISTING GATES:

- another existing tool / a browser path / a local workaround: a task naming the
  tool to use, in the ordinary task store
- ask Caleb / install or configure: one deduplicated notification, then the item
  waits BLOCKED_USER
- wait for an external event: BLOCKED_EXTERNAL, with what it waits for
- a small capability addition: `gaps.materialize`, assigned to the local repair
  tier (bounded work the local tier may take; its gates decide, not this file)
- a larger capability: `gaps.materialize` for a frontier worker; the item says
  NEEDS_STRONGER_MODEL while no frontier model can think
- refuse by policy: FAILED with the rule named (money is his; approvals and the
  kill switch are never hers)

This is not self-modification. Every addition is a queued build or verify task that
goes through review, tests and the merge rules like any other; filing one grants
nothing (`gaps` docstring). Demand is REUSED, not duplicated: gaps he actually hit
come from the demand ledger (`file_from_demand`), and the ledger keeps counting.

Classification is deterministic on purpose: it has to work with every model out,
and a rule that decides "this is a policy refusal" must not be a model's opinion.
"""
from __future__ import annotations

import datetime as dt
import re

from aletheia import work_states as ws

#: The words that make a step a question for him, an external wait, a web path or a script.
_ASK = re.compile(r"\b(?:which|prefer|decide|choose|your (?:password|pin|ssn)|do you want|should i)\b", re.I)
_WAIT = re.compile(r"\b(?:wait(?:ing)? for|hear back|reply|respond|until|arrives?|confirmation (?:email|letter))\b", re.I)
_WEB = re.compile(r"\b(?:website|web ?site|online|portal|web page|form on|site|url|https?://)\b", re.I)
_LOCAL = re.compile(r"\b(?:convert|rename|parse|calculate|compute|sort|merge (?:the )?files?|csv|spreadsheet|"
                    r"extract|resize|compress|count)\b", re.I)
_LARGE = re.compile(r"\b(?:architecture|auth(?:entication|orization)?|permissions?|security|migrat\w+|"
                    r"refactor|integration with|new (?:service|provider|platform)|oauth|payments? system|"
                    r"multi-?system)\b", re.I)
_SELF_AUTHORITY = re.compile(r"\b(?:approve (?:my|your|its) own|lift (?:the|your|her) (?:kill switch|halt)|"
                             r"resume yourself|grant (?:yourself|herself)|widen (?:your|her) (?:authority|grants?))\b",
                             re.I)

CONFIG_STATUSES = {"NEEDS_CONFIGURATION"}
VERIFY_STATUSES = {"EXPERIMENTAL", "DEGRADED"}
BUILD_STATUSES = {"NOT_BUILT", "UNAVAILABLE"}
#: Demand reasons that are a missing capability, not a wall hit during a real attempt.
GAP_REASONS = {"GAP", "NOT_BUILT", "UNAVAILABLE", "NEEDS_CONFIGURATION", "EXPERIMENTAL", "DEGRADED", "UNKNOWN"}


def _registry():
    try:
        from aletheia import capabilities
        return capabilities.load_registry()
    except Exception:
        return {"capabilities": []}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", str(text or "").lower())}


def _other_tool(step: str, registry: dict, exclude: str = "") -> dict | None:
    """An AVAILABLE capability whose description shares enough words with the step."""
    want = _words(step)
    if not want:
        return None
    best, score = None, 0
    for cap in registry.get("capabilities", []):
        if cap.get("status") != "AVAILABLE" or cap.get("id") == exclude:
            continue
        overlap = len(want & (_words(cap.get("description")) | _words(cap.get("id", "").replace(".", " "))))
        if overlap > score:
            best, score = cap, overlap
    return best if score >= 2 else None


def classify(step: str, *, capability: str = "", registry: dict | None = None,
             scope: str = "") -> dict:
    """{"outcome", "why", "next", "state", "requires", "capability", "tool"}. Pure but for the registry."""
    step = " ".join(str(step or "").split())
    registry = registry if registry is not None else _registry()
    by_id = {c.get("id"): c for c in registry.get("capabilities", [])}
    entry = by_id.get(capability) if capability else None
    status = str((entry or {}).get("status") or ("UNKNOWN" if capability else ""))

    def out(outcome: str, why: str, nxt: str, *, requires=(), tool: str = "") -> dict:
        return {"outcome": outcome, "why": why, "next": nxt, "state": ws.GAP_STATE[outcome],
                "requires": list(requires), "capability": capability, "tool": tool, "step": step}

    try:
        from aletheia import webtask
        spends = webtask.would_spend(step)
    except Exception:
        spends = True       # fail closed: if the money check cannot run, nothing here may look like buying
    if spends or capability.split(".")[0] in {"purchase", "shopping", "payment"}:
        return out("refuse_policy", "it commits money, and only Caleb spends money",
                   "nothing: tell Caleb what it would cost if he wants to do it himself")
    if _SELF_AUTHORITY.search(step):
        return out("refuse_policy", "it would change her own authority or kill switch, which only Caleb may do",
                   "nothing: only Caleb can do that")
    if entry is not None and status == "AVAILABLE":
        return out("other_tool", f"{capability} is available", f"use {capability}", tool=capability)
    if status in CONFIG_STATUSES:
        return out("install_configure", f"{capability} is built but needs setup",
                   f"ask Caleb to finish setting up {capability}")
    if status in VERIFY_STATUSES:
        return out("small_capability", f"{capability} exists but is {status}: it needs live evidence or a repair",
                   f"verify or repair {capability}")
    if _WAIT.search(step) and not _WEB.search(step):
        return out("wait_external", "it depends on something outside that has not happened yet",
                   "wait for it, and look again when it arrives")
    if _ASK.search(step):
        return out("ask_caleb", "only Caleb can answer that", "ask Caleb once, then remember the answer",
                   requires=["user_decision"])
    alternative = _other_tool(step, registry, exclude=capability)
    if alternative is not None:
        return out("other_tool", f"{alternative['id']} can do this another way", f"use {alternative['id']}",
                   tool=alternative["id"])
    if _WEB.search(step) and "browser.pursue" in by_id or (_WEB.search(step) and "web.task" in by_id):
        tool = "browser.pursue" if "browser.pursue" in by_id else "web.task"
        return out("browser_path", "a website can do it and the browser loop drives websites",
                   f"do it through {tool}", requires=["browser"], tool=tool)
    if _LOCAL.search(step) and "script.run" in by_id:
        return out("local_workaround", "a small sandboxed script can do it", "write and run a script",
                   requires=["code_execution"], tool="script.run")
    large = scope == "large" or bool(_LARGE.search(step)) or status == "UNKNOWN"
    if large and scope != "small":
        return out("large_capability", f"{capability or 'this'} needs new capability beyond the local repair tier",
                   f"queue building {capability or 'it'} for a frontier model")
    return out("small_capability", f"{capability or 'this'} is a bounded addition",
               f"queue a small addition for {capability or 'it'}")


def record(step: str, *, capability: str = "", registry: dict | None = None, scope: str = "",
           asked: str = "", now: dt.datetime | None = None) -> dict:
    """Classify and file the durable work item (idempotent per capability + step)."""
    from aletheia import work_engine
    verdict = classify(step, capability=capability, registry=registry, scope=scope)
    state = verdict["state"]
    # A gap item is first READY to take its next action; the action decides where it waits.
    return work_engine.add(
        f"{verdict['outcome'].replace('_', ' ')}: {step or capability}", kind="gap", key=f"{capability}|{step}",
        state=ws.READY if state != ws.FAILED else ws.FAILED,
        reason="" if state != ws.FAILED else verdict["why"], next=verdict["next"],
        # Filing the next action needs nothing; the work it files states its own needs.
        requires=[],
        payload={**verdict, "asked": str(asked or "")[:140]}, priority=3, now=now)


def act(it: dict, *, now: dt.datetime | None = None) -> dict:
    """Take a gap item's next action through the existing gates. Returns the new state."""
    now = now or dt.datetime.now(dt.timezone.utc)
    v = dict(it.get("payload") or {})
    outcome, cap = v.get("outcome"), str(v.get("capability") or "")
    if outcome == "refuse_policy":
        return {"state": ws.FAILED, "reason": v.get("why", "policy forbids it"), "next": v.get("next", "")}
    if outcome in {"other_tool", "browser_path", "local_workaround"}:
        from aletheia import tasks
        tid = "use-" + re.sub(r"[^a-z0-9]+", "-", f"{v.get('tool', '')}-{v.get('step', '')}".lower()).strip("-")[:50]
        try:
            tasks.create(tid, f"{v.get('next')}: {v.get('step') or cap}"[:200],
                         required_capabilities=[v["tool"]] if v.get("tool") else None, priority=3)
        except FileExistsError:
            pass
        return {"state": ws.DONE, "reason": "", "next": f"handed to task {tid}"}
    if outcome in {"ask_caleb", "install_configure"}:
        from aletheia import notifications
        notifications.publish("Something only you can do", f"{v.get('why')}: {v.get('step') or cap}. {v.get('next')}.",
                              priority="NORMAL", source="work", dedupe_key=f"work-gap:{it.get('id')}",
                              related={"work": it.get("id")})
        return {"state": ws.BLOCKED_USER, "reason": v.get("why", "only Caleb can do this"),
                "next": "when Caleb answers or finishes the setup", "not_before": None}
    if outcome == "wait_external":
        return {"state": ws.BLOCKED_EXTERNAL, "reason": v.get("why", "waiting on the world"),
                "next": v.get("next", "when it arrives")}
    if outcome in {"small_capability", "large_capability"} and cap:
        from aletheia import gaps
        worker = "local-repair" if outcome == "small_capability" else "claude"
        filed = gaps.materialize([cap], worker=worker)
        ids = ", ".join(t["id"] for t in filed) or "nothing new"
        return {"state": ws.DONE, "reason": "", "next": f"queued as {ids} (goes through review and tests)"}
    if outcome in {"small_capability", "large_capability"}:
        # No registry id to materialize: file the scoping as a task for the right tier.
        from aletheia import tasks
        tid = "build-" + re.sub(r"[^a-z0-9]+", "-", str(v.get("step") or "gap").lower()).strip("-")[:50]
        worker = "local-repair" if outcome == "small_capability" else "claude"
        try:
            tasks.create(tid, f"Scope and build: {v.get('step')}"[:200], assigned_worker=worker, priority=3)
        except FileExistsError:
            pass
        return {"state": ws.DONE, "reason": "", "next": f"queued as {tid} for {worker} (review and tests apply)"}
    return {"state": ws.BLOCKED_USER, "reason": "it could not be classified into an action",
            "next": "ask Caleb what he wants done"}


def _demand_gaps(registry: dict, limit: int) -> list[tuple[str, str]]:
    """(capability, his latest words) for every ledger row that is a missing capability."""
    from aletheia import demand
    by_id = {c.get("id"): c for c in registry.get("capabilities", [])}
    out = []
    for row in demand.ranked(limit=limit):
        cap = str(row.get("capability") or "")
        status = str((by_id.get(cap) or {}).get("status") or "UNKNOWN")
        reasons = set((row.get("reasons") or {}).keys())
        if status == "AVAILABLE" or not (reasons & GAP_REASONS):
            continue          # resolved, or a wall hit during a real attempt (its own store owns that)
        out.append((cap, (row.get("in_his_words") or [""])[-1]))
    return out


def preview_from_demand(*, registry: dict | None = None, limit: int = 12) -> list[dict]:
    """The classification each demand gap would get. Writes nothing."""
    registry = registry if registry is not None else _registry()
    return [classify(words or cap, capability=cap, registry=registry)
            for cap, words in _demand_gaps(registry, limit)]


def file_from_demand(*, now: dt.datetime | None = None, registry: dict | None = None, limit: int = 12) -> list[dict]:
    """Every capability gap in the demand ledger becomes a durable item, once."""
    registry = registry if registry is not None else _registry()
    return [record(words or cap, capability=cap, registry=registry, asked=words, now=now)
            for cap, words in _demand_gaps(registry, limit)]
