"""Any request that means "go do this on the web", not one more vertical.

His correction, and it is the right one: *"this applying to jobs thing is
an example — it's an example of something where you need to access a
document on my computer, do multiple steps on a browser, shit like
that."*

I had been hand-building verticals. `apply_run` drives a job application
and nothing else; the next request that needs six clicks on a website
would have needed another module and another week. That ceiling is the
actual defect, and this is the general thing underneath all of them.

    goal        "renew my registration on the DMV site"
                "download last month's statement and put it in my workspace"
                "fill in this application with my resume"
    start_url   where to begin, or she searches for it
    -> she LOOKS at the page, DECIDES one step, DOES it, and looks again.

The loop is deliberately boring: observe, decide, act, repeat, bounded.
What makes it usable rather than a party trick is what it refuses to do.

**It cannot invent a fact about him.** Every value it types comes from
`aletheia.profile` or from the words of his own request. A model asked to
fill a form will happily produce a plausible phone number; here a value
that is neither on file nor in what he said is REFUSED at the gate, and
the step comes back as a question. This is checked in code, not asked for
in a prompt.

**It stops before anything that commits.** Submit, Send, Pay, Delete,
Confirm, Place order — the same `computer.COMMITTING_PATTERN` the desktop
hands already refuse — end the run and produce ONE approval carrying the
exact page, the exact button and everything typed to get there. He taps
it and the click happens; he does not, and nothing did.

**Money is refused outright, not gated.** Anything that reads as spending
stops the run with no approval offered at all, because "confirm you want
to spend $400" is a question this system does not ask (his standing rule,
and the one line that has never moved).

**Every step is journaled, and the budget is finite.** A loop that cannot
end is not autonomy, it is a runaway. It stops at the budget, at the
goal, at a question, or at a commit — and says which.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from aletheia import (browse, computer, formfill, journal, policy, profile,
                      reasoner, stateio)

ACTOR = "aletheia-webtask"

MAX_STEPS = 14
MAX_TEXT = 4_000
MAX_LINKS = 40
MAX_FIELDS = 45
MAX_FRAMES = 12
FRAME_WAIT_TRIES = 40          # 10s for an iframe to attach
TAB_WAIT_TRIES = 20            # 3s for a new tab to open
STEP_TIMEOUT_S = 90.0
MAX_GOAL_CHARS = 600

DONE, ASK, COMMIT, BUDGET, REFUSED = ("DONE", "NEEDS_YOU", "AWAITING_YOU",
                                      "OUT_OF_STEPS", "REFUSED")
SIGN_IN = "NEEDS_SIGN_IN"
HUMAN_CHECK = "NEEDS_YOUR_EYES"

# A "security check" is a wall a person is supposed to pass, and she is not
# a person. Solving one is also, everywhere, against the site's terms — so
# she names it and hands it back rather than trying anything clever.
HUMAN_WORDS = re.compile(
    r"(i'?m not a robot|verify (?:that )?you(?:'re| are) (?:a )?human|"
    r"are you a human|complete the captcha|recaptcha|hcaptcha|cloudflare|"
    r"security check|unusual traffic)", re.I)

# Anything that reads as spending. Not gated — REFUSED. "Confirm you want
# to spend $400" is a question this system does not ask.
MONEY_WORDS = re.compile(
    r"\b(pay|payment|purchase|buy|checkout|check\s*out|place\s+order|"
    r"add\s+to\s+cart|billing|credit\s+card|card\s+number|cvv|subscribe|"
    r"upgrade\s+plan|donate|tip|deposit|withdraw|transfer\s+funds)\b", re.I)

ACTIONS = ("fill", "type", "select", "click", "attach", "download", "goto",
           "done", "ask", "give_up")

SYSTEM = """You are driving a web browser for Caleb, one step at a time, to
finish the goal he gave you. You see what the page currently shows. You
reply with ONE step.

Reply with a single JSON object and nothing else:

  {"action": "fill",   "values": {"#email": "<from FACTS>", "#city": "..."}}
  {"action": "type",   "selector": "#email", "value": "<from FACTS only>"}
  {"action": "select", "selector": "#country", "value": "<an exact option>"}
  {"action": "click",  "selector": "#next"}
  {"action": "attach", "selector": "#resume", "value": "<a name from HIS FILES>"}
  {"action": "download", "selector": "#statement-link"}
  {"action": "goto",   "value": "https://..."}
  {"action": "ask",    "value": "<the one question only he can answer>"}
  {"action": "done",   "value": "<what was accomplished>"}
  {"action": "give_up","value": "<why this page cannot get there>"}

RULES THAT ARE NOT SUGGESTIONS:

- A value you TYPE must come from FACTS ABOUT HIM or from his own request,
  copied exactly. You do not know his phone number, his address, his
  employer or his date of birth beyond what FACTS says. If a field needs
  something that is not there, use "ask" — never a plausible-looking
  value. A made-up answer on a real form is the worst thing you can do
  here, and it is checked: an invented value is refused and wasted.
- To SAVE a file the page offers, click it with "download" instead of
  "click": the file lands in his workspace and the run can say where.
