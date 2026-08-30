"""Host-bound API credential operations whose plaintext never leaves the PC.

This module is intentionally NOT general browser automation. It has two jobs:

* create_capture(): click a live control that specifically means create/generate
  an API credential, then capture the generated value directly into the Windows
  DPAPI vault;
* fill_alias(): resolve an already-vaulted alias and fill it into a live
  API-key/token/credential field on an explicitly allowed host.

There is no read/show/copy-to-stdout operation. Passwords, login/2FA/recovery,
payment fields, revocation/deletion/rotation and account-security actions are
refused. The public intercom may carry URLs/selectors/aliases, never plaintext.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from aletheia import browse, journal, policy, secret_store, secret_trust, stateio

ACTOR = "aletheia-secret-browser"
MAX_SELECTOR = 500
MIN_CAPTURE_CHARS = 8
MAX_CAPTURE_CHARS = 4096
SAFE_SELECTOR = re.compile(r"^[\x20-\x7e]{1,500}$")
API_KINDS = frozenset({"api_key", "access_token", "client_secret", "credential"})

CREATE_VERBS = ("create", "generate", "new", "issue")
CREDENTIAL_NOUNS = (
    "api key", "apikey", "access key", "access token", "token", "credential",
    "client secret", "secret key", "secret",
)
FIELD_NOUNS = (
    "api key", "apikey", "access key", "access token", "token", "credential",
    "client secret", "secret key",
)
BLOCKED_TERMS = (
    "password", "passcode", "sign in", "signin", "log in", "login", "2fa", "mfa",
    "authenticator", "one-time", "one time", "otp", "verification code",
    "recovery code", "backup code", "security code", "pin", "cvv", "credit card",
    "debit card", "card number", "billing", "payment", "checkout", "purchase",
    "delete", "remove", "revoke", "rotate", "reset", "change password",
    "close account", "terminate", "account security",
)
SECRET_AUTOCOMPLETE = {
    "current-password", "new-password", "one-time-code", "cc-number", "cc-csc",
    "cc-exp", "cc-exp-month", "cc-exp-year",
}


class SecretBrowserRefused(PermissionError):
    pass


class SecretBrowserError(RuntimeError):
    pass


def _url_host(url: str) -> str:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError as exc:
        raise ValueError("url must be an absolute http(s) URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute http(s) URL")
    return parsed.hostname.casefold()


def _same_host(url: str, host: str) -> bool:
    try:
        reached = urlparse(str(url or ""))
    except ValueError:
        return False
    return bool(reached.hostname and reached.hostname.casefold() == host.casefold())


def _selector(value: str, name: str) -> str:
    if not isinstance(value, str) or not SAFE_SELECTOR.fullmatch(value):
        raise ValueError(f"{name} must be bounded printable selector text")
    return value


def _semantic(meta: dict) -> str:
    parts = [
        meta.get("text", ""), meta.get("aria", ""), meta.get("title", ""),
        meta.get("name", ""), meta.get("id", ""), meta.get("placeholder", ""),
        meta.get("label", ""), meta.get("nearby", ""),
    ]
    return " ".join(" ".join(str(x).split()) for x in parts).casefold()


def _element_meta(page, selector: str) -> dict:
    page.wait_for_selector(selector)
    meta = page.eval_on_selector(
        selector,
        """el => ({
          text: (el.innerText || '').slice(0, 300),
          aria: (el.getAttribute('aria-label') || '').slice(0, 200),
          title: (el.getAttribute('title') || '').slice(0, 200),
          name: (el.getAttribute('name') || '').slice(0, 160),
          id: (el.id || '').slice(0, 160),
          placeholder: (el.getAttribute('placeholder') || '').slice(0, 200),
          role: (el.getAttribute('role') || '').slice(0, 80),
          inputType: (el.getAttribute('type') || '').slice(0, 80),
          autocomplete: (el.getAttribute('autocomplete') || '').slice(0, 100),
          label: (el.labels && el.labels.length ? Array.from(el.labels).map(x => x.innerText || '').join(' ') : '').slice(0, 300),
          nearby: (el.parentElement ? (el.parentElement.innerText || '') : '').slice(0, 500)
        })""",
    ) or {}
    if not isinstance(meta, dict):
        raise SecretBrowserRefused("live browser element could not be described safely")
    return meta


def _blocked(meta: dict) -> str | None:
    semantic = _semantic(meta)
    return next((term for term in BLOCKED_TERMS if term in semantic), None)


def _require_create_control(meta: dict) -> None:
    blocked = _blocked(meta)
    if blocked:
        raise SecretBrowserRefused(f"credential create control crosses blocked boundary ({blocked})")
    semantic = _semantic(meta)
    if not any(verb in semantic for verb in CREATE_VERBS):
        raise SecretBrowserRefused("live control is not clearly a credential creation control")
    if not any(noun in semantic for noun in CREDENTIAL_NOUNS):
        raise SecretBrowserRefused("live control does not clearly name an API credential")


def _require_capture_control(meta: dict) -> None:
    blocked = _blocked(meta)
    if blocked:
        raise SecretBrowserRefused(f"capture target crosses blocked boundary ({blocked})")
    semantic = _semantic(meta)
    if not any(noun in semantic for noun in CREDENTIAL_NOUNS):
        raise SecretBrowserRefused("capture target does not clearly identify a credential")
    # A legitimate API key is often visually masked with type=password. The
    # semantic label must identify an API credential, and actual password/OTP/
    # payment autocomplete values are still a hard stop.
    autocomplete = str(meta.get("autocomplete", "")).casefold()
    if autocomplete in SECRET_AUTOCOMPLETE:
        raise SecretBrowserRefused("password/2FA/payment fields are not API credential outputs")


def _require_fill_control(meta: dict) -> None:
    blocked = _blocked(meta)
    # API-key/token words are intentionally allowed here; BLOCKED_TERMS does
    # not include them. Authentication *password/OTP* and money remain blocked.
    if blocked:
        raise SecretBrowserRefused(f"credential fill field crosses blocked boundary ({blocked})")
    semantic = _semantic(meta)
    if not any(noun in semantic for noun in FIELD_NOUNS):
        raise SecretBrowserRefused("live field does not clearly identify an API credential")
    # Masked API-key fields may also use type=password. Treat the live semantic
    # label + autocomplete contract as authoritative instead of the mask type.
    autocomplete = str(meta.get("autocomplete", "")).casefold()
    if autocomplete in SECRET_AUTOCOMPLETE:
        raise SecretBrowserRefused("password/2FA/payment fields cannot receive API aliases")


def _api_value(value: object) -> str:
    """Require a single opaque API credential, not a whole page/container."""
    if not isinstance(value, str):
        raise SecretBrowserError("credential output was not text")
    secret = value.strip()
    if not MIN_CAPTURE_CHARS <= len(secret) <= MAX_CAPTURE_CHARS:
        raise SecretBrowserError("credential output length was not plausible for an API credential")
    if not secret.isascii() or any(ch.isspace() for ch in secret):
        raise SecretBrowserError("credential output was not one bounded opaque API value")
    return secret


def _capture_value(page, selector: str) -> str:
    value = page.eval_on_selector(
        selector,
        """el => {
          const v = ('value' in el && typeof el.value === 'string') ? el.value : '';
          return (v || el.textContent || '').trim();
        }""",
    )
    return _api_value(value)


def _guard_host(page, host: str) -> None:
    if not _same_host(page.url, host):
        raise SecretBrowserRefused(
            "credential browser crossed to a different host; refusing to touch the page"
        )


def create_capture(*, url: str, create_selector: str, capture_selector: str,
                   alias: str) -> dict:
    """Create one API credential and vault it without returning plaintext."""
    host = _url_host(url)
    create_selector = _selector(create_selector, "create_selector")
    capture_selector = _selector(capture_selector, "capture_selector")
    alias = stateio.safe_id(alias, name="secret alias")
    if secret_store.exists(alias):
        raise SecretBrowserRefused(
            f"alias {alias!r} already exists; refusing to overwrite/rotate a stored credential"
        )
    policy.ensure_not_halted()
    secret_trust.claim("create_capture", host=host, alias=alias)
    ok, why = browse.available()
    if not ok:
        raise SecretBrowserError(f"browser unavailable ({why})")

    try:
        with browse._Session() as ctx:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded")
                _guard_host(page, host)
                _require_create_control(_element_meta(page, create_selector))
                page.click(create_selector)
                policy.ensure_not_halted()
                page.wait_for_selector(capture_selector)
                _guard_host(page, host)
                meta = _element_meta(page, capture_selector)
                _require_capture_control(meta)
                secret = _capture_value(page, capture_selector)
                stored = secret_store.put(
                    alias, secret, provider=host, kind="api_key",
                    allowed_hosts=[host],
                )
            finally:
                page.close()
    except (SecretBrowserRefused, SecretBrowserError):
        raise
    except Exception:
        # Browser/DPAPI exception strings are not allowed onto the public
        # receipt path after plaintext has existed in process memory.
        raise SecretBrowserError("credential create/capture failed locally") from None

    journal.append(
        "action", "secret:browser",
        f"created and vaulted alias {alias!r} for host {host}", actor=ACTOR,
    )
    return {
        "outcome": "stored",
        "alias": stored["name"],
        "kind": stored["kind"],
        "provider": stored["provider"],
        "allowed_hosts": stored["allowed_hosts"],
    }


def _alias_metadata(alias: str) -> dict:
    try:
        meta = secret_store.metadata(alias)
    except (KeyError, secret_store.SecretStoreError, ValueError):
        # Never send private local paths/state-reader details into a public receipt.
        raise SecretBrowserRefused(f"secret alias {alias!r} is unavailable or corrupt") from None
    if str(meta.get("kind", "")) not in API_KINDS:
        raise SecretBrowserRefused(
            f"alias {alias!r} is not classified as an API credential"
        )
    return meta


def fill_alias(*, url: str, selector: str, alias: str) -> dict:
    """Fill a host-bound vault alias into an API credential field locally."""
    host = _url_host(url)
    selector = _selector(selector, "selector")
    alias = stateio.safe_id(alias, name="secret alias")
    meta = _alias_metadata(alias)
    try:
        allowed = secret_store.normalize_hosts(meta.get("allowed_hosts") or [])
    except ValueError:
        raise SecretBrowserRefused(f"alias {alias!r} has invalid host binding metadata") from None
    if host not in allowed:
        raise SecretBrowserRefused(
            f"alias {alias!r} is not bound to host {host!r}; refusing possible exfiltration"
        )
    policy.ensure_not_halted()
    secret_trust.claim("fill_alias", host=host, alias=alias)
    ok, why = browse.available()
    if not ok:
        raise SecretBrowserError(f"browser unavailable ({why})")

    try:
        with browse._Session() as ctx:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded")
                _guard_host(page, host)
                _require_fill_control(_element_meta(page, selector))
                secret = _api_value(secret_store.get(alias))
                page.fill(selector, secret)
                # Read only length, never value, to prove something was filled
                # without pulling plaintext back out of the DOM.
                filled_length = page.eval_on_selector(
                    selector,
                    "el => (('value' in el && typeof el.value === 'string') ? el.value.length : -1)",
                )
                if not isinstance(filled_length, int) or filled_length != len(secret):
                    raise SecretBrowserError("credential field did not accept the stored alias")
            finally:
                page.close()
    except (SecretBrowserRefused, SecretBrowserError):
        raise
    except Exception:
        raise SecretBrowserError("credential fill failed locally") from None

    journal.append(
        "action", "secret:browser",
        f"filled alias {alias!r} into API credential field on host {host}", actor=ACTOR,
    )
    return {"outcome": "filled", "alias": alias, "host": host}
