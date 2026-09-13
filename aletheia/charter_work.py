"""Which charter step the builder does next — in code, not in a prompt.

The cloud builder ("Thea project builder") carried these rules as prose in
its routine prompt. Prose cannot be tested, and one of its rules was
quietly starving the whole loop: it skipped any charter whose BASE branch
had a real commit in the last twelve hours, meaning "someone is working
there, do not collide". But the builder never works on the base branch. It
branches off it and opens a pull request back into it, which is what every
contributor does to a branch that is moving. Measured 2026-09-13: the
builder had run daily for three days and opened zero pull requests,
because Caleb's other loops commit to exactly those base branches — the
AI_HANDOFF loop touches `claude/open-range-promo-video-4n7k7o` every hour,
so that charter could never be picked at all.

A moving base is not a collision. It is a merge, later. The rule that
replaces it is the one that was already there and actually means "work is
waiting for a human": an OPEN pull request from a `claude/thea-<slug>-`
branch.

The second thing this fixes is the orphan. On 2026-09-11 the builder did
pick holdco-platform, pushed `claude/thea-holdco-platform-s2-bdd5`, and
opened no pull request — it has no GitHub tools, and its fallback ("push
the branch, Aletheia opens the pull request") needs a Core that was never
switched on. The branch has sat there since. A pushed branch with no pull
request is not a reason to skip and not a reason to redo the work: it is
the work, finished, needing a door. `choose` returns it as FINISH_PR.

The core here is PURE — it takes facts somebody else observed and returns
a decision. That keeps the rules under test without the suite reaching the
network, and lets the same rules answer "why did nothing happen today?"
from a fixture.

**This module opens nothing and merges nothing.** The pull request for a
pushed branch is `project_merge.open_builder_prs`, which already exists
with its halt check, its machine-bound `code_trust` grant and its
one-attempt-per-head marker; a second path that opened pull requests
would be exactly the drift this repository keeps paying for. What was
missing was never the door — it was knowing which step to do, and saying
out loud why nothing happened.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, field

from aletheia import plans

THEA = "thea"

#: A builder branch: claude/thea-<slug>-s<n>-<hex>
BRANCH_RE = re.compile(r"^claude/thea-(?P<slug>.+)-s(?P<n>\d+)-[0-9a-f]+$")

BUILD = "build"          # do this step, from scratch
FINISH_PR = "finish_pr"  # the work is pushed; it needs a pull request


def branch_name(slug: str, n: int, nonce: str) -> str:
    """The one spelling of a builder branch, so nothing has to guess it."""
    return f"claude/thea-{slug}-s{n}-{nonce}"


def parse_branch(ref: str) -> tuple[str, int] | None:
    """(slug, step) for a builder branch, or None if it is not one."""
    m = BRANCH_RE.match(str(ref or "").strip())
    if not m:
        return None
    return m.group("slug"), int(m.group("n"))


@dataclass(frozen=True)
class RepoFacts:
    """What the caller observed about one charter's repository.

    `base_age_hours` is how long the base branch has gone without a commit;
    None means the branch does not exist yet, which sorts as the oldest
    (a brand-new venture is the most neglected thing there is).
    """
    open_thea_prs: tuple[str, ...] = ()      # branch refs with an OPEN pull request
    thea_branches: tuple[str, ...] = ()      # every claude/thea-* branch pushed
    base_age_hours: float | None = None


@dataclass(frozen=True)
class Decision:
    action: str                  # BUILD or FINISH_PR
    slug: str
    n: int
    step: dict
    branch: str = ""             # set for FINISH_PR: the branch already pushed
    why: str = ""


@dataclass
class Survey:
    """Every charter, and what the builder concluded about each one."""
    decision: Decision | None = None
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (slug, reason)

    def as_dict(self) -> dict:
        d = self.decision
        return {
            "action": d.action if d else "none",
            "slug": d.slug if d else "",
            "n": d.n if d else 0,
            "branch": d.branch if d else "",
            "text": (d.step.get("text") if d else "") or "",
            "why": d.why if d else "nothing to do",
            "skipped": [{"slug": s, "reason": r} for s, r in self.skipped],
        }


def _orphan_branches(slug: str, facts: RepoFacts) -> list[tuple[str, int]]:
    """Builder branches for this charter that are pushed with no open PR."""
    out = []
    for ref in facts.thea_branches:
        parsed = parse_branch(ref)
        if parsed and parsed[0] == slug and ref not in facts.open_thea_prs:
            out.append((ref, parsed[1]))
    return sorted(out, key=lambda r: r[1])


def _open_for(slug: str, facts: RepoFacts) -> list[str]:
    return [r for r in facts.open_thea_prs if (parse_branch(r) or ("", 0))[0] == slug]


def consider(plan: dict, facts: RepoFacts) -> tuple[Decision | None, str]:
    """What the builder should do about ONE charter, and why not, if not.

    Order matters: a pushed branch with no pull request is finished work
    that never got a door, and handing it one comes before starting
    anything new — otherwise the same step is built again and again while
    yesterday's result rots on the remote.
    """
    slug = str(plan.get("slug") or "")
    if not plans.is_charter(plan):
        return None, "not a charter — no project block"
    if plan.get("state") != "open":
        return None, f"state is {plan.get('state')!r}, not open"

    orphans = _orphan_branches(slug, facts)
    if orphans:
        ref, n = orphans[0]
        step = next((s for s in plan.get("steps", []) if s.get("n") == n), None)
        if step is not None:
            return Decision(FINISH_PR, slug, n, step, branch=ref,
                            why="pushed with no pull request"), ""
        # A branch for a step the charter no longer has. Say so rather than
        # silently ignoring it — somebody renumbered a charter under it.
        return None, f"branch {ref} names step {n}, which this charter no longer has"

    waiting = _open_for(slug, facts)
    if waiting:
        return None, f"work is waiting for review ({', '.join(sorted(waiting))})"

    step = plans.next_for(plan, THEA)
    if step is None:
        return None, "no step of hers is doable — hers are done, blocked, or waiting on his"
    return Decision(BUILD, slug, int(step.get("n") or 0), step,
                    why="her next doable step"), ""


def choose(charters: list[dict], facts: dict[str, RepoFacts]) -> Survey:
    """One step, across every charter — or nothing, with a reason each.

    Finishing a pushed branch always beats starting new work. Otherwise the
    most neglected base branch wins, so attention spreads instead of
    piling onto whichever charter sorts first.
    """
    out = Survey()
    candidates: list[Decision] = []
    for plan in charters or []:
        slug = str(plan.get("slug") or "")
        decision, reason = consider(plan, facts.get(slug, RepoFacts()))
        if decision is None:
            out.skipped.append((slug, reason))
        else:
            candidates.append(decision)

    if not candidates:
        return out

    def rank(d: Decision) -> tuple[int, float]:
        age = facts.get(d.slug, RepoFacts()).base_age_hours
        # FINISH_PR first; then the longest-neglected base (None = forever).
        return (0 if d.action == FINISH_PR else 1,
                -(float("inf") if age is None else age))

    candidates.sort(key=rank)
    out.decision = candidates[0]
    for other in candidates[1:]:
        out.skipped.append((other.slug, "another charter was picked this run"))
    return out


def _hours_since(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return max(0.0, (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600.0)


def observe(plan: dict, fleet: dict, *, request) -> RepoFacts:
    """What GitHub says about one charter — READS ONLY.

    `request` is injected so the suite never reaches the network. A repo
    this token cannot see answers empty facts rather than raising: not
    being able to look is a fact about the token, not about the work.
    """
    project = plan.get("project") or {}
    repo = (fleet.get("repos") or {}).get(project.get("repo")) or {}
    owner = repo.get("owner") or fleet.get("owner")
    name = repo.get("github")
    if not (owner and name):
        return RepoFacts()
    full = f"{owner}/{name}"

    def get(path):
        try:
            out = request("GET", path)
        except Exception:
            return None
        return out if isinstance(out, list) else None

    branches = [str(b.get("name") or "") for b in (get(f"/repos/{full}/branches?per_page=100") or [])]
    branches = [b for b in branches if parse_branch(b)]

    open_prs = []
    for pr in get(f"/repos/{full}/pulls?state=open&per_page=100") or []:
        ref = str(((pr or {}).get("head") or {}).get("ref") or "")
        if parse_branch(ref):
            open_prs.append(ref)

    age = None
    base = project.get("base_branch")
    if base:
        commits = get(f"/repos/{full}/commits?sha={base}&per_page=1") or []
        if commits:
            age = _hours_since((((commits[0].get("commit") or {}).get("committer") or {})
                                .get("date")))
    return RepoFacts(open_thea_prs=tuple(open_prs), thea_branches=tuple(branches),
                     base_age_hours=age)


def survey(charters: list[dict], fleet: dict, *, request) -> Survey:
    """Look at every charter on GitHub, then decide."""
    facts = {str(p.get("slug")): observe(p, fleet, request=request) for p in charters}
    return choose(charters, facts)


def pr_body(slug: str, n: int, step_text: str, notes: str = "") -> str:
    """The handoff. `plans.credit_merged` reads the first line and will not
    credit a step without it, so it is written here rather than by whoever
    remembers the format."""
    lines = [f"Charter-Step: {slug}#{n}", "", f"**Step {n}:** {step_text}".rstrip()]
    if notes:
        lines += ["", notes.rstrip()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Say what to do next. The builder runs this instead of re-deriving
    the rules from its own prompt every night."""
    ap = argparse.ArgumentParser(description="Which charter step is next")
    ap.add_argument("--facts", help="JSON file of observed repo facts "
                                    "(default: assume nothing is pushed anywhere)")
    ap.add_argument("--live", action="store_true",
                    help="read branches and pull requests from GitHub")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args(argv)

    charters = [p for p in plans.all_plans() if plans.is_charter(p)]

    if args.live:
        from aletheia import gh
        from aletheia.fleet import load_fleet
        result = survey(charters, load_fleet(), request=gh.request)
    else:
        facts: dict[str, RepoFacts] = {}
        if args.facts:
            raw = json.loads(open(args.facts, encoding="utf-8").read())
            for slug, f in (raw or {}).items():
                facts[slug] = RepoFacts(
                    open_thea_prs=tuple(f.get("open_thea_prs") or ()),
                    thea_branches=tuple(f.get("thea_branches") or ()),
                    base_age_hours=f.get("base_age_hours"),
                )
        result = choose(charters, facts)

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
        return 0

    d = result.decision
    if d is None:
        print("Nothing to build.")
    elif d.action == FINISH_PR:
        print(f"OPEN A PULL REQUEST for {d.branch} ({d.slug} step {d.n}).")
        print(f"  step: {d.step.get('text')}")
        print("  the work is already pushed — do not build it again.")
    else:
        print(f"BUILD {d.slug} step {d.n}: {d.step.get('text')}")
    for slug, reason in result.skipped:
        print(f"  skipped {slug}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
