"""Second sandbox batch, 2026-10-04, frontier off. Three stores with a writer
and a fast reader that missed the phrasing he used, so a model answered - and
a model asked about a store nothing in its context mentions DENIES THE STORE
EXISTS (CLAUDE.md):

    > what's my shopping list        I don't have a shopping list for you ...
                                     if you've got one in a file somewhere ...
    > how much do I pay for netflix  I can look through what's gone through on
                                     your accounts for Netflix charges ...
    > what projects are you carrying I don't see any projects in front of me

The second one is worse than a denial: an OFFER to read bank data she does
not have. Each now has a fast reader that proves the store either way.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import quick


class TheShoppingListAnswersHoweverHeAsks(unittest.TestCase):
    def test_every_phrasing_reaches_the_same_reader(self):
        with mock.patch("aletheia.quick._shopping", return_value="1 thing on your shopping list: milk."):
            for q in ("what's my shopping list", "read me the shopping list", "what's on my grocery list",
                      "grocery list", "what do I need to get", "shopping list?"):
                self.assertEqual(quick.answer(q), "1 thing on your shopping list: milk.", q)


class WhatHePaysComesFromHerStoreAndNowhereElse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        from aletheia import subscriptions
        p = mock.patch.object(subscriptions, "SUBS_DIR", Path(self.tmp.name)); p.start(); self.addCleanup(p.stop)
        self.subs = subscriptions

    def test_an_empty_list_says_it_is_empty_and_names_no_bank(self):
        said = quick.answer("how much do I pay for netflix")
        self.assertEqual(said, "Netflix isn't on your subscriptions list, and the list is empty. "
                               "I only know the subscriptions you tell me about - I don't see your bank.")

    def test_a_hit_says_the_amount_and_the_cadence(self):
        self.subs.create("netflix", merchant="Netflix", amount=15.49, cadence="monthly", next_charge="2026-10-12")
        self.assertEqual(quick.answer("what do I pay for Netflix"),
                         "You pay $15.49 a month for Netflix. Next charge 2026-10-12.")
        self.assertEqual(quick.answer("how much is netflix costing me"),
                         "You pay $15.49 a month for Netflix. Next charge 2026-10-12.")

    def test_a_miss_names_what_she_does_have(self):
        self.subs.create("spotify", merchant="Spotify", amount=11.99)
        said = quick.answer("how much do I pay for netflix")
        self.assertTrue(said.startswith("Netflix isn't on your subscriptions list. I have Spotify."), said)
        self.assertIn("I don't see your bank", said)
        self.assertNotIn("accounts", said)


class TheProjectsSheCarriesAreTheCharters(unittest.TestCase):
    """One implementation: quick reads the same answer the `projects` kind gives."""

    def ask(self, q, rows, queued=()):
        with mock.patch("aletheia.plans.all_plans", return_value=rows), \
             mock.patch("aletheia.charters.pending", return_value=list(queued)), \
             mock.patch("aletheia.projects.all_projects", return_value=[]):
            return quick.answer(q)

    def test_open_charters_are_named_with_their_progress_and_whose_turn_it_is(self):
        rows = [
            {"slug": "barkly", "title": "Barkly", "state": "open", "project": {"repo": "money_machine"},
             "steps": [{"n": 1, "text": "Get CI green", "state": "todo", "owner": "thea"},
                       {"n": 2, "text": "Ship it", "state": "todo", "owner": "caleb", "needs": [1]}]},
            {"slug": "promo", "title": "Open Range demo films", "state": "open", "project": {"repo": "money_machine"},
             "steps": [{"n": 1, "text": "Write the status", "state": "done", "owner": "thea"},
                       {"n": 2, "text": "Pick a film", "state": "todo", "owner": "caleb", "needs": [1]}]},
            {"slug": "old", "title": "Old plan", "state": "open", "steps": []},         # not a charter
        ]
        said = self.ask("what projects are you carrying", rows)
        self.assertEqual(said, "I'm carrying Barkly (0 of 2 steps done, mine next) and "
                               "Open Range demo films (1 of 2 steps done, yours next).")

    def test_a_draft_and_an_ask_still_to_draft_are_both_said(self):
        rows = [{"slug": "drafted", "title": "Drafted thing", "state": "proposed", "project": {}, "steps": []}]
        said = self.ask("what are my projects", rows, queued=[{"kind": "new", "text": "a recipe app for my mom"}])
        self.assertEqual(said, "Waiting for your yes: Drafted thing. Still to draft or apply: a recipe app for my mom.")

    def test_an_empty_store_still_proves_the_store(self):
        self.assertEqual(self.ask("list my projects", []), "No active projects.")


class WhetherTheHuntIsPausedIsAMarkerFile(unittest.TestCase):
    def test_paused_and_not(self):
        with mock.patch("aletheia.apply_forever.paused", return_value={"reason": "until Monday"}):
            self.assertEqual(quick.answer("is the job hunt paused"),
                             'Yes, the job hunt is paused: until Monday. Say "start applying" and it picks up again.')
        with mock.patch("aletheia.apply_forever.paused", return_value=None), \
             mock.patch("aletheia.campaign.running", return_value=None):
            said = quick.answer("is the job hunt on hold")
        self.assertTrue(said.startswith("No, it isn't paused."), said)


if __name__ == "__main__":
    unittest.main()
