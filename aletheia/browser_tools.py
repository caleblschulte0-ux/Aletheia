"""The general browser loop as tools a model can REQUEST.

The brief (docs/JARVIS_BRIEF.md §1 and §4): tool choice without tool
authority. Each descriptor says what the tool is; `agent_session.Broker`
decides whether a request runs inside the session, and it only ever runs
reads there.

    browser.observe   READ. Open one page, return it as semantic targets
                      (role + accessible name + value) and its page state.
                      Runs inside the session. Web content: untrusted.
    browser.missions  READ. Where every browser goal stands: its last
                      checkpoint and the exact boundary it stopped at.
    browser.pursue    WORLD. Drive a goal to done or to a named boundary.
                      Fills forms and moves through a site, so it is
                      `web.task` (operator_always): inside a session it is a
                      HANDOFF, never a run. Its own final press is a second,
                      hash-bound approval on top.
    browser.act       WORLD. One semantic action on a mission's page. Same
                      capability, same handoff.
    browser.code      ROUTINE. Hand a verification code to a waiting
                      mission. Writes local state only, and still waits for
                      him inside a session: a code in a model's mouth is not
                      a code he gave.

Spending is refused by the broker before any of this (`webtask.would_spend`
over the arguments), and again by the loop at the goal and at the button.
"""
from __future__ import annotations

from aletheia import intercom, tools

_TARGET = {"type": ["object", "string"],
           "description": "a target id from browser.observe (t4), or {role, label}"}


def _observe(args: dict) -> dict:
    from aletheia import browser_loop
    return browser_loop.observe_url(str(args["url"]))


def _missions(args: dict) -> dict:
    from aletheia import browser_mission as bm, site_skills
    wanted = str(args.get("mission") or "").strip()
    rows = bm.all_missions()
    if wanted:
        rows = [r for r in rows if r.get("id") == wanted]
        if not rows:
            return {"missions": [], "note": f"no browser mission {wanted}"}
        r = rows[0]
        return {"mission": {
            "id": r["id"], "goal": r.get("goal"), "state": r.get("state"), "mode": r.get("mode"),
            "skill": r.get("skill"), "boundary": r.get("boundary"),
            "checkpoints": [c.get("name") for c in r.get("checkpoints") or []][-20:],
            "submits": [{k: s.get(k) for k in ("at", "button", "verdict")} for s in r.get("submits") or []],
            "history": [h.get("did") for h in r.get("history") or []][-10:],
            "site": {k: v for k, v in site_skills.for_domain(r.get("start_url", "")).items()
                     if k in ("domain", "mode", "families", "boundaries", "runs")}}}
    return {"missions": [{"id": r["id"], "goal": r.get("goal"), "state": r.get("state"),
                          "said": bm.describe(r)} for r in rows[-20:]],
            "note": "empty: no browser goal has been pursued yet" if not rows else ""}


def _pursue(args: dict) -> dict:
    from aletheia import browser_loop, browser_mission as bm
    skill = None
    if str(args.get("skill") or "") == "job_application":
        from aletheia import job_skill
        skill = job_skill.SKILL
    record = browser_loop.pursue(str(args["goal"]), str(args["url"]), inputs=args.get("inputs") or {},
                                 mode=str(args.get("mode") or browser_loop.AUTONOMOUS), skill=skill)
    return {"mission": record["id"], "state": record.get("state"), "said": bm.describe(record),
            "boundary": record.get("boundary")}


def _act(args: dict) -> dict:
    from aletheia import browser_loop
    return browser_loop.act(str(args["mission"]), {"act": args["act"], "target": args.get("target"),
                                                   "value": args.get("value")})


def _code(args: dict) -> dict:
    from aletheia import browser_loop, browser_mission as bm
    record = browser_loop.post_code(str(args["mission"]), str(args["code"]))
    return {"mission": record["id"], "said": bm.describe(record)}


TOOLS = (
    tools.declare(
        "browser.observe",
        description=("Open one web page and read it as semantic targets (role, label, value) with "
                     "its page state (FORM, ACCOUNT_LOGIN, CAPTCHA, REVIEW, ...). Reading only."),
        input_schema={"properties": {"url": {"type": "string"}}, "required": ["url"]},
        handler=_observe, capability="browser.read", reads=("web",), open_world=True,
        provenance=tools.UNTRUSTED_WEB),
    tools.declare(
        "browser.missions",
        description=("Where your browser goals stand: each one's state, last checkpoint and the "
                     "exact boundary it stopped at (mission narrows to one)."),
        input_schema={"properties": {"mission": {"type": "string"}}},
        handler=_missions, capability="state.now", reads=("browser-missions", "site-skills")),
    tools.declare(
        "browser.pursue",
        description=("Pursue a goal on a website until done or a named boundary (goal, url; inputs "
                     "are his answers; mode autonomous|assisted; skill general|job_application). "
                     "Always handed to Caleb."),
        input_schema={"properties": {"goal": {"type": "string"}, "url": {"type": "string"},
                                     "inputs": {"type": "object"},
                                     "mode": {"type": "string", "enum": ["autonomous", "assisted"]},
                                     "skill": {"type": "string", "enum": ["general", "job_application"]}},
                      "required": ["goal", "url"]},
        handler=_pursue, capability="web.task", risk=intercom.TIER_WORLD,
        writes=("browser-missions", "site-skills", "approvals"), reads=("web",), open_world=True,
        approval="operator_always", provenance=tools.UNTRUSTED_WEB,
        notes="fills forms on someone else's site; its final press is a second hash-bound approval"),
    tools.declare(
        "browser.act",
        description=("One action on a browser mission's page (mission; act fill|select|check|uncheck|"
                     "click|follow; target; value). A committing button becomes an approval. Always "
                     "handed to Caleb."),
        input_schema={"properties": {"mission": {"type": "string"},
                                     "act": {"type": "string", "enum": ["fill", "select", "check",
                                                                        "uncheck", "click", "follow"]},
                                     "target": _TARGET, "value": {"type": "string"}},
                      "required": ["mission", "act", "target"]},
        handler=_act, capability="web.task", risk=intercom.TIER_WORLD,
        writes=("browser-missions", "approvals"), reads=("web",), open_world=True,
        approval="operator_always", provenance=tools.UNTRUSTED_WEB),
    tools.declare(
        "browser.code",
        description="Give a waiting browser mission the verification code Caleb received (mission, code).",
        input_schema={"properties": {"mission": {"type": "string"}, "code": {"type": "string"}},
                      "required": ["mission", "code"]},
        handler=_code, capability="web.task", risk=intercom.TIER_ROUTINE,
        writes=("browser-missions",), approval="operator_once", idempotent=False),
)
