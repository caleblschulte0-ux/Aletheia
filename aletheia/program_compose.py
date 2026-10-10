"""A long-mission task is a COMPOSITION of tools she already has, chosen by capability.

Continuity brief IV.13: *"No special 'new life' code: compose capabilities
dynamically."* A task in a long mission (`aletheia.programs`) says what it has
to DO in plain words ("look up what renting costs there", "send a message to
the person who listed it", "put the visit on the calendar") and, optionally,
which tools a model thought fit. This module turns that into steps over the
one tool catalog (`aletheia.tools`: every intercom kind plus the declared
tools), by matching what each tool IS - its name and its description - against
what the step needs. Nothing here names a domain, a site, a person or a
project; a new tool joins every mission the moment its descriptor exists.

Three outcomes per need:

- a tool whose descriptor matches: a step. Whether it runs here or is handed to
  Caleb is NOT decided here; `agent_session.Broker` decides at run time, the
  same gate every session uses (ability and permission stay separate).
- a tool that exists but is not usable on this machine: a step that will wait,
  and the reason travels with it.
- no tool at all: a capability gap, classified by `work_gaps.classify` into its
  next action (another tool, a browser path, ask Caleb, wait, queue a build,
  or refuse by policy). Never a dead end.

`VERB_SENSES` is the only vocabulary here: what ordinary verbs of doing mean in
the words tool descriptions use. It is about ACTS (contact, schedule, look up,
remember), never about what a life contains.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

#: Ordinary verbs -> the words tool descriptors use for that act.
VERB_SENSES: dict[str, tuple[str, ...]] = {
    "contact": ("message", "email", "send", "draft", "text"),
    "message": ("message", "send", "text", "email"),
    "email": ("email", "mail", "draft", "send"),
    "write": ("draft", "compose", "document", "write"),
    "reach": ("message", "email", "send"),
    "reply": ("reply", "email", "message"),
    "ask": ("message", "email", "question"),
    "call": ("phone", "call", "message"),
    "schedule": ("calendar", "meeting", "meet", "free", "slot", "event", "remind"),
    "book": ("calendar", "meeting", "event"),
    "arrange": ("calendar", "meeting", "meet", "slot"),
    "calendar": ("calendar", "event", "meeting"),
    "remind": ("remind", "reminder"),
    "research": ("research", "sources", "search", "web", "pages", "question"),
    "look": ("research", "search", "read", "page", "find"),
    "find": ("search", "find", "research", "discover"),
    "search": ("search", "research", "find"),
    "compare": ("research", "sources", "compare"),
    "read": ("read", "page", "browse"),
    "check": ("read", "check", "status", "search"),
    "browse": ("browse", "page", "website", "browser"),
    "track": ("task", "status", "watch", "record"),
    "watch": ("watch", "monitor", "notify"),
    "note": ("note", "remember", "memory"),
    "remember": ("remember", "memory", "recall"),
    "recall": ("recall", "memory", "remember"),
    "register": ("register", "event"),
    "rsvp": ("rsvp", "register", "event"),
    "join": ("join", "register"),
    "subscribe": ("join", "register"),
    "list": ("list", "task", "tasks"),
    "plan": ("plan", "task", "steps"),
    "apply": ("apply", "application", "form"),
    "fill": ("form", "fill", "apply"),
    "save": ("save", "file", "write", "document"),
    "organize": ("task", "list", "file", "document"),
    "summarize": ("research", "document", "compose", "summary"),
    "travel": ("travel", "journey", "time"),
    "commute": ("travel", "journey", "time"),
    "route": ("travel", "journey", "time"),
}

#: Words that carry no meaning about what a tool does.
_STOP = frozenset("""a an and or the to of for in on at by with from into about as is are be it its
this that these those his her their my your our me you him them she he i we us do does did can could
would should will may might must not no yes any all some each every one two three new more most very
just also then than so if when where which who whom what how why there here up out over under after
before between within without per via using use used get got make made take thing things someone
something anything caleb thea aletheia want wants need needs""".split())

#: Tool words too generic to count as a match on their own.
_WEAK = frozenset({"command", "kind", "records", "record", "operator", "local", "state", "returns", "result"})

MATCH_THRESHOLD = 3


def _stem(word: str) -> str:
    for suffix in ("ings", "ing", "ies", "ied", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            base = word[: -len(suffix)]
            return base + ("y" if suffix in ("ies", "ied") else "")
    return word


def words(text: Any) -> set[str]:
    raw = re.findall(r"[a-z][a-z']+", str(text or "").lower().replace("_", " ").replace(".", " "))
    return {_stem(w.strip("'")) for w in raw if w not in _STOP and len(w) > 2}


def need_words(need: str) -> set[str]:
    """The need's own words plus what its verbs mean in descriptor language."""
    base = words(need)
    out = set(base)
    for w in base:
        out |= {_stem(s) for s in VERB_SENSES.get(w, ())}
    return out


