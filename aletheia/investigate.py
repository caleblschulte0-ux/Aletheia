"""Questions about her own work are LOOKED INTO, with her tools, in the live path.

`AgentSession` (a tool loop whose model never owns authority) answered the
brief's first two milestones from its CLI and from nowhere else: everything
he actually said went core -> intents -> quick / converse / planner, and
`converse` answers from a hand-built context. That is fine for "what's the
capital of Iceland" and exactly wrong for "why didn't the Palantir one
send", whose answer is in a record, a journal line and a boundary name that
no fixed context carries.

So this is the route. A QUESTION about her work - status, why, what went
wrong, what she is doing, what she needs - about ANY of it (an application,
a project, a task, a browser goal, her own code) goes to a session, which
reads whatever it needs and answers with how it knows. Jobs are the test
case here, not the architecture: nothing below names an employer, a board
or a project.

THE ORDER IN `intents.propose` IS THE SAFETY ARGUMENT:

1. `quick` first. "What are you doing" is a file read and stays one.
2. The spending door. An instruction that commits money is refused before
   anything, and the session's own door refuses it again.
3. Then this, and only for QUESTIONS. An instruction ("retry the Palantir
   one", "look into why it failed") stays on the planner, because a
   session only reads and would answer an order with a report.

It may only ever ADD an answer. A session that produced nothing usable
(a model that could not speak the protocol, a step cap, a loop) hands the
sentence back to the old path, so routing a question here can never leave
him with less than he had.

Negative and failure-shaped phrasings are written in the same sitting as the
positive ones (CLAUDE.md: "The question she is asked in the negative reaches
nothing"): "why didn't", "what hasn't sent", "is anything stuck", "did it go
through", "what's not working".
"""
from __future__ import annotations

import hashlib
import re
from typing import Callable

ACTOR = "aletheia-investigate"

#: The live path's session is shorter than the CLI's: he is waiting in a room.
LIVE_STEPS = 5
#: After this long the model is told to answer from what it has. A spoken
#: follow-up is collected for ~105 s; subscriptions answer well inside that.
LIVE_BUDGET_S = 80.0
#: The last call after the budget still needs time to answer.
DEADLINE_GRACE_S = 15.0

# ---- which sentences -------------------------------------------------------

#: How a question opens. Anchored on the sentence after filler is stripped.
#: Deliberately NOT "can you check / look into / find out": those are
#: instructions, and instructions stay on the planner.
_QUESTION = re.compile(
    r"^(?:why|what|whats|what's|how|hows|how's|where|wheres|where's|which|who|when|"
    r"is|isn't|isnt|are|aren't|arent|was|wasn't|wasnt|were|did|didn't|didnt|does|do|"
    r"has|hasn't|hasnt|have|haven't|havent|had|will|won't|wont|"
    r"any|anything|something|nothing|"
    r"tell me|explain|do you know|"
    r"(?:can|could|would) (?:you|u) (?:tell me|explain|let me know))\b")

#: A suggestion phrased as a question is an instruction: "why don't you retry it".
_SUGGESTION = re.compile(r"^why (?:don'?t|do not|not) (?:you|u|we)\b|^how about\b|^what if (?:you|we)\b")

#: Talk about the conversation itself, which the session cannot see and
#: `converse` (which carries the thread) can: "why did you say that".
_ABOUT_THE_TALK = re.compile(
    r"\b(?:say|said|saying|mean|meant|means|think|thought|feel|like|call me|joke|"
    r"sound|sounds|repeat|word|words)\b")

#: Something that goes wrong.
_FAILURE = re.compile(
    r"\b(?:fail\w*|wrong|broke|broken|break\w*|stuck|block\w*|stall\w*|errors?|"
    r"crash\w*|problems?|issues?|stopp?ed|hung|hangs?|hanging|timed out|time ?out|"
    r"gave up|give up|skipp?\w*|reject\w*|refus\w*|denied|held up|holding up|"
    r"not (?:working|sending|going|done|finished|sent|running|moving|happening|submitted)|"
    r"didn'?t|did not|doesn'?t|does not|hasn'?t|has not|haven'?t|have not|wasn'?t|was not|"
    r"weren'?t|were not|won'?t|will not|can'?t|cannot|couldn'?t|could not|isn'?t|aren'?t)\b")

