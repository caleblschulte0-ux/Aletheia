# Aletheia Local AI — isolated ChatGPT prototype

> Branch-only prototype. This work was intentionally authored on
> `chatgpt/local-ai-brain-v1`. It is not wired into `main` and does not replace
> the canonical assistant/runtime until reviewed.

## Goal

Give Aletheia an always-available local reasoning provider so a cloud-model
outage does not remove Aletheia's ability to interpret ordinary operator input.
The LLM remains a replaceable worker. Aletheia's deterministic state, planners,
approval gates, command validators, and execution layer remain authoritative.

The prototype path is:

```
operator text
    |
    v
aletheia.brain_router
    |
    +--> local Ollama model --> aletheia.brain.validate_output --> proposal
    |
    `--> if local model/socket/protocol/contract fails
         aletheia.brain.FALLBACK --> clarify (no guessed action)
```

No model output in this branch directly executes a tool or changes world state.

## Windows setup

From the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local-ai.ps1
```

The script:

1. installs Ollama with its official Windows installer if `ollama` is missing;
2. pulls the configured model (default `qwen3:8b`);
3. checks Ollama's loopback API;
4. prints the two commands below.

Ollama serves its local API on `http://127.0.0.1:11434` by default.

## Use

Check the local socket/model:

```powershell
python -m aletheia.brain_router status
```

Interpret an operator sentence, local-first with deterministic fallback:

```powershell
python -m aletheia.brain_router interpret "What needs my attention?"
```

Force the local provider (useful while testing; errors instead of fallback):

```powershell
python -m aletheia.brain_router interpret --provider local "Make a plan for this"
```

Force Aletheia's existing deterministic fallback:

```powershell
python -m aletheia.brain_router interpret --provider fallback "test"
```

Pass a bounded JSON object as reference context:

```powershell
python -m aletheia.brain_router interpret --context .\state\pulse\latest.json "Summarize the important part"
```

The context is explicitly labeled untrusted to the model and truncated before
submission if it exceeds the adapter's bound.

## Configuration

Optional environment variables:

```powershell
$env:ALETHEIA_LOCAL_AI_MODEL = "qwen3:8b"
$env:ALETHEIA_LOCAL_AI_URL = "http://127.0.0.1:11434"
$env:ALETHEIA_LOCAL_AI_TIMEOUT = "90"
```

The adapter intentionally refuses non-loopback URLs. This prototype is a local
brain, not a generic remote-model proxy. A future provider abstraction can add
cloud providers separately with explicit trust/configuration boundaries.

## Fail-closed behavior

`auto` mode falls back to `aletheia.brain.FALLBACK` if any of these occur:

- Ollama is not running;
- the request times out;
- the model is missing;
- Ollama returns malformed JSON;
- the model returns an object that violates Aletheia's existing brain contract;
- local configuration is invalid.

That fallback returns a `clarify` intent with zero confidence. It does not
manufacture an executable command.

## Security boundary

The local model can only produce the already-defined brain proposal shape.
It cannot, through this adapter:

- execute shell commands;
- browse;
- send email/messages;
- edit files;
- dispatch workflows;
- approve its own actions;
- mutate Aletheia state;
- claim a receipt exists.

Any future wiring into the canonical assistant must preserve the existing path:
model proposal -> deterministic validation/planning -> policy/approval gates ->
provider/tool -> evidence/receipt.

## Tests

Run:

```powershell
python -m unittest tests.test_local_brain
```

The tests mock the Ollama socket; CI does not need a downloaded model. They cover
valid structured output, contract rejection, offline fallback, protocol fallback,
health status, loopback-only configuration, and context bounding.

## What is intentionally NOT done on this branch

- No modification to `aletheia/assistant.py`.
- No change to `aletheia/brain.py`.
- No replacement of Claude, ChatGPT, or any cloud workflow.
- No model download committed to Git (weights stay on the PC/Ollama store).
- No merge to `main`.

Once reviewed, the smallest canonical integration is to make the existing
`assistant interpret` command select the local provider in `auto` mode while
retaining an explicit deterministic fallback option. The adapter itself should
remain replaceable so later Qwen/Gemma/custom Aletheia models can be swapped by
configuration rather than architecture changes.
