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
import datetime as dt
import json
import re
import sys
from pathlib import Path

from aletheia import (browse, computer, formfill, journal, policy, profile,
                      reasoner, stateio)

ACTOR = "aletheia-webtask"

# A real application is three to six PAGES, and each page costs a look and
# a decision. Eight steps was a number picked before any of them had been
# driven; the three-page fixture alone spends five, and a run that stops
# halfway through a form leaves a half-filled form behind and nothing to
# resume from — the browser context closes with the run.
MAX_STEPS = 24
MAX_TEXT = 4_000
MAX_LINKS = 40
MAX_FIELDS = 45
MAX_HIS_FILES = 40             # of his own documents she will offer to attach
# What she may UPLOAD. Narrower than what she may read, on purpose: a
# document is a thing you send somebody, and a .key or a .env is not.
ATTACHABLE = frozenset({".pdf", ".docx", ".doc", ".txt", ".md", ".rtf",
                        ".odt", ".pages", ".csv", ".png", ".jpg", ".jpeg"})
MAX_FRAMES = 12
FRAME_WAIT_TRIES = 40          # 10s for an iframe to attach
TAB_WAIT_TRIES = 20            # 3s for a new tab to open
IDLE_LIMIT = 3                 # rounds that change nothing before she stops
STALE_AFTER_MIN = 20           # a RUNNING record older than this is a leftover
STEP_TIMEOUT_S = 90.0
MAX_GOAL_CHARS = 600

DONE, ASK, COMMIT, BUDGET, REFUSED = ("DONE", "NEEDS_YOU", "AWAITING_YOU",
                                      "OUT_OF_STEPS", "REFUSED")
