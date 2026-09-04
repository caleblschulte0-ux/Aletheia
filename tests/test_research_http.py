"""Search over plain HTTP: the challenge page is for the browser.

2026-09-04, hours before the operator's first real use: "how much is a
2019 Civic worth" answered "I don't have reliable pricing data — the
sources are Wikipedia articles about the Accord", because every engine the
headless browser visited served a challenge or an unrendered shell. One
ordinary HTTP request to Bing's RSS endpoint returned KBB and Edmunds. This
file holds that: the parsers, the order, and that a refusal costs one
attempt rather than the question. Nothing here touches the network.
"""
from __future__ import annotations

import io
import unittest
from unittest import mock

from aletheia import research

RSS = """<?xml version="1.0"?><rss><channel><title>q - Bing</title>
<item><title>2019 Honda Civic Values &amp; Cars for Sale | KBB</title>
<link>https://www.kbb.com/honda/civic/2019/</link>
<description><![CDATA[Get the <b>value</b> of a 2019 Civic.]]></description></item>
<item><title>2019 Honda Civic Appraisal | Edmunds</title>
<link>https://www.edmunds.com/honda/civic/2019/appraisal-value/</link>
<description>Trade-in and private party values.</description></item>
<item><title>Images</title><link>/images/search?q=x</link><description></description></item>
</channel></rss>"""

DDG = """<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.kbb.com%2Fhonda%2Fcivic%2F2019%2F&amp;rut=abc">2019 Honda <b>Civic</b> Values</a>
<a class="result__snippet" href="x">Get the value of a 2019 Civic.</a></div>
<div class="result"><a class="result__a" href="https://www.carmax.com/value/honda/civic/2019">CarMax</a>
<a class="result__snippet" href="y">Instant offer.</a></div>"""

CHALLENGE = "<html><body>select all squares containing a duck</body></html>"


class _Resp(io.BytesIO):
    def __init__(self, body: str, status: int = 200):
        super().__init__(body.encode("utf-8"))
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener_for(answers: dict):
    """answers: substring of URL -> (status, body) or Exception."""
    calls = []

    def open_(req, timeout=None):
        url = req.full_url
        calls.append(url)
        for key, answer in answers.items():
            if key in url:
                if isinstance(answer, Exception):
                    raise answer
                status, body = answer
                return _Resp(body, status)
        raise AssertionError(f"unexpected fetch {url}")
    open_.calls = calls
    return open_


class ParsersCase(unittest.TestCase):
    def test_bing_rss_gives_titles_links_and_snippets_and_drops_relative_links(self):
        links = research._parse_bing_rss(RSS)
        self.assertEqual([l["href"] for l in links],
                         ["https://www.kbb.com/honda/civic/2019/",
                          "https://www.edmunds.com/honda/civic/2019/appraisal-value/"])
        self.assertEqual(links[0]["text"], "2019 Honda Civic Values & Cars for Sale | KBB")
        self.assertEqual(links[0]["snippet"], "Get the value of a 2019 Civic.")

    def test_ddg_html_unwraps_the_redirect_and_keeps_snippets(self):
        links = research._parse_ddg_html(DDG)
        self.assertEqual(len(links), 2)
        self.assertTrue(links[0]["href"].startswith("https://duckduckgo.com/l/?uddg="))
        self.assertEqual(research._unwrap(links[0]["href"]), "https://www.kbb.com/honda/civic/2019/")
        self.assertEqual(links[0]["text"], "2019 Honda Civic Values")
        self.assertEqual(links[1]["snippet"], "Instant offer.")

    def test_a_challenge_page_parses_to_nothing(self):
        self.assertEqual(research._parse_ddg_html(CHALLENGE), [])
        self.assertEqual(research._parse_bing_rss(CHALLENGE), [])


class OrderCase(unittest.TestCase):
    def test_bing_rss_is_tried_first_and_wins(self):
        open_ = opener_for({"format=rss": (200, RSS), "duckduckgo": (200, DDG)})
        page = research.http_search("2019 civic value", opener=open_)
        self.assertEqual(page["engine"], "bing-rss")
        self.assertEqual(len(open_.calls), 1)
        self.assertIn("KBB", page["text"])

    def test_when_bing_refuses_duckduckgo_is_tried(self):
        open_ = opener_for({"format=rss": (200, "<rss><channel></channel></rss>"),
                            "duckduckgo": (200, DDG)})
        page = research.http_search("q", opener=open_)
        self.assertEqual(page["engine"], "duckduckgo-html")
        self.assertEqual(len(open_.calls), 2)

    def test_a_challenge_status_is_not_a_result(self):
        open_ = opener_for({"format=rss": OSError("refused"),
                            "duckduckgo": (202, CHALLENGE)})
        page = research.http_search("q", opener=open_)
        self.assertEqual(page["links"], [])
        self.assertIn("duckduckgo-html: HTTP 202", page["error"])

    def test_nothing_raises_out_of_http_search(self):
        open_ = opener_for({"format=rss": OSError("no network"),
                            "duckduckgo": OSError("no network")})
        page = research.http_search("q", opener=open_)
        self.assertEqual(page["links"], [])
        self.assertIn("OSError", page["error"])


class FindSourcesCase(unittest.TestCase):
    def test_http_results_are_used_and_the_browser_is_never_driven(self):
        driven = []
        page = {"url": "x", "title": "bing-rss results",
                "text": "2019 Honda Civic Values — Get the value. " * 20,
                "links": research._parse_bing_rss(RSS), "engine": "bing-rss"}
        found = research.find_sources("q", reader=lambda u: driven.append(u) or {},
                                      http=lambda q: page)
        self.assertEqual([s["url"] for s in found][:2],
                         ["https://www.kbb.com/honda/civic/2019/",
                          "https://www.edmunds.com/honda/civic/2019/appraisal-value/"])
        self.assertEqual(driven, [])

    def test_an_empty_http_answer_falls_through_to_the_driven_engines(self):
        driven = []

        def reader(url):
            driven.append(url)
            return {"url": url, "title": "t", "text": "x" * 600,
                    "links": [{"href": "https://example.org/a", "text": "A"}]}
        with mock.patch.object(research.journal, "append"):
            found = research.find_sources(
                "q", reader=reader, http=lambda q: {"links": [], "text": "", "error": "bing-rss: HTTP 500"})
        self.assertTrue(driven)
        self.assertEqual(found[0]["url"], "https://example.org/a")

    def test_http_none_means_driven_engines_only(self):
        driven = []
        research.find_sources("q", reader=lambda u: driven.append(u) or {"text": "", "links": []},
                              http=None)
        self.assertTrue(driven)


if __name__ == "__main__":
    unittest.main()
