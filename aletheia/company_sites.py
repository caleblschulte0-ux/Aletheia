"""Jobs on employers' OWN careers sites, not only the boards she already knows.

His words, 2026-09-13: *"make sure that we are not just looking on these job
sites but also company websites."*

Until now every opening came from two places: the Greenhouse and Lever boards
on file, and a web search restricted to applicant-tracking hosts. On his PC
that search is dead in practice - DuckDuckGo answers every query with an HTTP
202 challenge and Bing's RSS ignores `site:` and answers "Customer Success
Manager careers" with dictionary pages - so the batch at 17:05Z found "0 more
by web search" and she only ever reached the same sixty boards.

WHERE THE LEADS COME FROM. The Muse publishes a free developer API (no key,
500 requests an hour) over several hundred thousand current postings, and
each posting's page names the EMPLOYER'S OWN job page: jobs.bechtel.com,
equitylifestyleproperties.wd5.myworkdayjobs.com, boards.greenhouse.io/spacex
- measured live before this was written. The Muse is a lead, never a place
to apply: she follows the link out to the employer and applies there, which
is what a person reading the listing would do.

Sources that were measured and are NOT used, and why:

- Remotive's API terms allow it only for republishing their listings.
- Himalayas answers a plain fetch of a job page with HTTP 403.
- Indeed, LinkedIn, ZipRecruiter, Glassdoor and the like need a login or
  forbid automation. A lead that points at one is skipped, never followed.

WHAT A LEAD BECOMES, decided from the address it lands on:

- a public applicant-tracking form she already fills (Greenhouse, Lever,
  Ashby, Workable, SmartRecruiters, Recruitee - `jobs.ATS`): that form,
  exactly as a board opening would be;
- a system that makes you create an account first (Workday, iCIMS, Taleo,
  SuccessFactors and similar): kept, marked `needs_account`, and never
  opened here - accounts are `signup`'s, behind its own gate;
- anything else on the employer's site: the posting page, which the campaign
  already walks to its Apply link.

A posting the employer has taken down (HTTP 404/410, "no longer accepting
applications", a JobPosting whose `validThrough` has passed) or placed outside
the United States is dropped before it costs a browser.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

ACTOR = "aletheia-company-sites"
FOUND_ON = "the company's own careers page"
UA = "Mozilla/5.0 (compatible; Aletheia/1.0; personal job search)"
TIMEOUT_S = 20.0
MAX_PAGE_BYTES = 2_500_000

MUSE_API = "https://www.themuse.com/api/public/jobs"
#: The Muse's own category names - its vocabulary, not a choice of jobs.
#: A category is asked for only when a word of his roles or his own
#: `work_wanted` appears in it.
MUSE_CATEGORIES = (
    "Account Management", "Business Operations", "Customer Service",
    "Project Management", "Data and Analytics", "Sales", "Advertising and Marketing",
    "Administration and Office", "Accounting", "Human Resources and Recruitment",
    "Retail", "Education", "Healthcare", "Science and Engineering",
    "Software Engineering", "Design and UX", "Writing and Editing", "Finance",
    "Legal Services", "Operations", "Product Management", "Social Media and Community",
)
#: Words a category shares with a role that say nothing about which category.
_CATEGORY_FILLER = frozenset("and of the services office management".split())
#: The Muse's levels for someone early in a field, and for everyone else.
EARLY_LEVELS = ("Entry Level", "Mid Level")
ALL_LEVELS = ("Entry Level", "Mid Level", "Senior Level")
MAX_CATEGORIES = 3
#: Twenty postings a page. Measured live 2026-09-13: forty leads for his five
#: roles held ONE title the boards' own scoring accepted, so a run lists a few
#: hundred and reads only the ones that match.
PAGES_PER_CATEGORY = 5
#: Listings kept per run (MAX_CATEGORIES x PAGES_PER_CATEGORY API calls at
#: most - the API allows 500 an hour).
MAX_LEADS = 300
#: Listing pages actually opened per run, after title and place have matched.
MAX_LEADS_READ = 100

#: Job sites that are not the employer and that need a login or refuse
#: automation. A lead pointing at one is skipped.
AGGREGATORS = re.compile(
    r"(?:^|\.)(?:indeed|linkedin|ziprecruiter|glassdoor|monster|simplyhired|careerbuilder|"
    r"dice|snagajob|talent|jooble|adzuna|lensa|jobright|wellfound|angel|getwork|"
    r"themuse|remotive|himalayas|jobicy|arbeitnow|builtin|flexjobs|ladders|"
    r"google|facebook|twitter|x|instagram|youtube)\.(?:com|co|io|app|net|org|jobs)$", re.I)
#: Systems that ask for an account before they take an application.
ACCOUNT_SYSTEMS = re.compile(
    r"(?:myworkdayjobs\.com|myworkdaysite\.com|workday\.com|icims\.com|taleo\.net|"
    r"successfactors\.(?:com|eu)|jobs\.sap\.com|oraclecloud\.com|ultipro\.com|ukg\.net|"
    r"dayforcehcm\.com|adp\.com|paylocity\.com|brassring\.com|kenexa\.com|avature\.net)$",
    re.I)
#: A path that is a job, on a host that is not one of the systems above.
_JOB_PATH = re.compile(r"/(?:jobs?|careers?|positions?|openings?|requisitions?|vacanc(?:y|ies)|"
                       r"apply|opportunit(?:y|ies))(?:/|\b|-)", re.I)
_NOT_A_PAGE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|ico|css|js|woff2?|ttf|pdf|json|xml)(?:$|\?)",
                         re.I)
#: An apostrophe INSIDE a word stays in the address. Live 2026-09-13 Grainger's
#: "Account Manager, Gov't" was cut at the apostrophe to ".../Account-Manager%2C-Gov",
#: which loads a page with no form, and it was staged and pressed. One followed by
#: anything else still ends it, so href='...' attributes stop where they should.
_URL = re.compile(r"""https?://(?:[^\s"'<>\\)]|'(?=[A-Za-z0-9]))+""")
_LD = re.compile(r"""<script[^>]+application/ld\+json[^>]*>(.*?)</script>""", re.S | re.I)
#: A bot check in front of the page. Live 2026-09-13 jobs.uber.com answered a
#: real browser with Cloudflare's "Just a moment..." and no Apply control at
#: all. She does not get past those; the lead is skipped and named.
_BOT_CHECK = re.compile(
    r"<title>\s*(?:just a moment|attention required|access denied|are you a robot|"
    r"verifying you are human|please verify you are a human)|cf-chl-|challenge-platform|"
    # SmartRecruiters, live 2026-09-13, in front of Equinox's one-click form.
    r"access is temporarily restricted|detected unusual activity from your|"
    r"_incapsula_resource|px-captcha|g-recaptcha[^>]*data-sitekey[^>]*>\s*</div>\s*</body>",
    re.I)
