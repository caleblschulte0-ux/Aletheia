"""Sums and calendar arithmetic he would otherwise wait a minute for.

Found with every model off, 2026-10-07: "what's the square root of 144",
"how many ounces in a pound", "what day of the week was july 4 1990",
"how many days between march 1 and april 15", "what time will it be in
3 hours" and "what's half of 250" each went to a planner nobody could
run. Every one is arithmetic. Each function returns a sentence, or None
when the words are not something it can be certain about. The fast lane's
whole safety argument is that None sends the question on to a model, so
nothing here may guess.
"""
from __future__ import annotations

import datetime as dt
import math
import re

_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
                 "half a": 0.5, "half an": 0.5, "a half": 0.5, "a quarter": 0.25}


def _num(word: str) -> float | None:
    w = str(word or "").strip().casefold().replace(",", "")
    if w in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[w])
    try:
        return float(w)
    except ValueError:
        return None


def said(value: float) -> str:
    """A number as it is said: whole numbers plain, the rest to two places."""
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    shown = round(value, 2)
    return f"{shown:,.2f}".rstrip("0").rstrip(".")


def _about(value: float) -> str:
    """"about 1.41", but "4" for 4.00001: a conversion table's last digit
    is not a reason to hedge a number anybody would call exact."""
    exact = abs(round(value, 2) - value) <= 0.0005 * max(1.0, abs(value))
    return ("" if exact else "about ") + said(round(value, 2) if exact else value)


# ---- arithmetic -------------------------------------------------------------

_FRACTIONS = {"half": 0.5, "a half": 0.5, "a third": 1 / 3, "one third": 1 / 3, "a quarter": 0.25,
              "one quarter": 0.25, "a fifth": 0.2, "a tenth": 0.1, "double": 2.0, "twice": 2.0,
              "triple": 3.0, "three quarters": 0.75, "two thirds": 2 / 3}


def arith(text: str) -> str | None:
    """Square roots, squares, powers, and half/a third/double of a number."""
    t = " ".join(str(text or "").casefold().split()).rstrip("?. ")
    t = re.sub(r"^(?:what(?:'s| is|s)|whats|calculate|work out) ", "", t)
    m = re.fullmatch(r"(?:the )?(square|cube) root of (-?[\d.,]+)", t)
    if m:
        n = _num(m.group(2))
        if n is None:
            return None
        if m.group(1) == "square":
            if n < 0:
                return "A negative number has no real square root."
            value = math.sqrt(n)
        else:
            value = math.copysign(abs(n) ** (1 / 3), n)
        return _about(value)[:1].upper() + _about(value)[1:] + "."
    m = re.fullmatch(r"(-?[\d.,]+) (squared|cubed)", t)
    if m:
        n = _num(m.group(1))
        return None if n is None else f"{said(n ** (2 if m.group(2) == 'squared' else 3))}."
    m = re.fullmatch(r"(-?[\d.,]+) (?:to the power of|to the|raised to(?: the power of)?|\^) (-?[\d.,]+)(?:th|st|nd|rd)?(?: power)?", t)
    if m:
        a, b = _num(m.group(1)), _num(m.group(2))
        if a is None or b is None or abs(b) > 100:
            return None
        try:
            return f"{said(a ** b)}."
        except (OverflowError, ZeroDivisionError):
            return None
    m = re.fullmatch(r"(half|a half|a third|one third|a quarter|one quarter|a fifth|a tenth|double|twice"
                     r"|triple|three quarters|two thirds) (?:of )?(-?[\d.,]+)", t)
    if m:
        n = _num(m.group(2))
        if n is None:
            return None
        value = _FRACTIONS[m.group(1)] * n
        out = _about(value)
        return out[:1].upper() + out[1:] + "."
    return None


# ---- kitchen and household units ----------------------------------------------

#: millilitres per unit
_VOLUME = {"teaspoon": 4.92892, "tablespoon": 14.7868, "fluid ounce": 29.5735, "cup": 236.588,
           "pint": 473.176, "quart": 946.353, "gallon": 3785.41, "milliliter": 1.0, "liter": 1000.0}
