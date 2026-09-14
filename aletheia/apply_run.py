"""Everything between "apply to this job" and one confirm.

His words, and they are the whole specification: *"If all this is is, it
comes to me and it says confirm you wanna apply to this job, that's fine.
That should be the goal. It needs to be able to handle every step in
between that could ever possibly exist."*

So the shape is: she opens the application, fills in everything she can
answer, attaches his resume, takes a picture of the filled form, and
brings him ONE decision with the whole thing visible. He says yes, and it
presses submit.

WHAT MAKES THAT SAFE RATHER THAN RECKLESS — three things, and they are
not negotiable.

**She never invents an answer.** `aletheia.formfill` splits every form
into what she knows and what she does not, and the second list comes back
to him. Anything protected or legal — self-identification, felony
questions, certifications — is his even when the profile holds something
that would fit. A staged application with an unanswered REQUIRED question
is refused outright: it would be submitted incomplete, or worse, submitted
with a blank where a "no" was expected.

**What he approves is exactly what is typed.** The approval carries a
sha256 of the page and the precise step list, and `browse.interact`
re-checks that binding itself — an approval for one plan cannot be spent
on another. He sees every field and every value before deciding, plus a
screenshot of the actual filled page.

**Submitting is a separate call with a separate consumption.** The
approval is spent once. A second submit of the same application finds it
already used and refuses, because the failure mode of a retry loop here
is five copies of his application in someone's inbox.

WHAT THIS DOES NOT YET HANDLE, said plainly rather than discovered:
account creation and logins (he signs in once himself, through
`browse.login`, and the session is reused), CAPTCHAs, and multi-page
wizards — for those it reports where it stopped instead of clicking
hopefully. Each of those is its own slice.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from aletheia import browse, formfill, journal, policy, profile, speech, stateio

ACTOR = "aletheia-apply"

MAX_QUESTIONS_SHOWN = 12
# Words on the one button that finishes an application. Matched against
# the visible text of buttons on the page, most specific first.
SUBMIT_WORDS = ("submit application", "submit your application", "apply now",
                "submit", "send application", "finish", "apply")
# The words live in `browse` now, with their refusal counterparts. Kept
# here as a name because tests and readers reach for it.
CONFIRMED_WORDS = browse.CONFIRMED_WORDS


class ApplyError(RuntimeError):
    pass


def staged_dir():
    return stateio.private_dir("applications")


#: What a browser says when a required box is empty. Never a question.
_BROWSER_COMPLAINTS = frozenset({
    "please fill out this field.", "please fill out this field",
    "please select an item in the list.", "please select an item in the list",
    "this field is required.", "this field is required",
    "please check this box if you want to proceed.",
    "please enter a valid email address.", "please tick this box to proceed.",
})


def sent_path():
    """Every url an application has actually gone to. Never rewritten by a re-stage.

    In its OWN directory, not beside the records: `all_runs()` reads every
    *.json in the applications directory as an application, so the ledger
    living there made every listing raise KeyError('state') — including the
    one she answers "what have I applied to?" from.
    """
    return stateio.private_dir("applications-sent") / "already-sent.json"


def _legacy_sent_path():
    """Where the ledger lived before f2465aed moved it (2026-09-12 19:41 CDT)."""
    return staged_dir() / "already-sent.json"


#: A record in either of these states went to the employer, or may have:
#: SUBMITTING is a press whose answer was never recorded (live 2026-09-13
#: Amtech and Carta hung there when the machine was restarted).
PRESSED_STATES = ("SUBMITTED", "SUBMITTING")


def already_sent() -> dict:
    """Every url an application went to, from EVERY place that says so.

    Live 2026-09-12 the ledger moved to its own directory at 00:41:50Z and
    the file that already held twenty sends stayed behind. Thirty-nine
    seconds later a campaign re-staged Stripe's "Account Executive, AI
    Sales" — sent at 19:11Z — found the new ledger empty, and pressed
    Submit on a second copy. Chrome crashing is the only reason Stripe did
    not receive it. So both files are read, and so is every record that
    already pressed the button: a move of the ledger can never again make
    her forget what she sent.
    """
    merged: dict = {}
    for path in (_legacy_sent_path(), sent_path()):
        try:
            value = stateio.read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            merged.update(value)
    # A form the site HANDED BACK is not in an employer's inbox. Live
    # 2026-09-13 Datadog's "GTM Operations Associate" page refused the
    # application and it was written into this ledger all the same, so it
    # counted as sent and could never be tried again. "Submitted,
    # unconfirmed" stays in: a second copy is the one outcome to avoid.
    merged = {url: entry for url, entry in merged.items()
              if str((entry or {}).get("verdict") or "").casefold() != "rejected"}
    try:
        records = all_runs()
    except Exception:
        records = []
    for record in records:
        url = str(record.get("url") or "").strip()
        if url and url not in merged and record.get("state") in PRESSED_STATES:
            merged[url] = {"id": record.get("id"), "at": record.get("submitted_at"),
                           "job_title": record.get("job_title", ""),
                           "company": record.get("company", ""),
                           "verdict": ((record.get("result") or {}).get("verdict")
                                       or "pressed, no answer recorded")}
    return merged


def was_sent(url: str) -> dict | None:
    """What is already in an employer's inbox for this url, if anything.

    THE RECORD CANNOT BE ITS OWN EVIDENCE. Live 2026-09-12: a campaign
    re-staged jobs that had already been submitted — `stage()` keys a
    record by a hash of the url and rebuilds it in place — so three
    applications the employers had already confirmed by email came back as
    fresh AWAITING_YOU records. `submit()`'s "already submitted" guard
    reads the record it just overwrote, so it would have sent a SECOND
    copy of his application to Stripe, Databricks and Samsara. The only
    thing that cannot be clobbered by a re-stage is a separate ledger.
    """
    return already_sent().get(str(url or "").strip()) or None


def _role_key(company: str, job_title: str) -> str:
    """One company and one role title, reduced to a comparable string.

    The stored title carries the employer on the end ("Business Development
    Representative — Databricks"), so that comes off before anything is
    compared, and everything that is not a letter or a digit goes with it.
    """
    company = " ".join(str(company or "").split())
    title = " ".join(str(job_title or "").split())
    if company:
        title = re.sub(r"\s*[—–\-|]\s*" + re.escape(company) + r"\s*$", "",
                       title, flags=re.I)
    title = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    return f"{company.casefold()}|{title}"


def was_applied_to_role(company: str, job_title: str) -> dict | None:
    """The same job at the same employer, under a DIFFERENT url.

    `was_sent` keys on the application url, which is exactly right and was
    not enough. Live 2026-09-13 two applications went to Databricks for
    "Business Development Representative" — gh_jid 8423165002 and
    8423167002, adjacent ids, one role posted to two locations. Two
    different urls, so the ledger held two honest entries and the guard had
    nothing to object to. An employer opening both sees one person applying
    twice for one job.

    Deliberately narrow: the SAME employer and the SAME title, after
    normalising. Databricks BDR and Databricks "Frontier AI Lab Account
    Executive" are two real jobs and both should go. So are Stripe's two
    and GitLab's two, which is why this compares titles rather than
    counting applications per company.
    """
    if not str(company or "").strip() or not str(job_title or "").strip():
        return None                      # nothing to compare is not a match
    want = _role_key(company, job_title)
    for entry in already_sent().values():
        if _role_key(entry.get("company", ""), entry.get("job_title", "")) == want:
            return entry
    return None


role_key = _role_key


def role_taken(company: str, job_title: str, url: str = "") -> dict | None:
    """The same job at the same employer, already sent OR already waiting.

    `was_applied_to_role` only reads what went, and only at the moment of
    sending — so a role posted to three locations was STAGED three times
    and asked him the same questions three times (Brex "People Business
    Partner, GTM", 2026-09-13 04:29Z, 04:34Z, 04:46Z), and a role already
    sent under one link was filled in again under another eighteen minutes
    later (Impact.com "Business Development Representative, Inbound").
    The same form at the same url is not a duplicate: that is a re-stage.
    """
    if not str(company or "").strip() or not str(job_title or "").strip():
        return None
    sent = was_applied_to_role(company, job_title)
    if sent:
        return {**sent, "state": "SUBMITTED"}
    want = _role_key(company, job_title)
    here = str(url or "").strip()
    for record in all_runs():
        if record.get("state") in (CLOSED, "FAILED"):
            continue
        if here and str(record.get("url") or "").strip() == here:
            continue
        if _role_key(record.get("company", ""), record.get("job_title", "")) == want:
            return {"id": record.get("id"), "at": record.get("staged_at"),
                    "state": record.get("state"), "url": record.get("url")}
    return None


def remember_sent(record: dict) -> None:
    """Write the url down the moment it really goes, and never forget it."""
    url = str(record.get("url") or "").strip()
    if not url:
        return
    ledger = already_sent()
    ledger[url] = {"id": record.get("id"), "at": record.get("submitted_at"),
                   "job_title": record.get("job_title", ""),
                   "company": record.get("company", ""),
                   "verdict": (record.get("result") or {}).get("verdict", "")}
    stateio.write_json_atomic(sent_path(), ledger)


def _record_path(run_id: str):
    return staged_dir() / f"{stateio.safe_id(run_id, name='application id')}.json"


def load_run(run_id: str) -> dict:
    return stateio.read_json(_record_path(run_id))


def all_runs(state: str | None = None) -> list[dict]:
    out = []
    directory = staged_dir()
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            value = stateio.read_json(path)
        except (OSError, ValueError):
            continue
        # The old sent ledger still sits in this directory on his PC, and it
        # is a map of urls, not an application.
        if not isinstance(value, dict) or "state" not in value:
            continue
        if state is None or value.get("state") == state:
            out.append(value)
    return out


#: An application she decided not to send — a duplicate, or a job that is
#: not realistic for him — with the reason on the record.
CLOSED = "CLOSED"
#: The button was pressed and the site handed the form back. Not sent, not
#: counted, and not pressed again with the same answers.
REJECTED = "REJECTED"


def _by_grant(approval: dict) -> bool:
    """Whether an approval was decided by his standing grant rather than by him."""
    via = str((approval or {}).get("decided_via") or "")
    return via.startswith("grant:") or via == "standing-grant"


#: What `waits_for_his_ok` answers for a job only her own model said was
#: realistic.
JUDGED_LOCALLY = "judged-locally"


def waits_for_his_ok(record: dict) -> str:
    """The kind of job this is when only HIS OWN yes may send it, else "".

    Part-time, contract, temporary, seasonal and internship work: he has not
    said whether he wants it, so the standing grant never decides it for him.
    ONE predicate for every place the grant is spent. Live 2026-09-13 the
    check lived only in the Core's beat, for approvals not yet decided - but
    `stage` spends the grant the moment a form is filled, so Bluevine's
    "People Coordinator & Office Operations Associate (part-time)" arrived at
    the beat already APPROVED and was sent without him ever seeing it.

    And a job only her OWN model judged realistic (`JUDGED_LOCALLY`): since
    2026-09-13 the hunt keeps going when Claude and Codex are both out, and
    the smaller model's yes is a reason to show him the job, not to send it.
    """
    from aletheia import job_fit
    kind = str(record.get("employment") or "")
    if not kind:
        named = " ".join(str(record.get(k) or "") for k in ("job_title", "page_title", "note"))
        kind = job_fit.employment_type(named)
    if not kind and job_fit.judged_locally(record.get("fit")):
        kind = JUDGED_LOCALLY
    if not kind:
        return ""
    try:
        approval = policy.load(record.get("approval") or "") if record.get("approval") else {}
    except Exception:
        approval = {}
    if approval.get("state") == "APPROVED" and not _by_grant(approval):
        return ""                        # he said yes to this one himself
    return kind


def his_ok_notice(record: dict, kind: str) -> tuple[str, str, str]:
    """(title, body, dedupe key) telling him why a job waits for his own OK.

    One notice per application PER REASON: a part-time job that her own model
    alone judged is two things he should know, and a key shared by both kept
    whichever was said first.
    """
    if kind == JUDGED_LOCALLY:
        return ("A job my own model picked is waiting for your OK",
                f"{describe(record)} - Claude and Codex were both out, so only my own model "
                "read the posting and said it is realistic. It was not sent on the standing "
                "grant. Approve it if you want it."[:400],
                f"apply-judged-locally:{record.get('id')}")
    return (f"A {kind} job is waiting for your OK",
            f"{describe(record)} - it is {kind}, so it was not sent on "
            "the standing grant. Approve it if you want it."[:400],
            f"apply-not-full-time:{record.get('id')}")


def close(run_id: str, why: str, *, via: str = "aletheia") -> dict:
    """Retire a waiting application without applying, and say why.

    Never one that already went: that is a fact about an employer's inbox,
    and closing the record would only hide it.
    """
    record = load_run(run_id)
    if record.get("state") in PRESSED_STATES:
        raise ApplyError(f"{run_id} already went to the employer; it cannot be closed")
    if record.get("state") == CLOSED:
        return record
    reason = " ".join(str(why or "").split())[:300]
    record.update({"state": CLOSED, "closed_at": stateio.utcnow(),
                   "closed_because": reason, "closed_by": via})
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("decision", "apply",
                   f"closed {run_id} without applying ({describe(record)}): {reason}",
                   actor=ACTOR)
    return record


#: A closure for being a DUPLICATE, told apart from one for being UNFIT by
#: its reason. A duplicate never reopens; an unfit one may, when he has said
#: what work he wants since.
_DUPLICATE_REASON = re.compile(r"same job|already went|already (?:applied|waiting|sent)|duplicate",
                               re.I)


def closure_kind(record: dict) -> str:
    """'duplicate' or 'unfit', for a CLOSED record."""
    kind = str(record.get("closed_kind") or "")
    if kind:
        return kind
    return ("duplicate" if _DUPLICATE_REASON.search(str(record.get("closed_because") or ""))
            else "unfit")


def closed_unfit(company: str, job_title: str, url: str = "") -> dict | None:
    """A CLOSED-as-unfit application for this form or this role, if there is one.

    `role_taken` deliberately does not count closed records: a closure says
    nothing about a DIFFERENT job. This is the other question — was THIS job
    already judged and closed — and it had no answer, so on 2026-09-13 two
    jobs closed at 15:40Z were found again, rebuilt at the same url and sent
    within the hour (Dutchie "Account Manager, SMB", impact.com "Creator
    Solutions Account Manager"). Company compared case-insensitively.
    """
    here = str(url or "").strip()
    want = (_role_key(company, job_title)
            if str(company or "").strip() and str(job_title or "").strip() else "")
    for record in all_runs(CLOSED):
        if closure_kind(record) != "unfit":
            continue
        if here and str(record.get("url") or "").strip() == here:
            return record
        if want and _role_key(record.get("company", ""), record.get("job_title", "")) == want:
            return record
    return None


def reopen(run_id: str, why: str) -> dict:
    """Bring a closed application back, on purpose and with the reason kept."""
    record = load_run(run_id)
    if record.get("state") != CLOSED:
        return record
    reason = " ".join(str(why or "").split())[:300]
    record.update({"state": "NEEDS_YOU", "reopened_at": stateio.utcnow(),
                   "reopened_because": reason,
                   "closed_before": record.get("closed_because", "")})
    for key in ("closed_at", "closed_because", "closed_by", "closed_kind"):
        record.pop(key, None)
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("decision", "apply",
                   f"reopened {run_id} ({describe(record)}): {reason}", actor=ACTOR)
    return record


def _close_quietly(run_id: str, why: str) -> None:
    try:
        close(run_id, why)
    except Exception:
        pass


# What the record keeps about the JOB, beside what it keeps about the form.
REMEMBERED = ("job_title", "company", "posting", "found_on", "answered_for_you", "fit",
              "employment")
# What an employer did about an application he sent, in his words. "No
# answer yet" is not one: that is the absence of an outcome, not an outcome.
OUTCOMES = ("replied", "interview", "offer", "rejected", "closed")


def remember(run_id: str, **fields) -> dict:
    """Keep what the campaign knows about the JOB on the saved record.

    Found 2026-09-11: the campaign set job_title, posting and found_on on
    the record it was holding and never wrote them back, so every saved
    application knew the form's URL and nothing about the job — "what have
    I applied to" could only read back a page title. Only these fields, and
    never over a state, an approval or a timestamp.
    """
    record = load_run(run_id)
    for name, value in fields.items():
        if name not in REMEMBERED:
            raise ApplyError(f"an application record does not keep {name!r}")
        if value not in (None, ""):
            record[name] = value
    stateio.write_json_atomic(_record_path(run_id), record)
    return record


def mark(run_id: str, outcome: str, *, note: str = "", when: str = "") -> dict:
    """Record what the employer did about an application, keeping the history."""
    key = " ".join(str(outcome or "").casefold().split())
    if key not in OUTCOMES:
        raise ApplyError(f"{outcome!r} is not one of: {', '.join(OUTCOMES)}")
    record = load_run(run_id)
    entry = {"outcome": key, "note": " ".join(str(note or "").split())[:300],
             "at": when or stateio.utcnow()}
    record.setdefault("outcomes", []).append(entry)
    record["outcome"] = key
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("note", "apply",
                   f"{run_id}: {key}" + (f" — {entry['note']}" if entry["note"] else ""),
                   actor=ACTOR)
    return record


def describe(record: dict) -> str:
    """One application, the way he would name it: the job, then the employer."""
    title = " ".join(str(record.get("job_title") or "").split())
    company = " ".join(str(record.get("company") or "").split())
    if title and company and company.casefold() not in title.casefold():
        named = f"{title} at {company}"
    else:
        named = (title or company
                 or " ".join(str(record.get("page_title") or "").split())
                 or str(record.get("url") or record.get("id") or "an application"))
    # A part-time, contract or temporary job says so wherever it is named.
    from aletheia import job_fit
    kind = str(record.get("employment") or "") or job_fit.employment_type(title)
    if kind and kind.casefold() not in named.casefold():
        named = f"{named} ({kind})"
    return named


def find(which: str) -> list[dict]:
    """The applications he means by a few words: an employer, a job, an id."""
    key = " ".join(str(which or "").casefold().split())
    if not key:
        return []
    rows = all_runs()
    exact = [r for r in rows if key == str(r.get("id") or "").casefold()]
    if exact:
        return exact
    return [r for r in rows
            if key in " ".join((describe(r), str(r.get("url") or ""))).casefold()]


def _submit_selector(buttons: list[dict]) -> str | None:
    """The one button that finishes it, by what it SAYS.

    Most specific phrase first: a page with both "Save" and "Submit
    application" must not match "apply" on a nav link first.
    """
    for word in SUBMIT_WORDS:
        for button in buttons:
            text = (button.get("text") or "").strip().casefold()
            if text == word:
                return button["selector"]
    for word in SUBMIT_WORDS:
        for button in buttons:
            if word in (button.get("text") or "").strip().casefold():
                return button["selector"]
    return None


BUTTONS_JS = r"""() => {
  const out = [];
  const sel = (el) => el.id ? `#${CSS.escape(el.id)}`
    : (el.name ? `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]` : null);
  for (const el of document.querySelectorAll(
      'button, input[type=submit], [role=button]')) {
    const selector = sel(el) || (el.type === 'submit'
      ? `${el.tagName.toLowerCase()}[type="submit"]` : null);
    if (!selector) continue;
    out.push({selector, text: (el.innerText || el.value || '').trim().slice(0, 80)});
  }
  return out;
}"""


def _tag(url: str) -> str:
    """A short, stable mark for one application, so re-staging the same form
    after he answers its questions REPLACES it rather than leaving a second
    copy waiting for the same confirmation."""
    import hashlib
    return hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:8]


def _same_question(a: str, b: str) -> bool:
    """The page's complaint and the form's label, as one question.

    The page reads the label off the block above a dropdown and cuts it at 90
    characters; the reader has the whole of it."""
    x, y = formfill._norm(a).rstrip(" *"), formfill._norm(b).rstrip(" *")
    if not x or not y:
        return False
    short = min(len(x), len(y), 60)
    return x[:short] == y[:short]


def _unpicked(fill: list[dict], chosen: dict, fields: list[dict],
              stopped: list[dict]) -> tuple[list[dict], list[dict]]:
    """Dropdowns she meant to answer and could not, as QUESTIONS WITH A SELECTOR.

    Live 2026-09-13 this was the single largest reason applications stopped:
    seventeen of them. She planned "SD" for Tebra's State dropdown, "Hartford"
    for Datadog's "In what cities are you available to work?", "Yes" for
    Vercel's authorization list — no option plainly said that, `pick_option`
    rightly chose nothing, and `_as_chosen` rightly left it off the
    confirmation. And then nothing else knew. The page's own complaint came
    back as "Please fill out this field." with no selector and no options, so
    the model answering from his facts could not be shown it, and his own
    answer, had he given one, had nowhere to land. Every one of them sat
    waiting on him for good.

    Returns (questions, the page's complaints that are not these questions).
    """
    by_selector = {f.get("selector"): f for f in fields}
    missed = []
    for row in fill:
        selector = row.get("selector")
        if selector not in chosen or chosen[selector]:
            continue
        field = by_selector.get(selector, {})
        # THE PAGE'S VERDICT decides, as everywhere else here: a dropdown left
        # empty that the page does not complain about is not stopping anything,
        # and it is simply not listed as filled.
        if not any(_same_question(s.get("label", ""), row.get("label", "")) for s in stopped):
            continue
        question = {"selector": selector, "label": row.get("label", ""),
                    "required": True, "type": field.get("type") or "text",
                    "why": (f"none of its options plainly says {row.get('value')!r}"
                            if row.get("value") not in (None, "") else
                            "none of its options is plainly the answer")}
        choices = _choices_of(field)
        if choices:
            question["choices"] = choices
        missed.append(question)
    rest = [s for s in stopped
            if not any(_same_question(s.get("label", ""), m["label"]) for m in missed)]
    # A complaint with no selector may still name a field that was read: give
    # it that field's selector and options, so it can be answered at all.
    for item in rest:
        if item.get("selector"):
            continue
        field = next((f for f in fields
                      if f.get("selector") and _same_question(item.get("label", ""),
                                                              f.get("label", ""))), None)
        if field is not None:
            item["selector"] = field["selector"]
            item.setdefault("type", field.get("type") or "text")
            choices = _choices_of(field)
            if choices and not item.get("choices"):
                item["choices"] = choices
    return missed, rest


def _choices_of(field: dict) -> list[str]:
    """A field's options as a question carries them: a typeahead's menu or a
    <select>'s own list, bounded without losing his answer or "Other".

    A question built from a <select> carried no options at all, because they
    live under `options`, not `choices` - so neither a model nor his own
    answer had anything to pick from."""
    offered = formfill.option_texts(field)
    if len(offered) <= formfill.MAX_CHOICES_KEPT:
        return offered
    try:
        known = profile.known()
    except Exception:
        known = {}
    return formfill.bounded_choices(offered, known=known)


def stage(url: str, *, resume: str = "", note: str = "", extra: dict | None = None,
          reader=None, filler=None, found_on: str = "") -> dict:
    """Fill the application and bring him one decision. Submits nothing.

    `extra` is his answers to the things she could not know — they are
    applied for this application and, when they name a profile field,
    remembered so he is never asked twice.
    """
    policy.ensure_not_halted()
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://", "file://")):
        raise ApplyError("that is not a page address")

    # His answers to last round's questions go in FIRST, so the plan sees
    # them. Two kinds, because the questions are of two kinds:
    #   "phone": "..."   a fact about him — remembered, never asked again
    #   "#felony": "No"  an answer to THIS form — used here and not stored
    # The second is deliberate. "Have you been convicted of a felony" is a
    # question he answers, not a fact she files away and reuses on a form
    # that may be asking something subtly different.
    # And they ACCUMULATE. Found live 2026-09-11: a form asking him two
    # things could never be finished, because each answer re-staged with
    # only itself — his "yes" to the certification was on the record, then
    # his LinkedIn re-staged without it and the form was blocked on the
    # certification again, forever. Every answer he has given this form is
    # applied to every re-stage of it.
    run_id = f"apply-{_tag(url)}"
    # A job he has already applied to is not a job to fill in again. The
    # campaign re-staged three of them on 2026-09-12 and turned confirmed
    # applications back into fresh ones waiting to be sent.
    gone = was_sent(url)
    if gone:
        raise ApplyError(
            f"an application already went to {url} at {gone.get('at')} "
            f"({gone.get('job_title') or 'that job'}) — not applying twice")
    try:
        before = load_run(run_id)
    except (OSError, ValueError, KeyError):
        before = {}
    # A closed application is not rebuilt by filling its form again. `stage`
    # keys a record by its url, so a batch that found a closed job again
    # overwrote the closure with a fresh record and sent it (Dutchie and
    # impact.com, 2026-09-13). Reopening is a decision: `reopen` makes it.
    if before.get("state") == CLOSED:
        raise ApplyError(
            f"{run_id} was closed without applying "
            f"({before.get('closed_because') or 'no reason kept'}) - it is reopened on "
            "purpose or not at all")
    per_form = dict(before.get("answers_given") or {})
    # What the JOB is survives a re-stage too. Staging rebuilds the record
    # from the form, so answering a question threw away the job title, the
    # employer and the posting the campaign had attached — and the tracker
    # was left naming the application after the form's page title.
    kept_job = {name: before[name] for name in REMEMBERED if before.get(name)}
    for field, value in (extra or {}).items():
        if field in profile.FIELDS:
            profile.set_answer(field, value, source="operator")
        else:
            per_form[str(field)] = value

    fields = formfill.read_form(url, reader=reader)
    # The BROWSER's complaint is not a question she failed to answer. Live
    # 2026-09-12 Datadog's record listed two blockers reading "Please fill
    # out this field." with no type — the page's own validation text, caught
    # after a submit — and one of them was a question she already had an
    # answer for on file. Stale validation kept applications blocked that
    # nothing was actually wrong with.
    fields = [f for f in fields
              if " ".join(str(f.get("label") or "").split()).casefold()
              not in _BROWSER_COMPLAINTS]
    # HIS ANSWERS GO IN WITH THE FACTS, not one line later. `plan` decides
    # what she fills on her own initiative, and it has to know which fields
    # he has already spoken about: since 2026-09-12 it ticks routine
    # paperwork by default, and with only the profile in hand it happily
    # ticked a certification he had explicitly answered "no" to. An answer
    # he gave outranks anything she would do by default - the same rule as
    # the ChatGPT lease, learned the same day. Profile facts are keyed by
    # field name and his answers by selector, so they cannot collide.
    # AN ACCOUNT WALL IS NOT AN APPLICATION. `formfill` drops password
    # inputs (SKIP_TYPES), which is right for a real application and means
    # a Workday login page reads as a form whose only real inputs vanish —
    # so it staged a record with nothing in it that could never be
    # submitted. Named now, with the host, so the account can be made
    # instead of the application being pretended.
    from aletheia import signup as _signup
    if _signup.is_signup_form(fields):
        host = urllib.parse.urlparse(url).netloc
        decision = _signup.prepare(fields, host=host)
        record = {"id": run_id, "state": "NEEDS_ACCOUNT", "url": url,
                  "host": host, "signup": decision.get("state"),
                  "why": decision.get("why") or
                         "this page wants an account before it will take an "
                         "application",
                  "not_filled": [], "skipped": [], "filled": [],
                  "staged_at": stateio.utcnow(), **kept_job}
        stateio.write_json_atomic(_record_path(run_id), record)
        journal.append("action", "apply",
                       f"{url} wants an account before it will take an "
                       f"application ({decision.get('state')})", actor=ACTOR)
        return record

    # A LIST TO JOIN IS NOT AN APPLICATION. Live 2026-09-13 Spectrum's posting
    # page - "Sign up for job alerts": names, Email, Confirm Email, a job
    # category, a location, an optional resume - was staged as the application
    # for "National Account Manager, Federal Government" and waited on him for
    # "Spectrum employee". Pressed, it would have put him on a mailing list
    # under that job's name. Same predicate as the campaign's form check.
    if formfill.is_signup_list(fields):
        failure = "a talent-network / job-alert signup, not an application"
        record = {"id": run_id, "state": "FAILED", "url": url, "failure": failure,
                  "approval": "", "steps": [], "filled": [], "not_filled": [],
                  "skipped": [], "resume": resume,
                  "staged_at": stateio.utcnow(), **kept_job}
        stateio.write_json_atomic(_record_path(run_id), record)
        journal.append("action", "apply", f"{url} is a job-alert signup, not an "
                       "application - not staged", actor=ACTOR)
        raise ApplyError(f"{run_id}: {failure}")

    plan = formfill.plan(fields, answers={**profile.known(), **per_form},
                         found_on=found_on or before.get("found_on") or "")
    answered = formfill.apply_answers(plan, fields, per_form)
    steps = formfill.steps(plan["fill"]) + answered["steps"]

    # NOTHING TO FILL IS NOT AN APPLICATION. Live 2026-09-13 Bond's posting had
    # been taken down - Greenhouse answered "Sorry, but we can't find that page" -
    # and Grainger's address was cut short onto a page with no form. Both were
    # staged with no field filled and nothing asked, approved on the grant, and
    # pressed, failing at send time with "could not find the button". A page
    # that offers nothing to type and asks nothing is recorded as not a form.
    if not plan["fill"] and not plan["ask"] and not answered["steps"]:
        failure = ("there is no application form on this page to fill - the posting "
                   "may have been taken down or the link was wrong")
        record = {"id": run_id, "state": "FAILED", "url": url, "failure": failure,
                  "approval": "", "steps": [], "filled": [], "not_filled": [],
                  "skipped": plan["skipped"], "resume": resume,
                  "staged_at": stateio.utcnow(), **kept_job}
        stateio.write_json_atomic(_record_path(run_id), record)
        journal.append("action", "apply", f"{url} has no application form to fill - "
                       "not staged", actor=ACTOR)
        raise ApplyError(f"{run_id}: {failure}")

    blocking = [a for a in plan["ask"] if a["required"]]
    if blocking:
        # Refused, not "filled as far as possible": a form submitted with a
        # blank where a "no" was expected is worse than one not submitted.
        #
        # SAVED, though, and that was the bug. The first version returned
        # this and wrote nothing, so ten applications each waiting on the
        # same three questions left no trace to collect the questions from
        # — "apply to ten jobs" asked him nothing and produced nothing. A
        # blocked application is a real thing that is waiting.
        record = {"id": run_id, "state": "NEEDS_YOU", "url": url,
                  "approval": "", "steps": [], "resume": resume,
                  "questions": plan["ask"][:MAX_QUESTIONS_SHOWN],
                  "not_filled": plan["ask"][:MAX_QUESTIONS_SHOWN],
                  "would_fill": [{"label": f["label"], "value": f["value"]}
                                 for f in plan["fill"]],
                  "filled": [], "skipped": plan["skipped"],
                  "answers_given": per_form, **kept_job,
                  "staged_at": stateio.utcnow(),
                  "say": (f"{speech.count_phrase(len(blocking), 'thing')} on that form only you can "
                          "answer. Tell me those and I will fill the rest and "
                          "bring it back to you to confirm.")}
        stateio.write_json_atomic(_record_path(run_id), record)
        return record

    shot = staged_dir() / f"{run_id}.png"
    filled = (filler or _fill_and_capture)(url, steps, resume, shot)

    # THE PAGE'S OWN VERDICT, not hers. Staging ended at "I typed
    # everything I could" and called that ready — so on a form whose
    # work-authorization question is a pair of divs, she produced an
    # application AWAITING HIS CONFIRMATION that the browser would then
    # refuse to send: he taps Approve, submit is pressed, nothing arrives,
    # and the run reports success. Found on a fixture built to look like
    # the forms an ATS actually serves.
    stopped = [item for item in (filled.get("blocking") or [])
               if item.get("label") not in {q.get("label") for q in plan["ask"]}]
    missed, stopped = _unpicked(plan["fill"], filled.get("chosen") or {}, fields, stopped)
    stopped = missed + stopped
    if stopped:
        record = {"id": run_id, "state": "NEEDS_YOU", "url": url,
                  "approval": "", "steps": steps, "resume": resume,
                  "questions": (plan["ask"] + stopped)[:MAX_QUESTIONS_SHOWN],
                  "not_filled": (plan["ask"] + stopped)[:MAX_QUESTIONS_SHOWN],
                  "would_fill": _as_chosen(plan["fill"], filled.get("chosen") or {}),
                  "filled": [], "skipped": plan["skipped"],
                  "answers_given": per_form, **kept_job,
                  "screenshot": str(shot) if shot.exists() else "",
                  "staged_at": stateio.utcnow(),
                  "say": ("I filled what I could, and the form still will not "
                          "go without: "
                          + "; ".join(i["label"] for i in stopped[:5])
                          + ". Tell me those and I will finish it.")}
        stateio.write_json_atomic(_record_path(run_id), record)
        journal.append("action", "apply",
                       f"held an application at {url} — the form will not go "
                       f"yet ({speech.count_phrase(len(stopped), 'thing')} outstanding)", actor=ACTOR)
        try:
            from aletheia import demand
            demand.record_attempt("application.submit", note or url,
                                  "NEEDS_YOU", source="apply")
        except Exception:
            pass
        return record

    # The same answers the site already refused are not pressed again. A
    # re-stage with something new goes back in line like any other.
    if before.get("state") == REJECTED and steps == list(before.get("steps") or []):
        raise ApplyError(
            f"{run_id}: the site refused this form with these same answers "
            f"({before.get('failure') or 'no reason kept'}) - not sending it again unchanged")

    action = browse.approval_action(url, steps)
    approval_id = f"{run_id}-submit"
    # Not on the grant when it is not full-time work: the approval waits for
    # him, and the beat tells him why.
    not_full_time = waits_for_his_ok({"note": note, "page_title": filled.get("title", ""),
                                      **kept_job})
    policy.request(
        approval_id, action,
        reason=(note or f"Submit an application at {url}"),
        consequence=("It sends your application to this employer under your "
                     "name. There is no undo."),
        reversible=False,
        capability=None if not_full_time else "application.submit")

    record = {"id": run_id, "state": "AWAITING_YOU", "url": url,
              "approval": approval_id, "steps": steps,
              "filled": (_as_chosen(plan["fill"] + answered["filled"],
                                    filled.get("chosen") or {})
                         + ([{"label": "Resume", "value": Path(resume).name}]
                            if filled.get("resume_attached") else [])),
              "not_filled": plan["ask"], "skipped": plan["skipped"],
              "resume": resume, "screenshot": str(shot) if shot.exists() else "",
              "page_title": filled.get("title", ""),
              "answers_given": per_form, **kept_job,
              "staged_at": stateio.utcnow()}
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("action", "apply",
                   f"staged an application at {url} — {speech.count_phrase(len(steps), 'field')} "
                   f"filled, awaiting his confirmation", actor=ACTOR)
    return record


def _as_chosen(rows: list[dict], chosen: dict) -> list[dict]:
    """What is ON the form, not what she meant to put there.

    A dropdown she typed "B.B.A." into chose "Bachelor's Degree", and the
    confirmation he approves said B.B.A. (live 2026-09-10). A dropdown that
    chose nothing is not listed as filled at all.
    """
    out = []
    for row in rows:
        selector = row.get("selector")
        value = row.get("value")
        if selector in chosen:
            if not chosen[selector]:
                continue
            value = chosen[selector]
        out.append({"label": row["label"], "value": value})
    return out


def _apply_steps(page, steps: list[dict]) -> dict:
    """One place that knows how to perform a step.

    Staging and submitting both type the same list, and they had their own
    copies of the loop — which is how two things that must be identical
    stop being identical. It also cost the first live run: a checkbox step
    carries no `value`, and `page.fill(selector, step["value"])` raised
    KeyError in the staging copy alone.
    """
    chosen: dict[str, str] = {}
    for step in steps:
        action = step["action"]
        if action == "select":
            page.select_option(step["selector"], step["value"])
        elif action == "click":
            page.click(step["selector"])       # a checkbox is ticked, not typed
        elif action == "press":
            page.keyboard.press(str(step["value"]))
        elif action == "wait_for":
            page.wait_for_selector(step["selector"])
        elif formfill.is_combobox(page, step["selector"]):
            # A search-as-you-type dropdown keeps nothing that is only typed.
            # The option is chosen, or it is left empty for him to answer.
            chosen[step["selector"]] = formfill.pick_option(
                page, step["selector"], step["value"])
        else:
            page.fill(step["selector"], str(step["value"]))
    return chosen


def _fill_and_capture(url: str, steps: list[dict], resume: str, shot: Path) -> dict:
    """Type it all in, photograph it, and say what would still stop it.

    Presses nothing — and, since 2026-09-04, does not pretend a form is
    ready when it is not: `formfill.blocking` asks the page itself.
    """
    ok, why = browse.available()
    if not ok:
        raise ApplyError(f"she cannot open the application: {why}")
    shot.parent.mkdir(parents=True, exist_ok=True)
    with browse._Session() as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        formfill.settle(page)
        chosen = _apply_steps(page, steps)
        landed = stuck = False
        if resume and _attach_resume(page, resume):
            # Wait for the page to TAKE the file before photographing it: live
            # on Flexport the picture he would approve showed an empty
            # progress bar under Resume/CV.
            landed = _resume_landed(page, resume)
            stuck = not landed
        page.screenshot(path=str(shot), full_page=True)
        blocking = formfill.blocking(page)
        if stuck:
            blocking.append({"label": "Resume/CV", "required": True,
                             "why": "the resume upload did not finish on the page"})
        result = {"title": page.title(), "url": page.url, "blocking": blocking,
                  "chosen": chosen, "resume_attached": landed}
        page.close()
    return result


UPLOAD_SETTLE_MS = 10_000
#: How much longer a page that is visibly still WORKING on the file gets.
UPLOAD_WORKING_MS = 20_000
UPLOADED_JS = r"""(name) => ((document.body && document.body.innerText) || '').includes(name)"""
# Lever never prints the file's name. It prints "Analyzing resume..." while
# it reads the file and then "Success!" - or "Couldn't auto-read resume.",
# which means its PARSER gave up, not that the file is missing: the file is in
# the form either way. Live 2026-09-13 both Nitra applications stopped on
# "the resume upload did not finish" with the resume sitting in the box.
#
# So: a file input that HOLDS a file, on a page showing nothing still at work
# (no progress bar, no "uploading", no "analyzing"). The Flexport lesson still
# holds - a visible progress bar is never read as done.
UPLOAD_SETTLED_JS = r"""() => {
  const held = [...document.querySelectorAll('input[type=file]')]
    .some(i => i.files && i.files.length > 0);
  if (!held) return 'empty';
  const seen = (el) => !!el && el.offsetParent !== null
    && (el.innerText || el.getAttribute('aria-valuenow') !== null);
  const busy = [...document.querySelectorAll(
      '[role=progressbar], progress, [class*="progress"], [class*="uploading"], '
      + '[class*="upload-working"], [class*="loading"]')]
    .some(el => seen(el) && !/complete|success|done/i.test(el.className || ''));
  const words = /\b(uploading|analyzing|analysing|processing file|please wait)\b/i
    .test((document.body && document.body.innerText) || '');
  return (busy || words) ? 'working' : 'held';
}"""


def _upload_state(page) -> str:
    """'held', 'working' or 'empty', across every frame."""
    best = "empty"
    for frame in formfill.frames(page):
        try:
            said = frame.evaluate(UPLOAD_SETTLED_JS)
        except Exception:
            continue
        if said == "held":
            return "held"
        if said == "working":
            best = "working"
    return best


def _resume_landed(page, resume: str, *, wait_ms: int | None = None) -> bool:
    """Has the page taken the file? An upload box shows the file's name once it has.

    Live on Flexport 2026-09-10 the picture he would have approved showed an
    empty progress bar under Resume/CV: it was taken the instant the file was
    handed over, and Submit was pressed just as fast.
    """
    name = Path(resume).name
    wait = getattr(page, "wait_for_timeout", None)
    budget = UPLOAD_SETTLE_MS if wait_ms is None else wait_ms
    for _ in range(max(1, budget // 500)):
        for frame in formfill.frames(page):
            try:
                if frame.evaluate(UPLOADED_JS, name):
                    return True
            except Exception:
                continue
        if wait is None:
            break
        wait(500)
    # No name on the page. A form that never prints one (Lever) has still
    # taken the file if the box holds it and nothing is still at work.
    extra = 0 if wait is None or wait_ms is not None else UPLOAD_WORKING_MS
    for _ in range(max(1, extra // 500)):
        state = _upload_state(page)
        if state == "held":
            return True
        if state == "empty" or wait is None or not extra:
            return False
        wait(500)
    return False


def _attach_resume(page, resume: str) -> bool:
    """Put his real resume in the upload box.

    This was on the "yours to do" list a commit ago, and it did not need
    to be: a file input takes a path, and the path is a file he already
    owns. It is still his document going to an employer, which is why it
    happens inside the same approval as everything else.
    """
    path = Path(resume).expanduser()
    if not path.is_file():
        return False
    for row in page.evaluate(formfill.READ_FORM_JS):
        if row.get("type") != "file":
            continue
        hay = " ".join(str(row.get(k, "")) for k in ("label", "name", "id")).lower()
        if any(word in hay for word in ("resume", "cv", "curriculum")):
            page.set_input_files(row["selector"], str(path))
            return True
    return False


def accept(run_id: str) -> dict:
    """Move a run to APPROVED because its approval ALREADY says so.

    Split out from `confirm` after the beat got it exactly backwards: it
    called `confirm`, which calls `policy.decide(APPROVED)` — so a run he
    had never looked at got approved BY THE THING CHECKING WHETHER HE HAD
    APPROVED IT, and one he genuinely had approved raised "already
    decided" and was reported to him as a failure. Granting and reading a
    grant are different verbs and now they are different functions.
    """
    record = load_run(run_id)
    ok, why = policy.usable(record["approval"])
    if not ok:
        raise ApplyError(why)
    record["state"] = "APPROVED"
    record["confirmed_at"] = stateio.utcnow()
    stateio.write_json_atomic(_record_path(run_id), record)
    return record


def confirm(run_id: str, *, via: str = "operator", because: str = "") -> dict:
    """He said yes here, at a keyboard. Grants the approval, sends nothing."""
    record = load_run(run_id)
    policy.decide(record["approval"], "APPROVED", via=via, because=because)
    return accept(run_id)


def submit(run_id: str, *, submitter=None) -> dict:
    """Press it. Once.

    The approval is spent here and the record moves to SUBMITTED before
    anything else can look at it, because the failure mode of a retry loop
    on this particular button is five copies of his application in
    somebody's inbox.
    """
    policy.ensure_not_halted()
    record = load_run(run_id)
    if record["state"] == "SUBMITTED":
        raise ApplyError(f"{run_id} was already submitted at "
                         f"{record.get('submitted_at')} — not sending it again")
    # And the same question asked of the LEDGER, which a re-stage cannot
    # rewrite. The check above reads the record, and on 2026-09-12 a
    # campaign rebuilt three already-sent records from scratch, which would
    # have put a second copy of his application in front of Stripe,
    # Databricks and Samsara. An employer cannot unsee that.
    gone = was_sent(record.get("url", ""))
    if gone:
        # CLOSED as well as refused. Refused alone left the record waiting,
        # and the beat asked the same question of it every minute.
        _close_quietly(run_id, "an application already went to this form")
        raise ApplyError(
            f"{run_id}: an application already went to {record.get('url')} at "
            f"{gone.get('at')} — not sending a second copy")
    # And the same JOB under a different url. Live 2026-09-13: two
    # applications reached Databricks for "Business Development
    # Representative" — gh_jid 8423165002 and 8423167002, one role posted
    # to two locations. Both urls were new, so the ledger had no objection
    # and the employer saw one person apply twice for one job. His
    # instruction the same evening: "make sure that we are really focusing
    # on not doing any duplicates".
    same = was_applied_to_role(record.get("company", ""),
                               record.get("job_title", ""))
    if same and same.get("id") != record.get("id"):
        _close_quietly(run_id, "the same job was already applied for under a different link")
        raise ApplyError(
            f"{run_id}: {record.get('job_title') or 'that job'} at "
            f"{record.get('company')} was already applied for at "
            f"{same.get('at')} — the same job under a different link")
    # And never a job that is not realistic for him, however many of its
    # questions have since been answered. His words, 2026-09-13: "shoot high
    # and shoot low. But it should be realistic."
    from aletheia import job_fit
    unfit = job_fit.quick_reason(record)
    if unfit:
        _close_quietly(run_id, f"not realistic: {unfit}")
        raise ApplyError(f"{run_id}: not sent — {unfit}")
    if record["state"] != "APPROVED":
        raise ApplyError(f"{run_id} is {record['state']}; it needs your "
                         "confirmation before anything is sent")
    ok, why = policy.usable(record["approval"])
    if not ok:
        raise ApplyError(f"{why} — nothing was sent")
    # The last line for a job only his own yes may send, whoever called.
    kind = waits_for_his_ok(record)
    if kind:
        record["state"] = "AWAITING_YOU"
        stateio.write_json_atomic(_record_path(record["id"]), record)
        why = ("only my own model judged it" if kind == JUDGED_LOCALLY else f"it is {kind} work")
        raise ApplyError(f"{run_id}: {why}, so it waits for your own OK - nothing was sent")

    import os as _os
    record["state"] = "SUBMITTING"
    record["submitted_at"] = stateio.utcnow()
    # Who is pressing, and whether the button has been pressed yet, so a
    # submit that is killed or dies can be settled honestly afterwards:
    # live 2026-09-13 two records sat at SUBMITTING for good and nothing
    # could say whether an employer had his application.
    record["submit_pid"] = _os.getpid()
    record.pop("pressed_at", None)
    stateio.write_json_atomic(_record_path(record["id"]), record)

    try:
        outcome = (submitter or _refill_and_submit)(record)
    except Exception as exc:
        why = f"{type(exc).__name__}: {exc}"[:300]
        if record.get("pressed_at") and not isinstance(exc, ApplyError):
            # The button WAS pressed and then something broke. Whether it
            # went is unknown, so it is counted as sent: a second copy in
            # an employer's inbox is the one outcome that cannot be undone.
            return _maybe_sent(record, why)
        if not record.get("pressed_at") and _worth_another_turn(exc):
            _back_in_line(record, why)
            raise
        record["state"] = "FAILED"
        record["failure"] = why
        stateio.write_json_atomic(_record_path(record["id"]), record)
        journal.append("alert", "apply",
                       f"{record['id']} failed to submit: {record['failure']}",
                       actor=ACTOR)
        raise

    if str(outcome.get("verdict") or "").casefold() == "rejected":
        # HANDED BACK is not sent. It is kept apart - not in the ledger, not
        # in his count - with the page's own complaint, so a later re-stage
        # can change something rather than press the same form again.
        complaint = " ".join(str(outcome.get("note") or outcome.get("evidence") or "").split())
        record.update({"state": REJECTED, "result": outcome,
                       "failure": f"the site refused it: {complaint}"[:300],
                       "rejected_at": stateio.utcnow()})
        stateio.write_json_atomic(_record_path(record["id"]), record)
        journal.append("alert", "apply",
                       f"{record['id']} was refused by the site at {record['url']} - "
                       f"not counted as sent: {complaint[:160]}", actor=ACTOR)
        raise ApplyError(f"{record['id']}: the site refused it - {complaint[:160]}")

    record.update({"state": "SUBMITTED", "result": outcome})
    stateio.write_json_atomic(_record_path(record["id"]), record)
    remember_sent(record)
    journal.append("action", "apply",
                   f"submitted {record['id']} to {record['url']} — "
                   f"{outcome.get('verdict')}", actor=ACTOR)
    return record


#: How many times an application whose button was never pressed goes back
#: in line after its browser was busy or would not open.
MAX_SUBMIT_TRIES = 3
#: A SUBMITTING record whose process cannot be named is settled after this.
SUBMIT_GRACE_S = 45 * 60
#: A submit still running after this is hung, and is stopped.
SUBMIT_CEILING_S = 2 * 60 * 60


def _worth_another_turn(exc: BaseException) -> bool:
    """A failure that happened before anything touched the form."""
    return isinstance(exc, browse.BrowserBusy) or browse._closed_browser_error(exc)


def _back_in_line(record: dict, why: str) -> dict:
    """Nothing was pressed: back to AWAITING_YOU for the next beat, a few times."""
    tries = int(record.get("submit_tries") or 0) + 1
    record["submit_tries"] = tries
    record["last_failure"] = why
    record.pop("submit_pid", None)
    if tries >= MAX_SUBMIT_TRIES:
        record["state"] = "FAILED"
        record["failure"] = f"{why} (tried {tries} times, nothing was ever pressed)"[:300]
        journal.append("alert", "apply",
                       f"{record['id']} failed to submit: {record['failure']}", actor=ACTOR)
    else:
        record["state"] = "AWAITING_YOU"
        record.pop("submitted_at", None)
        journal.append("action", "apply",
                       f"{record['id']} goes back in line - {why[:120]} - nothing was pressed",
                       actor=ACTOR)
    stateio.write_json_atomic(_record_path(record["id"]), record)
    return record


def _maybe_sent(record: dict, why: str) -> dict:
    company = record.get("company") or "the employer"
    record["state"] = "SUBMITTED"
    record["result"] = {
        "verdict": "submitted, unconfirmed",
        "note": (f"She pressed Submit and was stopped before the page answered "
                 f"({why[:120]}). Check your email for a confirmation from "
                 f"{company}. It is counted as sent so it can never go twice.")}
    stateio.write_json_atomic(_record_path(record["id"]), record)
    remember_sent(record)
    journal.append("alert", "apply",
                   f"{record['id']} may have been submitted to {record.get('url')} - "
                   f"interrupted after the press: {why[:160]}", actor=ACTOR)
    return record


def settle_interrupted(run_id: str, why: str) -> dict:
    """A submit that stopped without finishing, settled from what is known.

    Pressed, or too old to know (a record from before `submit_pid` was
    written): counted as sent, unconfirmed, and he is told to check his
    email. Never pressed: back in line.
    """
    record = load_run(run_id)
    if record.get("state") != "SUBMITTING":
        return record
    if record.get("pressed_at") or "submit_pid" not in record:
        return _maybe_sent(record, why)
    return _back_in_line(record, why)


def reconcile_stuck_submits(*, now: float | None = None) -> list[dict]:
    """Every SUBMITTING record whose submit is gone or hung, settled."""
    from aletheia import proc
    import datetime as _dt
    now = time.time() if now is None else now
    settled = []
    for record in all_runs("SUBMITTING"):
        try:
            began = _dt.datetime.fromisoformat(
                str(record.get("submitted_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            began = 0.0
        age = now - began
        pid = record.get("submit_pid")
        alive = proc.pid_alive(pid, needle="aletheia") if pid else None
        if alive is True and age < SUBMIT_CEILING_S:
            continue
        if alive is None and age < SUBMIT_GRACE_S:
            continue
        if alive is True:
            if proc.pid_alive(pid, needle="aletheia.apply_run") is True:
                proc.kill_tree(pid)
            why = f"the submit was still running after {int(age // 60)} minutes and was stopped"
        else:
            why = "the process pressing it stopped before it finished"
        settled.append(settle_interrupted(record["id"], why))
    return settled


#: The page telling him a human check is in the way, in the words the real
#: forms use. Matched on the SENTENCE, never on the word "code" alone: a job
#: description that mentions writing code is not a verification wall.
_CODE_WALL = re.compile(
    r"verification code was sent|enter the [0-9]+-character code"
    r"|confirm you(?:'|’)?re a human|code we (?:just )?(?:e-?mailed|sent)",
    re.I)
#: The code itself, taken from the sentence that hands it over. Greenhouse
#: writes: "Copy and paste this code into the security code field on your
#: application: ApHIj2MW".
#:
#: Two things the first version got wrong, both proved against his real mail
#: on 2026-09-12. It matched `[A-Z0-9]` and every real code is MIXED case
#: (ApHIj2MW, gOF5SXbK, kwsGIRvz) - and worse, `(?:code|verification)\D{0,40}`
#: let the capture land on the word "security" itself, so it returned
#: 'security' for all five and typed that into the form. A pattern that
#: matches something is not a pattern that matches the right thing.
_CODE_IN_MAIL = re.compile(
    r"(?:code|codes?)\s*(?:field[^:]{0,30})?[:\s]\s*([A-Za-z0-9]{6,10})\b"
    r"|\b([A-Za-z0-9]{8})\b(?=[^A-Za-z0-9]{0,40}(?:is your|after you enter"
    r"|to (?:submit|confirm)))")
#: Words that are never the code, however the sentence is shaped.
_NOT_A_CODE = frozenset({
    "security", "greenhouse", "application", "resubmit", "verification",
    "password", "continue"})
CODE_WAIT_TRIES = 20
CODE_WAIT_S = 15


def _wants_a_code(body: str) -> bool:
    return bool(_CODE_WALL.search(str(body or "")))


def _when(message: dict) -> float:
    """When an email was sent, as a number. Unreadable dates sort oldest."""
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(str(message.get("date", ""))).timestamp()
    except Exception:
        return 0.0


def code_in(text: str) -> str:
    """The code out of one email's text, or "" — the words are never it."""
    for hit in _CODE_IN_MAIL.finditer(str(text or "")):
        found = (hit.group(1) or hit.group(2) or "").strip()
        if found and found.casefold() not in _NOT_A_CODE:
            return found
    return ""


#: Words a company's name carries that the email naming it may not.
_COMPANY_FILLER = frozenset({
    "inc", "llc", "ltd", "co", "corp", "corporation", "company", "technologies",
    "technology", "labs", "the", "com", "io", "hq", "group", "holdings"})


def names_the_employer(subject: str, employer: str) -> bool:
    """Whether an email's subject names this employer, the way people write it.

    Live 2026-09-13 a code arrived about a minute after the click, in the
    inbox she reads, and she reported it never came: the record called the
    company "Acme ..." (a board name cut short) and the email said "Acme
    Technologies", and a SUBSTRING of one in the other is neither. The same
    gap sat under "Acme" / "Acme.io", "Acme" / "Acme, Inc." and "ACM" /
    "-ACM-", which only worked because they happened to be substrings.
    Compared as WORDS, legal suffixes and punctuation aside: every
    real word of the employer's name must be a word of the subject. An
    employer she cannot name at all does not narrow the search.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", str(employer or "").casefold())
             if w not in _COMPANY_FILLER]
    if not words:
        return True
    said = set(re.findall(r"[a-z0-9]+", str(subject or "").casefold()))
    return all(w in said for w in words)


def _emailed_code(employer: str = "", reader=None, since: float = 0.0) -> str:
    """The code the site just emailed, out of the inbox SHE can read.

    His ruling, 2026-09-12: *"If we have an option to fill an email, we just
    put open range interactive email ... who gives a shit what my personal
    email is if it's not something inappropriate?"* The address is not the
    point — being able to READ it is. Sent to his personal inbox, the code
    is unreachable and every application stops one field short.

    THE NEWEST ONE, FOR THIS EMPLOYER. `mail.read_body` refuses when more
    than one unread message matches, which is correct for "what did the
    dentist say" and useless here: a retry earns another code, and by the
    fourth attempt his inbox held four unread "Security code for your
    application to Databricks" emails, so the lookup threw every time and
    the gate reported that nothing had arrived. Codes are also per
    application — typing Databricks' code into Reddit's form fails, and
    looks from the outside exactly like a wrong code.
    """
    from aletheia import mail
    if reader is not None:
        for _ in range(CODE_WAIT_TRIES):
            found = reader(employer=employer)
            if found:
                return found
            time.sleep(CODE_WAIT_S)
        return ""
    for _ in range(CODE_WAIT_TRIES):
        try:
            unread = mail.SmtpImapTransport().fetch_unread(30)
        except Exception:
            unread = []
        mine = [m for m in unread
                if "security code" in str(m.get("subject", "")).casefold()
                and names_the_employer(str(m.get("subject", "")), employer)]
        # NEWEST FIRST, BY THE DATE HEADER, never by the order IMAP happens
        # to return. Live 2026-09-12 this read `reversed(mine)` on the belief
        # that IMAP hands back oldest-first; it hands back NEWEST-first, so
        # the walk went to the staleest code every time. Reddit was sent the
        # code from 15:46 when the page had just asked with the one from
        # 16:07, and Databricks got the oldest of five - both came back
        # "Incorrect security code". Stripe, GitLab and Scale AI worked only
        # because each had exactly one unread code, where oldest and newest
        # are the same message.
        mine.sort(key=_when, reverse=True)
        # AND NEWER THAN THE CLICK THAT ASKED FOR IT. Proved from his own
        # inbox, 2026-09-12: Reddit pressed submit at 16:26:52 and its code
        # arrived at 16:27:11 - NINETEEN SECONDS LATER. The lookup ran in
        # between and took the newest code that existed then, which was the
        # previous attempt's, from 16:07. Databricks was the same twice over.
        # Stripe, GitLab and Scale AI only worked because they had no earlier
        # code to be stale - so sorting was necessary and never sufficient,
        # and every test passed because no fixture had a prior code in it.
        #
        # A code older than the click is not this page's code. Wait for one
        # that is, rather than typing a stale one and reading "Incorrect
        # security code" off the form.
        if since:
            mine = [m for m in mine if _when(m) >= since - 5.0]
        for message in mine:
            try:
                body = mail.SmtpImapTransport().fetch_body(
                    message.get("message_id", ""))
            except Exception:
                continue
            found = code_in(str((body or {}).get("text") or ""))
            if found:
                return found
        time.sleep(CODE_WAIT_S)
    return ""


def _texted_code(since: float = 0.0) -> str:
    """The code the site just TEXTED, out of his Google Voice messages.

    A fallback, not a replacement: email is tried first because that is
    where most of them arrive and because reading a page costs a browser.
    Returns "" for every failure — no browser, not signed in, nothing
    fresh — because the caller's next line already says the honest thing
    ("it reached neither the inbox nor the texts she can read"), and a
    traceback out of here would reach the room as a log line.
    """
    try:
        from aletheia import gvoice
        found = gvoice.latest_code()
    except Exception:
        return ""
    if not found:
        return ""
    # Newer than the click that asked for it, the same rule the inbox
    # follows: a code from the previous attempt fails in a way that looks
    # exactly like a wrong code.
    if since and found.get("age_s") is not None:
        if time.time() - float(found["age_s"]) < since - 5.0:
            return ""
    return str(found.get("code") or "")


CODE_BOXES_JS = """() => Array.from(document.querySelectorAll(
  "input[autocomplete='one-time-code'], input[name*='security'], "
  + "input[id*='security'], input[name*='verification'], input[id*='verification']"
)).filter(el => el.offsetParent !== null).map((el, i) => el.id
  ? '#' + CSS.escape(el.id) : "input[name='" + el.name + "']:nth-of-type(" + (i+1) + ")")"""


def _type_the_code(page, code: str) -> None:
    """One box per character, or one box for the lot — both are out there."""
    boxes = page.evaluate(CODE_BOXES_JS) or []
    if len(boxes) <= 1:
        page.fill(boxes[0] if boxes else "input[autocomplete='one-time-code']", code)
        return
    for selector, character in zip(boxes, code):
        page.fill(selector, character)


def _refill_and_submit(record: dict) -> dict:
    """Re-open, re-fill exactly the approved steps, press the button.

    Re-filling rather than holding a page open for however long he takes
    to decide: a browser page waiting on a human is a resource the Core
    cannot promise, and the Core restarts itself on every code update. The
    approval is bound to the step list, so what is typed the second time is
    identical to what he saw.
    """
    ok, why = browse.available()
    if not ok:
        raise ApplyError(f"she cannot reopen the application: {why}")
    shot = staged_dir() / f"{record['id']}-submitted.png"
    with browse._Session() as ctx:
        page = ctx.new_page()
        page.goto(record["url"], wait_until="domcontentloaded")
        formfill.settle(page)
        _apply_steps(page, record["steps"])
        if record.get("resume") and _attach_resume(page, record["resume"]):
            if not _resume_landed(page, record["resume"]):
                # Pressing Submit with the upload still running sends his
                # application without the resume, or has it refused.
                raise ApplyError("the resume upload did not finish on the page - "
                                 "nothing was pressed")
        button = _submit_selector(page.evaluate(BUTTONS_JS))
        if button is None:
            raise ApplyError(
                "she could not find the button that submits this form — "
                "nothing was pressed. It may be a multi-step application, "
                "which she does not drive yet.")
        # The instant the button is pressed: any verification code this page
        # wants is emailed AFTER this, and anything older belongs to an
        # earlier attempt.
        asked_at = time.time()
        _press(page, record, button)
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_timeout(1500)     # let a confirmation render
        except Exception:
            pass
        # THE WHOLE PAGE for the decision, a slice of it for the record.
        # Live 2026-09-12 this read `[:4000]` and the check below never once
        # fired on a real form: a Greenhouse application runs to six thousand
        # characters and the verification sentence is the LAST thing on it,
        # so the detector was handed a page with the evidence cut off and
        # correctly found nothing. Truncate what is STORED, never what is
        # examined.
        whole = page.inner_text("body") or ""
        body = whole[:4000]
        # THE LAST GATE, and it is not a defect in the form. Live 2026-09-12
        # six applications were filled perfectly and none was accepted:
        # Greenhouse ends with "A verification code was sent to <address>.
        # To submit your application, enter the 8-character code to confirm
        # you're a human", and the button stays dead until it is typed. The
        # code is bound to THIS page, so it has to be done here, in the
        # session that pressed the button - reopening earns a fresh code.
        if _wants_a_code(whole):
            # Named, because the code is per application: Greenhouse titles
            # it "Security code for your application to Databricks", and
            # typing Databricks' code into Reddit's form fails in a way that
            # looks exactly like a wrong code.
            code = _emailed_code(record.get("company") or "", since=asked_at)
            if not code:
                # SOME SITES TEXT IT INSTEAD. The signup number is a Google
                # Voice line, so a code sent to it is one she can read —
                # and without this the application stops one field short
                # with the code sitting in a tab, which is the failure this
                # whole path exists to avoid. The same freshness rule
                # applies: gvoice refuses anything older than ten minutes.
                code = _texted_code(since=asked_at)
            if not code:
                # Never a silent success. He is told the application is
                # sitting one code away rather than being counted as sent.
                raise ApplyError(
                    "the site sent a verification code to confirm a human is "
                    "applying, and it has reached neither the inbox nor the "
                    "texts she can read — nothing was submitted")
            _type_the_code(page, code)
            page.click(_submit_selector(page.evaluate(BUTTONS_JS)) or button)
            page.wait_for_load_state("domcontentloaded")
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass
            # The same rule on the way out. A "Thank you for applying"
            # banner sits at the top, but the OUTCOME is read from this
            # text, and a page that hands the form back puts its complaint
            # wherever it likes - truncating here is how a real acceptance
            # gets reported as "unconfirmed".
            whole = page.inner_text("body") or ""
            body = whole[:4000]
        page.screenshot(path=str(shot), full_page=True)
        landed = page.url
        title = page.title()
        page.close()
    # Never "done" without something that says so. A click that produced
    # no confirmation is a click, not an application — and a page that
    # handed the form back is a REFUSAL, which used to read the same as
    # silence. `browse.read_outcome` is the one place that knows the
    # difference, so this and the general web loop cannot drift on it.
    return {"url": landed, "title": title,
            "evidence": body[:600], "screenshot": str(shot),
            **browse.read_outcome(body, did=record.get("button", "submit"),
                                  title=title, url=landed)}


def _click_never_landed(exc: BaseException) -> str:
    """Why a click raised WITHOUT ever reaching the page, or "" when it may have.

    Playwright times a click out while it is still waiting for the element to
    be visible, enabled and still - before any pointer event is sent - and says
    so in its call log. A timeout after the click is a wait for navigation,
    and names it.
    """
    text = str(exc or "")
    if type(exc).__name__ != "TimeoutError" or "navigat" in text.casefold():
        return ""
    for said, meaning in (("not enabled", "the button was disabled"),
                          ("intercepts pointer events", "something on the page covered it"),
                          ("not visible", "the button was not visible"),
                          ("not stable", "the button kept moving")):
        if said in text:
            return meaning
    return "it never became clickable"


def _press(page, record: dict, button: str) -> None:
    """Press Submit, writing down that it was pressed - and taking that back
    when the click provably never landed.

    Written BEFORE the click, so a process killed mid-press is settled as "may
    have gone" rather than "nothing was sent". But live 2026-09-13 Nitra and
    Ro (both Lever) timed out waiting for `#btn-submit` to take a click, were
    counted as sent - "Check your email" - and no confirmation ever came: the
    button was never pressed, and the ledger now says both employers have his
    application.
    """
    record["pressed_at"] = stateio.utcnow()
    stateio.write_json_atomic(_record_path(record["id"]), record)
    try:
        page.click(button)
    except Exception as exc:
        why = _click_never_landed(exc)
        if not why:
            raise
        record.pop("pressed_at", None)
        # WHAT was in the way, kept on the record. Live 2026-09-13 both Lever
        # sends timed out here and the journal cut the reason off; a probe of
        # a fresh Lever form found the button clear and an invisible hCaptcha
        # loaded behind it. The next blocked click says which it was.
        seen = _what_blocked_the_click(page, button, record)
        if seen.get("captcha"):
            why = "a CAPTCHA challenge was in front of it, and she does not solve those"
        record["click_evidence"] = seen
        stateio.write_json_atomic(_record_path(record["id"]), record)
        raise ApplyError(f"the Submit button would not take a click - {why} - "
                         "nothing was sent") from None


#: What sits on a page when a Submit click cannot land: a visible CAPTCHA
#: challenge frame, and whatever element is on top of the button's centre.
_BLOCKED_JS = r"""(sel) => {
  const challenge = /hcaptcha|recaptcha|turnstile|challenges\.cloudflare/i;
  const shown = [...document.querySelectorAll('iframe')].filter(f =>
    f.offsetParent !== null && f.offsetWidth > 100 && f.offsetHeight > 100 &&
    challenge.test((f.src || '') + ' ' + (f.title || '')));
  const out = {captcha: shown.length > 0, covered_by: '', button_found: false};
  const b = document.querySelector(sel);
  if (b) {
    out.button_found = true;
    const r = b.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (top && top !== b && !b.contains(top)) {
      out.covered_by = top.outerHTML.slice(0, 200);
      if (/captcha|turnstile/i.test(out.covered_by)) out.captcha = true;
    }
  }
  return out;
}"""


def _what_blocked_the_click(page, button: str, record: dict) -> dict:
    """What was in front of a Submit button that would not take a click. Never raises."""
    seen: dict = {"captcha": False, "covered_by": "", "button_found": None}
    try:
        seen.update(page.evaluate(_BLOCKED_JS, button) or {})
    except Exception as exc:
        seen["error"] = f"{type(exc).__name__}"[:60]
    try:
        shot = staged_dir() / f"{record['id']}-blocked.png"
        page.screenshot(path=str(shot), full_page=False)
        seen["screenshot"] = str(shot)
    except Exception:
        pass
    return seen


def spoken(record: dict) -> str:
    if record.get("state") == "NEEDS_YOU":
        return record["say"]
    if record.get("state") == "AWAITING_YOU":
        left = len(record.get("not_filled") or [])
        return (f"Application ready at {record['url']}: "
                f"{speech.count_phrase(len(record['filled']), 'field')} filled"
                + (f", {left} left blank that you may want to look at" if left else "")
                + ". Say confirm to send it, or look at the screenshot first.")
    if record.get("state") == "SUBMITTED":
        return f"Sent. {record.get('result', {}).get('note', '')}"
    return f"{record.get('id')} is {record.get('state')}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apply, with one confirmation.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_stage = sub.add_parser("stage")
    p_stage.add_argument("url")
    p_stage.add_argument("--resume", default="")
    p_stage.add_argument("--answer", action="append", default=[],
                         metavar="FIELD=VALUE")
    sub.add_parser("pending")
    p_ok = sub.add_parser("confirm"); p_ok.add_argument("run_id")
    p_send = sub.add_parser("submit"); p_send.add_argument("run_id")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "stage":
            extra = dict(a.split("=", 1) for a in args.answer if "=" in a)
            record = stage(args.url, resume=args.resume, extra=extra)
            print(spoken(record))
            print(json.dumps(record.get("filled") or record.get("would_fill"),
                             indent=2, ensure_ascii=False))
            for q in record.get("questions") or record.get("not_filled") or []:
                print(f"  {'*' if q['required'] else ' '} {q['label']}: {q['why']}")
        elif args.cmd == "pending":
            for record in all_runs("AWAITING_YOU"):
                print(f"{record['id']}  {record['url']}")
        elif args.cmd == "confirm":
            print(spoken(confirm(args.run_id)))
        else:
            print(spoken(submit(args.run_id)))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
