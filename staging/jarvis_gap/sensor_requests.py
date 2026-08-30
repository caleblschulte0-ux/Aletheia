"""Request-bound one-shot mobile sensor sessions.

The first camera prototype used a single global latest-frame slot. That is safe
from persistence but not from *cross-request confusion*: two near-simultaneous
questions could consume each other's frame. This staging-only module binds a
camera/location handoff to one opaque, expiring token and to the digest of the
question that caused the request.

Nothing here opens a socket or grants remote access. A future Core endpoint can
use this store behind the existing authenticated/TLS remote-access layer.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import threading
from dataclasses import dataclass, field

from .mobile_sensors import (ImageObservation, MAX_FUTURE_SKEW, _utc,
                             location_metadata, validate_location)

ALLOWED_KINDS = frozenset({"camera", "location"})
DEFAULT_TTL_S = 90.0
MAX_TTL_S = 300.0
MAX_OUTSTANDING = 32
MAX_QUESTION_CHARS = 1200
TOKEN_BYTES = 32


def _normalize_question(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("sensor request question is required")
    normalized = " ".join(value.split())
    if len(normalized) > MAX_QUESTION_CHARS:
        raise ValueError(f"sensor request question exceeds {MAX_QUESTION_CHARS} characters")
    return normalized


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _token_digest(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


@dataclass
class _Ticket:
    id: str
    token_sha256: str
    requested: frozenset[str]
    question_sha256: str
    created_at: dt.datetime
    expires_at: dt.datetime
    camera: ImageObservation | None = field(default=None, repr=False)
    location: dict | None = field(default=None, repr=False)

    def public(self) -> dict:
        supplied = []
        if self.camera is not None:
            supplied.append("camera")
        if self.location is not None:
            supplied.append("location")
        return {
            "id": self.id,
            "requested": sorted(self.requested),
            "supplied": supplied,
            "question_sha256": self.question_sha256,
            "created_at": _utc(self.created_at).isoformat(),
            "expires_at": _utc(self.expires_at).isoformat(),
            "complete": self.requested == frozenset(supplied),
        }


@dataclass(frozen=True)
class SensorCapture:
    ticket_id: str
    question_sha256: str
    camera: ImageObservation | None = field(default=None, repr=False)
    location: dict | None = field(default=None, repr=False)

    def metadata(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "question_sha256": self.question_sha256,
            "camera": None if self.camera is None else self.camera.metadata(),
            "location": location_metadata(self.location),
        }

    def reasoning_context(self, *, include_location: bool = False) -> dict:
        value = self.metadata()
        if include_location and self.location is not None:
            value["location"] = dict(self.location)
        return value


class SensorTicketStore:
    """In-memory, expiring, consume-once sensor request registry."""

    def __init__(self, *, clock=None, max_outstanding: int = MAX_OUTSTANDING) -> None:
        if not isinstance(max_outstanding, int) or not 1 <= max_outstanding <= 256:
            raise ValueError("max_outstanding must be 1..256")
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._max_outstanding = max_outstanding
        self._lock = threading.Lock()
        self._tickets: dict[str, _Ticket] = {}

    def _now(self) -> dt.datetime:
        return _utc(self._clock())

    def _purge_locked(self, now: dt.datetime) -> int:
        stale = [key for key, ticket in self._tickets.items() if ticket.expires_at <= now]
        for key in stale:
            self._tickets.pop(key, None)
        return len(stale)

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_locked(self._now())

    def issue(self, question: str, *, kinds=("camera",), ttl_s: float = DEFAULT_TTL_S) -> tuple[str, dict]:
        normalized = _normalize_question(question)
        requested = frozenset(kinds)
        if not requested or not requested <= ALLOWED_KINDS:
            raise ValueError(f"sensor kinds must be a non-empty subset of {sorted(ALLOWED_KINDS)}")
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)) or not 5 <= float(ttl_s) <= MAX_TTL_S:
            raise ValueError(f"ttl_s must be 5..{MAX_TTL_S:g}")
        now = self._now()
        token = secrets.token_urlsafe(TOKEN_BYTES)
        ticket = _Ticket(
            id="sensor-" + secrets.token_hex(6),
            token_sha256=_token_digest(token),
            requested=requested,
            question_sha256=_digest_text(normalized),
            created_at=now,
            expires_at=now + dt.timedelta(seconds=float(ttl_s)),
        )
        with self._lock:
            self._purge_locked(now)
            if len(self._tickets) >= self._max_outstanding:
                raise RuntimeError("too many outstanding sensor requests")
            self._tickets[ticket.token_sha256] = ticket
        return token, ticket.public()

    def _get_locked(self, token: str, now: dt.datetime) -> _Ticket:
        self._purge_locked(now)
        ticket = self._tickets.get(_token_digest(token))
        if ticket is None:
            raise PermissionError("sensor token is invalid, expired, or already consumed")
        return ticket

    @staticmethod
    def _check_observed(ticket: _Ticket, observed_at: dt.datetime) -> None:
        observed = _utc(observed_at)
        if observed < ticket.created_at - dt.timedelta(seconds=MAX_FUTURE_SKEW):
            raise ValueError("sensor observation predates this request")
        if observed > ticket.expires_at + dt.timedelta(seconds=MAX_FUTURE_SKEW):
            raise ValueError("sensor observation falls outside this request window")

    def accept_camera(self, token: str, image: ImageObservation) -> dict:
        if not isinstance(image, ImageObservation) or image.source != "iphone.camera":
            raise ValueError("camera request requires an iPhone camera observation")
        now = self._now()
        with self._lock:
            ticket = self._get_locked(token, now)
            if "camera" not in ticket.requested:
                raise PermissionError("this sensor request did not ask for a camera frame")
            if ticket.camera is not None:
                raise RuntimeError("camera frame already supplied for this request")
            self._check_observed(ticket, image.observed_at)
            image_age = (now - _utc(image.observed_at)).total_seconds()
            if image_age < -MAX_FUTURE_SKEW:
                raise ValueError("camera observation is implausibly in the future")
            ticket.camera = image
            return ticket.public()

    def accept_location(self, token: str, packet: dict) -> dict:
        now = self._now()
        with self._lock:
            ticket = self._get_locked(token, now)
            if "location" not in ticket.requested:
                raise PermissionError("this sensor request did not ask for location")
            if ticket.location is not None:
                raise RuntimeError("location already supplied for this request")
            elapsed = max(0.0, (now - ticket.created_at).total_seconds())
            value = validate_location(
                packet, now=now, max_age_s=min(MAX_TTL_S, elapsed + MAX_FUTURE_SKEW)
            )
            observed = dt.datetime.fromisoformat(value["observed_at"])
            self._check_observed(ticket, observed)
            ticket.location = value
            return ticket.public()

    def status(self, token: str) -> dict:
        now = self._now()
        with self._lock:
            return self._get_locked(token, now).public()

    def consume(self, token: str) -> SensorCapture:
        now = self._now()
        with self._lock:
            ticket = self._get_locked(token, now)
            supplied = ({"camera"} if ticket.camera is not None else set()) | ({"location"} if ticket.location is not None else set())
            missing = ticket.requested - supplied
            if missing:
                raise RuntimeError(f"sensor request is incomplete; missing {sorted(missing)}")
            self._tickets.pop(ticket.token_sha256, None)
            return SensorCapture(ticket.id, ticket.question_sha256, ticket.camera, ticket.location)
