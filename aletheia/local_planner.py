"""The planner's local rung: a COMPACT prompt her own model can actually finish.

Measured on his laptop, 2026-09-18, with `ALETHEIA_FRONTIER_OFF=1` and the
real models (qwen3:8b, 8 CPU threads of which `local_brain` gives inference
two, Ollama's loaded context window 4096 tokens):

    prompt        cold        warm
    2.0 KB        162 s        33 s
    4.0 KB          -         113 s
    28.7 KB    the whole planner prompt: timed out at 180 s through the
               door and again at 300 s, the per-call ceiling, so a bigger
               budget is not the fix

28.7 KB is about 7,200 tokens. The window it is loaded into holds 4,096, so
the front of the prompt — the part that says what the output must look like —
never reached the model at all. The grammar is 18.2 KB of it: 117 kinds, every
one of them, on every ask. The frontier model reads that in one gulp; her own
model cannot, and the acceptance pass recorded the result — with the frontier
out, "go to books.toscrape.com and tell me the title of the first book in the
travel category" reached nothing, while "work on my projects" worked only
because it is one of the deterministic phrases in `voice`.

So this module shows her own model the FEW kinds this sentence could plausibly
mean, and nothing else:

    shortlist()       deterministic, from the descriptors (`aletheia.tools`):
                      word overlap with the kind's name, its description and
                      its spoken group, plus a small hand-kept table of the
                      obvious verbs. No model decides what a model is shown.
    compact_prompt()  those kinds with their argument schemas and one example
                      each, inside a byte budget the hardware can meet.
    compile()         one call, validated through the SAME gates as every
                      other plan, retried once with the error, then honest.

WHAT THIS MAY NOT DO. It is a smaller PROMPT, never a smaller gate. Every step
it compiles goes through `planner._classify`: `intercom.PLANNER_FORBIDDEN`,
`planner.SPENDING_KINDS`, `intercom.validate_kind_args`, the tiers, the
containers, the approvals. The shortlist itself can only ever REMOVE kinds
from what the model may name, and it is built from `planner_visible`
descriptors, so a forbidden verb is not in the catalog it is shown and is
refused again if it arrives anyway. The spending door is asked BEFORE the
model is, because a refusal that arrives after a round trip arrives too late.

And it is a FALLBACK. `planner.compile` asks the frontier first whenever a
frontier model could answer; this runs when none can. A plan it compiled says
so, in the record and out loud, because an answer he trusts as Claude's and is
not is the failure he cannot detect.
"""
from __future__ import annotations

import re

from aletheia import intercom, localtime, tools

#: The local prompt may not exceed this. Measured, not guessed: 4 KB is
#: ~1,000 tokens, which fits the 4,096-token window Ollama loads qwen3:8b
#: into with room for the sentence, the context and the answer — and it
#: came back in 113 s warm. 8 KB and up is where the curve leaves the room.
BUDGET_BYTES = 4_096
#: The prompt's share of it. The rest is the context, which the model reads in
#: the same breath: `situational.snapshot()` is 2.4 KB on an empty machine and
#: up to 8 KB on his, so a 2.8 KB prompt with the whole snapshot behind it is
#: an 11 KB ask wearing a 3 KB label. A budget that counts only half of what
#: travels is not a budget.
PROMPT_BUDGET_BYTES = 3_000
CONTEXT_BUDGET_BYTES = BUDGET_BYTES - PROMPT_BUDGET_BYTES
#: The snapshot's keys, most useful to a PLANNER first. `now` is dropped
#: outright: the prompt already carries his local time and the offset, and the
#: snapshot spends 1.6 KB saying it again.
CONTEXT_KEYS = ("trust_boundary", "recent_conversation", "operator",
                "recent_references", "calendar_next", "room")
#: How many kinds a local model is shown. More is not more accurate: every
#: one of them is read on every ask, and the 4 KB run that named seven kinds
#: chose the right one while the 2 KB run that named twenty-six did not.
SHORTLIST_MAX = 7
#: One-step plans are the common case. A short chain is allowed when the
#: sentence plainly has two parts; anything longer is refused whole and
#: retried once, because a local model padding a plan is a local model
#: guessing.
MAX_STEPS = 3
#: Marker on a plan compiled here. `intents` reads it; so does the receipt.
COMPILED_BY = "my own model"
#: Set on a plan that RULES compiled, with no model at all (aletheia.rule_planner).
COMPILED_BY_RULES = "rules, with no model"

