"""What an opening is WORTH to him, from facts, with the reasons written down.

The brief (section 3): *"Score for value, not keyword similarity: role/skill
fit, realistic seniority, compensation, geography/remote, employer quality,
advancement, unusual pay for local cost of living, recency, ease; minus
over/under qualification, missing credentials, travel mismatch, pay below
floor, duplicates, scam risk. Deterministic facts stay deterministic; the
model handles fuzzy fit. Keep two queues: best-fit and interesting outliers."*

Until now the campaign tried openings in the order `jobs._score` sorted them -
a title-overlap number between 0 and 1.5 - and everything else it knew (pay,
place, a bot check, an account wall, an employer it had met) either decided
yes-or-no later or decided nothing. So a $70,000 job in Dublin behind a
Workday login and a $110,000 job on a Sioux Falls employer's own site with a
public form were the same 1.0.

This scores a job from what is ON the record - the title, the place, the pay
a posting lists or a JobPosting declares, the date, the system it applies
through, what `employers` remembers about the employer, what `job_fit`'s
rules say he cannot honestly claim - and writes every reason on the record as
`why_she_liked_it` so the UI can answer "why this one?". The MODEL judges only
the fuzzy part ("different title, same work"), through `job_fit.judge` as
before; nothing here calls one.

COST OF LIVING is a coarse, built-in, state-level index (US average = 100)
with a few metros above their state, rounded to fives and approximated from
the published 2024 state indexes (MERIC / BEA regional price parities). It is
deliberately rough: it exists to tell a $95,000 job in Sioux Falls from a
$95,000 job in San Francisco, not to price either. Say so when you quote it.

An OUTLIER is a job whose pay, adjusted by that index, is well above his floor
in a market where that is unusual, or a small employer (few openings, its own
careers page) paying at or above his floor - the ECG shape. Outliers rank UP:
the score carries a bonus, and the queue says why.
"""
from __future__ import annotations

import datetime as dt
import re

ACTOR = "aletheia-job-value"

#: Coarse cost-of-living index by state (US = 100). See the module docstring.
STATE_INDEX = {
    "AL": 88, "AK": 125, "AZ": 108, "AR": 89, "CA": 138, "CO": 105, "CT": 113, "DE": 101,
    "FL": 103, "GA": 91, "HI": 185, "ID": 102, "IL": 92, "IN": 91, "IA": 90, "KS": 87,
    "KY": 93, "LA": 92, "ME": 112, "MD": 116, "MA": 146, "MI": 91, "MN": 95, "MS": 86,
    "MO": 89, "MT": 103, "NE": 93, "NV": 101, "NH": 114, "NJ": 114, "NM": 94, "NY": 125,
    "NC": 97, "ND": 92, "OH": 94, "OK": 86, "OR": 115, "PA": 97, "RI": 112, "SC": 97,
    "SD": 93, "TN": 91, "TX": 93, "UT": 103, "VT": 115, "VA": 101, "WA": 116, "WV": 88,
    "WI": 97, "WY": 95, "DC": 145,
}
#: Metros priced above their state. Matched as words in the location.
METRO_INDEX = (
    (re.compile(r"\b(?:new york|nyc|manhattan|brooklyn)\b", re.I), 175, "New York"),
    (re.compile(r"\b(?:san francisco|bay area|palo alto|mountain view|san jose|menlo park|oakland)\b", re.I),
     180, "the Bay Area"),
    (re.compile(r"\bseattle\b", re.I), 130, "Seattle"),
    (re.compile(r"\bboston\b", re.I), 150, "Boston"),
    (re.compile(r"\blos angeles\b", re.I), 150, "Los Angeles"),
    (re.compile(r"\bsan diego\b", re.I), 145, "San Diego"),
    (re.compile(r"\bwashington,? d\.?c\.?\b", re.I), 145, "Washington, DC"),
    (re.compile(r"\bchicago\b", re.I), 105, "Chicago"),
    (re.compile(r"\bdenver\b", re.I), 110, "Denver"),
    (re.compile(r"\bmiami\b", re.I), 115, "Miami"),
    (re.compile(r"\bhonolulu\b", re.I), 185, "Honolulu"),
)
#: An opening that pays more than this many times his floor is not a job.
SCAM_PAY_MULTIPLE = 4.0
SCAM_PAY_ABSOLUTE = 400_000
_SCAM_WORDS = re.compile(
    r"wire transfer|western union|moneygram|training fee|processing fee|pay to apply|"
    r"application fee|starter kit|cashier'?s? check|reshipping|package (?:handler|forwarding) from home|"
    r"earn \$?\d[\d,]* (?:a|per) (?:day|week) from home|no experience.{0,20}\$\d{3},\d{3}", re.I)
