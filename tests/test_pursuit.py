"""Pursuit: one opportunity at a time, reasoned about, never a workflow.

His brief (docs/PURSUIT_BRIEF.md): "A developer should not be able to
answer: what does Aletheia always do after applying?" These tests hold the
rules that make that true without a model in the room: a scripted thinker
stands in for the reasoner, and every door to the world is a stub.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import pursuit

NOW = dt.datetime(2026, 9, 21, 15, 0, tzinfo=dt.timezone.utc)


def scripted(*answers):
    """A thinker that returns the given proposals in order (last one repeats)."""
    calls = []

    def think(record, now):
        calls.append(record["id"])
        idx = min(len(calls) - 1, len(answers) - 1)
        return answers[idx], {"provider": "scripted", "local": False}
    think.calls = calls
    return think


NOTHING = {"understanding": "A plain situation.", "uncertainty": [], "strategy": "Leave it.",
           "effort": {"minutes": 0, "why": "nothing more would help"}, "moves": [],
           "stop": {"done": True, "why": "nothing more would help"}}


class PursuitCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(pursuit, "store_dir", return_value=base / "opportunities"),
            mock.patch("aletheia.journal.append"),
            mock.patch("aletheia.policy.ensure_not_halted"),
        ]
        for p in self.patches:
            p.start()
        (base / "opportunities").mkdir()
        self.base = base

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def opportunity(self, **evidence):
        rec = pursuit.open_opportunity(key="thing-1", name="A role somewhere",
                                       objective="Get serious consideration", now=NOW)
        for kind, text in (evidence or {"posting": "They want someone who knows funding partners."}).items():
            pursuit.add_evidence(rec, kind, text, source="test", now=NOW)
        pursuit.save(rec)
        return rec


class TheRecordCase(PursuitCase):
    def test_opening_twice_is_one_opportunity(self):
        a = pursuit.open_opportunity(key="k", name="n", objective="o", now=NOW)
        b = pursuit.open_opportunity(key="k", name="n", objective="o", now=NOW)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(pursuit.all_opportunities()), 1)

    def test_the_same_evidence_twice_is_one_piece(self):
        rec = self.opportunity()
        first = pursuit.add_evidence(rec, "posting", "They want someone who knows funding partners.",
                                     source="test", now=NOW)
        self.assertEqual(first, rec["evidence"][0]["id"])
        self.assertEqual(len(rec["evidence"]), 1)

    def test_something_new_makes_it_due_now(self):
        rec = self.opportunity()
        rec["state"] = pursuit.PARKED
        rec["next_look"] = {"at": "2026-10-30T00:00:00Z", "because": "later"}
        pursuit.save(rec)
        self.assertEqual(pursuit.due(now=NOW), [])
        pursuit.observe(rec["id"], "reply", "They wrote back", now=NOW)
        due = pursuit.due(now=NOW)
        self.assertEqual([r["id"] for r in due], [rec["id"]])
        self.assertEqual(due[0]["state"], pursuit.OPEN)

    def test_an_outcome_that_ends_it_closes_it(self):
        rec = self.opportunity()
        pursuit.record_outcome(rec["id"], "declined", note="not this time", now=NOW)
        self.assertEqual(pursuit.load(rec["id"])["state"], pursuit.CLOSED)
        with self.assertRaises(pursuit.PursuitError):
            pursuit.record_outcome(rec["id"], "won the lottery", now=NOW)


class TheRulesOnAMoveCase(PursuitCase):
    """What the validator holds the model to, whatever it answers."""

    def test_a_move_with_no_reason_is_dropped(self):
        rec = self.opportunity()
        clean, dropped = pursuit.validate({"moves": [{"kind": "look", "why": "yes", "cites": ["e1"],
                                                      "detail": {"query": "x"}}]}, rec)
        self.assertEqual(clean["moves"], [])
        self.assertIn("no reason", dropped[0]["why"])

    def test_a_move_citing_no_evidence_she_holds_is_dropped(self):
        rec = self.opportunity()
        clean, dropped = pursuit.validate(
            {"moves": [{"kind": "look", "why": "it would settle whether they are growing",
                        "cites": ["e99"], "detail": {"query": "x"}}]}, rec)
        self.assertEqual(clean["moves"], [])
        self.assertIn("cites no evidence", dropped[0]["why"])

    def test_a_note_whose_claims_stand_on_nothing_is_dropped(self):
        rec = self.opportunity()
        clean, dropped = pursuit.validate(
            {"moves": [{"kind": "note_to_person", "why": "the posting stresses partners and he manages them",
                        "cites": ["e1"], "detail": {"to": "Dana", "text": "Hello", "grounded_on": []}}]}, rec)
        self.assertEqual(clean["moves"], [])
        self.assertIn("stand on no evidence", dropped[0]["why"])

    def test_a_kind_she_has_no_tool_for_becomes_a_suggestion_not_an_act(self):
        # Inventing a tactic is allowed; pretending to carry it out is not.
        rec = self.opportunity()
        clean, _ = pursuit.validate(
            {"moves": [{"kind": "record a short video walkthrough", "cites": ["e1"],
                        "why": "the posting asks for someone who can show their work"}]}, rec)
        self.assertEqual(clean["moves"][0]["kind"], "suggest")
        self.assertIn("video walkthrough", clean["moves"][0]["detail"]["idea"])

    def test_a_move_already_taken_is_not_taken_again(self):
        rec = self.opportunity()
        rec["never_repeat"] = ["note_to_person:dana"]
        pursuit.save(rec)
        clean, dropped = pursuit.validate(
            {"moves": [{"kind": "note_to_person", "why": "a second nudge might land this time",
                        "cites": ["e1"], "detail": {"to": "Dana", "text": "Hi again", "grounded_on": ["e1"]}}]},
            rec)
        self.assertEqual(clean["moves"], [])
        self.assertIn("never again", dropped[0]["why"])

    def test_effort_is_the_models_number_under_the_ceiling(self):
        rec = self.opportunity()
        clean, _ = pursuit.validate({"effort": {"minutes": 500, "why": "unusually promising"}}, rec)
        self.assertEqual(clean["effort"]["minutes"], 60)
        clean, _ = pursuit.validate({"effort": {"minutes": "lots"}}, rec)
        self.assertEqual(clean["effort"]["minutes"], 0)

    def test_the_catalog_is_what_the_model_is_shown(self):
        rec = self.opportunity()
        ctx = pursuit.context_for(rec, now=NOW)
        self.assertEqual(set(ctx["catalog"]), set(pursuit.MOVES))
        self.assertEqual(ctx["evidence"][0]["id"], "e1")
        compact = pursuit.context_for(rec, compact=True, now=NOW)
        self.assertNotIn("what_has_happened_elsewhere", compact)


class NothingIsFixedAfterwardsCase(PursuitCase):
    """The brief's test: there is no answer to "what does she always do next"."""

    def test_the_same_kind_of_opportunity_gets_different_moves_from_different_evidence(self):
        think = scripted(
            {**NOTHING, "moves": [{"kind": "look", "why": "the posting names a product she has not read about",
                                   "cites": ["e1"], "detail": {"query": "their new product", "question": "what is it"}}],
             "stop": {"done": False, "why": ""}},
            NOTHING)
        looked = []

        def fake_look(record, move, now):
            looked.append(move["detail"]["query"])
            return {"state": "done", "effect": "read it"}
        a = self.opportunity(posting="They just launched a product.")
        out_a = pursuit.pass_once(a["id"], think=think, doers={"look": fake_look}, now=NOW)
        b = pursuit.open_opportunity(key="thing-2", name="Another role", objective="o", now=NOW)
        pursuit.add_evidence(b, "posting", "Nothing remarkable.", source="test", now=NOW)
        pursuit.save(b)
        out_b = pursuit.pass_once(b["id"], think=think, doers={"look": fake_look}, now=NOW)
        self.assertEqual([d["move"] for d in out_a["did"]], ["look"])
        self.assertEqual(out_b["did"], [])
        self.assertEqual(looked, ["their new product"])
        self.assertEqual(pursuit.load(b["id"])["state"], pursuit.PARKED)

    def test_nothing_more_to_do_is_a_complete_answer(self):
        rec = self.opportunity()
        out = pursuit.pass_once(rec["id"], think=scripted(NOTHING), now=NOW)
        self.assertEqual(out["did"], [])
        fresh = pursuit.load(rec["id"])
        self.assertEqual(fresh["state"], pursuit.PARKED)
        self.assertEqual(fresh["strategy"], "Leave it.")

    def test_the_module_has_no_sequence_in_it(self):
        # Not a stage machine: no function decides what comes "after" anything.
        import inspect
        names = [n for n, _ in inspect.getmembers(pursuit, inspect.isfunction)]
        for word in ("after_", "follow_up", "stage_", "next_stage", "pipeline"):
            self.assertFalse(any(word in n for n in names), word)


