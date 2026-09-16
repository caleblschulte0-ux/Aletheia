"""Recall and self-diagnosis as tools a model can REQUEST.

    memory.recall        READ. Facts from her stores (KNOWN) and passages from
                         the semantic index (FOUND IN HISTORY), or neither
                         (GUESS) - the basis travels with the observation.
    self.diagnose        READ. The failure, similar past failures and fixes,
                         the code that raised it: boundary or defect, where,
                         on what evidence, how sure. No model call inside: in
                         a session, the session's own model does the thinking.
    repo.propose_patch   A RECORD ONLY. Writes a proposal (diagnosis, diff,
                         suggested tests) under private state and changes no
                         code; `tools.RECORD_ONLY_STORES` is why the broker
                         lets it run inside a session.
    repo.try_patch       ROUTINE, operator_once. Applies a proposal in a
                         throwaway worktree and runs the named tests there.
                         It executes code, so inside a session it is always a
                         HANDOFF.

Nothing here merges, pushes, or touches the checkout she runs from.
"""
from __future__ import annotations

import json

from aletheia import intercom, tools

#: What one observation can carry. The session cuts at 1,800 characters.
FACT_CHARS = 360
SNIPPET_CHARS = 200
MAX_FACTS_SHOWN = 2
#: The note a model reads with each basis: short, because it is paid for on
#: every step, and the whole of what the basis obliges her to say.
BASIS_NOTE = {
    "KNOWN": "facts are exact rows from your stores; history is related, not certain",
    "FOUND IN HISTORY": "related history found by search, not fact: say 'from my history'",
    "GUESS": "nothing matched: anything you say about this is a guess, so say so",
}


