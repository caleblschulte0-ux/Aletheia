# Aletheia single-front-door end state

Operator ruling: **Aletheia is the interface. AI vendors, local models, tools, apps, repos, devices, and services are workers/providers behind her.**

This is a product requirement, not a convenience feature.

## End-state user experience

When Aletheia is fully operational, the operator should not need to keep separate Claude, ChatGPT, Qwen, GitHub, or other worker/provider interfaces open in order to get normal work done.

The operator talks to **Aletheia**. Aletheia determines how the request should be fulfilled.

For any request, Aletheia should be able to:

1. understand the desired outcome;
2. resolve relevant memory, project state, and context;
3. decide whether deterministic code, a local model, a frontier model, a specialized skill, a tool, or multiple workers are appropriate;
4. route work to the best available provider(s) without requiring the operator to choose a vendor;
5. coordinate multi-worker work when useful;
6. observe and verify the result;
7. recover, retry, or reroute when a provider fails or is unavailable;
8. return one coherent result through Aletheia;
9. remember useful outcomes, corrections, and routing evidence for future work.

## Provider invisibility

Claude, OpenAI/ChatGPT/Codex, Qwen, future local models, and future specialist models are implementation details.

The normal interaction should be:

```text
operator
   |
   v
ALETHEIA
   |
   +--> local Qwen / specialist model
   +--> Claude
   +--> OpenAI / Codex
   +--> deterministic code
   +--> tools / connectors / apps / devices
   |
   v
ALETHEIA
   |
   v
operator
```

The operator may ask which worker was used, force a specific worker, or open a provider directly for debugging or unusual work, but that must be optional rather than required.

## Routing objective

Aletheia should choose workers based on the outcome required and available evidence, including capability, quality, task specialization, privacy, latency, cost, context availability, health, and confidence.

A local model should be preferred when it is sufficiently capable and offers an advantage such as privacy, specialization, low marginal cost, persistent operation, or deep familiarity with Aletheia. A frontier model should be used when its additional capability is likely to materially improve the outcome. The system should not route by brand loyalty.

Specialized Aletheia-trained skills may eventually outperform general frontier models on narrow recurring operator tasks. Those skills remain workers behind the same Aletheia interface.

## Acceptance test

Aletheia has reached this end state when a normal day can be run from Aletheia alone: the operator can ask for arbitrary work without deciding which model, app, repo, tab, tool, or workflow should handle it, and Aletheia can route, execute, verify, and report the result herself within the operator's authority and safety boundaries.

This document clarifies and extends the existing orchestration north star in `docs/PLAYBOOK.md` §§1, 4, 7 and the worker model in `docs/ARCHITECTURE.md`. If implementation choices conflict with this single-front-door requirement, the implementation should move toward this requirement rather than making provider selection part of the operator's normal workflow.
