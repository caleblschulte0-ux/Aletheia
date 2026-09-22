"""The job hunt's door into `pursuit`: an application record becomes an
opportunity with its evidence, and what happens to it flows back.

This is the ONLY place the general pursuit knows a role, an employer or a
resume: here they are evidence and words, and `pursuit` itself carries
none of them (`tests/test_studies.py` checks). Nothing here decides what
to do about an opportunity - that is the reasoner's, per opportunity.
"""
from __future__ import annotations

import datetime as dt

from aletheia import journal, pursuit

ACTOR = "aletheia-pursuit"
#: Applications in these states are live situations worth carrying. Not
#: NEEDS_YOU: a form waiting on questions only he can answer has nothing to
#: pursue until he answers, and opening one for each of those made 240
#: opportunities out of one night's records (2026-09-22) - twelve hours of
#: her own model's time on situations that could not move.
LIVE_STATES = ("SUBMITTED", "AWAITING_YOU", "APPROVED", "SUBMITTING")
#: The application's state that means the opportunity waits on him.
HIS_TURN_STATES = ("NEEDS_YOU", "NEEDS_ACCOUNT")
#: ...and the states that mean it is over.
OVER_STATES = {"CLOSED": "dropped", "FAILED": "gone", "REJECTED": "declined"}
#: How many new opportunities one sync may open; the rest wait for the next.
OPEN_PER_SYNC = 5
RESUME_CHARS = 5_000
POSTING_CHARS = 6_000
#: Profile facts a note may stand on. The sensitive fields are his to say
#: (profile.NEVER_AUTOFILL) and never travel here.
PROFILE_FACTS = ("current_title", "current_employer", "school", "degree", "field_of_study",
                 "years_experience", "city", "state", "country")

#: What an employer's subject line says, in the sent ledger's own outcome
#: words, and what that is for the opportunity.
REPLY_OUTCOMES = {"wants_time": "conversation", "rejected": "declined", "noted": "replied"}
_DECLINE_WORDS = ("unfortunately", "not moving forward", "not be moving forward", "other candidates",
                  "not selected", "decided not to", "no longer under consideration", "regret to")


def _key(record: dict) -> str:
    return f"application:{record.get('url') or record.get('id')}"


def _name(record: dict) -> str:
    title = str(record.get("job_title") or record.get("page_title") or "the role").strip()
    company = str(record.get("company") or "").strip()
    return f"{title} at {company}" if company and company.casefold() not in title.casefold() else title


def _record_evidence(record: dict) -> str:
    fit = record.get("fit") or {}
    lines = [
        f"Application {record.get('id')} — state {record.get('state')}",
        f"Role: {record.get('job_title') or '?'}; employer: {record.get('company') or '?'}",
        f"Form: {record.get('url')}", f"Posting: {record.get('posting') or ''}",
        f"Found on: {record.get('found_on') or '?'}",
    ]
    for key in ("submitted_at", "staged_at"):
        if record.get(key):
            lines.append(f"{key.replace('_', ' ')}: {record[key]}")
    if fit.get("why"):
        lines.append(f"Her fit judgement: {fit['why']}")
    if record.get("why_she_liked_it"):
        lines.append(f"Why she liked it: {record['why_she_liked_it']}")
    if record.get("why_not"):
        lines.append(f"Reservation: {record['why_not']}")
    filled = record.get("filled") or []
    open_questions = record.get("not_filled") or record.get("questions") or []
    if filled:
        lines.append(f"Filled {len(filled)} fields on the form; "
                     f"{len(open_questions)} left as questions")
    # WHICH questions are open, not just how many: the first live pass
    # guessed that one blank field "could be disqualifying" and told him to
    # go and look, because the count was all it had.
    for q in open_questions[:12]:
        label = str(q.get("label") or q.get("selector") or "").strip()
        if label:
            lines.append(f"Open question on the form{' (required)' if q.get('required') else ''}: {label}")
    for row in record.get("outcomes") or []:
        lines.append(f"Outcome {row.get('outcome')}: {row.get('note', '')} ({row.get('at', '')[:10]})")
    return "\n".join(l for l in lines if l.strip())


def _same_employer(record: dict) -> str:
    from aletheia import apply_run
    company = str(record.get("company") or "").strip().casefold()
    if not company:
        return ""
    rows = []
    for other in apply_run.all_runs():
        if other.get("id") == record.get("id"):
            continue
        if str(other.get("company") or "").strip().casefold() != company:
            continue
        rows.append(f"{other.get('job_title') or '?'} — {other.get('state')}"
                    + (f", outcome {other['outcome']}" if other.get("outcome") else ""))
    return ("Other applications to the same employer:\n" + "\n".join(rows[:8])) if rows else ""


def _posting(record: dict) -> str:
    from aletheia import jobs
    job = {"posting_url": record.get("posting") or record.get("url"), "apply_url": record.get("url")}
    try:
        return str(jobs.posting_text(job) or "")[:POSTING_CHARS]
    except Exception:
        return ""


def _his_facts() -> str:
    from aletheia import profile
    try:
        known = profile.known()
    except Exception:
        return ""
    rows = [f"{k.replace('_', ' ')}: {known[k]}" for k in PROFILE_FACTS if known.get(k)]
    return ("About him (from his own answers):\n" + "\n".join(rows)) if rows else ""


def _resume() -> str:
    from aletheia import campaign
    try:
        _path, text = campaign.read_resume()
    except Exception:
        return ""
    return str(text or "")[:RESUME_CHARS]


