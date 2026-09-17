"""Observations for a study: what a page, a feed, a public API or his own repository SAYS, measured.

His brief addendum (docs/CONTINUITY_BRIEF.md, 2026-09-17): *"study named or
discovered comparables deeply ... with provenance for every observation;
open-world content stays untrusted data"* and *"the same lens applied to his own
project ... so differences are measured, not asserted."*

AN OBSERVATION is one durable record (`state/private/studies/<study>/evidence/<id>.json`):

    id           ev-<hash>                         what a claim cites
    target       the URL or repository path it was read from
    role         subject | comparable:<key>        whose it is
    source       which observation source read it (below)
    method       how, in words (a plain HTTP GET that robots.txt allows, a public API, git ls-files)
    fetched_at   when
    status       the HTTP status or "read"
    provenance   tools.UNTRUSTED_WEB for anything from outside this machine,
                 tools.TRUSTED_TOOL_OUTPUT for his own repository (its text is still data)
    metrics      numbers extracted DETERMINISTICALLY (no model): counts, lengths,
                 structure, cadence
    structure    headings, early action labels, feed titles: short, scrubbed
    excerpt      bounded, scrubbed text; shown to a model only inside a field labelled
                 untrusted, never as an instruction
    digest       of the content, so "did it change" is a comparison, not a guess

SOURCES ARE PLUGGABLE AND CHOSEN BY CAPABILITY. Each source says what it reads
(`reads`: a URL or a local path) and what it yields; `sources_for(target)` picks
the ones that can read a target. Nothing here knows any platform or any kind of
project:

    web_page     any public HTML page, over plain HTTP (no browser)
    feed         any RSS or Atom feed; a page that links one (<link rel=alternate>)
                 has it read too, so a publishing cadence is measured wherever it exists
    public_api   a public JSON API, described as DATA in config/observation_sources.json
                 (a URL pattern, the calls, the fields): adding a platform is a reviewed
                 data edit, never code
    local_repo   his project's committed files (git ls-files) at a path

POLITE BY CONSTRUCTION. robots.txt is honoured for pages and feeds; a domain whose
terms forbid automation (`site_skills` manual_only) is never read; one request per
host every few seconds; a request budget per study; a cached reading is reused
rather than fetched again. Nothing here logs in, posts, submits or spends.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from aletheia import stateio
from aletheia.fleet import REPO_ROOT

ACTOR = "aletheia-study"
USER_AGENT = "Aletheia-study/1 (a personal assistant reading public pages for its owner; read-only)"
TIMEOUT_S = 20
MAX_BYTES = 1_500_000
MAX_EXCERPT = 4_000
MAX_STRUCTURE_ROWS = 24
HOST_INTERVAL_S = 3.0
MAX_REQUESTS_PER_STUDY = 40
CACHE_S = 6 * 3600
#: The public-API descriptions: reviewed data, read only (talk.SANDBOX_READ_ONLY).
SOURCES_CONFIG = REPO_ROOT / "config" / "observation_sources.json"

UNTRUSTED = "UNTRUSTED_WEB"
LOCAL = "TRUSTED_TOOL_OUTPUT"

#: Every metric an extractor can produce, with what it counts. The lens may only
#: name metrics from here, so a lens is always something she can MEASURE.
METRICS: dict[str, str] = {
    "words": "visible words in the document",
    "sentences": "sentences in the visible text",
    "avg_sentence_words": "average words per sentence",
    "headings": "headings of any level",
    "top_heading_words": "words in the first top-level heading",
    "first_screen_words": "words before the second heading (what is read first)",
    "paragraphs": "paragraphs",
    "list_items": "list items",
    "links": "links",
    "external_links": "links to other hosts",
    "early_actions": "links and buttons with short labels before the second heading",
    "buttons": "buttons",
    "forms": "forms",
    "inputs": "form inputs",
    "images": "images",
    "images_with_alt_ratio": "share of images with alt text (0..1)",
    "embeds": "embedded media or frames",
    "code_blocks": "code or preformatted blocks",
    "tables": "tables",
    "quotes": "quotations",
    "numbers": "numbers written in the text (figures, counts, prices, dates)",
    "title_words": "words in the document title",
    "description_words": "words in the meta description",
    "feeds_linked": "feeds the page links to",
    "entries": "entries in a feed or dated series",
    "entries_per_week": "entries per week across the series",
    "median_gap_days": "median days between consecutive entries",
    "last_entry_age_days": "days since the newest entry",
    "entry_title_words": "median words in an entry title",
    "tracked_files": "files committed to the repository",
    "doc_files": "documentation files committed (markdown, text)",
}
#: API fields become metrics named by the data file, prefixed so they never collide.
API_PREFIX = "api."

_HOST_LOCK = threading.Lock()
_LAST_HIT: dict[str, float] = {}
_ROBOTS: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}


class ObservationRefused(RuntimeError):
    """A read that politeness, terms or budget forbids. Recorded, never retried blindly."""


# ---- time and store -------------------------------------------------------------------

def _now(now: dt.datetime | None = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    return (when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


def evidence_dir(study_id: str) -> Path:
    return stateio.private_dir("studies", study_id, "evidence")


def load(study_id: str, evidence_id: str) -> dict:
    return stateio.read_json(evidence_dir(study_id) / f"{stateio.safe_id(evidence_id, name='evidence id')}.json")


def all_evidence(study_id: str) -> list[dict]:
    root = evidence_dir(study_id)
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("ev-*.json")):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("id") == path.stem:
            out.append(value)
    return sorted(out, key=lambda e: (e.get("fetched_at") or "", e["id"]))


def _clean(text: Any, limit: int) -> str:
    from aletheia import sensitivity
    value = sensitivity.clean(" ".join(str(text if text is not None else "").split()))
    return value[:limit]


def record(study_id: str, *, target: str, role: str, source: str, method: str, status: Any,
           provenance: str, metrics: dict, structure: dict | None = None, excerpt: str = "",
           content: str = "", now: dt.datetime | None = None, extra: dict | None = None) -> dict:
    """Write one observation. Every field of provenance is required; a reading without
    them is not evidence."""
    now = _now(now)
    if not str(target or "").strip() or not str(method or "").strip() or not str(source or "").strip():
        raise ValueError("an observation needs its target, source and method")
    if provenance not in (UNTRUSTED, LOCAL):
        raise ValueError("an observation's provenance must be untrusted web content or local tool output")
    digest = hashlib.sha256(str(content or excerpt).encode("utf-8", "replace")).hexdigest()[:16]
    eid = "ev-" + hashlib.sha256(f"{study_id}|{role}|{target}|{source}|{_stamp(now)}|{digest}".encode()).hexdigest()[:12]
    clean_structure = {}
    for key, rows in (structure or {}).items():
        if isinstance(rows, list):
            clean_structure[str(key)[:40]] = [_clean(r, 300 if key == "links" else 160) for r in rows[:MAX_STRUCTURE_ROWS]
                                              if str(r).strip()]
    value = {
        "version": 1, "id": eid, "study": study_id, "target": str(target)[:500], "role": str(role)[:80],
        "source": source, "method": str(method)[:200], "fetched_at": _stamp(now), "status": status,
        "provenance": provenance,
        "metrics": {str(k)[:60]: (round(float(v), 3) if isinstance(v, (int, float)) and not isinstance(v, bool)
                                  else v) for k, v in (metrics or {}).items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)},
        "structure": clean_structure, "excerpt": _clean(excerpt, MAX_EXCERPT), "digest": digest,
        **(extra or {}),
    }
    stateio.write_json_atomic(evidence_dir(study_id) / f"{eid}.json", value)
    return value


# ---- politeness ------------------------------------------------------------------------

def _host(url: str) -> str:
    return urllib.parse.urlsplit(str(url or "")).netloc.lower().split("@")[-1].split(":")[0]


def _terms_forbid(url: str) -> str:
    """Why a domain's terms forbid automated reading (site_skills' manual floor), or ""."""
    try:
        from aletheia import site_skills
        skill = site_skills.for_domain(url)
    except Exception:  # noqa: BLE001 - no skills known is not a refusal
        return ""
    if str(skill.get("mode") or "") == "manual_only":
        return f"the terms of {_host(url)} forbid automated access"
    return ""


def robots_allow(url: str, *, opener: Callable | None = None) -> bool:
    """robots.txt for a page or feed. An unreadable robots file allows, as the convention says;
    a 401/403 on robots.txt disallows."""
    parts = urllib.parse.urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    cached = _ROBOTS.get(root)
    if cached and time.monotonic() - cached[0] < CACHE_S:
        parser = cached[1]
    else:
        parser = urllib.robotparser.RobotFileParser()
        try:
            status, body, _ctype, _final = _get(root + "/robots.txt", opener=opener, polite=False)
            if status in (401, 403):
                parser.disallow_all = True
            elif status >= 400:
                parser.allow_all = True
            else:
                parser.parse(body.splitlines())
        except Exception:  # noqa: BLE001
            parser = None
        _ROBOTS[root] = (time.monotonic(), parser)
    if parser is None:
        return True
    return parser.can_fetch(USER_AGENT, url)


def _wait_turn(host: str, sleep: Callable[[float], None] = time.sleep) -> None:
    with _HOST_LOCK:
        last = _LAST_HIT.get(host)
        gap = HOST_INTERVAL_S - (time.monotonic() - last) if last is not None else 0
        if gap > 0:
            sleep(gap)
        _LAST_HIT[host] = time.monotonic()


def _get(url: str, *, accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
         opener: Callable | None = None, polite: bool = True) -> tuple[int, str, str, str]:
    """(status, body, content type, final url). Plain HTTP; never raises for an HTTP status."""
    if not re.match(r"^https?://", str(url or "")):
        raise ObservationRefused("only http(s) addresses are read")
    if polite:
        _wait_turn(_host(url))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                               "Accept-Language": "en-US,en;q=0.8"})
    open_ = opener or urllib.request.urlopen
    try:
        with open_(req, timeout=TIMEOUT_S) as resp:
            body = resp.read(MAX_BYTES).decode("utf-8", "replace")
            ctype = str((getattr(resp, "headers", None) or {}).get("Content-Type", "") or "")
            final = resp.geturl() if hasattr(resp, "geturl") else url
            return int(getattr(resp, "status", 200) or 200), body, ctype, final
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(50_000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        return int(exc.code), body, "", url


class Budget:
    """How many requests one research pass may still make."""

    def __init__(self, limit: int = MAX_REQUESTS_PER_STUDY):
        self.limit, self.used = int(limit), 0

    def spend(self) -> None:
        if self.used >= self.limit:
            raise ObservationRefused(f"the study's request budget ({self.limit}) is spent")
        self.used += 1


# ---- deterministic extraction ------------------------------------------------------------

_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,.]*%?(?![\w])")


def _words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def text_metrics(text: str) -> dict:
    words = _words(text)
    sentences = [s for s in _SENTENCE_END.split(text or "") if _words(s)]
    return {"words": len(words), "sentences": len(sentences),
            "avg_sentence_words": round(len(words) / len(sentences), 1) if sentences else 0.0,
            "numbers": len(_NUMBER.findall(text or ""))}


_SKIP_TEXT = {"script", "style", "noscript", "svg", "template", "head"}
_HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK = {"p", "li", "div", "section", "article", "header", "footer", "td", "th", "blockquote", "pre", "br",
          "h1", "h2", "h3", "h4", "h5", "h6", "tr", "main", "aside", "nav", "figcaption", "dd", "dt"}


class _Page(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.skip = 0
        self.stack: list[str] = []
        self.chunks: list[str] = []
        self.title, self.description = "", ""
        self.in_title = False
        self.headings: list[tuple[int, str]] = []
        self.heading: list[str] | None = None
        self.heading_level = 0
        self.links: list[dict] = []
        self.link: dict | None = None
        self.buttons: list[str] = []
        self.button: list[str] | None = None
        self.counts = {"paragraphs": 0, "list_items": 0, "forms": 0, "inputs": 0, "images": 0, "images_alt": 0,
                       "embeds": 0, "code_blocks": 0, "tables": 0, "quotes": 0}
        self.feeds: list[str] = []
        self.actions_before_second_heading: list[str] = []
        self.words_before_second_heading = 0

    def _position_open(self) -> bool:
        return sum(1 for level, _ in self.headings if level <= 2) < 2

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in _SKIP_TEXT:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta" and a.get("name", "").lower() == "description":
            self.description = a.get("content", "")
        if tag == "link" and "alternate" in a.get("rel", "").lower() and \
                re.search(r"(rss|atom)\+xml", a.get("type", ""), re.I) and a.get("href"):
            self.feeds.append(urllib.parse.urljoin(self.base, a["href"]))
        if self.skip:
            return
        if tag in _BLOCK:
            self.chunks.append("\n")
        if tag in _HEADING:
            self.heading, self.heading_level = [], _HEADING[tag]
        elif tag == "a" and a.get("href"):
            self.link = {"href": urllib.parse.urljoin(self.base, a["href"]), "text": []}
        elif tag == "button" or a.get("role") == "button":
            self.button = []
        elif tag == "p":
            self.counts["paragraphs"] += 1
        elif tag == "li":
            self.counts["list_items"] += 1
        elif tag == "form":
            self.counts["forms"] += 1
        elif tag in ("input", "textarea", "select") and a.get("type", "").lower() != "hidden":
            self.counts["inputs"] += 1
        elif tag == "img":
            self.counts["images"] += 1
            if a.get("alt", "").strip():
                self.counts["images_alt"] += 1
        elif tag in ("iframe", "embed", "object", "video", "audio"):
            self.counts["embeds"] += 1
        elif tag == "pre":
            self.counts["code_blocks"] += 1
        elif tag == "table":
            self.counts["tables"] += 1
        elif tag in ("blockquote", "q"):
            self.counts["quotes"] += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TEXT and self.skip:
            self.skip -= 1
        if tag == "title":
            self.in_title = False
        if self.skip:
            return
        if tag in _HEADING and self.heading is not None:
            text = " ".join("".join(self.heading).split())
            if text:
                self.headings.append((self.heading_level, text))
            self.heading = None
        elif tag == "a" and self.link is not None:
            text = " ".join("".join(self.link["text"]).split())
            self.links.append({"href": self.link["href"], "text": text})
            if text and len(_words(text)) <= 5 and self._position_open():
                self.actions_before_second_heading.append(text)
            self.link = None
        elif tag == "button" and self.button is not None:
            text = " ".join("".join(self.button).split())
            self.buttons.append(text)
            if text and len(_words(text)) <= 5 and self._position_open():
                self.actions_before_second_heading.append(text)
            self.button = None
        if tag in _BLOCK:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.skip:
            return
        self.chunks.append(data)
        if self.heading is not None:
            self.heading.append(data)
        if self.link is not None:
            self.link["text"].append(data)
        if self.button is not None:
            self.button.append(data)
        if self._position_open():
            self.words_before_second_heading += len(_words(data))


def extract_html(body: str, url: str) -> dict:
    """Metrics, structure, text and linked feeds of one HTML document. Pure."""
    page = _Page(url)
    try:
        page.feed(body or "")
        page.close()
    except Exception:  # noqa: BLE001 - a malformed page is still measured as far as it parsed
        pass
    text = re.sub(r"[ \t]+", " ", html.unescape("".join(page.chunks)))
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    host = _host(url)
    external = [l for l in page.links if _host(l["href"]) and _host(l["href"]) != host]
    top = next((t for level, t in page.headings if level == 1), page.headings[0][1] if page.headings else "")
    metrics = {**text_metrics(text), "headings": len(page.headings), "top_heading_words": len(_words(top)),
               "first_screen_words": page.words_before_second_heading, "paragraphs": page.counts["paragraphs"],
               "list_items": page.counts["list_items"], "links": len(page.links), "external_links": len(external),
               "early_actions": len(page.actions_before_second_heading), "buttons": len(page.buttons),
               "forms": page.counts["forms"], "inputs": page.counts["inputs"], "images": page.counts["images"],
               "images_with_alt_ratio": round(page.counts["images_alt"] / page.counts["images"], 2)
               if page.counts["images"] else 0.0,
               "embeds": page.counts["embeds"], "code_blocks": page.counts["code_blocks"],
               "tables": page.counts["tables"], "quotes": page.counts["quotes"],
               "title_words": len(_words(html.unescape(page.title))),
               "description_words": len(_words(page.description)), "feeds_linked": len(page.feeds)}
    same_host = [l for l in page.links if _host(l["href"]) == host and l["text"] and len(_words(l["text"])) <= 6]
    structure = {"headings": [f"h{level}: {t}" for level, t in page.headings],
                 "early_actions": page.actions_before_second_heading, "title": [html.unescape(page.title).strip()],
                 "description": [page.description.strip()],
                 "links": [f"{l['text']} -> {l['href']}" for l in same_host[:MAX_STRUCTURE_ROWS]]}
    return {"metrics": metrics, "structure": structure, "text": text, "feeds": list(dict.fromkeys(page.feeds)),
            "links": page.links}


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_MD_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")


def extract_markdown(body: str, where: str = "") -> dict:
    """The same metrics for a markdown document (the lens compares like with like). Pure."""
    lines = (body or "").splitlines()
    headings, in_code, code_blocks, tables, quotes, items = [], False, 0, 0, 0, 0
    paragraphs, para_open, prose = 0, False, []
    before_second, actions_early = 0, []
    images = _MD_IMAGE.findall(body or "")
    for line in lines:
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
            if in_code:
                code_blocks += 1
            para_open = False
            continue
        if in_code:
            continue
        m = _MD_HEADING.match(line)
        if m:
            headings.append((len(m.group(1)), m.group(2).strip()))
            para_open = False
            continue
        if line.strip().startswith("|") and line.strip().endswith("|"):
            if not para_open:
                tables += 1
            para_open = True
            continue
        if line.strip().startswith(">"):
            quotes += 1
        if _MD_LIST.match(line):
            items += 1
        if not line.strip():
            para_open = False
            continue
        if not para_open and not _MD_LIST.match(line):
            paragraphs += 1
        para_open = True
        clean = _MD_IMAGE.sub(" ", line)
        clean = _MD_LINK.sub(lambda mm: mm.group(1), clean)
        prose.append(clean)
        open_position = sum(1 for level, _ in headings if level <= 2) < 2
        if open_position:
            before_second += len(_words(clean))
            for text, _href in _MD_LINK.findall(line):
                if text.strip() and len(_words(text)) <= 5 and not _MD_IMAGE.search(text):
                    actions_early.append(text.strip())
    text = "\n".join(prose)
    links = _MD_LINK.findall(body or "")
    top = next((t for level, t in headings if level == 1), headings[0][1] if headings else "")
    metrics = {**text_metrics(text), "headings": len(headings), "top_heading_words": len(_words(top)),
               "first_screen_words": before_second, "paragraphs": paragraphs, "list_items": items,
               "links": len(links), "external_links": sum(1 for _t, h in links if re.match(r"https?://", h)),
               "early_actions": len(actions_early), "buttons": 0, "forms": 0, "inputs": 0,
               "images": len(images), "images_with_alt_ratio": round(sum(1 for alt, _ in images if alt.strip())
                                                                     / len(images), 2) if images else 0.0,
               "embeds": 0, "code_blocks": code_blocks, "tables": tables, "quotes": quotes,
               "title_words": len(_words(top)), "description_words": 0, "feeds_linked": 0}
    structure = {"headings": [f"h{level}: {t}" for level, t in headings], "early_actions": actions_early}
    return {"metrics": metrics, "structure": structure, "text": text, "feeds": [], "links": []}


def series_metrics(dates: list[dt.datetime], titles: list[str] | None = None, *,
                   now: dt.datetime | None = None) -> dict:
    """Cadence of a dated series (feed entries, releases): deterministic. Pure."""
    now = _now(now)
    stamps = sorted(d for d in dates if d is not None)
    out = {"entries": len(stamps)}
    if titles:
        out["entry_title_words"] = float(statistics.median([len(_words(t)) for t in titles])) if titles else 0.0
    if len(stamps) >= 2:
        span_days = max((stamps[-1] - stamps[0]).total_seconds() / 86400.0, 1.0)
        gaps = [(b - a).total_seconds() / 86400.0 for a, b in zip(stamps, stamps[1:])]
        out["entries_per_week"] = round(len(stamps) / span_days * 7.0, 2)
        out["median_gap_days"] = round(statistics.median(gaps), 2)
    if stamps:
        out["last_entry_age_days"] = round(max(0.0, (now - stamps[-1]).total_seconds() / 86400.0), 2)
    return out


def extract_feed(body: str, *, now: dt.datetime | None = None) -> dict:
    """An RSS or Atom document: entries, titles and cadence. Pure; defused against entities."""
    import xml.etree.ElementTree as ET
    if re.search(r"<!DOCTYPE|<!ENTITY", body or "", re.I):
        raise ValueError("a feed with a DTD is not parsed")
    root = ET.fromstring((body or "").encode("utf-8"))
    dates, titles = [], []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag not in ("item", "entry"):
            continue
        when, title = None, ""
        for child in el:
            ctag = child.tag.rsplit("}", 1)[-1].lower()
            if ctag in ("pubdate", "published", "date") and when is None:
                when = _parse(child.text)
            elif ctag == "updated" and when is None:
                when = _parse(child.text)
            elif ctag == "title":
                title = " ".join(str(child.text or "").split())
        dates.append(when)
        titles.append(title)
    metrics = series_metrics([d for d in dates if d], [t for t in titles if t], now=now)
    metrics["entries"] = len(titles)
    return {"metrics": metrics, "structure": {"entry_titles": [t for t in titles if t]},
            "text": "\n".join(t for t in titles if t)}


# ---- the sources ---------------------------------------------------------------------------

def _load_api_descriptions() -> list[dict]:
    try:
        value = json.loads(SOURCES_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = value.get("sources") if isinstance(value, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and r.get("id") and r.get("match") and r.get("reads")]


def _dig(value: Any, path: str) -> Any:
    for part in [p for p in str(path or "").split(".") if p]:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def observe_page(study_id: str, url: str, *, role: str, budget: Budget, opener: Callable | None = None,
                 now: dt.datetime | None = None, follow_feeds: bool = True) -> list[dict]:
    """One public page, and the feeds it links. Returns the observations written."""
    why = _terms_forbid(url)
    if why:
        raise ObservationRefused(why)
    budget.spend()
    if not robots_allow(url, opener=opener):
        raise ObservationRefused(f"robots.txt on {_host(url)} does not allow reading {url}")
    status, body, ctype, final = _get(url, opener=opener)
    method = "plain HTTP GET that robots.txt allows (no browser, no login)"
    if status >= 400 or not body.strip():
        return [record(study_id, target=url, role=role, source="web_page", method=method, status=status,
                       provenance=UNTRUSTED, metrics={}, excerpt="", content=body, now=now,
                       extra={"note": f"the page answered HTTP {status} with {len(body)} characters"})]
    if re.search(r"(rss|atom)\+xml|/xml|text/xml", ctype, re.I) or body.lstrip().startswith("<?xml"):
        return [_feed_observation(study_id, url, body, role=role, method=method, status=status, now=now)]
    page = extract_html(body, final or url)
    out = [record(study_id, target=url, role=role, source="web_page", method=method, status=status,
                  provenance=UNTRUSTED, metrics=page["metrics"], structure=page["structure"],
                  excerpt=page["text"], content=body, now=now,
                  extra={"final_url": final if final != url else None,
                         "thin": page["metrics"]["words"] < 60})]
    if follow_feeds:
        for feed in page["feeds"][:1]:
            try:
                budget.spend()
                if not robots_allow(feed, opener=opener):
                    continue
                f_status, f_body, _c, _f = _get(feed, accept="application/rss+xml,application/atom+xml,"
                                                             "application/xml;q=0.9", opener=opener)
                if f_status < 400 and f_body.strip():
                    out.append(_feed_observation(study_id, feed, f_body, role=role, status=f_status, now=now,
                                                 method="plain HTTP GET of the feed the page links (robots.txt allows)",
                                                 extra={"linked_from": url}))
            except (ObservationRefused, ValueError, OSError):
                continue
    return out


def _feed_observation(study_id: str, url: str, body: str, *, role: str, method: str, status: Any,
                      now: dt.datetime | None, extra: dict | None = None) -> dict:
    try:
        feed = extract_feed(body, now=now)
    except Exception as exc:  # noqa: BLE001 - an unparseable feed is recorded as such
        return record(study_id, target=url, role=role, source="feed", method=method, status=status,
                      provenance=UNTRUSTED, metrics={}, content=body, now=now,
                      extra={**(extra or {}), "note": f"the feed could not be parsed ({type(exc).__name__})"})
    return record(study_id, target=url, role=role, source="feed", method=method, status=status,
                  provenance=UNTRUSTED, metrics=feed["metrics"], structure=feed["structure"],
                  excerpt=feed["text"], content=body, now=now, extra=extra)


def observe_api(study_id: str, url: str, description: dict, match: re.Match, *, role: str, budget: Budget,
                opener: Callable | None = None, now: dt.datetime | None = None) -> list[dict]:
    """A public API described as data. Each read is one observation."""
    now = _now(now)
    groups = {k: urllib.parse.quote(v, safe="") for k, v in match.groupdict().items() if v}
    out = []
    for read in description.get("reads") or []:
        try:
            call = str(read["url"]).format(**groups)
        except (KeyError, IndexError):
            continue
        if _host(call) not in {str(h).lower() for h in description.get("hosts") or []}:
            continue                    # a description may only call the hosts it names
        why = _terms_forbid(call)
        if why:
            raise ObservationRefused(why)
        budget.spend()
        status, body, _ctype, _final = _get(call, accept=str(read.get("accept") or "application/json"), opener=opener)
        method = f"public API ({description['id']}): {read.get('what') or 'GET'}"
        if status >= 400:
            out.append(record(study_id, target=call, role=role, source="public_api", method=method, status=status,
                              provenance=UNTRUSTED, metrics={}, content=body, now=now,
                              extra={"describes": url, "note": f"the API answered HTTP {status}"}))
            continue
        kind = read.get("as") or "json"
        if kind == "markdown":
            doc = extract_markdown(body, call)
            out.append(record(study_id, target=call, role=role, source="public_api", method=method, status=status,
                              provenance=UNTRUSTED, metrics=doc["metrics"], structure=doc["structure"],
                              excerpt=doc["text"], content=body, now=now, extra={"describes": url}))
            continue
        try:
            value = json.loads(body)
        except ValueError:
            continue
        metrics, structure = {}, {}
        if kind == "json":
            for name, spec in (read.get("fields") or {}).items():
                path, _, transform = str(spec).partition(":")
                got = _dig(value, path)
                if transform == "age_days":
                    when = _parse(got)
                    if when is not None:
                        metrics[API_PREFIX + name] = round((now - when).total_seconds() / 86400.0, 2)
                elif isinstance(got, (int, float)) and not isinstance(got, bool):
                    metrics[API_PREFIX + name] = got
                elif isinstance(got, str) and got.strip():
                    structure.setdefault("fields", []).append(f"{name}: {got}")
        elif kind == "json_dates" and isinstance(value, list):
            dates = [_parse(_dig(row, read.get("date") or "")) for row in value if isinstance(row, dict)]
            titles = [str(_dig(row, read.get("title") or "") or "") for row in value if isinstance(row, dict)]
            metrics = {f"{API_PREFIX}{read.get('series') or 'series'}.{k}": v
                       for k, v in series_metrics([d for d in dates if d], [t for t in titles if t], now=now).items()}
            structure = {"titles": [t for t in titles if t]}
        out.append(record(study_id, target=call, role=role, source="public_api", method=method, status=status,
                          provenance=UNTRUSTED, metrics=metrics, structure=structure,
                          excerpt="\n".join(structure.get("fields") or structure.get("titles") or []),
                          content=body, now=now, extra={"describes": url}))
    return out


def _git_files(path: Path) -> list[str]:
    from aletheia import proc
    done = subprocess.run(["git", "ls-files", "-z"], cwd=str(path), capture_output=True, timeout=60,
                          creationflags=proc.hidden_flags())
    if done.returncode != 0:
        raise ObservationRefused(f"{path} is not a git repository she can list")
    return [p for p in done.stdout.decode("utf-8", "replace").split("\0") if p]


def observe_repo(study_id: str, path: str, *, role: str, files: list[str] | None = None,
                 now: dt.datetime | None = None) -> list[dict]:
    """His project's committed files at a local path. The documents the lens reads are
    measured with the same extractors the comparables' pages are."""
    root = Path(path).expanduser()
    if not root.is_dir():
        raise ObservationRefused(f"{path} is not a folder on this machine")
    tracked = _git_files(root)
    docs = [p for p in tracked if p.lower().endswith((".md", ".markdown", ".txt", ".rst", ".html", ".htm"))]
    chosen = [p for p in (files or []) if p in tracked] or \
        sorted(docs, key=lambda p: (0 if re.search(r"(^|/)(index\.html?|readme\.md)$", p, re.I) else 1,
                                    p.count("/"), p))[:3]
    out = [record(study_id, target=str(root), role=role, source="local_repo", method="git ls-files at the path",
                  status="read", provenance=LOCAL, metrics={"tracked_files": len(tracked), "doc_files": len(docs)},
                  structure={"files": tracked[:MAX_STRUCTURE_ROWS]}, content="\n".join(tracked), now=now)]
    for rel in chosen:
        full = root / rel
        try:
            body = full.read_text(encoding="utf-8", errors="replace")[:MAX_BYTES]
        except OSError:
            continue
        doc = extract_html(body, "file:///" + rel) if rel.lower().endswith((".html", ".htm")) \
            else extract_markdown(body, rel)
        out.append(record(study_id, target=f"{root.as_posix()}/{rel}", role=role, source="local_repo",
                          method="read the committed file at the path", status="read", provenance=LOCAL,
                          metrics=doc["metrics"], structure=doc["structure"], excerpt=doc["text"], content=body,
                          now=now, extra={"file": rel}))
    return out


