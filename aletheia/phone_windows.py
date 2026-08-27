"""A real call transport — Phase 12's missing half (Playbook §§17–21).

`phone_v0.py` has been a complete session controller since the systems
layer: approved hash-bound call plans, a verified `phone_bridge` audio
session, a durable DIALING claim written *before* the side effect, halt
re-checked before dialing and keypad, a call-time budget, and the refusal
to treat a call ending as proof the goal succeeded. It shipped with one
transport, `InMemoryCallTransport`, whose own docstring says it is
"never evidence that a real phone provider exists".

This is the provider. It places calls through Phone Link (Microsoft's
`YourPhone` app) against the operator's paired iPhone, and it is
deliberately built on two OS mechanisms rather than on a UI tree:

**Dialling is a `tel:` URI, aimed explicitly.** Walking Phone Link's
accessibility tree to find a dial pad would rot the week the app
redesigns — the one-off workflow §152 warns about. A `tel:` handoff is
documented and stable. But the aim matters: on this machine the classic
`tel:` handler is Skype for Business, and three packaged apps claim the
protocol, so a naive `start tel:+1...` opens the wrong app or a chooser
dialog and silently places no call. `dial()` therefore launches Phone
Link's own AUMID, and `available()` refuses when Phone Link is not the
app that would answer. A dial that opens the wrong window is worse than a
refusal, because only the refusal is honest about what happened.

**A call is CONNECTED when the audio says so** — but the signal is the
endpoint's STATE, not its existence. The first version of this module
tested whether Hands-Free endpoints were present, and a preflight on the
real machine reported call audio live with no call in progress: paired
AirPods and a paired iPhone publish HFP endpoints permanently. Presence
would have made `observe()` return CONNECTED the instant it was asked,
which is §107's Jarvis theater exactly — a receipt for something that
never happened. Windows marks an endpoint ACTIVE (1) only when the SCO
link is really carrying a call; a merely paired device sits at UNPLUGGED
(8). That distinction is measured through MMDevice, and it is what
`observe()` believes over anything a UI claims (§30: the receipt is the
audio path, not the screen).

Nothing here decides whether a call may happen. The envelope arrives
already approved, hash-bound and disclosure-checked by `phone_v0` and
`calls.py`, which is also where §19 lives: Aletheia identifies itself
truthfully and never claims to be Caleb.

EXPERIMENTAL until a call actually completes end to end. Every mechanism
below is real and individually verified; no call has been placed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

from aletheia.proc import run as proc_run

PHONE_LINK_AUMID = "Microsoft.YourPhone_8wekyb3d8bbwe!App"
PHONE_LINK_PACKAGE = "Microsoft.YourPhone"
PHONE_LINK_PROCESS = "PhoneExperienceHost"
# Windows names both HFP endpoints through this driver; matching on it is
# how a live call is distinguished from a headset merely being paired.
HFP_MARKER = "Hands-Free"
DIAL_SETTLE_S = 6.0
CONNECT_TIMEOUT_S = 45.0
E164 = re.compile(r"^\+?[0-9]{3,15}$")


class TransportUnavailable(RuntimeError):
    """The machine cannot place a call right now. Callers degrade honestly."""


def _powershell(script: str, timeout_s: float = 25.0) -> tuple[int, str]:
    try:
        proc = proc_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                        capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def normalize_number(value: str) -> str:
    """A dialable number, or refuse. Never a guess at what was meant."""
    raw = str(value or "").strip()
    compact = re.sub(r"[\s()\-.]", "", raw)
    if not E164.fullmatch(compact):
        raise ValueError(
            f"{raw!r} is not a dialable number — digits only, optionally "
            "leading '+', 3 to 15 digits")
    return compact


def phone_link_running() -> bool:
    code, out = _powershell(
        f"@(Get-Process -Name {PHONE_LINK_PROCESS} -ErrorAction SilentlyContinue).Count")
    return code == 0 and out.strip().isdigit() and int(out.strip()) > 0


def phone_link_installed() -> bool:
    code, out = _powershell(
        f"@(Get-AppxPackage -Name {PHONE_LINK_PACKAGE}).Count")
    return code == 0 and out.strip().isdigit() and int(out.strip()) > 0


def phone_paired() -> tuple[bool, str]:
    """Is a phone paired and reporting OK to Windows?"""
    code, out = _powershell(
        "@(Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Status -eq 'OK' -and $_.FriendlyName -notmatch "
        "'Enumerator|Radio|Adapter|RFCOMM|Profile|Avrcp' }) | "
        "Select-Object -First 4 -ExpandProperty FriendlyName")
    if code != 0:
        return False, f"could not read Bluetooth devices: {out[:120]}"
    names = [n.strip() for n in out.splitlines() if n.strip()]
    if not names:
        return False, "no Bluetooth phone is paired and connected"
    return True, ", ".join(dict.fromkeys(names))


# MMDevice DEVICE_STATE. A paired-but-idle Bluetooth headset sits at
# UNPLUGGED; the endpoint goes ACTIVE only when a call is really routed
# through it. Measured on this machine with no call up: every HFP
# endpoint reported 8.
DEVICE_STATE_ACTIVE = 0x1
DEVICE_STATE_ALL = 0x0F
RENDER, CAPTURE = 0, 1


def hfp_endpoints(*, active_only: bool = False) -> list[dict]:
    """Hands-Free endpoints Windows knows about, with their live state.

    `active_only` is the call signal. Without it this lists paired
    devices, which is a different question and not evidence of anything.
    """
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        return []
    try:
        enumerator = AudioUtilities.GetDeviceEnumerator()
    except Exception:
        return []
    found = []
    for flow, direction in ((RENDER, "output"), (CAPTURE, "input")):
        try:
            collection = enumerator.EnumAudioEndpoints(flow, DEVICE_STATE_ALL)
            count = collection.GetCount()
        except Exception:
            continue
        for index in range(count):
            try:
                endpoint = collection.Item(index)
                state = endpoint.GetState()
                name = str(AudioUtilities.CreateDevice(endpoint).FriendlyName)
            except Exception:
                continue
            if HFP_MARKER.casefold() not in name.casefold():
                continue
            if active_only and state != DEVICE_STATE_ACTIVE:
                continue
            found.append({"name": name[:120], "direction": direction,
                          "state": state,
                          "active": state == DEVICE_STATE_ACTIVE})
    return found


def call_audio_live() -> bool:
    """Is call audio really routed to this PC right now?

    Both directions must be ACTIVE. One-way audio is not a phone call, and
    reporting CONNECTED for it would hand the conversation loop a
    microphone with nowhere to speak.
    """
    active = [e for e in hfp_endpoints(active_only=True) if e.get("active")]
    directions = {endpoint["direction"] for endpoint in active}
    return {"input", "output"} <= directions


def available() -> tuple[bool, str]:
    """(usable, why). Every failure names the one thing that is missing."""
    if os.name != "nt":
        return False, "the Phone Link transport is Windows-only"
    if not phone_link_installed():
        return False, ("Phone Link (Microsoft.YourPhone) is not installed — "
                       "install it and pair the iPhone before Aletheia can call")
    if not phone_link_running():
        return False, ("Phone Link is installed but not running — start it and "
                       "sign in; a background dial cannot bring up its first-run flow")
    paired, detail = phone_paired()
    if not paired:
        return False, f"{detail} — connect the phone over Bluetooth"
    return True, f"Phone Link ready; paired: {detail}"


def _launch_tel(number: str) -> tuple[int, str]:
    """Hand the number to PHONE LINK specifically, never to the tel: default.

    `start tel:...` uses whatever holds the protocol association. On this
    machine that is Skype for Business, and two other packaged apps also
    claim it — so the generic path opens the wrong app or a chooser and
    places no call at all. Addressing the AUMID removes the ambiguity.
    """
    target = f"tel:{number}"
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Start-Process -FilePath 'shell:AppsFolder\\{PHONE_LINK_AUMID}' "
        f"-ArgumentList '{target}'; 'launched'")
    return _powershell(script)


class PhoneLinkTransport:
    """A `phone_v0.CallTransport` over Phone Link + Bluetooth HFP."""
    provider_id = "windows.phonelink"

    def __init__(self, *, settle_s: float = DIAL_SETTLE_S,
                 connect_timeout_s: float = CONNECT_TIMEOUT_S):
        self.settle_s = settle_s
        self.connect_timeout_s = connect_timeout_s
        self._calls: dict[str, dict] = {}
        self._counter = 0

    # ---- the protocol -------------------------------------------------

    def dial(self, envelope: dict) -> dict:
        ok, why = available()
        if not ok:
            raise TransportUnavailable(why)
        number = normalize_number(
            envelope.get("number") or envelope.get("to") or "")
        self._counter += 1
        handle = f"phonelink-{self._counter}"
        code, out = _launch_tel(number)
        if code != 0:
            self._calls[handle] = {"status": "FAILED", "number": number}
            return {"handle": handle, "status": "FAILED",
                    "detail": f"Phone Link did not accept the dial: {out[:200]}"}
        self._calls[handle] = {"status": "DIALING", "number": number,
                               "started": time.monotonic()}
        time.sleep(self.settle_s)
        return self.observe(handle)

    def observe(self, handle: str) -> dict:
        state = self._calls.get(handle)
        if state is None:
            return {"handle": handle, "status": "FAILED", "detail": "unknown handle"}
        if state["status"] in ("ENDED", "FAILED"):
            return {"handle": handle, "status": state["status"],
                    "detail": "call is over"}
        live = call_audio_live()
        if live:
            state["status"] = "CONNECTED"
            names = ", ".join(e["name"] for e in hfp_endpoints(active_only=True))
            return {"handle": handle, "status": "CONNECTED",
                    "detail": f"hands-free audio is ACTIVE: {names}"[:400]}
        waited = time.monotonic() - state.get("started", time.monotonic())
        if waited >= self.connect_timeout_s:
            state["status"] = "NO_ANSWER"
            return {"handle": handle, "status": "NO_ANSWER",
                    "detail": f"no call audio after {waited:.0f}s"}
        # Still ringing: the phone has the call, the PC has no audio yet.
        state["status"] = "RINGING"
        return {"handle": handle, "status": "RINGING",
                "detail": f"dialled; waiting for call audio ({waited:.0f}s)"}

    def keypad(self, handle: str, digits: str) -> dict:
        state = self._calls.get(handle)
        if state is None:
            return {"handle": handle, "status": "FAILED", "detail": "unknown handle"}
        # DTMF during a call needs Phone Link's in-call keypad, which this
        # transport does not drive. Refusing is the honest answer: silently
        # doing nothing would let an IVR plan "succeed" having pressed
        # nothing at all (§30, §106).
        return {"handle": handle, "status": state["status"],
                "detail": "DTMF is not implemented by this transport; "
                          "an IVR plan needs a provider that can send tones"}

    def hangup(self, handle: str) -> dict:
        state = self._calls.get(handle)
        if state is not None:
            state["status"] = "ENDED"
        # Ending is left to the phone or the operator: Phone Link exposes no
        # documented hangup handoff, and a UI-tree click is exactly the
        # fragile thing this transport avoids. The session is marked ENDED
        # so nothing downstream believes a call is still live.
        return {"handle": handle, "status": "ENDED",
                "detail": "session released; end the call on the phone or in "
                          "Phone Link if it is still up"}


def preflight() -> dict:
    """Everything Phase 12 needs, checked without placing a call."""
    ok, why = available()
    paired, who = phone_paired()
    return {
        "transport_available": ok,
        "reason": why,
        "phone_link_installed": phone_link_installed(),
        "phone_link_running": phone_link_running(),
        "phone_paired": paired,
        "paired_devices": who,
        "call_audio_live_now": call_audio_live(),
        "hands_free_endpoints": hfp_endpoints(),
        "hands_free_active_now": hfp_endpoints(active_only=True),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Phone Link call transport (Phase 12).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight", help="check everything except placing a call")
    p_num = sub.add_parser("check-number", help="validate a number without dialing")
    p_num.add_argument("number")
    args = ap.parse_args(argv)

    if args.cmd == "check-number":
        try:
            print(normalize_number(args.number))
            return 0
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    report = preflight()
    print(json.dumps(report, indent=2))
    return 0 if report["transport_available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
