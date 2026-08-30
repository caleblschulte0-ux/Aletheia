# ChatGPT staging — Aletheia reasoning gateway integration seam

Branch: `chatgpt/local-ai-brain-v1`
PR: #48 (draft / DO NOT MERGE without review)

This document is the shortest review path for integrating the local model pool
into canonical Aletheia later. The implementation remains isolated on the
ChatGPT staging branch today.

## The stable seam

Canonical Aletheia should not know about Ollama, Qwen model names, thinking
flags, training file paths, or fast/deep failover. It should know one interface:

```python
from aletheia import reasoning_gateway

output = reasoning_gateway.interpret(operator_text, context)
```

`interpret()` returns the exact existing `aletheia.brain` validated output
shape. No wrapper is required by canonical callers.

For UI/observability/feedback callers:

```python
result = reasoning_gateway.interpret_with_meta(operator_text, context)
```

That additionally exposes:

- selected role (`fast`, `deep`, or `fallback`)
- route reason
- actual model name
- thinking mode
- future-training `turn_id`
- validated brain output

## Current staging provider stack

- `fast` -> `qwen3:8b`, think=false
- `deep` -> `qwen3.6:27b`, think=true
- auto routing is deterministic
- selected local role may fail over once to the other local role
- both local roles failing -> canonical deterministic `brain.FALLBACK`

The role/model mapping is machine-local configuration. These model names are
not architectural dependencies.

## Exact canonical seam found on main

At review time, canonical `aletheia/assistant.py` currently imports `brain` and
its `interpret` branch ends with:

```python
if args.cmd == "interpret":
    return _print(brain.FALLBACK.run(args.text))
```

After Claude reviews/adopts the staging modules, the smallest possible caller
change is conceptually:

```diff
-from aletheia import (..., brain, ...)
+from aletheia import (..., brain, reasoning_gateway, ...)

 if args.cmd == "interpret":
-    return _print(brain.FALLBACK.run(args.text))
+    return _print(reasoning_gateway.interpret(args.text))
```

That is intentionally the whole canonical integration seam for v1.

Do not apply this diff blindly. Claude should first review/rebase the staging
modules against current main, run the full suite, and decide how canonical
context should be supplied.

## Training-data loop

Every successful local role run records a stable `turn_id`. Rich callers receive
that id from `interpret_with_meta()` and can attach operator feedback through:

```python
reasoning_gateway.feedback(
    turn_id,
    verdict="good",  # good | bad | mixed | corrected
    note="optional operator note",
)
```

The gateway also exposes:

```python
reasoning_gateway.training_status()
reasoning_gateway.export_training(path)
```

Data remains machine-local by default and is not committed to Git.

## Why this is an integration layer instead of an Ollama integration

Aletheia talks to `reasoning_gateway`.

`reasoning_gateway` talks to the provider/routing layer.

Today that layer happens to use Ollama + Qwen. Tomorrow it can use a different
local model, another runtime, a trained Aletheia model, or a cloud escalation
provider without changing canonical assistant semantics.

Target architecture:

```text
canonical Aletheia
      |
      v
reasoning_gateway
      |
      +--> fast local provider
      +--> deep local provider
      +--> future providers
      `--> deterministic fallback
      |
      v
existing brain output contract
      |
      v
existing deterministic planning / policy / approvals / execution
```

## Authority boundary

The gateway is reasoning only. It does not:

- execute a command
- run shell actions
- browse
- send communications
- mutate canonical state
- approve an action
- widen a capability or authority grant

Model output must still pass the existing `brain.validate_output()` contract.
World-touching behavior remains downstream of Aletheia's deterministic gates.

## Claude review checklist

1. Rebase/cherry-pick the staging modules against current main rather than
   merging the old branch wholesale.
2. Review `reasoning_gateway.py` first; this is the intended canonical API.
3. Review `local_model_pool.py` as a replaceable provider implementation.
4. Confirm the fast/deep routing thresholds are acceptable for v1.
5. Decide what canonical context (if any) `assistant interpret` should supply.
6. Review secret/PII redaction before broad automatic context capture.
7. Keep exact training provenance and `turn_id` behavior.
8. Run full CI plus a live Windows/Ollama smoke test.
9. Only then make the tiny canonical caller change.

## Files that define this seam

- `aletheia/reasoning_gateway.py` — stable Aletheia-facing API
- `aletheia/local_model_pool.py` — two-tier provider/routing implementation
- `aletheia/local_brain.py` — Ollama transport + brain-contract adapter
- `aletheia/model_pool_config.py` — replaceable role/model configuration
- `aletheia/training_data.py` — local future-model dataset
- `aletheia/local_ai_bridge.py` — CLI smoke-test surface on TOP of the gateway
- `tests/test_reasoning_gateway.py` — integration-contract tests

Nothing in this document authorizes merging PR #48.
