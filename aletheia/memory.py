"""Structured memory with provenance (Playbook §§38–46, Phase 16 v1).

Four domains beyond the episodic journal — `identity`, `preferences`,
`people`, `organizations` — each a JSON file in `memory/` mapping a key
to an entry that always carries its provenance:

    {"value": …, "source": "…", "ts": "…", "kind": "explicit|inferred|temporary"}

so "Why do you think that?" (§45) is answerable for every fact, and an
explicit operator correction (§46 — "when I say after work I mean after
5:30") overwrites an inferred one but records where it came from.
Writers: the operator through the intercom's `remember` command (source
= their quoted words), Claude sessions, and the CLI. ChatGPT reads these
files raw to resolve references ("the doctor", "after work") — it never
writes them directly.

Sensitivity note: this repo is the store, so nothing secret belongs here
(§60) — no passwords, tokens, or data the operator wouldn't commit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from aletheia import journal
from aletheia.fleet import REPO_ROOT

MEMORY_DIR = REPO_ROOT / "memory"
DOMAINS = {"identity", "preferences", "people", "organizations"}
KINDS = {"explicit", "inferred", "temporary"}


def _path(domain: str) -> Path:
    if domain not in DOMAINS:
        raise ValueError(f"domain {domain!r} not in {sorted(DOMAINS)}")
    return MEMORY_DIR / f"{domain}.json"


def _load(domain: str) -> dict:
    p = _path(domain)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _save(domain: str, data: dict) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _path(domain).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")


def remember(domain: str, key: str, value, source: str,
             kind: str = "explicit") -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} not in {sorted(KINDS)}")
    if not source.strip():
        raise ValueError("a memory without a source is a guess — provenance is required")
    data = _load(domain)
    entry = {
        "value": value, "source": source, "kind": kind,
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    replaced = data.get(key)
    data[key] = entry
    _save(domain, data)
    note = f"set {domain}.{key} = {json.dumps(value, ensure_ascii=False)[:80]} ({kind})"
    if replaced:
        note += f" — replaced {replaced['kind']} value from {replaced['source'][:60]}"
    journal.append("note", f"memory:{domain}.{key}", note)
    return entry


def recall(domain: str, key: str):
    entry = _load(domain).get(key)
    return entry["value"] if entry else None


def everything(*, max_chars: int = 4_000) -> dict:
    """Every remembered fact, shaped for a reasoning prompt.

    Recall by exact key only is fine for code and useless in conversation:
    he says "what's my sister's name?", not "recall people.sister". Until
    this existed, `converse` had no path to any of it, so a fact he had
    deliberately told her to remember could not reach the answer — the
    single most obvious way for a personal assistant to feel like a
    stranger.

    Values only, with the KIND kept (`inferred` is a guess she made and he
    should be able to see that it is), and bounded: memory is small by
    design, but a prompt that grows without a ceiling is a bug waiting for
    the day somebody remembers a lot.
    """
    out: dict[str, dict] = {}
    spent = 0
    for domain in sorted(DOMAINS):
        try:
            entries = _load(domain)
        except (OSError, ValueError):
            continue                      # a corrupt file thins her, never mutes her
        for key in sorted(entries):
            entry = entries[key]
            if not isinstance(entry, dict) or "value" not in entry:
                continue
            value = entry["value"]
            text = value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False)
            spent += len(key) + len(text)
            if spent > max_chars:
                return out
            held = {"value": value}
            if entry.get("kind") and entry["kind"] != "explicit":
                held["kind"] = entry["kind"]   # a guess is labelled as one
            out.setdefault(domain, {})[key] = held
    return out


def why(domain: str, key: str) -> str:
    entry = _load(domain).get(key)
    if not entry:
        return f"no memory of {domain}.{key}"
    return (f"{domain}.{key} = {json.dumps(entry['value'], ensure_ascii=False)} — "
            f"{entry['kind']}, from: {entry['source']} (at {entry['ts']})")


def forget(domain: str, key: str, via: str = "operator-cli") -> bool:
    data = _load(domain)
    if key not in data:
        return False
    del data[key]
    _save(domain, data)
    journal.append("note", f"memory:{domain}.{key}", "forgotten", actor=via)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Structured memory with provenance.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_set = sub.add_parser("set")
    p_set.add_argument("domain", choices=sorted(DOMAINS))
    p_set.add_argument("key"); p_set.add_argument("value")
    p_set.add_argument("--source", required=True)
    p_set.add_argument("--kind", choices=sorted(KINDS), default="explicit")
    p_get = sub.add_parser("get")
    p_get.add_argument("domain", choices=sorted(DOMAINS)); p_get.add_argument("key")
    p_why = sub.add_parser("why")
    p_why.add_argument("domain", choices=sorted(DOMAINS)); p_why.add_argument("key")
    p_f = sub.add_parser("forget")
    p_f.add_argument("domain", choices=sorted(DOMAINS)); p_f.add_argument("key")
    p_l = sub.add_parser("list")
    p_l.add_argument("domain", nargs="?", choices=sorted(DOMAINS))
    args = ap.parse_args(argv)

    if args.cmd == "set":
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        remember(args.domain, args.key, value, source=args.source, kind=args.kind)
        print(f"remembered {args.domain}.{args.key}")
    elif args.cmd == "get":
        print(json.dumps(recall(args.domain, args.key), ensure_ascii=False))
    elif args.cmd == "why":
        print(why(args.domain, args.key))
    elif args.cmd == "forget":
        print("forgotten" if forget(args.domain, args.key) else "no such memory")
    else:
        for domain in ([args.domain] if args.domain else sorted(DOMAINS)):
            data = _load(domain)
            for key, e in sorted(data.items()):
                print(f"{domain}.{key:24} = {json.dumps(e['value'], ensure_ascii=False)[:60]}"
                      f"  [{e['kind']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
