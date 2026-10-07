"""A board is searched by the words of each title she hunts for, and every
word has to be in the posting's title - so the same work posted under a
name not on her list is never seen. 2026-10-07: five titles, read off his
resume on 09-23 and kept by its hash since, while what she found a day fell
from 40-70 to 8-25. The brief asks for the other titles employers use for
the same work, up to eight, and the roles read under the old brief are read
again once - with the old ones as the floor when nobody can think."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import campaign, stateio

TEXT = "Customer success and account management, four years..."


class OneJobHasManyTitles(unittest.TestCase):
    def setUp(self):
        campaign.forget_roles()
        self.addCleanup(campaign.forget_roles)
        for target in ("aletheia.profile.known", ):
            p = mock.patch(target, return_value={})
            p.start(); self.addCleanup(p.stop)
        for target, value in (("aletheia.job_fit.preferences", ([], [])),
                              ("aletheia.job_fit.unwanted_reason", "")):
            p = mock.patch(target, return_value=value)
            p.start(); self.addCleanup(p.stop)

    def _old_cache(self, roles):
        key = campaign._resume_key(TEXT).split(":", 1)[-1]          # the pre-version key
        path = campaign._roles_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(path, {key: roles})

    def test_the_brief_asks_for_the_other_titles_of_the_same_work(self):
        brief = " ".join(campaign.ROLES_BRIEF.split())
        self.assertIn("SAME work under different titles", brief)
        self.assertIn("up to 8", brief)
        self.assertEqual(campaign.MAX_ROLES, 8)

    def test_eight_titles_are_kept(self):
        many = [f"Title {n}" for n in range(10)]
        self.assertEqual(len(campaign._roles_validator({"roles": many})["roles"]), 8)

    def test_roles_read_under_the_old_brief_are_read_again_once(self):
        self._old_cache(["Customer Success Manager"])
        think = mock.Mock(return_value={"roles": ["Customer Success Manager", "Customer Success Associate",
                                                  "Account Coordinator"]})
        first = campaign.roles_for(TEXT, think=think)
        second = campaign.roles_for(TEXT, think=think)
        self.assertEqual(think.call_count, 1)
        self.assertIn("Customer Success Associate", first)
        self.assertEqual(first, second)

    def test_nobody_to_think_keeps_the_old_roles_rather_than_one_title(self):
        self._old_cache(["Customer Success Manager", "Account Manager"])
        def nobody(*a, **k):
            raise RuntimeError("nobody can think")
        self.assertEqual(campaign.roles_for(TEXT, think=nobody),
                         ["Customer Success Manager", "Account Manager"])


if __name__ == "__main__":
    unittest.main()
