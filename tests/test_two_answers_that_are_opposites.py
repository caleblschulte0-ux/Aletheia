"""It told Scale AI he needs a visa. He does not.

2026-09-12, his first run where an application actually reached "ready for
you to approve". It was filled like this::

    Are you legally authorized to work in the country where the job is
    located?*                                                      -> Yes
    Will you now or in the future require company sponsorship to retain or
    extend your work authorization in the country where the job is
    located?*                                                      -> Yes

Both answers came from ONE fact, ``work_authorization`` ("Yes"), because
``match_field`` is longest-phrase-wins and the sponsorship question also
contains the words "work authorization". His ``needs_sponsorship`` was
"No" on file the whole time and was never consulted.

This is the worst shape a matching bug can take. The two fields' answers
are OPPOSITES, so the wrong one does not leave a blank that somebody
notices - it states the reverse of the truth, in his name, on a real
application, under a heading employers filter on. It would have gone out
the moment he said yes.

So: a question that asks whether he NEEDS sponsorship is about sponsorship,
however much authorization vocabulary the sentence carries.
"""
from __future__ import annotations

import unittest

from aletheia import formfill


def _field(label, **kw):
    base = {"selector": "#q", "label": label, "name": "", "id": "",
            "tag": "input", "type": "text", "required": True, "value": ""}
    base.update(kw)
    return base


class TwoAnswersThatAreOppositesCase(unittest.TestCase):
    #: The live Scale AI label, verbatim.
    SCALE_AI = ("Will you now or in the future require company sponsorship to "
                "retain or extend your work authorization in the country where "
                "the job is located?*")

    def test_the_question_that_went_out_wrong(self):
        self.assertEqual(formfill.match_field(_field(self.SCALE_AI)),
                         "needs_sponsorship")

    def test_the_plain_authorization_question_is_untouched(self):
        for label in ("Are you legally authorized to work in the country where "
                      "the job is located?*",
                      "Are you legally authorized to work in the United States?",
                      "Do you have the right to work in the US?"):
            with self.subTest(label=label[:40]):
                self.assertEqual(formfill.match_field(_field(label)),
                                 "work_authorization")

    def test_every_way_an_employer_asks_about_needing_sponsorship(self):
        for label in (
                "Will you require visa sponsorship now or in the future?",
                "Do you need sponsorship to work in the United States?",
                "Will you now or in the future require sponsorship for employment "
                "visa status (e.g. H-1B)?",
                "Do you require a work permit to be employed here?",
                "Would you need us to sponsor you for a visa?",
        ):
            with self.subTest(label=label[:40]):
                self.assertEqual(formfill.match_field(_field(label)),
                                 "needs_sponsorship", label)

    def test_a_conditional_follow_up_is_still_nobody_s_fact(self):
        """Brex, live 2026-09-10: it depends on an answer above, not a fact."""
        self.assertIsNone(formfill.match_field(_field(
            "If you're not authorized to work at the stated location, what "
            "sponsorship would you require for the role?")))

    def test_the_two_answers_really_are_opposites_on_one_form(self):
        """End to end: both questions, one plan, two different facts."""
        form = [_field("Are you legally authorized to work in the country where "
                       "the job is located?*", selector="#auth"),
                _field(self.SCALE_AI, selector="#spon")]
        plan = formfill.plan(form, answers={"work_authorization": "Yes",
                                            "needs_sponsorship": "No"})
        filled = {step["selector"]: step["value"] for step in plan["fill"]}
        self.assertEqual(filled.get("#auth"), "Yes")
        self.assertEqual(filled.get("#spon"), "No",
                         "he does not need sponsorship, and the form must say so")


if __name__ == "__main__":
    unittest.main()
