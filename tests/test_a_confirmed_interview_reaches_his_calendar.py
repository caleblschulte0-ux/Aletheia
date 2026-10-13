import datetime as dt
import unittest
from unittest import mock

from aletheia import calendly, interviews


class FakePage:
    def __init__(self, after_save="https://calendar.google.com/calendar/r/week", landing=None):
        self.url = ""
        self.after_save = after_save
        self.landing = landing
        self.clicked = []

    def goto(self, url, **_):
        self.url = self.landing or url

    def wait_for_timeout(self, *_):
        pass

    def wait_for_load_state(self, *_ , **__):
        pass

    def query_selector(self, selector):
        page = self

        class El:
            def click(self):
                page.clicked.append(selector)
                page.url = page.after_save

        return El()


START, END = "2026-10-13T18:00:00+00:00", "2026-10-13T18:30:00+00:00"


class ByBrowser(unittest.TestCase):
    def test_google_template_url_is_his_account_and_utc(self):
        url = calendly.template_url(title="Interview: Via", start=START, end=END, account="me@example.com")
        self.assertIn("action=TEMPLATE", url)
        self.assertIn("20261013T180000Z%2F20261013T183000Z", url)
        self.assertIn("authuser=me%40example.com", url)

    def test_saved_under_the_grant(self):
        page = FakePage()
        with mock.patch.object(calendly.journal, "append"):
            got = calendly.by_browser(title="Interview: Via", start=START, end=END,
                                      spender=lambda *_: "g1", page=page, account="")
        self.assertEqual(got["state"], "written")
        self.assertTrue(page.clicked)

    def test_no_grant_presses_nothing_and_says_not_on_it(self):
        page = FakePage()
        got = calendly.by_browser(title="Interview: Via", start=START, end=END,
                                  spender=lambda *_: None, page=page, account="")
        self.assertEqual(got["state"], "needs_grant")
        self.assertIn("NOT", got["say"])
        self.assertFalse(page.clicked)

    def test_a_sign_in_wall_is_said_not_claimed(self):
        page = FakePage(landing="https://accounts.google.com/ServiceLogin?continue=x")
        got = calendly.by_browser(title="Interview: Via", start=START, end=END,
                                  spender=lambda *_: "g1", page=page, account="")
        self.assertEqual(got["state"], "needs_sign_in")
        self.assertFalse(page.clicked)

    def test_no_live_provider_no_longer_claims_the_invitation_did_it(self):
        with mock.patch("aletheia.calendar_live.available", return_value=(False, "none")), \
                mock.patch.object(calendly, "by_browser", return_value={"state": "written", "say": "x"}) as b:
            got = calendly.put_on_his_calendar(title="Interview: Via", start=START, end=END)
        self.assertEqual(got["state"], "written")
        b.assert_called_once()


class Sweep(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 13, 1, 30, tzinfo=dt.timezone.utc)

    def event(self, **kw):
        base = {"id": "interview-via-2026-10-13", "title": "Interview: Via", "start": START, "end": END,
                "status": "CONFIRMED", "source": "interviews"}
        base.update(kw)
        return base

    def run_sweep(self, events, copies=None, state="written"):
        calls = []

        def writer(**kw):
            calls.append(kw)
            return {"state": state}

        store = dict(copies or {})
        with mock.patch.object(interviews, "_copies", side_effect=lambda: dict(store)), \
                mock.patch.object(interviews, "_note_copy",
                                  side_effect=lambda eid, live, now=None: store.__setitem__(
                                      eid, {"state": live["state"], "at": (now or self.NOW).isoformat()})), \
                mock.patch.object(interviews.journal, "append"):
            interviews.copy_to_his_calendar(now=self.NOW, events=events, writer=writer)
        return calls, store

    def test_a_confirmed_interview_is_copied_once(self):
        calls, store = self.run_sweep([self.event()])
        self.assertEqual(len(calls), 1)
        calls, _ = self.run_sweep([self.event()], copies=store)
        self.assertEqual(calls, [])

    def test_his_own_hold_counts_her_pencil_mark_does_not(self):
        calls, _ = self.run_sweep([self.event(status="TENTATIVE", source="hold:caleb")])
        self.assertEqual(len(calls), 1)
        calls, _ = self.run_sweep([self.event(status="TENTATIVE", source="interviews")])
        self.assertEqual(calls, [])

    def test_past_and_other_events_are_left(self):
        calls, _ = self.run_sweep([self.event(start="2026-10-12T18:00:00+00:00"),
                                   self.event(id="x", title="Dentist")])
        self.assertEqual(calls, [])

    def test_a_failure_waits_an_hour_then_tries_again(self):
        recent = {"interview-via-2026-10-13": {"state": "failed",
                                               "at": (self.NOW - dt.timedelta(minutes=10)).isoformat()}}
        calls, _ = self.run_sweep([self.event()], copies=recent)
        self.assertEqual(calls, [])
        old = {"interview-via-2026-10-13": {"state": "failed",
                                            "at": (self.NOW - dt.timedelta(hours=2)).isoformat()}}
        calls, _ = self.run_sweep([self.event()], copies=old)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()


