"""Read-only readiness check for Aletheia's signed-in ChatGPT browser profile.

Checking readiness never submits a prompt. Interactive authentication remains a
normal headed browser flow through `python -m aletheia.browse login ...`.
"""
from __future__ import annotations

import argparse
import json

from aletheia import browse, browser_reasoner


def status() -> dict:
    ok, why = browse.available()
    if not ok:
        return {"ready": False, "reason": why}
    if not browse.PROFILE_DIR.exists():
        return {"ready": False, "reason": "browser profile has not been initialized"}
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
    argparse.ArgumentParser(description="Check the local ChatGPT subscription session.").parse_args(argv)
    result = status()
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
