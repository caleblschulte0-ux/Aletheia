"""Twenty-seventh sandbox batch, 2026-10-05: subscriptions, people, and "I meant".

    > what's my biggest subscription        [5.6s] a model
    > how much do I pay a year ...          [4.1s] a model
    > when is spotify due                   "I have nothing about spotify on file" - the notes
    > what do I pay for weekly              "Weekly isn't on your subscriptions list"
    > remember Dana is my landlord          "Noted." - then "who is my landlord": nobody
    > who is Dana                           [4.1s] a model
    > what's Dana's number                  "Your Dana's number is ..."
    > no I meant the electrician            [6.0s] the planner, two steps, an approval
"""
import unittest
from unittest import mock

from aletheia import intercom, memory, quick, tasks, voice

ROWS = [{"merchant": "spotify", "amount": 9.99, "cadence": "monthly", "status": "ACTIVE"},
        {"merchant": "amazon prime", "amount": 120.0, "cadence": "annual", "status": "ACTIVE"}]


class Subscriptions(unittest.TestCase):
    def test_biggest_year_cadence_and_due(self):
        with mock.patch("aletheia.subscriptions.all_subscriptions", return_value=ROWS):
            self.assertEqual(quick.answer("what's my biggest subscription"),
                             "The biggest: amazon prime at $120.00 a year, then spotify at $9.99 a month.")
            self.assertEqual(quick.answer("which one costs the least"),
                             "The cheapest: spotify at $9.99 a month, then amazon prime at $120.00 a year.")
            self.assertTrue(quick.answer("how much do i pay a year for subscriptions").startswith("About $239.88 a year"))
            self.assertTrue(quick.answer("how much do i spend a month on subscriptions").startswith("About $19.99 a month"))
            self.assertEqual(quick.answer("what do i pay for weekly"), "Nothing weekly on your subscriptions list.")
            self.assertEqual(quick.answer("what do i pay for yearly"), "Yearly: amazon prime at $120.00.")
            self.assertEqual(quick.answer("when is spotify due"),
                             "You pay $9.99 a month for spotify. I don't have its charge date - tell me and I'll keep it.")


class People(unittest.TestCase):
    def test_the_fact_is_about_the_landlord_whichever_side_the_name_is_on(self):
        self.assertEqual(memory.parse_fact("remember Dana is my landlord"),
                         {"subject": "landlord", "key": "landlord", "value": "Dana", "domain": "people", "mine": True})
        self.assertEqual(voice.interpret("remember Dana is my landlord")["command"]["key"], "landlord")
        # and the plain shape is untouched
        self.assertEqual(memory.parse_fact("remember my landlord is Dana")["value"], "Dana")

    def test_who_is_reads_the_shelf_and_the_contacts(self):
        with mock.patch("aletheia.memory.everything", return_value={"people": {"landlord": {"value": "Dana", "about": "your landlord"}}}), \
             mock.patch("aletheia.contacts.all_contacts", return_value=[{"id": "dana", "display_name": "Dana", "phones": ["0005550199"], "emails": []}]):
            self.assertEqual(quick.answer("who is dana"), "Dana is your landlord; number 000 555 0199.")
            self.assertTrue(quick.answer("who is pat").startswith("I don't have anyone called Pat on file."))
        self.assertEqual(quick.match("who is my landlord")[0], "person")

    def test_a_named_person_owns_their_number(self):
        with mock.patch("aletheia.contacts.all_contacts", return_value=[{"id": "dana", "display_name": "Dana", "phones": ["0005550199"], "emails": []}]):
            self.assertEqual(intercom._contacts_answer("dana"), "Dana's number is 000 555 0199.")


class IMeant(unittest.TestCase):
    def test_the_last_words_are_swapped_and_the_old_task_replaced(self):
        turns = [{"he_asked": "add a task to call the plumber", "she_answered": "Added a task: call the plumber.", "how": "stores"}]
        with mock.patch("aletheia.converse.recent", return_value=turns):
            out = voice.interpret("no I meant the electrician")["command"]
        self.assertEqual(out["description"], "call the electrician")
        self.assertEqual(out["replaces"], "call the plumber")
        self.assertIn("replaces", intercom.KIND_ARGS["task_new"][1])
        import uuid
        tag = uuid.uuid4().hex[:6]
        tasks.create(f"call-the-plumber-{tag}", "call the plumber")
        said = intercom.execute_command({"kind": "task_new", "id": f"call-the-electrician-{tag}", "description": "call the electrician",
                                         "replaces": "call the plumber"}, {"repos": {}})
        self.assertIn("instead of call the plumber", said)
        # The open "call the plumber" is gone - whichever one it was, if a
        # previous run of this suite left one behind.
        still_open = [x for x in tasks.all_tasks() if x.get("description") == "call the plumber"
                      and x.get("status") not in ("CANCELLED", "COMPLETED", "FAILED_TERMINAL")]
        self.assertFalse(still_open, still_open)

    def test_nothing_to_swap_goes_on_to_the_planner(self):
        with mock.patch("aletheia.converse.recent", return_value=[{"he_asked": "what time is it", "she_answered": "9 am.", "how": "stores"}]):
            self.assertEqual(voice.interpret("no I meant the electrician")["command"]["kind"], "intent")


if __name__ == "__main__":
    unittest.main()
