"""Pursuit — reason about ONE opportunity at a time, and decide what, if
anything, would help it along.

His brief, 2026-09-21 (`docs/PURSUIT_BRIEF.md`): do not build a fixed
workflow of find, tailor, apply, message, follow up; every opportunity is
its own problem. The objective is given; the sequence is not. For every opportunity worth the time, use
the evidence she holds - and obtain more when it would change the answer -
to decide what would most increase his chance of serious consideration,
truthfully, without noise, and inside his authority rules.

The durable object is the OPPORTUNITY, not an application:

    objective · evidence · understanding · uncertainty · strategy ·
    moves taken and their effects · people · commitments · things never to
    repeat · the next decision point · effort spent · outcome

A pass over one opportunity is:

    observe -> understand -> identify uncertainty -> gather -> reason ->
    act -> observe the result -> update the plan

and nothing here knows what an opportunity IS. The words that would make
it one kind of thing (a role, an employer, his CV) live in whatever
opens it (`pursuit_applications`) and in the evidence, never in this
module - `tests/test_studies.py` walks this file's strings and identifiers
for a domain word.

Three rules hold the brief's two hard lines:

- **A move must cite evidence she holds, and say why it would help THIS
  opportunity.** `validate` drops a move with no citation or no reason; a
  note or a document must also name the evidence its claims stand on
  (creative strategy is encouraged, creative biography is forbidden). A
  kind she has no tool for is not refused: it becomes a suggestion he
  hears, so she may invent a tactic without pretending to do it.
- **Nothing outward leaves without his yes.** A note is a DRAFT through
  `mail.draft` / `messages.draft`, each bound to its own approval; a page
  read and a workspace file are reversible and go in the autonomy ledger.
- **Effort is a decision, bounded.** The model says how many more minutes
  this opportunity is worth; `EFFORT_DAY_S` caps a day. Not a tier: a
  ceiling.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from aletheia import journal, stateio

ACTOR = "aletheia-pursuit"
VERSION = 1

OPEN, PARKED, CLOSED = "OPEN", "PARKED", "CLOSED"
STATES = (OPEN, PARKED, CLOSED)

#: What she may DO about an opportunity. A catalog of tools, not stages:
#: the reasoner chooses among them per opportunity, or chooses none.
#: `yes` says whether his approval stands between the move and the world.
MOVES = {
    "look": {"does": "read a page or search the web for something specific, and keep what it says as evidence",
             "yes": False},
    "submit": {"does": "put the application in through the door the opportunity offers (his standing rules for that door apply)",
               "yes": True},
    "note_to_person": {"does": "draft a short, specific note to a named person; it waits for his yes before it is sent",
                       "yes": True},
    "write": {"does": "write a document (an analysis, a short piece, a page) into her workspace for him to use or send",
              "yes": False},
    "wait": {"does": "decide a date to look at this again, and why", "yes": False},
    "leave": {"does": "nothing else would help; leave it until something happens", "yes": False},
    "close": {"does": "stop pursuing it, with the reason", "yes": False},
    "suggest": {"does": "something she cannot do herself but thinks would help; he hears it", "yes": True},
}
#: Moves she may carry out without him (the reversible half).
UNATTENDED_MOVES = ("look", "write", "wait", "leave", "close")
#: A move's `why` shorter than this is not a reason.
MIN_WHY_CHARS = 12
MAX_MOVES_PER_PASS = 4
MAX_EVIDENCE_CHARS = 12_000       # what a frontier model is shown
COMPACT_EVIDENCE_CHARS = 3_000    # what her own model is shown
#: The gateway's default whole-context cap is 8 KB, sized for a sentence
#: and a snapshot. A real opportunity's evidence (the posting alone is up
#: to 6 KB) needs the room the fit judge already takes for itself.
MAX_CONTEXT_BYTES = 20 * 1024
MAX_NOTE_CHARS = 1_500
MAX_DOC_CHARS = 8_000
#: The most she may spend on one opportunity in a day, whatever the model
#: says it is worth. A ceiling, never a tier.
EFFORT_DAY_S = 45 * 60
#: A pass that does no gathering still costs this much of the budget.
PASS_COST_S = 30.0
OUTCOMES = ("replied", "conversation", "offer", "declined", "gone", "took_it", "dropped")
LOOKED_BACK_DAYS = 90

UNTRUSTED = "UNTRUSTED_WEB"
TRUSTED = "TRUSTED_LOCAL_STATE"

_LOCK = threading.Lock()
#: How each move is carried out. Injectable, so an adapter may register the
#: one door only it knows (`submit`) and tests may stub the world.
DOERS: dict = {}


class PursuitError(RuntimeError):
    pass


# ---------------------------------------------------------------- store

def store_dir() -> Path:
    return stateio.private_dir("opportunities")


def _path(oid: str) -> Path:
    return store_dir() / f"{stateio.safe_id(oid, name='opportunity id')}.json"


def load(oid: str) -> dict:
    return stateio.read_json(_path(oid))


def save(record: dict) -> dict:
    record["updated_at"] = stateio.utcnow()
    stateio.write_json_atomic(_path(record["id"]), record)
    return record


def all_opportunities(state: str | None = None) -> list[dict]:
    rows = []
    for path in sorted(store_dir().glob("opp-*.json")):
        try:
            row = stateio.read_json(path)
        except ValueError:
            continue
        if state is None or row.get("state") == state:
            rows.append(row)
    return rows


def find(which: str) -> dict | None:
    """By id, or by the subject's key or name (case-insensitive)."""
    want = str(which or "").strip().casefold()
    if not want:
        return None
    for row in all_opportunities():
        subject = row.get("subject") or {}
        if want in (row["id"].casefold(), str(subject.get("key", "")).casefold(),
                    str(subject.get("name", "")).casefold()):
            return row
    return None


