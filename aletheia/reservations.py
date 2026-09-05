"""Private reservation workflow with explicit confirmation truth.

Search candidates and selected slots can be recorded, but a reservation
becomes CONFIRMED only when an external provider supplies a confirmation
identifier.

`propose_booking` used to set BOOK_PROPOSED, name `reservation.book`, and
stop — and the only way to reach that capability was hand-typing a JSON
list of browser selectors at a command line. The same dead end
`subscription.cancel` had: a ledger of intentions wearing a capability's
name. A candidate carries the page it is booked on now, and booking it is
a `webtask` run that stops at the button and waits for him.

Two rules, the same two:

**She never guesses where to go.** A candidate with no URL is a question
for him, not a search that lands on somebody else's booking page.

**CONFIRMED still means the provider said so.** A press the site did not
acknowledge leaves it BOOK_PROPOSED — committing him to be somewhere he
is not actually booked is worse than not booking at all.
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
    candidate = {"id": candidate_id, "provider": provider, "place": place,
                 "slot": slot, "url": str((details or {}).get("url") or "").strip(),
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


def all_reservations(state: str | None = None) -> list[dict]:
    if not RES_DIR.is_dir():
        return []
    out = []
    for path in sorted(RES_DIR.glob("*.json")):
        try:
            value = load(path.stem)
        except (OSError, ValueError):
            continue
        if state is None or value.get("state") == state:
            out.append(value)
    return out


def _chosen(value: dict) -> dict:
    return next((c for c in value["candidates"]
                 if c["id"] == value.get("selected")), {})


def propose_booking(reservation_id: str) -> dict:
    value = load(reservation_id)
    if value["state"] != "SELECTED":
        raise ValueError("select a candidate first")
    value["state"] = "BOOK_PROPOSED"
    value["booking_proposal"] = {"required_capability": "web.task",
                                 "required_approval": "operator_always",
                                 "authority": "proposal_only"}
    if not _chosen(value).get("url"):
        # NAMED, not silent — the mistake this file used to make.
        value["blocked_on"] = (
            "I need the web address the booking is made on — I will not "
            "guess one.")
    value["updated_at"] = utcnow()
    write_json_atomic(_path(reservation_id), value)
    return value["booking_proposal"]


def start_booking(reservation_id: str, *, runner=None) -> dict:
    """Go to the page and get as far as the button. Books nothing.

    The sentence is written HERE rather than by a model: a booking made
    at the wrong place, on the wrong day, is not a thing to leave to
    phrasing.
    """
    value = load(reservation_id)
    if value["state"] == "CONFIRMED":
        return value
    if value["state"] not in {"SELECTED", "BOOK_PROPOSED"}:
        raise ValueError("select a candidate first")
    picked = _chosen(value)
    if not picked.get("url"):
        if value["state"] == "SELECTED":
            propose_booking(reservation_id)
        return load(reservation_id)
    if runner is None:
        from aletheia import webtask
        runner = webtask.run
    record = runner(
        f"Book {value['description']} at {picked['place']} for "
        f"{picked['slot']} on this page.", start_url=picked["url"])
    value["state"] = "BOOK_PROPOSED"
    value["web_task"] = record.get("id", "")
    value["booking_state"] = record.get("state", "")
    value["updated_at"] = utcnow()
    value.pop("blocked_on", None)
    write_json_atomic(_path(reservation_id), value)
    return value


def _wanted(value: dict, capability: str) -> None:
    """He asked for this and did not get it. Counted in his own words."""
    try:
        from aletheia import demand
        demand.record_attempt(capability,
                              str(value.get("description") or value.get("id") or ""),
                              "NEEDS_YOU", source="reservations")
    except Exception:
        pass


def reconcile(*, loader=None) -> list[dict]:
    """CONFIRMED when the provider says so, never when we pressed.

    Committing him to be somewhere he is not actually booked is worse
    than not booking at all.
    """
    if loader is None:
        from aletheia import webtask
        loader = webtask.load_run
    changed = []
    for value in all_reservations():
        if value.get("state") != "BOOK_PROPOSED" or not value.get("web_task"):
            continue
        try:
            record = loader(value["web_task"])
        except Exception:
            continue
        state = str(record.get("state", ""))
        if state == value.get("booking_state"):
            continue
        verdict = str(record.get("result", {}).get("verdict") or "")
        value["booking_state"] = state
        value["updated_at"] = utcnow()
        if verdict == "confirmed":
            value["state"] = "CONFIRMED"
            value["confirmation"] = {
                "id": "", "source": "the booking page",
                "evidence": str(record.get("result", {}).get("evidence", ""))[:400],
                "recorded_at": utcnow()}
            value.pop("blocked_on", None)
        elif state in ("REJECTED", "COMMITTED"):
            _wanted(value, "reservation.book")
            value["blocked_on"] = (
                f"I pressed it and {_chosen(value).get('place', 'the site')} "
                "did not confirm. "
                + str(record.get("result", {}).get("note", ""))[:200])
        write_json_atomic(_path(value["id"]), value)
        changed.append(value)
    return changed


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
