"""His words, 2026-09-23: "Everything should be one click. Pretend you're an
old lady using it." A card saying "Stopped at a CAPTCHA on
jobs.example.com: waiting for you" carried no way to get there. "Open it"
opens the page the mission stopped on, in his browser, on his PC - from a
record she holds, never from a free address, and never from a model."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agenda, browser_mission, intercom, journal, mission_browser, notifications, open_it, tools

NOW = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.timezone.utc)


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)

    def mission(self, **over):
        record = {"id": "bm-apply-for-this-job-abc", "goal": "Apply for this job at Example",
                  "start_url": "https://jobs.example.com/apply/1", "state": "NEEDS_YOU", "mode": "assisted",
                  "boundary": {"kind": "CAPTCHA", "url": "https://jobs.example.com/apply/1?step=2",
                               "say": "a CAPTCHA is in front of the form", "at": "2026-09-23T11:00:00Z"},
                  "beat": "2026-09-23T11:00:00Z", "checkpoints": [], "route": []}
        record.update(over)
        browser_mission.save(record)
        return record


class TheKindIsHisTapOnly(unittest.TestCase):
    def test_the_grammar_the_tier_and_the_doors(self):
        self.assertEqual(intercom.KIND_ARGS["open_page"], ({"which"}, set()))
        self.assertIn("open_page", intercom.ROUTINE_KINDS)
        self.assertIn("open_page", intercom.PLANNER_FORBIDDEN, "a model may not open a page on his screen")
        self.assertIn("open_page", agenda.FORBIDDEN_KINDS)
        self.assertIn("open_page", notifications.HIS_TAP_KINDS)
        self.assertEqual(tools.CONSEQUENCE_OF["open_page"], tools.VISIBLE_TO_HIM)


class ThePageItOpens(Isolated):
    def test_a_missions_boundary_page_in_his_browser(self):
        self.mission()
        opened = []
        out = open_it.open_for("bm-apply-for-this-job-abc", opener=lambda url: opened.append(url) or True)
        self.assertEqual(opened, ["https://jobs.example.com/apply/1?step=2"])
        self.assertIn("Opened", out["said"])
        self.assertIn("in your browser", out["said"])
        self.assertIn("opened jobs.example.com", journal.JOURNAL_PATH.read_text(encoding="utf-8"))

    def test_where_it_started_when_the_boundary_has_no_address(self):
        self.mission(boundary={"kind": "SIGN_IN", "url": ""})
        opened = []
        open_it.open_for("bm-apply-for-this-job-abc", opener=lambda url: opened.append(url) or True)
        self.assertEqual(opened, ["https://jobs.example.com/apply/1"])

    def test_nothing_to_open_is_said_and_never_guessed(self):
        with self.assertRaises(open_it.NothingToOpen):
            open_it.open_for("nothing-like-this", opener=lambda url: True)
        self.mission(boundary={"kind": "CAPTCHA", "url": "javascript:alert(1)"}, start_url="")
        with self.assertRaises(open_it.NothingToOpen):
            open_it.open_for("bm-apply-for-this-job-abc", opener=lambda url: True)
        self.mission()
        with self.assertRaises(open_it.NothingToOpen):
            open_it.open_for("bm-apply-for-this-job-abc", opener=lambda url: False)

    def test_an_application_names_its_missions_page(self):
        self.mission()
        with mock.patch("aletheia.apply_run.find", return_value=[
                {"id": "apply-1", "company": "Example", "job_title": "CSM", "url": "https://jobs.example.com/apply/1",
                 "mission": "bm-apply-for-this-job-abc"}]), \
             mock.patch("aletheia.apply_run.describe", return_value="CSM at Example"):
            opened = []
            out = open_it.open_for("Example", opener=lambda url: opened.append(url) or True)
        self.assertEqual(opened, ["https://jobs.example.com/apply/1?step=2"])
        self.assertEqual(out["what"], "CSM at Example")

    def test_through_the_intercom_and_never_in_a_rehearsal(self):
        self.mission()
        with mock.patch("aletheia.intercom.rehearsing", return_value=False), \
             mock.patch.object(open_it, "open_for", return_value={"said": "Opened jobs.example.com in your browser."}):
            self.assertIn("Opened", intercom.execute_command({"kind": "open_page", "which": "bm-apply-for-this-job-abc"}, {}))
        with mock.patch("aletheia.intercom.rehearsing", return_value=True), \
             mock.patch.object(open_it, "open_for", side_effect=AssertionError("must not open")):
            self.assertIn("rehearsal", intercom.execute_command({"kind": "open_page", "which": "x"}, {}))


class TheCardCarriesTheClick(Isolated):
    def test_a_captcha_card_has_open_it(self):
        record = self.mission()
        card = mission_browser.card(record, NOW)
        self.assertEqual(card["status"], "NEEDS YOU")
        self.assertEqual(card["action"], {"label": "Open it", "kind": "open_page",
                                          "args": {"which": "bm-apply-for-this-job-abc"}})

    def test_a_press_waiting_on_his_yes_has_its_approve_button_not_this(self):
        record = self.mission(state="AWAITING_APPROVAL", boundary={"kind": "SUBMIT_APPROVAL",
                                                                   "url": "https://jobs.example.com/apply/1"})
        card = mission_browser.card(record, NOW)
        self.assertEqual(card["action"], {})

    def test_a_running_mission_has_nothing_to_open(self):
        record = self.mission(state="RUNNING", boundary={}, beat=NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
        card = mission_browser.card(record, NOW)
        self.assertEqual(card["action"], {})


if __name__ == "__main__":
    unittest.main()