VIA = ("Hi Caleb,\n\nThanks for submitting your availability! I've got the details for your phone "
       "interview all set up:\n\nDate/Time: Oct 13, 2026 1:00pm-1:30pm (GMT-05:00) Central Time "
       "(US & Canada)\nInterviewers: Ben Chen")


class AnOldConfirmation(unittest.TestCase):
    """Via confirmed on Oct 8, before she could read a confirmation, and the
    poll only looks back 48 hours: the interview was on nobody's calendar."""
    LEDGER = {"https://jobs.example/via": {"id": "apply-via", "company": "Via",
                                           "job_title": "Business Development Representative"}}

    class Inbox:
        def __init__(self, messages):
            self.messages = messages
            self.bodies_read = []

        def fetch_since(self, since, limit):
            return [m for m in self.messages]

        def fetch_body(self, mid):
            self.bodies_read.append(mid)
            return {"text": VIA}

    def run_catch_up(self, inbox):
        from aletheia import runtime
        seen = []
        with mock.patch.object(interviews, "status", return_value={"on": True, "window": {}}), \
                mock.patch.object(interviews, "record_confirmation",
                                  side_effect=lambda event, entry, **kw: seen.append((entry, kw)) or
                                  {"state": "confirmed"}):
            out = runtime._catch_up_confirmed_interviews(now_s=1e12, transport=inbox, ledger=self.LEDGER)
        return out, seen

    def test_the_via_confirmation_is_read_again_and_recorded(self):
        inbox = self.Inbox([{"subject": "Confirming your Phone Interview with Via!",
                             "from": "Allie <allie.schlager@ridewithvia.com>", "message_id": "<m1>"},
                            {"subject": "Thanks for applying to Via!", "from": "no-reply@ridewithvia.com",
                             "message_id": "<m2>"}])
        out, seen = self.run_catch_up(inbox)
        self.assertEqual(inbox.bodies_read, ["<m1>"])
        self.assertEqual(seen[0][0]["id"], "apply-via")
        self.assertEqual(out, [{"application": "apply-via", "state": "confirmed"}])

    def test_it_runs_at_most_every_six_hours(self):
        from aletheia import runtime
        inbox = self.Inbox([])
        with mock.patch.object(interviews, "status", return_value={"on": True, "window": {}}):
            runtime._CAUGHT_UP["at"] = -1e18
            runtime._catch_up_confirmed_interviews(now_s=1000.0, transport=inbox, ledger={})
            self.assertEqual(runtime._catch_up_confirmed_interviews(now_s=2000.0, transport=inbox, ledger={}), [])

    def test_record_confirmation_puts_a_future_time_on_and_a_past_one_not(self):
        with mock.patch.object(interviews, "status",
                               return_value={"on": True, "window": dict(interviews.DEFAULT_WINDOW)}), \
                mock.patch.object(interviews, "_confirmed", return_value={"state": "confirmed"}) as c:
            got = interviews.record_confirmation({"id": "e"}, {"company": "Via"}, subject="Confirming your interview",
                                                 text=VIA, now=dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc))
            self.assertEqual(got, {"state": "confirmed"})
            self.assertEqual(c.call_args[0][0]["start"], "2026-10-13T13:00:00-05:00")
            late = interviews.record_confirmation({"id": "e"}, {"company": "Via"}, subject="Confirming your interview",
                                                  text=VIA, now=dt.datetime(2026, 10, 14, tzinfo=dt.timezone.utc))
            self.assertIsNone(late)
