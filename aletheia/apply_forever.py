"""Keep looking and applying until he says stop.

His words, 2026-09-12, going AFK: *"make sure it dont stop looking and
applying end to end until i say stop."*

The two halves of that were not equally true. SENDING already never
stopped: `runtime.send_approved_applications` runs on the Core's beat,
picks up everything AWAITING_YOU whose approval is APPROVED, and his
standing grant (`apply-nonstop`) means those approvals decide themselves.
LOOKING did stop — `campaign.start` spawns one process that finds N jobs
and exits, and when it exits nothing starts another. He would have come
back to a finished pile and a machine doing nothing.

So this is the missing half, and it is deliberately almost nothing: if no
campaign is running, start one; wait; look again. Everything that makes
it safe already exists and is not re-implemented here.

- `campaign._launch` holds a lock, so a second campaign cannot start while
  one is under way. This loop cannot stack them however often it wakes.
- `policy.ensure_not_halted()` is what "stop" MEANS in this system. His
  halt, from any surface, ends the loop rather than being a flag this
  module invents.
- The standing grant expires on its own. When it does, applications still
  get found and filled and simply wait for him again — the loop does not
  quietly keep sending on an authority that has run out.

Run as a Windows task alongside the Core (`autostart.TASKS['apply']`), so
it survives a reboot, a crash and the end of whatever session started it.
A loop launched from a terminal dies with that terminal; that is exactly
how the first attempt at this was lost.

Applications WAITING on him are hers too. Reading them again with what she
knows now (`campaign retry`) was only ever run by a person, and run from an
outside session it was killed for memory. So when some are waiting and no
refill has started within the hour, a turn starts a refill instead of a
batch - under the same lock, so the two never overlap.
"""
from __future__ import annotations

import argparse
import time

from aletheia import campaign, journal, policy, speech

ACTOR = "aletheia-apply-forever"

#: How long to wait before looking for work again. Long enough that a quiet
#: day costs nothing, short enough that a finished campaign is noticed.
IDLE_WAIT_S = 300.0
#: How many to ask for each time. Small batches on purpose: a campaign that
#: dies at job forty loses forty; one that dies at job eight loses eight.
BATCH = 8
#: How often the waiting applications are read again, at most.
REFILL_EVERY_S = 3600.0
#: How many waiting applications one refill reads.
REFILL_LIMIT = 60
#: When this process last started a refill (monotonic seconds). Process
#: memory is enough: a restarted loop refilling once early costs one refill.
_LAST_REFILL: list[float] = []


#: The rest already said out loud, so a long one is journaled once, not
#: every five minutes.
_SAID_REST: set[str] = set()


def _claude_rests_until():
    """When Claude's usage window comes back, while it is spent. Never raises."""
    try:
        from aletheia import reasoner
        return reasoner.resting_until()
    except Exception:
        return None


def _another_mind() -> tuple[bool, str]:
    """(True, who) when Codex or her own model can think while Claude rests,
    else (False, why not, in words). Spends no model request. Never raises."""
    reasons = []
    try:
        from aletheia import reasoner
        ok, why = reasoner.codex_available()
        if ok:
            return True, "codex"
        reasons.append(why)
        ok, why = reasoner.local_allowed()
        if ok:
            return True, "local"
        reasons.append(why)
    except Exception as exc:
        reasons.append(f"the other models could not be checked ({type(exc).__name__})")
    return False, "; ".join(reasons)


def _waiting() -> int:
    """How many applications are waiting on him. Never raises."""
    try:
        from aletheia import apply_run
        return len(apply_run.all_runs("NEEDS_YOU"))
    except Exception:
        return 0


