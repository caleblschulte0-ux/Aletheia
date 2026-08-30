# ChatGPT handoff — local AI brain prototype

Branch: `chatgpt/local-ai-brain-v1`

This branch is intentionally isolated from `main`. The operator explicitly asked
ChatGPT to build the local-AI integration off to the side in its own area so it
can be reviewed later. Do not interpret the existence of this branch as approval
to merge it.

## Why this exists

Aletheia already has a clean model-independent contract in `aletheia/brain.py`.
The missing piece was a real local provider. This prototype fills that socket
without changing the canonical runtime.

## ChatGPT-authored files

- `aletheia/local_brain.py`
  - loopback-only Ollama adapter;
  - default model `qwen3:8b`;
  - calls `/api/chat` with a JSON schema and temperature 0;
  - output still passes through `aletheia.brain.Provider.run()` and
    `brain.validate_output()`;
  - `run_auto()` fails closed to the existing deterministic provider;
  - read-only `/api/tags` health/status check.

- `aletheia/brain_router.py`
  - isolated CLI proving local-first routing without editing `assistant.py`;
  - modes: `auto`, `local`, `fallback`;
  - optional JSON context file;
  - no action/tool execution.

- `scripts/setup-local-ai.ps1`
  - Windows bootstrap for Ollama;
  - pulls the configured model;
  - verifies the loopback API.

- `tests/test_local_brain.py`
  - mocked socket tests for structured output, fail-closed behavior, status,
    context bounds, and loopback enforcement.

- `tests/test_brain_router.py`
  - routing behavior tests.

- `docs/LOCAL_AI.md`
  - operator/setup/security documentation.

## Files deliberately NOT modified

- `aletheia/brain.py`
- `aletheia/assistant.py`
- `aletheia/act.py`
- command registry / intercom contracts
- approval or authority code
- workflows
- `main`

## Review questions for Claude

1. Does the JSON schema in `local_brain.py` accurately represent the canonical
   brain contract, or should schema ownership move into `brain.py`?
2. Is loopback-only Ollama the correct trust boundary for the first local brain?
3. Should canonical `assistant interpret` become local-first after review, or
   should routing live in a dedicated provider manager?
4. What canonical context should be supplied to the model by default? The
   prototype deliberately accepts only explicitly supplied context.
5. Should provider availability/status become a first-class Aletheia vital?
6. Are there additional prompt-injection boundaries needed before canonical
   state documents are passed as untrusted context?
7. Which model should be the first supported default after hardware profiling?
   `qwen3:8b` is only a conservative bootstrap choice, not an architectural lock.

## Suggested canonical integration after review

Keep the architecture:

```
operator/input
  -> provider router
      -> local model (first)
      -> optional cloud provider(s) when explicitly configured/available
      -> deterministic fallback
  -> canonical brain output validator
  -> deterministic planner/intercom validation
  -> policy + approvals
  -> tool/provider execution
  -> evidence + receipt
```

Do not give the local model direct shell/browser/email/GitHub execution rights.
The point of the local layer is continuity of reasoning when cloud models are
unavailable, not expansion of model authority.

## Merge policy

Review, modify freely, cherry-pick selectively, or discard. Nothing on this
branch is operator-approved for `main` merely because ChatGPT authored it.
