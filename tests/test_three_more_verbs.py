"""Three from the 2026-09-23 night sweep with every frontier off: "who
emailed me today" was answered "want me to check?" (a question about the
inbox is the ask to look); "remind me to drink water every hour" planned for
a hundred seconds for a door she lacks; "delete the last task" planned for a
minute for want of a verb."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import voice


class InboxQuestionsLookCase(unittest.TestCase):
    def test_a_question_about_the_inbox_checks_it(self):
        for said in ("thea who emailed me today", "thea what's the last email I got", "thea any new emails",
                     "thea did anyone email me", "thea anything new in my inbox"):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(said)["command"], {"kind": "email_check"})


class HourlyReminderCase(unittest.TestCase):
    def test_within_the_day_is_said_not_planned(self):
        for said in ("thea remind me to drink water every hour", "thea remind me every 30 minutes to stretch",
                     "thea remind me to stand up every 2 hours"):
            with self.subTest(said=said):
                out = voice.interpret(said)
                self.assertIsNone(out["command"])
                self.assertIn("daily and weekly I can", out["say"])
        self.assertEqual(voice.interpret("thea remind me every day at 9 to stretch")["command"]["kind"], "remind_daily")


class DeleteTheLastTaskCase(unittest.TestCase):
    def test_the_newest_open_task_is_cancelled_by_id(self):
        rows = [{"id": "t1", "status": "OPEN", "created_at": "2026-09-22T01:00:00Z"},
                {"id": "t2", "status": "OPEN", "created_at": "2026-09-23T01:00:00Z"},
                {"id": "t3", "status": "COMPLETED", "created_at": "2026-09-23T02:00:00Z"}]
        with mock.patch("aletheia.tasks.all_tasks", return_value=rows):
            cmd = voice.interpret("thea delete the last task")["command"]
        self.assertEqual((cmd["kind"], cmd["id"], cmd["state"]), ("task_status", "t2", "CANCELLED"))
        with mock.patch("aletheia.tasks.all_tasks", return_value=[]):
            self.assertIn("no open task", voice.interpret("thea remove my latest task")["say"])


if __name__ == "__main__":
    unittest.main()
