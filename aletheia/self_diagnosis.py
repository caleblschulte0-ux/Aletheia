"""Why did that fail? Her own answer, from the record, her history and her code.

The brief (docs/JARVIS_BRIEF.md §2): "changing her running code stays a
different privilege, progressing inspect -> diagnose -> propose -> branch ->
patch -> tests -> stronger-model review -> operator/standing policy ->
merge." This module is the first five steps and stops there, in code:

    diagnose(failure)     READ. Gathers the failure (a browser mission's stop,
                          an application record, a journal alert, a failing
                          test's output), recalls similar failures and past
                          fixes from the semantic index, finds the code that
                          raised it with the read-only repo tools, and says:
                          BOUNDARY (something outside the code rightly
                          stopped it) or DEFECT (the code did the wrong
                          thing), where, on what evidence, how sure.
    propose_patch(...)    A RECORD. Diagnosis + unified diff + suggested tests,
                          written under private state. Applies nothing.
    try_patch(proposal)   A THROWAWAY WORKTREE. A local branch in a separate
                          directory outside the live checkout, the diff
                          applied there, ONLY the named tests run there, the
                          worktree removed. Never the live checkout, never a
                          push, never a merge: there is no code path here that
                          does any of those, and `assert_not_live` refuses a
                          worktree anywhere inside the repository she runs.

WHO THINKS. Gathering and the first classification are rules, so a
diagnosis exists with no model at all. `think` (her local model through
`local_model_pool`) may refine it, and may only cite evidence and code
locations that were actually gathered - anything else is dropped and the
confidence capped. A stronger reviewer is optional and goes through the
existing `reasoning_gateway` (policy "critical", the subscriptions); its
verdict is stored BESIDE the local diagnosis under `provenance.reviewer`,
never over it. Code proposals reaching a merge remain the subscriptions'
and his (CLAUDE.md, "Repositories stay with the subscriptions"): nothing
here merges, and `project_merge` still refuses Aletheia's own code.

NOT KEYED TO ONE GOAL. A failure is resolved by a table of resolvers
(`RESOLVERS`: missions, applications, journal, tests, free text through the
general ledger), and the boundary vocabulary names kinds of wall (a
CAPTCHA, an account, a code, his answer, a rule), not sites or employers.

    python -m aletheia.self_diagnosis diagnose "apply-81f9d7e2" [--think] [--review]
    python -m aletheia.self_diagnosis propose "mission:bm-..." [--think] [--diff file]
    python -m aletheia.self_diagnosis try patch-1a2b3c4d5e --tests tests.test_x
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

BOUNDARY = "boundary"
DEFECT = "defect"
UNCLEAR = "unclear"
KINDS = (BOUNDARY, DEFECT, UNCLEAR)

MAX_EVIDENCE = 12
MAX_CODE_READS = 3
CODE_CONTEXT_LINES = 24
MAX_SEARCHES = 8
TEST_TIMEOUT_S = 600
THINK_TIMEOUT_S = 240.0

#: Walls outside the code, by the words that name them. Order matters: the
#: first that matches names the boundary.
BOUNDARY_SIGNS: tuple[tuple[str, re.Pattern], ...] = (
    ("a CAPTCHA, which she never solves", re.compile(r"\b(?:h?captcha|recaptcha|turnstile|bot check)\b", re.I)),
    ("spending money, which she never does", re.compile(r"\bspend(?:s|ing)? money\b|\bwould spend\b", re.I)),
    ("an account or sign-in wall", re.compile(r"\bNEEDS_ACCOUNT\b|\b(?:sign[ -]?in|log[ -]?in|create an account|account wall)\b", re.I)),
    ("a verification code only he receives", re.compile(r"\bverification code\b|\bone[- ]time (?:code|password)\b|\b2fa\b", re.I)),
    ("the site's terms forbid automation", re.compile(r"\bMANUAL_ONLY\b|\bterms forbid\b", re.I)),
    ("questions only he can answer", re.compile(r"\bNEEDS_YOU\b|\bAWAITING_YOU\b|only you can answer|questions? only he|needs \d+ answers? from you", re.I)),
    ("his approval, which is still pending", re.compile(r"\bAWAITING_APPROVAL\b|\bwaiting for (?:his|your) (?:ok|approval|yes)\b", re.I)),
    ("the kill switch: she is halted", re.compile(r"\bhalted\b", re.I)),
    ("the site refused it", re.compile(r"\bREJECTED\b|handed it back", re.I)),
)
#: Signs of the code doing the wrong thing. A crash-shaped exception beats a
#: boundary word: a KeyError while reading a CAPTCHA page is still a KeyError.
DEFECT_SIGNS = re.compile(
    r"Traceback|\b(?:TypeError|KeyError|AttributeError|NameError|IndexError|AssertionError|"
    r"UnboundLocalError|ImportError|ModuleNotFoundError|RecursionError|ZeroDivisionError|"
    r"JSONDecodeError|UnicodeDecodeError)\b|\bFAIL:|\bERROR: test|unexpected(?:ly)?\b|crash", re.I)
SOFT_FAILURE = re.compile(r"\b(?:failed|error|timed? ?out|took longer|could not|couldn't|refused)\b", re.I)
_EXC_NAME = re.compile(r"\b([A-Z][A-Za-z]+(?:Error|Exception|Refused|Unavailable))\b")
_TEST_NAME = re.compile(r"^tests(?:[./][A-Za-z0-9_]+)+(?:\.py)?(?:::[A-Za-z0-9_.]+)?$")

#: Paths a patch may not quietly touch: the gates and the registries. A
#: proposal that changes one says so in its record, in capitals.
AUTHORITY_PATHS = ("config/", "aletheia/policy.py", "aletheia/agent_session.py", "aletheia/tools.py",
                   "aletheia/project_merge.py", "aletheia/authority.py", "aletheia/secret_",
                   "aletheia/access.py", "aletheia/intercom.py", "aletheia/webtask.py",
                   "aletheia/sensitivity.py", ".github/")


# ---- private-state locations ---------------------------------------------------

def proposals_dir() -> Path:
    from aletheia import stateio
    return stateio.private_dir("patch-proposals")


def worktrees_root() -> Path:
    """Where throwaway worktrees go: the system temp directory, never the
    repository. A function so tests can point it somewhere hostile."""
    override = os.environ.get("ALETHEIA_PATCH_WORKTREES", "").strip()
    return Path(override) if override else Path(tempfile.gettempdir()) / "aletheia-patch-worktrees"


def _now() -> str:
    from aletheia import stateio
    return stateio.utcnow()


def _clean(text: Any) -> str:
    from aletheia import sensitivity
    return sensitivity.clean(str(text if text is not None else ""))


def _short(text: Any, limit: int = 400) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "..."


# ---- resolving a failure --------------------------------------------------------

def _app_failure(record: dict) -> dict:
    from aletheia import state_tools
    summary = state_tools.summarise_record(record)
    parts = [f"state {record.get('state')}"]
    for key in ("failure", "why", "say", "captcha_note", "closed_because"):
        if record.get(key):
            parts.append(f"{key}: {record.get(key)}")
    if summary.get("questions_waiting"):
        parts.append("questions waiting: " + "; ".join(summary["questions_waiting"]))
    if summary.get("click_evidence"):
        parts.append("click evidence: " + json.dumps(summary["click_evidence"], ensure_ascii=False))
    if summary.get("result"):
        parts.append("result: " + json.dumps(summary["result"], ensure_ascii=False))
    return {"kind": "application", "ref": record.get("id"), "state": record.get("state"),
            "title": f"{record.get('job_title') or ''} ({record.get('company') or ''})".strip(),
            "text": _clean(" | ".join(parts)), "record": summary}


def _mission_failure(record: dict) -> dict:
    boundary = record.get("boundary") or {}
    parts = [f"state {record.get('state')}"]
    if boundary:
        parts.append("stopped at: " + json.dumps({k: boundary.get(k) for k in ("kind", "say", "url", "step", "needs")
                                                   if boundary.get(k)}, ensure_ascii=False))
    history = [str(h.get("did") or "") for h in (record.get("history") or [])][-6:]
    if history:
        parts.append("last steps: " + " | ".join(history))
    submits = [f"{s.get('button')}: {s.get('verdict')}" for s in (record.get("submits") or [])]
    if submits:
        parts.append("submits: " + "; ".join(submits))
    return {"kind": "browser mission", "ref": record.get("id"), "state": record.get("state"),
            "title": str(record.get("goal") or "")[:120], "text": _clean(" | ".join(parts)),
            "record": {"id": record.get("id"), "goal": record.get("goal"), "state": record.get("state"),
                       "boundary": boundary, "last_checkpoint": record.get("last_checkpoint")}}


def resolve_application(ref: str, detail: str = "") -> dict | None:
    from aletheia import apply_run
    wanted = ref.split(":", 1)[1].strip() if ref.lower().startswith("application:") else ref.strip()
    runs = apply_run.all_runs()
    for record in runs:
        if record.get("id") == wanted:
            return _app_failure(record)
    if ref.lower().startswith("application:"):
        from aletheia import semantic_index
        words = set(semantic_index.significant(wanted))
        matched = [r for r in runs if semantic_index._name_hit(words, str(r.get("company") or ""))]
        matched.sort(key=lambda r: (r.get("state") in ("SUBMITTED", "CLOSED"),
                                    str(r.get("submitted_at") or r.get("staged_at") or "")), reverse=False)
        if matched:
            return _app_failure(matched[0])
    return None


def resolve_mission(ref: str, detail: str = "") -> dict | None:
    from aletheia import browser_mission
    wanted = ref.split(":", 1)[1].strip() if ref.lower().startswith("mission:") else ref.strip()
    if not wanted.startswith("bm-"):
        return None
    try:
        return _mission_failure(browser_mission.load(wanted))
    except (OSError, ValueError):
        return None


def resolve_journal(ref: str, detail: str = "") -> dict | None:
    if not ref.lower().startswith("journal:"):
        return None
    from aletheia import journal, semantic_index
    words = semantic_index.significant(ref.split(":", 1)[1])
    rows = [e for e in journal.since(24 * 14) if e.get("kind") in ("alert", "recovery", "event", "action")]
    scored = []
    for entry in rows:
        have = set(semantic_index.tokens(f"{entry.get('subject')} {entry.get('text')}"))
        hits = sum(1 for w in words if w in have)
        if hits and (entry.get("kind") == "alert" or SOFT_FAILURE.search(str(entry.get("text")))):
            scored.append((hits, entry.get("ts", ""), entry))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    entry = scored[0][2]
    return {"kind": "journal entry", "ref": f"journal {entry.get('ts')}", "state": entry.get("kind"),
            "title": str(entry.get("subject") or ""),
            "text": _clean(f"{entry.get('kind')} {entry.get('subject')}: {entry.get('text')}"),
            "record": {k: entry.get(k) for k in ("ts", "kind", "actor", "subject", "text")}}


def resolve_test(ref: str, detail: str = "") -> dict | None:
    name = ref.split(":", 1)[1].strip() if ref.lower().startswith("test:") else ref.strip()
    if not _TEST_NAME.match(name):
        return None
    return {"kind": "failing test", "ref": name, "state": "FAILED",
            "title": name, "text": _clean(detail or f"the test {name} fails"),
            "record": {"test": name, "output": _short(_clean(detail), 1500)}}


def resolve_ledger(ref: str, detail: str = "") -> dict | None:
    """Free words: whatever record in her stores they name, most-recent unfinished first."""
    from aletheia import apply_run, browser_mission, semantic_index
    facts, _unreadable = semantic_index.ledger(ref)
    for fact in facts:
        if fact.get("store") == "browser missions":
            try:
                return _mission_failure(browser_mission.load(str(fact.get("id"))))
            except (OSError, ValueError):
                continue
    finished = ("SUBMITTED", "DONE")
    apps = [f for f in facts if f.get("store") == "applications"]
    apps.sort(key=lambda f: (str((f.get("fact") or {}).get("state")) in finished))
    for fact in apps:
        for record in apply_run.all_runs():
            if record.get("id") == fact.get("id"):
                return _app_failure(record)
    return None


#: Tried in order. The first that recognises the reference wins.
RESOLVERS: tuple[tuple[str, Callable[[str, str], dict | None]], ...] = (
    ("test", resolve_test),
    ("mission", resolve_mission),
    ("application", resolve_application),
    ("journal", resolve_journal),
    ("ledger", resolve_ledger),
)


def resolve(ref: str, detail: str = "") -> dict:
    ref = " ".join(str(ref or "").split())[:300]
    for name, resolver in RESOLVERS:
        try:
            found = resolver(ref, detail)
        except Exception:                                             # noqa: BLE001
            continue
        if found:
            found["resolved_by"] = name
            found["basis"] = "KNOWN"
            return found
    return {"kind": "description", "ref": ref, "state": "", "title": ref,
            "text": _clean(detail or ref), "record": None, "resolved_by": None,
            "basis": "GUESS"}


# ---- gathering evidence -----------------------------------------------------------

def _fragments(text: str) -> list[str]:
    """Literal phrases worth searching the code for: the pieces of a message
    her own code most likely wrote."""
    out: list[str] = []
    for piece in re.split(r"\s+-\s+|[|;:()\[\]{}\"]|\.\s", str(text)):
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z']+", piece)]
        if len(words) < 4:
            continue
        for start in range(0, max(1, len(words) - 3), 3):
            phrase = " ".join(words[start:start + 5])
            if phrase.casefold() not in (p.casefold() for p in out):
                out.append(phrase)
    return out[:MAX_SEARCHES]


def gather_code(failure: dict, *, search: Callable | None = None, read: Callable | None = None,
                symbol: Callable | None = None, recall: Callable | None = None) -> dict:
    """Where in her own code this failure was written, by three routes: the
    message's own words (git grep), exception names (the symbol index), and
    the semantic index over code."""
    from aletheia import repo_tools, semantic_index
    search = search or repo_tools.repo_search
    read = read or repo_tools.repo_read
    symbol = symbol or repo_tools.repo_symbol
    recall = recall or semantic_index.recall
    locations: dict[tuple[str, int], dict] = {}

    def add(path: str, line: int, why: str, weight: float) -> None:
        if not path or path.startswith("tests/") and failure.get("kind") != "failing test":
            weight *= 0.4
        key = (path, int(line))
        row = locations.setdefault(key, {"path": path, "line": int(line), "why": [], "weight": 0.0})
        if why not in row["why"]:
            row["why"].append(why)
        row["weight"] += weight

    text = str(failure.get("text") or "")
    searched = []
    for phrase in _fragments(text):
        try:
            found = search({"query": phrase, "limit": 5})
        except Exception:                                             # noqa: BLE001
            continue
        searched.append({"query": phrase, "matched": found.get("matched", 0)})
        for hit in (found.get("hits") or [])[:5]:
            add(hit["path"], hit["line"], f"contains the message text {phrase!r}", 3.0)
    for name in sorted(set(_EXC_NAME.findall(text)))[:4]:
        try:
            found = symbol({"name": name})
        except Exception:                                             # noqa: BLE001
            continue
        for d in (found.get("definitions") or [])[:3]:
            add(d["path"], d["line"], f"defines {name}", 1.5)
    if failure.get("kind") == "failing test":
        test = str(failure.get("ref") or "")
        leaf = re.split(r"[.:]", test)[-1]
        try:
            for d in (symbol({"name": leaf}).get("definitions") or [])[:2]:
                add(d["path"], d["line"], f"the failing test {leaf}", 4.0)
        except Exception:                                             # noqa: BLE001
            pass
    try:
        hits = recall(f"{failure.get('title', '')} {text}"[:400], sources=["code"], k=4,
                      include_ledger=False)
        for snip in hits.get("snippets") or []:
            where = str(snip.get("where") or "")
            m = re.match(r"^(.+?):(\d+)$", where)
            if m:
                add(m.group(1), int(m.group(2)), "related code found by the index", 1.0)
    except Exception:                                                 # noqa: BLE001
        pass
    ranked = sorted(locations.values(), key=lambda r: -r["weight"])
    reads = []
    for row in ranked[:MAX_CODE_READS]:
        try:
            got = read({"path": row["path"], "start": max(1, row["line"] - CODE_CONTEXT_LINES // 2),
                        "lines": CODE_CONTEXT_LINES})
        except Exception:                                             # noqa: BLE001
            continue
        if got.get("text"):
            reads.append({"path": got["path"], "start": got["start"], "end": got["end"], "text": got["text"]})
    return {"locations": [{**r, "why": "; ".join(r["why"]), "weight": round(r["weight"], 1)}
                          for r in ranked[:8]],
            "reads": reads, "searched": searched}


def classify(failure: dict, code: dict | None = None) -> dict:
    """The rules' verdict: which kind, which boundary, how sure."""
    text = f"{failure.get('state') or ''} {failure.get('text') or ''}"
    boundary = next((name for name, pattern in BOUNDARY_SIGNS if pattern.search(text)), None)
    crash = DEFECT_SIGNS.search(text)
    located = bool(code and code.get("locations"))
    if crash and not boundary:
        return {"kind": DEFECT, "boundary": None, "confidence": 0.6 if located else 0.45,
                "why": f"the failure reads like the code breaking ({crash.group(0)})"}
    if crash and boundary:
        return {"kind": UNCLEAR, "boundary": boundary, "confidence": 0.35,
                "why": (f"it names {boundary}, but also reads like the code breaking "
                        f"({crash.group(0)}); both are possible")}
    if boundary:
        return {"kind": BOUNDARY, "boundary": boundary, "confidence": 0.75 if failure.get("record") else 0.55,
                "why": f"the record names {boundary}, a wall outside the code that stopped it on purpose"}
    if failure.get("kind") == "failing test":
        return {"kind": DEFECT, "boundary": None, "confidence": 0.5,
                "why": "a test that fails is a defect in the code or in the test"}
    if SOFT_FAILURE.search(text):
        return {"kind": UNCLEAR, "boundary": None, "confidence": 0.3,
                "why": "it failed, and nothing in the record says whether the code or the world stopped it"}
    return {"kind": UNCLEAR, "boundary": None, "confidence": 0.2,
            "why": "the record does not say what went wrong"}