#: A state of hers that is only a question after "why": "why are you halted"
#: is looked into, "are you halted" is a yes or no `quick` already holds.
_HER_STATE = re.compile(r"\b(?:halted|paused|offline|so slow|idle|asleep|quiet|down)\b")

#: What she can do is the registry's question, carried by `converse` with the
#: capability block - "what can't you do" must never lose it to a session.
_ABOUT_ABILITY = re.compile(
    r"^what (?:can'?t|cannot|can not|can|could|couldn'?t) (?:you|u) (?:do|handle|help with)\b"
    r"|^what (?:are|r) (?:you|u) (?:not )?(?:able|unable|allowed) to\b"
    r"|^what (?:don'?t|do not) (?:you|u) (?:do|know how to)\b")

#: Where something stands.
_STATUS = re.compile(
    r"\b(?:status|progress|update|updates|latest|going|coming along|getting on|"
    r"how far|so far|yet|go through|gone through|went through|go out|went out|"
    r"send|sends|sending|sent|submit\w*|appl(?:y|ied|ies|ication|ications)|finish\w*|"
    r"done|complete\w*|working on|doing|happen\w*|left to do|next step|"
    r"mov(?:e|ed|ing)|progressed|start(?:ed)?|ship(?:ped)?|merged?|landed|posted|uploaded|"
    r"published|repl(?:y|ied)|heard back)\b")

#: The work itself, whatever it is about. `the <x> one` is how he names a
#: record he cannot name ("the Palantir one").
_WORK = re.compile(
    r"\b(?:applications?|apps?|jobs?|job hunt|hunt|campaign|forms?|employers?|"
    r"tasks?|projects?|plans?|charters?|missions?|goals?|steps?|errands?|stud(?:y|ies)|experiments?|"
    r"reminders?|approvals?|handoffs?|requests?|runs?|loop|sessions?|"
    r"browser|pages?|sites?|captcha|account|"
    r"emails? you|mail you|messages? you|"
    r"builds?|pull requests?|prs?|commits?|branch|tests?|code|repo|repository|"
    r"sync|core|index|model|workers?|queue|"
    r"the [\w.&'-]+(?: [\w.&'-]+)? one)\b")

#: "What's not working", "what's stuck": a subject-less question about her.
_WHAT_IS_WRONG = re.compile(
    r"^(?:what|which)(?:'s| is|s| are|'re)? (?:still |currently )?(?:not )?"
    r"(?:working|broken|failing|failed|wrong|stuck|blocked|down|erroring|hanging)(?: right now| now| today)?$"
    r"|^what(?:'s| has|s)? (?:not |never )?(?:sent|gone through|gone out)(?: yet| today)?$"
    r"|^what (?:hasn'?t|didn'?t|did not|has not|won'?t) (?:sent|send|go through|gone through|work|worked|finish\w*|run)"
    r"(?: yet| today)?$")

#: "What went wrong today": a failure on a day is a failure in her day.
_HER_DAY = re.compile(r"\b(?:today|yesterday|tonight|last night|this morning|this afternoon|overnight)\b")

#: Her, as the one doing the work.
_HER = re.compile(r"\b(?:you|u|your|yourself|thea|aletheia|she)\b")

#: "Anything stuck", "is something wrong": a question about everything she runs.
_ANY = re.compile(r"\b(?:anything|something|everything|nothing)\b")

