"""What the standing grant may send, and what counts as sent.

2026-09-13, two defects in one afternoon:

- Bluevine's "People Coordinator & Office Operations Associate (part-time)"
  went out on the standing grant. The not-full-time check lived only in the
  Core's beat, for approvals still open - but `stage` spends the grant the
  moment a form is filled, so the record arrived at the beat already
  APPROVED and the check never ran. Part-time, contract, temporary, seasonal
  and internship work waits for HIS OWN yes, on every path.
- Datadog's "GTM Operations Associate" page handed the form back, and the
  record was marked SUBMITTED and written into the sent ledger: counted as
  an application, and never to be tried again. A refusal is not a sent
  application - but the same answers are not pressed a second time either.
"""
from __future__ import annotations

from unittest import mock

from aletheia import apply_run, notifications, policy, runtime, stateio

import tests.test_apply_run as base

READY = {"#felony": "No", "#cert": True}


class _Case(base.ApplyCase):
    def grant_approved(self, out, title):
        approval = policy.load(out["approval"])
        approval.update({"state": "APPROVED", "decided_via": "grant:apply-nonstop"})
        policy.save(approval)
        record = apply_run.load_run(out["id"])
        record["job_title"] = title
        stateio.write_json_atomic(apply_run._record_path(out["id"]), record)
        return record


class OnlyHisYesSendsWorkThatIsNotFullTime(_Case):
    def test_staging_does_not_spend_the_grant_on_a_part_time_job(self):
        with mock.patch.object(policy, "request", wraps=policy.request) as asked:
            out = self.staged(extra=READY,
                              note="Apply: Office Operations Associate (part-time) — Acme — https://x")
        self.assertEqual(out["state"], "AWAITING_YOU")
        self.assertIsNone(asked.call_args.kwargs.get("capability"))
        self.assertEqual(policy.load(out["approval"])["state"], "PENDING")

    def test_the_path_that_sent_bluevine_now_holds_it_and_says_why(self):
        out = self.staged(extra=READY)
        self.grant_approved(out, "People Coordinator & Office Operations Associate (part-time) — Bluevine")
        said = []
        with mock.patch.object(runtime, "_submit_in_its_own_process",
                               side_effect=AssertionError("sent on the grant")), \
             mock.patch.object(notifications, "publish",
                               side_effect=lambda title, *a, **k: said.append(title)):
            self.assertEqual(runtime.send_approved_applications(), [])
        self.assertTrue(any("part-time" in t for t in said), said)
        self.assertEqual(apply_run.load_run(out["id"])["state"], "AWAITING_YOU")

    def test_his_own_yes_still_sends_it(self):
        out = self.staged(extra=READY)
        self.grant_approved(out, "Office Operations Associate (part-time) — Acme")
        approval = policy.load(out["approval"])
        approval["decided_via"] = "phone"
        policy.save(approval)
        pressed = []
        with mock.patch.object(runtime, "_submit_in_its_own_process",
                               side_effect=lambda run_id, **k: pressed.append(run_id)
                               or apply_run.load_run(run_id)), \
             mock.patch.object(notifications, "publish"):
            runtime.send_approved_applications()
        self.assertEqual(pressed, [out["id"]])

    def test_submit_itself_refuses_a_grant_approved_part_time_job(self):
        out = self.staged(extra=READY)
        record = self.grant_approved(out, "Seasonal Operations Associate — Acme")
        record["state"] = "APPROVED"
        stateio.write_json_atomic(apply_run._record_path(out["id"]), record)
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run.submit(out["id"], submitter=lambda r: self.fail("pressed"))
        self.assertIn("your own OK", str(caught.exception))
        self.assertEqual(apply_run.load_run(out["id"])["state"], "AWAITING_YOU")


class ARefusedFormIsNotASentApplication(_Case):
    def ready_and_confirmed(self):
        out = self.staged(extra=READY)
        apply_run.confirm(out["id"])
        return out

    def test_it_is_kept_apart_and_out_of_the_ledger(self):
        out = self.ready_and_confirmed()
        with self.assertRaises(apply_run.ApplyError):
            apply_run.submit(out["id"], submitter=lambda r: {
                "verdict": "rejected", "note": "The site handed it back rather than accepting it"})
        record = apply_run.load_run(out["id"])
        self.assertEqual(record["state"], apply_run.REJECTED)
        self.assertIn("handed it back", record["failure"])
        self.assertIsNone(apply_run.was_sent(record["url"]), "a refusal is not in his count")

    def test_a_ledger_entry_already_marked_rejected_is_not_counted(self):
        stateio.write_json_atomic(apply_run.sent_path(), {
            "https://refused.example/1": {"id": "apply-a", "verdict": "rejected"},
            "https://maybe.example/2": {"id": "apply-b", "verdict": "submitted, unconfirmed"}})
        self.assertIsNone(apply_run.was_sent("https://refused.example/1"))
        self.assertIsNotNone(apply_run.was_sent("https://maybe.example/2"),
                             "a send that may have landed still counts - duplicates are worse")

    def test_a_page_that_refused_is_not_counted_by_the_employer_reply_matcher_either(self):
        out = self.ready_and_confirmed()
        with self.assertRaises(apply_run.ApplyError):
            apply_run.submit(out["id"], submitter=lambda r: {"verdict": "rejected", "note": "no"})
        self.assertNotIn(out["url"], apply_run.already_sent())

    def test_the_same_answers_are_not_pressed_again(self):
        out = self.ready_and_confirmed()
        with self.assertRaises(apply_run.ApplyError):
            apply_run.submit(out["id"], submitter=lambda r: {"verdict": "rejected", "note": "no"})
        with self.assertRaises(apply_run.ApplyError) as caught:
            self.staged(extra=READY)
        self.assertIn("same answers", str(caught.exception))
