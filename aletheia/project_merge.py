"""Merge finished project work — only on the projects he said she may.

THE RULING, 2026-09-10. Asked who merges a finished piece of project work
once the tests pass, he picked this option, in these words:

    "She merges low-risk (Recommended) — She merges projects you mark
    low-risk (Barkly, promo video) after tests plus an independent review.
    The trader and Aletheia's own code still wait for you."

WHY A MERGE PATH EXISTS AT ALL, in a repository where every other page says
a human merges. The same afternoon he said what he needs: he starts a
project hot, drifts inside two weeks, and needs her to keep building it.
A builder whose pull requests wait on a man who has stopped looking
produces a queue, not a product — the project stalls exactly as before,
with more code sitting in it. So on the charters he marked low-risk,
finished and verified work lands without him.

WHAT IT WILL NOT DO — each enforced below, not described:

- Touch `NEVER_MERGE`: the trader and Aletheia, named by him. The charter's
  risk field is not trusted for those; a charter edited to say "low" buys
  nothing, and those repositories are never even read here.
- Merge into a repository's DEFAULT branch. The projects carried today live
  on their own long-running branches, and landing on `main` is a release.
  Releases are his.
- Merge work it did not see built: the head must be a builder branch
  (`claude/thea-`) in the same repository, never a fork, and the body must
  name a charter step that is the builder's, not his.
- Merge on red, running or ABSENT checks. No CI is not a pass.
- Merge a change to `.github/`, a registry, a secret or any path the code
  worker protects, or a file with no text diff to read.
- Merge on a same-model review. The builder writes with the plan model;
  the review must come from another model, or there is no merge.
- Run without BOTH his machine-bound code-work grant and the ruling switch
  (`python -m aletheia.project_merge on|off|status`), while halted, or past
  MAX_MERGES_PER_DAY.

A review is asked ONCE per head commit and remembered. The local loop made
150 proposals and every one was declined, many of them the same question
asked again half an hour later; a gate that re-asks a model every cycle
spends his subscription to learn nothing new.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from urllib.parse import quote

from aletheia import (code_trust, code_worker, gh, journal, plans, policy,
                      reasoner, stateio)
from aletheia.fleet import load_fleet

ACTOR = "aletheia-project-merge"
ROOT = stateio.private_dir("project-merge")
RULING_PATH = ROOT / "ruling.json"
MERGES_DIR = ROOT / "merges"
REVIEWS_DIR = ROOT / "reviews"
OPENED_DIR = ROOT / "opened"

BUILDER_PREFIX = "claude/thea-"
# His words: "The trader and Aletheia's own code still wait for you."
NEVER_MERGE = frozenset({"aletheia", "schwab-trader"})
MAX_MERGES_PER_DAY = 6
MAX_FILES = 40
MAX_CHANGED_LINES = 3_000
GREEN = frozenset({"success", "neutral", "skipped"})
# The cloud builder is told to build with this model, so the review must not.
BUILDER_MODEL = reasoner.PLAN_MODEL
RULING_WORDS = ("She merges low-risk (Recommended) — She merges projects you mark "
                "low-risk (Barkly, promo video) after tests plus an independent review. "
                "The trader and Aletheia's own code still wait for you.")
# claude/thea-<charter slug>-s<step>[-anything]
BRANCH_STEP = re.compile(r"^claude/thea-([a-z0-9][a-z0-9-]*?)-s(\d+)(?:-|$)")


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _enc(full: str) -> str:
    return "/".join(quote(part, safe="") for part in str(full).split("/", 1))


def _record_id(*parts: object) -> str:
    raw = re.sub(r"[^a-z0-9-]+", "-", "-".join(str(p) for p in parts).casefold()).strip("-")
    return stateio.safe_id(raw[:150] or "record", name="merge record id")


# ---- the ruling switch -------------------------------------------------------

def ruling() -> dict | None:
    if not RULING_PATH.is_file():
        return None
    try:
        value = stateio.read_json(RULING_PATH)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("enabled") is True else None


def enable(words: str, *, via: str) -> dict:
    """Record his ruling, in his words, and turn merging on."""
    policy.ensure_not_halted()
    words = " ".join(str(words or "").split())
    if not words:
        raise ValueError("a ruling is recorded in his words, and there were none")
    record = {"version": 1, "enabled": True, "words": words, "via": via,
              "recorded_at": stateio.utcnow()}
    stateio.write_json_atomic(RULING_PATH, record)
    journal.append("decision", "code:merge",
                   f"low-risk project merges ENABLED on his ruling: {words[:300]}", actor=via)
    return record


def disable(*, via: str) -> bool:
    current = ruling()
    if not current:
        return False
    current.update({"enabled": False, "disabled_at": stateio.utcnow(), "disabled_via": via})
    stateio.write_json_atomic(RULING_PATH, current)
    journal.append("decision", "code:merge", "low-risk project merges DISABLED", actor=via)
    return True


def _merges_since(now: dt.datetime, hours: int = 24) -> int:
    if not MERGES_DIR.is_dir():
        return 0
    cutoff = now - dt.timedelta(hours=hours)
    count = 0
    for path in MERGES_DIR.glob("*.json"):
        try:
            stamp = str(stateio.read_json(path).get("merged_at") or "")
            when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except (OSError, ValueError, AttributeError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        if when >= cutoff:
            count += 1
    return count


def status() -> dict:
    current = ruling()
    return {"ruling": bool(current), "words": (current or {}).get("words"),
            "recorded_at": (current or {}).get("recorded_at"),
            "grant_active": bool(code_trust.active()),
            "merged_last_24h": _merges_since(_now()), "max_per_day": MAX_MERGES_PER_DAY,
            "never_merge": sorted(NEVER_MERGE)}


# ---- the gates -----------------------------------------------------------------

def named_step(plan: dict, body: object) -> int | None:
    """The charter step a pull request says it builds, if it names this charter."""
    for slug, n in plans.CHARTER_STEP.findall(str(body or "")):
        if slug.casefold() == plan.get("slug"):
            return int(n)
    return None


def diff_text(files: list[dict]) -> str:
    return "".join(
        f"--- a/{f.get('previous_filename') or f.get('filename')}\n"
        f"+++ b/{f.get('filename')}\n{f.get('patch') or ''}\n"
        for f in files if isinstance(f, dict))


def refusal(plan: dict, meta: dict, pr: dict, files: list[dict], checks: list[dict]) -> str:
    """Why she may not merge this pull request, or "" if she may.

    Pure — everything is passed in — so every gate is tested without a
    network, and a request that failed upstream arrives as an empty value
    that some gate refuses, never as a skipped check.
    """
    project = plan.get("project") if isinstance(plan.get("project"), dict) else {}
    full = str(meta.get("full_name") or "")
    name = full.split("/", 1)[-1]
    if not full or name.casefold() in NEVER_MERGE:
        return f"{name or 'this repository'} is one he merges himself"
    if project.get("risk") != "low":
        return "the charter does not mark this project low-risk"
    if meta.get("private"):
        return "it is a private repository"
    base = str((pr.get("base") or {}).get("ref") or "")
    if not base or base != project.get("base_branch"):
        return f"it targets {base or 'no branch'}, not the charter's branch"
    if base == str(meta.get("default_branch") or ""):
        return "merging into the default branch is a release, and releases are his"
    head = pr.get("head") or {}
    if not str(head.get("ref") or "").startswith(BUILDER_PREFIX):
        return "it is not from a builder branch"
    if str((head.get("repo") or {}).get("full_name") or "").casefold() != full.casefold():
        return "it comes from a fork"
    if pr.get("state") != "open" or pr.get("draft"):
        return "it is not an open, ready pull request"
    step_n = named_step(plan, pr.get("body"))
    step = next((s for s in plan.get("steps", []) if s.get("n") == step_n), None)
    if step is None:
        return "it does not name the charter step it builds (Charter-Step: slug#n)"
    if plans.owner(step) != plans.THEA:
        return "the step it names is his, not the builder's"
    if pr.get("mergeable") is not True or pr.get("mergeable_state") != "clean":
        return f"GitHub does not call it cleanly mergeable ({pr.get('mergeable_state')})"
    rows = [f for f in files if isinstance(f, dict)]
    if not rows:
        return "its changed files could not be read"
    if len(rows) > MAX_FILES:
        return f"it changes {len(rows)} files, more than one review can hold"
    changed = sum(int(f.get("additions") or 0) + int(f.get("deletions") or 0) for f in rows)
    if changed > MAX_CHANGED_LINES:
        return f"it changes {changed} lines, more than one review can hold"
    for f in rows:
        for path in {str(f.get("filename") or ""), str(f.get("previous_filename") or "")} - {""}:
            try:
                if code_worker.protected_path(full, path):
                    return f"it touches a protected path ({path})"
            except code_worker.CodeWorkerError:
                return f"it names an unsafe path ({path})"
        if "patch" not in f:
            return f"{f.get('filename')} has no text diff to review"
    if len(diff_text(rows)) > code_worker.MAX_CONTEXT_CHARS:
        return "the diff is too large to review whole, and a truncated diff is not a reviewed one"
    runs = [c for c in checks if isinstance(c, dict)]
    if not runs:
        return "no checks ran on its head commit, and no CI is not a pass"
    for run in runs:
        if run.get("status") != "completed":
            return f"check '{run.get('name')}' is still running"
        if run.get("conclusion") not in GREEN:
            return f"check '{run.get('name')}' is {run.get('conclusion')}"
    return ""


def review(plan: dict, step_n: int, full: str, pr: dict, files: list[dict], *,
           think=None) -> dict:
    """An independent model's verdict on the diff, or a refusal to pretend."""
    model = reasoner.review_model(BUILDER_MODEL)
    if model == BUILDER_MODEL:
        return {"approved": False, "independent": False, "model": model, "findings": [],
                "summary": "no model other than the builder's is reachable, so there is "
                           "no independent review"}
    think = think or reasoner.subscription_json
    step = next((s for s in plan.get("steps", []) if s.get("n") == step_n), {})
    # The OBJECTIVE is composed from the charter, which is his and reviewed.
    # The pull request's own title and body are the builder's account of
    # itself: evidence, in the labelled field, never instruction.
    objective = (f"Review pull request #{pr.get('number')} in {full}. It should complete step "
                 f"{step_n} of the '{plan.get('title')}' charter: {step.get('text', '')}. "
                 f"The charter's goal: {plan.get('goal')}")[:code_worker.MAX_OBJECTIVE_CHARS]
    evidence = code_worker.sanitize_external(
        f"Pull request title: {pr.get('title')}\n\nPull request body:\n{pr.get('body') or ''}")
    verdict = think(code_worker.REVIEW_SYSTEM, objective,
                    context={"objective": objective, "proposed_diff": diff_text(files),
                             "untrusted_external_text": evidence},
                    model=model, validator=code_worker._review_validator,
                    max_context_bytes=code_worker.CONTEXT_BYTES)
    return {**verdict, "model": model, "independent": True}


