# Claude review handoff — Jarvis gap staging

This is **non-production ChatGPT-authored code** on
`chatgpt/jarvis-gap-build-20260830`. Per `CLAUDE.md`, it requires Claude
line-by-line review before anything is considered for integration.

## Review scope

Review only `staging/jarvis_gap/` and `staging/__init__.py`. The branch should
contain no production wiring at all.

Files with behavior:

- `mobile_sensors.py` — ephemeral camera/location contracts;
- `sensor_requests.py` — opaque expiring one-shot request binding;
- `vision.py` — provider-neutral read-only image reasoning contract;
- `camera_question.py` — isolated "What is this?" vertical slice;
- `desktop_context.py` — read-only Windows foreground/clipboard sensor;
- `visual_fallback.py` — proposal-only screenshot target locator;
- `tests/test_staging_gap.py` — hermetic contract tests.

## Invariants Claude should try to break

1. **No production reachability.** Nothing under `aletheia/`, `interface/`,
   `config/`, `scripts/`, Core routes, intercom kinds, or registries imports or
   calls this staging package.
2. **No image persistence.** Camera/screenshot bytes are not written, journaled,
   serialized in metadata, or exposed by repr.
3. **No sensor cross-talk.** One request cannot consume another request's camera
   frame/location; token replay fails after consumption/expiry.
4. **No ambient precise location.** Diagnostic metadata omits lat/lon. Exact
   coordinates only enter the one reasoning call for a request that asked for
   location.
5. **No ambient clipboard disclosure.** Diagnostics hash it. Text reaches a
   reasoning context only through `include_clipboard=True`.
6. **VISION cannot act.** Its accepted output is only answer/confidence/basis.
   Visual target output is a proposal with `execution_authority: false`.
7. **Visual fallback cannot bypass UIA.** There is no connection to
   `computer.execute`; any future connection must be separately policy-reviewed.
8. **No new auth surface.** Sensor tickets are request correlation, not remote
   authentication. Future endpoints must sit behind existing `aletheia.access`.
9. **No fake iOS notification capability.** The audit explicitly leaves generic
   cross-app notification reading unbuilt.

## Local staging evidence before handoff

Run from repository root:

```text
python -m unittest discover -s staging/jarvis_gap/tests -t . -v
python -m compileall -q staging
```

ChatGPT's isolated run after the second build pass: **24 tests passed** plus
compileall. This is not a substitute for the repository's normal full suite or a
Windows live test of `WindowsContextBackend`.

## Decisions still required before integration

- Which provider(s) advertise `VISION`? Prefer local/subscription-backed options
  consistent with Playbook §6; do not make one vendor architectural.
- Is camera a one-question/one-frame interaction only, or may an explicitly
  started session stream several frames? This staging code intentionally chooses
  the smaller one-shot authority surface.
- Which remote-access scope is allowed to upload sensor data? Existing `read`
  and `full` may be too broad; if a `sensor` scope is proposed, review it as an
  auth-policy change rather than sneaking it in with camera wiring.
- How should current browser tab / selected file be resolved without fragile
  title parsing? Keep those gaps named until a real provider exists.

Do not merge the staging directory as a feature merely because tests are green.
First ratify the contracts, then port the approved pieces into production in a
small vertical slice with registry truth and live evidence.
