"""Private portfolio discovery and read-only GitHub health scanning.

Detailed repo state is stored only under Aletheia's private local state.  This
module never commits a portfolio snapshot to the public repo.  It deliberately
separates observation from action: finding a red CI run or an old PR creates no
authority to edit, merge, close, publish, spend, or send anything.
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import quote

from aletheia import gh, stateio
from aletheia.fleet import load_fleet

ROOT = stateio.private_dir("portfolio")
LATEST = ROOT / "latest.json"
MAX_REPOS = 40
MAX_ITEMS = 20
ACTIVE_DAYS = 180
FAIL_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}


class PortfolioUnavailable(RuntimeError):
    pass


def _safe_request(request, path: str, default):
    try:
        value = request("GET", path)
    except Exception:
        return default
    return value if value is not None else default


def _observed_request(request, path: str, default):
    """Return (observed, value); network/API failure is never empty-good-news."""
    try:
        value = request("GET", path)
    except Exception:
        return False, default
    return True, value if value is not None else default


def _parse_time(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _age_days(value: object, now: dt.datetime) -> int | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds() // 86400))


def _repo_id(full_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", full_name.casefold()).strip("-")[:120]


def discover(*, fleet: dict | None = None, request=gh.request,
             now: dt.datetime | None = None) -> list[dict]:
    """Discover the operator's non-archived repositories.

    Fleet entries are always included. GitHub discovery uses the public owner
    endpoint, so it still works when no PAT is configured; an authenticated
    request may additionally reveal private repos, which remain private state.
    """
    fleet = fleet or load_fleet()
    owner = str(fleet.get("owner") or "").strip()
    if not owner:
        raise PortfolioUnavailable("fleet owner is not configured")
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)

    by_name: dict[str, dict] = {}
    for key, cfg in (fleet.get("repos") or {}).items():
        if not isinstance(cfg, dict) or not cfg.get("github"):
            continue
        full = f"{owner}/{cfg['github']}"
        by_name[full.casefold()] = {
            "id": _repo_id(full), "key": key, "name": cfg["github"],
            "full_name": full, "private": False, "archived": False,
            "default_branch": cfg.get("default_branch") or "main",
            "summary": cfg.get("summary") or "", "source": "fleet",
            "updated_at": None,
        }

    paths = [f"/users/{quote(owner)}/repos?per_page=100&sort=updated"]
    if gh.token():
        paths.insert(0, "/user/repos?per_page=100&sort=updated&affiliation=owner")
    for path in paths:
        rows = _safe_request(request, path, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("archived"):
                continue
            full = str(row.get("full_name") or "")
            if not full or not full.casefold().startswith(owner.casefold() + "/"):
                continue
            age = _age_days(row.get("updated_at") or row.get("pushed_at"), now)
            if full.casefold() not in by_name and age is not None and age > ACTIVE_DAYS:
                continue
            prior = by_name.get(full.casefold(), {})
            by_name[full.casefold()] = {
                "id": _repo_id(full), "key": prior.get("key"),
                "name": str(row.get("name") or full.split("/", 1)[-1]),
                "full_name": full, "private": bool(row.get("private")),
                "archived": False,
                "default_branch": str(row.get("default_branch") or prior.get("default_branch") or "main"),
                "summary": str(row.get("description") or prior.get("summary") or "")[:500],
                "source": "github", "updated_at": row.get("updated_at") or row.get("pushed_at"),
            }
    return sorted(by_name.values(), key=lambda r: str(r.get("updated_at") or ""), reverse=True)[:MAX_REPOS]


def scan_repo(repo: dict, *, request=gh.request,
              now: dt.datetime | None = None) -> dict:
    """Read a bounded set of GitHub signals for one repository."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    full = str(repo["full_name"])
    encoded = "/".join(quote(part) for part in full.split("/", 1))
    branch = quote(str(repo.get("default_branch") or "main"), safe="")

    meta_ok, meta = _observed_request(request, f"/repos/{encoded}", {})
    commit_ok, commit = _observed_request(request, f"/repos/{encoded}/commits/{branch}", {})
    prs_ok, prs = _observed_request(request, f"/repos/{encoded}/pulls?state=open&per_page={MAX_ITEMS}", [])
    issues_ok, issues = _observed_request(request, f"/repos/{encoded}/issues?state=open&per_page={MAX_ITEMS}", [])
    runs_ok, runs = _observed_request(request, f"/repos/{encoded}/actions/runs?per_page=10", {})
    evidence_ok = bool(meta_ok and (commit_ok or prs_ok or issues_ok or runs_ok))

    if isinstance(meta, dict) and meta:
        repo = {**repo,
                "private": bool(meta.get("private", repo.get("private"))),
                "default_branch": meta.get("default_branch") or repo.get("default_branch"),
                "updated_at": meta.get("updated_at") or repo.get("updated_at")}
    commit_data = commit.get("commit", {}) if isinstance(commit, dict) else {}
    author = commit_data.get("author", {}) if isinstance(commit_data, dict) else {}
    commit_at = author.get("date") if isinstance(author, dict) else None
    commit_age = _age_days(commit_at, now)

    pr_rows = prs if prs_ok and isinstance(prs, list) else []
    issue_rows = [i for i in issues if isinstance(i, dict) and "pull_request" not in i] if issues_ok and isinstance(issues, list) else []
    run_rows = runs.get("workflow_runs", []) if runs_ok and isinstance(runs, dict) else []
    failing = [r for r in run_rows if isinstance(r, dict) and str(r.get("conclusion") or "") in FAIL_CONCLUSIONS]
    pending = [r for r in run_rows if isinstance(r, dict) and str(r.get("status") or "") != "completed"]

    problems: list[dict] = []
    if not evidence_ok:
        problems.append({"kind": "observation_unavailable", "severity": "high",
                         "detail": "live GitHub health evidence was unavailable"})
    if failing:
        newest = failing[0]
        problems.append({"kind": "ci_failure", "severity": "high",
                         "detail": str(newest.get("name") or "workflow")[:160],
                         "at": newest.get("updated_at") or newest.get("created_at")})
    if pending:
        problems.append({"kind": "ci_running", "severity": "info",
                         "detail": f"{len(pending)} workflow run(s) still active"})
    old_prs = [p for p in pr_rows if (_age_days(p.get("created_at"), now) or 0) >= 7]
    if old_prs:
        problems.append({"kind": "stale_pr", "severity": "medium",
                         "detail": f"{len(old_prs)} open PR(s) at least 7 days old"})
    if commit_ok and commit_age is not None and commit_age >= 30:
        problems.append({"kind": "stale_repo", "severity": "low",
                         "detail": f"default branch last changed {commit_age} days ago"})

    if not evidence_ok:
        score, state = None, "UNKNOWN"
    else:
        score = 100
        score -= 45 if failing else 0
        score -= min(20, len(old_prs) * 5)
        score -= 10 if commit_age is not None and commit_age >= 30 else 0
        score = max(0, score)
        state = "RED" if score < 60 else "YELLOW" if score < 85 else "GREEN"
    return {
        **repo,
        "health": state, "health_score": score,
        "latest_commit_at": commit_at, "latest_commit_age_days": commit_age,
        "open_prs": len(pr_rows), "open_issues": len(issue_rows),
        "active_runs": len(pending), "recent_failed_runs": len(failing),
        "observation_complete": evidence_ok, "problems": problems,
    }


