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

from aletheia import journal
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


def _score(job: dict, terms: list[str], where: str) -> float:
    title = job["title"].casefold()
    hits = sum(1 for t in terms if t in title)
    if not hits:
        return 0.0
    value = hits / max(1, len(terms))
    if where:
        place = where.casefold()
        loc = job["location"].casefold()
        if place in loc or (place in ("remote", "anywhere") and "remote" in loc):
            value += 0.5
        elif place not in ("remote", "anywhere") and loc and place not in loc:
            value -= 0.35
    return value


def search(role: str, *, where: str = "", limit: int = 10,
           fetcher=None) -> dict:
    """Real openings she can really apply to, most relevant first."""
    terms = _terms(role)
    if not terms:
        raise ValueError("say what kind of role")
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

    found, failures = [], []
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        for board, jobs, problem in pool.map(one, rows):
            if problem:
                failures.append({"board": board.get("token"),
                                 "company": board.get("company", ""),
                                 "provider": board.get("provider", ""),
                                 "gone": problem.startswith("GONE:"),
                                 "why": problem})
                continue
            for job in jobs:
                value = _score(job, terms, where)
                if value > 0:
                    found.append((value, job))
    found.sort(key=lambda row: row[0], reverse=True)
    matches = [job for _v, job in found[:max(1, min(int(limit), MAX_RESULTS))]]
    journal.append("action", "jobs",
                   f"searched {len(rows)} board(s) for {role!r}: "
                   f"{len(found)} match(es), {len(failures)} board(s) failed",
                   actor=ACTOR)
    _say_a_board_is_gone([f for f in failures if f["gone"]])
    return {"role": role, "where": where, "matches": matches,
            "searched": len(rows), "matched": len(found), "failed": failures}


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
    print(f"\n{out['matched']} match(es) across {out['searched']} board(s)",
          file=sys.stderr)
    for failure in out["failed"]:
        print(f"  board {failure['board']} failed: {failure['why']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
