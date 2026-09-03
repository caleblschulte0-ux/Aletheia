"""A reminder that actually reminds him.

The gap this closes is embarrassing in the way that only obvious things
are. "Remind me at three to call the dentist" worked end to end: the
planner produced `remind_at`, the scheduler stored it, `runtime.tick`
claimed it at three o'clock exactly, `intercom` ran `notify_operator`,
and a notification was written to disk. Nothing appeared on his screen.
Nothing made a sound. His phone, in his pocket, was not polling. The
reminder existed, was correct, was on time, and did not remind him.

Everything upstream of delivery was already right, which is precisely
why nobody noticed: every test passed, the receipt was real, the journal
said "reminder surfaced". Surfaced WHERE.

So this is the last inch. The Core runs on his Windows PC, in front of
him, so the notification goes where he is: a real Windows toast, from
PowerShell's WinRT bridge, which ships with the operating system. No
package to install, no service to sign into, no cloud round trip.

WHAT IT WILL NOT DO:

- It never becomes the record. The notification store stays the source
  of truth and a toast that fails changes nothing about it — a missed
  toast is a missed toast, not a lost reminder.
- It never speaks for a notification `announce` has not been given.
  Those are separate consents: seeing something on your own screen is
  not the same as a machine talking in a room that may have other
  people in it.
- It never runs anywhere it cannot work. On a non-Windows machine
  `available()` says so and the delivery pass does nothing, rather than
  spawning a shell that fails four times a minute.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

from aletheia import journal, stateio
from aletheia.proc import run as proc_run

ACTOR = "aletheia-desktop"

# Toasts are for the two priorities that mean "look now". A NORMAL notice
# is something to find when he goes looking, and a machine that interrupts
# for everything is one he turns off.
LOUD = ("URGENT", "IMPORTANT")
MAX_PER_TICK = 3
TIMEOUT_S = 12.0
TITLE_CHARS = 64
BODY_CHARS = 220

# Windows will not show a toast from an application it does not know, and
# registering one needs an installer. Every PowerShell-based notifier
# solves this the same way: borrow the AppUserModelID Windows already ships
# for PowerShell itself. The toast then reads as coming from PowerShell,
# which is honest — it IS coming from PowerShell.
APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$lines = $template.GetElementsByTagName('text')
$lines.Item(0).AppendChild($template.CreateTextNode($payload.title)) > $null
$lines.Item(1).AppendChild($template.CreateTextNode($payload.body)) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($payload.app).Show($toast)
"""


def delivered_path():
    return stateio.private_dir("desktop") / "delivered.json"


def _delivered() -> dict:
    try:
        value = stateio.read_json(delivered_path())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _mark(notice_id: str) -> None:
    """Record BEFORE showing, and keep only a bounded tail.

    Before, on purpose: a crash between the two costs him one toast, while
    the other order costs him the same toast every sixty seconds until he
    notices — and the notification is still in the store either way.
    """
    seen = _delivered()
    seen[notice_id] = stateio.utcnow()
    if len(seen) > 500:
        for old in sorted(seen, key=lambda k: seen[k])[:len(seen) - 500]:
            seen.pop(old, None)
    stateio.write_json_atomic(delivered_path(), seen)


def _powershell() -> str | None:
    for name in ("powershell.exe", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def available() -> tuple[bool, str]:
    """(usable, reason) — never raises, so a caller can ask every tick."""
    if os.name != "nt" and sys.platform != "win32":
        return False, "desktop toasts are Windows-only; this is not Windows"
    if not _powershell():
        return False, "powershell.exe is not on PATH"
    return True, "ready"


def toast(title: str, body: str, *, runner=None) -> bool:
    """Show one toast. Returns whether it went; never raises."""
    ok, _why = available()
    if not ok:
        return False
    shell = _powershell()
    runner = runner or proc_run
    payload = json.dumps({"title": str(title)[:TITLE_CHARS],
                          "body": str(body)[:BODY_CHARS], "app": APP_ID})
    try:
        done = runner([shell, "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
                      input=payload, capture_output=True, text=True,
                      timeout=TIMEOUT_S)
    except Exception:
        return False
    return getattr(done, "returncode", 1) == 0


def deliver_pending(*, runner=None) -> list[str]:
    """Put anything loud and undelivered on his screen. Returns what went.

    Called from the Core's beat. Silent and cheap when there is nothing to
    do, which is almost always: one read of a small JSON file and no
    process spawned at all.
    """
    ok, _why = available()
    if not ok:
        return []
    from aletheia import notifications
    seen = _delivered()
    sent = []
    for notice in notifications.all_notifications(state="UNREAD"):
        if len(sent) >= MAX_PER_TICK:
            break
        if notice.get("priority") not in LOUD or notice["id"] in seen:
            continue
        _mark(notice["id"])
        if toast(notice.get("title", "Aletheia"), notice.get("body", ""),
                 runner=runner):
            sent.append(notice["id"])
            journal.append("action", "desktop",
                           f"put {notice['id']} on his screen", actor=ACTOR)
        else:
            journal.append("event", "desktop",
                           f"could not show {notice['id']}; it is still unread",
                           actor=ACTOR)
    return sent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Notifications on his own screen.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("deliver", help="show anything loud and undelivered")
    test = sub.add_parser("test", help="show one toast now")
    test.add_argument("--title", default="Aletheia")
    test.add_argument("--body", default="This is what a reminder looks like.")
    args = ap.parse_args(argv)
    ok, why = available()
    if args.cmd == "status":
        print(json.dumps({"available": ok, "reason": why,
                          "delivered": len(_delivered())}, indent=2))
        return 0
    if args.cmd == "test":
        if not ok:
            print(why, file=sys.stderr)
            return 1
        return 0 if toast(args.title, args.body) else 1
    shown = deliver_pending()
    print(f"{len(shown)} shown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
