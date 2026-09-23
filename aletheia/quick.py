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
    r"(?P<count2_total> (?:in total|total|overall|so far|ever))?(?: today)?$"
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
        r"^what(?:'s| is|s)? waiting(?: on| for)? me$"
        r"|^what(?:'s| is|s)? waiting$"
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
        r"|^(?:catch me up|fill me in|bring me up to speed|where are we)(?: please)?$")),
    ("focus", re.compile(
        r"^what should i (?:focus on|do|work on|prioriti[sz]e|tackle|start with)(?: today| first| right now| this morning| now)?$"
        r"|^(?:plan|organi[sz]e|map out|lay out) my day$|^what(?:'s| is) (?:the )?(?:most important|top priority|priority)"
        r"(?: thing)?(?: today| right now)?$|^what(?:'s| is) on (?:my|the) plate(?: today)?$"
        r"|^what do i need to (?:do|get done)(?: today)?$")),
    # "How many interviews do I have" / "did I get any rejections" (2026-09-23):
    # outcomes are on the application records.
    ("outcomes", re.compile(
        r"^(?:how many|any|do i have any|did i get any|have i (?:got|gotten|had) any|what) (?P<outcome>interviews?|offers?|"
        r"rejections?)(?: (?:do i have|have i got|so far|yet|lined up|coming up|today|this week))*$"
        r"|^(?:who|which (?:companies|employers|jobs)) (?:(?P<outcome2>rejected) me|(?P<outcome3>turned) me down|"
        r"made (?:me )?an (?P<outcome4>offer)|(?:wants?|asked) (?:to |an |for an )?(?P<outcome5>interview|talk))$")),
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
        r"|^(?:what|who|where) did (?:you|u|we) apply(?: (?:to|for))?(?: for me)?(?: today| this week| tonight| so far)?$"
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
    ("to_answer", re.compile(
        r"^(?:is there )?anything (?:i|that i) (?:need|have) to answer(?: for you)?$"
        r"|^what (?:questions|do you need answered|do (?:you|u) need me to answer|needs answering)(?: do (?:you|u) have)?(?: for me)?$"
        r"|^(?:any|what) questions(?: for me)?$|^what are (?:you|u) (?:stuck on|waiting on me for)$")),
    ("found", re.compile(
        r"^how many (?:jobs|openings|postings|roles|positions) (?:have (?:you|u)|did (?:you|u)|have we) (?:found|find|come across|turned up|discovered)"
        r"(?: today| so far| tonight)?$|^what (?:jobs|openings) (?:have (?:you|u)|did (?:you|u)) (?:found|find)(?: today)?$")),
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
    # "How many days until Christmas" paid a model for arithmetic on a
    # calendar (2026-09-23). Weekdays, named days and a month-and-day.
    ("until", re.compile(
        r"^how (?:many days|long) (?:until|till|to|before) (?:the )?(?!(?:you|u|i|we|she|it|they|he) )"
        r"(?P<until>[a-z][a-z' ]{2,30}?)(?: is it)?$"
        r"|^(?:when is|when's) (?P<until2>christmas|new year(?:'s)?(?: day| eve)?|halloween|thanksgiving|"
        r"valentine'?s(?: day)?|easter|the fourth of july|july 4th|independence day)$")),
    # THE FIRST THING HE ASKS IN THE MORNING (2026-09-23): sent overnight
    # and done overnight, from the records.
    ("overnight", re.compile(
        r"^what happened (?:overnight|last night|tonight|while i (?:was asleep|slept|was sleeping|was out))$"
        r"|^what did (?:you|u) (?:do|get done) (?:overnight|last night|while i (?:was asleep|slept|was sleeping))$"
        r"|^(?:did )?anything (?:happen )?(?:overnight|last night|while i (?:was asleep|slept))$"
        r"|^how (?:did|was) (?:the night|last night|overnight)(?: go)?$")),
    # "When did you last update" was answered by her own model from the
    # journal ("no record of that") - git and `running.version` know.
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
        r"|^what have (?:you|u) been doing$"
        r"|^what did (?:you|u) get done(?: today)?$"
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
    # "how many did you send this week" went to a planner nobody could run
    # (2026-09-23 night sweep); the records carry the dates.
    ("sent_count", re.compile(
        r"^how many (?:applications |apps |jobs )?(?:did|have) (?:you|u|we) (?:send|sent|submit|submitted|apply to|applied to|put in)(?: out)?"
        r"(?: (?P<sent_window>today|tonight|this week|so far this week|this month|yesterday|last week|so far|in total|altogether|overall|ever))?\s*\??$")),
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
        r"|^(?:got|have) the time$|^time$")),
    ("date", re.compile(
        r"^what(?:'s| is|s)? (?:the |today'?s? )?date( today)?$"
        r"|^what day is it( today)?$|^what(?:'s| is|s)? today$"
        r"|^what day of the week is it$")),
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
        r"^what(?:'s| is|s)? on (?:my |the )?(?:calendar|schedule|agenda|plate)"
        r"(?: for)? (?P<day>today|tomorrow|this week|next week)$"
        r"|^what (?:do i have|have i got|is there|am i doing) (?:on )?(?P<day2>today|tomorrow|this week|next week)$"
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
        r"|^what (?:meetings|appointments|events|calls) (?:do i have|have i got|are there)(?: on)? (?P<day9>today|tomorrow|this week|next week)$")),
    ("alerts", re.compile(
        r"^(?:are there |is there )?any(?:thing)? (?:alerts|broken|wrong|failing)$"
        r"|^any alerts$|^is anything broken$|^anything broken$"
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
        r"|^what(?:'s| is|s)? on the shopping list$")),
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
        r"|^(?:do i|have i) (?:have|got) (?:anything|any plans|much) on"
        r"(?: (?P<free2>today|tomorrow))?$"
        r"|^is my (?P<free3>today|tomorrow) free$")),
    # Already computed every beat for the wall (`next_appointment`), and
    # it was paying a round trip to be read aloud. Deliberately without a
    # trailing clause: "what's my next meeting ABOUT" and "move my next
    # meeting" are different questions and belong to the planner.
    ("next_meeting", re.compile(
        r"^what(?:'s| is|s)? my next (?:meeting|appointment|event)$"
        r"|^when(?:'s| is)? my next (?:meeting|appointment|event)$"
        r"|^do i have (?:any )?(?:meetings|appointments)(?: coming up| today)?$"
        r"|^what(?:'s| is|s)? (?:next |coming up )?on my calendar$"
        r"|^(?:my )?next (?:meeting|appointment)$"
        r"|^what(?:'s| is|s)? my schedule(?: today)?$")),
    ("version", re.compile(
        r"^what version are (?:you|u) on$|^what version are (?:you|u) running$"
        r"|^what code are (?:you|u) running$|^what(?:'s| is|s)? your version$"
        r"|^which (?:branch|commit) are (?:you|u) on$"
        r"|^are (?:you|u) (?:up to date|current|stale)$"
        r"|^are (?:you|u) running the latest code$")),
    ("uptime", re.compile(
        r"^how long have (?:you|u) been (?:up|running|on|awake|going)$"
        r"|^how long have (?:you|u) been here$"
        r"|^what(?:'s| is|s)? your uptime$|^uptime$")),
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
        r"^(?:hi|hello|hey|yo|hiya|howdy|hey there|hi there)$"
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
        r"|^any (?:replies|responses|word|news)(?: from (?:employers|anyone|the jobs))?(?: yet| today)?$"
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
        r"^what(?:'s| is|s)? (?P<pct>[\d.]+) ?(?:%|percent) of (?P<of>[\d.,]+)$"
        r"|^what(?:'s| is|s)? (?P<a>[\d.,]+) (?P<op>plus|minus|times|divided by|over|x|\+|-|\*|/) (?P<b>[\d.,]+)$"
        r"|^(?:convert |what(?:'s| is|s)? )?(?P<n>[\d.,]+) (?P<from>miles?|km|kilometers?|kilometres?|pounds?|lbs?|"
        r"kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c)"
        r" (?:to|in|into) (?P<to>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|"
        r"meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c)$"
        # THE OTHER WORD ORDER: "how many miles is 10 km", "how many pounds in 5 kg"
        r"|^how many (?P<to2>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c) (?:is|are|in|make|equals?|to) (?P<n2>[\d.,]+|a|an|one) ?(?P<from2>miles?|km|kilometers?|kilometres?|pounds?|lbs?|kg|kilograms?|feet|foot|ft|meters?|metres?|inches|inch|cm|centimeters?|fahrenheit|celsius|f|c)$")),
    ("mine", re.compile(
        r"^what(?:'s| is|s)? my (?P<mine>email(?: address)?|phone(?: number)?"
        r"|number|city|town|name|first name|last name|full name)$"
        r"|^who am i$")),
    ("home", re.compile(
        r"^where do i live$|^what city do i live in$"
        r"|^what town do i live in$|^where(?:'s| is) home$")),
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
        if name == "status_of":
            return name, text
        if name in ("math", "farewell"):
            return name, text
        rest = next((captured[k] for k in ("what", "what2", "what3", "mine",
                                           "free", "free2", "free3",
                                           "down", "down2", "weather",
                                           "weather2", "weather3",
                                           "day", "day2", "day3", "day4", "day5", "day6", "day7",
                                           "outcome", "outcome2", "outcome3", "outcome4", "outcome5",
                                           "until", "until2", "day8", "day9",
                                           "why_not", "why_not2", "why_not3", "sent_window")
                     if captured.get(k)), "")
        if name in ("opportunity", "opportunity_loose", "applied_when", "person", "why_not"):
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


