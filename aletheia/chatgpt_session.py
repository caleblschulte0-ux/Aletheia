"""Read-only readiness check for Aletheia's signed-in ChatGPT browser profile.

Checking readiness never submits a prompt. Interactive authentication remains a
normal headed browser flow through `python -m aletheia.browse login ...`.
"""
from __future__ import annotations

import argparse
import json

from aletheia import browse, browser_reasoner


def status(*, open_a_window: bool = False) -> dict:
    """Is his signed-in ChatGPT usable? By default, ANSWERED WITHOUT OPENING IT.

    2026-09-12, his words: *"this keeps randomly opening chat GPT windows
    for no reason and then closing them right away ... it needs to stop
    just randomly popping up a ChatGPT window every fucking minute."*

    He was right, and this function was the cause. Its only gate was
    "is a browser installed", so every caller got a REAL ChatGPT window:
    the Command Center polls `/api/setup` every two minutes while the tab
    is open, `setup.audit()` calls `_chatgpt_browser()`, and that called
    this. A readiness CHECK was driving his personal account on a page
    refresh - and because it asked no lease, his two spoken orders to
    stop ("thea I said stop opening ChatGPT windows") could not stop it.

    So: a probe never opens a window. It reports what is on disk and what
    he has allowed. Only a caller that says `open_a_window=True` - the
    `python -m aletheia.chatgpt_session` he runs himself to prove the
    sign-in - is permitted to, and even then only under the lease.
    """
    ok, why = browse.available()
    if not ok:
        return {"ready": False, "reason": why}
    if not browse.PROFILE_DIR.exists():
        return {"ready": False, "reason": "browser profile has not been initialized"}
    allowed, lease_why = browser_reasoner.available()
    if not open_a_window:
        # The honest answer a health check is entitled to: the profile is
        # there, and whether she may use it. Anything more costs a window.
        if not allowed:
            return {"ready": False, "reason": lease_why}
        return {"ready": True,
                "reason": "signed-in profile is on disk and allowed "
                          "(not opened to check)"}
    if not allowed:
        return {"ready": False, "reason": lease_why}
    try:
        with browser_reasoner._subscription_session() as ctx:
            page = ctx.new_page()
            try:
                page.goto(browser_reasoner.CHATGPT_URL, wait_until="domcontentloaded")
                if not browser_reasoner._host_ok(page.url):
                    return {"ready": False, "reason": "ChatGPT redirected to authentication"}
                browser_reasoner._editor(page)
                return {"ready": True, "reason": "signed-in ChatGPT prompt is available"}
            finally:
                page.close()
    except browser_reasoner.BrowserReasonerUnavailable:
        return {"ready": False, "reason": "ChatGPT page loaded but the prompt is unavailable"}
    except Exception:
        return {"ready": False, "reason": "ChatGPT session check failed locally"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check the local ChatGPT subscription session.")
    ap.add_argument("--open", action="store_true",
                    help="really open the browser to prove the sign-in "
                         "(otherwise the check opens nothing)")
    args = ap.parse_args(argv)
    result = status(open_a_window=args.open)
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
