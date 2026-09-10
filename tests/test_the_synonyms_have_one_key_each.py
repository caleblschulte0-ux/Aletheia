"""A duplicate key in a dict literal is silent, and Python keeps the last.

`intercom.KIND_ARGS` is already held against exactly this
(`test_every_kind_has_a_handler`), because the grammar decides what may
be relayed and a silently-dropped key there is a hole. `SYNONYMS` decides
WHICH CAPABILITY SHE CLAIMS TO HAVE, which is the same size of hole, and
nothing was watching it.

Found by writing one:

    "search": ("find", "search", "file"),      # mine, dropped in silence
    ...
    "search": ("research", "browser", "journal"),

so "can you search my computer for a file" answered `journal.search`.
Every word of that answer is true about the journal, and he asked about
his disk.

The other rule here is the same shape and cost the same half hour:
`_query_terms` looks synonyms up AFTER `_words` has folded the plural, so
a key written as "downloads" is never reached at all. Keys are stems.
"""
from __future__ import annotations

import ast
import collections
import inspect
import unittest

from aletheia import self_knowledge as sk


def _literal_keys(module, name: str) -> list[str]:
    """The keys AS WRITTEN, which is the only place a duplicate is visible.

    Reading `module.NAME.keys()` cannot find this: by then Python has
    already collapsed the duplicate and thrown the first one away.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and getattr(node.targets[0], "id", "") == name):
            return [k.value for k in node.value.keys]
    raise AssertionError(f"{name} is not a dict literal any more")


class OneKeyEachCase(unittest.TestCase):
    def test_no_synonym_is_written_twice(self):
        keys = _literal_keys(sk, "SYNONYMS")
        counted = collections.Counter(keys)
        dupes = sorted(k for k, n in counted.items() if n > 1)
        self.assertEqual(dupes, [], f"silently dropped: {dupes}")

    def test_every_key_survives_stemming(self):
        """A key that stems to something else is never looked up."""
        for key in _literal_keys(sk, "SYNONYMS"):
            with self.subTest(key=key):
                self.assertEqual(sk._stem(key), key,
                                 f"{key!r} is only reachable as "
                                 f"{sk._stem(key)!r}")

    def test_a_key_is_not_a_stop_word(self):
        """`_query_terms` drops stop words before it ever looks here."""
        for key in _literal_keys(sk, "SYNONYMS"):
            with self.subTest(key=key):
                self.assertNotIn(key, sk.STOP)
                self.assertGreaterEqual(len(key), 3)


class WhatTheDuplicateCostCase(unittest.TestCase):
    def test_searching_his_computer_is_not_searching_her_journal(self):
        found = sk.relevant("can you search my computer for a file")
        self.assertTrue(found)
        self.assertTrue(found[0]["capability"].startswith(("file", "document")),
                        f"answered about {found[0]['capability']}")

    def test_searching_her_journal_still_is(self):
        """The fix must not simply move the error."""
        found = sk.relevant("can you search your journal")
        self.assertTrue(found[0]["capability"].startswith("journal"))

    def test_a_plural_he_says_reaches_its_synonym(self):
        """"downloads" is looked up after the plural is folded."""
        self.assertIn("find", sk._query_terms("what's in my downloads"))


if __name__ == "__main__":
    unittest.main()
