# Why the gaps cost so much

Measured on `live` at 6fb9daa, 2026-09-13, after a week that was supposed
to begin with turning her on and instead turned into two days of job work.

The question is not "why are there gaps." There will always be gaps. The
question is why **each one costs a human**, and the answer is specific
enough to fix.

## The finding: she records what she cannot do, and nothing reads it

Aletheia has a complete, honest, well-maintained record of her own
limitations. Three of them, in fact:

- **`demand.py`** — every "can you…?" whose best match was not AVAILABLE,
  and since 2026-09-05 every real attempt she TRIED AND COULD NOT FINISH,
  in his own words.
- **`gaps.materialize`** — when a plan needs a capability that is not
  AVAILABLE, it files a build task naming the exact missing primitive.
- **`config/capabilities.json`** — 146 capabilities with honest statuses.

Now count the readers.

| record | writers | readers that BUILD anything |
|---|---|---|
| `demand` | 10 (`converse`, `intents`, `quick`, `cannot`, `apply_run`, `webtask`, `script`, `subscriptions`, `reservations`) | **0** |
| gap build-tasks | `gaps.materialize` | **0** |

`demand` has exactly one reader — `converse.py:604`, which reads
`demand.notable()` in order to *mention it in conversation*. Every other
`tasks.all_tasks()` caller in the package reads to DISPLAY (the API, the
wall, `quick`, `current_state`, `voice`) or to verify. None to execute.

And the code loop's entire universe of work is four lines:

```python
def choose_work(repo, *, request=gh.request):
    ...
    return _issue_work(repo, request=request) or _ci_work(repo, request=request)
```

**An open GitHub issue, or failing CI. That is all she will ever build.**

So the loop is: she notices a gap → names it precisely → files a task →
says it out loud → and then nothing, forever. Her own ledger of what she
cannot do is the one input her builder never looks at.

This is the repo's own "a store with a writer and no reader" rule, at the
top level, on the one store that would make her self-building.

## The second finding: the same bug shape keeps being rediscovered

Because rules live in prose, they get violated again by someone who did
not read that prose.

- **Console windows, twice.** 2026-08-27 he watched black boxes pop up all
  day; `proc.py` was written for it, and its docstring says every helper
  goes through `proc.run`. 2026-09-13 `ears.py` — which POLLS — called
  `subprocess.run(["powershell", ...])` directly and made his desktop
  unusable. Eighteen days. Same bug. And then *two sessions fixed it on
  the same day without knowing about each other*, which is the cost paid
  twice over.
- **"First in the list takes everything," three times.** Thirty-six
  configured boards crowded out the web search entirely ("every slot went
  to Stripe and Databricks"). Then two Greenhouse hosts crowded out the
  Lever search so it usually never ran. Then the charter loop's
  base-branch rule made three of four charters permanently ineligible.
  Three instances of one shape, each found by a person.

The fix that worked, both times, was the same: **turn the rule into a test
that fails.** `test_no_console_windows_on_his_desktop.py` walks every
module's AST; a fourth instance cannot land. Nothing in a docstring has
that property.

## The third finding: AVAILABLE means "has a caller," not "works"

120 of 146 capabilities are AVAILABLE. The registry's own definition of
AVAILABLE is that the entry names a real caller — which is a much weaker
claim than it sounds when read aloud, and the repo already knows this:

> INSTALLED is not WORKING, and a readiness check that confuses them is
> the worst kind of lie.

That lesson was learned about `browse.available()` and fixed in one place.
It was never generalised. Most of those 120 have never been run against
the world. The job pipeline is the proof: every piece of it was AVAILABLE
for weeks, and its first real run staged nothing, because the resume did
not read and both forms stopped on twelve required questions.

## What is actually irreducible, and what is not

Of 76 defect commits since 2026-09-10, **31 explicitly name a live
observation** — a real page, his real inbox, his real desktop. That class
is irreducible. A verification code that expires, a dropdown that must be
read while open, a pronoun box with nothing to click: no architecture
finds those before the first real run, and every form-filling system ever
built has paid that tax.

What is NOT irreducible is everything else:

- a gap she named and nobody built;
- a rule she already knew, violated again because it was prose;
- a discovery made once and not kept, so the next run rediscovers it.

## Getting to "proficient, self-building"

Four changes, in the order that compounds.

### 1. Point the builder at her own ledger

`choose_work` gains a third source: build tasks filed by `gaps`, ranked by
`demand`. One function, and the loop closes — the thing she most often
could not do becomes the thing she next tries to build.

This is the whole ballgame. Without it, she is a system that notices gaps
with great precision and is structurally incapable of closing them, and
every one of them routes through him forever.

Guardrails this needs, because it points her at her own code: the existing
`code_trust` grant with its cap, a PR she cannot merge on Aletheia itself
(`project_merge` already refuses that), and one build attempt per gap per
day so a gap she cannot close does not consume every cycle.

### 2. Make every "never" a test

The console-window rule survived eighteen days as a docstring and died. It
survives as an AST walk. `CLAUDE.md` holds perhaps thirty rules of the
form "never X" — each one is a candidate, and the ones already violated
once are the priority. A rule nothing enforces is a rule with a half-life.

### 3. Keep the world she has already seen

`tests/fixtures/` has **two** HTML files. For a system whose entire cost
is discovering how real pages behave, that is the largest missed
compounding in the repo. Every real page she touches should be saved as a
fixture on first contact. Then the second capability's discovery loop is
hours of offline replay rather than days of live round trips — and the
twelve Spotify non-questions become a regression test instead of a memory.

### 4. Make a failure produce work, not just a sentence

Today a failed run writes a journal line and tells him. It should write
the page that beat her, file the task, and rank it — so the loop in (1)
has something concrete to pick up tomorrow. A failure that produces only
prose is a failure that has to be re-experienced.

## The honest prediction

(2) and (3) are a day each and reduce the recurring cost immediately. (1)
is the one that changes what she *is*, and it is also the one to do
carefully, because it is the first time her builder is pointed at her own
limitations rather than at a GitHub issue somebody wrote.

None of this makes the first real run of a new capability cheap. It makes
the *second* one cheap, and it stops the third rediscovery of a bug she
has already fixed twice.
