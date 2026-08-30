"""Jarvis gap prototypes — deliberately disconnected from Aletheia runtime."""

from .browser_transfers import DownloadProposal, UploadProposal, propose_download, propose_upload
from .camera_question import CameraQuestionPipeline
from .computer_extensions import ExtendedComputerProposal, propose as propose_computer_extension
from .desktop_context import DesktopContextObservation, WindowsContextBackend, capture
from .mobile_sensors import EphemeralSensorBuffer, ImageObservation, validate_location
from .multimodal_router import ReasoningRequest, RouteDecision, require_available, route
from .ollama_vision import OllamaVisionBackend, OllamaVisionConfig
from .phonelink_messages_probe import probe as probe_phonelink_messages
from .sensor_requests import SensorCapture, SensorTicketStore
from .texting import TextDraft, prepare as prepare_text
from .vision import VisionAnswer, VisionReasoner
from .visual_fallback import VisualTarget, VisualTargetPlanner

__all__ = [
    "DownloadProposal",
    "UploadProposal",
    "propose_download",
    "propose_upload",
    "CameraQuestionPipeline",
    "ExtendedComputerProposal",
    "propose_computer_extension",
    "DesktopContextObservation",
    "WindowsContextBackend",
    "capture",
    "EphemeralSensorBuffer",
    "ImageObservation",
    "validate_location",
    "ReasoningRequest",
    "RouteDecision",
    "require_available",
    "route",
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
