"""Night sweep 2026-09-23, every frontier off: "only apply to remote jobs",
"don't apply to part-time jobs", "raise my minimum salary to 110k" each went
to a planner nobody could run - for a store one line of his settles. A
sentence about what he wants, will not do, wants to be paid, or when he
could start is one line in his profile (preference_set), read back the same
way (preferences), and never a mission's to change."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agenda, intercom, profile, tools, voice


class TheSentencesAreHisProfile(unittest.TestCase):
    def test_the_voice_shapes(self):
        for said, field, value in (
                ("only apply to remote jobs", "work_wanted", "only remote jobs"),
                ("thea only look for customer success roles", "work_wanted", "only customer success roles"),
                ("don't apply to part-time jobs", "work_not_wanted", "part-time jobs"),
                ("no more cold calling jobs", "work_not_wanted", "cold calling"),
                ("never apply to sales roles", "work_not_wanted", "sales roles"),
                ("raise my minimum salary to 110k", "desired_pay", "110k"),
                ("my minimum pay is $95,000", "desired_pay", "$95,000"),
                ("I can start in two weeks", "notice_period", "in two weeks")):
            with self.subTest(said=said):
                out = voice.interpret(said)
                self.assertEqual(out["command"]["kind"], "preference_set", out)
                self.assertEqual(out["command"]["field"], field)
                self.assertEqual(out["command"]["value"].casefold(), value.casefold())

    def test_the_reader_has_a_sentence(self):
        for said in ("what do you steer by", "what are my job preferences", "what have I told you to avoid"):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(said)["command"], {"kind": "preferences"})

    def test_stopping_the_hunt_is_not_a_preference(self):
        for said in ("stop applying to jobs", "stop applying for today"):
            with self.subTest(said=said):
                self.assertNotEqual(voice.interpret(said)["command"].get("kind"), "preference_set")


class TheStoreAndItsReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(profile, "path", lambda: d / "answers.json")
        p.start(); self.addCleanup(p.stop)

    def test_the_lists_accumulate_and_the_facts_replace(self):
        self.assertEqual(profile.steer_by("work_wanted", "only remote jobs"), "From now on I'll look for only remote jobs.")
        self.assertEqual(profile.steer_by("work_not_wanted", "cold calling"), "From now on I'll leave out cold calling.")
        self.assertEqual(profile.steer_by("work_not_wanted", "part-time jobs"),
                         "From now on I'll leave out cold calling; part-time jobs.")
        self.assertEqual(profile.steer_by("work_not_wanted", "Cold calling"),
                         "From now on I'll leave out cold calling; part-time jobs.", "a repeat is not said twice")
        self.assertEqual(profile.steer_by("desired_pay", "110k"), "Your minimum pay is now 110k.")
        self.assertEqual(profile.steer_by("desired_pay", "$115,000"), "Your minimum pay is now $115,000.")
        said = profile.preferences_words()
        self.assertIn("the work you want: only remote jobs", said)
        self.assertIn("the work you won't do: cold calling; part-time jobs", said)
        self.assertIn("what you want to be paid: $115,000", said)
        with self.assertRaises(ValueError):
            profile.steer_by("email", "x@y.z")

    def test_the_command_and_its_reader_through_the_intercom(self):
        with mock.patch("aletheia.intercom.rehearsing", return_value=False):
            said = intercom.execute_command({"kind": "preference_set", "field": "work_wanted", "value": "only remote jobs"}, {})
            self.assertEqual(said, "From now on I'll look for only remote jobs.")
            self.assertIn("only remote jobs", intercom.execute_command({"kind": "preferences"}, {}))
            with self.assertRaises(Exception):
                intercom.execute_command({"kind": "preference_set", "field": "email", "value": "x"}, {})

    def test_the_grammar_knows_it_and_a_mission_may_not(self):
        self.assertEqual(sorted(intercom.allowed_values("preference_set", "field")), sorted(profile.PREFERENCE_FIELDS))
        self.assertIn("preference_set", intercom.ROUTINE_KINDS)
        self.assertIn("preferences", intercom.READ_ONLY_KINDS)
        self.assertIn("preference_set", agenda.FORBIDDEN_KINDS)
        self.assertIn("preference_set", tools.LOCAL_MODEL_WRITES)


if __name__ == "__main__":
    unittest.main()