# ---- the sweep ----------------------------------------------------------------

def _charters(fleet: dict, plan_rows: list[dict]):
    owner = str(fleet.get("owner") or "")
    for plan in plan_rows:
        if plan.get("state") != "open" or not plans.is_charter(plan):
            continue
        cfg = (fleet.get("repos") or {}).get(plan["project"].get("repo")) or {}
        name = str(cfg.get("github") or "")
        if owner and name:
            yield plan, f"{owner}/{name}"


def _consider(plan: dict, full: str, meta: dict, number: int, *, request, think,
              now: dt.datetime) -> dict:
    enc = _enc(full)
    pr = request("GET", f"/repos/{enc}/pulls/{int(number)}")
    pr = pr if isinstance(pr, dict) else {}
    files = request("GET", f"/repos/{enc}/pulls/{int(number)}/files?per_page=100")
    sha = str((pr.get("head") or {}).get("sha") or "")
    checks = (request("GET", f"/repos/{enc}/commits/{quote(sha, safe='')}/check-runs?per_page=100")
              if sha else {})
    runs = checks.get("check_runs") if isinstance(checks, dict) else None
    files = files if isinstance(files, list) else []
    out = {"repo": full, "pr": number, "sha": sha[:12]}
    why = refusal(plan, meta, pr, files, runs if isinstance(runs, list) else [])
    if why:
        return {**out, "status": "WAITING", "reason": why}

    step_n = named_step(plan, pr.get("body"))
    cache = REVIEWS_DIR / f"{_record_id(full, number, sha)}.json"
    verdict = None
    if cache.is_file():
        try:
            verdict = stateio.read_json(cache)
        except (OSError, ValueError):
            verdict = None
    if not isinstance(verdict, dict):
        policy.ensure_not_halted()
        verdict = review(plan, step_n, full, pr, files, think=think)
        verdict["reviewed_at"] = stateio.utcnow()
        stateio.write_json_atomic(cache, verdict)
        if not verdict.get("approved"):
            journal.append("decision", "code:merge",
                           f"review REFUSED {full}#{number}: {str(verdict.get('summary'))[:200]}",
                           actor=ACTOR)
    if not verdict.get("approved") or not verdict.get("independent"):
        return {**out, "status": "REVIEW_REJECTED", "reason": str(verdict.get("summary"))[:300]}

    # Last look before the one write that cannot be taken back quietly.
    policy.ensure_not_halted()
    if not ruling() or not code_trust.active():
        return {**out, "status": "OFF"}
    merged = request("PUT", f"/repos/{enc}/pulls/{int(number)}/merge", {
        "sha": sha, "merge_method": "squash",
        "commit_title": f"{str(pr.get('title') or '')[:200]} (#{number})",
    })
    if not isinstance(merged, dict) or merged.get("merged") is not True:
        return {**out, "status": "MERGE_FAILED",
                "reason": str((merged or {}).get("message") or "")[:200]}
    base = str((pr.get("base") or {}).get("ref") or "")
    stateio.write_json_atomic(MERGES_DIR / f"{_record_id(full, number)}.json", {
        "version": 1, "repo": full, "pr": number, "sha": sha, "base": base,
        "charter": plan["slug"], "step": step_n, "review_model": verdict.get("model"),
        "merged_at": _now(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    journal.append("action", "code:merge",
                   f"merged {full}#{number} into {base}: {plan['title']} step {step_n}, "
                   f"reviewed by {verdict.get('model')}", actor=ACTOR)
    return {**out, "status": "MERGED", "charter": plan["slug"], "step": step_n}


def sweep(*, request=gh.request, plan_rows: list[dict] | None = None,
          fleet: dict | None = None, think=None, now: dt.datetime | None = None) -> list[dict]:
    """Consider every open builder pull request on every low-risk charter."""
    policy.ensure_not_halted()
    if not ruling() or not code_trust.active():
        return []
    now = _now(now)
    fleet = fleet if fleet is not None else load_fleet()
    rows = plan_rows if plan_rows is not None else plans.all_plans()
    out: list[dict] = []
    for plan, full in _charters(fleet, rows):
        if full.split("/", 1)[1].casefold() in NEVER_MERGE or plan["project"].get("risk") != "low":
            continue  # not even read: there is nothing here for her to consider
        enc = _enc(full)
        base = str(plan["project"].get("base_branch") or "")
        try:
            meta = request("GET", f"/repos/{enc}")
            listed = request("GET", f"/repos/{enc}/pulls?state=open&base={quote(base, safe='')}"
                                    "&per_page=30")
        except Exception as exc:
            out.append({"repo": full, "status": "UNREADABLE", "reason": type(exc).__name__})
            continue
        for row in listed if isinstance(listed, list) else []:
            if not str(((row or {}).get("head") or {}).get("ref") or "").startswith(BUILDER_PREFIX):
                continue
            if _merges_since(now) >= MAX_MERGES_PER_DAY:
                out.append({"status": "THROTTLED", "max_per_day": MAX_MERGES_PER_DAY})
                return out
            policy.ensure_not_halted()
            try:
                out.append(_consider(plan, full, meta if isinstance(meta, dict) else {},
                                     int(row["number"]), request=request, think=think, now=now))
            except policy.Halted:
                raise
            except Exception as exc:
                out.append({"repo": full, "pr": row.get("number"), "status": "ERROR",
                            "reason": f"{type(exc).__name__}: {exc}"[:200]})
    return out


def open_builder_prs(*, request=gh.request, plan_rows: list[dict] | None = None,
                     fleet: dict | None = None) -> list[dict]:
    """Open the pull request for work the cloud builder pushed but did not open.

    A cloud session can always push its branch; whether it can open a pull
    request depends on the tools its environment has. Work that exists only
    as a branch is work nobody sees, so this opens it — for every charter,
    including the ones he merges himself, because a pull request is how he
    sees it too. One attempt per branch head: a branch GitHub refused is not
    asked again until it has new commits.
    """
    policy.ensure_not_halted()
    if not code_trust.active():
        return []
    fleet = fleet if fleet is not None else load_fleet()
    rows = plan_rows if plan_rows is not None else plans.all_plans()
    by_repo: dict[str, list[dict]] = {}
    for plan, full in _charters(fleet, rows):
        by_repo.setdefault(full, []).append(plan)
    out: list[dict] = []
    for full, charters in by_repo.items():
        enc = _enc(full)
        try:
            branches = request("GET", f"/repos/{enc}/branches?per_page=100")
            prs = request("GET", f"/repos/{enc}/pulls?state=all&per_page=100")
        except Exception:
            continue
        if not isinstance(branches, list) or not isinstance(prs, list):
            continue
        has_pr = {str(((p or {}).get("head") or {}).get("ref") or "") for p in prs}
        for branch in branches:
            name = str((branch or {}).get("name") or "")
            sha = str(((branch or {}).get("commit") or {}).get("sha") or "")
            found = BRANCH_STEP.match(name)
            if not found or name in has_pr:
                continue
            plan = next((p for p in charters if p["slug"] == found.group(1)), None)
            n = int(found.group(2))
            step = next((s for s in (plan or {}).get("steps", []) if s.get("n") == n), None)
            if plan is None or step is None:
                continue
            marker = OPENED_DIR / f"{_record_id(full, name)}.json"
            try:
                if marker.is_file() and stateio.read_json(marker).get("sha") == sha:
                    continue
            except (OSError, ValueError):
                pass
            policy.ensure_not_halted()
            base = str(plan["project"]["base_branch"])
            body = (f"Built by Thea's cloud builder for the **{plan['title']}** charter.\n\n"
                    f"Step {n}: {step['text']}\n\n"
                    f"Charter-Step: {plan['slug']}#{n}\n\n"
                    "Opened by Aletheia because the builder pushed the branch without a pull "
                    "request. "
                    + ("She may merge this herself once every check is green and a second "
                       "model has reviewed it." if plan["project"].get("risk") == "low"
                       and full.split("/", 1)[1].casefold() not in NEVER_MERGE
                       else "This project is one Caleb merges himself."))
            try:
                pr = request("POST", f"/repos/{enc}/pulls", {
                    "title": f"[Thea] {plan['title']}: step {n}, {step['text'][:80]}",
                    "head": name, "base": base, "body": body, "maintainer_can_modify": True})
                url = (pr or {}).get("html_url")
                outcome = {"repo": full, "branch": name, "status": "OPENED", "url": url}
                journal.append("action", "code:merge",
                               f"opened the pull request for builder branch {full}:{name} -> {base} ({url})",
                               actor=ACTOR)
            except Exception as exc:
                outcome = {"repo": full, "branch": name, "status": "ERROR",
                           "reason": f"{type(exc).__name__}: {exc}"[:200]}
            stateio.write_json_atomic(marker, {**outcome, "sha": sha, "at": stateio.utcnow()})
            out.append(outcome)
    return out


def main(argv: list[str] | None = None) -> int:
    from aletheia import browser_reasoner
    browser_reasoner.drop_lease()
    ap = argparse.ArgumentParser(description="Merge finished builder work on low-risk charters.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on", help="record his ruling, in his words, and enable merging")
    on.add_argument("--words", default=RULING_WORDS)
    sub.add_parser("off")
    sub.add_parser("status")
    sub.add_parser("sweep", help="consider open builder pull requests now")
    sub.add_parser("open", help="open pull requests for pushed builder branches now")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "on":
            print(json.dumps(enable(args.words, via="operator-local"), indent=2, ensure_ascii=False))
        elif args.cmd == "off":
            print("Merging is off." if disable(via="operator-local") else "It was already off.")
        elif args.cmd == "status":
            print(json.dumps(status(), indent=2, ensure_ascii=False))
        else:
            from aletheia import closed
            if closed.is_closed():
                print("Aletheia is closed — nothing merges. `python -m aletheia.closed open` to change that.")
                return 0
            result = sweep() if args.cmd == "sweep" else open_builder_prs()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except policy.Halted as exc:
        print(f"halted: {exc}")
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
