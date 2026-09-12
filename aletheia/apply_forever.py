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
"""
from __future__ import annotations

import argparse
import time

from aletheia import campaign, journal, policy

ACTOR = "aletheia-apply-forever"

#: How long to wait before looking for work again. Long enough that a quiet
#: day costs nothing, short enough that a finished campaign is noticed.
IDLE_WAIT_S = 300.0
#: How many to ask for each time. Small batches on purpose: a campaign that
#: dies at job forty loses forty; one that dies at job eight loses eight.
BATCH = 8


def once(*, batch: int = BATCH, resume: str = "", starter=None) -> dict:
    """One turn of the loop: start a campaign, or leave the running one be."""
    policy.ensure_not_halted()
    current = campaign.running()
    if current:
        return {"started": False, "already": current.get("pid")}
    start = starter or campaign.start
    out = start(count=batch, resume=resume)
    if out.get("started"):
        journal.append("action", "apply:forever",
                       f"started another batch of {batch} — he asked for this to "
                       "keep looking until he says stop", actor=ACTOR)
    return out


def forever(*, batch: int = BATCH, resume: str = "", wait_s: float = IDLE_WAIT_S,
            turns: int | None = None, starter=None, sleeper=None) -> int:
    """Look, apply, wait, repeat — until he halts her or the process dies.

    `turns` and `sleeper` exist for the tests. Left alone it does not stop.
    """
    sleep = sleeper or time.sleep
    done = 0
    while turns is None or done < turns:
        try:
            once(batch=batch, resume=resume, starter=starter)
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
