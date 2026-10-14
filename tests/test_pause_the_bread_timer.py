""""Pause the bread timer" went to the planner (2026-10-14); "pause the
timer" was already answered honestly. A named one gets the same answer."""
import unittest

from aletheia import voice


class PauseANamedTimer(unittest.TestCase):
    def test_named(self):
        for said in ("pause the bread timer", "hold the pasta timer", "pause my egg timer"):
            out = voice._interpret(said)
            self.assertIsNone(out["command"], said)
            self.assertTrue(out["say"].startswith("I can't pause a timer"), said)


if __name__ == "__main__":
    unittest.main()
