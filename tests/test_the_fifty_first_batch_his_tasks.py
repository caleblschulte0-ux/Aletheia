"""Fifty-first sandbox batch, 2026-10-05: his tasks, asked about and shaped.

    > add a deadline of friday to the passport task   [6.5s] a plan, an approval
    > prioritize the bank one                         [5.5s] a model
    > snooze the dentist till monday                  [8.0s] a plan, an approval
    > which tasks have deadlines / what's due soonest  [6.5s] a model each
    > how many tasks did I finish this week           [19.5s] a model, which counted nothing
    > what's left this week / what's after that       a model each
"""
import datetime as dt
import unittest
import uuid
from unittest import mock

from aletheia import intercom, localtime, quick, scheduler, tasks, voice


def _clear():
    for t in tasks.all_tasks():
        if t.get("status") not in tasks.contracts.TASK_TERMINAL:
            tasks.set_status(t["id"], "CANCELLED", "test")


class Deadlines(unittest.TestCase):
    def setUp(self):
        _clear()
        self.addCleanup(_clear)
        self.passport, self.bank = f"renew-passport-{uuid.uuid4().hex[:6]}", f"call-the-bank-{uuid.uuid4().hex[:6]}"
        intercom.execute_command({"kind": "task_new", "id": self.passport, "description": "renew my passport"}, "q")
        intercom.execute_command({"kind": "task_new", "id": self.bank, "description": "call the bank"}, "q")

    def test_a_deadline_is_put_on_a_task_he_has(self):
        d = voice.interpret("thea add a deadline of friday to the passport task")
        self.assertEqual(d["command"]["kind"], "task_status")
        self.assertEqual(d["command"]["id"], self.passport)
        self.assertEqual(dt.date.fromisoformat(d["command"]["deadline"]).strftime("%A"), "Friday")
        said = intercom.execute_command(d["command"], "q")
        self.assertTrue(said.startswith("Deadline set: renew my passport, by "), said)
        self.assertNotIn("11:59", said)
        self.assertEqual(tasks.load(self.passport)["deadline"], d["command"]["deadline"])
        d = voice.interpret("thea the passport task is due next monday")
        self.assertEqual(dt.date.fromisoformat(d["command"]["deadline"]).strftime("%A"), "Monday")
        self.assertGreater(dt.date.fromisoformat(d["command"]["deadline"]), localtime.today() + dt.timedelta(days=6))
        self.assertEqual(voice.interpret("thea give the passport one a deadline of the 20th")["command"]["deadline"][-2:], "20")
        # a reminder is not a task
        self.assertNotEqual(voice.interpret("thea the dentist reminder is due friday")["command"].get("kind"), "task_status")

    def test_then_the_deadline_questions_read_it(self):
        self.assertIn("None of your open tasks has a deadline", quick.answer("which tasks have deadlines"))
        intercom.execute_command(voice.interpret("thea add a deadline of friday to the passport task")["command"], "q")
        self.assertEqual(quick.answer("which tasks have deadlines"), "1 task with a deadline: renew my passport by Friday.")
        self.assertEqual(quick.answer("what's due soonest"), "Soonest: renew my passport by Friday.")
        self.assertEqual(quick.match("what's left this week")[0], "left_week")
        self.assertIn("renew my passport", quick.answer("what's left this week"))

    def test_priority_puts_it_first(self):
        d = voice.interpret("thea prioritize the bank one")
        self.assertEqual(d["command"], {"kind": "task_status", "id": self.bank, "state": "QUEUED", "priority": 1})
        self.assertEqual(intercom.execute_command(d["command"], "q"), "Moved to the top of your list: call the bank.")
        self.assertTrue(intercom._tasks_answer().startswith("2 things on your list: call the bank and renew my passport"))
        self.assertEqual(quick.answer("what's after that"), "Then renew my passport. That's the list.")

    def test_finished_counts_what_he_marked_done(self):
        self.assertIn("No tasks marked done this week", quick.answer("how many tasks did I finish this week"))
        intercom.execute_command({"kind": "task_done", "which": "bank"}, "q")
        self.assertEqual(quick.answer("what did I finish today"), "1 task done today: call the bank.")
        self.assertEqual(quick.answer("how many tasks did I finish this week"), "1 task done this week: call the bank.")
        self.assertIn("No tasks marked done yesterday", quick.answer("what did I finish yesterday"))


class SnoozeTillADay(unittest.TestCase):
    def test_the_reminder_moves_to_that_day_at_its_own_time(self):
        tz = localtime.operator_tz()
        at = dt.datetime.combine(localtime.today() + dt.timedelta(days=1), dt.time(14, 30), tzinfo=tz)
        rows = [{"id": "r-dentist", "version": 1, "kind": "once", "at": at.isoformat(), "enabled": True,
                 "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "command": {"kind": "notify_operator", "text": "call the dentist"}}]
        with mock.patch.object(scheduler, "all_schedules", return_value=rows):
            d = voice.interpret("thea snooze the dentist till monday")
            self.assertEqual(d["command"]["kind"], "remind_at")
            self.assertEqual(d["command"]["replaces"], "call the dentist")
            when = dt.datetime.fromisoformat(d["command"]["at"])
            self.assertEqual((when.strftime("%A"), when.hour, when.minute), ("Monday", 14, 30))
            d = voice.interpret("thea push the dentist to friday at 9")
            when = dt.datetime.fromisoformat(d["command"]["at"])
            self.assertEqual((when.strftime("%A"), when.hour), ("Friday", 9))


if __name__ == "__main__":
    unittest.main()
