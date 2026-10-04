"""Find a named person at an organisation, and a way to reach them, from
what the organisation itself publishes.

The pursuit's best move - a short, specific note to the right human - was
dead on arrival: `note_to_person` needs somebody by name with an address,
the reasoner had no way to FIND one, and a note addressed to "the hiring
manager" is rightly dropped (`pursuit.nobody_by_name`). So nothing was
ever written to anybody. This is the missing move's engine.

Deterministic, no model, and bounded:

- NAMES come with a TITLE or they are not kept: "Jane Doe, Head of
  Talent", "Raj Patel - Director of Partnerships", a search result's
  "Jane Doe - Head of Talent at Acme". A title has to carry one of the
  caller's `title_words` (who the ask is about), so an engineer on the
  team page is not a person to write to about partnerships.
- ADDRESSES are kept only on the organisation's OWN domain, and only when
  the local part is plainly the person's (first.last, flast, first) or
  plainly a shared door (careers@, jobs@, hr@, talent@, people@, hello@,
  contact@). Nothing is guessed: an address pattern that MIGHT be right
  is a message to a stranger, and that is spam with his name on it.
- Where it looks: the texts the caller already holds (the posting), then
  a few of the organisation's own pages (/about, /team, ...), then a web
  search whose result titles and snippets name people without visiting
  any sign-in-walled site. At most `max_pages` page reads and two
  searches per call; every page read is a read, never a press.

Nothing here sends anything. A person found with an address is somebody
the reasoner may write to - and that note still waits for his tap.
"""
from __future__ import annotations

import re
import urllib.request

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NAME_WORD = r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
NAME = re.compile(rf"\b({_NAME_WORD}(?: {_NAME_WORD}){{1,2}})\b")
#: A word that starts a line and is not a first name.
_NOT_A_NAME = frozenset("""about ask contact contacts dear email hello hi meet our questions team the our
    senior junior head director vice chief manager lead staff principal associate call reach please
    join apply visit see read learn more careers jobs""".split())
#: What separates a name from a title on a line.
_SEP = re.compile(r"^[\s,\-–—|:.]*(?:is|as)?[\s,\-–—|:.]*")
_TITLE_END = re.compile(r"[\n,|()\[\]]|\s+(?:at|for|@)\s+|\.\s|\s[-–—]\s|$")
SHARED_LOCAL = frozenset("careers jobs hr talent people recruiting recruitment hello contact info team hiring".split())
MAX_PEOPLE = 8
SITE_PATHS = ("/about", "/team", "/about-us", "/people", "/leadership", "/company")
HTTP_TIMEOUT_S = 15
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_SCRIPTS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", str(text or "").casefold())]


def _local_matches(local: str, name: str) -> bool:
    parts = _words(name)
    if len(parts) < 2:
        return False
    first, last = parts[0], parts[-1]
    local = local.casefold()
    forms = {f"{first}.{last}", f"{first}{last}", f"{first}_{last}", f"{first[0]}{last}",
             f"{first}.{last[0]}", first, f"{last}.{first}", f"{first}-{last}"}
    return local in forms


def _title_after(line: str, end: int) -> str:
    rest = _SEP.sub("", line[end:], count=1)
    cut = _TITLE_END.search(rest)
    title = rest[:cut.start()] if cut else rest
    return " ".join(title.split()).strip(" .,-–—|:")


