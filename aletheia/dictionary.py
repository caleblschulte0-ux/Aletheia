"""What a word means, read from a public dictionary.

"Define serendipity" and "what does ubiquitous mean" went to the planner
(2026-10-07), and with nothing thinking she kept them "for later". A model
asked would answer from memory; a dictionary answers from a dictionary.
The Free Dictionary API serves Wiktionary-derived entries to anyone, with
no key and no account. Whatever it says is read out as its own words, two
senses at most, and a word it does not know is said to be unknown - never
filled in from somewhere else.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from aletheia import stateio

URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
AGENT = "Aletheia personal assistant (local, single user)"
TIMEOUT_S = 10
MAX_BYTES = 500_000


def _cache_path():
    return stateio.private_dir("dictionary") / "words.json"


def _fetch(word: str):
    request = urllib.request.Request(URL.format(word=urllib.parse.quote(word)), headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read(MAX_BYTES).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []                                   # the dictionary does not know it
        raise


def senses(word: str, *, fetch=None) -> list[tuple[str, str]]:
    """[(part of speech, definition)], the first sense of each part of
    speech first. Cached for good: a word does not change its meaning."""
    word = " ".join(str(word or "").casefold().split())
    if not re.fullmatch(r"[a-z][a-z' -]{0,40}", word):
        return []
    cache = {}
    if fetch is None:
        try:
            cache = stateio.read_json(_cache_path()) or {}
        except Exception:
            cache = {}
        if word in cache:
            return [tuple(row) for row in cache[word]]
    data = (fetch or _fetch)(word)
    firsts, rest = [], []
    for entry in data if isinstance(data, list) else []:
        for meaning in (entry.get("meanings") or []) if isinstance(entry, dict) else []:
            part = str(meaning.get("partOfSpeech") or "").strip()
            defs = [str(d.get("definition") or "").strip() for d in (meaning.get("definitions") or [])
                    if isinstance(d, dict) and d.get("definition")]
            if defs:
                firsts.append((part, defs[0]))
                rest.extend((part, d) for d in defs[1:])
    found = firsts + rest
    if fetch is None:
        try:
            cache[word] = found[:6]
            stateio.write_json_atomic(_cache_path(), cache)
        except Exception:
            pass
    return found


def spoken(word: str, *, say_unknown: bool = True, **kwargs) -> str:
    """What the word means, out loud. Never raises. With `say_unknown`
    False a word the dictionary lacks is "" - slang and names may still be
    something a model can answer, so the fast lane must not close on them."""
    said = " ".join(str(word or "").split())
    try:
        found = senses(said, **kwargs)
    except OSError:
        return "I couldn't reach the dictionary just now - the internet may be down. Everything else still works."
    except Exception as exc:
        return f"I couldn't look that up just now ({type(exc).__name__})."
    if not found:
        if not say_unknown:
            return ""
        return f"The dictionary doesn't have \"{said}\". If it's a name or slang, it may not be in there."
    lines = []
    for part, definition in found[:2]:
        definition = definition.rstrip(".")
        lines.append(f"as {'an' if part[:1] in 'aeiou' else 'a'} {part}, {definition[:1].lower() + definition[1:]}"
                     if part else definition)
    return f"{said[:1].upper() + said[1:]}: " + "; or, ".join(lines) + "."