class TheDoorsToTheWorldCase(PursuitCase):
    def test_a_note_is_a_draft_that_waits_for_his_yes_and_nothing_is_sent(self):
        rec = self.opportunity()
        drafted = []

        def fake_draft(to, subject, body, requested_via="voice"):
            drafted.append((to, subject, body, requested_via))
            return {"id": "mail-abc", "state": "PENDING"}
        proposal = {**NOTHING, "stop": {"done": False, "why": ""},
                    "effort": {"minutes": 5, "why": "worth a note"},
                    "moves": [{"kind": "note_to_person",
                               "why": "the posting stresses partners and his background is exactly that",
                               "cites": ["e1"],
                               "detail": {"to": "Dana <dana@example.com>", "subject": "Partners",
                                          "text": "A short, specific note.", "grounded_on": ["e1"]}}]}
        with mock.patch("aletheia.mail.available", return_value=(True, "")), \
             mock.patch("aletheia.mail.draft", side_effect=fake_draft), \
             mock.patch("aletheia.mail.send_approved") as sent:
            out = pursuit.pass_once(rec["id"], think=scripted(proposal, NOTHING), now=NOW)
        self.assertEqual(drafted[0][0], "dana@example.com")
        self.assertEqual(drafted[0][3], "pursuit")
        self.assertFalse(sent.called)
        move = pursuit.load(rec["id"])["moves"][0]
        self.assertEqual(move["state"], "waiting for his yes")
        self.assertEqual(move["handle"], "mail-abc")
        self.assertIn("note_to_person:dana <dana@example.com>", pursuit.load(rec["id"])["never_repeat"])
        self.assertEqual(out["did"][0]["state"], "waiting for his yes")

    def test_a_note_with_nobody_to_send_it_through_reaches_him_as_words(self):
        rec = self.opportunity()
        proposal = {**NOTHING, "stop": {"done": False, "why": ""}, "effort": {"minutes": 5, "why": "x"},
                    "moves": [{"kind": "note_to_person", "why": "a specific reason that is long enough",
                               "cites": ["e1"],
                               "detail": {"to": "Dana", "text": "Hello Dana.", "grounded_on": ["e1"]}}]}
        with mock.patch("aletheia.mail.available", return_value=(False, "not set up")), \
             mock.patch("aletheia.notifications.publish") as told:
            pursuit.pass_once(rec["id"], think=scripted(proposal, NOTHING), now=NOW)
        self.assertTrue(told.called)
        self.assertIn("Hello Dana.", told.call_args[0][1])
        self.assertEqual(pursuit.load(rec["id"])["moves"][0]["state"], "handed to him")

    def test_his_yes_is_read_back_from_the_approval(self):
        rec = self.opportunity()
        rec["moves"].append({"id": "m1", "kind": "note_to_person", "state": "waiting for his yes",
                             "handle": "mail-abc", "effect": "drafted", "why": "w", "cites": ["e1"],
                             "target": "note_to_person:dana", "detail": {}})
        pursuit.save(rec)
        with mock.patch("aletheia.policy.load", return_value={"state": "APPROVED"}):
            changed = pursuit.refresh_moves(rec["id"], now=NOW)
        self.assertEqual(changed[0]["state"], "sent")

    def test_a_suggestion_is_told_to_him_and_never_acted_on(self):
        rec = self.opportunity()
        proposal = {**NOTHING, "stop": {"done": False, "why": ""}, "effort": {"minutes": 5, "why": "x"},
                    "moves": [{"kind": "bring a cake to the office", "cites": ["e1"],
                               "why": "the posting says they love baking"}]}
        with mock.patch("aletheia.notifications.publish") as told:
            out = pursuit.pass_once(rec["id"], think=scripted(proposal, NOTHING), now=NOW)
        self.assertEqual(out["did"][0]["state"], "handed to him")
        self.assertIn("cake", told.call_args[0][1])

    def test_a_document_goes_into_her_workspace_and_the_ledger(self):
        rec = self.opportunity()
        proposal = {**NOTHING, "stop": {"done": False, "why": ""}, "effort": {"minutes": 10, "why": "x"},
                    "moves": [{"kind": "write", "why": "a short analysis would show he knows their market",
                               "cites": ["e1"],
                               "detail": {"title": "Their funding partners", "text": "Analysis body.",
                                          "grounded_on": ["e1"]}}]}
        with mock.patch("aletheia.workspace.root", return_value=self.base / "ws"), \
             mock.patch("aletheia.autonomy.record") as noted:
            out = pursuit.pass_once(rec["id"], think=scripted(proposal, NOTHING), now=NOW)
        path = Path(out["did"][0]["handle"])
        self.assertTrue(path.exists())
        self.assertIn("Analysis body.", path.read_text(encoding="utf-8"))
        self.assertEqual(noted.call_args.kwargs["consequence"], "reversible_local")

    def test_a_door_that_fails_is_recorded_not_raised(self):
        rec = self.opportunity()
        proposal = {**NOTHING, "stop": {"done": False, "why": ""}, "effort": {"minutes": 5, "why": "x"},
                    "moves": [{"kind": "look", "why": "it would settle whether they are hiring at all",
                               "cites": ["e1"], "detail": {"query": "are they hiring"}}]}

        def broken(record, move, now):
            raise RuntimeError("no network")
        with mock.patch("aletheia.demand.record_attempt") as demanded:
            out = pursuit.pass_once(rec["id"], think=scripted(proposal, NOTHING),
                                    doers={"look": broken}, now=NOW)
        self.assertEqual(out["did"][0]["state"], "failed")
        self.assertIn("no network", out["did"][0]["effect"])
        self.assertTrue(demanded.called)

    def test_a_look_keeps_what_it_read_as_untrusted_evidence(self):
        rec = self.opportunity()
        proposal = {**NOTHING, "stop": {"done": False, "why": ""}, "effort": {"minutes": 5, "why": "x"},
                    "moves": [{"kind": "look", "why": "the posting names a launch she has not read about",
                               "cites": ["e1"], "detail": {"url": "https://example.com/news"}}]}
        with mock.patch("aletheia.browse.read_page",
                        return_value={"title": "News", "text": "They launched a lending product."}):
            pursuit.pass_once(rec["id"], think=scripted(proposal, NOTHING), now=NOW)
        fresh = pursuit.load(rec["id"])
        looked = [e for e in fresh["evidence"] if e["kind"] == "looked"]
        self.assertEqual(looked[0]["provenance"], pursuit.UNTRUSTED)
        self.assertIn("lending product", looked[0]["text"])


