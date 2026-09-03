"""Browser control — the adapter-ladder rung that reaches sites with no API
(Playbook §§11, 14; Phase 8).

The browser is the world's largest unofficial interface. This module drives
a **dedicated, persistent browser profile** so the operator signs into his
own accounts once, normally, and Aletheia then works inside that authorized
session. Per §14 that is the only acceptable path: no copied cookies, no
bypassed authentication, no pretending to be a browser we are not.

On Windows, Aletheia prefers the operator's installed Google Chrome for both
manual sign-in and later Playwright automation. The one-time login flow opens
Chrome directly, not through Playwright; this avoids identity providers such as
Google rejecting an automation-controlled login browser while still keeping the
session inside Aletheia's dedicated local profile.

Three capabilities, split by what they DO rather than by convenience:

    read_page(url)              observe — no approval
    screenshot(url, out)        observe — no approval
    interact(url, steps, aid)   ACTS on someone else's system — requires an
                                APPROVED approval (§56 L4 / §61: browser.read
                                never implies browser.submit)

Everything respects the kill switch, and every call is journaled with what
it touched. Playwright is an OPTIONAL dependency: `available()` reports the
truth and callers degrade honestly rather than crashing (§104 — never
hallucinate a capability that isn't installed).

The profile lives in `cache/browser-profile/` (gitignored, never committed —
it holds real session cookies).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from aletheia import journal, policy
from aletheia.fleet import REPO_ROOT

PROFILE_DIR = REPO_ROOT / "cache" / "browser-profile"
DEFAULT_TIMEOUT_MS = 20_000
MAX_TEXT = 20_000

# steps interact() accepts; anything else is refused before the browser opens
STEP_ACTIONS = {"click", "type", "press", "wait_for", "select"}


def _chromium_path() -> str | None:
    """Respect a pre-provisioned Playwright browser if the environment pins one."""
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root:
        candidate = Path(root) / "chromium"
        if candidate.exists():
            return str(candidate)
    return None


def _system_chrome_path() -> str | None:
    """Return an installed/pinned Google Chrome executable when available.

    `ALETHEIA_CHROME_PATH` is an explicit operator override and is returned even
    when missing so `available()` can report the bad path instead of silently
    switching browsers.
    """
    pinned = os.environ.get("ALETHEIA_CHROME_PATH")
    if pinned:
        return pinned
    if os.name != "nt":
        return None

    candidates: list[Path] = []
    for root_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(root_name)
        if root:
            candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    which = shutil.which("chrome.exe") or shutil.which("chrome")
    if which:
        candidates.append(Path(which))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _browser_executable() -> str | None:
    """Use real Chrome on Windows so its manually-created session remains usable."""
    return _system_chrome_path() or _chromium_path()


def available() -> tuple[bool, str]:
    """(usable, reason) — the honest answer to 'can you drive a browser'."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False, "playwright is not installed (pip install playwright)"
    exe = _browser_executable()
    if exe and not Path(exe).exists():
        return False, f"browser executable not found at {exe}"
    return True, "ready"


def _closed_browser_error(exc: BaseException) -> bool:
    """True only for the benign cleanup error caused by a user closing Chrome."""
    text = str(exc).lower()
    return exc.__class__.__name__ == "TargetClosedError" or (
        "target page, context or browser has been closed" in text
    )


def native_login(url: str, profile: Path | None = None) -> int:
    """Open a normal installed Chrome process for one-time interactive login.

    No Playwright connection is made while credentials/Google authentication are
    entered. Chrome writes its authenticated session directly into the same
    dedicated profile Aletheia later opens with Playwright.
    """
    chrome = _system_chrome_path()
    if not chrome or not Path(chrome).is_file():
        raise RuntimeError(
            "Google Chrome is required for the normal sign-in flow on Windows; "
            "install Chrome or set ALETHEIA_CHROME_PATH"
        )
    profile_path = Path(profile or PROFILE_DIR)
    profile_path.mkdir(parents=True, exist_ok=True)
    cmd = [
        chrome,
        f"--user-data-dir={profile_path}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--new-window",
        url,
    ]
    return subprocess.run(cmd, check=False).returncode


class _Session:
    """A persistent-profile Playwright context. Context manager."""

    def __init__(self, headed: bool = False, profile: Path | None = None):
        self.headed = headed
        self.profile = Path(profile or PROFILE_DIR)
        self._pw = None
        self.context = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        kwargs = {"headless": not self.headed}
        exe = _browser_executable()
        if exe:
            kwargs["executable_path"] = exe
        self.context = self._pw.chromium.launch_persistent_context(
            str(self.profile), **kwargs)
        self.context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        return self.context

    def __exit__(self, *exc):
        try:
            if self.context:
                try:
                    self.context.close()
                except Exception as close_exc:
                    if not _closed_browser_error(close_exc):
                        raise
        finally:
            if self._pw:
                try:
                    self._pw.stop()
                except Exception as stop_exc:
                    if not _closed_browser_error(stop_exc):
                        raise


def _guard(what: str) -> None:
    policy.ensure_not_halted()
    ok, reason = available()
    if not ok:
        raise RuntimeError(f"cannot {what}: {reason}")


def read_page(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS,
              profile: Path | None = None) -> dict:
    """Observe a page: title, visible text, links. Read-only — no approval."""
    _guard("read a page")
    with _Session(profile=profile) as ctx:
        page = ctx.new_page()
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        result = {
            "url": page.url,
            "title": page.title(),
            "text": (page.inner_text("body") or "")[:MAX_TEXT],
            "links": [
                {"text": (a.get("text") or "").strip()[:120], "href": a.get("href")}
                for a in page.eval_on_selector_all(
                    "a[href]",
                    "els => els.slice(0, 100).map(e => ({text: e.innerText, href: e.href}))")
            ],
        }
        page.close()
    journal.append("action", "browser:read", f"read {result['url']} — {result['title'][:80]}")
    return result


