"""The capability registry — Aletheia's self-knowledge (Playbook §§8, 104, Phase 2).

`config/capabilities.json` is the ONLY place Aletheia's abilities live:
what it can do (capability), how it currently does it (provider), how
risky it is, what approval it needs, what really calls it, and its honest
status — AVAILABLE / DEGRADED / EXPERIMENTAL / NEEDS_CONFIGURATION /
UNAVAILABLE / NOT_BUILT. "Can you do X?" is answered from here, never
improvised (§104: never hallucinate capability; §106: never fake one).

Rule zero meets §116: an AVAILABLE entry must name a real caller; a
NOT_BUILT entry must name its ticket. CI validates every entry against
`contracts.validate_capability`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from aletheia import contracts
from aletheia.fleet import REPO_ROOT

DEFAULT_PATH = REPO_ROOT / "config" / "capabilities.json"


class CapabilityError(ValueError):
    """The registry is missing or invalid — fail closed, never guess."""


def load_registry(path: Path | str = DEFAULT_PATH) -> dict:
    path = Path(path)
    try:
        reg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityError(f"capability registry unreadable: {exc}") from exc
    problems = validate(reg)
    if problems:
        raise CapabilityError("capability registry invalid:\n  " + "\n  ".join(problems))
    return reg


def validate(reg: dict) -> list[str]:
    problems: list[str] = []
    if "revision" not in reg:
        problems.append("missing revision")
    providers = {p.get("id") for p in reg.get("providers", [])}
    for p in reg.get("providers", []):
        problems += contracts.validate_provider(p)
    for a in reg.get("agents", []):
        problems += contracts.validate_agent(a)
        if a.get("provider") not in providers:
            problems.append(f"agent {a.get('id')}: provider {a.get('provider')!r} not declared")
    seen: set[str] = set()
    for c in reg.get("capabilities", []):
        problems += contracts.validate_capability(c)
        cid = c.get("id")
        if cid in seen:
            problems.append(f"duplicate capability id {cid!r}")
        seen.add(cid)
        if c.get("provider") not in providers:
            problems.append(f"{cid}: provider {c.get('provider')!r} not declared")
    return problems


def get(cid: str, reg: dict | None = None) -> dict:
    reg = reg or load_registry()
    for c in reg["capabilities"]:
        if c["id"] == cid:
            return c
    raise KeyError(f"no capability {cid!r} in the registry")


def by_status(status: str, reg: dict | None = None) -> list[dict]:
    reg = reg or load_registry()
    return [c for c in reg["capabilities"] if c["status"] == status]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        reg = load_registry()
    except CapabilityError as exc:
        print(exc, file=sys.stderr)
        return 1
    if "--validate" in argv:
        print(f"capability registry OK — rev {reg['revision']}, "
              f"{len(reg['capabilities'])} capabilities, {len(reg['providers'])} providers")
        return 0
    if argv and not argv[0].startswith("-"):
        try:
            c = get(argv[0], reg)
        except KeyError as exc:
            print(exc, file=sys.stderr)
            return 1
        for k, v in c.items():
            print(f"{k:16} {v}")
        return 0
    order = ["AVAILABLE", "DEGRADED", "EXPERIMENTAL", "NEEDS_CONFIGURATION",
             "UNAVAILABLE", "NOT_BUILT"]
    for status in order:
        rows = by_status(status, reg)
        if not rows:
            continue
        print(f"\n{status} ({len(rows)})")
        for c in rows:
            print(f"  {c['id']:26} [{c['risk_class']:6}] {c['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
