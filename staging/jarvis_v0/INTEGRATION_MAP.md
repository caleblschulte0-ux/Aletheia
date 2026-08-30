# Proposed integration map — review only

This file maps staging ports to pieces that already exist in Aletheia.  It is not
an instruction to merge them wholesale.

| Jarvis staging seam | Existing Aletheia candidate | Integration rule |
|---|---|---|
| `PerceptionPort` | `aletheia.computer` inspection + screen/browser readers | Prefer semantic/UIA data; pixels are fallback evidence, not raw authority. |
| `ReasoningPort` | hybrid local/subscription reasoning gateway | Reasoner may emit typed intent/plan only; never receive tool handles. |
| `AuthorityPort` | canonical policy/approval system | Exact plan digest must be bound to approval; no staging authority store. |
| `ActionPort` | capability registry / `aletheia.computer` / intercom execution | Dispatch only named registered capabilities. |
| `VerificationPort` | new deterministic evidence adapters | A model cannot mark its own action successful. |
| `MemoryPort` | canonical memory/private stores/journal | Preserve provenance, privacy and existing storage rules. |
| `VoicePort` | current room/browser speech surface | STT/TTS/wake engine should be replaceable adapters. |
| `SupervisorModel` | local Core + future Windows supervisor | Service installation is a separate operator-approved integration. |
| `ProactiveEngine` | events/watchers/scheduler | It emits proposals/notifications first; authority remains unchanged. |

## Suggested integration sequence

1. **Catalog + plan validation only.** Wire no actions.
2. **Reasoning adapter.** Convert current reasoning output to typed `Intent`/`Plan`.
3. **Read-only perception.** UIA/browser/state observations only.
4. **Canonical authority adapter.** Exact plan approval, no execution yet.
5. **One harmless action capability + deterministic verification.**
6. **Expand computer/browser action set one capability at a time.**
7. **Canonical memory adapter for verified episodes.**
8. **Room runtime adapters:** local wake word, STT, TTS.
9. **Proactive engine:** events -> proposals/notifications, not autonomous writes.
10. **Windows supervisor/service** only after the loop has survived real acceptance.

Each step should be independently reversible and reviewable.
