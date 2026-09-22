"""An application becomes an opportunity with its evidence, and what the
employer says reaches it - the job hunt's door into `pursuit`."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import pursuit, pursuit_applications as pa

NOW = dt.datetime(2026, 9, 21, 15, 0, tzinfo=dt.timezone.utc)

RECORD = {"id": "apply-0078e378", "state": "SUBMITTED", "url": "https://example.com/apply/1",
          "posting": "https://example.com/careers/1", "company": "Acme", "job_title": "Partnerships Lead",
          "found_on": "the company's own careers page", "submitted_at": "2026-09-12T18:47:04Z",
          "fit": {"realistic": True, "why": "he manages funding partners today", "by": "rules"},
          "filled": [{"label": "Name", "value": "x"}], "not_filled": [], "outcomes": []}


class ApplicationsBecomeOpportunitiesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        (base / "opportunities").mkdir()
        self.patches = [
            mock.patch.object(pursuit, "store_dir", return_value=base / "opportunities"),
            mock.patch("aletheia.journal.append"),
            mock.patch("aletheia.apply_run.all_runs", return_value=[RECORD]),
            mock.patch("aletheia.apply_run.load_run", return_value=dict(RECORD)),
            mock.patch("aletheia.profile.known", return_value={"current_title": "Funding Manager",
                                                                "gender": "never travels"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_the_evidence_is_the_record_the_posting_his_background_and_his_facts(self):
        opp = pa.open_from_application(RECORD, now=NOW, posting=lambda r: "We seek a partnerships lead.",
                                       resume=lambda: "Caleb manages funding partners.")
        kinds = [e["kind"] for e in opp["evidence"]]
        self.assertEqual(kinds, ["application", "posting", "his background", "his facts"])
        self.assertIn("Partnerships Lead", opp["subject"]["name"])
        self.assertIn("Acme", opp["objective"])
        posting = next(e for e in opp["evidence"] if e["kind"] == "posting")
        self.assertEqual(posting["provenance"], pursuit.UNTRUSTED)
        facts = next(e for e in opp["evidence"] if e["kind"] == "his facts")
        self.assertIn("Funding Manager", facts["text"])
        self.assertNotIn("gender", facts["text"])

    def test_the_open_questions_are_named_not_counted(self):
        # The first live pass guessed one blank field "could be disqualifying"
        # and told him to go and look: the count was all the evidence said.
        record = {**RECORD, "not_filled": [{"label": "Years of customer success experience",
                                            "required": True, "selector": "#q1"}]}
        opp = pa.open_from_application(record, now=NOW, posting=lambda r: "P", resume=lambda: "R")
        text = next(e for e in opp["evidence"] if e["kind"] == "application")["text"]
        self.assertIn("Open question on the form (required): Years of customer success experience", text)

    def test_opening_again_adds_no_second_copy(self):
        a = pa.open_from_application(RECORD, now=NOW, posting=lambda r: "P", resume=lambda: "R")
        b = pa.open_from_application(RECORD, now=NOW, posting=lambda r: "P", resume=lambda: "R")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(b["evidence"]), 4)

    def test_sync_opens_live_applications_once(self):
        with mock.patch.object(pa, "_posting", return_value="P"), \
             mock.patch.object(pa, "_resume", return_value="R"):
            first = pa.sync(now=NOW)
            second = pa.sync(now=NOW)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_a_form_waiting_on_him_opens_nothing_and_parks_what_is_open(self):
        # 240 opportunities out of one night's records, most of them forms
        # waiting on his answers: nothing to pursue until he answers.
        waiting = {**RECORD, "id": "apply-1", "url": "https://example.com/apply/w", "state": "NEEDS_YOU"}
        with mock.patch("aletheia.apply_run.all_runs", return_value=[waiting]), \
             mock.patch.object(pa, "_posting", return_value="P"), mock.patch.object(pa, "_resume", return_value="R"):
            self.assertEqual(pa.sync(now=NOW), [])
            opp = pa.open_from_application({**waiting, "state": "SUBMITTED"}, now=NOW,
                                           posting=lambda r: "P", resume=lambda: "R")
            pa.sync(now=NOW)
        fresh = pursuit.load(opp["id"])
        self.assertEqual(fresh["state"], pursuit.PARKED)
        self.assertIn("only he can answer", fresh["next_look"]["because"])

    def test_a_closed_or_failed_application_ends_its_opportunity(self):
        opp = pa.open_from_application(RECORD, now=NOW, posting=lambda r: "P", resume=lambda: "R")
        with mock.patch("aletheia.apply_run.all_runs", return_value=[{**RECORD, "state": "CLOSED"}]), \
             mock.patch.object(pa, "_posting", return_value="P"), mock.patch.object(pa, "_resume", return_value="R"):
            pa.sync(now=NOW)
        fresh = pursuit.load(opp["id"])
        self.assertEqual(fresh["state"], pursuit.CLOSED)
        self.assertEqual(fresh["outcome"]["kind"], "dropped")

    def test_an_employers_reply_is_written_on_the_application_and_heard_by_the_opportunity(self):
        with mock.patch.object(pa, "_posting", return_value="P"), \
             mock.patch.object(pa, "_resume", return_value="R"), \
             mock.patch("aletheia.apply_run.mark") as marked:
            opp = pa.heard_back("apply-0078e378", "Acme: we'd like to schedule a call", "wants_time", now=NOW)
        self.assertEqual(marked.call_args.args[:2], ("apply-0078e378", "replied"))
        self.assertEqual(opp["outcome"]["kind"], "conversation")
        self.assertEqual(opp["state"], pursuit.OPEN)
        self.assertEqual(opp["next_look"]["at"], "2026-09-21T15:00:00Z")
        self.assertTrue(any(e["kind"] == "reply" for e in opp["evidence"]))

    def test_a_decline_in_the_subject_closes_it(self):
        with mock.patch.object(pa, "_posting", return_value="P"), \
             mock.patch.object(pa, "_resume", return_value="R"), \
             mock.patch("aletheia.apply_run.mark") as marked:
            opp = pa.heard_back("apply-0078e378", "Unfortunately we are not moving forward", "noted", now=NOW)
        self.assertEqual(marked.call_args.args[:2], ("apply-0078e378", "rejected"))
        self.assertEqual(opp["state"], pursuit.CLOSED)
        self.assertEqual(opp["outcome"]["kind"], "declined")

    def test_a_bare_acknowledgement_is_not_a_reply(self):
        self.assertIsNone(pa.heard_back("apply-0078e378", "We received your application", "acknowledgement"))

    def test_the_submit_door_is_the_existing_one(self):
        pursuit.DOERS.pop("submit", None)
        pa.register()
        self.assertIs(pursuit.DOERS["submit"], pa._submit)
        opp = pa.open_from_application(RECORD, now=NOW, posting=lambda r: "P", resume=lambda: "R")
        with mock.patch("aletheia.apply_run.was_sent", return_value={"id": "x"}):
            out = pa._submit(opp, {"why": "w"}, NOW)
        self.assertEqual(out["effect"], "already sent")
        with mock.patch("aletheia.apply_run.was_sent", return_value=None), \
             mock.patch("aletheia.apply_run.stage",
                        return_value={"state": "AWAITING_YOU", "approval": "apply-1-submit", "say": "Ready."}) as staged:
            out = pa._submit(opp, {"why": "the fit is unusually strong"}, NOW)
        self.assertEqual(staged.call_args.args[0], RECORD["url"])
        self.assertEqual(out["state"], "waiting for his yes")


if __name__ == "__main__":
    unittest.main()
