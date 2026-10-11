"""Dated lines read out of text: "Networking After Hours - Tue, Oct 14, 5:30 pm".

A look that found a listing page wrote its answer in prose, and the step after it - putting
the thing on his calendar - had only a small model to pull a date and a time back out of
that prose. It found none and looked again for days while the page it had read listed
dated items (his PC, 2026-10-11). This reads them deterministically: a date (ISO, a month
name, or month/day) and, on the same line, a time. Nothing is guessed: a line with a date
and no time is returned untimed, and a year that is not written is the next one in which
that day has not yet passed.
"""
from __future__ import annotations

import datetime as dt
import re

MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NAMED = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b"
                    r"(?:,?\s+(\d{4})\b)?", re.I)
_NUMERIC = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?![\d/])")
_TIME_12 = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\b\.?", re.I)
_TIME_24 = re.compile(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b")
_WEEKDAY = re.compile(r"\b(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|nesday|urday|sday)?\b\.?,?", re.I)
_SPLIT = re.compile(r"\n+|\s\|\s|;\s|\s•\s|\s·\s|(?<=[a-z]{2}[.!?])\s+(?=[A-Z])")
#: The marker a look puts before the dated lines it carries (`research.spoken`).
_MARKER = re.compile(r"^dated:\s*", re.I)
_EDGES = " -–—:,|()@.\t"

MAX_TITLE = 80


def _date(m: re.Match, kind: str, today: dt.date) -> dt.date | None:
    try:
        if kind == "iso":
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if kind == "named":
            month, day, year = MONTHS[m.group(1).lower()[:3]], int(m.group(2)), m.group(3)
        else:
            month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
            if year and len(year) == 2:
                year = "20" + year
        if year:
            return dt.date(int(year), month, day)
        found = dt.date(today.year, month, day)
        return found if found >= today else dt.date(today.year + 1, month, day)
    except (ValueError, KeyError):
        return None


def _time(text: str) -> dt.time | None:
    m = _TIME_12.search(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return None
        hour = hour % 12 + (12 if m.group(3).lower() == "p" else 0)
        return dt.time(hour, minute)
    m = _TIME_24.search(text)
    return dt.time(int(m.group(1)), int(m.group(2))) if m else None


def _title(before: str, rest: str) -> str:
    for part in (before, rest):
        cut = _WEEKDAY.sub(" ", _TIME_12.sub(" ", _TIME_24.sub(" ", part)))
        cut = re.sub(r"\s+", " ", cut).strip(_EDGES)
        cut = re.sub(r"\s+(?:on|from|at)$", "", cut, flags=re.I).strip(_EDGES)
        if len(re.findall(r"[A-Za-z]", cut)) >= 3:
            return cut[:MAX_TITLE].strip(_EDGES)
    return ""


def occurrences(text: str, *, now: dt.datetime, tz: dt.tzinfo) -> list[dict]:
    """Every dated line of `text`: {"title", "date", "start" (ISO, or "" untimed), "timed", "line"},
    in the order the text gives them. A date standing alone in a row ("Lunch | Oct. 19 at 12:00 pm")
    takes the cell before it as its title; a line that names no title at all is left out."""
    today = now.astimezone(tz).date()
    out, prev = [], ""
    for line in _SPLIT.split(str(text or "")):
        line = _MARKER.sub("", " ".join(line.split()))
        if not line:
            continue
        before, prev = prev, line
        found = None
        for kind, pattern in (("iso", _ISO), ("named", _NAMED), ("numeric", _NUMERIC)):
            m = pattern.search(line)
            if m:
                day = _date(m, kind, today)
                if day is not None:
                    found = (m, day)
                    break
        if found is None:
            continue
        m, day = found
        title = _title(line[:m.start()], line[m.end():]) or _title(before, "")
        if not title:
            continue
        at = _time(line[m.end():]) or _time(line)
        start = dt.datetime.combine(day, at, tzinfo=tz).isoformat() if at else ""
        out.append({"title": title, "date": day.isoformat(), "start": start, "timed": bool(at),
                    "line": line[:160]})
    return out
