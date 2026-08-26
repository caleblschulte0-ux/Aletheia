"""Provider-neutral contacts and exact, ambiguity-safe person resolution.

This is Phase 14's local data model, not a Google/Outlook connection. It gives
Aletheia one stable way to refer to people before provider adapters exist.
Resolution is deliberately conservative: aliases may help, but two matches are
an error and an unknown person is never guessed.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.stateio import read_json, safe_id, utcnow, write_json_atomic

CONTACTS_DIR = REPO_ROOT / "state" / "contacts"
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
    if not isinstance(emails, list) or any(not _EMAIL_RE.fullmatch(x) for x in emails):
        raise ValueError("emails must be a list of email addresses")
    for key in ("aliases", "phones", "organizations", "tags"):
        value = contact.get(key, [])
        if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
            raise ValueError(f"{key} must be a list of non-empty strings")
    if len({_norm(x) for x in emails}) != len(emails):
        raise ValueError("duplicate email")


def save(contact: dict) -> dict:
    validate(contact)
    write_json_atomic(_path(contact["id"]), contact)
    return contact


def create(contact_id: str, display_name: str, *, emails: list[str] | None = None,
           phones: list[str] | None = None, aliases: list[str] | None = None,
           organizations: list[str] | None = None, tags: list[str] | None = None) -> dict:
    path = _path(contact_id)
    if path.exists():
        raise FileExistsError(f"contact {contact_id!r} already exists")
    now = utcnow()
    contact = {
        "version": 1,
        "id": contact_id,
        "display_name": display_name.strip(),
        "emails": emails or [],
        "phones": phones or [],
        "aliases": aliases or [],
        "organizations": organizations or [],
        "tags": tags or [],
        "created_at": now,
        "updated_at": now,
    }
    return save(contact)


def load(contact_id: str) -> dict:
    value = read_json(_path(contact_id))
    validate(value)
    return value


def all_contacts() -> list[dict]:
    if not CONTACTS_DIR.is_dir():
        return []
    out = []
    for path in sorted(CONTACTS_DIR.glob("*.json")):
        try:
            value = read_json(path)
            validate(value)
            out.append(value)
        except ValueError:
            continue
    return out


def resolve(query: str, contacts: list[dict] | None = None) -> dict:
    q = _norm(query)
    if not q:
        raise ValueError("contact query is empty")
    contacts = all_contacts() if contacts is None else contacts
    exact: list[dict] = []
    for c in contacts:
        candidates = [c["id"], c["display_name"], *c.get("aliases", []), *c.get("emails", [])]
        if q in {_norm(x) for x in candidates}:
            exact.append(c)
    if not exact:
        raise KeyError(f"no contact matches {query!r}")
    unique = {c["id"]: c for c in exact}
    if len(unique) != 1:
        names = ", ".join(sorted(c["display_name"] for c in unique.values()))
        raise LookupError(f"contact {query!r} is ambiguous: {names}")
    return next(iter(unique.values()))


def primary_email(contact: dict) -> str:
    emails = contact.get("emails", [])
    if len(emails) != 1:
        if not emails:
            raise LookupError(f"contact {contact['id']!r} has no email")
        raise LookupError(f"contact {contact['id']!r} has multiple emails; choose explicitly")
    return emails[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia contacts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new"); p_new.add_argument("id"); p_new.add_argument("name")
    p_new.add_argument("--email", action="append", default=[]); p_new.add_argument("--alias", action="append", default=[])
    p_show = sub.add_parser("show"); p_show.add_argument("query")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        print(json.dumps(create(args.id, args.name, emails=args.email, aliases=args.alias), indent=2))
    elif args.cmd == "show":
        print(json.dumps(resolve(args.query), indent=2))
    else:
        for c in all_contacts():
            print(f"{c['id']:24} {c['display_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
