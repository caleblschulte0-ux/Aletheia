"""Jarvis gap prototypes — deliberately disconnected from Aletheia runtime."""

from .camera_question import CameraQuestionPipeline
from .desktop_context import DesktopContextObservation, WindowsContextBackend, capture
from .mobile_sensors import EphemeralSensorBuffer, ImageObservation, validate_location
from .ollama_vision import OllamaVisionBackend, OllamaVisionConfig
from .sensor_requests import SensorCapture, SensorTicketStore
from .vision import VisionAnswer, VisionReasoner
from .visual_fallback import VisualTarget, VisualTargetPlanner

__all__ = [
    "CameraQuestionPipeline",
    "DesktopContextObservation",
    "WindowsContextBackend",
    "capture",
    "EphemeralSensorBuffer",
    "ImageObservation",
    "validate_location",
    "OllamaVisionBackend",
    "OllamaVisionConfig",
    "SensorCapture",
    "SensorTicketStore",
    "VisionAnswer",
    "VisionReasoner",
    "VisualTarget",
    "VisualTargetPlanner",
]