Think = Callable[[str, str], "tuple[dict, str]"]

DIAGNOSE_SYSTEM = """You are Thea (Aletheia) diagnosing a failure in YOUR OWN software, from
evidence gathered for you. Reply with ONE JSON object:
{"kind": "boundary" | "defect" | "unclear",
 "summary": "<two plain sentences: what stopped it and why>",
 "likely_location": [{"path": "<a path from CODE>", "line": <int>, "why": "<short>"}],
 "evidence_ids": ["e1", ...],
 "confidence": <0.0-1.0>,
 "next_step": "<the one thing that would move it forward, and whose it is>"}
A BOUNDARY is a wall outside the code that correctly stopped the work (a CAPTCHA,
an account, a code only he receives, his answer or approval, a rule she keeps,
a site refusing). A DEFECT is the code doing the wrong thing. Cite ONLY evidence
ids and code paths shown to you. If the evidence does not decide it, say unclear
with a low confidence. Never invent a file, a line or a fact."""


def _bundle_text(failure: dict, rules: dict, evidence: list[dict], code: dict) -> str:
    lines = [f"FAILURE ({failure.get('kind')} {failure.get('ref')}): {_short(failure.get('title'), 160)}",
             f"RECORD: {_short(failure.get('text'), 1200)}",
             f"RULES SAY: {rules['kind']} - {rules['why']}", "EVIDENCE:"]
    for e in evidence:
        lines.append(f"{e['id']} [{e['source']}; {e['basis']}] {e['where']}: {_short(e['text'], 300)}")
    lines.append("CODE:")
    for loc in code.get("locations", [])[:6]:
        lines.append(f"- {loc['path']}:{loc['line']} ({loc['why']})")
    for got in code.get("reads", []):
        lines.append(f"--- {got['path']} lines {got['start']}-{got['end']}\n{got['text'][:1400]}")
    return "\n".join(lines)[:7500]


