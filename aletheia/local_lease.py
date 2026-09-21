"""One local model job at a time, across all of her processes, and conversation first.

His laptop has no GPU and Ollama has ONE queue. Measured 2026-09-16: a 6-token
classification waited 275 s behind another request, and a bounded repair draft
takes ~190 s. The live Core (conversation), a work session ("work on my
projects"), the local repair tier and a mission's staged draft are separate
processes or threads that each believed they had the machine to themselves, so
a work job could put the room behind three minutes of code drafting.

This is a small cross-process LEASE on the local model, taken around every call
to Ollama (`local_model_pool.run_json`, which the gateway's local rung, the
repair tier and agent sessions all go through):

- One holder at a time, machine-wide: a file created exclusively in a lock
  directory shared by every process on this PC (not private state, which a
  sandbox moves - the queue it protects does not move).
- A holder that died, or overstayed its call's own timeout, is stale and is
  cleared, so a crash never wedges her own model.
- CONVERSATION FIRST. A caller is `conversation` unless it says otherwise.
  Background work runs inside `with local_lease.purpose(WORK):` and yields: it
  does not take the lease while a conversation is waiting for it, and it waits
  longer. A conversation that has waited its bound goes ahead anyway (Ollama
  queues it) rather than leave him in silence - the lease may only ever remove
  contention, never an answer.
- A work caller that cannot get the lease in its bound raises `LeaseBusy`, a
  `LocalPoolUnavailable`: "her own model is busy with the conversation" is a
  reason to try later, never a failure of the work.

Nothing here grants anything; it only orders calls.
"""
from __future__ import annotations

import contextvars
import json
import os
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LEASE_ENV = "ALETHEIA_LOCAL_LEASE_DIR"
CONVERSATION = "conversation"
WORK = "work"
PURPOSES = (CONVERSATION, WORK)
LEASE_NAME = "ollama.lease"
#: How long a conversation waits for a lease before going ahead without one.
CONVERSATION_WAIT_S = 30.0
#: How long background work waits before giving up this attempt.
WORK_WAIT_S = 900.0
#: A holder's lease lasts its call's timeout plus this grace, then it is stale.
GRACE_S = 60.0
DEFAULT_HOLD_S = 360.0
POLL_S = 0.25
WANT_FRESH_S = 120.0

_PURPOSE: contextvars.ContextVar[str] = contextvars.ContextVar("aletheia_local_purpose", default=CONVERSATION)
_HELD = threading.local()


class LeaseBusy(RuntimeError):
    """Background work could not get her own model in time (it said why)."""


def lease_dir() -> Path:
    override = os.environ.get(LEASE_ENV, "").strip()
    return Path(override) if override else Path(tempfile.gettempdir()) / "aletheia-locks"


def _lease_path() -> Path:
    return lease_dir() / LEASE_NAME


@contextmanager
def purpose(name: str) -> Iterator[None]:
    """Everything local-model inside this block is `name` (CONVERSATION or WORK)."""
    if name not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    token = _PURPOSE.set(name)
    try:
        yield
    finally:
        _PURPOSE.reset(token)


def current_purpose() -> str:
    return _PURPOSE.get()


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _alive(pid) -> bool | None:
    try:
        from aletheia import proc
        return proc.pid_alive(pid)
    except Exception:  # noqa: BLE001
        return None


def _stale(record: dict | None, now: float) -> bool:
    if not record:
        return True
    try:
        if float(record.get("expires_at") or 0) < now:
            return True
    except (TypeError, ValueError):
        return True
    return _alive(record.get("pid")) is False


def holder() -> dict | None:
    """Who holds her own model right now (None when free or stale). Never raises."""
    record = _read(_lease_path())
    return None if _stale(record, time.time()) else record


def _clear_stale(path: Path, seen: dict | None) -> None:
    """Remove a stale lease without ever removing a fresh one another process just took."""
    tomb = path.with_name(f"{LEASE_NAME}.stale-{os.getpid()}-{secrets.token_hex(3)}")
    try:
        os.replace(path, tomb) if os.name != "nt" else os.rename(path, tomb)
    except OSError:
        return
    moved = _read(tomb)
    if seen is not None and moved is not None and moved.get("token") != seen.get("token") \
            and not _stale(moved, time.time()):
        # Someone took the lease between our read and our move: give it back.
        try:
            os.rename(tomb, path)
            return
        except OSError:
            pass
    try:
        tomb.unlink()
    except OSError:
        pass


