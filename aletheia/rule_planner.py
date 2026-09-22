"""Plans compiled by RULES, with no model at all: the rung under her own model.

His words, 2026-09-21: *"it's to the point I can say whatever I want and
it will do stuff even when no frontier models are available."* Three rungs
make that true, and this is the bottom one. The frontier plans anything.
Her own model plans anything, slowly, when Ollama is up. And when there is
nothing - no subscription, no local model - a sentence that plainly means
one of the kinds below is compiled here, in a millisecond, from its words.

Two rules keep it honest, and both are the same rule `quick` lives by:

- **Exact shapes only.** A rule matches the whole sentence or it does not
  fire; a wrong compile reads fluently while sending the ask to the wrong
  verb, which is the failure he cannot detect. A sentence no rule owns
  returns None and goes on to her model, or to the queue that re-plans it
  when a model is back. Never a guess, never a catch-all.
- **Every gate still stands.** The plan this returns is the same shape her
  model returns, and it goes through `planner._classify`, the grammar, the
  registry and the approval tiers exactly as a model's plan would. Rules
  cannot reach a forbidden kind (they are checked against
  `intercom.PLANNER_FORBIDDEN` by test), cannot spend (the money door is
  asked before this runs), and a world-touching step still waits for his
  yes.

The plan SAYS it was planned by rules (`local_planner.COMPILED_BY_RULES`):
an answer he trusts as a model's and is not is the failure he cannot
detect.
"""
from __future__ import annotations

import re
from typing import Callable

from aletheia import intercom

PROVIDER = "aletheia.rules"
CONFIDENCE = 0.7

_FILLER = (r"^(?:(?:hey|ok|okay|please|thea|can you|could you|would you|will you|"
           r"i want you to|i need you to|go|just|now|go ahead and)[,!]?\s+)*")
_TAIL = r"(?:\s+(?:please|for me|now|thanks|thank you))*\s*[.!?]*$"
_URL = re.compile(r"(https?://\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|co|co\.uk|gov|edu|dev|app|ai)(?:/\S*)?)",
                  re.I)
_LISTS = {"reminders": "reminders", "reminder": "reminders", "tasks": "tasks", "task list": "tasks",
          "to do list": "tasks", "todo list": "tasks", "to-do list": "tasks",
          "shopping list": "shopping_list", "applications": "applications",
          "subscriptions": "subscriptions", "contacts": "contacts", "watches": "watches",
          "projects": "projects", "agents": "agents", "missions": "missions",
          "studies": "studies"}
_LIST_SAID = {"reminders": "your reminders", "tasks": "your tasks", "shopping_list": "the shopping list",
              "applications": "your applications", "subscriptions": "your subscriptions",
              "contacts": "your contacts", "watches": "what I'm watching for",
              "projects": "your projects", "agents": "my workers", "missions": "my missions",
              "studies": "your studies"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").casefold()).strip("-")[:40] or "task"


def _clean(text: str) -> str:
    return " ".join(str(text or "").split()).strip(" ,.;:")


def _with_scheme(url: str) -> str:
    url = str(url or "").strip().rstrip(".,")
    return url if url.lower().startswith("http") else "https://" + url


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(_with_scheme(url)).hostname or url).removeprefix("www.")


# ---- the rules -----------------------------------------------------------------
#
# Each is (pattern, kind, fill). `fill(match, request)` returns the step's
# arguments and the spoken summary, or None when the words are not enough
# to fill a required argument - in which case the rule did not fire.

def _task_new(m, request):
    text = _clean(m.group("what"))
    if len(text) < 3:
        return None
    from aletheia.voice import _split_deadline
    text, deadline = _split_deadline(text)
    args = {"description": text, "id": _slug(text)}
    if deadline:
        args["deadline"] = deadline
    return args, f"Add a task: {text}" + (f", due {deadline}" if deadline else "")


def _task_done(m, request):
    which = _clean(m.group("what"))
    return ({"which": which}, f"Mark {which} as done") if len(which) >= 3 else None


def _shopping_add(m, request):
    item = _clean(m.group("what"))
    return ({"item": item}, f"Add {item} to the shopping list") if item else None


def _shopping_off(m, request):
    item = _clean(m.group("what"))
    return ({"item": item}, f"Take {item} off the shopping list") if item else None


