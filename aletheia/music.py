"""Play, pause and skip — without an API key, today.

`media.play` has been NOT_BUILT since somebody noticed the Spotify
window open on his PC. He has Premium and offered to get an API key, and
he should not have to: the transport controls — play, pause, next,
previous — are Windows media keys, which every media application on the
machine already listens for. No key, no OAuth, no account.

WHAT THE KEY WOULD BUY, and it is a real difference rather than a
formality. Media keys control what is ALREADY QUEUED. They cannot choose
— "play the Rolling Stones" needs the Spotify Web API and his
credentials, and no amount of key-pressing substitutes for it. That is
registered separately as `media.choose` rather than smuggled in here,
because "play some music" answering by resuming whatever was paused on
Thursday is a different promise from the one he made.

STORE APP, AIMED. Spotify on this machine is the Microsoft Store build
(`SpotifyAB.SpotifyMusic_zpdnekdrzrea0`), which has no .exe to run. It
is launched through its AUMID the same way `phone_windows` aims at Phone
Link — and for the same reason: the generic route opens the wrong thing
or nothing.

IT NEVER CLAIMS MORE THAN IT DID. A media key is fire-and-forget: there
is no acknowledgement from the application, so "I pressed play" is the
honest sentence and "it is playing" is not. Where she can check — the
player being open at all — she checks.
"""
from __future__ import annotations

import subprocess
import sys
import time

from aletheia import journal

ACTOR = "music"

# The Store package on his machine. `phone_windows` aims at Phone Link
# by AUMID for the same reason: a Store app has no path to run.
SPOTIFY_AUMID = "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"
SPOTIFY_PROCESS = "Spotify"

# Windows virtual key codes. These are the physical media buttons on a
# keyboard, and every player on the machine is already listening.
KEYS = {
    "play": 0xB3,        # VK_MEDIA_PLAY_PAUSE
    "pause": 0xB3,       # the same key: it is a toggle, and saying so is honest
    "next": 0xB0,        # VK_MEDIA_NEXT_TRACK
    "previous": 0xB1,    # VK_MEDIA_PREV_TRACK
    "stop": 0xB2,        # VK_MEDIA_STOP
}

# How long to give the player to come up before pressing play at it.
LAUNCH_SETTLE_S = 3.0


class MusicUnavailable(RuntimeError):
    """She could not do it, and the message says why."""


def player_running() -> bool:
    """Is a Spotify process alive? Never raises."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Name {SPOTIFY_PROCESS} "
             "-ErrorAction SilentlyContinue | Measure-Object).Count"],
            capture_output=True, text=True, timeout=15)
        return (out.stdout or "0").strip().splitlines()[-1].strip() not in ("", "0")
    except Exception:
        return False


def open_player() -> tuple[bool, str]:
    """Start Spotify, aimed at its AUMID. Never raises."""
    if player_running():
        return True, "already open"
    if sys.platform != "win32":
        return False, "this only works on his Windows machine"
    try:
        subprocess.Popen(
            ["explorer.exe", f"shell:AppsFolder\\{SPOTIFY_AUMID}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        return True, "opened Spotify"
    except Exception as exc:
        return False, f"could not open Spotify ({type(exc).__name__})"


def press(what: str) -> bool:
    """Send one media key. True if it was sent, never raises.

    Fire-and-forget by nature: Windows gives no acknowledgement that any
    application acted on it, which is why nothing here reports that
    music IS playing.
    """
    code = KEYS.get(str(what or "").lower())
    if code is None or sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
        user32.keybd_event(code, 0, KEYEVENTF_EXTENDEDKEY, 0)
        user32.keybd_event(code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


def control(what: str, *, sleep=time.sleep) -> str:
    """One transport command, and a sentence that claims only what happened."""
    what = str(what or "").lower().strip()
    if what not in KEYS:
        raise MusicUnavailable(
            f"I don't know how to {what or 'do that'} — I can play, pause, "
            "skip and go back.")

    opened = ""
    if what == "play" and not player_running():
        # Pressing play at nothing does nothing, and reporting success
        # would be the sentence he cannot check.
        ok, detail = open_player()
        if not ok:
            raise MusicUnavailable(detail)
        opened = "Opening Spotify. "
        sleep(LAUNCH_SETTLE_S)

    if not press(what):
        raise MusicUnavailable(
            "I couldn't reach the media keys on this machine.")
    journal.append("action", "music", f"pressed {what}", actor=ACTOR)

    said = {"play": "Play.", "pause": "Paused.", "next": "Skipped.",
            "previous": "Back one.", "stop": "Stopped."}[what]
    # NOT "it's playing". A media key is fire-and-forget and nothing
    # confirms the player acted, so the sentence describes what she did.
    return opened + said


def cannot_choose() -> str:
    """The honest half: transport is not selection.

    Said whenever he names something to play, because resuming whatever
    was paused on Thursday is a different promise from the one he made.
    """
    return ("I can start, pause and skip what's already queued, but I can't "
            "pick a particular song yet — that needs your Spotify account "
            "connected, which is a separate thing you'd set up once.")
