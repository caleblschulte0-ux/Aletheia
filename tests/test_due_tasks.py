"""A deadline he set has to come back to him.

`tasks.create` accepted a deadline, stored it, and NO CODE IN THE SYSTEM
ever compared one to the clock. "Add a task to renew the registration by
Friday" was a sentence in a file that would never come back — which is
the whole difference between a task list and a graveyard.

Worse, the deadline was not validated either, so a string the system
could never act on was stored happily and the failure showed up as
nothing happening, weeks later, with nothing to look at.
"""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, localtime, notifications, runtime, tasks


class DueCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "tasks").mkdir()
        (d / "notices").mkdir()
        for target, attr, value in ((tasks, "TASKS_DIR", d / "tasks"),
                                    (notifications, "NOTICES_DIR", d / "notices"),
                                    (journal, "JOURNAL_PATH", d / "j.jsonl")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)

    def a_task(self, tid, deadline, status="QUEUED"):
        task = tasks.create(tid, f"do {tid}", deadline=deadline)
        if status != "QUEUED":
            tasks.set_status(tid, status)
        return task

    def in_hours(self, hours):
        return (dt.datetime.now(dt.timezone.utc)
                + dt.timedelta(hours=hours)).isoformat()


class ADeadlineIsRead(DueCase):
    def test_a_bare_date_means_the_end_of_that_day_where_he_lives(self):
        """"By Friday" is not "Friday at midnight UTC", which is Thursday
        evening where he is."""
        when = tasks.parse_deadline("2026-09-12")
        self.assertEqual(when.hour, 23)
        self.assertEqual(when.tzinfo, localtime.operator_tz())

    def test_a_timestamp_with_an_offset_is_taken_as_written(self):
        when = tasks.parse_deadline("2026-09-12T17:00:00-05:00")
        self.assertEqual(when.hour, 17)

    def test_something_unparseable_is_none_not_an_exception(self):
        for bad in ("next friday", "", None, "soon", {}):
            self.assertIsNone(tasks.parse_deadline(bad))

    def test_an_unparseable_deadline_is_refused_where_the_mistake_is(self):
        """It used to be stored happily and then silently never come due."""
        with self.assertRaises(ValueError) as caught:
            tasks.create("bad-one", "something", deadline="next friday")
        self.assertIn("not a date or timestamp", str(caught.exception))


class ItComesBack(DueCase):
    def test_an_overdue_task_is_put_in_front_of_him(self):
        self.a_task("renew-tags", self.in_hours(-3))
        out = runtime.surface_due_tasks()
        self.assertEqual([r["task"] for r in out], ["renew-tags"])
        notice = notifications.all_notifications()[0]
        self.assertIn("Overdue", notice["title"])
        self.assertEqual(notice["priority"], "IMPORTANT",
                         "IMPORTANT is what reaches his screen")

    def test_due_soon_is_said_differently_from_overdue(self):
        self.a_task("pay-it", self.in_hours(4))
        runtime.surface_due_tasks()
        self.assertIn("Due soon", notifications.all_notifications()[0]["title"])

    def test_a_distant_deadline_is_left_alone(self):
        self.a_task("someday", self.in_hours(72))
        self.assertEqual(runtime.surface_due_tasks(), [])

    def test_a_finished_task_stops_nudging(self):
        self.a_task("done-thing", self.in_hours(-3), status="COMPLETED")
        self.assertEqual(runtime.surface_due_tasks(), [])

    def test_a_task_with_no_deadline_is_never_nudged(self):
        tasks.create("open-ended", "think about it")
        self.assertEqual(runtime.surface_due_tasks(), [])

    def test_the_soonest_comes_first(self):
        self.a_task("later-one", self.in_hours(6))
        self.a_task("sooner-one", self.in_hours(-1))
        self.assertEqual([r["task"] for r in runtime.surface_due_tasks()],
                         ["sooner-one", "later-one"])


class OnceADayNotOnceAndNotEveryMinute(DueCase):
    def test_the_beat_does_not_republish_it_every_sixty_seconds(self):
        """A notification every minute is a notification he turns off."""
        self.a_task("renew-tags", self.in_hours(-3))
        for _ in range(5):
            runtime.surface_due_tasks()
        self.assertEqual(len(notifications.all_notifications()), 1)

    def test_it_comes_back_the_next_day(self):
        """A deadline that spoke once at 3am and never again has not
        reminded him of anything."""
        self.a_task("renew-tags", self.in_hours(-30))
        runtime.surface_due_tasks()
        tomorrow = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
        runtime.surface_due_tasks(now=tomorrow)
        self.assertEqual(len(notifications.all_notifications()), 2)


class TheBeatRunsIt(unittest.TestCase):
    def test_it_is_in_the_tick_and_cannot_stop_it(self):
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn('guarded("due"', body)
        self.assertIn('"due_tasks": due_tasks', body)

    def test_conversation_knows_what_is_due_not_just_what_is_open(self):
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "converse.py").read_text(encoding="utf-8")
        self.assertIn('(due {task[\'deadline\']})', body)


if __name__ == "__main__":
    unittest.main()
