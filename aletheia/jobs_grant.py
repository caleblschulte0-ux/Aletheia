"""The jobs grant reaches the general browser's job missions.

His words, 2026-09-23 morning, in his words: *"Yeah, it can make its own
accounts. I don't give a shit."* — and, the night before, *"if it's job
related and it's just applying to a job, approve it."* That morning five
approvals sat on his page: "press 'Create Account' for Customer Success
Manager — Autodesk", "... — Salesforce" (twice), "... — Henry Schein", and
"press 'send' for Account Manager II — PNC". Every one was the general
browser (`browser_loop`) driving a site with no form adapter, asking
`web.commit` for the one button a job application comes down to.

`web.commit` is the loop's word for ANY committing button, on any site, and
it is not in the registry at all, so no grant can ever cover it as such
(`authority.allows` refuses a capability the registry does not know). What
the grant covers is the ACT: the jobs grant (`standing.JOBS_CAPABILITIES`)
is spent on `application.submit` for the button that sends an application
and on `account.create` for the button that makes an account, and only on a
mission that is a job application. Anything else the loop holds - a form
on somebody else's site, a button in a mission of his own - waits for him
exactly as before.

Two things make it safe:

- The grant is spent on a registry capability, through `authority.satisfy`,
  with the approval id as the action id: one receipt per approval, refused
  by the same rules as every other grant (expired, exhausted, high-risk).
  No grant means nothing here approves anything.
- The approval is DECIDED, in his name, citing the grant and his words. The
  loop's own gate is unchanged: `press_approved_web_tasks` still re-reads the
  page against the digest he was asked about, and presses once.
"""
from __future__ import annotations

import re

from aletheia import journal, policy

ACTOR = "aletheia-standing"

#: What the loop calls a job application mission (its id carries its goal).
JOB_MISSION_PREFIX = "bm-apply-for-this-job"

#: The button that makes an account, by what it says. Anything else a job
#: mission holds is the application's own send.
_ACCOUNT_BUTTON = re.compile(
    r"\b(?:create|open|make|set ?up)\s+(?:an?\s+|my\s+|your\s+|new\s+)?(?:account|profile|login)\b"
    r"|\bsign\s*up\b|\bregister\b|\bjoin(?:\s+now)?\b",
    re.I)

_MISSION_APPROVAL = re.compile(r"^(?P<mission>.+?)--g\d+-commit-[0-9a-f]+$")

HIS_WORDS = ("his words 2026-09-23: \"it can make its own accounts\" and "
             "\"if it's job related and it's just applying to a job, approve it\"")


def is_job_mission(record: dict) -> bool:
    """A mission the job hunt started, by its id and its skill - never by
    what its page says."""
    if not isinstance(record, dict):
        return False
    if str(record.get("id") or "").startswith(JOB_MISSION_PREFIX):
        return True
    try:
        from aletheia import job_skill
        return bool(record.get("skill")) and record.get("skill") == job_skill.SKILL
    except Exception:
        return False


def capability_for(record: dict) -> str | None:
    """Which registry capability the held button IS, or None when this is
    not a job mission's button at all."""
    if not is_job_mission(record):
        return None
    gate = record.get("gate") if isinstance(record.get("gate"), dict) else {}
    boundary = record.get("boundary") if isinstance(record.get("boundary"), dict) else {}
    button = " ".join(str(gate.get("button") or "").split())
    if boundary.get("kind") == "ACCOUNT_CREATION_APPROVAL" or _ACCOUNT_BUTTON.search(button):
        return "account.create"
    return "application.submit"


def approve_under_the_grant(*, approvals=None, load_mission=None, satisfy=None) -> list[dict]:
    """Spend the jobs grant on every job mission's pending button. Returns
    what was decided; never raises past one approval."""
    from aletheia import authority, browser_mission
    approvals = policy.all_approvals() if approvals is None else approvals
    load_mission = browser_mission.load if load_mission is None else load_mission
    satisfy = authority.satisfy if satisfy is None else satisfy
    decided: list[dict] = []
    for approval in approvals:
        if approval.get("state") != "PENDING" or str(approval.get("capability") or "") != "web.commit":
            continue
        aid = str(approval.get("id") or "")
        hit = _MISSION_APPROVAL.match(aid)
        if not hit:
            continue
        try:
            record = load_mission(hit.group("mission"))
        except Exception:
            continue
        capability = capability_for(record)
        if not capability:
            continue
        try:
            claim = satisfy(capability, aid)
        except Exception:
            claim = None
        if claim is None:
            continue          # no grant covers this act: it waits for him, as before
        try:
            policy.decide(aid, "APPROVED", via="standing-grant", because=f"{claim}: {HIS_WORDS}")
        except Exception:
            continue
        what = " ".join(str(approval.get("reason") or approval.get("requested_action") or aid).split())[:160]
        journal.append("decision", f"approval:{aid}",
                       f"approved under the jobs grant ({capability}): {what}", actor=ACTOR)
        decided.append({"approval": aid, "capability": capability, "grant": claim})
    return decided
