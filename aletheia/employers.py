"""The employers she has met, remembered: name, domains, career pages, ATS.

His words, 2026-09-15: *"find unusually good opportunities wherever employers
publish them, including small companies."* The model case is his own ECG job -
a small South Dakota employer paying well, found on its own site, absent from
every board. Nothing she had remembered employers as such: a board token in
`learned_boards.json`, a company name on an application record, a host in a
web-search cache. Three stores, none of them able to answer "what do you know
about Bechtel?" or "which employers near me have you never crawled?".

This is the durable employer universe the brief asks for (section 3): one row
per employer, in private state (`jobs/employers.json`), upserted from every
place she meets one - a learned board, a Muse lead, an AI search result, a
careers-page crawl, his sent ledger and his application records - and read
back by name or domain.

WHAT A ROW IS. `name`, the domains that are the employer's OWN (never an
applicant-tracking host: boards.greenhouse.io is Greenhouse's, not Acme's),
`career_urls`, the `ats` and board `token` when it has one she can list,
`locations`, `first_seen`, `last_seen`, `last_crawled`, `jobs_seen` (the most
openings any one reading showed), `source`, a `high_value` flag with `notes`.

MATCHING IS IDEMPOTENT. A row is found by a shared domain, then by the same
ATS board, then by a normalised name; the first upsert creates it and every
later one only widens it. Nothing here reaches the network.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.parse

from aletheia import stateio

ACTOR = "aletheia-employers"
MAX_EMPLOYERS = 3000
MAX_DOMAINS = 6
MAX_CAREER_URLS = 8
MAX_LOCATIONS = 12
MAX_NOTES = 400

#: Hosts that are an applicant-tracking system's, a job site's, or a free
#: mailbox's - never an employer's own domain.
_NOT_THEIR_DOMAIN = re.compile(
    r"(?:^|\.)(?:greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|smartrecruiters\.com|"
    r"recruitee\.com|myworkdayjobs\.com|myworkdaysite\.com|workday\.com|icims\.com|taleo\.net|"
    r"successfactors\.(?:com|eu)|jobs\.sap\.com|oraclecloud\.com|ultipro\.com|ukg\.net|"
    r"dayforcehcm\.com|adp\.com|paylocity\.com|paycomonline\.net|brassring\.com|kenexa\.com|"
    r"avature\.net|bamboohr\.com|jazzhr\.com|applytojob\.com|breezy\.hr|rippling\.com|"
    r"pinpointhq\.com|teamtailor\.com|jobvite\.com|applicantpro\.com|hirebridge\.com|"
    r"gmail\.com|yahoo\.com|outlook\.com|hotmail\.com|themuse\.com)$", re.I)

#: The ATS a host belongs to, for a link that is a board or a job on one.
_ATS_HOSTS = (
    ("greenhouse", re.compile(r"(?:^|\.)greenhouse\.io$")),
    ("lever", re.compile(r"(?:^|\.)lever\.co$")),
    ("ashby", re.compile(r"(?:^|\.)ashbyhq\.com$")),
    ("workable", re.compile(r"(?:^|\.)workable\.com$")),
    ("smartrecruiters", re.compile(r"(?:^|\.)smartrecruiters\.com$")),
    ("recruitee", re.compile(r"(?:^|\.)recruitee\.com$")),
    ("workday", re.compile(r"(?:^|\.)(?:myworkdayjobs\.com|myworkdaysite\.com|workday\.com)$")),
    ("icims", re.compile(r"(?:^|\.)icims\.com$")),
    ("taleo", re.compile(r"(?:^|\.)taleo\.net$")),
    ("successfactors", re.compile(r"(?:^|\.)(?:successfactors\.(?:com|eu)|jobs\.sap\.com)$")),
    ("ukg", re.compile(r"(?:^|\.)(?:ultipro\.com|ukg\.net)$")),
    ("dayforce", re.compile(r"(?:^|\.)dayforcehcm\.com$")),
    ("adp", re.compile(r"(?:^|\.)adp\.com$")),
    ("paylocity", re.compile(r"(?:^|\.)paylocity\.com$")),
    ("paycom", re.compile(r"(?:^|\.)paycomonline\.net$")),
    ("bamboohr", re.compile(r"(?:^|\.)bamboohr\.com$")),
    ("jazzhr", re.compile(r"(?:^|\.)(?:jazzhr\.com|applytojob\.com)$")),
    ("breezy", re.compile(r"(?:^|\.)breezy\.hr$")),
    ("rippling", re.compile(r"(?:^|\.)rippling\.com$")),
    ("pinpoint", re.compile(r"(?:^|\.)pinpointhq\.com$")),
    ("teamtailor", re.compile(r"(?:^|\.)teamtailor\.com$")),
    ("jobvite", re.compile(r"(?:^|\.)jobvite\.com$")),
    ("applicantpro", re.compile(r"(?:^|\.)applicantpro\.com$")),
)

_NAME_NOISE = re.compile(
    r"\b(?:inc|llc|ltd|limited|corp|corporation|co|company|plc|gmbh|group|holdings|"
    r"the)\b\.?", re.I)


def path():
    return stateio.private_dir("jobs") / "employers.json"


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(str(url or "")).netloc.casefold().split("@")[-1].split(":")[0]


def domain_of(url_or_host: str) -> str:
    """The employer's registrable-ish domain from a URL or host, or "" when the
    host is an ATS, a job site or not a host at all. `www.` comes off."""
    value = str(url_or_host or "").strip()
    if not value:
        return ""
    host = host_of(value) if "//" in value else value.casefold().split("/")[0]
    host = host.strip().strip(".")
    if not host or " " in host or "." not in host or _NOT_THEIR_DOMAIN.search(host):
        return ""
    if re.fullmatch(r"[\d.]+", host):
        return ""
    return re.sub(r"^www\.", "", host)


def ats_of(url: str) -> str:
    """Which applicant-tracking system a link belongs to, or ""."""
    host = host_of(url)
    for name, pattern in _ATS_HOSTS:
        if host and pattern.search(host):
            return name
    return ""


def name_key(name: str) -> str:
    """"The Acme Corp., Inc." and "acme corp" are one employer."""
    low = _NAME_NOISE.sub(" ", str(name or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+", low))


def _clean_name(name) -> str:
    name = " ".join(str(name or "").split())[:80]
    return "" if re.search(r"(?:\.\.\.|…)\s*$", name) else name


def _load() -> dict:
    try:
        value = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = value.get("employers") if isinstance(value, dict) else None
    return rows if isinstance(rows, dict) else {}


def _save(rows: dict) -> None:
    if len(rows) > MAX_EMPLOYERS:
        # The oldest-seen go first; what she met last week matters more than
        # a name a search engine mentioned in June.
        keep = sorted(rows.items(), key=lambda kv: str(kv[1].get("last_seen") or ""))
        rows = dict(keep[-MAX_EMPLOYERS:])
    stateio.write_json_atomic(path(), {"employers": rows})


def all_rows() -> list[dict]:
    return list(_load().values())


def _find(rows: dict, *, domains: list[str], ats: str, token: str, name: str) -> str:
    for key, row in rows.items():
        if domains and set(domains) & set(row.get("domains") or []):
            return key
    if ats and token:
        for key, row in rows.items():
            if row.get("ats") == ats and str(row.get("token") or "").casefold() == token.casefold():
                return key
    if name:
        wanted = name_key(name)
        if wanted:
            for key, row in rows.items():
                if name_key(row.get("name")) == wanted or wanted in (row.get("aliases") or []):
                    return key
    return ""


def _merge_list(row: dict, field: str, values, cap: int) -> None:
    have = list(row.get(field) or [])
    for value in values:
        value = str(value or "").strip()
        if value and value not in have:
            have.append(value)
    row[field] = have[-cap:]


def upsert(*, name: str = "", domain: str = "", url: str = "", career_url: str = "",
           ats: str = "", token: str = "", location: str = "", source: str = "",
           jobs_seen: int | None = None, high_value: bool | None = None, note: str = "",
           crawled: bool = False, now: str = "") -> dict:
    """Remember one employer, or widen what is remembered. Idempotent.

    `url` may be any address on the employer's site or on its ATS: the domain,
    the ATS and often the token are read off it. Returns the row.
    """
    rows = _load()
    row = _upsert_into(rows, name=name, domain=domain, url=url, career_url=career_url, ats=ats,
                       token=token, location=location, source=source, jobs_seen=jobs_seen,
                       high_value=high_value, note=note, crawled=crawled, now=now)
    _save(rows)
    return dict(row)


def _upsert_into(rows: dict, *, name: str = "", domain: str = "", url: str = "",
                 career_url: str = "", ats: str = "", token: str = "", location: str = "",
                 source: str = "", jobs_seen: int | None = None, high_value: bool | None = None,
                 note: str = "", crawled: bool = False, now: str = "") -> dict:
    """`upsert` against rows already in hand; the caller saves."""
    now = now or stateio.utcnow()
    name = _clean_name(name)
    domains = [d for d in (domain_of(domain), domain_of(url), domain_of(career_url)) if d]
    ats = str(ats or "").strip().casefold() or ats_of(url) or ats_of(career_url)
    token = str(token or "").strip()
    if not token and ats:
        try:
            from aletheia import jobs
            matched = jobs.job_from_url(url) or jobs.job_from_url(career_url)
            if matched and matched[0].provider == ats:
                token = matched[1]
        except Exception:
            token = ""
    if not (name or domains or (ats and token)):
        raise ValueError("an employer needs a name, a domain or a board")
    key = _find(rows, domains=domains, ats=ats, token=token, name=name)
    if not key:
        key = domains[0] if domains else (f"{ats}:{token}".casefold() if ats and token
                                          else name_key(name))
        if key in rows:
            key = f"{key}#{len(rows)}"
        rows[key] = {"name": name or (domains[0] if domains else token), "domains": [],
                     "career_urls": [], "ats": "", "token": "", "locations": [],
                     "first_seen": now, "last_seen": now, "last_crawled": "",
                     "jobs_seen": 0, "source": source, "high_value": False, "notes": "",
                     "aliases": []}
    row = rows[key]
    if name and not row.get("name"):
        row["name"] = name
    elif name and name_key(name) != name_key(row.get("name")):
        _merge_list(row, "aliases", [name_key(name)], 8)
    _merge_list(row, "domains", domains, MAX_DOMAINS)
    if career_url:
        _merge_list(row, "career_urls", [career_url], MAX_CAREER_URLS)
    if ats and not row.get("ats"):
        row["ats"] = ats
    if token and (not row.get("token") or row.get("ats") == ats):
        row["token"] = token
    if location:
        _merge_list(row, "locations", [" ".join(str(location).split())[:80]], MAX_LOCATIONS)
    if jobs_seen is not None:
        row["jobs_seen"] = max(int(row.get("jobs_seen") or 0), int(jobs_seen))
    if high_value is not None:
        row["high_value"] = bool(high_value)
    if note:
        row["notes"] = (" ".join(str(note).split()) + (" | " + row["notes"] if row.get("notes") else ""))[:MAX_NOTES]
    if crawled:
        row["last_crawled"] = now
    if source and not row.get("source"):
        row["source"] = source
    row["last_seen"] = now
    return row


def remember_jobs(jobs_found: list[dict], *, source: str = "", now: str = "") -> int:
    """Every employer behind a list of openings in `jobs.search_many`'s shape.

    A board opening names its ATS and token; a company-site one names the
    employer's own host in `posting_url`. Never raises: memory that cannot be
    written costs a memory, not the search.
    """
    seen, count = set(), 0
    try:
        from aletheia import jobs as _jobs
        listable = set(_jobs.PROVIDERS)
    except Exception:
        listable = set()
    try:
        rows = _load()
        for job in jobs_found or []:
            if not isinstance(job, dict):
                continue
            company = _clean_name(job.get("company"))
            provider = str(job.get("provider") or "")
            listed = provider in listable
            token = str(job.get("board") or "") if listed else ""
            posting = str(job.get("posting_url") or "")
            marker = (company.casefold(), provider, token, domain_of(posting))
            if marker in seen or not (company or domain_of(posting) or token):
                continue
            seen.add(marker)
            try:
                _upsert_into(rows, name=company, url=posting,
                             career_url=posting if domain_of(posting) else "",
                             ats=provider if listed else ats_of(posting), token=token,
                             location=str(job.get("location") or "")[:80],
                             source=source or str(job.get("found_by") or "a board"), now=now)
                count += 1
            except Exception:
                continue
        if count:
            _save(rows)
    except Exception:
        return count
    return count


def seed_from_records(*, now: str = "") -> int:
    """Employers already in her other stores: learned boards, the sent ledger,
    every application record. Run once; idempotent after that."""
    count = 0
    try:
        from aletheia import jobs as _jobs
        for board in _jobs.boards():
            try:
                upsert(name=str(board.get("company") or ""), ats=str(board.get("provider") or ""),
                       token=str(board.get("token") or ""),
                       source="a learned board" if board.get("learned") else "a configured board",
                       now=now)
                count += 1
            except Exception:
                continue
    except Exception:
        pass
    try:
        from aletheia import apply_run
        rows = list(apply_run.already_sent().values())
        try:
            rows += apply_run.all_runs()
        except Exception:
            pass
        for record in rows:
            if not isinstance(record, dict):
                continue
            company = _clean_name(record.get("company"))
            posting = str(record.get("posting") or "")
            url = str(record.get("url") or "")
            if not company and not domain_of(posting):
                continue
            try:
                upsert(name=company, url=posting or url, career_url=posting if domain_of(posting) else "",
                       source="an application on record", now=now)
                count += 1
            except Exception:
                continue
    except Exception:
        pass
    return count


def about(name_or_domain: str) -> dict | None:
    """What she knows about one employer, by name or by domain. None when nothing."""
    wanted = str(name_or_domain or "").strip()
    if not wanted:
        return None
    rows = _load()
    domain = domain_of(wanted) or (wanted.casefold() if "." in wanted else "")
    key = _find(rows, domains=[domain] if domain else [], ats="", token="", name=wanted)
    if not key:
        # A word of the name is enough when it names one employer.
        needle = name_key(wanted)
        hits = [k for k, r in rows.items() if needle and needle in name_key(r.get("name"))]
        key = hits[0] if len(hits) == 1 else ""
    return dict(rows[key]) if key else None


def stale(days: float = 1.0, *, now: dt.datetime | None = None) -> list[dict]:
    """Employers with a domain or a career page that has not been crawled within `days`."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for row in _load().values():
        if not (row.get("domains") or row.get("career_urls")):
            continue
        last = str(row.get("last_crawled") or "")
        try:
            when = dt.datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        except ValueError:
            when = None
        if when is None or (now - when) >= dt.timedelta(days=days):
            out.append(dict(row))
    out.sort(key=lambda r: (str(r.get("last_crawled") or ""), str(r.get("first_seen") or "")))
    return out


