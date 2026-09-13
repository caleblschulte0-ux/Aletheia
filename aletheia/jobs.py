"""Where the jobs actually come from.

The campaign was proved against a job board I wrote myself, and on the
real internet it found NOTHING. `research.find_sources` drives a headless
browser at a search engine, and a search engine answers a headless
browser with a challenge page — so "apply to ten jobs" returned zero
openings and everything downstream of it was theatre.

That is the difference between a demo and a thing that works, and it is
the reason he said it was not fixed.

So jobs come from the systems that PUBLISH them, not from scraping
search results. Greenhouse and Lever both expose their boards as public
JSON — no key, no account, documented, stable — and both host the real
application form at a public URL that needs no login. That last part is
what makes this the right source rather than merely a working one: a
posting she can find but not apply to is a link he could have found
himself.

  greenhouse  boards-api.greenhouse.io/v1/boards/<token>/jobs
              -> boards.greenhouse.io/embed/job_app?for=<token>&token=<id>
  lever       api.lever.co/v0/postings/<token>?mode=json
              -> jobs.lever.co/<token>/<id>/apply

The company list lives in `config/job_boards.json` so it is data he can
add to, not a literal buried in code. Twenty boards is four thousand
live openings; adding a company is one line.

WHAT IT WILL NOT DO: pretend a board that did not answer is empty. A
provider that fails is reported as failed, per board, because "no jobs
matched" and "the network refused me" are different answers and only one
of them means try a different search.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from aletheia import journal, speech, stateio
from aletheia.fleet import REPO_ROOT

ACTOR = "aletheia-jobs"

BOARDS_PATH = REPO_ROOT / "config" / "job_boards.json"
TIMEOUT_S = 20.0
MAX_BYTES = 12_000_000
MAX_WORKERS = 8
MAX_RESULTS = 60
UA = "Mozilla/5.0 (compatible; Aletheia/1.0; personal job search)"

# Words that carry no signal in a job title and would match everything.
STOP = frozenset("""a an and for in of on the to with senior junior staff lead
principal i ii iii jobs job role roles remote hybrid onsite""".split())

# Words nearly every title has. A role's OTHER words must be in the title:
# live 2026-09-10 "Account Manager" matched "Accounts Receivable Manager" and
# "Operations Manager" matched "Corporate Accounting Manager", because
# "manager" counted as a hit and "account" was found inside "accounts".
GENERIC_TITLE_WORDS = frozenset("""manager management associate specialist
coordinator analyst representative rep executive officer assistant consultant
administrator generalist""".split())
# What a title says about level. Left out only when the caller says so
# (campaign, for someone early in his field), never by default.
SENIOR_TITLE_WORDS = frozenset("""senior sr staff principal lead director head vp
vice chief enterprise strategic""".split())
# "Enterprise" and "Strategic" account roles carry the largest deals and ask
# for years of closing; live 2026-09-10 they were most of what an Associate
# a year into business development was offered.

# Places outside the United States, to tell "Remote - EMEA" from "Remote".
# A US state, a state code or "US" in the location settles it first.
_ABROAD = re.compile(
    r"\b(?:emea|europe|apac|latam|uk|united kingdom|england|london|ireland|dublin|"
    r"germany|berlin|munich|france|paris|spain|madrid|barcelona|netherlands|amsterdam|"
    r"poland|warsaw|portugal|lisbon|sweden|stockholm|switzerland|zurich|india|bengaluru|"
    r"bangalore|hyderabad|pune|singapore|japan|tokyo|korea|seoul|china|hong kong|taiwan|"
    r"australia|sydney|melbourne|canada|toronto|vancouver|montreal|mexico|brazil|"
    r"sao paulo|argentina|colombia|israel|tel aviv|philippines|manila|uae|dubai)\b")
_US_WORD = re.compile(r"(?:^|[^a-z])(?:us|usa|u\.s\.a?\.?|united states)(?:[^a-z]|$)")
_US_NAMES = ("united states", "united states of america", "usa", "us")


class JobsError(RuntimeError):
    pass


def boards() -> list[dict]:
    """The company boards she can reach: the configured list, then every
    employer a web search has turned up since. Data, not a literal."""
    try:
        value = json.loads(BOARDS_PATH.read_text(encoding="utf-8"))
        rows = value.get("boards") if isinstance(value, dict) else value
    except (OSError, ValueError):
        rows = []
    configured = [r for r in (rows or []) if isinstance(r, dict) and r.get("token")]
    known = {(r.get("provider"), r["token"]) for r in configured}
    learned = [r for r in _learned_boards()
               if (r.get("provider"), r.get("token")) not in known]
    return configured + learned


MAX_LEARNED_BOARDS = 400


def _learned_path():
    return stateio.private_dir("jobs") / "learned_boards.json"


def _learned_boards() -> list[dict]:
    try:
        rows = json.loads(_learned_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    # A name a search engine cut short is not a name. It is healed on the way
    # out, so the one already on his PC ("Neros ...") stops spreading; the
    # board's own listing supplies the real one.
    return [{**r, "company": r["token"]} if _cut(r.get("company")) else r
            for r in rows if isinstance(r, dict) and r.get("token") and r.get("provider")]


def _cut(name) -> bool:
    """"Neros ..." - the end of a name a search result ran out of room for."""
    return bool(re.search(r"(?:\.\.\.|…)\s*$", str(name or "")))


def _learn_boards(found: list[dict]) -> int:
    """Keep every employer a web search turned up, so the next search reads
    its board directly. Live 2026-09-10 the web search worked for a few
    queries and then DuckDuckGo answered everything with its challenge page:
    an employer found once should not depend on being found again."""
    rows = _learned_boards()
    have = {(r["provider"], r["token"]) for r in rows}
    added = 0
    for job in found:
        key = (job.get("provider"), job.get("board"))
        if not all(key) or key in have:
            continue
        have.add(key)
        rows.append({"provider": key[0], "token": key[1],
                     "company": ("" if _cut(job.get("company")) else job.get("company")) or key[1],
                     "learned": True, "from": "web search"})
        added += 1
    if added:
        path = _learned_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(path, rows[-MAX_LEARNED_BOARDS:])
    return added


def _forget_boards(gone: list[dict]) -> None:
    drop = {(f.get("provider"), f.get("board")) for f in gone}
    rows = [r for r in _learned_boards() if (r["provider"], r["token"]) not in drop]
    path = _learned_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, rows)


class BoardGone(JobsError):
    """The provider says this board does not exist.

    Different in kind from a timeout, and the difference is the whole
    point: a board that times out is worth retrying, a board that 404s is
    a company that renamed or left the provider and will 404 forever.
    Three of them sat dead in `config/job_boards.json` — reported per
    search, in a journal line nobody reads, while every search quietly
    covered fewer companies than the file claimed.
    """


def _fetch(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read(MAX_BYTES).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            raise BoardGone(f"the provider says this board does not exist "
                            f"(HTTP {exc.code})") from exc
        raise


def _board_name(provider: str, token: str, fetch=None) -> str:
    """The company's name as its own board publishes it. Greenhouse does; Lever does not."""
    if provider != "greenhouse" or not token:
        return ""
    try:
        data = (fetch or _fetch)(
            f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(str(token))}")
    except Exception:
        return ""
    name = " ".join(str((data or {}).get("name") or "").split())
    return "" if _cut(name) else name[:80]


