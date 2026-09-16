"""A shallow, polite crawl of one employer's own site for where it posts jobs.

The brief (section 3): *"Shallow polite career-site crawling: careers/jobs
paths, sitemaps, external ATS links, JSON-LD JobPosting. Extraction ladder:
official ATS API -> JobPosting structured data -> known ATS adapter -> generic
DOM -> local-model extraction -> vision only if required."*

His ECG job was on a small South Dakota employer's own site and on no board.
Everything before this needed a LISTING to point at the employer (The Muse, an
AI search result); nothing could start from a domain she already knew and ask
the site itself. This does, from a known domain:

  homepage -> the Careers / Jobs / Join Us / Employment link, the likely paths
  (/careers, /jobs, ...), the sitemap's career-shaped addresses; on each of
  those, schema.org JobPosting objects, links out to an applicant-tracking
  system (learned as a board when it is one she can list), and links whose
  text and path look like one job.

THE LADDER, in `openings`: an ATS feed she can list beats structured data,
which beats a known ATS page, which beats a job-shaped link. A row says which
rung it came from (`extracted_by`), and a job-shaped link is `unverified` -
its title is the link text, and the campaign's own page walk decides the
rest. The model-extraction rung is NOT built: nothing here asks a model.

POLITE. robots.txt is read first and its Disallow lines for everyone (and for
her own agent name) are honoured for every path crawled; no host is hit more
than once every MIN_GAP_S; a crawl reads at most MAX_PAGES pages; a bot check
in front of the site ends the crawl and says so; a job aggregator is never
crawled at all; and an employer crawled within RECRAWL_AFTER is left alone
(`employers.last_crawled`), so a batch that runs all day does not read the
same eight pages all day. Nothing here spends money.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse

from aletheia import company_sites, employers

ACTOR = "aletheia-career-sites"
FOUND_BY = "employer crawl"
FOUND_ON = "the employer's own careers page"
AGENT_NAME = "aletheia"

MAX_PAGES = 8
MAX_SITEMAP_URLS = 5
MAX_JOB_LINKS = 40
MIN_GAP_S = 1.5
RECRAWL_AFTER = dt.timedelta(days=1)
#: Employers crawled in one batch. Each is up to MAX_PAGES polite fetches.
MAX_EMPLOYERS_PER_BATCH = 6
DESCRIPTION_CHARS = 4000

LIKELY_PATHS = ("/careers", "/careers/", "/jobs", "/jobs/", "/join-us", "/join",
                "/employment", "/about/careers", "/company/careers", "/work-with-us",
                "/opportunities", "/openings")
_CAREER_TEXT = re.compile(
    r"\b(?:careers?|jobs?|join (?:us|our team|the team)|employment|work (?:with|for) us|"
    r"open(?:ings| positions| roles)|opportunities|we(?:'|’)re hiring|now hiring|vacancies)\b",
    re.I)
_CAREER_PATH = re.compile(
    r"/(?:careers?|jobs?|join(?:-?us)?|employment|work-with-us|opportunities|openings|"
    r"positions|vacancies|recruit(?:ing|ment))(?:/|$|\?|\.|-)", re.I)
_A_TAG = re.compile(r"""<a\b[^>]*?href\s*=\s*(["'])(.*?)\1[^>]*>(.*?)</a>""", re.S | re.I)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S | re.I)
_SITEMAP_LINE = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.I | re.M)
#: A link whose text is a job: a few words, one of them the name of a kind of
#: work. Nav words ("View all jobs", "Careers") are not.
_ROLE_WORD = re.compile(
    r"\b(?:manager|specialist|analyst|engineer|associate|coordinator|representative|rep|"
    r"director|technician|nurse|assistant|developer|accountant|administrator|consultant|"
    r"designer|officer|clerk|agent|advisor|adviser|lead|supervisor|planner|buyer|"
    r"scientist|architect|operator|mechanic|driver|teacher|instructor|therapist|"
    r"pharmacist|physician|attorney|paralegal|recruiter|controller|bookkeeper|"
    r"executive|partner|success|development|operations|sales|marketing|support|"
    r"intern|apprentice|trainee)\b", re.I)
_NAV_TEXT = re.compile(
    r"^(?:view|see|browse|search|all|open|current|apply|learn more|read more|careers?|jobs?|"
    r"openings?|positions?|opportunities|home|back|next|previous|more)\b[\w\s]*$", re.I)
