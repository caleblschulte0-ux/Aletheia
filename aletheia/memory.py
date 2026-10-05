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
import re
from pathlib import Path

from aletheia import journal
from aletheia.fleet import REPO_ROOT

# PRIVATE state since 2026-09-04. The four domains held his identity,
# preferences, people and organizations in a directory the repository
# tracked - and the repository is public. The night before first real use
# a session recorded his home address here from his own resume and caught
# it in `git status` before it was committed. Playbook §38-45 calls these
# memory domains; CLAUDE.md says his words are never committed. This is
# the file that makes that true. `MEMORY_DIR` keeps its name because every
# test patches it; only the default moved.
from aletheia.stateio import private_dir
MEMORY_DIR = private_dir("memory")
DOMAINS = {"identity", "preferences", "people", "organizations"}
KINDS = {"explicit", "inferred", "temporary"}

#: Which shelf a fact's SUBJECT belongs on, by the subject's own words. Kept here, beside the
#: shelves, because the store is the one thing that knows what each domain IS; the composition
#: layer that derives a `remember` from "remember my landlord is Dana" names no category of its
#: own (tests/test_programs.py holds it to that). A subject naming none of these words goes
#: nowhere: a wrong shelf is worse than a question, so `domain_for` answers "" and the caller
#: leaves the domain to him.
SHELF_WORDS = {
    "people": ("landlord", "wife", "husband", "girlfriend", "boyfriend", "partner", "sister",
               "brother", "mom", "mother", "dad", "father", "son", "daughter", "friend", "boss",
               "manager", "dentist", "doctor", "neighbor", "neighbour", "roommate", "coworker",
               "recruiter", "contact", "cousin", "aunt", "uncle", "grandma", "grandpa", "plumber",
               "mechanic", "barber", "vet", "lawyer", "accountant", "trainer", "coach"),
    "organizations": ("company", "employer", "bank", "gym", "school", "college", "university",
                      "church", "clinic", "insurer", "insurance", "store", "shop", "team", "club",
                      "agency", "firm", "studio", "vendor", "supplier"),
    "preferences": ("favorite", "favourite", "prefer", "preferred", "usual", "default", "like",
                    "likes", "go-to", "go to", "preference"),
}


#: "remember that my landlord is Dana Whitfield": the subject, the joiner and the value, read
#: off the sentence. The subject may carry "my", "the" or "our"; the joiner is "is", "are", "="
#: or ":"; a trailing full stop is not part of the value. One parser, because the voice layer
#: and the work session's argument filling both compile this sentence and two copies drift.
FACT = re.compile(r"^(?:remember|note|save|keep in mind|record)(?: that|:)?\s+(?P<my>my\s+)?(?:the |our )?"
                  r"(?P<key>.+?)\s+(?:is|are|=|:)\s+(?P<value>.+?)[.!]?$", re.I | re.S)


def key_for(subject: str) -> str:
    """A memory key from a subject's words: lowercase, words joined by underscores, so
    "best friend" is stored where "who is my best friend" looks (`quick._person` tries the
    underscored form)."""
    # "sister's birthday" is a key about the sister, not about an "s".
    bare = re.sub(r"'s\b", "", str(subject or "").lower())
    words = re.sub(r"[^a-z0-9]+", "_", bare).strip("_")
    return words[:60].rstrip("_")


def parse_fact(sentence: str) -> dict | None:
    """{"subject", "key", "value", "domain"} when the sentence says "remember X is Y", else None.

    `value` keeps his capitals (it is sliced from the sentence as he said it), `domain` is
    `domain_for` and may be "" when the subject's words name no shelf."""
    text = " ".join(str(sentence or "").split())
    found = FACT.match(text)
    if not found:
        return None
    subject = found.group("key").strip()
    value = found.group("value").strip()[:480]
    mine = bool(found.group("my"))
    flipped = re.match(r"^(?:my|our)\s+(.+)$", value, re.I)
    if flipped and not domain_for(subject) and domain_for(flipped.group(1)):
        # "Remember Dana is my landlord" (2026-10-05): the shelf word is on
        # the right. The fact is about the landlord, and the landlord is Dana.
        subject, value, mine = flipped.group(1).strip(), subject, True
    return {"subject": subject, "key": key_for(subject), "value": value,
            "domain": domain_for(subject), "mine": mine}


def domain_for(subject: str) -> str:
    """The shelf for a fact about `subject`, or "" when its words name none.

    No "my ... is" fallback onto `identity`: "my lease is up in March" and "my flight is at
    six" are facts about his week, not about him, and a note the journal readers find
    ("what did I tell you about the lease") is the right place for them."""
    low = " ".join(str(subject or "").lower().split())
    for domain, words in SHELF_WORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            return domain
    return ""


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
             kind: str = "explicit", about: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} not in {sorted(KINDS)}")
    if not source.strip():
        raise ValueError("a memory without a source is a guess — provenance is required")
    data = _load(domain)
    entry = {
        "value": value, "source": source, "kind": kind,
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if about:
        # The subject as he said it ("your sister's birthday"), so what is
        # read back is his phrase and not the key's underscores.
        entry["about"] = str(about)[:80]
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
            if entry.get("about"):
                held["about"] = entry["about"]  # his phrase for it, for reading back
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
