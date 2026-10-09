"""Live 2026-10-08, Via: "I've got the details for your phone interview all
set up: Date/Time: Oct 13, 2026 1:00pm-1:30pm (GMT-05:00) Central Time".

Read as an ask for time it drafted a reply picking the time they had just
confirmed, pencilled it in TENTATIVE, and read the zone "(GMT-05:00)" as a
second, 5 PM proposal. His ruling wants it "on the calendar, the Open Range
Interactive Calendar" - and there is nothing to answer."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import calendar as cal, interviews, journal, mail, policy, reply_understanding as ru

VIA = ("Hi Caleb,\n\nThanks for submitting your availability! I've got the details for your phone "
       "interview all set up:\n\nDate/Time: Oct 13, 2026 1:00pm-1:30pm (GMT-05:00) Central Time "
       "(US & Canada)\nInterviewers: Ben Chen\n\nThey will give you a call at +16053215691.")
NOW = dt.datetime(2026, 10, 8, 17, 32, tzinfo=dt.timezone.utc)


class TheTimesInIt(unittest.TestCase):
    def test_a_zone_offset_is_not_a_time_and_a_range_is_one_time(self):
        times = ru.extract_times(VIA, reference=NOW, timezone="America/Chicago", minutes=30)
        self.assertEqual([t["start"] for t in times], ["2026-10-13T13:00:00-05:00"])

    def test_two_times_joined_by_and_are_still_two(self):
        times = ru.extract_times("Tuesday 10am and 2pm work", reference=NOW, timezone="America/Chicago")
        self.assertEqual(len(times), 2)

    def test_what_confirms_and_what_asks(self):
        self.assertTrue(interviews.confirms("Confirming your Phone Interview with Via!", VIA))
        self.assertFalse(interviews.confirms("Interview - Fin", "Could you do Wednesday at 1:30pm?"))
        self.assertFalse(interviews.confirms("Interview confirmation",
                                             "Please submit your availability so we can get this confirmed."))


class TheAct(unittest.TestCase):
    ENTRY = {"id": "apply-via", "company": "Via", "job_title": "Business Development Representative"}
    EVENT = {"id": "ev-via", "attributes": {"sender": "allie.schlager@ridewithvia.com"}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in ((mail, "MAIL_DIR", root / "mail"), (policy, "APPROVALS_DIR", root / "approvals"),
                                    (journal, "JOURNAL_PATH", root / "journal.jsonl"),
                                    (cal, "CALENDAR_DIR", root / "events")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        # The switch, not `enable()`: enabling creates a standing calendar
        # grant that outlives this test and approves other tests' writes.
        on = mock.patch.object(interviews, "status",
                               return_value={"on": True, "window": dict(interviews.DEFAULT_WINDOW)})
        on.start(); self.addCleanup(on.stop)

    def test_it_goes_on_both_calendars_confirmed_and_nothing_is_drafted(self):
        live, marks, notices = [], [], []
        out = interviews.consider(
            self.EVENT, self.ENTRY, subject="Confirming your Phone Interview with Via!", text=VIA, now=NOW,
            busy=lambda s, e: False, known={"full_name": "Caleb Schulte"},
            calendar_writer=lambda **kw: live.append(kw) or {"state": "written",
                                                             "say": "it is on the Open Range Interactive calendar"},
            marker=lambda rid, outcome, note="": marks.append((rid, outcome, note)),
            notify=lambda title, body, **kw: notices.append((title, body)))
        self.assertEqual(out["state"], "confirmed")
        self.assertEqual(live[0]["start"], "2026-10-13T13:00:00-05:00")
        self.assertEqual(live[0]["title"], "Interview: Via")
        event = cal.load(out["hold"])
        self.assertEqual((event["status"], event["movable"]), ("CONFIRMED", False))
        self.assertEqual(list(mail.MAIL_DIR.glob("mail-*.json")) if mail.MAIL_DIR.exists() else [], [])
        self.assertEqual(marks[0][:2], ("apply-via", "interview"))
        self.assertEqual(notices[0][0], "Via interview confirmed")
        self.assertIn("Open Range Interactive calendar", notices[0][1])

    def test_her_own_pencil_mark_becomes_the_confirmed_time(self):
        cal.create("interview-via-2026-10-13", "Interview: Via", "2026-10-13T13:30:00-05:00",
                   "2026-10-13T14:00:00-05:00", source="interviews", status="TENTATIVE", movable=True)
        out = interviews.consider(
            self.EVENT, self.ENTRY, subject="Confirming your Phone Interview with Via!", text=VIA, now=NOW,
            busy=lambda s, e: False, known={}, calendar_writer=lambda **kw: {"state": "by_invitation", "say": ""},
            marker=lambda *a, **k: None, notify=lambda *a, **k: None)
        event = cal.load(out["hold"])
        self.assertEqual((event["start"], event["status"]), ("2026-10-13T13:00:00-05:00", "CONFIRMED"))


if __name__ == "__main__":
    unittest.main()
