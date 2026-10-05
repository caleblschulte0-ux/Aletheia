"""Fourth sandbox batch, 2026-10-04, frontier off:

    > add netflix at 15.49 a month to my subscriptions   [8.7s] journaled
    > what subscriptions do I have                        No subscriptions are being tracked.

The store had a writer (subscriptions.create) and no sentence that reached
it, so the planner filed the ask as a NOTE - a capability nothing can say is
not a capability (rule zero) - and the receipt it read back was the handler's
return value, a developer's word. And "what did you say", after eighteen
answers: "I haven't said anything yet this conversation" - the reader asked
the thread for a key it never writes.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, quick, voice


class ASubscriptionIsASentence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        from aletheia import subscriptions
        p = mock.patch.object(subscriptions, "SUBS_DIR", Path(self.tmp.name)); p.start(); self.addCleanup(p.stop)
        self.subs = subscriptions

    def test_the_ways_he_says_it(self):
        for said, merchant, amount, cadence in (
                ("add Netflix at 15.49 a month to my subscriptions", "Netflix", "15.49", "monthly"),
                ("track my Spotify subscription at $11.99 per month", "Spotify", "11.99", "monthly"),
                ("I pay 120 a year for Amazon Prime", "Amazon Prime", "120", "annual"),
                ("add the gym at 30 a month", "gym", "30", "monthly")):
            cmd = voice.interpret(said)["command"]
            self.assertEqual(cmd, {"kind": "subscription_add", "merchant": merchant, "amount": amount,
                                   "cadence": cadence}, said)

    def test_the_round_trip_she_failed(self):
        cmd = voice.interpret("add Netflix at 15.49 a month to my subscriptions")["command"]
        said = intercom.execute_command(cmd, {}, quote="t")
        self.assertEqual(said, "Tracking Netflix at $15.49 a month.")
        self.assertEqual(intercom.execute_command({"kind": "subscriptions"}, {}, quote="t"),
                         "1 active: Netflix. About $15.49 a month.")
        self.assertEqual(quick.answer("how much do I pay for netflix"), "You pay $15.49 a month for Netflix.")
        again = intercom.execute_command(cmd, {}, quote="t")
        self.assertEqual(again, "Netflix is already on your subscriptions list at $15.49.")

    def test_the_next_charge_is_the_soonest_dated_one(self):
        self.assertTrue(quick.answer("what's my next charge").startswith("Your subscriptions list is empty"))
        self.subs.create("spotify", merchant="Spotify", amount=11.99, next_charge="2026-10-20")
        self.subs.create("netflix", merchant="Netflix", amount=15.49, next_charge="2026-10-12")
        self.assertEqual(quick.answer("when is my next charge"), "Next charge: $15.49 for Netflix on 2026-10-12.")

    def test_it_is_routine_and_reversible_not_outward(self):
        self.assertEqual(intercom.tier("subscription_add"), intercom.tier("task_new"))
        self.assertNotIn("subscription_add", intercom.PLANNER_FORBIDDEN)


class WhatDidYouSayReadsTheThread(unittest.TestCase):
    def test_the_last_answer_comes_back(self):
        with mock.patch("aletheia.converse.recent",
                        return_value=[{"at": "", "he_asked": "what time is it", "she_answered": "6:56 pm."}]):
            self.assertEqual(quick.answer("what did you say"), "I said: 6:56 pm.")


class ANoteReceiptIsASentence(unittest.TestCase):
    def test_noted(self):
        with mock.patch("aletheia.journal.append"):
            self.assertEqual(intercom.execute_command({"kind": "note", "text": "x"}, {}, quote="t"), "Noted.")


if __name__ == "__main__":
    unittest.main()
