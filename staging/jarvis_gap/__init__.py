"""Jarvis gap prototypes — deliberately disconnected from Aletheia runtime."""

from .mobile_sensors import EphemeralSensorBuffer, ImageObservation, validate_location
from .vision import VisionAnswer, VisionReasoner
from .visual_fallback import VisualTarget, VisualTargetPlanner

__all__ = [
    "EphemeralSensorBuffer",
    "ImageObservation",
    "validate_location",
    "VisionAnswer",
    "VisionReasoner",
    "VisualTarget",
    "VisualTargetPlanner",
]
