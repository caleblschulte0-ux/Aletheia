"""The job hunt's numbers, published where the morning brief can read them.

The brief is composed in the cloud from the repository, and the application
records live on his PC - so from the first application to 2026-10-02 the
brief never once had a "## Job hunt" section: `brief._job_hunt_lines`
asked `current_state.job_hunt()`, found no records on the runner, and
printed nothing. He asked *"how's it going"* of a system that could not
say, and his own words that day were *"I'm not getting accepted to any of
the jobs, so clearly she's not doing a good job"* - a judgement nobody
could check, because the funnel was nowhere.

So the Core writes the COUNTS - never a name, an employer, a question or
a url; this repository is public - to `state/hunt/funnel.json` on the
beat, by his local day, and the checkpoint commit carries it (`state/` is
an owned path). The brief reads it when it has no records of its own.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

from aletheia import stateio
from aletheia.fleet import REPO_ROOT

#: Repo-anchored on purpose (the checkpoint commit carries it), which is
#: why the suite and the sandbox must point it elsewhere: the first full
#: run wrote a funnel of test rows into the real repository
#: (`tests/__init__.py` sets the variable; `talk.SANDBOX_STORES` moves it).
FUNNEL_PATH = Path(os.environ.get("ALETHEIA_HUNT_FUNNEL") or (REPO_ROOT / "state" / "hunt" / "funnel.json"))
DAYS = 30
PUBLISH_EVERY_S = 1800.0
_LAST: dict = {"at": 0.0}

PRESSED = ("SUBMITTED", "SUBMITTING")
#: Why a closed application was closed, by the words of the reason
#: `apply_run.close` was given. Buckets only: the reason itself can name the
#: employer, and this file is public.
CLOSED_BECAUSE = (("not realistic", "not_realistic"), ("already", "duplicate"),
                  ("same job", "duplicate"), ("stale", "stale"), ("expired", "stale"),
                  ("no longer", "stale"))
#: The record's own closure kind, where it wrote one, in the funnel's words.
#: Live 2026-10-07 the first published breakdown read "other: 276" - nearly
#: every closure - because pages that were never forms and postings taken
#: down carry their kind on the record and no reason the text buckets knew.
CLOSED_KINDS = {"not-a-form": "not_a_form", "gone": "gone", "left": "left",
                "duplicate": "duplicate"}


def _left_bucket(why: str) -> str:
    """Which wall the general browser left an application at, by the
    mission's own words. Live 2026-10-07 "left" was 139 of the month's
    closures, the largest by far, and a human check, a page with no way
    forward and a question nobody answered are three different fixes."""
    try:
        from aletheia import browser_mission
        words = browser_mission._KIND_WORDS
    except Exception:
        words = {}
    for kind, said in sorted(words.items(), key=lambda kv: -len(kv[1])):
        if said.casefold() in why:
            return "left_" + kind.casefold()
    return "left"


def _closed_bucket(record: dict) -> str:
    why = str(record.get("closed_because") or "").casefold()
    named = next((name for lead, name in CLOSED_BECAUSE if lead in why), "")
    try:
        from aletheia import apply_run
        kind = apply_run.closure_kind(record)
    except Exception:
        kind = str(record.get("closed_kind") or "")
    if kind == "left":
        return _left_bucket(why)
    if kind in CLOSED_KINDS:
        if kind == "not-a-form":
            return f"not_a_form_{_why_not_a_form(why)}_on_{_system_of(record.get('url'))}"
        if kind == "gone":
            # A posting a board still LISTS and whose form is gone is a stale
            # listing on that system, not a job that closed in the ordinary
            # way: live 2026-10-08 "gone" was 15 of three days' closures.
            return f"gone_on_{_system_of(record.get('url'))}"
        return CLOSED_KINDS[kind]
    if named:
        return named
    # `closure_kind` calls everything it cannot place "unfit", and every
    # unfit closure is a judgement that the job was not realistic for him.
    return "not_realistic" if kind == "unfit" else "other"


def _why_not_a_form(why: str) -> str:
    """Which of `apply_run.stage`'s three "not a form" findings it was, from
    its own fixed sentences. Live 2026-10-07 46 closures read "not_a_form"
    and nothing said whether those were job-alert lists, bot checks or
    postings whose form sits behind a button - three different fixes."""
    if "job-alert" in why or "talent-network" in why:
        return "signup_list"
    if "name, email or phone" in why:
        return "asks_nothing"
    if "no application form" in why:
        return "nothing_to_fill"
    return "other"


def _system_of(url) -> str:
    """The applicant-tracking system an address belongs to, or
    "employer_site": a system's name, never the employer's."""
    import urllib.parse
    host = (urllib.parse.urlparse(str(url or "")).hostname or "").casefold()
    for system in ("greenhouse", "lever", "ashbyhq", "workable", "smartrecruiters", "recruitee",
                   "bamboohr", "myworkdayjobs", "icims"):
        if system in host.split("."):
            return system
    return "employer_site"


#: A failure's own words name an employer, a url or a question, and this
#: repo is public, so only its SHAPE is published: never pressed, refused
#: by the site, or the name of the error that stopped it.
_ERROR_NAME = re.compile(r"^([A-Za-z_][A-Za-z0-9_]{2,60}(?:Error|Exception|Timeout|Busy|Refused|Closed))\s*:")


_NET_CODE = re.compile(r"net::(ERR_[A-Z_]{2,40})")

#: Any leading name before a colon - published only when it is the name of a
#: real exception class, so an employer's name never is.
_LEADING_NAME = re.compile(r"^([A-Z][A-Za-z0-9_]{2,60})\s*:")


def _exception_names() -> set[str]:
    """The names of every exception class this process has loaded. Most of
    hers do not end in Error (DuplicateSubmission, PressNeverReached,
    Halted), and live 2026-10-07 51 of 59 failures still read "other"."""
    names, todo = set(), [BaseException]
    while todo:
        cls = todo.pop()
        names.add(cls.__name__)
        try:
            todo.extend(cls.__subclasses__())
        except TypeError:
            continue
    return names


def _failed_bucket(record: dict) -> str:
    why = str(record.get("failure") or "")
    low = why.casefold()
    if "nothing was ever pressed" in low:
        return "never_pressed"
    if low.startswith("the site refused it"):
        return "site_refused"
    if "would not take a click" in low:
        return "submit_would_not_click"
    named = _ERROR_NAME.match(why.strip())
    if named:
        return named.group(1)
    leading = _LEADING_NAME.match(why.strip())
    if leading and leading.group(1) != "Error" and leading.group(1) in _exception_names():
        return leading.group(1)
    if re.match(r"^Error\s*:", why.strip()):
        # The browser library's own exception is called just "Error", and
        # it was most of the 52 "other" failures on 2026-10-07. Its network
        # code (net::ERR_...) names the shape without naming the site.
        code = _NET_CODE.search(why)
        return f"browser_{code.group(1).casefold()}" if code else "browser_error"
    if not why.strip() and record.get("engine"):
        # The general browser's REFUSED and MANUAL_ONLY land here with no
        # failure text at all: the wall it stopped at is the reason. Live
        # 2026-10-07, 54 of 74 failures read "other".
        wall = str(record.get("boundary") or "unknown").casefold()
        return "browser_" + re.sub(r"[^a-z0-9_]+", "_", wall)[:40]
    if not why.strip():
        # A record put down with no words: the last try's own words, if any.
        last = str(record.get("last_failure") or "").strip()
        return _failed_bucket({"failure": last}) if last else "no_reason_written"
    return "other"


#: What each batch did with the openings it was handed, by the time it
#: finished: counts only. Private state, because a run's own lists name
#: employers; only the sums are published.
TALLIES_PATH = stateio.private_dir("campaign") / "tallies.json"
#: The parts of a batch's answer that are lists of openings, in the
#: funnel's words.
BATCH_PARTS = (("ready", "ready"), ("blocked", "needs_answer"), ("failed", "unreachable"),
               ("needs_account", "needs_account"), ("passed_over", "not_realistic"),
               ("duplicates", "duplicate"), ("later", "unjudged"))


#: Why the fit judge turned a job down, by the rule's own fixed words
#: (`job_fit.hard_reason`, `UNWANTED_KINDS`). A model's reason is free text
#: that can name the employer, so it is only ever counted as "model".
_UNFIT_WORDS = (("years", re.compile(r"asks for \d+\+? years")),
                ("language", re.compile(r"someone who speaks")),
                ("clearance", re.compile(r"military or security-clearance")),
                ("license", re.compile(r"requires an? .{1,40} license")),
                ("hands_on", re.compile(r"hands-on shift work")),
                ("sales", re.compile(r"sales job|cold calling|outbound prospecting|quota")),
                ("pay", re.compile(r"under his \$[\d,]+ floor")),
                ("rival", re.compile(r"competes directly with his employer")))


def _unfit_bucket(why: str) -> str:
    """Which rule passed a job over, or "model", or "closed_before"."""
    why = str(why or "").casefold()
    for bucket, pattern in _UNFIT_WORDS:
        if pattern.search(why):
            return bucket
    if why.startswith(("not realistic", "closed as not realistic")):
        return "closed_before"
    return "model"


def _unreachable_bucket(why: str) -> str:
    """Why an opening could not be reached, as a word that names nothing: a
    form that was not there, a page left until tomorrow, or the kind of
    error - its class name only, since the message can carry an address."""
    why = str(why or "")
    lowered = why.casefold()
    if "no application form" in lowered:
        return "no_form"
    if "until tomorrow" in lowered:
        return "left_till_tomorrow"
    kind = re.match(r"([A-Z][A-Za-z]*(?:Error|Exception|Timeout|Unavailable|Refused))\b", why)
    return kind.group(1) if kind else "other"


def _batch_tally(result: dict) -> dict:
    """One batch's answer as counts. A weak shot and a full employer are
    told apart from the plain not-realistic and same-job, because each is
    a different dial: the angle's bar and the per-employer limit."""
    tally = {name: 0 for _part, name in BATCH_PARTS}
    tally.update({"weak_shot": 0, "employer_full": 0})
    for part, name in BATCH_PARTS:
        for row in result.get(part) or []:
            why = str(row.get("why") or "").casefold() if isinstance(row, dict) else ""
            if part == "passed_over" and why.startswith("a weak shot"):
                tally["weak_shot"] += 1
            elif part == "passed_over":
                tally[name] += 1
                bucket = "unfit_" + _unfit_bucket(why)
                tally[bucket] = tally.get(bucket, 0) + 1
            elif part == "failed":
                tally[name] += 1
                bucket = "unreachable_" + _unreachable_bucket(row.get("why") if isinstance(row, dict) else "")
                tally[bucket] = tally.get(bucket, 0) + 1
            elif part == "duplicates" and "this month" in why:
                tally["employer_full"] += 1
            else:
                tally[name] += 1
    return tally


