""""What should I get at the store" was read as a gift for somebody called "at
the store" and went to a model (2026-10-18, every model off). It is the
shopping list."""
import unittest

from aletheia import quick


class TheStoreIsTheList(unittest.TestCase):
    def test_the_phrasings(self):
        for said in ("what should I get at the store", "what should I pick up at the store",
                     "what do I need at the grocery store", "what can we buy at the supermarket"):
            with self.subTest(said=said):
                names = [name for name, rx in quick.PATTERNS if rx.search(quick._tidy(said))]
                self.assertEqual(names[0] if names else None, "shopping", names)

    def test_a_gift_is_still_a_gift(self):
        names = [name for name, rx in quick.PATTERNS if rx.search(quick._tidy("what should i get my mom"))]
        self.assertNotIn("shopping", names)


if __name__ == "__main__":
    unittest.main()