# ---- shortlisting ---------------------------------------------------------
#
# Hand-kept, like `tools.SPOKEN_GROUPS_BY_NAME` and for the same reason: a
# mechanical mapping from an English verb to a kind would have to guess, and a
# wrong guess reads fluently while sending the ask to the wrong verb. Every
# kind named here is checked against the live grammar by
# `tests/test_local_planner.py`, so this cannot drift into naming something
# that does not exist or something the planner may not emit.
VERB_HINTS: dict[str, tuple[str, ...]] = {
    r"\bremind\b|\breminder\b": ("remind_at", "remind_daily", "remind_weekly"),
    r"\bevery day\b|\bdaily\b": ("remind_daily",),
    r"\bevery (?:mon|tues|wednes|thurs|fri|satur|sun)day\b|\bweekly\b": ("remind_weekly",),
    r"\btask\b|\bto-?do\b": ("task_new", "tasks"),
    r"\bremember\b|\bdon'?t forget\b|\bnote that\b": ("remember", "note"),
    r"\bwhat do you know\b|\brecall\b|\bwhat did i tell you\b": ("recall",),
    r"\bgo to\b|\bwebsite\b|\bweb ?site\b|\bon the web\b|\bsign up\b|\bfill (?:in|out)\b": ("web_task",),
    r"https?://|\bwww\.|\b[a-z0-9-]+\.(?:com|org|net|io|co\.uk|gov|edu)\b": ("web_task", "browse_read"),
    r"\blook up\b|\bresearch\b|\bfind out\b|\bwhat'?s the (?:weather|price|score)\b": ("research",),
    r"\bsearch\b|\bsearch for\b": ("research", "web_task"),
    r"\bemail\b|\be-?mail\b": ("email_draft", "email_check", "email_read"),
    r"\btext\b|\bmessage\b": ("message_send", "thread_draft"),
    r"\bwrite\b|\bdraft\b|\bcompose\b|\bwrite up\b": ("compose", "file_write", "doc_make"),
    r"\bsave\b|\bput it in a file\b|\bwrite it to\b": ("file_write", "compose"),
    r"\bspreadsheet\b|\bword doc\b|\bdocument\b|\bpowerpoint\b|\bslide": ("doc_make",),
    r"\bread\b.*\bfile\b|\bopen the file\b|\bwhat'?s in\b": ("file_read", "file_find"),
    r"\bfind\b.*\bfile\b|\bwhere is\b.*\.(?:pdf|docx?|txt|md|json)\b": ("file_find",),
    r"\bcalendar\b|\bam i free\b|\bbook (?:a|the) (?:slot|time)\b|\bschedule\b": (
        "free_time", "calendar_hold", "calendar_find_free"),
    r"\bmeet\b|\bmeeting\b": ("meet", "free_time"),
    r"\bshopping list\b|\badd .* to the list\b": ("shopping_add", "shopping_list"),
    r"\bplay\b.*\bmusic\b|\bput on\b.*\bmusic\b": ("music",),
    r"\bjobs?\b|\bappl(?:y|ication)\b": ("jobs", "apply_prepare", "applications"),
    r"\bproject\b|\brepo\b|\brepositor": ("projects", "work_projects", "project_new"),
    r"\bwork on my projects\b": ("work_projects",),
    r"\bplan\b\s*\b(?:for|to)\b|\bnew plan\b": ("plan_new", "plan_add_step"),
    r"\bcontact\b|\bphone number\b|\bwho is\b": ("contacts", "contact_add"),
    r"\btell me\b|\blet me know\b|\bnotify me\b": ("notify_operator",),
    r"\bsubscription": ("subscriptions", "money"),
    r"\bhow (?:much|long)\b.*\bdrive\b|\bhow far\b": ("travel_time",),
    r"\btrim\b|\bconvert\b|\bcaption": ("media_trim", "media_convert", "media_captions"),
}

