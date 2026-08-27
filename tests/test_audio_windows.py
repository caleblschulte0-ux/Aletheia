"""The real audio backend, tested without real audio.

`sounddevice` is injected, so these run in CI and on a machine with no
sound card. What they hold is the part that makes a router trustworthy:
a route is active because FRAMES MOVED, never because a stream object
was constructed without raising.
"""
import unittest
from unittest import mock

from aletheia import audio_router, audio_windows


DEVICES = [
    {"device_index": 1, "name": "Microphone Array (Intel Smart Sound)",
     "input_channels": 4, "output_channels": 0, "default_samplerate": 16000.0},
    {"device_index": 3, "name": "Speakers (Realtek(R) Audio)",
     "input_channels": 0, "output_channels": 2, "default_samplerate": 48000.0},
    {"device_index": 7, "name": "Speakers (Realtek(R) Audio)",
     "input_channels": 0, "output_channels": 2, "default_samplerate": 48000.0},
    {"device_index": 11, "name": "Input (Hands-Free HF Audio)",
     "input_channels": 1, "output_channels": 0, "default_samplerate": 16000.0},
    {"device_index": 10, "name": "Output (Hands-Free HF Audio)",
     "input_channels": 0, "output_channels": 1, "default_samplerate": 16000.0},
]


class FakeStream:
    """A PortAudio stream that can be told to deliver frames, or not."""

    def __init__(self, **kw):
        self.kw = kw
        self.active = False
        self.closed = False
        self.callback = kw.get("callback")

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.closed = True


class FakeSoundDevice:
    def __init__(self, fail_on: set[int] | None = None):
        self.fail_on = fail_on or set()
        self.streams: list[FakeStream] = []

    def _make(self, **kw):
        if kw.get("device") in self.fail_on:
            raise RuntimeError(f"device {kw['device']} is in use")
        stream = FakeStream(**kw)
        self.streams.append(stream)
        return stream

    def RawInputStream(self, **kw):   # noqa: N802 - mirrors sounddevice
        return self._make(**kw)

    def RawOutputStream(self, **kw):  # noqa: N802
        return self._make(**kw)


def plan(routes=None, endpoints=None):
    return {
        "purpose": "phone_bridge",
        "endpoints": endpoints or [
            {"id": "mic", "kind": "physical_input", "label": "Microphone Array",
             "device_index": 1},
            {"id": "spk", "kind": "physical_output", "label": "Speakers",
             "device_index": 3},
        ],
        "routes": routes or [{"source": "mic", "sink": "spk", "monitor": False}],
    }


class ResolveCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(audio_windows, "inventory", return_value=DEVICES)
        p.start(); self.addCleanup(p.stop)

    def test_a_pinned_index_is_used(self):
        self.assertEqual(audio_windows.resolve_device(
            {"id": "mic", "kind": "physical_input", "label": "anything",
             "device_index": 1}), 1)

    def test_a_pinned_index_that_vanished_is_refused(self):
        with self.assertRaises(audio_windows.AudioDeviceError) as caught:
            audio_windows.resolve_device(
                {"id": "mic", "kind": "physical_input", "label": "x",
                 "device_index": 99})
        self.assertIn("no longer exists", str(caught.exception))

    def test_a_label_resolves_when_unambiguous(self):
        self.assertEqual(audio_windows.resolve_device(
            {"id": "mic", "kind": "physical_input",
             "label": "Microphone Array"}), 1)

    def test_an_ambiguous_label_refuses_rather_than_guessing(self):
        # two different devices both named "Speakers (Realtek(R) Audio)"
        with self.assertRaises(audio_windows.AudioDeviceError) as caught:
            audio_windows.resolve_device(
                {"id": "spk", "kind": "physical_output", "label": "Speakers"})
        self.assertIn("matches 2 devices", str(caught.exception))
        self.assertIn("pin device_index", str(caught.exception))

    def test_an_output_endpoint_cannot_resolve_to_an_input_device(self):
        with self.assertRaises(audio_windows.AudioDeviceError):
            audio_windows.resolve_device(
                {"id": "bad", "kind": "physical_output",
                 "label": "Microphone Array"})

    def test_a_pinned_index_of_the_wrong_direction_is_refused(self):
        with self.assertRaises(audio_windows.AudioDeviceError) as caught:
            audio_windows.resolve_device(
                {"id": "bad", "kind": "physical_output", "label": "x",
                 "device_index": 1})
        self.assertIn("has none", str(caught.exception))

    def test_an_unmatched_label_is_refused(self):
        with self.assertRaises(audio_windows.AudioDeviceError):
            audio_windows.resolve_device(
                {"id": "x", "kind": "physical_input", "label": "VB-CABLE"})

    def test_hands_free_endpoints_resolve_like_any_other_device(self):
        # the whole point of not requiring a virtual cable driver
        self.assertEqual(audio_windows.resolve_device(
            {"id": "call_in", "kind": "physical_input",
             "label": "Input (Hands-Free"}), 11)
        self.assertEqual(audio_windows.resolve_device(
            {"id": "call_out", "kind": "physical_output",
             "label": "Output (Hands-Free"}), 10)


