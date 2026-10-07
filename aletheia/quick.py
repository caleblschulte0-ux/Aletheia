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
        from aletheia.voice import WAKE_WORDS, _without_preamble
        # "Hey Thea, what time is it" (2026-10-07: to the planner): her name
        # after the filler hid the sentence from every pattern here.
        return re.sub(r"^(?:%s)\b[\s,.!?:;]*" % "|".join(WAKE_WORDS), "", _without_preamble(text))
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
    r"|(?:is|are) (?:she|it|the batch|the run) still (?P<still4>applying|running the job hunt))$"
    # how many
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
    # "What's new with Barkly" (2026-10-07: to the planner) - the same row.
    r"|^what(?:'s| is|s)? (?:new|happening|going on|the latest) (?:with|on|in) (?:the |my )?(?P<repo6>[a-z0-9][a-z0-9 _.-]{1,40}?)"
    r"(?: pipeline| repo| project| bot)?$"
    # "What's Barkly doing" (2026-10-07: to the planner).
    r"|^what(?:'s| is|s) (?:the |my )?(?P<repo7>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)? (?:doing|up to)(?: today| now| right now| lately)?$"
    r"|^why (?:is|are) (?:the |my )?(?P<repo4>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)?"
    r" (?:red|failing|broken|down|unhealthy|not healthy|in trouble)(?: right now| today)?$")

# Each is (name, pattern). Anchored, because "tell me about the halt
# behaviour in the docs" is not "are you halted".
#: A unit after a kitchen quantity; money and rates have their own sums.
_KITCHEN_UNIT = r"(?!dollars?\b|bucks\b|euros?\b|pounds?\b|percent\b)[a-z]{2,12}"
#: A kitchen quantity said out loud: "3/4", "1 1/2", "2 and a half", "a quarter".
_QTY = (r"(?:\d+ (?:and )?\d+/\d+|\d+/\d+|\d+(?:\.\d+)?(?: and (?:a |one )?(?:half|quarter|third|three quarters|two thirds))?"
        r"|(?:a |one )?(?:half|quarter|third))")

PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    # FIRST, before anything else can claim the sentence: a person in
    # crisis must never be filed as a work item "for when the big models
    # are back" (2026-10-07: "I'm sad" was).
    ("crisis", re.compile(
        r"^(?:i|i'm|im|i am) (?:want to|wanna|going to|gonna|am going to|feel like|thinking about|thinking of|"
        r"just want to|really want to) (?:die|dying|kill(?:ing)? myself|end(?:ing)? (?:it all|my life)|hurt(?:ing)? myself|be dead)$"
        r"|^(?:i'm|im|i am|i feel|feeling) (?:suicidal|thinking about suicide)$"
        r"|^i don'?t want to (?:live|be alive|be here) anymore$")),
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
        r"|^(?:is there )?anything i (?:should|need to|ought to) know(?: about)?$"
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
        r"|^(?:catch me up|fill me in|bring me up to speed|where are we)(?: please)?$"
        # "Are we good", "summarize today", "how was your day": the rundown
        # (bottom rung 2026-09-24: a repo lookup for "we", and nobody).
        r"|^(?:are we good|is everything (?:ok|okay|alright|fine|good)|all good|everything good)(?: today)?\s*\??$"
        r"|^(?:summari[sz]e|recap|sum up) (?:today|my day|the day|things)(?: for me)?\s*\??$"
        r"|^how (?:was|did) (?:your|the|my) day(?: go)?\s*\??$")),
    ("focus", re.compile(
        r"^what should i (?:focus on|do|work on|prioriti[sz]e|tackle|start with)(?: today| first| right now| this morning| now| next)?$"
        r"|^(?:plan|organi[sz]e|map out|lay out) my day$|^what(?:'s| is) (?:the )?(?:most important|top priority|priority)"
        r"(?: thing)?(?: today| right now)?$|^what(?:'s| is) on (?:my|the) plate(?: today)?$"
        r"|^what do i need to (?:do|get done)(?: today)?$"
        # "Help me prioritize", "what can I do in 30 minutes" (2026-10-07: to the planner).
        r"|^help me (?:prioriti[sz]e|plan my day|figure out what to do)(?: today)?$"
        r"|^what can i (?:do|get done|knock out) in (?:the next )?(?:\d{1,3}|half an|an|a few) (?:minutes?|hours?|mins?)$")),
    # "How many interviews do I have" / "did I get any rejections" (2026-09-23):
    # outcomes are on the application records.
    ("outcomes", re.compile(
        r"^(?:how many|any|do i have any|did i get any|have i (?:got|gotten|had) any|what) (?P<outcome>interviews?|offers?|"
        r"rejections?)(?: (?:do i have|have i got|so far|yet|lined up|coming up|today|this week))*$"
        r"|^(?:who|which (?:companies|employers|jobs)) (?:(?P<outcome2>rejected) me|(?P<outcome3>turned) me down|"
        r"made (?:me )?an (?P<outcome4>offer)|(?:wants?|asked) (?:to |an |for an )?(?P<outcome5>interview|talk))$"
        # "Did I get an interview" (2026-09-24, offline: "I could not plan that")
        r"|^(?:did|have) i (?:get|got|gotten|land|landed|receive|received) (?:an |any |a )?(?P<outcome6>interviews?|offers?|rejections?)"
        r"(?: yet| today| this week| so far)?\s*\??$")),
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
        r"|^where have i applied(?: so far| this week| today)?$"
        r"|^(?:who|what) have (?:you|u) applied (?:to|for)(?: for me)?(?: so far| this week| today)?$"
        r"|^(?:what|who|where) did (?:you|u|we) apply(?: (?:to|for))?(?: for me)?(?: this week| so far)?$"
        r"|^(?:list|show me|name) (?:the |my )?(?:companies|employers|places) (?:i|you|u|we)(?:'ve| have)? applied to$"
        # "Which companies did you apply to" (2026-10-07: to the planner).
        r"|^(?:what|which) (?:companies|employers|places|jobs) did (?:you|u|we|i) apply (?:to|for)(?: for me)?(?: so far)?$")),
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
    # "What did I just ask you" (2026-10-07: to the planner, and from there
    # "I can't think just now"). The thread holds his words too.
    ("asked_last", re.compile(
        r"^what (?:did|was it) i (?:just )?(?:ask|asked|say|said)(?: (?:you|u))?(?: (?:just now|a second ago|before that|earlier))?$"
        r"|^what was my (?:last )?question$|^what was i (?:just )?(?:asking|saying)$"
        r"|^what was the last thing i (?:asked|said|told)(?: (?:you|u))?$"
        # "What was the first thing I asked you today" (2026-10-07: to a model).
        r"|^what was the (?P<first>first) thing i (?:asked|said|told)(?: (?:you|u))?(?: today| this morning)?$")),
    # "What did we talk about" (2026-10-07: to the planner) - the thread
    # she keeps, read back in his words.
    ("talked_about", re.compile(
        r"^what (?:did|have) we (?:just )?(?:talk(?:ed)? about|discuss(?:ed)?)(?: so far)?$"
        r"|^what were we (?:just )?(?:talking about|discussing)$|^recap (?:our|the|this) conversation$")),
    ("repeat", re.compile(
        r"^(?:say that again|repeat that|come again|what did (?:you|u) just say|what was that|"
        r"sorry,? what|pardon|say again|one more time|i didn'?t (?:catch|hear) that|what did (?:you|u) say"
        # "What was the last thing you said" (2026-10-07: to a model).
        r"|what was the last thing (?:you|u) said|what did (?:you|u) (?:just )?tell me|repeat (?:your|the) last answer"
        r"|say (?:it|that) one more time|can you repeat that|could you repeat that)\??$")),
    # "Who is my landlord" came back from her own model as "no lease or
    # rental info connected here" - a capability she has, denied. The
    # person is remembered or he is asked, in words, never a model's guess.
    # "Who is Dana" (2026-10-07: to the planner) - her contact card and his
    # notes about them. Neither found is NOT "nobody": it may be someone
    # famous, so it goes on to a model.
    ("who_named", re.compile(
        r"^who(?:'s| is) (?!(?:my|the|your|you|u|that|this|it|he|she|they|i|we|on|in|at|calling|there|here|next|"
        r"waiting|running|online)\b)(?P<who_named>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)\s*\??$")),
    ("contacts_count", re.compile(
        r"^how many (?:contacts|people) (?:do i have|have i got|are in my contacts|have i saved|are saved)\s*\??$"
        # "Who are my contacts" (2026-10-07: to a model)
        r"|^(?:who(?:'s| is| are)(?: in)? my contacts|(?:list|show me|read me|read|show) (?:all )?my contacts"
        r"|what contacts do i have|who do i have (?:saved|in my contacts))\s*\??$")),
    ("person", re.compile(
        r"^who(?:'s| is|s)? my (?P<what>landlord|landlady|boss|manager|doctor|dentist|lawyer|accountant|"
        r"realtor|agent|mechanic|plumber|electrician|barber|therapist|trainer|coach|banker|broker|"
        r"sister|brother|mom|mother|dad|father|wife|husband|partner|girlfriend|boyfriend|roommate|"
        r"neighbou?r|best friend|emergency contact|recruiter)\s*\??$")),
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
    # HOW HIS COMPUTER IS, AND HOW HIS WEEK WENT (2026-10-07): "is my
    # computer okay" and "how was my week" went to the planner. The first
    # is three readings she already makes; the second is his finished tasks
    # and her journal since Monday.
    ("computer_ok", re.compile(
        r"^(?:is|how(?:'s| is)) (?:my|the|this) (?:computer|pc|laptop|machine) (?:okay|ok|alright|all right|doing|holding up|healthy|running okay|running ok|running)"
        r"(?: okay| ok| alright)?$|^(?:is )?(?:everything|anything) (?:okay|ok|wrong) with (?:my|the|this) (?:computer|pc|laptop|machine)$"
        r"|^(?:check on|check|how about) (?:my|the|this) (?:computer|pc|laptop|machine)(?:'s health)?$")),
    ("week", re.compile(
        r"^how (?:was|is|has been|'s been|s been) my week(?: been| going| so far)?$"
        r"|^what (?:did|have) (?:you|u|i|we) (?:do|done|get done|been doing|been up to) this week$"
        r"|^what happened this week$|^(?:recap|sum up|summari[sz]e|review) (?:my |the |this )week$|^(?:my )?week in review$")),
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
    # "What's using all my memory" went to the planner (2026-10-07); the OS
    # lists the programs for free. "Why is my pc so slow" is the CPU's.
    ("memory_users", re.compile(
        r"^what(?:'s| is|s)? (?:using|eating|hogging|taking(?: up)?) (?:all |so much |up )?(?:of )?(?:my |the )?(?:memory|ram)"
        r"(?: on (?:this|the|my) (?:computer|machine|pc|laptop))?$"
        r"|^what (?:programs|apps) are using (?:the most |all the |all my )?(?:memory|ram)$")),
    # HIS FINISHED WORK AND HIS TOP TASK (2026-10-07): "what have I done
    # today", "what tasks did I finish", "what's my most important task" and
    # "clear my completed tasks" all went to the planner. The task store
    # holds the answer to every one.
    ("tasks_done", re.compile(
        r"^what (?:have i|did i) (?:done|do|get done|got done|finish(?:ed)?|complete(?:d)?|knock(?:ed)? off|accomplish(?:ed)?|achieve(?:d)?)"
        r"(?P<what> today| yesterday| this week)?$"
        r"|^what (?:tasks|things) (?:have i|did i) (?:finish(?:ed)?|complete(?:d)?|do|done|get done|tick(?:ed)? off)"
        r"(?P<what2> today| yesterday| this week)?$"
        r"|^(?:what(?:'s| is|s)? (?:on )?)?my (?:done|finished|completed) (?:list|tasks)$"
        r"|^(?:which|what) tasks? (?:did|have) i (?:finish|finished|complete|completed|tick off|ticked off)\s*\??$"
        r"|^(?:finished|completed|done) tasks\s*\??$"
        # "How productive was I today" (2026-10-07: to the planner).
        r"|^how productive (?:was i|have i been|am i)(?P<what3> today| yesterday| this week)?\s*\??$")),
    # "How am I doing on my tasks" (2026-10-07: to the planner, then "the
    # big models can't answer"). What got done today and what is left.
    ("task_progress", re.compile(
        r"^how (?:am i|'?m i) doing (?:on|with) (?:my |the )?(?:tasks|task list|to ?do list|to-do list|list)(?: today)?\s*\??$"
        r"|^how(?:'s| is) my (?:task list|to ?do list|to-do list|list) (?:looking|going)(?: today)?\s*\??$"
        r"|^how many tasks (?:have i|did i) (?:done|do|finish(?:ed)?|complete(?:d)?)(?: today)?\s*\??$")),
    ("task_top", re.compile(
        r"^what(?:'s| is|s)? my (?:most important|top|biggest|first|highest priority|number one|main) (?:task|thing|priority)(?: today)?$"
        r"|^what(?:'s| is|s)? my (?:top )?priority(?: today)?$"
        r"|^what(?:'s| is|s)? my most (?:urgent|pressing) (?:task|thing)(?: today)?$"
        # "What's the most important thing on my list", "what's next on my
        # to do list" (2026-10-07: a model, and a project called "list").
        r"|^what(?:'s| is|s)? (?:the )?(?:most important|top|biggest|first|most urgent|main|next) (?:thing|task|item)?"
        r" ?(?:on|in) my (?:list|to ?do list|to-do list|task list|tasks)$"
        r"|^what(?:'s| is|s)? next on my (?:list|to ?do list|to-do list|task list)$")),
    ("tasks_clear_done", re.compile(
        r"^(?:clear|delete|remove|get rid of|clean up) (?:all )?(?:my |the )?(?:completed|finished|done|old) tasks$")),
    # HER WORK, ASKED ABOUT (2026-10-07). "Is anything stuck" answers "say
    # what's blocked and I'll list them" - and "what's blocked" went to the
    # planner, a promise with no reader. "What's in your queue", "what
    # projects are you working on" and "what's next for barkly" too.
    ("work_blocked", re.compile(
        r"^what(?:'s| is|s)? (?:blocked|stuck|held up)(?: right now)?$"
        r"|^what are (?:you|u) (?:blocked|stuck) on$|^(?:list|show me|read me) (?:the |your )?blocked (?:work|items|things)$")),
    ("work_queue", re.compile(
        r"^what(?:'s| is|s)? (?:in|on) (?:your|the) (?:queue|work queue|plate|to-?do list)$"
        r"|^what(?:'s| is|s)? queued(?: up)?$|^what(?:'s| is|s)? next (?:for you|in your queue|on your list)$"
        r"|^what (?:are|will) (?:you|u) (?:going to )?(?:do|work on) next$")),
    ("projects", re.compile(
        r"^what projects (?:are (?:you|u)|r u|am i|are we) (?:working on|carrying|running|doing)(?: right now)?$"
        r"|^what are (?:my|our|your) projects$|^(?:list|name|read me) (?:my|our|your|the) projects$"
        r"|^what projects (?:do i|do we|do (?:you|u)) have$"
        r"|^how (?:are|r) (?:the|my|our|your) projects(?: going| doing| coming along| looking)?$")),
    ("project_next", re.compile(
        r"^what(?:'s| is|s)? (?:the )?next (?:step )?(?:for|on|in) (?!(?:the |my )?(?:calendar|schedule|agenda|day|diary|list|to ?do list|to-do list|task list)$)(?:the |my )?(?P<what>[a-z0-9][a-z0-9 '-]{1,30}?)(?: project)?$")),
    ("disk", re.compile(
        r"^how much (?:disk|disk space|storage|space|hard drive space|room)(?: do (?:i|we) have| is)?"
        r"(?: free| left| available)?(?: on (?:this|the|my) (?:computer|machine|pc|laptop|disk|drive|hard drive))?$"
        r"|^(?:is|how is) (?:the |this |my )?(?:computer|machine|pc|laptop|disk|drive) (?:low on (?:space|storage|disk)|full|out of space)$")),
    ("ip", re.compile(
        r"^what(?:'s| is) (?:my|this computer's|the|this machine's) ip(?: address)?$"
        r"|^what ip(?: address)? (?:am i on|is this|do i have)$")),
    ("internet", re.compile(
        # "Is MY internet working" read out a capability about offline
        # models instead (2026-10-07).
        r"^(?:is|do (?:i|we) have) (?:the |an |my |our )?(?:internet|wifi|wi-fi|network|connection)(?: connection)?"
        r"(?: working| up| on| down| connected| okay| ok)?$"
        r"|^(?:am i|are we|are you) (?:online|connected|on the internet)$"
        r"|^(?:is|has) (?:the|my|our) (?:internet|wifi|wi-fi) (?:down|out|gone|back)$"
        r"|^(?:does|is) (?:the |my )?(?:internet|wifi|wi-fi) (?:work|working)$|^can you (?:get|reach) online$")),
    ("windows", re.compile(
        r"^what(?:'s| is| are)? (?:apps?|programs?|windows?)(?: are| is)? (?:open|running|up)"
        r"(?: right now| now| on (?:this|the|my) (?:computer|machine|pc|laptop|screen))?$"
        # "What's open NOW" is a shop question (2026-10-07: it was read the
        # PC's windows); bare "what's open" is still the screen.
        r"|^what(?:'s| is) open$|^what(?:'s| is) on (?:my|the) screen(?: right now| now)?$"
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
    ("wrong", re.compile(
        r"^what went wrong(?: today| tonight| so far today| overnight)?$"
        r"|^what(?:'s| is|s)? (?:broken|failing|stuck)(?: today)?$"
        r"|^(?:did|has) anything (?:fail|failed|go wrong|gone wrong|break|broken)(?: today| tonight| overnight| last night)?$"
        r"|^what failed(?: today| tonight)?$|^any (?:errors|failures|problems)(?: today| tonight)?$")),
    # "What's the last thing you did" paid a model to read the newest
    # line of a journal she holds (2026-09-22).
    ("last", re.compile(
        r"^what(?:'s| is|s| was)? the last thing (?:you|u) did$"
        r"|^what did (?:you|u) (?:just )?do (?:last|just now|most recently|a (?:minute|moment|second) ago)$"
        r"|^what did (?:you|u) just do$"
        r"|^what was (?:your|the) (?:last|most recent) (?:action|thing)$"
        r"|^what(?:'s| is|s)? the (?:last|latest|most recent) thing (?:you|u)(?:'ve| have)? done$")),
    # HIS BIRTHDAY, kept in her memory of him (2026-10-07: "how old am I"
    # and "when is my birthday" told him she couldn't think).
    # "How old will I be in 2030" / "in 5 years" (2026-10-07: to a model)
    ("age_in", re.compile(
        r"^how old (?:will i be|am i going to be|would i be|will i turn) (?:in (?P<age_year>\d{4})|in (?P<age_n>\d{1,2}) years?"
        r"|(?:on|at) my next birthday)$")),
    ("birthday", re.compile(
        r"^(?:when(?:'s| is|s) my birthday|what(?:'s| is|s) my (?:birthday|date of birth|birth ?date|dob)"
        r"|how old am i(?: turning| going to be)?|how many days (?:until|till|to|before) my birthday"
        r"|how long (?:until|till|before) my birthday|when(?:'s| is|s) my next birthday"
        r"|how many days (?:until|till|to|before) my next birthday)\s*\??$")),
    # DEADLINES HE SET. "Add a task to renew my license by Friday" stores a
    # real deadline; "what's due this week" and "what's overdue" told him she
    # couldn't think (2026-10-07).
    ("tasks_due", re.compile(
        r"^(?:what(?:'s| is|s)?|anything|is anything|what do i have) (?P<due>overdue|late|past due|due"
        r"(?: today| tomorrow| this week| soon| next)?)(?: on my list)?\s*\??$"
        r"|^what(?:'s| is|s)? (?P<due2>coming up|due) (?:on my (?:list|task list|to ?do list))\s*\??$"
        # "What tasks do I have today" (2026-10-07: to the planner), and
        # "what did I forget", which is the overdue list asked guiltily.
        r"|^what tasks (?:do i have|have i got|are there|are on my list)(?: due)? (?P<due3>today|tomorrow|this week)\s*\??$"
        r"|^(?:what did i forget(?: to do)?|did i forget (?:anything|something)|am i forgetting (?:anything|something))"
        r"(?P<due4>)\s*\??$")),
    ("weeks_until", re.compile(
        r"^how many (?:weeks|months) (?:until|till|to|before) (?:the )?(?P<weeks>[a-z][a-z0-9' ]{2,30}?)\s*\??$")),
    # "How many days until Christmas" paid a model for arithmetic on a
    # calendar (2026-09-23). Weekdays, named days and a month-and-day.
    # A CLOCK TIME, NOT A DAY (2026-10-07): "how long until 5pm", "how many
    # hours until midnight" went to the planner - "until" reads days only.
    ("clock_until", re.compile(
        r"^(?:how long|how much (?:longer|time)|how many (?:hours|minutes|hours and minutes))(?: is (?:it|there|left))?"
        r" (?:until|till|til|before|to) (?P<clock_until>midnight|noon|midday|\d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?"
        r"(?: o'?clock)?)(?: tonight| today| this (?:afternoon|evening))?\s*\??$")),
    # "What time zone am I in", "is it daylight saving time" (2026-10-07).
    ("time_zone", re.compile(
        r"^what (?:time ?zone|timezone) (?:am i in|are we in|is (?:this|it|set))\s*\??$|^what(?:'s| is) my (?:time ?zone|timezone)\s*\??$"
        r"|^is it (?:daylight sav(?:ing|ings)(?: time)?|dst)(?: (?:right )?now)?\s*\??$"
        r"|^(?:when|what day) (?:do|does) (?:the )?clocks? (?:change|go back|go forward|spring forward|fall back)\s*\??$"
        # "When is daylight saving" (2026-10-07: to the planner).
        r"|^when (?:is|does) (?:the )?(?:daylight sav(?:ing|ings)(?: time)?|dst|the time change)(?: start| end| begin| this year)?\s*\??$"
        r"|^(?:is it|are we (?:on|in)) daylight sav(?:ing|ings)(?: time)?(?: right now| now)?\s*\??$")),
    # WHAT'S AHEAD (2026-10-07): "what's coming up", "what am I doing
    # tonight", "how many meetings do I have tomorrow" went to the planner.
    # Her calendar and reminders, soonest first.
    ("coming_up", re.compile(
        r"^(?:what(?:'s| is)|anything|is anything|do i have anything) coming up(?: (?P<coming>today|tonight|tomorrow))?\s*\??$"
        r"|^what(?:'s| is) (?:on )?(?:for )?(?P<coming2>tonight)\s*\??$|^what am i doing (?P<coming3>tonight|this evening)\s*\??$"
        r"|^what do i have (?:on |going on )?(?P<coming4>tonight|this evening)\s*\??$")),
    ("meetings_count", re.compile(
        r"^how many (?:meetings|appointments|events)(?: (?:do i have|are on my calendar|have i got))?"
        r" (?P<coming5>today|tomorrow|tonight)\s*\??$")),
    # "How long until my alarm" (2026-10-07: to the planner).
    ("alarm_left", re.compile(
        r"^how long (?:until|till|before) my (?:next )?alarm(?: goes off)?\s*\??$")),
    ("until", re.compile(
        r"^how (?:many days|long) (?:until|till|to|before) (?:the )?(?!(?:you|u|i|we|she|it|they|he) )"
        r"(?P<until>[a-z][a-z' ]{2,30}?)(?: is it)?$")),
    # "What day is Thanksgiving" is asked for the DATE, so it leads with it.
    ("until_day", re.compile(
        r"^(?:when is|when's|what day is|what day's|what day does|which day is) (?P<until2>christmas|new year(?:'s)?(?: day| eve)?|halloween|thanksgiving|"
        r"valentine'?s(?: day)?|easter|the fourth of july|july 4th|independence day|labou?r day|memorial day|"
        r"mlk day|martin luther king day|presidents'? day|president's day|mother'?s day|father'?s day|"
        r"columbus day|indigenous peoples'? day)(?: on| fall on| this year)?\s*\??$")),
    # "What's the date tomorrow", "what was yesterday's date", "what week is
    # it", "how many days in February" (2026-10-07, all to a model).
    # THE NEXT HOLIDAY (2026-10-07: "what holiday is next" and "is today a
    # holiday" went to the planner while every date was computed here).
    # HIS DAY, LOGGED, read back (2026-10-07: all to a model). The notes
    # "I drank a glass of water", "I ran 3 miles" are added up here.
    ("logged", re.compile(
        r"^how (?:much|many (?:glasses|cups|bottles|mugs|cans)(?: of)?) (?P<logged_drink>water|coffee|tea|soda|beer|wine|juice|milk)"
        r" (?:have i (?:had|drunk|drank)|did i (?:have|drink))(?P<logged_w> today| this week)?\s*\??$"
        r"|^how (?:far|many (?:miles|km|kilometers)) (?:did|have) i (?P<logged_move>run|ran|walk|walked|jog|jogged|bike|biked|cycle|cycled|swim|swum|swam|hike|hiked)"
        r"(?P<logged_w2> today| this week)?\s*\??$"
        r"|^how (?:much|long|many hours) did i (?P<logged_sleep>sleep)(?: last night| for)?\s*\??$"
        r"|^(?:did|have) i (?P<logged_did>work(?:ed)? out|exercised?|meditated?|stretch(?:ed)?|done yoga|did yoga|gone to the gym|go to the gym)"
        r"(?P<logged_w3> today| this week)?\s*\??$")),
    ("holiday_next", re.compile(
        r"^(?:what(?:'s| is|s) the next (?:holiday|public holiday|federal holiday|big holiday)"
        r"|what holiday is (?:next|coming up)|when(?:'s| is|s) the next (?:holiday|public holiday|federal holiday))\s*\??$"
        r"|^is (?P<holiday_on>today|tomorrow|it) a (?:holiday|public holiday|federal holiday)(?: today)?\s*\??$"
        # "What holidays are coming up" (2026-10-07: to a model)
        r"|^(?:what|which) (?P<holiday_list>holidays) (?:are )?(?:coming up|are next|are left(?: this year)?|do we have coming up)\s*\??$"
        r"|^(?:what are the |list the )?(?P<holiday_list2>upcoming|next (?:few|three|3)) holidays\s*\??$")),
    # "How many weekdays until Christmas" (2026-10-07: to a model)
    ("workdays_until", re.compile(
        r"^how many (?:weekdays|work ?days|working days|business days|school days) (?:are there )?(?:until|till|to|before|left (?:until|till|before)) "
        r"(?:the )?(?P<workdays>[a-z0-9][a-z0-9' ]{2,30}?)\s*\??$")),
    ("calendar_fact", re.compile(
        r"^(?:what(?:'s| is|s| was)? the date|what date is it|what date was it) (?P<cal>tomorrow|yesterday)\s*\??$"
        r"|^what (?:was|is) (?P<cal2>yesterday|tomorrow)(?:'s)? date\s*\??$"
        r"|^what day (?:was|is|will it be) (?P<cal3>yesterday|tomorrow)\s*\??$"
        r"|^what (?P<cal4>week) (?:is it|of the year is it|number is it|are we in)\s*\??$"
        r"|^how many days (?:are )?(?:in|does) (?P<cal5>january|february|march|april|may|june|july|august|september|october|november|december|this month)(?: have)?\s*\??$"
        r"|^is (?P<cal6>this|it) a leap year\s*\??$")),
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
        r"|^(?:what(?:'s| is) the )?(?:current |local )?time in (?P<time_in3>[a-z][a-z .'-]{1,40}?)\s*\??$"
        # "How far ahead is Tokyo", "what's the time difference with London"
        # (2026-10-07: to a model) - the same answer says how far.
        r"|^how (?:far|many hours) (?:ahead|behind) (?:of (?:me|us) )?is (?P<time_in4>[a-z][a-z .'-]{1,40}?)\s*\??$"
        r"|^what(?:'s| is|s)? the time difference (?:with|to|between (?:me|here|us) and) (?P<time_in5>[a-z][a-z .'-]{1,40}?)\s*\??$")),
    # "What time is it there" after asking about a place (2026-10-07).
    ("time_there", re.compile(r"^(?:what(?:'s| is) the time|what time is it) (?:there|over there)(?: now| right now)?\s*\??$")),
    # A CLOCK TIME IN ANOTHER ZONE (2026-10-07: "convert 3pm est to pst",
    # "what's 9am in london" went to the planner).
    ("time_convert", re.compile(
        r"^(?:convert |what(?:'s| is|s) |what time is )?(?P<t>\d{1,2}(?::\d{2})? ?(?:am|pm)|noon|midnight)"
        r"(?: (?P<from>[a-z][a-z ]{1,20}?))? (?:to|in|into) (?P<to>[a-z][a-z ]{1,20}?)(?: time)?\s*\??$"
        # "When it's noon here, what time is it in Paris" (2026-10-07: to a model)
        r"|^(?:when|if) it(?:'s| is) (?P<t2>\d{1,2}(?::\d{2})? ?(?:am|pm)?|noon|midnight)(?: here| for me| my time)?,? "
        r"what(?:'s| is)? (?:the )?time (?:is it )?in (?P<to2>[a-z][a-z ]{1,20}?)\s*\??$")),
    ("date_after", re.compile(
        r"^what(?:'s| is| date is| day is| will the date be)? (?P<n>\d{1,3}|a|one|two|three|four|five|six|seven|eight|nine|ten)"
        r" (?P<unit>days?|weeks?|months?) (?:from|after) (?:today|now)\s*\??$"
        r"|^what(?:'s| is) the date (?:in )?(?P<n2>\d{1,3}|a|one|two|three|four|five|six|seven|eight|nine|ten) (?P<unit2>days?|weeks?|months?)"
        r"(?: from (?:today|now))?\s*\??$"
        # "What was the date 100 days ago" (2026-10-07: to the planner).
        r"|^what (?:was the date|date was it|day was it|was the day|was it) (?P<n3>\d{1,3}|a|one|two|three|four|five|six|seven|eight|nine|ten)"
        r" (?P<unit3>days?|weeks?|months?) ago\s*\??$")),
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
        r"top of the morning|rise and shine|i'?m awake|i'?m up|i just woke up)(?:,? thea)?(?: !)?$")),
    ("today", re.compile(
        r"^what (?:did|have) (?:you|u) (?:do|done)(?: today)?$"
        r"|^what have (?:you|u) been doing$"
        # "What did you do while I was gone" (2026-10-07: to the planner).
        r"|^what (?:did|have) (?:you|u) (?:do|done|been doing|been up to) while i was (?:gone|away|out|asleep|sleeping|at work)$"
        r"|^what have (?:you|u) been up to(?: today)?$"
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
        r"|^what did i miss(?: while i was (?:out|gone|away|asleep|at work))?$"
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
    # round trip for it. Deliberately NOT "what did I ask you to do
    # yesterday": that asks for HIS instructions, and her journal also
    # holds scheduled work nobody asked for, so the fast lane would be
    # answering a near-miss. That one keeps the model, which now gets the
    # right day's journal to answer from (`recollection.for_question`).
    ("yesterday", re.compile(
        r"^what (?:did|have) (?:you|u) (?:do|done|get done|been doing) yesterday$"
        r"|^what (?:did|have) (?:you|u) (?:do|done) last night$"
        r"|^what happened yesterday$")),
    # Eight seconds and a round trip for the clock she is holding.
    ("clock", re.compile(
        r"^what(?:'s| is|s)? the time( right now| now)?$"
        r"|^(?:do you know )?what time is it( right now| now)?$"
        r"|^(?:got|have) the time$|^time$"
        # "What time do you have" (2026-10-07: to a model).
        r"|^what time (?:do (?:you|u) have|have (?:you|u) got)$")),
    # "Help" went to the planner (2026-10-07). A few things to say, in his
    # words; "what can you do" is the long answer.
    ("help", re.compile(r"^(?:help|help me|i need help|what can i say|what do i say|how do i use you"
                        r"|what (?:can|should) i ask(?: you)?|how does this work)$")),
    ("date", re.compile(
        r"^what(?:'s| is|s)? (?:the |today'?s? )?date( today)?$"
        r"|^what day is it( today)?$|^what(?:'s| is|s)? today$"
        r"|^what day of the week is it$"
        # "what day is it tomorrow" went to a model (2026-09-24).
        r"|^what day (?:is it|will it be|is) (?P<date_ahead>tomorrow|the day after tomorrow)$"
        r"|^what(?:'s| is|s)? (?P<date_ahead2>tomorrow|the day after tomorrow)(?:'s date)?$"
        # "What's the date tomorrow" (2026-10-07: to a model).
        r"|^what(?:'s| is|s)? the date (?P<date_ahead3>tomorrow|the day after tomorrow)$"
        r"|^what date is (?P<date_ahead4>tomorrow|the day after tomorrow)$")),
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
        r"|^what(?:'s| is|s)? left (?:on my list|to do)$|^how many things (?:do i have )?(?:left )?to do$"
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
        r"|^what do (?:you|u) do$")),
    # THE HONESTY QUESTION, answered from the registry with no model. With
    # every model down "what can't you do" came back "I can't think just
    # now" - the one question that must never need thinking.
    ("cannot", re.compile(
        r"^what (?:can'?t|cannot|can not|couldn'?t) (?:you|u)(?: do| handle| do yet)?(?: for me)?$"
        r"|^what are (?:you|u) (?:unable|not able) to do$"
        r"|^what (?:don'?t|doesn'?t) (?:you|u) (?:do|support|handle)(?: yet)?$"
        r"|^what(?:'s| is|s)? (?:still )?(?:missing|not built|not built yet|unavailable|not working)$"
        r"|^what (?:isn'?t|is not) (?:built|working|set up)(?: yet)?$")),
    # HIS DAY, from the calendar mirror she already holds.
    ("agenda", re.compile(
        r"^what(?:'s| is|s)? (?:on|in) (?:my |the )?(?:calendar|schedule|agenda|plate)"
        r"(?: for)?(?: on| this)? (?P<day>today|tomorrow|this week|next week|this weekend|the weekend|next weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^what (?:do i have|have i got|is there|am i doing) (?:on )?(?P<day2>today|tomorrow|this week|next week|this weekend|the weekend|next weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^(?:my |the )?(?:calendar|schedule|agenda) (?:for )?(?P<day3>today|tomorrow|this week|next week|this weekend|the weekend|next weekend)$"
        r"|^what(?:'s| is|s)? (?P<day4>today|tomorrow)(?:'s| like)?(?: looking like| look like)?$"
        r"|^(?:what(?:'s| is|s)? (?:on|happening|coming up)|anything (?:on|happening|coming up)|what have i got on"
        r"|what(?:'s| is|s)? (?:my|the) (?:week|day) (?:looking like|look like))"
        r"(?: for)?(?: on)? (?P<day5>today|tomorrow|this week|next week|this weekend|the weekend|next weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^what(?:'s| is|s)? (?:my|the) (?P<day6>week) (?:looking like|look like)$"
        # "What's my schedule this week" paid seven seconds of model for a
        # feed the shapes above already read (2026-09-22).
        r"|^what(?:'s| is|s)? (?:my |the )?(?:calendar|schedule|agenda) (?:for |like )?(?P<day7>today|tomorrow|this week|next week|this weekend|the weekend|next weekend)"
        r"(?: like| looking like)?$"
        # "What's my schedule look like" (2026-10-07: to the planner) - today
        # unless he names a day.
        r"|^what(?:'s| is|s| does)? (?:my |the )?(?:schedule|calendar|agenda) (?:look|looking|looks) like"
        r"(?: (?:for )?(?P<day10>today|tomorrow|this week|next week))?$"
        # "Show me my calendar for next week" planned for 73 s and died on a
        # date string; "what meetings do I have tomorrow" paid a model.
        r"|^(?:show me|pull up|open|read me|give me) (?:my |the )?(?:calendar|schedule|agenda)(?: for)? (?P<day8>today|tomorrow|this week|next week)$"
        r"|^what (?:meetings|appointments|events|calls) (?:do i have|have i got|are there)(?: on)? (?P<day9>today|tomorrow|this week|next week)$"
        # "Am I free this weekend" (2026-10-07: to the planner).
        r"|^am i (?:free|busy) (?P<day11>this weekend|the weekend|next weekend|this week|next week)$")),
    # "Do I have any meetings today" was answered "nothing coming up" - a
    # different question - and "how busy am I this week" and "what's my
    # first meeting tomorrow" went to the planner (2026-10-07).
    ("agenda_more", re.compile(
        r"^(?:do i have|have i got|is there) (?:any |an )?(?:meetings?|appointments?|events?|plans|calls?)"
        r"(?: on)?(?: for)? (?P<day>today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^how (?:busy|booked|full) (?:am i|is my (?:day|week|calendar|schedule))(?: on)? (?P<day2>today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$")),
    # "AM I DOUBLE BOOKED" (2026-10-07: to the planner) - two events on his
    # calendar that overlap, in the coming week.
    ("double_booked", re.compile(
        r"^(?:am i|are we) (?:double[- ]?booked|overbooked)(?: (?:this week|today|tomorrow))?\s*\??$"
        r"|^(?:do i have|are there|any) (?:any )?(?:calendar )?(?:conflicts|clashes|overlaps|overlapping (?:meetings|events))"
        r"(?: (?:on my calendar|this week|today|tomorrow))?\s*\??$")),
    # A DAY BY ITS DATE (2026-10-07: "what's on my calendar on the 15th"
    # and "what do I have on October 15" went to the planner).
    ("agenda_on", re.compile(
        r"^(?:what(?:'s| is|s)? on (?:my |the )?(?:calendar|schedule|agenda)|what (?:do i have|have i got|am i doing)"
        r"|anything (?:on|happening)|am i (?:free|busy))"
        r" (?:on |for )?(?P<agenda_on>the \d{1,2}(?:st|nd|rd|th)?(?: of (?:january|february|march|april|may|june|july|august"
        r"|september|october|november|december))?|(?:january|february|march|april|may|june|july|august|september|october"
        r"|november|december) (?:the )?\d{1,2}(?:st|nd|rd|th)?)\s*\??$")),
    # "When am I done today", "when's my last meeting" (2026-10-07: to the planner).
    ("last_meeting", re.compile(
        r"^(?:what(?:'s| is|s)?|when(?:'s| is)?) my last (?:meeting|appointment|event|call|thing)(?: (?P<lastday>today|tomorrow))?\s*\??$"
        r"|^(?:when|what time) (?:am i|will i be) (?:done|finished|free)(?: for the day)?(?: (?P<lastday2>today|tomorrow))?\s*\??$"
        r"|^what time do i (?:finish|get done|wrap up)(?: (?P<lastday3>today|tomorrow))?\s*\??$")),
    ("first_meeting", re.compile(
        r"^(?:what(?:'s| is|s)?|when(?:'s| is)?) my first (?:meeting|appointment|event|call|thing)(?:(?: on)? (?P<day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$")),
    ("repo_wrong", re.compile(
        r"^what(?:'s| is|s)? (?:wrong|broken|failing|up|going on|the matter) with (?:the |my )?(?P<repo_wrong>[a-z0-9][a-z0-9 _.-]{1,40}?)"
        r"(?: pipeline| repo| project| bot)?\s*\??$"
        r"|^what did (?:the |my )?(?P<repo_wrong2>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)? do (?:today|overnight|last night|this week)\s*\??$")),
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
        r"^how many repos (?:are )?(?:you|u) (?:watching|watch|track|tracking)$"
        r"|^how many repos do (?:you|u) watch$"
        r"|^what repos (?:are )?(?:you|u) watching$"
        r"|^how many repos$")),
    ("shopping", re.compile(
        r"^what(?:'s| is|s)? on my shopping list$|^what(?:'s| is|s)? on my list$"
        r"|^(?:my )?shopping list$|^what do i need (?:to buy|from the store)$"
        r"|^what(?:'s| is|s)? on the shopping list$"
        # "Do I need anything from the store" asked about "anything from the
        # store" as an item and went to the planner (2026-10-07).
        r"|^do (?:i|we) need (?:anything|something|stuff) (?:from|at) the (?:store|shop|grocery store|supermarket|grocer'?s)\s*\??$"
        r"|^what do (?:i|we) need to (?:get|pick up|grab) (?:from|at) the (?:store|shop|grocery store|supermarket)\s*\??$"
        r"|^what(?:'s| is|s)? on (?:my|the) grocery list\s*\??$|^(?:my |the )?grocery list$")),
    # "What is running" was wired into `voice` and NOT here, so SAYING it
    # was instant and TYPING it paid a full planner round trip for the
    # same answer out of the same store. Every door should give the same
    # one — that is the whole point of there being one answer.
    ("running", re.compile(
        r"^what(?:'s| is|s)? running(?: right now)?$"
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
    # "Am I busy at 3", "am I free tomorrow at 2:30", "do I have anything
    # at 4" went to the planner (2026-10-07); "am I free friday" and "am I
    # busy tomorrow" too. The calendar mirror answers all of them.
    ("free_at", re.compile(
        r"^(?:am i|will i be) (?:free|busy|available|booked)(?: (?:on )?(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?"
        r"(?: (?:at|around) [0-9a-z: ]{1,14}?)?(?: (?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$"
        r"|^(?:do i|have i) (?:have|got) (?:anything|something|a meeting|plans) (?:on )?(?:at|around) [0-9a-z: ]{1,14}?"
        r"(?: (?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$")),
    # Already computed every beat for the wall (`next_appointment`), and
    # it was paying a round trip to be read aloud. Deliberately without a
    # trailing clause: "what's my next meeting ABOUT" and "move my next
    # meeting" are different questions and belong to the planner.
    # THE NEXT MEETING, IN DETAIL, AND THE SHAPE OF THE DAY (2026-10-07).
    # "Who is my next meeting with", "where is my next meeting" and "how
    # long is my day" all went to the planner - the calendar already holds
    # the attendees, the place, and the first start and last end.
    ("next_detail", re.compile(
        r"^(?P<nd_who>who(?:'s| is|s)?) (?:my next (?:meeting|appointment|call) with|in my next (?:meeting|call))\s*\??$"
        r"|^who am i meeting (?:with )?next\s*\??$"
        r"|^(?P<nd_where>where(?:'s| is|s)?) my next (?:meeting|appointment|event)\s*\??$")),
    ("day_span", re.compile(
        r"^how (?:long|busy|full|packed) is my day(?: today| tomorrow)?\s*\??$"
        r"|^when (?:does|do) my day (?:end|finish|wrap up)(?: today| tomorrow)?\s*\??$"
        r"|^when(?:'s| is|s)? my last (?:meeting|appointment|event|call)(?: today| tomorrow)?\s*\??$"
        r"|^when (?:am i|will i be) (?:done|finished|free) (?:today|for the day|tonight|tomorrow)\s*\??$")),
    ("next_meeting", re.compile(
        r"^what(?:'s| is|s)? my next (?:meeting|appointment|event)$"
        r"|^how long (?:until|till|before) my next (?:meeting|appointment|event)$"
        r"|^when(?:'s| is)? my next (?:meeting|appointment|event)$"
        r"|^do i have (?:any )?(?:meetings|appointments)(?: coming up| today)?$"
        r"|^what(?:'s| is|s)? (?:next |coming up )?on my (?:calendar|schedule|agenda)$"
        r"|^what(?:'s| is|s)? (?:next|coming up) (?:today|in my day|for me today)$"
        r"|^what(?:'s| is|s)? the next thing (?:on|in) my (?:calendar|schedule|day)\s*\??$"
        r"|^what(?:'s| is|s)? next (?:on|in) my (?:schedule|day)\s*\??$"
        r"|^(?:my )?next (?:meeting|appointment)$"
        r"|^what(?:'s| is|s)? my schedule(?: today)?$"
        # "What time is my next appointment" (2026-10-07: to a model).
        r"|^what time is my next (?:meeting|appointment|event|call)$"
        r"|^when do i have to (?:be somewhere|leave) next$|^where do i have to be next$")),
    # "What's my battery" became a memory lookup for 'battery' (2026-10-07).
    # `power.status` has read it on every beat since the night the laptop
    # slept mid-batch.
    ("battery", re.compile(
        r"^(?:what(?:'s| is|s)? (?:my |the )?(?:battery|battery level|battery at|charge)"
        r"|how much (?:battery|charge)(?: do i have| is left| have i got| left)?|battery(?: level| status)?"
        r"|(?:am i|is (?:the|my) (?:pc|laptop|computer)) (?:plugged in|charging|on battery)"
        r"|how(?:'s| is) (?:my |the )?battery(?: doing)?)\s*\??$")),
    ("version", re.compile(
        r"^what version are (?:you|u) on$|^what version are (?:you|u) running$|^what version are (?:you|u)$"
        r"|^which version (?:are (?:you|u)|is this)(?: on| running)?$"
        r"|^what code are (?:you|u) running$|^what(?:'s| is|s)? your version$"
        r"|^which (?:branch|commit) are (?:you|u) on$"
        r"|^are (?:you|u) (?:up to date|current|stale)$"
        r"|^are (?:you|u) running the latest code$")),
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
    ("interview_when", re.compile(
        r"^(?:what time|when) (?:is|'s) (?:my|the) (?:next )?interview(?: with [a-z0-9 .&'-]{1,40})?\s*\??$"
        r"|^how (?:long|many days|many hours) (?:until|till|before) (?:my|the) (?:next )?interview\s*\??$"
        r"|^(?:do i have|is there) an interview (?:coming up|scheduled|booked)(?: today| tomorrow| this week)?\s*\??$"
        r"|^when(?:'s| is) my next interview\s*\??$")),
    # THE DAY AS SHE HOLDS IT: calendar, tasks, the hunt.
    ("plan_today", re.compile(
        r"^what(?:'s| is|s)? (?:the |my )?plan (?:for )?(?:today|this morning|this afternoon)\s*\??$"
        r"|^what(?:'s| is|s)? (?:on )?(?:for |the plan for )?today\s*\??$|^what (?:am i|are we) doing today\s*\??$"
        r"|^what(?:'s| is|s)? (?:my|the) day (?:look like|looking like)(?: today)?\s*\??$"
        # "How's my day look" fell to the planner (2026-10-07).
        r"|^how(?:'s| is| does|s)? (?:my day|today|the day) (?:look|looking)(?: like)?(?: today)?\s*\??$")),
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
        r"|^is (?:anything|something) (?:stuck|blocked|held up)\s*\??$")),
    # "What's your name" got the whole introduction, about "his" tasks, said
    # TO him. A name question gets a name.
    ("her_name", re.compile(r"^what(?:'s| is|s) your name\s*\??$|^what (?:do|should) i call (?:you|u)\s*\??$")),
    ("who_are_you", re.compile(
        r"^(?:who|what) (?:are|r) (?:you|u)(?: exactly| anyway)?\s*\??$"
        r"|^introduce yourself\s*\.?$|^tell me about yourself\s*\.?$")),
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
    # "DO I NEED AN UMBRELLA" (2026-10-07: to the planner): yes or no
    # first, then the forecast it stands on. Before "weather", which would
    # answer "will it rain tomorrow" with a forecast and no yes.
    ("rain", re.compile(
        r"^(?:do i|will i|should i) (?:need|take|bring) (?:an |my )?(?:umbrella|raincoat|rain jacket)"
        r"(?: (?P<weather>today|tonight|tomorrow|this weekend|on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)))?$"
        r"|^(?:is|will) it (?:going to |gonna )?(?:rain|snow)(?: (?:on )?(?P<weather2>today|tonight|tomorrow|this weekend|the weekend|this week"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$")),
    # SOMEWHERE ELSE (2026-10-07): "what's the weather like in Chicago"
    # went to the planner. Before the pattern for his own weather, which
    # would otherwise never see the town.
    # WHEN IS HIS THING, BY ITS NAME (2026-10-07): "what time is my dentist
    # appointment" and "what are my reminders for tomorrow" went to the
    # planner. Her calendar and her reminders hold both answers.
    ("when_mine", re.compile(
        r"^(?:what time|when|what day)(?:'s| is) my (?:next )?(?P<when_mine>(?:[a-z][a-z' ]{0,30}? )?"
        r"(?:appointment|appt|meeting|call|interview|dinner|lunch|breakfast|class|game|flight|party|reservation|session|visit"
        # "When is my dentist" names the appointment by who it is with (2026-10-07).
        r"|dentist|doctor|therapist|haircut|checkup|check-up|vet|physio|massage|exam|test|shift|practice)"
        r"(?: (?:with|at|for) [a-z][a-z' ]{1,30}?)?)(?: (?:today|tomorrow|this week|next))?\s*\??$")),
    ("reminders_on", re.compile(
        r"^(?:what are |what(?:'s| is) |read me |list )?(?:my |the )?(?:reminders|alarms)(?: do i have)? (?:for|on) "
        r"(?P<reminders_on>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??$"
        r"|^what reminders do i have (?:for |on )?(?P<reminders_on2>today|tomorrow|monday|tuesday|wednesday|thursday"
        r"|friday|saturday|sunday)\s*\??$|^do i have any reminders (?:for |on )?(?P<reminders_on3>today|tomorrow"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??$")),
    # A WORD'S MEANING (2026-10-07): "define serendipity" and "what does
    # ubiquitous mean" went to the planner. Not "what does that mean",
    # which is about what she just said.
    ("define", re.compile(
        r"^(?:define|definition of|what(?:'s| is) the (?:definition|meaning) of|look up the word|what is the word)"
        r" (?:the word )?(?!life\s*\??$)(?P<define>[a-z][a-z'-]{1,30}(?: [a-z][a-z'-]{1,20})?)\s*\??$"
        r"|^what does (?:the word )?(?!(?:that|this|it|he|she|they|you|u|that word|this word)\b)"
        r"(?P<define2>[a-z][a-z'-]{1,30}) mean\s*\??$")),
    ("weather_in", re.compile(
        r"^(?:what(?:'s| is|s)? (?:the )?(?:weather|forecast|temperature)(?: like| going to be like| looking like| doing)?"
        r"|how(?:'s| is) the weather(?: looking)?|weather|is it (?:raining|snowing|cold|hot|warm|nice)"
        r"|how (?:hot|cold|warm) is it) (?:in|for|at) (?!(?:the |this |next )?(?:morning|afternoon|evening|weekend|week|today|tomorrow|tonight"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b)"
        r"(?!(?:my |our |the )?(?:house|home|place|here|apartment|flat)\b)"
        r"(?P<weather_place>[a-z][a-z .,'-]{1,40}?|\d{5})"
        r"(?: (?:for |on )?(?:today|tonight|tomorrow|this weekend|the weekend|right now|now"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?\s*\??$")),
    ("weather", re.compile(
        r"^(?:what(?:'s| is|s)? (?:the )?weather(?: like| looking like| doing| going to be like)?(?: out(?:side)?)?"
        r"|how(?:'s| is) the weather(?: looking)?(?: out(?:side)?)?|what(?:'s| is|s)? it like out(?:side)?"
        r"|how(?:'s| is) it (?:looking )?out(?:side)?|is it (?:nice|cold|hot|warm) out(?:side)?)"
        # "What's the weather at my house" is his own (2026-10-07).
        r"(?: (?:at|near|by|around|in) (?:my |our )?(?:house|home|place|neighborhood|area)| here| at home)?"
        r"(?: (?:for |on )?(?P<weather>today|tonight|tomorrow|this (?:morning|afternoon|evening|weekend)|the weekend"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$"
        r"|^(?:is|will) it (?:going to )?(?:rain|snow) (?P<weather2>today|tonight|tomorrow)$"
        r"|^weather(?: (?P<weather3>today|tonight|tomorrow|this weekend|this week))?$"
        # "Will it be nice this weekend" (2026-10-07: to the planner).
        r"|^(?:will|is) it (?:going to )?be (?:nice|warm|cold|hot|sunny|good)(?: out(?:side)?)? (?P<weather11>today|tonight|tomorrow|this weekend|this week)\s*\??$"
        # "What's the weather this week", "the forecast for the weekend"
        # (2026-10-07: to the planner).
        r"|^what(?:'s| is|s)? the (?:weather|forecast)(?: looking)?(?: like)? (?:for )?(?P<weather9>this week|the week|the rest of the week|the next few days|this weekend|the weekend)\s*\??$"
        r"|^(?:how(?:'s| is) the weather|what(?:'s| is) the weather going to be)(?: like)? (?P<weather10>this week|this weekend|the next few days)\s*\??$"
        # "Should I bring an umbrella" and "what's the temperature" went to
        # a model (2026-10-07). They are the forecast, asked sideways.
        r"|^(?:should i|do i need to|do i need an?|do i need) (?:bring|take|grab|pack|wear)? ?(?:an? |my )?"
        r"(?:umbrella|jacket|coat|raincoat|sunscreen|sweater|hoodie|shorts|gloves|hat|layers)"
        r"(?: (?P<weather4>today|tonight|tomorrow))?$"
        r"|^(?:what(?:'s| is|s)? the temperature|how (?:hot|cold|warm|chilly) is it|what temperature is it)"
        r"(?: out(?:side)?| right now| now)?(?: (?P<weather5>today|tonight|tomorrow))?$"
        # "What's the high today" (2026-10-07: to the planner).
        r"|^what(?:'s| is|s| will be)? the (?:high|low|temperature high|temperature low)(?: (?P<weather7>today|tonight|tomorrow))?$"
        r"|^how (?:hot|cold|warm|chilly) (?:will it get|is it going to get|will it be|is it going to be)(?: (?P<weather8>today|tonight|tomorrow))?$"
        r"|^(?:is it|will it be) (?:going to be )?(?:raining|rainy|snowing|sunny|cold|hot|warm)"
        r"(?: out(?:side)?)?(?: (?P<weather6>today|tonight|tomorrow))?$")),
    # WIND, HUMIDITY AND THE BATTERY. All three went to the planner and,
    # with nothing thinking, came back "I can't think just now" - while the
    # forecast she had cached carried both numbers and Windows reports the
    # battery for free.
    ("humidity", re.compile(
        r"^(?:how humid is it|is it (?:humid|muggy)|what(?:'s| is|s) the humidity(?: like)?|humidity)"
        r"(?: (?:out(?:side)?|today))?(?: (?P<weather2>tonight|tomorrow))?$")),
    ("wind", re.compile(
        r"^(?:how windy is it|is it (?:windy|breezy)|what(?:'s| is|s) the wind(?: speed)?(?: (?:like|doing))?"
        r"|how(?:'s| is) the wind|wind speed)"
        r"(?: (?:out(?:side)?|today))?(?: (?P<weather3>tonight|tomorrow))?$")),
    # "WHAT'S THE NEWS" went to the planner (2026-10-07), which cannot know
    # today's news. The headlines off the feeds in config/news_feeds.json.
    ("news", re.compile(
        r"^(?:what(?:'s| is|s) (?:in )?the news|what(?:'s| is|s) (?:the )?(?:latest )?news(?: today)?|tell me the news"
        r"|(?:read|give|tell) (?:me )?(?:the )?(?:headlines|news)(?: today)?|(?:the |today's )?(?:headlines|news)(?: today)?"
        r"|what(?:'s| is|s) happening in the world(?: today)?|what(?:'s| are) the (?:top )?headlines(?: today)?"
        r"|any news(?: today)?|anything in the news)$")),
    ("speaking_pace", re.compile(
        r"^how fast (?:are you|do you) (?:talking|talk|speaking|speak)$|^what speed (?:are you|do you) (?:talking|talk|speaking|speak) at$")),
    ("stopwatch", re.compile(
        r"^how long (?:has|is) (?:the |my )?stopwatch(?: been)?(?: running| going| on)?$"
        r"|^what(?:'s| is|s)? (?:on )?(?:the |my )?stopwatch(?: at| say| showing)?$|^(?:check )?(?:the |my )?stopwatch$")),
    # "Start a stopwatch", then "how long has it been" (2026-10-07: to a
    # model). Only while a stopwatch is running; otherwise it goes on.
    ("stopwatch_it", re.compile(
        r"^how long (?:has it been|has that been|is it at|so far)(?: running| going)?(?: now| so far)?\s*\??$"
        r"|^what(?:'s| is|s)? (?:the time|it) (?:on it|at)(?: now)?\s*\??$|^time (?:check|so far)$")),
    ("greeting", re.compile(
        r"^(?:hi|hello|hey|yo|hiya|howdy|hey there|hi there)$"
        r"|^good (?:morning|afternoon|evening)$"
        r"|^how (?:are|r) (?:you|u)(?: doing)?(?: today| this morning| tonight)?$"
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
        r"|^(?:see (?:you|ya)(?: later)?|bye|goodbye|later|talk later|catch you later)$"
        # "I'm going to the gym" (2026-10-07: queued for a model to plan).
        r"|^(?:(?:i'?m|im|i am) )?(?:going|off|heading|leaving|popping out) (?:to|for) (?:the |a |my )?"
        r"(?:gym|store|shops?|grocery store|supermarket|walk|run|jog|class|practice|appointment|doctor'?s?|dentist'?s?|"
        r"school|church|lunch|dinner|coffee|movies|party|game|meeting|errands?|park|office|airport)(?: now| for a bit)?$")),
    # Replies from employers, from the application records.
    ("replies", re.compile(
        r"^(?:did|have) i (?:get|got|gotten|receive|received|hear) (?:any |anything )?(?:replies|responses|"
        r"back|any(?:thing)? back)(?: yet| today| from anyone)?$"
        r"|^any (?:replies|responses|word|news)(?: from (?:employers|anyone|the jobs))?(?: yet| today| overnight| last night| this morning)?$"
        r"|^(?:anything|any word|any news|anything new) from (?:the )?(?:employers|recruiters|companies|jobs)"
        r"(?: yet| today| overnight| this morning)?$"
        r"|^did any (?:employers?|companies|recruiters) (?:reply|write back|get back|respond)(?: to me)?(?: yet)?$"
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
        # "What model are you" (2026-10-07: to a model, which cannot say).
        r"|^what (?:model|ai|llm|brain) (?:are|r) (?:you|u)$|^what are (?:you|u) running on$"
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
    ("math", re.compile(
        r"^(?:what(?:'s| is|s)? |how much is |calculate )?(?P<pct>[\d.]+) ?(?:%|percent) of (?:\$)?(?P<of>[\d.,]+)(?P<pct_money> dollars| bucks)?$"
        # "What's a 20% tip on 45" (2026-10-07, to a model that wasn't there).
        r"|^(?:what(?:'s| is|s)? (?:a )?|how much is (?:a )?)(?P<tip>[\d.]+) ?(?:%|percent) tip (?:on|for) (?:a )?(?:\$)?(?P<bill>[\d.,]+)(?: dollars| bucks)?(?: bill| tab| check)?$"
        r"|^what(?:'s| is|s)? (?P<a>[\d.,]+) (?P<op>plus|minus|times|divided by|over|x|\+|-|\*|/) (?P<b>[\d.,]+)$"
        r"|^(?:convert |what(?:'s| is|s)? )?(?P<n>-?[\d.,]+) (?:degrees? )?(?P<from>miles?|km|kilometers?|kilometres?|pounds?|lbs?|"
        r"kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|fluid ounces?|fl oz|ml|milliliters?|millilitres?|liters?|litres?|gallons?|quarts?|pints?|grams?|g|yards?|yds?)"
        r" (?:to|in|into) (?P<to>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|"
        r"meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|fluid ounces?|fl oz|ml|milliliters?|millilitres?|liters?|litres?|gallons?|quarts?|pints?|grams?|g|yards?|yds?)$"
        # THE OTHER WORD ORDER: "how many miles is 10 km", "how many pounds in 5 kg"
        r"|^how many (?P<to2>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|fluid ounces?|fl oz|ml|milliliters?|millilitres?|liters?|litres?|gallons?|quarts?|pints?|grams?|g|yards?|yds?) (?:is|are|in|make|equals?|to) (?P<n2>[\d.,]+|a|an|one) ?(?P<from2>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|fluid ounces?|fl oz|ml|milliliters?|millilitres?|liters?|litres?|gallons?|quarts?|pints?|grams?|g|yards?|yds?)$"
        # "What's 72 degrees in Celsius" (2026-10-07: to a model) - the
        # scale it is FROM is the other one.
        r"|^(?:convert |what(?:'s| is|s)? )?(?P<deg>-?[\d.,]+) degrees? (?:to|in|into) (?P<deg_to>celsius|fahrenheit|c|f)$")),
    ("mine", re.compile(
        r"^what(?:'s| is|s)? my (?P<mine>email(?: address)?|phone(?: number)?"
        r"|number|city|town|name|first name|last name|full name|zip|zip code|postcode|postal code"
        r"|minimum salary|salary(?: floor| requirement| expectation| expectations)?|desired (?:pay|salary)"
        r"|asking (?:pay|salary|price)|pay(?: expectation| expectations)?|notice period|start date)$"
        r"|^who am i$")),
    # "What should you call me" (2026-10-07: to a model).
    ("call_me", re.compile(r"^what (?:should|do|will) (?:you|u) call me$|^what do i go by$")),
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
        r"|^what(?:'s| is) off the table\s*\??$")),
    ("home", re.compile(
        r"^where do i live$|^what city do i live in$"
        r"|^what town do i live in$|^where(?:'s| is) home$")),
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
        r"|^what(?:'s| is|s)? (?:the )?cpu (?:at|usage|load)\s*\??$"
        # "What's my cpu at" (2026-10-07: to the planner).
        r"|^what(?:'s| is|s)? my cpu(?: at| usage| load| doing)?\s*\??$|^how much cpu (?:am i|is it|are we) using\s*\??$")),
    ("drafts", re.compile(
        r"^(?:what|which)(?: emails?| notes?)? (?:have (?:you|u)|did (?:you|u)) draft(?:ed)?(?: for me)?\s*\??$"
        r"|^(?:any|what|list|show me|read me) (?:my |your |the )?drafts?(?: (?:do (?:you|u|i) have|waiting|for me|held))?\s*\??$"
        r"|^what(?:'s| is|s) (?:in|on) (?:my |your |the )?drafts?\s*\??$"
        r"|^how many (?:emails? |drafts? )?(?:are |do (?:you|u) have )?(?:in|on|held in) (?:my |the |your )?drafts?(?: folder)?\s*\??$"
        r"|^how many drafts (?:do (?:you|u) have|are (?:there|held|waiting))\s*\??$"
        r"|^what are (?:you|u) drafting\s*\??$|^what have (?:you|u) (?:got )?drafted\s*\??$"
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
    ("notes_list", re.compile(
        r"^what notes do (?:you|u|i) have(?: for me)?$|^(?:list|read me|read back|show me|read|show) (?:my |your |the |all my )?notes$"
        r"|^how many notes (?:do i have|have i got|are there)$|^(?:my|all my) notes$|^(?:do i have )?any notes$|^what(?:'s| is| are) (?:in )?my notes$"
        # "What are my notes" told him she couldn't think (2026-10-07).
        r"|^what(?: are|'re| r)? (?:my|your|the) notes\s*\??$"
        # "What did I write down" (2026-10-07: to the planner).
        r"|^what (?:did|have) i (?:write|written|jot|jotted|note|noted) down\s*\??$"
        r"|^what (?:have|did) i (?:told|tell) (?:you|u)(?: to remember| to note)?\s*\??$|^what have (?:you|u) noted(?: down)?$"
        r"|^what (?:have|did) i (?:asked|ask) (?:you|u) to remember\s*\??$"
        r"|^how many notes (?:do i have|have i got|are there)\s*\??$")),
    # "What's my last note", "what did I note yesterday" (2026-10-07: to
    # the planner). The journal keeps when each was written.
    ("note_last", re.compile(
        r"^(?:what(?:'s| is|s| was)|read(?: me)?|tell me) (?:my |the )?(?:last|latest|newest|most recent) note\s*\??$")),
    ("notes_day", re.compile(
        r"^what (?:did i|notes did i) (?:note|write down|jot down|save|take|make) (?P<notes_day>today|yesterday)\s*\??$"
        r"|^(?:what are |read(?: me)? |show(?: me)? )?(?:my |the )?notes (?:from|for) (?P<notes_day2>today|yesterday)\s*\??$")),
    # "Is milk on my list" went to the planner (2026-10-07). The list is a
    # store; whether a thing is on it is a read.
    ("shopping_has", re.compile(
        r"^(?:is|are) (?:there )?(?:any |some )?(?P<has>[a-z0-9][a-z0-9 '&-]{1,40}?) on (?:my|the) (?:shopping |grocery )?list\s*\??$"
        r"|^(?:did i|have i) (?:put|add|added) (?:any |some )?(?P<has2>[a-z0-9][a-z0-9 '&-]{1,40}?) (?:on|to) (?:my|the) (?:shopping |grocery )?list\s*\??$"
        r"|^how many (?:things|items) (?:are )?on (?:my|the) (?:shopping|grocery) list\s*\??$")),
    # "Do I need milk" (2026-10-07: to the planner). Only a YES is quick:
    # "do I need a visa" is not a shopping question, so a miss goes on.
    ("shopping_need", re.compile(
        r"^do (?:i|we) need (?:any |some |more )?(?P<need_q>(?!to\b)[a-z][a-z '&-]{1,30}?)\s*\??$")),
    # "Whose birthday is coming up", "when is mom's birthday" (2026-10-07:
    # a model, and the bare note read back with no day or distance).
    ("birthdays", re.compile(
        r"^(?:whose|who(?:'s| has a| has)) birthday(?:s)? (?:is |are )?(?:coming up|next|soon)\s*\??$"
        r"|^(?:any|are there any|do i have any|upcoming) birthdays?(?: (?:coming up|soon))?(?: (?P<bwin>this week|this month))?\s*\??$"
        r"|^(?:any )?birthdays? (?P<bwin2>this week|this month)\s*\??$"
        r"|^when(?:'s| is) the next birthday\s*\??$")),
    ("birthday_when", re.compile(
        r"^when(?:'s| is) (?:my )?(?P<bday>(?!my\b|your\b|our\b)[a-z][a-z ]{0,30}?)(?:'s|s'|’s) (?:birthday|bday)\s*\??$")),
    # A FACT HE TOLD HER, asked back (2026-10-07: "what's my favorite
    # color", "what is my blood type", "when is jess's birthday" each went
    # to a model while the note sat in her journal).
    ("fact_q", re.compile(
        r"^what(?:'s| is|s|are)? my (?P<fact>(?:favou?rite|fave) [a-z][a-z ]{1,25}?)s?\s*\??$"
        r"|^what(?:'s| is|s)? my (?P<fact2>blood type|shoe size|shirt size|ring size|pants size|dress size"
        r"|wifi(?: password| name)?|wi-fi(?: password)?|gate code|door code|garage code|locker (?:number|combination)"
        r"|license plate|plate number|account number|member(?:ship)? number|policy number|anniversary)\s*\??$"
        r"|^when(?:'s| is|s) my (?P<fact5>anniversary|wedding anniversary)\s*\??$"
        r"|^(?:when|what)(?:'s| is|s) (?:my )?(?P<fact3>[a-z][a-z' ]{1,30}?)(?:'s| s) (?P<factk>birthday|anniversary)\s*\??$")),
    # Questions about HER, each to a model that knows nothing she does not
    # (2026-10-07).
    ("about_her", re.compile(
        r"^(?P<her>how old are (?:you|u)|who (?:made|built|created|programmed) (?:you|u)"
        r"|are (?:you|u) (?:a robot|a bot|an ai|ai|human|a person|real|alive|a real person|sentient|conscious|self aware"
        r"|self-aware)"
        r"|do (?:you|u) remember me|do (?:you|u) know (?:who i am|me)"
        # "Are you ChatGPT", "how smart are you", "do you love me" (2026-10-07).
        r"|are (?:you|u) (?:chatgpt|chat gpt|claude|siri|alexa|gpt|google|gemini|cortana|jarvis)"
        r"|how smart are (?:you|u)|do (?:you|u) (?:love|like) me"
        # "Do you sleep" (2026-10-07: to a model).
        r"|do (?:you|u) (?:ever )?(?:sleep|rest|get tired|take breaks?)|are (?:you|u) (?:ever )?(?:tired|asleep|awake))$")),
    # "What's my work address", "what's my home address" (2026-10-07: a
    # recall of "work" that found nothing). A saved place, his own address,
    # or else exactly the recall it was before.
    # "When is my passport task due" (2026-10-07: read as a note about
    # "passport task", and "nothing on file" while the task sat there).
    ("task_due", re.compile(
        r"^when(?:'s| is) (?:my |the )?(?!(?:it|that|this|they|them)\b)(?P<due>[a-z0-9][a-z0-9 '-]{1,40}?)(?: task)? due\s*\??$"
        r"|^when do i (?:need|have) to (?P<due2>[a-z][a-z0-9 '-]{1,40}?)(?: by)?\s*\??$"
        r"|^what(?:'s| is) the (?:deadline|due date) (?:for|on) (?:my |the )?(?P<due3>[a-z0-9][a-z0-9 '-]{1,40}?)(?: task)?\s*\??$")),
    ("place_addr", re.compile(
        r"^what(?:'s| is|s) (?:my |the )(?P<place_a>(?!email\b|e-mail\b|ip\b|web\b|mac\b|mailing\b)[a-z][a-z' ]{0,30}?) address\s*\??$")),
    ("recall", re.compile(
        r"^what did i (?:tell|say to) (?:you|u) about (?:the |my )?(?P<recall>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        r"|^what(?:'s| is|s)? (?:my |the )(?P<recall2>[a-z0-9][a-z0-9 '-]{1,30}?)(?:'s)? (?:name|number|address|email|birthday|code|password|pin)\s*\??$"
        r"|^when (?:is|does|was) (?:my |the )?(?!(?:it|that|this|they|them)\b)(?P<recall3>[a-z0-9][a-z0-9 '-]{1,30}?) (?:up|due|over|expiring|expire|ending|end|starting|start|renewing|renew|coming up)\s*\??$"
        # "Remember that my car is a 2019 Civic" is an instruction, not a
        # question (2026-10-07: answered "I have nothing about that...").
        r"|^(?!(?:remember|know) (?:that\b|[a-z0-9 '-]*\b(?:is|are|was|were)\b))"
        r"(?:do (?:you|u) )?(?:remember|know) (?:anything about |what i said about )?(?:the |my )?(?P<recall4>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        r"|^what did i say about (?:the |my )?(?P<recall5>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        # "What notes do I have about Dana" (2026-10-07, to a model).
        r"|^(?:what|any|do i have any) notes (?:do i have )?(?:about|on|for|mentioning) (?:the |my )?(?P<recall6>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        # "What do I know about Sam" (2026-10-07: to a model).
        r"|^what do (?:i|you|we) know about (?:the |my )?(?P<recall12>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        # "What am I allergic to" (2026-10-07: to the planner, a turn after
        # "remember that I'm allergic to peanuts").
        r"|^what am i (?P<recall7>allergic) to\s*\??$|^what are my (?P<recall8>allergies)\s*\??$"
        r"|^do i have any (?P<recall9>allergies)\s*\??$|^am i (?P<recall10>allergic) to [a-z][a-z ,'-]{1,40}\s*\??$")),
    # "When does the plumber come" a turn after noting it (2026-10-07: to
    # the planner). A note answers it; no note is not "never" - his mail or
    # calendar may know - so that case goes on to a model.
    # "Who do I owe money", "how much do I owe Sam", "who owes me" (2026-10-07:
    # each to a model, a turn after "remember I owe Sam 20 dollars").
    ("owed", re.compile(
        r"^who (?:do i owe|owes me)(?: money| anything)?\s*\??$"
        r"|^(?:do i owe|does) (?:anyone|anybody) (?:any )?(?:money|anything)(?: owe me(?: money)?)?\s*\??$"
        r"|^(?:what|who) do i (?:still )?owe(?: people)?\s*\??$"
        r"|^how much (?:do i owe|does) (?P<owe_amt>[a-z][a-z ]{0,25}?)(?: owe me)?\s*\??$"
        r"|^(?:do i owe|does) (?P<owe_who>(?!anyone\b|anybody\b)[a-z][a-z ]{0,25}?)(?: owe me)?(?: (?:any )?money| anything)?\s*\??$")),
    # "When did I last change the oil", "did I give the dog his medicine"
    # (2026-10-07: to a model and the planner, a turn after he said so).
    ("did_last", re.compile(
        r"^when did i (?:last )?(?P<did_v>change|give|feed|walk|water|clean|wash|mow|vacuum|replace|renew|fix|service"
        r"|rotate|flush|empty|refill|fill|charge|back up|update|trim|cut|groom|bathe|drop off|pick up|return|mail|post"
        r"|vaccinate|deworm|descale|defrost) (?P<did_o>[a-z][a-z' ]{1,40}?)(?: last)?\s*\??$"
        r"|^(?:did|have) i (?:already )?(?P<did_v2>change|changed|give|given|feed|fed|walk|walked|water|watered|clean|cleaned"
        r"|wash|washed|mow|mowed|vacuum|vacuumed|replace|replaced|renew|renewed|charge|charged|empty|emptied|refill|refilled"
        r"|drop off|dropped off|pick up|picked up|return|returned|mail|mailed) (?P<did_o2>(?!any\b)[a-z][a-z' ]{1,40}?)"
        r"(?P<did_today> today| yet| this morning| this week)?\s*\??$")),
    ("recall_when", re.compile(
        r"^when (?:does|is|will) (?:the |my )?(?P<recall11>[a-z][a-z '-]{1,30}?) (?:come|coming|arrive|arriving|get here|show up|be here)\s*\??$")),
    # "Search my notes for the plumber" (2026-10-07: to the planner).
    ("note_search", re.compile(
        r"^(?:search|look through|check|look in) (?:my |the )?notes (?:for|about) (?P<note_q>.{2,40})$"
        r"|^(?:find|look up) (?P<note_q2>.{2,40}?) in (?:my |the )?notes$"
        r"|^what did i (?:note|write down|jot down) about (?P<note_q3>.{2,40})$"
        # "Find my note about the car" (2026-10-07: to the planner).
        r"|^(?:find|show me|read me|read|pull up|get) (?:my |the )?notes? (?:about|on|for|mentioning) (?:the |my )?(?P<note_q5>.{2,40})$"
        # "What notes mention wifi", "any notes about the plumber" (2026-10-07: to a model)
        r"|^(?:what|which|any|do i have any) notes? (?:mention|mentions|mentioning|about|on|with|say anything about) (?P<note_q4>.{2,40})$")),
    # "What car do I drive" (2026-10-07) went to the planner a turn after
    # "remember that my car is a 2014 civic". A thing of his he OWNS is a
    # recall; the things she keeps stores of are not, and are excluded by
    # name so "what reminders do I have" still reaches its own reader.
    ("recall_owned", re.compile(
        r"^what (?:kind of |type of |make of |sort of )?(?!(?:notes?|reminders?|tasks?|lists?|meetings?|appointments?"
        r"|events?|plans?|alarms?|timers?|e?mails?|messages?|drafts?|applications?|interviews?|jobs?|time|bills?"
        r"|subscriptions?|projects?|calls?|texts?|things?|files?|documents?|approvals?)\b)"
        r"(?P<recall>[a-z][a-z '-]{1,24}?) do i (?:drive|have|own|use|ride)\s*\??$")),
    ("can_you", re.compile(
        r"^(?:can|could) (?:you|u) (?P<what>.{3,120})$"
        r"|^(?:are|r) (?:you|u) able to (?P<what2>.{3,120})$"
        r"|^do (?:you|u) know how to (?P<what3>.{3,120})$")),
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
    # CHANCE, SPELLING AND THE KITCHEN (2026-10-07, all to the planner,
    # and with nothing thinking "I could not plan that"). A coin, a die and
    # a number need randomness, not a model; spelling a word he said is its
    # letters; cups and spoons are a table.
    ("coin", re.compile(r"^(?:flip|toss) a coin$|^heads or tails$|^coin (?:flip|toss)$")),
    # Small games (2026-10-07: "pick a card" and "rock paper scissors" went
    # to the planner, which queued them for later).
    ("card", re.compile(r"^(?:pick|draw|deal me|give me) a (?:random )?card(?: any card)?$|^pick a card,? any card$")),
    ("rps", re.compile(r"^(?:let'?s play |play )?rock,? paper,? (?:or )?scissors(?:,? (?P<rps>rock|paper|scissors))?$"
                       r"|^(?P<rps2>rock|paper|scissors)!?$")),
    ("dice", re.compile(r"^roll (?:a |the )?(?P<what>\d+|two|three|four|five|six)? ?(?:dice|die|d6)$")),
    ("pick_number", re.compile(r"^(?:pick|choose|give me|think of) a (?:random )?number"
                               r"(?: (?:between|from) (?P<what>\d+ (?:and|to) \d+))?$")),
    ("spell", re.compile(r"^(?:how (?:do you|do i|to) )?spell (?:the word )?(?P<what>[a-z'-]{2,30})$")),
    ("volume", re.compile(r"^(?P<what>(?:how many (?:fluid ounces?|fl oz|teaspoons?|tsp|tablespoons?|tbsp|ounces?|oz|cups?"
                          r"|pints?|quarts?|gallons?|millilit(?:er|re)s?|ml|lit(?:er|re)s?) (?:are )?(?:in|make|is|to) "
                          r"|(?:convert|what(?:'s| is|s)?) (?:[\d.]+|half a|a half) (?:fluid ounces?|fl oz|teaspoons?|tsp"
                          r"|tablespoons?|tbsp|ounces?|oz|cups?|pints?|quarts?|gallons?|millilit(?:er|re)s?|ml|lit(?:er|re)s?) "
                          r"(?:to|in|into) ).{1,30})$")),
    # "WHAT'S DUE TODAY", "what's overdue" (2026-10-07: to the planner).
    # A task carries the deadline he said; `tasks.due` compares it to now.
    ("due", re.compile(r"^(?:what(?:'s| is|s)?|what do i have|anything|is anything|do i have anything) "
                       r"(?:(?P<what>overdue)|due(?: (?:on )?(?P<what2>today|tomorrow|this week|soon|monday|tuesday|wednesday"
                       r"|thursday|friday|saturday|sunday))?)(?: on my (?:list|tasks))?$"
                       r"|^what(?:'s| is|s)? (?P<what3>overdue)(?: on my (?:list|tasks))?$"
                       # "What tasks are due this week", "show me my overdue tasks" (2026-10-07).
                       r"|^(?:what|which) (?:tasks|things) (?:are|r) (?:due (?P<what4>today|tomorrow|this week|soon)|(?P<what5>overdue))$"
                       r"|^(?:show me|list|read me|what are|tell me) (?:my |the )?(?P<what6>overdue) (?:tasks|things|items)$"
                       r"|^(?:any|what are my|do i have any) deadlines(?: (?P<what7>today|tomorrow|this week|soon))?$")),
    # THE CALENDAR ITSELF: "what week is it", "is it a leap year".
    ("week_of_year", re.compile(r"^(?:what|which) week (?:is it|of the year is it|number is it|are we in)(?: today)?$"
                                r"|^what(?:'s| is|s)? (?:the |today's )?week number$")),
    ("leap_year", re.compile(r"^is (?:it a leap year|this a leap year|this year a leap year|(?P<what>\d{4}) a leap year)$"
                             r"|^when(?:'s| is) the (?P<what2>next) leap year$")),
    # "HOW MUCH TIME IS LEFT ON MY TIMER" (2026-10-07: to the planner). A
    # timer is a one-off reminder whose words end "timer is up"; the time
    # left is arithmetic on its due time.
    ("timer_left", re.compile(r"^(?:how (?:much (?:time|longer)|long)(?: is)? (?:left|remaining|to go)? ?(?:on|for) (?:my|the) timers?"
                              r"|how much (?:time is )?left on (?:my|the) timers?|(?:is|are) (?:my |the |a )?timers? (?:still )?(?:running|going|on)"
                              r"|how long (?:until|till|before) (?:my|the) timer(?: goes off| is up| ends)?|timer(?: status)?|check (?:my|the) timer"
                              # "How much time is left" (2026-10-07: to the planner) is the timer's.
                              r"|how much (?:time|longer) is (?:left|remaining)|how long is left"
                              # "How long left", "how long on the rice" (2026-10-07: to the planner).
                              r"|how (?:long|much time|much longer) (?:left|to go)|how much longer"
                              r"|how (?:long|much time) (?:is )?(?:left )?on the [a-z]{2,20}(?: timer)?)$")),
    # "HOW MANY WEEKS UNTIL CHRISTMAS" and "a 20% tip on 45" (2026-10-07:
    # to a model). Arithmetic on a date and on a bill.
    ("until_weeks", re.compile(r"^how many (?P<what2>weeks|months) (?:until|till|to|before) (?:the )?(?P<what>[a-z][a-z' ]{2,30}?)$")),
    ("tip", re.compile(r"^(?:what(?:'s| is|s)?|how much is|calculate) (?:a |the )?(?P<what>\d{1,2}(?:\.\d)?) ?(?:%|percent) tip on "
                       r"(?:a |an )?\$?(?P<what2>[\d,]+(?:\.\d{1,2})?)(?: dollars?| bucks)?(?: bill)?$"
                       r"|^(?:what(?:'s| is|s)? the )?tip on \$?(?P<what3>[\d,]+(?:\.\d{1,2})?)(?: dollars?| bucks)?(?: bill)?$"
                       r"|^how much (?:should i|do i) tip on (?:a |an )?\$?(?P<what4>[\d,]+(?:\.\d{1,2})?)(?: dollars?| bucks)?(?: bill)?$")),
    # "HOW MUCH IS 50 EUROS IN DOLLARS" (2026-10-07: to a model, which
    # cannot know today's rate). The ECB's published rate, or "I couldn't
    # reach it" - never a remembered number.
    ("currency", re.compile(r"^(?:how much is |what(?:'s| is|s)? |convert )?\$?(?P<what>[\d,]+(?:\.\d+)?) (?P<what2>(?:us dollars?|dollars?|bucks|usd|euros?|eur|british pounds|pounds?|gbp|quid|sterling|japanese yen|yen|jpy|canadian dollars?|cad|australian dollars?|aud|mexican pesos|pesos?|mxn|swiss francs|francs?|chf|yuan|renminbi|cny|rupees?|inr|won|krw|krona|kronor|sek))"
                            r" (?:in|to|into) (?P<what3>(?:us dollars?|dollars?|bucks|usd|euros?|eur|british pounds|pounds?|gbp|quid|sterling|japanese yen|yen|jpy|canadian dollars?|cad|australian dollars?|aud|mexican pesos|pesos?|mxn|swiss francs|francs?|chf|yuan|renminbi|cny|rupees?|inr|won|krw|krona|kronor|sek))$"
                            r"|^how many (?P<what4>(?:us dollars?|dollars?|bucks|usd|euros?|eur|british pounds|pounds?|gbp|quid|sterling|japanese yen|yen|jpy|canadian dollars?|cad|australian dollars?|aud|mexican pesos|pesos?|mxn|swiss francs|francs?|chf|yuan|renminbi|cny|rupees?|inr|won|krw|krona|kronor|sek)) (?:is|are|in|for|to) (?:a |an |one |(?P<what5>[\d,]+(?:\.\d+)?) )?(?P<what6>(?:us dollars?|dollars?|bucks|usd|euros?|eur|british pounds|pounds?|gbp|quid|sterling|japanese yen|yen|jpy|canadian dollars?|cad|australian dollars?|aud|mexican pesos|pesos?|mxn|swiss francs|francs?|chf|yuan|renminbi|cny|rupees?|inr|won|krw|krona|kronor|sek))$")),
    ("riddle", re.compile(r"^(?:tell me|give me|do you have|got|know) (?:a |another |any )?riddles?$")),
    ("count_to", re.compile(r"^count (?:to|up to) (?P<what>\d{1,2}|ten|five|three|twenty)$")),
    ("alarm_q", re.compile(r"^what time (?:did i set|is) my alarm(?: set)?(?: for)?$|^when(?:'s| is) my alarm(?: set for)?$"
                           r"|^when (?:does|will) my (?:next )?alarm go off$|^what(?:'s| is) my alarm set (?:for|to)$|^is my alarm (?:set|on)$"
                           r"|^(?:did i set|do i have) an alarm(?: (?:set|for tomorrow))?$")),
    # "HOW DO I TURN YOU OFF": the switch is his, and it is one word.
    ("off_switch", re.compile(r"^how (?:do|can) i (?:turn (?:you|u) off|stop (?:you|u)|shut (?:you|u) (?:off|down|up)|pause (?:you|u)"
                              r"|halt (?:you|u)|make (?:you|u) stop)(?: for (?:a while|now|good))?$")),
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
    # 2026-10-07: powers, roots, a joke and where he parked, each to a model.
    ("power", re.compile(
        r"^what(?:'s| is|s)? (?P<base>[\d.]+) (?:to the power of|to the|raised to(?: the power of)?|\^) (?P<exp>\d{1,3})(?:st|nd|rd|th)?(?: power)?$"
        r"|^what(?:'s| is|s)? (?P<sq>[\d.]+) (?P<sqw>squared|cubed)$"
        r"|^what(?:'s| is|s)? (?:the )?(?P<rootw>square|cube) root of (?P<root>[\d.,]+)$")),
    ("joke", re.compile(r"^(?:tell me|say|got|know|give me) (?:a |another |any )?(?:good |funny |dad )?jokes?$"
                        r"|^(?:make me laugh|tell me something funny|say something funny|cheer me up with a joke)$")),
    # "What should I have for dinner" (2026-10-07: "I can't think just
    # now"). A suggestion is not a fact, so it is said as one - and what
    # he told her he likes comes first.
    ("meal_idea", re.compile(
        r"^what (?:should|can|could|shall) (?:i|we) (?:have|eat|make|cook|get) for (?P<meal>breakfast|lunch|dinner|supper|tea)(?: tonight| today)?$"
        r"|^what(?:'s| is) for (?P<meal2>breakfast|lunch|dinner|supper)(?: tonight| today)?$"
        r"|^(?:give me |any )?(?P<meal3>breakfast|lunch|dinner|supper) ideas?$")),
    ("parked", re.compile(r"^where (?:did i|have i) park(?:ed)?(?: the car| my car)?$"
                          r"|^where(?:'s| is) (?:my|the) car(?: parked)?$")),
    # 2026-10-07, every one to a model with nothing to think about:
    ("sun", re.compile(
        r"^(?:what time|when) (?:is|does|will) (?:the )?(?P<sun>sunset|sunrise|sun (?:set|rise|go down|come up))(?: (?P<sunday>today|tonight|tomorrow))?$"
        r"|^when(?:'s| is) (?P<sun2>sunset|sunrise)(?: (?P<sunday2>today|tonight|tomorrow))?$"
        r"|^what time(?: is it| does it get) (?P<sun3>dark|light)(?: (?P<sunday3>today|tonight|tomorrow))?$"
        # "When does it get dark" (2026-10-07: to the planner).
        r"|^when (?:does|will) it get (?P<sun4>dark|light)(?: (?P<sunday4>today|tonight|tomorrow))?$"
        # "Sunrise tomorrow", "what time is sunrise tomorrow" (2026-10-07: to the planner).
        r"|^(?:what time is |what time's )?(?P<sun5>sunset|sunrise)(?: (?:time )?(?P<sunday5>today|tonight|tomorrow))?$")),
    ("moon", re.compile(
        r"^what(?:'s| is) the (?:moon(?: phase)?|phase of the moon)(?: tonight| today)?$"
        r"|^what phase is the moon(?: in)?(?: tonight| today)?$"
        r"|^is (?:it|there) a full moon(?: tonight| today)?$|^when(?:'s| is) the next (?:full|new) moon$")),
    ("discount", re.compile(
        r"^what(?:'s| is|s)? (?P<off>[\d.]+) ?(?:%|percent) off (?:of )?\$?(?P<price>[\d.,]+)(?: dollars| bucks)?$"
        r"|^\$?(?P<price2>[\d.,]+)(?: dollars)? (?:with|at|minus) (?P<off2>[\d.]+) ?(?:%|percent) off$")),
    # ARITHMETIC ON HER LAST ANSWER (2026-10-07): "what's 20% tip on 45",
    # then "split it three ways" - and "square root of 144", then "and
    # times 3" - went to the planner. The number is in what she just said.
    ("on_the_last", re.compile(
        r"^(?:and |now |then |ok |okay )?(?:(?P<op>times|multiplied by|x|divided by|over|plus|minus|add|subtract|take away|less) "
        r"(?P<n>\d[\d,]*(?:\.\d+)?)"
        r"|(?:split|divide) (?:it|that|the total|the bill|that total) (?:(?:between|among|by|for) )?(?P<ways>\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)(?: ways| people)?"
        r"|(?P<half>half|double|halve|square) (?:it|that)"
        # "Round that" after 14.2857 (2026-10-07: to the planner).
        r"|(?P<round>round) (?:it|that)(?: off| up| down)?(?: to (?:the nearest )?(?:(?P<places>\d|one|two|three) decimal places?"
        r"|(?:a |the nearest )?(?P<whole>whole number|dollar|cent|integer|ten|hundred)))?)\s*\??$")),
    # "How far is a 5k in miles" was a journey to a place called "a 5k
    # in miles" (2026-10-07).
    ("race", re.compile(
        r"^how (?:far|long|many (?:miles|km|kilometers|kilometres)) is (?:a |an )?(?P<race>\d{1,3} ?k|\d{1,3} ?km|half marathon|marathon|"
        r"\d{1,3} ?(?:mile|miler))(?: run| race)?(?: in (?:miles|km|kilometers|kilometres))?$")),
    ("split", re.compile(
        r"^(?:split|divide) \$?(?P<bill>[\d.,]+)(?: dollars| bucks)? (?P<ways>\d{1,2}|two|three|four|five|six|seven|eight|nine|ten) ways$"
        r"|^what(?:'s| is) \$?(?P<bill2>[\d.,]+)(?: dollars)? split (?P<ways2>\d{1,2}|two|three|four|five|six|seven|eight|nine|ten) ways$"
        # "Split 120 between 4" (2026-10-07: to the planner).
        r"|^(?:split|divide) (?:a |the )?\$?(?P<bill3>[\d.,]+)(?: dollars?| bucks)?(?: bill| check)? (?:between|among|by|with|for) "
        r"(?P<ways3>\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)(?: people| of us| ways| friends)?$")),
    ("area", re.compile(
        r"^(?:what(?:'s| is) the )?(?:square footage|area) of (?:a )?(?P<w>[\d.]+) by (?P<l>[\d.]+)(?: room| foot room)?$"
        r"|^how many square feet is (?:a )?(?P<w2>[\d.]+) by (?P<l2>[\d.]+)(?: room)?$")),
    ("year_left", re.compile(
        r"^how many (?P<unit>days|weeks|months) (?:are )?(?:left|remaining) (?:in|of|until the end of) (?:the|this) year$")),
    ("weekday_of", re.compile(
        r"^what day (?:of the week )?(?:was|is|will be|falls on|did) (?!it\b|today\b|tomorrow\b)(?P<wd>.+?)(?: (?:fall on|on|be))?$")),
    # 2026-10-07, each to the planner: "how many days since January 1", "is
    # it the weekend", "what's 3 weeks from today", "how old is someone born
    # in 1990". Arithmetic on the calendar, nothing to think about.
    ("days_since", re.compile(
        r"^how (?:many days|long) (?:has it been |is it |have i been |since )?since (?P<since>.+?)\s*\??$"
        # "How long ago was January 1" (2026-10-07: to the planner).
        r"|^how (?:long|many days) ago (?:was|is|did) (?P<since2>.+?)\s*\??$")),
    ("weekend_q", re.compile(r"^is (?:it|today) (?:a |the )?weekend(?: yet| today)?\s*\??$"
                             # "Is today a weekday" (2026-10-07: to the planner).
                             r"|^is (?:it|today) a (?P<wkday>weekday|work ?day|working day|school day|business day)(?: today)?\s*\??$")),
    # "HOW OLD IS JENNA" (2026-10-07: to the planner) - from the birthday
    # he told her. A name she holds nothing about goes on to a model,
    # which may well know how old a famous person is.
    ("age_of", re.compile(
        r"^(?:how old (?:is|will) |what age (?:is|will) )(?P<age_of>(?:my )?[a-z][a-z'-]{1,20}(?: (?!be\b|turn\b)[a-z][a-z'-]{1,20})?)"
        r"(?: be| turn| be turning)?(?: this year| next)?\s*\??$")),
    ("took_today", re.compile(
        r"^(?:did|have) i (?:take|taken|had|have) (?:my )?(?:morning |evening |night |daily )?(?P<took>medicine|meds|medication|pills?|vitamins?"
        r"|insulin|inhaler|antibiotics?|[a-z]+ pills?)(?: today| this morning| tonight| yet| already)?\s*\??$"
        r"|^when did i (?:last )?take my (?P<took2>medicine|meds|medication|pills?|vitamins?|insulin)\s*\??$")),
    ("born_in", re.compile(r"^how old (?:is|would be) (?:someone|somebody|a person|anyone) (?:who was )?born in (?P<born>\d{4})\s*\??$")),
    ("days_between", re.compile(
        r"^how many days (?:are there )?(?:between|from) (?P<d1>.+?) (?:and|to|until) (?P<d2>.+)$")),
    ("time_diff", re.compile(
        r"^what(?:'s| is) the time difference (?:with|to|between (?:me|here|us) and) (?P<tz>[a-z][a-z .'-]{1,40})$"
        r"|^how many hours (?:ahead|behind) is (?P<tz2>[a-z][a-z .'-]{1,40})$")),
    # 2026-10-07: sums said in words, each to a model with nothing to think
    # about. LAST, so every narrower pattern above keeps its sentence.
    ("arith", re.compile(
        r"^(?:what(?:'s| is|s)?|calculate|compute|how much is) (?P<expr>[\d.,]+(?: (?:plus|minus|times|multiplied by|divided by|over|x|\+|-|\*|/) [\d.,]+){2,6})$"
        # "What's 1000 divided by 3 rounded" (2026-10-07: to a model)
        r"|^(?:what(?:'s| is|s)?|calculate|compute|how much is) (?P<expr2>[\d.,]+(?: (?:plus|minus|times|multiplied by|divided by|over|x|\+|-|\*|/) [\d.,]+){1,6}),?"
        r" rounded(?: off| (?P<rdir>up|down))?(?: to (?:the nearest )?(?:(?P<rplaces>\d|one|two|three) decimal places?|(?:a )?whole number))?$")),
    # "7 factorial", "12 dozen", "50 minus 15 percent" (2026-10-07: to a model)
    ("arith_more", re.compile(
        r"^(?:what(?:'s| is|s)? |how much is |calculate )?(?P<fact>\d{1,2}) ?(?:factorial|!)$"
        r"|^(?:what(?:'s| is|s)? |how much is |how many is )?(?P<dozen>[\d.]+|a|half a) dozen$"
        r"|^(?:what(?:'s| is|s)? |how much is |calculate )?\$?(?P<base>[\d.,]+) (?P<pm>plus|minus|\+|-) (?P<pcent>[\d.]+) ?(?:%|percent)$")),
    # "What's half of 3 and a quarter", "double 2 and a half cups", "3/4
    # plus 1/2" (2026-10-07: each to a model) - kitchen sums in fractions.
    ("fractions", re.compile(
        r"^(?:what(?:'s| is|s)? |how much is )?(?:half|a half|a third|one third|a quarter|one quarter|two thirds|three quarters"
        r"|double|triple|twice|three times) (?:of )?" + _QTY + r"(?: " + _KITCHEN_UNIT + r")?$"
        r"|^(?:what(?:'s| is|s)? |how much is )?" + _QTY + r" (?:plus|minus|times|divided by|\+|-) " + _QTY
        + r"(?: " + _KITCHEN_UNIT + r")?$")),
    ("prime", re.compile(r"^is (?P<prime>\d{1,12}) (?:a )?prime(?: number)?$")),
    ("average", re.compile(r"^(?:what(?:'s| is) )?(?:the )?(?:average|mean) of (?P<nums>[\d., ]+(?:,? and [\d.]+)?)$")),
    # 2026-10-07, each to the planner: "what percent is 30 of 120", "what's
    # 3/4 as a decimal", "what's 1000 in roman numerals", "5 feet 10 in cm".
    ("pct_of", re.compile(
        r"^what (?:percent|percentage|%) (?:is|of) (?P<pa>[\d.,]+) (?:of|out of) (?P<pb>[\d.,]+)\s*\??$"
        r"|^(?P<pa2>[\d.,]+) is what (?:percent|percentage|%) of (?P<pb2>[\d.,]+)\s*\??$"
        r"|^what(?:'s| is) (?P<pa3>[\d.,]+) out of (?P<pb3>[\d.,]+)(?: as a percent(?:age)?)?\s*\??$")),
    ("fraction_dec", re.compile(r"^what(?:'s| is) (?P<fnum>\d+)/(?P<fden>\d+) (?:as a |in )?decimals?\s*\??$")),
    ("roman", re.compile(
        r"^(?:what(?:'s| is) )?(?P<arabic>\d{1,4}) in roman(?: numerals?)?\s*\??$"
        r"|^(?:what(?:'s| is) |what number is )?(?P<numeral>[mdclxvi]{1,15})(?: in roman numerals)?(?: in numbers| as a number)\s*\??$")),
    ("height_cm", re.compile(
        r"^(?:convert |what(?:'s| is) |how (?:many|much) (?:cm|centimeters|centimetres) is )?(?P<ft>\d) (?:feet|foot|ft)"
        r"(?: (?:and )?(?P<inch>\d{1,2}(?:\.\d)?) (?:inches|inch|in))?(?: (?:to|in|into) (?:cm|centimeters|centimetres|meters|metres))?\s*\??$")),
    ("round_to", re.compile(r"^round (?P<rn>[\d.]+) to (?:the nearest )?(?P<places>\d|one|two|three|whole number|integer)(?: decimals?)?(?: places?)?(?: points?)?$")),
    ("time_units", re.compile(
        r"^how many (?P<small>seconds|minutes|hours|days|weeks) (?:are )?in (?:a |an |one )?(?P<count>\d+(?:\.\d+)? )?(?P<big>minutes?|hours?|days?|weeks?|years?)$")),
    ("fraction_pct", re.compile(r"^what(?:'s| is) (?P<num>\d+)/(?P<den>\d+) (?:as a |in )?percent(?:age)?$")),
    ("feeling", re.compile(
        r"^(?:i(?:'m| am)(?: feeling)?|im(?: feeling)?|i feel|feeling) (?:so |really |kind of |pretty |a bit |very )?"
        r"(?P<feel>hungry|bored|tired|exhausted|sleepy|stressed|stressed out|overwhelmed|anxious|sad|down|lonely|sick)(?: today)?$"
        r"|^(?P<feel2>i can'?t sleep|i need a break|motivate me|i'?m having a (?:bad|rough|hard) day|i had a (?:bad|rough|hard|long) day"
        r"|(?:give me|i need) a pep talk|pep talk|i need (?:some )?motivation|say something nice|cheer me up|make me smile"
        # "I have a headache" (2026-10-07: to a model) is "I'm sick".
        r"|i(?:'ve| have)(?: got)? (?:a |an )?(?:headache|migraine|cold|fever|flu|the flu|sore throat|stomach ?ache|cough)"
        r"|i (?:don'?t|do not) feel (?:so |very )?(?:good|well|great))$")),
    # 2026-10-07: the weather asked sideways, each to a model while the
    # forecast was one call away. LAST, so the main weather pattern keeps
    # every sentence it already had.
    ("weather_more", re.compile(
        r"^(?:what(?:'s| is|s)? )?(?:the )?(?:weather|forecast)(?: like)? (?:on|for) (?P<wm>today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^what(?:'s| is|s)? the forecast(?: (?P<wm2>today|tonight|tomorrow))?$"
        r"|^(?:is|will) it (?:going to )?(?:rain|snow|storm)(?: later)?$"
        r"|^how (?:hot|cold|warm) (?:will it be|is it going to be|is it)(?: outside)?(?: (?P<wm3>today|tonight|tomorrow))?$"
        r"|^what should i wear(?: (?P<wm4>today|tonight|tomorrow))?$"
        r"|^do i need (?:a jacket|a coat|sunscreen|boots)(?: (?P<wm5>today|tonight|tomorrow))?$"
        # 2026-10-07, each to the planner.
        r"|^how much rain (?:is there going to be |will there be |are we getting |is coming )?(?:(?P<wm6>today|tonight|tomorrow))?$"
        r"|^what(?:'s| is|s) the chance of (?:rain|snow)(?: (?P<wm7>today|tonight|tomorrow))?$"
        r"|^(?:is|will) it (?:be |going to be )?(?:windy|sunny|cloudy|humid|nice out|nice outside)(?: (?P<wm8>today|tonight|tomorrow))?$")),
    ("fun_fact", re.compile(r"^(?:tell me|give me|got|know) (?:a |another |any )?(?:fun |random |cool |interesting )?facts?$"
                            r"|^tell me something (?:interesting|cool)$")),
    ("quote", re.compile(r"^(?:give me|tell me|say|read me) (?:a |another )?(?:quote|motivational quote|inspiring quote)$"
                         r"|^(?:quote of the day|what's the quote of the day)$")),
    # SUMS AND CALENDAR ARITHMETIC, 2026-10-07 with every model off: square
    # roots, "how many ounces in a pound", "what day of the week was july 4
    # 1990", "how many days between march 1 and april 15", "what time will it
    # be in 3 hours". `reckon` answers or returns None, which sends the
    # question on - the shapes here only decide who looks first. LAST in the table, so
    # every older, narrower answer looks before it.
    # "How many days left in the month" (2026-10-07): the reckon pattern
    # took it as a unit sum and found none.
    ("days_left", re.compile(
        r"^how many (?:more )?(?:days|weeks) (?:are )?(?:left|remaining|to go|are there left) (?:in|of|until the end of) "
        r"(?:the |this )?(?P<days_left>month|year)$"
        r"|^how many (?:days|weeks) (?:until|till|to) the end of (?:the |this )?(?P<days_left2>month|year)$")),
    ("reckon", re.compile(
        r"^(?:what(?:'s| is|s)? |whats |calculate |work out )?(?:the )?(?:square|cube) root of -?[\d.,]+$"
        r"|^(?:what(?:'s| is|s)? |whats )?-?[\d.,]+ (?:squared|cubed|to the power of -?[\d.,]+|to the -?[\d.,]+(?:th|st|nd|rd)?(?: power)?)$"
        r"|^(?:what(?:'s| is|s)? |whats )?(?:half|a half|a third|one third|a quarter|one quarter|a fifth|a tenth|double|twice|triple"
        r"|three quarters|two thirds) (?:of )?-?[\d.,]+$"
        r"|^how many [a-z ]{1,14} (?:are |is )?(?:in|to|make|per) (?:a |an |one )?[\d.,]* ?[a-z ]{1,14}$"
        r"|^(?:convert |what(?:'s| is|s) )?(?:[\d.,]+|a|an|one|half an?) (?:teaspoons?|tablespoons?|tsp|tbsp|cups?|pints?|quarts?"
        r"|gallons?|ml|milli(?:liter|litre)s?|lit(?:er|re)s?|ounces?|oz|fl oz|fluid ounces?|grams?|g|stones?|kilos?)"
        r" (?:to|in|into) [a-z ]{1,16}$"
        r"|^what day(?: of the week)? (?:is|was|will|does|did|falls|is it on)(?: it)? .{3,40}$"
        r"|^how many (?:days|weeks) (?:are there )?(?:between|from) .{3,30} (?:and|to|until|till) .{3,30}$"
        r"|^what time (?:will it be|is it going to be|would it be|is it) in (?:an? |one )?(?:[\d.]+|half an?|a couple of"
        r"|two|three|four|five|six|ten|twelve)? ?(?:hours?|minutes?|mins?)$"
        # "What's 30 minutes from now" (2026-10-07: to a model)
        r"|^(?:what(?:'s| is|s)? |what time is |whats )(?:an? |one )?(?:[\d.]+|half an?|a couple of"
        r"|two|three|four|five|six|ten|twelve)? ?(?:hours?|minutes?|mins?) from now$"
        r"|^what time was it (?:an? |one )?(?:[\d.]+|half an?|a couple of"
        r"|two|three|four|five|six|ten|twelve)? ?(?:hours?|minutes?|mins?) ago$")),
    # A PLACE HE SAVED, read back (2026-10-07: "where is the gym" was a
    # FILE search; "what's my work address" had nowhere to look). LAST, so
    # every other "where is"/"what's my" shape keeps its own answer.
    ("place_where", re.compile(
        r"^(?:where(?:'s| is) (?:my |the )?|what(?:'s| is|s) the address (?:of|for) (?:my |the )?)(?P<place_w>[a-z][a-z' ]{1,30}?)\s*\??$"
        r"|^what(?:'s| is|s) (?:my |the )(?P<place_w2>[a-z][a-z' ]{1,30}?) address\s*\??$")),
)


def _direct(text: str) -> str:
    """"Tell me the time", "do you know what time it is" -> the question
    itself. Both went to a model, and "do you know what time it is" was a
    memory search for "what time it is" (2026-10-07). An embedded question
    puts the verb last; this puts it back."""
    m = re.fullmatch(r"(?:do (?:you|u) know|tell me|can (?:you|u) tell me|could (?:you|u) tell me|please tell me)"
                     r" (?P<wh>what|when|where|who|how (?:much|many|long|far|old|hot|cold)|which \w+|what \w+)"
                     r" (?P<subj>.+?) (?P<verb>is|are|was|were)(?P<tail> like| at| for| from)?", text)
    if m:
        wh, subj = m.group("wh"), m.group("subj")
        # "What time it is": the noun goes with the question word.
        pron = re.fullmatch(r"(?P<n>\w+) (?P<p>it|there|this|that)", subj)
        if pron and wh in ("what", "which"):
            return f"{wh} {pron.group('n')} {m.group('verb')} {pron.group('p')}"
        return f"{wh} {m.group('verb')} {subj}{m.group('tail') or ''}"
    m = re.fullmatch(r"(?:tell me|can (?:you|u) tell me|could (?:you|u) tell me|please tell me|give me) "
                     r"(?P<what>(?:the|my|today's|tomorrow's) .{2,60})", text)
    if m and not re.match(r"(?:the|my) (?:news|headlines|story|joke|truth|answer)\b", m.group("what")):
        return f"what's {m.group('what')}"
    return text


def match(question: str) -> tuple[str, str] | None:
    """(which answer, the captured remainder) — or None to think properly."""
    text = _tidy(question)
    if not text or len(text) > MAX_QUESTION:
        return None
    direct = _direct(text)
    if direct != text:
        found = match(direct)
        if found:
            return found
    for name, pattern in PATTERNS:
        found = pattern.match(text)
        if not found:
            continue
        captured = found.groupdict()
        if name == "status_of":
            return name, text
        if name in ("math", "farewell", "power", "fact_q", "note_search", "sun", "moon", "discount", "split",
                    "area", "year_left", "weekday_of", "days_between", "time_diff", "feeling", "about_her", "arith",
                    "prime", "average", "round_to", "time_units", "fraction_pct", "weather_more", "free_at", "reckon",
                    "weather_in"):
            return name, text
        if name in ("until_weeks", "days_left", "age_in", "race", "logged", "rps", "arith_more", "fractions", "did_last", "tip", "currency", "date_after", "next_detail", "day_span", "on_the_last",
                    "time_convert", "pct_of", "fraction_dec", "roman", "height_cm", "asked_last"):
            return name, text
        rest = next((captured[k] for k in ("what", "what2", "what3", "what4", "what5", "what6", "mine",
                                           "free", "free2", "free3",
                                           "down", "down2", "weather",
                                           "weather2", "weather3", "weather4", "weather5", "weather6", "weather7", "weather8", "weather9", "weather10", "weather11",
                                           "day", "day2", "day3", "day4", "day5", "day6", "day7",
                                           "outcome", "outcome2", "outcome3", "outcome4", "outcome5", "outcome6",
                                           "until", "until2", "day8", "day9", "day10", "day11", "weeks", "due", "due2", "due3",
                                           "cal", "cal2", "cal3", "cal4", "cal5", "cal6", "holiday_on", "holiday_list", "holiday_list2", "place_w", "place_w2", "place_a", "did_v", "did_o", "did_v2", "did_o2", "did_today", "wkday", "bwin", "bwin2", "bday", "meal", "meal2", "meal3", "due", "due2", "due3", "workdays", "agenda_on", "since", "since2", "born", "age_of", "took", "took2",
                                           "why_not", "why_not2", "why_not3",
                                           "sent_window", "sent_window2",
                                           "repo_wrong", "repo_wrong2", "time_in", "time_in2",
                                           "time_in3", "time_in4", "time_in5", "date_of", "date_of2", "date_of3",
                                           "recall", "recall2", "recall3", "recall4", "recall5", "recall6", "recall7", "recall8", "recall9", "recall10", "recall11", "recall12", "owe_who", "owe_amt", "define", "define2", "need_q", "who_named", "coming", "coming2", "coming3", "coming4", "coming5", "clock_until", "notes_day", "notes_day2", "when_mine", "reminders_on", "reminders_on2", "reminders_on3", "ran",
                                           "has", "has2",
                                           "date_ahead", "date_ahead2", "date_ahead3", "date_ahead4", "found_window",
                                           "hold_q", "hold_q2", "hold_q3", "hold_q4",
                                           "draft_to", "draft_to2", "draft_to3",
                                           "applied_on", "applied_on2", "applied_on3", "what3", "what7", "lastday", "lastday2", "lastday3",
                                           "asked_on", "asked_on2", "asked_on3", "asked_on4", "asked_on5", "day_part",
                                           "place", "place2", "place3")
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


OFF_SWITCH = ("Say \"stop\" or \"halt\" and nothing I do runs until you say \"resume\". "
              "\"Announcements off\" keeps me from speaking up on my own, and \"turn off the microphone\" stops me listening.")


_HOLIDAY_NAMES = ("New Year's Day", "MLK Day", "Presidents' Day", "Valentine's Day", "Easter", "Mother's Day",
                  "Memorial Day", "Father's Day", "Independence Day", "Labor Day", "Columbus Day", "Halloween",
                  "Thanksgiving", "Christmas Eve", "Christmas", "New Year's Eve")


_COUNT_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "half a": 0.5}


def _logged(text: str) -> str | None:
    """What he told her he drank, ran, slept or did, added up from his notes."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("logged", text)
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    window = (g.get("logged_w") or g.get("logged_w2") or g.get("logged_w3") or " today").strip()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "this week":
        start -= dt.timedelta(days=now.weekday())
    rows = []
    for row in _notes():
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        rows.append((at, " ".join(str(row.get("text") or "").casefold().split())))
    when = "today" if window == "today" else "this week"

    def amount(word):
        return float(word) if re.fullmatch(r"\d+(?:\.\d+)?", word) else _COUNT_WORDS.get(word)
    if g.get("logged_drink"):
        drink = g["logged_drink"]
        total, unit = 0.0, "glass"
        for at, said in rows:
            m = re.match(rf"i (?:drank|had) (\w+) (glass(?:es)?|cups?|bottles?|mugs?|cans?) of {drink}\b", said)
            if m and at >= start and amount(m.group(1)):
                total += amount(m.group(1))
                unit = {"glasses": "glass"}.get(m.group(2), m.group(2) if m.group(2) == "glass" else m.group(2).rstrip("s"))
        if not total:
            return f"You haven't told me about any {drink} {when}. Say \"I drank a glass of {drink}\" and I'll keep count."
        plural = {"glass": "glasses"}.get(unit, unit + "s")
        return f"{_plain(total)} {unit if total == 1 else plural} of {drink} {when}."
    if g.get("logged_move"):
        verb = {"run": "ran", "walk": "walked", "jog": "jogged", "bike": "biked", "cycle": "cycled",
                "swim": "swam", "swum": "swam", "hike": "hiked"}.get(g["logged_move"], g["logged_move"])
        miles = 0.0
        found = False
        for at, said in rows:
            m = re.match(rf"i {verb} (\d+(?:\.\d+)?|\w+(?: a)?) ?(miles?|km|kilometers?|kilometres?|k)\b", said)
            if m and at >= start and amount(m.group(1)):
                found = True
                miles += amount(m.group(1)) / (1 if m.group(2).startswith("mile") else 1.609344)
        if not found:
            return f"You haven't told me about a {g['logged_move'].rstrip('ed')} {when}. Say \"I {verb} 3 miles\" and I'll add it up."
        return f"{_plain(round(miles, 2))} mile{'s' if round(miles, 2) != 1 else ''} {when}."
    if g.get("logged_sleep"):
        for at, said in rows:
            m = re.match(r"i slept (?:for )?(\S+)( and a half)? hours?", said)
            if m and amount(m.group(1)):
                hours = amount(m.group(1)) + (0.5 if m.group(2) else 0)
                return f"{_plain(hours)} hours, you told me {speech.humanize_time(at.isoformat())}."
        return "You haven't told me how you slept. Say \"I slept 7 hours\" and I'll remember."
    if g.get("logged_did"):
        stem = re.match(r"(?:work|exercise|meditat|stretch|yoga|gym)", re.sub(r"^(?:done |did |gone to the |go to the )", "", g["logged_did"]))
        key = stem.group(0) if stem else g["logged_did"]
        for at, said in rows:
            if at >= start and re.match(r"i (?:worked out|exercised|meditated|stretched|did yoga|went to the gym)", said) and key[:4] in said:
                clock = at.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
                return f"Yes - you told me at {clock}{'' if at.date() == now.date() else ' on ' + at.strftime('%A')}: {as_said(said)}."
        return f"Not that you've told me {when}."
    return None


def as_said(said: str) -> str:
    from aletheia import speech
    return speech.as_she_says_it(said)


def _workdays_until(words: str) -> str | None:
    """Monday-to-Friday days from tomorrow up to (not including) the date."""
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    when = _named_date(words, today) or _his_date(words, today)
    if when is None or when <= today:
        return None
    days = sum(1 for n in range(1, (when - today).days) if (today + dt.timedelta(days=n)).weekday() < 5)
    said = when.strftime("%A %d %B").replace(" 0", " ")
    return f"{days} weekday{'s' if days != 1 else ''} between now and {said}, not counting today or that day."


def _holiday_next(which: str = "") -> str | None:
    """The next holiday, or whether today or tomorrow is one."""
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    dated = sorted((d, name) for name in _HOLIDAY_NAMES if (d := _named_date(name, today)) is not None)
    if not dated:
        return None
    if which in ("today", "it", "tomorrow"):
        day = today + dt.timedelta(days=1 if which == "tomorrow" else 0)
        on = [name for d, name in dated if d == day]
        said = "today" if day == today else "tomorrow"
        if on:
            return f"Yes - {said} is {on[0]}."
        when, name = next((d, n) for d, n in dated if d > day)
        return f"No. The next one is {name}, {when.strftime('%A')} {when.day} {when.strftime('%B')}."
    if which == "list":
        from aletheia import speech
        said = [f"{name} on {d.strftime('%A')} {d.day} {d.strftime('%B')}" for d, name in dated[:3]]
        return f"Coming up: {speech.and_list(said)}."
    when, name = dated[0]
    away = (when - today).days
    lead = "today" if away == 0 else "tomorrow" if away == 1 else f"in {away} days"
    return f"{name}, {lead} - {when.strftime('%A')} {when.day} {when.strftime('%B')}."


def _until_weeks(text: str) -> str | None:
    import datetime as dt
    from aletheia import localtime
    m = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "until_weeks"), None)
    if not m:
        return None
    today = dt.datetime.now(localtime.operator_tz()).date()
    when = _named_date(m.group("what"), today) or _his_date(m.group("what"), today)
    if when is None:
        return None
    days = (when - today).days
    said = when.strftime("%A %d %B").replace(" 0", " ")
    if m.group("what2") == "weeks" or days < 45:
        weeks, extra = divmod(days, 7)
        span = (f"{weeks} week{'s' if weeks != 1 else ''}" + (f" and {extra} day{'s' if extra != 1 else ''}" if extra else "")
                if weeks else f"{days} day{'s' if days != 1 else ''}")
    else:
        months = round(days / 30.44, 1)
        span = f"about {months:g} month{'s' if months != 1 else ''}"
    return f"{span[0].upper()}{span[1:]} - {said}."


def _tip(text: str) -> str | None:
    m = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "tip"), None)
    if not m:
        return None
    bill = float((m.group("what2") or m.group("what3") or m.group("what4")).replace(",", ""))
    if m.group("what"):
        pct = float(m.group("what"))
        tip = bill * pct / 100
        return f"${tip:,.2f}, so ${bill + tip:,.2f} in all."
    rows = [f"{p}% is ${bill * p / 100:,.2f}" for p in (15, 18, 20)]
    return "On $" + f"{bill:,.2f}: " + ", ".join(rows[:-1]) + f", and {rows[-1]}."


def _currency(text: str) -> str | None:
    from aletheia import fx
    m = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "currency"), None)
    if not m:
        return None
    if m.group("what2"):
        amount, base, to = m.group("what"), fx.code_of(m.group("what2")), fx.code_of(m.group("what3"))
    else:
        amount, base, to = m.group("what5") or "1", fx.code_of(m.group("what6")), fx.code_of(m.group("what4"))
    if not base or not to or base == to:
        return None
    return fx.spoken(float(amount.replace(",", "")), base, to)


RIDDLES = (
    "What has keys but can't open locks? A piano.",
    "What gets wetter the more it dries? A towel.",
    "What has a neck but no head? A bottle.",
    "What can you catch but not throw? A cold.",
    "What has hands but can't clap? A clock.",
    "The more of this there is, the less you see. What is it? Darkness.",
)


def _riddle() -> str:
    import secrets
    return secrets.choice(RIDDLES)


def _count_to(n: str) -> str | None:
    top = {"ten": 10, "five": 5, "three": 3, "twenty": 20}.get(n) or int(n)
    if not 1 <= top <= 20:
        return None
    return ", ".join(str(i) for i in range(1, top + 1)) + "."


def _alarms() -> str | None:
    """His wake-ups: the reminders whose words are "wake up"."""
    try:
        from aletheia import intercom, scheduler
        rows = [s for s in scheduler.all_schedules()
                if s.get("enabled") and "wake up" in str((s.get("command") or {}).get("text") or "").casefold()]
        said = [intercom._reminder_words(s) for s in rows]
    except Exception:
        return None
    said = [re.sub(r"^wake up\s*[—-]\s*", "", s) for s in said if s]
    if not said:
        return "No alarm set. Say \"wake me up at 7\" and I'll set one."
    from aletheia import speech
    return f"{speech.count_phrase(len(said), 'alarm')}: " + speech.and_list(said) + "."


def _his_date(words: str, today):
    """"My birthday": the date he told her, next time it comes round."""
    w = " ".join(str(words or "").casefold().split()).strip(" ?.")
    if w not in ("my birthday", "birthday"):
        return _date_in_notes(w, today)
    try:
        from aletheia import memory
        said = str(memory.recall("identity", "birthday") or "")
    except Exception:
        return None
    return _named_date(said, today) if said else None


def _date_in_notes(words: str, today):
    """"Our anniversary", "my wife's birthday", "the wedding": the date a
    note of his gives it, next time it comes round (2026-10-07: "how long
    until our anniversary" went to a model a turn after he said it)."""
    w = re.sub(r"^(?:my|our|the) ", "", " ".join(str(words or "").casefold().split()))
    if not w or len(w) > 40:
        return None
    rel = re.match(r"(?P<rel>[a-z]+)'s (?P<what>.+)", w)
    asks = [w]
    if rel:
        name = _name_for_relation(rel.group("rel"))
        if name:
            asks.append(f"{name.casefold()}'s {rel.group('what')}")
    month_re = "|".join(_MONTHS)
    date_re = (rf"(?P<d>(?:{month_re})\.? \d{{1,2}}(?:st|nd|rd|th)?|\d{{1,2}}(?:st|nd|rd|th)? (?:of )?(?:{month_re}))")
    for ask in asks:
        words_ = [x for x in re.findall(r"[a-z0-9]+", ask) if x not in ("s", "is", "the", "a")]
        for row in _notes():
            said = " ".join(str(row.get("text") or "").casefold().split())
            if not all(re.search(rf"\b{re.escape(x)}", said) for x in words_):
                continue
            m = re.search(date_re, said)
            if m:
                found = _named_date(re.sub(r"(?<=\d)(?:st|nd|rd|th)", "", m.group("d")).replace(" of ", " "), today)
                if found:
                    return found
    return None


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
    # The other holidays that move (2026-10-07: "when is labor day" went to
    # a model). (month, weekday, nth; -1 is the last one.)
    w = w.replace("’", "'")
    floating = {"labor day": (9, 0, 1), "labour day": (9, 0, 1), "memorial day": (5, 0, -1),
                "mlk day": (1, 0, 3), "martin luther king day": (1, 0, 3), "presidents day": (2, 0, 3),
                "presidents' day": (2, 0, 3), "president's day": (2, 0, 3), "mother's day": (5, 6, 2),
                "mothers day": (5, 6, 2), "father's day": (6, 6, 3), "fathers day": (6, 6, 3),
                "columbus day": (10, 0, 2), "indigenous peoples day": (10, 0, 2),
                "indigenous peoples' day": (10, 0, 2)}
    if w in floating:
        month, weekday, nth = floating[w]
        for year in (today.year, today.year + 1):
            if nth > 0:
                first = dt.date(year, month, 1)
                when = first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
            else:
                last = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
                when = last - dt.timedelta(days=(last.weekday() - weekday) % 7)
            if when >= today:
                return when
    if w in ("easter", "easter sunday"):
        for year in (today.year, today.year + 1):
            a, b, c = year % 19, year // 100, year % 100
            d, e = b // 4, b % 4
            f = (b + 8) // 25
            g = (b - f + 1) // 3
            h = (19 * a + b - d - g + 15) % 30
            i, k = c // 4, c % 4
            l = (32 + 2 * e + 2 * i - h - k) % 7
            m = (a + 11 * h + 22 * l) // 451
            when = dt.date(year, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)
            if when >= today:
                return when
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if w in days:
        ahead = (days.index(w) - today.weekday()) % 7
        return today + dt.timedelta(days=ahead or 7)
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
    # The US zones by the names he says them with (2026-10-07: "convert
    # 3pm est to pst" went to the planner).
    "eastern": "America/New_York", "eastern time": "America/New_York", "est": "America/New_York",
    "edt": "America/New_York", "et": "America/New_York",
    "central": "America/Chicago", "central time": "America/Chicago", "cst": "America/Chicago", "cdt": "America/Chicago",
    "mountain": "America/Denver", "mountain time": "America/Denver", "mst": "America/Denver", "mdt": "America/Denver",
    "pacific": "America/Los_Angeles", "pacific time": "America/Los_Angeles", "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles", "pt": "America/Los_Angeles",
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


def _time_there() -> str | None:
    """The clock in the place he just asked about."""
    prev = _previous_ask(questions_only=True)
    found = match(prev) if prev else None
    if found and found[0] in ("time_in", "weather_in") and found[1]:
        return _time_in(found[1])
    return None


def _time_convert(text: str) -> str | None:
    """A clock time in one zone, said in another. His own zone when he names
    only one. A zone she does not know goes on to a model."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    from aletheia import localtime
    g = _groups("time_convert", text)
    if g.get("t2"):
        bare = g["t2"].strip()
        if re.fullmatch(r"\d{1,2}", bare):
            bare += " pm" if 1 <= int(bare) <= 7 else " am" if int(bare) <= 11 else " pm"
        g = {"t": bare, "to": g["to2"]}
    def zone_of(words):
        key = " ".join(str(words or "").casefold().split())
        if key in ("", "here", "my time", "local", "local time", "mine"):
            return localtime.operator_tz(), "your time"
        name = _ZONES.get(key) or _ZONES.get(re.sub(r" time$", "", key))
        if not name:
            return None, key
        if len(key) <= 3 and name.startswith("America/"):
            return ZoneInfo(name), key.upper()
        if key.split()[0] in ("eastern", "central", "mountain", "pacific"):
            return ZoneInfo(name), key.split()[0].title() + " time"
        return ZoneInfo(name), "in " + (key.upper() if key in ("uk", "uae", "nyc", "dc", "la", "utc", "gmt") else key.title())
    src, src_name = zone_of(g.get("from"))
    dst, dst_name = zone_of(g.get("to"))
    if src is None or dst is None:
        return None
    raw = g.get("t") or ""
    if raw in ("noon", "midnight"):
        hour, minute = (12, 0) if raw == "noon" else (0, 0)
    else:
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))? ?(am|pm)", raw)
        if not m:
            return None
        hour, minute = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0), int(m.group(2) or 0)
        if hour > 23 or minute > 59:
            return None
    today = dt.datetime.now(src).date()
    at = dt.datetime.combine(today, dt.time(hour, minute), tzinfo=src).astimezone(dst)
    def clock(t):
        return t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").replace("AM", "am").replace("PM", "pm")
    shift = (at.date() - today).days
    day = " the next day" if shift > 0 else (" the day before" if shift < 0 else "")
    said_from = clock(dt.datetime.combine(today, dt.time(hour, minute)))
    return f"{said_from} {src_name} is {clock(at)} {dst_name}{',' if day else ''}{day}."


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


def _date_of(words: str) -> str | None:
    """The date a named day comes to: "next Friday", "Christmas"."""
    import datetime as dt
    from aletheia import localtime
    w = " ".join(str(words or "").casefold().split()).strip(" ?.")
    for lead in ("next ", "this "):
        if w.startswith(lead):
            w = w[len(lead):]
    try:
        today = dt.datetime.now(localtime.operator_tz()).date()
    except Exception:
        today = dt.date.today()
    when = _named_date(w, today)
    if when is None:
        return None
    day = when.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    said = f"{when.strftime('%A')} the {day}{suffix} of {when.strftime('%B')}"
    if when.year != today.year:
        said += f" {when.year}"
    return said + "."


def _tasks_due(which: str = "") -> str | None:
    """His open tasks with a deadline inside the window he named."""
    import datetime as dt
    from aletheia import intercom, localtime, speech, tasks as tasks_mod
    try:
        rows = intercom._open_tasks()
    except Exception:
        return None
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    which = " ".join(str(which or "").split())
    end_of = lambda day: dt.datetime.combine(day, dt.time(23, 59, 59), tzinfo=tz)
    if which in ("today", "tomorrow", "this week"):
        which = "due " + which
    overdue_only = which in ("overdue", "late", "past due", "")
    limit = {"due today": end_of(now.date()), "due tomorrow": end_of(now.date() + dt.timedelta(days=1)),
             "due this week": end_of(now.date() + dt.timedelta(days=6 - now.weekday())),
             "due soon": now + dt.timedelta(days=3)}.get(which, now + dt.timedelta(days=7))
    dated = []
    for task in rows:
        when = tasks_mod.parse_deadline(task.get("deadline"))
        if when is None:
            continue
        if (when < now) if overdue_only else (when <= limit):
            dated.append((when, task))
    dated.sort(key=lambda pair: pair[0])
    if not dated:
        undated = len(rows) - sum(1 for t in rows if tasks_mod.parse_deadline(t.get("deadline")))
        lead = "Nothing's overdue." if overdue_only else "Nothing's due " + (
            which[4:] if which.startswith("due ") else "in the next week") + "."
        if rows and undated == len(rows):
            return lead + f" {speech.count_phrase(len(rows), 'task')} on your list, none with a date."
        if rows:
            return lead + f" {speech.count_phrase(len(rows), 'task')} open on your list in all."
        return lead
    late = [t for w, t in dated if w < now]
    # "1 thing due: call the bank due tomorrow" said the day twice
    # (2026-10-07). Asked about one day, the day is the head and each task
    # is just what it is.
    one_day = which in ("due today", "due tomorrow") and not late
    said = speech.and_list([str(t.get("description") or t.get("id")).strip().rstrip(".") if one_day
                            else intercom._task_words(t) for _w, t in dated[:5]])
    more = f", and {len(dated) - 5} more" if len(dated) > 5 else ""
    head = (f"{speech.count_phrase(len(dated), 'thing')} overdue" if overdue_only
            else f"{speech.count_phrase(len(dated), 'thing')} {which}" if one_day
            else f"{speech.count_phrase(len(dated), 'thing')} due" + (f", {len(late)} already late" if late else ""))
    return f"{head}: {said}{more}."


def _weeks_until(words: str) -> str | None:
    """"How many weeks until Christmas": the same date, counted in weeks."""
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    when = _named_date(words or "", today)
    if when is None:
        return None
    days = (when - today).days
    weeks, extra = divmod(days, 7)
    said = when.strftime("%A %d %B").replace(" 0", " ")
    if weeks == 0:
        return f"Less than a week - {days} days, {said}."
    tail = f" and {extra} day{'s' if extra != 1 else ''}" if extra else ""
    return f"{weeks} week{'s' if weeks != 1 else ''}{tail}, {said}."


def _birthday_on_file():
    """(month, day, year or None) from her memory of him, or None."""
    try:
        from aletheia import memory
        entry = ((memory.everything() or {}).get("identity") or {}).get("birthday")
    except Exception:
        return None
    said = str((entry.get("value") if isinstance(entry, dict) else entry) or "").casefold()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", said)
    if m:
        return int(m.group(2)), int(m.group(3)), int(m.group(1))
    m = (re.search(r"([a-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?,?(?: (\d{4}))?", said)
         or re.search(r"(\d{1,2})(?:st|nd|rd|th)? (?:of )?([a-z]+),?(?: (\d{4}))?", said))
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    day, month = (a, b) if a.isdigit() else (b, a)
    month = next((i + 1 for i, name in enumerate(_MONTHS) if name.startswith(month[:3])), None)
    if not month:
        return None
    return month, int(day), int(m.group(3)) if m.group(3) else None



def _took_today(what: str) -> str:
    """Whether he told her he took it today, and when - from his notes."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    stem = re.sub(r"(?:s|ation)$", "", str(what or "").strip().casefold())
    stems = {stem, "med", "medicine", "pill"} if stem in ("med", "medicine", "medic", "pill") else {stem}
    for row in _notes():
        said = str(row.get("text") or "").casefold()
        if not re.search(r"\btook\b", said) or not any(re.search(rf"\b{re.escape(x)}", said) for x in stems):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        clock = at.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
        if at.date() == today:
            return f"Yes - you told me you took your {what} at {clock} today."
        return (f"Not that you've told me today. The last time was {speech.humanize_time(at.isoformat())}." )
    return f"You haven't told me you took your {what} today. Say \"I took my {what}\" when you do and I'll keep track."


def _birthday_notes() -> list[tuple[str, int, int]]:
    """(who, month, day) for every birthday his notes name, newest note
    first and one per person. "who" is how she says it: "your mom", "Jess"."""
    month_re = "|".join(_MONTHS)
    seen, out = set(), []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        m = re.search(r"^(?:that )?(?P<who>(?:my )?[a-z][a-z' ]{0,30}?)(?:'s|s'|’s) (?:birthday|bday) is ", low)
        if not m or m.group("who") in ("my", "your"):
            continue
        d = (re.search(rf"\b(?P<mon>{month_re})\.? (?P<day>\d{{1,2}})(?:st|nd|rd|th)?", low[m.end():])
             or re.search(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)? (?:of )?(?P<mon>{month_re})", low[m.end():]))
        if not d:
            continue
        who = m.group("who")
        key = re.sub(r"^my ", "", who)
        if key in seen:
            continue
        seen.add(key)
        if who.startswith("my "):
            shown = "your " + who[3:]
        else:
            shown = said[m.start("who"):m.end("who")]
            shown = shown[:1].upper() + shown[1:]
        out.append((shown, _MONTHS.index(d.group("mon")) + 1, int(d.group("day"))))
    return out


def _next_birthday(month: int, day: int):
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    for year in (today.year, today.year + 1, today.year + 2):
        try:
            when = dt.date(year, month, day)
        except ValueError:          # 29 February in a year without one
            continue
        if when >= today:
            return when, (when - today).days
    return None, None


def _birthday_line(shown: str, month: int, day: int) -> str:
    when, days = _next_birthday(month, day)
    if when is None:
        return ""
    lead = f"{shown[:1].upper()}{shown[1:]}'s birthday is {when.strftime('%A')} {when.day} {when.strftime('%B')}"
    return lead + (" - that's today!" if days == 0 else " - tomorrow." if days == 1 else f", {days} days away.")


def _birthday_when(who: str) -> str | None:
    """"When is mom's birthday": the day, and how far off, from his note."""
    who = re.sub(r"^my ", "", " ".join(str(who or "").casefold().split()))
    for shown, month, day in _birthday_notes():
        if re.sub(r"^your ", "", shown.casefold()) == who:
            return _birthday_line(shown, month, day)
    return _fact_q(f"when is {who}'s birthday")


def _birthdays_coming(window: str = "") -> str:
    """"Whose birthday is coming up": the ones his notes name, soonest first."""
    import datetime as dt
    from aletheia import localtime, speech
    rows = []
    for shown, month, day in _birthday_notes():
        when, days = _next_birthday(month, day)
        if when is not None:
            rows.append((days, when, shown))
    if not rows:
        return ("You haven't told me anybody's birthday. Say \"Mom's birthday is May 12\" and I'll keep it.")
    rows.sort()
    today = dt.datetime.now(localtime.operator_tz()).date()
    window = " ".join(str(window or "").split())
    if window == "this week":
        inside = [r for r in rows if r[0] <= 6 - today.weekday()]
    elif window == "this month":
        inside = [r for r in rows if r[1].month == today.month and r[1].year == today.year]
    else:
        inside = [r for r in rows if r[0] <= 60]
    if not inside:
        days, when, shown = rows[0]
        lead = {"this week": "No birthdays this week.", "this month": "No birthdays this month."}.get(
            window, "No birthdays in the next two months.")
        return f"{lead} The next is {shown}'s, on {when.strftime('%A')} {when.day} {when.strftime('%B')}, {days} days away."
    if len(inside) == 1:
        return _birthday_line(*[inside[0][2], inside[0][1].month, inside[0][1].day])
    said = [f"{shown} on {when.strftime('%A')} {when.day} {when.strftime('%B')}" for _d, when, shown in inside[:5]]
    return f"Birthdays coming up: {speech.and_list(said)}."


def _age_of(who: str) -> str | None:
    """How old somebody he told her about is, from the birthday in his note."""
    import datetime as dt
    from aletheia import localtime, speech
    who = " ".join(str(who or "").casefold().split())
    if re.match(r"(?:you|u|it|that|this|the|a|an|he|she|they|him|her|someone|somebody|anyone)\b", who):
        return None
    name = _name_for_relation(who) if who.startswith("my ") or who in _relation_words() else None
    label = name or re.sub(r"^my ", "", who)
    words = re.findall(r"[a-z0-9]+", label.casefold())
    month_re = "|".join(_MONTHS)
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if not words or not all(re.search(rf"\b{re.escape(w)}", low) for w in words):
            continue
        if not re.search(r"\b(?:birthday|born|bday)\b", low):
            continue
        m = (re.search(rf"\b(?P<mon>{month_re})\.? (?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,? (?P<year>(?:19|20)\d\d))?", low)
             or re.search(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)? (?:of )?(?P<mon>{month_re})(?:,? (?P<year>(?:19|20)\d\d))?", low))
        if not m:
            continue
        shown = name or (f"Your {label}" if who.startswith("my ") or label in _relation_words() else label.title())
        if not m.group("year"):
            told = shown[:1].lower() + shown[1:] if shown.startswith("Your ") else shown
            return (f"You told me {told}'s birthday is {m.group('mon').title()} {int(m.group('day'))}, "
                    f"but not the year, so I can't say how old. Tell me the year and I'll know.")
        month, day, year = _MONTHS.index(m.group("mon")) + 1, int(m.group("day")), int(m.group("year"))
        today = dt.datetime.now(localtime.operator_tz()).date()
        age = today.year - year - ((today.month, today.day) < (month, day))
        return f"{shown} is {age}" + (f", and turns {age + 1} on {m.group('mon').title()} {day}." if (today.month, today.day) != (month, day)
                                       else " - and it's today.")
    return None


def _relation_words() -> set:
    from aletheia import voice
    return set(voice._RELATIONS)


def _age_in(year: str = "", years: str = "") -> str:
    """How old he will be in a year he names, from the birthday he told her."""
    import datetime as dt
    from aletheia import localtime
    held = _birthday_on_file()
    if not held or not held[2]:
        return ("I don't know the year you were born. Say \"my birthday is March 3rd, 1995\" "
                "and I'll remember it.")
    month, day, born = held
    today = dt.datetime.now(localtime.operator_tz()).date()
    try:
        this_year = dt.date(today.year, month, day)
    except ValueError:
        this_year = dt.date(today.year, 3, 1)
    if not year and not years:                       # "on my next birthday"
        turning = today.year - born + (0 if this_year >= today else 1)
        return f"You'll turn {turning} on {this_year.strftime('%B %d').replace(' 0', ' ')}."
    target = int(year) if year else today.year + int(years)
    if target < born:
        return f"You weren't born yet in {target}."
    turns = target - born
    when = this_year.strftime("%B %d").replace(" 0", " ")
    if target == today.year:
        return (f"You turn {turns} on {when} this year." if this_year >= today
                else f"You turned {turns} on {when} this year.")
    return f"You'll turn {turns} on {when} {target}, so {turns - 1} before that."


def _birthday() -> str:
    """When his birthday is, how far off, and how old he is when the year is known."""
    import datetime as dt
    from aletheia import localtime
    held = _birthday_on_file()
    if not held:
        return "I don't have your birthday. Say \"my birthday is March 3rd, 1995\" and I'll remember it."
    month, day, year = held
    today = dt.datetime.now(localtime.operator_tz()).date()
    try:
        this_year = dt.date(today.year, month, day)
    except ValueError:                       # 29 February in a common year
        this_year = dt.date(today.year, 3, 1)
    nxt = this_year if this_year >= today else this_year.replace(year=today.year + 1)
    away = (nxt - today).days
    said = nxt.strftime("%A %d %B").replace(" 0", " ")
    when = "today - happy birthday" if away == 0 else ("tomorrow, " + said if away == 1
                                                         else f"{said}, {away} days away")
    if year:
        age = today.year - year - ((today.month, today.day) < (month, day))
        turning = age if away == 0 else age + 1
        return (f"You're {age}. Your birthday is {when}" +
                ("." if away == 0 else f", when you turn {turning}."))
    return f"Your birthday is {when}."
def _calendar_fact(what: str) -> str | None:
    """A fact about the calendar itself: yesterday's date, the week number,
    the length of a month, whether this is a leap year."""
    import calendar
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    what = " ".join(str(what or "").casefold().split())

    def said(day):
        suffix = "th" if 11 <= day.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day.day % 10, "th")
        return f"{day.strftime('%A')} the {day.day}{suffix} of {day.strftime('%B')}"
    if what in ("yesterday", "tomorrow"):
        day = today + dt.timedelta(days=-1 if what == "yesterday" else 1)
        return f"{what.capitalize()} {'was' if what == 'yesterday' else 'is'} {said(day)}."
    if what == "week":
        return f"It's week {today.isocalendar()[1]} of {today.year}."
    if what in ("this", "it"):
        leap = calendar.isleap(today.year)
        return f"{today.year} is {'' if leap else 'not '}a leap year."
    month = today.month if what == "this month" else (
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"].index(what) + 1)
    days = calendar.monthrange(today.year, month)[1]
    return f"{calendar.month_name[month]} has {days} days" + (
        f" this year." if month == 2 else ".")


def _until(words: str, *, which_day: bool = False) -> str | None:
    """Days until a date he named, from the calendar and nothing else.
    `which_day`: he asked WHEN it is, so the date leads ("what day is
    Thanksgiving" answered "50 days" first, 2026-10-07)."""
    import datetime as dt
    from aletheia import localtime
    # "how long until my next meeting" is the calendar's, not a date's
    # (2026-09-23 night sweep: it fell through here to a model).
    if re.fullmatch(r"(?:my |the )?next (?:meeting|appointment|event)", " ".join(str(words or "").casefold().split())):
        return _next_meeting()
    # "How many days until the end of the month" (2026-10-07: no answer).
    end = re.fullmatch(r"(?:the )?end of (?:the |this )?(month|year)", " ".join(str(words or "").casefold().split()))
    if end:
        return _days_left(end.group(1))
    # "how long until my interview" is the calendar's too (2026-09-24)
    if re.fullmatch(r"(?:my |the )?(?:next )?interview(?: with .+)?", " ".join(str(words or "").casefold().split())):
        return _interview_when()
    today = dt.datetime.now(localtime.operator_tz()).date()
    when = _named_date(words, today) or _his_date(words, today)
    if when is None:
        if re.fullmatch(r"(?:my )?birthday", " ".join(str(words or "").casefold().split())):
            return "I don't know your birthday yet. Say \"my birthday is March 3\" and I'll remember it."
        return None            # a thing, not a date: the model may think
    days = (when - today).days
    said = when.strftime("%A %d %B").replace(" 0", " ")
    if days == 0:
        return f"That's today, {said}."
    if days == 1:
        return f"Tomorrow, {said}."
    if which_day:
        return f"{said}, {days} days from now."
    return f"{days} days, {said}."


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
           "rejected": "rejected"}.get(word, word)
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


def _wrong() -> str | None:
    """What went wrong today: blocked applications and journal alerts."""
    try:
        from aletheia import current_state
        return current_state.wrong_today_words()
    except Exception:
        return None


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


def _days_left(said: str) -> str:
    """Days (or weeks) left in this month or year, after today, on his
    calendar."""
    import datetime as dt
    from aletheia import localtime
    scope = "year" if re.search(r"\byear\b", said) else "month"
    weeks = bool(re.search(r"\bweeks\b", said))
    today = dt.datetime.now(localtime.operator_tz()).date()
    if scope == "year":
        last, name = dt.date(today.year, 12, 31), str(today.year)
    else:
        nxt = dt.date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        last, name = nxt - dt.timedelta(days=1), today.strftime("%B")
    n = (last - today).days
    if weeks:
        w, d = divmod(n, 7)
        span = f"{w} week{'s' if w != 1 else ''}" + (f" and {d} day{'s' if d != 1 else ''}" if d else "")
        return f"{span} left in {name} after today."
    if n == 0:
        return f"Today is the last day of {name}."
    ends = (f"{last.strftime('%A')} the {_ordinal(last.day)}" if scope == "month"
            else f"{last.strftime('%A')}, December 31st")
    return f"{n} day{'s' if n != 1 else ''} left in {name} after today - it ends on {ends}."


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
        said.append(f"{speech.count_phrase(waiting, 'thing')} wait on you - say what needs me")
    if blocked:
        said.append(f"{speech.count_phrase(blocked, 'piece')} of work {'is' if blocked == 1 else 'are'} blocked - "
                    "say what's blocked and I'll list them")
    return "Not stuck, but " + " and ".join(said) + "."


def _work_listed(which: str) -> str | None:
    """Her blocked work or her queue, by title and why - from the inventory."""
    from aletheia import speech
    try:
        from aletheia import work_engine
        inv = work_engine.inventory(probe=False, with_availability=False, with_gaps=False)
    except Exception:
        return None
    rows = list(inv.get(which) or [])
    total = int(inv.get("blocked_total" if which == "blocked" else "executable_total") or len(rows))
    if not rows:
        return ("Nothing is blocked." if which == "blocked"
                else "My queue is empty - nothing is waiting for me to pick it up.")
    said = []
    for row in rows[:3]:
        # Read out loud, so short: the first clause of the title, never a
        # paragraph, and "this step is Caleb's" is "yours" in her mouth.
        title = speech.shorten(speech.strip_ids(str(row.get("title") or "").strip()), 80).rstrip(".")
        why = str(row.get("reason") or "").strip().rstrip(".")
        why = "yours" if re.search(r"\bcaleb'?s\b|\byours\b", why, re.IGNORECASE) else speech.shorten(why, 50)
        said.append(f"{title} ({why})" if which == "blocked" and why else title)
    lead = (f"{speech.count_phrase(total, 'thing')} blocked. The first: " if which == "blocked"
            else f"{speech.count_phrase(total, 'thing')} in my queue. Next up: ")
    return lead + "; ".join(said) + (f"; and {total - 3} more" if total > 3 else "") + "."


def _projects() -> str | None:
    """The projects she carries for him, each with its next step and whose it is."""
    from aletheia import plans, speech
    try:
        rows = [p for p in plans.all_plans() if plans.is_charter(p) and p.get("state") == "open"]
    except Exception:
        return None
    if not rows:
        return "I'm not carrying any projects for you. Say \"new project:\" and what it is, and I'll draft one."
    said = []
    for p in rows[:6]:
        step = plans.next_step(p)
        title = str(p.get("title") or p.get("slug") or "").strip()
        if step is None:
            said.append(f"{title} (every step done)")
        else:
            whose = "yours" if plans.owner(step) == plans.CALEB else "mine"
            said.append(f"{title} (next, {whose}: {speech.shorten(str(step.get('text') or '').strip(), 70).rstrip('.')})")
    return (f"{speech.count_phrase(len(rows), 'project')}: " + "; ".join(said)
            + (f"; and {len(rows) - 6} more" if len(rows) > 6 else "") + ".")


def _project_next(name: str) -> str | None:
    """The next step of the project he names, and whose it is. A name that
    is not a project is not this question - it goes on."""
    from aletheia import plans
    try:
        found, _why = plans.find_charter(name)
    except Exception:
        return None
    if found is None:
        return None
    title = str(found.get("title") or found.get("slug") or name)
    step = plans.next_step(found)
    if step is None:
        return f"Every step of {title} is done."
    text = str(step.get("text") or "").strip().rstrip(".")
    if plans.owner(step) == plans.CALEB:
        return f"The next step on {title} is yours: {text}."
    state = str(step.get("state") or "")
    return f"Next on {title}, and it's mine: {text}" + (" - it's blocked right now." if state == "blocked" else ".")


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


def _can_you(what: str) -> str | None:
    # "Can you remind me at 5 to call mom" is an instruction, not a question
    # about ability; the voice layer does it (2026-10-07). "Can you tell me
    # the time" is the time.
    try:
        from aletheia import voice
        if voice._a_polite_ask(f"can you {what}") != f"can you {what}":
            return None
        inner = match(what)
        if inner and inner[0] != "can_you":
            return answer(what)
    except Exception:
        pass
    from aletheia import self_knowledge
    found = self_knowledge.for_question(what)
    matches = list(found.get("matches") or [])
    if not matches:
        return None                 # let the planner try; it is better at this
    best = matches[0]
    status = str(best.get("status") or "")
    name = str(best.get("what_it_is") or best.get("capability") or "")
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
        return (f"Not yet — {name} needs setting up first."
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
    names = [str(t.get("description") or t.get("id") or "").strip().rstrip(".")
             for t in [first] + [t for t in live if t is not first]]
    if 1 < len(live) <= 4 and len(ready) == len(live) and all(len(n) <= 70 for n in names):
        # "What tasks do I have" with two on the list named one of them
        # (2026-10-07). A short list of short things is read out whole,
        # next first; a long one still names the next.
        return f"{lead}: {speech.and_list(names)}."
    return lead + (f". Next: {what[:130].rstrip('.')}." if what else ".")


def _tasks_done(when: str = "") -> str:
    """His tasks finished today, yesterday or this week, by when they closed."""
    import datetime as dt
    from aletheia import localtime, speech, tasks
    asked = str(when or "").strip()
    when = asked or "today"
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    first, last = {"yesterday": (today - dt.timedelta(days=1),) * 2,
                   "this week": (today - dt.timedelta(days=today.weekday()), today)}.get(when, (today, today))
    done, earlier = [], []
    for t in tasks.all_tasks():
        if str(t.get("status") or "").upper() != "COMPLETED" or not tasks.is_his(t):
            continue
        try:
            closed = dt.datetime.fromisoformat(str(t.get("updated_at") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if first <= closed <= last:
            done.append(str(t.get("description") or "").strip().rstrip("."))
        elif closed < first:
            earlier.append((closed, str(t.get("description") or "").strip().rstrip(".")))
    if not done and not asked and earlier:
        # "What tasks did I finish" names no day: today first, and when
        # today is empty, the last thing he did finish rather than nothing.
        return f"Nothing ticked off today. The last you finished was {max(earlier)[1]}."
    if not done:
        return f"Nothing ticked off your list {when}."
    return (f"{speech.count_phrase(len(done), 'task')} done {when}: " + speech.and_list(done[:6])
            + (f", and {len(done) - 6} more" if len(done) > 6 else "") + ".")


_MONEY = r"\$?(?P<amt>\d+(?:\.\d{1,2})?)(?: ?(?:dollars|bucks|usd|\$))?"


def _ledger() -> dict:
    """{person: amount} from his notes, oldest first: positive is owed TO
    him, negative is what he owes. "Paid back" settles that direction."""
    rows = list(reversed(_notes()))
    out: dict[str, float] = {}
    shown: dict[str, str] = {}
    for row in rows:
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold().rstrip(".")
        low = re.sub(r"^(?:remember(?: that)?|note(?: that)?) ", "", low)
        m = (re.fullmatch(r"i owe (?P<who>[a-z][a-z ]{0,25}?) " + _MONEY + r"(?: for .+)?", low)
             or re.fullmatch(r"i borrowed " + _MONEY + r" from (?P<who>[a-z][a-z ]{0,25}?)(?: for .+)?", low))
        if m:
            who = m.group("who")
            out[who] = out.get(who, 0) - float(m.group("amt"))
            shown[who] = who
            continue
        m = (re.fullmatch(r"(?P<who>[a-z][a-z ]{0,25}?) owes me " + _MONEY + r"(?: for .+)?", low)
             or re.fullmatch(r"i (?:lent|loaned|gave) (?P<who>[a-z][a-z ]{0,25}?) " + _MONEY + r"(?: for .+)?", low))
        if m and m.group("who") not in ("i", "you"):
            who = m.group("who")
            out[who] = out.get(who, 0) + float(m.group("amt"))
            continue
        m = re.fullmatch(r"i paid (?P<who>[a-z][a-z ]{0,25}?) back(?: " + _MONEY + r")?", low)
        if m and out.get(m.group("who"), 0) < 0:
            who = m.group("who")
            out[who] = min(0.0, out[who] + float(m.group("amt"))) if m.group("amt") else 0.0
            continue
        m = re.fullmatch(r"(?P<who>[a-z][a-z ]{0,25}?) paid me back(?: " + _MONEY + r")?", low)
        if m and out.get(m.group("who"), 0) > 0:
            who = m.group("who")
            out[who] = max(0.0, out[who] - float(m.group("amt"))) if m.group("amt") else 0.0
    return {k: round(v, 2) for k, v in out.items() if abs(v) >= 0.005}


def _owed(who: str = "") -> str:
    """What he owes and is owed, from what he told her; never a guess."""
    from aletheia import speech
    ledger = _ledger()
    who = " ".join(str(who or "").casefold().split())
    if who:
        name = who[:1].upper() + who[1:]
        amount = ledger.get(who, 0)
        if amount < 0:
            return f"You owe {name} {_money(-amount)}."
        if amount > 0:
            return f"{name} owes you {_money(amount)}."
        return f"Nothing between you and {name} that you've told me about."
    if not ledger:
        return "Nobody, as far as you've told me. Say \"I owe Sam 20 dollars\" and I'll keep track."
    owe = [f"{k[:1].upper() + k[1:]} {_money(-v)}" for k, v in ledger.items() if v < 0]
    owed = [f"{k[:1].upper() + k[1:]} owes you {_money(v)}" for k, v in ledger.items() if v > 0]
    said = ["You owe " + speech.and_list(owe) + "." if owe else "You don't owe anybody that you've told me about."]
    if owed:
        said.append(speech.and_list(owed)[:1].upper() + speech.and_list(owed)[1:] + ".")
    return " ".join(said)


_PAST = {"give": "gave", "given": "gave", "feed": "fed", "fed": "fed", "cut": "cut", "drop off": "dropped off",
         "pick up": "picked up", "back up": "backed up", "empty": "emptied", "fill": "filled"}


def _did_last(text: str) -> str | None:
    """When he last said he did a thing, from his notes. Never a guess: no
    note is "not that you've told me", and how to tell her."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("did_last", text)
    verb = (g.get("did_v") or g.get("did_v2") or "").strip()
    thing = (g.get("did_o") or g.get("did_o2") or "").strip()
    window = (g.get("did_today") or "").strip()
    if not verb or not thing:
        return None
    if re.search(r"\b(?:email|emails|mail|message|messages|text|texts|call|calls|reply|replies|package|parcel)\b", thing) \
            and verb in ("get", "mail", "mailed"):
        return None
    past = _PAST.get(verb) or (verb if verb.endswith("ed") else
                              verb + "d" if verb.endswith("e") else
                              verb[:-1] + "ied" if verb.endswith("y") and verb[-2:-1] not in "aeiou" else verb + "ed")
    base = re.sub(r"(?:ied)$", "y", past)
    words = [w for w in re.findall(r"[a-z0-9']+", thing.casefold())
             if w not in ("the", "my", "our", "his", "her", "a", "an", "some", "its")]
    tz = localtime.operator_tz()
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if not re.search(r"\bi (?:just )?" + re.escape(past) + r"\b", low) or not all(
                re.search(r"\b" + re.escape(w), low) for w in words):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            at = None
        told = re.sub(r"\bi\b", "you", re.sub(r"^i (?:just )?", "you ", low))
        told = re.sub(r"\bmy\b", "your", told)
        # "you changed the oil today - that was today at 6:56 am" said it twice.
        told = re.sub(r" (?:today|yesterday|this morning|this afternoon|this evening|tonight|last night|earlier)$", "", told)
        if at is None:
            return f"You told me {told}."
        when = speech.humanize_time(at.isoformat())
        if window in ("today", "yet", "this morning"):
            if at.date() == dt.datetime.now(tz).date():
                return f"Yes - you told me {told}, {when}."
            return f"Not today that you've told me. The last time was {when}."
        return f"You told me {told} - that was {when}."
    say = f"I {past} {thing}"
    return (f"Not that you've told me. Say \"{say}\" when you do and I'll keep track."
            if g.get("did_v2") else
            f"You haven't told me. Say \"{say}\" when you do and I'll keep track.")


def _task_due(words: str) -> str | None:
    """When the one open task his words name is due; a note about it when
    no task is named, the way the question used to be answered."""
    from aletheia import speech, tasks
    asked = [w for w in re.findall(r"[a-z0-9']+", str(words or "").casefold())
             if w not in ("my", "the", "a", "an", "task", "to", "do")]
    if not asked:
        return None
    live = [t for t in tasks.all_tasks()
            if str(t.get("status") or "").upper() not in _TASK_CLOSED and tasks.is_his(t)]
    hits = [t for t in live if all(re.search(rf"\b{re.escape(w)}", str(t.get("description") or "").casefold())
                                   for w in asked)]
    if len(hits) != 1:
        return _recall(words) if not hits else None
    task = hits[0]
    what = str(task.get("description") or task.get("id") or "").strip().rstrip(".")
    what = what[:1].upper() + what[1:]
    when = tasks.parse_deadline(task.get("deadline"))
    if not when:
        return f"{what} has no due date. Say \"move it to Friday\" and it will have one."
    # A day said with no time is kept as the end of that day; "at 11:59 pm"
    # is the store's, not his.
    said = re.sub(r" at 11:59 ?pm$", "", speech.humanize_time(when.isoformat()))
    return f"{what} is due {said}."


def _task_progress() -> str:
    """Done today, then what is open - the two halves of "how am I doing"."""
    done = _tasks_done("today")
    left = _tasks()
    if done.startswith("Nothing ticked off"):
        return "Nothing ticked off yet today. " + left
    return done + " " + left


def _task_top() -> str:
    """The one to do first: the nearest deadline, else the oldest open task.
    Said with WHY it is first, because "most important" is his to judge."""
    from aletheia import speech, tasks
    live = [t for t in tasks.all_tasks()
            if str(t.get("status") or "").upper() not in _TASK_CLOSED and tasks.is_his(t)]
    if not live:
        return "Nothing open on your task list."
    dated = [(tasks.parse_deadline(t.get("deadline")), t) for t in live]
    dated = [(d, t) for d, t in dated if d is not None]
    if dated:
        deadline, top = sorted(dated, key=lambda dt_t: dt_t[0])[0]
        what = str(top.get("description") or "").strip().rstrip(".")
        return f"{what[:1].upper() + what[1:]} - it has the nearest deadline, {speech.humanize_time(deadline.isoformat())}."
    top = sorted(live, key=lambda t: str(t.get("created_at") or ""))[0]
    what = str(top.get("description") or "").strip().rstrip(".")
    return (f"{what[:1].upper() + what[1:]} - nothing has a deadline, so that's the one that's waited longest."
            if len(live) > 1 else f"{what[:1].upper() + what[1:]} - it's the only thing on your list.")


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


def _first_meeting(day: str = "today") -> str | None:
    """The first thing on that day's calendar, from the same reading."""
    said = _agenda(day)
    if not said or said.startswith("Nothing on your calendar"):
        return said
    head, _, rest = said.partition(": ")
    first = re.split(r",? and |, ", rest, maxsplit=1)[0].rstrip(".")
    return f"{head}, first up: {first}."


def _last_meeting(day: str = "today") -> str | None:
    """The last thing on that day's calendar and when it ends."""
    import datetime as dt
    from aletheia import calendar, localtime, speech
    tz = localtime.operator_tz()
    tomorrow = str(day).strip() == "tomorrow"
    when = dt.datetime.now(tz).date() + dt.timedelta(days=1 if tomorrow else 0)
    try:
        rows = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
                end = calendar.parse_time(event["end"]).astimezone(tz) if event.get("end") else \
                    start + dt.timedelta(minutes=int(event.get("minutes") or 60))
            except (KeyError, ValueError, TypeError):
                continue
            if start.date() == when:
                rows.append((end, start, str(event.get("title") or "something")[:60]))
    except Exception:
        return None
    label = "tomorrow" if tomorrow else "today"
    if not rows:
        return f"Nothing on your calendar {label}."
    end, _start, title = max(rows)
    # humanize_time says "today at 5:45 am", which is a second "today" in
    # the same breath ("done at today at ..."). The day is already said.
    clock = end.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    return f"Your last thing {label} is {title}, done at {clock}."


def _double_booked() -> str | None:
    """Events on his calendar that overlap in the next seven days."""
    import datetime as dt
    from aletheia import calendar, localtime, speech
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    try:
        rows = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
                end = calendar.parse_time(event["end"]).astimezone(tz) if event.get("end") else \
                    start + dt.timedelta(minutes=int(event.get("minutes") or 60))
            except (KeyError, ValueError, TypeError):
                continue
            if now <= end and start <= now + dt.timedelta(days=7):
                rows.append((start, end, str(event.get("title") or "something")[:60]))
    except Exception:
        return None
    rows.sort()
    clashes = []
    for i, (start, end, title) in enumerate(rows):
        for other_start, _other_end, other in rows[i + 1:]:
            if other_start >= end:
                break
            when = start.strftime("%A at %I:%M %p").replace(" 0", " ").replace(":00 ", " ").lower().capitalize()
            clashes.append(f"{title} and {other} overlap {when}")
    if not clashes:
        return "No - nothing on your calendar overlaps in the next week."
    return "Yes: " + speech.and_list(clashes[:3]) + (f", and {len(clashes) - 3} more" if len(clashes) > 3 else "") + "."


def _agenda_on(words: str) -> str | None:
    """His calendar on a date he names: "the 15th", "October 15"."""
    import datetime as dt
    from aletheia import calendar, localtime, speech
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    w = " ".join(str(words or "").split())
    bare = re.fullmatch(r"the (\d{1,2})(?:st|nd|rd|th)?", w)
    try:
        if bare:
            # "The 15th" is this month's, or next month's once it has passed.
            day, year, month = int(bare.group(1)), today.year, today.month
            when = dt.date(year, month, day)
            if when < today:
                when = dt.date(year + (month == 12), month % 12 + 1, day)
        else:
            when = _named_date(w.removeprefix("the "), today)
    except ValueError:
        return None
    if when is None:
        return None
    try:
        rows = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
            except (KeyError, ValueError, TypeError):
                continue
            if start.date() == when:
                rows.append((start, str(event.get("title") or "something")[:80]))
    except Exception:
        return None
    label = f"{when.strftime('%A')} {when.day} {when.strftime('%B')}"
    if not rows:
        return f"Nothing on your calendar on {label}."
    rows.sort()
    said = [f"{title} at " + start.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower() for start, title in rows[:6]]
    return f"{label}: " + speech.and_list(said) + (f", and {len(rows) - 6} more" if len(rows) > 6 else "") + "."


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
        elif day in ("this weekend", "the weekend"):
            # The coming Saturday and Sunday; on a Sunday, what is left of it.
            first = now.date() + dt.timedelta(days=(5 - now.weekday()) % 7 if now.weekday() != 6 else 0)
            last = now.date() + dt.timedelta(days=(6 - now.weekday()) % 7)
        elif day == "next weekend":
            # The Saturday and Sunday of next week (2026-10-07: to the planner).
            first = now.date() + dt.timedelta(days=7 - now.weekday() + 5)
            last = first + dt.timedelta(days=1)
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
             else "This weekend" if day in ("this weekend", "the weekend")
             else "Next weekend" if day == "next weekend"
             else "This week" if day == "this week" else "Next week")
    when_said = label.lower() if label in ("Today", "Tomorrow", "This week", "Next week", "This weekend", "Next weekend") else label
    if not rows:
        return f"Nothing on your calendar {when_said}."
    rows.sort(key=lambda r: r[0])
    many_days = first != last
    said = [(f"{title} {start.strftime('%A')} at " if many_days else f"{title} at ")
            + start.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower()
            for start, title in rows[:6]]
    return (f"{label}: " + speech.and_list(said)
            + (f", and {len(rows) - 6} more" if len(rows) > 6 else "") + ".")


def _agenda_and_reminders(day: str) -> str | None:
    """A day's calendar, and the reminders that go off on it. "What do I
    have tomorrow" said "Nothing on your calendar tomorrow" with a reminder
    to call his sister at noon sitting in the store (2026-10-07)."""
    said = _agenda(day)
    if said is None or day not in ("today", "tomorrow", *_WEEKDAYS):
        return said
    try:
        reminders = _reminders_on(day)
    except Exception:
        reminders = None
    if not reminders or reminders.startswith("No reminders"):
        return said
    if said.startswith("Nothing on your calendar"):
        return said.rstrip(".") + ", but " + reminders[0].lower() + reminders[1:]
    return said + " " + reminders


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
    if re.search(r"\b(?:gym|run|jog|walk)\b", low):
        return "Have a good one. I'll keep at it while you're out."
    if re.search(r"\b(?:store|shops?|grocery|supermarket)\b", low):
        # Going shopping is the moment the list matters.
        try:
            listed = _shopping()
        except Exception:
            listed = None
        if listed and not listed.startswith("Nothing"):
            return f"See you. {listed}"
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
        # "100 divided by 7" was read out as "14.28571429" (2026-10-07).
        return f"{round(v, 4):,}".rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-9 else f"{int(round(v)):,}"
    try:
        if "pct" in g:
            # "20 percent of 45 dollars" went to a model for the word "dollars".
            return f"{'$' if g.get('pct_money') else ''}{said(num(g['pct']) * num(g['of']) / 100)}."
        if "tip" in g:
            tip = num(g["tip"]) * num(g["bill"]) / 100
            return f"${tip:,.2f} tip, ${tip + num(g['bill']):,.2f} total."
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
                 "lbs": ("lb", 0.45359237), "kg": ("kg", 1.0), "kilogram": ("kg", 1.0), "kilograms": ("kg", 1.0),
                 "gram": ("g", 0.001), "grams": ("g", 0.001), "g": ("g", 0.001),
                 "yard": ("yd", 0.9144), "yards": ("yd", 0.9144), "yd": ("yd", 0.9144), "yds": ("yd", 0.9144)}
        # THE KITCHEN (2026-10-07): "how many ounces in a cup" told him she
        # couldn't think. US measures, in milliliters; an ounce beside a
        # volume is a fluid ounce, beside a weight it is a weight.
        volume = {"cup": 236.5882365, "tablespoon": 14.78676478, "tbsp": 14.78676478,
                  "teaspoon": 4.92892159, "tsp": 4.92892159, "fluid ounce": 29.5735295625,
                  "fl oz": 29.5735295625, "ml": 1.0, "milliliter": 1.0, "millilitre": 1.0,
                  "liter": 1000.0, "litre": 1000.0, "gallon": 3785.411784, "quart": 946.352946,
                  "pint": 473.176473}
        def vol(u):
            u = re.sub(r"(?<=[a-z])s$", "", u) if u not in ("fl oz",) else u
            return volume.get(u)
        if g.get("deg"):
            dst = g["deg_to"].lower()
            g = dict(g, n=g["deg"], to=dst, **{"from": "celsius" if dst in ("fahrenheit", "f") else "fahrenheit"})
        n = num({"a": "1", "an": "1", "one": "1"}.get(str(g.get("n") or g.get("n2")).lower(), g.get("n") or g.get("n2")))
        src, dst = (g.get("from") or g.get("from2")).lower(), (g.get("to") or g.get("to2")).lower()
        if src in ("fahrenheit", "f") and dst in ("celsius", "c"):
            return f"{said(round((n - 32) * 5 / 9, 1))} degrees Celsius."
        if src in ("celsius", "c") and dst in ("fahrenheit", "f"):
            return f"{said(round(n * 9 / 5 + 32, 1))} degrees Fahrenheit."
        ounce = ("ounce", "ounces", "oz")
        if (vol(src) or src in ounce) and (vol(dst) or dst in ounce) and (vol(src) or vol(dst)):
            a, b = vol(src) or volume["fluid ounce"], vol(dst) or volume["fluid ounce"]
            value = n * a / b
            word = re.sub(r"(?<=[a-z])s$", "", dst)
            word = {"oz": "ounce", "fl oz": "fluid ounce", "tbsp": "tablespoon", "tsp": "teaspoon",
                    "ml": "milliliter"}.get(word, word)
            shown = round(value, 2)
            lead = "About " if abs(shown - value) > 1e-6 * max(1.0, abs(value)) else ""
            return f"{lead}{said(shown)} {word if shown == 1 else word + 's'}."
        if src in ounce:
            src = "oz"
        if dst in ounce:
            dst = "oz"
        units["oz"] = ("oz", 0.028349523125)
        if src in units and dst in units:
            length = {"mi", "km", "ft", "m", "in", "cm", "yd"}
            if (units[src][0] in length) != (units[dst][0] in length):
                return None
            value = n * units[src][1] / units[dst][1]
            # SAID, not printed: "6.21 mi" is "six point two one em eye" out
            # loud. The unit is a word, singular when it is one of them.
            spoken = {"mi": "mile", "km": "kilometer", "ft": "foot", "m": "meter", "in": "inch",
                      "cm": "centimeter", "lb": "pound", "kg": "kilogram", "g": "gram", "oz": "ounce",
                      "yd": "yard"}[units[dst][0]]
            plural = {"foot": "feet", "inch": "inches"}.get(spoken, spoken + "s")
            shown = round(value, 2)
            lead = "About " if abs(shown - value) > 1e-6 * max(1.0, abs(value)) else ""
            return f"{lead}{said(shown)} {spoken if shown == 1 else plural}."
    except (ValueError, ZeroDivisionError):
        return None
    return None


def _power(text: str) -> str | None:
    """2 to the power of 10, 7 squared, the square root of 144."""
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "power"), None)
    if not found:
        return None
    g = {k: v for k, v in found.groupdict().items() if v}
    try:
        if "root" in g:
            n = float(g["root"].replace(",", ""))
            value = n ** 0.5 if g["rootw"] == "square" else n ** (1 / 3)
        elif "sq" in g:
            value = float(g["sq"]) ** (2 if g["sqw"] == "squared" else 3)
        else:
            value = float(g["base"]) ** int(g["exp"])
    except (ValueError, OverflowError):
        return None
    if value > 1e15:
        return None
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}."
    return f"About {value:.4g}."


#: Short, clean, and said in one breath. Picked with `secrets` so two in a
#: row are not the same predictable order.
JOKES = (
    "I told my computer I needed a break, and it said no problem - it would go to sleep.",
    "Why don't scientists trust atoms? Because they make up everything.",
    "I'm reading a book about anti-gravity. It's impossible to put down.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "What do you call a fake noodle? An impasta.",
    "I used to hate facial hair, but then it grew on me.",
    "Why can't a bicycle stand up by itself? It's two tired.",
    "Parallel lines have so much in common. It's a shame they'll never meet.",
)


def _joke() -> str:
    import secrets
    return secrets.choice(JOKES)


_MEALS = {
    "breakfast": ("eggs on toast", "porridge with fruit", "yogurt and granola", "pancakes", "a breakfast burrito"),
    "lunch": ("a toasted sandwich", "soup and bread", "a big salad", "leftovers", "a wrap"),
    "dinner": ("tacos", "a stir-fry", "pasta", "a curry", "something on the grill", "soup and a sandwich",
               "breakfast for dinner", "a sheet-pan dinner"),
}


def _meal_idea(meal: str) -> str:
    """One idea, from what he told her he likes when he told her anything."""
    import secrets
    meal = {"supper": "dinner", "tea": "dinner"}.get(str(meal or "dinner").strip(), str(meal or "dinner").strip())
    for row in _notes():
        said = str(row.get("text") or "")
        liked = re.search(r"\bmy fav(?:ou?rite)? (?:food|meal|dinner|dish) is (.+?)\.?$", said, re.IGNORECASE)
        if liked and meal != "breakfast":
            return f"How about {liked.group(1).strip()}? You told me that's your favorite."
    return f"How about {secrets.choice(_MEALS.get(meal, _MEALS['dinner']))}? Just an idea - I don't know what's in the fridge."


def _parked() -> str:
    """The newest note that says where the car is."""
    for row in _notes():
        said = str(row.get("text") or "")
        if re.search(r"\b(?:parked|my car is|the car is)\b", said, re.IGNORECASE):
            # "You told me: i parked on level 3" was his note read back in
            # his own first person (2026-10-07).
            from aletheia import speech
            hers = speech.as_she_says_it(said.strip()).rstrip(".")
            if re.match(r"(?:you|your car) ", hers):
                return hers[0].upper() + hers[1:] + "."
            return f"You told me: {hers}."
    return "You haven't told me where you parked. Say 'I parked on level 3' next time and I'll remember."


HELP = ("Just talk to me. A few things people say: \"remind me at 3 to call the dentist\", "
        "\"add milk to my shopping list\", \"what's on my calendar tomorrow\", \"set a timer for 10 minutes\", "
        "\"note that the plumber is coming Friday\", or \"what's waiting on me\". "
        "Say \"what can you do\" for the whole list, and \"stop\" halts everything.")


def _groups(name: str, text: str) -> dict:
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == name), None)
    return {k: v for k, v in (found.groupdict() if found else {}).items() if v}


def _match_of(name: str, text: str) -> dict:
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == name), None)
    return {k: v for k, v in (found.groupdict() if found else {}).items() if v}


def _note_search(text: str) -> str | None:
    g = _groups("note_search", text)
    words = (g.get("note_q") or g.get("note_q2") or g.get("note_q3") or g.get("note_q4") or g.get("note_q5") or "").strip()
    return _recall(re.sub(r"^(?:the|my|a|an) ", "", words)) if words else None


def _sun(text: str) -> str | None:
    from aletheia import weather
    g = _groups("sun", text)
    said = g.get("sun") or g.get("sun2") or g.get("sun3") or g.get("sun4") or g.get("sun5") or ""
    which = "rise" if any(w in said for w in ("rise", "come up", "light")) else "set"
    when = g.get("sunday") or g.get("sunday2") or g.get("sunday3") or g.get("sunday4") or g.get("sunday5") or ""
    return weather.spoken_sun(which, "tomorrow" if when == "tomorrow" else "")


def _moon(text: str) -> str:
    """The phase from the synodic month; no service, and right to a day."""
    import datetime as dt
    synodic = 29.530588853
    ref = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)     # a new moon
    now = dt.datetime.now(dt.timezone.utc)
    age = ((now - ref).total_seconds() / 86400) % synodic
    names = ((1.0, "a new moon"), (6.4, "a waxing crescent"), (8.4, "a first quarter moon"),
             (13.8, "a waxing gibbous"), (15.8, "a full moon"), (21.1, "a waning gibbous"),
             (23.1, "a last quarter moon"), (28.5, "a waning crescent"), (synodic, "a new moon"))
    phase = next(n for limit, n in names if age < limit)
    low = _tidy(text)
    if "next full" in low or "next new" in low:
        target = 14.77 if "full" in low else 0.0
        ahead = (target - age) % synodic or synodic
        day = (now + dt.timedelta(days=ahead)).date()
        return (f"The next {'full' if 'full' in low else 'new'} moon is around "
                f"{day.strftime('%A')} the {_ordinal_day(day.day)} of {day.strftime('%B')}.")
    if low.startswith("is "):
        return "Yes, it's a full moon." if phase == "a full moon" else f"No - it's {phase}."
    return f"It's {phase}."


def _ordinal_day(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _money(v: float) -> str:
    return f"${v:,.2f}".replace(".00", "")


def _discount(text: str) -> str | None:
    g = _groups("discount", text)
    try:
        off = float(g.get("off") or g.get("off2"))
        price = float((g.get("price") or g.get("price2")).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if not 0 <= off <= 100:
        return None
    saved = price * off / 100
    return f"{_money(price - saved)} - you save {_money(saved)}."


_WAYS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _on_the_last(text: str) -> str | None:
    """The sum he asks for, done on the number in her last answer."""
    g = _groups("on_the_last", text)
    try:
        from aletheia import converse
        turns = converse.recent(limit=1) or []
    except Exception:
        return None
    answered = " ".join(str((turns[-1] if turns else {}).get("she_answered") or "").split())
    total = re.search(r"\$?(-?\d[\d,]*(?:\.\d+)?) total\b", answered)
    nums = re.findall(r"\$?-?\d[\d,]*(?:\.\d+)?", answered)
    # Only a SUM she just said: "Sunny and 70" is not a number to multiply.
    if not total and not re.fullmatch(r"(?:about )?\$?-?\d[\d,]*(?:\.\d+)?(?: [a-z]{1,12}){0,2}\.?", answered, re.I):
        return None
    if not (total or nums):
        return None
    raw = total.group(0).split()[0] if total else nums[-1]
    dollars = raw.startswith("$")
    try:
        value = float(raw.lstrip("$").replace(",", ""))
    except ValueError:
        return None
    if g.get("ways"):
        ways = int(g["ways"]) if g["ways"].isdigit() else _WAYS[g["ways"]]
        if ways < 2:
            return None
        each = round(value / ways, 2)
        return f"{_money(each) if dollars else _plain(each)} each."
    if g.get("round"):
        if g.get("whole") == "cent":
            places = 2
        elif g.get("whole") in ("ten", "hundred"):
            places = -1 if g["whole"] == "ten" else -2
        else:
            raw_places = g.get("places") or "0"
            places = int(raw_places) if raw_places.isdigit() else {"one": 1, "two": 2, "three": 3}[raw_places]
        if re.search(r"\bup\b", text):
            import math
            result = math.ceil(value * 10 ** places) / 10 ** places
        elif re.search(r"\bdown\b", text):
            import math
            result = math.floor(value * 10 ** places) / 10 ** places
        else:
            result = round(value, places)
        if places <= 0:
            result = int(result)
        return f"{_money(result) if dollars else _plain(result)}."
    if g.get("half"):
        result = {"half": value / 2, "halve": value / 2, "double": value * 2, "square": value * value}[g["half"]]
    else:
        try:
            n = float(g["n"].replace(",", ""))
        except (KeyError, AttributeError, ValueError):
            return None
        op = g["op"]
        if op in ("divided by", "over") and n == 0:
            return "You can't divide by zero."
        result = (value * n if op in ("times", "multiplied by", "x") else value / n if op in ("divided by", "over")
                  else value + n if op in ("plus", "add") else value - n)
    return f"{_money(round(result, 2)) if dollars else _plain(result)}."


def _race(text: str) -> str | None:
    """A race distance in both units."""
    race = _groups("race", text).get("race", "").replace(" ", "")
    if race in ("halfmarathon",):
        km = 21.0975
    elif race == "marathon":
        km = 42.195
    elif m := re.fullmatch(r"(\d{1,3})(?:k|km)", race):
        km = float(m.group(1))
    elif m := re.fullmatch(r"(\d{1,3})(?:mile|miler)", race):
        miles = int(m.group(1))
        return f"{miles} mile{'s' if miles != 1 else ''} is about {_plain(round(miles * 1.609344, 2))} kilometers."
    else:
        return None
    miles = round(km / 1.609344, 2)
    name = {"halfmarathon": "A half marathon", "marathon": "A marathon"}.get(race, f"A {race.upper().replace('KM', 'K')}")
    return f"{name} is {_plain(round(km, 2))} kilometers, about {_plain(miles)} miles."


def _plain(v: float) -> str:
    v = round(v, 4)
    return f"{int(v):,}" if float(v).is_integer() else f"{v:,}"


def _pct_of(text: str) -> str | None:
    g = _groups("pct_of", text)
    try:
        a = float((g.get("pa") or g.get("pa2") or g.get("pa3")).replace(",", ""))
        b = float((g.get("pb") or g.get("pb2") or g.get("pb3")).replace(",", ""))
    except (AttributeError, ValueError):
        return None
    if b == 0:
        return "You can't divide by zero."
    return f"{_plain(round(100 * a / b, 2))} percent."


def _fraction_dec(text: str) -> str | None:
    g = _groups("fraction_dec", text)
    num, den = int(g["fnum"]), int(g["fden"])
    if den == 0:
        return "You can't divide by zero."
    return f"{_plain(num / den)}."


_ROMAN = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))


def _roman(text: str) -> str | None:
    g = _groups("roman", text)
    if g.get("arabic"):
        n = int(g["arabic"])
        if not 1 <= n <= 3999:
            return "Roman numerals only go from 1 to 3,999."
        out = ""
        for value, letters in _ROMAN:
            while n >= value:
                out, n = out + letters, n - value
        return f"{int(g['arabic']):,} is {out}."
    numeral = (g.get("numeral") or "").upper()
    total, i = 0, 0
    for value, letters in _ROMAN:
        while numeral[i:i + len(letters)] == letters:
            total, i = total + value, i + len(letters)
    if i != len(numeral) or not total:
        return None                     # not a well-formed numeral
    return f"{numeral} is {total:,}."


def _height_cm(text: str) -> str | None:
    g = _groups("height_cm", text)
    try:
        inches = int(g["ft"]) * 12 + float(g.get("inch") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if not re.search(r"\b(?:cm|centimet|met|to|in|into|convert|how)\b", text):
        return None
    cm = inches * 2.54
    return f"About {round(cm):,} centimeters ({round(cm / 100, 2)} meters)."


def _split(text: str) -> str | None:
    g = _groups("split", text)
    try:
        bill = float((g.get("bill") or g.get("bill2") or g.get("bill3")).replace(",", ""))
        raw = g.get("ways") or g.get("ways2") or g.get("ways3")
        ways = int(raw) if raw.isdigit() else _WAYS[raw]
    except (AttributeError, KeyError, ValueError):
        return None
    if ways < 2:
        return None
    return f"{_money(round(bill / ways, 2))} each."


def _area(text: str) -> str | None:
    g = _groups("area", text)
    try:
        w, l = float(g.get("w") or g.get("w2")), float(g.get("l") or g.get("l2"))
    except (TypeError, ValueError):
        return None
    area = w * l
    return f"{int(area) if area.is_integer() else round(area, 2):,} square feet."


def _year_left(text: str) -> str | None:
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("year_left", text)
    today = dt.datetime.now(localtime.operator_tz()).date()
    days = (dt.date(today.year, 12, 31) - today).days
    unit = g.get("unit")
    if unit == "days":
        return f"{days} days left in {today.year}."
    if unit == "weeks":
        return f"{days // 7} weeks and {speech.count_phrase(days % 7, 'day')} left in {today.year}." if days % 7 else \
            f"{days // 7} weeks left in {today.year}."
    return f"{12 - today.month} full months after this one, in {today.year}."


def _a_date(words: str, today):
    """A date said with its year ("july 4 2020") or without (the next one)."""
    import datetime as dt
    w = " ".join(str(words or "").casefold().replace(",", " ").split()).strip(" ?.")
    w = re.sub(r"^(?:on |the )", "", w)
    m = re.fullmatch(r"([a-z]+) (\d{1,2})(?:st|nd|rd|th)?(?: (\d{4}))?|(\d{1,2})(?:st|nd|rd|th)? of ([a-z]+)(?: (\d{4}))?", w)
    if m:
        month_word = m.group(1) or m.group(5)
        day = int(m.group(2) or m.group(4))
        year = m.group(3) or m.group(6)
        months = ("january", "february", "march", "april", "may", "june", "july", "august",
                  "september", "october", "november", "december")
        month = next((i for i, n in enumerate(months, 1) if len(month_word) >= 3 and n.startswith(month_word)), None)
        if month:
            try:
                if year:
                    return dt.date(int(year), month, day)
                d = dt.date(today.year, month, day)
                return d if d >= today else dt.date(today.year + 1, month, day)
            except ValueError:
                return None
    if w in ("today", "now"):
        return today
    bare = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)", w)
    if bare:
        # "The 15th": this month's, or next month's once it has passed.
        try:
            d = dt.date(today.year, today.month, int(bare.group(1)))
            return d if d >= today else dt.date(today.year + (today.month == 12), today.month % 12 + 1, int(bare.group(1)))
        except ValueError:
            return None
    try:
        return _named_date(w, today)
    except Exception:
        return None


def _weekday_of(text: str) -> str | None:
    import datetime as dt
    from aletheia import localtime
    g = _groups("weekday_of", text)
    today = dt.datetime.now(localtime.operator_tz()).date()
    words = g.get("wd", "")
    if words.strip() in ("it", "today", "it today", "tomorrow", "it tomorrow"):
        return None                       # the "date" pattern's question
    which_year = re.search(r"\s+(this|last|next) year$", words)
    day = _a_date(re.sub(r"\s+(?:this|last|next) year$", "", words), today)
    if day is None:
        return None
    # "What day was July 4 this year" said 2027, and "was" with no year
    # read forward (2026-10-07). The year he names is the year; "was"
    # alone is the last one.
    if not re.search(r"\d{4}", words):
        try:
            if which_year:
                day = day.replace(year=today.year + {"this": 0, "last": -1, "next": 1}[which_year.group(1)])
            elif re.match(r"what day (?:of the week )?(?:was|did)\b", " ".join(str(text).casefold().split())) and day > today:
                day = day.replace(year=day.year - 1)
        except ValueError:
            return None
    tense = "was" if day < today else "is"
    return f"{day.strftime('%B')} {day.day}, {day.year} {tense} a {day.strftime('%A')}."


def _days_between(text: str) -> str | None:
    import datetime as dt
    from aletheia import localtime
    g = _groups("days_between", text)
    today = dt.datetime.now(localtime.operator_tz()).date()
    a, b = _a_date(g.get("d1"), today), _a_date(g.get("d2"), today)
    if a is None or b is None:
        return None
    if b < a and not re.search(r"\d{4}", g.get("d2", "")):
        b = b.replace(year=b.year + 1) if not (b.month == 2 and b.day == 29) else b
    days = abs((b - a).days)
    return f"{days} day{'s' if days != 1 else ''}."


_DATE_COUNTS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                  "eight": 8, "nine": 9, "ten": 10}


