"""Continuous project triage -> reviewed code PR loop.

Each scheduled cycle observes the portfolio, reconciles prior PR evidence, and at
most once attempts one bounded public-repository repair sourced from a real open
GitHub issue or a current CI failure. It does not invent product direction, edit
private repositories, or merge its own pull requests.
"""
from __future__ import annotations

import argparse
import json
from urllib.parse import quote

from aletheia import (code_trust, code_worker, gh, mission, policy, portfolio,
                      stateio)

ROOT = stateio.private_dir("project-loop")
LATEST = ROOT / "latest.json"
DEFAULT_DAILY_LIMIT = 3
MAX_RECONCILE = 20
SKIP_LABELS = {"wontfix", "duplicate", "question", "invalid", "no-auto", "manual-only"}


class ProjectLoopError(RuntimeError):
    pass


def _enc_repo(full: str) -> str:
    parts = str(full).split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise ProjectLoopError("repo name must be owner/name")
    return "/".join(quote(p, safe="") for p in parts)


def _open_auto_pr_exists(repo: dict, *, request=gh.request) -> bool:
    encoded = _enc_repo(repo["full_name"])
    try:
        rows = request("GET", f"/repos/{encoded}/pulls?state=open&per_page=30")
    except Exception:
        return True
    if not isinstance(rows, list):
        return True
    for pr in rows:
        head = (pr.get("head") or {}) if isinstance(pr, dict) else {}
        if str(head.get("ref") or "").startswith("thea-auto/"):
            return True
    return False


def _issue_work(repo: dict, *, request=gh.request) -> dict | None:
    encoded = _enc_repo(repo["full_name"])
    try:
        rows = request("GET", f"/repos/{encoded}/issues?state=open&sort=updated&direction=desc&per_page=30")
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    for issue in rows:
        if not isinstance(issue, dict) or issue.get("pull_request"):
            continue
        labels = {
            str((x.get("name") if isinstance(x, dict) else x) or "").casefold()
            for x in issue.get("labels", [])
        }
        if labels & SKIP_LABELS:
            continue
        number = issue.get("number")
        title = str(issue.get("title") or "").strip()
        if not isinstance(number, int) or not title:
            continue
        body = str(issue.get("body") or "").strip()
        # The TITLE and the BODY are both written by strangers. They travel
        # as `evidence`, never inside the objective: the objective is the
        # only string the models take as instruction, and it is composed
        # here from facts we control (the repository, the issue number).
        objective = f"Resolve open GitHub issue #{number} in {repo['full_name']}"
        evidence = f"Issue title: {title}"
        if body:
            evidence += "\n\nIssue body:\n" + body
        return {"task_id": f"issue-{number}", "kind": "issue",
                "objective": objective[:4000],
                "evidence": code_worker.sanitize_external(evidence)}
    return None


def _ci_work(repo: dict, *, request=gh.request) -> dict | None:
    encoded = _enc_repo(repo["full_name"])
    try:
        data = request("GET", f"/repos/{encoded}/actions/runs?per_page=20")
    except Exception:
        return None
    rows = data.get("workflow_runs", []) if isinstance(data, dict) else []
    failed = [
        r for r in rows if isinstance(r, dict)
        and str(r.get("status") or "") == "completed"
        and str(r.get("conclusion") or "") in portfolio.FAIL_CONCLUSIONS
    ]
    if not failed:
        return None
    run = failed[0]
    run_id = run.get("id")
    if not isinstance(run_id, int):
        return None
    details = []
    try:
        jobs = request("GET", f"/repos/{encoded}/actions/runs/{run_id}/jobs?per_page=30")
        for job in (jobs.get("jobs", []) if isinstance(jobs, dict) else []):
            if not isinstance(job, dict) or str(job.get("conclusion") or "") == "success":
                continue
            failed_steps = [
                str(step.get("name") or "") for step in job.get("steps", [])
                if isinstance(step, dict) and str(step.get("conclusion") or "") == "failure"
            ]
            # Each name is its OWN untrusted string, so each is sanitized on
            # its own: a role header ("System: ...") sits at the start of a
            # job name and would be mid-line — invisible to a line anchor —
            # once the names were joined into one blob.
            label = code_worker.sanitize_external(str(job.get("name") or "job"))[:120] or "job"
            if failed_steps:
                clean = [code_worker.sanitize_external(name)[:80] for name in failed_steps[:5]]
                label += ": " + ", ".join(name for name in clean if name)
            details.append(label[:300])
    except Exception:
        pass
    objective = (
        f"Repair the current failing CI run {run_id} in {repo['full_name']}. "
        "Do not edit GitHub workflow files; fix only safe application/test code. "
        "If the root cause requires a protected workflow, credential, policy, or governance path, make no change."
    )
    # Job and step names come from the repository's workflow files, which any
    # contributor may edit — untrusted for the same reason an issue body is.
    evidence = ("Failing jobs/steps: " + "; ".join(details[:8])) if details else ""
    return {"task_id": f"ci-{run_id}", "kind": "ci", "objective": objective[:4000],
            "evidence": code_worker.sanitize_external(evidence)}


