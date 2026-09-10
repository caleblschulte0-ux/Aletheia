"""The staleness guard ate its own exit.

His real machine, tonight, with a four-day-old approval sitting in it:

    > approve
      The only thing waiting is from 5 days ago: Fully shut down Aletheia
      / stop her from listening entirely. Say approve that if you still
      want it.
    > approve that
      The only thing waiting is from 5 days ago: Fully shut down Aletheia
      / stop her from listening entirely. Say approve that if you still
      want it.

And so did "approve it", "yes to that", "approve the first one", "approve
the shutdown". Every route in and no route through: a stale approval had
become unapprovable by voice at all, and she was instructing him to say a
sentence that did nothing.

The guard is right and its question was wrong. It asked whether the
approval was REQUESTED recently, which is the same question as "has he
just been told about this" for a fresh one and a different question for
an old one. So `surfaced_at` records the moment he was TOLD - declared in
the Approval contract, bookkeeping and not authority: it never makes an
approval usable, only answerable, and `decide()` is still the only thing
that changes state. The AGE he hears stays the age of the request,
because five days old is the fact that matters.

Two more in the same sentence, found by driving it:

- AN OFFER IS A CLAIM ABOUT ABILITY. His real pending one is
  `intent.execute`, which is operator_always and may NEVER be approved by
  voice. "Say approve that if you still want it" sent him down a path
  that ends in a refusal for an entirely different reason. She asks the
  gate first now, and offers the thing she can actually do: denying needs
  no gate, because denying is the safe direction.
- AND IT SAID AN IDENTIFIER OUT LOUD: "intent.execute always needs you,
  not the room". Expanding it through the registry made it worse - the
  descriptions are clauses written for a reader, so it became "run an
  approved plan later, bound to a sha256 of exactly the plan that was
  approved always needs you". He does not need the name at all; the
  consequence is already in the same breath.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from unittest import mock

from aletheia import contracts, voice


class _WithApprovals(unittest.TestCase):
    """A throwaway store. An approve test that touches the live one is how
    a rehearsal halts the real Aletheia."""

    def setUp(self):
        self._was = os.environ.get("ALETHEIA_PRIVATE_STATE")
        os.environ["ALETHEIA_PRIVATE_STATE"] = tempfile.mkdtemp(prefix="ap-")
        from aletheia import policy
        self.policy = policy
        self._dir = policy.APPROVALS_DIR
        policy.APPROVALS_DIR = (
            __import__("pathlib").Path(os.environ["ALETHEIA_PRIVATE_STATE"])
            / "approvals")
        policy.APPROVALS_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.policy.APPROVALS_DIR = self._dir
        if self._was is None:
            os.environ.pop("ALETHEIA_PRIVATE_STATE", None)
        else:
            os.environ["ALETHEIA_PRIVATE_STATE"] = self._was

    def make(self, aid, capability, consequence, *, days_old=5):
        when = (dt.datetime.now(dt.timezone.utc)
                - dt.timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.policy.request(aid, "run 1 step(s): do_task",
                            'operator said: "..."', consequence,
                            reversible=False, capability=capability)
        stored = self.policy.load(aid)
        stored["requested_at"] = when
        stored.pop("surfaced_at", None)
        self.policy.save(stored)
        return stored

    def say(self, words):
        return voice._interpret(words) or {}


class TheContractDeclaresItCase(unittest.TestCase):
    def test_surfaced_at_is_a_field_an_approval_may_have(self):
        """The first fix shipped as a no-op: the contract rejected it and
        `surfaced` caught everything and returned."""
        ok = {"id": "a", "requested_action": "x", "reason": "y",
              "consequence": "z", "reversible": False, "state": "PENDING",
              "requested_at": "2026-09-05T00:00:00Z",
              "surfaced_at": "2026-09-09T00:00:00Z"}
        self.assertEqual(contracts.validate_approval(ok), [])

    def test_an_unknown_field_is_still_refused(self):
        """The contract's strictness is the thing that caught it."""
        bad = {"id": "a", "requested_action": "x", "reason": "y",
               "consequence": "z", "reversible": False, "state": "PENDING",
               "requested_at": "2026-09-05T00:00:00Z", "invented": "no"}
        self.assertTrue(contracts.validate_approval(bad))