def _greenhouse(board: dict) -> list[dict]:
    token = board["token"]
    data = _fetch(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    # A name he configured is his. A LEARNED name came off a search result -
    # live 2026-09-13 "Neros ..." for Neros Technologies, which then keyed
    # the duplicate check and the verification-code lookup on three dots -
    # so the board's own company_name outranks it.
    given = str(board.get("company") or "").strip()
    trusted = "" if (board.get("learned") or _cut(given)) else given
    fallback = "" if _cut(given) else given
    out = []
    for job in data.get("jobs", []):
        jid = job.get("id")
        if not jid:
            continue
        published = " ".join(str(job.get("company_name") or "").split())
        out.append({
            "title": (job.get("title") or "").strip(),
            "company": trusted or ("" if _cut(published) else published) or fallback or token,
            "location": ((job.get("location") or {}).get("name") or "").strip(),
            "posting_url": job.get("absolute_url") or "",
            # The public application form. No account, no login.
            "apply_url": ("https://boards.greenhouse.io/embed/job_app"
                          f"?for={urllib.parse.quote(token)}&token={jid}"),
            "provider": "greenhouse", "board": token, "id": str(jid),
        })
    return out


def _lever(board: dict) -> list[dict]:
    token = board["token"]
    data = _fetch(f"https://api.lever.co/v0/postings/{token}?mode=json")
    out = []
    for job in data if isinstance(data, list) else []:
        jid = job.get("id")
        if not jid:
            continue
        out.append({
            "title": (job.get("text") or "").strip(),
            "company": board.get("company") or token,
            "location": ((job.get("categories") or {}).get("location") or "").strip(),
            "posting_url": job.get("hostedUrl") or "",
            "apply_url": f"https://jobs.lever.co/{urllib.parse.quote(token)}/{jid}/apply",
            "provider": "lever", "board": token, "id": str(jid),
        })
    return out


PROVIDERS = {"greenhouse": _greenhouse, "lever": _lever}

_GREENHOUSE_FORM = re.compile(r"[?&]for=([A-Za-z0-9_-]+).*?[?&]token=(\d+)")
POSTING_CHARS = 12_000


def _plain(markup: str) -> str:
    import html
    text = re.sub(r"<(?:br|/p|/li|/h\d)[^>]*>", "\n", html.unescape(str(markup or "")), flags=re.I)
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def posting_text(job: dict, fetch=None) -> str:
    """What the posting SAYS - requirements included - or "" when it cannot tell.

    The board listing carries a title and a place and nothing about what
    the job needs, so "Series 7 required", "7+ years selling into federal
    agencies" and "years managing Costco at Issaquah HQ" were invisible to
    everything that chose a job. Both providers publish one posting's text
    at a public address; this reads it. Never raises.
    """
    get = fetch or _fetch
    for address in (job.get("url"), job.get("apply_url"), job.get("posting"),
                    job.get("posting_url")):
        address = urllib.parse.unquote(str(address or ""))
        try:
            form = _GREENHOUSE_FORM.search(address)
            green = form or _GREENHOUSE_JOB.search(address)
            if green:
                data = get(f"https://boards-api.greenhouse.io/v1/boards/"
                           f"{green.group(1)}/jobs/{green.group(2)}")
                return _plain((data or {}).get("content", ""))[:POSTING_CHARS]
            lever = _LEVER_JOB.search(address)
            if lever:
                data = get(f"https://api.lever.co/v0/postings/{lever.group(1)}/{lever.group(2)}")
                parts = [str((data or {}).get(k) or "") for k in ("descriptionPlain", "additionalPlain")]
                for block in (data or {}).get("lists") or []:
                    parts.append(str(block.get("text") or ""))
                    parts.append(_plain(block.get("content", "")))
                return " ".join(" ".join(parts).split())[:POSTING_CHARS]
        except Exception:
            return ""
    return ""


def _terms(role: str) -> list[str]:
    words = re.split(r"[^a-z0-9+#]+", str(role).casefold())
    return [w for w in words if w and w not in STOP and len(w) > 1]


# A title that manages the people doing the job. "Manager, Account Management"
# asked for five years and two managing a team, and live 2026-09-10 it was
# offered to someone a year into business development.
_MANAGES_PEOPLE = re.compile(
    r"^\s*manager\b|\bmanager\s+of\b|\bpeople manager\b|"
    r"\bmanager,\s+\w+\s+(?:management|managers|executives|representatives|development|team)\b",
    re.I)


def _title_words(title: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9+#]+", str(title).casefold()) if w}


# Cities a US posting names without a state: "Chicago, Seattle, NYC, San
# Francisco" was ruled out live because nothing in it said "US".
_US_CITY = re.compile(
    r"\b(?:new york|nyc|san francisco|sf|bay area|chicago|seattle|boston|austin|"
    r"los angeles|denver|atlanta|miami|dallas|houston|philadelphia|portland|san diego|"
    r"minneapolis|sioux falls|phoenix|salt lake city|nashville|raleigh|charlotte|"
    r"detroit|pittsburgh|st\.? louis|kansas city|omaha|des moines|washington,? d\.?c\.?)\b")


def _in_country(location: str, country: str) -> bool:
    """Is this job somewhere he can work without sponsorship?

    He needs none in the United States, and live 2026-09-10 the top matches
    were in Dublin, Bengaluru, Singapore and Mexico City. An empty location
    is not ruled out; "Hybrid" with no place in it is.
    """
    loc = " ".join(str(location or "").split())
    want = " ".join(str(country or "").casefold().split())
    if not want or not loc:
        return True
    low = loc.casefold()
    if want not in _US_NAMES:
        return want in low
    from aletheia.formfill import US_STATE_NAMES
    if _US_WORD.search(low) or _US_CITY.search(low):
        return True
    if any(re.search(r"\b" + re.escape(name.casefold()) + r"\b", low)
           for name in US_STATE_NAMES.values()):
        return True
    # A state code, but not Greenhouse's country prefix: live "CA-Toronto,
    # CA-Montreal" was read as California.
    if re.search(r",\s*(?:" + "|".join(US_STATE_NAMES) + r")(?![-\w])", loc):
        return True
    if _ABROAD.search(low):
        return False
    return "remote" in low or "anywhere" in low


#: Where a title stops naming the job and starts naming the team, the
#: product or the place: "Product Manager, Connected Account Onboarding".
_QUALIFIER = re.compile(r"\s*(?:,|\s[-–—|:]\s|\()\s*")
#: Title head words that are rungs of the same ladder. A role's head may meet
#: another rung of its own ladder - that is the "shoot high and shoot low" he
#: asked for - and never a head from a different line of work.
HEAD_LADDERS = (
    frozenset("representative rep associate specialist coordinator executive manager".split()),
    frozenset("analyst associate specialist".split()),
)


def _primary_words(title: str) -> set[str]:
    """The words that name the job itself, before any qualifier."""
    return _title_words(_QUALIFIER.split(str(title or ""), maxsplit=1)[0])


def _head_fits(role_head: str, primary: set[str]) -> bool:
    if role_head in primary:
        return True
    return any(role_head in ladder and primary & ladder for ladder in HEAD_LADDERS)


def _score(job: dict, terms: list[str], where: str, *, exclude=frozenset()) -> float:
    words = _title_words(job["title"])
    if exclude and (words & exclude or _MANAGES_PEOPLE.search(str(job["title"]))):
        return 0.0
    # Whole words, and every word that is not generic: "account" is not in
    # "accounts receivable", and "manager" alone is not a match.
    needed = [t for t in terms if t not in GENERIC_TITLE_WORDS] or list(terms)
    if not all(t in words for t in needed):
        return 0.0
    # And they have to name the JOB, not the team. Live 2026-09-12/13 one
    # shared word anywhere was enough: "Account Manager" matched "Product
    # Manager, Connected Account Onboarding" (and it was sent), "Partner
    # Manager" matched "People Business Partner, GTM" and "Event Marketing
    # Manager, 3P & Partner", "Operations Analyst" matched "Accounting
    # Manager, GL Operations" and "Financial Operations Manager".
    primary = _primary_words(job["title"])
    if not any(t in primary for t in needed):
        return 0.0
    heads = [t for t in terms if t in GENERIC_TITLE_WORDS]
    if heads and needed != list(terms) and not _head_fits(heads[-1], primary):
        return 0.0
    value = sum(1 for t in terms if t in words) / max(1, len(terms))
    if where:
        place = where.casefold()
        loc = job["location"].casefold()
        if place in loc or (place in ("remote", "anywhere") and "remote" in loc):
            value += 0.5
        elif place not in ("remote", "anywhere") and loc and place not in loc:
            value -= 0.35
    return value


def _gather(fetcher=None) -> tuple[list[dict], list[dict], int]:
    """Every open job on every configured board, and the boards that failed."""
    rows = boards()
    if not rows:
        raise JobsError(
            f"no job boards configured — {BOARDS_PATH} is missing or empty. "
            "Each entry is a provider and a company's board token.")

    def one(board):
        provider = PROVIDERS.get(board.get("provider"))
        if provider is None:
            return board, [], f"unknown provider {board.get('provider')!r}"
        try:
            return board, (fetcher or provider)(board), ""
        except BoardGone as exc:
            # Permanently gone, not merely unreachable. Marked so the
            # caller can say so out loud exactly once.
            return board, [], f"GONE: {exc}"[:120]
        except Exception as exc:
            # A board that did not answer is FAILED, not empty. "No jobs
            # matched" and "the network refused me" are different answers.
            return board, [], f"{type(exc).__name__}: {exc}"[:120]

    everything, failures = [], []
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        for board, jobs, problem in pool.map(one, rows):
            if problem:
                failures.append({"board": board.get("token"),
                                 "company": board.get("company", ""),
                                 "provider": board.get("provider", ""),
                                 "gone": problem.startswith("GONE:"),
                                 "learned": bool(board.get("learned")),
                                 "why": problem})
                continue
            everything.extend(jobs)
    # A board he configured that is gone is worth telling him about. One she
    # picked up from a web search is simply forgotten.
    _say_a_board_is_gone([f for f in failures if f["gone"] and not f["learned"]])
    learned_gone = [f for f in failures if f["gone"] and f["learned"]]
    if learned_gone:
        _forget_boards(learned_gone)
    return everything, failures, len(rows)


def search(role: str, *, where: str = "", limit: int = 10,
           fetcher=None) -> dict:
    """Real openings she can really apply to, most relevant first."""
    return search_many([role], where=where, limit=limit, fetcher=fetcher)


def search_many(roles: list[str], *, where: str = "", limit: int = 10,
                fetcher=None, discover: bool = False, http=None,
                country: str = "", exclude=(), namer=None, companies=None) -> dict:
    """Openings for ANY of these roles, each scored by the role it fits best.

    `discover` adds openings on boards nobody configured: a web search for
    each role on Greenhouse and Lever, whose public forms need no login. The
    configured list is where she starts, never where she stops - "it should
    be able to apply to any job" was his rule, and twenty-four tech
    companies are not any job.

    `discover` also adds openings on employers' OWN careers sites
    (`company_sites.openings`): his words, 2026-09-13, "not just looking on
    these job sites but also company websites". `companies` replaces that
    finder; on a search given its own `fetcher` (a test) nothing reaches the
    network unless a finder is handed in.
    """
    term_sets = [terms for terms in (_terms(r) for r in roles or []) if terms]
    if not term_sets:
        raise ValueError("say what kind of role")
    exclude = frozenset(str(w).casefold() for w in exclude or ())
    everything, failures, searched = _gather(fetcher)
    found = []
    for job in everything:
        if country and not _in_country(job.get("location", ""), country):
            continue
        value = max(_score(job, terms, where, exclude=exclude) for terms in term_sets)
        if value > 0:
            found.append((value, job))
    found.sort(key=lambda row: row[0], reverse=True)
    cap = max(1, min(int(limit), MAX_RESULTS))
    # One opening from each employer before a second from any: live the top
    # sixty were Databricks, Stripe and Brex, and three tries each ran out of
    # employers after nine.
    queues: dict[str, list] = {}
    for _v, job in found:
        queues.setdefault(str(job.get("company") or "").casefold(), []).append(job)
    board, waiting = [], list(queues.values())
    while waiting:
        board += [queue.pop(0) for queue in waiting]
        waiting = [queue for queue in waiting if queue]
    web = []
    if discover:
        # The web search always runs. It ran only when the boards came up
        # short, and thirty-six big tech boards never do: live 2026-09-10
        # every slot went to Stripe and Databricks, and no other employer
        # was ever looked for.
        seen = {job["apply_url"] for job in board[:cap]}
        for job in discover_openings(roles, limit=cap, http=http):
            if job["apply_url"] in seen:
                continue
            if country and not _in_country(job.get("location", ""), country):
                continue
            if max(_score(job, terms, "", exclude=exclude) for terms in term_sets) <= 0:
                continue
            seen.add(job["apply_url"])
            web.append(job)
        # An employer known only by its board token is named by its board,
        # once per board, before it is remembered or applied to. Only on a
        # real search: a test's own fetcher never reaches the network here.
        name_of = namer if namer is not None else (_board_name if fetcher is None else None)
        if name_of:
            names: dict = {}
            for job in web:
                if not job.get("named_by_token"):
                    continue
                key = (job.get("provider"), job.get("board"))
                if key not in names:
                    try:
                        names[key] = str(name_of(*key) or "")
                    except Exception:
                        names[key] = ""
                if names[key] and not _cut(names[key]):
                    job["company"] = names[key]
        _learn_boards(web)
    own = []
    finder = companies if companies is not None else (_company_openings if fetcher is None else None)
    if discover and finder:
        seen = {job["apply_url"] for job in board[:cap]} | {job["apply_url"] for job in web}
        try:
            for job in finder(roles, limit=cap, country=country, exclude=exclude) or []:
                if job.get("apply_url") and job["apply_url"] not in seen:
                    seen.add(job["apply_url"])
                    own.append(job)
        except Exception:
            own = []            # a source that will not answer costs this source
    # The web and the employers' own sites take turns in the third slot, so
    # neither crowds out the other and neither crowds out the boards.
    beyond, i = [], 0
    while i < max(len(web), len(own)):
        beyond += [row[i] for row in (web, own) if i < len(row)]
        i += 1
    # Two from the boards, then one found beyond them, so both get tried.
    matches, b, w = [], 0, 0
    while len(matches) < cap and (b < len(board) or w < len(beyond)):
        if w < len(beyond) and (len(matches) % 3 == 2 or b >= len(board)):
            matches.append(beyond[w])
            w += 1
        else:
            matches.append(board[b])
            b += 1
    discovered = [job for job in matches if job.get("found_by") == "web search"]
    on_their_sites = [job for job in matches if job.get("found_by") == "company site"]
    journal.append("action", "jobs",
                   f"searched {speech.count_phrase(searched, 'board')} for "
                   f"{', '.join(roles)!r}: {speech.count_phrase(len(found), 'match')}, "
                   f"{len(discovered)} more by web search, "
                   f"{len(on_their_sites)} on employers' own sites, "
                   f"{speech.count_phrase(len(failures), 'board')} failed",
                   actor=ACTOR)
    return {"role": ", ".join(roles), "roles": list(roles), "where": where,
            "matches": matches, "searched": searched, "matched": len(found),
            "discovered": len(discovered), "company_sites": len(on_their_sites),
            "failed": failures}


def _company_openings(roles: list[str], *, limit: int, country: str = "", exclude=()) -> list[dict]:
    """Employers' own careers sites, for the kind of work he said he wants."""
    from aletheia import company_sites, profile
    try:
        wanted = str(profile.known().get("work_wanted") or "")
    except Exception:
        wanted = ""
    return company_sites.openings(roles, limit=limit, country=country, exclude=exclude,
                                  wanted=wanted, early=bool(exclude))


MAX_ROLES_PER_SEARCH = 5
_GREENHOUSE_JOB = re.compile(
    r"https?://(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9_-]+)/jobs/(\d+)")
_LEVER_JOB = re.compile(
    r"https?://jobs\.lever\.co/([A-Za-z0-9_.-]+)/([0-9a-fA-F-]{36})")
_ASHBY_JOB = re.compile(
    r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)/([0-9a-fA-F-]{36})")
_WORKABLE_JOB = re.compile(
    r"https?://apply\.workable\.com/([A-Za-z0-9_.-]+)/j/([A-Z0-9]{8,})")
_SMARTRECRUITERS_JOB = re.compile(
    r"https?://jobs\.smartrecruiters\.com/([A-Za-z0-9_.-]+)/(\d{6,})")
_RECRUITEE_JOB = re.compile(
    r"https?://([A-Za-z0-9-]+)\.recruitee\.com/o/([A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class Ats:
    """One applicant-tracking system she can reach.

    ADDING ONE IS A ROW. Greenhouse and Lever were two hardcoded regexes
    and two hardcoded URL shapes, so a third system meant editing the
    search list, the matcher and the converter in three places — which is
    how "she only applies on Greenhouse" happens. The search sites, the
    matchers and the apply-URL shapes are all derived from this table now.

    Every system here hosts its application form at a PUBLIC URL. That is
    the whole entry requirement and it is not negotiable: one that needs an
    account is reached through `signup`, which is a different path with a
    different gate, not by adding a row here.
    """
    provider: str
    site: str                       # the host a site: search sweeps
    job: "re.Pattern"               # a job URL -> (token, id)
    apply: "Callable[[str, str], str]"


def _gh_apply(token: str, jid: str) -> str:
    return ("https://boards.greenhouse.io/embed/job_app"
            f"?for={urllib.parse.quote(token)}&token={jid}")


#: Public, login-free application forms, in the order a sweep meets them.
#: Two hosts for Greenhouse because it moved most boards to job-boards.
ATS: tuple[Ats, ...] = (
    Ats("greenhouse", "job-boards.greenhouse.io", _GREENHOUSE_JOB, _gh_apply),
    Ats("greenhouse", "boards.greenhouse.io", _GREENHOUSE_JOB, _gh_apply),
    Ats("lever", "jobs.lever.co", _LEVER_JOB,
        lambda t, j: f"https://jobs.lever.co/{urllib.parse.quote(t)}/{j}/apply"),
    Ats("ashby", "jobs.ashbyhq.com", _ASHBY_JOB,
        lambda t, j: f"https://jobs.ashbyhq.com/{urllib.parse.quote(t)}/{j}/application"),
    Ats("workable", "apply.workable.com", _WORKABLE_JOB,
        lambda t, j: f"https://apply.workable.com/{urllib.parse.quote(t)}/j/{j}/apply/"),
    Ats("smartrecruiters", "jobs.smartrecruiters.com", _SMARTRECRUITERS_JOB,
        lambda t, j: f"https://jobs.smartrecruiters.com/{urllib.parse.quote(t)}/{j}"),
    Ats("recruitee", "recruitee.com", _RECRUITEE_JOB,
        lambda t, j: f"https://{urllib.parse.quote(t)}.recruitee.com/o/{j}/c/new"),
)

#: The hosts a sweep searches, derived so the two cannot drift apart.
SEARCH_SITES = tuple(dict.fromkeys(a.site for a in ATS))


def job_from_url(href: str) -> tuple[Ats, str, str] | None:
    """(system, token, id) for a job URL on any system she can reach."""
    for ats in ATS:
        found = ats.job.search(str(href or ""))
        if found:
            return ats, found.group(1), found.group(2)
    return None


def discover_openings(roles: list[str], *, limit: int = 10, http=None) -> list[dict]:
    """Openings on ANY company's Greenhouse or Lever board that a web search finds.

    One plain HTTP search per board site for all the roles at once (research.http_search -
    Bing's RSS answers a document fetch where a headless browser is
    challenged). A result is kept only when its address is a real job on
    one of those boards, and it is turned into the same public, login-free
    application form the configured boards use.
    """
    if http is None:
        from aletheia import research
        http = research.http_search
    out, seen = [], set()
    roles = [str(r) for r in roles or [] if str(r).strip()]
    # ONE search per board site for every role, OR'd together. One per role per
    # site was fifteen searches a campaign, and live 2026-09-10 DuckDuckGo
    # answered everything after the first few with its challenge page.
    wanted = " OR ".join(f'"{r}"' for r in roles[:MAX_ROLES_PER_SEARCH])
    if len(roles[:MAX_ROLES_PER_SEARCH]) > 1:
        wanted = f"({wanted})"
    # Each site gets its OWN bucket and they are interleaved at the end.
    # They used to share one list with an early return at `limit`, and the
    # two Greenhouse hosts are searched before Lever — so Greenhouse filled
    # the quota and jobs.lever.co was usually never reached at all. That is
    # the same starvation the comment above `discover_openings`'s caller
    # describes one level up, where thirty-six configured boards were
    # crowding out the web search entirely. Being third in a list is not a
    # reason to be invisible.
    buckets: dict[str, list[dict]] = {site: [] for site in SEARCH_SITES}
    for role in roles[:1]:
        for site in SEARCH_SITES:
            found = buckets[site]
            try:
                page = http(f'site:{site} {wanted}')
            except Exception:
                continue
            links = (page or {}).get("links") or []
            if not links and "202" in str((page or {}).get("error") or ""):
                # Every engine refused. Asking again right away only
                # lengthens the refusal.
                break
            for link in links:
                # DuckDuckGo wraps each result in its own redirect; the job's
                # address is inside it, encoded.
                href = urllib.parse.unquote(str(link.get("href") or ""))
                title = " ".join(str(link.get("text") or "").split())[:160]
                # A result reads "Job Application for Account Executive, Growth
                # at Tebra": the job is the part between, the employer the part
                # after, not the board token "tebra" or "gongio".
                employer = ""
                cleaned = re.sub(r"(?i)^job application for\s+", "", title)
                named = re.match(r"(?i)^(.*\S)\s+at\s+(.+)$", cleaned)
                if cleaned != title and named:
                    cleaned, employer = named.group(1), named.group(2)
                if _cut(employer):
                    # "... at Neros ..." - the engine ran out of room. The
                    # board token stands in until the board names itself.
                    employer = ""
                title = cleaned[:120]
                matched = job_from_url(href)
                if not matched:
                    continue
                ats, token, jid = matched
                # `named_by_token` says the employer name is the BOARD TOKEN
                # rather than anything the result actually said — "gongio"
                # instead of Gong. It came in on live the same day this
                # became a table; carried here so it holds for every system
                # rather than only the two that used to be written out.
                job = {"title": title or role, "company": employer or token,
                       "location": "", "posting_url": href,
                       "apply_url": ats.apply(token, jid),
                       "provider": ats.provider, "board": token, "id": jid,
                       "found_by": "web search", "named_by_token": not employer}
                if job["apply_url"] in seen:
                    continue
                seen.add(job["apply_url"])
                found.append(job)
                if len(found) >= limit:
                    break

    # Round-robin, so a site with three results is represented next to one
    # with thirty instead of being cut off behind it.
    waiting = [b for b in buckets.values() if b]
    while waiting and len(out) < limit:
        for bucket in list(waiting):
            if len(out) >= limit:
                break
            out.append(bucket.pop(0))
        waiting = [b for b in waiting if b]
    return out[:limit]


def _say_a_board_is_gone(gone: list[dict]) -> None:
    """A dead board is fewer companies searched, silently. Say it once.

    The journal already recorded "3 board(s) failed" every single time,
    and a line in an append-only file is not somebody being told. The
    notification is deduped on the board token, so it appears once and
    stays put until he acknowledges it — a board that is gone today is
    gone tomorrow, and nagging about it daily would train him to ignore
    the one that matters.

    Never raises: a search must not fail because it could not complain.
    """
    for failure in gone:
        try:
            from aletheia import notifications
            company = failure.get("company") or failure["board"]
            provider = failure.get("provider") or "?"
            notifications.publish(
                f"Job board gone: {company}",
                f"{company} no longer publishes a {provider} board at "
                f"'{failure['board']}' — every search since has covered one "
                f"company fewer than {BOARDS_PATH.name} claims. Fix the token "
                f"or remove the line; `python -m aletheia.jobs --check` "
                f"re-proves the whole file.",
                priority="INFO", source="jobs",
                # PROVIDER AND TOKEN. A token is unique only within a
                # provider — the same company can hold `acme` on Greenhouse
                # and `acme` on Lever, and keying on the token alone
                # silently collapsed two dead boards into one notice.
                dedupe_key=f"jobs:board-gone:{provider}:{failure['board']}")
        except Exception:
            pass


def check() -> dict:
    """Prove every configured board against its provider, right now.

    The board file rots on its own: companies rename, get acquired, or
    move off the provider, and nothing in a search tells you the file has
    quietly shrunk. This is the command that answers "is this list still
    true?".
    """
    rows = boards()

    def one(board):
        provider = PROVIDERS.get(board.get("provider"))
        if provider is None:
            return {**board, "live": False, "count": 0,
                    "why": f"unknown provider {board.get('provider')!r}"}
        try:
            return {**board, "live": True, "count": len(provider(board)), "why": ""}
        except Exception as exc:
            return {**board, "live": False, "count": 0,
                    "why": f"{type(exc).__name__}: {exc}"[:120]}

    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        results = list(pool.map(one, rows))
    live = [r for r in results if r["live"]]
    return {"boards": results, "live": len(live), "dead": len(results) - len(live),
            "openings": sum(r["count"] for r in live)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Real openings she can apply to.")
    ap.add_argument("role", nargs="?")
    ap.add_argument("--where", default="")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--boards", action="store_true", help="list the boards")
    ap.add_argument("--check", action="store_true",
                    help="prove every board against its provider right now")
    args = ap.parse_args(argv)
    if args.check:
        out = check()
        for row in sorted(out["boards"], key=lambda r: (r["live"], r["count"])):
            mark = f"{row['count']:>5} open" if row["live"] else "  DEAD    "
            print(f"{mark}  {row.get('provider','?'):11} {row['token']:16} "
                  f"{row.get('company','')}{'  — ' + row['why'] if row['why'] else ''}")
        print(f"\n{out['live']} live, {out['dead']} dead, "
              f"{out['openings']} openings", file=sys.stderr)
        return 1 if out["dead"] else 0
    if args.boards or not args.role:
        for board in boards():
            print(f"{board.get('provider','?'):11} {board['token']:16} "
                  f"{board.get('company','')}")
        return 0
    try:
        out = search(args.role, where=args.where, limit=args.limit)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for job in out["matches"]:
        print(f"{job['company']:14} {job['title'][:52]:54} {job['location'][:24]}")
        print(f"               {job['apply_url']}")
    print(f"\n{speech.count_phrase(out['matched'], 'match')} across "
          f"{speech.count_phrase(out['searched'], 'board')}",
          file=sys.stderr)
    for failure in out["failed"]:
        print(f"  board {failure['board']} failed: {failure['why']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