#: Pay-per-click hops a listing uses in place of the employer's address. One
#: of them was followed live to the employer's posting (dsp.prng.co ->
#: chevronstations.com); another bounced back to the listing site's search
#: page, which is why where a hop LANDS is checked, never assumed.
_AD_HOPS = re.compile(
    r"""https?://(?:click\.appcast\.io|dsp\.prng\.co|[a-z0-9.-]*jobs2careers\.com|"""
    r"""[a-z0-9.-]*recruitics\.com|[a-z0-9.-]*joveo\.com|[a-z0-9.-]*pandologic\.com)"""
    r"""/[^\s"'<>\\)]+""", re.I)
MAX_HOPS_PER_LEAD = 2
_TAKEN_DOWN = re.compile(
    r"no longer (?:accepting (?:applications|applicants)|available|open|active|posted)|"
    r"(?:position|job|role|posting|requisition) (?:has been|was|is) (?:filled|closed|removed|expired)|"
    r"this (?:job|posting|position|role|requisition) (?:has )?(?:expired|closed)|"
    r"job you are (?:trying to access|looking for) (?:is|was) (?:no longer|not)",
    re.I)


def _fetch(url: str, accept: str = "text/html") -> tuple[int, str, str]:
    """(status, final url, body). A 404/410 comes back as a status, never raises."""
    request = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read(MAX_PAGE_BYTES).decode("utf-8", "replace")
            return int(getattr(response, "status", 200) or 200), response.geturl(), body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200_000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return int(exc.code), url, body


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(str(url or "")).netloc.casefold().split("@")[-1].split(":")[0]


