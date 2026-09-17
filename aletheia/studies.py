"""Studies: turning outside research into justified project direction, then measuring it.

His brief addendum (docs/CONTINUITY_BRIEF.md, 2026-09-17), in his words: *"These
three ... are doing way better than ours. Study them deeply, figure out what they
do better, and improve our [project]"* - and *"Do NOT build [platform]-specific
architecture. This same pattern should work for [competitors], products,
websites, businesses, etc."* So nothing in this file, or in the modules it
drives, knows what a project or a comparable IS. A study is:

    subject       his project: a name, and whatever of it she can read - a folder on
                  this machine, a repository, a charter, its public addresses
    comparables   the things he says do better, named by him (or proposed from a
                  search and confirmed by him - a proposal is never studied first)
    questions     what the study is trying to find out, from his words
    lens          the dimensions to compare on, each naming metrics an observation
                  source can MEASURE (`study_observe.METRICS`) and what to look for;
                  drafted by a model from his words, never a category list
    evidence      observations with provenance (`study_observe`), durable, indexed
    comparison    subject vs comparables on the lens: measured differences computed
                  deterministically, plus claims that cite evidence ids (uncited claims
                  are dropped, or kept only as labelled guesses)
    hypotheses    ranked, evidence-backed proposals: the observations behind each,
                  the change, the expected effect, the metric that would show it, how
                  its baseline is read, cost, risk, reversibility, the execution path
    decisions     HIS: accept, reject or reshape each hypothesis; later keep, revert or
                  iterate on a measured change. Her own actors are refused.
    results       what each change did to its metric, with caveats, and what was learned

LIFECYCLE. `propose` (his words) -> the pipeline (`study_run`: shape -> research ->
compare -> strategy, each a work item the one engine carries) -> hypotheses wait
on HIS decision (durable `waits`, owner "studies") -> an accepted one runs through
the EXISTING safe execution paths with its baseline recorded first -> a
`time_after` wait re-reads the metric after the window -> a keep/revert/iterate
decision for him -> the result feeds the next strategy and memory.

Nothing here executes: this is the record, its gates and its readers. Every writer
has a reader: `status`, the `studies` intercom kind, the `study.status` /
`study.evidence` session tools, the mission-control provider and the `studies`
section of current_state.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Callable

from aletheia import stateio, waits, work_states as ws

ACTOR = "aletheia-studies"
OWNER = "studies"
VERSION = 1

OPEN, DONE, DROPPED = "OPEN", "DONE", "DROPPED"
STEPS = ("shape", "research", "compare", "strategy")

# hypothesis states
PROPOSED, ACCEPTED, REJECTED, RESHAPING = "PROPOSED", "ACCEPTED", "REJECTED", "RESHAPING"
EXECUTING, READY, MEASURING, VERDICT = "EXECUTING", "READY", "MEASURING", "VERDICT"
KEPT, REVERTING, REVERTED, ITERATING, BLOCKED = "KEPT", "REVERTING", "REVERTED", "ITERATING", "BLOCKED"
H_STATES = (PROPOSED, ACCEPTED, REJECTED, RESHAPING, EXECUTING, READY, MEASURING, VERDICT, KEPT, REVERTING,
            REVERTED, ITERATING, BLOCKED)
H_FINISHED = (REJECTED, KEPT, REVERTED, ITERATING)

#: Where an accepted hypothesis is carried. Each is an EXISTING path (study_run).
EXECUTION_PATHS = {
    "project_change": "a bounded change to the project's own files, on a branch (a pull request where one "
                      "may be opened), never the default branch",
    "experiment": "the same bounded change, run as an experiment with a named variant and a duration",
    "code_work": "code work beyond a bounded change: investigated into a packet for a stronger model",
    "outward": "anything that publishes, posts or messages: handed to Caleb for approval",
    "his": "something only Caleb can do (an account, a setting, a purchase): asked once",
}
REVERSIBILITY = ("reversible", "partly_reversible", "irreversible")
LEVELS = ("low", "medium", "high")
DECISIONS = ("accept", "reject", "reshape")
VERDICTS = ("keep", "revert", "iterate")
HER_OWN_VIA = ("aletheia", "agent", "thea")
MAX_HISTORY = 30
MAX_RESULTS = 30

_LOCK = threading.RLock()


class StudyError(ValueError):
    pass


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return waits._now(now)


stamp = waits.stamp
parse = waits.parse


def studies_dir() -> Path:
    return stateio.private_dir("studies")


def _path(sid: str) -> Path:
    return studies_dir() / f"{stateio.safe_id(sid, name='study id')}.json"


def load(sid: str) -> dict:
    return stateio.read_json(_path(sid))


def save(record: dict) -> dict:
    stateio.write_json_atomic(_path(record["id"]), record)
    return record


def all_studies() -> list[dict]:
    root = studies_dir()
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("study-*.json")):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("id") == path.stem:
            out.append(value)
    return out


def update(sid: str, fn: Callable[[dict], Any]) -> tuple[dict, Any]:
    with _LOCK:
        record = load(sid)
        said = fn(record)
        save(record)
        return record, said


def _clean(text: Any, limit: int = 600) -> str:
    return " ".join(str(text if text is not None else "").split())[:limit]


def _history(row: dict, text: str, now: dt.datetime) -> None:
    rows = list(row.get("history") or [])
    rows.append({"at": stamp(now), "did": str(text)[:240]})
    row["history"] = rows[-MAX_HISTORY:]


def _journal(kind: str, subject: str, text: str) -> None:
    """The journal is committed; it names the study, never what a page said."""
    try:
        from aletheia import journal
        journal.append(kind, subject, str(text)[:300], actor=ACTOR)
    except Exception:  # noqa: BLE001
        pass


def _her_own(via: str) -> bool:
    low = str(via or "").strip().lower()
    return not low or any(low.startswith(p) for p in HER_OWN_VIA)


def item_id(sid: str, key: str = "") -> str:
    return f"study:{sid}" + (f"/{key}" if key else "")


# ---- the subject and the comparables ---------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40] or "item"


def resolve_subject(name: str = "", *, path: str = "", repo: str = "", surface: list[str] | None = None) -> dict:
    """His project, from what he said plus what her records know about it: a charter
    (plans/ with a project block) or a fleet repository of that name. Never invented:
    what is not found stays empty and the study says it can only read what it has."""
    name = _clean(name, 80)
    subject = {"name": name or (Path(path).name if path else repo.split("/")[-1] if repo else ""),
               "path": str(path or ""), "repo": str(repo or ""), "branch": "", "subdir": "", "charter": "",
               "surface": [s for s in (surface or []) if str(s).strip()]}
    want = _slug(subject["name"])
    if want and not (subject["path"] or subject["repo"]):
        try:
            from aletheia import local_repair, plans
            plan, _why = plans.find_charter(subject["name"])
            if plan is not None:
                target = local_repair.charter_target(plan["slug"], plan=plan)
                subject.update(charter=target["charter"], repo=target["repo"], branch=target["base_ref"],
                               subdir=target["subdir"])
                for key in ("url", "site", "homepage"):
                    if (plan.get("project") or {}).get(key):
                        subject["surface"].append(str(plan["project"][key]))
        except Exception:  # noqa: BLE001 - no charter found is not an error
            pass
    if want and not (subject["path"] or subject["repo"]):
        try:
            from aletheia.fleet import load_fleet
            fleet = load_fleet()
            for key, cfg in (fleet.get("repos") or {}).items():
                if want in (_slug(key), _slug(cfg.get("github"))):
                    subject.update(repo=f"{fleet.get('owner')}/{cfg.get('github')}",
                                   branch=str(cfg.get("default_branch") or "main"))
                    break
        except Exception:  # noqa: BLE001
            pass
    return subject


def subject_targets(subject: dict) -> list[str]:
    targets = []
    if subject.get("path"):
        targets.append(subject["path"])
    elif subject.get("repo") and not subject.get("subdir"):
        targets.append(f"https://github.com/{subject['repo']}")
    targets += [s for s in subject.get("surface") or [] if s not in targets]
    return targets


def _comparable(name: str, targets: list[str], *, named_by: str, confirmed: bool, taken: set[str]) -> dict:
    key = _slug(name) or "comparable"
    base, n = key, 2
    while key in taken:
        key, n = f"{base}-{n}", n + 1
    taken.add(key)
    return {"key": key, "name": _clean(name, 120), "targets": [str(t) for t in targets if str(t).strip()][:4],
            "named_by": named_by, "confirmed": bool(confirmed)}


# ---- his words in ---------------------------------------------------------------------------

def propose(words: str, *, via: str, subject: dict, comparables: list[dict], program: str = "",
            now: dt.datetime | None = None) -> dict:
    """A new study from his sentence. Comparables he named are confirmed by naming them;
    anything proposed from a search waits for his yes before it is studied."""
    now = _now(now)
    words = _clean(words, 1500)
    if len(words) < 3:
        raise StudyError("a study needs his sentence saying what to study and why")
    if _her_own(via):
        raise PermissionError("a study is started by Caleb")
    sid = f"study-{now.strftime('%Y%m%d')}-{secrets.token_hex(3)}"
    taken: set[str] = set()
    rows = [_comparable(c.get("name") or (c.get("targets") or ["comparable"])[0], list(c.get("targets") or []),
                        named_by=c.get("named_by") or "caleb", confirmed=c.get("named_by", "caleb") == "caleb",
                        taken=taken)
            for c in comparables or [] if c.get("name") or c.get("targets")]
    record = {
        "version": VERSION, "id": sid, "state": OPEN, "title": _clean(words, 90), "words": words,
        "via": str(via)[:60], "program": str(program or ""), "created_at": stamp(now), "updated_at": stamp(now),
        "subject": dict(subject), "comparables": rows, "questions": [], "lens": None,
        "pending": list(STEPS), "running": None, "blocked": None,
        "research": {"observations": [], "refused": [], "requests": 0, "at": None},
        "comparison": None, "hypotheses": [], "results": [], "learned": [], "history": [], "asks": [
            {"at": stamp(now), "kind": "study", "words": words, "via": str(via)[:60]}],
    }
    _history(record, "asked for: " + words[:180], now)
    with _LOCK:
        save(record)
    _journal("task", item_id(sid), f"new study asked for: {len(rows)} comparable(s) against "
                                   f"{record['subject'].get('name') or 'his project'}")
    return record


def confirm_comparables(sid: str, keys: list[str] | None, *, via: str, now: dt.datetime | None = None) -> dict:
    """His yes to proposed comparables (all of them, or the keys he names)."""
    now = _now(now)
    if _her_own(via):
        raise PermissionError("which comparables are studied is Caleb's call")

    def change(record):
        hit = 0
        for c in record.get("comparables") or []:
            if not c.get("confirmed") and (not keys or c["key"] in keys):
                c.update(confirmed=True, confirmed_by=str(via)[:60], confirmed_at=stamp(now))
                hit += 1
        if hit:
            _history(record, f"Caleb confirmed {hit} comparable(s)", now)
        record["updated_at"] = stamp(now)
        return hit
    return update(sid, change)[1]


def find(which: str = "", *, include_finished: bool = False) -> dict | None:
    rows = [s for s in all_studies() if include_finished or s.get("state") == OPEN]
    if not rows:
        return None
    which = _clean(which, 200).lower()
    if which:
        exact = next((s for s in rows if s["id"] == which), None)
        if exact:
            return exact
        want = {w for w in re.findall(r"[a-z0-9]{3,}", which) if w not in {"study", "the", "my", "our"}}
        if want:
            scored = sorted(((len(want & set(re.findall(r"[a-z0-9]{3,}", " ".join(
                [s.get("title") or "", (s.get("subject") or {}).get("name") or ""]
                + [c.get("name") or "" for c in s.get("comparables") or []]).lower()))), s) for s in rows),
                key=lambda x: (-x[0], x[1].get("updated_at") or ""))
            if scored and scored[0][0]:
                return scored[0][1]
    return sorted(rows, key=lambda s: s.get("updated_at") or "")[-1]


# ---- the pipeline's results in -----------------------------------------------------------------

def claim_step(sid: str, step: str, owner: str, now: dt.datetime) -> bool:
    def change(record):
        if record.get("state") != OPEN or step not in (record.get("pending") or []):
            return False
        if record.get("pending")[0] != step:
            return False
        running = record.get("running") or {}
        if running and running.get("step") == step and running.get("owner") != owner:
            started = parse(running.get("at"))
            if started and (now - started).total_seconds() < 45 * 60:
                return False
        record["running"] = {"step": step, "owner": owner, "at": stamp(now)}
        record["blocked"] = None
        return True
    return bool(update(sid, change)[1])


def finish_step(sid: str, step: str, fill: Callable[[dict], None], *, said: str, now: dt.datetime) -> dict:
    """A step's output stored and the step struck off, under one lock."""
    def change(record):
        fill(record)
        record["pending"] = [s for s in record.get("pending") or [] if s != step]
        record["running"] = None
        record["blocked"] = None
        record["updated_at"] = stamp(now)
        _history(record, said, now)
    return update(sid, change)[0]


