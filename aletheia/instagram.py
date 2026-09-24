"""Post to his Instagram account through the Instagram Graph API.

His words, 2026-09-24: *"I need an app or API or whatever it requires to
automatically post stuff to Instagram. I need her to set that up."* This is
the door: the two Graph API calls that publish an image with a caption
(create a media container, then publish it), the token read from the DPAPI
vault by NAME and never written anywhere, and a ledger of what went out.

What only he can do, and what this module says plainly until it is done:
the Instagram account has to be a professional account, a Meta developer
app has to hold the `instagram_content_publish` permission, and the
long-lived access token and the Instagram user id have to be put here once:

    python -m aletheia.secret_store put instagram.token --provider instagram --kind api_token
    python -m aletheia.instagram configure <instagram-user-id> --username <handle>

Publishing is OUTWARD: it reaches the world, so every post is an approval
of his (the `instagram_post` kind is world-tier and `tools.OUTWARD_ALWAYS`
names it). Nothing here widens authority.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from aletheia import journal, stateio

ACTOR = "aletheia-instagram"
TOKEN_ALIAS = "instagram.token"
GRAPH = "https://graph.facebook.com/v21.0"
MAX_CAPTION = 2200
SETUP = ("Instagram isn't set up yet. It needs your Instagram user id once "
         "(python -m aletheia.instagram configure <id>) and the long-lived access token in my vault "
         "(python -m aletheia.secret_store put instagram.token --provider instagram --kind api_token); "
         "both come from the Meta developer app after your account is a professional account.")


def _dir() -> Path:
    return stateio.private_dir("instagram")


def _config_path() -> Path:
    return _dir() / "config.json"


def _ledger_path() -> Path:
    return _dir() / "posts.jsonl"


def config() -> dict:
    try:
        raw = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def configure(user_id: str, *, username: str = "") -> dict:
    user_id = str(user_id or "").strip()
    if not user_id.isdigit():
        raise ValueError("the Instagram user id is a number (the professional account's IG User ID)")
    value = {"user_id": user_id, "username": str(username or "").strip().lstrip("@"),
             "configured_at": stateio.utcnow()}
    _dir().mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(_config_path(), value)
    journal.append("event", "instagram", f"configured for user id {user_id}"
                   + (f" (@{value['username']})" if value["username"] else ""), actor=ACTOR)
    return value


def _token() -> str:
    from aletheia import secret_store
    return secret_store.get(TOKEN_ALIAS)


def available() -> tuple[bool, str]:
    """(ready, why). Checked from the stores, never by calling Instagram."""
    if not config().get("user_id"):
        return False, SETUP
    try:
        from aletheia import secret_store
        if not secret_store.exists(TOKEN_ALIAS):
            return False, SETUP
    except Exception as exc:  # noqa: BLE001
        return False, f"the vault could not be read ({type(exc).__name__})"
    who = config().get("username")
    return True, f"ready to post to Instagram{' as @' + who if who else ''}"


class GraphTransport:
    """The real thing: two POSTs to the Graph API. Stdlib only."""

    def post(self, path: str, fields: dict) -> dict:
        data = urllib.parse.urlencode(fields).encode("utf-8")
        req = urllib.request.Request(f"{GRAPH}/{path}", data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:600]
            try:
                err = json.loads(body).get("error") or {}
                said = str(err.get("message") or body)
            except ValueError:
                said = body
            raise RuntimeError(f"Instagram said no ({exc.code}): {said}") from None


def publish(image_url: str, caption: str, *, transport=None) -> dict:
    """Create a media container for `image_url` with `caption`, publish it,
    and record it. Raises RuntimeError with a sentence when Instagram
    refuses; the token never appears in the sentence, the ledger or the
    journal."""
    ready, why = available()
    if not ready:
        raise RuntimeError(why)
    image_url = str(image_url or "").strip()
    if not image_url.startswith("https://"):
        raise RuntimeError("Instagram only takes a public https image address for the picture")
    caption = " ".join(str(caption or "").split())
    if len(caption) > MAX_CAPTION:
        raise RuntimeError(f"the caption is over Instagram's {MAX_CAPTION} characters")
    user = str(config()["user_id"])
    driver = transport or GraphTransport()
    token = _token()
    made = driver.post(f"{user}/media", {"image_url": image_url, "caption": caption, "access_token": token})
    creation = str((made or {}).get("id") or "")
    if not creation:
        raise RuntimeError("Instagram did not give back a media container")
    out = driver.post(f"{user}/media_publish", {"creation_id": creation, "access_token": token})
    media_id = str((out or {}).get("id") or "")
    if not media_id:
        raise RuntimeError("Instagram accepted the picture but did not publish it")
    row = {"id": media_id, "at": stateio.utcnow(), "image_url": image_url, "caption": caption,
           "user_id": user, "username": str(config().get("username") or "")}
    _dir().mkdir(parents=True, exist_ok=True)
    with _ledger_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    journal.append("action", "instagram", f"posted to Instagram: {caption[:80]!r}" if caption else
                   "posted a picture to Instagram", actor=ACTOR)
    return row


def posts(limit: int = 20) -> list[dict]:
    """What she has posted, newest first, from her own ledger."""
    try:
        lines = _ledger_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    out.reverse()
    return out[:max(1, int(limit))]


def spoken_posts() -> str:
    from aletheia import speech
    rows = posts()
    ready, why = available()
    if not rows:
        return ("Nothing posted to Instagram yet." if ready else "Nothing posted to Instagram yet; " + why)
    said = [f"{(r.get('caption') or 'a picture')[:60]!r} ({speech.humanize_time(str(r.get('at') or ''))})"
            for r in rows[:4]]
    return (f"{speech.count_phrase(len(rows), 'post')} to Instagram: " + "; ".join(said)
            + (f"; and {len(rows) - 4} more" if len(rows) > 4 else "") + ".")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Post to his Instagram through the Graph API.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    conf = sub.add_parser("configure")
    conf.add_argument("user_id")
    conf.add_argument("--username", default="")
    post = sub.add_parser("post")
    post.add_argument("image_url")
    post.add_argument("--caption", default="")
    sub.add_parser("posts")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "status":
            ready, why = available()
            print(("READY: " if ready else "NOT READY: ") + why)
        elif args.cmd == "configure":
            print(json.dumps(configure(args.user_id, username=args.username), indent=2))
        elif args.cmd == "post":
            row = publish(args.image_url, args.caption)
            print(f"posted: media id {row['id']}")
        elif args.cmd == "posts":
            print(spoken_posts())
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
