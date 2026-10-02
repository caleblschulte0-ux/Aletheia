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
            "generated_at": stateio.utcnow()}


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
    out.append("")
    return out