def block_step(sid: str, step: str, *, why: str, until: dt.datetime | None, state: str, now: dt.datetime) -> dict:
    def change(record):
        record["running"] = None
        record["blocked"] = {"step": step, "why": _clean(why, 300), "state": state,
                             "until": stamp(until) if until else None, "at": stamp(now)}
        record["updated_at"] = stamp(now)
        _history(record, f"{step} waits ({state}): {_clean(why, 140)}", now)
    return update(sid, change)[0]


def open_hypothesis_decision(record: dict, hyp: dict, now: dt.datetime) -> dict:
    held = waits.wait_for(item_id(record["id"], hyp["key"]),
                          {"kind": "user_decision", "question": f"{hyp['title']}: accept, reject or reshape?",
                           "options": list(DECISIONS)},
                          reason=f"a proposed change for Caleb to accept, reject or reshape: {hyp['title']}",
                          owner=OWNER, key=f"decision:{hyp.get('version', 1)}",
                          context={"study": record["id"], "hypothesis": hyp["key"], "purpose": "decision"}, now=now)
    hyp["wait"] = held["id"]
    return held


def apply_hypotheses(sid: str, rows: list[dict], *, drafted_by: dict, now: dt.datetime | None = None) -> dict:
    """Store ranked hypotheses; each one waits on HIS decision. Hypotheses already on the
    record are never overwritten: one he asked to reshape is marked superseded by the new
    ones, one he asked to iterate on stays as it was, and undecided proposals keep their
    place. Whatever a drafter put in a row, a new hypothesis starts PROPOSED."""
    now = _now(now)

    def change(record):
        existing = list(record.get("hypotheses") or [])
        reshaped = [r for r in record.get("reshape") or [] if not r.get("done")]
        iterated = [r for r in record.get("iterate") or [] if not r.get("done")]
        for r in reshaped:
            old = next((h for h in existing if h["key"] == r["hypothesis"]), None)
            if old is not None and old["state"] == RESHAPING:
                old.update(state=REJECTED, superseded=True)
                _history(old, "reshaped into new proposals, as Caleb asked", now)
        fresh = []
        numbers = [int(m.group(1)) for h in existing for m in [re.fullmatch(r"h(\d+)", h["key"])] if m]
        nxt = max(numbers or [0]) + 1
        for row in rows:
            clean = {k: v for k, v in row.items() if k not in {"key", "state", "decision", "wait", "verdict",
                                                                "baseline", "measurement", "execution_result"}}
            hyp = {**clean, "key": f"h{nxt}", "state": PROPOSED, "decision": None, "wait": None, "baseline": None,
                   "execution_result": None, "measurement": None, "verdict": None,
                   "drafted_by": drafted_by, "created_at": stamp(now), "history": [], "version": 1,
                   **({"reshapes": [r["hypothesis"] for r in reshaped]} if reshaped else {}),
                   **({"iterates": [r["hypothesis"] for r in iterated]} if iterated else {})}
            nxt += 1
            _history(hyp, f"proposed by {drafted_by.get('provider')}", now)
            fresh.append(hyp)
        for r in reshaped + iterated:
            r["done"] = stamp(now)
        record["hypotheses"] = existing + fresh
        proposals = sorted([h for h in record["hypotheses"] if h["state"] == PROPOSED],
                           key=lambda h: -(h.get("score") or 0))
        for n, hyp in enumerate(proposals, 1):
            hyp["rank"] = n
        for hyp in fresh:
            open_hypothesis_decision(record, hyp, now)
        for old in existing:
            if old.get("superseded") and old.get("wait"):
                try:
                    waits.cancel(old["wait"], why="reshaped into new proposals", now=now)
                except (ValueError, OSError):
                    pass
        record["updated_at"] = stamp(now)
        return fresh
    record, fresh = update(sid, change)
    _journal("event", item_id(sid), f"{len(fresh)} hypothesis(es) drafted by {drafted_by.get('provider')}; "
                                    "each waits for Caleb's decision")
    _notify(record, "Your study has proposals",
            f"{len(fresh)} evidence-backed change{'s' if len(fresh) != 1 else ''} for {record['subject'].get('name') or 'your project'}"
            + (f", drafted by {drafted_by.get('provider')}" if drafted_by.get("provider") else "")
            + ". Nothing changes until you accept one.", key=f"study-proposals:{sid}:{stamp(now)}")
    return record


