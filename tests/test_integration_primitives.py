import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (authority, brain, composition, current_state, documents, finance,
                      handler, meetings, notifications, places, reservations, room,
                      shopping, subscriptions, travel, vehicles)

UTC = dt.timezone.utc


class PrivateRootCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        bindings = [
            (notifications, "NOTICES_DIR", root / "notices"),
            (documents, "DOCS_DIR", root / "docs"),
            (places, "PLACES_DIR", root / "places"), (places, "TRAVEL_DIR", root / "travel-times"),
            (shopping, "SHOP_DIR", root / "shopping"), (subscriptions, "SUBS_DIR", root / "subs"),
            (finance, "ACCOUNTS_DIR", root / "accounts"), (finance, "TX_DIR", root / "tx"),
            (vehicles, "VEHICLES_DIR", root / "vehicles"), (vehicles, "SERVICE_DIR", root / "service"),
            (travel, "TRIPS_DIR", root / "trips"), (reservations, "RES_DIR", root / "reservations"),
            (authority, "GRANTS_DIR", root / "grants"), (authority, "CLAIMS_DIR", root / "claims"),
            (handler, "REQUESTS_DIR", root / "handler"),
        ]
        for module, attr, value in bindings:
            patcher = mock.patch.object(module, attr, value)
            patcher.start(); self.addCleanup(patcher.stop)


class TestNotifications(PrivateRootCase):
    def test_dedupe_and_ack(self):
        first = notifications.publish("Reply", "Bob replied", dedupe_key="reply:e1")
        second = notifications.publish("Reply again", "duplicate", dedupe_key="reply:e1")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(notifications.unread_count(), 1)
        notifications.set_state(first["id"], "ACKNOWLEDGED")
        self.assertEqual(notifications.unread_count(), 0)

    def test_invalid_priority_refused(self):
        with self.assertRaises(ValueError):
            notifications.publish("x", "y", priority="PANIC")


class TestBrain(PrivateRootCase):
    def test_unknown_output_fields_fail_closed(self):
        with self.assertRaises(brain.BrainOutputError):
            brain.validate_output({"intent": "answer", "summary": "x", "shell": "rm -rf"})

    def test_provider_validates_model_output(self):
        provider = brain.Provider("fake", lambda text, ctx: {"intent": "plan", "summary": "ok",
                                                              "required_capabilities": ["task.persist"],
                                                              "references": [], "confidence": 0.9})
        self.assertEqual(provider.run("handle it")["intent"], "plan")

    def test_fallback_does_not_pretend_understanding(self):
        self.assertEqual(brain.FALLBACK.run("do magic")["intent"], "clarify")


class TestPlaces(PrivateRootCase):
    def test_exact_resolution_and_observed_travel(self):
        places.create("home", "Home", aliases=["my house"])
        places.create("work", "Work")
        self.assertEqual(places.resolve("my house")["id"], "home")
        places.record_travel("home", "work", minutes=15, source="maps observation")
        self.assertEqual(places.travel_time("home", "work")["minutes"], 15)

    def test_travel_requires_provenance(self):
        places.create("a", "A"); places.create("b", "B")
        with self.assertRaises(ValueError):
            places.record_travel("a", "b", minutes=5, source="")


class TestDocuments(PrivateRootCase):
    def test_hash_and_search(self):
        doc = documents.ingest_text("lease", title="Lease", text="Pets require written approval.", source="upload")
        self.assertEqual(len(doc["sha256"]), 64)
        self.assertIn("Pets", documents.search("pets")[0]["snippet"])

    def test_tamper_detected(self):
        documents.ingest_text("d", title="D", text="original", source="upload")
        value = documents.read_json(documents._path("d"))
        value["text"] = "changed"
        documents.write_json_atomic(documents._path("d"), value)
        with self.assertRaises(ValueError):
            documents.load("d")


