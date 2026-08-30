"""Encrypted private observations over the public GitHub intercom.

The repository is public, but ChatGPT sometimes needs private UI state from the
operator's PC to continue a task. This module provides a confidential return
channel without another cloud service:

* ChatGPT creates an ephemeral RSA key pair and puts ONLY the public key in the
  quote-bound direct-work command.
* The PC observes the browser or Windows accessibility tree locally.
* The observation is bounded/redacted, encrypted with AES-256-GCM, and the AES
  key is wrapped with RSA-OAEP-SHA256.
* Only ciphertext is written under ``exchange/commands/sealed/``. The existing
  Core sync loop already commits that directory.
* Plaintext is never written to Git, journaled, printed, or returned in a
  normal intercom receipt.

This path is observation only. It cannot click, type, invoke, submit, or act.
"""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import urlparse, urlunparse

from aletheia import browse, journal, perception, policy, stateio, work_trust
from aletheia.fleet import REPO_ROOT

ACTOR = "aletheia-sealed-observe"
SEALED_DIR = REPO_ROOT / "exchange" / "commands" / "sealed"
VERSION = 1
ALG = "RSA-OAEP-SHA256+A256GCM"
MAX_PUBLIC_KEY_BYTES = 2048
MAX_BROWSER_TEXT = 14_000
MAX_BROWSER_CONTROLS = 160
MAX_PAYLOAD_BYTES = 64 * 1024

# Broad fallback on top of perception.redact(). It deliberately over-redacts
# opaque identifiers: losing an ID is safer than disclosing an unfamiliar
# credential shape to a model.
OPAQUE_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_./+=:-]{28,}(?![A-Za-z0-9])")
SECRET_FIELD_HINTS = (
    "password", "passphrase", "one-time", "one time", "otp",
    "verification code", "recovery code", "security code", "cvv", "pin",
    "api key", "apikey", "access token", "secret key", "private key",
)
CONTROL_SELECTOR = (
    "a[href],button,input,select,textarea,[role=button],[role=link],"
    "[role=menuitem],[role=tab]"
)


class SealedObservationError(RuntimeError):
    pass


def available() -> tuple[bool, str]:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        from cryptography.hazmat.primitives.serialization import load_der_public_key  # noqa: F401
    except ImportError:
        return False, (
            "cryptography is not installed "
            "(pip install -r requirements-optional.txt)"
        )
    return True, "encrypted observation ready"


def _clean(text: object, limit: int = 500) -> str:
    if not isinstance(text, str):
        return ""
    value = " ".join(text.split())[:limit]
    value = perception.redact(value)
    return OPAQUE_TOKEN.sub("[redacted opaque value]", value)


def _safe_response_id(value: str) -> str:
    return stateio.safe_id(value, name="response_id")


def sidecar_path(response_id: str):
    return SEALED_DIR / f"{_safe_response_id(response_id)}.json"


def _load_public_key(public_key_b64: str):
    ok, why = available()
    if not ok:
        raise SealedObservationError(why)
    if not isinstance(public_key_b64, str) or not public_key_b64:
        raise ValueError("public_key must be non-empty base64 DER")
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except Exception as exc:
        raise ValueError("public_key must be valid base64 DER") from exc
    if not 1 <= len(raw) <= MAX_PUBLIC_KEY_BYTES:
        raise ValueError("public_key has an invalid size")

    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    try:
        key = load_der_public_key(raw)
    except Exception as exc:
        raise ValueError("public_key is not valid DER") from exc
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
        raise ValueError("public_key must be RSA with at least 2048 bits")
    return key


def seal_payload(payload: dict, public_key_b64: str, response_id: str) -> dict:
    """Return a Git-safe encrypted envelope; never persist plaintext here."""
    rid = _safe_response_id(response_id)
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    plaintext = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if len(plaintext) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"observation exceeds {MAX_PAYLOAD_BYTES} bytes")
    public_key = _load_public_key(public_key_b64)

    import os
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    data_key = os.urandom(32)
    nonce = os.urandom(12)
    aad = f"aletheia-sealed-observe-v{VERSION}:{rid}".encode("utf-8")
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, aad)
    wrapped = public_key.encrypt(
        data_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "version": VERSION,
        "alg": ALG,
        "response_id": rid,
        "created_at": stateio.utcnow(),
        "aad": base64.b64encode(aad).decode("ascii"),
        "wrapped_key": base64.b64encode(wrapped).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def _write_sidecar(response_id: str, envelope: dict):
    path = sidecar_path(response_id)
    try:
        stateio.create_json_exclusive(path, envelope)
    except FileExistsError:
        # A retry after "sidecar written, receipt push failed" must not reread
        # private UI. The existing ciphertext is the idempotent result.
        pass
    return path


def _require_trust() -> dict:
    grant = work_trust.active()
    if not grant:
        raise PermissionError(
            "sealed private observation requires the local standing workstation grant"
        )
    policy.ensure_not_halted()
    return grant


def _safe_url(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _clean(raw, 500)
    # Queries/fragments can carry bearer tokens, OAuth codes, and private
    # search terms. They are not needed for navigation reasoning.
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))[:1000]