def _notify(record: dict, title: str, body: str, *, key: str) -> None:
    try:
        from aletheia import notifications
        notifications.publish(title, body[:400], priority="NORMAL", source="studies", dedupe_key=key,
                              related={"study": record["id"]})
    except Exception:  # noqa: BLE001
        pass


def hypothesis(record: dict, key: str) -> dict:
    found = next((h for h in record.get("hypotheses") or [] if h["key"] == key), None)
    if found is None:
        raise StudyError(f"no hypothesis {key!r} in that study")
    return found


def pick_hypothesis(record: dict, which: str, states: tuple = (PROPOSED,)) -> dict | None:
    """The hypothesis he means: its key, its rank ("the first one", "2") or words of its title."""
    rows = sorted([h for h in record.get("hypotheses") or [] if h["state"] in states],
                  key=lambda h: (h.get("rank") or 99, h["key"]))
    if not rows:
        return None
    low = _clean(which, 200).lower()
    ordinals = {"first": 1, "top": 1, "one": 1, "second": 2, "two": 2, "third": 3, "three": 3, "fourth": 4,
                "four": 4, "fifth": 5, "five": 5, "last": len(rows)}
    if not low:
        return rows[0] if len(rows) == 1 else None
    for h in rows:
        if low == h["key"]:
            return h
    m = re.search(r"\b(\d+)\b", low) or re.search(r"\b(" + "|".join(ordinals) + r")\b", low)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else ordinals[m.group(1)]
        ranked = [h for h in rows if (h.get("rank") or 0) == n]
        if ranked:
            return ranked[0]
        return rows[n - 1] if 1 <= n <= len(rows) else None
    want = set(re.findall(r"[a-z0-9]{4,}", low))
    scored = sorted(((len(want & set(re.findall(r"[a-z0-9]{4,}", (h.get("title") or "").lower()))), h)
                     for h in rows), key=lambda x: -x[0])
    return scored[0][1] if scored and scored[0][0] else None