def scan_all(*, fleet: dict | None = None, request=gh.request,
             now: dt.datetime | None = None) -> dict:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    repos = discover(fleet=fleet, request=request, now=now)
    scanned = [scan_repo(repo, request=request, now=now) for repo in repos]
    snapshot = {
        "version": 1, "scanned_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repos": scanned,
        "counts": {
            "total": len(scanned),
            "red": sum(r["health"] == "RED" for r in scanned),
            "yellow": sum(r["health"] == "YELLOW" for r in scanned),
            "green": sum(r["health"] == "GREEN" for r in scanned),
            "unknown": sum(r["health"] == "UNKNOWN" for r in scanned),
            "private": sum(bool(r.get("private")) for r in scanned),
        },
    }
    stateio.write_json_atomic(LATEST, snapshot)
    return snapshot


def load_latest() -> dict | None:
    if not LATEST.is_file():
        return None
    try:
        value = stateio.read_json(LATEST)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _priority(row: dict) -> tuple[int, str]:
    score = row.get("health_score")
    return (score if isinstance(score, int) else -1, str(row.get("name", "")))


def public_summary(snapshot: dict) -> str:
    """Receipt-safe summary: never names private repositories."""
    rows = list(snapshot.get("repos") or [])
    public = [r for r in rows if not r.get("private")]
    private_count = len(rows) - len(public)
    priority = sorted(public, key=_priority)
    trouble = [r for r in priority if r.get("health") != "GREEN"][:5]
    counts = snapshot.get("counts") or {}
    head = (f"Scanned {counts.get('total', len(rows))} projects: "
            f"{counts.get('red', 0)} red, {counts.get('yellow', 0)} yellow, "
            f"{counts.get('green', 0)} green, {counts.get('unknown', 0)} unknown.")
    if trouble:
        details = "; ".join(
            f"{r.get('name','?')} {str(r.get('health','')).lower()}"
            + (f" ({r['problems'][0]['detail']})" if r.get("problems") else "")
            for r in trouble)
        head += " Needs attention: " + details + "."
    if private_count:
        head += f" {private_count} private project(s) are included in the local detailed view."
    return head[:1800]