#: What she is doing and what she needs, in any of his ways of asking.
_DOING_OR_NEEDS = re.compile(
    r"\bwhat (?:are|r|were) (?:you|u) (?:doing|working on|up to|busy with|stuck on|waiting (?:on|for))\b"
    # "what did you get done": her work sessions' receipts answer it (work.receipts)
    r"|\bwhat (?:did|have|has) (?:you|u) (?:get|got|gotten) done\b"
    r"|\bwhat (?:did|have) (?:you|u) (?:finish(?:ed)?|accomplish(?:ed)?)\b"
    r"|\bneed(?:s)? (?:from|of) me\b|\bneed me to\b|\bwaiting (?:on|for) me\b|\bneeds? me\b"
    r"|\bwhat(?:'s| is|s) (?:blocking|holding up|stopping) (?:you|u|it|the)\b")

#: "What did you do without asking me." The question his continuity brief made
#: askable: since she may now do reversible local work unattended, he is owed a
#: straight answer about what that was, from the receipts rather than from a
#: model's memory of the turn. Written with its negatives and its synonyms in
#: the same sitting (CLAUDE.md: "The question she is asked in the negative
#: reaches nothing") - without asking, without telling, without my say-so, on
#: your own, by yourself, unattended, behind my back.
_WITHOUT_ASKING = re.compile(
    r"\bwithout (?:asking|telling|checking with|clearing (?:it )?with|my say|my say-so|"
    r"my approval|my permission|me knowing|letting me know)\b"
    r"|\b(?:on your own|by yourself|off your own back|unattended|autonomously|"
    r"behind my back)\b"
    r"|\bdid(?:n'?t| not)? (?:you )?(?:ask|check with) me\b")

#: "How is Barkly going", "where are we with the promo video", "any update on X".
_HOW_IS_X_GOING = re.compile(
    r"^(?:how(?:'s| is|s| are)|how(?:'re)) (?:the |my |our |your )?(?P<x>[\w .&'-]{2,40}?) "
    r"(?:going|coming along|coming|progressing|getting on|looking)(?: so far| today| now)?$"
    r"|^where (?:are|is|'re) (?:you|u|we|things|it) (?:at )?(?:with|on) (?P<x2>.{2,60})$"
    r"|^(?:any|what(?:'s| is|s) the) (?:progress|update|news|status|latest) (?:on|with|of|for) (?P<x3>.{2,60})$"
    r"|^what(?:'s| is|s) (?:happening|going on) with (?P<x4>.{2,60})$"
    r"|^what happened (?:to|with) (?P<x5>.{2,60})$")

#: Subjects of "how is X going" that are small talk, not work.
_SMALL_TALK = re.compile(
    r"^(?:it|things|life|you|u|everything|the day|your day|my day|today|the weather|"
    r"day|week|weekend|morning|afternoon|evening|night|family|mom|dad|weather|work)$")


def _tidy(text: str) -> str:
    said = " ".join(str(text or "").split()).strip()
    said = said.rstrip("?.! ").casefold().replace("’", "'")
    try:
        from aletheia.voice import _without_preamble, strip_wake_word
        said = _without_preamble(strip_wake_word(said).casefold())
    except Exception:
        pass
    return re.sub(r"^(?:please|so|ok|okay|hey|um|uh|and|but)\s+", "", said).strip()


