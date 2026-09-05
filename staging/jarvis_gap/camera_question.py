"""Isolated vertical slice for Playbook §87: "Thea, what is this?"

This joins the staging sensor ticket and read-only VISION contracts without
joining production Aletheia. The request is bound three ways before reasoning:
opaque sensor token, question sha256, and image sha256 in the returned answer.
A location packet is included only when that request explicitly asked for it.

No endpoint, mobile permission prompt, provider choice, command, click, memory
write, event publication, or Core route exists here.
"""
from __future__ import annotations

import hashlib

from .mobile_sensors import ImageObservation
from .sensor_requests import SensorTicketStore, _normalize_question
from .vision import VisionAnswer, VisionReasoner


def _question_digest(question: str) -> str:
    return hashlib.sha256(_normalize_question(question).encode("utf-8")).hexdigest()


class CameraQuestionPipeline:
    def __init__(self, vision: VisionReasoner, *, tickets: SensorTicketStore | None = None) -> None:
        if not isinstance(vision, VisionReasoner):
            raise TypeError("vision must be a VisionReasoner")
        self.vision = vision
        self.tickets = tickets or SensorTicketStore()

    def start(self, question: str, *, include_location: bool = False,
              ttl_s: float = 90.0) -> tuple[str, dict]:
        kinds = ("camera", "location") if include_location else ("camera",)
        return self.tickets.issue(question, kinds=kinds, ttl_s=ttl_s)

    def submit_camera(self, token: str, image: ImageObservation) -> dict:
        return self.tickets.accept_camera(token, image)

    def submit_location(self, token: str, packet: dict) -> dict:
        return self.tickets.accept_location(token, packet)

    def answer(self, token: str, question: str) -> VisionAnswer:
        normalized = _normalize_question(question)
        status = self.tickets.status(token)
        if _question_digest(normalized) != status["question_sha256"]:
            raise PermissionError("question does not match the sensor request that captured these observations")
        capture = self.tickets.consume(token)
        if capture.camera is None:
            raise RuntimeError("camera question completed without a camera frame")
        context = {"sensor_request": {
            "ticket_id": capture.ticket_id,
            "question_sha256": capture.question_sha256,
        }}
        if capture.location is not None:
            # Exact coordinates are disclosed only here, because this request
            # explicitly included location and is now performing its one read.
            context["location"] = dict(capture.location)
        return self.vision.ask(capture.camera, normalized, context=context)
