# Jarvis foundation V0 — isolated staging only

**DO NOT MERGE OR WIRE THIS PACKAGE INTO THE LIVE CORE YET.**

This directory is ChatGPT-owned staging work.  It does not import into
`aletheia.core`, does not register a capability, does not add an intercom
command, does not start a Windows service, does not touch the real browser,
does not read the microphone/camera, and does not write canonical memory.

The goal is to make the missing Jarvis architecture concrete enough for review
without giving experimental code any authority.

## What is built here

The staging loop has explicit seams for:

1. **observe** — bounded sensor observations,
2. **recall** — bounded relevant memory,
3. **understand** — operator utterance -> explicit intent,
4. **plan** — typed capability steps with risk and expected evidence,
5. **authorize** — approve/refuse the *exact whole plan*,
6. **act** — one approved step at a time,
7. **verify** — prove each requested effect before continuing,
8. **remember** — only verified turns may propose memory,
9. **speak** — optional output surface.

Supporting pieces include:

- a wake-word/follow-up conversation state machine with no microphone dependency;
- a perception hub that can later combine accessibility, browser, screen,
  notification, microphone, camera, and device observations;
- ephemeral memory to exercise retrieval and verified-episode capture;
- a health supervisor model for future always-on service wiring;
- fully hermetic fake adapters and a simulation demo.

Run the safe demo:

```powershell
python -m staging.jarvis_v0.demo
```

It prints `"simulated": true` and cannot touch the computer.

## Non-negotiable integration boundaries

Before any of this can reach production, a reviewer should map these staging
ports onto the authority boundaries that already exist in Aletheia:

- `AuthorityPort` must delegate to canonical policy/approval rules.
- `ActionPort` must delegate to registered capabilities or
  `aletheia.computer`; the model never gets a raw shell/UI handle.
- `VerificationPort` needs capability-specific evidence, not an LLM saying
  "looks good."
- `MemoryPort.commit` must respect canonical memory provenance and privacy.
- perception must prefer semantic/accessibility sources before pixels.
- camera/microphone/browser adapters need explicit privacy and retention rules.
- retries/replanning must remain bounded and may not silently widen authority.

## What this deliberately does *not* solve yet

- real wake-word engine, STT, TTS, microphone device selection;
- Windows Service / Task Scheduler installation;
- real UIA acceptance on the operator PC;
- browser interaction adapter;
- screen/camera vision;
- proactive watchers and event triggers;
- routing the live Qwen/Claude/ChatGPT reasoners into `ReasoningPort`;
- canonical long-term memory;
- self-replanning after failure;
- multi-device/phone/home hardware.

Those should be separate reviewed integrations, not one giant merge.
