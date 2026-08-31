"""What the wall shows, and how honest it is about its own age.

The wall rendered a fleet of six repositories — three of them empty stubs
— and none of the things that need him. Its only data source was a
six-hourly cloud cron, measured 10.5 hours stale while these were written.
"""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import presence, pulse

NOW = dt.datetime(2026, 8, 27, 20, 0, tzinfo=dt.timezone.utc)


class SnapshotCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "ALETHEIA_PRIVATE_STATE": str(Path(self.tmp.name) / "private")})
        env.start(); self.addCleanup(env.stop)

    def quiet(self, halted=None, **over):
        stubs = {"_approvals": [], "_notifications": [], "_meetings": [],
                 "_working": [], "_next_appointment": None}
        stubs.update(over)
        for name, value in stubs.items():
            p = mock.patch.object(presence, name, return_value=value)
            p.start(); self.addCleanup(p.stop)
        # halted is a parameter, not a hard-coded patch: patching it here
        # would silently win over a caller's own patch and hide the case
        # under test — which is exactly what it did.
        with mock.patch("aletheia.policy.halted", return_value=halted), \
             mock.patch("aletheia.liveness.age_seconds", return_value=3.0):
            return presence.snapshot(NOW)

    def test_a_quiet_house_says_so(self):
        self.assertEqual(self.quiet()["headline"], "All quiet")

    def test_decisions_come_first(self):
        snap = self.quiet(
            _approvals=[{"label": "the email to Dana"}, {"label": "the plan"}],
            _notifications=[{"title": "CI went red", "priority": "URGENT"}])
        # something urgent is on screen, but a decision he must make outranks it
        self.assertIn("2 decisions waiting", snap["headline"])
        self.assertIn("the email to Dana", snap["headline"])

    def test_halted_outranks_everything(self):
        snap = self.quiet(halted={"reason": "stop"},
                          _approvals=[{"label": "the email"}])
        self.assertIn("HALTED", snap["headline"])
        self.assertTrue(snap["halted"])

    def test_an_urgent_notice_is_the_headline_when_nothing_needs_deciding(self):
        snap = self.quiet(_notifications=[{"title": "CI went red", "priority": "URGENT"}])
        self.assertEqual(snap["headline"], "CI went red")

    def test_routine_notices_are_not_a_headline(self):
        snap = self.quiet(_notifications=[{"title": "pulse ran", "priority": "INFO"}])
        self.assertEqual(snap["headline"], "All quiet")

    def test_one_broken_source_does_not_blank_the_wall(self):
        def boom():
            raise RuntimeError("store unreadable")

        with mock.patch.object(presence, "_meetings", side_effect=boom):
            snap = self.quiet()
        self.assertEqual(snap["meetings"], [])
        self.assertIn("headline", snap)

    def test_the_snapshot_carries_its_own_age(self):
        self.assertEqual(self.quiet()["generated_at"], "2026-08-27T20:00:00Z")

    def test_duplicate_notification_titles_are_shown_once(self):
        from aletheia import notifications
        rows = [{"title": "Mail polling failed", "priority": "IMPORTANT",
                 "created_at": "x", "id": "a"},
                {"title": "Mail polling failed", "priority": "IMPORTANT",
                 "created_at": "y", "id": "b"}]
        with mock.patch.object(notifications, "all_notifications", return_value=rows):
            self.assertEqual(len(presence._notifications()), 1)

    def test_an_interrupted_intent_is_visible_as_needing_verification(self):
        from aletheia import errands, followups, intents
        with mock.patch.object(followups, "pending_count", return_value=0), \
             mock.patch.object(intents, "all_intents", side_effect=lambda state=None: (
                 [{"summary": "water the garden"}]
                 if state == intents.INTERRUPTED else [])), \
             mock.patch.object(errands, "all_errands", return_value=[]):
            working = presence._working()
        self.assertEqual(working, [{"what": "plan needs verification",
                                    "detail": "water the garden"}])


class PulseBlockCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "latest.json"
        p = mock.patch.object(pulse, "PULSE_DIR", Path(self.tmp.name))
        p.start(); self.addCleanup(p.stop)

    def test_the_fleet_stamp_is_never_refreshed_by_a_local_write(self):
        # the §107 rule: a fresh local read must not make six-hour-old
        # repository health render as current
        self.path.write_text(json.dumps(
            {"generated_at": "2026-08-27T09:56:10Z", "repos": {"a": {}}}),
            encoding="utf-8")
        out = pulse.write_local_block({"generated_at": "2026-08-27T20:00:00Z"},
                                      path=self.path)
        self.assertEqual(out["generated_at"], "2026-08-27T09:56:10Z")
        self.assertEqual(out["now"]["generated_at"], "2026-08-27T20:00:00Z")
        self.assertEqual(out["repos"], {"a": {}})

    def test_it_works_with_no_fleet_pulse_at_all(self):
        out = pulse.write_local_block({"headline": "All quiet"}, path=self.path)
        self.assertIsNone(out["generated_at"])
        self.assertEqual(out["now"]["headline"], "All quiet")

    def test_a_corrupt_pulse_is_replaced_not_propagated(self):
        self.path.write_text("{ not json", encoding="utf-8")
        out = pulse.write_local_block({"headline": "All quiet"}, path=self.path)
        self.assertEqual(out["now"]["headline"], "All quiet")

    def test_the_write_is_atomic_and_readable(self):
        pulse.write_local_block({"headline": "x"}, path=self.path)
        json.loads(self.path.read_text(encoding="utf-8"))
        self.assertFalse(list(Path(self.tmp.name).glob("*.tmp")),
                         "a temp file was left behind")


class WallCase(unittest.TestCase):
    """The page itself — held against what it must render."""

    def setUp(self):
        from aletheia.fleet import REPO_ROOT
        self.html = (REPO_ROOT / "interface" / "index.html").read_text(encoding="utf-8")

    def test_the_wall_renders_the_local_block(self):
        self.assertIn('id="presence"', self.html)
        self.assertIn("presenceHTML", self.html)
        self.assertIn("pulse.now", self.html)

    def test_it_shows_both_ages_separately(self):
        self.assertIn("her ", self.html)
        self.assertIn("fleet ", self.html)

    def test_live_means_the_heartbeat_not_the_cron(self):
        # a six-hour-old fleet pulse says nothing about whether she is running
        self.assertIn("heartbeat_age_s", self.html)
        self.assertIn("CORE SILENT", self.html)

    def test_stubs_are_visually_demoted(self):
        self.assertIn(".stub { opacity", self.html)


if __name__ == "__main__":
    unittest.main()