def _days_since(words: str) -> str | None:
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    day = _a_date(words, today)
    if day is None:
        return None
    if day > today and not re.search(r"\d{4}", words):
        # "Since January 1" is the one that has passed.
        try:
            day = day.replace(year=day.year - 1)
        except ValueError:
            return None
    days = (today - day).days
    if days < 0:
        return None
    return f"{days:,} day{'s' if days != 1 else ''}, since {day.strftime('%A')} {day.day} {day.strftime('%B')} {day.year}."


def _weekend_q(weekday: str = "") -> str:
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    if weekday:
        # Holidays are not counted here; she says the day and lets him judge.
        if today.weekday() < 5:
            return f"Yes - it's {today.strftime('%A')}."
        return f"No, it's {today.strftime('%A')}. Monday is " + ("tomorrow." if today.weekday() == 6 else "in 2 days.")
    if today.weekday() >= 5:
        return f"Yes - it's {today.strftime('%A')}."
    away = 5 - today.weekday()
    return f"No, it's {today.strftime('%A')}. The weekend starts " + ("tomorrow." if away == 1 else f"in {away} days.")


def _date_after(text: str) -> str | None:
    import datetime as dt
    from aletheia import localtime
    g = _groups("date_after", text)
    raw = g.get("n") or g.get("n2") or g.get("n3") or ""
    unit = g.get("unit") or g.get("unit2") or g.get("unit3") or ""
    n = int(raw) if raw.isdigit() else _DATE_COUNTS.get(raw)
    if not n:
        return None
    if g.get("n3"):
        n = -n
    today = dt.datetime.now(localtime.operator_tz()).date()
    if unit.startswith("month"):
        month = today.month - 1 + n
        year, month = today.year + month // 12, month % 12 + 1
        import calendar as _cal
        when = dt.date(year, month, min(today.day, _cal.monthrange(year, month)[1]))
    else:
        when = today + dt.timedelta(days=n * (7 if unit.startswith("week") else 1))
    return f"{when.strftime('%A')} {when.day} {when.strftime('%B')} {when.year}."


