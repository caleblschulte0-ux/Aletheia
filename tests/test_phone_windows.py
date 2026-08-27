"""The Phone Link transport: refuse clearly, and never claim a call that
is not happening.

The bug these were written around was found on real hardware, not in
design: the first version treated the PRESENCE of Hands-Free endpoints as
proof of a live call, and paired AirPods publish those permanently. It
reported call audio live with no call in progress. Endpoint STATE is the
signal; presence is not evidence of anything.
"""
import unittest
from unittest import mock

from aletheia import phone_v0, phone_windows


def endpoint(name, direction, state):
    return {"name": name, "direction": direction, "state": state,
            "active": state == phone_windows.DEVICE_STATE_ACTIVE}


IDLE = [  # a paired headset and a paired phone, no call
    endpoint("Headset (AirPods Hands-Free)", "output", 8),
    endpoint("Headset (AirPods Hands-Free)", "input", 8),
    endpoint("Output (Hands-Free HF Audio (iPhone))", "output", 8),
    endpoint("Input (Hands-Free HF Audio (iPhone))", "input", 8),
]
IN_CALL = [
    endpoint("Output (Hands-Free HF Audio (iPhone))", "output", 1),
    endpoint("Input (Hands-Free HF Audio (iPhone))", "input", 1),
]


class NumberCase(unittest.TestCase):
    def test_ordinary_shapes_normalize(self):
        for raw, expect in [("+1 (555) 010-9999", "+15550109999"),
                            ("555.010.9999", "5550109999"),
                            ("  +445550109  ", "+445550109")]:
            self.assertEqual(phone_windows.normalize_number(raw), expect)

    def test_anything_that_is_not_a_number_is_refused(self):
        for raw in ("", "   ", "the dentist", "+1-555-CALL-NOW", "12",
                    "+1555010999900000", "555;010", None):
            with self.assertRaises(ValueError, msg=repr(raw)):
                phone_windows.normalize_number(raw)

    def test_a_number_is_never_guessed_at(self):
        # no stripping of letters into digits, no area-code invention
        with self.assertRaises(ValueError):
            phone_windows.normalize_number("call mum")


class CallSignalCase(unittest.TestCase):
    def test_paired_but_idle_endpoints_are_not_a_call(self):
        # the exact false positive found on the real machine
        with mock.patch.object(phone_windows, "hfp_endpoints",
                               side_effect=lambda active_only=False: (
                                   [e for e in IDLE if e["active"]] if active_only else IDLE)):
            self.assertFalse(phone_windows.call_audio_live())

    def test_both_directions_active_is_a_call(self):
        with mock.patch.object(phone_windows, "hfp_endpoints",
                               side_effect=lambda active_only=False: (
                                   IN_CALL if active_only else IDLE + IN_CALL)):
            self.assertTrue(phone_windows.call_audio_live())

    def test_one_way_audio_is_not_a_call(self):
        half = [IN_CALL[0]]
        with mock.patch.object(phone_windows, "hfp_endpoints",
                               side_effect=lambda active_only=False: half):
            self.assertFalse(phone_windows.call_audio_live())

    def test_no_pycaw_means_no_claim_of_a_call(self):
        with mock.patch.dict("sys.modules", {"pycaw.pycaw": None, "pycaw": None}):
            self.assertEqual(phone_windows.hfp_endpoints(), [])
            self.assertFalse(phone_windows.call_audio_live())


class AvailabilityCase(unittest.TestCase):
    def patch(self, *, installed=True, running=True, paired=(True, "iPhone")):
        for name, value in (("phone_link_installed", installed),
                            ("phone_link_running", running),
                            ("phone_paired", paired)):
            p = mock.patch.object(phone_windows, name, return_value=value)
            p.start(); self.addCleanup(p.stop)

    def test_all_present_is_available(self):
        self.patch()
        ok, why = phone_windows.available()
        self.assertTrue(ok)
        self.assertIn("iPhone", why)

    def test_each_missing_piece_is_named(self):
        self.patch(installed=False)
        self.assertIn("not installed", phone_windows.available()[1])

    def test_installed_but_not_running_is_refused(self):
        self.patch(running=False)
        ok, why = phone_windows.available()
        self.assertFalse(ok)
        self.assertIn("not running", why)

    def test_no_paired_phone_is_refused(self):
        self.patch(paired=(False, "no Bluetooth phone is paired and connected"))
        ok, why = phone_windows.available()
        self.assertFalse(ok)
        self.assertIn("Bluetooth", why)

    def test_off_windows_is_honest(self):
        with mock.patch.object(phone_windows.os, "name", "posix"):
            ok, why = phone_windows.available()
        self.assertFalse(ok)
        self.assertIn("Windows-only", why)


