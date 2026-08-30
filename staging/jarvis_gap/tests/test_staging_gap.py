from __future__ import annotations

import datetime as dt
import unittest

from staging.jarvis_gap.mobile_sensors import (
    EphemeralSensorBuffer,
    ImageObservation,
    validate_location,
)
from staging.jarvis_gap.vision import VisionReasoner
from staging.jarvis_gap.visual_fallback import VisualTargetPlanner

UTC = dt.timezone.utc


class FakeVision:
    def __init__(self, output):
        self.output = output
    def analyze(self, image, question, *, context):
        return dict(self.output)


class FakeTarget:
    def __init__(self, output):
        self.output = output
    def locate(self, screenshot, instruction, *, width, height):
        return dict(self.output)


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 30, 20, 0, tzinfo=UTC)

    def test_camera_metadata_never_contains_bytes(self):
        image = ImageObservation(b"jpeg-bytes", "image/jpeg", self.now)
        meta = image.metadata()
        self.assertNotIn("data", meta)
        self.assertEqual(meta["size_bytes"], 10)
        self.assertEqual(len(meta["sha256"]), 64)

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
        image = ImageObservation(b"x", "image/png", self.now)
        buffer.put_camera(image)
        self.assertIs(buffer.consume_camera(), image)
        self.assertIsNone(buffer.consume_camera())

    def test_snapshot_exposes_metadata_not_pixels(self):
        buffer = EphemeralSensorBuffer(clock=lambda: self.now)
        buffer.put_camera(ImageObservation(b"secret-pixels", "image/webp", self.now))
        snap = buffer.snapshot()
        self.assertNotIn("data", snap["camera"])
        self.assertNotIn(b"secret-pixels", repr(snap).encode())


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.image = ImageObservation(
            b"pixels", "image/jpeg", dt.datetime(2026, 8, 30, tzinfo=UTC)
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


class VisualFallbackTests(unittest.TestCase):
    def setUp(self):
        self.screen = ImageObservation(
            b"screen", "image/png", dt.datetime(2026, 8, 30, tzinfo=UTC),
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