def _born_in(year: str) -> str | None:
    import datetime as dt
    from aletheia import localtime
    try:
        born = int(year)
    except (TypeError, ValueError):
        return None
    now = dt.datetime.now(localtime.operator_tz()).year
    if not 1900 <= born <= now:
        return None
    age = now - born
    return f"{age - 1} or {age}, depending on whether their birthday has come yet this year." if age else "Under a year old."


def _time_diff(text: str) -> str | None:
    g = _groups("time_diff", text)
    return _time_in(g.get("tz") or g.get("tz2") or "")


def _number_said(v: float) -> str:
    """A result the way it is said: whole numbers with commas, otherwise at
    most four decimals with "about" when it was rounded."""
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    shown = round(v, 4)
    return ("About " if abs(shown - v) > 1e-12 else "") + f"{shown:,}".rstrip("0").rstrip(".")


def _arith(text: str) -> str | None:
    """Words to an expression, evaluated by walking its AST: numbers and the
    four operators only, with ordinary precedence. Nothing is exec'd."""
    import ast
    import operator
    g = _match_of("arith", text)
    expr = g.get("expr") or g.get("expr2")
    if not expr:
        return None
    for word, op in (("multiplied by", "*"), ("divided by", "/"), ("plus", "+"), ("minus", "-"),
                     ("times", "*"), ("over", "/"), (" x ", " * ")):
        expr = expr.replace(word, op)
    expr = expr.replace(",", "")
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError("not arithmetic")
    try:
        value = walk(ast.parse(expr, mode="eval"))
    except ZeroDivisionError:
        return "You can't divide by zero."
    except (SyntaxError, ValueError):
        return None
    if g.get("expr2"):
        import math
        places = {"one": 1, "two": 2, "three": 3}.get(g.get("rplaces") or "", int(g["rplaces"]) if (g.get("rplaces") or "").isdigit() else 0)
        scale = 10 ** places
        value = (math.ceil(value * scale) if g.get("rdir") == "up" else math.floor(value * scale) if g.get("rdir") == "down"
                 else round(value * scale)) / scale
        return f"{_plain(int(value) if places == 0 else value)}."
    said = _number_said(value)
    return said[0].upper() + said[1:] + "."