def decide(sid: str, key: str, choice: str, *, words: str, via: str, now: dt.datetime | None = None) -> dict:
    """HIS decision on a proposed hypothesis: accept, reject or reshape (with his words).
    This is the only door from PROPOSED to ACCEPTED; nothing executes before it."""
    now = _now(now)
    if _her_own(via):
        raise PermissionError("accepting, rejecting or reshaping a change is Caleb's decision")
    choice = str(choice or "").strip().lower()
    if choice not in DECISIONS:
        raise StudyError(f"a decision is one of {', '.join(DECISIONS)}")
    record = load(sid)
    hyp = hypothesis(record, key)
    if hyp["state"] != PROPOSED:
        raise StudyError(f"that change is already {hyp['state'].lower()}")
    if hyp.get("wait"):
        try:
            waits.decide(hyp["wait"], choice, words=words, via=via, now=now)
        except waits.WaitError:
            pass

    def change(record):
        h = hypothesis(record, key)
        if h["state"] != PROPOSED:
            raise StudyError(f"that change is already {h['state'].lower()}")
        h["decision"] = {"choice": choice, "words": _clean(words, 400), "via": str(via)[:60], "at": stamp(now)}
        h["state"] = {"accept": ACCEPTED, "reject": REJECTED, "reshape": RESHAPING}[choice]
        _history(h, f"Caleb chose {choice}" + (f": {_clean(words, 120)}" if words else ""), now)
        if choice == "reshape":
            record["pending"] = list(dict.fromkeys(list(record.get("pending") or []) + ["strategy"]))
            record.setdefault("reshape", []).append({"hypothesis": key, "words": _clean(words, 400),
                                                     "at": stamp(now)})
        record["updated_at"] = stamp(now)
        return h
    h = update(sid, change)[1]
    _journal("decision", item_id(sid, key), f"Caleb chose {choice} for a proposed change")
    return h


