"""The headlines, read from public feeds he can see listed.

"What's the news" and "tell me the news" went to the planner (2026-10-07),
which has no way to know today's news and, with nothing thinking, kept the
question "for later". A news feed is a public RSS file: no key, no account,
nothing to sign in to. Which feeds is DATA (`config/news_feeds.json`), so
changing his sources is a reviewed edit of a file and never of this code.

Every headline is read off a feed and said with the feed's name; nothing
is summarised by a model, because a summary of the news nobody can check
against its source is the one kind of answer that must not be invented.
"""
from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from aletheia import stateio

REPO_ROOT = Path(__file__).resolve().parent.parent
FEEDS_PATH = REPO_ROOT / "config" / "news_feeds.json"

AGENT = "Aletheia personal assistant (local, single user)"
# Headlines move, but asking twice in a minute should not cost two fetches.
CACHE_SECONDS = 900
TIMEOUT_S = 10
# A feed is a few tens of kilobytes. Anything far bigger is not a feed.
MAX_BYTES = 2_000_000


class NewsUnavailable(RuntimeError):
    """She could not read any feed, and the message says so in English."""


def feeds() -> list[dict]:
    """The feeds he reads, from the registry file. Empty when it is unreadable."""
    try:
        rows = json.loads(FEEDS_PATH.read_text(encoding="utf-8")).get("feeds") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [r for r in rows if isinstance(r, dict) and str(r.get("url", "")).startswith("https://")
            and r.get("name")]


def _cache_path():
    return stateio.private_dir("news") / "headlines.json"


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read(MAX_BYTES + 1)


def parse(raw: bytes) -> list[str]:
    """Item titles from an RSS or Atom document, in feed order.

    A document type declaration is refused before parsing: a feed never
    needs one, and it is how an XML file expands itself into gigabytes.
    """
    if len(raw) > MAX_BYTES or re.search(rb"<!DOCTYPE|<!ENTITY", raw[:4096], re.IGNORECASE):
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    titles = []
    for item in root.iter():
        tag = item.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        for child in item:
            if child.tag.rsplit("}", 1)[-1] == "title":
                text = " ".join("".join(child.itertext()).split())
                if text:
                    titles.append(text.rstrip("."))
                break
    return titles


def headlines(*, fresh: bool = False, fetch=None) -> list[dict]:
    """[{"source", "title"}], the first few from each feed, cached briefly."""
    if not fresh and fetch is None:
        try:
            cached = stateio.read_json(_cache_path())
            import datetime as dt
            at = dt.datetime.fromisoformat(str(cached["at"]).replace("Z", "+00:00"))
            if (dt.datetime.now(dt.timezone.utc) - at).total_seconds() < CACHE_SECONDS and cached.get("rows"):
                return cached["rows"]
        except Exception:
            pass
    sources = feeds()
    if not sources:
        raise NewsUnavailable("I don't have any news sources set up, so I can't read you the headlines.")
    fetch = fetch or _fetch
    rows = []
    for feed in sources:
        try:
            titles = parse(fetch(feed["url"]))
        except Exception:
            continue                       # one feed down is not the news being down
        rows.extend({"source": str(feed["name"]), "title": t} for t in titles[:int(feed.get("take") or 3)])
    if not rows:
        raise NewsUnavailable("I couldn't reach any of the news feeds just now - the internet may be down. "
                              "Everything else still works.")
    try:
        stateio.write_json_atomic(_cache_path(), {"at": stateio.utcnow(), "rows": rows})
    except Exception:
        pass
    return rows


def spoken(limit: int = 5, **kwargs) -> str:
    """The top headlines, out loud, each with where it came from. Never raises."""
    try:
        rows = headlines(**kwargs)
    except NewsUnavailable as exc:
        return str(exc)
    except Exception as exc:
        return f"I couldn't read the news just now ({type(exc).__name__}). Everything else still works."
    picked, seen = [], set()
    for row in rows:
        key = row["title"].casefold()
        if key in seen:
            continue
        seen.add(key)
        picked.append(row)
        if len(picked) >= limit:
            break
    by_source: dict[str, list[str]] = {}
    for row in picked:
        by_source.setdefault(row["source"], []).append(row["title"])
    parts = [f"From {source}: " + "; ".join(titles) + "." for source, titles in by_source.items()]
    return "Here are the headlines. " + " ".join(parts)
