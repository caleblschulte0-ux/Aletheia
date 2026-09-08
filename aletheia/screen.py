"""Capture the desktop as a PNG, with no third-party imaging library.

The other half of ``perception.pixels``. ``browse.screenshot`` photographs
a *web page* through Playwright; nothing in the repo could photograph the
DESKTOP, so the vision path had no image source to be wired to.

Three things shape this module:

**GDI does the scaling, not Python.** A 1920x1080 frame is two million
pixels, and resampling that in a Python loop takes seconds - which would
put the cost right back where the whole point was to remove it.
``StretchBlt`` with ``HALFTONE`` asks Windows to scale during the copy, so
the bitmap that reaches Python is already the size the model wants.

**No third-party imaging library.** Pillow is installed on this machine,
but a pip-installed feature works on the machine of whoever remembered to
run it. ``zlib`` and ``struct`` are a complete PNG encoder for the one
colour type needed here, and ``ctypes`` already talks to user32 in
``desktop_context``.

**Looking is not pressing.** Like ``desktop_context``, this module can
only read. There is no click, no key, no focus - not refused by a check,
absent by construction.

The bytes are never written to disk here. A caller that wants a file says
so; a caller that just wants an answer never lets them touch the disk at
all.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import hashlib
import os
import struct
import zlib
from dataclasses import dataclass, field

#: Longest edge handed to a model. Vision models downscale internally
#: anyway; sending more is latency bought for nothing.
DEFAULT_MAX_EDGE = 1024

#: Refuse anything absurd rather than trying to allocate it.
MAX_EDGE_LIMIT = 4096

SRCCOPY = 0x00CC0020
HALFTONE = 4
DIB_RGB_COLORS = 0
BI_RGB = 0

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

MONITOR_DEFAULTTOPRIMARY = 1

#: Which screen "my screen" means. Default ACTIVE, decided by measurement:
#: this machine runs three monitors as one 5760x1080 desktop, so capturing
#: all of it and fitting the longest edge into 1024 produced a 1024x192
#: smear with no readable text in it. "What's on my screen" means the one
#: he is looking at, which is the one holding the focused window.
MONITORS = ("active", "primary", "all")


class ScreenUnavailable(RuntimeError):
    """No desktop to photograph - not Windows, or no interactive session."""


@dataclass(frozen=True)
class Screenshot:
    """A captured frame. ``png`` is bytes and is kept out of ``repr``."""

    png: bytes = field(repr=False)
    width: int
    height: int
    captured_at: dt.datetime
    scale: float = 1.0
    source: str = "windows.desktop"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.png).hexdigest()

    def metadata(self) -> dict:
        """What may be journalled: shape and identity, never pixels."""
        return {
            "source": self.source,
            "captured_at": self.captured_at.astimezone(dt.timezone.utc).isoformat(),
            "width": self.width,
            "height": self.height,
            "scale": round(self.scale, 4),
            "bytes": len(self.png),
            "sha256": self.digest,
        }


def _png(rgb: bytes, width: int, height: int) -> bytes:
    """Encode 8-bit RGB rows as a PNG. zlib and struct are the whole codec."""
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride]
                   for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            # level 6: level 9 costs noticeably more time for a percent or
            # two on screen content, and this sits on a latency path.
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def _target_size(width: int, height: int, max_edge: int) -> tuple[int, int, float]:
    longest = max(width, height)
    if longest <= max_edge:
        return width, height, 1.0
    scale = max_edge / longest
    # never round an edge to zero on a very lopsided virtual desktop
    return max(1, int(width * scale)), max(1, int(height * scale)), scale


def available() -> bool:
    """True when a capture could actually be attempted."""
    return os.name == "nt"


def _bounds(user32, monitor: str) -> tuple[int, int, int, int]:
    """Pixel rectangle of the screen being asked about."""
    from ctypes import wintypes

    if monitor == "all":
        return (user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
                user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
                user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
                user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

    handle = 0
    if monitor == "active":
        # The monitor holding the focused window. Falls back to primary,
        # which is what MONITOR_DEFAULTTOPRIMARY means, so a desktop with
        # nothing focused still answers.
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        handle = user32.MonitorFromWindow(user32.GetForegroundWindow(),
                                          MONITOR_DEFAULTTOPRIMARY)
    if not handle:
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        handle = user32.MonitorFromPoint(wintypes.POINT(0, 0),
                                         MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not handle or not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        # Primary screen metrics are always answerable, so this degrades
        # to a real capture rather than to an exception.
        return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    r = info.rcMonitor
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def capture(*, max_edge: int = DEFAULT_MAX_EDGE, monitor: str = "active",
            now: dt.datetime | None = None) -> Screenshot:
    """Photograph one screen, scaled down by GDI.

    ``monitor`` is "active" (the screen holding the focused window),
    "primary", or "all" (the whole virtual desktop).
    """
    if not available():
        raise ScreenUnavailable("desktop capture is available only on Windows")
    if monitor not in MONITORS:
        raise ValueError(f"monitor must be one of {list(MONITORS)}")
    if not isinstance(max_edge, int) or isinstance(max_edge, bool) or max_edge < 1:
        raise ValueError("max_edge must be a positive integer")
    if max_edge > MAX_EDGE_LIMIT:
        raise ValueError(f"max_edge above {MAX_EDGE_LIMIT} is refused")

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    left, top, src_w, src_h = _bounds(user32, monitor)
    if src_w <= 0 or src_h <= 0:
        # A service or a locked session has no desktop to read. Say that,
        # rather than returning a black rectangle a model will describe.
        raise ScreenUnavailable("no desktop is available to capture")

    out_w, out_h, scale = _target_size(src_w, src_h, max_edge)

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise ScreenUnavailable("could not open a device context for the screen")
    memory_dc = bitmap = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, out_w, out_h)
        if not memory_dc or not bitmap:
            raise ScreenUnavailable("could not allocate a bitmap for the capture")
        gdi32.SelectObject(memory_dc, bitmap)
        # HALFTONE averages when shrinking; the default would drop pixels
        # and hand the model aliased text.
        gdi32.SetStretchBltMode(memory_dc, HALFTONE)
        gdi32.SetBrushOrgEx(memory_dc, 0, 0, None)
        ok = gdi32.StretchBlt(memory_dc, 0, 0, out_w, out_h,
                              screen_dc, left, top, src_w, src_h, SRCCOPY)
        if not ok:
            raise ScreenUnavailable("the screen copy was refused by Windows")

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD),
                        ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.biWidth = out_w
        # negative height asks for a top-down image, so the rows arrive in
        # the order PNG wants instead of upside down
        info.biHeight = -out_h
        info.biPlanes = 1
        info.biBitCount = 32
        info.biCompression = BI_RGB

        buffer = ctypes.create_string_buffer(out_w * out_h * 4)
        copied = gdi32.GetDIBits(memory_dc, bitmap, 0, out_h, buffer,
                                 ctypes.byref(info), DIB_RGB_COLORS)
        if copied != out_h:
            raise ScreenUnavailable("the captured bitmap could not be read back")
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)

    # GDI hands back BGRA; PNG wants RGB. A slice assignment on a
    # bytearray does this at C speed - a per-pixel Python loop over a
    # million pixels is a visible pause on the latency path.
    bgra = bytearray(buffer.raw)
    rgb = bytearray(out_w * out_h * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]

    return Screenshot(png=_png(bytes(rgb), out_w, out_h), width=out_w,
                      height=out_h, scale=scale,
                      captured_at=(now or dt.datetime.now(dt.timezone.utc)))


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Photograph the desktop.")
    ap.add_argument("--out", metavar="PATH", help="write the PNG here")
    ap.add_argument("--max-edge", type=int, default=DEFAULT_MAX_EDGE)
    args = ap.parse_args(argv)
    try:
        shot = capture(max_edge=args.max_edge)
    except ScreenUnavailable as exc:
        print(f"can't: {exc}")
        return 1
    if args.out:
        with open(args.out, "wb") as handle:
            handle.write(shot.png)
        print(f"wrote {args.out}")
    for key, value in shot.metadata().items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
