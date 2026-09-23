"""Live 2026-09-23 "Job applications need you - 2 I could not reach a form
on. Nothing has been sent." reached his desktop every seventeen minutes
through the night. A batch with nothing for him is not a notice."""
import unittest

from aletheia import campaign


class NoToastForNothing(unittest.TestCase):
    def test_a_batch_with_nothing_for_him_is_not_a_notice(self):
        self.assertFalse(campaign.worth_a_notice({"ready": [], "blocked": [], "failed": [{"url": "x"}, {"url": "y"}],
                                                  "needs_account": [], "questions": []}))
        self.assertFalse(campaign.worth_a_notice({}))

    def test_anything_he_can_act_on_still_is(self):
        self.assertTrue(campaign.worth_a_notice({"ready": [{"id": "a"}]}))
        self.assertTrue(campaign.worth_a_notice({"blocked": [{"id": "a"}], "questions": [{"label": "q"}]}))
        self.assertTrue(campaign.worth_a_notice({"needs_account": [{"id": "a"}]}))


if __name__ == "__main__":
    unittest.main()