# ---- execution, measurement and his verdict ----------------------------------------------------

def set_hypothesis(sid: str, key: str, fn: Callable[[dict, dict], Any], *, now: dt.datetime | None = None) -> tuple[dict, Any]:
    now = _now(now)

    def change(record):
        h = hypothesis(record, key)
        said = fn(record, h)
        h["updated_at"] = stamp(now)
        record["updated_at"] = stamp(now)
        return said
    return update(sid, change)


def record_baseline(sid: str, key: str, baseline: dict, *, now: dt.datetime | None = None) -> dict:
    """The metric's value BEFORE the change. Refused once a change exists: a baseline read
    after the change is not a baseline."""
    now = _now(now)

    def fn(record, h):
        if h["state"] not in (ACCEPTED, EXECUTING) or (h.get("decision") or {}).get("choice") != "accept":
            raise StudyError(f"a baseline is read for a change Caleb accepted, not a {h['state'].lower()} one")
        if (h.get("execution_result") or {}).get("changed"):
            raise StudyError("the change already exists; a baseline read now would not be a baseline")
        h["baseline"] = {**baseline, "at": stamp(now)}
        _history(h, f"baseline {baseline.get('metric')} = {baseline.get('value')}", now)
        return h["baseline"]
    return set_hypothesis(sid, key, fn, now=now)[1]


