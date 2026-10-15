"""2026-10-15, every model off: "add a timer for the pasta for 8 minutes" went
to the planner, and then "cancel the pasta timer" - with only a plain
10-minute timer running - cancelled that one, because "timer" is in every
timer's words. A named timer is matched by its name or not at all."""
import unittest
from unittest import mock

from aletheia import intercom, voice


def _timer(rid, text, created):
    return {"id": rid, "kind": "once", "at": "2099-01-01T12:00:00+00:00", "enabled": True, "created_at": created,
            "command": {"kind": "notify", "text": text}}


TEN = _timer("t1", "your 10-minute timer is up", "2026-10-15T16:00:00Z")
EGGS = _timer("t2", "eggs timer is up", "2026-10-15T16:01:00Z")


class ANamedTimerIsItsName(unittest.TestCase):
    def one(self, needle, rows):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
            return intercom._one_reminder(needle)

    def test_no_pasta_timer_cancels_nothing(self):
        row, why = self.one("pasta timer is up", [TEN])
        self.assertIsNone(row)
        self.assertEqual(why, "You don't have a pasta timer. The 10-minute timer is running.")

    def test_it_names_the_ones_that_are_running(self):
        row, why = self.one("rice timer is up", [TEN, EGGS])
        self.assertIsNone(row)
        self.assertIn("You don't have a rice timer.", why)
        self.assertIn("timers are running", why)

    def test_the_one_named_is_found(self):
        row, _why = self.one("eggs timer is up", [TEN, EGGS])
        self.assertEqual(row["id"], "t2")

    def test_any_timer_still_means_the_timer(self):
        row, _why = self.one("timer is up", [TEN])
        self.assertEqual(row["id"], "t1")


class AddATimer(unittest.TestCase):
    def test_add_is_set(self):
        self.assertEqual(voice._texted("add a timer for the pasta for 8 minutes"),
                         "set a timer for the pasta for 8 minutes")
        self.assertEqual(voice._texted("thea create a 5 minute timer for the eggs"),
                         "thea set a 5 minute timer for the eggs")

    def test_a_task_about_a_timer_is_left_alone(self):
        self.assertEqual(voice._texted("add a task to make a timer app"), "add a task to make a timer app")
        self.assertEqual(voice._texted("make a timer app"), "make a timer app")


if __name__ == "__main__":
    unittest.main()