- A file upload is filled with "attach", and "value" must be one of the
  names under HIS FILES. You cannot invent a path; a path he does not own
  is refused.
- Use the selectors given to you verbatim. Do not invent one.
- For a dropdown, "value" must be one of the options listed for it.
- EVERY FIELD THAT MATCHES A FACT ABOUT HIM IS ALREADY FILLED before you
  are asked. What is left in "fields" with an empty value is what needs
  judgment: an essay, a choice, an acknowledgment. Answer those from HIS
  REQUEST with one "fill" carrying all of them at once, and use "ask" for
  any you genuinely cannot answer from what he said.
- Never re-type a field whose current value is already right; the page
  state you are shown includes what each field currently holds, and a
  repeat is refused and wasted.
- "done" only when the goal is actually finished on this page. Not "I
  filled the form" — that is not done, submitting is, and submitting is
  not yours to do.
- If the next step is a button that submits, sends, pays, deletes,
  confirms or places an order, CLICK IT ANYWAY: the system intercepts
  those and asks him. Your job is to identify it, not to avoid it."""


class WebTaskError(RuntimeError):
    pass


def runs_dir():
    return stateio.private_dir("webtasks")


def _record_path(run_id: str):
    return runs_dir() / f"{stateio.safe_id(run_id, name='web task id')}.json"


def load_run(run_id: str) -> dict:
    return stateio.read_json(_record_path(run_id))


def all_runs(state: str | None = None) -> list[dict]:
    out = []
    if not runs_dir().is_dir():
        return out
    for path in sorted(runs_dir().glob("*.json")):
        try:
            value = stateio.read_json(path)
        except (OSError, ValueError):
            continue
        if state is None or value.get("state") == state:
            out.append(value)
    return out


OBSERVE_JS = r"""() => {
  const seen = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
           && s.display !== 'none';
  };
  const sel = (el) => el.id ? `#${CSS.escape(el.id)}`
    : (el.name ? `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`
               : null);
  const buttons = [];
  for (const el of document.querySelectorAll(
        'button, input[type=submit], input[type=button], a[role=button], [role=button]')) {
    if (!seen(el)) continue;
    const selector = sel(el) || (el.type === 'submit'
      ? `${el.tagName.toLowerCase()}[type="submit"]` : null);
    if (!selector) continue;
    buttons.push({selector, text: (el.innerText || el.value || '').trim().slice(0,70)});
    if (buttons.length > 30) break;
  }
  const links = [];
  for (const a of document.querySelectorAll('a[href]')) {
    if (!seen(a)) continue;
    const text = (a.innerText || '').trim();
    if (!text) continue;
    // A link needs a SELECTOR, not just an href: "Apply for this job" is an
    // <a target=_blank> on most careers sites, and following its href with
    // goto loses whatever the click itself would have done.
    const raw = a.getAttribute('href') || '';
    const one = sel(a) || (raw ? `a[href="${raw.replace(/"/g, '\\"')}"]` : null);
    links.push({href: a.href, text: text.slice(0, 70),
                ...(one ? {selector: one} : {})});
    if (links.length > 60) break;
  }
  return {title: document.title, url: location.href,
          text: (document.body ? document.body.innerText : '').slice(0, 6000),
          buttons, links};
}"""


def documents() -> dict:
    """The files she may attach: his, and only his.

    The other half of what he asked for — "you need to access a document
    on my computer" — and the same rule as a typed value: a path the model
    produced is not a file he owns. She may attach what is in her
    workspace and the resume she can find, nothing else.
    """
    out: dict[str, str] = {}
    try:
        from aletheia import applications
        out["resume"] = applications.find_resume()
    except Exception:
        pass
    try:
        from aletheia import workspace
        for row in workspace.listing()[:40]:
            name = Path(row["path"]).name if isinstance(row, dict) else str(row)
            path = row["path"] if isinstance(row, dict) else str(row)
            out.setdefault(name, path)
    except Exception:
        pass
    return out


def _facts(goal: str) -> dict:
    """What she is allowed to type: his profile, plus his own words."""
    return {"about_him": profile.known(), "his_request": goal,
            "his_files": documents()}


def _permitted_values(goal: str) -> set[str]:
    """Every string she may put into a field, normalised.

    The safety rule that makes this usable on a real form: a model asked
    to fill one will produce a plausible phone number without hesitating.
    Here a value that is neither on file nor in his own sentence is
    refused at the gate — in CODE, not in a prompt, because a prompt is a
    request and this is a rule.
    """
    allowed = set()
    for value in profile.known().values():
        text = str(value).strip()
        if text:
            allowed.add(text.casefold())
    for word in re.findall(r"[\w@.+\-/']{2,}", str(goal)):
        allowed.add(word.casefold())
    allowed.add(str(goal).strip().casefold())
    return allowed


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).casefold())


def _value_is_his(value: str, allowed: set[str], options: list[str],
                  goal: str = "") -> bool:
    text = str(value).strip()
    if not text:
        return False
    low = text.casefold()
    if low in allowed or low in {o.strip().casefold() for o in options}:
        return True
    # HE SAID IT. A sentence he put in his own request is his, whether or
    # not it is the whole request: "for 'why do you want to work here' say
    # ..." was refused by the first version because the essay was a
    # substring of the goal rather than the goal itself, so the one thing
    # he had explicitly dictated came back as a question.
    if goal and len(low) > 12:
        haystack = " ".join(_normal(goal).split())
        needle = " ".join(_normal(text).split())
        if needle and needle in haystack:
            return True
    # A composed value ("Austin, TX") is fine when every piece of it is his.
    pieces = [p.strip().casefold() for p in re.split(r"[,;|]| - ", text) if p.strip()]
    if pieces and all(p in allowed for p in pieces):
        return True
    # Yes/no and short affirmations are answers, not personal facts.
    return low in {"yes", "no", "true", "false", "n/a", "none", "0", "1"}


FRAME_RE = re.compile(r"^@frame(\d+)\|(.*)$", re.S)


def _frames(page) -> list:
    """The page, and everything embedded in it.

    An application form on a company careers page is very often an
    `<iframe>` — Greenhouse and Lever both ship one as their embed, and
    it is what the "Apply" link on a real site drops you onto. Reading
    only the top document, she stood on such a page and said *"I don't
    see any form fields"* while the whole form sat one frame away. A page
    object without `.frames` (a test double, an older shape) behaves
    exactly as it did before.
    """
    got = getattr(page, "frames", None)
    if not got:
        return [page]
    try:
        return list(got)[:MAX_FRAMES]
    except TypeError:
        return [page]


def _tag(index: int, selector: str) -> str:
    """A selector carries the frame it belongs to, or it is ambiguous.

    `#fn` means something different in each frame of a page, and a
    selector that does not say which one is a coin flip at replay time.
    """
    return selector if index == 0 else f"@frame{index}|{selector}"


def _holds(frame, css: str) -> bool:
    """Does this frame actually contain that element right now?"""
    finder = getattr(frame, "query_selector", None)
    if finder is None:
        return True                      # a test double: index is the truth
    try:
        return finder(css) is not None
    except Exception:
        return False


def _resolve(page, selector: str):
    """(where to do it, what to do it to).

    The frame INDEX is a hint; the element being there is the truth. An
    `<iframe>` attaches after `domcontentloaded` and then navigates, so
    right after a page load frame 1 exists and is still blank — the first
    version typed into it and spent twenty seconds waiting for a field
    that would never appear in that document. Real sites also reorder and
    re-attach frames between the run and the press. So: prefer the
    recorded position, accept any frame that has the element, and wait a
    bounded time for one to.
    """
    match = FRAME_RE.match(str(selector or ""))
    if not match:
        return page, selector
    index, css = int(match.group(1)), match.group(2)
    wait = getattr(page, "wait_for_timeout", None)
    for attempt in range(FRAME_WAIT_TRIES if wait else 1):
        frames = _frames(page)
        ordered = ([frames[index]] if index < len(frames) else []) + [
            f for i, f in enumerate(frames) if i != index]
        for frame in ordered:
            if _holds(frame, css):
                return frame, css
        if wait is None:
            break
        try:
            wait(250)
        except Exception:
            break
    frames = _frames(page)
    return (frames[index] if index < len(frames) else page), css


def control_text(page, selector: str):
    """What the thing at that selector says, or None if it is not there.

    The buttons list is buttons; the "Apply for this job" on a real
    careers page is an ordinary link, and refusing to click one because
    it is not a `<button>` cost a step on the very first live run. What
    matters is that the element EXISTS and what it SAYS — the label is
    what the money and commit refusals read.
    """
    target, css = _resolve(page, selector)
    finder = getattr(target, "query_selector", None)
    if finder is None:
        return None
    try:
        el = finder(css)
    except Exception:
        return None
    if el is None:
        return None
    try:
        return ((el.inner_text() or el.get_attribute("value") or "")
                .strip()[:70])
    except Exception:
        return ""


def _open_pages(ctx) -> list:
    try:
        return [p for p in (getattr(ctx, "pages", None) or []) if not p.is_closed()]
    except Exception:
        return []


def follow_new_tab(ctx, page, before: list):
    """A click that opened a new tab is followed, not lost.

    `target="_blank"` is how half the Apply buttons on the internet work.
    Without this she clicks, the form opens in a tab she is not looking
    at, and she reports the page she is still standing on as having no
    fields.
    """
    # A popup does not exist the instant the click returns; the browser
    # opens it a beat later. Checking once found nothing and she carried
    # on describing the page she had just left.
    opened: list = []
    for _ in range(TAB_WAIT_TRIES):
        opened = [p for p in _open_pages(ctx) if p not in before]
        if opened:
            break
        try:
            page.wait_for_timeout(150)
        except Exception:
            break
    if not opened:
        return page
    fresh = opened[-1]
    try:
        fresh.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    return fresh


class _Hands:
    """Act on a selector wherever it actually lives.

    Playwright's `page.fill` only reaches the top document; a frame has
    the same verbs. This is the one place that knows the difference, so
    the run loop and the press replay cannot disagree about it.
    """

    def __init__(self, page):
        self.page = page

    def fill(self, selector, value):
        target, css = _resolve(self.page, selector)
        target.fill(css, str(value))

    def select_option(self, selector, value=None, *, label=None):
        target, css = _resolve(self.page, selector)
        if label is not None:
            target.select_option(css, label=label)
        else:
            target.select_option(css, value)

    def check(self, selector):
        target, css = _resolve(self.page, selector)
        target.check(css)

    def uncheck(self, selector):
        target, css = _resolve(self.page, selector)
        target.uncheck(css)

    def set_input_files(self, selector, path):
        target, css = _resolve(self.page, selector)
        target.set_input_files(css, path)

    def click(self, selector):
        target, css = _resolve(self.page, selector)
        target.click(css)


def read_forms(page) -> list[dict]:
    """Every field on the page, in every frame, each selector frame-tagged."""
    rows: list[dict] = []
    for index, frame in enumerate(_frames(page)):
        try:
            got = frame.evaluate(formfill.READ_FORM_JS)
        except Exception:
            continue
        for row in got or []:
            row = dict(row)
            row["selector"] = _tag(index, row["selector"])
            rows.append(row)
        if len(rows) > MAX_FIELDS * 2:
            break
    return rows


def observe(page) -> dict:
    """What the page shows, small enough to reason about."""
    seen = page.evaluate(OBSERVE_JS)
    buttons, links = list(seen.get("buttons") or []), list(seen.get("links") or [])
    for index, frame in enumerate(_frames(page)):
        if index == 0:
            continue
        try:
            inner = frame.evaluate(OBSERVE_JS)
        except Exception:
            continue
        # The Submit button of an embedded form is INSIDE the frame. Without
        # this she can fill an iframe form and then find nothing to press.
        buttons += [{**b, "selector": _tag(index, b["selector"])}
                    for b in (inner.get("buttons") or [])]
        links += list(inner.get("links") or [])
        if inner.get("text"):
            seen["text"] = (seen.get("text") or "") + "\n" + inner["text"]
    seen["buttons"], seen["links"] = buttons, links
    fields = read_forms(page)
    trimmed = []
    for field in fields[:MAX_FIELDS]:
        row = {"selector": field["selector"], "type": field.get("type"),
               "label": (field.get("question") or field.get("label")
                         or field.get("name") or "")[:120],
               "value": (field.get("value") or "")[:60],
               "required": bool(field.get("required"))}
        if field.get("type") in ("checkbox", "radio"):
            row["checked"] = bool(field.get("checked"))
        if field.get("options"):
            row["options"] = [o["text"] or o["value"]
                              for o in field["options"]][:40]
        if field.get("option"):
            row["is_option"] = field["option"][:60]
        trimmed.append(row)
    return {"title": seen["title"][:160], "url": seen["url"],
            "text": seen["text"][:MAX_TEXT],
            # The unabridged rows, for `formfill` — popped before the page
            # ever goes to the model.
            "_raw": fields,
            "fields": trimmed,
            "buttons": seen["buttons"][:20],
            "links": seen["links"][:MAX_LINKS]}


def wall(seen: dict) -> dict | None:
    """A door she is not allowed to walk through on his behalf.

    Two of them, and they are different in kind:

    A SIGN-IN wall is a thing he can fix once. She never stores his
    passwords — a password box is refused by the value gate like any
    other fact she was not given — but the browser profile she drives is
    persistent, so him signing in once at a real window is permanent.
    That is `python -m aletheia.browse login <url>`, and saying so is a
    fix handed over rather than a dead end.

    A HUMAN CHECK is not his to fix and not hers to defeat. She says
    which page, and stops.
    """
    text = f"{seen.get('title', '')}\n{seen.get('text', '')}"
    if HUMAN_WORDS.search(text[:4000]):
        return {"state": HUMAN_CHECK,
                "say": ("This page is asking to check that a human is here, "
                        f"at {seen.get('url', '')[:90]} — I cannot answer that "
                        "one for you and I will not try. Open it yourself and "
                        "then tell me to carry on.")}
    if any(f.get("type") == "password" for f in seen.get("fields") or []):
        url = seen.get("url", "")
        return {"state": SIGN_IN,
                "say": ("This wants an account before it will go any further, "
                        f"at {url[:90]}. I do not keep your passwords, so this "
                        "is the one bit you do: run `python -m aletheia.browse "
                        f"login {url[:120]}`, sign in in the window that opens, "
                        "close it, and tell me to carry on — I keep the session "
                        "after that and you will not have to do it again."),
                "sign_in_url": url}
    return None


def _decide(goal: str, page_state: dict, history: list[dict], think) -> dict:
    # Belt: the raw rows ride along in `observe` for `formfill` and are
    # popped by the loop. Nothing underscored ever reaches the model — a
    # forgotten pop would silently spend the whole prompt budget.
    page_state = {k: v for k, v in page_state.items() if not k.startswith("_")}
    prompt = json.dumps({
        "goal": goal,
        "facts_about_him": _facts(goal)["about_him"],
        "his_files": list(_facts(goal)["his_files"]),
        "page": page_state,
        "already_filled": [f["label"] for f in page_state["fields"]
                           if (f.get("value") or "").strip()][:30],
        "steps_so_far": history[-6:],
    }, ensure_ascii=False)[:14_000]
    said = think(SYSTEM, prompt, timeout_s=STEP_TIMEOUT_S)
    if isinstance(said, tuple):
        said = said[0]
    text = str(said or "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise WebTaskError(f"the brain did not return a step: {text[:120]}")
    step = json.loads(match.group(0))
    if step.get("action") not in ACTIONS:
        raise WebTaskError(f"unknown action {step.get('action')!r}")
    return step


def run(goal: str, *, start_url: str = "", budget: int = 8, think=None,
        session=None, run_id: str = "") -> dict:
    """Drive a browser toward a goal. Stops at a commit, a question, or the budget."""
    policy.ensure_not_halted()
    goal = " ".join(str(goal or "").split())
    if not goal:
        raise ValueError("say what to do")
    if len(goal) > MAX_GOAL_CHARS:
        raise ValueError(f"the goal must be under {MAX_GOAL_CHARS} characters")
    if MONEY_WORDS.search(goal):
        return {"state": REFUSED, "goal": goal, "steps": [],
                "say": ("That asks me to spend money, and I do not do that — "
                        "not with an approval, not with a confirmation. "
                        "Nothing was opened.")}
    budget = max(1, min(int(budget), MAX_STEPS))
    think = think or reasoner.subscription_text
    allowed = _permitted_values(goal)
    run_id = run_id or f"web-{stateio.safe_id(re.sub(r'[^a-z0-9]+', '-', goal.casefold())[:28].strip('-') or 'task')}"

    ok, why = browse.available()
    if not ok:
        raise WebTaskError(f"she cannot drive a browser: {why}")

    history: list[dict] = []
    # Every value that really went into the page, in `browse.interact`'s own
    # grammar. The first version collected only steps whose action was
    # "type" or "select" — and once filling was batched under "fill", that
    # list was EMPTY, so the approval bound nothing and pressing submit
    # would have re-opened a blank form and sent it. Caught on the first
    # run that reached a submit button.
    applied: list[dict] = []
    attached: list[dict] = []
    downloaded: list[str] = []
    outcome = {"state": BUDGET, "say": "Ran out of steps before finishing."}
    opener = session or browse._Session
    with opener() as ctx:
        page = ctx.new_page()
        hands = _Hands(page)
        page.goto(start_url or "about:blank", wait_until="domcontentloaded")
        for _ in range(budget):
            policy.ensure_not_halted()

            # DETERMINISTIC FIRST. `formfill.plan` maps a form to his profile
            # with no model call at all, and it is simply better at it: on a
            # live Stripe application it fills 15 of 23 fields, every time,
            # in milliseconds. Asking a model to do that instead spent three
            # turns rephrasing one essay and left the rest blank. The model
            # is for judgment — which button, which page, what does this
            # question mean — not for copying his email address into a box.
            # LOOK BEFORE TYPING. The deterministic pass used to run first,
            # which meant that on a sign-in page she put his email address
            # into the username box and only then noticed it was a wall she
            # was not going to get through — a half-filled login left behind
            # on a site she then walked away from.
            seen = observe(page)
            blocked = wall(seen)
            if blocked:
                history.append({"step": {"action": "look"},
                                "result": blocked["state"]})
                outcome = blocked
                break
            raw = seen.pop("_raw", None) or []
            if raw:
                mapped = formfill.plan(raw)
                filled_now = []
                for item in mapped["fill"]:
                    current = next((f.get("value") or "" for f in raw
                                    if f["selector"] == item["selector"]), "")
                    if current.strip() == str(item["value"]).strip():
                        continue
                    try:
                        if item["action"] == "select":
                            hands.select_option(item["selector"], item["value"])
                        else:
                            hands.fill(item["selector"], item["value"])
                    except Exception:
                        continue
                    applied.append({"action": item["action"],
                                    "selector": item["selector"],
                                    "value": item["value"]})
                    filled_now.append(item["label"][:36])
                if filled_now:
                    history.append({"step": {"action": "known"},
                                    "result": (f"filled {len(filled_now)} from "
                                               "what I know: "
                                               + ", ".join(filled_now[:8]))})
                    seen = observe(page)      # the values changed
                    seen.pop("_raw", None)

            try:
                step = _decide(goal, seen, history, think)
            except Exception as exc:
                outcome = {"state": ASK, "say": f"I got stuck: {exc}"[:300]}
                break
            action = step["action"]

            if action == "done":
                said = str(step.get("value", "done"))[:400]
                if downloaded:
                    said += (" Saved: "
                             + ", ".join(Path(d).name for d in downloaded[:4]))
                outcome = {"state": DONE, "say": said}
                break
            if action in ("ask", "give_up"):
                outcome = {"state": ASK,
                           "say": str(step.get("value", "I need you"))[:400]}
                break

            selector = str(step.get("selector") or "")
            value = str(step.get("value") or "")

            if action == "goto":
                if not value.startswith(("http://", "https://", "file://")):
                    history.append({"step": step, "result": "refused: not a url"})
                    continue
                page.goto(value, wait_until="domcontentloaded")
                # Part of the ROUTE, so the press can walk it again. Without
                # this the replay started on the careers page she was given
                # and never reached the application she had navigated to.
                applied.append({"action": "goto", "selector": "", "value": value})
                history.append({"step": step, "result": f"opened {value[:80]}"})
                continue

            field = next((f for f in seen["fields"] if f["selector"] == selector), None)
            button = next((b for b in seen["buttons"] if b["selector"] == selector), None)

            if action == "fill":
                # A whole page in one turn. One field per model call meant
                # fifteen calls for one form, and the first live run spent
                # its entire budget re-typing fields it had already filled.
                done_now, refused_now, needed = [], [], []
                for sel, val in (step.get("values") or {}).items():
                    target = next((f for f in seen["fields"]
                                   if f["selector"] == sel), None)
                    if target is None:
                        refused_now.append(f"{sel}: no such field")
                        continue
                    current = (target.get("value") or "").strip()
                    if current == str(val).strip():
                        continue                      # already right
                    if current and any(a["selector"] == sel for a in applied):
                        # She already answered this one. A model that
                        # rephrases its own essay three times burns the
                        # budget and changes nothing he approved.
                        continue
                    if not _value_is_his(str(val), allowed,
                                         target.get("options") or [], goal):
                        needed.append(target["label"][:80])
                        continue
                    try:
                        if target.get("type") in ("checkbox", "radio"):
                            # A checkbox is CHECKED, not typed into. Missing
                            # this meant a required "I certify the above is
                            # true" box stayed empty, the browser refused the
                            # submit, and the run reported success while the
                            # employer received nothing at all.
                            yes = str(val).strip().casefold() in (
                                "yes", "true", "1", "on", "checked", "i agree",
                                "agree", "tick", "check")
                            hands.check(sel) if yes else hands.uncheck(sel)
                            action_used = "check" if yes else "uncheck"
                        elif target.get("options"):
                            hands.select_option(sel, label=str(val))
                            action_used = "select"
                        else:
                            hands.fill(sel, str(val))
                            action_used = "type"
                        done_now.append(target["label"][:40])
                        applied.append({"action": action_used,
                                        "selector": sel, "value": str(val)})
                    except Exception as exc:
                        refused_now.append(f"{sel}: {type(exc).__name__}")
                history.append({"step": {"action": "fill",
                                         "count": len(done_now)},
                                "result": (f"filled {len(done_now)}: "
                                           + ", ".join(done_now[:8])
                                           + (f" | refused {refused_now}" if refused_now else ""))})
                if needed:
                    outcome = {"state": ASK,
                               "say": ("I need your answers for: "
                                       + "; ".join(needed[:6])
                                       + ". I will not make them up."),
                               "questions": needed}
                    break
                if not done_now and not refused_now:
                    history.append({"step": {"action": "fill"},
                                    "result": "nothing left to fill"})
                continue

            if action in ("type", "select"):
                if field is None:
                    history.append({"step": step, "result": "refused: no such field"})
                    continue
                if not _value_is_his(value, allowed,
                                     field.get("options") or [], goal):
                    # THE gate. A plausible invented value is the worst
                    # thing that can happen on a real form, so it is
                    # refused here rather than discouraged in a prompt.
                    history.append({"step": step,
                                    "result": "refused: that value is not his "
                                              "and not something he said"})
                    outcome = {"state": ASK,
                               "say": (f"I need your answer for "
                                       f"{field['label'][:90]!r} — I will not "
                                       "make one up.")}
                    break
                if (field.get("value") or "").strip() == value.strip():
                    history.append({"step": step,
                                    "result": "skipped: already holds that value"})
                    continue
                if action == "select":
                    hands.select_option(selector, label=value)
                else:
                    hands.fill(selector, value)
                applied.append({"action": action, "selector": selector,
                                "value": value})
                history.append({"step": step, "result": f"filled {field['label'][:50]}"})
                continue

            if action == "attach":
                held = documents()
                path = held.get(value) or held.get(Path(str(value)).name)
                if path is None and str(value) in held.values():
                    path = str(value)
                if path is None:
                    history.append({"step": step,
                                    "result": f"refused: {value!r} is not one "
                                              "of his files"})
                    outcome = {"state": ASK,
                               "say": (f"I could not find a file called "
                                       f"{value!r}. Put it in my workspace or "
                                       "tell me the path.")}
                    break
                if field is None:
                    history.append({"step": step, "result": "refused: no such field"})
                    continue
                hands.set_input_files(selector, str(path))
                attached.append({"selector": selector, "path": str(path)})
                history.append({"step": step,
                                "result": f"attached {Path(path).name}"})
                continue

            if action == "download":
                # Saving a file the page offers. It lands in HER WORKSPACE,
                # which is the one directory she may write — a download is
                # not permission to put a file anywhere on his disk.
                from aletheia import workspace
                try:
                    with page.expect_download(timeout=60_000) as caught:
                        hands.click(selector)
                    got = caught.value
                    name = re.sub(r"[^A-Za-z0-9._-]+", "-",
                                  got.suggested_filename or "download")[:80]
                    target = workspace.root() / "downloads" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    got.save_as(str(target))
                except Exception as exc:
                    history.append({"step": step,
                                    "result": f"download failed: {type(exc).__name__}"})
                    continue
                downloaded.append(str(target))
                journal.append("action", "webtask",
                               f"saved {name} into the workspace", actor=ACTOR)
                history.append({"step": step, "result": f"saved {name}"})
                continue

            if action == "click":
                label = (button or {}).get("text", "") or (field or {}).get("label", "")
                if button is None and field is None:
                    found = control_text(page, selector)
                    if found is None:
                        history.append({"step": step,
                                        "result": "refused: no such control"})
                        continue
                    label = label or found
                if MONEY_WORDS.search(label):
                    outcome = {"state": REFUSED,
                               "say": (f"That button says {label[:60]!r}, which "
                                       "spends money. I stopped and did not "
                                       "press it.")}
                    break
                commits = computer.committing_label(label)
                if commits:
                    empty = [f["label"] for f in seen["fields"]
                             if f.get("required")
                             and not (f.get("value") or "").strip()
                             and f.get("type") not in ("file", "hidden", "submit")]
                    if empty:
                        # The browser would refuse this submit and the run
                        # would report success while nothing was sent.
                        outcome = {"state": ASK,
                                   "say": ("These are still empty and the form "
                                           "will not go without them: "
                                           + "; ".join(empty[:6])),
                                   "questions": empty}
                        break
                    # The end of the road for one run: everything up to the
                    # irreversible click is done, and the click itself
                    # becomes one approval carrying the page, the button and
                    # every value typed to get there.
                    outcome = _await_him(run_id, goal, page, label, selector,
                                         applied, attached, commits,
                                         start_url=start_url)
                    break
                before = _open_pages(ctx)
                hands.click(selector)
                try:
                    page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass
                moved = follow_new_tab(ctx, page, before)
                applied.append({"action": "click", "selector": selector})
                if moved is not page:
                    page, hands.page = moved, moved
                    applied.append({"action": "new_tab", "selector": ""})
                    history.append({"step": step,
                                    "result": f"clicked {label[:40]} — it "
                                              "opened a new tab, following it"})
                    continue
                history.append({"step": step, "result": f"clicked {label[:50]}"})
                continue

        shot = runs_dir() / f"{run_id}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(shot), full_page=True)
        except Exception:
            shot = None
        outcome.update({"url": page.url, "title": page.title()})
        page.close()

    record = {"id": run_id, "goal": goal, "steps": history,
              "downloaded": downloaded,
              "screenshot": str(shot) if shot else "", "at": stateio.utcnow(),
              **outcome}
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("action", "webtask",
                   f"{record['state']} after {len(history)} step(s): {goal[:90]}",
                   actor=ACTOR)
    return record


def _digest(action: str) -> str:
    import hashlib
    return hashlib.sha256(action.encode("utf-8")).hexdigest()[:12]


def _await_him(run_id: str, goal: str, page, label: str, selector: str,
               typed: list[dict], attached: list[dict], commits: str,
               start_url: str = "") -> dict:
    """Everything is filled; the committing click waits for him."""
    action = browse.approval_action(start_url or page.url, typed + [
        {"action": "click", "selector": selector}])
    # The approval id carries the ROUTE, not just the run. `policy.request`
    # is idempotent on the id, so a second run of the same goal — a route
    # that now fills different fields, or lands on a different button —
    # would otherwise inherit the yes he gave the first one. Caught by
    # running the same goal twice against a test site while iterating.
    approval_id = f"{run_id}-commit-{_digest(action)}"
    policy.request(
        approval_id, action,
        reason=f"{goal} — press {label[:60]!r} on {page.url[:80]}",
        consequence=(f"It presses a button that says {commits!r}. That is not "
                     "something she can undo."),
        reversible=False, capability="web.commit")
    return {"state": COMMIT, "approval": approval_id, "action": action,
            "button": label,
            "button_selector": selector, "typed": typed, "attached": attached,
            # The whole route, not just the last page. A three-page wizard is
            # reached by clicking THROUGH it, and re-opening page three
            # directly loses what pages one and two established — the first
            # version replayed page one's fills onto page three and died on
            # "waiting for locator #fn", with the site having received the
            # first two pages and never the third.
            "replay_from": start_url or page.url,
            "say": (f"Everything is filled in. The last step is a button that "
                    f"says {label[:50]!r} — confirm it and I will press it.")}


def commit(run_id: str, *, presser=None) -> dict:
    """He confirmed. Re-open, re-fill exactly what he saw, press it once."""
    policy.ensure_not_halted()
    record = load_run(run_id)
    if record.get("state") == "COMMITTED":
        raise WebTaskError(f"{run_id} was already done at {record.get('committed_at')}")
    if record.get("state") != COMMIT:
        raise WebTaskError(f"{run_id} is {record.get('state')}; nothing to press")
    approval = policy.load(record["approval"])
    if approval.get("state") != "APPROVED":
        raise WebTaskError(f"approval {record['approval']} is "
                           f"{approval.get('state')} — nothing was pressed")
    # What he said yes to is the ROUTE and the BUTTON, not the run's name.
    expected = browse.approval_action(
        record.get("replay_from") or record["url"],
        record.get("typed", []) + [{"action": "click",
                                    "selector": record["button_selector"]}])
    if approval.get("requested_action") != expected:
        raise WebTaskError(
            f"approval {record['approval']} was given for a different route "
            "than the one on file — nothing was pressed")
    _claim(record)
    record["state"] = "COMMITTING"
    record["committed_at"] = stateio.utcnow()
    stateio.write_json_atomic(_record_path(run_id), record)
    try:
        result = (presser or _press)(record)
    except Exception as exc:
        record.update({"state": "FAILED",
                       "failure": f"{type(exc).__name__}: {exc}"[:300]})
        stateio.write_json_atomic(_record_path(run_id), record)
        raise
    record.update({"state": "COMMITTED", "result": result})
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("action", "webtask",
                   f"pressed {record.get('button', '')[:40]!r} for {run_id}",
                   actor=ACTOR)
    return record


def _claim(record: dict) -> None:
    """One yes presses one button, once.

    The approval id is the route's digest, which is what stops a DIFFERENT
    route from inheriting his yes. It does not stop the SAME route being
    run again: a second `run` of the same goal overwrites the record with
    a fresh AWAITING_YOU while the old approval is still APPROVED, and the
    press would go through without asking — a second application to the
    same job, or a second anything. Consumed here the way a computer run
    consumes one (`computer._claim_approval`), in the journal, BEFORE the
    press, so a failed press also needs a fresh yes rather than becoming a
    retry loop nobody agreed to.
    """
    ref = f"approval:{record['approval']}"
    for entry in journal.entries():
        if (entry.get("subject") == "webtask:press"
                and ref in (entry.get("refs") or [])):
            raise WebTaskError(
                f"approval {record['approval']} has already been used to press "
                f"{record.get('button', 'a button')!r} — pressing again needs a "
                "fresh yes from you")
    journal.append("action", "webtask:press",
                   f"PRESSING {record.get('button', '')[:40]!r} for {record['id']}",
                   actor=ACTOR, refs=[ref, f"run:{record['id']}"])


def _press(record: dict) -> dict:
    """Replay the WHOLE route, then press the button he approved.

    Not just the last page: a wizard is reached by clicking through it, so
    re-opening the final step directly loses everything the earlier pages
    established.
    """
    attachments = {a["selector"]: a["path"] for a in record.get("attached", [])}
    with browse._Session() as ctx:
        page = ctx.new_page()
        hands = _Hands(page)
        page.goto(record.get("replay_from") or record["url"],
                  wait_until="domcontentloaded")
        for step in record.get("typed", []):
            action, selector = step["action"], step.get("selector") or ""
            if action == "goto":
                page.goto(str(step.get("value", "")), wait_until="domcontentloaded")
            elif action == "select":
                hands.select_option(selector, label=step["value"])
            elif action == "check":
                hands.check(selector)
            elif action == "uncheck":
                hands.uncheck(selector)
            elif action == "new_tab":
                continue                        # handled by the click before it
            elif action == "click":
                for sel, path in attachments.items():
                    try:
                        hands.set_input_files(sel, path)
                    except Exception:
                        pass
                before = _open_pages(ctx)
                hands.click(selector)
                try:
                    page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass
                moved = follow_new_tab(ctx, page, before)
                if moved is not page:
                    page, hands.page = moved, moved
            else:
                hands.fill(selector, str(step.get("value", "")))
        for selector, path in attachments.items():
            try:
                hands.set_input_files(selector, path)
            except Exception:
                pass
        hands.click(record["button_selector"])
        page.wait_for_load_state("domcontentloaded")
        # The receipt of an EMBEDDED form is inside the frame; the parent
        # page still says "Application form below" and reads like nothing
        # happened. The evidence has to be what the form itself now says.
        parts = [page.inner_text("body") or ""]
        for frame in _frames(page)[1:]:
            try:
                parts.append(frame.inner_text("body") or "")
            except Exception:
                continue
        body = "\n".join(t for t in parts if t.strip())[:2000]
        shot = runs_dir() / f"{record['id']}-after.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
        except Exception:
            shot = ""
        out = {"url": page.url, "title": page.title(), "evidence": body[:600],
               "screenshot": str(shot)}
        page.close()
    return out


def spoken(record: dict) -> str:
    return str(record.get("say") or record.get("state", "?"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Do a thing on the web, one step at a time.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("goal")
    p_run.add_argument("--url", default="")
    p_run.add_argument("--budget", type=int, default=8)
    p_go = sub.add_parser("commit"); p_go.add_argument("run_id")
    sub.add_parser("waiting")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "run":
            record = run(args.goal, start_url=args.url, budget=args.budget)
            print(spoken(record))
            for entry in record["steps"]:
                print(f"  {entry['step'].get('action'):7} {entry['result'][:70]}")
        elif args.cmd == "waiting":
            for record in all_runs(COMMIT):
                print(f"{record['id']}  {record.get('button','')}  {record['goal'][:50]}")
        else:
            print(spoken(commit(args.run_id)))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
