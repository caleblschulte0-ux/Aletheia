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

    def test_the_page_needs_him_and_no_email_is_drafted(self):
        marks, notices, drafted = [], [], []
        out = interviews.consider(
            {"id": "ev-via", "attributes": {"sender": "allie@ridewithvia.com"}},
            {"id": "apply-via", "company": "Via"}, subject="Still interested in interviewing with Via?",
            text=VIA_BODY, now=self.NOW, busy=lambda s, e: False,
            drafter=lambda *a: drafted.append(a),
            marker=lambda rid, outcome, note="": marks.append((rid, outcome)),
            notify=lambda title, body, **kw: notices.append((title, body, kw)),
            known={"full_name": "Caleb Schulte"})
        self.assertEqual(out["state"], "availability_page")
        self.assertEqual(drafted, [])
        self.assertEqual(marks, [("apply-via", "interview")])
        title, body, kw = notices[0]
        self.assertEqual(title, "Via wants to interview you")
        self.assertIn("1 PM to 2:30 PM Central", body)
        self.assertIn("Wednesday", body)
        self.assertIn(VIA_PAGE, body)
        self.assertEqual(kw["priority"], "URGENT")
        self.assertEqual(kw["about"], "NEEDS_YOU")


if __name__ == "__main__":
    unittest.main()
