"""Browser control — the adapter-ladder rung that reaches sites with no API
(Playbook §§11, 14; Phase 8).

The browser is the world's largest unofficial interface. This module drives
a **dedicated, persistent Chromium profile** so the operator signs into his
own accounts once, normally, and Aletheia then works inside that authorized
session. Per §14 that is the only acceptable path: no copied cookies, no
bypassed authentication, no pretending to be a browser we are not.

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
import json
import sys
from pathlib import Path

from aletheia import journal, policy
from aletheia.fleet import REPO_ROOT

PROFILE_DIR = REPO_ROOT / "cache" / "browser-profile"
DEFAULT_TIMEOUT_MS = 20_000
MAX_TEXT = 20_000

# steps interact() accepts; anything else is refused before the browser opens
STEP_ACTIONS = {"click", "type", "press", "wait_for", "select"}


def available() -> tuple[bool, str]:
    """(usable, reason) — the honest answer to 'can you drive a browser'."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False, "playwright is not installed (pip install playwright)"
    exe = _chromium_path()
    if exe and not Path(exe).exists():
        return False, f"chromium not found at {exe}"
    return True, "ready"


def _chromium_path() -> str | None:
    """Respect a pre-provisioned browser if the environment pins one."""
    import os
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root:
        candidate = Path(root) / "chromium"
        if candidate.exists():
            return str(candidate)
    return None


class _Session:
    """A persistent-profile Chromium context. Context manager."""

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
        exe = _chromium_path()
        if exe:
            kwargs["executable_path"] = exe
        self.context = self._pw.chromium.launch_persistent_context(
            str(self.profile), **kwargs)
        self.context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        return self.context

    def __exit__(self, *exc):
        try:
            if self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()


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


def interact(url: str, steps: list[dict], approval_id: str,
             profile: Path | None = None) -> dict:
    """ACT on a page — click, type, submit. Requires an APPROVED approval.

    Separate from read_page on purpose (§61): permission to look at a page is
    never permission to press its buttons. The approval is checked before the
    browser opens, and the steps are validated before that.
    """
    problems = validate_steps(steps)
    if problems:
        raise ValueError("; ".join(problems))
    if not policy.is_approved(approval_id):
        raise policy.Halted(  # refusal, surfaced the same way a halt is
            f"approval {approval_id!r} is not APPROVED — browser interaction acts on "
            "someone else's system and is never self-authorized")
    _guard("interact with a page")

    done = []
    with _Session(profile=profile) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        for s in steps:
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
    p_l.add_argument("url", help="open a real window so you can sign in once")
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
    else:  # login — opens a real window on the operator's machine
        print("Opening a browser window. Sign in normally, then close it.")
        with _Session(headed=True) as ctx:
            page = ctx.new_page()
            page.goto(args.url)
            input("Press Enter here when you are done signing in ... ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
