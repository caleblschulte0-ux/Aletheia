"""Bounded autonomous code worker that prepares reviewed pull requests only.

This module is deliberately not a general coding shell. It reads PUBLIC GitHub
repository text through the existing REST client, sends a small bounded context
to the subscription reasoner, validates full-file replacements, runs a separate
review pass, and only then creates a new `thea-auto/*` branch and pull request.
It never writes or merges a default branch.
"""
from __future__ import annotations

import base64
import difflib
import re
import secrets
from pathlib import PurePosixPath
from urllib.parse import quote

from aletheia import code_trust, gh, journal, reasoner, stateio

ACTOR = "aletheia-code-worker"
RUNS_DIR = stateio.private_dir("code-worker") / "runs"
MAX_MANIFEST = 160
MAX_CANDIDATES = 12
MAX_FILES = 4
MAX_FILE_BYTES = 14_000
MAX_CONTEXT_CHARS = 7_000
MAX_CHANGE_CHARS = 35_000
MAX_TOTAL_CHANGE_CHARS = 70_000
MAX_OBJECTIVE_CHARS = 4_000
TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".md", ".txt",
    ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".sql", ".sh", ".ps1",
}
PROTECTED_PREFIXES = (
    ".github/", ".git/", "exchange/", "state/", "memory/", "plans/",
    # config/ holds the REGISTRIES — fleet front-door grants and every
    # capability's approval_policy. CLAUDE.md: authority "widens only by a
    # reviewed registry edit — never a code path around the check", and an
    # autonomous worker proposing its own widening is exactly such a path.
    # (Found open in the 2026-09-01 catch-up review.)
    "config/",
    # agent instructions: skills/settings steer any session that reads them
    ".claude/",
)
PROTECTED_BASENAMES = {
    ".env", ".env.local", "credentials.json", "secrets.json", "id_rsa", "id_ed25519",
}
PROTECTED_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
ALETHEIA_PROTECTED = {
    "aletheia/policy.py", "aletheia/authority.py", "aletheia/work_session.py",
    "aletheia/work_trust.py", "aletheia/code_trust.py", "aletheia/secret_store.py",
    "aletheia/secret_browser.py", "aletheia/secret_trust.py", "aletheia/intercom.py",
    "aletheia/contracts.py", "aletheia/capabilities.py", "aletheia/gh.py",
    "aletheia/reasoner.py", "aletheia/browser_reasoner.py", "aletheia/code_worker.py",
    "aletheia/project_loop.py",
    # added 2026-09-01: authority surfaces that existed but were unlisted
    "aletheia/machine_binding.py",   # root of trust for every standing grant
    "aletheia/work_direct.py",       # the public bus's refusal list
    "aletheia/sealed_observe.py",    # crypto for private-data egress
    "aletheia/github_auth.py",       # the credentials this very loop uses
    "aletheia/standing.py",          # standing-authority reads
    "aletheia/proc.py",              # windowless-subprocess contract
    "aletheia/core.py",              # the always-on host of every gate
    "aletheia/supervisor.py",        # what relaunches it
    "aletheia/sync.py",              # what pulls code onto the PC
    "aletheia/project_autostart.py", # what starts the loop
    "aletheia/portfolio.py",         # what the loop is allowed to look at
    # the constitution and the playbook it serves: a worker must never
    # propose an edit to the rules it is judged by
    "claude.md", "docs/playbook.md", "docs/architecture.md", "readme.md",
}

PROPOSE_SYSTEM = """You are a code-edit proposal engine inside Aletheia.
Return exactly one JSON object: {"summary": string, "changes": [{"path": string,
"content": string, "why": string}], "confidence": number}. Only replace files
that are present in the supplied FILES object. Do not add/delete/rename files.
Make the smallest complete change that satisfies the objective. Preserve unrelated
behavior and existing public interfaces. Never add secrets, credentials, network
exfiltration, self-modifying code, or attempts to bypass tests/policy. If the
bounded files are insufficient, return an empty changes list and explain why.
"""

REVIEW_SYSTEM = """You are an independent code reviewer. Return exactly one JSON
object: {"approved": boolean, "summary": string, "findings": [string]}. Review
the proposed diff against the objective for correctness, regressions, unsafe
behavior, accidental scope expansion, secret handling, destructive behavior,
and testability. Approve only when the diff is safe and materially addresses the
objective. Do not rewrite code and do not claim tests ran.
"""