class TestShoppingAndSubscriptions(PrivateRootCase):
    def test_purchase_stays_proposal_only(self):
        shopping.create("chair", need="desk chair", budget=200)
        shopping.add_candidate("chair", "c1", title="Chair", price=150, source="store")
        shopping.select("chair", "c1")
        proposal = shopping.propose_purchase("chair")
        self.assertEqual(proposal["required_approval"], "operator_always")
        self.assertEqual(proposal["authority"], "proposal_only")

    def test_budget_is_enforced_before_proposal(self):
        shopping.create("chair", need="desk chair", budget=100)
        shopping.add_candidate("chair", "c1", title="Chair", price=150, source="store")
        with self.assertRaises(ValueError):
            shopping.select("chair", "c1")

    def test_subscription_monthly_equivalent_and_cancel_proposal(self):
        value = subscriptions.create("service", merchant="Service", amount=120, cadence="annual")
        self.assertEqual(subscriptions.monthly_equivalent(value), 10)
        result = subscriptions.request_cancel("service")
        self.assertEqual(result["cancel_proposal"]["required_approval"], "operator_always")


class TestFinance(PrivateRootCase):
    def test_net_worth_is_read_only_snapshot(self):
        finance.record_account("checking", name="Checking", kind="checking", balance=1000, source="bank export")
        finance.record_account("card", name="Card", kind="credit", balance=-200, source="bank export")
        result = finance.net_worth()
        self.assertEqual(result["net"], 800)
        self.assertEqual(result["authority"], "read_only_snapshot")

    def test_transaction_requires_known_account(self):
        with self.assertRaises(ValueError):
            finance.record_transaction("t1", account_id="missing", amount=-5, description="x",
                                       occurred_at="2026-08-26T12:00:00Z", source="export")


class TestVehicles(PrivateRootCase):
    def test_due_by_mileage_and_time(self):
        vehicles.create("car", name="Car")
        vehicles.record_odometer("car", 11000)
        vehicles.add_service_rule("car", "oil", description="Oil", every_miles=5000,
                                  every_days=180, last_miles=5000, last_date="2026-01-01")
        due = vehicles.due("car", today=dt.date(2026, 8, 26))
        self.assertEqual(set(due[0]["reasons"]), {"mileage", "time"})

    def test_odometer_cannot_go_backwards(self):
        vehicles.create("car", name="Car"); vehicles.record_odometer("car", 100)
        with self.assertRaises(ValueError):
            vehicles.record_odometer("car", 99)


class TestTravelAndReservations(PrivateRootCase):
    def test_itinerary_reports_missing_lodging_transport(self):
        travel.create("trip", title="Trip", start_date="2026-09-01", end_date="2026-09-03")
        self.assertEqual(len(travel.gaps("trip")), 2)
        travel.add_item("trip", "hotel", kind="hotel", title="Hotel")
        self.assertEqual(travel.gaps("trip"), ["transportation not recorded"])

    def test_reservation_not_confirmed_without_external_confirmation(self):
        reservations.create("dinner", kind="restaurant", description="Dinner", party_size=2)
        reservations.add_candidate("dinner", "slot", provider="provider", place="Cafe", slot="19:00")
        reservations.select("dinner", "slot")
        proposal = reservations.propose_booking("dinner")
        self.assertEqual(proposal["authority"], "proposal_only")
        confirmed = reservations.confirm("dinner", confirmation_id="ABC123", source="provider receipt")
        self.assertEqual(confirmed["state"], "CONFIRMED")


