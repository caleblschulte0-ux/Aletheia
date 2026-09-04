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

from aletheia.proc import run as proc_run
import sys
import urllib.error
from pathlib import Path

from aletheia import gh, stateio
from aletheia.fleet import REPO_ROOT, load_fleet

PULSE_DIR = REPO_ROOT / "state" / "pulse"


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GitHubSource:
    """Reads the fleet through the GitHub REST API."""

    def __init__(self, owner: str, token: str | None = None):
        self.owner = owner
        self.token = token or os.environ.get("FLEET_TOKEN") or os.environ.get("GITHUB_TOKEN")

    def _get(self, path: str) -> dict | list:
        return gh.request("GET", path, tok=self.token)

    def recent_commits(self, gh: str, branch: str, n: int = 5) -> list[dict]:
        commits = self._get(f"/repos/{self.owner}/{gh}/commits?sha={branch}&per_page={n}")
        return [
            {
                "sha": c["sha"][:12],
                "date": c["commit"]["committer"]["date"],
                "message": c["commit"]["message"].splitlines()[0][:120],
            }
            for c in commits
        ]

    def read_json(self, gh: str, path: str, branch: str):
        meta = self._get(f"/repos/{self.owner}/{gh}/contents/{path}?ref={branch}")
        if not isinstance(meta, dict) or meta.get("encoding") != "base64":
            raise ValueError(f"{path} is not a base64-encoded file")
        import base64
        return json.loads(base64.b64decode(meta["content"]).decode("utf-8"))

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

    def recent_commits(self, gh: str, branch: str, n: int = 5) -> list[dict]:
        out = proc_run(
            ["git", "log", f"-{n}", "--format=%H%x00%cI%x00%s"],
            cwd=self._dir(gh), capture_output=True, text=True, check=True,
        ).stdout.strip()
        commits = []
        for line in out.splitlines():
            sha, date, msg = line.split("\x00")
            commits.append({"sha": sha[:12], "date": date, "message": msg[:120]})
        return commits

    def read_json(self, gh: str, path: str, branch: str):
        return json.loads((self._dir(gh) / path).read_text(encoding="utf-8"))

    def workflow_run(self, gh: str, workflow: str) -> dict:
        return {"error": "unavailable offline"}

    def state_file(self, gh: str, path: str, branch: str) -> dict:
        p = self._dir(gh) / path
        if p.is_dir():
            return {"exists": True, "kind": "dir"}
        if not p.is_file():
            return {"exists": False}
        return {"exists": True, "bytes": p.stat().st_size}


def _dig(data, path: str):
    """Follow a dotted path into parsed JSON."""
    for part in path.split("."):
        data = data[part]
    return data


def private_vitals_path() -> Path:
    """Where the numbers that must not be committed actually live."""
    return stateio.private_dir("pulse") / "vitals.json"


def _vitals(repo: dict, source) -> tuple[list[dict], list[dict]]:
    """Evaluate the registry's declared vitals, split public from private.

    THE REPOSITORY IS PUBLIC AND HIS ACCOUNT BALANCE IS NOT. Ten daily
    briefs carried "realized P&L -$40.82 · win rate 14.3% · cash $2.50"
    under his name, dated, because a vital was a vital and the pulse is
    committed. A vital marked `private` in the registry is evaluated the
    same way and kept out of every committed file — the wall reads it
    from private state on his own machine, where it belongs.

    Which vitals are private is a REGISTRY decision. A collector that
    hardcodes "the trading repo is the sensitive one" is wrong the day he
    adds a second one.

    Each failure is recorded on the vital itself — a broken probe never
    takes the pulse down.
    """
    out, held = [], []
    gh, branch = repo["github"], repo["default_branch"]
    cache: dict[str, object] = {}
    for vital in repo.get("vitals", []):
        entry = {"label": vital["label"]}
        if "unit" in vital:
            entry["unit"] = vital["unit"]
        try:
            if vital["file"] not in cache:
                cache[vital["file"]] = source.read_json(gh, vital["file"], branch)
            node = cache[vital["file"]]
            if vital.get("path"):
                node = _dig(node, vital["path"])
            entry["value"] = len(node) if vital["probe"] == "count" else node
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        (held if vital.get("private") else out).append(entry)
    return out, held


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
    private: dict = {}
    for rid, repo in fleet["repos"].items():
        record: dict = {
            "github": repo["github"],
            "role": repo["role"],
            "status": repo["status"],
            "summary": repo["summary"],
        }
        gh, branch = repo["github"], repo["default_branch"]
        try:
            record["commits"] = source.recent_commits(gh, branch)
            record["commit"] = record["commits"][0] if record["commits"] else None
        except Exception as exc:  # a dead repo is a finding, not a crash
            record["error"] = f"{type(exc).__name__}: {exc}"
        if "error" not in record:
            record["vitals"], held = _vitals(repo, source)
            if held:
                # Named but never valued: the wall can honestly say "3
                # figures, on your screen only" instead of pretending the
                # repo has nothing to report.
                record["private_vitals"] = [v["label"] for v in held]
                private[rid] = held
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
    # The numbers go somewhere gitignored, on whichever machine collected
    # them. Best effort: a private store that cannot be written must never
    # stop the pulse, and the committed file is already safe either way.
    if private:
        try:
            path = private_vitals_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            stateio.write_json_atomic(
                path, {"generated_at": pulse["generated_at"], "repos": private})
        except Exception:
            pass
    return pulse


