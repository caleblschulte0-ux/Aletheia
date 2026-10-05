"""Twenty-ninth sandbox batch, 2026-10-05: his decisions, the notices, the trouble.

    > what did I approve today      [6.0s] a model: "I don't have the full
                                    journal for the day in front of me"
    > what did I turn down today    [5.0s] the same
    > read me my notifications      [4.0s] a model, for "Nothing new"
    > what went wrong yesterday     [29.0s] a model and her own diagnosis
    > what broke                    [5.5s] a model
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick, voice

NOW = dt.datetime.now(dt.timezone.utc).isoformat()
ROWS = [{"id": "a1", "state": "APPROVED", "decided_at": NOW, "reason": "x", "plan": {"summary": "Hold tomorrow at 10 for the dentist"}},
        {"id": "a2", "state": "DENIED", "decided_at": NOW, "reason": "y", "plan": {"summary": "Hold Friday at 2 for the bank"}},
        {"id": "a3", "state": "APPROVED", "decided_at": "2020-01-01T00:00:00Z", "reason": "z", "plan": {"summary": "Something old"}}]


class HisDecisions(unittest.TestCase):
    def test_today_s_yes_and_no_from_the_store(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=ROWS), \
             mock.patch("aletheia.voice.approval_label", side_effect=lambda a: a["plan"]["summary"]):
            self.assertEqual(quick.answer("what did i approve today"), "Today you approved: Hold tomorrow at 10 for the dentist.")
            self.assertEqual(quick.answer("what did i turn down today"), "Today you turned down: Hold Friday at 2 for the bank.")
            self.assertEqual(quick.answer("what decisions did i make today"),
                             "Today you decided on 2 things: approved: Hold tomorrow at 10 for the dentist; turned down: Hold Friday at 2 for the bank.")
        with mock.patch("aletheia.policy.all_approvals", return_value=[]):
            self.assertEqual(quick.answer("what did i say yes to today"), "Nothing approved today.")


class TheTrouble(unittest.TestCase):
    def test_yesterday_reads_the_journals_alerts_for_that_day(self):
        yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).replace(hour=12).isoformat()
        rows = [{"ts": yesterday, "kind": "alert", "text": "the site refused the form"},
                {"ts": yesterday, "kind": "action", "text": "sent an application"}]
        with mock.patch("aletheia.recollection._read_journal", return_value=(rows, True)), \
             mock.patch("aletheia.localtime.today", return_value=dt.date.today()):
            said = quick.answer("what went wrong yesterday")
        self.assertEqual(said, "1 alert in the journal yesterday, the latest: the site refused the form.")
        with mock.patch("aletheia.recollection._read_journal", return_value=([], True)):
            self.assertTrue(quick.answer("did anything break yesterday").startswith("Nothing went wrong that I recorded yesterday"))

    def test_what_broke_is_today_and_notifications_are_read(self):
        self.assertEqual(quick.match("what broke")[0], "wrong")
        self.assertEqual(voice.interpret("read me my notifications")["command"], {"kind": "notify_check"})
        self.assertEqual(voice.interpret("what notifications do I have")["command"], {"kind": "notify_check"})


if __name__ == "__main__":
    unittest.main()
