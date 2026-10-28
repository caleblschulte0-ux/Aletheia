""""I have a doctor's appointment on november 12 at 2:30", then "move it to
friday" went to the planner (2026-10-28), though "move the doctor's
appointment to friday" moved it. "It" after a hold is the hold, by its title."""
import unittest
from unittest import mock

from aletheia import voice

HOLD = {"kind": "calendar_hold", "title": "doctor's appointment", "start": "2026-11-12T20:30:00+00:00"}


class MoveTheHoldToADay(unittest.TestCase):
    def said(self, sentence, held=HOLD):
        seen = []
        real = voice._interpret

        def interpret(text, *a, **k):
            seen.append(text)
            if text.startswith("move doctor's appointment to "):
                return {"command": {"kind": "calendar_hold", "title": "doctor's appointment", "start": "MOVED"}, "say": None}
            return real(text, *a, **k)
        with mock.patch.object(voice, "_recent_ask_of", lambda kind, needs, turns=4: held if kind == "calendar_hold" else {}), \
                mock.patch.object(voice, "_hold_as_it_is_now", lambda found: found), \
                mock.patch.object(voice, "_interpret", interpret):
            return real(sentence), seen

    def test_a_day_is_the_hold_by_its_title(self):
        for sentence, when in (("move it to friday", "friday"), ("move it to friday at 3", "friday at 3"),
                               ("make it friday", "friday"), ("push it to tomorrow", "tomorrow"),
                               ("move it to november 13", "november 13")):
            got, seen = self.said(sentence)
            self.assertEqual(got["command"]["start"], "MOVED", sentence)
            self.assertIn(f"move doctor's appointment to {when}", seen, sentence)

    def test_with_no_hold_just_made_it_is_not_reread(self):
        got, seen = self.said("move it to friday", held={})
        self.assertFalse(any(s.startswith("move doctor's") for s in seen))


if __name__ == "__main__":
    unittest.main()
