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

# Never worth reading for a research question, and cheap to exclude before
# spending a page load on them.
SKIP_HOSTS = {
    "duckduckgo.com", "html.duckduckgo.com", "google.com", "www.google.com",
    "bing.com", "www.bing.com", "youtube.com", "www.youtube.com",
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
    """DuckDuckGo's HTML results wrap the real link in a redirect. Follow it
    here rather than loading their hop: one fewer page load, and the source
    we journal is the source we actually read."""
    if "duckduckgo.com/l/" not in href:
        return href
    try:
        target = parse_qs(urlparse(href).query).get("uddg", [])
        return target[0] if target else href
    except ValueError:
        return href


def find_sources(query: str, *, limit: int = MAX_SOURCES,
                 reader=browse.read_page) -> list[dict]:
    """Search the way a person does — no API key, per §6.

    Failure here is survivable and must not end a run: a search engine that
    changes its markup should cost this query, not the whole question.
    """
    try:
        page = reader(SEARCH_URL.format(quote_plus(query)))
    except Exception as exc:
        journal.append("alert", "research",
                       f"search failed for {query!r}: {type(exc).__name__}",
                       actor=ACTOR)
        return []
    out, seen = [], set()
    for link in page.get("links", []):
        href = _unwrap(str(link.get("href") or ""))
        if not href.startswith(("http://", "https://")):
            continue
        host = _host(href)
        if not host or host in SKIP_HOSTS or host in seen:
            continue
        seen.add(host)          # one page per site: five views of one outlet
        out.append({"url": href, "title": (link.get("text") or "").strip()[:160]})
        if len(out) >= limit:
            break
    return out


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


def run(question: str, *, reader=browse.read_page, think=None) -> dict:
    """One research question, end to end, with sources."""
    question = str(question or "").strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question must be 1..{MAX_QUESTION_CHARS} characters")
    policy.ensure_not_halted()
    think = think or reasoner.subscription_json

    plan = think(PLAN_SYSTEM, question, model=reasoner.INTERPRET_MODEL,
                 validator=_plan_validator)

    candidates, seen_hosts = [], set()
    for query in plan["queries"]:
        policy.ensure_not_halted()
        for source in find_sources(query, reader=reader):
            host = _host(source["url"])
            if host in seen_hosts:
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
        context={"question": question,
                 "sources": [{"url": s["url"], "title": s["title"],
                              "extract": s["extract"]} for s in sources]},
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
    try:
        documents.ingest_text(doc_id, title=report["question"],
                              text=as_markdown(report), source="aletheia.research")
    except Exception as exc:      # a delivery failure must not lose the answer
        journal.append("alert", "research",
                       f"could not store the report: {type(exc).__name__}",
                       actor=ACTOR)
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