def _merge_model(diagnosis: dict, output: dict, provider: str, code: dict) -> None:
    """Take what the model said only where it stays inside the evidence."""
    kind = str(output.get("kind") or "").strip().lower()
    known_paths = {loc["path"] for loc in code.get("locations", [])} | {r["path"] for r in code.get("reads", [])}
    evidence_ids = {e["id"] for e in diagnosis["evidence"]}
    dropped = []
    locations = []
    for loc in output.get("likely_location") or []:
        if not isinstance(loc, dict):
            continue
        path = str(loc.get("path") or "")
        if path in known_paths:
            try:
                line = int(loc.get("line") or 0)
            except (TypeError, ValueError):
                line = 0
            locations.append({"path": path, "line": line, "why": _short(loc.get("why"), 200)})
        else:
            dropped.append(path)
    cited = [i for i in (output.get("evidence_ids") or []) if i in evidence_ids]
    try:
        confidence = max(0.0, min(float(output.get("confidence")), 1.0))
    except (TypeError, ValueError):
        confidence = diagnosis["confidence"]
    if dropped:
        confidence = min(confidence, 0.4)
    if kind in KINDS:
        diagnosis["kind"] = kind
    if output.get("summary"):
        diagnosis["summary"] = _short(_clean(output["summary"]), 600)
    if locations:
        diagnosis["likely_location"] = locations
    if cited:
        diagnosis["cited_evidence"] = cited
    if output.get("next_step"):
        diagnosis["next_step"] = _short(_clean(output["next_step"]), 300)
    diagnosis["confidence"] = round(confidence, 2)
    diagnosis["provenance"]["classified_by"] = provider
    if dropped:
        diagnosis["provenance"]["dropped_uncited_locations"] = dropped[:5]


