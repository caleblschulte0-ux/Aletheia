# The dispatch tax

**Status: PROPOSAL. No code changes.** Measured on `main` at 80981fc,
2026-09-13. Nothing here has been implemented; this is the plan, written
so the decision can be made before the next capability is built rather
than after.

## What this is about

Two days of work took a job application from "staged" to "sent". Reading
the 64 commits that did it, most were discoveries about the world —
a verification code that expired before she typed it, a dropdown whose
options can only be read while it is open, a pronoun box with nothing to
click, twelve required fields on a Spotify form that were not questions.
That class is irreducible. No architecture prevents it and no amount of
design finds it earlier than the first real run.

But a minority were not about the world at all:

> "The ledger was sitting where every listing reads applications"
> "Every list of her tasks has to know about the new one"
> "The registry was the last place still saying she would spend his money"
> "The gate was built, landed, and never fired"
> "Forgetting broke her hands: an import made speech local to execute_command"

Those are the codebase's own shape charging rent. They are the only part
of the two days that was avoidable, and they are the part that grows with
every capability added. This document measures that cost and proposes one
change to collapse it.

## The measurement

Adding one capability touches a **median of about ten files**, and nothing
in the repository tells you which ten. The spread, as it stands today:

| what must change | where | size today |
|---|---|---|
| the grammar slot | `intercom.KIND_ARGS` | 109 kinds |
| which runner executes it | `intercom.LOCAL_KINDS` | 74 kinds |
| whether it is read-only | `intercom.READ_ONLY_KINDS` | 38 kinds |
| whether it is routine | `intercom.ROUTINE_KINDS` | 48 kinds |
| whether the planner may emit it | `intercom.PLANNER_FORBIDDEN` | 8 kinds |
| whether its steps re-check | `intercom.CONTAINERS` | 4 kinds |
| the handler branch | `intercom.execute_command` | 915 lines, 174 branches |
| how he can say it | `voice._interpret` | 1,215 lines, 56 pattern branches |
| whether she answers it fast | `quick.py` | 981 lines |
| the honest registry row | `config/capabilities.json` | 143 capabilities |
| the reader that proves the writer | `tests/test_every_writer_has_a_reader.py` | hand-kept |
| the handler that proves the kind | `tests/test_every_kind_has_a_handler.py` | both directions |

A kind's identity is therefore smeared across six module-level sets
declared at lines 54, 492, 537, 580, 757 and 1572 of one file, plus a
branch roughly a thousand lines below the first of them. To answer "what is
`web_task`, exactly?" you read six places. To add `web_task`, you write
six places, and the failure mode when you miss one is silent: the gate
that never fired, the ledger nobody read, the registry still promising
something the code had stopped doing.

## What is already right, and must not be lost

`KIND_ARGS` is already a real single source of truth for the **grammar**.
`planner.grammar_brief` generates the model's prompt from it, `core` derives
its accepted payloads from it, `quick` and `standing` read it. Adding a
slot widens every asking surface at once, which is exactly why "a
capability nothing can say is not a capability" stopped being a recurring
bug. That property is the thing worth preserving — the proposal extends
it to the other five facts rather than replacing it.

The structural tests are also right and stay. `test_every_kind_has_a_handler`
holds both directions; `test_every_writer_has_a_reader` is hand-kept on
purpose, because a mechanical check would have to guess which store a
handler touches and a wrong guess is a test that passes for the wrong
reason. Neither is what this proposal changes.

## The proposal: one descriptor per kind

Replace the six parallel collections with one table whose rows are whole
kinds. Every current set becomes a **derived** view, computed once at
import:

```python
@dataclass(frozen=True)
class Kind:
    name: str
    required: frozenset[str]
    optional: frozenset[str] = frozenset()
    tier: Tier = Tier.ROUTINE      # READ_ONLY | ROUTINE | WORLD | CONTAINER
    runner: Runner = Runner.ACTIONS # ACTIONS | LOCAL
    planner: bool = True            # may the planner emit it
    handler: Callable | None = None # the branch, as a function
    says: tuple[str, ...] = ()      # phrasings voice._interpret matches
```

with

