"""She added milk to a list she then said she did not have.

    > add milk to my shopping list
      Added to the shopping list: milk.
    > what's on my shopping list
      I don't have a shopping list stored anywhere I can check.

One turn apart. `shopping_add` shipped with no way to READ the store and
no way to take anything off it, so the only honest half of the exchange
was the first one — and the second was worse than an error, because it
tells him to go and keep the list somewhere else.
"""
import unittest
from unittest import mock

from aletheia import act, intercom, shopping, speech, voice


def item(need, state="RESEARCHING", wid=None):
    return {"id": wid or "shop-" + need.replace(" ", "-"), "need": need,
            "state": state,
            "created_at": "2026-09-07T00:00:00Z"}


class HeCanAskForTheList(unittest.TestCase):
    def test_the_question_is_deterministic(self):
        for said in ("what's on my shopping list", "shopping list",
                     "what do I need from the store", "read my shopping list"):
            self.assertEqual(voice.interpret(said)["command"],
                             {"kind": "shopping_list"}, said)

    def test_taking_something_off_is_heard(self):
        self.assertEqual(voice.interpret("take milk off my shopping list")["command"],
                         {"kind": "shopping_off", "item": "milk"})
        self.assertEqual(voice.interpret("remove the eggs from the shopping list")["command"],
                         {"kind": "shopping_off", "item": "the eggs"})

    def test_adding_still_adds(self):
        # The read patterns run first; "add milk to my shopping list" must
        # not be swallowed by them.
        self.assertEqual(voice.interpret("add milk to my shopping list")["command"],
                         {"kind": "shopping_add", "item": "milk"})

    def test_reading_is_read_only_and_removing_is_routine(self):
        self.assertIn("shopping_list", intercom.READ_ONLY_KINDS)
        self.assertIn("shopping_off", intercom.ROUTINE_KINDS)


class TheStoreAnswers(unittest.TestCase):
    def run_it(self, cmd):
        return intercom.execute_command(cmd, {})

    def test_an_empty_list_says_so_without_denying_the_list(self):
        with mock.patch.object(shopping, "all_workflows", return_value=[]):
            self.assertEqual(self.run_it({"kind": "shopping_list"}),
                             "Nothing on your shopping list.")

    def test_it_reads_back_what_was_added(self):
        with mock.patch.object(shopping, "all_workflows",
                               return_value=[item("milk"), item("bread")]):
            said = self.run_it({"kind": "shopping_list"})
        self.assertIn("2 things on your shopping list", said)
        self.assertIn("milk and bread", said)

    def test_something_already_bought_is_not_still_on_the_list(self):
        rows = [item("milk"), item("a monitor", state="ORDERED"),
                item("old thing", state="CANCELLED")]
        with mock.patch.object(shopping, "all_workflows", return_value=rows):
            said = self.run_it({"kind": "shopping_list"})
        self.assertIn("1 thing", said)
        self.assertNotIn("monitor", said)

    def test_removing_cancels_and_never_deletes(self):
        with mock.patch.object(shopping, "all_workflows", return_value=[item("milk")]), \
             mock.patch.object(shopping, "cancel") as cancel:
            said = self.run_it({"kind": "shopping_off", "item": "milk"})
        cancel.assert_called_once_with("shop-milk")
        self.assertEqual(speech.spoken_receipt("shopping_off", said),
                         "Took it off your shopping list: milk.")

    def test_two_that_match_is_a_question(self):
        rows = [item("milk"), item("milk chocolate")]
        with mock.patch.object(shopping, "all_workflows", return_value=rows):
            with self.assertRaises(act.Refused) as caught:
                self.run_it({"kind": "shopping_off", "item": "milk"})
        self.assertIn("Which one", str(caught.exception))
        self.assertIn(" or ", str(caught.exception))

    def test_something_not_on_the_list_is_refused_in_words(self):
        with mock.patch.object(shopping, "all_workflows", return_value=[item("milk")]):
            with self.assertRaises(act.Refused) as caught:
                self.run_it({"kind": "shopping_off", "item": "a canoe"})
        self.assertIn("shopping list", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
