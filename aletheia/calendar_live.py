"""Configured official live calendar provider + Core refresh hook.

Config is deliberately outside the public repository:
    ~/.aletheia/calendar-live.json

Example Google shape (values omitted on purpose):
    {"provider":"google","calendar_id":"primary","timezone":"America/Chicago",
     "allow_writes":false,
     "oauth":{"client_id":"...","client_secret":"...","refresh_token":"..."}}

Example Microsoft shape:
    {"provider":"microsoft","calendar_id":null,"allow_writes":false,
     "oauth":{"client_id":"...","refresh_token":"...","tenant":"common",
              "scope":"offline_access Calendars.ReadWrite"}}

`allow_writes` defaults false. Even when true, the generic calendar_provider layer
still requires an APPROVED, exact-hash write plan before calling an adapter.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from aletheia import calendar_provider
from aletheia.calendar_google import GoogleCalendarProvider, TOKEN_URL as GOOGLE_TOKEN_URL
from aletheia.calendar_graph import MicrosoftGraphCalendarProvider
from aletheia.calendar_oauth import OAuthSession, Transport
from aletheia.stateio import private_dir, read_json, utcnow, write_json_atomic

CONFIG_FILE = Path.home() / ".aletheia" / "calendar-live.json"
STATE_PATH = private_dir("calendar") / "live-provider-state.json"
WINDOW_PAST_DAYS = 1
WINDOW_FUTURE_DAYS = 60
REFRESH_EVERY_S = 30 * 60
_TENANT_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")


def _raw_config(path: Path | None = None) -> dict:
    path = path or CONFIG_FILE
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"calendar-live.json is invalid: {type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise ValueError("calendar-live.json must contain an object")
    return value


def validate_config(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("live calendar config must be an object")
    provider = value.get("provider")
    if provider not in {"google", "microsoft"}:
        raise ValueError("live calendar provider must be google or microsoft")
    unknown = set(value) - {"provider", "calendar_id", "timezone", "allow_writes", "oauth"}
    if unknown:
        raise ValueError(f"unsupported live calendar config fields: {sorted(unknown)}")
    allow_writes = value.get("allow_writes", False)
    if not isinstance(allow_writes, bool):
        raise ValueError("allow_writes must be boolean")
    calendar_id = value.get("calendar_id")
    if calendar_id is not None and (not isinstance(calendar_id, str) or not calendar_id.strip()):
        raise ValueError("calendar_id must be a non-empty string or null")
    oauth = value.get("oauth")
    if not isinstance(oauth, dict):
        raise ValueError("live calendar config requires oauth object")
    allowed_oauth = {"client_id", "client_secret", "refresh_token", "tenant", "scope"}
    if set(oauth) - allowed_oauth:
        raise ValueError("live calendar oauth contains unsupported fields")
    for required in ("client_id", "refresh_token"):
        if not isinstance(oauth.get(required), str) or not oauth[required].strip():
            raise ValueError(f"live calendar oauth requires {required}")
    clean_oauth = {k: v.strip() for k, v in oauth.items()
                   if isinstance(v, str) and v.strip()}
    clean = {"provider": provider, "allow_writes": allow_writes, "oauth": clean_oauth}
    if calendar_id is not None:
        clean["calendar_id"] = calendar_id.strip()
    if provider == "google":
        timezone = value.get("timezone")
        if not isinstance(timezone, str) or not timezone.strip():
            raise ValueError("Google live calendar config requires timezone")
        # Provider constructor validates ZoneInfo; keep config validation free
        # of network and platform side effects.
        clean["timezone"] = timezone.strip()
    else:
        tenant = clean_oauth.get("tenant", "common")
        if not _TENANT_RE.fullmatch(tenant):
            raise ValueError("Microsoft OAuth tenant contains unsupported characters")
        clean_oauth["tenant"] = tenant
        clean_oauth.setdefault("scope", "offline_access Calendars.ReadWrite")
    return clean


def config(path: Path | None = None) -> dict:
    return validate_config(_raw_config(path))


def available(path: Path | None = None) -> tuple[bool, str]:
    try:
        value = _raw_config(path)
        if not value:
            return False, f"no official calendar provider configured in {path or CONFIG_FILE}"
        clean = validate_config(value)
    except ValueError as exc:
        return False, str(exc)
    mode = "read/write enabled" if clean["allow_writes"] else "read-only writes disabled"
    return True, f"{clean['provider']} provider configured ({mode}); live account not yet verified"


def build_provider(*, transport: Transport | None = None, path: Path | None = None):
    value = config(path)
    oauth = value["oauth"]
    if value["provider"] == "google":
        refresh_form = {
            "client_id": oauth["client_id"],
            "refresh_token": oauth["refresh_token"],
        }
        if oauth.get("client_secret"):
            refresh_form["client_secret"] = oauth["client_secret"]
        session = OAuthSession("google.calendar", token_url=GOOGLE_TOKEN_URL,
                               refresh_form=refresh_form, transport=transport)
        return GoogleCalendarProvider(
            session, calendar_id=value.get("calendar_id", "primary"),
            timezone=value["timezone"], allow_writes=value["allow_writes"])
    tenant = oauth["tenant"]
    refresh_form = {
        "client_id": oauth["client_id"],
        "refresh_token": oauth["refresh_token"],
        "scope": oauth["scope"],
    }
    if oauth.get("client_secret"):
        refresh_form["client_secret"] = oauth["client_secret"]
    session = OAuthSession(
        "microsoft.graph.calendar",
        token_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        refresh_form=refresh_form, transport=transport)
    return MicrosoftGraphCalendarProvider(
        session, calendar_id=value.get("calendar_id"), allow_writes=value["allow_writes"])


def _stamp(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def refresh(*, now: dt.datetime | None = None, transport: Transport | None = None,
            path: Path | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("calendar refresh time must be timezone-aware")
    provider = build_provider(transport=transport, path=path)
    start = now - dt.timedelta(days=WINDOW_PAST_DAYS)
    end = now + dt.timedelta(days=WINDOW_FUTURE_DAYS)
    result = calendar_provider.sync_window(
        provider, start.isoformat(), end.isoformat(), authoritative=True)
    state = {
        "version": 1, "provider": provider.provider_id,
        "last_refresh": _stamp(now), "window_start": _stamp(start),
        "window_end": _stamp(end), "remote_count": result["remote_count"],
        "conflicts": len(result["conflicts"]), "updated_at": utcnow(),
    }
    write_json_atomic(STATE_PATH, state)
    return result


def refresh_if_due(*, now: dt.datetime | None = None, transport: Transport | None = None,
                   path: Path | None = None) -> dict | None:
    if not available(path)[0]:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("calendar refresh time must be timezone-aware")
    if STATE_PATH.exists():
        try:
            state = read_json(STATE_PATH)
            last = state.get("last_refresh")
            if last:
                previous = dt.datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                if (now - previous).total_seconds() < REFRESH_EVERY_S:
                    return None
        except (ValueError, TypeError):
            # Corrupt cache is not authority; a safe full refresh repairs it.
            pass
    return refresh(now=now, transport=transport, path=path)
