"""His words, 2026-10-02: *"she's not watching my inbox, scheduling me
meetings, like... She sucks. Fix it."*

Four things were true in the code that morning, and each is a test here:

- the inbox poll asked IMAP for UNSEEN mail only, and he reads his mail on
  his phone - an employer's "are you free Thursday?" opened within five
  minutes was never seen by her;
- an employer's reply was matched by its SUBJECT against the sent ledger
  and nothing else - "Interview request" from careers@gong.io matched
  nothing, and a recruiter about a job he never applied to was nobody;
- a decline was "recognised and let go" and never written down;
- interview scheduling was OFF by default (nine days after he asked for
  it), and when on, the reply was HELD in silence where only "what have
  you drafted" found it, under an outward-mail hold that also refused the
  send he would have tapped.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from aletheia import events, hunt_funnel, interviews, journal, mail, policy, rulings, runtime


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in ((mail, "MAIL_DIR", root / "mail"), (policy, "APPROVALS_DIR", root / "approvals"),
                                    (journal, "JOURNAL_PATH", root / "journal.jsonl"),
                                    (events, "EVENTS_DIR", root / "events"), (events, "WATCHERS_DIR", root / "watchers")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)


# ---- the inbox is read by date, not by the unread flag -------------------------------

class ByDate:
    """A transport that can list by date. `fetch_unread` must not be the poll's question any more."""
    rehearsal_safe = True

    def __init__(self, rows):
        self.rows = rows
        self.asked = []

    def fetch_unread(self, limit):
        raise AssertionError("the poll must read by date, not by the unread flag")

    def fetch_since(self, since_epoch, limit):
        self.asked.append(since_epoch)
        return self.rows[:limit]


class UnreadOnly:
    def __init__(self, rows):
        self.rows = rows

    def fetch_unread(self, limit):
        return self.rows[:limit]


def a_mail(n, subject="Interview request", sender="careers@gong.io"):
    return {"from": f"Gong Careers <{sender}>", "subject": subject,
            "date": "Thu, 02 Oct 2026 14:00:00 +0000", "message_id": f"<m{n}@gong.io>"}


class TheInboxIsReadByDate(Isolated):
    def test_the_poll_asks_for_recent_mail_read_or_unread(self):
        driver = ByDate([a_mail(1)])
        mail.poll_events(transport=driver)                       # baseline
        driver.rows = [a_mail(1), a_mail(2, "Re: your application")]
        before = time.time()
        actions = mail.poll_events(transport=driver)
        self.assertEqual([a["action"] for a in actions], ["received"])
        self.assertAlmostEqual(driver.asked[-1], before - mail.POLL_LOOKBACK_S, delta=5)
        # and the event carries the Message-ID, so the body can be read later
        from aletheia import events
        kinds = [e for e in events.list_events(limit=10) if e["kind"] == "mail.received"]
        self.assertEqual(kinds[0]["attributes"]["message_id"], "<m2@gong.io>")

    def test_a_transport_without_dates_is_still_polled_by_the_unread_flag(self):
        driver = UnreadOnly([a_mail(1)])
        self.assertEqual(mail.poll_events(transport=driver), [{"action": "baseline", "count": 1}])
        driver.rows = [a_mail(1), a_mail(3)]
        self.assertEqual([a["action"] for a in mail.poll_events(transport=driver)], ["received"])

    def test_one_message_is_one_event_however_long_it_stays_in_the_window(self):
        driver = ByDate([])
        mail.poll_events(transport=driver)
        driver.rows = [a_mail(4)]
        self.assertEqual(len(mail.poll_events(transport=driver)), 1)
        self.assertEqual(mail.poll_events(transport=driver), [])


# ---- a reply he must tap asks for the tap, under the hold -------------------------------

class Sent:
    rehearsal_safe = True

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append((msg["To"], msg["Subject"]))


