import unittest

from aletheia import contracts
from aletheia.capabilities import load_registry
from aletheia.fleet import load_fleet
from aletheia.plans import all_plans


def _task(**over):
    t = {"id": "t1", "description": "d", "status": "QUEUED",
         "created_at": "2026-08-25T00:00:00Z", "updated_at": "2026-08-25T00:00:00Z",
         "attempts": 0}
    t.update(over)
    return t


class TestTaskContract(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(contracts.validate_task(_task()), [])

    def test_bad_state_refused(self):
        problems = contracts.validate_task(_task(status="SORTA_DONE"))
        self.assertTrue(any("SORTA_DONE" in p for p in problems))

    def test_unknown_field_refused(self):
        problems = contracts.validate_task(_task(vibes="good"))
        self.assertTrue(any("unknown field" in p for p in problems))

    def test_optionals_accepted(self):
        t = _task(goal="g", priority=1, dependencies=["t0"],
                  assigned_worker="claude", required_capabilities=["fleet.read"])
        self.assertEqual(contracts.validate_task(t), [])


class TestOtherContracts(unittest.TestCase):
    def test_approval(self):
        ap = {"id": "a1", "requested_action": "send email", "reason": "operator asked",
              "consequence": "email is sent", "reversible": False,
              "state": "PENDING", "requested_at": "2026-08-25T00:00:00Z"}
        self.assertEqual(contracts.validate_approval(ap), [])
        ap["state"] = "MAYBE"
        self.assertTrue(contracts.validate_approval(ap))

    def test_action_record(self):
        r = {"id": "r1", "capability": "github.issue.create", "provider": "github.api",
             "requested_by": "operator-via-intercom", "timestamp": "2026-08-25T00:00:00Z",
             "policy_decision": "registry_grant satisfied", "result": "issue #4"}
        self.assertEqual(contracts.validate_action_record(r), [])

    def test_agent_roles_validated(self):
        a = {"id": "claude", "provider": "claude.session", "description": "builder",
             "roles": ["CODING", "SORCERY"]}
        problems = contracts.validate_agent(a)
        self.assertTrue(any("SORCERY" in p for p in problems))


class TestGoalContractMatchesPlansStore(unittest.TestCase):
    """One contract, one store: every real plan file must satisfy the Goal
    contract, so the two can never drift."""

    def test_every_plan_is_a_valid_goal(self):
        plans = all_plans()
        self.assertTrue(plans, "no plans on disk to hold the contract against")
        for p in plans:
            self.assertEqual(contracts.validate_goal(p), [], p.get("slug"))


class TestCapabilityRegistry(unittest.TestCase):
    def test_registry_loads_and_validates(self):
        reg = load_registry()
        self.assertGreaterEqual(len(reg["capabilities"]), 10)

    def test_every_entry_names_a_caller_or_ticket(self):
        for c in load_registry()["capabilities"]:
            self.assertTrue(c["caller"].strip(), c["id"])
            if c["status"] == "NOT_BUILT":
                self.assertIn("ticket", c["caller"].lower(), c["id"])

    def test_registry_gated_capabilities_exist_in_fleet_grants(self):
        """A capability claiming registry_grant must actually be gated by
        something in config/fleet.json's front_door model."""
        fleet = load_fleet()
        grants = set()
        for repo in fleet["repos"].values():
            fd = repo.get("front_door", {})
            if fd.get("dispatch"):
                grants.add("github.workflow.dispatch")
            if fd.get("issues"):
                grants.add("github.issue.create")
        for c in load_registry()["capabilities"]:
            if c["approval_policy"] == "registry_grant" and c["status"] == "AVAILABLE":
                self.assertIn(c["id"], grants,
                              f"{c['id']} claims registry_grant but no grant exists")


if __name__ == "__main__":
    unittest.main()
