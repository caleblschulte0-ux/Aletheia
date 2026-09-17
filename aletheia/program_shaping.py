"""His words become a DRAFT long mission: outcomes, workstreams, tasks, questions.

Continuity brief IV.11-12: *"Do not predefine what a mission means. No hard-coded
categories ... Structure is discovered from the mission and the discussion with
him, as measurable outcomes and workstreams."* So nothing here lists what a
mission might be about. A model reads what he said (and, on a revision, the
structure so far and his answers) and proposes:

- `questions`   what it must ask HIM to make the outcomes measurable
- `outcomes`    each with how to tell it is met
- `workstreams` discovered from his words, each serving outcomes
- `tasks`       per workstream, each saying what it must DO in plain words
                (`does`), which existing tools fit (`uses`, from a menu of the
                real catalog), what it needs first, and what it then waits for
- `activities`  recurring work ("every morning") and monitoring (`watch`)
- `decisions`   choices that are his, with the options

The reasoning is the gateway's STANDARD class: frontier first, her own model
when the frontier is out, and the draft records which one wrote it and why, so
"drafted by my own model because the frontier was out" is sayable. It is a
DRAFT: `programs.confirm`, reached only by his words, makes it active.

The validator is tolerant on purpose (a local model is sloppy with keys) and
strict where it matters: every reference resolves, counts are bounded, a
`then_wait` is one of the kinds `aletheia.waits` can wake.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Callable

MAX_OUTCOMES = 8
MAX_WORKSTREAMS = 8
MAX_TASKS = 30
MAX_ACTIVITIES = 6
MAX_DECISIONS = 6
MAX_QUESTIONS = 6
WAIT_FOR = ("reply", "date", "event", "decision", "result")
CADENCES = ("day", "week", "hours")
CONTEXT_BYTES = 24 * 1024
#: Shaping is background work, never a conversation: it may use the long ceiling.
WORK_BUDGET_S = 600.0

SYSTEM = """You shape a LONG-RUNNING MISSION for Caleb from his own words. It may run for weeks
or months and span several unrelated parts of his life; you do not know in advance what those
parts are, so DISCOVER them from what he said. Do not use a fixed list of life areas.

Return JSON only, with these keys:
{
 "title": short name for the mission,
 "objective": his objective restated in one or two sentences,
 "horizon": how long he gave it in his words ("" if none),
 "questions": [{"ask": a question for Caleb, "why": what it decides}],
 "outcomes": [{"key": "o1", "text": a concrete result, "measure": how anyone can tell it is met}],
 "workstreams": [{"key": "w1", "title": ..., "why": ..., "outcomes": ["o1"]}],
 "tasks": [{"key": "t1", "workstream": "w1", "title": imperative, "detail": the specifics from his words,
            "does": [plain verb phrases of what it must do],
            "uses": [tool names from TOOLS that fit, or []],
            "needs": [keys of tasks that must finish first],
            "then_wait": null or {"for": "reply"|"date"|"event"|"decision"|"result",
                                  "who": who must answer, "in_days": number, "follow_up_days": number,
                                  "timeout_days": number, "timeout_means": what silence would mean,
                                  "question": for a decision, "options": [..]}}],
 "activities": [{"key": "a1", "workstream": "w1", "title": ..., "detail": ..., "does": [...], "uses": [...],
                 "cadence": {"every": "day"|"week"|"hours", "at": "HH:MM", "weekdays": [0-6], "hours": n},
                 "watch": true if it monitors something for changes}],
 "decisions": [{"key": "d1", "workstream": "w1", "question": ..., "options": [..], "after": [task keys]}]
}

Rules:
- Ask Caleb the questions that make outcomes MEASURABLE (dates, amounts, must-haves) instead of guessing.
- Only use facts he gave. Never invent people, addresses, prices or dates.
- Tasks are small and concrete. Contacting someone, scheduling, or anything that reaches another
  person is still a task: it will ask for Caleb's approval when it runs, so plan it anyway.
