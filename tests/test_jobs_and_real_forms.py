"""Where the jobs come from, and a real employer's form.

The campaign was proved against a job board I wrote myself. On the real
internet it found NOTHING: `research.find_sources` drives a headless
browser at a search engine, and a search engine answers a headless
browser with a challenge page. Zero openings, and everything downstream
of it was theatre. That is the difference between a demo and a thing that
works, and it is why he said it was not fixed.

Jobs now come from the systems that PUBLISH them — Greenhouse and Lever,
public JSON, no key — and both host the real application form at a public
URL with no login. A posting she can find but not apply to is a link he
could have found himself.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import formfill, jobs, journal, profile

GH = {"jobs": [
    {"id": 1, "title": "Senior Software Engineer, Video",
     "location": {"name": "Remote - US"},
     "absolute_url": "https://example.com/jobs/1"},
    {"id": 2, "title": "Office Manager", "location": {"name": "Dublin"},
     "absolute_url": "https://example.com/jobs/2"}]}
LV = [{"id": "abc", "text": "Software Engineer, Platform",
       "categories": {"location": "Remote"},
       "hostedUrl": "https://jobs.lever.co/acme/abc"}]


class JobsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              Path(self.tmp.name) / "j.jsonl")
        p.start(); self.addCleanup(p.stop)
        self.boards = [{"provider": "greenhouse", "token": "acme", "company": "Acme"},
                       {"provider": "lever", "token": "acme", "company": "Acme"}]
        b = mock.patch.object(jobs, "boards", lambda: self.boards)
        b.start(); self.addCleanup(b.stop)

    def fetcher(self, fail=()):
        def fetch(board):
            if board["token"] in fail:
                raise OSError("network said no")
            return (jobs._greenhouse(board) if board["provider"] == "greenhouse"
                    else jobs._lever(board))
        return fetch


class TheRightJobsForHimCase(JobsCase):
    """Live 2026-09-10, for a Business Development Associate in South Dakota,
    the top matches were "Accounts Receivable Manager" and "Fraud Operations
    Manager (Mandarin-speaking)", in Dublin, Bengaluru and Singapore."""

    def rows(self, *titles_and_places):
        return [{"title": title, "company": f"Co{i}", "location": place,
                 "apply_url": f"u{i}"}
                for i, (title, place) in enumerate(titles_and_places)]

    def search(self, roles, rows, **kw):
        with mock.patch.object(jobs, "boards",
                               return_value=[{"provider": "greenhouse", "token": "t"}]):
            return jobs.search_many(roles, fetcher=lambda board: rows, limit=10, **kw)

    def test_a_generic_word_alone_is_not_a_match(self):
        out = self.search(["Account Manager"], self.rows(
            ("Accounts Receivable Manager", ""), ("Account Manager, SMB", ""),
            ("Corporate Accounting Manager", "")))
        self.assertEqual([j["title"] for j in out["matches"]], ["Account Manager, SMB"])

    def test_only_jobs_in_his_country(self):
        out = self.search(["Account Manager"], self.rows(
            ("Account Manager", "Dublin"), ("Account Manager", "Bengaluru, India"),
            ("Account Manager", "Austin, TX"), ("Account Manager", "Remote - US"),
            ("Account Manager", "Remote - EMEA"), ("Account Manager", "New York, New York"),
            ("Account Manager", "Hybrid"), ("Account Manager", "CA-Toronto, CA-Montreal"),
            ("Account Manager", "Chicago, Seattle, NYC, San Francisco"),
            ("Account Manager", "Sioux Falls"), ("Account Manager", "Vancouver, WA")),
            country="United States")
        self.assertEqual(sorted(j["location"] for j in out["matches"]),
                         sorted(["Austin, TX", "Remote - US", "New York, New York",
                                 "Chicago, Seattle, NYC, San Francisco", "Sioux Falls",
                                 "Vancouver, WA"]))

    def test_too_senior_titles_are_left_out_when_asked(self):
        out = self.search(["Business Development"], self.rows(
            ("Senior Business Development Manager", ""),
            ("Business Development Representative", ""),
            ("Head of Business Development", "")), exclude=jobs.SENIOR_TITLE_WORDS)
        self.assertEqual([j["title"] for j in out["matches"]],
                         ["Business Development Representative"])

    def test_a_site_search_answered_with_other_sites_tries_the_next_engine(self):
        """Bing's RSS ignores site: (live 2026-09-10: Investopedia and Indeed
        for site:boards.greenhouse.io), so no job was ever found by searching."""
        from aletheia import research

        class Answer:
            def __init__(self, body):
                self.status, self.body = 200, body.encode()

            def read(self, n=-1):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(request, timeout=0):
            if "format=rss" in request.full_url:
                return Answer("<rss><item><title>Indeed</title><link>https://www.indeed.com/q</link>"
                              "<description>jobs</description></item></rss>")
            return Answer('<a class="result__a" href="https://job-boards.greenhouse.io/acme/jobs/123">'
                          'Account Executive - Acme</a>')
        got = research.http_search('site:job-boards.greenhouse.io "Account Executive"', opener=opener)
        self.assertEqual(got["engine"], "duckduckgo-html")
        self.assertEqual([link["href"] for link in got["links"]],
                         ["https://job-boards.greenhouse.io/acme/jobs/123"])

    def test_a_result_wrapped_in_a_redirect_is_still_a_job(self):
        page = {"links": [{"href": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fjob-boards.greenhouse.io"
                                   "%2Facme%2Fjobs%2F555&rut=x", "text": "Account Executive"}]}
        found = jobs.discover_openings(["Account Executive"], limit=5, http=lambda q: page)
        self.assertEqual([j["apply_url"] for j in found],
                         ["https://boards.greenhouse.io/embed/job_app?for=acme&token=555"])

    def test_a_search_result_title_is_the_job_and_its_employer(self):
        page = {"links": [{"href": "https://job-boards.greenhouse.io/tebra/jobs/42",
                           "text": "Job Application for Account Executive, Growth at Tebra"}]}
        found = jobs.discover_openings(["Account Executive"], limit=5, http=lambda q: page)
        self.assertEqual((found[0]["title"], found[0]["company"]),
                         ("Account Executive, Growth", "Tebra"))

    def test_enterprise_and_strategic_are_left_out_for_someone_early(self):
        out = self.search(["Account Executive"], self.rows(
            ("Enterprise Account Executive", ""), ("Strategic Account Executive", ""),
            ("Account Executive, SMB", "")), exclude=jobs.SENIOR_TITLE_WORDS)
        self.assertEqual([j["title"] for j in out["matches"]], ["Account Executive, SMB"])

    def test_a_title_that_manages_the_team_is_left_out_for_someone_early(self):
        out = self.search(["Account Manager"], self.rows(
            ("Manager, Account Management", ""),
            ("Sales Manager, Account Executives - Startups", ""),
            ("Account Manager, SMB", "")), exclude=jobs.SENIOR_TITLE_WORDS)
        self.assertEqual([j["title"] for j in out["matches"]], ["Account Manager, SMB"])

    def test_one_from_each_employer_before_a_second_from_any(self):
        rows = [{"title": "Account Manager", "company": "Big", "location": "",
                 "apply_url": f"b{i}"} for i in range(5)]
        rows.append({"title": "Account Manager", "company": "Small", "location": "",
                     "apply_url": "s0"})
        out = self.search(["Account Manager"], rows)
        self.assertEqual([j["company"] for j in out["matches"][:2]], ["Big", "Small"])

    def test_web_found_employers_always_get_a_share(self):
        rows = self.rows(*[("Account Manager", "") for _ in range(20)])
        page = {"links": [{"href": f"https://boards.greenhouse.io/other{i}/jobs/{100 + i}",
                           "text": "Account Manager"} for i in range(5)]}
        out = self.search(["Account Manager"], rows, discover=True, http=lambda q: page)
        self.assertGreaterEqual(out["discovered"], 3)
        self.assertEqual(out["matches"][2].get("found_by"), "web search")


