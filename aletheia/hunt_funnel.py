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


def _closed_bucket(record: dict) -> str:
    why = str(record.get("closed_because") or "").casefold()
    named = next((name for lead, name in CLOSED_BECAUSE if lead in why), "")
    try:
        from aletheia import apply_run
        kind = apply_run.closure_kind(record)
    except Exception:
        kind = str(record.get("closed_kind") or "")
    if kind in CLOSED_KINDS:
        return CLOSED_KINDS[kind]
    if named:
        return named
    # `closure_kind` calls everything it cannot place "unfit", and every
    # unfit closure is a judgement that the job was not realistic for him.
    return "not_realistic" if kind == "unfit" else "other"


#: A failure's own words name an employer, a url or a question, and this
#: repo is public, so only its SHAPE is published: never pressed, refused
#: by the site, or the name of the error that stopped it.
_ERROR_NAME = re.compile(r"^([A-Za-z_][A-Za-z0-9_]{2,60}(?:Error|Exception|Timeout|Busy|Refused|Closed))\s*:")


def _failed_bucket(record: dict) -> str:
    why = str(record.get("failure") or "")
    low = why.casefold()
    if "nothing was ever pressed" in low:
        return "never_pressed"
    if low.startswith("the site refused it"):
        return "site_refused"
    named = _ERROR_NAME.match(why.strip())
    if named:
        return named.group(1)
    return "other"


WORKED = ("AWAITING_YOU", "NEEDS_YOU", "NEEDS_ACCOUNT", "SUBMITTED", "SUBMITTING", "FAILED", "REJECTED", "APPROVED")


def _day(stamp: object, zone) -> str:
    try:
        from aletheia import localtime
        return localtime.parse_utc(str(stamp)).astimezone(zone).date().isoformat()
    except Exception:
        return ""


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
    total = {"found": 0, "filled": 0, "sent": 0, "replies": 0, "interviews": 0, "rejections": 0}
    for day in by_day.values():
        for key in total:
            total[key] += day[key]
    return {"days": dict(sorted(by_day.items())), "window_days": days, "totals": total,
            "sent_all_time": sum(1 for r in rows if isinstance(r, dict) and r.get("state") in PRESSED),
            "waiting": waiting(rows, now=now, first=first),
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
           "closed": {}, "failed_because": {}, "oldest_days": 0}
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
