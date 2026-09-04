"""Look into something and come back with an answer that cites its sources.

The second mission kind, and the one the operator will use most: *"look into
X and tell me what you find."* It is the right one to build after
`fix_projects` because it touches nothing dangerous — it only ever READS —
and because it is the shape of half the things a person actually wants an
assistant for.

What makes this different from asking a model the same question: **every
claim carries the page it came from, and a claim with no source does not
survive.** A model answering from memory is a plausible paragraph; this is
a paragraph you can check. That distinction is the whole point (§30, §106),
and it is enforced in `_verified()` rather than requested in a prompt.

How it works, and why each step is bounded:

- **Finding pages.** There is no search API here and there will not be one:
  §6 says no API keys, every worker runs on the operator's own
  subscriptions. So she searches the way a person does — the browser, a
  search engine, the result links. That is `browse.read_page`, which is
  read-only and needs no approval.
- **Reading them.** At most `MAX_SOURCES` pages per question, each
  truncated. A research run that reads forty pages is one that spends an
  hour and a subscription's goodwill to answer a question about opening
  hours.
- **Writing it up.** One model call over the collected extracts, returning
  findings each bound to the URL it came from. Anything it cannot source is
  dropped, and the report says how many were dropped rather than hiding it.
- **Delivering it.** The report is a durable document (`aletheia.documents`)
  plus a notification, because an answer that exists only in a log is an
  answer he never receives — the same failure as the follow-up bug.

A research run spends no money, sends nothing, and changes nothing outside
this machine. That is why it can live under a mission budget at all.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from urllib.parse import parse_qs, quote_plus, urlparse

from aletheia import (browse, documents, journal, notifications, policy,
                      reasoner, stateio)

ACTOR = "aletheia-research"

MAX_SOURCES = 5
MAX_QUERIES = 3
MAX_EXTRACT_CHARS = 6_000
MAX_QUESTION_CHARS = 500
SEARCH_URL = "https://duckduckgo.com/html/?q={}"
# Engines, in the order she tries them. The first live run (2026-09-02)
# found DuckDuckGo's HTML endpoint answering the headless browser with a
# "select all squares containing a duck" challenge — one link, no results
# — and Brave, Mojeek and Startpage refusing outright. Bing answers, with
# every result wrapped in a redirect that carries the real address
# base64-encoded (unwrapped below). Wikipedia's own search is the last
# resort and a primary source in its own right. A challenge page is not an
# error, it is a page with no results: it costs one engine, not the
# question.
BING_URL = "https://www.bing.com/search?q={}"
WIKIPEDIA_URL = "https://en.wikipedia.org/w/index.php?search={}&ns0=1&fulltext=1"
# Wikipedia before Bing: on the operator's PC Bing answers the headless
# browser with an unrendered shell whose links belong to some OTHER query
# (asked for Chicago's tallest building, it offered the tallest people),
# and the guard in _results() treats an unrendered page as no results.
SEARCH_ENGINES = (("duckduckgo", SEARCH_URL), ("wikipedia", WIKIPEDIA_URL),
                  ("bing", BING_URL))
# A results page a person could read has more text than a nav bar.
MIN_RESULTS_PAGE_CHARS = 500
_WIKI_ARTICLE = re.compile(r"^https://en\.wikipedia\.org/wiki/[^:#?]+$")

# Never worth reading for a research question, and cheap to exclude before
# spending a page load on them.
SKIP_HOSTS = {
    "duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com",
    "google.com", "www.google.com",
    "bing.com", "www.bing.com", "search.brave.com", "www.mojeek.com",
    "www.startpage.com", "youtube.com", "www.youtube.com",
    "facebook.com", "www.facebook.com", "x.com", "twitter.com",
}

PLAN_SYSTEM = """You turn one research question into search queries.
Return exactly one JSON object: {"queries": [string], "why": string}.
Give between one and three queries. Make them the words a knowledgeable person
would actually type — specific nouns, no filler, no quotes unless a phrase
matters. Prefer queries that would surface primary sources over commentary."""

WRITE_SYSTEM = """You write a sourced research answer from supplied extracts.
Return exactly one JSON object:
{"answer": string, "findings": [{"claim": string, "url": string}],
 "gaps": [string], "confidence": number}

RULES, and the first is absolute:
- Every finding's `url` MUST be one of the urls supplied in the context. Do not
  cite a page you were not given, and do not invent one. A claim you cannot
  attach to a supplied url does not belong in findings at all.