def excluded(tool) -> str:
    """Why a tool is never composed into a mission step, or ""."""
    from aletheia import intercom, tools as tools_mod
    name = tool.name
    if tool.kind and tool.kind in intercom.PLANNER_FORBIDDEN:
        return "a switch only Caleb's words reach"
    if name in {"approve", "deny", "resume", "halt"}:
        return "decides about authority"
    if tool.kind and tool.kind in tools_mod.SWITCH_KINDS:
        return "a switch"
    if tool.destructive:
        return "removes or stops something"
    if name.startswith("mission_") or name.startswith("mission.") or name == "missions":
        return "the long-mission layer itself"
    if name in {"intent", "handle", "agent_new", "rule", "dispatch"}:
        return "starts a planner or worker of its own"
    if re.search(r"(?:^|_)(?:answer|retry|outcome|stop|off)$", name):
        return "continues or ends something already started"
    return ""


_REGISTRY_WORDS: dict[str, str] = {}


def _capability_text(tool) -> str:
    """The registry's own description of what the tool's capability is, when known."""
    if not tool.capability:
        return ""
    if not _REGISTRY_WORDS:
        try:
            from aletheia import capabilities
            for entry in capabilities.load_registry().get("capabilities", []):
                _REGISTRY_WORDS[str(entry.get("id"))] = str(entry.get("description") or "")
        except Exception:  # noqa: BLE001 - the descriptor alone still decides
            _REGISTRY_WORDS["_"] = ""
    return _REGISTRY_WORDS.get(tool.capability, "")


def _tool_words(tool) -> tuple[set[str], set[str]]:
    return words(tool.name), (words(tool.description) | words(_capability_text(tool))) - _WEAK


#: "Free" that means costing nothing, not free time: "free newcomer events" matched the tool
#: that finds free time on his calendar, and the search for events never ran (his PC, 2026-10-10).
NO_COST_FREE = re.compile(r"\bfree\s+(?!time\b|windows?\b|slots?\b|hours?\b|evenings?\b|days?\b|"
                          r"afternoons?\b|mornings?\b|weekends?\b|periods?\b|blocks?\b|on\b|at\b|between\b|"
                          r"for\b|to\b)", re.I)


def score(need: str, tool) -> int:
    want = need_words(NO_COST_FREE.sub("", str(need or "")))
    name_w, desc_w = _tool_words(tool)
    return 3 * len(want & name_w) + len((want & desc_w) - name_w)


def usable_tools(catalog: dict) -> dict:
    return {name: t for name, t in catalog.items() if not excluded(t)}


#: A need that STARTS with one of these is a look-up: it is met by reading, and
#: a tool that changes something (a form filled, an event registered, a web
#: task that needs his approval) is never the answer to it. Measured on his PC
#: 2026-10-09: "Search for upcoming job fairs, hiring events..." waited for his
#: approval, because the step went to the website catch-all.
LOOKUP_VERBS = frozenset({"search", "find", "look", "research", "read", "check", "compare", "browse",
                          "discover", "identify", "scan", "review", "see", "learn",
                          # A recurring look: a weekly sweep and a watch both waited for his
                          # yes on 2026-10-10.
                          "watch", "monitor", "sweep", "scout"})