def local_think(timeout_s: float = THINK_TIMEOUT_S) -> Think:
    """Her own model, through the pool (memory check, transport, capture)."""
    def think(system: str, text: str) -> tuple[dict, str]:
        from aletheia import local_model_pool
        run = local_model_pool.run_json(system, text, role="fast", timeout_s=min(timeout_s, 300.0),
                                        think_override=False)
        return run.output, f"ollama:{run.model}"
    return think


def diagnose(failure_ref: str, *, detail: str = "", think: Think | None = None,
             review: bool = False, recall: Callable | None = None,
             code_tools: dict | None = None, reviewer: Callable | None = None) -> dict:
    """A structured diagnosis. Never raises for a failure it cannot find: it
    says what it could and could not see."""
    from aletheia import semantic_index
    started = time.monotonic()
    recall = recall or semantic_index.recall
    failure = resolve(failure_ref, detail)
    query = _short(f"{failure.get('title', '')} {failure.get('text', '')}", 380)
    evidence: list[dict] = []
    if failure.get("record") is not None:
        evidence.append({"id": "e1", "source": failure["kind"], "where": str(failure.get("ref")),
                         "text": _short(failure.get("text"), 600), "basis": "KNOWN"})
    similar: dict = {}
    try:
        similar = recall(query, sources=["journal", "fixes", "sessions", "missions", "applications",
                                         "notifications"], k=6, include_ledger=False)
    except Exception as exc:                                          # noqa: BLE001
        similar = {"snippets": [], "index": f"recall failed ({type(exc).__name__})"}
    for snip in similar.get("snippets") or []:
        if snip.get("where") == failure.get("ref") or str(failure.get("ref")) in str(snip.get("where")):
            continue
        evidence.append({"id": f"e{len(evidence) + 1}", "source": snip.get("source"), "where": snip.get("where"),
                         "text": snip.get("text"), "basis": snip.get("basis", "FOUND IN HISTORY"),
                         "ts": snip.get("ts")})
        if len(evidence) >= MAX_EVIDENCE:
            break
    code = gather_code(failure, recall=recall, **(code_tools or {}))
    for got in code["reads"]:
        evidence.append({"id": f"e{len(evidence) + 1}", "source": "code", "where": f"{got['path']}:{got['start']}",
                         "text": got["text"][:500], "basis": "KNOWN"})
    rules = classify(failure, code)
    diagnosis: dict[str, Any] = {
        "id": "diag-" + hashlib.sha256(f"{failure.get('kind')}|{failure.get('ref')}|{failure.get('text')}"
                                       .encode("utf-8")).hexdigest()[:10],
        "failure": {k: failure.get(k) for k in ("kind", "ref", "state", "title", "text", "resolved_by")},
        "kind": rules["kind"], "boundary": rules["boundary"],
        "summary": rules["why"],
        "likely_location": [{"path": loc["path"], "line": loc["line"], "why": loc["why"]}
                            for loc in code["locations"][:3]],
        "evidence": evidence,
        "similar_history": [{k: s.get(k) for k in ("source", "where", "ts", "basis")}
                            for s in (similar.get("snippets") or [])],
        "index": {k: similar.get(k) for k in ("answered_by", "embedded_fraction", "lexical_because", "index")
                  if similar.get(k) is not None},
        "code_searched": code["searched"],
        "confidence": rules["confidence"],
        "next_step": _next_step(rules),
        "basis": failure["basis"] if failure.get("record") is not None else
        ("FOUND IN HISTORY" if len(evidence) else "GUESS"),
        "provenance": {"gathered_at": _now(), "classified_by": "rules", "reviewer": None},
    }
    if failure.get("record") is None:
        diagnosis["note"] = ("no record in her stores matched that reference, so this rests on the "
                             "description and on history found by search")
        diagnosis["confidence"] = min(diagnosis["confidence"], 0.35)
    if think is not None:
        try:
            output, provider = think(DIAGNOSE_SYSTEM, _bundle_text(failure, rules, evidence, code))
            if isinstance(output, dict):
                _merge_model(diagnosis, output, provider, code)
        except Exception as exc:                                      # noqa: BLE001
            diagnosis["provenance"]["model_failed"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    if review:
        diagnosis["provenance"]["reviewer"] = review_diagnosis(diagnosis, reviewer=reviewer)
    diagnosis["seconds"] = round(time.monotonic() - started, 1)
    return diagnosis


def _next_step(rules: dict) -> str:
    if rules["kind"] == BOUNDARY:
        return (f"nothing to fix in the code: the wall is {rules['boundary']}. Say what remains and "
                "whose it is; a patch is only worth proposing if she stopped later than she should have.")
    if rules["kind"] == DEFECT:
        return "read the likely location, then propose a patch with the tests that should cover it."
    return "look at the record and the code named here before deciding whether it is a wall or a bug."


REVIEW_SYSTEM = """You review a diagnosis another model made of a failure in a personal
assistant's own code. Reply with ONE JSON object:
{"agrees": true|false, "kind": "boundary"|"defect"|"unclear", "comment": "<two sentences>"}
Judge only from the evidence shown. You have no tools and no authority."""


def review_diagnosis(diagnosis: dict, *, reviewer: Callable | None = None) -> dict:
    """A stronger model's second opinion, through the existing gateway, stored
    beside the local diagnosis and marked as the reviewer's."""
    text = json.dumps({k: diagnosis.get(k) for k in ("failure", "kind", "boundary", "summary",
                                                     "likely_location", "evidence", "confidence")},
                      ensure_ascii=False, default=str)[:9000]
    try:
        if reviewer is not None:
            output, provider = reviewer(REVIEW_SYSTEM, text)
        else:
            from aletheia import reasoning_gateway
            result = reasoning_gateway.reason_json(REVIEW_SYSTEM, text, policy="critical", timeout_s=120.0)
            output, provider = result.output, result.provider
    except Exception as exc:                                          # noqa: BLE001
        return {"asked": True, "answered": False, "why": f"{type(exc).__name__}: {str(exc)[:160]}",
                "policy": "critical"}
    return {"asked": True, "answered": True, "provider": provider, "policy": "critical",
            "role": "stronger reviewer (not the author of this diagnosis)",
            "agrees": bool(output.get("agrees")) if isinstance(output, dict) else None,
            "kind": (output or {}).get("kind") if isinstance(output, dict) else None,
            "comment": _short(_clean((output or {}).get("comment")), 500) if isinstance(output, dict) else "",
            "at": _now()}


# ---- proposing a patch --------------------------------------------------------------

_DIFF_FILE = re.compile(r"^(?:---|\+\+\+) (?:[ab]/)?(\S+)", re.M)


def diff_files(diff: str) -> list[str]:
    files = []
    for name in _DIFF_FILE.findall(str(diff or "")):
        if name != "/dev/null" and name not in files:
            files.append(name)
    return files


def check_diff(diff: str, *, git: Callable | None = None) -> dict:
    """Is this a diff of tracked files that applies to HEAD? `git apply
    --check` reads and never writes."""
    from aletheia import repo_tools
    files = diff_files(diff)
    if not files:
        return {"ok": False, "why": "no file headers: not a unified diff", "files": []}
    problems = []
    for name in files:
        try:
            repo_tools._tracked_file(name)
        except repo_tools.RepoError as exc:
            problems.append(str(exc))
    if problems:
        return {"ok": False, "why": "; ".join(problems)[:400], "files": files}
    runner = git or _git_check
    ok, why = runner(diff)
    return {"ok": ok, "why": why, "files": files}


def _git_check(diff: str) -> tuple[bool, str]:
    from aletheia import proc, repo_tools
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    done = subprocess.run(["git", "apply", "--check", "--verbose", "-"], input=diff.encode("utf-8"),
                          capture_output=True, cwd=str(repo_tools.root()), timeout=30, env=env,
                          creationflags=proc.hidden_flags())
    said = (done.stderr or done.stdout).decode("utf-8", "replace").strip().splitlines()
    return done.returncode == 0, (said[-1] if said else "")[:300]


def suggest_tests(files: list[str], *, search: Callable | None = None) -> list[str]:
    """The test modules that import what the patch touches."""
    from aletheia import repo_tools
    search = search or repo_tools.repo_search
    out: list[str] = []
    for name in files:
        if name.startswith("tests/") and name.endswith(".py"):
            out.append(name[:-3].replace("/", "."))
            continue
        if not (name.startswith("aletheia/") and name.endswith(".py")):
            continue
        module = name[len("aletheia/"):-3].replace("/", ".")
        for query in (f"from aletheia import {module}", f"aletheia.{module}", f"import {module}"):
            try:
                found = search({"query": query, "path": "tests", "limit": 30})
            except Exception:                                         # noqa: BLE001
                continue
            for hit in found.get("hits") or []:
                test = hit["path"][:-3].replace("/", ".")
                if hit["path"].endswith(".py") and test not in out:
                    out.append(test)
            if len(out) >= 6:
                break
    return out[:6]


PATCH_SYSTEM = """You propose a SMALL fix to your own code for a diagnosed defect. Reply
with ONE JSON object: {"diff": "<a unified diff against the files shown, with ---/+++
headers and @@ hunks>", "summary": "<one sentence>", "tests": ["tests.test_module", ...]}.
Change as little as possible. Only touch files shown under CODE. If the diagnosis is a
boundary, or you cannot write a correct diff, reply {"diff": "", "summary": "<why not>"}.
This is a proposal: it is never applied without tests and a person."""


def propose_patch(failure_ref: str, *, diff: str = "", tests: list[str] | None = None,
                  summary: str = "", detail: str = "", diagnosis: dict | None = None,
                  think: Think | None = None, drafted_by: str = "", review: bool = False,
                  reviewer: Callable | None = None, check: Callable | None = None,
                  write: bool = True) -> dict:
    """A proposal RECORD. Nothing is applied, branched, pushed or merged."""
    from aletheia import stateio
    diagnosis = diagnosis or diagnose(failure_ref, detail=detail)
    diff = str(diff or "")
    diff_by = drafted_by or ("the asking session's model" if diff else "")
    if not diff and think is not None and diagnosis.get("kind") != BOUNDARY:
        text = (f"DIAGNOSIS: {json.dumps({k: diagnosis.get(k) for k in ('kind', 'summary', 'likely_location')}, ensure_ascii=False)}\n"
                "CODE:\n" + "\n".join(e["text"] for e in diagnosis["evidence"] if e["source"] == "code"))[:7000]
        try:
            output, provider = think(PATCH_SYSTEM, text)
            diff = str((output or {}).get("diff") or "")
            summary = summary or _short((output or {}).get("summary"), 300)
            tests = tests or [t for t in (output or {}).get("tests") or [] if isinstance(t, str)]
            diff_by = provider
        except Exception as exc:                                      # noqa: BLE001
            diagnosis.setdefault("provenance", {})["patch_model_failed"] = f"{type(exc).__name__}"
    if diff and not diff.endswith("\n"):
        diff += "\n"
    checked = check_diff(diff, git=check) if diff else {"ok": False, "why": "no diff proposed", "files": []}
    files = checked["files"]
    touches = [f for f in files if f.startswith(AUTHORITY_PATHS)]
    wanted_tests = [t for t in (tests or []) if _TEST_NAME.match(str(t))] or suggest_tests(files)
    ident = "patch-" + hashlib.sha256(f"{failure_ref}|{diff}|{summary}".encode("utf-8")).hexdigest()[:10]
    record = {
        "id": ident, "created_at": _now(), "status": "PROPOSED",
        "authority": ("none: this is a proposal. Nothing was applied to her running code, and "
                      "nothing is branched, pushed or merged by writing it."),
        "failure_ref": _clean(failure_ref)[:300],
        "summary": _clean(summary)[:400] or diagnosis.get("summary"),
        "diagnosis": diagnosis,
        "diff": _clean(diff)[:60_000],
        "diff_check": checked,
        "files": files,
        "touches_authority": touches,
        "suggested_tests": wanted_tests,
        "provenance": {"diagnosis_by": diagnosis.get("provenance", {}).get("classified_by"),
                       "diff_by": diff_by or "nobody (no diff was drafted)", "reviewer": None},
    }
    if touches:
        record["warning"] = ("THIS PATCH TOUCHES A GATE OR A REGISTRY (" + ", ".join(touches) +
                             "). Permission to edit code is never permission to widen authority.")
    if not diff:
        record["why_no_diff"] = ("the diagnosis is a boundary, which code does not fix"
                                 if diagnosis.get("kind") == BOUNDARY else
                                 "no diff was supplied or drafted")
    if review and diff:
        record["provenance"]["reviewer"] = review_diagnosis(
            {**diagnosis, "summary": f"{diagnosis.get('summary')} PROPOSED DIFF:\n{diff[:4000]}"},
            reviewer=reviewer)
    if write:
        path = proposals_dir() / f"{ident}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(path, record)
        record["path"] = str(path)
    return record


def load_proposal(ident: str) -> dict:
    from aletheia import stateio
    return stateio.read_json(proposals_dir() / f"{stateio.safe_id(ident, name='proposal id')}.json")


# ---- trying one, somewhere that is not her ----------------------------------------------

class LiveCheckoutRefused(PermissionError):
    """A worktree path that is, or is inside, the checkout she runs from."""


def assert_not_live(path: Path, *, live: Path | None = None) -> Path:
    """THE PATH GUARD. Every write this module makes to code happens under a
    path that passed this, and the repository she runs from never does."""
    from aletheia import repo_tools
    live = Path(live or repo_tools.root()).resolve()
    target = Path(path).resolve()
    if target == live or live in target.parents or target in live.parents:
        raise LiveCheckoutRefused(f"{target} is the live checkout or contains it; a patch is only ever "
                                  "tried in a throwaway worktree outside it")
    return target


def _run_git(args: list[str], cwd: Path, *, timeout: int = 60, input_text: str | None = None) -> tuple[int, str]:
    from aletheia import proc
    if args and args[0] in ("push", "merge", "pull", "fetch", "rebase", "reset", "checkout", "stash"):
        raise LiveCheckoutRefused(f"git {args[0]} is never run by a patch trial")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=timeout, env=env,
                          input=input_text.encode("utf-8") if input_text is not None else None,
                          creationflags=proc.hidden_flags())
    out = (done.stdout + done.stderr).decode("utf-8", "replace")
    return done.returncode, out


