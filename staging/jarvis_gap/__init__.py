"""Jarvis gap prototypes — deliberately disconnected from Aletheia runtime."""

from .camera_question import CameraQuestionPipeline
from .desktop_context import DesktopContextObservation, WindowsContextBackend, capture
from .mobile_sensors import EphemeralSensorBuffer, ImageObservation, validate_location
from .ollama_vision import OllamaVisionBackend, OllamaVisionConfig
from .phonelink_messages_probe import probe as probe_phonelink_messages
from .sensor_requests import SensorCapture, SensorTicketStore
from .texting import TextDraft, prepare as prepare_text
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
    "probe_phonelink_messages",
    "SensorCapture",
    "SensorTicketStore",
    "TextDraft",
    "prepare_text",
    "VisionAnswer",
    "VisionReasoner",
    "VisualTarget",
    "VisualTargetPlanner",
]
