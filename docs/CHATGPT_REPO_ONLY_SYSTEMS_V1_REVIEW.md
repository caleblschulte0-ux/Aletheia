# ChatGPT repo-only systems v1 — Claude review manifest

> **UNAPPROVED CHATGPT DRAFT. Do not merge automatically. Claude line-by-line review required.**

## Operator authorization

The operator explicitly asked ChatGPT to **build everything it can** while preserving the established boundary: ChatGPT work stays isolated and Claude can review/edit/reject it before anything reaches `main`.

This branch starts from `main` at `2ce8b2fabf39614c0cb558031a6fc5dccea815e5`. It does not contain PR #28; the Phase 17 event-bus proposal remains independently reviewable.

## Scope

This is a large **repo-only foundation** for roadmap work that does not require the operator's Windows PC. All production changes are additive files. Existing Core, policy, intercom, mail, pulse, director, workflow, registry, UI, and state files are untouched.

### Files added

- `aletheia/stateio.py` — safe IDs, atomic JSON replacement, exclusive append-style record creation
- `aletheia/contacts.py` — provider-neutral contacts + ambiguity-safe resolution
- `aletheia/calendar.py` — timezone-aware event model, conflicts, buffers, free-slot calculation
- `aletheia/scheduler.py` — one-shot/interval/daily/weekly schedules + idempotent due receipts; **does not execute commands**
- `aletheia/communications.py` — channel-neutral threads/messages/reply expectations
- `aletheia/outcomes.py` — action attempts separated from evidence-backed verification
- `aletheia/gaps.py` — capability-gap assessment + idempotent development-task materialization
- `aletheia/projects.py` — first-class project records linking goals/tasks/people/blockers/decisions
- `aletheia/context.py` — bounded explicit recent referents; ambiguity is refused rather than guessed
- `aletheia/proactive.py` — exact-match proactive rules, cooldown, event dedupe; produces proposals only
- `aletheia/recovery.py` — deterministic retry classification/backoff/budget; never sleeps or re-executes
- `aletheia/devices.py` — provider-neutral device/room records; devices remain unusable until observed ONLINE
- `tests/test_repo_only_systems.py`
- `tests/test_repo_only_runtime.py`
- this review document

## Verification performed before upload

A local isolated test harness ran **48 focused tests: 48/48 passed**.

The tests cover:

- path traversal / overwrite protections in state files
- contact ambiguity and unknown-recipient refusal
- timezone-aware calendar math, half-open conflicts, buffers, free slots
- schedule timing and idempotent occurrence claims
- reply expectations that only resolve on the correct participant after the tracked outbound message
- evidence required before an action can be VERIFIED
- capability gap classification and duplicate development-task avoidance
- immutable terminal projects
- ambiguity-safe recent context
- proactive event dedupe and cooldown
- recovery retry budgets and deterministic backoff
- device ability declaration and observed-online gating

Repository CI is the integration authority after the draft PR opens.

## Deliberate non-wiring

None of these modules are added to `config/capabilities.json`, Core routes, intercom command kinds, pulse, mail, director, or scheduled workflows in this branch.

That is deliberate. The operator asked for a non-invasive review box. Registering or wiring these primitives would change live authority/behavior and should happen only after Claude ratifies the data contracts and failure semantics.

## Security / authority properties to review

1. **Scheduler is not an executor.** A due receipt contains a command proposal; existing policy/approval gates must still authorize execution.
2. **Proactivity is not authority.** A rule emits a proposal (`surface`, `notify`, `enqueue`), never invokes a capability directly.
3. **Devices fail closed.** A declared device ability is insufficient; `require_ability` also requires an observed `ONLINE` state.
4. **Contacts fail on ambiguity.** No fuzzy recipient guessing is present.
5. **Context fails on ambiguity.** Multiple different eligible referents require explicit disambiguation.
6. **Outcomes separate invocation from verification.** `SUCCEEDED` becomes `AWAITING_VERIFICATION`; only evidence can make it `VERIFIED`.
7. **Gap materialization does not bypass worker governance.** It creates ordinary durable tasks assigned to Claude by default; director/approval rules remain separate.
8. **State writes avoid shared append-hot files.** Immutable receipt records use exclusive creation; mutable definitions use atomic replacement.

## Suggested Claude integration order if contracts are accepted

1. Review/merge PR #28 or replace its event contract.
2. Wire event producers into Phase 17.
3. Feed events into `proactive.py` and communication reply expectations.
4. Register Phase 14 local calendar/contact primitives honestly; external calendar provider remains `NEEDS_CONFIGURATION` until live.
5. Wire `scheduler.py` due receipts through existing intercom/policy execution, never directly.
6. Adopt `outcomes.py` for actions that currently equate invocation with success.
7. Wire `gaps.py` into the orchestrator/director for Phase 20 gap → development-task behavior.
8. Add Home Assistant adapter later; only then consider `room.scene` AVAILABLE after live verification.

## Things this branch does NOT claim

- no Google/Outlook calendar connection
- no live Home Assistant connection
- no Windows UI Automation acceptance
- no local wake-word/audio routing
- no phone calling
- no SMS transport
- no automatic spending/purchasing
- no autonomous execution of scheduled or proactive proposals
- no claim that Phase 14/18/19/20 are complete

Those remain configuration/integration or PC-dependent work and must be represented honestly in the capability registry.


---

## Claude review verdict — 2026-08-26

**RATIFIED as written** (journal `review:pr29`). One environment truth
it exposed: Windows Python ships no tz database — `tzdata` is now on
the bootstrap's required path. All modules gained real callers this
session (`python -m aletheia.assistant`, the Core runtime tick).
