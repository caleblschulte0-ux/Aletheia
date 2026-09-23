"""Every batch of the night of 2026-09-23 put "2 applications filled in and
waiting for you to confirm" on his screen while the standing grant sent
every one of them untouched. The sentence follows the grant."""
import unittest
from unittest import mock

from aletheia import campaign

OUT = {"ready": [{"id": "apply-1"}, {"id": "apply-2"}], "blocked": [], "failed": [], "questions": []}


class TheSentenceFollowsTheGrant(unittest.TestCase):
    def test_with_the_grant_live_nothing_waits_for_him(self):
        with mock.patch("aletheia.standing.jobs_status", return_value={"granted": True}):
            said = campaign.spoken(OUT)
            self.assertIn("2 applications filled in; they go out on the next beat without a tap", said)
            self.assertNotIn("waiting for you to confirm", said)
            title, _body = campaign._summary(OUT)
            self.assertEqual(title, "Applications going out")

    def test_without_it_he_confirms_as_before(self):
        with mock.patch("aletheia.standing.jobs_status", return_value={"granted": False}):
            self.assertIn("2 applications filled in and waiting for you to confirm", campaign.spoken(OUT))
            self.assertEqual(campaign._summary(OUT)[0], "Applications ready to approve")

    def test_a_store_she_cannot_read_means_he_confirms(self):
        with mock.patch("aletheia.standing.jobs_status", side_effect=OSError("no store")):
            self.assertIn("waiting for you to confirm", campaign.spoken(OUT))


if __name__ == "__main__":
    unittest.main()