def _now(now: dt.datetime | None) -> dt.datetime:
    return now or dt.datetime.now(dt.timezone.utc)


def _stamp(now: dt.datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def opportunity_id(key: str) -> str:
    return "opp-" + hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:10]


def open_opportunity(*, key: str, name: str, objective: str, subject: dict | None = None,
                     now: dt.datetime | None = None) -> dict:
    """Open (or return the existing) opportunity for `key`. Idempotent."""
    now = _now(now)
    oid = opportunity_id(key)
    path = _path(oid)
    if path.exists():
        return stateio.read_json(path)
    record = {
        "version": VERSION, "id": oid, "state": OPEN,
        "subject": {"key": key, "name": name, **(subject or {})},
        "objective": " ".join(str(objective).split()),
        "evidence": [], "understanding": "", "uncertainty": [], "strategy": "",
        "moves": [], "people": [], "commitments": [], "never_repeat": [],
        "next_look": {"at": _stamp(now), "because": "just opened"},
        "outcome": None,
        "effort": {"spent_s": 0.0, "day": now.strftime("%Y-%m-%d"), "allowed_s": 0.0,
                   "because": ""},
        "history": [], "created_at": _stamp(now), "updated_at": _stamp(now),
    }
    save(record)
    journal.append("event", f"opportunity:{oid}", f"opened: {name} — {record['objective']}",
                   actor=ACTOR)
    return record


def add_evidence(record: dict, kind: str, text: str, *, source: str = "",
                 provenance: str = TRUSTED, now: dt.datetime | None = None) -> str:
    """Append one piece of evidence and return its id. Same text twice is one."""
    text = str(text or "").strip()
    if not text:
        return ""
    digest = hashlib.sha1(f"{kind}|{source}|{text}".encode("utf-8")).hexdigest()[:8]
    for row in record["evidence"]:
        if row.get("digest") == digest:
            return row["id"]
    eid = f"e{len(record['evidence']) + 1}"
    record["evidence"].append({"id": eid, "kind": kind, "source": source, "text": text,
                               "provenance": provenance, "digest": digest,
                               "at": _stamp(_now(now))})
    return eid


def observe(oid: str, kind: str, text: str, *, source: str = "", provenance: str = UNTRUSTED,
            now: dt.datetime | None = None) -> dict:
    """Something happened (a reply, a change on the page). It is evidence,
    and it makes the opportunity worth looking at again NOW."""
    now = _now(now)
    with _LOCK:
        record = load(oid)
        eid = add_evidence(record, kind, text, source=source, provenance=provenance, now=now)
        if record["state"] == PARKED:
            record["state"] = OPEN
        record["next_look"] = {"at": _stamp(now), "because": f"new {kind}"}
        record["history"].append({"at": _stamp(now), "what": f"observed {kind} ({eid})"})
        save(record)
    journal.append("event", f"opportunity:{oid}", f"heard something new ({kind}): {text[:140]}",
                   actor=ACTOR)
    return record


def record_outcome(oid: str, kind: str, *, note: str = "", now: dt.datetime | None = None) -> dict:
    if kind not in OUTCOMES:
        raise PursuitError(f"an outcome is one of {', '.join(OUTCOMES)}")
    now = _now(now)
    with _LOCK:
        record = load(oid)
        record["outcome"] = {"kind": kind, "note": note, "at": _stamp(now)}
        if kind in ("declined", "gone", "took_it", "dropped"):
            record["state"] = CLOSED
        else:
            record["state"] = OPEN
            record["next_look"] = {"at": _stamp(now), "because": f"outcome: {kind}"}
        record["history"].append({"at": _stamp(now), "what": f"outcome {kind}: {note}"[:200]})
        save(record)
    journal.append("event", f"opportunity:{oid}", f"outcome: {kind}" + (f" — {note}" if note else ""),
                   actor=ACTOR)
    return record


# ---------------------------------------------------------------- what has worked

def lessons(*, now: dt.datetime | None = None, limit: int = 12) -> list[str]:
    """What actually happened, per opportunity, as sentences.

    Given to the reasoner as evidence, never applied as a rule: "a note to
    a named person got a reply at X" is context for the next decision, not
    an instruction to always write one.
    """
    now = _now(now)
    rows = []
    for record in all_opportunities():
        outcome = record.get("outcome")
        done = [m for m in record.get("moves", []) if m.get("state") in ("done", "sent")]
        if not outcome and not done:
            continue
        when = _parse((outcome or {}).get("at") or record.get("updated_at") or "")
        if when and (now - when).days > LOOKED_BACK_DAYS:
            continue
        kinds = [m["kind"] for m in done] or ["nothing beyond opening it"]
        said = f"{record['subject'].get('name', record['id'])}: did {', '.join(kinds)}"
        said += f" — outcome {outcome['kind']}" if outcome else " — no outcome yet"
        rows.append(said)
    return rows[-limit:]