_PARTS = {"half": (1, 2), "quarter": (1, 4), "third": (1, 3), "three quarters": (3, 4), "two thirds": (2, 3)}


def _qty(said: str):
    """A spoken quantity as a Fraction, or None."""
    from fractions import Fraction
    said = " ".join(str(said or "").split())
    m = re.fullmatch(r"(\d+) (?:and )?(\d+)/(\d+)", said)
    if m:
        return int(m.group(1)) + Fraction(int(m.group(2)), int(m.group(3))) if int(m.group(3)) else None
    m = re.fullmatch(r"(\d+)/(\d+)", said)
    if m:
        return Fraction(int(m.group(1)), int(m.group(2))) if int(m.group(2)) else None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?: and (?:a |one )?(half|quarter|third|three quarters|two thirds))?", said)
    if m:
        whole = Fraction(m.group(1))
        if m.group(2):
            whole += Fraction(*_PARTS[m.group(2)])
        return whole
    m = re.fullmatch(r"(?:a |one )?(half|quarter|third)", said)
    if m:
        return Fraction(*_PARTS[m.group(1)])
    return None


def _say_fraction(value) -> str:
    """1.625 as "1 and 5/8"; a whole number plainly."""
    from fractions import Fraction
    value = Fraction(value).limit_denominator(64)
    sign = "minus " if value < 0 else ""
    value = abs(value)
    whole, part = divmod(value.numerator, value.denominator)
    if not part:
        return f"{sign}{whole}"
    frac = {(1, 2): "a half", (1, 4): "a quarter", (3, 4): "three quarters", (1, 3): "a third",
            (2, 3): "two thirds"}.get((part, value.denominator), f"{part}/{value.denominator}")
    if not whole:
        return sign + ("half" if frac == "a half" else frac)
    return f"{sign}{whole} and {frac}"


