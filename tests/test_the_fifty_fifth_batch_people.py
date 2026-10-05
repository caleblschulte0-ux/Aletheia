"""Fifty-fifth sandbox batch, 2026-10-05: people and contacts.

    > add Dana to my contacts her number is 000 555 0100   "Saved add Dana to my contacts her: 000 555 0100."
    > who do I know / how many contacts do I have          a model each
    > delete Dana from my contacts                         [6.0s] a plan, an approval
    > what do you know about Dana                          "people: landlord is Dana"
    > Dana's birthday is March 3                           [6.0s] a plan, an approval
    > when's Dana's birthday / how many days until Dana's birthday   a model each, "still waiting on your approval"
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import contacts, intercom, localtime, memory, quick, voice


class People(unittest.TestCase):
    def test_a_contact_added_by_the_sentence_he_says(self):
        self.assertEqual(voice.interpret("thea add Dana to my contacts her number is 000 555 0100")["command"],
                         {"kind": "contact_add", "name": "Dana", "phone": "000 555 0100"})
        self.assertEqual(voice.interpret("thea put Sam in my contacts, email sam@example.com")["command"],
                         {"kind": "contact_add", "name": "Sam", "email": "sam@example.com"})
        self.assertEqual(voice.interpret("thea delete Dana from my contacts")["command"],
                         {"kind": "forget", "about": "Dana", "domain": "contacts"})

    def test_removing_a_contact_leaves_what_she_remembers_alone(self):
        self.addCleanup(memory.forget, "people", "landlord")
        intercom.execute_command({"kind": "remember", "domain": "people", "key": "landlord", "value": "Dana"}, "q")
        row = {"id": "c-dana", "display_name": "Dana", "emails": [], "phones": ["000 555 0100"], "aliases": []}
        with mock.patch.object(contacts, "all_contacts", return_value=[row]), \
                mock.patch.object(contacts, "forget", return_value=row) as gone:
            said = intercom.execute_command({"kind": "forget", "about": "Dana", "domain": "contacts"}, "q")
        self.assertTrue(said.startswith("Forgotten: Dana (0"), said)
        gone.assert_called_once_with("c-dana")
        self.assertEqual(memory.recall("people", "landlord"), "Dana")
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            self.assertEqual(intercom.execute_command({"kind": "forget", "about": "Sam", "domain": "contacts"}, "q"), "No contact called Sam.")
        for said in ("who do I know", "how many contacts do I have", "who have I saved"):
            self.assertEqual(quick.match(said)[0], "contacts_all", said)

    def test_what_she_knows_about_somebody_is_a_sentence(self):
        self.addCleanup(memory.forget, "people", "landlord")
        intercom.execute_command({"kind": "remember", "domain": "people", "key": "landlord", "value": "Dana"}, "q")
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            said = intercom.execute_command({"kind": "recall", "about": "Dana"}, "q")
        self.assertNotIn("people:", said)
        self.assertIn("landlord", said)
        self.assertTrue(said[0].isupper() and said.endswith("."), said)
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            said = intercom.execute_command({"kind": "recall", "about": "landlord"}, "q")
        self.assertEqual(said, "Your landlord is Dana.")

    def test_somebody_elses_birthday_is_a_note_she_reads_back(self):
        self.assertEqual(voice.interpret("thea Dana's birthday is March 3")["command"],
                         {"kind": "note", "text": "Dana's birthday is March 3"})
        self.assertNotEqual(voice.interpret("thea when's Dana's birthday")["command"].get("kind"), "note")
        rows = [{"text": "Dana's birthday is March 3"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            when = quick._birthday_of("dana")
            self.assertEqual((when.month, when.day), (3, 3))
            self.assertGreaterEqual(when, localtime.today())
            self.assertEqual(quick.match("when's Dana's birthday")[0], "recall")
            self.assertIn("Dana's birthday is March 3", quick.answer("when's Dana's birthday"))
            said = quick.answer("how many days until Dana's birthday")
            self.assertRegex(said, r"^\d+ days? - \w+ 3 March\.$")
            with mock.patch.object(quick, "_a_name_in", return_value="dana"):
                d = voice.interpret("thea remind me to call Dana on her birthday")
            self.assertEqual(d["command"]["kind"], "remind_at")
            self.assertEqual(d["command"]["text"], "call Dana")
            self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]).date(), when)
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("I don't have Dana's birthday", quick.answer("how many days until Dana's birthday"))


if __name__ == "__main__":
    unittest.main()
