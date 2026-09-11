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

from aletheia import journal, speech
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
    """The company boards she can reach. Data, not a literal."""
    try:
        value = json.loads(BOARDS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = value.get("boards") if isinstance(value, dict) else value
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("token")]


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


def _greenhouse(board: dict) -> list[dict]:
    token = board["token"]
    data = _fetch(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    out = []
    for job in data.get("jobs", []):
        jid = job.get("id")
        if not jid:
            continue
        out.append({
            "title": (job.get("title") or "").strip(),
            "company": board.get("company") or token,
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


def _score(job: dict, terms: list[str], where: str, *, exclude=frozenset()) -> float:
    words = _title_words(job["title"])
    if exclude and (words & exclude or _MANAGES_PEOPLE.search(str(job["title"]))):
        return 0.0
    # Whole words, and every word that is not generic: "account" is not in
    # "accounts receivable", and "manager" alone is not a match.
    needed = [t for t in terms if t not in GENERIC_TITLE_WORDS] or list(terms)
    if not all(t in words for t in needed):
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
                                 "why": problem})
                continue
            everything.extend(jobs)
    _say_a_board_is_gone([f for f in failures if f["gone"]])
    return everything, failures, len(rows)


def search(role: str, *, where: str = "", limit: int = 10,
           fetcher=None) -> dict:
    """Real openings she can really apply to, most relevant first."""
    return search_many([role], where=where, limit=limit, fetcher=fetcher)


def search_many(roles: list[str], *, where: str = "", limit: int = 10,
                fetcher=None, discover: bool = False, http=None,
                country: str = "", exclude=()) -> dict:
    """Openings for ANY of these roles, each scored by the role it fits best.

    `discover` adds openings on boards nobody configured: a web search for
    each role on Greenhouse and Lever, whose public forms need no login. The
    configured list is where she starts, never where she stops - "it should
    be able to apply to any job" was his rule, and twenty-four tech
    companies are not any job.
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
    # Two from the boards, then one the web found, so both get tried.
    matches, b, w = [], 0, 0
    while len(matches) < cap and (b < len(board) or w < len(web)):
        if w < len(web) and (len(matches) % 3 == 2 or b >= len(board)):
            matches.append(web[w])
            w += 1
        else:
            matches.append(board[b])
            b += 1
    discovered = [job for job in matches if job.get("found_by") == "web search"]
    journal.append("action", "jobs",
                   f"searched {speech.count_phrase(searched, 'board')} for "
                   f"{', '.join(roles)!r}: {speech.count_phrase(len(found), 'match')}, "
                   f"{len(discovered)} more by web search, "
                   f"{speech.count_phrase(len(failures), 'board')} failed",
                   actor=ACTOR)
    return {"role": ", ".join(roles), "roles": list(roles), "where": where,
            "matches": matches, "searched": searched, "matched": len(found),
            "discovered": len(discovered), "failed": failures}


_GREENHOUSE_JOB = re.compile(
    r"https?://(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9_-]+)/jobs/(\d+)")
_LEVER_JOB = re.compile(
    r"https?://jobs\.lever\.co/([A-Za-z0-9_.-]+)/([0-9a-fA-F-]{36})")


def discover_openings(roles: list[str], *, limit: int = 10, http=None) -> list[dict]:
    """Openings on ANY company's Greenhouse or Lever board that a web search finds.

    One plain HTTP search per role per provider (research.http_search -
    Bing's RSS answers a document fetch where a headless browser is
    challenged). A result is kept only when its address is a real job on
    one of those boards, and it is turned into the same public, login-free
    application form the configured boards use.
    """
    if http is None:
        from aletheia import research
        http = research.http_search
    out, seen = [], set()
    for role in roles or []:
        # Greenhouse moved most boards to job-boards.greenhouse.io; both are searched.
        for site in ("job-boards.greenhouse.io", "boards.greenhouse.io", "jobs.lever.co"):
            if len(out) >= limit:
                return out
            try:
                page = http(f'site:{site} "{role}"')
            except Exception:
                continue
            for link in (page or {}).get("links") or []:
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
                title = cleaned[:120]
                green, lever = _GREENHOUSE_JOB.search(href), _LEVER_JOB.search(href)
                if green:
                    token, jid = green.group(1), green.group(2)
                    job = {"title": title or role, "company": employer or token, "location": "",
                           "posting_url": href,
                           "apply_url": ("https://boards.greenhouse.io/embed/job_app"
                                         f"?for={urllib.parse.quote(token)}&token={jid}"),
                           "provider": "greenhouse", "board": token, "id": jid,
                           "found_by": "web search"}
                elif lever:
                    token, jid = lever.group(1), lever.group(2)
                    job = {"title": title or role, "company": employer or token, "location": "",
                           "posting_url": href,
                           "apply_url": f"https://jobs.lever.co/{urllib.parse.quote(token)}/{jid}/apply",
                           "provider": "lever", "board": token, "id": jid,
                           "found_by": "web search"}
                else:
                    continue
                if job["apply_url"] in seen:
                    continue
                seen.add(job["apply_url"])
                out.append(job)
                if len(out) >= limit:
                    return out
    return out


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
