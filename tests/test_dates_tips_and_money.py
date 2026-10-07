"""Weeks until a day, a tip, his birthday, money abroad, and the off switch.

2026-10-07, every model off: "how many weeks until christmas", "what's a
20% tip on 45", "how many days until my birthday", "how much is 50 euros in
dollars" and "how do I turn you off" all went to a model or the planner.
"""
import unittest
from unittest import mock

from aletheia import fx, memory, quick, voice


class WeeksAndTips(unittest.TestCase):
    def test_weeks_until(self):
        self.assertRegex(quick.answer("how many weeks until christmas"), r"^(\d+ weeks?( and \d+ days?)?|\d+ days?) - Friday 25 December\.$")

    def test_a_tip(self):
        self.assertEqual(quick.answer("what's a 20% tip on 45"), "$9.00, so $54.00 in all.")
        self.assertEqual(quick.answer("tip on 80"), "On $80.00: 15% is $12.00, 18% is $14.40, and 20% is $16.00.")


class HisBirthday(unittest.TestCase):
    def test_said_is_remembered_not_a_form_field(self):
        got = voice.interpret("my birthday is march 3")["command"]
        self.assertEqual((got["kind"], got["key"], got["value"]), ("remember", "birthday", "march 3"))

    def test_days_until_it(self):
        with mock.patch.object(memory, "recall", return_value="march 3"):
            self.assertRegex(quick.answer("how many days until my birthday"), r"March\.$")
        with mock.patch.object(memory, "recall", return_value=None):
            self.assertIn("my birthday is", quick.answer("how many days until my birthday"))


class Money(unittest.TestCase):
    def test_at_the_published_rate(self):
        with mock.patch.object(fx, "rate", return_value=(1.0912, "2026-10-06")):
            said = quick.answer("how much is 50 euros in dollars")
        self.assertTrue(said.startswith("50 euros is about 54.56 dollars"), said)
        self.assertIn("European Central Bank", said)

    def test_no_service_is_no_number(self):
        with mock.patch.object(fx, "_cache_path", side_effect=OSError), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            said = quick.answer("how much is 50 euros in dollars")
        self.assertIn("won't guess", said)
        self.assertNotRegex(said, r"\d+\.\d\d")

    def test_weight_is_still_weight(self):
        self.assertEqual(quick.match("how many pounds in 5 kg")[0], "math")


class TheOffSwitch(unittest.TestCase):
    def test_every_word_it_names_works(self):
        said = quick.answer("how do i turn you off")
        self.assertIn('"stop"', said)
        self.assertEqual(voice.interpret("stop")["command"]["kind"], "halt")
        self.assertEqual(voice.interpret("announcements off")["command"]["kind"], "announce_set")
        self.assertEqual(voice.interpret("turn off the microphone")["command"]["kind"], "mic_off")


if __name__ == "__main__":
    unittest.main()
