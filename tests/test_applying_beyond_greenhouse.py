"""Every system she applies on is a system she SEARCHES.

His words, 2026-09-13: *"keep making it so that tomorrow when my Claude thing
runs out, it keeps applying to jobs everywhere across the Internet, not just
on Greenhouse."* Of 63 applications sent, 49 went through Greenhouse and 2
through Lever, and both Lever sends failed. `jobs.ATS` already named Ashby,
Workable, SmartRecruiters and Recruitee - and `jobs.PROVIDERS`, the table of
boards she can LIST, held only Greenhouse and Lever. So the other four were
reached only when something else happened to hand her a link, and nothing
learned their boards when it did.

The network is stubbed throughout. Every endpoint was proved with a plain
HTTP GET against a real employer when this was written: Notion and Ramp on
Ashby, Hugging Face on Workable, Equinox on SmartRecruiters, bunq on
Recruitee.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply_run, campaign, company_sites, jobs, journal
from tests.test_apply_run import ApplyCase
from tests.test_campaign import FORM_FIELDS, POSTING_FIELDS, CampaignCase
from tests.test_company_websites_too import muse_page

JID = "11111111-1111-4111-8111-111111111111"
ASHBY_FORM = f"https://jobs.ashbyhq.com/acme/{JID}/application"
LEVER_FORM = f"https://jobs.lever.co/acme/{JID}/apply"
GH_FORM = "https://boards.greenhouse.io/embed/job_app?for=acme&token=42"

ASHBY = {"apiVersion": "1", "jobs": [
    {"id": JID, "title": " Account Manager | Commercial", "location": "New York, NY (HQ)",
     "secondaryLocations": [{"location": "Remote (US)"}], "isListed": True,
     "jobUrl": f"https://jobs.ashbyhq.com/acme/{JID}", "applyUrl": ASHBY_FORM},
    {"id": "22222222-2222-4222-8222-222222222222", "title": "Account Manager",
     "location": "Remote", "isListed": False}]}
WORKABLE = {"name": "Acme Robotics", "jobs": [
    {"title": "Account Manager", "shortcode": "AB12CD34EF", "telecommuting": True,
     "url": "https://apply.workable.com/j/AB12CD34EF",
     "locations": [{"city": "Austin", "region": "Texas", "country": "United States"}]}]}
RECRUITEE = {"offers": [
    {"id": 7, "slug": "account-manager", "title": "Account Manager", "status": "published",
     "location": "New York, New York, United States", "company_name": "Acme",
     "careers_url": "https://careers.acme.com/o/account-manager",
     "careers_apply_url": "https://careers.acme.com/o/account-manager/c/new"},
    {"id": 8, "slug": "draft", "title": "Account Manager", "status": "draft"}]}


def smartrecruiters_api(total: int):
    """A company with `total` postings, a hundred a page, as the Posting API pages them."""
    asked = []

    def fetch(url):
        asked.append(url)
        offset = int(url.rsplit("offset=", 1)[1])
        rows = [{"id": str(744000000000000 + i), "uuid": f"uuid-{i}", "name": "Account Manager",
                 "company": {"identifier": "Acme", "name": "Acme Fitness"},
                 "location": {"fullLocation": "Miami, FL, United States", "remote": False}}
                for i in range(offset, min(total, offset + 100))]
        return {"offset": offset, "limit": 100, "totalFound": total, "content": rows}
    fetch.asked = asked
    return fetch


class LearningCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        for target, name, value in ((journal, "JOURNAL_PATH", self.dir / "j.jsonl"),
                                    (jobs, "_learned_path", lambda: self.dir / "learned.json")):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def learned(self):
        return [(r["provider"], r["token"], r["company"], r["from"]) for r in jobs._learned_boards()]


class EverySystemSheAppliesOnIsListed(LearningCase):
    def test_every_system_in_the_table_is_one_she_can_list(self):
        """The bug in one line: ATS said six systems and PROVIDERS said two."""
        self.assertLessEqual({a.provider for a in jobs.ATS}, set(jobs.PROVIDERS))

    def test_ashby(self):
        with mock.patch.object(jobs, "_fetch", return_value=ASHBY) as fetch:
            rows = jobs._ashby({"provider": "ashby", "token": "acme", "company": "Acme"})
        self.assertIn("api.ashbyhq.com/posting-api/job-board/acme", fetch.call_args[0][0])
        self.assertEqual(len(rows), 1, "an unlisted posting is not offered to applicants")
        self.assertEqual(rows[0]["title"], "Account Manager | Commercial")
        self.assertEqual(rows[0]["apply_url"], ASHBY_FORM)
        self.assertTrue(jobs._in_country(rows[0]["location"], "United States"))

    def test_workable(self):
        with mock.patch.object(jobs, "_fetch", return_value=WORKABLE):
            rows = jobs._workable({"provider": "workable", "token": "acme", "learned": True})
        job = rows[0]
        self.assertEqual(job["company"], "Acme Robotics", "a learned board is named by its own feed")
        self.assertEqual(job["apply_url"], "https://apply.workable.com/acme/j/AB12CD34EF/apply/")
        self.assertTrue(job["location"].startswith("Remote - Austin"))
        ats, token, code = jobs.job_from_url(job["apply_url"])
        self.assertEqual((ats.provider, token, code), ("workable", "acme", "AB12CD34EF"))

    def test_smartrecruiters_is_read_page_by_page_to_the_end(self):
        api = smartrecruiters_api(150)
        with mock.patch.object(jobs, "_fetch", side_effect=api):
            rows = jobs._smartrecruiters({"provider": "smartrecruiters", "token": "Acme"})
        self.assertEqual((len(rows), len(api.asked)), (150, 2))
        self.assertEqual(rows[0]["posting_url"], "https://jobs.smartrecruiters.com/Acme/744000000000000")
        self.assertIn("oneclick-ui/company/Acme/publication/uuid-0", rows[0]["apply_url"],
                      "the posting page is not the form; the one-click form is")
        self.assertEqual(rows[0]["company"], "Acme Fitness")

    def test_a_huge_smartrecruiters_board_is_bounded(self):
        api = smartrecruiters_api(5000)
        with mock.patch.object(jobs, "_fetch", side_effect=api):
            rows = jobs._smartrecruiters({"provider": "smartrecruiters", "token": "Acme"})
        self.assertEqual(len(api.asked), jobs.SMARTRECRUITERS_PAGES)
        self.assertEqual(len(rows), jobs.SMARTRECRUITERS_PAGES * jobs.SMARTRECRUITERS_PAGE)

    def test_recruitee(self):
        with mock.patch.object(jobs, "_fetch", return_value=RECRUITEE) as fetch:
            rows = jobs._recruitee({"provider": "recruitee", "token": "acme"})
        self.assertEqual(fetch.call_args[0][0], "https://acme.recruitee.com/api/offers/")
        self.assertEqual([r["apply_url"] for r in rows],
                         ["https://careers.acme.com/o/account-manager/c/new"])

    def test_a_recruitee_job_on_the_employers_own_domain_is_walked_not_staged(self):
        """bunq's apply link redirects to careers.bunq.com/positions/..., a posting
        page; staged as the form it was refused as no application at all."""
        hosted = {"offers": [dict(RECRUITEE["offers"][0], slug="am",
                                  careers_apply_url="https://acme.recruitee.com/o/am/c/new")]}
        with mock.patch.object(jobs, "_fetch", return_value=RECRUITEE):
            own = jobs._recruitee({"provider": "recruitee", "token": "acme"})[0]
        with mock.patch.object(jobs, "_fetch", return_value=hosted):
            theirs = jobs._recruitee({"provider": "recruitee", "token": "acme"})[0]
        self.assertFalse(own["direct"])
        self.assertTrue(theirs["direct"])

    def test_a_recruitee_token_is_a_subdomain_and_nothing_else(self):
        with mock.patch.object(jobs, "_fetch") as fetch:
            with self.assertRaises(jobs.BoardGone):
                jobs._recruitee({"provider": "recruitee", "token": "evil.com/x"})
        self.assertFalse(fetch.called)

    def test_a_board_on_another_system_is_searched_like_any_other(self):
        with mock.patch.object(jobs, "boards",
                               return_value=[{"provider": "ashby", "token": "acme", "company": "Acme"}]), \
             mock.patch.object(jobs, "_fetch", return_value=ASHBY):
            out = jobs.search_many(["Account Manager"], limit=5)
        self.assertEqual([(m["provider"], m["apply_url"]) for m in out["matches"]], [("ashby", ASHBY_FORM)])
        self.assertIn("score", out["matches"][0])


class TheAddressesReadRight(unittest.TestCase):
    def test_a_workable_address_with_no_account_is_still_a_job(self):
        """Workable's own feed hands out apply.workable.com/j/<code>; the pattern
        that required an account in the path matched none of them."""
        ats, token, code = jobs.job_from_url("https://apply.workable.com/j/AB12CD34EF")
        self.assertEqual((ats.provider, token, code), ("workable", "", "AB12CD34EF"))
        self.assertEqual(ats.apply(token, code), "https://apply.workable.com/j/AB12CD34EF/apply")

    def test_a_smartrecruiters_posting_page_is_walked_not_staged(self):
        page = {"links": [
            {"href": "https://jobs.smartrecruiters.com/Acme/744000149110069-account-manager",
             "text": "Account Manager"},
            {"href": "https://boards.greenhouse.io/acme/jobs/42", "text": "Account Manager"}]}
        found = {j["provider"]: j for j in jobs.discover_openings(["Account Manager"], limit=5,
                                                                   http=lambda q: page)}
        self.assertFalse(found["smartrecruiters"]["direct"])
        self.assertTrue(found["greenhouse"]["direct"])

    def test_an_employer_site_that_leads_to_ashby_names_the_board_by_token(self):
        lead = {"title": "Account Manager", "company": "Acme", "locations": ["Austin, TX"],
                "lead": "https://www.themuse.com/jobs/acme/1"}
        pages = {lead["lead"]: muse_page(f"https://jobs.ashbyhq.com/acme/{JID}")}
        out = company_sites.openings(["Account Manager"], leads=lambda *a, **k: [lead],
                                     fetch=lambda url: (200, url, pages.get(url, "")))
        self.assertEqual([(j["provider"], j["board"], j["direct"], j["apply_url"]) for j in out],
                         [("ashby", "acme", True, ASHBY_FORM)])


class SheLearnsABoardWhereverSheMeetsOne(LearningCase):
    def test_an_employer_site_leading_to_ashby_teaches_her_the_board(self):
        own = [{"title": "Account Manager", "company": "Acme", "location": "",
                "apply_url": ASHBY_FORM, "provider": "ashby", "board": "acme",
                "found_by": "company site", "direct": True}]
        with mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            jobs.search_many(["Account Manager"], fetcher=lambda b: [], limit=5, discover=True,
                             http=lambda q: {"links": []}, companies=lambda roles, **kw: own)
        self.assertEqual(self.learned(), [("ashby", "acme", "Acme", "company site")])

    def test_a_job_the_ai_web_search_found_on_ashby_teaches_her_the_board(self):
        found = [{"title": "Account Manager", "company": "Beta", "location": "",
                  "apply_url": ASHBY_FORM.replace("/acme/", "/beta/"), "found_by": "ai web search"}]
        with mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            jobs.search_many(["Account Manager"], fetcher=lambda b: [], limit=5, discover=True,
                             http=lambda q: {"links": []}, companies=lambda roles, **kw: [],
                             websearch=lambda roles, **kw: found)
        self.assertEqual(self.learned(), [("ashby", "beta", "Beta", "ai web search")])

    def test_a_careers_page_host_is_not_a_board(self):
        self.assertEqual(jobs._learn_boards([{"provider": "company site", "board": "careers.acme.com"}]), 0)

    def test_a_token_that_could_carry_a_host_or_a_path_is_never_learned(self):
        self.assertEqual(jobs._learn_boards([{"provider": "recruitee", "board": "evil.com/x"},
                                             {"provider": "ashby", "board": "a/../b"}]), 0)

    def test_an_address_with_no_account_names_no_board(self):
        self.assertEqual(jobs.learn_board_urls([{"url": "https://apply.workable.com/j/AB12CD34EF"}],
                                               source="employer page"), 0)


class TheCampaignLearnsFromAnEmployersApplyLink(CampaignCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(jobs, "_learned_path", lambda: Path(self.tmp.name) / "learned.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_an_apply_link_to_ashby_is_staged_and_its_board_remembered(self):
        page = {"title": "Account Manager", "company": "Acme", "location": "",
                "apply_url": "https://careers.acme.com/jobs/1", "found_by": "company site",
                "direct": False, "provider": "company site", "board": "careers.acme.com"}

        def opener(url):
            if url == ASHBY_FORM:
                return list(FORM_FIELDS), []
            return list(POSTING_FIELDS), [{"href": ASHBY_FORM, "text": "Apply for this job"}]

        out = campaign.run("Account Manager", json_think=False, draft_essays_too=False,
                           searcher=lambda roles, **kw: {"matches": [page], "searched": 1},
                           opener=opener,
                           stager=lambda url, **kw: {"id": "apply-x", "state": "AWAITING_YOU", "url": url})
        self.assertEqual([r["url"] for r in out["ready"]], [ASHBY_FORM])
        self.assertIn(("ashby", "acme", "employer page"),
                      [(r["provider"], r["token"], r["from"]) for r in jobs._learned_boards()])


class ACaptchaOnTheFormIsWrittenDown(ApplyCase):
    def filler(self, captcha=""):
        def fake(url, steps, resume, shot):
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(b"png")
            return {"title": "Apply", "url": url, "captcha": captcha}
        return fake

    def test_a_captcha_the_browser_saw_is_on_the_record(self):
        record = apply_run.stage(LEVER_FORM, reader=self.reader(), filler=self.filler("hcaptcha"),
                                 extra={"#felony": "No", "#cert": True})
        self.assertEqual(record["state"], "AWAITING_YOU")
        self.assertEqual(apply_run.load_run(record["id"])["captcha"], "hcaptcha")
        self.assertIn("nothing is sent", record["captcha_note"])

    def test_a_widget_in_the_field_list_marks_a_form_that_stops_early(self):
        from tests.test_apply_run import FORM
        widget = {"selector": "#h-captcha-response", "label": "", "name": "h-captcha-response",
                  "id": "h-captcha-response", "tag": "textarea", "type": "textarea",
                  "required": False, "value": ""}
        record = apply_run.stage(LEVER_FORM, reader=self.reader(FORM + [widget]), filler=self.filler())
        self.assertEqual((record["state"], record["captcha"]), ("NEEDS_YOU", "hcaptcha"))

    def test_a_form_without_one_carries_no_mark(self):
        record = apply_run.stage(GH_FORM, reader=self.reader(), filler=self.filler(),
                                 extra={"#felony": "No", "#cert": True})
        self.assertNotIn("captcha", record)

    def test_the_send_path_names_the_invisible_check(self):
        class Page:
            def click(self, selector):
                raise TimeoutError("Timeout 30000ms exceeded. waiting for element to be enabled")

            def evaluate(self, script, arg=None):
                return {"captcha": False, "covered_by": "", "button_found": True}

            def screenshot(self, **kw):
                pass

        record = {"id": "apply-captcha", "url": LEVER_FORM, "captcha": "hcaptcha"}
        with self.assertRaises(apply_run.ApplyError) as said:
            apply_run._press(Page(), record, "#btn-submit")
        self.assertIn("hcaptcha", str(said.exception))
        self.assertIn("nothing was sent", str(said.exception))
        self.assertEqual(record["click_evidence"]["captcha_on_form"], "hcaptcha")
        self.assertNotIn("pressed_at", record)


class ABlockPageIsNotAnApplication(ApplyCase):
    """Live 2026-09-13 SmartRecruiters answered Equinox's one-click form with
    "Access is temporarily restricted", and its feedback box was staged
    AWAITING_YOU with nothing filled."""

    BLOCK = [{"selector": "#reason", "label": "Reason for contacting us (required):", "name": "reason",
              "id": "reason", "tag": "textarea", "type": "textarea", "required": False, "value": ""}]

    def test_a_page_that_asks_nothing_about_him_is_failed_and_named(self):
        filled = []
        url = "https://jobs.smartrecruiters.com/oneclick-ui/company/Acme/publication/u1?dcr_ci=Acme"
        with self.assertRaises(apply_run.ApplyError) as said:
            apply_run.stage(url, reader=self.reader(self.BLOCK),
                            filler=lambda *a: filled.append(a) or {})
        self.assertIn("not an application form", str(said.exception))
        self.assertEqual(filled, [], "no browser is spent filling it")
        self.assertEqual(apply_run.load_run(f"apply-{apply_run._tag(url)}")["state"], "FAILED")

    def test_the_bot_check_wording_closes_a_lead_before_a_browser(self):
        body = "<h1>Access is temporarily restricted</h1><p>We detected unusual activity from your device</p>"
        self.assertEqual(company_sites.still_open("https://x", fetch=lambda u: (200, u, body)),
                         (False, "the employer's site puts a bot check in front of its jobs"))


class WhichSystemsACaptchaHolds(unittest.TestCase):
    """Measured from the records, never a name written into the code."""

    def test_a_captcha_whose_sends_went_unconfirmed_is_a_risk(self):
        """Lever, measured: the form carries hCaptcha and both sends were
        "probably not received"."""
        records = [{"url": LEVER_FORM, "state": "AWAITING_YOU", "captcha": "hcaptcha"},
                   {"url": LEVER_FORM.replace("1111/", "1113/"), "state": "SUBMITTED",
                    "result": {"verdict": "probably not received"}},
                   {"url": ASHBY_FORM, "state": "AWAITING_YOU"}]
        self.assertEqual(apply_run.captcha_risky_providers(records), {"lever"})

    def test_a_captcha_nobody_has_pressed_through_yet_is_not_a_risk_yet(self):
        """Workable loads Turnstile; with no send tried, nothing says it blocks."""
        workable = "https://apply.workable.com/acme/j/AB12CD34EF/apply/"
        records = [{"url": workable, "state": "NEEDS_YOU", "captcha": "turnstile"}]
        self.assertEqual(apply_run.captcha_risky_providers(records), set())

    def test_a_captcha_that_sends_went_through_anyway_is_not(self):
        """Greenhouse loads reCAPTCHA and 57 of its sends came back confirmed."""
        records = [{"url": GH_FORM, "state": "AWAITING_YOU", "captcha": "recaptcha"},
                   {"url": GH_FORM.replace("42", "43"), "state": "SUBMITTED",
                    "result": {"verdict": "confirmed"}}]
        self.assertEqual(apply_run.captcha_risky_providers(records), set())

    def test_a_blocked_click_counts_and_an_unconfirmed_send_clears_nothing(self):
        records = [{"url": LEVER_FORM, "state": "FAILED", "click_evidence": {"captcha": True}},
                   {"url": LEVER_FORM.replace("1111/", "1112/"), "state": "SUBMITTED",
                    "result": {"verdict": "probably not received"}}]
        self.assertEqual(apply_run.captcha_risky_providers(records), {"lever"})


class EqualOpeningsPreferAFormWithoutACaptcha(unittest.TestCase):
    def page(self, name, url, score, provider=""):
        return {"title": name, "url": url, "score": score, "provider": provider}

    def test_between_equals_the_captcha_form_goes_later(self):
        pages = [self.page("L1", LEVER_FORM, 1.0, "lever"), self.page("G1", GH_FORM, 1.0, "greenhouse"),
                 self.page("A1", ASHBY_FORM, 1.0, "ashby"), self.page("L2", LEVER_FORM, 0.5, "lever"),
                 self.page("G2", GH_FORM, 0.5, "greenhouse")]
        out = campaign.captcha_later(pages, risky={"lever"})
        self.assertEqual([p["title"] for p in out], ["G1", "A1", "L1", "G2", "L2"])

    def test_a_better_match_is_never_passed_over_and_nothing_is_dropped(self):
        pages = [self.page("L1", LEVER_FORM, 1.0, "lever"), self.page("G1", GH_FORM, 0.5, "greenhouse")]
        self.assertEqual(campaign.captcha_later(pages, risky={"lever"}), pages)

    def test_nothing_measured_changes_nothing(self):
        pages = [self.page("L1", LEVER_FORM, 1.0, "lever"), self.page("G1", GH_FORM, 1.0, "greenhouse")]
        self.assertEqual(campaign.captcha_later(pages, risky=set()), pages)

    def test_the_system_is_read_from_the_address_when_the_page_does_not_say(self):
        pages = [self.page("L1", LEVER_FORM, 1.0), self.page("G1", GH_FORM, 1.0)]
        self.assertEqual([p["title"] for p in campaign.captcha_later(pages, risky={"lever"})], ["G1", "L1"])

    def test_by_default_it_asks_the_records(self):
        pages = [self.page("L1", LEVER_FORM, 1.0, "lever"), self.page("G1", GH_FORM, 1.0, "greenhouse")]
        with mock.patch.object(apply_run, "captcha_risky_providers", return_value={"lever"}):
            self.assertEqual([p["title"] for p in campaign.captcha_later(pages)], ["G1", "L1"])


class ABoardNamesItsEmployer(unittest.TestCase):
    def test_ashby_by_its_page_title(self):
        asked = []
        name = jobs._board_name("ashby", "ramp",
                                page=lambda url: asked.append(url) or "<html><title>Ramp Jobs</title>")
        self.assertEqual((name, asked), ("Ramp", ["https://jobs.ashbyhq.com/ramp"]))

    def test_workable_by_its_feed_and_lever_not_at_all(self):
        self.assertEqual(jobs._board_name("workable", "hf", fetch=lambda url: {"name": "Hugging Face"}),
                         "Hugging Face")
        self.assertEqual(jobs._board_name("lever", "acme", fetch=lambda url: {"name": "x"}), "")


class SeedingFromWhatSheHasAlreadySeen(LearningCase):
    def test_only_new_boards_on_systems_she_can_list(self):
        seen = [{"url": "https://job-boards.greenhouse.io/stripe/jobs/1", "company": "Stripe"},
                {"url": ASHBY_FORM, "company": "Acme", "from": "application record"},
                {"url": "https://apply.workable.com/j/AB12CD34EF", "company": "NoAccount"},
                {"url": LEVER_FORM, "company": "Acme"}, {"url": LEVER_FORM, "company": "Acme"},
                {"url": "https://careers.example.com/jobs/1", "company": "Example"}]
        with mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "stripe"}]):
            found = jobs.boards_seen(seen)
        self.assertEqual([(f["provider"], f["board"], f["found_by"]) for f in found],
                         [("ashby", "acme", "application record"), ("lever", "acme", "")])

    def test_only_a_board_that_answers_with_openings_is_kept(self):
        def fetcher(board):
            if board["token"] == "down":
                raise OSError("refused")
            return [] if board["token"] == "empty" else [{"company": "Acme Inc"}]
        proved = {p["board"]: p for p in jobs.prove_boards(
            [{"provider": "ashby", "board": b, "company": ""} for b in ("live", "empty", "down")],
            fetcher=fetcher)}
        self.assertEqual({b: p["live"] for b, p in proved.items()},
                         {"live": True, "empty": False, "down": False})
        self.assertEqual(proved["live"]["company"], "Acme Inc")
        self.assertIn("refused", proved["down"]["why"])

    def test_the_seed_script_follows_listings_to_the_board_and_leaves_no_setting_changed(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "seed_learned_boards.py"
        spec = importlib.util.spec_from_file_location("seed_learned_boards", path)
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        lead = {"title": "Account Manager", "company": "Acme", "lead": "https://www.themuse.com/jobs/acme/1"}
        usual = company_sites.PAGES_PER_CATEGORY
        with mock.patch.object(company_sites, "muse_leads", return_value=[lead]):
            rows, read = script.muse_urls(
                company_sites, ["Account Manager"], "", pages=9, most=10,
                fetch=lambda url: (200, url, muse_page(f"https://jobs.ashbyhq.com/acme/{JID}")))
        self.assertEqual((rows, read), ([{"url": f"https://jobs.ashbyhq.com/acme/{JID}",
                                          "company": "Acme", "from": "company site"}], 1))
        self.assertEqual(company_sites.PAGES_PER_CATEGORY, usual)


if __name__ == "__main__":
    unittest.main()
