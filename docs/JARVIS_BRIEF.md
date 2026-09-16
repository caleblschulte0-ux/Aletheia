# Aletheia Improvement Brief: From Orchestrator to a Real Local "Jarvis"

Operator-supplied brief, 2026-09-15. Kept verbatim in its substance so every
session works from the same target. His own summary of the diagnosis:

> Aletheia has accumulated capabilities faster than it has accumulated a
> unified agent runtime and a unified model of itself.

## The five system-level changes

| What must change | Current situation | Target |
|---|---|---|
| Local intelligence | Mostly structured reasoning worker | Persistent tool-using agent |
| Capability model | Commands/capabilities spread across several representations | One declarative tool registry |
| Self-awareness | Separate stores; limited repo/state visibility | Unified queryable world/self model |
| Browser | Deterministic browser operations plus growing special cases | General observe-reason-act-verify loop |
| Job hunting | Increasing ATS-specific automation | Web-scale discovery + universal application state machine |
| Interface | Good-looking operator console | Living mission control for everything Thea is doing |
| Cloud models | Often feel like the "real brain" | Specialists Thea hires only when useful |

The rule to preserve: **the model never owns authority.** A model may
request tools, chain calls, inspect results and revise plans; the Core
decides whether an action is permitted and performs it. Tool choice without
tool authority.

## 1. The local AI as the operating intelligence

Introduce an `AgentSession` runtime above `reasoning_gateway`:

```
Caleb -> Intent -> AgentSession (read state, retrieve memory, discover permitted tools)
  -> local model -> ToolRequest -> Policy Broker (schema, capability, scope, grant, approval)
  -> Executor -> Observation -> local model -> repeat until satisfied / blocked / handed off
  -> verify -> checkpoint -> explain
```

A tool call never invokes Python directly: it becomes an `ActionIntent`
the Core checks, executes, sanitizes, receipts, and returns as an
observation. This extends the existing "model proposes; gates dispose"
philosophy from one compiled plan to an iterative session.

Make the September 13 "one descriptor per kind" proposal the foundational
refactor, and make each descriptor a full tool definition: name,
description, input/output schema, handler, risk tier, read_only /
destructive / idempotent / open_world, reads/writes, planner and
local-model visibility, approval policy, standing grant, UI component. From
that one table derive the planner grammar, the local-model tool catalog,
Command Center forms, the capability registry, approval behaviour, docs,
quick commands, voice discoverability, tests, and eventually MCP exposure.
Keep the protocol MCP-compatible without rebuilding around MCP; MCP's
multi-round-trip requests map directly onto "this site needs a CAPTCHA, I
have everything else ready, tell me when you're done".

Local model hierarchy: fast local (resident; classification, routing, simple
tool selection), deep local only on hardware where it runs reliably (the
27B deep role failed 31/31 on this 16 GB laptop - a capacity mismatch, not
an orchestration bug), an optional vision model, a tiny always-on embedding
model, and cloud specialists invoked by Aletheia rather than presented as
her. Acceptance for a deep default: zero memory-related failures over a
100-session soak. The fast model gets smarter by looking things up
(ledger, profile, code index, journal, browser observations) instead of
remembering them.

## 2. Real self-awareness

Add a `repo` capability family: `repo.list/search/read/symbol/status/diff/
log/test_history` read-only; `repo.test` behind a local-execution gate;
`repo.propose_patch` non-authoritative; `repo.change` behind the code-work
grant; `repo.open_pr` behind the external/write gate. Reading her own code is
normal; changing her running code stays a different privilege, progressing
inspect -> diagnose -> propose -> branch -> patch -> tests -> stronger-model
review -> operator/standing policy -> merge.

Make `current_state` the single root of situational awareness, including
what it omits today: the job hunt (running, discovered/qualified/attempted/
ready/sent/blocked/replies, blockers), the agent's own state and mission
step, the browser (site, purpose, stage), and code state (repo, branch,
dirty, latest commit). Complement exact state with a local semantic index
over code, docs, journal, application history, employer notes, browser
failures and prior fixes; facts come from the ledger, embeddings only find
history. Distinguish knowing, looking and guessing when she answers.

## 3. Job discovery for the jobs nobody else finds

Split discovery into explicit stages: discover the web -> employers ->
career surfaces -> individual jobs -> normalize + score -> resolve the
application destination -> apply.

- A `search.web` provider backed by a real web index (replaceable), issuing
  diverse discovery queries whose results become candidate employers and
  career pages, not applications.
