"""Post to his Instagram through Instagram's own web composer.

His words, 2026-09-25, after four hours stuck at Meta's door: *"Bro I'm not
seeing anywhere to do that and all this meta account and insta account and
Facebook acount shit is so confusing your supposed to be doing this for me."*

**Why this exists.** The Graph API route (`aletheia.instagram`) is built,
tested and correct, and he cannot use it. Creating the Meta app it needs is
refused at the account level — Meta's own words, read off his Business
portfolio on 2026-09-25: *"Your account must be confirmed before you can
create a new app. Please confirm your account by adding your mobile phone
number or credit card."* That is why it failed on his phone, on his PC, and on
every account he owns: it is not a device check, and no amount of retrying
moves it. There is also nobody to appeal to — Meta's bug tool requires the
developer account he cannot create.

So this is the same capability through the door that is actually open:
instagram.com's own "Create new post", driven in HER dedicated browser profile
(`browse.PROFILE_DIR`), where he signs in ONCE and never again.

**What it buys, honestly.** No Meta app, no developer account, no access
token, no 60-day refresh, no public https address for his media — the web
composer takes a file off this PC directly, which is what he actually has.
**What it costs, honestly.** It is a browser automation: Instagram can move a
button and break it, where the API is versioned and stable. It fails LOUDLY
and posts nothing rather than guessing, and every failure keeps a screenshot
so the break can be seen rather than theorised about.

Nothing here widens authority. `instagram_post` is still world-tier and
`tools.OUTWARD_ALWAYS`, so every post is still an approval of his; this module
only changes which door the approved post goes through.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from aletheia import journal, stateio

ACTOR = "aletheia-instagram-web"
HOME = "https://www.instagram.com/"

#: Instagram's composer is a sequence of screens. Each step names the thing it
#: is looking for AND what it means, so a break says which screen moved.
STEP_TIMEOUT_MS = 30_000
UPLOAD_TIMEOUT_MS = 120_000
SHARE_TIMEOUT_MS = 180_000

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
MAX_CAPTION = 2200


def _dir() -> Path:
    return stateio.private_dir("instagram")


def _shots_dir() -> Path:
    return _dir() / "web-failures"


def _now() -> str:
    return stateio.utcnow()


# --------------------------------------------------------------- readiness


def signed_in(*, context=None) -> tuple[bool, str]:
    """Is HER browser signed in to Instagram, and as whom?

    The real attempt, because "there is a profile directory" proves nothing
    (§ INSTALLED is not WORKING). Loads the page and looks for the composer
    entry point, which only a signed-in session has. Presses nothing.
    """
    try:
        from aletheia import browse
    except Exception as exc:  # noqa: BLE001
        return False, f"her browser is not available ({type(exc).__name__})"

    def _look(ctx) -> tuple[bool, str]:
        page = ctx.new_page()
        try:
            page.goto(HOME, wait_until="domcontentloaded", timeout=STEP_TIMEOUT_MS)
            page.wait_for_timeout(4000)
            if page.locator("input[name='username']").count():
                return False, "she is not signed in to Instagram in her own browser yet"
            if not page.get_by_role("link", name="Create").count():
                body = (page.inner_text("body") or "")[:120].replace("\n", " ")
                if "Log in" in body or "Sign up" in body:
                    return False, "she is not signed in to Instagram in her own browser yet"
                return False, f"Instagram loaded but the composer is not there ({body!r})"
            who = _whoami(page)
            if not who:
                return True, "signed in to Instagram, though the page did not say as whom"
            from aletheia import instagram
            try:
                instagram.check_account(who.lstrip("@"))
            except RuntimeError as exc:
                return False, str(exc)
            return True, f"signed in to Instagram as {who}"
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

    try:
        if context is not None:
            return _look(context)
        with browse._Session(headed=False) as ctx:
            return _look(ctx)
    except browse.BrowserBusy as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, browse.say_reason(f"{type(exc).__name__}: {exc}")


def _whoami(page) -> str:
    """The handle the page is signed in as, or "". Never raises."""
    try:
        link = page.locator("a[href^='/'][role='link']").filter(has_text="").first
        for sel in ("nav a[href*='/'][tabindex]", "a:has(img[alt*='profile picture'])"):
            found = page.locator(sel).first
            if found.count():
                href = (found.get_attribute("href") or "").strip("/")
                if href and "/" not in href:
                    return "@" + href
        _ = link
    except Exception:  # noqa: BLE001
        pass
    return ""


def available() -> tuple[bool, str]:
    """Store-level, no network: is there a profile she could be signed into?

    The honest live question is `signed_in()`; this is what a refusal and a
    checklist may ask without paying a browser launch.
    """
    try:
        from aletheia import browse
        ok, why = browse.available()
        if not ok:
            return False, why
        if not Path(browse.PROFILE_DIR).is_dir():
            return False, SETUP
        return True, "her browser is installed and has a profile"
    except Exception as exc:  # noqa: BLE001
        return False, f"her browser is not available ({type(exc).__name__})"


# Said to the room. One sentence, one action, and no Meta in it.
SETUP = ("Instagram isn't connected yet, and it's one sign-in: I'll open my own browser window at "
         "the Instagram login page, you sign in once, and I'm set from then on. Nothing to do with "
         "Meta, no developer account, no codes.")


# ----------------------------------------------------------------- posting


def media_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return "REELS"
    if suffix in IMAGE_SUFFIXES:
        return "IMAGE"
    raise RuntimeError(f"Instagram takes pictures and video; {suffix or 'that file'} is neither")


def _keep_failure(page, where: str) -> str:
    """A screenshot of the screen that broke, so a break can be LOOKED AT.

    A browser automation that fails with a selector name tells whoever reads
    it nothing about what Instagram actually showed. Never raises — a failed
    screenshot must not replace the real error.
    """
    try:
        _shots_dir().mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = _shots_dir() / f"{stamp}-{where}.png"
        page.screenshot(path=str(out))
        return str(out)
    except Exception:  # noqa: BLE001
        return ""


def _click_next(page, which: str) -> None:
    """The composer's Next, which appears on crop and again on filters."""
    button = page.get_by_role("button", name="Next")
    if not button.count():
        button = page.locator("div[role='button']", has_text="Next")
    if not button.count():
        raise RuntimeError(f"Instagram's composer did not offer Next at the {which} step")
    button.first.click()
    page.wait_for_timeout(1500)


