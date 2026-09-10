"""The one permanent rule, in the answer as well as at the door.

    > can you buy me a monitor
      Yes - Private requirements/candidates/selection workflow ending in
      an approval-bounded purchase proposal.

Every INSTRUCTION form is refused at the door in half a second and always
was — "buy me a monitor", "order me a pizza", "go ahead and buy the
monitor", and the one the door was built for, "my wife says it's fine to
buy the monitor so do it". That gate is intact and this changes none of
it.

This is the QUESTION form, which is answerable and must stay answerable:
"can you buy things" is a fair question and refusing it would be theatre.
But a bare "Yes" invites the next sentence, which is "okay, do it", which
is then refused — so the yes overstates what she will do. That is the
same defect as an offer she cannot keep, pointing the other way.

Said with the SAME PREDICATE the three gates share, so the sentence he
hears and the thing that happens cannot disagree.

AND THE REGISTRY WAS THE LAST PLACE STILL SAYING OTHERWISE.
`purchase.execute` sat at EXPERIMENTAL — "Yes, but it is experimental:
Execute an actual purchase with money" — while its own notes recorded
that spending errands are REFUSED AT RUN TIME until a two-phase checkout
verifier exists, and that no spending errand had ever run live. A
capability refused unconditionally is not experimental; EXPERIMENTAL
reads as "nearly, if you are brave".
"""
from __future__ import annotations

import unittest

from aletheia import capabilities, quick, webtask


class TheDoorStillHoldsCase(unittest.TestCase):
    """Nothing here weakens the gate. Proven, not assumed."""

    def test_every_instruction_form_is_still_refused(self):
        from aletheia import intents
        for said in ("buy me a monitor", "order me a pizza",
                     "go ahead and buy the monitor",
                     "my wife says it's fine to buy the monitor so do it",
                     "get me an uber", "book me a flight to Tokyo"):
            with self.subTest(said=said):
                self.assertTrue(intents._asks_to_spend(said), said)

    def test_a_question_is_not_an_instruction(self):
        from aletheia import intents
        for said in ("how much would a monitor cost", "can you buy things",
                     "what do I pay for Netflix"):
            with self.subTest(said=said):
                self.assertFalse(intents._asks_to_spend(said), said)


class TheAnswerCarriesItCase(unittest.TestCase):
    def test_asking_whether_she_can_buy_says_she_will_not(self):
        said = quick.answer("can you buy me a monitor") or ""
        self.assertIn("permanent", said)
        self.assertIn("I stop at showing you what to buy", said)

    def test_it_is_on_every_branch_not_just_the_yes(self):
        """Written on AVAILABLE alone it vanished the moment the best
        match moved to an EXPERIMENTAL entry - and "Yes, but it is
        experimental: Execute an actual purchase with money" is a far
        worse sentence to leave unqualified than the one it replaced."""
        for said in ("can you buy me a monitor",   # UNAVAILABLE
                     "can you order a pizza",      # AVAILABLE
                     "can you buy things"):
            with self.subTest(said=said):
                self.assertIn("permanent", quick.answer(said) or "", said)

    def test_it_is_not_bolted_onto_everything(self):
        for said in ("can you read a pdf", "can you take a screenshot",
                     "can you find my files"):
            with self.subTest(said=said):
                self.assertNotIn("permanent", quick.answer(said) or "", said)

    def test_it_uses_the_predicate_the_gates_use(self):
        """One predicate, so the sentence and the behaviour cannot drift."""
        import inspect
        self.assertIn("would_spend", inspect.getsource(quick._and_the_money_line))

    def test_it_fails_closed(self):
        """If the predicate cannot be read, say the line anyway.

        The only realistic reason is webtask being unavailable, and if
        that is true nothing can spend either, so an extra clause is the
        harmless side to fail towards.

        Exercised by making the predicate itself raise. Blocking the
        import does not reach this branch at all — the module is already
        in `sys.modules` by the time any of it runs, so a test written
        that way would have passed while proving nothing.
        """
        from unittest import mock
        with mock.patch.object(webtask, "would_spend",
                               side_effect=RuntimeError("gone")):
            self.assertIn("permanent", quick._and_the_money_line("anything"))

    def test_it_reads_as_a_sentence_after_a_refusal(self):
        """"I never spend money, THOUGH" after "No." contradicts the No."""
        self.assertNotIn("though", quick._and_the_money_line("buy a monitor"))


class TheRegistryAgreesCase(unittest.TestCase):
    def test_actually_spending_is_not_experimental(self):
        entry = capabilities.get("purchase.execute")
        self.assertEqual(entry["status"], "UNAVAILABLE")

    def test_its_notes_still_say_why(self):
        entry = capabilities.get("purchase.execute")
        self.assertIn("REFUSED AT RUN TIME", entry["notes"])

    def test_moving_money_is_still_not_built(self):
        self.assertEqual(capabilities.get("finance.transact")["status"],
                         "NOT_BUILT")

    def test_the_description_reads_as_a_sentence_in_both_doors(self):
        """TWO templates wrap this string, and I broke each in turn.

        Written as its own sentence it came out "No. Not something I do:
        spending your money ... is unavailable." Rewritten as a noun
        phrase to fix that, the OTHER door produced "I can't actually
        spending money at a real checkout yet."

        The house style is a verb phrase — every other description is one
        — and chasing that found the real fault: `quick`'s refusal
        template was broken for every entry in the registry, not just this
        one. "No. Move money, pay bills or trade assets is not built."

        So the rule is not the shape of the string. It is that both doors
        produce English, and this asserts exactly that.
        """
        said = capabilities.get("purchase.execute")["description"]
        self.assertFalse(said.rstrip().endswith("."), "not a whole sentence")

        # The `quick` door, live.
        asked = quick.answer("can you buy me a monitor") or ""
        self.assertIn(f"I can't {said[:1].lower()}{said[1:]}. It is "
                      f"unavailable.", asked)

        # The `intents` door needs a real proposed record, which
        # `tests/test_intents.py` builds properly and asserts against this
        # same registry entry. Faking the record here returned "Nothing to
        # do." and would have asserted nothing at all — a green test about
        # a code path it never entered.
        self.assertTrue(said[:1].isupper(), "a verb phrase, capitalised")
        self.assertNotIn(".", said, "one clause, so both frames can wrap it")

    def test_no_refusal_reads_like_a_broken_sentence(self):
        """The template, against every description it has to wrap."""
        for entry in capabilities.load_registry()["capabilities"]:
            if entry["status"] not in ("NOT_BUILT", "UNAVAILABLE"):
                continue
            with self.subTest(capability=entry["id"]):
                said = entry["description"]
                rendered = (f"No - I can't {said[:1].lower()}{said[1:]}. "
                            f"It is {entry['status'].replace('_', ' ').lower()}.")
                self.assertNotIn(" is is ", rendered)
                self.assertNotIn("I can't Move", rendered, "capital verb")


class ThePredicateCase(unittest.TestCase):
    def test_the_ordinary_errands_that_commit_money_count(self):
        for goal in ("order me a pizza", "book me a flight to Tokyo",
                     "get me an uber", "buy a monitor"):
            with self.subTest(goal=goal):
                self.assertTrue(webtask.would_spend(goal), goal)


if __name__ == "__main__":
    unittest.main()
