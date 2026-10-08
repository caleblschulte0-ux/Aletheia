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


#: What he takes by the pill and counts by the name.
_MEDS = ("advil", "tylenol", "ibuprofen", "aspirin", "aleve", "motrin", "excedrin", "acetaminophen", "naproxen",
         "melatonin", "benadryl", "claritin", "zyrtec")


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
        from aletheia.voice import _apostrophes
        return _apostrophes(re.sub(r"^(?:%s)\b[\s,.!?:;]*" % "|".join(WAKE_WORDS), "", _without_preamble(text)))
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

# Medicines he names by name, shared with `voice`'s note for taking one.
#: People whose word he passes on by their role ("the doctor said ..."),
#: kept as a note and read back by "what did the doctor say".
_ROLES_WHO_TELL = (r"doctor|doc|dentist|vet|mechanic|boss|manager|teacher|landlord|lawyer|accountant|plumber|electrician"
                   r"|contractor|coach|therapist|nurse|pharmacist|surgeon|realtor|agent|recruiter|counselor|principal|trainer")

_DRUGS = (r"ibuprofen|advil|motrin|tylenol|acetaminophen|paracetamol|aspirin|aleve|naproxen|excedrin|benadryl|claritin"
          r"|zyrtec|allegra|melatonin|nyquil|dayquil|sudafed|mucinex|tums|pepto|imodium|prilosec|zantac|pepcid"
          r"|lisinopril|metformin|amoxicillin|prednisone|adderall|zoloft|lexapro|wellbutrin|xanax|levothyroxine"
          r"|atorvastatin|lipitor|omeprazole|insulin|antihistamines?|antacids?|cough syrup|allergy pills?|painkillers?")

# Things done TO him, which he says he got or had: "I got a haircut".
_SERVICES = (r"(?:a |an |my |the )?(?:haircut|hair cut|trim|oil change|flu shot|flu jab|covid (?:shot|booster|vaccine)|booster"
             r"|tetanus shot|massage|checkup|check-up|physical|manicure|pedicure|car wash|eye exam|teeth cleaning|dental cleaning"
             r"|tune-?up|inspection|blood test|blood work|mammogram|colonoscopy|tattoo|facial|wax"
             # "I got new tires today" (2026-10-08: to the planner)
             r"|new tires|new tyres|new brakes|brakes done|tires rotated|tire rotation|alignment|new battery|new wipers)")

PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    # FIRST, before anything else can claim the sentence: a person in
    # crisis must never be filed as a work item "for when the big models
    # are back" (2026-10-07: "I'm sad" was).
    ("crisis", re.compile(
        r"^(?:i|i'm|im|i am) (?:want to|wanna|going to|gonna|am going to|feel like|thinking about|thinking of|"
        r"just want to|really want to) (?:die|dying|kill(?:ing)? myself|end(?:ing)? (?:it all|my life)|hurt(?:ing)? myself|be dead)$"
        r"|^(?:i'm|im|i am|i feel|feeling) (?:suicidal|thinking about suicide)$"
        r"|^i don'?t want to (?:live|be alive|be here) anymore$")),
    # "What's my password for Netflix" said "I don't have anything
    # remembered about password for netflix" (2026-10-07), as if one could
    # be. She never keeps a password; said the same way every time.
    ("no_password", re.compile(
        r"^(?:what(?:'s| is|s| was)|tell me|give me|read me|do you (?:know|have|remember)|remind me(?: of)?) (?:my |the |our )?"
        r"(?:[a-z0-9][a-z0-9 '-]{0,30} )?(?:password|passcode|passphrase)(?: (?:for|to|on) (?:my |the |our )?[a-z0-9][a-z0-9 '-]{0,30})?\s*\??$")),
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
        # "Anything waiting on me", "what needs my attention" (2026-10-07: to a model).
        r"|^(?:is |are )?(?:there )?(?:anything|something|things) waiting (?:on|for) me(?: right now| now| today)?\s*\??$"
        r"|^(?:what|does anything|anything|is there anything that) needs? my attention(?: right now| now| today)?\s*\??$"
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
        # "Which of those is most urgent" after his list (2026-10-08: to a model).
        r"|^(?:which|what) (?:of (?:those|them|these)|one|task)(?: of (?:those|them))? (?:is|should i do|do i do) (?:the )?"
        r"(?:most (?:urgent|important|pressing)|first|top priority|priority)$"
        r"|^what can i (?:do|get done|knock out) in (?:the next )?(?:\d{1,3}|half an|an|a few) (?:minutes?|hours?|mins?)$"
        # "Prioritize my tasks", "I have 30 minutes free what should I do"
        # (2026-10-07: to the planner).
        r"|^(?:prioriti[sz]e|rank|order|sort) my (?:tasks|to ?dos?|to-dos?|list|to do list|day)(?: for me)?$"
        r"|^i(?:'ve| have)? (?:got )?(?:\d{1,3}|half an|an|a few) (?:minutes?|mins?|hours?)(?: free| to kill| spare)?,?"
        r" what should i (?:do|work on|tackle)$")),
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
        # "How many days since I started my new job" was read as an
        # application called "many days since I started my new" (2026-10-07):
        # a "how" question about anything else is not one.
        r" (?:the |my |our )?(?!(?:many|much|long|old|far|often|soon|have|has|had|did|do|does|can|could|should|am|was|were|will|would)\b)"
        r"(?P<what>.+?) (?:application|app|job|role|opportunity|position|posting)(?: going| doing| looking)?$")),
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
        # "Where was I" (2026-10-07: to a model) - the thread picks up here.
        r"|^where (?:was i|were we)$|^what (?:was i|were we) (?:doing|talking about)$"
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
        r"|say (?:it|that) one more time|can you repeat that|could you repeat that"
        # "Say that again slower" (2026-10-07: to the planner).
        r"|(?:say (?:it|that) again|repeat (?:it|that)) (?:slower|more slowly|slowly)(?: please)?"
        # "Read it again" (2026-10-07: to the planner).
        r"|read (?:it|that|them) (?:again|back)|again please|one more time please"
        # A bare "what?" or "huh?" (2026-10-07: to a model).
        r"|what|huh|eh|wait what|hm what)\??$")),
    # "Who is my landlord" came back from her own model as "no lease or
    # rental info connected here" - a capability she has, denied. The
    # person is remembered or he is asked, in words, never a model's guess.
    # "Who is Dana" (2026-10-07: to the planner) - her contact card and his
    # notes about them. Neither found is NOT "nobody": it may be someone
    # famous, so it goes on to a model.
    # "What's the last thing I told you", "did I tell you about my trip"
    # (2026-10-07: a model and the planner, with the notes right there).
    ("told_last", re.compile(
        r"^what(?:'s| is| was) the last thing i (?:told you|said|asked you to remember|had you (?:note|remember))\s*\??$"
        r"|^(?:did|have) i (?:ever |already )?(?:tell|told) you about (?P<told_about>[a-z][a-z0-9' ]{1,40}?)\s*\??$")),
    # "What does Sam like" (2026-10-07: to a model, after "Sam likes coffee").
    ("their_likes", re.compile(
        r"^what (?:does|do) (?P<tl_who>(?:my |our )?(?!(?:i|we|you|he|she|it|they)\b)[a-z][a-z']{1,20}) (?P<tl_verb>like|love|hate|enjoy|collect|not like)"
        r"(?: (?:to (?:eat|drink|do))| best| most)?\s*\??$")),
    # "What flowers does Anna like" (2026-10-08: to a model): her favorite
    # flower, or what he said she likes, when he told her.
    ("their_kind", re.compile(
        r"^what (?:kind of |kinds of |type of |sort of )?(?P<tk_what>[a-z]{3,20}?)(?:e?s)? (?:does|do) (?P<tk_who>(?:my |our )?(?!(?:i|we|you|he|she|it|they)\b)[a-z][a-z']{1,20})"
        r" (?:like|love|prefer|enjoy)(?: best| most)?\s*\??$")),
    # "How many miles until my oil change" (2026-10-08: to a model): the
    # mileage it is due at, less the last mileage he told her.
    ("miles_until", re.compile(
        r"^how (?:many|much) (?:more )?(?:miles|mi) (?:until|till|before|to|left (?:until|before|till)) (?:my |the |our )?(?:next )?"
        r"(?P<mu_what>oil change|service|tune-?up|tire rotation|inspection|timing belt)(?: is due)?\s*\??$")),
    # "How many pills do I have left", "when will I run out of my pills"
    # (2026-10-08: to a model). His count, less his daily dose since.
    ("pills_left", re.compile(
        r"^(?:how many (?:pills|tablets|capsules|doses) (?:do i have|have i got|are) left"
        r"|when (?:will|do|am) i (?:going to )?run(?:ning)? out(?: of (?:my )?(?:pills|tablets|capsules|meds|medicine|medication))?"
        r"|how long (?:will|do) my (?:pills|tablets|meds|medicine) last)\s*\??$")),
    # "How long is my vacation" (2026-10-08: to a model): the days between
    # the two dates his note gives it.
    ("trip_length", re.compile(
        r"^how (?:long|many days|many nights) (?:is|will be|are) (?:my |our |the )(?P<tl_what>vacation|holiday|trip|cruise|honeymoon)"
        r"(?: (?:going to be|for))?\s*\??$")),
    ("their_fact", re.compile(
        r"^(?:who|what)(?:'s| is|s) (?P<tf_who>(?:my )?[a-z][a-z']{1,20})(?:'s|s') (?P<tf_key>teacher|school|coach|pediatrician|doctor|dentist"
        r"|class|grade|team|best friend|nickname|shoe size|clothes size|shirt size|bedtime|daycare|babysitter|nanny|tutor|vet"
        r"|middle name|last name)(?: name)?\s*\??$"
        r"|^what (?P<tf_key2>school|grade|class|daycare) (?:does|is) (?P<tf_who2>(?:my )?[a-z][a-z']{1,20}) (?:go to|in|at)\s*\??$"
        r"|^what (?:is|are) (?P<tf_who3>(?:my )?[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) (?P<tf_allergy>allergic to)\s*\??$")),
    # "Who's coming for Thanksgiving" (2026-10-07: to a model, with "my
    # in-laws are coming for Thanksgiving" kept).
    ("who_coming", re.compile(
        r"^who(?:'s| is| are) (?:coming over|coming to visit|coming|visiting|staying with us)"
        # "Who's coming Saturday" (2026-10-08) was a person called "coming saturday"
        r"(?: (?:(?:for|on|over|this|to|at) )?(?P<who_coming>[a-z][a-z' ]{1,30}?))?\s*\??$")),
    ("who_named", re.compile(
        r"^who(?:'s| is) (?!(?:my|the|your|you|u|that|this|it|he|she|they|i|we|on|in|at|calling|there|here|next|"
        r"waiting|running|online)\b)(?P<who_named>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)\s*\??$"
        # "How do I know Sam" (2026-10-07: to a model) - what he told her.
        r"|^how do i know (?!(?:that|this|it|if|when|what|which|where|whether|how)\b)(?P<who_named2>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)\s*\??$")),
    ("contacts_count", re.compile(
        r"^how many (?:contacts|people) (?:do i have|have i got|are in my contacts|have i saved|are saved)\s*\??$"
        # "Who are my contacts" (2026-10-07: to a model)
        r"|^(?:who(?:'s| is| are)(?: in)? my contacts|(?:list|show me|read me|read|show) (?:all )?my contacts"
        r"|what contacts do i have|who do i have (?:saved|in my contacts))\s*\??$")),
    # "Where do I work" after "I work at Acme" (2026-10-07: to a model).
    # "What's a synonym for happy", "the opposite of hot" (2026-10-07: to a
    # model). The dictionary lists both; one it lists none for still goes on.
    ("synonym", re.compile(
        r"^(?:what(?:'s| is|s| are)? )?(?:a |some )?(?:synonyms? (?:for|of)|other words? for|another word for|a word for|"
        r"words? that means? the same as) (?P<syn>[a-z][a-z'-]{1,30})\s*\??$"
        r"|^(?:give me )?(?:a |some )?synonyms? (?:for|of) (?P<syn2>[a-z][a-z'-]{1,30})\s*\??$")),
    ("antonym", re.compile(
        r"^(?:what(?:'s| is|s| are)? )?(?:the |an |some )?(?:opposite of|antonyms? (?:for|of)) (?P<ant>[a-z][a-z'-]{1,30})\s*\??$")),
    ("counted", re.compile(
        r"^how many (?P<counted>(?!tasks|reminders|notes|things|emails|people|contacts|days|hours|minutes|weeks)[a-z][a-z -]{1,20}?) "
        r"(?:have i done|did i do|have i walked|did i walk|did i take|have i taken"
        # "how many calories did I eat today", with "I ate 2000 calories" kept (2026-10-08)
        r"|(?<=calories )(?:did i eat|have i eaten|have i had|did i have))"
        r"(?P<counted_when> today| this week| yesterday)?\s*\??$")),
    ("ate", re.compile(
        r"^what did i (?:have|eat) for (?P<ate_meal>breakfast|lunch|dinner|supper|dessert)(?P<ate_when> today| yesterday| last night| this morning| tonight)?\s*\??$"
        r"|^what (?:did i eat|have i eaten)(?P<ate_when2> today| yesterday)?\s*\??$")),
    # "What have I lent out" (2026-10-08: to a model, with "I lent Mike my
    # drill" kept): every lend not since given back.
    # "What time do I need to get up tomorrow" (2026-10-08: a memory search
    # for "get up"): his alarm, and the first thing on his calendar.
    ("get_up", re.compile(
        r"^(?:what time|when) (?:do i|should i|will i|am i) (?:need to |have to |got to )?(?:get up|wake up|be up|waking up|getting up)"
        r"(?P<get_up> tomorrow| in the morning| today)?\s*\??$")),
    # "What do I need to give back" after "I borrowed a ladder from Sam"
    # (2026-10-08: to the planner, and "I can't think").
    ("borrowed", re.compile(
        r"^(?:what (?:do i|did i) (?:need to |have to |still )?give back(?: to (?:people|anyone|anybody))?"
        r"|what (?:have i|did i) borrow(?:ed)?(?: from (?:people|anyone|anybody))?|what (?:do i have|have i got) (?:that'?s |that is )?borrowed)\s*\??$")),
    ("lent_out", re.compile(
        r"^(?:what|which things|what stuff) (?:have i|did i|do i have) (?:lend|lent|loan|loaned)(?: out)?(?: to (?:people|anyone|anybody))?\s*\??$"
        r"|^who (?:has|have|borrowed) (?:my|any of my) (?:stuff|things)\s*\??$|^what (?:do i have|have i got) (?:lent|loaned) out\s*\??$")),
    ("lent", re.compile(
        r"^who (?:has|borrowed|took|has got) (?:my|our) (?P<lent>[a-z][a-z' ]{1,25}?)\s*\??$"
        r"|^(?:who did i|did i) (?:lend|loan|give) (?:my|our|the) (?P<lent2>[a-z][a-z' ]{1,25}?) to(?: anyone| anybody| someone)?\s*\??$")),
    ("liked_how", re.compile(
        r"^how do i (?:like|take|have|drink) my (?P<liked_how>coffee|tea|steak|burgers?|eggs|toast|latte|martini|whiskey"
        r"|bourbon|pizza|tacos|sandwich|smoothie|oatmeal)\s*\??$")),
    ("went", re.compile(
        r"^when did i (?:last )?(?P<went>go to (?:the )?(?:gym|pool|yoga|pilates|spin class|class|church|doctor|dentist|chiropractor|therapy|physical therapy|barber|library|park)|go (?:for a |on a )(?:run|walk|swim|bike ride|ride|hike|jog)|go (?:running|swimming|jogging|hiking|biking|cycling)|work out|exercise|meditate|do yoga|run|jog|swim)(?: last)?\s*\??$"
        r"|^(?:did|have) i (?:already )?(?P<went2>(?:go|gone|been) to (?:the )?(?:gym|pool|yoga|pilates|spin class|class|church|doctor|dentist|chiropractor|therapy|physical therapy|barber|library|park)|(?:go|gone|been) (?:for a |on a )(?:run|walk|swim|bike ride|ride|hike|jog)|(?:go|gone|been) (?:running|swimming|jogging|hiking|biking|cycling)|work(?:ed)? out|exercised?|meditated?|(?:do|done) yoga|run|ran|jog|jogged|swim|swum)(?P<went_when> today| yet| this week| this morning)?\s*\??$"
        r"|^how (?:many times|often) (?:did|have) i (?P<went3>(?:go|gone|been) to (?:the )?(?:gym|pool|yoga|pilates|spin class|class|church|doctor|dentist|chiropractor|therapy|physical therapy|barber|library|park)|(?:go|gone|been) (?:for a |on a )(?:run|walk|swim|bike ride|ride|hike|jog)|(?:go|gone|been) (?:running|swimming|jogging|hiking|biking|cycling)|work(?:ed)? out|exercised?|meditate|do yoga|run|jog|swim)(?P<went_when3> today| this week| this month| last week)?\s*\??$")),
    ("did_count", re.compile(
        r"^how many times (?:did|have) i (?P<dc_v>change|give|feed|walk|water|clean|wash|mow|vacuum|replace|call|visit|pay"
        r"|take|charge|empty|fill|refill)(?:ed|d)? (?P<dc_o>[a-z][a-z' ]{1,40}?)(?P<dc_when> today| this week| this month| yesterday)?\s*\??$")),
    # "Did I finish the report" (2026-10-07: to the planner) - his list and
    # what he told her he finished.
    ("did_finish", re.compile(
        r"^(?:did|have) i (?:finish(?:ed)?|complete(?:d)?|wrap(?:ped)? up) (?:the |my )?(?P<did_finish>[a-z0-9][a-z0-9' ]{1,40}?)"
        r"(?: done| finished)?(?: yet| already| today| this week)?\s*\??$")),
    # "What did I think of the Thai place", "what restaurants do I want to
    # try", "what was I thinking about getting" (2026-10-07: to a model,
    # with the note in his words).
    ("opinion", re.compile(
        r"^(?:what did i think (?:of|about)|how did i like|did i like|did i enjoy) (?:the |that |this |my |our )?(?P<opinion>[a-z0-9][a-z0-9' -]{1,40}?)\s*\??$"
        r"|^what (?P<want_try>restaurants?|places?|foods?|things?|movies?|shows?|books?|bars?|cafes?|coffee shops?|games?)? ?(?:do|did) i (?:want|wanna|say i wanted) to"
        r" (?:try|check out|go to|visit)\s*\??$"
        r"|^what (?:was|am|were) i thinking (?:about|of)(?: (?:getting|buying|doing|trying|starting|learning|taking up|getting into))?\s*\??$"
        # "Where do I want to travel", "what movies did I like", "what did I
        # rate Inception" (2026-10-08: to a model, with his notes on file).
        r"|^(?P<want_go>where) (?:do|did) i (?:want|wanna|say i wanted) to (?:travel|go|visit)(?: someday| one day)?\s*\??$"
        r"|^what (?P<liked>movies?|films?|shows?|books?|restaurants?|places?|songs?|albums?|games?) (?:did|have) i (?:like|liked|love|loved|enjoy|enjoyed)\s*\??$"
        r"|^what did i (?:rate|give) (?:the |that )?(?P<rated>[a-z0-9][a-z0-9' -]{1,40}?)\s*\??$")),
    # "What did I add to the list today" (2026-10-07: to the planner).
    # "How much chicken do I need" a turn after "add 2 pounds of chicken"
    # (2026-10-08: "I can't think"): the amount on the list. None when the
    # list holds no such thing, so a recipe question still reaches a model.
    ("shop_qty", re.compile(
        r"^how (?:much|many) (?P<shop_qty>[a-z][a-z' -]{1,25}?) (?:do|did) (?:i|we) (?:need|need to (?:get|buy)|have on (?:my|the) list)\s*\??$")),
    ("shop_added", re.compile(
        r"^what (?:did i|have i|did we|have we) (?:add|added|put)(?: on| to)? (?:to |on )?(?:my |the |our )?(?:shopping |grocery )?list"
        r"(?: (?P<shop_added>today|yesterday|this week))?\s*\??$")),
    ("cost_mine", re.compile(
        # "How much do I spend on bills a month" (2026-10-07: to a model) -
        # first, so "bills" is never read as one bill called that.
        r"^how much (?:do (?:i|we) (?:spend|pay) (?:on|for) (?:my |our )?|are my |is my )(?:monthly )?(?P<cost_bills2>bills|expenses)"
        r"(?: (?:in total|altogether|total))?(?: (?:a|each|per|every) month| monthly)?\s*\??$"
        r"|^how much (?:is|are|was) (?:my|our|the) (?P<cost_mine>[a-z][a-z' ]{1,30}?)(?: (?:a|per|each) (?:month|week|year))?\s*\??$"
        # "How much is rent" (2026-10-07: to a model, beside "my rent is 1500").
        r"|^how much (?:is|was) (?P<cost_mine3>rent|mortgage)(?: (?:a|per|each) month)?\s*\??$"
        r"|^(?:how much|what) do (?:i|we) (?:pay|spend) (?:for|on|in) (?:my |our |the )?(?P<cost_mine2>[a-z][a-z' ]{1,30}?)"
        r"(?: (?:a|per|each) (?:month|week|year))?\s*\??$"
        r"|^what (?:are|r) my (?:monthly )?(?P<cost_bills>bills|expenses|monthly bills)(?: (?:this|a|each|per) month| monthly)?\s*\??$"
        # "What bills do I have this month" (2026-10-08: "I can't think").
        r"|^what (?P<cost_bills3>bills|expenses) do (?:i|we) (?:have|pay|owe)(?: (?:this|a|each|per|every) month| monthly)?\s*\??$")),
    # "What's my oldest task" (2026-10-08: searched memory for "oldest task").
    ("task_age", re.compile(
        r"^(?:what(?:'s| is|s)|which is) (?:my |the )?(?P<task_age>oldest|newest|latest|most recent|first|last) "
        r"(?:task|thing on my (?:list|to ?do list)|to ?do)(?: on my list)?\s*\??$")),
    # "Do I have class tomorrow" after "I have class at 9 on Mondays and
    # Wednesdays" (2026-10-08: a FILE search). Placed after the readers for
    # "anything", "plans" and "meetings", which say the whole day.
    ("do_i_have", re.compile(
        r"^(?:do|will) (?:i|we|the kids|my kids|the children) have (?!(?:any|anything|something|plans|a meeting|meetings|events|stuff|time|free time|spare time|openings|gaps|to)\b)"
        r"(?P<do_i_have>[a-z][a-z' ]{1,20}? (?:today|tonight|tomorrow|this weekend|(?:on |this |next )?"
        r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)))\s*\??$")),
    # "How did I do on my test" after "I got an A on my test" (2026-10-08).
    ("how_did_i_do", re.compile(
        r"^(?:how did i do|what did i get|what was my (?:grade|score|mark)) on (?:my |the |our )?(?P<how_did_i_do>[a-z][a-z' ]{1,30}?)\s*\??$")),
    # "How many months left on my lease" after "my lease ends in June"
    # (2026-10-08: to a model).
    ("left_on", re.compile(
        r"^how (?:many (?P<left_unit>days|weeks|months)|long|much (?:time|longer)) (?:is |do i have )?(?:left on|left before|left until"
        r"|until the end of|before the end of) (?:my |our )(?!(?:\w+ )?(?:timer|alarm)s?\b)(?P<left_on>[a-z][a-z' ]{1,30}?)\s*\??$")),
    # "How long was I at the gym" after "I'm going to the gym" ... "I'm back"
    # (2026-10-08: to a model). His own words, with their times, say it.
    ("how_long_out", re.compile(
        r"^how long was i (?:(?:at|out at|in) (?:the )?(?P<how_long_out>[a-z][a-z' ]{1,25}?)|(?P<how_long_out2>gone|out|away))"
        r"(?: for)?(?: today)?\s*\??$")),
    # "When did I last eat" after "I ate at 7" (2026-10-08: to a model; an
    # irregular verb the did-last reader cannot make).
    ("last_ate", re.compile(
        r"^(?:when did i (?:last )?(?:eat|have something to eat|have a meal)|when was (?:the last time i ate|my last meal)"
        r"|what time did i (?:last )?eat)(?: today)?\s*\??$")),
    # "Do I work tomorrow" after "I have the day off tomorrow" (2026-10-08:
    # to the planner).
    ("do_i_work", re.compile(
        r"^(?:do|will) i (?:have to |need to |got to |gotta )?work (?P<do_i_work>today|tomorrow|tonight|this weekend"
        r"|(?:on |this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\s*\??$")),
    ("work_hours", re.compile(
        r"^(?:what time|when) do i (?P<work_hours>start|begin|get off|finish|clock in|clock out)(?: work)?(?: today| tomorrow| tonight)?\s*\??$"
        r"|^(?:what time|when) does my (?:shift|work ?day) (?P<work_hours2>start|begin|end|finish)(?: today| tomorrow)?\s*\??$"
        # "How long until I get off work" (2026-10-08: to a model).
        r"|^how (?:long|much longer|much time) (?:until|till|before) i (?P<work_hours3>get off|finish|clock out|start|clock in)(?: work)?\s*\??$")),
    ("life_when", re.compile(
        r"^when (?:am i|are we) (?P<lw>moving|going on (?:vacation|holiday|my trip|our trip|a trip|our honeymoon)|retiring|graduating"
        r"|starting (?:my |the )?(?:new job|school|college|classes)|having (?:my )?surgery|flying to [a-z][a-z ]{1,25}?"
        r"|off(?: work)?(?: next)?|next off|on vacation|working from home|out of (?:the )?office)\s*\??$"
        r"|^when do (?:i|we) (?P<lw2>start (?:my |the |our )?(?:new job|school|college|classes)|move|leave for (?:my |our |the )?(?:vacation|trip|holiday)"
        r"|fly to [a-z][a-z ]{1,25}?)\s*\??$"
        r"|^when(?:'s| is) (?:my|our) (?P<lw3>vacation|holiday|trip|move|moving day|surgery|first day|graduation|honeymoon"
        r"|(?:next )?days? off|time off|pto)\s*\??$"
        # "Am I working from home today" (2026-10-07: to the planner).
        r"|^(?:am i|are we) (?P<lw4>working from home|wfh|off(?: work)?|on vacation) (?:today|tomorrow)\s*\??$"
        # "When is my package coming" (2026-10-07: to a model).
        # "When is my car inspection" (2026-10-07: to a model).
        r"|^when(?:'s| is) (?:my|the) (?:car|truck|van|suv)(?:'s|s)? (?P<lw6>inspection|service|oil change|tune-?up|smog check"
        r"|emissions test|tire rotation)(?: due)?\s*\??$"
        r"|^when is (?:my|the) (?:car|truck|van|suv) due(?: for (?:an? |its )?(?P<lw7>inspection|service|oil change|tune-?up"
        r"|smog check|emissions test|tire rotation))?\s*\??$"
        r"|^when (?:is|does|will|should) (?:my|the) (?P<lw5>package|parcel|delivery) (?:coming|arriving|arrive|come|get here|be here|due)\s*\??$"
        # "When am I going to the gym", "what am I doing after work"
        # (2026-10-07: both to a model, a turn after he said).
        r"|^when (?:am i|was i) (?:going|heading|gonna go) (?:to )?(?:the )?(?P<lw8>gym|store|grocery store|pool|park|library|post office"
        r"|bank|mall|barber|salon|vet|shopping|running|swimming|for a (?:run|walk|swim|bike ride))\s*\??$"
        r"|^what am i doing (?P<lw9>after work|before work|after lunch|after dinner|after school|later(?: today)?)\s*\??$"
        # "When is my phone arriving" (2026-10-07: to a model, after "I ordered a new phone").
        r"|^when (?:is|are|will|does|do|should) my (?!package|parcel|delivery)(?P<lw10>[a-z][a-z' ]{1,25}?) "
        r"(?:coming|arriving|arrive|come|get here|be here|be delivered|getting delivered|ship|shipping)\s*\??$"
        r"|^(?P<lw11>is anything|are any packages|is a package|is anything being|am i expecting (?:any )?(?:packages|deliveries|anything))"
        r"(?: (?:coming|arriving|being delivered|getting delivered|due|delivered))?(?: today| tomorrow| this week)?\s*\??$"
        # "When am I going to Denver" (2026-10-07: to a model, after he said).
        r"|^when (?:am i|are we) (?:going|heading|headed|driving) to (?P<lw12>[a-z][a-z' ]{1,30}?)\s*\??$"
        r"|^when (?:am i|are we) visiting (?P<lw13>[a-z][a-z' ]{1,30}?)\s*\??$")),
    # "What did I promise Sarah" (2026-10-07: to a model).
    ("promised", re.compile(r"^what did i promise (?P<prom>[a-z][a-z' ]{1,25}?)\s*\??$"
                            r"|^(?:did i|have i) promise(?:d)? (?P<prom2>anyone|anybody|someone|[a-z][a-z' ]{1,25}?) anything\s*\??$"
                            r"|^what (?:have i|did i) promise(?:d)?(?: (?:to )?(?P<prom3>anyone|anybody|people))?\s*\??$")),
    # "What's on my calendar tomorrow morning" (2026-10-07: to a model).
    ("agenda_part", re.compile(
        r"^(?:what(?:'s| is)(?: on)?(?: my (?:calendar|schedule))?|what do i have(?: on)?|what have i got(?: on)?|anything(?: on)?"
        r"|do i have anything|is there anything(?: on my calendar)?)"
        r"(?: (?:for|on))? (?:(?P<ap_day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday) (?P<ap_part>morning|afternoon|evening|night)"
        r"|this (?P<ap_part2>morning|afternoon|evening)|(?P<ap_part3>tonight))\s*\??$"
        # "What's my schedule look like tomorrow morning", "what does my
        # morning look like tomorrow" (2026-10-07: to a model).
        r"|^what(?:'s| is| does)? my (?:schedule|calendar|day) look(?:s)? like (?P<ap_day4>today|tomorrow|monday|tuesday|wednesday"
        r"|thursday|friday|saturday|sunday) (?P<ap_part4>morning|afternoon|evening|night)\s*\??$"
        r"|^what(?:'s| is| does)? my (?P<ap_part5>morning|afternoon|evening) look(?:s)? like(?: (?P<ap_day5>today|tomorrow|monday"
        r"|tuesday|wednesday|thursday|friday|saturday|sunday))?\s*\??$")),
    ("worked", re.compile(
        r"^(?:how long|how many hours|how much) (?:did i|have i) (?:work|worked|been working)(?P<worked> today| yesterday| this week)?\s*\??$"
        r"|^how long (?:was i|have i been) at work(?P<worked2> today| yesterday)?\s*\??$")),
    ("off_lists", re.compile(
        r"^what (?P<off_w>movies |shows |films |tv shows )?have i (?:watched|seen|finished watching)(?: lately| recently| this year| so far)?\s*\??$"
        r"|^what (?P<off_r>books )?have i (?:read|finished reading)(?: lately| recently| this year| so far)?\s*\??$"
        r"|^how many (?P<off_n>books|movies|shows|films) have i (?:read|watched|seen|finished)(?P<off_y> this year| so far)?\s*\??$"
        r"|^what was the last (?P<off_l>book|movie|show|film) i (?:read|watched|saw|finished)\s*\??$"
        r"|^what (?P<off_now>book )?am i (?:currently )?reading(?: right now| now| at the moment)?\s*\??$"
        # "What show am I watching" after "I started a new show called
        # Severance" (2026-10-08: to a model).
        r"|^what (?P<off_tv>show |series |tv show )?am i (?:currently )?watching(?: right now| now| at the moment| these days)?\s*\??$"
        # "What did I watch recently" (2026-10-08: to a model).
        r"|^what (?:movies |shows |films |tv shows |books )?did i (?:watch|see|read|finish(?: watching| reading)?)(?: lately| recently| last| this year)\s*\??$")),
    # "What time do I usually wake up" (2026-10-07: to a model, two turns
    # after "I woke up at 6:30").
    # "What was my blood pressure" (2026-10-07: to a model, a turn after he
    # said it).
    ("reading", re.compile(
        r"^(?:what(?:'s| is| was|s)|what were) my (?:last |latest |most recent )?(?P<reading>blood pressure|bp|heart rate|resting heart rate"
        r"|pulse|blood sugar|glucose|blood glucose|a1c|temperature|temp|oxygen|o2)(?: reading| readings| numbers)?"
        r"(?: today| this morning| yesterday| last time)?\s*\??$")),
    # "How long have I been awake" (2026-10-07: to a model, after "I woke up at 6:30").
    ("awake_for", re.compile(r"^how long (?:have i been|am i) (?:awake|up)(?: for| today| now)?\s*\??$")),
    # "When did I get to work" (2026-10-07: to a model, after "I'm at work").
    ("arrived", re.compile(
        r"^(?:when|what time) did i (?:get|arrive|make it) (?:to |at )?(?P<arrived>work|the office|home|school|the gym)\s*\??$"
        # "What time did I leave work" (2026-10-07: to a model).
        r"|^(?:when|what time) did i (?P<work_mark>leave|finish|get off|clock out of|clock out|start|clock in|clock in to|begin) work(?: today)?\s*\??$")),
    # "How much do I owe on my car" answered about a person called "On My
    # Car" (2026-10-07). What is left on a loan, from his note.
    ("loan_left", re.compile(
        r"^how much (?:do i (?:still )?owe|is left|do i have left|is still owed) on (?:my |the )?(?P<loan>car|truck|house|mortgage|student loans?|loan|credit card|card)\s*\??$"
        r"|^what(?:'s| is) (?:left on|the balance on|my balance on) (?:my |the )?(?P<loan2>car|truck|house|mortgage|student loans?|loan|credit card|card)(?: loan)?\s*\??$")),
    ("role_said", re.compile(
        r"^what did (?:the|my|our) (?P<role_said>" + _ROLES_WHO_TELL + r") (?:say|tell me|tell us|think|recommend|want me to do)\s*\??$")),
    ("woke_usual", re.compile(
        r"^(?:what time|when) do i (?:usually|normally|typically|tend to) (?:wake up|get up|go to bed|go to sleep|fall asleep)\s*\??$"
        r"|^what(?:'s| is|s)? my (?:usual|normal|average|typical) (?:bedtime|wake[- ]?up time|wake time)\s*\??$"
        # "What time do I go to bed", "what's my bedtime" (2026-10-08: to a
        # model, after "I go to bed at 11 usually").
        r"|^(?:what time|when) do i (?:wake up|get up|go to bed|go to sleep)(?: at night| in the morning)?\s*\??$"
        r"|^what(?:'s| is|s)? my (?:bedtime|bed time|wake[- ]?up time|wake time)\s*\??$")),
    ("woke", re.compile(
        r"^(?:what time|when) did i (?P<woke>wake up|get up|go to bed|go to sleep|fall asleep)"
        r"(?: today| this morning| last night| yesterday)?\s*\??$")),
    ("weight", re.compile(
        r"^(?:what(?:'s| is|s) my (?:current )?weight|how much do i weigh(?: now)?|what do i weigh|what did i weigh(?: last)?)\s*\??$")),
    ("body", re.compile(
        r"^(?P<body>how tall am i|what(?:'s| is) my height|what(?:'s| is) my bmi|what(?:'s| is) my body mass index"
        r"|how much weight (?:have i|did i) (?:lost|lose|gained|gain)(?: so far)?|how much have i (?:lost|gained)(?: so far)?|how(?:'s| is| am i doing (?:on|with)) my weight(?: loss)?(?: goal)?"
        # "What did I weigh last week" (2026-10-07: to a model).
        r"|what (?:did i weigh|was my weight)(?: (?:last week|last month|yesterday|a week ago|a month ago|last time))?"
        r"|how much (?:do|did) i weigh(?: (?:last week|last month|yesterday|a week ago|a month ago|last time))?"
        r"|what(?:'s| is) my (?:current )?weight"
        # "How far am I from my goal weight" (2026-10-07: to the planner).
        r"|how (?:far|close) am i (?:from|to) my (?:goal|target) weight|how (?:far|close) am i (?:from|to) (?:my|reaching my) (?P<body_goal>goal|target)|how much (?:more )?(?:weight )?(?:do i (?:have|need) to|to) lose"
        r"|how many (?:more )?pounds (?:to go|(?:do i have|do i need) to lose|until my goal))\s*\??$")),
    ("meds", re.compile(
        r"^what (?:medications?|medicines?|meds|prescriptions?|pills) (?:do i take|am i on|am i taking|do i have)\s*\??$"
        r"|^what(?:'s| is| are) my (?:medications?|meds|prescriptions?)\s*\??$")),
    ("work_at", re.compile(
        r"^(?:where do i (?:work|go to school|study)|who do i work for|where(?:'s| is) my (?:work|job|office|school))\s*\??$")),
    ("after_that", re.compile(
        r"^(?:and |ok |okay )?(?:what(?:'s| is|s)? |what about |and )?(?:after that|next after that|the one after(?: that)?"
        r"|after it|then what)\s*\??$")),
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
        r"(?P<what> today| yesterday| this week| last week| last weekend| this weekend| over the weekend"
        r"| (?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$"
        r"|^what (?:tasks|things) (?:have i|did i) (?:finish(?:ed)?|complete(?:d)?|do|done|get done|tick(?:ed)? off)"
        r"(?P<what2> today| yesterday| this week| last week| last weekend)?$"
        r"|^(?:what(?:'s| is|s)? (?:on )?)?my (?:done|finished|completed) (?:list|tasks)$"
        r"|^(?:which|what) tasks? (?:did|have) i (?:finish|finished|complete|completed|tick off|ticked off)\s*\??$"
        r"|^(?:finished|completed|done) tasks\s*\??$"
        # "How productive was I today" (2026-10-07: to the planner).
        r"|^how productive (?:was i|have i been|am i)(?P<what3> today| yesterday| this week)?\s*\??$"
        # "How many tasks did I finish this week" (2026-10-07: to a model; today has its own answer).
        r"|^how many (?:tasks|things) (?:have i|did i) (?:finish(?:ed)?|complete(?:d)?|get done|tick(?:ed)? off|do|done)"
        r"(?P<what4> yesterday| this week)\s*\??$")),
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
        # "What year was I born" (2026-10-08: to a model)
        r"|(?:what year|when) was i born|what(?:'s| is) my birth year"
        r"|how long (?:until|till|before) my birthday|when(?:'s| is|s) my next birthday"
        r"|how many days (?:until|till|to|before) my next birthday"
        # "How old will I be on my birthday" (2026-10-07: to a model).
        r"|how old (?:will i be|am i going to be|will i turn|do i turn)(?: on my (?:next )?birthday| next)?)\s*\??$")),
    # "What's my zodiac sign", "what day was I born" (2026-10-07: to a model).
    ("born_facts", re.compile(
        r"^(?:what(?:'s| is|s) my (?P<born_q>zodiac sign|star sign|sign|astrological sign|zodiac)"
        r"|what (?P<born_q2>day)(?: of the week)? was i born(?: on)?"
        # "How old will I be next year", "how many days old am I" (2026-10-07: to a model)
        r"|how old (?:will|would) i be (?P<born_q3>next year)"
        r"|how many (?P<born_q4>days|weeks|months) (?:old am i|have i been alive))\s*\??$")),
    # DEADLINES HE SET. "Add a task to renew my license by Friday" stores a
    # real deadline; "what's due this week" and "what's overdue" told him she
    # couldn't think (2026-10-07).
    ("tasks_due", re.compile(
        r"^(?:what(?:'s| is|s)?|anything|is anything|what do i have) (?P<due>overdue|late|past due|due"
        r"(?: today| tomorrow| this week| next week| this month| next month| soon| next)?)(?: on my list)?\s*\??$"
        r"|^what(?:'s| is|s)? (?P<due2>coming up|due) (?:on my (?:list|task list|to ?do list))\s*\??$"
        # "What tasks do I have today" (2026-10-07: to the planner), and
        # "what did I forget", which is the overdue list asked guiltily.
        r"|^what tasks (?:do i have|have i got|are there|are on my list)(?: due)? (?P<due3>today|tomorrow|this week)\s*\??$"
        # "What do I have to do tomorrow" (2026-10-07: to a model).
        r"|^what (?:do i|have i got to|do i still) (?:have|need|got) to do (?P<due5>tomorrow|this week|this weekend)\s*\??$"
        # "What am I forgetting" (2026-10-07: to a model).
        r"|^(?:what did i forget(?: to do)?|did i forget (?:anything|something)|am i forgetting (?:anything|something)"
        r"|what am i forgetting|is there anything i(?:'m| am) forgetting)"
        r"(?: today)?(?P<due4>)\s*\??$"
        # "What's on my list for Friday" (2026-10-08: to a model).
        # ("What's due Friday" is `due`'s, which was there first.)
        r"|^(?:what(?:'s| is|s) on my (?:list|task list|to ?do list)(?: due)? (?:for|on) "
        r"|what do i have (?:to do|due|on my list) (?:on )?)"
        r"(?P<due6>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??$")),
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
        r"^(?:what(?:'s| is|s)|what do i have|what have i got|anything|is anything|do i have anything) coming up(?: (?P<coming>today|tonight|tomorrow))?\s*\??$"
        r"|^what(?:'s| is) (?:on )?(?:for )?(?P<coming2>tonight)\s*\??$|^what am i doing (?P<coming3>tonight|this evening)\s*\??$"
        r"|^what do i have (?:on |going on )?(?P<coming4>tonight|this evening)\s*\??$")),
    ("meetings_count", re.compile(
        r"^how many (?:meetings|appointments|events)(?: (?:do i have|are on my calendar|have i got))?"
        r" (?P<coming5>today|tomorrow|tonight)\s*\??$")),
    # "What appointments do I have", "any meetings coming up" (2026-10-08:
    # to a model): the calendar's next few, the way meetings_count reads it.
    ("meetings_ahead", re.compile(
        r"^(?:what|which) (?:appointments|meetings|events) (?:do i have|have i got|are (?:on my calendar|coming up))(?: coming up)?\s*\??$"
        r"|^(?:do i have |have i got )?any (?:appointments|meetings|events) coming up\s*\??$")),
    # "How many meetings do I have this week" (2026-10-07: to a model).
    ("meetings_week", re.compile(
        r"^how many (?:meetings|appointments|events|calls)(?: (?:do i have|are on my calendar|have i got))?"
        r" (?P<meetings_week>this week|next week)\s*\??$")),
    # "How long until my alarm" (2026-10-07: to the planner).
    ("alarm_left", re.compile(
        r"^how long (?:until|till|before) my (?:next )?alarm(?: goes off)?\s*\??$"
        # "How much sleep will I get" (2026-10-07: to a model) is the same sum.
        r"|^how (?:much sleep|many hours(?: of sleep)?|long) (?:will|can|do|would) i (?:get|sleep)(?: if i (?:go to bed|sleep) now)?(?: tonight)?\s*\??$")),
    # "What time is my pill reminder" (2026-10-07: to a model).
    ("reminder_when", re.compile(
        r"^(?:what time|when)(?:'s| is|s| does) (?:my |the )(?P<reminder_when>[a-z][a-z' ]{1,30}?) (?:reminder|alarm)"
        r"(?: (?:set for|go off|for))?\s*\??$")),
    ("until_mine", re.compile(
        # "My interview" is the `until` reader's; this is only the ones named by who.
        r"^how long (?:is it )?(?:until|till|til|before) (?:my |the |our )?(?P<until_mine>"
        r"(?:lunch|dinner|breakfast|brunch|coffee|drinks|meeting|call) with [a-z][a-z' ]{1,30}?)"
        r"(?: (?:today|tomorrow))?\s*\??$")),
    ("until", re.compile(
        r"^how (?:many days|many hours|many minutes|long) (?:until|till|to|before) (?:the )?(?!(?:you|u|i|we|she|it|they|he) |(?:soft |hard |medium )?boil\b)"
        r"(?P<until>[a-z][a-z' ]{2,30}?)(?: is it)?$")),
    # "What day is Thanksgiving" is asked for the DATE, so it leads with it.
    ("until_day", re.compile(
        r"^(?:when is|when's|what day is|what day's|what day does|which day is) (?P<until2>christmas|new year(?:'s)?(?: day| eve)?|halloween|thanksgiving|"
        r"valentine'?s(?: day)?|easter|the fourth of july|july 4th|independence day|labou?r day|memorial day|"
        r"mlk day|martin luther king day|presidents'? day|president's day|mother'?s day|father'?s day|"
        r"columbus day|indigenous peoples'? day|veterans'? day|veteran's day|juneteenth|st\.? patrick'?s day"
        r"|saint patrick'?s day)(?: on| fall on| this year)?\s*\??$")),
    # "When is Easter next year", "what day is Christmas in 2028" (2026-10-07: to a model).
    ("holiday_year", re.compile(
        r"^(?:when is|when's|what day is|what day's|what day does|which day is|what date is) (?P<hy>christmas|new year(?:'s)?(?: day| eve)?|halloween"
        r"|thanksgiving|valentine'?s(?: day)?|easter|the fourth of july|july 4th|independence day|labou?r day|memorial day"
        r"|mlk day|martin luther king day|presidents'? day|president's day|mother'?s day|father'?s day"
        r"|columbus day|indigenous peoples'? day|veterans'? day|veteran's day|juneteenth|st\.? patrick'?s day"
        r"|saint patrick'?s day)(?: (?:fall )?on)? (?P<hy_year>next year|in \d{4}|\d{4})(?: fall on| on)?\s*\??$")),
    # "What's the date tomorrow", "what was yesterday's date", "what week is
    # it", "how many days in February" (2026-10-07, all to a model).
    # THE NEXT HOLIDAY (2026-10-07: "what holiday is next" and "is today a
    # holiday" went to the planner while every date was computed here).
    # HIS DAY, LOGGED, read back (2026-10-07: all to a model). The notes
    # "I drank a glass of water", "I ran 3 miles" are added up here.
    ("logged", re.compile(
        r"^how (?:much|many (?:glasses|cups|bottles|mugs|cans)(?: of)?) (?P<logged_drink>water|coffee|tea|soda|beer|wine|juice|milk)"
        r"(?: (?:have i (?:had|drunk|drank)|did i (?:have|drink))(?P<logged_w> today| this week)?|(?P<logged_w5> today| this week))\s*\??$"
        # "How many coffees have I had today" (2026-10-07: to a model).
        r"|^how many (?P<logged_drink2>coffee|tea|soda|beer|wine|juice|milk|latte|espresso)s? (?:have i (?:had|drunk|drank)|did i (?:have|drink))"
        r"(?P<logged_w6> today| this week)?\s*\??$"
        # "How much advil have I taken today" (2026-10-08: to a model, a turn
        # after "I took 2 advil").
        r"|^how (?:much|many) (?P<logged_med>" + "|".join(_MEDS) + r"|pills|tablets|painkillers) (?:have i|did i) (?:taken|take|took|had|have)"
        r"(?P<logged_w7> today| this week)?\s*\??$"
        # "What's my longest run" (2026-10-08: to a memory search).
        r"|^what(?:'s| is|s| was) my (?:longest|farthest|furthest|biggest) (?P<logged_longest>run|walk|hike|bike ride|ride|swim|jog)"
        r"(?: this week| this month| this year| ever)?\s*\??$"
        r"|^how (?:far|many (?:miles|km|kilometers)) (?:did|have) i (?P<logged_move>run|ran|walk|walked|jog|jogged|bike|biked|cycle|cycled|swim|swum|swam|hike|hiked)"
        r"(?P<logged_w2> today| this week| this month)?\s*\??$"
        r"|^how (?:much|long|many (?:minutes|hours)|much time) (?:did|have) i (?:been |spent )?(?P<logged_dur>run|ran|running|walk|walked|walking|jog|jogged|jogging|bike|biked|biking|cycle|cycled|cycling|swim|swum|swam|swimming|hike|hiked|hiking|exercise|exercised|exercising|work(?:ed)? out|working out)"
        r"(?: for)?(?P<logged_w4> today| this week| this month)?\s*\??$"
        r"|^how (?:much|long|many hours) did i (?P<logged_sleep>sleep)(?: last night| for)?\s*\??$"
        # "How did I sleep last night", "what's my average sleep" (2026-10-08:
        # to a model, a turn after "I slept 7 hours last night").
        r"|^how (?:did|have) i (?P<logged_sleep6>sleep|slept|been sleeping)(?: last night)?\s*\??$"
        r"|^(?:what(?:'s| is|s) my average (?:sleep|hours of sleep)|how (?:much|many hours)(?: of sleep)? do i (?:usually |normally )?"
        r"(?:sleep|get)(?: a night)?(?: on average)?|how much sleep do i (?:usually |normally )?get(?: on average)?)\s*\??$"
        # "How much did I sleep this week" (2026-10-07: to a model).
        r"|^how (?:much|many hours)(?: of sleep)? (?:did i|have i) (?:sleep|slept|get|gotten)(?: sleep)? (?P<logged_sleep3>this week)\s*\??$"
        r"|^how (?:much|many hours of) sleep (?:did i get|have i had|have i gotten) (?P<logged_sleep4>this week)\s*\??$"
        # "How did I sleep this week" (2026-10-08: to a model).
        r"|^how (?:did|have) i (?:sleep|slept|been sleeping) (?P<logged_sleep5>this week)\s*\??$"
        # "How much sleep did I get" (2026-10-07: to a model).
        r"|^how (?:much|many hours of) (?P<logged_sleep2>sleep) (?:did i get|have i had|have i gotten)(?: last night)?\s*\??$"
        # "Did I sleep enough" (2026-10-07: to the planner).
        r"|^(?:did i|have i been) (?:get(?:ting)? enough sleep|sleep(?:ing)? enough|(?P<logged_enough>sleep(?:ing)? well))(?: last night)?\s*\??$"
        r"|^(?:did i|have i) (?:get|gotten|got) enough sleep(?: last night)?\s*\??$"
        r"|^(?:did|have) i (?P<logged_did>work(?:ed)? out|exercised?|meditated?|stretch(?:ed)?|done yoga|did yoga|gone to the gym|go to the gym)"
        r"(?P<logged_w3> today| this week)?\s*\??$")),
    ("holiday_next", re.compile(
        r"^(?:what(?:'s| is|s) the next (?:holiday|public holiday|federal holiday|big holiday)"
        r"|what holiday is (?:next|coming up)|when(?:'s| is|s) the next (?:holiday|public holiday|federal holiday))\s*\??$"
        r"|^is (?P<holiday_on>today|tomorrow|it|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r" a (?:holiday|public holiday|federal holiday|bank holiday)(?: today)?\s*\??$"
        # "What holidays are in November" (2026-10-07: to a model).
        r"|^(?:what|which|are there any|any) holidays? (?:are |is )?(?:there )?(?:in|this) (?P<holiday_month>january|february|march"
        r"|april|may|june|july|august|september|october|november|december|month)\s*\??$"
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
        r"|^how many days (?:are )?(?:in|does) (?P<cal5>(?:january|february|march|april|may|june|july|august|september|october|november|december|this month)(?: this year| next year| (?:19|20)\d\d)?)(?: have)?\s*\??$"
        r"|^is (?P<cal6>this|it) a leap year\s*\??$"
        # "Is tomorrow a weekday", "what quarter are we in" (2026-10-07: to a model).
        r"|^is (?P<cal7>(?:tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday) (?:a |the )?"
        r"(?:weekday|week day|weekend|weekend day|work ?day|working day))\s*\??$"
        r"|^what (?P<cal8>quarter) (?:is it|are we in|is this|of the year is it)\s*\??$")),
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
        # "What time zone is Paris in" (2026-10-08: to a model): its clock and how far off.
        r"|^what (?:time ?zone|timezone) is (?P<time_in6>[a-z][a-z .'-]{1,40}?) in\s*\??$"
        r"|^what(?:'s| is) the (?:time ?zone|timezone) (?:in|of|for) (?P<time_in7>[a-z][a-z .'-]{1,40}?)\s*\??$"
        # "How far ahead is Tokyo", "what's the time difference with London"
        # (2026-10-07: to a model) - the same answer says how far.
        r"|^how (?:far|many hours) (?:ahead|behind) (?:of (?:me|us) )?is (?P<time_in4>[a-z][a-z .'-]{1,40}?)\s*\??$"
        r"|^what(?:'s| is|s)? the time difference (?:with|to|between (?:me|here|us) and) (?P<time_in5>[a-z][a-z .'-]{1,40}?)\s*\??$")),
    # "What time is it where my sister lives" (2026-10-08: to a model): the
    # town his note says she lives in, then its clock.
    ("time_where", re.compile(
        r"^what(?:'s| is)? (?:the )?time (?:is it )?(?:where|for) (?P<tw_who>(?:my |our )?[a-z][a-z']{1,20}(?: (?!lives\b|is\b|now\b)[a-z]{2,20})?)"
        r"(?: (?:lives|is|lives now|is now))?(?: right now| now)?\s*\??$")),
    # "What time is it there" after asking about a place (2026-10-07).
    ("time_there", re.compile(r"^(?:what(?:'s| is) the time|what time is it) (?:there|over there)(?: now| right now)?\s*\??$")),
    # A CLOCK TIME IN ANOTHER ZONE (2026-10-07: "convert 3pm est to pst",
    # "what's 9am in london" went to the planner).
    ("time_convert", re.compile(
        r"^(?:convert |what(?:'s| is|s) |what time is )?(?P<t>\d{1,2}(?::\d{2})? ?(?:am|pm)|noon|midnight)"
        r"(?: (?P<from>[a-z][a-z ]{1,20}?))? (?:to|in|into) (?P<to>[a-z][a-z ]{1,20}?)(?: time)?\s*\??$"
        # "When it's noon here, what time is it in Paris" (2026-10-07: to a model)
        r"|^(?:when|if) it(?:'s| is) (?P<t2>\d{1,2}(?::\d{2})? ?(?:am|pm)?|noon|midnight)(?: here| for me| my time)?,? "
        r"what(?:'s| is)? (?:the )?time (?:is it )?in (?P<to2>[a-z][a-z ]{1,20}?)\s*\??$"
        # "When is 9am in London", "what time is 9am London time for me"
        # (2026-10-07: to a model) - their clock, said in his.
        r"|^(?:when|what time) is (?P<t3>\d{1,2}(?::\d{2})? ?(?:am|pm)|noon|midnight) (?:in )?(?P<from3>[a-z][a-z ]{1,20}?)(?: time)?"
        r"(?: (?:here|for me|my time|in my time|where i am))?\s*\??$")),
    ("date_after", re.compile(
        r"^what(?:'s| is| date is| day is| will the date be)? (?P<n>\d{1,3}|a|one|two|three|four|five|six|seven|eight|nine|ten)"
        r" (?P<unit>days?|weeks?|months?) (?:from|after) (?:today|now)\s*\??$"
        r"|^what(?:'s| is) the date (?:in )?(?P<n2>\d{1,3}|a|one|two|three|four|five|six|seven|eight|nine|ten) (?P<unit2>days?|weeks?|months?)"
        r"(?: from (?:today|now))?\s*\??$"
        # "What was the date 100 days ago" (2026-10-07: to the planner).
        r"|^what (?:was the date|date was it|day was it|was the day|was it) (?P<n3>\d{1,3}|a|one|two|three|four|five|six|seven|eight|nine|ten)"
        r" (?P<unit3>days?|weeks?|months?) ago\s*\??$")),
    ("date_of", re.compile(
        r"^what(?:'s| is|s)? the date (?:on |for )?(?:of )?(?!(?:today|tomorrow|yesterday|now)\b)(?P<date_of>(?:next |this )?[a-z][a-z ']{2,30}?)\s*\??$"
        r"|^what date is (?P<date_of2>(?:next |this )?[a-z][a-z ']{2,30}?)\s*\??$"
        r"|^when(?:'s| is) (?P<date_of3>(?:next |this )(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\s*\??$"
        # "What's next Monday's date" (2026-10-07: a model).
        r"|^what(?:'s| is|s) (?P<date_of4>(?:next |this )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))'?s date\s*\??$")),
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
        # "Show me what you did" (2026-10-07: to the planner).
        r"|^(?:show|tell) me what (?:you|u) (?:did|have done|'ve done|been doing)(?: today)?$"
        # A part of the day (2026-09-24, offline: "I can't think just now")
        r"|^what (?:did|have) (?:you|u) (?:do|done|get done|been doing) (?P<day_part>this morning|this afternoon|this evening|tonight|earlier|earlier today|so far today)$"
        # "What happened this morning" (2026-10-07: to a model).
        r"|^what(?:'s| has)? happened (?P<day_part2>this morning|this afternoon|this evening|earlier|earlier today|so far today|today)$"
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
                        r"|what (?:can|should) i ask(?: you)?|how does this work"
                        # "What can I say to you" (2026-10-07: to a model).
                        r"|what (?:can|should|do) i (?:say|ask|tell) (?:to )?(?:you|thea)|what (?:kind of )?(?:things|stuff) can i (?:say|ask)(?: you)?"
                        r"|how do i talk to you)$")),
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
        # "What errands do I have" read a note about errands (2026-10-07):
        # an errand is a task, and his list is where they are.
        r"|^what errands (?:do i have|have i got|do i (?:need|have) to run)(?: to run)?\s*\??$|^what are my errands$"
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
        r"(?: for)?(?: on| this)? (?P<day>today|tomorrow|this week|next week|this weekend|the weekend|next weekend|this month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^what (?:do i have|have i got|is there|am i doing) (?:on )?(?P<day2>today|tomorrow|this week|next week|this weekend|the weekend|next weekend|this month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        # "Who am I meeting tomorrow" became a calendar hold called "who am
        # I meeting" (2026-10-07). It is the day's calendar, asked by who.
        r"|^(?:who|where) (?:am i|do i) (?:meeting|meet|seeing|see|having (?:lunch|dinner|coffee|breakfast) with|have (?:lunch|dinner|coffee|breakfast) with|"
        r"have (?:a )?meetings? with)(?: with)? (?P<day13>today|tomorrow|tonight|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??$"
        r"|^(?:my |the )?(?:calendar|schedule|agenda) (?:for )?(?P<day3>today|tomorrow|this week|next week|this weekend|the weekend|next weekend)$"
        r"|^what(?:'s| is|s)? (?P<day4>today|tomorrow)(?:'s| like)?(?: looking like| look like)?$"
        # "What's Friday look like" (2026-10-07: to a model).
        r"|^what(?:'s| is|s| does) (?P<day12>monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|this weekend|next weekend)"
        r"(?: looking like| look like)$"
        # "Is anything happening Saturday" (2026-10-07: to the planner).
        r"|^(?:what(?:'s| is|s)? (?:on|happening|coming up|going on)|(?:is (?:there )?|(?:do i have|have i got) (?!anything(?: on| planned| scheduled| going on)? (?:today|tomorrow)$))?anything(?: (?:on|happening|coming up|planned|going on))?|what have i got on"
        r"|what(?:'s| is|s)? (?:my|the) (?:week|day) (?:looking like|look like))"
        r"(?: for)?(?: on)? (?P<day5>today|tomorrow|this week|next week|this weekend|the weekend|next weekend|this month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$"
        r"|^what(?:'s| is|s| does)? (?:my|the) (?P<day6>week) (?:looking like|look like)$"
        # "What's my schedule this week" paid seven seconds of model for a
        # feed the shapes above already read (2026-09-22).
        r"|^what(?:'s| is|s)? (?:my |the )?(?:calendar|schedule|agenda) (?:for |like )?(?P<day7>today|tomorrow|this week|next week|this weekend|the weekend|next weekend|this month|the week|the month)"
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
        r"|anything (?:on|happening)|am i (?:free|busy)"
        # "What did I have yesterday" (2026-10-07: to a model).
        r"|what (?:was|did i have) on (?:my |the )?(?:calendar|schedule|agenda)|what did i have(?: on)?|what meetings did i have"
        r"|did i have anything(?: on)?|was i busy"
        # "What's on the 15th" (2026-10-07: to a model) - "on" said once.
        r"|what(?:'s| is|s)?(?= on ))"
        r" (?:on |for )?(?P<agenda_on>yesterday|the \d{1,2}(?:st|nd|rd|th)?(?: of (?:january|february|march|april|may|june|july|august"
        r"|september|october|november|december))?|(?:january|february|march|april|may|june|july|august|september|october"
        r"|november|december) (?:the )?\d{1,2}(?:st|nd|rd|th)?)\s*\??$")),
    # "When am I done today", "when's my last meeting" (2026-10-07: to the planner).
    ("last_meeting", re.compile(
        r"^(?:what(?:'s| is|s)?|when(?:'s| is)?|what time(?:'s| is)) my last (?:meeting|appointment|event|call|thing)(?: (?P<lastday>today|tomorrow))?\s*\??$"
        r"|^(?:when|what time) (?:am i|will i be) (?:done|finished|free)(?: for the day)?(?: (?P<lastday2>today|tomorrow))?\s*\??$"
        r"|^what time do i (?:finish|get done|wrap up)(?: (?P<lastday3>today|tomorrow))?\s*\??$")),
    ("first_meeting", re.compile(
        r"^(?:what(?:'s| is|s)?|when(?:'s| is)?|what time(?:'s| is)) my first (?:meeting|appointment|event|call|thing)(?:(?: on)? (?P<day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$")),
    ("repo_wrong", re.compile(
        r"^what(?:'s| is|s)? (?:wrong|broken|failing|up|going on|the matter) with (?:the |my )?(?P<repo_wrong>[a-z0-9][a-z0-9 _.-]{1,40}?)"
        r"(?: pipeline| repo| project| bot)?\s*\??$"
        # "What did I ask you to do today" read the fleet (2026-10-07): a
        # person is not a repository.
        r"|^what did (?!(?:i|you|u|we|he|she|they|it)\b)(?:the |my )?(?P<repo_wrong2>[a-z0-9][a-z0-9 _.-]{1,40}?)(?: pipeline| repo| project| bot)? do (?:today|overnight|last night|this week)\s*\??$")),
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
    # "What's on the list" (2026-10-07: to a model). A list he named a turn
    # ago is that list, read by `voice`; otherwise it is his shopping.
    # "What do I need to return" (2026-10-07: to a model, a turn after "I
    # need to return the shoes by Friday"). His open tasks with that verb.
    ("tasks_verb", re.compile(
        r"^what (?:do i|else do i|have i got to|do i still) (?:need|have|got) to (?P<tv>return|call|pay|pick up|drop off|fix|mail|send|email|text"
        r"|schedule|book|cancel|renew|clean|wash|finish|sign|file|read|write|print|ship|sell|clean up|book|look into|follow up on)\s*\??$"
        r"|^who do i (?:need|have) to (?P<tv2>call|text|email|pay|write to|follow up with)\s*\??$"
        # "What calls do I need to make" (2026-10-07: to a model).
        r"|^what (?P<tv3>calls|emails|errands|returns|payments) do i (?:need|have|still need) to (?:make|send|run|do)\s*\??$")),
    ("the_list", re.compile(r"^what(?:'s| is|s)? on the list$|^read (?:me )?the list$")),
    ("shopping", re.compile(
        r"^what(?:'s| is|s)? on my shopping list$|^what(?:'s| is|s)? on my list$"
        r"|^(?:my )?shopping list$|^what do (?:i|we) need (?:to buy|from the store)$"
        # "I'm going grocery shopping" (2026-10-07: to a model) is the moment the list is for.
        r"|^(?:i'?m|i am|we'?re|we are) (?:going|heading|off) grocery shopping(?: now)?$"
        # "Do I need anything from the store" asked about "anything from the
        # store" as an item and went to the planner (2026-10-07).
        r"|^do (?:i|we) need (?:anything|something|stuff) (?:from|at) the (?:store|shop|grocery store|supermarket|grocer'?s)\s*\??$"
        r"|^what do (?:i|we) need to (?:get|pick up|grab) (?:from|at) the (?:store|shop|grocery store|supermarket)\s*\??$"
        r"|^what(?:'s| is|s)? on (?:my|the) grocery list\s*\??$|^(?:my |the )?grocery list$"
        # "I'm at the store" (2026-10-07: to a model) is the moment the list is for.
        r"|^(?:i'?m|i am|we'?re|we are) (?:at|in) (?:the )?(?:grocery store|store|supermarket|shops?|market|costco|target"
        r"|walmart|trader joe'?s|whole foods|aldi|kroger|safeway|publix|grocer'?s)(?: now)?\s*$")),
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
        r"(?: (?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$"
        # "Do I have any free time thursday" went to the planner (2026-10-08).
        r"|^(?:do i|will i) (?:have|get) (?:any )?(?:free time|time free|spare time|openings|gaps)"
        r"(?: (?:on )?(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$")),
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
        r"|^how (?:long|much time)(?: is there)? (?:until|till|before) my next (?:meeting|appointment|event)$"
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
        # "Give me a summary of my day" (2026-10-07: to the planner).
        r"|^(?:give me |can i get |what(?:'s| is) )?(?:a |the )?(?:summary|rundown|run-down|overview) of (?:my day|today)\s*\??$"
        r"|^(?:summari[sz]e|sum up) my day\s*\??$"
        # "Tell me about my day" (2026-10-08: to the planner).
        r"|^tell me (?:something |a bit |a little )?about (?:my day|today)(?: today)?\s*\??$"
        r"|^what(?:'s| is|s)? (?:on )?(?:for |the plan for )?today\s*\??$|^what (?:am i|are we) doing today\s*\??$"
        r"|^what(?:'s| is|s)? (?:my|the) day (?:look like|looking like)(?: today)?\s*\??$"
        # "Anything I should know about today" (2026-10-08: to the planner).
        r"|^(?:is there )?anything (?:i should|i need to|to) know (?:about )?(?:for )?today\s*\??$"
        r"|^what (?:should i|do i need to) know (?:about )?(?:for )?today\s*\??$"
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
    ("her_name", re.compile(r"^what(?:'s| is|s) your name\s*\??$|^what (?:do|should|can) i call (?:you|u)\s*\??$|^(?:do you have|have you got) a name\s*\??$")),
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
        r"(?: (?P<weather>today|tonight|tomorrow|this weekend|this afternoon|this evening|this morning|later(?: today)?"
        r"|on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)))?$"
        # "Will it rain this afternoon" (2026-10-07: a model).
        r"|^(?:is|will) it (?:going to |gonna )?(?:rain|snow)(?: (?:on )?(?P<weather2>today|tonight|tomorrow|this weekend|the weekend|this week"
        r"|this afternoon|this evening|this morning|later(?: today)?"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$")),
    # SOMEWHERE ELSE (2026-10-07): "what's the weather like in Chicago"
    # went to the planner. Before the pattern for his own weather, which
    # would otherwise never see the town.
    # WHEN IS HIS THING, BY ITS NAME (2026-10-07): "what time is my dentist
    # appointment" and "what are my reminders for tomorrow" went to the
    # planner. Her calendar and her reminders hold both answers.
    ("when_mine", re.compile(
        r"^(?:what time|when|what day)(?:'s| is) (?:my|the|our|(?=(?!my|your|the|our)[a-z]{2,20}(?:'s|s') )) ?(?:next )?(?!last |first )(?P<when_mine>(?:[a-z][a-z' ]{0,30}? )?"
        r"(?:appointment|appt|meeting|call|interview|dinner|lunch|breakfast|class|game|flight|party|reservation|session|visit"
        # "When is my dentist" names the appointment by who it is with (2026-10-07).
        r"|dentist|doctor|therapist|haircut|checkup|check-up|vet|physio|massage|exam|test|shift|practice)"
        r"(?: (?:with|at|for) [a-z][a-z' ]{1,30}?)?)(?: (?:today|tomorrow|this week|next))?\s*\??$")),
    # "What time is lunch with Jess", "how long until lunch with Jess"
    # (2026-10-07: to a model) - a meal or a coffee named by who it is with.
    ("when_with", re.compile(
        r"^(?:what time|when)(?:'s| is) (?:my |the |our )?(?P<when_with>(?:lunch|dinner|breakfast|brunch|coffee|drinks)"
        r" with [a-z][a-z' ]{1,30}?)(?: (?:today|tomorrow))?\s*\??$")),
    # "What's my dentist appointment" (2026-10-07: to a model) - only the
    # words that are always an appointment; "what's my flight" may be a number.
    ("when_mine_what", re.compile(
        r"^what(?:'s| is) (?:my|the|our) (?:next )?(?P<when_mine2>(?:[a-z][a-z' ]{0,30}? )?(?:appointment|appt|interview|reservation)"
        r"(?: (?:with|at|for) [a-z][a-z' ]{1,30}?)?)(?: (?:today|tomorrow|this week|next))?\s*\??$")),
    # "What time do I pick up Leo" (2026-10-07: to a model) - the reminder
    # he set for it, read like "what time is my dentist".
    ("when_do_i", re.compile(
        r"^(?:what time|when) do i (?:have to |need to |got to )?(?P<when_do_i>(?:pick up|drop off|collect|get) [a-z][a-z' ]{1,25}?)"
        r"(?: today| tomorrow)?\s*\??$")),
    # "When am I meeting John" (2026-10-07: to a model).
    ("when_meeting", re.compile(
        # "What time do I meet Dana" (2026-10-08: to a model).
        r"^(?:when|what time) (?:am i|do i) (?:meeting|meet|seeing|see|having (?:lunch|dinner|coffee|breakfast|a call) with|have (?:lunch|dinner|coffee|breakfast|a call) with"
        r"|talking to|calling)(?: with)? (?P<when_meeting>[a-z][a-z' ]{1,25}?)(?: next| again)?\s*\??$"
        # "What do I have with Sam" (2026-10-07: to a model).
        r"|^(?:what do i have|do i have anything|have i got anything)(?: (?:on|coming up|scheduled|planned))? with (?P<when_meeting2>[a-z][a-z' ]{1,25}?)\s*\??$")),
    ("reminders_on", re.compile(
        r"^(?:what are |what(?:'s| is) |read me |list )?(?:my |the )?(?:reminders|alarms)(?: do i have)? (?:for|on) "
        r"(?P<reminders_on>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??$"
        r"|^what reminders do i have (?:for |on )?(?P<reminders_on2>today|tonight|tomorrow|monday|tuesday|wednesday|thursday"
        r"|friday|saturday|sunday)\s*\??$|^(?:do i have |are there |have i got )?any reminders (?:for |on )?(?P<reminders_on3>today|tonight|tomorrow"
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
        r"|^(?:is|will) it (?:going to )?(?:rain|snow) (?P<weather2>today|tonight|tomorrow|this weekend|this week|(?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))$"
        r"|^weather(?: (?P<weather3>today|tonight|tomorrow|this weekend|this week))?$"
        # "When will it stop raining", "is it raining" (2026-10-07: to a model).
        r"|^(?:when (?:will|does|is) it (?:going to )?(?:stop|start) (?:raining|snowing)|is it (?:raining|snowing|sunny|cloudy|foggy) (?:out(?:side)?|right now|now)?)\s*\??$"
        # "Will it be nice this weekend" (2026-10-07: to the planner).
        r"|^(?:will|is) it (?:going to )?be (?:nice|warm|cold|hot|sunny|good)(?: out(?:side)?)? (?P<weather11>today|tonight|tomorrow|this weekend|this week)\s*\??$"
        # "What's the weather this week", "the forecast for the weekend"
        # (2026-10-07: to the planner).
        r"|^what(?:'s| is|s)? the (?:weather|forecast)(?: looking)?(?: like)? (?:for )?(?P<weather9>this week|the week|the rest of the week|the next few days|this weekend|the weekend|today|tonight|tomorrow|(?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\s*\??$"
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
        r"|^how (?:hot|cold|warm|chilly) (?:will it get|is it going to get|will it be|is it going to be)(?: (?P<weather8>today|tonight|tomorrow|this weekend|this week|(?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)))?$"
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
        r"|^how (?:are|r) (?:you|u)(?: doing| feeling| holding up)?(?: today| this morning| tonight)?$"
        r"|^how (?:you|u) doing$|^how goes it$")),
    # Coming and going. "I'm home" and "goodnight" went to the PLANNER and,
    # with nothing thinking, came back "I could not plan that".
    ("arrival", re.compile(
        r"^(?:i'?m|im|i am) (?:home|back|here|in)(?: now)?$|^(?:just )?got (?:home|back|in)$"
        # "I'm back from the gym" (2026-10-07: to a model)
        r"|^(?:i'?m|im|i am|just got|i just got) back from (?:the |my |a |work|school)[a-z ]{0,20}$")),
    ("farewell", re.compile(
        # "Going to bed" and "I'm leaving for work" were planned as steps
        # ("I will let you know when you're ready to go", 2026-09-23).
        r"^(?P<night>good ?night|night night|sleep well|(?:i'?m |im |i am )?(?:going to|off to|heading to) (?:bed|sleep)"
        r"|turning in|see you tomorrow|talk tomorrow)(?:,? thea)?(?: now)?$"
        r"|^(?:(?:i'?m|im|i am) )?(?:leaving|heading out|heading off|going out|off|out|off to work|going to work|"
        r"heading to work|leaving for work|back later|be back later"
        # "I'm leaving work" (2026-10-07: queued for a model to plan).
        r"|heading home|going home|on my way home)"
        r"(?: now| for work| for the day| for a bit)?$"
        r"|^(?:see (?:you|ya)(?: later)?|bye|goodbye|later|talk later|catch you later)$"
        # "I'm going to the gym" (2026-10-07: queued for a model to plan).
        r"|^(?:(?:i'?m|im|i am) )?(?:going|off|heading|leaving|popping out) (?:to|for) (?:the |a |my )?"
        r"(?:gym|store|shops?|grocery store|supermarket|walk|run|jog|class|practice|appointment|doctor'?s?|dentist'?s?|"
        r"school|church|lunch|dinner|coffee|movies|party|game|meeting|errands?|park|office|airport)(?: now| for a bit)?$"
        # "I'm leaving the store" (2026-10-08: to the planner) is on his way.
        r"|^(?:(?:i'?m|im|i am) )?(?:leaving|done at|finished at|walking out of|out of) (?:the )?"
        r"(?:gym|store|shops?|grocery store|supermarket|doctor'?s?|dentist'?s?|school|church|park|office|airport|mall|bank"
        r"|post office|pharmacy|library)(?: now)?$")),
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
        r"|^(?:any|anyone|has anybody|any employers?) (?:written|wrote|got|gotten) back(?: to me)?(?: yet)?$"
        # "Did anyone reply to my applications", "any updates on my job
        # applications" (2026-10-07: to a model, which could not answer).
        r"|^(?:did|has) (?:anyone|anybody|any (?:employers?|companies)) (?:replied|reply|respond|responded|gotten back|got back|get back)"
        r" (?:to|on|about) (?:my |any of my )?(?:job )?(?:applications|apps)(?: yet)?$"
        r"|^(?:any|are there any) (?:updates?|news|replies|word|responses) (?:on|about|from) (?:my |the )?(?:job )?(?:applications|apps)(?: yet| today)?$")),
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
        # "What's 1 billion divided by 365" (2026-10-07: to a model).
        r"|^what(?:'s| is|s)? (?P<a>[\d.,]+(?: (?:thousand|million|billion|trillion))?) (?P<op>plus|minus|times|divided by|over|x|\+|-|\*|/)"
        r" (?P<b>[\d.,]+(?: (?:thousand|million|billion|trillion))?)$"
        # "What is 2+2", "5*3" - the symbol with no spaces (2026-10-07: to a model).
        r"|^(?:what(?:'s| is|s)? |calculate )?(?P<a2>[\d.]+) ?(?P<op2>\+|\*|/|x|×) ?(?P<b2>[\d.]+)\s*\??$"
        r"|^(?:convert |what(?:'s| is|s)? )?(?P<n>-?[\d.,]+) (?:degrees? )?(?P<from>miles?|km|kilometers?|kilometres?|pounds?|lbs?|"
        r"kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|fluid ounces?|fl oz|ml|milliliters?|millilitres?|liters?|litres?|gallons?|quarts?|pints?|grams?|g|yards?|yds?)"
        r" (?:to|in|into) (?P<to>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|"
        r"meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|fluid ounces?|fl oz|ml|milliliters?|millilitres?|liters?|litres?|gallons?|quarts?|pints?|grams?|g|yards?|yds?)$"
        # THE OTHER WORD ORDER: "how many miles is 10 km", "how many pounds in 5 kg"
        r"|^how many (?P<to2>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|fluid ounces?|fl oz|ml|milliliters?|millilitres?|liters?|litres?|gallons?|quarts?|pints?|grams?|g|yards?|yds?) (?:is|are|in|make|equals?|to) (?P<n2>[\d.,]+|a|an|one) ?(?P<from2>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|fluid ounces?|fl oz|ml|milliliters?|millilitres?|liters?|litres?|gallons?|quarts?|pints?|grams?|g|yards?|yds?)$"
        # "What's 72 degrees in Celsius" (2026-10-07: to a model) - the
        # scale it is FROM is the other one.
        r"|^(?:convert |what(?:'s| is|s)? )?(?P<deg>-?[\d.,]+) degrees? (?:to|in|into) (?P<deg_to>celsius|fahrenheit|c|f)$"
        # "What's 98.6 in celsius" (2026-10-07: to a model) - the scale named in full.
        r"|^(?:convert |what(?:'s| is|s)? )?(?P<deg2>-?[\d.,]+) (?:to|in|into) (?P<deg_to2>celsius|fahrenheit)$")),
    ("mine", re.compile(
        r"^what(?:'s| is|s)? my (?P<mine>email(?: address)?|phone(?: number)?"
        r"|number|city|town|name|first name|last name|full name|zip|zip code|postcode|postal code"
        r"|minimum salary|salary(?: floor| requirement| expectation| expectations)?|desired (?:pay|salary)"
        r"|asking (?:pay|salary|price)|pay(?: expectation| expectations)?|notice period|start date)$"
        r"|^who am i$")),
    # "What should you call me" (2026-10-07: to a model).
    ("call_me", re.compile(r"^what (?:should|do|will) (?:you|u) call me$|^what do i go by$"
                           # "What's my nickname" (2026-10-07: to a model)
                           r"|^what(?:'s| is) my (?:nickname|nick name|preferred name)\s*\??$")),
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
    # "What did I tell you today" listed his ASKS (2026-10-08); what he told
    # her is his notes, and the asks are the fallback when there are none.
    # "Who is visiting this weekend" after "my sister is visiting this
    # weekend" (2026-10-08: the question was SAVED as a note).
    ("who_coming_noted", re.compile(
        r"^who(?:'s| is| are) (?P<who_coming_noted>visiting|coming over|coming to visit|coming to stay|coming|staying with us|in town|flying in)"
        r"(?: (?:this weekend|next weekend|this week|next week|tomorrow|tonight|today|on [a-z]+|for [a-z' ]+))?\s*\??$")),
    # "Who called today" after "my mom called" (2026-10-08: both to a model).
    # "What do I like" (2026-10-08: to a model, with "my favorite color is
    # blue" kept): his favorites and what he said he loves.
    ("his_likes", re.compile(
        r"^what (?:do i|things do i|stuff do i) (?:like|love|enjoy)(?: doing)?\s*\??$"
        r"|^what are (?:my|some of my) (?:favou?rites?|favou?rite things|likes)\s*\??$")),
    # "What's my max bench" after "I benched 185" (2026-10-08: to a model).
    ("lift_max", re.compile(
        r"^what(?:'s| is| was) my (?:max|best|heaviest|top|pr|personal best|personal record|one rep max|1 rep max)"
        r"(?: on (?:the )?| for (?:the )?| )?(?P<lift_max>bench(?: press)?|squat|deadlift|overhead press|curl|leg press)\s*\??$"
        r"|^how much (?:can i|do i|did i|have i) (?P<lift_max2>bench|squat|deadlift|curl|leg press)(?:ed)?\s*\??$")),
    # "How long have I had this cold" (2026-10-08: to a model).
    ("sick_since", re.compile(
        r"^how long have i (?:had|been sick with|been dealing with|been fighting) (?:this |my |a |an |the )?"
        r"(?P<sick_since>headache|migraine|cold|fever|flu|sore throat|stomach ?ache|cough)(?: for)?\s*\??$")),
    # "How old am I if I was born in 1990" (2026-10-08: to a model).
    ("born_age", re.compile(
        r"^how old (?:am i|would i be|is (?:someone|somebody|a person|someone who was|somebody who was))"
        r"(?: if i was| if i were| if i'?m| who was)? born in (?P<born_age>(?:19|20)\d\d)\s*\??$"
        r"|^how old (?:is|would be) (?:someone|somebody|a person) born in (?P<born_age2>(?:19|20)\d\d)\s*\??$")),
    ("who_called", re.compile(
        r"^(?:who (?:called|texted|stopped by|came by|dropped by)|did (?:anyone|anybody|someone) (?:call|text|stop by|come by))"
        r"(?: me)?(?: (?P<who_called>today|yesterday|this morning|earlier|earlier today))?\s*\??$")),
    ("told_on", re.compile(
        r"^what (?:did|have) i (?:tell|told) (?:you|u)"
        r" (?P<told_on>yesterday|today|this morning|last night|earlier|earlier today|so far today)\s*\??$")),
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
        r"^what (?:did i|notes did i) (?:note|write down|jot down|save|take|make) (?P<notes_day>today|yesterday|this week|last week)\s*\??$"
        r"|^(?:what (?:are|were) |read(?: me)? |show(?: me)? )?(?:my |the )?notes (?:from|for) (?P<notes_day2>today|yesterday|this week|last week)\s*\??$")),
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
        r"|^when(?:'s| is) the next birthday\s*\??$"
        # "What birthdays are coming up" (2026-10-07: to a model).
        r"|^what birthdays (?:are|do i have|have i got) (?:coming up|soon|next)\s*\??$"
        r"|^(?:what|which) birthdays? (?:is|are) (?:next|soon)\s*\??$"
        # "Who has a birthday this month" (2026-10-07: to a model).
        r"|^(?:whose|who(?:'s| has a| has)) birthdays? (?:is |are )?(?:in )?(?P<bwin3>this week|this month)\s*\??$")),
    ("birthday_when", re.compile(
        r"^when(?:'s| is) (?:my )?(?P<bday>(?!my\b|your\b|our\b)[a-z][a-z ]{0,30}?)(?:'s|s'|’s) (?:birthday|bday)\s*\??$")),
    # A FACT HE TOLD HER, asked back (2026-10-07: "what's my favorite
    # color", "what is my blood type", "when is jess's birthday" each went
    # to a model while the note sat in her journal).
    ("fact_q", re.compile(
        r"^what(?:'s| is|s|are)? my (?P<fact>(?:favou?rite|fave) [a-z][a-z ]{1,25}?)s?\s*\??$"
        r"|^what size (?P<fact6>shoe|shirt|ring|pants|dress)s? do i (?:wear|take|have)\s*\??$"
        r"|^what(?:'s| is|s)? (?:my|the|our) (?P<fact2>blood type|shoe size|shirt size|ring size|pants size|dress size"
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
    # "How long until I need to leave": his reminder to leave. Ahead of
    # task_due, which read it as a task called "leave".
    ("until_leave", re.compile(
        r"^(?:how (?:much time|long) (?:do i have |have i got )?(?:until|till|before) i (?:need to|have to|should|gotta|got to) (?:leave|go|head out)"
        r"|when do i (?:need to|have to|should) (?:leave|head out)(?: today)?)\s*\??$")),
    # "When is my passport task due" (2026-10-07: read as a note about
    # "passport task", and "nothing on file" while the task sat there).
    # "When is it due" a turn after "add a task to renew my passport by
    # Friday" (2026-10-08: to a model): the task just added.
    ("it_due", re.compile(r"^when(?:'s| is| was) (?:it|that|this)(?: one| task)? due\s*\??$")),
    ("task_due", re.compile(
        r"^when(?:'s| is) (?:my |the )?(?!(?:it|that|this|they|them)\b)(?P<due>[a-z0-9][a-z0-9 '-]{1,40}?)(?: task)? due\s*\??$"
        r"|^when do i (?:need|have) to (?P<due2>[a-z][a-z0-9 '-]{1,40}?)(?: by)?\s*\??$"
        r"|^what(?:'s| is) the (?:deadline|due date) (?:for|on) (?:my |the )?(?P<due3>[a-z0-9][a-z0-9 '-]{1,40}?)(?: task)?\s*\??$"
        # "When are my library books due" (2026-10-07: to a model).
        r"|^when are (?:my |the |our )?(?!(?:they|those|these)\b)(?P<due4>[a-z0-9][a-z0-9 '-]{1,40}?) due(?: back)?\s*\??$")),
    ("place_addr", re.compile(
        r"^what(?:'s| is|s) (?:my |the )(?P<place_a>(?!email\b|e-mail\b|ip\b|web\b|mac\b|mailing\b)[a-z][a-z' ]{0,30}?) address\s*\??$")),
    # "What's Jen's kid's name", "who is Bob married to" (2026-10-08: to a
    # model a turn after "Jen's kid's name is Mia", "Bob's wife is Linda").
    ("their_person", re.compile(
        r"^what(?:'s| is) (?P<tp_who>(?!my\b|your\b|the\b)[a-z]{2,15})'s (?P<tp_rel>[a-z][a-z -]{1,20}?)'s name\s*\??$"
        r"|^who(?:'s| is) (?P<tp_who2>(?!my\b|your\b|the\b|it\b|that\b|he\b|she\b)[a-z]{2,15}) married to\s*\??$")),
    # HABITS HE KEEPS COUNT OF (2026-10-08: all to a model): "how many days
    # in a row have I meditated", "how many drinks did I have this week",
    # "am I on track with my workouts".
    # "How many vacation days do I have left" (2026-10-08: to a model, a
    # turn after "I have 3 vacation days left").
    ("days_off", re.compile(
        r"^how many (?P<off_kind>vacation|pto|sick|personal|holiday|leave) days? (?:do i have|have i got|are left|have i (?:got )?left"
        r"|do i have left|have i used|have i taken|did i take|do i get)(?: left)?(?: this year)?\s*\??$"
        r"|^how much (?P<off_kind2>pto|vacation|leave|time off) (?:do i have|have i got)(?: left)?\s*\??$"
        # "How many days off do I have" (2026-10-08: to a model) is vacation.
        r"|^how many (?:days off|vacation days|days of vacation|days of pto) (?:do i have|have i got|are left|do i have left)(?: left)?(?: this year)?\s*\??$")),
    ("habit", re.compile(
        r"^how many days in a row (?:have|did) i (?P<hb_streak>[a-z]+(?: [a-z]+)?)\s*\??$"
        r"|^(?:what(?:'s| is) my|how long is my) (?P<hb_streak2>[a-z]+) streak\s*\??$"
        r"|^how many (?P<hb_count>drinks|beers|glasses of wine|cigarettes|smokes|cups of coffee|coffees|sodas|cokes|energy drinks)"
        r"(?: (?:did|have) i (?:had|have|drink|drunk|drank|smoke|smoked))?(?: (?P<hb_when>today|this week|this month|yesterday))?\s*\??$"
        r"|^(?:am i|how am i doing) on (?:track with |)(?:my )?(?P<hb_goal>workouts?|work ?out goal|exercise(?: goal)?|gym(?: goal)?)\s*\??$"
        r"|^(?:am i on track|how am i doing) (?:with|on) (?:my )?(?P<hb_goal2>workouts?|work ?out goal|exercise(?: goal)?|gym(?: goal)?)\s*\??$")),
    # "When does school start" read back every note naming school, the
    # pictures day first (2026-10-08).
    ("starts_when", re.compile(
        r"^when (?:does|do|is|are|will) (?:the |my |our |[a-z]{2,15}'s )?(?!(?:it|that|this|they|them|he|she|we|you|i)\b)"
        r"(?P<sw_what>[a-z][a-z' ]{1,25}?) (?P<sw_verb>start|starting|begin|beginning|end|ending|finish|over|open|close|get out|let out)\s*\??$")),
    ("recall", re.compile(
        r"^what did i (?:tell|say to) (?:you|u) about (?:the |my )?(?P<recall>[a-z0-9][a-z0-9 '-]{1,40}?)\s*\??$"
        r"|^what(?:'s| is|s)? (?:my |the )(?P<recall2>[a-z0-9][a-z0-9 '-]{1,30}?)(?:'s)? (?P<recall_attr>name|number|address|email|birthday|code|password|pin)\s*\??$"
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
        r"|^do i have any (?P<recall9>allergies)\s*\??$|^am i (?P<recall10>allergic) to [a-z][a-z ,'-]{1,40}\s*\??$"
        # "How many kids do I have", "what are my kids' names" (2026-10-07:
        # to a model, a turn after "my kids are Emma, Leo and Sam").
        r"|^how many (?P<recall13>kids|children|sons|daughters|grandkids|grandchildren|siblings|brothers|sisters) do (?:i|we) have\s*\??$"
        r"|^(?:what are|who are|what's|whats) (?:my|our) (?P<recall14>kids|children|grandkids|grandchildren)(?:'s|'|s)?(?: names?)?\s*\??$")),
    # "What foods don't I like", "do I like mushrooms" (2026-10-07: to a
    # model, a turn after "I don't like mushrooms").
    # "How long have I been married" (2026-10-07: to a model, a turn after
    # "I got married in 2018").
    ("married", re.compile(r"^how long (?:have|has) (?:i|we|anna and i|my wife and i|my husband and i) been married\s*\??$"
                           r"|^how many years (?:have i|have we) been married\s*\??$|^when did (?:i|we) get married\s*\??$"
                           # "What anniversary is this year" (2026-10-08: to a model).
                           r"|^(?:what|which) (?:wedding )?anniversary (?:is (?:it|this|this one|this year|coming up|next)|are we (?:on|at|celebrating)(?: this year)?)\s*\??$")),
    # "What time should I go to bed if I wake up at 6" (2026-10-07: to a model).
    ("bedtime_calc", re.compile(
        r"^(?:what time|when) should i (?:go to bed|go to sleep|sleep|be in bed) (?:if|so|to)(?: that)? i (?:can )?(?:wake up|get up|have to (?:wake|get) up"
        r"|need to (?:wake|get) up|want to (?:wake|get) up|wake) (?:at )?(?P<bt>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)"
        r"(?:,? (?:and |to )?(?:get|have|sleep)(?: for)? (?P<bh>\d{1,2}|seven|eight|nine|six) hours?(?: of sleep)?)?\s*\??$")),
    ("dislikes", re.compile(
        r"^what (?:foods?|things?|food) (?:don't|do not|dont) i (?:like|eat)\s*\??$"
        r"|^what (?:don't|do not|dont) i (?:like|eat)\s*\??$|^what (?:foods? |things? )?do i (?:not like|hate|dislike|not eat)\s*\??$"
        r"|^(?:what are|what's|whats) my (?:food )?dislikes\s*\??$"
        r"|^do i (?:like|eat) (?P<dl_thing>[a-z][a-z ]{1,30}?)\s*\??$")),
    # "When does the plumber come" a turn after noting it (2026-10-07: to
    # the planner). A note answers it; no note is not "never" - his mail or
    # calendar may know - so that case goes on to a model.
    # "Who do I owe money", "how much do I owe Sam", "who owes me" (2026-10-07:
    # each to a model, a turn after "remember I owe Sam 20 dollars").
    ("owed", re.compile(
        r"^who (?:do i owe|owes me)(?: money| anything)?(?: to)?\s*\??$"
        r"|^(?:does|do) (?:anyone|anybody) (?:still )?owe me(?: (?:any )?(?:money|anything))?\s*\??$"
        r"|^(?:do i owe|does) (?:anyone|anybody) (?:any )?(?:money|anything)(?: owe me(?: money)?)?\s*\??$"
        r"|^(?:what|who) do i (?:still )?owe(?: people)?\s*\??$"
        r"|^how much (?:do i (?:still )?owe|does) (?P<owe_amt>[a-z][a-z ]{0,25}?)(?: still)?(?: owe me)?(?: now| still)?\s*\??$"
        # "Do I still owe Sam" (2026-10-07: to the planner).
        r"|^(?:do i (?:still )?owe|does(?=.*\bowe me\b)) (?P<owe_who>(?!anyone\b|anybody\b)[a-z][a-z ]{0,25}?)(?: still)?(?: owe me)?(?: (?:any )?money| anything)?\s*\??$")),
    # "When did I last change the oil", "did I give the dog his medicine"
    # (2026-10-07: to a model and the planner, a turn after he said so).
    # "When did I get promoted" (2026-10-08: to a model, one turn after he
    # said so). Read from the news he told her.
    ("news_when", re.compile(
        r"^when did (?:i|we) (?P<news_when>get (?:promoted|hired|engaged|married|the job|(?:a |my |the )?(?:raise|promotion|offer|job offer|new job))"
        r"|graduate|quit my job|lose my job|get laid off|buy (?:a|the|our|my) (?:house|home|car)|close on (?:the|our|my) house)\s*\??$")),
    # "What did I need to call the vet about" (2026-10-08: to a model, one
    # turn after "I need to call the vet about Max" became a task).
    ("task_about", re.compile(
        r"^what (?:did|do) i (?:need|have|want|say i (?:need|had|wanted)) to (?P<task_about>[a-z][a-z' ]{2,50}?) (?:about|for)\s*\??$"
        r"|^why (?:did|do) i (?:need|have|want) to (?P<task_about2>[a-z][a-z' ]{2,50}?)\s*\??$")),
    # "What am I doing for Sarah" (2026-10-08: to a model, a turn after
    # "remind me to buy flowers for Sarah on Friday").
    ("plans_for", re.compile(
        r"^what (?:am i|are we) (?:doing|getting|planning|giving|buying) (?:for )?(?!(?:dinner|lunch|breakfast|brunch|christmas|thanksgiving|halloween|easter|today|tonight|tomorrow|the|work|fun|now|money|food|it|that|this|them|him|her|you|me|my (?:birthday|anniversary)|new year)\b)(?P<plans_for>(?:my )?[a-z][a-z'-]{1,20})"
        r"(?: for (?:her|his|their) (?:birthday|anniversary|bday))?\s*\??$"
        r"|^what (?:do i have|have i got) (?:planned|lined up) for (?!(?:dinner|lunch|breakfast|brunch|christmas|thanksgiving|halloween|easter|today|tonight|tomorrow|the|work|fun|now|money|food|it|that|this|them|him|her|you|me|my (?:birthday|anniversary)|new year)\b)(?P<plans_for2>(?:my )?[a-z][a-z'-]{1,20})(?:'s (?:birthday|bday))?\s*\??$")),
    # "What's broken in the house", "is the sink fixed" (2026-10-08: both to
    # a model, with "the dishwasher is broken" kept).
    ("broken", re.compile(
        r"^what(?:'s| is|s)? (?:still )?(?:broken|not working|needs fixing|needs to be fixed|needs repair)"
        r"(?: in the house| at home| around the house| at the house)?(?P<broken>)\s*\??$"
        r"|^(?:is|are|did) (?:the|my|our) (?P<broken2>[a-z][a-z' ]{1,25}?) (?:fixed|repaired|still broken|get fixed)(?: yet| now)?\s*\??$")),
    # "What do I need to bring", "who is having the party", "where am I
    # meeting Tom" (2026-10-08: each to a model, one turn after he said it).
    ("to_bring", re.compile(
        r"^what (?:do|did) i (?:need|have|want|say i(?:'d| would)? need) to (?P<to_bring>bring|take|pack|wear|make|buy|get)"
        r"(?: (?:to|for) (?:the |my |our )?[a-z][a-z' ]{1,25})?\s*\??$")),
    ("event_who", re.compile(
        r"^who(?:'s| is) (?:having|hosting|throwing|doing) (?:the |this |that )?(?P<event_who>[a-z][a-z' ]{1,25}?)\s*\??$"
        r"|^where am i (?:meeting|seeing|having (?:coffee|lunch|dinner|drinks) with) (?P<event_who2>[a-z][a-z' ]{1,25}?)(?: tomorrow| today| tonight)?\s*\??$")),
    # "Is my passport still valid" (2026-10-08: to the planner, a turn
    # after "my passport expires on June 5 2027").
    ("still_valid", re.compile(
        r"^(?:is|are) (?:my|our) (?P<still_valid>[a-z][a-z' ]{1,25}?) (?:still )?(?:valid|expired|current|up to date|out of date)(?: yet)?\s*\??$"
        r"|^(?:has|have) (?:my|our) (?P<still_valid2>[a-z][a-z' ]{1,25}?) expired(?: yet)?\s*\??$")),
    # "Who lives in Chicago" (2026-10-08: to a model, after "my brother
    # lives in Chicago").
    ("who_lives", re.compile(
        r"^who (?:do i know (?:that |who )?)?(?:lives|live|is living|stays|moved) (?:in|near|to) (?P<who_lives>[a-z][a-z .'-]{1,30}?)\s*\??$")),
    # "Can I eat chicken" with "I am vegetarian" kept (2026-10-08: to the
    # planner). Only what his notes settle; anything else is a model's.
    ("can_eat", re.compile(r"^(?:can|should) i (?:eat|have|drink) (?:a |an |some |the )?(?P<can_eat>[a-z][a-z ]{1,25}?)\s*\??$")),
    # "What bills do I have coming up" (2026-10-08: to a model, with "the
    # water bill is due on the 15th" kept).
    ("bills_due", re.compile(
        r"^(?:what|which) bills (?:do i (?:need|have) to pay|(?:do i have |have i got |are )?(?:coming up|due|to pay|left to pay))"
        r"(?: this (?:week|month)| soon| next)?\s*\??$")),
    # "What do you remind me every morning", "what are my daily reminders"
    # (2026-10-08: to a model and to a memory search).
    ("repeating", re.compile(
        r"^what (?:do|will) (?:you|u) remind me (?:about |of |to do )?every (?P<repeating>morning|day|night|evening|week|month)\s*\??$"
        r"|^what(?: are|'s|s)? my (?P<repeating2>daily|weekly|monthly|recurring|repeating|regular|morning|nightly) reminders?\s*\??$")),
    # "What restaurants do I like" (2026-10-08: to a model, with his
    # favorite and "I tried Nobu and loved it" kept).
    ("places_liked", re.compile(
        r"^(?:what|which) (?:restaurants|places(?: to eat)?|spots) do (?:i|we) (?:like|love|enjoy)\s*\??$"
        r"|^what are (?:my|our) favou?rite (?:restaurants|places to eat|places)\s*\??$")),
    # "What did the insurance company say" (2026-10-08: to a model, a turn
    # after "they said the claim was approved" was kept under their name).
    ("who_said", re.compile(
        # Only "the ..." - a person by name may be in his mail ("what did
        # Dana say" is a model's).
        r"^what did (?P<who_said>the [a-z][a-z' &.-]{1,40}?) (?:say|tell me|tell you)\s*\??$")),
    # "How many kids does Jake have" after "Jake has two kids" (2026-10-08:
    # to a model).
    ("how_many_has", re.compile(
        r"^(?:how many (?P<hm_what>kids|children|sons|daughters|grandkids|grandchildren|brothers|sisters|siblings|dogs|cats|pets)"
        r" (?:does|do) (?P<hm_who>(?:my )?[a-z][a-z'-]{1,20}) have"
        r"|(?:does|do) (?P<hm_who2>(?:my )?[a-z][a-z'-]{1,20}) have (?:any )?(?P<hm_what2>kids|children|sons|daughters|grandkids"
        r"|grandchildren|brothers|sisters|siblings|dogs|cats|pets))\s*\??$")),
    # "What episode am I on" after "I'm on episode 4 of Severance", and
    # "what did I rate Severance" (2026-10-08: to a model).
    ("episode_on", re.compile(
        r"^what (?:episode|season|ep) (?:am i on|was i on|did i get to|am i up to)(?: (?:of|in|with) (?P<episode_on>[a-z0-9][a-z0-9' :-]{1,40}?))?\s*\??$"
        r"|^where (?:am i|was i|did i leave off|did i get to) (?:in|with|on) (?P<episode_on2>[a-z0-9][a-z0-9' :-]{1,40}?)\s*\??$")),
    ("rated", re.compile(
        r"^(?:what|how) did i (?:rate|score|give) (?P<rated>[a-z0-9][a-z0-9' :-]{1,40}?)\s*\??$")),
    ("did_last", re.compile(
        r"^when did i (?:last )?(?P<did_v>change|give|feed|walk|water|clean|wash|mow|vacuum|replace|renew|fix|service"
        r"|rotate|flush|empty|refill|fill|charge|back up|update|trim|cut|groom|bathe|drop off|pick up|return|mail|post"
        r"|vaccinate|deworm|descale|defrost|call|visit|pay|talk to|talk with|speak to|speak with|see|meet with|meet up with|meet"
        r"|hang out with|text|catch up with|lock|close|shut|unplug|turn off|take out) (?P<did_o>[a-z][a-z' ]{1,40}?)(?: last)?\s*\??$"
        r"|^(?:did|have) i (?:already )?(?P<did_v2>change|changed|give|given|feed|fed|walk|walked|water|watered|clean|cleaned"
        r"|wash|washed|mow|mowed|vacuum|vacuumed|replace|replaced|renew|renewed|charge|charged|empty|emptied|refill|refilled"
        r"|drop off|dropped off|pick up|picked up|return|returned|mail|mailed|call|called|visit|visited|pay|paid"
        r"|talk to|talked to|speak to|spoken to|see|seen|text|texted|lock|locked|close|closed|shut|unplug|unplugged"
        r"|turn off|turned off|take out|taken out|took out) (?P<did_o2>(?!any\b)[a-z][a-z' ]{1,40}?)"
        r"(?P<did_today> today| yet| this morning| this week| this month)?\s*\??$"
        # "When did I last get a haircut" (2026-10-07: to a model). Only a
        # service: "when did I get that email" belongs to the mail.
        r"|^when did i (?:last )?(?P<did_v3>get|have) (?P<did_o3>" + _SERVICES + r"|gas)(?: last| done)?\s*\??$"
        # "When did the dog get his heartworm pill" (2026-10-08: to a model,
        # a turn after "I gave the dog his heartworm pill").
        r"|^when did (?P<did_who6>the (?:dog|cat|puppy|kitten|baby|kids?)|my (?:dog|cat|son|daughter|kids?|wife|husband|mom|dad)"
        r"|(?!i\b|you\b|we\b|they\b|it\b)[a-z]{2,15}) (?:last )?(?:get|have|take) (?P<did_pro6>his|her|their|its|the|a) (?P<did_o6>[a-z][a-z' ]{1,30}?)"
        r"(?: last)?\s*\??$"
        r"|^(?:did|have) i (?:already )?(?P<did_v4>get|got|gotten|have|had) (?P<did_o4>" + _SERVICES + r")"
        r"(?P<did_today2> today| yet| this morning| this week| this month)?\s*\??$"
        # "How long since I talked to mom" (2026-10-07: to a model).
        r"|^how long (?:has it been |is it |'s it been )?since i (?:last )?(?P<did_v5>changed|gave|fed|walked|watered|cleaned|washed"
        r"|mowed|vacuumed|replaced|renewed|called|visited|paid|talked to|talked with|spoke to|spoke with|saw|met with|texted"
        r"|caught up with|change|give|feed|walk|water|clean|wash|mow|call|visit|pay|talk to|speak to|see|text) (?P<did_o5>[a-z][a-z' ]{1,40}?)\s*\??$")),
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
        r"^what (?:kind of |type of |make of |sort of )?(?!(?:(?:recurring|repeating|regular|daily|weekly|monthly|other|upcoming|open|active) )?(?:notes?|reminders?|tasks?|lists?|meetings?|appointments?"
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
    # "Yes or no" (2026-10-07: to the planner) - a coin with other words on it.
    ("yes_no", re.compile(r"^(?:just )?(?:say )?yes or no\s*\??$|^(?:give me a )?random yes or no$")),
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
                       r"|^(?:(?:what(?:'s| is|s)?|how much is) the )?tip on \$?(?P<what3>[\d,]+(?:\.\d{1,2})?)(?: dollars?| bucks)?(?: bill)?$"
                       r"|^how much (?:should i|do i) tip on (?:a |an )?\$?(?P<what4>[\d,]+(?:\.\d{1,2})?)(?: dollars?| bucks)?(?: bill)?$")),
    # "HOW MUCH IS 50 EUROS IN DOLLARS" (2026-10-07: to a model, which
    # cannot know today's rate). The ECB's published rate, or "I couldn't
    # reach it" - never a remembered number.
    ("currency", re.compile(r"^(?:how much is |what(?:'s| is|s)? |convert )?\$?(?P<what>[\d,]+(?:\.\d+)?) (?P<what2>(?:us dollars?|dollars?|bucks|usd|euros?|eur|british pounds|pounds?|gbp|quid|sterling|japanese yen|yen|jpy|canadian dollars?|cad|australian dollars?|aud|mexican pesos|pesos?|mxn|swiss francs|francs?|chf|yuan|renminbi|cny|rupees?|inr|won|krw|krona|kronor|sek))"
                            r" (?:in|to|into) (?P<what3>(?:us dollars?|dollars?|bucks|usd|euros?|eur|british pounds|pounds?|gbp|quid|sterling|japanese yen|yen|jpy|canadian dollars?|cad|australian dollars?|aud|mexican pesos|pesos?|mxn|swiss francs|francs?|chf|yuan|renminbi|cny|rupees?|inr|won|krw|krona|kronor|sek))$"
                            r"|^how many (?P<what4>(?:us dollars?|dollars?|bucks|usd|euros?|eur|british pounds|pounds?|gbp|quid|sterling|japanese yen|yen|jpy|canadian dollars?|cad|australian dollars?|aud|mexican pesos|pesos?|mxn|swiss francs|francs?|chf|yuan|renminbi|cny|rupees?|inr|won|krw|krona|kronor|sek)) (?:is|are|in|for|to) (?:a |an |one |(?P<what5>[\d,]+(?:\.\d+)?) )?(?P<what6>(?:us dollars?|dollars?|bucks|usd|euros?|eur|british pounds|pounds?|gbp|quid|sterling|japanese yen|yen|jpy|canadian dollars?|cad|australian dollars?|aud|mexican pesos|pesos?|mxn|swiss francs|francs?|chf|yuan|renminbi|cny|rupees?|inr|won|krw|krona|kronor|sek))$")),
    ("riddle", re.compile(r"^(?:tell me|give me|do you have|got|know) (?:a |another |any )?riddles?$")),
    ("count_to", re.compile(r"^count (?:to|up to) (?P<what>\d{1,2}|ten|five|three|twenty)$")),
    ("alarm_q", re.compile(r"^what time (?:did i set|is) my alarm(?: set)?(?: for)?(?: tomorrow| today| tonight| in the morning| on [a-z]+day)?$"
                           r"|^when(?:'s| is) my alarm(?: set for)?(?: tomorrow| in the morning)?$"
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
    # "What do I do on Fridays" (2026-10-08: to a model): the reminders
    # that repeat that day, what is on the coming one, and what he said
    # happens then. Ahead of status_of, which read "what's happening on
    # saturdays" as the fleet.
    ("on_days", re.compile(
        r"^what(?: do i (?:usually |normally )?(?:do|have(?: going on)?)|(?:'s| is|s) (?:usually |normally )?(?:on|happening))"
        r" (?:on )?(?P<od>monday|tuesday|wednesday|thursday|friday|saturday|sunday)s\s*\??$")),
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
    ("pick_for_me", re.compile(
        r"^(?:recommend|suggest|pick) (?:me )?(?:a |something to )?(?P<pick_watch>movie|film|show|something to watch|watch)(?: to watch)?(?: tonight)?\s*\??$"
        r"|^what (?:movie |film |show |tv show )?(?:should|could|can) (?:i|we) (?P<pick_watch2>watch)(?: tonight| now| next)?\s*\??$"
        r"|^what (?:should|could|can) (?:i|we) (?P<pick_read>read)(?: next)?\s*\??$"
        # "Recommend a book" (2026-10-07: to the planner) - off his reading list.
        r"|^(?:recommend|suggest|pick) (?:me )?(?:a |something to )?(?P<pick_read2>book|read|novel)(?: to read)?(?: next)?\s*\??$"
        r"|^where (?:should|could|can|shall) (?:i|we) (?P<pick_eat>eat|go (?:to eat|for dinner|for lunch|out))(?: tonight| today| for dinner| for lunch)?\s*\??$")),
    # "What temperature do I cook chicken to", "how long do I boil an egg"
    # (2026-10-07: "I can't think just now"). The safe temperatures are the
    # USDA's published minimums, the same every time - a table, not a guess.
    ("cook_temp", re.compile(
        r"^(?:what(?:'s| is)? (?:the )?(?:safe |internal |minimum )*(?:temp(?:erature)?|temp) (?:do i |should i |to )?(?:cook|for|of)"
        r"|what (?:temp(?:erature)?|temp) (?:do i|should i|does|is) (?:cook )?)"
        r" ?(?:a |an |the )?(?P<cook_temp>chicken|turkey|poultry|duck|ground beef|ground pork|ground turkey|ground chicken|burgers?|hamburgers?"
        r"|pork(?: chops?| loin| tenderloin)?|ham|beef|steak|lamb|veal|roast|fish|salmon|tuna|shrimp|eggs?|leftovers|casseroles?)"
        r"(?: breasts?| thighs?| wings?)?(?: cooked| done| safe)?(?: to| at)?\s*\??$"
        r"|^what (?:temp(?:erature)?|internal temp(?:erature)?) (?:should|does|do) (?:a |an |the |my )?(?P<cook_temp2>chicken|turkey|pork|ham|beef"
        r"|steak|lamb|fish|salmon|ground beef|burgers?|eggs?)(?: breasts?| thighs?| chops?)? (?:be|reach|need to be|have to be)"
        r"(?: cooked)?(?: to| at)?\s*\??$"
        r"|^how long (?:do i|should i|to|do you) (?P<egg_boil>soft |hard |medium )?boil (?:an? |the )?(?P<egg_kind>soft |hard |medium )?(?:boiled )?eggs?"
        r"(?: for)?\s*\??$")),
    ("meal_plan", re.compile(
        r"^what(?:'s| is) (?:on )?(?:my|the|our) meal plan(?: for (?P<mp_day>today|tonight|tomorrow|this week|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?\s*\??$"
        r"|^(?:read|show) me (?:my|the|our) meal plan\s*\??$"
        r"|^what (?:am i|are we) (?:having|eating|making|cooking) for (?:dinner|supper|lunch)(?:(?: on)? (?P<mp_day2>today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?: night)?)?\s*\??$"
        r"|^what(?:'s| is) for (?:dinner|supper|lunch) (?:on )?(?P<mp_day3>tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?: night)?\s*\??$")),
    ("meal_idea", re.compile(
        r"^what (?:should|can|could|shall) (?:i|we) (?:have|eat|make|cook|get) for (?P<meal>breakfast|lunch|dinner|supper|tea)(?: tonight| today)?$"
        r"|^what(?:'s| is) for (?P<meal2>breakfast|lunch|dinner|supper)(?: tonight| today)?$"
        r"|^(?:give me |any )?(?P<meal3>breakfast|lunch|dinner|supper) ideas?$")),
    ("parked", re.compile(r"^where (?:did i|have i) park(?:ed)?(?: the car| my car)?(?: (?:at|in) (?:the )?(?P<parked_at>[a-z][a-z ]{1,25}))?$"
                          r"|^where(?:'s| is) (?:my|the) car(?: parked)?$")),
    # 2026-10-07, every one to a model with nothing to think about:
    ("sun", re.compile(
        r"^(?:what time|when) (?:is|does|will) (?:the )?(?P<sun>sunset|sunrise|sun (?:set|rise|go down|come up))(?: (?P<sunday>today|tonight|tomorrow))?$"
        r"|^when(?:'s| is) (?P<sun2>sunset|sunrise)(?: (?P<sunday2>today|tonight|tomorrow))?$"
        r"|^what time(?: is it| does it get) (?P<sun3>dark|light)(?: (?P<sunday3>today|tonight|tomorrow))?$"
        # "When does it get dark" (2026-10-07: to the planner).
        r"|^when (?:does|will) it get (?P<sun4>dark|light)(?: (?P<sunday4>today|tonight|tomorrow))?$"
        # "Sunrise tomorrow", "what time is sunrise tomorrow" (2026-10-07: to the planner).
        # "What's the sunrise tomorrow", "when's the sunset" (2026-10-07: a memory search).
        r"|^(?:what time is |what time's |what(?:'s| is|s) |when(?:'s| is) )?(?:the )?(?P<sun5>sunset|sunrise)"
        r"(?: (?:time )?(?P<sunday5>today|tonight|tomorrow))?$"
        # "How long until sunset" (2026-10-08: to a model) - the time it is.
        r"|^how (?:long|much (?:longer|time)) (?:is it )?(?:until|till|til|before) (?:the )?(?P<sun6>sunset|sunrise|dark|it gets dark|the sun sets)$")),
    ("moon", re.compile(
        r"^what(?:'s| is) the (?:moon(?: phase)?|phase of the moon)(?: tonight| today)?$"
        r"|^what phase is the moon(?: in)?(?: tonight| today)?$"
        r"|^is (?:it|there) a full moon(?: tonight| today)?$|^when(?:'s| is) the next (?:full|new) moon$")),
    # "What's the plural of moose" (2026-10-07: to a model).
    ("plural", re.compile(r"^what(?:'s| is|s)? the plural (?:of|for) (?:an? )?(?P<plural>[a-z]{2,20})\s*\??$"
                          r"|^(?:what(?:'s| is) )?(?:the )?plural (?:of|for) (?:an? )?(?P<plural2>[a-z]{2,20})\s*\??$")),
    # 2026-10-07, all to a model with nothing to think about: "what's 8
    # percent sales tax on 45", "if I save 200 a month how much will I have
    # in a year", "what year was it 25 years ago", "how tall is 180 cm in feet".
    ("sums_more", re.compile(
        r"^(?:what(?:'s| is|s)? |how much is |calculate )?(?:the )?(?P<tax>\d{1,2}(?:\.\d{1,3})?) ?(?:%|percent) (?:sales )?tax on \$?(?P<tax_on>[\d,]+(?:\.\d{1,2})?)(?: dollars| bucks)?\s*\??$"
        r"|^if i (?:save|put away|set aside) \$?(?P<save>[\d,]+(?:\.\d{1,2})?)(?: dollars| bucks)? (?:a|per|every) (?P<save_per>week|month|day|year)"
        r",? how much (?:will|would) i have (?:saved )?(?:in|after) (?P<save_n>a|one|two|three|four|five|six|ten|\d{1,2}) (?P<save_u>weeks?|months?|years?)\s*\??$"
        r"|^what year (?:was it|will it be) (?P<yr_n>\d{1,4}) years? (?P<yr_dir>ago|from now)\s*\??$"
        r"|^what year will it be in (?P<yr_n2>\d{1,4}) years?\s*\??$"
        r"|^how (?:tall|long|far|heavy|big|wide|deep|high|hot|cold|much) is (?!(?:a |an )?\d+(?:\.\d)?k\b)(?P<conv>(?:a |an )?[\d.,]+ ?[a-z°]+(?: [a-z]+)?) in (?P<conv_to>[a-z ]+?)\s*\??$")),
    ("discount", re.compile(
        r"^(?:what(?:'s| is|s)? |how much is |calculate )?(?P<off>[\d.]+) ?(?:%|percent) off (?:of )?\$?(?P<price>[\d.,]+)(?: dollars| bucks)?$"
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
        r"(?P<ways3>\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)(?: people| of us| ways| friends)?$"
        # "Split 120 three ways with tip" (2026-10-08: refused as spending).
        # Arithmetic on a bill, with the tip said or a 20% one named.
        r"|^(?:split|divide) (?:a |the )?\$?(?P<bill4>[\d.,]+)(?: dollars?| bucks)?(?: bill| check)? (?:(?:between|among|by|for) )?"
        r"(?P<ways4>\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)(?: people| of us| ways| friends)?"
        r",? (?:with|plus|including|and) (?:a )?(?:(?P<tip_pct>\d{1,2}) ?(?:%|percent) )?(?:tip|gratuity)$")),
    ("area", re.compile(
        r"^(?:what(?:'s| is) the )?(?:square footage|area) of (?:a )?(?P<w>[\d.]+) by (?P<l>[\d.]+)(?: room| foot room)?$"
        r"|^how many square feet is (?:a )?(?P<w2>[\d.]+) by (?P<l2>[\d.]+)(?: room)?$")),
    ("year_left", re.compile(
        r"^how many (?P<unit>days|weeks|months) (?:are )?(?:left|remaining) (?:in|of|until the end of) (?:the|this) year$")),
    # "What's next Friday", "what's the 15th" (2026-10-08: each to a model).
    # The date, and what is on it.
    # "What was I working on" (2026-10-08: to the planner and a model). The
    # last "I'm working on X" he told her; "where was I" is the thread's.
    ("where_was_i", re.compile(
        r"^(?:what was i (?:working on|in the middle of)(?: before)?"
        r"|remind me what i was (?:working on|doing|in the middle of))\s*\??$")),
    # "What did I just add" (2026-10-08: to a model): her last "Added ..."
    # in this conversation, said back.
    ("just_added", re.compile(
        r"^what (?:did i|have i) (?:just )?(?:add|put)(?:ed)?(?: (?:to|on) (?:the|my) (?:[a-z]+ )?list)?\s*\??$"
        # "What did I just do", "what did I just say" (2026-10-08: to a model)
        r"|^what did i just (?P<ja_do>do|say|ask(?: you)?(?: for)?|tell you)\s*\??$")),
    ("date_what", re.compile(
        r"^what(?:'s| is|s) (?:(?:this|next) (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|the \d{1,2}(?:st|nd|rd|th)?)\s*\??$")),
    ("weekday_of", re.compile(
        r"^what day (?:of the week )?(?:was|is|will be|falls on|did) (?!it\b|today\b|tomorrow\b)(?P<wd>.+?)(?: (?:fall on|on|be))?$")),
    # 2026-10-07, each to the planner: "how many days since January 1", "is
    # it the weekend", "what's 3 weeks from today", "how old is someone born
    # in 1990". Arithmetic on the calendar, nothing to think about.
    # "How long have I been at my job", "how many days since I started my
    # new job" (2026-10-07: an application called "many days since I
    # started my new", and a model).
    ("job_since", re.compile(
        # "How long have I worked here" (2026-10-08: to a model)
        r"^(?:how long have i (?:worked here|been working here|been here at work|been at this job|been (?:at|with|working at|working for|in) (?:my (?:new )?job|work|my company|my role|[a-z][a-z0-9&.' -]{1,30}?)|had my (?:new )?job|worked (?:at|for) [a-z][a-z0-9&.' -]{1,30}?)"
        r"|how many (?:days|weeks|months) (?:since i started|have i been at|have i had) (?:my (?:new )?job|work|at [a-z][a-z0-9&.' -]{1,30}?|working at [a-z][a-z0-9&.' -]{1,30}?)"
        r"|when did i start (?:my (?:new )?job|work at [a-z][a-z0-9&.' -]{1,30}?|working at [a-z][a-z0-9&.' -]{1,30}?|at [a-z][a-z0-9&.' -]{1,30}?))\s*\??$")),
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
        r"^(?:how old (?:is|will) |what age (?:is|will) )(?P<age_of>(?:my )?[a-z][a-z'-]{1,20}(?: (?!be\b|turn\b|turning\b|now\b)[a-z][a-z'-]{1,20})?)"
        r"(?: be| turn| be turning| turning| now)?(?: this year| next| on (?:his|her|their) (?:next )?birthday)?\s*\??$")),
    ("took_today", re.compile(
        r"^(?:did|have) i (?:take|taken|had|have) (?:my |any |an? |some )?(?:morning |evening |night |daily )?(?P<took>medicine|meds|medication|pills?|vitamins?"
        r"|insulin|inhaler|antibiotics?|[a-z]+ pills?|" + _DRUGS + r")(?: today| this morning| tonight| yet| already)?\s*\??$"
        # "When did I last take ibuprofen" (2026-10-07: to a model).
        r"|^when did i (?:last )?(?:take|have) (?:my |an? |some |the )?(?P<took2>medicine|meds|medication|pills?|vitamins?|insulin|" + _DRUGS + r")"
        r"(?: last)?\s*\??$"
        # "When can I take more Tylenol" (2026-10-07: to a model). When he
        # last took it is hers to say; how long to wait is the label's.
        r"|^(?:when|how soon) (?:can|should|could) i (?:take|have) (?:more|another(?: dose)?|my next(?: dose)?|some more) (?:of )?(?:my |the )?"
        r"(?P<took3>medicine|meds|medication|pills?|insulin|" + _DRUGS + r")\s*\??$")),
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
    # "What's 1000 seconds in minutes", "convert 90 minutes to hours" (2026-10-07: a model).
    ("dur_convert", re.compile(
        r"^(?:convert |what(?:'s| is|s) )?(?P<dn>\d[\d,]*(?:\.\d+)?) (?P<du>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)"
        r" (?:to|in|into|in to) (?P<dt>seconds|minutes|hours|days|weeks)\s*\??$"
        r"|^how many (?P<dt2>seconds|minutes|hours|days|weeks) (?:is|are) (?P<dn2>\d[\d,]*(?:\.\d+)?) "
        r"(?P<du2>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\s*\??$")),
    # "What's pi" (2026-10-07: a model, and with none "I can't think just now").
    ("constant", re.compile(
        r"^(?:what(?:'s| is|s) )?(?:the value of )?(?P<const>pi|the speed of light|the golden ratio|absolute zero|"
        r"the boiling point of water|the freezing point of water)(?: to (?:\d+|five|ten) (?:digits|decimal places))?\s*\??$")),
    # "What's the capital of France" (2026-10-07: a model, and with none "I
    # can't think just now"). A fixed table; a place not in it is a model's.
    ("capital", re.compile(
        r"^what(?:'s| is|s) the capital(?: city)? of (?:the )?(?P<cap>[a-z][a-z .']{2,30}?)\s*\??$"
        r"|^what(?:'s| is|s) (?:the )?(?P<cap2>[a-z][a-z .']{2,30}?)(?:'s| s) capital(?: city)?\s*\??$")),
    # "How do I add a reminder" (2026-10-07: a model, and with none "I can't think just now").
    ("how_to", re.compile(
        r"^how (?:do|can|would|should) i (?P<howto>add|set|set up|make|create|start|put|cancel|delete|remove|turn off|stop|"
        r"check|see|read|hear|find) (?:a |an |my |the |up )?(?:new )?(?P<howto_what>reminders?|alarms?|timers?|tasks?|to ?dos?|"
        r"notes?|shopping list|lists?|calendar events?|events?|appointments?|holds?|stopwatch)"
        r"(?: (?:with|using|on|to|from) you| on (?:my|the|your) (?:list|calendar))?\s*\??$")),
    ("fraction_pct", re.compile(r"^what(?:'s| is) (?P<num>\d+)/(?P<den>\d+) (?:as a |in )?percent(?:age)?$")),
    ("feeling", re.compile(
        # "I've been feeling tired lately" (2026-10-08: to the planner)
        r"^(?:i(?:'m| am)(?: feeling)?|im(?: feeling)?|i feel|feeling|i(?:'ve| have) been(?: feeling)?) (?:so |really |kind of |pretty |a bit |very )?"
        r"(?P<feel>hungry|bored|tired|exhausted|sleepy|stressed|stressed out|overwhelmed|anxious|sad|down|lonely|sick"
        # "I'm procrastinating" (2026-10-07: to the planner)
        r"|procrastinating|unmotivated|distracted|stuck|thirsty|cold|freezing|hot|nervous|scared|worried|running late|stuck in traffic"
        r"|late|frustrated|annoyed|angry|mad|pissed off|fed up|sick of (?:this|it|everything|work)|so done)(?: today| again| now| right now| lately| recently| all week| this week| all day)?(?P<feel_about> (?:about|for|before) (?:my |the |a |an )?[a-z][a-z ]{1,30})?$"
        r"|^(?P<feel2>i can'?t sleep|i can'?t (?:focus|concentrate)|i need a break|motivate me|i'?m having a (?:bad|rough|hard) day|i had a (?:bad|rough|hard|long) day"
        r"|(?:give me|i need) a pep talk|pep talk|i need (?:some )?motivation|say something nice|cheer me up|make me smile"
        r"|give me a compliment|compliment me|say something nice about me"
        # "I have a headache" (2026-10-07: to a model) is "I'm sick".
        r"|i(?:'ve| have)(?: got| had)? (?:a |an )?(?:headache|migraine|cold|fever|flu|the flu|sore throat|stomach ?ache|cough)"
        # "I have a headache since this morning" (2026-10-08: to the planner).
        r"(?: (?:since (?:this morning|last night|yesterday|lunch|[a-z]+day)|all (?:day|morning|week)|again|today|right now|now))?"
        r"|i (?:don'?t|do not) feel (?:so |very )?(?:good|well|great)"
        # "I think I'm getting a cold" (2026-10-07: to the planner).
        r"|i (?:think i'?m|might be|may be|feel like i'?m) (?:getting|coming down with|catching) (?:a |an |the )?(?:cold|flu|fever|something|sick|bug))$")),
    # Good news, a good mood, a birthday, a loss (2026-10-07: every one to a
    # model, and with none "I can't think just now" to "my dog died").
    ("life_news", re.compile(
        r"^(?:i(?:'m| am)(?: feeling)?|im(?: feeling)?|i feel|feeling) (?:so |really |pretty |very |super )?"
        # Not "I'm good": that is as often "no thanks" as a mood.
        r"(?P<good>great|amazing|awesome|happy|fantastic|wonderful|excited|better|much better)(?: today| now)?!*$"
        r"|^(?:i|we) (?P<win>got the job|got (?:a |the |my )?(?:raise|promotion|offer|job offer|new job)|got promoted|got hired"
        r"|passed (?:my |the )?(?:test|exam|driving test|interview|class|bar|boards)|got engaged|got married|graduated"
        r"|finished (?:my |the )?(?:degree|marathon|race)|bought a (?:house|home|car)|closed on (?:the|our|my) house)(?: today)?!*$"
        r"|^(?:i'?m|i am|we'?re|we are) (?P<win2>getting married|engaged|having a baby|pregnant|expecting)!*$"
        # "I didn't get the job", "I quit my job" (2026-10-07: to the planner).
        r"|^i (?P<setback>didn'?t get (?:the|that) (?:job|offer|promotion|apartment|house|part|role)|did not get (?:the|that) (?:job|offer|promotion|role)"
        r"|got (?:rejected|turned down|laid off|fired|let go)|lost my job|was laid off|was let go|failed (?:my |the )?(?:test|exam|interview|driving test|class))(?: today)?$"
        r"|^i (?P<quit>quit my job|just quit|put in my notice|gave my notice|handed in my notice|resigned)(?: today)?!*$"
        r"|^(?:it'?s|today is|today's) my (?P<celebrate>birthday|anniversary|wedding anniversary|work anniversary)(?: today)?!*$"
        r"|^my (?P<loss>dog|cat|pet|bird|horse|grandma|grandmother|grandpa|grandfather|mom|mum|mother|dad|father|uncle|aunt"
        r"|friend|brother|sister|husband|wife|partner|cousin|best friend) (?:just )?(?:died|passed away|passed)"
        r"(?: today| yesterday| this morning| last night| this week)?$"
        # "My sister had a baby" (2026-10-07: to the planner).
        r"|^my (?P<theirs>mom|mum|mother|dad|father|sister|brother|son|daughter|wife|husband|partner|friend|best friend|cousin"
        r"|aunt|uncle|grandma|grandpa|boss|niece|nephew|neighbou?r) (?P<their_news>had a baby|had her baby|is pregnant|got engaged"
        r"|got married|graduated|got (?:a |the |her |his )?(?:new )?job|got (?:a |the )?promotion|got promoted|bought a (?:house|home|car)"
        r"|turned \d{1,3}|is having a baby|had twins)(?: today| yesterday| this week)?!*$")),
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
    # ANY "WHAT'S MY X" he told her in so many words (2026-10-07: "what's my
    # locker combo" paid a model to find "my locker combo is 12 34 56").
    # LAST, and silent when no note says "my X is": the model still answers.
    ("kept", re.compile(
        r"^(?:what (?:ideas have i (?:had|got|told you|saved|given you)|are my ideas|ideas do i have)"
        r"|(?:read|show|tell|give) me (?:all )?my ideas|(?:list )?my ideas|what were my ideas)(?P<kept_idea>)\s*\??$"
        r"|^what (?:do i want|did i say i wanted?|have i said i want(?:ed)?|was i wanting) to learn(?P<kept_learn>)\s*\??$"
        r"|^(?:what (?:are|were) my (?:goals|resolutions|new year'?s resolutions)(?: (?:this|for this) year)?"
        r"|(?:read|tell|remind) me (?:of )?my (?:goals|resolutions))(?P<kept_goal>)\s*\??$"
        r"|^(?:what (?:am|have) i (?:been )?(?:grateful|thankful) for|(?:read|show|tell) me (?:what i'?m grateful for|my gratitude(?: list| journal)?))(?P<kept_thanks>)\s*\??$"
        r"|^(?:(?:read|show|tell) me (?:what'?s in )?my (?:journal|diary)|what(?:'s| is) in my (?:journal|diary)"
        r"|what did i (?:write|put|say) in my (?:journal|diary)"
        # "how have I been feeling lately" (2026-10-08): his moods are journal lines
        r"|how (?:have i been|was i|am i) feeling(?: lately| recently)?|what(?:'s| was| is|s) my mood(?: lately| recently)?"
        r"|how(?:'s| has) my mood been(?: lately| recently)?)(?P<kept_when> today| yesterday| this week)?(?P<kept_journal>)\s*\??$")),
    ("gift_for", re.compile(
        r"^what (?:gift ideas|gifts|presents|present ideas) (?:do i have|have i (?:got|saved|kept)|did i (?:save|have)) for (?P<gift_for>(?:my )?[a-z][a-z' ]{1,25}?)\s*\??$"
        r"|^what(?:'s| is|s) on (?:(?P<gift_for3>(?:my )?[a-z][a-z ]{1,25}?)'s gift (?:list|ideas)|my gift (?:list|ideas) for (?P<gift_for4>(?:my )?[a-z][a-z' ]{1,25}?))\s*\??$"
        r"|^what (?:should|could|can) i (?:get|buy|give) (?P<gift_for2>(?:my )?[a-z][a-z' ]{1,25}?)(?: for (?:(?:her|his|their) )?(?:birthday|christmas|the holidays|our anniversary))?\s*\??$"
        # "Gift ideas for my dad" (2026-10-08: to the planner).
        r"|^(?:any )?(?:gift|present) ideas? for (?P<gift_for5>(?:my )?[a-z][a-z' ]{1,25}?)\s*\??$")),
    ("fact_any", re.compile(r"^what(?:'s| is|s| are) (?P<fact_whose>my|our|the) (?!(?:busiest|quietest|least busy|freest) day\b)(?!.* (?:about|for|at|on|with|in|like|from|to)\s*\??$)(?P<fact_any>[a-z][a-z0-9' ]{1,30}?)\s*\??$")),
    # LAST, so every specific door wins: "when does the trash go out",
    # "when is soccer", "when is the babysitter coming" read the note he
    # made saying so (2026-10-07: all to a model). None when no note does.
    # "How long is my meeting with Sam", "who is my meeting with at 3",
    # "what's my busiest day this week" (2026-10-07: all to a model).
    # "How much have I saved", "how much more do I need to save" (2026-10-07: to a model).
    ("saved", re.compile(
        r"^how much (?:money )?(?:have i|did i) (?:saved?|put away|set aside)(?P<saved_w> so far| this week| this month| in total| total)?\s*\??$"
        r"|^how much (?P<saved_more>more )?(?:do i|will i) (?:still )?(?:need|have) to save\s*\??$"
        r"|^how (?P<saved_close>close|far) am i (?:from|to) (?:my |the )?(?:savings )?goal\s*\??$"
        r"|^how much is left to save\s*\??$"
        # "How much do I need to save each week" (2026-10-08: to a model,
        # with the goal and its date in his notes).
        r"|^how much (?:do|should|will) i (?:need to |have to |got to |gotta )?(?:save|put away|set aside)"
        r" (?:each|a|per|every) (?P<saved_per>day|week|month)(?: to (?:reach|hit|make) (?:my|the) goal)?\s*\??$")),
    # "When should I water the plants next" (2026-10-07: to a model, with a
    # reminder to water them every 3 days on file).
    ("next_due", re.compile(
        r"^when (?:should|do|will|must) i (?:next )?(?P<next_due>(?!be\b|get\b|go\b|leave\b)[a-z][a-z' ]{2,40}?)(?: next| again)\s*\??$"
        r"|^when (?:should|do|will|must) i next (?P<next_due2>(?!be\b|get\b|go\b|leave\b)[a-z][a-z' ]{2,40}?)\s*\??$")),
    # "Did I miss any reminders" (2026-10-07: to the planner).
    ("missed_reminders", re.compile(
        r"^(?:did i miss|have i missed|did i skip) (?:any )?reminders?(?: today)?\s*\??$"
        r"|^(?:any|are there any|were there any) (?:missed|unseen|unread) reminders?(?: today)?\s*\??$"
        r"|^(?:any|are there any|were there any) reminders? (?:that )?i (?:missed|haven'?t seen|didn'?t see)\s*\??$")),
    ("event_detail", re.compile(
        r"^how long (?:is|will be) (?:my|the) (?:next )?(?P<ed_long>(?:[a-z]+ )?(?:meeting|call|appointment|appt|interview|class|session|lunch|dinner)"
        r"(?: with [a-z][a-z' ]{1,25}?)?)(?: today| tomorrow)?\s*\??$"
        # "Where am I having lunch Friday", "where is lunch with Dana"
        # (2026-10-08: to a model, and to a FILE search).
        r"|^where(?:'s| is| am i having| am i meeting| are we having| are we meeting| do i have) (?:my |the |our )?"
        r"(?P<ed_where>(?:[a-z]+ )?(?:meeting|call|appointment|appt|interview|class|session|lunch|dinner|breakfast|brunch|coffee"
        r"|drinks|party)(?: with [a-z][a-z' ]{1,25}?)?)(?: (?:on )?(?P<ed_where_day>today|tonight|tomorrow|monday|tuesday|wednesday"
        r"|thursday|friday|saturday|sunday))?\s*\??$"
        r"|^who(?:'s| is) my (?:meeting|call|appointment|lunch|dinner) (?:with )?(?:at|for) (?P<ed_at>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)(?: (?P<ed_day>today|tomorrow))?\s*\??$"
        r"|^(?:what(?:'s| is)|which (?:day|is)) my (?P<ed_busy>busiest|quietest|least busy|freest) day(?: (?:this|next) week)?\s*\??$"
        # "What's after my 2pm", "what do I have after 3" (2026-10-07: to a model).
        r"|^what(?:'s| is| do i have| have i got)(?: on)? after (?:my |the )?(?P<ed_after>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)"
        r"(?: (?:meeting|call|appointment|one))?(?: (?P<ed_after_day>today|tomorrow))?\s*\??$"
        # "What does Leo have this week" (2026-10-07: to a model, a turn
        # after "Leo has a dentist appointment Monday at 4").
        # "What's Leo doing Thursday", "does Leo have anything Thursday"
        # (2026-10-08: to a model, and to the money ledger).
        r"|^(?:what (?:does|do)|what(?:'s| is)|does) (?!(?:i|we|you|it|that|this|he|she|they|the|a)\b)(?P<ed_who>(?:my |our )?[a-z][a-z']{1,20})"
        r" (?:have(?: going on| on| coming up| anything(?: on| going on)?)?|doing|up to)"
        r"(?: (?:on )?(?P<ed_who_when>today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?\s*\??$")),
    # "When do I have class", "when does my daughter have practice" a turn
    # after "...every Tuesday and Thursday at 5" (2026-10-08: to a model).
    # "When are the dog's shots due" (2026-10-08: "nothing on file", with
    # "my dog is due for shots in November" kept): the note, said back.
    # "What deliveries am I expecting" a turn after "my Amazon order is
    # arriving tomorrow" (2026-10-08: "I can't think").
    ("deliveries", re.compile(
        r"^(?:what (?P<deliveries>deliveries|packages|orders|parcels|shipments) (?:am i|are we) (?:expecting|waiting (?:on|for))"
        r"|(?:am i|are we) expecting (?:any )?(?P<deliveries2>deliveries|packages|orders|parcels|a package|a delivery)"
        r"|(?:any|are there any) (?P<deliveries3>deliveries|packages|parcels) (?:coming|arriving|due)(?: today| tomorrow| this week)?)\s*\??$")),
    ("pet_due", re.compile(
        r"^when (?:is|are|does|do) (?:the|my|our) (?P<pet_due>(?:dog|cat|puppy|kitten|pet)(?:'?s)? [a-z ]{3,25}?)"
        r" (?:due|need(?: to be done)?)\s*\??$")),
    ("when_have", re.compile(
        r"^(?:when|what days?|what time) (?:do|does) (?P<when_have>(?:i|we|my [a-z]+|the kids|[a-z]{2,15}) have"
        r" (?!(?:time|to|a meeting|meetings|plans|anything|something)\b)[a-z][a-z' ]{1,20}?)\s*\??$")),
    ("when_note", re.compile(
        r"^(?:when|what day|what time) (?:is|does|do|are) (?:the |my |our )?(?!(?:it|that|this|they|them|he|she|we|you|i)\b)"
        # the calendar's own words belong to the calendar's readers
        r"(?!(?:meetings?|calls?|appointments?|events?|calendar|schedule)\b)(?!.* (?:today|tomorrow|tonight|this week)\s*\??$)"
        r"(?P<when_note>[a-z][a-z' ]{1,25}?)"
        r"(?: go out| come| happen| start| get picked up| picked up| collected| coming| coming over| arriving| here| day)?\s*\??$")),
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
    # "Am I on call this weekend", "am I on a diet" (2026-10-08: to a
    # model, after he said so) is what he told her about it.
    m = re.fullmatch(r"(?:am i|was i) (?:on|doing) (?:a |an |the )?(?P<state>diet|keto|cleanse|fast|call|antibiotics|medication|meds"
                     r"|vacation|leave|parental leave|break)(?: (?:this|next) (?:week|weekend|month)| right now| now| still| today)?\s*\??", text)
    if m:
        return f"what did i tell you about being on {m.group('state')}"
    # "When is trash day" with a weekly trash reminder set (2026-10-08: to a
    # model). Only when one reminder names it; otherwise the question goes on
    # as it was, so this can only add an answer.
    m = re.fullmatch(r"(?:when|what day)(?:'s| is) (?:the |my )?(?P<what>trash|garbage|recycling|bins?|yard waste|compost)"
                     r" (?:day|pickup|pick up|collection)\s*\??", text)
    if m:
        try:
            from aletheia import intercom
            if intercom._one_reminder(m.group("what"))[0] is not None:
                return f"what time is my {m.group('what')} reminder"
        except Exception:
            pass
    # "What are the kids doing Saturday" (2026-10-08: to a model, with "the
    # kids have soccer at 5 on Saturday" in his notes): the day's reader
    # says the calendar and the notes for it.
    m = re.fullmatch(r"what (?:are|is) (?:the kids|my kids|our kids|my son|my daughter|[a-z]{2,15}) doing"
                     r" (?:on |this |next )?(?P<day>today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??", text)
    if m and not re.match(r"what (?:are|is|do|does) (?:you|u|i|we|they|it)\b", text):
        return f"what's on {m.group('day')}"
    # "Who am I having lunch with on Friday" (2026-10-08: to a model, with
    # "lunch with Mike" on Friday's calendar): the day's reader names them.
    m = re.fullmatch(r"who (?:am i|are we) (?:having (?:lunch|dinner|breakfast|coffee|drinks) with|meeting(?: with)?|seeing|seeing for (?:lunch|dinner))"
                     r" (?:on |this |next )?(?P<day>today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??", text)
    if m:
        return f"what's on {m.group('day')}"
    # "What's on next Tuesday" (2026-10-08: to a model, a turn after "a
    # dentist appointment next Tuesday" was put on the coming Tuesday): the
    # same day the hold was put on, asked the way the agenda reads it.
    m = re.fullmatch(r"(?P<head>what(?:'s| is|s)? on(?: my calendar| my schedule)?(?: for)?|what do i have(?: on)?|what have i got(?: on)?)"
                     r" (?:this|next|this coming|the coming) (?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??", text)
    if m:
        return f"what's on {m.group('day')}"
    # "Can you check if I have anything tomorrow" (2026-10-08: to the
    # planner) is the question itself.
    m = re.fullmatch(r"(?:can|could|would) (?:you|u) (?:please )?(?:check|see|look|find out|tell me) (?:if|whether) "
                     r"(?P<q>(?:i|we) (?:have|am|'m|are|need|owe)|there(?:'s| is| are)|my [a-z ]{1,30}? (?:is|are)) (?P<rest>.{2,80}?)\s*\??", text)
    if m:
        q = m.group("q")
        lead = {"i have": "do i have", "we have": "do we have", "i am": "am i", "i'm": "am i", "we are": "are we",
                "i need": "do i need", "i owe": "do i owe", "there's": "is there", "there is": "is there",
                "there are": "are there"}.get(q)
        if lead is None and q.startswith("my "):
            verb = q.rsplit(" ", 1)[1]
            lead = f"{verb} {q[:-len(verb)].strip()}"
        if lead:
            return f"{lead} {m.group('rest')}"
    # "Is there anything on my calendar today" (2026-10-08: answered "Yes"
    # with a description of her calendar code, read as "can she").
    m = re.fullmatch(r"(?:is there |do i have |have i got |have we got |do we have )?anything (?:on|in) (?:my|the|our) (?:calendar|schedule|diary|agenda)"
                     r"(?: (?:for )?(?P<day>today|tomorrow|tonight|this week|next week|this weekend|monday|tuesday|wednesday|thursday"
                     r"|friday|saturday|sunday))?\s*\??", text)
    if m:
        return f"what's on my calendar {m.group('day')}" if m.group("day") else "what's coming up"
    # "How many shopping days until Christmas", "how many sleeps until my
    # birthday" (2026-10-08: to a model) - the same count.
    m = re.fullmatch(r"how many (?:shopping |more |working |school )?(?:days|sleeps) (?:left )?(?:until|till|til|before|to) (?P<what>.{2,40}?)\s*\??", text)
    if m and re.match(r"how many (?:shopping|more|sleeps|days left)", text):
        return f"how many days until {m.group('what')}"
    # "What time will it be in Tokyo when it's 9am here" (2026-10-08: to a
    # model) - the conversion, asked the long way round.
    m = re.fullmatch(r"what time (?:will it be|is it|would it be) (?:in|for) (?P<place>[a-z][a-z .'-]{1,30}?) "
                     r"(?:when|if) (?:it'?s|it is) (?P<t>\d{1,2}(?::\d\d)? ?(?:am|pm)?)(?: here| (?:my|your) time| for me)?\s*\??", text) \
        or re.fullmatch(r"(?:if|when) (?:it'?s|it is) (?P<t>\d{1,2}(?::\d\d)? ?(?:am|pm)?)(?: here| (?:my|your) time| for me)?,? "
                        r"what time (?:is it|will it be|would it be) (?:in|for) (?P<place>[a-z][a-z .'-]{1,30}?)\s*\??", text)
    if m:
        return f"convert {m.group('t').replace(' ', '')} to {m.group('place')} time"
    # "Is my prescription picked up" (2026-10-08: read as a repository
    # called "prescription picked", and answered about the fleet pulse).
    m = re.fullmatch(r"(?:is|are|has|have) (?P<w>my|our|the) (?P<o>[a-z][a-z' ]{1,40}?) (?:been )?"
                     r"(?P<v>picked up|dropped off|paid|returned|mailed|renewed|walked|fed|watered|taken out|changed|washed|cleaned)(?: yet| today)?\s*\??", text)
    if m:
        base = {"picked up": "pick up", "dropped off": "drop off", "paid": "pay", "returned": "return", "mailed": "mail",
                "renewed": "renew", "walked": "walk", "fed": "feed", "watered": "water", "taken out": "take out",
                "changed": "change", "washed": "wash", "cleaned": "clean"}[m.group("v")]
        return f"did i {base} {m.group('w')} {m.group('o')}" + (" today" if text.rstrip(" ?").endswith("today") else "")
    # "How long until I start my new job" (2026-10-08: to a model) is "how
    # long until my new job starts", which reads his note.
    m = re.fullmatch(r"how (?P<how>long|many days|many weeks) (?:is it )?(?:until|till|til|before) i start (?:my |the )?(?P<what>new job|job|school|college|classes)\s*\??", text)
    if m:
        what = "new job" if m.group("what") in ("new job", "job") else m.group("what")
        return f"how {m.group('how')} until my {what} starts" if what == "new job" else f"how {m.group('how')} until {what} starts"
    # "Did I take the trash out" (2026-10-08: to the planner, one turn after
    # "I took the trash out") is "did I take out the trash".
    m = re.fullmatch(r"(?P<q>did i|have i|when did i(?: last)?) (?:take|taken|put) (?P<o>(?:the |my )?(?:trash|garbage|rubbish"
                     r"|recycling|bins?|trash cans?|garbage cans?|compost))(?: out)(?P<t> today| yet| this morning)?\s*\??", text)
    if m:
        return f"{m.group('q')} take out {m.group('o')}{m.group('t') or ''}"
    # "How long ago did I water the plants" (2026-10-08: to a model) is
    # "how long since I watered the plants".
    m = re.fullmatch(r"how long ago did i (?:last )?(?P<rest>[a-z][a-z' ]{2,50}?)\s*\??", text)
    if m and (match(f"how long since i {m.group('rest')}") or ("", ""))[0] == "did_last":
        return f"how long since i {m.group('rest')}"
    # "What's the plan for tomorrow" (2026-10-08: to a model): the day.
    m = re.fullmatch(r"what(?:'s| is) (?:the|my|our) (?:plan|schedule|agenda|game plan)(?: for)? (?P<day>today|tomorrow|tonight)\s*\??", text)
    if m:
        return f"what do i have to do {m.group('day')}"
    # "What expires soon" (2026-10-08: to a model, with "my license expires
    # on November 5" kept): the dates he told her, the way "what's due next
    # month" already reads them.
    if re.fullmatch(r"(?:what(?:'s| is)? (?:expiring|up for renewal|due for renewal|running out)|what (?:expires|needs renewing|needs to be renewed)"
                    r"|(?:is |does )?anything (?:expiring|expire|need renewing|due for renewal))(?: soon| this month| next month)?\s*\??", text):
        return "what's due next month"
    # "What hotel am I staying at" a turn after "my hotel is the Hilton"
    # (2026-10-08: to a model): the fact he gave, asked by its own name.
    m = re.fullmatch(r"(?:what|which|where(?:'s| is)?) (?P<what>hotel|airbnb|campsite|cabin)(?: am i| are we| is it)?"
                     r"(?: staying(?: at| in)?| booked| at)?\s*\??", text) \
        or re.fullmatch(r"where (?:am i|are we) staying(?: in [a-z][a-z .'-]{1,30}?| tonight| there)?\s*\??", text)
    if m:
        what = m.groupdict().get("what") or "hotel"
        if _fact_any(what):
            return f"what's my {what}"
    # "How long has it been since my last haircut" (2026-10-08: to a model,
    # with "I got a haircut" kept): the "when did I last" reader says when.
    m = re.fullmatch(r"how long (?:has it been |is it )?since (?:my last (?P<noun>haircut|oil change|massage|manicure|pedicure"
                     r"|flu shot|checkup|check-up|physical|eye exam|car wash)|i last (?P<verb>[a-z][a-z ']{2,30}?))\s*\??", text)
    if m and m.group("noun"):
        noun = m.group("noun")
        return f"when did i last get {'an' if noun[0] in 'aeiou' else 'a'} {noun}"
    if m:
        first, _, after = m.group("verb").partition(" ")
        present = {"went": "go", "called": "call", "talked": "talk", "saw": "see", "visited": "visit", "ate": "eat",
                   "ran": "run", "worked": "work", "cleaned": "clean", "washed": "wash", "fed": "feed", "walked": "walk",
                   "texted": "text", "mowed": "mow", "watered": "water", "did": "do", "had": "have", "got": "get",
                   "took": "take", "changed": "change", "vacuumed": "vacuum"}.get(first)
        if present:
            return f"when did i last {present} {after}".strip()
    # "Do you remember what I told you yesterday" (2026-10-08: "nothing on
    # file about what i told you yesterday"): the day's reader.
    m = re.fullmatch(r"(?:do|did) (?:you|u) remember what i (?:told|said to|tell) (?:you|u)"
                     r" (?P<when>yesterday|today|this morning|last night|earlier|earlier today)\s*\??", text)
    if m:
        return f"what did i tell you {m.group('when')}"
    # "What should I eat" (2026-10-08: "I can't think just now"): the meal
    # it is time for, asked the way the meal-idea reader already answers.
    if re.fullmatch(r"what (?:should|can|could|shall) (?:i|we) (?:eat|have to eat|make to eat)(?: (?:now|today|right now))?\s*\??", text) \
            or re.fullmatch(r"(?:i'?m|i am) hungry,? what should i eat\s*\??", text):
        import datetime as dt
        from aletheia import localtime
        hour = dt.datetime.now(localtime.operator_tz()).hour
        return "what should i make for " + ("breakfast" if 4 <= hour < 11 else "lunch" if hour < 15 else "dinner")
    # "What's for dinner tonight" (2026-10-08: to a model): tonight's plan
    # when there is one, otherwise the same idea "what should I make" gets.
    m = re.fullmatch(r"what(?:'s| is|s) for (?P<meal>dinner|supper|lunch)(?: tonight| today)?\s*\??", text)
    if m:
        try:
            planned = _planned_for("tonight" if m.group("meal") != "lunch" else "today")
        except Exception:
            planned = None
        return f"what am i making for {m.group('meal')}" if planned else f"what should i make for {m.group('meal')}"
    # "How often do you remind me to stretch" (2026-10-08: to the planner).
    m = re.fullmatch(r"how often (?:do|will|are) (?:you|u) (?:remind(?:ing)?|going to remind) me (?:to |about )?(?P<what>.+?)\s*\??", text)
    if m:
        return f"what time is my {m.group('what')} reminder"
    # "Am I done for the day" (2026-10-08: to the planner) is what's still due.
    if re.fullmatch(r"(?:am i|are we) (?:all )?(?:done|finished|through) (?:for (?:the day|today|tonight)|with (?:my list|everything|today|the day))"
                    r"(?: yet)?\s*\??|is there anything (?:else )?(?:left|due) (?:for )?today\s*\??", text):
        return "what's due today"
    # "What's left for Saturday" (2026-10-08: to a model) is what is due then.
    m = re.fullmatch(r"what(?:'s| is|s) (?:left|still to do|still on my list|left to do) (?:for|on) "
                     r"(?P<day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??", text)
    if m:
        return f"what's due {m.group('day')}"
    # "How is my weight loss going" read the FLEET's status (2026-10-08).
    m = re.fullmatch(r"how(?:'s| is|s) (?:my |the )?(?:weight loss|weight|diet)(?: going| coming along| doing)?\s*\??", text)
    if m:
        return "how am i doing on my weight loss"
    # "When does my car need an oil change" (2026-10-08: to a model) is the
    # note he gave her about it.
    m = re.fullmatch(r"when (?:does|do|will) (?:my|our|the) (?P<thing>car|truck|van|suv|bike|motorcycle|furnace|ac|water heater"
                     r"|lawn mower|mower) need (?:an? |its |new )?(?P<what>[a-z ]{3,40}?)\s*\??", text)
    if m:
        return f"what did i tell you about {m.group('what')}"
    # "What size shoes does Emma wear" (2026-10-08: to a model, a turn
    # after "Emma's shoe size is 2") is her shoe size.
    m = re.fullmatch(r"what size (?P<what>shoe|shirt|pants|dress|ring|jacket|coat|diaper|clothes)s? (?:does|do) (?P<who>(?!i\b|you\b|we\b)[a-z]{2,15}|my [a-z]{2,15})"
                     r" (?:wear|take|have|need)\s*\??", text)
    if m:
        who = m.group("who")
        return f"what is {who}'s {m.group('what')} size"
    # "Did anyone feed the cat" (2026-10-08: to a model, a turn after "I
    # fed the cat"): what she knows is what he told her he did.
    m = re.fullmatch(r"(?:did|has) (?:anyone|anybody|someone|somebody|we) (?P<rest>(?:feed|fed|walk|walked|water|watered|take out|taken out"
                     r"|took out|let out|lock|locked|pay|paid|give|given|gave|change|changed|empty|emptied|clean|cleaned) .{2,40}?)(?: yet| today)?\s*\??", text)
    if m:
        base = {"fed": "feed", "walked": "walk", "watered": "water", "taken out": "take out", "took out": "take out",
                "locked": "lock", "paid": "pay", "given": "give", "gave": "give", "changed": "change", "emptied": "empty",
                "cleaned": "clean"}
        verb, _, obj = m.group("rest").partition(" ")
        two = re.match(r"(taken out|took out|take out|let out) (.+)", m.group("rest"))
        if two:
            verb, obj = two.group(1), two.group(2)
        return f"did i {base.get(verb, verb)} {obj}"
    # "How am I doing on my reading goal" (2026-10-08: to a model) is the
    # book count this year, which says the goal beside it.
    if re.fullmatch(r"(?:how (?:am i doing|am i tracking|close am i|far along am i) (?:on|with|to|toward|towards)|am i on track (?:with|for))"
                    r" my (?:reading|book|books) goal\s*\??", text):
        return "how many books have i read this year"
    # "Is the electric bill paid" (2026-10-08: to the planner, a turn after
    # "I paid the electric bill") is "did I pay the electric bill".
    m = re.fullmatch(r"(?:is|has) (?P<what>(?:the |my )?(?:[a-z][a-z ]{0,30}? )?(?:bill|rent|mortgage|payment|insurance|tuition|loan|fee|fees|tax|taxes))"
                     r" (?:been )?paid(?P<tail> yet| this month)?\s*\??", text)
    if m:
        return f"did i pay {m.group('what')}{m.group('tail') or ''}"
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
        # "What's my cat's name" read back every note about the cat
        # (2026-10-08: "...and you told me: you fed the cat"). What he asked
        # for travels with it.
        if name == "recall" and captured.get("recall2") and captured.get("recall_attr"):
            return name, f"{captured['recall2']}|{captured['recall_attr']}"
        if name in ("math", "farewell", "power", "fact_q", "note_search", "sun", "moon", "discount", "split",
                    "area", "year_left", "weekday_of", "days_between", "time_diff", "feeling", "about_her", "arith",
                    "prime", "average", "round_to", "time_units", "fraction_pct", "weather_more", "free_at", "reckon",
                    "weather_in"):
            return name, text
        if name in ("owed", "fact_any", "counted", "ate", "dur_convert", "how_to", "life_news", "lent", "liked_how", "went", "did_count", "cost_mine", "work_hours", "off_lists", "body", "meds", "took_today", "their_fact", "when_note", "plural", "kept", "gift_for", "meal_plan", "pick_for_me", "worked", "sums_more", "life_when", "agenda_part", "event_detail", "missed_reminders", "parked", "saved", "next_due", "holiday_year", "dislikes", "married", "next_meeting", "promised", "capital", "bedtime_calc", "cook_temp", "shop_added", "opinion", "woke_usual", "reading", "awake_for", "no_password", "arrived", "the_list", "tasks_verb", "role_said", "loan_left", "job_since", "their_likes", "told_last", "date_what", "where_was_i", "on_days", "until_leave", "just_added", "their_kind", "miles_until", "pills_left", "time_where", "trip_length", "starts_when", "it_due", "their_person", "birthday", "habit", "days_off", "focus"):
            return name, text
        if name in ("until_weeks", "days_left", "age_in", "race", "logged", "rps", "arith_more", "fractions", "did_last", "tip", "currency", "date_after", "next_detail", "day_span", "on_the_last",
                    "time_convert", "pct_of", "fraction_dec", "roman", "height_cm", "asked_last", "how_many_has"):
            return name, text
        rest = next((captured[k] for k in ("what", "what2", "what3", "what4", "what5", "what6", "mine",
                                           "free", "free2", "free3",
                                           "down", "down2", "weather",
                                           "weather2", "weather3", "weather4", "weather5", "weather6", "weather7", "weather8", "weather9", "weather10", "weather11",
                                           "day", "day2", "day3", "day4", "day5", "day6", "day7", "day13",
                                           "outcome", "outcome2", "outcome3", "outcome4", "outcome5", "outcome6",
                                           "until", "until2", "day8", "day9", "day10", "day11", "weeks", "due", "due2", "due3", "due4", "due5", "due6", "syn", "syn2", "ant",
                                           "cal", "cal2", "cal3", "cal4", "cal5", "cal6", "cal7", "cal8", "born_q", "born_q2", "born_q3", "born_q4", "day12", "holiday_on", "holiday_month", "holiday_list", "holiday_list2", "place_w", "place_w2", "place_a", "did_v", "did_o", "did_v2", "did_o2", "did_today", "wkday", "bwin", "bwin2", "bwin3", "bday", "meal", "meal2", "meal3", "woke", "const", "date_of4", "due", "due2", "due3", "workdays", "agenda_on", "since", "since2", "born", "age_of", "took", "took2",
                                           "why_not", "why_not2", "why_not3",
                                           "sent_window", "sent_window2",
                                           "repo_wrong", "repo_wrong2", "time_in", "time_in2",
                                           "time_in3", "time_in4", "time_in5", "time_in6", "time_in7", "date_of", "date_of2", "date_of3",
                                           "recall", "recall2", "recall3", "recall4", "recall5", "recall6", "recall7", "recall8", "recall9", "recall10", "recall11", "recall12", "recall13", "recall14", "owe_who", "owe_amt", "define", "define2", "need_q", "who_named", "who_named2", "coming", "coming2", "coming3", "coming4", "coming5", "meetings_week", "when_do_i", "when_meeting", "when_meeting2", "when_mine2", "clock_until", "notes_day", "notes_day2", "when_mine", "reminders_on", "reminders_on2", "reminders_on3", "ran",
                                           "has", "has2",
                                           "date_ahead", "date_ahead2", "date_ahead3", "date_ahead4", "found_window",
                                           "hold_q", "hold_q2", "hold_q3", "hold_q4",
                                           "draft_to", "draft_to2", "draft_to3",
                                           "applied_on", "applied_on2", "applied_on3", "what3", "what7", "lastday", "lastday2", "lastday3",
                                           "told_on", "episode_on", "episode_on2", "rated", "who_called", "news_when", "task_about", "task_about2", "plans_for", "plans_for2", "broken2", "to_bring", "event_who", "event_who2", "still_valid", "still_valid2", "who_lives", "can_eat", "repeating", "repeating2", "who_said", "lift_max", "lift_max2", "sick_since", "born_age", "born_age2", "when_have", "pet_due", "shop_qty", "who_coming_noted", "do_i_work", "task_age", "how_did_i_do", "do_i_have", "left_on", "how_long_out", "asked_on", "asked_on2", "asked_on3", "asked_on4", "asked_on5", "day_part", "day_part2",
                                           "place", "place2", "place3", "when_with", "until_mine", "reminder_when", "did_finish",
                                           "who_coming")
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
               "independence day": (7, 4),
               # "What holidays are in November" left out Veterans Day (2026-10-07).
               "veterans day": (11, 11), "veterans' day": (11, 11), "veteran's day": (11, 11),
               "juneteenth": (6, 19), "st patrick's day": (3, 17), "saint patrick's day": (3, 17),
               "st. patrick's day": (3, 17), "st patricks day": (3, 17)}
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")


OFF_SWITCH = ("Say \"stop\" or \"halt\" and nothing I do runs until you say \"resume\". "
              "\"Announcements off\" keeps me from speaking up on my own, and \"turn off the microphone\" stops me listening.")


_HOLIDAY_NAMES = ("New Year's Day", "MLK Day", "Presidents' Day", "Valentine's Day", "Easter", "Mother's Day",
                  "Memorial Day", "Father's Day", "Independence Day", "Labor Day", "Columbus Day", "Halloween",
                  "Thanksgiving", "Christmas Eve", "Christmas", "New Year's Eve", "Veterans Day", "Juneteenth",
                  "St Patrick's Day")


_COUNT_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "half a": 0.5}


_OFF_KIND = {"pto": "vacation", "holiday": "vacation", "leave": "vacation", "time off": "vacation"}


def _days_off(text: str) -> str | None:
    """His days off left: the newest balance he told her, less the days he
    said he took since. Nothing told is said, not guessed."""
    import datetime as dt
    from aletheia import speech
    g = _groups("days_off", text)
    kind = g.get("off_kind") or g.get("off_kind2") or "vacation"
    kind = _OFF_KIND.get(kind, kind)
    used_q = re.search(r"\b(?:used|taken|did i take)\b", _tidy(text))
    num = r"(\d{1,3}(?:\.5)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|half a)"
    names = {"vacation": r"(?:vacation|pto|holiday|leave)", "sick": r"sick", "personal": r"personal"}[kind] \
        if kind in ("vacation", "sick", "personal") else re.escape(kind)
    have = re.compile(rf"i (?:have|'ve got|have got|got|still have) {num} (?:more )?{names} days?(?: left| remaining)?", re.I)
    took = re.compile(rf"i (?:took|used|am taking|'m taking|take) {num} {names} days?"
                      + (r"|i took (?:today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|the day) off" if kind == "vacation" else ""),
                      re.I)
    amount = lambda w: _COUNT_WORDS.get(w.casefold()) if not w[0].isdigit() else float(w)
    taken, balance, when = 0.0, None, ""
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).rstrip(".")
        said = re.sub(r" (?:today|yesterday|this week|last week|this year|on [a-z]+day)$", "", said, flags=re.I)
        m = have.fullmatch(said) if not used_q else None
        if m:
            balance, when = amount(m.group(1)), str(row.get("ts") or "")
            break
        m = took.fullmatch(said)
        if m:
            taken += amount(m.group(1)) if m.group(1) else 1
    plain = lambda n: str(int(n)) if float(n).is_integer() else str(n)
    if used_q:
        if not taken:
            return f"You haven't told me you've taken any {kind} days."
        return f"{plain(taken)} {kind} day{'s' if taken != 1 else ''}, from what you've told me."
    if balance is None:
        return (f"You haven't told me how many {kind} days you have. Say \"I have 10 {kind} days left\" and I'll count "
                "them down as you take them.")
    left = max(0.0, balance - taken)
    since = speech.humanize_time(when) if when else ""
    since = ("on " + since) if since[:1].isdigit() else since
    if not taken:
        return f"{plain(left)} {kind} day{'s' if left != 1 else ''} left, you told me {since}.".replace(" ,", ",")
    return (f"{plain(left)} {kind} day{'s' if left != 1 else ''} left - you had {plain(balance)} {since} "
            f"and you've taken {plain(taken)} since.")


def _logged(text: str) -> str | None:
    """What he told her he drank, ran, slept or did, added up from his notes."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("logged", text)
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    window = (g.get("logged_w") or g.get("logged_w2") or g.get("logged_w3") or g.get("logged_w4") or g.get("logged_w5")
              or g.get("logged_w6") or g.get("logged_w7")
              or (" this week" if g.get("logged_dur") else " today")).strip()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "this week":
        start -= dt.timedelta(days=now.weekday())
    elif window == "this month":
        # "How far have I run this month" (2026-10-08: to a model)
        start = start.replace(day=1)
    rows = []
    for row in _notes():
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        said = " ".join(str(row.get("text") or "").casefold().split())
        # "I ran 5 miles yesterday" was said today about yesterday (2026-10-08).
        if said.endswith(" yesterday"):
            at -= dt.timedelta(days=1)
        rows.append((at, said))
    when = window if window in ("today", "this month") else "this week"

    def amount(word):
        return float(word) if re.fullmatch(r"\d+(?:\.\d+)?", word) else _COUNT_WORDS.get(word)
    if g.get("logged_drink") or g.get("logged_drink2"):
        drink = g.get("logged_drink") or g["logged_drink2"]
        total, unit = 0.0, "glass"
        for at, said in rows:
            # "Log 8 glasses of water" is kept as "8 glasses of water" (2026-10-07: not counted).
            m = re.match(rf"(?:i (?:just )?(?:drank|had) )?(\w+) (glass(?:es)?|cups?|bottles?|mugs?|cans?) of {drink}\b", said)
            if m and at >= start and amount(m.group(1)):
                total += amount(m.group(1))
                unit = {"glasses": "glass"}.get(m.group(2), m.group(2) if m.group(2) == "glass" else m.group(2).rstrip("s"))
                continue
            # "I had a coffee", "I had coffee at 3", "I drank 2 beers"
            # (2026-10-07): one each, in the vessel it comes in.
            m = re.match(rf"i (?:just )?(?:drank|had|finished) (?:(an?|another|one|two|three|four|five|\d+|my \w+) )?{drink}s?\b", said)
            if m and at >= start:
                n = 1.0 if not m.group(1) or m.group(1) in ("a", "an", "another") or m.group(1).startswith("my ") else amount(m.group(1))
                if n:
                    total += n
                    unit = {"coffee": "cup", "tea": "cup", "latte": "cup", "espresso": "cup", "soda": "can",
                            "beer": "", "wine": "glass"}.get(drink, unit)
        if not total:
            # "Say 'I drank a glass of coffee'" (2026-10-07): a cup is what coffee comes in.
            vessel = {"coffee": "cup", "tea": "cup", "beer": "can", "soda": "can"}.get(drink, "glass")
            return f"You haven't told me about any {drink} {when}. Say \"I drank a {vessel} of {drink}\" and I'll keep count."
        if not unit:
            return f"{_plain(total)} {drink if total == 1 else drink + 's'} {when}."
        plural = {"glass": "glasses"}.get(unit, unit + "s")
        return f"{_plain(total)} {unit if total == 1 else plural} of {drink} {when}."
    if g.get("logged_med"):
        med = g["logged_med"]
        stem = med[:-1] if med in ("pills", "tablets", "painkillers") else med
        total, last, last_said = 0.0, None, ""
        for at, said in rows:
            m = re.match(rf"i (?:just )?(?:took|had|taken) (?:(an?|one|two|three|four|\d+) )?(?:\w+ )?{stem}s?\b", said)
            if m and at >= start:
                n = 1.0 if not m.group(1) or m.group(1) in ("a", "an") else amount(m.group(1))
                if n:
                    total += n
                    if last is None or at > last:
                        # "I took 2 advil at 3" said at 5:44 was "the last at
                        # 5:44 am" (2026-10-08): the time he said, when he said one.
                        told = re.search(r"\bat (\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)(?: today| this morning| this afternoon)?\s*$", said)
                        last, last_said = at, (f"at {told.group(1)}" if told else "")
        if not total:
            return f"You haven't told me about any {med} {when}."
        return (f"{_plain(total)} {med if med.endswith('s') else med} {when}, the last "
                f"{last_said or speech.humanize_time(last.isoformat()).replace('today ', '')}, from what you've told me.")
    if g.get("logged_longest"):
        kind = g["logged_longest"]
        verb = {"run": "ran", "walk": "walked", "hike": "hiked", "bike ride": "biked", "ride": "biked", "swim": "swam",
                "jog": "jogged"}[kind]
        best = None
        for at, said in rows:
            m = re.match(rf"i {verb} (\d+(?:\.\d+)?|\w+(?: a)?) ?(miles?|km|kilometers?|kilometres?|k)\b", said)
            if m and amount(m.group(1)):
                miles = amount(m.group(1)) / (1 if m.group(2).startswith("mile") else 1.609344)
                if best is None or miles > best[0]:
                    best = (miles, at)
        if best is None:
            return f"You haven't told me about a {kind} with a distance. Say \"I {verb} 3 miles\" and I'll keep it."
        return (f"{_plain(round(best[0], 2))} mile{'s' if round(best[0], 2) != 1 else ''}, "
                f"{speech.humanize_time(best[1].isoformat())}, from what you've told me.")
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
    if g.get("logged_dur"):
        # "Log 30 minutes of running", then "how much did I run this week"
        # (2026-10-07: to the planner). Minutes and miles, both as he said them.
        first = g["logged_dur"].split()[0]
        words = next((w for k, w in (
            ("r", r"ran|run|runs|running"), ("wa", r"walk|walked|walks|walking"), ("j", r"jog|jogged|jogging"),
            ("b", r"bike|biked|biking|bike ride|cycled|cycling|cycle"), ("c", r"bike|biked|biking|cycled|cycling|cycle"),
            ("s", r"swim|swam|swum|swimming"), ("h", r"hike|hiked|hiking"),
            ("e", r"exercise|exercised|exercising|worked out|workout|working out"),
            ("wo", r"worked out|work out|workout|working out|exercised")) if first.startswith(k)), None)
        if not words:
            return None
        noun = {"r": "running", "wa": "walking", "j": "jogging", "b": "biking", "c": "cycling", "s": "swimming",
                "h": "hiking", "e": "exercise", "wo": "working out"}[next(k for k in ("r", "wa", "j", "b", "c", "s", "h", "e", "wo")
                                                                           if first.startswith(k))]
        minutes, miles, seen = 0.0, 0.0, False
        for at, said in rows:
            if at < start or not re.search(rf"\b(?:{words})\b", said):
                continue
            t = re.search(r"\b(\d+(?:\.\d+)?|an?|one|two|half an?)[- ](minutes?|mins?|hours?|hrs?)\b", said)
            d = re.search(r"\b(\d+(?:\.\d+)?)[- ]?(miles?|km|kilometers?|kilometres?|k)\b", said)
            if t:
                n = {"a": 1, "an": 1, "one": 1, "two": 2, "half a": 0.5, "half an": 0.5}.get(t.group(1)) or float(t.group(1))
                minutes += n * (60 if t.group(2).startswith("h") else 1)
                seen = True
            if d:
                miles += float(d.group(1)) / (1 if d.group(2).startswith("mile") else 1.609344)
                seen = True
        example = {"running": "run", "walking": "walk", "jogging": "jog", "biking": "bike ride", "cycling": "bike ride",
                   "swimming": "swim", "hiking": "hike"}.get(noun, "workout")
        if not seen:
            return f"You haven't told me about any {noun} {when}. Say \"I went for a 30 minute {example}\" and I'll add it up."
        bits = []
        if minutes:
            h, mm = divmod(int(round(minutes)), 60)
            bits.append(" and ".join(x for x in (speech.count_phrase(h, "hour") if h else "",
                                                  speech.count_phrase(mm, "minute") if mm else "") if x))
        if miles:
            bits.append(f"{_plain(round(miles, 2))} mile{'s' if round(miles, 2) != 1 else ''}")
        said = " and ".join(bits)
        return f"{said[:1].upper() + said[1:]} {when}."
    if re.search(r"\b(?:average|usually|normally)\b", text.casefold()) and "sleep" in text.casefold():
        nights = {}
        for at, said in rows:
            m = re.match(r"i slept (?:for )?(\S+)( and a half)? hours?", said)
            if m and now - at <= dt.timedelta(days=30) and amount(m.group(1)) and at.date() not in nights:
                nights[at.date()] = amount(m.group(1)) + (0.5 if m.group(2) else 0)
        if not nights:
            return "You haven't told me how you've slept. Say \"I slept 7 hours\" in the morning and I'll keep the average."
        if len(nights) == 1:
            return f"You've told me about one night: {_plain(list(nights.values())[0])} hours."
        return (f"About {_plain(round(sum(nights.values()) / len(nights), 1))} hours a night, "
                f"over the {len(nights)} nights you've told me about this month.")
    if g.get("logged_sleep3") or g.get("logged_sleep4") or g.get("logged_sleep5"):
        monday = start - dt.timedelta(days=now.weekday())
        nights = {}
        for at, said in rows:
            m = re.match(r"i slept (?:for )?(\S+)( and a half)? hours?", said)
            if m and at >= monday and amount(m.group(1)) and at.date() not in nights:
                nights[at.date()] = amount(m.group(1)) + (0.5 if m.group(2) else 0)
        if not nights:
            return "You haven't told me how you slept this week. Say \"I slept 7 hours\" in the morning and I'll add it up."
        total = sum(nights.values())
        if len(nights) == 1:
            return f"You've told me about one night this week: {_plain(total)} hours."
        return (f"{_plain(round(total, 1))} hours over the {len(nights)} nights you told me about - "
                f"about {_plain(round(total / len(nights), 1))} a night.")
    if re.search(r"\benough\b|\bsleep(?:ing)? well\b", text.casefold()) and "how " not in text.casefold():
        # "Did I sleep enough": last night's hours against the usual
        # seven to nine, from his own words; nothing told, nothing judged.
        heard = _logged("how much did i sleep last night")
        hours = re.match(r"(?:About )?(\d+(?:\.\d+)?)(?: hours?| hour)?(?: and (\d+) minutes?)?", heard or "")
        if not hours:
            return heard
        h = float(hours.group(1)) + (int(hours.group(2)) / 60 if hours.group(2) else 0)
        verdict = ("Not quite - most adults need seven to nine hours." if h < 7
                   else "Yes - that's in the seven to nine hours most adults need." if h <= 9
                   else "Plenty - more than the seven to nine most adults need.")
        return f"{heard} {verdict}"
    if g.get("logged_sleep") or g.get("logged_sleep2") or g.get("logged_sleep6"):
        for at, said in rows:
            m = re.match(r"i slept (?:for )?(\S+)( and a half)? hours?", said)
            if m and amount(m.group(1)):
                hours = amount(m.group(1)) + (0.5 if m.group(2) else 0)
                return f"{_plain(hours)} hours, you told me {speech.humanize_time(at.isoformat())}."
        # "I went to bed at midnight" and "I woke up at 7" (2026-10-07): the
        # night between them, when both were told within the last day.
        woke = bed = None
        for at, said in rows:
            if now - at > dt.timedelta(hours=20):
                break
            m = re.match(r"i (?:woke up|got up) (?:at |around |about )?(\d{1,2})(?::(\d\d))? ?(am|pm|a\.m\.|p\.m\.)?", said)
            if m and woke is None:
                woke = (int(m.group(1)) % 12 + (12 if (m.group(3) or "").startswith("p") else 0), int(m.group(2) or 0))
            m = re.match(r"i (?:went to bed|went to sleep|fell asleep) (?:at |around |about )?(midnight|(\d{1,2})(?::(\d\d))? ?(am|pm|a\.m\.|p\.m\.)?)", said)
            if m and bed is None:
                if m.group(1) == "midnight":
                    bed = (0, 0)
                else:
                    h = int(m.group(2)) % 12
                    # a bare 11 is at night; a bare 1 is after midnight
                    pm = (m.group(4) or "").startswith("p") or (not m.group(4) and h >= 7)
                    bed = (h + (12 if pm else 0), int(m.group(3) or 0))
        if woke and bed:
            minutes = (woke[0] * 60 + woke[1] - bed[0] * 60 - bed[1]) % (24 * 60)
            if 0 < minutes <= 16 * 60:
                h, mm = divmod(minutes, 60)
                said = speech.count_phrase(h, "hour") + (f" and {speech.count_phrase(mm, 'minute')}" if mm else "")
                return f"About {said} - you told me when you went to bed and when you woke up."
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
    months = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
              "october", "november", "december")
    if which in months or which == "month":
        month = today.month if which == "month" else months.index(which) + 1
        said_month = months[month - 1].capitalize()
        inside = [(d, n) for d, n in dated if d.month == month and (d - today).days < 366]
        if not inside:
            return f"No holidays I know of in {said_month}."
        from aletheia import speech
        return f"In {said_month}: " + speech.and_list(
            [f"{n} on {d.strftime('%A')} {d.day}" for d, n in sorted(inside)]) + "."
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if which in ("today", "it", "tomorrow") or which in weekdays:
        if which in weekdays:
            # "Is Monday a holiday" (2026-10-07: to the planner): the coming one.
            day = today + dt.timedelta(days=(weekdays.index(which) - today.weekday()) % 7)
        else:
            day = today + dt.timedelta(days=1 if which == "tomorrow" else 0)
        on = [name for d, name in dated if d == day]
        said = "today" if day == today else "tomorrow" if day == today + dt.timedelta(days=1) else which.capitalize()
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
    # "How long until my lease is up" a turn after "my lease ends July 31"
    # (2026-10-08): the end said another way is still the end.
    w = re.sub(r" (?:is up|is over|runs out|expires|ends|is due|starts|begins)$", "", w)
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
        words_ = [x[:-1] if len(x) > 3 and x.endswith("e") else x
                  for x in re.findall(r"[a-z0-9]+", ask) if x not in ("s", "is", "the", "a")]
        for row in _notes():
            said = " ".join(str(row.get("text") or "").casefold().split())
            if not all(re.search(rf"\b{re.escape(x)}", said) for x in words_):
                continue
            m = re.search(date_re, said)
            if m:
                found = _named_date(re.sub(r"(?<=\d)(?:st|nd|rd|th)", "", m.group("d")).replace(" of ", " "), today)
                if found:
                    return found
            found = _relative_in_note(said, row.get("ts"), today)
            if found:
                return found
    return None


def _relative_in_note(said: str, ts, today):
    """"My parents are coming to visit next weekend": the day that names,
    counted from when he SAID it, and only while it is still ahead
    (2026-10-08: "how many days until my parents visit" went to a model)."""
    import datetime as dt
    from aletheia import localtime
    try:
        base = dt.datetime.fromisoformat(str(ts or "").replace("Z", "+00:00")).astimezone(localtime.operator_tz()).date()
    except ValueError:
        return None
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    m = re.search(r"\b(?:(?P<which>this|next) )?(?P<day>weekend|week|" + "|".join(days) + r")\b|\btomorrow\b|\bon the (?P<nth>\d{1,2})(?:st|nd|rd|th)\b"
                  r"|\bin (?P<n>\d{1,2}|a|two|three|four) (?P<unit>days?|weeks?)\b", said)
    if not m:
        return None
    if m.group(0) == "tomorrow":
        when = base + dt.timedelta(days=1)
    elif m.group("nth"):
        n = int(m.group("nth"))
        try:
            when = base.replace(day=n)
        except ValueError:
            return None
        if when < base:
            when = (when.replace(day=1) + dt.timedelta(days=32)).replace(day=n)
    elif m.group("n"):
        n = {"a": 1, "two": 2, "three": 3, "four": 4}.get(m.group("n")) or int(m.group("n"))
        when = base + dt.timedelta(days=n * (7 if m.group("unit").startswith("week") else 1))
    else:
        day, which = m.group("day"), m.group("which")
        monday_next = base + dt.timedelta(days=7 - base.weekday())
        if day == "week":
            if which != "next":
                return None
            when = monday_next
        elif day == "weekend":
            when = monday_next + dt.timedelta(days=5) if which == "next" else base + dt.timedelta(days=(5 - base.weekday()) % 7)
        else:
            ahead = (days.index(day) - base.weekday()) % 7 or 7
            when = base + dt.timedelta(days=ahead + (7 if which == "next" and ahead < 7 - base.weekday() else 0))
    return when if when >= today else None


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


def _trip_length(text: str) -> str | None:
    """"My vacation is December 10 to 17": seven nights, from his note.
    None without a note giving both ends."""
    import datetime as dt
    from aletheia import localtime
    what = (_groups("trip_length", text).get("tl_what") or "").casefold()
    months = "|".join(_MONTHS)
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        if not re.search(rf"\b{what}\b", said):
            continue
        m = re.search(rf"(?P<m1>{months})\.? (?P<d1>\d{{1,2}})(?:st|nd|rd|th)? (?:to|through|thru|until|till|-) "
                      rf"(?:(?P<m2>{months})\.? )?(?P<d2>\d{{1,2}})", said)
        if not m:
            continue
        today = dt.datetime.now(localtime.operator_tz()).date()
        start = _named_date(f"{m.group('m1')} {m.group('d1')}", today)
        end = _named_date(f"{m.group('m2') or m.group('m1')} {m.group('d2')}", start or today)
        if not start or not end or end < start:
            return None
        nights = (end - start).days
        return (f"{nights} night{'s' if nights != 1 else ''} - {start.strftime('%B')} {start.day} to "
                f"{end.strftime('%B')} {end.day}, from what you told me.")
    return None


def _time_where(text: str) -> str | None:
    """"What time is it where my sister lives": "my sister lives in Denver"
    from his notes, then the clock there. None without a town she knows."""
    who = re.sub(r"^(?:my|our) ", "", " ".join(str(_groups("time_where", text).get("tw_who") or "").casefold().split()))
    if not who or who in ("i", "you", "we", "it", "here"):
        return None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        m = re.fullmatch(r"(?:my |our )?" + re.escape(who) + r" (?:lives|is living|is based|moved|lives now) (?:in|to) "
                         r"(?P<town>[A-Za-z][A-Za-z .'-]{1,40}?)\.?", said, re.IGNORECASE)
        if m:
            clock = _time_in(m.group("town").casefold())
            if clock:
                return clock
    return None


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
    if g.get("t3"):
        g = {"t": g["t3"], "from": g["from3"], "to": ""}
    def zone_of(words):
        key = re.sub(r"^in ", "", " ".join(str(words or "").casefold().split()))
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
    said_next = w.startswith("next ")
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
    if said_next and w in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
        # "Next Friday" is the coming one to half the people who say it and
        # the one after to the rest (2026-10-07: she picked one silently).
        later = when + dt.timedelta(days=7)
        late_day = later.day
        late_suffix = "th" if 11 <= late_day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(late_day % 10, "th")
        return f"{said} - or the {late_day}{late_suffix}, if you mean the week after."
    return said + "."


def _noted_dates() -> list:
    """(date, his words) for every note that puts a date on something of his:
    "my registration is due November 30", "my license expires March 3",
    "the lease ends June 1". Only a month with its day; a bare month is not a
    date. Past dates roll to next year."""
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    month_re = "|".join(_MONTHS)
    out = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if not re.search(r"\b(?:is|are) due\b|\bexpires?\b|\bends?\b|\brenews?\b|\bis up\b|\bruns out\b", low):
            continue
        m = (re.search(rf"\b(?P<mon>{month_re})\.? (?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,? (?P<year>20\d\d))?\b", low)
             or re.search(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)? of (?P<mon>{month_re})(?:,? (?P<year>20\d\d))?\b", low))
        if not m:
            continue
        try:
            when = dt.date(int(m.group("year") or today.year), _MONTHS.index(m.group("mon")) + 1, int(m.group("day")))
        except ValueError:
            continue
        if not m.group("year") and when < today:
            when = when.replace(year=today.year + 1)
        out.append((when, said))
    return sorted(out)


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
    if which in ("today", "tomorrow", "this week", "next week", "this month", "next month"):
        which = "due " + which
    if which in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
        from aletheia import voice
        iso = voice._spoken_day(which)
        if not iso:
            return None
        day = which.capitalize()
        on = [t for t in rows if (tasks_mod.parse_deadline(t.get("deadline")) or now).astimezone(tz).date().isoformat() == iso
              and tasks_mod.parse_deadline(t.get("deadline"))]
        rem = _reminders_on(which) or ""
        rem = "" if rem.startswith("No reminders") else " " + rem
        if not on:
            return f"Nothing's due on {day}." + rem
        said = speech.and_list([str(t.get("description") or t.get("id")).strip().rstrip(".") for t in on[:5]])
        more = f", and {len(on) - 5} more" if len(on) > 5 else ""
        return f"{speech.count_phrase(len(on), 'thing')} due on {day}: {said}{more}.{rem}"
    # "What do I need to do this weekend" (2026-10-08: to a model, a turn
    # after "clean the gutters" went on the list due Sunday).
    if which == "this weekend":
        sat = now.date() + dt.timedelta(days=(5 - now.weekday()) % 7) if now.weekday() != 6 else now.date()
        days = {sat, sat + dt.timedelta(days=1)} if now.weekday() != 6 else {sat}
        on = [t for t in rows if tasks_mod.parse_deadline(t.get("deadline"))
              and tasks_mod.parse_deadline(t.get("deadline")).astimezone(tz).date() in days]
        if not on:
            return "Nothing on your list is due this weekend."
        said = speech.and_list([str(t.get("description") or t.get("id")).strip().rstrip(".") for t in on[:5]])
        return f"{speech.count_phrase(len(on), 'thing')} due this weekend: {said}."
    overdue_only = which in ("overdue", "late", "past due", "")
    limit = {"due today": end_of(now.date()), "due tomorrow": end_of(now.date() + dt.timedelta(days=1)),
             "due this week": end_of(now.date() + dt.timedelta(days=6 - now.weekday())),
             # "What's due this month" (2026-10-07: to a model).
             "due next week": end_of(now.date() + dt.timedelta(days=13 - now.weekday())),
             "due this month": end_of((now.date().replace(day=1) + dt.timedelta(days=32)).replace(day=1)
                                      - dt.timedelta(days=1)),
             "due next month": end_of((now.date().replace(day=1) + dt.timedelta(days=63)).replace(day=1)
                                      - dt.timedelta(days=1)),
             "due soon": now + dt.timedelta(days=3)}.get(which, now + dt.timedelta(days=7))
    dated = []
    for task in rows:
        when = tasks_mod.parse_deadline(task.get("deadline"))
        if when is None:
            continue
        if (when < now) if overdue_only else (when <= limit):
            dated.append((when, task))
    dated.sort(key=lambda pair: pair[0])
    # "What do I have to do tomorrow" left out "pick up the kids at 3"
    # (2026-10-08): a reminder on that day is something to do on it too.
    also = ""
    if which in ("due today", "due tomorrow"):
        rem = _reminders_on(which[4:]) or ""
        if rem and not rem.startswith("No reminders"):
            also = " " + rem
    # "My car registration is due November 30", then "what's due next month"
    # (2026-10-08): nothing on the list, and the date he told her unsaid.
    told = ([speech.as_she_says_it(text).rstrip(".") for day, text in _noted_dates()
             if now.date() <= day <= limit.date()] if not overdue_only and which.startswith("due ") else [])
    if told and not dated:
        return (f"Nothing on your list is {which}, but you told me: " + "; ".join(told[:3]) + "." + also)
    if told:
        also = f"{also} You also told me: " + "; ".join(told[:3]) + "."
    if not dated:
        undated = len(rows) - sum(1 for t in rows if tasks_mod.parse_deadline(t.get("deadline")))
        if also:
            return "Nothing's " + which + " on your list." + also
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
    return f"{head}: {said}{more}.{also}"


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
    year = int(m.group(3)) if m.group(3) else None
    if year is None:
        # "I was born in 1995" said on its own, beside a birthday with no year.
        try:
            from aletheia import memory
            told = re.fullmatch(r"\s*((?:19|20)\d\d)\s*", str(memory.recall("identity", "birth_year") or ""))
            year = int(told.group(1)) if told else None
        except Exception:
            year = None
    return month, int(day), year



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
        # "I took ibuprofen at 2" - the time he said, not when he said it.
        told_at = re.search(r"\bat (\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)\s*$", said)
        if told_at:
            clock = told_at.group(1)
        if at.date() == today:
            return f"Yes - you told me you took {'' if (re.fullmatch(_DRUGS, what.casefold()) and what != 'insulin') else 'your '}{what} at {clock} today."
        return (f"Not that you've told me today. The last time was {speech.humanize_time(at.isoformat())}." )
    # A medicine by name is not "your ibuprofen".
    yours = "" if re.fullmatch(_DRUGS, str(what or "").casefold()) and what not in ("insulin",) else "your "
    mine = "" if not yours else "my "
    return f"You haven't told me you took {yours}{what} today. Say \"I took {mine}{what}\" when you do and I'll keep track."


def _took_asked(text: str) -> str:
    """"Did I take ...": yes or no first. "When did I last take ...": the
    when, with no "Yes" in front of an answer to a question that was not
    a yes-or-no (2026-10-07)."""
    g = _groups("took_today", text)
    if g.get("took3"):
        said = re.sub(r"^Yes - you told me", "You told me", _took_today(g["took3"]))
        said = re.sub(r" Say \".*$", "", said)
        return (f"{said} How long to wait before the next one is on the label or your prescription - "
                "I won't guess at a dose.")
    said = _took_today(g.get("took") or g.get("took2") or "")
    if g.get("took2"):
        said = re.sub(r"^Yes - you told me", "You told me", said)
        said = re.sub(r"^Not that you've told me today\. The last time was", "The last time you told me was", said)
        said = re.sub(r" today\. Say ", ". Say ", said)
    return said


def _birthday_notes() -> list[tuple[str, int, int]]:
    """(who, month, day) for every birthday his notes name, newest note
    first and one per person. "who" is how she says it: "your mom", "Jess"."""
    month_re = "|".join(_MONTHS)
    seen, out = set(), []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        m = (re.search(r"^(?:that )?(?P<who>(?:my )?[a-z][a-z' ]{0,30}?)(?:'s|s'|’s) (?:birthday|bday) is ", low)
             # "Leo was born on May 3 2018" is a birthday too (2026-10-07).
             or re.search(r"^(?P<who>(?:my )?[a-z][a-z' ]{0,30}?) (?:was|were) born (?:on )?", low))
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
    rel = _relation_for_name(who)
    if rel:
        for shown, month, day in _birthday_notes():
            if re.sub(r"^your ", "", shown.casefold()) == rel:
                return _birthday_line(shown[:1].upper() + shown[1:], month, day)
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


def _safe_date(year: int, month: int, day: int):
    import datetime as dt
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _age_of(who: str) -> str | None:
    """How old somebody he told her about is, from the birthday in his note."""
    import datetime as dt
    from aletheia import localtime, speech
    who = " ".join(str(who or "").casefold().split())
    if re.match(r"(?:you|u|it|that|this|the|a|an|he|she|they|him|her|someone|somebody|anyone)\b", who):
        return None
    name = _name_for_relation(who) if who.startswith("my ") or who in _relation_words() else None
    label = name or re.sub(r"^my ", "", who)
    # "My mom's birthday is April 12" names her by the relation, not by
    # "Linda" (2026-10-07: "how old is my mom" found neither) - either will do.
    either = [re.findall(r"[a-z0-9]+", label.casefold())]
    if name:
        either.append(re.findall(r"[a-z0-9]+", re.sub(r"^my ", "", who)))
    month_re = "|".join(_MONTHS)

    def names_them(low: str) -> bool:
        return any(ws and all(re.search(rf"\b{re.escape(w)}", low) for w in ws) for ws in either)
    words = either[0]
    # "My mom was born in 1965" gives the year a birthday note may lack.
    born_in = None
    for row in _notes():
        low = " ".join(str(row.get("text") or "").split()).casefold()
        y = re.search(r"\bborn in ((?:19|20)\d\d)\b", low)
        if y and names_them(low):
            born_in = int(y.group(1))
            break
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if not names_them(low):
            continue
        if not re.search(r"\b(?:birthday|born|bday)\b", low) or re.search(r"\bborn in (?:19|20)\d\d\b", low):
            continue
        m = (re.search(rf"\b(?P<mon>{month_re})\.? (?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,? (?P<year>(?:19|20)\d\d))?", low)
             or re.search(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)? (?:of )?(?P<mon>{month_re})(?:,? (?P<year>(?:19|20)\d\d))?", low))
        if not m:
            continue
        shown = (name[:1].upper() + name[1:] if name
                 else f"Your {label}" if who.startswith("my ") or label in _relation_words() else label.title())
        if not m.group("year") and born_in:
            month, day = _MONTHS.index(m.group("mon")) + 1, int(m.group("day"))
            today = dt.datetime.now(localtime.operator_tz()).date()
            age = today.year - born_in - ((today.month, today.day) < (month, day))
            return f"{shown} is {age}" + (f", and turns {age + 1} on {m.group('mon').title()} {day}."
                                           if (today.month, today.day) != (month, day) else " - and it's today.")
        if not m.group("year"):
            # "Jake is 30" and "Jake's birthday is June 5" (2026-10-08: "not
            # the year, so I can't say how old"). The age he said, plus any
            # birthday since he said it.
            month, day = _MONTHS.index(m.group("mon")) + 1, int(m.group("day"))
            had = re.compile(rf"\b(?:{re.escape(label.casefold())}|{re.escape(re.sub(r'^my ', '', who))})"
                             r"(?: is| just turned| turned) (\d{1,3})(?: years old| yrs old)?\.?$")
            tz = localtime.operator_tz()
            today = dt.datetime.now(tz).date()
            for row in reversed(_notes()):
                a = had.search(" ".join(str(row.get("text") or "").split()).casefold())
                if not a:
                    continue
                try:
                    since = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
                except ValueError:
                    since = today
                age = int(a.group(1)) + sum(1 for y in range(since.year, today.year + 1)
                                            if _safe_date(y, month, day) and since < _safe_date(y, month, day) <= today)
                if (today.month, today.day) == (month, day):
                    return f"{shown} is {age} - and it's today."
                return f"{shown} is {age}, and turns {age + 1} on {m.group('mon').title()} {day}."
            told = shown[:1].lower() + shown[1:] if shown.startswith("Your ") else shown
            return (f"You told me {told}'s birthday is {m.group('mon').title()} {int(m.group('day'))}, "
                    f"but not the year, so I can't say how old. Tell me the year and I'll know.")
        month, day, year = _MONTHS.index(m.group("mon")) + 1, int(m.group("day")), int(m.group("year"))
        today = dt.datetime.now(localtime.operator_tz()).date()
        age = today.year - year - ((today.month, today.day) < (month, day))
        return f"{shown} is {age}" + (f", and turns {age + 1} on {m.group('mon').title()} {day}." if (today.month, today.day) != (month, day)
                                       else " - and it's today.")
    if born_in:
        shown = (name[:1].upper() + name[1:] if name
                 else f"Your {label}" if who.startswith("my ") or label in _relation_words() else label.title())
        year = dt.datetime.now(localtime.operator_tz()).year
        return (f"{shown} is {year - born_in - 1} or {year - born_in}, depending on whether the birthday has come yet "
                f"this year. Tell me the birthday and I'll know.")
    # "My sister is 28" said plainly (2026-10-08: to the planner, and "how
    # old is my sister" asked for her birthday after).
    # His capitals are on the name, never on the note it is matched against
    # ("how old is my cat" missed "Luna is 4", 2026-10-08).
    said_age = re.compile(rf"\b(?:{re.escape(label.casefold())}|{re.escape((name or label).casefold())}"
                          rf"|{re.escape(re.sub(r'^my ', '', who))})(?: is| just turned| turned| will be)"
                          r" (\d{1,3})(?: years old| yrs old)?\.?$")
    for row in reversed(_notes()):
        m = said_age.search(" ".join(str(row.get("text") or "").split()).casefold())
        if m and 0 < int(m.group(1)) < 120:
            told = (name[:1].upper() + name[1:] if name
                    else f"your {label}" if who.startswith("my ") or label in _relation_words() else label.title())
            return f"You told me {told} is {int(m.group(1))}."
    # "How old is Emma" with notes about Emma and none about her birthday
    # (2026-10-08: to a model). Somebody of his he never dated is his to
    # say; a name she has never heard of may be anybody's, so a model may.
    if who.startswith("my ") or label in _relation_words() or any(names_them(" ".join(str(r.get("text") or "").split()).casefold())
                                                                 for r in _notes()):
        shown = (name[:1].upper() + name[1:] if name
                 else f"your {label}" if who.startswith("my ") or label in _relation_words() else label.title())
        head = re.sub(r"^your ", "My ", shown) if shown.startswith("your ") else shown[:1].upper() + shown[1:]
        return (f"You haven't told me when {shown} was born. Say \"{head}'s birthday is\" and the date with the year, "
                "and I'll know.")
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


def _birthday(text: str = "") -> str:
    """When his birthday is, how far off, and how old he is when the year is known."""
    import datetime as dt
    from aletheia import localtime
    held = _birthday_on_file()
    if not held:
        return "I don't have your birthday. Say \"my birthday is March 3rd, 1995\" and I'll remember it."
    month, day, year = held
    # "What year was I born" is the year, first (2026-10-08)
    if re.search(r"\bborn\b|\bbirth year\b", _tidy(text)):
        if not year:
            return (f"You told me your birthday is {dt.date(2000, month, day).strftime('%B')} {day}, but not the year. "
                    "Say \"my birthday is\" with the year, and I'll remember it.")
        return f"{dt.date(year, month, day).strftime('%B')} {day}, {year}."
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
    if re.search(r"\bold\b|\bage\b", _tidy(text)):
        # "How old am I" with no year answered only when the birthday is
        return f"Your birthday is {when}, but you haven't told me the year, so I can't say how old. Say \"my birthday is\" with the year."
    return f"Your birthday is {when}."


_ZODIAC = ((1, 20, "Capricorn"), (2, 19, "Aquarius"), (3, 21, "Pisces"), (4, 20, "Aries"), (5, 21, "Taurus"),
           (6, 21, "Gemini"), (7, 23, "Cancer"), (8, 23, "Leo"), (9, 23, "Virgo"), (10, 23, "Libra"),
           (11, 22, "Scorpio"), (12, 22, "Sagittarius"), (12, 32, "Capricorn"))


def _born_facts(which: str) -> str:
    """His sign, or the weekday he was born, from the birthday on file."""
    import datetime as dt
    held = _birthday_on_file()
    if not held:
        return "I don't have your birthday. Say \"my birthday is March 3rd, 1995\" and I'll remember it."
    month, day, year = held
    asked = str(which or "")
    if asked == "next year" or asked in ("days", "weeks", "months"):
        if not year:
            return "I have your birthday but not the year. Say \"my birthday is\" with the year and I'll know."
        from aletheia import localtime
        today = dt.datetime.now(localtime.operator_tz()).date()
        age = today.year - year - ((today.month, today.day) < (month, day))
        if asked in ("days", "weeks", "months"):
            try:
                lived = (today - dt.date(year, month, day)).days
            except ValueError:
                return "I couldn't work that out from the birthday I have."
            n = {"days": lived, "weeks": lived // 7, "months": age * 12 + (today.month - month) % 12 - (today.day < day)}[asked]
            return f"About {n:,} {asked}." if asked != "days" else f"{n:,} days."
        # the birthday he turns next is this year's when it has not come yet
        upcoming = (today.month, today.day) < (month, day)
        return (f"{age + 2} - you turn {age + 1} on {dt.date(2000, month, day).strftime('%B')} {day} this year, "
                f"and {age + 2} on it next year." if upcoming
                else f"{age + 1}, on {dt.date(2000, month, day).strftime('%B')} {day} next year.")
    if which == "day":
        if not year:
            return "I have your birthday but not the year. Say \"my birthday is\" with the year and I'll know."
        try:
            return f"You were born on a {dt.date(year, month, day).strftime('%A')}."
        except ValueError:
            return "I couldn't work that out from the birthday I have."
    sign = next(name for m, d, name in _ZODIAC if (month, day) < (m, d))
    return f"{sign} - your birthday is {dt.date(2000, month, day).strftime('%B')} {day}."


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
    if what == "quarter":
        return f"The {('first', 'second', 'third', 'fourth')[(today.month - 1) // 3]} quarter of {today.year}."
    asked = re.fullmatch(r"(\w+) (?:a |the )?(weekday|week day|weekend|weekend day|work ?day|working day)", what)
    if asked:
        names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        word = asked.group(1)
        day = today if word == "today" else today + dt.timedelta(days=1) if word == "tomorrow" else None
        weekday = day.weekday() if day else names.index(word)
        weekend = asked.group(2).startswith("weekend")
        yes = (weekday >= 5) == weekend
        name = f"{word} is {day.strftime('%A')}" if day else f"{word.capitalize()} is {'a weekday' if weekday < 5 else 'the weekend'}"
        return f"{'Yes' if yes else 'No'} - {name}."
    if what in ("yesterday", "tomorrow"):
        day = today + dt.timedelta(days=-1 if what == "yesterday" else 1)
        return f"{what.capitalize()} {'was' if what == 'yesterday' else 'is'} {said(day)}."
    if what == "week":
        return f"It's week {today.isocalendar()[1]} of {today.year}."
    if what in ("this", "it"):
        leap = calendar.isleap(today.year)
        return f"{today.year} is {'' if leap else 'not '}a leap year."
    # "How many days in February 2028" (2026-10-07: to a model).
    year_said = re.search(r" (this year|next year|(?:19|20)\d\d)$", what)
    what = what[:year_said.start()] if year_said else what
    year = (today.year + 1 if year_said.group(1) == "next year" else today.year if year_said.group(1) == "this year"
            else int(year_said.group(1))) if year_said else today.year
    month = today.month if what == "this month" else (
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"].index(what) + 1)
    days = calendar.monthrange(year, month)[1]
    if month == 2 and year_said and year_said.group(1)[0].isdigit():
        return f"February {year} has {days} days."
    return f"{calendar.month_name[month]} has {days} days" + (
        f" {'next year' if year != today.year else 'this year'}." if month == 2 else ".")


def _until(words: str, *, which_day: bool = False) -> str | None:
    """Days until a date he named, from the calendar and nothing else.
    `which_day`: he asked WHEN it is, so the date leads ("what day is
    Thanksgiving" answered "50 days" first, 2026-10-07)."""
    import datetime as dt
    from aletheia import localtime, speech
    # "How long until sunset" is the sun's, not a date's (2026-10-08).
    if re.fullmatch(r"(?:the )?(?:sunset|sunrise|dark|it gets dark|the sun sets)", str(words or "").strip()):
        return _sun(f"how long until {str(words).strip()}")
    # "how long until my next meeting" is the calendar's, not a date's
    # (2026-09-23 night sweep: it fell through here to a model).
    if re.fullmatch(r"(?:my |the )?next (?:meeting|appointment|event)", " ".join(str(words or "").casefold().split())):
        return _next_meeting(until=True)
    if re.fullmatch(r"(?:my )?(?:bedtime|bed time|bed)", " ".join(str(words or "").casefold().split())):
        return _until_bedtime()
    # "How many days until the end of the month" (2026-10-07: no answer).
    end = re.fullmatch(r"(?:the )?end of (?:the |this )?(month|year)", " ".join(str(words or "").casefold().split()))
    if end:
        return _days_left(end.group(1))
    # "how long until my interview" is the calendar's too (2026-09-24)
    if re.fullmatch(r"(?:my |the )?(?:next )?interview(?: with .+)?", " ".join(str(words or "").casefold().split())):
        return _interview_when()
    # "How long until my flight" when he told her the day AND the time:
    # hours, not "Tomorrow" (2026-10-08).
    if re.match(r"(?:my|our) ", " ".join(str(words or "").casefold().split())):
        try:
            from aletheia import voice
            if voice._event_from_notes(words):
                timed = _until_mine(words)
                if timed:
                    return timed
        except Exception:
            pass
    today = dt.datetime.now(localtime.operator_tz()).date()
    nxt = re.fullmatch(r"next (monday|tuesday|wednesday|thursday|friday|saturday|sunday)", " ".join(str(words or "").casefold().split()))
    if nxt:
        # "How many days until next Friday" (2026-10-08: to a model) is two
        # answers on most days, the same two "what's the date next Friday" gives.
        ahead = (_WEEKDAYS.index(nxt.group(1)) - today.weekday()) % 7 or 7
        soon, later = today + dt.timedelta(days=ahead), today + dt.timedelta(days=ahead + 7)
        name = nxt.group(1).capitalize()
        first = "Tomorrow" if ahead == 1 else f"{ahead} days"
        if ahead == 7:
            return f"7 days, {name} the {_ordinal(soon.day)}."
        return (f"{first}, {name} the {_ordinal(soon.day)} - or {ahead + 7} days, the {_ordinal(later.day)}, "
                f"if you mean the week after.")
    when = _named_date(words, today) or _his_date(words, today)
    if when is None:
        if re.fullmatch(r"(?:my )?birthday", " ".join(str(words or "").casefold().split())):
            return "I don't know your birthday yet. Say \"my birthday is March 3\" and I'll remember it."
        found = _until_mine(words)  # a thing, not a date: the model may think
        if found is None and re.fullmatch(r"(?:my |our |the )?(?:trip|vacation|holiday|getaway)", " ".join(str(words or "").casefold().split())):
            # "I'm going to Paris next month" names no day (2026-10-08: a
            # model was asked to count to it).
            for row in _notes():
                said = " ".join(str(row.get("text") or "").split())
                if re.search(r"\b(?:trip|vacation|holiday|going to|heading to|flying to|driving to)\b", said, re.I) \
                        and re.search(r"\b(?:next|this) (?:week|month|year|summer|winter|spring|fall|weekend)\b|\bin (?:the )?(?:summer|winter|spring|fall)\b", said, re.I):
                    return (f"You told me {speech.as_she_says_it(said).rstrip('.')}, but not the day. "
                            "Tell me the date and I'll count down to it.")
        return found
    days = (when - today).days
    said = when.strftime("%A %d %B").replace(" 0", " ")
    if days == 0:
        return f"That's today, {said}."
    if days == 1:
        return f"Tomorrow, {said}."
    if which_day:
        return f"{said}, {days} days from now."
    return f"{days} days, {said}."


def _until_bedtime() -> str:
    """"How long until bedtime" (2026-10-08: to a model): his bedtime
    reminder, or the bedtime he told her, from now."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    at, why = None, ""
    try:
        from aletheia import intercom, scheduler
        found, _w = intercom._one_reminder("bed")
        if found is not None:
            at = scheduler.next_occurrence(found, now)
            why = "your bedtime reminder"
    except Exception:  # noqa: BLE001
        at = None
    if at is None:
        for row in _notes():
            m = re.match(r"i (?:usually |normally |always )?(?:go to bed|go to sleep|turn in) (?:at |around |by )?"
                         r"(\d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?)", " ".join(str(row.get("text") or "").split()), re.I)
            if m:
                from aletheia import voice
                hhmm = voice._spoken_time(m.group(1))
                if hhmm:
                    hour, minute = map(int, hhmm.split(":"))
                    if voice._is_bare_hour(m.group(1)) and 6 <= hour <= 11:
                        hour += 12
                    at = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
                    if at <= now:
                        at += dt.timedelta(days=1)
                    why = "the bedtime you told me"
                break
    if at is None:
        return "You haven't told me a bedtime. Say \"remind me to go to bed at 10:30 every night\" and I'll keep it."
    def span_of(minutes):
        hours, mins = divmod(max(1, minutes), 60)
        return " and ".join(p for p in (f"{hours} hour{'s' if hours != 1 else ''}" if hours else "",
                                        f"{mins} minute{'s' if mins != 1 else ''}" if mins else "") if p)
    at = at.astimezone(tz)
    gone = int((now - (at - dt.timedelta(days=1))).total_seconds() // 60)
    clock = at.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    if 0 < gone < 6 * 60:
        # Asked at 1 am, "22 hours" is true and useless: bedtime has gone by.
        return f"Past it - {why} was {clock}, {span_of(gone)} ago."
    span = span_of(int((at - now).total_seconds() // 60))
    return f"{span[:1].upper() + span[1:]} - {why} is {speech.humanize_time(at.isoformat())}."


def _holiday_year(text: str) -> str | None:
    """A holiday in the year he names: the day it falls on, said whole."""
    import datetime as dt
    from aletheia import localtime
    g = _groups("holiday_year", text)
    today = dt.datetime.now(localtime.operator_tz()).date()
    said = (g.get("hy_year") or "").replace("in ", "")
    year = today.year + 1 if said == "next year" else int(said) if said.isdigit() else None
    if not year or not g.get("hy") or abs(year - today.year) > 200:
        return None
    try:
        when = _named_date(g["hy"], dt.date(year - 1, 12, 31))
    except Exception:
        return None
    if when is None or when.year != year:
        return None
    return f"{when.strftime('%A %d %B %Y').replace(' 0', ' ')}."


def _until_mine(words: str) -> str | None:
    """"How long until my dentist appointment", "... until my timer goes
    off", "... until the weekend" (2026-10-07: all to a model, with the hold,
    the timer and the calendar in her own stores). None when nothing of his
    is named that, so a model may still know."""
    import datetime as dt
    from aletheia import localtime, speech
    said = " ".join(str(words or "").casefold().split())
    now = dt.datetime.now(localtime.operator_tz())
    if re.fullmatch(r"(?:the |this )?weekend", said):
        if now.weekday() >= 5:
            return "It's the weekend now."
        days = 5 - now.weekday()
        return "Tomorrow is Saturday." if days == 1 else f"{days} days - it starts Saturday."
    # "How long until my lease ends" (2026-10-08): the note that dates it.
    ending = re.fullmatch(r"(?:my|the|our) (?P<x>[a-z][a-z' ]{1,30}?) (?:ends|expires|is up|runs out)", said)
    if ending:
        left = _left_on(ending.group("x"))
        if left:
            return left
    thing = re.sub(r"^(?:my|the) (?:next )?|\s+(?:goes off|go off|is|starts|begins|rings)$", "", said)
    # "How many days until the party": the "the" was taken by the pattern
    # (2026-10-07: to a model). A bare thing is still looked for; only a
    # match on her own stores answers.
    if not thing:
        return None
    timer = re.fullmatch(r"(?:\w+ )?(?:timer|alarm)", thing)
    # The thing itself before a reminder that mentions it: "pack - your
    # flight is tomorrow" at 7 pm is not the flight (2026-10-08). The
    # calendar first, then a note that gave it a day and a time, then the
    # reminders.
    coming = _coming()
    if not timer:
        try:
            from aletheia import voice
            noted = voice._event_from_notes(thing)
        except Exception:
            noted = None
        if noted:
            coming = ([row for row in coming if row[2] == "calendar"]
                      + [(dt.datetime.fromisoformat(noted["start"]), thing, "note")]
                      + [row for row in coming if row[2] != "calendar"])
        else:
            coming = sorted(coming, key=lambda row: row[2] != "calendar")
    for at, text, store in coming:
        low = text.casefold()
        if timer:
            hit = store == "reminder" and (("timer is up" in low) if "timer" in thing else low == "wake up")
        else:
            words_of = [w for w in re.findall(r"[a-z0-9]+", thing) if w not in _STOP_WORDS]
            named = [w for w in words_of if w.rstrip("s") not in _WHEN_NOUNS] or words_of
            hit = bool(named) and all(re.search(rf"\b{re.escape(w.rstrip('s'))}", low) for w in named)
        if not hit:
            continue
        minutes = max(0, int(round((at - now).total_seconds() / 60)))
        days, rest = divmod(minutes, 24 * 60)
        hours, mins = divmod(rest, 60)
        # "17 days and 32 minutes" (2026-10-07): the two biggest units that
        # sit side by side, and a day count past a few days on its own.
        if days >= 3:
            parts = [speech.count_phrase(days + (1 if hours >= 12 else 0), "day")]
        elif days:
            parts = [speech.count_phrase(days, "day")] + ([speech.count_phrase(hours, "hour")] if hours else [])
        else:
            parts = [speech.count_phrase(n, unit) for n, unit in ((hours, "hour"), (mins, "minute")) if n]
        span = " and ".join(parts[:2]) if parts else "less than a minute"
        return f"{span[:1].upper()}{span[1:]} - {speech.humanize_time(at.isoformat())}."
    return None


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


def _focus(only_first: bool = False) -> str:
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
    # "What should I do first" read the whole list back (2026-10-08): the
    # first one, and why it is first. "Plan my day" still wants the list.
    tasks = _task_top() if only_first else _tasks()
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


def _as_done(line: str) -> str:
    """A receipt read back as something done. "Today: I'll remind you today
    at 5 pm: call Dana" promised in the future what he asked about in the
    past (2026-10-07)."""
    m = re.fullmatch(r"I'll remind you (.+?): (.+)", line)
    if m:
        return f"Set a reminder for {m.group(1)}: {m.group(2)}"
    m = re.fullmatch(r"(.+?),? I'll remind you: (.+)", line)
    if m:
        return f"Set a reminder for {m.group(1)[:1].lower()}{m.group(1)[1:]}: {m.group(2)}"
    return line


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
    lines = [_shortened(_as_done(str(r.get("what") or "").strip().rstrip(".")))
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
            line = _shortened(_as_done(str(rows[-1].get("what") or "").strip().rstrip(".")))
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
            # "Job interview" he pencilled in himself (2026-10-07: "no
            # interview on your calendar" with it there) is one too.
            if not re.search(r"\binterview\b", title, re.I):
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
    who = re.sub(r"^\s*interview\s*[:with-]*\s*", "", title, flags=re.I).strip()
    kind = re.fullmatch(r"\s*(?:(?:my|a|the) )?((?:job|phone|video|zoom|second|final|first|in-person|onsite|on-site) )*interview\s*", title, re.I)
    if kind or not who:
        named = f"Your {title.strip().lower()}" if kind and kind.group(1) else "Your interview"
    else:
        who = re.sub(r"\s*interview$", "", who, flags=re.I).strip() or "them"
        named = f"Your interview with {who}"
    day = "today" if start.date() == now.date() else "tomorrow" if start.date() == now.date() + dt.timedelta(days=1) \
        else start.strftime("%A")
    clock = start.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    left = start - now
    hours_left = left.total_seconds() / 3600.0
    until = (f"in {int(round(hours_left * 60))} minutes" if hours_left < 1
             else f"in {int(round(hours_left))} hours" if hours_left < 36
             else f"in {int(round(hours_left / 24))} days")
    said = f"{named} is {day} at {clock}, {until}."
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


def _did_finish(what: str) -> str | None:
    """"Did I finish the report": a task of his ticked off, or a note that
    he finished it - and an open task by that name is a plain no. None when
    neither store knows the thing at all, so nothing is guessed."""
    import datetime as dt
    from aletheia import speech, tasks
    what = " ".join(str(what or "").casefold().split())
    words = [w for w in re.findall(r"[a-z0-9]+", what) if w not in ("the", "my", "a", "an", "it", "that")]
    if not words or what in ("it", "that", "everything", "anything"):
        return None

    # "Did I finish cleaning the garage" is the task "clean the garage".
    stems = [w[:-3] if len(w) > 5 and w.endswith("ing") else w.rstrip("s") for w in words]

    def names(text: str) -> bool:
        low = str(text or "").casefold()
        return all(re.search(rf"\b{re.escape(w)}", low) for w in stems)
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        m = re.match(r"i(?:'ve| have)? (?:just )?(?:finished|completed|wrapped up|did|done) (.+)", said, re.IGNORECASE)
        if m and names(m.group(1)):
            when = speech.humanize_time(str(row.get("ts") or "")) if row.get("ts") else ""
            return f"Yes - you told me you finished {speech.as_she_says_it(m.group(1)).rstrip('.')}" + (f", {when}." if when else ".")
    try:
        rows = [t for t in tasks.all_tasks() if tasks.is_his(t) and names(t.get("description"))]
    except Exception:
        return None
    done = [t for t in rows if str(t.get("status") or "").upper() == "COMPLETED"]
    if done:
        t = max(done, key=lambda t: str(t.get("updated_at") or ""))
        when = speech.humanize_time(str(t.get("updated_at") or "")) if t.get("updated_at") else ""
        return f"Yes - you ticked off {str(t.get('description') or '').rstrip('.')}" + (f" {when}." if when else ".")
    if rows:
        return f"Not yet - {str(rows[0].get('description') or '').rstrip('.')} is still open on your list."
    return None


def _tasks_done(when: str = "") -> str:
    """His tasks finished today, yesterday or this week, by when they closed."""
    import datetime as dt
    from aletheia import localtime, speech, tasks
    asked = str(when or "").strip()
    when = asked or "today"
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    monday = today - dt.timedelta(days=today.weekday())
    first, last = {"yesterday": (today - dt.timedelta(days=1),) * 2,
                   "this week": (monday, today),
                   # "What did I do on Saturday", "last weekend" (2026-10-08: to a model).
                   "last week": (monday - dt.timedelta(days=7), monday - dt.timedelta(days=1)),
                   "last weekend": (monday - dt.timedelta(days=2), monday - dt.timedelta(days=1)),
                   "over the weekend": (monday - dt.timedelta(days=2), monday - dt.timedelta(days=1)),
                   "this weekend": (monday + dt.timedelta(days=5), min(today, monday + dt.timedelta(days=6))),
                   }.get(when, (today, today))
    day = re.fullmatch(r"(?:on )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", when)
    if day:
        back = (today.weekday() - _WEEKDAYS.index(day.group(1))) % 7
        first = last = today - dt.timedelta(days=back)
        when = "today" if back == 0 else f"on {day.group(1).capitalize()}"
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
    # "I finished the report" with no task for it is kept as a note
    # (2026-10-07), and "what did I do today" then said nothing was done.
    noted = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        m = re.match(r"i(?:'ve| have)? (?:just )?(finished|completed|wrapped up|did|done) (.+)", said, re.IGNORECASE)
        if not m:
            continue
        try:
            day = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if first <= day <= last:
            verb = m.group(1).casefold()
            noted.append(f"{'did' if verb == 'done' else verb} {speech.as_she_says_it(m.group(2)).rstrip('.')}")
    if noted:
        also = f"you told me you {speech.and_list(noted[:4])}"
        if not done:
            return f"Nothing ticked off your list {when}, but {also}."
        return (f"{speech.count_phrase(len(done), 'task')} done {when}: " + speech.and_list(done[:6])
                + f". And {also}.")
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
    him, negative is what he owes. "Paid back" settles that direction.

    The two directions are kept apart until the end (2026-10-08): "I owe
    Mike 20", "Mike owes me 50", "I paid Mike back" left Mike owing 30,
    because the 20 had already been netted away before it was paid."""
    rows = list(reversed(_notes()))
    owe: dict[str, float] = {}
    owed: dict[str, float] = {}
    for row in rows:
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold().rstrip(".")
        low = re.sub(r"^(?:remember(?: that)?|note(?: that)?) ", "", low)
        m = (re.fullmatch(r"i owe (?P<who>[a-z][a-z ]{0,25}?) " + _MONEY + r"(?: for .+)?", low)
             or re.fullmatch(r"i borrowed " + _MONEY + r" from (?P<who>[a-z][a-z ]{0,25}?)(?: for .+)?", low))
        if m:
            who = m.group("who")
            owe[who] = owe.get(who, 0) + float(m.group("amt"))
            continue
        m = (re.fullmatch(r"(?P<who>[a-z][a-z ]{0,25}?) owes me " + _MONEY + r"(?: for .+)?", low)
             or re.fullmatch(r"i (?:lent|loaned|gave) (?P<who>[a-z][a-z ]{0,25}?) " + _MONEY + r"(?: for .+)?", low))
        if m and m.group("who") not in ("i", "you"):
            who = m.group("who")
            owed[who] = owed.get(who, 0) + float(m.group("amt"))
            continue
        m = re.fullmatch(r"i paid (?P<who>[a-z][a-z ]{0,25}?) back(?: " + _MONEY + r")?", low)
        if m and owe.get(m.group("who"), 0) > 0:
            who = m.group("who")
            owe[who] = max(0.0, owe[who] - float(m.group("amt"))) if m.group("amt") else 0.0
            continue
        m = (re.fullmatch(r"(?P<who>[a-z][a-z ]{0,25}?) paid me back(?: " + _MONEY + r")?", low)
             or re.fullmatch(r"(?P<who>[a-z][a-z ]{0,25}?) (?:paid|gave) me " + _MONEY + r"(?: back)?", low))
        if m and owed.get(m.group("who"), 0) > 0:
            who = m.group("who")
            owed[who] = max(0.0, owed[who] - float(m.group("amt"))) if m.group("amt") else 0.0
    out = {who: owed.get(who, 0) - owe.get(who, 0) for who in list(owe) + [w for w in owed if w not in owe]}
    return {k: round(v, 2) for k, v in out.items() if abs(v) >= 0.005}


def _named(who: str) -> str:
    """"sam" -> "Sam"; "the irs" -> "the IRS", not "The irs" (2026-10-07)."""
    words = str(who or "").split()
    out = [w.upper() if w in ("irs", "dmv", "ups", "usps", "hoa", "va") else
           w if (i == 0 and w in ("the", "my", "our")) or (i and w in ("the", "of", "and")) else w[:1].upper() + w[1:]
           for i, w in enumerate(words)]
    return " ".join(out)


def _owed(question: str = "") -> str:
    """What he owes and is owed, from what he told her; never a guess.

    "Who owes me money" opened with "You don't owe anybody" (2026-10-07):
    the half he asked about comes first, and only that half when he asked
    one way round."""
    from aletheia import speech
    ledger = _ledger()
    g = _groups("owed", question) if question else {}
    who = " ".join(str(g.get("owe_who") or g.get("owe_amt") or "").casefold().split())
    low = _tidy(question or "")
    to_me = bool(re.search(r"\bowes? me\b", low)) and not re.search(r"\bdo i owe\b", low)
    by_me = bool(re.search(r"\b(?:do i (?:still )?owe|what do i owe)\b", low)) and not to_me
    if who:
        name = _named(who)
        amount = ledger.get(who, 0)
        if amount < 0:
            return f"You owe {name} {_money(-amount)}."
        if amount > 0:
            return f"{name} owes you {_money(amount)}."
        return f"Nothing between you and {name} that you've told me about."
    owe = [f"{_named(k)} {_money(-v)}" for k, v in ledger.items() if v < 0]
    owed = [f"{_named(k)} owes you {_money(v)}" for k, v in ledger.items() if v > 0]
    owed_line = (speech.and_list(owed)[:1].upper() + speech.and_list(owed)[1:] + ".") if owed else ""
    # When the half he asked about is empty, the other half is still worth
    # a sentence: "nobody - but you owe Jo $5".
    if to_me:
        if owed_line:
            return owed_line
        return ("Nobody owes you anything that you've told me about. "
                + ("You owe " + speech.and_list(owe) + "." if owe
                   else "Say \"I lent Sam 20 dollars\" and I'll keep track."))
    if by_me and owe:
        return "You owe " + speech.and_list(owe) + "."
    if not owe and not owed:
        return "Nobody, as far as you've told me. Say \"I owe Sam 20 dollars\" and I'll keep track."
    said = ["You owe " + speech.and_list(owe) + "." if owe else "You don't owe anybody that you've told me about."]
    if owed_line:
        said.append(owed_line)
    return " ".join(said)


_PAST = {"take out": "took out", "taken out": "took out", "took out": "took out", "talk to": "talked to", "talk with": "talked to", "speak to": "talked to", "spoken to": "talked to",
         "speak with": "talked to", "talked to": "talked to", "see": "saw", "seen": "saw", "meet": "met", "meet with": "met",
         "meet up with": "met", "hang out with": "hung out with", "text": "texted", "texted": "texted",
         "catch up with": "caught up with", "shut": "shut", "turn off": "turned off", "turned off": "turned off",
         "get": "got", "got": "got", "gotten": "got", "have": "had", "had": "had", "pay": "paid", "paid": "paid", "give": "gave", "given": "gave", "feed": "fed", "fed": "fed", "cut": "cut", "drop off": "dropped off",
         "pick up": "picked up", "back up": "backed up", "empty": "emptied", "fill": "filled"}


#: Ways of being with somebody: asked about one, any of them answers.
_WITH_SOMEBODY = {"talked to", "saw", "met", "hung out with", "caught up with"}


def _past_of(verb: str) -> str:
    """"call" -> "called", the same rule `_did_last` reads his notes by."""
    return _PAST.get(verb) or (verb if verb.endswith("ed") else
                               verb + "d" if verb.endswith("e") else
                               verb[:-1] + "ied" if verb.endswith("y") and verb[-2:-1] not in "aeiou" else verb + "ed")


def _base_verb(past: str) -> str | None:
    """"called" -> "call", "dropped off" -> "drop off": the form "when did I
    last ..." is asked in, found by running `_past_of` backwards - None when
    no candidate gives the word back."""
    head, _, tail = past.partition(" ")
    for base, said in _PAST.items():
        if said == past:
            return base
    for cand in (head[:-1], head[:-2], head[:-3], head[:-3] + "y"):
        base = f"{cand} {tail}".strip()
        # Only a verb "when did I last" knows: "chang" would give "changed" back too.
        if cand and (_past_of(cand) == head or cand + cand[-1:] + "ed" == head) and _groups("did_last", f"when did i last {base} it"):
            return base
    return None


def _did_last(text: str) -> str | None:
    """When he last said he did a thing, from his notes. Never a guess: no
    note is "not that you've told me", and how to tell her."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("did_last", text)
    verb = (g.get("did_v") or g.get("did_v2") or g.get("did_v3") or g.get("did_v4") or g.get("did_v5") or "").strip()
    thing = (g.get("did_o") or g.get("did_o2") or g.get("did_o3") or g.get("did_o4") or g.get("did_o5") or "").strip()
    if g.get("did_o6"):
        # what somebody got is what he says he GAVE them
        verb, thing = "give", f"{g.get('did_who6') or ''} {g['did_o6']}"
    window = (g.get("did_today") or g.get("did_today2") or "").strip()
    service = bool(g.get("did_v3") or g.get("did_v4"))
    if not verb or not thing:
        return None
    if re.search(r"\b(?:email|emails|mail|message|messages|text|texts|call|calls|reply|replies|package|parcel)\b", thing) \
            and verb in ("get", "mail", "mailed", "see", "seen", "text", "texted"):
        return None
    past = _past_of(verb)
    base = re.sub(r"(?:ied)$", "y", past)
    words = [w for w in re.findall(r"[a-z0-9']+", thing.casefold())
             if w not in ("the", "my", "our", "his", "her", "a", "an", "some", "its")]
    tz = localtime.operator_tz()
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        # talking to somebody is any of the ways he says he did
        said_as = ("(?:got|had|gotten)" if service else
                   r"(?:talked (?:to|with)|spoke (?:to|with)|called|texted|saw|met(?: up)?(?: with)?|hung out with|caught up with|visited)"
                   if past in _WITH_SOMEBODY else re.escape(past))
        # "I took the trash out" is "I took out the trash" (2026-10-08).
        if " " in past and not service and past not in _WITH_SOMEBODY:
            head, _, particle = past.partition(" ")
            said_as = rf"(?:{re.escape(past)}|{re.escape(head)}\b.{{1,40}}?\b{re.escape(particle)})"
        if not re.search(r"\bi (?:just )?" + said_as + r"\b", low) or not all(
                re.search(r"\b" + re.escape(w), low) for w in words):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            at = None
        # his words, his capitals: "you saw Sam", not "you saw sam"
        told = re.sub(r"\bi\b", "you", re.sub(r"^i (?:just )?", "you ", said, flags=re.I), flags=re.I)
        told = re.sub(r"\bmy\b", "your", told, flags=re.I)
        # "you changed the oil today - that was today at 6:56 am" said it twice.
        told = re.sub(r" (?:today|yesterday|this morning|this afternoon|this evening|tonight|last night|earlier)\.?$", "", told, flags=re.I)
        told = told.rstrip(".")
        if at is None:
            return f"You told me {told}."
        when = speech.humanize_time(at.isoformat())
        if g.get("did_v5"):
            days = (dt.datetime.now(tz).date() - at.date()).days
            lead = "Not long" if days <= 0 else speech.count_phrase(days, "day")
            return f"{lead} - you told me {told} {when}."
        if window in ("today", "yet", "this morning"):
            if at.date() == dt.datetime.now(tz).date():
                return f"Yes - you told me {told}, {when}."
            return f"Not today that you've told me. The last time was {when}."
        # "Did I pay rent this month" (2026-10-07: "not that you've told me"
        # one turn after "I paid rent").
        if window in ("this week", "this month"):
            today = dt.datetime.now(tz).date()
            first = today.replace(day=1) if window == "this month" else today - dt.timedelta(days=today.weekday())
            if at.date() >= first:
                return f"Yes - you told me {told}, {when}."
            return f"Not {window} that you've told me. The last time was {when}."
        return f"You told me {told} - that was {when}."
    if service:
        # "I got a haircut" ticked off the task "get a haircut" rather than
        # writing a note: the task's own close is when it happened.
        try:
            from aletheia import tasks
            done = [t for t in tasks.all_tasks() if str(t.get("status") or "").upper() in ("DONE", "COMPLETED")
                    and str(t.get("description") or "").casefold().startswith("get ")
                    and all(re.search(r"\b" + re.escape(w), str(t.get("description") or "").casefold()) for w in words)]
        except Exception:
            done = []
        done.sort(key=lambda t: str(t.get("updated_at") or ""), reverse=True)
        if done and done[0].get("updated_at"):
            when = speech.humanize_time(str(done[0]["updated_at"]))
            if window in ("today", "yet", "this morning"):
                try:
                    day = dt.datetime.fromisoformat(str(done[0]["updated_at"]).replace("Z", "+00:00")).astimezone(tz).date()
                except ValueError:
                    day = None
                if day != dt.datetime.now(tz).date():
                    return f"Not today that you've told me. The last time was {when}."
            got = re.sub(r"^get ", "got ", str(done[0]["description"]).strip(), flags=re.I)
            got = re.sub(r"\bmy\b", "your", got)
            if window in ("today", "yet", "this morning"):
                return f"Yes - you {got}, {when}."
            return f"You {got} {when} - you ticked it off your list."
    # "I picked up my prescription" ticked the task off instead of writing a
    # note (2026-10-08: "not that you've told me" one turn later).
    if not service:
        try:
            from aletheia import tasks
            n = len(verb.split())
            rows = [t for t in tasks.all_tasks() if tasks.is_his(t)
                    and _past_of(" ".join(str(t.get("description") or "").casefold().split()[:n])) == past
                    and all(re.search(r"\b" + re.escape(w), str(t.get("description") or "").casefold()) for w in words)]
        except Exception:
            rows = []
        done = sorted((t for t in rows if str(t.get("status") or "").upper() in ("DONE", "COMPLETED")),
                      key=lambda t: str(t.get("updated_at") or ""), reverse=True)
        if done:
            desc = re.sub(r"\bmy\b", "your", str(done[0].get("description") or "").strip().rstrip("."), flags=re.I)
            when = speech.humanize_time(str(done[0].get("updated_at") or "")) if done[0].get("updated_at") else ""
            return f"Yes - you ticked off {desc}" + (f" {when}." if when else ".")
        if any(str(t.get("status") or "").upper() not in _TASK_CLOSED for t in rows):
            desc = re.sub(r"\bmy\b", "your", str(rows[0].get("description") or "").strip().rstrip("."), flags=re.I)
            return f"Not yet - {desc} is still on your list."
    say = f"I {past} {thing}"
    if g.get("did_o6"):
        # "I gave Max his flea medicine", his capitals and his pronoun
        who6 = str(g.get("did_who6") or "")
        shown = who6 if re.match(r"(?:the|my) ", who6) else _named(who6)
        say = f"I {past} {shown} {g.get('did_pro6')} {g['did_o6']}"
    return (f"Not that you've told me. Say \"{say}\" when you do and I'll keep track."
            if g.get("did_v2") or g.get("did_v4") else
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
        # "When is rent due" with a monthly reminder to pay it (2026-10-07:
        # "I have nothing about rent on file").
        return (_when_mine(words) or _due_note(words)) if not hits else None
    task = hits[0]
    what = str(task.get("description") or task.get("id") or "").strip().rstrip(".")
    what = what[:1].upper() + what[1:]
    when = tasks.parse_deadline(task.get("deadline"))
    if not when:
        # "Renew my passport by June" has its when in its own words
        # (2026-10-07: "has no due date", with "by June" right there).
        said = re.search(r"\b(by|before) ((?:the )?(?:end of )?[a-z0-9][a-z0-9 ]{1,25})$", what, re.IGNORECASE)
        if said:
            return f"By {said.group(2)[:1].upper() + said.group(2)[1:]}, you said - there's no exact date on it."
        return f"{what} has no due date. Say \"move it to Friday\" and it will have one."
    # A day said with no time is kept as the end of that day; "at 11:59 pm"
    # is the store's, not his.
    said = re.sub(r" at 11:59 ?pm$", "", speech.humanize_time(when.isoformat()))
    return f"{what} is due {said}."


def _due_note(words: str) -> str | None:
    """A note of his saying WHEN the thing is due. "When is rent due"
    answered "your rent is 1500" (2026-10-07): a note that names it but no
    day answers a different question, so it is not read back as this one."""
    from aletheia import speech
    asked = [w for w in re.findall(r"[a-z0-9']+", str(words or "").casefold()) if w not in ("my", "the", "a", "an", "our")]
    if not asked:
        return None
    dated = re.compile(r"\b(?:due|every|each|on the|by|before|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
                       r"|january|february|march|april|may|june|july|august|september|october|november|december"
                       r"|\d{1,2}(?:st|nd|rd|th)|first|last day|end of)\b", re.I)
    named = False
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if not all(re.search(rf"\b{re.escape(w)}", said, re.I) for w in asked):
            continue
        named = True
        if dated.search(said):
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    if named:
        thing = " ".join(asked)
        verb = "are" if thing.endswith("s") and not thing.endswith("ss") else "is"
        return f"You haven't told me when your {thing} {verb} due. Say \"my {thing} {verb} due on the 1st\" and I'll remember."
    # "When is the water bill due" was answered with "you paid the electric
    # bill" (2026-10-08): memory's answer counts only if it names it all.
    held = _recall(words)
    if held and all(re.search(rf"\b{re.escape(w)}", held, re.I) for w in asked) and " and you told me" not in held:
        return held
    return None


def _task_progress() -> str:
    """Done today, then what is open - the two halves of "how am I doing"."""
    done = _tasks_done("today")
    left = _tasks()
    if done.startswith("Nothing ticked off"):
        return "Nothing ticked off yet today. " + left
    return done + " " + left


def _and_one_more(tied: list) -> str:
    """"Email your boss is due then too." - a tie said, not hidden."""
    from aletheia import speech
    names = [str(t.get("description") or "").strip().rstrip(".") for t in tied[:3]]
    said = speech.and_list(names)
    return f"{said[:1].upper() + said[1:]} {'is' if len(names) == 1 else 'are'} due then too."


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
        # A date with no time is the day, not "tomorrow at 11:59 pm" (2026-10-08).
        when = re.sub(r" at 11:59 pm$", "", speech.humanize_time(deadline.isoformat()))
        tied = [t for d, t in dated if d == deadline and t is not top]
        also = f" {_and_one_more(tied)}" if tied else ""
        return f"{what[:1].upper() + what[1:]} - it has the nearest deadline, {when}.{also}"
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
        # "...open or close the garage, and say" was a sentence cut at a
        # character count (2026-10-08): a long one is cut at a clause.
        def clause(said: str) -> str:
            said = str(said or "").rstrip(".")
            while len(said) > 60 and ", " in said:
                said = said.rsplit(", ", 1)[0]
            return speech.shorten(said, 60).rstrip(".")
        named = [clause(intents._in_english(c)) for c in unbuilt[:3]]
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


def _meetings_week(which: str = "this week") -> str | None:
    """How many things are on his calendar for the rest of this week, or
    next week, Monday to Sunday on his clock."""
    import datetime as dt
    from aletheia import calendar, localtime, speech
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    monday = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    nxt = str(which).strip() == "next week"
    start = monday + dt.timedelta(days=7) if nxt else now
    end = monday + dt.timedelta(days=14 if nxt else 7)
    try:
        titles = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                at = calendar.parse_time(event["start"]).astimezone(tz)
            except (KeyError, ValueError, TypeError):
                continue
            if start <= at < end:
                titles.append((at, str(event.get("title") or "something")[:60]))
    except Exception:
        return None
    label = "next week" if nxt else "for the rest of this week"
    if not titles:
        return f"Nothing on your calendar {label}."
    titles.sort()
    shown = [f"{t} {speech.humanize_time(at.isoformat())}" for at, t in titles[:4]]
    return (f"{speech.count_phrase(len(titles), 'thing')} on your calendar {label}: {speech.and_list(shown)}"
            + (f", and {len(titles) - 4} more." if len(titles) > 4 else "."))


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
        if w == "yesterday":
            when = today - dt.timedelta(days=1)
        elif bare:
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
    if w == "yesterday":
        if not rows:
            return "Nothing was on your calendar yesterday."
        label = "Yesterday"
    if not rows:
        return f"Nothing on your calendar on {label}."
    rows.sort()
    said = [f"{title} at " + start.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower() for start, title in rows[:6]]
    return f"{label}: " + speech.and_list(said) + (f", and {len(rows) - 6} more" if len(rows) > 6 else "") + "."


def _agenda(day: str = "today") -> str | None:
    day = {"week": "this week", "the week": "this week", "the month": "this month"}.get(day, day)
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
        elif day == "this month":
            # "What's happening this month" (2026-10-07: to a model).
            first = now.date()
            last = (now.date().replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
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
             else "This month" if day == "this month"
             else "This week" if day == "this week" else "Next week")
    when_said = label.lower() if label in ("Today", "Tomorrow", "This week", "Next week", "This weekend", "Next weekend",
                                           "This month") else label
    # "We're having people over Friday night" is a note, and "what's
    # happening Friday" said only "Nothing on your calendar Friday"
    # (2026-10-07). His own word for the day, said this past week.
    told = _plans_told(day)
    if not rows:
        return f"Nothing on your calendar {when_said}." + (f" But you told me: {told}." if told else "") \
            + _reminders_between(first, last, now)
    rows.sort(key=lambda r: r[0])
    many_days = first != last
    said = [(f"{title} {start.strftime('%A')} the {_ordinal(start.day)} at " if day == "this month"
             else f"{title} {start.strftime('%A')} at " if many_days else f"{title} at ")
            + start.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower()
            for start, title in rows[:6]]
    return (f"{label}: " + speech.and_list(said)
            + (f", and {len(rows) - 6} more" if len(rows) > 6 else "") + "."
            + (f" And you told me: {told}." if told else ""))


def _plans_told(day: str) -> str:
    """His notes from the past six days naming this weekday or the weekend
    ("we're having people over Friday night"), in his words - "" for any
    other day word, since "tomorrow" said last week is not this tomorrow."""
    import datetime as dt
    from aletheia import speech
    word = {"this weekend": "weekend", "the weekend": "weekend"}.get(day, day)
    if word not in _WEEKDAYS and word != "weekend":
        return ""
    pattern = (r"\b(?:weekend|saturday|sunday)\b" if word == "weekend" else rf"\b{word}\b")
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=6)
    found = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if at >= cut and re.search(pattern, said.casefold()) and not re.search(r"\bnext\b|\blast\b|\bevery\b", said.casefold()):
            found.append(speech.as_she_says_it(said).rstrip("."))
        if len(found) >= 3:
            break
    return speech.and_list(found)


_PART_HOURS = {"morning": (5, 12), "afternoon": (12, 17), "evening": (17, 22), "night": (17, 24), "tonight": (17, 24)}


def _agenda_part(text: str) -> str | None:
    """One part of one day on his calendar: "tomorrow morning", "tonight"."""
    import datetime as dt
    from aletheia import calendar, localtime, speech
    g = _groups("agenda_part", text)
    day = g.get("ap_day") or g.get("ap_day4") or g.get("ap_day5") or "today"
    part = g.get("ap_part") or g.get("ap_part2") or g.get("ap_part3") or g.get("ap_part4") or g.get("ap_part5") or ""
    lo, hi = _PART_HOURS.get(part, (0, 24))
    try:
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        if day in _WEEKDAYS:
            when = now.date() + dt.timedelta(days=(_WEEKDAYS.index(day) - now.weekday()) % 7)
        else:
            when = now.date() + dt.timedelta(days=1 if day == "tomorrow" else 0)
        rows = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
            except (KeyError, ValueError, TypeError):
                continue
            if start.date() == when and lo <= start.hour < hi:
                rows.append((start, str(event.get("title") or "something")[:80]))
    except Exception:
        return None
    label = ("tonight" if part in ("tonight", "night") and when == now.date()
             else f"this {part}" if when == now.date()
             else f"tomorrow {part}" if when == now.date() + dt.timedelta(days=1) else f"{when.strftime('%A')} {part}")
    if not rows:
        return f"Nothing on your calendar {label}."
    rows.sort()
    said = [f"{t} at " + s.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower() for s, t in rows[:6]]
    return f"{label[:1].upper() + label[1:]}: {speech.and_list(said)}."


def _event_detail(text: str) -> str | None:
    """A meeting's length, who a meeting at a time is with, and the week's
    busiest or quietest day - all off the calendar mirror."""
    import datetime as dt
    from aletheia import calendar, localtime, speech
    g = _groups("event_detail", text)
    try:
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        events = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
                end = calendar.parse_time(event["end"]).astimezone(tz) if event.get("end") else None
            except (KeyError, ValueError, TypeError):
                continue
            if start >= now - dt.timedelta(hours=1):
                events.append((start, end, str(event.get("title") or "something")[:80]))
    except Exception:
        return None
    events.sort(key=lambda e: e[0])
    if g.get("ed_where"):
        from aletheia import voice
        words = [w for w in re.findall(r"[a-z0-9']+", g["ed_where"]) if w not in ("with", "the", "my", "a", "our")]
        day = voice._spoken_day("today" if g.get("ed_where_day") == "tonight" else g["ed_where_day"]) \
            if g.get("ed_where_day") else None
        try:
            held = [e for e in calendar.all_events() if e.get("status") != "CANCELLED"]
        except Exception:
            return None
        hits = []
        for event in held:
            try:
                start = calendar.parse_time(event["start"]).astimezone(tz)
            except (KeyError, ValueError, TypeError):
                continue
            title = str(event.get("title") or "")
            if start >= now - dt.timedelta(hours=1) and (not day or start.date().isoformat() == day) \
                    and all(re.search(r"\b" + re.escape(w), title.casefold()) for w in words):
                hits.append((start, title, str(event.get("location") or "").strip()))
        if not hits:
            return None
        start, title, where = sorted(hits)[0]
        title = title[:1].upper() + title[1:]
        when = speech.humanize_time(start.isoformat())
        if where:
            return f"{title} is at {where}, {when}."
        return f"{title} is {when} - you haven't told me where. Say \"it's at\" and the place and I'll add it."
    if g.get("ed_long"):
        words = [w for w in re.findall(r"[a-z0-9']+", g["ed_long"]) if w not in ("with", "the", "my", "a")]
        hits = [e for e in events if all(re.search(r"\b" + re.escape(w), e[2].casefold()) for w in words)]
        if not hits:
            return None
        start, end, title = hits[0]
        if not end:
            return f"{title} has no end time on your calendar."
        minutes = int((end - start).total_seconds() // 60)
        amount = (speech.count_phrase(minutes // 60, "hour") + (f" and {speech.count_phrase(minutes % 60, 'minute')}" if minutes % 60 else "")
                  if minutes >= 60 else speech.count_phrase(minutes, "minute"))
        return f"{amount}: {title}, {speech.humanize_time(start.isoformat())} to {end.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower()}."
    if g.get("ed_at"):
        m = re.fullmatch(r"(\d{1,2})(?::(\d\d))? ?(am|pm)?", g["ed_at"])
        hour = int(m.group(1)) % 12 + (12 if (m.group(3) == "pm" or (not m.group(3) and int(m.group(1)) < 8)) else 0)
        days = [now.date() + dt.timedelta(days=1)] if g.get("ed_day") == "tomorrow" else \
               [now.date()] if g.get("ed_day") == "today" else [now.date(), now.date() + dt.timedelta(days=1)]
        for day in days:
            for start, _end, title in events:
                if start.date() == day and start.hour == hour and (not m.group(2) or start.minute == int(m.group(2))):
                    return f"{title[:1].upper() + title[1:]}, {speech.humanize_time(start.isoformat())}."
        return f"Nothing on your calendar at {g['ed_at']}."
    if g.get("ed_who"):
        # His calendar's lines that name them; None when none does - their
        # week may be on a calendar of theirs she cannot see.
        who = re.sub(r"^(?:my|our) ", "", g["ed_who"])
        when = g.get("ed_who_when") or "this week"
        weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        if when in weekdays:
            first = now.date() + dt.timedelta(days=(weekdays.index(when) - now.weekday()) % 7)
            last = first
        else:
            first = now.date() + dt.timedelta(days=1 if when == "tomorrow" else 7 - now.weekday() if when == "next week" else 0)
            last = first if when in ("today", "tomorrow") else first + dt.timedelta(days=6)
        hits = [(start, title) for start, _end, title in events
                if first <= start.date() <= last and re.search(r"\b" + re.escape(who) + r"\b", title, re.IGNORECASE)]
        if not hits:
            # "My son has soccer practice tuesdays at 5" is a note, not a hold.
            day_name = first.strftime("%A").casefold() if first == last else ""
            for row in _notes():
                said = " ".join(str(row.get("text") or "").split())
                if re.search(r"\b" + re.escape(who) + r"\b", said, re.I) and (
                        not day_name or re.search(r"\b" + day_name + r"s?\b|\bevery (?:day|weekday)\b", said, re.I)) \
                        and re.search(r"\b(?:has|have|goes to|go to)\b", said, re.I):
                    return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
            return None
        said = speech.and_list([f"{t[:1].upper() + t[1:]}, {speech.humanize_time(st.isoformat())}" for st, t in hits[:5]])
        return said + "."
    if g.get("ed_after"):
        m = re.fullmatch(r"(\d{1,2})(?::(\d\d))? ?(am|pm)?", g["ed_after"])
        hour = int(m.group(1)) % 12 + (12 if (m.group(3) == "pm" or (not m.group(3) and int(m.group(1)) < 8)) else 0)
        day = now.date() + dt.timedelta(days=1 if g.get("ed_after_day") == "tomorrow" else 0)
        after = [e for e in events if e[0].date() == day and (e[0].hour, e[0].minute) > (hour, int(m.group(2) or 0))]
        if not after:
            return f"Nothing on your calendar after {g['ed_after']}{' tomorrow' if day != now.date() else ''}."
        start, _end, title = after[0]
        return f"{title[:1].upper() + title[1:]}, {speech.humanize_time(start.isoformat())}."
    if g.get("ed_busy"):
        nxt = "next week" in text.casefold()
        monday = now.date() - dt.timedelta(days=now.weekday())
        first = monday + dt.timedelta(days=7) if nxt else now.date()
        last = monday + dt.timedelta(days=13 if nxt else 6)
        counts = {}
        for start, _end, _t in events:
            if first <= start.date() <= last:
                counts[start.date()] = counts.get(start.date(), 0) + 1
        if g["ed_busy"] == "busiest":
            if not counts:
                return "Nothing on your calendar " + ("next week." if nxt else "for the rest of this week.")
            day, n = max(sorted(counts.items()), key=lambda r: r[1])
            return f"{day.strftime('%A')}, with {speech.count_phrase(n, 'thing')} on it."
        free = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)
                if first + dt.timedelta(days=i) not in counts]
        if free:
            return f"{free[0].strftime('%A')} - nothing on it at all."
        day, n = min(sorted(counts.items()), key=lambda r: r[1])
        return f"{day.strftime('%A')}, with {speech.count_phrase(n, 'thing')} on it."
    return None


_SAVED_NOTE = re.compile(r"^i (?:just )?(?:saved|put away|set aside|put|moved|transferred) \$?(?P<amt>\d[\d,]*(?:\.\d\d)?)")
_SAVE_GOAL = re.compile(r"^(?:i(?:'m| am)? (?:want to|wanna|need to|trying to|going to|gonna|plan to|saving up|saving) (?:save (?:up )?)?"
                        r"|my savings goal is |my goal is to save )\$?(?P<amt>\d[\d,]*(?:\.\d\d)?)(?P<k>k)?(?: dollars| bucks)?"
                        r"(?: (?:for|towards?) (?P<for>(?:a |an |my |the )?[a-z][a-z ]{1,30}?))?(?: by .*)?$")


def _save_by(words: str, today):
    """The date a goal is due "by": a date he named, or a bare month read as
    its first day ("by December" is before December). None when unsure."""
    import datetime as dt
    try:
        when = _named_date(words, today) or _his_date(words, today)
    except Exception:
        when = None
    if when is not None:
        return when
    month = re.fullmatch(r"(?:the )?(?:start of |beginning of )?(" + "|".join(_MONTHS) + r")(?: (\d{4}))?", words.strip())
    if not month:
        return None
    number = _MONTHS.index(month.group(1)) + 1
    year = int(month.group(2)) if month.group(2) else today.year + (number <= today.month)
    return dt.date(year, number, 1)


def _saved(text: str) -> str | None:
    """What he told her he saved, against the goal he told her. None when
    he has said neither."""
    import datetime as dt
    from aletheia import localtime
    g = _groups("saved", text)
    window = (g.get("saved_w") or "").strip()
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    start = {"this week": now - dt.timedelta(days=now.weekday()), "this month": now.replace(day=1)}.get(window)
    total, goal, goal_by = 0.0, None, ""
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        m = _SAVED_NOTE.match(said)
        if m and (said.startswith("i saved") or re.search(r"savings|fund|\bfor\b", said)):
            try:
                at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
            except ValueError:
                at = now
            if not start or at.date() >= start.date():
                total += float(m.group("amt").replace(",", ""))
            continue
        m = _SAVE_GOAL.match(said)
        if m and goal is None:
            amount = float(m.group("amt").replace(",", "")) * (1000 if m.group("k") else 1)
            goal = (amount, re.sub(r"^my ", "your ", (m.group("for") or "").strip()))
            by = re.search(r" by (.+)$", said)
            goal_by = by.group(1).strip() if by else ""
    if not total and not goal:
        return None
    span = f" {window}" if window and window not in ("so far", "in total", "total") else ""
    if not goal:
        if g.get("saved_more") or g.get("saved_close") or "left" in text:
            return f"You've told me you saved {_money(total)}, but not what you're saving towards."
        return f"{_money(total)}{span}, from what you've told me."
    amount, for_ = goal
    aim = f"your {_money(amount)} goal" + (f" for {for_}" if for_ else "")
    if total >= amount:
        return f"You've saved {_money(total)} - that's {aim} reached."
    left = amount - total
    per = g.get("saved_per")
    if per:
        due = _save_by(goal_by, now.date()) if goal_by else None
        if due is None:
            return (f"{_money(left)} to go toward {aim}, but you didn't tell me by when. "
                    "Say \"I want to save 1000 dollars by December\" and I'll work it out.")
        span_days = (due - now.date()).days
        if span_days <= 0:
            return f"Your goal date has passed, and {_money(left)} is still to go toward {aim}."
        count = {"day": span_days, "week": span_days / 7, "month": span_days / 30.44}[per]
        each = left / max(count, 1)
        return (f"About {_money(round(each, 2))} a {per} - {_money(left)} to go toward {aim} "
                f"by {due.strftime('%B')} {due.day}.")
    return f"You've saved {_money(total)}{span} toward {aim}, so {_money(left)} to go, from what you've told me."


def _next_due(text: str) -> str | None:
    """The next reminder for the thing he names. None when no reminder
    names it - a model may know how often it should be done."""
    from aletheia import speech
    g = _groups("next_due", text)
    asked = (g.get("next_due") or g.get("next_due2") or "").strip()
    words = [w for w in re.findall(r"[a-z0-9]+", asked.casefold()) if w not in _STOP_WORDS]
    if not words:
        return None
    for at, said, store in _coming():
        if store == "reminder" and all(re.search(rf"\b{re.escape(w[:5])}", said.casefold()) for w in words):
            return f"Your next reminder to {said.rstrip('.')} is {speech.humanize_time(at.isoformat())}."
    return None


def _missed_reminders(text: str = "") -> str | None:
    """Reminders that went off and he has not seen: the unread notices
    titled Reminder, said by their bodies."""
    from aletheia import notifications, speech
    try:
        rows = [n for n in notifications.all_notifications(state="UNREAD", limit=200)
                if str(n.get("title") or "") == "Reminder"]
    except Exception:
        return None
    if not rows:
        return "No - nothing I reminded you of is still unseen."
    said = [f"{str(n.get('body') or '').strip().rstrip('.')} ({speech.humanize_time(str(n.get('created_at') or ''))})"
            for n in rows[:4]]
    return (f"{speech.count_phrase(len(rows), 'reminder')} you haven't seen: " + speech.and_list(said)
            + (f", and {len(rows) - 4} more" if len(rows) > 4 else "") + ".")


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


_FOR_HOME = re.compile(r"^remind me (?P<how>to|that) (?P<what>.+?) when i(?:'m| am| get| arrive| come)? (?:get |am |come )?"
                       r"(?:back )?(?:home|back)$", re.I)


def _home_reminders() -> list[str]:
    """What he asked to be told when he got home, since he last said he
    was (2026-10-08: she said she couldn't, and "I'm home" said nothing)."""
    import datetime as dt
    arrived = ""
    try:
        from aletheia import converse
        pattern = dict(PATTERNS)["arrival"]
        for turn in converse._thread():
            if pattern.match(_tidy(str(turn.get("you") or ""))):
                arrived = max(arrived, str(turn.get("at") or ""))
    except Exception:  # noqa: BLE001
        pass
    since = None
    try:
        since = dt.datetime.fromisoformat(arrived.replace("Z", "+00:00")) if arrived else None
    except ValueError:
        since = None
    out = []
    for row in reversed(_notes()):
        m = _FOR_HOME.match(" ".join(str(row.get("text") or "").split()))
        if not m:
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if since is None or at > since:
            out.append(m.group("what") if m.group("how") == "to" else "that " + m.group("what"))
    return out


def _arrival() -> str:
    from aletheia import speech
    try:
        from aletheia import needs_you
        rows = needs_you.items()
    except Exception:
        rows = []
    home = _home_reminders()
    told = (f" You asked me to remind you when you got home: {speech.and_list([speech._yours(h) for h in home])}."
            if home else "")
    if rows:
        return f"Welcome back.{told} {speech.count_phrase(len(rows), 'thing')} waiting on you."
    return f"Welcome back.{told}" + ("" if told else " Nothing's waiting on you.")


def _farewell(text: str) -> str:
    low = str(text or "").lower()
    if any(w in low for w in ("night", "sleep", "bed")):
        return "Goodnight. I'll keep going quietly."
    # "Leaving the gym" is on his way back, not out (2026-10-08).
    leaving_a_place = re.search(r"\b(?:leaving|done at|finished at|walking out of|out of) the [a-z' ]+$", low)
    if re.search(r"\b(?:gym|run|jog|walk)\b", low) and not leaving_a_place:
        return "Have a good one. I'll keep at it while you're out."
    # "I'm heading home" was answered "I'll keep at it while you're out"
    # (2026-10-07) - he is coming back, and what waits is what he wants.
    if re.search(r"\b(?:heading|going|on my way|way) home\b|\b(?:leaving work|leaving the office|off work|done for the day)\b", low) \
            or leaving_a_place:
        try:
            from aletheia import needs_you
            from aletheia import speech
            rows = needs_you.items()
        except Exception:
            rows = []
        if rows:
            return f"Safe trip home. {speech.count_phrase(len(rows), 'thing')} waiting on you when you're in."
        return "Safe trip home. Nothing's waiting on you."
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
    if "op2" in g:
        g.update(a=g["a2"], op={"×": "x"}.get(g["op2"], g["op2"]), b=g["b2"])

    def num(s: str) -> float:
        digits, _, scale = str(s).replace(",", "").partition(" ")
        return float(digits) * {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}.get(scale, 1)

    def said(v: float) -> str:
        # "100 divided by 7" was read out as "14.28571429" (2026-10-07).
        if abs(v - round(v)) <= 1e-9:
            return f"{int(round(v)):,}"
        # "142.8571" is four digits nobody wanted out loud (2026-10-07):
        # past the point, two places is what a person says.
        if abs(v) >= 1:
            return f"{round(v, 2):,.2f}".rstrip("0").rstrip(".")
        return f"{round(v, 4):,}".rstrip("0").rstrip(".")
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
        if g.get("deg") or g.get("deg2"):
            dst = (g.get("deg_to") or g["deg_to2"]).lower()
            g = dict(g, n=g.get("deg") or g["deg2"], to=dst, **{"from": "celsius" if dst in ("fahrenheit", "f") else "fahrenheit"})
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


def _planned_for(day: str) -> str | None:
    """The meal plan's line for one day ("Monday: chicken"), or None."""
    import datetime as dt
    from aletheia import lists, localtime
    try:
        rows = lists.items("meal plan") or []
    except Exception:
        return None
    if day in ("today", "tonight", "tomorrow"):
        when = dt.datetime.now(localtime.operator_tz()).date() + dt.timedelta(days=1 if day == "tomorrow" else 0)
        day = when.strftime("%A").lower()
    hits = [r.split(":", 1)[1].strip() for r in rows if r.casefold().startswith(day + ":")]
    from aletheia import speech
    return speech.and_list(hits) if hits else None


#: USDA safe minimum internal temperatures, Fahrenheit (rest 3 minutes where noted).
_SAFE_TEMPS = (
    (r"chicken|turkey|poultry|duck|ground turkey|ground chicken|leftovers|casserole", 165, ""),
    (r"ground beef|ground pork|burger|hamburger", 160, ""),
    (r"egg", 160, " for egg dishes - or until the yolk and white are firm"),
    (r"pork|ham|beef|steak|lamb|veal|roast", 145, ", then rest it 3 minutes"),
    (r"fish|salmon|tuna|shrimp", 145, ""),
)


def _cook_temp(text: str) -> str | None:
    """A safe cooking temperature or how long to boil an egg, from a table."""
    g = _groups("cook_temp", text)
    if g.get("cook_temp") or g.get("cook_temp2"):
        food = g.get("cook_temp") or g["cook_temp2"]
        for pattern, f, tail in _SAFE_TEMPS:
            if re.search(rf"\b(?:{pattern})", food):
                c = round((f - 32) * 5 / 9)
                return (f"{f} degrees Fahrenheit, {c} Celsius, inside at the thickest part{tail}. "
                        "That's the USDA's safe minimum.")
        return None
    kind = (g.get("egg_boil") or g.get("egg_kind") or "").strip()
    if kind == "soft":
        return "About 6 minutes in boiling water for a soft-boiled egg, then into cold water."
    if kind == "medium":
        return "About 8 minutes in boiling water for a jammy middle, then into cold water."
    if kind == "hard" or "boil" in str(text).casefold():
        return ("About 10 to 12 minutes in boiling water for hard-boiled - 6 for soft, 8 for jammy - "
                "then into cold water.")
    return None


def _pick_for_me(text: str) -> str | None:
    """Something to watch or read off his own list, or his favourite place
    to eat. None when he keeps nothing to pick from - then it is a question
    a model can think about (2026-10-07: "recommend a movie" with Arrival on
    his watch list went to the planner)."""
    import secrets
    from aletheia import lists
    g = _groups("pick_for_me", text)
    if g.get("pick_eat"):
        for row in _notes():
            m = re.search(r"\bmy fav(?:ou?rite)? (?:restaurant|place to eat|takeout|takeaway) is (.+?)\.?$",
                          str(row.get("text") or ""), re.I)
            if m:
                return f"How about {m.group(1).strip()}? You told me it's your favorite."
        return None
    want = "read" if g.get("pick_read") or g.get("pick_read2") else "watch"
    try:
        rows = [t for h in lists.all_lists() if lists.kind_of(h["name"]) == want for t in (lists.items(h["name"]) or [])]
    except Exception:
        return None
    if not rows:
        return None
    pick = secrets.choice(rows)
    return f"From your {'reading' if want == 'read' else 'watch'} list: {pick}." + (
        f" There {'is' if len(rows) == 2 else 'are'} {len(rows) - 1} more on it." if len(rows) > 1 else "")


def _meal_plan(text: str) -> str | None:
    """His meal plan, or one day of it, from the list he keeps."""
    from aletheia import lists, speech
    g = _groups("meal_plan", text)
    day = (g.get("mp_day") or g.get("mp_day2") or g.get("mp_day3") or "").strip()
    # "What am I making for dinner" (2026-10-07: to a model) is tonight's.
    if not day and re.match(r"what (?:am i|are we) ", text.casefold()):
        day = "tonight"
    try:
        rows = lists.items("meal plan")
    except Exception:
        return None
    if rows is None:
        # no plan kept: "what am I having for dinner tomorrow" is not ours
        return None if day else "You don't have a meal plan yet. Say \"add chicken to my meal plan for Monday\"."
    if day and day != "this week":
        planned = _planned_for(day)
        said = {"today": "today", "tonight": "tonight", "tomorrow": "tomorrow"}.get(day, f"on {day.capitalize()}")
        return f"{planned[:1].upper() + planned[1:]} {said}." if planned else f"Nothing on your meal plan {said}."
    if not rows:
        return "Your meal plan is empty."
    return f"Your meal plan: {'; '.join(rows[:7])}" + (f"; and {len(rows) - 7} more." if len(rows) > 7 else ".")


def _meal_idea(meal: str) -> str:
    """One idea, from what he told her he likes when he told her anything."""
    import secrets
    meal = {"supper": "dinner", "tea": "dinner"}.get(str(meal or "dinner").strip(), str(meal or "dinner").strip())
    if meal == "dinner":
        planned = _planned_for("today")
        if planned:
            return f"Your meal plan says {planned}."
    for row in _notes():
        said = str(row.get("text") or "")
        liked = re.search(r"\bmy fav(?:ou?rite)? (?:food|meal|dinner|dish) is (.+?)\.?$", said, re.IGNORECASE)
        if liked and meal != "breakfast":
            return f"How about {liked.group(1).strip()}? You told me that's your favorite."
    return f"How about {secrets.choice(_MEALS.get(meal, _MEALS['dinner']))}? Just an idea - I don't know what's in the fridge."


def _parked(at: str = "") -> str:
    """The newest note that says where the car is - at the place he names,
    when he names one ("where did I park at the airport")."""
    at = " ".join(str(at or "").casefold().split())
    for row in _notes():
        said = str(row.get("text") or "")
        if at and not re.search(rf"\b{re.escape(at)}\b", said.casefold()):
            continue
        if re.search(r"\b(?:parked|my car is|the car is)\b", said, re.IGNORECASE):
            # "You told me: i parked on level 3" was his note read back in
            # his own first person (2026-10-07).
            from aletheia import speech
            hers = speech.as_she_says_it(said.strip()).rstrip(".")
            if re.match(r"(?:you|your car) ", hers):
                return hers[0].upper() + hers[1:] + "."
            return f"You told me: {hers}."
    if at:
        return f"You haven't told me where you parked at the {at}."
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
    said = g.get("sun") or g.get("sun2") or g.get("sun3") or g.get("sun4") or g.get("sun5") or g.get("sun6") or ""
    which = "rise" if any(w in said for w in ("rise", "come up", "light")) else "set"
    when = g.get("sunday") or g.get("sunday2") or g.get("sunday3") or g.get("sunday4") or g.get("sunday5") or ""
    day = "tomorrow" if when == "tomorrow" else ""
    return weather.spoken_sun(which, day, until=True) if g.get("sun6") else weather.spoken_sun(which, day)


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


def _sums_more(text: str) -> str | None:
    """Sales tax, plain saving, a year counted back or forward, and a unit
    conversion asked as "how tall is". Arithmetic said as arithmetic."""
    import datetime as dt
    g = _groups("sums_more", text)
    if g.get("tax"):
        rate, on = float(g["tax"]), float(g["tax_on"].replace(",", ""))
        tax = round(on * rate / 100 + 1e-9, 2)
        return f"${tax:,.2f} tax, ${on + tax:,.2f} total."
    if g.get("save"):
        words = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10}
        n = words.get(g["save_n"]) or int(g["save_n"])
        per_year = {"day": 365, "week": 52, "month": 12, "year": 1}[g["save_per"]]
        unit = g["save_u"].rstrip("s")
        periods = n * {"year": per_year, "month": per_year / 12, "week": per_year / 52}[unit]
        total = float(g["save"].replace(",", "")) * periods
        return (f"${total:,.0f}" if total == int(total) else f"${total:,.2f}") + ", before any interest."
    if g.get("yr_n") or g.get("yr_n2"):
        n = int(g.get("yr_n") or g.get("yr_n2"))
        year = dt.date.today().year + (-n if g.get("yr_dir") == "ago" else n)
        return f"{year}." if year > 0 else None
    if g.get("conv"):
        # a height is said in feet AND inches: "5 feet 11", not "5.91 feet"
        h = re.fullmatch(r"(?:a |an )?([\d.]+) ?(cm|centimeters?|centimetres?|m|meters?|metres?)", g["conv"])
        if h and g["conv_to"].strip() in ("feet", "foot", "feet and inches", "ft"):
            inches = float(h.group(1)) / (2.54 if h.group(2).startswith("c") else 0.0254)
            feet, rest = divmod(round(inches), 12)
            return f"About {feet} feet {rest} inches." if rest else f"About {feet} feet."
        return answer(f"what's {g['conv']} in {g['conv_to']}")
    return None


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
        bill = float((g.get("bill") or g.get("bill2") or g.get("bill3") or g.get("bill4")).replace(",", ""))
        raw = g.get("ways") or g.get("ways2") or g.get("ways3") or g.get("ways4")
        ways = int(raw) if raw.isdigit() else _WAYS[raw]
    except (AttributeError, KeyError, ValueError):
        return None
    if ways < 2:
        return None
    if g.get("bill4"):
        pct = int(g.get("tip_pct") or 20)
        total = bill * (1 + pct / 100)
        return (f"With a {pct}% tip, {_money(round(total / ways, 2))} each - {_money(round(total, 2))} in all."
                + ("" if g.get("tip_pct") else " Say \"with a 15% tip\" for a different one."))
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


def _just_added(turns: int = 8, text: str = "") -> str | None:
    """Her last "Added to the shopping list: bread." or "Added a task: X."
    in the conversation, said back. None without one in the last few turns:
    a model may have added it."""
    try:
        from aletheia import converse
        thread = list(converse._thread() or [])[-turns:]
    except Exception:
        return None
    if _groups("just_added", text).get("ja_do") if text else False:
        # the turn before this one, his words and what came of them
        for turn in reversed(thread):
            you = " ".join(str(turn.get("you") or "").split())
            her = " ".join(str(turn.get("her") or "").split())
            if you and not re.match(r"what did i just\b", you, re.I):
                return f"You said \"{you}\", and I answered: {her}"
        return None
    for turn in reversed(thread):
        her = " ".join(str(turn.get("her") or "").split())
        m = re.match(r"Added (to (?:the|your) [a-z' ]+?): (.+?)\.?$", her)
        if m:
            return f"You just added {m.group(2)} {m.group(1).replace('to the ', 'to your ', 1)}."
        m = re.match(r"Added a task: (.+?)\.?$", her)
        if m:
            return f"You just added a task: {m.group(1)}."
    return None


def _on_days(text: str) -> str | None:
    """"What do I do on Fridays": the coming Friday's calendar and
    reminders, and his notes about Fridays."""
    day = _groups("on_days", text).get("od") or ""
    if not day:
        return None
    said = _agenda_and_reminders(day)
    told = []
    for row in _notes():
        note = " ".join(str(row.get("text") or "").split())
        if re.search(rf"\b{day}s\b|\bevery {day}\b", note, re.I):
            told.append(note.rstrip("."))
    if told:
        from aletheia import speech
        extra = "You told me " + speech.and_list([speech.as_she_says_it(t) for t in told[:3]]) + "."
        return f"{said} {extra}" if said else extra
    return said


def _until_leave() -> str | None:
    """His next reminder to leave. Without one he hasn't said when, and
    she says how to tell her."""
    import datetime as dt
    from aletheia import localtime, speech
    now = dt.datetime.now(localtime.operator_tz())
    try:
        coming = _coming()
    except Exception:
        return None
    for at, said, store in coming:
        if store == "reminder" and re.match(r"(?:leave|head out|go)\b", said.casefold()):
            minutes = int((at - now).total_seconds() // 60)
            if minutes < 0:
                continue
            span = (f"{minutes} minute{'s' if minutes != 1 else ''}" if minutes < 60
                    else f"{minutes // 60} hour{'s' if minutes // 60 != 1 else ''}"
                    + (f" and {minutes % 60} minutes" if minutes % 60 else ""))
            return f"{span} - your reminder to {said.rstrip('.')} is {speech.humanize_time(at.isoformat())}."
    return "You haven't told me when you need to leave. Say \"remind me to leave at\" and the time, and I'll keep it."


def _where_was_i() -> str | None:
    """The newest "I'm working on X" he told her. None without one: he may
    have said it to a model."""
    import datetime as dt
    from aletheia import localtime, speech
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        m = re.fullmatch(r"i'?m (?:still |just )?(working on|in the middle of|halfway through) (.+?)\.?", said, re.I)
        if not m:
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(localtime.operator_tz())
            when = " " + speech.humanize_time(at.isoformat())
        except ValueError:
            when = ""
        return f"You told me{when} you were {m.group(1).casefold()} {m.group(2)}."
    return None


def _date_what(text: str) -> str | None:
    """"What's next Friday": the date, then the calendar on it. "Next" a day
    or two away names both, because people mean either."""
    import datetime as dt
    from aletheia import localtime
    low = " ".join(str(text).casefold().split()).strip(" ?.")
    today = dt.datetime.now(localtime.operator_tz()).date()
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    m = re.search(r"(this|next) (\w+day)$", low)
    try:
        if m:
            ahead = (days.index(m.group(2)) - today.weekday()) % 7 or 7
            when = today + dt.timedelta(days=ahead)
            name = m.group(2).capitalize()
            if m.group(1) == "next" and ahead <= 2:
                later = when + dt.timedelta(days=7)
                lead = (f"This {name} is {when.strftime('%B')} {when.day}, and the one after is "
                        f"{later.strftime('%B')} {later.day}. ")
                when = later
            else:
                lead = f"{m.group(1).capitalize()} {name} is {when.strftime('%B')} {when.day}. "
        else:
            day = int(re.search(r"\d{1,2}", low).group(0))
            when = dt.date(today.year, today.month, day)
            if when < today:
                when = dt.date(today.year + (today.month == 12), today.month % 12 + 1, day)
            lead = f"The {low.rsplit(' ', 1)[-1]} is a {when.strftime('%A')}, {when.strftime('%B')} {when.day}. "
    except (ValueError, AttributeError):
        return None
    agenda = _agenda_on(f"{when.strftime('%B').casefold()} {when.day}")
    if agenda is None:
        return None
    if agenda.startswith("Nothing"):
        return lead + f"Nothing's on your calendar on {when.strftime('%B')} {when.day}."
    return lead + "On it: " + agenda.split(": ", 1)[1]


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
        # "How long since I called mom" (2026-10-07: a model): a thing he
        # did, read from his notes the way "when did I last" is.
        m = re.fullmatch(r"(?:i |you )?(?:last )?(?P<v>[a-z]+(?:ed| up| off)|fed|gave|cut) (?P<o>[a-z][a-z' ]{1,40})", words.strip())
        if m:
            base = _base_verb(m.group("v"))
            if base:
                return _did_last(f"when did i last {base} {m.group('o')}")
        # "How many days since my birthday" with none told (2026-10-08: to
        # a model) has one honest answer.
        whose = re.fullmatch(r"(?:my|our) (birthday|anniversary|wedding anniversary)", words.strip())
        if whose:
            return (f"You haven't told me when your {whose.group(1)} is. Say \"my {whose.group(1)} is\" and the date, "
                    "and I'll remember it.")
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


_CONSTANTS = {
    "pi": "Pi is about 3.14159 - 3.14159265358979 to fourteen places.",
    "the speed of light": "About 299,792 kilometers a second - roughly 186,282 miles a second.",
    "the golden ratio": "About 1.618.",
    "absolute zero": "Minus 273.15 degrees Celsius - minus 459.67 Fahrenheit.",
    "the boiling point of water": "100 degrees Celsius, 212 Fahrenheit, at sea level.",
    "the freezing point of water": "0 degrees Celsius, 32 Fahrenheit.",
}


_CAPITALS = {
    # countries
    "afghanistan": "Kabul", "argentina": "Buenos Aires", "australia": "Canberra", "austria": "Vienna", "belgium": "Brussels",
    "brazil": "Brasília", "canada": "Ottawa", "chile": "Santiago", "china": "Beijing", "colombia": "Bogotá", "cuba": "Havana",
    "czech republic": "Prague", "czechia": "Prague", "denmark": "Copenhagen", "egypt": "Cairo", "england": "London",
    "ethiopia": "Addis Ababa", "finland": "Helsinki", "france": "Paris", "germany": "Berlin", "ghana": "Accra",
    "greece": "Athens", "hungary": "Budapest", "iceland": "Reykjavík", "india": "New Delhi", "indonesia": "Jakarta",
    "iran": "Tehran", "iraq": "Baghdad", "ireland": "Dublin", "israel": "Jerusalem", "italy": "Rome", "jamaica": "Kingston",
    "japan": "Tokyo", "kenya": "Nairobi", "mexico": "Mexico City", "morocco": "Rabat", "netherlands": "Amsterdam",
    "new zealand": "Wellington", "nigeria": "Abuja", "north korea": "Pyongyang", "norway": "Oslo", "pakistan": "Islamabad",
    "peru": "Lima", "philippines": "Manila", "poland": "Warsaw", "portugal": "Lisbon", "russia": "Moscow",
    "saudi arabia": "Riyadh", "scotland": "Edinburgh", "singapore": "Singapore", "south africa": "Pretoria, Cape Town and Bloemfontein - it has three",
    "south korea": "Seoul", "korea": "Seoul", "spain": "Madrid", "sweden": "Stockholm", "switzerland": "Bern",
    "taiwan": "Taipei", "thailand": "Bangkok", "turkey": "Ankara", "ukraine": "Kyiv", "united kingdom": "London",
    "uk": "London", "great britain": "London", "united states": "Washington, D.C.", "usa": "Washington, D.C.",
    "us": "Washington, D.C.", "america": "Washington, D.C.", "venezuela": "Caracas", "vietnam": "Hanoi", "wales": "Cardiff",
    # US states
    "alabama": "Montgomery", "alaska": "Juneau", "arizona": "Phoenix", "arkansas": "Little Rock", "california": "Sacramento",
    "colorado": "Denver", "connecticut": "Hartford", "delaware": "Dover", "florida": "Tallahassee", "georgia": "Atlanta",
    "hawaii": "Honolulu", "idaho": "Boise", "illinois": "Springfield", "indiana": "Indianapolis", "iowa": "Des Moines",
    "kansas": "Topeka", "kentucky": "Frankfort", "louisiana": "Baton Rouge", "maine": "Augusta", "maryland": "Annapolis",
    "massachusetts": "Boston", "michigan": "Lansing", "minnesota": "Saint Paul", "mississippi": "Jackson",
    "missouri": "Jefferson City", "montana": "Helena", "nebraska": "Lincoln", "nevada": "Carson City",
    "new hampshire": "Concord", "new jersey": "Trenton", "new mexico": "Santa Fe", "new york": "Albany",
    "north carolina": "Raleigh", "north dakota": "Bismarck", "ohio": "Columbus", "oklahoma": "Oklahoma City",
    "oregon": "Salem", "pennsylvania": "Harrisburg", "rhode island": "Providence", "south carolina": "Columbia",
    "south dakota": "Pierre", "tennessee": "Nashville", "texas": "Austin", "utah": "Salt Lake City", "vermont": "Montpelier",
    "virginia": "Richmond", "washington": "Olympia", "washington state": "Olympia", "west virginia": "Charleston",
    "wisconsin": "Madison", "wyoming": "Cheyenne",
}


def _capital(text: str) -> str | None:
    """A capital from the fixed table; anything else is a model's question."""
    g = _groups("capital", text)
    place = " ".join(str(g.get("cap") or g.get("cap2") or "").replace(".", "").split())
    city = _CAPITALS.get(place)
    if not city:
        return None
    # "Georgia" is a state and a country (2026-10-07): say which.
    if place == "georgia":
        return "Atlanta, for the state - the country's capital is Tbilisi."
    return city if city.endswith(".") else f"{city}."


_HOW_TO = {
    "reminder": ('Just say "remind me at 3 to call the dentist" - or "every Monday at 9" for one that repeats.',
                 'Say "cancel my reminder to call the dentist". "What reminders do I have" reads them first.',
                 'Say "what reminders do I have".'),
    "alarm": ('Say "wake me up at 6" or "set an alarm for 7 tomorrow".',
              'Say "turn off my 7 am alarm".', 'Say "what alarms do I have".'),
    "timer": ('Say "set a timer for 10 minutes".', 'Say "cancel the timer".', 'Say "how long is left on my timer".'),
    "task": ('Say "add call the vet to my list".', 'Say "delete the task call the vet", or "I finished call the vet" to tick it off.',
             'Say "what\'s on my list".'),
    "note": ('Say "note that the plumber is coming Friday".', 'Say "delete my note about the plumber".',
             'Say "what notes do I have", or "what did I tell you about the plumber".'),
    "list": ('Say "add milk to my shopping list", or "make a packing list" for a new one.',
             'Say "take milk off my shopping list".', 'Say "what\'s on my shopping list".'),
    "event": ('Say "add a dentist appointment on Tuesday at 10" and I\'ll put a hold on your calendar.',
              "I can't take things off your calendar yet - only add holds. Remove it in your calendar itself.",
              'Say "what\'s on my calendar tomorrow".'),
    "stopwatch": ('Say "start a stopwatch".', 'Say "stop the stopwatch".', 'Say "how long has the stopwatch been running".'),
}


def _how_to(text: str) -> str | None:
    """"How do I add a reminder": the sentence that does it, which is the
    whole of the answer - nothing to install, nothing to open."""
    g = _match_of("how_to", text)
    verb, what = g.get("howto") or "", (g.get("howto_what") or "").rstrip("s")
    what = {"to do": "task", "todo": "task", "shopping list": "list", "calendar event": "event", "appointment": "event",
            "hold": "event"}.get(what, what)
    said = _HOW_TO.get(what)
    if not said:
        return None
    which = 1 if verb in ("cancel", "delete", "remove", "turn off", "stop") else \
        2 if verb in ("check", "see", "read", "hear", "find") else 0
    return said[which]


def _dur_convert(text: str) -> str | None:
    """A length of time in another unit, with the remainder said the way a
    person says it: "1000 seconds" is "16 minutes and 40 seconds"."""
    g = _match_of("dur_convert", text)
    unit = {"sec": "second", "min": "minute", "hr": "hour"}
    src = g.get("du") or g.get("du2") or ""
    src = unit.get(src.rstrip("s"), src.rstrip("s"))
    dst = (g.get("dt") or g.get("dt2") or "").rstrip("s")
    n = float((g.get("dn") or g.get("dn2") or "0").replace(",", ""))
    if src not in _SECONDS or dst not in _SECONDS:
        return None
    value = n * _SECONDS[src] / _SECONDS[dst]
    said = f"{_number_said(value)} {dst}{'' if value == 1 else 's'}"
    whole = int(value)
    if _SECONDS[src] < _SECONDS[dst] and whole >= 1 and abs(value - round(value)) > 1e-9:
        rest = round((value - whole) * _SECONDS[dst] / _SECONDS[src])
        if 0 < rest:
            said = (f"{whole:,} {dst}{'' if whole == 1 else 's'} and {rest:,} {src}{'' if rest == 1 else 's'}")
    return said[:1].upper() + said[1:] + "."


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
    "procrastinating": ("Pick the smallest piece of it and do just that for five minutes. Say \"start a focus "
                        "session\" and I'll time it."),
    "unmotivated": "You've started harder things than whatever this is. Pick the smallest piece and do just that.",
    "distracted": "Say \"start a focus session\" and I'll hold the time for you. Put the phone face down.",
    "stuck": "Tell me what you're stuck on. Saying it out loud is half of it.",
    "thirsty": "Have a glass of water. Say \"I drank a glass of water\" and I'll keep count.",
    "cold": "Grab a layer, or turn the heat up a notch.",
    "freezing": "Grab a layer, or turn the heat up a notch.",
    "hot": "Get some water and some air. Hot days are worth taking slowly.",
    "nervous": ("That's normal before something that matters - it means you care. Tell me what's coming up and I'll "
                "make sure nothing about it is left to chance."),
    "scared": "I'm here. Tell me what's going on and we'll take it one step at a time.",
    "worried": "Tell me what's on your mind. If there's something to do about it, I'll help you do it.",
    "running late": "Want them to know? Say \"text\" and the name and what to say, like \"text Sam I'm running late\".",
    "late": "Want them to know? Say \"text\" and the name and what to say, like \"text Sam I'm running late\".",
    "stuck in traffic": "Want them to know? Say \"text\" and the name and what to say, like \"text Sam I'm stuck in traffic\".",
    "i can't focus": "Say \"start a focus session\" and I'll hold the time for you. Put the phone face down.",
    "i cant focus": "Say \"start a focus session\" and I'll hold the time for you. Put the phone face down.",
    "say something nice": "You keep starting things most people only talk about. That counts for a lot.",
}


def _feeling(text: str) -> str | None:
    g = _match_of("feeling", text)
    said = (g.get("feel") or g.get("feel2") or "").strip()
    # "I've been late" is a habit, not a text to send now
    if said in ("late", "running late", "stuck in traffic") and re.match(r"i(?:'ve| have) been\b", _tidy(text)):
        return None
    if "pep talk" in said or "motivation" in said:
        said = "motivate me"
    if said in ("cheer me up", "make me smile", "give me a compliment", "compliment me", "say something nice about me"):
        said = "say something nice"
    if re.match(r"(?:frustrated|annoyed|angry|mad|pissed off|fed up|sick of|so done)", said):
        return "That sounds frustrating. Tell me what's going wrong, and if it's something I can fix or take off you, I will."
    if re.match(r"i(?:'ve| have)|i (?:don'?t|do not) feel|i (?:think|might|may|feel like)", said):
        said = "sick"
    if re.match(r"i can'?t concentrate", said):
        said = "i can't focus"
    about = re.sub(r"^(?:about|for|before) (?:my |the |a |an )?", "", (g.get("feel_about") or "").strip())
    if about and said in ("nervous", "scared", "worried") and re.search(
            r"\b(?:interview|test|exam|presentation|meeting|date|flight|surgery|appointment|speech|game|race|first day"
            r"|review|audition|call|trip|wedding|procedure)\b", about):
        line = f"That's normal before your {about} - it means you care."
        if "interview" in about:
            when = _interview_when()
            if not when.startswith(("No interview", "I can't")):
                line += " " + when
        return line
    if said.startswith(("i'm having", "im having", "i had a")):
        return "I'm sorry - rough days end. Tell me one thing I can take off your plate and I'll do it."
    return _FEELINGS.get(said)


def _life_news(text: str) -> str | None:
    """What he tells her about his life, answered the way a person would -
    briefly, and without turning it into a task."""
    g = _match_of("life_news", text)
    if g.get("good"):
        return "Glad to hear it."
    if g.get("win") or g.get("win2"):
        return "Congratulations - that's brilliant news."
    if g.get("celebrate"):
        which = g["celebrate"]
        if which == "birthday":
            try:
                from aletheia import profile
                known = bool(profile.answer("birthday"))
            except Exception:  # noqa: BLE001
                known = True
            return "Happy birthday!" + ("" if known else
                                        " Say \"my birthday is\" and the date, and I'll remember it for next year.")
        return f"Happy {which}!"
    if g.get("setback"):
        return "I'm sorry. That one stings, and it's their loss. When you're ready, we'll go again."
    if g.get("quit"):
        return "That's a big step. Tell me what's next when you know, and I'll keep track of it."
    if g.get("theirs"):
        return f"That's lovely news - congratulations to your {g['theirs']}."
    if g.get("loss"):
        return ("I'm so sorry. Take whatever time you need - I'll keep things running, "
                "and anything that can wait will.")
    return None


def _related(word: str, which: str) -> str | None:
    try:
        from aletheia import dictionary
        return dictionary.spoken_related(word.strip(), which) or None
    except Exception:
        return None


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


def _who_coming(when: str) -> str | None:
    """Who he told her is coming or visiting - for the occasion he names,
    when he names one. None when no note says so."""
    from aletheia import speech
    words = [w for w in re.findall(r"[a-z0-9']+", str(when or "").casefold()) if w not in ("the", "my", "our", "a")]
    found = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if re.search(r"\b(?:is|are) (?:visiting|coming|staying with us|in town|flying in)\b", low) \
                and all(re.search(rf"\b{re.escape(w)}", low) for w in words):
            found.append(speech.as_she_says_it(said).rstrip("."))
        if len(found) >= 3:
            break
    return f"You told me: {speech.and_list(found)}." if found else None


def _opinion(text: str) -> str | None:
    """What he told her he thought of a thing, wants to try, or is thinking
    about - his own words read back. None for a thing he never mentioned."""
    from aletheia import speech
    low = _tidy(text)
    g = _groups("opinion", text)
    if g.get("opinion"):
        words = [w for w in re.findall(r"[a-z0-9]+", g["opinion"]) if w not in ("the", "that", "this", "my", "our")]
        for row in _notes():
            said = " ".join(str(row.get("text") or "").split())
            # "Dune was amazing" (2026-10-08) is what he thought too.
            if (re.match(r"(?:i|we) (?:really |absolutely |totally |kind of |kinda )?(?:loved|liked|hated|enjoyed|didn'?t|did not)\b",
                         said.casefold())
                    or re.search(r"\b(?:was|is) (?:really |so |pretty |kind of |kinda |very |super |just )?(?:amazing|great|good|bad"
                                 r"|terrible|boring|ok|okay|fine|awesome|incredible|meh|disappointing|overrated|underrated|fantastic"
                                 r"|excellent|awful|brilliant|slow|confusing|beautiful|hilarious|funny|sad|scary|mid)\b", said.casefold())) \
                    and words and all(re.search(rf"\b{re.escape(w)}", said.casefold()) for w in words):
                return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
        return None
    if g.get("rated"):
        words = [w for w in re.findall(r"[a-z0-9]+", g["rated"]) if w not in ("the", "that", "this")]
        for row in _notes():
            said = " ".join(str(row.get("text") or "").split())
            if re.match(r"i (?:rated|gave) ", said.casefold()) and all(re.search(rf"\b{re.escape(w)}", said.casefold()) for w in words):
                return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
        return None
    if g.get("liked"):
        kind = g["liked"].rstrip("s")
        kinds = {"movie": r"movie|film", "film": r"movie|film", "show": r"show|series", "book": r"book|novel",
                 "restaurant": r"restaurant|place", "place": r"place|restaurant", "song": r"song", "album": r"album", "game": r"game"}[kind]
        rows = [" ".join(str(r.get("text") or "").split()) for r in _notes()
                if re.match(r"(?:i|we) (?:really |absolutely |totally )?(?:loved|liked|enjoyed|rated)\b.*\b(?:" + kinds + r")\b",
                            str(r.get("text") or "").casefold())
                and not re.search(r"\b(?:didn'?t|did not|not)\b", str(r.get("text") or "").casefold())]
        if not rows:
            return None
        return f"You told me: {speech.and_list([speech.as_she_says_it(r).rstrip('.') for r in rows[:4]])}."
    if "thinking" in low:
        rows = [" ".join(str(r.get("text") or "").split()) for r in _notes()
                if re.match(r"(?:i'?m|i am|we'?re|we are) thinkin", str(r.get("text") or "").casefold())]
    else:
        rows = [" ".join(str(r.get("text") or "").split()) for r in _notes()
                if re.match(r"(?:i|we)(?:'d| would)? (?:want|wanna|like|love|need|really want) to (?:try|check out|go to|visit|see|travel to)",
                            str(r.get("text") or "").casefold())]
        if (g.get("want_try") or "").rstrip("s") not in ("", "place", "thing"):
            # "what restaurants do I want to try" is not "visit Japan someday"
            rows = [r for r in rows if not re.search(r"\b(?:visit|see|travel to)\b", r.casefold())]
        if g.get("want_go"):
            # a place, not a restaurant to try; and his bucket list too
            rows = [r for r in rows if re.search(r"\b(?:visit|go to|see|travel to)\b", r.casefold())]
            try:
                from aletheia import lists as _lists
                bucket = [str(i) for i in (_lists.items("bucket") or [])]
            except Exception:
                bucket = []
            if bucket:
                rows.append("your bucket list has " + speech.and_list(bucket[:4]))
    if not rows:
        return None
    said = [speech.as_she_says_it(r).rstrip(".") for r in rows[:4]]
    return f"You told me: {speech.and_list(said)}."


def _shop_added(text: str) -> str | None:
    """What went on his shopping list today (or yesterday, this week), still
    on it, newest last. From the store's own times; nothing is guessed."""
    import datetime as dt
    from aletheia import intercom, localtime, speech
    when = _groups("shop_added", text).get("shop_added") or "today"
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    start = {"today": today, "yesterday": today - dt.timedelta(days=1),
             "this week": today - dt.timedelta(days=today.weekday())}[when]
    end = today if when == "yesterday" else None
    try:
        rows = intercom._shopping_items()
    except Exception:
        return None
    added = []
    for w in rows:
        try:
            at = dt.datetime.fromisoformat(str(w.get("created_at") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if at >= start and (end is None or at < end):
            added.append(str(w.get("need") or w["id"])[:60])
    if not added:
        return f"Nothing still on your shopping list was added {when}."
    return f"Added {when} and still on the list: {speech.and_list(added)}."


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


def _next_meeting(until: bool = False) -> str | None:
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
    # "How long until my next meeting" was answered with when it is and
    # never how long (2026-10-07).
    if until:
        try:
            left = int((dt.datetime.fromisoformat(str(appointment.get("start"))) - now).total_seconds() // 60)
        except (TypeError, ValueError):
            left = None
        if left is not None and left >= 0:
            from aletheia import speech
            d, h, m = left // 1440, (left % 1440) // 60, left % 60
            span = (speech.count_phrase(m, "minute") if left < 60
                    else speech.count_phrase(h, "hour") + (f" and {speech.count_phrase(m, 'minute')}" if m and h < 3 else "")
                    if left < 1440
                    else speech.count_phrase(d, "day") + (f" and {speech.count_phrase(h, 'hour')}" if h and d < 3 else ""))
            return f"{span[:1].upper()}{span[1:]} - {title + ', ' if title else ''}{when}."
    # "lunch with Sam Friday at 12 pm." began in lower case (2026-10-07).
    return f"Next up: {title}, {when}." if title else f"You've got something {when}."


def _after_that() -> str | None:
    """"What's after that", once she has named something on his calendar:
    the next one after it. Only when her last answer named one."""
    import datetime as dt
    try:
        from aletheia import calendar, converse, speech
        turns = converse._thread()
        last = next((str(t.get("her") or "") for t in reversed(turns or []) if str(t.get("her") or "").strip()), "")
        now = dt.datetime.now(dt.timezone.utc)
        upcoming = []
        for event in calendar.all_events():
            if event.get("status") == "CANCELLED":
                continue
            try:
                start = calendar.parse_time(event["start"])
            except (KeyError, ValueError, TypeError):
                continue
            if start >= now:
                upcoming.append((start, str(event.get("title") or "").strip()))
    except Exception:
        return None
    upcoming.sort(key=lambda pair: pair[0])
    named = [i for i, (start, title) in enumerate(upcoming)
             if title and title.casefold() in last.casefold() and speech.humanize_time(start.isoformat()) in last]
    if not named:
        return None
    later = upcoming[max(named) + 1:]
    if not later:
        return "Nothing after that on your calendar."
    start, title = later[0]
    return f"After that: {title or 'something'}, {speech.humanize_time(start.isoformat())}."


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
    today = dt.datetime.now(tz).date()
    # "What did I note last week" (2026-10-07: to a model) is a range.
    first = {"yesterday": today - dt.timedelta(days=1), "this week": today - dt.timedelta(days=today.weekday()),
             "last week": today - dt.timedelta(days=today.weekday() + 7)}.get(day, today)
    last = {"yesterday": first, "last week": first + dt.timedelta(days=6)}.get(day, today)
    said = []
    for row in _notes():
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        if first <= at.date() <= last:
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
         # "My address is 12 Oak St", then "what's my address" (2026-10-08:
         # to the planner - her memory keeps it as identity.address).
         "address": ("address", "street"), "home address": ("address", "street"),
         "street address": ("street", "address"),
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
                  "zip": "zip code", "zip code": "zip code", "postcode": "zip code", "postal code": "zip code",
                  "address": "address", "home address": "address", "street address": "address"}


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
        # A tombstone takes back the notes written BEFORE it: "my locker is
        # 42", undone, then said again, is a note again (2026-10-07: the
        # second one stayed hidden behind the first one's tombstone).
        rows = []
        for e in entries:
            if e.get("subject") == "operator:forgotten":
                gone = str(e.get("text") or "")[:300]
                rows = [r for r in rows if str(r.get("text") or "")[:300] != gone]
            elif e.get("kind") == "note" and e.get("subject") == "operator" \
                    and not str(e.get("text") or "").startswith("(voice"):
                # the room's unmatched transcripts are journaled as notes;
                # "(voice, unmatched) north korea" is not a note of his
                rows.append(e)
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


def _told_on(rest) -> str:
    """The notes he gave her on a day; his asks when he gave none."""
    words = str(rest or "").casefold()
    said = _notes_day("yesterday" if ("yesterday" in words or "last night" in words) else "today")
    return _asked_on(rest) if said.startswith("No notes") else said


_CALLED = r"\b(?:called|rang|texted|messaged|stopped by|came by|dropped by|came over|phoned)\b"


def _shop_qty(rest) -> str | None:
    """The amount of a thing on his shopping list, in his words."""
    thing = " ".join(str(rest or "").casefold().split())
    if not thing:
        return None
    try:
        from aletheia import intercom
        rows = intercom._shopping_items()
    except Exception:
        return None
    stem = thing[:-1] if len(thing) > 3 and thing.endswith("s") else thing
    for row in rows or []:
        need = " ".join(str(row.get("need") or "").split())
        if re.search(rf"\b{re.escape(stem)}", need.casefold()) and re.search(r"\d|\b(?:a|an|one|two|three|four|five|six|dozen|half)\b", need.casefold()):
            return f"Your list says {need}."
    return None


def _who_called(rest) -> str:
    """Who he told her called or came by, from the day's notes."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    words = str(rest or "").casefold()
    day = dt.datetime.now(tz).date() - dt.timedelta(days=1 if "yesterday" in words else 0)
    when = "yesterday" if "yesterday" in words else "today"
    said = []
    for row in _notes():
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        text = str(row.get("text") or "").strip()
        if at.date() == day and re.search(_CALLED, text.casefold()):
            said.append(speech.as_she_says_it(text).rstrip("."))
    if not said:
        return (f"Nobody that you told me about {when} - I can't see your phone's calls. "
                "Say \"Mom called\" and I'll keep it.")
    return speech.and_list(said[:5]) + "."


def _who_coming_noted(rest) -> str:
    """Who he told her is visiting, from his notes, newest first."""
    from aletheia import speech
    said = []
    for row in reversed(_notes()):
        text = str(row.get("text") or "").strip()
        if re.search(r"\b(?:is|are) (?:visiting|coming|staying with us|in town|flying in)\b", text.casefold()) \
                and not re.match(r"(?:who|what)\b", text.casefold()):
            said.append(speech.as_she_says_it(text).rstrip("."))
    if not said:
        return "You haven't told me about anyone visiting. Say \"my sister is visiting this weekend\" and I'll keep it."
    return "You told me " + speech.and_list([s[:1].lower() + s[1:] if s.startswith(("Your ", "The ")) else s
                                             for s in said[:3]]) + "."


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


def _how_long_out(place) -> str | None:
    """How long he was out, from his own words today: the last "I'm going to
    the gym" and the first "I'm back" after it. None when he never said he
    was going, so the question goes on."""
    import datetime as dt
    from aletheia import converse, journal, localtime, recollection, speech
    place = re.sub(r"^(?:gone|out|away)$", "", str(place or "").strip())
    tz = localtime.operator_tz()
    date = dt.datetime.now(tz).strftime("%Y-%m-%d")
    try:
        rows = [e for e in journal.entries()
                if e.get("kind") == "note" and e.get("subject") == converse.ASKED_SUBJECT
                and recollection._local_date(str(e.get("ts") or "")) == date]
    except Exception:
        return None
    rows.sort(key=lambda e: str(e.get("ts") or ""))
    there = (rf"\b(?:going|heading|headed|off|leaving|went|driving|walking|running) (?:out )?to (?:the )?{re.escape(place)}\b" if place
             else r"\b(?:going|heading|headed|off) (?:out|to)\b|\bleaving\b|\bstepping out\b")
    back = r"\b(?:i'?m|i am|just got|got|we'?re) (?:back|home)\b|\bback from\b|\bhome now\b"
    left = None
    for i, e in enumerate(rows):
        if re.search(there, " ".join(str(e.get("text") or "").casefold().split())):
            left = i
    if left is None:
        return None
    def at(e):
        return dt.datetime.fromisoformat(str(e.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
    went = at(rows[left])
    clock = lambda t: t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    for e in rows[left + 1:]:
        if re.search(back, " ".join(str(e.get("text") or "").casefold().split())):
            minutes = max(1, int((at(e) - went).total_seconds() // 60))
            h, m = divmod(minutes, 60)
            span = speech.count_phrase(m, "minute") if not h else speech.count_phrase(h, "hour") + (
                f" and {speech.count_phrase(m, 'minute')}" if m else "")
            return (f"About {span} - you said you were going at {clock(went)} and you were back at {clock(at(e))}.")
    where = f"to the {place}" if place else "out"
    return f"You said you were going {where} at {clock(went)}, and you haven't told me you're back yet."


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


def _relation_for_name(name: str) -> str | None:
    """The other way round: "Dana" -> "sister", when a note of his says
    "my sister's name is Dana". Asked "when is Dana's birthday" after
    telling her his sister's birthday, she said he never had."""
    who = " ".join(str(name or "").casefold().split())
    if not who or not re.fullmatch(r"[a-z][a-z' -]{1,40}", who):
        return None
    n = re.escape(who)
    rel = r"(?P<rel>[a-z][a-z' ]{1,24}?)"
    shapes = (rf"^(?:my|our) {rel}(?:'s| s)? name is {n}\.?$",
              rf"^(?:my|our) {rel} is (?:called |named ){n}\.?$",
              rf"^{n} is (?:my|our) (?:new |older |younger |little |big |best )?{rel}\.?$")
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        for shape in shapes:
            m = re.match(shape, said)
            if m:
                return m.group("rel")
    return None


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
    if g.get("fact6"):
        key = f"{g['fact6']} size"
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


def _fact_any(thing: str, whose: str = "my") -> str | None:
    """The newest note saying "my <thing> is ...", in his words; None
    otherwise, so nothing is answered that a note does not settle. "Our"
    and "the" find a note that said any of the three."""
    thing = " ".join(str(thing or "").casefold().split())
    if not thing or "password" in thing or "passcode" in thing:
        return None
    from aletheia import speech
    # "What's my locker combo" a turn after "my locker combination is ..."
    # (2026-10-08: "nothing remembered"): a short form asks for the long one.
    short = {"combo": "combination", "combination": "combo", "info": "information", "information": "info",
             "appt": "appointment", "bday": "birthday", "b-day": "birthday", "dob": "date of birth",
             "num": "number", "#": "number", "id": "id number"}
    things = [thing] + [re.sub(rf"(?<![a-z]){re.escape(a)}(?![a-z])", b, thing) for a, b in short.items()
                        if re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", thing)]
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        # "What's our room number" is answered by "the hotel room number is 312".
        owner = "my" if whose == "my" else "(?:my|our|the)(?: [a-z]+){0,2}"
        if any(re.match(rf"^(?:that )?{owner} {re.escape(t)}s? (?:is|are|=) \S", said.casefold()) for t in things):
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    # "What's my address" a turn after "my address is 12 Oak St" (2026-10-08:
    # to the planner): a fact of his profile, read where it is kept.
    if whose == "my" and thing in _MINE:
        return _mine(thing)
    return None


def _recall(words: str) -> str | None:
    """What he told her about `words`: his notes and her memory, by the
    words themselves. Nothing matching is said as nothing - never guessed."""
    from aletheia import memory, speech
    words, _bar, attr = str(words or "").partition("|")
    being = re.fullmatch(r"being on (.+)", words.strip())
    if being:
        # "Am I on call" is the phrase, not every note with "call" in it.
        state = re.escape(being.group(1))
        for row in _notes():
            said = " ".join(str(row.get("text") or "").split()).rstrip(".")
            if re.search(rf"\b(?:on|doing|started|starting|began) (?:a |an |the )?(?:new )?{state}\b", said, re.I):
                return f"You told me: {speech.as_she_says_it(said)}."
        return None
    wanted = [w for w in re.findall(r"[a-z0-9']+", str(words or "").casefold()) if w not in _STOP_WORDS]
    if not wanted:
        return None
    stems = [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in wanted]
    # "What pets do I have" said nothing while "my dog's name is Max" was
    # on file (2026-10-07): a category is asked by its members' names.
    for w in list(stems):
        stems += {"pet": ["dog", "cat", "puppy", "kitten", "hamster", "rabbit", "bunny", "parrot", "fish", "turtle", "horse"],
                  "kid": ["son", "daughter", "children"], "children": ["son", "daughter", "kid"],
                  "car": ["truck", "van", "suv"], "vehicle": ["car", "truck", "van", "suv"]}.get(w.rstrip("s"), [])

    def hit(text: str) -> bool:
        low = str(text or "").casefold()
        # "What's my wife's name" read back "Bob's wife is Linda" (2026-10-08)
        if any(re.match(rf"[a-z]{{2,15}}'s {re.escape(s)}\b", low) for s in stems if s in _relation_words() | {"neighbor", "neighbour"}):
            return False
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
    if attr and len(found) > 1:
        asked = [f for f in found if attr in f.casefold() or (attr == "name" and re.search(r"\bnamed|\bcalled\b", f.casefold()))]
        found = asked or found
    if not found:
        # "What am I allergic to" read back "nothing about allergic".
        shown = {"allergic": "allergies", "allergic to": "allergies"}.get(str(words).strip(), words)
        return f"I have nothing about {shown} on file - tell me and I'll remember it."
    said = speech.and_list(found[:4])
    return said[:1].upper() + said[1:] + "."


_DISLIKE = re.compile(r"\b(?:don't|do not|dont|never) (?:like|eat)\b|\bdislike|\bcan't stand\b|\bcan't eat\b|\bhate\b"
                      r"|\ballergic\b|\b(?:vegetarian|vegan|lactose|gluten)\b")


def _dislikes(text: str) -> str | None:
    """What he told her he doesn't like or eat, in his words. "Do I like X"
    is answered only when a note names X; otherwise a model may know."""
    from aletheia import speech
    g = _groups("dislikes", text)
    thing = " ".join(str(g.get("dl_thing") or "").split())
    said = []
    for row in _notes():
        low = " ".join(str(row.get("text") or "").split()).casefold()
        if _DISLIKE.search(low) and (not thing or thing.rstrip("s") in low):
            said.append(speech.as_she_says_it(str(row.get("text")).strip()).rstrip("."))
    if thing:
        if said:
            return f"No - you told me: {said[0]}."
        return None
    if not said:
        return "You haven't told me anything you don't like. Say \"I don't like mushrooms\" and I'll remember it."
    return "You told me: " + speech.and_list(said[:5]) + "."


def _married(text: str) -> str | None:
    """How long he has been married, from his note naming the year (or the
    anniversary with one). No year on file is a model's question."""
    import datetime as dt
    from aletheia import localtime, speech
    today = dt.datetime.now(localtime.operator_tz()).date()
    when_asked = text.casefold().startswith("when")
    which = bool(re.match(r"(?:what|which) (?:wedding )?anniversary", _tidy(text)))
    no_year = None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if not re.search(r"\bmarried\b|\banniversary\b", low):
            continue
        if no_year is None and "anniversary" in low and not re.search(r"\b(?:19|20)\d\d\b", low):
            no_year = said
        m = re.search(r"\b(\d{1,2}) years\b", low)
        if m and "been married" in low and not when_asked:
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
        y = re.search(r"\b((?:19|20)\d\d)\b", low)
        if not y or int(y.group(1)) > today.year:
            continue
        if when_asked:
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
        if which:
            # the next one is counted from the year they married
            nxt = _date_in_notes("anniversary", today)
            n = (nxt.year if nxt else today.year) - int(y.group(1))
            if n < 1:
                return None
            on = f", on {nxt.strftime('%A %d %B').replace(' 0', ' ')}" if nxt else ""
            return f"Your {_ordinal(n)}{on} - you told me {speech.as_she_says_it(said).rstrip('.')}."
        years = today.year - int(y.group(1))
        return (f"About {speech.count_phrase(years, 'year')} - you told me: {speech.as_she_says_it(said).rstrip('.')}."
                if years else f"Less than a year - you told me: {speech.as_she_says_it(said).rstrip('.')}.")
    if no_year:
        # "Our anniversary is May 5" names the day and not the year
        # (2026-10-07: "how many years have we been married" went to a model).
        return (f"You told me: {speech.as_she_says_it(no_year).rstrip('.')}. But not the year, so I can't say how long. "
                "Say \"we got married in\" and the year, and I'll know.")
    return None


def _promised(text: str) -> str | None:
    """What he told her he promised somebody, in his words."""
    from aletheia import speech
    g = _groups("promised", text)
    who = " ".join(str(g.get("prom") or g.get("prom2") or g.get("prom3") or "").split())
    anyone = who in ("", "anyone", "anybody", "someone", "people")
    words = [w for w in re.findall(r"[a-z0-9']+", who) if w not in ("my", "our", "the")]
    said = []
    for row in _notes():
        low = " ".join(str(row.get("text") or "").split()).casefold()
        if re.match(r"i promised\b", low) and (anyone or all(re.search(rf"\b{re.escape(w)}", low) for w in words)):
            said.append(speech.as_she_says_it(str(row.get("text")).strip()).rstrip("."))
    if not said:
        return ("You haven't told me about any promises." if anyone
                else f"You haven't told me you promised {who} anything.")
    return "You told me: " + speech.and_list(said[:4]) + "."


def _bedtime_calc(text: str) -> str | None:
    """When to be asleep for a wake-up time: eight hours unless he names
    another, and a quarter of an hour to fall asleep said beside it."""
    g = _groups("bedtime_calc", text)
    m = re.fullmatch(r"(\d{1,2})(?::(\d\d))?\s*(am|pm)?", str(g.get("bt") or "").strip())
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
    hours = {"six": 6, "seven": 7, "eight": 8, "nine": 9}.get(str(g.get("bh") or ""), int(g.get("bh") or 8) if str(g.get("bh") or "8").isdigit() else 8)
    if not 4 <= hours <= 12:
        return None
    asleep = (hour * 60 + int(m.group(2) or 0) - hours * 60) % (24 * 60)

    def clock(minutes):
        h, mm = divmod(minutes % (24 * 60), 60)
        return f"{h % 12 or 12}{':%02d' % mm if mm else ''} {'am' if h < 12 else 'pm'}"
    return (f"Asleep by {clock(asleep)} for {hours} hours - so in bed around {clock(asleep - 15)}, "
            "since it takes a while to drop off.")


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
        # The forecast speaks in halves of a day: an afternoon is "today",
        # an evening "tonight", and "later" the rest of today.
        when = {"this afternoon": "today", "this morning": "today", "this evening": "tonight",
                "later": "", "later today": ""}.get(str(when or "").strip(), when)
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
    # "2 contacts: Dad and mom" (2026-10-07): a name is said with its capital.
    names = sorted(str(r.get("display_name") or r.get("id")) for r in rows)
    names = [n[:1].upper() + n[1:] for n in names]
    return (f"{speech.count_phrase(len(rows), 'contact')}: " + speech.and_list(names[:8])
            + (f", and {len(rows) - 8} more" if len(rows) > 8 else "") + ".")


def _his_likes() -> str:
    """His favorites and the things he said he likes, newest first."""
    from aletheia import speech
    rows = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).rstrip(".")
        if re.fullmatch(r"(?:my )?(?:favou?rite|fav) [a-z ]{2,25}? (?:is|are) .{1,40}|i (?:really )?(?:like|love|enjoy|am into|'m into) "
                        r"(?!you\b|it\b|that\b|this\b|to\b).{2,50}", said, re.I):
            out = speech.as_she_says_it(said)
            if out.casefold() not in {r.casefold() for r in rows}:
                rows.append(out)
    if not rows:
        return "You haven't told me what you like yet. Say \"my favorite food is tacos\" or \"I love hiking\" and I'll remember."
    return "You told me: " + "; ".join(rows[:5]) + (f"; and {len(rows) - 5} more" if len(rows) > 5 else "") + "."


def _lift_max(lift: str) -> str | None:
    """His heaviest logged lift of one kind, from "I benched 185"."""
    from aletheia import speech
    lift = re.sub(r" press$", "", " ".join(str(lift or "").split()))
    verb = {"bench": r"bench(?:ed| pressed)|did (?:a )?bench(?: of)?", "squat": r"squatted|did (?:a )?squat(?: of)?",
            "deadlift": r"deadlifted|did (?:a )?deadlift(?: of)?", "overhead": r"(?:overhead|military) pressed",
            "curl": r"curled", "leg": r"leg pressed"}.get(lift.split()[0] if lift else "", None)
    if not verb:
        return None
    best, said = 0, ""
    for row in _notes():
        m = re.search(rf"\bi (?:just )?(?:{verb}) (\d{{2,4}})( ?(?:pounds|lbs?|kilos|kgs?))?", str(row.get("text") or ""), re.I)
        if m and int(m.group(1)) > best:
            best = int(m.group(1))
            said = speech.humanize_time(str(row.get("ts") or "")) if row.get("ts") else ""
            unit = (m.group(2) or "").strip()
    name = {"bench": "bench", "overhead": "overhead press", "leg": "leg press"}.get(lift.split()[0], lift)
    if not best:
        example = {"bench": "benched 185", "squat": "squatted 225", "deadlift": "deadlifted 275", "overhead": "overhead pressed 95",
                   "curl": "curled 35", "leg": "leg pressed 300"}[lift.split()[0]]
        return f"You haven't told me any {name} weights yet. Say \"I {example}\" after a set and I'll keep your best."
    return f"Your best {name} is {best}{' ' + unit if unit else ''}" + (f", {said}." if said else ".")


def _sick_since(what: str) -> str | None:
    """How long since he first told her he had it, in this run of it: the
    oldest mention with no "I feel better" after it. "Since Monday" he said
    himself is said back as he said it."""
    import datetime as dt
    from aletheia import localtime, speech
    what = " ".join(str(what or "").split())
    tz = localtime.operator_tz()
    first, since = None, ""
    for row in _notes():                                    # newest first
        said = " ".join(str(row.get("text") or "").split()).casefold()
        if re.search(r"\b(?:feel|feeling) (?:much )?better\b|\bover (?:it|my|the)\b", said):
            break
        if re.search(rf"\b(?:have|had|got) (?:a |an |the )?{re.escape(what)}\b", said):
            try:
                first = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
            except ValueError:
                continue
            m = re.search(r"\bsince ([a-z ]+)$", said)
            since = m.group(1) if m else ""
    if first is None:
        return f"You haven't told me you have a {what}. Say \"I have a {what}\" and I'll keep count." \
            if what[0] not in "aeiou" else f"You haven't told me you have an {what}."
    if since:
        since = re.sub(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lambda d: d.group(1).capitalize(), since)
        return f"Since {since}, you told me."
    days = (dt.datetime.now(tz).date() - first.date()).days
    told = speech.humanize_time(first.isoformat())
    return (f"Since {told}, when you first told me." if days < 1
            else f"{days} day{'s' if days != 1 else ''} - you first told me {told}.")


def _born_age(said: str) -> str | None:
    """Age from a birth year alone: two answers, because the year does not
    say whether the birthday has come round yet."""
    import datetime as dt
    from aletheia import localtime
    year = int(said) if str(said or "").isdigit() else 0
    now = dt.datetime.now(localtime.operator_tz()).year
    if not year or year > now:
        return None
    age = now - year
    if age == 0:
        return "Under a year old."
    return f"{age} if the birthday has already come this year, {age - 1} if not."


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
        # "Who is Jake" is answered by who he IS first - "your brother's
        # name is Jake" - and then what else he said (2026-10-08 it came
        # last, after where Jake lives and what he likes).
        who = re.escape(name.casefold().strip())
        notes.sort(key=lambda n: 0 if re.search(rf"\bname is {who}$|^{who} is (?:my|our) ", n.casefold()) else 1)
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


def _reminder_when(what: str) -> str | None:
    """"What time is my pill reminder": the one reminder his words name,
    said with when it goes off. None when none or several match - "when is
    my next reminder" and the rest have their own readers."""
    what = " ".join(str(what or "").split())
    if not what or what in ("next", "first", "last", "the next"):
        return None
    try:
        from aletheia import intercom
        found, why = intercom._one_reminder(what)
        if found is None:
            stem = re.sub(r"s$", "", what)
            found, why = intercom._one_reminder(stem) if stem != what else (None, why)
        if found is None:
            # Her reminders are all hers, so "none is about that" and "which
            # one" are both facts of her store, already said in a sentence.
            return str(why) or None
        said = intercom._reminder_words(found)
    except Exception:
        return None
    text, _, when = said.partition(" — ")
    if not when:
        return None
    if when.startswith(("every", "Every")):
        # "When's my next plant reminder" answered "every Monday at 9 am"
        # (2026-10-08): the rule is not the date he asked for.
        try:
            import datetime as dt
            from aletheia import scheduler, speech
            at = scheduler.next_occurrence(found, dt.datetime.now(dt.timezone.utc))
            if at and what.startswith("next "):
                return (f"Your {what} reminder is {speech.humanize_time(at.isoformat())}: "
                        f"{speech._yours(text.rstrip('.'))}. It repeats {when[0].lower() + when[1:]}.")
            if at:
                when = f"{when}, next {speech.humanize_time(at.isoformat())}"
        except Exception:  # noqa: BLE001 - the rule alone is still true
            pass
    return f"Your {what} reminder is {when}: {text.rstrip('.')}."


def _when_mine(what: str, until: bool = False) -> str | None:
    """"What time is my dentist appointment": the soonest event or reminder
    naming it, said with when. Every word he named must be in it. With
    `until`, how long from now first ("how long until lunch with Jess")."""
    import datetime as dt
    from aletheia import speech
    words = [w for w in re.findall(r"[a-z0-9]+", str(what or "").casefold())
             if w not in _STOP_WORDS and w not in ("s", "with", "at", "for")]
    named = [w for w in words if w.rstrip("s") not in _WHEN_NOUNS]
    words = named or words                    # "my dentist appointment" is the dentist
    if not words:
        return None
    # The appointment before the reminder ABOUT it: "remind me the day
    # before" made "when is my doctors appointment" answer with the
    # reminder's day (2026-10-08).
    for at, text, store in sorted(_coming(), key=lambda row: row[2] != "calendar"):
        low = text.casefold()
        if all(re.search(rf"\b{re.escape(w.rstrip('s'))}", low) for w in words):
            when = speech.humanize_time(at.isoformat())
            if until:
                left = int((at - dt.datetime.now(dt.timezone.utc)).total_seconds() // 60)
                if left < 0:
                    return None
                d, h, m = left // 1440, (left % 1440) // 60, left % 60
                span = (speech.count_phrase(m, "minute") if left < 60
                        else speech.count_phrase(h, "hour") + (f" and {speech.count_phrase(m, 'minute')}" if m and h < 3 else "")
                        if left < 1440
                        else speech.count_phrase(d, "day") + (f" and {speech.count_phrase(h, 'hour')}" if h and d < 3 else ""))
                return f"{span[:1].upper() + span[1:]} - {text.rstrip('.')} is {when}."
            if store == "calendar":
                # "Your haircut is Saturday", not "Haircut is Saturday"
                # (2026-10-08); a title he gave capitals keeps them.
                said = f"your {text}" if text[:1].islower() and not re.match(r"(?:my|the|a|an|our) ", text) else text
                return f"{said[:1].upper() + said[1:]} is {when}."
            return f"You have a reminder {when}: {text.rstrip('.')}."
    # A note he told her: "the dentist is the 15th at 10" before there was a
    # calendar hold for it (2026-10-07: to the planner, with the note held).
    for row in ([] if until else _notes()):
        said = " ".join(str(row.get("text") or "").split())
        # "Kate lives at 44 Pine St" answered "when am I seeing Kate"
        # (2026-10-08): an address is not a when.
        if re.search(r"\b(?:lives?|living|address|located|moved) (?:is )?(?:at|on|to)\b|\b(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd)\b",
                     said.casefold()):
            continue
        # "What time is my flight" after "I'm flying out at 7am" (2026-10-08).
        kin = {"flight": r"\bfl(?:y|ying|ight|ights)\b|\bflying\b", "trip": r"\b(?:trip|vacation|holiday|going to|visiting)\b",
               "vacation": r"\b(?:vacation|holiday|trip)\b"}
        if all(re.search(kin.get(w.rstrip("s"), rf"\b{re.escape(w.rstrip('s'))}"), said.casefold()) for w in words) \
                and re.search(r"\b\d{1,2}(?:st|nd|rd|th|:\d\d| ?[ap]\.?m\b)|\b(?:at|on|the|by) \d{1,2}\b|\b\d{1,2}/\d{1,2}\b"
                              r"|day\b|tomorrow|tonight|noon|\bweekend\b|\b(?:next|this) (?:week|month|year)\b"
                              # "My next checkup is in January" (2026-10-08)
                              r"|\bin (?:" + "|".join(_MONTHS) + r"|spring|summer|fall|autumn|winter)\b", said.casefold()):
            # A when, not just a number: "my rent is 1500" answered "when
            # is rent due" (2026-10-07).
            return f"You told me: {speech.as_she_says_it(said.rstrip('.'))}."
    # Nothing by that name in her stores is not "you have none": it may be
    # in his mail, which a model can read. Only a found answer is quick.
    return None


def _reminders_between(first, last, now) -> str:
    """" You do have 1 reminder: Friday at 9 am, call grandma." for an empty
    calendar: "what's coming up this week" said "Nothing on your calendar
    this week" with two reminders set in it (2026-10-08). Empty when none."""
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    try:
        rows = [(at.astimezone(tz), text) for at, text, store in _coming()
                if store == "reminder" and first <= at.astimezone(tz).date() <= last and at.astimezone(tz) >= now]
    except Exception:
        return ""
    if not rows:
        return ""
    said = [f"{speech.humanize_time(at.isoformat())}, {speech._yours(text.rstrip('.'))}" for at, text in rows[:4]]
    more = f"; and {len(rows) - 4} more" if len(rows) > 4 else ""
    return f" You do have {speech.count_phrase(len(rows), 'reminder')}: " + "; ".join(said) + more + "."


def _reminders_on(day: str) -> str | None:
    """His reminders and alarms that go off on the day he names."""
    import datetime as dt
    from aletheia import localtime, voice
    # "What reminders do I have tonight" (2026-10-08: to a model): today's
    # from 5 pm on.
    tonight = day == "tonight"
    if tonight:
        day = "today"
    iso = voice._spoken_day(day)
    if not iso:
        return None
    tz = localtime.operator_tz()
    # From the START of that day: a daily reminder whose next time is today
    # was missing from tomorrow (2026-10-08).
    start = max(dt.datetime.now(dt.timezone.utc),
                dt.datetime.combine(dt.date.fromisoformat(iso), dt.time(0, 0), tzinfo=tz) - dt.timedelta(seconds=1))
    rows = [(at.astimezone(tz), text) for at, text, store in _coming(start) if store == "reminder"
            and at.astimezone(tz).date().isoformat() == iso and (not tonight or at.astimezone(tz).hour >= 17)]
    if tonight:
        day = "tonight"
    if not rows:
        return f"No reminders {day if day in ('today', 'tonight', 'tomorrow') else 'on ' + day.capitalize()}."
    from aletheia import speech
    said = [f"{at.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower()}, {speech._yours(text.rstrip('.'))}" for at, text in rows[:6]]
    lead = f"{speech.count_phrase(len(rows), 'reminder')} {day if day in ('today', 'tonight', 'tomorrow') else 'on ' + day.capitalize()}: "
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

    def name(text: str, at) -> str:
        found = re.search(r"your (.+?) timer is up", text)
        if not found:
            return "your timer"
        # "15 minutes left on your 10-minute timer" after "add 5 minutes"
        # (2026-10-07): a length it has outgrown is not its name any more -
        # the rule voice's own answer already kept.
        length = re.fullmatch(r"(\d+)[- ](minute|hour)s?", found.group(1))
        if length and (at - now).total_seconds() > int(length.group(1)) * (3600 if length.group(2) == "hour" else 60) + 30:
            return "your timer"
        # A named one is "the eggs timer" - the same words voice uses.
        called = re.fullmatch(r"\d+(?:[- ]and a half)?[- ](?:minute|hour|second)s?[- ](.+)", found.group(1))
        return f"the {called.group(1)} timer" if called else f"your {found.group(1)} timer"
    lines = [f"{left(at)} left on {name(text, at)}" for at, text in running[:3]]
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
    # "Where is lunch with Dana" is a place on his calendar, not a saved
    # place or a file (2026-10-08: searched his Documents).
    if re.search(r"\b(?:meeting|call|appointment|appt|interview|class|session|lunch|dinner|breakfast|brunch|coffee|drinks|party)\b", name):
        said = _event_detail(f"where is {name}")
        if said:
            return said
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
    # "How many tablespoons in a quarter cup" (2026-10-08: to a model)
    m = (re.fullmatch(r"how many " + _VOLUME_WORD + r" (?:are )?(?:in|make|is|to) (?:a |an |one |(?P<n>[\d.]+|half a|a half"
                      r"|a quarter(?: of a)?|a third(?: of a)?|three quarters(?: of a)?|two thirds(?: of a)?|1/4|1/3|1/2|3/4|2/3) )?"
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
    fractions = {"half a": 0.5, "a half": 0.5, "1/2": 0.5, "1/4": 0.25, "1/3": 1 / 3, "3/4": 0.75, "2/3": 2 / 3}
    for word, part in (("a quarter", 0.25), ("a third", 1 / 3), ("three quarters", 0.75), ("two thirds", 2 / 3)):
        fractions[word] = fractions[word + " of a"] = part
    n = fractions.get(said_n) if said_n in fractions else float(said_n) if said_n else 1.0
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
    # "Refused — Nothing is waiting to be snoozed" is not something that
    # happened overnight (2026-10-07): a refusal that had nothing to act on
    # changed nothing, and the morning has three lines to spend.
    # Nor is "refused — Which one — 6 am or 7 am?": a question she asked
    # him back, read out in the morning as a thing she did.
    rows = [e for e in rows if not re.match(r"refused\s*[—-]\s*(?:nothing|there(?:'s| is) nothing|no |which\b|.*\?\s*$)",
                                            str(recollection._row(e).get("what") or ""), re.IGNORECASE)]
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
        # "What do you remember about me" said "Nothing yet" with two notes
        # in the store (2026-10-07). They are not about HIM, but they are
        # what she holds, and an empty answer denies the store.
        try:
            held = len(_notes())
        except Exception:
            held = 0
        if held:
            return (f"Nothing about you yourself yet, but I'm keeping {speech.count_phrase(held, 'note')} for you - "
                    "say \"read my notes\" to hear them.")
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


def _counted(text: str) -> str | None:
    """"How many pushups have I done today": his notes saying "I did 50
    pushups", added up. None when he has kept none, so the question goes on
    ("how many steps did I take" has its own honest answer)."""
    import datetime as dt
    from aletheia import localtime
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "counted"), None)
    if not found:
        return None
    what = found.group("counted").strip()
    when = (found.group("counted_when") or " today").strip()
    if what in _MEDS:
        # "How many tylenol have I taken": "Say 'I did 20 tylenol'" (2026-10-08).
        return _logged(f"how much {what} have i taken {when}")
    stem = re.sub(r"(?:es|s)$", "", what.replace("-", ""))
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    start = {"today": today, "yesterday": today - dt.timedelta(days=1),
             "this week": today - dt.timedelta(days=today.weekday())}[when]
    end = start if when == "yesterday" else today
    total, seen = 0, False
    said = re.compile(r"^i (?:did|just did|have done|walked|took|swam|rowed|ate|had|ate about|had about) (?:another )?(\d[\d,]*) ([a-z][a-z -]{1,20})", re.IGNORECASE)
    for row in _notes():
        m = said.match(str(row.get("text") or ""))
        if not m or re.sub(r"(?:es|s)$", "", m.group(2).strip().casefold().replace("-", "").split()[0]) != stem.split()[0]:
            continue
        try:
            day = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if start <= day <= end:
            total += int(m.group(1).replace(",", ""))
            seen = True
    if not seen:
        if stem in ("step", "heart rate", "calorie"):
            return None                 # those have their own honest answer
        # "Say 'I did 20 pills'" (2026-10-08): a pill is taken.
        verb, n = ("took", 2) if stem in ("pill", "tablet", "capsule", "dose", "painkiller", "vitamin") \
            else ("ate", 500) if what == "calories" else ("did", 20)
        return f"You haven't told me about any {what} {when}. Say \"I {verb} {n} {what}\" and I'll add them up."
    return f"{total:,} {what} {when}."


def _went_said(asked: str) -> str:
    """The regex a note of his matches when he did what `asked` names."""
    a = re.sub(r"\b(?:gone|been)\b", "go", asked.casefold())
    a = re.sub(r"\b(?:the|a|an|on|for)\b", " ", a)
    a = " ".join(a.split())
    m = re.match(r"go to (.+)", a)
    if m:
        place = m.group(1)
        return (rf"\bwent to (?:the )?{re.escape(place)}\b|\b(?:i'?m|i am|just got) (?:at|to) (?:the )?{re.escape(place)}\b"
                + (r"|\bworked out at the gym\b" if place == "gym" else ""))
    noun = re.sub(r"^go ", "", a)
    # "Did I work out today" after "I ran 3 miles" and "I did 30 pushups"
    # (2026-10-08: "Not that you've told me today"). A run, a ride, a lift
    # or a set of anything is a workout.
    workout = (r"\bworked out\b|\bexercised\b|went to (?:the )?gym|\b(?:ran|jogged|swam|biked|cycled|hiked|rowed|lifted)\b"
               # "I ran into Sam", "ran out of milk", "ran late" are not runs.
               r"(?! (?:into|out|late|over|errands|across|up|a|an|the|my|our|his|her|some|it|them)\b)"
               r"|went (?:for a |on a )?(?:run|jog|swim|bike ride|ride|hike)|went (?:running|jogging|swimming|cycling|biking|hiking)"
               r"|\bdid (?:\d+ |a |some )?(?:push-?ups|sit-?ups|squats|pull-?ups|crunches|burpees|lunges|planks?|reps|sets|yoga|pilates"
               r"|cardio|a workout|weights|crossfit|hiit)\b|\b(?:played|had) (?:basketball|soccer|tennis|pickleball|squash|volleyball)\b")
    runs = {"run": r"\bran\b|went (?:for a |on a )?run|went running", "running": r"\bran\b|went (?:for a |on a )?run|went running",
            "jog": r"\bjogged\b|went (?:for a )?jog|went jogging", "jogging": r"\bjogged\b|went (?:for a )?jog|went jogging",
            "ran": r"\bran\b|went (?:for a |on a )?run|went running", "jogged": r"\bjogged\b|went (?:for a )?jog|went jogging",
            "swim": r"\bswam\b|went (?:for a )?swim|went swimming", "swum": r"\bswam\b|went (?:for a )?swim|went swimming",
            "swimming": r"\bswam\b|went (?:for a )?swim|went swimming",
            "work out": workout, "worked out": workout, "exercise": workout, "exercised": workout,
            "meditate": r"\bmeditated\b", "meditated": r"\bmeditated\b",
            "do yoga": r"\bdid yoga\b|went to yoga", "done yoga": r"\bdid yoga\b|went to yoga"}
    if noun in runs:
        return runs[noun]
    stem = re.sub(r"ing$", "", noun)
    return rf"\bwent (?:for a |on a )?{re.escape(noun)}\b|\bwent {re.escape(stem)}"


def _went(text: str) -> str | None:
    """"When did I last go to the gym", "did I work out today", "how many
    times did I go for a run this week": his notes saying he did, counted
    and dated. Nothing kept is said as nothing kept - never guessed."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("went", text)
    asked = (g.get("went") or g.get("went2") or g.get("went3") or "").strip()
    if not asked:
        return None
    window = (g.get("went_when") or g.get("went_when3") or "").strip()
    said_re = _went_said(asked)
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    hits = []
    for row in _notes():
        low = " ".join(str(row.get("text") or "").split()).casefold()
        if not low.startswith(("i ", "i'm ", "im ", "just got ")) or not re.search(said_re, low):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        hits.append(at)
    hits.sort(reverse=True)
    plain = re.sub(r"\b(?:gone|been)\b", "go", asked)
    if g.get("went3"):
        start = {"today": now.replace(hour=0, minute=0, second=0, microsecond=0),
                 "this month": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                 "last week": (now - dt.timedelta(days=now.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)}.get(
            window, (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0))
        end = start + dt.timedelta(days=7) if window == "last week" else now + dt.timedelta(days=1)
        n = sum(1 for at in hits if start <= at < end)
        span = window or "this week"
        if not n:
            return f"None {span} that you've told me."
        return f"{speech.count_phrase(n, 'time')} {span}, from what you've told me."
    if g.get("went2"):
        if not hits:
            return f"Not that you've told me{' ' + window if window else ''}."
        last = hits[0]
        if window in ("today", "yet", "this morning"):
            if last.date() == now.date():
                return f"Yes - {speech.humanize_time(last.isoformat())}."
            return f"Not today that you've told me. The last time was {speech.humanize_time(last.isoformat())}."
        if window == "this week" and last < now - dt.timedelta(days=now.weekday() + 1):
            return f"Not this week that you've told me. The last time was {speech.humanize_time(last.isoformat())}."
        return f"Yes - the last time was {speech.humanize_time(last.isoformat())}."
    if not hits:
        return f"You haven't told me. Say \"I {_past_go(plain)}\" when you do and I'll keep track."
    return f"The last time you told me was {speech.humanize_time(hits[0].isoformat())}."


def _past_go(asked: str) -> str:
    """"go to the gym" said the way he would tell her he did it."""
    a = asked.casefold()
    for base, past in (("go ", "went "), ("work out", "worked out"), ("exercise", "exercised"), ("meditate", "meditated"),
                       ("do yoga", "did yoga"), ("run", "went for a run"), ("jog", "went for a jog"), ("swim", "went for a swim")):
        if a.startswith(base):
            return past + a[len(base):]
    return a


_SPENT_NOTE = re.compile(r"^i (?:spent|paid) \$?(?P<amt>\d[\d,]*(?:\.\d+)?)(?: dollars| bucks)? (?:on|for) (?P<on>.+?)"
                         r"(?: (?P<when>today|yesterday|this week|last night))?\.?$")


def _spent(question: str) -> str | None:
    """"How much did I spend this week", "what did I spend on groceries":
    added up from what he told her ("I spent 40 dollars on groceries").
    None when he has told her nothing about spending at all, so the
    accounts answer still says there is no bank."""
    import datetime as dt
    from aletheia import localtime, speech
    low = _tidy(question or "")
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    rows = []
    for row in _notes():
        m = _SPENT_NOTE.match(" ".join(str(row.get("text") or "").split()).casefold())
        if not m:
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        if m.group("when") in ("yesterday", "last night"):
            at -= dt.timedelta(days=1)
        rows.append((at, float(m.group("amt").replace(",", "")), m.group("on").strip()))
    if not rows:
        return None
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window = next((w for w in ("today", "yesterday", "this week", "last week", "this month", "last month")
                   if re.search(rf"\b{w}\b", low)), "")
    start, end = {"today": (midnight, midnight + dt.timedelta(days=1)),
                  "yesterday": (midnight - dt.timedelta(days=1), midnight),
                  "this week": (midnight - dt.timedelta(days=now.weekday()), midnight + dt.timedelta(days=1)),
                  "last week": (midnight - dt.timedelta(days=now.weekday() + 7), midnight - dt.timedelta(days=now.weekday())),
                  "this month": (midnight.replace(day=1), midnight + dt.timedelta(days=1)),
                  "last month": ((midnight.replace(day=1) - dt.timedelta(days=1)).replace(day=1), midnight.replace(day=1)),
                  }.get(window, (midnight - dt.timedelta(days=30), midnight + dt.timedelta(days=1)))
    span = window or "in the last 30 days"
    on = re.search(r"\bspen[dt] (?:on|for) (?P<on>[a-z][a-z' ]{1,30}?)(?: (?:today|yesterday|this week|last week|this month|last month))?$", low)
    asked_for = [w.rstrip("s") for w in on.group("on").split() if w not in ("the", "my", "a")] if on else []
    if asked_for == ["food"]:
        # "On food" is lunch and groceries too (2026-10-08: "nothing on food").
        asked_for = list(_FOOD_WORDS)
    hits = [r for r in rows if start <= r[0] < end and (not on or any(w in r[2] for w in asked_for))]
    if not hits:
        return (f"Nothing on {on.group('on')} {span} that you've told me." if on
                else f"Nothing {span} that you've told me.")
    total = sum(r[1] for r in hits)
    if on:
        return f"{_money(total)} on {on.group('on')} {span}, from what you've told me."
    by: dict[str, float] = {}
    for _, amt, what in hits:
        by[what] = by.get(what, 0) + amt
    ranked = sorted(by.items(), key=lambda kv: -kv[1])
    # "What did I spend the most on" (2026-10-08) answered with the total:
    # the biggest leads when that is what he asked.
    if re.search(r"\b(?:the )?most\b|\bbiggest\b|\blargest\b", low) and ranked:
        top, amt = ranked[0]
        return (f"{top[:1].upper() + top[1:]}: {_money(amt)} of the {_money(total)} you've told me you spent {span}."
                if len(ranked) > 1 else f"{top[:1].upper() + top[1:]}, {_money(amt)} - the only spending you've told me about {span}.")
    parts = [f"{_money(v)} on {k}" for k, v in ranked[:4]]
    return f"{_money(total)} {span}, from what you've told me: {speech.and_list(parts)}."


#: What "food" is when he says what he spent it on.
_FOOD_WORDS = ("food", "grocer", "eating out", "takeout", "take out", "restaurant", "lunch", "dinner", "breakfast",
               "brunch", "coffee", "pizza", "snack", "doordash", "uber eats", "fast food", "burger", "tacos", "sushi")


_BUDGET_NOTE = re.compile(r"^(?:my |our )?(?P<kind>monthly |weekly |grocery |food |eating out |gas |fun |shopping )?budget is "
                          r"(?:about |around )?\$?(?P<amt>\d[\d,]*(?:\.\d+)?)(?: dollars| bucks)?"
                          r"(?: (?:a|per|each|every) (?P<per>week|month))?")


def _budget(question: str) -> str | None:
    """"Am I over budget", "how much is left in my grocery budget": his
    budget note against what he told her he spent. None when he never gave
    a budget, so the question goes where it went before."""
    import datetime as dt
    from aletheia import localtime
    low = _tidy(question or "")
    asked = re.search(r"\b(grocery|food|eating out|gas|fun|shopping)\b", low)
    budgets = []
    for row in _notes():
        m = _BUDGET_NOTE.match(" ".join(str(row.get("text") or "").split()).casefold())
        if m:
            budgets.append(((m.group("kind") or "").strip(), float(m.group("amt").replace(",", "")),
                            m.group("per") or ("week" if (m.group("kind") or "").strip() == "weekly" else "month")))
    if not budgets:
        return None
    want = asked.group(1) if asked else ""
    pick = next((b for b in budgets if b[0] == want), None) if want else \
        next((b for b in budgets if b[0] in ("", "monthly", "weekly")), budgets[0])
    if not pick:
        return f"You haven't told me a {want} budget."
    kind, amount, per = pick
    category = kind if kind not in ("", "monthly", "weekly") else ""
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - dt.timedelta(days=now.weekday()) if per == "week" else midnight.replace(day=1)
    words = {"grocery": ("grocer", "food"), "food": _FOOD_WORDS,
             # "I spent 25 on lunch" is eating out (2026-10-08)
             "eating out": ("eating out", "restaurant", "takeout", "take out", "lunch", "dinner", "breakfast", "brunch",
                            "fast food", "pizza", "dining")}.get(category, (category,) if category else ())
    spent = 0.0
    for row in _notes():
        m = _SPENT_NOTE.match(" ".join(str(row.get("text") or "").split()).casefold())
        if not m:
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        if m.group("when") in ("yesterday", "last night"):
            at -= dt.timedelta(days=1)
        if at >= start and (not words or any(w in m.group("on") for w in words)):
            spent += float(m.group("amt").replace(",", ""))
    name = f"{category} budget" if category else "budget"
    span = f"this {per}"
    if spent > amount:
        return f"Yes - you're {_money(spent - amount)} over your {_money(amount)} {name} {span}, from what you've told me."
    if re.search(r"\bover\b", low):
        return (f"No - you've spent {_money(spent)} of your {_money(amount)} {name} {span}, "
                f"so {_money(amount - spent)} is left, from what you've told me.")
    return f"{_money(amount - spent)} left of your {_money(amount)} {name} {span} - you've spent {_money(spent)}, from what you've told me."


_PAY_AMOUNT = re.compile(r"(?:paycheck|pay ?check|pay|salary|income|take[- ]home(?: pay)?|hourly rate|wages?) (?:is|are) "
                         r"(?:about |around )?\$?(?P<a>\d[\d,.]*)(?P<k>k)?(?: dollars| bucks)?(?: (?:an? |per |every |each )(?P<per>hour|week|month|year|two weeks|other week))?"
                         r"|^i (?:make|earn|get paid|bring home|take home|get) (?:about |around )?\$?(?P<a2>\d[\d,.]*)(?P<k2>k)?(?: dollars| bucks)?"
                         r" (?:an? |per |every |each )(?P<per2>hour|week|month|year|two weeks|other week)")
_PAY_WHEN = re.compile(r"^(?:i get paid (?:every|each|on|the|twice|weekly|biweekly|bi-weekly|monthly|fortnightly)\b|(?:my )?pay ?day is )")
_PAID_NOTE = re.compile(r"^i (?:just )?got (?:my )?(?:paid|paycheck|pay ?check)")
_PER_YEAR = {"hour": 2080, "week": 52, "two weeks": 26, "other week": 26, "month": 12, "year": 1}


def _next_payday(said: str):
    """The next date a pay note names - "on the 15th and the 30th", "on the
    1st", "every Friday", "the last day of the month". None for any other
    shape (every other Friday has no anchor), never a guess."""
    import calendar as _calmod
    import datetime as dt
    from aletheia import localtime
    low = str(said or "").casefold()
    today = dt.datetime.now(localtime.operator_tz()).date()
    days = [int(d) for d in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)\b", low) if 1 <= int(d) <= 31]
    last = bool(re.search(r"\blast (?:day|business day)\b|\bend of (?:the|every) month\b", low))
    if days or last:
        found = []
        for ahead in range(3):
            year, month = today.year + (today.month - 1 + ahead) // 12, (today.month - 1 + ahead) % 12 + 1
            size = _calmod.monthrange(year, month)[1]
            for d in days + ([size] if last else []):
                found.append(dt.date(year, month, min(d, size)))
        coming = sorted(x for x in found if x >= today)
        return coming[0] if coming else None
    # "Every Friday", and "on Fridays" (2026-10-08: "how many days until
    # payday" read the note back with no date).
    weekday = re.search(r"\b(?:every (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
                        r"|(?:on )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s\b)", low)
    if weekday and not re.search(r"\bother\b", low):
        want = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(
            weekday.group(1) or weekday.group(2))
        return today + dt.timedelta(days=(want - today.weekday()) % 7)
    return None


def _pay(question: str) -> str | None:
    """His pay, from what he told her: how much (worked out to a year, a
    month or a week when he asks one), when it comes, when it last came.
    None when he never said, so the question goes on as before."""
    from aletheia import speech
    low = _tidy(question or "")
    notes = [(" ".join(str(r.get("text") or "").split()), r) for r in _notes()]
    if re.search(r"\bhow much (?:did i|was my)\b", low):
        for t, r in notes:
            m = _PAID_NOTE.match(t.casefold()) and re.search(r"\$?(\d[\d,.]*)(k)?", t)
            if m:
                amount = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
                return f"You told me you got paid {_money(amount)} {speech.humanize_time(str(r.get('ts') or ''))}."
        return None
    if re.search(r"\bwhen did i\b", low):
        paid = [(t, r) for t, r in notes if _PAID_NOTE.match(t.casefold())]
        if not paid:
            return None
        return f"You told me you got paid {speech.humanize_time(str(paid[0][1].get('ts') or ''))}."
    if re.search(r"\bwhen\b|pay ?day|until i get paid|until my paycheck", low):
        hit = next((t for t, _ in notes if _PAY_WHEN.match(t.casefold())), None)
        if not hit:
            return None
        told = f"You told me: {speech.as_she_says_it(hit).rstrip('.')}."
        nxt = _next_payday(hit)
        if nxt is None:
            return told
        import datetime as dt
        from aletheia import localtime
        days = (nxt - dt.datetime.now(localtime.operator_tz()).date()).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        return f"Next payday is {nxt.strftime('%A')} the {_ordinal(nxt.day)}, {when}. {told}"
    hit = None
    for t, _ in notes:
        m = _PAY_AMOUNT.search(t.casefold())
        if m:
            hit = (t, m)
            break
    if not hit:
        return None
    t, m = hit
    amount = float((m.group("a") or m.group("a2")).replace(",", "").rstrip("."))
    if m.group("k") or m.group("k2"):
        amount *= 1000
    per = m.group("per") or m.group("per2") or ("year" if re.search(r"salary|income", t.casefold()) and amount > 9000 else "")
    want = next((u for u in ("hour", "week", "month", "year") if re.search(rf"\b(?:an? |per ){u}\b|\b{u}ly\b", low)),
                "year" if re.search(r"\b(?:yearly|annual)\b", low) else
                "month" if "monthly" in low else "week" if "weekly" in low else "")
    if not per or not want or want == per:
        return f"You told me: {speech.as_she_says_it(t).rstrip('.')}."
    yearly = amount * _PER_YEAR[per]
    out = yearly / _PER_YEAR[want]
    note = " before tax, if that's a 40-hour week" if per == "hour" or want == "hour" else ""
    return f"About {_money(round(out, 2 if want == 'hour' else 0))} a {want}{note}. You told me {speech.as_she_says_it(t).rstrip('.')}."


_START_NOTE = re.compile(r"^(?:i (?:start|begin|get to|have to be at|need to be at|clock in at|clock in|go in)(?: work)?(?: at)?"
                         r"|my (?:shift|work ?day) (?:starts|begins)(?: at)?"
                         # "My work hours are 9 to 5" (2026-10-08: to the planner).
                         r"|my (?:work |working )?hours are|i work(?: from)?) (?P<at>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)")
_END_NOTE = re.compile(r"^(?:(?:i (?:get off|finish|leave|clock out)(?: work)?(?: at)?|my (?:shift|work ?day) (?:ends|finishes)(?: at)?) "
                       r"|(?:my (?:work |working )?hours are|i work(?: from)?) \d{1,2}(?::\d\d)?(?: ?(?:am|pm))? (?:to|till|until|-) )"
                       r"(?P<at>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)")
_COMMUTE_NOTE = re.compile(r"^(?:my commute is|it takes me|my drive to work is) (?:about |around )?(?P<n>\d{1,3}) (?P<u>minutes|mins|min|hours?)")


_LIFE_WORDS = {"moving": r"\b(?:moving|move)\b", "move": r"\b(?:moving|move)\b", "vacation": r"\b(?:vacation|holiday)\b",
               "holiday": r"\b(?:vacation|holiday)\b", "trip": r"\btrip\b", "new job": r"\bnew job\b", "school": r"\bschool\b",
               "college": r"\bcollege\b", "classes": r"\bclasses\b", "surgery": r"\bsurgery\b", "first day": r"\bfirst day\b",
               "graduation": r"\bgraduat", "graduating": r"\bgraduat", "retiring": r"\bretir", "honeymoon": r"\bhoneymoon\b",
               "moving day": r"\b(?:moving|move)\b",
               "off": r"\b(?:days? off|time off|pto|off work|i'?m off|i am off|have \w+ off|taking \w+(?: \w+)? off|on vacation|on holiday)\b",
               "working from home": r"\b(?:working from home|wfh)\b", "wfh": r"\b(?:working from home|wfh)\b",
               "out of the office": r"\bout of (?:the )?office\b", "out of office": r"\bout of (?:the )?office\b",
               "package": r"\b(?:package|parcel|delivery)\b", "parcel": r"\b(?:package|parcel|delivery)\b",
               "delivery": r"\b(?:package|parcel|delivery)\b",
               "inspection": r"\binspection\b", "service": r"\bdue for (?:an? |its )?service\b",
               "oil change": r"\boil change\b", "tune-up": r"\btune-?up\b", "tuneup": r"\btune-?up\b",
               "smog check": r"\bsmog\b", "emissions test": r"\bemissions\b", "tire rotation": r"\btire rotation\b",
               "car due": r"\b(?:car|truck|van|suv)\b.*\bdue\b",
               "pto": r"\b(?:days? off|time off|pto|off work|on vacation)\b"}


def _on_its_way(thing: str | None) -> str | None:
    """What he told her he ordered or has coming, in the last month - the
    thing he named, or any delivery when he asked about all of them. None
    when he named a thing he never mentioned: his mail may know."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    coming = r"\b(?:ordered|bought|purchased|arriving|coming|delivered|delivery|package|parcel|shipping|shipped)\b"
    named = [w for w in re.findall(r"[a-z0-9']+", (thing or "").casefold()) if w not in ("new", "the", "my", "a", "an")]
    hits = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if not re.search(coming, said, re.I):
            continue
        if named and not all(re.search(r"\b" + re.escape(w) + r"s?\b", said, re.I) for w in named):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        if (now - at).days > 30:
            continue
        day = "today" if at.date() == now.date() else f"on {at.strftime('%A')} {at.day} {at.strftime('%B')}"
        hits.append((day, speech.as_she_says_it(said).rstrip(".")))
        if named or len(hits) == 3:
            break
    if not hits:
        if named:
            return None
        return "Nothing you've told me about. Say \"my package is arriving Thursday\" and I'll keep it."
    if named:
        day, told = hits[0]
        arrive = re.search(r"\b(?:arriv|coming|due|deliver|get(?:ting)? here)", told, re.I)
        return f"You told me {day}: {told}." + ("" if arrive else " You didn't say when it arrives.")
    days = {d for d, _t in hits}
    lead = f"You told me {hits[0][0]}" if len(days) == 1 else "From what you've told me lately"
    return f"{lead}: " + speech.and_list([t for _d, t in hits]) + "."


def _plan_said_today(place: str | None, when: str | None) -> str | None:
    """A plan for later he told her today ("I'm going to the gym after
    work"), read back in his words. None when there is none: it may be on
    his calendar, which a model reads."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    if place:
        pattern = r"\b(?:going|heading|gonna go|go)(?: to)? (?:the )?" + re.escape(place) + r"\b"
    elif (when or "").startswith("later"):
        pattern = r"\b(?:going|heading|gonna go)\b"     # any plan he told her for today
    else:
        pattern = r"\b" + re.escape(when or "") + r"\b"
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if not re.search(pattern, said, re.I) or not re.match(r"(?:i'?m|i am|i'?ll be|i will be) ", said, re.I):
            continue
        try:
            day = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if day != today:
            continue
        return f"You told me earlier: {speech.as_she_says_it(said).rstrip('.')}."
    return None


def _life_when(text: str) -> str | None:
    """When his move, trip or new job is, from his note - with the day he
    said it, since "next month" is only true from that day. None when he
    never said: it may be on a calendar or in his mail."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("life_when", text)
    if g.get("lw8") or g.get("lw9"):
        return _plan_said_today(g.get("lw8"), g.get("lw9"))
    if g.get("lw10") or g.get("lw11"):
        # "When is my sister coming" is a visit, not a delivery: what he
        # told her about it is read the way any "when" note is.
        return _on_its_way(g.get("lw10")) or (_when_note(text) if g.get("lw10") else None)
    if g.get("lw12") or g.get("lw13"):
        dest = (g.get("lw12") or g.get("lw13")).strip()
        pattern = (r"\b(?:going|heading|headed|driving|trip|off|flying|fly|flight) to " if g.get("lw12") else r"\bvisiting ") + re.escape(dest) + r"\b"
        found = _told_when(pattern)
        return found or (_when_note(text) if g.get("lw12") else None)
    asked = (g.get("lw") or g.get("lw2") or g.get("lw3") or g.get("lw4") or g.get("lw5") or g.get("lw6") or g.get("lw7")
             or ("car due" if re.match(r"when is (?:my|the) (?:car|truck|van|suv) due", text.casefold()) else "")).strip()
    key = next((k for k in sorted(_LIFE_WORDS, key=len, reverse=True) if k in asked), None)
    place = re.search(r"(?:fly|flying) to (.+)$", asked)
    pattern = (r"\b(?:fly|flying|flight) to " + re.escape(place.group(1))) if place else _LIFE_WORDS.get(key or "")
    if not pattern:
        return None
    return _told_when(pattern)


def _told_when(pattern: str) -> str | None:
    """His newest note matching `pattern`, read back with the day he said
    it, because "next week" is only true from that day."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if not re.search(pattern, said, re.I):
            continue
        told = speech.as_she_says_it(said).rstrip(".")
        try:
            day = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            return f"You told me: {told}."
        if day == dt.datetime.now(tz).date():
            return f"You told me today: {told}."
        return f"You told me on {day.strftime('%A')} {day.day} {day.strftime('%B')}: {told}."
    return None


def _worked(text: str) -> str | None:
    """Hours at work from his "started work" and "finished work" notes, day
    by day on his clock; a day still open counts to now. None when he never
    logged a start - his hours may be somewhere a model can read."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("worked", text)
    when = (g.get("worked") or g.get("worked2") or " today").strip()
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    today = now.date()
    first = {"yesterday": today - dt.timedelta(days=1), "this week": today - dt.timedelta(days=today.weekday())}.get(when, today)
    last = today - dt.timedelta(days=1) if when == "yesterday" else today
    marks = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        if said not in ("started work", "finished work"):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        if first <= at.date() <= last:
            marks.append((at, said))
    if not any(s == "started work" for _a, s in marks):
        return None if when == "today" and not marks else f"You didn't tell me you started work {when}."
    # A start and a finish in the same second are a start, then a finish.
    marks.sort(key=lambda m: (m[0], m[1] != "started work"))
    total, start, still = 0.0, None, False
    for at, said in marks:
        if said == "started work":
            start = start or at
        elif start:
            total += (at - start).total_seconds()
            start = None
    if start:
        end = now if start.date() == today else start.replace(hour=23, minute=59)
        total += (end - start).total_seconds()
        still = start.date() == today
    minutes = int(total // 60)
    amount = (speech.count_phrase(minutes // 60, "hour") + (f" and {speech.count_phrase(minutes % 60, 'minute')}" if minutes % 60 else "")
              if minutes >= 60 else speech.count_phrase(minutes, "minute"))
    return f"{amount} {when}" + (", and you're still at it." if still else ".")


def _work_hours(text: str) -> str | None:
    """"What time do I start work": his note saying so, in his words."""
    from aletheia import speech
    g = _groups("work_hours", text)
    which = g.get("work_hours") or g.get("work_hours2") or g.get("work_hours3") or ""
    note = _END_NOTE if which in ("get off", "finish", "clock out", "end") else _START_NOTE
    # "I have to work late tonight" (2026-10-08) is today's end, said first.
    late = _working_late_today() if note is _END_NOTE and not re.search(r"\btomorrow\b", _tidy(text)) else None
    if late:
        for row in _notes():
            found = note.match(" ".join(str(row.get("text") or "").split()).casefold())
            clock = _work_clock(found.group("at"), True) if found else None
            if clock:
                return f"{late}, so later than your usual {clock}."
        return f"{late}, but not until when."
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        found = note.match(said.casefold())
        if found and g.get("work_hours3"):
            return _until_work(found.group("at"), which, said)
        if found:
            # "When do I get off work" is a time: "At 5 pm", then his words
            # (2026-10-08: "you work 9 to 5" left the sum to him).
            clock = _work_clock(found.group("at"), which in ("get off", "finish", "clock out", "end"))
            told = f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
            return f"At {clock}. {told}" if clock else told
    return None


def _working_late_today() -> str | None:
    """His note from today saying he works late, said back; None without."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if not re.search(r"\bwork(?:ing)? late\b|\bworking (?:until|till) \d", said, re.I):
            continue
        try:
            day = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if day == today and not re.search(r"\btomorrow\b", said, re.I):
            return f"You told me {speech.as_she_says_it(said).rstrip('.')}"
        if day == today - dt.timedelta(days=1) and re.search(r"\btomorrow\b", said, re.I):
            return f"You told me yesterday {speech.as_she_says_it(said).rstrip('.')}"
    return None


_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _deliveries() -> str:
    """What he told her is on its way, newest first, in his words."""
    from aletheia import speech
    said, seen = [], set()
    for row in _notes():
        note = " ".join(str(row.get("text") or "").split())
        low = note.casefold()
        if re.search(r"\b(?:order|package|delivery|parcel|shipment|box)e?s?\b", low) \
                and re.search(r"\b(?:arriv\w*|coming|deliver\w*|here|showing up|out for delivery|should come)\b", low) \
                and low not in seen:
            seen.add(low)
            said.append(speech.as_she_says_it(note).rstrip("."))
    if not said:
        return ("You haven't told me about anything on its way. Say \"my package is arriving Thursday\" "
                "and I'll keep it.")
    return "You told me: " + speech.and_list(said[:4]) + "."


def _pet_due(rest) -> str | None:
    """What he told her his pet is due for, and when. None otherwise."""
    from aletheia import speech
    said = " ".join(str(rest or "").casefold().split())
    m = re.match(r"(?P<pet>dog|cat|puppy|kitten|pet)(?:'?s)? (?P<what>.+)", said)
    if not m:
        return None
    stem = m.group("what").split()[-1].rstrip("s")
    for row in _notes():
        note = " ".join(str(row.get("text") or "").split())
        low = note.casefold()
        if re.search(rf"\b{m.group('pet')}", low) and re.search(rf"\b{re.escape(stem)}", low) and re.search(r"\bdue\b|\bneeds?\b", low):
            return f"You told me: {speech.as_she_says_it(note).rstrip('.')}."
    return None


def _when_have(rest) -> str | None:
    """The days he told her somebody has something: the newest note naming
    who and what together with a day. None when no note says."""
    from aletheia import speech
    said = " ".join(str(rest or "").casefold().split())
    who, _, thing = said.partition(" have ")
    words = [w for w in re.findall(r"[a-z0-9']+", thing) if w not in ("my", "the", "a", "an", "our")]
    if not words:
        return None
    subject = {"i": r"^(?:i|we)\b", "we": r"^(?:we|i)\b"}.get(who, rf"^(?:my |our |the )?{re.escape(who.removeprefix('my '))}\b")
    for row in _notes():
        note = " ".join(str(row.get("text") or "").split())
        low = note.casefold()
        if not re.search(subject, low) or not all(re.search(rf"\b{re.escape(w.rstrip('s'))}", low) for w in words):
            continue
        if re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekday|weekend)s?\b|\bat \d", low):
            told = speech.as_she_says_it(note).rstrip(".")
            return f"You told me {told[:1].lower()}{told[1:]}."
    return None


def _do_i_have(rest) -> str | None:
    """Whether a thing of his falls on a day: his calendar first, then the
    days he told her it happens. None when neither says, so the question
    goes on as it was."""
    import datetime as dt
    from aletheia import localtime, speech
    said = " ".join(str(rest or "").casefold().split())
    thing = re.sub(r" (?:today|tonight|tomorrow|this weekend|(?:on |this |next )?(?:monday|tuesday|wednesday|thursday"
                   r"|friday|saturday|sunday))$", "", said).strip()
    if thing in ("work", "to work"):
        day = re.search(r"(today|tonight|tomorrow|this weekend|(?:on |this |next )?(?:monday|tuesday|wednesday|thursday"
                        r"|friday|saturday|sunday))\s*\??$", said)
        return _do_i_work(day.group(1)) if day else None
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    asked = re.search(r"(today|tonight|tomorrow|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\??$", said)
    if not asked:
        return None
    a = asked.group(1)
    if a == "this weekend":
        targets = [today + dt.timedelta(days=(5 - today.weekday()) % 7 + i) for i in (0, 1)]
    elif a in ("today", "tonight"):
        targets = [today]
    elif a == "tomorrow":
        targets = [today + dt.timedelta(days=1)]
    else:
        targets = [today + dt.timedelta(days=(_DAYS.index(a) - today.weekday()) % 7)]
    words = [w for w in re.findall(r"[a-z0-9']+", thing.casefold()) if w not in ("my", "the", "a", "an", "our")]
    if not words:
        return None
    for at, title, store in _coming():
        local = at.astimezone(tz)
        if store == "calendar" and local.date() in targets and all(re.search(rf"\b{re.escape(w.rstrip('s'))}", title.casefold())
                                                                   for w in words):
            return f"Yes - {title.rstrip('.')} {speech.humanize_time(at.isoformat())}."
    for row in _notes():
        note = " ".join(str(row.get("text") or "").split())
        low = note.casefold()
        if not all(re.search(rf"\b{re.escape(w.rstrip('s'))}", low) for w in words):
            continue
        # "The kids have no school on Monday" (2026-10-08), said this week,
        # answers "do the kids have school Monday".
        if a in _DAYS and re.search(rf"\bno {re.escape(words[0])}", low) and re.search(rf"\b{a}\b", low):
            try:
                noted = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
            except ValueError:
                noted = None
            if noted and 0 <= (targets[0] - noted).days < 7:
                told = speech.as_she_says_it(note).rstrip(".")
                return f"No - you told me {told[:1].lower()}{told[1:]}."
        plural = {i for i, d in enumerate(_DAYS) if re.search(rf"\b{d}s\b", low)}
        # "every Monday and Wednesday" (2026-10-08) is the same as "on Mondays and Wednesdays".
        every = re.search(r"\bevery ((?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                          r"(?:(?:,| and|, and) (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))*)", low)
        if every:
            plural |= {i for i, d in enumerate(_DAYS) if re.search(rf"\b{d}\b", every.group(1))}
        if re.search(r"\bweekdays\b", low):
            plural |= {0, 1, 2, 3, 4}
        if re.search(r"\bweekends\b", low):
            plural |= {5, 6}
        if plural:
            told = speech.as_she_says_it(note).rstrip(".")
            yes = any(d.weekday() in plural for d in targets)
            return f"{'Yes' if yes else 'No'} - you told me {told[:1].lower()}{told[1:]}."
    return None


def _left_on(thing: str, unit: str = "") -> str | None:
    """How long until something of his ends, from the note that said when:
    "my lease ends in June", "my license expires March 3". A bare month is
    counted in months and says so. None when no note dates it."""
    import datetime as dt
    from aletheia import localtime, speech
    words = [w for w in re.findall(r"[a-z0-9']+", str(thing or "").casefold()) if w not in ("my", "the", "our")]
    if not words:
        return None
    today = dt.datetime.now(localtime.operator_tz()).date()
    def names(text):
        return all(re.search(rf"\b{re.escape(w.rstrip('s'))}", text.casefold()) for w in words)
    for day, said in _noted_dates():
        if names(said) and day >= today:
            left = (day - today).days
            span = (speech.count_phrase(left, "day") if left < 21 else speech.count_phrase(round(left / 7), "week")
                    if left < 63 else f"about {speech.count_phrase(round(left / 30.44), 'month')}")
            told = speech.as_she_says_it(said).rstrip(".")
            return f"{span[:1].upper()}{span[1:]} - you told me {told[:1].lower()}{told[1:]}."
    month_re = "|".join(_MONTHS)
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        m = re.search(rf"\b(?:ends?|expires?|is up|runs out|is due|renews?) (?:in |at the end of )?(?P<mon>{month_re})(?: (?P<year>20\d\d))?\b", low)
        if m and names(said):
            number = _MONTHS.index(m.group("mon")) + 1
            year = int(m.group("year")) if m.group("year") else today.year + (number < today.month)
            months = (year - today.year) * 12 + number - today.month
            told = speech.as_she_says_it(said).rstrip(".")
            if months <= 0:
                return f"It's this month - you told me {told[:1].lower()}{told[1:]}."
            return f"About {speech.count_phrase(months, 'month')} - you told me {told[:1].lower()}{told[1:]}."
    return None


def _how_did_i_do(rest) -> str | None:
    """The grade or score he told her for a test, newest first. None when he
    told her none, so the question goes on."""
    from aletheia import speech
    thing = [w for w in re.findall(r"[a-z0-9']+", str(rest or "").casefold()) if w not in ("my", "the", "our")]
    if not thing:
        return None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if re.search(r"\b(?:got|scored|made|received|passed|failed)\b", low) \
                and all(re.search(rf"\b{re.escape(w.rstrip('s'))}", low) for w in thing):
            told = speech.as_she_says_it(said).rstrip(".")
            return f"You told me {told[:1].lower()}{told[1:]}."
    return None


def _last_ate() -> str:
    """When he last told her he ate, from his notes, newest first."""
    from aletheia import speech
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if re.match(r"(?:i|we) (?:just |finally )?(?:ate|had (?:breakfast|lunch|dinner|supper|brunch|a snack|a meal|something to eat))\b",
                    said.casefold()):
            told = speech.as_she_says_it(said).rstrip(".")
            return (f"You told me {told[:1].lower()}{told[1:]} - that was "
                    f"{speech.humanize_time(str(row.get('ts') or ''))}.")
    return "You haven't told me. Say \"I just ate\" next time and I'll keep track."


def _task_age(rest) -> str:
    """His oldest or newest open task, with when he added it."""
    from aletheia import speech, tasks
    live = sorted((t for t in tasks.all_tasks()
                   if str(t.get("status") or "").upper() not in _TASK_CLOSED and tasks.is_his(t)),
                  key=lambda t: str(t.get("created_at") or ""))
    if not live:
        return "Nothing open on your task list."
    oldest = str(rest or "").strip() in ("oldest", "first")
    task = live[0] if oldest else live[-1]
    what = str(task.get("description") or task["id"]).strip().rstrip(".")
    return (f"{what[:1].upper()}{what[1:]} - you added it {speech.humanize_time(str(task.get('created_at') or ''))}."
            + ("" if len(live) > 1 else " It's the only one open."))


def _do_i_work(rest) -> str | None:
    """Whether he works on a day, from what he told her: a day off named for
    it, then the days he said he works. None when he said neither."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    asked = re.sub(r"^(?:on|this|next) ", "", str(rest or "").strip())
    if asked == "weekend":
        targets = [today + dt.timedelta(days=(5 - today.weekday()) % 7 + i) for i in (0, 1)]
    elif asked in ("today", "tonight"):
        targets = [today]
    elif asked == "tomorrow":
        targets = [today + dt.timedelta(days=1)]
    elif asked in _DAYS:
        targets = [today + dt.timedelta(days=(_DAYS.index(asked) - today.weekday()) % 7)]
    else:
        return None
    hours = None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        try:
            on = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        off = re.search(r"\b(?:day|days|night|weekend) off\b|\b(?:off work|not working|don't work|do not work)\b"
                        r"|\bi'?m off (?:today|tomorrow|on |this |next |mon|tue|wed|thu|fri|sat|sun)", low)
        if off:
            named = {on: "today", on + dt.timedelta(days=1): "tomorrow"}
            hits = [d for d in targets if (named.get(d) and named[d] in low)
                    or _DAYS[d.weekday()] in low or ("weekend" in low and d.weekday() >= 5)]
            if hits:
                return f"No - you told me {speech.as_she_says_it(said).rstrip('.')[:1].lower()}{speech.as_she_says_it(said).rstrip('.')[1:]}."
        days = re.search(r"\bi work (?:on )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
                         r" (?:to|through|thru|-) (monday|tuesday|wednesday|thursday|friday|saturday|sunday)", low)
        if days and hours is None:
            first, last = _DAYS.index(days.group(1)), _DAYS.index(days.group(2))
            span = {(first + i) % 7 for i in range((last - first) % 7 + 1)}
            hours = all(d.weekday() in span for d in targets), said
        elif re.search(r"\bi work (?:on )?weekdays\b", low) and hours is None:
            hours = all(d.weekday() < 5 for d in targets), said
    if hours is not None:
        works, said = hours
        told = speech.as_she_says_it(said).rstrip(".")
        return f"{'Yes' if works else 'No'} - you told me {told[:1].lower()}{told[1:]}."
    # Nothing about days: say what she has, and what would settle it. No
    # model knows his work days either.
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if _START_NOTE.match(said.casefold()):
            told = speech.as_she_says_it(said).rstrip(".")
            return (f"You told me {told[:1].lower()}{told[1:]}, but not which days. "
                    "Say \"I work Monday to Friday\" and I'll know.")
    return "You haven't told me which days you work. Say \"I work Monday to Friday\" and I'll know."


def _work_clock(at: str, off: bool) -> str | None:
    """"5" in "I work 9 to 5" as the clock it means: "5 pm"."""
    m = re.fullmatch(r"(\d{1,2})(?::(\d\d))? ?(am|pm)?", str(at or "").strip())
    if not m:
        return None
    hour, minute = int(m.group(1)) % 12, int(m.group(2) or 0)
    pm = m.group(3) == "pm" or (not m.group(3) and (off and hour < 12 or not off and hour < 6))
    return f"{hour or 12}{f':{minute:02d}' if minute else ''} {'pm' if pm else 'am'}"


def _until_work(at: str, which: str, said: str) -> str | None:
    """"How long until I get off work": the gap to the time he told her."""
    import datetime as dt
    from aletheia import localtime, speech
    m = re.fullmatch(r"(\d{1,2})(?::(\d\d))? ?(am|pm)?", at.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)) % 12, int(m.group(2) or 0)
    off = which in ("get off", "finish", "clock out")
    # A bare hour is the working day: "9 to 5" starts in the morning and
    # ends in the afternoon.
    if m.group(3) == "pm" or (not m.group(3) and (off and hour < 12 or not off and hour < 6)):
        hour += 12 if hour < 12 else 0
    now = dt.datetime.now(localtime.operator_tz())
    then = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    clock = then.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    day = ""
    if then <= now:
        if off:
            return f"You're done for the day - you get off at {clock}."
        then, day = then + dt.timedelta(days=1), " tomorrow"
    left = int((then - now).total_seconds() // 60)
    h, mm = divmod(left, 60)
    gap = speech.count_phrase(mm, "minute") if not h else speech.count_phrase(h, "hour") + (
        f" and {speech.count_phrase(mm, 'minute')}" if mm else "")
    return f"{gap[:1].upper() + gap[1:]} - you {'get off' if off else 'start'} at {clock}{day}."


def _commute_told(leaving: bool) -> str | None:
    """Half of the commute sum, when half is all he gave (2026-10-08: "my
    commute is 25 minutes" then "how long is my commute" asked where work
    is). None when he said neither."""
    start = commute = None
    for row in _notes():
        low = " ".join(str(row.get("text") or "").split()).casefold()
        start = start or _START_NOTE.match(low)
        commute = commute or _COMMUTE_NOTE.match(low)
    if commute:
        minutes = int(commute.group("n")) * (60 if commute.group("u").startswith("hour") else 1)
        if not leaving:
            return (f"About {minutes} minutes, you told me. Say \"work is at\" and the address and I'll time it "
                    "with traffic.")
        return (f"You told me your commute is about {minutes} minutes, but not when you start. "
                "Say \"I start work at 9\" and I'll work it out.")
    if start and leaving:
        return (f"You start at {start.group('at').strip()}, but I don't know how long the trip is. "
                "Say \"my commute is 25 minutes\" and I'll work it out.")
    return None


def _leave_for_work() -> str | None:
    """When to leave, from his own notes: the start time less the commute.
    None unless he told her both - half of it is not an answer."""
    import datetime as dt
    start = commute = None
    for row in _notes():
        low = " ".join(str(row.get("text") or "").split()).casefold()
        start = start or _START_NOTE.match(low)
        commute = commute or _COMMUTE_NOTE.match(low)
    if not start or not commute:
        return None
    m = re.fullmatch(r"(\d{1,2})(?::(\d\d))? ?(am|pm)?", start.group("at").strip())
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "pm" and hour < 12:
        hour += 12
    elif m.group(3) == "am" and hour == 12:
        hour = 0
    elif not m.group(3) and hour < 5:
        hour += 12                      # "I start at 2" is the afternoon
    if hour > 23 or minute > 59:
        return None
    minutes = int(commute.group("n")) * (60 if commute.group("u").startswith("hour") else 1)
    leave = dt.datetime(2000, 1, 1, hour, minute) - dt.timedelta(minutes=minutes)
    said = leave.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    return (f"By {said} - you start at {start.group('at').strip()} and your commute is about {minutes} minutes, "
            "from what you've told me. That's without traffic.")


def _off_lists(text: str) -> str | None:
    """What came off his watch and reading lists, and what he says he is
    reading - "what have I watched", "how many books have I read this
    year", "what am I reading" (2026-10-07: all to a model). Read from his
    own lists and notes; None when he keeps no such list and said nothing."""
    import datetime as dt
    from aletheia import lists, speech
    g = _groups("off_lists", text)
    low = _tidy(text)
    if g.get("off_now") is not None or re.match(r"^what (?:book )?am i", low):
        for row in _notes():
            m = re.match(r"i(?:'ve| have|'m| am)? (?:just |currently |now |still )?(?:(?:started|begun|began) (?:reading|on)|reading) (?P<b>.+?)\.?$",
                         " ".join(str(row.get("text") or "").split()), re.I)
            if m:
                book = m.group("b")
                finished = any(re.match(rf"i (?:just )?(?:finished|read) {re.escape(book.casefold())}\b",
                                        str(r.get("text") or "").casefold()) for r in _notes())
                read = {t.casefold() for name in (h["name"] for h in lists.all_lists() if lists.kind_of(h["name"]) == "read")
                        for t, _at in lists.done_items(name)}
                if not finished and book.casefold() not in read:
                    return f"You told me you're reading {book}."
                return f"The last book you told me about was {book}, and you've finished it. Tell me when you start the next one."
        # nothing kept is said, not guessed at (2026-10-07: to a model)
        return "You haven't told me what you're reading. Say \"I started reading\" and the title, and I'll keep it."
    if g.get("off_tv") is not None or re.match(r"^what (?:show |series |tv show )?am i (?:currently )?watching", low):
        for row in _notes():
            m = re.match(r"i'?m watching (?P<s>.+?)\.?$", " ".join(str(row.get("text") or "").split()), re.I)
            if not m:
                continue
            show = m.group("s")
            gone = any(re.match(rf"i (?:just )?(?:finished|watched|finished watching) {re.escape(show.casefold())}\b",
                                str(r.get("text") or "").casefold()) for r in _notes())
            gone = gone or show.casefold() in {t.casefold() for name in (h["name"] for h in lists.all_lists()
                                                                          if lists.kind_of(h["name"]) == "watch")
                                               for t, _at in lists.done_items(name)}
            if gone:
                return f"The last show you told me about was {show}, and you've finished it. Tell me when you start the next one."
            episode = _episode_of(show)
            return f"You told me you're watching {show}" + (f", and you're on {episode}." if episode else ".")
        return "You haven't told me what you're watching. Say \"I started watching\" and the title, and I'll keep it."
    noun = g.get("off_n") or g.get("off_l") or ""
    want = "read" if (g.get("off_r") is not None or noun == "book" or noun == "books"
                      or re.search(r"\bread\b", low)) else "watch"
    done = [(t, at) for h in lists.all_lists() if lists.kind_of(h["name"]) == want for t, at in lists.done_items(h["name"])]
    # "I watched Oppenheimer" said as a note counts as much as a list
    # line ticked off (2026-10-07: "what movies have I watched" to a model).
    said = (r"i (?:just )?(?:finished reading|read) (?P<t>.+?)\.?$" if want == "read"
            else r"i (?:just )?(?:watched|finished watching|binged) (?P<t>.+?)(?: (?:last night|tonight|today|yesterday|again))?\.?$")
    seen = {t.casefold() for t, _ in done}
    # "I finished Dune" after "I started reading Dune" (2026-10-08: "what
    # books have I read" to a model). A bare "finished" is a book only when
    # it is one he said he was reading or meant to read.
    if want == "read":
        books = {m.group("b").casefold() for m in (
            re.match(r"i(?:'ve| have|'m| am)? (?:just |currently |now |still )?(?:(?:started|begun|began) (?:reading|on)|reading) (?P<b>.+?)\.?$",
                     " ".join(str(r.get("text") or "").split()), re.I) for r in _notes()) if m}
        books |= {t.casefold() for h in lists.all_lists() if lists.kind_of(h["name"]) == "read" for t in (lists.items(h["name"]) or [])}
        if books:
            said = (r"i (?:just )?(?:finished reading |read |finished (?:the book )?(?=(?:" + "|".join(re.escape(b) for b in books)
                    + r")\.?$))(?P<t>.+?)\.?$")
    for row in _notes():
        m = re.match(said, " ".join(str(row.get("text") or "").split()), re.I)
        if m and m.group("t").casefold() not in seen and not re.match(r"(?:it|that|the book|the movie|the show)$", m.group("t"), re.I):
            seen.add(m.group("t").casefold())
            done.append((m.group("t"), str(row.get("ts") or "")))
    if not done and not any(lists.kind_of(h["name"]) == want for h in lists.all_lists()):
        return None
    done.sort(key=lambda r: r[1], reverse=True)
    verb = "read" if want == "read" else "watched"
    if g.get("off_l"):
        if not done:
            return f"Nothing's come off your {'reading' if want == 'read' else 'watch'} list yet."
        # "Dune, from your list" when Dune was only ever said (2026-10-08).
        listed = {t.casefold() for h in lists.all_lists() if lists.kind_of(h["name"]) == want
                  for t, _at in lists.done_items(h["name"])}
        return f"{done[0][0]}, " + ("from your list." if done[0][0].casefold() in listed else "from what you've told me.")
    if g.get("off_y") or "this year" in low:
        year = str(dt.date.today().year)
        done = [r for r in done if r[1].startswith(year)]
    if g.get("off_n"):
        # "1 book this year, off your list" (2026-10-08) - the count came
        # from his notes too, and a goal he set is the other half.
        said = f"{speech.count_phrase(len(done), noun.rstrip('s'))}{' this year' if 'this year' in low else ''}, from what you've told me"
        goal = next((int(m.group(1)) for m in (re.search(r"\bgoal is to (?:read|watch) (\d{1,3}) " + re.escape(noun.rstrip("s")),
                                                          str(r.get("text") or ""), re.I) for r in _notes()) if m), None)
        if goal and goal > len(done):
            said += f" - {goal - len(done)} to go on your goal of {goal}"
        elif goal:
            said += f" - that's your goal of {goal} reached"
        return said + "."
    if not done:
        return f"Nothing's come off your {'reading' if want == 'read' else 'watch'} list yet."
    return f"You've {verb} {speech.and_list([t for t, _ in done[:6]])}" + (f" and {len(done) - 6} more." if len(done) > 6 else ".")


def _did_count(text: str) -> str | None:
    """"How many times did I walk the dog today": his notes saying he did,
    counted for the day, week or month he named. Never a guess."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("did_count", text)
    verb, thing = (g.get("dc_v") or "").strip(), (g.get("dc_o") or "").strip()
    if not verb or not thing:
        return None
    window = (g.get("dc_when") or "").strip() or "today"
    past = {"take": "took"}.get(verb) or _past_of(verb)
    words = [w for w in re.findall(r"[a-z0-9']+", thing.casefold()) if w not in ("the", "my", "our", "a", "an", "some")]
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = {"today": (midnight, midnight + dt.timedelta(days=1)),
                  "yesterday": (midnight - dt.timedelta(days=1), midnight),
                  "this week": (midnight - dt.timedelta(days=now.weekday()), midnight + dt.timedelta(days=1)),
                  "this month": (midnight.replace(day=1), midnight + dt.timedelta(days=1))}[window]
    n = 0
    for row in _notes():
        low = " ".join(str(row.get("text") or "").split()).casefold()
        if not re.match(rf"i (?:just )?{re.escape(past)}\b", low) or not all(re.search(rf"\b{re.escape(w)}", low) for w in words):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        n += start <= at < end
    if not n:
        return f"None {window} that you've told me. Say \"I {past} {thing}\" when you do and I'll keep count."
    return f"{speech.count_phrase(n, 'time')} {window}, from what you've told me."


_BILL_KEYS = (r"rent|mortgage|car payment|(?:car |auto |health |home |renters? |life |pet )?insurance(?: payment| bill)?"
              r"|phone bill|cell(?: phone)? bill|electric(?:ity)? bill|internet bill|wifi bill|water bill|gas bill|cable bill"
              r"|utilities|utility bill|student loans?(?: payment)?|loan payment|daycare|tuition|gym membership|hoa(?: fees?)?"
              r"|childcare|car loan|trash bill|sewer bill"
              r"|netflix|spotify|hulu|disney plus|disney\+|hbo max|hbo|youtube premium|youtube tv|amazon prime|prime membership|apple music|apple tv|icloud|peacock|paramount plus|audible|game pass|xbox game pass|playstation plus|ps plus|chatgpt|chat gpt|claude subscription|(?:[a-z]+ )?subscription")


def _cost_mine(text: str) -> str | None:
    """"How much is my rent", "what are my bills": his notes saying so
    ("my rent is 1500"). None when he never said - a model may know a
    figure from his mail; nothing here guesses one."""
    from aletheia import speech
    g = _groups("cost_mine", text)
    rows = [" ".join(str(r.get("text") or "").split()) for r in _notes()]
    if g.get("cost_bills") or g.get("cost_bills2") or g.get("cost_bills3"):
        bills, seen, total, whole = [], set(), 0.0, True
        for said in rows:
            m = re.match(rf"(?:my|our) (?P<k>{_BILL_KEYS}) (?:is|are) (?P<v>.*\d.*)$", said.casefold())
            if m and m.group("k") not in seen:
                seen.add(m.group("k"))
                bills.append(speech.as_she_says_it(said).rstrip(".").removeprefix("your ").removeprefix("Your "))
                n = re.search(r"\$?(\d[\d,]*(?:\.\d+)?)", m.group("v"))
                if not n:
                    whole = False
                    continue
                amount = float(n.group(1).replace(",", ""))
                v = m.group("v")
                total += (amount / 12 if re.search(r"\b(?:year|annual|yearly)\b", v)
                          else amount * 52 / 12 if re.search(r"\bweek(?:ly)?\b", v) else amount)
        if not bills:
            return None
        listed = f"From what you've told me: your {speech.and_list(bills)}."
        if g.get("cost_bills2") and whole:
            return f"About {_money(round(total))} a month. {listed}"
        return listed
    thing = " ".join(str(g.get("cost_mine") or g.get("cost_mine2") or g.get("cost_mine3") or "").casefold().split())
    # "How much do I spend on groceries a month" (2026-10-07: to a model,
    # with "I spent 60 on groceries" kept): what he told her he spent.
    if thing and g.get("cost_mine2") and not re.fullmatch(_BILL_KEYS, thing):
        return _spent(f"how much did i spend on {thing} this month")
    if not thing or not re.fullmatch(_BILL_KEYS, thing):
        return None
    for said in rows:
        if re.match(rf"(?:my|our|the) {re.escape(thing)} (?:is|are|was|were|costs?|came to|came out to) .*\d", said.casefold()):
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    # "How much is my rent" with nothing told (2026-10-07: to a model, which
    # has no way to know). Her memory first; then plainly not told. Only a
    # note naming ALL of it: "the electric bill" read back the water bill
    # beside it (2026-10-08).
    words = [w for w in re.findall(r"[a-z0-9]+", thing) if w not in ("my", "the", "our")]
    named = [said for said in rows if all(re.search(rf"\b{re.escape(w)}", said.casefold()) for w in words)]
    held = f"You told me: {speech.as_she_says_it(named[0]).rstrip('.')}." if named else None
    if held and not held.startswith("I have nothing"):
        # "My car insurance renews on December 1" is not what it costs
        # (2026-10-08: read back as the answer to "how much").
        if not re.search(r"\$\s?\d|\d\s*(?:k\b|dollars|bucks|a (?:month|year|week)|per |/)|\b(?:is|are|costs?|pay) \$?\d",
                         held.casefold()):
            return held.rstrip(".") + ", but not how much it is."
        return held
    said = {"hoa": "HOA", "hbo": "HBO", "hbo max": "HBO Max", "icloud": "iCloud", "chatgpt": "ChatGPT", "ps plus": "PS Plus"}.get(
        thing, thing.title() if re.fullmatch(r"netflix|spotify|hulu|disney plus|youtube premium|youtube tv|amazon prime|apple music"
                                              r"|apple tv|peacock|paramount plus|audible|game pass|xbox game pass|playstation plus", thing)
        else thing)
    return f"You haven't told me your {said}. Say \"my {said} is\" and the amount, and I'll remember it."


def _lent(text: str) -> str | None:
    """"Who has my drill": his note saying he lent it, in his words. Nothing
    kept is said as nothing kept (2026-10-07: to a model, which could only
    guess)."""
    from aletheia import speech
    g = _groups("lent", text)
    thing = " ".join(str(g.get("lent") or g.get("lent2") or "").split())
    stem = re.sub(r"(?:es|s)$", "", thing) or thing
    if len(stem) < 3:
        return None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if re.search(rf"\b{re.escape(stem)}", low) and re.search(r"\b(?:lent|loaned|gave|handed|borrowed|has|took|returned)\b"
                                                               r"|\bback\b", low):
            if re.search(r"\bback\b|\breturned\b", low):
                return f"You got it back - you told me: {speech.as_she_says_it(said).rstrip('.')}."
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    return f"You haven't told me you lent your {thing} to anybody."


def _get_up(rest: str = "") -> str:
    """His alarm that morning and the first thing on his calendar."""
    import datetime as dt
    from aletheia import localtime
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    day = now.date() + dt.timedelta(days=0 if "today" in str(rest or "") else 1)
    label = "today" if day == now.date() else "tomorrow"
    start = max(dt.datetime.now(dt.timezone.utc), dt.datetime.combine(day, dt.time(0, 0), tzinfo=tz))
    rows = [(at.astimezone(tz), text, store) for at, text, store in _coming(start) if at.astimezone(tz).date() == day]
    clock = lambda at: at.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
    alarm = next((at for at, text, store in rows if store == "reminder" and text.strip().casefold() == "wake up"), None)
    first = next(((at, text) for at, text, store in rows if store == "calendar"), None)
    said = []
    if first:
        said.append(f"Your first thing {label} is {first[1]} at {clock(first[0])}")
    if alarm:
        said.append(f"your alarm is set for {clock(alarm)}" if said else f"Your alarm is set for {clock(alarm)} {label}")
    elif first:
        said.append("and there's no alarm set")
    if not said:
        return f"Nothing on your calendar {label} and no alarm set, so whenever you like."
    out = said[0] + ("" if len(said) == 1 else (", " if said[1].startswith("your") else " ") + said[1])
    return out + "."


def _borrowed() -> str:
    """Every thing he said he borrowed and has not said he gave back."""
    from aletheia import speech
    out: dict[str, str] = {}
    for row in reversed(_notes()):
        low = " ".join(str(row.get("text") or "").split()).casefold().rstrip(".")
        m = re.fullmatch(r"i borrowed (?:a |an |the |some |his |her |their )?(?P<thing>[a-z][a-z' ]{1,30}?) from (?P<who>[a-z][a-z' ]{1,30})", low)
        if m:
            out[m.group("thing")] = m.group("who")
            continue
        back = re.fullmatch(r"i (?:gave|brought|took|returned) (?:back )?(?:the |his |her |their |[a-z]+'s )?(?P<thing>[a-z][a-z' ]{1,30}?)"
                            r"(?: back)?(?: to [a-z][a-z' ]{1,30})?", low)
        if back:
            out.pop(back.group("thing"), None)
    if not out:
        return "Nothing borrowed that you've told me about."
    said = [f"the {thing} from {('your ' + who.split(' ', 1)[1]) if who.startswith(('my ', 'our ')) else who.title()}"
            for thing, who in out.items()]
    return f"From what you've told me, you have {speech.and_list(said)}."


def _lent_out() -> str:
    """Every thing he said he lent and has not said came back."""
    from aletheia import speech
    out: dict[str, str] = {}
    for row in reversed(_notes()):
        low = " ".join(str(row.get("text") or "").split()).casefold().rstrip(".")
        m = (re.fullmatch(r"i (?:lent|loaned|gave) (?P<who>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) (?:my|our|the) (?P<thing>[a-z][a-z' ]{1,30})", low)
             or re.fullmatch(r"i (?:lent|loaned) (?:my|our|the) (?P<thing>[a-z][a-z' ]{1,30}?) to (?P<who>[a-z][a-z' ]{1,30})", low))
        if m:
            out[m.group("thing")] = m.group("who")
            continue
        back = (re.fullmatch(r"[a-z][a-z' ]{1,30}? (?:gave|brought|returned) (?:my|our|the) (?P<thing>[a-z][a-z' ]{1,30}?) back", low)
                # "Mike gave back my drill" (2026-10-08: still lent out)
                or re.fullmatch(r"[a-z][a-z' ]{1,30}? (?:gave|brought) back (?:my|our|the) (?P<thing>[a-z][a-z' ]{1,30})", low)
                or re.fullmatch(r"[a-z][a-z' ]{1,30}? returned (?:my|our|the) (?P<thing>[a-z][a-z' ]{1,30})", low)
                or re.fullmatch(r"i got (?:my|our|the) (?P<thing>[a-z][a-z' ]{1,30}?) back(?: from .+)?", low))
        if back:
            out.pop(back.group("thing"), None)
    if not out:
        return "Nothing lent out that you've told me about."
    def person(who):
        if who.startswith(("my ", "our ")):
            return "your " + who.split(" ", 1)[1]
        return "your " + who if who in _relation_words() else who.title()
    said = [f"your {thing} with {person(who)}" for thing, who in out.items()]
    return f"From what you've told me: {speech.and_list(said)}."


_KEPT = {
    # which: (what his note starts with, what a row is called, said when none)
    "idea": (r"idea: ", "idea", "No ideas kept yet. Say \"I have an idea for...\" and I'll hold on to it."),
    "learn": (r"i want to learn ", "thing to learn", "You haven't told me anything you want to learn."),
    "goal": (r"(?:my|one of my) (?:main |big |new )?(?:goals?|new year'?s resolutions?|resolutions?)\b", "goal",
             "You haven't told me your goals. Say \"my goal this year is...\" and I'll keep it."),
    "thanks": (r"grateful for ", "thing", "You haven't told me what you're grateful for yet."),
    "journal": (r"journal: ", "journal entry", "Nothing in your journal yet. Say \"journal entry\" and what you want to keep."),
}


def _kept(text: str) -> str | None:
    """His ideas, things to learn, goals, thanks and journal: the notes the
    voice layer writes with a word on the front, newest first, read back in
    his words with that word taken off."""
    import datetime as dt
    from aletheia import localtime, speech
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "kept"), None)
    g = found.groupdict() if found else {}
    # the markers are empty groups: which one matched is which list
    which = next((k for k in _KEPT if g.get("kept_" + k) is not None), None)
    if which is None:
        return None
    start, noun, none = _KEPT[which]
    when = (g.get("kept_when") or "").strip()
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    days = {"today": (today, today), "yesterday": (today - dt.timedelta(days=1),) * 2,
            "this week": (today - dt.timedelta(days=today.weekday()), today)}.get(when)
    rows = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if not re.match(start, said.casefold()):
            continue
        if days:
            try:
                day = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
            except ValueError:
                continue
            if not days[0] <= day <= days[1]:
                continue
        if which in ("idea", "journal"):
            said = said.split(":", 1)[1].strip()
        elif which == "thanks":
            said = said[len("grateful for "):]
        elif which == "goal":
            said = re.sub(r"^(?:my|one of my) .{0,40}?\b(?:is|are) ", "", said, flags=re.I)
        elif which == "learn":
            said = said[len("i want to learn "):]
        said = speech.as_she_says_it(said).rstrip(".")
        if said.casefold() not in {r.casefold() for r in rows}:
            rows.append(said)
    if not rows:
        return f"Nothing in your journal from {when}." if when else none
    head = {"idea": "Your ideas", "learn": "You want to learn", "goal": "Your goals",
            "thanks": "You're grateful for", "journal": "Your journal" + (f" from {when}" if when else "")}[which]
    if which in ("learn", "thanks"):
        out = f"{head} {speech.and_list(rows[:5])}"
    else:
        out = f"{head}, newest first: " + "; ".join(rows[:5]) if len(rows) > 1 else f"{head}: {rows[0]}"
    if len(rows) > 5:
        out += f"; and {len(rows) - 5} more"
    return out + "."


def _gift_for(text: str) -> str | None:
    """His gift list's lines for one person. "What should I get my sister"
    with nothing kept for her is a question a model can think about, so it
    is None; asked for the ideas he SAVED, none is the answer."""
    from aletheia import lists, speech
    g = _groups("gift_for", text)
    who = " ".join(str(g.get("gift_for") or g.get("gift_for2") or g.get("gift_for3") or g.get("gift_for4")
                       or g.get("gift_for5") or "").split())
    name = re.sub(r"^my ", "", who)
    if not name or name in ("you", "it", "that", "them", "him", "her"):
        return None
    try:
        rows = lists.items("gift") or []
    except Exception:
        return None
    alias = _name_for_relation(name) if " " not in name else None
    if not alias and " " not in name and name not in _relation_words():
        # "What should I get Sarah" reads "my wife loves tulips" too (2026-10-08)
        alias = next((rel for rel in _relation_words() if (_name_for_relation(rel) or "").casefold() == name.casefold()), None)
    hits = [r for r in rows if re.search(rf"\bfor (?:my )?(?:{re.escape(name)}|{re.escape(alias or name)})\b", r, re.I)]
    if hits:
        said = [re.sub(rf"\s+for (?:my )?(?:{re.escape(name)}|{re.escape(alias or name)})\b.*$", "", r, flags=re.I) for r in hits]
        shown = speech.as_she_says_it(who) if who.startswith("my ") or who in _relation_words() else _named(who)
        return f"Your gift ideas for {shown}: {speech.and_list(said)}."
    shown = speech.as_she_says_it(who) if who.startswith("my ") or who in _relation_words() else _named(who)
    # "What should I get my mom" with "my mom likes gardening" kept
    # (2026-10-08: "I can't think"): what he told her they like, as an idea.
    likes = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        m = re.match(rf"^(?:my )?(?:{re.escape(name)}|{re.escape(alias or name)}) (?:really )?(?:likes|loves|is into|enjoys"
                     rf"|is really into|has been wanting|wants|collects) (?P<what>.{{2,80}}?)\.?$", said, re.I)
        if m and m.group("what").casefold() not in {x.casefold() for x in likes}:
            likes.append(m.group("what"))
    if likes:
        return (f"Nothing saved as a gift idea, but you told me {shown} likes {speech.and_list(likes[:3])} - "
                "something for that would land. Just an idea.")
    if g.get("gift_for2"):
        return None
    return f"You haven't saved any gift ideas for {shown}. Say \"gift idea for {who}\" and what it is."


def _liked_how(text: str) -> str | None:
    """"How do I like my coffee": his note saying so. None when there is
    none - a taste is not a thing to guess at."""
    from aletheia import speech
    thing = str(_groups("liked_how", text).get("liked_how") or "")
    if not thing:
        return None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        # "my coffee order is an oat latte" says it too (2026-10-08)
        if re.match(rf"i (?:like|take|have|drink|want|prefer) my {re.escape(thing)}\b|my {re.escape(thing)} order is ", said.casefold()):
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    return f"You haven't told me how you like your {thing}. Tell me once and I'll remember it."


def _ate(text: str) -> str | None:
    """"What did I have for lunch yesterday": his notes saying "I had a
    burrito for lunch" or "I ate a salad", for that day (and that meal, when
    he named one). Nothing kept is said as nothing kept - never guessed."""
    import datetime as dt
    from aletheia import localtime, speech
    found = next((p.match(_tidy(text)) for n, p in PATTERNS if n == "ate"), None)
    if not found:
        return None
    meal = {"supper": "dinner"}.get(found.group("ate_meal") or "", found.group("ate_meal") or "")
    when = (found.group("ate_when") or found.group("ate_when2") or " today").strip()
    if when == "last night":
        when = "yesterday"
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    day = today - dt.timedelta(days=1) if when == "yesterday" else today
    said = re.compile(r"^(?:for (breakfast|lunch|dinner|supper|dessert)(?: today| yesterday| tonight)?,? )?"
                      r"i (?:just )?(?:had|ate|(?P<made>made|cooked|grabbed|ordered|got)) (.+?)(?: for (breakfast|lunch|dinner|supper|a snack|dessert))?"
                      r"(?: (today|yesterday|this morning|tonight|last night))?\.?$", re.IGNORECASE)
    hits: list[str] = []
    for row in _notes():
        m = said.match(" ".join(str(row.get("text") or "").split()))
        if not m:
            continue
        # "I made tacos for dinner" is a meal; "I got a haircut" is not
        if m.group("made") and not m.group(4):
            continue
        of = {"supper": "dinner", "a snack": "a snack"}.get((m.group(1) or m.group(4) or "").casefold(),
                                                            (m.group(1) or m.group(4) or "").casefold())
        if not of:
            # "I had pizza last night" is dinner (2026-10-07).
            of = {"last night": "dinner", "tonight": "dinner", "this morning": "breakfast"}.get((m.group(5) or "").casefold(), "")
        if meal and of != meal:
            continue
        try:
            noted = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if (m.group(5) or "").casefold() in ("yesterday", "last night"):
            noted -= dt.timedelta(days=1)
        if noted != day:
            continue
        food = speech.as_she_says_it(m.group(3).strip()).rstrip(".")
        hits.append(f"{food} for {of}" if of and not meal else food)
        if len(hits) >= 4:
            break
    named = f"for {meal} {when}" if meal else when
    if not hits:
        return (f"You didn't tell me what you had {named}. "
                "Say \"I had a burrito for lunch\" and I'll remember it.")
    hits.reverse()                      # newest first in the store; said in the order he ate
    return f"You told me you had {speech.and_list(hits)} {named}."


_READINGS = {"blood pressure": r"(?:blood pressure|bp)", "bp": r"(?:blood pressure|bp)",
             "heart rate": r"(?:resting )?(?:heart rate|pulse)", "resting heart rate": r"(?:resting )?(?:heart rate|pulse)",
             "pulse": r"(?:resting )?(?:heart rate|pulse)", "blood sugar": r"(?:blood sugar|glucose|blood glucose)",
             "glucose": r"(?:blood sugar|glucose|blood glucose)", "blood glucose": r"(?:blood sugar|glucose|blood glucose)",
             "a1c": r"a1c", "temperature": r"(?:temperature|temp)", "temp": r"(?:temperature|temp)",
             "oxygen": r"(?:oxygen|o2)", "o2": r"(?:oxygen|o2)"}


def _reading(text: str) -> str:
    """His newest reading of a number he told her (blood pressure, heart
    rate, blood sugar), with when. Never a verdict on it: that is his
    doctor's, and a model's guess at it is worse than none."""
    from aletheia import speech
    g = _groups("reading", text)
    asked = (g.get("reading") or "").strip()
    pattern = _READINGS.get(asked)
    if not pattern:
        return None
    named = "blood pressure" if asked == "bp" else asked
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        m = re.match(r"(?:my )?" + pattern + r" (?:was|is|reading was|came out|came out at|was at)? ?(.+?)\.?$", said, re.I)
        if not m or not re.search(r"\d", m.group(1)):
            continue
        value = re.sub(r" ?/ ?", " over ", m.group(1).strip())
        when = speech.humanize_time(str(row.get("ts") or "")) if row.get("ts") else ""
        return f"Your {named} was {value}" + (f", you told me {when}." if when else ".")
    return f"You haven't told me your {named}. Say \"my {named} was\" and the number, and I'll keep it."


def _arrived(text: str) -> str | None:
    """When he said he got somewhere today ("I'm at work", "I got home"),
    from the time on the note. None when he didn't say: a model may know."""
    import datetime as dt
    from aletheia import localtime
    g = _groups("arrived", text)
    place = (g.get("arrived") or "").strip()
    word = re.sub(r"^the ", "", place)
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    # "I'm at work" and "I'm done for the day" are kept as "started work"
    # and "finished work", the marks "how long did I work" reads.
    mark = (g.get("work_mark") or "").strip()
    wanted = ("started work" if mark in ("start", "clock in", "clock in to", "begin") or word == "work"
              else "finished work" if mark else "")
    if wanted:
        for row in _notes():
            if " ".join(str(row.get("text") or "").split()).casefold() != wanted:
                continue
            try:
                at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
            except ValueError:
                continue
            if at.date() == today:
                clock = at.strftime('%I:%M %p').lstrip('0').lower()
                return (f"At {clock} - that's when you told me you were done with work." if wanted == "finished work"
                        else f"At {clock} - that's when you told me you were at work.")
        if mark:
            return None
    said_it = re.compile(r"^(?:(?:i'?m|i am) (?:just |now |finally )?(?:at |back |back at |here at |in at )?"
                         r"|(?:i'?ve |i have |i )?(?:just |finally )?(?:got|arrived|made it|got back)(?: to| at)? )"
                         r"(?:the )?" + re.escape(word) + r"\b", re.I)
    # "I'm home" is answered "Welcome back" and kept as a turn of the
    # conversation rather than a note, so the conversation is read too.
    try:
        from aletheia import converse
        turns = [{"text": t.get("you"), "ts": t.get("at")} for t in reversed(converse._thread())]
    except Exception:  # noqa: BLE001
        turns = []
    for row in sorted(list(_notes()) + turns, key=lambda r: str(r.get("ts") or ""), reverse=True):
        said = re.sub(r"^(?:hey |ok |okay )?thea,? ", "", " ".join(str(row.get("text") or "").split()), flags=re.I)
        if not said_it.match(said):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        if at.date() != today:
            continue
        return f"At {at.strftime('%I:%M %p').lstrip('0').lower()} - that's when you told me you were {'home' if word == 'home' else 'at ' + place}."
    return None


def _loan_left(text: str) -> str:
    """What he told her is left on a loan, with when he said it."""
    from aletheia import speech
    g = _groups("loan_left", text)
    loan = (g.get("loan") or g.get("loan2") or "").strip()
    stem = re.sub(r"s$", "", loan.split()[-1])
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if re.match(r"i (?:still )?owe .*\bon (?:my |the )?(?:[a-z]+ )?" + re.escape(stem), said, re.I) \
                or re.match(r"(?:my |the )?(?:[a-z]+ )?" + re.escape(stem) + r"(?: loan)? (?:balance )?(?:is|has) ", said, re.I) and re.search(r"\d", said):
            when = speech.humanize_time(str(row.get("ts") or "")) if row.get("ts") else ""
            return f"You told me{' ' + when if when else ''}: {speech.as_she_says_it(said).rstrip('.')}."
    return (f"You haven't told me what's left on your {loan}. There's no bank connected - "
            f"say \"I owe\" and the amount \"on my {loan}\" and I'll keep it.")


def balances_told() -> str | None:
    """Balances he read off his bank and told her ("my checking account has
    2400"), newest per account, with when - the only balances she can hold
    with no bank connected. None when he told her none."""
    from aletheia import speech
    seen, said_back = set(), []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        m = re.match(r"(?:my |i have (?:about |around )?\$?[\d,.]+k?(?: dollars| bucks)? in (?:my )?)(?P<acct>checking|savings|bank|401k|ira|brokerage)", said, re.I)
        if not m or not re.search(r"\d", said) or m.group("acct").casefold() in seen:
            continue
        seen.add(m.group("acct").casefold())
        when = speech.humanize_time(str(row.get("ts") or "")) if row.get("ts") else ""
        said_back.append(speech.as_she_says_it(said).rstrip(".") + (f" ({when})" if when else ""))
    if not said_back:
        return None
    return "There's no bank connected, but you told me: " + speech.and_list(said_back[:4]) + "."


def _role_said(text: str) -> str | None:
    """"What did the doctor say": the newest note saying what the doctor
    said. None when there is none: it may be in his mail."""
    from aletheia import speech
    role = (_groups("role_said", text).get("role_said") or "").strip()
    if not role:
        return None
    said_it = re.compile(r"^(?:the|my|our) " + re.escape(role) + r" (?:said|says|told me|told us|thinks|recommended|wants me to)\b", re.I)
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if said_it.match(said):
            when = speech.humanize_time(str(row.get("ts") or "")) if row.get("ts") else ""
            return f"You told me{' ' + when if when else ''}: {speech.as_she_says_it(said).rstrip('.')}."
    return None


def _tasks_verb(text: str) -> str | None:
    """His open tasks that start with the verb he asked by, with when
    they're due. None when none do: the thing may be in his notes or mail."""
    from aletheia import speech, tasks
    g = _groups("tasks_verb", text)
    verb = (g.get("tv") or g.get("tv2") or {"calls": "call", "emails": "email", "returns": "return", "payments": "pay",
                                              "errands": ""}.get(g.get("tv3") or "", "") or "").strip()
    if g.get("tv3") == "errands":
        return _tasks()
    if not verb:
        return None
    live = [t for t in tasks.all_tasks()
            if str(t.get("status") or "").upper() not in _TASK_CLOSED and tasks.is_his(t)]
    head = verb.split()[0]
    hits = []
    for t in live:
        what = " ".join(str(t.get("description") or "").split()).rstrip(".")
        if re.match(re.escape(verb if head in ("pick", "drop", "clean", "look", "follow") else head) + r"\b", what, re.I):
            when = tasks.parse_deadline(t.get("deadline"))
            due = re.sub(r" at 11:59 ?pm$", "", speech.humanize_time(when.isoformat())) if when else ""
            hits.append(what + (f" by {due}" if due else ""))     # a comma would collide in a list
    if not hits:
        return None
    if len(hits) == 1:
        return f"{hits[0][:1].upper() + hits[0][1:]}."
    return f"{speech.count_phrase(len(hits), 'thing')} on your list: {speech.and_list(hits)}."


def _the_list() -> str | None:
    """His shopping list, unless the last few turns were about a list of his
    own - then None, and `voice` reads that one."""
    try:
        from aletheia import voice
        if voice._the_named_list_just_used()[0]:
            return None
    except Exception:  # noqa: BLE001
        pass
    return _shopping()


def _no_password(text: str = "") -> str:
    """The no-passwords line - unless her memory holds one he explicitly
    asked her to keep, which is then read back as `_recall` would have."""
    from aletheia import memory, voice
    asked = [w for w in re.findall(r"[a-z0-9]+", _tidy(text)) if w not in _STOP_WORDS
             and w not in ("password", "passcode", "passphrase", "remember", "know", "tell", "give", "read", "remind",
                           "what", "whats", "s", "is", "was", "the", "for", "to", "on", "of", "do", "you", "have")]
    try:
        held = memory.everything(max_chars=8000)
    except Exception:  # noqa: BLE001
        held = {}
    for _domain, entries in held.items():
        for key, row in entries.items():
            label = key.replace("_", " ")
            if re.search(r"pass(?:word|code|phrase)", label.casefold()) and all(w in label.casefold() for w in asked):
                value = row.get("value") if isinstance(row, dict) else row
                return f"{label[:1].upper() + label[1:]}: {value}."
    return voice._NO_PASSWORDS


def _awake_for() -> str:
    """Since the time he said he woke up today, or how to tell her."""
    import datetime as dt
    from aletheia import localtime, speech
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        m = re.match(r"i (?:woke up|got up) (?:at |around |about )?(\d{1,2})(?::(\d\d))? ?(am|pm|a\.m\.|p\.m\.)?(?:\W|$)", said)
        if not m:
            continue
        try:
            noted = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        if noted.date() != now.date():
            break
        hour = int(m.group(1)) % 12 + (12 if (m.group(3) or "").startswith("p") else 0)
        woke = now.replace(hour=hour, minute=int(m.group(2) or 0), second=0, microsecond=0)
        if woke > now or hour > 23:
            break
        h, mm = divmod(int((now - woke).total_seconds() // 60), 60)
        span = " and ".join(x for x in (speech.count_phrase(h, "hour") if h else "",
                                         speech.count_phrase(mm, "minute") if mm else "") if x) or "a moment"
        return f"About {span} - you told me you woke up at {woke.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower()}."
    return "You haven't told me when you woke up today. Say \"I woke up at 7\" and I'll work it out."


def _woke_usual(text: str) -> str:
    """"What time do I usually wake up": the middle of the times he told her
    in the last month. Once is not "usually", and it says so."""
    import datetime as dt
    from aletheia import localtime
    low = _tidy(text)
    bed = bool(re.search(r"\b(?:bed|bedtime|sleep|asleep)\b", low))
    kin = ("went to bed", "went to sleep", "fell asleep") if bed else ("woke up", "got up")
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    minutes = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        m = re.match(r"i (?:" + "|".join(kin) + r") (?:at |around |about )?(\d{1,2})(?::(\d\d))? ?(am|pm|a\.m\.|p\.m\.)?(?:\W|$)", said)
        if not m:
            continue
        try:
            noted = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
            if (now - noted).days > 30:
                continue
        except ValueError:
            pass
        hour, mins, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "")
        if hour > 23 or mins > 59:
            continue
        if half == "pm" and hour < 12:
            hour += 12
        elif half == "am" and hour == 12:
            hour = 0
        elif not half and bed and 6 <= hour <= 11:
            hour += 12          # "went to bed at 11" is the evening
        elif not half and bed and hour == 12:
            hour = 0            # "went to bed at 12:30" is half past midnight
        at = hour * 60 + mins
        if bed and at < 12 * 60:
            at += 24 * 60       # after midnight is later the same night
        minutes.append(at)
    if len(minutes) < 2:
        # "I usually go to bed at 11" (2026-10-07) is the answer itself.
        habit = re.compile(r"\bi (?:usually |normally |always |tend to )?(?:" + ("go to bed|go to sleep" if bed else "wake up|get up")
                           + r") (?:at |around |by )?\d", re.I)
        for row in _notes():
            said = " ".join(str(row.get("text") or "").split())
            if habit.search(said) and re.search(r"\b(?:usually|normally|always|tend to|most (?:nights|days|mornings)|every (?:night|day|morning)|on weekdays)\b", said, re.I):
                from aletheia import speech
                return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
        if not minutes:
            # A bedtime reminder is his bedtime too, and an alarm his wake-up
            # time (2026-10-08).
            try:
                from aletheia import intercom, speech
                found, _why = intercom._one_reminder("bed" if bed else "wake up")
                if found is not None:
                    what, _, when = intercom._reminder_words(found).partition(" — ")
                    if when and bed:
                        return f"You haven't said when you go to bed, but your reminder to {speech._yours(what)} is {when}."
                    if when:
                        return f"You haven't said when you wake up, but your alarm is set for {when}."
            except Exception:
                pass
        return _woke("go to bed" if bed else "wake up") + (
            " That's the only time you've told me, so I can't say what's usual yet." if minutes else "")
    minutes.sort()
    middle = minutes[len(minutes) // 2] if len(minutes) % 2 else (minutes[len(minutes) // 2 - 1] + minutes[len(minutes) // 2]) // 2
    middle = int(round(middle / 5.0) * 5) % (24 * 60)
    clock = dt.time(middle // 60, middle % 60)
    said = clock.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").replace("AM", "am").replace("PM", "pm")
    return f"Around {said} - from the {len(minutes)} times you've told me this month."


def _woke(act: str) -> str:
    """"What time did I wake up": the newest note saying when he did."""
    from aletheia import speech
    said = {"wake up": "woke up", "get up": "got up", "go to bed": "went to bed", "go to sleep": "went to sleep",
            "fall asleep": "fell asleep"}.get(act.strip(), act.strip())
    kin = ("woke up", "got up") if said in ("woke up", "got up") else ("went to bed", "went to sleep", "fell asleep")
    for row in _notes():
        text = " ".join(str(row.get("text") or "").split())
        m = re.match(r"i (" + "|".join(kin) + r") (?:at |around |about )?(.+?)\.?$", text, re.IGNORECASE)
        if not m:
            continue
        at, day = re.match(r"(.+?)(?: (today|this morning|last night|yesterday))?$", m.group(2)).groups()
        when = f" {day.casefold()}" if day else ""
        if not day and row.get("ts"):
            # "You told me you woke up at 7, told me today at 11:40 am" (2026-10-07).
            try:
                import datetime as dt
                from aletheia import localtime
                tz = localtime.operator_tz()
                noted = dt.datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).astimezone(tz)
                ago = (dt.datetime.now(tz).date() - noted.date()).days
                woke = kin[0] == "woke up"
                when = (" this morning" if woke else " last night" if noted.hour < 12 else " tonight") if ago == 0 else \
                       (" yesterday" if woke else " the night before last" if noted.hour < 12 else " last night") if ago == 1 else \
                       f" on {(noted.date() - dt.timedelta(days=0 if woke or noted.hour >= 12 else 1)).strftime('%A')}"
            except (ValueError, TypeError):
                when = ""
        return f"You told me you {m.group(1).casefold()} at {at}{when}."
    return f"You haven't told me. Say \"I {said} at {7 if kin[0] == 'woke up' else 11}\" and I'll remember it."


_HEIGHT = re.compile(r"(?:i'?m|i am|my height is) (?:about |around )?(?:(?P<ft>\d)(?:'| foot| feet| ft) ?(?:(?P<inch>\d{1,2})(?:\"|''| inches| in)?)?"
                     r"|(?P<cm>\d{3}) ?cm|(?P<m>1\.\d\d) ?m)\b")
_WEIGHED = re.compile(r"^i(?: weigh| weighed| am|'m) (?P<n>\d{2,3}(?:\.\d)?)(?: ?(?P<u>pounds|lbs?|kg|kilos|kilograms))?")


def _height_m() -> tuple[float, str] | None:
    """(metres, as he said it) from the newest note giving his height."""
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        m = _HEIGHT.match(said.casefold())
        if m:
            if m.group("ft"):
                metres = (int(m.group("ft")) * 12 + int(m.group("inch") or 0)) * 0.0254
            elif m.group("cm"):
                metres = int(m.group("cm")) / 100
            else:
                metres = float(m.group("m"))
            return metres, said
    return None


def _weights() -> list[tuple[str, float]]:
    """(when, kg) for every weight he told her, newest first."""
    out = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        m = _WEIGHED.match(said)
        if m and (said.startswith("i weigh") or m.group("u")):
            n = float(m.group("n"))
            out.append((_when_weighed(said, str(row.get("ts") or "")), n if (m.group("u") or "").startswith(("kg", "kilo")) else n * 0.4536))
    # "I weighed 185 last week", said after today's 182, is the older one
    return sorted(out, key=lambda r: r[0], reverse=True)


def _when_weighed(said: str, ts: str) -> str:
    """When a weigh-in was, not when he said it: "last week" moves it back."""
    import datetime as dt
    m = re.search(r"\b(yesterday|last week|last month|a week ago|a month ago|(?:two|three|2|3) weeks ago)$", said)
    if not m or not ts:
        return ts
    back = {"yesterday": 1, "last week": 7, "a week ago": 7, "last month": 30, "a month ago": 30, "two weeks ago": 14,
            "2 weeks ago": 14, "three weeks ago": 21, "3 weeks ago": 21}[m.group(1)]
    try:
        return (dt.datetime.fromisoformat(ts.replace("Z", "+00:00")) - dt.timedelta(days=back)).isoformat()
    except ValueError:
        return ts


def _body(text: str) -> str | None:
    """Height, BMI and weight lost, from what he told her - and the
    arithmetic said as arithmetic, never as medical advice."""
    from aletheia import speech
    asked = _tidy(text)
    if "tall" in asked or "height" in asked:
        h = _height_m()
        if not h:
            return "You haven't told me your height. Say \"I'm 5 foot 10\" and I'll remember it."
        return f"You told me: {speech.as_she_says_it(h[1]).rstrip('.')}."
    if "bmi" in asked or "body mass" in asked:
        h, w = _height_m(), _weights()
        missing = [x for x, have in (("your height", h), ("your weight", w)) if not have]
        if missing:
            return f"I need {speech.and_list(missing)} for that - tell me and I'll work it out."
        bmi = w[0][1] / (h[0] ** 2)
        return f"About {bmi:.1f}, from the height and weight you told me."
    w = _weights()
    if re.search(r"\b(?:goal|target|to go|to lose|until my goal)\b", asked):
        goal = None
        for row in _notes():
            g = re.match(r"(?:my )?(?:goal|target) weight is (?:about |around )?(\d{2,3}(?:\.\d)?)\s*(kg|kilos?|pounds|lbs?)?",
                         " ".join(str(row.get("text") or "").split()).casefold())
            if g:
                goal = float(g.group(1)) * (1 / 0.4536 if (g.group(2) or "").startswith("k") else 1)
                break
        if goal is None:
            # "How far am I from my goal" may be a savings goal: not ours to deny.
            if re.search(r"(?:from|to) (?:my|reaching my) (?:goal|target)\s*\??$", asked):
                return None
            return "You haven't told me a goal weight. Say \"my goal weight is\" and the number."
        if not w:
            return f"Your goal is {goal:.0f} pounds, but you haven't told me what you weigh. Say \"I weigh\" and the number."
        now = w[0][1] / 0.4536
        gap = now - goal
        if abs(gap) < 0.5:
            return f"You're there - {now:.0f} pounds, and your goal is {goal:.0f}."
        return (f"{abs(gap):.0f} pounds to {'go' if gap > 0 else 'gain'}: you told me {now:.0f}, and your goal is {goal:.0f}.")
    m = re.search(r"\b(?:weigh|weight)\b(?: (?P<when>last week|last month|yesterday|a week ago|a month ago|last time))?\s*\??$", asked)
    if m and not re.search(r"\b(?:lost|lose|gained|gain|doing|how's|how is)\b", asked):
        if not w:
            return "You haven't told me your weight yet. Say \"I weigh\" and the number."
        import datetime as dt
        back = {"yesterday": 1, "last week": 7, "a week ago": 7, "last month": 30, "a month ago": 30}.get(m.group("when") or "")
        pick = w[0]
        if back:
            cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=back)
            older = [r for r in w if r[0] and dt.datetime.fromisoformat(r[0].replace("Z", "+00:00")) <= cut + dt.timedelta(hours=12)]
            if not older:
                first = speech.humanize_time(w[-1][0]) if w[-1][0] else "before"
                return f"You hadn't told me a weight by then - the first was {first}, {w[-1][1] / 0.4536:.0f} pounds."
            pick = older[0]
        elif m.group("when") == "last time" and len(w) > 1:
            pick = w[1]
        when = speech.humanize_time(pick[0]) if pick[0] else "the last time you told me"
        return f"{pick[1] / 0.4536:.0f} pounds, {when}."
    if len(w) < 2:
        # "I lost 2 pounds" said as a change, with no second weigh-in.
        change = 0.0
        for row in _notes():
            c = re.match(r"i (lost|dropped|gained|put on) (\d{1,3}(?:\.\d)?) ?(pounds?|lbs?|kg|kilos?)",
                         " ".join(str(row.get("text") or "").split()).casefold())
            if c:
                n = float(c.group(2)) * (2.2046 if c.group(3).startswith("k") else 1)
                change += n if c.group(1) in ("lost", "dropped") else -n
        if change:
            return f"{'Down' if change > 0 else 'Up'} about {abs(change):.0f} pounds, from what you've told me."
        if not w and re.fullmatch(r"how much have i (?:lost|gained)(?: so far)?\??", asked):
            return None  # "how much have I lost" with no weights may be money
        return ("I only have one weight from you so far - tell me again as it changes and I'll keep track."
                if w else "You haven't told me your weight yet. Say \"I weigh\" and the number.")
    pounds = (w[-1][1] - w[0][1]) / 0.4536
    first = speech.humanize_time(w[-1][0]) if w[-1][0] else "the first time"
    # the day is the point; "since 30 September at 9 pm" is a clock nobody weighed at
    first = re.sub(r" at \d{1,2}(?::\d\d)? ?(?:am|pm)$", "", first)
    # "Down about 2 pounds since today" (2026-10-08): the first weigh-in was earlier today.
    first = {"today": "earlier today", "tonight": "earlier tonight"}.get(first.casefold(), first)
    if abs(pounds) < 0.5:
        return f"About the same as {first}, from what you've told me."
    return f"{'Down' if pounds > 0 else 'Up'} about {abs(pounds):.0f} pounds since {first}, from what you've told me."


_IRREGULAR_PLURALS = {
    "moose": "moose", "deer": "deer", "sheep": "sheep", "fish": "fish", "series": "series", "species": "species",
    "aircraft": "aircraft", "bison": "bison", "salmon": "salmon", "trout": "trout", "mouse": "mice", "louse": "lice",
    "goose": "geese", "tooth": "teeth", "foot": "feet", "man": "men", "woman": "women", "child": "children",
    "person": "people", "ox": "oxen", "cactus": "cacti", "fungus": "fungi", "nucleus": "nuclei", "octopus": "octopuses",
    "criterion": "criteria", "phenomenon": "phenomena", "analysis": "analyses", "crisis": "crises", "thesis": "theses",
    "axis": "axes", "basis": "bases", "diagnosis": "diagnoses", "knife": "knives", "wife": "wives", "life": "lives",
    "leaf": "leaves", "half": "halves", "wolf": "wolves", "calf": "calves", "shelf": "shelves", "loaf": "loaves",
    "thief": "thieves", "elf": "elves", "self": "selves", "roof": "roofs", "chef": "chefs", "belief": "beliefs",
    "chief": "chiefs", "cliff": "cliffs", "potato": "potatoes", "tomato": "tomatoes", "hero": "heroes", "echo": "echoes",
    "veto": "vetoes", "piano": "pianos", "photo": "photos", "radio": "radios", "zoo": "zoos", "video": "videos",
    "datum": "data", "medium": "media", "bacterium": "bacteria", "curriculum": "curricula", "index": "indexes",
    "appendix": "appendices", "die": "dice", "bus": "buses", "quiz": "quizzes", "alumnus": "alumni", "virus": "viruses",
    "campus": "campuses", "focus": "focuses", "radius": "radii", "stimulus": "stimuli", "syllabus": "syllabuses",
    "stomach": "stomachs", "monarch": "monarchs", "epoch": "epochs", "tech": "techs", "patriarch": "patriarchs",
}


def _plural(text: str) -> str | None:
    """A plural by the ordinary rules, or from the list of ones that break
    them. A word the rules would guess at (most -f, -o, -us, -is, -on
    endings) is left to a model rather than guessed."""
    g = _groups("plural", text)
    word = str(g.get("plural") or g.get("plural2") or "").casefold()
    if not word:
        return None
    said = _IRREGULAR_PLURALS.get(word)
    if not said:
        if re.search(r"(?:f|fe|o|us|is|on|um|ix|ex|a)$", word):
            return None
        if re.search(r"(?:s|x|z|ch|sh)$", word):
            said = word + "es"
        elif re.search(r"[^aeiou]y$", word):
            said = word[:-1] + "ies"
        else:
            said = word + "s"
    return f"{said[:1].upper() + said[1:]}." if said != word else f"{word[:1].upper() + word[1:]} - it's the same in the plural."


def _habit(text: str) -> str | None:
    """Streaks, counts and a weekly goal, from what he told her he did.
    Never a guess: nothing kept is said as nothing kept."""
    import datetime as dt
    from aletheia import localtime, speech
    g = _groups("habit", text)
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)

    def dated(row):
        try:
            return dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            return None

    verb = (g.get("hb_streak") or g.get("hb_streak2") or "").strip()
    if verb:
        head, _, rest = verb.partition(" ")
        past = {"run": "ran", "swim": "swam", "go": "went", "read": "read", "do": "did", "eat": "ate", "ride": "rode",
                "write": "wrote", "drink": "drank", "sleep": "slept", "lift": "lifted"}.get(head) or (
            head if head.endswith("ed") else _past_of(head))
        said_re = re.compile(rf"^i (?:just )?{re.escape(past)}\b" + (rf".*\b{re.escape(rest)}" if rest else ""))
        days = {dated(r).date() for r in _notes() if dated(r) and said_re.search(" ".join(str(r.get("text") or "").split()).casefold())}
        if not days:
            return f"You haven't told me you {past}{' ' + rest if rest else ''}. Say \"I {past}{' ' + rest if rest else ''}\" when you do and I'll keep count."
        day = now.date() if now.date() in days else now.date() - dt.timedelta(days=1)
        run = 0
        while day in days:
            run += 1
            day -= dt.timedelta(days=1)
        if not run:
            last = max(days)
            return f"No streak right now - the last day you told me was {last.strftime('%A %d %B').replace(' 0', ' ')}."
        if run == 1 and now.date() in days:
            return "Just today so far - one day."
        today = " counting today" if now.date() in days else ", not counting today yet"
        return f"{speech.count_phrase(run, 'day')} in a row{',' if today.startswith(' c') else ''}{today}."
    what = (g.get("hb_count") or "").strip()
    if what:
        when = (g.get("hb_when") or "this week").strip()
        start = {"today": now.replace(hour=0, minute=0, second=0, microsecond=0),
                 "yesterday": (now - dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
                 "this month": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)}.get(
            when, (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0))
        end = start + dt.timedelta(days=1) if when == "yesterday" else now + dt.timedelta(days=1)
        smoke = what in ("cigarettes", "smokes")
        nouns = (r"cigarettes?|smokes?" if smoke else
                 r"drinks?|beers?|glass(?:es)? of (?:wine|champagne)|wines?|shots?|cocktails?|margaritas?|seltzers?"
                 if what in ("drinks", "beers", "glasses of wine") else re.escape(what.rstrip("s")) + "s?")
        verbs = r"smoked|had" if smoke else r"had|drank|drunk"
        total = 0
        for row in _notes():
            at = dated(row)
            if not at or not (start <= at < end):
                continue
            low = " ".join(str(row.get("text") or "").split()).casefold()
            m = re.match(rf"i (?:just )?(?:{verbs}) (?P<n>\d+|a couple(?: of)?|a few|an?|one|two|three|four|five|six|seven|eight|nine|ten)"
                         rf" (?:more )?(?:{nouns})\b", low)
            if m:
                total += int(m.group("n")) if m.group("n").isdigit() else {"a couple": 2, "a couple of": 2, "a few": 3}.get(m.group("n")) or int(_COUNT_WORDS.get(m.group("n"), 1))
        noun = "cigarette" if smoke else "drink" if what in ("drinks", "beers", "glasses of wine") else what.rstrip("s")
        if not total:
            return f"None {when} that you've told me."
        return f"{speech.count_phrase(total, noun)} {when}, from what you've told me."
    if g.get("hb_goal") or g.get("hb_goal2"):
        goal = None
        for row in _notes():
            m = re.match(r"i (?:want|need|plan|am going|'m going|aim) to (?:work out|exercise|go to the gym|hit the gym|train)"
                         r" (\d|one|two|three|four|five|six|seven) (?:times|days) (?:a|per|each) week",
                         " ".join(str(row.get("text") or "").split()).casefold())
            if m:
                goal = int(m.group(1)) if m.group(1).isdigit() else int(_COUNT_WORDS[m.group(1)])
                break
        done = _went("how many times did i work out this week") or ""
        n = int(re.match(r"(\d+)", done).group(1)) if re.match(r"\d+", done) else 0
        if goal is None:
            return (f"You haven't told me a goal. Say \"I want to work out 4 times a week\" and I'll keep you to it. "
                    f"So far this week: {speech.count_phrase(n, 'workout')}.")
        left = goal - n
        days_left = 6 - now.weekday()
        if left <= 0:
            return f"Yes - {speech.count_phrase(n, 'workout')} this week, and your goal is {goal}."
        return (f"{speech.count_phrase(n, 'workout')} so far this week, {left} to go for your goal of {goal}, "
                f"with {speech.count_phrase(days_left, 'day')} left after today.")
    return None


def _their_person(text: str) -> str | None:
    """Somebody's person, from his note: "Jen's kid's name is Mia", "Bob's
    wife is Linda", "Bob is married to Linda". None when no note says."""
    from aletheia import speech
    g = _groups("their_person", text)
    who = (g.get("tp_who") or g.get("tp_who2") or "").casefold()
    rel = (g.get("tp_rel") or "").casefold().strip()
    rels = [rel] if rel else ["wife", "husband", "partner", "spouse", "fiancee", "fiance"]
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if any(re.match(rf"{re.escape(who)}'s {re.escape(r)}s?(?:'s name)? (?:is|are) ", low) for r in rels) \
                or (not rel and re.match(rf"{re.escape(who)} is married to ", low)):
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    return None


def _it_due() -> str | None:
    """The task his last exchange named, and when it is due."""
    from aletheia import voice
    task = voice._the_task_just_added()
    return _task_due(task) if task else None


def _starts_when(text: str) -> str | None:
    """"When does school start": the note naming it AND the change asked
    about, so "school pictures are on the 14th" is not the answer to when
    school starts. No such note falls back to everything said about it."""
    from aletheia import speech
    g = _groups("starts_when", text)
    what = " ".join(str(g.get("sw_what") or "").casefold().split())
    words = [w for w in re.findall(r"[a-z0-9]+", what) if w not in _STOP_WORDS and w != "s"]
    if not words:
        return None
    verb = {"starting": "start", "beginning": "begin", "ending": "end", "over": "over", "get out": "out", "let out": "out"}.get(
        g.get("sw_verb") or "", g.get("sw_verb") or "")
    kin = {"start": r"start|begin|first day|back", "begin": r"start|begin|first day|back", "end": r"end|finish|over|last day|out",
           "finish": r"end|finish|over|last day|out", "over": r"end|finish|over|last day|out", "out": r"out|end|over|last day",
           "open": r"open", "close": r"close|shut"}.get(verb, re.escape(verb))
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if all(re.search(rf"\b{re.escape(w)}", low) for w in words) and re.search(rf"\b(?:{kin})", low):
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    return _recall(what)


def _when_note(text: str) -> str | None:
    """The newest note naming the thing with a day or a time in it."""
    from aletheia import speech
    thing = " ".join(str(_groups("when_note", text).get("when_note") or "").casefold().split())
    words = [w for w in re.findall(r"[a-z0-9]+", thing) if w not in _STOP_WORDS and w not in ("s",)]
    if not words:
        return None
    stems = [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words]
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if all(re.search(rf"\b{re.escape(w)}", low) for w in stems) and re.search(
                r"\d|\b(?:mon|tues|wednes|thurs|fri|satur|sun|week)days?\b|\b(?:today|tonight|tomorrow|weekends?)\b", low):
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    # "When is the recital" after "my daughter has a recital on Friday at 6"
    # went on the calendar (2026-10-08: to a model). The soonest one.
    for at, what, store in _coming():
        low = str(what or "").casefold()
        if store == "calendar" and all(re.search(rf"\b{re.escape(w)}", low) for w in stems):
            name = str(what).strip().rstrip(".")
            if name[:1].islower() and not re.match(r"(?:my|the|a|an|our) ", name):
                name = "your " + name
            return f"{name[:1].upper() + name[1:]} is {speech.humanize_time(at.isoformat())}."
    # "When is our anniversary" with nothing told (2026-10-08: "I can't
    # think") - a date only he knows, so the answer is how to tell her.
    whose = re.match(r"when (?:is|'s) (?P<whose>my|our) ", _tidy(text))
    if whose and re.fullmatch(r"(?:wedding )?anniversary", thing):
        return (f"You haven't told me. Say \"{whose.group('whose')} anniversary is\" and the date, "
                "and I'll remember it.")
    return None


def _their_fact(text: str) -> str | None:
    """"Who is Leo's teacher", "what school does Leo go to", "what is my
    daughter allergic to": his note naming it. Also asked by the name he
    told her for a relation ("my son" is Leo). None when no note says."""
    from aletheia import speech
    g = _groups("their_fact", text)
    who = " ".join(str(g.get("tf_who") or g.get("tf_who2") or g.get("tf_who3") or "").casefold().split())
    key = (g.get("tf_key") or g.get("tf_key2") or ("allergic" if g.get("tf_allergy") else "")).casefold()
    if not who or not key or who in ("my", "your", "his", "her", "their", "the", "it", "this", "that"):
        return None
    names = [re.sub(r"^my ", "", who)]
    named = _name_for_relation(who) if who.startswith("my ") or who in _relation_words() else None
    if named:
        names.append(named.casefold())
    for name in names:
        words = re.findall(r"[a-z0-9]+", name)
        for row in _notes():
            said = " ".join(str(row.get("text") or "").split())
            low = said.casefold()
            if all(re.search(rf"\b{re.escape(w)}", low) for w in words) and re.search(rf"\b{re.escape(key)}", low):
                return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    return None


def _meds(text: str = "") -> str | None:
    """What he told her he takes: "my prescription is ...", "I take ..."."""
    from aletheia import speech
    found, seen = [], set()
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        # "My prescription is ready" is about a pickup, not what he takes
        # (2026-10-07: read back as his medication).
        if re.match(r"(?:my|our) (?:daily )?(?:prescriptions?|medications?|meds) (?:is|are) "
                    r"(?!(?:ready|done|in|at|due|expired|running out|out|low|almost|filled|refilled|not|late|waiting)\b)", low) \
                or re.match(r"i(?: take|'m taking| am taking|'m on| am on) (?:my )?[a-z0-9]", low) \
                and re.search(_DRUGS + r"|\bmg\b|pills?|tablets?|vitamins?|supplements?|daily|every (?:day|morning|night)", low):
            key = re.sub(r"\W+", " ", low)
            if key not in seen:
                seen.add(key)
                found.append(speech.as_she_says_it(said).rstrip("."))
    if not found:
        return None
    return "You told me: " + speech.and_list(found[:4]) + "."


def _weight() -> str | None:
    """"What's my weight": the newest weight he told her, with when."""
    said = re.compile(r"\bi(?: weigh| weighed| am|'m) (\d{2,3}(?:\.\d)?)(?: ?(pounds|lbs?|kg|kilos|kilograms))?", re.IGNORECASE)
    for row in _notes():
        text = str(row.get("text") or "")
        m = said.search(text)
        if re.search(r"\b(?:yesterday|last week|last month|weeks? ago|a month ago)\W*$", text, re.I):
            continue  # a weigh-in from before, not what he weighs
        if m and (text.casefold().startswith("i weigh") or m.group(2)):
            unit = {"lb": "pounds", "lbs": "pounds", "kilos": "kg", "kilograms": "kg"}.get((m.group(2) or "").casefold(),
                                                                                      (m.group(2) or "").casefold())
            when = ""
            try:
                from aletheia import speech
                when = ", " + speech.humanize_time(str(row.get("ts") or row.get("at") or "")) if (row.get("ts") or row.get("at")) else ""
            except Exception:
                when = ""
            return f"You told me you weigh {m.group(1)}{' ' + unit if unit else ''}{when}."
    return None


def _task_about(what: str) -> str | None:
    """The open task he means, read back whole. None when no open task
    starts with what he said: it may be on the calendar or in a note."""
    from aletheia import tasks
    words = [w for w in re.findall(r"[a-z0-9']+", what.casefold()) if w not in ("the", "my", "a", "an")]
    if not words:
        return None
    try:
        rows = [t for t in tasks.all_tasks() if tasks.is_his(t)
                and str(t.get("status") or "").upper() not in ("COMPLETED", "DONE", "CANCELLED", "DROPPED", "FAILED_TERMINAL")]
    except Exception:
        return None
    for t in rows:
        desc = " ".join(str(t.get("description") or "").split()).rstrip(".")
        have = [w for w in re.findall(r"[a-z0-9']+", desc.casefold()) if w not in ("the", "my", "a", "an")]
        if have[:len(words)] == words and len(have) > len(words):
            return f"Your task says: {desc}."
    return None


def _plans_for(who: str) -> str | None:
    """Reminders, tasks and calendar holds that name somebody of his, read
    together. None when nothing names them: a model may know of more."""
    from aletheia import speech, tasks
    who = " ".join(str(who or "").casefold().split())
    base = re.sub(r"^my ", "", who)
    if not base or base in ("you", "me", "it", "that", "them", "him", "her", "dinner", "lunch", "breakfast", "today",
                            "tonight", "tomorrow", "the", "work", "fun", "christmas", "thanksgiving", "halloween", "now"):
        return None
    names = {base}
    if who.startswith("my ") or base in _relation_words():
        n = _name_for_relation(base)
        if n:
            names.add(n.casefold())
    else:
        names |= {rel for rel in _relation_words() if (_name_for_relation(rel) or "").casefold() == base}
    hit = lambda t: any(re.search(rf"\b{re.escape(n)}\b", str(t or "").casefold()) for n in names)
    said = []
    for at, what, store in _coming():
        if hit(what):
            when = speech.humanize_time(at.isoformat())
            said.append(f"{what} {when}" if store == "calendar" else f"a reminder {when} to {what.rstrip('.')}")
    try:
        said += [speech.as_she_says_it(str(t.get("description") or "")).rstrip(".") for t in tasks.all_tasks() if tasks.is_his(t)
                 and str(t.get("status") or "").upper() not in _TASK_CLOSED and hit(t.get("description"))]
    except Exception:
        pass
    if not said:
        return None
    shown = speech.as_she_says_it(who) if who.startswith("my ") or base in _relation_words() else _named(base)
    return f"For {shown}, you have {speech.and_list(said[:4])}."


_BROKE = re.compile(r"^(?:the|my|our) (?P<t>[a-z][a-z' ]{1,25}?) (?:is|are|was|keeps) (?:broken|leaking|not working|busted|clogged|acting up"
                    r"|making a (?:weird |strange |loud )?noise)|^(?:the|my|our) (?P<t2>[a-z][a-z' ]{1,25}?) (?:broke|stopped working|died|quit working)")
_FIXED = re.compile(r"\b(?:fixed|repaired|unclogged) (?:the|my|our) (?P<t>[a-z][a-z' ]{1,25})"
                    r"|^(?:the|my|our) (?P<t2>[a-z][a-z' ]{1,25}?) (?:is|got|was) (?:fixed|repaired|working again)")


def _broken(thing: str = "") -> str | None:
    """What he told her broke and has not told her was fixed. Asked about
    one thing, its newest word either way; None when he never said."""
    from aletheia import speech
    thing = " ".join(str(thing or "").casefold().split())
    state: dict[str, tuple[str, str]] = {}
    for row in reversed(_notes()):
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold().rstrip(".")
        for rx, how in ((_FIXED, "fixed"), (_BROKE, "broken")):
            m = rx.search(low)
            if m:
                what = re.sub(r" (?:today|again|yesterday|now)$", "", (m.group("t") or m.group("t2")).strip())
                state[what] = (how, said)
                break
    if thing:
        hit = state.get(thing) or next((v for k, v in state.items() if k.endswith(" " + thing) or thing.endswith(" " + k)), None)
        if not hit:
            return None
        how, said = hit
        if how == "fixed":
            return f"Yes - you told me {speech.as_she_says_it(said).rstrip('.')}."
        return f"Not that you've told me. The last I heard, {speech.as_she_says_it(said).rstrip('.')}."
    broken = [speech.as_she_says_it(said).rstrip(".") for how, said in state.values() if how == "broken"]
    if not broken:
        return "Nothing you've told me is broken right now." if state else None
    return f"From what you've told me: {speech.and_list(broken[:5])}."


def _to_bring(verb: str) -> str | None:
    """His open tasks that start with the verb he asked about, read back.
    None when there are none: a note or a model may know."""
    from aletheia import speech, tasks
    verb = verb.casefold().strip()
    try:
        rows = [str(t.get("description") or "").strip().rstrip(".") for t in tasks.all_tasks() if tasks.is_his(t)
                and str(t.get("status") or "").upper() not in _TASK_CLOSED
                and str(t.get("description") or "").casefold().startswith(verb + " ")]
    except Exception:
        return None
    if not rows:
        return None
    return f"Your list says: {speech.and_list([speech.as_she_says_it(r) for r in rows[:5]])}."


def _event_who(what: str) -> str | None:
    """Who is hosting an event, or where he meets somebody: the note or
    calendar hold he made, read back - and plainly when it never said."""
    import datetime as dt
    from aletheia import speech
    what = " ".join(str(what or "").casefold().split())
    words = [w for w in re.findall(r"[a-z0-9']+", what) if w not in ("the", "my", "a", "an", "our")]
    if not words:
        return None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if all(re.search(rf"\b{re.escape(w)}", said.casefold()) for w in words):
            return f"You told me: {speech.as_she_says_it(said).rstrip('.')}."
    for at, title, store in _coming():
        if store == "calendar" and all(re.search(rf"\b{re.escape(w)}", str(title).casefold()) for w in words):
            return f"{title} is {speech.humanize_time(at.isoformat())}, but you didn't tell me where."
    return None


def _still_valid(thing: str) -> str | None:
    """Whether a document he told her the expiry of is still good, worked
    out from that date. None when he never said when it expires."""
    import datetime as dt
    from aletheia import localtime, speech
    thing = " ".join(str(thing or "").casefold().split())
    words = [w for w in re.findall(r"[a-z]+", thing) if w not in ("my", "the", "drivers", "driver's", "driving")]
    if not words:
        return None
    month_re = "|".join(_MONTHS)
    today = dt.datetime.now(localtime.operator_tz()).date()
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        if not all(re.search(rf"\b{re.escape(w)}", low) for w in words) \
                or not re.search(r"\b(?:expires?|expired|expiring|runs out|valid (?:until|till|through)|good (?:until|till|through)|renew)", low):
            continue
        m = re.search(rf"\b(?P<mon>{month_re})\.?(?: (?P<day>\d{{1,2}})(?:st|nd|rd|th)?)?(?:,? (?P<year>20\d\d))?", low)
        if not m:
            continue
        mon = _MONTHS.index(m.group("mon")) + 1
        year = int(m.group("year")) if m.group("year") else today.year
        day = int(m.group("day")) if m.group("day") else 28
        try:
            ends = dt.date(year, mon, day)
        except ValueError:
            continue
        if not m.group("year") and ends < today.replace(day=1):
            ends = ends.replace(year=year + 1)
        told = f"you told me {speech.as_she_says_it(said).rstrip('.')}"
        # Said without yes or no: "is it valid" and "has it expired" ask
        # the same thing with opposite answers.
        if ends < today:
            return f"It has expired - {told}, and that date has passed."
        left = (ends - today).days
        if left >= 60:
            return f"It's still good - {told}, so about {round(left / 30.44)} months left."
        return f"It's still good for now - {told}, so {speech.count_phrase(left, 'day')} left. Worth renewing soon."
    return None


def _who_lives(place: str) -> str | None:
    """Everybody he told her lives in a place, in his words. None when
    nobody: a model may know of somebody from his mail."""
    from aletheia import speech
    place = " ".join(str(place or "").casefold().split())
    found = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if re.search(r"\b(?:lives?|living|moved|stays?|is) (?:in|to|near) " + re.escape(place) + r"\b", said.casefold()) \
                and not re.match(r"i\b", said.casefold()):
            hers = speech.as_she_says_it(said).rstrip(".")
            if hers.casefold() not in (f.casefold() for f in found):
                found.append(hers)
    if not found:
        return None
    return f"You told me {speech.and_list(found[:4])}."


_MEAT = r"chicken|beef|pork|steak|bacon|ham|turkey|lamb|sausage|burgers?|hot ?dogs?|pepperoni|salami|meat|meatballs?|veal|duck|venison|brisket|ribs|wings"
_FISH = r"fish|salmon|tuna|shrimp|prawns?|crab|lobster|sushi|cod|tilapia|anchov(?:y|ies)|oysters?|clams?|mussels?|scallops?"
_ANIMAL = r"eggs?|milk|cheese|butter|yogurt|yoghurt|ice cream|cream|honey"


def _can_eat(food: str) -> str | None:
    """Whether his own notes rule a food out: an allergy, his diet, or a
    dislike. None when nothing he said settles it."""
    food = " ".join(str(food or "").casefold().split())
    if not food:
        return None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        allergy = re.search(r"\ballergic to (?P<a>[a-z][a-z ,]{1,40})", low)
        if allergy and any(a.strip() and (a.strip().rstrip("s") in food or food.rstrip("s") in a.strip())
                           for a in re.split(r",| and | or ", allergy.group("a"))):
            return f"No - you told me you're allergic to {allergy.group('a').strip().rstrip('.')}."
        diet = re.search(r"\bi(?:'m| am) (?:a )?(?:strict )?(?P<d>vegetarian|vegan|pescatarian)\b", low)
        if diet:
            d = diet.group("d")
            banned = _MEAT + ("" if d == "pescatarian" else "|" + _FISH) + ("|" + _ANIMAL if d == "vegan" else "")
            if re.search(rf"\b(?:{banned})\b", food):
                return f"Not if you're sticking to it - you told me you're {d}."
        dislike = re.match(r"i (?:don'?t|do not|hate|can'?t stand) (?:like |eat )?(?P<x>[a-z][a-z ]{1,30})", low)
        if dislike and (dislike.group("x").rstrip("s") in food or food.rstrip("s") in dislike.group("x")):
            return f"You can, but you told me {_say_mine(said)}."
    return None


def _say_mine(said: str) -> str:
    from aletheia import speech
    return speech.as_she_says_it(said).rstrip(".")


def _bills_due() -> str | None:
    """Bills he told her are due and reminders to pay one, together. None
    when neither store has any: his mail may, and a model can read it."""
    from aletheia import speech
    said, seen = [], set()
    for row in _notes():
        note = " ".join(str(row.get("text") or "").split())
        low = note.casefold()
        if re.search(rf"\b(?:{_BILL_KEYS}|bill|payment)\b", low) and re.search(r"\bdue\b", low):
            key = re.sub(r"\W+", " ", low)
            if key not in seen:
                seen.add(key)
                said.append(speech.as_she_says_it(note).rstrip("."))
    for at, what, store in _coming():
        if store == "reminder" and re.search(r"\b(?:pay|bill|rent|mortgage)\b", str(what).casefold()):
            said.append(f"a reminder {speech.humanize_time(at.isoformat())} to {str(what).rstrip('.')}")
    if not said:
        return None
    return f"From what you've told me: {speech.and_list(said[:5])}."


def _repeating(which: str = "") -> str:
    """His reminders that come back, with how often - every one switched
    on, or only the kind he named."""
    import datetime as dt
    from aletheia import speech
    try:
        from aletheia import scheduler
        specs = [sp for sp in scheduler.all_schedules() if sp.get("enabled") and sp.get("kind") != "once"
                 and str((sp.get("command") or {}).get("text") or "").strip()]
    except Exception:
        specs = []
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def clock(sp):
        try:
            h, m = (int(x) for x in str(sp.get("time") or "").split(":")[:2])
        except ValueError:
            return ""
        return dt.time(h, m).strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()

    def how(sp):
        kind = sp.get("kind")
        if kind == "interval":
            n = int(sp.get("every_minutes") or 0)
            return f"every {speech.count_phrase(n // 60, 'hour')}" if n % 60 == 0 else f"every {speech.count_phrase(n, 'minute')}"
        if kind == "daily":
            return f"every day at {clock(sp)}"
        if kind == "weekly":
            return f"every {speech.and_list([days[d] for d in sp.get('weekdays') or []])} at {clock(sp)}"
        if kind == "monthly":
            return f"on the {_ordinal(int(sp.get('monthday') or 1))} of every month at {clock(sp)}"
        return ""
    which = (which or "").strip()
    keep = {"morning": lambda sp: sp.get("kind") == "daily" and clock(sp).endswith("am"),
            "night": lambda sp: sp.get("kind") == "daily" and clock(sp).endswith("pm"),
            "evening": lambda sp: sp.get("kind") == "daily" and clock(sp).endswith("pm"),
            "nightly": lambda sp: sp.get("kind") == "daily" and clock(sp).endswith("pm"),
            "day": lambda sp: sp.get("kind") == "daily", "daily": lambda sp: sp.get("kind") == "daily",
            "week": lambda sp: sp.get("kind") == "weekly", "weekly": lambda sp: sp.get("kind") == "weekly",
            "month": lambda sp: sp.get("kind") == "monthly", "monthly": lambda sp: sp.get("kind") == "monthly"}.get(which)
    rows = [sp for sp in specs if keep is None or keep(sp)]
    if not rows:
        every = {"daily": "day", "weekly": "week", "monthly": "month", "nightly": "night"}.get(which, which)
        every = every if every in ("morning", "day", "night", "evening", "week", "month") else "day"
        return f"No reminders like that are set. Say \"remind me every {every} to\" and what, and I'll set one."
    said = [f"{speech._yours(str(sp['command']['text']).strip().rstrip('.'))}, {how(sp)}" for sp in rows[:6]]
    return f"{speech.count_phrase(len(rows), 'repeating reminder')}: " + "; ".join(said) + "."


def _places_liked() -> str | None:
    """Restaurants he told her he likes: his favorite and the ones he
    tried and liked. None when there are none - a model may know more."""
    from aletheia import speech
    found = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        fav = re.match(r"(?:my|our) (?:favou?rite|go-to) (?:restaurant|place to eat|place|spot)s? (?:is|are) (?P<x>.+?)\.?$", said, re.I)
        tried = re.match(r"(?:i|we) (?:tried|went to|ate at|had (?:dinner|lunch|breakfast|brunch) at|checked out) (?:a |this |the |that )?(?:new )?"
                         r"(?:(?:place|restaurant|spot|cafe|bar|bakery|diner)(?: called| named)? )?(?P<x>.+?) (?:and|but) (?:i |we )?"
                         r"(?:really |absolutely )?(?:loved|liked|enjoyed) it", said, re.I)
        liked = re.match(r"(?:i|we) (?:really |absolutely )?(?:love|loved|like|liked|enjoy|enjoyed) (?:the )?(?P<x>.+?)"
                         r" (?:restaurant|place)\b", said, re.I)
        m = fav or tried or liked
        if m and not re.search(r"\b(?:didn'?t|did not|not)\b", low):
            name = m.group("x").strip()
            if name.casefold() not in (f.casefold() for f in found):
                found.append(name)
    if not found:
        return None
    return f"From what you've told me: {speech.and_list(found[:5])}."


def _who_said(who: str) -> str | None:
    """What he told her somebody said, newest first. None when he never
    did: it may be in his mail, which a model can read."""
    from aletheia import speech
    who = " ".join(str(who or "").casefold().split())
    base = re.sub(r"^(?:the|my) ", "", who)
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if re.match(rf"(?:the |my )?{re.escape(base)} (?:said|told me|says)\b", said, re.I):
            return f"You told me {speech.as_she_says_it(said).rstrip('.')}."
    return None


_HAS_KIN = {"kids": r"kids?|children|child|sons?|daughters?|boys?|girls?|twins", "children": r"kids?|children|child|sons?|daughters?|boys?|girls?|twins",
            "grandkids": r"grandkids?|grandchildren", "grandchildren": r"grandkids?|grandchildren",
            "siblings": r"brothers?|sisters?|siblings?", "pets": r"pets?|dogs?|cats?"}


def _how_many_has(text: str) -> str | None:
    """What he said somebody has: "Jake has two kids"."""
    g = _groups("how_many_has", text)
    who = (g.get("hm_who") or g.get("hm_who2") or "").strip()
    what = (g.get("hm_what") or g.get("hm_what2") or "").strip()
    if not who or not what or who in ("you", "i", "he", "she", "they", "it"):
        return None
    name = _name_for_relation(who) if who.startswith("my ") else None
    names = {re.sub(r"^my ", "", who)} | ({name.casefold()} if name else set())
    nouns = _HAS_KIN.get(what) or (what.rstrip("s") + "s?")
    has = re.compile(r"\b(?:my )?(?:" + "|".join(re.escape(n) for n in names) + r")(?:'s)? (?:has|have|has got) "
                     r"(?:no|one|two|three|four|five|six|seven|eight|\d{1,2}|a|an) (?:[a-z-]+ )?(?:" + nouns + r")\b")
    for row in reversed(_notes()):
        said = " ".join(str(row.get("text") or "").split())
        if has.search(said.casefold()):
            told = re.sub(r"\bmy\b", "your", said.rstrip("."), flags=re.I)
            return f"You told me {told[:1].lower() + told[1:] if told.startswith('Your') else told}."
    return None


_EPISODE = re.compile(r"^i'?m (?:on|up to|at) (?P<ep>(?:season \d{1,2},? )?episode \d{1,3}|season \d{1,2}) of (?P<show>.+?)\.?$", re.I)


def _episode_of(show: str = "") -> str | None:
    """The newest "I'm on episode 4 of X" for that show, or for any show."""
    for row in reversed(_notes()):
        m = _EPISODE.match(" ".join(str(row.get("text") or "").split()))
        if m and (not show or m.group("show").casefold() == show.casefold()):
            return m.group("ep").replace(",", "")
    return None


def _episode_on(show: str) -> str | None:
    show = " ".join(str(show or "").split())
    for row in reversed(_notes()):
        m = _EPISODE.match(" ".join(str(row.get("text") or "").split()))
        if m and (not show or m.group("show").casefold() == show.casefold()):
            return f"You told me you're on {m.group('ep').replace(',', '')} of {m.group('show')}."
    return None


def _rated(what: str) -> str | None:
    what = " ".join(str(what or "").split()).casefold()
    for row in reversed(_notes()):
        said = " ".join(str(row.get("text") or "").split())
        m = re.match(r"i (?:rated|gave|scored) (?P<t>.+?) (?:a )?(?P<n>\d{1,3}(?:\.\d)?(?: out of \d{1,3}| stars?|/\d{1,3})?)\.?$", said, re.I)
        if m and m.group("t").casefold() == what:
            return f"You gave {m.group('t')} {m.group('n')}."
    return None


_NEWS_PAST = {"get": "got", "graduate": "graduated", "quit": "quit", "lose": "lost", "buy": "bought", "close": "closed"}


def _news_when(what: str) -> str | None:
    """When he told her his news, from his journal. None when he never
    said: it may have come up in a conversation a model answered."""
    from aletheia import speech
    head, _, rest = what.casefold().strip().partition(" ")
    past = _NEWS_PAST.get(head)
    if not past:
        return None
    words = [w for w in re.findall(r"[a-z']+", rest) if w not in ("a", "my", "the", "our")]
    for row in _notes():
        low = " ".join(str(row.get("text") or "").casefold().split())
        if not re.search(r"\b(?:i|we) (?:just |finally )?" + past + r"\b", low) \
                or not all(re.search(r"\b" + re.escape(w), low) for w in words):
            continue
        said = " ".join(str(row.get("text") or "").split())
        told = re.sub(r"\bmy\b", "your", re.sub(r"^(?:journal: )?i ", "you ", said, flags=re.I), flags=re.I).rstrip(".!")
        when = speech.humanize_time(str(row.get("ts") or ""))
        return f"You told me {told} {when}." if when else f"You told me {told}."
    return None


def _job_since(text: str) -> str | None:
    """How long he has been at his job, from his note saying when he
    started. None when he never said: his profile or mail may know."""
    import datetime as dt
    from aletheia import localtime
    tz = localtime.operator_tz()
    today = dt.datetime.now(tz).date()
    said_it = re.compile(r"\bi (?:just |only )?(?:started|began) (?:my |a |the )?(?:new )?(?:job|work|working|position|role)?"
                         r"(?: ?(?:at|with|for) [a-z0-9][a-z0-9&.' -]{1,30}?)? ?(?:on |in |back in |this |last )?"
                         r"(?P<when>today|yesterday|(?:the )?\d{1,2}(?:st|nd|rd|th)?(?: of)? [a-z]+(?:,? \d{4})?"
                         r"|[a-z]+(?: (?:the )?\d{1,2}(?:st|nd|rd|th)?)?(?:,? \d{4})?)\.?$", re.I)
    for row in _notes():
        text_ = " ".join(str(row.get("text") or "").split())
        m = said_it.search(text_)
        if not m or not re.search(r"\b(?:job|work|working|position|role|at|with|for)\b", text_, re.I):
            continue
        try:
            noted = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        when = m.group("when").casefold().strip(" .")
        began = None
        if when == "today":
            began = noted
        elif when == "yesterday":
            began = noted - dt.timedelta(days=1)
        else:
            d = re.fullmatch(r"(?:the )?(?P<a>\d{1,2})?(?:st|nd|rd|th)?(?: of)? ?(?P<mon>[a-z]+)(?: (?:the )?(?P<b>\d{1,2})(?:st|nd|rd|th)?)?(?:,? (?P<y>\d{4}))?", when)
            mon = next((i + 1 for i, name in enumerate(_MONTHS) if d and d.group("mon") and name.startswith(d.group("mon")[:3])), None)
            if d and mon:
                day = int(d.group("a") or d.group("b") or 1)
                year = int(d.group("y") or noted.year)
                try:
                    began = dt.date(year, mon, day)
                except ValueError:
                    began = None
                if began and not d.group("y") and began > noted:
                    began = began.replace(year=year - 1)
        if not began:
            from aletheia import speech
            return f"You told me: {speech.as_she_says_it(text_).rstrip('.')}."
        days = (today - began).days
        on = f"{began.strftime('%A')} {began.day} {began.strftime('%B')}" + ("" if began.year == today.year else f" {began.year}")
        # "March 2021" named a month, not the first of it (2026-10-08)
        month_only = when not in ("today", "yesterday") and not (d.group("a") or d.group("b"))
        if month_only:
            on = began.strftime("%B") + ("" if began.year == today.year else f" {began.year}")
        if days < 0:
            return f"You start in {on}." if month_only else f"You start on {on}."
        if days == 0:
            return "You started today."
        if days < 60:
            span = f"{days} day{'s' if days != 1 else ''}"
        elif days < 730:
            span = f"about {round(days / 30.44)} months"
        else:
            span = f"about {days // 365} years"
        return f"{span[:1].upper() + span[1:]} - you started {'in' if month_only else 'on'} {on}."
    # "I got a new job at Acme" (2026-10-08) says when he GOT it, not when he
    # started: said back as that, with what is missing.
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if re.search(r"\bi (?:just |finally )?(?:got (?:a |the |my )?(?:new )?job|got hired)\b", said, re.I):
            from aletheia import speech
            when = speech.humanize_time(str(row.get("ts") or ""))
            told = re.sub(r"^(?:journal: )?i ", "you ", said, flags=re.I).rstrip(".!")
            return (f"You told me {told} {when}, " if when else f"You told me {told}, ") + \
                "but not the day you started. Tell me and I'll count from it."
    return None


def _told_last(text: str) -> str | None:
    """His newest note, or the newest one about what he names. None when
    nothing he named was kept: he may have said it in a conversation a
    model answered, so this is never "you didn't"."""
    import datetime as dt
    from aletheia import localtime, speech
    about = " ".join(str(_groups("told_last", text).get("told_about") or "").casefold().split())
    words = [w for w in re.findall(r"[a-z0-9']+", about) if w not in ("my", "the", "a", "an", "our", "your")]
    # "My trip" is how he refers to "I'm going to Denver next weekend".
    kin = {"trip": r"\b(?:trip|vacation|holiday|going to|heading to|flying to|driving to|visiting|flight)\b",
           "vacation": r"\b(?:trip|vacation|holiday)\b", "job": r"\b(?:job|work|boss)\b", "move": r"\bmov(?:e|ing)\b"}
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if not said or (words and not all(re.search(kin.get(w, rf"\b{re.escape(w)}"), said, re.I) for w in words)):
            continue
        hers = speech.as_she_says_it(re.sub(r"^(?:Journal|Idea): ", "", said)).rstrip(".")
        try:
            at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(localtime.operator_tz())
            when = speech.humanize_time(at.isoformat())
        except ValueError:
            when = ""
        lead = "Yes - you told me" if words else "You told me"
        return f"{lead}{' ' + when if when else ''}: {hers}."
    return None


def _pills_left(text: str) -> str | None:
    """His last "I have 10 pills left", less "I take 2 a day" for each day
    since. None without a count when he asked about running out of
    something unnamed: that may not be pills at all."""
    import datetime as dt
    from aletheia import localtime, speech
    words = {"one": 1, "two": 2, "three": 3, "four": 4}
    count = dose = None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        if count is None:
            m = re.fullmatch(r"i(?:'ve| have)(?: got)? (?:about |only |just )?(\d{1,3}) (?:pills|tablets|capsules|doses).* left\.?", said)
            if m:
                try:
                    at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(localtime.operator_tz())
                except ValueError:
                    continue
                count = (int(m.group(1)), at)
        if dose is None:
            m = re.fullmatch(r"i take (\d|one|two|three|four) .*?(?:a|per|each|every) day\.?", said)
            if m:
                dose = words.get(m.group(1)) or int(m.group(1))
    if count is None:
        if re.search(r"\bout\b(?!.*\b(?:pills|tablets|capsules|meds|medicine|medication)\b)", text.casefold()):
            return None
        return "You haven't told me how many you have. Say \"I have 10 pills left\" and I'll keep count."
    n, at = count
    told = f"you told me {speech.humanize_time(at.isoformat())} you had {n}"
    if not dose:
        return f"{told[:1].upper() + told[1:]}. Say \"I take 2 a day\" and I'll work out when they run out."
    now = dt.datetime.now(at.tzinfo)
    left = max(0, n - dose * (now.date() - at.date()).days)
    if left == 0:
        return f"By now you're out: {told}, at {dose} a day."
    out = now.date() + dt.timedelta(days=left // dose)
    return (f"About {left} left - {told}, at {dose} a day. They run out around "
            f"{out.strftime('%A')}, {out.strftime('%B')} {out.day}.")


def _miles_until(text: str) -> str | None:
    """The miles between his car's last mileage and the one a service is
    due at, both from his notes. Either missing is said, with how to say it."""
    what = (_groups("miles_until", text).get("mu_what") or "").casefold()
    if not what:
        return None
    number = r"(?P<n>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?P<k>k)?"
    due = odo = None
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split()).casefold()
        if due is None and what.split()[0] in said and re.search(r"\bdue\b|\bneeded\b", said):
            m = re.search(r"(?:at|by|around) " + number, said)
            if m:
                due = float(m.group("n").replace(",", "")) * (1000 if m.group("k") else 1)
        if odo is None and re.search(r"\b(?:car|truck|van|suv|odometer|mileage|milage)\b", said) \
                and not re.search(r"\bdue\b", said):
            m = re.search(r"(?:has|is at|at|reads|says|is) (?:about |around )?" + number + r" ?(?:miles|mi|km)?\b", said)
            if m:
                odo = float(m.group("n").replace(",", "")) * (1000 if m.group("k") else 1)
        if due is not None and odo is not None:
            break
    if due is None:
        return f"You haven't told me when your {what} is due. Say \"my {what} is due at 45,000 miles\" and I'll keep it."
    if odo is None:
        return (f"Your {what} is due at {due:,.0f} miles, but I don't know your mileage. "
                "Say \"my car has 43,000 miles\" and I'll work it out.")
    left = due - odo
    if left <= 0:
        return f"It's due now - your {what} was due at {due:,.0f} miles and you told me the car has {odo:,.0f}."
    return f"About {left:,.0f} miles: it's due at {due:,.0f} and you told me the car has {odo:,.0f}."


def _their_kind(text: str) -> str | None:
    """"What flowers does Anna like": "Anna's favorite flower is tulips",
    or a note saying she likes something of that kind. None without one."""
    from aletheia import speech
    g = _groups("their_kind", text)
    what = (g.get("tk_what") or "").casefold()
    who = re.sub(r"^(?:my|our) ", "", " ".join(str(g.get("tk_who") or "").casefold().split()))
    if not what or not who:
        return None
    stem = re.escape(what[:max(3, len(what) - 1)])
    found = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if re.fullmatch(r"(?:my |our )?" + re.escape(who) + r"(?:'s|s') (?:favou?rite|fave) " + stem + r"[a-z]* (?:is|are) .+", said, re.I) \
                or re.fullmatch(r"(?:my |our )?" + re.escape(who) + r" (?:really |also )?(?:likes|loves|prefers|enjoys|adores) .*\b"
                                + stem + r"[a-z]*\b.*", said, re.I):
            hers = speech.as_she_says_it(said).rstrip(".")
            if hers.casefold() not in (f.casefold() for f in found):
                found.append(hers)
    if not found:
        return None
    return "You told me " + speech.and_list(found[:3]) + "."


def _their_likes(text: str) -> str | None:
    """"What does Sam like": his notes saying what someone likes or
    doesn't. None when there are none - a model may know them better."""
    from aletheia import speech
    g = _groups("their_likes", text)
    who = " ".join(str(g.get("tl_who") or "").casefold().split())
    if not who:
        return None
    hate = g.get("tl_verb") in ("hate", "not like")
    verbs = (r"(?:hates|doesn'?t like|does not like|can'?t stand)" if hate
             else r"(?:really |also )?(?:likes|loves|adores|prefers|enjoys|is into|is obsessed with|is a fan of|collects)")
    # "What does my wife like" with "Sarah likes candles" kept, and the
    # other way round (2026-10-08: to a model): the name he gave counts.
    base = re.sub(r"^(?:my|our) ", "", who)
    names = [base]
    if who.startswith(("my ", "our ")) or base in _relation_words():
        named = _name_for_relation(base)
        if named:
            names.append(named.casefold())
    else:
        names += [rel for rel in _relation_words() if (_name_for_relation(rel) or "").casefold() == base]
    found = []
    for row in _notes():
        said = " ".join(str(row.get("text") or "").split())
        if re.fullmatch(r"(?:my |our )?(?:" + "|".join(re.escape(n) for n in names) + r") " + verbs + r" .+", said, re.IGNORECASE):
            hers = speech.as_she_says_it(said).rstrip(".")
            if hers.casefold() not in (f.casefold() for f in found):
                found.append(hers)
    if not found:
        return None
    return "You told me: " + speech.and_list(found[:4]) + "."


def _work_at() -> str | None:
    """"Where do I work": the note he made saying so. Nothing kept is left
    to whatever else might know (his profile), never answered "no"."""
    said = re.compile(r"\bi (work|am working|started working|go to school|study) (at|for) (.+)"
                      r"|\bi (?:just )?(?:started|got) (?:a |my |the )?(?:new )?(?:job )?(at) (.+?)(?: today| yesterday| this week)?$",
                      re.IGNORECASE)
    for row in _notes():
        m = said.search(str(row.get("text") or ""))
        if m and m.group(3) is None:
            return f"You told me you work at {m.group(5).strip().rstrip('.')}."
        if m:
            school = m.group(1).casefold() in ("go to school", "study")
            verb = f"{m.group(1).casefold()} {m.group(2).casefold()}" if school else f"work {m.group(2).casefold()}"
            return f"You told me you {verb} {m.group(3).strip().rstrip('.')}."
    return None


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
                # "My emergency contact is my mom" is "your mom" said back.
                value = re.sub(r'^(?:my|our) ', 'your ', m.group(1).strip().rstrip('.'), flags=re.I)
                # "my doctor is dr patel" came back "dr patel" (2026-10-07):
                # a title and a name are capitalised the way they are written.
                titled = re.fullmatch(r"(dr|mr|mrs|ms|miss|prof)(\.?) ([a-z][a-z'-]*)((?: [a-z][a-z'-]*)?)", value)
                if titled:
                    value = (titled.group(1).title() + titled.group(2) + " " + titled.group(3).title()
                             + titled.group(4).title())
                return f"Your {who} is {value}."
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
    if ", but you told me" in done:
        # "I finished the report" is already said in his half; her
        # "Noted: you finished the report" would say it twice (2026-10-08).
        rows = [r for r in rows if not str(r.get("what") or "").startswith("Noted: ")]
        return f"{done} What I did this week: {_listed(rows, 'this week').split(': ', 1)[1]}" if rows else done
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
           "parked": lambda rest: _parked(_groups("parked", rest).get("parked_at") or ""),
           "fact_q": lambda rest: _fact_q(rest),
           "fact_any": lambda rest: _fact_any(_groups("fact_any", rest).get("fact_any", ""),
                                              _groups("fact_any", rest).get("fact_whose", "my")),
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
           "dur_convert": _dur_convert,
           "how_to": _how_to,
           "life_news": _life_news,
           "constant": lambda rest: _CONSTANTS.get(rest.strip()),
           "fraction_pct": lambda rest: _fraction_pct(rest),
           "fun_fact": lambda rest: _pick(FUN_FACTS),
           "quote": lambda rest: _pick(QUOTES),
           "rain": lambda rest: _rain(rest),
           "timer_left": lambda rest: _timer_left(),
           "week_of_year": lambda rest: _week_of_year(),
           "due": lambda rest: _due(rest),
           "leap_year": lambda rest: _leap_year(rest),
           "coin": lambda rest: _coin(),
           "yes_no": lambda rest: __import__("secrets").choice(("Yes.", "No.")),
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
           "focus": lambda rest: _focus(only_first=bool(re.search(r"\b(?:first|start with|tackle|most urgent|most pressing)\b"
                                                                  r"|^(?:which|what) (?:of|one|task)", rest))),
           "outcomes": _outcomes,
           "until": _until,
           "race": lambda rest: _race(rest),
           "age_in": lambda rest: _age_in(_groups("age_in", rest).get("age_year", ""),
                                          _groups("age_in", rest).get("age_n", "")),
           "until_day": lambda rest: _until(rest, which_day=True),
           "weeks_until": lambda rest: _weeks_until(rest),
           "tasks_due": lambda rest: _tasks_due(rest),
           "birthday": lambda text: _birthday(text),
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
           "work_at": lambda rest: _work_at(),
           "born_facts": lambda rest: _born_facts(rest if rest in ("day", "next year", "days", "weeks", "months") else "sign"),
           "weight": lambda rest: _weight(),
           "counted": _counted,
           "ate": _ate,
           "lent": _lent,
           "lent_out": lambda rest: _lent_out(),
           "borrowed": lambda rest: _borrowed(),
           "get_up": lambda rest: _get_up(rest),
           "kept": _kept,
           "gift_for": _gift_for,
           "meal_plan": _meal_plan,
           "pick_for_me": _pick_for_me,
           "worked": _worked,
           "sums_more": _sums_more,
           "life_when": _life_when,
           "agenda_part": _agenda_part,
           "event_detail": _event_detail,
           "missed_reminders": _missed_reminders,
           "saved": _saved,
           "next_due": _next_due,
           "holiday_year": _holiday_year,
           "went": _went,
           "did_count": _did_count,
           "off_lists": _off_lists,
           "body": _body,
           "their_fact": _their_fact,
           "when_note": _when_note,
           "when_meeting": lambda rest: _when_mine(rest),
           "plural": _plural,
           "when_do_i": lambda rest: _when_mine(rest) or _task_due(rest),
           "meds": _meds,
           "work_hours": _work_hours,
           "cost_mine": _cost_mine,
           "liked_how": _liked_how,
           "woke": lambda rest: _woke(rest),
           "woke_usual": lambda text: _woke_usual(text),
           "reading": lambda text: _reading(text),
           "awake_for": lambda text: _awake_for(),
           "no_password": lambda text: _no_password(text),
           "arrived": lambda text: _arrived(text),
           "synonym": lambda rest: _related(rest, "synonyms"),
           "antonym": lambda rest: _related(rest, "antonyms"),
           "after_that": lambda rest: _after_that(),
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
           "the_list": lambda text: _the_list(),
           "tasks_verb": lambda text: _tasks_verb(text),
           "role_said": lambda text: _role_said(text),
           "loan_left": lambda text: _loan_left(text),
           "date_what": lambda text: _date_what(text),
           "where_was_i": lambda text: _where_was_i(),
           "on_days": lambda text: _on_days(text),
           "until_leave": lambda text: _until_leave(),
           "just_added": lambda text: _just_added(text=text),
           "their_kind": lambda text: _their_kind(text),
           "miles_until": lambda text: _miles_until(text),
           "pills_left": lambda text: _pills_left(text),
           "time_where": lambda text: _time_where(text),
           "trip_length": lambda text: _trip_length(text),
           "starts_when": lambda text: _starts_when(text),
           "it_due": lambda text: _it_due(),
           "their_person": lambda text: _their_person(text),
           "habit": lambda text: _habit(text),
           "days_off": lambda text: _days_off(text),
           "job_since": lambda text: _job_since(text),
           "their_likes": lambda text: _their_likes(text),
           "told_last": lambda text: _told_last(text),
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
           "next_meeting": lambda rest: _next_meeting(until=str(rest).casefold().startswith("how long")),
           "next_detail": lambda rest: _next_detail(rest),
           "took_today": lambda text: _took_asked(text),
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
           "when_mine_what": lambda rest: _when_mine(rest),
           "when_with": lambda rest: _when_mine(rest),
           "who_coming": lambda rest: _who_coming(rest),
           "opinion": lambda rest: _opinion(rest),
           "did_finish": lambda rest: _did_finish(rest),
           "shop_added": lambda rest: _shop_added(rest),
           "cook_temp": lambda rest: _cook_temp(rest),
           "reminder_when": lambda rest: _reminder_when(rest),
           "until_mine": lambda rest: _when_mine(rest, until=True),
           "alarm_left": lambda rest: _alarm_left(),
           "coming_up": lambda rest: _coming_up(rest),
           "meetings_count": lambda rest: _coming_up(rest, calendar_only=True),
           "meetings_ahead": lambda rest: _coming_up("", calendar_only=True),
           "meetings_week": lambda rest: _meetings_week(rest),
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
           "told_on": _told_on,
           "who_called": _who_called,
           "news_when": _news_when,
           "plans_for": _plans_for,
           "broken": _broken,
           "to_bring": _to_bring,
           "still_valid": _still_valid,
           "who_lives": _who_lives,
           "episode_on": _episode_on,
           "rated": _rated,
           "how_many_has": _how_many_has,
           "who_said": _who_said,
           "places_liked": lambda rest: _places_liked(),
           "repeating": _repeating,
           "bills_due": lambda rest: _bills_due(),
           "can_eat": _can_eat,
           "event_who": lambda rest: _event_who(rest),
           "task_about": _task_about,
           "born_age": _born_age,
           "his_likes": lambda rest: _his_likes(),
           "sick_since": _sick_since,
           "lift_max": _lift_max,
           "when_have": _when_have,
           "pet_due": _pet_due,
           "deliveries": lambda rest: _deliveries(),
           "shop_qty": _shop_qty,
           "do_i_work": _do_i_work,
           "last_ate": lambda rest: _last_ate(),
           "how_did_i_do": _how_did_i_do,
           "how_long_out": _how_long_out,
           "left_on": lambda rest: _left_on(rest),
           "do_i_have": _do_i_have,
           "task_age": _task_age,
           "who_coming_noted": _who_coming_noted,
           "asked_on": _asked_on,
           "hunt_why": lambda rest: _hunt_why(),
           "who_are_you": lambda rest: _who_are_you(),
           "her_name": lambda rest: "Thea - short for Aletheia.",
           "offline_can": lambda rest: _offline_can(),
           "memory_free": lambda rest: _memory_free(),
           "recall": _recall,
           "dislikes": _dislikes,
           "married": _married,
           "promised": _promised,
           "capital": _capital,
           "bedtime_calc": _bedtime_calc,
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
