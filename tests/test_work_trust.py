"""Standing workstation trust only auto-opens the already-bounded Work Session layer."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, policy, work_direct, work_session, work_trust


class WorkTrustCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(work_trust, "GRANT_PATH", root / "grant.json"),
            mock.patch.object(work_session, "SESSION_PATH", root / "session.json"),
            mock.patch.object(work_session, "CLAIMS_DIR", root / "claims"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
            mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"),
            mock.patch.object(policy, "HALT_PATH", root / "halt.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.now = dt.datetime(2026, 8, 30, 1, 0, tzinfo=dt.timezone.utc)

    def test_enable_creates_expiring_private_grant(self):
        grant = work_trust.enable(
            days=30, session_hours=6, session_actions=150,
            via="test-local", now=self.now,
        )
        self.assertTrue(policy.is_approved(grant["approval_id"]))
        live = work_trust.active(now=self.now)
        self.assertIsNotNone(live)
        self.assertEqual(live["session_hours"], 6)
        self.assertEqual(live["session_actions"], 150)
        self.assertTrue(work_trust.GRANT_PATH.is_file())

    def test_expired_or_disabled_grant_cannot_open_session(self):
        work_trust.enable(days=1, via="test-local", now=self.now)
        later = self.now + dt.timedelta(days=2)
        self.assertIsNone(work_trust.active(now=later))
        self.assertIsNone(work_trust.ensure_session(now=later))
        self.assertFalse(work_session.SESSION_PATH.exists())

        # Fresh grant then explicit off is equally final.
        work_trust.enable(days=2, via="test-local", now=self.now)
        self.assertTrue(work_trust.disable(via="test-local"))
        self.assertIsNone(work_trust.ensure_session(now=self.now))

    def test_active_grant_auto_opens_only_bounded_work_session(self):
        grant = work_trust.enable(
            days=10, session_hours=4, session_actions=99,
            via="test-local", now=self.now,
        )
        session = work_trust.ensure_session(now=self.now)
        self.assertIsNotNone(session)
        self.assertEqual(session["max_actions"], 99)
        self.assertEqual(
            dt.datetime.fromisoformat(session["expires"].replace("Z", "+00:00")),
            self.now + dt.timedelta(hours=4),
        )
        self.assertTrue(policy.is_approved(session["approval_id"]))
        self.assertNotEqual(session["approval_id"], grant["approval_id"])

    def test_existing_session_is_reused_not_reapproved(self):
        work_trust.enable(days=10, via="test-local", now=self.now)
        first = work_trust.ensure_session(now=self.now)
        second = work_trust.ensure_session(now=self.now + dt.timedelta(minutes=2))
        self.assertEqual(first["id"], second["id"])

    def test_kill_switch_beats_standing_grant(self):
        work_trust.enable(days=10, via="test-local", now=self.now)
        policy.halt("operator stop", via="test")
        with self.assertRaises(policy.Halted):
            work_trust.ensure_session(now=self.now)

    def test_bounds_are_hard(self):
        with self.assertRaises(ValueError):
            work_trust.enable(days=work_trust.MAX_DAYS + 1, now=self.now)
        with self.assertRaises(ValueError):
            work_trust.enable(session_hours=work_session.MAX_HOURS + 1, now=self.now)
        with self.assertRaises(ValueError):
            work_trust.enable(session_actions=work_session.MAX_ACTIONS + 1, now=self.now)


class DirectWorkTrustHookCase(unittest.TestCase):
    def test_direct_work_uses_local_trust_when_no_session_is_live(self):
        quote = "Open Notepad"
        text = work_direct.encode(
            quote=quote, summary="Open Notepad",
            actions=[{"type": "computer", "steps": [
                {"action": "open_app", "app": "notepad.exe", "arguments": []}
            ]}],
        )
        with mock.patch.object(work_direct.work_session, "active", return_value=None), \
             mock.patch("aletheia.work_trust.ensure_session", return_value={"id": "auto"}) as ensure, \
             mock.patch.object(
                 work_direct.work_session, "run_computer",
                 return_value={"run_id": "run-1", "steps_done": 1},
             ) as run:
            result = work_direct.execute(text, quote=quote)
        ensure.assert_called_once_with()
        run.assert_called_once()
        self.assertEqual(result["state"], "EXECUTED")

    def test_direct_work_still_refuses_when_neither_session_nor_grant_exists(self):
        quote = "Open Notepad"
        text = work_direct.encode(
            quote=quote, summary="Open Notepad",
            actions=[{"type": "computer", "steps": [
                {"action": "open_app", "app": "notepad.exe", "arguments": []}
            ]}],
        )
        with mock.patch.object(work_direct.work_session, "active", return_value=None), \
             mock.patch("aletheia.work_trust.ensure_session", return_value=None), \
             mock.patch.object(work_direct.work_session, "run_computer") as run:
            with self.assertRaises(work_session.WorkSessionRequired):
                work_direct.execute(text, quote=quote)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
