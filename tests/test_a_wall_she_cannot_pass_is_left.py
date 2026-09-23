"""Live 2026-09-23 his page carried 72 "waiting for you" cards from the
general browser - 30 with no way forward, 16 where he had already said no,
3 whose posting had closed, 11 where she ran out of steps, went in circles
or hit an error - each ending "it carries on when you do your part", with
nothing to press. A wall she cannot pass is a wall she leaves; a wall that
is his waits two days and is then left too, said as such."""
import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from aletheia import apply_run, browser_mission as bm, mission_browser

NOW = dt.datetime(2026, 9, 23, 9, 0, tzinfo=dt.timezone.utc)


def mission(mid, kind, hours_ago, state="NEEDS_YOU", url="https://jobs.example.com/x"):
    at = (NOW - dt.timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {"id": mid, "goal": "apply for this job", "start_url": url, "state": state,
            "boundary": {"kind": kind, "url": url, "at": at, "say": "stopped"}, "beat": at}


class WallsAreLeft(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)
        p = mock.patch.object(bm, "missions_dir", return_value=self.dir)
        p.start(); self.addCleanup(p.stop)
        self.lines = []
        j = mock.patch("aletheia.browser_mission.journal.append", side_effect=lambda *a, **k: self.lines.append(a))
        j.start(); self.addCleanup(j.stop)

    def test_what_is_not_his_is_left_now_and_his_waits_two_days(self):
        for m in (mission("m-noway", "NO_WAY_FORWARD", 1), mission("m-denied", "APPROVAL_DENIED", 1),
                  mission("m-closed", "POSTING_CLOSED", 90), mission("m-captcha-new", "CAPTCHA", 3),
                  mission("m-captcha-old", "CAPTCHA", 60), mission("m-signin", "SIGN_IN", 1),
                  mission("m-running", "", 1, state="RUNNING")):
            bm.save(m)
        left = bm.leave_walls(NOW)
        self.assertEqual(sorted(r["id"] for r in left), ["m-captcha-old", "m-closed", "m-denied", "m-noway"])
        self.assertEqual(bm.load("m-captcha-new")["state"], "NEEDS_YOU", "a fresh human check still waits for him")
        self.assertEqual(bm.load("m-signin")["state"], "NEEDS_YOU")
        self.assertEqual(bm.load("m-running")["state"], "RUNNING")
        self.assertEqual(bm.load("m-noway")["state"], bm.LEFT)
        self.assertIn("no way forward", bm.load("m-noway")["left_because"])
        self.assertIn("two days", bm.load("m-captcha-old")["left_because"])
        self.assertEqual(len(self.lines), 1, "one journal line for the sweep, not one per mission")
        self.assertIn("left 4 applications", self.lines[0][2])
        self.assertNotIn("NO_WAY_FORWARD", self.lines[0][2])
        self.assertEqual(bm.leave_walls(NOW), [], "a second sweep finds nothing to leave")

    def test_a_left_wall_and_a_wall_that_is_not_his_render_no_card(self):
        self.assertIsNone(mission_browser.card(mission("m1", "NO_WAY_FORWARD", 1), NOW))
        self.assertIsNone(mission_browser.card({**mission("m2", "CAPTCHA", 1), "state": bm.LEFT}, NOW))
        card = mission_browser.card(mission("m3", "CAPTCHA", 1), NOW)
        self.assertIsNotNone(card)
        self.assertEqual(card["status"], "NEEDS YOU")


class TheRecordsBehindThemClose(unittest.TestCase):
    def test_left_missions_close_their_application_records_quietly(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(apply_run, "staged_dir", lambda: pathlib.Path(tmp)), \
             mock.patch("aletheia.apply_run.journal.append", side_effect=AssertionError("one line per record")):
            url = "https://jobs.example.com/x"
            rid = f"apply-{apply_run._tag(url)}"
            apply_run.stateio.write_json_atomic(apply_run._record_path(rid),
                                                {"id": rid, "state": "NEEDS_YOU", "url": url, "engine": "browser_loop"})
            sent_url = "https://jobs.example.com/sent"
            sid = f"apply-{apply_run._tag(sent_url)}"
            apply_run.stateio.write_json_atomic(apply_run._record_path(sid),
                                                {"id": sid, "state": "SUBMITTED", "url": sent_url})
            left = [{**mission("m", "NO_WAY_FORWARD", 1, url=url), "left_because": "nothing more she could do here: no way forward on the page"},
                    {**mission("m2", "NO_WAY_FORWARD", 1, url=sent_url), "left_because": "x"}]
            self.assertEqual(apply_run.close_left_missions(left), 1)
            self.assertEqual(apply_run.load_run(rid)["state"], apply_run.CLOSED)
            self.assertEqual(apply_run.load_run(rid)["closed_kind"], "left")
            self.assertEqual(apply_run.load_run(sid)["state"], "SUBMITTED", "a sent one is never touched")


class TheJournalLineIsASentence(unittest.TestCase):
    def test_no_state_code_reaches_the_journal(self):
        said = apply_run._loop_line("https://www.jobs.paloaltonetworks.com/en", "NEEDS_YOU",
                                    {"kind": "CAPTCHA"}, {"state": "NEEDS_YOU"})
        self.assertEqual(said, "jobs.paloaltonetworks.com: stopped at a human check - left for you")
        said = apply_run._loop_line("https://careers.se.com/jobs/1", "NEEDS_YOU", {"kind": "NO_WAY_FORWARD"}, {})
        self.assertEqual(said, "careers.se.com: stopped at no way forward on the page")
        self.assertEqual(apply_run._loop_line("https://x.com/a", "SUBMITTED", {}, {}), "x.com: sent through the general browser")
        for s in (said,):
            self.assertNotIn("NEEDS_YOU", s)


if __name__ == "__main__":
    unittest.main()
