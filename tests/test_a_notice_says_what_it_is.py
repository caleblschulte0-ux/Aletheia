"""Two reminders fired. One of them vanished, and neither was named.

The reminder chain works end to end — "remind me at 4" becomes a schedule,
the Core's beat fires it, a notification is published IMPORTANT and
UNREAD. Then the surface he actually looks at threw most of it away:

    "what's waiting on me"  ->  "1 thing I wanted to tell you about."

That is the answer to "how many", and he asked what. Worse, `presence`
deduplicated unread notices **by title**, and every reminder is titled
"Reminder" — so "call the dentist" and "pick up the kids" collapsed into
one line, and the second one was simply gone.
"""
import unittest
from unittest import mock

from aletheia import presence, quick


def notice(title, body, priority="IMPORTANT", nid="n1"):
    return {"id": nid, "title": title, "body": body, "priority": priority,
            "state": "UNREAD", "created_at": "2026-09-06T20:00:00Z"}


class TwoRemindersAreTwoThingsCase(unittest.TestCase):
    def unread(self, rows):
        return mock.patch("aletheia.notifications.all_notifications",
                          lambda **kw: rows)

    def test_two_reminders_do_not_collapse_into_one(self):
        with self.unread([notice("Reminder", "call the dentist", nid="a"),
                          notice("Reminder", "pick up the kids", nid="b")]):
            said = presence._notifications()
        self.assertEqual(len(said), 2)
        self.assertEqual({n["says"] for n in said},
                         {"call the dentist", "pick up the kids"})

    def test_the_same_notice_twice_still_collapses(self):
        """The dedupe it was written for: one subsystem failing twice
        shows the same sentence twice and reads as a bug in the wall."""
        with self.unread([notice("Trader down", "no heartbeat", nid="a"),
                          notice("Trader down", "no heartbeat", nid="b")]):
            self.assertEqual(len(presence._notifications()), 1)

    def test_a_generic_title_is_replaced_by_what_it_is_about(self):
        with self.unread([notice("Reminder", "call the dentist")]):
            self.assertEqual(presence._notifications()[0]["says"],
                             "call the dentist")

    def test_a_real_title_keeps_its_body_alongside(self):
        with self.unread([notice("Trader halted", "guardrail tripped at 3pm")]):
            says = presence._notifications()[0]["says"]
        self.assertIn("Trader halted", says)
        self.assertIn("guardrail tripped", says)

    def test_a_title_that_already_contains_the_body_is_not_doubled(self):
        with self.unread([notice("Application sent to Stripe",
                                 "sent to Stripe")]):
            self.assertEqual(presence._notifications()[0]["says"],
                             "Application sent to Stripe")

    def test_the_headline_says_the_thing_not_the_category(self):
        with self.unread([notice("Reminder", "call the dentist")]):
            snap = presence.snapshot()
        self.assertEqual(snap["headline"], "call the dentist")

    def test_the_title_is_still_carried_for_anything_that_wants_it(self):
        with self.unread([notice("Reminder", "call the dentist")]):
            row = presence._notifications()[0]
        self.assertEqual(row["title"], "Reminder")
        self.assertEqual(row["body"], "call the dentist")


class AskingWhatIsWaitingCase(unittest.TestCase):
    def snap(self, notices, waiting=()):
        return mock.patch("aletheia.presence.snapshot",
                          lambda: {"halted": False, "waiting_on_you": list(waiting),
                                   "notifications": notices})

    def test_she_names_them(self):
        with self.snap([{"says": "call the dentist"},
                        {"says": "pick up the kids"}]):
            said = quick.answer("whats waiting on me")
        self.assertIn("call the dentist", said)
        self.assertIn("pick up the kids", said)
        self.assertNotIn("I wanted to tell you about", said)

    def test_a_long_list_is_summarised_rather_than_recited(self):
        with self.snap([{"says": f"thing {n}"} for n in range(6)]):
            said = quick.answer("whats waiting on me")
        self.assertIn("and 3 more", said)

    def test_a_notice_with_no_words_falls_back_to_a_count(self):
        with self.snap([{"says": ""}, {"says": ""}]):
            said = quick.answer("whats waiting on me")
        self.assertIn("2 things", said)

    def test_approvals_are_still_named_first(self):
        with self.snap([{"says": "call the dentist"}],
                       waiting=[{"label": "send the email to Dana"}]):
            said = quick.answer("whats waiting on me")
        self.assertIn("send the email to Dana", said)
        self.assertIn("call the dentist", said)


if __name__ == "__main__":
    unittest.main()
