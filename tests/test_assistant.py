"""The assistant CLI is the real caller for the personal-OS verbs.

Each test drives main(argv) end to end against patched private stores —
proving the registry's caller claims rather than asserting them.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (assistant, authority, communications, context, devices, documents,
                      finance, handler, notifications, outcomes, places, proactive,
                      projects, reservations, room, scheduler, shopping, subscriptions,
                      travel, vehicles)


class AssistantCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        bindings = [
            (notifications, "NOTICES_DIR", root / "notices"),
            (scheduler, "SCHEDULE_DIR", root / "sched" / "defs"),
            (scheduler, "RECEIPT_DIR", root / "sched" / "receipts"),
            (handler, "REQUESTS_DIR", root / "handler"),
            (projects, "PROJECTS_DIR", root / "projects"),
            (context, "REFS_DIR", root / "refs"),
            (places, "PLACES_DIR", root / "places"),
            (places, "TRAVEL_DIR", root / "travel-times"),
            (documents, "DOCS_DIR", root / "docs"),
            (shopping, "SHOP_DIR", root / "shopping"),
            (subscriptions, "SUBS_DIR", root / "subs"),
            (finance, "ACCOUNTS_DIR", root / "accounts"),
            (finance, "TX_DIR", root / "tx"),
            (vehicles, "VEHICLES_DIR", root / "vehicles"),
            (vehicles, "SERVICE_DIR", root / "service"),
            (travel, "TRIPS_DIR", root / "trips"),
            (reservations, "RES_DIR", root / "reservations"),
            (devices, "DEVICES_DIR", root / "devices"),
            (room, "SCENES_DIR", root / "scenes"),
            (authority, "GRANTS_DIR", root / "grants"),
            (authority, "CLAIMS_DIR", root / "claims"),
            (communications, "THREADS_DIR", root / "threads"),
            (communications, "MESSAGES_DIR", root / "messages"),
            (communications, "EXPECT_DIR", root / "expectations"),
            (proactive, "RULES_DIR", root / "rules"),
            (proactive, "RECEIPTS_DIR", root / "rule-receipts"),
            (outcomes, "ACTIONS_DIR", root / "actions"),
        ]
        for module, attr, value in bindings:
            patcher = mock.patch.object(module, attr, value)
            patcher.start(); self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = assistant.main(list(argv))
        self.assertEqual(code, 0, out.getvalue())
        return json.loads(out.getvalue())


class TestAssistant(AssistantCase):
    def test_schedule_lifecycle(self):
        created = self.run_cli("schedule", "add-daily", "morning", "brief",
                               "--tz", "UTC", "--time", "08:00")
        self.assertEqual(created["kind"], "daily")
        listed = self.run_cli("schedule", "list")
        self.assertEqual([s["id"] for s in listed], ["morning"])
        disabled = self.run_cli("schedule", "disable", "morning")
        self.assertFalse(disabled["enabled"])

    def test_notifications_ack_roundtrip(self):
        notice = notifications.publish("Hello", "world", dedupe_key="t")
        listed = self.run_cli("notifications", "--state", "UNREAD")
        self.assertEqual([n["id"] for n in listed], [notice["id"]])
        acked = self.run_cli("ack", notice["id"])
        self.assertEqual(acked["state"], "ACKNOWLEDGED")

    def test_handle_blocked_then_done(self):
        report = {"available": [], "blocked": [{"id": "x", "status": "NOT_BUILT"}],
                  "unknown": [], "satisfied": False}
        with mock.patch.object(handler.gaps, "assess", return_value=report), \
             mock.patch.object(handler.gaps, "materialize", return_value=[]):
            blocked = self.run_cli("handle", "new", "req", "--intent", "do x",
                                   "--requires", "x")
        self.assertEqual(blocked["state"], "BLOCKED_CAPABILITY")
        ready = {"available": ["x"], "blocked": [], "unknown": [], "satisfied": True}
        with mock.patch.object(handler.gaps, "assess", return_value=ready):
            self.run_cli("handle", "refresh", "req")
        done = self.run_cli("handle", "done", "req", "--evidence", "receipt abc")
        self.assertEqual(done["state"], "COMPLETED")

    def test_project_and_context(self):
        self.run_cli("project", "new", "alpha", "Alpha", "--goal", "ship")
        updated = self.run_cli("project", "update", "alpha", "--decision", "use v1")
        self.assertEqual(updated["decisions"][0]["text"], "use v1")
        self.run_cli("context", "remember", "r1", "--kind", "project",
                     "--value", "project:alpha", "--label", "it")
        resolved = self.run_cli("context", "resolve", "--kind", "project")
        self.assertEqual(resolved["value"], "project:alpha")

    def test_places_docs_shop_subs(self):
        self.run_cli("place", "new", "home", "Home", "--alias", "my house")
        self.assertEqual(self.run_cli("place", "resolve", "my house")["id"], "home")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("Pets require written approval.")
            path = fh.name
        self.addCleanup(os.unlink, path)
        self.run_cli("doc", "ingest", "lease", "--title", "Lease",
                     "--source", "upload", "--file", path)
        self.assertEqual(self.run_cli("doc", "search", "pets")[0]["id"], "lease")
        self.run_cli("shop", "new", "chair", "--need", "desk chair", "--budget", "200")
        self.run_cli("shop", "candidate", "chair", "c1", "--title", "Chair",
                     "--price", "150", "--source", "store")
        self.run_cli("shop", "select", "chair", "c1")
        proposal = self.run_cli("shop", "propose", "chair")
        self.assertEqual(proposal["authority"], "proposal_only")
        self.run_cli("subs", "new", "svc", "--merchant", "Service", "--amount", "120",
                     "--cadence", "annual")
        cancel = self.run_cli("subs", "cancel-request", "svc")
        self.assertEqual(cancel["cancel_proposal"]["required_approval"], "operator_always")

    def test_finance_vehicle_trip_reserve(self):
        self.run_cli("finance", "account", "checking", "--name", "Checking",
                     "--kind", "checking", "--balance", "1000", "--source", "bank export")
        self.assertEqual(self.run_cli("finance", "net")["net"], 1000)
        self.run_cli("vehicle", "new", "car", "--name", "Car")
        self.run_cli("vehicle", "odometer", "car", "11000")
        self.run_cli("vehicle", "rule", "car", "oil", "--description", "Oil",
                     "--every-miles", "5000", "--last-miles", "5000")
        self.assertEqual(self.run_cli("vehicle", "due", "car")[0]["rule_id"], "oil")
        self.run_cli("trip", "new", "sept", "--title", "Trip",
                     "--from", "2026-09-01", "--to", "2026-09-03")
        self.assertEqual(len(self.run_cli("trip", "gaps", "sept")), 2)
        self.run_cli("reserve", "new", "dinner", "--kind", "restaurant",
                     "--description", "Dinner", "--party", "2")
        self.run_cli("reserve", "candidate", "dinner", "slot", "--provider", "p",
                     "--place", "Cafe", "--slot", "19:00")
        self.run_cli("reserve", "select", "dinner", "slot")
        self.assertEqual(self.run_cli("reserve", "propose", "dinner")["authority"],
                         "proposal_only")

    def test_device_scene_plan(self):
        self.run_cli("device", "register", "lamp", "--name", "Lamp", "--kind", "light",
                     "--room", "office", "--provider", "ha", "--external-id", "light.lamp",
                     "--ability", "on", "--ability", "off")
        devices.mark_observed("lamp", online=True, observed_state={"on": False})
        self.run_cli("scene", "new", "night", "Night", "--step", "lamp:off")
        plan = self.run_cli("scene", "plan", "night")
        self.assertEqual(plan["status"], "READY_FOR_PROVIDER")

    def test_grant_requires_real_approval(self):
        with mock.patch.object(authority.policy, "is_approved", return_value=False):
            with self.assertRaises(PermissionError):
                assistant.main(["grant", "new", "g", "--capabilities", "browser.read",
                                "--approval", "nope", "--expires", "2099-01-01T00:00:00Z"])

    def test_interpret_never_guesses(self):
        self.assertEqual(self.run_cli("interpret", "do magic")["intent"], "clarify")

    def test_compose_and_recover(self):
        plan = self.run_cli("compose", "plan", "meeting.schedule")
        self.assertIn("ready", plan)
        step = self.run_cli("recover", "--code", "timeout", "--attempts", "1",
                            "--max-attempts", "3")
        self.assertEqual(step["decision"], "RETRY")

    def test_comm_thread_expectation_roundtrip(self):
        self.run_cli("comm", "thread", "t", "--with", "bob", "--subject", "plans")
        self.run_cli("comm", "message", "m1", "t", "--direction", "OUTBOUND",
                     "--channel", "email", "--from", "bob", "--summary", "asked",
                     "--at", "2026-08-26T10:00:00+00:00")
        exp = self.run_cli("comm", "expect", "e1", "t", "--after", "m1", "--from", "bob")
        self.assertEqual(exp["status"], "WAITING")
        self.assertEqual([e["id"] for e in self.run_cli("comm", "expectations")], ["e1"])

    def test_rule_lifecycle(self):
        rule = self.run_cli("rule", "new", "r1", "--on", "core.sync_failed",
                            "--action", "notify", "--cooldown-minutes", "60")
        self.assertTrue(rule["persistent"])
        self.assertFalse(self.run_cli("rule", "disable", "r1")["enabled"])
        self.assertEqual(len(self.run_cli("rule", "list")), 1)

    def test_outcome_evidence_gate(self):
        plan_json = json.dumps({"to": "x"})
        self.run_cli("outcome", "start", "a1", "--capability", "email.send",
                     "--provider", "local", "--intent", "send", "--plan", plan_json)
        self.run_cli("outcome", "attempt", "a1", "--outcome", "SUCCEEDED")
        with self.assertRaises(ValueError):  # no evidence, no VERIFIED
            assistant.main(["outcome", "verify", "a1"])
        self.run_cli("outcome", "evidence", "a1", "e1", "--kind", "equals",
                     "--observed", "2", "--expected", "2")
        self.assertEqual(self.run_cli("outcome", "verify", "a1")["status"], "VERIFIED")

    def test_state_snapshot(self):
        snapshot = self.run_cli("state")
        self.assertIn("needs_attention", snapshot)


if __name__ == "__main__":
    unittest.main()
