"""Post to his Instagram account — pictures and Reels — through Meta's API.

His words, 2026-09-24: *"I need an app or API or whatever it requires to
automatically post stuff to Instagram. I need her to set that up."* And,
2026-09-25, when the work was waiting on a yes: *"I gave it its permission.
And if it didn't give me my permission there, then boom, I'm giving it here.
It has my permission. Just get this done. I don't care what it takes."*
That yes is to the setup and the merge. It is NOT permission to post
anything without his approval of that specific post: `instagram_post` is
world-tier and `tools.OUTWARD_ALWAYS`, so every post is still an approval
of his, and nothing here widens authority.

**Two routes, one module.** Meta has two ways in and the token says which:

- *Instagram API with Instagram Login* — host `graph.instagram.com`, scopes
  `instagram_business_basic` + `instagram_business_content_publish`, no
  Facebook Page anywhere. Its tokens start `IGAA`. This is the easy path for
  one person's own professional account and it is what the setup asks for.
- *Instagram API with Facebook Login* — host `graph.facebook.com`, a
  Facebook Page linked to the account. Its tokens start `EAA`. Supported
  because it is the only route with a resumable upload endpoint.

The API version is NOT hardcoded: `api_version()` reads the config, then
`ALETHEIA_INSTAGRAM_API_VERSION`, then `DEFAULT_API_VERSION`. v21.0 was
pinned here and is near end of life; a version is data, and a module that
has to be edited to follow Meta's calendar gets left behind.

**Setup is ONE command at his keyboard**: `python -m aletheia.instagram
connect`. It prompts for the token without echoing it, works out which
route it belongs to from its prefix, discovers the Instagram user id from
the token itself (`GET /me?fields=user_id,username` — so he never has to go
find a number), stores the token in the DPAPI vault as `instagram.token`,
and then proves the whole thing with a read-only call before it says READY.
`status` makes that same live call, because configured is not connected
(§30): a readiness check that confuses them is wrong exactly where he is
trusting it.

**The token refreshes itself.** A dashboard token lasts 60 days.
`refresh_if_due()` runs on the Core's beat and calls
`GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`
before it expires (Meta requires the token be at least 24 hours old). The
refresh is journaled; the token never is — not in git, the journal, a
receipt, a log, a screenshot or an error sentence.

**Local files.** Meta has no upload for images at all: a picture is
published by handing Instagram a public `https` address it fetches itself,
and resumable upload (`rupload.facebook.com`) exists for video only and
only on the Facebook Login route. His content is files on this PC, so
something has to serve them for the minute the fetch takes. The option
picked, and why: **a temporary file on a branch of his OWN public GitHub
repository**, read back over `raw.githubusercontent.com`, removed and the
branch deleted as soon as the post lands. It is his account, his repo and a
credential he already has in the vault (`github.fleet`), so nothing is
uploaded to a third-party host he did not choose; the address is a content
hash nobody can guess; and the stager VERIFIES the content type it just
published before handing the address to Meta rather than assuming (measured
2026-09-25: that host serves a .png as `image/png` and a .mp4 as
`application/octet-stream`, so a picture is held to `image/*` and a video is
allowed octet-stream, which Meta reads the container of). What it
is not is a secrecy mechanism, and that is measured rather than hedged: on
2026-09-25 a staged JPEG came back `image/jpeg` at the right byte count, the
teardown removed the file AND the branch (the GitHub API answers 404 for
both afterwards), and `raw.githubusercontent.com` went on serving the blob
from its CDN for minutes after that. So the honest window is minutes, not
seconds, which is fine for media he is in the act of publishing publicly and
is the reason this is never used for anything else. `staging` in the config
turns it off, in which case a local path is refused in words instead.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from aletheia import journal, stateio

ACTOR = "aletheia-instagram"
TOKEN_ALIAS = "instagram.token"
GITHUB_TOKEN_ALIAS = "github.fleet"

IG_HOST = "https://graph.instagram.com"
FB_HOST = "https://graph.facebook.com"
ROUTE_IG = "instagram"
ROUTE_FB = "facebook"
# Meta's current version as of 2026-09-25. Data, not a pin: config first,
# then the environment, then this.
DEFAULT_API_VERSION = "v25.0"
API_VERSION_ENV = "ALETHEIA_INSTAGRAM_API_VERSION"
SCOPES_IG = ("instagram_business_basic", "instagram_business_content_publish")

MAX_CAPTION = 2200
JPEG_SUFFIXES = {".jpg", ".jpeg"}
CONVERTIBLE_SUFFIXES = {".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
IMAGE = "IMAGE"
REELS = "REELS"

# Container status polling. Meta's own guidance is about once a minute; a
# Reel that is still transcoding after five minutes is a fact, not a wait.
CONTAINER_POLL_S = 60.0
CONTAINER_BUDGET_S = {IMAGE: 60.0, REELS: 300.0}
CONTAINER_READY = "FINISHED"
CONTAINER_WORKING = "IN_PROGRESS"

TOKEN_LIFETIME_DAYS = 60          # what "Generate token" hands him
REFRESH_WHEN_UNDER_DAYS = 10      # refresh with room to spare
REFRESH_NOT_BEFORE_HOURS = 24     # Meta refuses a token younger than this
REFRESH_CHECK_EVERY_S = 6 * 3600  # how often the beat bothers to look

STAGE_MAX_BYTES = 90 * 1024 * 1024
STAGE_BRANCH = "thea-media"
STAGE_DIR = "thea-media"

# Said to the room. No commands in it: the exact lines belong on his setup
# page, and reading a shell command out loud is not an answer (§ the one
# page is the product — no developer words above the drawer).
SETUP = ("Instagram isn't set up yet, and the three things left are yours: switch the account to a "
         "professional account, create the Meta developer app and generate a token for it, then paste "
         "that token into me once at your keyboard. Your setup page has the exact steps.")


# ---------------------------------------------------------------- config


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


def _save(**changes) -> dict:
    value = config()
    value.update(changes)
    _dir().mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(_config_path(), value)
    return value


def api_version() -> str:
    """Config, then the environment, then the default. Never hardcoded at a
    call site — Meta retires versions on its own calendar."""
    for candidate in (config().get("api_version"), os.environ.get(API_VERSION_ENV)):
        text = str(candidate or "").strip()
        if re.fullmatch(r"v\d+\.\d+", text):
            return text
    return DEFAULT_API_VERSION


def route_of(token: str) -> str:
    """Which of Meta's two routes a token belongs to, from its prefix.

    `IGAA...` is an Instagram-Login user token (graph.instagram.com);
    `EAA...` is a Facebook-Login token (graph.facebook.com). Anything else
    falls back to whatever the config recorded, then to the Instagram route,
    because that is the one the setup asks for.
    """
    text = str(token or "")
    if text.startswith("IGAA"):
        return ROUTE_IG
    if text.startswith("EAA"):
        return ROUTE_FB
    saved = str(config().get("route") or "").strip()
    return saved if saved in (ROUTE_IG, ROUTE_FB) else ROUTE_IG


def host_for(route: str) -> str:
    return FB_HOST if route == ROUTE_FB else IG_HOST


def base_for(token: str) -> str:
    return f"{host_for(route_of(token))}/{api_version()}"


def _token() -> str:
    from aletheia import secret_store
    return secret_store.get(TOKEN_ALIAS)


# ------------------------------------------------------------- transport


def _scrub(text: str) -> str:
    """Whatever we are about to say, without a token in it. Belt and braces:
    a Graph GET carries the token in the query string, so any URL that
    reaches a message, a log or an exception passes through here."""
    return re.sub(r"(access_token=)[^&\s]+", r"\1<hidden>", str(text))


class GraphTransport:
    """The real thing: stdlib HTTP against Meta's Graph hosts.

    Takes FULL urls so the host and the API version are visible to whoever
    is looking — including a test, which is how "an IGAA token goes to
    graph.instagram.com" becomes something a suite can prove.

    The timeout is short for the read-only questions and long for a post,
    because `verify()` is what the setup page calls when he presses the
    button: a readiness check that can hang for two minutes is a page that
    looks broken (§ a readiness check is a button, never a poll).
    """

    def __init__(self, timeout: float = 120.0):
        self.timeout = float(timeout)

    def _read(self, req: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:600]
            try:
                err = json.loads(body).get("error") or {}
                said = str(err.get("message") or body)
            except ValueError:
                said = body
            raise RuntimeError(f"Instagram said no ({exc.code}): {_scrub(said)}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Instagram could not be reached ({_scrub(exc.reason)})") from None

    def post(self, url: str, fields: dict) -> dict:
        data = urllib.parse.urlencode(fields).encode("utf-8")
        return self._read(urllib.request.Request(url, data=data, method="POST"))

    def get(self, url: str, params: dict) -> dict:
        full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return self._read(urllib.request.Request(full, method="GET"))


ASK_TIMEOUT_S = 20.0    # a read-only question, behind a button he pressed
POST_TIMEOUT_S = 120.0  # Meta fetches the media inside this call


def _transport(given=None, *, timeout: float = POST_TIMEOUT_S) -> "GraphTransport":
    return given if given is not None else GraphTransport(timeout)


# ------------------------------------------------------------- readiness


def available() -> tuple[bool, str]:
    """(ready, why) from the STORES only — no network.

    This is what a refusal and the setup checklist read, and it must never
    cost a round trip: it is asked on the beat and rendered on a page. The
    live question is `verify()`.
    """
    if not config().get("user_id"):
        return False, SETUP
    try:
        from aletheia import secret_store
        if not secret_store.exists(TOKEN_ALIAS):
            return False, SETUP
    except Exception as exc:  # noqa: BLE001
        return False, f"the vault could not be read ({type(exc).__name__})"
    who = config().get("username")
    return True, f"set up for Instagram{' as @' + who if who else ''}"


def verify(*, transport=None) -> tuple[bool, str]:
    """The REAL question: is she connected to his account right now?

    One read-only call. Configured is not connected — a vault entry and a
    saved number prove that somebody typed something, not that Instagram
    will take a post. Reading is not publishing, so this is safe to ask on
    a button.
    """
    ok, why = available()
    if not ok:
        return False, why
    try:
        token = _token()
    except Exception as exc:  # noqa: BLE001
        return False, f"the token is not readable from the vault ({type(exc).__name__})"
    user = str(config()["user_id"])
    driver = _transport(transport, timeout=ASK_TIMEOUT_S)
    try:
        who = driver.get(f"{base_for(token)}/{user}",
                         {"fields": "username,account_type", "access_token": token})
    except RuntimeError as exc:
        return False, str(exc)
    name = str((who or {}).get("username") or "")
    kind = str((who or {}).get("account_type") or "")
    if not name:
        return False, "Instagram answered but did not say which account this is"
    if name != str(config().get("username") or name):
        _save(username=name)
    said = f"connected to Instagram as @{name}"
    if kind:
        said += f" ({kind.lower().replace('_', ' ')})"
    expires = config().get("token_expires_at")
    if expires:
        left = _days_until(expires)
        if left is not None:
            said += f"; the token has {left} day{'' if left == 1 else 's'} left"
            if config().get("token_expires_estimated"):
                said += " by Meta's usual 60"
    return True, said


def _days_until(stamp: str) -> int | None:
    when = _parse(stamp)
    if when is None:
        return None
    return max(0, int((when - _now()).total_seconds() // 86400))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse(stamp: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- connect


def discover(token: str, *, transport=None) -> dict:
    """The Instagram user id FROM THE TOKEN, so he never has to find it.

    Instagram route: `GET /me?fields=user_id,username`. Facebook route: the
    id hangs off a Page, so walk `/me/accounts` and take the one Instagram
    account there; two of them is a question for him, not a guess.
    """
    driver = _transport(transport, timeout=ASK_TIMEOUT_S)
    base = base_for(token)
    if route_of(token) == ROUTE_IG:
        me = driver.get(f"{base}/me", {"fields": "user_id,username", "access_token": token})
        user = str((me or {}).get("user_id") or (me or {}).get("id") or "")
        if not user:
            raise RuntimeError("the token did not say which Instagram account it is for")
        return {"user_id": user, "username": str((me or {}).get("username") or "")}
    pages = driver.get(f"{base}/me/accounts",
                       {"fields": "name,instagram_business_account{id,username}",
                        "access_token": token})
    found = []
    for page in (pages or {}).get("data") or []:
        linked = (page or {}).get("instagram_business_account") or {}
        if linked.get("id"):
            found.append({"user_id": str(linked["id"]),
                          "username": str(linked.get("username") or ""),
                          "page": str(page.get("name") or "")})
    if not found:
        raise RuntimeError("that Facebook token reaches no Page with an Instagram account linked "
                           "to it — link the professional account to a Page, or use an Instagram "
                           "login token (it starts IGAA) instead")
    if len(found) > 1:
        names = ", ".join(f"@{f['username'] or f['page']}" for f in found)
        raise RuntimeError(f"that token reaches more than one Instagram account ({names}) — "
                           "say which one with --user-id")
    return found[0]


def paste_help(token: str, exc: Exception) -> str:
    """What Meta said, plus the thing he can actually do about it.

    Measured against the live host 2026-09-25 with a deliberately bad token:
    the bare answer is "Instagram said no (400): Failed to decode", which is
    honest and useless at the one moment he is standing there pasting. A
    partial paste is by far the likeliest cause - the token is long, it is
    shown once, and the box it comes from is easy to clip.
    """
    text = str(token or "")
    said = [f"Instagram would not accept that token: {exc}"]
    if not (text.startswith("IGAA") or text.startswith("EAA")):
        said.append("It also does not begin with IGAA or EAA, which every Meta token does, "
                    "so it looks like a partial paste or the wrong value copied.")
    said.append("Press Generate token again and paste the whole thing. Nothing was stored, "
                "so running this again is safe.")
    return " ".join(said)


def connect(token: str = "", *, user_id: str = "", api: str = "", transport=None) -> dict:
    """ONE command's worth of setup: take the token, work out the route,
    discover the account, store the token by name, prove it live.

    The token is read with `getpass` when it is not passed, so it is never
    echoed and never in his shell history. It goes straight into the DPAPI
    vault; this function returns the CONFIG, which holds no secret.
    """
    from aletheia import secret_store
    token = str(token or "").strip()
    if not token:
        token = getpass.getpass("Paste the Instagram access token (not echoed): ").strip()
    if not token:
        raise RuntimeError("no token was pasted, so nothing was changed")
    ok, why = secret_store.available()
    if not ok:
        raise RuntimeError(f"the vault cannot hold the token: {why}")
    route = route_of(token)
    if api:
        _save(api_version=api)
    if str(user_id).strip():
        who = {"user_id": str(user_id).strip(), "username": ""}
    else:
        try:
            who = discover(token, transport=transport)
        except RuntimeError as exc:
            # Nothing has been written yet — the vault put and the config
            # save are both below this — so "nothing was stored" is a fact.
            raise RuntimeError(paste_help(token, exc)) from None
    if not str(who["user_id"]).isdigit():
        raise RuntimeError("the Instagram user id came back as something that is not a number")
    secret_store.put(TOKEN_ALIAS, token, provider="instagram", kind="api_token")
    now = stateio.utcnow()
    _save(user_id=str(who["user_id"]),
          username=str(who.get("username") or "").lstrip("@"),
          route=route,
          api_version=api_version(),
          token_set_at=now,
          token_expires_at=(_now() + dt.timedelta(days=TOKEN_LIFETIME_DAYS)
                            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
          token_expires_estimated=True,
          connected_at=now)
    journal.append("event", "instagram",
                   f"connected to Instagram user id {who['user_id']}"
                   + (f" (@{who['username']})" if who.get("username") else "")
                   + f" over the {route} login route; the token is in the vault as {TOKEN_ALIAS}",
                   actor=ACTOR)
    live, said = verify(transport=transport)
    if not live:
        raise RuntimeError(f"the token was stored, but Instagram did not confirm it: {said}")
    journal.append("event", "instagram", f"verified live: {said}", actor=ACTOR)
    return config()


def configure(user_id: str, *, username: str = "") -> dict:
    """Saved the id by hand. Kept because it is the escape hatch when
    discovery cannot see the account (two Pages, an odd token); `connect`
    is the door."""
    user_id = str(user_id or "").strip()
    if not user_id.isdigit():
        raise ValueError("the Instagram user id is a number (the professional account's IG User ID)")
    value = _save(user_id=user_id, username=str(username or "").strip().lstrip("@"),
                  configured_at=stateio.utcnow())
    journal.append("event", "instagram", f"configured for user id {user_id}"
                   + (f" (@{value['username']})" if value.get("username") else ""), actor=ACTOR)
    return value


# --------------------------------------------------------------- refresh


def refresh_token(*, transport=None) -> dict:
    """Trade the current token for a fresh 60 days.

    `GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`
    — unversioned, and Instagram-route only: a Facebook Page token does not
    refresh this way, and pretending it does would hand him a broken
    Instagram in two months. The new token goes into the vault under the
    same name; the journal gets the fact and never the value.
    """
    token = _token()
    if route_of(token) != ROUTE_IG:
        raise RuntimeError("a Facebook login token does not refresh this way; "
                           "the Instagram login route (a token starting IGAA) does")
    age = _parse(str(config().get("token_set_at") or ""))
    if age is not None and (_now() - age).total_seconds() < REFRESH_NOT_BEFORE_HOURS * 3600:
        raise RuntimeError("Instagram refuses to refresh a token less than 24 hours old")
    out = _transport(transport, timeout=ASK_TIMEOUT_S).get(f"{IG_HOST}/refresh_access_token",
                                   {"grant_type": "ig_refresh_token", "access_token": token})
    fresh = str((out or {}).get("access_token") or "")
    if not fresh:
        raise RuntimeError("Instagram did not give back a refreshed token")
    seconds = int((out or {}).get("expires_in") or TOKEN_LIFETIME_DAYS * 86400)
    from aletheia import secret_store
    secret_store.put(TOKEN_ALIAS, fresh, provider="instagram", kind="api_token")
    now = stateio.utcnow()
    value = _save(token_set_at=now, last_refresh=now,
                  token_expires_at=(_now() + dt.timedelta(seconds=seconds)
                                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  token_expires_estimated=False)
    days = max(0, seconds // 86400)
    journal.append("event", "instagram",
                   f"refreshed the Instagram access token; it now lasts {days} more days",
                   actor=ACTOR)
    return value


def refresh_due(*, now: dt.datetime | None = None) -> bool:
    """Is the token close enough to expiry to be worth a call?"""
    now = now or _now()
    if not available()[0]:
        return False
    if str(config().get("route") or ROUTE_IG) != ROUTE_IG:
        return False
    set_at = _parse(str(config().get("token_set_at") or ""))
    if set_at is not None and (now - set_at).total_seconds() < REFRESH_NOT_BEFORE_HOURS * 3600:
        return False
    expires = _parse(str(config().get("token_expires_at") or ""))
    if expires is None:
        return True  # unknown expiry is a reason to find out, not to wait
    return (expires - now).total_seconds() <= REFRESH_WHEN_UNDER_DAYS * 86400


def refresh_if_due(*, now: dt.datetime | None = None, transport=None) -> dict | None:
    """Core-tick hook: an honest no-op unless a refresh is both due and not
    already attempted within REFRESH_CHECK_EVERY_S. Never raises into the
    beat — a failure is journaled once and retried on the next window, so a
    weekend offline is two lines rather than two thousand."""
    now = now or _now()
    if not refresh_due(now=now):
        return None
    last = _parse(str(config().get("last_refresh_attempt") or ""))
    if last is not None and (now - last).total_seconds() < REFRESH_CHECK_EVERY_S:
        return None
    _save(last_refresh_attempt=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        return refresh_token(transport=transport)
    except Exception as exc:  # noqa: BLE001
        journal.append("alert", "instagram",
                       f"could not refresh the Instagram token ({_scrub(exc)}) — "
                       "it will be tried again, and posting stops when it expires",
                       actor=ACTOR)
        return None


# --------------------------------------------------------------- caption


def normalize_caption(text: str) -> str:
    """Keep the shape he wrote: line breaks and hashtags survive.

    The old version ran `" ".join(text.split())`, which turned a caption
    with three lines and a block of hashtags into one paragraph — Instagram
    renders exactly what it is given, so that collapse was visible in the
    post. Runs of spaces inside a line still collapse (a caption is not
    ASCII art), trailing space goes, and three or more blank lines become
    two, because Instagram eats the rest anyway.
    """
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in raw.split("\n")]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# --------------------------------------------------------------- staging


class NoStager:
    """Staging turned off. A local path is refused in words."""

    reason = ("Instagram only publishes media it can fetch from a public https address — Meta has "
              "no upload for pictures at all — and I am not set up to put a file anywhere public. "
              "Give me an https address, or turn staging back on.")

    def stage(self, path: Path, kind: str):
        raise RuntimeError(self.reason)


class GithubStager:
    """Serve one local file from a branch of his own public repository.

    Why this and not the alternatives, plainly: Meta fetches media from a
    public `https` URL and has no image upload at all, so a file on this PC
    has to be readable from the internet for the seconds the fetch takes.
    A tunnel out of this machine is not something a session may open. A
    third-party host is not mine to choose. His GitHub account is already
    his, already public, and its token is already in the vault for other
    work — so the file goes to a `thea-media` branch under a name that is
    its own content hash, is read back over `raw.githubusercontent.com`
    (no redirect, correct content type, which the stager CHECKS rather than
    assumes), and is deleted along with the branch as soon as the post
    lands. It is not a secrecy mechanism and does not pretend to be: it is
    for media he is in the act of publishing publicly.
    """

    API = "https://api.github.com"
    RAW = "https://raw.githubusercontent.com"

    def __init__(self, repo: str = "", *, token: str = "", branch: str = STAGE_BRANCH):
        self.repo = repo or self._repo()
        self.branch = branch
        self._token = token

    @staticmethod
    def _repo() -> str:
        """Which repository holds the staging branch, asked of the REGISTRY.

        `config/fleet.json` already says who owns this fleet and what the hub
        repository is called; a literal owner/name in code here would be a
        second place to edit and a first place to be wrong (§ the five
        registries are the only sources of truth).
        """
        saved = str(config().get("staging_repo") or "").strip()
        if saved:
            return saved
        env = str(os.environ.get("ALETHEIA_GITHUB_REPO") or "").strip()
        if env:
            return env
        from aletheia import fleet
        registry = fleet.load_fleet()
        owner = str(registry.get("owner") or "").strip()
        name = str(((registry.get("repos") or {}).get("aletheia") or {}).get("github") or "").strip()
        if not owner or not name:
            raise RuntimeError("config/fleet.json does not say which repository this is, "
                               "so there is nowhere to serve the file from")
        return f"{owner}/{name}"

    def token(self) -> str:
        if self._token:
            return self._token
        from aletheia import secret_store
        self._token = secret_store.get(GITHUB_TOKEN_ALIAS)
        return self._token

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        url = path if path.startswith("http") else f"{self.API}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token()}")
        req.add_header("Accept", "application/vnd.github+json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                text = r.read().decode("utf-8")
                return json.loads(text) if text.strip() else {}
        except urllib.error.HTTPError as exc:
            said = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"GitHub said no ({exc.code}) staging the file: {said}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub could not be reached to stage the file ({exc.reason})") from None

    # What raw.githubusercontent actually serves, MEASURED 2026-09-25 rather
    # than assumed: a .png comes back `image/png` and a .mp4 comes back
    # `application/octet-stream`, because that host types files by extension
    # and has no video mapping. So a picture is held to image/*, where the
    # host is known to be right, and a video is allowed octet-stream, where
    # Meta reads the container itself. What is never allowed is text/html,
    # which is what a 404 page, a login wall or a rate limit looks like -
    # handing that to Instagram is a post that fails with nothing said.
    OK_FOR = {IMAGE: ("image/",), REELS: ("video/", "application/octet-stream")}

    def content_type(self, url: str, *, tries: int = 4, sleep=time.sleep) -> str:
        """The real attempt, with a HEAD so a 90 MB video is not downloaded
        to learn its type. Retried, because a file committed a moment ago
        takes a beat to appear on the raw host, and a 404 read as a bad file
        would be a lie about his media."""
        last = ""
        for attempt in range(max(1, tries)):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"),
                                            timeout=60) as r:
                    return str(r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                last = str(exc)
                if attempt + 1 < max(1, tries):
                    sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"the staged file could not be read back ({last}) — nothing was posted")

    def stage(self, path: Path, kind: str):
        raw = path.read_bytes()
        if len(raw) > STAGE_MAX_BYTES:
            raise RuntimeError(f"that file is {len(raw) // (1024 * 1024)} MB and this way of serving "
                               f"it caps at {STAGE_MAX_BYTES // (1024 * 1024)} MB — put it at a "
                               "public https address and give me that instead")
        name = hashlib.sha256(raw).hexdigest()[:24] + path.suffix.lower()
        where = f"{STAGE_DIR}/{name}"
        mine = self._ensure_branch()
        body = {"message": f"thea: stage {name} for one Instagram post",
                "content": base64.b64encode(raw).decode("ascii"),
                "branch": self.branch}
        # The name IS the content hash, so posting the same file twice finds
        # its own earlier copy still there; the Contents API needs that blob's
        # sha to replace it rather than answering 422.
        already = self._sha_of(where)
        if already:
            body["sha"] = already
        made = self._call("PUT", f"/repos/{self.repo}/contents/{where}", body)
        sha = str(((made or {}).get("content") or {}).get("sha") or already or "")
        url = f"{self.RAW}/{self.repo}/{self.branch}/{where}"
        served = self.content_type(url)
        if not served.startswith(self.OK_FOR[kind]):
            self._remove(where, sha, drop_branch=mine)
            raise RuntimeError(f"that file would be served to Instagram as "
                               f"{served or 'nothing'}, which it will not take — nothing was posted")

        def teardown() -> None:
            self._remove(where, sha, drop_branch=mine)

        return url, teardown

    def _sha_of(self, where: str) -> str:
        try:
            got = self._call("GET", f"/repos/{self.repo}/contents/{where}?ref={self.branch}")
        except RuntimeError:
            return ""
        return str((got or {}).get("sha") or "") if isinstance(got, dict) else ""

    def _ensure_branch(self) -> bool:
        """True when THIS call created the branch, which is the only case in
        which tearing down may delete it: a branch that was already there may
        hold a file another post is still using."""
        try:
            self._call("GET", f"/repos/{self.repo}/git/ref/heads/{self.branch}")
            return False
        except RuntimeError:
            pass
        head = self._call("GET", f"/repos/{self.repo}/commits?per_page=1")
        sha = str((head or [{}])[0].get("sha") or "") if isinstance(head, list) else ""
        if not sha:
            raise RuntimeError("could not find a commit to branch the staging area from")
        self._call("POST", f"/repos/{self.repo}/git/refs",
                   {"ref": f"refs/heads/{self.branch}", "sha": sha})
        return True

    def _remove(self, where: str, sha: str, *, drop_branch: bool = True) -> None:
        """Best effort, and loud in the journal when it fails: a staged file
        left behind is his media sitting in a public place.

        Removing it from GitHub is not the same as it being unfetchable.
        Measured 2026-09-25: after this ran, the API answered 404 for both the
        file and the branch while the raw CDN still served the blob for
        minutes. Nothing here can flush that cache, so nothing here claims to.
        """
        try:
            if sha:
                self._call("DELETE", f"/repos/{self.repo}/contents/{where}",
                           {"message": f"thea: the post landed; unstage {where}",
                            "sha": sha, "branch": self.branch})
            if drop_branch:
                self._call("DELETE", f"/repos/{self.repo}/git/refs/heads/{self.branch}")
        except Exception as exc:  # noqa: BLE001
            journal.append("alert", "instagram",
                           f"could not remove the staged file {where} from {self.repo} "
                           f"({type(exc).__name__}) — it is still public",
                           actor=ACTOR)


def stager(given=None):
    if given is not None:
        return given
    if str(config().get("staging") or "github").lower() in ("", "off", "none", "no"):
        return NoStager()
    return GithubStager()


# --------------------------------------------------------------- publish


def media_kind(media: str, *, media_type: str = "") -> str:
    """IMAGE or REELS, from what he said or from the file's own name."""
    asked = str(media_type or "").strip().upper()
    if asked in (IMAGE, REELS):
        return asked
    if asked in ("VIDEO", "REEL"):
        return REELS
    suffix = Path(urllib.parse.urlparse(str(media)).path or str(media)).suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return REELS
    return IMAGE