def _until(words: str) -> str | None:
    """Days until a date he named, from the calendar and nothing else."""
    import datetime as dt
    from aletheia import localtime
    today = dt.datetime.now(localtime.operator_tz()).date()
    when = _named_date(words, today)
    if when is None:
        return None            # a thing, not a date: the model may think
    days = (when - today).days
    said = when.strftime("%A %d %B").replace(" 0", " ")
    if days == 0:
        return f"That's today, {said}."
    if days == 1:
        return f"Tomorrow, {said}."
    return f"{days} days, {said}."


_STATE_WORDS = {"SUBMITTED": "it went", "SUBMITTING": "it is going out now",
                "AWAITING_YOU": "it is filled and waiting to go out on the next beat",
                "NEEDS_YOU": "it stopped on a question only you can answer",
                "NEEDS_ACCOUNT": "the site wants an account before it will take an application",
                "REJECTED": "the site refused the form", "FAILED": "it would not send",
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
    if state in ("FAILED", "REJECTED", "NEEDS_ACCOUNT", "CLOSED") and reason:
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


def _found() -> str:
    """Openings found today, from the hunt's own reading."""
    from aletheia import current_state, speech
    try:
        hunt = current_state.job_hunt() or {}
    except Exception:
        return "I can't read my application records right now."
    today = hunt.get("today") or {}
    found = int(today.get("discovered") or 0)
    if not found:
        return "No openings found today yet."
    fit = int(today.get("qualified") or 0)
    sent = int(today.get("sent") or 0)
    return (f"{speech.count_phrase(found, 'opening')} found today, {fit} worth applying to"
            + (f", {sent} sent" if sent else "") + ".")


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
    faults = []
    for a in fleet.get("alerts") or []:
        name = (repos.get(a.get("repo")) or {}).get("github") or a.get("github") or a.get("repo")
        why = (", ".join(f.replace(".yml", "") for f in a.get("failing") or []) + " failing") if a.get("failing") \
            else ("missing " + ", ".join(a["missing"])) if a.get("missing")             else ("can't be read" if a.get("error") else "a fault")
        faults.append(f"{name} ({why})")
    said = f"{speech.count_phrase(len(active), 'project')} active" + (f", {len(dormant)} dormant" if dormant else "")
    said += (f"; {speech.count_phrase(len(faults), 'fault')}: " + speech.and_list(faults)) if faults else "; no faults"
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


def _today() -> str:
    # A CALENDAR day, not the last 24 hours. Asked at nine in the morning,
    # a rolling window is mostly yesterday — and it would report the same
    # evening twice, once here and once under "yesterday".
    rows = _on_day(0)
    if not rows:
        return "Nothing yet today."
    return _listed(rows, "today")


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


def _date() -> str:
    """"What day is it" — the day first, because that is what he asked."""
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    return f"{now.strftime('%A')} the {_ordinal(now.day)} of {now.strftime('%B')}."


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
    label = ("Today" if first == last == now.date() else "Tomorrow" if first == last
             else "This week" if day == "this week" else "Next week")
    if not rows:
        return f"Nothing on your calendar {label.lower()}."
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
            return f"{said(num(g['pct']) * num(g['of']) / 100)}."
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
    alerts = [a for a in (latest.get("alerts") or []) if isinstance(a, dict)]
    if not alerts:
        return "Nothing red. The fleet is green."
    named = []
    for row in alerts[:3]:
        repo = str(row.get("repo") or row.get("github") or "something")
        failing = [str(f) for f in (row.get("failing") or [])]
        named.append(repo + (f" ({', '.join(failing[:2])})" if failing else ""))
    if len(alerts) > 3:
        named.append(f"{len(alerts) - 3} more")
    return (f"{speech.count_phrase(len(alerts), 'repo')} red: "
            + speech.and_list(named) + ".")


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
        return running.version_words(running.version())
    except Exception:
        return None


def _uptime() -> str | None:
    """How long she has been on, from her own heartbeat."""
    from aletheia import liveness
    seconds = liveness.uptime_seconds()
    if seconds is None:
        return None                 # she does not know; do not invent one
    return f"Up {liveness.spoken_duration(seconds)}."


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
         "full name": ("legal_name", "full_name")}

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
    fields = _MINE.get(asked)
    if not fields:
        return None
    try:
        for field in fields:
            value = profile.answer(field)
            if value:
                return str(value)
    except Exception:
        return None
    return (f"I don't have your {asked} on file. "
            "Tell me and I'll remember it.")


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
    if groups.get("count_window"):
        # "How many jobs did I apply to this week" waited two minutes on her
        # own model (2026-09-22); the records carry their dates.
        return "count_window", groups["count_window"].strip()
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
        # "Is the job hunt running" arrives here when its subject was said
        # in a way _JOB does not list; the pulse will not know it either.
        if _JOB_RE.fullmatch(subject):
            shape = "still"
        elif subject in ("aletheia", "thea", "you", "yourself", "everything", "it all"):
            # Her own status is the "what are you doing" answer, not the
            # Aletheia repository's row of the pulse.
            return _doing()
        else:
            return current_state.repo_words(subject)
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
        stage = mission_jobs.stage_of(record).replace("_", " ").casefold()
        return f"{apply_run.describe(record)}: {stage}." + (
            f" {record['say']}" if record.get("say") else "")
    return f"I don't have an application to {words}."