def schedule_measurement(record: dict, hyp: dict, now: dt.datetime) -> dict:
    days = float((hyp.get("execution") or {}).get("duration_days") or hyp.get("measure_after_days") or 7)
    at = now + dt.timedelta(days=max(days, 1 / 24))
    held = waits.wait_for(item_id(record["id"], hyp["key"]), {"kind": "time_after", "at": stamp(at)},
                          reason=f"measuring {hyp['metric']['name']} after {hyp['title']}",
                          owner=OWNER, key=f"measure:{hyp.get('version', 1)}:{len(hyp.get('measurements') or [])}",
                          context={"study": record["id"], "hypothesis": hyp["key"], "purpose": "measure"}, now=now)
    hyp["measure_wait"] = held["id"]
    hyp["measure_at"] = stamp(at)
    return held


def open_verdict(record: dict, hyp: dict, now: dt.datetime) -> dict:
    held = waits.wait_for(item_id(record["id"], hyp["key"]),
                          {"kind": "user_decision", "question": f"{hyp['title']}: keep, revert or iterate?",
                           "options": list(VERDICTS)},
                          reason=f"a measured change for Caleb to keep, revert or iterate on: {hyp['title']}",
                          owner=OWNER, key=f"verdict:{hyp.get('version', 1)}:{len(hyp.get('measurements') or [])}",
                          context={"study": record["id"], "hypothesis": hyp["key"], "purpose": "verdict"}, now=now)
    hyp["verdict_wait"] = held["id"]
    return held


def verdict(sid: str, key: str, choice: str, *, words: str, via: str, now: dt.datetime | None = None) -> dict:
    """HIS verdict on a measured change. keep -> what worked is learned; revert -> a revert
    runs through the same safe path; iterate -> the strategy drafts a follow-up he decides on."""
    now = _now(now)
    if _her_own(via):
        raise PermissionError("keeping or reverting a change is Caleb's decision")
    choice = str(choice or "").strip().lower()
    if choice not in VERDICTS:
        raise StudyError(f"a verdict is one of {', '.join(VERDICTS)}")
    record = load(sid)
    hyp = hypothesis(record, key)
    if hyp["state"] != VERDICT:
        raise StudyError(f"that change is {hyp['state'].lower()}, not waiting for a verdict")
    if hyp.get("verdict_wait"):
        try:
            waits.decide(hyp["verdict_wait"], choice, words=words, via=via, now=now)
        except waits.WaitError:
            pass

    def change(record):
        h = hypothesis(record, key)
        m = h.get("measurement") or {}
        h["verdict"] = {"choice": choice, "words": _clean(words, 300), "via": str(via)[:60], "at": stamp(now)}
        h["state"] = {"keep": KEPT, "revert": REVERTING, "iterate": ITERATING}[choice]
        lesson = {"at": stamp(now), "hypothesis": key, "title": h["title"], "metric": (h.get("metric") or {}).get("name"),
                  "baseline": (h.get("baseline") or {}).get("value"), "after": m.get("value"),
                  "change": m.get("change"), "verdict": choice, "caveats": m.get("caveats") or [],
                  "worked": m.get("moved_as_expected")}
        record["learned"] = (record.get("learned") or [])[-MAX_RESULTS:] + [lesson]
        if choice == "iterate":
            record["pending"] = list(dict.fromkeys(list(record.get("pending") or []) + ["strategy"]))
            record.setdefault("iterate", []).append({"hypothesis": key, "words": _clean(words, 300), "at": stamp(now)})
        _history(h, f"Caleb's verdict: {choice}", now)
        record["updated_at"] = stamp(now)
        return h
    h = update(sid, change)[1]
    _journal("decision", item_id(sid, key), f"Caleb's verdict on a measured change: {choice}")
    return h


def set_state(sid: str, state: str, *, via: str, why: str = "", now: dt.datetime | None = None) -> dict:
    now = _now(now)
    if state not in (OPEN, DONE, DROPPED):
        raise StudyError("a study is open, done or dropped")
    if _her_own(via):
        raise PermissionError("closing or dropping a study is Caleb's call")

    def change(record):
        record["state"] = state
        record["updated_at"] = stamp(now)
        _history(record, f"{state.lower()} by Caleb" + (f": {why}" if why else ""), now)
    record = update(sid, change)[0]
    if state == DROPPED:
        for held in waits.waiting(owner=OWNER):
            if (held.get("context") or {}).get("study") == sid:
                waits.cancel(held["id"], why="the study was dropped", now=now)
    return record


