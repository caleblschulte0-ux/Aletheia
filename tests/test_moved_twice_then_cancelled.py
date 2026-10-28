"""A reminder moved twice and then cancelled is one stopped reminder.

2026-10-28, talking to her with the models off:

    > remind me tomorrow at 9 to email sarah
    > make it 10 instead
    > actually make it friday
    > cancel all my reminders
    > what reminders do i have
      None are on right now. You stopped these this week: email sarah —
      Friday at 10 am, email sarah — tomorrow at 9 am and email sarah —
      tomorrow at 10 am.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, scheduler


def spec(sid, at, *, moved=False, stamp="2026-10-28T15:00:00Z"):
    row = {"version": 1, "id": sid, "kind": "once", "at": at, "enabled": False, "created_at": stamp, "updated_at": stamp,
           "command": {"kind": "notify_operator", "text": "email sarah"}}
    if moved:
        row["moved"] = True
    return row


class OneStop(unittest.TestCase):
    def test_the_moved_ones_are_not_stopped(self):
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [spec("a", soon, moved=True, stamp=now), spec("b", soon, moved=True, stamp=now), spec("c", soon, stamp=now)]
        with mock.patch.object(scheduler, "all_schedules", return_value=rows):
            self.assertEqual([r["id"] for r in intercom._stopped_reminders()], ["c"])

    def test_the_same_words_stopped_twice_are_said_once(self):
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now = dt.datetime.now(dt.timezone.utc)
        rows = [spec("old", soon, stamp=(now - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")),
                spec("new", soon, stamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"))]
        with mock.patch.object(scheduler, "all_schedules", return_value=rows):
            self.assertEqual([r["id"] for r in intercom._stopped_reminders()], ["new"])

    def test_moving_marks_the_old_one(self):
        saved = {}
        with mock.patch.object(scheduler, "load", return_value={"id": "x", "enabled": True}), \
                mock.patch.object(scheduler, "save", side_effect=lambda s: saved.update(s) or s):
            scheduler.set_enabled("x", False, moved=True)
        self.assertTrue(saved["moved"])
        with mock.patch.object(scheduler, "load", return_value=dict(saved)), \
                mock.patch.object(scheduler, "save", side_effect=lambda s: saved.clear() or saved.update(s) or s):
            scheduler.set_enabled("x", True)
        self.assertNotIn("moved", saved)


if __name__ == "__main__":
    unittest.main()
