"""A reading goal has a move: answer it from the page in front of her.

Live, 2026-09-18: the loop navigated onto the exact page holding the answer and
stopped with *"nothing on it moves toward the goal without a guess. Tell me
what to press."* Nothing moved toward the goal because nothing needed pressing:
the goal was a question and the answer was on the screen.

Three things have to be true of the fix, and the third is the one that matters:

- the answer is FOUND where the page lays it out, deterministically,
- the page that does NOT hold it says so, in a different sentence,
- and she NEVER guesses: a model answer whose quote is not on the page is
  thrown away whole, however confident it sounded.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import browser_loop, browser_mission as bm, browser_route, page_answer

# A product page's own text, as Chrome's innerText renders the table.
BOOK_PAGE = """A Light in the Attic
Home Books Poetry A Light in the Attic
£51.77
In stock (22 available)
Product Description
It's hard to imagine a world without A Light in the Attic.
Product Information
UPC\ta897fe39b1053632
Product Type\tBooks
Price (excl. tax)\t£51.77
Price (incl. tax)\t£51.77
Tax\t£0.00
Availability\tIn stock (22 available)
Number of reviews\t0
"""

CATALOGUE_PAGE = """All products
A Light in the Attic £51.77 In stock
Tipping the Velvet £53.74 In stock
"""


def obs(text=BOOK_PAGE, url="http://books.toscrape.com/x.html", title="A Light in the Attic"):
    return {"url": url, "title": title, "text": text, "state": "CONTENT"}


class AGoalThatIsAQuestion(unittest.TestCase):
    def test_the_question_shapes(self):
        for goal in ("what is the price of A Light in the Attic",
                     "how many are in stock",
                     "what's the UPC?",
                     "is it in stock",
                     "tell me what the price is",
                     "How much does it cost"):
            self.assertTrue(page_answer.is_a_question(goal), goal)

    def test_an_instruction_is_not_a_question(self):
        for goal in ("add the book to the basket",
                     "apply for the warehouse job at Acme",
                     "sign up for the newsletter",
                     "open the product page for A Light in the Attic"):
            self.assertFalse(page_answer.is_a_question(goal), goal)

    def test_nothing_at_all_is_not_a_question(self):
        self.assertFalse(page_answer.is_a_question(""))
        self.assertFalse(page_answer.is_a_question(None))


class ThePageLaysItOut(unittest.TestCase):
    """Deterministic: no model, nothing to hallucinate."""

    def test_the_answer_is_read_out_of_the_table(self):
        found = page_answer.from_page("what is the UPC", BOOK_PAGE)
        self.assertEqual(found["answer"], "a897fe39b1053632")
        self.assertEqual(found["found_by"], "the page's own words")
        self.assertIn("UPC", found["quote"])

    def test_the_tighter_label_wins_so_two_prices_are_not_confused(self):
        self.assertEqual(page_answer.from_page("what is the price excluding tax", BOOK_PAGE)["quote"],
                         "Price (excl. tax): £51.77")
        self.assertEqual(page_answer.from_page("what is the price including tax", BOOK_PAGE)["quote"],
                         "Price (incl. tax): £51.77")

    def test_a_label_that_does_not_carry_every_word_of_the_goal_is_not_the_answer(self):
        self.assertIsNone(page_answer.from_page("what is the shipping weight", BOOK_PAGE))

    def test_a_page_with_no_rows_gives_nothing(self):
        self.assertIsNone(page_answer.from_page("what is the UPC", CATALOGUE_PAGE))

    def test_a_sentence_with_a_colon_in_it_is_not_a_row(self):
        text = ("Note: we ship everywhere in the world and we have done so since the very "
                "beginning of this shop, which was quite a long time ago now.\n")
        self.assertEqual(page_answer.pairs(text), [])

    def test_no_model_is_asked_when_the_page_says_it(self):
        from aletheia import reasoning_gateway

        def never(*a, **k):
            raise AssertionError("it asked a model about a page that already said it")

        with mock.patch.object(reasoning_gateway, "reason_json", side_effect=never):
            found = page_answer.answer("what is the UPC", obs())
        self.assertEqual(found["answer"], "a897fe39b1053632")
        self.assertEqual(found["url"], "http://books.toscrape.com/x.html")


class SheNeverGuesses(unittest.TestCase):
    """Everything a model says rides on a quote that is really on the page."""

    def think(self, answer, quote):
        def think(system, text):
            return {"answer": answer, "quote": quote}
        think.provider = "ollama:qwen3:8b"
        return think

    def test_a_quoted_answer_is_kept(self):
        found = page_answer.from_model(
            "how many are available", BOOK_PAGE,
            think=self.think("22", "In stock (22 available)"))
        self.assertEqual(found["answer"], "22")
        self.assertEqual(found["found_by"], "ollama:qwen3:8b")

    def test_an_invented_quote_throws_the_whole_answer_away(self):
        self.assertIsNone(page_answer.from_model(
            "how many are available", BOOK_PAGE,
            think=self.think("40", "In stock (40 available)")))

    def test_an_answer_that_is_not_in_the_words_it_claims_to_have_read_is_dropped(self):
        self.assertIsNone(page_answer.from_model(
            "how many are available", BOOK_PAGE,
            think=self.think("forty", "In stock (22 available)")))

    def test_a_model_that_says_it_is_not_here_is_believed(self):
        self.assertIsNone(page_answer.from_model(
            "who wrote it", BOOK_PAGE, think=self.think("", "")))

    def test_a_model_that_fails_is_not_an_error(self):
        def broken(system, text):
            raise RuntimeError("no")
        self.assertIsNone(page_answer.from_model("what is the UPC", BOOK_PAGE, think=broken))

    def test_a_caller_with_no_model_still_gets_the_deterministic_read(self):
        found = page_answer.answer("what is the UPC", obs(), use_model=False)
        self.assertEqual(found["answer"], "a897fe39b1053632")

    def test_and_asks_no_model_when_it_has_none(self):
        from aletheia import reasoning_gateway
        with mock.patch.object(reasoning_gateway, "reason_json",
                               side_effect=AssertionError("it asked a model it was told it had not got")):
            self.assertIsNone(page_answer.answer("who wrote it", obs(), use_model=False))


class TheLoopFinishesInsteadOfAsking(unittest.TestCase):
    def record(self, goal):
        return {"id": "m-1", "goal": goal, "state": bm.RUNNING, "route": [{"action": "goto"}],
                "checkpoints": [], "start_url": "http://books.toscrape.com/"}

    def test_a_reading_goal_finishes_with_the_answer_and_its_citation(self):
        rec = self.record("what is the UPC of A Light in the Attic")
        found = browser_loop._answer_from(rec["goal"], obs(), decide=None)
        browser_loop._finish_reading(rec, obs(), judged_by=found["found_by"], found=found)
        self.assertEqual(rec["state"], bm.DONE)
        self.assertEqual(rec["result"]["answer"], "a897fe39b1053632")
        self.assertIn("UPC", rec["result"]["quote"])
        self.assertEqual(rec["result"]["url"], "http://books.toscrape.com/x.html")
        self.assertEqual(rec["result"]["found_by"], "the page's own words")

    def test_a_page_that_does_not_answer_it_says_that_and_does_not_ask_what_to_press(self):
        said = browser_loop._say_boundary("NO_ANSWER_ON_THE_PAGE", "http://books.toscrape.com/",
                                          page="a page to read",
                                          question="who wrote A Light in the Attic")
        self.assertIn("does not answer", said)
        self.assertIn("will not guess", said)
        self.assertNotIn("nothing on it moves toward the goal", said)

    def test_an_action_goal_keeps_the_old_boundary(self):
        said = browser_loop._say_boundary("NO_WAY_FORWARD", "http://x/", page="a page to read")
        self.assertIn("Tell me what to press", said)

    def test_reading_a_page_is_never_why_a_mission_crashes(self):
        with mock.patch.object(page_answer, "answer", side_effect=RuntimeError("boom")):
            self.assertEqual(browser_loop._answer_from("what is the UPC", obs(), decide=None), {})

    def test_a_scripted_loop_never_pays_for_a_real_local_call(self):
        """A suite that scripts `decide` must not be charged two minutes a test."""
        from aletheia import reasoning_gateway

        def scripted(*a):
            return {}

        with mock.patch.object(reasoning_gateway, "reason_json",
                               side_effect=AssertionError("the suite paid for a real model call")):
            # The page does not lay this one out, so only a model could answer it.
            self.assertEqual(browser_loop._answer_from("who wrote it", obs(), decide=scripted), {})

    def test_a_scripted_loop_can_script_the_reading_too(self):
        def scripted(*a):
            return {}
        scripted.read = lambda system, text: {"answer": "22", "quote": "In stock (22 available)"}
        scripted.read.provider = "scripted"
        found = browser_loop._answer_from("how many are available", obs(), decide=scripted)
        self.assertEqual(found["answer"], "22")

    def test_the_real_loop_does_reach_the_gateway(self):
        seen = {}

        def reason_json(system, text, **kwargs):
            seen["policy"] = kwargs.get("policy")
            raise ValueError("nothing today")

        from aletheia import reasoning_gateway
        with mock.patch.object(reasoning_gateway, "reason_json", side_effect=reason_json):
            browser_loop._answer_from("who wrote it", obs(), decide=browser_loop.gateway_decide)
        self.assertEqual(seen["policy"], "routine")


class TheAnswerIsWhatSheSays(unittest.TestCase):
    def test_the_room_hears_the_answer_and_where_she_read_it(self):
        rec = {"goal": "what is the UPC", "state": bm.DONE,
               "result": {"answer": "a897fe39b1053632", "quote": "UPC: a897fe39b1053632",
                          "url": "http://books.toscrape.com/x.html", "title": "A Light in the Attic"}}
        said = browser_route.spoken(rec)
        self.assertIn("a897fe39b1053632", said)
        self.assertIn("A Light in the Attic", said)
        self.assertNotIn("The site confirmed it", said)

    def test_nothing_was_submitted_so_nothing_claims_the_site_confirmed_it(self):
        rec = {"goal": "read the page", "state": bm.DONE, "result": {}}
        self.assertNotIn("confirmed", browser_route.spoken(rec))

    def test_a_real_submission_still_says_the_site_confirmed_it(self):
        rec = {"goal": "apply for the job", "state": bm.DONE, "result": {},
               "submits": [{"at": "now"}]}
        self.assertIn("The site confirmed it", browser_route.spoken(rec))

    def test_the_mission_description_carries_it_too(self):
        rec = {"goal": "what is the UPC", "state": bm.DONE,
               "result": {"answer": "a897fe39b1053632", "quote": "UPC: a897fe39b1053632",
                          "url": "http://x/", "title": "A Light in the Attic"}}
        self.assertIn("a897fe39b1053632", bm.describe(rec))

    def test_a_result_with_no_answer_says_nothing_rather_than_something_empty(self):
        self.assertEqual(page_answer.spoken({}), "")
        self.assertEqual(page_answer.spoken({"answer": "   "}), "")


if __name__ == "__main__":
    unittest.main()