# ---------------------------------------------------------------- reasoning

BRIEF = """You are deciding what, if anything, would help ONE opportunity along.
The objective and every piece of evidence held are below, each with an id.

Think about THIS situation: what is known, what is not, what would change the
answer if it were known, and what he legitimately has that the ordinary
candidate may not. Then propose the few moves that would most increase the
chance of serious consideration, or propose none if nothing more would help.
There is no required sequence and no default next step.

Rules:
- Every move must say WHY it would help this particular opportunity, and
  must cite the evidence ids it rests on. A move with no reason is dropped.
- A note or a document may state only what the cited evidence supports.
  Invent tactics freely; never invent facts about him or about them.
- Do not repeat anything listed under never_repeat.
- Say how many more minutes of work this opportunity is worth right now, and
  why. Zero is a fine answer.
- A move of a kind not in the catalog is allowed: it becomes a suggestion he
  hears. Do not pretend it can be carried out.
- YOU do the work. Anything you would do now is a move in "moves", not a
  sentence in the strategy: a brief to write is a "write" move, a page to
  check is a "look", something only he can do is a "suggest". Never assign
  him a chore in prose; the strategy is the hypothesis, not a to-do list.

Answer with ONE JSON object:
{"understanding": "<what this situation is, in a few sentences>",
 "uncertainty": ["<what would change the answer if known>", ...],
 "strategy": "<the current best hypothesis, one or two sentences>",
 "effort": {"minutes": <0-60>, "why": "<why that much>"},
 "moves": [{"kind": "<catalog kind or your own words>", "why": "<the causal reason>",
            "cites": ["e1", ...],
            "detail": {<per kind: look: {"question", "url" or "query"};
                       note_to_person: {"to", "subject", "text", "grounded_on": [ids]};
                       write: {"title", "text", "grounded_on": [ids]};
                       wait: {"days", "for"}; suggest: {"idea"}; others: {}>}}],
 "stop": {"done": <true if nothing more is worth doing now>, "why": "<why>"}}
"""

COMPACT_BRIEF = """Decide what, if anything, would help ONE opportunity. Evidence has ids.
Look for ONE concrete match between what they ask for and what he has.
Propose at most two moves from the catalog, or none. Every move must carry
"quote": an exact sentence copied from the evidence it rests on - if you
cannot quote it, do not propose it. Never invent facts. Answer with one JSON object:
{"understanding": "...", "uncertainty": [], "strategy": "...",
 "effort": {"minutes": 0, "why": "..."},
 "moves": [{"kind": "...", "why": "...", "cites": ["e1"], "quote": "...", "detail": {}}],
 "stop": {"done": true, "why": "..."}}
"""
#: A quote shorter than this is not a quote.
MIN_QUOTE_CHARS = 20


def _quoted(move_raw: dict, record: dict, cites: list[str]) -> bool:
    """Does the move carry a verbatim line from the evidence it cites?

    The rule `page_answer` already uses for her own model: it may only
    answer by QUOTING what she holds, because an invented answer comes with
    an invented quote and an invented quote is checkable. A move with no
    quote, or a "quote" that is not in the cited evidence, is dropped.
    """
    quote = " ".join(str(move_raw.get("quote") or "").split()).casefold()
    if len(quote) < MIN_QUOTE_CHARS:
        return False
    held = {row["id"]: " ".join(str(row.get("text", "")).split()).casefold()
            for row in record.get("evidence", [])}
    return any(quote in held.get(cid, "") for cid in cites)


def _evidence_text(record: dict, budget: int) -> list[dict]:
    """Every piece of evidence, cut to `budget` characters in total.

    An EVEN share each, with what a short piece leaves over passed to the
    long ones - not newest-first: at her own model's 3 KB the first live
    pass (2026-09-22) filled the budget with his background and never
    showed the posting at all, and then reasoned about a role it had not
    read.
    """
    rows = [r for r in record.get("evidence", []) if str(r.get("text", "")).strip()]
    if not rows:
        return []
    shares = {r["id"]: 0 for r in rows}
    left = budget
    pending = sorted(rows, key=lambda r: len(str(r["text"])))
    while pending and left > 0:
        each = left // len(pending)
        row = pending.pop(0)
        take = min(len(str(row["text"])), max(each, 80))
        shares[row["id"]] = take
        left -= take
    out = []
    for row in rows:
        text = str(row.get("text", ""))
        cut = text[:shares[row["id"]]]
        if not cut:
            continue
        out.append({"id": row["id"], "kind": row["kind"], "provenance": row.get("provenance", ""),
                    "text": cut + ("…" if len(text) > len(cut) else "")})
    return out


