"""Every rule is compiled once, not once per sentence (2026-10-08).

`voice._interpret` tries more patterns than Python's own `re` cache holds,
so each sentence recompiled hundreds of them - 0.2 s of the two seconds the
room is promised. `aletheia.rx` is `re` with a cache big enough to hold
them, and nothing else.
"""
import re as stdlib_re
import time
import unittest

from aletheia import quick, rx, speech, voice


class RxIsRe(unittest.TestCase):
    def test_same_answers_as_re(self):
        cases = [(r"(\w+) (\w+)", "hello world"), (r"^a.c$", "abc"), (r"x", "yyy")]
        for pattern, text in cases:
            for fn in ("match", "fullmatch", "search", "findall", "split"):
                self.assertEqual(repr(getattr(rx, fn)(pattern, text)), repr(getattr(stdlib_re, fn)(pattern, text)))
        self.assertEqual(rx.sub(r"o", "0", "foo", count=1), stdlib_re.sub(r"o", "0", "foo", count=1))
        self.assertEqual(rx.subn(r"o", "0", "foo"), stdlib_re.subn(r"o", "0", "foo"))
        self.assertTrue(rx.search("ABC", "xabcx", rx.I))
        self.assertIs(rx.compile(r"q+"), rx.compile(r"q+"))
        compiled = stdlib_re.compile("z")
        self.assertEqual(rx.compile(compiled).pattern, "z")

    def test_the_rule_modules_use_it(self):
        for module in (voice, quick, speech):
            self.assertIs(module.re, rx, module.__name__)

    def test_a_sentence_no_rule_owns_is_fast(self):
        voice._interpret("make me a sandwich")
        quick.answer("make me a sandwich")
        started = time.perf_counter()
        for _ in range(5):
            voice._interpret("make me a sandwich")
            quick.answer("make me a sandwich")
        # Each pass was ~0.2 s while every rule was recompiled; generous
        # headroom for a loaded machine.
        self.assertLess((time.perf_counter() - started) / 5, 0.1)


if __name__ == "__main__":
    unittest.main()
