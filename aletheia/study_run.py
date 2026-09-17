"""Carrying a study: the pipeline, the execution of what he accepted, and the measurement.

A study (`aletheia.studies`) does not schedule itself. Its steps and its accepted
changes are WORK ITEMS in `work_engine.SOURCES["studies"]`, run by the one engine
(`SOURCE_RUNNERS["studies"]` -> `run_item`), one piece of work at a time, off the beat's thread,
with her own model under the WORK lease so conversation goes first. The door ("study
X, Y and Z and improve my project") starts the pipeline at once (`start`).

THE PIPELINE, each step stored before the next begins (a process exit costs at most
the step in flight):

    shape      the lens and the questions (study_reason.draft_lens)
    research   every confirmed comparable and his project, read through the observation
               sources that can read them (study_observe), with provenance, politely,
               following a few same-site links the lens asks for
    compare    measured differences + cited claims (study_reason.compare)
    strategy   ranked hypotheses, each waiting on HIS decision (study_reason.strategize)

When nobody can think the steps do not stop: after the model has been tried, the
lens, the comparison and the strategy fall back to rules, and every artefact says who
drafted it ("rules", "ollama:...", "subscription.auto").

EXECUTION, ONLY AFTER HIS YES (`studies.decide` is the one door to ACCEPTED):

    1. the BASELINE: the hypothesis's metric is read from his project through the same
       observation source, and stored, BEFORE anything is changed;
    2. the path the hypothesis names, each one an existing safe path:
         project_change / experiment  a bounded change drafted as exact edits (the local
                  repair tier's edit format and validator), applied in a throwaway worktree,
                  inspected (`local_repair.inspect_diff`: size, protected paths, secrets,
                  tests), the project's own tests run when it has them, committed on a
                  `thea-study/*` branch - a pull request through `code_worker.open_repair_pr`
                  only where one may be opened and never in a rehearsal; never the default
                  branch, never a merge. Anything not bounded becomes a packet.
         code_work  investigated into a packet queued for a stronger model (work_runners)
         outward    composed from the tool catalog; anything that reaches the world is a
                  handoff he approves (work_runners._compose)
         his        asked once (work_runners._his)
    3. a durable `time_after` wait for the measurement window.

MEASUREMENT (`on_wait`, woken on the beat): the metric is read again through the same
source, compared with the baseline with its caveats said (one reading each side, a
proxy, other commits in the window, whether the change shipped at all), stored, and a
keep / revert / iterate decision is opened for HIM. keep is learned; revert runs the
inverse edits through the same path; iterate asks the strategy for a follow-up he
decides on. Nothing here merges, publishes, sends or spends.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import secrets
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from aletheia import studies as st, study_observe as so, study_reason as sr, waits, work_states as ws

ACTOR = "aletheia-study-run"
EXECUTION = os.environ.get("ALETHEIA_STUDY_EXECUTION", "thread")
PROCESS_ID = uuid.uuid4().hex[:12]
MODEL_RETRY = dt.timedelta(minutes=15)
MODEL_TRIES_BEFORE_RULES = 2
MAX_FOLLOW_PER_TARGET = 2
MAX_FILE_CHARS = 6_000
MAX_EDIT_FILES = 3
MIN_CONFIDENCE = 0.5
MAX_EXTENSIONS = 2
#: Test seams: a thinker (or False for "nobody can think") and an HTTP opener.
THINK: Any = None
OPENER: Callable | None = None

_WORKER: dict[str, Any] = {"thread": None}


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return st._now(now)


stamp = st.stamp


def _journal(kind: str, subject: str, text: str) -> None:
    st._journal(kind, subject, text)


def _rehearsing() -> bool:
    from aletheia import intercom
    return intercom.rehearsing()


def _thinker(now: dt.datetime) -> sr.Think | None:
    if THINK is False:
        return None
    if THINK is not None:
        return THINK
    from aletheia import work_requirements as wr
    return sr.gateway_think() if wr.world("reasoning", now=now)["ok"] else None


# ---- the door ----------------------------------------------------------------------------------

_URL = re.compile(r"https?://[^\s,;<>\"')]+")


def parse_request(words: str) -> dict:
    """What he asked to study, from his sentence: the comparables (addresses, or names to find)
    and the project to improve. Pure. Nothing here knows what kind of thing either is."""
    text = " ".join(str(words or "").split())
    urls = [u.rstrip(".") for u in _URL.findall(text)]
    rest = _URL.sub(" ", text)
    project = ""
    m = re.search(r"\b(?:improve|better|fix up|grow|compare (?:them )?(?:to|with|against))\s+(?:my|our|the)\s+"
                  r"([\w .'&-]{2,60}?)(?:\s+(?:with|using|based|by)\b|[.,!?]|$)", rest, re.I)
    if m:
        project = m.group(1).strip()
    names: list[str] = []
    m = re.search(r"\b(?:study|research|look (?:in)?to|analy[sz]e|compare)\s+(.+?)"
                  r"(?:\s*[,.]?\s*(?:and\s+)?(?:figure out|work out|find out|see|tell me|then|so (?:that|we)|"
                  r"and (?:improve|make|fix|grow))\b|$)", rest, re.I)
    if m:
        chunk = re.sub(r"^(?:these|those|the|them|how)\s+", "", m.group(1).strip(), flags=re.I)
        for part in re.split(r"\s*(?:,|;|\band\b|&)\s*", chunk):
            part = part.strip(" .")
            if part and len(part) <= 60 and not re.fullmatch(r"(?:them|it|those|these|deeply|closely|\s)*", part, re.I):
                names.append(part)
    return {"urls": list(dict.fromkeys(urls)), "names": names, "project": project}


def name_of(url: str) -> str:
    """A sayable name for an address he gave: the site, or the site's path when the site is shared
    by many things (two addresses on one host must not get one name). Pure."""
    parts = re.sub(r"^https?://(?:www\.)?", "", str(url or "")).strip("/").split("/")
    host, path = parts[0], [p for p in parts[1:] if p and "?" not in p][:2]
    return "/".join(path) if len(path) == 2 else (f"{host}/{path[0]}" if path else host)


def discover(name: str, *, search: Callable | None = None) -> list[str]:
    """Candidate addresses for a comparable he named without one: a plain-HTTP search. Proposals only."""
    try:
        from aletheia import research
        found = (search or research.http_search)(name)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for link in found.get("links") or []:
        href = str(link.get("href") or "")
        if re.match(r"^https?://", href) and href not in out:
            out.append(href)
        if len(out) >= 1:
            break
    return out


def start(words: str, *, via: str, project: str = "", path: str = "", repo: str = "", surface: list[str] | None = None,
          comparables: list[dict] | None = None, now: dt.datetime | None = None, search: Callable | None = None,
          run: bool = True) -> dict:
    """The door. Returns {"study", "said"}. Named comparables are studied; searched ones wait for his yes."""
    now = _now(now)
    asked = parse_request(words)
    subject = st.resolve_subject(project or asked["project"], path=path, repo=repo, surface=surface)
    if comparables is None:
        comparables = [{"name": name_of(u), "targets": [u], "named_by": "caleb"} for u in asked["urls"]]
        for name in asked["names"]:
            if any(name.lower() in (c["name"] or "").lower() for c in comparables):
                continue
            comparables.append({"name": name, "targets": discover(name, search=search), "named_by": "search"})
    if not comparables:
        return {"study": None, "said": "Which ones should I study? Name them, or give me their addresses."}
    if not (subject.get("path") or subject.get("repo") or subject.get("surface")):
        return {"study": None, "said": (f"I don't know where {subject.get('name') or 'your project'} lives yet, so "
                                        "I couldn't compare it. Tell me its folder, repository or address.")}
    record = st.propose(words, via=via, subject=subject, comparables=comparables, now=now)
    unconfirmed = [c["name"] for c in record["comparables"] if not c.get("confirmed")]
    if run and not unconfirmed:
        kick(record["id"])
    from aletheia import speech
    names = speech.and_list([c["name"] for c in record["comparables"]][:4])
    if unconfirmed:
        said = (f"I'll study {names} against {subject.get('name') or 'your project'}. I found addresses for "
                f"{speech.and_list(unconfirmed[:3])} by searching; say study them to confirm before I read them.")
    else:
        said = (f"Studying {names} against {subject.get('name') or 'your project'}: I'll read them and yours the "
                "same way, measure the differences, and bring you evidence-backed changes. Nothing changes until "
                "you accept one.")
    return {"study": record, "said": said}


def kick(sid: str) -> None:
    """Carry the pipeline now, off the caller's thread (or inline in tests)."""
    _start(lambda: run_pipeline(sid))