#: A job-shaped link on the employer's own site: a job path, or a query id.
_JOB_HREF = re.compile(r"/(?:jobs?|careers?|positions?|openings?|opportunit(?:y|ies)|"
                       r"requisitions?|vacanc(?:y|ies)|job-details?|jobdetails?)(?:/|-|\?|\.)"
                       r"|[?&](?:gh_jid|jobid|job_id|jid|reqid|req|id|posting)=", re.I)
#: Board-level ATS addresses (no job id): the employer's whole board.
_BOARD_URL = (
    ("greenhouse", re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9_-]+)/?(?:[?#]|$)")),
    ("greenhouse", re.compile(r"https?://boards\.greenhouse\.io/embed/job_board\?for=([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"https?://jobs\.lever\.co/([A-Za-z0-9_.-]+)/?(?:[?#]|$)")),
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)/?(?:[?#]|$)")),
    ("workable", re.compile(r"https?://apply\.workable\.com/([A-Za-z0-9_.-]+)/?(?:[?#]|$)")),
    ("smartrecruiters", re.compile(r"https?://(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_.-]+)/?(?:[?#]|$)")),
    ("recruitee", re.compile(r"https?://([a-z0-9-]+)\.recruitee\.com/?(?:[?#]|$)")),
)

_last_hit: dict[str, float] = {}


class CrawlStopped(RuntimeError):
    """The site cannot be crawled politely: a bot check, or robots says no."""


# ---- politeness -------------------------------------------------------------------

def _wait_turn(host: str, *, sleeper=time.sleep, clock=time.monotonic) -> None:
    last = _last_hit.get(host)
    now = clock()
    if last is not None and now - last < MIN_GAP_S:
        sleeper(MIN_GAP_S - (now - last))
    _last_hit[host] = clock()


def robots_rules(robots_txt: str, agent: str = AGENT_NAME) -> dict:
    """{"disallow": [paths], "sitemaps": [urls]} for everyone plus `agent`.

    The group for `*` and the group naming her agent both apply - a site that
    forbids everyone is not asked, and one that names her by name is obeyed.
    An `Allow:` more specific than a `Disallow:` is honoured the usual way.
    """
    disallow, allow, sitemaps = [], [], _SITEMAP_LINE.findall(str(robots_txt or ""))
    applies = False
    for raw in str(robots_txt or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _sep, value = line.partition(":")
        field, value = field.strip().casefold(), value.strip()
        if field == "user-agent":
            applies = value == "*" or agent.casefold() in value.casefold()
        elif applies and field == "disallow" and value:
            disallow.append(value)
        elif applies and field == "allow" and value:
            allow.append(value)
    return {"disallow": disallow, "allow": allow, "sitemaps": sitemaps}


def _rule_matches(rule: str, path: str) -> bool:
    pattern = re.escape(rule).replace(r"\*", ".*")
    if pattern.endswith(r"\$"):
        pattern = pattern[:-2] + "$"
    return re.match(pattern, path) is not None


def allowed(url: str, rules: dict | None) -> bool:
    if not rules:
        return True
    path = urllib.parse.urlsplit(str(url or "")).path or "/"
    longest_deny = max((len(r) for r in rules.get("disallow", []) if _rule_matches(r, path)), default=-1)
    longest_allow = max((len(r) for r in rules.get("allow", []) if _rule_matches(r, path)), default=-1)
    return longest_deny < 0 or longest_allow >= longest_deny


# ---- reading pages ------------------------------------------------------------------

def _links(page_html: str, base: str) -> list[tuple[str, str]]:
    """(absolute href, visible text) for every <a> on the page."""
    out = []
    for _q, href, inner in _A_TAG.findall(str(page_html or "")):
        href = html.unescape(href).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(inner)).split())[:160]
        try:
            out.append((urllib.parse.urljoin(base, href).split("#")[0], text))
        except ValueError:
            continue
    return out


def _same_site(url: str, domain: str) -> bool:
    host = company_sites.host_of(url)
    return host == domain or host.endswith("." + domain)


def _career_links(links: list[tuple[str, str]], domain: str) -> list[str]:
    out = []
    for href, text in links:
        if not _same_site(href, domain) or company_sites._NOT_A_PAGE.search(href):
            continue
        path = urllib.parse.urlsplit(href).path or ""
        if _CAREER_TEXT.search(text) or _CAREER_PATH.search(path):
            out.append(href)
    return list(dict.fromkeys(out))


def _ats_links(links: list[tuple[str, str]], page_html: str) -> tuple[list[dict], list[str]]:
    """(board or job links on a system she can list, links to account systems)."""
    from aletheia import jobs
    boards, accounts = [], []
    hrefs = [h for h, _t in links]
    # A board is often embedded, not linked: the script src or an iframe.
    hrefs += [html.unescape(u) for u in company_sites._URL.findall(str(page_html or ""))]
    for href in dict.fromkeys(hrefs):
        matched = jobs.job_from_url(href)
        if matched and matched[1]:
            boards.append({"provider": matched[0].provider, "token": matched[1], "url": href,
                           "job": True})
            continue
        for provider, pattern in _BOARD_URL:
            found = pattern.match(href)
            if found:
                boards.append({"provider": provider, "token": found.group(1), "url": href,
                               "job": False})
                break
        else:
            if company_sites.needs_account(href) and not company_sites._NOT_A_PAGE.search(href):
                accounts.append(href)
    seen, unique = set(), []
    for row in boards:
        key = (row["provider"], row["token"], row["job"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique, list(dict.fromkeys(accounts))


def _job_links(links: list[tuple[str, str]], domain: str) -> list[dict]:
    out, seen = [], set()
    for href, text in links:
        if not _same_site(href, domain) or company_sites._NOT_A_PAGE.search(href):
            continue
        words = text.split()
        if not (2 <= len(words) <= 12) or _NAV_TEXT.match(text) or not _ROLE_WORD.search(text):
            continue
        if not _JOB_HREF.search(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append({"title": text, "url": href})
        if len(out) >= MAX_JOB_LINKS:
            break
    return out


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value") or ""
    if isinstance(value, list):
        value = " ".join(_text(v) for v in value)
    return " ".join(str(value or "").split())


def _place(node: dict) -> str:
    places = node.get("jobLocation")
    parts = []
    for place in places if isinstance(places, list) else [places]:
        if not isinstance(place, dict):
            continue
        address = place.get("address") if isinstance(place.get("address"), dict) else place
        bits = [str(address.get(k) or "").strip()
                for k in ("addressLocality", "addressRegion", "addressCountry")]
        bits = [b for b in bits if b]
        if bits:
            parts.append(", ".join(bits))
        elif _text(place.get("name")):
            parts.append(_text(place.get("name")))
    location = "; ".join(dict.fromkeys(parts))
    if str(node.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        location = f"Remote - {location}" if location else "Remote"
    return location[:120]


def _salary(node: dict) -> tuple[float, float, str] | None:
    base = node.get("baseSalary")
    if not isinstance(base, dict):
        return None
    value = base.get("value") if isinstance(base.get("value"), dict) else base
    unit = str(value.get("unitText") or base.get("unitText") or "").upper()
    low, high = value.get("minValue"), value.get("maxValue")
    if low is None and high is None:
        low = high = value.get("value")
    try:
        low = float(str(low).replace(",", "")) if low not in (None, "") else None
        high = float(str(high).replace(",", "")) if high not in (None, "") else None
    except ValueError:
        return None
    if low is None and high is None:
        return None
    low = low if low is not None else high
    high = high if high is not None else low
    return (min(low, high), max(low, high), unit or "YEAR")


def posting_facts(node: dict, *, page_url: str = "") -> dict:
    """One schema.org JobPosting, flattened to the facts the hunt uses."""
    org = node.get("hiringOrganization")
    description = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(_text(node.get("description")))).split())
    facts = {
        "title": _text(node.get("title"))[:160],
        "company": _text(org)[:80],
        "location": _place(node),
        "employment_type": _text(node.get("employmentType")).casefold()[:40],
        "posted": str(node.get("datePosted") or "")[:32],
        "valid_through": str(node.get("validThrough") or "")[:32],
        "description": description[:DESCRIPTION_CHARS],
        "url": str(node.get("url") or page_url or "")[:800],
    }
    pay = _salary(node)
    if pay:
        facts["salary"] = [pay[0], pay[1]]
        facts["salary_unit"] = pay[2]
    return facts


# ---- the crawl ------------------------------------------------------------------------

def _get(url: str, *, fetch, sleeper, rules, report: dict) -> tuple[int, str, str]:
    if not allowed(url, rules):
        report["robots_blocked"].append(url)
        return 0, url, ""
    if report["pages_read"] >= MAX_PAGES:
        return 0, url, ""
    _wait_turn(company_sites.host_of(url), sleeper=sleeper)
    report["pages_read"] += 1
    try:
        status, final, body = fetch(url)
    except Exception as exc:
        report["errors"].append(f"{url}: {type(exc).__name__}")
        return 0, url, ""
    if company_sites._BOT_CHECK.search((body or "")[:60_000]) or (
            status in (403, 429, 503) and not (body or "").strip()):
        raise CrawlStopped("the site puts a bot check in front of its pages")
    return status, final or url, body or ""


def crawl(start: str, *, fetch=None, sleeper=time.sleep, robots_fetch=None) -> dict:
    """Where one employer posts its jobs, read from its own site.

    `start` is a domain or any URL on it. Returns what was found on at most
    MAX_PAGES pages: career pages, JobPosting facts, board or job links on
    applicant-tracking systems, account-walled systems, job-shaped links -
    and `stopped` when the crawl could not go on, with the reason.
    """
    fetch = fetch or company_sites._fetch
    domain = employers.domain_of(start) or employers.domain_of(f"https://{start}")
    report = {"domain": domain, "start": start, "pages_read": 0, "career_urls": [],
              "postings": [], "ats": [], "account_systems": [], "job_links": [],
              "robots_blocked": [], "errors": [], "stopped": ""}
    if not domain:
        report["stopped"] = "not an employer's own domain"
        return report
    if company_sites.is_aggregator(f"https://{domain}"):
        report["stopped"] = "a job aggregator, never crawled"
        return report
    base = start if "//" in str(start) else f"https://{domain}/"
    robots_txt = ""
    try:
        _wait_turn(domain, sleeper=sleeper)
        r_status, _f, r_body = (robots_fetch or fetch)(f"https://{domain}/robots.txt")
        robots_txt = r_body if r_status == 200 else ""
    except Exception:
        robots_txt = ""
    rules = robots_rules(robots_txt)
    queue: list[str] = []
    seen: set[str] = set()

    def push(url: str) -> None:
        url = url.split("#")[0]
        if url not in seen and _same_site(url, domain):
            seen.add(url)
            queue.append(url)

    try:
        status, final, body = _get(base, fetch=fetch, sleeper=sleeper, rules=rules, report=report)
        home_links = _links(body, final) if status == 200 else []
        for href in _career_links(home_links, domain):
            push(href)
        for path in LIKELY_PATHS:
            push(urllib.parse.urljoin(f"https://{domain}/", path))
        if status == 200:
            _harvest(body, final, domain, home_links, report)
        for sitemap in (rules.get("sitemaps") or [f"https://{domain}/sitemap.xml"])[:2]:
            if report["pages_read"] >= MAX_PAGES - 1:
                break
            s_status, _sf, s_body = _get(sitemap, fetch=fetch, sleeper=sleeper, rules=rules, report=report)
            if s_status != 200:
                continue
            for loc in _LOC.findall(s_body)[:2000]:
                loc = html.unescape(loc)
                if _CAREER_PATH.search(urllib.parse.urlsplit(loc).path or ""):
                    push(loc)
                    if len(queue) >= MAX_SITEMAP_URLS + len(LIKELY_PATHS):
                        break
        while queue and report["pages_read"] < MAX_PAGES:
            url = queue.pop(0)
            status, final, body = _get(url, fetch=fetch, sleeper=sleeper, rules=rules, report=report)
            if status != 200 or not body:
                continue
            if final not in report["career_urls"]:
                report["career_urls"].append(final)
            links = _links(body, final)
            _harvest(body, final, domain, links, report)
            # One level deeper: a careers home that links its own listing page.
            for href in _career_links(links, domain)[:3]:
                push(href)
    except CrawlStopped as exc:
        report["stopped"] = str(exc)
    return report


def _harvest(body: str, page_url: str, domain: str, links: list, report: dict) -> None:
    for node in company_sites._postings(body):
        facts = posting_facts(node, page_url=page_url)
        if facts["title"] and facts["url"] not in {p["url"] for p in report["postings"]}:
            report["postings"].append(facts)
    boards, accounts = _ats_links(links, body)
    have = {(b["provider"], b["token"], b["job"], b["url"]) for b in report["ats"]}
    for row in boards:
        key = (row["provider"], row["token"], row["job"], row["url"])
        if key not in have:
            have.add(key)
            report["ats"].append(row)
    for url in accounts:
        if url not in report["account_systems"]:
            report["account_systems"].append(url)
    have_jobs = {j["url"] for j in report["job_links"]}
    for row in _job_links(links, domain):
        if row["url"] not in have_jobs and len(report["job_links"]) < MAX_JOB_LINKS:
            have_jobs.add(row["url"])
            report["job_links"].append(row)


# ---- the ladder ----------------------------------------------------------------------

def _row(title: str, company: str, location: str, posting_url: str, apply_url: str, *,
         provider: str, board: str, ident: str, direct: bool, rung: str, **extra) -> dict:
    return {"title": " ".join(str(title or "").split())[:160], "company": company,
            "location": location, "posting_url": posting_url, "apply_url": apply_url,
            "provider": provider, "board": board, "id": ident, "direct": direct,
            "needs_account": provider == "account site",
            "found_by": FOUND_BY, "found_on": FOUND_ON, "extracted_by": rung, **extra}


def openings(employer: dict, *, fetch=None, sleeper=time.sleep, feed=None,
             report: dict | None = None) -> list[dict]:
    """Every opening one employer publishes, by the ladder, in `jobs.search_many`'s shape.

    `feed(board)` replaces the ATS providers (tests). Never raises.
    """
    from aletheia import jobs
    report = report if report is not None else {}
    name = str(employer.get("name") or "")
    out, seen = [], set()

    def keep(row: dict) -> None:
        if row["posting_url"] and row["posting_url"] not in seen and row["title"]:
            seen.add(row["posting_url"])
            out.append(row)

    # 1. The official feed of a board she can list.
    ats, token = str(employer.get("ats") or ""), str(employer.get("token") or "")
    if ats in jobs.PROVIDERS and token:
        try:
            rows = (feed or jobs.PROVIDERS[ats])({"provider": ats, "token": token,
                                                  "company": name, "learned": True})
            for job in rows or []:
                keep({**job, "found_by": FOUND_BY, "found_on": FOUND_ON, "extracted_by": "ats feed",
                      "direct": job.get("direct", True)})
            report["ats_feed"] = len(rows or [])
        except Exception as exc:
            report["ats_feed_failed"] = f"{type(exc).__name__}: {exc}"[:120]
    # 2-4. The site itself, when there is one to read.
    start = (employer.get("domains") or [""])[0] or (employer.get("career_urls") or [""])[0]
    if not start:
        return out
    crawled = crawl(start, fetch=fetch, sleeper=sleeper)
    report["crawl"] = crawled
    for facts in crawled["postings"]:
        url = facts["url"]
        matched = jobs.job_from_url(url)
        if matched:
            ats_, token_, jid = matched
            keep(_row(facts["title"], facts["company"] or name, facts["location"], url,
                      ats_.apply(token_, jid), provider=ats_.provider, board=token_, ident=jid,
                      direct=ats_.form, rung="jobposting json-ld",
                      salary=facts.get("salary"), salary_unit=facts.get("salary_unit", ""),
                      posted=facts["posted"], valid_through=facts["valid_through"],
                      employment_type=facts["employment_type"], description=facts["description"]))
        else:
            account = company_sites.needs_account(url)
            keep(_row(facts["title"], facts["company"] or name, facts["location"], url, url,
                      provider="account site" if account else "company site",
                      board=company_sites.host_of(url), ident=url, direct=False,
                      rung="jobposting json-ld",
                      salary=facts.get("salary"), salary_unit=facts.get("salary_unit", ""),
                      posted=facts["posted"], valid_through=facts["valid_through"],
                      employment_type=facts["employment_type"], description=facts["description"]))
    for link in crawled["ats"]:
        if link["job"]:
            matched = jobs.job_from_url(link["url"])
            if not matched:
                continue
            ats_, token_, jid = matched
            keep(_row(link.get("title") or f"a job at {name or token_}", name, "", link["url"],
                      ats_.apply(token_, jid), provider=ats_.provider, board=token_, ident=jid,
                      direct=ats_.form, rung="known ats page", unverified=True))
        elif link["provider"] in jobs.PROVIDERS and not (ats == link["provider"] and token == link["token"]):
            # The whole board, read now; remembered as this employer's next time.
            try:
                rows = (feed or jobs.PROVIDERS[link["provider"]])(
                    {"provider": link["provider"], "token": link["token"], "company": name, "learned": True})
                for job in rows or []:
                    keep({**job, "found_by": FOUND_BY, "found_on": FOUND_ON,
                          "extracted_by": "ats feed", "direct": job.get("direct", True)})
                report.setdefault("boards_read", []).append((link["provider"], link["token"]))
            except Exception:
                continue
    for link in crawled["job_links"]:
        account = company_sites.needs_account(link["url"])
        keep(_row(link["title"], name, "", link["url"], link["url"],
                  provider="account site" if account else "company site",
                  board=company_sites.host_of(link["url"]), ident=link["url"], direct=False,
                  rung="careers page link", unverified=True))
    return out


def crawl_employers(rows: list[dict] | None = None, *, limit: int = MAX_EMPLOYERS_PER_BATCH,
                    fetch=None, sleeper=time.sleep, feed=None, now: dt.datetime | None = None,
                    report: dict | None = None) -> list[dict]:
    """Openings from the employers due a crawl, remembering what each crawl taught.

    `rows` defaults to `employers.stale()`; at most `limit` are crawled. Each
    employer's row gets `last_crawled`, `jobs_seen`, its career pages, and its
    board when the crawl found one; boards she can list are learned. Never
    raises.
    """
    from aletheia import jobs
    report = report if report is not None else {}
    report.setdefault("crawled", [])
    now = now or dt.datetime.now(dt.timezone.utc)
    due = rows if rows is not None else employers.stale(RECRAWL_AFTER.total_seconds() / 86400, now=now)
    out = []
    for employer in list(due)[:max(0, int(limit))]:
        one: dict = {}
        try:
            found = openings(employer, fetch=fetch, sleeper=sleeper, feed=feed, report=one)
        except Exception as exc:
            found, one = [], {"failed": f"{type(exc).__name__}: {exc}"[:120]}
        crawled = one.get("crawl") or {}
        boards = [b for b in crawled.get("ats") or [] if b["provider"] in jobs.PROVIDERS]
        try:
            employers.upsert(name=str(employer.get("name") or ""),
                             domain=(employer.get("domains") or [""])[0],
                             career_url=(crawled.get("career_urls") or [""])[0],
                             ats=boards[0]["provider"] if boards else "",
                             token=boards[0]["token"] if boards else "",
                             jobs_seen=len(found), crawled=True,
                             note=crawled.get("stopped") or "",
                             now=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            pass
        try:
            jobs.learn_boards([{"provider": b["provider"], "board": b["token"],
                                "company": str(employer.get("name") or "")} for b in boards],
                              source="employer crawl")
        except Exception:
            pass
        report["crawled"].append({"name": employer.get("name"),
                                  "domain": (employer.get("domains") or [""])[0],
                                  "openings": len(found), "pages": crawled.get("pages_read", 0),
                                  "postings": len(crawled.get("postings") or []),
                                  "boards": [(b["provider"], b["token"]) for b in boards],
                                  "stopped": crawled.get("stopped") or one.get("failed") or ""})
        out.extend(found)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Crawl one employer's site for where it posts jobs.")
    ap.add_argument("domain")
    ap.add_argument("--openings", action="store_true", help="run the whole ladder")
    args = ap.parse_args(argv)
    if args.openings:
        row = employers.about(args.domain) or {"name": args.domain, "domains": [employers.domain_of(args.domain)
                                                                                or employers.domain_of("https://" + args.domain)]}
        report: dict = {}
        for job in openings(row, report=report):
            print(f"{job['company'][:22]:22} {job['title'][:48]:48} {job.get('location','')[:20]:20} "
                  f"[{job['extracted_by']}]")
        print(json.dumps({k: v for k, v in (report.get("crawl") or {}).items() if k != "postings"},
                         indent=1)[:2000], file=sys.stderr)
        return 0
    print(json.dumps(crawl(args.domain), indent=1)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