def _as_jpeg(path: Path) -> tuple[Path, str]:
    """Instagram publishes JPEG images and nothing else through the API.

    His screenshots are PNG, so refusing outright would make the whole
    feature useless for the files he actually has. HIS file is never
    touched: a JPEG copy goes to a temp directory and the ledger says what
    it was converted from.
    """
    if path.suffix.lower() in JPEG_SUFFIXES:
        return path, ""
    if path.suffix.lower() not in CONVERTIBLE_SUFFIXES:
        raise RuntimeError(f"Instagram takes JPEG pictures and MP4 video; {path.suffix or 'that file'} "
                           "is neither")
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError(f"Instagram only publishes JPEG pictures and that is a {path.suffix} — "
                           "converting it needs Pillow, which is not installed here") from None
    out = Path(tempfile.mkdtemp(prefix="thea-ig-")) / (path.stem + ".jpg")
    with Image.open(path) as im:
        im.convert("RGB").save(out, "JPEG", quality=92)
    return out, path.suffix.lower().lstrip(".")


def _await_container(container: str, kind: str, token: str, driver, *,
                     sleep=time.sleep, now=time.monotonic) -> None:
    """Poll the container until Instagram says FINISHED.

    A Reel is transcoded before it can be published, so publishing straight
    away fails with a message about the media not being available. About
    once a minute, for at most five (one for a picture), and EXPIRED or
    ERROR is said as itself rather than waited out.

    Only IN_PROGRESS waits. Anything unrecognised is refused, and a reply
    with NO `status_code` at all goes straight on to publish: this runs on
    the ordinary picture path too, and a field Meta chooses not to send back
    must not become a minute of waiting and then a failure on the one thing
    that was working. `media_publish` is still the real gate — it says no,
    in Instagram's own words, when the container genuinely is not ready.
    """
    budget = CONTAINER_BUDGET_S.get(kind, 300.0)
    thing = "video" if kind == REELS else "picture"
    started = now()
    while True:
        state = driver.get(f"{base_for(token)}/{container}",
                           {"fields": "status_code,status", "access_token": token})
        code = str((state or {}).get("status_code") or "").upper()
        if not code or code in (CONTAINER_READY, "PUBLISHED"):
            return
        if code != CONTAINER_WORKING:
            detail = str((state or {}).get("status") or code)
            raise RuntimeError(f"Instagram could not prepare the {thing} "
                               f"({code}): {_scrub(detail)}")
        if now() - started >= budget:
            raise RuntimeError(f"Instagram was still processing the {thing} after "
                               f"{int(budget // 60)} minute(s); nothing was published")
        sleep(min(CONTAINER_POLL_S, max(1.0, budget - (now() - started))))


