"""Read-only Windows context prototype for Playbook §48.

Production Aletheia can already list/inspect UIA windows, but §48 calls for the
ambient *current computer context* needed to resolve phrases such as "this" and
"send this to Claude": foreground window/app and clipboard, without performing
an action. This staging module keeps that observation separate from
`computer.control` and never writes it to disk.

The clipboard is deliberately treated like camera pixels: diagnostics expose a
hash and length, not its contents. A caller must explicitly request
`reasoning_context(include_clipboard=True)` to disclose the text to a reasoning
step.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import PurePath, PureWindowsPath
from typing import Protocol

from .mobile_sensors import _utc

MAX_TITLE_CHARS = 500
MAX_PATH_CHARS = 4096
MAX_CLIPBOARD_CHARS = 20_000


def _clean(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", " ").split())[:limit]


@dataclass(frozen=True)
class ClipboardObservation:
    text: str = field(repr=False)
    observed_at: dt.datetime
    source: str = "windows.clipboard"

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("clipboard text must be a string")
        if len(self.text) > MAX_CLIPBOARD_CHARS:
            raise ValueError(f"clipboard text exceeds {MAX_CLIPBOARD_CHARS} characters")
        _utc(self.observed_at)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def metadata(self) -> dict:
        return {
            "source": self.source,
            "observed_at": _utc(self.observed_at).isoformat(),
            "chars": len(self.text),
            "sha256": self.digest,
            "present": bool(self.text),
        }


@dataclass(frozen=True)
class DesktopContextObservation:
    observed_at: dt.datetime
    active_window_title: str = field(repr=False)
    process_id: int | None = None
    process_path: str = field(default="", repr=False)
    clipboard: ClipboardObservation | None = field(default=None, repr=False)
    source: str = "windows.foreground"

    def __post_init__(self) -> None:
        _utc(self.observed_at)
        if self.process_id is not None and (isinstance(self.process_id, bool) or not isinstance(self.process_id, int) or self.process_id < 0):
            raise ValueError("process_id must be a non-negative integer or null")
        if len(self.active_window_title) > MAX_TITLE_CHARS:
            raise ValueError("active window title exceeds limit")
        if len(self.process_path) > MAX_PATH_CHARS:
            raise ValueError("process path exceeds limit")

    @property
    def process_name(self) -> str:
        return (PureWindowsPath(self.process_path).name if "\\" in self.process_path else PurePath(self.process_path).name) if self.process_path else ""

    def metadata(self) -> dict:
        title_bytes = self.active_window_title.encode("utf-8")
        return {
            "source": self.source,
            "observed_at": _utc(self.observed_at).isoformat(),
            "window_title_chars": len(self.active_window_title),
            "window_title_sha256": hashlib.sha256(title_bytes).hexdigest(),
            "process_id": self.process_id,
            "process_name": self.process_name,
            "clipboard": None if self.clipboard is None else self.clipboard.metadata(),
        }

    def reasoning_context(self, *, include_clipboard: bool = False) -> dict:
        value = {
            **self.metadata(),
            "active_window_title": self.active_window_title,
        }
        if include_clipboard and self.clipboard is not None:
            value["clipboard"] = {**self.clipboard.metadata(), "text": self.clipboard.text}
        return value


class DesktopContextBackend(Protocol):
    def foreground(self) -> dict:
        """Return title/process_id/process_path for the current foreground window."""

    def clipboard_text(self) -> str | None:
        """Return current Unicode clipboard text or None."""


def capture(backend: DesktopContextBackend, *, now: dt.datetime | None = None,
            include_clipboard: bool = True) -> DesktopContextObservation:
    now = _utc(now or dt.datetime.now(dt.timezone.utc))
    raw = backend.foreground()
    if not isinstance(raw, dict):
        raise ValueError("foreground backend must return an object")
    unknown = set(raw) - {"title", "process_id", "process_path"}
    if unknown:
        raise ValueError(f"foreground backend returned unknown fields {sorted(unknown)}")
    title = _clean(raw.get("title"), MAX_TITLE_CHARS)
    pid = raw.get("process_id")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid < 0):
        raise ValueError("foreground process_id is invalid")
    process_path = _clean(raw.get("process_path"), MAX_PATH_CHARS)
    clipboard = None
    if include_clipboard:
        text = backend.clipboard_text()
        if text is not None:
            if not isinstance(text, str):
                raise ValueError("clipboard backend must return text or null")
            if len(text) > MAX_CLIPBOARD_CHARS:
                raise ValueError(f"clipboard text exceeds {MAX_CLIPBOARD_CHARS} characters")
            clipboard = ClipboardObservation(text, now)
    return DesktopContextObservation(now, title, pid, process_path, clipboard)


class WindowsContextBackend:
    """Stdlib/ctypes read-only implementation; no clicks, keys, or focus changes."""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    CF_UNICODETEXT = 13

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows desktop context is available only on Windows")
        from ctypes import wintypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.user32.OpenClipboard.argtypes = [wintypes.HWND]
        self.user32.OpenClipboard.restype = wintypes.BOOL
        self.user32.GetClipboardData.argtypes = [wintypes.UINT]
        self.user32.GetClipboardData.restype = wintypes.HANDLE
        self.user32.CloseClipboard.restype = wintypes.BOOL
        self.kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalLock.restype = ctypes.c_void_p
        self.kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalUnlock.restype = wintypes.BOOL

    def foreground(self) -> dict:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "", "process_id": None, "process_path": ""}
        length = max(0, int(self.user32.GetWindowTextLengthW(hwnd)))
        title_buf = ctypes.create_unicode_buffer(min(length + 1, MAX_TITLE_CHARS + 1))
        self.user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
        pid = ctypes.c_ulong(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_path = ""
        handle = self.kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if handle:
            try:
                size = ctypes.c_ulong(MAX_PATH_CHARS)
                path_buf = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
                if self.kernel32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                    process_path = path_buf.value
            finally:
                self.kernel32.CloseHandle(handle)
        return {"title": title_buf.value, "process_id": int(pid.value), "process_path": process_path}

    def clipboard_text(self) -> str | None:
        if not self.user32.OpenClipboard(None):
            return None
        try:
            handle = self.user32.GetClipboardData(self.CF_UNICODETEXT)
            if not handle:
                return None
            ptr = self.kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                value = ctypes.wstring_at(ptr)
            finally:
                self.kernel32.GlobalUnlock(handle)
            if len(value) > MAX_CLIPBOARD_CHARS:
                raise ValueError(f"clipboard text exceeds {MAX_CLIPBOARD_CHARS} characters")
            return value
        finally:
            self.user32.CloseClipboard()