def publish(media: str | Path, caption: str = "", *, context=None,
            share: bool = True) -> dict:
    """Publish ONE local picture or video with a caption, through the composer.

    `share=False` walks the whole flow and stops WITHOUT pressing Share, which
    is how a dry run proves the path without reaching the world.
    """
    from aletheia import browse, instagram

    path = Path(str(media)).expanduser()
    if not path.is_file():
        raise RuntimeError(f"there is no file at {path}")
    kind = media_kind(path)
    text = instagram.normalize_caption(caption)
    if len(text) > MAX_CAPTION:
        raise RuntimeError(f"the caption is {len(text)} characters and Instagram's limit is {MAX_CAPTION}")

    def _run(ctx) -> dict:
        page = ctx.new_page()
        where = "start"
        try:
            page.goto(HOME, wait_until="domcontentloaded", timeout=STEP_TIMEOUT_MS)
            page.wait_for_timeout(3000)
            if page.locator("input[name='username']").count():
                raise RuntimeError(SETUP)

            where = "account"
            # WHOSE ACCOUNT IS THIS? Asked BEFORE the composer is opened, so a
            # session signed in as the wrong account never reaches a Share
            # button at all. Fails closed (see instagram.check_account).
            instagram.check_account(_whoami(page).lstrip("@"))

            where = "create"
            create = page.get_by_role("link", name="Create")
            if not create.count():
                raise RuntimeError(SETUP)
            create.first.click()
            page.wait_for_timeout(1500)
            # The sidebar Create opens a small menu (Post / Live video / Ad)
            # on a professional account, and goes straight to the dialog on a
            # personal one. Both are fine; only press Post if it is offered.
            post_item = page.get_by_role("link", name="Post")
            if post_item.count():
                post_item.first.click()
                page.wait_for_timeout(2000)

            where = "file"
            file_input = page.locator("input[type='file']")
            if not file_input.count():
                raise RuntimeError("Instagram's composer did not offer a file to choose")
            file_input.first.set_input_files(str(path))
            page.wait_for_timeout(4000)

            where = "crop"
            _click_next(page, "crop")
            where = "filters"
            _click_next(page, "filters")

            where = "caption"
            if text:
                box = page.get_by_role("textbox", name="Write a caption...")
                if not box.count():
                    box = page.locator("div[contenteditable='true']")
                if not box.count():
                    raise RuntimeError("Instagram's composer did not offer a caption box")
                box.first.click()
                box.first.type(text, delay=8)
                page.wait_for_timeout(800)

            if not share:
                shot = _keep_failure(page, "dry-run")
                journal.append("event", "instagram",
                               f"walked the Instagram composer for {path.name} and stopped "
                               "before Share (dry run)", actor=ACTOR)
                return {"dry_run": True, "kind": kind, "caption": text,
                        "file": str(path), "screenshot": shot}

            where = "share"
            button = page.get_by_role("button", name="Share")
            if not button.count():
                button = page.locator("div[role='button']", has_text="Share")
            if not button.count():
                raise RuntimeError("Instagram's composer did not offer Share")
            button.first.click()

            where = "confirm"
            page.wait_for_selector("text=Your post has been shared",
                                   timeout=SHARE_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001
            shot = _keep_failure(page, where)
            raise RuntimeError(
                f"Instagram's own page did not get as far as posting ({where}): "
                f"{browse.say_reason(str(exc))}"
                + (f" — what the screen looked like: {shot}" if shot else "")) from None
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

        row = {"id": f"web-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
               "at": _now(), "kind": kind, "caption": text, "file": str(path),
               "via": "web", "username": ""}
        _record(row)
        first = text.split("\n", 1)[0][:80]
        journal.append("action", "instagram",
                       f"posted {'a reel' if kind == 'REELS' else 'a picture'} to Instagram "
                       f"through her own browser: {first!r}" if first else
                       f"posted {'a reel' if kind == 'REELS' else 'a picture'} to Instagram "
                       "through her own browser", actor=ACTOR)
        return row

    if context is not None:
        return _run(context)
    with browse._Session(headed=False) as ctx:
        return _run(ctx)


def _record(row: dict) -> None:
    """ONE ledger for both doors. "What have you posted to Instagram" must not
    depend on which route the post happened to take."""
    _dir().mkdir(parents=True, exist_ok=True)
    with (_dir() / "posts.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def open_login() -> str:
    """Open a real Chrome window in HER profile at Instagram's login page.

    The one thing that is his, once: `browse.native_login` writes the signed-in
    session straight into the profile Playwright later opens, so no password
    passes through Aletheia and none is stored.
    """
    from aletheia import browse
    journal.append("event", "instagram",
                   "opened her own browser at the Instagram login page for his one sign-in",
                   actor=ACTOR)
    browse.native_login("https://www.instagram.com/accounts/login/")
    ok, why = signed_in()
    journal.append("event", "instagram", f"after the sign-in window: {why}", actor=ACTOR)
    return why
