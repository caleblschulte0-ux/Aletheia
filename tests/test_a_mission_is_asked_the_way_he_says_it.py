"""A mission is started and asked about in his own words (2026-10-11).

"new mission: get me in shape by summer" went to the planner, and "what
missions do I have" was answered by the notes reader - "I have nothing
about missions on file" - while the mission store was the thing he meant.
"""

import unittest

from aletheia import voice


class AMissionIsAskedTheWayHeSaysIt(unittest.TestCase):
    def test_new_mission_colon_starts_one(self):
        for said in ("new mission: get me in shape by summer", "a new mission to get me in shape by summer",
                     "start a new mission: get me in shape by summer"):
            got = voice._interpret(said) or {}
            self.assertEqual((got.get("command") or {}).get("kind"), "mission_new", said)
            self.assertEqual(got["command"]["objective"], "get me in shape by summer", said)

    def test_asking_about_missions_reaches_the_mission_store(self):
        for said in ("what missions do I have", "what are my missions?", "do I have any missions",
                     "list my missions", "show me my missions", "which missions are running"):
            got = voice._interpret(said) or {}
            self.assertEqual((got.get("command") or {}).get("kind"), "missions", said)

    def test_new_mission_status_is_not_a_mission_called_status(self):
        got = voice._interpret("new mission status") or {}
        self.assertNotEqual((got.get("command") or {}).get("kind"), "mission_new")

    def test_cancelling_a_mission_that_is_not_there_is_never_a_subscription(self):
        from unittest import mock
        from aletheia import programs
        with mock.patch.object(programs, "named", return_value=None), \
                mock.patch.object(programs, "find", return_value=None):
            for said in ("cancel my mission", "stop the mission", "drop my big mission"):
                got = voice._interpret(said) or {}
                self.assertIsNone(got.get("command"), said)
                self.assertIn("mission", got.get("say") or "", said)


if __name__ == "__main__":
    unittest.main()
