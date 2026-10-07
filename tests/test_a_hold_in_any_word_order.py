"""The day and time may come before "my calendar" or after it."""
import unittest

from aletheia import voice


def held(said):
    c = (voice._interpret(said) or {}).get("command") or {}
    return c.get("kind"), c.get("title"), str(c.get("start", ""))[11:16]


class AHoldInAnyWordOrder(unittest.TestCase):
    def test_day_and_time_before_the_calendar(self):
        self.assertEqual(held("add lunch with dana friday at noon to my calendar"),
                         ("calendar_hold", "lunch with dana", "12:00"))

    def test_time_then_day(self):
        self.assertEqual(held("put dentist at 3 tomorrow on my calendar"),
                         ("calendar_hold", "dentist", "15:00"))

    def test_the_old_order_still_works(self):
        self.assertEqual(held("add dinner with sam on my calendar friday at 7"),
                         ("calendar_hold", "dinner with sam", "19:00"))

    def test_no_day_or_time_is_not_a_hold(self):
        self.assertNotEqual(held("add my trip to my calendar")[0], "calendar_hold")


if __name__ == "__main__":
    unittest.main()
