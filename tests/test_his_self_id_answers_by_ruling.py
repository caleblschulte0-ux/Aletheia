"""His words, 2026-10-08: "first it should try male white non hispanic not a
vetrean but if thats not on otipon or not working then we can decline to say".

Six applications were waiting on a gender, race or veteran question that day.
The ruling answers those four and nothing else: disability, orientation and
every legal declaration stay exactly where they were."""
import unittest
from unittest import mock

from aletheia import formfill, rulings


class HisSelfIdRuling(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS)
        p.start()
        self.addCleanup(p.stop)

    def pick(self, label, choices):
        return formfill.declared_choice(label, choices, stored={})

    def test_the_ruling_carries_his_words(self):
        ruling = rulings.for_switch("self_id")
        self.assertIn("male white non hispanic", rulings.quote(ruling))
        self.assertEqual(ruling["otherwise"], "decline")

    def test_his_answers_are_chosen_where_they_are_offered(self):
        self.assertEqual(self.pick("Gender", ["Male", "Female", "Decline to self-identify"]), "Male")
        self.assertEqual(self.pick("Race", ["Asian", "Black or African American", "White",
                                            "Two or More Races", "Decline to self-identify"]),
                         "White")
        self.assertEqual(self.pick("Are you Hispanic/Latino?",
                                   ["Yes", "No", "Decline to self-identify"]), "No")
        self.assertEqual(self.pick("Veteran Status",
                                   ["I am a protected veteran", "I am not a protected veteran",
                                    "I don't wish to answer"]),
                         "I am not a protected veteran")

    def test_a_list_without_his_answer_declines(self):
        self.assertEqual(self.pick("Gender identity",
                                   ["Woman", "Non-binary", "I prefer not to answer"]),
                         "I prefer not to answer")
        self.assertEqual(self.pick("Race / Ethnicity",
                                   ["Asian", "Black", "Native Hawaiian", "I decline to self-identify"]),
                         "I decline to self-identify")

    def test_with_nothing_to_decline_it_is_still_his(self):
        self.assertIsNone(self.pick("Gender", ["Woman", "Non-binary"]))

    def test_disability_and_orientation_are_not_answered_by_it(self):
        self.assertIsNone(self.pick("Disability Status",
                                    ["Yes, I have a disability", "No, I do not have a disability",
                                     "I do not want to answer"]))
        self.assertIsNone(self.pick("Sexual orientation",
                                    ["Heterosexual", "Gay", "I don't wish to answer"]))

    def test_his_own_word_at_the_keyboard_wins(self):
        stored = {"gender": {"value": "Female", "source": "operator"}}
        self.assertEqual(formfill.declared_choice("Gender", ["Male", "Female"], stored=stored),
                         "Female")

    def test_without_the_ruling_nothing_is_answered_for_him(self):
        with mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_ROOT / "nope.json"):
            self.assertIsNone(self.pick("Gender", ["Male", "Female", "Decline to self-identify"]))


if __name__ == "__main__":
    unittest.main()
