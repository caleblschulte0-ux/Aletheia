"""A real audio backend — Phase 11's missing half.

`audio_router.py` has been a complete control plane since the systems
layer: plans, hash-bound approvals, exact-fingerprint verification,
sessions, halt checks. It shipped with exactly one backend,
`InMemoryAudioBackend`, whose docstring says what it is — "a deterministic
fake used only for hermetic tests". So `audio.route` sat EXPERIMENTAL with
an honest note: *no real Windows audio device has ever been routed*.

This is the device that gets routed. Each approved route opens a real
input stream on the source endpoint and a real output stream on the sink,
and pumps frames between them through a bounded ring. Nothing is written
to disk, nothing is transcribed, and no buffer outlives the session — a
router moves audio, it does not keep it.

**Verification is frames, not intent.** `audio_router.activate` refuses
any observation that does not name the exact approved route fingerprints,
and this backend only reports a route active once samples have actually
crossed it. A stream that opened and then went silent — a device stolen
by another app, a Bluetooth headset that wandered off — reads as inactive
on the next `observe`, which is the whole point of §30: the operator
learns that the bridge is dead from the bridge, not from a call going
strangely quiet.

No virtual audio cable is required, and that is deliberate. The obvious
Phase 12 design routes a call through VB-CABLE or VoiceMeeter, both of
which are kernel-mode drivers someone has to install with admin rights.
On this machine the Bluetooth Hands-Free endpoints Windows creates for
the operator's paired iPhone are already real input and output devices,
so the bridge is a route between two endpoints that exist rather than a
driver to install. If he later installs a virtual cable, its endpoints
enumerate here like any other and nothing in this module changes.
"""
from __future__ import annotations

import threading
import time

SAMPLE_RATE = 16000          # HFP call audio is narrowband; this is generous
BLOCK_FRAMES = 320           # 20ms at 16kHz — telephony's usual packet
CHANNELS = 1
QUEUE_BLOCKS = 25            # ~half a second of slack, then oldest is dropped
# A route must move at least this many frames since the last observation to
# count as live. One block is enough: the question is "is audio moving",
# not "how much".
LIVE_FRAMES = BLOCK_FRAMES


class AudioDeviceError(RuntimeError):
    """A real device could not be opened. Never silently degraded."""


def _sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:  # honest degradation (§106)
        raise AudioDeviceError(
            "sounddevice is not installed — `pip install -r requirements-optional.txt`"
        ) from exc
    return sd


def inventory() -> list[dict]:
    """Real endpoints, from the real device list."""
    from aletheia import audio_router
    return audio_router.sounddevice_inventory()


def resolve_device(endpoint: dict) -> int:
    """The device index this endpoint names, or raise.

    An endpoint may pin `device_index` outright. Otherwise its label is
    matched against the live device list — because indices move when a
    headset connects, and a plan that silently routes to whatever is at
    index 11 today is worse than one that refuses.
    """
    devices = inventory()
    by_index = {d["device_index"]: d for d in devices}
    wants_input = endpoint["kind"].endswith("input")

    if "device_index" in endpoint:
        found = by_index.get(endpoint["device_index"])
        if found is None:
            raise AudioDeviceError(
                f"endpoint {endpoint['id']!r} pins device_index "
                f"{endpoint['device_index']}, which no longer exists")
        return _checked(found, endpoint, wants_input)

    label = endpoint["label"].casefold()
    matches = [d for d in devices
               if label in d["name"].casefold()
               and (d["input_channels"] if wants_input else d["output_channels"]) > 0]
    if not matches:
        raise AudioDeviceError(
            f"no {'input' if wants_input else 'output'} device matches endpoint "
            f"{endpoint['id']!r} ({endpoint['label']!r})")
    if len({d["name"] for d in matches}) > 1:
        names = ", ".join(sorted({d["name"] for d in matches})[:4])
        raise AudioDeviceError(
            f"endpoint {endpoint['id']!r} ({endpoint['label']!r}) is ambiguous: "
            f"{names} — pin device_index in the plan rather than guessing")
    return _checked(matches[0], endpoint, wants_input)


def _checked(device: dict, endpoint: dict, wants_input: bool) -> int:
    channels = device["input_channels"] if wants_input else device["output_channels"]
    if channels <= 0:
        raise AudioDeviceError(
            f"endpoint {endpoint['id']!r} wants "
            f"{'input' if wants_input else 'output'} but device "
            f"{device['name']!r} has none")
    return device["device_index"]


