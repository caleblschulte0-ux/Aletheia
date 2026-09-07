"""Liveness: a heartbeat that cannot kill its own process, and downtime
that becomes a fact instead of a silence (the 2026-08-27 outage)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, liveness


class LivenessCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "heartbeat.json"
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              Path(self.tmp.name) / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)

    def test_beat_then_read_back(self):
        entry = liveness.beat(actor="core", port=8777, path=self.path)
        self.assertEqual(entry["actor"], "core")
        self.assertEqual(liveness.last(self.path)["port"], 8777)

    def test_no_heartbeat_is_none_not_zero(self):
        # "never beat" and "beat just now" must never be confused
        self.assertIsNone(liveness.age_seconds(path=self.path))
        self.assertFalse(liveness.alive(path=self.path))

    def test_age_and_staleness(self):
        liveness.beat(path=self.path)
        stamp = liveness.last(self.path)["ts"]
        self.assertLess(liveness.age_seconds(now=stamp, path=self.path), 1.0)
        self.assertTrue(liveness.alive(now=stamp, path=self.path))
        # six hours later — the real outage — is not alive
        from aletheia import stateio
        stateio.write_json_atomic(self.path, {"ts": "2026-08-27T12:42:05Z"})
        self.assertAlmostEqual(
            liveness.age_seconds(now="2026-08-27T18:42:05Z", path=self.path),
            6 * 3600, delta=1)
        self.assertFalse(liveness.alive(now="2026-08-27T18:42:05Z", path=self.path))

    def test_corrupt_heartbeat_is_no_heartbeat(self):
        self.path.write_text("{ this is not json", encoding="utf-8")
        self.assertIsNone(liveness.last(self.path))
        self.assertIsNone(liveness.age_seconds(path=self.path))

    def test_beat_never_raises_even_when_unwritable(self):
        # a heartbeat that can throw is a liability in the Core's hot loop
        bad = Path(self.tmp.name) / "no-such-dir" / "\0" / "heartbeat.json"
        liveness.beat(path=bad)  # must not raise

    def test_restart_is_not_an_outage(self):
        from aletheia import stateio
        stateio.write_json_atomic(self.path, {"ts": "2026-08-27T12:42:05Z"})
        gap = liveness.note_start(now="2026-08-27T12:42:11Z", path=self.path)
        self.assertIsNone(gap)  # 6s = a self-update relaunch, not an absence
        self.assertEqual(journal.entries(journal.JOURNAL_PATH), [])

    def test_outage_is_journaled_with_its_duration(self):
        from aletheia import stateio
        stateio.write_json_atomic(self.path, {"ts": "2026-08-27T12:42:05Z"})
        with mock.patch("aletheia.events.emit") as emit:
            gap = liveness.note_start(now="2026-08-27T18:42:05Z", path=self.path)
        self.assertAlmostEqual(gap, 6 * 3600, delta=1)
        rows = journal.entries(journal.JOURNAL_PATH)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "alert")
        self.assertIn("6.0h", rows[0]["text"])
        # and it reaches the bus, so watchers/proactive rules can act on it
        kind, subject, summary = emit.call_args.args
        self.assertEqual(kind, "core.outage_ended")
        self.assertEqual(emit.call_args.kwargs["attributes"]["downtime_seconds"],
                         21600.0)

    def test_note_start_leaves_a_fresh_heartbeat(self):
        liveness.note_start(path=self.path)
        self.assertTrue(liveness.alive(path=self.path))

    def test_first_ever_start_is_not_reported_as_an_outage(self):
        self.assertIsNone(liveness.note_start(path=self.path))
        self.assertEqual(journal.entries(journal.JOURNAL_PATH), [])


class HowLongHasSheBeenUpCase(unittest.TestCase):
    """She could say to the second how long she had been GONE and had no
    answer at all for how long she had been here — which is the first
    thing anybody asks a machine whose whole promise is being on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "heartbeat.json"
        liveness._STARTED_AT = None
        self.addCleanup(setattr, liveness, "_STARTED_AT", None)

    def test_a_heartbeat_with_no_start_stamp_is_not_a_guess(self):
        """Every heartbeat written before this existed. "I do not know" is
        the only honest answer, and None is how this module says it."""
        liveness.beat(path=self.path)
        self.assertIsNone(liveness.uptime_seconds(path=self.path))

    def test_note_start_records_it_and_beats_carry_it(self):
        liveness.note_start(path=self.path, now="2026-09-07T10:00:00Z")
        self.assertEqual(liveness.last(self.path)["started_at"],
                         "2026-09-07T10:00:00Z")
        liveness.beat(path=self.path)
        self.assertEqual(liveness.last(self.path)["started_at"],
                         "2026-09-07T10:00:00Z",
                         "a later beat must not lose the start stamp")

    def test_it_measures_from_the_start(self):
        liveness.note_start(path=self.path, now="2026-09-07T10:00:00Z")
        self.assertEqual(
            liveness.uptime_seconds(now="2026-09-07T10:02:30Z", path=self.path),
            150.0)

    def test_a_STALE_heartbeat_says_nothing_about_being_up(self):
        """A stamp from a process that has since died records when it
        started, not that it is still running. Reading uptime off a dead
        process would be the most confident possible lie about being on.

        Both sides of this comparison move together now. The first
        version froze the "long after" time and let `beat` stamp the real
        clock, so it passed or failed by the hour of the day it ran —
        CLAUDE.md's bomb with a date on it, built the same day I read the
        warning about it.
        """
        liveness.note_start(path=self.path, now="2026-09-07T10:00:00Z")
        long_after = "2026-09-07T18:00:00Z"
        self.assertFalse(liveness.alive(now=long_after, path=self.path))
        self.assertIsNone(liveness.uptime_seconds(now=long_after, path=self.path))

    def test_a_torn_stamp_is_not_a_crash(self):
        liveness.note_start(path=self.path, now="not a timestamp")
        self.assertIsNone(liveness.uptime_seconds(path=self.path))


class SaidOutLoudCase(unittest.TestCase):
    """`humanize` writes "3.2h", which is right on a wall and wrong in a
    room."""

    def test_it_says_it_the_way_a_person_would(self):
        for seconds, expected in ((45, "45 seconds"), (600, "10 minutes"),
                                  (3600, "an hour"), (7200, "2 hours"),
                                  (90000, "a day"), (200000, "2 days")):
            with self.subTest(seconds=seconds):
                self.assertEqual(liveness.spoken_duration(seconds), expected)

    def test_an_awkward_span_keeps_both_halves(self):
        self.assertEqual(liveness.spoken_duration(3900), "1 hour and 5 minutes")

    def test_nothing_it_says_is_an_abbreviation(self):
        """The whole reason this exists beside `humanize`."""
        for seconds in (45, 600, 3600, 3900, 7200, 90000, 200000):
            said = liveness.spoken_duration(seconds)
            for short in ("s", "m", "h", "d"):
                self.assertFalse(said.endswith(short) and said[-2:-1].isdigit(),
                                 said)

    def test_the_fast_lane_declines_when_she_does_not_know(self):
        from aletheia import quick
        with mock.patch("aletheia.liveness.uptime_seconds", return_value=None):
            self.assertIsNone(quick.answer("how long have you been up"))

    def test_the_fast_lane_says_it_when_she_does(self):
        from aletheia import quick
        with mock.patch("aletheia.liveness.uptime_seconds", return_value=7200):
            self.assertEqual(quick.answer("how long have you been up"),
                             "Up 2 hours.")



if __name__ == "__main__":
    unittest.main()
