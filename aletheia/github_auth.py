"""Bootstrap GitHub REST authentication into the local DPAPI vault.

The official GitHub CLI owns interactive/web authentication. Aletheia only asks
`gh auth token` for the already-authorized token, verifies it with an
authenticated read, and immediately stores it in Windows DPAPI. The token is
never printed, journaled, committed, or passed through the public command bus.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

from aletheia import gh, secret_store
from aletheia.proc import hidden_flags

ALIAS = gh.LOCAL_TOKEN_ALIAS


class GitHubAuthError(RuntimeError):
    pass


def cli_path() -> str | None:
    return shutil.which("gh")


def _cli_token() -> str:
    path = cli_path()
    if not path:
        raise GitHubAuthError("GitHub CLI is not installed")
    try:
        proc = subprocess.run(
            [path, "auth", "token"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
            creationflags=hidden_flags(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubAuthError(f"GitHub CLI auth could not be read ({type(exc).__name__})") from None
    token = (proc.stdout or "").strip()
    if proc.returncode != 0 or not token:
        raise GitHubAuthError("GitHub CLI is not signed in")
    if len(token) > 4096 or any(ch.isspace() for ch in token):
        raise GitHubAuthError("GitHub CLI returned an invalid token shape")
    return token


def _verify(token: str) -> dict:
    try:
        user = gh.request("GET", "/user", tok=token)
    except Exception as exc:
        raise GitHubAuthError(f"GitHub rejected local authentication ({type(exc).__name__})") from None
    login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(login, str) or not login:
        raise GitHubAuthError("GitHub authentication did not resolve an account")
    return {"authenticated": True, "login": login}


def import_from_cli() -> dict:
    ok, why = secret_store.available()
    if not ok:
        raise GitHubAuthError(f"local secret vault unavailable ({why})")
    token = _cli_token()
    verified = _verify(token)
    meta = secret_store.put(
        ALIAS, token, provider="github.com", kind="api_token",
        allowed_hosts=["api.github.com"],
    )
    return {
        **verified, "stored": True, "alias": meta["name"],
        "provider": meta["provider"], "kind": meta["kind"],
    }


def status() -> dict:
    try:
        token = gh.token()
    except Exception:
        token = None
    if not token:
        return {"authenticated": False, "stored": secret_store.exists(ALIAS)}
    try:
        result = _verify(token)
    except GitHubAuthError:
        return {"authenticated": False, "stored": secret_store.exists(ALIAS)}
    return {**result, "stored": secret_store.exists(ALIAS)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import/check GitHub authentication without printing tokens.")
    ap.add_argument("cmd", choices=["import-cli", "status"])
    args = ap.parse_args(argv)
    try:
        result = import_from_cli() if args.cmd == "import-cli" else status()
        print(json.dumps(result, indent=2))
        return 0 if result.get("authenticated") else 1
    except Exception as exc:
        print(json.dumps({"authenticated": False, "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