_WINDOW_DAYS = {"today": 0, "tonight": 0, "so far": 0, "yesterday": 1, "this week": 7, "so far this week": 7,
                "last week": 14, "this month": 30}


def _sent_count(window: str) -> str | None:
    """How many applications went out in a window, counted from the records."""
    import datetime as dt
    from aletheia import apply_run, speech
    window = " ".join(str(window or "today").split()).casefold()
    try:
        rows = apply_run.all_runs("SUBMITTED")
    except Exception:
        return "I can't read my application records right now, so I can't say."
    now = dt.datetime.now(dt.timezone.utc)
    days = _WINDOW_DAYS.get(window)
    if days is None:                           # in total / altogether / ever
        count, span = len(rows), "in all"
    elif days == 0:
        today = now.astimezone().date()
        count = sum(1 for r in rows if _local_day(r.get("submitted_at")) == today)
        span = "today"
    else:
        since = now - dt.timedelta(days=days)
        count = sum(1 for r in rows if _stamp_of(r.get("submitted_at")) and _stamp_of(r.get("submitted_at")) >= since)
        span = window if window != "so far this week" else "this week"
        if window == "yesterday":
            yesterday = (now.astimezone() - dt.timedelta(days=1)).date()
            count = sum(1 for r in rows if _local_day(r.get("submitted_at")) == yesterday)
    if not count:
        return f"None {span} - no applications went out{' ' + span if span != 'in all' else ' at all'}."
    return f"{speech.count_phrase(count, 'application')} sent {span}."


