"""His words, 2026-09-23 evening, about "What she's doing": "it says needs
you, needs you, needs you ... stopped at a captcha ... If I wanted a bot to
take me to websites where the jobs are and not actually apply to them for
me, I wouldn't be here. I need to be able to clear those."

Two rules: a human check or a sign-in on a JOB application is not his to
do and is left on the beat, and every card that waits on him carries Clear."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agenda, browser_mission as bm, intercom, journal, mission_browser, notifications, tools
from aletheia.fleet import REPO_ROOT

NOW = dt.datetime(2026, 9, 24, 0, 30, tzinfo=dt.timezone.utc)


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)

    def mission(self, mid, kind, **over):
        record = {"id": mid, "goal": "Apply for this job at Example" if mid.startswith("bm-apply") else "Sign up for the library card",
                  "start_url": "https://example.com/x", "state": bm.NEEDS_YOU, "mode": "assisted",
                  "boundary": {"kind": kind, "url": "https://example.com/x?step=2", "say": "", "at": "2026-09-24T00:20:00Z"},
                  "beat": "2026-09-24T00:20:00Z", "checkpoints": [], "route": []}
        record.update(over)
        bm.save(record)
        return record


class AWallOnAJobIsNotHis(Isolated):
    def test_a_captcha_or_sign_in_on_a_job_is_left_now_and_his_own_goal_waits(self):
        self.mission("bm-apply-for-this-job-aaaa", "CAPTCHA")
        self.mission("bm-apply-for-this-job-bbbb", "SIGN_IN")
        self.mission("bm-apply-for-this-job-cccc", "QUESTIONS")
        self.mission("bm-library-card-dddd", "CAPTCHA")
        left = bm.leave_walls(NOW)
        self.assertEqual(sorted(r["id"] for r in left), ["bm-apply-for-this-job-aaaa", "bm-apply-for-this-job-bbbb"])
        self.assertIn("a human check on a job application, which is not yours to do",
                      bm.load("bm-apply-for-this-job-aaaa")["left_because"])
        self.assertEqual(bm.load("bm-apply-for-this-job-cccc")["state"], bm.NEEDS_YOU, "a real question still waits")
        self.assertEqual(bm.load("bm-library-card-dddd")["state"], bm.NEEDS_YOU, "his own goal's check is his")
        line = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertIn("left 2 applications", line)
        self.assertNotIn("CAPTCHA", line.split("left 2 applications")[-1])


class TheClearClick(Isolated):
    def test_every_card_that_waits_on_him_carries_clear(self):
        waiting = self.mission("bm-apply-for-this-job-cccc", "QUESTIONS")
        card = mission_browser.card(waiting, NOW)
        self.assertEqual(card["status"], "NEEDS YOU")
        # Open it (the page holds his part) first, then Clear - both his clicks.
        self.assertEqual([a["label"] for a in card["actions"]], ["Open it", "Clear"])
        self.assertIn({"label": "Clear", "kind": "mission_leave", "args": {"which": "bm-apply-for-this-job-cccc"}},
                      card["actions"])
        stopped = self.mission("bm-apply-for-this-job-eeee", "REJECTED", state=bm.REJECTED)
        self.assertEqual([a["label"] for a in mission_browser.card(stopped, NOW)["actions"]], ["Clear"])
        running = self.mission("bm-apply-for-this-job-ffff", "", state=bm.RUNNING,
                               boundary={}, beat=NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(mission_browser.card(running, NOW)["actions"], [])

    def test_clearing_leaves_it_and_closes_its_application(self):
        self.mission("bm-apply-for-this-job-cccc", "QUESTIONS")
        closed = []
        with mock.patch("aletheia.intercom.rehearsing", return_value=False), \
             mock.patch("aletheia.apply_run.close_left_missions", side_effect=lambda left: closed.extend(left) or 1):
            said = intercom.execute_command({"kind": "mission_leave", "which": "browser:bm-apply-for-this-job-cccc"}, {})
        self.assertIn("Cleared", said)
        self.assertIn("Apply for this job at Example", said)
        self.assertEqual(bm.load("bm-apply-for-this-job-cccc")["state"], bm.LEFT)
        self.assertEqual(bm.load("bm-apply-for-this-job-cccc")["left_because"], "you cleared it")
        self.assertEqual([r["id"] for r in closed], ["bm-apply-for-this-job-cccc"])
        self.assertIsNone(mission_browser.card(bm.load("bm-apply-for-this-job-cccc"), NOW), "gone from the page")
        self.assertIn("cleared: Apply for this job at Example", journal.JOURNAL_PATH.read_text(encoding="utf-8"))
        with mock.patch("aletheia.intercom.rehearsing", return_value=False):
            with self.assertRaises(Exception):
                intercom.execute_command({"kind": "mission_leave", "which": "bm-nothing"}, {})
        with mock.patch("aletheia.intercom.rehearsing", return_value=True):
            self.assertIn("rehearsal", intercom.execute_command({"kind": "mission_leave", "which": "x"}, {}))

    def test_the_kind_is_his_tap_only(self):
        self.assertEqual(intercom.KIND_ARGS["mission_leave"], ({"which"}, set()))
        self.assertIn("mission_leave", intercom.ROUTINE_KINDS)
        self.assertIn("mission_leave", intercom.PLANNER_FORBIDDEN)
        self.assertIn("mission_leave", agenda.FORBIDDEN_KINDS)
        self.assertIn("mission_leave", notifications.HIS_TAP_KINDS)
        self.assertIn("mission_leave", tools.INTERNAL_KINDS)

    def test_the_page_renders_every_action_on_a_card(self):
        js = (REPO_ROOT / "interface" / "thea-app.js").read_text(encoding="utf-8")
        self.assertIn("c.actions", js)
        self.assertIn("acts(c)", js)


if __name__ == "__main__":
    unittest.main()
