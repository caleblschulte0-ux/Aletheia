"""The job application skill: the general browser loop's first client.

The operator, 2026-09-16: *"jobs should be the current test case, not the
architecture ... Specialized job code is fine as an optimization."* So this
is a SKILL handed to `browser_loop.pursue`, and everything it adds is an
optimisation on top of the general loop, never a requirement of it:

- it ANNOTATES pages (JOB_POST, APPLICATION) so a record can say "stopped
  on the posting" instead of "stopped on a content page";
- it fills from his PROFILE through `formfill.plan` (the same deterministic
  mapper the application filler has used on every live form), in addition
  to the goal's own inputs, and keeps `formfill`'s refusals - the
  never-autofill questions stay his;
- it attaches the resume `webtask.documents` finds when a file box asks for
  one;
- it adds "apply" to the words that move toward the goal.

What it does NOT do is drive anything. Observation, page states, the value
gate, checkpoints, the approval at Submit and the duplicate-submit
invariant are the loop's, identical for a library card.
"""
from __future__ import annotations

import re
from pathlib import Path

from aletheia import browser_loop, formfill, page_state as ps

JOB_POST = "JOB_POST"
APPLICATION = "APPLICATION"

_POSTING = re.compile(r"apply for this (?:job|position|role)|job description|responsibilities|"
                      r"qualifications|about the role|what you(?:'|’)ll do|jobposting", re.I)
_CLOSED = re.compile(
    r"\bclosed:\s*\w+ \d{1,2},? \d{4}|no longer accepting applications|(?:this|the) (?:job|position|posting|"
    r"opening|requisition) (?:is|has been) (?:closed|filled|no longer available)|position (?:has been )?filled|"
    r"job (?:posting )?(?:has )?expired|applications? (?:are |is )?(?:now )?closed", re.I)
_RESUME = re.compile(r"\bresume\b|\bcv\b|curriculum vitae|r[ée]sum[ée]", re.I)


