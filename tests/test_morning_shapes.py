"""The first things he asks in the morning, with every frontier off
(2026-09-23 sweep): "what happened overnight" and "anything from employers"
and "how many applications went out tonight" waited two minutes on her own
model; "when did you last update" was guessed from the journal ("no record
of that"); "brief me" read a terminal command out loud."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import quick


def _stamp(hours_ago: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class OvernightCase(unittest.TestCase):
    def test_sent_and_done_since_ten_last_night(self):
        sent = [{"id": "apply-1", "state": "SUBMITTED", "company": "Taranis", "submitted_at": _stamp(1)},
                {"id": "apply-2", "state": "SUBMITTED", "company": "Eaton", "submitted_at": _stamp(2)},
                {"id": "apply-3", "state": "SUBMITTED", "company": "Old Co", "submitted_at": _stamp(40)}]
        journal = [{"ts": _stamp(1.5), "kind": "action", "subject": "apply", "actor": "aletheia-apply",
                    "text": "submitted apply-1 to https://x/1"}]
        with mock.patch("aletheia.apply_run.all_runs", return_value=sent), \
             mock.patch("aletheia.recollection._read_journal", return_value=(journal, True)), \
             mock.patch("aletheia.quick._now_hour", return_value=8, create=True):
            said = quick.answer("what happened overnight")
        self.assertTrue(said.startswith("Overnight:"), said)
        self.assertIn("2 applications sent overnight", said)
        self.assertIn("Taranis", said)
        self.assertNotIn("Old Co", said)

    def test_a_quiet_night_says_so(self):
        with mock.patch("aletheia.apply_run.all_runs", return_value=[]), \
             mock.patch("aletheia.recollection._read_journal", return_value=([], True)):
            self.assertIn("quiet night", quick.answer("did anything happen while I was asleep"))


class TonightCountCase(unittest.TestCase):
    def test_tonight_and_last_night_are_windows(self):
        sent = [{"id": "apply-1", "state": "SUBMITTED", "company": "Taranis", "submitted_at": _stamp(0.5)},
                {"id": "apply-2", "state": "SUBMITTED", "company": "Old Co", "submitted_at": _stamp(60)}]
        with mock.patch("aletheia.apply_run.all_runs", return_value=sent):
            said = quick.answer("how many applications went out last night")
        self.assertIn("sent last night", said)
        self.assertIn("Taranis", said)
        self.assertNotIn("Old Co", said)


class EmployersCase(unittest.TestCase):
    def test_anything_from_employers_is_the_replies_shape(self):
        with mock.patch("aletheia.quick._replies", return_value="Nobody has written back yet.") as replies:
            for said in ("anything from employers", "did any employers reply", "any news from recruiters"):
                with self.subTest(said=said):
                    self.assertEqual(quick.answer(said), "Nobody has written back yet.")
        self.assertTrue(replies.called)


class UpdatedCase(unittest.TestCase):
    def test_when_she_last_updated_is_git_and_version(self):
        done = mock.Mock(returncode=0, stdout="2026-09-23T02:39:00+00:00\n")
        with mock.patch("aletheia.proc.run", return_value=done), \
             mock.patch("aletheia.running.version", return_value={"running_old_code": False, "behind_count": 0}):
            said = quick.answer("when did you last update")
        self.assertTrue(said.startswith("My code last changed"), said)
        self.assertIn("that's the code I'm running", said)
        with mock.patch("aletheia.proc.run", return_value=done), \
             mock.patch("aletheia.running.version", return_value={"running_old_code": False, "behind_count": 3}):
            self.assertIn("3 newer changes waiting", quick.answer("are you up to date"))
        with mock.patch("aletheia.proc.run", return_value=done), \
             mock.patch("aletheia.running.version", return_value={"running_old_code": True}):
            self.assertIn("restart me", quick.answer("when was your last update"))
        # "What version are you on" stays the version shape, which says the commit.
        self.assertNotEqual(quick.match("what version are you on")[0], "updated")


class BriefWithoutAReadingCase(unittest.TestCase):
    def test_no_command_is_read_out_loud(self):
        from aletheia import intercom
        with mock.patch("aletheia.pulse.PULSE_DIR") as d:
            d.__truediv__.return_value.exists.return_value = False
            said = intercom.execute_command({"kind": "brief"}, {})
        self.assertNotIn("python", said)
        self.assertIn("fleet reading", said)


if __name__ == "__main__":
    unittest.main()
