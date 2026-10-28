"""Days he is away, said the way he says them, and when he works.

2026-10-28, talking to her with the models off:

    > I have a work trip november 3 to 5          (to the planner)
    > I'm going to denver november 3 to 5         (to the planner)
    > when do I work      after "I work 9 to 5 monday through friday"
      I can't think just now ...

A trip is whole days, so a clash with one is never "at 12 am".
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick, voice

NOW = dt.datetime.now(localtime.operator_tz()).isoformat()


class AwayFor(unittest.TestCase):
    def test_he_says_he_has_one(self):
        for said, title in (("i have a work trip november 3 to 5", "work trip"),
                            ("i've got a conference from november 3 to november 5", "conference"),
                            ("i'm on vacation november 3 to 5", "vacation"),
                            ("i'm going to denver november 3 to 5", "Trip to Denver")):
            got = voice.interpret(said)["command"]
            self.assertEqual((got["kind"], got["title"], got["anyway"]), ("calendar_hold", title, True), said)
            start, end = dt.datetime.fromisoformat(got["start"]), dt.datetime.fromisoformat(got["end"])
            self.assertEqual((start.month, start.day, start.hour), (11, 3, 0), said)
            self.assertEqual((end - start).days, 3, said)

    def test_a_question_is_not_a_trip(self):
        got = voice.interpret("am i going to denver november 3 to 5")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "calendar_hold")

    def test_a_clash_with_whole_days_names_the_days(self):
        tz = localtime.operator_tz()
        trip = {"title": "work trip", "kind": "overlap",
                "start": dt.datetime(2026, 11, 3, tzinfo=tz).isoformat(),
                "end": dt.datetime(2026, 11, 6, tzinfo=tz).isoformat()}
        said = intercom._clash_words([trip])
        self.assertIn("work trip from Tuesday 3 November to Thursday 5 November", said)
        self.assertNotIn("12 am", said)
        one = dict(trip, end=dt.datetime(2026, 11, 4, tzinfo=tz).isoformat())
        self.assertIn("work trip all day Tuesday 3 November", intercom._clash_words([one]))


class WhenHeWorks(unittest.TestCase):
    def test_the_note_answers_it(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "i work 9 to 5 monday through friday", "ts": NOW}]):
            for asked in ("when do i work", "what days do i work", "what are my work hours", "what's my work schedule"):
                self.assertEqual(quick.answer(asked), "You told me you work 9 to 5 Monday through Friday.", asked)

    def test_nothing_said_is_left_to_a_model(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "i like tea", "ts": NOW}]):
            self.assertIsNone(quick.answer("when do i work"))


if __name__ == "__main__":
    unittest.main()
