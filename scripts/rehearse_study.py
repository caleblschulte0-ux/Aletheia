"""Rehearse a whole study for real: real public reads, a real model, a scratch project, a fake clock.

    python scripts/rehearse_study.py --domain web                  # public pages vs a scratch site
    python scripts/rehearse_study.py --domain web --frontier-off   # the same, thought by her own model
    python scripts/rehearse_study.py --domain repos                # public repositories vs a scratch repo

What it proves (docs/CONTINUITY_BRIEF.md, addendum 2026-09-17): his sentence -> a lens
-> polite plain-HTTP reads of the comparables AND his project with provenance ->
measured differences and cited claims -> ranked hypotheses waiting on his decision ->
HIS yes (SIMULATED and labelled) -> the baseline read first -> a bounded change on a
thea-study branch in the scratch project -> a fake clock past the window (the change
not merged yet, so the window is extended honestly) -> HIS merge (SIMULATED, labelled)
-> the measurement and its caveats -> HIS keep (SIMULATED, labelled).

SAFETY: every store is a throwaway directory (private state, the repo-anchored stores
`talk --sandbox` redirects, the journal, the worktrees); ALETHEIA_REHEARSAL is set
before anything imports, so no pull request, post or email can happen; the subject is
a scratch git repository made here; nothing is pushed. Nothing in this script knows
what the comparables are beyond the addresses in the sentence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMULATED = "caleb-SIMULATED-in-rehearsal"

WEB_SITE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Quillnote</title></head>
<body>
<h1>Quillnote</h1>
<p>Quillnote is a note application. It stores notes in files on your computer and it can sync them with a folder
that you choose. It supports markdown formatting and it has a search function and tags.</p>
<h2>About</h2>
<p>The project was started in 2025 as a hobby. It is written in TypeScript and released under the MIT license.
Contributions are welcome on the issue tracker, where you can also report problems that you find.</p>
<h2>Download</h2>
<p>Builds for Windows, macOS and Linux are on the releases page: <a href="https://example.invalid/releases">releases</a>.</p>
</body></html>
"""

REPO_README = """# mdtidy

mdtidy tidies markdown files.

It fixes some formatting problems.
"""

REPO_CODE = '''"""mdtidy: trailing spaces and blank-line runs in markdown."""


def tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    out, blank = [], False
    for line in lines:
        if not line:
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(line)
    return "\\n".join(out).strip() + "\\n"
'''

REPO_TEST = '''import unittest

from mdtidy import tidy


class TidyCase(unittest.TestCase):
    def test_it_collapses_blank_runs(self):
        self.assertEqual(tidy("a  \\n\\n\\n\\nb"), "a\\n\\nb\\n")
'''

DOMAINS = {
    "web": {
        "project": "Quillnote",
        "files": {"index.html": WEB_SITE, "README.md": "# Quillnote site\n\nThe landing site.\n"},
        "words": ("These three open-source note apps convert far better than ours: https://joplinapp.org/ "
                  "https://standardnotes.com/ https://notesnook.com/ - study them deeply, figure out what they do "
                  "better, and improve my Quillnote site."),
    },
    "repos": {
        "project": "mdtidy",
        "files": {"README.md": REPO_README, "mdtidy.py": REPO_CODE, "tests/__init__.py": "",
                  "tests/test_tidy.py": REPO_TEST},
        "words": ("These markdown tools onboard people much better than mine: https://github.com/DavidAnson/markdownlint "
                  "https://github.com/igorshubovych/markdownlint-cli https://github.com/remarkjs/remark-lint - study "
                  "them and improve my mdtidy repository's onboarding."),
    },
}


def isolate(room: Path, *, frontier_off: bool, model: str) -> None:
    os.environ["ALETHEIA_PRIVATE_STATE"] = str(room / "private")
    os.environ["ALETHEIA_JOURNAL_PATH"] = str(room / "journal.jsonl")
    os.environ["ALETHEIA_WORKSPACE"] = str(room / "workspace")
    os.environ["ALETHEIA_MACHINE_KEY"] = str(room / "machine.key")
    os.environ["ALETHEIA_APPROVALS_DIR"] = str(room / "approvals")
    os.environ["ALETHEIA_REPAIR_WORKTREES"] = str(room / "worktrees")
    os.environ["ALETHEIA_REHEARSAL"] = "1"
    os.environ["ALETHEIA_STUDY_EXECUTION"] = "inline"
    os.environ["ALETHEIA_SEMANTIC_INDEX_OFF"] = "1"
    os.environ.setdefault("ALETHEIA_TZ", "America/Chicago")
    if frontier_off:
        os.environ["ALETHEIA_FRONTIER_OFF"] = "1"
        os.environ["ALETHEIA_LOCAL_AI_ENABLED"] = "1"
        os.environ["ALETHEIA_LOCAL_AI_FAST_MODEL"] = model
        os.environ["ALETHEIA_LOCAL_AI_DEEP_MODEL"] = model
    (room / "workspace").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Caleb (simulated)", "GIT_AUTHOR_EMAIL": "sim@localhost",
           "GIT_COMMITTER_NAME": "Caleb (simulated)", "GIT_COMMITTER_EMAIL": "sim@localhost"}
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    if done.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {done.stderr}")
    return done.stdout