- Nothing may spend money: if something would cost money, make it a decision for Caleb.
- Waiting is normal: a reply, a date, an event, his decision. Say what a timeout would mean.
- If REVISION is given, return the whole updated structure, keeping existing keys for work that stays.
"""


SKELETON_SYSTEM = """You shape a LONG-RUNNING MISSION for Caleb from his own words. DISCOVER its parts from what he
said; do not use a fixed list of life areas. Only use facts he gave. Keep it short.
Return JSON only:
{"title": short name, "objective": one sentence, "horizon": his time frame or "",
 "questions": [{"ask": a question that makes an outcome measurable}] (at most 3),
 "outcomes": [{"key": "o1", "text": a concrete result, "measure": how to tell it is met}] (at most 4),
 "workstreams": [{"key": "w1", "title": a part of the mission, "outcomes": ["o1"]}] (at most 4)}"""

STREAM_SYSTEM = """List the small concrete tasks for ONE part of Caleb's long mission. Only facts he gave; never
invent people, prices or dates; nothing that spends money. Reaching a person is fine (he approves it). Be brief.
Return JSON only: {"tasks": [{"title": imperative sentence with the specifics,
 "waits_for": "reply" or "date" or "decision" or "", "who": person to hear from or "",
 "after": number of an earlier task in this list or 0}]} with at most 3 tasks."""

#: What a compact local plan's wait means, before he says otherwise: a reply is nudged (with his approval)
#: after three days and stops being waited for after ten; a date is the next day.
COMPACT_WAIT = {"reply": {"follow_up_days": 3, "timeout_days": 10,
                          "timeout_means": "no reply in ten days; ask Caleb whether to try again or move on"},
                "date": {"in_days": 1}, "decision": {}}


class ShapeError(ValueError):
    pass


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, (str, dict)) and value:
        return [value]
    return []


def _key(prefix: str, raw: Any, n: int, taken: set[str]) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(raw or "").lower())[:12] or f"{prefix}{n}"
    while key in taken:
        n += 1
        key = f"{prefix}{n}"
    taken.add(key)
    return key


def _number(value: Any, low: float, high: float) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, n))


def _then_wait(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    kind = str(value.get("for") or "").strip().lower()
    if kind not in WAIT_FOR:
        return None
    out = {"for": kind, "who": _text(value.get("who"), 120)}
    for field, low, high in (("in_days", 0, 365), ("follow_up_days", 0.5, 60), ("timeout_days", 0.5, 365)):
        n = _number(value.get(field), low, high)
        if n is not None:
            out[field] = n
    out["timeout_means"] = _text(value.get("timeout_means"), 200)
    if kind == "decision":
        out["question"] = _text(value.get("question"), 200)
        out["options"] = [_text(o, 80) for o in _list(value.get("options")) if _text(o, 80)][:6]
        if not out["question"]:
            return None
    return out


def _cadence(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    every = str(value.get("every") or "").strip().lower().rstrip("s")
    every = {"daily": "day", "weekly": "week", "hourly": "hours", "hour": "hours"}.get(every, every)
    if every not in CADENCES:
        return None
    out: dict = {"every": every}
    at = str(value.get("at") or "").strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", at) and int(at.split(":")[0]) < 24 and int(at.split(":")[1]) < 60:
        out["at"] = f"{int(at.split(':')[0]):02d}:{at.split(':')[1]}"
    elif every != "hours":
        out["at"] = "08:00"
    if every == "week":
        days = sorted({int(d) for d in _list(value.get("weekdays")) if str(d).isdigit() and 0 <= int(d) <= 6})
        out["weekdays"] = days or [0]
    if every == "hours":
        out["hours"] = int(_number(value.get("hours"), 1, 168) or 24)
    return out


def validate(value: Any, *, tool_names: set[str] | None = None) -> dict:
    """The structure, normalised. Raises ShapeError when there is nothing to work from."""
    if not isinstance(value, dict):
        raise ShapeError("the draft must be an object")
    tool_names = tool_names or set()
    out: dict = {"title": _text(value.get("title"), 80), "objective": _text(value.get("objective"), 400),
                 "horizon": _text(value.get("horizon"), 80)}
    out["questions"] = [q for q in ({"ask": _text((q or {}).get("ask") if isinstance(q, dict) else q, 240),
                                     "why": _text((q or {}).get("why") if isinstance(q, dict) else "", 200)}
                                    for q in _list(value.get("questions"))) if q["ask"]][:MAX_QUESTIONS]
    taken: set[str] = set()
    outcomes = []
    for n, row in enumerate(_list(value.get("outcomes")), 1):
        if not isinstance(row, dict) or not _text(row.get("text"), 240):
            continue
        outcomes.append({"key": _key("o", row.get("key"), n, taken), "text": _text(row.get("text"), 240),
                         "measure": _text(row.get("measure"), 240) or "Caleb says it is met"})
    out["outcomes"] = outcomes[:MAX_OUTCOMES]
    outcome_keys = {o["key"] for o in out["outcomes"]}
    streams = []
    for n, row in enumerate(_list(value.get("workstreams")), 1):
        if not isinstance(row, dict) or not _text(row.get("title"), 120):
            continue
        streams.append({"key": _key("w", row.get("key"), n, taken), "title": _text(row.get("title"), 120),
                        "why": _text(row.get("why"), 240),
                        "outcomes": [str(o) for o in _list(row.get("outcomes")) if str(o) in outcome_keys]})
    out["workstreams"] = streams[:MAX_WORKSTREAMS]
    stream_keys = [w["key"] for w in out["workstreams"]]

    def stream_of(raw: Any) -> str:
        raw = str(raw or "")
        if raw in stream_keys:
            return raw
        title = raw.lower()
        match = next((w["key"] for w in out["workstreams"] if title and title == w["title"].lower()), "")
        return match or (stream_keys[0] if stream_keys else "")

    tasks = []
    for n, row in enumerate(_list(value.get("tasks")), 1):
        if not isinstance(row, dict) or not _text(row.get("title"), 160):
            continue
        tasks.append({"key": _key("t", row.get("key"), n, taken), "workstream": stream_of(row.get("workstream")),
                      "title": _text(row.get("title"), 160), "detail": _text(row.get("detail"), 480),
                      "does": [_text(d, 160) for d in _list(row.get("does")) if _text(d, 160)][:6],
                      "uses": [str(u) for u in _list(row.get("uses")) if not tool_names or str(u) in tool_names][:6],
                      "needs_raw": [str(x) for x in _list(row.get("needs"))],
                      "then_wait": _then_wait(row.get("then_wait")),
                      "outcomes": [str(o) for o in _list(row.get("outcomes")) if str(o) in outcome_keys]})
    tasks = tasks[:MAX_TASKS]
    task_keys = {t["key"] for t in tasks}
    for t in tasks:
        t["needs"] = [k for k in t.pop("needs_raw") if k in task_keys and k != t["key"]]
    out["tasks"] = tasks
    activities = []
    for n, row in enumerate(_list(value.get("activities")), 1):
        if not isinstance(row, dict) or not _text(row.get("title"), 160):
            continue
        cadence = _cadence(row.get("cadence"))
        if cadence is None:
            continue
        activities.append({"key": _key("a", row.get("key"), n, taken), "workstream": stream_of(row.get("workstream")),
                           "title": _text(row.get("title"), 160), "detail": _text(row.get("detail"), 480),
                           "does": [_text(d, 160) for d in _list(row.get("does")) if _text(d, 160)][:6],
                           "uses": [str(u) for u in _list(row.get("uses"))
                                    if not tool_names or str(u) in tool_names][:6],
                           "cadence": cadence, "watch": bool(row.get("watch"))})
    out["activities"] = activities[:MAX_ACTIVITIES]
    decisions = []
    for n, row in enumerate(_list(value.get("decisions")), 1):
        if not isinstance(row, dict) or not _text(row.get("question"), 240):
            continue
        decisions.append({"key": _key("d", row.get("key"), n, taken), "workstream": stream_of(row.get("workstream")),
                          "question": _text(row.get("question"), 240),
                          "options": [_text(o, 80) for o in _list(row.get("options")) if _text(o, 80)][:6],
                          "after": [str(k) for k in _list(row.get("after")) if str(k) in task_keys]})
    out["decisions"] = decisions[:MAX_DECISIONS]
    if not out["outcomes"] or not out["workstreams"] or not (out["tasks"] or out["activities"]):
        raise ShapeError("a mission draft needs at least one outcome, one workstream and one task")
    for w in out["workstreams"]:
        if not w["outcomes"]:
            w["outcomes"] = [out["outcomes"][0]["key"]]
    if not out["title"]:
        out["title"] = _text(out["objective"] or out["workstreams"][0]["title"], 80)
    return out


def context_for(words: str, *, catalog: dict, answers: list[dict] | None = None,
                current: dict | None = None, revision: str = "", now: dt.datetime | None = None) -> dict:
    from aletheia import program_compose
    now = now or dt.datetime.now(dt.timezone.utc)
    blob = " ".join([words, revision] + [str(a.get("answer") or "") for a in answers or []])
    ctx: dict = {"today": now.date().isoformat(), "his_words": words[:1500],
                 "TOOLS": program_compose.menu(blob, catalog, limit=24)}
    if answers:
        ctx["his_answers"] = [{"asked": a.get("ask"), "answer": a.get("answer")} for a in answers if a.get("answer")]
    if current:
        ctx["current_structure"] = {k: current.get(k) for k in ("title", "objective", "outcomes", "workstreams",
                                                                 "tasks", "activities", "decisions")}
    if revision:
        ctx["REVISION"] = revision[:800]
    raw = json.dumps(ctx, default=str)
    if len(raw.encode("utf-8")) > CONTEXT_BYTES and current:
        # The structure is the bulky part: keep titles and keys, which is what a revision edits.
        ctx["current_structure"]["tasks"] = [{"key": t.get("key"), "workstream": t.get("workstream"),
                                              "title": t.get("title")} for t in current.get("tasks") or []]
    return ctx


def _skeleton_validator(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ShapeError("the skeleton must be an object")
    probe = dict(value)
    probe["tasks"] = [{"title": "placeholder", "workstream": ""}]
    checked = validate(probe)
    checked.pop("tasks", None)
    for key in ("activities", "decisions"):
        checked.pop(key, None)
    return checked


def expand_compact(value: dict) -> dict:
    """A compact local plan ({"title", "waits_for", "who", "after"}) in the full task shape."""
    tasks = _list(value.get("tasks"))
    if not tasks or not all(isinstance(t, dict) and "key" not in t for t in tasks):
        return value
    out = []
    for n, t in enumerate(tasks, 1):
        title = _text(t.get("title"), 160)
        waits_for = str(t.get("waits_for") or "").strip().lower()
        then = None
        if waits_for in COMPACT_WAIT:
            then = dict(COMPACT_WAIT[waits_for], **{"for": waits_for, "who": _text(t.get("who"), 120)})
            if waits_for == "decision":
                then["question"] = title
        after = t.get("after")
        needs = [f"t{int(after)}"] if str(after).isdigit() and 0 < int(after) < n else []
        out.append({"key": f"t{n}", "title": title, "detail": title, "does": [], "uses": [], "needs": needs,
                    "then_wait": then})
    return {"tasks": out, "activities": value.get("activities") or [], "decisions": value.get("decisions") or []}


def _stream_validator(stream: dict, names: set[str]) -> Callable[[Any], dict]:
    def check(value: Any) -> dict:
        if not isinstance(value, dict):
            raise ShapeError("a workstream plan must be an object")
        value = expand_compact(value)
        probe = {"title": "x", "outcomes": [{"key": o, "text": o} for o in stream.get("outcomes") or ["o1"]],
                 "workstreams": [{"key": stream["key"], "title": stream["title"], "outcomes": stream.get("outcomes")}],
                 "tasks": value.get("tasks"), "activities": value.get("activities"),
                 "decisions": value.get("decisions")}
        if not (value.get("tasks") or value.get("activities")):
            return {"tasks": [], "activities": [], "decisions": []}     # a part with nothing to do yet
        checked = validate(probe, tool_names=names)
        return {k: checked[k] for k in ("tasks", "activities", "decisions")}
    return check


def staged_context(words: str, *, catalog: dict, answers: list[dict] | None = None, current: dict | None = None,
                   revision: str = "", now: dt.datetime | None = None) -> dict:
    context = context_for(words, catalog=catalog, answers=answers, current=current, revision=revision, now=now)
    context.pop("TOOLS", None)
    if context.get("current_structure"):
        cs = context["current_structure"]
        context["current_structure"] = {"title": cs.get("title"), "outcomes": cs.get("outcomes"),
                                        "workstreams": [{"key": w.get("key"), "title": w.get("title")}
                                                        for w in cs.get("workstreams") or []]}
    return context


def skeleton(words: str, context: dict, *, think: Callable | None = None) -> dict:
    """Stage one: {"value", "provider", "degraded"}. Raises ReasonerUnavailable."""
    value, provider, degraded = _asker(think)(SKELETON_SYSTEM, words, context, _skeleton_validator)
    return {"value": value, "provider": provider, "degraded": degraded}


def stream_plan(words: str, skel: dict, stream: dict, context: dict, *, catalog: dict,
                think: Callable | None = None) -> dict:
    """Stage two, for ONE workstream: {"value", "provider", "degraded"}. Raises ReasonerUnavailable.
    The compact shape (title, waits_for, who, after) is what a local model finishes in time; the tools are
    then chosen by capability from the task's own words (`program_compose`)."""
    sub = {"mission": skel.get("objective") or words[:300], "his_words": words[:900],
           "workstream": {"key": stream["key"], "title": stream["title"]},
           "outcomes": [o for o in skel["outcomes"] if o["key"] in (stream.get("outcomes") or [])],
           "today": context.get("today")}
    if context.get("his_answers"):
        sub["his_answers"] = context["his_answers"]
    value, provider, degraded = _asker(think)(STREAM_SYSTEM, stream["title"], sub,
                                              _stream_validator(stream, set(catalog)))
    return {"value": value, "provider": provider, "degraded": degraded}


