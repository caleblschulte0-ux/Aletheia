"""The watchdog that finds her running says so once an hour, not every
five minutes (869 "another Aletheia is already serving" lines by
2026-09-24, 288 a day, for a probe that found her fine)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from aletheia import supervisor


class OnceAnHour(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": tmp.name})
        env.start(); self.addCleanup(env.stop)

    def test_the_first_probe_is_news_and_the_next_fifty_nine_minutes_are_not(self):
        import time
        base = time.time() + 100_000.0          # past any stamp another test left
        self.assertTrue(supervisor._watchdog_probe_is_news(now=base))
        self.assertFalse(supervisor._watchdog_probe_is_news(now=base + 300))
        self.assertFalse(supervisor._watchdog_probe_is_news(now=base + 3500))
        self.assertTrue(supervisor._watchdog_probe_is_news(now=base + 3700))

    def test_a_probe_that_finds_her_running_exits_and_journals_only_when_it_is_news(self):
        lines = []
        with mock.patch.object(supervisor, "core_alive", return_value=True), \
                mock.patch.object(supervisor, "_journal", side_effect=lambda *a: lines.append(a)), \
                mock.patch("builtins.print"):
            self.assertEqual(supervisor.run_forever(), 0)
            self.assertEqual(supervisor.run_forever(), 0)
            self.assertEqual(supervisor.run_forever(), 0)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("already serving", lines[0][2])


if __name__ == "__main__":
    unittest.main()
