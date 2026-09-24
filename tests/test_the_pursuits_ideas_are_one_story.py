"""The pursuit's ideas are one story per opportunity (2026-09-24).

24 unread "An idea for ..." sat on his page, several per opportunity, each
older one stale the moment a newer idea for the same opportunity was
filed. The newest idea for an opportunity supersedes the last; a note held
for him is its own story and is never hidden by an idea.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, notifications, pursuit


class TheNewestIdeaWins(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d / "private")})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (notifications, "NOTICES_DIR", d / "notices")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)

    def test_the_newest_idea_for_an_opportunity_is_the_only_unread_one(self):
        now = dt.datetime.now(dt.timezone.utc)
        stripe = {"id": "opp-1", "subject": {"name": "Stripe"}}
        ramp = {"id": "opp-2", "subject": {"name": "Ramp"}}
        for opp, mid, idea in ((stripe, "m1", "look at their blog"), (stripe, "m2", "ask the recruiter"),
                               (ramp, "m3", "read the job post again")):
            pursuit._do_suggest(opp, {"id": mid, "detail": {"idea": idea}, "why": "because"}, now)
        left = notifications.all_notifications(state="UNREAD", limit=500)
        # The speech door flattens the body to one line: "<idea> — <why>".
        self.assertEqual(sorted(n["body"].split(" — ")[0] for n in left),
                         ["ask the recruiter", "read the job post again"])
        self.assertEqual({n["topic"] for n in left}, {"pursuit:opp-1:idea", "pursuit:opp-2:idea"})
        retired = [n for n in notifications.all_notifications(limit=500) if n["state"] == "READ"]
        self.assertEqual(len(retired), 1)
        self.assertTrue(retired[0]["body"].startswith("look at their blog"), retired[0]["body"])


if __name__ == "__main__":
    unittest.main()