def private_vitals() -> dict:
    """The held-back numbers, for the wall on his own machine."""
    try:
        return stateio.read_json(private_vitals_path()).get("repos", {})
    except Exception:
        return {}


def write_local_block(block: dict, path=None) -> dict:
    """Merge the live "about her" block into latest.json, in place.

    Deliberately does NOT touch `generated_at`. That stamp belongs to the
    fleet data, which is collected in Actions on a six-hourly cron, and
    refreshing it here would make six-hour-old repository health render as
    current — §107 exactly. The local block carries its own timestamp and
    the wall shows both, because there really are two ages.
    """
    path = path or (PULSE_DIR / "latest.json")
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            raise ValueError("pulse is not an object")
    except (OSError, ValueError, json.JSONDecodeError):
        # No fleet pulse yet (a fresh clone, or Actions has never run). The
        # wall should still show her; it just has nothing to say about repos.
        current = {"generated_at": None, "repos": {}, "alerts": [],
                   "source": "local-only"}
    current["now"] = block
    PULSE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return current


def transitions(prev: dict | None, cur: dict) -> list[dict]:
    """Health changes since the previous pulse — what the sentinel acts on."""
    out = []
    prev_repos = (prev or {}).get("repos", {})
    for rid, r in cur["repos"].items():
        before = prev_repos.get(rid, {}).get("health")
        if before and before != r["health"]:
            out.append({"repo": rid, "github": r["github"], "from": before, "to": r["health"]})
    return out


def find_alerts(pulse: dict) -> list[dict]:
    """Active repos in trouble RIGHT NOW: red health or unreachable.
    Offline-mode 'unknown' (no error, just no telemetry) is not an alert."""
    out = []
    for rid, r in pulse["repos"].items():
        if r["status"] != "active":
            continue
        if r["health"] != "red" and not r.get("error"):
            continue
        alert = {"repo": rid, "github": r["github"], "health": r["health"]}
        if r.get("error"):
            alert["error"] = r["error"]
        failing = [
            n for n, w in (r.get("workflows") or {}).items()
            if w.get("status") == "completed" and w.get("conclusion") not in ("success", "skipped")
        ]
        missing = [p for p, f in (r.get("state_files") or {}).items() if f.get("exists") is False]
        if failing:
            alert["failing"] = failing
        if missing:
            alert["missing"] = missing
        out.append(alert)
    return out


def enrich(pulse: dict, prev: dict | None) -> dict:
    """Fold change-awareness and fleet intent into the pulse: transitions
    vs the previous pulse, current alerts, and open-plan summary. The wall
    and the brief read all of it from this one file."""
    from aletheia import plans as plans_mod
    pulse["transitions"] = transitions(prev, pulse)
    pulse["alerts"] = find_alerts(pulse)
    open_plans = [p for p in plans_mod.all_plans() if p["state"] == "open"]
    pulse["plans"] = {
        "open": len(open_plans),
        "items": [
            {"slug": p["slug"], "title": p["title"],
             "done": plans_mod.progress(p)[0], "total": plans_mod.progress(p)[1]}
            for p in open_plans
        ],
    }
    from aletheia import contracts, tasks as tasks_mod
    all_t = tasks_mod.all_tasks()
    live = [t for t in all_t if t["status"] not in contracts.TASK_TERMINAL]
    pulse["tasks"] = {
        "live": len(live),
        "by_status": {},
        "items": [
            {"id": t["id"], "status": t["status"], "description": t["description"],
             **({"worker": t["assigned_worker"]} if t.get("assigned_worker") else {})}
            for t in sorted(live, key=lambda t: (t.get("priority", 3), t["created_at"]))[:8]
        ],
    }
    for t in all_t:
        pulse["tasks"]["by_status"][t["status"]] = pulse["tasks"]["by_status"].get(t["status"], 0) + 1
    return pulse


HEALTH_MARK = {"green": "🟢", "red": "🔴", "unknown": "⚪", "dormant": "💤"}
# the wall's vocabulary — status is never color-alone anywhere Aletheia speaks
STATUS_WORDS = {"green": "OPERATIONAL", "red": "FAULT", "unknown": "NO TELEMETRY", "dormant": "DORMANT"}


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
        vitals = r.get("vitals", [])
        if vitals:
            lines.append("")
            parts = []
            for v in vitals:
                if "error" in v:
                    parts.append(f"{v['label']}: unreadable ({v['error']})")
                else:
                    unit = v.get("unit", "")
                    val = v["value"]
                    if unit == "usd" and isinstance(val, (int, float)):
                        parts.append(f"{v['label']}: ${val:,.2f}")
                    elif unit == "%":
                        parts.append(f"{v['label']}: {val}%")
                    else:
                        parts.append(f"{v['label']}: {val}")
            lines.append("Vitals — " + " · ".join(parts))
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
    out_dir = Path(args.out)
    prev = None
    prev_path = out_dir / "latest.json"
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = None
    enrich(pulse, prev)
    for t in pulse["transitions"]:
        from aletheia import journal
        kind = "alert" if t["to"] == "red" else ("recovery" if t["from"] == "red" else "event")
        journal.append(kind, f"repo:{t['repo']}", f"health {t['from']} -> {t['to']}")
    paths = write_pulse(pulse, out_dir)
    for rid, r in pulse["repos"].items():
        print(f"{HEALTH_MARK.get(r['health'], '?')} {rid}: {r['health']}"
              + (f" ({r['error']})" if r.get("error") else ""))
    print("wrote " + ", ".join(str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p) for p in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
