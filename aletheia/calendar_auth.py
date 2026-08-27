"""One-time official OAuth consent bootstrap for live calendar providers.

This is a local desktop authorization flow, not a credential bypass. It opens the
provider's normal system-browser consent page, listens on 127.0.0.1 for exactly
one callback, validates a high-entropy state value, uses PKCE-S256, exchanges the
single-use code at the provider's documented HTTPS token endpoint, and writes
only the resulting refresh-token configuration to ~/.aletheia/calendar-live.json.

No authorization code, access token, refresh token or client secret is printed,
journaled, committed, or returned in the success summary. Existing config is
never overwritten unless the operator explicitly passes --replace.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Callable

from aletheia import calendar_live
from aletheia.calendar_google import TOKEN_URL as GOOGLE_TOKEN_URL
from aletheia.calendar_oauth import Transport, UrlLibTransport
from aletheia.stateio import write_json_atomic

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_READ_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
GOOGLE_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events"
MICROSOFT_READ_SCOPE = "Calendars.Read"
MICROSOFT_WRITE_SCOPE = "Calendars.ReadWrite"
CALLBACK_PATH = "/oauth/callback"
CALLBACK_TIMEOUT_S = 180


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_pkce() -> tuple[str, str]:
    """Return RFC 7636 verifier + S256 challenge."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    if not 43 <= len(verifier) <= 128:
        raise RuntimeError("PKCE verifier generation failed")
    return verifier, challenge


def new_state() -> str:
    return secrets.token_urlsafe(32)


def _tenant(value: str) -> str:
    # Reuse the exact live-config validator for path safety.
    clean = calendar_live.validate_config({
        "provider": "microsoft", "oauth": {
            "client_id": "placeholder", "refresh_token": "placeholder",
            "tenant": value, "scope": "offline_access Calendars.Read"}})
    return clean["oauth"]["tenant"]


def build_authorization_url(provider: str, *, client_id: str, redirect_uri: str,
                            state: str, challenge: str, enable_writes: bool = False,
                            tenant: str = "common") -> tuple[str, str]:
    if not all(isinstance(x, str) and x for x in (client_id, redirect_uri, state, challenge)):
        raise ValueError("OAuth authorization URL requires client_id, redirect_uri, state and challenge")
    common = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider == "google":
        scope = GOOGLE_WRITE_SCOPE if enable_writes else GOOGLE_READ_SCOPE
        query = {**common, "scope": scope, "access_type": "offline", "prompt": "consent"}
        return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(query), scope
    if provider == "microsoft":
        tenant = _tenant(tenant)
        scope = "offline_access " + (MICROSOFT_WRITE_SCOPE if enable_writes else MICROSOFT_READ_SCOPE)
        query = {**common, "scope": scope, "response_mode": "query"}
        return (f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?"
                + urllib.parse.urlencode(query)), scope
    raise ValueError("OAuth provider must be google or microsoft")


def exchange_code(provider: str, *, client_id: str, code: str, verifier: str,
                  redirect_uri: str, scope: str, tenant: str = "common",
                  client_secret: str | None = None,
                  transport: Transport | None = None) -> str:
    """Exchange a single-use authorization code and return only refresh_token."""
    for name, value in (("client_id", client_id), ("code", code),
                        ("verifier", verifier), ("redirect_uri", redirect_uri)):
        if not isinstance(value, str) or not value:
            raise ValueError(f"OAuth code exchange requires {name}")
    form = {
        "client_id": client_id, "code": code, "code_verifier": verifier,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }
    transport = transport or UrlLibTransport()
    if provider == "google":
        token_url = GOOGLE_TOKEN_URL
        if client_secret:
            form["client_secret"] = client_secret
    elif provider == "microsoft":
        tenant = _tenant(tenant)
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        form["scope"] = scope
        # Public desktop clients should not have a secret. Keep optional support
        # for a deliberately configured confidential registration, but never
        # require one for the native flow.
        if client_secret:
            form["client_secret"] = client_secret
    else:
        raise ValueError("OAuth provider must be google or microsoft")
    _, _, payload = transport.request(
        "POST", token_url, form=form, expected={200}, operation="calendar OAuth code exchange")
    refresh = (payload or {}).get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise RuntimeError("calendar authorization returned no refresh token; configuration was not written")
    return refresh


class _CallbackResult:
    def __init__(self):
        self.params: dict[str, str] | None = None
        self.event = threading.Event()


class _CallbackServer(http.server.HTTPServer):
    allow_reuse_address = False


def _handler(expected_state: str, result: _CallbackResult):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A003
            return  # query strings can contain codes; never log a request line

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            error = query.get("error", [""])[0]
            valid = parsed.path == CALLBACK_PATH and secrets.compare_digest(state, expected_state)
            if valid and (code or error) and result.params is None:
                result.params = {"state": state, "code": code, "error": error}
                result.event.set()
                status = 200
                message = "Authorization received. You can close this tab and return to Aletheia."
            else:
                status = 400
                message = "This authorization callback is invalid. Return to Aletheia and try again."
            body = ("<!doctype html><meta charset='utf-8'><title>Aletheia</title>"
                    f"<p>{message}</p>").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler


def listen_once(expected_state: str, *, provider: str,
                timeout: int = CALLBACK_TIMEOUT_S,
                open_browser: Callable[[str], bool] | None = webbrowser.open,
                authorization_url_builder: Callable[[str], str] | None = None) -> tuple[str, str]:
    """Run one loopback listener and return (redirect_uri, authorization code).

    `authorization_url_builder` receives the final redirect URI. Injection keeps
    tests hermetic and ensures the server is already listening before the browser
    is opened.
    """
    if provider not in {"google", "microsoft"}:
        raise ValueError("OAuth provider must be google or microsoft")
    result = _CallbackResult()
    server = _CallbackServer(("127.0.0.1", 0), _handler(expected_state, result))
    server.timeout = 0.5
    port = server.server_address[1]
    host = "127.0.0.1" if provider == "google" else "localhost"
    redirect_uri = f"http://{host}:{port}{CALLBACK_PATH}"
    try:
        if authorization_url_builder is not None:
            auth_url = authorization_url_builder(redirect_uri)
            if open_browser is not None and not open_browser(auth_url):
                raise RuntimeError("system browser could not be opened for calendar authorization")
        deadline = threading.Event()
        # Use repeated handle_request calls rather than serve_forever so timeout
        # is bounded and shutdown never races a background server thread.
        import time
        end = time.monotonic() + max(1, min(int(timeout), 600))
        while time.monotonic() < end and not result.event.is_set():
            server.handle_request()
        if result.params is None:
            raise TimeoutError("calendar authorization timed out before a valid local callback")
        if result.params.get("error"):
            raise PermissionError("calendar authorization was denied or failed at the provider")
        code = result.params.get("code", "")
        if not code:
            raise RuntimeError("calendar authorization callback contained no code")
        return redirect_uri, code
    finally:
        server.server_close()


def write_config(provider: str, *, client_id: str, refresh_token: str,
                 enable_writes: bool = False, timezone: str | None = None,
                 calendar_id: str | None = None, tenant: str = "common",
                 scope: str | None = None, client_secret: str | None = None,
                 path: Path | None = None, replace: bool = False) -> dict:
    path = path or calendar_live.CONFIG_FILE
    if path.exists() and not replace:
        raise FileExistsError(f"live calendar config already exists at {path}; pass --replace explicitly")
    oauth = {"client_id": client_id, "refresh_token": refresh_token}
    if client_secret:
        oauth["client_secret"] = client_secret
    value: dict = {"provider": provider, "allow_writes": bool(enable_writes), "oauth": oauth}
    if calendar_id:
        value["calendar_id"] = calendar_id
    if provider == "google":
        if not timezone:
            raise ValueError("Google authorization requires --timezone")
        value["timezone"] = timezone
    elif provider == "microsoft":
        oauth["tenant"] = tenant
        oauth["scope"] = scope or ("offline_access " + (MICROSOFT_WRITE_SCOPE if enable_writes else MICROSOFT_READ_SCOPE))
    else:
        raise ValueError("OAuth provider must be google or microsoft")
    clean = calendar_live.validate_config(value)
    write_json_atomic(path, clean)
    # Deliberately return a secret-free summary, not the config object.
    return {"provider": clean["provider"], "allow_writes": clean["allow_writes"],
            "calendar_id": clean.get("calendar_id"), "path": str(path)}


def authorize(provider: str, *, client_id: str, enable_writes: bool = False,
              timezone: str | None = None, calendar_id: str | None = None,
              tenant: str = "common", client_secret: str | None = None,
              path: Path | None = None, replace: bool = False,
              transport: Transport | None = None,
              open_browser: Callable[[str], bool] | None = webbrowser.open) -> dict:
    # Refuse an overwrite BEFORE opening a browser or creating any token.
    target = path or calendar_live.CONFIG_FILE
    if target.exists() and not replace:
        raise FileExistsError(f"live calendar config already exists at {target}; pass --replace explicitly")
    verifier, challenge, state = *new_pkce(), new_state()
    selected_scope = ""

    def url_for(redirect_uri: str) -> str:
        nonlocal selected_scope
        url, selected_scope = build_authorization_url(
            provider, client_id=client_id, redirect_uri=redirect_uri,
            state=state, challenge=challenge, enable_writes=enable_writes,
            tenant=tenant)
        return url

    redirect_uri, code = listen_once(
        state, provider=provider, open_browser=open_browser,
        authorization_url_builder=url_for)
    refresh = exchange_code(
        provider, client_id=client_id, code=code, verifier=verifier,
        redirect_uri=redirect_uri, scope=selected_scope, tenant=tenant,
        client_secret=client_secret, transport=transport)
    return write_config(
        provider, client_id=client_id, refresh_token=refresh,
        enable_writes=enable_writes, timezone=timezone, calendar_id=calendar_id,
        tenant=tenant, scope=selected_scope, client_secret=client_secret,
        path=target, replace=replace)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Authorize Aletheia to an official calendar provider")
    sub = ap.add_subparsers(dest="provider", required=True)
    for name in ("google", "microsoft"):
        p = sub.add_parser(name)
        p.add_argument("--client-id", required=True)
        p.add_argument("--client-secret")
        p.add_argument("--calendar-id")
        p.add_argument("--enable-writes", action="store_true")
        p.add_argument("--replace", action="store_true")
        if name == "google":
            p.add_argument("--timezone", required=True)
        else:
            p.add_argument("--tenant", default="common")
    args = ap.parse_args(argv)
    result = authorize(
        args.provider, client_id=args.client_id,
        client_secret=args.client_secret,
        calendar_id=args.calendar_id,
        enable_writes=args.enable_writes, replace=args.replace,
        timezone=getattr(args, "timezone", None),
        tenant=getattr(args, "tenant", "common"))
    print(f"calendar authorization saved: {result['provider']} (writes {'enabled' if result['allow_writes'] else 'disabled'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