def _busy() -> bool:
    worker = _WORKER.get("thread")
    return worker is not None and worker.is_alive()


def _start(body: Callable[[], Any]) -> None:
    if EXECUTION == "inline":
        body()
        return

    def guarded():
        try:
            body()
        except Exception as exc:  # noqa: BLE001
            _journal("alert", "studies", f"a piece of study work failed ({type(exc).__name__})")
    worker = threading.Thread(target=guarded, name="aletheia-study-work", daemon=True)
    _WORKER["thread"] = worker
    worker.start()


# ---- the pipeline ------------------------------------------------------------------------------

def run_pipeline(sid: str, *, now: dt.datetime | None = None, max_steps: int = 8) -> dict:
    """Run steps until none is left, one blocks, or the study waits on him."""
    record = st.load(sid)
    for _ in range(max_steps):
        record = st.load(sid)
        pending = record.get("pending") or []
        if record.get("state") != st.OPEN or not pending or record.get("blocked"):
            break
        if any(not c.get("confirmed") for c in record.get("comparables") or []) and pending[0] != "shape":
            break
        said = run_step(sid, pending[0], now=now)
        if not said.get("done"):
            break
    return st.load(sid)


def run_step(sid: str, step: str, *, now: dt.datetime | None = None) -> dict:
    from aletheia import local_lease, policy, reasoner
    now = _now(now)
    policy.ensure_not_halted()
    if not st.claim_step(sid, step, PROCESS_ID, now):
        return {"done": False, "why": "not this step's turn, or it is already running"}
    record = st.load(sid)
    think = _thinker(now)
    tries = int(((record.get("model_tries") or {}).get(step)) or 0)
    try:
        with local_lease.purpose(local_lease.WORK):
            if step == "shape":
                return _shape(sid, record, think, now)
            if step == "research":
                return _research(sid, record, now)
            if step == "compare":
                return _compare(sid, record, think, now)
            if step == "strategy":
                return _strategy(sid, record, think, now)
        return {"done": False, "why": f"unknown step {step}"}
    except reasoner.ReasonerUnavailable as exc:
        tries += 1

        def count(r):
            r.setdefault("model_tries", {})[step] = tries
        st.update(sid, count)
        if tries >= MODEL_TRIES_BEFORE_RULES:
            with local_lease.purpose(local_lease.WORK):
                fallback = {"shape": _shape, "compare": _compare, "strategy": _strategy}[step]
                return fallback(sid, st.load(sid), None, now, note=f"the model did not finish ({str(exc)[:120]})")
        st.block_step(sid, step, why=f"no model finished thinking about it ({str(exc)[:160]})",
                      until=now + MODEL_RETRY, state=ws.BLOCKED_MODEL, now=now)
        return {"done": False, "why": "model"}
    except policy.Halted:
        def release(r):
            r["running"] = None
        st.update(sid, release)
        raise
    except Exception as exc:  # noqa: BLE001 - a broken step is a retry, never a crash
        st.block_step(sid, step, why=f"it failed ({type(exc).__name__}: {str(exc)[:160]})",
                      until=now + dt.timedelta(hours=1), state=ws.RETRY_LATER, now=now)
        return {"done": False, "why": type(exc).__name__}


def _shape(sid, record, think, now, note: str = "") -> dict:
    lens = sr.draft_lens(record, think)
    if note:
        lens["drafted_by"]["note"] = note + "; " + str(lens["drafted_by"].get("note") or "")

    def fill(r):
        r["lens"] = {k: lens[k] for k in ("dimensions", "follow", "drafted_by")}
        r["questions"] = lens["questions"]
    st.finish_step(sid, "shape", fill, now=now,
                   said=f"lens drafted by {lens['drafted_by']['provider']}: {len(lens['dimensions'])} dimensions")
    return {"done": True}


