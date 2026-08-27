import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import audio_router, calls, journal, phone_v0, policy


class AudioPhoneCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(audio_router, "PLANS_DIR", root / "audio-plans"),
            mock.patch.object(audio_router, "SESSIONS_DIR", root / "audio-sessions"),
            mock.patch.object(phone_v0, "SESSIONS_DIR", root / "phone-sessions"),
            mock.patch.object(calls, "PLANS_DIR", root / "call-plans"),
            mock.patch.object(calls, "AUTH_DIR", root / "call-auth"),
            mock.patch.object(calls, "RESULTS_DIR", root / "call-results"),
            mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"),
            mock.patch.object(policy, "HALT_PATH", root / "halt.json"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.root = root

    def audio_plan(self, plan_id="bridge", purpose="phone_bridge"):
        return audio_router.build_plan(
            plan_id,
            purpose=purpose,
            endpoints=[
                {"id":"call-rx","kind":"virtual_output","label":"call received audio"},
                {"id":"assistant-in","kind":"virtual_input","label":"assistant microphone"},
                {"id":"assistant-out","kind":"virtual_output","label":"assistant speech"},
                {"id":"call-tx","kind":"virtual_input","label":"call microphone"},
                {"id":"operator-out","kind":"physical_output","label":"operator monitor"},
            ],
            routes=[
                {"source":"call-rx","sink":"assistant-in"},
                {"source":"assistant-out","sink":"call-tx"},
                {"source":"call-rx","sink":"operator-out","monitor":True},
            ],
        )

    def active_audio(self, plan_id="bridge", purpose="phone_bridge"):
        plan = self.audio_plan(plan_id, purpose)
        audio_router.request_activation_approval(plan_id, f"approve-audio-{plan_id}")
        policy.decide(f"approve-audio-{plan_id}", "APPROVED", via="test")
        backend = audio_router.InMemoryAudioBackend()
        session = audio_router.activate(plan_id, f"approve-audio-{plan_id}", backend,
                                        session_id=f"audio-session-{plan_id}")
        return plan, backend, session

    def authorized_call(self, call_id="doctor", max_minutes=10):
        plan = calls.propose(
            call_id, contact_ref="doctor-office", purpose="ask about an appointment",
            allowed_disclosures=["name", "availability"], forbidden_topics=["payment card"],
            success_condition="appointment options collected", max_minutes=max_minutes)
        approval_id = f"approve-call-{call_id}"
        policy.request(approval_id, calls.approval_action(plan),
                       reason="test call", consequence="phone call may be placed",
                       reversible=False)
        policy.decide(approval_id, "APPROVED", via="test")
        calls.authorize(call_id, approval_id)
        return plan


class TestAudioRouter(AudioPhoneCase):
    def test_plan_hash_detects_tampering(self):
        self.audio_plan()
        path = audio_router.PLANS_DIR / "bridge.json"
        value = json.loads(path.read_text())
        value["plan"]["routes"][0]["sink"] = "call-tx"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "hash"):
            audio_router.load_plan("bridge")

    def test_direct_feedback_cycle_and_duplicate_route_refused(self):
        endpoints = [
            {"id":"a","kind":"virtual_output","label":"A"},
            {"id":"b","kind":"virtual_input","label":"B"},
        ]
        with self.assertRaisesRegex(ValueError, "feedback"):
            audio_router.build_plan("cycle", purpose="other", endpoints=endpoints,
                                    routes=[{"source":"a","sink":"b"},{"source":"b","sink":"a"}])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audio_router.build_plan("dup", purpose="other", endpoints=endpoints,
                                    routes=[{"source":"a","sink":"b"},{"source":"a","sink":"b"}])

    def test_activation_requires_exact_approval(self):
        self.audio_plan()
        policy.request("wrong", "audio.route:not-the-plan", reason="wrong",
                       consequence="wrong", reversible=True)
        policy.decide("wrong", "APPROVED", via="test")
        backend = audio_router.InMemoryAudioBackend()
        with self.assertRaises(PermissionError):
            audio_router.activate("bridge", "wrong", backend)
        self.assertEqual(backend.starts, 0)

    def test_halt_blocks_backend_before_side_effect(self):
        self.audio_plan()
        audio_router.request_activation_approval("bridge", "audio-ok")
        policy.decide("audio-ok", "APPROVED", via="test")
        policy.halt("test stop", via="test")
        backend = audio_router.InMemoryAudioBackend()
        with self.assertRaises(policy.Halted):
            audio_router.activate("bridge", "audio-ok", backend)
        self.assertEqual(backend.starts, 0)

    def test_partial_activation_is_stopped_and_refused(self):
        self.audio_plan()
        audio_router.request_activation_approval("bridge", "audio-ok")
        policy.decide("audio-ok", "APPROVED", via="test")
        class Partial(audio_router.InMemoryAudioBackend):
            def start(self, plan):
                value = super().start(plan)
                value["routes"] = value["routes"][:-1]
                return value
        backend = Partial()
        with self.assertRaisesRegex(RuntimeError, "exact approved routes"):
            audio_router.activate("bridge", "audio-ok", backend)
        self.assertEqual(backend.starts, 1)
        self.assertEqual(backend.stops, 1)

    def test_wrong_routes_with_same_count_are_stopped_and_refused(self):
        self.audio_plan()
        audio_router.request_activation_approval("bridge", "audio-ok")
        policy.decide("audio-ok", "APPROVED", via="test")
        class Wrong(audio_router.InMemoryAudioBackend):
            def start(self, plan):
                value = super().start(plan)
                value["routes"][0] = "route-000000000000000000000000"
                return value
        backend = Wrong()
        with self.assertRaisesRegex(RuntimeError, "exact approved routes"):
            audio_router.activate("bridge", "audio-ok", backend)
        self.assertEqual(backend.stops, 1)

    def test_active_route_is_observed_and_stop_is_idempotent(self):
        _, backend, session = self.active_audio()
        observed = audio_router.verify_active(session["id"], backend)
        self.assertEqual(observed["state"], "ACTIVE")
        self.assertEqual(observed["route_fingerprints"],
                         audio_router.route_fingerprints(self.audio_plan_from_session(observed)))
        first = audio_router.stop(session["id"], backend)
        second = audio_router.stop(session["id"], backend)
        self.assertEqual(first["state"], "STOPPED")
        self.assertEqual(second["state"], "STOPPED")
        self.assertEqual(backend.stops, 1)

    def audio_plan_from_session(self, session):
        return audio_router.load_plan(session["plan_id"])["plan"]


