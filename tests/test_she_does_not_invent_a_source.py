"""She claimed read-only access to his bank. She has an empty folder.

    > what's my bank balance
      I can pull that up - I have read-only access to your balances and
      transactions.

`finance.accounts()` returns [] and always has. `finance.visibility` is a
store he could record snapshots into by hand, not a link to anything.
CLAUDE.md names this failure already - "an OFFER is a claim about
ability... there is no bank data. Inventing a source sounds like
helpfulness, which makes it harder to catch than inventing an answer."

Two faults, and the second is why the first mattered: "how much money do
I have" hit the grounded path and was honest, while "what's my BANK
balance" matched no pattern and was answered by a model with no finance
context at all. A question she can answer from a store must never reach a
model without it.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import intercom, voice


class TheWayAPersonAsksAboutMoneyCase(unittest.TestCase):
    def test_every_phrasing_reaches_the_store(self):
        """Not one of these may be left to a model to imagine."""
        for said in ("how much money do i have",
                     "what's my balance",
                     "what's my bank balance",
                     "what's in my bank",
                     "what do i have in the bank",
                     "what are my accounts",
                     "my net worth",
                     "how am i doing financially"):
            with self.subTest(said=said):
                decided = voice.interpret(said) or {}
                command = decided.get("command") or {}
                self.assertEqual(command.get("kind"), "money", said)


class AnEmptyStoreStillProvesTheStoreCase(unittest.TestCase):
    def _said(self, accounts, assets=0.0, liabilities=0.0, net=0.0):
        worth = {"accounts": accounts, "assets": assets,
                 "liabilities": liabilities, "net": net}
        with mock.patch("aletheia.finance.net_worth", return_value=worth), \
             mock.patch("aletheia.finance.handoffs", return_value=[]):
            return intercom.execute_command({"kind": "money"}, {}, quote="x")

    def test_nothing_connected_says_so_plainly(self):
        said = self._said(0)
        self.assertIn("no bank connected", said.lower())
        self.assertNotIn("0.00", said)

    def test_it_never_claims_access_it_does_not_have(self):
        """The sentence that started this: a claim about ability."""
        said = self._said(0).lower()
        for boast in ("i have read-only access", "i can pull",
                      "i'll fetch", "let me pull"):
            self.assertNotIn(boast, said)

    def test_a_zero_balance_is_not_reported_as_a_balance(self):
        """"Assets 0.00 across 0 accounts" implies accounts that are empty."""
        self.assertNotIn("assets", self._said(0).lower())

    def test_real_accounts_still_report_the_numbers(self):
        said = self._said(2, assets=1234.5, liabilities=200.0, net=1034.5)
        self.assertIn("1,234.50", said)
        self.assertIn("2 accounts", said)

    def test_large_numbers_are_grouped_so_they_can_be_read(self):
        """"1234567.00" out loud is a digit stream."""
        said = self._said(1, assets=1234567.0, net=1234567.0)
        self.assertIn("1,234,567.00", said)

    def test_it_is_sayable(self):
        for accounts in (0, 3):
            with self.subTest(accounts=accounts):
                said = self._said(accounts, assets=10.0, net=10.0)
                self.assertNotIn("{", said)
                self.assertNotIn("_", said)
                self.assertTrue(said.strip().endswith("."), said)


if __name__ == "__main__":
    unittest.main()