def wants_session(text: str) -> bool:
    """Is this a QUESTION about her work that needs looking into? Never raises.

    Decides on the sentence's shape AND its subject: a question about the
    world ("why is the sky blue", "why do planes crash") names none of her
    work and stays with `converse`; an instruction stays with the planner.
    """
    try:
        said = _tidy(text)
    except Exception:
        return False
    if not said or len(said.split()) > 40:
        return False
    if not (_QUESTION.match(said) or str(text or "").rstrip().endswith("?")):
        return False
    if _SUGGESTION.match(said) or _ABOUT_ABILITY.match(said):
        return False
    # "Did you send it", "why didn't that work": a pronoun names something
    # said a moment ago, and the thread lives with `converse`, not here.
    if _ABOUT_THE_TALK.search(said) and not _WORK.search(said):
        return False
    if _DOING_OR_NEEDS.search(said) or _WHAT_IS_WRONG.match(said):
        return True
    # "What did you do without asking me" names her and names the thing; the
    # ledger holds the answer and no fixed context carries it.
    if _WITHOUT_ASKING.search(said) and (_HER.search(said) or _ANY.search(said)):
        return True
    going = _HOW_IS_X_GOING.match(said)
    if going:
        subject = next((going.group(k) for k in ("x", "x2", "x3", "x4", "x5") if going.group(k)), "")
        subject = re.sub(r"^(?:the|my|our|your) ", "", subject.strip())
        if not subject or _SMALL_TALK.match(subject):
            return False
        if going.group("x4") or going.group("x5"):
            # "what happened with the election" is the world's news; "what
            # happened with the Stripe application" is hers.
            return bool(_WORK.search(said) or _HER.search(said))
        return True
    work = bool(_WORK.search(said))
    hers = bool(_HER.search(said))
    anything = bool(_ANY.search(said))
    if said.startswith("why"):
        # "why is the sky blue" names nothing of hers; "why can't you finish
        # the Palantir application" and "why didn't the Stripe one send" do.
        failing, standing = bool(_FAILURE.search(said)), bool(_STATUS.search(said))
        return (work or ((hers or anything) and (failing or standing or bool(_HER_STATE.search(said))))
                or (failing and standing and not re.search(r"\b(?:it|that|this)\b", said)))
    if _FAILURE.search(said):
        if not work and re.match(r"^(?:are|r|were|is) (?:you|u)(?: \w+){1,2}$", said):
            return False          # "are you stopped": a yes or no, `quick`'s
        return work or hers or anything or bool(_HER_DAY.search(said))
    if _STATUS.search(said):
        return work or (hers and anything)
    return False


# ---- what she says while she looks -----------------------------------------

#: A tool, in the words a room can hear. Anything not named here is "my records".
_LOOKING_AT = {
    "state.now": "what I'm doing right now",
    "work.receipts": "what my work session did",
    "autonomy.unattended": "what I did without asking you",
    "work.inventory": "the work on record",
    "mission.status": "your missions",
    "study.status": "your studies",
    "study.evidence": "what the study read",
    "mission.waiting": "what your missions are waiting on",
    "missions": "your missions",
    "applications.query": "the application records",
    "applications": "the application records",
    "journal.query": "my journal",
    "memory.recall": "my history",
    "self.diagnose": "the record of what went wrong",
    "browser.missions": "my browser work",
    "projects": "your projects",
    "tasks": "your task list",
    "reminders": "your reminders",
    "running": "which parts of me are running",
    "agents": "my workers",
    "recall": "what I remember",
    "notify_check": "your notifications",
    "watches": "what I'm watching for",
    "contacts": "your contacts",
    "jobs": "the job boards",
}


def looking_at(tool: str) -> str:
    name = str(tool or "")
    if name.startswith("repo."):
        return "my own code"
    return _LOOKING_AT.get(name, "my records")


def _narrator(report: Callable[[str], object]) -> Callable[[str, dict], None]:
    said: set[str] = set()

    def on_step(tool: str, _args: dict) -> None:
        words = looking_at(tool)
        if words in said:
            return
        said.add(words)
        try:
            report(f"Looking at {words}.")
        except Exception:
            pass
    return on_step


def _report(line: str) -> None:
    try:
        from aletheia import followups
        followups.report(line)
    except Exception:
        pass


# ---- the answer ------------------------------------------------------------

def _own_model_lead() -> str:
    try:
        from aletheia import reasoner
        return reasoner.own_model_lead()
    except Exception:
        return "This answer is mine: slower, and simpler. "


def spoken_answer(result) -> str:
    """What the room hears for a session that answered. Through the one door
    for model prose, with the disclosure first when her own model wrote it."""
    from aletheia import reasoner, speech
    said = speech.spoken_prose(str(result.answer or "")).strip()
    if not said:
        return ""
    if reasoner.provider_kind(result.model) == "local":
        said = _own_model_lead() + said
    return said


