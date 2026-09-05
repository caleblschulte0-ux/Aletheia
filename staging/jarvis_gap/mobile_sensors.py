"""Ephemeral mobile/physical sensor contracts for future Aletheia integration.

This module is intentionally NOT connected to the Core, mobile page, capability
registry, memory, event bus, or any network listener. It prototypes the missing
Playbook §49/§86/§92 primitives: phone camera and location as permissioned
sensors.

Privacy boundary:
- camera bytes live in memory only;
- camera reads are consume-once by default;
- no file/network/repo persistence exists here;
- location requires an explicit consent marker and a fresh timestamp;
- metadata exposed to logs/contexts never includes image bytes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import threading
from dataclasses import dataclass, field

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
DEFAULT_TTL_S = 120.0
MAX_LOCATION_AGE_S = 300.0
MAX_ACCURACY_M = 50_000.0
MAX_FUTURE_SKEW = 10.0


def _utc(value: dt.datetime) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _valid_image_signature(data: bytes, media_type: str) -> bool:
    if media_type == "image/jpeg":
        return len(data) >= 3 and data[:3] == b"\xff\xd8\xff"
    if media_type == "image/png":
        return len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n"
    if media_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


@dataclass(frozen=True)
class ImageObservation:
    data: bytes = field(repr=False)
    media_type: str
    observed_at: dt.datetime
    source: str = "iphone.camera"

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("image data must be non-empty bytes")
        if len(self.data) > MAX_IMAGE_BYTES:
            raise ValueError(f"image exceeds {MAX_IMAGE_BYTES} bytes")
        if self.media_type not in ALLOWED_MEDIA_TYPES:
            raise ValueError(f"unsupported image media type {self.media_type!r}")
        if not _valid_image_signature(self.data, self.media_type):
            raise ValueError("image bytes do not match the declared media type")
        if self.source not in {"iphone.camera", "windows.screenshot"}:
            raise ValueError("unsupported image source")
        _utc(self.observed_at)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def metadata(self) -> dict:
        return {
            "source": self.source,
            "media_type": self.media_type,
            "observed_at": _utc(self.observed_at).isoformat(),
            "size_bytes": len(self.data),
            "sha256": self.digest,
        }


def validate_location(packet: dict, *, now: dt.datetime | None = None,
                      max_age_s: float = MAX_LOCATION_AGE_S) -> dict:
    """Validate one permissioned geolocation observation.

    The contract deliberately carries consent and accuracy. A coordinate with no
    provenance is not a trustworthy statement of where the operator is.
    """
    if not isinstance(packet, dict):
        raise ValueError("location packet must be an object")
    allowed = {"version", "source", "observed_at", "lat", "lon", "accuracy_m", "consent"}
    unknown = set(packet) - allowed
    if unknown:
        raise ValueError(f"location packet has unknown fields {sorted(unknown)}")
    if packet.get("version") != 1:
        raise ValueError("location packet version must be 1")
    if packet.get("source") not in {"iphone.geolocation", "browser.geolocation"}:
        raise ValueError("location source is not accepted")
    if packet.get("consent") is not True:
        raise PermissionError("location requires explicit operator/browser consent")
    for key in ("lat", "lon", "accuracy_m"):
        value = packet.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{key} must be a finite number")
    lat, lon, accuracy = float(packet["lat"]), float(packet["lon"]), float(packet["accuracy_m"])
    if not -90 <= lat <= 90:
        raise ValueError("lat must be -90..90")
    if not -180 <= lon <= 180:
        raise ValueError("lon must be -180..180")
    if not 0 <= accuracy <= MAX_ACCURACY_M:
        raise ValueError(f"accuracy_m must be 0..{MAX_ACCURACY_M:g}")
    try:
        observed = dt.datetime.fromisoformat(str(packet.get("observed_at", "")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be ISO-8601") from exc
    observed = _utc(observed)
    now = _utc(now or dt.datetime.now(dt.timezone.utc))
    age = (now - observed).total_seconds()
    if age < -MAX_FUTURE_SKEW:
        raise ValueError("location observation is implausibly in the future")
    if age > max_age_s:
        raise ValueError(f"location observation is stale ({age:.0f}s old)")
    return {
        "version": 1,
        "source": packet["source"],
        "observed_at": observed.isoformat(),
        "lat": lat,
        "lon": lon,
        "accuracy_m": accuracy,
        "consent": True,
    }


def location_metadata(value: dict | None) -> dict | None:
    """Privacy-safe presence metadata; precise coordinates are intentionally omitted."""
    if value is None:
        return None
    return {
        "version": value.get("version"),
        "source": value.get("source"),
        "observed_at": value.get("observed_at"),
        "accuracy_m": value.get("accuracy_m"),
        "consent": value.get("consent") is True,
        "present": True,
    }


class EphemeralSensorBuffer:
    """Small in-memory handoff point for future mobile sensor endpoints.

    Camera data is never returned by `snapshot()`. A reasoning caller must use
    `consume_camera()`, which removes the bytes immediately. A fresh unconsumed
    frame is not silently overwritten: cross-request camera mixups are worse than
    making the next capture retry.
    """

    def __init__(self, ttl_s: float = DEFAULT_TTL_S, *, clock=None) -> None:
        if not 1 <= float(ttl_s) <= 3600:
            raise ValueError("ttl_s must be 1..3600")
        self.ttl_s = float(ttl_s)
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._lock = threading.Lock()
        self._camera: ImageObservation | None = None
        self._location: dict | None = None

    def _age(self, observed_at: dt.datetime) -> float:
        return (_utc(self._clock()) - _utc(observed_at)).total_seconds()

    def _fresh(self, observed_at: dt.datetime) -> bool:
        age = self._age(observed_at)
        return -MAX_FUTURE_SKEW <= age <= self.ttl_s

    def put_camera(self, image: ImageObservation, *, replace: bool = False) -> dict:
        if not isinstance(image, ImageObservation):
            raise TypeError("image must be ImageObservation")
        age = self._age(image.observed_at)
        if age < -MAX_FUTURE_SKEW:
            raise ValueError("camera observation is implausibly in the future")
        if age > self.ttl_s:
            raise ValueError(f"camera observation is stale ({age:.0f}s old)")
        with self._lock:
            if self._camera is not None and self._fresh(self._camera.observed_at) and not replace:
                raise RuntimeError("a fresh unconsumed camera frame already exists")
            self._camera = image
        return image.metadata()

    def put_location(self, packet: dict) -> dict:
        value = validate_location(packet, now=self._clock(), max_age_s=self.ttl_s)
        with self._lock:
            self._location = value
        return dict(value)

    def consume_camera(self) -> ImageObservation | None:
        with self._lock:
            image, self._camera = self._camera, None
        if image is None or not self._fresh(image.observed_at):
            return None
        return image

    def latest_location(self) -> dict | None:
        with self._lock:
            value = None if self._location is None else dict(self._location)
        if value is None:
            return None
        observed = dt.datetime.fromisoformat(value["observed_at"])
        if not self._fresh(observed):
            return None
        return value

    def snapshot(self) -> dict:
        """Metadata-only state safe for diagnostics; never camera bytes."""
        with self._lock:
            image = self._camera
        camera = image.metadata() if image is not None and self._fresh(image.observed_at) else None
        return {"camera": camera, "location": location_metadata(self.latest_location())}
