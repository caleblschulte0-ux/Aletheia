"""Wake-word and turn-state logic without microphone or TTS dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time


class VoiceState(str, Enum):
    SLEEPING = "sleeping"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class VoiceSession:
    wake_words: tuple[str, ...] = ("thea", "aletheia")
    followup_window_s: float = 12.0
    state: VoiceState = VoiceState.SLEEPING
    _followup_until: float = 0.0

    def accept(self, transcript: str, *, now: float | None = None) -> str | None:
        """Return command text if the turn belongs to Aletheia, else ``None``."""
        now = time.monotonic() if now is None else now
        text = transcript.strip()
        lowered = text.lower()
        for wake in self.wake_words:
            if lowered == wake:
                self.state = VoiceState.LISTENING
                self._followup_until = now + self.followup_window_s
                return ""
            prefix = wake + " "
            if lowered.startswith(prefix):
                self.state = VoiceState.THINKING
                self._followup_until = now + self.followup_window_s
                return text[len(prefix):].strip()

        if now <= self._followup_until and self.state in {
            VoiceState.LISTENING,
            VoiceState.THINKING,
            VoiceState.SPEAKING,
        }:
            self.state = VoiceState.THINKING
            self._followup_until = now + self.followup_window_s
            return text
        return None

    def mark_speaking(self, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.state = VoiceState.SPEAKING
        self._followup_until = now + self.followup_window_s

    def sleep(self) -> None:
        self.state = VoiceState.SLEEPING
        self._followup_until = 0.0