class EffortIsADecisionCase(PursuitCase):
    def test_the_days_ceiling_stops_the_acting_not_the_thinking(self):
        rec = self.opportunity()
        rec["effort"] = {"spent_s": pursuit.EFFORT_DAY_S, "day": NOW.strftime("%Y-%m-%d"),
                         "allowed_s": 0.0, "because": ""}
        pursuit.save(rec)
        proposal = {**NOTHING, "stop": {"done": False, "why": ""}, "effort": {"minutes": 30, "why": "x"},
                    "moves": [{"kind": "look", "why": "it would settle whether they are hiring at all",
                               "cites": ["e1"], "detail": {"query": "q"}}]}
        looked = []
        out = pursuit.pass_once(rec["id"], think=scripted(proposal, NOTHING),
                                doers={"look": lambda r, m, n: looked.append(1) or {"state": "done", "effect": ""}},
                                now=NOW)
        self.assertEqual(looked, [])
        self.assertEqual(out["strategy"], "Leave it.")
        self.assertEqual(pursuit.load(rec["id"])["moves"][0]["state"], "proposed")

    def test_a_new_day_starts_the_budget_again(self):
        rec = self.opportunity()
        rec["effort"] = {"spent_s": pursuit.EFFORT_DAY_S, "day": "2026-09-20", "allowed_s": 0.0, "because": ""}
        self.assertEqual(pursuit._spent_today(rec, NOW), 0.0)