def is_aggregator(url: str) -> bool:
    host = host_of(url)
    return bool(host) and bool(AGGREGATORS.search(host))


def needs_account(url: str) -> bool:
    host = host_of(url)
    return bool(host) and bool(ACCOUNT_SYSTEMS.search(host))


def categories_for(roles: list[str], wanted: str = "") -> list[str]:
    """The Muse categories that share a real word with his roles or his words."""
    words = set(re.findall(r"[a-z]+", " ".join([*(roles or []), wanted or ""]).casefold()))
    scored = []
    for category in MUSE_CATEGORIES:
        mine = set(re.findall(r"[a-z]+", category.casefold())) - _CATEGORY_FILLER
        # "Operations" meets "operations"; "Customer Service" meets "customer".
        shared = {w for w in mine if w in words or (w.endswith("s") and w[:-1] in words)}
        if shared:
            scored.append((len(shared), category))
    scored.sort(key=lambda row: -row[0])
    return [category for _n, category in scored[:MAX_CATEGORIES]]


def employer_link(page_html: str, *, lead_host: str = "") -> str:
    """The employer's own job page named on a listing page, or "".

    Preference: a public applicant-tracking form she already fills, then a
    system that needs an account, then any job-shaped page on another site.
    The listing site itself, job aggregators and static assets never count.
    """
    from aletheia import jobs
    text = html.unescape(str(page_html or "")).replace("\\/", "/").replace("\\u002F", "/")
    public, account, other = [], [], []
    for raw in _URL.findall(text):
        url = raw.rstrip(".,;")
        host = host_of(url)
        if not host or host == lead_host or host.endswith("." + lead_host) or _NOT_A_PAGE.search(url):
            continue
        if is_aggregator(url):
            continue
        if jobs.job_from_url(url):
            public.append(url)
        elif needs_account(url):
            if "/job" in urllib.parse.urlsplit(url).path.casefold() or "job" in url.casefold():
                account.append(url)
        elif _JOB_PATH.search(urllib.parse.urlsplit(url).path or ""):
            other.append(url)
    for group in (public, account, other):
        if group:
            return group[0]
    return ""


def _postings(page_html: str) -> list[dict]:
    """Every schema.org JobPosting the page declares."""
    found = []
    for raw in _LD.findall(str(page_html or "")):
        try:
            data = json.loads(html.unescape(raw.strip()))
        except (ValueError, TypeError):
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            node = queue.pop(0)
            if not isinstance(node, dict):
                continue
            queue.extend(n for n in (node.get("@graph") or []) if isinstance(n, dict))
            kind = node.get("@type")
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                found.append(node)
    return found


def _outside_the_us(posting: dict) -> bool:
    """A posting that names only countries other than the United States."""
    from aletheia import jobs
    places = []
    for key in ("applicantLocationRequirements", "jobLocation"):
        value = posting.get(key)
        for item in value if isinstance(value, list) else [value]:
            if not isinstance(item, dict):
                continue
            address = item.get("address") if isinstance(item.get("address"), dict) else item
            country = address.get("addressCountry") or address.get("name") or ""
            if isinstance(country, dict):
                country = country.get("name") or ""
            if str(country).strip():
                places.append(str(country))
    return bool(places) and not any(jobs._in_country(p, "United States") for p in places)


