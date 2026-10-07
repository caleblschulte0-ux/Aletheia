"""Questions about one moment, a note taken back, and the inbox counted.

    > am I busy at 3              -> the planner
    > what's on friday            -> the planner
    > delete that note            -> the planner, a turn after he made it
    > how many unread emails do I have -> the planner

And the first version of the moment answer said "Yes, you're free" to
"am I busy" - the yes has to answer HIS verb.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, quick, voice


def at(day, hour, minute=0):
    tz = localtime.operator_tz()
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz).isoformat()


class OneMoment(unittest.TestCase):
    def setUp(self):
        self.tz = localtime.operator_tz()
        self.tomorrow = dt.datetime.now(self.tz).date() + dt.timedelta(days=1)
        events = [{"title": "Dentist", "start": at(self.tomorrow, 14, 30),
                   "end": at(self.tomorrow, 15, 30), "status": "CONFIRMED"}]
        p = mock.patch.object(calendar, "all_events", return_value=events)
        p.start()
        self.addCleanup(p.stop)

    def test_the_shapes_reach_the_fast_lane(self):
        for said in ("am i busy at 3", "am i free tomorrow at 2:30", "do i have anything at 4",
                     "am i free friday", "am i busy tomorrow"):
            self.assertEqual(quick.match(said)[0], "free_at", said)
        self.assertEqual(quick.match("am i free tomorrow"), ("free", "tomorrow"))
        self.assertEqual(quick.match("what's on friday"), ("agenda", "friday"))

    def test_a_clash_is_named_and_the_yes_answers_his_verb(self):
        self.assertEqual(quick.answer("am i free tomorrow at 3"),
                         "No - you've got Dentist from 2:30 pm to 3:30 pm.")
        self.assertEqual(quick.answer("am i busy tomorrow at 3"),
                         "Yes - you've got Dentist from 2:30 pm to 3:30 pm.")

    def test_free_is_free_whichever_way_he_asks(self):
        self.assertEqual(quick.answer("am i free tomorrow at 5"), "Yes, you're free at 5 pm tomorrow.")
        self.assertEqual(quick.answer("am i busy tomorrow at 5"), "No, you're free at 5 pm tomorrow.")

    def test_a_bare_hour_is_never_the_middle_of_the_night(self):
        self.assertIn("3 pm", quick.answer("am i free at 3"))
        self.assertIn("3 am", quick.answer("am i free at 3 am"))


class ThatNote(unittest.TestCase):
    def test_the_newest_note_is_the_one_forgotten(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "the gate code is 4411"}]):
            self.assertEqual(voice.interpret("delete that note")["command"],
                             {"kind": "forget", "about": "the gate code is 4411"})

    def test_no_notes_says_so(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            out = voice.interpret("delete the last note")
            self.assertIsNone(out["command"])
            self.assertIn("no note", out["say"])


class TheInbox(unittest.TestCase):
    def test_counting_and_reading_are_the_inbox_check(self):
        for said in ("how many unread emails do I have", "read me my last email",
                     "any unread emails"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "email_check"}, said)


if __name__ == "__main__":
    unittest.main()