class AReplyAsksForHisTapUnderTheHold(Isolated):
    def test_asks_anyway_files_the_approval_and_the_tap_sends_it(self):
        self.assertTrue(mail.outward_hold()["on"])
        d = mail.draft("recruiter@fin.ai", "Re: Interview", "Wednesday works.", requested_via="interviews",
                       asks_anyway=True, about="apply-1")
        self.assertFalse(d.get("held"))
        self.assertTrue(d["his_tap"])
        self.assertEqual(policy.load(d["id"])["state"], "PENDING")
        self.assertEqual(mail.held_drafts(), [])
        out = Sent()
        self.assertEqual(mail.send_approved(out), [])               # not yet: no tap
        time.sleep(1.1)                                              # `created` is to the second
        policy.decide(d["id"], "APPROVED", via="phone", because="he tapped send")
        results = mail.send_approved(out)
        self.assertEqual([r["outcome"] for r in results], ["sent"])
        self.assertEqual(out.sent, [("recruiter@fin.ai", "Re: Interview")])

    def test_an_ordinary_draft_under_the_hold_is_still_held(self):
        d = mail.draft("someone@example.com", "Hello", "Body")
        self.assertTrue(d["held"])
        self.assertEqual(mail.send_approved(Sent()), [])

    def test_an_old_approval_from_before_the_hold_still_does_not_go(self):
        mail.lift_hold(via="test")
        d = mail.draft("someone@example.com", "Hello", "Body")
        policy.decide(d["id"], "APPROVED", via="test")
        mail.hold_outward(quote="that is on hold", via="test")
        out = Sent()
        self.assertEqual(mail.send_approved(out), [])
        self.assertEqual(out.sent, [])


# ---- an employer's reply is matched by sender and body, and a decline is written down ----

LEDGER = {
    "https://boards.greenhouse.io/embed/job_app?for=gongio&token=1": {
        "id": "apply-gong", "at": "2026-09-30T02:03:17Z", "company": "Gong",
        "job_title": "Account Executive - Private Equity — Gong"},
    "https://jobs.lever.co/fin/123/apply": {
        "id": "apply-fin", "at": "2026-09-29T03:14:50Z", "company": "Fin",
        "job_title": "Customer Success Manager — Fin"},
}


def an_event(subject, sender="", event_id="evt-1", message_id="<x@y>"):
    return {"id": event_id, "kind": "mail.received", "summary": f"{subject} — from Someone",
            "subject": f"email:{sender or 'unknown'}", "source": "mail",
            "attributes": {"sender": sender, "fingerprint": "abc", "message_id": message_id}}


