"""The roles come off his resume (campaign.roles_for), so "add Sales Engineer
to the roles" had nowhere to go (open item, morning report 2026-09-23). A
role he names is one line in his profile and is hunted for beside the
resume's - never twice, never work he refused."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import campaign, profile, voice


class TheSentences(unittest.TestCase):
    def test_add_and_also_look_for(self):
        for said, value in (("add Sales Engineer to the roles", "sales engineer"),
                            ("add solutions consultant to my roles", "solutions consultant"),
                            ("put account executive on the list of roles", "account executive"),
                            ("also look for sales engineer jobs", "sales engineer"),
                            ("and also apply to implementation specialist roles", "implementation specialist")):
            with self.subTest(said=said):
                out = voice.interpret(said)
                self.assertEqual(out["command"]["kind"], "preference_set", out)
                self.assertEqual(out["command"]["field"], "roles_added")
                self.assertEqual(out["command"]["value"], value)

    def test_other_sentences_are_left_alone(self):
        for said in ("add milk to the list", "also look for the cat", "add a task to call the dentist",
                     "only apply to remote jobs"):
            with self.subTest(said=said):
                cmd = voice.interpret(said).get("command") or {}
                self.assertNotEqual(cmd.get("field"), "roles_added", cmd)


class TheHunt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(profile, "path", lambda: d / "answers.json")
        p.start(); self.addCleanup(p.stop)

    def test_the_role_accumulates_and_is_read_back(self):
        self.assertEqual(profile.steer_by("roles_added", "Sales Engineer"),
                         "Besides what your resume is for, I'll hunt for Sales Engineer.")
        self.assertEqual(profile.steer_by("roles_added", "sales engineer"),
                         "Besides what your resume is for, I'll hunt for Sales Engineer.", "a repeat is not said twice")
        profile.steer_by("roles_added", "Solutions Consultant")
        self.assertEqual(profile.roles_added(), ["Sales Engineer", "Solutions Consultant"])
        self.assertIn("roles you added: Sales Engineer; Solutions Consultant", profile.preferences_words())

    def test_the_resumes_roles_plus_his(self):
        profile.steer_by("roles_added", "Sales Engineer")
        with mock.patch.object(campaign, "roles_remembered", return_value=["Account Manager", "Sales Engineer"]):
            roles = campaign.roles_for("resume text", think=lambda *a, **k: {"roles": ["Account Manager"]})
        self.assertEqual(roles, ["Account Manager", "Sales Engineer"], "never twice")

    def test_his_role_alone_when_the_resume_says_nothing(self):
        profile.steer_by("roles_added", "Sales Engineer")
        with mock.patch.object(campaign, "roles_remembered", return_value=[]):
            self.assertEqual(campaign.roles_for("resume text", think=False), ["Sales Engineer"])

    def test_work_he_refused_is_not_hunted_for_however_he_names_it(self):
        profile.steer_by("work_not_wanted", "sales")
        profile.steer_by("roles_added", "Sales Development Representative")
        with mock.patch.object(campaign, "roles_remembered", return_value=["Account Manager"]):
            roles = campaign.roles_for("resume text", think=lambda *a, **k: {"roles": ["Account Manager"]})
        self.assertEqual(roles, ["Account Manager"])


if __name__ == "__main__":
    unittest.main()
