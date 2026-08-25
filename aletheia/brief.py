"""The morning brief — "here is your empire this morning" (ROADMAP A5).

Composes a daily digest from what Aletheia already knows — the current
pulse, day-over-day vital deltas from pulse history, health transitions,
open plans, the ChatGPT inbox, and the journal's last 24 hours — and
delivers it two ways:

  - committed truth: `state/brief/latest.md` (+ dated copy in history/)
  - a rolling "☀️ Fleet brief" issue on this repo, body refreshed and a
    comment added per brief (the comment is the phone notification)

Run daily by `brief.yml`. Composition is pure (`compose`), so the digest
is testable without a network; delivery degrades honestly without a token.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from aletheia import gh, journal
from aletheia.fleet import REPO_ROOT
from aletheia.pulse import PULSE_DIR, STATUS_WORDS

BRIEF_DIR = REPO_ROOT / "state" / "brief"
BRIEF_TITLE = "☀️ Fleet brief"


def previous_pulse(pulse: dict, history_dir: Path = PULSE_DIR / "history") -> dict | None:
    """The most recent history pulse from BEFORE the current pulse's day."""
    today = pulse["generated_at"][:10].replace("-", "")
    if not history_dir.is_dir():
        return None
    for f in sorted(history_dir.glob("*.json"), reverse=True):
        if f.stem < today:
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return None


def vital_deltas(prev: dict | None, cur: dict) -> dict[str, dict[str, float]]:
    """{repo_id: {label: cur - prev}} for vitals numeric on both sides."""
    out: dict[str, dict[str, float]] = {}
    prev_repos = (prev or {}).get("repos", {})
    for rid, r in cur["repos"].items():
        before = {v["label"]: v.get("value") for v in prev_repos.get(rid, {}).get("vitals", [])}
        for v in r.get("vitals", []):
            a, b = before.get(v["label"]), v.get("value")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                out.setdefault(rid, {})[v["label"]] = round(b - a, 2)
    return out


def _fmt(value, unit: str | None, signed: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return str(value)
    sign = "+" if signed and value > 0 else ""
    if unit == "usd":
        return f"{'-' if value < 0 else sign}${abs(value):,.2f}"
    if unit == "%":
        return f"{sign}{value}%"
    return f"{sign}{value:,g}"


def compose(pulse: dict, prev: dict | None, journal_entries: list[dict],
            new_suggestions: int) -> str:
    day = pulse["generated_at"][:10]
    alerts = pulse.get("alerts") or []
    deltas = vital_deltas(prev, pulse)
    lines = [f"# ☀️ Fleet brief — {day}", ""]

    if alerts:
        lines.append(f"**{len(alerts)} fault(s) need eyes:** "
                     + ", ".join(f"`{a['github']}`" for a in alerts))
    else:
        lines.append("**All quiet.** No faults anywhere in the fleet.")
    lines.append("")

    for rid, r in pulse["repos"].items():
        if r["status"] != "active":
            continue
        word = STATUS_WORDS.get(r["health"], r["health"])
        lines.append(f"## {r['github']} — {word}")
        parts = []
        for v in r.get("vitals", []):
            if "error" in v:
                continue
            d = deltas.get(rid, {}).get(v["label"])
            delta_txt = f" ({_fmt(d, v.get('unit'), signed=True)})" if d else ""
            parts.append(f"{v['label']} {_fmt(v.get('value'), v.get('unit'))}{delta_txt}")
        if parts:
            lines.append("- " + " · ".join(parts))
        c = r.get("commit")
        if c:
            lines.append(f"- last commit `{c['sha']}`: {c['message']}")
        lines.append("")

    trans = pulse.get("transitions") or []
    if trans:
        lines.append("## Changes since the last pulse")
        for t in trans:
            lines.append(f"- `{t['github']}` went {t['from']} → **{t['to']}**")
        lines.append("")

    plans = (pulse.get("plans") or {}).get("items", [])
    if plans:
        lines.append("## Plans in motion")
        for p in plans:
            lines.append(f"- **{p['title']}** — {p['done']}/{p['total']} steps done (`{p['slug']}`)")
        lines.append("")

    live_tasks = (pulse.get("tasks") or {}).get("items", [])
    if live_tasks:
        lines.append("## Tasks in flight")
        for t in live_tasks:
            worker = f" → {t['worker']}" if t.get("worker") else ""
            lines.append(f"- [{t['status']}] {t['description']} (`{t['id']}`){worker}")
        lines.append("")

    if new_suggestions:
        lines.append(f"## Inbox: {new_suggestions} ChatGPT suggestion(s) awaiting a ruling")
        lines.append("Rule with `python -m aletheia.suggestions list --state new`.")
        lines.append("")

    notable = [e for e in journal_entries
               if e["kind"] in ("decision", "action", "alert", "recovery")]
    if notable:
        lines.append("## Last 24h in the journal")
        for e in notable[-12:]:
            lines.append(f"- `{e['ts'][11:16]}` [{e['kind']}] {e['subject']}: {e['text']}")
        lines.append("")

    lines.append("---")
    lines.append(f"pulse `{pulse['generated_at']}` · registry rev {pulse['fleet_revision']} · "
                 "composed by `aletheia.brief`")
    return "\n".join(lines)


def _count_new_suggestions() -> int:
    from aletheia.suggestions import SUGGESTIONS_DIR, load_verdicts
    verdicts = load_verdicts()
    n = 0
    for f in SUGGESTIONS_DIR.glob("*.json"):
        if f.stem not in verdicts:
            n += 1
    return n


def deliver_issue(text: str, day: str, repo_full: str, request=gh.request) -> str:
    issues = request("GET", f"/repos/{repo_full}/issues?state=open&per_page=100") or []
    existing = next((i for i in issues
                     if i.get("title", "").startswith(BRIEF_TITLE) and "pull_request" not in i), None)
    if existing is None:
        request("POST", f"/repos/{repo_full}/issues",
                {"title": BRIEF_TITLE, "body": text})
        return "opened"
    request("PATCH", f"/repos/{repo_full}/issues/{existing['number']}", {"body": text})
    request("POST", f"/repos/{repo_full}/issues/{existing['number']}/comments",
            {"body": f"Brief for **{day}**:\n\n{text}"})
    return "commented"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compose (and deliver) the morning fleet brief.")
    ap.add_argument("--repo", help="owner/name for issue delivery; omit to only write files")
    ap.add_argument("--pulse", default=str(PULSE_DIR / "latest.json"))
    args = ap.parse_args(argv)

    pulse = json.loads(Path(args.pulse).read_text(encoding="utf-8"))
    prev = previous_pulse(pulse)
    text = compose(pulse, prev, journal.since(24), _count_new_suggestions())
    day = pulse["generated_at"][:10]

    (BRIEF_DIR / "history").mkdir(parents=True, exist_ok=True)
    (BRIEF_DIR / "latest.md").write_text(text + "\n", encoding="utf-8")
    (BRIEF_DIR / "history" / f"{day.replace('-', '')}.md").write_text(text + "\n", encoding="utf-8")
    journal.append("brief", "fleet", f"morning brief composed for {day}")
    print(f"brief written for {day}")

    if args.repo:
        if not gh.token():
            print("no token — brief written to state/ but not delivered as an issue", file=sys.stderr)
            return 0
        outcome = deliver_issue(text, day, args.repo)
        print(f"brief issue: {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
