"""Stops are published as a system and the buttons the page offered, in a fixed vocabulary."""
import datetime as dt
import unittest

from aletheia import browser_mission as bm
from aletheia import hunt_funnel


class StopShapes(unittest.TestCase):
    def test_words_outside_the_vocabulary_never_appear(self):
        said = hunt_funnel.button_words(["Apply to Stripe", "Save job", "Interested in Acme Corp?"])
        self.assertNotIn("stripe", said.casefold())
        self.assertNotIn("acme", said.casefold())
        self.assertIn("apply", said)

    def test_a_stop_is_counted_by_system_and_buttons(self):
        now = dt.datetime(2026, 10, 11, tzinfo=dt.timezone.utc)
        mission = {"state": bm.LEFT, "left_at": "2026-10-10T12:00:00Z", "id": "bm-apply-for-this-job-x",
                   "boundary": {"kind": "NO_WAY_FORWARD", "url": "https://jobs.example.com/p/1",
                                "page_state": "content", "dead_end": "no_apply",
                                "buttons": ["Learn more", "Join Acme"]}}
        shapes = hunt_funnel.stop_shapes([mission], now=now)
        self.assertEqual(list(shapes.values()), [1])
        key = next(iter(shapes))
        self.assertTrue(key.startswith("employer_site: no_apply: "))
        self.assertNotIn("acme", key.casefold())
        self.assertNotIn("example", key.casefold())


if __name__ == "__main__":
    unittest.main()
