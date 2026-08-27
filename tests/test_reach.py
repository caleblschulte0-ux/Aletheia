"""The last mile for the room and for money.

Two halves of §143. Home Assistant is a boundary Aletheia may cross once
the operator gives her a token — so the code is real and the credential is
his. Moving money is a boundary she does not cross at all — so the code
carries the task up to it and stops, which is a different thing from not
having been written.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import devices, finance, hass, journal, policy, room, stateio


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, *a):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class HassCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {
            "ALETHEIA_HASS_URL": "http://hub.local:8123",
            "ALETHEIA_HASS_TOKEN": "tok",
            "ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in (
                (devices, "DEVICES_DIR", root / "private" / "devices"),
                (room, "SCENES_DIR", root / "private" / "room" / "scenes"),
                (policy, "APPROVALS_DIR", root / "approvals"),
                (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        (root / "approvals").mkdir(parents=True, exist_ok=True)
        halt = mock.patch.object(policy, "halted", return_value=None)
        halt.start(); self.addCleanup(halt.stop)
        devices.register("lamp", name="Desk lamp", kind="light", room="office",
                         provider="home_assistant", external_id="light.desk",
                         abilities=["on", "off", "brightness"])
        room.create("evening", "Evening", [{"device": "lamp", "ability": "brightness",
                                            "value": 30}])
        self.calls = []

    def opener(self, payload=None):
        def fake(request, timeout=None):
            self.calls.append((request.full_url, request.method,
                               json.loads(request.data) if request.data else None,
                               request.headers))
            return FakeResponse(payload if payload is not None else {"ok": True})
        return fake

    def online(self):
        devices.mark_observed("lamp", online=True, observed_state={"state": "on"})

    def approve(self, aid="ap-scene"):
        policy.request(aid, "move the room", "he asked", "lights change", False)
        policy.decide(aid, "APPROVED", via="test")
        return aid

    # ---- configuration honesty --------------------------------------

    def test_missing_url_says_exactly_what_is_missing(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_HASS_URL": ""}):
            ok, why = hass.available()
        self.assertFalse(ok)
        self.assertIn("ALETHEIA_HASS_URL", why)

    def test_missing_token_says_it_is_never_stored_in_the_repo(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_HASS_TOKEN": ""}):
            ok, why = hass.available()
        self.assertFalse(ok)
        self.assertIn("never stored in this repo", why)

    def test_a_rejected_token_is_reported_as_such(self):
        import urllib.error

        def deny(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 401, "no", {}, None)

        ok, detail = hass.ping(opener=deny)
        self.assertFalse(ok)
        self.assertIn("token is not accepted", detail)

    def test_an_unreachable_hub_degrades_rather_than_raising_into_callers(self):
        def refuse(request, timeout=None):
            raise OSError("connection refused")

        ok, detail = hass.ping(opener=refuse)
        self.assertFalse(ok)
        self.assertIn("could not reach", detail)

    def test_the_token_travels_as_a_bearer_header_only(self):
        hass.ping(opener=self.opener({"message": "API running"}))
        url, _, _, headers = self.calls[0]
        self.assertNotIn("tok", url)  # never in a URL, where it would be logged
        self.assertEqual(headers["Authorization"], "Bearer tok")

    # ---- the gate ----------------------------------------------------

    def test_a_scene_without_an_approval_is_refused_before_any_call(self):
        self.online()
        with self.assertRaises(policy.Halted):
            hass.execute_scene("evening", "ap-nope", opener=self.opener())
        self.assertEqual(self.calls, [])

    def test_a_device_not_observed_online_is_refused(self):
        # "turn off the heater" silently doing nothing is worse than a refusal
        aid = self.approve()
        with self.assertRaises(hass.HassUnavailable) as caught:
            hass.execute_scene("evening", aid, opener=self.opener())
        self.assertIn("not verified online", str(caught.exception))
        self.assertIn("hass observe", str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_an_approved_scene_calls_the_right_service(self):
        self.online()
        record = hass.execute_scene("evening", self.approve(), opener=self.opener())
        self.assertEqual(record["state"], "COMPLETED")
        url, method, payload, _ = self.calls[0]
        self.assertEqual(url, "http://hub.local:8123/api/services/light/turn_on")
        self.assertEqual(method, "POST")
        self.assertEqual(payload, {"entity_id": "light.desk", "brightness_pct": 30})

    def test_halt_stops_a_scene_before_the_next_device(self):
        self.online()
        aid = self.approve()
        with mock.patch.object(policy, "halted", return_value={"reason": "stop"}):
            record = hass.execute_scene("evening", aid, opener=self.opener())
        self.assertEqual(record["state"], "FAILED")
        self.assertEqual(self.calls, [])

    def test_an_unknown_ability_fails_loudly_instead_of_doing_nothing(self):
        self.online()
        with self.assertRaises(ValueError):
            hass._service_call({"ability": "teleport", "external_id": "x"})

    def test_observe_marks_a_missing_entity_offline(self):
        hass.observe(opener=self.opener([{"entity_id": "light.other", "state": "on"}]))
        self.assertEqual(devices.load("lamp")["status"], "OFFLINE")

    def test_observe_marks_a_live_entity_online(self):
        hass.observe(opener=self.opener(
            [{"entity_id": "light.desk", "state": "on", "attributes": {"brightness": 3}}]))
        self.assertEqual(devices.load("lamp")["status"], "ONLINE")

    def test_an_unavailable_entity_is_not_online(self):
        hass.observe(opener=self.opener(
            [{"entity_id": "light.desk", "state": "unavailable"}]))
        self.assertEqual(devices.load("lamp")["status"], "OFFLINE")

    def test_volume_is_translated_into_the_hubs_units(self):
        _, _, payload = hass._service_call(
            {"ability": "volume", "external_id": "media_player.x", "value": 40})
        self.assertAlmostEqual(payload["volume_level"], 0.4)


class MoneyBoundaryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for attr, value in (("ACCOUNTS_DIR", root / "accounts"),
                            ("TX_DIR", root / "tx"),
                            ("HANDOFF_DIR", root / "handoffs")):
            p = mock.patch.object(finance, attr, value)
            p.start(); self.addCleanup(p.stop)

    def test_there_is_still_no_way_to_move_money(self):
        # the point of the boundary: no function here sends a payment
        for forbidden in ("transfer", "pay", "trade", "transact", "withdraw"):
            self.assertFalse(hasattr(finance, forbidden),
                             f"finance.{forbidden} would cross §143")

    def test_a_hand_off_records_everything_except_the_authorization(self):
        value = finance.hand_off("rent", kind="bill", amount=1450.0,
                                 payee="Landlord Ltd", due="2026-09-01",
                                 why="he asked me to sort rent")
        self.assertEqual(value["state"], "AWAITING_OPERATOR")
        self.assertIn("§143", value["boundary"])
        self.assertIn("1450.00", value["remaining_work"])
        self.assertIn("Landlord Ltd", value["remaining_work"])

    def test_an_unknown_source_account_is_refused(self):
        with self.assertRaises(ValueError):
            finance.hand_off("x", kind="transfer", amount=10.0, payee="Someone",
                             from_account="not-a-real-account")

    def test_a_zero_or_negative_amount_is_refused(self):
        for amount in (0, -5):
            with self.assertRaises(ValueError):
                finance.hand_off("x", kind="bill", amount=amount, payee="A")

    def test_a_payee_is_required(self):
        with self.assertRaises(ValueError):
            finance.hand_off("x", kind="bill", amount=5.0, payee="  ")

    def test_pending_hand_offs_are_listed_until_he_settles_them(self):
        finance.hand_off("rent", kind="bill", amount=1450.0, payee="Landlord Ltd")
        self.assertEqual(len(finance.handoffs()), 1)
        finance.settle("rent", reference="CONF-99")
        self.assertEqual(finance.handoffs(), [])
        self.assertEqual(finance.handoffs(pending_only=False)[0]["reference"], "CONF-99")

    def test_settling_needs_the_reference_he_was_given(self):
        finance.hand_off("rent", kind="bill", amount=10.0, payee="A")
        with self.assertRaises(ValueError):
            finance.settle("rent", reference="")


if __name__ == "__main__":
    unittest.main()