_EARLY_TITLE = re.compile(r"\b(?:intern|internship|entry[- ]level|trainee|junior|jr\.?)\b", re.I)
_SMALL_EMPLOYER_MAX_OPENINGS = 30
OUTLIER_BONUS = 8
BEST_FIT_MIN = 45
OUTLIER_MIN = 40


def col_index(location: str) -> tuple[int, str]:
    """(index, what it is for) from a location string. 100 and "" when it cannot tell."""
    loc = " ".join(str(location or "").split())
    if not loc:
        return 100, ""
    for pattern, value, label in METRO_INDEX:
        if pattern.search(loc):
            return value, label
    try:
        from aletheia.formfill import US_STATE_NAMES
    except Exception:
        US_STATE_NAMES = {}
    low = loc.casefold()
    for code, name in US_STATE_NAMES.items():
        if re.search(r"\b" + re.escape(name.casefold()) + r"\b", low):
            return STATE_INDEX.get(code, 100), name
    for code in STATE_INDEX:
        if re.search(r"(?:,|\b)\s*" + code + r"(?![-\w])", loc):
            return STATE_INDEX[code], code
    return 100, ""


def pay_floor(known: dict | None, location: str = "") -> float:
    """His minimum for a job in this place, from `desired_pay` in his words: the
    first figure for anywhere or remote, the lowest for a job in his own state."""
    known = known or {}
    try:
        from aletheia.formfill import _amounts
        amounts = [a for a in _amounts(str(known.get("desired_pay") or "")) if a >= 1000]
    except Exception:
        amounts = []
    if not amounts:
        return 0.0
    if _in_his_state(location, known):
        return min(amounts)
    return amounts[0]


def _in_his_state(location: str, known: dict | None) -> bool:
    known = known or {}
    state = str(known.get("state") or "").strip()
    if not state or not location:
        return False
    try:
        from aletheia.formfill import US_STATE_NAMES
        name = US_STATE_NAMES.get(state.upper(), state)
    except Exception:
        name = state
    low = str(location).casefold()
    if re.search(r"\b" + re.escape(name.casefold()) + r"\b", low):
        return True
    return bool(re.search(r"(?:,|\b)\s*" + re.escape(state.upper()) + r"(?![-\w])", str(location)))


def annual_pay(job: dict, text: str = "") -> tuple[float, float] | None:
    """(low, high) a year, from a JobPosting's baseSalary on the record or the
    posting's own text. None when neither says."""
    pay = job.get("salary")
    if isinstance(pay, (list, tuple)) and len(pay) == 2:
        try:
            low, high = float(pay[0]), float(pay[1])
        except (TypeError, ValueError):
            low = high = None
        if low is not None:
            unit = str(job.get("salary_unit") or "YEAR").upper()
            times = {"HOUR": 2080, "DAY": 260, "WEEK": 52, "MONTH": 12}.get(unit, 1)
            if unit == "YEAR" and high < 1000:            # "$95k" written as 95
                times = 1000
            low, high = low * times, high * times
            if 10_000 <= low <= high:
                return low, high
    if text:
        try:
            from aletheia.campaign import listed_pay_ranges
            ranges = listed_pay_ranges(text)
        except Exception:
            ranges = []
        if ranges:
            return min(r[0] for r in ranges), max(r[1] for r in ranges)
    return None


def _days_old(stamp: str, now: dt.datetime) -> int | None:
    stamp = str(stamp or "").strip()
    if not stamp:
        return None
    try:
        when = dt.datetime.fromisoformat(stamp[:19].replace("Z", ""))
    except ValueError:
        return None
    return (now.replace(tzinfo=None) - when).days


def _title_of(job: dict) -> str:
    from aletheia import job_fit
    return job_fit.bare_title(job.get("job_title") or job.get("title") or "", job.get("company") or "")


