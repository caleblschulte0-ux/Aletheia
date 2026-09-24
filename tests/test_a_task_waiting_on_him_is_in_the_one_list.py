"""One list of what needs him — and the task store is one of its sources.

Live 2026-09-24, on his page: two task cards under "What she's doing" said
"needs you", each with an "I did it" button, while the "Needs you" section
beside them said "Nothing needs you right now." The cards read
`state/tasks`; the list read approvals, work and applications and not that
store. Two surfaces, two answers about the same thing, which is precisely
what the one list was built to end.

Two more things were wrong with those cards. One was titled "Verify or
repair capability reservation.book" — a session's words, with a capability
id in them, above the drawer; the registry says what an id IS, and that is
what he reads. And it was not his at all: its tests passed, and what it
waited for was a real booking one day, which is the world's to bring, not
a chore of his to tick off.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import mission_control as mc
from aletheia import needs_you, speech, tasks


def _task(**over) -> dict:
    row = {"id": "configure-reservation-book", "status": "WAITING_OPERATOR",
           "description": "Configure capability reservation.book",
           "created_at": "2026-09-17T02:58:13Z", "updated_at": "2026-09-18T17:07:08Z"}
    row.update(over)
    return row


class ATaskWaitingOnHimIsInTheOneList(unittest.TestCase):
    def test_a_task_waiting_on_him_is_a_row(self):
        with mock.patch("aletheia.tasks.all_tasks", lambda: [_task()]):
            rows = needs_you.items(sources={"task": needs_you._tasks})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind"], "task")
        self.assertIn("I did it", row["how"])
        for field in ("what", "why", "if_ignored", "how"):
            self.assertTrue(row[field])

    def test_the_task_store_is_a_source_of_the_real_list(self):
        self.assertIn("task", needs_you.SOURCES)
        self.assertIs(needs_you.SOURCES["task"], needs_you._tasks)

    def test_a_task_waiting_on_the_world_or_a_blocker_is_not_on_him(self):
        rows = [_task(status="WAITING_EXTERNAL"), _task(id="b", status="BLOCKED"),
                _task(id="c", status="COMPLETED"), _task(id="d", status="CANCELLED")]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            self.assertEqual(needs_you.items(sources={"task": needs_you._tasks}), [])

    def test_the_row_says_what_the_capability_is_not_its_id(self):
        with mock.patch("aletheia.tasks.all_tasks", lambda: [_task()]):
            rows = needs_you.items(sources={"task": needs_you._tasks})
        self.assertNotIn("reservation.book", rows[0]["what"])
        self.assertEqual(rows[0]["what"], speech.say_capabilities(_task()["description"]))


class TheCardSaysItInWords(unittest.TestCase):
    def test_the_card_title_and_need_carry_no_capability_id(self):
        card = mc.task_mission(_task())
        self.assertEqual(card["status"], "NEEDS YOU")
        self.assertNotIn("reservation.book", card["title"])
        self.assertNotIn("reservation.book", card["needs"][0]["said"])
        self.assertEqual(card["title"], speech.say_capabilities(_task()["description"]))

    def test_the_card_and_the_list_agree_on_what_waits(self):
        """Whatever the card says needs him, the list says too."""
        with mock.patch("aletheia.tasks.all_tasks", lambda: [_task()]):
            rows = needs_you.items(sources={"task": needs_you._tasks})
        card = mc.task_mission(_task())
        self.assertEqual(rows[0]["what"].rstrip("."), card["needs"][0]["said"].rstrip("."))


class AVerifiedCapabilityWaitsOnARealUseNotOnHim(unittest.TestCase):
    """The record on his PC, written before 2026-09-24, says WAITING_OPERATOR.
    Both readers read it as waiting on the world, so neither can say
    "needs you" about it again."""

    def verified(self) -> dict:
        return _task(id="verify-reservation-book", description="Verify or repair capability reservation.book",
                     result="its tests pass here; live evidence needs a live booking round-trip")

    def test_the_effective_status_is_the_worlds(self):
        self.assertEqual(tasks.effective_status(self.verified()), "WAITING_EXTERNAL")
        self.assertEqual(tasks.effective_status(_task()), "WAITING_OPERATOR")
        self.assertEqual(tasks.effective_status(self.verified() | {"status": "COMPLETED"}), "COMPLETED")

    def test_it_is_not_in_the_list_and_its_card_is_waiting_with_no_button(self):
        with mock.patch("aletheia.tasks.all_tasks", lambda: [self.verified()]):
            self.assertEqual(needs_you.items(sources={"task": needs_you._tasks}), [])
        card = mc.task_mission(self.verified())
        self.assertEqual(card["status"], "WAITING")
        self.assertEqual(card["needs"], [])
        self.assertFalse(card.get("action"))
        self.assertNotIn("reservation.book", card["title"])


if __name__ == "__main__":
    unittest.main()
