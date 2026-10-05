"""Thirty-fourth sandbox batch, 2026-10-05: the hunt's outcomes, from the records.

    > did anyone reject me                [5.7s] "I can't tell"
    > who ghosted me / who haven't I heard back from   [5.6s] [5.5s] "I can't tell"
    > what's the oldest application / which is furthest along   [7.0s] [7.0s]
    > what's the last thing you sent      [5.5s] "I don't have anything showing"
    > what companies did you find today   [4.0s] a model
    > when's the next batch               [5.5s] "I don't see a batch scheduled"
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick

OLD = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
NEW = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
RUNS = [{"state": "SUBMITTED", "submitted_at": OLD, "company": "Acme", "job_title": "Account Manager", "outcomes": []},
        {"state": "SUBMITTED", "submitted_at": NEW, "company": "Globex", "job_title": "CSM", "outcomes": [{"outcome": "interview"}]},
        {"state": "NEEDS_YOU", "company": "Initech", "job_title": "Rep", "outcomes": []}]


class TheRecordsAnswer(unittest.TestCase):
    def test_rejections_ghosts_and_the_extremes(self):
        with mock.patch("aletheia.apply_run.all_runs", return_value=RUNS):
            self.assertEqual(quick.answer("did anyone reject me"), "No rejections on record.")
            self.assertEqual(quick.answer("who ghosted me"), "1 application with nothing back after a week: Account Manager at Acme.")
            self.assertEqual(quick.answer("who haven't i heard back from"), "1 application with nothing back after a week: Account Manager at Acme.")
            self.assertTrue(quick.answer("what's the oldest application").startswith("The oldest: Account Manager at Acme, sent "))
            self.assertEqual(quick.answer("which application is furthest along"), "CSM at Globex is furthest along, with an interview.")
            self.assertTrue(quick.answer("what's the last thing you sent").startswith("The last application sent was CSM at Globex, "))
        with mock.patch("aletheia.apply_run.all_runs", return_value=[]):
            self.assertEqual(quick.answer("who ghosted me"), "Nobody to chase: no application has gone out through me yet.")
            self.assertEqual(quick.answer("what's the oldest application"), "None: no application has gone out through me yet.")
            self.assertEqual(quick.answer("what's the last thing you sent"), "Nothing has gone out through me yet.")

    def test_the_companies_found_and_the_next_batch(self):
        with mock.patch("aletheia.job_discovery.today", return_value={"discovered": 3, "employers_new": ["Acme"],
                                                                      "best": [{"company": "Globex", "title": "CSM", "value": 5}]}):
            self.assertEqual(quick.answer("what companies did you find today"), "Today: Acme and Globex.")
        with mock.patch("aletheia.job_discovery.today", return_value=None):
            self.assertEqual(quick.answer("which employers came up today"), "I have not gone looking for jobs yet today.")
        with mock.patch("aletheia.apply_forever.paused", return_value={"reason": "you said stop"}):
            self.assertTrue(quick.answer("when's the next batch").startswith("Not until you say start applying"))
        with mock.patch("aletheia.apply_forever.paused", return_value=None):
            self.assertIn("about every 5 minutes", quick.answer("when do you apply again"))


if __name__ == "__main__":
    unittest.main()
