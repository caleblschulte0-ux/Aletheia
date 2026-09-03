"""Authenticated remote access — the transport the phone never had (§92).

`interface/mobile.html` has existed since Phase 21 and no phone could ever
load it, for a good reason: the Core binds loopback only, because it had
no authentication and `--host` refused non-loopback rather than pretend
otherwise (§59, fail closed). The roadmap called the transport a ticket
and warned in the same breath that port 8777 must never simply be exposed
as a shortcut. This module is that ticket, built the long way.

Three conditions, all required, none of them defaulted on:

1. **A token exists.** Created only by an explicit `access mint`, shown to
   the operator exactly once, and stored only as a sha256. A stolen state
   directory yields hashes, not keys. No token, no remote listening — the
   Core keeps refusing the bind exactly as it does today.

2. **TLS is configured.** A bearer token over plain HTTP is a password
   read aloud on every hop. The Core will not bind a non-loopback address
   without a certificate and key, and this module will not invent one:
   `tailscale cert`, mkcert or Let's Encrypt produce a real one, and the
   Tailscale route is worth naming twice because it also solves getting
   home from a coffee shop without opening a port on his router.

3. **Scope.** A token is `read` or `full`. Read tokens answer GET and
   nothing else, so the wall on a phone cannot become a command channel
   because a screen was left unlocked on a train. Full is opt-in per
   token, per device, and expires.

Loopback is deliberately unchanged and stays unauthenticated: it is the
operator's own machine talking to itself, which is the same trust
boundary the Core has always had. Everything else authenticates, is rate
limited into uselessness after a handful of wrong guesses, and is
journaled with its token id — so "who asked" is answerable later.

Ability is still not permission (§70). A `full` token is authenticated,
not omnipotent: it reaches the same `/api/command` grammar behind the
same policy gates, so a phone can no more skip an approval than the
keyboard can.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import secrets
import sys
import threading

from aletheia import journal, stateio
from aletheia.stateio import private_dir

ACTOR = "aletheia-access"

SCOPES = ("read", "full")
TOKEN_BYTES = 32
DEFAULT_DAYS = 90

# Wrong guesses allowed from one address before it is locked out, and for
# how long. Small on purpose: a person mistyping a token retries once, and
# an attacker gets a few hundred attempts a day instead of millions.
MAX_FAILURES = 5
LOCKOUT_S = 900.0

_LOCK = threading.Lock()
_FAILURES: dict[str, list] = {}


def tokens_path():
    return stateio.private_dir("access") / "tokens.json"


def _load() -> dict:
    path = tokens_path()
    if not path.exists():
        return {"version": 1, "tokens": []}
    try:
        return stateio.read_json(path)
    except ValueError:
        # A corrupt token store authenticates nobody. Fail closed, loudly.
        journal.append("alert", "access",
                       "the token store is unreadable — remote access is closed "
                       "until it is repaired or re-minted", actor=ACTOR)
        return {"version": 1, "tokens": []}


def _save(store: dict) -> None:
    stateio.write_json_atomic(tokens_path(), store)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expired(record: dict, now: dt.datetime | None = None) -> bool:
    try:
        expires = dt.datetime.fromisoformat(str(record["expires"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return True  # no readable expiry is an expired token, not a forever one
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    return expires <= (now or dt.datetime.now(dt.timezone.utc))


def live_tokens(now: dt.datetime | None = None) -> list[dict]:
    return [t for t in _load()["tokens"]
            if not t.get("revoked") and not _expired(t, now)]


def enabled(now: dt.datetime | None = None) -> bool:
    """Is there any credential a remote caller could present?"""
    return bool(live_tokens(now))


def mint(label: str, scope: str = "read", days: int = DEFAULT_DAYS) -> tuple[str, dict]:
    """Create a token. Returns (plaintext, record) — the plaintext exists
    in this process and nowhere else, ever again."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    if not str(label).strip():
        raise ValueError("a token needs a label — 'iPhone', 'the tablet'; "
                         "an unlabelled credential cannot be revoked with confidence")
    if not isinstance(days, int) or not 1 <= days <= 365:
        raise ValueError("days must be 1..365 — a credential that never expires "
                         "is one nobody remembers to remove")
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires = (dt.datetime.now(dt.timezone.utc)
               + dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {"id": "tok-" + secrets.token_hex(5), "label": str(label)[:64],
              "scope": scope, "sha256": _digest(token), "expires": expires,
              "created_at": stateio.utcnow(), "last_used": None}
    store = _load()
    store["tokens"].append(record)
    _save(store)
    journal.append("decision", "access",
                   f"minted {scope} token {record['id']} for {record['label']!r}, "
                   f"expires {expires}", actor=ACTOR)
    return token, record


def revoke(token_id: str) -> bool:
    store = _load()
    for record in store["tokens"]:
        if record["id"] == token_id and not record.get("revoked"):
            record["revoked"] = stateio.utcnow()
            _save(store)
            journal.append("decision", "access", f"revoked token {token_id}",
                           actor=ACTOR)
            return True
    return False


def locked_out(address: str, now: float | None = None) -> bool:
    import time
    now = now if now is not None else time.monotonic()
    with _LOCK:
        recent = [t for t in _FAILURES.get(address, []) if now - t < LOCKOUT_S]
        _FAILURES[address] = recent
        return len(recent) >= MAX_FAILURES


def _note_failure(address: str, now: float | None = None) -> None:
    import time
    now = now if now is not None else time.monotonic()
    with _LOCK:
        _FAILURES.setdefault(address, []).append(now)


def clear_failures() -> None:
    with _LOCK:
        _FAILURES.clear()


def verify(token: str, address: str = "?",
           now: dt.datetime | None = None) -> dict | None:
    """The token's record, or None. Constant-time, rate limited, journaled."""
    if locked_out(address):
        return None
    presented = _digest(str(token or ""))
    for record in live_tokens(now):
        # compare_digest on the HASHES: equal length, no early exit, and the
        # secret itself is never held next to an attacker-supplied string
        if hmac.compare_digest(presented, record["sha256"]):
            return record
    _note_failure(address)
    journal.append("alert", "access",
                   f"rejected remote credential from {address}", actor=ACTOR)
    return None


def note_use(token_id: str) -> None:
    store = _load()
    for record in store["tokens"]:
        if record["id"] == token_id:
            record["last_used"] = stateio.utcnow()
            _save(store)
            return


def bearer(headers) -> str:
    """The token out of an Authorization header, or ''."""
    raw = ""
    try:
        raw = headers.get("Authorization", "") or ""
    except AttributeError:
        return ""
    prefix = "bearer "
    return raw[len(prefix):].strip() if raw.lower().startswith(prefix) else ""


LOCAL_SECRET_NAME = "local-session.token"
LOCAL_SECRET_BYTES = 32


def local_secret_path() -> Path:
    return private_dir("access") / LOCAL_SECRET_NAME


def local_secret() -> str:
    """A per-machine secret that local WRITES must carry (2026-09-03).

    Loopback used to be trusted outright: the Core's own comment called it
    "the operator's own machine talking to itself". A security review made
    the distinction that matters — 127.0.0.1 proves where a packet came
    from, not that Caleb sent it. Any process running under his Windows
    account could POST /api/command and approve an email, resume after a
    halt, or drive the desktop.

    Reads stay open on loopback deliberately, and that is not laziness: a
    local process can already read `state/` off the same disk, so gating GET
    would cost real usability and buy nothing against this threat. WRITES
    are different — approving is an escalation nothing on disk gives away —
    so a POST from loopback must present this secret.

    The Core mints it at startup and injects it into the pages it serves, so
    the wall and the Command Center keep working with no login.
    """
    path = local_secret_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    secret = secrets.token_urlsafe(LOCAL_SECRET_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret, encoding="utf-8")
    try:      # best effort; the private dir is already user-scoped
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def local_write_allowed(supplied: str | None) -> bool:
    """Constant-time comparison of a supplied local secret."""
    if not supplied:
        return False
    return secrets.compare_digest(str(supplied), local_secret())


def is_loopback(address: str) -> bool:
    return str(address) in ("127.0.0.1", "::1", "localhost")


def proxied_via_tailscale(headers) -> bool:
    """Did this request arrive through `tailscale serve`'s local proxy?

    Added 2026-09-03. `tailscale serve` terminates TLS on the tailnet
    hostname and forwards to the configured backend as a NEW connection
    FROM THIS MACHINE — so a phone reaching the Core over Tailscale looks,
    at the socket level, identical to a script sitting at the keyboard:
    both show client_address 127.0.0.1. Treating both as "loopback" (the
    Core's original, narrower meaning — HIS machine talking to itself) let
    every device on the tailnet inherit full local trust with no token, no
    scope, no revocation.

    The distinguishing signal is real, not inferred: tailscaled itself
    adds `Tailscale-*` headers to every request it forwards (verified live
    against this machine's tailscaled — `Tailscale-User-Login`,
    `Tailscale-Headers-Info`, and others), and nothing else on this
    machine has a reason to send them. A local process COULD forge one on
    its own direct request, but that only routes it into the STRICTER
    branch below (a real minted token, checked in constant time) — forging
    the header buys an attacker nothing; it cannot manufacture the token.
    """
    try:
        return any(str(name).lower().startswith("tailscale-") for name in headers.keys())
    except AttributeError:
        return False


def forwarded_address(headers, fallback: str) -> str:
    """The real originating tailnet IP when tailscale served the request,
    for rate-limiting and audit that mean something per-device again."""
    try:
        forwarded = (headers.get("X-Forwarded-For", "") or "").split(",")[0].strip()
    except AttributeError:
        forwarded = ""
    return forwarded or fallback


def is_genuinely_local(address: str, headers) -> bool:
    """The Core's ORIGINAL loopback trust: this machine talking to itself,
    not merely a packet that happens to arrive from 127.0.0.1 (which a
    tailscale-serve-proxied phone request also does)."""
    return is_loopback(address) and not proxied_via_tailscale(headers)


def scope_allows(scope: str, method: str) -> bool:
    """A read token answers GET and HEAD. Anything that changes state is full."""
    return scope == "full" or str(method).upper() in ("GET", "HEAD")


def bind_refusal(host: str, tls_cert: str | None, tls_key: str | None,
                 now: dt.datetime | None = None) -> str | None:
    """Why this host must not be served, or None if it may be.

    The whole fail-closed rule in one place, so the Core cannot drift from
    it and a test can hold it.
    """
    if is_loopback(host) or host in ("127.0.0.1", "localhost"):
        return None
    if not enabled(now):
        return ("no access token exists — run `python -m aletheia.access mint "
                "\"<device>\"` first; the Core will not listen off-loopback "
                "with nothing to authenticate")
    if not (tls_cert and tls_key):
        return ("no TLS certificate — a bearer token over plain HTTP is a "
                "password said out loud on every hop. Get one with "
                "`tailscale cert <name>` (which also gets you home without "
                "opening a port), mkcert, or Let's Encrypt, then pass "
                "--tls-cert/--tls-key")
    from pathlib import Path
    missing = [p for p in (tls_cert, tls_key) if not Path(p).is_file()]
    if missing:
        return f"TLS files not found: {', '.join(missing)}"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Credentials for reaching the Core from off this machine.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_mint = sub.add_parser("mint", help="create a token (shown once)")
    p_mint.add_argument("label", help="which device this is for")
    p_mint.add_argument("--scope", choices=SCOPES, default="read")
    p_mint.add_argument("--days", type=int, default=DEFAULT_DAYS)
    sub.add_parser("list")
    p_rev = sub.add_parser("revoke")
    p_rev.add_argument("id")
    args = ap.parse_args(argv)

    if args.cmd == "mint":
        token, record = mint(args.label, args.scope, args.days)
        print(f"token id : {record['id']}  ({record['scope']}, expires {record['expires']})")
        print(f"token    : {token}")
        print("\nThis is the only time it is shown — only its sha256 is stored.")
        print("Send it to the device over something you trust, then:")
        print("  Authorization: Bearer <token>")
        return 0
    if args.cmd == "revoke":
        ok = revoke(args.id)
        print("revoked." if ok else f"no live token {args.id!r}.")
        return 0 if ok else 1
    rows = _load()["tokens"]
    for record in rows:
        state = ("revoked" if record.get("revoked")
                 else "expired" if _expired(record) else "live")
        print(f"{record['id']}  {state:8} {record['scope']:5} "
              f"expires {record['expires']}  {record['label']}"
              + (f"  last used {record['last_used']}" if record.get("last_used") else ""))
    print(f"{len(rows)} token(s); {len(live_tokens())} live", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
