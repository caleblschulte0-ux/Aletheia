"""The fast lane: answers she already has, given without a model call.

Measured 2026-09-05 on the operator's own subscription, a `claude -p`
round trip is ~3.6 seconds regardless of how small the answer is, and
"are you halted?" was paying it twice — once for the planner to classify
it, once for `converse` to answer it. This module removes that for a
handful of sentences he says constantly.

The whole safety argument for it is one sentence: **it may only ever
remove latency, never an answer.** So most of what is tested here is the
declining. A pattern that fires on something it cannot really answer is
worse than no fast path at all, because the slow path was working.
"""
import unittest
from unittest import mock

from aletheia import quick, speech, voice

REGISTRY_MATCH = [{"capability": "documents.read", "status": "AVAILABLE",
                   "what_it_is": "Get the words out of a PDF or .docx"}]


def stub_registry(matches):
    return mock.patch("aletheia.self_knowledge.for_question",
                      lambda q, **kw: {"asked_about": "specific",
                                       "matches": list(matches)})


class MatchCase(unittest.TestCase):
    """Which sentences the shortcut claims, and — mostly — which it does not."""

    def test_the_five_shapes_are_recognised(self):
        for sentence, expected in (
                ("are you halted?", "halted"),
                ("r u stopped", "halted"),
                ("Are you running?", "halted"),
                ("what's waiting on me", "waiting"),
                ("do you need anything from me", "waiting"),
                ("what are you doing", "doing"),
                ("status", "doing"),
                ("what did you do today?", "today"),
                ("can you read a pdf", "can_you"),
                ("are you able to book a flight", "can_you")):
            with self.subTest(sentence=sentence):
                found = quick.match(sentence)
                self.assertIsNotNone(found, f"{sentence!r} should be claimed")
                self.assertEqual(found[0], expected)

    def test_every_pattern_has_an_answer_and_the_reverse(self):
        """A pattern with no answer would fail silently: `answer` swallows
        the KeyError and returns None, so the sentence would still work —
        just slowly, forever, with nobody knowing the shortcut was dead."""
        names = [name for name, _p in quick.PATTERNS]
        self.assertEqual(sorted(names), sorted(quick.ANSWERS),
                         "a pattern and its answer must exist in both places")
        self.assertEqual(len(names), len(set(names)), "duplicate pattern name")

    def test_real_work_is_never_claimed(self):
        """The important half. These go to the planner, which can do them."""
        for sentence in (
                "apply to ten jobs with my resume",
                "email dana and tell her i'll be late",
                "cancel my gym membership",
                "book a table for two on friday",
                "halt",
                "resume",
                "approve",
                # About halting, not a question about her state.
                "tell me about the halt behaviour in the docs",
                "why did you stop the trader",
                "what did dana say today",
                "can you",              # too short to be a capability question
                ""):
            with self.subTest(sentence=sentence):
                self.assertIsNone(quick.match(sentence),
                                  f"{sentence!r} must reach the planner")

    def test_a_long_sentence_is_never_claimed(self):
        """A paragraph that happens to start "can you" is not a lookup."""
        self.assertIsNone(quick.match("can you " + "x" * quick.MAX_QUESTION))