class TestAuthority(PrivateRootCase):
    def _cap(self, cid, *, risk="low", policy="none"):
        return {"id": cid, "risk_class": risk, "approval_policy": policy}

    def test_grant_requires_operator_approval(self):
        with mock.patch.object(authority.policy, "is_approved", return_value=False):
            with self.assertRaises(PermissionError):
                authority.create("g", capability_ids=["x"], approval_id="a",
                                 expires="2099-01-01T00:00:00Z")

    def test_high_risk_can_never_be_delegated(self):
        with mock.patch.object(authority.policy, "is_approved", return_value=True), \
             mock.patch.object(authority.capabilities, "get", return_value=self._cap("x", risk="high")):
            with self.assertRaises(ValueError):
                authority.create("g", capability_ids=["x"], approval_id="a",
                                 expires="2099-01-01T00:00:00Z")

    def test_bounded_claims_are_exclusive(self):
        with mock.patch.object(authority.policy, "is_approved", return_value=True), \
             mock.patch.object(authority.capabilities, "get", return_value=self._cap("x")):
            authority.create("g", capability_ids=["x"], approval_id="a",
                             expires="2099-01-01T00:00:00Z", max_uses=1)
            authority.claim("g", "x", "action-1", now=dt.datetime(2026, 8, 26, tzinfo=UTC))
            with self.assertRaises(PermissionError):
                authority.claim("g", "x", "action-2", now=dt.datetime(2026, 8, 26, tzinfo=UTC))


class TestCompositionAndMeeting(PrivateRootCase):
    def test_composition_reports_gaps(self):
        reg = {"capabilities": [{"id": "contacts.resolve", "status": "AVAILABLE"},
                                {"id": "calendar.availability", "status": "NOT_BUILT"},
                                {"id": "communication.track", "status": "AVAILABLE"}]}
        result = composition.plan("meeting.schedule", registry=reg)
        self.assertFalse(result["ready"])
        self.assertEqual(result["gaps"]["blocked"][0]["id"], "calendar.availability")

    def test_meeting_planner_resolves_person_and_constraints(self):
        records = [{"version": 1, "id": "bob", "display_name": "Bob", "emails": ["bob@example.com"],
                    "phones": [], "aliases": [], "organizations": [], "tags": [], "provenance": "test",
                    "created_at": "x", "updated_at": "x"}]
        result = meetings.propose("Bob", start_day="2026-08-31", end_day="2026-08-31",
                                  duration_minutes=30, timezone="America/Chicago", not_before="17:30",
                                  not_after="19:00", events=[], contact_records=records, limit=1)
        self.assertEqual(result["status"], "PROPOSED")
        self.assertTrue(result["slots"][0]["start"].startswith("2026-08-31T17:30"))


class TestRoom(PrivateRootCase):
    def test_scene_requires_online_declared_device(self):
        scene = {"version": 1, "id": "night", "name": "Night",
                 "steps": [{"device": "lamp", "ability": "off", "value": True}],
                 "created_at": "x", "updated_at": "x"}
        with mock.patch.object(room, "load", return_value=scene), \
             mock.patch.object(room.devices, "load", return_value={"id": "lamp", "abilities": ["off"],
                                                                    "status": "ONLINE", "provider": "ha",
                                                                    "external_id": "light.lamp"}), \
             mock.patch.object(room.devices, "require_ability") as require:
            result = room.plan("night")
        require.assert_called_once()
        self.assertEqual(result["status"], "READY_FOR_PROVIDER")


class TestCurrentState(PrivateRootCase):
    def test_snapshot_surfaces_attention_without_inventing_activity(self):
        with mock.patch.object(current_state.tasks, "all_tasks", return_value=[
                {"id": "t", "description": "Need operator", "status": "WAITING_OPERATOR"}]), \
             mock.patch.object(current_state.tasks, "ready", return_value=[]), \
             mock.patch.object(current_state.projects, "all_projects", return_value=[]), \
             mock.patch.object(current_state.policy, "all_approvals", return_value=[]), \
             mock.patch.object(current_state.policy, "halted", return_value=None), \
             mock.patch.object(current_state.communications, "all_expectations", return_value=[]), \
             mock.patch.object(current_state.scheduler, "all_schedules", return_value=[]), \
             mock.patch.object(current_state.notifications, "unread_count", return_value=0), \
             mock.patch.object(current_state.capabilities, "load_registry", return_value={"capabilities": []}):
            result = current_state.snapshot(now=dt.datetime(2026, 8, 26, tzinfo=UTC))
        self.assertEqual(result["needs_attention"]["waiting_operator"], ["t"])


if __name__ == "__main__":
    unittest.main()
