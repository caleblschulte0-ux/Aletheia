"""Twenty-second sandbox batch, 2026-10-05: small talk about the turn before,
and two lies.

    > do you have access to my bank     [10.0s] "Read-only, yes. I can see your
                                        balances" - there is no bank data
    > can you drive                     "Yes — Private vehicle facts, odometer..."
    > what are you bad at               read as a project called "are you bad"
    > why did you do that               [9.0s] a model, inventing "the only
                                        thing I've done in the last week"
    > are you sure                      [10.6s] a model, "I shouldn't have said that"
    > forget everything about my sister "I have nothing remembered about
                                        everything about my sister."
    > who made you                      [5.5s] a model
"""
import unittest
from unittest import mock

from aletheia import converse, intercom, quick

VEHICLE = {"capability": "vehicle.facts", "status": "AVAILABLE",
           "what_it_is": "Private vehicle facts, odometer and maintenance due calculations."}
BOOKING = {"capability": "reservation.book", "status": "EXPERIMENTAL",
           "what_it_is": "Book or cancel a live external reservation."}
MONEY = {"capability": "money.move", "status": "NOT_BUILT",
         "what_it_is": "Move money, pay bills or trade assets."}


class AMatchThatNeverSaysHisVerb(unittest.TestCase):
    def test_can_you_drive_is_a_no_with_the_closest_thing(self):
        with mock.patch("aletheia.self_knowledge.for_question", return_value={"matches": [VEHICLE]}):
            said = quick.answer("can you drive")
        self.assertTrue(said.startswith("No - I can't drive. The closest thing I do is private vehicle facts"), said)

    def test_a_match_that_says_his_verb_still_answers_yes(self):
        with mock.patch("aletheia.self_knowledge.for_question", return_value={"matches": [BOOKING]}):
            said = quick.answer("can you book flights")
        self.assertTrue(said.startswith("Yes, but it is experimental"), said)

    def test_access_to_the_bank_is_no(self):
        with mock.patch("aletheia.self_knowledge.for_question", return_value={"matches": [MONEY]}):
            said = quick.answer("do you have access to my bank")
            see = quick.answer("can you see my bank account")
        self.assertTrue(said.startswith("No - I have no access to your bank."), said)
        self.assertNotIn("Read-only", said)
        self.assertTrue(see.startswith("No - I have no access to your bank account."), see)

    def test_bad_at_is_the_honesty_question_not_a_project(self):
        self.assertEqual(quick.match("what are you bad at")[0], "cannot")
        self.assertEqual(quick.match("what are your limits")[0], "cannot")
        self.assertEqual(quick.match("what's barkly up to")[0], "project_of")


class TheTurnBefore(unittest.TestCase):
    def test_why_names_his_sentence(self):
        with mock.patch("aletheia.converse.recent", return_value=[
                {"he_asked": "add a task to call the plumber", "she_answered": "Added a task: call the plumber.", "how": "stores"}]), \
             mock.patch("aletheia.recollection.day", return_value=[{"what": "Added a task: call the plumber", "at": "x"}]):
            self.assertEqual(quick.answer("why did you do that"),
                             'Because you said "add a task to call the plumber" - so I did: added a task: call the plumber.')
        with mock.patch("aletheia.recollection.day", return_value=[]):
            self.assertEqual(quick.answer("why did you do that"), "I haven't done anything today to explain.")

    def test_sure_reads_where_the_answer_came_from(self):
        with mock.patch("aletheia.converse.recent", return_value=[{"he_asked": "x", "she_answered": "Added a task: call the plumber.", "how": "stores"}]):
            self.assertEqual(quick.answer("are you sure"),
                             "Yes - that came straight from my own records, not a guess: Added a task: call the plumber.")
        with mock.patch("aletheia.converse.recent", return_value=[{"he_asked": "x", "she_answered": "Probably.", "how": "model"}]):
            self.assertIn("came from a model", quick.answer("are you sure"))
        with mock.patch("aletheia.converse.recent", return_value=[{"he_asked": "x", "she_answered": "Probably.", "how": ""}]):
            self.assertIn("don't have a record of where", quick.answer("really"))

    def test_the_thread_keeps_how_a_turn_was_answered(self):
        converse.forget()
        converse.remember_exchange("add a task", "Added a task.", how="stores")
        converse.remember_exchange("why", "Because.", how="model")
        turns = converse.recent(limit=2)
        self.assertEqual([t["how"] for t in turns], ["stores", "model"])
        converse.forget()

    def test_who_made_her_is_a_fact_not_a_model(self):
        self.assertTrue(quick.answer("who made you").startswith("You did."))


class ForgetEverythingAbout(unittest.TestCase):
    def test_the_receipt_uses_his_phrase(self):
        from aletheia import memory
        memory.remember("people", "sister_birthday", "March 3rd", source="test", about="your sister's birthday")
        said = intercom.execute_command({"kind": "forget", "about": "everything about my sister"}, {"repos": {}})
        self.assertEqual(said, "Forgotten: your sister's birthday, which was March 3rd.")


    def test_the_lead_words_come_off(self):
        with mock.patch("aletheia.memory.everything", return_value={"people": {"sister_birthday": {"value": "March 3rd"}}}), \
             mock.patch("aletheia.memory._load", return_value={"sister_birthday": {"value": "March 3rd"}}):
            hits = intercom._remembered_matching("everything about my sister")
        self.assertTrue(any(h[1] == "sister_birthday" for h in hits), hits)


if __name__ == "__main__":
    unittest.main()