def merge(skel: dict, parts: dict, *, catalog: dict) -> dict:
    """The skeleton and every workstream's plan as one validated structure."""
    structure = dict(skel, tasks=[], activities=[], decisions=[])
    for stream in skel["workstreams"]:
        part = parts.get(stream["key"]) or {"tasks": [], "activities": [], "decisions": []}
        prefix = stream["key"]
        rename = {t["key"]: f"{prefix}{t['key']}" for t in part["tasks"]}
        for t in part["tasks"]:
            structure["tasks"].append(dict(t, key=rename[t["key"]], workstream=stream["key"],
                                           needs=[rename[n] for n in t["needs"] if n in rename]))
        for a in part["activities"]:
            structure["activities"].append(dict(a, key=f"{prefix}{a['key']}", workstream=stream["key"]))
        for d in part["decisions"]:
            structure["decisions"].append(dict(d, key=f"{prefix}{d['key']}", workstream=stream["key"],
                                               after=[rename[k] for k in d["after"] if k in rename]))
    return validate(structure, tool_names=set(catalog))


def shape_staged(words: str, *, catalog: dict, answers: list[dict] | None = None, current: dict | None = None,
                 revision: str = "", think: Callable | None = None, now: dt.datetime | None = None) -> dict:
    """The same structure in small calls - a skeleton, then one call per workstream - so a local model on a
    CPU can finish each inside its time limit. All at once here; `program_run.do_shape` does it one call per
    run and keeps each finished piece on disk, so an outage or a restart costs one call, not the draft."""
    context = staged_context(words, catalog=catalog, answers=answers, current=current, revision=revision, now=now)
    skel = skeleton(words, context, think=think)
    parts, last = {}, skel
    for stream in skel["value"]["workstreams"]:
        last = stream_plan(words, skel["value"], stream, context, catalog=catalog, think=think)
        parts[stream["key"]] = last["value"]
    return {"structure": merge(skel["value"], parts, catalog=catalog), "drafted_by": last["provider"],
            "degraded": last["degraded"], "staged": True}


