import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import audio_router, calls, journal, phone_v0, policy


class HardeningCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, path in [
            (audio_router, "PLANS_DIR", root / "audio-plans"),
            (audio_router, "SESSIONS_DIR", root / "audio-sessions"),
            (phone_v0, "SESSIONS_DIR", root / "phone-sessions"),
            (calls, "PLANS_DIR", root / "call-plans"),
            (calls, "AUTH_DIR", root / "call-auth"),
            (calls, "RESULTS_DIR", root / "call-results"),
            (policy, "APPROVALS_DIR", root / "approvals"),
            (policy, "HALT_PATH", root / "halt.json"),
            (journal, "JOURNAL_PATH", root / "journal.jsonl"),
        ]:
            p = mock.patch.object(target, name, path); p.start(); self.addCleanup(p.stop)

    def prepared(self):
        audio_router.build_plan(
            "bridge", purpose="phone_bridge",
            endpoints=[
                {"id":"rx","kind":"virtual_output","label":"RX"},
                {"id":"ain","kind":"virtual_input","label":"Assistant in"},
                {"id":"aout","kind":"virtual_output","label":"Assistant out"},
                {"id":"tx","kind":"virtual_input","label":"TX"},
            ],
            routes=[{"source":"rx","sink":"ain"},{"source":"aout","sink":"tx"}],
        )
        audio_router.request_activation_approval("bridge", "audio-ok")
        policy.decide("audio-ok", "APPROVED", via="test")
        audio = audio_router.InMemoryAudioBackend()
        audio_session = audio_router.activate("bridge", "audio-ok", audio, session_id="audio-live")

        call_plan = calls.propose("call", contact_ref="test", purpose="test purpose", max_minutes=5)
        policy.request("call-ok", calls.approval_action(call_plan), reason="test",
                       consequence="call", reversible=False)
        policy.decide("call-ok", "APPROVED", via="test")
        calls.authorize("call", "call-ok")
        transport = phone_v0.InMemoryCallTransport()
        phone = phone_v0.prepare("call", audio_session["id"], audio_backend=audio,
                                 transport=transport, session_id="phone-live")
        return audio, transport, phone

    def test_call_end_is_not_goal_verification(self):
        audio, transport, phone = self.prepared()
        phone = phone_v0.dial(phone["id"], audio_backend=audio, transport=transport)
        ended = phone_v0.end(phone["id"], audio_backend=audio, transport=transport,
                             status="COMPLETED", summary="transport ended normally")
        self.assertEqual(ended["state"], "ENDED")
        self.assertFalse(ended["call_result"]["verified"])

    def test_terminal_provider_status_cleans_audio_and_records_truth(self):
        audio, transport, phone = self.prepared()
        phone = phone_v0.dial(phone["id"], audio_backend=audio, transport=transport)
        transport.calls[phone["call_handle"]]["status"] = "BUSY"
        ended = phone_v0.observe(phone["id"], audio_backend=audio, transport=transport)
        self.assertEqual(ended["state"], "ENDED")
        self.assertEqual(ended["outcome_status"], "BUSY")
        self.assertEqual(audio_router.load_session(phone["audio_session_id"])["state"], "STOPPED")
        self.assertFalse(ended["call_result"]["verified"])

    def test_wrong_transport_cannot_hang_up_session(self):
        audio, transport, phone = self.prepared()
        phone = phone_v0.dial(phone["id"], audio_backend=audio, transport=transport)
        class Other(phone_v0.InMemoryCallTransport):
            provider_id = "other.phone"
        other = Other()
        with self.assertRaisesRegex(ValueError, "does not match"):
            phone_v0.end(phone["id"], audio_backend=audio, transport=other)
        self.assertEqual(transport.calls[phone["call_handle"]]["status"], "CONNECTED")
        self.assertEqual(audio_router.load_session(phone["audio_session_id"])["state"], "ACTIVE")

    def test_crash_uncertain_dial_claim_refuses_redial(self):
        audio, transport, phone = self.prepared()
        path = phone_v0.SESSIONS_DIR / "phone-live.json"
        value = json.loads(path.read_text())
        value["state"] = "DIALING"
        value["dial_claimed_at"] = value["updated_at"]
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, "reconcile manually"):
            phone_v0.observe("phone-live", audio_backend=audio, transport=transport)
        with self.assertRaises(ValueError):
            phone_v0.dial("phone-live", audio_backend=audio, transport=transport)
        self.assertEqual(transport.dial_count, 0)


if __name__ == "__main__":
    unittest.main()
