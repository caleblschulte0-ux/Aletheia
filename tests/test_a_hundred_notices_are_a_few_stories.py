"""A hundred notices are a few stories (2026-09-24).

His page said "100 things worth seeing": sixty were "An idea for ..." from
the pursuit, one per opportunity, and the count had hit the route's own
limit. Notices of one story - the same topic with the particular id taken
out, or the same title stem - become ONE row on the page, the newest,
carrying how many it stands for and every id "Got it" then clears.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, notifications


def _n(i: int, title: str, topic: str = "", created: str = "") -> dict:
    return {"version": 1, "id": f"notice-{i:04d}", "title": title, "body": f"body {i}", "priority": "NORMAL",
            "state": "UNREAD", "created_at": created or f"2026-09-24T{i % 24:02d}:00:00Z",
            "updated_at": "2026-09-24T00:00:00Z", **({"topic": topic} if topic else {})}


class AStoryIsOneRow(unittest.TestCase):
    def test_the_story_of_a_notice(self):
        self.assertEqual(notifications.story_of({"topic": "pursuit:opp-07278e0e77:idea"}), "pursuit:idea")
        self.assertEqual(notifications.story_of({"topic": "jobs.batch"}), "jobs.batch")
        self.assertEqual(notifications.story_of({"title": "An idea for Key Account Manager at Driveline"}), "an idea")
        self.assertEqual(notifications.story_of({"title": "A note worth sending to Dana"}), "a note worth sending")
        self.assertEqual(notifications.story_of({"title": "Reminder"}), "reminder")

    def test_three_or_more_of_a_story_fold_to_the_newest_with_a_count(self):
        rows = [_n(1, "An idea for Stripe", "pursuit:opp-1:idea"), _n(2, "Reminder"),
                _n(3, "An idea for Ramp", "pursuit:opp-2:idea"), _n(4, "An idea for Vanta", "pursuit:opp-3:idea"),
                _n(5, "Application sent"), _n(6, "Application sent")]
        out = notifications.folded(rows)
        self.assertEqual([r["id"] for r in out], ["notice-0001", "notice-0002", "notice-0005", "notice-0006"])
        idea = out[0]
        self.assertEqual((idea["count"], idea["ids"]), (3, ["notice-0001", "notice-0003", "notice-0004"]))
        self.assertNotIn("count", out[1], "two of a kind are still two rows")

    def test_the_route_folds_and_counts_the_whole_list(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d / "private")})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (notifications, "NOTICES_DIR", d / "notices")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        for i in range(120):
            notifications.publish(f"An idea for Company {i}", f"idea {i}", source="pursuit",
                                  dedupe_key=f"pursuit-idea:opp-{i}:m", topic=f"pursuit:opp-{i}:idea")
        notifications.publish("Reminder", "call the dentist", dedupe_key="r:1")
        # What the route hands the page for ?state=UNREAD&folded=1.
        rows = notifications.folded(notifications.all_notifications(state="UNREAD", limit=500))
        ideas = [r for r in rows if r.get("count")]
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0]["count"], 120, "the count is the whole list, not the route's old limit of 100")
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