def publish(media: str, caption: str = "", *, media_type: str = "", transport=None,
            stage=None, sleep=time.sleep) -> dict:
    """Publish ONE picture or Reel with a caption, and record it.

    `media` is either a public https address or a path on this PC; a local
    file is staged, published and unstaged. Raises RuntimeError with a
    sentence a person can act on when anything refuses; the token never
    appears in that sentence, the ledger or the journal.
    """
    ready, why = available()
    if not ready:
        raise RuntimeError(why)
    media = str(media or "").strip().strip('"')
    if not media:
        raise RuntimeError("there is nothing to post — name a picture, a video or an https address")
    kind = media_kind(media, media_type=media_type)
    text = normalize_caption(caption)
    if len(text) > MAX_CAPTION:
        raise RuntimeError(f"the caption is {len(text)} characters and Instagram's limit is {MAX_CAPTION}")

    token = _token()
    driver = _transport(transport)
    user = str(config()["user_id"])
    teardown = None
    local = ""
    converted = ""
    if media.lower().startswith("https://"):
        url = media
    elif media.lower().startswith("http://"):
        raise RuntimeError("Instagram will only fetch media over https, and that address is http")
    else:
        path = Path(media).expanduser()
        if not path.is_file():
            raise RuntimeError(f"there is no file at {path}")
        local = str(path)
        if kind == IMAGE:
            path, converted = _as_jpeg(path)
        url, teardown = stager(stage).stage(path, kind)

    try:
        fields = {"caption": text, "access_token": token}
        if kind == REELS:
            fields.update({"media_type": REELS, "video_url": url})
        else:
            fields["image_url"] = url
        made = driver.post(f"{base_for(token)}/{user}/media", fields)
        container = str((made or {}).get("id") or "")
        if not container:
            raise RuntimeError("Instagram did not give back a media container")
        _await_container(container, kind, token, driver, sleep=sleep)
        out = driver.post(f"{base_for(token)}/{user}/media_publish",
                          {"creation_id": container, "access_token": token})
        media_id = str((out or {}).get("id") or "")
        if not media_id:
            raise RuntimeError("Instagram accepted the media but did not publish it")
    finally:
        if teardown is not None:
            teardown()

    row = {"id": media_id, "at": stateio.utcnow(), "kind": kind, "caption": text,
           "user_id": user, "username": str(config().get("username") or "")}
    if local:
        row["file"] = local
        if converted:
            row["converted_from"] = converted
    else:
        row["media_url"] = url
    _dir().mkdir(parents=True, exist_ok=True)
    with _ledger_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    what = "a reel" if kind == REELS else "a picture"
    first = text.split("\n", 1)[0][:80]
    journal.append("action", "instagram",
                   f"posted {what} to Instagram: {first!r}" if first else
                   f"posted {what} to Instagram", actor=ACTOR)
    return row


