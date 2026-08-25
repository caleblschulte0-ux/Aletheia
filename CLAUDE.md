# Aletheia — notes for Claude sessions

**Read `docs/PLAYBOOK.md` first.** It is the operator's master playbook
(2026-08-25) and supersedes every earlier definition. Aletheia is
Caleb's universal personal operating system — the interface between his
intent and everything software can legitimately observe, control,
delegate, coordinate, create, monitor, or influence. Spoken name: Thea.
The fleet monitoring this repo started as is now one sensory organ (the
**Fleet Observatory**), not the identity. `docs/ARCHITECTURE.md` maps
the playbook onto the code that exists; `docs/ROADMAP.md` tracks phases
honestly. This file is the working constitution for sessions editing
this repo.

## Rule zero: if you can fix it, fix it — and name what's missing

Inherited from Shorts-pipeline, extended by the playbook (§148–149): a
finding you could have fixed and didn't is worse than no finding. If you
cannot do it, determine exactly WHICH capability is missing; if it can
reasonably be built, turn the gap into an implementation task (a plan
step, a task, a registry NOT_BUILT entry with its ticket) — never a
permanent limitation. Never build a capability and leave it unwired:
everything in this repo has a real caller or says NOT_BUILT.

## The five registries are the only sources of truth

1. `config/fleet.json` — the fleet's composition and front-door grants
   (`python -m aletheia.fleet --validate`)
2. `config/capabilities.json` — what Aletheia can do, honestly:
   AVAILABLE / DEGRADED / EXPERIMENTAL / NEEDS_CONFIGURATION /
   UNAVAILABLE / NOT_BUILT (`python -m aletheia.capabilities`)
3. `aletheia/contracts.py` — the vocabulary (Capability, Provider, Goal,
   Task, Agent, Approval, ActionRecord) and every enum
4. `plans/` — goals as data (`python -m aletheia.plans list`)
5. `state/` — run truth: pulse, briefs, journal, tasks — CI-writable,
   never hand-tuned to look better

Never restate what a registry holds anywhere else; tests hold the README
table and the Goal contract against their stores. A missing or invalid
registry fails CLOSED.

**Never hallucinate capability (§104), never fake one (§106–107).** "Can
Aletheia do X?" is answered from the capability registry. An AVAILABLE
entry names its real caller; a NOT_BUILT entry names its ticket. No
Jarvis theater: the wall and every report render only what the pulse and
stores actually contain.

## Authority: authorized vs. unauthorized — not observe vs. act

The playbook replaces the old "observes but doesn't act" line (§55).
Aletheia SHOULD act — through front doors, within explicit grants:

- ABILITY and PERMISSION are separate (§70). Building `shopping.purchase`
  never authorizes using it. Grants live in registries
  (`front_door`, `approval_policy`), are checked BEFORE any network
  call, and widen only by a reviewed registry edit — never a code path
  around the check.
- Every action is journaled (`state/journal/` — append-only, same
  standing as posted logs; never edit or prune).
- High-risk capabilities (spending, binding agreements, sensitive
  disclosures, destructive actions) are `operator_always` — no grant
  short-circuits them (§56 L4).
- Fleet repos keep their own gates (the showrunner, the trader's
  guardrails); Aletheia reaches them only through their front doors with
  an outside caller's authority.

## Workers, and who edits

Aletheia is the orchestrator; models are workers (§4). **Claude is the
only worker that edits code** — in this repo and every fleet repo — via
`claude/*` branches. Claude is not Aletheia itself (§65). ChatGPT is the
voice and an advisor (§66): it reads everything public and writes
exactly two lanes, both validated —

- `exchange/suggestions/*.json` — prose findings, ruled on with a real
  `--because` (`python -m aletheia.suggestions`)
- `exchange/commands/*.json` — relayed OPERATOR asks per
  `exchange/INTERCOM.md`: named kinds only, `operator_quote` required,
  executed through the same gates, receipts committed

Nothing either lane carries can touch code, workflows, registries, or
docs. No model API keys anywhere (§6): both workers run on the
operator's subscriptions through official clients; a surface that stops
being supported degrades honestly.

## Tasks and goals are durable, verification is real

Real-world work outlives conversations (§27): anything multi-step or
waiting-on-the-world becomes a task (`python -m aletheia.tasks`) or a
plan, not a promise in chat. "No answer today" is WAITING_EXTERNAL, not
failure (§139). Never report "command executed" as "goal achieved"
(§30): say what the receipt, test, pulse, or CI run actually shows, and
never trust a worker's "done" without evidence when verification is
possible (§68).

## Interfaces

The **wall** (`interface/index.html`) is Ambient Aletheia (§88):
cinematic, one committed dark look, legible across a room, minimal when
nothing matters, and a PURE view of `state/pulse/latest.json` — smarts
go in collectors and registries, never the page; status is never
color-alone. The interactive **Command Center** (§90) is Phase 6 — until
then the intercom is the command channel. Do not grow controls into the
wall quietly.

## Storage & branch discipline

Small JSON/markdown only, nothing over 256KB, no media, no secrets in
committed files (Actions secrets only). `state/pulse/history/` keeps one
small file per day. Interactive sessions develop on `claude/*` branches
and push there; no auto-merge here — merges to `main` are deliberate.

## The standing assignment

Every session acts on the playbook rather than re-describing it (§156):
audit → build the next phase slice → keep every registry truthful → test
→ push → report concrete engineering status (§157). The build strategy
is vertical slices (§113); the priority order is §137. When the operator
says "handle it," this file plus the registries are how you know what
you may touch and how.