class TransportCase(unittest.TestCase):
    def setUp(self):
        for name, value in (("phone_link_installed", True),
                            ("phone_link_running", True),
                            ("phone_paired", (True, "iPhone"))):
            p = mock.patch.object(phone_windows, name, return_value=value)
            p.start(); self.addCleanup(p.stop)
        self.launches = []
        p = mock.patch.object(
            phone_windows, "_launch_tel",
            side_effect=lambda n: self.launches.append(n) or (0, "launched"))
        p.start(); self.addCleanup(p.stop)
        self.transport = phone_windows.PhoneLinkTransport(settle_s=0)

    def live(self, value):
        return mock.patch.object(phone_windows, "call_audio_live", return_value=value)

    def test_dial_hands_the_number_to_phone_link(self):
        with self.live(True), mock.patch.object(phone_windows, "hfp_endpoints",
                                                return_value=IN_CALL):
            result = self.transport.dial({"number": "+1 555 010 9999"})
        self.assertEqual(self.launches, ["+15550109999"])
        self.assertEqual(result["status"], "CONNECTED")

    def test_a_dial_before_audio_is_ringing_not_connected(self):
        with self.live(False):
            result = self.transport.dial({"number": "5550109999"})
        self.assertEqual(result["status"], "RINGING")
        self.assertIn("waiting for call audio", result["detail"])

    def test_no_audio_within_the_timeout_is_no_answer(self):
        transport = phone_windows.PhoneLinkTransport(settle_s=0, connect_timeout_s=0)
        with self.live(False):
            handle = transport.dial({"number": "5550109999"})["handle"]
            result = transport.observe(handle)
        self.assertEqual(result["status"], "NO_ANSWER")

    def test_an_unavailable_machine_refuses_rather_than_dialling(self):
        with mock.patch.object(phone_windows, "phone_link_running", return_value=False):
            with self.assertRaises(phone_windows.TransportUnavailable):
                self.transport.dial({"number": "5550109999"})
        self.assertEqual(self.launches, [], "it dialled anyway")

    def test_a_bad_number_never_reaches_the_dialler(self):
        with self.assertRaises(ValueError):
            self.transport.dial({"number": "the dentist"})
        self.assertEqual(self.launches, [])

    def test_a_failed_launch_is_reported_as_failed(self):
        with mock.patch.object(phone_windows, "_launch_tel",
                               return_value=(1, "no such app")):
            result = self.transport.dial({"number": "5550109999"})
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("no such app", result["detail"])

    def test_unknown_handles_are_failed_not_crashes(self):
        for call in (lambda: self.transport.observe("nope"),
                     lambda: self.transport.keypad("nope", "1"),
                     lambda: self.transport.hangup("nope")):
            self.assertIn(call()["status"], {"FAILED", "ENDED"})

    def test_keypad_refuses_rather_than_pretending(self):
        # an IVR plan must not "succeed" having pressed nothing
        with self.live(False):
            handle = self.transport.dial({"number": "5550109999"})["handle"]
        result = self.transport.keypad(handle, "1")
        self.assertIn("not implemented", result["detail"])

    def test_hangup_marks_the_session_over(self):
        with self.live(True), mock.patch.object(phone_windows, "hfp_endpoints",
                                                return_value=IN_CALL):
            handle = self.transport.dial({"number": "5550109999"})["handle"]
        self.assertEqual(self.transport.hangup(handle)["status"], "ENDED")
        self.assertEqual(self.transport.observe(handle)["status"], "ENDED")

    def test_it_satisfies_the_controllers_observation_contract(self):
        with self.live(True), mock.patch.object(phone_windows, "hfp_endpoints",
                                                return_value=IN_CALL):
            result = self.transport.dial({"number": "5550109999"})
        bounded = phone_v0._normalize_observation(result)
        self.assertEqual(set(bounded), {"handle", "status", "detail"})
        self.assertIn(bounded["status"], phone_v0.TRANSPORT_STATUSES)

    def test_it_declares_a_provider_id_the_controller_accepts(self):
        self.assertEqual(phone_v0._transport_id(self.transport),
                         "windows.phonelink")


class PreflightCase(unittest.TestCase):
    def test_preflight_places_no_call(self):
        with mock.patch.object(phone_windows, "_launch_tel") as launch, \
             mock.patch.object(phone_windows, "phone_link_installed", return_value=True), \
             mock.patch.object(phone_windows, "phone_link_running", return_value=True), \
             mock.patch.object(phone_windows, "phone_paired", return_value=(True, "iPhone")), \
             mock.patch.object(
                 phone_windows, "hfp_endpoints",
                 side_effect=lambda active_only=False: (
                     [e for e in IDLE if e["active"]] if active_only else IDLE)):
            report = phone_windows.preflight()
        launch.assert_not_called()
        self.assertTrue(report["transport_available"])
        self.assertFalse(report["call_audio_live_now"])


if __name__ == "__main__":
    unittest.main()
