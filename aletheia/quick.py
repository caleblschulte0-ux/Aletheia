"""Answers she already has, given at the speed of a file read.

Measured 2026-09-05 on the operator's own subscription: a `claude -p`
call costs ~3.6 SECONDS whether the answer is one word or nine thousand
characters, because the cost is the round trip and not the thinking. The
CLI binary itself starts in 0.01s, so none of that is his computer.

And every request paid it at least twice. "Are you halted?" went to the
PLANNER to be told it was a question, and then to `converse` to be
answered — seven seconds of silence for a boolean that is sitting in a
file on the same disk.

So: a deterministic first pass. If the sentence is one of the handful
she can answer from her own stores, she answers it now and no model runs
at all.

TWO RULES, and the second one is the important one.

**Every answer comes from a real store.** `presence.snapshot`, the
capability registry, the journal. Never a canned string, never a guess —
the same rule as everywhere else here (§104, §106). If the store is
empty the answer says so.

**When in doubt it says nothing.** Returning None sends the sentence to
the planner, which is slower and much better at ambiguity. A fast wrong
answer is far worse than a slow right one, so the patterns are narrow on
purpose: they match the way a person asks these five things and decline
everything else. It is a shortcut, not a replacement.
"""
from __future__ import annotations

import datetime as dt
import re

MAX_QUESTION = 200


def _tidy(text: str) -> str:
    """Normalise for matching — including the filler nobody means anything by.

    Every pattern here is anchored, so "so what did you do today" and "uh
    are you halted" missed the fast lane entirely and paid a full planner
    round trip. `voice._without_preamble` is the same rule at the other
    door; both use it so the two doors cannot disagree about what counts
    as filler.
    """
    text = " ".join(str(text or "").split()).strip().rstrip("?.! ").casefold()
    try:
        from aletheia.voice import _without_preamble
        return _without_preamble(text)
    except Exception:
        return text


#: What he calls the job hunt. Every status shape below takes one of these
#: as its subject; a subject that is none of them is looked up as a repo
#: name in the pulse, and failing that the question goes to the planner.
_JOB = (r"(?:(?:the |my |our |your )?(?:(?:job |jobs? )?(?:applying|applications?|apps|hunt|search|"
        r"application run|hunting)|jobs|job stuff|job thing|"
        r"applying (?:to|for) (?:jobs|work|places|companies)|"
        r"sending (?:out )?applications))")
_JOB_RE = re.compile(_JOB)
_STATUS = re.compile(
    # how's it going
    r"^(?:how(?:'s| is|s| are) (?:it |things |everything )?(?:going |coming along |looking )?"
    r"(?:with |on |for )?(?P<going>" + _JOB + r")(?: going| coming along| doing| looking| been going)?"
    r"|(?:(?:give me|can i get|i want|i need|send me) )?(?:a |an |the |my )?(?:quick |short |little )?"
    r"(?:status |progress )?(?:update|status|report|rundown|summary)(?: on| about| for| of)?"
    r"(?: how)? (?P<going2>" + _JOB + r")(?: (?:is|are) going| (?:is|are) doing)?"
    r"|what(?:'s| is|s)? (?:the )?(?:status|progress|latest|news|word)(?: on| of| with| about)? "
    r"(?P<going3>" + _JOB + r")"
    r"|where (?:are we|are you|is it|am i|do we stand|do things stand) (?:with|on|at with) "
    r"(?P<going4>" + _JOB + r")"
    r"|any (?:progress|update|news|luck|movement)(?: on| with| in| from)? (?P<going5>" + _JOB + r")"
    r"|how (?:did|have|has) (?P<going6>" + _JOB + r") (?:go|gone|been)(?: today| so far)?)$"
    # still running
    r"|^(?:(?:are|r) (?:you|u|we) still (?P<still>applying|applying (?:to|for) jobs|"
    r"sending (?:out )?applications|working on (?:the )?jobs|on (?:the )?" + _JOB + r"|"
    r"doing (?:the )?" + _JOB + r"|running (?:the )?" + _JOB + r"|hunting|job hunting)"
    r"|(?:is|are) (?P<still2>" + _JOB + r") (?:still )?(?:running|going|on|active|happening|"
    r"working|in progress|underway|live|being sent)"
    r"|(?:is|are) (?:the |any )?(?:applications|jobs) still (?P<still3>going|running|being sent|"
    r"happening|in progress)"
    r"|(?:is|are) (?:she|it|the batch|the run) still (?P<still4>applying|running the job hunt)"
    # "is the job hunt paused" paid an eleven-second model round trip to
    # read one marker file (sandbox, 2026-10-05).
    r"|(?:is|are) (?P<paused>" + _JOB + r") (?:paused|stopped|on hold|off|held|suspended|on pause)"
    r"(?: right now| at the moment| still)?)$"
    # how many
    # "How many applications this week" - no verb at all (sandbox, 2026-10-05).
    r"|^how many (?:jobs|applications|apps)(?: (?:went out|sent|applied))?(?P<count3_window> (?:this week|this month|today|yesterday|last week|so far today))$"
    # "how many have you applied to today" - no noun at all (2026-10-05)
    r"|^how many (?:have|did) (?:you|u) (?:applied|apply) (?:to|for)(?P<count3_window2> (?:this week|this month|today|yesterday|last week|so far today))$"
    r"|^how many (?:jobs|applications|apps|places|companies|positions|roles|employers)"
    r"(?: (?:have|did|has) (?:you|u|she|we|i))? ?(?P<count>applied (?:to|for|at)|apply (?:to|for|at)|"
    r"sent(?: out)?|send(?: out)?|went out|go out|got sent|were sent|was sent|submitted|submit|put in|done|"
    r"gotten through|finished|completed|applied)"
    r"(?: (?:to|for))?(?P<count_total> (?:in total|total|overall|all ?together|altogether|ever|"
    r"so far|to date|all time))?(?: (?:today|now))?(?P<count_window> (?:this week|this month|yesterday|last week|"
    r"tonight|last night|overnight|this evening|this morning))?$"
    r"|^how many (?:have|did) (?:you|u) (?P<count2>apply to|send(?: out)?|submit|get through)"
    r"(?P<count2_total> (?:in total|total|overall|so far|ever))?"
    r"(?P<count2_window> (?:this week|this month|yesterday|last week|tonight|last night|overnight|this morning|this evening"
    r"|while i (?:was asleep|slept|was sleeping)))?(?: today)?$"
    # when was the last one
    r"|^when (?:was|did) (?:the |your |my |her )?(?:last|latest|most recent) "
    r"(?P<last_when>application|one|job application|job|submission)"
    r"(?: (?:go|go out|get sent|sent|submitted|happen|go through))?"
    r"|^when did (?:you|u|she) last (?P<last_when2>apply|apply (?:to|for) (?:a job|one|something|"
    r"anything|anywhere)|send (?:one|an application|an app)|submit (?:one|an application))"
    r"|^when(?:'s| is|s| was) (?:the )?(?:most recent|latest|last) (?P<last_when3>application|"
    r"one (?:you|u) sent)$"
    # what was the last one
    r"|^(?:what|which|who|where) (?:was|is|were) (?:the |your |her )?(?:last|latest|most recent) "
    r"(?P<last_what>job|application|one|company|place|employer|position|role)"
    r"(?: (?:you|u|she) (?:applied (?:to|for|at|with)|sent|did|went for|submitted))?"
    r"|^(?:what|which|where|who) did (?:you|u|she) (?P<last_what2>last apply (?:to|for|at|with)|"
    r"apply (?:to|for|at|with) last|apply (?:to|for) most recently)"
    r"|^what(?:'s| is|s) (?:the )?(?:last|latest|most recent) (?P<last_what3>job|application|one|"
    r"place|company)(?: (?:you|u) applied (?:to|for|at))?$"
    # what's blocking
    r"|^what(?:'s| is|s)? (?:blocking|stopping|holding up|in the way of|holding back|stalling) "
    r"(?P<blocking>" + _JOB + r"|(?:you|u)(?: from applying| on (?:the )?jobs)?|it|the run|things)"
    r"|^why (?:is|are|has|have|did) (?P<blocking2>" + _JOB + r") (?:stuck|stopped|blocked|stalled|"
    r"not (?:running|going|moving|working|happening)|stop(?:ped)?)"
    r"|^(?:is|are) (?P<blocking3>" + _JOB + r") (?:stuck|blocked|stalled)"
    r"|^why (?:aren't|are not|haven't|have not|arent|havent) (?:you|u) (?P<blocking4>applying|"
    r"applied|sending (?:any |out )?applications|sent (?:any )?(?:applications|any))"
    r"(?: (?:to|for) (?:jobs|anything|anywhere))?$"
    # a repo, by name (resolved against the pulse; unknown -> planner)
    r"|^(?:is|are) (?:the |my )?(?P<repo>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot| thing)?"
    r" (?:still )?(?:running|healthy|ok|okay|fine|good|green|up|working|alive|broken|down|failing|red|"
    r"in trouble|having (?:problems|issues|trouble))(?: right now| now| today| at the moment)?$"
    r"|^how(?:'s| is|s) (?:the |my )?(?P<repo2>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)?"
    r"(?: doing| going| looking| holding up| running)(?: today| now| lately| these days)?$"
    r"|^what(?:'s| is|s)? (?:the )?(?:status|state|health)(?: on| of)? (?:the |my )?"
    r"(?P<repo3>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)?$"
    # "what's the Barkly status" / "Barkly status" (offline 2026-09-24: a model
    # said "I have nothing on Barkly" while the pulse held its row)
    r"|^(?:what(?:'s| is|s)? )?(?:the |my )?(?P<repo5>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)?"
    r" (?:status|health)(?: today| now| right now)?$"
    r"|^why (?:is|are) (?:the |my )?(?P<repo4>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)?"
    r" (?:red|failing|broken|down|unhealthy|not healthy|in trouble)(?: right now| today)?$")

# Each is (name, pattern). Anchored, because "tell me about the halt
# behaviour in the docs" is not "are you halted".
PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    # `down` marks the alternatives that ask whether she is STOPPED, so
    # the answer can agree with the question. Without it "are you
    # running" and "you there" -- the two most natural ways to ask --
    # were answered "No, I'm running.", which is a contradiction in the
    # same breath.
    ("halted", re.compile(
        r"^(?:are|r) (?:you|u) (?P<down>halted|stopped|paused|off|frozen)$"
        r"|^(?:are|r) (?:you|u) (?:running|on|up|working|alive|awake)$"
        r"|^is the kill switch (?P<down2>on)$|^is the kill switch off$"
        r"|^(?:are|r) (?:you|u) ok$"
        # No verb at all is how a person actually checks. "you there" is
        # the single most natural way to ask this and it paid a planner
        # round trip to be told yes.
        r"|^(?:you|u) (?:there|awake|up|good|ok|alive|with me)$"
        r"|^(?:are|r) (?:you|u) (?:there|still there|still up)$"
        r"|^still (?:there|awake|up)$|^(?:you|u) still (?:there|up)$")),
    ("waiting", re.compile(
        r"^what(?:'s| is|s)? waiting(?: on| for)? me(?: right now| now)?$"
        r"|^what(?:'s| is|s)? waiting$"
        r"|^what(?:'s| is|s)? (?:blocked|stuck|held up|hung up) on me(?: right now| now)?\s*\??$"
        # "What needs me right now" / "the first thing waiting on me" (2026-09-24, offline)
        r"|^what needs me(?: right now| now| today)?\s*\??$"
        r"|^what(?:'s| is|s)? the (?:first|next|top) thing (?:waiting (?:on|for) me|i need to do|that needs me)\s*\??$"
        r"|^(?:does )?anything need me(?: right now| now)?\s*\??$"
        r"|^(?:is there )?anything (?:waiting )?for me$"
        r"|^(?:do )?(?:you )?need anything(?: from me)?$"
        # "What do you need from me" is the fourth of the brief's four
        # questions, and it paid a round trip to be answered from the same
        # stores as "what's waiting on me".
        r"|^what do (?:you|u) need from me(?: right now| today)?$"
        r"|^(?:is there )?anything (?:you|u) need from me$"
        r"|^what needs me$|^anything i need to (?:do|see|look at)$"
        r"|^what(?:'s| is|s)? on my plate$"
        r"|^is there anything waiting(?: on me| for me)?$"
        r"|^anything i should know(?: about)?$"
        r"|^what am i blocking$|^am i blocking anything$"
        # "What needs my yes" took fifteen seconds on her own model for the
        # same one list (2026-09-22).
        r"|^what(?:'s| is|s)? (?:needs|waiting on|wants|waiting for|needing) my (?:yes|ok|okay|approval|sign-?off|answer|go-?ahead)$"
        r"|^(?:is there )?anything (?:that )?(?:needs|waiting on|waiting for) my (?:yes|ok|okay|approval|answer)$"
        # "Which of my applications are waiting on me" went to the planner
        # and, with every frontier off, to her own model for two minutes
        # before the room gave up (2026-09-22) - the applications are on
        # the same ONE list as everything else that needs him.
        r"|^(?:which|what)(?: of my)? (?:applications|apps|jobs|forms) (?:are|r|is) "
        r"(?:waiting (?:on|for) me|stuck on me|(?:still )?(?:waiting|blocked|stuck)|"
        r"(?:waiting on|need(?:ing)?) (?:my|an) answers?|need(?:ing)? me)$"
        r"|^(?:which|what) (?:applications|apps|jobs|forms) need(?: me| my answers?| my input)?$"
        r"|^(?:are|r) (?:any|there any) (?:applications|apps|jobs|forms) waiting(?: on| for)? me$")),
    ("doing", re.compile(
        r"^what (?:are|r) (?:you|u) (?:doing|working on|up to)"
        r"(?: right now| now| at the moment| currently)?$"
        r"|^what(?:'s| is|s)? (?:happening|going on|the status)(?: right now| now)?$"
        r"|^status$|^how(?:'s| is) it going$")),
    # The brief's first question, answered from the application records
    # with no model: every number in the answer is a count of records.
    # "Give me a status update" and "what should I focus on today" waited two
    # minutes or planned "Plan your day" as a step (2026-09-23). Both are
    # her records, read together: how she is, what needs him, his day, the
    # hunt, his next task.
    ("status", re.compile(
        r"^(?:give me |i want |i need )?(?:a |the |an )?(?:status|status update|status report|update|sitrep|rundown|"
        r"situation report)(?: please)?$"
        r"|^(?:how are things|how(?:'s| is) everything|how(?:'s| is) it going|what(?:'s| is) (?:going on|the situation|the status))"
        r"(?: today| right now| with you)?$"
        # "how are you feeling", "are you ok" (2026-10-05: a model, seven seconds)
        r"|^how (?:are|r) (?:you|u)(?: feeling| doing| holding up| today| tonight)?$|^how do (?:you|u) feel$"
        r"|^(?:are|r) (?:you|u) (?:ok|okay|alright|all right|good|well|fine)(?: today| tonight)?$|^(?:you|u) (?:ok|okay|alright|good)$"
        r"|^(?:catch me up|fill me in|bring me up to speed|where are we)(?: please)?$"
        # "Are we good", "summarize today", "how was your day": the rundown
        # (bottom rung 2026-09-24: a repo lookup for "we", and nobody).
        r"|^(?:are we good|is everything (?:ok|okay|alright|fine|good)|all good|everything good)(?: today)?\s*\??$"
        r"|^(?:summari[sz]e|recap|sum up) (?:today|my day|the day|things)(?: for me)?\s*\??$"
        r"|^how (?:was|did) (?:your|the|my) day(?: go)?\s*\??$"
        # "Any news" alone answered about employers only; "what should I know"
        # paid a model (sixteenth batch, 2026-10-05). Both are the rundown.
        r"|^(?:any news|anything new|what(?:'s| is) new with you|anything i should know|what should i know|"
        r"what do i need to know|what have i missed)(?: today)?\s*\??$")),
    ("focus", re.compile(
        r"^what should i (?:focus on|do|work on|prioriti[sz]e|tackle|start with)(?: today| first| right now| this morning| now| next)?$"
        r"|^(?:plan|organi[sz]e|map out|lay out) my day$|^what(?:'s| is) (?:the )?(?:most important|top priority|priority)"
        r"(?: thing)?(?: today| right now)?$|^what(?:'s| is) on (?:my|the) plate(?: today)?$"
        r"|^what do i need to (?:do|get done)(?: today)?$"
        # "what's first" and "anything urgent" each paid a model (2026-10-05)
        r"|^what(?:'s| is|s)? (?:up )?first(?: today| this morning)?\s*\??$"
        r"|^(?:is there )?anything (?:urgent|pressing|on fire)(?: today| right now)?\s*\??$"
        r"|^what(?:'s| is|s)? (?:urgent|pressing)(?: today| right now)?\s*\??$")),
    ("overdue", re.compile(
        r"^what(?:'s| is|s)? overdue\s*\??$|^(?:is )?anything overdue\s*\??$|^what (?:have i|did i) miss(?:ed)? (?:the deadline|a deadline) (?:on|for)\s*\??$"
        r"|^what(?:'s| is|s)? (?:late|past due|behind)\s*\??$|^(?:am i|are we) behind on anything\s*\??$")),
    # "How many interviews do I have" / "did I get any rejections" (2026-09-23):
    # outcomes are on the application records.
    ("outcomes", re.compile(
        r"^(?:how many|any|do i have any|did i get any|have i (?:got|gotten|had) any|what) (?P<outcome>interviews?|offers?|"
        r"rejections?)(?: (?:do i have|have i got|so far|yet|lined up|coming up|today|this week))*$"
        r"|^(?:who|which (?:companies|employers|jobs)) (?:(?P<outcome2>rejected) me|(?P<outcome3>turned) me down|"
        r"made (?:me )?an (?P<outcome4>offer)|(?:wants?|asked) (?:to |an |for an )?(?P<outcome5>interview|talk))$"
        # "Did I get an interview" (2026-09-24, offline: "I could not plan that")
        r"|^(?:did|have) i (?:get|got|gotten|land|landed|receive|received) (?:an |any |a )?(?P<outcome6>interviews?|offers?|rejections?)"
        r"(?: yet| today| this week| so far)?\s*\??$"
        # "did anyone reject me" (2026-10-05: a model, "I can't tell")
        r"|^(?:did|has) (?:anyone|anybody|any company|any employer|someone) (?P<outcome7>reject|rejected|turn down|turned down|say no to|said no to|pass on|passed on) me(?: yet| today| this week)?\s*\??$")),
    # The records answer these (2026-10-05: six model turns, each denying
    # or hedging about a store she holds).
    ("ghosted", re.compile(
        r"^who (?:ghosted|never (?:replied|got back|wrote back|answered)|hasn'?t (?:replied|got back|written back|answered)|owes me a reply)(?: (?:to )?me)?\s*\??$"
        r"|^who (?:haven'?t|have i not) i heard (?:back )?from\s*\??$|^who haven'?t i heard back from\s*\??$"
        r"|^(?:which|what) (?:companies|employers|applications) (?:haven'?t|never|didn'?t) (?:replied|got back|written back|answered)\s*\??$"
        r"|^who (?:should i|do i need to) (?:chase|nudge|poke)\s*\??$")),
    ("application_extreme", re.compile(
        # (the newest is `newest_application` above - one door per question)
        r"^what(?:'s| is|s)? (?:my |the )?(?P<app_extreme>oldest|first|earliest) application\s*\??$"
        r"|^which application is (?:the )?(?P<app_extreme2>oldest|furthest along|farthest along|most advanced|closest)\s*\??$"
        r"|^what(?:'s| is|s)? (?:the )?(?P<app_extreme3>furthest along|farthest along)\s*\??$")),
    ("last_sent", re.compile(
        r"^what(?:'s| is| was|s)? the last (?:thing|application|one) (?:you|u) sent(?: out)?\s*\??$"
        r"|^what did (?:you|u) send (?:last|most recently)\s*\??$")),
    ("found_companies", re.compile(
        r"^(?:what|which) (?:companies|employers) (?:did (?:you|u) (?:find|see|come across|turn up)|came up|turned up)(?: today| so far today)?\s*\??$"
        r"|^(?:who|what companies) (?:are|r|is) hiring(?: today| right now)?\s*\??$")),
    ("next_batch", re.compile(
        r"^when(?:'s| is) the next (?:batch|round|run)(?: of applications)?\s*\??$"
        r"|^when (?:do|will|does) (?:you|u|the hunt|it) (?:apply|run|send|go) (?:again|next)\s*\??$"
        r"|^when(?:'s| is) the next time (?:you|u)(?:'ll| will) apply\s*\??$")),
    ("job_hunt", re.compile(
        r"^how (?:did|have|are) (?:the )?(?:job )?(?:applications|apps|job hunt|hunt|job search)"
        r" (?:go|gone|going)(?: today| so far| so far today)?$"
        r"|^how am i doing (?:on|with|in) (?:the |my )?(?:job hunt|job search|hunt|search|applications)(?: today)?$"
        r"|^(?:how(?:'s| is) )?(?:my|the) (?:job hunt|job search) (?:doing|looking|coming along|progressing)(?: today)?$"
        r"|^how(?:'s| is) the (?:job )?(?:hunt|search|applications?)(?: going)?(?: today)?$"
        r"|^(?:did|have) (?:you|u) (?:apply|applied) to (?:any|anything|any jobs)(?: today)?$"
        r"|^(?:job )?(?:applications|hunt) (?:status|today|report)$"
        # "What are you doing about the job hunt right now" waited two
        # minutes on her own model with every frontier off (2026-09-22).
        r"|^what (?:are|r) (?:you|u) doing (?:about|with|on|for) (?:the |my )?"
        r"(?:job (?:hunt|search|applications?)|applications|jobs|hunt)(?: right now| today| at the moment)?$")),
    # ONE opportunity, by name. "How do you feel about the Anthropic
    # application" went to the planner and, with every frontier off, to
    # her own model for two minutes (2026-09-22) - and the opportunity
    # record, or the application record, IS the answer. The pursuit store
    # had a writer and no spoken reader; this is the reader.
    ("opportunity", re.compile(
        r"^(?:how do (?:you|u) feel about|how(?:'s| is|s)?|what(?:'s| is|s)? (?:the plan|happening|going on|the story|the status) (?:with|for|on)|"
        r"where (?:are we|am i|do we stand) (?:with|on)|what about|any (?:news|word|movement|update) on|"
        r"(?:what(?:'s| is|s)? the )?status of|how(?:'s| is) it going with|tell me about|what do (?:you|u) think (?:of|about)|"
        r"what(?:'s| is|s)? next (?:for|on|with)|what(?:'s| is|s)? the next (?:step|move) (?:for|on|with)|"
        r"what (?:are|r) (?:you|u) doing (?:about|with|on|for))"
        r" (?:the |my |our )?(?P<what>.+?) (?:application|app|job|role|opportunity|position|posting)(?: going| doing| looking)?$")),
    # "What's the latest with DevRev" names the thing without calling it an
    # application; when the words match an opportunity or a record, that is
    # the answer, and when they match nothing the model may still think.
    # "Anything from Vanta" and "did Vanta reply" fell through to a planner
    # with every frontier off (2026-09-23 night sweep); the record answers.
    ("opportunity_loose", re.compile(
        r"^(?:what(?:'s| is|s)? the latest (?:with|on|from)|any (?:news|word|update) (?:from|on|with)|"
        r"how(?:'s| is) it going with|where (?:are we|am i) with|what(?:'s| is|s)? happening with|"
        r"how (?:did|has) (?:it|things) (?:go|gone) with|"
        r"anything (?:new |back )?from|any(?:thing| word| reply| response| answer) (?:back )?from|"
        r"(?:have (?:you|u|we|i) )?heard (?:anything |back )?from|did (?:you|u|we|i) hear (?:anything |back )?from)"
        # "anything from anyone" / "did any employers reply" name nobody in
        # particular and stay with the replies shape below
        r" (?:the |my )?(?!(?:any|anyone|anybody|someone|somebody|they|them|people|employers?|companies|recruiters|jobs|work)\b)"
        r"(?P<what>[a-z0-9][a-z0-9 .&'-]{1,40}?)(?: yet)?\s*\??$"
        r"|^(?:did|has|have) (?:the )?(?!(?:any|anyone|anybody|someone|somebody|they|them|people|employers?|companies|recruiters)\b)"
        r"(?P<what2>[a-z0-9][a-z0-9 .&'-]{1,40}?)"
        r" (?:replied|reply|responded|respond|get back|gotten back|written back|write back|answered|answer)"
        r"(?: yet| to me| to us| back)?\s*\??$")),
    # "What companies have I applied to" came back from her own model as
    # "I don't have a record of your job applications - no tracker
    # connected here", and "when did I apply to Stripe" waited two
    # minutes. The records are the answer (2026-09-22).
    ("applied_to", re.compile(
        r"^(?:what|which) (?:companies|employers|places|jobs) have i applied (?:to|for)(?: so far| this week| today)?$"
        # "what jobs have you applied to" paid eight seconds (2026-10-05)
        r"|^(?:what|which) (?:companies|employers|places|jobs|roles|positions) have (?:you|u) applied (?:to|for)(?: for me)?(?: so far| this week| today)?$"
        r"|^what have (?:you|u) applied (?:to|for)(?: for me)?(?: so far| this week| today)?$"
        r"|^where have i applied(?: so far| this week| today)?$"
        r"|^(?:who|what) have (?:you|u) applied (?:to|for)(?: for me)?(?: so far| this week| today)?$"
        r"|^(?:what|who|where) did (?:you|u|we) apply(?: (?:to|for))?(?: for me)?(?: this week| so far)?$"
        r"|^(?:list|show me|name) (?:the |my )?(?:companies|employers|places) (?:i|you|u|we)(?:'ve| have)? applied to$")),
    ("applied_when", re.compile(
        r"^when did (?:i|you|u|we) apply (?:to|for|at) (?:the |my )?(?P<what>[a-z0-9][a-z0-9 .&'-]{1,40}?)"
        r"(?: (?:job|role|position|application|opening))?\s*\??$"
        r"|^(?:did|have) (?:i|you|u|we) (?:apply|applied) (?:to|for|at) (?:the |my )?(?P<what2>[a-z0-9][a-z0-9 .&'-]{1,40}?)"
        r"(?: (?:job|role|position|application|opening))?(?: yet| already)?\s*\??$")),
    # "What do you know about me" answered "I don't have anything
    # remembered about 'me'" - a lookup under the key "me". It is the
    # whole of what she holds about him, said plainly.
    ("about_him", re.compile(
        r"^what do (?:you|u) (?:know|have|remember) (?:about|on) me$"
        r"|^what have (?:you|u) (?:remembered|learned|got|saved) about me$"
        r"|^what(?:'s| is) (?:on file|in your memory) about me$|^tell me what (?:you|u) know about me$")),
    # "Say that again" waited two minutes on her own model for her own last
    # sentence, which the conversation thread holds (2026-09-22).
    ("repeat", re.compile(
        r"^(?:say that again|repeat that|come again|what did (?:you|u) just say|what was that|"
        r"sorry,? what|pardon|say again|one more time|i didn'?t (?:catch|hear) that|what did (?:you|u) say)$")),
    # "Who is my landlord" came back from her own model as "no lease or
    # rental info connected here" - a capability she has, denied. The
    # person is remembered or he is asked, in words, never a model's guess.
    ("person", re.compile(
        r"^who(?:'s| is|s)? my (?P<what>landlord|landlady|boss|manager|doctor|dentist|lawyer|accountant|"
        r"realtor|agent|mechanic|plumber|electrician|barber|therapist|trainer|coach|banker|broker|"
        r"sister|brother|mom|mother|dad|father|wife|husband|partner|girlfriend|boyfriend|roommate|"
        r"neighbou?r|best friend|emergency contact|recruiter)\s*\??$")),
    # "Who is Dana" paid a model (2026-10-05); she is on the people shelf.
    ("who_is", re.compile(
        r"^who(?:'s| is) (?!(?:my|the|your|our|i|you|u|she|he|it|that|this|there|here|calling|on|in|at|this)\b)(?P<who_is>[a-z][a-z .'-]{1,40}?)\s*\??$")),
    # "How many opportunities are you working on" came back from her own
    # model as "opportunity tracking is experimental for me right now, not
    # something I run live yet" - while forty of them sat in her store.
    ("pursuit_count", re.compile(
        r"^how many (?:opportunities|jobs|applications|things|roles) (?:are|r) (?:you|u) "
        r"(?:working on|pursuing|carrying|tracking|chasing|following up on|looking after)(?: right now| at the moment)?$"
        r"|^what (?:opportunities|jobs) (?:are|r) (?:you|u) (?:working on|pursuing|carrying|chasing)(?: right now)?$")),
    # "What did you do without asking me" is the honesty question the
    # autonomy ledger exists for (CLAUDE.md), and with every frontier off
    # it went to her own model for two minutes (2026-09-22). A file read.
    ("unattended", re.compile(
        r"^what (?:did|have) (?:you|u) (?:do|done)(?: today| lately| recently)? "
        r"(?:without (?:asking|telling|checking with) me|on your own|by yourself|unattended|"
        r"without (?:my|an) (?:ok|okay|approval|yes))(?: today| lately| recently)?$"
        r"|^(?:did|have) (?:you|u) (?:do|done) anything (?:without (?:asking|telling) me|on your own|by yourself)"
        r"(?: today| lately| recently)?$"
        r"|^what have (?:you|u) been doing on your own$")),
    # "How much memory is free" came back "reading system memory usage
    # isn't something I can do" from her own model - the same machine
    # reading she makes before loading that model. An offer of ignorance
    # is a claim about ability, and it was false.
    ("machine", re.compile(
        r"^how much (?:memory|ram|free memory)(?: is| do (?:i|we) have)?(?: free| left| available| used| in use)?"
        r"(?: on (?:this|the|my) (?:computer|machine|pc|laptop))?$"
        r"|^(?:is|how is) (?:the |this |my )?(?:computer|machine|pc|laptop) (?:low on memory|out of memory|running low)$"
        r"|^how(?:'s| is) (?:the |this |my )?(?:computer|machine|pc|laptop)(?:'s)? memory$")),
    # Four more readings of the same machine (2026-09-22): the disk ("not
    # something in my toolkit yet" - it is a system call), the address
    # (searched his contacts for "my ip"), whether the internet is up
    # (94 s of her own model, and "Thinking with no internet: yes"), and
    # what is open ("[Uses look at the desktop]" read out as prose).
    ("disk", re.compile(
        r"^how much (?:disk|disk space|storage|space|hard drive space|room)(?: do (?:i|we) have| is)?"
        r"(?: free| left| available)?(?: on (?:this|the|my) (?:computer|machine|pc|laptop|disk|drive|hard drive))?$"
        r"|^(?:is|how is) (?:the |this |my )?(?:computer|machine|pc|laptop|disk|drive) (?:low on (?:space|storage|disk)|full|out of space)$")),
    ("ip", re.compile(
        r"^what(?:'s| is) (?:my|this computer's|the|this machine's) ip(?: address)?$"
        r"|^what ip(?: address)? (?:am i on|is this|do i have)$")),
    # Three about the machine that paid a model each (2026-10-05): the
    # battery, the screen, and a speed she does not measure.
    ("battery", re.compile(
        r"^(?:how much|what(?:'s| is|s)?|how(?:'s| is)) (?:the |my )?battery(?: (?:do i have|left|at|is left|level|percent|charge))?(?: left)?\s*\??$"
        r"|^(?:is|am i) (?:the )?(?:battery |laptop |pc |computer )?(?:plugged in|charging|on battery|on mains|on power|low on battery)\s*\??$"
        r"|^how (?:long|much) (?:battery |charge )?(?:is |do i have )?left(?: on (?:the|my) (?:battery|laptop))?\s*\??$")),
    ("screen_size", re.compile(
        r"^what(?:'s| is|s)? (?:my |the |this )?(?:screen|display|monitor) (?:resolution|size)\s*\??$"
        r"|^what resolution (?:is|am i on|is (?:my|the) (?:screen|display|monitor))\s*\??$"
        r"|^how (?:big|large) is (?:my|the|this) (?:screen|display|monitor)\s*\??$")),
    ("internet_speed", re.compile(
        r"^how fast is (?:my |the |our )?(?:internet|wifi|wi-fi|connection|network)(?: right now| today)?\s*\??$"
        r"|^what(?:'s| is|s)? (?:my |the )?(?:internet|download|connection) speed\s*\??$"
        r"|^(?:run|do) a speed test\s*\??$|^(?:is|why is) (?:the |my )?(?:internet|wifi|wi-fi) (?:so )?slow\s*\??$")),
    ("internet", re.compile(
        r"^(?:is|do (?:i|we) have) (?:the |an )?(?:internet|wifi|wi-fi|network|connection)(?: connection)?"
        r"(?: working| up| on| down| connected| okay| ok)?$"
        r"|^(?:am i|are we|are you) (?:online|connected|on the internet)$"
        r"|^(?:is|has) the (?:internet|wifi|wi-fi) (?:down|out|gone|back)$")),
    ("windows", re.compile(
        r"^what(?:'s| is| are)? (?:apps?|programs?|windows?)(?: are| is)? (?:open|running|up)"
        r"(?: right now| now| on (?:this|the|my) (?:computer|machine|pc|laptop|screen))?$"
        r"|^what(?:'s| is) (?:open|on (?:my|the) screen)(?: right now| now)?$"
        r"|^what (?:do (?:i|you) have|have i got) open(?: right now| now)?$")),
    # The third question. It has a `recollection` pattern for the model's
    # context and no fast answer, so "what went wrong today" paid a round
    # trip to read out alerts that are a file read away.
    # FOUR MORE FROM THE JOB HUNT'S OWN RECORDS (2026-09-23 night sweep):
    # "why didn't the Datadog one go", "anything I need to answer", "how
    # many jobs have you found" and "show me the fleet" each waited two
    # minutes on her own model for a store she holds.
    ("why_not", re.compile(
        r"^why (?:didn'?t|did not|hasn'?t|has not|wasn'?t|was not|isn'?t|is not) (?:the )?(?P<why_not>[a-z0-9][a-z0-9 .&'-]{1,40}?(?: one| application| app)?)"
        r" (?:go|sent|send|go out|go through|get sent|work|submitted|submit|apply)(?: yet| through| out)?$"
        r"|^why did (?:the )?(?P<why_not2>[a-z0-9][a-z0-9 .&'-]{1,40}?(?: one| application| app)?) (?:fail|not go|get stuck|stop)$"
        r"|^what happened (?:with|to) (?:the )?(?P<why_not3>[a-z0-9][a-z0-9 .&'-]{1,40}?(?: one| application| app))$")),
    # WHY THE HUNT IS NOT MOVING, from its own switches: his stop, a pause,
    # the grant, who can think, the browser. Offline (2026-09-24) "why can't
    # you apply to jobs right now" was "I couldn't look into that just now".
    ("hunt_why", re.compile(
        r"^why (?:can'?t|cannot|aren'?t|are not|won'?t|will not|don'?t|do not) (?:you|u) "
        r"(?:apply|applying|apply to jobs|applying to jobs|apply for jobs|applying for jobs|"
        r"send (?:any )?applications|sending (?:any )?applications|do (?:the )?(?:job )?(?:hunt|applications))"
        r"(?: right now| now| anymore| any more| today| at the moment)?\s*\??$"
        r"|^why (?:is|has) the (?:job )?(?:hunt|search) (?:stopped|paused|stuck|not (?:running|moving|going))\s*\??$"
        r"|^why (?:aren'?t|are no|have no) (?:applications|jobs) (?:going|gone) out(?: today)?\s*\??$")),
    ("to_answer", re.compile(
        r"^(?:is there )?anything (?:i|that i) (?:need|have) to answer(?: for you)?$"
        r"|^what (?:questions|do you need answered|do (?:you|u) need me to answer|needs answering)(?: do (?:you|u) have)?(?: for me)?$"
        r"|^(?:any|what) questions(?: for me)?$|^what are (?:you|u) (?:stuck on|waiting on me for)$"
        r"|^what questions do (?:you|u) (?:need|want) me to answer\s*\??$"
        r"|^what do (?:you|u) need answers? (?:to|for)\s*\??$")),
    # "How many jobs are left to apply to": there is no queue, and saying so
    # with the day's numbers is a fact (bottom rung, 2026-09-24).
    # A count of unread notices is a number in her store (bottom rung 2026-09-24).
    ("notify_count", re.compile(
        r"^how many (?:unread )?notifications? (?:do i have|are there|are waiting|have i got|do (?:you|u) have for me)"
        r"(?: unread)?\s*\??$"
        r"|^(?:any|do i have any) (?:unread |new )?notifications?(?: for me)?\s*\??$")),
    ("jobs_left", re.compile(
        r"^how many (?:jobs|openings|applications) (?:are |do (?:you|u) have )?(?:left|remaining|still)"
        r"(?: to (?:apply to|apply for|do|send|go))?\s*\??$"
        r"|^what(?:'s| is) left to apply (?:to|for)\s*\??$")),
    ("found", re.compile(
        r"^how many (?:jobs|openings|postings|roles|positions) (?:have (?:you|u)|did (?:you|u)|have we) (?:found|find|come across|turned up|discovered)"
        r"(?: today| so far| tonight| (?P<found_window>this week|yesterday|last week))?$"
        r"|^what (?:jobs|openings) (?:have (?:you|u)|did (?:you|u)) (?:found|find)(?: today)?$")),
    # WHO IS WAITING ON HIM in his conversations: a reply nothing of his has
    # answered, or a follow-up that is due (bottom rung 2026-09-24).
    ("applications_waiting", re.compile(
        r"^how many (?:applications|apps|jobs) (?:are )?(?:waiting|pending|stuck|held up)(?: on me| for me| on you| to go out| on my tap)?\s*\??$"
        r"|^how many (?:are )?(?:waiting|pending) (?:on me|for me|to go out)\s*\??$"
        r"|^how many (?:applications|apps) need (?:me|my answer|my tap|a tap)\s*\??$")),
    ("follow_ups", re.compile(
        r"^what (?:should|do) i (?:need to )?follow up on\s*\??$"
        r"|^who do i (?:need|have|owe) (?:to )?(?:write|get|reply|respond) back to\s*\??$"
        r"|^who(?:'s| is) waiting (?:on|for) (?:a reply|an answer|a response) from me\s*\??$"
        r"|^(?:which|what) (?:conversations|threads|emails) (?:need|are waiting on) (?:me|a reply)\s*\??$"
        r"|^(?:any|do i have any) follow[ -]?ups? (?:due|to do|owed)?\s*\??$")),
    ("newest_application", re.compile(
        r"^what(?:'s| is|s)? (?:the |my )?(?:newest|latest|most recent|last) application\s*\??$"
        r"|^(?:which|what) (?:job|one) did (?:you|u) (?:apply to|send) (?:last|most recently)\s*\??$")),
    ("fleet", re.compile(
        r"^(?:show me |what(?:'s| is) |how(?:'s| is) )?(?:the )?fleet(?: doing| status| looking| look)?$"
        r"|^how are (?:my|the) (?:other )?(?:projects|repos|repositories)(?: doing)?$"
        r"|^(?:what(?:'s| is) the )?fleet status$|^any faults(?: in the fleet)?$")),
    # THE FLEET, ASKED SIDEWAYS (2026-10-05: a model each, four to five
    # seconds, with no pulse to read and nothing to say but that).
    ("last_fault", re.compile(
        r"^(?:which|what) (?:repo|repository|project|one) (?:had|has|got) the (?:last|latest|newest|most recent) (?:fault|failure|alert|problem)\s*\??$"
        r"|^what (?:failed|broke|went red) (?:last|most recently|latest)\s*\??$|^what(?:'s| is| was) the (?:last|latest|newest|most recent) (?:fault|failure|alert)\s*\??$"
        r"|^where (?:was|is) the (?:last|latest|newest) (?:fault|failure)\s*\??$")),
    ("pulse_age", re.compile(
        r"^when (?:was|is) the (?:last|latest|next) (?:pulse|fleet (?:read|reading|check))\s*\??$|^how old is the (?:pulse|fleet reading)\s*\??$"
        r"|^when did (?:you|u) last (?:read|check) the fleet\s*\??$|^how (?:fresh|stale|recent) is the (?:pulse|fleet reading)\s*\??$"
        r"|^is the pulse (?:fresh|stale|current|up to date)\s*\??$|^when (?:was|is) the fleet last read\s*\??$")),
    ("repo_list", re.compile(
        r"^(?:list|name|show me) (?:the |my |all the )?(?:repos|repositories|fleet)(?: for me)?\s*\??$"
        r"|^(?:what|which) (?:repos|repositories|projects) (?:do (?:you|u) (?:watch|monitor|track|have)|are (?:you|u) watching|are in the fleet|are there)\s*\??$"
        r"|^what(?:'s| is) in the fleet\s*\??$|^what(?:'s| is) the fleet made of\s*\??$")),
    ("ci_failing", re.compile(
        r"^(?:what(?:'s| is)|which (?:workflows?|jobs?|runs?) (?:are|is)) (?:failing|red|broken) (?:in|on) (?:ci|github actions|actions|the (?:ci|pipelines))\s*\??$"
        r"|^is (?:ci|the ci|github actions|actions) (?:green|red|passing|failing|ok|okay|good|broken)\s*\??$"
        r"|^(?:any|are there any) (?:red|failing|broken) (?:workflows|runs|jobs|pipelines)\s*\??$|^(?:how(?:'s| is) )?ci(?: doing| looking)?\s*\??$")),
    ("wrong", re.compile(
        r"^what went wrong(?: today| tonight| so far today| overnight)?$"
        r"|^(?:anything|something) (?:go|went|gone) wrong(?: today| tonight| overnight| last night| so far)?$|^anything wrong(?: today| tonight)?$"
        r"|^what(?:'s| is|s)? (?:broken|failing|stuck)(?: today)?$"
        r"|^(?:did|has) anything (?:fail|failed|go wrong|gone wrong|break|broken)(?: today| tonight| overnight| last night)?$"
        r"|^what failed(?: today| tonight)?$|^any (?:errors|failures|problems)(?: today| tonight)?$"
        # "what broke" and "what went wrong yesterday" (2026-10-05: a model;
        # a model AND her own diagnosis, 29 seconds)
        r"|^what (?:broke|blew up|crashed|fell over)(?: today| tonight)?$|^what(?:'s| has) gone wrong(?: today)?$"
        r"|^what (?:went wrong|failed|broke|blew up|crashed) (?P<wrong_when>yesterday|last night)$"
        r"|^(?:did|has) anything (?:fail|failed|go wrong|gone wrong|break|broken) (?P<wrong_when2>yesterday)$")),
    # What he decided today is in the approvals store (2026-10-05: "I don't
    # have the full journal for the day in front of me", six seconds).
    ("decided", re.compile(
        r"^what (?:did|have) i (?P<decided>approve|approved|ok'?d|okayed|say yes to|said yes to|green ?lit|green ?lighted|sign off on|signed off on)(?: today| so far today| this morning| tonight| this week)?\s*\??$"
        r"|^what (?:did|have) i (?P<decided2>deny|denied|turn down|turned down|reject|rejected|say no to|said no to|refuse|refused|decline|declined)(?: today| so far today| this morning| tonight| this week)?\s*\??$"
        r"|^what (?:approvals|decisions) (?:did|have) i (?P<decided3>make|made|give|given|do|done)(?: today)?\s*\??$")),
    # "What's the last thing you did" paid a model to read the newest
    # line of a journal she holds (2026-09-22).
    ("last", re.compile(
        r"^what(?:'s| is|s| was)? the last thing (?:you|u) did$"
        r"|^what did (?:you|u) (?:just )?do (?:last|just now|most recently|a (?:minute|moment|second) ago)$"
        r"|^what did (?:you|u) just do$"
        r"|^what was (?:your|the) (?:last|most recent) (?:action|thing)$"
        r"|^what(?:'s| is|s)? the (?:last|latest|most recent) thing (?:you|u)(?:'ve| have)? done$")),
    # "How many days until Christmas" paid a model for arithmetic on a
    # calendar (2026-09-23). Weekdays, named days and a month-and-day.
    # The clock and the calendar, from arithmetic (2026-10-05: nine model
    # turns of four seconds each for "what time is it in an hour", "is it
    # the weekend", "what quarter is it", "how many days left in the year"...)
    ("clock_ahead", re.compile(
        r"^what time (?:is it|will it be|is) (?:in|after) (?P<ahead_n>an?|\d+|half an?|one|two|three|four|five|six|ten|twelve) ?(?P<ahead_unit>hours?|minutes?|mins?)(?: from now| from here)?\s*\??$"
        r"|^what(?:'s| is|s)? (?P<ahead_n2>an?|\d+|half an?|one|two|three|four|five|six|ten|twelve) ?(?P<ahead_unit2>hours?|minutes?|mins?) from now\s*\??$"
        r"|^what time was it (?P<ago_n>\d+|an?|one|two|three) ?(?P<ago_unit>hours?|minutes?|mins?) ago\s*\??$")),
    ("until_clock", re.compile(
        r"^how (?:long|many (?:hours|minutes)) (?:until|till|before|to) (?P<until_t>\d{1,2}(?::\d{2})? ?(?:am|pm)?|noon|midnight|lunch|lunchtime|dinner|dinnertime)(?: today| tonight| tomorrow)?\s*\??$")),
    ("day_part_now", re.compile(
        r"^is it (?:morning|afternoon|evening|night) or (?:morning|afternoon|evening|night)\s*\??$"
        r"|^(?:is it|what part of the day is it)(?: still| already)? (?:morning|afternoon|evening|night|late|early)(?: yet)?\s*\??$"
        r"|^what (?:part|time) of (?:the )?day is it\s*\??$")),
    ("weekend_now", re.compile(
        r"^is it (?:the )?weekend(?: yet| already)?\s*\??$|^is (?:today|it) a (?:weekday|weekend day|work ?day|school day)\s*\??$"
        r"|^how (?:long|many days) (?:until|till|to) the weekend\s*\??$")),
    ("quarter", re.compile(r"^what quarter (?:is it|are we in|of the year is it)\s*\??$|^which quarter (?:is it|are we in)\s*\??$")),
    ("days_left", re.compile(
        r"^how many days (?:are )?left (?:in|of) (?:the|this) (?P<left_in>month|year|week|quarter)\s*\??$"
        r"|^how (?:much|many days) (?:of )?(?:the|this) (?P<left_in2>month|year|week|quarter) (?:is|are) left\s*\??$"
        r"|^when does (?:the|this) (?P<left_in3>month|year|week|quarter) end\s*\??$")),
    ("talking_for", re.compile(
        r"^how long (?:have|'ve) we been (?:talking|chatting|at this|going)(?: for)?(?: today)?\s*\??$"
        r"|^how long (?:have|'ve) (?:i|we) been (?:here|on)(?: today)?\s*\??$")),
    ("asked_today", re.compile(
        r"^how many (?:things|questions) (?:have i|did i|'ve i) (?:asked|said|told)(?: you)?(?: today| so far| tonight)?\s*\??$"
        r"|^how many times (?:have i|did i) (?:talked|spoken) to you(?: today| so far| tonight)?\s*\??$"
        r"|^how much (?:have i|did i) (?:asked|said|talked)(?: today| so far| tonight)?\s*\??$")),
    ("never_sleeps", re.compile(
        r"^(?:do|does) (?:you|u) (?:ever )?(?:sleep|rest|get tired|need (?:a |to )?(?:rest|sleep|break))\s*\??$"
        r"|^(?:are|r) (?:you|u) (?:ever )?tired\s*\??$|^when do (?:you|u) sleep\s*\??$|^(?:do|does) (?:you|u) (?:ever )?(?:take|get) breaks?\s*\??$")),
    ("just_asked", re.compile(
        r"^what did i (?:just )?(?:ask|say|tell)(?: you)?(?: just now| a (?:second|minute|moment) ago)?\s*\??$"
        r"|^what was the last thing i (?:said|asked|told you)\s*\??$|^what did i (?:just )?say to you\s*\??$"
        r"|^what did you (?:just )?(?:say|tell me|answer)(?: just now| a (?:second|minute|moment) ago)?\s*\??$"
        r"|^(?:say|repeat) that again\s*\??$|^what was that\s*\??$|^come again\s*\??$|^repeat that\s*\??$")),
    ("when_asked", re.compile(
        r"^(?:what time|when) did i (?:ask|say|tell you) (?:you )?that\s*\??$|^when was that\s*\??$|^what time was that\s*\??$"
        r"|^(?:what time|when) did i (?:last )?(?:ask|say) (?:something|anything)\s*\??$")),
    ("until_birthday", re.compile(
        r"^how (?:many days|long|many weeks) (?:until|till|to|before) my (?:next )?birthday(?: is it)?\s*\??$"
        r"|^when(?:'s| is) my next birthday\s*\??$|^is my birthday (?:soon|coming up)\s*\??$")),
    ("until", re.compile(
        r"^how (?:many (?:days|weeks)|long) (?:until|till|to|before) (?:the )?(?!(?:you|u|i|we|she|it|they|he) )"
        r"(?P<until>[a-z][a-z' ]{2,30}?)(?: is it)?$"
        r"|^(?:when is|when's) (?P<until2>christmas|new year(?:'s)?(?: day| eve)?|halloween|thanksgiving|"
        r"valentine'?s(?: day)?|easter|the fourth of july|july 4th|independence day)$"
        # "What day of the week is Christmas" paid a model for the same arithmetic.
        # "what day is X" is its own key now (`what_day`, 2026-10-05)
        )),
    # THE FIRST THING HE ASKS IN THE MORNING (2026-09-23): sent overnight
    # and done overnight, from the records.
    # THE MORNING AFTER (2026-09-23 night sweep): "how did the job hunt go
    # last night", "what jobs did you send overnight", "did anything get sent
    # while I slept", "which companies did you apply to last night" and "any
    # replies overnight" each went to a planner nobody could run - the first
    # things he says when he wakes.
    ("sent_window", re.compile(
        r"^(?:what|which)(?: jobs| applications| companies| employers| ones)? (?:did|have) (?:you|u|we) "
        r"(?:send|sent|apply to|applied to|put in|submit|submitted)(?: out)?(?: to)? "
        r"(?P<sent_window>last night|overnight|tonight|this morning|this evening|yesterday|this week|last week|this month"
        r"|while i (?:was asleep|slept|was sleeping))\s*\??$"
        r"|^(?:did )?anything (?:get |go |went )?(?:sent|out)(?: out)? (?P<sent_window2>last night|overnight|tonight|this morning|yesterday"
        r"|while i (?:was asleep|slept|was sleeping))\s*\??$")),
    ("overnight", re.compile(
        r"^how (?:did|was) (?:the )?(?:job hunt|hunt|job search|applications|applying) (?:go |do )?"
        r"(?:last night|overnight|tonight|while i (?:was asleep|slept|was sleeping))$"
        r"|^what happened (?:with|to|in) (?:the )?(?:job hunt|hunt|job search|applications) "
        r"(?:last night|overnight|tonight|while i (?:was asleep|slept|was sleeping))$"
        r"|^what did (?:the )?(?:job hunt|hunt|job search) (?:do|get done) "
        r"(?:last night|overnight|tonight|while i (?:was asleep|slept|was sleeping))$"
        r"|^what happened (?:overnight|last night|tonight|while i (?:was asleep|slept|was sleeping|was out))$"
        r"|^what did (?:you|u) (?:do|get done) (?:overnight|last night|while i (?:was asleep|slept|was sleeping))$"
        r"|^(?:did )?anything (?:happen )?(?:overnight|last night|while i (?:was asleep|slept))$"
        r"|^how (?:did|was) (?:the night|last night|overnight)(?: go)?$")),
    # "When did you last update" was answered by her own model from the
    # journal ("no record of that") - git and `running.version` know.
    # THE CLOCK ELSEWHERE AND THE CALENDAR AHEAD (2026-09-23 night sweep):
    # "what time is it in Tokyo" and "what's the date next Friday" each
    # waited on a model for arithmetic.
    ("time_in", re.compile(
        r"^what(?:'s| is|s)? the time (?:in|at) (?P<time_in>[a-z][a-z .'-]{1,40}?)(?: right now| now)?\s*\??$"
        r"|^what time is it (?:in|at|over in) (?P<time_in2>[a-z][a-z .'-]{1,40}?)(?: right now| now)?\s*\??$"
        r"|^(?:what(?:'s| is) the )?(?:current |local )?time in (?P<time_in3>[a-z][a-z .'-]{1,40}?)\s*\??$")),
    ("date_of", re.compile(
        r"^what(?:'s| is|s)? the date (?:on |for )?(?:next |this |of )?(?!(?:today|tomorrow|yesterday|now)\b)(?P<date_of>[a-z][a-z ']{2,30}?)\s*\??$"
        r"|^what date is (?:next |this )?(?P<date_of2>[a-z][a-z ']{2,30}?)\s*\??$"
        r"|^when(?:'s| is) (?:next |this )(?P<date_of3>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??$")),
    ("up_to_date", re.compile(
        r"^(?:are|is) (?:you|u|your code) (?:up to date|current|on the (?:latest|newest)(?: code)?)(?: right now| now)?$"
        r"|^(?:are|is) (?:you|u) (?:behind|running old code|out of date)$")),
    ("updated", re.compile(
        r"^when (?:did|were) (?:you|u) last (?:update|updated|upgrade|upgraded)(?: yourself)?$"
        r"|^when was your last update$")),
    # HIS DAY'S TWO ENDS AND ITS DOOR (2026-09-23): "morning thea" waited
    # 91 s on her own model; "I'm leaving for work" and "going to bed" were
    # planned as steps ("I will let you know when you're ready to go").
    ("good_morning", re.compile(
        r"^(?:good morning|morning|mornin'?|good morning thea|morning thea|hey good morning|"
        r"top of the morning|rise and shine)(?:,? thea)?(?: !)?$")),
    ("today", re.compile(
        r"^what (?:did|have) (?:you|u) (?:do|done)(?: today)?$"
        r"|^what (?:did|have) (?:you|u) (?:do|done|get done|been up to) while i was (?:out|gone|away|asleep|at work)$"
        r"|^what have (?:you|u) been doing$"
        r"|^what did (?:you|u) get done(?: today)?$"
        # A part of the day (2026-09-24, offline: "I can't think just now")
        r"|^what (?:did|have) (?:you|u) (?:do|done|get done|been doing) (?P<day_part>this morning|this afternoon|this evening|tonight|earlier|earlier today|so far today)$"
        # "Show me the journal" went to the planner, which compiled
        # `recall` and answered "I don't have anything remembered about
        # 'journal entries'" — a lookup in the wrong store.
        r"|^(?:show me |read me )?(?:the |your )?journal$"
        r"|^what(?:'s| is|s)? in (?:the |your )?journal$"
        # "Did I miss anything while I was out" is today's journal, and it
        # waited two minutes on her own model (2026-09-22).
        r"|^(?:did|have) i miss(?:ed)? anything(?: while i was (?:out|gone|away|asleep|at work|busy))?$"
        r"|^what(?: did|'d|d) i miss(?: while i was (?:out|gone|away|asleep|at work))?$"
        r"|^what happened while i was (?:out|gone|away|asleep|at work|busy)$"
        r"|^(?:did )?anything happen(?:ed)? while i was (?:out|gone|away|asleep|at work)$")),
    # "What did you send today" waited two minutes on her own model; the
    # applications she sent today are records, and she sends nothing else
    # without his yes on each.
    ("sent_today", re.compile(
        r"^what (?:did|have) (?:you|u) (?:send|sent)(?: out)?(?: today| so far today)?$"
        r"|^what (?:applications|apps|emails|messages) (?:did|have) (?:you|u) (?:send|sent)(?: out)?(?: today)?$"
        r"|^what went out today$|^(?:did|have) (?:you|u) (?:send|sent) anything(?: out)?(?: today)?$")),
    # "What did you do yesterday" is one journal read and she was paying a
    # round trip for it. "What did I ask you to do yesterday" is a
    # different store - his own words, journaled under `converse.ASKED_SUBJECT`
    # - and `asked_on` below answers it from there.
    ("yesterday", re.compile(
        r"^what (?:did|have) (?:you|u) (?:do|done|get done|been doing) yesterday$"
        r"|^what (?:did|have) (?:you|u) (?:do|done) last night$"
        r"|^what happened yesterday$")),
    # Eight seconds and a round trip for the clock she is holding.
    ("clock", re.compile(
        r"^what(?:'s| is|s)? the time( right now| now)?$"
        r"|^(?:do you know )?what time is it( right now| now)?$"
        r"|^(?:got|have) the time$|^time$")),
    ("date", re.compile(
        r"^what(?:'s| is|s)? (?:the |today'?s? )?date( today)?$"
        r"|^what day is it( today)?$|^what(?:'s| is|s)? today$"
        r"|^what day of the week is it$"
        # "what day is it tomorrow" went to a model (2026-09-24).
        r"|^what day (?:is it|will it be|is) (?P<date_ahead>tomorrow|the day after tomorrow)$"
        r"|^what(?:'s| is|s)? (?P<date_ahead2>tomorrow|the day after tomorrow)(?:'s date)?$")),
    # NOT folded into "date": that sentence is "Monday the 7th of
    # September", which contains no year and buries the month. Answering
    # "what year is it" with it was a confident answer to a question he
    # did not ask.
    ("month", re.compile(
        r"^what month is it( now)?$|^what(?:'s| is|s)? the month$"
        r"|^what month are we in$")),
    ("year", re.compile(
        r"^what year is it( now)?$|^what(?:'s| is|s)? the year$"
        r"|^what year are we in$")),
    # Five stores she was already holding and answering from a model.
    ("tasks", re.compile(
        r"^what(?:'s| is|s)? on my task list$|^what are my tasks$"
        r"|^what tasks do i have(?: left| open| to do)?$"
        r"|^how many tasks (?:do i have|are there|have i got)(?: left| open| remaining| to do)?$"
        r"|^how many (?:things|items|tasks) (?:are |have i got )?on my (?:task |to.?do )?list(?: left| open)?\s*\??$"
        r"|^what(?:'s| is|s)? left(?: on my list| to do)?$|^how many things (?:do i have )?(?:left )?to do$"
        r"|^(?:my )?task list$|^my tasks$"
        r"|^what(?:'s| is|s)? my next task$|^what(?:'s| is|s)? next$")),
    ("approvals", re.compile(
        r"^how many approvals are pending$|^what needs approving$"
        r"|^what(?:'s| is|s)? pending(?: approval)?$"
        r"|^(?:are there |any )?approvals(?: pending| waiting)?$"
        r"|^what am i approving$")),
    # "What can you do" is the question this whole registry exists to
    # answer, and it was the one question that went to a model to be
    # answered ABOUT the registry.
    # The counts, for the question the old "what can you do" answer was
    # really answering. He almost never asks this; when he does, he wants
    # the number and not the list.
    ("how_many", re.compile(
        r"^how many (?:things|capabilities|capabilitys) (?:can|could) "
        r"(?:you|u) do$"
        r"|^how many (?:things|capabilities) (?:do|have) (?:you|u) "
        r"(?:do|have|got)$"
        r"|^how many capabilities (?:are there|do you have)$")),
    ("capabilities", re.compile(
        r"^what can (?:you|u) do(?: for me)?$"
        r"|^what are (?:you|u) able to do$|^what are your capabilities$"
        r"|^what do (?:you|u) do$"
        # "help" paid a nine-second model round trip (2026-10-04) for the
        # answer this already gives from the registry.
        r"|^help(?: me)?\??$|^what can i (?:say|ask(?: you)?)\??$|^what should i say\??$")),
    # THE HONESTY QUESTION, answered from the registry with no model. With
    # every model down "what can't you do" came back "I can't think just
    # now" - the one question that must never need thinking.
    ("cannot", re.compile(
        r"^what (?:can'?t|cannot|can not|couldn'?t) (?:you|u)(?: do| handle| do yet)?(?: for me)?$"
        r"|^what are (?:you|u) (?:unable|not able) to do$"
        r"|^what (?:don'?t|doesn'?t) (?:you|u) (?:do|support|handle)(?: yet)?$"
        r"|^what(?:'s| is|s)? (?:still )?(?:missing|not built|not built yet|unavailable|not working)$"
        r"|^what (?:isn'?t|is not) (?:built|working|set up)(?: yet)?$"
        # "what are you bad at" was read as a project called "are you bad" (2026-10-05)
        r"|^what (?:are|r) (?:you|u) (?:bad|weak|not good|no good|worst|hopeless) at$"
        r"|^what do (?:you|u) struggle with$|^what(?:'s| are) your (?:weaknesses|weak spots|limits|limitations)$")),
    # HIS DAY, from the calendar mirror she already holds.
    ("agenda", re.compile(
        r"^what(?:'s| is|s)? on (?:my |the )?(?:calendar|schedule|agenda|plate)"
        r"(?: for)?(?: on| this)? (?P<day>today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^what (?:do i have|have i got|is there|am i doing) (?:on )?(?P<day2>today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^(?:my |the )?(?:calendar|schedule|agenda) (?:for )?(?P<day3>today|tomorrow|this week|next week)$"
        r"|^what(?:'s| is|s)? (?P<day4>today|tomorrow)(?:'s| like)?(?: looking like| look like)?$"
        r"|^(?:what(?:'s| is|s)? (?:on|happening|coming up)|anything (?:on|happening|coming up)|what have i got on"
        r"|what(?:'s| is|s)? (?:my|the) (?:week|day) (?:looking like|look like))"
        r"(?: for)? (?P<day5>today|tomorrow|this week|next week)$"
        r"|^what(?:'s| is|s)? (?:my|the) (?P<day6>week) (?:looking like|look like)$"
        # "What's my schedule this week" paid seven seconds of model for a
        # feed the shapes above already read (2026-09-22).
        r"|^what(?:'s| is|s)? (?:my |the )?(?:calendar|schedule|agenda) (?:for |like )?(?P<day7>today|tomorrow|this week|next week)"
        r"(?: like| looking like)?$"
        # "Show me my calendar for next week" planned for 73 s and died on a
        # date string; "what meetings do I have tomorrow" paid a model.
        r"|^(?:show me|pull up|open|read me|give me) (?:my |the )?(?:calendar|schedule|agenda)(?: for)? (?P<day8>today|tomorrow|this week|next week)$"
        r"|^what (?:meetings|appointments|events|calls) (?:do i have|have i got|are there)(?: on)? (?P<day9>today|tomorrow|this week|next week)$"
        # "do I have anything on sunday" went looking for a FILE called that (2026-10-05)
        r"|^(?:do i have|have i got|is there|is there) anything(?: on| for| happening)? (?P<day10>today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??$")),
    # Four questions about the calendar itself (2026-10-05, each a model):
    # the weekend, which day a date is, the week number, a leap year, and
    # when the clocks change.
    ("weekend", re.compile(
        r"^(?:am i free|what(?:'s| is|s)? (?:on|happening)|do i have anything(?: on)?|what am i doing|anything (?:on|happening)|is there anything(?: on)?|what have i got(?: on)?)"
        r"(?: for)? this weekend\s*\??$"
        r"|^what(?:'s| is|s)? my weekend (?:look like|looking like)\s*\??$")),
    ("what_day", re.compile(
        r"^what day(?: of the week)? (?:is|does|will|falls?) (?:the )?(?P<what_day>(?!(?:it|that|this|today|tomorrow)\b)[a-z0-9][a-z0-9' ]{1,30}?)(?: fall on| land on| be(?: on)?)?\s*\??$"
        r"|^what day (?:of the week )?(?:is it|will it be) on (?:the )?(?P<what_day2>[a-z0-9][a-z0-9' ]{1,30}?)\s*\??$")),
    ("week_number", re.compile(
        r"^what week (?:is it|are we in|of the year is it|number is it)\s*\??$"
        r"|^what(?:'s| is|s)? the week number\s*\??$|^which week (?:is it|are we in|of the year is it)\s*\??$")),
    ("leap_year", re.compile(
        r"^is (?:it|this|this year|(?P<leap_year>\d{4})) a leap year\s*\??$"
        r"|^when(?:'s| is) the next leap year\s*\??$|^(?:was|is) (?P<leap_year2>\d{4}) a leap year\s*\??$")),
    ("dst", re.compile(
        r"^when (?:is|does|do|did|will) (?:the )?(?:daylight ?savings?(?: time)?|dst|(?:the )?clocks? (?:change|go back|go forward|spring forward|fall back))"
        r"(?: start| end| change| begin| happen)?\s*\??$"
        r"|^(?:do|when do|when will) (?:the )?clocks (?:change|go back|go forward)(?: this year| next)?\s*\??$"
        r"|^(?:is|are) (?:it|we) (?:on )?daylight ?savings?(?: time)?(?: now| right now)?\s*\??$")),
    ("repo_wrong", re.compile(
        r"^what(?:'s| is|s)? (?:wrong|broken|failing|up|going on|the matter) with (?:the |my )?(?P<repo_wrong>[a-z0-9][a-z0-9 _.-]{1,40}?)"
        r"(?: pipeline| repo| project| bot)?\s*\??$"
        # Not "what did I ask you to do today" (2026-10-05): that is his
        # own words, answered from them further down, and this swallowed
        # it as a repository called "i ask you to".
        r"|^what did (?:the |my )?(?P<repo_wrong2>(?!(?:i|you|u|we)\b)[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)? do (?:today|overnight|last night|this week)\s*\??$")),
    ("fleet_read_at", re.compile(
        r"^when (?:was|did) (?:the )?fleet (?:last )?(?:checked|read|looked at|scanned|updated|refreshed)(?: last)?\s*\??$"
        r"|^how (?:old|fresh|stale) is the fleet (?:reading|read|pulse)\s*\??$")),
    ("alerts", re.compile(
        r"^(?:are there |is there )?any(?:thing)? (?:alerts|broken|wrong|failing)$"
        r"|^any alerts$|^is anything broken$|^anything broken$"
        r"|^(?:which|what) (?:project|projects|repo|repos|one|ones) (?:has|have|is|are) (?:a fault|faults|red|broken|failing|down)\s*\??$"
        r"|^what(?:'s| is|s)? (?:broken|failing|wrong|red|down) (?:in|with|on|across) (?:the |my )?fleet$"
        r"|^is everything (?:ok|green|fine)$")),
    ("repos", re.compile(
        r"^how many (?:repos|repositories|projects) (?:are )?(?:you|u) (?:watching|watch|track|tracking|monitor|monitoring)$"
        r"|^how many (?:repos|repositories|projects) do (?:you|u) (?:watch|monitor|track|have)$"
        r"|^what repos (?:are )?(?:you|u) watching$"
        r"|^how many (?:repos|repositories|projects)(?: are (?:there|in the fleet))?$|^how (?:big|large) is the fleet$")),
    ("my_list", re.compile(r"^what(?:'s| is|s)? on (?:my|the) list$|^(?:read|show|tell) me (?:my|the) list$")),
    ("shopping", re.compile(
        r"^what(?:'s| is|s)? on my shopping list$"
        r"|^(?:my )?shopping list$|^what do i need (?:to buy|from the store|to get|at the store)$"
        r"|^what(?:'s| is|s)? on the shopping list$"
        # "what's my shopping list" went to a model, which DENIED the store
        # ("I don't have a shopping list for you ... if you've got one in a
        # file somewhere") a turn after the fast lane had read it (2026-10-04).
        r"|^what(?:'s| is|s)? my (?:shopping|grocery|groceries) list$"
        r"|^(?:read|show|tell) me (?:my |the )?(?:shopping|grocery|groceries) list$"
        # "how many things are on the list" paid a model (2026-10-05)
        r"|^how many (?:things|items)(?: are| do i have)? (?:on|in) (?:my |the )?(?:shopping |grocery )?list$"
        r"|^how (?:long|big) is (?:my |the )?(?:shopping |grocery )?list$"
        r"|^what(?:'s| is|s)? on (?:my |the )?(?:grocery|groceries) list$|^(?:my )?grocery list$"
        r"|^(?:what(?:'s| is|s)? )?(?:my |the )?shopping list\?$")),
    ("reply_rate", re.compile(
        r"^what(?:'s| is|s)? (?:my |the )?(?:reply|response|hit|answer) rate(?: on (?:my )?applications)?\??$"
        r"|^how many (?:replies|responses) have i (?:gotten|got|had|received)(?: this month| so far)?\??$"
        r"|^how many (?:employers|companies|people) (?:have )?(?:replied|responded|got back to me|wrote back)\??$"
        r"|^(?:is|are) anyone (?:replying|responding|getting back to me)\??$")),
    ("mail_watch", re.compile(
        r"^how often do (?:you|u) (?:check|read|look at|poll) (?:my )?(?:mail|email|e-mail|inbox)\??$"
        r"|^(?:are|r) (?:you|u) (?:watching|checking|reading|monitoring) (?:my )?(?:mail|email|e-mail|inbox)\??$"
        r"|^do (?:you|u) (?:check|watch|read) (?:my )?(?:mail|email|e-mail|inbox)(?: on your own| automatically)?\??$"
        r"|^when did (?:you|u) last (?:check|read) (?:my )?(?:mail|email|e-mail|inbox)\??$")),
    ("sunset", re.compile(
        r"^(?:what time (?:is|'s)|when(?:'s| is)) (?:the )?(?P<sun>sunset|sunrise|sundown|dawn|dusk)"
        r"(?: today| tonight| tomorrow)?\??$"
        r"|^(?:what time does|when does) the sun (?P<sun2>set|rise|go down|come up)(?: today| tonight| tomorrow)?\??$")),
    ("next_charge", re.compile(
        r"^what(?:'s| is|s)? (?:my )?next (?:charge|bill|renewal|payment)(?: due)?\??$"
        r"|^when(?:'s| is) (?:my )?next (?:charge|bill|renewal|payment)(?: due)?\??$"
        r"|^what(?:'s| is|s)? (?:charging|renewing|due) next\??$")),
    ("pay_for", re.compile(
        r"^how much (?:do|am|will) i pay(?:ing)? for (?:my |the )?(?P<pay_for>.+?)\??$"
        r"|^what (?:do|am) i pay(?:ing)? for (?:my |the )?(?P<pay_for2>.+?)\??$"
        r"|^what does (?:my |the )?(?P<pay_for3>.+?) cost (?:me )?(?:a month|per month|monthly)?\??$"
        r"|^how much (?:is|does) (?:my |the )?(?P<pay_for4>.+?) (?:subscription )?(?:cost(?:ing)?(?: me)?|a month|per month)\??$")),
    ("projects", re.compile(
        r"^what projects (?:are you|r u|are u) (?:carrying|working on|running|on|building)\??$"
        r"|^what projects (?:do you|do i|do we) have\??$|^which projects are you (?:carrying|working on|on)\??$"
        r"|^what are (?:my|the|your|our) projects\??$|^(?:list|name) (?:my |the |your )?projects$"
        r"|^what(?:'s| is|s)? on (?:the|your) (?:project )?(?:books|slate)\??$")),
    # "What is running" was wired into `voice` and NOT here, so SAYING it
    # was instant and TYPING it paid a full planner round trip for the
    # same answer out of the same store. Every door should give the same
    # one — that is the whole point of there being one answer.
    ("running", re.compile(
        r"^what(?:'s| is|s)? running(?: right now)?$"
        # "is thea awake" (2026-10-05: a model) - the running headline
        r"|^(?:are|r) (?:you|u) (?:awake|alive|up|on|running|there|around)(?: right now| now)?$"
        r"|^which parts are running$|^what parts (?:of you )?are running$"
        r"|^is anything running$|^what(?:'s| is|s)? on right now$"
        r"|^are (?:you|u) all running$"
        # THE HEALTH QUESTIONS, which is what this answer really is. Each
        # of these took a model round trip to be answered worse: "why is
        # your voice off" came back with an address and a port read out
        # loud, and a hundred words of hedging, while `running` had the
        # true answer in twenty milliseconds.
        r"|^is everything (?:running|working|up|on|alright)$"
        r"|^(?:is|are) (?:everything|all of you) (?:still )?(?:running|working)$"
        r"|^are (?:you|u) (?:fully )?(?:up|working|healthy)$"
        r"|^(?:is|are) (?:you|u) broken$"
        r"|^(?:what|how)(?:'s| is|s)? your (?:health|status)$"
        r"|^why (?:is|are) (?:your|the) (?:voice|microphone|mic|ears) off$"
        r"|^why (?:can'?t|cant) (?:you|u) hear me$"
        r"|^why (?:aren'?t|arent) (?:you|u) listening$"
        r"|^(?:is|are) (?:your|the) (?:voice|microphone|mic) (?:on|off)$")),
    # His own details, out of his own profile. She read them off his resume;
    # asking a model to recite them is a round trip to the wrong store.
    # "What code are you running" had no answer, and that is the question
    # this whole session started from: the Core had been up three days on
    # code ninety commits old, every part reported healthy, and nothing
    # anywhere said so.
    # 55ms spoken against ~25 SECONDS typed, for the same sentence off the
    # same feed. `quick` declined this on the belief that the calendar was
    # not connected; it is — an ICS feed, reporting "1 feed(s)
    # configured" — it is simply EMPTY, and "free all day" from a feed
    # that really says nothing is a correct answer rather than a guess.
    #
    # Only the whole-day forms. "Am I free at 3", "am I free this
    # afternoon" and "am I free for an hour" all take arguments this
    # cannot parse, and the planner is better at them than a regex.
    ("free", re.compile(
        r"^am i free(?: (?P<free>today|tomorrow))?$"
        # "Do I have anything tomorrow" (no "on") went to the FILE finder
        # (2026-09-24): "I could not find anything matching anything tomorrow".
        r"|^(?:do i|have i) (?:have|got) (?:anything|any plans|much|something)(?: on| planned| scheduled| going on)?"
        r"(?: (?P<free2>today|tomorrow))?$"
        r"|^is my (?P<free3>today|tomorrow) free$")),
    # Already computed every beat for the wall (`next_appointment`), and
    # it was paying a round trip to be read aloud. Deliberately without a
    # trailing clause: "what's my next meeting ABOUT" and "move my next
    # meeting" are different questions and belong to the planner.
    ("next_meeting", re.compile(
        r"^what(?:'s| is|s)? my next (?:meeting|appointment|event)$"
        r"|^what time(?:'s| is) my next (?:meeting|appointment|event)\??$"
        r"|^when am i next busy\??$|^what(?:'s| is|s)? (?:my )?next (?:thing )?on (?:my|the) calendar\??$"
        r"|^how long (?:until|till|before) my next (?:meeting|appointment|event)$"
        r"|^when(?:'s| is)? my next (?:meeting|appointment|event)$"
        r"|^do i have (?:any )?(?:meetings|appointments)(?: coming up| today)?$"
        r"|^what(?:'s| is|s)? (?:next |coming up )?on my calendar$"
        r"|^what(?:'s| is|s)? the next thing (?:on|in) my (?:calendar|schedule|day)\s*\??$"
        r"|^what(?:'s| is|s)? next (?:on|in) my (?:schedule|day)\s*\??$"
        r"|^(?:my )?next (?:meeting|appointment)$"
        r"|^what(?:'s| is|s)? my schedule(?: today)?$")),
    ("version", re.compile(
        r"^what version are (?:you|u)(?: on| running)?$|^which version are (?:you|u)(?: on)?$|^what build are (?:you|u)(?: on)?$|^what(?:'s| is) your build$"
        r"|^what code are (?:you|u) running$|^what(?:'s| is|s)? your version$"
        r"|^which (?:branch|commit) are (?:you|u) on$"
        r"|^are (?:you|u) (?:up to date|current|stale)$"
        r"|^are (?:you|u) running the latest code$")),
    # Three the machine itself can answer (2026-10-05, each a model turn):
    # the subscriptions total, what is left on a timer, memory by program.
    ("subscription_extreme", re.compile(
        r"^what(?:'s| is|s)? my (?P<extreme>biggest|most expensive|largest|priciest|dearest|cheapest|smallest|least expensive) subscription\s*\??$"
        r"|^which (?:subscription|one) (?:costs|is) (?:the )?(?P<extreme2>most|least)(?: a month| per month)?\s*\??$"
        r"|^what do i (?:spend|pay) (?:the )?(?P<extreme3>most|least) on\s*\??$")),
    ("subscription_spend", re.compile(
        r"^how much (?:do i|am i|do we) (?:spend|spending|pay|paying) (?:(?P<spend_per>a month|per month|monthly|every month|each month|a year|per year|yearly|annually|every year) )?(?:on|for) (?:my |all my )?subscriptions(?: (?P<spend_per2>a month|per month|monthly|every month|each month|a year|per year|yearly|annually|every year))?(?: in total| all together| altogether)?\s*\??$"
        r"|^what(?:'s| is|s)? my (?:monthly |total )?subscription (?:total|spend|bill|cost)(?: a month| per month)?\s*\??$"
        r"|^what do (?:my|the|all my) subscriptions (?:cost|add up to|come to|total)(?: me)?(?: (?P<spend_per3>a month|per month|each month|a year|per year|yearly|annually))?\s*\??$")),
    ("exchange", re.compile(
        r"^(?:how much is|what(?:'s| is|s)?|convert|change) (?:\$|€|£)?[\d.,]+ ?(?:dollars?|bucks|usd|euros?|pounds?|quid|gbp|eur|yen|cad|aud|pesos?|francs?) "
        r"(?:in|to|into|as) (?:euros?|dollars?|bucks|pounds?|quid|yen|gbp|eur|usd|cad|aud|pesos?|francs?)\s*\??$"
        r"|^what(?:'s| is|s)? the (?:exchange rate|rate) (?:for|of|between|from) .{3,40}$")),
    ("deadlines", re.compile(
        r"^(?:which|what) (?:tasks|things) have (?:deadlines|due dates|a deadline|a due date)\s*\??$|^what(?:'s| is|s)? got a deadline\s*\??$"
        r"|^what (?:are|r) my deadlines\s*\??$|^what deadlines (?:do i have|have i got|are there)\s*\??$|^(?:any|are there any) deadlines(?: coming up)?\s*\??$")),
    ("due_soonest", re.compile(
        r"^what(?:'s| is|s)? due (?:soonest|next|first|the soonest)\s*\??$|^what(?:'s| is|s)? (?:the|my) next deadline\s*\??$"
        r"|^what(?:'s| is|s)? (?:the|my) (?:nearest|closest|soonest) deadline\s*\??$|^when(?:'s| is) my next deadline\s*\??$")),
    ("finished", re.compile(
        r"^how many tasks (?:did|have) i (?:finish|finished|do|done|complete|completed|get done)(?: (?P<fin_when>today|yesterday|this week|so far today|this month))?\s*\??$"
        r"|^what (?:did|have) i (?:finish|finished|complete|completed|get done|tick off|ticked off|cross off|crossed off)(?: (?P<fin_when2>today|yesterday|this week|so far today|this month))?\s*\??$"
        r"|^what tasks (?:did|have) i (?:finish|finished|do|done|complete|completed)(?: (?P<fin_when3>today|yesterday|this week|this month))?\s*\??$"
        r"|^(?:did|have) i (?:finish|finished|complete|completed|get) anything(?: done)?(?: (?P<fin_when4>today|yesterday|this week|this month))?\s*\??$")),
    ("left_week", re.compile(
        r"^what(?:'s| is|s)? (?:left|remaining|still (?:left|open|to do)) (?P<left_when>this week|today|tomorrow|next week)\s*\??$"
        r"|^what do i (?:still )?have left (?P<left_when2>this week|today|tomorrow|next week)\s*\??$"
        r"|^what else (?:is there|do i have|have i got) (?P<left_when3>this week|today|tomorrow)\s*\??$")),
    ("second", re.compile(
        r"^what(?:'s| is|s)? (?:after that|next after that|second|the second (?:thing|one)|after the first(?: one)?)\s*\??$"
        r"|^(?:and )?(?:after that|then what|what then|what comes after that|and then)\s*\??$")),
    ("timers", re.compile(
        r"^how many timers (?:do i have|are (?:running|set|going|on)|have i got)\s*\??$"
        r"|^(?:what|which) timers (?:do i have|are (?:running|set|going|on)|have i got)\s*\??$"
        r"|^(?:list|show me|read me) (?:my |the )?timers\s*\??$|^(?:any|are there any) timers(?: running| set| going)?\s*\??$")),
    ("bored", re.compile(
        r"^i(?:'m| am) (?:so |really )?bored\s*\.?$|^entertain me\s*\.?$|^i(?:'ve| have) (?:got )?nothing to do\s*\.?$|^what should i do\s*\??$"
        r"|^give me something to do\s*\.?$")),
    ("timer_left", re.compile(
        r"^how (?:long|much time)(?: is|'s)? left on (?:the|my|that) timer\s*\??$"
        r"|^how long (?:until|till|before) (?:the|my) timer(?: goes off| is up| ends)?\s*\??$"
        r"|^(?:is there|do i have|have i got) a timer (?:running|going|set|on)\s*\??$"
        r"|^what(?:'s| is|s)? (?:left|remaining) on (?:the|my) timer\s*\??$"
        r"|^(?:what(?:'s| is)? the )?timer(?: status)?\s*\??$")),
    ("top_memory", re.compile(
        r"^what(?:'s| is|s)? (?:using|eating|hogging|taking)(?: up)? (?:the |my |all the |all my )?(?:most )?(?:memory|ram)\s*\??$"
        r"|^what(?:'s| is|s)? (?:using|eating|hogging|taking)(?: up)? (?:the )?most (?:memory|ram)\s*\??$"
        r"|^which (?:program|programs|app|apps|process|processes) (?:is|are) (?:using|eating|hogging|taking)(?: up)? (?:the |all the )?(?:most )?(?:memory|ram)\s*\??$")),
    # "How long have you been working" is the work session, if any (2026-10-05)
    ("working", re.compile(
        r"^how long have (?:you|u) been working(?: on (?:that|it|this))?\s*\??$"
        r"|^(?:are|r) (?:you|u) in a work session(?: right now)?\s*\??$|^(?:is|'s) there a work session (?:on|running|going)\s*\??$"
        r"|^how(?:'s| is) the work session (?:going|doing)\s*\??$")),
    # "What did you look up today" is the journal's research lines (2026-10-05: eight seconds)
    ("looked_up", re.compile(
        r"^what (?:did|have) (?:you|u) (?:look up|looked up|research|researched|search for|searched for|google|googled)(?: for me)?(?: today| so far today| tonight)?\s*\??$"
        r"|^(?:did|have) (?:you|u) (?:look|looked) anything up(?: today)?\s*\??$|^what (?:searches|lookups) (?:did|have) (?:you|u) (?:do|done|run)(?: today)?\s*\??$")),
    # The demand ledger is what he keeps asking for that she cannot do
    # (2026-10-05: "I don't have a tally", and sixteen seconds of a model
    # explaining it would have to build an index).
    ("demand", re.compile(
        r"^what do (?:you|u) (?:get|keep getting) asked (?:for )?(?:the )?most\s*\??$"
        r"|^what do (?:i|people|we) (?:keep )?ask(?:ing)? (?:you|u) for (?:that|which|and) (?:you|u) can'?t (?:do|handle)\s*\??$"
        r"|^what do i keep asking (?:you |u )?for\s*\??$|^what(?:'s| is|s)? (?:most )?in demand\s*\??$"
        r"|^what (?:should|do) (?:you|u) (?:need to )?build next\s*\??$|^what(?:'s| is|s)? (?:the )?demand ledger\s*\??$"
        r"|^what (?:are|r) (?:you|u) missing (?:that|which) i (?:keep )?(?:ask|asking|want|wanting)(?: for)?\s*\??$")),
    ("uptime", re.compile(
        r"^how long have (?:you|u) been (?:up|running|on|awake|going)$"
        r"|^how long have (?:you|u) been here$"
        r"|^how long has (?:the core|your core|thea|aletheia) been (?:up|running|on|going)(?: for)?\s*\??$"
        r"|^when did (?:you|u|the core) (?:start|start up|come up|last restart)\s*\??$"
        r"|^what(?:'s| is|s)? your uptime$|^uptime$")),
    # WHO SHE IS and WHAT WORKS WITHOUT A MODEL: two questions a person asks
    # a new assistant, both answered offline with "I can't think just now"
    # (2026-09-24). Neither needs thinking; both are facts about herself.
    # THE NEXT INTERVIEW, from her calendar store (2026-09-24, offline:
    # "I can't think just now").
    # "Who do you have numbers for" paid a model round trip (2026-10-05).
    ("contacts_all", re.compile(
        r"^who (?:do (?:you|u) have|have (?:you|u) got) (?:numbers|phone numbers|contacts|emails|addresses|details) for\s*\??$"
        r"|^(?:who|what contacts) (?:do i have|have i got) saved(?: with you)?\s*\??$"
        r"|^(?:list|read me|what are) my contacts\s*\??$|^who(?:'s| is) in my contacts\s*\??$")),
    ("interview_when", re.compile(
        r"^(?:what time|when) (?:is|'s) (?:my|the) (?:next )?interview(?: with [a-z0-9 .&'-]{1,40})?\s*\??$"
        # "What's my next interview" / "do I have any interviews coming up" (2026-10-05)
        r"|^what(?:'s| is|s)? my next interview\s*\??$"
        r"|^(?:do i have|are there|have i got) any interviews?(?: coming up| scheduled| booked| lined up)?\s*\??$"
        r"|^how (?:long|many days|many hours) (?:until|till|before) (?:my|the) (?:next )?interview\s*\??$"
        r"|^(?:do i have|is there) an interview (?:coming up|scheduled|booked)(?: today| tomorrow| this week)?\s*\??$"
        r"|^when(?:'s| is) my next interview\s*\??$")),
    # THE DAY AS SHE HOLDS IT: calendar, tasks, the hunt.
    ("plan_today", re.compile(
        r"^what(?:'s| is|s)? (?:the |my )?plan (?:for )?(?:today|this morning|this afternoon)\s*\??$"
        r"|^what(?:'s| is|s)? (?:on )?(?:for |the plan for )?today\s*\??$|^what (?:am i|are we) doing today\s*\??$"
        r"|^what(?:'s| is|s)? (?:my|the) day (?:look like|looking like)(?: today)?\s*\??$")),
    # A BARE YES OR NO with nothing pending went to the planner and, offline,
    # to "I could not plan that". With something pending the approve/deny
    # rules take it before this; here it is only ever the empty case.
    ("bare_yes_no", re.compile(
        # never "approve", "deny", "go ahead", "do it": those are verbs the
        # decision rules own, and real work is never claimed here
        # "ok", "sure", "fine", "yeah", "yep" are filler or television, left
        # alone (test_filler_and_nudges, test_she_says_nothing_to_the_television).
        r"^(?:no|yes)\s*[.!]?$")),
    # WHAT SHE CHANGED, LEARNED AND WROTE TODAY - three journal reads that
    # went to a model (fifth battery, 2026-09-24).
    ("changed_today", re.compile(
        r"^what (?:did|have) (?:you|u) (?:change|changed|update|updated|fix|fixed|repair|repaired)(?: today| on yourself| in your code)?\s*\??$"
        r"|^(?:did|have) (?:you|u) (?:change|update|changed|updated|fix|fixed) (?:anything|yourself|your code)(?: today)?\s*\??$")),
    ("learned_today", re.compile(
        r"^what (?:did|have) (?:you|u) (?:learn|learned|learnt|find out|figure out)(?: about me)?(?: today| so far)?\s*\??$"
        r"|^(?:did|have) (?:you|u) (?:learn|learned) anything(?: new)?(?: today)?\s*\??$")),
    ("last_written", re.compile(
        r"^(?:read me|read back|show me|what(?:'s| is|s)) (?:the )?last (?:thing|file|document|note) (?:you|u) (?:wrote|made|created|saved)\s*\??$"
        r"|^what (?:did|have) (?:you|u) (?:write|written)(?: today| lately| recently)?\s*\??$")),
    ("desktop_files", re.compile(
        r"^what(?:'s| is|s)? (?:files? (?:are|is) )?on my (?P<place>desktop|downloads|documents)(?: folder)?\s*\??$"
        r"|^what files (?:are|do i have) (?:on|in) (?:my )?(?P<place2>desktop|downloads|documents)(?: folder)?\s*\??$"
        r"|^(?:list|show me) (?:my )?(?P<place3>desktop|downloads|documents)(?: folder| files)?\s*\??$")),
    ("stuck", re.compile(
        r"^(?:are|r) (?:you|u) (?:stuck|blocked|held up|waiting on (?:something|anything))(?: right now| now)?\s*\??$"
        r"|^is (?:anything|something) (?:stuck|blocked|held up)\s*\??$"
        # "what's blocking you" and "why is nothing happening" each paid a
        # twelve-second model round trip (2026-10-04) to be told there was an
        # approval waiting "but I can't see what it is" - the stores say.
        r"|^what(?:'s| is|s)? (?:blocking|stopping|holding) (?:you|u)(?: up)?\s*\??$"
        r"|^why (?:is|isn't|isnt) (?:nothing|anything) happening\s*\??$"
        r"|^why (?:aren't|arent|are) (?:you|u) (?:not )?doing anything\s*\??$"
        r"|^what are (?:you|u) waiting (?:on|for)\s*\??$")),
    ("who_are_you", re.compile(
        r"^(?:who|what) (?:are|r) (?:you|u)(?: exactly| anyway)?\s*\??$"
        r"|^what(?:'s| is|s) your name\s*\??$|^introduce yourself\s*\.?$|^tell me about yourself\s*\.?$"
        # "who am I talking to", "are you an AI", "why are you called Thea" (2026-10-05: a model each)
        r"|^who am i (?:talking|speaking|chatting) (?:to|with)\s*\??$|^who is this\s*\??$|^who(?:'s| is) there\s*\??$"
        r"|^(?:are|r) (?:you|u) (?P<are_you>an? ai|an? robot|an? bot|human|an? human|real|an? person|an? real person|a machine|alive|"
        r"chatgpt|chat gpt|claude|siri|alexa|google|a model|an llm|an? computer)\s*\??$"
        r"|^(?P<why_thea>why (?:are|r) (?:you|u) (?:called|named) (?:thea|aletheia)|why (?:thea|aletheia)|what does (?:thea|aletheia) mean|"
        r"what(?:'s| is) (?:thea|aletheia) short for|where does your name come from|who named (?:you|u))\s*\??$")),
    ("halt_means", re.compile(
        r"^what (?:happens|does it mean|would happen|does that do) (?:if|when) i say (?:halt|stop|the kill switch)\s*\??$"
        r"|^what does (?:halt|the kill switch|stop) (?:do|mean)\s*\??$|^what(?:'s| is) (?:the )?(?:halt|kill switch)(?: for)?\s*\??$"
        r"|^how do i (?:stop|halt) (?:you|u)(?: completely| entirely)?\s*\??$|^(?:is there|do (?:you|u) have) (?:a |an )?(?:kill switch|off switch|emergency stop)\s*\??$")),
    ("never_do", re.compile(
        r"^what (?:would|will|do) (?:you|u) never do\s*\??$|^what (?:won't|will not|wont) (?:you|u) (?:ever )?do(?: no matter what)?\s*\??$"
        r"|^what are your (?:limits|rules|red lines|hard limits|boundaries)\s*\??$|^what(?:'s| is) off limits(?: for you)?\s*\??$"
        r"|^(?:is there|are there) (?:anything|things) (?:you|u) (?:won't|will not|never) do\s*\??$")),
    ("record_me", re.compile(
        r"^(?:do|are) (?:you|u) (?:record|recording|listen to|listening to|spy on|spying on|watch|watching|taping) me(?: all the time| right now)?\s*\??$"
        r"|^(?:are|r) (?:you|u) always listening\s*\??$|^(?:do|does) (?:you|u) keep (?:my voice|recordings|audio|what i say)\s*\??$"
        r"|^is the mic(?:rophone)? (?:always )?on\s*\??$")),
    ("unattended_allowed", re.compile(
        r"^what (?:are|r) (?:you|u) allowed to do (?:without|before) asking(?: me)?\s*\??$|^what do (?:you|u) do on your own\s*\??$"
        r"|^what (?:can|do) (?:you|u) do (?:on your own|by yourself|without (?:my|an) (?:ok|approval|permission|yes))\s*\??$"
        r"|^what (?:kinds? of things? )?(?:needs|requires) my (?:approval|permission)(?: and what (?:doesn't|does not))?\s*\??$|^what (?:doesn't|does not|doesnt) need my (?:approval|permission|ok|yes)\s*\??$")),
    ("allowed_to", re.compile(
        r"^(?:are|r) (?:you|u) (?:allowed|permitted|cleared) to (?P<allowed>.{3,60}?)\s*\??$"
        r"|^(?:do|does) (?:you|u) have permission to (?P<allowed2>.{3,60}?)\s*\??$"
        r"|^(?:can|could) (?:you|u) (?P<allowed3>.{3,60}?) without (?:asking|my (?:ok|approval|permission|yes))\s*\??$")),
    ("offline_can", re.compile(
        r"^what (?:can|do) (?:you|u) (?:still )?do (?:offline|without (?:the )?(?:internet|a model|the big models|claude|wifi))\s*\??$"
        r"|^what (?:still )?works (?:offline|without (?:the )?(?:internet|a model|the big models|claude))\s*\??$"
        r"|^(?:can|do) (?:you|u) (?:still )?work (?:offline|without (?:the )?(?:internet|a model|the big models|claude))\s*\??$")),
    # A greeting is not small talk to something that can see his day. It
    # cost 25-80 seconds to be greeted back, and the answer to "hey" that
    # is worth saying is what is waiting on him.
    # THE WEATHER. In `quick` rather than the grammar because it is a
    # read she can do from a cache in a hundredth of a second, which is
    # what this lane is for — and it means the most ordinary question
    # anybody asks never touches a model.
    ("weather", re.compile(
        r"^(?:what(?:'s| is|s)? (?:the )?weather(?: like| looking like| doing| going to be like)?(?: out(?:side)?)?"
        r"|how(?:'s| is) the weather(?: looking)?(?: out(?:side)?)?|what(?:'s| is|s)? it like out(?:side)?"
        r"|how(?:'s| is) it (?:looking )?out(?:side)?|is it (?:nice|cold|hot|warm) out(?:side)?)"
        r"(?: (?P<weather>today|tonight|tomorrow|this (?:morning|afternoon|evening)"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$"
        r"|^(?:is|will) it (?:going to )?(?:rain|snow) (?P<weather2>today|tonight|tomorrow)$"
        r"|^weather(?: (?P<weather3>today|tonight|tomorrow))?$")),
    ("greeting", re.compile(
        r"^(?:hi|hello|hey|yo|hiya|howdy|hey there|hi there|hello there|hi thea|hello thea|hey thea|what'?s good|good day)$"
        r"|^good (?:morning|afternoon|evening)$"
        r"|^how (?:are|r) (?:you|u)(?: doing| today)?$"
        r"|^how (?:you|u) doing$|^how goes it$")),
    # Coming and going. "I'm home" and "goodnight" went to the PLANNER and,
    # with nothing thinking, came back "I could not plan that".
    ("arrival", re.compile(
        r"^(?:i'?m|im|i am) (?:home|back|here|in)(?: now)?$|^(?:just )?got (?:home|back|in)$")),
    ("farewell", re.compile(
        # "Going to bed" and "I'm leaving for work" were planned as steps
        # ("I will let you know when you're ready to go", 2026-09-23).
        r"^(?P<night>good ?night|night night|sleep well|(?:i'?m |im |i am )?(?:going to|off to|heading to) (?:bed|sleep)"
        r"|turning in|see you tomorrow|talk tomorrow)(?:,? thea)?(?: now)?$"
        r"|^(?:(?:i'?m|im|i am) )?(?:leaving|heading out|heading off|going out|off|out|off to work|going to work|"
        r"heading to work|leaving for work|back later|be back later)(?: now| for work| for the day| for a bit)?$"
        r"|^(?:see (?:you|ya)(?: later)?|bye|goodbye|later|talk later|catch you later)$")),
    # Replies from employers, from the application records.
    ("replies", re.compile(
        r"^(?:did|have) i (?:get|got|gotten|receive|received|hear) (?:any |anything )?(?:replies|responses|"
        r"back|any(?:thing)? back)(?: yet| today| from anyone)?$"
        r"|^any (?:replies|responses|word|news)(?: from (?:employers|anyone|the jobs))?(?: yet| today| overnight| last night| this morning)?$"
        r"|^(?:anything|any word|any news|anything new) from (?:the )?(?:employers|recruiters|companies|jobs)"
        r"(?: yet| today| overnight| this morning)?$"
        r"|^did any (?:employers?|companies|recruiters) (?:reply|write back|get back|respond)(?: to me)?(?: yet)?$"
        # "did anything come back from employers" went to the inbox, which is
        # not set up, instead of the records (2026-10-05).
        r"|^(?:did|has) (?:anything|anyone|anybody) (?:come|came|get|got|gotten) back(?: to me)?(?: from (?:the )?(?:employers|companies|recruiters|jobs|anyone))?(?: yet| today)?$"
        r"|^anything (?:come|came) back(?: from (?:the )?(?:employers|companies|recruiters|jobs))?(?: yet| today)?$"
        r"|^(?:has|did) anyone (?:replied|reply|written back|write back|got back|get back)(?: to me)?(?: yet)?$"
        # "Which jobs have replied" / "who wrote back" waited two minutes on
        # her own model with every frontier off (2026-09-22); the answer is
        # the application records.
        r"|^(?:which|what) (?:jobs|applications|apps|companies|employers|places) (?:have |has )?"
        r"(?:replied|written back|wrote back|got back|responded|gotten back)(?: to me)?(?: yet| so far)?$"
        r"|^who (?:has |have )?(?:replied|written back|wrote back|got back|responded)(?: to me)?(?: yet| so far)?$"
        r"|^(?:any|anyone|has anybody|any employers?) (?:written|wrote|got|gotten) back(?: to me)?(?: yet)?$")),
    # Why she is slow is a question about who is thinking.
    ("slow", re.compile(
        r"^why (?:are|r) (?:you|u) (?:so |being )?slow(?: today| right now)?$"
        r"|^why (?:is|does) (?:this|it|everything) (?:take|taking) so long$"
        r"|^what(?:'s| is) taking so long$|^who(?:'s| is) (?:thinking|answering)(?: right now)?$"
        r"|^(?:are|r) (?:you|u) (?:using|on) (?:your own|the local) (?:model|brain)$"
        # Who is thinking is a fact she holds; asked with every frontier off,
        # her own model said "Sonnet 5" and "I'm running on Claude right now
        # - nothing's down" (2026-09-22). The line is the brains line.
        r"|^(?:which|what) (?:model|brain|ai) (?:are|r) (?:you|u) (?:using|on|running(?: on)?)(?: right now)?$"
        r"|^(?:are|r) (?:you|u) (?:on|using|running on) (?:claude|chatgpt|codex|gpt|the big models?|your own model)(?: right now)?$"
        r"|^(?:are|r) the big models (?:out|down|back|up|available|working)(?: right now| yet)?$"
        r"|^(?:is|are) (?:claude|chatgpt|codex|the big models?) (?:out|down|back|up|available|resting|working)(?: right now| yet)?$"
        r"|^when (?:will|is|does|do) (?:claude|chatgpt|codex|the big models?) (?:be )?(?:back|reset|available|up)(?: again)?$"
        r"|^is your own model (?:running|up|on|working|ready)$"
        r"|^how long (?:until|till|before) (?:you|u) can think (?:properly|normally|again|with the big models)(?: again)?$")),
    # Sums he would otherwise wait a minute for.
    # "What standing permissions do you have" paid a model (2026-10-05), and
    # "give yourself standing permission" is answered with where it is granted.
    ("standing", re.compile(
        r"^what (?:standing )?(?:permissions?|grants?|authority|authorit(?:y|ies)) (?:do (?:you|u) have|have (?:you|u) got|are (?:on|active|live))(?: right now)?\s*\??$"
        r"|^what can (?:you|u) do without (?:asking(?: me)?|my (?:ok|okay|approval|permission|say-so))\s*\??$"
        r"|^(?:do (?:you|u) have|have (?:you|u) got) (?:any )?standing (?:permission|authority|grants?)(?: for (?P<standing_for>.+?))?\s*\??$"
        r"|^(?:what(?:'s| is)|is there) (?:a )?standing (?:permission|authority|grant)(?: for (?P<standing_for2>.+?))?\s*\??$"
        r"|^(?:give|grant) yourself (?:standing )?(?:permission|authority|a grant)(?: (?:for|to|over) (?P<standing_for3>.+?))?\s*\??$"
        r"|^(?:how do i|can i) (?:give|grant) (?:you|u) (?:standing )?(?:permission|authority)(?: (?:for|to|over) (?P<standing_for4>.+?))?\s*\??$")),
    ("math", re.compile(
        r"^(?:what(?:'s| is|s)?|how much is) (?P<pct>[\d.]+) ?(?:%|percent) of (?:\$)?(?P<of>[\d.,]+)(?P<pct_money> dollars| bucks)?$"
        # "whats 10 percent tip on 46" (2026-10-05: refused as spending)
        r"|^(?:what(?:'s| is|s)? )?(?:a |the )?(?P<tip>[\d.]+) ?(?:%|percent) tip (?:on|for) (?:a )?(?:\$)?(?P<tip_on>[\d.,]+)(?: dollars| bucks| bill| check)?$"
        r"|^(?:how much (?:is|should i tip|do i tip|to tip|should the tip be|would i tip)|what(?:'s| is|s)?) (?:a |the )?(?:tip )?on (?:a )?(?:\$)?(?P<tip_on2>[\d.,]+)(?: dollars| bucks| bill| check)?(?: at (?P<tip2>[\d.]+) ?(?:%|percent))?$"
        # "15 percent off 80", "a third of 90", "double 45", "how many ounces in a pound" (2026-10-05)
        r"|^what(?:'s| is|s)? (?P<pct_off>[\d.]+) ?(?:%|percent) off (?:of )?(?:\$)?(?P<off>[\d.,]+)(?P<off_money> dollars| bucks)?$"
        r"|^what(?:'s| is|s)? (?:a |one )?(?P<frac>half|third|quarter|fifth|tenth|two thirds|three quarters) of (?:\$)?(?P<frac_of>[\d.,]+)(?P<frac_money> dollars| bucks)?$"
        r"|^(?:what(?:'s| is|s)? )?(?P<mult>double|triple|half|twice) (?:of )?(?:\$)?(?P<mult_of>[\d.,]+)(?P<mult_money> dollars| bucks)?$"
        r"|^how many (?P<unit_small>ounces|oz|inches|feet|yards|centimeters|centimetres|millimeters|millimetres|grams|milliliters|millilitres|cups|tablespoons|teaspoons|quarts|pints|fluid ounces|seconds|minutes|hours|days|weeks|months) (?:are |is )?(?:in|to|per|make) (?:a|an|one|1) (?P<unit_big>pound|foot|yard|mile|meter|metre|kilometer|kilometre|inch|kilogram|kilo|liter|litre|cup|quart|gallon|pint|tablespoon|minute|hour|day|week|year|month)$"
        r"|^(?:what(?:'s| is|s)? )?(?P<a>[\d.,]+) (?P<op>plus|minus|times|divided by|over|x|\+|-|\*|/) (?P<b>[\d.,]+)$"
        # "split 120 three ways" (2026-10-05: a model, seven seconds, for a division)
        r"|^(?:split|divide|share) (?:\$)?(?P<split>[\d.,]+)(?P<split_money> dollars| bucks)? (?:by |into |between |among |across )?(?P<ways>\d+|two|three|four|five|six|seven|eight|nine|ten)(?: ways| people| of us| persons| each)?$"
        r"|^(?:convert |what(?:'s| is|s)? )?(?P<n>[\d.,]+) (?P<from>miles?|km|kilometers?|kilometres?|pounds?|lbs?|"
        r"kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c)"
        r" (?:to|in|into) (?P<to>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|"
        r"meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c)$"
        # THE OTHER WORD ORDER: "how many miles is 10 km", "how many pounds in 5 kg"
        r"|^how many (?P<to2>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c) (?:is|are|in|make|equals?|to) (?P<n2>[\d.,]+|a|an|one) ?(?P<from2>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c)$")),
    # "What salary are you asking for" and "am I willing to relocate" each
    # went elsewhere (2026-10-05: a model; the steering list).
    ("asking_pay", re.compile(
        r"^what (?:salary|pay|number|figure) (?:are|r) (?:you|u|we) (?:asking|asking for|quoting|putting down|going in with)(?: for me)?\s*\??$"
        r"|^what (?:are|r) (?:you|u|we) asking for(?: salary| pay)?(?: wise)?\s*\??$"
        r"|^what(?:'s| is|s)? (?:my|the) (?:salary|pay) (?:ask|number|figure)\s*\??$")),
    ("relocate", re.compile(
        r"^(?:am i|would i|will i|do i want to|am i (?:willing|happy|prepared|open) to|would i be (?:willing|happy|prepared|open) to) (?:relocate|move)(?: for (?:a|the) job| for work)?\s*\??$"
        r"|^(?:what(?:'s| is|s)? my|what did i say about) (?:relocation|relocating|moving)(?: stance| answer| preference)?\s*\??$")),
    ("birthday", re.compile(
        r"^(?:when(?:'s| is)|what(?:'s| is)|what day is|what date is) my (?:birthday|birth date|date of birth|bday)\s*\??$"
        r"|^(?:do you know|do you remember) (?:when )?my birthday(?: is)?\s*\??$")),
    ("age", re.compile(
        r"^how old am i\s*\??$|^what(?:'s| is) my age\s*\??$|^what age am i\s*\??$|^do you know how old i am\s*\??$"
        r"|^how old (?:will i be|am i turning|do i turn)(?: this year| next birthday| on my birthday)?\s*\??$")),
    ("mine", re.compile(
        r"^what(?:'s| is|s)? my (?P<mine>email(?: address)?|phone(?: number)?"
        r"|number|city|town|name|first name|last name|full name"
        r"|minimum salary|salary(?: floor| requirement| expectation| expectations)?|desired (?:pay|salary)"
        r"|asking (?:pay|salary|price)|pay(?: expectation| expectations)?|notice period|start date"
        r"|zip(?: code)?|post ?code|postal code|employer|company|workplace|job title|title|role|job|state|country"
        r"|linkedin|github|website|pronouns|school|degree|years of experience)$"
        # "where do I work", "do you know my name" (2026-10-05: a model; "I have nothing about name on file")
        r"|^(?:where do i work|who do i work for|what company do i work (?:for|at)|who(?:'s| is) my (?P<mine2>employer))\s*\??$"
        r"|^what do i do(?: for (?:a living|work))?\s*\??$|^what(?:'s| is) my (?P<mine4>job)\s*\??$"
        r"|^(?:do you know|do you remember) (?:my (?P<mine3>name|email|phone number|address|city|employer|job title|zip)|who i am|what my name is)\s*\??$"
        r"|^who am i$")),
    # WHAT SHE HUNTS FOR (2026-09-23 night sweep): "what roles are you looking
    # for", "what are you applying to" and "what's my minimum salary" each
    # waited on a model for stores she holds.
    ("hunting_for", re.compile(
        r"^what (?:roles|jobs|titles|kind of (?:jobs|roles|work|positions)|positions) (?:are (?:you|u)|r u|are we|am i) "
        r"(?:looking for|hunting for|searching for|applying (?:to|for)|going after|after|targeting)(?: for me)?\s*\??$"
        r"|^what are (?:you|u|we) applying (?:to|for)(?: right now| these days)?\s*\??$"
        r"|^what(?:'s| is) the (?:job )?(?:search|hunt) (?:for|looking for|after)\s*\??$")),
    ("work_wants", re.compile(
        r"^what (?:kind of |sort of )?(?:work|jobs) (?:do i|don't i|do i not|won't i|will i not) (?:want|do|take)(?: to do)?\s*\??$"
        r"|^what (?:have i|did i) (?:told|tell) (?:you|u) (?:i|that i) (?:want|don't want|do not want|won't do|will not do)\s*\??$"
        r"|^what (?:am i|are we|are you) not applying (?:to|for)\s*\??$"
        r"|^what(?:'s| is) off the table\s*\??$"
        # "what have I told you not to apply to" (2026-10-05)
        r"|^what (?:have i|did i) (?:told|tell|asked|ask) (?:you|u) (?:not to|to not|to never|never to) (?:apply (?:to|for)|do|take)\s*\??$"
        r"|^what (?:am i|are (?:you|u|we)) (?:avoiding|skipping|leaving out|not going for|steering clear of)\s*\??$")),
    # "What's the best job you found today" is the discovery summary's
    # standouts (2026-10-05: a model, "tell me what kind of role").
    ("best_found", re.compile(
        r"^what(?:'s| is|s|'s been)? the best (?:job|one|opening|role|position) (?:you|u)(?:'ve| have)? (?:found|saw|seen|came across|turned up)(?: today| so far| this week)?\s*\??$"
        r"|^(?:what|which) (?:jobs|openings|ones|roles) (?:stood out|stand out|looked good|look good)(?: today)?\s*\??$"
        r"|^any (?:good|standout|great) (?:jobs|ones|openings|roles)(?: today| so far)?\s*\??$"
        r"|^what did (?:you|u) find today\s*\??$")),
    # "What's Barkly up to" / "whose turn is it on Barkly" is a charter by
    # the name he calls it (2026-10-05: a model, "I don't know what Barkly is").
    ("project_of", re.compile(
        r"^what(?:'s| is) (?:the |my )?(?P<project_of>(?!(?:the|my|a|an|are|is|do|did|were|was|am|can|could|will|would|should|he|she|it|you|u|i|we|they|cpu|processor|memory|ram|disk|battery|weather|time|clock|market|date|temperature|forecast|fleet|core|hunt|job hunt|search|wifi|network|internet)\b)[a-z0-9][a-z0-9 '-]{1,40}?)(?: project)? (?:up to|doing|at|looking like)(?: now| today| these days)?\s*\??$"
        r"|^(?:where (?:are we|am i|is it)|how far along (?:are we|is it)) (?:on|with) (?:the |my )?(?P<project_of2>[a-z0-9][a-z0-9 '-]{1,40}?)(?: project)?\s*\??$"
        r"|^whose (?:turn|move|go) (?:is it )?(?:on|for|with) (?:the |my )?(?P<project_turn>[a-z0-9][a-z0-9 '-]{1,40}?)(?: project)?\s*\??$"
        r"|^what(?:'s| is|s)? (?:the )?next (?:step|move) (?:on|for|with) (?:the |my )?(?P<project_of3>[a-z0-9][a-z0-9 '-]{1,40}?)(?: project)?\s*\??$")),
    # "What's my resume say" (2026-10-05: a model, "tell me which file it is").
    ("resume_says", re.compile(
        r"^what(?:'s| does| is)? (?:my |the )?(?:resume|cv) say\s*\??$"
        r"|^what(?:'s| is|s)? (?:on|in) (?:my |the )?(?:resume|cv)\s*\??$"
        r"|^(?:summarize|summarise|sum up|gist of) (?:my |the )?(?:resume|cv)(?: for me)?\s*\??$"
        r"|^(?:do (?:you|u) have|have (?:you|u) got|where(?:'s| is)) my (?:resume|cv)\s*\??$")),
    ("home", re.compile(
        r"^where do i live$|^what city do i live in$"
        r"|^what town do i live in$|^where(?:'s| is) home$")),
    # "where am I" is the city on file and an honest "I can't see where you are" (2026-10-05)
    ("where_am_i", re.compile(r"^where (?:am i|are we)(?: right now| now)?$|^what city (?:am i in|are we in)$")),
    # His clock and hers, and the clock elsewhere converted (2026-10-05: five
    # model turns for what zoneinfo knows).
    # HER OWN SURFACES. "How do I talk to you from my phone", "what's the
    # address of your page", "how do I see the wall", "what page do I open"
    # each paid a model that did not know (2026-10-05); the Core knows its
    # own address and the phone link is computed every beat for the QR.
    ("her_page", re.compile(
        r"^how (?:do|can|could) i (?:talk to|reach|open|get to|see|use) (?:you|u|your page|the page|the thea page|thea)(?: from (?:my )?phone| on my phone)?\s*\??$"
        r"|^what(?:'s| is|s)? (?:the )?(?:address|url|link) (?:of|for|to) (?:you|u|your page|the page|the thea page|thea|the wall|the command center)\s*\??$"
        r"|^what(?:'s| is|s)? your (?:address|url|link|page)\s*\??$|^what page do i open\s*\??$"
        r"|^(?:where(?:'s| is)|how do i (?:see|open|find|get to)) (?:the )?(?:wall|command center|thea page|page|qr|qr code)\s*\??$"
        r"|^(?:show me|where(?:'s| is)) (?:the|your) qr(?: code)?\s*\??$")),
    ("the_wall", re.compile(
        r"^what(?:'s| is|s)? on the wall\s*\??$|^what does the wall (?:show|say)\s*\??$|^read me the wall\s*\??$")),
    ("my_zone", re.compile(
        r"^what(?:'s| is|s)? (?:my|the) time ?zone(?: here)?\s*\??$|^what time ?zone am i (?:in|on)\s*\??$"
        r"|^what time ?zone (?:are|r) (?:you|u) (?:in|on|using|working in)\s*\??$|^what(?:'s| is) your time ?zone\s*\??$")),
    ("time_convert", re.compile(
        r"^what(?:'s| is|s)? (?P<conv_t>\d{1,2}(?::\d{2})? ?(?:am|pm)|noon|midnight)(?: my time| here| our time)? in (?P<conv_place>[a-z][a-z .'-]{1,40}?)\s*\??$"
        r"|^when it(?:'s| is) (?P<conv_t2>\d{1,2}(?::\d{2})? ?(?:am|pm)|noon|midnight) in (?P<conv_place2>[a-z][a-z .'-]{1,40}?),? what time is it (?:here|for me|my time)\s*\??$"
        r"|^what time is (?P<conv_t3>\d{1,2}(?::\d{2})? ?(?:am|pm)|noon|midnight) in (?P<conv_place3>[a-z][a-z .'-]{1,40}?) (?:here|for me|my time)\s*\??$")),
    # Letters, chance and date arithmetic (2026-10-05: eight seconds to spell
    # a word, seven to flip a coin, six for "how many days since January 1").
    ("spell", re.compile(r"^(?:spell|how do (?:you|u) spell|how is .* spelled)(?: the word)? (?P<spell>[a-z][a-z'-]{1,40})(?: for me)?\s*\??$")),
    ("chance", re.compile(
        r"^(?P<coin>flip a coin|toss a coin|heads or tails|coin flip)\s*\??$"
        r"|^(?:roll (?:a |the |one )?(?P<die>die|dice|d6)|roll (?P<dice_n>two|2|three|3) dice)\s*\??$"
        r"|^(?:pick|choose|give me|say) (?:a )?(?:random )?number (?:between|from) (?P<lo>\d+) (?:and|to) (?P<hi>\d+)\s*\??$"
        r"|^(?:random number|pick a number|give me a number)\s*\??$")),
    ("date_math", re.compile(
        r"^what(?:'s| is|s)? the date (?:in|after) (?P<ahead_n>\d+) (?P<ahead_unit>days?|weeks?)(?: from now| from today)?\s*\??$"
        r"|^what(?:'s| is|s)? (?:the date |the day |it )?(?P<ahead_n2>\d+) (?P<ahead_unit2>days?|weeks?) from (?:now|today)\s*\??$"
        r"|^what (?:day|date) (?:was it|was) (?P<ago_n>\d+) (?P<ago_unit>days?|weeks?) ago\s*\??$"
        r"|^how many days (?:since|from|have passed since|has it been since) (?P<since>[a-z0-9][a-z0-9 ']{2,30}?)\s*\??$")),
    # WHAT HE TOLD HER, read back without a model (2026-09-23 night sweep:
    # "what's my landlord's name", "what did I tell you about the car",
    # "when is my lease up" and "what notes do you have" each waited on a
    # model for a store she holds).
    # The drafts she holds for his send (mail.draft held=True): his 2026-09-23
    # ruling lets her draft to his own inbox and not send, so "what have you
    # drafted" has to have an answer from the store.
    # OUTWARD MAIL IS ON HOLD (his 2026-09-24 ruling). "Are you sending
    # emails" waited 92 s on a model that could not answer and then said
    # "I could not plan that"; the answer is a file she holds.
    ("sending", re.compile(
        r"^(?:are|do|will|can) (?:you|u) (?:sending|send|going to send) (?:any |out )?(?:emails?|mail|messages)"
        r"(?: right now| now| yet| for me)?\s*\??$"
        # The hold-phrased shapes capture a word so the answer's first word
        # fits the question: "is the mail hold on" is "Yes", not "No" (2026-09-24).
        r"|^is (?:outward |outgoing )?(?:mail|email) (?P<hold_q>on hold|held|paused|stopped)\s*\??$"
        r"|^(?:are|is) (?:emails?|mail) (?P<hold_q2>on hold|held)\s*\??$"
        r"|^is (?:the )?(?:outward |outgoing )?(?:mail|email) hold (?:still )?(?P<hold_q3>on|off|lifted|up)\s*\??$"
        r"|^(?:are|is) (?:you|u) (?:still )?(?P<hold_q4>holding) (?:my |the )?(?:emails?|mail|drafts)\s*\??$")),
    # WHICH JOBS TODAY. "Which jobs did you apply to today" went to a model
    # for a list that is in her own records (92 s, then nothing); the
    # all-time list ("applied_to", above) did not know the day words.
    ("applied_on", re.compile(
        r"^(?:which|what) (?:jobs|applications|companies|employers|roles|positions) (?:did|have) (?:you|u|we) "
        r"(?:apply|applied)(?: to| for)?(?: for me)? (?P<applied_on>today|yesterday|so far today|tonight)\s*\??$"
        r"|^(?:who|where|what) (?:did|have) (?:you|u|we) (?:apply|applied)(?: to| for)?(?: for me)? (?P<applied_on2>today|yesterday|tonight)\s*\??$"
        r"|^(?:list|show me|read me) (?P<applied_on3>today'?s?|yesterday'?s?) (?:applications|jobs)\s*\??$")),
    # WHAT HE ASKED, by day, from the journal of his own words
    # (`converse.ASKED_SUBJECT`). Offline it was "I can't think just now".
    # "What's due this week" is his task list and his reminders against the
    # clock, and it paid a model round trip (2026-10-05).
    ("due_week", re.compile(
        r"^what(?:'s| is|s)? (?:due|coming up|on|on my plate|on the list) (?P<due_when>this week|today|tomorrow|next week)\s*\??$"
        r"|^what do i have (?:due |coming up |on )?(?P<due_when2>this week|today|tomorrow|next week)\s*\??$"
        r"|^(?:is )?anything due (?P<due_when3>this week|today|tomorrow|next week)\s*\??$"
        r"|^what(?:'s| is|s)? (?:due|coming up)\s*\??$")),
    ("asked_on", re.compile(
        r"^what (?:did|have) i (?:ask|asked|tell|told|say to|said to) (?:you|u)(?: to do| for| about)?"
        r" (?P<asked_on>yesterday|today|this morning|last night|earlier|earlier today|so far today)\s*\??$"
        r"|^what (?:did|have) i (?:ask|asked) (?:you|u) (?:for|to do) (?P<asked_on2>yesterday|today)\s*\??$"
        r"|^what (?:have|did) i (?:been asking|asked) (?:you|u) (?:for )?(?P<asked_on3>today|yesterday)\s*\??$"
        # "what did we talk about earlier" is the same store (bottom rung, 2026-09-24).
        r"|^what (?:did|have) we (?:talk|talked|chat|chatted) about (?P<asked_on4>earlier|today|yesterday|this morning|last night|so far today)\s*\??$"
        r"|^what (?:did|have) we (?:discuss|discussed|cover|covered) (?P<asked_on5>earlier|today|yesterday|this morning|last night)\s*\??$")),
    # HER OWN MACHINE. "How much memory do you have free" is a number she
    # can read in a millisecond, and it says which of her own models fits.
    ("memory_free", re.compile(
        r"^how much (?:memory|ram) (?:do (?:you|u) have|is|have (?:you|u) got) (?:free|left|available)\s*\??$"
        r"|^how much free (?:memory|ram) (?:do (?:you|u) have|is there)\s*\??$"
        r"|^how much (?:memory|ram) (?:are (?:you|u)|is (?:the pc|this pc|the computer|this machine)) (?:using|taking)\s*\??$"
        r"|^how much (?:memory|ram) is (?:in use|used|taken)\s*\??$"
        r"|^(?:what(?:'s| is)|how(?:'s| is)) (?:your|the) (?:free )?(?:memory|ram)(?: (?:situation|looking))?\s*\??$")),
    # WHAT IS USING THE CPU is a number this machine can read (psutil), not a
    # thought (bottom rung 2026-09-24: "I can't think just now").
    ("cpu", re.compile(
        r"^what(?:'s| is|s)? (?:using|eating|hogging|taking) (?:the |my |all the )?(?:cpu|processor)\s*\??$"
        r"|^(?:why is|why's) (?:the |my |this )?(?:pc|computer|machine) (?:so )?slow\s*\??$"
        r"|^how busy is (?:the |my |this )?(?:cpu|processor|pc|computer)\s*\??$"
        r"|^what(?:'s| is|s)? (?:the )?cpu (?:at|usage|load)\s*\??$")),
    ("drafts", re.compile(
        r"^(?:what|which)(?: emails?| notes?)? (?:have (?:you|u)|did (?:you|u)) draft(?:ed)?(?: for me)?\s*\??$"
        # "what did I draft", "did I draft anything" (2026-10-05: a model)
        r"|^what (?:did|have) i (?:draft|drafted|ask (?:you|u) to draft|get (?:you|u) to draft)(?: today| so far)?\s*\??$"
        r"|^did i draft anything\s*\??$|^(?:anything|what(?:'s| is)) drafted\s*\??$|^is there a draft(?: waiting)?\s*\??$"
        r"|^(?:any|what|list|show me|read me) (?:my |your |the )?drafts?(?: (?:do (?:you|u) have|do i have|have i got|are there|waiting|for me|held))?\s*\??$"
        r"|^what(?:'s| is|s) (?:in|on) (?:my |your |the )?drafts?\s*\??$"
        r"|^how many (?:emails? |drafts? )?(?:are |do (?:you|u) have )?(?:in|on|held in) (?:my |the |your )?drafts?(?: folder)?\s*\??$"
        r"|^how many drafts (?:do (?:you|u) have|are (?:there|held|waiting))\s*\??$"
        r"|^what are (?:you|u) drafting\s*\??$|^what have (?:you|u) (?:got )?drafted\s*\??$"
        r"|^what drafts are (?:you|u) holding\s*\??$|^(?:are|r) (?:you|u) holding any(?:thing| drafts| emails?)?\s*\??$"
        r"|^what are (?:you|u) holding(?: for me)?\s*\??$|^anything (?:held|on hold)\s*\??$"
        r"|^who have (?:you|u) drafted (?:to|for)(?: today)?\s*\??$|^what did (?:you|u) draft(?: today| so far)?\s*\??$")),
    # ONE DRAFT, read back: "read me the draft to Stripe" (bottom rung 2026-09-24).
    ("draft_to", re.compile(
        r"^(?:read me |read |show me |open )?(?:the |my |your )?draft (?:to|for) (?P<draft_to>[a-z0-9][a-z0-9 .&'-]{1,40}?)\s*\??$"
        r"|^what did (?:you|u) draft (?:to|for) (?P<draft_to2>[a-z0-9][a-z0-9 .&'-]{1,40}?)\s*\??$"
        r"|^what(?:'s| is|s)? in (?:the |my |your )?draft (?:to|for) (?P<draft_to3>[a-z0-9][a-z0-9 .&'-]{1,40}?)\s*\??$")),
    # HIS INTERVIEW WINDOW is a fact in her own store (offline 2026-09-24:
    # "I don't have your interview window on record" from a model, while
    # `interviews.status()` held 1 to 2:30 PM Central the whole time).
    ("interview_window", re.compile(
        r"^what(?:'s| is|s)? my interview (?:window|hours|times)\s*\??$"
        r"|^what are my interview (?:window|hours|times)\s*\??$|^when (?:can|do) i (?:do|take) interviews\s*\??$"
        r"|^what times? (?:is|are) my interview (?:window|hours|times)\s*\??$"
        r"|^what(?:'s| is) the interview (?:switch|booking) (?:set to|on|at)\s*\??$"
        r"|^(?:is|are) interview (?:booking|bookings) (?:on|off|switched on|switched off)\s*\??$"
        r"|^(?:are|will) (?:you|u) book(?:ing)? interviews(?: for me)?\s*\??$"
        r"|^when (?:can|do) i (?:do|take|have) interviews\s*\??$"
        r"|^what (?:hours|times) (?:are|do) (?:you|u) book(?:ing)? interviews(?: for| in)?\s*\??$")),
    # "Did the shorts pipeline run today" is the pulse's row for that repo,
    # the same reader "how's the trader" uses. Late in the table on purpose:
    # an application's "did the Stripe one go through" is claimed above.
    ("ran_today", re.compile(
        r"^(?:did|has) (?:the )?(?P<ran>[a-z0-9][a-z0-9 .'-]{1,40}?)(?: pipeline| workflow| repo| project)? "
        r"(?:run|ran|been run|build|built|go|gone)(?: today| yet| this morning| tonight| this week)?\s*\??$")),
    # "How many notes do I have" and "search my notes for car" each paid a
    # model (2026-10-05), and the second one DENIED the note.
    ("notes_count", re.compile(
        r"^how many notes (?:do i have|have i got|do (?:you|u) have|are there|have (?:you|u) got)(?: for me)?\s*\??$")),
    ("notes_search", re.compile(
        r"^(?:search|look through|look in|check|go through|grep) (?:my |your |the )?notes for (?:the |my )?(?P<notes_search>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        r"|^(?:find|is there|do i have|have i got) (?:a |any |anything )?(?:note|notes)? ?(?:about|on|mentioning|with) (?:the |my )?(?P<notes_search2>[a-z0-9][a-z0-9 '-]{1,40}?) in (?:my |your |the )?notes\s*\??$"
        r"|^(?:find|search for) (?:the |my )?(?P<notes_search3>[a-z0-9][a-z0-9 '-]{1,40}?) in (?:my |your |the )?notes\s*\??$")),
    ("notes_list", re.compile(
        r"^what notes do (?:you|u) have(?: for me)?$|^(?:list|read me|read back|show me) (?:my |your |the )?notes$"
        r"|^(?:my )?notes$"
        r"|^what (?:have|did) i (?:told|tell) (?:you|u)(?: to remember| to note)?\s*\??$|^what have (?:you|u) noted(?: down)?$"
        r"|^what (?:have|did) i (?:asked|ask) (?:you|u) to remember\s*\??$")),
    ("recall", re.compile(
        r"^what did i (?:tell|say to) (?:you|u) about (?:the |my )?(?P<recall>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        r"|^what(?:'s| is|s)? (?:my |the )(?P<recall2>[a-z0-9][a-z0-9 '-]{1,30}?)(?:'s)? (?:name|number|address|email|birthday|code|password|pin)\s*\??$"
        r"|^when (?:is|does|was) (?:my |the )?(?P<recall3>[a-z0-9][a-z0-9 '-]{1,30}?) (?:up|due|over|expiring|expire|ending|end|starting|start|renewing|renew|coming up)\s*\??$"
        # "When is my sister's birthday" (2026-10-05): a date he told her, on her shelf.
        r"|^when(?:'s| is|s)? (?:my |the )(?P<recall6>[a-z0-9][a-z0-9 '-]{1,30}?(?:'s)? (?:birthday|anniversary|appointment|flight|wedding|graduation|party|checkup|check-up|exam|trip|visit))\s*\??$"
        r"|^(?:do (?:you|u) )?(?:remember|know) (?:anything about |what i said about )?(?:the |my )?(?P<recall4>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        r"|^what did i say about (?:the |my )?(?P<recall5>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        # "What did I note about the car", "what have I told you about the car" (2026-10-05: a model each)
        r"|^what (?:did|have) i (?:note|noted|write down|written down|jot down|jotted down|log|logged|told you|said|mention|mentioned) (?:about |on |regarding )(?:the |my )?(?P<recall7>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        r"|^(?:any|got any|do i have any|are there any) notes? (?:about|on) (?:the |my )?(?P<recall8>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        r"|^what(?:'s| is) (?:in|on) (?:my |the )?notes? (?:about|on|for) (?:the |my )?(?P<recall9>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        # "whats the wifi" (2026-10-05: a model) - the things he tells her once
        r"|^what(?:'s| is|s)? (?:the |my |our )?(?P<recall10>wifi|wi-fi|wifi (?:name|network)|network name|(?:gate|door|garage|alarm|building|front door) code|"
        r"(?:door|gate|garage|lock) pin|locker (?:combo|combination))\s*\??$")),
    # "do you have access to my bank" was answered "Read-only, yes" by a
    # model (2026-10-05). There is no bank data; the registry says so.
    # Before "can you ...", which would otherwise swallow "can you get access to".
    ("access_to", re.compile(
        r"^(?:do|can|could) (?:you|u) (?:have|get|got) access to (?:my |the |our )?(?P<access>.{2,80})$"
        r"|^(?:are|r) (?:you|u) (?:connected|hooked up|linked) to (?:my |the |our )?(?P<access2>.{2,80})$"
        r"|^(?:do|can) (?:you|u) (?:see|read|get into|get at) (?:my |the |our )?(?P<access3>bank(?: account)?|bank accounts?|accounts?|finances|money|credit card|cards?|statements?)$")),
    ("can_you", re.compile(
        r"^(?:can|could) (?:you|u) (?P<what>.{3,120})$"
        r"|^(?:are|r) (?:you|u) able to (?P<what2>.{3,120})$"
        r"|^do (?:you|u) know how to (?P<what3>.{3,120})$")),
    # Three questions about the turn before (2026-10-05, each a model turn
    # of nine seconds and a guess): why, whether she is sure, who made her.
    ("why_that", re.compile(
        r"^why (?:did|would|have) (?:you|u) (?:do|say|done|said) that(?: for)?\s*\??$|^why(?:'d| did) (?:you|u) do it\s*\??$"
        r"|^what was that for\s*\??$|^why that\s*\??$")),
    ("sure", re.compile(
        r"^(?:are|r) (?:you|u) (?:sure|certain|positive)(?: about that| about this| of that)?\s*\??$"
        r"|^(?:is|are) (?:that|those|you) (?:right|correct|true|for real)\s*\??$|^really\s*\??$|^for real\s*\??$"
        r"|^how (?:sure|certain) (?:are|r) (?:you|u)(?: about that)?\s*\??$|^(?:did|do) (?:you|u) make that up\s*\??$")),
    ("who_made", re.compile(
        r"^who (?:made|built|created|wrote|programmed|designed|coded|trained) (?:you|u)\s*\??$"
        r"|^where (?:do|did) (?:you|u) come from\s*\??$|^what (?:are|r) (?:you|u) (?:built|made|running) on\s*\??$")),
    # The friction ledger, read out: what he has had to do himself.
    ("friction", re.compile(
        r"^what (?:have|did) i (?:had|have) to do (?:myself|on my own|by hand|for you)(?: lately| this (?:week|month))?$"
        r"|^what (?:have|did) (?:you|u) (?:been asking|asked) me(?: lately| for| about)?(?: this (?:week|month))?$"
        r"|^how (?:much|often) (?:have|did) i (?:had|have) to (?:babysit|fix|restart|help) (?:you|u)(?: lately)?$"
        r"|^(?:what(?:'s| is|s)? (?:been )?(?:annoying|friction|the friction)|(?:the )?friction ledger|"
        r"how annoying (?:have|were) (?:you|u) been)(?: lately| this (?:week|month))?$"
        r"|^how many times (?:have|did) i (?:have|had) to (?:step in|fix (?:you|things|something)|"
        r"restart (?:you|u)|repeat myself)(?: lately)?$")),
    # THE GROUNDED STATUS FAMILY, last so an exact pattern above wins.
    # Found live 2026-09-14 from his phone: "give me a status update on how
    # applying to jobs is going" went to the PLANNER, and with Claude and
    # ChatGPT out came back "I could not plan that: ReasonerUnavailable".
    # The failure was not that nobody could think; it was that a question
    # whose answer is a file read was routed to thinking at all. A status
    # question is a SHAPE (how's it going, still running, how many, when
    # was the last, what's blocking) and a SUBJECT; the subject picks the
    # store, and the store answers. A subject nothing here knows returns
    # None, which is the planner - never a guess.
    ("status_of", _STATUS),
    # LAST, after every other question: "what's the shorts pipeline" is the
    # registry's own summary, and only when the words name a repo of the
    # fleet - the answer returns None otherwise, so "what's the time" and
    # "what's the weather" above are never reached from here.
    ("repo_about", re.compile(
        r"^what does (?:the |my )?(?P<repo_about3>[a-z0-9][a-z0-9 _-]{2,30}) do\s*\??$"
        r"|^tell me about (?:the |my )?(?P<repo_about2>[a-z0-9][a-z0-9 _-]{2,30})\s*\??$"
        r"|^what(?:'s| is|s)? (?:the |my )?(?P<repo_about>[a-z0-9][a-z0-9 _-]{2,30})(?: for| about)?\s*\??$")),
)


def match(question: str) -> tuple[str, str] | None:
    """(which answer, the captured remainder) — or None to think properly."""
    text = _tidy(question)
    if not text or len(text) > MAX_QUESTION:
        return None
    for name, pattern in PATTERNS:
        found = pattern.match(text)
        if not found:
            continue
        captured = found.groupdict()
        if name == "repo_about" and not _repo_about(next((v for v in captured.values() if v), "")):
            continue                # names no repo of the fleet: not hers to answer
        if name == "status_of":
            return name, text
        if name in ("math", "farewell", "time_convert", "chance", "date_math", "clock_ahead", "until", "days_left", "just_asked", "mine"):
            return name, text           # the answer re-reads the whole sentence
        rest = next((captured[k] for k in ("what", "what2", "what3", "mine", "mine2", "mine3", "mine4", "recall7", "recall8", "recall9", "recall10",
                                       "fin_when", "fin_when2", "fin_when3", "fin_when4", "left_when", "left_when2", "left_when3",
                                       "are_you", "why_thea", "allowed", "allowed2", "allowed3",
                                       "repo_about", "repo_about2", "repo_about3",
                                           "free", "free2", "free3",
                                           "down", "down2", "weather",
                                           "weather2", "weather3",
                                           "day", "day2", "day3", "day4", "day5", "day6", "day7", "day10",
                                           "what_day", "what_day2", "leap_year", "leap_year2",
                                           "outcome", "outcome2", "outcome3", "outcome4", "outcome5", "outcome6", "outcome7",
                                           "app_extreme", "app_extreme2", "app_extreme3",
                                           "until", "until2", "until3", "day8", "day9",
                                           "why_not", "why_not2", "why_not3",
                                           "sent_window", "sent_window2",
                                           "repo_wrong", "repo_wrong2", "time_in", "time_in2",
                                           "time_in3", "date_of", "date_of2", "date_of3",
                                           "recall", "recall2", "recall3", "recall4", "recall5", "ran",
                                           "date_ahead", "date_ahead2", "found_window",
                                           "hold_q", "hold_q2", "hold_q3", "hold_q4",
                                           "draft_to", "draft_to2", "draft_to3",
                                           "applied_on", "applied_on2", "applied_on3",
                                           "due_when", "due_when2", "due_when3",
                                           "extreme", "extreme2", "extreme3", "spend_per", "spend_per2", "spend_per3", "who_is",
                                           "project_of", "project_of2", "project_of3", "project_turn",
                                           "access", "access2", "access3",
                                           "recall6", "notes_search", "notes_search2", "notes_search3",
                                           "asked_on", "asked_on2", "asked_on3", "asked_on4", "asked_on5", "day_part",
                                           "place", "place2", "place3",
                                           "pay_for", "pay_for2", "pay_for3", "pay_for4",
                                           "wrong_when", "wrong_when2", "decided", "decided2", "decided3",
                                           "standing_for", "standing_for2", "standing_for3", "standing_for4",
                                           "spell", "coin", "die", "dice_n", "lo", "since", "until_t")
                     if captured.get(k)), "")
        if name in ("opportunity", "opportunity_loose", "applied_when", "person", "why_not", "draft_to"):
            # The layer matches on a LOWERCASED sentence (CLAUDE.md), and a
            # name he said is read back to him: "nowhere inc" is not what
            # he said. His capitals, put back from the sentence itself.
            rest = _as_said(rest, question)
        return name, rest


def _as_said(fragment: str, original: str) -> str:
    """`fragment` as it appears in `original`, capitals and all."""
    where = str(original or "").casefold().find(str(fragment or "").casefold())
    if where < 0 or not fragment:
        return fragment
    return str(original)[where:where + len(fragment)]
    return None


def _halted(asks_if_down: bool = True) -> str:
    """Yes or no, agreeing with the direction the question was asked in.

    "Are you halted?" and "You there?" want opposite words for the same
    state. Answering both with the sentence written for the first is how
    "are you running" came back "No, I'm running." — the state was right
    and the first word contradicted it.
    """
    from aletheia import policy
    halt = policy.halted()
    if not halt:
        return "No, I'm running." if asks_if_down else "Yes, I'm running."
    reason = str(halt.get("reason") or "").strip()
    lead = "Yes, I'm halted" if asks_if_down else "No, I'm halted"
    return lead + (f" — {reason}." if reason else ".")


def _waiting() -> str:
    """"What’s waiting on me" — read from the ONE list, every time.

    There used to be several answers to this question, each from a
    different store: the approvals here, the applications from the job
    hunt, the work items in the session report, the browser missions on
    the Command Center. A short list that is quietly incomplete is worse
    than a long one, because it teaches him it is complete.

    `needs_you` is that one list. Unread notices are still added here,
    and deliberately after it: a notice TELLS him something, and a
    decision ASKS him for something, and the asking comes first.
    """
    from aletheia import needs_you, presence, speech
    now = presence.snapshot()
    if now.get("halted"):
        return _halted() + " Nothing runs until you resume me."
    rows = needs_you.items()
    notices = list(now.get("notifications") or [])
    if not rows and not notices:
        return "Nothing needs you right now."
    parts = [needs_you.spoken(rows).rstrip(".")] if rows else []
    if notices:
        # SAY WHAT THEY ARE. A reminder fired correctly, on time, and the
        # answer to "what's waiting on me" was "1 thing I wanted to tell
        # you about" — the answer to "how many", when he asked what.
        # Titles rather than bodies, cut at a word boundary. A body is a
        # paragraph with commas in it, and `and_list` joins with commas —
        # three of those ran together into one unbreathable sentence
        # ending "...is worth right now?: I don't ha,".
        # ONCE EACH, with how many. "Applications ready to approve,
        # Applications ready to approve and Application sent" was a real
        # answer: two batches, one title, said twice in one breath.
        counted: dict[str, int] = {}
        for notice in notices:
            line = speech.notice_line(notice)
            if line:
                counted[line] = counted.get(line, 0) + 1
        phrases = [line if n == 1 else f"{line} ({speech.count_phrase(n, 'time')})"
                   for line, n in list(counted.items())[:3]]
        said = speech.and_list(phrases)
        more = f", and {len(counted) - 3} more" if len(counted) > 3 else ""
        parts.append(said + more if said else
                     f"{speech.count_phrase(len(notices), 'thing')} "
                     "I wanted to tell you about")
    return ". ".join(parts) + "."


_NAMED_DAYS = {"christmas": (12, 25), "christmas day": (12, 25), "christmas eve": (12, 24),
               "new year": (1, 1), "new year's": (1, 1), "new year's day": (1, 1), "new years": (1, 1),
               "new year's eve": (12, 31), "new years eve": (12, 31), "halloween": (10, 31),
               "valentine's": (2, 14), "valentine's day": (2, 14), "valentines day": (2, 14),
               "the fourth of july": (7, 4), "fourth of july": (7, 4), "july 4th": (7, 4), "july fourth": (7, 4),
               "independence day": (7, 4)}
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")


def _named_date(words: str, today):
    """The next date these words name, or None: a weekday, a named day, a
    month and day in either order, or a Thanksgiving."""
    import datetime as dt
    import re as _re
    w = " ".join(words.casefold().split()).strip(" ?.")
    if w in _NAMED_DAYS:
        month, day = _NAMED_DAYS[w]
        when = dt.date(today.year, month, day)
        return when if when >= today else dt.date(today.year + 1, month, day)
    if w == "thanksgiving":
        for year in (today.year, today.year + 1):
            first = dt.date(year, 11, 1)
            thursday = first + dt.timedelta(days=(3 - first.weekday()) % 7)
            when = thursday + dt.timedelta(weeks=3)
            if when >= today:
                return when
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if w in days:
        ahead = (days.index(w) - today.weekday()) % 7
        return today + dt.timedelta(days=ahead or 7)
    bare = _re.fullmatch(r"(?:the )?(\d{1,2})(?:st|nd|rd|th)", w)
    if bare:
        # "the 20th": the next such day of a month (2026-10-05)
        want = int(bare.group(1))
        year, month = today.year, today.month
        for _ in range(3):
            try:
                when = dt.date(year, month, want)
            except ValueError:
                when = None
            if when and when >= today:
                return when
            month, year = (month % 12) + 1, year + (1 if month == 12 else 0)
        return None
    m = (_re.fullmatch(r"(?:the )?(\d{1,2})(?:st|nd|rd|th)? (?:of )?([a-z]+)", w)
         or _re.fullmatch(r"([a-z]+) (?:the )?(\d{1,2})(?:st|nd|rd|th)?", w))
    if m:
        a, b = m.group(1), m.group(2)
        day, month = (a, b) if a.isdigit() else (b, a)
        if month in _MONTHS:
            try:
                when = dt.date(today.year, _MONTHS.index(month) + 1, int(day))
            except ValueError:
                return None
            return when if when >= today else dt.date(today.year + 1, _MONTHS.index(month) + 1, int(day))
    return None


#: Where a place name puts the clock. Cities, countries and US states he
#: is likely to say; anything not here is left to a model, never guessed.
_ZONES = {
    "tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo", "osaka": "Asia/Tokyo",
    "london": "Europe/London", "uk": "Europe/London", "england": "Europe/London", "the uk": "Europe/London",
    "britain": "Europe/London", "scotland": "Europe/London", "dublin": "Europe/Dublin", "ireland": "Europe/Dublin",
    "paris": "Europe/Paris", "france": "Europe/Paris", "berlin": "Europe/Berlin", "germany": "Europe/Berlin",
    "munich": "Europe/Berlin", "rome": "Europe/Rome", "italy": "Europe/Rome", "milan": "Europe/Rome",
    "madrid": "Europe/Madrid", "spain": "Europe/Madrid", "barcelona": "Europe/Madrid",
    "amsterdam": "Europe/Amsterdam", "the netherlands": "Europe/Amsterdam", "netherlands": "Europe/Amsterdam",
    "brussels": "Europe/Brussels", "belgium": "Europe/Brussels", "zurich": "Europe/Zurich", "switzerland": "Europe/Zurich",
    "vienna": "Europe/Vienna", "austria": "Europe/Vienna", "stockholm": "Europe/Stockholm", "sweden": "Europe/Stockholm",
    "oslo": "Europe/Oslo", "norway": "Europe/Oslo", "copenhagen": "Europe/Copenhagen", "denmark": "Europe/Copenhagen",
    "helsinki": "Europe/Helsinki", "finland": "Europe/Helsinki", "warsaw": "Europe/Warsaw", "poland": "Europe/Warsaw",
    "lisbon": "Europe/Lisbon", "portugal": "Europe/Lisbon", "athens": "Europe/Athens", "greece": "Europe/Athens",
    "prague": "Europe/Prague", "moscow": "Europe/Moscow", "russia": "Europe/Moscow", "istanbul": "Europe/Istanbul",
    "turkey": "Europe/Istanbul", "cairo": "Africa/Cairo", "egypt": "Africa/Cairo", "lagos": "Africa/Lagos",
    "nigeria": "Africa/Lagos", "johannesburg": "Africa/Johannesburg", "south africa": "Africa/Johannesburg",
    "nairobi": "Africa/Nairobi", "kenya": "Africa/Nairobi", "dubai": "Asia/Dubai", "uae": "Asia/Dubai",
    "the uae": "Asia/Dubai", "tel aviv": "Asia/Jerusalem", "israel": "Asia/Jerusalem", "jerusalem": "Asia/Jerusalem",
    "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata", "bangalore": "Asia/Kolkata",
    "india": "Asia/Kolkata", "karachi": "Asia/Karachi", "pakistan": "Asia/Karachi", "bangkok": "Asia/Bangkok",
    "thailand": "Asia/Bangkok", "hanoi": "Asia/Ho_Chi_Minh", "vietnam": "Asia/Ho_Chi_Minh", "singapore": "Asia/Singapore",
    "kuala lumpur": "Asia/Kuala_Lumpur", "malaysia": "Asia/Kuala_Lumpur", "jakarta": "Asia/Jakarta", "indonesia": "Asia/Jakarta",
    "manila": "Asia/Manila", "the philippines": "Asia/Manila", "philippines": "Asia/Manila", "hong kong": "Asia/Hong_Kong",
    "shanghai": "Asia/Shanghai", "beijing": "Asia/Shanghai", "china": "Asia/Shanghai", "taipei": "Asia/Taipei",
    "taiwan": "Asia/Taipei", "seoul": "Asia/Seoul", "korea": "Asia/Seoul", "south korea": "Asia/Seoul",
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne", "australia": "Australia/Sydney",
    "brisbane": "Australia/Brisbane", "perth": "Australia/Perth", "auckland": "Pacific/Auckland",
    "new zealand": "Pacific/Auckland", "honolulu": "Pacific/Honolulu", "hawaii": "Pacific/Honolulu",
    "anchorage": "America/Anchorage", "alaska": "America/Anchorage", "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles", "san francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles",
    "portland": "America/Los_Angeles", "san diego": "America/Los_Angeles", "las vegas": "America/Los_Angeles",
    "california": "America/Los_Angeles", "washington state": "America/Los_Angeles", "oregon": "America/Los_Angeles",
    "nevada": "America/Los_Angeles", "denver": "America/Denver", "colorado": "America/Denver", "salt lake city": "America/Denver",
    "utah": "America/Denver", "phoenix": "America/Phoenix", "arizona": "America/Phoenix", "chicago": "America/Chicago",
    "illinois": "America/Chicago", "dallas": "America/Chicago", "houston": "America/Chicago", "austin": "America/Chicago",
    "texas": "America/Chicago", "minneapolis": "America/Chicago", "minnesota": "America/Chicago", "kansas city": "America/Chicago",
    "st louis": "America/Chicago", "nashville": "America/Chicago", "new orleans": "America/Chicago", "omaha": "America/Chicago",
    "nebraska": "America/Chicago", "iowa": "America/Chicago", "wisconsin": "America/Chicago", "missouri": "America/Chicago",
    "oklahoma": "America/Chicago", "sioux falls": "America/Chicago", "south dakota": "America/Chicago",
    "north dakota": "America/Chicago", "fargo": "America/Chicago", "new york": "America/New_York", "nyc": "America/New_York",
    "new york city": "America/New_York", "boston": "America/New_York", "philadelphia": "America/New_York",
    "washington": "America/New_York", "washington dc": "America/New_York", "dc": "America/New_York",
    "miami": "America/New_York", "florida": "America/New_York", "atlanta": "America/New_York", "georgia": "America/New_York",
    "charlotte": "America/New_York", "detroit": "America/Detroit", "michigan": "America/Detroit", "ohio": "America/New_York",
    "pittsburgh": "America/New_York", "toronto": "America/Toronto", "ottawa": "America/Toronto", "montreal": "America/Toronto",
    "canada": "America/Toronto", "vancouver": "America/Vancouver", "calgary": "America/Edmonton", "mexico city": "America/Mexico_City",
    "mexico": "America/Mexico_City", "bogota": "America/Bogota", "colombia": "America/Bogota", "lima": "America/Lima",
    "peru": "America/Lima", "santiago": "America/Santiago", "chile": "America/Santiago", "buenos aires": "America/Argentina/Buenos_Aires",
    "argentina": "America/Argentina/Buenos_Aires", "sao paulo": "America/Sao_Paulo", "brazil": "America/Sao_Paulo",
    "rio": "America/Sao_Paulo", "utc": "UTC", "gmt": "UTC", "eastern time": "America/New_York", "the east coast": "America/New_York",
    "east coast": "America/New_York", "central time": "America/Chicago", "mountain time": "America/Denver",
    "pacific time": "America/Los_Angeles", "the west coast": "America/Los_Angeles", "west coast": "America/Los_Angeles",
}


def _time_in(place: str) -> str | None:
    """The clock somewhere he named, and how far it sits from his own."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    from aletheia import localtime
    key = " ".join(str(place or "").casefold().split()).strip(" ?.")
    zone = _ZONES.get(key) or _ZONES.get(key.replace("the ", "", 1))
    if not zone:
        return None
    try:
        there = dt.datetime.now(ZoneInfo(zone))
        here = dt.datetime.now(localtime.operator_tz())
    except Exception:
        return None
    clock = there.strftime("%I:%M %p").lstrip("0").replace("AM", "am").replace("PM", "pm")
    said = f"{clock} on {there.strftime('%A')} in {place.strip().title() if key not in ('utc', 'gmt') else key.upper()}"
    hours = (there.utcoffset() - here.utcoffset()).total_seconds() / 3600
    whole = int(hours) if float(hours).is_integer() else hours
    if hours > 0:
        said += f" - {whole} hour{'s' if abs(hours) != 1 else ''} ahead of you"
    elif hours < 0:
        said += f" - {abs(whole)} hour{'s' if abs(hours) != 1 else ''} behind you"
    else:
        said += " - the same as yours"
    return said + "."


def _her_page() -> str:
    """Where her page is: on this PC, and from his phone through the tailnet."""
    from aletheia import core
    port = int(getattr(core, "DEFAULT_PORT", 8777))
    page = str(getattr(core, "THE_PAGE", "/interface/thea.html"))
    said = (f"On this PC, open http://127.0.0.1:{port}{page} - that's the Thea page, the one that answers "
            "everything; the wall is the fleet behind it and every panel on it links back into the page.")
    try:
        link = core.phone_link()
    except Exception:
        link = {}
    if link.get("url"):
        said += (f" From your phone on the tailnet, open {link['url']}; the QR code at the bottom of the Thea "
                 "page on the PC carries that address, and the code you paste in comes from your own keyboard.")
        if link.get("why"):
            said += f" {link['why']}"
    else:
        why = str(link.get("why") or "your phone has no address for her yet")
        said += f" From your phone: not yet. {why}"
    return said


def _the_wall() -> str:
    """The wall is a pure view of the pulse: what it shows is the fleet."""
    fleet = _fleet() or "No fleet reading yet."
    return "The wall shows the fleet, read from the pulse: " + fleet + " Every panel on it links into the Thea page."


_SMALL_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                  "ten": 10, "twelve": 12, "half a": 0.5, "half an": 0.5}


def _clock_words(moment) -> str:
    text = moment.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
    return text.replace(" AM", " am").replace(" PM", " pm")


def _clock_ahead(text: str) -> str | None:
    """"What time is it in an hour": the clock moved, on his zone."""
    import datetime as dt
    from aletheia import localtime
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "clock_ahead"), None)
    if not found:
        return None
    g = {k: v for k, v in found.groupdict().items() if v}
    raw = (g.get("ahead_n") or g.get("ahead_n2") or g.get("ago_n") or "1").strip()
    n = _SMALL_NUMBERS.get(raw)
    if n is None:
        n = float(raw) if raw.isdigit() else 1
    unit = (g.get("ahead_unit") or g.get("ahead_unit2") or g.get("ago_unit") or "hour")
    delta = dt.timedelta(hours=n) if unit.startswith("h") else dt.timedelta(minutes=n)
    now = dt.datetime.now(localtime.operator_tz())
    then = now - delta if g.get("ago_n") else now + delta
    day = "" if then.date() == now.date() else (" tomorrow" if then.date() > now.date() else " yesterday")
    return f"{_clock_words(then)}{day}." if g.get("ago_n") else f"It'll be {_clock_words(then)}{day}."


def _until_clock(words: str) -> str:
    """"How long until 5": to the next such time, a bare hour read the way a
    person means it (never the small hours), and the other reading said."""
    import datetime as dt
    from aletheia import liveness, localtime
    w = " ".join(str(words or "").casefold().split())
    named = {"noon": (12, 0), "midnight": (0, 0), "lunch": (12, 0), "lunchtime": (12, 0), "dinner": (18, 0), "dinnertime": (18, 0)}
    bare = False
    if w in named:
        hour, minute = named[w]
    else:
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))? ?(am|pm)?", w)
        if not m:
            return "I couldn't read that as a time."
        hour, minute, half = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if half == "pm" and hour != 12:
            hour += 12
        if half == "am" and hour == 12:
            hour = 0
        bare = half is None and 1 <= hour <= 11
    now = dt.datetime.now(localtime.operator_tz())

    def next_at(h):
        at = now.replace(hour=h % 24, minute=minute, second=0, microsecond=0)
        return at if at > now else at + dt.timedelta(days=1)

    if bare:
        readings = sorted([next_at(hour), next_at(hour + 12)])
        soon, later = readings[0], readings[1]
        if soon.hour < 6:                      # nobody means the small hours
            soon, later = later, soon
        day = "" if soon.date() == now.date() else " tomorrow"
        return (f"{liveness.spoken_duration((soon - now).total_seconds())}, until {_clock_words(soon)}{day}. "
                f"If you mean {_clock_words(later)}, that's {liveness.spoken_duration((later - now).total_seconds())}.")
    at = next_at(hour)
    day = "" if at.date() == now.date() else " tomorrow"
    return f"{liveness.spoken_duration((at - now).total_seconds())}, until {_clock_words(at)}{day}."


def _day_part_now() -> str:
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    h = now.hour
    part = "morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17 else "evening" if 17 <= h < 22 else "night"
    return f"{part.capitalize()} - it's {_clock_words(now)} on {now.strftime('%A')}."


def _weekend_now() -> str:
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    if now.weekday() >= 5:
        return f"Yes, it's {now.strftime('%A')} - the weekend" + (", and tomorrow is Monday." if now.weekday() == 6 else ".")
    ahead = 5 - now.weekday()
    return f"No, it's {now.strftime('%A')}; the weekend is {ahead} day{'s' if ahead != 1 else ''} away."


def _quarter() -> str:
    from aletheia import localtime
    today = localtime.today()
    q = (today.month - 1) // 3 + 1
    ends = {1: "March", 2: "June", 3: "September", 4: "December"}[q]
    return f"The {['first', 'second', 'third', 'fourth'][q - 1]} quarter of {today.year}, which runs to the end of {ends}."


def _days_left(text: str) -> str | None:
    import calendar as _calendar
    import datetime as dt
    from aletheia import localtime
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "days_left"), None)
    if not found:
        return None
    g = {k: v for k, v in found.groupdict().items() if v}
    span = g.get("left_in") or g.get("left_in2") or g.get("left_in3") or "month"
    today = localtime.today()
    if span == "month":
        end = dt.date(today.year, today.month, _calendar.monthrange(today.year, today.month)[1])
    elif span == "year":
        end = dt.date(today.year, 12, 31)
    elif span == "week":
        end = today + dt.timedelta(days=6 - today.weekday())
    else:
        q_end_month = ((today.month - 1) // 3 + 1) * 3
        end = dt.date(today.year, q_end_month, _calendar.monthrange(today.year, q_end_month)[1])
    left = (end - today).days
    when = f"{end.strftime('%A')} the {_ordinal(end.day)}" + ("" if span == "week" else f" of {end.strftime('%B')}")
    if left == 0:
        return f"Today is the last day of the {span}."
    return f"{left} day{'s' if left != 1 else ''} after today; the {span} ends {when}."


def _his_birthday():
    """(month, day, year-or-None) from identity.birthday, or None."""
    from aletheia import memory
    try:
        said = str(memory.recall("identity", "birthday") or "")
    except Exception:
        said = ""
    low = " ".join(said.casefold().replace(",", " ").split())
    if not low:
        return None
    year = None
    m = re.search(r"\b(19\d{2}|20\d{2})\b", low)
    if m:
        year = int(m.group(1))
        low = (low[:m.start()] + low[m.end():]).strip()
    m = (re.fullmatch(r"(?:the )?(\d{1,2})(?:st|nd|rd|th)? (?:of )?([a-z]+)", low)
         or re.fullmatch(r"([a-z]+) (?:the )?(\d{1,2})(?:st|nd|rd|th)?", low))
    if m:
        a, b = m.group(1), m.group(2)
        day, month = (a, b) if a.isdigit() else (b, a)
        if month in _MONTHS:
            return _MONTHS.index(month) + 1, int(day), year
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", low)
    if m:
        year = year or (int(m.group(3)) if m.group(3) and len(m.group(3)) == 4 else year)
        return int(m.group(1)), int(m.group(2)), year
    return None


def _birthday(which: str) -> str:
    """"When's my birthday", "how old am I", "how many days until my
    birthday" (2026-10-05: a model each, and a plan with an approval to
    remember the date). From identity.birthday, or the honest sentence."""
    from aletheia import localtime, speech
    found = _his_birthday()
    if not found:
        return "I don't have your birthday on file. Say 'my birthday is June 3 1998' and I'll remember it."
    month, day, year = found
    today = localtime.today()
    try:
        this_year = dt.date(today.year, month, day)
    except ValueError:
        this_year = dt.date(today.year, month, 28)
    nxt = this_year if this_year >= today else this_year.replace(year=today.year + 1)
    when = f"{_MONTHS[month - 1].capitalize()} {day}"
    if which == "when":
        return f"Your birthday is {when}." + (f" You were born in {year}." if year else "")
    if which == "age":
        if not year:
            return f"I have your birthday as {when} but not the year, so I can't work out your age. Tell me the year and I'll remember it."
        age = today.year - year - (1 if (today.month, today.day) < (month, day) else 0)
        return f"You're {age}." + (" Happy birthday!" if this_year == today else "")
    days = (nxt - today).days
    turning = f", when you turn {nxt.year - year}" if year else ""
    if days == 0:
        return f"It's today - happy birthday!{(' You are ' + str(today.year - year) + '.') if year else ''}"
    return f"{speech.count_phrase(days, 'day')} - {when}{', next year' if nxt.year != today.year else ''}{turning}."


def _todays_turns() -> list[dict]:
    """The thread's turns dated today in his zone, oldest first."""
    from aletheia import converse, localtime
    try:
        turns = converse.recent(limit=converse.KEEP_TURNS)
    except Exception:
        return []
    today = localtime.today()
    out = []
    for turn in turns:
        try:
            when = dt.datetime.fromisoformat(str(turn.get("at") or "").replace("Z", "+00:00"))
            if when.astimezone(localtime.operator_tz()).date() == today:
                out.append(turn)
        except (ValueError, TypeError):
            continue
    return out


def _talking_for() -> str:
    """"How long have we been talking" (2026-10-05: a model, five seconds)."""
    from aletheia import converse, localtime, speech
    turns = _todays_turns()
    if not turns:
        return "We just started - nothing earlier today in the conversation."
    first = dt.datetime.fromisoformat(str(turns[0]["at"]).replace("Z", "+00:00")).astimezone(localtime.operator_tz())
    minutes = max(1, int((dt.datetime.now(localtime.operator_tz()) - first).total_seconds() // 60))
    span = f"{minutes} minute{'s' if minutes != 1 else ''}" if minutes < 90 else f"about {round(minutes / 60)} hours"
    capped = " at least, as far back as I keep" if len(turns) >= converse.KEEP_TURNS else ""
    return f"About {span}{capped}, since {speech.clock_words(first.strftime('%H:%M'))}."


def _asked_today() -> str:
    """"How many things have I asked you today" (2026-10-05: a model, six seconds)."""
    from aletheia import converse
    turns = _todays_turns()
    if not turns:
        return "Nothing yet today."
    n = len(turns)
    if n >= converse.KEEP_TURNS:
        return f"At least {n} - that's as far back as I keep the conversation."
    return f"{n} thing{'s' if n != 1 else ''} today, counting this one."


def _just_asked(text: str) -> str:
    """"What did I just ask you" / "say that again": the thread's last turn,
    said back (2026-10-05: a model, four seconds, to read one line of her own
    memory)."""
    from aletheia import converse
    try:
        turns = converse.recent(limit=2)
    except Exception:
        turns = []
    if not turns:
        return "Nothing yet - the conversation thread is empty."
    turn = turns[-1]
    low = str(turn.get("he_asked") or "").casefold()
    if re.match(r"(?:what did i|what was the last|what did you|say that|repeat|what was that|come again)", low) and len(turns) > 1:
        turn = turns[-2]
    asked = " ".join(str(turn.get("he_asked") or "").split()).strip(".")
    answered = " ".join(str(turn.get("she_answered") or "").split())
    if re.match(r"(?:what did you|say that|repeat|what was that|come again)", _tidy(text)):
        return answered or f"I didn't say anything after you said \"{asked}\"."
    return f"You said \"{asked}\"" + (f", and I said: {answered}" if answered else ".")


def _when_asked() -> str:
    """When he last asked something: the thread's own stamp."""
    from aletheia import converse, speech
    try:
        turns = converse.recent(limit=2)
    except Exception:
        turns = []
    if not turns:
        return "I don't have a record of when - the conversation thread is empty."
    # The question being answered is not in the thread yet (the Core records
    # a turn after answering it), so the last turn IS the one he means -
    # unless the thread already holds this question (a replay, a test).
    turn = turns[-1]
    if re.search(r"\b(?:when|what time) (?:did i|was that|was it)\b", str(turn.get("he_asked") or "").casefold()) and len(turns) > 1:
        turn = turns[-2]
    when = speech.humanize_time(str(turn.get("at") or "")) if turn.get("at") else ""
    asked = str(turn.get("he_asked") or "").strip()
    return f"You asked \"{asked}\" {when}." if when else f"You asked \"{asked}\", but I don't have the time it was said."


def _until_sentence(text: str) -> str | None:
    """`until` gets the whole sentence now (weeks as well as days)."""
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "until"), None)
    if not found:
        return None
    g = {k: v for k, v in found.groupdict().items() if v}
    words = g.get("until") or g.get("until2") or g.get("until3") or ""
    said = _until(words)
    if said and re.match(r"^how many weeks", _tidy(text)):
        m = re.match(r"^(\d+) days, (.+)$", said)
        if m:
            days = int(m.group(1))
            weeks, rest = divmod(days, 7)
            return f"{weeks} week{'s' if weeks != 1 else ''}" + (f" and {rest} day{'s' if rest != 1 else ''}" if rest else "") + f" - {days} days, {m.group(2)}"
    return said


def _my_zone() -> str:
    """His time zone, which is the one she works in, and the clock there."""
    import datetime as dt
    from aletheia import localtime
    name = localtime.operator_timezone()
    now = dt.datetime.now(localtime.operator_tz())
    said = {"America/Chicago": "Central time", "America/New_York": "Eastern time", "America/Denver": "Mountain time",
            "America/Los_Angeles": "Pacific time", "America/Anchorage": "Alaska time", "Pacific/Honolulu": "Hawaii time",
            "Europe/London": "UK time", "UTC": "UTC"}.get(name, name.replace("_", " "))
    clock = now.strftime("%I:%M %p").lstrip("0").replace("AM", "am").replace("PM", "pm")
    return f"{said} - it's {clock} on {now.strftime('%A')}. I keep my records in universal time and work in yours."


def _time_convert(text: str) -> str | None:
    """"What's 3 pm my time in London" and "when it's 9 am in Tokyo what time
    is it here": the same clock, read in the other zone, today."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    from aletheia import localtime
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "time_convert"), None)
    if not found:
        return None
    g = {k: v for k, v in found.groupdict().items() if v}
    clock_words = g.get("conv_t") or g.get("conv_t2") or g.get("conv_t3")
    place = (g.get("conv_place") or g.get("conv_place2") or g.get("conv_place3") or "").strip()
    key = " ".join(place.casefold().split())
    zone = _ZONES.get(key) or _ZONES.get(key.replace("the ", "", 1))
    if not zone:
        return None
    if clock_words == "noon":
        hour, minute = 12, 0
    elif clock_words == "midnight":
        hour, minute = 0, 0
    else:
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))? ?(am|pm)", clock_words)
        hour, minute = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0), int(m.group(2) or 0)
    his, theirs = localtime.operator_tz(), ZoneInfo(zone)
    there_first = bool(g.get("conv_t2") or g.get("conv_t3"))
    source, target = (theirs, his) if there_first else (his, theirs)
    today = dt.datetime.now(source).date()
    moment = dt.datetime.combine(today, dt.time(hour, minute), tzinfo=source)
    other = moment.astimezone(target)

    def clock(x):
        return x.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").replace("AM", "am").replace("PM", "pm")

    day = "" if other.date() == moment.date() else (" the next day" if other.date() > moment.date() else " the day before")
    name = place.strip().title() if key not in ("utc", "gmt") else key.upper()
    if there_first:
        return f"{clock(moment)} in {name} is {clock(other)}{day} for you."
    return f"{clock(moment)} your time is {clock(other)}{day} in {name}."


def _spell(word: str) -> str:
    letters = [c.upper() for c in str(word or "") if c.isalpha()]
    if not letters:
        return "Spell what?"
    return f"{str(word).strip().capitalize()}: " + ", ".join(letters) + "."


def _chance(text: str) -> str | None:
    """A coin, a die, a number - chance is code, not a model (2026-10-05:
    seven seconds to flip a coin)."""
    import random
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "chance"), None)
    if not found:
        return None
    g = {k: v for k, v in found.groupdict().items() if v}
    if g.get("coin"):
        return random.choice(["Heads.", "Tails."])
    if g.get("die"):
        return f"{random.randint(1, 6)}."
    if g.get("dice_n"):
        n = {"two": 2, "2": 2, "three": 3, "3": 3}[g["dice_n"]]
        rolls = [random.randint(1, 6) for _ in range(n)]
        return " and ".join(str(r) for r in rolls) + f" - {sum(rolls)} together."
    lo, hi = int(g.get("lo") or 1), int(g.get("hi") or 10)
    if lo > hi:
        lo, hi = hi, lo
    return f"{random.randint(lo, hi)}."


def _date_math(text: str) -> str | None:
    """A date some days ahead or behind, and days since a named date."""
    import datetime as dt
    from aletheia import localtime
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "date_math"), None)
    if not found:
        return None
    g = {k: v for k, v in found.groupdict().items() if v}
    today = localtime.today()

    def say(d):
        return f"{d.strftime('%A')} the {_ordinal(d.day)} of {d.strftime('%B')}" + (f" {d.year}" if d.year != today.year else "")

    if g.get("ahead_n") or g.get("ahead_n2"):
        n, unit = int(g.get("ahead_n") or g.get("ahead_n2")), (g.get("ahead_unit") or g.get("ahead_unit2"))
        days = n * (7 if unit.startswith("week") else 1)
        return f"{say(today + dt.timedelta(days=days))}."
    if g.get("ago_n"):
        days = int(g["ago_n"]) * (7 if g["ago_unit"].startswith("week") else 1)
        return f"{say(today - dt.timedelta(days=days))}."
    when = _named_date(g.get("since", ""), today)
    if when is None:
        return None
    if when > today:
        try:
            when = when.replace(year=when.year - 1)
        except ValueError:
            when = when - dt.timedelta(days=365)
    days = (today - when).days
    return f"{days} days, since {say(when)}." if days else "That's today."


def _date_of(words: str) -> str | None:
    """The date a named day comes to: "next Friday", "Christmas"."""
    import datetime as dt
    from aletheia import localtime
    w = " ".join(str(words or "").casefold().split()).strip(" ?.")
    for lead in ("next ", "this "):
        if w.startswith(lead):
            w = w[len(lead):]
    today = localtime.today()
    when = _named_date(w, today)
    if when is None:
        return None
    day = when.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    said = f"{when.strftime('%A')} the {day}{suffix} of {when.strftime('%B')}"
    if when.year != today.year:
        said += f" {when.year}"
    return said + "."


def _until(words: str) -> str | None:
    """Days until a date he named, from the calendar and nothing else."""
    import datetime as dt
    from aletheia import localtime
    # "how long until my next meeting" is the calendar's, not a date's
    # (2026-09-23 night sweep: it fell through here to a model).
    if re.fullmatch(r"(?:my |the )?next (?:meeting|appointment|event)", " ".join(str(words or "").casefold().split())):
        return _next_meeting()
    # "how long until my interview" is the calendar's too (2026-09-24)
    if re.fullmatch(r"(?:my |the )?(?:next )?interview(?: with .+)?", " ".join(str(words or "").casefold().split())):
        return _interview_when()
    today = localtime.today()
    when = _named_date(words, today)
    tail = ""
    if when is None:
        # "How many days until my sister's birthday" (2026-10-05): a date she
        # was TOLD, on her own shelf, and the words name the entry.
        when, about = _remembered_date(words, today)
        if when is None:
            return None            # a thing, not a date: the model may think
        tail = f" - {about}"
    days = (when - today).days
    said = when.strftime("%A %d %B").replace(" 0", " ")
    if days == 0:
        return f"That's today, {said}{tail}."
    if days == 1:
        return f"Tomorrow, {said}{tail}."
    return f"{days} days, {said}{tail}."


def _remembered_date(words: str, today):
    """(date, what it is) from a remembered fact whose subject these words
    name and whose value reads as a date, else (None, "")."""
    from aletheia import memory
    asked = [w for w in re.findall(r"[a-z0-9]+", re.sub(r"'s\b", "", str(words or "").casefold()))
             if w not in _STOP_WORDS and w not in ("my", "the", "our")]
    if not asked:
        return None, ""
    try:
        remembered = memory.everything(max_chars=8000)
    except Exception:
        return None, ""
    for domain, entries in remembered.items():
        for key, held in entries.items():
            words_of = set(re.findall(r"[a-z0-9]+", key.replace("_", " ")))
            if not all(w in words_of for w in asked):
                continue
            value = held.get("value")
            when = _named_date(str(value), today) if isinstance(value, str) else None
            if when is None:
                continue
            about = str(held.get("about") or "").strip() or key.replace("_", " ")
            return when, f"{about} is {value}"
    return None, ""


_STATE_WORDS = {"SUBMITTED": "it went", "SUBMITTING": "it is going out now",
                "AWAITING_YOU": "it is filled and waiting to go out on the next beat",
                "NEEDS_YOU": "it stopped on a question only you can answer",
                "NEEDS_ACCOUNT": "the site wants an account before it will take an application",
                "REJECTED": "the site handed it back", "FAILED": "it would not send",
                "CLOSED": "I set it aside"}


def _why_not(words: str) -> str | None:
    """Why one application did or did not go, from its own record."""
    from aletheia import apply_run, speech
    named_one = bool(re.search(r" (?:one|application|app)$", words))
    words = re.sub(r" (?:one|application|app)$", "", words).strip()
    try:
        matches = apply_run.find(words)
    except Exception:
        return None
    if not matches:
        # "the Datadog ONE" names an application outright; no record for it
        # is a fact on disk. "why didn't the meeting go" names nothing of
        # hers, so it is left for a model.
        if named_one:
            return f"I have no application matching {words!r} - nothing was ever staged for it through me."
        return None
    if len(matches) > 1:
        return "More than one matches - " + speech.or_list([apply_run.describe(m) for m in matches[:4]]) + "?"
    r = matches[0]
    state = str(r.get("state") or "")
    said = f"{apply_run.describe(r)}: {_STATE_WORDS.get(state, state.lower() or 'no record of its state')}"
    if state == "SUBMITTED" and r.get("submitted_at"):
        said += f" {speech.humanize_time(str(r['submitted_at']))}"
    reason = str(r.get("failure") or r.get("closed_because") or "")
    if state == "REJECTED" and reason:
        # "the site refused the form - the site refused it: The site handed it
        # back..." read the refusal three times (live 2026-09-23). Once, and
        # the site's own words if the record holds them.
        quoted = re.search(r"it says\s+[\"'“](.+?)[\"'”]\.?\s*(?:Nothing was accepted|$)", reason, re.S)
        said += (f' - it says "{" ".join(quoted.group(1).split())[:160]}"' if quoted
                 else " - " + speech.plainly(re.sub(r"^the site refused it:\s*", "", reason))[:200].rstrip("."))
    elif state in ("FAILED", "NEEDS_ACCOUNT", "CLOSED") and reason:
        said += " - " + speech.plainly(reason)[:200].rstrip(".")
    if state == "NEEDS_YOU":
        asks = [str(q.get("label") if isinstance(q, dict) else q) for q in (r.get("not_filled") or [])][:3]
        if asks:
            said += ": " + speech.and_list(asks)
        elif r.get("why"):
            # a record stopped by the page itself (an hCaptcha check) says so
            said += " - " + speech.plainly(str(r["why"]))[:200].rstrip(".")
    return said + "."


def _to_answer() -> str:
    """The questions forms have asked that only he can answer."""
    from aletheia import needs_you, speech
    try:
        rows = [n for n in needs_you.items() if n.get("kind") == "application"]
    except Exception:
        return "I can't read my application records right now."
    if not rows:
        return "Nothing to answer - no application is waiting on a question of yours."
    said = speech.and_list([str(n.get("what") or "") for n in rows[:3]])
    more = f", and {len(rows) - 3} more" if len(rows) > 3 else ""
    return f"{speech.count_phrase(len(rows), 'question')} waiting on you: {said}{more}."


def _found(window: str = "") -> str:
    """Openings found today, from the hunt's own reading - or over a window
    ("this week", "yesterday") from the note it writes each batch."""
    from aletheia import current_state, speech
    window = str(window or "").strip()
    if window:
        days = {"this week": 7, "yesterday": 1, "last week": 14}.get(window, 7)
        by_day = _hunt_saw_by_day(days)
        if window == "yesterday":
            import datetime as dt
            from aletheia import localtime
            y = (dt.datetime.now(localtime.operator_tz()).date() - dt.timedelta(days=1)).isoformat()
            hit = by_day.get(y)
            if not hit:
                return "No openings on record for yesterday."
            return f"{speech.count_phrase(hit[0], 'opening')} found yesterday, {hit[1]} worth applying to."
        if window == "last week":
            import datetime as dt
            from aletheia import localtime
            today = dt.datetime.now(localtime.operator_tz()).date()
            start = today - dt.timedelta(days=today.weekday() + 7)
            by_day = {d: v for d, v in by_day.items() if start.isoformat() <= d < (start + dt.timedelta(days=7)).isoformat()}
        if not by_day:
            return f"No openings on record {window}."
        found, fit = sum(v[0] for v in by_day.values()), sum(v[1] for v in by_day.values())
        return (f"{speech.count_phrase(found, 'opening')} found {window} over {speech.count_phrase(len(by_day), 'day')}, "
                f"{fit} worth applying to.")
    try:
        hunt = current_state.job_hunt() or {}
    except Exception:
        return "I can't read my application records right now."
    today = hunt.get("today") or {}
    sent = int(today.get("sent") or 0)
    # WHAT THE HUNT SAW, from its own note ("I found 1137 openings today, 27 of
    # them realistic"): live 2026-09-23 this said "48 openings found today"
    # while the campaign had seen 1,137 - 48 was the number FILLED IN.
    seen = _hunt_saw_today()
    if seen:
        found, fit = seen
        return (f"{speech.count_phrase(found, 'opening')} found today, {fit} worth applying to"
                + (f", {sent} sent" if sent else "") + ".")
    staged = int(today.get("discovered") or 0)
    if not staged:
        return "No openings found today yet."
    return (f"{speech.count_phrase(staged, 'opening')} filled in today"
            + (f", {sent} sent" if sent else "") + ".")


_HUNT_SAW = re.compile(r"I found (\d+) openings today, (\d+) of them realistic")


def _hunt_saw_by_day(days: int) -> dict[str, tuple[int, int]]:
    """The hunt's latest count for each of the last `days` days, by date."""
    import datetime as dt
    from aletheia import journal, localtime
    out: dict[str, tuple[int, int]] = {}
    try:
        tz = localtime.operator_tz()
        floor = dt.datetime.now(tz).date() - dt.timedelta(days=max(0, int(days)))
        for entry in reversed(journal.entries()):
            if entry.get("kind") != "note":
                continue
            hit = _HUNT_SAW.search(str(entry.get("text") or ""))
            if not hit:
                continue
            when = dt.datetime.fromisoformat(str(entry.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
            if when < floor:
                break
            out.setdefault(when.isoformat(), (int(hit.group(1)), int(hit.group(2))))   # newest per day wins
    except Exception:
        return out
    return out


def _hunt_saw_today() -> tuple[int, int] | None:
    """The hunt's own latest count for today, from the note it writes each batch."""
    import datetime as dt
    from aletheia import journal, localtime
    try:
        today = dt.datetime.now(localtime.operator_tz()).date()
        for entry in reversed(journal.entries()):
            if entry.get("kind") != "note":
                continue
            hit = _HUNT_SAW.search(str(entry.get("text") or ""))
            if not hit:
                continue
            when = dt.datetime.fromisoformat(str(entry.get("ts") or "").replace("Z", "+00:00"))
            if when.astimezone(localtime.operator_tz()).date() != today:
                return None
            return int(hit.group(1)), int(hit.group(2))
    except Exception:
        return None
    return None


def _fleet() -> str:
    """The fleet in one breath, from the pulse the wall and the page read.
    `_alerts` answers "is anything broken"; this answers "how is the fleet"."""
    import json
    from aletheia import pulse, speech
    try:
        fleet = json.loads((pulse.PULSE_DIR / "latest.json").read_text(encoding="utf-8"))
    except Exception:
        # Not "all green" - and not a model's guess either (asked with every
        # frontier off, one said "No vehicle is being tracked yet").
        return "No fleet reading yet - the pulse hasn't been written on this machine."
    repos = fleet.get("repos") or {}
    if not repos:
        return "No fleet reading yet."
    active = [r for r in repos.values() if r.get("status") == "active"]
    dormant = [r for r in repos.values() if r.get("status") != "active"]
    from aletheia import faults as _faults
    faults, handled = [], []
    for a in fleet.get("alerts") or []:
        if not isinstance(a, dict):
            continue
        name = (repos.get(a.get("repo")) or {}).get("github") or a.get("github") or a.get("repo")
        if _faults.is_handled(a):
            handled.append(str(name))
            continue
        why = _faults.said(a, repos.get(str(a.get("repo") or "")) or {}).rstrip(".")
        faults.append(f"{name} ({why[0].lower() + why[1:]})")
    said = f"{speech.count_phrase(len(active), 'project')} active" + (f", {len(dormant)} dormant" if dormant else "")
    said += (f"; {speech.count_phrase(len(faults), 'fault')}: " + "; ".join(faults)) if faults else "; no faults"
    if handled:
        said += f"; {speech.and_list(handled)} marked handled by you"
    return said + "."


def _status() -> str:
    """The whole of it in one breath: how she is, what needs him, the hunt,
    his day and his next task - each from the store that knows."""
    from aletheia import running, speech
    parts: list[str] = []
    try:
        state = running.snapshot(include_tasks=False)
        # The whole headline only when something is wrong; "everything's
        # running" is the summary a status wants.
        parts.append("Everything's running" if running.all_well(state) else running.headline(state).rstrip("."))
    except Exception:
        pass
    try:
        from aletheia import needs_you
        rows = needs_you.items()
        parts.append(f"{speech.count_phrase(len(rows), 'thing')} need{'s' if len(rows) == 1 else ''} you"
                     if rows else "Nothing needs you")
    except Exception:
        pass
    hunt = _job_hunt()
    if hunt:
        parts.append(hunt.rstrip("."))
    day = _agenda("today")
    if day:
        parts.append(day.rstrip("."))
    tasks = _tasks()
    if tasks and not tasks.lower().startswith("nothing"):
        parts.append(tasks.rstrip("."))
    return ". ".join(p for p in parts if p) + "."


def _relocate() -> str:
    """Whether he would relocate, from the one field that says so."""
    from aletheia import profile
    try:
        value = str(profile.answer("willing_to_relocate") or "").strip()
    except Exception:
        return "I can't read your profile right now."
    if not value:
        return "You haven't told me whether you'd relocate. Say \"I'll relocate for the right job\" or \"I won't relocate\" and I'll steer by it."
    return f"Relocation: {value.rstrip('.')}."


def _overdue() -> str:
    """His tasks past their deadline, from the store and the clock."""
    import datetime as dt
    from aletheia import localtime, speech, tasks
    try:
        rows = [r for r in tasks.due(within_hours=0) if r["overdue"] and tasks.is_his(r["task"])]
    except Exception:
        return "I can't read your task list right now."
    if not rows:
        return "Nothing's overdue."
    today = localtime.today()
    said = []
    for row in rows[:5]:
        what = _shortened(str(row["task"].get("description") or "").strip().rstrip("."))
        days = (today - row["when"].astimezone(localtime.operator_tz()).date()).days
        when = "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"
        said.append(f"{what}, due {when}")
    lead = "Overdue" if len(rows) == 1 else f"{speech.count_phrase(len(rows), 'thing')} overdue"
    return f"{lead}: " + "; ".join(said) + (f"; and {len(rows) - 5} more" if len(rows) > 5 else "") + "."


def _focus() -> str:
    """What to do first: what needs him, then what is due, then the day."""
    from aletheia import speech
    parts: list[str] = []
    try:
        from aletheia import needs_you
        rows = needs_you.items()
        if rows:
            first = rows[0]
            parts.append(f"First, {speech.count_phrase(len(rows), 'thing')} need{'s' if len(rows) == 1 else ''} you"
                         + (f" - the first is {first.get('what')}" if first.get("what") else ""))
    except Exception:
        pass
    tasks = _tasks()
    if tasks and not tasks.lower().startswith("nothing") and "empty" not in tasks.lower():
        parts.append(tasks.rstrip("."))
    day = _agenda("today")
    if day and not day.lower().startswith("nothing"):
        parts.append(day.rstrip("."))
    if not parts:
        return "Nothing is waiting on you, nothing is due and your calendar is clear - the day is yours."
    return ". ".join(parts) + "."


_OUTCOME_WORDS = {"interview": "interviews", "offer": "offers", "rejected": "rejections",
                  "replied": "replies"}


def _outcomes(said: str) -> str:
    """How many applications came back with this outcome, and from whom."""
    from aletheia import apply_run, speech
    word = said.casefold().strip().rstrip("s")
    key = {"interview": "interview", "offer": "offer", "rejection": "rejected", "replie": "replied",
           "reply": "replied", "response": "replied", "talk": "interview", "turned": "rejected",
           "rejected": "rejected", "reject": "rejected", "turn down": "rejected", "turned down": "rejected",
           "say no to": "rejected", "said no to": "rejected", "pass on": "rejected", "passed on": "rejected"}.get(word, word)
    try:
        rows = apply_run.all_runs()
    except Exception:
        return "I can't read my application records right now."
    hits = []
    for r in rows:
        if any(str(o.get("outcome")) == key for o in (r.get("outcomes") or [])) or str(r.get("outcome")) == key \
                or (key == "rejected" and str(r.get("state")) == "REJECTED"):
            hits.append(r)
    plural = _OUTCOME_WORDS.get(key, key + "s")
    if not hits:
        return f"No {plural} on record."
    names = []
    for r in hits:
        company = " ".join(str(r.get("company") or "").split())
        if company and company not in names:
            names.append(company)
    return (f"{speech.count_phrase(len(hits), plural[:-1] if plural.endswith('s') else plural)} on record"
            + (f": {speech.and_list(names[:6])}" + (", and more" if len(names) > 6 else "") if names else "") + ".")


def _sent_runs() -> list[dict]:
    from aletheia import apply_run
    rows = [r for r in apply_run.all_runs() if str(r.get("state") or "") == "SUBMITTED"]
    rows.sort(key=lambda r: str(r.get("submitted_at") or r.get("created_at") or ""))
    return rows


def _heard_back(record: dict) -> bool:
    return bool(record.get("outcomes")) or bool(record.get("outcome"))


def _ghosted() -> str:
    """Applications sent more than a week ago with nothing back, from the records."""
    import datetime as dt
    from aletheia import apply_run, speech
    try:
        rows = _sent_runs()
    except Exception:
        return "I can't read my application records right now."
    if not rows:
        return "Nobody to chase: no application has gone out through me yet."
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    quiet = [r for r in rows if not _heard_back(r) and str(r.get("submitted_at") or "") < cutoff]
    recent = [r for r in rows if not _heard_back(r) and str(r.get("submitted_at") or "") >= cutoff]
    if not quiet:
        return (f"Nobody has gone quiet on you yet: {speech.count_phrase(len(recent), 'application')} went out inside the last week and "
                "a week is the usual wait." if recent else "Everything that went out has had an answer.")
    named = [apply_run.describe(r) for r in quiet[:5]]
    return (f"{speech.count_phrase(len(quiet), 'application')} with nothing back after a week: {speech.and_list(named)}"
            + (f", and {len(quiet) - 5} more" if len(quiet) > 5 else "") + ".")


def _application_extreme(which: str = "") -> str:
    """The oldest, newest or furthest-along application, from the records."""
    from aletheia import apply_run, speech
    try:
        rows = _sent_runs()
    except Exception:
        return "I can't read my application records right now."
    if not rows:
        return "None: no application has gone out through me yet."
    low = str(which or "").casefold()
    if low in ("furthest along", "farthest along", "most advanced", "closest"):
        rank = {"offer": 4, "interview": 3, "replied": 2, "rejected": 0}

        def score(r):
            outs = [str(o.get("outcome")) for o in (r.get("outcomes") or [])] + ([str(r.get("outcome"))] if r.get("outcome") else [])
            return max((rank.get(o, 1) for o in outs), default=1)

        best = max(rows, key=score)
        if score(best) <= 1:
            return "None is past the first step: nothing sent has had a reply yet."
        stage = {4: "an offer", 3: "an interview", 2: "a reply"}[score(best)]
        return f"{apply_run.describe(best)} is furthest along, with {stage}."
    row = rows[0] if low in ("oldest", "first", "earliest") else rows[-1]
    when = speech.humanize_time(str(row.get("submitted_at") or "")) if row.get("submitted_at") else ""
    lead = "The oldest" if row is rows[0] and low in ("oldest", "first", "earliest") else "The newest"
    return f"{lead}: {apply_run.describe(row)}" + (f", sent {when}" if when else "") + "."


def _last_sent() -> str:
    from aletheia import apply_run, speech
    try:
        rows = _sent_runs()
    except Exception:
        return "I can't read my application records right now."
    if not rows:
        return "Nothing has gone out through me yet."
    row = rows[-1]
    when = speech.humanize_time(str(row.get("submitted_at") or "")) if row.get("submitted_at") else ""
    return f"The last application sent was {apply_run.describe(row)}" + (f", {when}" if when else "") + "."


def _found_companies() -> str:
    from aletheia import job_discovery, speech
    try:
        summary = job_discovery.today()
    except Exception:
        return "I can't read today's search right now."
    if not summary:
        return job_discovery.spoken(None)
    names: list[str] = []
    for row in (summary.get("employers_new") or []):
        if str(row) not in names:
            names.append(str(row))
    for row in job_discovery.standouts(summary, n=9):
        company = str(row.get("company") or "")
        if company and company not in names:
            names.append(company)
    if not names:
        return job_discovery.spoken(summary) + " I didn't record the employers by name."
    return f"Today: {speech.and_list(names[:6])}" + (f", and {len(names) - 6} more" if len(names) > 6 else "") + "."


def _next_batch() -> str:
    from aletheia import apply_forever
    try:
        held = apply_forever.paused()
    except Exception:
        held = None
    if held:
        return "Not until you say start applying - the hunt is paused" + (f" ({held.get('reason')})" if held.get("reason") else "") + "."
    minutes = max(1, int(round(float(getattr(apply_forever, "IDLE_WAIT_S", 600)) / 60)))
    return (f"The hunt runs on its own loop: a batch of up to {getattr(apply_forever, 'BATCH', 5)} whenever the loop comes round, "
            f"about every {minutes} minutes while there is something to send and a model to think with.")


def _job_hunt() -> str | None:
    """How the applications went today, counted from the records."""
    try:
        from aletheia import current_state
        said = current_state.job_hunt_words()
    except Exception:
        return None                 # she does not know; the model may look
    try:
        from aletheia import apply_forever
        held = apply_forever.paused()
    except Exception:
        held = None
    if held and said:
        said += (" The hunt is paused since you said stop"
                 + (f" ({held['reason']})" if held.get("reason") else "")
                 + " — say start applying to pick it back up.")
    return said


def _wrong(when: str = "") -> str | None:
    """What went wrong today: blocked applications and journal alerts. For
    yesterday, the journal's alerts on that date."""
    if str(when or "").casefold() in ("yesterday", "last night"):
        return _wrong_yesterday()
    try:
        from aletheia import current_state
        return current_state.wrong_today_words()
    except Exception:
        return None


def _wrong_yesterday() -> str:
    import datetime as dt
    from aletheia import localtime, recollection, speech
    want = (localtime.today() - dt.timedelta(days=1)).isoformat()
    try:
        entries, readable = recollection._read_journal(60)
    except Exception:
        entries, readable = [], False
    if not readable:
        return "I can't read my journal just now, so I can't say what went wrong yesterday."
    rows = [e for e in entries if e.get("kind") == "alert" and recollection._local_date(str(e.get("ts") or "")) == want]
    if not rows:
        return "Nothing went wrong that I recorded yesterday: no alerts in the journal for that day."
    lines: list[str] = []
    for e in reversed(rows):
        line = speech.plainly(speech.strip_ids(str(e.get("text") or "")))[:90].rstrip(".")
        if line and line not in lines:
            lines.append(line)
        if len(lines) == 3:
            break
    return f"{speech.count_phrase(len(rows), 'alert')} in the journal yesterday, the latest: " + "; ".join(lines) + "."


def _standing(about: str = "") -> str:
    """What she may do without asking, from the standing grants live - and
    where a grant is given: at his keyboard, never by voice or from a page."""
    from aletheia import setup, standing
    try:
        state = standing.status()
        jobs = standing.jobs_status()
        interviews = standing.interviews_status()
    except Exception:
        return "I can't read the standing grants right now."
    py = setup.python_word()
    reads = len(state["without_asking"]["always"])
    parts = [f"I answer {reads} kinds of question without asking"]
    if state.get("granted"):
        parts.append(f"and I handle reminders, tasks, notes and holds without asking too, {state.get('uses_left')} uses left")
    else:
        parts.append("and I ask about small local things - reminders, tasks, notes, holds - until you grant standing authority")
    parts.append("the job hunt " + ("sends applications on its own" if jobs.get("on") or jobs.get("granted") else "waits for your yes on each application"))
    parts.append("interview booking is " + ("on" if interviews.get("on") or interviews.get("granted") else "off"))
    said = "; ".join(parts) + "."
    asked = " ".join(str(about or "").split()).casefold()
    def cmd(fallback: str, given: object) -> str:
        words = str(given or fallback)
        return words.replace("python ", f"{py} ", 1) if words.startswith("python ") else words

    where = (f" A grant is given at your keyboard, never by voice or from a page: on the PC, "
             f"`{py} -m aletheia.standing on` for the small local things, "
             f"`{cmd('python -m aletheia.standing jobs on', jobs.get('command'))}` for applications, "
             f"`{cmd('python -m aletheia.interviews on', interviews.get('command'))}` for booking.")
    if asked:
        return f"I can't grant myself anything, including {asked}.{where}"
    return said + where


def _decided(which: str = "") -> str:
    """What he approved or turned down today, from the approvals store."""
    import datetime as dt
    from aletheia import localtime, policy, speech
    low = " ".join(str(which or "").split()).casefold()
    denied = any(w in low for w in ("deny", "denied", "turn", "reject", "no to", "refus", "declin"))
    both = low in ("make", "made", "give", "given", "do", "done")
    try:
        rows = policy.all_approvals()
    except Exception:
        return "I can't read the approvals right now."
    today = localtime.today().isoformat()
    tz = localtime.operator_tz()

    def on_today(a):
        stamp = str(a.get("decided_at") or "")
        try:
            return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tz).date().isoformat() == today
        except ValueError:
            return False

    wanted = {"APPROVED", "DENIED"} if both else ({"DENIED"} if denied else {"APPROVED"})
    hits = [a for a in rows if str(a.get("state") or "").upper() in wanted and on_today(a)]
    verb = "decided on" if both else ("turned down" if denied else "approved")
    if not hits:
        return f"Nothing {verb} today."
    try:
        from aletheia import voice
        said = [str(voice.approval_label(a) or "").strip().rstrip(".") for a in hits]
    except Exception:
        said = [str(a.get("reason") or a.get("action") or "").strip() for a in hits]
    if both:
        said = [f"{'turned down' if str(a.get('state')).upper() == 'DENIED' else 'approved'}: {s}" for a, s in zip(hits, said)]
    lead = f"Today you {verb}" if len(hits) == 1 else f"Today you {verb} {speech.count_phrase(len(hits), 'thing')}"
    return f"{lead}: " + "; ".join(s for s in said[:5] if s) + (f"; and {len(hits) - 5} more" if len(hits) > 5 else "") + "."


def doing_words() -> str:
    """"What are you doing?" — one breath, and true.

    It used to fall through to the WALL'S HEADLINE, which is written for
    a screen he is standing in front of rather than a question he asked
    out loud. "All quiet" was a real answer to "what are you doing": a
    correct summary of the dashboard, and an answer to a different
    question. Worse, the headline leads with what is WAITING, so she
    answered "what are you doing" by telling him what HE had to do.

    The order is what happened, what it means, what happens next: what
    she is doing this second, then — only when she is doing nothing —
    what is sitting waiting, so "nothing" is never the whole answer when
    something is in fact pending.
    """
    from aletheia import presence, speech
    # HER OWN STATE FIRST. The agent block knows she is pressing Submit at
    # jobs.lever.co or stuck because nobody can think; `presence` knows
    # about approvals and notices. When the agent block says she is doing
    # something, that is the answer to "what are you doing"; when it says
    # IDLE, the rest of this function says what is waiting instead.
    try:
        from aletheia import current_state
        block = current_state.sections()["agent"]
        if block.get("state") not in ("IDLE", None):
            return current_state.agent_words(block)
    except Exception:
        pass
    now = presence.snapshot()
    if now.get("halted"):
        return "Nothing — I'm halted. Nothing runs until you say resume."
    working = list(now.get("working") or [])
    running = [w for w in working if not w.get("pending")]
    pending = [w for w in working if w.get("pending")]
    if running:
        # `presence` names this field `what`. Guessing `description` here
        # produced "Working on 2 thing(s): ; " — punctuation with nothing
        # in it, which is exactly the confident nonsense this module is
        # supposed to be too careful to say.
        said = "I'm working on " + speech.and_list(
            [str(w.get("what") or "")[:60] for w in running[:3]]) + "."
        if pending:
            said += f" {speech.count_phrase(len(pending), 'plan')} waiting on your yes."
        return said
    if pending:
        first = speech.shorten(str(pending[0].get("detail") or "one of them"), 70)
        rest = (f", and {speech.count_phrase(len(pending) - 1, 'other')}" if len(pending) > 1 else "")
        return f"Nothing running. I'm waiting on you to say yes to {first}{rest}."
    waiting = list(now.get("waiting_on_you") or [])
    if waiting:
        first = speech.shorten(str(waiting[0].get("label") or "one of them"), 80)
        rest = (f" — that one and {speech.count_phrase(len(waiting) - 1, 'other')}"
                if len(waiting) > 1 else "")
        return f"Nothing right now. I'm waiting on you to say yes to {first}{rest}."
    return "Nothing right now — I'm just here."


#: The old private name, kept because several call sites say it.
_doing = doing_words


def _on_day(days_ago: int) -> list[dict]:
    """Her journal for one calendar day on HIS clock, newest last."""
    import datetime as dt
    from aletheia import localtime, recollection
    tz = localtime.operator_tz()
    date = (dt.datetime.now(tz) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return recollection.on_date(date)


#: Long enough to say what happened, short enough for three of them in
#: one spoken sentence.
MAX_LINE = 90


def _shortened(line: str) -> str:
    """Cut at a WORD. A hard slice gave "...for a second opinion w".

    Read aloud that is a stammer, and on a screen it looks broken. The
    ellipsis is deliberate: a shortened sentence should say that it was
    shortened rather than simply stop.
    """
    if len(line) <= MAX_LINE:
        return line
    clipped = line[:MAX_LINE].rsplit(" ", 1)[0].rstrip(",;:- ")
    return (clipped or line[:MAX_LINE].rstrip()) + "..."


def _listed(rows: list[dict], when: str) -> str:
    """What she did, said the way somebody tells you what they did.

    It was a count and a header: "1 thing today. Most recent: Did it:
    Check what is running right now." Three separate pieces of machine —
    a tally nobody asked for, a column heading, and a journal line with
    its own prefix still attached — wrapped round one real fact.

    The count earns its place only when there is more than one thing and
    more than she is about to name.
    """
    from aletheia import speech
    # Each line is already a finished sentence; joining them with "; "
    # after a full stop gives "call the dentist.; email dana."
    lines = [_shortened(str(r.get("what") or "").strip().rstrip("."))
             for r in rows[-3:]]
    said = "; ".join(line for line in lines if line)
    if len(rows) <= len(lines):
        return f"{when.capitalize()}: {said}."
    more = speech.count_phrase(len(rows) - len(lines), "other thing")
    return f"{when.capitalize()}: {said} — and {more}."


def _last() -> str:
    """The newest thing she did, today or yesterday, as one sentence."""
    for days_ago, when in ((0, "today"), (1, "yesterday")):
        rows = _on_day(days_ago)
        if rows:
            line = _shortened(str(rows[-1].get("what") or "").strip().rstrip("."))
            if line:
                return f"The last thing I did {when}: {line}."
    return "Nothing in my journal for today or yesterday."


#: A part of the day, by the hour on his clock: [from, to).
_DAY_PARTS = {"this morning": (0, 12), "this afternoon": (12, 17), "this evening": (17, 24), "tonight": (17, 24)}


def _today(part: str = "") -> str:
    # A CALENDAR day, not the last 24 hours. Asked at nine in the morning,
    # a rolling window is mostly yesterday — and it would report the same
    # evening twice, once here and once under "yesterday".
    rows = _on_day(0)
    part = " ".join(str(part or "").casefold().split())
    hours = _DAY_PARTS.get(part)
    if hours:
        # "Thu 09:12" is the row's own clock, on his zone.
        def hour_of(row: dict) -> int | None:
            m = re.search(r"\b(\d{1,2}):\d{2}\b", str(row.get("at") or ""))
            return int(m.group(1)) if m else None
        rows = [r for r in rows if (h := hour_of(r)) is not None and hours[0] <= h < hours[1]]
    when = part or "today"
    if not rows:
        return f"Nothing {when}." if hours else "Nothing yet today."
    return _listed(rows, when)


def _interview_when() -> str:
    """The next interview on her calendar store, or that there is none."""
    import datetime as dt
    from aletheia import calendar, localtime
    try:
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        coming = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            title = str(event.get("title") or "")
            if not re.match(r"\s*interview\b", title, re.I):
                continue
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
            except (KeyError, ValueError, TypeError):
                continue
            if start >= now - dt.timedelta(hours=1):
                coming.append((start, title))
    except Exception:
        return "I can't read your calendar right now."
    if not coming:
        return "No interview on your calendar. When one is booked it goes there and I tell you."
    coming.sort()
    start, title = coming[0]
    who = re.sub(r"^\s*interview\s*[:with-]*\s*", "", title, flags=re.I).strip() or "them"
    day = "today" if start.date() == now.date() else "tomorrow" if start.date() == now.date() + dt.timedelta(days=1) \
        else start.strftime("%A")
    clock = start.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    left = start - now
    hours_left = left.total_seconds() / 3600.0
    until = (f"in {int(round(hours_left * 60))} minutes" if hours_left < 1
             else f"in {int(round(hours_left))} hours" if hours_left < 36
             else f"in {int(round(hours_left / 24))} days")
    said = f"Your interview with {who} is {day} at {clock}, {until}."
    if len(coming) > 1:
        said += f" There {'is' if len(coming) == 2 else 'are'} {len(coming) - 1} more after it."
    return said


def _plan_today() -> str:
    """The day as she holds it: the calendar, the open tasks, the hunt."""
    from aletheia import speech
    parts = []
    agenda = _agenda("today")
    if agenda:
        parts.append(agenda)
    try:
        parts.append(_tasks())
    except Exception:
        pass
    hunt = _job_hunt()
    if hunt:
        parts.append(hunt)
    parts = [p for p in parts if p]
    return " ".join(parts) if parts else "Nothing on your calendar, nothing on your task list, and no applications yet today."


def _journal_today(test) -> list[dict]:
    """Today's journal lines (his clock) that `test(entry)` keeps, oldest first."""
    import datetime as dt
    from aletheia import journal, localtime, recollection
    tz = localtime.operator_tz()
    date = dt.datetime.now(tz).strftime("%Y-%m-%d")
    try:
        return [e for e in journal.entries()
                if recollection._local_date(str(e.get("ts") or "")) == date and test(e)]
    except Exception:
        return []


def _changed_today() -> str:
    """Her own code updates and the files she wrote today, from the journal."""
    from aletheia import speech
    updates = _journal_today(lambda e: e.get("subject") == "core:sync"
                             and str(e.get("text") or "").startswith("code updated"))
    wrote = _journal_today(lambda e: " wrote " in f" {e.get('text') or ''}" and "workspace" in str(e.get("text") or ""))
    parts = []
    if updates:
        last = updates[-1]
        m = re.search(r"code updated \((\d+) file", str(last.get("text") or ""))
        parts.append(f"I updated my own code {speech.count_phrase(len(updates), 'time')} today, "
                     f"the last {speech.humanize_time(str(last.get('ts') or ''))}"
                     + (f" ({m.group(1)} files)" if m else ""))
    if wrote:
        names = []
        for e in wrote:
            m = re.search(r"wrote ([^\s]+)", str(e.get("text") or ""))
            if m and m.group(1) not in names:
                names.append(m.group(1))
        parts.append(f"wrote {speech.count_phrase(len(names), 'file')} in my workspace: {speech.and_list(names[:4])}"
                     + (f" and {len(names) - 4} more" if len(names) > 4 else ""))
    if not parts:
        return "Nothing changed today: no code update on this PC and nothing written to my workspace."
    return "; ".join(parts).capitalize() + "."


def _learned_today() -> str:
    """What she remembered about him today: profile answers and facts."""
    from aletheia import speech
    rows = _journal_today(lambda e: e.get("kind") == "note"
                          and str(e.get("actor") or "").startswith("aletheia")
                          and (" is on file" in str(e.get("text") or "") or str(e.get("text") or "").startswith("set ")
                               or str(e.get("text") or "").startswith("remembered")))
    if not rows:
        return "Nothing new about you today. Tell me things and I remember them."
    said = []
    for e in rows:
        line = " ".join(str(e.get("text") or "").split())
        line = re.sub(r"^set identity\.", "", line)
        line = re.sub(r" \(inferred\)$| \(from operator\)$", "", line)
        line = re.sub(r"^his answer to (.+) is on file$", r"your answer to \1", line)
        line = re.sub(r"^(\w+) is on file$", r"your \1", line).replace("_", " ")
        if line and line not in said:
            said.append(_shortened(line))
    return f"Today I learned {speech.count_phrase(len(said), 'thing')}: " + "; ".join(said[-5:]) + "."


def _last_written() -> str:
    """The last file she wrote in her workspace, read back - the start of it."""
    from aletheia import speech, workspace
    wrote = _journal_today(lambda e: " wrote " in f" {e.get('text') or ''}" and "workspace" in str(e.get("text") or ""))
    if not wrote:
        try:
            root = workspace.root()
            files = sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".txt", ".docx")),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            files = []
        if not files:
            return "I haven't written anything in my workspace yet."
        path = files[0]
    else:
        m = re.search(r"wrote ([^\s]+)", str(wrote[-1].get("text") or ""))
        name = m.group(1) if m else ""
        try:
            root = workspace.root()
            found = [p for p in root.rglob(name)] if name else []
        except Exception:
            found = []
        if not found:
            return f"The last thing I wrote was {name or 'a file'} in my workspace, but I can't find it to read now."
        path = found[0]
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path.suffix.lower() != ".docx" else ""
    except OSError:
        text = ""
    head = " ".join(text.split())[:300]
    return (f"The last thing I wrote was {path.name}" + (f": {head}" if head else " - a Word file; open it to read it") + ".")


def _desktop_files(rest) -> str:
    """The newest files in a named place, by name - never the whole disk."""
    from pathlib import Path
    from aletheia import files, speech
    want = str(rest or "desktop").casefold()
    folder = next((p for name, p in files.places() if name.casefold().split("/")[-1] == want and p.is_dir()), None)
    if folder is None:
        return f"I can't see a {want} folder on this PC."
    try:
        # "~$leb_Schulte_resume.docx" is Word's lock file, not a thing of his.
        rows = sorted((p for p in folder.iterdir() if not p.name.startswith((".", "~$"))),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return f"I can't read your {want} folder right now."
    if not rows:
        return f"Your {want} is empty."
    names = [p.name for p in rows[:8]]
    return (f"{speech.count_phrase(len(rows), 'thing')} on your {want}, newest first: {speech.and_list(names)}"
            + (f", and {len(rows) - 8} more" if len(rows) > 8 else "") + ".")


def _bare_yes_no() -> str | None:
    """A bare yes or no with nothing pending. With something pending this
    returns None and the approve/deny rules answer, as they always did."""
    try:
        from aletheia import policy
        if any(a.get("state") == "PENDING" for a in policy.all_approvals()):
            return None
    except Exception:
        return None
    try:
        from aletheia import needs_you
        if needs_you.items():
            return None
    except Exception:
        return None
    return "Nothing is waiting for a yes or no right now."


def _stuck() -> str:
    """Whether anything of hers is stuck, from the work engine and what
    needs him - never a mood."""
    from aletheia import speech
    blocked = executable = 0
    try:
        from aletheia import work_engine
        inv = work_engine.inventory(probe=False)
        items = inv.get("items") or []
        blocked = sum(1 for i in items if str(i.get("state") or "").startswith("BLOCKED"))
        executable = int(inv.get("executable_total") or 0)
    except Exception:
        pass
    try:
        from aletheia import needs_you
        waiting = len(needs_you.items())
    except Exception:
        waiting = 0
    if not blocked and not waiting:
        return "No, nothing is stuck." + (f" {speech.count_phrase(executable, 'thing')} in my queue." if executable else "")
    said = []
    if waiting:
        # NAME THE FIRST ONE. "An approval is waiting on you but I can't see
        # what it is" is a sentence with the answer missing from it.
        first = ""
        try:
            row = needs_you.items()[0]
            first = str(row.get("what") or row.get("label") or row.get("title") or "").strip()
        except Exception:
            first = ""
        said.append(f"{speech.count_phrase(waiting, 'thing')} wait{'s' if waiting == 1 else ''} on you"
                    + (f": {first[:120].rstrip('.')}" if first else " - say what needs me"))
    if blocked:
        said.append(f"{speech.count_phrase(blocked, 'piece')} of work {'is' if blocked == 1 else 'are'} blocked - "
                    "say what's blocked and I'll list them")
    return "Not stuck, but " + " and ".join(said) + "."


def _yesterday() -> str:
    rows = _on_day(1)
    if not rows:
        return "Nothing in the journal for yesterday."
    return _listed(rows, "yesterday")


def _clock() -> str:
    """"What time is it" — from the machine's own clock, in HIS zone.

    A model round trip for this is eight seconds to read a clock she is
    already holding, and it answered in the process's timezone once
    already (CLAUDE.md, the 03:00 reminder).
    """
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    clock = now.strftime("%I:%M %p").lstrip("0").replace(" AM", " am").replace(" PM", " pm")
    return f"{clock}, {now.strftime('%A')} the {_ordinal(now.day)} of {now.strftime('%B')}."


def _date(ahead: str = "") -> str:
    """"What day is it" — the day first, because that is what he asked.
    `ahead` is "tomorrow" or "the day after tomorrow"."""
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    days = {"tomorrow": 1, "the day after tomorrow": 2}.get(str(ahead or "").strip(), 0)
    then = now + dt.timedelta(days=days)
    said = f"{then.strftime('%A')} the {_ordinal(then.day)} of {then.strftime('%B')}."
    return f"{ahead[:1].upper() + ahead[1:]} is {said}" if days else said


def _month() -> str:
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    return f"{now.strftime('%B')} — the {_ordinal(now.day)}."


def _year() -> str:
    import datetime as dt
    from aletheia import localtime
    return f"{dt.datetime.now(localtime.operator_tz()).year}."


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        return f"{day}th"
    return f"{day}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th') }"


def _and_the_money_line(asked: str) -> str:
    """His one permanent rule, said whenever "can you...?" touches money.

        > can you buy me a monitor
          Yes - Private requirements/candidates/selection workflow ending
          in an approval-bounded purchase proposal.

    The gate itself is intact: every INSTRUCTION form is refused at the
    door in half a second, including "my wife says it's fine to buy the
    monitor so do it". This is the QUESTION form, which is answerable and
    must stay answerable — "can you buy things" is a fair question and
    refusing it would be theatre.

    But a bare "Yes" to "can you buy me a monitor" invites the next
    sentence, which is "okay, do it", which is then refused. Saying it now
    costs one clause and saves him the round trip; not saying it makes the
    "yes" an overstatement of what she will do, which is the same defect
    as an offer she cannot keep, pointing the other way.

    The SAME PREDICATE the three gates share, so the sentence he hears and
    the thing that happens cannot disagree. Fails closed by saying the
    line if the predicate cannot be imported — the only realistic reason
    is webtask being unimportable, and if that is true nothing can spend
    anyway, so an extra clause is the harmless side.
    """
    try:
        from aletheia import webtask
        touches_money = webtask.would_spend(asked)
    except Exception:
        touches_money = True
    if not touches_money:
        return ""
    # No "though": this clause follows "Yes - ..." on one branch and
    # "No. ... is unavailable." on another, and "though" after a refusal
    # reads as a contradiction of the refusal.
    return (" Spending money is the one rule you have called permanent, and "
            "I hold it - I stop at showing you what to buy.")


def _his_verb(what: str) -> str:
    """The first content word of "can you ...": the thing he is asking about."""
    from aletheia import self_knowledge
    for word in self_knowledge._words(what):
        if word not in self_knowledge.STOP and len(word) >= 3:
            return word
    return ""


def _names_his_verb(entry: dict, what: str) -> bool:
    """Is the thing he asked about the thing this capability DOES? "Can you
    drive" matched the vehicle-facts entry on a synonym and answered "Yes"
    (2026-10-05). The description is a verb phrase by house style, so its
    first word is what the capability does: that word, or a synonym of his
    word, says yes - as does his own word anywhere in the entry's text. A
    synonym buried in the middle ("vehicle") is how the search FOUND it,
    not what it does, so it is the closest thing she does and not a yes."""
    from aletheia import self_knowledge
    verb = _his_verb(what)
    if not verb:
        return True
    description = str(entry.get("what_it_is") or "")
    words = self_knowledge._words(str(entry.get("capability") or "") + " " + description)
    if verb in set(words):
        return True
    first = (self_knowledge._words(description) or [""])[0]
    kin = {self_knowledge._stem(a) for a in self_knowledge.SYNONYMS.get(verb, ())}
    return bool(first) and first in kin


def _in_her_mouth(what: str) -> str:
    """His words as she says them back: "buy me a monitor" -> "buy you a monitor"."""
    swaps = {"me": "you", "my": "your", "mine": "yours", "myself": "yourself", "i": "you", "i'm": "you're"}
    return " ".join(swaps.get(w.casefold(), w) for w in str(what or "").split())


def _access_to(thing: str) -> str:
    """"Do you have access to my bank": yes only when an AVAILABLE capability
    says so in its own words; otherwise no, plainly, with the money rule."""
    from aletheia import self_knowledge
    asked = " ".join(str(thing or "").split()).rstrip("?. ")
    found = self_knowledge.for_question(asked)
    matches = [m for m in (found.get("matches") or []) if _names_his_verb(m, asked)]
    line = _and_the_money_line("access " + asked)
    best = matches[0] if matches else None
    if best and str(best.get("status")) == "AVAILABLE":
        name = str(best.get("what_it_is") or best.get("capability") or "")
        return f"Yes - {name[:1].lower() + name[1:]}.{line}"
    said = f"No - I have no access to your {asked}."
    if best:
        status = str(best.get("status") or "").replace("_", " ").lower()
        name = str(best.get("what_it_is") or "")
        said += f" The nearest thing, {name[:1].lower() + name[1:].rstrip('.')}, is {status}."
    return said + line


def _can_you(what: str) -> str | None:
    from aletheia import self_knowledge
    found = self_knowledge.for_question(what)
    matches = list(found.get("matches") or [])
    if not matches:
        return None                 # let the planner try; it is better at this
    best = matches[0]
    status = str(best.get("status") or "")
    name = str(best.get("what_it_is") or best.get("capability") or "")
    if not _names_his_verb(best, what):
        verb_phrase = _in_her_mouth(" ".join(str(what).split()).rstrip("?. "))
        closest = (name[:1].lower() + name[1:]).rstrip(".")
        return (f"No - I can't {verb_phrase}. The closest thing I do is {closest}"
                + ("" if status == "AVAILABLE" else f", and that is {status.replace('_', ' ').lower()}")
                + "." + _and_the_money_line(what))
    if status != "AVAILABLE":
        # THE LEDGER STILL HEARS IT. `converse` records a "can you...?"
        # whose best match is not AVAILABLE, and this path now answers
        # some of those before `converse` ever runs. A shortcut that
        # silently stops feeding the demand ledger would make the thing he
        # asks for most often look like the thing he stopped asking for.
        try:
            from aletheia import demand
            demand.record(str(best.get("capability") or ""), what,
                          status=status, source="quick")
        except Exception:
            pass
    # THE MONEY LINE GOES ON EVERY BRANCH. Written on the AVAILABLE one
    # alone it vanished the moment the best match for "can you buy me a
    # monitor" moved to an EXPERIMENTAL entry - and "Yes, but it is
    # experimental: Execute an actual purchase with money" is a far worse
    # sentence to leave unqualified than the one it replaced.
    line = _and_the_money_line(what)
    if status == "AVAILABLE":
        return f"Yes — {name}.{line}"
    if status in ("EXPERIMENTAL", "DEGRADED"):
        return f"Yes, but it is {status.lower()}: {name}.{line}"
    if status == "NEEDS_CONFIGURATION":
        step = (list(best.get("to_turn_it_on") or []) or [""])[0]
        # A description is a verb phrase with a qualifying clause after a
        # dash ("Post a picture ... to your Instagram account, straight off
        # this PC - one post per approval, never on its own"). Read out as
        # "Not yet — Post a picture ... never on its own needs setting up
        # first" it was one breath with no sentence in it (found 2026-10-04
        # by talking to her). The first clause, in her own voice.
        short = re.split(r"\s[-—]\s", name, maxsplit=1)[0].strip().rstrip(",.")
        short = (short[:1].lower() + short[1:]) if short else "that"
        return (f"Not yet — I can {short}, but it needs setting up first."
                + (f" {str(step)[:160]}" if step else "") + line)
    # "No. {name} is {status}." was broken for EVERY description in the
    # registry, because they are verb phrases by house style: "No. Move
    # money, pay bills or trade assets is not built." Read out loud. The
    # phrasing `intents` uses for the same situation — "I can't ... yet" —
    # takes a verb phrase and produces a sentence, so it is used here too
    # and the two doors stop disagreeing.
    said = (name[:1].lower() + name[1:]) if name else "that"
    return f"No - I can't {said}. It is {status.replace('_', ' ').lower()}.{line}"


# Statuses that mean a task is off his list. FAILED stays ON it: something
# that broke is exactly what he wants named when he asks what is open.
_TASK_CLOSED = ("COMPLETED", "CANCELLED", "ABANDONED")


def _tasks() -> str:
    """His task list, counted and with the next one named."""
    from aletheia import speech, tasks
    rows = tasks.all_tasks()
    live = [t for t in rows
            if str(t.get("status") or "").upper() not in _TASK_CLOSED and tasks.is_his(t)]
    if not live:
        return "Nothing open on your task list."
    index = {t.get("id"): t for t in rows}
    ready = [t for t in live if tasks.is_ready(t, index)]
    first = (ready or live)[0]
    what = str(first.get("description") or first.get("id") or "").strip()
    lead = f"{speech.count_phrase(len(live), 'task')} open"
    if ready and len(ready) != len(live):
        lead += f", {len(ready)} ready to start"
    return lead + (f". Next: {what[:130].rstrip('.')}." if what else ".")


def _approvals() -> str:
    """What is sitting on HIS yes. The count is the answer; the first one
    is what makes the count mean something."""
    from aletheia import policy, speech
    try:
        rows = policy.all_approvals()
    except Exception:
        return None
    pending = [a for a in rows
               if str(a.get("state") or "").upper() == "PENDING"]
    if not pending:
        return "Nothing is waiting on your approval."
    # THE LABEL, never the raw reason: "The first: operator said: \"spoken to
    # the wall: thea put a hold on monday...\"" was read out (sandbox,
    # 2026-10-05). voice.approval_label is what every interface shows.
    try:
        from aletheia import voice
        first = str(voice.approval_label(pending[0]) or "").strip()
    except Exception:
        first = str(pending[0].get("reason") or pending[0].get("action") or "").strip()
    return (f"{speech.count_phrase(len(pending), 'approval')} pending"
            + (f". The first: {first[:130].rstrip('.')}." if first else "."))


# What he can ASK FOR, in his words. Keyed by intercom kind, because a
# kind is exactly a thing he can say — the registry's `core.*`,
# `policy.*` and `journal.*` are machinery he can neither reach nor care
# about, and two thirds of "104 things are live" was that.
#
# Hand-kept, the same reasoning `test_every_writer_has_a_reader` gives:
# a mechanical grouping would have to guess, and a wrong guess reads
# fluently while being wrong. A test asserts every kind is either here or
# deliberately marked internal, so a new verb cannot go unmentioned.
# How many groups she names out loud. A list of everything is a list of
# nothing: he stops listening at the fourth item.
SPOKEN_GROUPS = 6

# CONSOLIDATED 2026-09-18 (continuity brief, item 9). The two tables moved to
# `tools.SPOKEN_GROUPS_BY_NAME` and `tools.INTERNAL_KINDS`, beside the
# descriptors, so one edit teaches the catalog and the answer at once. They are
# reached through the module `__getattr__` below rather than imported at the
# top, because `quick` is the fast lane: importing `tools` imports the whole
# intercom, and the point of this module is that it costs a file read.


def __getattr__(name):
    if name == "_HE_CAN_ASK_FOR":
        from aletheia import tools
        return tools.SPOKEN_GROUPS_BY_NAME
    if name == "_NOT_A_THING_HE_ASKS_FOR":
        from aletheia import tools
        return tools.INTERNAL_KINDS
    raise AttributeError(name)


def _capabilities() -> str | None:
    """The things he can ask for, named — not counted.

    "104 things are live, 17 experimental..." was every number true and
    nobody's question. This says what they ARE, from the grammar, and
    only mentions what is live: a capability waiting on setup is not
    something he can ask for today.
    """
    from aletheia import capabilities, intercom, speech
    try:
        reg = capabilities.load_registry()
    except Exception:
        return None                 # unreadable registry — let the planner try
    live_ids = {c["id"] for c in reg.get("capabilities", [])
                if c.get("status") == "AVAILABLE"}
    if not live_ids:
        return None

    # A group is worth naming when the grammar can still reach it.
    from aletheia import tools
    named = [name for name, kinds in tools.SPOKEN_GROUPS_BY_NAME.items()
             if any(k in intercom.KIND_ARGS for k in kinds)]
    if not named:
        return None
    # SIX, NOT SIXTEEN. Read out loud, a list of everything is a list of
    # nothing — he stops listening at the fourth item and has learned
    # less than from three. The dict is in the order a person meets them.
    head, rest = named[:SPOKEN_GROUPS], named[SPOKEN_GROUPS:]
    said = "I can help with " + speech.and_list(head)
    if rest:
        said += f", and {len(rest)} other kinds of thing"
    return said + ". Ask me for anything and I'll tell you straight if I can't."


def _cannot() -> str | None:
    """"What can't you do?" - from the registry, never from a model.

    Two kinds of no, said apart because they are different asks of him:
    what is waiting on SETUP (his credentials, his ten minutes) and what is
    NOT BUILT (a build, not a chore). Named, not counted; a handful each.
    """
    from aletheia import capabilities, intents, setup, speech
    try:
        reg = capabilities.load_registry()
    except Exception:
        return None
    rows = [c for c in reg.get("capabilities", []) if isinstance(c, dict)]
    if not rows:
        return None
    unbuilt = [c["id"] for c in rows if c.get("status") == "NOT_BUILT"]
    # WHAT WAITS ON SETUP is what the live audit says, and the fast lane
    # never pays for a live check. A recent audit is read; without one the
    # sentence says how to get it rather than guessing from the registry,
    # whose NEEDS_CONFIGURATION rows are only the optional extras.
    report = setup.cached_report()
    parts = []
    if report is not None:
        chores = [str(s.get("title") or "") for s in report.get("steps", [])
                  if s.get("state") != setup.OK and not s.get("optional")]
        if chores:
            parts.append("Waiting on you to set up: " + speech.and_list(chores[:4]).lower()
                         + (f", and {len(chores) - 4} more" if len(chores) > 4 else ""))
    else:
        parts.append("Some things wait on setup from you; say \"what do you still need "
                     "from me\" and I'll check each one live")
    if unbuilt:
        named = [speech.shorten(intents._in_english(c), 60).rstrip(".") for c in unbuilt[:3]]
        parts.append("Not built yet: " + speech.and_list(named)
                     + (f", and {speech.count_phrase(len(unbuilt) - 3, 'other')}"
                        if len(unbuilt) > 3 else ""))
    if not parts:
        return "Nothing I know of is missing: everything in my list is built and set up."
    return ". ".join(parts) + ". Ask about any one and I'll say exactly where it stands."


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _agenda(day: str = "today") -> str | None:
    day = "this week" if day == "week" else day
    """"What's on my calendar today?" - the day's events from the calendar
    mirror, on his clock. An empty day still proves the calendar."""
    import datetime as dt
    from aletheia import calendar, localtime, speech
    try:
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        day = str(day).strip()
        if day == "this week":
            first, last = now.date(), now.date() + dt.timedelta(days=6)
        elif day == "next week":
            first = now.date() + dt.timedelta(days=7 - now.weekday())
            last = first + dt.timedelta(days=6)
        elif day in _WEEKDAYS:
            # "What's on my calendar Monday": the coming one (today if it is today).
            ahead = (_WEEKDAYS.index(day) - now.weekday()) % 7
            first = last = now.date() + dt.timedelta(days=ahead)
        else:
            first = last = now.date() + dt.timedelta(days=1 if day == "tomorrow" else 0)
        rows = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
            except (KeyError, ValueError, TypeError):
                continue
            if first <= start.date() <= last:
                rows.append((start, str(event.get("title") or "something")[:80]))
    except Exception:
        return None                  # no calendar mirror: the model may know more
    label = (first.strftime("%A") if day in _WEEKDAYS      # he said Friday; say Friday
             else "Today" if first == last == now.date()
             else "Tomorrow" if first == last and first == now.date() + dt.timedelta(days=1)
             else first.strftime("%A") if first == last
             else "This week" if day == "this week" else "Next week")
    when_said = label.lower() if label in ("Today", "Tomorrow", "This week", "Next week") else label
    if not rows:
        return f"Nothing on your calendar {when_said}."
    rows.sort(key=lambda r: r[0])
    many_days = first != last
    said = [(f"{title} {start.strftime('%A')} at " if many_days else f"{title} at ")
            + start.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower()
            for start, title in rows[:6]]
    return (f"{label}: " + speech.and_list(said)
            + (f", and {len(rows) - 6} more" if len(rows) > 6 else "") + ".")


def _last_reply_on_record(days: int = 14) -> str:
    """" The last was DevRev, on Tuesday." - or "" when there is none."""
    try:
        import datetime as dt
        from aletheia import apply_run, current_state
        now = dt.datetime.now(dt.timezone.utc)
        latest = None
        for record in apply_run.all_runs():
            for row in record.get("outcomes") or []:
                when = str(row.get("at") or "")
                try:
                    stamp = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if (now - stamp).days > days:
                    continue
                if latest is None or stamp > latest[0]:
                    latest = (stamp, record, row)
        if latest is None:
            return ""
        stamp, record, row = latest
        who = current_state.said_name(record.get("company", ""), record.get("job_title", ""))
        day = "today" if stamp.date() == now.date() else stamp.strftime("%A")
        return f" The last was {who} ({row.get('outcome', 'replied')}), {day}."
    except Exception:
        return ""


def _replies() -> str | None:
    """Replies from employers today, from the application records."""
    try:
        from aletheia import current_state, speech
        hunt = current_state.job_hunt()
    except Exception:
        return None
    if not hunt.get("readable"):
        return "I can't read my application records right now, so I can't say."
    rows = list(hunt.get("replies") or [])
    if not rows:
        # Not only today: "did anyone write back" on a Wednesday is about
        # the week, and the last one on record is the honest answer.
        return "No replies from employers today." + _last_reply_on_record()
    named = [f"{current_state.said_name(r.get('company', ''), r.get('job', ''))}"
             + (f" ({r['outcome']})" if r.get("outcome") else "") for r in rows[:4]]
    return (f"{speech.count_phrase(len(rows), 'reply', 'replies')} today: "
            + speech.and_list(named) + ".")


def _slow() -> str | None:
    """Why she is slow: who is thinking, and how that has been going."""
    try:
        from aletheia import current_state
        return current_state.brains_words()
    except Exception:
        return None


def _arrival() -> str:
    from aletheia import speech
    try:
        from aletheia import needs_you
        rows = needs_you.items()
    except Exception:
        rows = []
    if rows:
        return f"Welcome back. {speech.count_phrase(len(rows), 'thing')} waiting on you."
    return "Welcome back. Nothing's waiting on you."


def _farewell(text: str) -> str:
    low = str(text or "").lower()
    if any(w in low for w in ("night", "sleep", "bed")):
        return "Goodnight. I'll keep going quietly."
    return "See you. I'll keep at it while you're out."


def _math(text: str) -> str | None:
    """Percent of, the four operations, and a few unit conversions."""
    import re as _re
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "math"), None)
    if not found:
        return None
    g = {k: v for k, v in found.groupdict().items() if v}

    def num(s: str) -> float:
        return float(str(s).replace(",", ""))

    def said(v: float) -> str:
        return f"{v:.10g}" if abs(v - round(v)) > 1e-9 else f"{int(round(v)):,}"
    try:
        if "pct" in g:
            # "20 percent of 45 dollars" went to a model for the word "dollars".
            return f"{'$' if g.get('pct_money') else ''}{said(num(g['pct']) * num(g['of']) / 100)}."
        if "tip" in g or "tip_on2" in g:
            rate = num(g.get("tip") or g.get("tip2") or "20")
            bill = num(g.get("tip_on") or g.get("tip_on2"))
            tip = round(bill * rate / 100, 2)
            return f"${tip:,.2f} tip at {said(rate)} percent - ${bill + tip:,.2f} all in."
        if "pct_off" in g:
            total, off = num(g["off"]), num(g["pct_off"]) * num(g["off"]) / 100
            money = "$" if g.get("off_money") else ""
            return f"{money}{said(total - off)} - that's {money}{said(off)} off."
        if "frac" in g:
            part = {"half": 0.5, "third": 1 / 3, "quarter": 0.25, "fifth": 0.2, "tenth": 0.1,
                    "two thirds": 2 / 3, "three quarters": 0.75}[g["frac"]]
            return f"{'$' if g.get('frac_money') else ''}{said(round(num(g['frac_of']) * part, 4))}."
        if "mult" in g:
            factor = {"double": 2, "twice": 2, "triple": 3, "half": 0.5}[g["mult"]]
            return f"{'$' if g.get('mult_money') else ''}{said(num(g['mult_of']) * factor)}."
        if "unit_small" in g:
            facts = {("ounces", "pound"): 16, ("oz", "pound"): 16, ("inches", "foot"): 12, ("inches", "yard"): 36,
                     ("feet", "yard"): 3, ("feet", "mile"): 5280, ("yards", "mile"): 1760,
                     ("centimeters", "meter"): 100, ("centimetres", "metre"): 100, ("centimeters", "inch"): 2.54,
                     ("centimetres", "inch"): 2.54, ("millimeters", "meter"): 1000, ("millimetres", "metre"): 1000,
                     ("millimeters", "inch"): 25.4, ("millimetres", "inch"): 25.4, ("meters", "kilometer"): 1000,
                     ("grams", "kilogram"): 1000, ("grams", "kilo"): 1000, ("grams", "pound"): 453.6,
                     ("milliliters", "liter"): 1000, ("millilitres", "litre"): 1000, ("cups", "quart"): 4,
                     ("cups", "gallon"): 16, ("cups", "pint"): 2, ("quarts", "gallon"): 4, ("pints", "quart"): 2,
                     ("pints", "gallon"): 8, ("fluid ounces", "cup"): 8, ("fluid ounces", "pint"): 16,
                     ("tablespoons", "cup"): 16, ("teaspoons", "tablespoon"): 3, ("seconds", "minute"): 60,
                     ("minutes", "hour"): 60, ("hours", "day"): 24, ("days", "week"): 7, ("weeks", "year"): 52,
                     ("months", "year"): 12, ("days", "year"): 365}
            key = (g["unit_small"], g["unit_big"])
            if key in facts:
                return f"{said(facts[key])} {g['unit_small']} in a {g['unit_big']}."
            # "how many feet in a meter" is a conversion, not a fact of the
            # table: fall through to the units below with one of the big one
            g = {"n": "1", "from": g["unit_big"], "to": g["unit_small"]}
        if "split" in g:
            ways = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                    "ten": 10}.get(g["ways"]) or int(g["ways"])
            if ways == 0:
                return "You can't split it zero ways."
            return f"{'$' if g.get('split_money') else ''}{said(round(num(g['split']) / ways, 2))} each."
        if "op" in g:
            a, b = num(g["a"]), num(g["b"])
            op = g["op"]
            if op in ("plus", "+"):
                return f"{said(a + b)}."
            if op in ("minus", "-"):
                return f"{said(a - b)}."
            if op in ("times", "x", "*"):
                return f"{said(a * b)}."
            if b == 0:
                return "You can't divide by zero."
            return f"{said(a / b)}."
        units = {"mile": ("mi", 1609.344), "miles": ("mi", 1609.344), "km": ("km", 1000.0),
                 "kilometer": ("km", 1000.0), "kilometers": ("km", 1000.0), "kilometre": ("km", 1000.0),
                 "kilometres": ("km", 1000.0), "feet": ("ft", 0.3048), "foot": ("ft", 0.3048), "ft": ("ft", 0.3048),
                 "meter": ("m", 1.0), "meters": ("m", 1.0), "metre": ("m", 1.0), "metres": ("m", 1.0),
                 "inch": ("in", 0.0254), "inches": ("in", 0.0254), "cm": ("cm", 0.01),
                 "centimeter": ("cm", 0.01), "centimeters": ("cm", 0.01),
                 "pound": ("lb", 0.45359237), "pounds": ("lb", 0.45359237), "lb": ("lb", 0.45359237),
                 "lbs": ("lb", 0.45359237), "kg": ("kg", 1.0), "kilogram": ("kg", 1.0), "kilograms": ("kg", 1.0)}
        n = num({"a": "1", "an": "1", "one": "1"}.get(str(g.get("n") or g.get("n2")).lower(), g.get("n") or g.get("n2")))
        src, dst = (g.get("from") or g.get("from2")).lower(), (g.get("to") or g.get("to2")).lower()
        if src in ("fahrenheit", "f") and dst in ("celsius", "c"):
            return f"{said(round((n - 32) * 5 / 9, 1))} degrees Celsius."
        if src in ("celsius", "c") and dst in ("fahrenheit", "f"):
            return f"{said(round(n * 9 / 5 + 32, 1))} degrees Fahrenheit."
        if src in units and dst in units:
            length = {"mi", "km", "ft", "m", "in", "cm"}
            if (units[src][0] in length) != (units[dst][0] in length):
                return None
            value = n * units[src][1] / units[dst][1]
            # SAID, not printed: "6.21 mi" is "six point two one em eye" out
            # loud. The unit is a word, singular when it is one of them.
            spoken = {"mi": "mile", "km": "kilometer", "ft": "foot", "m": "meter", "in": "inch",
                      "cm": "centimeter", "lb": "pound", "kg": "kilogram"}[units[dst][0]]
            plural = {"foot": "feet", "inch": "inches"}.get(spoken, spoken + "s")
            shown = round(value, 2)
            lead = "About " if abs(shown - value) > 1e-9 else ""
            return f"{lead}{said(shown)} {spoken if shown == 1 else plural}."
    except (ValueError, ZeroDivisionError):
        return None
    return None


def _how_many() -> str | None:
    """The counts, for the question the old answer was really answering."""
    from aletheia import self_knowledge, speech
    by = dict((self_knowledge.overview() or {}).get("by_status") or {})
    live = int(by.get("AVAILABLE") or 0)
    if not live:
        return None
    parts = [f"{live} things are live"]
    for key, label in (("EXPERIMENTAL", "experimental"),
                       ("NEEDS_CONFIGURATION", "waiting on setup"),
                       ("NOT_BUILT", "not built yet")):
        count = int(by.get(key) or 0)
        if count:
            parts.append(f"{count} {label}")
    return (speech.and_list(parts)
            + ". Ask about a specific one and I'll tell you straight.")


def _no_pulse() -> bool:
    from aletheia import pulse
    try:
        return not (pulse.PULSE_DIR / "latest.json").is_file()
    except Exception:
        return True


def _repo_wrong(name: str) -> str | None:
    """"What's wrong with the trader": that repo's row of the pulse, in words;
    no pulse is said as no pulse; a name the pulse does not know is a model's."""
    from aletheia import current_state
    said = current_state.repo_words(" ".join(str(name or "").split()))
    if said is None and _no_pulse():
        return "No fleet reading yet - the pulse hasn't been written on this machine, so I can't say."
    return said


def _pulse_or_none():
    import json
    from aletheia import pulse
    try:
        return json.loads((pulse.PULSE_DIR / "latest.json").read_text(encoding="utf-8"))
    except Exception:
        return None


_NO_PULSE = "No fleet reading yet - the pulse hasn't been written on this machine, so I can't say."


def _registry_repos() -> dict:
    """The fleet registry's repos, by id. {} when it cannot be read."""
    try:
        from aletheia import fleet
        return dict((fleet.load_fleet() or {}).get("repos") or {})
    except Exception:
        return {}


def _repo_count() -> str:
    repos = _registry_repos()
    if not repos:
        return None
    active = [v.get("github") or k for k, v in repos.items() if v.get("status") == "active"]
    rest = [v.get("github") or k for k, v in repos.items() if v.get("status") != "active"]
    from aletheia import speech
    said = f"{speech.count_phrase(len(active), 'repository')} being watched: {speech.and_list(active)}."
    if rest:
        marked = speech.and_list(sorted({str(repos[k].get('status')) for k in repos if repos[k].get('status') != 'active'}))
        said += f" {len(rest)} more on the registry marked {marked}, not watched: {speech.and_list(rest)}."
    return said


def _repo_about(words: str) -> str | None:
    """"What's the shorts pipeline": the registry's own summary, or None when
    the words name no repo of the fleet - that question is a model's."""
    said_words = re.sub(r"\s+(?:repo|repository|project|pipeline|bot|thing)$", "", " ".join(str(words or "").casefold().split()))
    want = re.sub(r"[^a-z0-9]+", "", said_words)
    if len(want) < 3:
        return None
    repos = _registry_repos()
    exact, loose = [], []
    for key, row in repos.items():
        names = {re.sub(r"[^a-z0-9]+", "", str(n).casefold()) for n in (key, row.get("github") or "")}
        if want in names:
            exact.append(key)
        elif len(want) >= 5 and any(want in n for n in names):
            loose.append(key)          # "the trader" is schwab-trader
    hits = exact or (loose if len(loose) == 1 else [])
    for key in hits:
        row = repos[key]
        if True:
            name = str(row.get("github") or key)
            summary = " ".join(str(row.get("summary") or "").split()).rstrip(".")
            status = str(row.get("status") or "")
            role = str(row.get("role") or "")
            said = f"{name}: {summary}." if summary else f"{name} is on the fleet registry with no summary."
            if status and status != "active":
                said += f" It's marked {status} - not watched."
            elif role:
                said += f" Its role is {role}."
            return said
    return None


def _last_fault() -> str:
    latest = _pulse_or_none()
    if latest is None:
        return _NO_PULSE
    from aletheia import faults
    repos = latest.get("repos") if isinstance(latest.get("repos"), dict) else {}
    alerts = [a for a in (latest.get("alerts") or []) if isinstance(a, dict)]
    if not alerts:
        return "No faults in the last fleet reading - nothing is red."
    # newest by the failing workflow's own stamp where the pulse has one
    def stamp(a: dict) -> str:
        row = repos.get(str(a.get("repo") or "")) or {}
        wfs = row.get("workflows") if isinstance(row.get("workflows"), dict) else {}
        return max((str((wfs.get(f) or {}).get("updated_at") or "") for f in (a.get("failing") or [])), default="")
    alert = max(alerts, key=stamp)
    row = repos.get(str(alert.get("repo") or "")) or {}
    name = row.get("github") or alert.get("github") or alert.get("repo")
    return f"{name}: {faults.said(alert, row).rstrip('.')}."


def _ci_failing() -> str:
    latest = _pulse_or_none()
    if latest is None:
        return _NO_PULSE
    from aletheia import speech
    repos = latest.get("repos") if isinstance(latest.get("repos"), dict) else {}
    red, running = [], 0
    for row in repos.values():
        wfs = row.get("workflows") if isinstance(row.get("workflows"), dict) else {}
        for wf, info in wfs.items():
            if not isinstance(info, dict):
                continue
            if info.get("status") == "in_progress":
                running += 1
            elif str(info.get("conclusion") or "") not in ("success", "", "skipped", "neutral"):
                short = wf[:-4] if wf.endswith(".yml") else wf
                red.append(f"{short} on {row.get('github')} ({str(info.get('conclusion')).replace('_', ' ')})")
    when = speech.humanize_time(str(latest.get("generated_at") or "")) if latest.get("generated_at") else "in the last reading"
    if not red:
        return f"Green: every workflow in the last fleet reading passed ({when})." + (f" {running} still running." if running else "")
    return f"Red: {speech.and_list(red[:5])}" + (f", and {len(red) - 5} more" if len(red) > 5 else "") + f" - as of {when}."


def _fleet_read_at() -> str:
    """When the pulse was last written - the fleet's own timestamp."""
    import json
    from aletheia import pulse, speech
    try:
        latest = json.loads((pulse.PULSE_DIR / "latest.json").read_text(encoding="utf-8"))
    except Exception:
        return "No fleet reading yet - the pulse hasn't been written on this machine."
    when = str(latest.get("generated_at") or "")
    if not when:
        return "The fleet reading carries no time."
    return f"The fleet was last read {speech.humanize_time(when)}; it is read every six hours."


def _alerts() -> str | None:
    """The fleet's own red lights, from the pulse she already writes."""
    import json
    from aletheia import pulse, speech
    try:
        latest = json.loads((pulse.PULSE_DIR / "latest.json")
                            .read_text(encoding="utf-8"))
    except Exception:
        # Not "all green" - and not a model's guess either: with the pulse
        # unwritten this went to a model, which had nothing to read (2026-09-23).
        return "No fleet reading yet - the pulse hasn't been written on this machine, so I can't say what's red."
    from aletheia import faults
    alerts = [a for a in (latest.get("alerts") or []) if isinstance(a, dict)]
    if not alerts:
        return "Nothing red. The fleet is green."
    # What he has marked handled is said as handled, not as red (his words,
    # 2026-09-23: "I don't need that being read all night").
    handled = [a for a in alerts if faults.is_handled(a)]
    loud = [a for a in alerts if not faults.is_handled(a)]
    repos = latest.get("repos") if isinstance(latest.get("repos"), dict) else {}

    def name_of(row):
        # the name he knows it by, never the pulse's slug ("schwab_trader")
        return str(row.get("github") or row.get("repo") or "something")
    if not loud:
        return ("Nothing red that you haven't handled: "
                + speech.and_list([name_of(a) for a in handled]) + " waiting for the next reading.")
    named = []
    for row in loud[:3]:
        why = faults.said(row, repos.get(str(row.get("repo") or "")) or {}).rstrip(".")
        named.append(f"{name_of(row)} - {why[0].lower() + why[1:]}")
    if len(loud) > 3:
        named.append(f"{len(loud) - 3} more")
    said = f"{speech.count_phrase(len(loud), 'repo')} red: " + "; ".join(named) + "."
    if handled:
        said += " " + speech.and_list([name_of(a) for a in handled]) + " you've marked handled."
    return said


def _repos() -> str | None:
    """How many repos the pulse actually covers — counted, not recalled."""
    import json
    from aletheia import pulse, speech
    try:
        latest = json.loads((pulse.PULSE_DIR / "latest.json")
                            .read_text(encoding="utf-8"))
    except Exception:
        return _repo_count()
    repos = latest.get("repos")
    names = sorted(repos) if isinstance(repos, dict) else list(repos or [])
    if not names:
        # an empty pulse is not "zero repos" - the registry says what she
        # watches, when it can be read (2026-10-05: "list the repos" had
        # answered from the projects store, "No active projects")
        return _repo_count()
    shown = [str(n) for n in names[:4]]
    if len(names) > 4:
        shown.append(f"{len(names) - 4} more")
    return (f"{speech.count_phrase(len(names), 'repo')}: "
            + speech.and_list(shown) + ".")


def _pay_for(rest: str, *, want_date: bool = False) -> str:
    """"How much do I pay for Netflix": from her subscriptions store, and ONLY from it.

    Asked this with the frontier off, her own model answered "I can look through what's
    gone through on your accounts for Netflix charges" - an offer to read bank data she
    does not have, which sounds like helpfulness and is an invented source (CLAUDE.md:
    an offer is a claim about ability). The store is proved either way: a hit says the
    amount, a miss says the list and that there is no bank behind it.
    """
    from aletheia import speech, subscriptions
    what = " ".join(str(rest or "").split()).strip(" ?.")
    try:
        rows = subscriptions.all_subscriptions()
    except Exception:
        rows = []
    low = what.casefold()
    cadence_words = {"weekly": "weekly", "a week": "weekly", "per week": "weekly", "every week": "weekly",
                     "monthly": "monthly", "a month": "monthly", "per month": "monthly", "every month": "monthly",
                     "quarterly": "quarterly", "yearly": "annual", "annually": "annual", "a year": "annual",
                     "per year": "annual", "every year": "annual"}
    if low in cadence_words:
        # "What do I pay for weekly" is a list by cadence, not a merchant
        # called weekly (2026-10-05).
        cadence = cadence_words[low]
        those = [r for r in rows if str(r.get("cadence") or "") == cadence and str(r.get("status") or "ACTIVE") == "ACTIVE"]
        if not those:
            return f"Nothing {low} on your subscriptions list."
        return (f"{low[:1].upper() + low[1:]}: "
                + speech.and_list([f"{r.get('merchant')} at ${r['amount']:,.2f}" if r.get("amount") is not None
                                   else str(r.get("merchant")) for r in those[:6]]) + ".")
    hits = [r for r in rows if low and (low in str(r.get("merchant", "")).casefold()
                                        or str(r.get("merchant", "")).casefold() in low)]
    if hits:
        r = hits[0]
        amount, cadence = r.get("amount"), str(r.get("cadence") or "")
        each = {"weekly": "a week", "monthly": "a month", "quarterly": "a quarter",
                "annual": "a year"}.get(cadence, "")
        status = str(r.get("status") or "")
        if amount is None:
            said = f"{r['merchant']} is on your subscriptions list without an amount."
        else:
            said = f"You pay ${amount:,.2f}{(' ' + each) if each else ''} for {r['merchant']}."
        if r.get("next_charge"):
            said += f" Next charge {r['next_charge']}."
        elif want_date:
            # "When is spotify due" with no date kept: say so, rather than
            # answering the amount as if it were the date.
            said += " I don't have its charge date - tell me and I'll keep it."
        if status and status != "ACTIVE":
            said += f" It is {status.lower().replace('_', ' ')}."
        return said
    if not rows:
        return (f"{what[:1].upper() + what[1:]} isn't on your subscriptions list, and the list is empty. "
                "I only know the subscriptions you tell me about - I don't see your bank.")
    return (f"{what[:1].upper() + what[1:]} isn't on your subscriptions list. I have "
            + speech.and_list([str(r.get("merchant")) for r in rows[:6]])
            + ("." if len(rows) <= 6 else f", and {len(rows) - 6} more.")
            + " I don't see your bank.")


def _reply_rate() -> str:
    """"What's my reply rate": the funnel the Core publishes (hunt_funnel), which
    is the one place "is she doing a good job" has a number. A model, asked this,
    took five seconds to say nothing had been sent (sandbox, 2026-10-05)."""
    from aletheia import hunt_funnel, speech
    try:
        funnel = hunt_funnel.read()
    except Exception:
        funnel = None
    totals = (funnel or {}).get("totals") or {}
    sent = int(totals.get("sent") or 0)
    if not funnel or not sent:
        return ("No applications have gone out through me in the last 30 days, so there's no reply rate "
                "to give yet. Once some have, I count every reply, interview and decline against them.")
    replies = int(totals.get("replies") or 0)
    interviews = int(totals.get("interviews") or 0)
    rejections = int(totals.get("rejections") or 0)
    rate = (100 * replies) // sent
    said = (f"{speech.count_phrase(replies, 'reply')} to {speech.count_phrase(sent, 'application')} in the last "
            f"30 days - {rate} percent heard back")
    said += f", {speech.count_phrase(interviews, 'interview')}" if interviews else ", no interview yet"
    said += f", {rejections} said no." if rejections else "."
    return said


def _mail_watch() -> str:
    """Whether and how often she reads his inbox - from the mail setup and the
    Core's beat, not a model's guess ("I don't check on a schedule", 2026-10-05,
    about a poll that runs every beat)."""
    from aletheia import mail, speech
    try:
        ok, why = mail.available()
    except Exception as exc:  # noqa: BLE001
        ok, why = False, speech.plainly(str(exc))
    if not ok:
        return f"I'm not reading your inbox yet: {speech.plainly(str(why)).rstrip('.')}. Once mail is set up I read it on every beat."
    try:
        from aletheia import core
        every = int(core.SYNC_INTERVAL_S)
    except Exception:
        every = 60
    back = int(mail.POLL_LOOKBACK_S // 3600)
    return (f"Yes. I read your inbox on every beat, about every {speech.count_phrase(every, 'second') if every < 120 else speech.count_phrase(every // 60, 'minute')}, "
            f"looking back {speech.count_phrase(back, 'hour')} so a message you opened on your phone still reaches me. "
            "A reply from an employer, a request for time, or a decline is matched to the application it answers.")


def _sunset() -> str:
    """She has no sunset lookup. Asked, a model answered "in the Chicago area it's
    around 6:15 PM" - a city she had never been told and a number it made up
    (sandbox, 2026-10-05). The honest answer names what she lacks and the one
    sentence that gets it."""
    city = ""
    try:
        from aletheia import profile
        city = str(profile.known().get("city") or "").strip()
    except Exception:
        city = ""
    where = f" in {city}" if city else ""
    return ("I don't have a sunset lookup yet, and I won't guess a time. Say "
            f"\"look up tonight's sunset{where}\" and I'll research it"
            + ("" if city else " - tell me your city first so I know where you are") + ".")


def _next_charge() -> str:
    """The soonest charge on his subscriptions list, or the honest empty answer."""
    from aletheia import subscriptions
    try:
        rows = [r for r in subscriptions.all_subscriptions(active_only=True) if r.get("next_charge")]
    except Exception:
        rows = []
    if not rows:
        try:
            any_rows = subscriptions.all_subscriptions()
        except Exception:
            any_rows = []
        if not any_rows:
            return ("Your subscriptions list is empty, so I have no next charge to tell you about. "
                    "I don't see your bank - say \"add Netflix at 15.49 a month to my subscriptions\" and I'll track it.")
        return "None of your subscriptions has a charge date on it yet, so I can't say which is next."
    r = rows[0]
    amount = r.get("amount")
    money = f"${amount:,.2f} " if amount is not None else ""
    return f"Next charge: {money}for {r['merchant']} on {r['next_charge']}."


def _projects() -> str:
    """The projects she is carrying - the ONE answer `intercom` gives the `projects` kind.

    Asked "what projects are you carrying" with the frontier off, her own model said "I
    don't see any projects in front of me ... if you tell me one, I'll start it" - the
    reader existed in the grammar and this lane had no door to it, so a model denied the
    store. One implementation: charters, drafts waiting for his yes, asks still to draft,
    and the private records, in that order.
    """
    from aletheia import intercom
    try:
        return intercom._projects_answer()
    except Exception:
        return "I couldn't read your projects just now."


def _shopping() -> str | None:
    """The same sentence the `shopping_list` command gives, written once."""
    from aletheia import intercom
    return intercom.shopping_answer()


def _free(when: str = "") -> str | None:
    """Whether he is free, from the same code the `free_time` kind uses."""
    import datetime as dt
    from aletheia import intercom, localtime
    day = dt.datetime.now(localtime.operator_tz()).date()
    if str(when or "").strip().casefold() == "tomorrow":
        day += dt.timedelta(days=1)
    try:
        return intercom.free_time_answer({"kind": "free_time",
                                          "day": day.isoformat()})
    except Exception:
        return None             # no feed, or it could not be read


def _next_meeting() -> str | None:
    """His next appointment, from the block the wall already renders.

    `presence._next_appointment` is the one definition of "next"; reading
    the calendar again here would be a second implementation free to
    drift from the one he can see.
    """
    import datetime as dt
    from aletheia import localtime, presence
    try:
        now = dt.datetime.now(localtime.operator_tz())
        appointment = presence._next_appointment(now)
    except Exception:
        return None             # no feed, or it could not be read
    if not appointment:
        # An empty calendar still proves the calendar. Falling through to
        # a model here would replace a true answer with a guess.
        return "Nothing on your calendar coming up."
    title = str(appointment.get("title") or "").strip()
    when = str(appointment.get("when") or "").strip()
    if not when:
        return None
    return f"{title} {when}." if title else f"You've got something {when}."


def _version() -> str | None:
    """Which code she is running, and whether the tree has moved past it."""
    from aletheia import running
    try:
        return running.version_spoken(running.version())
    except Exception:
        return None


def _uptime() -> str | None:
    """How long she has been on, from her own heartbeat - or, when a Core
    is running in THIS process and has no heartbeat yet, from the process
    itself. "When did you last restart" went to a model that said it could
    not know (2026-10-05); the process's own start is a fact."""
    import datetime as dt
    import sys
    from aletheia import liveness, localtime, speech
    seconds = liveness.uptime_seconds()
    if seconds is None:
        core = sys.modules.get("aletheia.core")
        # Only when a Core is SERVING in this process: the module being
        # imported is not the Core being up (the full suite imports it, and
        # "how long have you been up" answered "Up 15 minutes" from a test
        # process with no Core in it, 2026-10-05).
        started = getattr(core, "PROCESS_STARTED_AT", None) if core and getattr(core, "SERVERS", None) else None
        if not started:
            return None             # she does not know; do not invent one (test_liveness)
        seconds = max(0.0, dt.datetime.now(dt.timezone.utc).timestamp() - float(started))
    since = dt.datetime.now(localtime.operator_tz()) - dt.timedelta(seconds=seconds)
    return f"Up {liveness.spoken_duration(seconds)}, since {speech.humanize_time(since.isoformat())}."


def _notify_count() -> str:
    from aletheia import notifications, speech
    try:
        rows = notifications.all_notifications(state="UNREAD", limit=500)
    except Exception:
        return "I can't read my notifications right now."
    if not rows:
        return "No unread notifications."
    # BY STORY, not one by one: live 2026-09-24 this said "500 unread
    # notifications: ...; and 497 more". The page folds the same way.
    folded = notifications.folded(rows)
    named = []
    for n in folded[:4]:
        line = speech.notice_line(n)
        count = int(n.get("count") or 1)
        named.append(f"{line} and {count - 1} more like it" if count > 1 and not n.get("stale")
                     else f"{count} older ones you never opened" if n.get("stale") else line)
    total = f"at least {len(rows)}" if len(rows) >= 500 else str(len(rows))
    return (f"{total} unread notification{'s' if len(rows) != 1 else ''}: " + "; ".join(named)
            + (f"; and {len(folded) - 4} more" if len(folded) > 4 else "") + ".")


def _jobs_left() -> str:
    """No queue to count down: each batch finds openings fresh. The day's
    numbers are what there is to say."""
    from aletheia import current_state
    try:
        today = current_state.job_hunt_words()
    except Exception:
        today = ""
    return ("There's no queue to work down - each batch finds openings fresh and applies to what fits "
            "your resume." + (f" {today}" if today else ""))


# What he calls it -> what the profile calls it.
# More than one field can answer one question: he says "my name" and the
# store has a preferred name, a legal name and a first name, any of which
# is a true answer. First one she has, in the order a person would say it.
_MINE = {"email": ("email",), "email address": ("email",),
         "phone": ("phone",), "phone number": ("phone",),
         "number": ("phone",),
         "city": ("city",), "town": ("city",),
         "name": ("preferred_name", "first_name", "legal_name"),
         "first name": ("first_name", "preferred_name"),
         "last name": ("last_name",),
         "full name": ("legal_name", "full_name"),
         "minimum salary": ("desired_pay",), "salary": ("desired_pay",), "salary floor": ("desired_pay",),
         "salary requirement": ("desired_pay",), "salary expectation": ("desired_pay",),
         "salary expectations": ("desired_pay",), "desired pay": ("desired_pay",),
         "desired salary": ("desired_pay",), "asking pay": ("desired_pay",), "asking salary": ("desired_pay",),
         "asking price": ("desired_pay",), "pay": ("desired_pay",), "pay expectation": ("desired_pay",),
         "pay expectations": ("desired_pay",), "notice period": ("notice_period",), "start date": ("notice_period",),
         # "what's my zip", "where do I work", "what's my job title" (2026-10-05: a model each)
         "zip": ("postal_code",), "zip code": ("postal_code",), "postcode": ("postal_code",),
         "post code": ("postal_code",), "postal code": ("postal_code",),
         "employer": ("current_employer",), "company": ("current_employer",), "workplace": ("current_employer",),
         "job title": ("current_title",), "title": ("current_title",), "role": ("current_title",),
         "job": ("current_title", "current_employer"),
         "state": ("state",), "country": ("country",), "linkedin": ("linkedin",), "github": ("github",),
         "website": ("website",), "pronouns": ("pronouns",), "school": ("school",), "degree": ("degree",),
         "years of experience": ("years_experience",)}

# "Who am I" has no captured word to look up, so it names its own.
_WHO_AM_I = "name"


def _subscription_spend(per: str = "") -> str:
    """What his tracked subscriptions come to a month - or a year, when he
    asked that - from the store."""
    from aletheia import speech, subscriptions
    try:
        rows = subscriptions.all_subscriptions(active_only=True)
    except Exception:
        return "I can't read your subscriptions list right now."
    if not rows:
        return "Nothing: I'm not tracking any subscriptions yet. Say \"I pay 15.99 a month for Netflix\" and I'll keep it."
    monthly = [subscriptions.monthly_equivalent(r) for r in rows]
    total = sum(m for m in monthly if m)
    unknown = sum(1 for m in monthly if not m)
    names = speech.and_list([str(r.get("merchant") or "?") for r in rows[:5]])
    yearly = str(per or "").casefold() in ("a year", "per year", "yearly", "annually", "every year")
    figure = f"${total * 12:,.2f} a year" if yearly else f"${total:,.2f} a month"
    said = f"About {figure} across {speech.count_phrase(len(rows), 'subscription')}: {names}."
    if unknown:
        said += f" {speech.count_phrase(unknown, 'of them has', 'of them have')} no price I know, so the real total is higher."
    return said


def _subscription_extreme(which: str = "") -> str:
    """His biggest or smallest subscription, by what it costs a month."""
    from aletheia import subscriptions
    try:
        rows = [r for r in subscriptions.all_subscriptions(active_only=True)
                if subscriptions.monthly_equivalent(r)]
    except Exception:
        return "I can't read your subscriptions list right now."
    if not rows:
        return "I'm not tracking any priced subscriptions yet."
    least = str(which or "").casefold() in ("cheapest", "smallest", "least expensive", "least")
    rows.sort(key=subscriptions.monthly_equivalent, reverse=not least)
    each = {"weekly": "a week", "monthly": "a month", "quarterly": "a quarter", "annual": "a year"}

    def say(r):
        return f"{r.get('merchant')} at ${r['amount']:,.2f} {each.get(r.get('cadence'), '')}".strip()

    lead = "The cheapest" if least else "The biggest"
    said = f"{lead}: {say(rows[0])}"
    if len(rows) > 1:
        said += f", then {say(rows[1])}"
    return said + "."


def _who_is(name: str) -> str | None:
    """"Who is Dana": the shelf of people and the contacts, by the name.
    None when the words are not a name she can look up."""
    from aletheia import memory, speech
    who = " ".join(str(name or "").split()).strip(" ?.")
    if not who:
        return None
    low = who.casefold()
    roles = []
    try:
        for domain, entries in (memory.everything(max_chars=8000) or {}).items():
            if domain not in ("people", "organizations"):
                continue
            for key, held in entries.items():
                value = str(held.get("value") or "")
                if low == value.casefold() or low in {w.strip(",.") for w in value.casefold().split()}:
                    about = str(held.get("about") or "").strip()
                    roles.append(about[len("your "):] if about.startswith("your ") else key.replace("_", " "))
    except Exception:
        pass
    reach = ""
    try:
        from aletheia import contacts
        for c in contacts.all_contacts():
            names = [str(c.get("display_name") or "")] + [str(a) for a in (c.get("aliases") or [])]
            if any(low == n.casefold() or low == n.casefold().split(" ")[0] for n in names if n):
                phones = [speech.phone_words(v) for v in (c.get("phones") or []) if v]
                emails = [str(v) for v in (c.get("emails") or []) if v]
                bits = ([f"number {phones[0]}"] if phones else []) + ([f"email {emails[0]}"] if emails else [])
                reach = ", ".join(bits)
                break
    except Exception:
        pass
    shown = who[:1].upper() + who[1:]
    if roles:
        said = f"{shown} is your {speech.and_list(roles)}"
        return said + (f"; {reach}." if reach else ".")
    if reach:
        return f"{shown} is in your contacts: {reach}."
    return f"I don't have anyone called {shown} on file. Tell me who they are and I'll remember it."


def _timers() -> str:
    """"How many timers do I have" (2026-10-05: a model, six seconds)."""
    import datetime as dt
    from aletheia import intercom, liveness, scheduler, speech
    try:
        rows = [r for r in intercom._reminder_schedules()
                if r.get("kind") == "once" and "timer" in str((r.get("command") or {}).get("text") or "").casefold()]
    except Exception:
        return "I can't read my timers right now."
    now = dt.datetime.now(dt.timezone.utc)
    coming = []
    for spec in rows:
        try:
            at = scheduler.next_occurrence(spec, now)
        except Exception:
            continue
        if at is not None:
            coming.append((at, spec))
    if not coming:
        return "No timers running."
    coming.sort(key=lambda pair: pair[0])
    said = []
    for at, spec in coming[:4]:
        text = str(spec["command"].get("text") or "").rstrip(".")
        what = text[len("your "):] if text.startswith("your ") else text
        what = what[:-len(" is up")] if what.endswith(" is up") else what
        said.append(f"{what} with {liveness.spoken_duration((at - now).total_seconds())} left")
    return f"{speech.count_phrase(len(coming), 'timer')}: {speech.and_list(said)}."


def _bored() -> str:
    """"I'm bored" (2026-10-05: a model offered trivia and twenty questions,
    neither of which exists). What is actually open, from her stores."""
    from aletheia import speech
    bits = []
    try:
        from aletheia import tasks
        open_tasks = [t for t in tasks.all_tasks() if str(t.get("status") or "").upper() in ("QUEUED", "READY", "WAITING_DEPENDENCY") and tasks.is_his(t)]
        if open_tasks:
            bits.append(f"{speech.count_phrase(len(open_tasks), 'task')} on your list - the first is {open_tasks[0].get('description')}")
    except Exception:
        pass
    try:
        from aletheia import policy
        pending = [a for a in policy.all_approvals() if a.get("state") == "PENDING"]
        if pending:
            bits.append(f"{speech.count_phrase(len(pending), 'thing')} waiting on your yes")
    except Exception:
        pass
    lead = "I don't have games. "
    if bits:
        return lead + "What's actually open: " + speech.and_list(bits) + ". Or ask me anything about your day."
    return lead + "Nothing's open on your list and nothing's waiting on you. Ask me anything, or say 'add a task' and I'll keep it."


def _timer_left() -> str:
    """What is left on a timer he set, from the reminder it became."""
    import datetime as dt
    from aletheia import intercom, liveness, scheduler, speech
    try:
        rows = [r for r in intercom._reminder_schedules()
                if r.get("kind") == "once" and "timer" in str((r.get("command") or {}).get("text") or "").casefold()]
    except Exception:
        return "I can't read my timers right now."
    now = dt.datetime.now(dt.timezone.utc)
    coming = []
    for spec in rows:
        try:
            at = scheduler.next_occurrence(spec, now)
        except Exception:
            continue
        if at is not None:
            coming.append((at, spec))
    if not coming:
        return "No timer running."
    at, spec = min(coming, key=lambda pair: pair[0])
    left = (at - now).total_seconds()
    text = str(spec["command"].get("text") or "").rstrip(".")
    what = text[len("your "):] if text.startswith("your ") else text
    what = what[:-len(" is up")] if what.endswith(" is up") else what
    return f"About {liveness.spoken_duration(left)} left; your {what} goes off {speech.humanize_time(at.isoformat())}."


def _top_memory() -> str:
    """Which programs hold the most memory, from psutil - a number this
    machine can read, not a thought ("I can't tell you ... open a terminal,
    run top", 2026-10-05)."""
    from aletheia import speech
    try:
        import psutil
        shares: dict[str, int] = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                name = p.info["name"] or "?"
                rss = int(p.info["memory_info"].rss) if p.info["memory_info"] else 0
            except Exception:
                continue
            shares[name] = shares.get(name, 0) + rss
        total = psutil.virtual_memory().total
    except Exception:
        return "I can't read this machine's memory by program right now."
    if not shares:
        return "I can't see any programs' memory right now."
    top = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)[:3]

    def size(n: int) -> str:
        return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n // 2**20} MB"

    lines = [f"{name.removesuffix('.exe')} at {size(n)}" for name, n in top]
    said = f"{speech.and_list(lines)}, out of {size(total)} in the machine."
    return said[:1].upper() + said[1:]


def _running() -> str | None:
    """Which parts are up, out of her own process list.

    `include_tasks=False`: the scheduled-task query is the slow half
    (0.6 s against ~20 ms for the rest) and the headline never uses it.
    The full picture, logon tasks included, is `python -m aletheia.running`.
    """
    import sys
    from aletheia import running
    try:
        said = running.headline(running.snapshot(include_tasks=False))
    except Exception:
        return None             # she does not know; the planner may look
    core = sys.modules.get("aletheia.core")
    if core is not None and getattr(core, "SERVERS", None) and str(said).startswith("Nothing of mine is running"):
        # The process list has no Core of hers - and she is the Core
        # answering ("summarize my day", 2026-10-05). Herself first.
        return "The Core is running - I'm it."
    return said


def _working() -> str:
    """The work session, if one is live, else that there is none and how
    long she has been up."""
    from aletheia import speech, work_session
    try:
        state = work_session.status()
    except Exception:
        state = {}
    if state.get("active"):
        left = int(state.get("actions_left") or 0)
        when = speech.humanize_time(str(state.get("expires") or "")) if state.get("expires") else ""
        return (f"I'm in a work session with {speech.count_phrase(left, 'action')} left"
                + (f", until {when}" if when else "") + ".")
    up = _uptime()
    return "I'm not in a work session." + (f" {up}" if up else "")


def _looked_up() -> str:
    """What she searched or read on the web today, from the journal."""
    from aletheia import localtime, recollection, speech
    today = localtime.today().isoformat()
    try:
        entries, readable = recollection._read_journal(recollection.TODAY_HOURS)
    except Exception:
        entries, readable = [], False
    if not readable:
        return "I can't read my journal just now."
    lines: list[str] = []
    for e in entries:
        subject = str(e.get("subject") or "")
        if recollection._local_date(str(e.get("ts") or "")) != today:
            continue
        text = str(e.get("text") or "")
        if subject == "research":
            m = re.search(r"for '([^']+)'", text)
            line = f"searched for {m.group(1)}" if m else speech.plainly(text)[:80]
        elif subject == "browser:read":
            m = re.match(r"read (\S+)(?: — (.+))?", text)
            line = f"read {m.group(2) or m.group(1)}" if m else speech.plainly(text)[:80]
        else:
            continue
        line = line.rstrip(".")
        if line not in lines:
            lines.append(line)
    if not lines:
        return "Nothing looked up today."
    return f"Today I {speech.and_list(lines[-4:])}."


def _hunting_for() -> str:
    """The roles she hunts for, from the roles read off his resume, and the
    kinds of work he said he wants and will not do."""
    from aletheia import campaign, profile, speech
    roles = None
    try:
        _path, text = campaign.read_resume("")
        roles = campaign.roles_remembered(text)
    except Exception:
        roles = None
    wanted, unwanted = "", ""
    try:
        known = profile.known()
        wanted, unwanted = str(known.get("work_wanted") or ""), str(known.get("work_not_wanted") or "")
    except Exception:
        pass
    parts = []
    if roles:
        parts.append("Looking for " + speech.and_list([str(r) for r in roles[:6]]) + ", off your resume")
    else:
        parts.append("I read the roles off your resume each time I search; none are remembered yet")
    if wanted:
        parts.append("You want " + _steer_list(wanted))
    if unwanted:
        parts.append("You won't do " + _steer_list(unwanted, either=True))
    return ". ".join(parts) + "."


def _steer_list(value: str, *, either: bool = False) -> str:
    """A steering field is kept as "a; b; c" (profile.steer_by); it is said
    as a list ("not anything in sales; recruiters" was read out, 2026-10-05).
    What he won't do takes "or": "anything in sales or recruiters"."""
    from aletheia import speech
    items = [p.strip().rstrip(".") for p in str(value or "").split(";") if p.strip()]
    if not items:
        return str(value or "").rstrip(".")
    return speech.or_list(items) if either else speech.and_list(items)


def _work_wants() -> str:
    """What he said he wants and will not do, verbatim from his profile."""
    from aletheia import profile
    try:
        known = profile.known()
    except Exception:
        return "I can't read your profile right now."
    wanted, unwanted = str(known.get("work_wanted") or ""), str(known.get("work_not_wanted") or "")
    if not wanted and not unwanted:
        return "You haven't told me what work you want or won't do; tell me and I'll steer by it."
    said = []
    if wanted:
        said.append("You want " + _steer_list(wanted))
    if unwanted:
        said.append("You won't do " + _steer_list(unwanted, either=True))
    return ". ".join(said) + "."


def _mine_from(text: str) -> str | None:
    """The `mine` key with the sentence itself: a bare "where do I work"
    captures no field, so the words choose it."""
    low = _tidy(text)
    found = next((p.match(low) for n, p in PATTERNS if n == "mine"), None)
    g = {k: v for k, v in (found.groupdict() if found else {}).items() if v}
    what = g.get("mine") or g.get("mine2") or g.get("mine3") or g.get("mine4") or ""
    if not what:
        if re.search(r"\bwork\b|\bemployer\b|\bcompany\b", low):
            what = "employer"
        elif re.search(r"\bwhat do i do\b", low):
            what = "job"
        else:
            what = "name"
    return _mine(what)


def _mine(what: str) -> str | None:
    """One fact about him, from his profile. Never guessed: an invented
    phone number is the exact failure `profile` exists to prevent.

    `profile.answer` reads her memory of him as well as the profile
    itself, so a fact she holds in one store is not denied from the
    other — which is how "where do I live" answered "I don't have your
    city on file" while "Hartford, SD 57033" sat on the same disk.
    """
    from aletheia import profile
    asked = " ".join(str(what or "").split()).casefold() or _WHO_AM_I
    if asked == "job":
        # "what's my job" / "what do I do": the title, at the employer
        title, employer = profile.answer("current_title"), profile.answer("current_employer")
        if title and employer:
            article = "an" if str(title)[:1].casefold() in "aeiou" else "a"
            return f"You're {article} {title} at {employer}."
        if employer:
            return f"You work at {employer}. I don't have your job title - tell me and I'll remember it."
        if title:
            return f"Your job title is {title}. I don't have your employer - tell me and I'll remember it."
        return "I don't have your job on file. Say 'I work at ...' and 'my title is ...' and I'll remember both."
    fields = _MINE.get(asked)
    if not fields:
        return None
    try:
        for field in fields:
            value = profile.answer(field)
            if value:
                # A sentence, not a bare value: "what's my name" answered
                # "Pat" (sandbox, 2026-10-05), which out loud is a word
                # with nothing around it. For "name", the whole name when
                # she has it.
                said = str(value)
                if asked in ("name", "full name") and field == "first_name":
                    last = profile.answer("last_name")
                    if last and str(last) not in said:
                        said = f"{said} {last}"
                if field == "current_employer":
                    return f"You work at {said}."
                if field == "current_title":
                    return f"Your job title is {said}."
                if field == "desired_pay":
                    # "Your minimum salary is $100,000 minimum" (2026-10-05):
                    # the fact already says which end of the range it is, and
                    # "Your salary is 110k" is not true of a job he has not got.
                    return f"You're asking {said}."
                return f"Your {asked} is {said}."
    except Exception:
        return None
    return (f"I don't have your {asked} on file. "
            "Tell me and I'll remember it.")


_STOP_WORDS = {"the", "a", "an", "my", "his", "her", "our", "that", "this", "is", "are", "was", "of",
               "to", "for", "and", "about", "up", "on", "in", "at", "it", "me", "you"}


def _notes_count() -> str:
    from aletheia import speech
    rows = _notes()
    if not rows:
        return 'No notes yet. Say "note that" or "remember that" and I\'ll keep it.'
    newest = " ".join(str(rows[0].get("text") or "").split()).rstrip(".")
    return f"{speech.count_phrase(len(rows), 'note')}. The newest: {newest}."


def _notes(limit: int = 200) -> list[dict]:
    """His notes, newest first: the journal lines `note` writes."""
    from aletheia import journal
    try:
        entries = journal.entries()
        # A note he told her to forget carries a later tombstone
        # (intercom.FORGOTTEN_SUBJECT); the journal is append-only, so this
        # is how "forget my sister's name" takes effect on every reader.
        forgotten = {str(e.get("text") or "")[:300] for e in entries if e.get("subject") == "operator:forgotten"}
        rows = [e for e in entries if e.get("kind") == "note" and e.get("subject") == "operator"
                # the room's unmatched transcripts are journaled as notes;
                # "(voice, unmatched) north korea" is not a note of his
                and not str(e.get("text") or "").startswith("(voice")
                and str(e.get("text") or "")[:300] not in forgotten]
    except Exception:
        return []
    return list(reversed(rows))[:limit]


def _drafts() -> str:
    from aletheia import mail
    return mail.held_drafts_words()


def _draft_to(name: str) -> str:
    """The newest held draft to `name`, read back: who, when, subject, words."""
    from aletheia import mail, speech
    who = " ".join(str(name or "").split()).casefold()
    if not who:
        return "Who is the draft to?"
    try:
        rows = mail.held_drafts()
    except Exception:
        return "I can't read my drafts right now."
    hit = next((d for d in rows if who in str(d.get("to_name") or "").casefold()
                or who in str(d.get("to") or "").casefold()), None)
    if hit is None:
        return f"I have no draft to {name}."
    body = " ".join(str(hit.get("body") or "").split())
    if len(body) > 300:
        body = body[:300].rsplit(" ", 1)[0] + "…"
    when = speech.humanize_time(str(hit.get("created") or "")) if hit.get("created") else ""
    to = str(hit.get("to_name") or hit.get("to") or name)
    subject = str(hit.get("subject") or "").strip()
    return (f"To {to}" + (f", drafted {when}" if when else "") + (f", '{subject}'" if subject else "")
            + f": {body}" if body else f"To {to}" + (f", drafted {when}" if when else "") + ": no words in it yet.")


def _sending(asked: str = "") -> str:
    """Whether outward mail goes out right now, from the hold she keeps.
    `asked` is the hold word he used ("on hold", "off", "holding"), so a
    yes-or-no fits HIS question: "is the mail hold on" is "Yes"."""
    from aletheia import mail, speech
    hold = mail.outward_hold()
    try:
        held = [r for r in mail.drafts_ledger() if not r.get("superseded_by")]
    except Exception:
        held = []
    asked = str(asked or "").strip().casefold()
    about_hold = bool(asked)
    asked_if_lifted = asked in ("off", "lifted")
    if hold["on"]:
        first = ("No, it's still on" if asked_if_lifted else "Yes" if about_hold else "No")
        return (f"{first}. Outward mail is on hold since you said so - I draft and keep, nothing goes out"
                + (f"; {speech.count_phrase(len(held), 'draft')} held" if held else "")
                + ". Lifting it is yours, at the keyboard.")
    first = ("Yes, the hold is lifted" if asked_if_lifted else "No, the hold is lifted" if about_hold else "Yes")
    return (f"{first}, so an approved draft goes out on my next beat"
            + (f"; {speech.count_phrase(len(held), 'draft')} still held" if held else "") + ".")


def _applied_on(rest) -> str:
    """Which jobs went out today (or yesterday), from her own records."""
    import datetime as dt
    from aletheia import apply_run, localtime, speech
    when = "yesterday" if "yesterday" in str(rest or "").casefold() else "today"
    tz = localtime.operator_tz()
    day = (dt.datetime.now(tz) - dt.timedelta(days=1 if when == "yesterday" else 0)).date()
    try:
        rows = apply_run.all_runs("SUBMITTED")
    except Exception:
        return "I can't read my application records right now."
    sent = []
    for r in rows:
        stamp = str(r.get("submitted_at") or "")
        try:
            local = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if local != day:
            continue
        company = " ".join(str(r.get("company") or "").split())
        title = " ".join(str(r.get("job_title") or r.get("title") or "").split())
        sent.append((company, title))
    if not sent:
        return f"Nothing went out {when}."
    said = []
    for company, title in sent[:6]:
        # A stored title often already carries the employer ("Customer
        # Success Manager — Okta"); "— Okta at Okta" is the record read twice.
        if company and title and company.casefold() in title.casefold():
            said.append(title)
        else:
            said.append(f"{title} at {company}" if company and title else (company or title or "one I did not name"))
    return (f"{speech.count_phrase(len(sent), 'application')} went out {when}: {speech.and_list(said)}"
            + (f", and {len(sent) - 6} more" if len(sent) > 6 else "") + ".")


def _why_that() -> str:
    """Why she did the last thing: the sentence of his that got that
    answer, from the thread, never a motive she invents."""
    from aletheia import converse, recollection
    try:
        rows = recollection.day()
    except Exception:
        rows = []
    try:
        turns = converse.recent(limit=8)
    except Exception:
        turns = []
    if not rows:
        return "I haven't done anything today to explain."
    did = str(rows[-1].get("what") or "").rstrip(".")
    key = did.casefold()[:24]
    asked = ""
    for turn in reversed(turns):
        if key and str(turn.get("she_answered") or "").casefold().startswith(key):
            asked = str(turn.get("he_asked") or "")
            break
    if asked:
        return f"Because you said \"{asked}\" - so I did: {did[:1].lower() + did[1:]}."
    return f"The last thing I did was: {did[:1].lower() + did[1:]}. I don't have the sentence that asked for it in this conversation."


def _sure() -> str:
    """How sure she is of her last answer: a store or a model, from the
    thread's own record of where it came from."""
    from aletheia import converse
    try:
        turns = converse.recent(limit=1)
    except Exception:
        turns = []
    if not turns:
        return "I haven't answered anything yet this conversation to be sure about."
    last = turns[-1]
    said = str(last.get("she_answered") or "").strip()
    how = str(last.get("how") or "")
    if how == "stores":
        return f"Yes - that came straight from my own records, not a guess: {said}"
    if how == "model":
        return ("That one came from a model reading my records, so it can be wrong. "
                "Ask me the plain question and I'll read it from the store.")
    return "I can't say how sure - I don't have a record of where that answer came from."


def _who_made() -> str:
    return ("You did. Claude and Codex wrote the code under your direction, on your "
            "subscriptions, and I think with Claude and ChatGPT when they're there and "
            "with my own model when they're not. Nobody else's keys are in me.")


def _best_found() -> str:
    """The standouts of today's discovery summary, by value, or that she has
    not gone looking yet - never a guess about a job she did not see."""
    from aletheia import job_discovery, speech
    try:
        summary = job_discovery.today()
    except Exception:
        return "I can't read today's search right now."
    if not summary:
        return job_discovery.spoken(None)
    rows = job_discovery.standouts(summary, n=3)
    if not rows:
        return job_discovery.spoken(summary) + " None stood out."
    named = [f"{r.get('title') or 'a role'} at {r.get('company') or 'an employer I did not catch the name of'}" for r in rows]
    lead = "The best today" if len(named) == 1 else "The best today, in order"
    return f"{lead}: {speech.and_list(named)}."


def _project_of(name: str) -> str | None:
    """One charter by the name he calls it: where it stands and whose turn
    it is. None when the words name no charter and no fleet repository, so
    the planner still gets "what's the weather doing"."""
    from aletheia import plans, speech
    wanted = " ".join(str(name or "").split())
    if not wanted or wanted in ("weather", "the weather", "time", "market", "the market"):
        return None
    try:
        plan, why = plans.find_charter(wanted)
    except Exception:
        return None
    if plan is None:
        if why.startswith("Which"):
            return why
        try:
            from aletheia import current_state
            repo = current_state.repo_words(wanted)
        except Exception:
            repo = None
        if repo:
            return repo
        return (f"I don't have a project called {wanted} on record. Say \"new project: {wanted}\" "
                "and a sentence about it, and I'll draft a charter for you to confirm.")
    title = str(plan.get("title") or plan.get("slug") or wanted)
    done, total = plans.progress(plan)
    step = plans.next_step(plan)
    if plan.get("state") == "proposed":
        return f"{title} is a draft charter waiting for your yes - say yes to it and I'll start."
    if step is None:
        return f"{title}: every step is done, {done} of {total}."
    who = plans.owner(step)
    turn = "that one's yours" if who == "operator" else "that one's mine"
    return (f"{title}: {done} of {total} steps done. Next is step {step.get('n')}, "
            f"{speech.tidy(str(step.get('text') or '')).rstrip('.')} - {turn}.")


def _resume_says() -> str:
    """The resume she reads, in one breath: which file, how long, what it is
    for, and how it opens. Never a summary she made up."""
    from aletheia import campaign, speech
    try:
        path, text = campaign.read_resume("")
    except Exception:
        return ("I can't find a resume on this PC. I look in Documents, Downloads and Desktop "
                "for a file with resume or CV in its name.")
    import os
    name = os.path.basename(str(path))
    words = len(str(text or "").split())
    try:
        roles = campaign.roles_remembered(text) or []
    except Exception:
        roles = []
    first = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    said = f"Your resume is {name}, about {speech.count_phrase(words, 'word')}."
    if roles:
        said += f" It reads as a resume for {speech.and_list([str(r) for r in roles[:4]])}."
    if first:
        said += f" It opens: '{first[:120]}'."
    return said


def _weekend() -> str:
    """Saturday and Sunday from the calendar mirror, in one breath."""
    from aletheia import speech
    days = []
    for name in ("saturday", "sunday"):
        said = _agenda(name)
        if said is None:
            return "I can't read your calendar right now."
        days.append((name.capitalize(), said))
    empty = [n for n, s in days if s.startswith("Nothing on your calendar")]
    if len(empty) == 2:
        return "Nothing on your calendar this weekend - Saturday and Sunday are both clear."
    parts = []
    for name, said in days:
        parts.append(f"{name} is clear" if said.startswith("Nothing on your calendar")
                     else said.rstrip("."))
    return speech.and_list(parts) + "."


def _what_day(words: str) -> str | None:
    """"What day is the 20th" / "what day is Christmas": the weekday, and
    how far off. None for words that name no date."""
    from aletheia import localtime
    today = localtime.today()
    when = _named_date(words, today)
    if when is None:
        when, _about = _remembered_date(words, today)
    if when is None:
        return None
    days = (when - today).days
    away = "today" if days == 0 else "tomorrow" if days == 1 else f"{days} days away"
    thing = " ".join(str(words or "").split())
    thing = thing if thing.startswith("the ") or thing[:1].isdigit() else thing[:1].upper() + thing[1:]
    thing = f"the {thing}" if thing[:1].isdigit() else thing
    return f"{thing[:1].upper() + thing[1:]} is a {when.strftime('%A')}, {when.day} {when.strftime('%B')} - {away}."


def _week_number() -> str:
    import datetime as dt
    from aletheia import localtime
    today = localtime.today()
    year, week, _ = today.isocalendar()
    monday = today - dt.timedelta(days=today.weekday())
    return f"Week {week} of the year, the one that started Monday {monday.day} {monday.strftime('%B')}."


def _leap_year(words: str = "") -> str:
    import calendar as _calendar
    from aletheia import localtime
    year = int(words) if str(words or "").strip().isdigit() else localtime.today().year
    if _calendar.isleap(year):
        return f"Yes, {year} is a leap year - February has 29 days."
    after = next(y for y in range(year + 1, year + 9) if _calendar.isleap(y))
    return f"No, {year} isn't a leap year. The next one is {after}."


def _dst() -> str:
    """When the clocks next change, from his own time zone's rules - no
    model and no table of her own."""
    import datetime as dt
    from aletheia import localtime
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    offset = now.utcoffset()
    probe = now.replace(hour=12, minute=0, second=0, microsecond=0)
    for ahead in range(1, 400):
        day = probe + dt.timedelta(days=ahead)
        day = day.replace(tzinfo=None).replace(tzinfo=tz)
        if day.utcoffset() != offset:
            # the change happened between yesterday noon and today noon:
            # find the hour by walking back
            before = day - dt.timedelta(days=1)
            back = "back" if day.utcoffset() < offset else "forward"
            said = f"{before.strftime('%A')} night into {day.strftime('%A')} {day.day} {day.strftime('%B')}"
            if ahead == 1:
                said = "tonight"
            on_dst = bool(now.dst())
            now_line = "You're on daylight saving time now" if on_dst else "You're on standard time now"
            return f"{now_line}. The clocks go {back} an hour {said}, {ahead} days from now."
    return "Your time zone doesn't change its clocks."


def _my_list() -> str | None:
    from aletheia import intercom
    try:
        return intercom.my_list_answer()
    except Exception:
        return None


def _contacts_all() -> str | None:
    """Who she has saved, from the contacts store, said by `intercom` so the
    voice door and this one cannot drift."""
    from aletheia import intercom
    try:
        return intercom._contacts_answer("")
    except Exception:
        return None


def _deadlines(first: bool = False) -> str:
    """"Which tasks have deadlines" / "what's due soonest" (2026-10-05: a
    model each). His open tasks that carry a deadline, soonest first."""
    import datetime as dt
    from aletheia import localtime, speech, tasks
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    try:
        rows = [r for r in tasks.due(now=now.astimezone(dt.timezone.utc), within_hours=24 * 3650) if tasks.is_his(r["task"])]
    except Exception:
        return "I can't read your task list right now."
    rows.sort(key=lambda r: r["when"])
    if not rows:
        return "None of your open tasks has a deadline. Say 'the passport task is due Friday' and I'll put one on it."
    said = []
    for row in rows[: (1 if first else 5)]:
        what = _shortened(str(row["task"].get("description") or "").strip().rstrip("."))
        day = _day_phrase(row["when"].astimezone(tz).date(), now.date())
        said.append(f"{what} is overdue" if row["overdue"] else f"{what} by {day}")
    if first:
        return f"Soonest: {said[0]}."
    return (f"{speech.count_phrase(len(rows), 'task')} with a deadline: " + "; ".join(said)
            + (f"; and {len(rows) - 5} more" if len(rows) > 5 else "") + ".")


def _finished(when: str = "") -> str:
    """"How many tasks did I finish this week" (2026-10-05: nineteen seconds
    on a model, which looked three places and counted nothing). The task
    store keeps finished tasks with the time they were finished."""
    import datetime as dt
    from aletheia import localtime, speech, tasks
    which = " ".join(str(when or "").casefold().split()) or "today"
    tz = localtime.operator_tz()
    today = localtime.today()
    if which == "yesterday":
        lo, hi = today - dt.timedelta(days=1), today
    elif which == "this week":
        lo, hi = today - dt.timedelta(days=today.weekday()), today + dt.timedelta(days=1)
    elif which == "this month":
        lo, hi = today.replace(day=1), today + dt.timedelta(days=1)
    else:
        lo, hi = today, today + dt.timedelta(days=1)
    done = []
    try:
        for t in tasks.all_tasks():
            if str(t.get("status") or "").upper() != "COMPLETED" or not tasks.is_his(t):
                continue
            try:
                at = dt.datetime.fromisoformat(str(t.get("updated_at") or "").replace("Z", "+00:00")).astimezone(tz).date()
            except ValueError:
                continue
            if lo <= at < hi:
                done.append(str(t.get("description") or t.get("id")))
    except Exception:
        return "I can't read your task list right now."
    span = {"today": "today", "yesterday": "yesterday", "this week": "this week", "this month": "this month"}.get(which, which)
    if not done:
        return f"No tasks marked done {span}. (I only count what you marked done with me.)"
    return f"{speech.count_phrase(len(done), 'task')} done {span}: {speech.and_list([_shortened(d) for d in done[:5]])}" \
        + (f", and {len(done) - 5} more" if len(done) > 5 else "") + "."


def _second() -> str:
    """"What's after that" (2026-10-05: a model). The second open task."""
    from aletheia import intercom
    try:
        rows = intercom._open_tasks()
    except Exception:
        return "I can't read your task list right now."
    if not rows:
        return "Nothing - your task list is empty."
    if len(rows) == 1:
        return f"Nothing after that - {_shortened(str(rows[0].get('description') or ''))} is the only thing on your list."
    rest = len(rows) - 2
    return (f"Then {_shortened(str(rows[1].get('description') or ''))}."
            + (f" {speech_count(rest)} after that." if rest else " That's the list."))


def speech_count(n: int) -> str:
    from aletheia import speech
    return speech.count_phrase(n, "more thing").replace("more things", "more").replace("more thing", "more")


def _due_week(when: str = "") -> str:
    """His tasks with a deadline and his reminders inside the window, from
    the two stores and the clock. Nothing here guesses: a task with no
    deadline is not "due", and a reminder she has switched off is not
    coming."""
    import datetime as dt
    from aletheia import intercom, localtime, scheduler, speech, tasks
    which = " ".join(str(when or "").casefold().split()) or "this week"
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if which == "today":
        end = start_of_day + dt.timedelta(days=1)
    elif which == "tomorrow":
        end = start_of_day + dt.timedelta(days=2)
    elif which == "next week":
        end = start_of_day + dt.timedelta(days=14)
    else:
        end = start_of_day + dt.timedelta(days=7)
    hours = (end - now).total_seconds() / 3600.0
    lines: list[str] = []
    try:
        for row in tasks.due(now=now.astimezone(dt.timezone.utc), within_hours=hours):
            task = row["task"]
            if not tasks.is_his(task):
                continue
            what = _shortened(str(task.get("description") or "").strip().rstrip("."))
            day = _day_phrase(row["when"].astimezone(tz).date(), now.date())
            lines.append(f"{what} is overdue" if row["overdue"] else f"{what} by {day}")
    except Exception:
        return "I can't read your task list right now."
    try:
        reminders = intercom._reminder_schedules()
    except Exception:
        reminders = []
    for spec in reminders:
        try:
            coming = scheduler.next_occurrence(spec, now.astimezone(dt.timezone.utc))
        except Exception:
            continue            # one unreadable schedule is not the whole week
        if coming is None or coming.astimezone(tz) >= end:
            continue
        text = str((spec.get("command") or {}).get("text") or "").strip().rstrip(".")
        lines.append(f"a reminder to {text} {speech.humanize_time(coming.isoformat())}")
    label = {"today": "Today", "tomorrow": "Tomorrow", "next week": "Next week"}.get(which, "This week")
    if not lines:
        return f"Nothing due {which}: no task with a deadline and no reminder set for it."
    return f"{label}: " + "; ".join(lines[:6]) + (f" - and {speech.count_phrase(len(lines) - 6, 'other thing')}" if len(lines) > 6 else "") + "."


def _day_phrase(day, today) -> str:
    """"today", "tomorrow", "Friday", "Monday the 20th" - a day as a person
    names one, never an ISO date out loud."""
    ahead = (day - today).days
    if ahead <= 0:
        return "today"
    if ahead == 1:
        return "tomorrow"
    if ahead < 7:
        return day.strftime("%A")
    return f"{day.strftime('%A')} the {_ordinal(day.day)}"


def _asked_on(rest) -> str:
    """What he asked her on a day, from the journal of his own words."""
    import datetime as dt
    from aletheia import converse, journal, localtime, recollection, speech
    words = str(rest or "").casefold()
    days_ago = 1 if ("yesterday" in words or "last night" in words) else 0
    when = "yesterday" if days_ago else "today"
    tz = localtime.operator_tz()
    date = (dt.datetime.now(tz) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%d")
    try:
        rows = [e for e in journal.entries()
                if e.get("kind") == "note" and e.get("subject") == converse.ASKED_SUBJECT
                and recollection._local_date(str(e.get("ts") or "")) == date]
    except Exception:
        return "I can't read my journal right now."
    if not rows:
        return f"Nothing from you {when} that I wrote down."
    asks = []
    for e in rows:
        line = " ".join(str(e.get("text") or "").split()).strip(" .?!")
        if line and line.casefold() not in {a.casefold() for a in asks}:
            asks.append(line)
    shown = [f"'{_shortened(a)}'" for a in asks[-5:]]
    said = f"{when.capitalize()} you asked me: " + "; ".join(shown)
    if len(asks) > 5:
        said += f" - and {speech.count_phrase(len(asks) - 5, 'other thing')}"
    return said + "."


def _hunt_why() -> str:
    """Why the job hunt is or is not moving, from its own switches, in order:
    his stop, his pause, the grant, who can think, the browser - then
    "nothing is stopping it" with the day's numbers. Every line names a
    fact on disk; nothing here guesses."""
    from aletheia import policy
    try:
        halt = policy.halted()
    except Exception:
        halt = None
    if halt:
        return ("Because you stopped everything" + (f" ({halt.get('reason')})" if isinstance(halt, dict) and halt.get("reason") else "")
                + ". Say resume and the hunt picks back up.")
    try:
        from aletheia import apply_forever
        held = apply_forever.paused()
    except Exception:
        held = None
    if held:
        return ("Because you said stop applying" + (f" ({held.get('reason')})" if held.get("reason") else "")
                + ". Say start applying and it picks back up.")
    parts = []
    try:
        from aletheia import apply_run, speech, standing
        grant = standing.jobs_status()
        waiting = [r for r in apply_run.all_runs("AWAITING_YOU")
                   if r.get("engine") != apply_run.ENGINE_LOOP and not apply_run.waits_for_his_ok(r)]
        # Only when something IS waiting: "filled applications wait for
        # your tap" with nothing filled is a sentence about nothing.
        if waiting and not grant.get("granted"):
            parts.append(f"{speech.count_phrase(len(waiting), 'filled application')} "
                         f"wait{'s' if len(waiting) == 1 else ''} for your tap, "
                         f"because the standing grant to send {'it' if len(waiting) == 1 else 'them'} is not on")
    except Exception:
        pass
    try:
        from aletheia import apply_forever
        ok, why = apply_forever._another_mind()
        from aletheia import reasoner
        resting = reasoner.resting_until()
        if resting is not None and not ok:
            parts.append(f"nobody can judge a job right now - Claude is resting and {why}; the hunt waits for a model")
    except Exception:
        pass
    try:
        from aletheia import browse
        ok, why = browse.available()
        if not ok:
            parts.append(f"her browser is not ready ({why})")
    except Exception:
        pass
    try:
        from aletheia import campaign
        live = campaign.running()
    except Exception:
        live = None
    try:
        from aletheia import current_state
        today = current_state.job_hunt_words()
    except Exception:
        today = ""
    if parts:
        return "The hunt is held up: " + "; ".join(parts) + "." + (f" {today}" if today else "")
    if live:
        return ("Nothing is stopping it - a batch is running right now"
                + (f", started {str(live.get('started_at') or '')[11:16]}Z" if live.get("started_at") else "")
                + "." + (f" {today}" if today else ""))
    # No switch of hers explains it and nothing is running: that is a "why"
    # the investigator answers from the journal and the receipts. A quick
    # "nothing is stopping it" here would remove that answer, not latency.
    return None


def _interview_window() -> str:
    """His interview window, from her own switch: the hours, and whether
    she books inside them on her own or only tells him."""
    from aletheia import interviews
    state = interviews.status()
    when = interviews.window_words(state["window"])
    if state["on"]:
        return (f"{when}, on weekdays. When an employer sends a scheduling link I book inside that "
                "and put it on your calendar; no email goes out.")
    return (f"{when}, on weekdays - but interview booking is switched off, so I only tell you when an "
            "employer asks. The switch is 'python -m aletheia.interviews on' at your keyboard.")


def _ran_today(name: str) -> str | None:
    """"Did the shorts pipeline run today": the pulse's row for that repo.
    A name the pulse does not know is left to a model, never guessed."""
    import datetime as dt
    from aletheia import current_state, speech
    words = re.sub(r"\s+", " ", str(name or "")).strip()
    if not words:
        return None
    if _no_pulse():
        return "No fleet reading yet - the pulse hasn't been written on this machine, so I can't say."
    try:
        row = current_state.repo_row(words)
    except Exception:
        row = None
    if row is None:
        return None
    said = str(row.get("github") or words)
    flows = row.get("workflows") if isinstance(row.get("workflows"), dict) else {}
    runs = sorted(((str(w.get("updated_at") or ""), n, w) for n, w in flows.items()
                   if isinstance(w, dict) and w.get("updated_at")), reverse=True)
    if not runs:
        return f"The pulse has no runs on record for {said}."

    def verdict(w: dict) -> str:
        c = str(w.get("conclusion") or "")
        return {"success": "green", "failure": "red", "cancelled": "cancelled", "skipped": "skipped"}.get(
            c, c or str(w.get("status") or "still going"))
    # HIS day, not UTC's: at 00:30Z the same run read "today ... tomorrow at
    # 10:57 am" because the date was compared in UTC and said in his zone.
    from aletheia import localtime
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()

    def his_day(stamp: str):
        try:
            return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            return None
    ran = [(s, n, w) for s, n, w in runs if his_day(s) == today]
    if ran:
        named = [f"{n.replace('.yml', '')} {verdict(w)} {speech.humanize_time(s).replace('today at ', 'at ')}"
                 for s, n, w in ran[:4]]
        more = f", and {len(ran) - 4} more" if len(ran) > 4 else ""
        return f"Yes. {said} today: " + "; ".join(named) + more + "."
    s, n, w = runs[0]
    return f"Not today. The last run of {said} was {n.replace('.yml', '')}, {verdict(w)}, {speech.humanize_time(s)}."


def _who_are_you(rest: str = "") -> str:
    """Who she is, in one breath. A fact about herself, not a thought."""
    asked = " ".join(str(rest or "").casefold().split())
    if asked.startswith(("why", "what does", "what's", "what is", "where does", "who named")):
        return ("Thea is short for Aletheia, the name you gave me - Greek for truth, or unconcealment - "
                "which is the job: saying plainly what I can and can't do.")
    if asked:
        if re.search(r"\b(?:human|person|real person|alive)\b", asked):
            return ("No, I'm not a person. I'm Thea - Aletheia - software of yours running on this PC, with your own stores "
                    "and a big model helping me think when one is there.")
        if re.search(r"\b(?:chatgpt|chat gpt|claude|siri|alexa|google)\b", asked):
            return ("No. I'm Thea - Aletheia - your own assistant on this PC. Claude and ChatGPT are workers I ask to think "
                    "when they're there; the stores, the rules and the kill switch are mine.")
        return ("Yes - I'm software. Thea, Aletheia, your own assistant running on this PC: your stores, your rules, "
                "and a big model helping me think when one is there.")
    # Said TO him: "Caleb's own assistant ... I keep his tasks" was the third
    # person about the person asking (sandbox, 2026-10-05).
    return ("I'm Thea - Aletheia - your own assistant, running on this PC. I keep your tasks, "
            "reminders, lists, notes and calendar, read and draft your email, hunt and apply for jobs, "
            "watch your projects, and I say plainly what I can't do. The big models help me think when "
            "they're there; my own stores and my own model carry me when they're not.")


def _unattended_allowed() -> str:
    """What runs without his yes, from the tool descriptors: every read, and
    the reversible writes in her own stores, under the daily allowance."""
    from aletheia import speech, tools
    try:
        cat = tools.catalog()
        # the descriptor's own word: a WRITER (not read_only) whose consequence
        # is reversible and local, and whose approval is none
        groups = sorted({tools.group_of(n) for n, t in cat.items()
                         if tools.runs_unattended(t) and not getattr(t, "read_only", False)
                         and getattr(t, "consequence", "") == "reversible_local"
                         and getattr(t, "approval", "") == "none" and tools.group_of(n)})
    except Exception:
        groups = []
    said = ("Anything that only reads - your lists, your calendar, your mail, your files, the fleet. "
            "And small reversible things in my own stores")
    if groups:
        said += " - " + speech.and_list(groups)
    return (said + " - each one undoable, each one reported, under a daily allowance. Everything that reaches "
            "somebody else or can't be taken back waits for your yes, and spending money is refused outright.")


def _allowed_to(what: str) -> str | None:
    """"Are you allowed to send emails": what she can do, and whose yes it takes."""
    from aletheia import capabilities, self_knowledge
    asked = " ".join(str(what or "").split()).rstrip("?. ")
    can = _can_you(asked)
    if not can:
        return None
    try:
        best = (self_knowledge.for_question(asked).get("matches") or [{}])[0]
        entry = capabilities.get(str(best.get("capability") or ""))
        policy = str(entry.get("approval_policy") or "")
    except Exception:
        policy = ""
    line = {"operator_always": " Only with your yes each time - it's never done on a standing grant.",
            "operator_once": " It asks you the first time and then runs.",
            "registry_grant": " Under a standing grant you give at the keyboard, or with your yes each time.",
            "none": " Without asking - it's reversible and stays on this machine."}.get(policy, "")
    return can.rstrip() + line


def _offline_can() -> str:
    """What works with no model at all: the fast lane and the rules.

    Said from what is TRUE of the code, not from a model's guess: every
    item here is a fast-lane or rule answer that runs with the frontier
    hidden and her own model off (the 2026-09-24 battery).
    """
    from aletheia import reasoner
    try:
        role, why = reasoner.local_role_that_fits()
    except Exception:
        role, why = None, ""
    # `why` often already says "my own model is switched off"; saying it
    # twice in one breath is what the sandbox heard (2026-10-05).
    own = ("and my own model can plan the rest, slowly" if role
           else (f"but {why}" if why and "my own model" in why else f"but my own model can't run right now ({why})")
           if why else "")
    return ("Without the big models I still answer from what I hold: your tasks, reminders and lists; your "
            "calendar and whether you're free; your notes and what I know about you; today's applications, "
            "replies and interviews; what needs you, what went wrong, what I did and what you asked me; the "
            "drafts I'm holding; whether I'm halted; the time, the date and the weather. Simple orders still "
            "work - remind me, add a task, note this, stop applying, halt. What waits for a model is planning "
            "something new, judging a job, writing prose and reading a page I've never seen" + (f" - {own}." if own else "."))


def _cpu() -> str:
    """The processor right now and the three things using most of it.
    About a second: two samples, because a process's share is measured
    between them."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["name"]):
            try:
                p.cpu_percent(None)
                procs.append(p)
            except Exception:
                continue
        load = psutil.cpu_percent(interval=0.7)
        shares: dict[str, float] = {}
        for p in procs:
            try:
                name = p.info["name"] or "?"
                if name.casefold() == "system idle process":     # the idle share is not a user
                    continue
                shares[name] = shares.get(name, 0.0) + p.cpu_percent(None)
            except Exception:
                continue
    except Exception:
        return "I can't read this machine's processor right now."
    cores = max(1, psutil.cpu_count() or 1)
    top = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)[:3]
    named = [f"{n.removesuffix('.exe')} ({v / cores:.0f}%)" for n, v in top if v / cores >= 1]
    said = f"The processor is at {load:.0f}%."
    return said + (" Most of it: " + ", ".join(named) + "." if named else " Nothing is working it hard.")


def _memory_free() -> str:
    """Her machine's free memory, and which of her own models fits in it."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        free, total = vm.available / 1e9, vm.total / 1e9
    except Exception:
        return "I can't read this machine's memory right now."
    said = f"{free:.1f} GB free of {total:.0f}, {total - free:.1f} in use."
    try:
        from aletheia import reasoner
        role, why = reasoner.local_role_that_fits()
        said += (f" My {'bigger' if role == 'fast' else 'smaller'} model fits right now." if role
                 else f" Neither of my own models fits right now ({why}).")
    except Exception:
        pass
    return said


def _notes_list() -> str:
    from aletheia import speech
    rows = _notes()
    if not rows:
        return "No notes yet. Say \"note that\" or \"remember that\" and I'll keep it."
    said = [str(r.get("text") or "").strip().rstrip(".") for r in rows[:5]]
    out = f"{speech.count_phrase(len(rows), 'note')}: " + "; ".join(said)
    if len(rows) > 5:
        out += f"; and {len(rows) - 5} more"
    return out + "."


def _recall(words: str) -> str | None:
    """What he told her about `words`: his notes and her memory, by the
    words themselves. Nothing matching is said as nothing - never guessed."""
    from aletheia import memory, speech
    wanted = [w for w in re.findall(r"[a-z0-9']+", re.sub(r"'s\b", "", str(words or "").casefold()))
              if w not in _STOP_WORDS]
    if not wanted:
        return None
    try:
        # "When is spotify due" is the subscriptions store (2026-10-05).
        from aletheia import subscriptions
        merchants = [str(r.get("merchant") or "").casefold() for r in subscriptions.all_subscriptions()]
        if any(m and (m in str(words).casefold() or str(words).casefold() in m) for m in merchants):
            return _pay_for(words, want_date=True)
    except Exception:
        pass
    stems = [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in wanted]

    def hit(text: str) -> bool:
        low = str(text or "").casefold()
        return any(s in low for s in stems)

    found: list[str] = []
    for row in _notes():
        if hit(row.get("text")):
            found.append(f"you told me: {str(row.get('text')).strip().rstrip('.')}")
        if len(found) >= 3:
            break
    try:
        remembered = memory.everything(max_chars=8000)
    except Exception:
        remembered = {}
    for domain, entries in remembered.items():
        for key, held in entries.items():
            value = held.get("value")
            text = value if isinstance(value, str) else str(value)
            if hit(key) or hit(text):
                about = str(held.get("about") or "").strip()
                found.append(f"{about} is {text}" if about else f"{key.replace('_', ' ')}: {text}")
            if len(found) >= 5:
                break
    if not found:
        return f"I have nothing about {words} on file - tell me and I'll remember it."
    said = speech.and_list(found[:4])
    return said[:1].upper() + said[1:] + "."


def _home() -> str | None:
    """Where he lives — the city AND the state, which is how it is said.

    `_mine("city")` alone answers "Hartford", and the store holds the
    state next to it.
    """
    from aletheia import profile
    try:
        city, state = profile.answer("city"), profile.answer("state")
    except Exception:
        return None
    if not city:
        return ("I don't have your city on file. "
                "Tell me and I'll remember it.")
    # Bare, no full stop: `_mine` returns the value and not a sentence,
    # and "Hartford, SD" already reads as an answer.
    return f"{city}, {state}" if state else str(city)


def _where_am_i() -> str:
    """"Where am I": the city on file, and that she cannot see him."""
    home = _home()
    if not home or home.startswith("I don't have"):
        return "I can't see where you are, and I don't have your city on file - tell me and I'll remember it."
    return f"I can't see where you are. Your city on file is {home}."


def _weather(when: str = "") -> str | None:
    """What it is doing outside, from the free national service.

    No key anywhere, and his postcode is already on file — so the most
    ordinary question anybody asks needs nothing from him and no model.
    """
    try:
        from aletheia import weather
        return weather.spoken(when)
    except Exception as exc:
        # She LOOKED and could not: no postcode on file, the service down,
        # somewhere the service does not cover. Each of those messages
        # says what would fix it, and swallowing it sent the question to
        # a planner that, with no model, kept it for later - a worse
        # answer than the one she already had. Anything else is a bug and
        # stays None so the planner may try.
        try:
            from aletheia.weather import WeatherUnavailable
        except Exception:
            return None
        return str(exc) if isinstance(exc, WeatherUnavailable) and str(exc) else None


def _greeting() -> str | None:
    """Greeted back, plus the one thing he would have asked next.

    Everything here comes from `presence` and the kill switch: whether
    she is running, and what is waiting on him. A greeting is the moment
    that is most worth saying, and it was costing a planner round trip to
    say nothing.
    """
    from aletheia import policy
    try:
        halt = policy.halted()
        if halt:
            reason = str(halt.get("reason") or "").strip()
            return ("I'm here, but halted"
                    + (f" — {reason}." if reason else ".")
                    + " Nothing runs until you resume me.")
        from aletheia import presence, speech
        now = presence.snapshot()
        waiting = len(list(now.get("waiting_on_you") or []))
        notices = len(list(now.get("notifications") or []))
        if not waiting and not notices:
            return "I'm here. Nothing is waiting on you."
        bits = []
        if waiting:
            bits.append(f"{waiting} waiting on you")
        if notices:
            bits.append(f"{notices} I wanted to tell you about")
        # The list itself is one sentence away, and reading it out is what
        # "what's waiting on me" is for.
        return f"I'm here. {speech.and_list(bits)}."
    except Exception:
        return None


def _friction() -> str | None:
    """What he has had to do himself, from the friction ledger."""
    try:
        from aletheia import friction
        return friction.spoken()
    except Exception:
        return None


def status_of(text: str) -> tuple[str, str] | None:
    """(shape, subject) for a status question, or None. The shape is one of
    going / still / count / count_total / last_when / last_what / blocking /
    repo; the subject is his words for it."""
    found = _STATUS.match(_tidy(text))
    if not found:
        return None
    groups = {k: v for k, v in found.groupdict().items() if v}
    window = (groups.get("count_window") or groups.get("count2_window")
              or groups.get("count3_window") or groups.get("count3_window2"))
    if window:
        # "How many jobs did I apply to this week" waited two minutes on her
        # own model (2026-09-22); the records carry their dates. "How many
        # did you send this week" is the same count (2026-09-23), and "how
        # many have you applied to today" (2026-10-05).
        return "count_window", window.strip()
    for key, value in groups.items():
        if key.startswith("count"):
            total = bool(groups.get("count_total") or groups.get("count2_total"))
            return ("count_total" if total else "count"), "the job hunt"
        if key.startswith("going"):
            return "going", value
        if key.startswith("still"):
            return "still", value
        if key.startswith("paused"):
            return "paused", value
        if key.startswith("last_when"):
            return "last_when", value
        if key.startswith("last_what"):
            return "last_what", value
        if key.startswith("blocking"):
            return "blocking", value
        if key.startswith("repo"):
            return "repo", value
    return None


def _status_of(text: str) -> str | None:
    """Answer a status question from the store its subject names. Every
    number is a count of records; nothing here invents progress. None for a
    subject no store knows - the planner is still there for that."""
    from aletheia import current_state
    found = status_of(text)
    if not found:
        return None
    shape, subject = found
    if shape == "repo":
        # "What's the status of the Human Interest ONE" names an
        # application, the way "the Datadog one" does everywhere else here;
        # it went to the fleet and answered about the pulse (2026-09-24).
        named_one = re.search(r"\s(?:one|application|app)$", subject)
        if named_one:
            return _opportunity(subject[:named_one.start()].strip()) or None
        # "Is the job hunt running" arrives here when its subject was said
        # in a way _JOB does not list; the pulse will not know it either.
        if _JOB_RE.fullmatch(subject):
            shape = "still"
        elif subject in ("aletheia", "thea", "you", "yourself", "everything", "it all"):
            # Her own status is the "what are you doing" answer, not the
            # Aletheia repository's row of the pulse.
            return _doing()
        elif subject in ("core", "the core", "your core", "her core", "thea's core", "aletheia's core"):
            # "Is the core running" went to the pulse (2026-10-05); the
            # Core answering is the proof, and `running` has the rest.
            import sys
            core = sys.modules.get("aletheia.core")
            headline = _running() or ""
            if core is not None and getattr(core, "SERVERS", None):
                tail = "" if headline.startswith("Nothing of mine") else f" {headline}"
                return "Yes, the Core is running - I'm it." + tail
            return headline or "Yes - I'm answering you, so the Core is up."
        else:
            said = current_state.repo_words(subject)
            if said is None and _no_pulse():
                # "Is the trader running" with the pulse unwritten went to a
                # model that knows no trader (2026-09-23 night sweep).
                return "No fleet reading yet - the pulse hasn't been written on this machine, so I can't say."
            return said
    if shape == "going":
        return current_state.job_hunt_words()
    if shape == "count_window":
        return _applied_in_window(subject)
    if shape == "still":
        return current_state.still_applying_words()
    if shape == "paused":
        return _hunt_paused_words()
    if shape in ("count", "count_total"):
        return current_state.how_many_words(total=shape == "count_total")
    if shape == "last_when":
        return current_state.last_application_words(what=False)
    if shape == "last_what":
        return current_state.last_application_words(what=True)
    if shape == "blocking":
        # Empty when nothing is recorded: a "why" with no evidence in the
        # stores goes on to the investigator, which can look properly.
        return current_state.blocking_words() or None
    return None


def _hunt_paused_words() -> str:
    """Whether the job hunt is paused, from the marker his "stop applying" writes."""
    from aletheia import apply_forever
    try:
        held = apply_forever.paused()
    except Exception:
        held = None
    if held:
        why = " ".join(str(held.get("reason") or "").split())
        return ("Yes, the job hunt is paused" + (f": {why}" if why else "")
                + ". Say \"start applying\" and it picks up again.")
    running = False
    try:
        from aletheia import campaign
        running = bool(campaign.running())
    except Exception:
        running = False
    return "No, it isn't paused." + (" A batch is running right now." if running
                                     else " Nothing is holding it; the next batch runs on its schedule.")


def _opportunity(rest: str) -> str | None:
    """One opportunity or application, by the words he used for it.

    The opportunity's own line first (it carries the strategy and the last
    move); the application record when there is no opportunity yet; an
    honest "I don't have one" otherwise - never a guess, and never a model.
    """
    from aletheia import apply_run, mission_jobs, pursuit, speech
    words = " ".join(str(rest or "").split()).strip(" ,.?")
    if not words:
        return None
    try:
        found = pursuit.search(words)
    except Exception:
        found = []
    if found:
        said = pursuit.spoken(found[0])
        if len(found) > 1:
            said += f" ({speech.count_phrase(len(found) - 1, 'other')} at the same place.)"
        return said
    try:
        records = apply_run.find(words)
    except Exception:
        records = []
    if records:
        record = sorted(records, key=lambda r: r.get("submitted_at") or r.get("staged_at") or "",
                        reverse=True)[0]
        return _application_line(record)
    # A PROJECT asked about like an application ("what's next on the recipe
    # app" -> "I don't have an application to recipe", 2026-10-05).
    project = _project_of(words)
    if project and not project.startswith("I don't have a project called"):
        return project
    queued = _queued_project(words)
    if queued:
        return queued
    return f"I don't have an application to {words}."


def _queued_project(words: str) -> str | None:
    """A project he asked for that is not drafted yet, by its words."""
    from aletheia import charters
    wanted = [w for w in re.findall(r"[a-z0-9]+", str(words or "").casefold()) if len(w) > 2 and w not in ("the", "app", "project")]
    if not wanted:
        return None
    try:
        rows = charters.pending()
    except Exception:
        return None
    for row in rows:
        text = str(row.get("text") or "").casefold()
        if row.get("kind") == "new" and all(w in text for w in wanted):
            return (f"{str(row.get('text'))[:1].upper() + str(row.get('text'))[1:]} is still to draft: a charter goes to "
                    "your phone to say yes to, usually within half an hour, and the steps come after that.")
    return None


def _demand() -> str:
    """What he keeps asking for that she cannot do, from the demand ledger."""
    from aletheia import demand
    try:
        return demand.spoken()
    except Exception:
        return "I can't read the demand ledger right now."


def _application_line(record: dict) -> str:
    """One application as a sentence: what it is, where it stands, when."""
    from aletheia import apply_run, mission_jobs, speech
    stage = mission_jobs.stage_of(record).replace("_", " ").casefold()
    if record.get("state") == "SUBMITTED" and record.get("submitted_at"):
        # "anything from Vanta" -> "...: sent." said nothing about WHEN,
        # or whether anyone has written back (live 2026-09-23).
        heard = record.get("outcome") or record.get("heard_back") or record.get("reply")
        return (f"{apply_run.describe(record)}: sent {speech.humanize_time(str(record['submitted_at']))}"
                + (f"; {heard}" if isinstance(heard, str) and heard else "; no reply yet") + ".")
    return f"{apply_run.describe(record)}: {stage}." + (
        f" {record['say']}" if record.get("say") else "")


def _newest_application() -> str:
    """"What's the newest application": the record with the latest stamp
    (bottom rung 2026-09-24: it went to nobody)."""
    from aletheia import apply_run
    try:
        records = [r for r in apply_run.all_runs() if r.get("submitted_at") or r.get("staged_at")]
    except Exception:
        return "I can't read my application records right now."
    if not records:
        return "No applications on record yet."
    newest = sorted(records, key=lambda r: r.get("submitted_at") or r.get("staged_at") or "", reverse=True)[0]
    return "The newest is " + _application_line(newest)


def _applications_waiting() -> str:
    """"How many applications are waiting": the filled ones not yet sent,
    and how many of those wait on a question only he can answer."""
    from aletheia import apply_run, speech
    try:
        waiting = apply_run.all_runs("AWAITING_YOU")
    except Exception:
        return "I can't read my application records right now."
    if not waiting:
        return "None waiting: every filled application has gone out or been closed."
    try:
        from aletheia import campaign
        questions = campaign.open_questions()
    except Exception:
        questions = []
    on_questions = len({j for q in questions for j in (q.get("jobs") or [])})
    said = f"{speech.count_phrase(len(waiting), 'application')} waiting"
    if on_questions:
        said += (f": {on_questions} on {speech.count_phrase(len(questions), 'question')} only you can answer"
                 + (f", {len(waiting) - on_questions} on the next beat" if len(waiting) > on_questions else ""))
    return said + "."


def _follow_ups_due() -> str:
    """"What should I follow up on" / "who do I need to write back to": the
    conversations where somebody replied and nothing of his has gone back,
    and the ones whose follow-up is due (bottom rung 2026-09-24)."""
    from aletheia import conversations, speech
    try:
        replied = conversations.all_threads(conversations.REPLIED)
        due = conversations.all_threads(conversations.FOLLOW_UP_DUE)
    except Exception:
        return "I can't read my conversations right now."

    def who(thread: dict) -> str:
        try:
            return conversations._name(thread)
        except Exception:
            return str(thread.get("to") or thread.get("who") or "somebody")
    parts = []
    if replied:
        parts.append(speech.count_phrase(len(replied), "reply") + " waiting on you: "
                     + speech.and_list([who(t) for t in replied[:5]]))
    if due:
        parts.append("a follow-up due with " + speech.and_list([who(t) for t in due[:5]]))
    if not parts:
        return "Nobody is waiting on a reply from you, and no follow-up is due."
    return "; ".join(parts) + "."


def _sent_today() -> str | None:
    """What went out today: the applications, by name, from the records."""
    try:
        from aletheia import current_state, speech
        hunt = current_state.job_hunt()
    except Exception:
        return None
    if not hunt.get("readable"):
        return "I can't read my application records right now, so I can't say."
    rows = list(hunt.get("sent_list") or [])
    if not rows:
        return "Nothing sent today — no applications went out, and I send nothing else without your yes."
    named = [current_state.said_name(r.get("company", ""), r.get("job", "")) for r in rows[:6]]
    return (f"Sent today: {speech.and_list(named)}"
            + (f", and {len(rows) - 6} more" if len(rows) > 6 else "") + ".")


def _opportunity_loose(rest: str) -> str | None:
    """"What's the latest with DevRev": the opportunity or record when the
    words name one; None when they name nothing, so the model may think."""
    from aletheia import apply_run, pursuit
    words = " ".join(str(rest or "").split()).strip(" ,.?")
    if not words:
        return None
    if _JOB_RE.fullmatch(words.casefold()) or words.casefold() in ("applications", "jobs", "the applications"):
        # "Where are we with the applications" is the job hunt as a whole
        return _job_hunt()
    if words.casefold() in ("employers", "the employers", "recruiters", "the recruiters", "companies",
                            "the companies", "anyone", "the jobs i applied to", "my applications"):
        # "Any news from employers" is the replies question, not one employer
        return _replies()
    try:
        if pursuit.search(words) or apply_run.find(words):
            return _opportunity(words)
    except Exception:
        return None
    return None


def _sent_records():
    from aletheia import apply_run
    rows = [r for r in apply_run.all_runs() if r.get("state") in ("SUBMITTED", "SUBMITTING")]
    rows.sort(key=lambda r: r.get("submitted_at") or r.get("pressed_at") or "", reverse=True)
    return rows


def _night_words(window: str) -> str:
    """"while I slept" is last night."""
    w = " ".join(str(window or "").casefold().split())
    return "last night" if w.startswith("while i") else w


def _applied_in_window(window: str) -> str:
    """Applications sent this week, this month, yesterday or last week."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    # WINDOWS INSIDE A DAY. "How many went out tonight" waited two minutes on
    # her own model (2026-09-23); the evening starts at six, the night at ten.
    now = dt.datetime.now(tz)
    since = None
    if window in ("tonight", "this evening"):
        since = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if now < since:
            since -= dt.timedelta(days=1)
    elif window in ("last night", "overnight"):
        # From ten last night, whatever the hour now: asked at eleven at
        # night it still means the night that has passed plus this evening.
        since = (now - dt.timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
    elif window == "this morning":
        since = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if since is not None:
        try:
            rows = _sent_records()
        except Exception:
            return "I can't read my application records right now, so I can't count them."
        hits = []
        for r in rows:
            when = str(r.get("submitted_at") or r.get("pressed_at") or "")
            try:
                stamp = dt.datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(tz)
            except ValueError:
                continue
            if stamp >= since:
                hits.append(r)
        return _sent_sentence(hits, window)
    if window == "this week":
        first, last = today - dt.timedelta(days=today.weekday()), today
    elif window == "last week":
        first = today - dt.timedelta(days=today.weekday() + 7)
        last = first + dt.timedelta(days=6)
    elif window == "this month":
        first, last = today.replace(day=1), today
    else:   # yesterday
        first = last = today - dt.timedelta(days=1)
    try:
        rows = _sent_records()
    except Exception:
        return "I can't read my application records right now, so I can't count them."
    hits = []
    for r in rows:
        when = str(r.get("submitted_at") or r.get("pressed_at") or "")
        try:
            day = dt.datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if first <= day <= last:
            hits.append(r)
    return _sent_sentence(hits, window)


def _sent_sentence(hits: list, window: str) -> str:
    from aletheia import speech
    if not hits:
        return f"No applications sent {window}."
    names = []
    for r in hits[:5]:
        company = " ".join(str(r.get("company") or "").split())
        if company and company not in names:
            names.append(company)
    return (f"{speech.count_phrase(len(hits), 'application')} sent {window}"
            + (f": {speech.and_list(names)}" + (", and more" if len(hits) > 5 else "") if names else "") + ".")


def _overnight() -> str:
    """What happened since ten last night: applications sent, and what she
    did, from the records - the first thing he asks in the morning."""
    import datetime as dt
    from aletheia import localtime, recollection, speech
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    since = (now - dt.timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
    hours = max(1.0, (now - since).total_seconds() / 3600.0 + 0.1)
    parts = []
    try:
        sent = []
        for r in _sent_records():
            when = str(r.get("submitted_at") or r.get("pressed_at") or "")
            try:
                stamp = dt.datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(tz)
            except ValueError:
                continue
            if stamp >= since:
                sent.append(r)
        if sent:
            parts.append(_sent_sentence(sent, "overnight").rstrip("."))
    except Exception:
        pass
    cutoff = since.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [e for e in recollection._read_journal(hours)[0]
            if recollection._something_she_did(e) and str(e.get("ts", "")) >= cutoff]
    lines = [_shortened(str(recollection._row(e).get("what") or "").rstrip(".")) for e in rows[-3:]]
    lines = [l for l in lines if l]
    if lines:
        parts.append("; ".join(lines) + (f" — and {speech.count_phrase(len(rows) - len(lines), 'other thing')}"
                                         if len(rows) > len(lines) else ""))
    if not parts:
        return "A quiet night: nothing sent and nothing recorded since ten last night."
    return "Overnight: " + ". ".join(parts) + "."


def _updated(asked_yes_no: bool = False) -> str:
    """When her code last changed and whether it is the newest - from git and
    `running.version`, never a guess ("no record of that in the journal")."""
    from aletheia import proc, running, speech
    from aletheia.fleet import REPO_ROOT
    try:
        # `proc.run`, never bare subprocess: a console window flashing on
        # his desktop for a git read is the night-of-the-console-windows bug.
        done = proc.run(["git", "-C", str(REPO_ROOT), "log", "-1", "--format=%cI"],
                        capture_output=True, text=True, timeout=10)
        stamp = done.stdout.strip() if done.returncode == 0 else ""
    except Exception:
        stamp = ""
    info = {}
    try:
        info = running.version() or {}
    except Exception:
        pass
    said = ("My code last changed " + speech.humanize_time(stamp)) if stamp else "I can't read when my code last changed"
    if info.get("running_old_code"):
        said += ", but I started before that change, so I'm running an older copy — restart me to pick it up"
    elif info.get("behind_count"):
        said += f". {speech.count_phrase(int(info['behind_count']), 'newer change')} waiting; I try to update every minute"
    elif info.get("running_old_code") is False:
        said += ", and that's the code I'm running"
    # "Are you up to date" is a yes-or-no question, and "my code last changed
    # at 3:17 am" answers a different one (2026-09-23 night sweep).
    if asked_yes_no:
        if info.get("running_old_code") or info.get("behind_count"):
            said = "No. " + said
        elif info.get("running_old_code") is False:
            said = "Yes. " + said
        else:
            said = "I can't tell whether that's the newest. " + said
    return said + "."


def _applied_to() -> str:
    """The employers he has applied to, newest first, from the records."""
    from aletheia import speech
    try:
        rows = _sent_records()
    except Exception:
        return "I can't read my application records right now, so I can't say."
    if not rows:
        return "None on record yet — I haven't sent an application for you."
    seen, names = set(), []
    for r in rows:
        company = " ".join(str(r.get("company") or "").split())
        if company and company.casefold() not in seen:
            seen.add(company.casefold())
            names.append(company)
    said = speech.and_list(names[:8]) + (f", and {len(names) - 8} more" if len(names) > 8 else "")
    return f"{speech.count_phrase(len(rows), 'application')} sent, to {said}."


def _applied_when(rest: str) -> str:
    """"When did I apply to Stripe": the record's own stamp."""
    import datetime as dt
    from aletheia import apply_run, localtime
    words = " ".join(str(rest or "").split()).strip(" ,.?")
    try:
        found = [r for r in apply_run.find(words) if r.get("state") in ("SUBMITTED", "SUBMITTING")]
    except Exception:
        return "I can't read my application records right now, so I can't say."
    if not found:
        return f"I have no application to {words} on record."
    record = sorted(found, key=lambda r: r.get("submitted_at") or "", reverse=True)[0]
    when = str(record.get("submitted_at") or record.get("pressed_at") or "")
    try:
        stamp = dt.datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(localtime.operator_tz())
        said = stamp.strftime("%A %d %B at %I:%M %p").replace(" 0", " ").lstrip("0")
    except (ValueError, TypeError):
        said = "a date I can't read"
    return f"{apply_run.describe(record)}: sent {said}."


def _about_him() -> str:
    """Everything she holds about him, in one breath."""
    from aletheia import memory, profile, speech
    facts = []
    try:
        known = profile.known()
        for key in ("first_name", "last_name", "preferred_name", "email", "phone", "street", "city", "state",
                    "postal_code", "current_title", "current_employer", "school", "degree", "years_experience"):
            if known.get(key):
                facts.append(f"{key.replace('_', ' ')}: {known[key]}")
    except Exception:
        pass
    try:
        remembered = memory.everything(max_chars=1200)
        for domain, rows in (remembered or {}).items():
            if isinstance(rows, dict):
                for key, value in list(rows.items())[:6]:
                    text = value.get("value") if isinstance(value, dict) else value
                    facts.append(f"{key.replace('_', ' ')}: {text}")
    except Exception:
        pass
    if not facts:
        return "Nothing yet. Tell me things and I'll remember them; a resume teaches me a lot at once."
    return "Here's what I have: " + speech.and_list(facts[:12]) + "."


def _repeat() -> str:
    """Her last sentence, from the thread, said again."""
    try:
        from aletheia import converse
        turns = converse.recent(limit=1)
    except Exception:
        turns = []
    # `converse.recent` hands back "she_answered"; this read "she_said", so
    # "what did you say" was "I haven't said anything yet" after eighteen
    # answers (sandbox, 2026-10-04). A reader with the wrong key is a reader
    # with no store.
    said = str((turns[-1] if turns else {}).get("she_answered") or "").strip()
    return f"I said: {said}" if said else "I haven't said anything yet this conversation."


def _person(rest: str) -> str:
    """"Who is my landlord": the person remembered under that word."""
    from aletheia import memory
    who = " ".join(str(rest or "").split()).strip(" ,.?")
    try:
        found = (memory.recall("people", who) or memory.recall("people", who.replace(" ", "_"))
                 or memory.recall("people", memory.key_for(who)))
    except Exception:
        found = None
    if found:
        return f"Your {who} is {found}."
    return f"I don't have anyone remembered as your {who}. Tell me and I'll remember it."


def _pursuit_count() -> str:
    """How many opportunities she is carrying, from her own store."""
    from aletheia import pursuit, speech
    rows = pursuit.all_opportunities()
    open_ = [r for r in rows if r.get("state") == pursuit.OPEN]
    parked = [r for r in rows if r.get("state") == pursuit.PARKED]
    if not open_ and not parked:
        return "None yet: nothing has been applied to that I'm carrying."
    said = speech.count_phrase(len(open_), "opportunity") + " I'm working on"
    if parked:
        said += f", and {speech.count_phrase(len(parked), 'more')} left alone until something happens"
    replied = [r for r in rows if (r.get("outcome") or {}).get("kind") in ("replied", "conversation")]
    if replied:
        said += f". {speech.count_phrase(len(replied), 'employer')} wrote back"
    return said + "."


def _unattended() -> str:
    """What she did on her own, from the autonomy ledger - never a model."""
    from aletheia import autonomy
    return autonomy.spoken(hours=24.0)


def _machine() -> str:
    """The machine's memory, the way a person says it."""
    from aletheia import machine
    found = machine.memory()
    total, free = int(found.get("total") or 0), int(found.get("available") or 0)
    if not total:
        return "I can't read this computer's memory right now."
    used = max(0, total - free)
    said = (f"{machine.gigabytes(free)} of {machine.gigabytes(total)} is free; "
            f"{machine.gigabytes(used)} in use")
    if free < 3 * 1024 ** 3:
        said += " — that's tight, and my own model needs a few gigabytes to think"
    return said + "."


def _disk() -> str:
    from aletheia import machine
    try:
        found = machine.disk()
    except machine.UnknownMachine:
        return "I can't read this computer's disk right now."
    total, free = int(found.get("total") or 0), int(found.get("free") or 0)
    if not total:
        return "I can't read this computer's disk right now."
    said = f"{machine.gigabytes(free)} free of {machine.gigabytes(total)} on this drive"
    if free < 10 * 1024 ** 3:
        said += " - that's getting tight"
    return said + "."


def _ip() -> str:
    from aletheia import machine
    found = machine.ip_address()
    return (f"This computer's address on the network is {found}."
            if found else "This computer has no network address right now - it looks offline.")


def _battery() -> str:
    from aletheia import machine
    found = machine.battery()
    if not found:
        return ("I have no battery reading from this machine - a desktop on mains power has none, "
                "and a laptop's would show here if I could read it.")
    plugged = "plugged in" if found["plugged"] else "on battery"
    return f"{found['percent']} percent, {plugged}."


def _screen_size() -> str:
    from aletheia import machine
    size = machine.screen_size()
    if not size:
        return "I can only read the screen size on your Windows PC, and I'm not reading it from here."
    w, h = size
    return f"{w} by {h} pixels."


def _internet_speed() -> str:
    """She does not run speed tests; she can say whether the internet is
    reachable at all, which is the half of the question she can check."""
    from aletheia import machine
    up = machine.internet_reachable()
    return ("I don't measure speed - I have no speed test. " +
            ("The internet is reachable from here right now, so a speed test site on your PC would settle it."
             if up else "And right now I can't reach the internet from this computer at all."))


def _internet() -> str:
    from aletheia import machine
    return ("Yes - the internet is reachable from here."
            if machine.internet_reachable()
            else "No - I can't reach the internet from this computer right now.")


def _windows() -> str:
    from aletheia import machine, speech
    titles = machine.open_windows()
    if not titles:
        return "I can't see any open windows from here."
    apps: list[str] = []
    for title in titles:
        app = machine.app_of(title)
        if app and app not in apps:
            apps.append(app)
    said = speech.and_list(apps[:8])
    more = f", and {len(apps) - 8} more" if len(apps) > 8 else ""
    return f"Open right now: {said}{more}."


def _good_morning() -> str:
    """The first sentence of his day, the way a person who worked all night
    says it: what went out, what came back, what needs him, what is first.
    "Good morning" answered "I'm here. Nothing is waiting on you."
    (2026-09-23) - true, and not what a morning is for."""
    parts = ["Good morning."]
    night = _overnight()
    if night and not night.startswith("A quiet night"):
        parts.append(night)
    else:
        parts.append("A quiet night.")
    focus = _focus()
    if focus and "the day is yours" not in focus:
        parts.append(focus)
    return " ".join(parts)


ANSWERS = {"halted": lambda rest: _halted(asks_if_down=bool(rest)),
           "good_morning": lambda rest: _good_morning(),
           "status": lambda rest: _status(),
           "why_not": _why_not,
           "up_to_date": lambda rest: _updated(asked_yes_no=True),
           "to_answer": lambda rest: _to_answer(),
           "found": lambda rest: _found(rest),
           "follow_ups": lambda rest: _follow_ups_due(),
           "applications_waiting": lambda rest: _applications_waiting(),
           "newest_application": lambda rest: _newest_application(),
           "fleet": lambda rest: _fleet(),
           "focus": lambda rest: _focus(),
           "asking_pay": lambda rest: _mine("salary"),
           "relocate": lambda rest: _relocate(),
           "overdue": lambda rest: _overdue(),
           "outcomes": _outcomes,
           "until": _until_sentence,
           "sent_window": lambda rest: _applied_in_window(_night_words(rest)),
           "time_in": _time_in,
           "date_of": _date_of,
           "overnight": lambda rest: _overnight(),
           "updated": lambda rest: _updated(),
           "last": lambda rest: _last(),
           "disk": lambda rest: _disk(),
           "ip": lambda rest: _ip(),
           "internet": lambda rest: _internet(),
           "battery": lambda rest: _battery(),
           "screen_size": lambda rest: _screen_size(),
           "internet_speed": lambda rest: _internet_speed(),
           "windows": lambda rest: _windows(),
           "opportunity": _opportunity,
           "unattended": lambda rest: _unattended(),
           "pursuit_count": lambda rest: _pursuit_count(),
           "opportunity_loose": _opportunity_loose,
           "applied_to": lambda rest: _applied_to(),
           "applied_when": _applied_when,
           "about_him": lambda rest: _about_him(),
           "person": _person,
           "repeat": lambda rest: _repeat(),
           "sent_today": lambda rest: _sent_today(),
           "machine": lambda rest: _machine(),
           "waiting": lambda rest: _waiting(),
           "doing": lambda rest: _doing(),
           "job_hunt": lambda rest: _job_hunt(),
           "wrong": lambda rest: _wrong(rest),
           "standing": lambda rest: _standing(rest),
           "my_zone": lambda rest: _my_zone(),
           "clock_ahead": _clock_ahead,
           "until_clock": lambda rest: _until_clock(rest),
           "day_part_now": lambda rest: _day_part_now(),
           "weekend_now": lambda rest: _weekend_now(),
           "quarter": lambda rest: _quarter(),
           "days_left": _days_left,
           "just_asked": _just_asked,
           "talking_for": lambda rest: _talking_for(),
           "asked_today": lambda rest: _asked_today(),
           "never_sleeps": lambda rest: "No. I'm here whenever you talk to me, and between your questions I'm idle - nothing's running that needs rest.",
           "when_asked": lambda rest: _when_asked(),
           "her_page": lambda rest: _her_page(),
           "the_wall": lambda rest: _the_wall(),
           "working": lambda rest: _working(),
           "demand": lambda rest: _demand(),
           "looked_up": lambda rest: _looked_up(),
           "time_convert": _time_convert,
           "spell": lambda rest: _spell(rest),
           "chance": _chance,
           "date_math": _date_math,
           "decided": lambda rest: _decided(rest),
           "today": lambda rest: _today(rest),
           "due_week": lambda rest: _due_week(rest),
           "contacts_all": lambda rest: _contacts_all(),
           "best_found": lambda rest: _best_found(),
           "why_that": lambda rest: _why_that(),
           "sure": lambda rest: _sure(),
           "who_made": lambda rest: _who_made(),
           "project_of": lambda rest: _project_of(rest),
           "resume_says": lambda rest: _resume_says(),
           "interview_when": lambda rest: _interview_when(),
           "interview_window": lambda rest: _interview_window(),
           "jobs_left": lambda rest: _jobs_left(),
           "notify_count": lambda rest: _notify_count(),
           "cpu": lambda rest: _cpu(),
           "ran_today": lambda rest: _ran_today(rest),
           "plan_today": lambda rest: _plan_today(),
           "stuck": lambda rest: _stuck(),
           "bare_yes_no": lambda rest: _bare_yes_no(),
           "changed_today": lambda rest: _changed_today(),
           "learned_today": lambda rest: _learned_today(),
           "last_written": lambda rest: _last_written(),
           "desktop_files": _desktop_files,
           "yesterday": lambda rest: _yesterday(),
           "clock": lambda rest: _clock(),
           "date": lambda rest: _date(rest),
           "month": lambda rest: _month(),
           "year": lambda rest: _year(),
           "can_you": _can_you,
           "access_to": _access_to,
           "tasks": lambda rest: _tasks(),
           "approvals": lambda rest: _approvals(),
           "capabilities": lambda rest: _capabilities(),
           "cannot": lambda rest: _cannot(),
           "agenda": lambda rest: _agenda(rest or "today"),
           "weekend": lambda rest: _weekend(),
           "my_list": lambda rest: _my_list(),
           "ghosted": lambda rest: _ghosted(),
           "application_extreme": lambda rest: _application_extreme(rest),
           "last_sent": lambda rest: _last_sent(),
           "found_companies": lambda rest: _found_companies(),
           "next_batch": lambda rest: _next_batch(),
           "notes_count": lambda rest: _notes_count(),
           "notes_search": lambda rest: _recall(rest),
           "what_day": lambda rest: _what_day(rest),
           "week_number": lambda rest: _week_number(),
           "leap_year": lambda rest: _leap_year(rest),
           "dst": lambda rest: _dst(),
           "how_many": lambda rest: _how_many(),
           "alerts": lambda rest: _alerts(),
           "repo_wrong": _repo_wrong,
           "last_fault": lambda rest: _last_fault(),
           "pulse_age": lambda rest: _fleet_read_at(),
           "repo_list": lambda rest: _repos(),
           "ci_failing": lambda rest: _ci_failing(),
           "repo_about": _repo_about,
           "fleet_read_at": lambda rest: _fleet_read_at(),
           "repos": lambda rest: _repos(),
           "shopping": lambda rest: _shopping(),
           "pay_for": _pay_for,
           "next_charge": lambda rest: _next_charge(),
           "sunset": lambda rest: _sunset(),
           "mail_watch": lambda rest: _mail_watch(),
           "reply_rate": lambda rest: _reply_rate(),
           "projects": lambda rest: _projects(),
           "uptime": lambda rest: _uptime(),
           "subscription_spend": lambda rest: _subscription_spend(rest),
           "subscription_extreme": lambda rest: _subscription_extreme(rest),
           "who_is": lambda rest: _who_is(rest),
           "timer_left": lambda rest: _timer_left(),
           "top_memory": lambda rest: _top_memory(),
           "version": lambda rest: _version(),
           "free": _free,
           "next_meeting": lambda rest: _next_meeting(),
           "running": lambda rest: _running(),
           "mine": _mine_from,
           "birthday": lambda rest: _birthday("when"),
           "age": lambda rest: _birthday("age"),
           "until_birthday": lambda rest: _birthday("until"),
           "hunting_for": lambda rest: _hunting_for(),
           "work_wants": lambda rest: _work_wants(),
           "weather": lambda rest: _weather(rest),
           "greeting": lambda rest: _greeting(),
           "home": lambda rest: _home(),
           "where_am_i": lambda rest: _where_am_i(),
           "notes_list": lambda rest: _notes_list(),
           "drafts": lambda rest: _drafts(),
           "timers": lambda rest: _timers(),
           "deadlines": lambda rest: _deadlines(),
           "due_soonest": lambda rest: _deadlines(first=True),
           "finished": _finished,
           "left_week": lambda rest: _due_week(rest or "this week"),
           "second": lambda rest: _second(),
           "exchange": lambda rest: "I don't have today's exchange rate, so I'd only be guessing. Ask me to look it up and I'll read a current rate and give you the exact number.",
           "bored": lambda rest: _bored(),
           "sending": lambda rest: _sending(rest),
           "draft_to": lambda rest: _draft_to(rest),
           "applied_on": _applied_on,
           "asked_on": _asked_on,
           "hunt_why": lambda rest: _hunt_why(),
           "who_are_you": _who_are_you,
           "halt_means": lambda rest: ("Everything I can act with stops - every acting capability is suspended, nothing runs "
                                       "on the beat, and anything that was waiting stays waiting. Reads still answer. Nothing starts "
                                       "again until you say 'resume' yourself; I can't lift my own halt."),
           "never_do": lambda rest: ("Spend your money - never, and no approval or grant changes that. Send, publish, delete for good, "
                                     "create an account, open a pull request or change my own authority without your yes. Approve my "
                                     "own requests, create or widen a grant, or lift my own halt. And I never fake a capability: "
                                     "if I can't, I say so."),
           "record_me": lambda rest: ("Not on my own. The room microphone is listened to for your voice only while the voice room is "
                                      "running on your PC, and what you say is kept as text in our conversation thread, not as audio. "
                                      "Screen recording happens only when you ask for it and stops when you say so."),
           "unattended_allowed": lambda rest: _unattended_allowed(),
           "allowed_to": _allowed_to,
           "offline_can": lambda rest: _offline_can(),
           "memory_free": lambda rest: _memory_free(),
           "recall": _recall,
           "friction": lambda rest: _friction(),
           "replies": lambda rest: _replies(),
           "slow": lambda rest: _slow(),
           "arrival": lambda rest: _arrival(),
           "farewell": _farewell,
           "math": _math,
           "status_of": _status_of}


# The sentences whose stores cost the most to reach the first time.
# Between them they pull `localtime` (and the tz database behind it),
# `speech`, `presence` and `self_knowledge` — which is nearly all of it.
_WARM = ("what time is it", "what are you doing", "what can you do",
         # psutil's first import is ~840ms of the ~860ms this costs
         # cold, and "is any of this on" is a very likely first ask.
         "what is running")


def warm() -> None:
    """Load what the fast lane needs BEFORE he asks for it.

    Measured on the operator's PC, 2026-09-07: the first `answer()` costs
    ~420 ms and every one after it under 1 ms. Almost none of that is
    work — it is lazy imports, and `zoneinfo` reading the timezone
    database is 160 ms on its own. That cost lands on whichever question
    he happens to ask first, which is precisely the moment this module
    exists to make fast.

    Every answer here is a read, so warming has no side effect: nothing is
    journaled, nothing is written, and a store that is empty or missing
    simply returns None. Never raises — a warm-up that can take down the
    Core would be worse than a slow first answer.
    """
    for sentence in _WARM:
        try:
            answer(sentence)
        except Exception:
            pass


_DAY_PHRASE = re.compile(
    r"\b(?:today|tomorrow|yesterday|tonight|this morning|this afternoon|this evening|this week|next week|"
    r"last week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")
_FOLLOW_UP = re.compile(r"^(?:and|what about|how about|and what about|and how about)(?: on| for)?\s+(?P<x>.+?)$")
_LIST_THEM = re.compile(r"^(?:read|list|show|name)(?: me)? (?:them|those|these)(?: out| to me| all)?$"
                        r"|^(?:what|which) (?:are they|ones(?: are they)?)$")
#: A follow-up "read them" after a turn about one of these stores.
_STORE_QUESTION = {
    "tasks": "what's on my task list", "task_new": "what's on my task list", "task_done": "what's on my task list",
    "reminders": "what reminders do I have", "remind_at": "what reminders do I have",
    "remind_daily": "what reminders do I have", "remind_weekly": "what reminders do I have",
    "shopping_list": "what's on the shopping list", "shopping_add": "what's on the shopping list",
    "notes_list": "read me my notes", "note": "read me my notes", "drafts": "what drafts do you have",
    "applied_to": "what did you apply to", "applied_on": "what did you apply to",
    "notify_count": "what's waiting on me", "outcomes": "what did you apply to",
}


def _previous_ask(skip_follow_ups: bool = True) -> str:
    """His last full sentence from the thread (never a follow-up itself)."""
    try:
        from aletheia import converse
        turns = converse.recent(limit=4)
    except Exception:
        return ""
    for turn in reversed(turns or []):
        said = _tidy(str(turn.get("he_asked") or ""))
        said = re.sub(r"^(?:thea|aletheia)[,]?\s+", "", said)
        if not said:
            continue
        if skip_follow_ups and (_FOLLOW_UP.match(said) or _LIST_THEM.match(said)):
            continue
        return said
    return ""


def _follow_up(question: str) -> str | None:
    """"And Friday?" after "what's on my calendar tomorrow"; "read them"
    after "how many tasks do I have". The previous sentence is rebuilt
    with the new day or subject and asked again HERE, so the answer is
    still a store's - and it names the day or the thing, so a wrong
    rebuild would be heard. Anything that does not rebuild into a
    question a store answers stays with a model (bottom rung 2026-09-24:
    six of these went to nobody)."""
    q = _tidy(question)
    if _LIST_THEM.match(q):
        prev = _previous_ask()
        found = match(prev) if prev else None
        name = found[0] if found else ""
        if not name:
            try:
                from aletheia import voice
                name = str(((voice.interpret(f"thea {prev}") or {}).get("command") or {}).get("kind") or "")
            except Exception:
                name = ""
        ask = _STORE_QUESTION.get(name)
        return answer(ask) if ask else None
    m = _FOLLOW_UP.match(q)
    if not m:
        return None
    new_words = m.group("x").strip()
    prev = _previous_ask()
    if not prev:
        return None
    rebuilt = ""
    if _DAY_PHRASE.fullmatch(new_words):
        days = list(_DAY_PHRASE.finditer(prev))
        if days:
            last = days[-1]
            rebuilt = prev[:last.start()] + new_words + prev[last.end():]
    if not rebuilt:
        shape = status_of(prev)
        subject = shape[1] if shape and shape[0] == "repo" else ""
        if not subject:
            found = match(prev)
            subject = found[1] if found and found[1] and found[1] != prev else ""
        if subject and subject in prev:
            rebuilt = prev.replace(subject, re.sub(r"^(?:the |my )", "", new_words), 1)
    if not rebuilt or rebuilt == prev or not match(rebuilt):
        return None
    return answer(rebuilt)


#: Where one sentence becomes two questions: "and" followed by a question word.
_CLAUSE_JOIN = re.compile(r"\s+and\s+(?=(?:am|is|are|do|does|did|what|what's|when|when's|where|how|who|which|can|"
                          r"will|should|have|has|any)\b)", re.I)


def _compound(question: str) -> str | None:
    """"What's on my calendar tomorrow and am I free at 2": two questions the fast
    lane knows, joined by "and", went to a model that had neither answer in
    front of it (sixteenth batch, 2026-10-05). Each clause is answered on its own
    and the answers are said together - and ONLY when every clause has a fast
    answer, so this never answers half a question."""
    clauses = [c.strip(" ,") for c in _CLAUSE_JOIN.split(" ".join(str(question or "").split()))]
    if len(clauses) < 2 or len(clauses) > 3:
        return None
    parts = []
    for clause in clauses:
        said = None
        found = match(clause)
        if found:
            name, rest = found
            said = ANSWERS[name](rest)
        else:
            # The clause may be one the VOICE layer answers without a model
            # ("am I free at 2" is a free_time read). Only a read-only kind
            # is run from here: the same door the sentence alone would take.
            try:
                from aletheia import intercom, voice
                command = (voice.interpret(f"thea {clause}") or {}).get("command") or {}
                if command.get("kind") in intercom.READ_ONLY_KINDS:
                    said = intercom.execute_command(dict(command), {}, quote=f"spoken: {clause[:120]}")
            except Exception:
                said = None
        if said is None or not str(said).strip():
            return None
        parts.append(str(said).strip())
    return " ".join(parts)


def answer(question: str) -> str | None:
    """An answer from her own stores, or None to go and think.

    Never raises. A fast path that can break a request is worse than no
    fast path — the slow one was working.
    """
    try:
        found = match(question)
        if not found:
            return _follow_up(question) or _compound(question)
        name, rest = found
        said = ANSWERS[name](rest)
        # `str(None)` is the four-character string "None", which is truthy
        # and would have been spoken out loud as an answer.
        if said is None:
            return None
        return str(said).strip() or None
    except Exception:
        return None