#: How often, said before the verb: "Weekly sweep", "Daily check". Not the act itself.
CADENCE_WORDS = frozenset({"daily", "weekly", "monthly", "nightly", "hourly", "regular", "recurring"})


#: A need that STARTS with one of these does something: a task that also holds, signs up or
#: writes is not a look-up, so the tools named for those acts are kept (2026-10-10: "Find free
#: newcomer events" with "hold fitting ones" and "register for free ones" kept only a reader).
DOING_VERBS = frozenset({"hold", "register", "sign", "book", "write", "save", "send", "apply", "prepare",
                         "pencil", "put", "add", "update", "draft", "submit", "schedule", "email", "message"})


def does_something(need: str) -> bool:
    said = [w for w in re.findall(r"[a-z]+", str(need or "").lower())]
    while said and said[0] in CADENCE_WORDS:
        said = said[1:]
    return bool(said) and said[0] in DOING_VERBS


def looks_up(need: str) -> bool:
    said = [w for w in re.findall(r"[a-z]+", str(need or "").lower())]
    while said and said[0] in CADENCE_WORDS:
        said = said[1:]
    return bool(said) and said[0] in LOOKUP_VERBS


def reader_for(task: dict, catalog: dict) -> Any:
    """The reading tool for a task that looks something up, or None.

    Its own needs are asked before its title: a title saying "watch ..." matched the tool that
    watches a PAGE, which needs an address the task never had, so it asked him for a url
    (2026-10-10), while the need under it was plainly a search. A reader whose required
    address the task does not contain is not one that fits."""
    text = " ".join(str(x) for x in (task.get("title"), task.get("detail"), *(task.get("does") or [])) if x)
    has_address = bool(re.search(r"https?://|www\.", text))
    readers = {n: t for n, t in catalog.items() if t.read_only
               and (has_address or "url" not in ((t.input_schema or {}).get("required") or []))}
    phrases = [str(n) for n in task.get("does") or [] if looks_up(str(n))] + [str(task.get("title") or "")]
    for phrase in phrases:
        tool, _top = best_tool(phrase, readers)
        if tool is not None:
            return tool
    return None


def best_tool(need: str, catalog: dict) -> tuple[Any, int]:
    best, top = None, 0
    reading = looks_up(need)
    for name, tool in sorted(usable_tools(catalog).items()):
        if reading and not tool.read_only:
            continue
        # A look-up about the world reads the world: her own repository is not where events are.
        # (+1 tied "search for newly listed events" between research and repo.list, and the
        # tie went to her own repository by name order - his PC, 2026-10-10.)
        s = score(need, tool) + (2 if reading and tool.open_world else 0)
        # Prefer what only looks when two tools tie: the smaller act first.
        if s > top or (s == top and s and best is not None and tool.read_only and not best.read_only):
            best, top = tool, s
    return (best, top) if top >= MATCH_THRESHOLD else (None, top)


def menu(text: str, catalog: dict, *, limit: int = 24, width: int = 90) -> list[str]:
    """The tools most relevant to `text`, one line each, for a shaping prompt."""
    ranked = []
    for name, tool in usable_tools(catalog).items():
        s = score(text, tool)
        if s:
            ranked.append((-s, name, tool))
    ranked.sort()
    return [f"{name}: {' '.join(tool.description.split())[:width]}" for _s, name, tool in ranked[:limit]]


def requirements(tool) -> list[str]:
    """What a step on this tool needs from the world, in `work_states.REQUIREMENTS`."""
    from aletheia import work_engine
    reqs = work_engine._caps_to_requirements([c for c in (tool.capability, tool.name) if c])
    if tool.open_world:
        reqs.append("network")
    return list(dict.fromkeys(reqs))


