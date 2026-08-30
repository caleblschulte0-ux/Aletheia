# Aletheia Local AI — isolated ChatGPT prototype

> Branch-only prototype. This work was intentionally authored on
> `chatgpt/local-ai-brain-v1`. It is not wired into `main` and does not replace
> the canonical assistant/runtime until reviewed.

## Two non-negotiable design rules

1. **Keep the learning data.** Every local reasoning attempt should create a
   durable, local training/evaluation example containing the input, exact model
   request payload, model/provider identity, validated result or failure, timing,
   and later operator feedback/corrections. This is how future Aletheia models
   get trained on Aletheia's actual work instead of starting from zero.
2. **The model is a cartridge, not the machine.** Changing from Qwen to Gemma,
   another Ollama model, or a future Aletheia-trained model must not require
   editing orchestration or policy code. The selected model lives in machine-
   local configuration and can be changed with one command.

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
    +--> selected local Ollama model
    |       |
    |       +--> aletheia.brain.validate_output --> proposal
    |       `--> local training/evaluation event retained
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

Choose another model during setup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local-ai.ps1 -Model "qwen3:14b"
```

The script installs Ollama if needed, pulls the selected model, saves the model
choice outside Git, checks the loopback API, and reports training-data status.

## Change models later — no code edit

Show the currently selected model:

```powershell
python -m aletheia.model_config show
```

Change it:

```powershell
ollama pull qwen3:14b
python -m aletheia.model_config set qwen3:14b
```

That is the intended model-swap boundary. `OllamaConfig.from_env()` resolves the
model using this precedence:

1. an explicit model passed by the caller;
2. `ALETHEIA_LOCAL_AI_MODEL` environment override;
3. the machine-local saved model;
4. bootstrap default `qwen3:8b`.

The saved choice lives outside the repository, under the user's local Aletheia
configuration directory. A model swap therefore creates no Git commit and does
not alter Aletheia policy, memory, plans, tools, or approvals.

## Use

Check the local socket/model and training capture:

```powershell
python -m aletheia.brain_router status
```

Interpret an operator sentence, local-first with deterministic fallback:

```powershell
python -m aletheia.brain_router interpret "What needs my attention?"
```

Force the local provider:

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

## Future-model training data

Training capture is **on by default** for local-model reasoning attempts. The
canonical events are intentionally stored outside Git:

- Windows: `%LOCALAPPDATA%\Aletheia\training`
- other systems: `~/.aletheia/training`

Each reasoning-turn event retains:

- timestamp and schema version;
- provider and exact model name;
- operator text;
- supplied context;
- **exact JSON request payload sent to Ollama**, including the historical system
  prompt and output schema;
- validated model result, or error type/message if the attempt failed;
- elapsed time.

Later feedback is stored as a separate append-only event linked by `turn_id`.
That lets the future dataset distinguish answers that were accepted, bad, mixed,
or explicitly corrected without rewriting the historical raw example.

Inspect retained data:

```powershell
python -m aletheia.training_cli status
```

Export a portable JSONL dataset when it is time to evaluate/fine-tune:

```powershell
python -m aletheia.training_cli export .\aletheia-training.jsonl
```

Attach feedback to a retained turn:

```powershell
python -m aletheia.training_cli feedback <turn-id> --verdict good
```

or attach a corrected brain-output object:

```powershell
python -m aletheia.training_cli feedback <turn-id> --verdict corrected --corrected-json .\corrected.json
```

Capture can be disabled for a session with `ALETHEIA_TRAINING_CAPTURE=0`, and the
storage location can be overridden with `ALETHEIA_TRAINING_DATA_DIR`. Capture
failures are fail-soft: a disk/logging problem does not block reasoning.

**Privacy boundary:** this dataset is meant to contain real personal Aletheia
context because that is what makes a future personal model useful. Therefore it
stays local by default and is never automatically committed, uploaded, or sent
to GitHub/cloud training services. Any future synchronization/encryption policy
must be an explicit separate design decision.

## Configuration

Optional environment variables:

```powershell
$env:ALETHEIA_LOCAL_AI_MODEL = "qwen3:8b"       # temporary model override
$env:ALETHEIA_LOCAL_AI_URL = "http://127.0.0.1:11434"
$env:ALETHEIA_LOCAL_AI_TIMEOUT = "90"
$env:ALETHEIA_TRAINING_CAPTURE = "1"
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
manufacture an executable command. Failed local attempts are still useful data
and are retained with an error label when capture is available.

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
python -m unittest tests.test_local_brain tests.test_brain_router tests.test_model_config tests.test_training_data
```

The tests mock the Ollama socket; CI does not need a downloaded model. They cover
structured output, contract rejection, offline/protocol fallback, training-event
retention, exact request capture, feedback/export, one-command model swapping,
environment overrides, loopback-only configuration, and context bounding.

## What is intentionally NOT done on this branch

- No modification to `aletheia/assistant.py`.
- No change to `aletheia/brain.py`.
- No replacement of Claude, ChatGPT, or any cloud workflow.
- No model download committed to Git (weights stay on the PC/Ollama store).
- No personal training dataset committed to Git.
- No merge to `main`.

Once reviewed, the smallest canonical integration is to make the existing
`assistant interpret` command select the local provider in `auto` mode while
retaining an explicit deterministic fallback option. The adapter, model config,
and training-data format should stay provider-neutral enough that a future
Aletheia-trained model can replace today's bootstrap model without rebuilding
the operating system around it.
