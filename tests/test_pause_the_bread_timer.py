""""Pause the bread timer" went to the planner (2026-10-14); "pause the
timer" was already answered. A named one is answered the same way - paused
by name since 2026-10-28, and with none running, said so."""
import unittest
from unittest import mock

from aletheia import voice


class PauseANamedTimer(unittest.TestCase):
    def test_named(self):
        with mock.patch.object(voice, "_running_once", return_value=[]):
            for said in ("pause the bread timer", "hold the pasta timer", "pause my egg timer"):
                out = voice._interpret(said)
                self.assertIsNone(out["command"], said)
                self.assertEqual(out["say"], "There's no timer running to pause.", said)


if __name__ == "__main__":
    unittest.main()
