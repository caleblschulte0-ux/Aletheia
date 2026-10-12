"""Talked to her, 2026-10-12, every model off: "how many applications this week" (no verb) and
"how many have you applied to this week" went to a model while "how many jobs did you apply to
this week" was counted from the records; and "what's my next step on the move" went to a model
while "what's next on the move plan" read the mission's own waits."""

import unittest

from aletheia import quick
from tests import test_his_mission_rehearsed as rehearsed


class BareCountsAreCounted(unittest.TestCase):

    def test_a_count_with_no_verb_is_the_count(self):
        self.assertEqual(quick.status_of("how many applications this week"), ("count_window", "this week"))
        self.assertEqual(quick.status_of("how many apps sent yesterday"), ("count_window", "yesterday"))
        self.assertEqual(quick.status_of("how many applications today"), ("count", "the job hunt"))
        self.assertEqual(quick.status_of("how many have you applied to this week"), ("count_window", "this week"))


class TheNextStepOnTheMissionIsItsWaits(rehearsed.HisMissionRunsWithoutHim):

    def test_next_step_names_the_mission(self):
        from aletheia import voice
        rehearsed.pg.add_words(self.pid, "also start planning a move somewhere warm", via="operator-voice",
                               now=rehearsed.NOW)
        for asked in ("what's my next step on the move", "what's the next thing for the move plan"):
            got = voice._interpret(asked)
            self.assertEqual(got["command"], {"kind": "missions", "about": "waiting", "which": self.pid}, asked)


if __name__ == "__main__":
    unittest.main()