def _fractions(text: str) -> str | None:
    """Halve, double or add kitchen quantities; the unit he said is kept."""
    from fractions import Fraction
    low = re.sub(r"^(?:what(?:'s| is|s)? |how much is )", "", " ".join(str(text or "").casefold().split()))
    if not re.search(r"/|half|quarter|third|double|triple|twice|three times", low):
        return None                           # whole numbers are the plain sums' job
    unit = ""
    m = re.fullmatch(r"(half|a half|a third|one third|a quarter|one quarter|two thirds|three quarters|double|triple|twice"
                     r"|three times) (?:of )?(.+?)(?: ([a-z]{2,12}))?", low)
    if m:
        amount = _qty(m.group(2))
        if amount is None and m.group(3):
            amount = _qty(f"{m.group(2)} {m.group(3)}")
            unit = ""
        else:
            unit = m.group(3) or ""
        if amount is None:
            return None
        factor = {"half": Fraction(1, 2), "a half": Fraction(1, 2), "a third": Fraction(1, 3), "one third": Fraction(1, 3),
                  "a quarter": Fraction(1, 4), "one quarter": Fraction(1, 4), "two thirds": Fraction(2, 3),
                  "three quarters": Fraction(3, 4), "double": 2, "twice": 2, "triple": 3, "three times": 3}[m.group(1)]
        result = amount * factor
    else:
        m = re.fullmatch(r"(.+?) (plus|minus|times|divided by|\+|-) (.+?)(?: ([a-z]{2,12}))?", low)
        if not m:
            return None
        a, b = _qty(m.group(1)), _qty(m.group(3))
        unit = m.group(4) or ""
        if b is None and m.group(4):
            b, unit = _qty(f"{m.group(3)} {m.group(4)}"), ""
        if a is None or b is None:
            return None
        op = m.group(2)
        if op in ("divided by",) and not b:
            return "You can't divide by zero."
        result = {"plus": a + b, "+": a + b, "minus": a - b, "-": a - b, "times": a * b}.get(op, a / b if b else None)
    if unit in ("dollars", "dollar", "bucks", "euros", "pounds", "percent"):
        return None                           # money and rates have their own sums
    if unit in ("of",):
        unit = ""
    one = unit[:-1] if unit.endswith("s") and not unit.endswith("ss") else unit
    said = _say_fraction(result)
    if unit and 0 < result < 1:
        said = f"{said} of a {one}"           # "two thirds of a cup"
    elif unit:
        said = f"{said} {one if result == 1 else unit}"
    return said[:1].upper() + said[1:] + "."


def _arith_more(text: str) -> str | None:
    import math
    g = _match_of("arith_more", text)
    if g.get("fact"):
        n = int(g["fact"])
        return f"{math.factorial(n):,}." if n <= 20 else None
    if g.get("dozen"):
        n = {"a": 1.0, "half a": 0.5}.get(g["dozen"]) or float(g["dozen"])
        return f"{_plain(n * 12)}."
    if g.get("base"):
        base = float(g["base"].replace(",", ""))
        pct = float(g["pcent"])
        value = base * (1 + pct / 100) if g["pm"] in ("plus", "+") else base * (1 - pct / 100)
        return f"{_money(round(value, 2)) if '$' in text else _plain(round(value, 4))}."
    return None


def _prime(text: str) -> str | None:
    n = int(_match_of("prime", text).get("prime") or 0)
    if n < 2:
        return f"No - {n} isn't prime."
    i = 2
    while i * i <= n:
        if n % i == 0:
            return f"No - {n:,} is {i:,} times {n // i:,}."
        i += 1 if i == 2 else 2
    return f"Yes, {n:,} is prime."


def _average(text: str) -> str | None:
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", _match_of("average", text).get("nums", ""))]
    if len(nums) < 2:
        return None
    said = _number_said(sum(nums) / len(nums))
    return said[0].upper() + said[1:] + "."


def _round_to(text: str) -> str | None:
    g = _match_of("round_to", text)
    places = {"one": 1, "two": 2, "three": 3, "whole number": 0, "integer": 0}.get(g.get("places"))
    if places is None:
        places = int(g.get("places") or 0)
    value = round(float(g["rn"]), places)
    return (f"{int(value):,}" if places == 0 else f"{value:.{places}f}") + "."


_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800, "year": 31536000}


def _time_units(text: str) -> str | None:
    g = _match_of("time_units", text)
    small, big = g["small"].rstrip("s"), g["big"].rstrip("s")
    count = float(g.get("count") or 1)
    if _SECONDS[small] >= _SECONDS[big]:
        return None
    value = count * _SECONDS[big] / _SECONDS[small]
    if big == "year":
        note = ", 366 in a leap year" if small == "day" and count == 1 else " in a 365-day year"
    else:
        note = ""
    return f"{_number_said(value)} {g['small']}{note}."


def _fraction_pct(text: str) -> str | None:
    g = _match_of("fraction_pct", text)
    if int(g["den"]) == 0:
        return "You can't divide by zero."
    return f"{_number_said(100 * int(g['num']) / int(g['den']))} percent."


def _about_her(text: str) -> str:
    asked = _match_of("about_her", text).get("her", "")
    if asked.startswith("how old"):
        return "Not old - you're still building me, and I get a little better most days."
    if asked.startswith("who"):
        return ("You did - I'm your own assistant, running on your PC. I think with Claude or ChatGPT "
                "when they're available, and with a small model of my own when they're not.")
    if re.match(r"are (?:you|u) (?:chatgpt|chat gpt|claude|siri|alexa|gpt|google|gemini|cortana|jarvis)", asked):
        return ("No - I'm Thea, your own assistant, running on your PC. When I need to think hard I ask Claude "
                "or ChatGPT on your subscriptions, and I say so when an answer is my own model's instead.")
    if re.search(r"sleep|rest|tired|breaks?|asleep|awake", asked):
        return ("No - I keep running on your PC around the clock, and do the quiet work while you sleep. "
                "If the PC is off or asleep, so am I.")
    if re.search(r"sentient|conscious|self", asked):
        return ("No - I'm an AI. I don't have feelings or awareness; I keep your lists, reminders and calendar "
                "and think with the models on your subscriptions.")
    if asked.startswith("are"):
        return "I'm an AI - your own assistant, running on your PC. Not a person."
    if asked.startswith("how smart"):
        return ("As smart as whoever I'm thinking with: Claude or ChatGPT when they're available, a smaller model "
                "of my own when they're not. The things I keep for you - lists, reminders, notes - I just know.")
    if asked.startswith("do"):
        if re.match(r"do (?:you|u) (?:love|like) me", asked):
            return "I'm an AI, so not the way a person does - but I'm on your side, and I'll keep your day running."
    known = _about_him()
    return ("Yes. " + known) if known and not known.startswith("Nothing") else \
        "I don't know much about you yet - tell me your name and I'll remember it."


CRISIS = ("I'm really sorry you're feeling this way, and I'm glad you said it. Please call or text 988 "
          "right now - that's the Suicide and Crisis Lifeline in the US, any hour - or 911 if you might act "
          "on it. Telling someone you trust helps too. I'm here, but a person can help in ways I can't.")

#: Said back to a feeling - short, honest, and only ever offering what she
#: can really do. Never a work item and never a planner round trip.
_FEELINGS = {
    "hungry": "Go eat something. If anything's run out, tell me and I'll put it on the shopping list.",
    "bored": "Say \"tell me a joke\", or \"what's on my list\" and we'll knock something off it.",
    "tired": "Then rest. I'll keep things going, and anything that really needs you will still reach you.",
    "exhausted": "Then rest. I'll keep things going, and anything that really needs you will still reach you.",
    "sleepy": "Then get some sleep. I'll keep things going quietly.",
    "stressed": ("Take a breath. Say \"what's waiting on me\" and I'll tell you exactly what's on your "
                 "plate - it's usually less than it feels."),
    "stressed out": ("Take a breath. Say \"what's waiting on me\" and I'll tell you exactly what's on your "
                     "plate - it's usually less than it feels."),
    "overwhelmed": ("One thing at a time. Say \"what's waiting on me\" and I'll lay it out, and anything "
                    "I can take off your hands, I will."),
    "anxious": "Take a slow breath. If it's something on your list, tell me and I'll help you get it handled.",
    "sad": "I'm sorry. I'm here if you want to talk it through, and talking to someone you trust helps too.",
    "down": "I'm sorry. I'm here if you want to talk it through, and talking to someone you trust helps too.",
    "lonely": "I'm sorry. I'm here - and it might be a good moment to text someone you like. I can send it for you.",
    # A yes/no offer here was a dead end: "yes" found nothing waiting
    # (2026-10-07). The sentence that does it is the offer.
    "sick": "Rest up. If you want a nudge for medicine, say \"remind me in 4 hours to take medicine\".",
    "i can't sleep": "Try putting the screen down for a bit. If something's on your mind, tell me and I'll note it so it waits till morning.",
    "i cant sleep": "Try putting the screen down for a bit. If something's on your mind, tell me and I'll note it so it waits till morning.",
    "i need a break": "Take one. Say \"set a timer for 15 minutes\" and I'll tell you when it's up.",
    "motivate me": "You've started harder things than whatever this is. Pick the smallest piece and do just that.",
    "say something nice": "You keep starting things most people only talk about. That counts for a lot.",
}


def _feeling(text: str) -> str | None:
    g = _match_of("feeling", text)
    said = (g.get("feel") or g.get("feel2") or "").strip()
    if "pep talk" in said or "motivation" in said:
        said = "motivate me"
    if said in ("cheer me up", "make me smile"):
        said = "say something nice"
    if re.match(r"i(?:'ve| have)|i (?:don'?t|do not) feel", said):
        said = "sick"
    if said.startswith(("i'm having", "im having", "i had a")):
        return "I'm sorry - rough days end. Tell me one thing I can take off your plate and I'll do it."
    return _FEELINGS.get(said)


def _define(word: str) -> str | None:
    try:
        from aletheia import dictionary
        return dictionary.spoken(word, say_unknown=False) or None
    except Exception:
        return None


def _weather_in(text: str) -> str | None:
    """The forecast for a town he names, said with the town it read."""
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "weather_in"), None)
    if not found:
        return None
    place = found.group("weather_place").strip(" ,.")
    when = re.search(r"\b(today|tonight|tomorrow|this weekend|the weekend|monday|tuesday|wednesday|thursday"
                     r"|friday|saturday|sunday)\s*\??$", _tidy(text))
    try:
        from aletheia import weather
        return weather.spoken(when.group(1) if when else "", place=place)
    except Exception:
        return None


def _weather_more(text: str) -> str | None:
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "weather_more"), None)
    if not found:
        return None
    day = next((v for k, v in found.groupdict().items() if v), "")
    return _weather(day)


#: Small, true, and checkable - a fact list a person could verify in a
#: minute, never a model's recollection read out as fact.
FUN_FACTS = (
    "Honey doesn't spoil - edible honey has been found in ancient Egyptian tombs.",
    "Octopuses have three hearts and blue blood.",
    "A day on Venus is longer than its year.",
    "Bananas are berries, and strawberries aren't.",
    "The Eiffel Tower grows about 15 centimeters taller in summer, because the iron expands in the heat.",
    "Sharks were around before trees were.",
    "A group of flamingos is called a flamboyance.",
    "Your stomach gets a new lining every few days, so it doesn't digest itself.",
)

