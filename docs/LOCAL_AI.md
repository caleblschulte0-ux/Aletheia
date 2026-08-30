# Local AI rollout

Aletheia owns policy, tools, state, approvals, and execution. Ollama models are
replaceable reasoning workers only. They never receive tool authority.

## Safe defaults

- Local routing is **disabled** after install or merge.
- Background student/shadow runs are **disabled** after activation.
- Critical and autonomous-code answers remain subscription-authoritative.
- Ollama is accepted only over plain HTTP on a loopback address.
- Training/evaluation records stay under gitignored `state/private/training`.
- Capture stops before 512 MiB by default; it never deletes older examples.

## Activate on the Windows operator PC

After the reviewed change is on `main` and the PC checkout is current:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\activate_local_ai.ps1
```

The script refuses non-`main` branches. `activate` checks that Ollama is online,
both configured model tags exist, and both models return the exact bounded JSON
smoke-test schema. A failed test leaves routing disabled.

Inspect or roll back without changing Git:

```powershell
python -m aletheia.local_ai status
python -m aletheia.local_ai deactivate
```

If an installed Ollama tag differs from the default, change the machine-local
role and run activation again:

```powershell
python -m aletheia.local_ai set-model fast qwen3:8b --no-think
python -m aletheia.local_ai set-model deep qwen3.6:27b --think
python -m aletheia.local_ai activate
```

Background comparison is an explicit later choice:

```powershell
python -m aletheia.local_ai shadow on
python -m aletheia.local_ai shadow off
```

## Routing and time budgets

- Routine screen, scheduling-reply, and advisor interpretation: one selected
  local role gets at most 15 seconds, with no second local attempt; the remaining
  route budget goes to the subscription chain.
- Standard planning: subscriptions get the first bounded slice; if they fail,
  the local deep role gets the remaining route budget, with no second local
  attempt.
- Critical/code work: subscriptions are required for the returned answer.
- Claude and the ChatGPT browser share one subscription timeout instead of each
  receiving a fresh full timeout.

These limits keep a sick Ollama process or an unavailable cloud route from
silently stacking several minute-long waits.