#: When nothing matches, these are what an arbitrary ask most often is. Not a
#: guess about HIS sentence — a floor, so the model is never shown an empty
#: catalog and forced to invent one.
FALLBACK_KINDS = ("web_task", "research", "task_new", "notify_operator")

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""a an and are as at be by can could do does for from get go
has have how i if in is it its me my of on or please so tell that the their them
then there they this to up us was what when where which who will with would you
your""".split())


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").lower())
            if len(w) > 2 and w not in _STOP}


def _kind_words(tool: "tools.Tool") -> tuple[set[str], set[str], set[str]]:
    """The three word bags a descriptor offers: its name, its group, its text."""
    name = set(_WORD.findall(tool.name))
    group = _words(tools.group_of(tool.name))
    described = _words(tool.description)
    return name, group, described


def _candidates(catalog: dict[str, "tools.Tool"]) -> list["tools.Tool"]:
    """Only kinds the planner may emit at all. A forbidden verb is not a
    low-ranked candidate; it is not a candidate."""
    return [t for t in catalog.values()
            if t.kind is not None and t.planner_visible
            and t.kind not in intercom.PLANNER_FORBIDDEN]


def score(request: str, tool: "tools.Tool", hinted: dict[str, int]) -> int:
    """How plausible this kind is for this sentence. Deterministic."""
    asked = _words(request)
    if not asked:
        return 0
    name, group, described = _kind_words(tool)
    points = hinted.get(tool.name, 0)
    points += 4 * len(asked & name)
    points += 2 * len(asked & group)
    points += min(3, len(asked & described))
    return points


def _hints(request: str) -> dict[str, int]:
    """The obvious verbs, weighted by how specific the pattern is."""
    text = " ".join(str(request or "").lower().split())
    found: dict[str, int] = {}
    for pattern, kinds in VERB_HINTS.items():
        if re.search(pattern, text):
            for i, kind in enumerate(kinds):
                found[kind] = max(found.get(kind, 0), 12 - i * 2)
    return found


def shortlist(request: str, *, catalog: dict[str, "tools.Tool"] | None = None,
              limit: int = SHORTLIST_MAX) -> list[str]:
    """The few kinds this sentence could plausibly mean, best first.

    Deterministic and bounded. It can only ever REMOVE kinds from what the
    model is shown, which is why it cannot widen authority: the catalog it
    draws from is already filtered to what the planner may emit.
    """
    catalog = catalog if catalog is not None else tools.catalog()
    hinted = _hints(request)
    ranked = []
    for tool in _candidates(catalog):
        points = score(request, tool, hinted)
        if points > 0:
            ranked.append((points, tool.name))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    chosen = [name for _, name in ranked[:max(1, int(limit))]]
    for name in FALLBACK_KINDS:
        if len(chosen) >= max(1, int(limit)):
            break
        if name in catalog and name not in chosen and catalog[name].planner_visible:
            chosen.append(name)
    return chosen


# ---- the compact prompt ---------------------------------------------------

HEADER = """You are the planning half of Aletheia, running on her own model on \
his laptop. Turn what he said into ONE JSON object and nothing else.

  {"intent":"plan","summary":"<one short line>","steps":[<step>],"confidence":0.0-1.0}

A step is {"kind":"<a kind below>","<arg>":"<value>"}. The literal key "kind" \
always carries the kind name.
If the right response is WORDS - a question, a fact, an opinion, a draft - \
return {"intent":"answer","summary":"<his question in one line>","steps":[]}.
If the instruction is genuinely ambiguous, return \
{"intent":"clarify","summary":"<the one question>"}.

