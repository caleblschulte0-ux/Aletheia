"""What this computer actually has, asked rather than assumed.

Written because a readiness check said yes about something that could not
work, which CLAUDE.md names as the worst kind of lie — it is wrong
precisely where he is trusting it. `browse.available()` returned True
from an import and a file on disk and reported a browser that could not
load a page; `local_model_pool.reachable()` returns True when Ollama
answers `/api/tags`, which proves Ollama is running and nothing else.

Found live 2026-09-09: the `deep` role resolves to `qwen3.6:27b`, a
**17.8 GB model on a 16 GB machine** with integrated graphics and no
discrete GPU. Anything `choose_role` sends to "deep" — a question
containing "debug", "root cause", "architecture", "review the code", or
simply longer than 1,200 characters — loads it. Measured while it was
resident: commit charge 32,329 MB of a 32,841 MB limit, 98.4%, with
1,026 MB of physical memory free. At that point Windows starts killing
things; what it killed was Aletheia's own test suite.

Nothing here is a guess about performance. It reads the number the OS
reports and compares it to the number Ollama reports, both live.

Stdlib only, via ctypes, the same way `screen.py` photographs the desktop
rather than installing Pillow: a capability that works on the machine of
whoever remembered to run pip is the same shape as one that does not
work.
"""
from __future__ import annotations

import ctypes
import os
import sys

#: What the operating system, his browser, his editor and everything else
#: he actually has open need to keep running while she thinks. Chosen from
#: the measurement above rather than from taste: with the 27B loaded there
#: was 1 GB free, and the machine was killing processes.
RESERVE_BYTES = 3 * 1024 ** 3

#: A model needs more than its file: weights, plus the KV cache for its
#: context, plus the runtime. Deliberately a flat margin rather than a
#: model of llama.cpp's allocator — the question here is "is this
#: obviously impossible", and a 27B on 16 GB is obviously impossible.
MODEL_OVERHEAD = 1.15


class UnknownMachine(RuntimeError):
    """The OS would not say. Say so; do not assume it is fine."""


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memory() -> dict:
    """Total and available physical memory, in bytes.

    Raises `UnknownMachine` rather than returning a plausible number: a
    fallback guess here would put the check back where it started, saying
    yes because it could not find out.
    """
    if sys.platform == "win32":
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise UnknownMachine("GlobalMemoryStatusEx failed")
        return {"total": int(status.ullTotalPhys),
                "available": int(status.ullAvailPhys),
                "load_percent": int(status.dwMemoryLoad)}
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        available = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
    except (AttributeError, ValueError, OSError) as exc:
        raise UnknownMachine(f"this platform will not say ({exc})") from None
    return {"total": int(total), "available": int(available),
            "load_percent": int(100 * (1 - available / total)) if total else 0}


def usable_for_a_model() -> int:
    """Bytes a model may take without starving everything else he has open."""
    return max(0, memory()["total"] - RESERVE_BYTES)


def room_for(model_bytes: int) -> dict:
    """Whether a model of this size can run here, and the numbers behind it.

    Returns the verdict AND the arithmetic, because "it does not fit" is
    an assertion and "17.8 GB plus overhead against 13 GB of usable
    memory" is something he can check.
    """
    needed = int(float(max(0, int(model_bytes or 0))) * MODEL_OVERHEAD)
    try:
        usable = usable_for_a_model()
        total = memory()["total"]
    except UnknownMachine as exc:
        # FAILS OPEN, deliberately and narrowly: a machine that will not
        # report its memory is not evidence that the model is too big, and
        # refusing on ignorance would break the local lane on any platform
        # this does not know. The reason travels so the audit can say it.
        return {"fits": True, "known": False, "why": str(exc),
                "needed": needed, "usable": 0, "total": 0}
    return {"fits": needed <= usable, "known": True, "why": "",
            "needed": needed, "usable": usable, "total": total}


def gigabytes(value: int) -> str:
    """A size he would say. "17.8 GB", not "17825792000"."""
    gb = float(max(0, int(value or 0))) / (1024 ** 3)
    if gb >= 10:
        return f"{gb:.0f} GB"
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{gb * 1024:.0f} MB"


def why_it_does_not_fit(name: str, verdict: dict) -> str:
    """The refusal, in English, with the numbers in it.

    Read out in a room, so no identifiers and no byte counts: this is the
    sentence that has to make him believe a capability she has installed
    is one she should not use.
    """
    return (f"{name} needs about {gigabytes(verdict['needed'])} and this "
            f"machine has {gigabytes(verdict['total'])} in total, so about "
            f"{gigabytes(verdict['usable'])} once everything else you have "
            f"open is left alone. It would run out of memory rather than "
            f"run slowly.")
