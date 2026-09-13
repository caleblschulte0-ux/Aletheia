"""A closed job stays closed, a job nobody judged is not a yes, and a click
that never landed is not a send.

All from his real applications on 2026-09-13, after his job preferences went
live:

- Dutchie "Account Manager, SMB" and impact.com "Creator Solutions Account
  Manager" were closed as not realistic at 15:40Z. The next batch found both
  again at the SAME url; `stage` keys a record by its url, rebuilt the closed
  records into fresh ones, and the grant sent them within the hour.
- The campaign asks a model about a bounded number of jobs; past the bound it
  judged with rules only and staged the rest as if a model had said yes.
  `retry_waiting` re-staged records nobody had ever judged (Nitra).
- "Forklift Operations Associate, Cherry Hill" came in under "Operations
  Analyst" and a model read "operations" in what he wants.
- "People Coordinator & Office Operations Associate (part-time)" was one
  answer away from being sent on the grant, unseen.
- MongoDB's confirmation page ("Thanks for taking the time to apply", titled
  "Thank you for applying", at .../confirmation) was reported unconfirmed.
- Nitra and Ro (Lever) timed out waiting for Submit to take a click, were
  counted as sent, and no confirmation ever came.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (apply_run, authority, browse, campaign, job_fit, journal,
                      notifications, profile, runtime, stateio)

import tests.test_apply_run as apply_base

RESUME = "Caleb Schulte. Business Development Associate. Construction operations 2019-2025."


class TimeoutError(Exception):          # Playwright's is named exactly this
    pass


class FakePage:
    def __init__(self, error=None):
        self.error = error

    def click(self, selector):
        if self.error:
            raise self.error


class ClosedStaysClosed(apply_base.ApplyCase):
    def ready_and_confirmed(self):
        out = self.staged(extra={"#felony": "No", "#cert": True})
        apply_run.confirm(out["id"])
        return out

    def test_filling_the_form_again_does_not_rebuild_a_closure(self):
        out = self.staged()
        apply_run.close(out["id"], "The posting requires 5+ years of account management")
        with self.assertRaises(apply_run.ApplyError):
            self.staged()
        self.assertEqual(apply_run.load_run(out["id"])["state"], "CLOSED")

    def test_reopening_is_a_decision_and_then_it_fills_again(self):
        out = self.staged()
        apply_run.close(out["id"], "requires 5+ years")
        reopened = apply_run.reopen(out["id"], "he said what work he wants since")
        self.assertEqual(reopened["closed_before"], "requires 5+ years")
        self.assertEqual(self.staged()["state"], "NEEDS_YOU")

    def test_a_closure_is_found_by_role_whatever_the_company_capitals(self):
        out = self.staged()
        apply_run.remember(out["id"], company="Impact.com",
                           job_title="Creator Solutions Account Manager — Impact.com")
        apply_run.close(out["id"], "requires 5+ years in creator marketing")
        self.assertIsNotNone(apply_run.closed_unfit(
            "impact.com", "Creator Solutions Account Manager — impact.com", "https://elsewhere/1"))

    def test_a_duplicate_closure_is_not_an_unfit_one(self):
        out = self.staged()
        apply_run.remember(out["id"], company="Brex", job_title="People Business Partner, GTM")
        apply_run.close(out["id"], "the same job is already waiting under another link")
        self.assertEqual(apply_run.closure_kind(apply_run.load_run(out["id"])), "duplicate")
        self.assertIsNone(apply_run.closed_unfit("Brex", "People Business Partner, GTM"))

    def test_a_part_time_job_says_so_wherever_it_is_named(self):
        self.assertEqual(apply_run.describe({"job_title": "Office Associate", "company": "Acme",
                                             "employment": "part-time"}),
                         "Office Associate at Acme (part-time)")
        self.assertEqual(
            apply_run.describe({"job_title": "Program Manager - Growth Operations, Contract",
                                "company": "Scale AI"}),
            "Program Manager - Growth Operations, Contract at Scale AI")

    def test_a_click_that_never_landed_is_not_a_send(self):
        out = self.ready_and_confirmed()
        never = TimeoutError('Page.click: Timeout 20000ms exceeded.\nCall log:\n'
                             '  - waiting for locator("#btn-submit")\n'
                             '    - locator resolved to <button id="btn-submit">\n'
                             '  - element is not enabled')

        def press(record):
            apply_run._press(FakePage(never), record, "#btn-submit")
            return {"verdict": "confirmed"}
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run.submit(out["id"], submitter=press)
        self.assertIn("nothing was sent", str(caught.exception))
        record = apply_run.load_run(out["id"])
        self.assertEqual(record["state"], "FAILED")
        self.assertNotIn("pressed_at", record)
        self.assertIsNone(apply_run.was_sent(record["url"]))

    def test_a_timeout_after_the_click_still_counts_as_maybe_sent(self):
        out = self.ready_and_confirmed()
        after = TimeoutError("Page.click: Timeout 20000ms exceeded.\nCall log:\n"
                             "  - waiting for scheduled navigations to finish")

        def press(record):
            apply_run._press(FakePage(after), record, "#btn-submit")
        record = apply_run.submit(out["id"], submitter=press)
        self.assertEqual(record["result"]["verdict"], "submitted, unconfirmed")

    def test_a_part_time_job_is_not_sent_on_the_grant(self):
        out = self.staged(extra={"#felony": "No", "#cert": True})
        apply_run.remember(out["id"], company="Bluevine",
                           job_title="People Coordinator & Office Operations Associate (part-time)")
        with mock.patch.object(authority, "satisfy", return_value="claim-1"), \
             mock.patch.object(runtime, "_submit_in_its_own_process",
                               side_effect=AssertionError("sent on the grant")):
            self.assertEqual(runtime.send_approved_applications(), [])
        titles = [n["title"] for n in notifications.all_notifications()]
        self.assertIn("A part-time job is waiting for your OK", titles)


class WhatKindOfWork(unittest.TestCase):
    WANTS = {"work_wanted": "business development, partnerships, account management, "
                            "customer success, operations, business operations, analyst roles"}

    def test_warehouse_shift_work_is_not_the_operations_he_asked_for(self):
        self.assertIn("shift work", job_fit.hard_reason(
            "Forklift Operations Associate, Cherry Hill", known=self.WANTS))
        self.assertEqual(job_fit.hard_reason("Business Operations Associate", known=self.WANTS), "")
        self.assertEqual(job_fit.hard_reason("Service Delivery Manager", known=self.WANTS), "")

    def test_it_is_his_words_that_decide(self):
        self.assertEqual(job_fit.hard_reason("Forklift Operations Associate", known={}), "")
        self.assertEqual(job_fit.hard_reason(
            "Warehouse Associate", known={"work_wanted": "warehouse work, operations"}), "")

    def test_the_kind_of_employment_is_read_not_decided(self):
        cases = {"People Coordinator & Office Operations Associate (part-time)": "part-time",
                 "Program Manager - Growth Operations, Contract": "contract",
                 "Summer Internship, Partnerships": "internship",
                 "Contract Manager": "", "Account Manager": ""}
        for title, kind in cases.items():
            self.assertEqual(job_fit.employment_type(title), kind, title)
        self.assertEqual(job_fit.employment_type("Office Associate",
                                                 "This is a part-time position, 20 hours."),
                         "part-time")

    def test_a_verdict_says_when_and_what_kind(self):
        said = job_fit.verdict({"title": "Office Associate (part-time)", "company": "Acme"},
                               RESUME, {}, think=False)
        self.assertEqual(said["employment"], "part-time")
        self.assertTrue(said["at"])


class AJudgmentIsOnlyAsCurrentAsHisWords(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for target, name, value in ((profile, "path", lambda: root / "answers.json"),
                                    (journal, "JOURNAL_PATH", root / "j.jsonl")):
            patch = mock.patch.object(target, name, value)
            patch.start(); self.addCleanup(patch.stop)

    def test_a_rules_yes_is_not_a_judgment_and_an_old_one_is_stale(self):
        profile.set_answer("work_not_wanted", "cold calling", source="operator")
        now = stateio.utcnow()
        self.assertTrue(job_fit.fit_is_current({"realistic": True, "by": "model", "at": now}))
        self.assertFalse(job_fit.fit_is_current({"realistic": True, "by": "", "at": now}))
        self.assertTrue(job_fit.fit_is_current({"realistic": False, "by": "rules", "at": now}))
        self.assertFalse(job_fit.fit_is_current(
            {"realistic": True, "by": "model", "at": "2026-09-13T15:40:00Z"}))
        self.assertFalse(job_fit.fit_is_current(None))


class TheCampaignKeepsItsDecisions(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for target, name, value in ((profile, "path", lambda: root / "answers.json"),
                                    (campaign, "LOCK_PATH", root / "running.json"),
                                    (campaign, "RUN_DIR", root),
                                    (journal, "JOURNAL_PATH", root / "j.jsonl")):
            patch = mock.patch.object(target, name, value)
            patch.start(); self.addCleanup(patch.stop)

    def run_with(self, pages, *, fit_think=False, closed=None, prefs_at="", count=5):
        tried, reopened = [], []

        def stager(url, resume="", note="", extra=None):
            tried.append(url)
            return {"id": url, "url": url, "state": "NEEDS_YOU", "questions": []}
        with mock.patch.object(campaign, "read_resume", return_value=("resume.pdf", RESUME)), \
             mock.patch.object(apply_run, "all_runs", return_value=[]), \
             mock.patch.object(apply_run, "role_taken", return_value=None), \
             mock.patch.object(apply_run, "closed_unfit",
                               side_effect=lambda company, title, url="": closed), \
             mock.patch.object(apply_run, "reopen",
                               side_effect=lambda rid, why: reopened.append(rid)), \
             mock.patch.object(job_fit, "preferences_changed_at", return_value=prefs_at):
            out = campaign.run("Account Manager", count=count, json_think=False,
                               searcher=lambda roles, **kw: {"matches": pages, "searched": 1},
                               stager=stager, draft_essays_too=False, fit_think=fit_think)
        return tried, reopened, out

    DUTCHIE = [{"apply_url": "https://dutchie/8555119002", "company": "Dutchie",
                "title": "Account Manager, SMB"}]
    CLOSED = {"id": "apply-102e3241", "url": "https://dutchie/8555119002",
              "closed_at": "2026-09-13T15:40:00Z",
              "closed_because": "The role requires 5+ years in account management"}

    @staticmethod
    def says(realistic):
        def think(system, text, **kw):
            return kw["validator"]({"realistic": realistic, "why": "read again"})
        return think

    def test_a_job_closed_since_he_last_spoke_stays_closed(self):
        tried, reopened, out = self.run_with(self.DUTCHIE, fit_think=self.says(True),
                                             closed=self.CLOSED, prefs_at="2026-09-13T15:00:00Z")
        self.assertEqual((tried, reopened), ([], []))
        self.assertIn("5+ years", out["passed_over"][0]["why"])

    def test_after_he_changes_what_he_wants_a_model_may_reopen_it(self):
        tried, reopened, _ = self.run_with(self.DUTCHIE, fit_think=self.says(True),
                                           closed=self.CLOSED, prefs_at="2026-09-13T16:40:00Z")
        self.assertEqual(reopened, ["apply-102e3241"])
        self.assertEqual(tried, ["https://dutchie/8555119002"])

    def test_but_never_the_rules_alone(self):
        tried, reopened, _ = self.run_with(self.DUTCHIE, fit_think=False,
                                           closed=self.CLOSED, prefs_at="2026-09-13T16:40:00Z")
        self.assertEqual((tried, reopened), ([], []))

    def test_a_job_the_bound_kept_from_a_model_waits_for_a_later_batch(self):
        pages = [{"apply_url": f"https://c{i}/1", "company": f"C{i}", "title": "Account Manager"}
                 for i in range(12)]
        tried, _, out = self.run_with(pages, fit_think=self.says(False), count=1)
        self.assertEqual(tried, [])
        self.assertEqual(len(out["passed_over"]), campaign.TRIES_PER_READY * 2)
        self.assertTrue(out["later"])

    def test_a_job_no_model_could_read_is_not_staged_as_a_yes(self):
        def out_of_service(system, text, **kw):
            raise RuntimeError("both subscriptions resting")
        tried, _, out = self.run_with(self.DUTCHIE, fit_think=out_of_service)
        self.assertEqual(tried, [])
        self.assertEqual(len(out["later"]), 1)

    def test_retrying_waiting_ones_judges_them_first(self):
        record = {"id": "apply-68f577d6", "state": "NEEDS_YOU", "url": "https://nitra/1",
                  "company": "Nitra", "job_title": "Account Manager (NitraMart) — Nitra"}
        closed = []
        with mock.patch.object(apply_run, "all_runs",
                               side_effect=lambda state=None: [record] if state == "NEEDS_YOU" else []), \
             mock.patch.object(apply_run, "close", side_effect=lambda rid, why: closed.append(rid)), \
             mock.patch.object(campaign, "read_resume", return_value=("resume.pdf", RESUME)), \
             mock.patch.object(campaign.policy, "ensure_not_halted"):
            out = campaign.retry_waiting(stager=lambda *a, **k: self.fail("filled in unjudged"),
                                         json_think=False, writer=False,
                                         fit_think=self.says(False), describer=lambda job: "")
        self.assertEqual(closed, ["apply-68f577d6"])
        self.assertEqual(out["ready"] + out["blocked"], [])


class WhatThePageSaidAfter(unittest.TestCase):
    MONGODB = ("Thanks for taking the time to apply to MongoDB!\nIn the meantime while we "
               "review your application, please check out the latest articles.")

    def test_mongodbs_confirmation_is_a_confirmation(self):
        self.assertEqual(browse.read_outcome(self.MONGODB, did="submit")["verdict"], "confirmed")

    def test_the_title_and_the_address_of_a_confirmation_page_count(self):
        self.assertEqual(browse.read_outcome("View more jobs", title="Thank you for applying")
                         ["verdict"], "confirmed")
        self.assertEqual(browse.read_outcome(
            "View more jobs",
            url="https://job-boards.greenhouse.io/embed/job_app/confirmation?for=x&token=1")
            ["verdict"], "confirmed")

    def test_silence_is_still_not_a_confirmation(self):
        self.assertEqual(browse.read_outcome("Resume/CV *  Submit application")["verdict"],
                         "submitted, unconfirmed")
        self.assertEqual(browse.read_outcome("View more jobs", title="Thank you for applying",
                                             form_still_there=True)["verdict"], "rejected")


if __name__ == "__main__":
    unittest.main()