def score(job: dict, *, known: dict | None = None, resume_text: str = "", text: str = "",
          early: bool | None = None, employer: dict | None = None, taken: bool = False,
          risky: set | None = None, now: dt.datetime | None = None) -> dict:
    """{"value": int, "queue": "best-fit" | "outlier" | "", "why_she_liked_it": [...],
    "why_not": [...], "facts": {...}} for one opening, from facts alone.

    `job` is a campaign page or an application record. `text` is the posting's
    text when someone has read it; `employer` is what `employers` remembers
    (looked up by company name when not given); `taken` says the same role is
    already sent or waiting; `risky` names systems whose forms a CAPTCHA has
    held (`apply_run.captcha_risky_providers`).
    """
    from aletheia import job_fit, jobs
    known = known or {}
    now = now or dt.datetime.now(dt.timezone.utc)
    title = _title_of(job)
    location = " ".join(str(job.get("location") or "").split())
    liked, not_liked = [], []
    value = 0.0
    facts: dict = {}

    # Role fit, as the search scored it (0 to 1.5).
    try:
        fit = float(job.get("score") or 0)
    except (TypeError, ValueError):
        fit = 0.0
    fit_pts = min(30.0, 20.0 * fit)
    value += fit_pts
    if fit_pts >= 20:
        liked.append("the title fits the work you asked for")
    elif fit_pts > 0:
        liked.append("the title is close to the work you asked for")

    # Seniority.
    words = jobs._title_words(title)
    if early is None:
        try:
            from aletheia.campaign import _seniority_to_leave_out
            early = bool(_seniority_to_leave_out(known))
        except Exception:
            early = False
    if words & jobs.SENIOR_TITLE_WORDS or jobs._MANAGES_PEOPLE.search(title):
        value -= 15
        not_liked.append("a senior or people-managing title")
    elif early and words & {"associate", "coordinator", "specialist", "analyst", "representative"}:
        value += 4
        liked.append("a level you can honestly claim")
    try:
        years = float(known.get("years_experience") or 0)
    except (TypeError, ValueError):
        years = 0.0
    if _EARLY_TITLE.search(title) and years >= 5:
        value -= 10
        not_liked.append("an entry-level title for someone with your years")

    # Pay, and pay against where the job is.
    floor = pay_floor(known, location)
    pay = annual_pay(job, text)
    index, market = col_index(location)
    facts.update({"floor": floor, "pay": list(pay) if pay else None, "col_index": index})
    small_market_high_pay = False
    if pay:
        low, high = pay
        mid = (low + high) / 2
        if floor and high < floor:
            value -= 25
            not_liked.append(f"pays below your ${floor:,.0f} floor (${low:,.0f} to ${high:,.0f})")
        elif floor and mid >= floor:
            value += 12
            liked.append(f"pays ${low:,.0f} to ${high:,.0f}, at or above your floor")
        elif floor:
            value += 4
            liked.append(f"the top of its range (${high:,.0f}) reaches your floor")
        else:
            liked.append(f"lists its pay: ${low:,.0f} to ${high:,.0f}")
        adjusted = mid / (index / 100.0)
        if floor and index <= 100 and adjusted >= 1.3 * floor:
            small_market_high_pay = True
            value += 10
            liked.append(f"unusually good pay for {market or 'that market'}: about ${adjusted:,.0f} "
                         "in national terms, on a rough cost-of-living index")
        top_limit = max(SCAM_PAY_ABSOLUTE, SCAM_PAY_MULTIPLE * floor) if floor else SCAM_PAY_ABSOLUTE
        if high > top_limit and not (words & {"director", "vp", "chief", "head", "physician", "surgeon"}):
            value -= 30
            not_liked.append(f"pay far above what this title plausibly earns (${high:,.0f})")

    # Geography.
    relocate = str(known.get("willing_to_relocate") or "").strip().casefold() in ("yes", "y", "true", "1")
    if location:
        low_loc = location.casefold()
        if _in_his_state(location, known):
            value += 10
            liked.append(f"in {known.get('state') or 'your state'}")
            city = str(known.get("city") or "").casefold()
            if city and city in low_loc:
                value += 2
        elif "remote" in low_loc or "anywhere" in low_loc:
            value += 8
            liked.append("remote")
        elif jobs._in_country(location, "United States"):
            if relocate:
                value += 3
                liked.append(f"in {location}, and you said you would relocate")
            else:
                value -= 6
                not_liked.append(f"in {location}, and you have not said you would move")
        else:
            value -= 40
            not_liked.append(f"outside the United States ({location})")

    # Employer quality, from what she has measured.
    if employer is None:
        try:
            from aletheia import employers as _employers
            employer = _employers.about(str(job.get("company") or "")) if job.get("company") else None
        except Exception:
            employer = None
    seen = int((employer or {}).get("jobs_seen") or 0)
    small_employer = False
    if employer:
        if 0 < seen <= _SMALL_EMPLOYER_MAX_OPENINGS:
            value += 4
            small_employer = True
            liked.append(f"a small employer ({seen} openings when I last looked)")
        elif seen:
            value += 2
        if employer.get("high_value"):
            value += 8
            liked.append("an employer you marked high value")
    provider = str(job.get("provider") or "")
    if provider == "company site":
        value += 2
        small_employer = small_employer or seen == 0
        liked.append("posted on the employer's own site")

    # Recency.
    age = _days_old(str(job.get("posted") or ""), now)
    if age is not None:
        if age <= 7:
            value += 6
            liked.append("posted this week")
        elif age <= 30:
            value += 3
        elif age > 90:
            value -= 6
            not_liked.append(f"posted {age} days ago")

    # Ease.
    if job.get("needs_account") or provider == "account site":
        value -= 8
        not_liked.append("the employer's site wants an account first")
    elif job.get("direct", True):
        value += 6
        liked.append("a public application form")
    if risky and provider in risky:
        value -= 4
        not_liked.append("a system whose forms a CAPTCHA has held before")
    if job.get("unverified"):
        value -= 3

    # Hard rules: what he cannot honestly claim, what he will not do.
    try:
        why = job_fit.hard_reason(title, text, resume_text=resume_text, known=known, early=bool(early))
    except Exception:
        why = ""
    if why:
        value -= 50
        not_liked.append(why.replace("he ", "you ").replace("him", "you").replace("his ", "your "))
    kind = job_fit.employment_type(title, text)
    if kind:
        value -= 8
        not_liked.append(f"{kind} work")
        facts["employment"] = kind
    if taken:
        value -= 60
        not_liked.append("the same job is already sent or waiting")
    if _SCAM_WORDS.search(text or ""):
        value -= 40
        not_liked.append("the posting reads like a scam (fees, wires, or too-good pay)")
    try:
        from aletheia import company_sites
        posting_url = str(job.get("posting") or job.get("posting_url") or job.get("url") or "")
        if not company_sites.host_of(posting_url) or company_sites.is_aggregator(posting_url):
            value -= 20
            not_liked.append("no employer address behind it")
    except Exception:
        pass

    queue = ""
    hard_no = bool(why) or taken
    if not hard_no and (small_market_high_pay or (small_employer and pay and floor and pay[1] >= floor)):
        if value >= OUTLIER_MIN:
            queue = "outlier"
            value += OUTLIER_BONUS
            liked.append("an interesting outlier: unusual pay or a small employer few would find")
    if not queue and not hard_no and value >= BEST_FIT_MIN and fit_pts >= 20:
        queue = "best-fit"
    return {"value": int(round(value)), "queue": queue, "why_she_liked_it": liked,
            "why_not": not_liked, "facts": facts}