class AnswerCase(unittest.TestCase):
    """Every answer comes out of a real store, or there is no answer."""

    def test_halted_reads_the_real_switch(self):
        with mock.patch("aletheia.policy.halted", lambda: None):
            self.assertEqual(quick.answer("are you halted"), "No, I'm running.")
        with mock.patch("aletheia.policy.halted",
                        lambda: {"reason": "he said stop"}):
            said = quick.answer("are you halted")
        self.assertIn("Yes", said)
        self.assertIn("he said stop", said)

    def test_waiting_counts_what_is_actually_there(self):
        empty = {"halted": False, "waiting_on_you": [], "notifications": []}
        with mock.patch("aletheia.presence.snapshot", lambda: empty):
            self.assertEqual(quick.answer("what's waiting on me"),
                             "Nothing is waiting on you.")
        loaded = {"halted": False,
                  "waiting_on_you": [{"label": "send the email to Dana"},
                                     {"label": "the errand"}],
                  "notifications": [{"title": "trader is down"}]}
        with mock.patch("aletheia.presence.snapshot", lambda: loaded):
            said = quick.answer("anything i need to do")
        self.assertIn("2 waiting on you", said)
        self.assertIn("send the email to Dana", said)
        # Spoken out loud, so "1 thing(s)" is not acceptable output.
        self.assertNotIn("(s)", said)

    def test_waiting_says_halted_first(self):
        """"What's waiting on me" while halted has a different true answer."""
        snap = {"halted": True, "waiting_on_you": [{"label": "x"}],
                "notifications": []}
        with mock.patch("aletheia.presence.snapshot", lambda: snap), \
             mock.patch("aletheia.policy.halted", lambda: {"reason": "stop"}):
            said = quick.answer("what's waiting on me")
        self.assertIn("halted", said.lower())
        self.assertIn("resume", said.lower())

    def test_doing_uses_the_field_presence_actually_writes(self):
        """`working` rows are keyed `what`. Guessing `description` here got
        "Working on 2 thing(s): ; " — punctuation with nothing inside it."""
        snap = {"headline": "", "working": [{"what": "rendering the slate"},
                                            {"what": "syncing"}]}
        with mock.patch("aletheia.presence.snapshot", lambda: snap):
            said = quick.answer("what are you doing")
        self.assertIn("rendering the slate", said)
        self.assertNotIn(": ;", said)

    def test_today_uses_the_field_recollection_actually_writes(self):
        # It reads `on_date` now, not `day`: "today" is a calendar day on
        # HIS clock, not the last 24 hours, or the same evening gets
        # reported twice — once here and once under "yesterday". The rule
        # this protects is the FIELD (`what`) and the sentence, not which
        # function supplies the rows.
        rows = [{"what": "intent: answered on the spot"},
                {"what": "sync: pushed receipts"}]
        with mock.patch("aletheia.recollection.on_date", lambda *a, **k: rows):
            said = quick.answer("what did you do today")
        self.assertIn("pushed receipts", said)
        self.assertIn("2 things today", said)
        self.assertNotIn("(s)", said)
        with mock.patch("aletheia.recollection.on_date", lambda *a, **k: []):
            self.assertEqual(quick.answer("what did you do today"),
                             "Nothing yet today.")

    def test_yesterday_is_a_different_day_not_a_longer_window(self):
        rows = [{"what": "sync: pushed receipts"}]
        seen = []

        def on_date(date, **k):
            seen.append(date)
            return rows

        with mock.patch("aletheia.recollection.on_date", on_date):
            said = quick.answer("what did you do yesterday")
            quick.answer("what did you do today")
        self.assertIn("1 thing yesterday", said)
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1])
        with mock.patch("aletheia.recollection.on_date", lambda *a, **k: []):
            self.assertIn("yesterday", quick.answer("what happened yesterday"))

    def test_what_he_asked_for_is_not_what_she_did(self):
        # "What did I ask you to do yesterday" asks for HIS instructions;
        # her journal also holds scheduled work nobody asked for. The fast
        # lane must not answer the near-miss — that one keeps the model,
        # which now gets the right day's journal to answer from.
        self.assertIsNone(quick.match("what did i ask you to do yesterday"))

    def test_can_you_answers_from_the_registry(self):
        with stub_registry(REGISTRY_MATCH):
            said = quick.answer("can you read a pdf")
        self.assertTrue(said.startswith("Yes"))
        self.assertIn("PDF", said)

    def test_can_you_is_honest_about_what_is_not_built(self):
        with stub_registry([{"capability": "flight.book", "status": "NOT_BUILT",
                             "what_it_is": "Book a flight"}]), \
             mock.patch("aletheia.demand.record", lambda *a, **k: None):
            said = quick.answer("can you book a flight")
        self.assertTrue(said.startswith("No"))
        self.assertIn("not built", said)

    def test_an_unrecognised_capability_goes_to_the_planner(self):
        """No registry match is not "no" — it is "I should think about it"."""
        with stub_registry([]):
            self.assertIsNone(quick.answer("can you fly a helicopter"))

    def test_a_no_still_reaches_the_demand_ledger(self):
        """`converse` counts a not-AVAILABLE "can you...?" as demand, and
        this path now answers some of those before `converse` ever runs. A
        shortcut that stops feeding the ledger makes the thing he asks for
        most often look like the thing he stopped asking for."""
        seen = []
        with stub_registry([{"capability": "flight.book", "status": "NOT_BUILT",
                             "what_it_is": "Book a flight"}]), \
             mock.patch("aletheia.demand.record",
                        lambda cap, asked, **kw: seen.append((cap, kw.get("status")))):
            quick.answer("can you book a flight")
        self.assertEqual(seen, [("flight.book", "NOT_BUILT")])

    def test_available_is_not_recorded_as_demand(self):
        seen = []
        with stub_registry(REGISTRY_MATCH), \
             mock.patch("aletheia.demand.record",
                        lambda *a, **k: seen.append(a)):
            quick.answer("can you read a pdf")
        self.assertEqual(seen, [])