def _follow_links(evidence: list[dict], follow: list[str]) -> list[str]:
    if not follow:
        return []
    out = []
    for ev in evidence:
        if ev.get("source") != "web_page":
            continue
        for row in (ev.get("structure") or {}).get("links") or []:
            text, _, href = str(row).partition(" -> ")
            if href and any(w in text.lower() for w in follow) and href not in out and href != ev.get("target"):
                out.append(href)
            if len(out) >= MAX_FOLLOW_PER_TARGET:
                return out
    return out


def _subject_reads(subject: dict) -> tuple[list[str], Callable[[], None]]:
    """Where his project can be read from, and how to clean up afterwards. A project that
    lives only in a remote repository is read from a throwaway mirror (project_checkout)."""
    targets = st.subject_targets(subject)
    if subject.get("path") or not subject.get("repo") or not subject.get("subdir"):
        return targets, lambda: None
    from aletheia import project_checkout
    view = project_checkout.checkout(subject["repo"], subject.get("branch") or "main", subdir=subject["subdir"])
    local = str(Path(view["path"]) / view["subdir"]) if view.get("subdir") else view["path"]
    return [local] + targets, lambda: project_checkout.discard(view)


def _research(sid, record, now) -> dict:
    budget = so.Budget()
    follow = (record.get("lens") or {}).get("follow") or []
    observed, refused = [], []
    targets, cleanup = _subject_reads(record.get("subject") or {})
    try:
        plan = [("subject", t) for t in targets]
        plan += [(f"comparable:{c['key']}", t) for c in record.get("comparables") or [] if c.get("confirmed")
                 for t in c.get("targets") or []]
        for role, target in plan:
            try:
                rows = so.observe(sid, target, role=role, budget=budget, opener=OPENER, now=now)
            except so.ObservationRefused as why:
                refused.append({"target": target, "role": role, "why": str(why)[:200]})
                continue
            except Exception as exc:  # noqa: BLE001 - one unreadable target is recorded, never the study's end
                refused.append({"target": target, "role": role, "why": f"{type(exc).__name__}: {str(exc)[:160]}"})
                continue
            observed += rows
            for extra in _follow_links(rows, follow):
                try:
                    observed += so.observe_page(sid, extra, role=role, budget=budget, opener=OPENER, now=now,
                                                follow_feeds=False)
                except so.ObservationRefused as why:
                    refused.append({"target": extra, "role": role, "why": str(why)[:200]})
                except Exception as exc:  # noqa: BLE001
                    refused.append({"target": extra, "role": role, "why": f"{type(exc).__name__}"})
    finally:
        cleanup()
    by_role = {}
    for ev in observed:
        by_role[ev["role"]] = by_role.get(ev["role"], 0) + 1

    def fill(r):
        r["research"] = {"observations": [e["id"] for e in observed], "refused": refused, "requests": budget.used,
                         "by_role": by_role, "at": stamp(now)}
        if not by_role.get("subject"):
            r.setdefault("notes", []).append("his project could not be read, so nothing could be measured on it")
    st.finish_step(sid, "research", fill, now=now,
                   said=f"read {len(observed)} observations in {budget.used} requests; {len(refused)} refused")
    return {"done": True}


def _compare(sid, record, think, now, note: str = "") -> dict:
    evidence = so.all_evidence(sid)
    comparison = sr.compare(record, evidence, think)
    if note:
        comparison["drafted_by"]["note"] = note

    def fill(r):
        r["comparison"] = {**comparison, "at": stamp(now)}
    st.finish_step(sid, "compare", fill, now=now,
                   said=(f"compared on {len(comparison['rows'])} measured rows; {len(comparison['claims'])} cited "
                         f"claims kept, {comparison['dropped']} uncited dropped, {comparison['guesses']} guesses"))
    return {"done": True}


def _strategy(sid, record, think, now, note: str = "") -> dict:
    evidence = so.all_evidence(sid)
    said = sr.strategize(record, evidence, think)
    if note:
        said["drafted_by"]["note"] = note
    st.finish_step(sid, "strategy", lambda r: r.setdefault("strategy_runs", []).append(
        {"at": stamp(now), "drafted_by": said["drafted_by"], "dropped": said["dropped"],
         "kept": len(said["hypotheses"])}), now=now,
        said=f"{len(said['hypotheses'])} hypotheses kept, {len(said['dropped'])} dropped")
    if said["hypotheses"]:
        st.apply_hypotheses(sid, said["hypotheses"], drafted_by=said["drafted_by"], now=now)
    return {"done": True, "hypotheses": len(said["hypotheses"])}


# ---- the engine's view ---------------------------------------------------------------------------

