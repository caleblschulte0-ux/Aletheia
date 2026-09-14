"""Jobs anywhere on the internet, not only on the boards she already knows.

His words, 2026-09-13 night: "keep applying to jobs everywhere across the
Internet, not just on Greenhouse". Plain web search is dead from his PC, so
the search is done by the tools inside his two subscriptions, through their
official CLIs, and nothing a model says about a job is believed until the
page itself is loaded. Every CLI and every HTTP fetch here is stubbed.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import jobs, journal, proc, reasoner, web_search_jobs as wsj

ROLES = ["Customer Success Manager", "Account Manager"]


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        for target, name, value in (
                (wsj, "_state_path", lambda: self.dir / "web_search.json"),
                (wsj, "_cache_path", lambda: self.dir / "web_search_cache.json"),
                (reasoner, "_rest_path", lambda: self.dir / "claude-rest.json"),
                (journal, "JOURNAL_PATH", self.dir / "journal.jsonl"),
                (jobs, "_learned_path", lambda: self.dir / "learned.json")):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)


def answer(*rows) -> str:
    return json.dumps({"postings": [dict(r) for r in rows]})


def done(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


# ---- the tools: windowless, read-only, and Claude gets ONLY web search ----------

class ClaudeCanOnlySearch(Isolated):
    def test_the_only_tool_is_web_search(self):
        argv = wsj.claude_argv("claude")
        self.assertEqual(argv[argv.index("--tools") + 1], "WebSearch")
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "WebSearch")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        joined = " ".join(argv)
        for never in ("Bash", "WebFetch", "Edit", "Write", "dangerously", "bypassPermissions",
                      "--mcp-config"):
            self.assertNotIn(never, joined)

    def test_it_runs_windowless_with_the_prompt_on_stdin_and_a_time_limit(self):
        seen = {}

        def run_tree(cmd, timeout_s, **kw):
            seen.update(cmd=cmd, timeout=timeout_s, **kw)
            return done(json.dumps({"result": answer(), "is_error": False}))
        with mock.patch.object(reasoner, "cli_path", return_value="claude"), \
             mock.patch.object(proc, "run_tree", side_effect=run_tree):
            wsj._claude_search("system", "the prompt")
        self.assertEqual(seen["input"], "the prompt")
        self.assertNotIn("the prompt", seen["cmd"])
        self.assertTrue(seen["cwd"])
        self.assertGreater(seen["timeout"], 0)

    def test_run_tree_hides_the_window_and_feeds_stdin(self):
        class Child:
            pid, returncode = 1, 0

            def communicate(self, input=None, timeout=None):
                Child.given = input
                return "out", ""
        with mock.patch.object(subprocess, "Popen", return_value=Child()) as popen:
            proc.run_tree(["x"], 5, input="hello")
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["creationflags"] & proc.NO_WINDOW, proc.NO_WINDOW)
        self.assertEqual(kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(Child.given, "hello")

    def test_a_search_out_of_time_is_unavailable_not_a_crash(self):
        with mock.patch.object(reasoner, "cli_path", return_value="claude"), \
             mock.patch.object(proc, "run_tree", side_effect=subprocess.TimeoutExpired("c", 1)):
            with self.assertRaises(wsj.SearchUnavailable):
                wsj._claude_search("s", "p")

    def test_a_spent_window_is_remembered_like_the_reasoner_does(self):
        said = "You've hit your session limit · resets 4:40pm (UTC)"
        with mock.patch.object(reasoner, "cli_path", return_value="claude"), \
             mock.patch.object(proc, "run_tree", return_value=done("", said, 1)):
            with self.assertRaises(wsj.SearchUnavailable):
                wsj._claude_search("s", "p")
        self.assertIsNotNone(reasoner.resting_until())
        ok, why = wsj._claude_ready()
        self.assertFalse(ok)
        self.assertIn("out until", why)


class CodexIsReadOnly(Isolated):
    def test_search_is_switched_on_and_nothing_can_be_written(self):
        argv = wsj.codex_argv("codex.exe", "C:/w", "C:/w/a.txt")
        self.assertEqual(argv[1], "exec")
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(argv[argv.index("-c") + 1], 'web_search="live"')
        for flag in ("--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
                     "--output-last-message"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[-1], "-")            # the prompt is read from stdin
        joined = " ".join(argv)
        self.assertNotIn("dangerously", joined)
        self.assertNotIn("workspace-write", joined)

    def test_an_expired_login_is_remembered_and_codex_is_not_asked_again(self):
        calls = []

        def run_tree(cmd, timeout_s, **kw):
            calls.append(cmd)
            return done("", "ERROR: unexpected status 401 Unauthorized: refresh token expired", 1)
        with mock.patch.object(wsj, "codex_path", return_value="codex.exe"), \
             mock.patch.object(proc, "run_tree", side_effect=run_tree):
            with self.assertRaises(wsj.SearchUnavailable) as caught:
                wsj._codex_search("s", "p")
            self.assertIn("login", str(caught.exception))
            ok, why = wsj._codex_ready()
            self.assertFalse(ok)
            self.assertIn("codex login", why)
            with mock.patch.object(wsj, "_claude_ready", return_value=(False, "resting")):
                with self.assertRaises(wsj.SearchUnavailable):
                    wsj._ask("s", "p", [])
        self.assertEqual(len(calls), 1)

    def test_it_is_skipped_when_it_is_not_installed(self):
        with mock.patch.object(wsj, "codex_path", return_value=None):
            self.assertFalse(wsj._codex_ready()[0])


class WhoIsAsked(Isolated):
    def providers(self, claude_ready=(True, ""), claude=None, codex_ready=(True, ""), codex=None):
        self.asked = []

        def claude_search(s, p):
            self.asked.append("Claude")
            if isinstance(claude, Exception):
                raise claude
            return claude or answer()

        def codex_search(s, p):
            self.asked.append("Codex")
            if isinstance(codex, Exception):
                raise codex
            return codex or answer()
        return [mock.patch.object(wsj, "_claude_ready", return_value=claude_ready),
                mock.patch.object(wsj, "_claude_search", side_effect=claude_search),
                mock.patch.object(wsj, "_codex_ready", return_value=codex_ready),
                mock.patch.object(wsj, "_codex_search", side_effect=codex_search)]

    def run_with(self, patches):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        spent = []
        return wsj._ask("s", "p", spent), spent

    def test_claude_first_and_codex_only_when_needed(self):
        (text, by), spent = self.run_with(self.providers())
        self.assertEqual((by, self.asked, spent), ("Claude", ["Claude"], ["Claude"]))

    def test_claude_resting_goes_straight_to_codex(self):
        (text, by), spent = self.run_with(self.providers(claude_ready=(False, "Claude is out")))
        self.assertEqual((by, self.asked), ("Codex", ["Codex"]))

    def test_claude_failing_falls_to_codex(self):
        (text, by), spent = self.run_with(self.providers(claude=wsj.SearchUnavailable("x")))
        self.assertEqual(self.asked, ["Claude", "Codex"])
        self.assertEqual(spent, ["Claude", "Codex"])

    def test_nobody_able_to_search_says_why(self):
        for p in self.providers(claude_ready=(False, "Claude is out until 4 PM"),
                                codex_ready=(False, "his login expired")):
            p.start()
            self.addCleanup(p.stop)
        with self.assertRaises(wsj.SearchUnavailable) as caught:
            wsj._ask("s", "p", [])
        self.assertIn("4 PM", str(caught.exception))
        self.assertIn("login", str(caught.exception))
        self.assertEqual(self.asked, [])

    def test_resting_claude_is_really_read_from_the_reasoner(self):
        reasoner._rest(dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2), "limit")
        ok, why = wsj._claude_ready()
        self.assertFalse(ok)


# ---- budget, cache, rotation ----------------------------------------------------

class HisWindowIsSpentCarefully(Isolated):
    def searcher(self, rows=None):
        prompts = []

        def search(system, prompt):
            prompts.append(json.loads(prompt))
            n = len(prompts)
            return answer(*(rows or [{"title": "Account Manager", "company": f"C{n}",
                                      "url": f"https://careers.c{n}.com/jobs/{1000 + n}"}])), "Claude"
        search.prompts = prompts
        return search

    def test_a_batch_makes_at_most_three_searches(self):
        search = self.searcher()
        report = {}
        found = wsj.find_postings(ROLES, searcher=search, report=report)
        self.assertEqual(len(search.prompts), wsj.MAX_SEARCHES_PER_BATCH)
        self.assertEqual(report["searches"], 3)
        self.assertEqual(len(found), 3)

    def test_the_next_batch_asks_differently(self):
        search = self.searcher()
        wsj.find_postings(ROLES, searcher=search)
        wsj.find_postings(ROLES, searcher=search)
        asked = [(tuple(p["roles"]), p["look_in"]) for p in search.prompts]
        self.assertEqual(len(asked), 6)
        self.assertEqual(len(set(asked)), 6, "a later batch repeated a search it had paid for")

    def test_the_day_has_a_cap(self):
        search = self.searcher()
        wsj.find_postings(ROLES, searcher=search, per_day=4)
        report = {}
        wsj.find_postings(ROLES, searcher=search, per_day=4, report=report)
        self.assertEqual(len(search.prompts), 4)
        self.assertIn("spent", report["stopped"])
        wsj.find_postings(ROLES, searcher=search, per_day=4,
                          now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
        self.assertGreater(len(search.prompts), 4, "a new day gets its searches back")

    def test_the_same_question_within_a_day_is_answered_from_the_cache(self):
        search = self.searcher()
        first = wsj.find_postings(ROLES, searcher=search)
        wsj._write(wsj._state_path(), {**wsj._read(wsj._state_path()), "cursor": 0})
        report = {}
        again = wsj.find_postings(ROLES, searcher=search, report=report)
        self.assertEqual(len(search.prompts), 3)
        self.assertEqual(report["cached"], 3)
        self.assertEqual([p["url"] for p in again], [p["url"] for p in first])

    def test_a_day_old_answer_is_searched_again(self):
        search = self.searcher()
        wsj.find_postings(ROLES, searcher=search)
        wsj._write(wsj._state_path(), {**wsj._read(wsj._state_path()), "cursor": 0})
        wsj.find_postings(ROLES, searcher=search,
                          now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=25))
        self.assertEqual(len(search.prompts), 6)

    def test_an_unreadable_answer_is_not_cached(self):
        calls = []

        def search(system, prompt):
            calls.append(1)
            return "I found some great jobs for you!", "Claude"
        report = {}
        self.assertEqual(wsj.find_postings(ROLES, searcher=search, report=report), [])
        self.assertEqual(report["unreadable"], 3)
        self.assertEqual(wsj._load_cache(dt.datetime.now(dt.timezone.utc)), {})

    def test_nobody_to_search_stops_the_batch_and_spends_nothing(self):
        with mock.patch.object(wsj, "_claude_ready", return_value=(False, "out")), \
             mock.patch.object(wsj, "_codex_ready", return_value=(False, "login expired")):
            report = {}
            self.assertEqual(wsj.find_postings(ROLES, report=report), [])
        self.assertEqual(report["searches"], 0)
        self.assertIn("login expired", report["stopped"])

    def test_no_roles_no_search(self):
        search = self.searcher()
        self.assertEqual(wsj.find_postings([], searcher=search), [])
        self.assertEqual(search.prompts, [])

    def test_his_words_travel_with_every_search(self):
        search = self.searcher()
        wsj.find_postings(ROLES, searcher=search, wanted="customer success",
                          not_wanted="no cold calling, no quotas", country="United States")
        self.assertTrue(all(p["he_will_not_do"] == "no cold calling, no quotas" for p in search.prompts))
        self.assertIn("Indeed", wsj.SYSTEM)
        self.assertIn("LinkedIn", wsj.SYSTEM)

    def test_the_answer_is_held_to_the_strict_shape(self):
        rows = wsj.postings_from('Here you go:\n```json\n{"postings": [{"title": "Account Manager", '
                                 '"url": "https://a.com/jobs/123", "extra": 1}, {"title": ""}, "x"]}\n```')
        self.assertEqual(rows, [{"title": "Account Manager", "company": "", "url": "https://a.com/jobs/123",
                                 "location": "", "found_on": ""}])


# ---- nothing a model says counts until the page holds up ------------------------

def page(title="Account Manager", *, org="Acme", country="US", locality="Chicago", region="IL",
         extra="", through=""):
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": title,
          "hiringOrganization": {"name": org},
          "jobLocation": {"address": {"addressLocality": locality, "addressRegion": region,
                                      "addressCountry": country}}}
    if through:
        ld["validThrough"] = through
    return (f"<html><head><title>{title}</title><script type='application/ld+json'>{json.dumps(ld)}"
            f"</script></head><body>{extra}Apply now</body></html>")


class OnlyWhatHoldsUp(unittest.TestCase):
    def check(self, url, response=None, title="Account Manager", location="", country="United States",
              known=None, raises=None):
        fetched = []

        def fetch(u):
            fetched.append(u)
            if raises:
                raise raises
            return response
        job, why = wsj.check_posting({"title": title, "company": "Acme", "url": url, "location": location,
                                      "found_on": "company careers page"},
                                     [jobs._terms(r) for r in ROLES], country=country, known=known,
                                     fetch=fetch)
        self.fetched = fetched
        return job, why

    def test_a_page_that_404s_is_dropped(self):
        job, why = self.check("https://careers.acme.com/jobs/12345", (404, "https://careers.acme.com/jobs/12345", ""))
        self.assertIsNone(job)
        self.assertIn("404", why)

    def test_a_page_that_does_not_load_is_dropped_never_trusted(self):
        job, why = self.check("https://careers.acme.com/jobs/12345", raises=TimeoutError())
        self.assertIsNone(job)
        self.assertIn("did not load", why)

    def test_a_careers_home_page_is_not_a_posting(self):
        job, why = self.check("https://acme.com/careers", (200, "https://acme.com/careers", "<html>Open roles</html>"))
        self.assertIsNone(job)
        self.assertIn("not one job posting", why)

    def test_a_page_declaring_several_jobs_is_a_listing(self):
        two = page() + page("Customer Success Manager")
        job, why = self.check("https://acme.com/jobs/12345", (200, "https://acme.com/jobs/12345", two))
        self.assertIsNone(job)
        self.assertIn("several jobs", why)

    def test_an_aggregator_is_never_even_loaded(self):
        job, why = self.check("https://www.indeed.com/viewjob?jk=abc123", (200, "", page()))
        self.assertIsNone(job)
        self.assertIn("aggregator", why)
        self.assertEqual(self.fetched, [])

    def test_a_title_that_does_not_fit_is_never_loaded(self):
        job, why = self.check("https://acme.com/jobs/12345", (200, "", page()), title="Staff Software Engineer")
        self.assertIsNone(job)
        self.assertEqual(self.fetched, [])

    def test_the_pages_own_title_outranks_the_models(self):
        response = (200, "https://acme.com/jobs/12345", page("Senior Software Engineer"))
        job, why = self.check("https://acme.com/jobs/12345", response)
        self.assertIsNone(job)
        self.assertIn("own title", why)

    def test_a_closed_posting_is_dropped_whatever_the_model_said(self):
        body = page(extra="This position is no longer accepting applications.")
        job, why = self.check("https://acme.com/jobs/12345", (200, "https://acme.com/jobs/12345", body))
        self.assertIsNone(job)
        self.assertIn("no longer open", why)

    def test_a_closing_date_in_the_past_is_dropped(self):
        body = page(through="2020-01-01T00:00:00Z")
        job, why = self.check("https://acme.com/jobs/12345", (200, "https://acme.com/jobs/12345", body))
        self.assertIsNone(job)

    def test_abroad_is_dropped(self):
        job, why = self.check("https://acme.com/jobs/12345", (200, "https://acme.com/jobs/12345",
                                                              page(country="IE", locality="Dublin", region="")))
        self.assertIsNone(job)
        job, why = self.check("https://acme.com/jobs/9", (200, "", page()), location="London, UK")
        self.assertIsNone(job)
        self.assertIn("country", why)

    def test_a_bot_check_is_dropped(self):
        body = "<html><head><title>Just a moment...</title></head></html>"
        job, why = self.check("https://acme.com/jobs/12345", (403, "https://acme.com/jobs/12345", body))
        self.assertIsNone(job)
        self.assertIn("bot check", why)

    def test_an_ats_job_that_redirects_to_its_board_has_closed(self):
        url = "https://job-boards.greenhouse.io/acme/jobs/4001234"
        job, why = self.check(url, (200, "https://job-boards.greenhouse.io/acme?error=true", "<html></html>"))
        self.assertIsNone(job)
        self.assertIn("closed", why)

    def test_a_real_ats_posting_becomes_its_public_form(self):
        url = "https://jobs.lever.co/acme/00000000-0000-4000-8000-000000000001"
        job, why = self.check(url, (200, url, "<html>Account Manager</html>"))
        self.assertEqual(why, "")
        self.assertEqual(job["apply_url"], url + "/apply")
        self.assertEqual((job["provider"], job["board"], job["direct"]), ("lever", "acme", True))
        self.assertEqual(job["found_by"], "ai web search")

    def test_a_workday_posting_is_kept_for_the_account_path(self):
        url = "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Chicago-IL/Account-Manager_R12345"
        job, why = self.check(url, (200, url, "<html><div id='root'></div></html>"))
        self.assertEqual(why, "")
        self.assertTrue(job["needs_account"])
        self.assertFalse(job["direct"])
        self.assertIn("needs an account", job["found_where"])

    def test_an_employers_own_posting_takes_the_pages_facts(self):
        url = "https://careers.acme.com/job/account-manager-chicago-4471"
        job, why = self.check(url, (200, url, page("Account Manager, Midwest", org="Acme Corp")))
        self.assertEqual(why, "")
        self.assertEqual((job["title"], job["company"], job["location"]),
                         ("Account Manager, Midwest", "Acme Corp", "Chicago, IL"))
        self.assertEqual(job["provider"], "company site")

    def test_work_he_will_not_do_is_dropped(self):
        known = {"work_not_wanted": "definitely don't wanna do sales, no cold calling"}
        job, why = self.check("https://acme.com/jobs/12345", (200, "", page("Account Executive")),
                              title="Account Executive", known=known)
        # Account Executive does not fit these roles in the first place; either
        # way it is never loaded and never kept.
        self.assertIsNone(job)

    def test_the_address_shapes(self):
        one = ("https://acme.icims.com/jobs/12345/account-manager/job",
               "https://acme.taleo.net/careersection/2/jobdetail.ftl?job=240001",
               "https://acme.com/careers/job?gh_jid=4455667",
               "https://acme.wd1.myworkdayjobs.com/Careers/job/Remote/Customer-Success-Manager_JR-0042")
        many = ("https://acme.com/careers", "https://acme.com/careers/search?q=account",
                "https://acme.wd1.myworkdayjobs.com/Careers", "https://acme.com/jobs/sales")
        for url in one:
            self.assertTrue(wsj.looks_like_one_posting(url), url)
        for url in many:
            self.assertFalse(wsj.looks_like_one_posting(url), url)


class ValidateAndReport(Isolated):
    def test_openings_report_what_was_dropped_and_the_boards_revealed(self):
        named = [
            {"title": "Account Manager", "company": "Acme", "url": "https://jobs.lever.co/acme/"
             "00000000-0000-4000-8000-000000000001", "location": "Remote, US", "found_on": "Lever"},
            {"title": "Account Manager", "company": "Gone", "url": "https://gone.com/jobs/1234",
             "location": "", "found_on": "careers page"},
            {"title": "Account Manager", "company": "Dup", "url": "https://gone.com/jobs/1234",
             "location": "", "found_on": ""},
            {"title": "Account Manager", "company": "LI", "url": "https://www.linkedin.com/jobs/view/1",
             "location": "", "found_on": ""},
        ]

        def fetch(url):
            if "gone.com" in url:
                return 404, url, ""
            return 200, url, "<html>Account Manager</html>"
        report = {}
        found = wsj.openings(ROLES, limit=10, country="United States", known={},
                             finder=lambda roles, **kw: named, fetch=fetch, report=report)
        self.assertEqual([j["company"] for j in found], ["Acme"])
        self.assertEqual(len(report["dropped"]), 2)
        self.assertEqual(report["boards_revealed"], [("lever", "acme")])

    def test_openings_never_raises(self):
        def finder(roles, **kw):
            raise RuntimeError("boom")
        report = {}
        self.assertEqual(wsj.openings(ROLES, known={}, finder=finder, report=report), [])
        self.assertIn("boom", report["stopped"])


# ---- wired into the search, without starving anything ---------------------------

class SharesTheSlots(Isolated):
    def search(self, *, companies=6, anywhere=6, websearch=None, rows=12, limit=9):
        board_rows = [{"title": "Account Manager", "company": f"Board{i}", "location": "",
                       "apply_url": f"https://board/{i}"} for i in range(rows)]
        own = [{"title": "Account Manager", "company": f"Own{i}", "location": "",
                "apply_url": f"https://own/{i}", "found_by": "company site", "direct": False}
               for i in range(companies)]
        ai = [{"title": "Account Manager", "company": f"Web{i}", "location": "",
               "apply_url": f"https://web/{i}", "found_by": "ai web search", "direct": False}
              for i in range(anywhere)]
        with mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            return jobs.search_many(["Account Manager"], fetcher=lambda b: board_rows, limit=limit,
                                    discover=True, http=lambda q: {"links": []},
                                    companies=lambda roles, **kw: own,
                                    websearch=websearch or (lambda roles, **kw: ai))

    @staticmethod
    def kinds(out):
        return [j.get("found_by") or "board" for j in out["matches"]]

    def test_the_boards_keep_two_slots_in_three(self):
        out = self.search(limit=9)
        self.assertEqual(self.kinds(out).count("board"), 6)
        self.assertIn("ai web search", self.kinds(out))
        self.assertIn("company site", self.kinds(out))
        self.assertEqual(out["web_searched"], self.kinds(out).count("ai web search"))

    def test_a_flood_from_the_search_does_not_starve_the_employers_sites(self):
        out = self.search(companies=10, anywhere=40, limit=30)
        kinds = self.kinds(out)
        self.assertEqual(kinds.count("board"), 12, "every board opening still gets a slot")
        self.assertGreaterEqual(kinds.count("company site"), 4)
        self.assertLessEqual(abs(kinds.count("company site") - kinds.count("ai web search")), 1)

    def test_nothing_from_the_search_leaves_the_rest_as_it_was(self):
        out = self.search(anywhere=0, limit=9)
        self.assertEqual(self.kinds(out)[:3], ["board", "board", "company site"])

    def test_a_search_that_raises_costs_only_itself(self):
        def boom(roles, **kw):
            raise RuntimeError("claude exploded")
        out = self.search(websearch=boom, limit=9)
        self.assertEqual(self.kinds(out).count("board"), 6)
        self.assertEqual(self.kinds(out).count("company site"), 3)

    def test_a_duplicate_of_a_board_job_is_not_offered_twice(self):
        dup = [{"title": "Account Manager", "company": "Board0", "location": "",
                "apply_url": "https://board/0", "found_by": "ai web search"}]
        out = self.search(websearch=lambda roles, **kw: dup, limit=20)
        urls = [j["apply_url"] for j in out["matches"]]
        self.assertEqual(len(urls), len(set(urls)))

    def test_a_test_search_never_reaches_the_real_search_tools(self):
        with mock.patch.object(jobs, "_web_search_openings", side_effect=AssertionError("claude")), \
             mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            jobs.search_many(["Account Manager"], limit=5, discover=True, fetcher=lambda b: [],
                             http=lambda q: {"links": []}, companies=lambda roles, **kw: [])

    def test_a_real_search_asks_the_real_finder(self):
        with mock.patch.object(jobs, "_gather", return_value=([], [], 0)), \
             mock.patch.object(jobs, "_company_openings", return_value=[]), \
             mock.patch.object(jobs, "discover_openings", return_value=[]), \
             mock.patch.object(wsj, "openings", return_value=[]) as real:
            jobs.search_many(["Account Manager"], limit=5, discover=True, country="United States")
        self.assertEqual(real.call_args.kwargs["country"], "United States")


if __name__ == "__main__":
    unittest.main()
