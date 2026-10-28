""""Forget Jake's number" said she had nothing about it while "what's Jake's
number" still read it from his contacts, and "cancel my 3 o'clock on thursday"
went to the planner though "cancel my 3 o'clock" worked (2026-10-28)."""
import unittest
from unittest import mock

from aletheia import contacts, intercom, voice


class ForgettingAContactsNumber(unittest.TestCase):
    def setUp(self):
        self.person = {"version": 1, "id": "jake", "display_name": "Jake", "phones": ["605-555-1234"],
                       "emails": ["jake@example.com"], "aliases": [], "organizations": [], "tags": [],
                       "created_at": "2026-10-28T00:00:00Z", "updated_at": "2026-10-28T00:00:00Z"}
        self.updated = {}
        patches = [mock.patch.object(contacts, "all_contacts", return_value=[self.person]),
                   mock.patch.object(contacts, "update", side_effect=lambda cid, **ch: self.updated.update(ch)),
                   mock.patch.object(intercom, "_remembered_matching", return_value=[]),
                   mock.patch.object(intercom, "_forget_note", return_value="")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def forget(self, about):
        return intercom.execute_command({"kind": "forget", "about": about}, {}, quote="forget")

    def test_the_number_goes_and_the_person_stays(self):
        said = str(self.forget("Jake's number"))
        self.assertEqual(self.updated, {"phones": []})
        self.assertIn("Forgotten Jake's number", said)
        self.assertIn("still in your contacts", said)

    def test_the_email_goes_on_its_own(self):
        self.forget("jake's email address")
        self.assertEqual(self.updated, {"emails": []})

    def test_somebody_not_in_contacts_is_still_nothing(self):
        said = str(self.forget("Sam's number"))
        self.assertEqual(self.updated, {})
        self.assertIn("nothing remembered", said)


class CancellingAHoldByTimeAndDay(unittest.TestCase):
    def test_the_day_is_allowed(self):
        hold = {"title": "haircut", "start": "2026-10-29T20:00:00+00:00"}
        seen = []
        def one(words):
            seen.append(words)
            return hold, ""
        with mock.patch.object(voice, "_one_of_her_holds", one):
            for sentence in ("cancel my 3 o'clock on thursday", "cancel my 3pm thursday", "clear thursday at 3"):
                got = voice._interpret(sentence)
                self.assertEqual(got["command"], {"kind": "hold_release", "title": "haircut", "start": hold["start"]}, sentence)
        self.assertIn("3 on thursday", seen[-1])


if __name__ == "__main__":
    unittest.main()