def find_people(text: str, *, domain: str, title_words, source: str = "") -> list[dict]:
    """People named in `text` with a title the ask is about, and the
    addresses on `domain` that are plainly theirs or plainly shared."""
    domain = re.sub(r"^www\.", "", str(domain or "").casefold())
    wanted = [w.casefold() for w in title_words if str(w).strip()]
    found: dict[str, dict] = {}
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        for hit in NAME.finditer(line):
            parts = hit.group(1).split()
            while parts and parts[0].casefold() in _NOT_A_NAME:
                parts.pop(0)
            if len(parts) < 2 or any(p.casefold() in _NOT_A_NAME for p in parts):
                continue
            name = " ".join(parts)
            title = _title_after(line, hit.end())
            low = title.casefold()
            if not title or not any(w in low for w in wanted) or len(title) > 60:
                continue
            key = name.casefold()
            if key not in found:
                found[key] = {"name": name, "title": title, "email": "", "source": source}
    emails = {m.group(0).casefold() for m in EMAIL.finditer(str(text or ""))}
    shared = []
    for address in sorted(emails):
        local, _, host = address.partition("@")
        if not domain or re.sub(r"^www\.", "", host) != domain:
            continue
        owner = next((p for p in found.values() if not p["email"] and _local_matches(local, p["name"])), None)
        if owner is not None:
            owner["email"] = address
        elif local in SHARED_LOCAL:
            shared.append({"name": "", "title": "a shared inbox", "email": address, "source": source})
    return (list(found.values()) + shared)[:MAX_PEOPLE]


def search_text(page: dict) -> str:
    """A search's result titles and snippets as lines a person may be named on."""
    lines = []
    for link in (page or {}).get("links") or []:
        for key in ("text", "snippet"):
            value = " ".join(str(link.get(key) or "").split())
            if value:
                lines.append(value)
    return "\n".join(lines)


def http_text(url: str, opener=None) -> dict:
    """One page as plain text over ordinary HTTP: a read, never a press."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*;q=0.8"})
    open_ = opener or urllib.request.urlopen
    with open_(req, timeout=HTTP_TIMEOUT_S) as resp:
        body = resp.read(1_000_000).decode("utf-8", "replace")
    text = _TAGS.sub("\n", _SCRIPTS.sub(" ", body))
    text = text.replace("&amp;", "&").replace("&nbsp;", " ")
    return {"url": url, "title": "", "text": "\n".join(" ".join(l.split()) for l in text.splitlines() if l.strip()),
            "links": []}


def _merge(into: dict, people: list[dict]) -> None:
    for person in people:
        key = person["name"].casefold() or person["email"]
        if not key:
            continue
        held = into.get(key)
        if held is None:
            into[key] = dict(person)
        elif not held.get("email") and person.get("email"):
            held["email"] = person["email"]


def find_at(organisation: str, *, domain: str, title_words, texts=(), reader=None, search=None,
            max_pages: int = 3) -> list[dict]:
    """People at `organisation`: from `texts` ((label, text) pairs the caller
    holds), then up to `max_pages` of its own site, then a web search's
    snippets. Never raises; a page that cannot be read is skipped."""
    out: dict[str, dict] = {}
    for label, text in texts or ():
        _merge(out, find_people(text, domain=domain, title_words=title_words, source=str(label)))
    reader = reader or http_text
    read = 0
    if domain:
        for path in SITE_PATHS:
            if read >= max_pages or len([p for p in out.values() if p["name"]]) >= 3:
                break
            url = f"https://{domain}{path}"
            read += 1
            try:
                page = reader(url)
            except Exception:
                continue
            text = f"{(page or {}).get('title', '')}\n{(page or {}).get('text', '')}"
            _merge(out, find_people(text, domain=domain, title_words=title_words, source=url))
    if search is not None and organisation:
        for word in list(title_words)[:2]:
            try:
                page = search(f"{organisation} {word}")
            except Exception:
                continue
            _merge(out, find_people(search_text(page), domain=domain, title_words=title_words,
                                    source=f"a web search for {organisation} {word}"))
    people = [p for p in out.values() if p["name"]] + [p for p in out.values() if not p["name"]]
    return people[:MAX_PEOPLE]


def said(people: list[dict]) -> str:
    """The people as lines of evidence."""
    rows = []
    for p in people:
        who = p["name"] or "a shared inbox"
        rows.append(f"{who} — {p.get('title') or '?'} — {p.get('email') or 'no address found'} ({p.get('source') or '?'})")
    return "\n".join(rows)