def context_for(record: dict, *, compact: bool = False, now: dt.datetime | None = None) -> dict:
    now = _now(now)
    budget = COMPACT_EVIDENCE_CHARS if compact else MAX_EVIDENCE_CHARS
    moves = [{"kind": m["kind"], "why": m.get("why", "")[:160], "state": m.get("state"),
              "effect": str(m.get("effect", ""))[:200]} for m in record.get("moves", [])]
    out = {
        "objective": record["objective"],
        "subject": {k: v for k, v in record["subject"].items() if k != "key"},
        "evidence": _evidence_text(record, budget),
        "moves_so_far": moves[-12:],
        "never_repeat": record.get("never_repeat", [])[-12:],
        "people": record.get("people", [])[-8:],
        "catalog": {k: v["does"] for k, v in MOVES.items()},
        "effort_left_today_s": max(0.0, EFFORT_DAY_S - _spent_today(record, now)),
        "today": now.strftime("%Y-%m-%d"),
    }
    if not compact:
        out["previous_understanding"] = record.get("understanding", "")[:800]
        out["what_has_happened_elsewhere"] = lessons(now=now)
    return out


_CITE_MARK = re.compile(r"\s*\[(?:e\d+)(?:\s*,\s*e\d+)*\]")


def _clean(text, limit: int) -> str:
    """One line, bounded, and without the model's own citation marks: the
    second live pass wrote "[e2]" into a reason that a notice then showed
    him. The citations live in `cites`; the words are for a person."""
    return " ".join(_CITE_MARK.sub("", str(text or "")).split())[:limit]


def validate(proposal: dict, record: dict, *, quoting: bool = False) -> tuple[dict, list[dict]]:
    """The model's answer, held to the rules. Returns (kept proposal, dropped moves).

    `quoting` is the stricter line her own model is held to: a move that
    does something (not wait, leave or close) must quote the evidence it
    cites, verbatim. The first pass on her own model alone (2026-09-22,
    557 s) filed a suggestion that suggested nothing - fluent filler in
    the right shape - and a quote is the one thing filler cannot supply.
    """
    if not isinstance(proposal, dict):
        raise ValueError("the answer is not an object")
    held = {row["id"] for row in record.get("evidence", [])}
    never = set(record.get("never_repeat", []))
    kept, dropped = [], []
    effort = proposal.get("effort") if isinstance(proposal.get("effort"), dict) else {}
    try:
        minutes = max(0, min(60, int(float(effort.get("minutes", 0)))))
    except (TypeError, ValueError):
        minutes = 0
    for raw in (proposal.get("moves") or [])[:MAX_MOVES_PER_PASS * 2]:
        if not isinstance(raw, dict):
            continue
        kind = _clean(raw.get("kind"), 60)
        why = _clean(raw.get("why"), 400)
        cites = [c for c in (raw.get("cites") or []) if isinstance(c, str) and c in held]
        detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else {}
        if len(why) < MIN_WHY_CHARS:
            dropped.append({"kind": kind, "why": "it gives no reason it would help"})
            continue
        if not cites:
            dropped.append({"kind": kind, "why": "it cites no evidence she holds"})
            continue
        if quoting and kind not in ("wait", "leave", "close") and not _quoted(raw, record, cites):
            dropped.append({"kind": kind, "why": "it quotes nothing from the evidence it cites"})
            continue
        if kind not in MOVES:
            detail = {"idea": _clean(raw.get("kind"), 200) + ": " + _clean(detail.get("idea") or why, 400)}
            kind = "suggest"
        move = {"kind": kind, "why": why, "cites": cites, "detail": {}}
        if kind == "look":
            url = _clean(detail.get("url"), 500)
            query = _clean(detail.get("query"), 200)
            if not (url.startswith("http") or query):
                dropped.append({"kind": kind, "why": "it names nothing to read or search"})
                continue
            move["detail"] = {"question": _clean(detail.get("question") or why, 300),
                              "url": url if url.startswith("http") else "", "query": query}
            target = f"look:{url or query}"
        elif kind == "note_to_person":
            grounded = [c for c in (detail.get("grounded_on") or []) if c in held]
            to = _clean(detail.get("to"), 200)
            text = _clean(detail.get("text"), MAX_NOTE_CHARS)
            if not (to and text):
                dropped.append({"kind": kind, "why": "it names no person or has no text"})
                continue
            if not grounded:
                dropped.append({"kind": kind, "why": "its claims stand on no evidence she holds"})
                continue
            move["detail"] = {"to": to, "subject": _clean(detail.get("subject"), 150),
                              "text": text, "grounded_on": grounded}
            target = f"note_to_person:{to.casefold()}"
        elif kind == "write":
            grounded = [c for c in (detail.get("grounded_on") or []) if c in held]
            title = _clean(detail.get("title"), 120)
            text = str(detail.get("text") or "").strip()[:MAX_DOC_CHARS]
            if not (title and text):
                dropped.append({"kind": kind, "why": "it has no title or no text"})
                continue
            if not grounded:
                dropped.append({"kind": kind, "why": "its claims stand on no evidence she holds"})
                continue
            move["detail"] = {"title": title, "text": text, "grounded_on": grounded}
            target = f"write:{title.casefold()}"
        elif kind == "wait":
            try:
                days = max(1, min(30, int(float(detail.get("days", 3)))))
            except (TypeError, ValueError):
                days = 3
            move["detail"] = {"days": days, "for": _clean(detail.get("for") or why, 200)}
            target = "wait"
        elif kind == "suggest":
            move["detail"] = {"idea": _clean(detail.get("idea") or why, 600)}
            target = f"suggest:{move['detail']['idea'][:60].casefold()}"
        else:
            target = kind
        if target in never or any(m.get("target") == target and m.get("state") != "failed"
                                  for m in record.get("moves", [])):
            dropped.append({"kind": kind, "why": "it was already done, or he said never again"})
            continue
        move["target"] = target
        kept.append(move)
        if len(kept) >= MAX_MOVES_PER_PASS:
            break
    stop = proposal.get("stop") if isinstance(proposal.get("stop"), dict) else {}
    clean = {
        "understanding": _clean(proposal.get("understanding"), 1200),
        "uncertainty": [_clean(u, 200) for u in (proposal.get("uncertainty") or [])
                        if isinstance(u, str) and u.strip()][:6],
        "strategy": _clean(proposal.get("strategy"), 500),
        "effort": {"minutes": minutes, "why": _clean(effort.get("why"), 300)},
        "moves": kept,
        "stop": {"done": bool(stop.get("done")), "why": _clean(stop.get("why"), 300)},
    }
    return clean, dropped


