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


class HisComputerAndHisWeek(unittest.TestCase):
    def test_the_sentences_reach_their_readers(self):
        for said in ("is my computer okay", "how's my computer doing", "check on my computer"):
            self.assertEqual(quick.match(said)[0], "computer_ok", said)
        for said in ("how was my week", "what did you do this week", "recap my week", "what happened this week"):
            self.assertEqual(quick.match(said)[0], "week", said)

    def test_a_week_lists_what_was_done(self):
        from unittest import mock
        rows = [{"what": f"Did thing {n}"} for n in range(5)]
        with mock.patch.object(quick, "_on_day", side_effect=lambda back: rows if back == 0 else []), \
                mock.patch.object(quick, "_tasks_done", return_value="2 tasks done this week: a and b."):
            said = quick._week()
        self.assertTrue(said.startswith("2 tasks done this week"))
        self.assertIn("What I did this week: Did thing 2", said)
        self.assertIn("2 other things", said)

    def test_a_computer_with_a_full_drive_says_so_first(self):
        from unittest import mock
        from aletheia import machine
        with mock.patch.object(machine, "memory", return_value={"total": 16 * 1024 ** 3, "available": 8 * 1024 ** 3}), \
                mock.patch.object(machine, "disk", return_value={"total": 500 * 1024 ** 3, "free": 2 * 1024 ** 3}):
            said = quick._computer_ok()
        self.assertTrue(said.startswith("One thing: the drive is nearly full"), said)


class HisZipSetAsAnOrder(unittest.TestCase):
    def test_set_my_zip_to(self):
        self.assertEqual(voice._interpret("set my zip to 57104")["command"],
                         {"kind": "remember", "domain": "identity", "key": "postal_code", "value": "57104"})