#: grams per unit
_WEIGHT = {"ounce": 28.3495, "pound": 453.592, "gram": 1.0, "kilogram": 1000.0, "stone": 6350.29}

_ALIASES = {"tsp": "teaspoon", "teaspoons": "teaspoon", "tbsp": "tablespoon", "tablespoons": "tablespoon",
            "fl oz": "fluid ounce", "fluid ounces": "fluid ounce", "cups": "cup", "pints": "pint",
            "quarts": "quart", "gallons": "gallon", "ml": "milliliter", "milliliters": "milliliter",
            "millilitres": "milliliter", "millilitre": "milliliter", "liters": "liter", "litres": "liter",
            "litre": "liter", "l": "liter", "ounces": "ounce", "oz": "ounce", "pounds": "pound", "lb": "pound",
            "lbs": "pound", "grams": "gram", "g": "gram", "kilograms": "kilogram", "kg": "kilogram",
            "kilos": "kilogram", "kilo": "kilogram", "stones": "stone"}

_PLURAL = {"fluid ounce": "fluid ounces", "stone": "stone"}

UNIT_WORDS = sorted(set(_VOLUME) | set(_WEIGHT) | set(_ALIASES), key=len, reverse=True)


def _unit(word: str) -> str | None:
    w = str(word or "").strip().casefold()
    w = _ALIASES.get(w, w)
    return w if w in _VOLUME or w in _WEIGHT else None


def kitchen(text: str) -> str | None:
    """"How many ounces in a pound", "how many cups in 2 quarts",
    "convert 3 cups to ml". An ounce beside a volume is a fluid ounce,
    which is what anybody in a kitchen means by it."""
    t = " ".join(str(text or "").casefold().split()).rstrip("?. ")
    units = "|".join(re.escape(u) for u in UNIT_WORDS)
    m = re.fullmatch(rf"how many ({units}) (?:are |is )?(?:in|to|make|per) (?:a |an |one )?([\d.,]*) ?({units})", t)
    if m:
        dst, n, src = m.group(1), m.group(2) or "1", m.group(3)
    else:
        m = re.fullmatch(rf"(?:convert |what(?:'s| is|s) )?([\d.,]+|a|an|one|half a|half an) ({units}) (?:to|in|into) ({units})", t)
        if not m:
            return None
        n, src, dst = m.group(1), m.group(2), m.group(3)
    a, b, count = _unit(src), _unit(dst), _num(n)
    if not a or not b or count is None or a == b:
        return None
    # An ounce next to a volume is a fluid ounce.
    if a == "ounce" and b in _VOLUME:
        a = "fluid ounce"
    if b == "ounce" and a in _VOLUME:
        b = "fluid ounce"
    if a in _VOLUME and b in _VOLUME:
        value = count * _VOLUME[a] / _VOLUME[b]
    elif a in _WEIGHT and b in _WEIGHT:
        value = count * _WEIGHT[a] / _WEIGHT[b]
    else:
        return ("That depends on what it is - a cup of flour and a cup of sugar "
                "weigh different amounts, so I won't guess.")
    word = b if _about(value) == "1" else _PLURAL.get(b, b + "s")
    out = f"{_about(value)} {word}"
    return out[:1].upper() + out[1:] + "."


# ---- the calendar -------------------------------------------------------------

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")