def screenshot(url: str, out_path: str | Path, full_page: bool = True,
               profile: Path | None = None) -> Path:
    """Observe a page as an image. Read-only — no approval."""
    _guard("screenshot a page")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with _Session(profile=profile) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.screenshot(path=str(out), full_page=full_page)
        page.close()
    journal.append("action", "browser:screenshot", f"captured {url} -> {out.name}")
    return out


def validate_steps(steps: list[dict]) -> list[str]:
    """Refuse a malformed plan BEFORE opening a browser."""
    problems = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or "action" not in s:
            problems.append(f"steps[{i}]: needs an action")
            continue
        action = s["action"]
        if action not in STEP_ACTIONS:
            problems.append(f"steps[{i}]: action {action!r} not in {sorted(STEP_ACTIONS)}")
            continue
        if action in ("click", "type", "wait_for", "select") and not s.get("selector"):
            problems.append(f"steps[{i}]: {action} needs a selector")
        if action in ("type", "press", "select") and s.get("value") is None:
            problems.append(f"steps[{i}]: {action} needs a value")
    return problems


def plan_digest(url: str, steps: list[dict]) -> str:
    """sha256 of exactly where and exactly what. Must stay byte-identical to
    `work_session._digest_browser`, which has produced this shape since the
    work-session layer landed."""
    raw = json.dumps({"url": url, "steps": steps}, sort_keys=True,
                     separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def approval_action(url: str, steps: list[dict]) -> str:
    """The exact `requested_action` an approval for this plan must carry."""
    return f"browser.interact:{plan_digest(url, steps)}"


def interact(url: str, steps: list[dict], approval_id: str,
             profile: Path | None = None, step_guard=None) -> dict:
    """ACT on a page — click, type, submit. Requires an approval bound to
    THIS page and THESE steps.

    Separate from read_page on purpose (§61): permission to look at a page is
    never permission to press its buttons.

    Until 2026-09-03 this checked only that the approval was APPROVED, and a
    security review found the hole: any approved id authorized any browser
    action, so an approval issued to click "Next" on one site could be handed
    to a step list that pressed "Place order" on another. The errand layer did
    its own hash check and was safe; nothing else was, and a caller that
    forgets is exactly what a confused-deputy bug is made of. Authorization
    now lives in the primitive, where it cannot be forgotten (§61, §70).

    `step_guard`, when supplied by a stricter caller such as a bounded work
    session, receives `(page, step)` immediately before each action.
    """
    problems = validate_steps(steps)
    if problems:
        raise ValueError("; ".join(problems))
    if not policy.is_approved(approval_id):
        raise policy.Halted(
            f"approval {approval_id!r} is not APPROVED — browser interaction acts on "
            "someone else's system and is never self-authorized")
    try:
        approval = policy.load(approval_id)
    except Exception:
        approval = {}
    if approval.get("requested_action") != approval_action(url, steps):
        raise policy.Halted(
            f"approval {approval_id!r} is not bound to this exact page and plan — "
            "an approval authorizes one url and one step list, never a substitute")
    _guard("interact with a page")

    done = []
    with _Session(profile=profile) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        for s in steps:
            policy.ensure_not_halted()
            if step_guard is not None:
                step_guard(page, s)
            action, sel, val = s["action"], s.get("selector"), s.get("value")
            if action == "click":
                page.click(sel)
            elif action == "type":
                page.fill(sel, str(val))
            elif action == "press":
                page.keyboard.press(str(val))
            elif action == "select":
                page.select_option(sel, str(val))
            elif action == "wait_for":
                page.wait_for_selector(sel)
            done.append(action if not sel else f"{action}:{sel}")
        result = {
            "url": page.url,
            "title": page.title(),
            "text": (page.inner_text("body") or "")[:MAX_TEXT],
            "steps_done": done,
        }
        page.close()
    journal.append("action", "browser:interact",
                   f"{len(done)} step(s) on {url} under approval {approval_id} -> {result['url']}")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Drive the authorized browser profile.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_r = sub.add_parser("read"); p_r.add_argument("url")
    p_s = sub.add_parser("shot"); p_s.add_argument("url"); p_s.add_argument("out")
    p_l = sub.add_parser("login")
    p_l.add_argument("url", help="open real Chrome so you can sign in once")
    args = ap.parse_args(argv)

    ok, reason = available()
    if args.cmd == "status":
        print(f"browser: {'ready' if ok else 'unavailable'} — {reason}")
        print(f"profile: {PROFILE_DIR}")
        return 0 if ok else 1
    if not ok:
        print(f"browser unavailable — {reason}", file=sys.stderr)
        return 1
    if args.cmd == "read":
        page = read_page(args.url)
        print(json.dumps({k: v for k, v in page.items() if k != "text"}, indent=2))
        print("\n" + page["text"][:2000])
    elif args.cmd == "shot":
        print(f"wrote {screenshot(args.url, args.out)}")
    else:
        if os.name == "nt":
            print("Opening normal Google Chrome with Aletheia's dedicated profile.")
            print("Sign in normally. When ChatGPT is open and signed in, close that Chrome window.")
            rc = native_login(args.url)
            if rc != 0:
                print(f"Chrome sign-in window exited with code {rc}", file=sys.stderr)
                return 1
        else:
            print("Opening a browser window. Sign in normally, then close it.")
            with _Session(headed=True) as ctx:
                page = ctx.new_page()
                page.goto(args.url)
                input("Press Enter here when you are done signing in ... ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
