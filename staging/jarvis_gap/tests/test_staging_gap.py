from __future__ import annotations

import datetime as dt
import unittest

from staging.jarvis_gap.camera_question import CameraQuestionPipeline
from staging.jarvis_gap.desktop_context import capture
from staging.jarvis_gap.mobile_sensors import (
    EphemeralSensorBuffer,
    ImageObservation,
    validate_location,
)
from staging.jarvis_gap.sensor_requests import SensorTicketStore
from staging.jarvis_gap.ollama_vision import (
    OllamaVisionBackend, OllamaVisionConfig, OllamaVisionProtocolError, build_payload,
)
from staging.jarvis_gap.vision import VisionReasoner
from staging.jarvis_gap.visual_fallback import VisualTargetPlanner

UTC = dt.timezone.utc
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
JPEG = b"\xff\xd8\xff" + b"pixels"
WEBP = b"RIFF\x04\x00\x00\x00WEBP" + b"pixels"


class FakeVision:
    def __init__(self, output):
        self.output = output
        self.context = None
    def analyze(self, image, question, *, context):
        self.context = context
        return dict(self.output)


class FakeTarget:
    def __init__(self, output):
        self.output = output
    def locate(self, screenshot, instruction, *, width, height):
        return dict(self.output)


class FakeDesktop:
    def __init__(self, *, clipboard="secret-ish text"):
        self.clipboard = clipboard
    def foreground(self):
        return {"title": "Budget.xlsx - Excel", "process_id": 44,
                "process_path": r"C:\\Program Files\\Microsoft Office\\EXCEL.EXE"}
    def clipboard_text(self):
        return self.clipboard


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 30, 20, 0, tzinfo=UTC)

    def test_camera_metadata_never_contains_bytes(self):
        image = ImageObservation(JPEG, "image/jpeg", self.now)
        meta = image.metadata()
        self.assertNotIn("data", meta)
        self.assertEqual(meta["size_bytes"], len(JPEG))
        self.assertEqual(len(meta["sha256"]), 64)
        self.assertNotIn("pixels", repr(image))

    def test_media_type_must_match_bytes(self):
        with self.assertRaisesRegex(ValueError, "declared media"):
            ImageObservation(b"not an image", "image/jpeg", self.now)

    def test_location_requires_consent(self):
        packet = {"version": 1, "source": "iphone.geolocation",
                  "observed_at": self.now.isoformat(), "lat": 43.5,
                  "lon": -96.7, "accuracy_m": 8, "consent": False}
        with self.assertRaises(PermissionError):
            validate_location(packet, now=self.now)

    def test_location_rejects_stale_data(self):
        old = self.now - dt.timedelta(minutes=6)
        packet = {"version": 1, "source": "iphone.geolocation",
                  "observed_at": old.isoformat(), "lat": 43.5,
                  "lon": -96.7, "accuracy_m": 8, "consent": True}
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_location(packet, now=self.now, max_age_s=300)

    def test_camera_is_consume_once(self):
        buffer = EphemeralSensorBuffer(clock=lambda: self.now)
        image = ImageObservation(PNG, "image/png", self.now)
        buffer.put_camera(image)
        self.assertIs(buffer.consume_camera(), image)
        self.assertIsNone(buffer.consume_camera())

    def test_fresh_camera_is_not_silently_overwritten(self):
        buffer = EphemeralSensorBuffer(clock=lambda: self.now)
        buffer.put_camera(ImageObservation(PNG, "image/png", self.now))
        with self.assertRaisesRegex(RuntimeError, "unconsumed"):
            buffer.put_camera(ImageObservation(PNG + b"2", "image/png", self.now))

    def test_snapshot_exposes_metadata_not_pixels(self):
        buffer = EphemeralSensorBuffer(clock=lambda: self.now)
        buffer.put_camera(ImageObservation(WEBP, "image/webp", self.now))
        snap = buffer.snapshot()
        self.assertNotIn("data", snap["camera"])
        self.assertNotIn(b"pixels", repr(snap).encode())

    def test_snapshot_hides_precise_location(self):
        buffer = EphemeralSensorBuffer(clock=lambda: self.now)
        buffer.put_location({"version": 1, "source": "iphone.geolocation",
                             "observed_at": self.now.isoformat(), "lat": 43.5,
                             "lon": -96.7, "accuracy_m": 8, "consent": True})
        meta = buffer.snapshot()["location"]
        self.assertTrue(meta["present"])
        self.assertNotIn("lat", meta)
        self.assertNotIn("lon", meta)


class TicketTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 30, 20, 0, tzinfo=UTC)
        self.store = SensorTicketStore(clock=lambda: self.now)

    def test_camera_is_bound_to_one_request_and_token_is_one_shot(self):
        token, issued = self.store.issue("What is this?", kinds=("camera",))
        image = ImageObservation(JPEG, "image/jpeg", self.now)
        self.store.accept_camera(token, image)
        capture_obj = self.store.consume(token)
        self.assertEqual(capture_obj.camera.digest, image.digest)
        self.assertEqual(capture_obj.question_sha256, issued["question_sha256"])
        with self.assertRaises(PermissionError):
            self.store.status(token)

    def test_capture_metadata_hides_coordinates_until_explicitly_requested(self):
        token, _ = self.store.issue("Where am I?", kinds=("location",))
        packet = {"version": 1, "source": "iphone.geolocation",
                  "observed_at": self.now.isoformat(), "lat": 43.5,
                  "lon": -96.7, "accuracy_m": 8, "consent": True}
        self.store.accept_location(token, packet)
        capture_obj = self.store.consume(token)
        self.assertNotIn("lat", capture_obj.metadata()["location"])
        self.assertEqual(43.5, capture_obj.reasoning_context(include_location=True)["location"]["lat"])

    def test_wrong_sensor_kind_is_refused(self):
        token, _ = self.store.issue("Where am I?", kinds=("location",))
        with self.assertRaises(PermissionError):
            self.store.accept_camera(token, ImageObservation(JPEG, "image/jpeg", self.now))

    def test_capture_must_be_complete_before_consume(self):
        token, _ = self.store.issue("What is this place?", kinds=("camera", "location"))
        self.store.accept_camera(token, ImageObservation(JPEG, "image/jpeg", self.now))
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self.store.consume(token)

    def test_old_frame_cannot_be_replayed_into_new_request(self):
        token, _ = self.store.issue("What is this?", kinds=("camera",))
        old = self.now - dt.timedelta(minutes=2)
        with self.assertRaisesRegex(ValueError, "predates"):
            self.store.accept_camera(token, ImageObservation(JPEG, "image/jpeg", old))

    def test_future_camera_timestamp_is_refused(self):
        token, _ = self.store.issue("What is this?", kinds=("camera",))
        future = self.now + dt.timedelta(seconds=30)
        with self.assertRaisesRegex(ValueError, "future"):
            self.store.accept_camera(token, ImageObservation(JPEG, "image/jpeg", future))


class CameraQuestionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 30, 20, 0, tzinfo=UTC)
        self.backend = FakeVision({"answer": "A coffee mug.", "confidence": 0.95, "basis": "visible handle"})
        tickets = SensorTicketStore(clock=lambda: self.now)
        self.pipeline = CameraQuestionPipeline(VisionReasoner(self.backend), tickets=tickets)

    def test_what_is_this_vertical_slice_is_request_and_image_bound(self):
        token, issued = self.pipeline.start("What is this?")
        image = ImageObservation(JPEG, "image/jpeg", self.now)
        self.pipeline.submit_camera(token, image)
        answer = self.pipeline.answer(token, "What is this?")
        self.assertEqual(answer.answer, "A coffee mug.")
        self.assertEqual(answer.image_sha256, image.digest)
        self.assertEqual(self.backend.context["sensor_request"]["question_sha256"], issued["question_sha256"])

    def test_wrong_question_cannot_steal_captured_frame(self):
        token, _ = self.pipeline.start("What is this?")
        self.pipeline.submit_camera(token, ImageObservation(JPEG, "image/jpeg", self.now))
        with self.assertRaisesRegex(PermissionError, "does not match"):
            self.pipeline.answer(token, "Where am I?")
        # The failed mismatched question did not consume the legitimate capture.
        answer = self.pipeline.answer(token, "What is this?")
        self.assertEqual(answer.answer, "A coffee mug.")

    def test_location_only_reaches_vision_when_request_asked_for_it(self):
        token, _ = self.pipeline.start("What is this place?", include_location=True)
        self.pipeline.submit_camera(token, ImageObservation(JPEG, "image/jpeg", self.now))
        self.pipeline.submit_location(token, {"version": 1, "source": "iphone.geolocation",
                                              "observed_at": self.now.isoformat(), "lat": 43.5,
                                              "lon": -96.7, "accuracy_m": 8, "consent": True})
        self.pipeline.answer(token, "What is this place?")
        self.assertEqual(self.backend.context["location"]["lat"], 43.5)


class DesktopContextTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 30, 20, 0, tzinfo=UTC)

    def test_diagnostics_omit_clipboard_text_and_full_process_path(self):
        observation = capture(FakeDesktop(), now=self.now)
        meta = observation.metadata()
        self.assertEqual(meta["process_name"], "EXCEL.EXE")
        self.assertNotIn("process_path", meta)
        self.assertNotIn("active_window_title", meta)
        self.assertNotIn("Budget.xlsx", repr(observation))
        self.assertNotIn("text", meta["clipboard"])
        self.assertNotIn("secret-ish", repr(observation))

    def test_clipboard_disclosure_is_explicit(self):
        observation = capture(FakeDesktop(), now=self.now)
        self.assertNotIn("text", observation.reasoning_context()["clipboard"])
        self.assertEqual(
            observation.reasoning_context(include_clipboard=True)["clipboard"]["text"],
            "secret-ish text",
        )


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.image = ImageObservation(
            JPEG, "image/jpeg", dt.datetime(2026, 8, 30, tzinfo=UTC)
        )

    def test_read_only_answer(self):
        answer = VisionReasoner(FakeVision({
            "answer": "A red mug.", "confidence": 0.94, "basis": "cylindrical cup with handle"
        })).ask(self.image, "What is this?")
        self.assertEqual(answer.answer, "A red mug.")
        self.assertEqual(answer.image_sha256, self.image.digest)

    def test_vision_refuses_action_shaped_output(self):
        reasoner = VisionReasoner(FakeVision({
            "answer": "Submit button", "confidence": 0.9, "basis": "label",
            "click": {"x": 5, "y": 5},
        }))
        with self.assertRaises(PermissionError):
            reasoner.ask(self.image, "What is there?")

    def test_vision_context_is_bounded_before_backend(self):
        backend = FakeVision({"answer": "x", "confidence": 1.0, "basis": "x"})
        with self.assertRaisesRegex(ValueError, "context exceeds"):
            VisionReasoner(backend).ask(self.image, "What?", context={"x": "y" * 9000})
        self.assertIsNone(backend.context)


class OllamaVisionTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 30, 20, 0, tzinfo=UTC)
        self.image = ImageObservation(JPEG, "image/jpeg", self.now)

    def test_config_has_no_default_model_and_refuses_non_loopback(self):
        with self.assertRaises(ValueError):
            OllamaVisionConfig("").validated()
        with self.assertRaises(ValueError):
            OllamaVisionConfig(" vision-model ").validated()
        with self.assertRaisesRegex(ValueError, "loopback"):
            OllamaVisionConfig("vision-model", base_url="http://example.com:11434").validated()

    def test_payload_contains_one_image_and_no_tools(self):
        payload = build_payload(
            OllamaVisionConfig("vision-model"), self.image, "What is this?", {"source": "camera"}
        )
        self.assertEqual(payload["model"], "vision-model")
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)
        self.assertEqual(len(payload["messages"][1]["images"]), 1)
        import base64
        self.assertEqual(base64.b64decode(payload["messages"][1]["images"][0]), JPEG)

    def test_direct_backend_call_also_refuses_action_output(self):
        def transport(config, path, payload):
            return {"message": {"content": '{"answer":"button","confidence":0.9,"basis":"label","x":4}'}}
        backend = OllamaVisionBackend(OllamaVisionConfig("vision-model"), transport=transport)
        with self.assertRaises(PermissionError):
            backend.analyze(self.image, "What is there?", context={})

    def test_direct_backend_context_and_question_are_bounded(self):
        def transport(config, path, payload):
            self.fail("oversized input must fail before transport")
        backend = OllamaVisionBackend(OllamaVisionConfig("vision-model"), transport=transport)
        with self.assertRaisesRegex(ValueError, "question exceeds"):
            backend.analyze(self.image, "x" * 1300, context={})
        with self.assertRaisesRegex(ValueError, "context exceeds"):
            backend.analyze(self.image, "What?", context={"x": "y" * 9000})

    def test_backend_is_compatible_with_read_only_vision_reasoner(self):
        calls = []
        def transport(config, path, payload):
            calls.append((path, payload))
            return {"message": {"content": '{"answer":"A mug.","confidence":0.9,"basis":"handle"}'}}
        backend = OllamaVisionBackend(OllamaVisionConfig("vision-model"), transport=transport)
        answer = VisionReasoner(backend).ask(self.image, "What is this?")
        self.assertEqual(answer.answer, "A mug.")
        self.assertEqual(calls[0][0], "/api/chat")

    def test_action_shaped_model_output_is_still_refused_by_outer_contract(self):
        def transport(config, path, payload):
            return {"message": {"content": '{"answer":"button","confidence":0.9,"basis":"label","x":4}'}}
        backend = OllamaVisionBackend(OllamaVisionConfig("vision-model"), transport=transport)
        with self.assertRaises(PermissionError):
            VisionReasoner(backend).ask(self.image, "What is there?")

    def test_invalid_model_json_fails_closed(self):
        def transport(config, path, payload):
            return {"message": {"content": "not-json"}}
        backend = OllamaVisionBackend(OllamaVisionConfig("vision-model"), transport=transport)
        with self.assertRaises(OllamaVisionProtocolError):
            backend.analyze(self.image, "What?", context={})

    def test_status_never_claims_unpulled_model(self):
        def transport(config, path, payload):
            self.assertEqual(path, "/api/tags")
            return {"models": [{"name": "other-model"}]}
        status = OllamaVisionBackend(
            OllamaVisionConfig("vision-model"), transport=transport
        ).status()
        self.assertTrue(status["online"])
        self.assertFalse(status["model_available"])


class VisualFallbackTests(unittest.TestCase):
    def setUp(self):
        self.screen = ImageObservation(
            PNG, "image/png", dt.datetime(2026, 8, 30, tzinfo=UTC),
            source="windows.screenshot",
        )

    def test_target_is_proposal_only_and_hash_bound(self):
        target = VisualTargetPlanner(FakeTarget({
            "x": 800, "y": 450, "label": "Submit", "confidence": 0.91,
        })).propose(self.screen, "find submit", width=1920, height=1080)
        out = target.as_dict()
        self.assertTrue(out["ready_for_review"])
        self.assertFalse(out["execution_authority"])
        self.assertEqual(out["screenshot_sha256"], self.screen.digest)

    def test_out_of_bounds_target_is_refused(self):
        planner = VisualTargetPlanner(FakeTarget({
            "x": 2000, "y": 5, "label": "bad", "confidence": 0.99,
        }))
        with self.assertRaisesRegex(ValueError, "outside"):
            planner.propose(self.screen, "find", width=1920, height=1080)

    def test_low_confidence_is_not_ready(self):
        target = VisualTargetPlanner(FakeTarget({
            "x": 10, "y": 10, "label": "maybe", "confidence": 0.4,
        })).propose(self.screen, "find", width=100, height=100)
        self.assertFalse(target.ready_for_review)


if __name__ == "__main__":
    unittest.main()