class CodeWorkerError(RuntimeError):
    pass


def _enc_repo(full: str) -> str:
    parts = str(full).split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise CodeWorkerError("repo_full_name must be owner/name")
    return "/".join(quote(p, safe="") for p in parts)


def _safe_path(path: str) -> str:
    """Normalize a repository path, or refuse it.

    Returns the NORMALIZED form, not the raw string. PurePosixPath quietly
    folds away a leading "./" and duplicate slashes, so a raw value could
    survive the traversal checks here and then fail to match a protected
    PREFIX downstream: "./config/fleet.json" does not start with "config/",
    but it addresses the same file. Caught by a protection test on
    2026-09-01 — the registries were reachable through that spelling.
    """
    value = str(path or "").replace("\\", "/").strip("/")
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or any(part in {"", "."} for part in p.parts):
        raise CodeWorkerError("unsafe repository path")
    normalized = str(p)
    if normalized in (".", "/") or normalized.startswith(("/", "../")):
        raise CodeWorkerError("unsafe repository path")
    return normalized


def protected_path(repo_full_name: str, path: str) -> bool:
    value = _safe_path(path)
    lower = value.casefold()
    base = PurePosixPath(lower).name
    if any(lower.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return True
    if base in PROTECTED_BASENAMES or lower.endswith(PROTECTED_SUFFIXES):
        return True
    if repo_full_name.casefold().endswith("/aletheia"):
        if lower in ALETHEIA_PROTECTED or lower.startswith("scripts/"):
            return True
    return False


def _is_text_candidate(repo_full_name: str, entry: dict) -> bool:
    if entry.get("type") != "blob":
        return False
    path = str(entry.get("path") or "")
    size = entry.get("size")
    if not isinstance(size, int) or size <= 0 or size > MAX_FILE_BYTES:
        return False
    try:
        if protected_path(repo_full_name, path):
            return False
    except CodeWorkerError:
        return False
    suffix = PurePosixPath(path.casefold()).suffix
    return suffix in TEXT_EXTENSIONS or PurePosixPath(path).name.casefold() in {"readme", "makefile"}


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9_]{3,}", str(text).casefold()) if len(x) < 40}


def _rank_paths(repo_full_name: str, tree: list[dict], objective: str) -> list[dict]:
    want = _tokens(objective)
    rows = []
    for entry in tree:
        if not isinstance(entry, dict) or not _is_text_candidate(repo_full_name, entry):
            continue
        path = str(entry["path"])
        low = path.casefold()
        score = sum(6 for token in want if token in low)
        score += 4 if low.startswith(("src/", "app/", "lib/", "tests/", "test/")) else 0
        score += 2 if PurePosixPath(low).name.startswith(("readme", "main", "index", "app")) else 0
        score -= low.count("/")
        rows.append((score, int(entry.get("size") or 0), path, entry))
    rows.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [row[3] for row in rows[:MAX_MANIFEST]]


def _decode_content(value: dict) -> str:
    if not isinstance(value, dict) or value.get("encoding") != "base64":
        raise CodeWorkerError("GitHub did not return base64 file content")
    try:
        raw = base64.b64decode(str(value.get("content") or ""), validate=False)
        return raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise CodeWorkerError("candidate file was not valid UTF-8 text") from None


def _proposal_validator(allowed: set[str]):
    def validate(value: dict) -> dict:
        if not isinstance(value, dict) or set(value) - {"summary", "changes", "confidence"}:
            raise ValueError("invalid code proposal fields")
        summary = value.get("summary")
        changes = value.get("changes")
        confidence = value.get("confidence", 0)
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 2_000:
            raise ValueError("proposal summary must be bounded text")
        if not isinstance(changes, list) or len(changes) > MAX_FILES:
            raise ValueError("proposal changes must be a bounded list")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ValueError("proposal confidence must be 0..1")
        total = 0
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"path", "content", "why"}:
                raise ValueError("each change needs path/content/why only")
            path = _safe_path(change["path"])
            if path not in allowed or path in seen:
                raise ValueError("proposal may only replace supplied files once")
            seen.add(path)
            content, why = change["content"], change["why"]
            if not isinstance(content, str) or len(content) > MAX_CHANGE_CHARS:
                raise ValueError("replacement content is not bounded text")
            if not isinstance(why, str) or not why.strip() or len(why) > 1_000:
                raise ValueError("change reason must be bounded text")
            total += len(content)
        if total > MAX_TOTAL_CHANGE_CHARS:
            raise ValueError("proposal replacement payload is too large")
        return value
    return validate