def compose(task: dict, catalog: dict, *, registry: dict | None = None) -> dict:
    """Steps over existing tools for one task, plus the gaps. Pure but for the registry.

    `task` carries "title", "detail", "does" (need phrases) and "uses" (tool names a
    model suggested). Returns {"steps", "requires", "gaps"}."""
    from aletheia import work_gaps
    usable = usable_tools(catalog)
    steps: list[dict] = []
    seen: set[str] = set()
    does = [str(n) for n in (task.get("does") or []) if str(n).strip()]
    title = str(task.get("title") or "")
    # A task looks something up when its title says so, or when every thing it does does
    # ("Weekly sweep for new events" whose one need is "search for newly listed events").
    lookup = "" if any(does_something(n) for n in does) else (
        title if looks_up(title) else (does[0] if does and all(looks_up(n) for n in does) else ""))
    for name in task.get("uses") or []:
        tool = usable.get(str(name))
        if tool is not None and lookup and not tool.read_only:
            # A model named a doing tool for a task that only looks something up: the reading tool
            # that fits does it without asking him. With none, the named one stands.
            tool = reader_for(task, catalog) or tool
        if tool is not None and tool.name not in seen:
            steps.append({"tool": tool.name, "for": "", "by": "named", "score": None})
            seen.add(tool.name)
    needs = does
    if not needs and not steps:
        needs = [" ".join(str(x) for x in (task.get("title"), task.get("detail")) if x)]
    gaps: list[dict] = []
    named = bool(steps)
    for need in needs:
        if named:
            # A model that named the tools is trusted to have covered the task with them; only the one
            # permanent rule is re-checked on each need, so naming a tool can never carry a payment.
            verdict = work_gaps.classify(need, registry=registry)
            if verdict["outcome"] == "refuse_policy":
                gaps.append({"need": need, "outcome": verdict["outcome"], "why": verdict["why"],
                             "next": verdict["next"], "state": verdict["state"], "tool": ""})
            elif not steps[0]["for"]:
                steps[0]["for"] = need
            continue
        covered = next((s for s in steps if score(need, catalog[s["tool"]]) >= MATCH_THRESHOLD), None)
        if covered is not None:
            covered["for"] = covered["for"] or need
            continue
        tool, top = best_tool(need, catalog)
        if tool is not None and lookup and not tool.read_only:
            # "Check the confidentiality of the setup" whose need says "confirm which calendar
            # holds are written to" matched the tool that WRITES a hold, and asked him for a time.
            reader = reader_for(task, catalog)
            tool = reader if reader is not None else tool
        if tool is None:
            verdict = work_gaps.classify(need, registry=registry)
            gaps.append({"need": need, "outcome": verdict["outcome"], "why": verdict["why"],
                         "next": verdict["next"], "state": verdict["state"], "tool": verdict.get("tool") or ""})
            if verdict.get("tool") and verdict["tool"] in usable and verdict["tool"] not in seen:
                steps.append({"tool": verdict["tool"], "for": need, "by": "gap:" + verdict["outcome"],
                              "score": top})
                seen.add(verdict["tool"])
            continue
        if tool.name in seen:
            continue
        steps.append({"tool": tool.name, "for": need, "by": "matched", "score": top})
        seen.add(tool.name)
    if named:
        for step in list(steps):
            if step["for"] and looks_up(step["for"]) and not catalog[step["tool"]].read_only:
                # A named doing tool whose own step only looks something up ("find matching
                # postings" given to the tool that prepares applications) handed a READ to him.
                # The look runs first on its own; the doing tool keeps its own gate after it.
                reader = reader_for({"title": title, "does": [step["for"]]}, catalog)
                if reader is not None and reader.name not in seen:
                    seen.add(reader.name)
                    moved = step["for"]
                    steps.insert(steps.index(step), {"tool": reader.name, "for": moved, "by": "reader",
                                                     "score": None})
                    step["for"] = ""
                    rest = [n for n in needs if n != moved]
                    if not any(score(n, catalog[step["tool"]]) >= MATCH_THRESHOLD
                               for n in rest) and not any(s is not step and s["tool"] == step["tool"] for s in steps):
                        # It was named only for the look the reader now does: nothing is left for it,
                        # and an idle doing step would only hand him an empty approval.
                        others = [x for x in steps if x is not step and not catalog[x["tool"]].read_only]
                        if others:
                            steps.remove(step)
                            seen.discard(step["tool"])
    reqs: list[str] = []
    for step in steps:
        reqs += requirements(catalog[step["tool"]])
    return {"steps": steps, "requires": list(dict.fromkeys(reqs)), "gaps": gaps}


