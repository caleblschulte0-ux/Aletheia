"""The pulse — one honest snapshot of the whole fleet.

Walks every repo in `config/fleet.json` and records what is actually true
right now: last commit, watched workflow outcomes, watched state files.
Writes `state/pulse/latest.json` (machine truth, read by the interface),
`state/pulse/briefing.md` (human/ChatGPT truth), and a small dated copy in
`state/pulse/history/`.

Two sources:
  - GitHubSource — the real one, used by `pulse.yml` in Actions. Needs a
    token that can READ every fleet repo (`FLEET_TOKEN` secret; the default
    `GITHUB_TOKEN` sees only Aletheia itself).
  - LocalSource — reads sibling clones on disk. No network, no workflow
    runs (recorded as unavailable, never guessed).

A repo the source cannot reach is a FINDING in the pulse, never an
exception and never a silent omission: the pulse always names every repo
in the registry and says what it could not see.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from aletheia.fleet import REPO_ROOT, load_fleet

PULSE_DIR = REPO_ROOT / "state" / "pulse"
API = "https://api.github.com"


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GitHubSource:
    """Reads the fleet through the GitHub REST API."""

    def __init__(self, owner: str, token: str | None = None):
        self.owner = owner
        self.token = token or os.environ.get("FLEET_TOKEN") or os.environ.get("GITHUB_TOKEN")

    def _get(self, path: str) -> dict | list:
        req = urllib.request.Request(f"{API}{path}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def latest_commit(self, gh: str, branch: str) -> dict:
        c = self._get(f"/repos/{self.owner}/{gh}/commits/{branch}")
        return {
            "sha": c["sha"][:12],
            "date": c["commit"]["committer"]["date"],
            "message": c["commit"]["message"].splitlines()[0][:120],
        }

    def workflow_run(self, gh: str, workflow: str) -> dict:
        try:
            runs = self._get(
                f"/repos/{self.owner}/{gh}/actions/workflows/{workflow}/runs?per_page=1"
            )["workflow_runs"]
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"error": "workflow not found"}
            raise
        if not runs:
            return {"error": "never run"}
        r = runs[0]
        return {
            "status": r["status"],
            "conclusion": r["conclusion"],
            "updated_at": r["updated_at"],
            "url": r["html_url"],
        }

    def state_file(self, gh: str, path: str, branch: str) -> dict:
        try:
            meta = self._get(
                f"/repos/{self.owner}/{gh}/contents/{path}?ref={branch}"
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"exists": False}
            raise
        if isinstance(meta, list):
            return {"exists": True, "kind": "dir"}
        return {"exists": True, "bytes": meta.get("size", 0)}


class LocalSource:
    """Reads sibling clones on disk. Workflow runs are honestly unavailable."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _dir(self, gh: str) -> Path:
        d = self.root / gh
        if not d.is_dir():
            raise FileNotFoundError(f"no clone at {d}")
        return d

    def latest_commit(self, gh: str, branch: str) -> dict:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%H%x00%cI%x00%s"],
            cwd=self._dir(gh), capture_output=True, text=True, check=True,
        ).stdout.strip()
        sha, date, msg = out.split("\x00")
        return {"sha": sha[:12], "date": date, "message": msg[:120]}

    def workflow_run(self, gh: str, workflow: str) -> dict:
        return {"error": "unavailable offline"}

    def state_file(self, gh: str, path: str, branch: str) -> dict:
        p = self._dir(gh) / path
        if p.is_dir():
            return {"exists": True, "kind": "dir"}
        if not p.is_file():
            return {"exists": False}
        return {"exists": True, "bytes": p.stat().st_size}


def _health(record: dict, status: str) -> str:
    """green / red / unknown / dormant — derived, never asserted."""
    if status == "stub":
        return "dormant"
    if record.get("error"):
        return "unknown"
    concluded = [
        w.get("conclusion")
        for w in record.get("workflows", {}).values()
        if "error" not in w and w.get("status") == "completed"
    ]
    missing_files = [
        p for p, f in record.get("state_files", {}).items() if not f.get("exists")
    ]
    if any(c not in ("success", "skipped") for c in concluded) or missing_files:
        return "red"
    if not concluded and record.get("workflows"):
        return "unknown"
    return "green"


