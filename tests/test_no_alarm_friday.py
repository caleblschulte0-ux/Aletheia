""""Turn off my alarm for Friday" turned the weekday alarm off for good, and
"no alarm Friday", "don't wake me up tomorrow" and "I'm sleeping in on
Saturday" went to the planner (2026-10-23). Each is that day's alarm, once.
"""
import unittest

from aletheia import voice


class NoAlarmFriday(unittest.TestCase):
    def _cmd(self, sentence):
        return voice.interpret(sentence).get("command") or {}

    def test_a_named_day_is_once(self):
        for sentence, day in (("turn off my alarm for friday", "friday"),
                              ("cancel my alarm for saturday", "saturday"),
                              ("turn off my alarm for tomorrow", "tomorrow"),
                              ("no alarm friday", "friday"),
                              ("don't wake me up tomorrow", "tomorrow"),
                              ("i'm sleeping in on saturday", "saturday"),
                              ("i don't need an alarm tomorrow", "tomorrow")):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._cmd(sentence), {"kind": "reminder_off", "which": "wake up", "once": day})

    def test_no_day_is_still_for_good(self):
        self.assertEqual(self._cmd("cancel my alarm"), {"kind": "reminder_off", "which": "wake up"})


if __name__ == "__main__":
    unittest.main()