def _review_validator(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"approved", "summary", "findings"}:
        raise ValueError("invalid review fields")
    if type(value["approved"]) is not bool:
        raise ValueError("review approved must be boolean")
    if not isinstance(value["summary"], str) or not value["summary"].strip() or len(value["summary"]) > 2_000:
        raise ValueError("review summary must be bounded text")
    findings = value["findings"]
    if not isinstance(findings, list) or len(findings) > 12 or any(not isinstance(x, str) or len(x) > 1_000 for x in findings):
        raise ValueError("review findings must be bounded text list")
    return value


def _diff_text(originals: dict[str, str], changes: list[dict]) -> str:
    pieces = []
    for change in changes:
        path = change["path"]
        before = originals[path].splitlines(keepends=True)
        after = change["content"].splitlines(keepends=True)
        pieces.extend(difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}", n=3))
        if sum(len(p) for p in pieces) > MAX_CONTEXT_CHARS:
            break
    return "".join(pieces)[:MAX_CONTEXT_CHARS]


def _run_id(repo_full_name: str, task_id: str) -> str:
    raw = re.sub(r"[^a-z0-9-]+", "-", f"{repo_full_name}-{task_id}".casefold()).strip("-")
    return stateio.safe_id(raw[:150], name="code run id")


def _run_path(repo_full_name: str, task_id: str):
    return RUNS_DIR / f"{_run_id(repo_full_name, task_id)}.json"


def _load_run(repo_full_name: str, task_id: str) -> dict | None:
    path = _run_path(repo_full_name, task_id)
    if not path.is_file():
        return None
    try:
        value = stateio.read_json(path)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _save_run(repo_full_name: str, task_id: str, value: dict) -> None:
    stateio.write_json_atomic(_run_path(repo_full_name, task_id), value)


def _fetch_candidates(request, encoded: str, ref: str, ranked: list[dict]) -> dict[str, dict]:
    """Read candidate files at an EXACT ref.

    Callers pass the resolved base SHA, never a branch name. Reading by
    branch opened a race (found 2026-09-01): the base commit is resolved
    once, then each file is fetched in its own request. A push landing in
    between meant the model reviewed content from a newer tree than the
    commit was built on — and because the commit is built on the OLD
    base_tree, the PR would silently revert whatever had landed in the
    files it rewrote. Reading at the pinned sha makes proposal, review and
    commit describe one tree.
    """
    selected: dict[str, dict] = {}
    used = 0
    for entry in ranked[:MAX_CANDIDATES]:
        path = str(entry["path"])
        row = request("GET", f"/repos/{encoded}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}")
        text = _decode_content(row)
        cost = len(path) + len(text)
        if selected and used + cost > MAX_CONTEXT_CHARS:
            continue
        if not selected and cost > MAX_CONTEXT_CHARS:
            continue
        selected[path] = {"content": text, "sha": row.get("sha"), "mode": entry.get("mode") or "100644"}
        used += cost
        if len(selected) >= MAX_FILES:
            break
    return selected