def _wants(now: float) -> list[dict]:
    rows = []
    try:
        paths = list(lease_dir().glob("want-*.json"))
    except OSError:
        return rows
    for path in paths:
        record = _read(path)
        if record is None:
            # Unreadable is not stale: a marker being written this instant
            # must not be deleted by the reader. Only one old by the clock
            # on the file is litter.
            try:
                old = now - path.stat().st_mtime > WANT_FRESH_S
            except OSError:
                old = False
            if old:
                try:
                    path.unlink()
                except OSError:
                    pass
            continue
        fresh = now - float(record.get("at") or 0) < WANT_FRESH_S \
            and _alive(record.get("pid")) is not False
        if fresh:
            rows.append(record)
        else:
            try:
                path.unlink()
            except OSError:
                pass
    return rows


def conversation_waiting(*, now: float | None = None) -> bool:
    """Is a conversation waiting for her own model RIGHT NOW? Never raises.

    The lease stops background work from TAKING the queue while he is waiting,
    which is not enough once a background call may run for twenty minutes: the
    call that is already running is the one in front of him. Background work
    passes this to `local_brain.infer_json` as its checkpoint, so a call in
    flight is put down rather than finished."""
    try:
        return bool(_wants(time.time() if now is None else now))
    except Exception:  # noqa: BLE001 - a checkpoint may never be the reason a call fails
        return False


def _try_take(path: Path, record: dict) -> bool:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    return True


@contextmanager
def hold(*, what: str = "", hold_s: float = DEFAULT_HOLD_S, max_wait_s: float | None = None,
         purpose_name: str | None = None) -> Iterator[dict]:
    """Hold her own model for one call. Yields {"held", "waited_s", "purpose", "why"}.

    Re-entrant within a thread. A conversation that waited `max_wait_s` goes ahead
    unheld; work raises LeaseBusy instead."""
    who = purpose_name or current_purpose()
    if who not in PURPOSES:
        who = CONVERSATION
    depth = getattr(_HELD, "depth", 0)
    if depth:
        _HELD.depth = depth + 1
        try:
            yield {"held": True, "waited_s": 0.0, "purpose": who, "why": "already held by this thread"}
        finally:
            _HELD.depth -= 1
        return
    limit = float(max_wait_s if max_wait_s is not None else (WORK_WAIT_S if who == WORK else CONVERSATION_WAIT_S))
    directory = lease_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        # No lock directory: order nothing, remove nothing.
        yield {"held": False, "waited_s": 0.0, "purpose": who, "why": "the lock directory is not writable"}
        return
    path = _lease_path()
    token = secrets.token_hex(8)
    started = time.monotonic()
    want = directory / f"want-{os.getpid()}-{token}.json"
    if who == CONVERSATION:
        # ATOMIC. A background call polls `_wants` every half second and
        # deleted any marker it could not parse - so a marker it read
        # half-written was gone for good, and the conversation waited its
        # whole limit with nobody knowing. Seen on a loaded CI runner
        # (2026-09-21); on his PC the draft and the room are different
        # processes and the same race is one poll away.
        try:
            from aletheia import stateio
            stateio.write_json_atomic(want, {"pid": os.getpid(), "at": time.time(), "what": what[:120]})
        except OSError:
            pass
    held = False
    why = ""
    try:
        while True:
            now = time.time()
            yielding = who == WORK and bool(_wants(now))
            if not yielding:
                record = {"pid": os.getpid(), "purpose": who, "what": str(what)[:160], "token": token,
                          "acquired_at": now, "expires_at": now + max(1.0, float(hold_s)) + GRACE_S}
                if _try_take(path, record):
                    held = True
                    break
                current = _read(path)
                if _stale(current, now):
                    _clear_stale(path, current)
                    continue
            waited = time.monotonic() - started
            if waited >= limit:
                current = _read(path) or {}
                busy = ("a conversation is waiting for it" if yielding else
                        f"it is busy with {current.get('what') or 'another job'} ({current.get('purpose') or 'unknown'})")
                if who == WORK:
                    raise LeaseBusy(f"her own model was not free for {waited:.0f} s: {busy}")
                why = f"went ahead after {waited:.0f} s because {busy}"
                break
            time.sleep(POLL_S)
    finally:
        if who == CONVERSATION:
            try:
                want.unlink()
            except OSError:
                pass
    info = {"held": held, "waited_s": round(time.monotonic() - started, 2), "purpose": who, "why": why}
    if held:
        _HELD.depth = 1
    try:
        yield info
    finally:
        if held:
            _HELD.depth = 0
            current = _read(path)
            if current is not None and current.get("token") == token:
                try:
                    path.unlink()
                except OSError:
                    pass
