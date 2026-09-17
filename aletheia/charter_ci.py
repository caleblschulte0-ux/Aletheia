"""Red CI on the branch a charter really lives on is work the local tier can try.

The project loop watches CI only on DEFAULT branches (`project_loop._ci_work`),
on purpose: its repair pull request targets the default branch. But his
projects do not live there. Barkly lives on `claude/barkley-mvp-mobile-qbegtj`,
where "Barkly CI" has failed on every push, and nothing turned that into work:
the charter step "get Barkly CI green" sat BLOCKED_MODEL waiting for Claude.

This module OBSERVES (reads only) the latest completed run of every workflow on
each open charter's branch, keeps what is red in a small cache in private state,
and the work engine's `charter_ci` source turns each red workflow into an item:
READY for the local tier (`work_runners`), which checks out that branch, runs
what it can, repairs a bounded failure on a branch, or investigates it into a
packet for a stronger model. The item's identity carries the run id, so a NEW
red run is new evidence and a green one makes the item disappear.

Reads are made at most every `TTL_S` (a work session refreshes it; a beat never
reaches the network for it). A repository that cannot be read is a note, never
an empty world.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Callable
from urllib.parse import quote

from aletheia import stateio, work_states as ws

TTL_S = 30 * 60
FAIL_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}
MAX_RUNS = 30
#: A charter step whose words are about its CI is the same work as the red run.
CI_WORDS = re.compile(r"\bCI\b|\bchecks?\b.*\b(?:green|pass)|\bworkflows?\b|\bbuild is (?:red|failing)\b")


def cache_path():
    return stateio.private_dir("work") / "charter_ci.json"


def _now(now: dt.datetime | None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def load() -> dict:
    try:
        value = stateio.read_json(cache_path())
    except (OSError, ValueError):
        return {"observed_at": None, "failures": [], "notes": []}
    return value if isinstance(value, dict) else {"observed_at": None, "failures": [], "notes": []}


def failing_runs(full_name: str, branch: str, *, get: Callable[[str], object] | None = None) -> list[dict]:
    """The latest COMPLETED run of each workflow on `branch`, when it is red, with its
    failed jobs and steps. Reads only."""
    from aletheia import project_checkout
    get = get or project_checkout.api_get
    data = get(f"/repos/{full_name}/actions/runs?branch={quote(branch, safe='')}&per_page={MAX_RUNS}")
    rows = data.get("workflow_runs") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise LookupError(f"the CI runs of {full_name}@{branch} could not be read")
    latest: dict[str, dict] = {}
    for run in rows:
        if not isinstance(run, dict) or run.get("status") != "completed":
            continue
        key = str(run.get("path") or run.get("name") or "workflow")
        if key not in latest:
            latest[key] = run            # newest first from the API
    out = []
    for key, run in latest.items():
        if str(run.get("conclusion") or "") not in FAIL_CONCLUSIONS:
            continue
        failed = []
        jobs = get(f"/repos/{full_name}/actions/runs/{int(run.get('id') or 0)}/jobs?per_page=30")
        for job in (jobs.get("jobs") if isinstance(jobs, dict) else None) or []:
            if not isinstance(job, dict) or str(job.get("conclusion") or "") in ("success", "skipped"):
                continue
            steps = [str(s.get("name")) for s in job.get("steps") or []
                     if isinstance(s, dict) and s.get("conclusion") == "failure"]
            failed.append({"job": str(job.get("name") or ""), "steps": steps})
        out.append({"workflow": str(run.get("name") or key), "workflow_path": str(run.get("path") or ""),
                    "run_id": int(run.get("id") or 0), "head_sha": str(run.get("head_sha") or ""),
                    "conclusion": str(run.get("conclusion") or ""), "url": str(run.get("html_url") or ""),
                    "at": str(run.get("updated_at") or run.get("created_at") or ""), "failed": failed})
    return out


def refresh(*, now: dt.datetime | None = None, force: bool = False,
            get: Callable[[str], object] | None = None) -> dict:
    """Look again at every open charter's branch, at most every TTL_S. Never raises."""
    now = _now(now)
    cached = load()
    seen = cached.get("observed_at")
    if not force and seen:
        try:
            age = (now - dt.datetime.strptime(seen, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc))
            if age.total_seconds() < TTL_S:
                return cached
        except ValueError:
            pass
    from aletheia import local_repair, plans
    failures, notes = [], []
    for plan in plans.all_plans():
        if plan.get("state") != "open" or not plans.is_charter(plan):
            continue
        slug = str(plan.get("slug") or "")
        try:
            target = local_repair.charter_target(slug, plan=plan)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{slug}: {exc}")
            continue
        try:
            runs = failing_runs(target["repo"], target["base_ref"], get=get)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{slug}: {exc}")
            continue
        for run in runs:
            failures.append({"slug": slug, "title": str(plan.get("title") or slug), "repo": target["repo"],
                             "branch": target["base_ref"], "subdir": target["subdir"], **run})
    value = {"observed_at": _stamp(now), "failures": failures, "notes": notes[-10:]}
    try:
        cache_path().parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(cache_path(), value)
    except OSError:
        pass
    return value


def _same_step(slug: str) -> str:
    """The id of HER unfinished charter step that is about CI, if there is exactly one."""
    from aletheia import plans
    try:
        plan = plans.load(slug)
    except Exception:  # noqa: BLE001
        return ""
    hits = [s for s in plan.get("steps") or [] if isinstance(s, dict) and s.get("state") != "done"
            and plans.owner(s) != plans.CALEB and CI_WORDS.search(str(s.get("text") or ""))]
    named = [s for s in hits if re.search(r"\bCI\b", str(s.get("text") or ""))]
    for group in (named, hits):
        if len(group) == 1:
            return f"plan:{slug}#{group[0].get('n')}"
    return ""


def _steps_text(failed: list[dict]) -> str:
    names = [s for f in failed for s in f.get("steps") or []] or [f.get("job") for f in failed if f.get("job")]
    return ", ".join(dict.fromkeys(n for n in names if n))[:160]


def source(now: dt.datetime) -> list[dict]:
    """Every red workflow on a charter branch, from the cache. Reads no network."""
    from aletheia import work_engine as we
    out = []
    for row in load().get("failures") or []:
        slug = str(row.get("slug") or "")
        workflow_key = re.sub(r"[^a-z0-9]+", "-", str(row.get("workflow_path") or row.get("workflow")).lower()).strip("-")
        failing = _steps_text(row.get("failed") or [])
        title = (f"{row.get('title')}: the {row.get('workflow')} CI run is red on its branch"
                 + (f" ({failing})" if failing else ""))
        same = _same_step(slug)
        out.append(we.item(f"ci:{slug}@{workflow_key}", "charter_ci", title, ws.READY,
                           requires=["reasoning", "network", "code_execution"],
                           next="check out the branch, reproduce and repair or investigate it",
                           native_state=f"run:{row.get('run_id')}", priority=2, owner="thea",
                           kind="charter_ci", updated=str(row.get("at") or ""),
                           payload={**{k: row.get(k) for k in ("slug", "repo", "branch", "subdir", "workflow",
                                                                "workflow_path", "run_id", "head_sha", "url",
                                                                "failed")},
                                    **({"same_as": same} if same else {})}))
    return out