Rules:
- Use ONLY the kinds below. Never invent a kind or an argument name.
- ONE step. Two only if the sentence plainly has two parts. Never more than %(max)d.
- Anything a person could do with a browser and a mouse is web_task; leave out \
url if you do not know it.
- Times are ISO-8601 with an offset, resolved in his local time.
- The summary is read out loud to him: say what you are about to do for him, \
no identifiers, no third person.
""" % {"max": MAX_STEPS}

#: Realistic values for the arguments a shortlisted kind usually needs, so the
#: one example per kind is an example and not a row of angle brackets.
EXAMPLE_VALUES = {
    "at": "2026-09-19T08:00:00-05:00", "time": "2026-09-19T08:00:00-05:00",
    "when": "2026-09-19T08:00:00-05:00", "date": "2026-09-19",
    "text": "call the bank", "title": "call the bank",
    "description": "call the bank", "request": "call the bank",
    "goal": "find the price of the blue kettle", "url": "https://example.com",
    "query": "tide times at Sandymouth", "topic": "tide times at Sandymouth",
    "path": "notes/summary.md", "name": "summary.md", "file": "notes/summary.md",
    "content": "the text to write", "body": "the text to write",
    "id": "abc123", "who": "Brant", "to": "Brant", "subject": "next week",
    "item": "milk", "day": "2026-09-19", "minutes": "30", "hour": "8",
}


def _example_value(kind: str, arg: str) -> str:
    allowed = intercom.allowed_values(kind, arg)
    if allowed:
        return str(allowed[0])
    return EXAMPLE_VALUES.get(arg, "...")


def _example(kind: str) -> str:
    required, _optional = intercom.KIND_ARGS[kind]
    parts = [f'"kind":"{kind}"']
    for arg in sorted(required):
        parts.append(f'"{arg}":"{_example_value(kind, arg)}"')
    return "{" + ",".join(parts) + "}"


def _signature(kind: str) -> str:
    required, optional = intercom.KIND_ARGS[kind]
    args = sorted(required) + [f"[{a}]" for a in sorted(optional)]
    return f"{kind}({', '.join(args)})"


def _description(kind: str, catalog: dict[str, "tools.Tool"], limit: int = 130) -> str:
    tool = catalog.get(kind)
    text = " ".join(str(getattr(tool, "description", "") or "").split())
    if text.startswith(f"The '{kind}' command"):
        # `tools._description_for_kind` falls back to restating the
        # signature when a kind has no note. The signature is on the line
        # above; a second copy costs bytes the budget needs.
        return ""
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "..."
    return text


def _closed_sets(kind: str) -> str:
    """A closed-set argument reads like free text from a name alone, and the
    model fills it in with something reasonable and wrong (`intercom.KIND_ENUMS`)."""
    lines = []
    for arg in sorted(intercom.KIND_ENUMS.get(kind, {})):
        allowed = intercom.allowed_values(kind, arg)
        if allowed:
            lines.append(f"      {arg} is exactly one of: " + ", ".join(allowed))
    return "\n".join(lines)


def kind_block(kind: str, catalog: dict[str, "tools.Tool"]) -> str:
    out = [f"  {_signature(kind)}"]
    described = _description(kind, catalog)
    if described:
        out.append(f"      {described}")
    closed = _closed_sets(kind)
    if closed:
        out.append(closed)
    out.append(f"      e.g. {_example(kind)}")
    return "\n".join(out)


def compact_context(context: dict | None, *, budget: int = CONTEXT_BUDGET_BYTES) -> dict:
    """The snapshot, cut to what a PLANNER needs and to what the budget allows.

    It is still untrusted data and still carries the sentence that says so.
    Dropping a key is honest in a way that truncating its value is not, so the
    keys go in order of usefulness and whatever does not fit is left out with
    `trimmed` saying it was.
    """
    import json
    if not isinstance(context, dict) or not context:
        return {}
    out: dict = {}
    dropped = False
    for key in CONTEXT_KEYS:
        if key not in context:
            continue
        candidate = {**out, key: context[key]}
        try:
            size = len(json.dumps(candidate, default=str).encode("utf-8"))
        except (TypeError, ValueError):
            continue
        if size > budget:
            dropped = True
            continue
        out = candidate
    if dropped or set(context) - set(CONTEXT_KEYS) - {"version", "as_of"}:
        out["trimmed"] = "this is a short view of her state, not all of it"
    return out


def compact_prompt(kinds, *, catalog: dict[str, "tools.Tool"] | None = None,
                   now: str | None = None, budget: int = PROMPT_BUDGET_BYTES) -> str:
    """The whole local system prompt, inside `budget` bytes.

    The budget is a refusal, not a preference: a prompt over it is trimmed by
    dropping the least plausible kind, and the last kind standing keeps its
    block. Never shows the whole catalog — that is the defect this exists for.
    """
    catalog = catalog if catalog is not None else tools.catalog()
    chosen = [k for k in kinds if k in intercom.KIND_ARGS
              and k not in intercom.PLANNER_FORBIDDEN]
    head = HEADER + "\n" + localtime.describe_now(now) + "\n\nKINDS:\n"
    while True:
        body = "\n".join(kind_block(k, catalog) for k in chosen)
        prompt = head + body + "\n"
        if len(prompt.encode("utf-8")) <= budget or len(chosen) <= 1:
            return prompt
        chosen = chosen[:-1]


# ---- one local compile, through the same gates ----------------------------

class LocalPlanUnavailable(RuntimeError):
    """Her own model could not produce a plan (it says why, in English)."""


def _validated(output: dict) -> dict:
    from aletheia import brain
    value = brain.validate_output(output)
    steps = list(value.get("steps") or [])
    if len(steps) > MAX_STEPS:
        raise brain.BrainOutputError(
            f"a plan may have at most {MAX_STEPS} steps; you returned {len(steps)}")
    return value


def _refusal_for_spending(request: str) -> str | None:
    """The one permanent rule, answered BEFORE the model is asked.

    `intents` already holds this door for the voice path, and the compiled
    step is refused again in `planner._classify`. This is the door for every
    OTHER caller of the planner — the CLI, an agenda, a work item — because a
    refusal that arrives after a two-minute local round trip arrives too late
    and reads as consent in the meantime. Fails closed.
    """
    text = " ".join(str(request or "").split())
    if not text or text.rstrip().endswith("?"):
        return None
    try:
        from aletheia import webtask
        return webtask.SPENDING_REFUSAL if webtask.would_spend(text) else None
    except Exception:  # noqa: BLE001
        # FAIL CLOSED, the way `intents._asks_to_spend` does: the only
        # realistic failure is webtask being unimportable, and if that is
        # true then nothing can spend anyway.
        return "I don't spend your money - that is the one permanent rule."


def propose(request: str, *, context: dict | None = None,
            catalog: dict[str, "tools.Tool"] | None = None,
            now: str | None = None, thinker=None) -> tuple[dict, str, list[str]]:
    """One compact local call, retried once with its own error.

    Returns (output, model, shortlisted_kinds). Raises LocalPlanUnavailable
    when her own model cannot be reached or cannot produce a valid shape.
    `thinker(system_prompt, text, context=..., timeout_s=...)` is the seam:
    it defaults to the reasoning gateway's local rung.
    """
    catalog = catalog if catalog is not None else tools.catalog()
    kinds = shortlist(request, catalog=catalog)
    prompt = compact_prompt(kinds, catalog=catalog, now=now)
    context = compact_context(context)
    think = thinker or _local_thinker()
    asked = request
    last = ""
    from aletheia import brain
    for attempt in (1, 2):
        try:
            output, model = think(prompt, asked, context=context)
        except Exception as exc:  # noqa: BLE001 - the pool says why in English
            raise LocalPlanUnavailable(str(exc) or type(exc).__name__) from None
        try:
            return _validated(output), model, kinds
        except brain.BrainOutputError as bad:
            last = str(bad)
            if attempt == 2:
                break
            # Hand the refusal back once and let it repair its own output.
            # The contract is unchanged; the second answer is checked exactly
            # as strictly as the first.
            asked = (f"{request}\n\n--- your previous answer was REJECTED ---\n"
                     f"{last}\nReturn the corrected JSON object only.")
    raise LocalPlanUnavailable(f"her own model did not return a usable plan ({last})")


def _local_thinker():
    """Her own model, fast role first (the one that fits 16 GB), then deep."""
    def think(system_prompt: str, text: str, *, context: dict | None = None):
        from aletheia import local_model_pool, reasoning_gateway
        # The per-call ceiling belongs to the local lane, not to this module:
        # another worker raises it, and a constant copied here would be the
        # copy that disagrees.
        budget = float(reasoning_gateway.LOCAL_MAX_TIMEOUT_S)
        first = None
        for role in ("fast", "deep"):
            try:
                result = reasoning_gateway.local_json(
                    system_prompt, text, context=context or {}, role=role,
                    timeout_s=budget)
                return result.output, result.local_model or result.provider
            except local_model_pool.LocalPoolUnavailable as exc:
                first = first or exc
        raise local_model_pool.LocalPoolUnavailable(str(first))
    return think
