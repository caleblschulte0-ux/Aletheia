"""The operator's clock (Playbook §39, §94).

Every store in this repo keeps UTC, which is right. What was missing was
the other half: when he says "tomorrow at 9", he means his tomorrow and
his 9, and the planner was told only the UTC instant — so on 2026-09-02
at 20:00 in Chicago, "remind me tomorrow at 9am" compiled to
2026-09-04T09:00:00Z: the wrong day (it was already the 3rd in UTC) and
the wrong hour (09:00 UTC is 4 in the morning to him). A reminder that
fires at the wrong time is worse than one he set himself.

One place answers "what time zone is the operator in", in this order:

  1. memory identity.timezone — his own word, with provenance (§45)
  2. ALETHEIA_TZ in the environment — the machine's configuration
  3. America/Chicago — the default the rest of the repo already assumed

and `describe_now()` writes the sentence a reasoning provider needs to
resolve relative dates against HIS time, with the UTC offset spelled out
so the timestamps it returns carry it.
"""
from __future__ import annotations

import datetime as dt
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/Chicago"
ENV = "ALETHEIA_TZ"
MEMORY_DOMAIN, MEMORY_KEY = "identity", "timezone"


def _valid(name: object) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name.strip()


def operator_timezone() -> str:
    """IANA name of the operator's time zone. Never raises; an invalid
    remembered or configured name falls through to the next source."""
    try:
        from aletheia import memory
        remembered = _valid(memory.recall(MEMORY_DOMAIN, MEMORY_KEY))
    except Exception:
        remembered = None
    return remembered or _valid(os.environ.get(ENV)) or DEFAULT_TIMEZONE


def operator_tz() -> ZoneInfo:
    return ZoneInfo(operator_timezone())


def parse_utc(value: str) -> dt.datetime:
    """An ISO-8601 string (Z or offset) as an aware datetime in UTC."""
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must carry a UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def describe_now(now: dt.datetime | str | None = None, timezone: str | None = None) -> str:
    """The time sentence for a reasoning provider: UTC instant, the
    operator's local time, and the rule for relative dates."""
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    elif isinstance(now, str):
        now = parse_utc(now)
    elif now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    tz_name = timezone or operator_timezone()
    local = now.astimezone(ZoneInfo(tz_name))
    offset = local.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    return (
        f"The current time is {now.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} (UTC). "
        f"The operator's local time is {local.strftime('%A %Y-%m-%d %H:%M')} "
        f"({tz_name}, UTC{offset}). Resolve every relative date and time he "
        f"uses — tomorrow, tonight, 9am, next week, after work — in HIS local "
        f"time, and write every timestamp as ISO-8601 with that offset "
        f"(for example {local.strftime('%Y-%m-%dT%H:%M:%S')}{offset})."
    )