class TheOpeningsAreREAL(JobsCase):
    def test_a_greenhouse_job_carries_a_form_url_that_needs_no_login(self):
        with mock.patch.object(jobs, "_fetch", return_value=GH):
            out = jobs.search("software engineer video", fetcher=jobs._greenhouse)
        job = out["matches"][0]
        self.assertIn("boards.greenhouse.io/embed/job_app", job["apply_url"])
        self.assertIn("for=acme", job["apply_url"])
        self.assertIn("token=1", job["apply_url"])

    def test_a_lever_job_carries_its_apply_page(self):
        with mock.patch.object(jobs, "_fetch", return_value=LV):
            out = jobs.search("software engineer platform", fetcher=jobs._lever)
        self.assertTrue(out["matches"][0]["apply_url"].endswith("/abc/apply"))

    def test_an_unrelated_job_does_not_match(self):
        with mock.patch.object(jobs, "_fetch", return_value=GH):
            out = jobs.search("software engineer", fetcher=jobs._greenhouse)
        self.assertNotIn("Office Manager", [j["title"] for j in out["matches"]])

    def test_location_moves_a_job_up_or_down(self):
        with mock.patch.object(jobs, "_fetch", return_value=GH):
            remote = jobs.search("engineer", where="remote",
                                 fetcher=jobs._greenhouse)["matches"]
        self.assertTrue(remote)
        self.assertIn("Remote", remote[0]["location"])

    def test_a_board_that_did_not_answer_is_FAILED_not_empty(self):
        """"No jobs matched" and "the network refused me" are different
        answers and only one of them means try different words."""
        with mock.patch.object(jobs, "_fetch", side_effect=OSError("refused")):
            out = jobs.search("engineer")
        self.assertEqual(out["matches"], [])
        self.assertEqual(len(out["failed"]), 2)
        self.assertIn("OSError", out["failed"][0]["why"])

    def test_a_board_the_provider_says_is_GONE_is_not_the_same_as_unreachable(self):
        """A timeout is worth retrying; a 404 is a company that renamed or
        left the provider and will 404 forever. Three of them sat dead in
        the shipped file, reported identically to a network blip on every
        search, so every search covered three companies fewer than the
        file claimed and nothing ever said so."""
        import urllib.error
        gone = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch.object(jobs, "notifications", create=True), \
             mock.patch("aletheia.notifications.publish") as told, \
             mock.patch.object(jobs.urllib.request, "urlopen", side_effect=gone):
            out = jobs.search("engineer")
        self.assertEqual(len(out["failed"]), 2)
        self.assertTrue(all(f["gone"] for f in out["failed"]))
        self.assertTrue(told.called, "a dead board must reach him, not just the journal")

    def test_an_unreachable_board_is_not_reported_as_gone(self):
        """The distinction has to hold in the other direction too, or the
        first flaky wifi moment tells him a company left the internet."""
        with mock.patch("aletheia.notifications.publish") as told, \
             mock.patch.object(jobs, "_fetch", side_effect=OSError("refused")):
            out = jobs.search("engineer")
        self.assertTrue(out["failed"])
        self.assertFalse(any(f["gone"] for f in out["failed"]))
        self.assertFalse(told.called)

    def test_the_complaint_is_deduped_per_board(self):
        """A board that is gone today is gone tomorrow. Nagging daily is
        how he learns to ignore the notice that matters."""
        import urllib.error
        gone = urllib.error.HTTPError("u", 410, "Gone", {}, None)
        with mock.patch("aletheia.notifications.publish") as told, \
             mock.patch.object(jobs.urllib.request, "urlopen", side_effect=gone):
            jobs.search("engineer")
        keys = {c.kwargs["dedupe_key"] for c in told.call_args_list}
        # One notice per DEAD BOARD, and the fixture is deliberately two
        # boards sharing the token "acme" on different providers: a token
        # is unique only within a provider, and keying on it alone
        # collapsed two dead boards into a single notice.
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(keys), len(told.call_args_list))
        self.assertEqual(keys, {"jobs:board-gone:greenhouse:acme",
                                "jobs:board-gone:lever:acme"})

    def test_a_search_still_works_when_it_cannot_complain(self):
        """A search must not fail because the notifier did."""
        import urllib.error
        gone = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch("aletheia.notifications.publish",
                        side_effect=RuntimeError("store gone")), \
             mock.patch.object(jobs.urllib.request, "urlopen", side_effect=gone):
            out = jobs.search("engineer")
        self.assertEqual(out["matches"], [])

    def test_check_proves_every_board_and_names_the_dead_ones(self):
        """The board file rots on its own — companies rename, get acquired,
        or move provider — and a search never says the list has shrunk."""
        def half(board):
            if board["provider"] == "lever":
                raise jobs.BoardGone("no such board (HTTP 404)")
            return [{"title": "Engineer", "company": "Acme", "location": "Remote",
                     "url": "u", "apply_url": "a", "id": "1", "provider": "greenhouse"}]
        with mock.patch.dict(jobs.PROVIDERS, {"greenhouse": half, "lever": half}):
            out = jobs.check()
        self.assertEqual(out["live"], 1)
        self.assertEqual(out["dead"], 1)
        self.assertEqual(out["openings"], 1)
        dead = [b for b in out["boards"] if not b["live"]][0]
        self.assertIn("404", dead["why"])

    def test_no_boards_configured_says_which_file(self):
        with mock.patch.object(jobs, "boards", lambda: []):
            with self.assertRaises(jobs.JobsError) as caught:
                jobs.search("engineer")
        self.assertIn("job_boards.json", str(caught.exception))

    def test_the_shipped_board_list_is_real_and_well_formed(self):
        rows = json.loads(jobs.BOARDS_PATH.read_text(encoding="utf-8"))["boards"]
        self.assertGreater(len(rows), 15)
        for row in rows:
            self.assertIn(row["provider"], jobs.PROVIDERS, row)
            self.assertTrue(row["token"] and row["company"], row)

    def test_the_campaign_uses_it_rather_than_a_search_engine(self):
        body = (Path(__file__).parent.parent / "aletheia" / "campaign.py"
                ).read_text(encoding="utf-8")
        # search_many since 2026-09-10: the roles come from the resume, and
        # every one of them is searched against the same public boards.
        self.assertIn("jobs.search_many", body)


