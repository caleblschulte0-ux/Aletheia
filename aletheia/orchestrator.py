"""Orchestrator V1 — deterministic goal → tasks → verified outcome
(Playbook §119, Phase 5).

No AI planning yet, on purpose: prove the architecture first. The
orchestrator compiles a Goal (a plan in `plans/`) into durable tasks —
one per not-yet-done step, chained sequentially — and syncs completion
back the other way with the §30 rule enforced in code: **a plan step is
marked done only when its task is COMPLETED with recorded evidence**
(a non-empty result). "Command executed" never silently becomes "goal
achieved".

    compile(slug)  plan steps  ──►  tasks <slug>-s<n> (sequential deps)
    sync(slug)     tasks COMPLETED+evidence  ──►  steps done;
                   every step done  ──►  plan done (journaled)

Both are idempotent — safe to run on every pulse. Task workers are
assigned per step by the caller or the director; the orchestrator only
shapes the work.
"""
from __future__ import annotations

import argparse

from aletheia import journal, plans, tasks


def task_id(slug: str, n: int) -> str:
    return f"{slug}-s{n}"


def compile_goal(slug: str, worker: str | None = None) -> list[dict]:
    """Create a task for every step that has no task yet. Sequential
    dependency chain: step n waits on step n-1's task. Idempotent."""
    plan = plans.load(slug)
    if plan["state"] != "open":
        raise ValueError(f"plan {slug!r} is {plan['state']} — only open goals compile")
    created = []
    for step in plan["steps"]:
        tid = task_id(slug, step["n"])
        if step["state"] == "done":
            continue
        try:
            tasks.load(tid)
            continue  # already compiled
        except FileNotFoundError:
            pass
        deps = []
        if step["n"] > 1:
            prev = task_id(slug, step["n"] - 1)
            prev_done = any(
                s["n"] == step["n"] - 1 and s["state"] == "done" for s in plan["steps"])
            try:
                tasks.load(prev)
                if not prev_done:
                    deps = [prev]
            except FileNotFoundError:
                pass
        created.append(tasks.create(
            tid, step["text"], goal=slug,
            dependencies=deps or None, assigned_worker=worker,
            priority=2))
    if created:
        journal.append("plan", f"plan:{slug}",
                       f"compiled — {len(created)} task(s) created")
    return created


def sync_goal(slug: str) -> dict:
    """Fold verified task completion back into the plan. Returns a summary."""
    plan = plans.load(slug)
    stepped, unverified = [], []
    for step in plan["steps"]:
        if step["state"] == "done":
            continue
        try:
            t = tasks.load(task_id(slug, step["n"]))
        except FileNotFoundError:
            continue
        if t["status"] == "COMPLETED":
            if t.get("result", "").strip():
                plans.set_step(slug, step["n"], "done")
                stepped.append(step["n"])
            else:
                unverified.append(step["n"])  # §30: no evidence, no credit
        elif t["status"] == "RUNNING" and step["state"] == "todo":
            plans.set_step(slug, step["n"], "doing")
        elif t["status"] == "BLOCKED" and step["state"] != "blocked":
            plans.set_step(slug, step["n"], "blocked")
    plan = plans.load(slug)
    done, total = plans.progress(plan)
    if total and done == total and plan["state"] == "open":
        plans.set_plan(slug, "done", because="every step completed with evidence")
    return {"slug": slug, "steps_done": stepped, "unverified": unverified,
            "progress": f"{done}/{total}", "plan_state": plans.load(slug)["state"]}


def run_all(worker: str | None = None) -> list[dict]:
    """Compile + sync every open goal — the pulse-cadence entry point."""
    out = []
    for plan in plans.all_plans():
        if plan["state"] != "open":
            continue
        compile_goal(plan["slug"], worker=worker)
        out.append(sync_goal(plan["slug"]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic goal orchestration.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_c = sub.add_parser("compile")
    p_c.add_argument("slug"); p_c.add_argument("--worker")
    p_s = sub.add_parser("sync"); p_s.add_argument("slug")
    p_r = sub.add_parser("run"); p_r.add_argument("--worker")
    args = ap.parse_args(argv)

    if args.cmd == "compile":
        created = compile_goal(args.slug, worker=args.worker)
        print(f"{len(created)} task(s) created for {args.slug}")
    elif args.cmd == "sync":
        print(sync_goal(args.slug))
    else:
        for summary in run_all(worker=args.worker):
            print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