def _gateway_think():
    """The default thinker: the frontier through the gateway when it is up,
    her own model with the compact brief when it is not."""
    from aletheia import local_model_pool, reasoner, reasoning_gateway, work_states

    def think(record: dict, now: dt.datetime) -> tuple[dict, dict]:
        validator = lambda out: validate(out, record)[0]
        # her own model is held to the quoting line; `reason` re-validates
        # the same way once it knows which rung answered
        quoting = lambda out: validate(out, record, quoting=True)[0]
        ask = "What, if anything, would help this opportunity along?"
        try:
            if reasoning_gateway.frontier_available():
                got = reasoning_gateway.reason_json(
                    BRIEF, ask, context=context_for(record, now=now), policy="standard",
                    validator=validator, attention=work_states.BACKGROUND,
                    max_context_bytes=MAX_CONTEXT_BYTES)
                provider = str(got.provider or "")
                return got.output, {"provider": provider[:120], "local": provider.startswith("ollama:")}
            if not reasoning_gateway.frontier_off() and reasoner.codex_available()[0]:
                # The job hunt's own chain (his 2026-09-13 ruling: Claude,
                # then Codex on his ChatGPT subscription, then her own
                # model). The gateway carries no Codex rung, and while
                # Claude rests this is the difference between a pass and
                # a day of "nobody could think". Codex saying it is out is
                # a reason to go on down, not to stop: measured 2026-09-22,
                # "Codex is out until 1:04 AM" escaped and ended the pass.
                try:
                    out = reasoner.codex_json(BRIEF, ask, context=context_for(record, now=now),
                                              validator=validator, max_context_bytes=MAX_CONTEXT_BYTES)
                    return out, {"provider": reasoner.CODEX_PROVIDER, "local": False}
                except reasoner.ReasonerUnavailable:
                    pass
            room, why = reasoner.local_allowed()
            if not room:
                # Asking a starved model is a timeout, not an answer.
                raise reasoner.ReasonerUnavailable(f"my own model has no room to think: {why}")
            got = reasoning_gateway.local_json(
                    COMPACT_BRIEF, "What, if anything, would help this opportunity?",
                    context=context_for(record, compact=True, now=now), role="fast",
                    validator=quoting, attention=work_states.BACKGROUND,
                    timeout_s=work_states.local_ceiling_s(work_states.BACKGROUND),
                    think_override=False)
        except local_model_pool.LocalPoolUnavailable as exc:
            # Her own model timing out, or stepping aside for a conversation,
            # is "nobody could think just now" - the same thing as a spent
            # subscription, and the same short wait. The first live turn
            # (2026-09-21, Claude and Codex both resting, her model starved
            # of memory) read it as a failed pass and parked four
            # opportunities for six hours.
            raise reasoner.ReasonerUnavailable(f"my own model could not answer: {exc}") from exc
        provider = str(got.provider or "")
        return got.output, {"provider": provider[:120], "local": provider.startswith("ollama:")}
    return think


def reason(oid: str, *, think=None, now: dt.datetime | None = None) -> dict:
    """One reasoning pass: update understanding, strategy and effort, and
    file the moves the model proposed (validated). Executes nothing."""
    now = _now(now)
    think = think or _gateway_think()
    record = load(oid)
    raw, drafted_by = think(record, now)
    clean, dropped = validate(raw, record, quoting=bool(drafted_by.get("local")))
    with _LOCK:
        record = load(oid)
        record["understanding"] = clean["understanding"] or record.get("understanding", "")
        record["uncertainty"] = clean["uncertainty"]
        record["strategy"] = clean["strategy"] or record.get("strategy", "")
        allowed = min(clean["effort"]["minutes"] * 60.0,
                      max(0.0, EFFORT_DAY_S - _spent_today(record, now)))
        record["effort"].update({"allowed_s": allowed, "because": clean["effort"]["why"]})
        filed = []
        for move in clean["moves"]:
            move.update({"id": f"m{len(record['moves']) + 1}", "state": "proposed",
                         "at": _stamp(now), "drafted_by": drafted_by, "effect": ""})
            record["moves"].append(move)
            filed.append(move)
        record["last_pass"] = {"at": _stamp(now), "dropped": dropped, "stop": clean["stop"],
                               "drafted_by": drafted_by}
        record["history"].append({"at": _stamp(now),
                                  "what": f"reasoned: {len(filed)} move(s), {len(dropped)} dropped"})
        if clean["stop"]["done"] and not filed:
            record["state"] = PARKED
            record["next_look"] = {"at": _stamp(now + dt.timedelta(days=7)),
                                   "because": clean["stop"]["why"] or "nothing more would help now"}
        save(record)
    journal.append("event", f"opportunity:{oid}",
                   (f"thought about it: {clean['strategy'][:160]}" if clean["strategy"] else
                    "thought about it") + (f"; {len(filed)} move(s) proposed" if filed else
                                           "; nothing more to do now"),
                   actor=ACTOR)
    return {"record": record, "moves": filed, "dropped": dropped, "stop": clean["stop"]}


