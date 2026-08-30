# ChatGPT handoff — local AI brain prototype

Branch: `chatgpt/local-ai-brain-v1`
Draft review surface: PR #48 — **DO NOT MERGE without operator + Claude review**.

This branch is intentionally isolated from `main`. The operator explicitly asked
ChatGPT to build the local-AI integration off to the side in its own area so it
can be reviewed later. Do not interpret the existence of this branch as approval
to merge it.

## Operator requirements now locked into the prototype

1. **Retain real usage data so future Aletheia models can be trained/evaluated.**
   Local reasoning attempts are captured locally by default with exact model
   request payloads, outputs/errors, model identity, timing and append-only later
   feedback/corrections. This dataset is never automatically committed/uploaded.
2. **The local model must be easy to replace.** Model selection is machine-local
   configuration. A swap is intended to be one command (`python -m
   aletheia.model_config set <model>`) rather than a source-code change.

These are architectural constraints, not just bootstrap conveniences.

## Why this exists

Aletheia already has a clean model-independent contract in `aletheia/brain.py`.
The missing piece was a real local provider. This prototype fills that socket
without changing the canonical runtime.

## ChatGPT-authored files

- `aletheia/local_brain.py`
  - loopback-only Ollama adapter;
  - bootstrap default `qwen3:8b`, resolved through external model config;
  - calls `/api/chat` with JSON schema + temperature 0;
  - output passes through `aletheia.brain.Provider.run()` / canonical validation;
  - `run_auto()` fails closed to the existing deterministic provider;
  - captures successful and failed local turns through `training_data`;
  - read-only `/api/tags` health/status check including capture stats.

- `aletheia/model_config.py`
  - model cartridge/config boundary outside Git;
  - precedence: explicit caller > env override > saved local selection > default;
  - CLI `show` and `set` commands;
  - future Ollama model changes require no orchestration/policy edits.

- `aletheia/training_data.py`
  - local-only future-model dataset substrate;
  - one atomic JSON event per turn/feedback item;
  - preserves exact request payload sent to the model runtime;
  - records provider/model, input/context, validated result or failure and timing;
  - append-only good/bad/mixed/corrected feedback linked by `turn_id`;
  - exports portable JSONL;
  - capture defaults on but failures are fail-soft so logging cannot break Thea.

- `aletheia/training_cli.py`
  - `status`, `export`, and `feedback` operator utilities.

- `aletheia/brain_router.py`
  - isolated CLI proving local-first routing without editing `assistant.py`;
  - modes: `auto`, `local`, `fallback`;
  - optional JSON context file;
  - no action/tool execution.

- `scripts/setup-local-ai.ps1`
  - Windows bootstrap for Ollama;
  - optional `-Model` argument;
  - pulls + saves the chosen model outside Git;
  - verifies loopback API and reports training capture.

- tests
  - `tests/test_local_brain.py`
  - `tests/test_brain_router.py`
  - `tests/test_model_config.py`
  - `tests/test_training_data.py`

- `docs/LOCAL_AI.md`
  - operator/setup/security/training-data/model-swap documentation.

- `.github/workflows/chatgpt-local-ai.yml`
  - branch/PR-only compile + isolated unit-test definition.

## Local data boundaries

Default training store:

- Windows: `%LOCALAPPDATA%\Aletheia\training`
- non-Windows: `~/.aletheia/training`

Default local-model config:

- Windows: `%LOCALAPPDATA%\Aletheia\local-ai\config.json`
- non-Windows: `~/.aletheia/local-ai/config.json`

These paths are intentionally outside the Git working tree. The data can include
real personal context and should therefore remain private/local until a separate,
explicit encrypted backup/sync design is approved.

## Files deliberately NOT modified

- `aletheia/brain.py`
- `aletheia/assistant.py`
- `aletheia/act.py`
- command registry / intercom contracts
- approval or authority code
- canonical `main`

All implementation on this PR remains additive/islanded for review.

## Review questions for Claude

1. Does the JSON schema in `local_brain.py` accurately represent the canonical
   brain contract, or should schema ownership move into `brain.py`?
2. Is loopback-only Ollama the correct trust boundary for the first local brain?
3. Should canonical `assistant interpret` become local-first after review, or
   should routing live in a dedicated provider manager?
4. What canonical context should be supplied by default? The prototype accepts
   only explicitly supplied context, while retaining exactly what was sent.
5. Should provider availability + dataset stats become first-class Aletheia vitals?
6. Are additional prompt-injection/redaction boundaries needed before canonical
   state documents are passed to a model and retained in the private dataset?
7. Should the future training store be encrypted at rest using Aletheia's local
   DPAPI substrate before canonical integration?
8. How should later outcomes/receipts automatically label reasoning turns as
   successful/failed training examples without trusting the LLM's self-rating?
9. Which model should be first after real hardware profiling? `qwen3:8b` is only
   a bootstrap choice. The architecture explicitly treats the model as swappable.
10. When Aletheia eventually hosts its own fine-tuned model, keep the same provider
    boundary so that replacing Ollama/Qwen does not require rebuilding the OS.

## Suggested canonical integration after review

Keep the architecture:

```
operator/input
  -> provider router
      -> selected local model (first)
      -> optional cloud provider(s) when explicitly configured/available
      -> deterministic fallback
  -> canonical brain output validator
  -> deterministic planner/intercom validation
  -> policy + approvals
  -> tool/provider execution
  -> evidence + receipt
  -> outcome/feedback linkage into private training dataset
```

Do not give the local model direct shell/browser/email/GitHub execution rights.
The local layer is continuity of reasoning and data generation for a future
Aletheia model, not expansion of model authority.

## Validation note

The branch contains compile/unit-test workflow definitions, but connector-authored
branch commits have not automatically produced GitHub Actions runs. Do not call
this green CI until the tests are actually executed on a PC or Actions run.

## Merge policy

Review, modify freely, cherry-pick selectively, or discard. Nothing on this
branch is operator-approved for `main` merely because ChatGPT authored it.
