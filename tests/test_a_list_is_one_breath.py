"""Several things for the shopping list are one sentence, not an approval."""
import unittest
from unittest import mock

from aletheia import intercom, voice


class AListIsOneBreath(unittest.TestCase):
    def cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}

    def test_a_comma_list_goes_straight_on(self):
        c = self.cmd("add eggs, bread and butter to my shopping list")
        self.assertEqual(c.get("kind"), "shopping_add")
        self.assertEqual(intercom.shopping_items_of(c["item"]), ["eggs", "bread", "butter"])

    def test_a_dish_with_and_in_its_name_is_one_row(self):
        self.assertEqual(intercom.shopping_items_of("mac and cheese"), ["mac and cheese"])
        self.assertEqual(intercom.shopping_items_of("eggs, mac and cheese and milk"),
                         ["eggs", "mac and cheese", "milk"])
        self.assertEqual(self.cmd("add mac and cheese to the list").get("kind"), "shopping_add")

    def test_a_doubtful_shape_still_goes_to_the_planner(self):
        self.assertNotEqual(self.cmd("add eggs milk and bread to the shopping list").get("kind"),
                            "shopping_add")


class AnythingTomorrowIsHisCalendar(unittest.TestCase):
    def cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}

    def test_anything_tomorrow_is_free_time(self):
        self.assertEqual(self.cmd("do I have anything tomorrow").get("kind"), "free_time")
        self.assertEqual(self.cmd("do I have anything on friday").get("kind"), "free_time")

    def test_this_weekend_is_a_stretch(self):
        c = self.cmd("do I have any plans this weekend")
        self.assertEqual((c.get("kind"), c.get("when")), ("calendar_find_free", "this weekend"))

    def test_a_file_is_still_a_file(self):
        self.assertEqual(self.cmd("do I have a file called taxes").get("kind"), "file_find")


if __name__ == "__main__":
    unittest.main()


class HowLongLeftOnTheTimer(unittest.TestCase):
    def test_it_is_a_subtraction(self):
        import datetime as dt
        now = dt.datetime(2026, 10, 7, 1, 0, tzinfo=dt.timezone.utc)
        rows = [{"kind": "once", "at": "2026-10-07T01:09:30+00:00",
                 "command": {"kind": "notify_operator", "text": "your 10-minute timer is up"}},
                {"kind": "once", "at": "2026-10-07T02:30:00+00:00",
                 "command": {"kind": "notify_operator", "text": "your 2-hour timer is up"}},
                {"kind": "once", "at": "2026-10-07T03:00:00+00:00",
                 "command": {"kind": "notify_operator", "text": "pay rent"}}]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
            said = voice._timer_left(now)
        self.assertEqual(said, "9 minutes left on your 10-minute timer and "
                               "1 hour and 30 minutes left on your 2-hour timer.")

    def test_no_timer_says_so(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[]):
            self.assertEqual(voice._timer_left(), "No timer is running.")

    def test_the_question_reaches_it(self):
        for said in ("how long left on my timer", "how much time is left on the timer",
                     "when will my timer go off"):
            out = voice._interpret(said) or {}
            self.assertIsNone(out.get("command"), said)
            self.assertTrue(out.get("say"), said)


class ToDoListAndNotes(unittest.TestCase):
    def test_to_do_list_is_the_task_list(self):
        for said in ("what's on my to do list", "my to do list", "show me my to-do list"):
            self.assertEqual(((voice._interpret(said) or {}).get("command") or {}).get("kind"),
                             "tasks", said)

    def test_add_to_my_to_do_list_is_a_task(self):
        c = (voice._interpret("add call the bank to my to do list") or {}).get("command") or {}
        self.assertEqual(c.get("kind"), "task_new")

    def test_what_are_my_notes_is_the_notes_list(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=[{"text": "wifi is on the fridge"}]):
            self.assertIn("fridge", quick.answer("what are my notes") or "")