class _Route:
    """One live source -> sink bridge, and the frame counters that prove it."""

    def __init__(self, fingerprint: str, source_index: int, sink_index: int,
                 samplerate: int = SAMPLE_RATE):
        self.fingerprint = fingerprint
        self.source_index = source_index
        self.sink_index = sink_index
        self.samplerate = samplerate
        self._blocks: list = []
        self._lock = threading.Lock()
        self._frames_in = 0
        self._frames_out = 0
        self._reported_at = 0
        self._error: str | None = None
        self._in_stream = None
        self._out_stream = None

    # --- the audio thread's two callbacks. Both must be cheap and must
    # --- never raise: an exception here kills the PortAudio stream.
    def _on_input(self, indata, frames, time_info, status):
        try:
            with self._lock:
                if len(self._blocks) >= QUEUE_BLOCKS:
                    self._blocks.pop(0)  # drop the oldest: latency beats backlog
                self._blocks.append(bytes(indata))
                self._frames_in += frames
        except Exception as exc:
            self._error = f"input: {type(exc).__name__}: {exc}"

    def _on_output(self, outdata, frames, time_info, status):
        try:
            with self._lock:
                block = self._blocks.pop(0) if self._blocks else None
                if block is not None:
                    self._frames_out += frames
            if block is None or len(block) != len(outdata):
                outdata[:] = b"\x00" * len(outdata)  # silence, never stale audio
            else:
                outdata[:] = block
        except Exception as exc:
            self._error = f"output: {type(exc).__name__}: {exc}"
            try:
                outdata[:] = b"\x00" * len(outdata)
            except Exception:
                pass

    def start(self) -> None:
        sd = _sounddevice()
        try:
            self._in_stream = sd.RawInputStream(
                samplerate=self.samplerate, blocksize=BLOCK_FRAMES,
                device=self.source_index, channels=CHANNELS, dtype="int16",
                callback=self._on_input)
            self._out_stream = sd.RawOutputStream(
                samplerate=self.samplerate, blocksize=BLOCK_FRAMES,
                device=self.sink_index, channels=CHANNELS, dtype="int16",
                callback=self._on_output)
            self._in_stream.start()
            self._out_stream.start()
        except Exception as exc:
            self.stop()
            raise AudioDeviceError(
                f"could not open {self.source_index} -> {self.sink_index}: "
                f"{type(exc).__name__}: {exc}") from exc

    def live(self) -> bool:
        """Have frames crossed this route since the last time we asked?"""
        with self._lock:
            moved = self._frames_in - self._reported_at
            self._reported_at = self._frames_in
        streams_up = bool(self._in_stream and self._out_stream
                          and self._in_stream.active and self._out_stream.active)
        return streams_up and self._error is None and moved >= LIVE_FRAMES

    def detail(self) -> str:
        with self._lock:
            return (self._error or
                    f"in={self._frames_in} out={self._frames_out} frames")

    def stop(self) -> None:
        for stream in (self._in_stream, self._out_stream):
            try:
                if stream is not None:
                    stream.stop()
                    stream.close()
            except Exception:
                pass  # stopping is cleanup; it may not fail its way out of here
        self._in_stream = self._out_stream = None
        with self._lock:
            self._blocks.clear()  # no audio outlives the session


class WindowsAudioBackend:
    """An `audio_router.AudioBackend` that moves real samples.

    Satisfies the protocol exactly: start(plan) / observe(handle) /
    stop(handle), returning only the four fields the router's bounded
    observation permits. It never decides what may run — the plan is
    already approved and fingerprinted before it arrives here.
    """
    provider_id = "windows.sounddevice"

    def __init__(self, settle_s: float = 0.6, samplerate: int = SAMPLE_RATE):
        # A moment for the first blocks to cross before start() reports.
        # Without it a healthy route reads as dead in its own first breath.
        self.settle_s = settle_s
        self.samplerate = samplerate
        self._sessions: dict[str, list] = {}
        self._counter = 0

    def start(self, plan: dict) -> dict:
        from aletheia import audio_router
        by_id = {e["id"]: e for e in plan["endpoints"]}
        self._counter += 1
        handle = f"win-audio-{self._counter}"
        routes: list = []
        try:
            for spec in plan["routes"]:
                route = _Route(
                    audio_router.route_fingerprint(spec),
                    resolve_device(by_id[spec["source"]]),
                    resolve_device(by_id[spec["sink"]]),
                    samplerate=self.samplerate)
                route.start()
                routes.append(route)
        except Exception:
            for route in routes:
                route.stop()
            raise
        self._sessions[handle] = routes
        time.sleep(self.settle_s)
        return self._observation(handle)

    def observe(self, handle: str) -> dict:
        return self._observation(handle)

    def _observation(self, handle: str) -> dict:
        routes = self._sessions.get(handle)
        if routes is None:
            return {"handle": handle, "active": False, "routes": [],
                    "detail": "unknown handle"}
        live = [r.fingerprint for r in routes if r.live()]
        details = "; ".join(f"{r.fingerprint[:14]} {r.detail()}" for r in routes)
        return {"handle": handle,
                # active only when EVERY approved route is moving audio: a
                # half-live bridge is a call with one deaf party
                "active": len(live) == len(routes) and bool(routes),
                "routes": sorted(live), "detail": details[:500]}

    def stop(self, handle: str) -> dict:
        for route in self._sessions.pop(handle, []):
            route.stop()
        return {"handle": handle, "active": False, "routes": [],
                "detail": "routes closed"}
