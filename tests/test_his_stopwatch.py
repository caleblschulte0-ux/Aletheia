"""His stopwatch, which counts up until he says stop.

2026-10-07: "start a stopwatch" went to the planner. A timer counts down to
a reminder; this is the other thing, one small record in private state.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, quick, stopwatch, voice

T0 = dt.datetime(2026, 10, 7, 12, 0, 0, tzinfo=dt.timezone.utc)


class TheStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.object(stopwatch, "_path", return_value=Path(self.dir.name) / "stopwatch.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_start_read_stop_reset(self):
        self.assertEqual(stopwatch.act("start", now=T0), "Stopwatch started.")
        self.assertIn("already running - 5 seconds", stopwatch.act("start", now=T0 + dt.timedelta(seconds=5)))
        self.assertEqual(stopwatch.spoken(now=T0 + dt.timedelta(minutes=1, seconds=4)),
                         "Your stopwatch is at 1 minute and 4 seconds, and still running.")
        self.assertEqual(stopwatch.act("stop", now=T0 + dt.timedelta(hours=1, minutes=2, seconds=3)),
                         "Stopped at 1 hour, 2 minutes and 3 seconds.")
        # Stopped is stopped: the reading does not keep counting.
        self.assertEqual(stopwatch.spoken(now=T0 + dt.timedelta(hours=5)),
                         "Your stopwatch stopped at 1 hour, 2 minutes and 3 seconds.")
        self.assertIn("reset", stopwatch.act("reset", now=T0 + dt.timedelta(hours=5)))
        self.assertIn("no stopwatch running", stopwatch.spoken())

    def test_nothing_to_stop_says_so(self):
        self.assertIn("no stopwatch running", stopwatch.act("stop", now=T0))
        self.assertIn("no stopwatch to reset", stopwatch.act("reset", now=T0))

    def test_through_the_command_door(self):
        self.assertEqual(intercom.execute_command({"kind": "stopwatch", "action": "start"}, {}), "Stopwatch started.")
        self.assertIn("still running", intercom.execute_command({"kind": "stopwatch_read"}, {}))
        self.assertIn("still running", quick.answer("how long has the stopwatch been running"))


class TheWaysHeSaysIt(unittest.TestCase):
    def test_start_stop_reset(self):
        for said, action in (("start a stopwatch", "start"), ("stop the stopwatch", "stop"),
                             ("reset my stopwatch", "reset")):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "stopwatch", "action": action})

    def test_stop_alone_is_still_the_halt(self):
        self.assertEqual(voice._interpret("stop")["command"]["kind"], "halt")

    def test_a_bad_action_is_refused_by_the_grammar(self):
        self.assertTrue(intercom.validate_kind_args({"kind": "stopwatch", "action": "explode"}, {}))


if __name__ == "__main__":
    unittest.main()
