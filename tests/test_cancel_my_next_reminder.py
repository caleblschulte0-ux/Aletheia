""""Cancel my next reminder" answered "None of your reminders is about next",
straight after "what's my next reminder" had named it, and "what reminders
repeat" went to a model (2026-10-18, every model off)."""
import unittest
from unittest import mock

from aletheia import intercom, quick


class NextIsTheSoonest(unittest.TestCase):
    rows = [{"id": "late", "command": {"text": "water the plants"}},
            {"id": "soon", "command": {"text": "call mom"}}]

    def test_next_is_the_one_going_off_first(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=self.rows), \
                mock.patch.object(intercom, "_soonest_first", side_effect=lambda rows: sorted(rows, key=lambda r: r["id"] != "soon")):
            for which in ("next", "my next", "the next one", "next reminder", "upcoming"):
                with self.subTest(which=which):
                    got, why = intercom._one_reminder(which)
                    self.assertEqual((got or {}).get("id"), "soon", why)

    def test_a_reminder_about_the_next_thing_is_still_found_by_its_words(self):
        rows = [{"id": "r1", "command": {"text": "plan the next trip"}}]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
            got, _why = intercom._one_reminder("next trip")
        self.assertEqual(got["id"], "r1")


class WhatRepeats(unittest.TestCase):
    def test_asked_without_my(self):
        for said in ("what reminders repeat", "which reminders do i have that repeat",
                     "do i have any recurring reminders", "are there any repeating reminders set"):
            with self.subTest(said=said):
                first = next(name for name, rx in quick.PATTERNS if rx.search(quick._tidy(said)))
                self.assertEqual(first, "repeating")


if __name__ == "__main__":
    unittest.main()
