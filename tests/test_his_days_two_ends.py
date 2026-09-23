"""From the 2026-09-23 night sweep: "good morning" answered "I'm here.
Nothing is waiting on you." - true, and not what a morning is for; "morning
thea" waited 91 s on her own model; "I'm leaving for work" and "going to
bed" were planned as steps ("I will let you know when you're ready to go")."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import quick


class GoodMorningCase(unittest.TestCase):
    def test_the_morning_is_the_night_then_the_day(self):
        with mock.patch("aletheia.quick._overnight", return_value="Overnight: 8 applications sent overnight: Datadog and Vanta."), \
             mock.patch("aletheia.quick._focus", return_value="First, 1 thing needs you - the first is Approve the Brex one."):
            for said in ("good morning", "morning thea", "Good morning, Thea"):
                with self.subTest(said=said):
                    out = quick.answer(said)
                    self.assertEqual(out, "Good morning. Overnight: 8 applications sent overnight: Datadog and Vanta. "
                                          "First, 1 thing needs you - the first is Approve the Brex one.")

    def test_a_quiet_night_and_a_clear_day_are_short(self):
        with mock.patch("aletheia.quick._overnight", return_value="A quiet night: nothing sent and nothing recorded since ten last night."), \
             mock.patch("aletheia.quick._focus", return_value="Nothing is waiting on you, nothing is due and your calendar is clear - the day is yours."):
            self.assertEqual(quick.answer("good morning"), "Good morning. A quiet night.")


class LeavingAndBedCase(unittest.TestCase):
    def test_leaving_is_the_farewell_not_a_plan(self):
        for said in ("I'm leaving for work", "heading out", "leaving now", "off to work"):
            with self.subTest(said=said):
                self.assertIn("keep at it while you're out", quick.answer(said))

    def test_bed_is_the_goodnight_not_a_plan(self):
        for said in ("going to bed", "I'm off to bed", "turning in"):
            with self.subTest(said=said):
                self.assertIn("keep going quietly", quick.answer(said))
        # "See you tomorrow" is a see-you first and a goodnight second.
        self.assertIn("keep at it", quick.answer("see you tomorrow"))


if __name__ == "__main__":
    unittest.main()