def source(now: dt.datetime) -> list[dict]:
    """Every open study's unfinished work, in the shared vocabulary. Reads only."""
    from aletheia import work_engine as we
    out: list[dict] = []
    for record in st.all_studies():
        if record.get("state") != st.OPEN:
            continue
        sid, name = record["id"], (record.get("subject") or {}).get("name") or "the project"
        unconfirmed = [c["name"] for c in record.get("comparables") or [] if not c.get("confirmed")]
        pending = record.get("pending") or []
        if unconfirmed:
            out.append(we.item(st.item_id(sid, "comparables"), "studies", f"Confirm what to study against {name}",
                               ws.BLOCKED_USER, requires=["user_decision"],
                               reason="comparables found by searching wait for Caleb's yes",
                               next="when Caleb says study them", priority=2, native_state="comparables",
                               owner=st.OWNER, kind="study_confirm", payload={"study": sid}))
        elif pending:
            step = pending[0]
            blocked = record.get("blocked") or {}
            running = record.get("running") or {}
            until = st.parse(blocked.get("until"))
            if running:
                state, reason, nxt = ws.RUNNING, "", f"finish the {step} step"
            elif blocked and until and until > now:
                state, reason, nxt = blocked.get("state") or ws.RETRY_LATER, blocked.get("why") or "", "try again"
            else:
                state, reason, nxt = ws.READY, "", f"the {step} step"
            out.append(we.item(st.item_id(sid, step), "studies", f"Study for {name}: {step}", state,
                               requires=["network"] if step == "research" else [], reason=reason, next=nxt,
                               not_before=blocked.get("until") if state != ws.READY else None, priority=3,
                               native_state=f"step:{step}:{state}", owner=st.OWNER, kind="study_step",
                               payload={"study": sid, "step": step}))
        for h in record.get("hypotheses") or []:
            if h.get("superseded"):
                continue
            iid, title = st.item_id(sid, h["key"]), f"{name}: {h['title']}"
            if h["state"] == st.PROPOSED:
                out.append(we.item(iid, "studies", title, ws.BLOCKED_USER, requires=["user_decision"],
                                   reason="a proposed change waits for Caleb to accept, reject or reshape it",
                                   next="when Caleb decides", priority=2, native_state="proposed", owner=st.OWNER,
                                   kind="study_decision", payload={"study": sid, "hypothesis": h["key"]}))
            elif h["state"] in (st.ACCEPTED, st.REVERTING):
                out.append(we.item(iid, "studies", title, ws.READY, reason="", priority=2,
                                   next="read the baseline, then carry the change" if h["state"] == st.ACCEPTED
                                   else "revert the change on a branch",
                                   native_state=h["state"].lower(), owner=st.OWNER, kind="study_execute",
                                   payload={"study": sid, "hypothesis": h["key"]}))
            elif h["state"] == st.EXECUTING:
                out.append(we.item(iid, "studies", title, ws.RUNNING, next="finish carrying the change",
                                   native_state="executing", owner=st.OWNER, kind="study_execute",
                                   payload={"study": sid, "hypothesis": h["key"]}))
            elif h["state"] == st.MEASURING:
                out.append(we.item(iid, "studies", title, ws.BLOCKED_EXTERNAL,
                                   reason=(h.get("execution_result") or {}).get("said") or "the change is out",
                                   next=f"measure {h['metric']['name']} again", not_before=h.get("measure_at"),
                                   native_state="measuring", owner=st.OWNER, kind="study_measure",
                                   payload={"study": sid, "hypothesis": h["key"]}))
            elif h["state"] == st.VERDICT:
                out.append(we.item(iid, "studies", title, ws.BLOCKED_USER, requires=["user_decision"],
                                   reason=(h.get("measurement") or {}).get("said") or "measured",
                                   next="when Caleb says keep, revert or iterate", native_state="verdict",
                                   owner=st.OWNER, kind="study_verdict", payload={"study": sid, "hypothesis": h["key"]}))
            elif h["state"] == st.BLOCKED:
                res = h.get("execution_result") or {}
                out.append(we.item(iid, "studies", title, res.get("work_state") or ws.BLOCKED_USER,
                                   reason=res.get("said") or "it could not be carried", next=res.get("next") or "",
                                   native_state="blocked", owner=st.OWNER, kind="study_blocked",
                                   payload={"study": sid, "hypothesis": h["key"]},
                                   evidence={k: res[k] for k in ("packet",) if res.get(k)}))
    return out


def run_item(it: dict, now: dt.datetime) -> dict:
    """`work_engine.SOURCE_RUNNERS["studies"]`: starts the work; the study record holds the truth."""
    payload = it.get("payload") or {}
    sid = payload.get("study")
    if not sid:
        return {"state": ws.FAILED, "reason": "not a study item", "next": ""}
    if EXECUTION != "inline" and _busy():
        return {"noop": True, "state": ws.READY, "reason": "", "next": "after the study work already running"}
    kind = it.get("kind")
    if kind == "study_step":
        _start(lambda: run_pipeline(sid))
        return {"state": ws.RUNNING, "reason": "", "next": f"the {payload.get('step')} step",
                "did": f"carried the study's {payload.get('step')} step", "kind": "started"}
    if kind == "study_execute":
        key = payload.get("hypothesis")
        if not claim_execution(sid, key, now):
            return {"noop": True, "state": ws.READY, "reason": "", "next": "nothing to claim"}
        _start(lambda: execute(sid, key, now=now if EXECUTION == "inline" else None))
        return {"state": ws.RUNNING, "reason": "", "next": "record the baseline, then carry the change",
                "did": "started carrying an accepted change", "kind": "started"}
    return {"noop": True, "state": it.get("state") or ws.BLOCKED_USER, "reason": it.get("reason") or "",
            "next": it.get("next") or ""}


# ---- execution ----------------------------------------------------------------------------------

def claim_execution(sid: str, key: str, now: dt.datetime) -> bool:
    def fn(record, h):
        if h["state"] not in (st.ACCEPTED, st.REVERTING):
            return False
        if h["state"] == st.ACCEPTED and not ((h.get("decision") or {}).get("choice") == "accept"
                                              and not st._her_own((h.get("decision") or {}).get("via"))):
            return False                      # the gate, checked again where the work starts
        h["run"] = {"owner": PROCESS_ID, "at": stamp(now), "was": h["state"]}
        h["state"] = st.EXECUTING
        return True
    try:
        return bool(st.set_hypothesis(sid, key, fn, now=now)[1])
    except st.StudyError:
        return False


def read_metric(sid: str, record: dict, h: dict, *, purpose: str, now: dt.datetime,
                where: str | None = None) -> dict:
    """The hypothesis's metric on his project, read through the observation source now.
    {"metric", "value", "evidence", "digest", "target", "source"}"""
    subject = record.get("subject") or {}
    budget = so.Budget(limit=8)
    targets = [where] if where else st.subject_targets(subject)
    cleanup = lambda: None  # noqa: E731
    if not where and subject.get("repo") and subject.get("subdir") and not subject.get("path"):
        targets, cleanup = _subject_reads(subject)
    rows: list[dict] = []
    try:
        for target in targets:
            try:
                rows += so.observe(sid, target, role="subject" if purpose != "variant" else "variant",
                                   budget=budget, opener=OPENER, now=now)
            except so.ObservationRefused:
                continue
    finally:
        cleanup()
    name = h["metric"]["name"]
    value, ids = so.metric_value(rows, name)
    carrying = next((r for r in rows if r["id"] in ids), {})
    for r in rows:
        try:
            r["purpose"] = purpose
            r["hypothesis"] = h["key"]
            from aletheia import stateio
            stateio.write_json_atomic(so.evidence_dir(sid) / f"{r['id']}.json", r)
        except (OSError, ValueError):
            pass
    return {"metric": name, "value": value, "evidence": ids, "digest": carrying.get("digest"),
            "target": carrying.get("target"), "source": carrying.get("source"), "file": carrying.get("file")}


