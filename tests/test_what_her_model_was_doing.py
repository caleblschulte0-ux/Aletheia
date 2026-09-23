"""The local-run ring and the busy mark kept the prompt's first 80
characters as "what she was doing", and for the resume-learning call that
was his name, address, phone and email - shown on his own screen under
"what my own model is doing" (2026-09-23). Personal text is said as what
it is: a document of his."""
from __future__ import annotations

import unittest

from aletheia import local_model_pool as pool


class WhatSheWasDoingCase(unittest.TestCase):
    def test_personal_text_is_named_not_quoted(self):
        said = pool._what_words("CALEB SCHULTE Hartford, SD 57033 | (605) 321-5691 | Caleblschulte0@gmail.com PRO")
        self.assertEqual(said, "reading a document of his")
        self.assertEqual(pool._what_words("john@example.com asked about the invoice"), "reading a document of his")

    def test_a_question_stays_a_question(self):
        self.assertEqual(pool._what_words("What, if anything, would help this opportunity?"),
                         "What, if anything, would help this opportunity?")
        self.assertEqual(len(pool._what_words("x " * 200)), 80)


if __name__ == "__main__":
    unittest.main()
