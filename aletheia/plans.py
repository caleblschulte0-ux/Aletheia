"""Plans — large-scale intent as tracked data (ROADMAP A9, first cut).

A plan is a goal decomposed into steps, each optionally aimed at a fleet
repo. Plans live in `plans/<slug>.json` (authored content, so repo root,
not `state/`), have a lifecycle, and every mutation is journaled. The
pulse embeds a summary so the wall and the morning brief both show what
is in motion — a plan nobody can see is a plan nobody chases.

States: plan open|done|dropped; step todo|doing|done|blocked.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from aletheia.fleet import REPO_ROOT, load_fleet
from aletheia import journal

PLANS_DIR = REPO_ROOT / "plans"
PLAN_STATES = {"open", "done", "dropped"}
STEP_STATES = {"todo", "doing", "done", "blocked"}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path(slug: str) -> Path:
    return PLANS_DIR / f"{slug}.json"


def load(slug: str) -> dict:
    return json.loads(_path(slug).read_text(encoding="utf-8"))


def save(plan: dict) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    _path(plan["slug"]).write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def all_plans() -> list[dict]:
    if not PLANS_DIR.is_dir():
        return []
    out = []
    for f in sorted(PLANS_DIR.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def validate_plan(plan: dict, fleet: dict) -> list[str]:
    problems = []
    for key in ("slug", "title", "goal", "state", "created", "steps"):
        if key not in plan:
            problems.append(f"missing key {key}")
    if plan.get("state") not in PLAN_STATES:
        problems.append(f"state {plan.get('state')!r} not in {sorted(PLAN_STATES)}")
    if "slug" in plan and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", plan["slug"]):
        problems.append(f"slug {plan['slug']!r} must be lowercase-kebab")
    for i, step in enumerate(plan.get("steps", [])):
        if not step.get("text"):
            problems.append(f"steps[{i}]: needs text")
        if step.get("state") not in STEP_STATES:
            problems.append(f"steps[{i}]: state {step.get('state')!r} not in {sorted(STEP_STATES)}")
        repo = step.get("repo")
        if repo and repo != "fleet" and repo not in fleet["repos"]:
            problems.append(f"steps[{i}]: repo {repo!r} not in the fleet registry")
    return problems


def new_plan(slug: str, title: str, goal: str) -> dict:
    if _path(slug).exists():
        raise FileExistsError(f"plan {slug!r} already exists")
    plan = {"slug": slug, "title": title, "goal": goal, "state": "open",
            "created": _now(), "steps": []}
    save(plan)
    journal.append("plan", f"plan:{slug}", f"opened — {title}")
    return plan


def add_step(slug: str, text: str, repo: str | None = None) -> dict:
    plan = load(slug)
    step = {"n": len(plan["steps"]) + 1, "text": text, "state": "todo"}
    if repo:
        step["repo"] = repo
    plan["steps"].append(step)
    save(plan)
    journal.append("plan", f"plan:{slug}", f"step {step['n']} added — {text}")
    return plan


def set_step(slug: str, n: int, state: str) -> dict:
    if state not in STEP_STATES:
        raise ValueError(f"step state must be one of {sorted(STEP_STATES)}")
    plan = load(slug)
    for step in plan["steps"]:
        if step["n"] == n:
            step["state"] = state
            save(plan)
            journal.append("plan", f"plan:{slug}", f"step {n} -> {state} ({step['text']})")
            return plan
    raise KeyError(f"plan {slug!r} has no step {n}")


def set_plan(slug: str, state: str, because: str = "") -> dict:
    if state not in PLAN_STATES:
        raise ValueError(f"plan state must be one of {sorted(PLAN_STATES)}")
    plan = load(slug)
    plan["state"] = state
    save(plan)
    journal.append("plan", f"plan:{slug}", f"-> {state}" + (f" — {because}" if because else ""))
    return plan


def progress(plan: dict) -> tuple[int, int]:
    steps = plan.get("steps", [])
    return sum(1 for s in steps if s["state"] == "done"), len(steps)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fleet plans.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new")
    p_new.add_argument("slug"); p_new.add_argument("title"); p_new.add_argument("goal")
    p_add = sub.add_parser("add-step")
    p_add.add_argument("slug"); p_add.add_argument("text"); p_add.add_argument("--repo")
    p_step = sub.add_parser("step")
    p_step.add_argument("slug"); p_step.add_argument("n", type=int)
    p_step.add_argument("state", choices=sorted(STEP_STATES))
    p_set = sub.add_parser("set")
    p_set.add_argument("slug"); p_set.add_argument("state", choices=sorted(PLAN_STATES))
    p_set.add_argument("--because", default="")
    sub.add_parser("list")
    p_show = sub.add_parser("show"); p_show.add_argument("slug")
    sub.add_parser("validate")
    args = ap.parse_args(argv)

    if args.cmd == "new":
        new_plan(args.slug, args.title, args.goal); print(f"plan {args.slug} opened")
    elif args.cmd == "add-step":
        p = add_step(args.slug, args.text, args.repo); print(f"step {len(p['steps'])} added")
    elif args.cmd == "step":
        set_step(args.slug, args.n, args.state); print(f"{args.slug} step {args.n} -> {args.state}")
    elif args.cmd == "set":
        set_plan(args.slug, args.state, args.because); print(f"{args.slug} -> {args.state}")
    elif args.cmd == "show":
        plan = load(args.slug)
        done, total = progress(plan)
        print(f"{plan['title']} [{plan['state']}] {done}/{total}\n  goal: {plan['goal']}")
        for s in plan["steps"]:
            mark = {"done": "x", "doing": ">", "blocked": "!", "todo": " "}[s["state"]]
            print(f"  [{mark}] {s['n']}. {s['text']}" + (f"  ({s['repo']})" if s.get("repo") else ""))
    elif args.cmd == "validate":
        fleet = load_fleet()
        bad = 0
        for plan in all_plans():
            problems = validate_plan(plan, fleet)
            if problems:
                bad += 1
                print(f"INVALID {plan.get('slug')}: " + "; ".join(problems))
        print(f"{len(all_plans())} plan(s), {bad} invalid")
        return 1 if bad else 0
    else:  # list
        for plan in all_plans():
            done, total = progress(plan)
            print(f"[{plan['state']:7}] {plan['slug']:24} {done}/{total}  {plan['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