# ---------------------------------------------------------------- acting

def _spent_today(record: dict, now: dt.datetime) -> float:
    effort = record.get("effort") or {}
    if effort.get("day") != now.strftime("%Y-%m-%d"):
        return 0.0
    return float(effort.get("spent_s") or 0.0)


def _spend(record: dict, seconds: float, now: dt.datetime) -> None:
    today = now.strftime("%Y-%m-%d")
    effort = record.setdefault("effort", {})
    if effort.get("day") != today:
        effort["day"], effort["spent_s"] = today, 0.0
    effort["spent_s"] = float(effort.get("spent_s") or 0.0) + float(seconds)


def _do_look(record: dict, move: dict, now: dt.datetime) -> dict:
    detail = move["detail"]
    if detail.get("url"):
        from aletheia import browse
        page = browse.read_page(detail["url"])
        text = f"{page.get('title', '')}\n{page.get('text', '')}".strip()
        source = detail["url"]
    else:
        from aletheia import research
        page = research.http_search(detail["query"])
        if page.get("error"):
            raise PursuitError(f"the search could not run: {page['error']}")
        text = f"{page.get('title', '')}\n{page.get('text', '')}".strip()
        source = f"search: {detail['query']}"
    if not text:
        raise PursuitError("the page had no text to read")
    eid = add_evidence(record, "looked", text[:6000], source=source, provenance=UNTRUSTED, now=now)
    return {"state": "done", "effect": f"kept what it said as {eid}", "evidence": eid}


def _address_of(to: str) -> tuple[str, str]:
    """(email, name) for `to`, from an address in the words or his contacts."""
    hit = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", to)
    if hit:
        return hit.group(0), to.replace(hit.group(0), "").strip(" <>()") or hit.group(0)
    try:
        from aletheia import contacts
        contact = contacts.resolve(to)
        return contacts.primary_email(contact), contact.get("display_name") or to
    except Exception:
        return "", to


def _do_note(record: dict, move: dict, now: dt.datetime) -> dict:
    detail = move["detail"]
    address, name = _address_of(detail["to"])
    grounded = ", ".join(detail.get("grounded_on", []))
    from aletheia import mail
    ok, why = mail.available()
    if address and ok:
        subject = detail.get("subject") or f"About {record['subject'].get('name', 'this')}"
        draft = mail.draft(address, subject, detail["text"], requested_via="pursuit")
        return {"state": "waiting for his yes", "handle": draft.get("id", ""),
                "effect": f"drafted an email to {name}; it goes when he says yes (stands on {grounded})"}
    # Nobody to send it through: the words still reach him, as a suggestion.
    from aletheia import notifications
    reason = (f"no address for {name}" if not address else f"mail is not set up ({why})")
    notifications.publish(
        f"A note worth sending to {name}",
        f"{detail['text']}\n\n— {move['why']} ({reason}, so it is yours to send.)",
        priority="NORMAL", source="pursuit", dedupe_key=f"pursuit-note:{record['id']}:{move['id']}",
        related={"opportunity": record["id"]})
    return {"state": "handed to him", "effect": f"could not send it myself ({reason}); left the words with him"}