def _music(m, request):
    from aletheia import music
    word = (m.group("what") or "").strip().lower()
    action = {"play": "play", "put on": "play", "start": "play", "pause": "pause",
              "stop": "pause", "skip": "next", "next": "next", "previous": "previous",
              "back": "previous", "go back": "previous"}.get(word)
    if not action or action not in music.KEYS:
        return None
    said = {"play": "Play music", "pause": "Pause the music",
            "next": "Skip to the next song", "previous": "Go back a song"}[action]
    return {"action": action}, said


def _browse_read(m, request):
    url = _with_scheme(m.group("what"))
    return {"url": url}, f"Read {_host(url)} and tell you what it says"


#: Desktop programs he names, and the executable each one is. "Open
#: chrome" was compiled as "open chrome in the browser" - a page named
#: chrome - while `computer_do` could launch it all along (2026-09-22).
#: A shell or interpreter is never here (computer.FORBIDDEN_APPS).
APPS = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe", "edge": "msedge.exe",
    "microsoft edge": "msedge.exe", "firefox": "firefox.exe", "notepad": "notepad.exe",
    "word": "winword.exe", "microsoft word": "winword.exe", "excel": "excel.exe",
    "powerpoint": "powerpnt.exe", "outlook": "outlook.exe", "spotify": "spotify.exe",
    "calculator": "calc.exe", "the calculator": "calc.exe", "explorer": "explorer.exe",
    "file explorer": "explorer.exe", "task manager": "taskmgr.exe", "paint": "mspaint.exe",
    "discord": "discord.exe", "slack": "slack.exe", "teams": "ms-teams.exe", "zoom": "zoom.exe",
    "vs code": "code.exe", "vscode": "code.exe", "visual studio code": "code.exe",
}


def _open_app(m, request):
    what = _clean(m.group("what"))
    app = APPS.get(what.casefold())
    if not app:
        return None
    return ({"steps": [{"action": "open_app", "app": app, "arguments": []}]},
            f"Open {what.title() if what.islower() else what}")


#: Folders he names by their Windows name. "Open my downloads folder" was
#: compiled as a page called "my downloads folder" (2026-09-22).
FOLDERS = ("downloads", "documents", "desktop", "pictures", "music", "videos")


def _open_folder(m, request):
    from pathlib import Path
    name = _clean(m.group("folder")).casefold()
    if name not in FOLDERS:
        return None
    path = Path.home() / name.title()
    if not path.is_dir():
        return {"say": f"There's no {name.title()} folder under your user folder here."}
    return ({"steps": [{"action": "open_app", "app": "explorer.exe", "arguments": [str(path)]}]},
            f"Open your {name.title()} folder")


def _lock(m, request):
    return {"steps": [{"action": "lock_screen"}]}, "Lock this computer"


def _close_app(m, request):
    # Closing a program is the one desktop act unattended hands never do
    # (`computer.ACT_ACTIONS`): it can lose unsaved work. Said, not guessed.
    what = _clean(m.group("what"))
    if what.casefold() not in APPS:
        return None
    return {"say": f"I don't close programs — closing can lose unsaved work. "
                   f"Alt+F4 closes {what.title() if what.islower() else what}; "
                   "I can open it, bring it to the front and read its windows."}


def _open_site(m, request):
    what = _clean(m.group("what"))
    if not what or len(what) > 40:
        return None
    if what.casefold() in APPS:
        return None   # a program, not a page: the app rule owns it
    if re.search(r"(?:^| )(?:folder|directory|file|drive)$", what.casefold()):
        return None   # a place on his disk is never a web page
    found = _URL.search(what)
    args = {"goal": f"Open {what} in the browser"}
    if found:
        args["url"] = _with_scheme(found.group(1))
    return args, f"Open {what} in the browser"


def _web_task(m, request):
    goal = _clean(m.group("what"))
    if len(goal) < 4:
        return None
    args = {"goal": goal}
    found = _URL.search(goal)
    if found:
        args["url"] = _with_scheme(found.group(1))
    return args, f"Do this on the web: {goal}"


def _contact_add(m, request):
    name = _clean(m.group("what"))
    if not name or len(name) > 60:
        return None
    args = {"name": name}
    detail = _clean(m.group("detail") or "")
    if "@" in detail:
        args["email"] = detail
    elif re.search(r"\d{3}", detail):
        args["phone"] = detail
    return args, f"Save {name} as a contact"


