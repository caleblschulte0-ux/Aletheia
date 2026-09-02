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

from aletheia import code_trust, code_worker, gh, policy, portfolio, stateio

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
        objective = f"Resolve GitHub issue #{number}: {title}"
        if body:
            objective += "\n\nIssue details:\n" + body[:2800]
        return {"task_id": f"issue-{number}", "kind": "issue", "objective": objective[:4000]}
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
            label = str(job.get("name") or "job")
            if failed_steps:
                label += ": " + ", ".join(failed_steps[:5])
            details.append(label[:300])
    except Exception:
        pass
    workflow = str(run.get("name") or "CI workflow")
    objective = (
        f"Repair the current failing CI for {workflow} (run {run_id}). "
        "Do not edit GitHub workflow files; fix only safe application/test code. "
        "If the root cause requires a protected workflow, credential, policy, or governance path, make no change."
    )
    if details:
        objective += " Failing jobs/steps: " + "; ".join(details[:8])
    return {"task_id": f"ci-{run_id}", "kind": "ci", "objective": objective[:4000]}


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
                repo["full_name"], work["objective"], task_id=work["task_id"], request=request
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
    sub.add_parser("status")
    args = ap.parse_args(argv)
    try:
        value = cycle(daily_limit=args.daily_limit) if args.cmd == "once" else status()
        print(json.dumps(value, indent=2))
        return 0 if value.get("status") not in {"ERROR", "CORRUPT"} else 1
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