def execute(sid: str, key: str, *, now: dt.datetime | None = None) -> dict:
    """Carry one ACCEPTED (or REVERTING) hypothesis. Baseline first; then its path."""
    from aletheia import local_lease, policy
    now = _now(now)
    policy.ensure_not_halted()
    record = st.load(sid)
    h = st.hypothesis(record, key)
    was = (h.get("run") or {}).get("was") or st.ACCEPTED
    if h["state"] != st.EXECUTING:
        return {"state": h["state"], "said": "not claimed for execution"}
    try:
        with local_lease.purpose(local_lease.WORK):
            if was == st.REVERTING:
                return _revert(sid, record, h, now)
            baseline = read_metric(sid, record, h, purpose="baseline", now=now)
            if baseline["value"] is None:
                return _blocked(sid, key, now, said=f"I couldn't read {h['metric']['name']} on the project, so no "
                                                    "baseline exists and nothing was changed",
                                work_state=ws.RETRY_LATER, nxt="read the project again")
            st.record_baseline(sid, key, baseline, now=now)
            record = st.load(sid)
            h = st.hypothesis(record, key)
            path = (h.get("execution") or {}).get("path")
            if path in ("project_change", "experiment"):
                return _change(sid, record, h, now)
            if path == "code_work":
                return _packet(sid, record, h, now, reasons=["the change is code work beyond a bounded edit"])
            return _world(sid, record, h, now, path=path)
    except policy.Halted:
        st.set_hypothesis(sid, key, lambda r, hh: hh.update(state=was), now=now)
        raise
    except Exception as exc:  # noqa: BLE001 - recorded on the hypothesis, never lost
        return _blocked(sid, key, now, said=f"carrying it failed ({type(exc).__name__}: {str(exc)[:160]})",
                        work_state=ws.RETRY_LATER, nxt="try again later", back_to=was)


def _blocked(sid: str, key: str, now: dt.datetime, *, said: str, work_state: str, nxt: str,
             extra: dict | None = None, back_to: str = "") -> dict:
    def fn(record, h):
        h["execution_result"] = {**(h.get("execution_result") or {}), "said": said, "work_state": work_state,
                                 "next": nxt, "at": stamp(now), "changed": False, **(extra or {})}
        h["state"] = back_to if back_to and work_state == ws.RETRY_LATER else st.BLOCKED
        st._history(h, f"blocked: {said[:160]}", now)
        return h
    st.set_hypothesis(sid, key, fn, now=now)
    _journal("event", st.item_id(sid, key), f"an accepted change could not be carried ({work_state})")
    return {"state": work_state, "said": said}


def _pseudo_item(record: dict, h: dict) -> dict:
    return {"id": st.item_id(record["id"], h["key"]), "source": "studies", "title": h["title"],
            "payload": {"text": h["change"]}, "state": ws.READY}


def _packet(sid: str, record: dict, h: dict, now: dt.datetime, *, reasons: list[str], attempts=None,
            base_sha: str = "") -> dict:
    from aletheia import work_runners
    subject = record.get("subject") or {}
    target = ({"repo": subject.get("repo") or "", "base_ref": subject.get("branch") or "",
               "subdir": subject.get("subdir") or "", "charter": subject.get("charter") or ""}
              if subject.get("repo") else None)
    comparison = record.get("comparison") or {}
    evidence_text = (f"Study {sid}. Accepted by Caleb: {h['title']}. Change: {h['change']}. Expected: "
                     f"{h['expected_effect']}. Metric: {h['metric']['name']} ({h['metric']['direction']}), baseline "
                     f"{(h.get('baseline') or {}).get('value')}. Measured rows: "
                     + " | ".join(r["said"] for r in (comparison.get("rows") or [])[:5]))
    out = work_runners._queue_packet(_pseudo_item(record, h), kind="study_change", reasons=reasons, target=target,
                                     objective=h["change"], evidence_text=evidence_text, base_sha=base_sha,
                                     attempts=attempts or [], did=f"queued {h['title']} for a stronger model")
    return _blocked(sid, h["key"], now, said=f"queued for a stronger model: {'; '.join(reasons)[:200]}",
                    work_state=ws.NEEDS_STRONGER_MODEL, nxt=out["next"],
                    extra={"packet": (out.get("evidence") or {}).get("packet"), "route": "packet"})


def _world(sid: str, record: dict, h: dict, now: dt.datetime, *, path: str) -> dict:
    """outward / his: the existing handoff and ask-once paths. Nothing is sent from here."""
    from aletheia import work_runners
    it = _pseudo_item(record, h)
    if path == "his":
        out = work_runners._his(it, {"why": "only Caleb can make this change (" + "; ".join(h.get("notes") or [])
                                     + ")" if h.get("notes") else "only Caleb can make this change"}, now)
    else:
        out = work_runners._compose(it, {"why": "it reaches the world, so it is handed to Caleb"}, now)
    return _ready(sid, h["key"], now, route=path, said=out.get("did") or out.get("reason") or "handed to Caleb",
                  extra={"handoff": (out.get("evidence") or {}).get("approval"), "work_state": out.get("state")},
                  changed=False)


def _ready(sid: str, key: str, now: dt.datetime, *, route: str, said: str, extra: dict, changed: bool) -> dict:
    def fn(record, h):
        h["execution_result"] = {"said": said, "route": route, "at": stamp(now), "changed": changed, **extra}
        h["state"] = st.MEASURING
        st.schedule_measurement(record, h, now)
        st._history(h, f"carried ({route}); measuring again at {h.get('measure_at')}", now)
        return h
    record, h = st.set_hypothesis(sid, key, fn, now=now)
    _journal("action", st.item_id(sid, key), f"an accepted change was carried ({route}); measurement scheduled")
    st._notify(record, "A change from your study is ready", f"{said[:300]}", key=f"study-ready:{sid}:{key}")
    return {"state": ws.BLOCKED_USER, "said": said}


def _project_files(root: Path, h: dict, baseline: dict) -> list[str]:
    from aletheia import investigation as inv
    code, out = inv.git(["ls-files"], root)
    tracked = set(out.splitlines()) if code == 0 else set()
    wanted = [f for f in (h.get("execution") or {}).get("files") or [] if f in tracked]
    if baseline.get("file") and baseline["file"] in tracked:
        wanted.insert(0, baseline["file"])
    return list(dict.fromkeys(wanted))[:MAX_EDIT_FILES]


