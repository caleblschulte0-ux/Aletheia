"""Sweep 23 (2026-10-07): a timer of two parts, a pause that cannot
happen, an allergy said as a fact, and "I'm" read back as "you're"."""
import unittest

from aletheia import quick, speech, voice


class ATimerOfTwoParts(unittest.TestCase):
    def _minutes(self, said):
        import datetime as dt
        got = voice._interpret(said)["command"]
        self.assertEqual(got["kind"], "remind_at")
        at = dt.datetime.fromisoformat(got["at"])
        return round((at - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60), got["text"]

    def test_an_hour_and_a_half(self):
        self.assertEqual(self._minutes("set a timer for an hour and a half"), (90, "your 1 hour 30 minute timer is up"))

    def test_hours_and_minutes(self):
        self.assertEqual(self._minutes("set a timer for 1 hour and 20 minutes")[0], 80)

    def test_and_a_half_minutes(self):
        self.assertEqual(self._minutes("timer for two and a half minutes")[0], 2)  # 2.5 rounds to 2

    def test_the_receipt_says_it_as_a_span(self):
        receipt = ("Scheduled 2026-10-07T07:00:00+00:00 — 'your 1 hour 30 minute timer is up'")
        said = speech.spoken_receipt("remind_at", receipt)
        self.assertIn("1 hour and 30 minutes", said)

    def test_a_pause_says_what_she_can_do(self):
        got = voice._interpret("pause the timer")
        self.assertIsNone(got["command"])
        self.assertIn("add 5 minutes", got["say"])


class AnAllergySaidAsAFact(unittest.TestCase):
    def test_it_is_kept_as_a_note(self):
        self.assertEqual(voice._interpret("i'm allergic to peanuts")["command"]["kind"], "note")

    def test_asked_about_one_allergy(self):
        self.assertEqual(quick.match("am i allergic to peanuts"), ("recall", "allergic"))

    def test_im_is_read_back_as_youre(self):
        self.assertEqual(speech.as_she_says_it("i'm allergic to peanuts"), "you're allergic to peanuts")
        self.assertEqual(speech.as_she_says_it("I've got a dog"), "you've got a dog")
