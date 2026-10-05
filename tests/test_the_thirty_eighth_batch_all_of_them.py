"""Thirty-eighth sandbox batch, 2026-10-05: "all" means all.

    > cancel all reminders   "Which one — call dad or call mom?"
    > clear all tasks        [5.2s] the planner, two steps, an approval
    > deny all               [7.0s] a model: "1 step only you can do."
"""
import unittest
from unittest import mock

from aletheia import intercom, voice


class AllOfThem(unittest.TestCase):
    def test_the_sentences(self):
        self.assertEqual(voice.interpret("cancel all reminders")["command"], {"kind": "reminder_off", "which": "all"})
        self.assertEqual(voice.interpret("cancel the dentist reminder")["command"], {"kind": "reminder_off", "which": "dentist"})
        self.assertEqual(voice.interpret("clear all tasks")["command"], {"kind": "task_done", "which": "everything", "as": "cancelled"})
        self.assertEqual(voice.interpret("deny all")["command"]["id"], "all")
        self.assertIn("as", intercom.KIND_ARGS["task_done"][1])

    def test_every_reminder_goes_off(self):
        rows = [{"id": "r1", "kind": "once", "command": {"kind": "notify_operator", "text": "call mom"}},
                {"id": "r2", "kind": "once", "command": {"kind": "notify_operator", "text": "call dad"}}]
        with mock.patch("aletheia.intercom._reminder_schedules", return_value=rows), \
             mock.patch("aletheia.scheduler.set_enabled") as off:
            said = intercom.execute_command({"kind": "reminder_off", "which": "all"}, {"repos": {}})
        self.assertEqual(said, "reminders off — call mom and call dad")
        self.assertEqual([c.args for c in off.call_args_list], [("r1", False), ("r2", False)])

    def test_every_task_is_cleared_not_done(self):
        rows = [{"id": "a", "description": "a"}, {"id": "b", "description": "b"}]
        with mock.patch("aletheia.intercom._open_tasks", return_value=rows), \
             mock.patch("aletheia.tasks.set_status") as moved:
            said = intercom.execute_command({"kind": "task_done", "which": "everything", "as": "cancelled"}, {"repos": {}}, quote="clear all tasks")
        self.assertEqual(said, "Cleared your task list: a and b.")
        self.assertEqual([c.args[1] for c in moved.call_args_list], ["CANCELLED", "CANCELLED"])

    def test_deny_all_is_each_its_own_no(self):
        pending = [{"id": "ap-1", "state": "PENDING"}, {"id": "ap-2", "state": "PENDING"}, {"id": "ap-3", "state": "APPROVED"}]
        with mock.patch("aletheia.policy.all_approvals", return_value=pending), \
             mock.patch("aletheia.policy.decide", side_effect=lambda i, s, **k: {"id": i, "state": s}) as decided, \
             mock.patch("aletheia.intercom._approval_words", side_effect=lambda a, i: f"the {i} thing"):
            said = intercom.execute_command({"kind": "deny", "id": "all"}, {"repos": {}})
        self.assertEqual(said, "denied — the ap-1 thing; the ap-2 thing")
        self.assertEqual([c.args[0] for c in decided.call_args_list], ["ap-1", "ap-2"])
        with mock.patch("aletheia.policy.all_approvals", return_value=[]):
            self.assertEqual(intercom.execute_command({"kind": "deny", "id": "all"}, {"repos": {}}), "Nothing is waiting for approval.")


if __name__ == "__main__":
    unittest.main()
