""""I need to buy milk, eggs and coffee" became a task called that, and "what
do I need from the store" then said the shopping list was empty (2026-10-16,
every model off). "What's tonight look like" went to a model."""
import unittest
from unittest import mock

from aletheia import calendar as cal, quick, voice


class AListOfThingsIsTheShoppingList(unittest.TestCase):
    def _cmd(self, said):
        return voice.interpret(said)["command"]

    def test_a_list_he_needs_to_buy(self):
        self.assertEqual(self._cmd("I need to buy milk, eggs and coffee"),
                         {"kind": "shopping_add", "item": "milk, eggs and coffee"})

    def test_a_list_he_is_out_of(self):
        self.assertEqual(self._cmd("we're out of milk, bread and butter")["kind"], "shopping_add")

    def test_groceries_to_pick_up(self):
        self.assertEqual(self._cmd("i need to pick up eggs, bread, and paper towels")["kind"], "shopping_add")

    def test_errands_to_pick_up_are_not_groceries(self):
        self.assertNotEqual(self._cmd("i need to pick up the kids, dry cleaning and milk")["kind"], "shopping_add")

    def test_a_list_with_a_job_in_it_is_not_a_list(self):
        self.assertNotEqual((self._cmd("i need to get milk, then call mom") or {}).get("kind"), "shopping_add")


class TonightLooksLike(unittest.TestCase):
    def test_the_phrasings(self):
        for said in ("what's tonight look like", "what does tonight look like",
                     "how's tonight looking", "what's my night look like"):
            with self.subTest(said=said), mock.patch.object(cal, "all_events", return_value=[]), \
                    mock.patch.object(quick, "_reminders_in_part", return_value=""):
                self.assertEqual(quick.answer(said), "Nothing on your calendar tonight.")

    def test_the_evening(self):
        with mock.patch.object(cal, "all_events", return_value=[]), \
                mock.patch.object(quick, "_reminders_in_part", return_value=""):
            self.assertEqual(quick.answer("how's my evening looking"), "Nothing on your calendar this evening.")


if __name__ == "__main__":
    unittest.main()
