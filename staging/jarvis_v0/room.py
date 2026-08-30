"""Conversation coordinator for an eventual always-listening room interface.

There is no microphone, speech recognizer, or TTS backend here.  The controller
only coordinates already-transcribed text with ``VoiceSession`` and a
``JarvisLoop``.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import LoopOutcome
from .loop import JarvisLoop, LoopResult
from .voice_contract import VoiceSession, VoiceState


@dataclass(frozen=True)
class RoomTurn:
    accepted: bool
    command_text: str | None
    result: LoopResult | None


class RoomController:
    def __init__(self, *, session: VoiceSession, loop: JarvisLoop) -> None:
        self.session = session
        self.loop = loop

    def transcript(self, text: str, *, now: float | None = None) -> RoomTurn:
        command = self.session.accept(text, now=now)
        if command is None:
            return RoomTurn(False, None, None)
        if command == "":
            return RoomTurn(True, "", None)

        result = self.loop.run(command)
        if result.summary:
            self.session.mark_speaking(now=now)
        if result.outcome in {LoopOutcome.FAILED, LoopOutcome.REFUSED}:
            # Keep a short follow-up window so the operator can correct/refine.
            self.session.state = VoiceState.SPEAKING
        return RoomTurn(True, command, result)
