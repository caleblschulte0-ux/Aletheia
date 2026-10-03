"""The job hunt's door into `pursuit`: an application record becomes an
opportunity with its evidence, and what happens to it flows back.

This is the ONLY place the general pursuit knows a role, an employer or a
resume: here they are evidence and words, and `pursuit` itself carries
none of them (`tests/test_studies.py` checks). Nothing here decides what
to do about an opportunity - that is the reasoner's, per opportunity.
"""
from __future__ import annotations

import datetime as dt
import re

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
#: Days after a sent application with no word from them at which silence is
#: written down as evidence - so the reasoner DECIDES about a follow-up,
#: instead of a rule sending "follow-up #2". Two marks, each once.
SILENCE_DAYS = (8, 21)
#: Who the person finder looks for when the reasoner names nobody in particular.
PEOPLE_WORDS = ("talent", "recruit", "hiring", "people", "head of", "director", "founder", "vp", "chief")
#: Words in a role's title that are the role, not the department.
_TITLE_NOISE = frozenset("""manager lead senior junior associate specialist coordinator representative rep
    director head vp vice president chief officer analyst executive assistant intern staff principal of the
    and for at remote hybrid us usa""".split())
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
        # The case already made for him (`job_angle`): verbatim pairs of what
        # they ask and what he has, so the reasoner after the form starts
        # from it instead of finding it again. TRUSTED: every half was checked
        # against the posting and the resume in code.
        try:
            from aletheia import job_angle
            case = job_angle.evidence_text(record.get("angle"))
        except Exception:
            case = ""
        if case:
            pursuit.add_evidence(opp, "the case for him", case,
                                 source="her reading of the posting beside his resume", now=now)
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
        if _silence(opp, record, now=now):
            changed.append(opp["id"])
            continue
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


def _silence(opp: dict, record: dict, *, now: dt.datetime) -> bool:
    """Write "no word from them N days in" onto a sent application's
    opportunity, once per mark. True when something was written."""
    if str(record.get("state") or "") != "SUBMITTED" or record.get("outcome") or record.get("outcomes"):
        return False
    sent = pursuit._parse(str(record.get("submitted_at") or ""))
    if sent is None:
        return False
    days = (now - sent).days
    due = [n for n in SILENCE_DAYS if days >= n]
    if not due:
        return False
    top = max(due)
    noted = set()
    for row in opp.get("evidence") or []:
        if row.get("kind") != "silence":
            continue
        for n in SILENCE_DAYS:
            if f"{n} days" in str(row.get("text") or ""):
                noted.add(n)
    if top in noted or any(n > top for n in noted):
        return False
    pursuit.observe(opp["id"], "silence",
                    f"No word from them {top} days after the application went in "
                    f"({str(record.get('submitted_at'))[:10]}).",
                    source="his inbox", provenance=pursuit.TRUSTED, now=now)
    return True


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
    if kind == "conversation":
        # The brief: "If Caleb gets an interview: the objective changes from
        # getting noticed to maximizing interview performance."
        name = _name(record)
        opp = pursuit.set_objective(
            oid, f"Do well in the conversation with {record.get('company') or 'them'} about {name}: "
                 "understand what they do and what the role needs, prepare him for it, and keep the thread warm",
            because=f"they wrote: {subject[:80]}", now=now)
    return opp


def _title_words(name: str) -> list[str]:
    """The department words of a role's title: "Partnerships Manager" -> partnerships."""
    return [w for w in re.findall(r"[a-z]+", str(name or "").casefold()) if w not in _TITLE_NOISE and len(w) > 2]


def _find_people(record: dict, who: str) -> list[dict]:
    """The person finder, pointed at this opportunity's organisation: the
    posting and what she has read, the organisation's own site, a search."""
    from aletheia import employers, people_finder, research
    subject = record.get("subject") or {}
    company = str(subject.get("organisation") or "")
    domain = employers.domain_of(str(subject.get("posting") or subject.get("url") or ""))
    if not domain and company:
        try:
            about = employers.about(company) or {}
        except Exception:
            about = {}
        domain = next((d for d in (about.get("domains") or []) if d), "") or str(about.get("domain") or "")
    words = _title_words(who) + _title_words(subject.get("name", "")) + list(PEOPLE_WORDS)
    seen, title_words = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            title_words.append(w)
    texts = [(f"{e.get('kind')} ({e.get('source') or '?'})", e.get("text", ""))
             for e in record.get("evidence") or [] if e.get("kind") in ("posting", "looked")]
    return people_finder.find_at(company, domain=domain, title_words=title_words, texts=texts,
                                 search=research.http_search)


def _find_person(record: dict, move: dict, now: dt.datetime) -> dict:
    """The `find_person` door: people land on the record and as evidence, so
    the next pass can write to somebody by name. Nothing is sent."""
    from aletheia import people_finder
    who = str((move.get("detail") or {}).get("who") or "")
    people = _find_people(record, who)
    if not people:
        return {"state": "done", "effect": "looked for a person to write to and found nobody by name"}
    held = {(p.get("name") or p.get("email") or "").casefold() for p in record.get("people") or []}
    new = [p for p in people if (p.get("name") or p.get("email") or "").casefold() not in held]
    record.setdefault("people", []).extend(new)
    eid = pursuit.add_evidence(record, "people", people_finder.said(people),
                               source="what the organisation publishes", provenance=pursuit.UNTRUSTED, now=now)
    named = [p for p in people if p.get("name")]
    said = ", ".join(f"{p['name']} ({p.get('title') or '?'})" + (" with an address" if p.get("email") else "")
                     for p in named[:3]) or f"a shared inbox: {people[0].get('email')}"
    return {"state": "done", "evidence": eid, "effect": f"found {said}", "people": new}


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
    pursuit.DOERS["find_person"] = _find_person


register()