def choose_work(repo: dict, *, request=gh.request) -> dict | None:
    if repo.get("private") or not repo.get("observation_complete"):
        return None
    if _open_auto_pr_exists(repo, request=request):
        return None
    return _issue_work(repo, request=request) or _ci_work(repo, request=request)


def _repo_priority(repo: dict) -> tuple[int, int, str]:
    health = {"RED": 0, "YELLOW": 1, "GREEN": 2, "UNKNOWN": 3}.get(str(repo.get("health")), 3)
    issues = int(repo.get("open_issues") or 0)
    return (health, -issues, str(repo.get("full_name") or ""))


def reconcile_prior(*, request=gh.request, limit: int = MAX_RECONCILE) -> list[dict]:
    out = []
    for run in code_worker.all_runs()[-max(0, int(limit)):]:
        if run.get("status") in {"MERGED", "CLOSED", "REVIEW_REJECTED"}:
            continue
        repo, task = run.get("repo"), run.get("task_id")
        if not isinstance(repo, str) or not isinstance(task, str):
            continue
        try:
            refreshed = code_worker.reconcile(repo, task, request=request)
        except Exception:
            continue
        if refreshed:
            out.append(refreshed)
    return out


def cycle(*, request=gh.request, daily_limit: int = DEFAULT_DAILY_LIMIT) -> dict:
    if type(daily_limit) is not int or not 1 <= daily_limit <= 20:
        raise ValueError("daily_limit must be 1..20")
    policy.ensure_not_halted()
    grant = code_trust.active()
    if not grant:
        result = {
            "version": 1, "status": "BLOCKED", "reason": "code_work_grant_required",
            "updated_at": stateio.utcnow(),
        }
        stateio.write_json_atomic(LATEST, result)
        return result

    reconciled = reconcile_prior(request=request)
    if code_trust.claims_since(hours=24) >= daily_limit:
        result = {
            "version": 1, "status": "THROTTLED", "daily_limit": daily_limit,
            "reconciled": len(reconciled), "updated_at": stateio.utcnow(),
        }
        stateio.write_json_atomic(LATEST, result)
        return result

    snapshot = portfolio.scan_all(request=request)
    public = [r for r in snapshot.get("repos", []) if isinstance(r, dict) and not r.get("private")]
    for repo in sorted(public, key=_repo_priority):
        work = choose_work(repo, request=request)
        if not work:
            continue
        try:
            run = code_worker.prepare_pr(
                repo["full_name"], work["objective"], task_id=work["task_id"],
                evidence=work.get("evidence", ""), request=request
            )
            result = {
                "version": 1, "status": "WORKED", "repo": repo["full_name"],
                "source": work["kind"], "task_id": work["task_id"],
                "work_status": run.get("status"), "pr_url": run.get("pr_url"),
                "reconciled": len(reconciled), "updated_at": stateio.utcnow(),
            }
        except Exception as exc:
            result = {
                "version": 1, "status": "ERROR", "repo": repo["full_name"],
                "source": work["kind"], "task_id": work["task_id"],
                "reason": type(exc).__name__, "reconciled": len(reconciled),
                "updated_at": stateio.utcnow(),
            }
        stateio.write_json_atomic(LATEST, result)
        return result

    result = {
        "version": 1, "status": "IDLE", "reconciled": len(reconciled),
        "scanned": snapshot.get("counts", {}).get("total", len(public)),
        "updated_at": stateio.utcnow(),
    }
    stateio.write_json_atomic(LATEST, result)
    return result


def status() -> dict:
    if not LATEST.is_file():
        return {"status": "NEVER_RUN"}
    try:
        value = stateio.read_json(LATEST)
    except ValueError:
        return {"status": "CORRUPT"}
    return value if isinstance(value, dict) else {"status": "CORRUPT"}


