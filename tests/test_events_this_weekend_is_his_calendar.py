""""What events are there this weekend" went to a model (2026-10-11); it is his calendar, like
"any events this weekend"."""

import unittest

from aletheia import quick


class EventsThisWeekendIsHisCalendar(unittest.TestCase):
    def test_the_ways_he_asks(self):
        for said in ("what events are there this weekend", "what events are this weekend",
                     "events this weekend", "what plans do I have tonight", "my plans for tomorrow"):
            found = quick.match(said)
            self.assertIsNotNone(found, said)
            self.assertEqual(found[0], "agenda", said)

    def test_finding_events_is_still_a_look(self):
        self.assertIsNone(quick.match("find me free events this weekend"))


if __name__ == "__main__":
    unittest.main()