def try_patch(ident: str, *, tests: list[str] | None = None, git: Callable | None = None,
              run_tests: Callable | None = None, keep_branch: bool = True) -> dict:
    """Apply a proposal in a throwaway worktree and run ONLY the named tests.
    Returns the updated proposal record."""
    from aletheia import journal, repo_tools, stateio
    record = load_proposal(ident)
    if not record.get("diff"):
        raise ValueError("that proposal has no diff to try")
    names = [t for t in (tests or record.get("suggested_tests") or []) if _TEST_NAME.match(str(t))]
    if not names:
        raise ValueError("name the tests to run: a trial never runs the whole suite")
    live = repo_tools.root().resolve()
    root = assert_not_live(worktrees_root(), live=live)
    where = assert_not_live(root / ident, live=live)
    git = git or _run_git
    branch = f"thea/proposal-{ident}"
    trial: dict[str, Any] = {"tried_at": _now(), "worktree": str(where), "branch": branch, "tests": names}
    root.mkdir(parents=True, exist_ok=True)
    code, out = git(["worktree", "add", "-B", branch, str(where), "HEAD"], live)
    if code != 0:
        trial.update({"applied": False, "why": _short(out, 300)})
        return _save_trial(record, trial)
    try:
        assert_not_live(where, live=live)
        code, out = git(["apply", "--whitespace=nowarn", "-"], where, input_text=record["diff"])
        trial["applied"] = code == 0
        if code != 0:
            trial["why"] = _short(out, 300)
            return _save_trial(record, trial)
        git(["-c", "user.name=Thea (proposal)", "-c", "user.email=thea@localhost", "commit", "-a",
             "-m", f"proposal {ident} (never merged by her)"], where)
        runner = run_tests or _run_named_tests
        result = runner(names, where)
        trial.update(result)
    finally:
        git(["worktree", "remove", "--force", str(where)], live)
        if not keep_branch:
            git(["branch", "-D", branch], live)
    try:
        journal.append("action", "self-diagnosis",
                       f"tried patch proposal {ident} in a throwaway worktree: tests "
                       f"{'passed' if trial.get('passed') else 'did not pass'}; nothing merged",
                       actor="aletheia-self-diagnosis")
    except Exception:                                                 # noqa: BLE001
        pass
    return _save_trial(record, trial)


