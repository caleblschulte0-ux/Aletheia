"""His Google Voice number is for making ACCOUNTS, never for applying.

His ruling, 2026-09-13, looking at the Google Voice tab:

    "They can use this Google Voice account that I have ... Don't have it
    be changing, like, anything on my resume or, like, anything like that.
    Just purely for making accounts that require a phone number. Any, like,
    application should use my actual phone number."

Two separate things keep that true, and this file holds BOTH, because one
lock is a thing somebody edits by accident:

1. `signup_phone` carries no `asks` phrases, so `formfill.match_field`
   has nothing to match a label against.
2. `match_field` skips `profile.SIGNUP_ONLY` by name, so adding `asks`
   phrases later still would not leak it.

The failure this prevents is quiet and expensive: an employer calls the
number on the application, reaches a Google Voice line he does not watch,
and he never learns the job called.
"""
from __future__ import annotations

import unittest

from aletheia import formfill, profile


class TheFieldIsMarked(unittest.TestCase):
    def test_signup_phone_exists_and_is_signup_only(self):
        self.assertIn("signup_phone", profile.FIELDS)
        self.assertIn("signup_phone", profile.SIGNUP_ONLY)

    def test_it_carries_no_asks_phrases(self):
        """The first lock: nothing for a label to match."""
        self.assertEqual(profile.FIELDS["signup_phone"]["asks"], ())

    def test_signup_only_is_derived_not_hand_kept(self):
        """A second list to remember is a second list to forget."""
        self.assertEqual(
            profile.SIGNUP_ONLY,
            frozenset(k for k, v in profile.FIELDS.items() if v.get("signup_only")))

    def test_his_real_phone_is_not_signup_only(self):
        self.assertNotIn("phone", profile.SIGNUP_ONLY)


class NoFormQuestionCanReachIt(unittest.TestCase):
    PHONE_LABELS = (
        "Phone", "Phone *", "Phone Number", "Phone number *", "Mobile",
        "Mobile phone", "Cell", "Cell phone", "Telephone", "Telephone number",
        "Primary phone", "Contact phone number", "What is your phone number?",
        "Best number to reach you", "Day-time telephone",
        # and the ones that name the thing itself
        "Signup phone", "Google Voice number", "Alternate phone",
        "Secondary phone number",
    )

    def test_every_phone_label_resolves_to_his_real_number(self):
        for label in self.PHONE_LABELS:
            with self.subTest(label=label):
                self.assertNotEqual(formfill.match_field({"label": label}),
                                    "signup_phone")

    def test_the_ordinary_phone_question_still_works(self):
        """Locking the signup number away must not break the real one —
        a field nothing fills is a question he answers by hand forever."""
        for label in ("Phone", "Mobile phone", "Telephone number",
                      "What is your phone number?"):
            with self.subTest(label=label):
                self.assertEqual(formfill.match_field({"label": label}), "phone")

    def test_a_name_or_id_attribute_cannot_reach_it_either(self):
        """A label-less Workday input is matched on its name/id codes."""
        for codes in ({"label": "", "name": "signup_phone"},
                      {"label": "", "id": "signupPhone"},
                      {"label": "", "name": "googleVoice"}):
            with self.subTest(codes=codes):
                self.assertNotEqual(formfill.match_field(codes), "signup_phone")

    def test_the_second_lock_holds_on_its_own(self):
        """If someone gives the field `asks` phrases by mistake, the
        SIGNUP_ONLY skip must still refuse it. This is the lock that
        matters, because the empty tuple is one careless edit from gone."""
        original = profile.FIELDS["signup_phone"]
        try:
            profile.FIELDS["signup_phone"] = dict(
                original, asks=("phone", "mobile", "cell", "telephone"))
            for label in ("Phone", "Mobile", "Cell", "Telephone"):
                with self.subTest(label=label):
                    self.assertNotEqual(formfill.match_field({"label": label}),
                                        "signup_phone")
        finally:
            profile.FIELDS["signup_phone"] = original

    def test_no_label_at_all_reaches_it(self):
        """Exhaustive over every phrase any field advertises: none of them
        may land on a signup-only field."""
        for key, spec in profile.FIELDS.items():
            for phrase in spec.get("asks") or ():
                with self.subTest(phrase=phrase):
                    got = formfill.match_field({"label": phrase})
                    self.assertNotIn(got or "", profile.SIGNUP_ONLY)



class AnApplicationGetsHisRealNumber(unittest.TestCase):
    """The other half of the rule, and the half he asked about.

    Locking the signup number away is only useful if the REAL number still
    lands on every application. The case that worried me: Workday builds an
    application from the account profile, so a phone box can arrive already
    prefilled with whatever the account was made with — the Google Voice
    number. If she left a prefilled field alone, every Workday application
    would quietly carry the number he does not watch, and he would never
    learn the job called.
    """

    KNOWN = {"phone": "605-555-0100", "signup_phone": "510-394-4076"}

    def _field(self, label, value=""):
        return {"label": label, "type": "tel", "selector": "#phone",
                "required": True, "value": value}

    def test_an_empty_phone_box_gets_his_real_number(self):
        plan = formfill.plan([self._field("Phone")], answers=self.KNOWN)
        self.assertEqual([r["value"] for r in plan["fill"]], ["605-555-0100"])

    def test_a_box_prefilled_with_the_signup_number_is_overwritten(self):
        """This is the Workday case. The prefilled Voice number must not
        survive into a submitted application."""
        plan = formfill.plan([self._field("Phone", value="510-394-4076")],
                             answers=self.KNOWN)
        values = [r["value"] for r in plan["fill"]]
        self.assertIn("605-555-0100", values)
        self.assertNotIn("510-394-4076", values)

    def test_every_phone_label_on_an_application_gets_the_real_number(self):
        for label in ("Phone", "Mobile phone", "Cell", "Telephone number",
                      "Primary phone", "What is your phone number?"):
            with self.subTest(label=label):
                plan = formfill.plan([self._field(label)], answers=self.KNOWN)
                self.assertEqual([r["value"] for r in plan["fill"]],
                                 ["605-555-0100"])

    def test_the_signup_number_appears_nowhere_in_an_application_plan(self):
        fields = [self._field("Phone"), self._field("Mobile", "510-394-4076"),
                  {"label": "Email", "type": "email", "selector": "#e",
                   "required": True, "value": ""}]
        plan = formfill.plan(fields, answers=self.KNOWN)
        self.assertNotIn("510-394-4076", str(plan))

if __name__ == "__main__":
    unittest.main()