def rank(pages: list[dict], *, known: dict | None = None, resume_text: str = "",
         describe=None, read_limit: int = 20, taken=None, risky: set | None = None,
         now: dt.datetime | None = None, employer_of=None) -> list[dict]:
    """Every page scored, the score and reasons written on it, best first.

    Two passes: everything from facts on the page, then the top `read_limit`
    again with their posting text (`describe(page)`) so pay and requirements
    count where they can be read. Stable, so pages the scoring cannot tell
    apart keep the order they came in (`campaign.captcha_later`'s).
    """
    known = known or {}
    pages = list(pages or [])
    try:
        from aletheia.campaign import _seniority_to_leave_out
        early = bool(_seniority_to_leave_out(known))
    except Exception:
        early = False
    if risky is None:
        try:
            from aletheia import apply_run
            risky = apply_run.captcha_risky_providers()
        except Exception:
            risky = set()

    def held(page: dict) -> bool:
        if taken is None:
            return False
        try:
            return bool(taken(page.get("company", ""), _title_of(page), page.get("url", "")))
        except Exception:
            return False

    def one(page: dict, text: str) -> None:
        said = score(page, known=known, resume_text=resume_text, text=text, early=early,
                     employer=(employer_of(page) if employer_of else None), taken=held(page),
                     risky=risky, now=now)
        page["value"] = said["value"]
        page["queue"] = said["queue"]
        page["why_she_liked_it"] = said["why_she_liked_it"]
        page["why_not"] = said["why_not"]
        page["value_facts"] = said["facts"]

    for page in pages:
        one(page, str(page.get("description") or ""))
    pages.sort(key=lambda p: -int(p.get("value") or 0))
    if describe is not None:
        for page in pages[:max(0, int(read_limit))]:
            try:
                text = str(describe(page) or "")
            except Exception:
                text = ""
            if text:
                one(page, text)
        pages.sort(key=lambda p: -int(p.get("value") or 0))
    return pages


def why(page: dict) -> str:
    """"Why this one?" in one sentence, from what the ranking wrote on it."""
    from aletheia import speech
    liked = list(page.get("why_she_liked_it") or [])
    not_liked = list(page.get("why_not") or [])
    if not liked and not not_liked:
        return "I have not scored it yet."
    line = ""
    if liked:
        line = "I liked it because " + speech.and_list(liked[:4])
    if not_liked:
        line += ("; against it, " if line else "Against it, ") + speech.and_list(not_liked[:3])
    return line + "."
