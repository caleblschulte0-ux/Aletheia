"""What he says is happening is on the calendar, clash or no clash.

2026-10-28, talking to her with the models off:

    > I have a dentist appointment friday at 2      Pencilled in ...
    > I have lunch with sam friday at 1:30
      I can't do that: I didn't pencil that in: it overlaps dentist appointment
    > do I have any conflicts friday               (to the planner)
    > what should I do first today                 (to a model)

Lunch is happening whether or not it runs into the dentist; refusing to
write it down only makes her calendar wrong. It is held anyway and the
clash is said back. Her OWN holds (a mission's, a plan's) still refuse a
clash: only a hold he said carries `anyway`.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, calendar_reasoning, intercom, quick, voice


class HeSaidItIsHappening(unittest.TestCase):
    def setUp(self):
        self.events = []
        create = lambda event_id, title, start, end, **kw: self.events.append(  # noqa: E731
            {"id": event_id, "title": title, "start": start, "end": end, "status": "TENTATIVE",
             "source": kw.get("source", "")}) or self.events[-1]
        self.patches = [mock.patch.object(calendar, "all_events", lambda: list(self.events)),
                        mock.patch.object(calendar, "create", create),
                        mock.patch.object(calendar, "load", mock.Mock(side_effect=ValueError)),
                        mock.patch.object(calendar_reasoning, "_save_hold", lambda record, did: record),
                        mock.patch.object(calendar_reasoning.journal, "append", lambda *a, **k: None)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        self.friday = dt.datetime(2099, 1, 2, tzinfo=dt.timezone.utc)

    def at(self, hour, minute=0):
        return (self.friday + dt.timedelta(hours=hour, minutes=minute)).isoformat()

    def test_his_word_is_held_and_the_clash_said(self):
        intercom.execute_command({"kind": "calendar_hold", "title": "dentist appointment", "start": self.at(14),
                                  "minutes": 60, "anyway": True}, {})
        said = intercom.execute_command({"kind": "calendar_hold", "title": "lunch with Sam", "start": self.at(13, 30),
                                         "minutes": 60, "anyway": True}, {})
        self.assertEqual(len(self.events), 2)
        self.assertIn("Pencilled in lunch with Sam", said)
        self.assertIn("Heads up: it runs into dentist appointment at", said)

    def test_a_hold_of_hers_still_refuses_a_clash(self):
        from aletheia import act
        intercom.execute_command({"kind": "calendar_hold", "title": "dentist appointment", "start": self.at(14),
                                  "minutes": 60}, {})
        with self.assertRaises(act.Refused):
            intercom.execute_command({"kind": "calendar_hold", "title": "a free walk", "start": self.at(13, 30),
                                      "minutes": 60}, {})
        self.assertEqual(len(self.events), 1)

    def test_what_he_says_compiles_with_anyway(self):
        got = voice.interpret("I have lunch with sam friday at 1:30")["command"]
        self.assertEqual((got["kind"], got.get("anyway")), ("calendar_hold", True))


class AskedWithoutAModel(unittest.TestCase):
    def test_conflicts_on_a_day(self):
        self.assertEqual(quick.match("do i have any conflicts friday")[0], "double_booked")
        self.assertEqual(quick.match("any conflicts on friday")[0], "double_booked")

    def test_what_first_today(self):
        for said in ("what should i do first today", "what should i work on next today",
                     "what should i focus on this afternoon"):
            self.assertEqual(quick.match(said)[0], "focus", said)


if __name__ == "__main__":
    unittest.main()
