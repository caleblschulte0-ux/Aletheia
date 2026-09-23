"""From the 2026-09-23 night sweep with every frontier off: "order more
coffee" reached an approval (the money door's "order" needed "a/an/the/some");
"turn on do not disturb" waited 78 s on her own model to ask what he meant;
"find my keys" planned for a minute and came back "she does not know a
folder called on my computer"; "show me my calendar for next week" planned
for 73 s and died on a date string."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import intents, quick, voice, webtask


class TheMoneyDoorCase(unittest.TestCase):
    def test_ordering_more_of_something_is_an_order(self):
        for said in ("order more coffee", "order another case of water", "buy more paper towels", "get me another charger"):
            with self.subTest(said=said):
                self.assertTrue(webtask.would_spend(said), said)
                self.assertTrue(intents._asks_to_spend(said), said)
        for said in ("how much would more coffee cost", "what did I order last time?"):
            with self.subTest(said=said):
                self.assertFalse(intents._asks_to_spend(said), said)


class DoNotDisturbCase(unittest.TestCase):
    def test_it_is_her_notices_going_quiet(self):
        for said, minutes in (("thea turn on do not disturb", 60), ("thea don't disturb me for 2 hours", 120),
                              ("thea quiet for 30 minutes", 30), ("thea snooze your notifications", 60)):
            with self.subTest(said=said):
                cmd = voice.interpret(said)["command"]
                self.assertEqual(cmd["kind"], "notify_snooze")
                self.assertEqual(cmd["minutes"], minutes)


class ALostObjectCase(unittest.TestCase):
    def test_she_says_she_has_no_eyes_in_the_room(self):
        for said in ("thea find my keys", "thea where's my phone", "thea where did I put my wallet"):
            with self.subTest(said=said):
                out = voice.interpret(said)
                self.assertIsNone(out["command"])
                self.assertIn("no eyes in the room", out["say"])
        self.assertEqual(voice.interpret("thea find my resume")["command"]["kind"], "file_find")


class TheCalendarInMoreWordsCase(unittest.TestCase):
    def test_show_me_and_what_meetings_are_the_agenda(self):
        with mock.patch("aletheia.quick._agenda", return_value="Nothing on your calendar next week.") as agenda:
            self.assertEqual(quick.answer("show me my calendar for next week"), "Nothing on your calendar next week.")
            self.assertEqual(agenda.call_args[0][0], "next week")
            self.assertEqual(quick.answer("what meetings do I have tomorrow"), "Nothing on your calendar next week.")
            self.assertEqual(agenda.call_args[0][0], "tomorrow")


if __name__ == "__main__":
    unittest.main()