class WarmingUpCase(unittest.TestCase):
    """The first answer cost ~420 ms and every one after it under 1 ms.
    None of that is work; it is lazy imports, and it landed on whichever
    question he happened to ask first."""

    def test_it_asks_for_real_answers(self):
        asked = []
        with mock.patch.object(quick, "answer", side_effect=asked.append):
            quick.warm()
        self.assertEqual(asked, list(quick._WARM))

    def test_every_warm_sentence_is_one_the_lane_claims(self):
        """A warm-up that missed the patterns would import nothing and
        quietly do no good at all."""
        for sentence in quick._WARM:
            with self.subTest(sentence=sentence):
                self.assertIsNotNone(quick.match(sentence))

    def test_a_store_that_explodes_does_not_take_the_core_down(self):
        """It runs on a thread at startup. Raising there would be a crash
        in the one place nothing is watching."""
        with mock.patch.object(quick, "answer", side_effect=RuntimeError("boom")):
            quick.warm()          # must not raise

    def test_it_writes_nothing(self):
        """Warming is reads only — it must never journal, because "she
        answered a question" nobody asked would be a lie in the record."""
        with mock.patch("aletheia.journal.append") as wrote:
            quick.warm()
        wrote.assert_not_called()



class NeverBreaksCase(unittest.TestCase):
    """A fast path that can break a request is worse than no fast path."""

    def test_a_store_that_raises_falls_through(self):
        def boom():
            raise RuntimeError("disk gone")
        with mock.patch("aletheia.presence.snapshot", boom):
            self.assertIsNone(quick.answer("what's waiting on me"))

    def test_none_is_never_spoken_as_the_word_none(self):
        """`str(None)` is the four-character string "None" — truthy, and it
        would have been read out loud as an answer."""
        with mock.patch.dict(quick.ANSWERS, {"halted": lambda rest: None}):
            self.assertIsNone(quick.answer("are you halted"))

    def test_an_empty_answer_falls_through(self):
        with mock.patch.dict(quick.ANSWERS, {"halted": lambda rest: "   "}):
            self.assertIsNone(quick.answer("are you halted"))


class WiredCase(unittest.TestCase):
    """It has to actually be in front of the planner, or it saves nothing."""

    def test_propose_answers_without_compiling_a_plan(self):
        from aletheia import intents

        def never(*a, **kw):
            raise AssertionError("the planner was called for a stored answer")

        with mock.patch("aletheia.policy.halted", lambda: None), \
             mock.patch.object(intents.planner, "compile", never):
            record = intents.propose("are you halted?", quote="are you halted?")
        self.assertTrue(record.get("fast_path"))
        self.assertEqual(record["intent"], "answer")
        self.assertEqual(record["spoken"], "No, I'm running.")
        self.assertEqual(intents.spoken(record), "No, I'm running.")

    def test_a_real_ask_still_reaches_the_planner(self):
        from aletheia import intents
        called = []

        def never(*a, **kw):
            called.append(a)
            raise RuntimeError("stop here")

        with mock.patch.object(intents.planner, "compile", never):
            with self.assertRaises(RuntimeError):
                intents.propose("apply to ten jobs with my resume")
        self.assertTrue(called, "real work must not be swallowed by the shortcut")