# ---- reading it back ---------------------------------------------------------------------------

def _evidence_count(sid: str) -> int:
    try:
        from aletheia import study_observe
        return len(study_observe.all_evidence(sid))
    except Exception:  # noqa: BLE001
        return 0


def summary(record: dict, now: dt.datetime | None = None) -> dict:
    now = _now(now)
    hyps = sorted(record.get("hypotheses") or [], key=lambda h: (h.get("rank") or 99, h["key"]))
    visible = [h for h in hyps if not h.get("superseded")]
    comparison = record.get("comparison") or {}
    blocked = record.get("blocked") or None
    due = sorted(h.get("measure_at") for h in visible if h["state"] == MEASURING and h.get("measure_at"))
    return {
        "id": record["id"], "title": record.get("title"), "state": record.get("state"),
        "subject": (record.get("subject") or {}).get("name"), "program": record.get("program") or "",
        "comparables": [{"key": c["key"], "name": c["name"], "confirmed": c.get("confirmed"),
                         "named_by": c.get("named_by"), "targets": c.get("targets")} for c in record.get("comparables") or []],
        "questions": record.get("questions") or [],
        "lens": [{"key": d.get("key"), "name": d.get("name"), "metrics": d.get("metrics")}
                 for d in (record.get("lens") or {}).get("dimensions") or []],
        "lens_by": (record.get("lens") or {}).get("drafted_by"),
        "pending": record.get("pending") or [], "running": record.get("running"), "blocked": blocked,
        "evidence": _evidence_count(record["id"]),
        "refused_reads": len((record.get("research") or {}).get("refused") or []),
        "comparison": {"rows": len(comparison.get("rows") or []), "claims": len(comparison.get("claims") or []),
                       "dropped": comparison.get("dropped", 0), "guesses": comparison.get("guesses", 0),
                       "drafted_by": comparison.get("drafted_by"),
                       "top": [r.get("said") for r in (comparison.get("rows") or [])[:4]]} if comparison else None,
        "hypotheses": [{"key": h["key"], "rank": h.get("rank"), "title": h["title"], "state": h["state"],
                        "metric": (h.get("metric") or {}).get("name"), "path": (h.get("execution") or {}).get("path"),
                        "evidence": h.get("evidence") or [], "expected_effect": h.get("expected_effect"),
                        "cost": h.get("cost"), "risk": h.get("risk"), "reversibility": h.get("reversibility"),
                        "baseline": (h.get("baseline") or {}).get("value"),
                        "result": (h.get("measurement") or {}).get("said"),
                        "execution": (h.get("execution_result") or {}).get("said"),
                        "measure_at": h.get("measure_at"), "drafted_by": (h.get("drafted_by") or {}).get("provider")}
                       for h in visible],
        "awaiting_decision": [h["key"] for h in visible if h["state"] == PROPOSED],
        "awaiting_verdict": [h["key"] for h in visible if h["state"] == VERDICT],
        "executing": [h["key"] for h in visible if h["state"] in (ACCEPTED, EXECUTING, REVERTING)],
        "ready": [h["key"] for h in visible if h["state"] == READY],
        "measuring": [h["key"] for h in visible if h["state"] == MEASURING],
        "next_measurement_at": due[0] if due else None,
        "unconfirmed_comparables": [c["name"] for c in record.get("comparables") or [] if not c.get("confirmed")],
        "learned": (record.get("learned") or [])[-5:], "updated_at": record.get("updated_at"),
        "results": (record.get("results") or [])[-6:],
    }


def status(which: str = "", *, now: dt.datetime | None = None) -> dict:
    try:
        rows = all_studies()
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "studies": [], "note": f"the studies could not be read ({type(exc).__name__})"}
    live = [s for s in rows if s.get("state") == OPEN]
    if which:
        found = find(which, include_finished=True)
        live = [found] if found else []
    out = {"readable": True, "total": len(rows), "studies": [summary(s, now) for s in live]}
    if not rows:
        out["note"] = ("READ AND EMPTY: the study store exists and holds no studies. Say none has been "
                       "started; never say there is no such thing.")
    elif not live:
        out["note"] = f"no open study matches{' ' + repr(which) if which else ''}; {len(rows)} on record"
    return out