# ---- arguments ------------------------------------------------------------------------

#: Argument names that mean "what this is about", filled from the task's own words.
TOPIC_ARGS = ("question", "query", "request", "text", "idea", "what", "goal", "description", "topic",
              "about", "purpose", "body", "note", "summary")
#: Argument names that mean "who": filled from the person the task then waits on, when it names one.
PERSON_ARGS = ("to", "person", "recipient", "who", "contact")


def mints_id(tool) -> bool:
    """Does this tool CREATE the thing its `id` names? Only then may an id be made up:
    `task_status` and `approve` take an id that must already exist, and a made-up one
    there is a wrong answer, not a missing one."""
    return str(tool.kind or tool.name).endswith("_new")


def new_id(words: str) -> str:
    """A lowercase-kebab id from the task's own words, with a short digest so two tasks
    that start alike do not collide. The same words always give the same id, so a retry
    finds the record its first attempt made instead of minting a second one."""
    slug = "-".join(re.findall(r"[a-z0-9]+", words.lower()))[:40].strip("-") or "task"
    return f"{slug}-{hashlib.sha256(words.encode('utf-8')).hexdigest()[:6]}"


def fill_args(tool, task: dict, given: dict | None = None) -> tuple[dict, list[str]]:
    """(args, still_missing). Topic-shaped string arguments come from the task's words,
    and a creating tool's new id is minted from them; anything else must come from the
    step itself, a model (`model_args`), or Caleb."""
    schema = tool.input_schema or {}
    props = schema.get("properties") or {}
    args = {k: v for k, v in dict(given or {}).items() if k in props}
    if "path" in args and tool.writes and set(tool.writes) <= {"workspace"}:
        # A path in her own workspace that the workspace would refuse (a model wrote
        # "C:\\Users\\...\\Documents\\Aletheia\\answers.md") is a path not given: it is
        # dropped here so it is filled like any missing one, instead of failing the step
        # three times (his PC, 2026-10-10: "file_write error: OutsideWorkspace").
        try:
            from aletheia import workspace
            workspace.resolve(str(args["path"]))
        except Exception:  # noqa: BLE001 - refused, or no workspace: either way not this path
            args.pop("path")
    words_of_task = " ".join(str(x) for x in (task.get("detail") or task.get("title"),) if x).strip()
    if not task.get("detail") and task.get("does") and task.get("title"):
        # The title alone searched for the wrong thing: "Compare a shortlist of warm ... places"
        # read pages about grammar. What it does says what it is about.
        words_of_task = (f"{task['title']}: " + "; ".join(str(n) for n in task["does"] if str(n).strip()))
    missing = []
    for key in schema.get("required") or []:
        if key in args and str(args[key]).strip():
            continue
        prop = props.get(key) or {}
        types = prop.get("type")
        stringy = types == "string" or (isinstance(types, list) and "string" in types)
        who = str((task.get("then_wait") or {}).get("who") or "").strip()
        if key in PERSON_ARGS and stringy and "enum" not in prop and who:
            args[key] = who[:200]
        elif key in TOPIC_ARGS and stringy and "enum" not in prop and words_of_task:
            args[key] = words_of_task[:480]
        elif key == "id" and stringy and "enum" not in prop and words_of_task and mints_id(tool):
            args[key] = new_id(words_of_task)
        else:
            missing.append(key)
    return args, missing