class AnsweredNowCase(unittest.TestCase):
    """The Core's gate on the followup path.

    `intent` is in SLOW_KINDS, so an intent normally becomes "Working on
    that." plus a poll. This decides which intents skip that.
    """

    def setUp(self):
        from aletheia import core
        self.core = core

    def test_a_stored_answer_is_returned(self):
        with mock.patch("aletheia.policy.halted", lambda: None):
            said = self.core.answered_now({"kind": "intent",
                                           "text": "are you halted"})
        self.assertEqual(said, "No, I'm running.")

    def test_a_matching_shape_with_no_stored_answer_is_not_run_inline(self):
        """"Can you fly a helicopter" MATCHES the can-you pattern and has no
        answer in the registry — so it falls to the planner. Deciding this
        on the pattern instead of on the answer would have run a full
        planner round trip inline and held the room open for it."""
        with stub_registry([]):
            self.assertIsNotNone(quick.match("can you fly a helicopter"))
            self.assertIsNone(self.core.answered_now(
                {"kind": "intent", "text": "can you fly a helicopter"}))

    def test_other_kinds_are_left_alone(self):
        self.assertIsNone(self.core.answered_now(
            {"kind": "screen_ask", "question": "are you halted"}))
        self.assertIsNone(self.core.answered_now({"kind": "halt"}))

    def test_it_never_raises(self):
        with mock.patch("aletheia.quick.answer",
                        mock.Mock(side_effect=RuntimeError("boom"))):
            self.assertIsNone(self.core.answered_now(
                {"kind": "intent", "text": "are you halted"}))


class SpokenIdsCase(unittest.TestCase):
    """Two real defects found while making these sentences model-free."""

    def test_a_namespaced_digest_is_stripped(self):
        """The wall's headline was reading "4 decisions waiting:
        browser.interact:193cc723561941c0…" — `ID_TOKEN` only knew the
        HYPHENATED id shape, and a content-bound approval names itself with
        a sha256 after a colon."""
        said = speech.strip_ids(
            "4 decisions waiting: browser.interact:193cc7235619a1b2c3d4")
        self.assertNotIn("193cc7235619", said)
        self.assertIn("4 decisions waiting", said)
        self.assertNotIn("a1e1957d0f", speech.strip_ids("mail-a1e1957d0f"))
        self.assertNotIn("193cc7235619a1b2", speech.strip_ids(
            "193cc7235619a1b2c3d4"))

    def test_ordinary_words_survive(self):
        """The widened pattern must not eat English."""
        for text in ("decided to send the email", "the trader is fine",
                     "docs/PLAYBOOK.md", "a1b2 is short"):
            with self.subTest(text=text):
                self.assertEqual(speech.strip_ids(text), text)

    def test_an_approval_is_labelled_by_its_reason_not_its_hash(self):
        label = voice.approval_label({
            "capability": "browser.interact",
            "requested_action": "browser.interact:193cc7235619a1b2c3d4",
            "reason": 'operator said: "cancel my gym membership"'})
        self.assertIn("cancel my gym membership", label)
        self.assertNotIn("193cc7235619", label)



