"""Companies whose jobs live only on their own website.

His words, 2026-09-13: *"there are companies all over the country that
only have [jobs] on their website. Like, I've never heard of that I
probably would like to work at."*

He is right, and it is the largest hole in job discovery. `jobs.ATS`
reaches six applicant-tracking systems — thousands of employers, but all
of them employers who bought an ATS. The manufacturer in Sioux Falls, the
regional insurer, the family firm with forty people and a good job: none
of them are on Greenhouse. They have a careers page. Nothing in this
repository has ever looked at one.

**WHAT THIS DOES.** Finds a company's own careers page, reads the openings
off it, and says which of them is a real posting. That is all. Applying is
somebody else's job — `formfill` reads the form, `signup` handles a login
wall, `apply_run` stages it under an approval. This module finds the door.

**THREE THINGS IT REFUSES TO GUESS**, because a wrong guess here is worse
than nothing:

1. **A careers page is not any page with "careers" in the URL.** A blog
   post about company culture, a press release about hiring, a
   third-party aggregator's page ABOUT the company — all of them match a
   naive pattern and none of them is a place to apply. `looks_like_careers`
   wants the page to actually list positions.
2. **A posting is not a link that says "Apply".** Half the "Apply" links
   on the internet go to a login wall, a PDF, or an email address. What it
   IS gets recorded (`kind`), so the caller can tell a form from a mailto
   from a dead end rather than discovering it three steps later.
3. **An ATS link found on a careers page is handed BACK to `jobs`.** Most
   mid-size companies have a careers page that links out to Greenhouse.
   Re-implementing that here would be a second path that drifts from the
   first; `jobs.job_from_url` already knows those shapes and stays the one
   implementation.

**UNPROVEN.** No real careers page has been read by this module. Company
sites are more varied than any ATS, and the first real sweep is where that
shows. It is EXPERIMENTAL in the registry and says so.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse

from aletheia import journal

ACTOR = "aletheia-careers"

#: A page that lists jobs says so in these words. Matched on the page's
#: TEXT, not its address: "/careers" is on a thousand pages that are about
#: working somewhere rather than places to apply.
_LISTS_JOBS = re.compile(
    r"open (?:positions|roles|jobs)|current (?:openings|opportunities|vacancies)"
    r"|job openings|available positions|view all jobs|browse (?:jobs|openings)"
    r"|apply now|join (?:our|the) team|we(?:'|’)re hiring|now hiring",
    re.I)

#: A page that says there is nothing, which is an ANSWER and not a failure.
_NO_OPENINGS = re.compile(
    r"no (?:current |open )?(?:positions|openings|vacancies|opportunities)"
    r"|not (?:currently )?hiring|check back",
    re.I)

#: Where a careers page usually lives, tried in order when a search finds
#: nothing. Cheap, and a 404 costs one request.
COMMON_PATHS = ("/careers", "/careers/", "/jobs", "/jobs/", "/about/careers",
                "/company/careers", "/join-us", "/work-with-us")

#: A link on a careers page that is probably one job.
_JOB_WORDS = re.compile(
    r"\b(?:apply|position|opening|job|role|vacancy|opportunit)", re.I)

#: Addresses that are never a job posting, however they are labelled.
_NOT_A_JOB = re.compile(
    r"\.(?:pdf|docx?|jpe?g|png|gif|zip)(?:$|\?)"
    r"|/(?:privacy|terms|cookie|legal|blog|news|press|about|contact)(?:/|$)"
    r"|^(?:tel|javascript):"
    r"|(?:facebook|twitter|x|linkedin|instagram|youtube)\.com",
    re.I)

FORM = "form"          # a page with an application form on it
MAILTO = "mailto"      # "send your resume to jobs@..."
ATS = "ats"            # links out to Greenhouse/Lever/etc — jobs.py owns it
PAGE = "page"          # a posting, application route not yet known

NOTHING_OPEN = "nothing_open"
NOT_A_CAREERS_PAGE = "not_a_careers_page"
UNREADABLE = "unreadable"


def looks_like_careers(text: str) -> bool:
    """Does this page actually LIST jobs?

    A page about working somewhere is not a page to apply on, and the two
    are indistinguishable by URL. "We're hiring" on a marketing page is
    the false positive this accepts on purpose: it is nearly always a link
    away from the real list, and `openings_on` follows links.
    """
    return bool(_LISTS_JOBS.search(str(text or "")))


def says_nothing_open(text: str) -> bool:
    """"No current openings" is an ANSWER. Reported as such rather than as
    a page that could not be read — a company with nothing open today is
    worth asking again next month, and a broken parser is not."""
    return bool(_NO_OPENINGS.search(str(text or "")))


def _absolute(href: str, base: str) -> str:
    try:
        return urllib.parse.urljoin(base, str(href or "").strip())
    except Exception:
        return ""


def classify(href: str) -> str:
    """What kind of thing this link is. `ats` is handed back to `jobs`."""
    url = str(href or "").strip()
    if url.casefold().startswith("mailto:"):
        return MAILTO
    try:
        from aletheia import jobs
        if jobs.job_from_url(url):
            return ATS
    except Exception:
        pass
    return PAGE


def openings_on(url: str, *, reader=None) -> dict:
    """Every opening a company's careers page lists.

    Returns the postings AND a state, because "nothing open" and "I could
    not read this" are different answers and only one of them means try
    again with a different page.
    """
    if reader is None:
        from aletheia import browse
        reader = browse.read_page
    try:
        page = reader(url)
    except Exception as exc:
        return {"state": UNREADABLE, "url": url, "openings": [],
                "why": f"could not open the careers page: {exc}"}

    text = str((page or {}).get("text") or "")
    base = str((page or {}).get("url") or url)
    links = (page or {}).get("links") or []

    found, seen = [], set()
    for link in links:
        href = _absolute(link.get("href"), base)
        label = " ".join(str(link.get("text") or "").split())[:120]
        if not href or href in seen:
            continue
        if _NOT_A_JOB.search(href):
            continue
        kind = classify(href)
        # A link is a posting if it SAYS so, or if it is an ATS job — those
        # are unambiguous and often have a bare title as their label.
        if kind != ATS and not (_JOB_WORDS.search(label) or _JOB_WORDS.search(href)):
            continue
        seen.add(href)
        found.append({"title": label, "url": href, "kind": kind,
                      "found_by": "careers page", "careers_page": base})

    if not found:
        if says_nothing_open(text):
            return {"state": NOTHING_OPEN, "url": base, "openings": [],
                    "why": "the page says there is nothing open right now"}
        if not looks_like_careers(text):
            return {"state": NOT_A_CAREERS_PAGE, "url": base, "openings": [],
                    "why": "this page does not list jobs"}
        return {"state": UNREADABLE, "url": base, "openings": [],
                "why": "the page lists jobs but none of its links read as one"}

    journal.append("action", f"{ACTOR}:read",
                   f"read {base} — {len(found)} opening(s) listed", actor=ACTOR)
    return {"state": "ok", "url": base, "openings": found}


def as_openings(rows: list[dict], *, company: str = "") -> list[dict]:
    """Careers-page postings in the same shape `jobs` returns.

    So the campaign does not learn a second vocabulary. Three kinds get
    three treatments, and the differences are real:

      * an ATS link is converted by `jobs.job_from_url`, which already
        knows how to turn it into a public application form;
      * an ordinary posting page IS its own apply URL — `apply_run` reads
        it, and if it turns out to be a login wall `signup` names it;
      * a mailto is DROPPED here, because the form path cannot use one.
        It is not lost: the row keeps its kind, and applying by email is a
        capability that does not exist yet rather than one to fake.
    """
    out = []
    for row in rows or []:
        kind, url = row.get("kind"), str(row.get("url") or "")
        if kind == MAILTO or not url:
            continue
        provider, board, jid = "careers-page", "", ""
        apply_url = url
        if kind == ATS:
            try:
                from aletheia import jobs
                matched = jobs.job_from_url(url)
            except Exception:
                matched = None
            if matched:
                ats, board, jid = matched
                provider, apply_url = ats.provider, ats.apply(board, jid)
        out.append({
            "title": row.get("title") or "", "company": company or "",
            # A careers page rarely says where a job is, and guessing is
            # the bug this whole change is about.
            "location": "", "location_known": False,
            "posting_url": url, "apply_url": apply_url,
            "provider": provider, "board": board, "id": jid,
            "found_by": "", "careers_page": row.get("careers_page", ""),
        })
    return out


def find_careers_page(company: str, *, http=None, reader=None,
                      site: str = "") -> dict:
    """Where a company lists its jobs.

    A web search first, because a company's careers page is usually the
    first thing a search for its name and "careers" returns. When that
    fails and the company's own domain is known, the common paths are
    tried — `/careers` costs one request and answers most of the rest.
    """
    name = " ".join(str(company or "").split())
    if not name:
        raise ValueError("a company needs a name to look for")
    if http is None:
        from aletheia import research
        http = research.http_search

    tried = []
    try:
        page = http(f'"{name}" careers jobs openings')
    except Exception:
        page = None
    for link in ((page or {}).get("links") or [])[:8]:
        href = str(link.get("href") or "")
        if not href or _NOT_A_JOB.search(href):
            continue
        # An aggregator's page about the company is not the company's page.
        host = urllib.parse.urlparse(href).netloc.casefold()
        if any(bad in host for bad in ("indeed.", "glassdoor.", "ziprecruiter.",
                                       "linkedin.", "simplyhired.", "monster.")):
            continue
        tried.append(href)
        out = openings_on(href, reader=reader)
        if out["state"] == "ok" or out["state"] == NOTHING_OPEN:
            return {**out, "company": name}

    if site:
        root = site if "://" in site else f"https://{site}"
        for path in COMMON_PATHS:
            guess = urllib.parse.urljoin(root, path)
            tried.append(guess)
            out = openings_on(guess, reader=reader)
            if out["state"] in ("ok", NOTHING_OPEN):
                return {**out, "company": name}

    return {"state": NOT_A_CAREERS_PAGE, "company": name, "openings": [],
            "tried": tried,
            "why": f"no page listing jobs was found for {name}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read a company's own careers page")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_r = sub.add_parser("read", help="openings on a careers page")
    p_r.add_argument("url")
    p_f = sub.add_parser("find", help="find a company's careers page")
    p_f.add_argument("company")
    p_f.add_argument("--site", default="", help="their domain, if you know it")
    args = ap.parse_args(argv)

    out = (openings_on(args.url) if args.cmd == "read"
           else find_careers_page(args.company, site=args.site))
    if out["state"] not in ("ok",):
        print(out.get("why") or out["state"])
        return 1
    for job in out["openings"]:
        print(f"  [{job['kind']:6}] {job['title'][:60]:60} {job['url']}")
    print(f"{len(out['openings'])} opening(s) on {out['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
