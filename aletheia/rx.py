"""`re`, with room in its cache for every rule she has.

`voice._interpret` tries well over a thousand patterns on every sentence,
and `quick`'s readers build more as they go. Python's own `re` keeps the
last 512 compiled patterns, so past that it threw each one away and
compiled it again on the next sentence: measured 2026-10-08, almost all of
the 0.2 s a sentence spent in `_interpret` was recompiling the same rules,
and the voice endpoint's "answer the room within two seconds" test began
missing by a tenth of a second on a busy machine.

Same functions, same signatures, same results - only the cache is bigger.
Modules that need it import it as `re`.
"""
from __future__ import annotations

import functools
import re as _re
from re import (A, ASCII, DOTALL, I, IGNORECASE, L, LOCALE, M, MULTILINE, NOFLAG, S, U, UNICODE, VERBOSE, X,  # noqa: F401
                Match, Pattern, RegexFlag, error, escape, purge)

#: Enough for every literal rule in voice and quick, with room for the
#: patterns built per sentence; the least recently used go first.
CACHE_SIZE = 8192


@functools.lru_cache(maxsize=CACHE_SIZE)
def _compiled(pattern, flags):
    return _re.compile(pattern, flags)


def compile(pattern, flags=0):  # noqa: A001 - the name `re` callers use
    if isinstance(pattern, _re.Pattern):
        return _re.compile(pattern, flags)
    return _compiled(pattern, flags)


def match(pattern, string, flags=0):
    return compile(pattern, flags).match(string)


def fullmatch(pattern, string, flags=0):
    return compile(pattern, flags).fullmatch(string)


def search(pattern, string, flags=0):
    return compile(pattern, flags).search(string)


def sub(pattern, repl, string, count=0, flags=0):
    return compile(pattern, flags).sub(repl, string, count)


def subn(pattern, repl, string, count=0, flags=0):
    return compile(pattern, flags).subn(repl, string, count)


def split(pattern, string, maxsplit=0, flags=0):
    return compile(pattern, flags).split(string, maxsplit)


def findall(pattern, string, flags=0):
    return compile(pattern, flags).findall(string)


def finditer(pattern, string, flags=0):
    return compile(pattern, flags).finditer(string)