class TheGuardStillHoldsCase(_WithApprovals):
    def test_a_bare_approve_does_not_run_a_stale_irreversible_thing(self):
        self.make("note-old", "memory.remember", "Save a note")
        out = self.say("approve")
        self.assertIsNone(out.get("command"), "it ran on a bare word")
        self.assertIn("5 days ago", out.get("say", ""))

    def test_a_fresh_one_still_answers_at_once(self):
        """The guard must not have made every approval a two-step."""
        self.make("note-new", "memory.remember", "Save a note", days_old=0)
        out = self.say("approve")
        self.assertEqual((out.get("command") or {}).get("kind"), "approve")


class TheGuardHasAnExitCase(_WithApprovals):
    def test_the_sentence_she_tells_him_to_say_works(self):
        self.make("note-old", "memory.remember", "Save a note about the rent")
        first = self.say("approve")
        self.assertIsNone(first.get("command"))
        self.assertIn("approve that", first.get("say", ""))
        second = self.say("approve that")
        self.assertEqual((second.get("command") or {}).get("kind"), "approve",
                         f"still looping: {second.get('say')}")
        self.assertEqual(second["command"]["id"], "note-old")

    def test_every_phrasing_gets_through_after_the_read_back(self):
        for words in ("approve that", "approve it", "yes to that",
                      "approve the first one"):
            with self.subTest(words=words):
                for path in self.policy.APPROVALS_DIR.glob("*.json"):
                    path.unlink()
                self.make("note-old", "memory.remember", "Save a note")
                self.say("approve")
                out = self.say(words)
                self.assertEqual((out.get("command") or {}).get("kind"),
                                 "approve", words)

    def test_the_age_he_hears_is_the_age_of_the_request(self):
        """Surfacing it must not make a five-day-old thing sound new.

        Only the "does he know what this is" test moves; `_how_long_ago`
        still reads `requested_at`, because five days old is the fact
        that matters and the whole reason she stopped to ask.
        """
        self.make("note-old", "memory.remember", "Save a note")
        self.assertIn("5 days ago", self.say("approve").get("say", ""))
        surfaced = self.policy.load("note-old")
        self.assertIn("surfaced_at", surfaced)
        self.assertIn("5 days ago", voice._how_long_ago(surfaced))

    def test_being_told_is_not_being_approved(self):
        """Bookkeeping, not authority."""
        self.make("note-old", "memory.remember", "Save a note")
        self.say("approve")
        stored = self.policy.load("note-old")
        self.assertEqual(stored["state"], "PENDING")
        self.assertIn("surfaced_at", stored)

    def test_a_write_that_fails_does_not_break_the_answer(self):
        self.make("note-old", "memory.remember", "Save a note")
        with mock.patch.object(self.policy, "save",
                               side_effect=RuntimeError("read only")):
            out = self.say("approve")
        self.assertIn("5 days ago", out.get("say", ""))


class WhatSheCannotDoSheDoesNotOfferCase(_WithApprovals):
    def test_a_voice_forbidden_approval_says_so_at_once(self):
        """Not after sending him down a path that ends in a refusal."""
        self.make("intent-shutdown", "intent.execute", "Fully shut down")
        said = self.say("approve").get("say", "")
        self.assertIn("Fully shut down", said)
        self.assertIn("in person", said)
        self.assertNotIn("Say approve that", said)

    def test_it_offers_the_thing_it_can_actually_do(self):
        self.make("intent-shutdown", "intent.execute", "Fully shut down")
        said = self.say("approve").get("say", "")
        self.assertIn("deny that", said)
        out = self.say("deny that")
        self.assertEqual((out.get("command") or {}).get("kind"), "deny")

    def test_no_identifier_is_read_out(self):
        self.make("intent-shutdown", "intent.execute", "Fully shut down")
        said = self.say("approve").get("say", "")
        self.assertNotIn("intent.execute", said)
        self.assertNotIn("sha256", said, "the registry description, verbatim")
        self.assertNotIn("_", said)

    def test_it_is_not_surfaced_because_it_can_never_be_answered(self):
        """Stamping one voice may not approve would be a lie in the store."""
        self.make("intent-shutdown", "intent.execute", "Fully shut down")
        self.say("approve")
        self.assertNotIn("surfaced_at", self.policy.load("intent-shutdown"))


if __name__ == "__main__":
    unittest.main()
