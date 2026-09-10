"""Plans — large-scale intent as tracked data (ROADMAP A9, first cut).

A plan is a goal decomposed into steps, each optionally aimed at a fleet
repo. Plans live in `plans/<slug>.json` (authored content, so repo root,
not `state/`), have a lifecycle, and every mutation is journaled. The
pulse embeds a summary so the wall and the morning brief both show what
is in motion — a plan nobody can see is a plan nobody chases.

CHARTERS. A plan with a `project` block is a charter: a venture he wants
carried while his attention is somewhere else. His words, 2026-09-10:
*"I'll start a project really passionate about it for, like, a week or two
and then just kinda get bored and forget about it ... I just need [her] to
be able to take my projects and continue building ... and keeping me on
track too."* A charter is what lets that happen without guessing. It names
the repository and the BRANCH the project really lives on (Barkly's ~500
commits are not on Money_Machine's `main`, which holds a README), how much
a merge risks, and — step by step — whose each step is. Hers go to the
cloud builder; his go into the morning brief, one at a time. A step is
credited by a merged pull request that names it (`credit_merged`) or by
him, never by a worker saying it finished (§68).

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
from aletheia import contracts, journal

PLANS_DIR = REPO_ROOT / "plans"
PLAN_STATES = contracts.GOAL_STATES
STEP_STATES = contracts.GOAL_STEP_STATES
STEP_OWNERS = contracts.GOAL_STEP_OWNERS
PROJECT_RISKS = contracts.GOAL_PROJECT_RISKS
THEA, CALEB = "thea", "caleb"
# How a pull request says which charter step it builds. It is the only
# thing that turns a merge into credit, so it is matched exactly.
CHARTER_STEP = re.compile(r"Charter-Step:\s*([a-z0-9][a-z0-9-]*)#(\d+)", re.IGNORECASE)


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
    project = plan.get("project")
    if project is not None:
        if not isinstance(project, dict):
            problems.append("project must be an object")
        else:
            if project.get("repo") not in fleet["repos"]:
                problems.append(f"project.repo {project.get('repo')!r} not in the fleet registry")
            if not str(project.get("base_branch") or "").strip():
                problems.append("project.base_branch: a charter names the branch the project lives on")
            if project.get("risk") not in PROJECT_RISKS:
                problems.append(f"project.risk {project.get('risk')!r} not in {sorted(PROJECT_RISKS)}")
    numbers = {s.get("n") for s in plan.get("steps", []) if isinstance(s, dict)}
    for i, step in enumerate(plan.get("steps", [])):
        if not step.get("text"):
            problems.append(f"steps[{i}]: needs text")
        if step.get("state") not in STEP_STATES:
            problems.append(f"steps[{i}]: state {step.get('state')!r} not in {sorted(STEP_STATES)}")
        repo = step.get("repo")
        if repo and repo != "fleet" and repo not in fleet["repos"]:
            problems.append(f"steps[{i}]: repo {repo!r} not in the fleet registry")
        if step.get("owner") is not None and step.get("owner") not in STEP_OWNERS:
            problems.append(f"steps[{i}]: owner {step.get('owner')!r} not in {sorted(STEP_OWNERS)}")
        for need in step.get("needs") or []:
            if need not in numbers or not isinstance(step.get("n"), int) or need >= step["n"]:
                problems.append(f"steps[{i}]: needs {need!r} must name an EARLIER step")
    return problems


def is_charter(plan: dict) -> bool:
    return isinstance(plan, dict) and isinstance(plan.get("project"), dict)


def owner(step: dict) -> str:
    """Whose step this is. Unmarked steps are hers: a charter that forgot to
    say should still move, and HIS steps are the ones that must be named,
    because they are the ones the brief will ask him for."""
    return str(step.get("owner") or THEA)


def next_step(plan: dict) -> dict | None:
    """The first step not done, whoever it belongs to — the project's "next"."""
    for step in plan.get("steps", []):
        if step.get("state") != "done":
            return step
    return None


def next_for(plan: dict, who: str) -> dict | None:
    """The first step `who` can actually do now.

    Not simply the next step. The builder should not stand still while a
    step of his sits undone, and he should not be asked for something that
    is still waiting on her. A step is doable when it is neither done nor
    blocked and every step it `needs` is done.
    """
    done = {s.get("n") for s in plan.get("steps", []) if s.get("state") == "done"}
    for step in plan.get("steps", []):
        if step.get("state") in ("done", "blocked") or owner(step) != who:
            continue
        if all(n in done for n in step.get("needs") or []):
            return step
    return None


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


def credit_merged(evidence: list[dict]) -> list[dict]:
    """Mark charter steps done on the one kind of evidence that counts.

    A merged pull request, into the branch the charter says the project
    lives on, whose body names the step (`Charter-Step: <slug>#<n>`). A
    worker saying it finished is not that (§68); nor is a pull request
    closed unmerged, or one merged into some other branch. Idempotent — a
    step already done is left alone, so the pulse runs this every time.
    """
    credited = []
    for row in evidence or []:
        try:
            slug, n = str(row["slug"]), int(row["n"])
            plan = load(slug)
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            continue
        if not is_charter(plan) or plan.get("state") != "open":
            continue
        if not row.get("merged_at") or row.get("base") != plan["project"].get("base_branch"):
            continue
        step = next((s for s in plan["steps"] if s.get("n") == n), None)
        if step is None or step.get("state") == "done":
            continue
        set_step(slug, n, "done")
        journal.append("plan", f"plan:{slug}",
                       f"step {n} credited by merged PR #{row.get('pr')} ({row.get('url')})")
        credited.append({"slug": slug, "n": n, "pr": row.get("pr")})
    return credited


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
            print(f"  [{mark}] {s['n']}. {s['text']}"
                  + (f"  ({s['repo']})" if s.get("repo") else "")
                  + ("  (yours)" if is_charter(plan) and owner(s) == CALEB else ""))
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
