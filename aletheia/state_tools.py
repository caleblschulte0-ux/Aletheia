"""The three tools a model needs to answer questions about her own state.

`state.now` is the live snapshot (`current_state`), `applications.query`
is the application records (`apply_run`), `journal.query` is the journal.
Every one of them READS: nothing here changes a store, so the policy
broker runs them without an approval, and the local model may see them.

Each answer says which of the three situations the store is in — full,
empty, or unreadable — because a model asked about a store nothing in its
context mentions denies the store exists (CLAUDE.md, "A store with a
writer and no reader makes her a liar"). An empty list still proves the
store; an unreadable one says so in its own words.
"""
from __future__ import annotations

import json
from typing import Any

from aletheia import tools

#: How much of a record a model is shown. Bounded, because an observation
#: is fed back into a prompt whose whole budget is a few thousand chars.
MAX_RECORDS = 8
MAX_TEXT = 240
MAX_QUESTIONS = 4

#: What of an application record travels. The fields that say what the job
#: is, where it stands and what stopped it — never the filled values (his
#: answers) and never the raw steps.
RECORD_FIELDS = ("id", "state", "company", "job_title", "url", "found_on",
                 "staged_at", "submitted_at", "pressed_at", "failure", "why",
                 "captcha", "captcha_note", "say", "closed_because", "outcome",
                 "employment", "host", "signup")


def _short(value: Any, limit: int = MAX_TEXT) -> Any:
    if isinstance(value, str):
        value = " ".join(value.split())
        return value if len(value) <= limit else value[:limit].rstrip() + "..."
    return value


def summarise_record(record: dict) -> dict:
    """One application, the way a model should see it."""
    out = {key: _short(record.get(key)) for key in RECORD_FIELDS
           if record.get(key) not in (None, "", [], {})}
    questions = record.get("questions") or record.get("not_filled") or []
    labels = [_short(str(q.get("label") or ""), 80) for q in questions
              if isinstance(q, dict) and q.get("label")]
    if labels:
        out["questions_waiting"] = labels[:MAX_QUESTIONS]
        if len(labels) > MAX_QUESTIONS:
            out["questions_waiting_more"] = len(labels) - MAX_QUESTIONS
    evidence = record.get("click_evidence")
    if isinstance(evidence, dict) and evidence:
        out["click_evidence"] = {k: _short(v, 120) for k, v in evidence.items()
                                 if k in ("captcha", "captcha_on_form", "covered_by",
                                          "button_found", "screenshot")}
    fit = record.get("fit")
    if isinstance(fit, dict) and fit:
        out["fit"] = {"realistic": fit.get("realistic"), "by": fit.get("by"),
                      "why": _short(fit.get("why"), 160)}
    result = record.get("result")
    if isinstance(result, dict) and result:
        out["result"] = {"verdict": result.get("verdict"), "note": _short(result.get("note"), 160)}
    return out


def _matches(record: dict, words: str) -> bool:
    want = " ".join(str(words or "").split()).casefold()
    if not want:
        return True
    haystack = " ".join(str(record.get(k) or "") for k in
                        ("id", "company", "job_title", "url", "page_title", "host")).casefold()
    return all(part in haystack for part in want.split())


def applications_query(args: dict, **_ignored) -> dict:
    """What she has applied to, or tried to — filtered, summarised, counted."""
    from aletheia import apply_run
    try:
        rows = apply_run.all_runs()
    except Exception as exc:  # noqa: BLE001 - the answer must say the store is unreadable
        return {"readable": False, "records": [], "counts": {},
                "note": f"the application records could not be read ({type(exc).__name__})"}
    # "needs you", "Needs-You" and NEEDS_YOU are one state: a model that spells it
    # the way a person says it must not be told the store has nothing.
    state = "_".join(str(args.get("state") or "").replace("-", " ").upper().split())
    # BOTH filter. `which or company` let `which` silently replace `company`,
    # so {"which": "engineer", "company": "Stripe"} returned every engineer
    # role anywhere - an answer about the wrong employer, said confidently.
    which = str(args.get("which") or "")
    company = str(args.get("company") or "")
    asked = " ".join(part for part in (which, company) if part.strip())
    limit = args.get("limit") or MAX_RECORDS
    try:
        limit = max(1, min(int(limit), MAX_RECORDS))
    except (TypeError, ValueError):
        limit = MAX_RECORDS
    counts: dict[str, int] = {}
    for record in rows:
        counts[str(record.get("state"))] = counts.get(str(record.get("state")), 0) + 1
    found = [r for r in rows if (not state or r.get("state") == state)
             and _matches(r, which) and _matches(r, company)]
    found.sort(key=lambda r: str(r.get("submitted_at") or r.get("staged_at") or ""), reverse=True)
    out = {"readable": True, "total": len(rows), "counts": counts,
           "matched": len(found), "records": [summarise_record(r) for r in found[:limit]]}
    if not rows:
        out["note"] = ("READ AND EMPTY: the application store exists and holds no records. "
                       "Say nothing has been applied to through her; never say there is no record.")
    elif not found:
        out["note"] = (f"no record matches {asked!r}"
                       + (f" in state {state}" if state else "")
                       + f"; the store holds {len(rows)} records in total")
    return out