def _safe_href(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        return ""
    if raw.startswith(("/", "#")):
        return _clean(raw.split("?", 1)[0].split("#", 1)[0], 220)
    return _safe_url(raw)[:220]


def _browser_control_rows(page) -> list[dict]:
    rows = page.eval_on_selector_all(
        CONTROL_SELECTOR,
        """els => els.slice(0, 160).map(e => ({
            tag: (e.tagName || '').toLowerCase(),
            type: e.getAttribute('type') || '',
            role: e.getAttribute('role') || '',
            name: e.getAttribute('name') || '',
            id: e.id || '',
            aria: e.getAttribute('aria-label') || '',
            placeholder: e.getAttribute('placeholder') || '',
            text: (e.innerText || '').trim(),
            href: e.getAttribute('href') || ''
        }))""",
    )
    safe: list[dict] = []
    for row in (rows or [])[:MAX_BROWSER_CONTROLS]:
        if not isinstance(row, dict):
            continue
        descriptor = " ".join(
            str(row.get(k, ""))
            for k in ("type", "name", "id", "aria", "placeholder", "text")
        ).casefold()
        if any(hint in descriptor for hint in SECRET_FIELD_HINTS):
            safe.append({
                "tag": _clean(row.get("tag"), 30),
                "type": _clean(row.get("type"), 40),
                "label": "[credential control]",
                "redacted": True,
            })
            continue
        item = {
            "tag": _clean(row.get("tag"), 30),
            "type": _clean(row.get("type"), 40),
            "role": _clean(row.get("role"), 40),
            "name": _clean(row.get("name"), 80),
            "id": _clean(row.get("id"), 80),
            "aria": _clean(row.get("aria"), 140),
            "placeholder": _clean(row.get("placeholder"), 140),
            "text": _clean(row.get("text"), 180),
            "href": _safe_href(row.get("href")),
        }
        safe.append({k: v for k, v in item.items() if v})
    return safe


def _same_observation_host(requested, reached) -> bool:
    """Redirects may upgrade HTTP->HTTPS, but may not cross host boundaries."""
    return bool(
        requested.hostname
        and reached.hostname
        and requested.hostname.casefold() == reached.hostname.casefold()
    )


def observe_browser(url: str) -> dict:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("browser observation requires an absolute http(s) URL")
    ok, why = browse.available()
    if not ok:
        raise RuntimeError(f"cannot privately observe browser: {why}")

    with browse._Session() as ctx:
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            current_url = page.url
            current = urlparse(current_url)
            # An approved observation of site A must never become a private
            # read of site B because A redirected. Check BEFORE title/body/
            # controls are touched. Same-host HTTP->HTTPS is allowed.
            if not _same_observation_host(parsed, current):
                raise PermissionError(
                    "browser observation crossed to a different host; refusing "
                    "to read the redirected page"
                )
            result = {
                "kind": "browser",
                "url": _safe_url(current_url),
                "title": _clean(page.title(), 300),
                "text": _clean(page.inner_text("body") or "", MAX_BROWSER_TEXT),
                "controls": _browser_control_rows(page),
            }
        finally:
            page.close()
    # Never journal private title/text/path/query. Host is enough for audit.
    journal.append(
        "action", "sealed:browser",
        f"prepared encrypted browser observation for host "
        f"{current.hostname or parsed.hostname or '?'}",
        actor=ACTOR,
    )
    return result


def observe_screen(window: str | None = None) -> dict:
    selector = {"title_re": re.escape(window)} if window else None
    result = {"kind": "screen", "observation": perception.observe(selector)}
    journal.append(
        "action", "sealed:screen",
        "prepared encrypted Windows accessibility observation",
        actor=ACTOR,
    )
    return result


def run(*, response_id: str, public_key: str, target: str,
        url: str | None = None, window: str | None = None) -> dict:
    """Create one encrypted sidecar and return only safe metadata."""
    rid = _safe_response_id(response_id)
    existing = sidecar_path(rid)
    if existing.is_file():
        return {
            "response_id": rid,
            "state": "READY",
            "sidecar": str(existing.relative_to(REPO_ROOT)),
            "reused": True,
        }

    _require_trust()
    _load_public_key(public_key)  # validate before touching private UI
    if target == "browser":
        if not url or window is not None:
            raise ValueError("browser target requires url and does not accept window")
        payload = observe_browser(url)
    elif target == "screen":
        if url is not None:
            raise ValueError("screen target does not accept url")
        payload = observe_screen(window)
    else:
        raise ValueError("target must be 'browser' or 'screen'")

    envelope = seal_payload(payload, public_key, rid)
    path = _write_sidecar(rid, envelope)
    return {
        "response_id": rid,
        "state": "READY",
        "sidecar": str(path.relative_to(REPO_ROOT)),
        "reused": False,
    }