class TheBeatCase(PursuitCase):
    def test_nobody_able_to_think_leaves_it_due_later_not_failed(self):
        from aletheia import reasoner
        rec = self.opportunity()

        def cannot(record, now):
            raise reasoner.ReasonerUnavailable("nobody could think")
        out = pursuit.tick(think=cannot, now=NOW)
        self.assertEqual(out, [])
        fresh = pursuit.load(rec["id"])
        self.assertEqual(fresh["state"], pursuit.OPEN)
        self.assertEqual(fresh["next_look"]["at"], "2026-09-21T15:30:00Z")

    def test_lessons_are_sentences_about_what_happened_not_rules(self):
        rec = self.opportunity()
        rec["moves"].append({"id": "m1", "kind": "note_to_person", "state": "sent", "why": "w",
                             "cites": ["e1"], "target": "t", "detail": {}, "effect": ""})
        pursuit.save(rec)
        pursuit.record_outcome(rec["id"], "conversation", note="they asked for time", now=NOW)
        said = pursuit.lessons(now=NOW)
        self.assertEqual(len(said), 1)
        self.assertIn("note_to_person", said[0])
        self.assertIn("conversation", said[0])
        for word in ("always", "never", "%"):
            self.assertNotIn(word, said[0])

    def test_the_spoken_line_has_no_developer_words(self):
        rec = self.opportunity()
        rec["strategy"] = "Apply plainly; the fit is ordinary."
        pursuit.save(rec)
        said = pursuit.spoken(rec)
        self.assertIn("A role somewhere", said)
        for word in ("opp-", "e1", "ollama", "claude", "{", "}"):
            self.assertNotIn(word, said)

    def test_the_cli_lists_and_shows(self):
        rec = self.opportunity()
        with mock.patch("builtins.print") as out:
            self.assertEqual(pursuit.main(["list"]), 0)
            self.assertEqual(pursuit.main(["show", rec["id"]]), 0)
        shown = json.loads(out.call_args_list[1].args[0])
        self.assertEqual(shown["id"], rec["id"])


if __name__ == "__main__":
    unittest.main()