- `answer` is a short direct reply to the question — a few sentences, the way a
  well-informed colleague answers out loud. No preamble, no restating the
  question.
- `gaps` names what the sources did NOT settle. An honest gap is worth more
  than a confident guess; if the sources disagree, say so there.
- `confidence` is 0..1 and reflects the SOURCES, not your fluency."""


class ResearchError(RuntimeError):
    pass


def _plan_validator(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - {"queries", "why"}:
        raise ValueError("invalid research plan fields")
    queries = value.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES:
        raise ValueError(f"queries must be a list of 1..{MAX_QUERIES}")
    clean = []
    for q in queries:
        if not isinstance(q, str) or not q.strip():
            raise ValueError("each query must be a non-empty string")
        clean.append(q.strip()[:200])
    return {"queries": clean, "why": str(value.get("why") or "")[:400]}


def _report_validator(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("report must be an object")
    if set(value) - {"answer", "findings", "gaps", "confidence"}:
        raise ValueError("invalid report fields")
    answer = value.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer must be a non-empty string")
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    for f in findings:
        if not isinstance(f, dict) or set(f) - {"claim", "url"}:
            raise ValueError("each finding is {claim, url}")
        if not isinstance(f.get("claim"), str) or not f["claim"].strip():
            raise ValueError("each finding needs a claim")
        if not isinstance(f.get("url"), str) or not f["url"].strip():
            raise ValueError("each finding needs a url")
    gaps = value.get("gaps", [])
    if not isinstance(gaps, list) or any(not isinstance(g, str) for g in gaps):
        raise ValueError("gaps must be a list of strings")
    try:
        confidence = float(value.get("confidence", 0))
    except (TypeError, ValueError):
        raise ValueError("confidence must be a number") from None
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be 0..1")
    return {"answer": answer.strip(), "findings": findings,
            "gaps": [g.strip() for g in gaps if g.strip()], "confidence": confidence}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").casefold()
    except ValueError:
        return ""


def _unwrap(href: str) -> str:
    """Search engines wrap the real link in a redirect. Follow it here
    rather than loading their hop: one fewer page load, and the source we
    journal is the source we actually read."""
    if "duckduckgo.com/l/" in href:
        try:
            target = parse_qs(urlparse(href).query).get("uddg", [])
            return target[0] if target else href
        except ValueError:
            return href
    if "bing.com/ck/a" in href:
        # Bing: ...&u=a1<urlsafe base64 of the destination>&... — a
        # relative destination (Bing's own images/maps tabs) decodes to a
        # path, which the http(s) check below then drops.
        try:
            packed = parse_qs(urlparse(href).query).get("u", [""])[0]
        except ValueError:
            return href
        if not packed.startswith("a1"):
            return href
        body = packed[2:]
        try:
            return base64.urlsafe_b64decode(
                body + "=" * (-len(body) % 4)).decode("utf-8", "replace")
        except (ValueError, binascii.Error):
            return href
    return href


def _results(engine: str, page: dict, limit: int) -> list[dict]:
    """The usable result links on one engine's page — none for a challenge."""
    if len(str(page.get("text") or "")) < MIN_RESULTS_PAGE_CHARS:
        # A challenge page, or a shell whose results never rendered: the
        # links on it are navigation and stale suggestions, not answers.
        return []
    out, seen = [], set()
    for link in page.get("links", []):
        href = _unwrap(str(link.get("href") or ""))
        if not href.startswith(("http://", "https://")):
            continue
        host = _host(href)
        if not host or host in SKIP_HOSTS:
            continue
        title = (link.get("text") or "").strip()[:160]
        if engine == "wikipedia":
            # One host by construction, so the rule is one page per ARTICLE;
            # `library` tells run() not to collapse these to a single page.
            if not _WIKI_ARTICLE.match(href) or href.endswith("/Main_Page") or href in seen:
                continue
            seen.add(href)
            out.append({"url": href, "title": title, "library": True})
        else:
            if host in seen:
                continue
            seen.add(host)          # one page per site: five views of one outlet
            out.append({"url": href, "title": title})
        if len(out) >= limit:
            break
    return out