def new_since(stamp: str) -> list[dict]:
    """Employers first met at or after an ISO timestamp (a day's "YYYY-MM-DD" works)."""
    return [dict(r) for r in _load().values() if str(r.get("first_seen") or "") >= str(stamp)]


def describe(row: dict) -> str:
    """One employer, said the way she would say it to him."""
    name = row.get("name") or (row.get("domains") or ["an employer"])[0]
    bits = []
    if row.get("domains"):
        bits.append(f"its site is {row['domains'][0]}")
    if row.get("ats"):
        bits.append(f"it hires through {row['ats'].capitalize()}" +
                    (f" (board {row['token']})" if row.get("token") else ""))
    elif row.get("career_urls"):
        bits.append("it posts jobs on its own careers page")
    if row.get("locations"):
        bits.append("in " + ", ".join(row["locations"][:3]))
    if row.get("jobs_seen"):
        bits.append(f"{row['jobs_seen']} openings the last time I looked")
    when = str(row.get("last_crawled") or "")[:10]
    bits.append(f"last crawled {when}" if when else "never crawled")
    if row.get("high_value"):
        bits.append("marked high value")
    line = f"{name}: " + "; ".join(bits) + "."
    if row.get("notes"):
        line += f" Notes: {row['notes']}"
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The employers she has met.")
    ap.add_argument("name", nargs="?", help="an employer's name or domain")
    ap.add_argument("--seed", action="store_true", help="remember employers from her other stores")
    ap.add_argument("--stale", action="store_true", help="those not crawled in a day")
    args = ap.parse_args(argv)
    if args.seed:
        print(f"{seed_from_records()} employers remembered from boards and records")
        return 0
    if args.name:
        row = about(args.name)
        if row is None:
            print(f"I have not met {args.name}.")
            return 1
        print(describe(row))
        return 0
    rows = stale() if args.stale else all_rows()
    for row in sorted(rows, key=lambda r: str(r.get("name") or "").casefold()):
        print(f"{str(row.get('name') or '')[:30]:30} {(row.get('domains') or [''])[0][:30]:30} "
              f"{row.get('ats') or 'custom':14} {row.get('jobs_seen', 0):>4} open  "
              f"{str(row.get('last_crawled') or 'never')[:10]}")
    print(f"\n{len(rows)} employers", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