def prepare_pr(repo_full_name: str, objective: str, *, task_id: str,
               request=gh.request) -> dict:
    """Prepare one independently reviewed PR. Never merge it."""
    objective = str(objective or "").strip()
    if not objective or len(objective) > MAX_OBJECTIVE_CHARS:
        raise ValueError(f"objective must be 1..{MAX_OBJECTIVE_CHARS} characters")
    task_id = stateio.safe_id(task_id, name="code task id")
    existing = _load_run(repo_full_name, task_id)
    if existing and existing.get("status") in {"PR_OPEN", "REVIEW_REJECTED"}:
        return existing
    if not gh.token():
        raise CodeWorkerError("GitHub write token is not configured locally (FLEET_TOKEN/GITHUB_TOKEN)")

    encoded = _enc_repo(repo_full_name)
    meta = request("GET", f"/repos/{encoded}")
    if not isinstance(meta, dict):
        raise CodeWorkerError("repository metadata was unavailable")
    private = bool(meta.get("private"))
    if private:
        raise code_trust.CodeTrustRequired("unattended model coding is disabled for private repositories")
    default = str(meta.get("default_branch") or "main")
    code_trust.claim(repo_full_name=repo_full_name, private=private, task_id=task_id)

    ref = request("GET", f"/repos/{encoded}/git/ref/heads/{quote(default, safe='')}")
    base_sha = (((ref or {}).get("object") or {}).get("sha"))
    if not isinstance(base_sha, str) or not base_sha:
        raise CodeWorkerError("default branch head was unavailable")
    commit = request("GET", f"/repos/{encoded}/git/commits/{quote(base_sha, safe='')}")
    base_tree = ((commit or {}).get("tree") or {}).get("sha")
    if not isinstance(base_tree, str) or not base_tree:
        raise CodeWorkerError("default branch tree was unavailable")
    tree = request("GET", f"/repos/{encoded}/git/trees/{quote(base_tree, safe='')}?recursive=1")
    if not isinstance(tree, dict) or tree.get("truncated") or not isinstance(tree.get("tree"), list):
        raise CodeWorkerError("repository tree was unavailable or too large for bounded autonomous work")

    ranked = _rank_paths(repo_full_name, tree["tree"], objective)
    selected = _fetch_candidates(request, encoded, base_sha, ranked)
    if not selected:
        raise CodeWorkerError("no safe bounded text files were available for this objective")
    originals = {path: row["content"] for path, row in selected.items()}
    context = {"objective": objective, "files": originals}
    proposal = reasoner.subscription_json(
        PROPOSE_SYSTEM, objective, context=context, model=reasoner.PLAN_MODEL,
        validator=_proposal_validator(set(selected)),
    )
    changes = [c for c in proposal["changes"] if c["content"] != originals[c["path"]]]
    if not changes:
        raise CodeWorkerError("reasoner found no safe bounded code change to make")
    for change in changes:
        if protected_path(repo_full_name, change["path"]):
            raise CodeWorkerError("proposal attempted a protected path")

    diff = _diff_text(originals, changes)
    if not diff.strip():
        raise CodeWorkerError("proposal produced no material diff")
    # The review is a SECOND OPINION only if it is a second judge. Using the
    # proposer's model means one systematic reasoning failure both writes and
    # approves the change (operator's challenge, 2026-09-01). Prefer a
    # different model; when only one is reachable, say so in the record and
    # in the PR body rather than calling it independent.
    review_model = reasoner.review_model(reasoner.PLAN_MODEL)
    review = reasoner.subscription_json(
        REVIEW_SYSTEM, objective,
        context={"objective": objective, "proposed_diff": diff, "proposal_summary": proposal["summary"]},
        model=review_model, validator=_review_validator,
    )
    review_independent = review_model != reasoner.PLAN_MODEL
    review["model"] = review_model
    review["independent"] = review_independent
    if not review["approved"]:
        result = {
            "version": 1, "status": "REVIEW_REJECTED", "repo": repo_full_name,
            "task_id": task_id, "base_sha": base_sha,
            "summary": proposal["summary"], "review": review,
            "updated_at": stateio.utcnow(),
        }
        _save_run(repo_full_name, task_id, result)
        return result

    blob_shas = {}
    for change in changes:
        blob = request("POST", f"/repos/{encoded}/git/blobs",
                       {"content": change["content"], "encoding": "utf-8"})
        sha = (blob or {}).get("sha")
        if not isinstance(sha, str) or not sha:
            raise CodeWorkerError("GitHub did not create replacement blob")
        blob_shas[change["path"]] = sha
    tree_rows = [
        {"path": path, "mode": str(selected[path].get("mode") or "100644"), "type": "blob", "sha": sha}
        for path, sha in blob_shas.items()
    ]
    new_tree = request("POST", f"/repos/{encoded}/git/trees", {"base_tree": base_tree, "tree": tree_rows})
    new_tree_sha = (new_tree or {}).get("sha")
    if not isinstance(new_tree_sha, str) or not new_tree_sha:
        raise CodeWorkerError("GitHub did not create proposed tree")
    message = f"[THEA-AUTO] {objective[:120]}"
    new_commit = request("POST", f"/repos/{encoded}/git/commits",
                         {"message": message, "tree": new_tree_sha, "parents": [base_sha]})
    commit_sha = (new_commit or {}).get("sha")
    if not isinstance(commit_sha, str) or not commit_sha:
        raise CodeWorkerError("GitHub did not create proposed commit")

    slug = re.sub(r"[^a-z0-9-]+", "-", task_id.casefold()).strip("-")[:45] or "task"
    branch = f"thea-auto/{slug}-{secrets.token_hex(3)}"
    request("POST", f"/repos/{encoded}/git/refs", {"ref": f"refs/heads/{branch}", "sha": commit_sha})
    # Name the review honestly. A same-model second pass is a lint, not a
    # second opinion, and a reviewer skimming this PR must be able to tell
    # which one they are looking at without reading the run record.
    review_label = (
        f"Review ({review_model}, independent of the {reasoner.PLAN_MODEL} proposal)"
        if review_independent else
        f"Review ({review_model} — SAME model that wrote the change; a "
        "consistency check, NOT an independent opinion)"
    )
    body = (
        "Automated Aletheia code-work PR.\n\n"
        f"Objective: {objective}\n\n"
        f"Proposal ({reasoner.PLAN_MODEL}): {proposal['summary']}\n\n"
        f"{review_label}: {review['summary']}\n\n"
        "Safety boundary: public-repo bounded replacements only; no workflow/governance/"
        "registry/secret paths; no default-branch write or merge. Files were read at the "
        "pinned base commit below, so this diff describes exactly the tree it was reviewed "
        "against. CI, if configured, remains authoritative — and a human merges.\n\n"
        f"Task: `{task_id}`\nBase: `{base_sha}`"
    )
    pr = request("POST", f"/repos/{encoded}/pulls", {
        "title": f"[THEA-AUTO] {objective[:90]}", "head": branch, "base": default,
        "body": body[:8_000], "maintainer_can_modify": True,
    })
    pr_url = (pr or {}).get("html_url")
    pr_number = (pr or {}).get("number")
    if not isinstance(pr_url, str) or not pr_url:
        raise CodeWorkerError("branch was created but GitHub did not create a pull request")
    result = {
        "version": 1, "status": "PR_OPEN", "repo": repo_full_name, "task_id": task_id,
        "objective": objective, "base_branch": default, "base_sha": base_sha,
        "branch": branch, "commit_sha": commit_sha, "pr_url": pr_url,
        "pr_number": pr_number, "files": [c["path"] for c in changes],
        "summary": proposal["summary"], "review": review, "updated_at": stateio.utcnow(),
    }
    _save_run(repo_full_name, task_id, result)
    journal.append(
        "action", f"code:{task_id}",
        f"prepared reviewed PR for {repo_full_name}: {pr_url}", actor=ACTOR,
    )
    return result


