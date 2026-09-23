"""On his PC, 2026-09-23, the local-run ring showed his resume's first line
over and over: every campaign batch asked a model to read the same document
(300-500 s of her own model each time when the frontier was out) for fields
the profile already held, and asked again which roles it points at. A
resume she has learned is not read again; the roles a model read off it are
kept by its hash."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import campaign


class LearnOnceCase(unittest.TestCase):
    def test_no_model_when_every_learnable_field_is_known(self):
        have = {f: "x" for f in campaign.LEARNABLE if f != "website"}
        with mock.patch("aletheia.profile.known", return_value=have), \
             mock.patch("aletheia.campaign._job_hunt_thinker") as thinker:
            out = campaign.learn_more("CALEB SCHULTE ...")
        thinker.assert_not_called()
        self.assertEqual(out, {})

    def test_a_model_is_asked_when_something_is_missing(self):
        have = {"first_name": "Caleb"}
        asked = mock.Mock(return_value={"school": "SDSU"})
        with mock.patch("aletheia.profile.known", return_value=have), \
             mock.patch("aletheia.profile.set_answer") as set_answer:
            out = campaign.learn_more("...", think=asked)
        asked.assert_called_once()
        self.assertEqual(out, {"school": "SDSU"})
        set_answer.assert_called_once()


class RolesOnceCase(unittest.TestCase):
    def setUp(self):
        campaign.forget_roles()

    def test_roles_read_off_a_resume_are_kept_by_its_hash(self):
        text = "Operations analyst with five years..."
        think = mock.Mock(return_value={"roles": ["Operations Analyst", "Business Analyst"]})
        with mock.patch("aletheia.profile.known", return_value={}), \
             mock.patch("aletheia.job_fit.preferences", return_value=([], [])), \
             mock.patch("aletheia.job_fit.unwanted_reason", return_value=""):
            first = campaign.roles_for(text, think=think)
            second = campaign.roles_for(text, think=think)
        self.assertEqual(first, second)
        self.assertEqual(think.call_count, 1)
        self.assertEqual(campaign.roles_remembered(text), first)
        self.assertIsNone(campaign.roles_remembered("a different resume"))


if __name__ == "__main__":
    unittest.main()