def _run_named_tests(names: list[str], where: Path) -> dict:
    from aletheia import proc
    assert_not_live(where)
    modules = [n.replace("/", ".").removesuffix(".py").split("::")[0] for n in names]
    scratch = tempfile.mkdtemp(prefix="aletheia-trial-state-")
    env = dict(os.environ, ALETHEIA_PRIVATE_STATE=scratch, ALETHEIA_JOURNAL_PATH=str(Path(scratch) / "journal.jsonl"),
               ALETHEIA_REHEARSAL="1", ALETHEIA_SEMANTIC_INDEX_OFF="1")
    flags = 0x00004000 if os.name == "nt" else 0                      # below normal priority
    started = time.monotonic()
    try:
        done = proc.run_tree([sys.executable, "-m", "unittest", *modules], TEST_TIMEOUT_S,
                             cwd=str(where), env=env, creationflags=flags)
        output = (done.stdout or "") + (done.stderr or "")
        passed = done.returncode == 0
    except subprocess.TimeoutExpired:
        output, passed = f"the tests took longer than {TEST_TIMEOUT_S} seconds and were stopped", False
    return {"passed": passed, "seconds": round(time.monotonic() - started, 1),
            "output_tail": _clean(output[-2500:])}


def _save_trial(record: dict, trial: dict) -> dict:
    from aletheia import stateio
    record.setdefault("trials", []).append(trial)
    record["status"] = "TRIED" if trial.get("applied") else "DID_NOT_APPLY"
    stateio.write_json_atomic(proposals_dir() / f"{record['id']}.json", record)
    return record


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Diagnose a failure; propose or try a patch (never merges).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diagnose")
    d.add_argument("failure")
    d.add_argument("--detail", default="")
    d.add_argument("--think", action="store_true", help="let her local model refine the rules' diagnosis")
    d.add_argument("--review", action="store_true", help="ask a stronger model (subscriptions) to review it")
    p = sub.add_parser("propose")
    p.add_argument("failure")
    p.add_argument("--detail", default="")
    p.add_argument("--diff", default="", help="a file holding the unified diff")
    p.add_argument("--tests", default="")
    p.add_argument("--think", action="store_true")
    p.add_argument("--review", action="store_true")
    t = sub.add_parser("try")
    t.add_argument("proposal")
    t.add_argument("--tests", default="")
    args = ap.parse_args(argv)
    if args.cmd == "diagnose":
        out = diagnose(args.failure, detail=args.detail, think=local_think() if args.think else None,
                       review=args.review)
    elif args.cmd == "propose":
        diff = Path(args.diff).read_text(encoding="utf-8") if args.diff else ""
        thinker = local_think() if args.think else None
        out = propose_patch(args.failure, diff=diff, detail=args.detail, think=thinker,
                            diagnosis=diagnose(args.failure, detail=args.detail, think=thinker),
                            tests=[x for x in args.tests.split(",") if x] or None, review=args.review)
    else:
        out = try_patch(args.proposal, tests=[x for x in args.tests.split(",") if x] or None)
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
