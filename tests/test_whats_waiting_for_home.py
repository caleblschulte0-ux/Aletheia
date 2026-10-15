"""2026-10-15, every model off: "remind me to call mom when I get home", then
"what's on my list for when I get home" went to a model; and "undo that"
after "remind me next week to renew my license" said "the reminder to renew
my license is off"."""
import unittest
from unittest import mock

from aletheia import quick


class WhatsWaitingForHome(unittest.TestCase):
    def test_the_home_reminders_are_listed(self):
        with mock.patch.object(quick, "_home_reminders", return_value=["call mom", "feed the cat"]):
            for q in ("what's on my list for when I get home", "what reminders do I have for when I get home",
                      "what did I ask you to remind me when I get home"):
                self.assertEqual(quick.answer(q), "When you get home: call mom and feed the cat.", q)

    def test_none_is_said(self):
        with mock.patch.object(quick, "_home_reminders", return_value=[]):
            self.assertTrue(quick.answer("what's for when I get home").startswith("Nothing's waiting for when you get home."))

    def test_the_other_reminder_questions_are_not_taken(self):
        t = quick._tidy("what reminders do i have")
        self.assertFalse(dict(quick.PATTERNS)["home_waiting"].search(t))


class UndoneIsSaidAsHis(unittest.TestCase):
    def test_my_becomes_your(self):
        from aletheia import intercom, scheduler
        found = {"id": "r1", "kind": "once", "at": "2026-10-19T09:00:00-05:00"}
        with mock.patch.object(intercom, "_one_reminder", return_value=(found, "")), \
                mock.patch.object(scheduler, "set_enabled"):
            said = intercom._reverse_his_ask("remind_at", {"kind": "remind_at", "text": "renew my license"})
        self.assertEqual(said, "Undone: the reminder to renew your license is off.")

if __name__ == "__main__":
    unittest.main()