HTTP_SEARCH_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HTTP_SEARCH_TIMEOUT_S = 15
# Plain-HTTP engines, in the order measured to answer on the operator's PC
# (2026-09-04). Bing's RSS is a machine format — no markup to scrape, and it
# answered every request; DuckDuckGo's HTML endpoint answered the first
# request and then served its challenge page (HTTP 202) to the same address
# for a while, so it is second. Both are the page anyone gets with curl:
# no key, no cookie, nothing reverse engineered (§6).
BING_RSS_URL = "https://www.bing.com/search?q={}&format=rss"
DDG_HTML_URL = "https://html.duckduckgo.com/html/?q={}"
_RSS_ITEM = re.compile(r"<item>(.*?)</item>", re.S)
_RSS_FIELD = {name: re.compile(rf"<{name}>(.*?)</{name}>", re.S)
              for name in ("title", "link", "description")}
_RESULT_LINK = re.compile(r'class="result__a"\s+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_RESULT_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
_TAGS = re.compile(r"<[^>]+>")
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)


def _fetch(url: str, opener=None) -> tuple[int, str]:
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": HTTP_SEARCH_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"})
    open_ = opener or urllib.request.urlopen
    with open_(req, timeout=HTTP_SEARCH_TIMEOUT_S) as resp:
        return int(getattr(resp, "status", 200) or 200), resp.read(2_000_000).decode("utf-8", "replace")


def _clean(fragment: str) -> str:
    fragment = _CDATA.sub(r"\1", fragment)
    return " ".join(_TAGS.sub(" ", fragment).replace("&amp;", "&").split())


def _parse_bing_rss(xml: str) -> list[dict]:
    links = []
    for item in _RSS_ITEM.findall(xml):
        fields = {k: (rx.search(item).group(1) if rx.search(item) else "")
                  for k, rx in _RSS_FIELD.items()}
        href = _clean(fields["link"])
        if not href.startswith(("http://", "https://")):
            continue
        links.append({"href": href, "text": _clean(fields["title"])[:160],
                      "snippet": _clean(fields["description"])[:300]})
    return links


def _parse_ddg_html(html: str) -> list[dict]:
    links = []
    snippets = [_clean(x) for x in _RESULT_SNIPPET.findall(html)]
    for i, (href, inner) in enumerate(_RESULT_LINK.findall(html)):
        href = href.replace("&amp;", "&")
        if href.startswith("//"):
            href = "https:" + href
        links.append({"href": href, "text": _clean(inner)[:160],
                      "snippet": snippets[i] if i < len(snippets) else ""})
    return links


def http_search(query: str, *, opener=None) -> dict:
    """The search-results page fetched as a plain document, not driven.

    Live on the operator's PC, 2026-09-04, hours before first real use:
    "how much is a 2019 Civic worth" came back "I don't have reliable
    pricing data — the sources are Wikipedia articles about the Accord",
    because every engine the HEADLESS BROWSER visited answered it with a
    challenge or an unrendered shell, and the Wikipedia fallback cannot
    price a car. One ordinary HTTP request to Bing's RSS endpoint returned
    KBB, Edmunds and J.D. Power. The challenge is aimed at automation that
    renders; a document fetch is not that.

    Returns the same shape `browse.read_page` does, so `_results` needs no
    special case, and never raises: an engine that refuses costs this
    attempt, not the question. `error` names the last refusal.
    """
    encoded = quote_plus(query)
    last_error = ""
    for engine, url, parse in (("bing-rss", BING_RSS_URL.format(encoded), _parse_bing_rss),
                               ("duckduckgo-html", DDG_HTML_URL.format(encoded), _parse_ddg_html)):
        try:
            status, body = _fetch(url, opener)
        except Exception as exc:
            last_error = f"{engine}: {type(exc).__name__}"
            continue
        links = parse(body)
        if status != 200 or not links:
            last_error = f"{engine}: HTTP {status}, {len(links)} link(s)"
            continue
        # `_results` treats a page with almost no text as a challenge; the
        # titles and snippets are the text a person would see.
        text = "\n".join(f"{l['text']} — {l['snippet']}" for l in links)
        return {"url": url, "title": f"{engine} results", "text": text,
                "links": links, "engine": engine}
    return {"url": "", "title": "", "text": "", "links": [], "error": last_error}