class AnEmployerIsKnownByItsDomainAndItsWords(unittest.TestCase):
    def setUp(self):
        self.published = []
        self.heard = []
        self.considered = []
        self.bodies = {}
        patches = [
            mock.patch("aletheia.apply_run.already_sent", return_value=dict(LEDGER)),
            mock.patch.object(runtime, "_heard_back", side_effect=lambda i, s, o: self.heard.append((i, o))),
            mock.patch.object(runtime, "_fetch_body", side_effect=lambda mid: self.bodies.get(mid, "")),
            mock.patch("aletheia.mail.available", return_value=(True, "configured")),
            mock.patch("aletheia.mail.read_body", side_effect=mail.MailError("nothing unread")),
            mock.patch("aletheia.mail._config", return_value={"address": "caleb@openrange.example"}),
            mock.patch("aletheia.employers.about", side_effect=lambda name: (
                {"name": "Gong", "domains": ["gong.io"]} if name == "Gong" else None)),
            mock.patch("aletheia.interviews.status", return_value={"on": True, "window": {}}),
            mock.patch("aletheia.interviews.consider",
                       side_effect=lambda event, entry, **kw: self.considered.append((entry, kw)) or {"state": "drafted"}),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        notes = mock.Mock()
        notes.publish.side_effect = lambda title, body, **kw: self.published.append((title, body, kw))
        notes.CHANGED = "changed"
        p = mock.patch.object(runtime, "notifications", notes)
        p.start(); self.addCleanup(p.stop)

    def test_the_senders_domain_names_the_employer_when_the_subject_does_not(self):
        out = runtime._job_reply(an_event("Interview request", sender="talent@gong.io"))
        self.assertEqual(out["outcome"], "wants_time")
        self.assertEqual(out["company"], "Gong")
        self.assertEqual(self.heard, [("apply-gong", "wants_time")])
        self.assertEqual(self.published[0][0], "Gong wants to talk")
        self.assertEqual(self.considered[0][0]["id"], "apply-gong")

    def test_an_applicant_tracking_systems_domain_is_nobodys(self):
        # greenhouse-mail.io is where every Greenhouse employer's mail comes from
        self.bodies["<g@gh>"] = "Hi Caleb, thanks for your interest. We will be in touch."
        out = runtime._job_reply(an_event("Hello", sender="no-reply@greenhouse-mail.io", message_id="<g@gh>"))
        self.assertIsNone(out)

    def test_the_body_names_the_employer_when_neither_subject_nor_sender_does(self):
        self.bodies["<b@fin>"] = ("Hi Caleb,\n\nThanks for applying to Fin for the Customer Success Manager "
                                  "role. Are you free Thursday at 2pm Central for a quick call?\n\nDana")
        out = runtime._job_reply(an_event("Re: your application", sender="dana@talentpartners.example",
                                          message_id="<b@fin>"))
        self.assertEqual(out["outcome"], "wants_time")
        self.assertEqual(out["company"], "Fin")
        self.assertEqual(self.considered[0][1]["text"][:9], "Hi Caleb,")

    def test_a_decline_is_recorded_and_raises_no_alarm(self):
        out = runtime._job_reply(an_event("Unfortunately, an update on your Gong application"))
        self.assertEqual(out, {"application": "apply-gong", "outcome": "rejected"})
        self.assertEqual(self.heard, [("apply-gong", "rejected")])
        self.assertEqual(self.published, [])

    def test_somebody_else_asking_about_a_job_reaches_him_and_the_interview_path(self):
        out = runtime._job_reply(an_event("Opportunity: a Sales Director role - are you available this week?",
                                          sender="maya@brightrecruiting.example"))
        self.assertEqual(out["outcome"], "wants_time")
        self.assertIsNone(out["application"])
        self.assertEqual(self.published[0][0], "Brightrecruiting wants to talk")
        self.assertEqual(self.considered[0][0]["id"], "")
        self.assertEqual(self.considered[0][0]["sender"], "maya@brightrecruiting.example")

    def test_a_mailbox_nobody_answers_is_noticed_but_not_replied_to(self):
        out = runtime._job_reply(an_event("Maya sent you a message: interview for an AE role",
                                          sender="messages-noreply@linkedin.com"))
        self.assertEqual(out["outcome"], "wants_time")
        self.assertIn("nobody can answer", self.published[0][1])
        self.assertEqual(self.considered, [])

    def test_mail_about_nothing_he_applied_to_and_not_about_a_job_is_left_alone(self):
        self.assertIsNone(runtime._job_reply(an_event("Your order has shipped", sender="orders@shop.example")))
        self.assertEqual(self.published, [])

    def test_his_own_mail_is_never_a_reply(self):
        self.assertIsNone(runtime._job_reply(an_event("Gong interview notes", sender="caleb@openrange.example")))


# ---- his rulings are data, and the grant follows the ruling --------------------------------

class HisRulingsAreData(unittest.TestCase):
    def test_the_interviews_ruling_carries_his_words(self):
        ruling = rulings.for_switch("interviews")
        self.assertTrue(ruling["on"])
        self.assertEqual(ruling["window"]["timezone"], "America/Chicago")
        self.assertIn("Fix it", rulings.quote(ruling))
        self.assertIn("2026-09-23", rulings.quote(ruling))

    def test_a_broken_or_wordless_ruling_grants_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rulings.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(rulings.load(path), [])
            path.write_text(json.dumps({"rulings": [{"id": "x", "switch": "interviews", "on": True}]}), encoding="utf-8")
            self.assertEqual(rulings.load(path), [])                       # no words of his: not a ruling
            path.write_text(json.dumps({"rulings": [{"id": "x", "switch": "spending", "on": True,
                                                     "quotes": [{"on": "2026-10-02", "said": "spend"}]}]}),
                            encoding="utf-8")
            self.assertEqual(rulings.load(path), [])                       # not a switch a ruling may touch

    def test_the_beat_creates_the_interviews_grant_from_the_ruling_once(self):
        runtime._RULINGS_CHECKED["at"] = 0.0
        with mock.patch("aletheia.interviews.status",
                        return_value={"on": True, "window": {}, "ruled_by": "interviews-on", "quote": "q"}), \
             mock.patch("aletheia.standing.interviews_active", return_value=None), \
             mock.patch("aletheia.standing.interviews_enable", return_value={"id": "standing-interviews-1"}) as enable, \
             mock.patch("aletheia.journal.append"):
            out = runtime._apply_rulings(now_s=1000.0)
            self.assertEqual(out, [{"ruling": "interviews-on", "grant": "standing-interviews-1"}])
            self.assertEqual(enable.call_args.kwargs["via"], "ruling:interviews-on")
            self.assertIn("Fix it", enable.call_args.kwargs["quote"])
            # rate-limited: the next beat does not list the grants again
            self.assertEqual(runtime._apply_rulings(now_s=1001.0), [])

    def test_his_keyboard_wins_over_the_ruling(self):
        runtime._RULINGS_CHECKED["at"] = 0.0
        with mock.patch("aletheia.interviews.status", return_value={"on": False, "window": {}}), \
             mock.patch("aletheia.standing.interviews_enable") as enable:
            self.assertEqual(runtime._apply_rulings(now_s=5000.0), [])
            self.assertFalse(enable.called)


# ---- the hunt's numbers reach the morning brief --------------------------------------------

ROWS = [
    {"id": "a1", "state": "SUBMITTED", "staged_at": "2026-09-30T15:00:00Z", "submitted_at": "2026-09-30T15:30:00Z",
     "outcomes": [{"outcome": "replied", "at": "2026-10-01T14:00:00Z"},
                  {"outcome": "interview", "at": "2026-10-01T16:00:00Z"}]},
    {"id": "a2", "state": "SUBMITTED", "staged_at": "2026-09-30T16:00:00Z", "submitted_at": "2026-09-30T16:30:00Z",
     "outcomes": [{"outcome": "rejected", "at": "2026-10-01T18:00:00Z"}]},
    {"id": "a3", "state": "NEEDS_YOU", "staged_at": "2026-10-01T10:00:00Z"},
    {"id": "a4", "state": "CLOSED", "staged_at": "2026-10-01T11:00:00Z"},
]
NOW = dt.datetime(2026, 10, 2, 12, 0, tzinfo=dt.timezone.utc)


class TheHuntReachesTheBrief(unittest.TestCase):
    def test_counts_are_counts_and_nothing_else(self):
        with mock.patch("aletheia.localtime.operator_tz", return_value=dt.timezone.utc):
            out = hunt_funnel.counts(ROWS, now=NOW)
        self.assertEqual(out["days"]["2026-09-30"], {"found": 2, "filled": 2, "sent": 2, "replies": 0,
                                                     "interviews": 0, "rejections": 0})
        self.assertEqual(out["days"]["2026-10-01"], {"found": 2, "filled": 1, "sent": 0, "replies": 3,
                                                     "interviews": 1, "rejections": 1})
        self.assertEqual(out["totals"]["sent"], 2)
        self.assertNotIn("a1", json.dumps(out))                                  # no ids, no names, no urls

    def test_published_once_per_change_and_read_by_the_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "funnel.json"
            hunt_funnel._LAST["at"] = 0.0
            with mock.patch("aletheia.apply_run.all_runs", return_value=ROWS), \
                 mock.patch("aletheia.localtime.operator_tz", return_value=dt.timezone.utc):
                self.assertTrue(hunt_funnel.publish(now=NOW, clock=lambda: 10_000.0, path=path))
                self.assertIsNone(hunt_funnel.publish(now=NOW, clock=lambda: 20_000.0, path=path))   # unchanged
                lines = hunt_funnel.words(hunt_funnel.read(path), now=NOW)
        self.assertEqual(lines[0], "## Job hunt")
        self.assertIn("**Yesterday:** 0 sent, 3 heard back, 1 interview(s)", lines[1])
        self.assertIn("**Last 7 days:** 2 sent, 3 heard back, 1 interview(s), 1 said no", lines[2])

    def test_the_brief_falls_back_to_the_published_funnel(self):
        from aletheia import brief
        funnel = {"days": {"2026-10-01": {"found": 3, "filled": 3, "sent": 3, "replies": 0, "interviews": 0,
                                           "rejections": 0}}, "totals": {}}
        with mock.patch("aletheia.current_state.job_hunt", return_value={"readable": True, "today": {}}), \
             mock.patch("aletheia.hunt_funnel.read", return_value=funnel), \
             mock.patch("aletheia.localtime.operator_tz", return_value=dt.timezone.utc):
            lines = brief._job_hunt_lines()
        self.assertEqual(lines[0], "## Job hunt")
        self.assertTrue(any("no interview yet" in line for line in lines), lines)


# ---- a cover letter is a letter ------------------------------------------------------------

class ACoverLetterIsALetter(unittest.TestCase):
    def test_a_cover_letter_box_gets_the_letter_brief(self):
        from aletheia import campaign
        prompts = []

        def think(prompt, resume, timeout_s=0.0):
            prompts.append(prompt)
            return "Hello,\n\nA letter." if "cover letter" in prompt.casefold() else "Two sentences."
        record = {"url": "https://jobs.example/1", "job_title": "Account Executive — Acme",
                  "questions": [{"type": "textarea", "selector": "#cl", "label": "Cover Letter (optional)"},
                                {"type": "textarea", "selector": "#why", "label": "Why Acme?"}]}
        with mock.patch("aletheia.formfill.is_anti_bot", return_value=False), \
             mock.patch.object(campaign, "_essay_facts", return_value="(none)"):
            drafted = campaign.draft_essays(record, "RESUME", think=think)
        self.assertEqual(drafted, {"#cl": "Hello,\n\nA letter.", "#why": "Two sentences."})
        self.assertIn("150 to 220 words", prompts[0])
        self.assertNotIn("150 to 220 words", prompts[1])


if __name__ == "__main__":
    unittest.main()
