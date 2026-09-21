# Reasoning classes: who may think for what

His continuity brief (`docs/CONTINUITY_BRIEF.md`, Part I.1, 2026-09-16): a
subsystem asks for a CLASS of reasoning, not a company. The classes are the
gateway's policies (`aletheia/reasoning_gateway.py`, vocabulary in
`aletheia/work_states.py`):

| class | who answers | use it for |
|---|---|---|
| `routine` | her own model first; a subscription only if local cannot | boring, bounded, checkable decisions: pick a link, pick search queries, classify |
| `standard` | frontier first (Claude, then the ChatGPT browser); her own model when they are out | work where quality matters but a slower, plainer answer beats none |
| `critical` | frontier required; local may shadow, never answer | independent review, merges, anything where a weaker answer is worse than waiting |

Gateway entry points: `reason_json(policy=...)`, `thinker(policy)` (a drop-in for
the old `subscription_json` seam), `frontier_json` / `local_json` for a caller
that keeps its own sticky chain, `local_ready()`, `frontier_available()`,
`frontier_status()` (who could answer, and when a limit resets, without asking), and
`ALETHEIA_FRONTIER_OFF=1`, which makes every gateway frontier rung refuse (a
simulation for acceptance test A; it only ever removes ability).

`tests/test_reasoning_classes.py` walks the AST of `aletheia/` and fails when a
direct call to Claude/Codex/ChatGPT/her own model appears outside the gateway
and outside its allowlist. Add a row there AND here, with the reason, or route
the call through the gateway.

## Migrated in wave C1a

| caller | was | now | class |
|---|---|---|---|
| `agent_session.chain_think` | `reasoner._subscription_json_with_provider`, then `local_model_pool.run_json` | `reasoning_gateway.frontier_json`, then `reasoning_gateway.local_json` (sticky per session) | standard |
| `agent_session.local_think` | `local_model_pool.run_json`, rescue `reasoner.subscription_json` | `reasoning_gateway.local_json`, rescue `reason_json(policy="critical")` | routine |
| `browser_loop.model_decider` (default) | `reasoner.work_json` (the job-hunt chain) | `browser_loop.gateway_decide`: compact prompt at `routine` (own model first), escalates to `standard` with the full page when the answer is null, unsure, or not a target on the page | routine -> standard |
| `browser_route._think` / its deciders | `reasoner.subscription_json` | `model_decider()` (the gateway decider above) | routine -> standard |
| `research.run` | `reasoner.subscription_json` for both calls | plan queries `thinker("routine")`, cited report `thinker("standard")` | routine / standard |

## Still direct, on purpose (the allowlist)

| caller | class | why it is direct |
|---|---|---|
| `campaign._job_hunt_thinker`, `campaign._any_model_answers` | standard | the job hunt's own chain `work_json`: Claude -> Codex -> her own model with 6 GB free (his 2026-09-13 ruling) |
| `campaign._any_model_writes` | standard | essays walk every writer, Codex and her own model included (his 2026-09-12 ruling); the gateway has no text route |
| `job_fit.judge` | standard | job-hunt chain with a stricter local prompt; a verdict only her model made waits for his OK |
| `pursuit._gateway_think` | standard | the pursuit IS the job hunt: the gateway first, then the same Codex rung (`codex_json`) while Claude rests — the gateway carries no Codex — then her own model, and only when `local_allowed()` says there is memory for it (a starved model is a timeout, not an answer; measured live 2026-09-21) |
| `converse.answer`, `converse._from_my_own_model` | standard | conversation is prose, and the local rung DISCLOSES itself ("this answer is from my own model") |
| `compose.compose` | standard | document prose; no gateway text route and no own-model disclosure on a saved file yet (gap) |
| `webtask.run` | standard | the older selector loop, superseded by `browser_loop` whenever a start page is known (gap: route or retire) |
| `script.write_program` | standard | authors sandboxed programs; the script sandbox is frozen for this wave |
| `web_search_jobs._claude_search`, `_claude_ready`, `_codex_search` | critical | web search is a tool of the Claude/Codex CLIs; her own model cannot search |
| `eyes._ask_claude_about` | critical | reads a screenshot through the Claude CLI; no gateway vision route yet (gap: qwen3-vl) |
| `setup._claude_cli` | critical | a setup probe OF the Claude CLI itself, not reasoning |
| `current_state.thinking` | critical | is each frontier CLI even installed, for the brains line; a presence check, no prompt |
| `planner.compile` (`infer_or_fallback`) | standard | already the gateway: the frontier rung is `reasoning_gateway.frontier_json` with the whole grammar, and the local rung is `local_planner` through `reasoning_gateway.local_json` with a compact prompt (the 28.7 KB one timed out at 300 s) |
| `code_worker`, `self_diagnosis`, `project_merge` | critical (review/merge), routine (local investigation) | owned this wave by `claude/continuity-local-repair`, which moves code work onto the gateway and adds the bounded local repair tier |

## Local browser decisions on this laptop

Measured 2026-09-16 on his laptop (no GPU, Ollama `num_thread` 2), one real
decision on a 20-target clinic home page, goal "book an annual physical", through
the routine prompt (`browser_loop.compact_page`, about 1,000 characters, 290 prompt
tokens, 14 output tokens). Both models chose the right link ("Request an
appointment") and said they were sure.

| model | cold | warm | notes |
|---|---|---|---|
| `qwen3-vl:4b` | 58.8 s (42.4 s load, 14.0 s prompt, 2.2 s output) | 2.6 s | answers in `thinking`; `local_brain` already reads it there |
| `qwen3:8b` | not measured cold (it was already loaded) | 7.2 s (0.3 s prompt, 6.7 s output) | |
| `qwen3:8b` while another worker was using Ollama | 180-260 s | | Ollama serves one request at a time; the wait is the queue |

So a warm local decision costs 3-7 s, and the routine slice for one decision
(`browser_loop.LOCAL_DECIDE_S`, 40 s, capped by the gateway's 45 s routine total)
covers it; a cold load or a busy Ollama does not fit, and then the decision
escalates to the standard class (frontier first). With the frontier off as well,
a contended local model returns no decision and the loop stops at a named
boundary (`NO_WAY_FORWARD`) rather than guessing.

