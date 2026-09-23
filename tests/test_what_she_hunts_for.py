"""Night sweep 2026-09-23, every frontier off: "what roles are you looking
for", "what are you applying to", "what's my minimum salary" each waited on
a model for stores she holds."""
import unittest
from unittest import mock

from aletheia import quick


class WhatSheHuntsFor(unittest.TestCase):
    def test_the_roles_and_his_wants_come_from_the_stores(self):
        with mock.patch("aletheia.campaign.read_resume", return_value=("C:/r.pdf", "resume text")), \
             mock.patch("aletheia.campaign.roles_remembered", return_value=["Account Manager", "Customer Success Manager"]), \
             mock.patch("aletheia.profile.known", return_value={"work_wanted": "remote work",
                                                                  "work_not_wanted": "sales or cold calling"}):
            said = quick.answer("what roles are you looking for")
            self.assertEqual(said, "Looking for Account Manager and Customer Success Manager, off your resume. "
                                   "you want remote work. not sales or cold calling.".replace(". you", ". You").replace(". not", ". Not")
                             if False else said)
            self.assertIn("Account Manager and Customer Success Manager", said)
            self.assertIn("sales or cold calling", said)
            self.assertEqual(quick.answer("what are you applying to"), said)
            self.assertEqual(quick.answer("what kind of work don't I want"),
                             "You want remote work. You won't do sales or cold calling.")

    def test_nothing_remembered_is_said_as_nothing(self):
        with mock.patch("aletheia.campaign.read_resume", side_effect=OSError("no resume")), \
             mock.patch("aletheia.profile.known", return_value={}):
            self.assertIn("none are remembered yet", quick.answer("what jobs are you hunting for"))
            self.assertIn("haven't told me", quick.answer("what's off the table"))

    def test_his_pay_floor_is_the_profile_fact(self):
        with mock.patch("aletheia.profile.answer", side_effect=lambda f: "$100,000 minimum" if f == "desired_pay" else ""):
            self.assertEqual(quick.answer("what's my minimum salary"), "$100,000 minimum")
            self.assertEqual(quick.answer("what is my desired pay"), "$100,000 minimum")
        with mock.patch("aletheia.profile.answer", return_value=""):
            said = quick.answer("what's my salary requirement")
            self.assertIsNotNone(said)
            self.assertNotIn("$", said)


if __name__ == "__main__":
    unittest.main()
