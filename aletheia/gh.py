"""Minimal GitHub REST client — the one door every capability talks through.

Token precedence: FLEET_TOKEN (cross-fleet PAT) then GITHUB_TOKEN (Actions
default, this repo only). Callers that can act without a token don't exist;
callers must handle the None-token case honestly rather than pretending.
"""
from __future__ import annotations

import json
import os
import urllib.request

API = "https://api.github.com"


def token() -> str | None:
    return os.environ.get("FLEET_TOKEN") or os.environ.get("GITHUB_TOKEN")


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