def open_from_application(record: dict, *, now: dt.datetime | None = None,
                          posting=None, resume=None) -> dict:
    """The opportunity for one application record, opened with what she
    already knows. Idempotent: an existing one only gains newer evidence."""
    posting = posting or _posting
    resume = resume or _resume
    name = _name(record)
    opp = pursuit.open_opportunity(
        key=_key(record), name=name,
        objective=f"Get serious consideration for {name}",
        subject={"url": record.get("url", ""), "posting": record.get("posting", ""),
                 "application": record.get("id", ""), "organisation": record.get("company", "")},
        now=now)
    with pursuit._LOCK:
        opp = pursuit.load(opp["id"])
        pursuit.add_evidence(opp, "application", _record_evidence(record),
                             source=f"application {record.get('id')}", now=now)
        text = posting(record) if callable(posting) else str(posting)
        if text:
            pursuit.add_evidence(opp, "posting", text, source=record.get("posting") or record.get("url", ""),
                                 provenance=pursuit.UNTRUSTED, now=now)
        his = resume() if callable(resume) else str(resume)
        if his:
            pursuit.add_evidence(opp, "his background", his, source="his resume", now=now)
        facts = _his_facts()
        if facts:
            pursuit.add_evidence(opp, "his facts", facts, source="his profile", now=now)
        same = _same_employer(record)
        if same:
            pursuit.add_evidence(opp, "history with them", same, source="applications", now=now)
        pursuit.save(opp)
    return opp


def sync(*, now: dt.datetime | None = None, limit: int = OPEN_PER_SYNC) -> list[dict]:
    """Open an opportunity for every live application not yet carried, and
    let the application's own state reach the ones already open: a form
    that came back to him is parked until he answers, a closed or failed
    one is over."""
    from aletheia import apply_run
    now = pursuit._now(now)
    opened = []
    records = sorted(apply_run.all_runs(), key=lambda r: r.get("submitted_at") or r.get("staged_at") or "",
                     reverse=True)
    for record in records:
        if record.get("state") not in LIVE_STATES:
            continue
        if pursuit._path(pursuit.opportunity_id(_key(record))).exists():
            continue
        try:
            opened.append(open_from_application(record, now=now))
        except Exception as exc:
            journal.append("alert", "opportunity", f"could not open one for {record.get('id')}: "
                           f"{type(exc).__name__}: {exc}", actor=ACTOR)
        if len(opened) >= limit:
            break
    reconcile(records, now=now)
    return opened


def reconcile(records: list[dict], *, now: dt.datetime | None = None) -> list[str]:
    """The application's state, carried onto its opportunity. Returns what changed."""
    now = pursuit._now(now)
    by_key = {_key(r): r for r in records}
    changed = []
    for opp in pursuit.all_opportunities():
        if opp.get("state") == pursuit.CLOSED:
            continue
        record = by_key.get((opp.get("subject") or {}).get("key", ""))
        if not record:
            continue
        state = str(record.get("state") or "")
        if state in OVER_STATES:
            pursuit.record_outcome(opp["id"], OVER_STATES[state],
                                   note=f"the application is {state.lower()}", now=now)
            changed.append(opp["id"])
        elif state in HIS_TURN_STATES and opp.get("state") == pursuit.OPEN:
            with pursuit._LOCK:
                fresh = pursuit.load(opp["id"])
                fresh["state"] = pursuit.PARKED
                fresh["next_look"] = {"at": pursuit._stamp(now + dt.timedelta(days=30)),
                                      "because": "the form is waiting on questions only he can answer"}
                fresh["history"].append({"at": pursuit._stamp(now), "what": "parked: waiting on him"})
                pursuit.save(fresh)
            changed.append(opp["id"])
    return changed


def decline_words(subject: str) -> bool:
    low = " ".join(str(subject or "").split()).casefold()
    return any(word in low for word in _DECLINE_WORDS)


def heard_back(application_id: str, subject: str, outcome: str, *,
               now: dt.datetime | None = None) -> dict | None:
    """An employer wrote. Record it on the application AND hand it to the
    opportunity as evidence, so the next pass reasons with it."""
    from aletheia import apply_run
    if not application_id or outcome == "acknowledgement":
        return None
    try:
        record = apply_run.load_run(application_id)
    except Exception:
        return None
    if decline_words(subject):
        outcome = "rejected"
    marked = {"wants_time": "replied", "noted": "replied", "rejected": "rejected"}.get(outcome)
    if marked and marked not in {r.get("outcome") for r in record.get("outcomes") or []}:
        try:
            apply_run.mark(application_id, marked, note=subject[:140])
        except Exception:
            pass
    oid = pursuit.opportunity_id(_key(record))
    if not pursuit._path(oid).exists():
        open_from_application(record, now=now)
    opp = pursuit.observe(oid, "reply", f"They wrote: {subject}", source="his inbox", now=now)
    kind = REPLY_OUTCOMES.get(outcome)
    if kind:
        opp = pursuit.record_outcome(oid, kind, note=subject[:140], now=now)
    return opp


def _submit(record: dict, move: dict, now: dt.datetime) -> dict:
    """The `submit` door: stage the form through the existing path, whose
    approval rules (his yes, or a standing grant that his rulings bound)
    are untouched by this."""
    from aletheia import apply_run
    url = record["subject"].get("url", "")
    if not url:
        raise pursuit.PursuitError("no form to submit")
    if apply_run.was_sent(url):
        return {"state": "done", "effect": "already sent"}
    staged = apply_run.stage(url, note=move.get("why", ""), found_on="pursuit")
    return {"state": "waiting for his yes" if staged.get("state") == "AWAITING_YOU" else "done",
            "handle": staged.get("approval", ""),
            "effect": staged.get("say") or f"staged it: {staged.get('state')}"}


def register() -> None:
    pursuit.DOERS["submit"] = _submit


register()
