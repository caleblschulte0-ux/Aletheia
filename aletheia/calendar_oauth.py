"""Small OAuth/HTTP boundary for official calendar providers.

This module deliberately does not implement an interactive login flow. The
operator obtains an OAuth client + refresh token through the provider's normal
consent UI and stores those values in ~/.aletheia/calendar-live.json. Access
tokens are refreshed on demand and cached only in gitignored private state.

Security rules:
- bearer/refresh/client secrets are never included in exception text or logs;
- response bodies are bounded before decoding;
- redirects are handled by urllib's normal HTTPS stack, but provider adapters
  must only supply allow-listed HTTPS URLs;
- one 401 may trigger one refresh+retry, never an unbounded auth loop.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

from aletheia.stateio import private_dir, read_json, write_json_atomic

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
TOKEN_SKEW_SECONDS = 60
TOKEN_DIR = private_dir("calendar") / "oauth"


class HttpError(RuntimeError):
    """Sanitized HTTP failure. Never carries a response body or auth header."""

    def __init__(self, status: int, operation: str):
        super().__init__(f"calendar provider HTTP {status} during {operation}")
        self.status = status
        self.operation = operation


class Transport(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                json_body: dict | None = None, form: dict[str, str] | None = None,
                expected: set[int] | None = None, operation: str = "request") -> tuple[int, dict, dict | None]: ...


def _read_bounded(response) -> bytes:
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("calendar provider response exceeds size cap")
    return data


class UrlLibTransport:
    """stdlib HTTPS JSON transport with sanitized failures."""

    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                json_body: dict | None = None, form: dict[str, str] | None = None,
                expected: set[int] | None = None, operation: str = "request") -> tuple[int, dict, dict | None]:
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError("calendar provider URL must be HTTPS")
        if json_body is not None and form is not None:
            raise ValueError("request may contain JSON or form data, not both")
        body = None
        request_headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif form is not None:
            body = urllib.parse.urlencode(form).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        req = urllib.request.Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                status = int(response.status)
                raw = _read_bounded(response)
                response_headers = {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as exc:
            # Consume at most the cap so a connection can be reused, but never
            # surface the provider body: OAuth/API errors can contain PII.
            try:
                exc.read(MAX_RESPONSE_BYTES + 1)
            except Exception:
                pass
            status = int(exc.code)
            if expected and status in expected:
                return status, {}, None
            raise HttpError(status, operation) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"calendar provider transport failed during {operation}: {type(exc.reason).__name__}") from None
        if expected is not None and status not in expected:
            raise HttpError(status, operation)
        if not raw:
            return status, response_headers, None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError(f"calendar provider returned invalid JSON during {operation}") from None
        if not isinstance(payload, dict):
            raise ValueError(f"calendar provider returned non-object JSON during {operation}")
        return status, response_headers, payload


def _safe_cache_id(provider_id: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in provider_id.lower())
    return clean[:80] or "calendar"


class OAuthSession:
    """Refresh-token backed bearer session with an injected transport seam."""

    def __init__(self, provider_id: str, *, token_url: str, refresh_form: dict[str, str],
                 transport: Transport | None = None, cache_path: Path | None = None):
        if not token_url.startswith("https://"):
            raise ValueError("OAuth token URL must be HTTPS")
        required = {"client_id", "refresh_token"}
        if not required <= refresh_form.keys() or any(not str(refresh_form[k]).strip() for k in required):
            raise ValueError("OAuth refresh config requires client_id and refresh_token")
        self.provider_id = provider_id
        self.token_url = token_url
        self.refresh_form = {str(k): str(v) for k, v in refresh_form.items() if v is not None}
        self.transport = transport or UrlLibTransport()
        self.cache_path = cache_path or (TOKEN_DIR / f"{_safe_cache_id(provider_id)}.json")

    def _cached(self) -> dict | None:
        if not self.cache_path.exists():
            return None
        try:
            value = read_json(self.cache_path)
        except ValueError:
            return None
        token = value.get("access_token")
        expires_at = value.get("expires_at")
        if not isinstance(token, str) or not token or not isinstance(expires_at, (int, float)):
            return None
        if float(expires_at) - TOKEN_SKEW_SECONDS <= time.time():
            return None
        return value

    def refresh(self) -> str:
        form = dict(self.refresh_form)
        form["grant_type"] = "refresh_token"
        _, _, payload = self.transport.request(
            "POST", self.token_url, form=form, expected={200}, operation="OAuth token refresh")
        payload = payload or {}
        token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3600)
        if not isinstance(token, str) or not token:
            raise RuntimeError("calendar OAuth refresh returned no access token")
        try:
            lifetime = max(60, min(int(expires_in), 24 * 60 * 60))
        except (TypeError, ValueError):
            raise RuntimeError("calendar OAuth refresh returned invalid expiry") from None
        write_json_atomic(self.cache_path, {
            "version": 1, "access_token": token, "expires_at": time.time() + lifetime})
        return token

    def access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = self._cached()
            if cached:
                return cached["access_token"]
        return self.refresh()

    def api_request(self, method: str, url: str, *, json_body: dict | None = None,
                    headers: dict[str, str] | None = None, expected: set[int] | None = None,
                    operation: str = "API request") -> tuple[int, dict, dict | None]:
        expected = expected or {200}
        base_headers = dict(headers or {})
        for attempt in range(2):
            token = self.access_token(force_refresh=attempt == 1)
            auth_headers = {**base_headers, "Authorization": f"Bearer {token}"}
            try:
                return self.transport.request(method, url, headers=auth_headers,
                                              json_body=json_body, expected=expected,
                                              operation=operation)
            except HttpError as exc:
                if exc.status == 401 and attempt == 0:
                    continue
                raise
        raise RuntimeError("calendar OAuth authentication failed")