def sources_for(target: str) -> list[str]:
    """Which observation sources can read this target, by what they read. Pure but for the data file."""
    text = str(target or "").strip()
    if re.match(r"^https?://", text):
        names = [f"public_api:{d['id']}" for d in _load_api_descriptions() if re.match(d["match"], text)]
        return names + ["web_page"] if not names else names
    if text and (Path(text).expanduser().is_dir() or re.match(r"^[A-Za-z]:[\\/]|^/|^~", text)):
        return ["local_repo"]
    return []


def observe(study_id: str, target: str, *, role: str, budget: Budget, opener: Callable | None = None,
            now: dt.datetime | None = None, files: list[str] | None = None) -> list[dict]:
    """Read one target with the sources that can read it. Raises ObservationRefused when none may."""
    names = sources_for(target)
    if not names:
        raise ObservationRefused(f"no observation source can read {target!r}")
    out: list[dict] = []
    for name in names:
        if name == "local_repo":
            out += observe_repo(study_id, target, role=role, files=files, now=now)
        elif name == "web_page":
            out += observe_page(study_id, target, role=role, budget=budget, opener=opener, now=now)
        elif name.startswith("public_api:"):
            wanted = name.split(":", 1)[1]
            for description in _load_api_descriptions():
                if description["id"] == wanted:
                    m = re.match(description["match"], target)
                    if m:
                        out += observe_api(study_id, target, description, m, role=role, budget=budget,
                                           opener=opener, now=now)
    return out


