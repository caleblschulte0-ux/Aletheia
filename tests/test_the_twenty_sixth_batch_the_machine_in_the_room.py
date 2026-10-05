"""Twenty-sixth sandbox batch, 2026-10-05: the machine, from the room.

    > turn up the volume             [4.7s] the planner, and an approval
    > how much battery do I have     [5.0s] a model
    > what's my screen resolution    [6.0s] a model
    > how fast is the internet       [4.5s] a model
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class TheRoom(unittest.TestCase):
    def test_turn_up_the_volume_is_the_same_key(self):
        self.assertEqual(voice.interpret("turn up the volume")["command"], {"kind": "music", "action": "volume_up"})
        self.assertEqual(voice.interpret("turn down the sound a bit")["command"], {"kind": "music", "action": "volume_down"})

    def test_battery_is_a_reading_or_an_honest_none(self):
        with mock.patch("aletheia.machine.battery", return_value={"percent": 62, "plugged": False}):
            self.assertEqual(quick.answer("how much battery do i have"), "62 percent, on battery.")
        with mock.patch("aletheia.machine.battery", return_value=None):
            self.assertTrue(quick.answer("am i plugged in").startswith("I have no battery reading"))

    def test_screen_size_and_speed(self):
        with mock.patch("aletheia.machine.screen_size", return_value=(2560, 1440)):
            self.assertEqual(quick.answer("what's my screen resolution"), "2560 by 1440 pixels.")
        with mock.patch("aletheia.machine.screen_size", return_value=None):
            self.assertIn("Windows PC", quick.answer("what resolution is my monitor"))
        with mock.patch("aletheia.machine.internet_reachable", return_value=False):
            said = quick.answer("how fast is the internet")
        self.assertTrue(said.startswith("I don't measure speed"), said)
        self.assertIn("can't reach the internet", said)


if __name__ == "__main__":
    unittest.main()
