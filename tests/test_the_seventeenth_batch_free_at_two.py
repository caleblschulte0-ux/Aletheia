"""Seventeenth sandbox batch, 2026-10-05.

    > am I free at 2                   [6.0s] a model, then - once it reached
                                       the calendar - the whole day's free
                                       stretches: true, and not the question
    > what did you do while I was out  "Approved: Pencil in a tentative hold
                                       ...; calendar:: pencilled in Dentist
                                       (tentative, in my own calendar only);
                                       Pencil in a tentative hold ..." - one
                                       hold, three lines, one of them with
                                       the hold's id stripped and the colons
                                       left behind
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar as cal, intercom, recollection, voice

TOMORROW = (dt.date.today() + dt.timedelta(days=1)).isoformat()
NOW = dt.datetime.now(dt.timezone.utc).isoformat()
DENTIST = {"version": 1, "id": "e1", "title": "Dentist", "status": "TENTATIVE",
           "start": f"{TOMORROW}T10:00:00-05:00", "end": f"{TOMORROW}T11:00:00-05:00",
           "created_at": NOW, "updated_at": NOW}


class TheHourTravels(unittest.TestCase):
    def test_a_time_with_no_day_is_today_and_a_bare_hour_is_the_afternoon(self):
        out = voice.interpret("thea am I free at 2")["command"]
        self.assertEqual(out, {"kind": "free_time", "day": dt.date.today().isoformat(), "at": "14:00"})

    def test_the_day_may_come_before_or_after_the_hour(self):
        for sentence in ("am I free tomorrow at 10 am", "am I free at 10 tomorrow"):
            with self.subTest(sentence=sentence):
                self.assertEqual(voice.interpret(sentence)["command"],
                                 {"kind": "free_time", "day": TOMORROW, "at": "10:00"})

    def test_a_part_of_the_day_still_works_and_next_friday_still_asks(self):
        self.assertEqual(voice.interpret("am I free tomorrow afternoon")["command"],
                         {"kind": "free_time", "day": TOMORROW, "part": "afternoon"})
        self.assertIsNone(voice.interpret("am I free next friday at 2")["command"])
        self.assertIn("at", intercom.KIND_ARGS["free_time"][1])


class TheAnswerIsYesOrNo(unittest.TestCase):
    def test_free_says_yes_and_busy_says_what_is_there(self):
        cal.validate(DENTIST)
        with mock.patch("aletheia.calendar.all_events", return_value=[DENTIST]):
            free = intercom.free_time_answer({"kind": "free_time", "day": TOMORROW, "at": "14:00"})
            busy = intercom.free_time_answer({"kind": "free_time", "day": TOMORROW, "at": "10:30"})
        self.assertTrue(free.startswith("Yes, you're free "), free)
        self.assertIn("2 pm", free)
        self.assertTrue(busy.startswith("No. "), busy)
        self.assertIn("Dentist from 10 am to 11 am", busy)

    def test_a_calendar_she_cannot_read_is_not_a_free_one(self):
        with mock.patch("aletheia.calendar.all_events", return_value=[{"id": "broken"}]):
            said = intercom.free_time_answer({"kind": "free_time", "day": TOMORROW, "at": "10:30"})
        self.assertTrue(said.startswith("I couldn't read your calendar"), said)
        self.assertNotIn("Yes", said)


class OneHoldIsOneAct(unittest.TestCase):
    def test_the_approval_and_the_calendar_speak_and_the_planner_does_not_repeat_them(self):
        summary = "Pencil in a tentative hold on your calendar tomorrow at 10 for the dentist"
        rows = [{"ts": NOW, "kind": "decision", "actor": "operator-via-intercom",
                 "subject": "approval:intent-1", "text": "Approved: " + summary},
                {"ts": NOW, "kind": "action", "actor": "aletheia-calendar-reasoning",
                 "subject": "calendar:hold-8cf464e74b3af2",
                 "text": "pencilled in Dentist (tentative, in my own calendar only)"},
                {"ts": NOW, "kind": "plan", "actor": "aletheia-planner", "subject": "planner",
                 "text": "Did it: " + summary}]
        with mock.patch("aletheia.recollection._read_journal", return_value=(rows, True)):
            said = [r["what"] for r in recollection.day()]
        self.assertEqual(said, ["Approved: " + summary,
                                "Pencilled in Dentist (tentative, in my own calendar only)"])


if __name__ == "__main__":
    unittest.main()
