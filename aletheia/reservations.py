"""Private reservation workflow with explicit confirmation truth.

Search candidates and selected slots can be recorded, but a reservation becomes
CONFIRMED only when an external provider supplies a confirmation identifier.
"""
from __future__ import annotations

from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

RES_DIR = private_dir("reservations")
STATES = {"SEARCHING", "SELECTED", "BOOK_PROPOSED", "CONFIRMED", "CANCELLED"}


def _path(reservation_id: str) -> Path:
    return RES_DIR / f"{safe_id(reservation_id, name='reservation id')}.json"


def create(reservation_id: str, *, kind: str, description: str,
           party_size: int | None = None) -> dict:
    if _path(reservation_id).exists():
        raise FileExistsError(reservation_id)
    if kind not in {"restaurant", "hotel", "appointment", "activity", "transport", "other"}:
        raise ValueError("unsupported reservation kind")
    if party_size is not None and (type(party_size) is not int or party_size < 1):
        raise ValueError("party_size must be positive")
    now = utcnow()
    value = {"version": 1, "id": safe_id(reservation_id, name="reservation id"), "kind": kind,
             "description": description, "party_size": party_size, "state": "SEARCHING",
             "candidates": [], "created_at": now, "updated_at": now}
    write_json_atomic(_path(reservation_id), value)
    return value


def load(reservation_id: str) -> dict:
    return read_json(_path(reservation_id))


def add_candidate(reservation_id: str, candidate_id: str, *, provider: str,
                  place: str, slot: str, details: dict | None = None) -> dict:
    value = load(reservation_id); safe_id(candidate_id, name="candidate id")
    if value["state"] != "SEARCHING":
        raise ValueError("candidates can only be added while searching")
    if any(c["id"] == candidate_id for c in value["candidates"]):
        raise FileExistsError(candidate_id)
    candidate = {"id": candidate_id, "provider": provider, "place": place, "slot": slot,
                 "details": details or {}, "recorded_at": utcnow()}
    value["candidates"].append(candidate)
    value["updated_at"] = utcnow()
    write_json_atomic(_path(reservation_id), value)
    return candidate


def select(reservation_id: str, candidate_id: str) -> dict:
    value = load(reservation_id)
    if not any(c["id"] == candidate_id for c in value["candidates"]):
        raise KeyError(candidate_id)
    value["selected"] = candidate_id
    value["state"] = "SELECTED"
    value["updated_at"] = utcnow()
    write_json_atomic(_path(reservation_id), value)
    return value


def propose_booking(reservation_id: str) -> dict:
    value = load(reservation_id)
    if value["state"] != "SELECTED":
        raise ValueError("select a candidate first")
    value["state"] = "BOOK_PROPOSED"
    value["booking_proposal"] = {"required_capability": "reservation.book",
                                 "required_approval": "operator_always", "authority": "proposal_only"}
    value["updated_at"] = utcnow()
    write_json_atomic(_path(reservation_id), value)
    return value["booking_proposal"]


def confirm(reservation_id: str, *, confirmation_id: str, source: str) -> dict:
    value = load(reservation_id)
    if value["state"] not in {"SELECTED", "BOOK_PROPOSED"}:
        raise ValueError("reservation is not awaiting confirmation")
    if not isinstance(confirmation_id, str) or not confirmation_id.strip():
        raise ValueError("confirmation_id is required")
    value["state"] = "CONFIRMED"
    value["confirmation_id"] = confirmation_id
    value["confirmation_source"] = source
    value["confirmed_at"] = utcnow()
    value["updated_at"] = utcnow()
    write_json_atomic(_path(reservation_id), value)
    return value