class TheWiderLaneCase(unittest.TestCase):
    """2026-09-07: measured against 68 sentences a person actually says,
    the lane caught 50% of them. The other half paid 25-50 SECONDS for
    answers sitting in files on the same disk. These are the ones added,
    and the shapes that must still be declined."""

    def test_the_near_misses_are_claimed(self):
        """Every one of these was a full planner round trip for an answer
        the module already knew how to give — it just did not recognise
        the way he said it."""
        for sentence, expected in (
                ("what time is it right now", "clock"),
                ("got the time", "clock"),
                ("what is the date today", "date"),
                # No verb at all is how a person actually checks.
                ("you there", "halted"),
                ("you awake", "halted"),
                ("still there", "halted"),
                ("you good", "halted"),
                ("are you still there", "halted"),
                ("is there anything waiting", "waiting"),
                ("anything i should know", "waiting"),
                ("what am i blocking", "waiting")):
            with self.subTest(sentence=sentence):
                found = quick.match(sentence)
                self.assertIsNotNone(found, f"{sentence!r} should be claimed")
                self.assertEqual(found[0], expected)

    def test_the_new_stores_are_claimed(self):
        for sentence, expected in (
                ("what's on my task list", "tasks"),
                ("how many tasks do i have", "tasks"),
                ("what's my next task", "tasks"),
                ("what needs approving", "approvals"),
                ("how many approvals are pending", "approvals"),
                ("what can you do", "capabilities"),
                ("any alerts", "alerts"),
                ("is anything broken", "alerts"),
                ("how's the fleet", "alerts"),
                ("what's my email", "mine"),
                ("what's my phone number", "mine"),
                ("where do i live", "home"),
                ("what month is it", "month"),
                ("what year is it", "year")):
            with self.subTest(sentence=sentence):
                found = quick.match(sentence)
                self.assertIsNotNone(found, f"{sentence!r} should be claimed")
                self.assertEqual(found[0], expected)

    def test_a_year_is_not_answered_with_a_date_sentence(self):
        """The regression this split exists for. `_date` says "Monday the
        7th of September" — which contains NO YEAR — and folding "what
        year is it" into it answered confidently and wrongly, which is the
        one thing this module may never do."""
        import datetime as dt
        said = quick.answer("what year is it")
        self.assertIn(str(dt.date.today().year), said)
        month = quick.answer("what month is it")
        self.assertIn(dt.date.today().strftime("%B"), month)

    def test_the_still_ambiguous_are_still_declined(self):
        """"What are my plans" is his calendar to a person and a `plans`
        record to her; "am I free" needs a calendar she does not have
        connected. When in doubt the lane says nothing."""
        for sentence in (
                "what's on my calendar",
                "am i free today",
                "what plans do i have",
                "what did you do last week"):
            with self.subTest(sentence=sentence):
                self.assertIsNone(quick.match(sentence),
                                  f"{sentence!r} must reach the planner")

    def test_tasks_counts_the_real_store_and_names_the_next(self):
        rows = [{"id": "a", "description": "call the plumber", "status": "QUEUED",
                 "dependencies": []},
                {"id": "b", "description": "done thing", "status": "COMPLETED",
                 "dependencies": []}]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            said = quick.answer("what's on my task list")
        self.assertIn("1 task", said)
        self.assertIn("call the plumber", said)
        self.assertNotIn("done thing", said)

    def test_an_empty_task_list_says_so(self):
        with mock.patch("aletheia.tasks.all_tasks", lambda: []):
            self.assertEqual(quick.answer("what are my tasks"),
                             "Nothing open on your task list.")

    def test_a_failed_task_is_still_on_his_list(self):
        """Something that broke is exactly what he wants named when he
        asks what is open — it is not "done"."""
        rows = [{"id": "a", "description": "the upload that broke",
                 "status": "FAILED", "dependencies": []}]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            said = quick.answer("what's on my task list")
        self.assertIn("the upload that broke", said)

    def test_approvals_counts_only_what_is_pending(self):
        rows = [{"state": "PENDING", "reason": 'operator said: "buy the monitor"'},
                {"state": "APPROVED", "reason": "already said yes"}]
        with mock.patch("aletheia.policy.all_approvals", lambda: rows):
            said = quick.answer("what needs approving")
        self.assertIn("1 approval", said)
        self.assertIn("buy the monitor", said)
        self.assertNotIn("already said yes", said)

    def test_no_approvals_says_so(self):
        with mock.patch("aletheia.policy.all_approvals", lambda: []):
            self.assertEqual(quick.answer("how many approvals are pending"),
                             "Nothing is waiting on your approval.")

    def test_capabilities_comes_out_of_the_registry(self):
        over = {"by_status": {"AVAILABLE": 7, "EXPERIMENTAL": 2,
                              "NOT_BUILT": 1}}
        with mock.patch("aletheia.self_knowledge.overview", lambda: over):
            said = quick.answer("what can you do")
        self.assertIn("7 things are live", said)
        self.assertIn("2 experimental", said)
        self.assertIn("1 not built", said)

    def test_an_unreadable_registry_goes_to_the_planner(self):
        with mock.patch("aletheia.self_knowledge.overview", lambda: {}):
            self.assertIsNone(quick.answer("what can you do"))

    def test_alerts_reads_the_pulse_she_writes(self):
        import json
        payload = json.dumps({"alerts": [{"repo": "shorts", "failing": ["daily.yml"]}]})
        with mock.patch("pathlib.Path.read_text", lambda self, **kw: payload):
            said = quick.answer("is anything broken")
        self.assertIn("shorts", said)
        self.assertIn("daily.yml", said)

    def test_a_green_fleet_says_green(self):
        import json
        with mock.patch("pathlib.Path.read_text",
                        lambda self, **kw: json.dumps({"alerts": []})):
            self.assertEqual(quick.answer("any alerts"),
                             "Nothing red. The fleet is green.")

    def test_no_pulse_at_all_is_not_reported_as_green(self):
        """A missing file means she does not know, and "everything is
        fine" is the worst available guess."""
        def boom(self, **kw):
            raise OSError("no pulse yet")
        with mock.patch("pathlib.Path.read_text", boom):
            self.assertIsNone(quick.answer("any alerts"))

    def test_the_shopping_list_is_the_intercom_sentence(self):
        """Written once. `quick` and the `shopping_list` command must not
        drift into two different sentences for the same store."""
        from aletheia import intercom
        with mock.patch("aletheia.intercom._shopping_items",
                        lambda: [{"id": "w1", "need": "milk"}]):
            said = quick.answer("what's on my shopping list")
            self.assertEqual(said, intercom.shopping_answer())
        self.assertIn("milk", said)

    def test_an_empty_shopping_list_says_so(self):
        with mock.patch("aletheia.intercom._shopping_items", lambda: []):
            self.assertEqual(quick.answer("what do i need to buy"),
                             "Nothing on your shopping list.")

    def test_the_shopping_overflow_does_not_say_and_twice(self):
        rows = [{"id": f"w{i}", "need": f"item{i}"} for i in range(11)]
        with mock.patch("aletheia.intercom._shopping_items", lambda: rows):
            said = quick.answer("my shopping list")
        self.assertIn("3 more", said)
        self.assertNotIn(", and", said)

    def test_repos_counts_the_pulse(self):
        import json
        payload = json.dumps({"repos": {"aletheia": {}, "shorts": {}}})
        with mock.patch("pathlib.Path.read_text", lambda self, **kw: payload):
            said = quick.answer("how many repos are you watching")
        self.assertIn("2 repos", said)
        self.assertIn("aletheia", said)

    def test_an_empty_pulse_is_not_reported_as_zero_repos(self):
        import json
        with mock.patch("pathlib.Path.read_text",
                        lambda self, **kw: json.dumps({"repos": {}})):
            self.assertIsNone(quick.answer("how many repos are you watching"))

    def test_the_overflow_does_not_say_and_twice(self):
        """`and_list` already supplies the conjunction, so appending
        ", and N more" after it read "a, b, c and d, and 2 more"."""
        import json
        repos = {f"repo{i}": {} for i in range(6)}
        with mock.patch("pathlib.Path.read_text",
                        lambda self, **kw: json.dumps({"repos": repos})):
            said = quick.answer("how many repos are you watching")
        self.assertIn("2 more", said)
        self.assertNotIn(", and", said)

    def test_his_details_come_from_his_profile(self):
        with mock.patch("aletheia.profile.answer",
                        lambda field: {"email": "caleb@example.com"}.get(field)):
            self.assertEqual(quick.answer("what's my email"), "caleb@example.com")

    def test_a_detail_she_does_not_have_is_never_invented(self):
        """An invented phone number is the exact failure `profile` exists
        to prevent, and it would be spoken with total confidence."""
        with mock.patch("aletheia.profile.answer", lambda field: None):
            said = quick.answer("what's my phone number")
        self.assertIn("don't have your phone", said)

    def test_where_he_lives_reads_the_city_field(self):
        with mock.patch("aletheia.profile.answer",
                        lambda field: "Hartford, SD" if field == "city" else None):
            self.assertEqual(quick.answer("where do i live"), "Hartford, SD")



if __name__ == "__main__":
    unittest.main()
