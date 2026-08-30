"""Health/supervision model for an eventual always-on Jarvis service.

No process management is performed here.  The class only models heartbeats and
restart recommendations so Windows-service wiring can be reviewed separately.
"""
from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass
class ComponentHealth:
    name: str
    critical: bool
    last_heartbeat: float | None = None
    failures: int = 0
    last_error: str | None = None

    def beat(self, *, now: float | None = None) -> None:
        self.last_heartbeat = time.monotonic() if now is None else now
        self.failures = 0
        self.last_error = None

    def fail(self, error: str) -> None:
        self.failures += 1
        self.last_error = error


class SupervisorModel:
    def __init__(self, *, stale_after_s: float = 30.0, restart_after_failures: int = 3) -> None:
        if stale_after_s <= 0 or restart_after_failures < 1:
            raise ValueError("invalid supervisor thresholds")
        self.stale_after_s = stale_after_s
        self.restart_after_failures = restart_after_failures
        self._components: dict[str, ComponentHealth] = {}

    def register(self, name: str, *, critical: bool) -> ComponentHealth:
        if not name.strip():
            raise ValueError("component name is required")
        if name in self._components:
            raise ValueError(f"component already registered: {name}")
        health = ComponentHealth(name=name, critical=critical)
        self._components[name] = health
        return health

    def snapshot(self, *, now: float | None = None) -> dict[str, dict]:
        now = time.monotonic() if now is None else now
        result: dict[str, dict] = {}
        for name, health in self._components.items():
            stale = (
                health.last_heartbeat is None
                or now - health.last_heartbeat > self.stale_after_s
            )
            result[name] = {
                "critical": health.critical,
                "stale": stale,
                "failures": health.failures,
                "last_error": health.last_error,
                "restart_recommended": (
                    health.critical
                    and (stale or health.failures >= self.restart_after_failures)
                ),
            }
        return result
