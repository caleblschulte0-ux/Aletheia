"""Shoot high and shoot low, but realistic — and one job, one application.

His words, 2026-09-13, the morning after: *"Maybe sometimes it should not be
applying for managers and stuff, but ... it's gonna apply to a lot of jobs.
So ... we're gonna have it shoot high and shoot low. But it should be
realistic."*

Every title below is a real one from that night, for a Business Development
Associate a year into partner management at a fintech firm.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (apply_run, campaign, job_fit, jobs, journal, policy, profile,
                      stateio)

RESUME = ("Caleb Schulte\nHartford, SD 57033\n"
          "Business Development Associate | Expansion Capital Group | 2025 - Present\n"
          "Partner management, deal structuring, CRM-driven account growth.\n"
          "B.B.A., Innovation & Entrepreneurship, University of South Dakota, 2025\n")

OVERNIGHT_ROLES = ["Account Manager", "Partner Manager", "Business Analyst",
                   "Operations Analyst", "Business Development Associate",
                   "Account Executive"]


class TheTitleHasToNameTheJobCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target, name, value in (
                (journal, "JOURNAL_PATH", Path(tmp.name) / "j.jsonl"),
                (jobs, "boards", lambda: [{"provider": "greenhouse", "token": "t"}]),
                (jobs, "_learned_path", lambda: Path(tmp.name) / "learned.json")):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def matched(self, titles):
        rows = [{"title": t, "company": f"Co{i}", "location": "", "apply_url": f"u{i}"}
                for i, t in enumerate(titles)]
        out = jobs.search_many(OVERNIGHT_ROLES, fetcher=lambda board: rows, limit=40)
        return [j["title"] for j in out["matches"]]

    def test_a_different_line_of_work_that_shared_one_word_is_not_a_match(self):
        wrong = ["Accounting Manager, GL Operations & Intercompany",
                 "Financial Operations Manager",
                 "People Business Partner, GTM (Customer Experience, Implementation & Sales Development)",
                 "Event Marketing Manager, 3P & Partner",
                 "Product Manager, Connected Account Onboarding Experiences",
                 "Product & Regulatory Operations Manager",
                 "Program Manager - Growth Operations, Contract",
                 "Business Operations Manager, Office of the CEO"]
        self.assertEqual(self.matched(wrong), [])

    def test_his_own_line_of_work_still_matches_a_step_up_and_a_step_down(self):
        right = ["Account Executive, Commercial", "Partner Development Manager",
                 "Business Development Representative, Inbound", "Client Account Manager I",
                 "Account Manager, SMB", "Operations Analyst"]
        self.assertEqual(sorted(self.matched(right)), sorted(right))


class ARequirementHeDoesNotMeetCase(unittest.TestCase):
    def reason(self, title, text="", early=False, resume=RESUME):
        return job_fit.hard_reason(title, text, resume_text=resume, known={}, early=early)

    def test_a_language_the_title_demands(self):
        self.assertIn("Spanish", self.reason(
            "Business Development Representative - Spanish or Portuguese Speaking"))
        self.assertIn("Mandarin", self.reason("Fraud Operations Manager (Mandarin-speaking)"))
        self.assertEqual(self.reason(
            "Business Development Representative - Spanish or Portuguese Speaking",
            resume=RESUME + "Fluent in Spanish\n"), "")

    def test_a_military_command_or_a_clearance(self):
        for title in ("Territory Business Development Manager, USMC (R5167)",
                      "Business Development Associate - CENTCOM"):
            self.assertIn("military", self.reason(title), title)
        self.assertIn("clearance", self.reason(
            "Account Executive", "Must be able to obtain and maintain a Secret clearance."))

    def test_a_license_that_is_required_but_not_one_that_is_a_bonus(self):
        self.assertIn("Series 7", self.reason(
            "Banking Relationship Manager", "Requirements: active Series 7 and 63 licenses."))
        # Brex's real posting, word for word.
        self.assertEqual(self.reason(
            "Banking Relationship Manager",
            "Bonus points Series 7 & 63 license (active or able to be re-activated)"), "")

    def test_far_more_years_than_someone_early_has(self):
        figma = ("We'd love to hear from you if you have: 7+ years of enterprise software "
                 "or SaaS sales experience, with significant experience selling into Federal")
        self.assertIn("7+ years", self.reason("Account Executive, Federal - Civilian",
                                              figma, early=True))
        self.assertEqual(self.reason("Account Executive, Federal - Civilian", figma), "")
        self.assertEqual(self.reason("Business Development Representative",
                                     "2-3 years of experience in outbound SaaS prospecting",
                                     early=True), "")
        self.assertEqual(self.reason("Account Executive",
                                     "5+ years of sales experience preferred", early=True), "")


class TheJudgmentCase(unittest.TestCase):
    def test_what_no_rule_can_see_is_the_models_to_judge(self):
        costco = {"title": "Account Manager, Costco — Grüns", "company": "Grüns"}

        def think(system, text, **kw):
            self.assertEqual(kw["context"]["job"], "Account Manager, Costco")
            return kw["validator"]({"realistic": False,
                                    "why": "it needs years managing the Costco account"})
        said = job_fit.verdict(costco, RESUME, {}, think=think,
                               describe=lambda job: "Years managing Costco at Issaquah HQ")
        self.assertEqual((said["realistic"], said["by"]), (False, "model"))

    def test_a_model_that_is_out_never_stops_the_hunt(self):
        def out(system, text, **kw):
            raise RuntimeError("session limit")
        said = job_fit.verdict({"title": "Account Executive", "company": "Acme"}, RESUME, {},
                               think=out)
        self.assertTrue(said["realistic"])

    def test_a_rule_decides_without_asking_a_model(self):
        said = job_fit.verdict({"title": "Business Development Associate - CENTCOM"},
                               RESUME, {}, think=lambda *a, **k: self.fail("asked a model"))
        self.assertEqual((said["realistic"], said["by"]), (False, "rules"))


class LedgerCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = self.d = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        (d / "approvals").mkdir(); (d / "applications").mkdir()
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "j.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (profile, "path", lambda: d / "answers.json"),
                (apply_run, "staged_dir", lambda: d / "applications"),
                (apply_run, "sent_path", lambda: d / "applications-sent" / "already-sent.json")):
            patch = mock.patch.object(target, attr, value)
            patch.start(); self.addCleanup(patch.stop)

    def record(self, run_id, **fields):
        value = {"id": run_id, "state": "NEEDS_YOU", "url": f"https://x/{run_id}",
                 "approval": "", **fields}
        stateio.write_json_atomic(self.d / "applications" / f"{run_id}.json", value)
        return value


class NothingSentIsForgottenCase(LedgerCase):
    STRIPE = "https://boards.greenhouse.io/embed/job_app?for=stripe&token=7532733"

    def test_the_ledger_left_behind_by_the_move_still_counts(self):
        """Stripe, 2026-09-13 00:42Z: sent at 19:11Z into the OLD file, then
        re-staged and pressed again because the new file was empty."""
        (self.d / "applications" / "already-sent.json").write_text(json.dumps({
            self.STRIPE: {"id": "apply-6a6399f8", "at": "2026-09-12T19:11:28Z",
                          "company": "Stripe",
                          "job_title": "Account Executive, AI Sales — Stripe"}}),
            encoding="utf-8")
        self.assertIsNotNone(apply_run.was_sent(self.STRIPE))
        with self.assertRaises(apply_run.ApplyError):
            apply_run.stage(self.STRIPE, reader=lambda u: [], filler=lambda *a: {})

    def test_that_old_file_is_not_read_as_an_application(self):
        (self.d / "applications" / "already-sent.json").write_text(
            json.dumps({self.STRIPE: {"id": "x"}}), encoding="utf-8")
        self.assertEqual(apply_run.all_runs(), [])

    def test_a_press_with_no_answer_recorded_counts_as_sent(self):
        """Amtech and Carta hung in SUBMITTING when the PC restarted."""
        self.record("apply-07ced411", state="SUBMITTING", company="Amtech Software",
                    job_title="Account Manager — Amtech Software")
        self.assertIsNotNone(apply_run.was_sent("https://x/apply-07ced411"))
        self.assertIsNotNone(apply_run.was_applied_to_role("Amtech Software", "Account Manager"))


class OneRoleOneApplicationCase(LedgerCase):
    def test_a_role_already_waiting_under_another_link_is_taken(self):
        self.record("apply-058b39ff", company="Brex",
                    job_title="People Business Partner, GTM — Brex")
        self.assertIsNotNone(apply_run.role_taken(
            "Brex", "People Business Partner, GTM — Brex", "https://x/other"))
        # the same form is a re-stage, not a duplicate
        self.assertIsNone(apply_run.role_taken(
            "Brex", "People Business Partner, GTM — Brex", "https://x/apply-058b39ff"))

    def test_a_closed_one_does_not_hold_the_role(self):
        self.record("apply-1", state="CLOSED", company="Acme", job_title="Account Executive")
        self.assertIsNone(apply_run.role_taken("Acme", "Account Executive", "https://x/2"))

    def test_a_duplicate_is_closed_as_well_as_refused(self):
        """Refused alone, it stayed waiting and the beat asked again every minute."""
        self.record("apply-153575ee", state="SUBMITTED", company="Databricks",
                    job_title="Business Development Representative — Databricks",
                    submitted_at="2026-09-12T16:55:14Z")
        self.record("apply-8cb54481", state="APPROVED", company="Databricks",
                    job_title="Business Development Representative — Databricks")
        with self.assertRaises(apply_run.ApplyError):
            apply_run.submit("apply-8cb54481", submitter=lambda r: self.fail("pressed"))
        self.assertEqual(apply_run.load_run("apply-8cb54481")["state"], "CLOSED")

    def test_an_unrealistic_job_is_never_sent_whatever_was_answered(self):
        self.record("apply-shield", state="APPROVED", company="Shield AI",
                    job_title="Territory Business Development Manager, USMC (R5167) — Shield AI")
        with self.assertRaises(apply_run.ApplyError):
            apply_run.submit("apply-shield", submitter=lambda r: self.fail("pressed"))
        self.assertEqual(apply_run.load_run("apply-shield")["state"], "CLOSED")

    def test_what_went_cannot_be_closed(self):
        self.record("apply-sent", state="SUBMITTED")
        with self.assertRaises(apply_run.ApplyError):
            apply_run.close("apply-sent", "tidy")


class TheCampaignSkipsThemCase(unittest.TestCase):
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

    def run_with(self, pages, *, fit_think=False, taken=None):
        tried = []

        def stager(url, resume="", note="", extra=None):
            tried.append(url)
            return {"id": url, "url": url, "state": "NEEDS_YOU", "questions": []}
        with mock.patch.object(campaign, "read_resume", return_value=("resume.pdf", RESUME)), \
             mock.patch.object(apply_run, "all_runs", return_value=[]), \
             mock.patch.object(apply_run, "role_taken", side_effect=taken or (lambda *a: None)):
            out = campaign.run("Account Executive", count=5, json_think=False,
                               searcher=lambda roles, **kw: {"matches": pages, "searched": 1},
                               stager=stager, draft_essays_too=False, fit_think=fit_think)
        return tried, out

    def test_one_role_posted_to_three_locations_is_tried_once(self):
        pages = [{"apply_url": f"https://brex/{i}", "company": "Brex",
                  "title": "People Business Partner, GTM"} for i in range(3)]
        tried, out = self.run_with(pages)
        self.assertEqual(tried, ["https://brex/0"])
        self.assertEqual(len(out["duplicates"]), 2)

    def test_a_role_already_sent_under_another_link_is_not_filled_again(self):
        pages = [{"apply_url": "https://impact/7768895002", "company": "Impact.com",
                  "title": "Business Development Representative, Inbound"},
                 {"apply_url": "https://acme/1", "company": "Acme", "title": "Account Executive"}]
        tried, _ = self.run_with(
            pages, taken=lambda company, title, url: {"id": "apply-035c4b6e"}
            if company == "Impact.com" else None)
        self.assertEqual(tried, ["https://acme/1"])

    def test_an_unrealistic_job_is_passed_over_with_the_reason(self):
        pages = [{"apply_url": "https://addepar/1", "company": "Addepar",
                  "title": "Business Development Representative - Spanish or Portuguese Speaking"},
                 {"apply_url": "https://gruns/1", "company": "Grüns", "title": "Account Manager, Costco"},
                 {"apply_url": "https://acme/1", "company": "Acme", "title": "Account Executive"}]

        def think(system, text, **kw):
            costco = "Costco" in kw["context"]["job"]
            return kw["validator"]({"realistic": not costco, "why": "Costco account years"})
        tried, out = self.run_with(pages, fit_think=think)
        self.assertEqual(tried, ["https://acme/1"])
        self.assertEqual({p["url"] for p in out["passed_over"]},
                         {"https://addepar/1", "https://gruns/1"})

    def test_answering_a_question_never_finishes_an_unrealistic_job(self):
        record = {"id": "apply-neros", "state": "NEEDS_YOU", "url": "https://neros/1",
                  "company": "Neros", "job_title": "Business Development Associate - CENTCOM"}
        closed = []
        with mock.patch.object(campaign, "open_questions", return_value=[]), \
             mock.patch.object(apply_run, "all_runs",
                               side_effect=lambda state=None: [record] if state == "NEEDS_YOU" else []), \
             mock.patch.object(apply_run, "close", side_effect=lambda rid, why: closed.append(rid)):
            out = campaign.answer_all({"Are you willing to relocate?": "Yes"},
                                      stager=lambda *a, **k: self.fail("re-staged"))
        self.assertEqual(closed, ["apply-neros"])
        self.assertEqual(out["ready"] + out["blocked"], [])


class TheStagedOnesAreReviewedCase(unittest.TestCase):
    RECORDS = [{"id": "apply-a", "state": "NEEDS_YOU", "company": "Shield AI",
                "job_title": "Territory Business Development Manager, USMC (R5167) — Shield AI"},
               {"id": "apply-b", "state": "NEEDS_YOU", "company": "Acme",
                "job_title": "Account Executive — Acme"}]

    def review(self, apply):
        closed = []
        with mock.patch.object(apply_run, "all_runs",
                               side_effect=lambda state=None: self.RECORDS if state == "NEEDS_YOU" else []), \
             mock.patch.object(apply_run, "close", side_effect=lambda rid, why: closed.append(rid)):
            rows = job_fit.review_staged(apply=apply, think=False, resume_text=RESUME, known={})
        return rows, closed

    def test_a_dry_run_names_them_and_closes_nothing(self):
        rows, closed = self.review(apply=False)
        self.assertEqual([r["id"] for r in rows], ["apply-a"])
        self.assertEqual(closed, [])

    def test_applying_it_closes_them(self):
        _rows, closed = self.review(apply=True)
        self.assertEqual(closed, ["apply-a"])

    def test_one_role_waiting_three_times_keeps_the_first(self):
        """Brex's People Business Partner, staged at 04:29Z, 04:34Z and 04:46Z."""
        brex = [{"id": f"apply-{n}", "state": "NEEDS_YOU", "company": "Brex",
                 "staged_at": at, "job_title": "People Business Partner, GTM — Brex"}
                for n, at in (("c", "2026-09-13T04:46Z"), ("a", "2026-09-13T04:29Z"),
                              ("b", "2026-09-13T04:34Z"))]
        with mock.patch.object(apply_run, "all_runs",
                               side_effect=lambda state=None: brex if state == "NEEDS_YOU" else []), \
             mock.patch.object(apply_run, "was_applied_to_role", return_value=None):
            rows = job_fit.review_staged(think=False, resume_text=RESUME, known={})
        self.assertEqual(sorted(r["id"] for r in rows), ["apply-b", "apply-c"])
        self.assertTrue(all(r["by"] == "duplicate" for r in rows))


