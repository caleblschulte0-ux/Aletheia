""""I parked on level 3", "I moved the car to level 5", "forget where I
parked" (2026-10-28): level 5 went, and "where did I park" then said level
3. Every note of where the car is says the same thing about it, so they all
go. And a car moved "to level 5" is ON level 5."""
import unittest
from unittest import mock

from aletheia import intercom, journal, quick, voice


class ForgetWhereIParked(unittest.TestCase):
    def test_every_spot_goes(self):
        rows = [{"text": "I parked on level 5"}, {"text": "my doctor is Dr. Kim"}, {"text": "I parked on level 3"}]
        with mock.patch.object(quick, "_notes", return_value=rows), \
                mock.patch.object(journal, "append") as wrote:
            self.assertEqual(intercom._forget_older_versions("I parked on level 5"), 2)
        self.assertEqual([c.args[2] for c in wrote.call_args_list], ["I parked on level 5", "I parked on level 3"])

    def test_a_moved_car_is_on_the_level(self):
        self.assertEqual(voice.interpret("I moved the car to level 5")["command"]["text"], "I parked on level 5")
        self.assertEqual(voice.interpret("I moved the car to the garage")["command"]["text"], "I parked in the garage")


if __name__ == "__main__":
    unittest.main()