def spoken_status(which: str = "", about: str = "", *, now: dt.datetime | None = None) -> str:
    from aletheia import speech
    said = status(which, now=now)
    if not said.get("readable"):
        return "I couldn't read your studies just now."
    rows = said["studies"]
    if not rows:
        return ("You haven't asked me to study anything yet." if not said.get("total")
                else "No study is open right now.")
    s = rows[0]
    name = s["subject"] or "your project"
    about = str(about or "").lower()
    parts = []
    if s["unconfirmed_comparables"]:
        parts.append(f"I found {speech.and_list(s['unconfirmed_comparables'][:3])} to compare against "
                     f"{name}; say study them to confirm.")
    step = (s.get("running") or {}).get("step") or (s["pending"][0] if s["pending"] else "")
    if s.get("blocked"):
        parts.append(f"The {s['blocked']['step']} step is waiting: {s['blocked']['why']}.")
    elif step:
        parts.append({"shape": f"I'm working out what to compare {name} on.",
                      "research": f"I'm reading the comparables and {name}.",
                      "compare": f"I've read {speech.count_phrase(s['evidence'], 'observation')} and I'm comparing.",
                      "strategy": "I'm turning the comparison into proposed changes."}.get(step, ""))
    if about in ("found", "find", "findings", "comparison") or (not about and s["comparison"]):
        top = [t for t in (s["comparison"] or {}).get("top") or [] if t]
        if top:
            parts.append("What I measured: " + "; ".join(t.rstrip(".") for t in top[:3]) + ".")
    proposals = [h for h in s["hypotheses"] if h["state"] == "PROPOSED"]
    if proposals and about in ("", "change", "changes", "should", "proposals", "found"):
        lines = [f"{n}, {h['title'].rstrip('.')}" for n, h in enumerate(proposals[:3], 1)]
        parts.append(f"{speech.count_phrase(len(proposals), 'change')} for you to decide: " + "; ".join(lines)
                     + ". Say accept the first one, reject it, or reshape it.")
    for h in s["hypotheses"]:
        if h["state"] == "MEASURING" and h.get("measure_at"):
            parts.append(f"I'm measuring {h['title'].rstrip('.')} again {_when_words(h['measure_at'])}.")
        elif h["state"] == "VERDICT" and h.get("result"):
            parts.append(f"{h['result'].rstrip('.')}. Keep it, revert it, or iterate?")
        elif h["state"] == "READY" and h.get("execution"):
            parts.append(h["execution"].rstrip(".") + ".")
    if not parts:
        parts.append(f"The study of {name} has {speech.count_phrase(s['evidence'], 'observation')} and nothing "
                     "waiting on you.")
    return " ".join(p for p in parts if p)


def _when_words(stamp_text: str | None) -> str:
    when = parse(stamp_text)
    if when is None:
        return "later"
    try:
        from aletheia import reasoner
        return reasoner.spoken_time(when)
    except Exception:  # noqa: BLE001
        return when.strftime("on %b %d")


def section(now: dt.datetime | None = None) -> dict:
    """The compact block current_state carries. Never raises."""
    try:
        said = status(now=now)
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "note": f"the studies could not be read ({type(exc).__name__})"}
    return {"readable": said.get("readable", False), "open": len(said.get("studies") or []),
            "studies": [{"id": s["id"], "subject": s["subject"], "evidence": s["evidence"],
                         "pending": s["pending"], "blocked": (s.get("blocked") or {}).get("why"),
                         "awaiting_decision": len(s["awaiting_decision"]), "awaiting_verdict": len(s["awaiting_verdict"]),
                         "measuring": len(s["measuring"]), "next_measurement_at": s["next_measurement_at"]}
                        for s in said.get("studies") or []],
            "note": said.get("note", "")}


def waiting_rows(now: dt.datetime | None = None) -> list[dict]:
    """What the studies wait on, for the work inventory and the room."""
    out = []
    for s in status(now=now).get("studies") or []:
        for h in s["hypotheses"]:
            if h["state"] == PROPOSED:
                out.append({"study": s["id"], "what": h["title"], "state": ws.BLOCKED_USER,
                            "why": "a proposed change waits for Caleb's decision"})
            elif h["state"] == VERDICT:
                out.append({"study": s["id"], "what": h["title"], "state": ws.BLOCKED_USER,
                            "why": "a measured change waits for Caleb's keep, revert or iterate"})
            elif h["state"] == MEASURING:
                out.append({"study": s["id"], "what": h["title"], "state": ws.BLOCKED_EXTERNAL,
                            "why": f"measuring again at {h.get('measure_at')}"})
    return out