def find_sources(query: str, *, limit: int = MAX_SOURCES,
                 reader=browse.read_page, http=http_search) -> list[dict]:
    """Search the way a person does — no API key, per §6.

    Failure here is survivable and must not end a run: a search engine that
    changes its markup should cost this query, not the whole question.

    Plain HTTP first (see `http_search`), the driven engines after: the
    order is "what answers on this machine", measured, not a preference.
    """
    if http is not None:
        page = http(query)
        found = _results(page.get("engine") or "http", page, limit)
        if found:
            return found
        journal.append("event", "research",
                       f"http search gave no usable results for {query!r}"
                       + (f" ({page['error']})" if page.get("error") else "")
                       + "; trying the driven engines", actor=ACTOR)
    for engine, template in SEARCH_ENGINES:
        try:
            page = reader(template.format(quote_plus(query)))
        except Exception as exc:
            journal.append("alert", "research",
                           f"{engine} search failed for {query!r}: {type(exc).__name__}",
                           actor=ACTOR)
            continue
        found = _results(engine, page, limit)
        if found:
            return found
        journal.append("event", "research",
                       f"{engine} gave no usable results for {query!r} — a "
                       "challenge page or changed markup; trying the next engine",
                       actor=ACTOR)
    return []


def read_sources(sources: list[dict], *, reader=browse.read_page) -> list[dict]:
    """Read each candidate, keeping what was actually retrieved.

    A page that fails is recorded as a failure rather than silently dropped,
    because "I read five pages" and "I tried five and two refused me" are
    different answers to how much the report is worth.
    """
    read, failed = [], []
    for source in sources:
        policy.ensure_not_halted()
        try:
            page = reader(source["url"])
        except Exception as exc:
            failed.append({"url": source["url"], "reason": type(exc).__name__})
            continue
        text = re.sub(r"\n{3,}", "\n\n", str(page.get("text") or "")).strip()
        if len(text) < 200:
            failed.append({"url": source["url"], "reason": "no readable text"})
            continue
        read.append({
            "url": page.get("url") or source["url"],
            "title": (page.get("title") or source.get("title") or "")[:200],
            "extract": text[:MAX_EXTRACT_CHARS],
        })
    return read, failed


def _bounded(question: str, sources: list[dict],
             limit: int = reasoner.MAX_CONTEXT_BYTES - 512) -> list[dict]:
    """Extracts cut to fit the reasoner's whole-context ceiling.

    Five pages at MAX_EXTRACT_CHARS is ~30 KB and the reasoner refuses
    anything over 8 KB outright — which is how the first live question
    (2026-09-02) found five good sources and then could not write a word.
    Every source keeps a share; the share shrinks until the whole fits.
    """
    per = MAX_EXTRACT_CHARS
    while True:
        rows = [{"url": s["url"], "title": (s.get("title") or "")[:120],
                 "extract": s["extract"][:per]} for s in sources]
        size = len(json.dumps({"question": question, "sources": rows},
                              ensure_ascii=False).encode("utf-8"))
        if size <= limit or per <= 300:
            return rows
        per = int(per * 0.7)


def _verified(report: dict, sources: list[dict]) -> dict:
    """Drop every finding that does not cite a page we actually read.

    This is the line between research and a plausible paragraph, so it is
    code rather than a sentence in a prompt. A model that invents a citation
    is not caught by asking it not to.
    """
    allowed = {s["url"] for s in sources}
    kept = [f for f in report["findings"] if f["url"] in allowed]
    dropped = len(report["findings"]) - len(kept)
    report["findings"] = kept
    report["unsourced_dropped"] = dropped
    if dropped:
        # Said out loud in the report itself: a silent drop would leave him
        # reading a thinner answer with no idea why.
        report["gaps"] = report["gaps"] + [
            f"{dropped} claim(s) were dropped for citing a page that was not read"]
    return report