def _compact(value, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _sources(value) -> list[str] | None:
    if isinstance(value, str):
        value = [s.strip() for s in value.replace(";", ",").split(",") if s.strip()]
    return [str(s) for s in value] if isinstance(value, list) and value else None


def recall(args: dict, **_ignored) -> dict:
    from aletheia import semantic_index
    try:
        k = max(1, min(int(args.get("k") or 3), 8))
    except (TypeError, ValueError):
        k = 3
    out = semantic_index.recall(str(args.get("query") or ""), sources=_sources(args.get("sources")), k=k)
    shown = {"basis": out["basis"], "note": BASIS_NOTE.get(out["basis"], "")}
    if out.get("facts"):
        shown["facts"] = [{"store": f.get("store"), "id": f.get("id"),
                           "fact": _compact(f.get("fact"), FACT_CHARS)} for f in out["facts"][:MAX_FACTS_SHOWN]]
        if len(out["facts"]) > MAX_FACTS_SHOWN:
            shown["more_facts"] = len(out["facts"]) - MAX_FACTS_SHOWN
    if out.get("snippets"):
        shown["history"] = [{"source": s["source"], "where": s["where"], "when": str(s.get("ts") or "")[:10],
                             "text": _compact(s["text"], SNIPPET_CHARS)} for s in out["snippets"][:k]]
    for key in ("answered_by", "lexical_because", "index", "unreadable_stores"):
        if out.get(key):
            shown[key] = out[key]
    return shown


def diagnose(args: dict, **_ignored) -> dict:
    from aletheia import self_diagnosis
    d = self_diagnosis.diagnose(str(args.get("failure") or ""), detail=str(args.get("detail") or ""))
    return {"basis": d["basis"], "kind": d["kind"], "boundary": d.get("boundary"),
            "also_faces": d.get("also_faces") or [], "other_records": d.get("other_matching_records") or [],
            "summary": d["summary"], "confidence": d["confidence"],
            "failure": _compact({k: d["failure"].get(k) for k in ("kind", "ref", "state", "text")}, 360),
            "likely_location": [{"path": l["path"], "line": l["line"], "why": _compact(l["why"], 90)}
                                for l in d["likely_location"][:3]],
            "evidence": [{"id": e["id"], "source": e["source"], "where": _compact(e["where"], 60),
                          "basis": e["basis"], "text": _compact(e["text"], 110)} for e in d["evidence"][:5]],
            "next_step": d["next_step"], "note": d.get("note", ""),
            "classified_by": d["provenance"]["classified_by"]}


def propose(args: dict, **_ignored) -> dict:
    from aletheia import self_diagnosis
    tests = args.get("tests")
    if isinstance(tests, str):
        tests = [t.strip() for t in tests.split(",") if t.strip()]
    record = self_diagnosis.propose_patch(str(args.get("failure") or ""), diff=str(args.get("diff") or ""),
                                          tests=tests or None, summary=str(args.get("summary") or ""),
                                          detail=str(args.get("detail") or ""))
    return {"proposal": record["id"], "status": record["status"], "authority": record["authority"],
            "diff_applies": record["diff_check"].get("ok"), "diff_check": record["diff_check"].get("why"),
            "files": record["files"], "suggested_tests": record["suggested_tests"],
            "touches_authority": record["touches_authority"],
            "why_no_diff": record.get("why_no_diff", ""),
            "diagnosis": {"kind": record["diagnosis"]["kind"], "summary": record["diagnosis"]["summary"]}}


def try_patch(args: dict, **_ignored) -> dict:
    from aletheia import self_diagnosis
    tests = args.get("tests")
    if isinstance(tests, str):
        tests = [t.strip() for t in tests.split(",") if t.strip()]
    record = self_diagnosis.try_patch(str(args["proposal"]), tests=tests or None)
    return {"proposal": record["id"], "status": record["status"], "trial": record["trials"][-1]}


TOOLS = (
    tools.declare(
        "memory.recall",
        description=("Look something up in your own memory: exact records from your stores (basis "
                     "KNOWN) and related passages from your history - journal, past sessions, browser "
                     "missions, notifications, commit messages, code and docs (basis FOUND IN HISTORY, "
                     "similar but not certain). query; sources narrows to any of ledger, journal, "
                     "sessions, missions, applications, employers, notifications, fixes, code, docs; k "
                     "at most 8."),
        input_schema={"properties": {"query": {"type": "string"},
                                     "sources": {"type": ["array", "string"]},
                                     "k": {"type": ["integer", "string"]}},
                      "required": ["query"]},
        handler=recall, capability="memory.semantic",
        reads=("semantic-index", "applications", "browser-missions", "employers", "tasks", "plans",
               "memory"),
        provenance=tools.TRUSTED_LOCAL_STATE),
    tools.declare(
        "self.diagnose",
        description=("Diagnose why something of yours failed or stopped: failure is a record id "
                     "(a browser mission, an application), journal:<words>, test:<tests.module>, or "
                     "plain words naming it; detail is any error text. Returns boundary or defect, the "
                     "likely code location, evidence and confidence."),
        input_schema={"properties": {"failure": {"type": "string"}, "detail": {"type": "string"}},
                      "required": ["failure"]},
        handler=diagnose, capability="self.diagnose",
        reads=("semantic-index", "repository", "applications", "browser-missions", "journal"),
        provenance=tools.TRUSTED_LOCAL_STATE),
    tools.declare(
        "repo.propose_patch",
        description=("Write a PROPOSAL to fix a diagnosed defect: failure (as for self.diagnose), diff "
                     "(a unified diff), tests, summary. Records it for Caleb; applies nothing, changes "
                     "no code, never branches or merges."),
        input_schema={"properties": {"failure": {"type": "string"}, "diff": {"type": "string"},
                                     "tests": {"type": ["array", "string"]},
                                     "summary": {"type": "string"}, "detail": {"type": "string"}},
                      "required": ["failure"]},
        handler=propose, capability="repo.propose_patch", risk=intercom.TIER_ROUTINE,
        writes=("patch-proposals",), idempotent=True, approval="none",
        reads=("repository", "semantic-index"), provenance=tools.TRUSTED_LOCAL_STATE,
        notes="non-authoritative: a record under private state, the brief's 'propose' step"),
    tools.declare(
        "repo.try_patch",
        description=("Try a patch proposal in a throwaway worktree outside your running code and run "
                     "only the named tests there (proposal; tests). Always handed to Caleb."),
        input_schema={"properties": {"proposal": {"type": "string"},
                                     "tests": {"type": ["array", "string"]}},
                      "required": ["proposal"]},
        handler=try_patch, capability="repo.propose_patch", risk=intercom.TIER_ROUTINE,
        writes=("patch-proposals", "git-branches"), idempotent=False, approval="operator_once",
        reads=("repository",), provenance=tools.TRUSTED_TOOL_OUTPUT,
        notes="executes code (the named tests) in a separate worktree; never the live checkout, never a push"),
)