def note_batch(result: dict, *, offered: int = 0, minutes: float = 0, now: dt.datetime | None = None,
               path=None) -> None:
    """Keep one finished batch's counts, a month of them. Never raises: the
    job hunt must not stop because a tally could not be written."""
    try:
        target = path or TALLIES_PATH
        stamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        floor = (stamp - dt.timedelta(days=DAYS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            rows = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = []
        rows = [r for r in rows if isinstance(r, dict) and str(r.get("at") or "") >= floor]
        # HOW LONG IT TOOK: a day with one batch that found one is either a
        # sparse board or one batch that ran all afternoon, and only the
        # minutes tell those apart.
        rows.append({"at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "offered": int(offered or 0),
                     "minutes": int(round(float(minutes or 0))), **_batch_tally(result)})
        target.parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(target, rows)
    except Exception:
        pass


def batches(tallies: list[dict], *, now: dt.datetime | None = None, days: int = DAYS) -> dict:
    """Per local day, what the batches did with what they were handed:
    how many ran and how many openings went each way. Pure.

    Live 2026-10-07 the funnel said 13 found for the day where mid-September
    days said forty and more, and nothing said whether the boards ran dry,
    the fit judge turned them away, the angle called them weak shots, or the
    per-employer limit held them: four different fixes, indistinguishable
    from the cloud."""
    from aletheia import localtime
    zone = localtime.operator_tz()
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(zone)
    first = (now.date() - dt.timedelta(days=days - 1)).isoformat()
    out: dict[str, dict] = {}
    for row in tallies or []:
        if not isinstance(row, dict):
            continue
        day = _day(row.get("at"), zone)
        if not day or day < first:
            continue
        into = out.setdefault(day, {"runs": 0})
        into["runs"] += 1
        for key, value in row.items():
            if key != "at" and isinstance(value, int):
                into[key] = into.get(key, 0) + value
    return dict(sorted(out.items()))


def _tallies(path=None) -> list[dict]:
    try:
        rows = json.loads((path or TALLIES_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


#: What a question that stopped a form ASKS, by its words: the topic only,
#: never the question (it can name the employer). Each topic is a fact of
#: his she could keep once and answer everywhere, so the biggest count is
#: the one thing worth asking him.
QUESTION_TOPICS = (("sponsor", "sponsorship"), ("visa", "sponsorship"), ("authoriz", "work_authorization"),
                   ("legally", "work_authorization"), ("salary", "pay"), ("compensation", "pay"),
                   ("pay ", "pay"), ("start date", "start_date"), ("when can you start", "start_date"),
                   ("available to start", "start_date"), ("relocat", "relocation"),
                   ("on-site", "on_site"), ("onsite", "on_site"), ("in office", "on_site"),
                   ("in-office", "on_site"), ("commute", "on_site"), ("years of", "years_experience"),
                   ("how many years", "years_experience"), ("why do you", "why_this_job"),
                   ("why are you", "why_this_job"), ("interest", "why_this_job"),
                   ("linkedin", "links"), ("portfolio", "links"), ("website", "links"),
                   # Which self-identification question, not one lump: he has
                   # answered veteran and disability already, so a lump of
                   # "demographic" could not say which one is still his to answer.
                   ("gender", "demographic_gender"), ("race", "demographic_race"),
                   ("veteran", "demographic_veteran"), ("disab", "demographic_disability"),
                   ("ethnic", "demographic_race"), ("hispanic", "demographic_race"),
                   ("pronoun", "demographic_pronouns"),
                   ("sexual orientation", "demographic_orientation"),
                   ("transgender", "demographic_gender"),
                   ("refer", "referral"), ("hear about", "referral"), ("cover letter", "cover_letter"),
                   ("security clearance", "clearance"), ("clearance", "clearance"),
                   ("background check", "background_check"), ("convicted", "background_check"),
                   ("felony", "background_check"), ("non-compete", "agreements"),
                   ("agreement", "agreements"), ("travel", "travel"), ("degree", "education"),
                   ("school", "education"), ("gpa", "education"), ("address", "address"),
                   ("city", "address"), ("phone", "contact"), ("email", "contact"))


def _question_topic(label: str) -> str:
    """At the START of a word, so "preferred" is not a referral and
    "ethnicity" is not a city."""
    said = " ".join(str(label or "").casefold().split()) + " "
    return next((topic for lead, topic in QUESTION_TOPICS
                 if re.search(r"(?<![a-z])" + re.escape(lead), said)), "other")


WORKED = ("AWAITING_YOU", "NEEDS_YOU", "NEEDS_ACCOUNT", "SUBMITTED", "SUBMITTING", "FAILED", "REJECTED", "APPROVED")


def _day(stamp: object, zone) -> str:
    try:
        from aletheia import localtime
        return localtime.parse_utc(str(stamp)).astimezone(zone).date().isoformat()
    except Exception:
        return ""


#: How many days count as recent for the closures published apart.
RECENT_DAYS = 3


def counts(rows: list[dict], *, now: dt.datetime | None = None, days: int = DAYS) -> dict:
    """Per-day counts from the records: found, filled, sent, replies,
    interviews, rejections. Pure."""
    from aletheia import localtime
    zone = localtime.operator_tz()
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(zone)
    first = (now.date() - dt.timedelta(days=days - 1)).isoformat()
    by_day: dict[str, dict] = {}

    def bump(day: str, key: str) -> None:
        if day and day >= first:
            by_day.setdefault(day, {"found": 0, "filled": 0, "sent": 0, "replies": 0,
                                    "interviews": 0, "rejections": 0})[key] += 1

    for r in rows:
        if not isinstance(r, dict):
            continue
        staged = _day(r.get("staged_at"), zone)
        bump(staged, "found")
        if r.get("state") in WORKED:
            bump(staged, "filled")
        if r.get("state") in PRESSED:
            bump(_day(r.get("submitted_at") or r.get("pressed_at") or r.get("staged_at"), zone), "sent")
        for entry in r.get("outcomes") or []:
            if not isinstance(entry, dict):
                continue
            when = _day(entry.get("at"), zone)
            outcome = str(entry.get("outcome") or "")
            if outcome in ("replied", "interview", "offer", "rejected"):
                bump(when, "replies")
            if outcome in ("interview", "offer"):
                bump(when, "interviews")
            if outcome == "rejected":
                bump(when, "rejections")
    # WHERE the window's applications went, by system name only (never an
    # employer): "is she applying beyond Greenhouse" was unanswerable.
    sent_by_system: dict[str, int] = {}
    for r in rows:
        if isinstance(r, dict) and r.get("state") in PRESSED:
            when = _day(r.get("submitted_at") or r.get("pressed_at") or r.get("staged_at"), zone)
            if when and when >= first:
                system = _system_of(r.get("url"))
                sent_by_system[system] = sent_by_system.get(system, 0) + 1
    total = {"found": 0, "filled": 0, "sent": 0, "replies": 0, "interviews": 0, "rejections": 0}
    for day in by_day.values():
        for key in total:
            total[key] += day[key]
    return {"days": dict(sorted(by_day.items())), "window_days": days, "totals": total,
            "sent_by_system": dict(sorted(sent_by_system.items())),
            "sent_all_time": sum(1 for r in rows if isinstance(r, dict) and r.get("state") in PRESSED),
            "waiting": waiting(rows, now=now, first=first),
            # THE LAST FEW DAYS APART. A month's closures mix causes already
            # fixed with ones still happening: live 2026-10-07 "asks nothing
            # on greenhouse" read 22, and nothing said whether one of them
            # was this week's.
            "closed_recently": {"days": RECENT_DAYS, "why": waiting(
                rows, now=now, first=(now.date() - dt.timedelta(days=RECENT_DAYS - 1)).isoformat())["closed"]},
            "generated_at": stateio.utcnow()}


def _waits_for_him(record: dict) -> str:
    try:
        from aletheia import apply_run
        return apply_run.waits_for_his_ok(record) or ""
    except Exception:
        return ""


def waiting(rows: list[dict], *, now: dt.datetime | None = None, first: str = "") -> dict:
    """Where the applications that were filled and NOT sent are sitting now.

    Live 2026-10-06 the funnel said 15 filled and 4 sent for the day, and
    nothing anywhere said where the other eleven were: waiting on an
    answer only he has, an account, his own OK for part-time work, a send
    that failed, or a grant nobody created. Every one of those is a
    different fix, and from the cloud they were indistinguishable. Counts
    only, never a name or a question."""
    from aletheia import localtime
    zone = localtime.operator_tz()
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(zone)
    out = {"to_send": 0, "his_ok": {}, "needs_answer": 0, "needs_account": 0, "failed": 0,
           "closed": {}, "failed_because": {}, "asked_about": {}, "oldest_days": 0}
    for r in rows:
        if not isinstance(r, dict):
            continue
        state = str(r.get("state") or "")
        if state in ("AWAITING_YOU", "APPROVED"):
            kind = _waits_for_him(r)
            if kind:
                out["his_ok"][kind] = out["his_ok"].get(kind, 0) + 1
            else:
                out["to_send"] += 1
        elif state == "NEEDS_YOU":
            out["needs_answer"] += 1
            for topic in {_question_topic(q.get("label") if isinstance(q, dict) else q)
                          for q in r.get("questions") or []}:
                out["asked_about"][topic] = out["asked_about"].get(topic, 0) + 1
        elif state == "NEEDS_ACCOUNT":
            out["needs_account"] += 1
        elif state == "FAILED":
            out["failed"] += 1
            kind = _failed_bucket(r)
            out["failed_because"][kind] = out["failed_because"].get(kind, 0) + 1
        elif state == "CLOSED":
            if first and _day(r.get("closed_at") or r.get("staged_at"), zone) < first:
                continue
            bucket = _closed_bucket(r)
            out["closed"][bucket] = out["closed"].get(bucket, 0) + 1
            continue
        else:
            continue
        try:
            age = (now - localtime.parse_utc(str(r.get("staged_at"))).astimezone(zone)).days
            out["oldest_days"] = max(out["oldest_days"], age)
        except Exception:
            pass
    out["his_ok"] = dict(sorted(out["his_ok"].items()))
    out["closed"] = dict(sorted(out["closed"].items()))
    out["failed_because"] = dict(sorted(out["failed_because"].items()))
    out["asked_about"] = dict(sorted(out["asked_about"].items()))
    return out


def publish(*, now: dt.datetime | None = None, clock=None, path=None) -> dict | None:
    """Write the funnel when it changed and at most every half hour. None
    when nothing was written. Never raises past the beat's guard."""
    tick = (clock or time.monotonic)()
    if tick - _LAST["at"] < PUBLISH_EVERY_S:
        return None
    _LAST["at"] = tick
    from aletheia import apply_run
    rows = apply_run.all_runs()
    fresh = counts(rows, now=now)
    fresh["batches"] = batches(_tallies(), now=now)
    left = _left_missions()
    fresh["stuck_at"] = stuck_at(left, now=now)
    # The month mixes stops already fixed with ones still happening.
    fresh["stuck_recently"] = {"days": RECENT_DAYS,
                               "where": stuck_at(left, now=now, days=RECENT_DAYS)}
    target = path or FUNNEL_PATH
    try:
        old = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    same = {k: v for k, v in old.items() if k != "generated_at"} == {k: v for k, v in fresh.items() if k != "generated_at"}
    if same:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(target, fresh)
    return {"written": str(target), "sent_in_window": fresh["totals"]["sent"]}


def _stuck_cause(boundary: dict) -> str:
    """Which of the general browser's own stops this was, from the words it
    left - never the page's address."""
    state = str(boundary.get("page_state") or "").casefold() or "unread"
    step = str(boundary.get("step") or "").casefold()
    if state == "unknown":
        return "unreadable_page"
    if step.startswith("find the box"):
        return "no_code_box"
    if step.startswith("tell me what to press"):
        return "unclear_button"
    held = str(boundary.get("dead_end") or "")
    if held in ("empty_page", "apply_elsewhere", "apply_not_taken", "no_apply"):
        # What the dead end held, one fixed word (browser_loop.DEAD_ENDS).
        return f"nothing_to_press_on_{state}+{held}"
    return "nothing_to_press_on_" + state


def _furthest(mission: dict) -> str:
    from aletheia import browser_mission as bm
    names = {row.get("name") for row in mission.get("checkpoints") or []}
    return next((name for name in reversed(bm.CHECKPOINTS) if name in names), "nothing")


def stuck_at(missions: list[dict], *, now: dt.datetime | None = None, days: int = DAYS) -> dict:
    """Where the general browser stopped on the job applications it left in
    the window: which stop and how far she had got, as counts. Live
    2026-10-07 "no way forward on the page" was 71 of the month's closed
    applications and nothing said whether that was a posting with no Apply
    button, a form she had filled, or a button she could not read."""
    from collections import Counter
    from aletheia import browser_mission as bm
    now = now or dt.datetime.now(dt.timezone.utc)
    first = now - dt.timedelta(days=days)
    out: dict = {}
    for mission in missions:
        try:
            if mission.get("state") != bm.LEFT or not bm._is_job(mission):
                continue
            when = dt.datetime.fromisoformat(str(mission.get("left_at") or "").replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            if when < first:
                continue
            boundary = mission.get("boundary") or {}
            kind = str(boundary.get("kind") or "unknown").casefold()
            where = f"{_stuck_cause(boundary)}/{_furthest(mission)}"
            out.setdefault(kind, Counter())[where] += 1
        except (ValueError, TypeError, AttributeError):
            continue
    return {kind: dict(sorted(c.items())) for kind, c in sorted(out.items())}


def _left_missions() -> list[dict]:
    try:
        from aletheia import browser_mission as bm
        return bm.all_missions(bm.LEFT)
    except Exception:
        return []


def read(path=None) -> dict | None:
    try:
        value = json.loads((path or FUNNEL_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and isinstance(value.get("days"), dict) else None


def words(funnel: dict, *, now: dt.datetime | None = None) -> list[str]:
    """The brief's lines from a published funnel: yesterday, the week, the
    month. Numbers only, and a verdict he can act on."""
    from aletheia import localtime
    zone = localtime.operator_tz()
    today = (now or dt.datetime.now(dt.timezone.utc)).astimezone(zone).date()
    days = funnel.get("days") or {}

    def window(n: int) -> dict:
        first = (today - dt.timedelta(days=n - 1)).isoformat()
        out = {"found": 0, "sent": 0, "replies": 0, "interviews": 0, "rejections": 0}
        for day, row in days.items():
            if day >= first:
                for k in out:
                    out[k] += int(row.get(k) or 0)
        return out

    yesterday = days.get((today - dt.timedelta(days=1)).isoformat()) or {}
    week, month = window(7), window(30)
    if not any(month.values()):
        return []                      # no hunt to speak of is no section, not a row of zeros
    out = ["## Job hunt"]
    out.append(f"- **Yesterday:** {int(yesterday.get('sent') or 0)} sent, "
               f"{int(yesterday.get('replies') or 0)} heard back, {int(yesterday.get('interviews') or 0)} interview(s)")
    out.append(f"- **Last 7 days:** {week['sent']} sent, {week['replies']} heard back, "
               f"{week['interviews']} interview(s), {week['rejections']} said no")
    out.append(f"- **Last 30 days:** {month['sent']} sent, {month['replies']} heard back, "
               f"{month['interviews']} interview(s), {month['rejections']} said no")
    if month["sent"] and not month["interviews"]:
        rate = (100 * month["replies"] // month["sent"]) if month["sent"] else 0
        out.append(f"- {month['sent']} applications and no interview yet; {rate}% heard back at all. "
                   "Say 'how is the job hunt going' for which employers and why.")
    out.extend(_waiting_words(funnel.get("waiting")))
    out.append("")
    return out


def _waiting_words(held) -> list[str]:
    """One line saying where the filled-but-unsent applications are, when
    any are. Every part names what clears it."""
    if not isinstance(held, dict):
        return []
    parts = []
    if held.get("needs_answer"):
        parts.append(f"{held['needs_answer']} stopped on a question only you can answer")
    if held.get("needs_account"):
        parts.append(f"{held['needs_account']} need an account on the employer's site")
    his_ok = sum(int(v or 0) for v in (held.get("his_ok") or {}).values())
    if his_ok:
        parts.append(f"{his_ok} wait for your own OK (part-time, contract or judged by her own model)")
    if held.get("to_send"):
        parts.append(f"{held['to_send']} filled and not yet sent")
    if held.get("failed"):
        parts.append(f"{held['failed']} failed to send")
    if not parts:
        return []
    return ["- **Waiting:** " + "; ".join(parts) + "."]
