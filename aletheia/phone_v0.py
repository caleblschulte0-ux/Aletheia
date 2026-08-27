"""Phone V0 session controller over approved call plans and approved audio routes.

This is the repo-only half of Playbook §§17–21. It does not contain a real
telephony/desktop-call provider. Instead it proves the orchestration contract a
real provider must obey:

1. ``calls.py`` has an operator-approved, hash-bound call plan that truthfully
   identifies Aletheia as an AI assistant.
2. Phase 11 has a separately approved and verified ACTIVE ``phone_bridge``
   audio session.
3. A deterministic conversation brief is derived from that exact approved call
   plan, so disclosure boundaries cannot be dropped by a voice provider.
4. Only then may an injected ``CallTransport`` receive a dial instruction.
5. A durable DIALING claim is written before the external side effect. A crash
   after that claim can never silently trigger a second dial.
6. Halt is rechecked before dialing/keypad actions; hangup/audio cleanup remains
   allowed because it reduces exposure.
7. The approved call time budget is enforced by observation.
8. A call ending is never treated as proof the user's real-world goal succeeded.

``InMemoryCallTransport`` is a hermetic fake. Until a Windows call-app provider
is implemented and live-tested, ``phone.call`` must not be marked AVAILABLE.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Protocol

from aletheia import audio_router, calls, phone_conversation, policy
from aletheia.stateio import (create_json_exclusive, private_dir, read_json,
                              safe_id, utcnow, write_json_atomic)

SESSIONS_DIR = private_dir("phone") / "sessions"
SESSION_STATES = {"PREPARED", "DIALING", "RINGING", "CONNECTED", "ENDED", "FAILED"}
TRANSPORT_STATUSES = {"DIALING", "RINGING", "CONNECTED", "ENDED", "FAILED", "BUSY", "NO_ANSWER"}
TERMINAL_TRANSPORT_TO_OUTCOME = {
    "ENDED": "COMPLETED",
    "FAILED": "FAILED",
    "BUSY": "BUSY",
    "NO_ANSWER": "NO_ANSWER",
}


def _path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{safe_id(session_id, name='phone session id')}.json"


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("phone session timestamp must be timezone-aware")
    return parsed


def _transport_id(transport: object) -> str:
    provider = getattr(transport, "provider_id", "")
    if not isinstance(provider, str) or not provider.strip() or len(provider) > 128:
        raise ValueError("call transport must declare provider_id")
    return provider.strip()


def _normalize_observation(value: dict) -> dict:
    if not isinstance(value, dict):
        raise RuntimeError("call transport observation must be an object")
    unknown = set(value) - {"handle", "status", "detail"}
    if unknown:
        raise RuntimeError(f"call transport returned unsupported fields: {sorted(unknown)}")
    handle = value.get("handle")
    status = value.get("status")
    if not isinstance(handle, str) or not handle.strip() or len(handle) > 128:
        raise RuntimeError("call transport handle is invalid")
    if status not in TRANSPORT_STATUSES:
        raise RuntimeError("call transport status is invalid")
    return {"handle": handle.strip(), "status": status,
            "detail": str(value.get("detail", ""))[:500]}


def _state_from_transport(status: str) -> str:
    if status in {"DIALING", "RINGING", "CONNECTED"}:
        return status
    if status == "ENDED":
        return "ENDED"
    return "FAILED"


class CallTransport(Protocol):
    """Provider seam; implementations receive only an already-approved envelope."""
    provider_id: str
    def dial(self, envelope: dict) -> dict: ...
    def observe(self, handle: str) -> dict: ...
    def keypad(self, handle: str, digits: str) -> dict: ...
    def hangup(self, handle: str) -> dict: ...


def load_session(session_id: str) -> dict:
    value = read_json(_path(session_id))
    if value.get("state") not in SESSION_STATES:
        raise ValueError("phone session has invalid state")
    return value


def prepare(call_id: str, audio_session_id: str, *, audio_backend: audio_router.AudioBackend,
            transport: CallTransport, session_id: str | None = None) -> dict:
    """Bind approved call + conversation contract + live audio into PREPARED."""
    policy.ensure_not_halted()
    envelope = calls.execution_envelope(call_id)
    if envelope["plan"].get("identity_disclosure") != calls.IDENTITY_DISCLOSURE:
        raise ValueError("call identity disclosure does not match the reviewed conduct contract")
    brief = phone_conversation.build(call_id)
    if brief["call_plan_sha256"] != envelope["plan_sha256"]:
        raise PermissionError("conversation brief does not match the approved call plan")
    audio = audio_router.verify_active(audio_session_id, audio_backend)
    audio_plan = audio_router.load_plan(audio["plan_id"])
    if audio_plan["plan"].get("purpose") != "phone_bridge":
        raise ValueError("Phone V0 requires an audio plan whose purpose is phone_bridge")
    session_id = session_id or f"phone-{call_id}"
    safe_id(session_id, name="phone session id")
    value = {
        "version": 1, "id": session_id, "call_id": call_id,
        "call_plan_sha256": envelope["plan_sha256"], "call_approval_id": envelope["approval_id"],
        "conversation_brief_sha256": brief["brief_sha256"],
        "audio_session_id": audio_session_id, "audio_plan_sha256": audio["plan_sha256"],
        "transport": _transport_id(transport), "state": "PREPARED",
        "max_minutes": envelope["plan"]["max_minutes"],
        "prepared_at": utcnow(), "updated_at": utcnow(),
    }
    create_json_exclusive(_path(session_id), value)
    return value


def _revalidate(session: dict, *, audio_backend: audio_router.AudioBackend,
                transport: CallTransport) -> tuple[dict, dict, dict]:
    policy.ensure_not_halted()
    envelope = calls.execution_envelope(session["call_id"])
    if envelope["plan_sha256"] != session["call_plan_sha256"] or envelope["approval_id"] != session["call_approval_id"]:
        raise PermissionError("call authorization changed after phone session was prepared")
    brief = phone_conversation.build(session["call_id"])
    if brief["brief_sha256"] != session["conversation_brief_sha256"]:
        raise PermissionError("phone conversation contract changed after session was prepared")
    audio = audio_router.verify_active(session["audio_session_id"], audio_backend)
    if audio["plan_sha256"] != session["audio_plan_sha256"]:
        raise PermissionError("audio route changed after phone session was prepared")
    if _transport_id(transport) != session["transport"]:
        raise ValueError("call transport does not match prepared session")
    return envelope, audio, brief


def dial(session_id: str, *, audio_backend: audio_router.AudioBackend,
         transport: CallTransport) -> dict:
    """Dial exactly once. DIALING is persisted before the provider call."""
    session = load_session(session_id)
    if session["state"] != "PREPARED":
        raise ValueError("phone session is not PREPARED; refusing duplicate/late dial")
    envelope, _, brief = _revalidate(session, audio_backend=audio_backend, transport=transport)
    session["state"] = "DIALING"
    session["dial_claimed_at"] = utcnow()
    session["updated_at"] = utcnow()
    write_json_atomic(_path(session_id), session)
    provider_envelope = {**envelope, "conversation": brief}
    try:
        policy.ensure_not_halted()
        observed = _normalize_observation(transport.dial(provider_envelope))
    except Exception as exc:
        session = load_session(session_id)
        session["state"] = "FAILED"
        session["failure"] = f"{type(exc).__name__}: {exc}"[:500]
        session["updated_at"] = utcnow()
        write_json_atomic(_path(session_id), session)
        raise
    session = load_session(session_id)
    session["call_handle"] = observed["handle"]
    session["state"] = _state_from_transport(observed["status"])
    session["observation"] = observed
    session["started_at"] = utcnow()
    session["updated_at"] = utcnow()
    write_json_atomic(_path(session_id), session)
    return session


def _budget_exceeded(session: dict, now: dt.datetime) -> bool:
    started = session.get("started_at")
    if not started:
        return False
    return now.astimezone(dt.timezone.utc) >= (
        _parse_time(started).astimezone(dt.timezone.utc) +
        dt.timedelta(minutes=session["max_minutes"]))


def observe(session_id: str, *, audio_backend: audio_router.AudioBackend,
            transport: CallTransport, now: dt.datetime | None = None) -> dict:
    session = load_session(session_id)
    if session["state"] in {"PREPARED", "ENDED", "FAILED"}:
        return session
    _revalidate(session, audio_backend=audio_backend, transport=transport)
    if not session.get("call_handle"):
        raise RuntimeError("dial was claimed but no provider handle is recorded; reconcile manually")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if _budget_exceeded(session, now):
        return end(session_id, audio_backend=audio_backend, transport=transport,
                   status="CANCELLED", summary="approved call time budget reached")
    observed = _normalize_observation(transport.observe(session["call_handle"]))
    if observed["handle"] != session["call_handle"]:
        raise RuntimeError("call transport observation handle changed")
    if observed["status"] in TERMINAL_TRANSPORT_TO_OUTCOME:
        return end(session_id, audio_backend=audio_backend, transport=transport,
                   status=TERMINAL_TRANSPORT_TO_OUTCOME[observed["status"]],
                   summary=observed["detail"] or f"provider reported {observed['status'].lower()}")
    session["state"] = _state_from_transport(observed["status"])
    session["observation"] = observed
    session["updated_at"] = utcnow()
    write_json_atomic(_path(session_id), session)
    return session


def keypad(session_id: str, digits: str, *, audio_backend: audio_router.AudioBackend,
           transport: CallTransport) -> dict:
    if not isinstance(digits, str) or not digits or len(digits) > 32 or any(ch not in "0123456789*#" for ch in digits):
        raise ValueError("keypad digits may contain only 0-9 * # and are limited to 32")
    session = load_session(session_id)
    if session["state"] not in {"DIALING", "RINGING", "CONNECTED"} or not session.get("call_handle"):
        raise ValueError("phone session is not in an active call state")
    _revalidate(session, audio_backend=audio_backend, transport=transport)
    policy.ensure_not_halted()
    observed = _normalize_observation(transport.keypad(session["call_handle"], digits))
    if observed["handle"] != session["call_handle"]:
        raise RuntimeError("call transport keypad handle changed")
    if observed["status"] in TERMINAL_TRANSPORT_TO_OUTCOME:
        return end(session_id, audio_backend=audio_backend, transport=transport,
                   status=TERMINAL_TRANSPORT_TO_OUTCOME[observed["status"]],
                   summary=observed["detail"] or f"provider reported {observed['status'].lower()}")
    session["state"] = _state_from_transport(observed["status"])
    session["observation"] = observed
    session["updated_at"] = utcnow()
    write_json_atomic(_path(session_id), session)
    return session


def end(session_id: str, *, audio_backend: audio_router.AudioBackend,
        transport: CallTransport, status: str = "COMPLETED", summary: str = "call ended") -> dict:
    """Hang up and stop routing. Cleanup remains permitted while halted.

    ``verified`` is deliberately False: a transport ending proves only that the
    call ended, not that the operator's desired outcome happened (§29–30).
    """
    session = load_session(session_id)
    if session["state"] == "ENDED":
        return session
    if status not in {"COMPLETED", "NO_ANSWER", "BUSY", "FAILED", "CANCELLED"}:
        raise ValueError("invalid call outcome")
    if _transport_id(transport) != session["transport"]:
        raise ValueError("call transport does not match prepared session")
    transport_error = None
    if session.get("call_handle"):
        try:
            observed = _normalize_observation(transport.hangup(session["call_handle"]))
            session["observation"] = observed
            if observed["handle"] != session["call_handle"] or observed["status"] != "ENDED":
                transport_error = "call transport did not verify hangup"
        except Exception as exc:
            transport_error = f"{type(exc).__name__}: {exc}"[:500]
    audio_error = None
    try:
        audio_router.stop(session["audio_session_id"], audio_backend)
    except Exception as exc:
        audio_error = f"{type(exc).__name__}: {exc}"[:500]
    if transport_error or audio_error:
        session["state"] = "FAILED"
        session["failure"] = "; ".join(x for x in (transport_error, audio_error) if x)
        session["updated_at"] = utcnow()
        write_json_atomic(_path(session_id), session)
        return session
    try:
        result = calls.record_outcome(session["call_id"], status=status, summary=summary,
                                      verified=False)
    except FileExistsError:
        result = read_json(calls.RESULTS_DIR / f"{safe_id(session['call_id'])}.json")
    session["state"] = "ENDED"
    session["outcome_status"] = status
    session["call_result"] = result
    session["ended_at"] = utcnow()
    session["updated_at"] = utcnow()
    write_json_atomic(_path(session_id), session)
    return session


class InMemoryCallTransport:
    """Hermetic fake transport; never evidence that a real phone provider exists."""
    provider_id = "fake.phone"

    def __init__(self, *, dial_status: str = "CONNECTED") -> None:
        if dial_status not in TRANSPORT_STATUSES:
            raise ValueError("invalid fake dial status")
        self.dial_status = dial_status
        self.calls: dict[str, dict] = {}
        self.dial_count = 0
        self.keypad_log: list[tuple[str, str]] = []

    def dial(self, envelope: dict) -> dict:
        self.dial_count += 1
        handle = f"fake-call-{self.dial_count}"
        self.calls[handle] = {"status": self.dial_status, "envelope": envelope}
        return {"handle": handle, "status": self.dial_status, "detail": "fake dial"}

    def observe(self, handle: str) -> dict:
        state = self.calls.get(handle, {"status": "FAILED"})
        return {"handle": handle, "status": state["status"], "detail": "fake observe"}

    def keypad(self, handle: str, digits: str) -> dict:
        if handle not in self.calls:
            return {"handle": handle, "status": "FAILED", "detail": "unknown handle"}
        self.keypad_log.append((handle, digits))
        return {"handle": handle, "status": self.calls[handle]["status"], "detail": "fake keypad"}

    def hangup(self, handle: str) -> dict:
        if handle in self.calls:
            self.calls[handle]["status"] = "ENDED"
        return {"handle": handle, "status": "ENDED", "detail": "fake hangup"}