SLICE_MAX = 3


def run_mission_slice(*, request=gh.request, slice_max: int = SLICE_MAX) -> dict:
    """Work the ACTIVE MISSION across every repository, not one and stop.

    `cycle()` returns after a single repair in a single repository. That is
    correct for an unattended 30-minute heartbeat and it is why "look at all
    my projects and fix the problems" was structurally impossible: six repos
    and a trickle of one item per half hour is not an answer to that request,
    it is a rounding error.

    A slice is bounded rather than unbounded — at most `slice_max` items, so
    the scheduled task keeps its execution limit and a crash costs one slice
    instead of the mission — but it sweeps ALL repositories and keeps going
    until the mission's own budget stops it. Progress is charged to the
    mission after each item, durably, so the next slice resumes rather than
    restarting (§27).

    HALT is re-read between every repository. A kill switch that only applies
    at the top of a run that lasts twenty minutes is a suggestion.
    """
    live = mission.active()
    if not live:
        return {"version": 1, "status": "NO_MISSION",
                "detail": "no mission is running; `python -m aletheia.mission "
                          "start fix_projects` authorizes one",
                "updated_at": stateio.utcnow()}
    grant = code_trust.active()
    if not grant:
        return {"version": 1, "status": "BLOCKED",
                "reason": "code_work_grant_required", "updated_at": stateio.utcnow()}

    reconciled = reconcile_prior(request=request)
    snapshot = portfolio.scan_all(request=request)
    public = [r for r in snapshot.get("repos", [])
              if isinstance(r, dict) and not r.get("private")]

    done, errors = [], []
    for repo in sorted(public, key=_repo_priority):
        if len(done) >= slice_max:
            break
        # Re-read both between repositories: the operator may have halted, and
        # the mission may have spent its last unit on the previous repository.
        policy.ensure_not_halted()
        if not mission.active():
            break
        work = choose_work(repo, request=request)
        if not work:
            continue
        try:
            run = code_worker.prepare_pr(
                repo["full_name"], work["objective"], task_id=work["task_id"],
                evidence=work.get("evidence", ""), request=request)
        except policy.Halted:
            raise
        except Exception as exc:
            errors.append({"repo": repo["full_name"], "reason": type(exc).__name__})
            mission.note(f"{repo['full_name']}: {type(exc).__name__}", spent=0)
            continue
        opened = run.get("status") == "PR_OPEN"
        done.append({"repo": repo["full_name"], "source": work["kind"],
                     "status": run.get("status"), "pr_url": run.get("pr_url")})
        # Only an opened pull request spends budget. A change the reviewer
        # refused cost time but produced nothing, and charging him for it
        # would end the mission early on exactly the days it worked hardest.
        mission.note(
            f"{repo['full_name']}: {run.get('status')}"
            + (f" {run.get('pr_url')}" if run.get("pr_url") else ""),
            spent=1 if opened else 0)

    result = {
        "version": 1, "status": "SWEPT", "mission": live["id"],
        "repos_scanned": len(public), "worked": done, "errors": errors,
        "reconciled": len(reconciled), "updated_at": stateio.utcnow(),
    }
    stateio.write_json_atomic(LATEST, result)
    return result


def main(argv: list[str] | None = None) -> int:
    # This runs as its OWN Windows scheduled task every 30 minutes, not as a
    # child of the supervisor — so the supervisor's environment scrubbing never
    # reaches it, and Task Scheduler hands it the user's environment. If the
    # operator ever sets the ChatGPT browser lease as a persistent user
    # variable, an unattended code loop would inherit the right to open his
    # signed-in ChatGPT on screen. Drop it before anything can read it.
    from aletheia import browser_reasoner
    browser_reasoner.drop_lease()
    ap = argparse.ArgumentParser(description="Aletheia continuous project repair loop.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    once = sub.add_parser("once")
    once.add_argument("--daily-limit", type=int, default=DEFAULT_DAILY_LIMIT)
    p_sweep = sub.add_parser(
        "sweep", help="work the active mission across every repository")
    p_sweep.add_argument("--max", type=int, default=SLICE_MAX)
    sub.add_parser("status")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "once":
            value = cycle(daily_limit=args.daily_limit)
        elif args.cmd == "sweep":
            value = run_mission_slice(slice_max=args.max)
        else:
            value = status()
        print(json.dumps(value, indent=2))
        return 0 if value.get("status") not in {"ERROR", "CORRUPT"} else 1
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
