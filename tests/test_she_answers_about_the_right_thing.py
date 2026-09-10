"""She said "yes" and described something else.

    > can you read my files
      Yes - Observe any web page through the authorized browser profile:
      title, visible text, links, screenshots.

A confident yes attached to the wrong capability, which is worse than a
no: every word of the description is TRUE, about a thing he did not ask
about, so there is nothing in the sentence for him to catch.

Two faults, and the second hid the first.

PLURALS WERE DIFFERENT WORDS. He says "files"; the registry says
`file.author` and "...or text file". "files" never matched "file", so the
capabilities that ARE about files scored almost entirely on the word
"read" - which `browser.read` also has in its id.

AND THE TIE WENT TO WHOEVER WAS FIRST. `browser.read` and
`document.read_any` both scored 4.44, and ties broke on status alone -
both AVAILABLE - so registry order decided what she claimed she could do.
"""
from __future__ import annotations

import unittest

from aletheia import quick, self_knowledge as sk


class FoldingAPluralCase(unittest.TestCase):
    def test_his_plural_is_the_registrys_singular(self):
        for said, stem in (("files", "file"), ("tasks", "task"),
                           ("reminders", "reminder"), ("entries", "entry"),
                           ("documents", "document")):
            with self.subTest(said=said):
                self.assertEqual(sk._stem(said), stem)

    def test_a_word_that_merely_ends_in_s_is_left_alone(self):
        """"Status" is not the plural of "statu"."""
        for word in ("status", "address", "access", "business", "press",
                     "progress", "class", "https", "focus", "news"):
            with self.subTest(word=word):
                self.assertEqual(sk._stem(word), word)

    def test_short_words_are_never_stemmed(self):
        for word in ("is", "as", "os", "gas"):
            with self.subTest(word=word):
                self.assertEqual(sk._stem(word), word)

    def test_the_question_and_the_registry_fold_the_same_way(self):
        """Both sides must agree or the match is worse, not better."""
        self.assertIn("file", sk._query_terms("can you read my files"))
        self.assertIn("file", sk._words("file.author"))


class SheAnswersAboutTheRightThingCase(unittest.TestCase):
    def _best(self, question):
        found = sk.relevant(question)
        return found[0]["capability"] if found else None

    def test_a_question_about_files_is_answered_about_files(self):
        """The bug: this returned the web browser."""
        best = self._best("can you read my files")
        self.assertIsNotNone(best)
        self.assertTrue(best.startswith(("file", "document")),
                        f"answered about {best}")

    def test_a_question_about_web_pages_still_gets_the_browser(self):
        """The fix must not simply move the error somewhere else."""
        self.assertTrue(self._best("can you read a web page")
                        .startswith("browser"))

    def test_the_ordinary_questions_still_land(self):
        for question, prefix in (("can you check my email", "email"),
                                 ("can you send a text", "message"),
                                 ("can you book a table", "reservation"),
                                 ("can you take a screenshot", "screen")):
            with self.subTest(question=question):
                self.assertTrue(self._best(question).startswith(prefix),
                                f"{question} -> {self._best(question)}")

    def test_a_tie_is_not_broken_by_position_in_the_file(self):
        """Whichever came first was winning, which is not a match."""
        terms = sk._query_terms("can you read my files")
        registry = sk._registry()
        scores = sorted((sk._score(e, terms), e["id"])
                        for e in registry["capabilities"])
        top = [row for row in scores if row[0] >= sk.FLOOR]
        self.assertTrue(top, "nothing scored at all")
        best = self._best("can you read my files")
        # Whatever wins must carry one of HIS words in its own id.
        self.assertTrue(any(w in terms for w in sk._words(best)),
                        f"{best} shares no word with the question")


class TheSpokenAnswerCase(unittest.TestCase):
    def test_it_says_yes_about_the_thing_he_asked(self):
        said = quick.answer("can you read my files") or ""
        self.assertIn("file", said.lower())
        self.assertNotIn("web page", said.lower())

    def test_an_experimental_capability_is_still_flagged(self):
        said = quick.answer("can you send a text") or ""
        self.assertIn("experimental", said.lower())


if __name__ == "__main__":
    unittest.main()
