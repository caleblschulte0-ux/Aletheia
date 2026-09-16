"""The general browser loop: observe -> understand -> act -> verify, for ANY goal.

The brief (docs/JARVIS_BRIEF.md §4), and the operator's direction on
2026-09-16 that shapes it: *"jobs should be the current test case, not the
architecture ... so Aletheia can handle totally different goals without
needing a new hardcoded workflow every time."*

    pursue("request a dental cleaning appointment", start_url,
           inputs={"full name": ..., "preferred day": "Tuesday"})
    pursue("apply for this job", posting_url, skill=job_skill.JobApplication())

Same loop. It takes a goal in words and any structured inputs, and each
step it:

  OBSERVES   the page as SEMANTIC TARGETS - role + accessible name + value
             (`look`). Selectors exist, but only inside: nothing above this
             module names one, and a model is never shown one.
  UNDERSTANDS what kind of page it is, in a vocabulary true of every site
             (`page_state`), plus whatever a SKILL annotates (a job skill
             marks JOB_POST; the loop does not know what that means).
  ACTS       with the least-authority move that makes progress: fill what
             his inputs answer, press a Next, follow the link the goal
             points at. Everything that submits, sends, confirms or makes
             an account stops at the EXISTING hash-bound approval
             (`webtask._await_him`), pressed later by the existing path
             (`webtask.commit`, which the Core already runs on his yes).
             Spending is refused, never gated.
  VERIFIES   by looking again after every transition, and by reading what
             the site said after a press - never "pressed" as "done".

Every stop is a PRECISELY NAMED boundary (`browser_mission.stop_at`): its
kind, the page, the exact remaining step. Every step is checkpointed with
the route that reached it, so a crash resumes instead of restarting, and
`browser_mission.may_submit` refuses a second press without proof the
first one failed.

What this module does NOT know, and a test holds it to that: what a job,
an employer, a resume or an ATS is. Those are `job_skill`, an optimisation
the loop can be handed.

Built on `webtask`'s primitives (observe, settle, frame-aware Hands, walk,
new-tab following, the approval and the press) rather than beside them:
one engine, a general layer on top.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from aletheia import (browse, browser_mission as bm, formfill, journal, page_state as ps,
                      policy, site_skills, stateio, webtask)

ACTOR = "aletheia-browser-loop"
MAX_STEPS = 30
DEFAULT_BUDGET = 20
ERROR_RETRIES = 2          # re-observing a failed page is always allowed
UNKNOWN_RETRIES = 2
MAX_TARGETS = 90

AUTONOMOUS, ASSISTED, MANUAL_ONLY = site_skills.AUTONOMOUS, site_skills.ASSISTED, site_skills.MANUAL_ONLY

#: Words that carry no meaning when matching a label to an input key.
FILLER = frozenset({"your", "you", "the", "a", "an", "of", "please", "enter", "full", "address",
                    "number", "type", "select", "choose", "provide", "our", "for", "to", "in",
                    "what", "is", "are", "my", "do", "and", "or", "if", "any", "this", "here"})


#: On a verification page, the button that sends only the CODE. Anything
#: else there (a "Submit application" beside the code box) still goes to
#: the approval.
_VERIFY_BUTTON = re.compile(r"^\s*(?:verify(?: \w+)?|confirm(?: (?:code|email|it))?|submit code|"
                            r"continue|next|done)\s*$", re.I)


class LoopError(RuntimeError):
    pass


# ---- observing ---------------------------------------------------------------

CAPTCHA_VISIBLE_JS = r"""() => {
  const marks = /hcaptcha|recaptcha|turnstile|challenges\.cloudflare/i;
  const big = (el) => { const r = el.getBoundingClientRect(); return r.width > 30 && r.height > 30; };
  for (const el of document.querySelectorAll('iframe[src]')) {
    if (marks.test(el.src || '') && big(el)) return (el.src.match(marks) || [''])[0].toLowerCase();
  }
  for (const el of document.querySelectorAll('.g-recaptcha, .h-captcha, .cf-turnstile, [data-captcha]')) {
    if (big(el)) return el.getAttribute('data-captcha') || el.className || 'captcha';
  }
  return '';
}"""
PROGRESSBAR_JS = r"""() => !!document.querySelector('[role=progressbar], progress, ol.steps, [aria-current=step]')"""


def _role_of_field(row: dict) -> str:
    kind = str(row.get("type") or "").casefold()
    if kind == "password":
        return "password"
    if kind == "file":
        return "file"
    if kind in ("checkbox", "switch"):
        return "checkbox"
    if kind == "radio" or row.get("is_option"):
        return "radio"
    if row.get("options"):
        return "combobox"
    return "textbox"


class StatusTracker:
    """The HTTP status of the main document, per page. A 500 is evidence
    only the network layer has; the page text may say nothing at all."""

    def __init__(self):
        self.codes: dict[int, int] = {}

    def watch(self, page) -> None:
        if id(page) in self.codes or not hasattr(page, "on"):
            return
        self.codes[id(page)] = 0

        def on_response(response, _page=page):
            try:
                if response.request.resource_type == "document" and response.frame == _page.main_frame:
                    self.codes[id(_page)] = int(response.status)
            except Exception:
                pass
        try:
            page.on("response", on_response)
        except Exception:
            pass

    def status(self, page) -> int | None:
        return self.codes.get(id(page)) or None


def look(page, *, tracker: StatusTracker | None = None, skill=None, site: dict | None = None) -> dict:
    """The page as semantic targets, classified. `_refs` (target id ->
    selector) and `_raw` (the form reader's rows) are internal and are
    stripped by `for_model` before anything leaves this module."""
    seen = webtask.observe(page)
    raw = seen.pop("_raw", None) or []
    targets: list[dict] = []
    refs: dict[str, str] = {}
    by_selector: set[str] = set()

    def add(role: str, label: str, selector: str, **extra) -> None:
        if not selector or selector in by_selector or len(targets) >= MAX_TARGETS:
            return
        by_selector.add(selector)
        tid = f"t{len(targets) + 1}"
        row = {"id": tid, "role": role, "label": " ".join(str(label or "").split())[:120]}
        row.update({k: v for k, v in extra.items() if v not in (None, "", [])})
        targets.append(row)
        refs[tid] = selector

    for field in seen.get("fields") or []:
        if str(field.get("type") or "").casefold() in ("hidden", "submit", "button", "image", "reset"):
            continue
        role = _role_of_field(field)
        if role == "radio" and field.get("is_option"):
            add(role, field["is_option"], field["selector"], question=field.get("label"),
                checked=field.get("checked"), required=field.get("required") or None)
            continue
        add(role, field.get("label"), field["selector"], value=field.get("value") or None,
            required=field.get("required") or None, options=field.get("options"),
            checked=field.get("checked") if role == "checkbox" else None)
    for button in seen.get("buttons") or []:
        role = str(button.get("role") or "button")
        role = "button" if role in ("button", "summary") else role
        add(role, button.get("text") or button.get("question"), button.get("selector", ""),
            question=button.get("question") if role != "button" else None,
            checked=button.get("checked"))
    for link in seen.get("links") or []:
        add("link", link.get("text"), link.get("selector", ""), href=link.get("href"))

    try:
        captcha = str(page.evaluate(CAPTCHA_VISIBLE_JS) or "")
    except Exception:
        captcha = ""
    try:
        progressbar = bool(page.evaluate(PROGRESSBAR_JS))
    except Exception:
        progressbar = False
    obs = {"url": seen.get("url", ""), "title": seen.get("title", ""), "text": seen.get("text", ""),
           "status": tracker.status(page) if tracker else None, "targets": targets,
           "still_missing": seen.get("still_missing") or [], "captcha": captcha,
           "progressbar": progressbar, "_refs": refs, "_raw": raw}
    understood = ps.classify(obs)
    obs.update({"state": understood["state"], "evidence": understood["evidence"],
                "controls": understood["controls"]})
    remembered = site_skills.known_state(site or {}, obs["url"]) if site else ""
    if remembered and obs["state"] == ps.UNKNOWN:
        obs["state"] = remembered
        obs["evidence"].append("a previous run confirmed this page shape")
    obs["annotations"] = list(skill.annotate(obs) if skill else [])
    return obs


def for_model(obs: dict, *, text_chars: int = 1_500) -> dict:
    """The observation a model (or a tool caller) sees: no selectors, no raw
    rows, bounded text, marked as somebody else's content."""
    return {"url": obs.get("url"), "title": obs.get("title"), "state": obs.get("state"),
            "evidence": obs.get("evidence"), "annotations": obs.get("annotations") or [],
            "status": obs.get("status"),
            "targets": [dict(t) for t in obs.get("targets") or []],
            "still_missing": [m.get("label") for m in obs.get("still_missing") or []
                              if isinstance(m, dict)][:10],
            "text": str(obs.get("text") or "")[:text_chars]}


# ---- targets -----------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(text or "").casefold()).split())


def find_target(obs: dict, spec: Any) -> dict | None:
    """A target by id ("t4"), or by {"role", "label"[, "nth"]}: exact
    accessible name first, then containment. Never by selector."""
    targets = obs.get("targets") or []
    if isinstance(spec, str):
        spec = {"id": spec} if re.fullmatch(r"t\d+", spec) else {"label": spec}
    if not isinstance(spec, dict):
        return None
    if spec.get("id"):
        return next((t for t in targets if t["id"] == spec["id"]), None)
    role, want = spec.get("role"), _norm(spec.get("label", ""))
    pool = [t for t in targets if not role or t["role"] == role]
    exact = [t for t in pool if _norm(t["label"]) == want]
    loose = [t for t in pool if want and want in _norm(t["label"])]
    found = exact or loose
    nth = int(spec.get("nth") or 0)
    return found[nth] if len(found) > nth else None


def content_words(text: str) -> set[str]:
    return {w for w in _norm(site_skills.normal_label(text)).split() if w not in FILLER}


def match_key(label: str, inputs: dict, site: dict | None = None) -> str | None:
    """Which of his inputs a label asks for. The site's learned alias first,
    then the same words, then one set of words inside the other - but only
    when the smaller side says at least two things, so "name" never
    answers "company name"."""
    if not inputs or not label:
        return None
    by_norm = {site_skills.normal_label(k.replace("_", " ")): k for k in inputs}
    alias = site_skills.alias_for(site or {}, label)
    if alias:
        if alias in inputs:
            return alias
        hit = by_norm.get(site_skills.normal_label(alias.replace("_", " ")))
        if hit:
            return hit
    mine = content_words(label)
    if not mine:
        return None
    best, best_size = None, 0
    for norm_key, key in by_norm.items():
        theirs = content_words(norm_key)
        if not theirs:
            continue
        if theirs == mine or (len(theirs) >= 2 and theirs <= mine) or (len(mine) >= 2 and mine <= theirs):
            if len(theirs) > best_size:
                best, best_size = key, len(theirs)
    return best


def _pick_option(options: list[str], value: str) -> str | None:
    want = _norm(value)
    for option in options or []:
        if _norm(option) == want:
            return option
    for option in options or []:
        if want and (want in _norm(option) or _norm(option) in want) and _norm(option):
            return option
    return None


# ---- skills ------------------------------------------------------------------

class GeneralSkill:
    """Fills a page from the goal's own structured inputs, and nothing else.

    The value gate is structural: every value typed is one of his inputs,
    copied, or an option the page itself offers that matches one. A
    required question none of them answers is a QUESTION for him, named
    exactly - never a plausible guess.
    """

    name = "general"

    def annotate(self, obs: dict) -> list[str]:
        return []

    def nav_words(self, goal: str) -> set[str]:
        return content_words(goal)

    def plan(self, obs: dict, record: dict, site: dict) -> dict:
        inputs = dict(record.get("inputs") or {})
        refs = obs.get("_refs") or {}
        fill, ask, aliases = [], [], {}
        radios: dict[str, list[dict]] = {}
        for t in obs.get("targets") or []:
            role = t["role"]
            if role in ("radio", "option") and t.get("question"):
                radios.setdefault(t["question"], []).append(t)
                continue
            if role not in ("textbox", "combobox", "checkbox", "file"):
                continue
            key = match_key(t["label"], inputs, site)
            if key is None:
                if t.get("required") and not str(t.get("value") or "").strip() and not t.get("checked"):
                    ask.append(t["label"])
                continue
            value = str(inputs[key])
            if t["label"] and site_skills.normal_label(t["label"]) != site_skills.normal_label(key.replace("_", " ")):
                aliases[t["label"]] = key
            selector = refs[t["id"]]
            if role == "checkbox":
                yes = value.strip().casefold() in ("yes", "true", "1", "on", "checked", "agree", "i agree")
                if bool(t.get("checked")) != yes:
                    fill.append({"action": "check" if yes else "uncheck", "selector": selector,
                                 "value": value, "label": t["label"], "key": key})
                continue
            if role == "file":
                path = Path(value)
                if path.is_file():
                    fill.append({"action": "attach", "selector": selector, "value": str(path),
                                 "label": t["label"], "key": key})
                elif t.get("required"):
                    ask.append(t["label"])
                continue
            if role == "combobox" and t.get("options"):
                option = _pick_option(t["options"], value)
                if option is None:
                    ask.append(f"{t['label']} (none of its choices is {value!r})")
                    continue
                if _norm(t.get("value")) in (_norm(option),):
                    continue
                fill.append({"action": "select", "selector": selector, "value": option,
                             "label": t["label"], "key": key})
                continue
            if str(t.get("value") or "").strip() == value.strip():
                continue
            fill.append({"action": "type", "selector": selector, "value": value,
                         "label": t["label"], "key": key})
        for question, choices in radios.items():
            key = match_key(question, inputs, site)
            required = any(c.get("required") for c in choices)
            if key is None:
                if required and not any(c.get("checked") for c in choices):
                    ask.append(question)
                continue
            if question and site_skills.normal_label(question) != site_skills.normal_label(key.replace("_", " ")):
                aliases[question] = key
            chosen = _pick_option([c["label"] for c in choices], str(inputs[key]))
            target = next((c for c in choices if c["label"] == chosen), None)
            if target is None:
                ask.append(f"{question} (none of its choices is {inputs[key]!r})")
            elif not target.get("checked"):
                fill.append({"action": "click", "selector": refs[target["id"]], "value": chosen,
                             "label": question, "key": key})
        return {"fill": fill, "ask": ask, "aliases": aliases}


GENERAL = GeneralSkill()


# ---- choosing a way forward ----------------------------------------------------

def _kind(t: dict, obs: dict) -> str:
    on_form = any(x["role"] in ("textbox", "combobox", "checkbox", "radio", "file", "password")
                  for x in obs.get("targets") or [])
    return ps.control_kind(t["label"], role=t["role"], on_form=on_form)


def controls(obs: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for t in obs.get("targets") or []:
        if t["role"] in ps.PRESS_ROLES:
            out.setdefault(_kind(t, obs), []).append(t)
    return out


def way_forward(obs: dict, goal: str, skill, site: dict, *, tried: set[str]) -> dict | None:
    """The link or harmless control that best moves toward the goal.

    A learned or seeded nav hint for this state wins; otherwise the control
    whose name shares the most content words with the goal (and the
    skill's own words). Never a commit, a sign-in, a payment or Back."""
    kinds = controls(obs)
    candidates = kinds.get(ps.NAVIGATE, []) + kinds.get(ps.PROGRESS, []) + kinds.get(ps.OTHER, [])
    candidates = [c for c in candidates if c["id"] not in tried and c["label"]]
    if not candidates:
        return None
    for hint in site.get("nav_hints") or []:
        if hint.get("from_state") and hint["from_state"] != obs.get("state"):
            continue
        found = next((c for c in candidates if _norm(c["label"]) == _norm(hint.get("label"))), None)
        if found:
            return found
    progress = kinds.get(ps.PROGRESS, [])
    progress = [c for c in progress if c["id"] not in tried]
    if progress:
        return progress[0]
    wanted = skill.nav_words(goal)
    best, score = None, 0
    for c in candidates:
        overlap = len(content_words(c["label"]) & wanted)
        if overlap > score:
            best, score = c, overlap
    return best


# ---- the loop ------------------------------------------------------------------

def _effective_mode(requested: str, site: dict) -> str:
    rank = {AUTONOMOUS: 0, ASSISTED: 1, MANUAL_ONLY: 2}
    requested = requested if requested in rank else AUTONOMOUS
    return max(requested, site.get("mode") or AUTONOMOUS, key=lambda m: rank.get(m, 2))


def _say_boundary(kind: str, url: str, **bits) -> str:
    where = url[:90]
    if kind == ps.CAPTCHA:
        return (f"A human check is in the way at {where}. I do not solve those. Everything before "
                "it is done and saved; pass the check yourself and tell me to carry on.")
    if kind == "SIGN_IN":
        return (f"This wants you signed in at {where}. I do not keep that password. Sign in once "
                f"(python -m aletheia.browse login {where}) and tell me to carry on.")
    if kind == "QUESTIONS":
        return ("I need your answers for: " + "; ".join(bits.get("questions") or [])[:400]
                + ". I will not make them up.")
    if kind == "WAITING_FOR_LINK":
        return (f"The site emailed a verification link for {where}. Give it to me (or open it "
                "yourself) and I will carry on from there.")
    if kind == "WAITING_FOR_CODE":
        return (f"The site sent a {bits.get('via', 'verification')} code for {where}. Give it to me "
                "and I will type it in and carry on.")
    if kind == "ERROR":
        return (f"The site kept failing at {where} ({bits.get('why', 'an error page')}); I looked "
                f"again {ERROR_RETRIES} times. Nothing was submitted.")
    if kind == "MANUAL_ONLY":
        return (f"{bits.get('because', 'This site forbids automation')}. Open {where} yourself; I "
                "will not drive it.")
    if kind == "NO_WAY_FORWARD":
        return (f"I am on {bits.get('page', 'a page')} at {where} and nothing on it moves toward the "
                "goal without a guess. Tell me what to press.")
    if kind == "DUPLICATE_SUBMIT":
        return str(bits.get("why") or "That was already pressed once.")
    if kind == "NO_VAULT":
        return f"Making an account at {where} needs a password vault, and there is none: {bits.get('why', '')}"
    return str(bits.get("say") or kind)


def _stop(record: dict, state: str, kind: str, obs: dict | None, step: str = "", **bits) -> dict:
    url = (obs or {}).get("url") or record.get("start_url") or ""
    boundary = {"kind": kind, "url": url, "page_state": (obs or {}).get("state", ""),
                "step": step, "say": _say_boundary(kind, url, **bits)}
    boundary.update({k: v for k, v in bits.items() if k in ("questions", "via", "why", "because") and v})
    record = bm.stop_at(record, state, boundary)
    if kind in (ps.CAPTCHA, "SIGN_IN", "WAITING_FOR_CODE", "ERROR", "MANUAL_ONLY") and url:
        site_skills.learn(url, boundary={"kind": kind, "note": boundary["say"][:180]})
    # WHAT HE TRIED AND COULD NOT HAVE (CLAUDE.md: every doing path reports).
    # A run that stopped at an account wall is a better fact about what to
    # build than any guess.
    try:
        from aletheia import demand
        said = {"SIGN_IN": "NEEDS_SIGN_IN", ps.CAPTCHA: "NEEDS_YOUR_EYES",
                "OUT_OF_STEPS": "OUT_OF_STEPS"}.get(kind) or (
            "REFUSED" if state in (bm.REFUSED, bm.MANUAL_ONLY) else "NEEDS_YOU")
        demand.record_attempt("web.task", record.get("goal", ""), said, detail=boundary["say"][:200],
                              source="browser_loop")
    except Exception:
        pass
    return record


class _Crash(BaseException):
    """Raised by a test hook to stand in for the process dying mid-run."""


def pursue(goal: str, start_url: str, *, inputs: dict | None = None, mode: str = AUTONOMOUS,
           skill=None, decide: Callable | None = None, session=None, budget: int = DEFAULT_BUDGET,
           code_source: Callable | None = None, on_step: Callable | None = None) -> dict:
    """Drive toward a goal until it is done or stops at a named boundary.

    Resumes the mission if one exists for this goal and page: the route is
    replayed, not redone, and a submission already made is never made
    again without proof it failed. Returns the mission record.
    """
    policy.ensure_not_halted()
    goal = " ".join(str(goal or "").split())
    if not goal:
        raise ValueError("say what the goal is")
    skill = skill or GENERAL
    site = site_skills.for_domain(start_url)
    record = bm.open_mission(goal, start_url, inputs=inputs, mode=mode, skill=skill.name)
    if webtask.would_spend(goal):
        return _stop(record, bm.REFUSED, "SPENDING", None, say=webtask.SPENDING_REFUSAL)
    record = sync(record)
    if record.get("state") in (bm.DONE, bm.AWAITING_APPROVAL, bm.SUBMITTING,
                               bm.SUBMITTED_UNCONFIRMED, bm.REFUSED):
        return record              # nothing to drive: done, waiting on him, or never
    effective = _effective_mode(mode, site)
    if effective == MANUAL_ONLY:
        return _stop(record, bm.MANUAL_ONLY, "MANUAL_ONLY", {"url": start_url},
                     because=site.get("manual_only_because") or "This site's terms forbid automation")
    record.update({"mode": effective, "state": bm.RUNNING, "boundary": None})
    record.setdefault("history", []).append({"at": stateio.utcnow(), "did": "started" if not record.get("route") else
                                             f"resumed: replaying {len(record['route'])} step(s) already done"})
    bm.save(record)
    budget = max(1, min(int(budget), MAX_STEPS))
    opener = session or browse._Session
    with opener() as ctx:
        page = ctx.new_page()
        try:
            return _drive(ctx, page, record, goal, skill, site, decide=decide, budget=budget,
                          code_source=code_source, on_step=on_step)
        finally:
            try:
                page.close()
            except Exception:
                pass


def resume(mid: str, *, done: str = "", answers: dict | None = None, **kwargs) -> dict:
    """Carry on after he passed a boundary (a CAPTCHA, a sign-in), or after a
    crash. The mission's route is replayed; nothing already submitted is
    pressed again."""
    force = bool(kwargs.pop("force", False))
    record = bm.load(mid)
    if record.get("state") == bm.RUNNING and not bm.stale(record) and not force:
        raise LoopError(f"{mid} is running right now")
    if done:
        record.setdefault("history", []).append({"at": stateio.utcnow(), "did": f"he says he passed: {done}"})
    if answers:
        # HIS ANSWERS ARE INPUTS: the questions she stopped on are answered
        # from them on the replayed page, and nothing he answered before is
        # asked again.
        record["inputs"] = {**(record.get("inputs") or {}), **{str(k): v for k, v in answers.items()}}
        record.setdefault("history", []).append(
            {"at": stateio.utcnow(), "did": f"he answered {len(answers)} question(s)"})
    if record.get("state") in (bm.NEEDS_YOU, bm.RUNNING, bm.REJECTED):
        record["state"] = bm.RUNNING
    bm.save(record)
    return pursue(record["goal"], record["start_url"], inputs=record.get("inputs"),
                  mode=record.get("mode") or AUTONOMOUS, **kwargs)


def _replay_from(record: dict) -> str:
    return record.get("resume_url") or record.get("start_url") or ""


def _load(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    webtask.settle(page)


def _drive(ctx, page, record: dict, goal: str, skill, site: dict, *, decide, budget: int,
           code_source, on_step) -> dict:
    tracker = StatusTracker()
    tracker.watch(page)
    hands = webtask._Hands(page)
    route = list(record.get("route") or [])
    attached = list(record.get("attached") or [])
    try:
        _load(page, _replay_from(record))
        if route:
            page = webtask.walk(ctx, page, hands, route, {a["selector"]: a["path"] for a in attached})
            hands.page = page
            tracker.watch(page)
    except Exception as exc:                                  # noqa: BLE001
        return _stop(record, bm.NEEDS_YOU, "ERROR", {"url": _replay_from(record)},
                     why=f"the page could not be put back ({browse.say_reason(str(exc))[:160]})")
    errors = unknowns = 0
    tried: set[str] = set()
    written: set[tuple[str, str]] = set()
    last_seen = ("", "")
    for step in range(budget):
        policy.ensure_not_halted()
        if on_step is not None:
            on_step(step, record)
        obs = look(page, tracker=tracker, skill=skill, site=site)
        state = obs["state"]
        if (obs["url"], state) != last_seen:
            record = bm.checkpoint(record, bm.OBSERVED, url=obs["url"], state=state)
            last_seen = (obs["url"], state)
            tried = set()
            site_skills.learn(obs["url"], state=state)

        if state == ps.ERROR:
            errors += 1
            if errors <= ERROR_RETRIES:
                _note(record, f"the page failed ({'; '.join(obs['evidence'])}); looking again")
                try:
                    _load(page, obs["url"] or _replay_from(record))
                    if route:
                        page = webtask.walk(ctx, page, hands, route,
                                            {a["selector"]: a["path"] for a in attached})
                        hands.page = page
                except Exception:
                    pass
                continue
            return _stop(record, bm.NEEDS_YOU, "ERROR", obs, why="; ".join(obs["evidence"]))
        errors = 0

        if state == ps.CAPTCHA:
            # ASSISTED: do everything allowed first, then stop at the exact
            # remaining step. The answers go in (and into the route, so they
            # come back on resume); the check and the press stay his.
            record["mode"] = ASSISTED
            planned = skill.plan(obs, record, site)
            fresh = [i for i in planned["fill"] if (obs["url"], i["selector"]) not in written]
            written.update((obs["url"], i["selector"]) for i in fresh)
            if _apply(page, hands, fresh, route, attached):
                record["route"], record["attached"] = route, attached
                record = bm.checkpoint(record, bm.FILLED, url=obs["url"], before="a human check")
            final = (controls(obs).get(ps.COMMIT) or controls(obs).get(ps.PROGRESS) or [{}])[0]
            return _stop(record, bm.NEEDS_YOU, ps.CAPTCHA, obs,
                         step=f"pass the human check on {obs['url'][:90]}"
                              + (f", then {final['label']!r} is next" if final.get("label") else ""),
                         questions=planned["ask"][:12] or None)
        if state == ps.ACCOUNT_LOGIN:
            # HER OWN ACCOUNT, on the exact host she made it on, with the
            # password only the vault holds. Anything else - his accounts,
            # a second try after the site said no - is his.
            signed = _sign_in(ctx, page, hands, obs, record, route, tracker)
            if signed is not None:
                page = signed
                record["route"] = route
                bm.save(record)
                continue
            return _stop(record, bm.NEEDS_YOU, "SIGN_IN", obs, step=f"sign in at {obs['url'][:90]}")
        if state == ps.SUCCESS:
            if bm.reached(record, bm.SUBMIT_CLICKED) or bm.reached(record, bm.REVIEW_REACHED):
                record = bm.checkpoint(record, bm.RECEIPT_VERIFIED, url=obs["url"],
                                       note="the site shows its confirmation")
                record["state"] = bm.DONE
                record["boundary"] = None
                return bm.checkpoint(record, bm.FINISHED, url=obs["url"])
            state = ps.CONTENT
        if state == ps.UNKNOWN:
            unknowns += 1
            if unknowns <= UNKNOWN_RETRIES:
                webtask.settle(page)
                continue
            return _stop(record, bm.NEEDS_YOU, "NO_WAY_FORWARD", obs, page=ps.say(state))

        if state == ps.EMAIL_VERIFICATION and not any(t["role"] == "textbox" for t in obs["targets"]):
            # A LINK, not a code: "we sent a verification link". Following it
            # is navigation, allowed only onto the same site.
            link = bm.take_event(record, "link")
            if not link and code_source is not None:
                try:
                    link = str(code_source(record, "link") or "")
                except Exception:
                    link = ""
            if not link:
                return _stop(record, bm.NEEDS_YOU, "WAITING_FOR_LINK", obs, via="email",
                             step="open the verification link the site emailed")
            if not _same_site(link, obs["url"]):
                return _stop(record, bm.NEEDS_YOU, "LINK_ELSEWHERE", obs,
                             say=f"The verification link goes to {site_skills.domain_of(link)}, not this "
                                 "site, so I did not follow it. Open it yourself and tell me to carry on.")
            _load(page, link)
            route.append({"action": "goto", "selector": "", "value": link})
            record["route"] = route
            _note(record, "followed the emailed verification link")
            continue

        if state in (ps.EMAIL_VERIFICATION, ps.SMS_VERIFICATION):
            via = "text" if state == ps.SMS_VERIFICATION else "email"
            code = bm.take_event(record, "code")
            if not code and code_source is not None:
                try:
                    code = str(code_source(record, via) or "")
                except Exception:
                    code = ""
            if not code:
                return _stop(record, bm.NEEDS_YOU, "WAITING_FOR_CODE", obs, via=via,
                             step="type the code the site sent")
            box = next((t for t in obs["targets"] if t["role"] == "textbox"), None)
            # Into the route too: the approved press replays the route in a
            # fresh browser, and a wizard behind a code is not reachable
            # without it. (A site whose codes expire fails that replay
            # honestly - the verdict is not proof, so nothing is re-sent.)
            _apply(page, hands, [{"action": "type", "selector": obs["_refs"][box["id"]],
                                  "value": code, "label": box["label"]}], route, attached)
            _note(record, f"typed the {via} code into {box['label'][:40]!r}")
            kinds = controls(obs)
            press = next((c for kind in (ps.PROGRESS, ps.OTHER, ps.COMMIT) for c in kinds.get(kind, [])
                          if kind != ps.COMMIT or _VERIFY_BUTTON.search(c["label"])), None)
            if press is None:
                result = _gate(ctx, page, obs, record, goal, route, attached)
                if result is not None:
                    return result
                continue
            page = _click(ctx, page, hands, obs["_refs"][press["id"]], route, tracker)
            continue

        if state in (ps.FORM, ps.MULTI_PAGE_WIZARD, ps.REVIEW, ps.ACCOUNT_SIGNUP):
            planned = skill.plan(obs, record, site)
            if state == ps.ACCOUNT_SIGNUP:
                extra = _signup_passwords(obs, record)
                if isinstance(extra, dict):         # a boundary
                    return extra
                planned["fill"] += extra
                named = next((i for i in planned["fill"] if i["action"] == "type"
                              and _USERNAME.search(str(i.get("label") or ""))), None)
                if named and record.get("account"):
                    record["account"]["username"] = named["value"]
            # ONE WRITE PER FIELD PER PAGE. A select reads back its option's
            # VALUE ("tue") while his input is the option's words ("Tuesday"),
            # and without this the two never agree and the budget goes on
            # choosing Tuesday forever.
            fresh = [item for item in planned["fill"]
                     if (obs["url"], item["selector"]) not in written]
            written.update((obs["url"], item["selector"]) for item in fresh)
            done_now = _apply(page, hands, fresh, route, attached)
            if planned.get("aliases"):
                site_skills.learn(obs["url"], aliases=planned["aliases"])
            if done_now:
                record["route"], record["attached"] = route, attached
                record = bm.checkpoint(record, bm.FILLED, url=obs["url"], count=len(done_now))
                continue                            # look again: the page changed
            if planned["ask"]:
                return _stop(record, bm.NEEDS_YOU, "QUESTIONS", obs, questions=planned["ask"][:12],
                             step="answer what only you can")
            kinds = controls(obs)
            nxt = [c for c in kinds.get(ps.PROGRESS, []) if c["id"] not in tried]
            if nxt and state != ps.REVIEW:
                tried.add(nxt[0]["id"])
                before = obs["url"]
                page = _click(ctx, page, hands, obs["_refs"][nxt[0]["id"]], route, tracker)
                record["route"] = route
                bm.save(record)
                site_skills.learn(before, hint={"from_state": state, "role": nxt[0]["role"],
                                                "label": nxt[0]["label"], "led_to": "next page"})
                continue
            if kinds.get(ps.COMMIT) or kinds.get(ps.CREATE_ACCOUNT) or kinds.get(ps.SPEND):
                result = _gate(ctx, page, obs, record, goal, route, attached)
                if result is not None:
                    return result
                continue
            state = ps.CONTENT                      # a form with no way on: look for one

        if state == ps.CONTENT:
            target = way_forward(obs, goal, skill, site, tried=tried)
            if target is None and decide is not None:
                target = _ask_model(decide, goal, obs, record)
            if target is None:
                return _stop(record, bm.NEEDS_YOU, "NO_WAY_FORWARD", obs, page=ps.say(obs["state"]))
            tried.add(target["id"])
            before, before_state = obs["url"], obs["state"]
            page = _click(ctx, page, hands, obs["_refs"][target["id"]], route, tracker)
            record["route"] = route
            bm.save(record)
            _note(record, f"followed {target['label'][:50]!r}")
            site_skills.learn(before, hint={"from_state": before_state, "role": target["role"],
                                            "label": target["label"], "led_to": "onward"})
            continue
    return _stop(record, bm.NEEDS_YOU, "OUT_OF_STEPS", None,
                 say=f"I used all {budget} steps without finishing. Everything so far is saved; "
                     "tell me to carry on.")


def _note(record: dict, text: str) -> None:
    rows = record.setdefault("history", [])
    rows.append({"at": stateio.utcnow(), "did": str(text)[:200]})
    record["history"] = rows[-60:]
    bm.save(record)


def _ask_model(decide: Callable, goal: str, obs: dict, record: dict) -> dict | None:
    """A model picks a control when the deterministic reading has none. It
    names a target; the loop still refuses anything that commits."""
    try:
        said = decide(goal, for_model(obs), list(record.get("history") or [])[-6:])
    except Exception:
        return None
    target = find_target(obs, (said or {}).get("target")) if isinstance(said, dict) else None
    if target is None or _kind(target, obs) in (ps.COMMIT, ps.CREATE_ACCOUNT, ps.SPEND, ps.SIGN_IN):
        return None
    return target


def _apply(page, hands, fill: list[dict], route: list[dict], attached: list[dict]) -> list[str]:
    done = []
    for item in fill:
        selector, action, value = item["selector"], item["action"], item.get("value", "")
        try:
            if action == "type":
                hands.fill(selector, value)
            elif action == "select":
                hands.select_option(selector, label=value)
            elif action == "check":
                hands.check(selector)
            elif action == "uncheck":
                hands.uncheck(selector)
            elif action == "click":
                hands.click(selector)
            elif action == "attach":
                hands.set_input_files(selector, value)
                attached.append({"selector": selector, "path": value})
                done.append(item.get("label", ""))
                continue
            elif action == "secret":
                from aletheia import secret_store
                hands.fill(selector, secret_store.get(item["alias"]))
                route.append({"action": "secret", "selector": selector, "alias": item["alias"]})
                done.append(item.get("label", ""))
                continue
            else:
                continue
        except Exception:
            continue
        route.append({"action": action, "selector": selector, "value": value})
        done.append(item.get("label", ""))
    return done


def _click(ctx, page, hands, selector: str, route: list[dict], tracker: StatusTracker):
    before = webtask._open_pages(ctx)
    hands.click(selector)
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    moved = webtask.follow_new_tab(ctx, page, before)
    route.append({"action": "click", "selector": selector})
    webtask.settle(moved)
    if moved is not page:
        route.append({"action": "new_tab", "selector": ""})
        hands.page = moved
        tracker.watch(moved)
    return moved


def _signup_passwords(obs: dict, record: dict):
    """Password boxes on an account form: a new password, kept ONLY in the
    vault (`signup` owns that rule). Returns fill items, or a boundary."""
    from aletheia import signup
    boxes = [t for t in obs["targets"] if t["role"] == "password"]
    if not boxes:
        return []
    host = site_skills.domain_of(obs["url"])
    alias = signup.account_alias(host)
    try:
        from aletheia import secret_store
        have = secret_store.exists(alias)
    except Exception:
        have = False
    if not have:
        ok, why = signup.vault_ready()
        if not ok:
            return _stop(record, bm.NEEDS_YOU, "NO_VAULT", obs, why=why)
        signup._vault().put(alias, signup.new_password(), provider=host, kind="account")
    record["account"] = {"host": host, "alias": alias}
    return [{"action": "secret", "selector": obs["_refs"][b["id"]], "alias": alias,
             "label": b["label"]} for b in boxes if not str(b.get("value") or "")]


_USERNAME = re.compile(r"e-?mail|user\s*name|username|login|user id", re.I)


def _same_site(url: str, here: str) -> bool:
    a, b = site_skills.domain_of(url), site_skills.domain_of(here)
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def _sign_in(ctx, page, hands, obs: dict, record: dict, route: list[dict], tracker):
    """Sign in with an account SHE made on this exact host (signup's store and
    the vault), once per page. Returns the page after, or None."""
    from aletheia import signup
    host = site_skills.domain_of(obs["url"])
    try:
        account = signup.known_account(host)
        from aletheia import secret_store
        have = bool(account) and secret_store.exists(account["alias"])
    except Exception:
        account, have = None, False
    tries = record.setdefault("sign_ins", {})
    if not have or tries.get(site_skills.path_of(obs["url"]), 0) >= 1:
        return None
    user = next((t for t in obs["targets"] if t["role"] == "textbox" and _USERNAME.search(t["label"])), None)
    boxes = [t for t in obs["targets"] if t["role"] == "password"]
    button = (controls(obs).get(ps.SIGN_IN) or [None])[0]
    if not (user and boxes and button and account.get("username")):
        return None
    tries[site_skills.path_of(obs["url"])] = 1
    _apply(page, hands, [{"action": "type", "selector": obs["_refs"][user["id"]],
                          "value": account["username"], "label": user["label"]}]
           + [{"action": "secret", "selector": obs["_refs"][b["id"]], "alias": account["alias"],
               "label": b["label"]} for b in boxes], route, [])
    _note(record, f"signed in with the account I made at {host}")
    return _click(ctx, page, hands, obs["_refs"][button["id"]], route, tracker)


def _gate(ctx, page, obs: dict, record: dict, goal: str, route: list[dict],
          attached: list[dict]) -> dict | None:
    """The final button: refused (money), refused (a duplicate), a question
    (the page says something is still empty), or ONE hash-bound approval
    through the existing webtask path. Returns the stopped record."""
    kinds = controls(obs)
    if kinds.get(ps.SPEND) and not (kinds.get(ps.COMMIT) or kinds.get(ps.CREATE_ACCOUNT)):
        label = kinds[ps.SPEND][0]["label"]
        return _stop(record, bm.REFUSED, "SPENDING", obs,
                     say=f"The way on is a button that says {label[:60]!r}, which spends money. "
                         "I stopped and did not press it.")
    target = (kinds.get(ps.CREATE_ACCOUNT) or kinds.get(ps.COMMIT))[0]
    kind = _kind(target, obs)
    if obs["state"] == ps.REVIEW or not bm.reached(record, bm.REVIEW_REACHED):
        record = bm.checkpoint(record, bm.REVIEW_REACHED, url=obs["url"], button=target["label"])
    ok, why = bm.may_submit_here(record, button=target["label"], url=obs["url"])
    if not ok:
        return _stop(record, bm.NEEDS_YOU, "DUPLICATE_SUBMIT", obs, why=why,
                     step="check whether the earlier press went through")
    try:
        empty = [row["label"] for row in formfill.blocking(page)]
    except Exception:
        empty = []
    if empty:
        return _stop(record, bm.NEEDS_YOU, "QUESTIONS", obs, questions=empty[:12],
                     step="answer what the form still needs")
    selector = obs["_refs"][target["id"]]
    commits = webtask.computer.committing_label(target["label"]) or target["label"] or "submit"
    replay = _replay_from(record)
    # ONE WEBTASK RUN PER GATE. The approval id is the route's digest, so a
    # retry after a rejection (same route) under the same run id would find
    # his FIRST yes already on file and already consumed; a fresh run id per
    # gate means every press asks him again, which is the point.
    record["gates"] = int(record.get("gates") or 0) + 1
    run_id = f"{record['id']}--g{record['gates']}"
    out = webtask._await_him(run_id, goal, page, target["label"], selector, list(route),
                             list(attached), commits, start_url=replay)
    webtask_record = {"id": run_id, "goal": goal, "steps": [], "attempt": record.get("attempt", 1),
                      "downloaded": [], "url": page.url, "title": obs.get("title", ""),
                      "mission": record["id"], "at": stateio.utcnow(), **out}
    stateio.write_json_atomic(webtask._record_path(run_id), webtask_record)
    record["route"], record["attached"] = route, attached
    record["approval"] = out["approval"]
    record["webtask_run"] = run_id
    record["gate"] = {"button": target["label"], "kind": kind, "url": obs["url"]}
    boundary_kind = "ACCOUNT_CREATION_APPROVAL" if kind == ps.CREATE_ACCOUNT else "SUBMIT_APPROVAL"
    record = bm.stop_at(record, bm.AWAITING_APPROVAL, {
        "kind": boundary_kind, "url": obs["url"], "page_state": obs["state"],
        "step": f"press {target['label']!r}", "approval": out["approval"], "say": out["say"]})
    journal.append("action", "browser-loop",
                   f"{boundary_kind} for {goal[:80]} - waiting on his yes", actor=ACTOR,
                   refs=[f"approval:{out['approval']}"])
    return record


# ---- the press, folded back into the mission -------------------------------------

def before_press(webtask_record: dict) -> None:
    """Called by `webtask.commit` BEFORE a mission's button is pressed,
    whichever path pressed it (the Core's beat or a command). Enforces the
    invariant and writes submit_clicked to disk first."""
    mid = webtask_record.get("mission")
    if not mid or not bm.exists(mid):
        return
    record = bm.load(mid)
    button = str(webtask_record.get("button") or "")
    url = str((record.get("gate") or {}).get("url") or webtask_record.get("url") or "")
    ok, why = bm.may_submit_here(record, button=button, url=url)
    if not ok:
        raise bm.DuplicateSubmission(why)
    bm.begin_submit(record, button=button, approval=str(webtask_record.get("approval") or ""), url=url)


def after_press(webtask_record: dict, result: dict | None, error: BaseException | None = None) -> dict:
    """What the site said, into the mission. A server error after a press
    is NOT proof the submission failed; only the site handing the form
    back is. Returns the (possibly corrected) result."""
    result = dict(result or {})
    mid = webtask_record.get("mission")
    if not mid or not bm.exists(mid):
        return result
    record = bm.load(mid)
    gate = record.get("gate") or {}
    if error is not None:
        bm.end_submit(record, verdict="error", evidence=f"{type(error).__name__}: {error}"[:300],
                      note="The press failed partway; whether it reached the site is unknown, so "
                           "it will not be pressed again without proof.")
        return result
    evidence = str(result.get("evidence") or "")
    verdict = str(result.get("verdict") or "submitted, unconfirmed")
    after = ps.classify({"text": evidence, "title": result.get("title", ""), "url": result.get("url", ""),
                         "targets": []})
    if after["state"] == ps.ERROR:
        verdict = "error"
        result.update({"verdict": verdict, "note": "The site errored after the press. That is not "
                       "proof it failed, so I will not press it again without checking."})
    elif verdict != "confirmed" and after["state"] == ps.SUCCESS:
        verdict = "confirmed"
        result.update({"verdict": verdict, "note": "The page says it went through."})
    elif verdict != "confirmed" and gate.get("kind") == ps.CREATE_ACCOUNT and after["state"] in (
            ps.EMAIL_VERIFICATION, ps.SMS_VERIFICATION, ps.ACCOUNT_LOGIN):
        verdict = "confirmed"
        result.update({"verdict": verdict, "note": "The site made the account and moved on to "
                                                   "verifying it."})
    record = bm.end_submit(record, verdict=verdict, evidence=evidence, url=str(result.get("url") or ""),
                           note=str(result.get("note") or ""))
    if verdict == "confirmed" and gate.get("kind") == ps.CREATE_ACCOUNT:
        # AN ACCOUNT IS A STEP, NOT THE GOAL. The route to here must never be
        # replayed (it ends in the press that made the account), so the next
        # leg starts from where the press landed.
        account = record.get("account") or {}
        if account.get("host") and account.get("username"):
            try:
                from aletheia import signup
                signup.record_account(account["host"], username=account["username"],
                                      provider=",".join(site_skills.for_domain(account["host"])["families"]))
            except Exception:
                pass
        record.update({"state": bm.RUNNING, "resume_url": str(result.get("url") or ""),
                       "route_before_account": record.get("route") or [], "route": [], "attached": [],
                       "boundary": None})
        record["checkpoints"] = [c for c in record["checkpoints"] if c.get("name") != bm.FINISHED]
        bm.save(record)
    try:
        site_skills.count_run(record.get("start_url", ""))
    except Exception:
        pass
    return result


def sync(record: dict) -> dict:
    """A mission waiting on an approval, reconciled with the webtask record
    the press path writes (the hooks already did this if they ran)."""
    if record.get("state") != bm.AWAITING_APPROVAL:
        return record
    try:
        pressed = webtask.load_run(record.get("webtask_run") or record["id"])
    except Exception:
        return record
    try:
        decided = policy.load(record.get("approval") or "").get("state")
    except Exception:
        decided = None
    if decided in ("DENIED", "EXPIRED") and pressed.get("state") == webtask.COMMIT:
        return bm.stop_at(record, bm.NEEDS_YOU, {
            "kind": "APPROVAL_" + decided, "url": pressed.get("url", ""),
            "say": f"You said no to pressing {pressed.get('button', 'it')!r}, so nothing was sent."
                   if decided == "DENIED" else "The approval expired before anyone pressed it; "
                                               "nothing was sent."})
    if pressed.get("state") == "COMMITTING" and record.get("state") == bm.AWAITING_APPROVAL:
        return bm.stop_at(record, bm.SUBMITTING, {"kind": "UNCONFIRMED", "url": pressed.get("url", ""),
                                                  "say": "The press started and its outcome was never "
                                                         "recorded; it will not be pressed again."})
    return bm.load(record["id"])


def commit(mid: str, *, presser=None) -> dict:
    """Press the approved button of a mission - the existing webtask path,
    with the mission's hooks. Returns the mission record."""
    record = bm.load(mid)
    if not record.get("webtask_run"):
        raise LoopError(f"{mid} has no button waiting to be pressed")
    webtask.commit(record["webtask_run"], presser=presser)
    return bm.load(mid)


def post_code(mid: str, code: str, *, source: str = "operator") -> dict:
    code = str(code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{4,12}", code):
        raise ValueError("a verification code is 4 to 12 letters or digits")
    return bm.post_event(mid, "code", code, source=source)


# ---- one action, for a tool ---------------------------------------------------

ACTS = ("fill", "select", "check", "uncheck", "click", "follow")


def act(mid: str, action: dict, *, session=None) -> dict:
    """One semantic action on a mission's page: replay the route, do it
    through the same gates, look again, checkpoint. A control that commits
    is not pressed here - it becomes the approval `_gate` makes."""
    policy.ensure_not_halted()
    record = bm.load(mid)
    if record.get("state") in (bm.DONE, bm.AWAITING_APPROVAL, bm.SUBMITTING, bm.SUBMITTED_UNCONFIRMED,
                               bm.REFUSED, bm.MANUAL_ONLY):
        return {"mission": bm.describe(record), "state": record.get("state"), "done": False}
    verb = str(action.get("act") or "")
    if verb not in ACTS:
        raise ValueError(f"act must be one of {ACTS}")
    site = site_skills.for_domain(record["start_url"])
    opener = session or browse._Session
    with opener() as ctx:
        page = ctx.new_page()
        tracker = StatusTracker()
        tracker.watch(page)
        hands = webtask._Hands(page)
        route = list(record.get("route") or [])
        attached = list(record.get("attached") or [])
        _load(page, _replay_from(record))
        if route:
            page = webtask.walk(ctx, page, hands, route, {a["selector"]: a["path"] for a in attached})
            hands.page = page
        obs = look(page, tracker=tracker, site=site)
        target = find_target(obs, action.get("target"))
        if target is None:
            return {"done": False, "problem": "no such target on the page", "page": for_model(obs)}
        kind = _kind(target, obs) if target["role"] in ps.PRESS_ROLES else "answer"
        selector = obs["_refs"][target["id"]]
        if verb in ("click", "follow") and kind in (ps.COMMIT, ps.CREATE_ACCOUNT, ps.SPEND):
            stopped = _gate(ctx, page, obs, record, record["goal"], route, attached)
            return {"done": False, "mission": bm.describe(stopped), "state": stopped.get("state"),
                    "boundary": stopped.get("boundary")}
        if verb in ("click", "follow") and kind == ps.SIGN_IN:
            stopped = _stop(record, bm.NEEDS_YOU, "SIGN_IN", obs)
            return {"done": False, "mission": bm.describe(stopped), "state": stopped.get("state")}
        value = str(action.get("value") or "")
        inputs = {str(v) for v in (record.get("inputs") or {}).values()}
        if verb in ("fill", "select") and value not in inputs and \
                _pick_option(target.get("options") or [], value) is None:
            return {"done": False, "problem": "that value is not one of his inputs or the page's own "
                                              "choices; I will not type a guess", "page": for_model(obs)}
        if verb in ("click", "follow"):
            page = _click(ctx, page, hands, selector, route, tracker)
        else:
            _apply(page, hands, [{"action": {"fill": "type"}.get(verb, verb), "selector": selector,
                                  "value": value, "label": target["label"]}], route, attached)
        record["route"], record["attached"] = route, attached
        after = look(page, tracker=tracker, site=site)
        record = bm.checkpoint(record, bm.FILLED if verb in ("fill", "select", "check", "uncheck")
                               else bm.OBSERVED, url=after["url"], state=after["state"])
        page.close()
    return {"done": True, "page": for_model(after), "mission": bm.describe(record)}


def observe_url(url: str, *, session=None) -> dict:
    """Open a page, read it as semantic targets, close it. Reading only."""
    policy.ensure_not_halted()
    if not re.match(r"^https?://", str(url or "")):
        raise ValueError("observe needs an http(s) url")
    site = site_skills.for_domain(url)
    opener = session or browse._Session
    with opener() as ctx:
        page = ctx.new_page()
        tracker = StatusTracker()
        tracker.watch(page)
        _load(page, url)
        obs = look(page, tracker=tracker, site=site)
        page.close()
    out = for_model(obs)
    out["site"] = {"domain": site["domain"], "mode": site["mode"], "families": site["families"]}
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="The general browser loop: any goal, named boundaries.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_obs = sub.add_parser("observe", help="read one page as semantic targets")
    p_obs.add_argument("url")
    sub.add_parser("missions", help="every browser mission and where it stopped")
    p_show = sub.add_parser("show", help="one mission in full")
    p_show.add_argument("mission")
    args = ap.parse_args(argv)
    if args.cmd == "observe":
        print(json.dumps(observe_url(args.url), indent=1, ensure_ascii=False))
        return 0
    if args.cmd == "show":
        print(json.dumps(bm.load(args.mission), indent=1, ensure_ascii=False))
        return 0
    rows = bm.all_missions()
    if not rows:
        print("No browser missions yet. (The store is there; it is empty.)")
    for row in rows:
        print(f"{row['id']:44} {row.get('state', ''):22} {bm.describe(row)[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