def catalog() -> list[dict]:
    """What each source reads and yields: the capability view a planner or a person reads."""
    rows = [{"source": "web_page", "reads": "a public web address", "yields": "document structure and copy metrics"},
            {"source": "feed", "reads": "a feed a page links, or a feed address", "yields": "entries and cadence"},
            {"source": "local_repo", "reads": "a project folder on this machine", "yields": "committed files and "
                                                                                         "document metrics"}]
    for d in _load_api_descriptions():
        rows.append({"source": f"public_api:{d['id']}", "reads": d.get("describe") or d["match"],
                     "yields": ", ".join(sorted({f for r in d.get("reads") or [] for f in (r.get("fields") or {})}))
                     or "API data"})
    return rows


def metric_value(observations: list[dict], metric: str) -> tuple[float | None, list[str]]:
    """The value of one metric across a target's observations, and the ids it came from.
    When several observations carry it, the one with the most words (the main document) wins."""
    carrying = [o for o in observations if isinstance((o.get("metrics") or {}).get(metric), (int, float))]
    if not carrying:
        return None, []
    latest: dict[str, dict] = {}
    for o in carrying:                       # the newest reading of each target stands for it
        held = latest.get(o.get("target") or o["id"])
        if held is None or (o.get("fetched_at") or "", o["id"]) > (held.get("fetched_at") or "", held["id"]):
            latest[o.get("target") or o["id"]] = o
    best = max(latest.values(), key=lambda o: ((o.get("metrics") or {}).get("words") or 0, o.get("fetched_at") or ""))
    return float(best["metrics"][metric]), [best["id"]]
