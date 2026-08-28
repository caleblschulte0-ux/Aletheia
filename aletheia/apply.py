"""Doing his side for him, wherever it can be done for him.

The checklist told him what to do. This does it. Everything Aletheia needs
from the operator is ultimately one secret he owns — a calendar URL, a hub
token, a certificate — and every step between "he has the secret" and "it
is configured and verified" is work a machine should do.

So each command here takes exactly one pasted string and finishes the job:
writes the config in the right place with the right shape, sets what has
to be set, runs the real check, and says what it can now see. If the
secret is wrong, it says so immediately instead of leaving a file that
fails quietly at three in the morning.

It also refuses to inflate what it can do. Nothing here creates a
credential, signs into an account on his behalf, or accepts a secret from
anywhere but him at a prompt he typed. Those are his, and §143 is the
reason: identity is the boundary, not an obstacle in front of one.

The cheap path is the default, deliberately. A Google calendar can be read
two ways: a full OAuth client (a cloud project, a consent screen, a
desktop registration — twenty minutes of unrelated work, and the step
people abandon) or the secret iCal address already sitting in his calendar
settings, which is one copy and answers "am I free" just as well. The
expensive path exists for writing; it is not the way in.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from aletheia import journal
from aletheia.proc import run as proc_run

ACTOR = "aletheia-apply"
HOME_CONFIG = Path.home() / ".aletheia"

GOOGLE_ICS = re.compile(
    r"^https://calendar\.google\.com/calendar/ical/.+/private-[0-9a-f]+/basic\.ics$")


def _write_home_json(name: str, value: dict) -> Path:
    HOME_CONFIG.mkdir(parents=True, exist_ok=True)
    path = HOME_CONFIG / name
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def calendar(url: str, *, feed_id: str = "primary") -> dict:
    """Configure the read-only calendar from one secret iCal address.

    Google: Settings -> the calendar -> "Secret address in iCal format".
    Outlook: "Publish calendar" -> ICS link. One copy, no OAuth client, no
    cloud project — and enough for availability, "am I free", and meeting
    slots, which is what the calendar is actually for here.
    """
    from aletheia import ics
    url = str(url).strip().strip('"').strip("'")
    if not url.startswith("https://"):
        raise ValueError("that is not an https calendar URL — copy the SECRET "
                         "iCal address from your calendar's settings")
    if url.endswith(".ics") is False and "ical" not in url:
        raise ValueError("that does not look like an iCal feed; it should end "
                         "in .ics")
    existing = {}
    path = HOME_CONFIG / "calendar.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    feeds = [f for f in existing.get("feeds", [])
             if isinstance(f, dict) and f.get("id") != feed_id]
    feeds.append({"id": feed_id, "url": url})
    _write_home_json("calendar.json", {"feeds": feeds})

    result = ics.refresh()
    from aletheia import calendar as cal
    events = len(cal.all_events())
    journal.append("event", "setup:calendar",
                   f"secret-ICS feed {feed_id!r} configured; {events} event(s) "
                   "mirrored", actor=ACTOR)
    return {"feed": feed_id, "events": events, "refresh": result,
            "secret_stored_in": str(path)}


def _setx(name: str, value: str) -> tuple[int, str]:
    """Persist a user environment variable on Windows.

    setx writes it for FUTURE processes, so this also sets it in the
    current one — otherwise the verification a second later would fail
    against an environment that has not caught up.
    """
    os.environ[name] = value
    if os.name != "nt":
        return 0, "set for this process only (not Windows)"
    proc = proc_run(["setx", name, value], capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()[:200]


def room(url: str, token: str) -> dict:
    """Point her at a Home Assistant and prove she can reach it."""
    from aletheia import hass
    url = str(url).strip().rstrip("/")
    token = str(token).strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("the hub URL needs http:// or https://")
    if len(token) < 40:
        raise ValueError("that does not look like a long-lived access token")
    _setx("ALETHEIA_HASS_URL", url)
    _setx("ALETHEIA_HASS_TOKEN", token)
    reachable, detail = hass.ping()
    if not reachable:
        raise RuntimeError(f"saved, but the hub refused: {detail}")
    observed = hass.observe()
    journal.append("event", "setup:room",
                   f"Home Assistant configured at {url}; {len(observed)} "
                   "registered device(s) observed", actor=ACTOR)
    return {"hub": url, "detail": detail, "devices_observed": len(observed),
            "note": "the token is in your user environment, never in this repo"}


def phone_access(label: str = "iPhone", scope: str = "read") -> dict:
    """Mint the credential and say exactly what is left, with real values."""
    from aletheia import access
    token, record = access.mint(label, scope=scope)
    host = os.environ.get("COMPUTERNAME") or "this-machine"
    return {
        "token_id": record["id"],
        "token": token,
        "scope": record["scope"],
        "expires": record["expires"],
        "shown_once": True,
        "next": [
            "tailscale cert " + host.lower() + ".<your-tailnet>.ts.net",
            "python -m aletheia.core --host 0.0.0.0 "
            "--tls-cert <cert.crt> --tls-key <cert.key>",
        ],
    }


def tailscale_present() -> bool:
    from shutil import which
    return which("tailscale") is not None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Finish a setup step from one pasted secret.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_cal = sub.add_parser("calendar", help="one secret iCal URL; no OAuth needed")
    p_cal.add_argument("url")
    p_cal.add_argument("--id", default="primary", dest="feed_id")
    p_room = sub.add_parser("room", help="Home Assistant URL + long-lived token")
    p_room.add_argument("url")
    p_room.add_argument("token")
    p_phone = sub.add_parser("phone-access", help="mint a token for your phone")
    p_phone.add_argument("--label", default="iPhone")
    p_phone.add_argument("--scope", default="read", choices=["read", "full"])
    args = ap.parse_args(argv)

    try:
        if args.cmd == "calendar":
            out = calendar(args.url, feed_id=args.feed_id)
            print(f"Calendar connected. {out['events']} event(s) mirrored.")
            print(f"The secret lives in {out['secret_stored_in']}, never in this repo.")
            return 0
        if args.cmd == "room":
            out = room(args.url, args.token)
            print(f"Room connected: {out['detail']}")
            print(f"{out['devices_observed']} registered device(s) observed.")
            return 0
        out = phone_access(args.label, args.scope)
        print(f"token id : {out['token_id']}  ({out['scope']}, expires {out['expires']})")
        print(f"token    : {out['token']}")
        print("\nThis is the only time it is shown. Still to do:")
        for line in out["next"]:
            print(f"  $ {line}")
        if not tailscale_present():
            print("\n  Tailscale is not installed yet:")
            print("  $ winget install Tailscale.Tailscale")
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