class TestPhoneV0(AudioPhoneCase):
    def prepared(self, max_minutes=10, purpose="phone_bridge"):
        _, audio_backend, audio = self.active_audio(purpose=purpose)
        self.authorized_call(max_minutes=max_minutes)
        transport = phone_v0.InMemoryCallTransport()
        session = phone_v0.prepare("doctor", audio["id"], audio_backend=audio_backend,
                                   transport=transport, session_id="phone-doctor")
        return audio_backend, transport, session

    def test_wrong_audio_purpose_refused_before_dial(self):
        _, audio_backend, audio = self.active_audio(purpose="voice_assistant")
        self.authorized_call()
        transport = phone_v0.InMemoryCallTransport()
        with self.assertRaisesRegex(ValueError, "phone_bridge"):
            phone_v0.prepare("doctor", audio["id"], audio_backend=audio_backend,
                             transport=transport, session_id="phone-doctor")
        self.assertEqual(transport.dial_count, 0)

    def test_dial_preserves_identity_and_refuses_duplicate(self):
        audio_backend, transport, session = self.prepared()
        called = phone_v0.dial(session["id"], audio_backend=audio_backend, transport=transport)
        self.assertEqual(called["state"], "CONNECTED")
        envelope = transport.calls[called["call_handle"]]["envelope"]
        self.assertEqual(envelope["plan"]["identity_disclosure"], calls.IDENTITY_DISCLOSURE)
        with self.assertRaises(ValueError):
            phone_v0.dial(session["id"], audio_backend=audio_backend, transport=transport)
        self.assertEqual(transport.dial_count, 1)

    def test_dial_failure_claim_is_not_retried_blindly(self):
        audio_backend, _, session = self.prepared()
        class Boom(phone_v0.InMemoryCallTransport):
            def dial(self, envelope):
                self.dial_count += 1
                raise OSError("dial transport lost")
        boom = Boom()
        with self.assertRaises(OSError):
            phone_v0.dial(session["id"], audio_backend=audio_backend, transport=boom)
        self.assertEqual(phone_v0.load_session(session["id"])["state"], "FAILED")
        with self.assertRaises(ValueError):
            phone_v0.dial(session["id"], audio_backend=audio_backend, transport=boom)
        self.assertEqual(boom.dial_count, 1)

    def test_halt_blocks_keypad_but_not_hangup_cleanup(self):
        audio_backend, transport, session = self.prepared()
        session = phone_v0.dial(session["id"], audio_backend=audio_backend, transport=transport)
        policy.halt("operator stop", via="test")
        with self.assertRaises(policy.Halted):
            phone_v0.keypad(session["id"], "1#", audio_backend=audio_backend, transport=transport)
        ended = phone_v0.end(session["id"], audio_backend=audio_backend, transport=transport,
                             status="CANCELLED", summary="operator halted")
        self.assertEqual(ended["state"], "ENDED")
        self.assertEqual(audio_router.load_session(session["audio_session_id"])["state"], "STOPPED")

    def test_time_budget_forces_hangup(self):
        audio_backend, transport, session = self.prepared(max_minutes=1)
        session = phone_v0.dial(session["id"], audio_backend=audio_backend, transport=transport)
        now = dt.datetime.fromisoformat(session["started_at"].replace("Z", "+00:00")) + dt.timedelta(minutes=2)
        ended = phone_v0.observe(session["id"], audio_backend=audio_backend,
                                 transport=transport, now=now)
        self.assertEqual(ended["state"], "ENDED")
        self.assertEqual(ended["outcome_status"], "CANCELLED")
        self.assertIn("time budget", ended["call_result"]["summary"])

    def test_keypad_is_bounded_and_uses_same_authorized_session(self):
        audio_backend, transport, session = self.prepared()
        session = phone_v0.dial(session["id"], audio_backend=audio_backend, transport=transport)
        updated = phone_v0.keypad(session["id"], "12#", audio_backend=audio_backend, transport=transport)
        self.assertEqual(updated["state"], "CONNECTED")
        self.assertEqual(transport.keypad_log, [(session["call_handle"], "12#")])
        with self.assertRaises(ValueError):
            phone_v0.keypad(session["id"], "12A", audio_backend=audio_backend, transport=transport)


if __name__ == "__main__":
    unittest.main()
