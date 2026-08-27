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


if __name__ == "__main__":
    unittest.main()
