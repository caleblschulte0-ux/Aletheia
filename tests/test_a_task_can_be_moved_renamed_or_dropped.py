"""A task he can add and tick off, he can also move, rename and drop.

2026-10-07: "move call the plumber to friday", "rename the passport one to
renew passport online" and "delete call the plumber" all went to the
planner. One verb, `task_change`, finds the task by his words and changes
one thing; the same verbs about notes or meetings are left alone.
"""
import unittest
from unittest import mock

from aletheia import act, intercom, speech, tasks, voice


ROWS = [{"id": "call-the-plumber", "description": "call the plumber", "status": "PENDING"},
        {"id": "renew-my-passport", "description": "renew my passport", "status": "PENDING"}]


class HeCanSayIt(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(intercom, "_open_tasks", return_value=ROWS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_move(self):
        got = voice.interpret("move call the plumber to friday")["command"]
        self.assertEqual((got["kind"], got["which"]), ("task_change", "call the plumber"))
        self.assertRegex(got["deadline"], r"^\d{4}-\d{2}-\d{2}$")

    def test_rename_keeps_his_words(self):
        got = voice.interpret("rename the passport one to Renew Passport Online")["command"]
        self.assertEqual(got["description"], "Renew Passport Online")

    def test_drop(self):
        got = voice.interpret("delete call the plumber")["command"]
        self.assertEqual((got["kind"], got.get("drop")), ("task_change", True))
        self.assertTrue(voice.interpret("take the plumber one off my list")["command"]["drop"])

    def test_words_that_name_no_task_are_left_alone(self):
        for said in ("delete my last note", "move my 3pm to friday", "cancel that", "cancel the first one"):
            self.assertNotEqual((voice.interpret(said)["command"] or {}).get("kind"), "task_change", said)


class ItReallyChanges(unittest.TestCase):
    def run_cmd(self, **cmd):
        with mock.patch.object(intercom, "_open_tasks", return_value=ROWS):
            return intercom.execute_command({"kind": "task_change", "which": "plumber", **cmd}, {})

    def test_drop_cancels_it(self):
        with mock.patch.object(tasks, "set_status") as setter:
            said = self.run_cmd(drop=True)
        self.assertEqual(setter.call_args[0][:2], ("call-the-plumber", "CANCELLED"))
        self.assertEqual(speech.spoken_receipt("task_change", said), "Dropped: call the plumber.")

    def test_move_sets_the_deadline(self):
        with mock.patch.object(tasks, "set_deadline",
                               return_value={**ROWS[0], "deadline": "2026-10-09"}) as setter:
            self.run_cmd(deadline="2026-10-09")
        self.assertEqual(setter.call_args[0], ("call-the-plumber", "2026-10-09"))

    def test_one_change_at_a_time(self):
        with self.assertRaises(act.Refused):
            self.run_cmd(drop=True, deadline="2026-10-09")
        with self.assertRaises(act.Refused):
            self.run_cmd(deadline="someday")

    def test_it_is_routine_like_ticking_off(self):
        self.assertEqual(intercom.tier("task_change"), intercom.tier("task_done"))


if __name__ == "__main__":
    unittest.main()


class NotesAndHerWorkspace(unittest.TestCase):
    def test_his_notes_asked_about_himself(self):
        from aletheia import quick
        for said in ("what notes do i have", "read my notes", "how many notes do i have"):
            self.assertEqual(quick.match(said)[0], "notes_list", said)

    def test_an_empty_workspace_is_said_in_her_own_voice(self):
        from aletheia import workspace
        with mock.patch.object(workspace, "listing", return_value=[]):
            said = intercom.execute_command({"kind": "file_list"}, {})
        self.assertIn("my workspace", said)
        self.assertNotIn("her ", said)
