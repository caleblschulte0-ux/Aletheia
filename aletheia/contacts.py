"""Provider-neutral contacts and ambiguity-safe person resolution.

This is Phase 14's stable local contact model, not a claim that Google or
Outlook is connected. Unknown or ambiguous people are refused, never guessed.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

CONTACTS_DIR = private_dir("contacts")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _path(contact_id: str) -> Path:
    return CONTACTS_DIR / f"{safe_id(contact_id, name='contact id')}.json"


def _norm(text: str) -> str:
    return " ".join(text.casefold().strip().split())


def validate(contact: dict) -> None:
    required = {"version", "id", "display_name", "created_at", "updated_at"}
    missing = required - contact.keys()
    if missing:
        raise ValueError(f"contact missing {sorted(missing)}")
    safe_id(contact["id"], name="contact id")
    if contact["version"] != 1:
        raise ValueError("unsupported contact version")
    if not isinstance(contact["display_name"], str) or not contact["display_name"].strip():
        raise ValueError("display_name is required")
    emails = contact.get("emails", [])
    if not isinstance(emails, list) or any(not isinstance(x, str) or not _EMAIL_RE.fullmatch(x) for x in emails):
        raise ValueError("emails must be a list of email addresses")
    if len({_norm(x) for x in emails}) != len(emails):
        raise ValueError("duplicate email")
    for key in ("aliases", "phones", "organizations", "tags"):
        value = contact.get(key, [])
        if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
            raise ValueError(f"{key} must be a list of non-empty strings")
        if len({_norm(x) for x in value}) != len(value):
            raise ValueError(f"{key} contains duplicates")


def save(contact: dict) -> dict:
    validate(contact)
    write_json_atomic(_path(contact["id"]), contact)
    return contact


def create(contact_id: str, display_name: str, *, emails: list[str] | None = None,
           phones: list[str] | None = None, aliases: list[str] | None = None,
           organizations: list[str] | None = None, tags: list[str] | None = None,
           provenance: str = "operator") -> dict:
    path = _path(contact_id)
    if path.exists():
        raise FileExistsError(f"contact {contact_id!r} already exists")
    now = utcnow()
    contact = {
        "version": 1, "id": safe_id(contact_id, name="contact id"),
        "display_name": display_name.strip(), "emails": emails or [], "phones": phones or [],
        "aliases": aliases or [], "organizations": organizations or [], "tags": tags or [],
        "provenance": provenance, "created_at": now, "updated_at": now,
    }
    return save(contact)


def load(contact_id: str) -> dict:
    value = read_json(_path(contact_id))
    validate(value)
    return value


def update(contact_id: str, **changes: object) -> dict:
    allowed = {"display_name", "emails", "phones", "aliases", "organizations", "tags", "provenance"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unsupported contact fields: {sorted(unknown)}")
    value = load(contact_id)
    for key, item in changes.items():
        value[key] = item
    value["updated_at"] = utcnow()
    return save(value)


def all_contacts() -> list[dict]:
    if not CONTACTS_DIR.is_dir():
        return []
    out = []
    for path in sorted(CONTACTS_DIR.glob("*.json")):
        try:
            out.append(load(path.stem))
        except ValueError:
            continue
    return out


def resolve(query: str, contacts: list[dict] | None = None) -> dict:
    q = _norm(query)
    if not q:
        raise ValueError("contact query is empty")
    contacts = all_contacts() if contacts is None else contacts
    exact: dict[str, dict] = {}
    for contact in contacts:
        validate(contact)
        candidates = [contact["id"], contact["display_name"], *contact.get("aliases", []), *contact.get("emails", [])]
        if q in {_norm(x) for x in candidates}:
            exact[contact["id"]] = contact
    if not exact:
        raise KeyError(f"no contact matches {query!r}")
    if len(exact) != 1:
        names = ", ".join(sorted(c["display_name"] for c in exact.values()))
        raise LookupError(f"contact {query!r} is ambiguous: {names}")
    return next(iter(exact.values()))


def primary_email(contact: dict) -> str:
    validate(contact)
    emails = contact.get("emails", [])
    if len(emails) != 1:
        if not emails:
            raise LookupError(f"contact {contact['id']!r} has no email")
        raise LookupError(f"contact {contact['id']!r} has multiple emails; choose explicitly")
    return emails[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia contacts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new")
    p_new.add_argument("id"); p_new.add_argument("name")
    p_new.add_argument("--email", action="append", default=[]); p_new.add_argument("--alias", action="append", default=[])
    p_show = sub.add_parser("show"); p_show.add_argument("query")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        print(json.dumps(create(args.id, args.name, emails=args.email, aliases=args.alias), indent=2))
    elif args.cmd == "show":
        print(json.dumps(resolve(args.query), indent=2))
    else:
        for contact in all_contacts():
            print(f"{contact['id']:24} {contact['display_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
