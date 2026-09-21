"""Learned site skills: what she knows about a domain, as DATA, not code.

The brief (docs/JARVIS_BRIEF.md §4) asks for "learned site skills (field
aliases, known states, navigation hints)", and the operator's direction on
2026-09-16 says what they are for: *"Specialized job code is fine as an
optimization, but the intelligence underneath it should stay fluid and
general."* A skill here is a JSON document per domain. Nothing in it is a
job; any goal on that domain reads it and any run on it teaches it.

    field_aliases   {normalised label: input key}   "given name" -> "first_name"
    page_states     [{path, state, seen}]           /apply/review is a REVIEW
    nav_hints       [{from_state, role, label, led_to, seen}]
    boundaries      [{kind, path, note, seen}]      "CAPTCHA at /signup"
    mode            autonomous | assisted | manual_only
    prefer          {"route": ...}                  an optimisation hint (an ATS path)

TWO LAYERS. `config/site_skills.json` is the reviewed seed (committed, no
private data): the known ATS families as optimisations, and the domains
whose TERMS forbid automation. Learned skills live in private state,
because where he has been is his. A learned skill can ADD knowledge and can
make a domain MORE restricted; it can never make a manual-only domain
automatable - that floor is the seed's, and changing it is a reviewed edit.

Every learned fact carries `seen` (how many runs confirmed it), so one odd
run does not outvote ten good ones, and nothing is ever typed from a skill:
an alias only says which of HIS inputs a label means, and the value gate in
the loop still decides whether that value may be typed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from aletheia import stateio

AUTONOMOUS = "autonomous"
ASSISTED = "assisted"
MANUAL_ONLY = "manual_only"
MODES = (AUTONOMOUS, ASSISTED, MANUAL_ONLY)
#: How restrictive each mode is; the effective mode is the most restrictive.
_RANK = {AUTONOMOUS: 0, ASSISTED: 1, MANUAL_ONLY: 2}

MAX_ALIASES = 200
MAX_STATES = 80
MAX_HINTS = 60
MAX_BOUNDARIES = 40


def seeds_path() -> Path:
    from aletheia.fleet import REPO_ROOT
    return REPO_ROOT / "config" / "site_skills.json"


def skills_dir() -> Path:
    return stateio.private_dir("site-skills")


def domain_of(url_or_host: str) -> str:
    """The registrable-ish host a skill is keyed on: no scheme, no www, no port."""
    text = str(url_or_host or "").strip()
    host = urlparse(text).hostname if "://" in text else text.split("/")[0].split(":")[0]
    host = re.sub(r"^www\.", "", str(host or "").casefold())
    return host


def normal_label(label: str) -> str:
    """A label as an alias key: lowercase words, no punctuation, no asterisks,
    no "(required)" - the same question however a site decorates it."""
    text = re.sub(r"\((?:required|optional)\)|\*", " ", str(label or "").casefold())
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())[:80]


def _load_seeds() -> dict:
    try:
        value = json.loads(seeds_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"families": [], "manual_only": []}
    return value if isinstance(value, dict) else {"families": [], "manual_only": []}


def _matches(domain: str, pattern: str) -> bool:
    pattern = str(pattern or "").casefold().lstrip(".")
    return bool(pattern) and (domain == pattern or domain.endswith("." + pattern))


def seed_for(domain: str) -> dict:
    """The reviewed knowledge for a domain: its family and the terms floor."""
    seeds = _load_seeds()
    out: dict = {"mode": AUTONOMOUS, "families": []}
    for row in seeds.get("manual_only") or []:
        if _matches(domain, row.get("domain", "")):
            out["mode"] = MANUAL_ONLY
            out["manual_only_because"] = str(row.get("because") or "its terms forbid automation")
    for family in seeds.get("families") or []:
        if any(_matches(domain, d) for d in family.get("domains") or []):
            out["families"].append(family)
    return out


def _path(domain: str) -> Path:
    safe = re.sub(r"[^a-z0-9.-]+", "-", domain)[:120].strip("-.") or "unknown"
    return skills_dir() / f"{safe}.json"


def _empty(domain: str) -> dict:
    return {"domain": domain, "field_aliases": {}, "page_states": [], "nav_hints": [],
            "boundaries": [], "mode": AUTONOMOUS, "runs": 0}


def learned(domain: str) -> dict:
    try:
        value = stateio.read_json(_path(domain))
    except (OSError, ValueError):
        return _empty(domain)
    if not isinstance(value, dict):
        return _empty(domain)
    base = _empty(domain)
    base.update(value)
    return base


def for_domain(url_or_host: str) -> dict:
    """Everything known about a domain, seed and learned merged.

    Aliases: learned outrank seed (they were confirmed on THIS site). Mode:
    the most restrictive of the two - a learned skill cannot lift the
    manual-only floor, whatever is written in the private file.
    """
    domain = domain_of(url_or_host)
    seed = seed_for(domain)
    mine = learned(domain)
    aliases: dict[str, str] = {}
    states, hints, boundaries = [], [], []
    for family in seed["families"]:
        aliases.update({normal_label(k): v for k, v in (family.get("field_aliases") or {}).items()})
        states += [dict(s, source="seed") for s in family.get("page_states") or []]
        hints += [dict(h, source="seed") for h in family.get("nav_hints") or []]
        boundaries += [dict(b, source="seed") for b in family.get("boundaries") or []]
    aliases.update(mine.get("field_aliases") or {})
    mode = max((seed["mode"], str(mine.get("mode") or AUTONOMOUS)),
               key=lambda m: _RANK.get(m, 2))
    return {
        "domain": domain, "mode": mode if mode in MODES else MANUAL_ONLY,
        "manual_only_because": seed.get("manual_only_because", ""),
        "families": [f.get("name") for f in seed["families"]],
        # Where this site's email comes from, when it is not the site's own
        # domain (Greenhouse mails from greenhouse-mail.io). Seed only: a
        # learned skill cannot widen which senders a code may be read from.
        "mail_domains": sorted({str(d).casefold() for f in seed["families"]
                                for d in f.get("mail_domains") or [] if d}),
        "prefer": next((f.get("prefer") for f in seed["families"] if f.get("prefer")), None),
        "field_aliases": aliases,
        "page_states": list(mine.get("page_states") or []) + states,
        "nav_hints": list(mine.get("nav_hints") or []) + hints,
        "boundaries": list(mine.get("boundaries") or []) + boundaries,
        "runs": int(mine.get("runs") or 0),
    }


def _bump(rows: list[dict], match: dict, extra: dict, limit: int) -> list[dict]:
    for row in rows:
        if all(row.get(k) == v for k, v in match.items()):
            row["seen"] = int(row.get("seen") or 0) + 1
            row.update(extra)
            break
    else:
        rows.append({**match, **extra, "seen": 1})
    rows.sort(key=lambda r: -int(r.get("seen") or 0))
    return rows[:limit]


def path_of(url: str) -> str:
    """A url's path with ids blurred, so /jobs/123/apply and /jobs/456/apply
    are one page shape."""
    path = urlparse(str(url or "")).path or "/"
    return re.sub(r"/(?:\d+|[0-9a-f]{8,}|[0-9a-f-]{20,})(?=/|$)", "/*", path.casefold())[:160]


def learn(url: str, *, aliases: dict | None = None, state: str = "",
          hint: dict | None = None, boundary: dict | None = None) -> dict:
    """Fold what one run confirmed into the domain's skill. Never raises
    into the loop: a skill that cannot be written is a lost lesson, not a
    failed run."""
    domain = domain_of(url)
    if not domain:
        return {}
    try:
        skill = learned(domain)
        for label, key in (aliases or {}).items():
            norm = normal_label(label)
            if norm and key:
                skill["field_aliases"][norm] = str(key)
        if len(skill["field_aliases"]) > MAX_ALIASES:
            skill["field_aliases"] = dict(list(skill["field_aliases"].items())[-MAX_ALIASES:])
        if state:
            skill["page_states"] = _bump(skill["page_states"], {"path": path_of(url), "state": state},
                                         {}, MAX_STATES)
        if hint:
            skill["nav_hints"] = _bump(
                skill["nav_hints"],
                {"from_state": hint.get("from_state", ""), "role": hint.get("role", ""),
                 "label": str(hint.get("label") or "")[:80]},
                {"led_to": hint.get("led_to", "")}, MAX_HINTS)
        if boundary:
            skill["boundaries"] = _bump(
                skill["boundaries"], {"kind": boundary.get("kind", ""), "path": path_of(url)},
                {"note": str(boundary.get("note") or "")[:200]}, MAX_BOUNDARIES)
        skill["updated"] = stateio.utcnow()
        target = _path(domain)
        target.parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(target, skill)
        return skill
    except Exception:                                   # noqa: BLE001
        return {}


def count_run(url: str) -> None:
    domain = domain_of(url)
    if not domain:
        return
    try:
        skill = learned(domain)
        skill["runs"] = int(skill.get("runs") or 0) + 1
        target = _path(domain)
        target.parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(target, skill)
    except Exception:                                   # noqa: BLE001
        pass


def known_state(skill: dict, url: str) -> str:
    """The state this page shape was confirmed to be, if a run confirmed it."""
    here = path_of(url)
    for row in skill.get("page_states") or []:
        if row.get("path") == here and int(row.get("seen") or 1) >= 1:
            return str(row.get("state") or "")
    return ""


def alias_for(skill: dict, label: str) -> str:
    return str((skill.get("field_aliases") or {}).get(normal_label(label)) or "")


def all_skills() -> list[dict]:
    out = []
    folder = skills_dir()
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            value = stateio.read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            out.append({"domain": value.get("domain"), "runs": value.get("runs", 0),
                        "aliases": len(value.get("field_aliases") or {}),
                        "states": len(value.get("page_states") or []),
                        "boundaries": [b.get("kind") for b in value.get("boundaries") or []][:6]})
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="What she has learned about each site.")
    ap.add_argument("domain", nargs="?")
    args = ap.parse_args(argv)
    if args.domain:
        print(json.dumps(for_domain(args.domain), indent=1))
        return 0
    rows = all_skills()
    if not rows:
        print("No site skills learned yet. (The store is there; it is empty.)")
    for row in rows:
        print(f"{row['domain']:34} runs={row['runs']} aliases={row['aliases']} "
              f"states={row['states']} boundaries={row['boundaries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