def _recall(m, request):
    about = _clean(m.group("what"))
    return ({"about": about}, f"Tell you what I know about {about}") if about else None


#: "my sister", "my landlord's number": people; a company: organizations;
#: "I", "my name/birthday/address": identity; the rest is a preference.
_PEOPLE = re.compile(r"\b(?:sister|brother|mom|mum|mother|dad|father|wife|husband|partner|girlfriend|"
                     r"boyfriend|son|daughter|kid|friend|landlord|landlady|boss|manager|doctor|dentist|"
                     r"neighbou?r|cousin|aunt|uncle|grandma|grandpa|roommate|coworker|colleague|"
                     r"accountant|lawyer|barber|vet|plumber|mechanic)\b", re.I)
_ORGS = re.compile(r"\b(?:company|employer|bank|gym|school|church|clinic|dealership|insurer|"
                   r"insurance|provider|landlord company|work)\b", re.I)
_IDENTITY = re.compile(r"^(?:my )?(?:name|birthday|birth date|date of birth|address|home address|"
                       r"postcode|zip(?: code)?|phone(?: number)?|number|email(?: address)?|"
                       r"blood type|height|weight|shoe size|size|allergies|allergy)$", re.I)


def _remember(m, request):
    """"remember my landlord is Dana Whitfield" - the most ordinary thing
    an assistant is told, compiled with no model. The key is what he
    called it, without "my"; the value keeps his capitals."""
    key = _clean(m.group("key")).lower()
    value = _clean(m.group("value"))
    for lead in ("my ", "the ", "that my ", "that the ", "that "):
        if key.startswith(lead):
            key = key[len(lead):]
    key = re.sub(r"'s (?:name|number|phone|email|address|birthday)$", "", key).strip()
    if not key or not value or len(key) > 60 or len(value) > 200:
        return None
    if _IDENTITY.match(key):
        domain = "identity"
    elif _PEOPLE.search(key):
        domain = "people"
    elif _ORGS.search(key):
        domain = "organizations"
    else:
        domain = "preferences"
    return {"domain": domain, "key": key, "value": value}, f"Remember your {key}: {value}"


def _file_find(m, request):
    query = _clean(m.group("what"))
    return ({"query": query}, f"Find {query} in your files") if query else None


def _file_read(m, request):
    path = _clean(m.group("what"))
    return {"path": path}, f"Read {path}"


def _watch_email(m, request):
    who = _clean(m.group("what"))
    return ({"who": who}, f"Watch for an email from {who}") if who else None


def _travel(m, request):
    place = _clean(m.group("what"))
    return ({"place": place}, f"Work out how long it takes to get to {place}") if place else None


def _subscription_cancel(m, request):
    which = _clean(m.group("what"))
    return ({"subscription": which}, f"Cancel your {which} subscription") if which else None


def _read_resume(m, request):
    """His resume, wherever it is - and when there is none, the SENTENCE
    that says so. The shape was matched and the fill returned None, so
    "read me my resume" with no resume on the PC was kept for a model to
    plan, which is a worse answer than the one she already had."""
    from aletheia import applications
    try:
        path = applications.find_resume("")
    except Exception:  # noqa: BLE001 - its message is written for a log, in the third person
        path = ""
    if not path:
        return {"say": ("I can't find a resume on this PC. I looked in Documents, Downloads, Desktop "
                        "and my own workspace. Drop a copy in Documents and I'll read it.")}
    return {"path": str(path), "anywhere": True}, "Read your resume"


def _message(m, request):
    """"Text my sister I'm running late": a draft and an approval, never a
    send. An unknown recipient is the answer, not an approval that fails
    after he says yes - `messages.draft` refuses a number it does not
    have, so the same check runs here, before anything is offered."""
    from aletheia import messages
    who = _clean(m.group("who"))
    body = _clean(m.group("body"))
    if not who or not body:
        return None
    number, name = messages.resolve_number(who)
    if number is None:
        return {"say": f"I don't have a phone number for {name or who}. Tell me the number once and I'll remember it."}
    return {"to": who, "body": body}, f"Text {name or who}: {body}"


#: The kind a rule returns when the sentence's answer is already known:
#: no step, one thing to say. Never in the grammar, never executed.
ANSWER = "answer"