class TheEmployersNameIsNeverCutShortCase(unittest.TestCase):
    """Live 2026-09-13 an application went on file under "Neros ..." — a
    search result's title ran out of room — and that name keyed the
    duplicate check and the verification-code lookup."""

    NEROS = {"links": [{"href": "https://job-boards.greenhouse.io/nerostechnologies/jobs/5209843007",
                        "text": "Job Application for Business Development Associate - CENTCOM at Neros ..."}]}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.learned = Path(tmp.name) / "learned.json"
        for target, name, value in ((journal, "JOURNAL_PATH", Path(tmp.name) / "j.jsonl"),
                                    (jobs, "_learned_path", lambda: self.learned)):
            patch = mock.patch.object(target, name, value)
            patch.start(); self.addCleanup(patch.stop)

    def board_jobs(self, company_name):
        return {"jobs": [{"id": 1, "title": "Account Executive", "company_name": company_name,
                          "location": {"name": "Remote - US"}}]}

    def test_a_search_result_cut_short_does_not_name_the_employer(self):
        found = jobs.discover_openings(["Business Development Associate"], limit=5,
                                       http=lambda q: self.NEROS)
        self.assertEqual((found[0]["company"], found[0]["title"]),
                         ("nerostechnologies", "Business Development Associate - CENTCOM"))

    def test_the_board_names_a_learned_employer(self):
        with mock.patch.object(jobs, "_fetch", return_value=self.board_jobs("Neros Technologies")):
            rows = jobs._greenhouse({"provider": "greenhouse", "token": "nerostechnologies",
                                     "company": "Neros ...", "learned": True})
        self.assertEqual(rows[0]["company"], "Neros Technologies")

    def test_a_name_he_configured_is_kept(self):
        with mock.patch.object(jobs, "_fetch", return_value=self.board_jobs("Gong.io")):
            rows = jobs._greenhouse({"provider": "greenhouse", "token": "gongio", "company": "Gong"})
        self.assertEqual(rows[0]["company"], "Gong")

    def test_a_cut_name_already_on_file_is_not_read_back(self):
        self.learned.write_text(json.dumps([{"provider": "greenhouse", "token": "nerostechnologies",
                                             "company": "Neros ...", "learned": True}]),
                                encoding="utf-8")
        self.assertEqual(jobs._learned_boards()[0]["company"], "nerostechnologies")

    def test_a_web_found_employer_is_named_by_its_board_and_remembered_that_way(self):
        with mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            out = jobs.search_many(["Business Development Associate"], fetcher=lambda b: [],
                                   limit=5, discover=True, http=lambda q: self.NEROS,
                                   namer=lambda provider, token: "Neros Technologies")
        self.assertEqual(out["matches"][0]["company"], "Neros Technologies")
        self.assertEqual(jobs._learned_boards()[0]["company"], "Neros Technologies")

    def test_the_board_name_lookup_reads_greenhouse_and_never_raises(self):
        self.assertEqual(jobs._board_name("greenhouse", "nerostechnologies",
                                          fetch=lambda url: {"name": "Neros Technologies"}),
                         "Neros Technologies")
        self.assertEqual(jobs._board_name("lever", "nitra", fetch=lambda url: self.fail("asked")), "")
        self.assertEqual(jobs._board_name("greenhouse", "x",
                                          fetch=lambda url: (_ for _ in ()).throw(OSError())), "")


class ThePostingIsReadCase(unittest.TestCase):
    def test_a_greenhouse_form_url_reads_its_posting(self):
        asked = []

        def fetch(url):
            asked.append(url)
            return {"content": "&lt;p&gt;Requirements&lt;/p&gt;<p>3+ years</p>"}
        text = jobs.posting_text(
            {"url": "https://boards.greenhouse.io/embed/job_app?for=brex&token=8802224002"},
            fetch=fetch)
        self.assertEqual(asked, ["https://boards-api.greenhouse.io/v1/boards/brex/jobs/8802224002"])
        self.assertIn("3+ years", text)

    def test_nothing_it_can_read_is_empty_not_an_error(self):
        self.assertEqual(jobs.posting_text({"url": "https://example.com/job"}), "")
        self.assertEqual(jobs.posting_text(
            {"url": "https://jobs.lever.co/nitra/5750374e-69f7-4923-89d3-460c0aa878b7/apply"},
            fetch=lambda url: (_ for _ in ()).throw(OSError("offline"))), "")


if __name__ == "__main__":
    unittest.main()