def still_open(url: str, *, fetch=None, now: dt.datetime | None = None) -> tuple[bool, str]:
    """(open, why not) for an employer's job page, read without a browser.

    Fails OPEN: a page that cannot be read, or a JavaScript shell with nothing
    in it, is left for the browser to judge. Only a clear "gone" closes it.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        status, _final, body = (fetch or _fetch)(url)
    except Exception:
        return True, ""
    if status in (404, 410):
        return False, f"the employer's page is gone (HTTP {status})"
    if _BOT_CHECK.search((body or "")[:60_000]) or (status in (403, 429, 503) and not body.strip()):
        return False, "the employer's site puts a bot check in front of its jobs"
    visible = " ".join(re.sub(r"<[^>]+>", " ", re.sub(
        r"<(script|style)\b.*?</\1>", " ", body or "", flags=re.S | re.I)).split())
    if _TAKEN_DOWN.search(visible[:20_000]):
        return False, "the employer says the job is no longer open"
    for posting in _postings(body):
        through = str(posting.get("validThrough") or "").strip()
        if through:
            try:
                ends = dt.datetime.fromisoformat(through.replace("Z", "+00:00"))
                if ends.tzinfo is None:
                    ends = ends.replace(tzinfo=dt.timezone.utc)
                if ends < now:
                    return False, "the posting's closing date has passed"
            except ValueError:
                pass
        if _outside_the_us(posting):
            return False, "the posting is outside the United States"
    return True, ""


def _muse_page(params: list[tuple[str, str]], fetch_json) -> list[dict]:
    url = MUSE_API + "?" + urllib.parse.urlencode(params)
    try:
        data = fetch_json(url)
    except Exception:
        return []
    return list((data or {}).get("results") or [])


def _fetch_json(url: str) -> dict:
    status, _final, body = _fetch(url, "application/json")
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    return json.loads(body)


#: The listing is deep; no batch reads more than PAGES_PER_CATEGORY of it.
MAX_PAGE = 60


def _cursor_path():
    from aletheia import stateio
    return stateio.private_dir("jobs") / "company_site_pages.json"


def _read_cursor(path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def muse_leads(roles: list[str], *, wanted: str = "", early: bool = True,
               fetch_json=None, limit: int = MAX_LEADS, cursor_path=None) -> list[dict]:
    """Current postings for his kind of work, from The Muse's public API.

    Each batch starts where the last one stopped. Without that every batch
    read the same first pages of each category, so the loop that runs all
    day would see the same few hundred postings all day.
    """
    fetch_json = fetch_json or _fetch_json
    levels = EARLY_LEVELS if early else ALL_LEVELS
    out, seen = [], set()
    categories = categories_for(roles, wanted) or [None]
    path = cursor_path if cursor_path is not None else _cursor_path()
    cursor = _read_cursor(path)
    start = {c: int(cursor.get(str(c), 0) or 0) % MAX_PAGE for c in categories}
    reached = dict(start)
    for step in range(PAGES_PER_CATEGORY):
        for category in categories:
            page = (start[category] + step) % MAX_PAGE
            params = [("page", str(page))] + [("level", lv) for lv in levels]
            if category:
                params.append(("category", category))
            rows = _muse_page(params, fetch_json)
            # The end of a category starts it over next time.
            reached[category] = (page + 1) % MAX_PAGE if rows else 0
            for job in rows:
                landing = str((job.get("refs") or {}).get("landing_page") or "")
                if not landing or landing in seen:
                    continue
                seen.add(landing)
                out.append({
                    "title": " ".join(str(job.get("name") or "").split())[:160],
                    "company": " ".join(str((job.get("company") or {}).get("name") or "").split())[:80],
                    "locations": [str(l.get("name") or "") for l in job.get("locations") or []
                                  if isinstance(l, dict)],
                    "lead": landing,
                })
                if len(out) >= limit:
                    _write_cursor(path, reached)
                    return out
    _write_cursor(path, reached)
    return out


def _write_cursor(path, reached: dict) -> None:
    try:
        from aletheia import stateio
        stateio.write_json_atomic(path, {str(k): v for k, v in reached.items()})
    except Exception:
        pass                     # a cursor that cannot be saved only repeats a page


def _location_ok(locations: list[str], country: str) -> bool:
    from aletheia import jobs
    if not country or not locations:
        return True                           # no posted place is not ruled out
    return any(jobs._in_country(place, country) for place in locations)


def follow_hops(page_html: str, *, lead_host: str, fetch) -> str:
    """The employer page a pay-per-click hop on the listing lands on, or "".

    A hop that lands back on the listing site, on an aggregator, or nowhere
    that looks like a job is not the employer, and is dropped.
    """
    from aletheia import jobs
    text = html.unescape(str(page_html or "")).replace("\\/", "/").replace("\\u002F", "/")
    for hop in list(dict.fromkeys(_AD_HOPS.findall(text)))[:MAX_HOPS_PER_LEAD]:
        try:
            status, final, _body = fetch(hop.rstrip(".,;"))
        except Exception:
            continue
        host = host_of(final)
        if status != 200 or not host or host == lead_host or host.endswith("." + lead_host):
            continue
        if is_aggregator(final) or _AD_HOPS.match(final):
            continue
        path = urllib.parse.urlsplit(final).path or ""
        if jobs.job_from_url(final) or needs_account(final) or _JOB_PATH.search(path):
            return final
    return ""


def openings(roles: list[str], *, limit: int = 10, country: str = "", exclude=(),
             wanted: str = "", early: bool = True, fetch=None, fetch_json=None,
             leads=None, skipped: list | None = None) -> list[dict]:
    """Openings on employers' own sites, in the shape `jobs.search_many` returns.

    Every lead is title-matched with the SAME scoring the boards use, placed
    in his country, followed to the employer, and checked still open. Never
    raises: a source that will not answer costs this source, not the search.
    `skipped`, when given, collects every lead that was read and dropped, and why.
    """
    from aletheia import jobs
    term_sets = [t for t in (jobs._terms(r) for r in roles or []) if t]
    if not term_sets:
        return []
    exclude = frozenset(str(w).casefold() for w in exclude or ())
    fetch = fetch or _fetch
    dropped = skipped if skipped is not None else []
    try:
        found = (leads or muse_leads)(roles, wanted=wanted, early=early, fetch_json=fetch_json)
    except Exception:
        return []
    out, seen = [], set()
    read = 0
    for lead in found:
        if len(out) >= limit or read >= MAX_LEADS_READ:
            break
        job = {"title": lead.get("title", ""), "location": ", ".join(lead.get("locations") or []),
               "company": lead.get("company", "")}
        if max(jobs._score(job, terms, "", exclude=exclude) for terms in term_sets) <= 0:
            continue
        if not _location_ok(lead.get("locations") or [], country):
            continue
        read += 1
        try:
            status, final, body = fetch(lead["lead"])
        except Exception as exc:
            dropped.append({**job, "lead": lead["lead"], "why": f"the listing did not load ({type(exc).__name__})"})
            continue
        if status != 200:
            dropped.append({**job, "lead": lead["lead"], "why": f"the listing did not load (HTTP {status})"})
            continue
        lead_host = host_of(final or lead["lead"])
        target = (employer_link(body, lead_host=lead_host)
                  or follow_hops(body, lead_host=lead_host, fetch=fetch))
        if not target:
            dropped.append({**job, "lead": lead["lead"], "why": "the listing names no employer page"})
            continue
        if target in seen:
            continue
        seen.add(target)
        matched = jobs.job_from_url(target)
        board = host_of(target)
        if matched:
            ats, token, jid = matched
            # The board is the TOKEN, which is what `jobs` learns and lists by;
            # the host said "jobs.ashbyhq.com" for every Ashby employer alike.
            # And a posting page that is not the form is walked, not staged.
            apply_url, direct, provider, account = ats.apply(token, jid), ats.form, ats.provider, False
            board = token or board
        else:
            account = needs_account(target)
            apply_url, direct, provider = target, False, ("account site" if account else "company site")
            if not account:
                is_open, why = still_open(target, fetch=fetch)
                if not is_open:
                    dropped.append({**job, "lead": lead["lead"], "target": target, "why": why})
                    continue
        out.append({
            "title": job["title"], "company": job["company"], "location": job["location"],
            "posting_url": target, "apply_url": apply_url, "provider": provider,
            "board": board, "id": target,
            "found_by": "company site", "found_on": FOUND_ON,
            "direct": direct, "needs_account": account, "lead": lead["lead"],
        })
    return out