class ARealEmployersForm(unittest.TestCase):
    """Not a form I wrote: 124 KB of markup saved from a live Stripe
    application on Greenhouse."""

    FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse-real.html"

    def setUp(self):
        if not self.FIXTURE.is_file():
            self.skipTest("real form fixture missing")
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            self.skipTest("playwright is not installed")
        self.chrome = next((str(p) for p in Path("/opt/pw-browsers").glob(
            "chromium-*/chrome-linux/chrome")), None)
        d = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (profile, "path", lambda: d / "a.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        profile.learn_from_resume(
            "Caleb Schulte\nAustin, TX\ncaleb@example.com | (512) 555-0134\n"
            "linkedin.com/in/caleb-schulte")
        for key, value in (("work_authorization", "Yes"),
                           ("needs_sponsorship", "No"),
                           ("country", "United States"),
                           ("willing_to_relocate", "No"),
                           ("current_employer", "Self-employed"),
                           ("current_title", "Software Engineer"),
                           ("school", "Texas State University"),
                           ("degree", "Bachelor's Degree")):
            profile.set_answer(key, value, source="operator")

    # ONE browser launch for the whole class. Each of these tests read the
    # same 124 KB of static markup, and each was launching its own
    # Chromium to do it: 13 seconds apiece, 67 for the file, for a value
    # that cannot differ between them. The fixture is a file:// URI and
    # depends on nothing this class sets up per test.
    _fields = None

    def fields(self):
        if ARealEmployersForm._fields is None:
            ARealEmployersForm._fields = self._read_the_form()
        return ARealEmployersForm._fields

    def _read_the_form(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            kwargs = {"args": ["--no-sandbox"]}
            if self.chrome:
                kwargs["executable_path"] = self.chrome
            try:
                browser = pw.chromium.launch(**kwargs)
            except Exception as exc:
                self.skipTest(f"no chromium: {type(exc).__name__}")
            page = browser.new_page()
            page.goto(self.FIXTURE.as_uri())
            found = page.evaluate(formfill.READ_FORM_JS)
            browser.close()
        return found

    def test_she_fills_the_real_fields(self):
        out = formfill.plan(self.fields())
        filled = {f["label"]: f["value"] for f in out["fill"]}
        self.assertEqual(filled.get("First Name*"), "Caleb")
        self.assertEqual(filled.get("Email*"), "caleb@example.com")
        self.assertEqual(filled.get("Phone*"), "(512) 555-0134")
        self.assertEqual(filled.get("Country*"), "United States")
        self.assertGreaterEqual(len(out["fill"]), 10)

    def test_twenty_six_checkboxes_are_ONE_question(self):
        """A real Stripe application asks "which countries do you
        anticipate working in?" as thirty checkboxes. Read one at a time
        they became thirty required questions labelled Australia, Belgium,
        Brazil — every one unanswerable, and between them they buried the
        handful he actually had to answer."""
        out = formfill.plan(self.fields())
        labels = [a["label"] for a in out["ask"]]
        self.assertNotIn("Australia", labels)
        self.assertNotIn("Belgium", labels)
        countries = next(a for a in out["ask"] if "countries" in a["label"])
        self.assertGreater(len(countries["choices"]), 20)
        self.assertIn("Australia", countries["choices"])

    def test_what_is_left_for_him_is_SMALL(self):
        out = formfill.plan(self.fields())
        required = [a for a in out["ask"] if a["required"]]
        self.assertLess(len(required), 8,
                        f"too many questions left: {[a['label'] for a in required]}")

    def test_self_identification_is_still_always_his(self):
        out = formfill.plan(self.fields())
        asked = " ".join(a["label"].casefold() for a in out["ask"])
        for word in ("gender", "veteran", "disability"):
            self.assertIn(word, asked, word)
        filled = " ".join(f["label"].casefold() for f in out["fill"])
        for word in ("gender", "veteran", "disability", "ethnic"):
            self.assertNotIn(word, filled, word)

    def test_the_resume_upload_is_recognised_and_left_alone(self):
        out = formfill.plan(self.fields())
        self.assertTrue(any("attach" in s["label"].casefold()
                            for s in out["skipped"]))


class HeAnswersAChoiceQuestion(unittest.TestCase):
    def test_naming_options_ticks_exactly_those(self):
        fields = [{"selector": "#a", "label": "United States", "option": "United States",
                   "question": "Which countries?", "group": "q1", "name": "q1[]",
                   "id": "a", "tag": "input", "type": "checkbox", "required": True,
                   "value": ""},
                  {"selector": "#b", "label": "Canada", "option": "Canada",
                   "question": "Which countries?", "group": "q1", "name": "q1[]",
                   "id": "b", "tag": "input", "type": "checkbox", "required": True,
                   "value": ""}]
        out = formfill.plan(fields)
        self.assertEqual(len(out["ask"]), 1)
        got = formfill.apply_answers(out, fields,
                                     {out["ask"][0]["selector"]: "United States"})
        self.assertEqual(got["steps"], [{"action": "click", "selector": "#a"}])
        self.assertEqual(out["ask"], [])

    def test_an_option_it_does_not_have_is_refused_not_approximated(self):
        """"United States" is not "United Kingdom"."""
        fields = [{"selector": "#a", "label": "United Kingdom",
                   "option": "United Kingdom", "question": "Which countries?",
                   "group": "q1", "name": "q1[]", "id": "a", "tag": "input",
                   "type": "checkbox", "required": True, "value": ""},
                  {"selector": "#b", "label": "Ireland", "option": "Ireland",
                   "question": "Which countries?", "group": "q1", "name": "q1[]",
                   "id": "b", "tag": "input", "type": "checkbox",
                   "required": True, "value": ""}]
        out = formfill.plan(fields)
        got = formfill.apply_answers(out, fields,
                                     {out["ask"][0]["selector"]: "Japan"})
        self.assertEqual(got["steps"], [])
        self.assertTrue(got["refused"])

    def test_a_lone_checkbox_stays_a_checkbox(self):
        """The certification tickbox is not a question with one option."""
        fields = [{"selector": "#cert", "label": "I certify this is true",
                   "option": "I certify this is true", "question": "",
                   "group": "cert", "name": "cert", "id": "cert",
                   "tag": "input", "type": "checkbox", "required": True,
                   "value": ""}]
        out = formfill.plan(fields)
        self.assertEqual(out["ask"][0]["label"], "I certify this is true")
        self.assertNotIn("choices", out["ask"][0])


class SheWritesTheEssayInsteadOfAskingIt(unittest.TestCase):
    def test_a_long_answer_is_drafted_from_his_resume(self):
        from aletheia import campaign
        record = {"url": "https://x", "job_title": "ML Engineer",
                  "questions": [{"selector": "#why", "type": "textarea",
                                 "label": "Describe your experience with ranking",
                                 "required": True, "why": "written answer"}]}
        seen = {}

        def think(system, text, **kw):
            seen["system"] = system
            seen["resume"] = text
            return "I built the ranking that decides which topics get made."
        got = campaign.draft_essays(record, "RESUME TEXT", think=think)
        self.assertEqual(list(got), ["#why"])
        self.assertIn("Describe your experience with ranking", seen["system"])
        self.assertIn("RESUME TEXT", seen["resume"])

    def test_a_question_his_resume_cannot_answer_comes_back_BLANK(self):
        """A made-up answer on a job application is worse than a blank."""
        from aletheia import campaign
        record = {"url": "https://x", "job_title": "Chef",
                  "questions": [{"selector": "#why", "type": "textarea",
                                 "label": "Describe your pastry experience",
                                 "required": True, "why": "written answer"}]}
        got = campaign.draft_essays(record, "RESUME", think=lambda *a, **k:
                                    "CANNOT WRITE — his resume says nothing about pastry.")
        self.assertEqual(got, {})

    def test_the_brief_forbids_inventing(self):
        from aletheia import campaign
        flat = " ".join(campaign.ESSAY_BRIEF.split())
        self.assertIn("ONLY what his resume below actually says", flat)
        self.assertIn("CANNOT WRITE", flat)

    def test_a_choice_question_is_never_drafted_as_prose(self):
        from aletheia import campaign
        record = {"questions": [{"selector": "#c", "type": "checkbox",
                                 "label": "Which countries?", "required": True,
                                 "choices": ["Japan"], "why": "choice"}]}
        self.assertEqual(campaign.draft_essays(record, "R",
                                               think=lambda *a, **k: "text"), {})


if __name__ == "__main__":
    unittest.main()