#: Spoken windows `calendar_reasoning.window` understands, in the order a task's words are tried.
WINDOW_WORDS = ("this weekend", "next week", "this week", "tomorrow", "today", "next two weeks")
#: What a READ over a stretch of days looks at when the task names none: enough to see a pattern.
DEFAULT_WINDOW = "next two weeks"
#: The arguments that carry what a new file SAYS; a tool with one of them and a path creates.
CONTENT_ARGS = ("text", "content", "what", "body")


def default_args(tool, task: dict, missing: list[str]) -> dict:
    """Values that need no one's judgement, for arguments nobody supplied: the window a
    READ looks over, and where a NEW file in her own workspace goes. Each is safe because
    of what the tool is - looking changes nothing, and a file of hers is hers to undo -
    so a wrong default costs a re-read or a rename, never something he would have refused.
    Everything else stays missing, which is a question for him."""
    words_of_task = " ".join(str(x) for x in (task.get("title"), task.get("detail"),
                                             " ".join(task.get("does") or [])) if x).lower()
    props = (tool.input_schema or {}).get("properties") or {}
    required = set((tool.input_schema or {}).get("required") or [])
    out: dict = {}
    for key in missing:
        prop = props.get(key) or {}
        if "enum" in prop:
            continue
        if key == "when" and tool.read_only:
            out[key] = next((w for w in WINDOW_WORDS if w in words_of_task), DEFAULT_WINDOW)
        elif (key == "path" and tool.writes and set(tool.writes) <= {"workspace"} and not tool.destructive
              and not tool.open_world and required & set(CONTENT_ARGS)):
            out[key] = f"missions/{new_id(str(task.get('title') or 'notes'))}.md"
    return out


ARGS_SYSTEM = """You fill in the arguments for ONE tool call that carries out one task of a
long-running mission for Caleb. Use only facts present in the task text and the known values.
Never invent a person, an address, a date or a number that is not written there: leave an
argument out when the text does not say it. found_by_earlier_steps is what earlier steps of the
mission read; a value written there counts as written. Reply with JSON {"args": {...}} only."""


def model_args(tool, task: dict, args: dict, missing: list[str], *, think=None,
               found: list[str] | None = None) -> dict:
    """Ask a ROUTINE thinker for the missing arguments. Raises ReasonerUnavailable.

    `found` is what the steps before it read (this task's and the tasks it needs): a hold for
    "the fitting events" takes its start and title from the events a search found, and without
    them the only honest answer was to ask him (2026-10-10)."""
    props = (tool.input_schema or {}).get("properties") or {}
    context = {"tool": tool.name, "description": tool.description[:300],
               "arguments_needed": {k: props.get(k, {}) for k in missing},
               "known": args, "task": {"title": task.get("title"), "detail": task.get("detail")}}
    if found:
        context["found_by_earlier_steps"] = [str(x)[:600] for x in found[-6:]]

    def validate(value: dict) -> dict:
        got = value.get("args") if isinstance(value, dict) else None
        if not isinstance(got, dict):
            raise ValueError("args must be an object")
        # A value outside the argument's own enum is dropped here rather than refused by the
        # handler later: the argument is then still missing, and missing is a question for him.
        return {"args": {k: v for k, v in got.items() if k in missing and str(v).strip()
                         and ("enum" not in (props.get(k) or {}) or v in props[k]["enum"])}}
    if think is None:
        from aletheia import reasoning_gateway
        # Boring work is ROUTINE (her own model first). With no frontier model, though, the routine
        # ceiling (15 s local, 45 s total) is shorter than her own model needs on a CPU, so the
        # standard class carries it: frontier is out anyway, and local gets the time to answer.
        # With findings to read it is not boring work: the standard class reads them first.
        policy = "routine" if reasoning_gateway.frontier_available() and not found else "standard"
        return reasoning_gateway.reason_json(ARGS_SYSTEM, str(task.get("title") or ""), context=context,
                                             policy=policy, validator=validate).output["args"]
    return think(ARGS_SYSTEM, str(task.get("title") or ""), context=context, validator=validate)["args"]
