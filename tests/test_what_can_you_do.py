"""The first question anybody asks, answered with a spreadsheet.

    "104 things are live, 17 experimental, 7 waiting on setup and 2 not
     built yet."

Every number true. Nobody has ever wanted to know how many capabilities
something has. He turned her on, asked the first question anybody asks,
and got an inventory report.
"""
import unittest
from unittest import mock

from aletheia import intercom, quick


class SheNamesThemCase(unittest.TestCase):
    def setUp(self):
        quick.warm()

    def test_she_says_what_she_can_do_not_how_many(self):
        said = quick.answer("what can you do")
        self.assertIsNotNone(said)
        self.assertNotIn("things are live", said)
        # a person's words, not a status vocabulary
        for jargon in ("AVAILABLE", "EXPERIMENTAL", "NEEDS_CONFIGURATION",
                       "capabilit", "registry", "_"):
            self.assertNotIn(jargon, said, said)

    def test_she_names_a_few_rather_than_everything(self):
        """Read out loud, a list of everything is a list of nothing."""
        said = quick.answer("what can you do")
        self.assertLessEqual(said.count(","), quick.SPOKEN_GROUPS + 1, said)

    def test_she_speaks_in_the_first_person(self):
        """A first draft said "workers SHE can put on something"."""
        said = quick.answer("what can you do").lower()
        for third_person in (" she ", " her ", "aletheia can"):
            self.assertNotIn(third_person, said, said)

    def test_an_unreadable_registry_says_nothing_rather_than_guessing(self):
        from aletheia import capabilities
        with mock.patch.object(capabilities, "load_registry",
                               side_effect=OSError("gone")):
            self.assertIsNone(quick.answer("what can you do"))


class TheGroupingCannotGoStaleCase(unittest.TestCase):
    """The list is hand-kept, for the reason `test_every_writer_has_a_reader`
    gives about its own: a mechanical grouping would have to guess which
    verbs belong together, and a wrong guess reads fluently while being
    wrong. So the test is that nothing is MISSING."""

    def test_every_kind_is_grouped_or_deliberately_internal(self):
        grouped = {k for kinds in quick._HE_CAN_ASK_FOR.values() for k in kinds}
        unaccounted = (set(intercom.KIND_ARGS)
                       - grouped - quick._NOT_A_THING_HE_ASKS_FOR)
        self.assertEqual(
            unaccounted, set(),
            "a verb he can say that 'what can you do' never mentions — "
            "add it to a group, or to the internal list if he cannot ask for it")

    def test_nothing_is_grouped_that_is_not_a_real_kind(self):
        grouped = {k for kinds in quick._HE_CAN_ASK_FOR.values() for k in kinds}
        self.assertEqual(grouped - set(intercom.KIND_ARGS), set(),
                         "named a verb the grammar does not have")

    def test_the_internal_list_is_only_real_kinds_too(self):
        self.assertEqual(quick._NOT_A_THING_HE_ASKS_FOR - set(intercom.KIND_ARGS),
                         set())


if __name__ == "__main__":
    unittest.main()
