# ChatGPT Phase 19 attention policy — Claude review

**UNAPPROVED CHATGPT CODE. Do not merge without Claude line-by-line review.**

Branch: `chatgpt/proactive-attention-v1`  
Base: Claude's `cf10a03` Phase 10 live-voice head.

## Problem this slice closes

The existing Phase 19 stack can turn events into notification/task proposals,
but it does not distinguish:

- something worth showing in the notification center;
- something allowed to interrupt during quiet hours;
- something that can wait until morning;
- something that becomes more important after being ignored.

Without that distinction, adding a future push provider would either wake the
operator too often or force each producer to invent its own notification rules.

## What this draft builds

### `aletheia/attention.py`

A private delivery-policy layer over the existing notification center.

Zero-intrusion defaults:

- quiet hours disabled;
- no priority bypasses quiet hours;
- no escalation rules.

Configured policy supports:

- named IANA timezone;
- same-day or cross-midnight quiet window;
- explicit priorities allowed to bypass quiet time;
- monotonic escalation chains (for example NORMAL -> IMPORTANT after 30 min,
  IMPORTANT -> URGENT after 120 min);
- escalation thresholds must increase along a chain;
- one private attention record per notification;
- states READY / DEFERRED / DELIVERED / CANCELLED;
- acknowledgement cancels a not-yet-delivered attention record;
- a deferred notice becomes READY after quiet hours automatically on a later
  Core tick;
- an escalation can become a quiet-hours bypass only when the final priority is
  explicitly in `bypass_priorities`;
- external/local delivery can be recorded only from READY and requires provider
  + evidence.

**Important:** `READY` does not mean sent. This module has no push transport.
The local UI may continue to show every notification; attention policy governs
interruptive delivery eligibility for future providers.

### `aletheia/proactive.py`

Rules now have explicit notification priority. Old rules without the field remain
valid and behave as NORMAL. Evaluation copies the priority into the proposal
receipt. The rule still never executes its proposal.

### `aletheia/proactive_cli.py`

Creates/lists/enables/disables proactive rules with explicit priority. This is a
configuration surface, not an executor.

### `aletheia/runtime.py`

Attention reconciliation runs LAST on each Core beat, after:

- schedule failure notices;
- mail/pulse observers;
- reply transitions;
- watcher notifications;
- proactive notifications;
- gap/handler reconciliation.

The attention engine is isolated with the existing `guarded()` pattern: corrupt
attention policy cannot stop the Core's other runtime functions.

## Authority boundary

This slice does **not** implement the Phase 19 ACT tier.

- no task is executed because a notice escalated;
- no approval is bypassed;
- no SMS/push/email is sent;
- no quiet-hours priority is inferred from content;
- no default wake-the-operator behavior is introduced.

A future delivery provider must consume only READY records and write delivery
evidence back. A future ACT tier still requires the ordinary capability/policy
path and is outside this PR.

## Failure modes Claude should attack

- quiet window crossing midnight and DST boundaries;
- quiet start/end equal or malformed;
- invalid timezone;
- low priority configured as a bypass accidentally;
- escalation that lowers priority or cycles;
- escalation chain whose later threshold is earlier than its first threshold;
- notice acknowledged while deferred;
- notice becomes urgent while quiet and is/isn't configured to bypass;
- repeated Core ticks creating duplicate delivery records;
- attention policy corruption preventing schedules or mail from running;
- a producer setting an unknown priority;
- delivery marked without provider evidence;
- DELIVERED record accidentally becoming eligible to send again.

## Proposed roadmap truth if accepted

Phase 19 can move from:

`PARTIAL — NOTIFY tier BUILT locally`

to something like:

`PARTIAL — attention/NOTIFY policy BUILT; external delivery provider + ACT tier remain`

Do not mark proactive external notification delivery AVAILABLE: there is still no
push/SMS provider in this slice.