def run(question: str, *, reader=browse.read_page, think=None,
        http=http_search) -> dict:
    """One research question, end to end, with sources."""
    question = str(question or "").strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question must be 1..{MAX_QUESTION_CHARS} characters")
    policy.ensure_not_halted()
    # Ask the browser whether it exists BEFORE spending a plan on it. Without
    # this, every search raised inside `find_sources`, was swallowed into a
    # journal alert, and `run` ended on "no readable sources were found —
    # it may be something the open web does not answer". That sentence is
    # false and it is the expensive kind of false: it blames the question
    # for a missing dependency, so nobody installs the dependency.
    if reader is browse.read_page:
        usable, why = browse.available()
        if not usable:
            raise ResearchError(
                f"she cannot read web pages right now: {why}. Research really "
                "opens the pages it cites, so there is nothing honest to "
                "return until that is fixed — everything else still works.")
    think = think or reasoner.subscription_json

    plan = think(PLAN_SYSTEM, question, model=reasoner.INTERPRET_MODEL,
                 validator=_plan_validator)

    candidates, seen_hosts = [], set()
    for query in plan["queries"]:
        policy.ensure_not_halted()
        for source in find_sources(query, reader=reader, http=http):
            host = _host(source["url"])
            if host in seen_hosts and not source.get("library"):
                continue
            seen_hosts.add(host)
            candidates.append(source)
        if len(candidates) >= MAX_SOURCES:
            break
    candidates = candidates[:MAX_SOURCES]
    if not candidates:
        raise ResearchError(
            "no readable sources were found for that question — say it "
            "differently, or it may be something the open web does not answer")

    sources, failed = read_sources(candidates, reader=reader)
    if not sources:
        raise ResearchError(
            f"found {len(candidates)} candidate page(s) and could read none of "
            "them")

    report = think(
        WRITE_SYSTEM, question,
        context={"question": question, "sources": _bounded(question, sources)},
        model=reasoner.PLAN_MODEL, validator=_report_validator)
    report = _verified(report, sources)
    report.update({
        "question": question,
        "queries": plan["queries"],
        "sources": [{"url": s["url"], "title": s["title"]} for s in sources],
        "unreadable": failed,
        "at": stateio.utcnow(),
    })
    _deliver(report)
    return report


def as_markdown(report: dict) -> str:
    lines = [f"# {report['question']}", "", report["answer"], ""]
    if report.get("findings"):
        lines += ["## What the sources say", ""]
        lines += [f"- {f['claim']}  \n  <{f['url']}>" for f in report["findings"]]
        lines.append("")
    if report.get("gaps"):
        lines += ["## What this does not settle", ""]
        lines += [f"- {g}" for g in report["gaps"]] + [""]
    lines += ["## Sources read", ""]
    lines += [f"- [{s['title'] or s['url']}]({s['url']})" for s in report["sources"]]
    if report.get("unreadable"):
        lines += ["", "## Could not be read", ""]
        lines += [f"- {u['url']} ({u['reason']})" for u in report["unreadable"]]
    lines += ["", f"_Confidence {report['confidence']:.0%} · {report['at']}_"]
    return "\n".join(lines)


def _deliver(report: dict) -> str:
    """Durable document + a notification. An answer that exists only in a log
    is an answer he never receives — the same failure as the follow-up bug."""
    doc_id = "research-" + re.sub(r"[^a-z0-9]+", "-",
                                  report["question"].casefold())[:48].strip("-")
    doc_id = f"{doc_id}-{report['at'][:10].replace('-', '')}"
    # The same question asked twice in a day is two reports, not one
    # report and one alert: the store refuses to overwrite (a document is
    # evidence), so the second takes the time of day as well. 2026-09-02,
    # live: the tallest building in Chicago, asked again, "could not store
    # the report: FileExistsError" — and the answer he was given had no
    # document behind it.
    stamp = report["at"][11:19].replace(":", "")
    for candidate in (doc_id, f"{doc_id}-{stamp}"):
        try:
            documents.ingest_text(candidate, title=report["question"],
                                  text=as_markdown(report), source="aletheia.research")
            doc_id = candidate
            break
        except FileExistsError:
            continue
        except Exception as exc:      # a delivery failure must not lose the answer
            journal.append("alert", "research",
                           f"could not store the report: {type(exc).__name__}",
                           actor=ACTOR)
            break
    else:
        journal.append("alert", "research",
                       "could not store the report: a report with this id "
                       "already exists for this second", actor=ACTOR)
    try:
        notifications.publish(
            f"Looked into: {report['question'][:70]}",
            report["answer"][:400] + f"\n\n{len(report['sources'])} source(s) read.",
            priority="NORMAL", source="research", dedupe_key=doc_id)
    except Exception:
        pass
    journal.append(
        "action", "research",
        f"{report['question'][:80]} — {len(report['findings'])} sourced "
        f"finding(s) from {len(report['sources'])} page(s)", actor=ACTOR)
    return doc_id


def spoken(report: dict) -> str:
    """Out loud: the answer, then where it came from. Not the whole report —
    he asked a question, not for a document to be read at him."""
    n = len(report["sources"])
    return (f"{report['answer']} "
            f"That is from {n} source{'s' if n != 1 else ''}; "
            "the full write-up is in your documents.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Look into something, with sources.")
    ap.add_argument("question")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    try:
        report = run(args.question)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2) if args.json else as_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
