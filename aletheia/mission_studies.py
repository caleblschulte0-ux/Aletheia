"""His studies on the mission screen: one card each, with the evidence, the comparison and what is his.

A study (`aletheia.studies`) turns outside research into proposed changes to one of
his projects and measures them. Its card answers what he would ask: how much she
read (the evidence count), what she measured (the top compared rows), which proposals
wait for HIS decision, which accepted changes are being carried or measured and when
the next measurement is due, and anything blocked with its reason. A study with a
proposal or a measured change waiting on him is NEEDS YOU; one reading or thinking is
RUNNING; one measuring with nothing on him is WAITING.

`read` is the only impure function; `build` is pure. Read-only throughout.
"""
from __future__ import annotations

from aletheia.mission_control import Provider, _words, mission_card

TYPE = "study"


def read(ctx: dict) -> dict:
    from aletheia import studies
    said = studies.status(now=ctx.get("now"))
    notes = [] if said.get("readable") else [said.get("note") or "the studies could not be read"]
    return {"status": said, "notes": notes}


def _status_word(s: dict) -> str:
    if s["awaiting_decision"] or s["awaiting_verdict"] or s["unconfirmed_comparables"]:
        return "NEEDS YOU"
    if s.get("running") or s["executing"] or (s["pending"] and not s.get("blocked")):
        return "RUNNING"
    if s["measuring"] or s["ready"] or s.get("blocked"):
        return "WAITING"
    return "OPEN"


def build(reading: dict, ctx: dict) -> dict:
    said = reading.get("status") or {}
    if not said.get("readable"):
        return {}
    cards, details, signals = [], {}, []
    for s in said.get("studies") or []:
        cid = f"study:{s['id']}"
        by_key = {h["key"]: h for h in s["hypotheses"]}
        needs = [{"said": f"Decide: {_words(by_key[k]['title'], 100)}", "blocking": True, "source": cid}
                 for k in s["awaiting_decision"]]
        needs += [{"said": f"Keep, revert or iterate: {_words(by_key[k]['title'], 90)}", "blocking": True,
                   "source": cid} for k in s["awaiting_verdict"]]
        if s["unconfirmed_comparables"]:
            needs.append({"said": "Confirm what to study: " + ", ".join(s["unconfirmed_comparables"][:3]),
                          "blocking": True, "source": cid})
        blockers = []
        if s.get("blocked"):
            blockers.append({"said": f"{s['blocked'].get('step')}: {s['blocked'].get('why')}",
                             "at": s["blocked"].get("until"), "source": cid})
        step = ((s.get("running") or {}).get("step") or (s["pending"][0] if s["pending"] else ""))
        nxt = ("your decision" if needs else f"measure again at {s['next_measurement_at']}" if s["measuring"]
               else f"the {step} step" if step else "")
        comparison = s.get("comparison") or {}
        counts = [{"label": "observations", "value": s["evidence"]},
                  {"label": "measured rows", "value": comparison.get("rows", 0)},
                  {"label": "proposals for you", "value": len(s["awaiting_decision"])},
                  {"label": "changes carried", "value": len(s["ready"]) + len(s["executing"])},
                  {"label": "measuring", "value": len(s["measuring"])}]
        cards.append(mission_card(
            id=cid, type=TYPE, title=f"Study: {s['subject'] or 'a project'}", status=_status_word(s),
            goal=s.get("title") or "", step=(f"{step}" if step else ""), next=nxt, blockers=blockers, needs=needs,
            counts=counts, receipts=[{"said": r.get("text"), "at": r.get("at")} for r in s["results"][-3:]],
            updated=s.get("updated_at"), detail=True, source="state/private/studies"))
        details[cid] = {"type": TYPE, "comparables": s["comparables"], "questions": s["questions"], "lens": s["lens"],
                        "lens_by": s.get("lens_by"), "comparison": comparison, "hypotheses": s["hypotheses"],
                        "pending": s["pending"], "blocked": s.get("blocked"), "evidence": s["evidence"],
                        "refused_reads": s["refused_reads"], "next_measurement_at": s["next_measurement_at"],
                        "learned": s["learned"]}
    if cards:
        waiting = sum(len(d["hypotheses"]) for d in details.values())
        signals.append({"what": "studies", "ok": True,
                        "said": f"{len(cards)} stud{'ies' if len(cards) != 1 else 'y'}, {waiting} proposal(s) on record"})
    return {"missions": cards, "details": details, "signals": signals}


PROVIDER = Provider(type=TYPE, label="Studies", read=read, build=build,
                    journal_subjects=frozenset(), subject_labels={"studies": "Studies"})
