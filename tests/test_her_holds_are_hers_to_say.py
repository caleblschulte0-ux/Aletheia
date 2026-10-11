"""Her own holds: what she put on his calendar, and taking one off.

2026-10-11, once the mission began pencilling events in: "what did you put on my calendar" went
to a model that has never seen her holds, "take that hold off my calendar" went to the planner,
and the release, when it was reached, read its hold id out loud.
"""
import unittest
from unittest import mock

from aletheia import calendar_reasoning, intercom, quick, voice

WALK = {"id": "hold-1", "title": "Tails on the Trail", "start": "2026-10-24T14:00:00+00:00",
        "end": "2026-10-24T15:00:00+00:00", "status": "TENTATIVE", "source": "hold:mission"}
FAIR = {"id": "hold-2", "title": "Fall Job Fair", "start": "2026-10-15T23:00:00+00:00",
        "end": "2026-10-16T00:00:00+00:00", "status": "TENTATIVE", "source": "hold:mission"}


def mine(*holds):
    return mock.patch.object(voice, "_her_upcoming_holds", lambda: [(None, h) for h in holds])


class WhatSheHeld(unittest.TestCase):
    def test_her_holds_are_read_from_her_store(self):
        with mock.patch.object(calendar_reasoning, "upcoming_holds", lambda: [WALK, FAIR]):
            said = quick.answer("what did you put on my calendar")
        self.assertTrue(said.startswith("I've pencilled in Fall Job Fair"), said)
        self.assertIn("Tails on the Trail", said)

    def test_none_is_said_as_none(self):
        with mock.patch.object(calendar_reasoning, "upcoming_holds", lambda: []):
            self.assertIn("haven't pencilled anything in", quick.answer("did you put anything on my calendar"))

    def test_how_many_sign_ups_reads_her_ledger(self):
        self.assertEqual(quick.match("how many events did you sign me up for this week")[0], "signed_up")


class TakingOneOff(unittest.TestCase):
    def test_that_hold_is_the_only_one_there_is(self):
        with mine(WALK):
            got = voice._interpret("take that hold off my calendar")
        self.assertEqual(got["command"], {"kind": "hold_release", "title": WALK["title"], "start": WALK["start"]})

    def test_with_several_she_asks_which(self):
        with mine(FAIR, WALK):
            got = voice._interpret("take that hold off my calendar")
        self.assertIsNone(got["command"])
        self.assertIn(" or ", got["say"])

    def test_a_named_one_is_taken_off(self):
        with mine(FAIR, WALK), mock.patch.object(voice, "_one_of_her_holds", lambda w: (WALK, "")):
            got = voice._interpret("take the trail walk off my calendar")
        self.assertEqual(got["command"]["title"], WALK["title"])

    def test_the_release_says_what_it_took_off_and_no_id(self):
        with mock.patch("aletheia.calendar.load", lambda event_id: dict(WALK)), \
                mock.patch.object(calendar_reasoning, "release_hold", lambda *a, **k: {}):
            said = intercom.execute_command({"kind": "hold_release", "title": WALK["title"], "start": WALK["start"]},
                                             {"repos": {}}, quote="test")
        said = str(said)
        self.assertIn("Took Tails on the Trail", said)
        self.assertNotIn("hold-", said)


if __name__ == "__main__":
    unittest.main()
