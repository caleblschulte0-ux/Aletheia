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

    def plan(self, obs: dict, record: dict, site: dict) -> dict:
        base = super().plan(obs, record, site)
        taken = {item["selector"] for item in base["fill"]}
        refs = obs.get("_refs") or {}
        try:
            mapped = formfill.plan(list(obs.get("_raw") or []))
        except Exception:
            mapped = {"fill": [], "ask": []}
        answered_labels = set()
        for item in mapped.get("fill") or []:
            if item["selector"] in taken:
                continue
            action = item["action"] if item["action"] in ("type", "select", "click", "check") else "type"
            base["fill"].append({"action": action, "selector": item["selector"],
                                 "value": item.get("value", ""), "label": item.get("label", ""),
                                 "key": item.get("profile_field", "profile")})
            taken.add(item["selector"])
            answered_labels.add(browser_loop._norm(item.get("label", "")))
        for t in obs.get("targets") or []:
            if t["role"] != "file" or not _RESUME.search(t["label"]) or refs.get(t["id"]) in taken:
                continue
            try:
                from aletheia import webtask
                resume = webtask.documents().get("resume")
            except Exception:
                resume = None
            if resume and Path(resume).is_file():
                base["fill"].append({"action": "attach", "selector": refs[t["id"]], "value": str(resume),
                                     "label": t["label"], "key": "resume"})
                answered_labels.add(browser_loop._norm(t["label"]))
        base["ask"] = [q for q in base["ask"] if browser_loop._norm(q) not in answered_labels]
        # A question the page already holds an answer to (filled on an earlier
        # look this run, or by the site) is not asked again.
        holding = {refs[t["id"]] for t in obs.get("targets") or []
                   if t["id"] in refs and (str(t.get("value") or "").strip() or t.get("checked"))}
        for row in mapped.get("ask") or []:
            label = str(row.get("label") or "")
            if row.get("required") and browser_loop._norm(label) not in answered_labels \
                    and row.get("selector") not in taken and row.get("selector") not in holding \
                    and label not in base["ask"]:
                base["ask"].append(label)
        return base


SKILL = JobApplication()
