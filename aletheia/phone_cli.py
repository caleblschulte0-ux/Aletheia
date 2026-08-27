"""The operator's front door to Phase 12 — and the caller it never had.

`phone_v0.py` is a careful session controller with no `main`, no CLI and
no runtime hook: nothing in the repo called it. That is most of why the
phase stalled at EXPERIMENTAL. Rule zero says a capability is not built
until something really invokes it, so this is that something.

It also chooses the providers. `phone_v0` takes an audio backend and a
call transport as arguments precisely so policy can be tested without a
desktop; real life needs the real ones, and needs to refuse honestly when
they are absent rather than quietly falling back to a fake. The in-memory
fakes live in the test suite's hands only — `transport()` and `backend()`
below will raise before they will hand a caller a pretend phone.

The order below is the safety property, not a workflow convenience:

    calls.propose      the plan, with §19's identity disclosure in it
    (operator approves) a hash-bound approval on that exact plan
    audio  activate    a verified ACTIVE phone_bridge route
    prepare            binds plan + brief + live audio, or refuses
    dial                the first thing that touches the world

Nothing here weakens a gate. Every command delegates to the controller,
which re-reads halt, re-verifies the audio session, and writes its DIALING
claim before the side effect.
"""
from __future__ import annotations

import argparse
import json
import sys

from aletheia import audio_router, calls, phone_v0


def backend() -> audio_router.AudioBackend:
    """The real Windows audio backend, or refuse."""
    from aletheia import audio_windows
    audio_windows._sounddevice()  # raises AudioDeviceError with the fix
    return audio_windows.WindowsAudioBackend()


def transport() -> phone_v0.CallTransport:
    """The real call transport, or refuse — never a fake."""
    from aletheia import phone_windows
    ok, why = phone_windows.available()
    if not ok:
        raise phone_windows.TransportUnavailable(why)
    return phone_windows.PhoneLinkTransport()


def readiness() -> dict:
    """Everything Phase 12 needs, without touching the phone."""
    from aletheia import audio_windows, phone_windows
    report = {"phone": phone_windows.preflight()}
    try:
        audio_windows._sounddevice()
        report["audio"] = {"available": True,
                           "devices": len(audio_windows.inventory())}
    except Exception as exc:
        report["audio"] = {"available": False, "reason": str(exc)}
    report["ready"] = bool(report["phone"]["transport_available"]
                           and report["audio"].get("available"))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 12 phone sessions.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ready", help="check the machine; places no call")

    p_prep = sub.add_parser("prepare", help="bind an approved call to live audio")
    p_prep.add_argument("call_id")
    p_prep.add_argument("--audio-session", required=True)
    p_prep.add_argument("--session")

    p_dial = sub.add_parser("dial", help="place the approved call")
    p_dial.add_argument("session")

    p_obs = sub.add_parser("observe")
    p_obs.add_argument("session")

    p_end = sub.add_parser("end")
    p_end.add_argument("session")

    p_show = sub.add_parser("show")
    p_show.add_argument("session")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "ready":
            report = readiness()
            print(json.dumps(report, indent=2))
            return 0 if report["ready"] else 1
        if args.cmd == "show":
            print(json.dumps(phone_v0.load_session(args.session), indent=2))
            return 0
        if args.cmd == "prepare":
            value = phone_v0.prepare(
                args.call_id, args.audio_session, audio_backend=backend(),
                transport=transport(), session_id=args.session)
        elif args.cmd == "dial":
            value = phone_v0.dial(args.session, audio_backend=backend(),
                                  transport=transport())
        elif args.cmd == "observe":
            value = phone_v0.observe(args.session, audio_backend=backend(),
                                     transport=transport())
        else:
            value = phone_v0.end(args.session, audio_backend=backend(),
                                 transport=transport())
        print(json.dumps(value, indent=2))
        return 0
    except Exception as exc:
        # Refusals are the normal case here (no approval, no audio, halted,
        # no phone). They belong on stderr with their reason, not as a stack.
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
