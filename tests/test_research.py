"""Research answers with sources, or it does not answer.

The second mission kind. The thing that separates it from asking a model
the same question is that every claim carries the page it came from and a
claim with no source does not survive — so that is what these test, along
with the ways a research run can fail without taking the whole thing down.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import documents, journal, notifications, policy, research


PAGES = {
    "https://duckduckgo.com/html/?q=q1": {
        "url": "https://duckduckgo.com/html/?q=q1", "title": "results", "text": "x" * 500,
        "links": [
            {"text": "Ad", "href": "https://duckduckgo.com/y.js?ad=1"},
            {"text": "Real one", "href": "https://example.org/a"},
            {"text": "Same site again", "href": "https://example.org/b"},
            {"text": "Second site", "href": "https://other.test/c"},
            {"text": "Video", "href": "https://www.youtube.com/watch?v=1"},
        ],
    },
    "https://example.org/a": {
        "url": "https://example.org/a", "title": "Primary source",
        "text": "The answer is forty two. " * 40, "links": [],
    },
    "https://other.test/c": {
        "url": "https://other.test/c", "title": "Second source",
        "text": "Independently, forty two. " * 40, "links": [],
    },
}


def reader(url, *a, **k):
    if url.startswith("https://duckduckgo.com/html/"):
        return PAGES["https://duckduckgo.com/html/?q=q1"]
    if url in PAGES:
        return PAGES[url]
    raise RuntimeError("unreachable")


class ResearchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "journal.jsonl"),
                (policy, "HALT_PATH", d / "halt.json"),
                (documents, "DOCS_DIR", d / "documents"),
                (notifications, "NOTICES_DIR", d / "notices")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)

    def think(self, findings=None, **overrides):
        """A stand-in for the model: plan first, then report."""
        report = {
            "answer": "Forty two.",
            "findings": findings if findings is not None else [
                {"claim": "It is forty two", "url": "https://example.org/a"}],
            "gaps": [], "confidence": 0.8,
        }
        report.update(overrides)
        calls = iter([{"queries": ["q1"], "why": "direct"}, report])

        def fake(system, text, **kwargs):
            value = next(calls)
            validator = kwargs.get("validator")
            return validator(value) if validator else value
        return fake


class ItAnswersWithSources(ResearchCase):
    def test_a_run_produces_sourced_findings(self):
        report = research.run("what is the answer", reader=reader,
                              think=self.think())
        self.assertEqual(report["answer"], "Forty two.")
        self.assertEqual(len(report["findings"]), 1)
        self.assertIn("example.org", report["findings"][0]["url"])
        self.assertTrue(report["sources"])

    def test_one_page_per_site(self):
        """Five views of one outlet is one source wearing five hats."""
        report = research.run("q", reader=reader, think=self.think())
        hosts = [research._host(s["url"]) for s in report["sources"]]
        self.assertEqual(len(hosts), len(set(hosts)))

    def test_search_engines_and_video_sites_are_not_read_as_sources(self):
        report = research.run("q", reader=reader, think=self.think())
        for source in report["sources"]:
            self.assertNotIn(research._host(source["url"]), research.SKIP_HOSTS)

    def test_the_report_is_stored_and_he_is_told(self):
        research.run("what is the answer", reader=reader, think=self.think())
        self.assertTrue(documents.search("forty two") or documents.search("answer"),
                        "an answer that exists only in a log is one he never gets")
        self.assertTrue(list(notifications.NOTICES_DIR.glob("*.json")))


class AnInventedCitationDoesNotSurvive(ResearchCase):
    """The line between research and a plausible paragraph. Enforced in code
    because a model that invents a citation is not caught by asking it not to."""

    def test_a_finding_citing_an_unread_page_is_dropped(self):
        report = research.run("q", reader=reader, think=self.think(findings=[
            {"claim": "real", "url": "https://example.org/a"},
            {"claim": "invented", "url": "https://nowhere.invalid/made-up"},
        ]))
        urls = [f["url"] for f in report["findings"]]
        self.assertIn("https://example.org/a", urls)
        self.assertNotIn("https://nowhere.invalid/made-up", urls)
        self.assertEqual(report["unsourced_dropped"], 1)

    def test_dropping_is_said_out_loud_not_hidden(self):
        report = research.run("q", reader=reader, think=self.think(findings=[
            {"claim": "invented", "url": "https://nowhere.invalid/x"}]))
        self.assertTrue(any("dropped" in g for g in report["gaps"]),
                        "a silent drop leaves him reading a thinner answer "
                        "with no idea why")

    def test_the_validator_refuses_a_malformed_report(self):
        for bad in ({"answer": "", "findings": [], "gaps": [], "confidence": 0.5},
                    {"answer": "a", "findings": [{"claim": "c"}], "gaps": [],
                     "confidence": 0.5},
                    {"answer": "a", "findings": [], "gaps": [], "confidence": 5},
                    {"answer": "a", "findings": [], "gaps": "no", "confidence": 0.5}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    research._report_validator(bad)


class FailuresAreSurvivableAndHonest(ResearchCase):
    def test_a_broken_search_does_not_end_the_run(self):
        def angry(url, *a, **k):
            if "duckduckgo" in url:
                raise RuntimeError("markup changed")
            return PAGES.get(url, {"url": url, "title": "", "text": "", "links": []})
        self.assertEqual(research.find_sources("q", reader=angry), [],
                         "a search engine changing its markup costs the query, "
                         "not the question")

    def test_an_unreadable_page_is_recorded_rather_than_dropped(self):
        def flaky(url, *a, **k):
            if url == "https://other.test/c":
                raise RuntimeError("403")
            return reader(url)
        report = research.run("q", reader=flaky, think=self.think())
        self.assertTrue(report["unreadable"])
        self.assertEqual(report["unreadable"][0]["reason"], "RuntimeError")

    def test_no_sources_is_an_honest_refusal_not_an_invented_answer(self):
        empty = {"url": "u", "title": "", "text": "", "links": []}
        with self.assertRaises(research.ResearchError):
            research.run("q", reader=lambda *a, **k: empty, think=self.think())

    def test_a_thin_page_is_not_treated_as_a_source(self):
        sources, failed = research.read_sources(
            [{"url": "https://example.org/a"}],
            reader=lambda *a, **k: {"url": "https://example.org/a", "title": "t",
                                    "text": "too short"})
        self.assertEqual(sources, [])
        self.assertEqual(failed[0]["reason"], "no readable text")


class ItReadsNothingItShouldNot(ResearchCase):
    def test_halt_stops_a_run_before_any_page_is_read(self):
        policy.halt("stop", via="test")
        pages = []
        with self.assertRaises(policy.Halted):
            research.run("q", reader=lambda u, *a, **k: pages.append(u) or reader(u),
                         think=self.think())
        self.assertEqual(pages, [], "halted before the browser opened")

    def test_a_question_must_be_bounded(self):
        for bad in ("", "   ", "x" * 5000):
            with self.subTest(bad=bad[:20]):
                with self.assertRaises(ValueError):
                    research.run(bad, reader=reader, think=self.think())

    def test_research_never_interacts_with_a_page(self):
        """It reads. Anything that clicks or types needs an approval and is a
        different capability entirely."""
        source = (Path(__file__).parent.parent / "aletheia" / "research.py"
                  ).read_text(encoding="utf-8")
        for forbidden in ("browse.interact", "browse.screenshot", "errands",
                          "secret_"):
            self.assertNotIn(forbidden, source, forbidden)


class TheRedirectWrapperIsUnwrapped(ResearchCase):
    def test_a_result_redirect_resolves_to_the_real_page(self):
        wrapped = ("https://duckduckgo.com/l/?uddg="
                   "https%3A%2F%2Fexample.org%2Freal&rut=abc")
        self.assertEqual(research._unwrap(wrapped), "https://example.org/real")

    def test_an_ordinary_link_is_untouched(self):
        self.assertEqual(research._unwrap("https://example.org/a"),
                         "https://example.org/a")


if __name__ == "__main__":
    unittest.main()
