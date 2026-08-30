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

**Staging prototype:** `mobile_sensors.py` defines ephemeral camera observations
and consume-once in-memory retention. It does not add an endpoint.

### 2. Location source — missing

The Playbook names iPhone location as context (§49/§92), but the capability
registry has no `location.read` and the mobile surface never calls browser
geolocation.

**Staging prototype:** `mobile_sensors.py` defines a fresh, consent-bearing,
accuracy-bearing location packet. It does not request location permission or
persist coordinates.

### 3. VISION worker seam — missing

The Playbook defines `VISION` as an abstract worker role (§7). Today's local
reasoning adapter is text/JSON only, and screen perception deliberately uses the
accessibility tree instead of pixels. There is no provider-neutral image
reasoning seam.

**Staging prototype:** `vision.py` accepts an injected future VISION backend and
strictly returns read-only answers. Action-shaped output is refused.

### 4. Visual computer fallback — missing by design

The Playbook adapter ladder includes visual computer control as rung 7 (§11,
§15). Production `computer.py` correctly refuses screen coordinates and
`perception.py` correctly stays read-only. No separate visual fallback exists
for canvas apps, games, remote desktops, or inaccessible controls.

**Staging prototype:** `visual_fallback.py` can only propose a point inside a
specific screenshot, hash-bound to that screenshot. It has **zero execution
authority** and is intentionally not wired to `computer.execute`.

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

1. Review/choose the VISION provider strategy; do not hard-code a vendor.
2. Add registry entries for `perception.camera`, `location.read`, and
   `vision.reason` only when there are real callers and tests.
3. Add authenticated mobile sensor endpoints behind existing remote-access
   scopes; camera bytes remain ephemeral/private.
4. Add the mobile UI capture/permission controls.
5. Connect read-only camera questions (`What is this?`) first.
6. Only after that, separately review a visual desktop fallback. It must remain
   lower priority than UIA and browser semantics, require exact policy/approval,
   re-observe after action, and verify before reporting success.

That sequence extends Aletheia rather than building a second Aletheia beside it.
