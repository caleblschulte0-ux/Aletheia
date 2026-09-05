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
        rows = [{"what": "intent: answered on the spot"},
                {"what": "sync: pushed receipts"}]
        with mock.patch("aletheia.recollection.day", lambda *a, **k: rows):
            said = quick.answer("what did you do today")
        self.assertIn("pushed receipts", said)
        self.assertIn("2 things today", said)
        self.assertNotIn("(s)", said)
        with mock.patch("aletheia.recollection.day", lambda *a, **k: []):
            self.assertEqual(quick.answer("what did you do today"),
                             "Nothing yet today.")

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


if __name__ == "__main__":
    unittest.main()
