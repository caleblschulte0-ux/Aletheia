# ChatGPT staging — two-tier local AI integration

Branch: `chatgpt/local-ai-brain-v1`
PR: draft review surface only; do not merge without operator + Claude review.

## Operator intent

Aletheia should be able to use the two local Ollama models already installed on the operator's PC without making either model a permanent architectural dependency.

Current intended roles:

| Role | Default model | Thinking | Purpose |
| --- | --- | --- | --- |
| `fast` | `qwen3:8b` | off | low-latency everyday interpretation/reasoning |
| `deep` | `qwen3.6:27b` | on | harder analysis, architecture, debugging, review, larger context |

These are defaults, not identities. The role-to-model mapping is stored outside Git and can be changed without modifying Aletheia code.

## What this staging integration adds

### `aletheia/model_pool_config.py`
Machine-local fast/deep profile configuration.

Examples:

```powershell
python -m aletheia.model_pool_config show
python -m aletheia.model_pool_config set-fast qwen3:8b --no-think
python -m aletheia.model_pool_config set-deep qwen3.6:27b --think
```

Changing either model is a configuration operation, not a code change.

### `aletheia/local_model_pool.py`
A two-tier Ollama reasoning pool that still produces the existing `aletheia.brain` contract.

Important properties:

- no direct tools or execution authority;
- fast and deep roles have independently swappable model names;
- fast defaults to `think=false`;
- deep defaults to `think=true`;
- deterministic auto routing is intentionally simple and reviewable;
- selected local role may fail over once to the other local role;
- if both local roles fail, the existing deterministic Aletheia fallback returns `clarify`;
- every attempt is retained through the existing branch-only training-data capture path, including the exact model request and failed/invalid proposals.

### `aletheia/local_ai_bridge.py`
A safe staging front door proving Aletheia-shaped callers can access the pool without editing canonical `aletheia/assistant.py`.

Examples:

```powershell
python -m aletheia.local_ai_bridge status
python -m aletheia.local_ai_bridge profiles
python -m aletheia.local_ai_bridge route "review the architecture"
python -m aletheia.local_ai_bridge ask --mode fast "Reply with only READY."
python -m aletheia.local_ai_bridge ask --mode deep "Review the architecture for hidden failure modes."
python -m aletheia.local_ai_bridge ask "What needs my attention?"
```

`route` performs no inference. `ask` returns route provenance plus the normal validated Aletheia brain output.

### `scripts/setup-local-ai-pool.ps1`
Idempotent-ish Windows bootstrap/check for both role models. It pulls the configured models, saves role configuration outside Git, then checks the staging bridge.

## Proposed canonical wiring for Claude to review

The smallest future integration is not to copy routing logic throughout Aletheia. Instead, add one provider-router seam near the existing `assistant interpret` path:

```text
operator input
  -> Aletheia context builder
  -> local provider router
       -> fast role (default)
       -> deep role (when warranted)
       -> optional cloud escalation later
       -> deterministic fallback
  -> existing brain output validation
  -> existing planners / capability checks / approvals
  -> tools only after deterministic authority gates
```

The model pool should remain a reasoning provider only. It should never acquire direct filesystem, browser, shell, messaging, purchasing, GitHub, or device authority.

## Routing policy intentionally kept conservative

The staging `auto` router selects `deep` only for obvious high-effort cues, long operator input, or large explicit context. Everything else goes `fast`.

Claude may replace this heuristic with a better deterministic complexity classifier, measured latency/quality policy, or explicit task metadata. The key contract is that *routing policy is separate from model identity*.

## Training-data requirement

Both roles use the branch's local training capture layer. The future dataset therefore records which role/model handled a turn and the exact request payload, output/error, timing, context, and later corrections/feedback.

This is important because future Aletheia models should be trainable on:

- good fast-model answers;
- good deep-model answers;
- cases where fast failed and deep succeeded;
- cases where both failed;
- invalid proposals rejected by deterministic validators;
- later operator/Claude corrections.

Do not automatically upload this dataset to GitHub or a cloud provider. It defaults to machine-local storage outside the repo.

## Review questions for Claude

1. Should canonical Aletheia expose exactly the role names `fast` and `deep`, or a more general provider-tier abstraction?
2. Is the current deterministic complexity heuristic acceptable for v1, or should canonical routing initially be explicit-only?
3. Should deep failure fall back to fast, or go directly to deterministic fallback for some error classes?
4. Which canonical context documents are safe/useful to pass into local models by default?
5. Should the local pool status become part of Aletheia's pulse/health system?
6. Should latency/token metrics be used later to learn routing decisions?
7. Before long-term deployment, where should the private training dataset be encrypted/backed up?

## Hard isolation boundary

This staging work does **not** modify canonical `aletheia/assistant.py`, `aletheia/brain.py`, action code, authority gates, intercom contracts, or `main`.

Claude can review, modify, cherry-pick, reimplement, or discard this entire seam without needing to unwind production behavior.