def once(*, batch: int = BATCH, resume: str = "", starter=None, refiller=None,
         clock=None) -> dict:
    """One turn of the loop: refill the waiting applications, start a
    campaign, or leave the running one be."""
    policy.ensure_not_halted()
    current = campaign.running()
    if current:
        return {"started": False, "already": current.get("pid")}
    # NOT WHILE NOBODY CAN THINK. Live 2026-09-13 his usage window was spent
    # from 18:42 to 19:40 UTC, and a batch started every five minutes anyway:
    # with no model it could not name his roles or judge a single job, so each
    # one searched 62 boards for his one resume title and applied to nothing.
    # Then his words the same day: "make it so that tomorrow when I hit my
    # Claude limit it still is applying for jobs." So Claude being out is no
    # longer enough to wait: the batch thinks with Codex, or with her own model
    # when there is memory for it, and waits only when neither can.
    rests = _claude_rests_until()
    if rests is not None:
        other, why = _another_mind()
        if not other:
            until = rests.isoformat()
            if until not in _SAID_REST:
                _SAID_REST.add(until)
                journal.append("decision", "apply:forever",
                               f"Claude is out until {until} and nobody else can think "
                               f"({why}), so the job hunt waits rather than run batches "
                               "that cannot judge a job", actor=ACTOR)
            return {"started": False, "resting_until": until, "why": why}
    # WHAT IS WAITING BEFORE WHAT IS NEW. An application stuck on a question
    # her facts or her code now answer is closer to sent than any fresh job,
    # and nothing but a person running `campaign retry` ever read one again.
    now = (clock or time.monotonic)()
    if not _LAST_REFILL or now - _LAST_REFILL[-1] >= REFILL_EVERY_S:
        waiting = _waiting()
        if waiting:
            # Stamped on the attempt, not the success: a refill that cannot
            # start must not take every turn from the batches.
            _LAST_REFILL[:] = [now]
            refill = refiller or campaign.start_retry
            out = refill(limit=REFILL_LIMIT)
            if out.get("started"):
                journal.append("action", "apply:forever",
                               f"reading {speech.count_phrase(waiting, 'waiting application')} "
                               "again with what she knows now, before looking for more",
                               actor=ACTOR)
            return {**out, "refill": True, "waiting": waiting}
    start = starter or campaign.start
    out = start(count=batch, resume=resume)
    if out.get("started"):
        journal.append("action", "apply:forever",
                       f"started another batch of {batch} — he asked for this to "
                       "keep looking until he says stop", actor=ACTOR)
    return out


def forever(*, batch: int = BATCH, resume: str = "", wait_s: float = IDLE_WAIT_S,
            turns: int | None = None, starter=None, sleeper=None, refiller=None) -> int:
    """Look, apply, wait, repeat — until he halts her or the process dies.

    `turns` and `sleeper` exist for the tests. Left alone it does not stop.
    """
    sleep = sleeper or time.sleep
    done = 0
    while turns is None or done < turns:
        try:
            once(batch=batch, resume=resume, starter=starter, refiller=refiller)
        except policy.Halted:
            journal.append("decision", "apply:forever",
                           "he halted her, so the job hunt stopped", actor=ACTOR)
            return 0
        except Exception as exc:
            # A bad batch is not a reason to stop hunting for good. It is
            # recorded and the next turn tries again.
            journal.append("alert", "apply:forever",
                           f"a batch could not start: {type(exc).__name__}: {exc}"[:200],
                           actor=ACTOR)
        done += 1
        if turns is None or done < turns:
            sleep(wait_s)
    return 0


def main(argv: list[str] | None = None) -> int:
    # An always-on process never inherits the right to open his signed-in
    # ChatGPT. Every other entry point registered as a scheduled task does
    # this first (core, project_loop, project_merge); this one is now one of
    # them, and on 2026-09-12 a readiness check that skipped the lease was
    # what kept putting ChatGPT windows over his work.
    from aletheia import browser_reasoner
    browser_reasoner.drop_lease()
    ap = argparse.ArgumentParser(
        description="Keep looking for jobs and applying until he says stop.")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--resume", default="")
    ap.add_argument("--wait", type=float, default=IDLE_WAIT_S)
    ap.add_argument("--once", action="store_true",
                    help="one turn and exit, for checking it works")
    args = ap.parse_args(argv)
    if args.once:
        print(once(batch=args.batch, resume=args.resume))
        return 0
    return forever(batch=args.batch, resume=args.resume, wait_s=args.wait)


if __name__ == "__main__":
    raise SystemExit(main())