def scratch(room: Path, files: dict[str, str], name: str) -> Path:
    project = room / name
    for rel, body in files.items():
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text(body, encoding="utf-8", newline="\n")
    git(project, "init", "-q", "-b", "main")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "the project as it is")
    return project


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domain", choices=sorted(DOMAINS), default="web")
    ap.add_argument("--frontier-off", action="store_true")
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)
    room = Path(tempfile.mkdtemp(prefix="rehearse-study-"))
    isolate(room, frontier_off=args.frontier_off, model=args.model)
    from aletheia import talk
    talk._redirect_repo_stores(room)
    from aletheia import (intercom, mission_studies, reasoning_gateway, studies as st, study_observe as so,
                          study_run as run, voice, waits, work_requirements as wr)
    assert intercom.rehearsing(), "rehearsal flag not set"
    domain = DOMAINS[args.domain]
    project = scratch(room, domain["files"], domain["project"].lower())
    log: dict = {"domain": args.domain, "frontier_off": reasoning_gateway.frontier_off(), "room": str(room),
                 "reasoning": wr.world("reasoning")["why"], "steps": [], "timings": {}}
    began = time.monotonic()

    def say(title, value=None):
        print(f"\n=== {title}")
        if value is not None:
            print(value if isinstance(value, str) else json.dumps(value, indent=1, ensure_ascii=False, default=str)[:6000])

    say("HIS SENTENCE (typed into the door as he would say it)", domain["words"])
    say("voice routes it to", voice._interpret(domain["words"]).get("command", {}).get("kind"))
    t0 = time.monotonic()
    door = run.start(domain["words"], via="operator-via-intercom", project=domain["project"], path=str(project), run=False)
    sid = door["study"]["id"]
    log["timings"]["door_s"] = round(time.monotonic() - t0, 2)
    say("SHE SAID", door["said"])

    for step in list(st.STEPS):
        t0 = time.monotonic()
        said = run.run_step(sid, step)
        record = st.load(sid)
        while record.get("blocked") and record["blocked"].get("step") == step:
            say(f"{step} blocked, retrying once", record["blocked"])
            st.update(sid, lambda r: r.update(blocked=None))
            said = run.run_step(sid, step)
            record = st.load(sid)
            if record.get("blocked"):
                break
        seconds = round(time.monotonic() - t0, 1)
        log["timings"][f"{step}_s"] = seconds
        log["steps"].append({"step": step, "said": said, "seconds": seconds})
        say(f"STEP {step} ({seconds}s)", record["history"][-1]["did"])

    record = st.load(sid)
    evidence = so.all_evidence(sid)
    log["lens"] = {"questions": record["questions"], "dimensions": record["lens"]["dimensions"],
                   "follow": record["lens"].get("follow"), "drafted_by": record["lens"]["drafted_by"]}
    say("LENS", log["lens"])
    log["evidence"] = [{"id": e["id"], "role": e["role"], "target": e["target"], "source": e["source"],
                        "method": e["method"], "status": e["status"], "fetched_at": e["fetched_at"],
                        "provenance": e["provenance"],
                        "metrics": {k: v for k, v in e["metrics"].items()
                                    if k in {"words", "first_screen_words", "early_actions", "headings", "images",
                                             "code_blocks", "list_items", "entries", "median_gap_days",
                                             "api.stars", "api.releases.entries_per_week", "numbers",
                                             "avg_sentence_words", "images_with_alt_ratio", "buttons", "links"}}}
                       for e in evidence]
    log["research"] = record["research"]
    say(f"EVIDENCE ({len(evidence)} observations, {record['research']['requests']} requests)", log["evidence"])
    comparison = record["comparison"]
    log["comparison"] = {"rows": [{"said": r["said"], "relative_gap": r["relative_gap"], "consistent": r["consistent"],
                                   "evidence": r["evidence"]} for r in comparison["rows"]],
                         "claims": comparison["claims"], "answers": comparison.get("answers"),
                         "guesses": comparison.get("guesses_list"), "dropped": comparison["dropped"],
                         "drafted_by": comparison["drafted_by"]}
    say("COMPARISON", log["comparison"])
    hyps = [h for h in record["hypotheses"] if h["state"] == st.PROPOSED]
    log["hypotheses"] = [{k: h.get(k) for k in ("key", "rank", "score", "title", "evidence", "observation", "change",
                                                "expected_effect", "metric", "baseline_method", "cost", "risk",
                                                "reversibility", "execution", "confidence", "notes", "drafted_by")}
                         for h in hyps]
    log["strategy_dropped"] = (record.get("strategy_runs") or [{}])[-1].get("dropped")
    say("HYPOTHESES (each waits on his decision)", log["hypotheses"])
    say("dropped by validation", log["strategy_dropped"])
    say("SHE SAYS when asked what should we change", st.spoken_status("", "change"))
    card = mission_studies.build(mission_studies.read({}), {})["missions"][0]
    log["card"] = {k: card[k] for k in ("status", "title", "next", "counts", "needs")}
    say("MISSION CARD", log["card"])
    if not hyps:
        log["timings"]["total_s"] = round(time.monotonic() - began, 1)
        _write(args, log)
        return 1

    chosen = next((h for h in hyps if h["execution"]["path"] in ("project_change", "experiment")), hyps[0])
    say("SIMULATED: Caleb accepts", f"{chosen['key']}: {chosen['title']}")
    st.decide(sid, chosen["key"], "accept", words="(simulated) yes, do that one", via=SIMULATED)
    t0 = time.monotonic()
    assert run.claim_execution(sid, chosen["key"], run._now())
    run.execute(sid, chosen["key"])
    log["timings"]["execute_s"] = round(time.monotonic() - t0, 1)
    h = st.hypothesis(st.load(sid), chosen["key"])
    log["execution"] = {"state": h["state"], "baseline": h.get("baseline"),
                        "result": {k: v for k, v in (h.get("execution_result") or {}).items() if k != "edits"},
                        "edits": (h.get("execution_result") or {}).get("edits"), "measure_at": h.get("measure_at")}
    say(f"EXECUTION ({log['timings']['execute_s']}s)", log["execution"])
    if h["state"] != st.MEASURING:
        log["timings"]["total_s"] = round(time.monotonic() - began, 1)
        _write(args, log)
        return 0

    at = waits.parse(h["measure_at"])
    say("FAKE CLOCK", f"advanced to {waits.stamp(at + dt.timedelta(hours=1))} (the window ends {h['measure_at']})")
    log["first_wake"] = waits.reconcile(at + dt.timedelta(hours=1))
    h = st.hypothesis(st.load(sid), chosen["key"])
    say("FIRST WAKE (the branch is not merged yet)", (h.get("measurements") or [{}])[-1])
    if h["state"] == st.MEASURING and h["execution_result"].get("branch"):
        say("SIMULATED: Caleb merges the branch", h["execution_result"]["branch"])
        git(project, "merge", "-q", "--no-ff", h["execution_result"]["branch"], "-m", "merge the study's change")
        later = waits.parse(h["measure_at"]) + dt.timedelta(hours=1)
        log["second_wake"] = waits.reconcile(later)
        h = st.hypothesis(st.load(sid), chosen["key"])
    log["measurement"] = h.get("measurement") or (h.get("measurements") or [{}])[-1]
    say("MEASUREMENT", log["measurement"])
    say("SHE SAYS when asked how's the study going", intercom.execute_command({"kind": "studies"}, {}, quote="how's the study going"))
    if h["state"] == st.VERDICT:
        suggestion = log["measurement"].get("suggestion") or "keep"
        say("SIMULATED: Caleb's verdict", suggestion)
        st.verdict(sid, chosen["key"], suggestion, words=f"(simulated) {suggestion} it", via=SIMULATED)
        record = st.load(sid)
        log["verdict"] = {"state": st.hypothesis(record, chosen["key"])["state"], "learned": record["learned"][-1]}
        say("LEARNED", log["verdict"])
    log["timings"]["total_s"] = round(time.monotonic() - began, 1)
    say("TIMINGS", log["timings"])
    _write(args, log)
    return 0


def _write(args, log) -> None:
    if args.json:
        Path(args.json).write_text(json.dumps(log, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
