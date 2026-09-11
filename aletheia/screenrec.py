"""Record one window on his screen to a video file, and stop.

2026-09-11: TikTok's developer review asked for a screen capture of the Shorts
Media app in use, and he wanted Aletheia to make it herself - "I want her to
do this, not you." She could photograph the screen and could not film it.

WHAT IS RECORDED IS ONE WINDOW, NEVER THE DESKTOP. This PC runs three screens
as one wide desktop, and a demo's rules are exactly the kind that list what
must never be in frame: the terminal, code, other apps, notifications. So a
recording names a window, and only that window's rectangle is captured. The
desktop is grabbed CROPPED to it rather than the window by its handle:
grabbing a browser by handle comes back black on a GPU-composited window,
while a cropped desktop grab measured a real picture on this PC (2026-09-11).

Limits that are not settings:
- a hard cap on length (MAX_SECONDS), so a recording nobody stops still ends;
- the file lands in his workspace and is never uploaded or sent anywhere;
- a minimized window, or a title that names no window or several, is refused
  with what is open, rather than guessed at;
- nothing is pressed or typed here: starting and stopping ffmpeg is all it does.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from aletheia import journal, stateio, workspace

ACTOR = "aletheia-screenrec"
MAX_SECONDS = 300
TAIL_S = 2.5
# Every helper process runs with no console window. His real retake
# (2026-09-11) ended with a black "C:\WINDOWS\SYSTEM32\tasklist" window over
# the app: stop() checks the recorder with tasklist while the recording is
# still running, and a console popping up is exactly what the recording must
# never show.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
DEFAULT_FPS = 30
FOLDER = "recordings"
_WINGET_FFMPEG = os.path.join("Microsoft", "WinGet", "Packages", "*FFmpeg*", "*", "bin", "ffmpeg.exe")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class RecordingError(RuntimeError):
    pass


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    hits = sorted(glob.glob(os.path.join(local, _WINGET_FFMPEG))) if local else []
    return hits[-1] if hits else ""


def _state_path() -> Path:
    return stateio.private_dir("recording") / "current.json"


def windows() -> list[dict]:
    """Visible top-level windows with a title, and where each one is drawn."""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes as wt
    user32 = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi
    found: list[dict] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        rect = wt.RECT()
        # The frame Windows actually draws (DWMWA_EXTENDED_FRAME_BOUNDS).
        # GetWindowRect adds invisible resize borders, which would put a strip
        # of whatever is behind the window into the recording.
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
        found.append({"title": buf.value, "minimized": bool(user32.IsIconic(hwnd)),
                      "left": rect.left, "top": rect.top,
                      "width": rect.right - rect.left, "height": rect.bottom - rect.top})
        return True

    user32.EnumWindows(each, 0)
    return found


def _norm(text: str) -> str:
    # Edge writes "Microsoft\u200b Edge" with a zero-width space nobody can type.
    return " ".join(re.sub(r"[\u200b-\u200f\ufeff]", "", str(text or "")).casefold().split())


def _on_screen(window: dict) -> bool:
    return not window.get("minimized") and window["width"] >= 200 and window["height"] >= 200


def find_window(named: str, *, listing: list[dict] | None = None) -> dict:
    """The ONE window on screen that `named` means.

    `named` may give alternatives separated by "|": her first plan
    (2026-09-11) named the demo "localhost|Shorts|Edge", the way a window
    pattern is written everywhere else in her grammar. They are tried in
    order, and the first that names exactly one window on screen wins; one
    that names several is skipped for the next. Only windows actually on
    screen count, so a minimized "New tab" does not make "Edge" ambiguous.
    When nothing settles it, the refusal says why rather than guessing.
    """
    wants = [w for w in (_norm(re.sub(r"^\^?(?:\.\*)?|(?:\.\*)?\$?$", "", part.strip()))
                         for part in str(named or "").split("|")) if w]
    if not wants:
        raise RecordingError("say which window to record")
    rows = [w for w in (windows() if listing is None else listing) if str(w.get("title") or "").strip()]
    usable = [w for w in rows if _on_screen(w)]
    crowded: list[dict] = []
    hidden: list[dict] = []
    for want in wants:
        exact = [w for w in usable if _norm(w["title"]) == want]
        hits = exact if len(exact) == 1 else (exact or [w for w in usable if want in _norm(w["title"])])
        if len(hits) == 1:
            return hits[0]
        crowded += [w for w in hits if w not in crowded]
        hidden += [w for w in rows if not _on_screen(w) and want in _norm(w["title"]) and w not in hidden]
    if crowded:
        raise RecordingError(f"{len(crowded)} windows match {named!r} ("
                             + "; ".join(w["title"] for w in crowded[:6]) + ") - say which")
    if hidden:
        raise RecordingError(f"{hidden[0]['title']!r} is minimized or too small to record - "
                             "bring it up on screen first")
    raise RecordingError(f"no open window is called {named!r}; open now: "
                         + "; ".join(sorted({w['title'] for w in rows})[:8]))


def current() -> dict | None:
    try:
        value = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("path") else None


def _alive(pid: int) -> bool:
    if not pid:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                         capture_output=True, text=True, errors="replace", **_NO_WINDOW)
    return str(int(pid)) in (out.stdout or "")


def _spawn(args: list[str]) -> int:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    return proc.pid


def _stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(str(name or "")).stem).strip("-.")
    return stem[:80] or dt.datetime.now().strftime("recording-%Y%m%d-%H%M%S")


def command(window: dict, out: Path, *, seconds: int, fps: int = DEFAULT_FPS,
            binary: str = "") -> list[str]:
    """The ffmpeg call: the desktop cropped to this window, capped, no sound."""
    width = int(window["width"]) - int(window["width"]) % 2
    height = int(window["height"]) - int(window["height"]) % 2
    return [binary or ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "gdigrab", "-framerate", str(int(fps)), "-draw_mouse", "1",
            "-offset_x", str(int(window["left"])), "-offset_y", str(int(window["top"])),
            "-video_size", f"{width}x{height}", "-i", "desktop",
            "-t", str(int(seconds)), "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            # A keyframe every second and no encoder lookahead, so a fragment
            # lands on disk every second. Her first full take (2026-09-11)
            # lost its last ~20s (Submitted, Done, Recent posts): with x264's
            # defaults nothing after the last 250-frame keyframe was written
            # before the hard stop.
            "-g", str(int(fps)), "-tune", "zerolatency",
            # A recording stopped hard is still a playable file.
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
            str(out)]


def start(window: str, *, name: str = "", max_seconds: int = MAX_SECONDS,
          spawner=None, listing: list[dict] | None = None) -> dict:
    """Begin recording one window. Returns at once; ffmpeg runs on its own."""
    running = current()
    if running and _alive(int(running.get("pid") or 0)):
        return {"started": False, "already": running}
    binary = ffmpeg()
    if not binary:
        raise RecordingError("ffmpeg is not installed on this PC")
    target = find_window(window, listing=listing)
    seconds = max(1, min(int(max_seconds or MAX_SECONDS), MAX_SECONDS))
    folder = workspace.root() / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    stem = _stem(name)
    out = folder / f"{stem}.mp4"
    n = 2
    while out.exists():
        out = folder / f"{stem}-{n}.mp4"
        n += 1
    pid = (spawner or _spawn)(command(target, out, seconds=seconds, binary=binary))
    record = {"pid": pid, "path": str(out), "window": target["title"],
              "size": f"{target['width']}x{target['height']}", "max_seconds": seconds,
              "started_at": stateio.utcnow()}
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(_state_path(), record)
    journal.append("action", "recording",
                   f"started recording the window {target['title']!r} to {out.name} "
                   f"(it stops by itself after {seconds}s)", actor=ACTOR)
    return {"started": True, **record}


def _kill(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"], capture_output=True, **_NO_WINDOW)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def _finish(path: Path) -> float | None:
    """Rewrite the fragmented file as an ordinary MP4, and measure it."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    binary = ffmpeg()
    tidy = path.with_name(path.stem + ".tidy.mp4")
    try:
        done = subprocess.run([binary, "-hide_banner", "-loglevel", "error", "-y",
                               "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(tidy)],
                              capture_output=True, timeout=300, **_NO_WINDOW)
        if done.returncode == 0 and tidy.exists() and tidy.stat().st_size > 0:
            os.replace(tidy, path)
    except Exception:
        pass
    finally:
        if tidy.exists():
            try:
                tidy.unlink()
            except OSError:
                pass
    try:
        info = subprocess.run([binary, "-hide_banner", "-i", str(path)],
                              capture_output=True, text=True, errors="replace", timeout=60,
                              **_NO_WINDOW).stderr
        m = _DURATION.search(info or "")
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    except Exception:
        return None


def stop(*, killer=None, finisher=None, sleeper=None, tail_s: float = TAIL_S) -> dict:
    """End the running recording and say where the file is and how long."""
    running = current()
    if not running:
        return {"stopped": False, "why": "nothing is being recorded"}
    pid = int(running.get("pid") or 0)
    if _alive(pid):
        # the last thing on screen is usually the point (a "Posted" note), so
        # it gets a moment to land in a written fragment before the hard stop
        (sleeper or time.sleep)(tail_s)
        (killer or _kill)(pid)
    try:
        _state_path().unlink()
    except OSError:
        pass
    path = Path(running["path"])
    seconds = (finisher or _finish)(path)
    journal.append("action", "recording", f"stopped recording {path.name}"
                   + (f" ({seconds:.0f}s)" if seconds else ""), actor=ACTOR)
    return {"stopped": True, "path": str(path), "seconds": seconds,
            "window": running.get("window")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record one window to a video file.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("window")
    s.add_argument("--name", default="")
    s.add_argument("--max-seconds", type=int, default=MAX_SECONDS)
    sub.add_parser("stop")
    sub.add_parser("status")
    sub.add_parser("windows")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "start":
            print(json.dumps(start(args.window, name=args.name, max_seconds=args.max_seconds), indent=2))
        elif args.cmd == "stop":
            print(json.dumps(stop(), indent=2))
        elif args.cmd == "status":
            print(json.dumps(current(), indent=2))
        else:
            for w in windows():
                print(f"{'min ' if w['minimized'] else '    '}{w['width']}x{w['height']}  {w['title']}")
    except RecordingError as exc:
        print(f"cannot: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