- A durable `employers` store (name, domains, career URLs, ATS, locations,
  last crawl, jobs seen, high-value flag) so the local employer universe
  around his geography and fields is remembered.
- Shallow polite career-site crawling: careers/jobs paths, sitemaps,
  external ATS links, JSON-LD `JobPosting`. Extraction ladder: official ATS
  API -> JobPosting structured data -> known ATS adapter -> generic DOM ->
  local-model extraction -> vision only if required. Use APIs to discover
  where genuinely public; use the browser to apply.
- Score for value, not keyword similarity: role/skill fit, realistic
  seniority, compensation, geography/remote, employer quality, advancement,
  unusual pay for local cost of living, recency, ease; minus over/under
  qualification, missing credentials, travel mismatch, pay below floor,
  duplicates, scam risk. Deterministic facts stay deterministic; the model
  handles fuzzy fit. Keep two queues: best-fit and interesting outliers.

## 4. "Apply anywhere" as a browser capability

ATS adapters optimize common cases; underneath is a general observe ->
understand -> act -> verify page loop with structured observations, a small
page-state vocabulary (JOB_POST, APPLICATION, ACCOUNT_LOGIN/SIGNUP,
EMAIL/SMS_VERIFICATION, MULTI_PAGE_WIZARD, REVIEW, SUCCESS, CAPTCHA, ERROR,
UNKNOWN), semantic targets (role/label) instead of raw selectors as the
primary abstraction, re-observation after every transition, mission
checkpoints (DISCOVERED ... SUBMIT_CLICKED, RECEIPT_VERIFIED, SENT) so a
crash resumes rather than restarts, verification codes as events, and
learned site skills (field aliases, known states, navigation hints).
Invariant: retrying observation is fine; retrying submission without proof
the prior attempt failed is not.

Three execution modes: autonomous permitted (public employer/ATS forms),
assisted (CAPTCHA, identity checks - do everything allowed, bring him to the
exact remaining step, resume), and manual-only where platform terms forbid
automation (Indeed, LinkedIn).

## 5. Interface around presence, missions and trust

Keep the visual language; change the information architecture. The top of
the screen always answers "what is Thea doing right now?" with a tiny
state vocabulary (IDLE, LISTENING, THINKING, LOOKING, ACTING, WAITING, NEEDS
YOU, BLOCKED, HALTED). Primary screen = conversation + present state;
exact commands become a developer drawer. Missions above tasks; a Job Hunt
Control Room as a pipeline (DISCOVERED -> REVIEWED -> APPLYING -> NEEDS YOU
-> SENT -> REPLIED -> INTERVIEW) with per-application cards that can answer
"why this one?" and "why didn't this send?"; a live activity ribbon in
plain sentences with receipts one click away; "Eyes" on the browser; model
provenance in the receipt, never as the identity.

## Five categories of state

Identity, world, mission, execution, self. Every interface and every model
draws from the same stores. Open-world content (web, email) is untrusted
data with tracked provenance; it may inform reasoning and may never create
authority.

## Roadmap and definition of done

Foundation first: one tool descriptor; the AgentSession loop;
`current_state` v2; repo/file introspection; semantic memory. Then the job
system: web-index discovery; employer intelligence; the generic browser
state machine; mission checkpoints. Then UI: mission-centric home, Job Hunt
Control Room, Eyes + handoff. Then intelligence: deep-local upgrade,
self-diagnosis and patch proposals.

Milestones:

1. Cloud off. Ask "how did applications go today, what are you doing, what
   went wrong, what do you need from me?" - answered from live state by the
   local model through its own tool calls, with no hand-built context.
2. "Why can't you handle this application?" - she inspects the record, the
   page, browser errors, her own code/registry, and names the boundary.
3. ECG-style discovery: small regional employers absent from every board,
   found from role/location preferences alone.
4. A browser torture suite (every ATS, account walls, custom forms,
   wizards, uploads, email/SMS codes, server errors, mid-run crash,
   duplicate URL, CAPTCHA handoff): every site succeeds or stops at a
   precisely named boundary without lying, duplicating, losing progress or
   asking him to redo work.
5. Come back after hours away and, from one screen in ten seconds, know:
   is she running, what is she doing, what did she accomplish, what
   failed, what needs me, what happens next.

The standard: **a capability counts as built only when Thea can discover
she has it, decide when to use it, request it safely, observe whether it
worked, recover when it did not, remember the result, explain it, and
surface its state in the interface.**