def _do_write(record: dict, move: dict, now: dt.datetime) -> dict:
    from aletheia import autonomy, tools, workspace
    detail = move["detail"]
    slug = re.sub(r"[^a-z0-9]+", "-", detail["title"].casefold()).strip("-")[:60] or "note"
    folder = workspace.root() / "opportunities" / record["id"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.md"
    body = (f"# {detail['title']}\n\n{detail['text']}\n\n---\n"
            f"Written for: {record['subject'].get('name', '')}. Stands on evidence "
            f"{', '.join(detail.get('grounded_on', []))}. Why: {move['why']}\n")
    path.write_text(body, encoding="utf-8")
    autonomy.record(tool="opportunity.write", args={"path": str(path)},
                    consequence=tools.REVERSIBLE_LOCAL,
                    said=f"wrote {detail['title']} into the workspace",
                    undo={"how": "none", "why": "a file in her workspace; delete it to undo"})
    return {"state": "done", "effect": f"wrote {path.name} in the workspace", "handle": str(path)}


def _do_wait(record: dict, move: dict, now: dt.datetime) -> dict:
    days = move["detail"]["days"]
    record["next_look"] = {"at": _stamp(now + dt.timedelta(days=days)), "because": move["detail"]["for"]}
    return {"state": "done", "effect": f"looking again in {days} day{'s' if days != 1 else ''}"}


def _do_leave(record: dict, move: dict, now: dt.datetime) -> dict:
    record["state"] = PARKED
    record["next_look"] = {"at": _stamp(now + dt.timedelta(days=14)), "because": move["why"]}
    return {"state": "done", "effect": "left it alone until something happens"}


def _do_close(record: dict, move: dict, now: dt.datetime) -> dict:
    record["state"] = CLOSED
    record["outcome"] = record.get("outcome") or {"kind": "dropped", "note": move["why"], "at": _stamp(now)}
    return {"state": "done", "effect": "stopped pursuing it"}


def _do_suggest(record: dict, move: dict, now: dt.datetime) -> dict:
    from aletheia import notifications
    notifications.publish(
        f"An idea for {record['subject'].get('name', 'an opportunity')}",
        f"{move['detail']['idea']}\n\n— {move['why']}",
        priority="NORMAL", source="pursuit", dedupe_key=f"pursuit-idea:{record['id']}:{move['id']}",
        related={"opportunity": record["id"]})
    return {"state": "handed to him", "effect": "told him the idea; it is his to take up"}


DEFAULT_DOERS = {"look": _do_look, "note_to_person": _do_note, "write": _do_write,
                 "wait": _do_wait, "leave": _do_leave, "close": _do_close, "suggest": _do_suggest}


def act(oid: str, move_id: str, *, doers: dict | None = None, now: dt.datetime | None = None) -> dict:
    """Carry out ONE proposed move through its door. Never raises out."""
    from aletheia import policy
    policy.ensure_not_halted()
    now = _now(now)
    doers = {**DEFAULT_DOERS, **DOERS, **(doers or {})}
    record = load(oid)
    move = next((m for m in record["moves"] if m["id"] == move_id), None)
    if move is None or move.get("state") != "proposed":
        return {"state": "skipped", "effect": "not a proposed move"}
    doer = doers.get(move["kind"])
    started = time.monotonic()
    if doer is None:
        result = {"state": "handed to him",
                  "effect": f"she has no door for {move['kind']} here; told him instead"}
        try:
            from aletheia import notifications
            notifications.publish(f"Something she would do for {record['subject'].get('name', 'this')}",
                                  f"{move['why']}", priority="NORMAL", source="pursuit",
                                  dedupe_key=f"pursuit-nodoor:{oid}:{move_id}",
                                  related={"opportunity": oid})
        except Exception:
            pass
    else:
        try:
            result = doer(record, move, now)
        except policy.Halted:
            raise
        except Exception as exc:
            result = {"state": "failed", "effect": f"could not: {type(exc).__name__}: {exc}"[:300]}
            try:
                from aletheia import demand
                demand.record_attempt("opportunity.pursue", move["why"], "NEEDS_YOU",
                                      detail=result["effect"], source="pursuit")
            except Exception:
                pass
    seconds = time.monotonic() - started
    with _LOCK:
        fresh = load(oid)
        # the doer may have changed the record in memory (state, next_look,
        # evidence); carry those, then stamp the move
        for key in ("state", "next_look", "outcome", "evidence"):
            fresh[key] = record.get(key, fresh.get(key))
        for stored in fresh["moves"]:
            if stored["id"] == move_id:
                stored.update({"state": result.get("state", "done"),
                               "effect": result.get("effect", ""),
                               "handle": result.get("handle", ""), "done_at": _stamp(now)})
                if result.get("state") in ("done", "sent", "waiting for his yes", "handed to him"):
                    fresh["never_repeat"] = sorted(set(fresh.get("never_repeat", []) + [move["target"]]))
        _spend(fresh, seconds, now)
        fresh["history"].append({"at": _stamp(now), "what": f"{move['kind']}: {result.get('effect', '')}"[:220]})
        save(fresh)
    journal.append("action", f"opportunity:{oid}", f"{move['kind']} — {result.get('effect', '')}",
                   actor=ACTOR)
    return result


def refresh_moves(oid: str, *, now: dt.datetime | None = None) -> list[dict]:
    """A move that waited on his yes: did it go? Read from its own store."""
    now = _now(now)
    changed = []
    with _LOCK:
        record = load(oid)
        for move in record["moves"]:
            if move.get("state") != "waiting for his yes" or not move.get("handle"):
                continue
            try:
                from aletheia import policy
                approval = policy.load(move["handle"])
            except Exception:
                continue
            state = str(approval.get("state", ""))
            if state == "APPROVED":
                move["state"], move["effect"] = "sent", move["effect"] + " — he said yes"
            elif state in ("DENIED", "EXPIRED"):
                move["state"], move["effect"] = "declined", move["effect"] + f" — {state.lower()}"
            else:
                continue
            changed.append(move)
            record["history"].append({"at": _stamp(now), "what": f"{move['kind']}: {move['state']}"})
        if changed:
            save(record)
    return changed


def pass_once(oid: str, *, think=None, doers: dict | None = None,
              now: dt.datetime | None = None) -> dict:
    """Reason about one opportunity, then carry out what may run inside
    the effort it was judged worth. Returns what happened, in words."""
    from aletheia import policy
    policy.ensure_not_halted()
    now = _now(now)
    refresh_moves(oid, now=now)
    out = reason(oid, think=think, now=now)
    record = out["record"]
    done = []
    for move in out["moves"]:
        fresh = load(oid)
        if fresh["state"] == CLOSED:
            break
        if _spent_today(fresh, now) >= max(fresh["effort"].get("allowed_s", 0.0), PASS_COST_S) \
                and move["kind"] not in ("wait", "leave", "close"):
            break
        done.append({"move": move["kind"], **act(oid, move["id"], doers=doers, now=now)})
    with _LOCK:
        fresh = load(oid)
        _spend(fresh, PASS_COST_S, now)
        if fresh["state"] == OPEN and not any(d.get("state") == "done" and d["move"] == "wait"
                                              for d in done):
            # No date was chosen: look again tomorrow unless something happens
            # first, or when the day's effort is back.
            fresh["next_look"] = {"at": _stamp(now + dt.timedelta(days=1)),
                                  "because": "the next look, unless something happens first"}
        save(fresh)
    return {"id": oid, "strategy": record.get("strategy", ""), "did": done,
            "dropped": out["dropped"], "stop": out["stop"]}


def due(*, now: dt.datetime | None = None) -> list[dict]:
    now = _now(now)
    rows = []
    for record in all_opportunities(OPEN):
        when = _parse((record.get("next_look") or {}).get("at") or "")
        if when is None or when <= now:
            rows.append(record)
    rows.sort(key=lambda r: (r.get("next_look") or {}).get("at") or "")
    return rows


def tick(*, limit: int = 2, think=None, doers: dict | None = None,
         now: dt.datetime | None = None) -> list[dict]:
    """The beat: a pass over each opportunity that is due, a few at a time.
    A thinker that cannot think leaves the opportunity due for later."""
    from aletheia import policy, reasoner
    policy.ensure_not_halted()
    now = _now(now)
    out = []
    for record in due(now=now)[:limit]:
        try:
            out.append(pass_once(record["id"], think=think, doers=doers, now=now))
        except policy.Halted:
            raise
        except reasoner.ReasonerUnavailable as exc:
            journal.append("event", f"opportunity:{record['id']}",
                           f"could not think about it just now: {exc}", actor=ACTOR)
            with _LOCK:
                fresh = load(record["id"])
                fresh["next_look"] = {"at": _stamp(now + dt.timedelta(minutes=30)),
                                      "because": "nobody could think just now"}
                save(fresh)
            break
        except Exception as exc:
            journal.append("alert", f"opportunity:{record['id']}",
                           f"a pass failed: {type(exc).__name__}: {exc}", actor=ACTOR)
            with _LOCK:
                fresh = load(record["id"])
                fresh["next_look"] = {"at": _stamp(now + dt.timedelta(hours=6)),
                                      "because": "the last pass failed"}
                save(fresh)
    return out


# ---------------------------------------------------------------- words

def _first_sentence(text: str, limit: int = 220) -> str:
    """Model prose, one sentence, through the one door for speech. The
    first live pass produced five sentences of shorthand for a room."""
    from aletheia import speech
    clean = speech.spoken_prose(str(text or ""))
    first = re.split(r"(?<=[.!?])\s+", clean, maxsplit=1)[0].strip()
    return first[:limit].rstrip(" ,;:.") if first else ""


def spoken(record: dict) -> str:
    name = record["subject"].get("name", record["id"])
    said = f"{name}: "
    if record.get("state") == CLOSED:
        outcome = record.get("outcome") or {}
        return said + f"closed — {outcome.get('kind', 'dropped')}" + (
            f", {outcome['note']}" if outcome.get("note") else "")
    if record.get("strategy"):
        said += _first_sentence(record["strategy"]) or "thought about"
    else:
        said += "not thought about yet"
    last = [m for m in record.get("moves", []) if m.get("state") not in ("proposed",)]
    if last:
        m = last[-1]
        said += f". Last: {m['kind'].replace('_', ' ')} — {m.get('effect', '')}"
    nxt = record.get("next_look") or {}
    if record.get("state") == PARKED:
        said += ". Left alone until something happens"
    elif nxt.get("at"):
        said += f". Next look {str(nxt['at'])[:10]}"
    return said + "."


def status() -> list[str]:
    return [spoken(r) for r in all_opportunities() if r.get("state") != CLOSED]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Opportunities she is pursuing, one at a time.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    show = sub.add_parser("show"); show.add_argument("which")
    t = sub.add_parser("tick"); t.add_argument("--limit", type=int, default=2)
    o = sub.add_parser("outcome"); o.add_argument("which"); o.add_argument("kind", choices=OUTCOMES)
    o.add_argument("note", nargs="?", default="")
    args = ap.parse_args(argv)
    if args.cmd in (None, "list"):
        rows = status()
        print("\n".join(rows) if rows else "Nothing being pursued.")
        return 0
    if args.cmd == "show":
        record = find(args.which)
        if not record:
            print("no such opportunity"); return 1
        print(json.dumps(record, indent=2)); return 0
    if args.cmd == "tick":
        for out in tick(limit=args.limit):
            print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "outcome":
        record = find(args.which)
        if not record:
            print("no such opportunity"); return 1
        print(spoken(record_outcome(record["id"], args.kind, note=args.note)))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
