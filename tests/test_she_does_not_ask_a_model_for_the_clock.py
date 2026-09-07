"""Two questions she was paying a round trip for, and one she misheard.

  "what time is it"            8.0s, through a model, for a clock she holds
  "how long until my meeting"  -> "I don't know where until my meeting is"

The second is the worse one. `how long (.+)` was read as a travel
question, so every "how long" sentence in the language became a
destination — and the deterministic layer answering a DIFFERENT question
is the failure he cannot detect, because the answer sounds like an
answer.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import places, quick, voice


class TheClockIsNotAModelQuestion(unittest.TestCase):
    def test_the_time_comes_from_the_clock(self):
        for said in ("what time is it", "what's the time", "time"):
            answer = quick.answer(said)
            self.assertTrue(answer, said)
            self.assertRegex(answer, r"\d{1,2}(:\d{2})? [ap]m")

    def test_the_day_question_leads_with_the_day(self):
        for said in ("what day is it", "what's the date", "what's today"):
            answer = quick.answer(said)
            self.assertTrue(answer, said)
            self.assertNotRegex(answer.split(",")[0], r"\d{1,2}:\d{2}")

    def test_the_date_is_said_the_way_a_person_says_it(self):
        for day, said in ((1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"),
                          (11, "11th"), (12, "12th"), (13, "13th"),
                          (21, "21st"), (22, "22nd"), (30, "30th")):
            self.assertEqual(quick._ordinal(day), said)

    def test_it_is_his_clock_and_not_the_machines(self):
        # A time in the PROCESS's zone is how a reminder set for 03:00 was
        # read back as "tomorrow at 8 am" (CLAUDE.md).
        import zoneinfo
        tokyo = zoneinfo.ZoneInfo("Asia/Tokyo")
        with mock.patch("aletheia.localtime.operator_tz", return_value=tokyo):
            here = dt.datetime.now(tokyo)
            answer = quick.answer("what day is it")
        self.assertIn(here.strftime("%A"), answer)

    def test_it_still_declines_what_it_cannot_be_sure_of(self):
        # The whole safety argument for this module: it may only remove
        # latency, never an answer.
        self.assertIsNone(quick.answer("what time is my flight"))
        self.assertIsNone(quick.answer("what time should I leave"))


class HowLongIsNotAlwaysAJourney(unittest.TestCase):
    def test_a_question_about_time_is_not_a_destination(self):
        for said in ("how long until my meeting", "how long have I been working",
                     "how long is a marathon"):
            got = voice.interpret(said)
            self.assertNotEqual((got.get("command") or {}).get("kind"),
                                "travel_time", said)

    def test_an_explicit_journey_is_still_one(self):
        for said in ("how long to get to the airport",
                     "how long does it take to get to work",
                     "how long is the drive to the airport"):
            got = voice.interpret(said)
            self.assertEqual(got["command"]["kind"], "travel_time", said)

    def test_an_explicit_journey_works_for_a_place_she_has_never_heard_of(self):
        # So she can ask for the address, rather than sending it to a
        # model that will invent a duration.
        got = voice.interpret("how long to get to the moon")
        self.assertEqual(got["command"], {"kind": "travel_time", "place": "the moon"})

    def test_the_bare_form_is_travel_only_for_a_place_she_knows(self):
        with mock.patch.object(places, "resolve", return_value={"id": "airport"}):
            got = voice.interpret("how long to the airport")
        self.assertEqual(got["command"]["kind"], "travel_time")
        with mock.patch.object(places, "resolve", side_effect=KeyError("no")):
            got = voice.interpret("how long to finish the report")
        self.assertNotEqual(got["command"]["kind"], "travel_time")

    def test_a_broken_place_store_never_breaks_the_sentence(self):
        with mock.patch.object(places, "resolve", side_effect=OSError("gone")):
            self.assertFalse(voice._known_place("the airport"))


if __name__ == "__main__":
    unittest.main()
