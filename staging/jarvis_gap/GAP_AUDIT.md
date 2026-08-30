# Jarvis gap audit — build-only staging

Branch intent: **identify what Aletheia genuinely lacks before writing more architecture.**
Nothing in this directory is imported by `aletheia/`, registered in
`config/capabilities.json`, exposed by the Core, or enabled on the operator PC.

## Existing foundation — do not rebuild

Current `main` already has all of these:

- persistent/self-updating/supervised Core: `core.py`, `sync.py`, `supervisor.py`, `autostart.py`;
- real room voice: `voice_room.py`, `voice.py`, `voice_quality.py`, `speech.py`;
- Windows UI Automation control: `computer.py`;
- browser read + approval-gated interaction: `browse.py`, `browser_reasoner.py`;
- current-state, event bus, watchers, scheduler, attention, proactive judgment;
- goals, tasks, planner, orchestrator, director, verification/outcome records;
- structured memory + journal + context/situational state;
- phone/audio bridge, calendar, email, contacts, room/Home Assistant adapters;
- local Qwen reasoning pool and private training capture;
- mobile status/approval/task surface and TLS/token remote-access layer;
- capability-gap materialization (`gaps.py`) itself.

The older staging branch duplicated several of those concepts and should not be
used as the basis for new work.

## Genuine gaps found against the Playbook

### 1. Phone camera perception — missing

The Playbook explicitly names the iPhone as a camera/physical-world bridge
(§49, §86, §87, §92). `main` has no camera capability, no camera module, no
camera endpoint, and the mobile surface has no capture path. Production
`perception.py` reads Windows UI Automation text; it is not physical camera
vision.

**Staging build:** `mobile_sensors.py` defines ephemeral image observations.
Image bytes are memory-only, MIME/signature checked, hidden from repr/metadata,
and consume-once. `sensor_requests.py` adds one-shot request tokens so two
simultaneous camera questions cannot consume each other's frame.

### 2. Location source — missing

The Playbook names iPhone location as context (§49/§92), but the capability
registry has no `location.read` and the mobile surface never calls browser
geolocation.

**Staging build:** `mobile_sensors.py` validates fresh, consent-bearing,
accuracy-bearing location packets. Exact coordinates are omitted from diagnostic
metadata and only enter a reasoning context when that request explicitly asked
for location.

### 3. VISION worker seam — missing

The Playbook defines `VISION` as an abstract worker role (§7). Today's local
reasoning adapter is text/JSON only, and screen perception deliberately uses the
accessibility tree instead of pixels. There is no provider-neutral image
reasoning seam.

**Staging build:** `vision.py` accepts an injected VISION backend and strictly
returns read-only answers. Action-shaped output is refused, context is
JSON-serializable and byte-bounded before the provider sees it, and every answer
is bound to the image sha256. `ollama_vision.py` now proves that seam can be made
concrete locally: it is loopback-only, tool-less, requires an explicit model
name (no assumption that the configured fast/deep text models are multimodal),
and honestly reports whether that model is actually pulled.

### 4. Visual computer fallback — missing by design

The Playbook adapter ladder includes visual computer control as rung 7 (§11,
§15). Production `computer.py` correctly refuses screen coordinates and
`perception.py` correctly stays read-only. No separate visual fallback exists
for canvas apps, games, remote desktops, or inaccessible controls.

**Staging build:** `visual_fallback.py` can only propose a point inside a
specific screenshot, hash-bound to that screenshot. It has **zero execution
authority** and is intentionally not wired to `computer.execute`.

### 5. Ambient Windows computer context — partially missing

Playbook §48 expects active window, foreground app, current tab, selected file,
clipboard and current project so phrases like "send this to Claude" have a
concrete referent. Production UIA can list windows and inspect controls, but the
canonical `current_state.py` does not carry foreground/clipboard context and
there is no ambient read-only foreground sensor.

**Staging build:** `desktop_context.py` provides a read-only ctypes Windows
backend for foreground title/process and Unicode clipboard. It has no ability to
focus, type, click, or mutate the clipboard. Diagnostic metadata hashes the
window title and clipboard rather than exposing their contents; reasoning must
explicitly request clipboard text.

This closes only the foreground-app/clipboard slice. Generic **current browser
tab**, **selected file**, and **current project** resolution remain open because
those need provider-specific semantics rather than title-string guessing.

## A complete isolated vertical slice now exists

`camera_question.py` joins the staging pieces for Playbook §87 without touching
the Core:

1. issue an opaque expiring request token for "What is this?";
2. accept only the sensor kinds that request named;
3. reject stale/replayed/cross-request frames;
4. verify the same question digest before consuming the capture;
5. disclose precise location only when location was requested;
6. call the read-only VISION seam;
7. return an answer bound to the exact image sha256.

It still has no HTTP endpoint, provider selection, mobile permission UI, memory
write, command path, or action authority. That is deliberate: the data and
trust boundaries can be reviewed before production wiring widens the surface.

## Important platform constraint: iPhone notifications

The Playbook also says selected phone notifications may become events (§49–50).
Do **not** implement a fake generic `iphone.notifications.read`: iOS does not
provide ordinary apps a supported API to inspect every other app's notification
center. The honest paths are provider-specific connectors/webhooks, explicit
Share Sheet/Shortcut forwarding where Apple permits it, or first-party events
from Aletheia's own mobile surface. The existing event bus can consume those
later; the missing piece is a legitimate source, not another event bus.

## Not code gaps

Do not build replacements for these. Their current blockers are configuration or
live evidence, not missing architecture:

- Home Assistant room scenes — needs operator token/config;
- calendar read/write — provider code exists; needs account authorization/live write evidence;
- remote iPhone access — TLS/token transport exists; needs operator setup;
- proactive advisor — built, opt-in by operator;
- phone call — built, first supervised call still required;
- purchase/reservation/cancellation errands — built, first live round-trips still required;
- agent delegation — dispatch built, live worker round-trip still required.

## Integration order if this staging work is accepted later

1. Claude line-by-line review of this branch; keep production untouched until the
   privacy/request-binding invariants are ratified.
2. Claude decides whether the staged local Ollama VISION backend is the first
   provider. It deliberately has no default model; choose and live-prove a
   multimodal model before registering it AVAILABLE.
3. Add registry entries for `perception.camera`, `location.read`,
   `computer.context.read`, and `vision.reason` only when real callers exist.
4. Add request-bound authenticated sensor endpoints behind the existing
   remote-access layer. Do not create a second authentication system.
5. Add the mobile capture/location permission controls. Camera bytes stay
   ephemeral/private; precise location is never journal payload.
6. Wire the **read-only** `What is this?` vertical slice first and live-verify it.
7. Separately wire foreground Windows context into context resolution; do not
   make clipboard contents ambient model context by default.
8. Only after those reads are proven, separately review visual desktop fallback.
   UIA/browser semantics stay higher priority; any coordinate action must get
   exact policy/approval, re-observe afterward, and verify before success.

That sequence extends Aletheia rather than building a second Aletheia beside it.
