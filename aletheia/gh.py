"""Minimal GitHub REST client — the one door every capability talks through.

Token precedence:
1. FLEET_TOKEN (explicit cross-fleet environment override)
2. GITHUB_TOKEN (GitHub Actions/default environment)
3. Windows DPAPI alias ``github.fleet`` from Aletheia's local secret store

The DPAPI fallback lets background Scheduled Tasks authenticate without putting
a long-lived token in the public repo, command bus, or user environment.
Missing/unavailable local secret state simply means "no token"; callers still
handle that state honestly.
"""
from __future__ import annotations

import json
import os
import urllib.request

API = "https://api.github.com"
LOCAL_TOKEN_ALIAS = "github.fleet"


def token() -> str | None:
    explicit = os.environ.get("FLEET_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if explicit:
        return explicit
    if os.name != "nt":
        return None
    try:
        from aletheia import secret_store
        value = secret_store.get(LOCAL_TOKEN_ALIAS)
    except Exception:
        return None
    value = value.strip() if isinstance(value, str) else ""
    return value or None


def request(method: str, path: str, body: dict | None = None, tok: str | None = None):
    """One REST call. Returns parsed JSON (or None for empty responses)."""
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    tok = tok or token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8")) if raw else None