def _no_args(said: str):
    return lambda m, request: ({}, said)


def _read_list(m, request):
    kind = _LISTS.get(_clean(m.group("what")).lower())
    if not kind:
        return None
    return {"__kind__": kind}, f"Read you {_LIST_SAID[kind]}"


RULES: tuple[tuple[str, str, Callable], ...] = (
    (r"(?:add|make|create|put|set up|new)\s+(?:a |an )?(?:new )?(?:task|to-?do|todo)(?: for me)?(?: to| :|:)?\s+(?P<what>.+)",
     "task_new", _task_new),
    (r"(?:add|put)\s+(?P<what>.+?)\s+(?:to|on)\s+(?:my |the )?(?:task list|to-?do list|todo list|tasks)",
     "task_new", _task_new),
    (r"(?:mark|tick|check)(?: off)?\s+(?P<what>.+?)\s+(?:as )?(?:done|complete|completed|finished)",
     "task_done", _task_done),
    # "I did X" needs the "I": "did I get any replies" is a question, and
    # it was marked done as a task called "i get any replies".
    (r"(?:i(?:'ve| have)? (?:did|finished|completed|done with|took care of)|done with|finished)"
     r"\s+(?:the )?(?P<what>(?!i |you |we |it |they )[^?]+?)(?: task| thing)?",
     "task_done", _task_done),
    (r"(?:add|put)\s+(?P<what>.+?)\s+(?:to|on)\s+(?:my |the )?(?:shopping )?list", "shopping_add", _shopping_add),
    (r"(?:take|remove|cross|delete|strike)\s+(?P<what>.+?)\s+(?:off|from)\s+(?:my |the )?(?:shopping )?list",
     "shopping_off", _shopping_off),
    (r"(?P<what>play|put on|start)(?: some| the| my)? music|(?P<what2>play)(?: me)? (?:something|anything)(?: \w+)?|"
     r"put (?:some |the )?music on", "music",
     lambda m, r: _music(type("M", (), {"group": lambda self, k: (m.group("what") or m.group("what2") or "play")})(), r)),
    (r"(?:turn (?:the music |it |the song )?off|turn off the (?:music|song)|stop the (?:music|song)|kill the music)",
     "music", lambda m, r: ({"action": "pause"}, "Pause the music") if "pause" in __import__("aletheia.music", fromlist=["KEYS"]).KEYS else None),
    (r"(?P<what>pause|stop|skip|next|previous|back|go back)(?: the| this)? (?:music|song|track)", "music", _music),
    (r"(?P<what>next|skip|previous|pause) (?:song|track)|(?P<what2>next|skip) it", "music",
     lambda m, r: _music(type("M", (), {"group": lambda self, k: (m.group("what") or m.group("what2"))})(), r)),
    (r"(?:read|read me|open|show me|pull up|check|look at)\s+(?P<what>https?://\S+|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|co|co\.uk|gov|edu|dev|app|ai)(?:/\S*)?)"
     r"(?: and (?:tell me|read me|say) what (?:it says|is on it|it is))?", "browse_read", _browse_read),
    (r"open (?:the |my )?(?:folder|file|document|directory)s? (?:with|containing|for|of|that has) (?:my |the )?(?P<what>.+)",
     "file_find", _file_find),
    (r"(?:open|open up|show me|go to|bring up)\s+(?:my |the )?(?P<folder>[a-z]+)(?: folder| directory)(?: for me| please)?",
     "computer_do", _open_folder),
    (r"lock (?:the |this |my )?(?:computer|pc|laptop|screen|machine|workstation)(?: for me| please)?|lock it",
     "computer_do", _lock),
    (r"(?:close|quit|exit|shut|shut down|kill)\s+(?P<what>[a-z][a-z ]{2,24}?)(?: for me| please| down)?",
     "computer_do", _close_app),
    (r"(?:open|open up|launch|start|run|bring up|fire up)\s+(?P<what>[a-z][a-z ]{2,24}?)(?: for me| please| up)?",
     "computer_do", _open_app),
    (r"(?:open|go to|pull up|bring up|launch)\s+(?P<what>(?!the folder|the file|my folder|my file)[a-z0-9][a-z0-9 .'-]{1,39}?)(?: in (?:the |my )?browser| for me)?",
     "web_task", _open_site),
    (r"find (?:me |us )?(?:a |an |some )?(?P<what>.+?) (?:near me|nearby|near here|around here|in town|close by)",
     "web_task", lambda m, r: ({"goal": f"find {_clean(m.group('what'))} near him"}, f"Look up {_clean(m.group('what'))} near you")),
    (r"(?:go|get) (?:online|on the (?:web|internet)) and (?P<what>.+)", "web_task", _web_task),
    (r"(?:on the (?:web|internet)|online),? (?P<what>.+)", "web_task", _web_task),
    (r"(?:sign me up for|sign up for|register (?:me )?(?:for|on)|create (?:me )?an account (?:on|at|with)|log ?in to|fill (?:in|out)|"
     r"order(?: me)?|book(?: me)?|reserve(?: me)?|renew|apply for|download|look up on|check on)\s+(?P<what>.+)",
     "web_task", lambda m, r: _web_task(m, r) and ({**_web_task(m, r)[0], "goal": _clean(r)}, f"Do this on the web: {_clean(r)}")),
    (r"(?:add|save)\s+(?P<what>[a-z][a-z .'-]{1,59}?)\s+(?:as a contact|to (?:my )?contacts)(?:[,:]?\s*(?:number|phone|email|at)?\s*(?P<detail>\S+))?",
     "contact_add", _contact_add),
    (r"remember(?: that)? (?P<key>(?:my |the )?[a-z][a-z' -]{1,50}?) (?:is|are|was|=|is called|is named) (?P<value>.+)",
     "remember", _remember),
    (r"(?:remember|save|note|keep in mind)(?: that)? (?P<key>my [a-z][a-z' -]{1,50}?)(?:'s (?:name|number|phone|email|address|birthday))? (?:is|are|was) (?P<value>.+)",
     "remember", _remember),
    (r"what do (?:you|u) (?:know|remember) about (?P<what>.+)|what did i tell (?:you|u) about (?P<what2>.+)",
     "recall", lambda m, r: _recall(type("M", (), {"group": lambda self, k: (m.group("what") or m.group("what2"))})(), r)),
    (r"(?:find|locate|look for|where(?:'s| is))\s+(?:my |the )?(?P<what>.+?)\s*(?:file|document|pdf|spreadsheet|doc)\b.*",
     "file_find", _file_find),
    (r"(?:find|locate|where(?:'s| is))\s+(?:my |the )?(?P<what>[^ ]+\.(?:pdf|docx?|xlsx?|txt|md|json|csv|pptx?))",
     "file_find", _file_find),
    (r"(?:read|open|show me)\s+(?:my |the )?(?P<what>\S+\.(?:pdf|docx?|txt|md|json|csv))", "file_read", _file_read),
    (r"(?:take a |grab a |get a )?screenshot(?: of (?:my |the )?screen)?|screenshot (?:my |the )?screen",
     "screenshot", _no_args("Take a screenshot")),
    (r"(?:watch|look out|keep an eye out|wait) for (?:an? )?(?:email|e-?mail|mail|message) from (?P<what>.+)",
     "watch_email_from", _watch_email),
    (r"(?:check|read|any|got any|are there any|is there any|do i have (?:any )?)\s*(?:my |the )?(?:new |unread )?"
     r"(?:emails?|e-?mails?|mail|inbox|messages)(?: for me| today)?",
     "email_check", _no_args("Check your email")),
    (r"read (?:me )?(?:my )?(?:resume|cv|résumé)(?: to me| out| out loud)?", "file_read", _read_resume),
    (r"(?:text|message|sms|send a (?:text|message) to) (?P<who>my [a-z]+|[a-z]+(?: (?!that\b|saying\b|and\b|to\b|i\b|i'm\b|im\b|we\b|please\b)[a-z]+)?|[\d() +-]{7,20})"
     r"(?:,? (?:that|saying|and say|and tell (?:him|her|them)(?: that)?|to say) |: |, | )(?P<body>.+)",
     "message_send", _message),
    (r"how (?:long|far)(?: is it| does it take| would it take| will it take| away is it)?\s+(?:to (?:get |drive |walk )?to|from here to)\s+(?P<what>.+)"
     r"|how far (?:is|away is|to) (?:it to )?(?P<what2>.+)",
     "travel_time", lambda m, r: _travel(type("M", (), {"group": lambda self, k: (m.group("what") or m.group("what2"))})(), r)),
    (r"cancel (?:my |the )?(?P<what>.+?)\s+(?:subscription|membership|plan)", "subscription_cancel", _subscription_cancel),
    (r"(?:what(?:'s| are| is)|show me|list|read me|read out|what(?:'s| is) on)\s+(?:my |the |your )?(?P<what>reminders?|tasks|task list|to-?do list|todo list|shopping list|applications|subscriptions|contacts|watches|projects|agents|missions|studies)",
     "__list__", _read_list),
    (r"what (?:am i|do i have to|do i need to) (?:do|doing)(?: today| next)?|what(?:'s| is) on my (?:to-?do|todo) list",
     "tasks", _no_args("Read you your tasks")),
    (r"(?:what(?:'s| is|s)? )?(?:the |my )?(?:morning |daily )?brief(?:ing)?(?: for today| today)?|give me the brief(?:ing)?",
     "brief", _no_args("Read you the brief")),
    # LAST: "what's my wifi password" is a thing he told her to remember.
    # The profile fields ("what's my email") and every list are matched
    # above this and in `quick`, so what reaches here is a remembered fact.
    (r"what(?:'s| is|s) my (?P<what>(?!email|phone|number|name|city|town|address|calendar|schedule|"
     r"agenda|list|tasks|reminders|balance)[a-z][a-z0-9 '-]{2,40}?)(?: again)?",
     "recall", _recall),
)

