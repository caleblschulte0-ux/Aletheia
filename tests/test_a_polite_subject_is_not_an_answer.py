"""His words, 2026-10-07: *"the tracking, it needs to be getting tracked better.
It needs to be getting alerting me better. Because I've had emails come into
my inbox about jobs and it doesn't tell me anything."*

Two things were true of his inbox that day, and each is a test here:

- most employers say no under a polite subject ("Thank you for applying to
  Klaviyo", "Thank you for your interest in ... at Affirm!"). A subject that
  reads as an acknowledgement was never opened, so every one of those was
  filed as an acknowledgement: the funnel counted 3 rejections against 230
  applications, which tells him nothing about what is working;
- both of his first interview invites (Via, Northspyre) asked him to enter
  his availability on a Greenhouse page. Nothing recognised that page, so
  the best she did was draft an email to a recruiter who had asked for the
  page, and he heard about neither.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import calendly, interviews, journal, mail, policy, runtime

VIA_PAGE = "https://app2.greenhouse.io/availability/370f5c1bebde8f2c301f197b4636e934"
VIA_BODY = ("Hi Caleb,\n\nI was excited to see your application for the Business Development "
            "Representative role at Via. Are you still interested in interviewing with us? If so, please "
            "input your upcoming availability into the scheduling link below.\n\nEnter your availability now > "
            f"( {VIA_PAGE}?utm_medium=email&utm_source=AvailabilityRequest )")

LEDGER = {
    "https://boards.greenhouse.io/klaviyo/jobs/1": {
        "id": "apply-klaviyo", "at": "2026-09-25T00:00:00Z", "company": "Klaviyo",
        "job_title": "Partner Account Manager — Klaviyo"},
    "https://boards.greenhouse.io/via/jobs/2": {
        "id": "apply-via", "at": "2026-09-26T00:00:00Z", "company": "Via",
        "job_title": "Business Development Representative, AI Labs — Via"},
}


def an_event(subject, sender="no-reply@klaviyo.com", message_id="<m@x>", event_id="evt-1"):
    return {"id": event_id, "kind": "mail.received", "summary": f"{subject} — from Someone",
            "subject": f"email:{sender}", "source": "mail",
            "attributes": {"sender": sender, "fingerprint": "abc", "message_id": message_id}}


class APoliteSubjectIsRead(unittest.TestCase):
    def setUp(self):
        self.heard, self.published, self.considered, self.bodies = [], [], [], {}
        patches = [
            mock.patch("aletheia.apply_run.already_sent", return_value=dict(LEDGER)),
            mock.patch.object(runtime, "_heard_back", side_effect=lambda i, s, o: self.heard.append((i, o))),
            mock.patch.object(runtime, "_fetch_body", side_effect=lambda mid: self.bodies.get(mid, "")),
            mock.patch("aletheia.mail.available", return_value=(True, "configured")),
            mock.patch("aletheia.mail.read_body", side_effect=mail.MailError("nothing unread")),
            mock.patch("aletheia.mail._config", return_value={"address": "caleb@openrange.example"}),
            mock.patch("aletheia.interviews.status", return_value={"on": True, "window": {}}),
            mock.patch("aletheia.interviews.consider",
                       side_effect=lambda event, entry, **kw: self.considered.append(kw) or {"state": "x"}),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        notes = mock.Mock()
        notes.publish.side_effect = lambda title, body, **kw: self.published.append((title, body, kw))
        p = mock.patch.object(runtime, "notifications", notes)
        p.start(); self.addCleanup(p.stop)

    def test_a_no_under_a_thank_you_is_a_rejection(self):
        self.bodies["<m@x>"] = ("Hi Caleb, Thank you for taking the time to apply for the Partner Account "
                                "Manager role at Klaviyo. After careful consideration, we have decided to move "
                                "forward with other candidates that better align with our needs.")
        out = runtime._job_reply(an_event("Thanks for applying to Klaviyo"))
        self.assertEqual(out, {"application": "apply-klaviyo", "outcome": "rejected"})
        self.assertEqual(self.heard, [("apply-klaviyo", "rejected")])
        self.assertEqual(self.published, [])

    def test_a_filled_position_is_a_rejection_too(self):
        self.bodies["<m@x>"] = ("Thank you for your interest in the role at Klaviyo! Unfortunately we just hired "
                                "someone for this role, so the position is no longer available.")
        out = runtime._job_reply(an_event("Thank you for your interest in Partner Account Manager at Klaviyo!"))
        self.assertEqual(out["outcome"], "rejected")

    def test_boilerplate_about_scheduling_stays_an_acknowledgement(self):
        self.bodies["<m@x>"] = ("Thanks for applying to Klaviyo! Our team reviews every application. If your "
                                "background is a match, we will reach out to schedule an interview.")
        out = runtime._job_reply(an_event("Thank you for applying to Klaviyo"))
        self.assertEqual(out["outcome"], "acknowledgement")
        self.assertEqual(self.published, [])

    def test_an_availability_page_inside_a_thank_you_reaches_him(self):
        self.bodies["<v@via>"] = "Thanks for applying to Via! Please add your times: " + VIA_PAGE
        out = runtime._job_reply(an_event("Thanks for applying to Via!", sender="people@ridewithvia.com",
                                          message_id="<v@via>"))
        self.assertEqual(out["outcome"], "wants_time")
        self.assertEqual(self.heard, [("apply-via", "wants_time")])
        self.assertEqual(len(self.published), 1)

    def test_an_unreadable_body_leaves_it_an_acknowledgement(self):
        out = runtime._job_reply(an_event("Thanks for applying to Klaviyo", message_id="<gone>"))
        self.assertEqual(out["outcome"], "acknowledgement")


class TheAvailabilityPage(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 7, 1, 0, tzinfo=dt.timezone.utc)   # Tuesday evening, Central
    WINDOW = {"start": "13:00", "end": "14:30", "timezone": "America/Chicago"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in ((mail, "MAIL_DIR", root / "mail"), (policy, "APPROVALS_DIR", root / "approvals"),
                                    (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(interviews, "status", return_value={"on": True, "window": dict(self.WINDOW)})
        p.start(); self.addCleanup(p.stop)

    def test_the_link_is_found_without_its_tracking(self):
        self.assertEqual(calendly.find_availability_links(VIA_BODY), [VIA_PAGE])
        self.assertEqual(calendly.find_scheduling_links(VIA_BODY), [])
        self.assertEqual(calendly.find_availability_links("https://boards.greenhouse.io/via/jobs/2"), [])
        self.assertEqual(calendly.find_availability_links("https://evil.example/availability/370f5c1bebde8f2c"), [])

    def consider(self, filler):
        marks, notices, drafted = [], [], []
        out = interviews.consider(
            {"id": "ev-via", "attributes": {"sender": "allie@ridewithvia.com"}},
            {"id": "apply-via", "company": "Via"}, subject="Still interested in interviewing with Via?",
            text=VIA_BODY, now=self.NOW, busy=lambda s, e: False,
            drafter=lambda *a: drafted.append(a), filler=filler,
            marker=lambda rid, outcome, note="": marks.append((rid, outcome, note)),
            notify=lambda title, body, **kw: notices.append((title, body, kw)),
            known={"full_name": "Caleb Schulte"})
        self.assertEqual(drafted, [], "a recruiter who asked for the page gets the page, not an email")
        return out, marks, notices

    def test_sent_in_his_window_and_he_is_told_which_days(self):
        seen = []
        out, marks, notices = self.consider(
            lambda url, **kw: seen.append((url, kw["window"])) or {"state": "sent", "days": ["2026-10-07", "2026-10-08"]})
        self.assertEqual(seen[0][0], VIA_PAGE)
        self.assertEqual(out["state"], "availability_sent")
        self.assertEqual(marks[0][:2], ("apply-via", "interview"))
        title, body, kw = notices[0]
        self.assertEqual(title, "Via has your interview times")
        self.assertIn("1 PM to 2:30 PM Central on Wednesday Oct 7, Thursday Oct 8", body)
        self.assertEqual(kw["about"], "FINISHED")

    def test_anything_short_of_sent_needs_him_with_the_link(self):
        for state in ({"state": "needs_grant", "days": ["2026-10-07"]}, {"state": "failed", "why": "no grid"},
                      {"state": "unconfirmed", "days": ["2026-10-07"]}):
            out, marks, notices = self.consider(lambda url, **kw: dict(state))
            self.assertEqual(out["state"], "availability_page", state)
            title, body, kw = notices[0]
            self.assertEqual(title, "Via wants to interview you")
            self.assertIn("1 PM to 2:30 PM Central", body)
            self.assertIn("Wednesday", body)
            self.assertIn(VIA_PAGE, body)
            self.assertEqual((kw["priority"], kw["about"]), ("URGENT", "NEEDS_YOU"))

    def test_a_filler_that_breaks_still_reaches_him(self):
        def boom(url, **kw):
            raise RuntimeError("browser died")
        out, marks, notices = self.consider(boom)
        self.assertEqual(out["state"], "availability_page")
        self.assertIn(VIA_PAGE, notices[0][1])


class _Handle:
    def __init__(self, box=None, text="", enabled=True, on_click=None):
        self.box, self.text, self.enabled, self.on_click = box, text, enabled, on_click

    def bounding_box(self):
        return self.box

    def inner_text(self):
        return self.text

    def get_attribute(self, name):
        return None

    def is_enabled(self):
        return self.enabled

    def click(self):
        if self.on_click:
            self.on_click()


class AGrid:
    """A week grid shaped the way FullCalendar renders one: rows with
    data-time every half hour from 08:00 (40px each), day columns with
    data-date. One week shows at a time; Next shows the following week."""
    ROW_H, TOP, COL_W, LEFT = 40, 100, 120, 60

    def __init__(self, first_monday: dt.date, *, submit_text="Submit Availability", after_submit="Thank you!"):
        self.monday, self.drags, self.submitted = first_monday, [], False
        self.submit_text, self.after_submit = submit_text, after_submit
        self.mouse = self
        self._down = None

    def goto(self, url, **kw):
        self.url = url

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass

    def screenshot(self, **kw):
        pass

    def query_selector(self, selector):
        import re as _re
        m = _re.search(r"data-time='(\d\d):(\d\d):00'", selector)
        if m:
            index = (int(m.group(1)) - 8) * 2 + int(m.group(2)) // 30
            return _Handle({"x": 0, "y": self.TOP + index * self.ROW_H, "width": 50, "height": self.ROW_H})
        m = _re.search(r"data-date='([\d-]+)'", selector)
        if m:
            day = dt.date.fromisoformat(m.group(1))
            offset = (day - self.monday).days
            if 0 <= offset < 7:
                return _Handle({"x": self.LEFT + offset * self.COL_W, "y": self.TOP, "width": self.COL_W,
                                "height": 800})
            return None
        if "next" in selector.casefold():
            return _Handle(text="Next", on_click=self._next)
        return None

    def _next(self):
        self.monday += dt.timedelta(days=7)

    def query_selector_all(self, selector):
        return [_Handle(text="Cancel"), _Handle(text=self.submit_text, on_click=self._submit)]

    def _submit(self):
        self.submitted = True

    def inner_text(self, selector):
        return self.after_submit if self.submitted else "Select times"

    # page.mouse
    def move(self, x, y, steps=1):
        self._at = (x, y)

    def down(self):
        self._down = self._at

    def up(self):
        (x0, y0), (x1, y1) = self._down, self._at
        day = self.monday + dt.timedelta(days=int((x0 - self.LEFT) // self.COL_W))
        def clock(y):
            half = int((y - self.TOP) // self.ROW_H)
            return f"{8 + half // 2:02d}:{(half % 2) * 30:02d}"
        self.drags.append((day.isoformat(), clock(y0), clock(y1)))


class MarkingThePage(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 7, 1, 0, tzinfo=dt.timezone.utc)    # Tuesday Oct 6, evening Central
    WINDOW = {"start": "13:00", "end": "14:30", "timezone": "America/Chicago"}

    def setUp(self):
        p = mock.patch("aletheia.journal.append")
        p.start(); self.addCleanup(p.stop)

    def test_his_window_on_every_free_weekday_then_submit_under_the_grant(self):
        from aletheia import availability_page
        page = AGrid(dt.date(2026, 10, 5))
        busy = lambda s, e: s.startswith("2026-10-09")          # Friday is taken
        out = availability_page.mark(VIA_PAGE, window=self.WINDOW, busy=busy, now=self.NOW, page=page,
                                     spender=lambda cap, act: "grant-1")
        self.assertEqual(out["state"], "sent")
        self.assertEqual(out["days"], ["2026-10-07", "2026-10-08", "2026-10-12", "2026-10-13",
                                       "2026-10-14", "2026-10-15", "2026-10-16"])
        # the drag starts inside the 1:00 row and ends inside the 2:00 row - 1:00 to 2:30
        self.assertEqual(page.drags[0], ("2026-10-07", "13:00", "14:00"))
        self.assertNotIn("2026-10-09", [d[0] for d in page.drags])
        self.assertTrue(page.submitted)

    def test_no_grant_means_nothing_is_sent(self):
        from aletheia import availability_page
        page = AGrid(dt.date(2026, 10, 5))
        out = availability_page.mark(VIA_PAGE, window=self.WINDOW, now=self.NOW, page=page,
                                     spender=lambda cap, act: None)
        self.assertEqual(out["state"], "needs_grant")
        self.assertFalse(page.submitted)
        self.assertTrue(page.drags)

    def test_a_page_that_is_not_a_grid_is_refused_without_pressing_anything(self):
        from aletheia import availability_page

        class Blank(AGrid):
            def query_selector(self, selector):
                return None
        page = Blank(dt.date(2026, 10, 5))
        out = availability_page.mark(VIA_PAGE, window=self.WINDOW, now=self.NOW, page=page,
                                     spender=lambda cap, act: "grant-1")
        self.assertEqual(out["state"], "failed")
        self.assertEqual((page.drags, page.submitted), ([], False))

    def test_a_page_that_does_not_thank_him_is_unconfirmed(self):
        from aletheia import availability_page
        page = AGrid(dt.date(2026, 10, 5), after_submit="Something went wrong, please try again")
        out = availability_page.mark(VIA_PAGE, window=self.WINDOW, now=self.NOW, page=page,
                                     spender=lambda cap, act: "grant-1")
        self.assertEqual(out["state"], "unconfirmed")

if __name__ == "__main__":
    unittest.main()
