"""Eight sentences about applications and himself with every frontier off
(2026-09-22): four waited two minutes on her own model, two were answered
by her own model DENYING a store she has ("no tracker connected", "no lease
info connected"), one looked up the key "me". Every one is a record."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import quick, voice

SENT = [{"id": "apply-1", "state": "SUBMITTED", "company": "Stripe", "job_title": "Operations Analyst",
         "url": "https://x/1", "submitted_at": "2026-09-21T18:47:04Z"},
        {"id": "apply-2", "state": "SUBMITTED", "company": "Figma", "job_title": "Ops Lead",
         "url": "https://x/2", "submitted_at": "2026-09-20T12:00:00Z"},
        {"id": "apply-3", "state": "NEEDS_YOU", "company": "Brex", "job_title": "AM", "url": "https://x/3"}]


class TheRecordsAnswerCase(unittest.TestCase):
    def test_what_companies_have_i_applied_to(self):
        with mock.patch("aletheia.apply_run.all_runs", return_value=SENT):
            said = quick.answer("what companies have I applied to")
        self.assertIn("2 applications sent", said)
        self.assertIn("Stripe", said)
        self.assertIn("Figma", said)
        self.assertNotIn("Brex", said)
        with mock.patch("aletheia.apply_run.all_runs", return_value=[]):
            self.assertIn("None on record yet", quick.answer("where have I applied"))

    def test_how_many_this_week_counts_by_date(self):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        rows = [{**SENT[0], "submitted_at": (now - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                {**SENT[1], "submitted_at": "2026-01-05T12:00:00Z"}]
        with mock.patch("aletheia.apply_run.all_runs", return_value=rows):
            said = quick.answer("how many jobs did I apply to this week")
        self.assertTrue(said.startswith("1 application sent this week"), said)
        self.assertIn("Stripe", said)
        with mock.patch("aletheia.apply_run.all_runs", return_value=[]):
            self.assertEqual(quick.answer("how many applications did you send yesterday"),
                             "No applications sent yesterday.")

    def test_when_did_i_apply_to_stripe(self):
        with mock.patch("aletheia.apply_run.find", return_value=[SENT[0]]):
            said = quick.answer("when did I apply to Stripe")
        self.assertIn("Stripe", said)
        self.assertIn("sent", said)
        self.assertRegex(said, r"(?:Monday|Sunday|Tuesday)")
        with mock.patch("aletheia.apply_run.find", return_value=[]):
            self.assertIn("no application to Nowhere", quick.answer("did I apply to Nowhere yet"))

    def test_the_latest_with_a_name_is_the_record_or_nothing(self):
        with mock.patch("aletheia.pursuit.search", return_value=[]), \
             mock.patch("aletheia.apply_run.find", return_value=[SENT[0]]):
            said = quick.answer("what's the latest with Stripe")
        self.assertIn("Stripe", said)
        with mock.patch("aletheia.pursuit.search", return_value=[]), \
             mock.patch("aletheia.apply_run.find", return_value=[]):
            self.assertIsNone(quick.answer("what's the latest with the weather"))


class HisPeopleAndHimselfCase(unittest.TestCase):
    def test_who_is_my_landlord_is_remembered_or_asked(self):
        with mock.patch("aletheia.memory.recall", return_value="Dana Ruiz"):
            self.assertEqual(quick.answer("who is my landlord"), "Your landlord is Dana Ruiz.")
        with mock.patch("aletheia.memory.recall", return_value=None):
            said = quick.answer("who's my dentist")
            self.assertIn("don't have anyone remembered as your dentist", said)

    def test_what_do_you_know_about_me_is_the_whole_of_it(self):
        with mock.patch("aletheia.profile.known", return_value={"first_name": "Caleb", "city": "Hartford"}), \
             mock.patch("aletheia.memory.everything", return_value={"people": {"landlord": {"value": "Dana"}}}):
            said = quick.answer("what do you know about me")
        self.assertIn("first name: Caleb", said)
        self.assertIn("landlord: Dana", said)
        with mock.patch("aletheia.profile.known", return_value={}), \
             mock.patch("aletheia.memory.everything", return_value={}):
            self.assertIn("Nothing yet", quick.answer("what have you remembered about me"))

    def test_the_voice_layer_no_longer_looks_up_the_key_me(self):
        out = voice.interpret("thea what do you know about me")
        self.assertNotEqual((out.get("command") or {}).get("kind"), "recall")
        self.assertEqual(voice.interpret("thea tell me about Dana")["command"]["kind"], "recall")


class ReadMeTheirEmailCase(unittest.TestCase):
    def test_read_me_the_devrev_email_is_the_unread_message_that_names_them(self):
        out = voice.interpret("thea read me the DevRev email")
        self.assertEqual(out["command"], {"kind": "email_read", "which": "DevRev"})
        self.assertNotEqual((voice.interpret("thea read me the latest email").get("command") or {}).get("kind"),
                            "email_read")


if __name__ == "__main__":
    unittest.main()
