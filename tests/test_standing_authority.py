"""Standing authority: what it stops asking about, and what it can never reach.

Risk used to be a property of the MACHINERY — `intent.execute` is
high-risk and operator_always, so a plan that only set a reminder was
gated exactly like one that emails his landlord. Risk is a property of the
PLAN now. Most of these tests exist to prove that widening it did not
widen anything it should not have.
"""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (authority, capabilities, intercom, intents, journal,
                      policy, standing)

FLEET = {"repos": {}}
REGISTRY = {
    "providers": {"aletheia.local": {}},
    "capabilities": [
        {"id": "task.persist", "status": "AVAILABLE", "provider": "aletheia.local"},
    ],
}


def provider(output):
    from aletheia import brain
    return brain.Provider("stub", lambda text, ctx: output)


class TierCase(unittest.TestCase):
    def test_every_kind_has_exactly_one_tier(self):
        for kind in intercom.KIND_ARGS:
            self.assertIn(intercom.tier(kind),
                          {intercom.TIER_READ, intercom.TIER_ROUTINE,
                           intercom.TIER_WORLD}, kind)

    def test_the_tiers_do_not_overlap(self):
        self.assertEqual(intercom.READ_ONLY_KINDS & intercom.ROUTINE_KINDS, frozenset())

    def test_an_unknown_kind_is_world_touching(self):
        # fails closed: a verb added tomorrow and forgotten here needs a
        # decision, rather than quietly riding a standing grant
        self.assertEqual(intercom.tier("teleport_me"), intercom.TIER_WORLD)

    def test_everything_that_reaches_a_person_is_world_touching(self):
        for kind in ("email_draft", "meet", "issue", "dispatch"):
            self.assertEqual(intercom.tier(kind), intercom.TIER_WORLD, kind)

    def test_the_controls_themselves_are_world_touching(self):
        for kind in ("halt", "resume", "approve", "deny"):
            self.assertEqual(intercom.tier(kind), intercom.TIER_WORLD, kind)

    def test_a_plan_takes_the_tier_of_its_riskiest_step(self):
        self.assertEqual(intercom.plan_tier(["note", "brief"]), intercom.TIER_READ)
        self.assertEqual(intercom.plan_tier(["note", "remind_at"]),
                         intercom.TIER_ROUTINE)
        # THE invariant: one world-touching step drags the whole plan up
        self.assertEqual(intercom.plan_tier(["note", "remind_at", "email_draft"]),
                         intercom.TIER_WORLD)

    def test_an_empty_plan_is_not_world_touching(self):
        self.assertEqual(intercom.plan_tier([]), intercom.TIER_READ)


class GrantCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in (
                (authority, "GRANTS_DIR", root / "grants"),
                (authority, "CLAIMS_DIR", root / "claims"),
                (policy, "APPROVALS_DIR", root / "approvals"),
                (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        (root / "approvals").mkdir(parents=True, exist_ok=True)

    def test_nothing_is_granted_by_default(self):
        self.assertIsNone(standing.active())
        self.assertFalse(standing.status()["granted"])

    def test_enabling_creates_a_bounded_grant(self):
        grant = standing.enable(days=7, uses=10)
        self.assertEqual(grant["capability_ids"], [standing.ROUTINE_CAPABILITY])
        self.assertEqual(grant["max_uses"], 10)
        self.assertTrue(grant["expires"])
        self.assertTrue(standing.status()["granted"])

    def test_enabling_twice_does_not_stack_grants(self):
        first = standing.enable(days=7, uses=10)
        second = standing.enable(days=30, uses=500)
        self.assertEqual(first["id"], second["id"])

    def test_a_permission_with_no_end_is_refused(self):
        for days in (0, -1, 4000):
            with self.assertRaises(ValueError, msg=str(days)):
                standing.enable(days=days)

    def test_revoking_takes_effect_immediately(self):
        standing.enable(days=7, uses=10)
        self.assertTrue(standing.disable())
        self.assertIsNone(standing.active())
        self.assertFalse(standing.disable())  # nothing left to revoke

    def test_it_can_never_be_pointed_at_something_high_risk(self):
        # authority.create refuses at CREATION time...
        policy.request("ap", "x", "r", "c", True)
        policy.decide("ap", "APPROVED", via="test")
        for capability in ("email.send", "intent.execute", "browser.interact",
                           "computer.control"):
            with self.assertRaises(ValueError, msg=capability):
                authority.create(f"forged-{capability.replace('.', '-')}",
                                 capability_ids=[capability], approval_id="ap",
                                 expires="2099-01-01T00:00:00Z")

    def test_a_grant_edited_on_disk_still_buys_nothing(self):
        # ...and authority.allows refuses again at SPEND time
        grant = standing.enable(days=7, uses=10)
        grant["capability_ids"].append("email.send")
        from aletheia import stateio
        stateio.write_json_atomic(authority._path(grant["id"]), grant)
        self.assertIsNone(authority.satisfy("email.send", "act-1"))

    def test_status_reports_from_the_registry_not_from_memory(self):
        state = standing.status()
        self.assertIn("email.send", state["never_grantable"])
        self.assertIn("email_draft", state["always_asks"])
        self.assertIn("brief", state["without_asking"]["always"])
        self.assertEqual(state["without_asking"]["while_granted"], [])
        standing.enable(days=7, uses=10)
        self.assertIn("remind_at",
                      standing.status()["without_asking"]["while_granted"])


class RoutingCase(unittest.TestCase):
    """Which capability an intent's approval is actually filed against."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in (
                (authority, "GRANTS_DIR", root / "grants"),
                (authority, "CLAIMS_DIR", root / "claims"),
                (policy, "APPROVALS_DIR", root / "approvals"),
                (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        (root / "approvals").mkdir(parents=True, exist_ok=True)
        halt = mock.patch.object(policy, "halted", return_value=None)
        halt.start(); self.addCleanup(halt.stop)

    def propose(self, steps, summary="s"):
        return intents.propose(
            "do it", quote="do it", fleet=FLEET, materialize=False,
            registry=REGISTRY,
            provider=provider({"intent": "plan", "summary": summary,
                               "steps": steps}))

    ROUTINE = [{"kind": "remind_at", "at": "2026-09-01T09:00:00Z", "text": "x"},
               {"kind": "task_new", "id": "t", "description": "d"}]
    WORLD = ROUTINE + [{"kind": "email_draft", "to": "dana", "body": "hi"}]

    def test_a_routine_plan_asks_against_the_grantable_capability(self):
        record = self.propose(self.ROUTINE)
        self.assertEqual(record["tier"], intercom.TIER_ROUTINE)
        self.assertEqual(policy.load(record["approval"])["capability"],
                         "intent.execute.routine")

    def test_a_world_touching_plan_asks_against_the_ungrantable_one(self):
        record = self.propose(self.WORLD)
        self.assertEqual(record["tier"], intercom.TIER_WORLD)
        self.assertEqual(policy.load(record["approval"])["capability"],
                         "intent.execute")

    def test_without_a_grant_a_routine_plan_still_asks(self):
        record = self.propose(self.ROUTINE)
        self.assertEqual(policy.load(record["approval"])["state"], "PENDING")

    def test_with_a_grant_a_routine_plan_stops_asking(self):
        standing.enable(days=7, uses=10)
        record = self.propose(self.ROUTINE)
        approval = policy.load(record["approval"])
        self.assertEqual(approval["state"], "APPROVED")
        self.assertTrue(approval["decided_via"].startswith("grant:"))

    def test_ONE_world_touching_step_defeats_the_grant_entirely(self):
        # the invariant the whole design rests on
        standing.enable(days=7, uses=10)
        record = self.propose(self.WORLD)
        self.assertEqual(policy.load(record["approval"])["state"], "PENDING")

    def test_every_granted_run_leaves_a_claim_receipt(self):
        grant = standing.enable(days=7, uses=10)
        self.propose(self.ROUTINE)
        self.assertEqual(len(authority._claims(grant["id"])), 1)

    def test_an_exhausted_grant_goes_back_to_asking(self):
        standing.enable(days=7, uses=1)
        first = self.propose(self.ROUTINE, summary="one")
        self.assertEqual(policy.load(first["approval"])["state"], "APPROVED")
        second = self.propose(
            [{"kind": "remind_at", "at": "2026-09-02T09:00:00Z", "text": "y"}],
            summary="two")
        self.assertEqual(policy.load(second["approval"])["state"], "PENDING")

    def test_revoking_goes_back_to_asking(self):
        standing.enable(days=7, uses=10)
        standing.disable()
        record = self.propose(self.ROUTINE)
        self.assertEqual(policy.load(record["approval"])["state"], "PENDING")

    def test_a_read_only_plan_never_asks_grant_or_no_grant(self):
        record = self.propose([{"kind": "brief"}])
        self.assertEqual(record["state"], intents.EXECUTED)
        self.assertTrue(record["read_only"])


class VoiceBoundaryCase(unittest.TestCase):
    """The room microphone is unauthenticated. It may READ what she is
    allowed to do; it may not WIDEN it."""

    def said(self, phrase):
        from aletheia import voice
        return voice.interpret(f"thea {phrase}")

    def test_asking_what_she_may_do_is_answered(self):
        self.assertEqual(self.said("what can you do without asking me")["command"],
                         {"kind": "authority_status"})

    def test_granting_by_voice_is_refused_with_the_reason(self):
        for phrase in ("grant standing authority", "revoke your authority",
                       "give you authority", "stop asking me about the small stuff"):
            out = self.said(phrase)
            self.assertIsNone(out["command"], phrase)
            self.assertIn("anything in the room could say it", out["say"], phrase)
            self.assertIn("aletheia.standing", out["say"], phrase)

    def test_reading_it_is_a_read_only_kind(self):
        self.assertEqual(intercom.tier("authority_status"), intercom.TIER_READ)


class SpokenCase(unittest.TestCase):
    def test_it_can_say_what_it_may_do(self):
        with mock.patch.object(standing, "status", return_value={
                "granted": False, "expires": None, "uses_left": 0,
                "without_asking": {"always": ["brief"], "while_granted": []},
                "always_asks": ["email_draft"], "never_grantable": []}):
            said = standing.spoken()
        self.assertIn("ask you about everything else", said)
        self.assertNotIn("None", said)


if __name__ == "__main__":
    unittest.main()