def all_runs() -> list[dict]:
    if not RUNS_DIR.is_dir():
        return []
    rows = []
    for path in sorted(RUNS_DIR.glob("*.json")):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def reconcile(repo_full_name: str, task_id: str, *, request=gh.request) -> dict | None:
    """Refresh one PR's external evidence. Never merges or closes anything."""
    run = _load_run(repo_full_name, task_id)
    if not run or not run.get("pr_number") or not run.get("commit_sha"):
        return run
    encoded = _enc_repo(repo_full_name)
    pr = request("GET", f"/repos/{encoded}/pulls/{int(run['pr_number'])}")
    if not isinstance(pr, dict):
        return run
    if pr.get("merged_at"):
        run["status"] = "MERGED"
        run["merged_at"] = pr.get("merged_at")
    elif pr.get("state") == "closed":
        run["status"] = "CLOSED"
    else:
        runs = request(
            "GET",
            f"/repos/{encoded}/actions/runs?head_sha={quote(str(run['commit_sha']), safe='')}&per_page=20",
        )
        rows = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
        rows = [r for r in rows if isinstance(r, dict) and r.get("head_sha") == run["commit_sha"]]
        if not rows:
            run["status"] = "PR_OPEN"
            run["ci"] = "NO_RUN_OBSERVED"
        elif any(str(r.get("status") or "") != "completed" for r in rows):
            run["status"] = "CI_RUNNING"
            run["ci"] = "RUNNING"
        elif any(str(r.get("conclusion") or "") not in {"success", "skipped", "neutral"} for r in rows):
            run["status"] = "CI_FAILED"
            run["ci"] = "FAILED"
        else:
            run["status"] = "CI_GREEN"
            run["ci"] = "GREEN"
    run["updated_at"] = stateio.utcnow()
    _save_run(repo_full_name, task_id, run)
    return run