def collect(fleet: dict, source) -> dict:
    pulse: dict = {
        "generated_at": _utcnow(),
        "fleet_revision": fleet["revision"],
        "owner": fleet["owner"],
        "source": type(source).__name__,
        "repos": {},
    }
    for rid, repo in fleet["repos"].items():
        record: dict = {
            "github": repo["github"],
            "role": repo["role"],
            "status": repo["status"],
            "summary": repo["summary"],
        }
        gh, branch = repo["github"], repo["default_branch"]
        try:
            record["commit"] = source.latest_commit(gh, branch)
        except Exception as exc:  # a dead repo is a finding, not a crash
            record["error"] = f"{type(exc).__name__}: {exc}"
        if "error" not in record:
            record["workflows"] = {}
            for wf in repo["watch"]["workflows"]:
                try:
                    record["workflows"][wf] = source.workflow_run(gh, wf)
                except Exception as exc:
                    record["workflows"][wf] = {"error": f"{type(exc).__name__}: {exc}"}
            record["state_files"] = {}
            for sf in repo["watch"]["state_files"]:
                try:
                    record["state_files"][sf] = source.state_file(gh, sf, branch)
                except Exception as exc:
                    record["state_files"][sf] = {"error": f"{type(exc).__name__}: {exc}"}
        record["health"] = _health(record, repo["status"])
        pulse["repos"][rid] = record
    return pulse


HEALTH_MARK = {"green": "🟢", "red": "🔴", "unknown": "⚪", "dormant": "💤"}


def briefing(pulse: dict) -> str:
    lines = [
        "# Fleet briefing",
        "",
        f"Generated {pulse['generated_at']} from fleet registry rev "
        f"{pulse['fleet_revision']} via {pulse['source']}.",
        "",
    ]
    for rid, r in pulse["repos"].items():
        mark = HEALTH_MARK.get(r["health"], "⚪")
        lines.append(f"## {mark} `{r['github']}` — {r['role']} ({r['status']})")
        lines.append("")
        lines.append(r["summary"])
        if r.get("error"):
            lines.append("")
            lines.append(f"**Unreachable:** {r['error']}")
            lines.append("")
            continue
        c = r.get("commit")
        if c:
            lines.append("")
            lines.append(f"Last commit `{c['sha']}` at {c['date']}: {c['message']}")
        wf_lines = []
        for name, w in r.get("workflows", {}).items():
            if "error" in w:
                wf_lines.append(f"- `{name}`: {w['error']}")
            else:
                wf_lines.append(
                    f"- `{name}`: {w['conclusion'] or w['status']} at {w['updated_at']}"
                )
        if wf_lines:
            lines.append("")
            lines.append("Watched workflows:")
            lines.extend(wf_lines)
        missing = [p for p, f in r.get("state_files", {}).items() if not f.get("exists")]
        if missing:
            lines.append("")
            lines.append("**Missing watched state files:** " + ", ".join(f"`{p}`" for p in missing))
        lines.append("")
    return "\n".join(lines)


def write_pulse(pulse: dict, out_dir: Path = PULSE_DIR) -> list[Path]:
    out_dir = Path(out_dir)
    (out_dir / "history").mkdir(parents=True, exist_ok=True)
    latest = out_dir / "latest.json"
    latest.write_text(json.dumps(pulse, indent=2) + "\n", encoding="utf-8")
    brief = out_dir / "briefing.md"
    brief.write_text(briefing(pulse) + "\n", encoding="utf-8")
    day = pulse["generated_at"][:10].replace("-", "")
    hist = out_dir / "history" / f"{day}.json"
    hist.write_text(json.dumps(pulse, indent=2) + "\n", encoding="utf-8")
    return [latest, brief, hist]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect the fleet pulse.")
    ap.add_argument("--local", metavar="ROOT", help="read sibling clones under ROOT instead of the GitHub API")
    ap.add_argument("--out", metavar="DIR", default=str(PULSE_DIR), help="output directory")
    args = ap.parse_args(argv)

    fleet = load_fleet()
    if args.local:
        source = LocalSource(Path(args.local))
    else:
        source = GitHubSource(fleet["owner"])
        if not source.token:
            print(
                "no FLEET_TOKEN or GITHUB_TOKEN in the environment — the API "
                "source cannot read private fleet repos without one",
                file=sys.stderr,
            )
            return 1
    pulse = collect(fleet, source)
    paths = write_pulse(pulse, Path(args.out))
    for rid, r in pulse["repos"].items():
        print(f"{HEALTH_MARK.get(r['health'], '?')} {rid}: {r['health']}"
              + (f" ({r['error']})" if r.get("error") else ""))
    print("wrote " + ", ".join(str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p) for p in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