# ---------------------------------------------------------------- ledger


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
    said = []
    for r in rows[:4]:
        first = str(r.get("caption") or "").split("\n", 1)[0][:60]
        what = first or ("a reel" if r.get("kind") == REELS else "a picture")
        said.append(f"{what!r} ({speech.humanize_time(str(r.get('at') or ''))})"
                    if first else f"{what} ({speech.humanize_time(str(r.get('at') or ''))})")
    return (f"{speech.count_phrase(len(rows), 'post')} to Instagram: " + "; ".join(said)
            + (f"; and {len(rows) - 4} more" if len(rows) > 4 else "") + ".")


# ------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Post to his Instagram. `connect` is the whole setup.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="ask Instagram, live, whether she is connected")
    con = sub.add_parser("connect", help="paste the token once; everything else is worked out")
    con.add_argument("--user-id", default="", help="only if discovery cannot see the account")
    con.add_argument("--api-version", default="", help="e.g. v25.0")
    conf = sub.add_parser("configure", help="save the user id by hand")
    conf.add_argument("user_id")
    conf.add_argument("--username", default="")
    post = sub.add_parser("post", help="one picture or reel; a file on this PC is fine")
    post.add_argument("media")
    post.add_argument("--caption", default="")
    post.add_argument("--media-type", default="", choices=["", "IMAGE", "REELS"])
    sub.add_parser("posts", help="what has gone out")
    sub.add_parser("refresh", help="trade the token for a fresh 60 days")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "status":
            ok, why = verify()
            print(("READY: " if ok else "NOT READY: ") + why)
            return 0 if ok else 1
        if args.cmd == "connect":
            connect(user_id=args.user_id, api=args.api_version)
            ok, why = verify()
            print(("READY: " if ok else "NOT READY: ") + why)
            if ok:
                # The last line he reads should say he is DONE and what happens
                # next, not leave him wondering whether to do something else.
                print("Nothing else here is yours. Ask me for the first post and "
                      "I'll bring you the picture and the caption to approve.")
            return 0 if ok else 1
        if args.cmd == "configure":
            print(json.dumps(configure(args.user_id, username=args.username), indent=2))
        elif args.cmd == "post":
            row = publish(args.media, args.caption, media_type=args.media_type)
            print(f"posted: media id {row['id']}")
        elif args.cmd == "posts":
            print(spoken_posts())
        elif args.cmd == "refresh":
            value = refresh_token()
            print(f"refreshed; the token now runs to {value.get('token_expires_at')}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(_scrub(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
