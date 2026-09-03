"""What she can actually do — answered from the registry, never guessed.

The most likely first question anyone asks a new assistant is some form
of "what can you do?", and the second is "can you do X?". Until now the
conversational half had no path to `config/capabilities.json` at all, so
both were answered by a language model reasoning from its general idea of
what an assistant probably does. That is exactly the failure the playbook
names twice (§104 never hallucinate capability, §106 never fake one), and
it is worse here than in most systems because most of the answers would
have been RIGHT — she really can send email, write files, drive the
desktop — which is what makes the wrong ones impossible to spot.

Three things this does that dumping the registry into a prompt would not:

- **It retrieves rather than recites.** 114 capabilities is more than a
  conversational prompt can carry, and the ceiling is real
  (`brain.MAX_TEXT`). Only what the question is about travels.
- **It answers "no" with a next step.** A capability at
  NEEDS_CONFIGURATION is not "I can't" — it is "not yet, and here is the
  command". `aletheia.setup` already holds those instructions and already
  proves them, so the two are joined here instead of a second copy being
  written that disagrees by Friday.
- **It never launders a status.** EXPERIMENTAL says experimental,
  NOT_BUILT says not built. A capability she has never successfully used
  must not be described in the same voice as one she uses every day.

The matching is deliberately plain: word overlap with a small hand-written
synonym map. No embeddings, no model call, no network — this has to run
inside the prompt-building path of every question, offline, in
milliseconds. It is a retrieval hint, not a judgement: the answer is still
written by the brain, from entries it can see and quote.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from aletheia import capabilities

# What a person says -> the words the registry actually uses. Every entry
# here is a phrase somebody would really say out loud; this is not a
# thesaurus, it is the gap between his vocabulary and the registry's.
SYNONYMS = {
    "email": ("mail", "inbox", "gmail", "message"),
    "mail": ("email", "inbox"),
    "text": ("message", "sms", "phone"),
    "call": ("phone", "dial", "ring"),
    "buy": ("purchase", "order", "shopping", "checkout"),
    "purchase": ("buy", "order", "shopping"),
    "order": ("purchase", "buy", "shopping"),
    "spend": ("purchase", "finance", "money", "pay"),
    "pay": ("finance", "purchase", "money"),
    "book": ("reservation", "reserve", "appointment", "schedule"),
    "reserve": ("reservation", "book", "appointment"),
    "appointment": ("reservation", "calendar", "meeting", "schedule"),
    "meeting": ("calendar", "schedule", "meet", "negotiate"),
    "schedule": ("calendar", "automation", "remind", "meeting"),
    "remind": ("remind", "notification", "schedule", "automation"),
    "calendar": ("calendar", "availability", "meeting", "schedule"),
    "free": ("availability", "calendar"),
    "write": ("file", "author", "document", "workspace"),
    "file": ("file", "author", "document", "workspace"),
    "document": ("file", "author", "document"),
    "edit": ("file", "author", "document"),
    "read": ("read", "browser", "document", "file"),
    "web": ("browser", "research", "read"),
    "internet": ("browser", "research"),
    "search": ("research", "browser", "journal"),
    "google": ("research", "browser"),
    "look": ("research", "browser", "observe"),
    "research": ("research", "browser"),
    "computer": ("computer", "screen", "desktop", "app"),
    "desktop": ("computer", "screen", "perception"),
    "screen": ("perception", "computer", "observe"),
    "app": ("computer", "control"),
    "open": ("computer", "control", "browser"),
    "code": ("code", "script", "task"),
    "script": ("task", "script", "code"),
    "program": ("code", "script", "task"),
    "video": ("media", "edit"),
    "audio": ("media", "audio", "speech"),
    "music": ("room", "media", "audio"),
    "lights": ("room", "scene"),
    "house": ("room", "scene", "device"),
    "remember": ("memory", "remember", "recall"),
    "forget": ("memory", "remember"),
    "know": ("memory", "recall", "context"),
    "car": ("vehicle",),
    "drive": ("vehicle", "travel"),
    "travel": ("travel", "place", "vehicle"),
    "trip": ("travel", "place"),
    "flight": ("travel", "reservation", "book"),
    "money": ("finance", "purchase", "subscription"),
    "bank": ("finance",),
    "invest": ("finance", "portfolio"),
    "subscription": ("subscription", "finance"),
    "stop": ("halt", "policy"),
    "halt": ("halt", "policy"),
    "approve": ("approve", "policy", "delegate"),
    "delegate": ("delegate", "policy", "agent"),
    "talk": ("converse", "speech", "voice"),
    "speak": ("speech", "voice", "announce"),
    "listen": ("voice", "wake", "audio"),
    "notify": ("notification", "announce", "deliver"),
    "notification": ("notification", "deliver", "announce"),
    "github": ("github", "workflow", "issue"),
    "repo": ("github", "fleet", "workflow"),
    "project": ("project", "plan", "goal"),
    "goal": ("goal", "plan", "mission"),
    "task": ("task", "plan"),
}

# Words that match everything and therefore mean nothing here.
STOP = frozenset("""
a an and are as at be by can could do does for from get give go has have he
her him his how i if in into is it its me my not of on or our she should so
that the their them then there these they this to us was we what when where
which who will with would you your yours am able about all any anything
""".split())

# Below this, a capability is not what he is asking about and including it
# only teaches the brain that the block is noise.
FLOOR = 2.0
DEFAULT_LIMIT = 6

# A question about the whole of her rather than one thing she does.
_BROAD = re.compile(
    r"\b(what (can|could|do) you (do|handle)|what are you (able|capable)|"
    r"your capabilities|what can( you)? help|everything you can|"
    r"what all can you|list (of )?(your )?(capabilities|abilities)|"
    r"what do you do)\b", re.I)


def _registry() -> dict:
    """Never raises. A registry that cannot be read makes her answer THINNER
    — "I would have to check" — never absent, and never a guess."""
    try:
        return capabilities.load_registry()
    except Exception:
        return {"capabilities": []}


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", str(text).casefold()) if w]


def _query_terms(question: str) -> dict[str, float]:
    """His words, plus the registry's words for the same things.

    A synonym is worth less than the word he actually used: "book" should
    prefer a capability whose own text says book, and only then reach for
    reservation.
    """
    terms: dict[str, float] = {}
    for word in _words(question):
        if word in STOP or len(word) < 3:
            continue
        terms[word] = max(terms.get(word, 0.0), 1.0)
        for alias in SYNONYMS.get(word, ()):
            terms[alias] = max(terms.get(alias, 0.0), 0.7)
    return terms


def _score(entry: dict, terms: dict[str, float]) -> float:
    """Weighted by WHERE the word appears: an id is what the thing IS."""
    fields = ((_words(entry.get("id", "")), 2.2),
              (_words(entry.get("description", "")), 1.0),
              (_words(entry.get("module", "")), 0.8))
    total = 0.0
    for words, weight in fields:
        seen = set(words)
        for term, value in terms.items():
            if term in seen:
                total += value * weight
    return total


def _next_step(capability_id: str) -> list[str]:
    """What he would have to do, if the checklist knows.

    A capability at NEEDS_CONFIGURATION is not "I can't" — it is "not yet,
    and here is the command". `aletheia.setup` already holds those
    instructions and already proves them by running them, so this joins the
    two rather than keeping a second copy that disagrees by Friday.
    """
    try:
        from aletheia import setup
        for step in setup.steps():
            if step.capability == capability_id:
                return [line for line in step.instructions() if line.strip()][:4]
    except Exception:
        pass
    return []


def _shape(entry: dict, *, with_steps: bool) -> dict:
    out = {"capability": entry["id"], "status": entry["status"],
           "what_it_is": entry.get("description", "")[:220]}
    if entry["status"] != "AVAILABLE" and with_steps:
        steps = _next_step(entry["id"])
        if steps:
            out["to_turn_it_on"] = steps
    return out


def relevant(question: str, *, limit: int = DEFAULT_LIMIT,
             registry: dict | None = None) -> list[dict]:
    """The capabilities this question is actually about. Possibly none."""
    terms = _query_terms(question)
    if not terms:
        return []
    registry = registry or _registry()
    scored = []
    for entry in registry.get("capabilities", []):
        value = _score(entry, terms)
        if value >= FLOOR:
            scored.append((value, entry))
    # Highest score first; ties broken so a thing she can really do outranks
    # one she cannot, because that is the more useful sentence to be told.
    scored.sort(key=lambda row: (row[0], row[1]["status"] == "AVAILABLE"),
                reverse=True)
    return [_shape(entry, with_steps=True) for _value, entry in scored[:limit]]


def overview(registry: dict | None = None) -> dict:
    """The whole of her, small enough to travel: counts and the gaps.

    "What can you do?" is not answered by 114 lines. It is answered by the
    shape of the thing plus the honest exceptions — what needs him, and
    what is not built — because those are the parts he can act on.
    """
    registry = registry or _registry()
    entries = registry.get("capabilities", [])
    by_status: dict[str, int] = {}
    for entry in entries:
        by_status[entry["status"]] = by_status.get(entry["status"], 0) + 1
    def named(status):
        return [{"capability": e["id"], "what_it_is": e.get("description", "")[:160]}
                for e in entries if e["status"] == status][:12]
    return {
        "how_many": len(entries),
        "by_status": by_status,
        "waiting_on_you": named("NEEDS_CONFIGURATION"),
        "not_built_yet": named("NOT_BUILT"),
        "registry_revision": registry.get("revision"),
    }


def for_question(question: str, *, registry: dict | None = None) -> dict:
    """What should travel with THIS question. Empty when it is not about her."""
    if _BROAD.search(str(question or "")):
        return {"asked_about": "everything", **overview(registry)}
    found = relevant(question, registry=registry)
    return {"asked_about": "specific", "matches": found} if found else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="What she can do, from the registry rather than from memory.")
    ap.add_argument("question", nargs="?",
                    help="a question; omit for the whole picture")
    args = ap.parse_args(argv)
    print(json.dumps(for_question(args.question) if args.question else overview(),
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
