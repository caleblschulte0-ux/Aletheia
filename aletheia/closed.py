"""Closing her, the way you close a window.

There was no way to do this. The Core and the supervisor each stop
cleanly on Ctrl+C and journal it — and both run as hidden scheduled
tasks, where nobody can press Ctrl+C. So the only available "stop" was
`Stop-ScheduledTask`, which terminates rather than asks: no clean exit,
no journal line, mid-action if she happened to be mid-action, and the
watchdog reopens her within five minutes anyway.

The operator: *"i just need her to close like i close a window not kill
her."*

A closed window stays closed. That is the whole difference between this
and a kill: one marker, written where both processes look, that means

  - the Core finishes what it is holding and exits 0, journaling it;
  - the supervisor treats that as a clean exit and does NOT relaunch;
  - the five-minute watchdog starts, sees the marker, and exits again
    without starting anything.

It lives in PRIVATE state, deliberately. Closing her is a thing he did on
this machine at this moment; it is not a fact about the fleet that
belongs in a public repository, and it must not sync to another machine
and close one he never touched.

It is not the kill switch and does not pretend to be. HALT
(`aletheia.policy`) is the safety gate: she keeps running and refuses to
act. This is the window button.
"""
from __future__ import annotations

import argparse
import sys

from aletheia import journal, stateio

ACTOR = "aletheia-closed"


def marker():
    return stateio.private_dir("runtime") / "closed.json"


def is_closed() -> bool:
    """Cheap and safe to call in a loop; an unreadable marker is not closed."""
    try:
        return marker().is_file()
    except Exception:
        return False


def why() -> str:
    try:
        return str(stateio.read_json(marker()).get("reason") or "")
    except Exception:
        return ""


def close(reason: str = "", via: str = "operator") -> dict:
    """Ask her to finish and stay shut."""
    record = {"closed_at": stateio.utcnow(), "reason": str(reason or ""),
              "via": str(via)}
    path = marker()
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, record)
    journal.append("event", "core", "closed by operator"
                   + (f" — {reason}" if reason else ""), actor=ACTOR)
    return record


def open_again(via: str = "operator") -> bool:
    """Let her start again. The watchdog brings her back on its own."""
    path = marker()
    if not path.is_file():
        return False
    try:
        path.unlink()
    except Exception:
        return False
    journal.append("event", "core", "reopened by operator", actor=ACTOR)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Close Aletheia the way you close a window, or open her "
                    "again. Not the kill switch — that is aletheia.policy halt.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_close = sub.add_parser("close", help="finish up and stay shut")
    p_close.add_argument("--reason", default="")
    sub.add_parser("open", help="let her start again")
    sub.add_parser("status")
    args = ap.parse_args(argv)

    if args.cmd == "close":
        close(args.reason)
        print("Closing. She will finish what she is holding and stay shut "
              "until you open her again.")
        return 0
    if args.cmd == "open":
        if open_again():
            print("Open. She comes back within five minutes, or start the "
                  "task to have her now.")
        else:
            print("She was not closed.")
        return 0
    if is_closed():
        print(f"closed — {why() or 'no reason given'}")
        return 0
    print("open")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
