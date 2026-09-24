"""A story's newest line supersedes the lines before it.

Live, 2026-09-24, his page said "100 things worth seeing". Sixty of them
were the job hunt saying the same thing every batch: forty "Job
applications need you", twenty "Applications going out". Each was true
when it was filed and every one but the last was stale the moment the
next batch ran - and each stayed UNREAD, because nothing in the store
knew they were lines of one story. A notice on a `topic` now retires the
unread ones before it on that topic, naming which notice replaced them.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import campaign, journal, notifications


class NoticeStore(unittest.TestCase):
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

    def unread(self):
        return notifications.all_notifications(state="UNREAD", limit=500)


class TheNewestLineOfAStoryIsTheOnlyUnreadOne(NoticeStore):
    def test_the_third_batch_notice_retires_the_two_before_it(self):
        first = notifications.publish("Job applications need you", "3 need answers.", topic="jobs.batch",
                                      dedupe_key="campaign:1")
        second = notifications.publish("Applications going out", "5 filled in.", topic="jobs.batch",
                                       dedupe_key="campaign:2")
        third = notifications.publish("Applications going out", "2 filled in.", topic="jobs.batch",
                                      dedupe_key="campaign:3")
        self.assertEqual([n["id"] for n in self.unread()], [third["id"]])
        # Each line names the line that replaced it, so the chain reads back.
        for old, newer in ((first, second), (second, third)):
            now = notifications.load(old["id"])
            self.assertEqual(now["state"], "READ")
            self.assertEqual(now["superseded_by"], newer["id"])
        self.assertEqual(notifications.load(third["id"])["topic"], "jobs.batch")

    def test_a_notice_on_another_topic_or_with_none_is_left_alone(self):
        reminder = notifications.publish("Reminder", "call the dentist", dedupe_key="r:1")
        idea = notifications.publish("An idea for Stripe", "look at their blog", topic="pursuit:stripe",
                                     dedupe_key="p:1")
        notifications.publish("Applications going out", "2 filled in.", topic="jobs.batch",
                              dedupe_key="campaign:9")
        ids = {n["id"] for n in self.unread()}
        self.assertIn(reminder["id"], ids)
        self.assertIn(idea["id"], ids)
        self.assertEqual(len(ids), 3)

    def test_what_he_acknowledged_stays_his_record(self):
        seen = notifications.publish("Job applications need you", "3 need answers.", topic="jobs.batch",
                                     dedupe_key="campaign:1")
        notifications.set_state(seen["id"], "ACKNOWLEDGED")
        notifications.publish("Applications going out", "2 filled in.", topic="jobs.batch",
                              dedupe_key="campaign:2")
        now = notifications.load(seen["id"])
        self.assertEqual(now["state"], "ACKNOWLEDGED")
        self.assertNotIn("superseded_by", now)

    def test_a_deduped_republish_retires_nothing(self):
        a = notifications.publish("Applications going out", "2 filled in.", topic="jobs.batch",
                                  dedupe_key="campaign:1")
        again = notifications.publish("Applications going out", "2 filled in.", topic="jobs.batch",
                                      dedupe_key="campaign:1")
        self.assertEqual(again["id"], a["id"])
        self.assertEqual(notifications.load(a["id"])["state"], "UNREAD")


class TheJobHuntsNoticesAreOneStory(NoticeStore):
    def test_every_campaign_notice_carries_the_batch_topic(self):
        campaign._notify("Job applications need you", "3 need answers.", "campaign:1")
        campaign._notify("The job applications stopped", "The browser would not start.", "campaign-failed:2",
                         about=notifications.FAILED)
        campaign._notify("Applications going out", "4 filled in.", "campaign-retry:3")
        left = self.unread()
        self.assertEqual([n["title"] for n in left], ["Applications going out"])
        self.assertEqual(left[0]["topic"], campaign.BATCH_TOPIC)
        stopped = [n for n in notifications.all_notifications(limit=500) if "stopped" in n["title"]]
        self.assertEqual(stopped[0]["state"], "READ")
        self.assertEqual(stopped[0]["superseded_by"], left[0]["id"])


if __name__ == "__main__":
    unittest.main()
