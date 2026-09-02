"""Standing grants are valid only on the machine that created them.

The hole this closes (found in the 2026-09-01 catch-up review, and it is
exactly the thing the operator asked to have challenged): every standing
grant — work_trust, secret_trust, code_trust — validated on two facts
that can BOTH arrive over the public GitHub sync.

- The grant record lives under `state/private/`, which is gitignored —
  but `.gitignore` only prevents an *accidental* add. `git add -f` puts
  it in a commit, and the Core's sync pulls whatever is tracked.
- The approval it checks (`policy.is_approved`) lives in
  `state/approvals/`, which is tracked and public already.

So a single push to the repo could have manufactured standing
workstation trust, standing secret-fill authority, or standing
autonomous-PR authority on the operator's PC. Nothing in the code
refused it; only the working agreement about who writes what stood in
the way, and a working agreement is not a gate.

The fix is a fact that cannot travel: an HMAC over the grant's
identifying fields, keyed by a random secret generated on first use and
stored OUTSIDE the repository, in the operator's home directory beside
his other local credentials. A grant that arrives by any transport
carries a signature computed with a key the sender does not have, so
`verify()` refuses it and the grant is inert.

The key never enters git, a journal entry, a receipt, or a command line.
It is not a secret from the operator — it is a secret from the network.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

KEY_PATH = Path.home() / ".aletheia" / "machine.key"


def _key_path() -> Path:
    """Overridable for tests via ALETHEIA_MACHINE_KEY (a path, not a key)."""
    override = os.environ.get("ALETHEIA_MACHINE_KEY")
    return Path(override) if override else KEY_PATH


def machine_key() -> bytes:
    """Read the machine key, creating it on first use.

    Created with owner-only permissions where the platform supports it.
    A short/corrupt key file is replaced rather than trusted: a grant
    signed with a degenerate key is not a grant.
    """
    path = _key_path()
    try:
        raw = bytes.fromhex(path.read_text(encoding="utf-8").strip())
        if len(raw) >= 32:
            return raw
    except (OSError, ValueError):
        pass
    key = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.hex(), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # Windows/filesystems without POSIX modes
        pass
    return key


def sign(fields: dict) -> str:
    """HMAC-SHA256 over the canonical form of a grant's identifying fields."""
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hmac.new(machine_key(), canonical.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def verify(record: dict, fields: dict) -> bool:
    """True only when `record` carries a binding this machine could have made.

    Fails closed on a missing binding: a grant written before bindings
    existed, or one delivered by a transport that could not compute it,
    is refused. Re-enabling locally is one command and mints a bound one.
    """
    presented = record.get("machine_binding")
    if not isinstance(presented, str) or not presented:
        return False
    return hmac.compare_digest(presented, sign(fields))


def refuse_unbound(grant: dict, *, kind: str, restore_command: str) -> None:
    """Tell the operator why a grant he set up has stopped working.

    Bindings arrived after his grants did, so his existing ones fail
    closed — correct, but silence would read as "Aletheia randomly
    stopped doing routine work". Notifications dedupe on the key, so this
    is one notice per grant, not one per check.
    """
    from aletheia import journal, notifications
    grant_id = str(grant.get("id", "unknown"))
    try:
        notifications.publish(
            f"{kind} needs re-enabling once",
            f"The standing {kind} grant ({grant_id}) is not bound to this machine, "
            "so it is refused. Grants now carry a machine signature that cannot "
            f"travel over git. Re-enable it locally: {restore_command}",
            priority="IMPORTANT", source="authority",
            dedupe_key=f"unbound-grant:{grant_id}")
        journal.append(
            "event", f"{kind}:refused",
            f"grant {grant_id} refused: no valid machine binding "
            f"(re-enable locally with `{restore_command}`)",
            actor="aletheia-machine-binding")
    except Exception:  # never let telling him about it break the check
        pass