class JobApplication(browser_loop.GeneralSkill):
    name = "job_application"

    def annotate(self, obs: dict) -> list[str]:
        marks = []
        blob = f"{obs.get('title', '')} {str(obs.get('text') or '')[:4000]}"
        if obs.get("state") == ps.CONTENT and _POSTING.search(blob):
            marks.append(JOB_POST)
        if obs.get("state") in (ps.FORM, ps.MULTI_PAGE_WIZARD, ps.REVIEW) and (
                any(t["role"] == "file" and _RESUME.search(t["label"]) for t in obs.get("targets") or [])
                or re.search(r"\bapplication\b", blob, re.I)):
            marks.append(APPLICATION)
        return marks

    def nav_words(self, goal: str) -> set[str]:
        return super().nav_words(goal) | {"apply", "application"}

    def boundary(self, obs: dict) -> dict | None:
        """A posting that says it has closed is a stop, not a page to wander
        from. Live 2026-09-17 a closed UltiPro posting had no Apply, and her
        own model followed "Accessibility Accommodation for Applicants"
        instead, three minutes per guess."""
        if obs.get("state") not in (ps.CONTENT, ps.ERROR, ps.UNKNOWN):
            return None
        blob = f"{obs.get('title', '')} {str(obs.get('text') or '')[:4000]}"
        hit = _CLOSED.search(blob)
        if not hit:
            return None
        return {"kind": "POSTING_CLOSED", "step": "pick another opening",
                "say": f"This posting says it is closed ({' '.join(hit.group(0).split())[:80]}), so there is "
                       "nothing to apply to. Nothing was filled or sent."}

    def plan(self, obs: dict, record: dict, site: dict) -> dict:
        base = super().plan(obs, record, site)
        taken = {item["selector"] for item in base["fill"]}
        refs = obs.get("_refs") or {}
        if obs.get("state") == ps.ACCOUNT_SIGNUP:
            # AN ACCOUNT IS NOT AN APPLICATION. `signup.plan` owns what an
            # account form gets - his signup number, never the one employers
            # ring - and the loop owns the password (vault only).
            from aletheia import signup, site_skills
            try:
                made = signup.plan(list(obs.get("_raw") or []), host=site_skills.domain_of(obs.get("url", "")),
                                   password="unused-here-the-loop-fills-passwords-from-the-vault")
            except Exception:
                made = {"fill": [], "missing": []}
            for item in made.get("fill") or []:
                selector = (item.get("field") or {}).get("selector")
                if item.get("is") == "password" or not selector or selector in taken:
                    continue
                base["fill"].append({"action": "type", "selector": selector, "value": str(item["value"]),
                                     "label": (item.get("field") or {}).get("label", ""), "key": item["is"]})
                taken.add(selector)
            filled = {browser_loop._norm(i.get("label", "")) for i in base["fill"]}
            base["ask"] = [q for q in base["ask"] if browser_loop._norm(q) not in filled]
            for item in made.get("missing") or []:
                label = str((item.get("field") or {}).get("label") or item.get("needs"))
                if (item.get("field") or {}).get("required") and label not in base["ask"]:
                    base["ask"].append(label)
            return base
        try:
            mapped = formfill.plan(list(obs.get("_raw") or []))
        except Exception:
            mapped = {"fill": [], "ask": []}
        # ANSWERED BY THE GENERAL SKILL OR ALREADY CHOSEN ON THE PAGE: a group
        # question with a ticked option is not his to answer again (live
        # 2026-09-17, Jane Street's Yes/No kept coming back after his No).
        answered_labels = {browser_loop._norm(i.get("label", "")) for i in base["fill"]}
        answered_labels |= {browser_loop._norm(t.get("question")) for t in obs.get("targets") or []
                            if t.get("question") and t.get("checked")}
        # WHAT THE PAGE ALREADY HOLDS is not typed again: a resumed mission
        # replays its route, and live 2026-09-17 (Avature) every profile field
        # was then typed a second time into the route.
        holds = {refs[t["id"]]: str(t.get("value") or "").strip() for t in obs.get("targets") or []
                 if t["id"] in refs}
        for item in mapped.get("fill") or []:
            if item["selector"] in taken:
                continue
            if item["action"] == "type" and holds.get(item["selector"]) == str(item.get("value") or "").strip():
                taken.add(item["selector"])
                answered_labels.add(browser_loop._norm(item.get("label", "")))
                continue
            action = item["action"] if item["action"] in ("type", "select", "click", "check") else "type"
            base["fill"].append({"action": action, "selector": item["selector"],
                                 "value": item.get("value", ""), "label": item.get("label", ""),
                                 "key": item.get("profile_field", "profile")})
            taken.add(item["selector"])
            answered_labels.add(browser_loop._norm(item.get("label", "")))
        files = [t for t in obs.get("targets") or [] if t["role"] == "file"]
        # ONE UNNAMED FILE BOX on a page that talks about a resume is the resume
        # box: BambooHR's reads only "Choose File*" (live 2026-09-17).
        generic = {"file", "input", "upload", "choose", "select", "browse", "attach", "attachment",
                   "document", "no", "selected", "drop", "here", "or"}
        lone = (len(files) == 1 and set(browser_loop._norm(files[0].get("label")).split()) <= generic
                and _RESUME.search(f"{obs.get('title', '')} {str(obs.get('text') or '')[:4000]}"))
        for t in files:
            if not (_RESUME.search(t["label"]) or lone) or refs.get(t["id"]) in taken:
                continue
            if any(a.get("selector") == refs.get(t["id"]) for a in record.get("attached") or []):
                answered_labels.add(browser_loop._norm(t["label"]))
                continue                     # attached already (the replay puts it back)
            try:
                from aletheia import webtask
                resume = webtask.documents().get("resume")
            except Exception:
                resume = None
            if resume and Path(resume).is_file():
                base["fill"].append({"action": "attach", "selector": refs[t["id"]], "value": str(resume),
                                     "label": t["label"], "key": "resume"})
                answered_labels.add(browser_loop._norm(t["label"]))
        # ONE QUESTION, HOWEVER MANY READERS SAW IT: the page reader cuts a long
        # label short and the form reader does not, so "answered" and "already
        # asked" compare by `same_question`, never by exact text.
        def answered(label: str) -> bool:
            return any(browser_loop.same_question(label, done) for done in answered_labels)

        base["ask"] = [q for q in base["ask"] if not answered(q)]
        # A question the page already holds an answer to (filled on an earlier
        # look this run, or by the site) is not asked again.
        holding = {refs[t["id"]] for t in obs.get("targets") or []
                   if t["id"] in refs and (str(t.get("value") or "").strip() or t.get("checked"))}
        for row in mapped.get("ask") or []:
            label = str(row.get("label") or "")
            if row.get("required") and not answered(label) \
                    and row.get("selector") not in taken and row.get("selector") not in holding:
                base["ask"].append(label)
        base["ask"] = browser_loop.unique_questions(base["ask"])
        return base


SKILL = JobApplication()
