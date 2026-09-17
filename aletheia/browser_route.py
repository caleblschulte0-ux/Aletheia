"""Which engine does a "go do this on a website" ask: the general loop, or the older one.

Operator direction, 2026-09-16: *"jobs should be the current test case, not
the architecture. Keep pushing the core toward general reasoning + reusable
tools/skills so Aletheia can handle totally different goals without needing
a new hardcoded workflow every time."*

`web_task` is the catch-all doing verb. Until now it always ran
`webtask.run` (a model picks one raw-selector step at a time), while the
general observe -> understand -> act -> verify loop (`browser_loop.pursue`:
semantic targets, page states, named stops, checkpoints, the
no-second-press invariant) had only ever run on fixtures. This module is the
switch between them, and it is deliberately small:

    LOOP     a start page is known and the goal is not something only the
             older loop can do. The general skill fills from his profile
             facts (the same facts webtask's value gate allows); a goal that
             reads as applying for a job is handed the job SKILL, an
             optimisation on the same loop. A model may pick which link or
             button moves toward the goal (`browser_loop.model_decider`),
             never what is typed and never a press that commits.
    WEBTASK  no start page (the older loop can search and navigate by
             itself), or a goal that saves a file (only it can download).

Every gate is unchanged, because both engines stop in the same places:
spending is refused before either runs (`webtask.would_spend`, here AND in
the loop); a committing button becomes ONE hash-bound approval
(`webtask._await_him`) pressed by `webtask.commit`; the desktop-hands
refusals are not touched. Both feed the demand ledger at their stops
(`browser_loop._stop`, `webtask.run`).

Specialised flows keep their own verbs: `apply_campaign` (the job hunt),
`subscription_cancel` and `reservations` still call their paths directly.
"""
from __future__ import annotations

import re

LOOP = "browser_loop"
WEBTASK = "webtask"

#: Only the older loop can save a file the page offers.
_DOWNLOADS = re.compile(r"\b(?:download|save (?:the |a |my )?(?:file|pdf|statement|receipt|invoice|copy)|"
                        r"export)\b", re.I)
_APPLYING = re.compile(r"\bappl(?:y|ying|ication)\b.{0,60}\b(?:job|role|position|posting|opening)\b|"
                       r"\b(?:job|role|position|posting|opening)\b.{0,60}\bappl(?:y|ication)\b", re.I)
#: A live session waits this long at the approval for his yes before handing
#: the press to the replay path. Short: the Core is waiting on this command.
LIVE_HOLD_S = 120.0


def engine_for(goal: str, url: str = "") -> tuple[str, str]:
    """(engine, why) for one ask. Pure."""
    url = str(url or "").strip()
    if not re.match(r"^https?://", url):
        return WEBTASK, "no start page, and only the older loop can search for one"
    if _DOWNLOADS.search(str(goal or "")):
        return WEBTASK, "the goal saves a file, and only the older loop can download"
    return LOOP, "a start page and a goal the general loop can drive"


def skill_for(goal: str, url: str = ""):
    """The general skill, or the job skill when the goal is applying for a job."""
    if _APPLYING.search(str(goal or "")):
        from aletheia import job_skill
        return job_skill.SKILL
    return None


def his_facts() -> dict:
    """What the general skill may type: his profile facts, minus anything
    that is his to answer on every form (`formfill.is_never_autofill`)."""
    from aletheia import formfill, profile
    out = {}
    try:
        known = profile.known()
    except Exception:
        known = {}
    for key, value in known.items():
        if value in (None, "") or isinstance(value, (dict, list)):
            continue
        try:
            if formfill.is_never_autofill({"label": str(key).replace("_", " ")}):
                continue
        except Exception:
            continue
        out[str(key)] = str(value)
    return out