_COMPILED = tuple((re.compile(_FILLER + "(?:" + pattern + ")" + _TAIL, re.I), kind, fill)
                  for pattern, kind, fill in RULES)


def _catalog_kinds() -> set[str]:
    return {k for k in intercom.KIND_ARGS if k not in intercom.PLANNER_FORBIDDEN}


def match(request: str) -> tuple[str, dict, str] | None:
    """(kind, args, summary) for a sentence a rule owns whole, else None."""
    text = " ".join(str(request or "").split()).strip()
    if not text or len(text) > 400:
        return None
    # Matched on his sentence AS HE SAID IT (the patterns are
    # case-insensitive), so "save Dana Brooks as a contact" keeps its
    # capitals: the layer that matched on a lowercased copy stored "dana
    # brooks" (CLAUDE.md, `voice._as_he_said`).
    allowed = _catalog_kinds()
    for pattern, kind, fill in _COMPILED:
        m = pattern.fullmatch(text)
        if not m:
            continue
        try:
            filled = fill(m, text)
        except Exception:  # noqa: BLE001 - a rule that cannot fill did not fire
            filled = None
        if not filled:
            continue
        if isinstance(filled, dict) and set(filled) == {"say"}:
            said = " ".join(str(filled["say"] or "").split())
            if said:
                return ANSWER, {"say": said}, said
            continue
        args, summary = filled
        if kind == "__list__":
            kind = args.pop("__kind__")
        if kind not in allowed:
            continue
        required, optional = intercom.KIND_ARGS.get(kind, (set(), set()))
        if not set(required) <= set(args) or not set(args) <= set(required) | set(optional):
            continue
        return kind, args, summary
    return None


def compile(request: str, *, now: str | None = None) -> dict | None:
    """The same shape her model returns, or None when no rule owns the sentence."""
    found = match(request)
    if not found:
        return None
    kind, args, summary = found
    if kind == ANSWER:
        return {"intent": "answer", "summary": summary[:200], "steps": [],
                "spoken": summary, "required_capabilities": [], "confidence": CONFIDENCE}
    return {"intent": "plan", "summary": summary[:200],
            "steps": [{"kind": kind, **args}],
            "required_capabilities": [], "confidence": CONFIDENCE}


def certain_answer(request: str) -> str | None:
    """The sentence a rule already has for this ask, or None. What
    `quick` is to questions about her stores, this is to instructions
    whose answer is settled by a fact on disk: no resume, no number."""
    found = match(request)
    return found[1]["say"] if found and found[0] == ANSWER else None


def kinds_named() -> set[str]:
    """Every kind a rule can compile into - for the test that holds them to the grammar."""
    return {kind for _p, kind, _f in RULES if kind != "__list__"} | set(_LISTS.values())