_ACTIVE_CONTENT = re.compile(r"<\s*(?:script|iframe|object|embed)\b|\bon[a-z]+\s*=\s*['\"]|javascript:", re.I)


def _change(sid: str, record: dict, h: dict, now: dt.datetime) -> dict:
    """A bounded change on a branch, through the local repair tier's parts."""
    from aletheia import investigation as inv, local_repair, policy, reasoner
    subject = record.get("subject") or {}
    if not subject.get("path"):
        return _packet(sid, record, h, now, reasons=["the project is not checked out on this machine, so a bounded "
                                                     "change cannot be drafted and verified here"])
    source = Path(subject["path"]).expanduser().resolve()
    base_sha = inv.resolve_sha(source, "HEAD")
    baseline = h.get("baseline") or {}
    name = f"study-{sid}-{h['key']}-{secrets.token_hex(3)}"
    think = _thinker(now)
    if think is None:
        return _packet(sid, record, h, now, reasons=["no model can draft the edit right now"], base_sha=base_sha)
    branch = ""
    with inv.worktree(source, base_sha, name) as top:
        files = _project_files(top, h, baseline)
        if not files:
            return _packet(sid, record, h, now, base_sha=base_sha,
                           reasons=["no file of the project was identified for the change"])
        contents = {f: (top / f).read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS] for f in files}
        validator = local_repair._edits_validator(set(files))
        context = {"decided_change": {"title": h["title"], "change": h["change"], "expected_effect": h["expected_effect"],
                                      "metric": h["metric"]["description"], "direction": h["metric"]["direction"],
                                      "variant": (h.get("execution") or {}).get("variant") or ""},
                   "files": contents}
        try:
            output, provider = think(sr.EDIT_SYSTEM, f"Make this change: {h['change'][:400]}", context=context,
                                     validator=validator)
        except reasoner.ReasonerUnavailable as exc:
            return _blocked(sid, h["key"], now, said=f"no model finished drafting the edit ({str(exc)[:120]})",
                            work_state=ws.RETRY_LATER, nxt="draft it again", back_to=st.ACCEPTED)
        draft = validator(output)
        attempt = {"provider": provider, "summary": draft["summary"], "confidence": draft["confidence"],
                   "edits": len(draft["edits"])}
        if not draft["bounded"] or not draft["edits"] or draft["confidence"] < MIN_CONFIDENCE:
            return _packet(sid, record, h, now, base_sha=base_sha, attempts=[attempt],
                           reasons=[f"the drafted edit was not a confident bounded change ({draft['summary'][:120]})"])
        policy.ensure_not_halted()
        try:
            originals = local_repair.apply_edits(top, draft["edits"])
        except local_repair.RepairRefused as why:
            return _packet(sid, record, h, now, base_sha=base_sha, attempts=[{**attempt, "refused": str(why)}],
                           reasons=[f"the drafted edit did not apply ({why})"])
        inspection = local_repair.inspect_diff(subject.get("repo") or source.name, originals, top)
        added = [ln for ln in inspection["diff"].splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        if any(_ACTIVE_CONTENT.search(ln) for ln in added):
            inspection["refusals"].append("active_content: the edit adds a script, a frame or an event handler")
        if inspection["refusals"] or not inspection["changed"]:
            local_repair.restore(top, originals)
            return _packet(sid, record, h, now, base_sha=base_sha,
                           attempts=[{**attempt, "refusals": inspection["refusals"][:4]}],
                           reasons=["the edit was refused on inspection: " + "; ".join(inspection["refusals"][:2])
                                    if inspection["refusals"] else "the edit changed nothing"])
        tests = None
        if (top / "tests").is_dir() or inv.uses_pytest(top):
            tests = inv.run_tests(top)
            if not tests["passed"]:
                local_repair.restore(top, originals)
                return _packet(sid, record, h, now, base_sha=base_sha,
                               attempts=[{**attempt, "tests": tests.get("failing")[:5]}],
                               reasons=["the project's own tests fail with the change"])
        predicted = read_metric(sid, record, h, purpose="variant", now=now, where=str(top))
        branch = f"thea-study/{re.sub(r'[^a-z0-9-]+', '-', sid)}-{h['key']}-{secrets.token_hex(2)}"
        for args in (["switch", "-c", branch], ["add", "--", *inspection["changed"].keys()]):
            code, out = inv.git(args, top)
            if code != 0:
                raise RuntimeError(f"git {args[0]} failed: {inv.clean(out, 160)}")
        code, out = inv.git(["commit", "-m", f"[THEA-STUDY] {h['title'][:60]}", "-m",
                             f"Study: {sid} hypothesis {h['key']}\nAccepted by: Caleb ({(h.get('decision') or {}).get('at')})\n"
                             f"Metric: {h['metric']['name']} {h['metric']['direction']}; baseline {baseline.get('value')} "
                             f"read {baseline.get('at')}\nDrafted by: {provider}\nBase: {base_sha}"],
                            top, identity=("Thea (study)", "thea@localhost"))
        if code != 0:
            raise RuntimeError(f"git commit failed: {inv.clean(out, 160)}")
        _c, head = inv.git(["rev-parse", "HEAD"], top)
        commit = head.strip().splitlines()[-1] if head.strip() else ""
        publish = {}
        if subject.get("repo") and _can_publish():
            try:
                from aletheia import code_worker
                pr = code_worker.open_repair_pr(subject["repo"], base_sha=base_sha,
                                                base_branch=subject.get("branch") or "main",
                                                files={p: {"content": (top / p).read_text(encoding="utf-8"),
                                                           "mode": "100644"} for p in inspection["changed"]},
                                                task_id=f"study-{h['key']}-{secrets.token_hex(3)}",
                                                title=h["title"][:70],
                                                body=f"From study {sid}, accepted by Caleb. {h['change'][:600]}")
                publish = {"pr_url": pr.get("pr_url")}
            except Exception as exc:  # noqa: BLE001 - the branch stands; the PR is retried by him or later
                publish = {"pr_error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    where = publish.get("pr_url") or f"branch {branch} in {source.name}"
    said = (f"{h['title']}: the change is ready on {where}"
            + (" (a rehearsal opens no pull request)" if _rehearsing() else "")
            + f"; on the branch {h['metric']['name']} reads {so_fmt(predicted.get('value'))}, baseline "
              f"{so_fmt(baseline.get('value'))}")
    return _ready(sid, h["key"], now, route=(h.get("execution") or {}).get("path") or "project_change", said=said,
                  changed=True,
                  extra={"branch": branch, "commit": commit, "base_sha": base_sha, "repo_path": str(source),
                         "files": list(inspection["changed"]), "diff_lines": inspection["lines"],
                         "diff": inv.clean(inspection["diff"], 4_000), "drafted_by": provider,
                         "edits": draft["edits"], "predicted": predicted, "tests": (tests or {}).get("passed"),
                         "review": "none by a second model: Caleb reviews the branch before it ships", **publish})


def so_fmt(value: Any) -> str:
    return sr._fmt(value if isinstance(value, (int, float)) else None)


def _can_publish() -> bool:
    if _rehearsing():
        return False
    from aletheia import work_runners
    return work_runners._gh_can_publish()


def _revert(sid: str, record: dict, h: dict, now: dt.datetime) -> dict:
    """His revert: the inverse of the stored edits, on a new branch from the project's HEAD."""
    from aletheia import investigation as inv, local_repair
    result = h.get("execution_result") or {}
    subject = record.get("subject") or {}
    edits = [{"path": e["path"], "find": e["replace"], "replace": e["find"], "why": "revert"}
             for e in reversed(result.get("edits") or [])]
    if not edits or not subject.get("path"):
        return _world(sid, record, h, now, path="his")
    source = Path(subject["path"]).expanduser().resolve()
    base_sha = inv.resolve_sha(source, "HEAD")
    with inv.worktree(source, base_sha, f"study-revert-{h['key']}-{secrets.token_hex(3)}") as top:
        try:
            originals = local_repair.apply_edits(top, edits)
        except local_repair.RepairRefused:
            said = (f"the change is not on the project's main line ({result.get('branch')} was never merged), so "
                    "reverting it means deleting that branch - yours to do")
            st.set_hypothesis(sid, h["key"], lambda r, hh: hh.update(
                state=st.REVERTED, revert={"said": said, "at": stamp(now)}), now=now)
            return {"state": ws.DONE, "said": said}
        inspection = local_repair.inspect_diff(subject.get("repo") or source.name, originals, top)
        branch = f"thea-study/{re.sub(r'[^a-z0-9-]+', '-', sid)}-{h['key']}-revert-{secrets.token_hex(2)}"
        for args in (["switch", "-c", branch], ["add", "--", *inspection["changed"].keys()]):
            inv.git(args, top)
        inv.git(["commit", "-m", f"[THEA-STUDY] revert: {h['title'][:60]}", "-m",
                 f"Study: {sid} hypothesis {h['key']}; Caleb's verdict: revert"], top,
                identity=("Thea (study)", "thea@localhost"))
    said = f"the revert of {h['title']} is ready on branch {branch}; merging it is yours"
    st.set_hypothesis(sid, h["key"], lambda r, hh: hh.update(
        state=st.REVERTED, revert={"said": said, "branch": branch, "at": stamp(now)}), now=now)
    _journal("action", st.item_id(sid, h["key"]), "a revert branch is ready for Caleb")
    return {"state": ws.BLOCKED_USER, "said": said}


# ---- measurement ---------------------------------------------------------------------------------

def _shipped(record: dict, h: dict) -> tuple[bool | None, list[str]]:
    """Is the change on the project's main line now, and what else landed in the window."""
    from aletheia import investigation as inv
    result = h.get("execution_result") or {}
    subject = record.get("subject") or {}
    if not result.get("changed"):
        return None, []
    if not subject.get("path") or not result.get("commit"):
        return None, []
    source = Path(subject["path"]).expanduser()
    code, out = inv.git(["log", "--no-merges", "--format=%H%x1f%s", f"{result['base_sha']}..HEAD"], source)
    if code != 0:
        return None, []
    rows = [line.split("\x1f", 1) for line in out.splitlines() if "\x1f" in line]
    shipped = any(sha == result["commit"] for sha, _ in rows)
    code2, tree = inv.git(["diff", "--stat", result["commit"], "HEAD", "--", *(result.get("files") or [])], source)
    if not shipped and code2 == 0 and not tree.strip():
        shipped = True                       # merged by a new commit with the same content (a squash)
    others = [subj for sha, subj in rows if sha != result["commit"] and "[THEA-STUDY]" not in subj]
    return shipped, others


def measure(sid: str, key: str, *, now: dt.datetime | None = None) -> dict:
    """The window ended: read the metric again the same way, compare, and ask him."""
    now = _now(now)
    record = st.load(sid)
    h = st.hypothesis(record, key)
    if h["state"] != st.MEASURING:
        return {"said": f"not measuring ({h['state']})"}
    baseline = h.get("baseline") or {}
    after = read_metric(sid, record, h, purpose="measurement", now=now)
    shipped, others = _shipped(record, h)
    result = h.get("execution_result") or {}
    extensions = len([m for m in h.get("measurements") or [] if m.get("extended")])
    caveats = ["one reading before and one after: no repeated measures, so noise cannot be told apart from effect"]
    if after.get("source") == "local_repo":
        caveats.append("a proxy read from the project's own files, not an outcome such as visits or sign-ups")
    if others:
        caveats.append(f"{len(others)} other commit(s) landed in the window and may explain part of any change: "
                       + "; ".join(o[:60] for o in others[:3]))
    if not result.get("changed"):
        caveats.append("nothing was changed by her; the change was handed to Caleb, so it may not have happened")
    if after["value"] is None:
        m = {"at": stamp(now), "value": None, "said": f"I couldn't read {h['metric']['name']} again", "caveats": caveats}
    else:
        before = baseline.get("value")
        delta = None if before is None else round(after["value"] - before, 3)
        wanted = 1 if h["metric"]["direction"] == "increase" else -1
        moved = None if delta is None else (delta * wanted > 0)
        m = {"at": stamp(now), "value": after["value"], "baseline": before, "change": delta,
             "relative": None if not before else round(delta / abs(before), 3), "moved_as_expected": moved,
             "evidence": after["evidence"], "baseline_evidence": baseline.get("evidence"), "shipped": shipped,
             "caveats": caveats}
        m["said"] = (f"{h['metric']['description']} went from {so_fmt(before)} to {so_fmt(after['value'])} after "
                     f"{h['title'].rstrip('.')}" + ("" if moved else ", which is not the direction we wanted"
                                                   if moved is False else ""))
    if shipped is False and extensions < MAX_EXTENSIONS:
        m.update(extended=True, said=(f"{h['title'].rstrip('.')} is still only on its branch, so there is nothing "
                                      "to measure yet; I'll look again after another window"))

        def fn(record, hh):
            hh["measurements"] = (hh.get("measurements") or []) + [m]
            st.schedule_measurement(record, hh, now)
        st.set_hypothesis(sid, key, fn, now=now)
        return {"said": m["said"], "extended": True}
    if shipped is False:
        m["caveats"].append("the change never reached the project's main line, so this measures no change at all")
    suggestion = ("keep" if m.get("moved_as_expected") and shipped is not False
                  else "revert" if m.get("moved_as_expected") is False and shipped else "iterate")
    m["suggestion"] = suggestion

    def fn(record, hh):
        hh["measurements"] = (hh.get("measurements") or []) + [m]
        hh["measurement"] = m
        hh["state"] = st.VERDICT
        st.open_verdict(record, hh, now)
        record["results"] = (record.get("results") or [])[-st.MAX_RESULTS:] + [
            {"at": stamp(now), "hypothesis": key, "text": m["said"], "suggestion": suggestion}]
        st._history(hh, f"measured: {m['said'][:160]}", now)
    record, _ = st.set_hypothesis(sid, key, fn, now=now)
    _journal("event", st.item_id(sid, key), f"a change was measured; Caleb decides keep, revert or iterate "
                                            f"(suggested: {suggestion})")
    st._notify(record, "Your study measured a change",
               f"{m['said']}. I'd {suggestion} it; the call is yours.", key=f"study-measured:{sid}:{key}:{stamp(now)}")
    return {"said": m["said"], "suggestion": suggestion}


def on_wait(held: dict, event: str, now: dt.datetime) -> dict:
    """`waits.HANDLERS["studies"]`."""
    ctx = held.get("context") or {}
    sid, key, purpose = ctx.get("study"), ctx.get("hypothesis"), ctx.get("purpose")
    if not sid or not key:
        return {"said": "not a study wait"}
    if purpose == "measure" and event == waits.WOKE:
        return measure(sid, key, now=now)
    if purpose in ("decision", "verdict") and event == waits.WOKE:
        decision = (held.get("outcome") or {}).get("evidence") or {}
        record = st.load(sid)
        h = st.hypothesis(record, key)
        choice = str(decision.get("choice") or "").lower()
        if purpose == "decision" and h["state"] == st.PROPOSED and choice in st.DECISIONS:
            st.decide(sid, key, choice, words=decision.get("words") or "", via=decision.get("via") or "", now=now)
        if purpose == "verdict" and h["state"] == st.VERDICT and choice in st.VERDICTS:
            st.verdict(sid, key, choice, words=decision.get("words") or "", via=decision.get("via") or "", now=now)
        return {"said": f"his {purpose} is on the study"}
    return {"said": f"{purpose} {event}"}


# ---- the intercom's door ---------------------------------------------------------------------------

def command(kind: str, cmd: dict, *, quote: str = "", via: str) -> str:
    """`study_new`, `studies`, `study_decide`, `study_confirm`, said and answered in sentences."""
    from aletheia import speech
    if kind == "studies":
        return st.spoken_status(str(cmd.get("which") or ""), str(cmd.get("about") or ""))
    if kind == "study_new":
        words = " ".join(str(cmd.get("words") or quote or "").split())
        return start(words, via=via, project=str(cmd.get("project") or ""), path=str(cmd.get("path") or ""))["said"]
    open_rows = [s for s in st.all_studies() if s.get("state") == st.OPEN]
    if not open_rows:
        return "You don't have a study open. Say study, then what to study and which project to improve."
    if kind == "study_confirm":
        record = st.find(str(cmd.get("study") or "")) or open_rows[-1]
        hit = st.confirm_comparables(record["id"], None, via=via)
        if not hit:
            return "Everything in that study is already confirmed."
        kick(record["id"])
        return f"Confirmed {speech.count_phrase(hit, 'comparable')}. I'll read them and your project now."
    choice = str(cmd.get("choice") or "").strip().lower()
    which = str(cmd.get("which") or "")
    words = " ".join(str(cmd.get("words") or "").split()) or " ".join(str(quote or "").split())[:300]
    states = (st.PROPOSED,) if choice in st.DECISIONS else (st.VERDICT,) if choice in st.VERDICTS else ()
    if not states:
        return "Say accept, reject or reshape for a proposal, or keep, revert or iterate for a measured change."
    candidates = ([st.find(str(cmd.get("study")))] if cmd.get("study") else []) or \
        sorted(open_rows, key=lambda s: s.get("updated_at") or "", reverse=True)
    for record in [c for c in candidates if c]:
        h = st.pick_hypothesis(record, which, states)
        if h is None:
            continue
        try:
            if choice in st.DECISIONS:
                st.decide(record["id"], h["key"], choice, words=words, via=via)
            else:
                st.verdict(record["id"], h["key"], choice, words=words, via=via)
        except (st.StudyError, PermissionError) as exc:
            return f"I didn't record that: {exc}."
        title = h["title"].rstrip(".")
        if choice == "accept":
            return (f"Accepted: {title}. I'll read {h['metric']['name'].replace('_', ' ')} on your project first, "
                    "then make the change on a branch; nothing merges or goes out without you.")
        if choice == "reject":
            return f"Rejected: {title}."
        if choice == "reshape":
            kick(record["id"])
            return f"I'll reshape {title} with what you said and bring it back for a decision."
        if choice == "keep":
            return f"Keeping {title}. I've noted what it did, so the next proposals learn from it."
        if choice == "revert":
            return f"I'll prepare a revert of {title} on a branch for you."
        kick(record["id"])
        return f"I'll draft a follow-up to {title} from what we measured."
    if choice in st.DECISIONS:
        return "Which one? " + (st.spoken_status("", "change") or "")
    return "Nothing is waiting for keep, revert or iterate right now."
