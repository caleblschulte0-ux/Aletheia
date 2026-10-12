"""Talked to her, 2026-10-12, every model off: "anything new on my calendar" and "what did you sign
me up for this week" went to a model and came back "I can't think just now", while "anything on
my calendar" and "what did you sign me up for" were answered at once from her own stores."""

import unittest

from aletheia import quick


class AnythingNewOnMyCalendarIsTheCalendar(unittest.TestCase):

    def test_the_new_and_added_phrasings_are_the_calendar_question(self):
        for asked, means in (("anything new on my calendar", "what's coming up"),
                             ("anything added to my calendar", "what's coming up"),
                             ("what's new on my calendar this week", "what's on my calendar this week"),
                             ("anything new on my schedule tomorrow", "what's on my calendar tomorrow"),
                             ("is there anything on my calendar today", "what's on my calendar today")):
            self.assertEqual(quick._direct(asked), means, asked)
            self.assertIsNotNone(quick.answer(asked), asked)

    def test_sign_ups_asked_with_a_when_are_her_ledger(self):
        for asked in ("what did you sign me up for this week", "what did you sign me up for lately",
                      "what have you signed me up for so far"):
            self.assertEqual((quick.match(asked) or ("",))[0], "signed_up", asked)
            self.assertIsNotNone(quick.answer(asked), asked)


if __name__ == "__main__":
    unittest.main()