def _stamp_of(value) -> "dt.datetime | None":
    import datetime as dt
    try:
        when = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _local_day(value):
    when = _stamp_of(value)
    return when.astimezone().date() if when else None


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
    said = str((turns[-1] if turns else {}).get("she_said") or "").strip()
    return f"I said: {said}" if said else "I haven't said anything yet this conversation."


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
           "sent_count": _sent_count,
           "up_to_date": lambda rest: _updated(asked_yes_no=True),
           "to_answer": lambda rest: _to_answer(),
           "found": lambda rest: _found(),
           "fleet": lambda rest: _fleet(),
           "focus": lambda rest: _focus(),
           "outcomes": _outcomes,
           "until": _until,
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
           "repeat": lambda rest: _repeat(),
           "sent_today": lambda rest: _sent_today(),
           "machine": lambda rest: _machine(),
           "waiting": lambda rest: _waiting(),
           "doing": lambda rest: _doing(),
           "job_hunt": lambda rest: _job_hunt(),
           "wrong": lambda rest: _wrong(),
           "today": lambda rest: _today(),
           "yesterday": lambda rest: _yesterday(),
           "clock": lambda rest: _clock(),
           "date": lambda rest: _date(),
           "month": lambda rest: _month(),
           "year": lambda rest: _year(),
           "can_you": _can_you,
           "tasks": lambda rest: _tasks(),
           "approvals": lambda rest: _approvals(),
           "capabilities": lambda rest: _capabilities(),
           "cannot": lambda rest: _cannot(),
           "agenda": lambda rest: _agenda(rest or "today"),
           "how_many": lambda rest: _how_many(),
           "alerts": lambda rest: _alerts(),
           "repos": lambda rest: _repos(),
           "shopping": lambda rest: _shopping(),
           "uptime": lambda rest: _uptime(),
           "version": lambda rest: _version(),
           "free": _free,
           "next_meeting": lambda rest: _next_meeting(),
           "running": lambda rest: _running(),
           "mine": _mine,
           "weather": lambda rest: _weather(rest),
           "greeting": lambda rest: _greeting(),
           "home": lambda rest: _home(),
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


def answer(question: str) -> str | None:
    """An answer from her own stores, or None to go and think.

    Never raises. A fast path that can break a request is worse than no
    fast path — the slow one was working.
    """
    try:
        found = match(question)
        if not found:
            return None
        name, rest = found
        said = ANSWERS[name](rest)
        # `str(None)` is the four-character string "None", which is truthy
        # and would have been spoken out loud as an answer.
        if said is None:
            return None
        return str(said).strip() or None
    except Exception:
        return None