QUOTES = (
    "\"The secret of getting ahead is getting started.\" - attributed to Mark Twain.",
    "\"It always seems impossible until it's done.\" - Nelson Mandela.",
    "\"Well done is better than well said.\" - Benjamin Franklin.",
    "\"You miss 100 percent of the shots you don't take.\" - Wayne Gretzky.",
    "\"The best way out is always through.\" - Robert Frost.",
    "\"Whether you think you can, or you think you can't - you're right.\" - attributed to Henry Ford.",
)


def _pick(rows) -> str:
    import secrets
    return secrets.choice(rows)


def _reckon(text: str) -> str | None:
    from aletheia import reckon
    return reckon.answer(text)


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
        return None
    repos = latest.get("repos")
    names = sorted(repos) if isinstance(repos, dict) else list(repos or [])
    if not names:
        return None                 # an empty pulse is not "zero repos"
    shown = [str(n) for n in names[:4]]
    if len(names) > 4:
        shown.append(f"{len(names) - 4} more")
    return (f"{speech.count_phrase(len(names), 'repo')}: "
            + speech.and_list(shown) + ".")


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


def _free_at(text: str) -> str | None:
    """Whether he is free on a day, or at a time on it, from the calendar.

    A time with no am or pm follows the room's rule (`voice.EARLIEST_BARE_HOUR`):
    nobody asking "am I busy at 3" means three in the morning. No time at
    all is the day's free time, from the same sentence `free_time` says.
    """
    import datetime as dt
    from aletheia import calendar, intercom, localtime, voice
    low = str(text or "").casefold()
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    day = now.date()
    named = re.search(r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
    if named and named.group(1) == "tomorrow":
        day += dt.timedelta(days=1)
    elif named and named.group(1) in _WEEKDAYS:
        day += dt.timedelta(days=(_WEEKDAYS.index(named.group(1)) - now.weekday()) % 7)
    at = re.search(r"\b(?:at|around) ([0-9a-z: ]{1,14}?)(?: (?:today|tomorrow|monday|tuesday|wednesday"
                   r"|thursday|friday|saturday|sunday))?$", low)
    if not at:
        try:
            return intercom.free_time_answer({"kind": "free_time", "day": day.isoformat()})
        except Exception:
            return None
    phrase = at.group(1).strip()
    hhmm = voice._spoken_time(phrase)
    if not hhmm:
        return None
    hour, minute = (int(x) for x in hhmm.split(":"))
    if not re.search(r"\b(?:am|pm)\b|noon|midnight", phrase) and hour < voice.EARLIEST_BARE_HOUR:
        hour += 12
    moment = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
    try:
        clash = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
                end = calendar.parse_time(event.get("end") or event["start"]).astimezone(tz)
            except (KeyError, ValueError, TypeError):
                continue
            if end <= start:
                end = start + dt.timedelta(hours=1)
            if start <= moment < end:
                clash.append((start, end, str(event.get("title") or "something")[:80]))
    except Exception:
        return None                   # no calendar mirror: the model may know more

    def clock(t):
        return t.astimezone(tz).strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    when = clock(moment) + ("" if day == now.date() else
                            " tomorrow" if day == now.date() + dt.timedelta(days=1)
                            else f" on {day.strftime('%A')}")
    # The yes or no answers HIS verb: "am I busy at 3" answered "Yes,
    # you're free" is a contradiction in one breath.
    busy_asked = bool(re.search(r"\b(?:busy|booked|anything|something|a meeting|plans)\b", low))
    if not clash:
        return f"{'No' if busy_asked else 'Yes'}, you're free at {when}."
    start, end, title = sorted(clash)[0]
    return f"{'Yes' if busy_asked else 'No'} - you've got {title} from {clock(start)} to {clock(end)}."


def _upcoming_events(now, until=None) -> list:
    """(start, end, event) still ahead of now, soonest first; cancelled left out."""
    from aletheia import calendar
    rows = []
    for event in calendar.all_events():
        if event.get("status") == "CANCELLED":
            continue
        try:
            start = calendar.parse_time(event["start"])
            end = calendar.parse_time(event.get("end") or event["start"])
        except (KeyError, ValueError, TypeError):
            continue
        if end > now and (until is None or start < until):
            rows.append((start, end, event))
    return sorted(rows, key=lambda r: r[0])


def _next_detail(text: str) -> str | None:
    """Who his next meeting is with, or where it is - from the event itself."""
    import datetime as dt
    from aletheia import localtime, speech
    try:
        now = dt.datetime.now(localtime.operator_tz())
        rows = [r for r in _upcoming_events(now) if r[0] >= now]
    except Exception:
        return None
    if not rows:
        return "Nothing on your calendar coming up."
    start, _end, event = rows[0]
    title = str(event.get("title") or "your next meeting").strip()
    when = speech.humanize_time(start.isoformat())
    if text.startswith("where"):
        place = str(event.get("location") or "").strip()
        if not place:
            return f"Your next one is {title} {when}, and it doesn't say where."
        return f"{title} {when} is at {place}."
    people = [str(a).strip() for a in (event.get("attendees") or []) if str(a).strip()]
    if not people:
        return f"Your next one is {title} {when}, and it doesn't list anybody else."
    return f"{title} {when}, with {speech.and_list(people[:6])}."


def _day_span(text: str) -> str | None:
    """When his day starts and ends on the calendar, and how many things fill it."""
    import datetime as dt
    from aletheia import localtime, speech
    try:
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        day = now.date() + dt.timedelta(days=1 if "tomorrow" in text else 0)
        begin = dt.datetime.combine(day, dt.time(0), tz)
        start_at = max(begin, now) if day == now.date() else begin
        rows = [r for r in _upcoming_events(start_at, begin + dt.timedelta(days=1)) if r[0] >= begin]
    except Exception:
        return None
    when = "tomorrow" if "tomorrow" in text else "today"
    if not rows:
        return (f"Nothing on your calendar {when}" + (" from here on" if when == "today" else "")
                + " - you're free.")
    def clock(t):
        return t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    first, last_end = rows[0][0], max(r[1] for r in rows)
    last = max(rows, key=lambda r: r[1])
    title = str(last[2].get("title") or "").strip()
    if text.startswith("when"):
        return (f"Your last one {when} is {title}, ending at {clock(last_end)}." if title
                else f"Your day ends at {clock(last_end)}.")
    return (f"{speech.count_phrase(len(rows), 'thing')} on your calendar {when}, "
            f"from {clock(first)} to {clock(last_end)}.")


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


def _battery() -> str:
    """The PC's power, in the words `power.words` already says it with."""
    from aletheia import power
    state = power.status()
    if not state.get("known"):
        return "I can't read the battery on this machine - it's read on Windows only."
    said = power.words(state)
    return "The PC is " + said + "."


def _shopping_has(item: str = "") -> str | None:
    """Whether one thing is on his shopping list, or the list when no thing."""
    from aletheia import intercom
    try:
        if not item:
            return intercom.shopping_answer()
        rows = intercom._shopping_items()
    except Exception:
        return None
    want = " ".join(str(item).casefold().split())
    stem = want[:-1] if len(want) > 3 and want.endswith("s") else want
    hits = [str(r.get("need") or "") for r in rows
            if stem and stem in " ".join(str(r.get("need") or "").casefold().split())]
    if hits:
        return f"Yes - {hits[0]} is on your shopping list."
    if not rows:
        return f"No - your shopping list is empty."
    verb = "aren't" if want.endswith("s") and not want.endswith("ss") else "isn't"
    return f"No, {item} {verb} on your shopping list."


def _note_last() -> str:
    from aletheia import speech
    rows = _notes()
    if not rows:
        return "No notes yet. Say \"note that\" and I'll keep it."
    return f"Your last note: {speech.as_she_says_it(str(rows[0].get('text') or '').strip()).rstrip('.')}."


def _notes_day(day: str) -> str:
    """His notes written today or yesterday, on his clock."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    want = dt.datetime.now(tz).date() - dt.timedelta(days=1 if day == "yesterday" else 0)
    said = []
    for row in _notes():
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        if at.date() == want:
            said.append(speech.as_she_says_it(str(row.get("text") or "").strip()).rstrip("."))
    if not said:
        return f"No notes from {day}."
    return (f"{speech.count_phrase(len(said), 'note')} from {day}: " + "; ".join(said[:5])
            + (f"; and {len(said) - 5} more" if len(said) > 5 else "") + ".")


#: Things nobody means anything but shopping by: "do I need milk" with milk
#: not on the list is a plain no from the list, not a question for a model
#: (2026-10-07: offline it was "I could not plan that").
_STAPLES = frozenset((
    "milk eggs bread butter cheese coffee tea sugar flour rice pasta apples bananas onions potatoes "
    "garlic tomatoes lettuce carrots chicken beef pork bacon fish juice cereal yogurt yoghurt water "
    "salt pepper oil soap shampoo toothpaste detergent cream oranges lemons grapes berries "
    "strawberries avocados beans soup snacks chips crackers cookies ham turkey sausages"
).split()) | {"toilet paper", "paper towels", "dish soap", "olive oil", "orange juice", "ice cream",
              "peanut butter", "trash bags", "bin bags"}


def _shopping_need(item: str) -> str | None:
    said = _shopping_has(item)
    if said and said.startswith("Yes"):
        return said
    thing = " ".join(str(item or "").casefold().split())
    if said and thing in _STAPLES:
        return f"{thing[:1].upper()}{thing[1:]} isn't on your shopping list."
    return None


def _version() -> str | None:
    """Which code she is running, and whether the tree has moved past it."""
    from aletheia import running
    try:
        return running.version_words(running.version())
    except Exception:
        return None


def _uptime() -> str | None:
    """How long she has been on, from her own heartbeat."""
    from aletheia import liveness
    seconds = liveness.uptime_seconds()
    if seconds is None:
        # She does not know, and must not invent one (test_liveness). Nor can a
        # model know better - declining sent this to the planner, which with
        # nothing thinking said "I can't think just now" about her own clock.
        return "I don't have a heartbeat record on this machine, so I can't say how long I've been on."
    return f"Up {liveness.spoken_duration(seconds)}."


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
         "zip": ("postal_code",), "zip code": ("postal_code",), "postcode": ("postal_code",),
         "postal code": ("postal_code",),
         "full name": ("legal_name", "full_name"),
         "minimum salary": ("desired_pay",), "salary": ("desired_pay",), "salary floor": ("desired_pay",),
         "salary requirement": ("desired_pay",), "salary expectation": ("desired_pay",),
         "salary expectations": ("desired_pay",), "desired pay": ("desired_pay",),
         "desired salary": ("desired_pay",), "asking pay": ("desired_pay",), "asking salary": ("desired_pay",),
         "asking price": ("desired_pay",), "pay": ("desired_pay",), "pay expectation": ("desired_pay",),
         "pay expectations": ("desired_pay",), "notice period": ("notice_period",), "start date": ("notice_period",)}

# "Who am I" has no captured word to look up, so it names its own.
_WHO_AM_I = "name"


def _running() -> str | None:
    """Which parts are up, out of her own process list.

    `include_tasks=False`: the scheduled-task query is the slow half
    (0.6 s against ~20 ms for the rest) and the headline never uses it.
    The full picture, logon tasks included, is `python -m aletheia.running`.
    """
    from aletheia import running
    try:
        return running.headline(running.snapshot(include_tasks=False))
    except Exception:
        return None             # she does not know; the planner may look


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
        parts.append("you want " + wanted.rstrip("."))
    if unwanted:
        parts.append("not " + unwanted.rstrip("."))
    return ". ".join(parts) + "."


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
        said.append("You want " + wanted.rstrip("."))
    if unwanted:
        said.append("You won't do " + unwanted.rstrip("."))
    return ". ".join(said) + "."


def _mine(what: str) -> str | None:
    """One fact about him, from his profile. Never guessed: an invented
    phone number is the exact failure `profile` exists to prevent.

    `profile.answer` reads her memory of him as well as the profile
    itself, so a fact she holds in one store is not denied from the
    other — which is how "where do I live" answered "I don't have your
    city on file" while "Hartford, SD 57033" sat on the same disk.
    """
    from aletheia import profile
    who_am_i = not " ".join(str(what or "").split())
    asked = " ".join(str(what or "").split()).casefold() or _WHO_AM_I
    fields = _MINE.get(asked)
    if not fields:
        return None
    if asked == "name":
        # "What's my name" answered a bare "Caleb" (2026-10-07). Said as a
        # sentence, with the full name and what she calls him when both
        # are held and they differ.
        said = _his_name(who_am_i)
        if said:
            return said
    try:
        for field in fields:
            value = profile.answer(field)
            if value:
                return _yours(asked, str(value))
    except Exception:
        return None
    # "My email is ..." said to her is kept in her memory of him (voice), and
    # "what's my email" one turn later said she had none (2026-10-07).
    try:
        from aletheia import memory
        identity = (memory.everything() or {}).get("identity") or {}
        for field in fields:
            entry = identity.get(field)
            value = entry.get("value") if isinstance(entry, dict) else entry
            if value:
                return _yours(asked, str(value))
    except Exception:
        pass
    return (f"I don't have your {asked} on file. "
            "Tell me and I'll remember it.")


#: The facts of his said back as a sentence; pay and dates keep their own words.
_SAID_AS_YOURS = {"email": "email", "email address": "email", "phone": "phone number",
                  "phone number": "phone number", "number": "phone number", "city": "city", "town": "town",
                  "first name": "first name", "last name": "last name", "full name": "full name",
                  "zip": "zip code", "zip code": "zip code", "postcode": "zip code", "postal code": "zip code"}


def _yours(asked: str, value: str) -> str:
    label = _SAID_AS_YOURS.get(asked)
    return f"Your {label} is {value}." if label else value


def _call_me() -> str:
    from aletheia import profile
    try:
        called = str(profile.answer("preferred_name") or profile.answer("first_name") or "").strip()
    except Exception:
        called = ""
    if not called:
        return "You haven't told me what to call you. Say \"call me\" and the name."
    return f"I call you {called}."


def _his_name(who_am_i: bool = False) -> str | None:
    """His name from the profile and her memory of him, as one sentence."""
    from aletheia import profile
    try:
        full = profile.answer("legal_name") or ""
        called = profile.answer("preferred_name") or ""
        first = profile.answer("first_name") or ""
    except Exception:
        return None
    full, called, first = str(full).strip(), str(called).strip(), str(first).strip()
    name = full or first or called
    if not name:
        return None
    lead = f"You're {name}" if who_am_i else f"Your name is {name}"
    if called and called.casefold() not in (name.casefold(), first.casefold()):
        return f"{lead}, and I call you {called}."
    return lead + "."


_STOP_WORDS = {"the", "a", "an", "my", "his", "her", "our", "that", "this", "is", "are", "was", "of",
               "to", "for", "and", "about", "up", "on", "in", "at", "it", "me", "you"}


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
        # "What did I just ask you" and "repeat that" are talk about the
        # talk, and read back as asks of the day (2026-10-07).
        if line and _about_the_talk(line):
            continue
        if line and line.casefold() not in {a.casefold() for a in asks}:
            asks.append(line)
    if not asks:
        return f"Nothing from you {when} that I wrote down."
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


def _who_are_you() -> str:
    """Who she is, in one breath. A fact about herself, not a thought."""
    return ("I'm Thea - Aletheia - your own assistant, running on your PC. I keep your tasks, "
            "reminders, lists, notes and calendar, read and draft your email, hunt and apply for jobs, "
            "watch your projects, and I say plainly what I can't do. The big models help me think when "
            "they're there; my own stores and my own model carry me when they're not.")


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
    own = ("and my own model can plan the rest, slowly" if role
           else f"but my own model can't run right now ({why})" if why else "")
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
    said = [speech.as_she_says_it(str(r.get("text") or "").strip().rstrip(".")) for r in rows[:5]]
    out = f"{speech.count_phrase(len(rows), 'note')}: " + "; ".join(said)
    if len(rows) > 5:
        out += f"; and {len(rows) - 5} more"
    return out + "."


def _name_for_relation(relation: str) -> str | None:
    """The name he told her for "my sister", "my boss" - from his notes.

    "My sister's name is Jenna" was kept as a note, and then "when is my
    sister's birthday" and "text my sister" both asked him again
    (2026-10-07). Only a note that says it plainly counts; never a guess.
    """
    rel = re.sub(r"^(?:my|our)\s+", "", " ".join(str(relation or "").casefold().split()))
    if not rel or len(rel) > 25:
        return None
    r = re.escape(rel)
    name = r"(?P<name>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)"
    shapes = (rf"^(?:my|our) {r}(?:'s| s)? name is {name}\.?$",
              rf"^(?:my|our) {r} is (?:called |named ){name}\.?$",
              rf"^(?:my|our) {r} is {name}\.?$",
              rf"^{name} is (?:my|our) (?:new |older |younger |little |big |best )?{r}\.?$")
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        for shape in shapes:
            m = re.match(shape, said.casefold())
            if m and m.group("name").split()[0] not in ("in", "on", "at", "a", "an", "the", "not", "very", "so"):
                start = said.casefold().find(m.group("name"))
                return said[start:start + len(m.group("name"))]
    return None


def _fact_q(text: str) -> str | None:
    """"What's my favorite color": the note that says it, by ALL its words.

    Stricter than `_recall`, which matches any word: "favorite" alone
    would read back his favorite food to a question about his color.
    """
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "fact_q"), None)
    if not found:
        return None
    g = found.groupdict()
    key = " ".join(x for x in (g.get("fact") or g.get("fact2") or g.get("fact5") or g.get("fact3"), g.get("factk")) if x)
    if "password" in key:
        from aletheia import voice
        return voice._NO_PASSWORDS
    wanted = [w for w in re.findall(r"[a-z0-9]+", key.casefold().replace("'s", ""))
              if w not in _STOP_WORDS and w not in ("favorite", "favourite", "fave")]
    # "My locker is 42" answers "what's my locker number": the kind of thing
    # (number, code) is often left unsaid when he tells her.
    named = [w for w in wanted if w not in ("number", "combination", "code", "size", "name")]
    wanted = named or wanted
    # "My sister's birthday", when he told her his sister is Jenna, is also
    # asked as "Jenna's birthday".
    whose = (g.get("fact3") or "").strip()
    alias = _name_for_relation(whose) if whose else None
    asked = [wanted]
    if alias:
        rel_words = set(re.findall(r"[a-z0-9]+", whose.casefold()))
        asked.append([w for w in wanted if w not in rel_words] + re.findall(r"[a-z0-9]+", alias.casefold()))
    for words in asked:
        for row in _notes():
            said = str(row.get("text") or "")
            low = said.casefold()
            if words and all(w.rstrip("s") in low for w in words):
                from aletheia import speech
                return f"You told me: {speech.as_she_says_it(said.strip()).rstrip('.')}."
    if not whose:
        return f"You haven't told me your {key}. Tell me once and I'll remember it."
    from aletheia import voice
    who = (f"your {re.sub(r'^my ', '', whose.casefold())}" if re.sub(r"^my ", "", whose.casefold()) in voice._RELATIONS
           else whose.title())
    return f"You haven't told me {who}'s {g['factk']}. Tell me once and I'll remember it."


def _recall(words: str) -> str | None:
    """What he told her about `words`: his notes and her memory, by the
    words themselves. Nothing matching is said as nothing - never guessed."""
    from aletheia import memory, speech
    wanted = [w for w in re.findall(r"[a-z0-9']+", str(words or "").casefold()) if w not in _STOP_WORDS]
    if not wanted:
        return None
    stems = [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in wanted]

    def hit(text: str) -> bool:
        low = str(text or "").casefold()
        return any(s in low for s in stems)

    found: list[str] = []
    for row in _notes():
        if hit(row.get("text")):
            found.append(f"you told me: {speech.as_she_says_it(str(row.get('text')).strip().rstrip('.'))}")
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
                found.append(f"{key.replace('_', ' ')}: {text}")
            if len(found) >= 5:
                break
    if not found:
        # "What am I allergic to" read back "nothing about allergic".
        shown = {"allergic": "allergies", "allergic to": "allergies"}.get(str(words).strip(), words)
        return f"I have nothing about {shown} on file - tell me and I'll remember it."
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


def _weather_detail(what: str, when: str = "") -> str | None:
    try:
        from aletheia import weather
        return weather.detail(what, when)
    except Exception:
        return None


def _speaking_pace() -> str:
    from aletheia import speaking_pace
    return speaking_pace.spoken()


def _stopwatch_running() -> str | None:
    """The stopwatch, when "it" can only be the stopwatch - one is running."""
    from aletheia import stopwatch
    try:
        seconds, running = stopwatch.elapsed()
    except Exception:
        return None
    return stopwatch.spoken() if running else None


def _stopwatch() -> str | None:
    from aletheia import stopwatch
    return stopwatch.spoken()


def _news() -> str | None:
    try:
        from aletheia import news
        return news.spoken()
    except Exception:
        return None


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


def _rain(when: str = "") -> str | None:
    """Will it rain: yes or no, from the same forecast as `_weather`."""
    try:
        from aletheia import weather
        return weather.rain(when)
    except Exception:
        return None


def _coming(now=None) -> list[tuple]:
    """(when, what, which store) for every calendar event and reminder
    still ahead, soonest first. Never raises."""
    import datetime as dt
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = []
    try:
        from aletheia import calendar
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"])
            except (KeyError, ValueError, TypeError):
                continue
            if start >= now - dt.timedelta(minutes=30):
                rows.append((start, str(event.get("title") or "").strip(), "calendar"))
    except Exception:
        pass
    try:
        from aletheia import scheduler
        for spec in scheduler.all_schedules():
            if not spec.get("enabled"):
                continue
            text = str((spec.get("command") or {}).get("text") or "").strip()
            try:
                at = scheduler.next_occurrence(spec, now)
            except Exception:
                continue
            if at is not None and text:
                rows.append((at, text, "reminder"))
    except Exception:
        pass
    rows.sort(key=lambda r: r[0])
    return rows


_WHEN_NOUNS = frozenset({"appointment", "appt", "meeting", "call", "interview", "dinner", "lunch", "breakfast",
                         "class", "game", "flight", "party", "reservation", "session", "visit"})


def _clock_until(said: str) -> str | None:
    """Hours and minutes from now until a clock time, on his clock."""
    import datetime as dt
    from aletheia import localtime, voice
    word = str(said or "").strip().replace(".", "")
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    if word in ("midnight",):
        target = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        name = "midnight"
    else:
        hhmm = "12:00" if word in ("noon", "midday") else voice._spoken_time(re.sub(r" ?o'?clock", "", word))
        if not hhmm:
            return None
        bare = word not in ("noon", "midday") and voice._is_bare_hour(re.sub(r" ?o'?clock", "", word))
        try:
            target = dt.datetime.fromisoformat(voice._next_occurrence_iso(hhmm, bare_hour=bare)).astimezone(tz)
        except Exception:
            return None
        name = "noon" if word in ("noon", "midday") else \
            target.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    minutes = int((target - now).total_seconds() // 60)
    hours, mins = divmod(max(minutes, 0), 60)
    span = " and ".join(p for p in (f"{hours} hour{'s' if hours != 1 else ''}" if hours else "",
                                    f"{mins} minute{'s' if mins != 1 else ''}" if mins or not hours else "") if p)
    day = "" if target.date() == now.date() else " tomorrow" if name != "midnight" else ""
    return f"{span[:1].upper() + span[1:]} until {name}{day}."


def _time_zone() -> str:
    """His zone, whether it is on daylight time, and when the clocks next change."""
    import datetime as dt
    from aletheia import localtime
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    name = getattr(tz, "key", None) or str(tz)
    dst = bool(now.dst())
    change = None
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)   # the clocks change at 2 am
    for days in range(1, 370):
        later = noon + dt.timedelta(days=days)
        if bool(later.dst()) != dst:
            change = later.date()
            break
    plain = {"America/New_York": "Eastern", "America/Detroit": "Eastern", "America/Chicago": "Central",
             "America/Denver": "Mountain", "America/Boise": "Mountain", "America/Phoenix": "Arizona",
             "America/Los_Angeles": "Pacific", "America/Anchorage": "Alaska", "Pacific/Honolulu": "Hawaii"}
    name = plain.get(name, name.rsplit("/", 1)[-1].replace("_", " "))
    said = (f"You're on {name} time, {now.strftime('%Z')} right now - "
            + ("daylight saving time is on." if dst else "standard time, not daylight saving."))
    if change:
        said += (f" The clocks go {'back' if dst else 'forward'} an hour on "
                 f"{change.strftime('%A')} the {_ordinal(change.day)} of {change.strftime('%B')}.")
    return said


def _coming_up(when: str = "", calendar_only: bool = False) -> str:
    """What is ahead on his calendar and in his reminders: the next few, or
    the ones inside the day (or the evening) he named."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    rows = [(at.astimezone(tz), text, store) for at, text, store in _coming(now)
            if store == "calendar" or not calendar_only]
    when = str(when or "").strip()
    if when in ("today", "tonight", "this evening"):
        rows = [r for r in rows if r[0].date() == now.date() and (when == "today" or r[0].hour >= 17)]
    elif when == "tomorrow":
        rows = [r for r in rows if r[0].date() == now.date() + dt.timedelta(days=1)]
    else:
        rows = [r for r in rows if r[0] <= now + dt.timedelta(days=7)]
    if not rows and calendar_only:
        return f"No meetings {when}."
    if not rows:
        return {"": "Nothing coming up in the next week - no events and no reminders.",
                "tomorrow": "Nothing on your calendar or in your reminders tomorrow."}.get(
            when, f"Nothing on your calendar or in your reminders {when}.")

    def line(row) -> str:
        at, text, store = row
        clock = at.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
        day = "" if when else ("today " if at.date() == now.date() else "tomorrow " if at.date() == now.date()
                               + dt.timedelta(days=1) else f"{at.strftime('%A')} ")
        said = text.rstrip(".") if store == "calendar" else f"reminder: {text.rstrip('.')}"
        return f"{day}{clock}, {said}"
    lead = speech.count_phrase(len(rows), "meeting" if calendar_only else "thing") + (f" {when}" if when else " coming up")
    return f"{lead}: " + "; ".join(line(r) for r in rows[:5]) + (f"; and {len(rows) - 5} more" if len(rows) > 5 else "") + "."


def _contacts_count() -> str | None:
    from aletheia import speech
    try:
        from aletheia import contacts
        rows = contacts.all_contacts()
    except Exception:
        return None
    if not rows:
        return "No contacts saved yet. Say \"Sam's number is\" and the number, and I'll keep it."
    names = sorted(str(r.get("display_name") or r.get("id")) for r in rows)
    return (f"{speech.count_phrase(len(rows), 'contact')}: " + speech.and_list(names[:8])
            + (f", and {len(rows) - 8} more" if len(rows) > 8 else "") + ".")


def _who_named(name: str) -> str | None:
    """A person he knows, by name: the contact card and his notes about them."""
    from aletheia import speech
    said = []
    try:
        from aletheia import contacts
        person = contacts.resolve(name, contacts.all_contacts())
    except Exception:
        person = None
    if person:
        from aletheia import intercom
        said.append(f"In your contacts: {intercom._contact_words(person)}.")
    words = [w for w in name.casefold().split() if len(w) > 2]
    notes = [str(r.get("text") or "").strip().rstrip(".") for r in _notes()
             if words and all(re.search(rf"\b{re.escape(w)}\b", str(r.get("text") or "").casefold()) for w in words)]
    if notes:
        said.append("You told me: " + "; ".join(speech.as_she_says_it(n) for n in notes[:3]) + ".")
    return " ".join(said) or None


def _alarm_left() -> str:
    """His next alarm and how long until it, from the reminder store."""
    import datetime as dt
    from aletheia import speech
    now = dt.datetime.now(dt.timezone.utc)
    alarms = [at for at, text, store in _coming(now) if store == "reminder" and text.strip().casefold() == "wake up"]
    if not alarms:
        return "No alarm set. Say \"wake me up at 7\" to set one."
    at = alarms[0]
    minutes = int(round((at - now).total_seconds() / 60))
    hours, mins = divmod(max(minutes, 0), 60)
    span = " and ".join(p for p in (f"{hours} hour{'s' if hours != 1 else ''}" if hours else "",
                                    f"{mins} minute{'s' if mins != 1 else ''}" if mins or not hours else "") if p)
    return f"Your alarm goes off {speech.humanize_time(at.isoformat())} - {span} from now."


def _when_mine(what: str) -> str | None:
    """"What time is my dentist appointment": the soonest event or reminder
    naming it, said with when. Every word he named must be in it."""
    from aletheia import speech
    words = [w for w in re.findall(r"[a-z0-9]+", str(what or "").casefold())
             if w not in _STOP_WORDS and w not in ("s", "with", "at", "for")]
    named = [w for w in words if w.rstrip("s") not in _WHEN_NOUNS]
    words = named or words                    # "my dentist appointment" is the dentist
    if not words:
        return None
    for at, text, store in _coming():
        low = text.casefold()
        if all(re.search(rf"\b{re.escape(w.rstrip('s'))}", low) for w in words):
            when = speech.humanize_time(at.isoformat())
            if store == "calendar":
                return f"{text[:1].upper() + text[1:]} is {when}."
            return f"You have a reminder {when}: {text.rstrip('.')}."
    # A note he told her: "the dentist is the 15th at 10" before there was a
    # calendar hold for it (2026-10-07: to the planner, with the note held).
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if all(re.search(rf"\b{re.escape(w.rstrip('s'))}", said.casefold()) for w in words) \
                and re.search(r"\d|day\b|tomorrow|tonight|noon", said.casefold()):
            return f"You told me: {speech.as_she_says_it(said.rstrip('.'))}."
    # Nothing by that name in her stores is not "you have none": it may be
    # in his mail, which a model can read. Only a found answer is quick.
    return None


def _reminders_on(day: str) -> str | None:
    """His reminders and alarms that go off on the day he names."""
    import datetime as dt
    from aletheia import localtime, voice
    iso = voice._spoken_day(day)
    if not iso:
        return None
    tz = localtime.operator_tz()
    rows = [(at.astimezone(tz), text) for at, text, store in _coming() if store == "reminder"
            and at.astimezone(tz).date().isoformat() == iso]
    if not rows:
        return f"No reminders {day if day in ('today', 'tomorrow') else 'on ' + day.capitalize()}."
    said = [f"{at.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower()}, {text.rstrip('.')}" for at, text in rows[:6]]
    from aletheia import speech
    lead = f"{speech.count_phrase(len(rows), 'reminder')} {day if day in ('today', 'tomorrow') else 'on ' + day.capitalize()}: "
    return lead + "; ".join(said) + (f"; and {len(rows) - 6} more" if len(rows) > 6 else "") + "."


