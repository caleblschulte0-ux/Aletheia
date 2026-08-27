"""The provider behind the room (Phase 18, §§83–85).

`devices.py` has always described what is in the room and what each thing
can do; `room.plan()` resolves a scene down to per-device steps and ends
with `status: READY_FOR_PROVIDER`. That string was the gap: there was no
provider. `room.scene` sat at NOT_BUILT and the lights never moved.

This is that provider — Home Assistant's REST API, which is the honest
choice here because it is the operator's own server on his own network,
speaking one documented protocol to whatever brand of hardware he owns.
Aletheia does not learn twelve vendor clouds; she learns one hub, and the
hub already knows the room. That is §152 again: a primitive, not twelve
integrations.

Credentials come from the environment and are never written anywhere:

    ALETHEIA_HASS_URL     http://homeassistant.local:8123
    ALETHEIA_HASS_TOKEN   a long-lived access token from his profile page

Absent either one, `available()` says exactly what is missing and nothing
here pretends otherwise (§106) — which is why the registry entry for
`room.scene` is NEEDS_CONFIGURATION rather than AVAILABLE. The code is
real; the token is his to create.

Two gates, deliberately. Reading state is `read` risk and ungated: knowing
whether a lamp is on is not touching it. Executing a scene requires an
APPROVED approval bound to the scene, re-reads the kill switch before
every device, and refuses any device the registry has not observed ONLINE
— because "turn off the heater" silently doing nothing is worse than
saying it could not.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from aletheia import devices, journal, policy, room

ACTOR = "aletheia-hass"
TIMEOUT_S = 10.0
MAX_BYTES = 1024 * 1024

# ability -> (domain, service, how the value becomes a service payload).
# The device registry's vocabulary, not Home Assistant's: a scene says
# "dim to 30", and translating that into service data is this layer's job.
SERVICES: dict[str, tuple[str, str]] = {
    "on": ("homeassistant", "turn_on"),
    "off": ("homeassistant", "turn_off"),
    "toggle": ("homeassistant", "toggle"),
    "brightness": ("light", "turn_on"),
    "color": ("light", "turn_on"),
    "temperature": ("climate", "set_temperature"),
    "volume": ("media_player", "volume_set"),
    "play": ("media_player", "media_play"),
    "pause": ("media_player", "media_pause"),
    "lock": ("lock", "lock"),
    "unlock": ("lock", "unlock"),
}


class HassUnavailable(RuntimeError):
    """No hub configured, or it cannot be reached. Callers degrade."""


def base_url() -> str:
    return os.environ.get("ALETHEIA_HASS_URL", "").strip().rstrip("/")


def _token() -> str:
    return os.environ.get("ALETHEIA_HASS_TOKEN", "").strip()


def available() -> tuple[bool, str]:
    """(usable, why) — the honest answer for the registry and for the room."""
    if not base_url():
        return False, ("ALETHEIA_HASS_URL is not set — point it at the "
                       "operator's Home Assistant, e.g. http://homeassistant.local:8123")
    if not _token():
        return False, ("ALETHEIA_HASS_TOKEN is not set — create a long-lived "
                       "access token in Home Assistant and put it in the "
                       "environment; it is never stored in this repo")
    return True, f"Home Assistant at {base_url()}"


def _request(path: str, payload: dict | None = None, opener=None) -> object:
    ok, why = available()
    if not ok:
        raise HassUnavailable(why)
    request = urllib.request.Request(
        f"{base_url()}/api/{path.lstrip('/')}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {_token()}",
                 "Content-Type": "application/json"},
        method="GET" if payload is None else "POST")
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=TIMEOUT_S) as response:
            body = response.read(MAX_BYTES).decode("utf-8")
    except urllib.error.HTTPError as exc:
        hint = (" — the token is not accepted" if exc.code in (401, 403) else "")
        raise HassUnavailable(f"Home Assistant returned {exc.code}{hint}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise HassUnavailable(f"could not reach Home Assistant: {exc}") from exc
    try:
        return json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as exc:
        raise HassUnavailable(f"unreadable response from Home Assistant: {exc}") from exc


def ping(opener=None) -> tuple[bool, str]:
    try:
        payload = _request("", opener=opener)
    except HassUnavailable as exc:
        return False, str(exc)
    message = (payload or {}).get("message") if isinstance(payload, dict) else None
    return True, str(message or "API running")


def states(opener=None) -> dict[str, dict]:
    """Every entity the hub knows, by entity_id. Read-only, ungated."""
    payload = _request("states", opener=opener)
    if not isinstance(payload, list):
        raise HassUnavailable("expected a list of states from Home Assistant")
    return {e["entity_id"]: e for e in payload
            if isinstance(e, dict) and e.get("entity_id")}


def observe(opener=None) -> list[dict]:
    """Refresh the device registry from the hub.

    This is what makes `room.plan()` honest: a device is ONLINE because
    the hub said so a moment ago, not because someone typed it in once.
    """
    live = states(opener=opener)
    touched = []
    for device in devices.all_devices():
        if device.get("provider") != "home_assistant":
            continue
        entity = live.get(device.get("external_id"))
        online = bool(entity) and entity.get("state") not in ("unavailable", "unknown")
        touched.append(devices.mark_observed(
            device["id"], online=online,
            observed_state=(entity or {}).get("attributes", {}) | (
                {"state": entity["state"]} if entity else {})))
    return touched


def _service_call(step: dict) -> tuple[str, str, dict]:
    """One planned scene step -> (domain, service, payload). Raises on
    an ability with no service: an unknown ability must never quietly
    become a no-op that reports success."""
    ability = step["ability"]
    if ability not in SERVICES:
        raise ValueError(f"ability {ability!r} has no Home Assistant service; "
                         f"known: {sorted(SERVICES)}")
    domain, service = SERVICES[ability]
    payload: dict = {"entity_id": step["external_id"]}
    value = step.get("value")
    if ability == "brightness" and value is not None:
        payload["brightness_pct"] = int(value)
    elif ability == "color" and value is not None:
        payload["color_name"] = str(value)
    elif ability == "temperature" and value is not None:
        payload["temperature"] = float(value)
    elif ability == "volume" and value is not None:
        payload["volume_level"] = max(0.0, min(1.0, float(value) / 100.0))
    return domain, service, payload


def execute_scene(scene_id: str, approval_id: str, opener=None) -> dict:
    """Actually move the room. Approval-gated, halt-checked per device.

    Returns an evidence record: what was called, on what, and what the hub
    said. A step that fails stops the scene — half a scene is a state the
    operator can see and correct; a scene that limps on past a failure is
    one he cannot.
    """
    if not policy.is_approved(approval_id):
        raise policy.Halted(
            f"approval {approval_id!r} is not APPROVED — moving the room acts "
            "on the operator's home and is never self-authorized")
    # room.plan() already refuses a device the registry has not observed
    # ONLINE (devices.require_ability). Translate that into this module's
    # vocabulary, with the one thing the operator needs to know next.
    try:
        planned = room.plan(scene_id)
    except RuntimeError as exc:
        raise HassUnavailable(f"{exc} — run `hass observe` first") from exc

    done, failed = [], None
    for step in planned["steps"]:
        if policy.halted():
            failed = "halted mid-scene"
            break
        try:
            domain, service, payload = _service_call(step)
            result = _request(f"services/{domain}/{service}", payload, opener=opener)
        except (HassUnavailable, ValueError) as exc:
            failed = f"{step['device']}: {exc}"
            break
        done.append({"device": step["device"], "service": f"{domain}.{service}",
                     "payload": payload, "changed": result})
    record = {"scene": scene_id, "approval": approval_id,
              "state": "COMPLETED" if failed is None else "FAILED",
              "steps_done": done, "failed": failed}
    journal.append("action", f"room:{scene_id}",
                   f"{len(done)}/{len(planned['steps'])} device(s) moved"
                   + (f" — stopped: {failed}" if failed else ""), actor=ACTOR)
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Home Assistant provider for the room.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("states")
    sub.add_parser("observe")
    p_run = sub.add_parser("scene")
    p_run.add_argument("id")
    p_run.add_argument("--approval", required=True)
    args = ap.parse_args(argv)

    ok, why = available()
    if args.cmd == "status":
        reachable, detail = ping() if ok else (False, why)
        print(f"{'reachable' if reachable else 'unavailable'}: {detail}")
        return 0 if reachable else 1
    if not ok:
        print(why, file=sys.stderr)
        return 1
    try:
        if args.cmd == "states":
            for entity_id, entity in sorted(states().items()):
                print(f"{entity_id:44} {entity.get('state')}")
            return 0
        if args.cmd == "observe":
            touched = observe()
            print(f"observed {len(touched)} registered device(s)")
            return 0
        print(json.dumps(execute_scene(args.id, args.approval), indent=2))
        return 0
    except (HassUnavailable, policy.Halted, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