def _date(words: str, today: dt.date) -> dt.date | None:
    """A date he named, with or without a year. Never guesses."""
    from aletheia import quick
    w = " ".join(str(words or "").casefold().replace(",", " ").split()).strip(" ?.")
    w = re.sub(r"\s+(?:this|next) year$", "", w)
    if w in ("today", "now"):
        return today
    if w == "tomorrow":
        return today + dt.timedelta(days=1)
    if w == "yesterday":
        return today - dt.timedelta(days=1)
    m = (re.fullmatch(r"(?:the )?(\d{1,2})(?:st|nd|rd|th)? (?:of )?([a-z]+) (\d{4})", w)
         or re.fullmatch(r"([a-z]+) (?:the )?(\d{1,2})(?:st|nd|rd|th)? (\d{4})", w))
    if m:
        a, b, year = m.group(1), m.group(2), int(m.group(3))
        day, month = (a, b) if a.isdigit() else (b, a)
        if month not in _MONTHS or not 1 <= year <= 9999:
            return None
        try:
            return dt.date(year, _MONTHS.index(month) + 1, int(day))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", w)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # Named days, weekdays and a month-and-day with no year: the next one.
    try:
        return quick._named_date(w, today)
    except Exception:
        return None


def _long(day: dt.date) -> str:
    return day.strftime("%B ") + str(day.day) + day.strftime(", %Y")


def weekday_of(text: str, today: dt.date) -> str | None:
    """"What day is christmas this year", "what day of the week was july 4 1990"."""
    t = " ".join(str(text or "").casefold().split()).rstrip("?. ")
    m = re.fullmatch(r"what day(?: of the week)? (?:is|was|will|does|did|falls|is it on)(?: it)? (.+?)"
                     r"(?: (?:be|fall|land|fall on|land on|on))?", t)
    if not m:
        return None
    day = _date(m.group(1), today)
    if day is None:
        return None
    if day == today:
        return f"Today - {day.strftime('%A')}, {_long(day)}."
    tense = "was" if day < today else "'s"
    return f"It{' ' if tense == 'was' else ''}{tense} a {day.strftime('%A')} - {_long(day)}."


def days_between(text: str, today: dt.date) -> str | None:
    """"How many days between march 1 and april 15", "... from X to Y"."""
    t = " ".join(str(text or "").casefold().split()).rstrip("?. ")
    m = re.fullmatch(r"how many (days|weeks) (?:are there )?(?:between|from) (.+?) (?:and|to|until|till) (.+?)", t)
    if not m:
        return None
    a, b = _date(m.group(2), today), _date(m.group(3), today)
    if a is None or b is None:
        return None
    # "march 1 and april 15", both without a year: the same year, in order.
    no_year = not re.search(r"\d{4}", m.group(2) + " " + m.group(3))
    if no_year and b < a and b.replace(year=a.year) >= a:
        b = b.replace(year=a.year)
    days = abs((b - a).days)
    if m.group(1) == "weeks":
        weeks, rest = divmod(days, 7)
        return f"{weeks} weeks" + (f" and {rest} days" if rest else "") + "."
    return f"{days:,} days."


def time_in(text: str, now: dt.datetime) -> str | None:
    """"What time will it be in 3 hours", "what time is it in 45 minutes"."""
    t = " ".join(str(text or "").casefold().split()).rstrip("?. ")
    m = re.fullmatch(r"what time (?:will it be|is it going to be|would it be|is it) in (?:an? |one )?([\d.]+|half an?|a couple of|two|three|four|five|six|ten|twelve)?"
                     r" ?(hours?|minutes?|mins?)", t)
    if not m:
        return None
    raw = m.group(1)
    n = 1.0 if raw is None else (0.5 if raw.startswith("half") else 2.0 if raw == "a couple of" else _num(raw))
    if n is None or n <= 0 or n > 10_000:
        return None
    delta = dt.timedelta(hours=n) if m.group(2).startswith("hour") else dt.timedelta(minutes=n)
    later = now + delta
    clock = later.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    day = ("" if later.date() == now.date()
           else " tomorrow" if later.date() == now.date() + dt.timedelta(days=1)
           else f" on {later.strftime('%A')}")
    return f"{clock}{day}."


def answer(text: str) -> str | None:
    """Whichever of these the words are, or None."""
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    for attempt in (lambda: arith(text), lambda: kitchen(text),
                    lambda: weekday_of(text, now.date()), lambda: days_between(text, now.date()),
                    lambda: time_in(text, now)):
        try:
            out = attempt()
        except Exception:
            out = None
        if out:
            return out
    return None
