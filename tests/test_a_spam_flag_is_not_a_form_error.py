"""A site that refuses the SENDER is not a site asking for a correction.

Live 2026-09-24, Ashby (Notion, CareerSwift): the press came back with
"We couldn't submit your application. Your application submission was
flagged as possible spam." She recorded it as "read what it wants and I
will fix it and try again" — a promise about a correction that does not
exist, and a re-read pass would have pressed the same form at the same
guard. The refusal is real and it is hers to say plainly: nothing on the
form was wrong, pressing again will not help, and this one is his to send
by hand if he wants it.
"""
from __future__ import annotations

import unittest

from aletheia import browse, campaign

ASHBY = ("We couldn't submit your application Your application submission was flagged "
         "as possible spam. If you believe this is an error, please contact support.")


class ASpamFlagIsSaidForWhatItIs(unittest.TestCase):
    def test_the_verdict_is_a_refusal_that_names_the_guard_not_the_form(self):
        out = browse.read_outcome("Apply for this job\n" + ASHBY, did="submit",
                                  form_still_there=True, complaints=[ASHBY])
        self.assertEqual(out["verdict"], "rejected")
        self.assertTrue(out.get("spam"))
        self.assertIn("possible spam", out["note"])
        self.assertNotIn("I will fix it", out["note"])
        self.assertIn("by hand", out["note"])

    def test_the_body_alone_is_enough_when_the_complaint_box_was_not_read(self):
        out = browse.read_outcome("Something went wrong.\n" + ASHBY, did="submit", form_still_there=True)
        self.assertTrue(out.get("spam"))

    def test_an_ordinary_complaint_is_still_a_correction_she_offers_to_make(self):
        out = browse.read_outcome("Phone must be 10 digits", did="submit", form_still_there=True,
                                  complaints=["Phone must be 10 digits"])
        self.assertEqual(out["verdict"], "rejected")
        self.assertFalse(out.get("spam"))
        self.assertIn("I will fix it", out["note"])

    def test_a_spam_refusal_is_never_re_staged_to_press_the_same_guard_again(self):
        record = {"id": "apply-b1ca106a", "state": "REJECTED",
                  "failure": "the site refused it: " + browse.SPAM_FLAG_NOTE, "stagings": 0}
        self.assertFalse(campaign.refused_submit(record))


if __name__ == "__main__":
    unittest.main()
