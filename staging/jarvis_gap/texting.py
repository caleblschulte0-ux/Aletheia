"""Text-message proposal contract — staging only, no sending path.

The Playbook's north-star examples include "Text him back", but production
Aletheia has email and phone-call providers, not a text-message capability.
This module builds only the part that can be made correct without touching the
world: resolve one saved phone number, bind the exact message content to a hash,
and expose privacy-safe metadata for an approval/review surface.

There is intentionally no ``send`` function and no transport import here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field

MAX_BODY_CHARS = 4000
E164 = re.compile(r"^\+?[0-9]{3,15}$")


def normalize_phone(value: str) -> str:
    raw = str(value or "").strip()
    compact = re.sub(r"[\s()\-.]", "", raw)
    if not E164.fullmatch(compact):
        raise ValueError("phone must be 3..15 digits, optionally with leading +")
    return compact


def _body(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("text body is required")
    if "\x00" in value:
        raise ValueError("text body may not contain NUL")
    value = value.strip()
    if len(value) > MAX_BODY_CHARS:
        raise ValueError(f"text body exceeds {MAX_BODY_CHARS} characters")
    return value


def _aware(value: dt.datetime) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def select_saved_phone(contact: dict, explicit: str | None = None) -> str:
    if not isinstance(contact, dict):
        raise ValueError("contact must be an object")
    contact_id = contact.get("id")
    display = contact.get("display_name")
    phones = contact.get("phones", [])
    if not isinstance(contact_id, str) or not contact_id.strip():
        raise ValueError("contact id is required")
    if not isinstance(display, str) or not display.strip():
        raise ValueError("contact display_name is required")
    if not isinstance(phones, list) or any(not isinstance(p, str) for p in phones):
        raise ValueError("contact phones must be a list of strings")
    normalized = []
    for phone in phones:
        candidate = normalize_phone(phone)
        if candidate not in normalized:
            normalized.append(candidate)
    if explicit is not None:
        chosen = normalize_phone(explicit)
        if chosen not in normalized:
            raise LookupError("explicit phone is not one of this contact's saved numbers")
        return chosen
    if not normalized:
        raise LookupError(f"contact {contact_id!r} has no phone number")
    if len(normalized) != 1:
        raise LookupError(f"contact {contact_id!r} has multiple phone numbers; choose explicitly")
    return normalized[0]


def _mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return "•••" + digits[-4:] if len(digits) >= 4 else "•••"


@dataclass(frozen=True)
class TextDraft:
    contact_id: str
    display_name: str
    phone: str = field(repr=False)
    body: str = field(repr=False)
    created_at: dt.datetime

    def __post_init__(self) -> None:
        if not isinstance(self.contact_id, str) or not self.contact_id.strip():
            raise ValueError("contact_id is required")
        if self.contact_id != self.contact_id.strip():
            raise ValueError("contact_id must be trimmed")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name is required")
        if self.display_name != self.display_name.strip():
            raise ValueError("display_name must be trimmed")
        normalized_phone = normalize_phone(self.phone)
        if self.phone != normalized_phone:
            raise ValueError("phone must already be normalized")
        normalized_body = _body(self.body)
        if self.body != normalized_body:
            raise ValueError("text body must already be trimmed")
        _aware(self.created_at)

    @property
    def digest(self) -> str:
        payload = {
            "contact_id": self.contact_id,
            "phone": normalize_phone(self.phone),
            "body": self.body,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def metadata(self) -> dict:
        """Safe for diagnostics: no message text and no full phone number."""
        return {
            "contact_id": self.contact_id,
            "display_name": self.display_name,
            "phone": _mask_phone(self.phone),
            "body_chars": len(self.body),
            "sha256": self.digest,
            "created_at": _aware(self.created_at).isoformat(),
            "execution_authority": False,
        }

    def approval_binding(self) -> dict:
        """Exact private payload an eventual approval must bind to.

        This is intentionally separate from metadata. A caller deciding to show
        the operator the exact proposed message may use it; logging code should
        use ``metadata`` instead.
        """
        return {
            "contact_id": self.contact_id,
            "display_name": self.display_name,
            "phone": normalize_phone(self.phone),
            "body": self.body,
            "sha256": self.digest,
        }


def prepare(contact: dict, body: str, *, phone: str | None = None,
            now: dt.datetime | None = None) -> TextDraft:
    chosen = select_saved_phone(contact, explicit=phone)
    return TextDraft(
        contact_id=contact["id"].strip(),
        display_name=contact["display_name"].strip(),
        phone=chosen,
        body=_body(body),
        created_at=_aware(now or dt.datetime.now(dt.timezone.utc)),
    )
