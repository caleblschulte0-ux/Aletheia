"""Perception-frame assembly for staging.

Real adapters can later contribute accessibility-tree, browser, notification,
microphone, camera, or device observations.  This module only combines already
supplied observations and removes exact duplicates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .contracts import Observation

Sensor = Callable[[str], Sequence[Observation]]


@dataclass(frozen=True)
class SensorSpec:
    name: str
    read: Sensor
    optional: bool = True


class PerceptionHub:
    def __init__(self, sensors: Sequence[SensorSpec], *, max_observations: int = 100) -> None:
        if max_observations < 1:
            raise ValueError("max_observations must be positive")
        self.sensors = tuple(sensors)
        self.max_observations = max_observations

    def observe(self, utterance: str) -> Sequence[Observation]:
        combined: list[Observation] = []
        seen: set[tuple[str, str, str]] = set()
        for sensor in self.sensors:
            try:
                batch = sensor.read(utterance)
            except Exception:
                if sensor.optional:
                    continue
                raise
            for item in batch:
                signature = (item.source, item.kind, repr(sorted(item.payload.items())))
                if signature in seen:
                    continue
                seen.add(signature)
                combined.append(item)
                if len(combined) >= self.max_observations:
                    return tuple(combined)
        return tuple(combined)