```python
KINDS: dict[str, Kind] = { ... }                       # the one table
KIND_ARGS  = {k: (v.required, v.optional) for k, v in KINDS.items()}
READ_ONLY_KINDS  = frozenset(k for k, v in KINDS.items() if v.tier is Tier.READ_ONLY)
ROUTINE_KINDS    = frozenset(k for k, v in KINDS.items() if v.tier is Tier.ROUTINE)
LOCAL_KINDS      = frozenset(k for k, v in KINDS.items() if v.runner is Runner.LOCAL)
PLANNER_FORBIDDEN= frozenset(k for k, v in KINDS.items() if not v.planner)
CONTAINERS       = frozenset(k for k, v in KINDS.items() if v.tier is Tier.CONTAINER)
```

Every existing caller keeps working unchanged — `planner.grammar_brief`,
`core`, `quick`, `standing` all read the same names they read now. The
names simply stop being hand-kept.

### What this buys, defect by defect

- **A kind cannot be in two tiers.** `test_a_kind_is_not_both_read_only_and_routine`
  asserts exactly this today, because being in both makes `tier()` depend
  on the order the checks happen to be written in. With one `tier` field
  that state is unrepresentable, and the assertion becomes unnecessary
  rather than merely satisfied.
- **A kind cannot lose its handler.** `handler` is a field, so a kind
  without one fails at import, not at the bare `else` that used to run
  `media.convert` for any unrecognised `media_*`.
- **A kind cannot be silently unsayable.** `says` sits next to the slot
  it fills, so the hole that made "remind me every monday" compile a
  generic `do_task` is visible in the row rather than inferable from the
  absence of a regex 1,200 lines away.
- **The ten files become two.** The row, and the registry entry that has
  to stay honest about it.

### Deliberately NOT in scope

- **No gate is weakened, moved, or widened.** `would_spend` stays one
  predicate checked in three places. `PLANNER_FORBIDDEN` keeps the same
  eight members and the same meaning. `CONTAINERS` keeps its four. The
  tier of every existing kind is transcribed, never re-decided — if a
  transcription changes any kind's tier, that is a bug in the
  transcription, and the migration test below catches it.
- **`voice._interpret` is not collapsed in this step.** Moving 56 pattern
  branches is a second change with its own risk; `says` is populated but
  `_interpret` keeps reading it in place until the table has landed and
  proved itself.
- **No capability is added, removed, or restated.** This is a refactor of
  how kinds are declared, not of what Aletheia can do.

## Migration, in an order that cannot silently drift

1. Land `Kind`, `Tier`, `Runner` and an empty `KINDS` alongside the
   existing six collections. Nothing reads it yet.
2. Transcribe all 109 kinds into `KINDS`. The six collections stay
   hand-written.
3. **Add the equivalence test** — the whole safety of this change:

   ```python
   def test_derived_sets_match_the_hand_kept_ones(self):
       self.assertEqual(derived(KINDS).read_only, READ_ONLY_KINDS)
       ...  # one per collection, all six
   ```

   It fails on any transcription error, for every kind, before anything
   depends on the table.
4. Only once green, replace the six literals with the derived
   expressions and delete the equivalence test's now-redundant half.
5. Convert `execute_command`'s 174 branches to `KINDS[kind].handler(...)`
   one tier at a time — READ_ONLY first (38 kinds, nothing world-touching
   at stake), then ROUTINE, then WORLD, then the four containers. The
   `intercom.tier()` stays exactly as it is — it keeps deciding authority
   from the derived sets, and keeps running before dispatch.

Steps 1–4 are mechanical and reversible. Step 5 is the one that needs
review per tier, and it is the one that pays for itself.

## What it does not fix

The two-day cost was mostly discovery, and this changes none of it. A
verification code will still expire, a dropdown will still have to be
read while open, and the only way to find the next twelve non-questions
on a form is to put a résumé in front of it and watch. This proposal
addresses the minority of that time that the codebase charged for itself
— worth doing precisely because it is the part that compounds, and it is
better done before the next capability than after ten more.

## Open question for the operator

Worth doing before the next big capability, or after? The argument for
before is that every kind added between now and then is another row to
transcribe later. The argument for after is that it touches
`intercom.py`, which the job pipeline currently runs through, and the
apply work is live. Steps 1–3 add code without changing behaviour and
could land at any time; steps 4–5 are the ones that want a quiet moment.