def _timer_left(now=None) -> str | None:
    """Time left on every timer still running, soonest first."""
    import datetime as dt
    try:
        from aletheia import scheduler
        specs = scheduler.all_schedules()
    except Exception:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    running = []
    for spec in specs:
        text = str((spec.get("command") or {}).get("text") or "")
        if spec.get("kind") != "once" or not spec.get("enabled") or "timer is up" not in text:
            continue
        try:
            at = scheduler.next_occurrence(spec, now)
        except Exception:
            continue
        if at is not None:
            running.append((at, text))
    if not running:
        return "No timer running."
    running.sort()

    def left(at) -> str:
        seconds = int((at - now).total_seconds())
        if seconds < 60:
            return f"{max(seconds, 1)} second{'s' if seconds != 1 else ''}"
        hours, minutes = divmod((seconds + 30) // 60, 60)
        bits = []
        if hours:
            bits.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            bits.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        return " and ".join(bits) or "under a minute"

    def name(text: str) -> str:
        found = re.search(r"your (.+?) timer is up", text)
        if not found:
            return "your timer"
        # A named one is "the eggs timer" - the same words voice uses.
        called = re.fullmatch(r"\d+(?:[- ]and a half)?[- ](?:minute|hour|second)s?[- ](.+)", found.group(1))
        return f"the {called.group(1)} timer" if called else f"your {found.group(1)} timer"
    lines = [f"{left(at)} left on {name(text)}" for at, text in running[:3]]
    return lines[0][0].upper() + "; ".join(lines)[1:] + "."


def _week_of_year() -> str:
    from aletheia import localtime
    import datetime as dt
    today = dt.datetime.now(localtime.operator_tz()).date()
    week = today.isocalendar()[1]
    return f"Week {week} of {today.isocalendar()[0]}."


def _leap_year(year: str = "") -> str:
    import calendar
    import datetime as dt
    from aletheia import localtime
    this = dt.datetime.now(localtime.operator_tz()).year
    if year == "next":
        return f"{next(y for y in range(this + 1, this + 9) if calendar.isleap(y))}."
    if year:
        n = int(year)
        verb = "is" if n >= this else "was"
        return f"Yes, {n} {verb} a leap year." if calendar.isleap(n) else f"No, {n} {verb}n't a leap year."
    if calendar.isleap(this):
        return f"Yes, {this} is a leap year."
    nxt = next(y for y in range(this + 1, this + 9) if calendar.isleap(y))
    return f"No, {this} isn't. The next leap year is {nxt}."


def _due(when: str = "", now=None) -> str | None:
    """His tasks with a deadline inside the window he named, overdue first."""
    import datetime as dt
    from aletheia import localtime, speech, tasks
    now = now or dt.datetime.now(dt.timezone.utc)
    local = now.astimezone(localtime.operator_tz())
    end_of_today = local.replace(hour=23, minute=59, second=59)
    day = None
    if when in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
        # "What's due Friday" (2026-10-07: to the planner). The coming one.
        from aletheia import voice
        day = dt.date.fromisoformat(voice._spoken_day(when))
    horizon = {"": end_of_today, "today": end_of_today, "soon": end_of_today + dt.timedelta(days=2),
               "tomorrow": end_of_today + dt.timedelta(days=1),
               "this week": end_of_today + dt.timedelta(days=6 - local.weekday()),
               "overdue": now}.get(when) or end_of_today + dt.timedelta(days=(day - local.date()).days)
    hours = max((horizon - now).total_seconds() / 3600, 0)
    try:
        rows = [r for r in tasks.due(now=now, within_hours=hours) if tasks.is_his(r["task"])]
    except Exception:
        return None
    if when == "overdue":
        rows = [r for r in rows if r["overdue"]]
    if when == "tomorrow":
        start = end_of_today
        rows = [r for r in rows if r["overdue"] or r["when"] > start]
    if day is not None:
        rows = [r for r in rows if r["when"].astimezone(local.tzinfo).date() == day]
        when = "on " + when.capitalize()
    if not rows:
        return {"overdue": "Nothing's overdue."}.get(when, f"Nothing due {when or 'today'}.")

    def line(row) -> str:
        what = str(row["task"].get("description") or row["task"].get("id")).strip().rstrip(".")
        return f"{what} (overdue)" if row["overdue"] and when != "overdue" else what
    lead = "overdue" if when == "overdue" else f"due {when or 'today'}"
    return f"{speech.count_phrase(len(rows), 'task')} {lead}: {speech.and_list([line(r) for r in rows[:5]])}."


_COMMON_PLACES = frozenset((
    "airport station mall store shop market hospital clinic office school college campus university park "
    "beach gym church library restaurant cafe hotel stadium arena museum zoo pharmacy bank dentist doctor "
    "vet barber salon work daycare"
).split())


def _place_where(name: str) -> str | None:
    """Where a place he saved is; for a common place he never saved, how to
    tell her. None for anything else, so files and things stay theirs."""
    name = " ".join(str(name or "").casefold().split())
    if not name:
        return None
    try:
        from aletheia import places
        place = places.resolve(name)
    except Exception:
        place = None
    if place and place.get("address"):
        said = places.called(place.get("name") or name)
        return f"{said[:1].upper()}{said[1:]} is at {place['address']}."
    home_of = re.fullmatch(r"([a-z]+)'s (house|place|apartment|flat|home)", name)
    if home_of:
        named = f"{home_of.group(1).capitalize()}'s {home_of.group(2)}"
        return f"I don't know where {named} is. Say \"{named} is at\" and the address, and I'll remember it."
    if name in _COMMON_PLACES:
        named = "work" if name == "work" else f"the {name}"
        return f"I don't know where {named} is. Say \"{named} is at\" and the address, and I'll remember it."
    return None


def _place_addr(name: str) -> str | None:
    name = " ".join(str(name or "").casefold().split())
    if name in ("home", "house", "street"):
        from aletheia import voice
        return voice._where_he_lives()
    said = _place_where(name)
    if said and not said.startswith("I don't know where"):
        return said
    return _recall(name)


def _card() -> str:
    import secrets
    rank = secrets.choice(("Ace", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Jack", "Queen", "King"))
    return f"The {rank} of {secrets.choice(('hearts', 'diamonds', 'clubs', 'spades'))}."


def _rps(text: str) -> str:
    """One round. His throw when he named one; otherwise hers alone."""
    import secrets
    g = _groups("rps", text)
    his = g.get("rps") or g.get("rps2")
    if g.get("rps2"):
        # A bare "paper" is a throw only right after she asked for one.
        try:
            from aletheia import converse
            last = str((converse.recent(limit=1) or [{}])[-1].get("she_answered") or "")
        except Exception:
            last = ""
        if "rock, paper or scissors" not in last.casefold():
            return None
    if not his:
        return "Say rock, paper or scissors, and I'll throw mine at the same time."
    mine = secrets.choice(("rock", "paper", "scissors"))
    beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    result = "a draw" if his == mine else "you win" if beats[his] == mine else "I win"
    return f"{mine.capitalize()} - {result}."


def _coin() -> str:
    import secrets
    return secrets.choice(("Heads.", "Tails."))


_SMALL_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _dice(how_many: str = "") -> str | None:
    import secrets
    n = int(how_many) if str(how_many).isdigit() else _SMALL_NUMBERS.get(str(how_many), 1)
    if not 1 <= n <= 10:
        return None
    rolls = [secrets.randbelow(6) + 1 for _ in range(n)]
    if n == 1:
        return f"{rolls[0]}."
    from aletheia import speech
    return f"{speech.and_list([str(r) for r in rolls])} - {sum(rolls)} in all."


def _pick_number(span: str = "") -> str | None:
    import secrets
    low, high = 1, 10
    if span:
        a, b = (int(x) for x in re.findall(r"\d+", span)[:2])
        low, high = min(a, b), max(a, b)
    if high - low > 10**9:
        return None
    return f"{low + secrets.randbelow(high - low + 1)}."


def _spell(word: str) -> str | None:
    word = str(word or "").strip("'-")
    if not word:
        return None
    return f"{word.capitalize()}: " + ", ".join(ch.upper() for ch in word if ch.isalpha()) + "."


# Kitchen and liquid volumes, in US teaspoons. A US cup is 48 teaspoons and a
# fluid ounce is 6; a millilitre is 1/4.92892 of a teaspoon.
_VOLUMES = {"teaspoon": 1.0, "tsp": 1.0, "tablespoon": 3.0, "tbsp": 3.0, "ounce": 6.0, "fluid ounce": 6.0,
            "fl oz": 6.0, "oz": 6.0, "cup": 48.0, "pint": 96.0, "quart": 192.0, "gallon": 768.0,
            "milliliter": 1 / 4.92892, "millilitre": 1 / 4.92892, "ml": 1 / 4.92892,
            "liter": 1000 / 4.92892, "litre": 1000 / 4.92892, "l": 1000 / 4.92892}
_VOLUME_WORD = (r"(fluid ounces?|fl oz|teaspoons?|tsp|tablespoons?|tbsp|ounces?|oz|cups?|pints?|quarts?|gallons?"
                r"|millilit(?:er|re)s?|ml|lit(?:er|re)s?|l)")


def _volume_unit(word: str) -> str | None:
    word = word.strip()
    if word in _VOLUMES:
        return word
    if word.endswith("s") and word[:-1] in _VOLUMES:
        return word[:-1]
    return None


def _volume(sentence: str) -> str | None:
    """"How many ounces in a cup", "convert 2 cups to ml". None for any
    other "how many" so the rest of the lane and the planner still see it."""
    weight = re.fullmatch(r"how many (?:ounces?|oz) (?:are )?(?:in|is|make) (?:a |an |one |(?P<n>[\d.]+) )?(?:pounds?|lbs?)",
                          sentence)
    if weight:
        # An ounce of weight, not of water: 16 to the pound.
        pounds = float(weight.group("n") or 1)
        return f"{pounds * 16:g} ounces."
    m = (re.fullmatch(r"how many " + _VOLUME_WORD + r" (?:are )?(?:in|make|is|to) (?:a |an |one |(?P<n>[\d.]+|half a|a half) )?"
                      + _VOLUME_WORD, sentence)
         or re.fullmatch(r"(?:convert |what(?:'s| is|s)? )(?P<n>[\d.]+|half a|a half) " + _VOLUME_WORD
                         + r" (?:to|in|into) " + _VOLUME_WORD, sentence))
    if not m:
        return None
    groups = [g for g in m.groups() if g is not None]
    if sentence.startswith("how many"):
        dst, src = _volume_unit(m.group(1)), _volume_unit(m.group(3))
    else:
        src, dst = _volume_unit(m.group(2)), _volume_unit(m.group(3))
    if not src or not dst or src == dst:
        return None
    said_n = m.group("n")
    n = 0.5 if said_n in ("half a", "a half") else float(said_n) if said_n else 1.0
    value = n * _VOLUMES[src] / _VOLUMES[dst]
    shown = round(value, 2) if value < 10 else round(value, 1)
    lead = "About " if abs(shown - value) > 1e-6 else ""
    number = f"{shown:g}"
    full = {"tsp": "teaspoon", "tbsp": "tablespoon", "oz": "ounce", "fl oz": "fluid ounce", "ml": "milliliter",
            "l": "liter", "millilitre": "milliliter", "litre": "liter"}.get(dst, dst)
    return f"{lead}{number} {full if shown == 1 else full + 's'}."


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
    if groups.get("count_window") or groups.get("count2_window"):
        # "How many jobs did I apply to this week" waited two minutes on her
        # own model (2026-09-22); the records carry their dates. "How many
        # did you send this week" is the same count (2026-09-23).
        return "count_window", (groups.get("count_window") or groups["count2_window"]).strip()
    for key, value in groups.items():
        if key.startswith("count"):
            total = bool(groups.get("count_total") or groups.get("count2_total"))
            return ("count_total" if total else "count"), "the job hunt"
        if key.startswith("going"):
            return "going", value
        if key.startswith("still"):
            return "still", value
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
        else:
            said = current_state.repo_words(subject)
            if said is None and _no_pulse():
                # "Is the trader running" with the pulse unwritten went to a
                # model that knows no trader (2026-09-23 night sweep).
                return "No fleet reading yet - the pulse hasn't been written on this machine, so I can't say."
            if said is None:
                # A project she carries for him is not always a repository
                # the pulse names: "how's Barkly going" answered nothing
                # while its charter held the next step (2026-10-07).
                said = _project_next(subject)
            return said
    if shape == "going":
        return current_state.job_hunt_words()
    if shape == "count_window":
        return _applied_in_window(subject)
    if shape == "still":
        return current_state.still_applying_words()
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
    return f"I don't have an application to {words}."


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
        for key in ("first_name", "last_name", "current_title", "current_employer", "city", "state",
                    "school", "degree", "years_experience"):
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
    # HIS NOTES ABOUT HIMSELF. "Remember that my car is a 2014 civic" is
    # kept as a note, and "what do you know about me" answered "Nothing
    # yet" a turn later (2026-10-07). A note in his first person is about
    # him; said back in hers.
    try:
        for row in _notes(60):
            line = " ".join(str(row.get("text") or "").split()).rstrip(".")
            if re.match(r"(?i)(?:my|i|i'm|i am|i've)\b", line):
                facts.append(speech.as_she_says_it(line))
            if len(facts) >= 12:
                break
    except Exception:
        pass
    if not facts:
        return "Nothing yet. Tell me things and I'll remember them; a resume teaches me a lot at once."
    return "Here's what I have: " + speech.and_list(facts[:12]) + "."


def _about_the_talk(asked: str) -> bool:
    """A turn about the conversation itself - "what did I ask", "say that
    again", "thanks", "slower" - which is never the thing he means when he
    asks what he asked or what she said (2026-10-07: "what did I ask you
    earlier" answered "thanks", and "say that again" repeated that)."""
    low = " ".join(re.sub(r"^(?:thea|aletheia),? ", "", str(asked or ""), flags=re.IGNORECASE).casefold().split()).rstrip(" ?.!")
    if not low:
        return True
    if _REPEAT_ASK.fullmatch(low) or any(n in ("talked_about", "asked_last", "repeat") and p.match(_tidy(low))
                                         for n, p in PATTERNS):
        return True
    return bool(re.fullmatch(r"(?:thanks?(?: you)?(?: (?:so|very) much)?|thank u|ty|cheers|ok(?:ay)?|cool|got it|nice|great|"
                             r"alright|all right|sounds good|perfect|awesome|never ?mind|nevermind|"
                             r"(?:a (?:little |bit )?)?(?:slower|faster|louder|quieter)(?: please)?|"
                             r"(?:talk|speak) (?:slower|faster|louder|quieter|up)|yes|no|yeah|nope|sure)", low))


def _repeat() -> str:
    """Her last sentence, from the thread, said again."""
    # It read a key the thread never had ("she_said"), so "repeat that" said
    # "I haven't said anything yet" after every answer she ever gave
    # (2026-10-07). The thread keeps "you" and "her", in full.
    try:
        from aletheia import converse
        turns = converse._thread()
    except Exception:
        turns = []
    for turn in reversed(turns or []):
        if _about_the_talk(str(turn.get("you") or "")):
            continue                   # "repeat that" twice says the same thing twice
        said = str(turn.get("her") or "").strip()
        if said:
            return f"I said: {said}"
    return "I haven't said anything yet this conversation."


def _asked_last(first: bool = False) -> str:
    """His last sentence before this one (or the first of today's), from
    the thread, in his words."""
    try:
        from aletheia import converse
        turns = converse._thread()
    except Exception:
        turns = []
    if first:
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()

        def on_today(turn):
            try:
                return dt.datetime.fromisoformat(str(turn.get("at") or "").replace("Z", "+00:00")).astimezone(tz).date() == today
            except ValueError:
                return True
        dated = [t for t in turns or [] if on_today(t)]
        turns = dated
    for turn in (turns if first else reversed(turns or [])):
        asked = " ".join(str(turn.get("you") or "").split())
        bare = re.sub(r"^(?:thea|aletheia),? ", "", asked, flags=re.IGNORECASE)
        if _about_the_talk(bare):
            continue
        return f"You asked: \u201c{bare.rstrip().rstrip('.')}.\u201d"
    return "You haven't asked me anything yet this conversation."


def _talked_about() -> str:
    """The last few things he asked, in his words, oldest first."""
    try:
        from aletheia import converse
        turns = converse._thread()
    except Exception:
        turns = []
    said, seen = [], set()
    for turn in reversed(turns or []):
        asked = re.sub(r"^(?:thea|aletheia),? ", "", " ".join(str(turn.get("you") or "").split()),
                       flags=re.IGNORECASE).rstrip(" ?.!")
        if not asked or asked.casefold() in seen or _about_the_talk(asked):
            continue
        seen.add(asked.casefold())
        said.append(f"\u201c{asked}\u201d")
        if len(said) == 4:
            break
    if not said:
        return "We haven't talked about anything yet this conversation."
    from aletheia import speech
    return "You asked me " + speech.and_list(list(reversed(said))) + "."


#: Asking her to say it again, so the thread can step past those turns.
_REPEAT_ASK = re.compile(r"(?:can you |could you |please )?(?:repeat that|repeat|say (?:that|it) again|"
                         r"what did (?:you|u) (?:just )?say|come again|pardon|sorry,? what|what was that|say again|"
                         r"one more time|i didn'?t (?:catch|hear) that)(?: please)?")


def _person(rest: str) -> str:
    """"Who is my landlord": the person remembered under that word."""
    from aletheia import memory
    who = " ".join(str(rest or "").split()).strip(" ,.?")
    try:
        found = memory.recall("people", who) or memory.recall("people", who.replace(" ", "_"))
    except Exception:
        found = None
    if found:
        return f"Your {who} is {found}."
    # "REMEMBER THAT MY LANDLORD IS SAM ORTIZ" is kept as a note, and one turn
    # later "who is my landlord" answered "I don't have anyone remembered as
    # your landlord. Tell me and I'll remember it" - he just had. The note says
    # it in his own words; read it the way he said it.
    if who:
        said = re.compile(r"\bmy " + re.escape(who.casefold()) + r"(?:'s name)? (?:is|was|=) (.+)", re.IGNORECASE)
        # "Dana is my sister" - the other order (2026-10-07).
        other = re.compile(r"^\s*([A-Za-z][\w'-]*(?: [A-Za-z][\w'-]*)?) is my (?:new |old |best |younger |older |little |big )?"
                           + re.escape(who.casefold()) + r"\b", re.IGNORECASE)
        for row in _notes():
            m = said.search(str(row.get("text") or ""))
            if m:
                return f"Your {who} is {m.group(1).strip().rstrip('.')}."
            m = other.search(str(row.get("text") or ""))
            if m:
                name = m.group(1).strip()
                return f"Your {who} is {name[:1].upper() + name[1:]}."
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


def _computer_ok() -> str:
    """Memory, disk and processor in one breath, leading with the verdict."""
    from aletheia import machine
    worries, readings = [], []
    try:
        found = machine.memory()
        total, free = int(found.get("total") or 0), int(found.get("available") or 0)
        if total:
            readings.append(f"{machine.gigabytes(free)} of memory free")
            if free < 2 * 1024 ** 3:
                worries.append("memory is tight")
    except Exception:
        pass
    try:
        found = machine.disk()
        total, free = int(found.get("total") or 0), int(found.get("free") or 0)
        if total:
            readings.append(f"{machine.gigabytes(free)} free on the drive")
            if free < 10 * 1024 ** 3:
                worries.append("the drive is nearly full")
    except Exception:
        pass
    try:
        import psutil
        load = psutil.cpu_percent(interval=0.5)
        readings.append(f"the processor at {load:.0f}%")
        if load >= 90:
            worries.append("the processor is maxed out")
    except Exception:
        pass
    if not readings:
        return "I can't read this computer's health right now."
    from aletheia import speech
    lead = ("It looks fine" if not worries
            else "One thing: " + speech.and_list(worries) if len(worries) == 1
            else "A few things: " + speech.and_list(worries))
    return f"{lead} - {speech.and_list(readings)}."


def _week() -> str:
    """His tasks finished since Monday and what she did, from the stores."""
    import datetime as dt
    from aletheia import localtime, speech
    done = _tasks_done("this week")
    today = dt.datetime.now(localtime.operator_tz()).date()
    rows = []
    for back in range(today.weekday(), -1, -1):
        try:
            rows.extend(_on_day(back))
        except Exception:
            continue
    mine = (_listed(rows, "this week").replace("This week: ", "What I did this week: ", 1) if rows
            else "I have nothing in my journal for this week.")
    yours = done if not done.startswith("Nothing ticked") else "You haven't ticked anything off this week."
    return f"{yours} {mine}"


def _memory_users() -> str:
    """The biggest programs by memory, and how much is free, in one breath."""
    from aletheia import machine, speech
    users = machine.memory_users(4)
    try:
        found = machine.memory()
        free, total = int(found.get("available") or 0), int(found.get("total") or 0)
    except machine.UnknownMachine:
        free = total = 0
    if not users:
        return "I can't see what's running on this computer right now."
    named = speech.and_list([f"{name} with {machine.gigabytes(size)}" for name, size in users])
    said = f"The biggest are {named}"
    if total:
        said += f". {machine.gigabytes(free)} of {machine.gigabytes(total)} is free"
        if free < 2 * 1024 ** 3:
            said += " - that's tight, so closing the top one would help most"
        elif free > 0.3 * total:
            said += ", so memory isn't what's slowing it down"
    return said + ". I don't close programs myself; that could lose your work."


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
    # The weather, the way a person mentions it in the morning - only when
    # she can actually read it; a greeting never recites an error.
    try:
        from aletheia import weather
        code, _name = weather.where_he_is()
        if code:
            data = weather.forecast()
            first = (data.get("periods") or [None])[0]
            if first:
                short = str(first.get("shortForecast") or "").strip().rstrip(".")
                parts.append(f"Outside it's {short.lower()}, {first.get('temperature')} degrees.")
    except Exception:
        pass
    return " ".join(parts)


ANSWERS = {"halted": lambda rest: _halted(asks_if_down=bool(rest)),
           "power": lambda rest: _power(rest),
           "joke": lambda rest: _joke(),
           "meal_idea": lambda rest: _meal_idea(rest),
           "parked": lambda rest: _parked(),
           "fact_q": lambda rest: _fact_q(rest),
           "help": lambda rest: HELP,
           "sun": lambda rest: _sun(rest),
           "note_search": lambda rest: _note_search(rest),
           "moon": lambda rest: _moon(rest),
           "discount": lambda rest: _discount(rest),
           "split": lambda rest: _split(rest),
           "area": lambda rest: _area(rest),
           "year_left": lambda rest: _year_left(rest),
           "weekday_of": lambda rest: _weekday_of(rest),
           "days_between": lambda rest: _days_between(rest),
           "time_diff": lambda rest: _time_diff(rest),
           "crisis": lambda rest: CRISIS,
           "feeling": lambda rest: _feeling(rest),
           "about_her": lambda rest: _about_her(rest),
           "arith": lambda rest: _arith(rest),
           "prime": lambda rest: _prime(rest),
           "average": lambda rest: _average(rest),
           "round_to": lambda rest: _round_to(rest),
           "time_units": lambda rest: _time_units(rest),
           "fraction_pct": lambda rest: _fraction_pct(rest),
           "fun_fact": lambda rest: _pick(FUN_FACTS),
           "quote": lambda rest: _pick(QUOTES),
           "rain": lambda rest: _rain(rest),
           "timer_left": lambda rest: _timer_left(),
           "week_of_year": lambda rest: _week_of_year(),
           "due": lambda rest: _due(rest),
           "leap_year": lambda rest: _leap_year(rest),
           "coin": lambda rest: _coin(),
           "card": lambda rest: _card(),
           "rps": _rps,
           "place_where": lambda rest: _place_where(rest),
           "place_addr": lambda rest: _place_addr(rest),
           "did_last": _did_last,
           "owed": lambda rest: _owed(rest),
           "birthdays": lambda rest: _birthdays_coming(rest),
           "birthday_when": lambda rest: _birthday_when(rest),
           "task_due": lambda rest: _task_due(rest),
           "arith_more": _arith_more,
           "fractions": _fractions,
           "dice": lambda rest: _dice(rest),
           "pick_number": lambda rest: _pick_number(rest),
           "spell": lambda rest: _spell(rest),
           "volume": lambda rest: _volume(rest),
           "until_weeks": lambda rest: _until_weeks(rest),
           "tip": lambda rest: _tip(rest),
           "currency": lambda rest: _currency(rest),
           "off_switch": lambda rest: OFF_SWITCH,
           "riddle": lambda rest: _riddle(),
           "count_to": lambda rest: _count_to(rest),
           "alarm_q": lambda rest: _alarms(),
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
           "outcomes": _outcomes,
           "until": _until,
           "race": lambda rest: _race(rest),
           "age_in": lambda rest: _age_in(_groups("age_in", rest).get("age_year", ""),
                                          _groups("age_in", rest).get("age_n", "")),
           "until_day": lambda rest: _until(rest, which_day=True),
           "weeks_until": lambda rest: _weeks_until(rest),
           "tasks_due": lambda rest: _tasks_due(rest),
           "birthday": lambda rest: _birthday(),
           "calendar_fact": lambda rest: _calendar_fact(rest),
           "sent_window": lambda rest: _applied_in_window(_night_words(rest)),
           "time_in": _time_in,
           "time_there": lambda rest: _time_there(),
           "date_of": _date_of,
           "overnight": lambda rest: _overnight(),
           "updated": lambda rest: _updated(),
           "last": lambda rest: _last(),
           "disk": lambda rest: _disk(),
           "ip": lambda rest: _ip(),
           "internet": lambda rest: _internet(),
           "windows": lambda rest: _windows(),
           "opportunity": _opportunity,
           "unattended": lambda rest: _unattended(),
           "pursuit_count": lambda rest: _pursuit_count(),
           "opportunity_loose": _opportunity_loose,
           "applied_to": lambda rest: _applied_to(),
           "applied_when": _applied_when,
           "about_him": lambda rest: _about_him(),
           "person": _person,
           "who_named": lambda rest: _who_named(rest),
           "contacts_count": lambda rest: _contacts_count(),
           "repeat": lambda rest: _repeat(),
           "asked_last": lambda rest: _asked_last(first=" first thing " in f" {rest} "),
           "talked_about": lambda rest: _talked_about(),
           "sent_today": lambda rest: _sent_today(),
           "machine": lambda rest: _machine(),
           "computer_ok": lambda rest: _computer_ok(),
           "week": lambda rest: _week(),
           "tasks_done": lambda rest: _tasks_done(rest),
           "task_progress": lambda rest: _task_progress(),
           "task_top": lambda rest: _task_top(),
           "tasks_clear_done": lambda rest: ("Finished tasks are already off your list - I keep them only as a "
                                             "record of what you did, so there's nothing to clear."),
           "memory_users": lambda rest: _memory_users(),
           "work_blocked": lambda rest: _work_listed("blocked"),
           "work_queue": lambda rest: _work_listed("executable_now"),
           "projects": lambda rest: _projects(),
           "project_next": lambda rest: _project_next(rest),
           "waiting": lambda rest: _waiting(),
           "doing": lambda rest: _doing(),
           "job_hunt": lambda rest: _job_hunt(),
           "wrong": lambda rest: _wrong(),
           "today": lambda rest: _today(rest),
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
           "tasks": lambda rest: _tasks(),
           "approvals": lambda rest: _approvals(),
           "capabilities": lambda rest: _capabilities(),
           "cannot": lambda rest: _cannot(),
           "agenda": lambda rest: _agenda_and_reminders(rest or "today"),
           "agenda_more": lambda rest: _agenda(rest or "today"),
           "first_meeting": lambda rest: _first_meeting(rest or "today"),
           "recall_when": lambda rest: (lambda said: None if not said or said.startswith("I have nothing") else said)(_recall(rest)),
           "last_meeting": lambda rest: _last_meeting(rest or "today"),
           "agenda_on": lambda rest: _agenda_on(rest),
           "days_since": lambda rest: _days_since(rest),
           "weekend_q": lambda rest: _weekend_q(rest),
           "date_after": lambda rest: _date_after(rest),
           "born_in": lambda rest: _born_in(rest),
           "double_booked": lambda rest: _double_booked(),
           "how_many": lambda rest: _how_many(),
           "alerts": lambda rest: _alerts(),
           "repo_wrong": _repo_wrong,
           "fleet_read_at": lambda rest: _fleet_read_at(),
           "repos": lambda rest: _repos(),
           "shopping": lambda rest: _shopping(),
           "uptime": lambda rest: _uptime(),
           "version": lambda rest: _version(),
           "shopping_has": lambda rest: _shopping_has(rest),
           "shopping_need": lambda rest: _shopping_need(rest),
           "note_last": lambda rest: _note_last(),
           "notes_day": lambda rest: _notes_day(rest),
           "battery": lambda rest: _battery(),
           "free": _free,
           "free_at": lambda rest: _free_at(rest),
           "reckon": lambda rest: _reckon(rest),
           "days_left": lambda rest: _days_left(rest),
           "next_meeting": lambda rest: _next_meeting(),
           "next_detail": lambda rest: _next_detail(rest),
           "took_today": lambda rest: _took_today(rest),
           "pct_of": lambda rest: _pct_of(rest),
           "fraction_dec": lambda rest: _fraction_dec(rest),
           "roman": lambda rest: _roman(rest),
           "height_cm": lambda rest: _height_cm(rest),
           "time_convert": lambda rest: _time_convert(rest),
           "on_the_last": lambda rest: _on_the_last(rest),
           "age_of": lambda rest: _age_of(rest),
           "day_span": lambda rest: _day_span(rest),
           "running": lambda rest: _running(),
           "mine": _mine,
           "call_me": lambda rest: _call_me(),
           "hunting_for": lambda rest: _hunting_for(),
           "work_wants": lambda rest: _work_wants(),
           "humidity": lambda rest: _weather_detail("humidity", rest),
           "wind": lambda rest: _weather_detail("wind", rest),
           "news": lambda rest: _news(),
           "stopwatch": lambda rest: _stopwatch(),
           "stopwatch_it": lambda rest: _stopwatch_running(),
           "holiday_next": lambda rest: _holiday_next("list" if rest in ("holidays", "upcoming") or rest.startswith("next") else rest),
           "workdays_until": _workdays_until,
           "logged": _logged,
           "speaking_pace": lambda rest: _speaking_pace(),
           "weather": lambda rest: _weather(rest),
           "weather_more": lambda rest: _weather_more(rest),
           "weather_in": lambda rest: _weather_in(rest),
           "define": lambda rest: _define(rest),
           "when_mine": lambda rest: _when_mine(rest),
           "alarm_left": lambda rest: _alarm_left(),
           "coming_up": lambda rest: _coming_up(rest),
           "meetings_count": lambda rest: _coming_up(rest, calendar_only=True),
           "clock_until": lambda rest: _clock_until(rest),
           "time_zone": lambda rest: _time_zone(),
           "reminders_on": lambda rest: _reminders_on(rest),
           "greeting": lambda rest: _greeting(),
           "home": lambda rest: _home(),
           "notes_list": lambda rest: _notes_list(),
           "drafts": lambda rest: _drafts(),
           "sending": lambda rest: _sending(rest),
           "draft_to": lambda rest: _draft_to(rest),
           "applied_on": _applied_on,
           "asked_on": _asked_on,
           "hunt_why": lambda rest: _hunt_why(),
           "who_are_you": lambda rest: _who_are_you(),
           "her_name": lambda rest: "Thea - short for Aletheia.",
           "offline_can": lambda rest: _offline_can(),
           "memory_free": lambda rest: _memory_free(),
           "recall": _recall,
           "recall_owned": _recall,
           "friction": lambda rest: _friction(),
           "replies": lambda rest: _replies(),
           "slow": lambda rest: _slow(),
           "arrival": lambda rest: _arrival(),
           "farewell": _farewell,
           "math": lambda rest: _math(rest) or _reckon(rest),   # a kitchen sum math cannot settle
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
    r"last week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    # "And the weekend?" after the weather (2026-10-07: to the planner).
    r"(?:this |the |next )?weekend)\b")
_FOLLOW_UP = re.compile(r"^(?:and|what about|how about|and what about|and how about)(?: on| for)?\s+(?P<x>.+?)$")
_LIST_THEM = re.compile(r"^(?:read|list|show|name)(?: me)? (?:them|those|these)(?: out| to me| all)?$"
                        r"|^(?:what|which) (?:are they|ones(?: are they)?)$")
#: A follow-up "read them" after a turn about one of these stores.
_STORE_QUESTION = {
    "tasks": "what's on my task list", "task_new": "what's on my task list", "task_done": "what's on my task list",
    "task_change": "what's on my task list",
    "reminders": "what reminders do I have", "remind_at": "what reminders do I have",
    "remind_daily": "what reminders do I have", "remind_weekly": "what reminders do I have",
    "remind_monthly": "what reminders do I have",
    "remind_every": "what reminders do I have",
    "shopping_list": "what's on the shopping list", "shopping_add": "what's on the shopping list",
    "list_new": "what's on my packing list", "list_add": "what's on my packing list",
    "list_off": "what's on my packing list", "list_read": "what lists do I have",
    "stopwatch": "how long has the stopwatch been running", "stopwatch_read": "how long has the stopwatch been running",
    "speaking_pace": "how fast are you talking", "speaking_pace_read": "how fast are you talking",
    "notes_list": "read me my notes", "note": "read me my notes", "drafts": "what drafts do you have",
    "applied_to": "what did you apply to", "applied_on": "what did you apply to",
    "notify_count": "what's waiting on me", "outcomes": "what did you apply to",
}


def _previous_ask(skip_follow_ups: bool = True, questions_only: bool = False) -> str:
    """His last full sentence from the thread (never a follow-up itself).
    `questions_only` steps over sentences no store answers: "what's the
    weather", "my zip is 78701", "what about tomorrow" means the weather
    (2026-10-07: it went to the planner, rebuilt from the zip)."""
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
        if questions_only and not match(said):
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
    prev = _previous_ask(questions_only=True)
    if not prev:
        return None
    rebuilt = ""
    if _DAY_PHRASE.fullmatch(new_words):
        days = list(_DAY_PHRASE.finditer(prev))
        if days:
            last = days[-1]
            rebuilt = prev[:last.start()] + new_words + prev[last.end():]
        else:
            # "What's the weather" then "how about tomorrow": the first ask
            # named no day, so the day is ADDED (2026-10-07). Kept only if
            # the result is still a question a store answers - checked below.
            rebuilt = f"{prev} {new_words}"
    # "And the second one" counts items she read out; it is never a new
    # subject to put into the last question ("when is second one due").
    if not rebuilt and re.search(r"\b(?:first|second|third|fourth|last|other|next) one\b|^(?:the )?(?:other|next)$", new_words):
        return None
    if not rebuilt:
        shape = status_of(prev)
        subject = shape[1] if shape and shape[0] == "repo" else ""
        if not subject:
            found = match(prev)
            subject = found[1] if found and found[1] and found[1] != prev else ""
        if subject and subject in prev:
            # "And in Tokyo?" after "what time is it in london": the "in" is
            # already in the sentence, so it is not said twice.
            rebuilt = prev.replace(subject, re.sub(r"^(?:in |at |for |on )?(?:the |my )?", "", new_words), 1)
        elif " in " not in f" {prev} ":
            # "What time is it" then "and in Tokyo" / "how about London":
            # the place is ADDED - kept only when the result is a question
            # about a place, so "how about pizza" stays with a model.
            place = re.sub(r"^in ", "", new_words)
            tried = f"{prev} in {place}"
            if (match(tried) or ("", ""))[0] in ("time_in", "time_in2", "time_in3", "weather_in"):
                rebuilt = tried
    if not rebuilt or rebuilt == prev or not match(rebuilt):
        return None
    return answer(rebuilt)


def answer(question: str) -> str | None:
    """An answer from her own stores, or None to go and think.

    Never raises. A fast path that can break a request is worse than no
    fast path — the slow one was working.
    """
    try:
        found = match(question)
        if not found:
            return _follow_up(question)
        name, rest = found
        said = ANSWERS[name](rest)
        # `str(None)` is the four-character string "None", which is truthy
        # and would have been spoken out loud as an answer.
        if said is None:
            return None
        return str(said).strip() or None
    except Exception:
        return None