def _unavailable_words() -> str:
    """Nobody could think, IN WORDS, from the state rather than the log line.

    The first talk run read the note out: "(neither Claude nor the ChatGPT
    browser could answer just now; and my own model is switched off receipts:
    C:\\Users\\...\\agent-sessions\\.json)" - a status line and a file path, in
    a room. The note stays in the session record, where it belongs.
    """
    try:
        from aletheia import local_model_pool, model_pool_config, reasoner
        cloud = reasoner.big_models_out()
        if not model_pool_config.enabled():
            mine = "my own model is switched off"
        elif not local_model_pool.reachable():
            mine = "my own model isn't running"
        else:
            mine = "my own model couldn't answer either"
        return f"I couldn't look into that just now: {cloud}, and {mine}. Ask me again in a bit."
    except Exception:
        return "I couldn't look into that just now: nobody could think it through. Ask me again in a bit."


def propose(request: str, *, quote: str = "", think=None, report: Callable[[str], object] | None = None,
            max_steps: int = LIVE_STEPS, budget_s: float = LIVE_BUDGET_S) -> dict | None:
    """The intent record for a question looked into with her tools, or None.

    None means "not this route" or "the session produced nothing usable":
    the caller carries on down the old path either way.
    """
    if not wants_session(request):
        return None
    from aletheia import agent_session, converse, journal, stateio
    report = report or _report
    think = think or agent_session.chain_think(on_switch=report, deadline_s=budget_s + DEADLINE_GRACE_S)
    # A QUESTION IS NEVER AN INSTRUCTION. Since C4b a session may do reversible
    # local work without asking (his continuity brief item 10) - and this route
    # exists precisely because the sentence was a question. "Why didn't the
    # Palantir one send" must not end with a task added, however reversible the
    # task is, so THIS route turns unattended work off and anything that writes
    # becomes a handoff exactly as it did before. An instruction goes to the
    # planner, and the work session is where she acts.
    session = agent_session.AgentSession(request, think=think, max_steps=max_steps,
                                         on_step=_narrator(report), budget_s=budget_s,
                                         unattended=False)
    result = session.run()
    outcome = result.outcome
    if outcome in (agent_session.ANSWERED, agent_session.HANDED_OFF, agent_session.REFUSED_AT_DOOR):
        said = spoken_answer(result)
    elif outcome == agent_session.MODEL_UNAVAILABLE and not result.model_calls:
        # Nobody could think from the first call: say so, in words. A model
        # that went away MID-session (a Claude call that hung after four good
        # ones) is more likely a blip, and the old path gets its own try.
        said = _unavailable_words()
    else:
        said = ""
    if not said:
        try:
            journal.append("event", "intent", "looked into a question with my tools and could "
                           "not put an answer together, so answered it the usual way", actor=ACTOR)
        except Exception:
            pass
        return None
    digest = hashlib.sha256(request.encode("utf-8")).hexdigest()[:8]
    record = {"id": f"intent-looked-{digest}", "state": "RETIRED", "request": request,
              "operator_quote": quote or request, "summary": request[:200], "intent": "answer",
              "spoken": said, "read_only": True, "steps": [], "proposed_at": stateio.utcnow(),
              "investigated": {"session": result.id, "outcome": outcome, "model": result.model,
                               "models": list(result.model_providers), "knowing": result.knowing,
                               "handoffs": len(result.handoffs), "duration_s": result.duration_s}}
    if outcome == agent_session.REFUSED_AT_DOOR:
        record["refused_spending"] = True
    # THE EXCHANGE IS REMEMBERED HERE, not only by the voice door: the typed
    # door records nothing of its own, and "why that one?" a turn later has
    # to find this. Deduped against the last turn, so the voice door's own
    # call cannot double it.
    converse.remember_exchange(request, said)
    try:
        journal.append("event", "intent", "looked into a question with my tools "
                       f"({len(result.receipts)} lookups)", actor=ACTOR)
    except Exception:
        pass
    return record