class BackendCase(unittest.TestCase):
    def setUp(self):
        self.sd = FakeSoundDevice()
        p = mock.patch.object(audio_windows, "_sounddevice", return_value=self.sd)
        p.start(); self.addCleanup(p.stop)
        q = mock.patch.object(audio_windows, "inventory", return_value=DEVICES)
        q.start(); self.addCleanup(q.stop)
        self.backend = audio_windows.WindowsAudioBackend(settle_s=0)

    def pump(self, handle, blocks=1):
        """Deliver `blocks` of real frames through every input callback."""
        for route in self.backend._sessions[handle]:
            for _ in range(blocks):
                route._on_input(b"\x00\x00" * audio_windows.BLOCK_FRAMES,
                                audio_windows.BLOCK_FRAMES, None, None)

    def test_start_opens_one_stream_pair_per_route(self):
        handle = self.backend.start(plan())["handle"]
        self.assertEqual(len(self.sd.streams), 2)
        self.assertTrue(all(s.active for s in self.sd.streams))
        self.backend.stop(handle)

    def test_a_route_is_not_active_until_frames_move(self):
        observation = self.backend.start(plan())
        # streams opened, but nothing has crossed them yet
        self.assertFalse(observation["active"])
        self.assertEqual(observation["routes"], [])

    def test_a_route_becomes_active_once_frames_move(self):
        handle = self.backend.start(plan())["handle"]
        self.pump(handle)
        observed = self.backend.observe(handle)
        self.assertTrue(observed["active"])
        self.assertEqual(observed["routes"],
                         audio_router.route_fingerprints(plan()))

    def test_a_route_that_goes_silent_reads_as_dead_on_the_next_look(self):
        # a Bluetooth headset that wandered off, or a device another app took
        handle = self.backend.start(plan())["handle"]
        self.pump(handle)
        self.assertTrue(self.backend.observe(handle)["active"])
        self.assertFalse(self.backend.observe(handle)["active"])

    def test_a_stopped_stream_is_not_active_even_with_frames(self):
        handle = self.backend.start(plan())["handle"]
        self.pump(handle)
        self.sd.streams[0].active = False
        self.assertFalse(self.backend.observe(handle)["active"])

    def test_a_callback_error_makes_the_route_dead_not_silently_fine(self):
        handle = self.backend.start(plan())["handle"]
        route = self.backend._sessions[handle][0]
        self.pump(handle)
        route._error = "input: RuntimeError: device lost"
        self.assertFalse(self.backend.observe(handle)["active"])
        self.assertIn("device lost", self.backend.observe(handle)["detail"])

    def test_half_a_bridge_is_not_active(self):
        # a call with one deaf party is not a working phone bridge
        two = plan(
            endpoints=[
                {"id": "mic", "kind": "physical_input", "label": "m", "device_index": 1},
                {"id": "spk", "kind": "physical_output", "label": "s", "device_index": 3},
                {"id": "call_in", "kind": "physical_input", "label": "c", "device_index": 11},
                {"id": "call_out", "kind": "physical_output", "label": "o", "device_index": 10},
            ],
            routes=[{"source": "mic", "sink": "call_out", "monitor": False},
                    {"source": "call_in", "sink": "spk", "monitor": False}])
        handle = self.backend.start(two)["handle"]
        only_first = self.backend._sessions[handle][0]
        only_first._on_input(b"\x00\x00" * audio_windows.BLOCK_FRAMES,
                             audio_windows.BLOCK_FRAMES, None, None)
        observed = self.backend.observe(handle)
        self.assertFalse(observed["active"])
        self.assertEqual(len(observed["routes"]), 1)

    def test_a_failed_second_route_closes_the_first(self):
        self.sd.fail_on = {10}
        two = plan(
            endpoints=[
                {"id": "mic", "kind": "physical_input", "label": "m", "device_index": 1},
                {"id": "spk", "kind": "physical_output", "label": "s", "device_index": 3},
                {"id": "call_out", "kind": "physical_output", "label": "o", "device_index": 10},
            ],
            routes=[{"source": "mic", "sink": "spk", "monitor": False},
                    {"source": "mic", "sink": "call_out", "monitor": False}])
        with self.assertRaises(audio_windows.AudioDeviceError):
            self.backend.start(two)
        self.assertTrue(all(s.closed for s in self.sd.streams),
                        "a half-open session leaked streams")
        self.assertEqual(self.backend._sessions, {})

    def test_stop_closes_streams_and_keeps_no_audio(self):
        handle = self.backend.start(plan())["handle"]
        self.pump(handle, blocks=3)
        route = self.backend._sessions[handle][0]
        self.backend.stop(handle)
        self.assertTrue(all(s.closed for s in self.sd.streams))
        self.assertEqual(route._blocks, [], "audio outlived the session")

    def test_an_unknown_handle_is_inactive_not_an_error(self):
        observed = self.backend.observe("win-audio-nope")
        self.assertFalse(observed["active"])
        self.assertEqual(observed["detail"], "unknown handle")

    def test_the_queue_drops_oldest_rather_than_growing(self):
        handle = self.backend.start(plan())["handle"]
        self.pump(handle, blocks=audio_windows.QUEUE_BLOCKS + 20)
        route = self.backend._sessions[handle][0]
        self.assertLessEqual(len(route._blocks), audio_windows.QUEUE_BLOCKS)
        self.backend.stop(handle)

    def test_output_writes_silence_when_nothing_has_arrived(self):
        handle = self.backend.start(plan())["handle"]
        route = self.backend._sessions[handle][0]
        buffer = bytearray(b"\xff" * (audio_windows.BLOCK_FRAMES * 2))
        route._on_output(buffer, audio_windows.BLOCK_FRAMES, None, None)
        self.assertEqual(bytes(buffer), b"\x00" * len(buffer),
                         "stale audio was replayed instead of silence")
        self.backend.stop(handle)

    def test_the_observation_satisfies_the_routers_bounded_contract(self):
        # audio_router refuses any observation with unexpected fields
        handle = self.backend.start(plan())["handle"]
        self.pump(handle)
        observed = self.backend.observe(handle)
        bounded = audio_router._bounded_observation(observed)
        self.assertEqual(set(bounded), {"handle", "active", "routes", "detail"})
        self.backend.stop(handle)


class HonestDegradationCase(unittest.TestCase):
    def test_a_missing_sounddevice_says_how_to_fix_it(self):
        with mock.patch.dict("sys.modules", {"sounddevice": None}):
            with self.assertRaises(audio_windows.AudioDeviceError) as caught:
                audio_windows._sounddevice()
        self.assertIn("requirements-optional", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
