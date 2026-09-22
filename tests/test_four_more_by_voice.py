"""Four sentences from the personal-facts sweep with every frontier off
(2026-09-22): one set a reminder on the wrong day, one went to the file
finder, two waited two minutes on her own model for a name on file and a
key on the keyboard."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import music, voice


class ARemindersDayIsReadCase(unittest.TestCase):
    def test_on_sunday_at_six_is_sunday_evening(self):
        out = voice.interpret("thea remind me to call mom on sunday at 6")
        self.assertEqual(out["command"]["kind"], "remind_at")
        when = dt.datetime.fromisoformat(out["command"]["at"])
        self.assertEqual(when.strftime("%A"), "Sunday")
        self.assertEqual((when.hour, when.minute), (18, 0))
        self.assertEqual(out["command"]["text"], "call mom")

    def test_the_day_may_come_first_and_the_time_may_be_missing(self):
        out = voice.interpret("thea remind me tomorrow to take the bins out")
        self.assertEqual(out["command"]["kind"], "remind_at")
        when = dt.datetime.fromisoformat(out["command"]["at"])
        self.assertEqual(when.date(), dt.date.today() + dt.timedelta(days=1))
        self.assertEqual(out["command"]["text"], "take the bins out")
        out = voice.interpret("thea remind me at 9 on friday to send the invoice")
        self.assertEqual(dt.datetime.fromisoformat(out["command"]["at"]).strftime("%A"), "Friday")

    def test_next_friday_is_still_asked_about(self):
        out = voice.interpret("thea remind me next friday to send the invoice")
        self.assertNotEqual(out["command"].get("kind") if out.get("command") else None, "remind_at")


class HisFactsAreHisCase(unittest.TestCase):
    def test_where_do_i_live_is_his_city_not_a_file(self):
        with mock.patch("aletheia.memory.recall", return_value=None), \
             mock.patch("aletheia.profile.known", return_value={"city": "Hartford", "state": "SD"}):
            out = voice.interpret("thea where do I live")
        self.assertIsNone(out["command"])
        self.assertIn("Hartford, SD", out["say"])
        with mock.patch("aletheia.memory.recall", return_value=None), \
             mock.patch("aletheia.profile.known", return_value={}):
            out = voice.interpret("thea what's my address")
        self.assertIn("don't have your address", out["say"])
        self.assertTrue(voice._not_a_file("do i live"))

    def test_spell_my_name_is_letters_from_his_profile(self):
        with mock.patch("aletheia.profile.known", return_value={"first_name": "Caleb", "last_name": "Schulte"}):
            out = voice.interpret("thea spell my last name")
            self.assertEqual(out["say"], "Schulte: S-C-H-U-L-T-E.")
            out = voice.interpret("thea spell my name")
            self.assertIn("C-A-L-E-B", out["say"])
        with mock.patch("aletheia.profile.known", return_value={}):
            self.assertIn("don't have your name", voice.interpret("thea spell my first name")["say"])


class TheVolumeIsAKeyCase(unittest.TestCase):
    def test_the_words_reach_the_keys(self):
        for sentence, action in (("thea turn the volume down", "volume_down"), ("thea louder", "volume_up"),
                                 ("thea turn it up a bit", "volume_up"), ("thea mute", "mute"),
                                 ("thea quieter", "volume_down")):
            with self.subTest(sentence=sentence):
                out = voice.interpret(sentence)
                self.assertEqual(out["command"], {"kind": "music", "action": action})
                self.assertIn(action, music.KEYS)

    def test_transport_is_untouched(self):
        self.assertEqual(voice.interpret("thea skip this song")["command"]["action"], "next")


if __name__ == "__main__":
    unittest.main()