def pursue(goal: str, url: str, *, budget: int = 16, decide=None, code_source=None,
           hold_s: float | None = None, session=None, inputs: dict | None = None) -> dict:
    """Drive one web_task through the general loop. Returns the mission record."""
    from aletheia import browser_loop, verification_mail
    skill = skill_for(goal, url)
    if skill is not None:
        from aletheia import apply_run
        gone = apply_run.was_sent(url)
        if gone:
            raise browser_loop.LoopError(
                f"an application already went to {url} at {gone.get('at')} - not applying twice")
    if decide is None:
        decide = browser_loop.model_decider()
    return browser_loop.pursue(
        goal, url, inputs={**his_facts(), **dict(inputs or {})}, skill=skill, decide=decide,
        budget=budget, session=session,
        code_source=code_source if code_source is not None else verification_mail.source(),
        hold_s=LIVE_HOLD_S if hold_s is None else hold_s)


def _think(system: str, text: str) -> dict:
    """Kept for callers that pass a thinker: the standard class, not a company."""
    from aletheia import reasoning_gateway
    return reasoning_gateway.reason_json(system, text, policy="standard").output


def spoken(record: dict) -> str:
    """One sentence for the room, from a mission record."""
    from aletheia import browser_mission as bm
    state = record.get("state")
    boundary = record.get("boundary") or {}
    if state == bm.DONE:
        return f"Done: {record.get('goal', 'that')}. The site confirmed it."
    if boundary.get("say"):
        return str(boundary["say"])
    return bm.describe(record)


def run(goal: str, *, url: str = "", budget: int = 16) -> str:
    """The web_task verb: route, run, and say what happened."""
    from aletheia import webtask
    engine, _why = engine_for(goal, url)
    if engine == WEBTASK or webtask.would_spend(goal):
        # Spending is refused by webtask.run itself, with no browser opened.
        return webtask.spoken(webtask.run(goal, start_url=url, budget=budget))
    return spoken(pursue(goal, url, budget=budget))


# ---- the follow-ups: "the answer is X", "try that again" ---------------------------------

def _stamp(row: dict) -> str:
    return str(row.get("beat") or row.get("at") or "")


def waiting_mission(run_id: str = "") -> dict | None:
    """A browser mission waiting on his answer: by id, or the latest one, but
    only when it is newer than the newest older-loop run waiting on him."""
    from aletheia import browser_mission as bm, webtask
    if run_id:
        return bm.load(run_id) if run_id.startswith("bm-") and bm.exists(run_id) else None
    missions = [m for m in bm.all_missions(bm.NEEDS_YOU)]
    if not missions:
        return None
    latest = max(missions, key=_stamp)
    older = [r for r in webtask.all_runs() if r.get("state") in webtask.PICKABLE]
    if older and max(_stamp(r) for r in older) > _stamp(latest):
        return None
    return latest


def rejected_mission(run_id: str = "") -> dict | None:
    from aletheia import browser_mission as bm, webtask
    if run_id:
        return bm.load(run_id) if run_id.startswith("bm-") and bm.exists(run_id) else None
    missions = bm.all_missions(bm.REJECTED)
    if not missions:
        return None
    latest = max(missions, key=_stamp)
    older = webtask.all_runs("REJECTED")
    if older and max(_stamp(r) for r in older) > _stamp(latest):
        return None
    return latest


def answer(mission: dict, answers: dict) -> str:
    from aletheia import browser_loop, verification_mail
    record = browser_loop.resume(mission["id"], answers=answers or None,
                                 skill=skill_for(mission.get("goal", ""), mission.get("start_url", "")),
                                 decide=browser_loop.model_decider(),
                                 code_source=verification_mail.source(), hold_s=LIVE_HOLD_S)
    return spoken(record)


def retry(mission: dict) -> str:
    """He asked to try again after the site refused: a new approval, never a
    press - and the approval sentence carries what the site said."""
    from aletheia import browser_loop, verification_mail
    record = browser_loop.resume(mission["id"], retry=True,
                                 skill=skill_for(mission.get("goal", ""), mission.get("start_url", "")),
                                 decide=browser_loop.model_decider(),
                                 code_source=verification_mail.source(), hold_s=LIVE_HOLD_S)
    return spoken(record)
