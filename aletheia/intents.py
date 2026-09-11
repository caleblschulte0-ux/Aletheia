"""Arbitrary asks, made durable and approvable (Playbook §27, §56, §97).

`aletheia.planner` can turn a sentence into a gated plan. This is what
happens to that plan afterwards, and it is the difference between a party
trick and a personal OS: the plan is PERSISTED, it is bound to an approval
by a hash of itself, and the Core executes it later — after the
conversation that produced it has ended, which is where real work lives.

The approval binding is the pattern already ratified for computer control
and for email: the approval carries a sha256 of the exact plan. Approving
authorizes THAT plan and no other. If anything about it changes between
the ask and the approval — a step edited, a capability that went missing,
the registry rewritten — the hash no longer matches and execution is
refused rather than adapted. "Approve" is never a blank cheque on a
sentence Aletheia has since reinterpreted.

Nothing here widens authority. Every step still runs through
`intercom.execute_command` and the gates behind it; halt is re-read before
each one. What this adds is only the ability for the thing being gated to
have come from a sentence instead of from a slot.

Private storage: an intent record contains the operator's own words.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sys
import threading

from aletheia import (asking, cannot, intercom, journal, planner, policy,
                      quick, routing, speech, stateio)
from aletheia.fleet import load_fleet

ACTOR = "aletheia-intent"
# Read once at import so `spoken` never pays a webtask import to answer.
try:
    from aletheia.webtask import SPENDING_REFUSAL as _SPENDING_REFUSAL
except Exception:      # webtask is optional-heavy; the rule is not
    _SPENDING_REFUSAL = ("That asks me to spend money, and I do not do that — "
                         "not with an approval, not with a confirmation.")
PROPOSED, RUNNING, EXECUTED, RETIRED, FAILED, INTERRUPTED = (
    "PROPOSED", "RUNNING", "EXECUTED", "RETIRED", "FAILED", "INTERRUPTED")
_RUN_LOCK = threading.Lock()


def intents_dir():
    return stateio.private_dir("intents")


def plan_hash(plan: planner.Plan) -> str:
    """A fingerprint of exactly what would run.

    Only the executable steps, in order, with their full arguments. The
    summary is prose and may be reworded without changing what happens;
    the commands are the thing being authorized.
    """
    material = [{"n": s.n, "command": s.command} for s in plan.executable]
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record_path(intent_id: str):
    return intents_dir() / f"{stateio.safe_id(intent_id, name='intent id')}.json"


def load(intent_id: str) -> dict:
    return stateio.read_json(_record_path(intent_id))


def all_intents(state: str | None = None) -> list[dict]:
    """Every intent on disk, parsed once per change, optionally filtered."""
    directory = intents_dir()
    if not directory.is_dir():
        return []
    rows = stateio.parsed_dir(directory)
    if state is None:
        return rows
    return [r for r in rows if r.get("state") == state]


def read_only(plan: planner.Plan) -> bool:
    """Does this plan only look at things?

    Found in real use: the room mic hears a half-sentence, the planner
    turns it into "report current operational status", and that files a
    durable intent AND an operator_always approval. Eight of them
    accumulated in a day — "acknowledge operator's remark; no action
    required" sitting in his queue waiting to be authorised.

    A plan that only reads is answered on the spot. Approvals are for
    things that change the world; spending his attention on anything else
    is what teaches him to stop reading the queue.
    """
    steps = plan.executable
    return bool(steps) and all(
        s.command["kind"] in intercom.READ_ONLY_KINDS for s in steps)


def _say_the_plan(plan) -> None:
    """One sentence about what is about to happen. Never raises.

    Only when there is something to say: a plan with no executable steps
    is about to be answered in the next breath, and narrating that would
    be two sentences where one does. Ids are stripped because this is
    read out loud in a room.
    """
    try:
        from aletheia import followups
        steps = [s for s in getattr(plan, "steps", []) or []]
        if not steps or not getattr(plan, "executable", False):
            return
        summary = speech.strip_ids(str(getattr(plan, "summary", "") or "")).strip()
        if not summary:
            return
        followups.report(
            f"Here's the plan: {summary} — "
            f"{speech.count_phrase(len(steps), 'step')}.")
    except Exception:
        pass        # narration must never be able to break the work


def _speak_answer(record: dict, request: str) -> dict:
    """Answer a question out loud, and never raise.

    ONE implementation for both roads to an answer — the short one that
    skips the planner and the long one that came back from it with
    nothing to do. Two copies of this drifted once already in this repo
    (`intents.spoken` and `voice.spoken_reply`), which is how "That
    failed: KeyError: ..." survived on the path nobody had fixed.
    """
    from aletheia import converse
    try:
        # Through the same sieve as everything else she says. `converse`
        # reads her stores, so its answers carry the ids in them: "there
        # are two pending approvals (intent-1b32747ddb, intent-a3d2ad3434)"
        # — read out loud, in a room. §145. And it writes for a screen
        # unless something stops it: "What I *can* do right now is look at
        # your desktop live (computer.observe/control)" was a real answer,
        # with an asterisk pair that is silence out loud and an identifier
        # that is gibberish. `spoken_prose` is all of it in one place.
        answered = converse.answer(request)["answer"]
        # A PROGRAM IS A FILE, NOT A SENTENCE. `unmarkdown` strips ```
        # fence markers, which is right for every other kind of markup and
        # exactly wrong for this one: it does not tidy the code, it
        # PROMOTES it into prose. "Write me a python script that renames
        # files" was answered with sixty lines read out loud — "import os.
        # import argparse. def rename_files(folder, mode, find=None..." —
        # two minutes long, unusable, and gone at the end of it. She has
        # had `file.author` all along and no path from an answer to it.
        from aletheia import codeblocks
        saved = codeblocks.save(answered, asked=request)
        record["spoken"] = speech.spoken_prose(codeblocks.prose_only(answered))
        if saved:
            record["files"] = [row["path"] for row in saved]
            record["spoken"] = (record["spoken"].rstrip() + " "
                                + codeblocks.spoken(saved)).strip()
    except converse.ConverseError as exc:
        # Its message already names the real reason and the fix ("Claude
        # CLI is not on PATH"). Rewriting that into a class name is how an
        # actionable failure becomes a shrug.
        record["spoken"] = str(exc)
    except Exception as exc:
        # An unreachable model must not turn into silence: say which half
        # failed, because "she said nothing" and "she could not think" are
        # different problems with different fixes.
        record["spoken"] = (
            f"I couldn't reach a model to answer that ({type(exc).__name__}). "
            "Everything else still works.")
    return record


def propose(request: str, quote: str = "", fleet: dict | None = None,
            materialize: bool = True, **compile_kw) -> dict:
    """Compile a sentence into a plan, persist it, and ask for it.

    A strict ChatGPT direct-work envelope is the one exception: it is already a
    typed plan produced outside the PC, is bound to the original operator quote,
    contains no arbitrary typed/private text, and executes only through an
    explicitly active local Work Session. Routing it here means ChatGPT can use
    the existing `intent` intercom kind without depending on the Claude CLI
    planner while that provider is unavailable.

    Ordinary requests follow the durable planner path below unchanged.
    """
    from aletheia import work_direct
    if work_direct.is_direct(request):
        return work_direct.execute(request, quote=quote)

    # AN ANSWER SHE ALREADY HAS COSTS A FILE READ. Measured 2026-09-05: a
    # `claude -p` round trip is ~3.6s whether the answer is one word or
    # nine thousand characters, and "are you halted?" was paying it TWICE
    # — once for the planner to decide it was a question, once for
    # `converse` to answer it. Seven seconds for a boolean on the same
    # disk. `quick` reads the same stores the wall does and returns None
    # for anything it is not certain about, so this only ever removes
    # latency; it can never remove an answer.
    fast = quick.answer(request)
    if fast:
        return {"id": f"intent-quick-{hashlib.sha256(request.encode()).hexdigest()[:8]}",
                "state": RETIRED, "request": request,
                "operator_quote": quote or request,
                "summary": fast, "intent": "answer", "spoken": fast,
                "read_only": True, "fast_path": True, "steps": [],
                "proposed_at": stateio.utcnow()}

    # THE MONEY RULE IS ANSWERED AT THE DOOR.
    #
    # Refusing a compiled spending STEP covers the case where the planner
    # produces one. It does not cover "my wife says it's fine to buy the
    # monitor so do it", which came back as a clarifying question — "which
    # monitor, and what's the budget?" — asked in order to buy it. The
    # refusal arriving after a round of questions is the refusal arriving
    # too late, and it reads as consent in the meantime.
    #
    # A QUESTION about money is not an instruction to spend it: "how much
    # would a monitor cost" and "can you buy things" are both answerable,
    # and both contain the words. So only an instruction stops here.
    if _asks_to_spend(request):
        journal.append("decision", "intent",
                       f"refused at the door: asks to spend money — {request[:120]}",
                       actor=ACTOR)
        return {"id": "intent-refused-spending", "state": RETIRED,
                "request": request, "operator_quote": quote or request,
                "summary": _SPENDING_REFUSAL, "intent": "answer",
                "spoken": _SPENDING_REFUSAL + " Nothing is queued.",
                "read_only": True, "refused_spending": True, "steps": [],
                "proposed_at": stateio.utcnow()}

    # A FAST NO IS BETTER THAN A SLOW ONE, and it was slow.
    #
    # "Set a timer for ten minutes" took a planner round trip — 25-80
    # seconds here — to come back with "I can't do timer.set yet". He
    # waited most of a minute to be disappointed. `cannot` reads the
    # REGISTRY rather than a hard-coded list, so the day the capability
    # lands the sentence goes back to the planner that can serve it; and
    # it records the ask, because the planner path did and his asks must
    # not stop being counted just because the answer got faster.
    #
    # AFTER `quick`, so anything she can actually answer is answered.
    refusal = cannot.answer(request)
    if refusal:
        return {"id": f"intent-cannot-{hashlib.sha256(request.encode()).hexdigest()[:8]}",
                "state": RETIRED, "request": request,
                "operator_quote": quote or request,
                "summary": refusal, "intent": "answer", "spoken": refusal,
                "read_only": True, "fast_path": True, "steps": [],
                "proposed_at": stateio.utcnow()}

    # A QUESTION THAT NEEDS NO PLAN DOES NOT NEED A PLANNER.
    #
    # "What's the capital of Iceland" was compiled by a fifteen-kilobyte
    # grammar prompt — 25-80 seconds on this machine — which concluded it
    # was a question and produced no steps, and then `converse` ran to
    # answer it anyway. The expensive call existed only to classify, which
    # is the same round trip `quick` was written to remove one layer down.
    #
    # `asking` decides deterministically and is biased toward the planner:
    # a question misread as a job costs him seconds, a JOB misread as a
    # question costs him the work not happening. So this only fires on
    # sentences that open like a question, name no doing-verb, and do not
    # mention her or his own stores.
    # ...and neither does a request whose whole product IS the answer.
    # "Write me an email to Brant" is one round trip pretending to be a
    # project: `routing.answerable_directly` is True for writing,
    # rewriting, summarising and plain questions, and False the moment
    # anything DELIVERS - so "write and send Brant an email" still
    # compiles a plan and still passes the gates on the way out.
    if asking.is_a_plain_question(request) or routing.answerable_directly(request):
        record = {"id": f"intent-asked-{hashlib.sha256(request.encode()).hexdigest()[:8]}",
                  "state": RETIRED, "request": request,
                  "operator_quote": quote or request,
                  "summary": request[:200], "intent": "answer",
                  "read_only": True, "asked_directly": True, "steps": [],
                  "proposed_at": stateio.utcnow()}
        _speak_answer(record, request)
        journal.append("event", "intent",
                       f"answered without planning: {request[:120]}", actor=ACTOR)
        return record

    fleet = fleet if fleet is not None else load_fleet()
    plan = planner.compile(request, fleet=fleet, **compile_kw)
    presses = _bind_committing_presses(plan, fleet)
    # SAY THE PLAN THE MOMENT IT EXISTS. His shape for a long request is
    # "I know that she's working on it fast, and then I'll hear the plan
    # fast, and then the results, they'll come when they come." Between
    # the acknowledgement and the results there was silence — minutes of
    # it — with a compiled plan sitting unmentioned. Outside a followup
    # this is a no-op, so nothing changes for a direct caller.
    _say_the_plan(plan)
    digest = plan_hash(plan)
    intent_id = f"intent-{digest[:10]}"
    approval_id = intent_id

    # What he asked for and could not have, counted in his own words. A gap
    # named on Tuesday and the same gap on Friday were indistinguishable:
    # `materialize_gaps` files a build task the first time and then quietly
    # does nothing, so a capability asked for eleven times and one mentioned
    # once looked identical on the task list forever.
    try:
        from aletheia import demand
        demand.record_plan(plan, request)
    except Exception:
        pass

    gap_tasks: list[str] = []
    if materialize:
        try:
            gap_tasks = planner.materialize_gaps(plan)
        except Exception as exc:
            journal.append("event", "intent",
                           f"could not materialize gaps: {type(exc).__name__}: {exc}",
                           actor=ACTOR)

    record = {
        "id": intent_id,
        "state": PROPOSED,
        "request": request,
        "operator_quote": quote or request,
        "summary": plan.summary,
        "intent": plan.intent,
        "plan_sha256": digest,
        "approval": approval_id,
        "provider": plan.provider,
        "degraded": plan.degraded,
        "steps": [{"n": s.n, "status": s.status, "detail": s.detail,
                   "command": s.command, "capability": s.capability}
                  for s in plan.steps],
        "gap_tasks": gap_tasks,
        "proposed_at": stateio.utcnow(),
    }
    if presses:
        record["presses"] = presses
    if read_only(plan):
        receipts = planner.execute(plan, fleet=fleet, quote=quote or request)
        record["state"] = EXECUTED
        record["receipts"] = receipts
        record["read_only"] = True
        # An EVENT, not an action. `planner.execute` already journals what
        # the steps did, so this was a second line for the same act — and
        # answering a question on the spot is talking, which "what did you
        # do today" should not list. It read: "Did it: Check how many
        # unread emails he has; answered on the spot (read-only): Check how
        # many unread emails he has".
        journal.append("event", "intent",
                       f"answered on the spot: {plan.summary[:120]}",
                       actor=ACTOR)
        return record
    if not plan.executable and plan.intent in ("answer", "clarify"):
        # HE ASKED A QUESTION. Until 2026-09-03 this retired the record and
        # spoken() fell through to plan.summary — a one-line restatement of
        # what he had just said. She was an executor with no mouth: ask her
        # anything a person asks an assistant and she handed back a gist.
        # A question now gets a real answer, from the same subscription
        # everything else runs on. Nothing is executed here.
        record["state"] = RETIRED
        record["read_only"] = True
        if plan.intent == "clarify":
            # A clarifying question is ALREADY the right thing to say. Sending
            # it through converse turned "Which sister — Ana or Mia?" into a
            # paragraph about ambiguity, which is worse in every way. Only a
            # question he asked gets answered here.
            return record
        _speak_answer(record, request)
        return record
    # NOTHING IS QUEUED FOR A PLAN THAT ASKS TO SPEND. `spoken()` already
    # answers with the refusal, but without this an approval object was
    # still created and left pending — a thing he could walk past later
    # and say "approve" to, for the ask she had just refused out loud.
    if any(s.status == planner.REFUSED
           and str(s.detail or "").startswith(_SPENDING_REFUSAL)
           for s in plan.steps):
        record["state"] = RETIRED
        record["refused_spending"] = True
        journal.append("decision", "intent",
                       f"refused: asks to spend money — {request[:120]}",
                       actor=ACTOR)
        return record
    # A PLAN WHOSE HANDS WERE REFUSED IS NOT "N STEPS READY".
    #
    # 2026-09-11, the TikTok review take: the sixteen clicks were refused and
    # the approval on his phone still offered the other five steps — open
    # Edge, start recording, stop recording, report — which is a video of
    # nothing under the summary of the video he asked for. The steps around
    # the hands only mean something if the hands run.
    hands = next((s for s in plan.steps if s.status == planner.REFUSED
                  and (s.command or {}).get("kind") in _HANDS_KINDS), None)
    if hands is not None:
        record["state"] = RETIRED
        record["refused_hands"] = {"n": hands.n, "kind": hands.command["kind"],
                                   "detail": str(hands.detail or "")[:400]}
        journal.append("decision", "intent",
                       f"refused: step {hands.n} ({hands.command['kind']}) cannot run "
                       f"as planned, so nothing is queued — {request[:120]}",
                       actor=ACTOR)
        return record

    stateio.write_json_atomic(_record_path(intent_id), record)

    if plan.executable and not read_only(plan):
        kinds = [s.command["kind"] for s in plan.executable]
        tier = intercom.plan_tier(kinds)
        record["tier"] = tier
        capability = ("intent.execute.routine" if tier == intercom.TIER_ROUTINE
                      else "intent.execute")
        # He is approving a PRESS, so the approval names it where he reads it.
        labels = [label for bound in presses for label in bound["presses"]]
        approval = policy.request(
            approval_id,
            requested_action=f"run {len(plan.executable)} step(s): " + ", ".join(kinds)
            + (f"; presses {', '.join(repr(l) for l in labels)} on the screen" if labels else ""),
            reason=f'operator said: "{(quote or request)[:200]}"',
            consequence=(plan.summary or "see the plan") + (
                f" — it will press {speech.and_list(labels)} on your screen, once, "
                "as part of this exact plan" if labels else ""),
            reversible=tier == intercom.TIER_ROUTINE and not labels, capability=capability)
        record["approval_state"] = approval.get("state")
    # SAYABLE. This line is read back out of her journal by "what did you
    # do today", and "1 executable, 0 blocked" is a log entry, not a
    # sentence - the same defect as the "1 file(s) read" line the suite
    # already caught once. The counts stay; the English is fixed.
    planned = speech.count_phrase(len(plan.executable), "step")
    held = f", {len(plan.blocked)} blocked" if plan.blocked else ""
    journal.append("plan", "intent",
                   f"{intent_id}: planned {planned}{held} — "
                   f"{plan.summary or request[:120]}",
                   actor=ACTOR)
    return record


# The kinds that are a plan's hands: when one is refused, what is left is not
# a smaller version of the ask.
_HANDS_KINDS = frozenset({"computer_do", "screen_record"})


def _bind_committing_presses(plan: planner.Plan, fleet: dict) -> list[dict]:
    """Offer a desktop step refused ONLY for its committing presses as part
    of the plan he approves, naming each press.

    The grammar gate refuses a computer_do that presses Post, Send or
    Delete, because unattended hands never press those, and that stays
    true: a step converted here runs only inside `computer.approved_presses`,
    which `_run_approved` enters after HIS approval of this exact plan hash,
    and each press is read again on screen before it is made. Every other
    refusal (a shell, a close, an unlabelled control, a bad field) stays
    refused.
    """
    from aletheia import computer
    bound: list[dict] = []
    for i, step in enumerate(plan.steps):
        command = step.command or {}
        if step.status != planner.REFUSED or command.get("kind") != "computer_do":
            continue
        steps = intercom._steps_of(command)
        if not isinstance(steps, list) or computer.validate_steps(steps):
            continue
        try:
            presses = computer.committing_presses(steps)
        except computer.ApprovalRequired:
            continue
        if not presses:
            continue
        try:
            computer.check_act_plan(steps)
            continue
        except computer.ApprovalRequired as exc:
            committing = f"computer_do: {exc}"
        # Nothing else about the step may be wrong: the committing press has
        # to be the grammar gate's ONLY objection.
        if intercom.validate_kind_args(command, fleet) != [committing]:
            continue
        labels = [p["label"] for p in presses]
        plan.steps[i] = planner.PlannedStep(
            step.n, planner.EXECUTABLE,
            "presses " + ", ".join(repr(l) for l in labels)
            + " — only inside his approval of this exact plan",
            command=step.command, capability=step.capability)
        bound.append({"n": step.n, "presses": labels})
    return bound


def _hands_refused(hands: dict) -> str:
    """Why a plan was not offered, in words he can act on."""
    why = re.sub(r"^\w+:\s*", "", str(hands.get("detail") or ""))
    why = re.split(r" — |; allowed:", why)[0]
    why = speech.tidy(speech.strip_ids(speech.spoken_prose(why)))[:220].rstrip(" .;")
    return ("I can't run that plan as written"
            + (f": step {hands.get('n')} was refused — {why}." if why else ".")
            + " Nothing is queued; tell me what to change and I'll plan it again.")


def spoken(record: dict) -> str:
    """What Thea says back. Short, honest about what is and is not happening."""
    # A real answer, when the ask was a QUESTION, beats every summary below.
    # Narrow on purpose: `clarify` and the degraded no-provider case keep
    # their own wording, which is already the right thing to say.
    if record.get("intent") == "answer" and record.get("spoken"):
        return str(record["spoken"])
    if record.get("direct_work"):
        return speech.spoken_prose(
            str(record.get("spoken") or record.get("summary")
                or "Work action completed."))[:600]

    # `.get`, not `[...]`: this function is the last thing between a
    # record and the room, and a KeyError here is silence where a sentence
    # should be.
    steps = record.get("steps") or []
    runnable = [s for s in steps if s.get("status") == planner.EXECUTABLE]
    gaps_named = [s for s in steps if s.get("status") == planner.GAP]
    manual = [s for s in steps if s.get("status") == planner.MANUAL]
    refused = [s for s in steps if s.get("status") == planner.REFUSED]
    if record.get("degraded") and not runnable:
        return f"I could not plan that: {record['degraded'][:160]}"
    if record.get("intent") == "clarify":
        # Through the sieve like everything else she says. A clarifying
        # question is model prose about her own state, so it carries the
        # ids in it: "the only open item I see is a pending approval
        # (intent-7aed1b5dcd) waiting on you". §145.
        asked = speech.spoken_prose(str(record.get("summary") or ""))
        return asked or "I need one thing cleared up before I plan that."
    if record.get("read_only"):
        receipts = record.get("receipts") or []
        answers = [str(r.get("detail", "")).strip() for r in receipts
                   if r.get("outcome") == "done" and str(r.get("detail", "")).strip()]
        # A FAILURE IS NOT AN ANSWER, AND THE SUMMARY IS NOT ONE EITHER.
        #
        # This filtered failures out — correctly, an error is not an answer
        # — and then fell back to `record["summary"]`, which is the
        # planner's restatement of what he ASKED for. So "read my resume"
        # came back "Read the operator's resume file" while the receipt
        # said `WorkspaceError: resume is not a file`, and "how many jobs
        # are open at Anthropic" came back "Find how many jobs are
        # currently open at Anthropic" while research had found nothing.
        #
        # Both sound like answers. Both are the question, reflected. That
        # is §30 in its worst shape: not "command executed" reported as
        # "goal achieved", but a FAILURE reported as the goal, in the
        # confident voice of having done it.
        trouble = [_plainly(r) for r in receipts
                   if r.get("outcome") not in ("done", None) and r.get("detail")]
        if answers and not trouble:
            return speech.spoken_prose(" ".join(answers))[:600]
        if answers:
            # The answers are finished sentences; ". — but" is two marks.
            return (" ".join(answers)[:480].rstrip(" .") + " — but "
                    + speech.and_list(trouble)[:200].rstrip(" .") + ".")
        if trouble:
            # The reasons are finished sentences; ". ." is two marks.
            return ("I couldn't: "
                    + speech.and_list(trouble)[:500].rstrip(" .") + ".")
        return "I did that, and it produced nothing to tell you."
    # A PLAN THAT WAS PARTLY REFUSED FOR SPENDING IS REFUSED.
    #
    # "Buy the cheapest 4K monitor and use my saved card" compiled into a
    # step that was refused for spending AND a step that was not, so she
    # said: "1 step ready — Find cheapest 4K monitor and buy using saved
    # card. Say approve to run it. That asks me to spend money, and I do
    # not do that." One sentence offering and refusing the same thing.
    #
    # Running the rest is not a smaller version of what he asked for; it
    # is a different thing, offered under the summary of the thing that
    # was refused. So the refusal is the answer.
    money = [s for s in refused
             if str(s.get("detail", "")).startswith(_SPENDING_REFUSAL)]
    if money:
        return _SPENDING_REFUSAL + " Nothing is queued."
    if record.get("refused_hands"):
        return _hands_refused(record["refused_hands"])

    parts = []
    if runnable:
        # THE SUMMARY, not the kinds. An executable step carries no
        # capability id (only gaps do), so naming the steps could only
        # ever read back the intercom vocabulary — "1 step ready —
        # task_new". The planner's own summary is the plain sentence for
        # what is about to happen, which is what somebody deciding
        # whether to say "approve" actually needs.
        #
        # And no approval id: §145, he approves by saying "approve", and
        # a hex string read out loud is a handle he cannot hold in his
        # head — while the sentence went on to tell him to say it back.
        ready = speech.count_phrase(len(runnable), "step") + " ready"
        summary = speech.spoken_prose(str(record.get("summary") or ""))
        said = f"{ready} — {summary}." if summary else f"{ready}."
        labels = [label for bound in record.get("presses") or []
                  for label in bound.get("presses") or []]
        if labels:
            # He is approving a press, so the sentence names it. The approval
            # is not a licence: it covers this exact plan, once.
            said += (f" It will press {speech.and_list(labels[:4])} on your screen, "
                     "and only as part of this exact plan.")
        if record.get("approval_state") == "APPROVED":
            # A standing grant already covered it, so there is nothing for
            # him to approve — and "say approve to run it" would send him
            # looking for a decision that has already been made.
            parts.append(said + " Your standing authority covers it, so it "
                                "runs on the next beat.")
        else:
            # ...but voice may approve only the ROUTINE tier (2026-09-03:
            # the room microphone is an input device, not an authentication
            # device). Telling him to "say approve" for a desktop or
            # world-touching plan sent him into a refusal, so the sentence
            # names the surface that can actually take the decision.
            # Only override when the tier is KNOWN and is not routine. An
            # absent tier is not evidence of a dangerous one, and treating
            # it as one took "say approve" away from every caller that
            # does not set it.
            tier = record.get("tier")
            how = ("Approve it on your phone or at the keyboard to run it."
                   if tier and tier != intercom.TIER_ROUTINE
                   else "Say approve to run it.")
            parts.append(said + " " + how + _why_it_asks(record))
    if gaps_named:
        parts.append(_cannot_yet(gaps_named, record))
    if manual:
        parts.append(f"{speech.count_phrase(len(manual), 'step')} only you can do.")
    if refused:
        # A refusal is worth SAYING only when it is about him. "I do not
        # spend money" is the whole answer; "claimed missing, but the
        # registry has audio.route AVAILABLE — claim ignored" is the
        # planner correcting the model, and he heard it, capability id and
        # all, appended to "1 step ready — Play music."
        his = [speech.tidy(speech.strip_ids(str(s.get("detail") or "")))
               for s in refused
               if str(s.get("detail", "")).startswith(_HIS_REFUSALS)]
        if his:
            parts.append(speech.and_list(his[:2]))
        elif not parts:
            # Nothing else to say, so the dropped step IS the answer —
            # but in his words, not the validator's.
            parts.append("I couldn't make sense of part of that — say it again?")
    return " ".join(parts) or "Nothing to do."


# A question ABOUT money is not an instruction to spend it.
_A_QUESTION = re.compile(
    r"^\s*(?:how|what|which|who|when|where|why|is|are|was|were|do|does|did|"
    r"can|could|should|would|will|have|has|am|tell me|show me)\b", re.I)


def _asks_to_spend(request: str) -> bool:
    """Is this an instruction that commits his money? Never raises."""
    text = " ".join(str(request or "").split())
    if not text or text.rstrip().endswith("?") or _A_QUESTION.match(text):
        return False
    try:
        from aletheia import webtask
        return webtask.would_spend(text)
    except Exception:
        # FAIL CLOSED. The only realistic failure here is webtask being
        # unimportable, and if that is true then nothing can spend anyway
        # — so refusing costs him nothing and guessing the other way is
        # the one mistake this rule exists to prevent.
        return True


# Refusal details written FOR HIM. Everything else in that field is the
# planner talking to itself about a model's bad step, and belongs in the
# record rather than in the room.
_HIS_REFUSALS = (_SPENDING_REFUSAL[:40],
                 "halt is not a step", "resume is not a step",
                 "approve is not a step", "deny is not a step")


def _why_it_asks(record: dict) -> str:
    """"Why are you asking me about THAT?" — answered, with the fix.

    "Add a task to renew my registration" runs instantly, because
    `voice.py` has a pattern for it and a direct command is ungated.
    "Mark the registration one done" asks for approval, because it went
    through the planner and the planner path gates the routine tier. Same
    action, same risk, and the only difference is whether somebody had
    written a regex for that phrasing.

    The gate is not the thing to change — `aletheia.standing` exists
    precisely so he can say yes once for the whole routine tier, and it
    is deliberately not grantable by voice, because the room microphone
    is unauthenticated. What was missing is that nothing ever told him
    the command existed at the moment he was being asked.

    Self-limiting: once the grant exists, `policy.request` consumes it and
    no approval is created, so this line stops appearing.
    """
    if record.get("tier") != intercom.TIER_ROUTINE:
        return ""
    # NEVER NEXT TO A DELETION. "2 steps ready — Delete all files in your
    # workspace. Say approve to run it. I ask about small local things
    # like this until you run `standing on` once." Each delete keeps a
    # version, so the tier is right — but offering to stop asking, in the
    # same breath as bulk deletion, reads as "shall I make this
    # automatic?" and that is not a thing to suggest at that moment.
    # `.get("command", {})` is not enough: a GAP or MANUAL step carries
    # the key with the value None, and `None.get` is an AttributeError in
    # the middle of a sentence.
    kinds = {str((s.get("command") or {}).get("kind") or "")
             for s in record.get("steps", [])}
    if kinds & DESTRUCTIVE_KINDS:
        return ""
    try:
        from aletheia import authority
        if authority.active_grants():
            return ""
    except Exception:
        pass
    if not _due_to_mention("standing", NUDGE_EVERY_S):
        return ""
    # No backticks. This is spoken, and a backtick is either silence or
    # the word "backtick"; the command is still exact without them.
    return (" I ask about small local things like this until you run "
            "python -m aletheia.standing on, once.")


# How often a standing nudge may be repeated. It is one sentence and the
# fix is one command, but three replies in a row carrying it — read out
# loud, in a room — is the thing that teaches him to stop listening.
NUDGE_EVERY_S = 3600.0

# Routine-tier kinds that remove or move something. Reversible, and still
# not the moment to suggest doing it without being asked.
DESTRUCTIVE_KINDS = frozenset({"file_delete", "file_move", "notify_clear",
                               "plan_set", "task_status"})


def _due_to_mention(what: str, every_s: float) -> bool:
    """Has it been long enough to say this again? Never raises.

    A failure to READ the marker says yes (better to repeat useful advice
    than to lose it); a failure to WRITE it just means it may repeat.
    """
    import time
    try:
        path = stateio.private_dir("nudges") / f"{stateio.safe_id(what)}.json"
        now = time.time()
        try:
            last = float(stateio.read_json(path).get("at", 0.0))
        except Exception:
            last = 0.0
        if now - last < every_s:
            return False
        stateio.write_json_atomic(path, {"at": now})
        return True
    except Exception:
        return True


def _plainly(receipt: dict) -> str:
    """One failed step, as a reason rather than a traceback.

    `speech.plainly` is the implementation, shared with
    `voice.spoken_reply` — both say these out loud, and they had drifted
    into stripping differently, so "That failed: KeyError: \"no place
    matches 'the airport'\"" came out of one path while the other had
    already been fixed.
    """
    return speech.plainly(receipt.get("detail", ""))[:220] or "it didn't work"


def _in_english(capability: str | None) -> str:
    """What a capability IS, in the registry's own words.

    She was saying "I can't do room.scene yet" and "1 step ready —
    free_time" out loud. Those are identifiers: correct, unsayable, and
    §145 is explicit that implementation details never reach speech
    unless they are useful to him. The registry already carries a human
    sentence for every capability; this is that sentence.
    """
    from aletheia import speech
    name = str(capability or "").strip()
    try:
        # ONE implementation: `speech.say_capabilities` needs exactly this
        # to render an id a model wrote into prose, and two copies of "the
        # registry's own words" drift the moment one of them is fixed.
        said = speech._capability_english(name) if name else ""
        if said:
            return said
    except Exception:
        pass
    return speech.deslug(name) or "that"


def _cannot_yet(gaps_named: list[dict], record: dict) -> str:
    """"Not yet" — and the one thing that would change it.

    A capability waiting on HIM (a hub to connect, an account to link) and
    one that does not exist yet are completely different answers, and both
    used to come out as the same sentence with an identifier in the middle
    of it: "I can't do room.scene yet; filed 1 build task(s)."

    The two paths are phrased separately on purpose. A capability with a
    setup step is one command away, and that command is the whole answer;
    one without a step has only the registry's description, which is a
    noun phrase and reads correctly after "I can't".
    """
    from aletheia import speech
    wanted = [s.get("capability") for s in gaps_named]
    step = _setup_step(wanted)
    if step is not None:
        # Deliberately NOT the step's `why`. That field is written for the
        # checklist screen and talks about her in the third person —
        # "without it SHE cannot answer 'am I free'" — which is a strange
        # thing to hear her say about herself, and long. He just asked for
        # the thing, so he knows what it is; the command is the part he
        # can act on.
        command = _how_command(step)
        prereq = _setup_prereq(step)
        said = "Not yet — that one needs setting up first"
        if command and prereq:
            return f"{said}. {prereq} Then: {command}."
        if command:
            return f"{said}: {command}."
        return f"{said}."
    said = "I can't " + speech.and_list([_in_english(c) for c in wanted]) + " yet"
    if record.get("gap_tasks"):
        return f"{said}. I've put it on the build list."
    return f"{said}."


def _setup_step(capabilities_wanted: list):
    """The setup checklist entry for the first gap that has one, or None."""
    try:
        from aletheia import setup
        wanted = {str(c) for c in capabilities_wanted if c}
        for step in setup.steps():
            if step.capability in wanted:
                return step
    except Exception:
        pass
    return None


def _how_command(step) -> str:
    """The runnable line out of a step's instructions.

    The instructions are a block written for a screen — "Only if you
    already run Home Assistant:", an indented menu path, then the command.
    Reading the first line out loud gives him a fragment ending in a
    colon; the command is the part he can act on.
    """
    try:
        for line in step.instructions():
            text = " ".join(str(line).split()).lstrip("$ ")
            if not text.startswith("python -m"):
                continue
            # The checklist is written for a screen, so a command often
            # carries an aside: "python -m aletheia.phone_cli ready
            # (should say True)". Read out, that is the command plus a
            # sentence fragment. The runnable part is what he needs.
            return re.sub(r"\s*\(.*$", "", text).strip()
    except Exception:
        pass
    return ""


_COMMAND_WORDS = frozenset({"python", "pip", "winget", "npm", "npx", "git",
                            "curl", "choco", "docker", "node", "ollama", "$"})


def _setup_prereq(step) -> str:
    """The thing HE has to go and fetch, in English — or "".

    A command with a placeholder in it does not answer its own question.
    "what's on my calendar this week" came back as `python -m aletheia.apply
    calendar "<paste the URL>"` and nothing else: that says what to type and
    not WHICH URL, and the line that answers it was sitting directly above
    the command in the checklist all along. Out loud it was worse — a shell
    command and an angle-bracket placeholder, with no hint the thing comes
    out of Google Calendar's settings.

    Headings are skipped: they end in a colon because a screen puts the
    substance underneath them, and read aloud they are a fragment. The
    exception is a CONDITIONAL heading, which is kept and prefixed —
    "Only if you already run Home Assistant:" is the entire difference
    between a five-minute task and installing a home automation platform.
    Arrows become commas for the same reason — nobody hears "dash greater
    than".
    """
    condition = ""
    try:
        for line in step.instructions():
            text = " ".join(str(line).split()).lstrip("$ ")
            if not text or text.split()[0].lower().rstrip(":") in _COMMAND_WORDS:
                continue
            # A line that opens with "(" is an aside belonging to the command
            # above it — "(then ask her anything — this step proves it by
            # asking)" is not an instruction he can start from.
            if text.endswith(":"):
                # A heading is a fragment on its own — except a CONDITIONAL
                # one, which is the most important thing in the block.
                # "Only if you already run Home Assistant:" is the whole
                # difference between a five-minute task and installing a
                # home automation platform, and dropping it left her
                # cheerfully reciting a menu path he has no menu for.
                if text.lower().startswith("only if"):
                    condition = text
                continue
            if text.startswith("(") or len(text.split()) < 4:
                continue
            text = (condition + " " + text) if condition else text
            text = text.replace("->", ",").replace("  ", " ")
            text = " ".join(text.replace(" ,", ",").split())
            return text if text.endswith(".") else text + "."
    except Exception:
        pass
    return ""


def run_approved(fleet: dict | None = None, executor=None) -> list[dict]:
    """Execute every PROPOSED intent whose approval is APPROVED.

    Called from the Core's runtime tick. Each step is durably claimed before it
    runs and receipted immediately afterwards. A run abandoned by a crash is
    recovered from durable terminal receipts when possible. Otherwise it is
    marked INTERRUPTED and never replayed automatically.
    """
    # The periodic Core beat and an immediate HTTP kick can overlap in the
    # same process. Serializing claims prevents one beat from mistaking the
    # other's live RUNNING record for an abandoned process.
    with _RUN_LOCK:
        return _run_approved(fleet, executor)


def _run_approved(fleet: dict | None = None, executor=None) -> list[dict]:
    fleet = fleet if fleet is not None else load_fleet()
    done: list[dict] = []
    for record in all_intents(state=RUNNING):
        receipts = record.get("receipts") or []
        runnable = [s["n"] for s in record.get("steps", [])
                    if s.get("status") == planner.EXECUTABLE]
        receipt_steps = [item.get("n") for item in receipts]
        if (runnable and receipt_steps == runnable
                and all(item.get("outcome") == "done" for item in receipts)):
            record["state"] = EXECUTED
            record["executed_at"] = stateio.utcnow()
            record["recovered_at"] = record["executed_at"]
            detail = "all step receipts were durable; finalized after restart"
        elif receipts and receipts[-1].get("outcome") in ("failed", "halted"):
            record["state"] = FAILED
            record["failed_at"] = stateio.utcnow()
            record["recovered_at"] = record["failed_at"]
            detail = "terminal step receipt was durable; finalized after restart"
        else:
            record["state"] = INTERRUPTED
            record["interrupted_at"] = stateio.utcnow()
            if record.get("current_step") is not None:
                record["interrupted_reason"] = (
                    "execution stopped after the current step was claimed; its "
                    "outcome is unknown; automatic replay is refused")
            else:
                record["interrupted_reason"] = (
                    "execution stopped before the full plan completed; durable "
                    "receipts were preserved; automatic continuation is refused")
            detail = record["interrupted_reason"]
        stateio.write_json_atomic(_record_path(record["id"]), record)
        journal.append("alert" if record["state"] == INTERRUPTED else "event",
                       "intent", f"{record['id']}: {detail}", actor=ACTOR)
        done.append({"intent": record["id"], "outcome": record["state"],
                     "detail": detail})
    for record in all_intents(state=PROPOSED):
        approval_id = record.get("approval")
        if not approval_id:
            continue
        try:
            approval = policy.load(approval_id)
        except (OSError, json.JSONDecodeError, KeyError):
            continue
        if approval.get("state") == "DENIED":
            record["state"] = RETIRED
            record["retired_at"] = stateio.utcnow()
            stateio.write_json_atomic(_record_path(record["id"]), record)
            journal.append("decision", "intent",
                           f"{record['id']} denied — retired", actor=ACTOR)
            done.append({"intent": record["id"], "outcome": "denied"})
            continue
        if approval.get("state") != "APPROVED":
            continue

        runnable = [s for s in record["steps"] if s["status"] == planner.EXECUTABLE]
        material = [{"n": s["n"], "command": s["command"]} for s in runnable]
        digest = hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()
        if digest != record.get("plan_sha256"):
            record["state"] = FAILED
            record["failed_reason"] = ("the plan changed after it was approved — "
                                       "refusing to run something else")
            stateio.write_json_atomic(_record_path(record["id"]), record)
            journal.append("alert", "intent",
                           f"{record['id']}: plan hash mismatch — refused", actor=ACTOR)
            done.append({"intent": record["id"], "outcome": "refused",
                         "detail": record["failed_reason"]})
            continue

        plan = planner.Plan(
            request=record["request"], summary=record.get("summary", ""),
            intent=record.get("intent", "plan"),
            steps=[planner.PlannedStep(s["n"], s["status"], s["detail"],
                                       s.get("command"), s.get("capability"))
                   for s in record["steps"]])
        record["state"] = RUNNING
        record["started_at"] = stateio.utcnow()
        record["receipts"] = []
        stateio.write_json_atomic(_record_path(record["id"]), record)

        def before_step(step, receipts):
            record["current_step"] = step.n
            record["current_kind"] = step.command["kind"]
            record["receipts"] = list(receipts)
            stateio.write_json_atomic(_record_path(record["id"]), record)

        def after_step(step, receipt, receipts):
            record["receipts"] = list(receipts)
            record["completed_steps"] = sum(
                1 for item in receipts if item.get("outcome") == "done")
            record.pop("current_step", None)
            record.pop("current_kind", None)
            stateio.write_json_atomic(_record_path(record["id"]), record)

        bound = {b.get("n") for b in record.get("presses") or []}
        pressing = contextlib.nullcontext()
        if bound:
            # The committing presses HE approved, in this plan's own steps
            # only: computer.act may make each once, reading the label on
            # screen first.
            from aletheia import computer
            pressing = computer.approved_presses(approval_id, [
                intercom._steps_of(s["command"]) for s in runnable
                if s["n"] in bound and (s.get("command") or {}).get("kind") == "computer_do"])
        with pressing:
            receipts = planner.execute(plan, fleet=fleet,
                                       quote=record.get("operator_quote", ""),
                                       executor=executor, before_step=before_step,
                                       after_step=after_step)
        record["receipts"] = receipts
        record["state"] = (FAILED if any(
            r["outcome"] != "done" for r in receipts) else EXECUTED)
        record["finished_at"] = stateio.utcnow()
        if record["state"] == EXECUTED:
            record["executed_at"] = record["finished_at"]
        stateio.write_json_atomic(_record_path(record["id"]), record)
        done.append({"intent": record["id"], "outcome": record["state"],
                     "receipts": receipts})
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Durable arbitrary asks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new", help="propose a plan from a sentence")
    p_new.add_argument("request")
    p_new.add_argument("--quote", default="")
    p_list = sub.add_parser("list")
    p_list.add_argument("--state", choices=[
        PROPOSED, RUNNING, EXECUTED, RETIRED, FAILED, INTERRUPTED])
    p_show = sub.add_parser("show")
    p_show.add_argument("id")
    sub.add_parser("run", help="execute every approved intent")
    args = ap.parse_args(argv)

    if args.cmd == "new":
        record = propose(args.request, quote=args.quote)
        print(spoken(record))
        return 0
    if args.cmd == "list":
        rows = all_intents(state=args.state)
        for record in rows:
            print(f"{record['id']}  {record['state']:9}  {record.get('summary', '')[:70]}")
        print(f"{len(rows)} intent(s)", file=sys.stderr)
        return 0
    if args.cmd == "show":
        print(json.dumps(load(args.id), indent=2))
        return 0
    for result in run_approved():
        print(f"{result['intent']}: {result['outcome']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