def _asker(think: Callable | None):
    def ask(system: str, text: str, context: dict, validator: Callable) -> tuple[dict, str, str | None]:
        if think is not None:
            return think(system, text, context=context, validator=validator), getattr(think, "provider", "scripted"), None
        from aletheia import reasoner, reasoning_gateway
        result = reasoning_gateway.reason_json(system, text, context=context, policy="standard",
                                               model=reasoner.PLAN_MODEL, timeout_s=WORK_BUDGET_S,
                                               validator=validator, max_context_bytes=CONTEXT_BYTES,
                                               work_budget_s=WORK_BUDGET_S)
        return result.output, result.provider, result.degraded
    return ask


def shape(words: str, *, catalog: dict, answers: list[dict] | None = None, current: dict | None = None,
          revision: str = "", think: Callable | None = None, now: dt.datetime | None = None,
          staged: bool | None = None) -> dict:
    """{"structure", "drafted_by", "degraded"}. Raises reasoner.ReasonerUnavailable when nobody can think.

    With a frontier model available it is one call; with none (her own model on a CPU) it is staged, because
    one call for the whole structure does not finish inside a local model's time limit (measured 2026-09-16:
    qwen3:8b timed out at 300 s on the single-call draft)."""
    words = _text(words, 1500)
    if not words:
        raise ShapeError("there is nothing to shape")
    if staged is None and think is None:
        from aletheia import reasoning_gateway
        staged = not reasoning_gateway.frontier_available()
    if staged:
        return shape_staged(words, catalog=catalog, answers=answers, current=current, revision=revision,
                            think=think, now=now)
    names = set(catalog)
    context = context_for(words, catalog=catalog, answers=answers, current=current, revision=revision, now=now)

    def validator(value: dict) -> dict:
        return validate(value, tool_names=names)
    if think is not None:
        output = think(SYSTEM, words, context=context, validator=validator)
        return {"structure": output, "drafted_by": getattr(think, "provider", "scripted"), "degraded": None}
    from aletheia import reasoner, reasoning_gateway
    result = reasoning_gateway.reason_json(
        SYSTEM, words, context=context, policy="standard", model=reasoner.PLAN_MODEL,
        timeout_s=WORK_BUDGET_S, validator=validator, max_context_bytes=CONTEXT_BYTES,
        work_budget_s=WORK_BUDGET_S)
    return {"structure": result.output, "drafted_by": result.provider, "degraded": result.degraded}
