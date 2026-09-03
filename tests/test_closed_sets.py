"""An argument with four legal values looked like free text.

The grammar the planner is shown is generated from `intercom.KIND_ARGS`,
which gives argument NAMES and nothing else. So `remember(domain, key,
value, [memory_kind])` told the model that `domain` existed and nothing
about what could go in it — and it filled the gap reasonably and wrongly:
domain "family" (the real ones are identity/preferences/people/
organizations) and memory_kind "fact" (explicit/inferred/temporary).

Both passed `validate_kind_args`, which checked that the ARGUMENT was
allowed and never what was inside it. So the step was marked EXECUTABLE,
survived approval, and died at execution with a bare ValueError.

"Remember my sister is Mia" — the most ordinary sentence an assistant
ever hears — compiled cleanly and did nothing.
"""
import unittest
from unittest import mock

from aletheia import contracts, intercom, memory, planner


class TheValuesComeFromTheCodeThatEnforcesThem(unittest.TestCase):
    """A second copy of an enum in a prompt is a copy that disagrees with
    the validator the day someone adds a value."""

    def test_the_domains_are_memorys_own(self):
        self.assertEqual(intercom.allowed_values("remember", "domain"),
                         sorted(memory.DOMAINS))

    def test_the_kinds_are_memorys_own(self):
        self.assertEqual(intercom.allowed_values("remember", "memory_kind"),
                         sorted(memory.KINDS))

    def test_the_task_states_are_the_contracts_own(self):
        self.assertEqual(intercom.allowed_values("task_status", "state"),
                         sorted(contracts.TASK_STATES))

    def test_adding_a_value_upstream_shows_up_here_with_no_edit(self):
        with mock.patch.object(memory, "DOMAINS", {"identity", "vehicles"}):
            self.assertEqual(intercom.allowed_values("remember", "domain"),
                             ["identity", "vehicles"])

    def test_an_argument_with_no_closed_set_says_so(self):
        self.assertIsNone(intercom.allowed_values("note", "text"))
        self.assertIsNone(intercom.allowed_values("remember", "key"))


class ABadValueIsCaughtBeforeItIsApproved(unittest.TestCase):
    """Where a bad value becomes a refusal the planner can see and repair,
    rather than an exception with an approval already spent on it."""

    def test_the_exact_value_that_broke_it(self):
        problems = intercom.validate_kind_args(
            {"kind": "remember", "domain": "family", "key": "sister",
             "value": "Mia"}, {})
        self.assertTrue(problems)
        self.assertIn("family", problems[0])
        self.assertIn("people", problems[0])

    def test_the_other_exact_value_that_broke_it(self):
        problems = intercom.validate_kind_args(
            {"kind": "remember", "domain": "people", "key": "sister",
             "value": "Mia", "memory_kind": "fact"}, {})
        self.assertTrue(problems)
        self.assertIn("fact", problems[0])

    def test_a_good_command_is_still_clean(self):
        self.assertEqual(intercom.validate_kind_args(
            {"kind": "remember", "domain": "people", "key": "sister",
             "value": "Mia", "memory_kind": "explicit"}, {}), [])

    def test_a_bad_task_state_is_refused_too(self):
        self.assertTrue(intercom.validate_kind_args(
            {"kind": "task_status", "id": "x", "state": "done"}, {}))

    def test_an_omitted_optional_enum_is_not_a_problem(self):
        self.assertEqual(intercom.validate_kind_args(
            {"kind": "remember", "domain": "people", "key": "s",
             "value": "v"}, {}), [])

    def test_the_refusal_names_what_would_have_worked(self):
        """A refusal that does not say the legal values gets guessed at
        again on the retry."""
        problems = intercom.validate_kind_args(
            {"kind": "remember", "domain": "family", "key": "s",
             "value": "v"}, {})
        for domain in sorted(memory.DOMAINS):
            self.assertIn(domain, problems[0])


class ThePlannerIsToldBeforeItGuesses(unittest.TestCase):
    def test_the_grammar_carries_the_closed_sets(self):
        brief = planner.grammar_brief()
        self.assertIn("CLOSED SETS", brief)
        self.assertIn("remember.domain is EXACTLY one of", brief)
        for domain in sorted(memory.DOMAINS):
            self.assertIn(domain, brief)

    def test_it_is_generated_not_written_down(self):
        with mock.patch.object(memory, "KINDS", {"guessed"}):
            self.assertIn("remember.memory_kind is EXACTLY one of: guessed",
                          planner.grammar_brief())

    def test_a_kind_that_left_the_grammar_does_not_linger_in_the_sets(self):
        with mock.patch.dict(intercom.KIND_ARGS, clear=True):
            self.assertNotIn("CLOSED SETS", planner.grammar_brief())

    def test_a_broken_enum_source_thins_the_grammar_rather_than_killing_it(self):
        with mock.patch.object(intercom, "allowed_values", return_value=None):
            self.assertNotIn("CLOSED SETS", planner.grammar_brief())


if __name__ == "__main__":
    unittest.main()