RUNNING = "RUNNING"
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
  // A modern form's controls are DIVS. Nothing in a Workday or Greenhouse
  // question has an id or a name: the "Yes" you click is
  // <div role=radio>, the city you pick is <li role=option>, and neither
  // is reachable by id, name, or the word "button". Without a path she
  // could see the box to type a city into and not one of the four cities.
  const path = (el) => {
    const bits = [];
    for (let n = el; n && n.nodeType === 1 && bits.length < 6; n = n.parentElement) {
      if (n.id) { bits.unshift(`#${CSS.escape(n.id)}`); break; }
      const tag = n.tagName.toLowerCase();
      if (tag === 'html' || tag === 'body') break;
      const kin = n.parentElement
        ? [...n.parentElement.children].filter(c => c.tagName === n.tagName) : [n];
      bits.unshift(kin.length > 1
        ? `${tag}:nth-of-type(${kin.indexOf(n) + 1})` : tag);
    }
    const one = bits.join(' > ');
    try {
      return one && document.querySelectorAll(one).length === 1 ? one : null;
    } catch (e) { return null; }
  };
  const sel = (el) => el.id ? `#${CSS.escape(el.id)}`
    : (el.name ? `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`
               : path(el));
  const named = (el) => {
    if (!el) return '';
    const own = el.getAttribute('aria-label');
    if (own) return own.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const n = document.getElementById(by);
      if (n && n.innerText.trim()) return n.innerText.trim().slice(0, 90);
    }
    return '';
  };
  const buttons = [];
  for (const el of document.querySelectorAll(
        'button, input[type=submit], input[type=button], a[role=button], [role=button]')) {
    if (!seen(el)) continue;
    // Prefer a selector that survives a reload: id, name, then the
    // semantic one, and only then a positional path. The press replays
    // the route on a freshly loaded page, so `form > div:nth-of-type(2)`
    // is a last resort, not a first choice.
    const selector = (el.id || el.name) ? sel(el)
      : (el.type === 'submit' ? `${el.tagName.toLowerCase()}[type="submit"]`
                              : path(el));
    if (!selector) continue;
    buttons.push({selector, text: (el.innerText || el.value || '').trim().slice(0,70)});
    if (buttons.length > 30) break;
  }
  // The ARIA widgets: an answer she can click, and the question it answers.
  for (const el of document.querySelectorAll(
        '[role=option], [role=radio], [role=checkbox], [role=switch], '
        + '[role=combobox], [role=menuitem], [role=tab], summary')) {
    if (!seen(el)) continue;
    const selector = sel(el);
    if (!selector) continue;
    const group = el.closest(
      '[role=radiogroup], [role=listbox], [role=group], [role=menu], fieldset');
    const row = {selector, text: (el.innerText || '').trim().slice(0, 70),
                 role: el.getAttribute('role') || el.tagName.toLowerCase()};
    const checked = el.getAttribute('aria-checked');
    if (checked !== null) row.checked = checked === 'true';
    const open = el.getAttribute('aria-expanded');
    if (open !== null) row.expanded = open === 'true';
    const question = named(group) || named(el);
    if (question) row.question = question;
    buttons.push(row);
    if (buttons.length > 60) break;
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
    # AND WHERE HE ACTUALLY KEEPS THINGS. The two halves of her disagreed:
    # "summarise the lease on my desktop" worked and "attach the lease on
    # my desktop" came back as "that is not one of your files". Same
    # folders as the reading half, and only things that are documents —
    # what she may upload is narrower than what she may read, because
    # uploading sends it to somebody else.
    try:
        from aletheia import converse
        found = []
        for place in converse.HOME_PLACES:
            folder = Path.home() / place if place else Path.home()
            try:
                entries = list(folder.iterdir())
            except Exception:
                continue
            for entry in entries:
                if (entry.is_file()
                        and entry.suffix.casefold() in ATTACHABLE
                        and entry.name not in out):
                    try:
                        found.append((entry.stat().st_mtime, entry))
                    except Exception:
                        continue
        for _, entry in sorted(found, reverse=True)[:MAX_HIS_FILES]:
            out.setdefault(entry.name, str(entry))
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


def _bare(text: str) -> str:
    """Only the letters and digits — how a fact reads with the formatting
    taken off. "(512) 555-0134", "512-555-0134" and "5125550134" are one
    phone number."""
    return re.sub(r"[^a-z0-9]+", "", str(text).casefold())


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
    # THE SAME FACT, PUNCTUATED THE WAY THE SITE WANTS. A form that says
    # "10 digits, no punctuation" is asking for his phone number, not for
    # a new one — and the gate refused "5125550134" because his profile
    # says "(512) 555-0134", so a rejection he could have fixed came back
    # as a question he had already answered. Same characters, ignoring
    # everything that is not a letter or a digit, is the same fact.
    bare = _bare(low)
    if bare and any(bare == _bare(a) for a in allowed):
        return True
    if bare and any(bare == _bare(o) for o in options):
        return True
    # A composed value ("Austin, TX") is fine when every piece of it is his.
    pieces = [p.strip().casefold() for p in re.split(r"[,;|]| - ", text) if p.strip()]
    if pieces and all(p in allowed for p in pieces):
        return True
    # Yes/no and short affirmations are answers, not personal facts.
    return low in {"yes", "no", "true", "false", "n/a", "none", "0", "1"}


# The frame-aware primitives live in `formfill`, which owns the form
# reading, so the application filler and this loop cannot drift on what a
# selector means. Kept under these names because they read better here.
FRAME_RE = formfill.FRAME_RE
MAX_FRAMES = formfill.MAX_FRAMES
FRAME_WAIT_TRIES = formfill.FRAME_WAIT_TRIES
_frames = formfill.frames
_tag = formfill.tag
_holds = formfill.holds
_resolve = formfill.resolve
_Hands = formfill.Hands
read_forms = formfill.read_all


def settle(page) -> None:
    """`formfill.settle`, plus the controls this loop can also act on — a
    landing page with an Apply link and no form at all is settled too."""
    def has_controls(target) -> bool:
        seen = target.evaluate(OBSERVE_JS)
        return bool(seen.get("buttons") or seen.get("links"))
    formfill.settle(page, extra=has_controls)


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
    # WHAT THE PAGE SAYS IS STILL MISSING, in front of the model before it
    # chooses. She typed a city into a typeahead, never picked one from
    # its list, and went straight for Submit — the hidden value the widget
    # sets stayed empty and the form would have bounced. The page knew.
    try:
        not_ready = formfill.blocking(page)[:10]
    except Exception:
        not_ready = []
    return {"title": seen["title"][:160], "url": seen["url"],
            "still_missing": not_ready,
            "text": seen["text"][:MAX_TEXT],
            # The unabridged rows, for `formfill` — popped before the page
            # ever goes to the model.
            "_raw": fields,
            "fields": trimmed,
            "buttons": seen["buttons"][:40],
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


def _decide(goal: str, page_state: dict, history: list[dict], think,
            refused_before: str = "") -> dict:
    # Belt: the raw rows ride along in `observe` for `formfill` and are
    # popped by the loop. Nothing underscored ever reaches the model — a
    # forgotten pop would silently spend the whole prompt budget.
    page_state = {k: v for k, v in page_state.items() if not k.startswith("_")}
    prompt = json.dumps({
        "goal": goal,
        "facts_about_him": _facts(goal)["about_him"],
        "his_files": list(_facts(goal)["his_files"]),
        "page": page_state,
        "the_page_says_these_are_missing": page_state.get("still_missing") or [],
        "already_filled": [f["label"] for f in page_state["fields"]
                           if (f.get("value") or "").strip()][:30],
        "steps_so_far": history[-6:],
        # What the site said when it refused this exact thing last time.
        # Without it a retry is the same attempt again, which is not a
        # retry, it is a loop with extra steps.
        **({"the_site_REFUSED_this_last_time_and_said": refused_before[:600]}
           if refused_before else {}),
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


def run(goal: str, *, start_url: str = "", budget: int = 16, think=None,
        refused_before: str = "", attempt: int = 1, pick_up: dict | None = None,
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
    # HIS ANSWERS ARE HIS. When he answers the questions she asked, those
    # words are as much his as anything on his profile — the gate exists
    # to stop a model inventing a fact, not to stop him supplying one.
    answers = dict((pick_up or {}).get("answers") or {})
    allowed |= {str(v).strip().casefold() for v in answers.values() if str(v).strip()}
    # The slug alone collided: "apply for the senior systems engineer job at
    # Stripe" and the same sentence ending in Databricks share their first
    # 28 characters, so the second run OVERWROTE the first one's record and
    # its pending approval pointed at a route that no longer existed. Same
    # goal on the same page is deliberately the same run; a different one
    # is a different run.
    if not run_id:
        slug = re.sub(r"[^a-z0-9]+", "-", goal.casefold())[:24].strip("-") or "task"
        run_id = f"web-{stateio.safe_id(slug)}-{_digest(goal + '|' + start_url)[:8]}"

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
    writes: dict[str, int] = {}
    attached: list[dict] = []
    downloaded: list[str] = []
    idle = 0
    outcome = {"state": BUDGET,
               "say": ("I ran out of steps before finishing. Nothing was "
                       "submitted — say 'carry on' and I will pick it up "
                       "from where I stopped.")}
    opener = session or browse._Session
    with opener() as ctx:
        page = ctx.new_page()
        hands = _Hands(page)
        page.goto(start_url or "about:blank", wait_until="domcontentloaded")
        settle(page)
        if pick_up:
            # PUT THE PAGE BACK. Everything she had already typed, and every
            # click that carried her between pages, replayed before the
            # first new step — so picking a run back up is continuing it,
            # not starting it again and asking him the same three questions.
            applied = [dict(s) for s in pick_up.get("typed") or []]
            attached = [dict(a) for a in pick_up.get("attached") or []]
            writes = {s["selector"]: 1 for s in applied if s.get("selector")}
            history = list(pick_up.get("steps") or [])[-4:]
            try:
                page = walk(ctx, page, hands,
                            applied, {a["selector"]: a["path"] for a in attached})
            except Exception as exc:
                # The page moved on under her. Honest, and not a crash.
                return _stopped(run_id, goal, attempt, history, [], "",
                                {"state": ASK,
                                 "say": ("I could not put that page back the "
                                         f"way I left it ({type(exc).__name__}). "
                                         "Start it again and I will do the "
                                         "whole thing.")})
            history.append({"step": {"action": "resume"},
                            "result": (f"put back {len(applied)} thing(s) I had "
                                       "already done")})
            if answers:
                # And his answers to what she asked, typed in before she
                # looks again — so the same questions are not asked twice.
                seen_now = observe(page)
                seen_now.pop("_raw", None)
                for label, value in answers.items():
                    field = next((f for f in seen_now["fields"]
                                  if label.casefold() in
                                  (f.get("label") or "").casefold()), None)
                    if field is None:
                        history.append({"step": {"action": "answer"},
                                        "result": f"no field for {label[:40]!r}"})
                        continue
                    try:
                        if field.get("type") in ("checkbox", "radio"):
                            hands.check(field["selector"])
                            used = "check"
                        elif field.get("options"):
                            hands.select_option(field["selector"], label=str(value))
                            used = "select"
                        else:
                            hands.fill(field["selector"], str(value))
                            used = "type"
                    except Exception as exc:
                        history.append({"step": {"action": "answer"},
                                        "result": f"could not: {type(exc).__name__}"})
                        continue
                    writes[field["selector"]] = writes.get(field["selector"], 0) + 1
                    applied.append({"action": used, "selector": field["selector"],
                                    "value": str(value)})
                    history.append({"step": {"action": "answer"},
                                    "result": f"your answer for {label[:44]}"})
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
                    if item["selector"] in writes:
                        # WHAT SHE KNOWS FILLS BLANKS. It does not argue
                        # with a decision made later in the same run: the
                        # site said "10 digits, no punctuation", the model
                        # obeyed, and this pass put his punctuated number
                        # straight back on the next round — the two of
                        # them overwrote each other until the budget ran
                        # out, which is how a retry that was working
                        # looked exactly like one that was not.
                        continue
                    if item["action"] in ("click", "check"):
                        already = next((f for f in raw
                                        if f["selector"] == item["selector"]), {})
                        if already.get("checked"):
                            continue          # already the chosen answer
                    else:
                        current = next((f.get("value") or "" for f in raw
                                        if f["selector"] == item["selector"]), "")
                        if current.strip() == str(item["value"]).strip():
                            continue
                    try:
                        if item["action"] == "select":
                            hands.select_option(item["selector"], item["value"])
                        elif item["action"] in ("click", "check"):
                            # An answer she CLICKS: a radio, or the div a
                            # modern form uses instead of one.
                            hands.click(item["selector"])
                        else:
                            hands.fill(item["selector"], item["value"])
                    except Exception:
                        continue
                    writes[item["selector"]] = writes.get(item["selector"], 0) + 1
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

            # CHECKPOINT before the slow part. Deciding is a model call
            # that takes tens of seconds; everything typed to get here is
            # on disk before it starts.
            _checkpoint(run_id, {"id": run_id, "goal": goal, "attempt": attempt,
                                 "steps": history, "typed": applied,
                                 "attached": attached, "downloaded": downloaded,
                                 "replay_from": start_url or page.url,
                                 "url": page.url, "at": stateio.utcnow()})
            try:
                step = _decide(goal, seen, history, think,
                               refused_before=refused_before)
            except Exception as exc:
                outcome = {"state": ASK, "say": f"I got stuck: {exc}"[:300]}
                break
            action = step["action"]

            if action == "done":
                said = str(step.get("value", "done"))[:400]
                if downloaded:
                    # WHERE, not just what. "Saved: 2026-06.pdf" is a file
                    # he now has to go and find.
                    said += (" Saved into " + str(Path(downloaded[0]).parent)
                             + ": " + ", ".join(Path(d).name
                                                for d in downloaded[:6]))
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
                settle(page)
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
                    if writes.get(sel, 0) >= 2:
                        # She has answered this one and corrected it once.
                        # The guard exists because a model that rephrases
                        # its own essay three times burns the budget and
                        # changes nothing. But the first version skipped
                        # ANY second write, which meant a site that said
                        # "phone must be 10 digits" could never be obeyed:
                        # the deterministic pass had already typed his
                        # punctuated number and the correction was
                        # silently dropped, every time, forever.
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
                        writes[sel] = writes.get(sel, 0) + 1
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
                    idle += 1
                    history.append({"step": {"action": "fill"},
                                    "result": "nothing left to fill"})
                    if idle >= IDLE_LIMIT:
                        # Spending the whole budget doing nothing is not
                        # thinking, it is a loop. It happened the first
                        # time a retry could not correct a value: eleven
                        # rounds of "nothing left to fill" and a run that
                        # reported OUT_OF_STEPS with no idea why.
                        outcome = {"state": ASK,
                                   "say": ("I am going round in circles on "
                                           "this page — I have nothing left "
                                           "I can change. Tell me what to put "
                                           "and where.")}
                        break
                else:
                    idle = 0
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
                # The FIELD decides the verb, not the word the model
                # used. It said "select" on a typeahead — an <input> with
                # role=combobox — and `select_option` threw "Element is
                # not a <select>", which ended the whole run rather than
                # one step. What a control is, is not a matter of opinion.
                real = "select" if field.get("options") else "type"
                try:
                    if real == "select":
                        hands.select_option(selector, label=value)
                    else:
                        hands.fill(selector, value)
                except Exception as exc:
                    history.append({"step": step,
                                    "result": f"could not: {type(exc).__name__}"})
                    continue
                writes[selector] = writes.get(selector, 0) + 1
                applied.append({"action": real, "selector": selector,
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
                asked = ((button or {}).get("question")
                         or (field or {}).get("question") or "")
                if asked and formfill.is_never_autofill({"label": asked}):
                    # The value gate refuses to TYPE an answer to these; a
                    # question whose answer is a div you click is the same
                    # question. Gender, race, veteran status, disability, a
                    # felony declaration — his to answer, never hers.
                    outcome = {"state": ASK,
                               "say": (f"{asked[:110]!r} is yours to answer, "
                                       "not mine. Tell me what to put and I "
                                       "will put it."),
                               "questions": [asked[:110]]}
                    break
                if MONEY_WORDS.search(label):
                    outcome = {"state": REFUSED,
                               "say": (f"That button says {label[:60]!r}, which "
                                       "spends money. I stopped and did not "
                                       "press it.")}
                    break
                commits = computer.committing_label(label)
                if commits:
                    # THE PAGE'S OWN VERDICT, in the one place that knows
                    # how to ask for it. Her own reading of "required and
                    # empty" missed everything the browser knows and
                    # everything a div question is, which is how a run
                    # reported success while the site refused the submit.
                    empty = [item["label"] for item in formfill.blocking(page)]
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
                if applied and applied[-1].get("action") == "click" \
                        and applied[-1].get("selector") == selector:
                    # She just clicked this. Doing it again is how a
                    # question the page can never report as answered turns
                    # into a loop that spends the whole budget.
                    history.append({"step": step,
                                    "result": "skipped: just clicked that"})
                    continue
                before = _open_pages(ctx)
                try:
                    hands.click(selector)
                except Exception as exc:
                    # A COOKIE BANNER, a modal, a chat bubble. Playwright
                    # says "intercepts pointer events" and times out; the
                    # first version let that end the whole run with a
                    # stack trace about a locator. It is a thing sitting
                    # on top of the page, she can see it in the buttons,
                    # and saying so is what lets the next step deal with it.
                    covered = "intercepts pointer events" in str(exc)
                    history.append({
                        "step": step,
                        "result": ("could not click it: something is covering "
                                   "the page — dismiss that first"
                                   if covered else
                                   f"could not click it: {type(exc).__name__}")})
                    continue
                try:
                    page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass
                moved = follow_new_tab(ctx, page, before)
                applied.append({"action": "click", "selector": selector})
                settle(moved)
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
              "attempt": attempt, "downloaded": downloaded,
              # THE ROUTE, on every ending and not only on a commit. It was
              # written down only when she reached a button, so a run that
              # stopped to ask him a question threw away everything it had
              # already done and he had to watch it be asked again.
              "typed": applied, "attached": attached,
              "replay_from": start_url or record_url(outcome),
              "screenshot": str(shot) if shot else "", "at": stateio.utcnow(),
              **outcome}
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("action", "webtask",
                   f"{record['state']} after {len(history)} step(s): {goal[:90]}",
                   actor=ACTOR)
    return record


def record_url(outcome: dict) -> str:
    return str(outcome.get("url") or "")


def _checkpoint(run_id: str, base: dict) -> None:
    """Write the run down mid-flight, so a crash is not a total loss.

    A run takes minutes and the record was written once, at the end. The
    Core restarts itself on every code update and its supervisor restarts
    it on a crash — so a restart in the middle threw away eleven filled
    fields and two pages of navigation, and the only evidence it had ever
    happened was a browser that was gone. The route is small JSON; there
    is no reason it should live only in memory.
    """
    try:
        stateio.write_json_atomic(_record_path(run_id),
                                  {**base, "state": RUNNING,
                                   "beat": stateio.utcnow(),
                                   "say": "I am working on this now."})
    except Exception:
        pass                  # a checkpoint that fails must not end the run


def _stale(record: dict, *, minutes: int = STALE_AFTER_MIN) -> bool:
    """Is this RUNNING record a leftover rather than a live run?"""
    beat = str(record.get("beat") or "")
    if not beat:
        return True
    try:
        when = dt.datetime.fromisoformat(beat.replace("Z", "+00:00"))
    except ValueError:
        return True
    age = dt.datetime.now(dt.timezone.utc) - when
    return age > dt.timedelta(minutes=minutes)


def _stopped(run_id, goal, attempt, history, downloaded, shot, outcome) -> dict:
    """Write a run down and say what happened. Used where the loop cannot."""
    record = {"id": run_id, "goal": goal, "steps": history, "attempt": attempt,
              "downloaded": downloaded, "typed": [], "attached": [],
              "screenshot": shot, "at": stateio.utcnow(), **outcome}
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("action", "webtask",
                   f"{record['state']}: {goal[:90]}", actor=ACTOR)
    return record


def walk(ctx, page, hands, route: list[dict], attachments: dict) -> object:
    """Put the page back the way she left it.

    The route is the unit — every value AND every navigation click — so
    replaying it is how a page that closed with the run comes back. The
    press has always done this; picking a run back up is the same walk
    without the final button, and two copies of it would drift.
    """
    for step in route:
        action, selector = step["action"], step.get("selector") or ""
        if action == "goto":
            page.goto(str(step.get("value", "")), wait_until="domcontentloaded")
            settle(page)
        elif action == "new_tab":
            continue                        # handled by the click before it
        elif action == "select":
            hands.select_option(selector, label=step["value"])
        elif action == "check":
            hands.check(selector)
        elif action == "uncheck":
            hands.uncheck(selector)
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
            settle(moved)
            if moved is not page:
                page, hands.page = moved, moved
        else:
            hands.fill(selector, str(step.get("value", "")))
    for selector, path in attachments.items():
        try:
            hands.set_input_files(selector, path)
        except Exception:
            pass
    return page


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
        reason=(f"{goal} — press {label[:60]!r} on {page.url[:80]}"
                + (" — sending " + ", ".join(Path(a["path"]).name
                                             for a in attached[:4])
                   if attached else "")),
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
            "say": (
                (f"Everything is filled in. The last step is a button that "
                 f"says {label[:50]!r} — confirm it and I will press it.")
                if typed else
                # NOTHING WAS FILLED, because not every commit is a form.
                # "Everything is filled in. The last step is a button that
                # says 'Cancel my membership'" is a strange thing to read
                # about a page she typed nothing into.
                (f"On {page.url[:70]} the one thing left is a button that "
                 f"says {label[:50]!r}. That is not something I can undo — "
                 "confirm it and I will press it."))}


def commit(run_id: str, *, presser=None) -> dict:
    """He confirmed. Re-open, re-fill exactly what he saw, press it once."""
    policy.ensure_not_halted()
    record = load_run(run_id)
    if record.get("state") in ("COMMITTED", "REJECTED"):
        raise WebTaskError(f"{run_id} was already pressed at "
                           f"{record.get('committed_at')} — "
                           f"{record.get('result', {}).get('verdict', 'done')}")
    if record.get("state") != COMMIT:
        raise WebTaskError(f"{run_id} is {record.get('state')}; nothing to press")
    ok, why = policy.usable(record["approval"])
    if not ok:
        raise WebTaskError(f"{why} — nothing was pressed")
    approval = policy.load(record["approval"])
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
    # PRESSED is not ACCEPTED. A site that hands the form back has refused
    # it, and calling that COMMITTED is the same lie as reporting "command
    # executed" as "goal achieved" (§30). Its own state, so a second press
    # needs a fresh yes and nothing counts it as done.
    verdict = str(result.get("verdict") or "submitted, unconfirmed")
    record.update({"state": "REJECTED" if verdict == "rejected" else "COMMITTED",
                   "result": result,
                   "say": (f"I pressed {record.get('button', 'it')!r}. "
                           + str(result.get("note", "")))[:400]})
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("action", "webtask",
                   f"pressed {record.get('button', '')[:40]!r} for {run_id} — "
                   f"{verdict}", actor=ACTOR)
    return record


PICKABLE = (BUDGET, ASK)


def carry_on(run_id: str, *, answers: dict | None = None, budget: int = 16,
             think=None, session=None) -> dict:
    """Pick a run back up — with his answers, if she asked for any.

    The two ways a run stops short are "I ran out of steps" and "only you
    can answer this", and both ended the same way: the page closed with
    the run and everything already typed went with it. Starting again
    meant watching her fill the same eleven fields and ask him the same
    three questions. Every real application has questions only he can
    answer, so that was not an edge case, it was the normal path.

    It is not a bypass. Picking it back up replays what she had done and
    then carries on into the same loop, which still stops at the same
    button and still asks him for the same one confirmation.
    """
    record = load_run(run_id)
    state = record.get("state")
    if state == RUNNING and not _stale(record):
        raise WebTaskError(f"{run_id} is running right now — let it finish")
    if state not in PICKABLE and state != RUNNING:
        raise WebTaskError(
            f"{run_id} is {state} — there is nothing waiting to be carried on")
    return run(record["goal"],
               start_url=record.get("replay_from") or record.get("url", ""),
               budget=budget, think=think, session=session,
               attempt=int(record.get("attempt", 1)), run_id=run_id,
               pick_up={"typed": record.get("typed") or [],
                        "attached": record.get("attached") or [],
                        "steps": record.get("steps") or [],
                        "answers": dict(answers or {})})


def retry(run_id: str, *, budget: int = 16, think=None, session=None) -> dict:
    """The site refused it. Read what it said, fix it, and ask him again.

    She was already saying *"read what it wants and I will fix it and try
    again"* with nothing behind it, which is a promise, not a capability.
    A REJECTED press is the one case where running it again is safe:
    the site did not accept anything, so there is nothing to duplicate.

    It is not a bypass. A retry is a new route, so it produces a NEW
    approval and waits for him exactly like the first one did.
    """
    record = load_run(run_id)
    if record.get("state") != "REJECTED":
        raise WebTaskError(
            f"{run_id} is {record.get('state')} — only a run the site refused "
            "can be tried again, because only then is nothing submitted")
    said = str(record.get("result", {}).get("evidence") or "")
    attempt = int(record.get("attempt", 1)) + 1
    fresh = f"{str(record['id']).split('--try')[0]}--try{attempt}"
    return run(record["goal"],
               start_url=record.get("replay_from") or record.get("url", ""),
               budget=budget, think=think, session=session,
               refused_before=said, run_id=fresh, attempt=attempt)


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
        settle(page)
        page = walk(ctx, page, hands, record.get("typed", []), attachments)
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
        # DID IT WORK? A press is an action; whether the site accepted it is
        # a different question, and the only honest source is what the page
        # says next. She pressed Submit on a form whose phone number the
        # site refused, got "there was a problem with your application"
        # back, and reported it as done.
        still_there = bool(formfill.blocking(page)) or bool(
            [f for f in formfill.read_all(page)
             if f.get("type") not in ("hidden", "submit", "button")])
        outcome = browse.read_outcome(body, did=record.get("button", ""),
                                      form_still_there=still_there)
        shot = runs_dir() / f"{record['id']}-after.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
        except Exception:
            shot = ""
        out = {"url": page.url, "title": page.title(), "evidence": body[:600],
               "screenshot": str(shot), **outcome}
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
    p_run.add_argument("--budget", type=int, default=16)
    p_go = sub.add_parser("commit"); p_go.add_argument("run_id")
    p_again = sub.add_parser("retry"); p_again.add_argument("run_id")
    p_on = sub.add_parser("carry-on")
    p_on.add_argument("run_id")
    p_on.add_argument("--answer", action="append", default=[],
                      metavar="LABEL=VALUE",
                      help="an answer to one of the questions she asked")
    sub.add_parser("waiting")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "run":
            record = run(args.goal, start_url=args.url, budget=args.budget)
            print(spoken(record))
            for entry in record["steps"]:
                print(f"  {entry['step'].get('action'):7} {entry['result'][:70]}")
        elif args.cmd == "carry-on":
            given = dict(pair.split("=", 1) for pair in args.answer if "=" in pair)
            more = carry_on(args.run_id, answers=given)
            print(spoken(more))
            for entry in more["steps"]:
                print(f"  {entry['step'].get('action'):7} {entry['result'][:70]}")
        elif args.cmd == "retry":
            again = retry(args.run_id)
            print(spoken(again))
            for entry in again["steps"]:
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
