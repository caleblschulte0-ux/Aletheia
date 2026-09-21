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
    r"(?: (?:have|did|has) (?:you|u|she|we))? ?(?P<count>applied (?:to|for|at)|apply (?:to|for|at)|"
    r"sent(?: out)?|submitted|put in|done|gotten through|finished|completed|applied)"
    r"(?: (?:to|for))?(?P<count_total> (?:in total|total|overall|all ?together|altogether|ever|"
    r"so far|to date|all time))?(?: (?:today|now))?$"
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
        r"|^what am i blocking$|^am i blocking anything$")),
    ("doing", re.compile(
        r"^what (?:are|r) (?:you|u) (?:doing|working on|up to)"
        r"(?: right now| now| at the moment| currently)?$"
        r"|^what(?:'s| is|s)? (?:happening|going on|the status)(?: right now| now)?$"
        r"|^status$|^how(?:'s| is) it going$")),
    # The brief's first question, answered from the application records
    # with no model: every number in the answer is a count of records.
    ("job_hunt", re.compile(
        r"^how (?:did|have|are) (?:the )?(?:job )?(?:applications|apps|job hunt|hunt|job search)"
        r" (?:go|gone|going)(?: today| so far| so far today)?$"
        r"|^how(?:'s| is) the (?:job )?(?:hunt|search|applications?)(?: going)?(?: today)?$"
        r"|^(?:did|have) (?:you|u) (?:apply|applied) to (?:any|anything|any jobs)(?: today)?$"
        r"|^(?:job )?(?:applications|hunt) (?:status|today|report)$")),
    # The third question. It has a `recollection` pattern for the model's
    # context and no fast answer, so "what went wrong today" paid a round
    # trip to read out alerts that are a file read away.
    ("wrong", re.compile(
        r"^what went wrong(?: today| so far today)?$"
        r"|^what(?:'s| is|s)? (?:broken|failing|stuck)(?: today)?$"
        r"|^(?:did|has) anything (?:fail|failed|go wrong|gone wrong|break|broken)(?: today)?$"
        r"|^what failed(?: today)?$|^any (?:errors|failures|problems)(?: today)?$")),
    ("today", re.compile(
        r"^what (?:did|have) (?:you|u) (?:do|done)(?: today)?$"
        r"|^what have (?:you|u) been doing$"
        r"|^what did (?:you|u) get done(?: today)?$"
        # "Show me the journal" went to the planner, which compiled
        # `recall` and answered "I don't have anything remembered about
        # 'journal entries'" — a lookup in the wrong store.
        r"|^(?:show me |read me )?(?:the |your )?journal$"
        r"|^what(?:'s| is|s)? in (?:the |your )?journal$")),
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
        r"|^what tasks do i have$|^how many tasks do i have$"
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
        r"|^what(?:'s| is|s)? (?:my|the) (?P<day6>week) (?:looking like|look like)$")),
    ("alerts", re.compile(
        r"^(?:are there |is there )?any(?:thing)? (?:alerts|broken|wrong|failing)$"
        r"|^any alerts$|^is anything broken$|^anything broken$"
        r"|^how(?:'s| is) the fleet$|^is everything (?:ok|green|fine)$"
        r"|^fleet status$")),
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
        r"^(?P<night>good ?night|night night|sleep well|i'?m going to (?:bed|sleep))$"
        r"|^(?:i'?m|im|i am) (?:leaving|heading out|going out|off|out)(?: now)?$"
        r"|^(?:see (?:you|ya)(?: later)?|bye|goodbye|later|talk later|catch you later)$")),
    # Replies from employers, from the application records.
    ("replies", re.compile(
        r"^(?:did|have) i (?:get|got|gotten|receive|received|hear) (?:any |anything )?(?:replies|responses|"
        r"back|any(?:thing)? back)(?: yet| today| from anyone)?$"
        r"|^any (?:replies|responses|word|news)(?: from (?:employers|anyone|the jobs))?(?: yet| today)?$"
        r"|^(?:has|did) anyone (?:replied|reply|written back|write back|got back|get back)(?: to me)?(?: yet)?$")),
    # Why she is slow is a question about who is thinking.
    ("slow", re.compile(
        r"^why (?:are|r) (?:you|u) (?:so |being )?slow(?: today| right now)?$"
        r"|^why (?:is|does) (?:this|it|everything) (?:take|taking) so long$"
        r"|^what(?:'s| is) taking so long$|^who(?:'s| is) (?:thinking|answering)(?: right now)?$"
        r"|^(?:are|r) (?:you|u) (?:using|on) (?:your own|the local) (?:model|brain)$")),
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
                                           "day", "day2", "day3", "day4", "day5", "day6")
                     if captured.get(k)), "")
        return name, rest
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


def _job_hunt() -> str | None:
    """How the applications went today, counted from the records."""
    try:
        from aletheia import current_state
        return current_state.job_hunt_words()
    except Exception:
        return None                 # she does not know; the model may look


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
        return "No replies from employers today."
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
        return None                 # no pulse written yet is not "all green"
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


ANSWERS = {"halted": lambda rest: _halted(asks_if_down=bool(rest)),
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
