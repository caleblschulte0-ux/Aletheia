"""'Snooze that for an hour' — the commonest thing anybody says to an alert.

It had no verb. The planner invented a capability called `reminder.cancel`,
filed a build task for it, and said "1 step ready — Snooze a reminder. Say
approve to run it. I can't reminder.cancel yet." — a sentence that both
offers and refuses.

A notice he has read and cannot act on YET is the normal case in a room,
so putting it down has to be as easy as saying so.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import act, intercom, notifications, scheduler, speech, voice


def notice(body, nid="n1", created="2026-09-07T00:00:00Z", title="Reminder"):
    return {"id": nid, "title": title, "body": body, "state": "UNREAD",
            "priority": "IMPORTANT", "created_at": created}


class HeCanSayIt(unittest.TestCase):
    def test_the_intervals_people_say(self):
        for said, minutes in (("snooze that for an hour", 60),
                              ("snooze that for 20 minutes", 20),
                              ("snooze it for half an hour", 30),
                              ("snooze the alert for 2 hours", 120)):
            self.assertEqual(voice.interpret(said)["command"],
                             {"kind": "notify_snooze", "minutes": minutes}, said)

    def test_a_bare_snooze_has_a_default_because_the_reply_says_it_back(self):
        self.assertEqual(voice.interpret("snooze that")["command"]["minutes"],
                         voice.DEFAULT_SNOOZE_MINUTES)

    def test_an_interval_it_cannot_read_is_not_rounded_to_one_he_did_not_say(self):
        got = voice.interpret("snooze that until tuesday")
        self.assertEqual(got["command"]["kind"], "intent")

    def test_it_is_routine_and_local(self):
        self.assertIn("notify_snooze", intercom.ROUTINE_KINDS)
        self.assertIn("notify_snooze", intercom.LOCAL_KINDS)


class ItReallyComesBack(unittest.TestCase):
    def snooze(self, rows, **cmd):
        made = {}

        def create(sid, command, **kw):
            made.update({"id": sid, "command": command, **kw})
            return {}

        with mock.patch.object(notifications, "all_notifications", return_value=rows), \
             mock.patch.object(notifications, "set_state") as state, \
             mock.patch.object(scheduler, "create", create):
            said = intercom.execute_command(
                {"kind": "notify_snooze", "minutes": 60, **cmd}, {})
        return said, made, state

    def test_it_schedules_the_notice_to_say_itself_again(self):
        said, made, state = self.snooze([notice("call the dentist")])
        self.assertEqual(made["kind"], "once")
        self.assertEqual(made["command"],
                         {"kind": "notify_operator", "text": "call the dentist"})
        when = dt.datetime.fromisoformat(made["at"])
        self.assertGreater(when, dt.datetime.now(dt.timezone.utc))
        self.assertEqual(speech.spoken_receipt("notify_snooze", said).split(":")[-1].strip(),
                         "call the dentist.")

    def test_it_is_read_and_not_acknowledged(self):
        # He has not dealt with it, he has deferred it — and it is coming
        # back to say so.
        _said, _made, state = self.snooze([notice("call the dentist")])
        state.assert_called_once_with("n1", "READ")

    def test_that_means_the_thing_that_just_spoke(self):
        rows = [notice("old one", nid="a", created="2026-09-07T00:00:00Z"),
                notice("the boiler man", nid="b", created="2026-09-07T09:00:00Z")]
        said, _made, _state = self.snooze(rows, which="that")
        self.assertIn("the boiler man", said)

    def test_he_can_name_one_instead(self):
        rows = [notice("call the dentist", nid="a"),
                notice("the boiler man", nid="b")]
        said, _made, _state = self.snooze(rows, which="dentist")
        self.assertIn("dentist", said)

    def test_two_that_match_is_a_question(self):
        rows = [notice("call the dentist", nid="a"),
                notice("call the plumber", nid="b")]
        with mock.patch.object(notifications, "all_notifications", return_value=rows):
            with self.assertRaises(act.Refused) as caught:
                intercom.execute_command(
                    {"kind": "notify_snooze", "minutes": 60, "which": "call"}, {})
        self.assertIn(" or ", str(caught.exception))

    def test_nothing_waiting_is_refused_in_words(self):
        with mock.patch.object(notifications, "all_notifications", return_value=[]):
            with self.assertRaises(act.Refused) as caught:
                intercom.execute_command({"kind": "notify_snooze", "minutes": 60}, {})
        self.assertIn("Nothing is waiting", str(caught.exception))

    def test_a_nonsense_interval_is_refused(self):
        for minutes in (0, -5, 60 * 24 * 400):
            with mock.patch.object(notifications, "all_notifications",
                                   return_value=[notice("x")]):
                with self.assertRaises(act.Refused):
                    intercom.execute_command(
                        {"kind": "notify_snooze", "minutes": minutes}, {})


if __name__ == "__main__":
    unittest.main()
