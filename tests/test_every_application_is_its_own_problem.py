"""His words, 2026-10-03: *"This needs to not just be Python code that applies
for jobs. This needs to be an AI whose every thought of every job application
is how, what maximizes the chance of me getting this job."*

What that means in code, each held here:

- THE ANGLE: before a form is opened a model reads the posting beside his
  resume and says what makes HIM the candidate for THIS job - as verbatim
  pairs, checked in code - and the essays, the card and the opportunity's
  reasoner all start from it. A weak shot is passed over. No model: a plain
  application, never a withheld one.
- DISCOVERY CHOOSES by his ruling where he never touched the switch.
- A PERSON can be found: the pursuit has a move that looks for a named
  human at the employer and a way to reach them, so a note has somebody.
- THE OBJECTIVE CHANGES when he lands a conversation, and SILENCE after an
  application is evidence the reasoner hears.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (apply_run, campaign, job_angle, job_discovery, journal, mission_jobs, people_finder,
                      policy, profile, pursuit, pursuit_applications as pa, rulings)
from tests.test_campaign import CampaignCase, RESUME

POSTING = ("We are hiring a Partnerships Manager. You will manage funding partner relationships, "
           "negotiate lender agreements and run partner onboarding. Requires 3+ years in fintech "
           "partnerships and comfort with lender contracts.")
HIS = ("Caleb Schulte. Partner Operations Associate at a fintech. Manages difficult funding partner "
       "relationships for a merchant cash advance lender. Built a pipeline that onboards partners in a day.")
NOW = dt.datetime(2026, 10, 3, 15, 0, tzinfo=dt.timezone.utc)


def good_answer(**kw) -> dict:
    return {"worth": 7, "why": "his partner work is exactly what they ask for",
            "lead_with": [{"they_ask": "manage funding partner relationships",
                           "he_has": "Manages difficult funding partner relationships",
                           "say": "I manage funding partner relationships today."},
                          {"they_ask": "run partner onboarding",
                           "he_has": "onboards partners in a day", "say": "I built the onboarding."}],
            "watch_out": ["3+ years in fintech partnerships"],
            "angle": "He does the partner work they describe, today, at a lender.", **kw}


# ---- the angle --------------------------------------------------------------------------

class TheAngleIsQuotedOrItIsNothing(unittest.TestCase):
    def test_both_halves_of_a_pair_must_be_verbatim(self):
        validate = job_angle.validator(POSTING, HIS)
        out = validate(good_answer())
        self.assertEqual(len(out["lead_with"]), 2)
        self.assertEqual(out["worth"], 7)
        self.assertIn("fintech partnerships", out["watch_out"][0])
        self.assertTrue(out["angle"])

    def test_a_paraphrase_is_dropped_and_an_angle_with_no_pair_is_no_angle(self):
        validate = job_angle.validator(POSTING, HIS)
        invented = good_answer(lead_with=[
            {"they_ask": "manage funding partner relationships", "he_has": "ran a lending desk for years",
             "say": "x"},                                          # not on his resume
            {"they_ask": "lead a team of twelve", "he_has": "Built a pipeline", "say": "y"},  # not in the posting
        ])
        out = validate(invented)
        self.assertEqual(out["lead_with"], [])
        self.assertEqual(out["angle"], "", "the case for him stands only on pairs; none left, no case")
        self.assertEqual(out["dropped_pairs"], 2)

    def test_matching_ignores_case_and_whitespace_but_not_words(self):
        validate = job_angle.validator(POSTING, HIS)
        out = validate(good_answer(lead_with=[{"they_ask": "MANAGE  funding partner\nrelationships",
                                               "he_has": "manages difficult funding partner relationships",
                                               "say": ""}]))
        self.assertEqual(len(out["lead_with"]), 1)

    def test_a_weak_shot_needs_the_model_and_the_pairs_to_agree(self):
        self.assertTrue(job_angle.weak_shot({"worth": 1, "why": "nothing matches", "lead_with": []}))
        self.assertEqual(job_angle.weak_shot({"worth": 1, "lead_with": [{"they_ask": "a", "he_has": "b"}]}), "",
                         "a stretch with one real match is still a shot")
        self.assertEqual(job_angle.weak_shot({"worth": 6, "lead_with": []}), "")
        self.assertEqual(job_angle.weak_shot(None), "")

    def test_nobody_to_think_is_a_plain_application_not_a_withheld_one(self):
        self.assertIsNone(job_angle.find("Role", "Acme", POSTING, HIS, think=False))

        def broken(*a, **k):
            raise RuntimeError("Claude is out")
        self.assertIsNone(job_angle.find("Role", "Acme", POSTING, HIS, think=broken))
        self.assertIsNone(job_angle.find("Role", "Acme", "short", HIS, think=lambda *a, **k: good_answer()))

    def test_the_words_for_a_writer_pair_them_and_name_the_gaps(self):
        angle = job_angle.validator(POSTING, HIS)(good_answer())
        said = job_angle.words(angle)
        self.assertIn('They ask for: "manage funding partner relationships"', said)
        self.assertIn('His resume shows: "Manages difficult funding partner relationships"', said)
        self.assertIn("Not shown on his resume (address honestly, never claim): 3+ years in fintech partnerships", said)
        self.assertEqual(job_angle.words(None), "")
        self.assertIn("7/10 shot", job_angle.evidence_text(angle))


class TheAngleTravels(CampaignCase):
    """Through the campaign: onto the record, into the essays, onto the card."""

    def _run_with_angle(self, think):
        return campaign.run("engineer", finder=self.finder(), reader=self.reader(), opener=self.opener(),
                            stager=self.stager(), json_think=False, angle_think=think,
                            describer=lambda page: POSTING)

    def test_the_angle_lands_on_the_record_and_the_card_answers_from_it(self):
        calls = []

        def think(brief, text, *, context, validator, **kw):
            calls.append(context["job"])
            self.assertIn("what maximises his chance", brief)
            self.assertEqual(context["posting"], POSTING)
            return validator(good_answer())
        with mock.patch.object(campaign, "read_resume", return_value=("resume.md", HIS)):
            out = self._run_with_angle(think)
        self.assertTrue(calls, "a model was asked about each job before its form")
        staged = (out["ready"] + out["blocked"])[0]
        kept = apply_run.load_run(staged["id"])
        self.assertEqual(kept["angle"]["worth"], 7)
        self.assertEqual(len(kept["angle"]["lead_with"]), 2)
        why = mission_jobs.why_this_one(kept)
        self.assertEqual(why["source"], "angle")
        self.assertIn("partner work", why["said"])
        self.assertIn("they ask for manage funding partner relationships; he has Manages difficult funding partner relationships",
                      why["liked"][0])
        self.assertIn("not shown on his resume: 3+ years in fintech partnerships", why["against"])

    def test_a_weak_shot_is_passed_over_with_its_reason(self):
        def think(brief, text, *, context, validator, **kw):
            return validator({"worth": 1, "why": "they want a licensed broker; nothing on his resume is that",
                              "lead_with": [], "watch_out": ["a broker license"], "angle": ""})
        with mock.patch.object(campaign, "read_resume", return_value=("resume.md", HIS)):
            out = self._run_with_angle(think)
        self.assertEqual(out["ready"] + out["blocked"], [])
        self.assertTrue(out["passed_over"])
        self.assertTrue(all(p["why"].startswith("a weak shot: ") for p in out["passed_over"]))

    def test_without_a_model_the_application_is_plain_and_goes(self):
        with mock.patch.object(campaign, "read_resume", return_value=("resume.md", HIS)):
            out = self._run_with_angle(False)
        staged = (out["ready"] + out["blocked"])[0]
        self.assertNotIn("angle", apply_run.load_run(staged["id"]))

    def test_the_essays_and_the_letter_lead_with_the_case(self):
        record = {"id": "x", "url": "https://x/apply", "job_title": "Partnerships Manager",
                  "angle": job_angle.validator(POSTING, HIS)(good_answer()),
                  "questions": [{"selector": "#why", "label": "Why do you want this role?", "type": "textarea"},
                                {"selector": "#cl", "label": "Cover letter", "type": "textarea"}]}
        prompts = []

        def writer(prompt, text, timeout_s=0):
            prompts.append(prompt)
            return "written"
        out = campaign.draft_essays(record, HIS, think=writer)
        self.assertEqual(set(out), {"#why", "#cl"})
        for prompt in prompts:
            self.assertIn("THE CASE FOR HIM:", prompt)
            self.assertIn('They ask for: "run partner onboarding"', prompt)
            self.assertIn("Never claim beyond them", prompt)
        plain = campaign.draft_essays({**record, "angle": None}, HIS, think=writer)
        self.assertIn(campaign.NO_ANGLE, prompts[-1])
        self.assertEqual(set(plain), {"#why", "#cl"})

    def test_the_opportunity_opens_with_the_case_as_trusted_evidence(self):
        record = {"id": "apply-1", "state": "SUBMITTED", "url": "https://x/apply", "company": "Acme",
                  "job_title": "Partnerships Manager", "angle": job_angle.validator(POSTING, HIS)(good_answer()),
                  "outcomes": []}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(pursuit, "store_dir", return_value=Path(tmp)), \
                mock.patch("aletheia.journal.append"), \
                mock.patch("aletheia.apply_run.all_runs", return_value=[record]), \
                mock.patch("aletheia.profile.known", return_value={}):
            opp = pa.open_from_application(record, now=NOW, posting=lambda r: POSTING, resume=lambda: HIS)
        case = next(e for e in opp["evidence"] if e["kind"] == "the case for him")
        self.assertEqual(case["provenance"], pursuit.TRUSTED)
        self.assertIn("7/10 shot", case["text"])
        self.assertIn("run partner onboarding", case["text"])


# ---- discovery chooses by his ruling ---------------------------------------------------

class DiscoveryChoosesByRuling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / "discovery_settings.json"
        p = mock.patch.object(job_discovery, "settings_path", return_value=self.settings)
        p.start(); self.addCleanup(p.stop)

    def test_the_ruling_is_the_default_where_he_never_touched_the_switch(self):
        with mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS):
            ruling = rulings.for_switch("discovery")
            self.assertTrue(ruling and ruling["on"])
            self.assertIn("maximizes the chance", rulings.quote(ruling))
            self.assertTrue(job_discovery.lets_discovery_choose())

    def test_no_ruling_file_means_off_as_before(self):
        with mock.patch.object(rulings, "DEFAULT_PATH", Path(self.tmp.name) / "none.json"):
            self.assertFalse(job_discovery.lets_discovery_choose())

    def test_his_own_hand_at_the_keyboard_wins_over_the_ruling(self):
        with mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS), \
                mock.patch("aletheia.journal.append"):
            job_discovery.set_discovery_choose(False, by="him")
            self.assertFalse(job_discovery.lets_discovery_choose())
            job_discovery.set_discovery_choose(True, by="him")
            self.assertTrue(job_discovery.lets_discovery_choose())


# ---- a person can be found ---------------------------------------------------------------

TEAM_PAGE = """About Acme
Our team
Jane Doe, Head of Talent
Raj Patel - Director of Partnerships
Sam Lee | Senior Software Engineer
Contact: careers@acme.com or press@othersite.com
Jane can be reached at jane.doe@acme.com
"""


class APersonCanBeFound(unittest.TestCase):
    def test_names_with_titles_and_addresses_on_their_own_domain(self):
        people = people_finder.find_people(TEAM_PAGE, domain="acme.com",
                                           title_words=("talent", "partnerships"), source="their site")
        names = {p["name"]: p for p in people}
        self.assertIn("Jane Doe", names)
        self.assertEqual(names["Jane Doe"]["title"], "Head of Talent")
        self.assertEqual(names["Jane Doe"]["email"], "jane.doe@acme.com")
        self.assertIn("Raj Patel", names)
        self.assertEqual(names["Raj Patel"]["email"], "", "no address on the page for him")
        self.assertNotIn("Sam Lee", names, "an engineer is not who the ask names")
        shared = [p for p in people if not p["name"]]
        self.assertEqual([p["email"] for p in shared], ["careers@acme.com"],
                         "a shared inbox on their domain is kept without a name; another site's is not")

    def test_a_search_snippet_names_people_without_visiting_the_site(self):
        snippets = {"text": "", "links": [
            {"href": "https://example.net/in/jd", "text": "Jane Doe - Head of Talent at Acme",
             "snippet": "Jane Doe. Head of Talent at Acme. Austin, Texas."},
            {"href": "https://example.net/in/x", "text": "Acme reviews", "snippet": "Great place"}]}
        people = people_finder.find_people(people_finder.search_text(snippets), domain="acme.com",
                                           title_words=("talent",), source="a web search")
        self.assertEqual([p["name"] for p in people if p["name"]], ["Jane Doe"])

    def test_find_at_reads_the_pages_it_is_given_then_the_site_then_a_search_bounded(self):
        read, searched = [], []

        def reader(url):
            read.append(url)
            return {"title": "Team", "text": TEAM_PAGE if url.endswith("/about") else "", "links": []}

        def search(query):
            searched.append(query)
            return {"text": "", "links": []}
        found = people_finder.find_at("Acme", domain="acme.com", title_words=("talent", "recruit"),
                                      texts=[("the posting", "Questions? Ask Pat Quinn, Recruiter, at pat@acme.com")],
                                      reader=reader, search=search, max_pages=2)
        names = [p["name"] for p in found if p["name"]]
        self.assertIn("Pat Quinn", names)
        self.assertIn("Jane Doe", names)
        self.assertLessEqual(len(read), 2)
        self.assertTrue(searched and "Acme" in searched[0])

    def test_the_pursuit_move_puts_people_on_the_record_so_a_note_has_somebody(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(pursuit, "store_dir", return_value=Path(tmp)), \
                mock.patch("aletheia.journal.append"), \
                mock.patch.object(policy, "ensure_not_halted"), \
                mock.patch.object(pa, "_find_people", return_value=[
                    {"name": "Jane Doe", "title": "Head of Talent", "email": "jane.doe@acme.com",
                     "source": "https://acme.com/about"}]):
            record = pursuit.open_opportunity(key="k", name="Partnerships Manager at Acme", objective="o",
                                              subject={"organisation": "Acme", "posting": "https://acme.com/jobs/1"},
                                              now=NOW)
            with pursuit._LOCK:
                record = pursuit.load(record["id"])
                pursuit.add_evidence(record, "posting", POSTING, now=NOW)
                pursuit.save(record)
            clean, dropped = pursuit.validate(
                {"moves": [{"kind": "find_person", "why": "the posting names nobody; a named person to write to would help",
                            "cites": ["e1"], "detail": {"who": "whoever runs partnerships or hiring"}}]},
                record)
            self.assertEqual(dropped, [])
            self.assertEqual(clean["moves"][0]["kind"], "find_person")
            out = pursuit.reason(record["id"], think=lambda r, n: ({"moves": clean["moves"]}, {"provider": "t"}), now=NOW)
            done = pursuit.act(record["id"], out["moves"][0]["id"], now=NOW)
            self.assertEqual(done["state"], "done")
            self.assertIn("Jane Doe", done["effect"])
            fresh = pursuit.load(record["id"])
            self.assertEqual(fresh["people"][0]["name"], "Jane Doe")
            self.assertTrue(any(e["kind"] == "people" and "jane.doe@acme.com" in e["text"] for e in fresh["evidence"]))
            self.assertFalse(pursuit.nobody_by_name("Jane Doe <jane.doe@acme.com>"))
            self.assertIn("find_person", pursuit.UNATTENDED_MOVES)

    def test_finding_nobody_says_so_and_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(pursuit, "store_dir", return_value=Path(tmp)), \
                mock.patch("aletheia.journal.append"), \
                mock.patch.object(policy, "ensure_not_halted"), \
                mock.patch.object(pa, "_find_people", return_value=[]):
            record = pursuit.open_opportunity(key="k2", name="n", objective="o",
                                              subject={"organisation": "Acme"}, now=NOW)
            with pursuit._LOCK:
                record = pursuit.load(record["id"])
                pursuit.add_evidence(record, "posting", POSTING, now=NOW)
                pursuit.save(record)
            move = {"kind": "find_person", "why": "a named person would help this along", "cites": ["e1"], "detail": {}}
            out = pursuit.reason(record["id"], think=lambda r, n: ({"moves": [move]}, {"provider": "t"}), now=NOW)
            done = pursuit.act(record["id"], out["moves"][0]["id"], now=NOW)
            self.assertIn("nobody", done["effect"])
            fresh = pursuit.load(record["id"])
            self.assertIn("find_person:", fresh["never_repeat"][0])
            _clean, dropped = pursuit.validate({"moves": [move]}, fresh)
            self.assertEqual(dropped[0]["why"], "it was already done, or he said never again")


# ---- the objective changes, and silence is evidence ------------------------------------

SENT = {"id": "apply-0078e378", "state": "SUBMITTED", "url": "https://example.com/apply/1",
        "posting": "https://example.com/careers/1", "company": "Acme", "job_title": "Partnerships Lead",
        "submitted_at": "2026-09-20T18:47:04Z", "outcomes": []}


class TheObjectiveMovesWithTheSituation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(pursuit, "store_dir", return_value=Path(self.tmp.name)),
                  mock.patch("aletheia.journal.append"),
                  mock.patch("aletheia.apply_run.all_runs", return_value=[SENT]),
                  mock.patch("aletheia.apply_run.load_run", return_value=dict(SENT)),
                  mock.patch("aletheia.apply_run.mark"),
                  mock.patch("aletheia.profile.known", return_value={}),
                  mock.patch.object(pa, "_posting", return_value="P"),
                  mock.patch.object(pa, "_resume", return_value="R")):
            p.start(); self.addCleanup(p.stop)

    def test_a_conversation_rewrites_the_objective_to_doing_well_in_it(self):
        opp = pa.heard_back(SENT["id"], "Interview with Acme", "wants_time", now=NOW)
        self.assertEqual(opp["outcome"]["kind"], "conversation")
        self.assertIn("Do well in the conversation", opp["objective"])
        self.assertIn("Acme", opp["objective"])
        self.assertIn("prepare him", opp["objective"])
        self.assertEqual(opp["state"], pursuit.OPEN)
        self.assertIn("objective", opp["history"][-1]["what"])

    def test_silence_after_the_application_is_evidence_that_makes_it_due_once_per_mark(self):
        opp = pa.open_from_application(SENT, now=NOW)
        with pursuit._LOCK:
            fresh = pursuit.load(opp["id"])
            fresh["state"] = pursuit.PARKED
            fresh["next_look"] = {"at": "2026-12-01T00:00:00Z", "because": "left alone"}
            pursuit.save(fresh)
        # 13 days in: the first mark
        changed = pa.reconcile([SENT], now=NOW)
        fresh = pursuit.load(opp["id"])
        self.assertIn(opp["id"], changed)
        self.assertEqual(fresh["state"], pursuit.OPEN)
        silence = [e for e in fresh["evidence"] if e["kind"] == "silence"]
        self.assertEqual(len(silence), 1)
        self.assertIn("8 days", silence[0]["text"])
        self.assertLessEqual(fresh["next_look"]["at"], pursuit._stamp(NOW))
        # the same day again: nothing new
        self.assertEqual(pa.reconcile([SENT], now=NOW), [])
        # 22 days in: the second mark, and no third
        later = NOW + dt.timedelta(days=9)
        pa.reconcile([SENT], now=later)
        pa.reconcile([SENT], now=later + dt.timedelta(days=30))
        silence = [e for e in pursuit.load(opp["id"])["evidence"] if e["kind"] == "silence"]
        self.assertEqual([("21 days" in e["text"]) for e in silence], [False, True])

    def test_a_reply_ends_the_silence(self):
        replied = {**SENT, "outcome": "replied", "outcomes": [{"outcome": "replied"}]}
        opp = pa.open_from_application(replied, now=NOW)
        with mock.patch("aletheia.apply_run.all_runs", return_value=[replied]):
            pa.reconcile([replied], now=NOW + dt.timedelta(days=40))
        self.assertFalse([e for e in pursuit.load(opp["id"])["evidence"] if e["kind"] == "silence"])


if __name__ == "__main__":
    unittest.main()