def journal_query(args: dict, **_ignored) -> dict:
    """Her journal, by words, kind and window. What she actually did."""
    from aletheia import journal
    hours = args.get("hours") or 24
    try:
        hours = max(0.25, min(float(hours), 24.0 * 31))
    except (TypeError, ValueError):
        hours = 24.0
    limit = args.get("limit") or 12
    try:
        limit = max(1, min(int(limit), 30))
    except (TypeError, ValueError):
        limit = 12
    term = " ".join(str(args.get("term") or "").split()).casefold()
    kind = str(args.get("kind") or "").strip().lower()
    try:
        rows = journal.since(hours)
        torn = journal.torn_lines()
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "entries": [],
                "note": f"the journal could not be read ({type(exc).__name__})"}
    if kind:
        rows = [e for e in rows if e.get("kind") == kind]
    if term:
        rows = [e for e in rows
                if all(part in (str(e.get("subject", "")) + " " + str(e.get("text", ""))).casefold()
                       for part in term.split())]
    entries = [{"ts": e.get("ts"), "kind": e.get("kind"), "actor": e.get("actor"),
                "subject": e.get("subject"), "text": _short(e.get("text"))}
               for e in rows[-limit:]]
    out = {"readable": True, "hours": hours, "matched": len(rows), "entries": entries}
    if torn:
        out["torn_lines"] = torn
    if not rows:
        out["note"] = ("nothing in the journal matched"
                       + (f" {term!r}" if term else "")
                       + f" in the last {hours:g} hours. That is a fact about this search, "
                       "not proof nothing happened.")
    return out


def state_now(args: dict, **_ignored) -> dict:
    """The live snapshot, or one section of it."""
    from aletheia import current_state
    # "job hunt", "Job-Hunt" and "job_hunt" are one section: the first real
    # local run asked for "job hunt", was told there is no such section, and
    # asked the same thing again.
    section = "_".join(str(args.get("section") or "").strip().lower().replace("-", " ").split())
    try:
        snapshot = current_state.snapshot()
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "note": f"the snapshot could not be built ({type(exc).__name__})"}
    if section:
        if section not in snapshot:
            return {"readable": True, "note": f"no section {section!r}; sections are "
                    + ", ".join(sorted(k for k in snapshot if isinstance(snapshot[k], (dict, list))))}
        return {"readable": True, "section": section, section: snapshot[section]}
    # The whole thing, but bounded: an interface reads the full snapshot
    # from /api/state, a model reads the headline sections.
    slim = {k: v for k, v in snapshot.items()
            if k in ("as_of", "halted", "agent", "job_hunt", "browser", "code",
                     "needs_attention", "waiting", "programs")}
    return {"readable": True, "state": json.loads(json.dumps(slim, default=str))}


TOOLS = (
    tools.declare(
        "state.now",
        description=("What you are doing right now, the job hunt so far today, the browser, "
                     "the code you are running, and what needs attention - the live snapshot. "
                     "section narrows it to one of: agent, job_hunt, browser, code, "
                     "needs_attention, focus, waiting, upcoming, capability_gaps."),
        input_schema={"properties": {"section": {"type": "string"}}},
        handler=state_now, capability="state.now", reads=("current_state",),
        provenance=tools.TRUSTED_LOCAL_STATE),
    tools.declare(
        "applications.query",
        description=("The job applications you have sent, staged, held or failed - the records "
                     "themselves, with what stopped each one (a CAPTCHA, questions only he can "
                     "answer, an account wall, a refused form). which filters by employer, job "
                     "title, url or id; state by SUBMITTED, AWAITING_YOU, NEEDS_YOU, FAILED, "
                     "REJECTED, CLOSED, NEEDS_ACCOUNT or SUBMITTING; limit at most 8."),
        input_schema={"properties": {"which": {"type": "string"}, "company": {"type": "string"},
                                     "state": {"type": "string"},
                                     "limit": {"type": ["integer", "string"]}}},
        handler=applications_query, capability="state.now", reads=("applications",),
        provenance=tools.TRUSTED_LOCAL_STATE),
    tools.declare(
        "journal.query",
        description=("Your own journal - every action, decision, alert and recovery you recorded. "
                     "term filters by words, kind by action, decision, alert, recovery, event, "
                     "note or task, hours is the window (default 24), limit at most 30. Use "
                     "kind=alert or kind=recovery for what went wrong."),
        input_schema={"properties": {"term": {"type": "string"}, "kind": {"type": "string"},
                                     "hours": {"type": ["integer", "number", "string"]},
                                     "limit": {"type": ["integer", "string"]}}},
        handler=journal_query, capability="journal.search", reads=("journal",),
        provenance=tools.TRUSTED_LOCAL_STATE),
)
