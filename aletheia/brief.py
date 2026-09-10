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

THE ONE THING (2026-09-10). He told us how his attention works: a project
gets a week or two of passion and then drifts. A digest of seven sections
is a thing a person like that closes unread. So the brief now LEADS with
exactly one thing that needs him — `pick_one_thing`, placed first in the
issue comment so it is the line his phone shows — and he answers it by
replying to the issue from wherever he is (`reply`, run by
brief-reply.yml): "yes", "done", "keep" or "drop". The same reply box takes
"new project: ...", "add ... to <project>" and "drop <project>". The comment
is posted by the Actions bot on purpose: GitHub does not notify a person
about comments made with his own token, which is the token the PC holds.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from aletheia import gh, journal
from aletheia.fleet import REPO_ROOT
from aletheia.pulse import BUILDER_PREFIX, PULSE_DIR, STATUS_WORDS

BRIEF_DIR = REPO_ROOT / "state" / "brief"
BRIEF_TITLE = "☀️ Fleet brief"
ONE_THING_FILE = "one_thing.json"
SNOOZE_FILE = "snoozes.json"
# "new project: ..." replied on the brief, waiting for the PC to draft it.
# The same path aletheia.charters reads through the contents API.
PROJECT_ASKS_FILE = "project_asks.json"
# A charter nobody — him or the builder — has moved in this long gets asked
# about. Long enough not to nag a project resting for a weekend; short
# enough to catch the drift he described before it becomes a month.
DRIFT_DAYS = 7
# "keep" buys this much quiet before the question comes back.
SNOOZE_DAYS = 7


def previous_pulse(pulse: dict, history_dir: Path | None = None) -> dict | None:
    """The most recent history pulse from BEFORE the current pulse's day.

    A pulse with no `generated_at` — which is what an unpulsed machine
    hands in — raised a bare KeyError, and "give me the brief" came back
    as "I couldn't: 'generated_at'".

    `history_dir` resolves at CALL time. As a default argument it was
    bound at import, so redirecting `pulse.PULSE_DIR` afterwards (a test,
    an audit sandbox) still read the real history.
    """
    history_dir = history_dir if history_dir is not None else PULSE_DIR / "history"
    stamp = str(pulse.get("generated_at") or "")
    if not stamp:
        return None
    today = stamp[:10].replace("-", "")
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


# ---- the one thing ----------------------------------------------------------

def _read_state(name: str) -> dict:
    try:
        value = json.loads((BRIEF_DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(name: str, value: dict) -> None:
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    (BRIEF_DIR / name).write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _stamp(now: dt.datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _quiet(item: dict) -> int:
    days = item.get("days_quiet")
    return days if isinstance(days, int) and not isinstance(days, bool) else -1


def _snoozed(snoozes: dict, slug: str, now: dt.datetime) -> bool:
    until = str((snoozes or {}).get(slug) or "")
    try:
        when = dt.datetime.fromisoformat(until.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when > now


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def _count(n: int, noun: str) -> str:
    if n == 0:
        return f"no {noun}s"
    return f"1 {noun}" if n == 1 else f"{n} {noun}s"


def _charters(pulse: dict) -> list[dict]:
    return [i for i in ((pulse.get("projects") or {}).get("items") or [])
            if isinstance(i, dict) and i.get("slug")]


def _drafts() -> list[dict]:
    """Charters drafted from something he asked for, waiting for his yes."""
    from aletheia import plans
    return sorted((p for p in plans.all_plans()
                   if plans.is_charter(p) and p.get("state") == "proposed"),
                  key=lambda p: (str(p.get("created") or ""), str(p.get("slug"))))


def _confirm_text(plan: dict) -> str:
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    hers = [s for s in steps if (s.get("owner") or "thea") == "thea"]
    yours = [s for s in steps if s.get("owner") == "caleb"]
    first = (hers or steps or [{"text": ""}])[0]["text"]
    merge = ("I'll merge its finished work myself once the tests pass and a second model has checked it."
             if (plan.get("project") or {}).get("risk") == "low" else "You merge its work.")
    return (f"New project drafted: {plan.get('title')}. {plan.get('goal')} "
            f"{_count(len(hers), 'step')} for me and {_count(len(yours), 'step')} for you, "
            f"starting with: {first}. {merge} Reply yes to start it, or no to drop it.")


def pick_one_thing(pulse: dict, snoozes: dict | None = None,
                   now: dt.datetime | None = None,
                   drafts: list[dict] | None = None) -> dict | None:
    """The ONE thing that needs him today, or None.

    Exactly one, in the order that unblocks the most:

    0. a project he asked for, drafted and waiting for his yes — nothing
       at all happens on it until he answers;
    1. a finished builder pull request only he may merge (a high-risk
       charter — the trader);
    2. his next step, on the charter that has sat quiet longest;
    3. a charter nobody has moved in DRIFT_DAYS: keep it or drop it.

    Low-risk pull requests are not on this list. She merges those herself
    (aletheia.project_merge) — that is what marking a charter low-risk means.
    """
    now = _now(now)
    for plan in drafts or []:
        if isinstance(plan, dict) and plan.get("slug"):
            return {"kind": "confirm", "slug": plan["slug"], "title": plan.get("title"),
                    "text": _confirm_text(plan)}
    items = _charters(pulse)
    waiting = []
    for item in items:
        if item.get("risk") != "high":
            continue
        for pr in item.get("open_prs") or []:
            if (isinstance(pr, dict) and not pr.get("draft")
                    and str(pr.get("head") or "").startswith(BUILDER_PREFIX)):
                waiting.append((str(pr.get("created_at") or ""), item, pr))
    if waiting:
        _, item, pr = min(waiting, key=lambda w: (w[0], w[1]["slug"]))
        return {"kind": "merge", "slug": item["slug"], "title": item["title"],
                "pr": pr.get("number"),
                "text": (f"{item['title']}: review and merge pull request #{pr.get('number')}, "
                         f"{pr.get('title')} ({pr.get('url')})")}
    yours = [i for i in items if isinstance(i.get("yours"), dict)]
    if yours:
        item = max(yours, key=lambda i: (_quiet(i), i["slug"]))
        step = item["yours"]
        return {"kind": "step", "slug": item["slug"], "title": item["title"],
                "n": step["n"], "step": step["text"],
                "text": f"{item['title']}: {step['text']}. Reply done when it is."}
    stalled = [i for i in items
               if _quiet(i) >= DRIFT_DAYS and not _snoozed(snoozes or {}, i["slug"], now)]
    if stalled:
        item = max(stalled, key=lambda i: (_quiet(i), i["slug"]))
        at_least = "at least " if item.get("quiet_at_least") else ""
        return {"kind": "drift", "slug": item["slug"], "title": item["title"],
                "text": (f"{item['title']} hasn't moved in {at_least}{_days(item['days_quiet'])}. "
                         "Reply keep or drop.")}
    return None


def _project_line(item: dict) -> str:
    head = f"**{item.get('title')}** — {item.get('done', 0)}/{item.get('total', 0)} steps"
    if item.get("error"):
        return f"{head} · couldn't read its branch ({item['error']})"
    quiet = _quiet(item)
    if item.get("not_started"):
        moved = "not started yet"
    elif item.get("quiet_at_least") and quiet >= 0:
        moved = f"no real work in at least {_days(quiet)} (only machine commits)"
    else:
        moved = ("no commits yet" if quiet < 0 else "moved today" if quiet == 0
                 else f"last moved {_days(quiet)} ago")
    parts = [head, moved]
    hers, yours = item.get("hers"), item.get("yours")
    if hers:
        parts.append(f"Thea next: {hers['text']}")
    if yours:
        parts.append(f"yours next: {yours['text']}")
    if not item.get("next"):
        parts.append("every step done")
    elif not hers and not yours:
        parts.append(f"waiting on: {item['next']['text']}")
    builder = [p for p in item.get("open_prs") or []
               if str((p or {}).get("head") or "").startswith(BUILDER_PREFIX)]
    if builder:
        parts.append(f"{len(builder)} open builder pull request"
                     + ("" if len(builder) == 1 else "s"))
    return " · ".join(parts)


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

    drafts = _drafts()
    thing = pick_one_thing(pulse, snoozes=_read_state(SNOOZE_FILE), drafts=drafts)
    if thing:
        lines.append("## 🧭 Your one thing today")
        lines.append(thing["text"])
        lines.append("")

    charters = _charters(pulse)
    if charters or drafts:
        lines.append("## Projects")
        for item in charters:
            lines.append("- " + _project_line(item))
        for plan in drafts:
            lines.append(f"- **{plan.get('title')}** — drafted, waiting for your yes")
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

    # THE BRIEF IS A COMMITTED FILE. `journal.since()` merges every writer,
    # including the private one, so a brief composed on his own machine
    # would quote his web tasks and applications straight into the
    # repository — which is exactly what it did: "webtask: AWAITING_YOU …
    # Fill in the job application on this page with my details" was in
    # `state/brief/latest.md`, published, while the journal it came from
    # had already been made private. Filtered HERE rather than trusting
    # the composer to be running somewhere the private file is absent.
    notable = [e for e in journal_entries
               if e["kind"] in ("decision", "action", "alert", "recovery")
               and journal.is_public_subject(e.get("subject", ""))]
    if notable:
        lines.append("## Last 24h in the journal")
        for e in notable[-12:]:
            lines.append(f"- `{e['ts'][11:16]}` [{e['kind']}] {e['subject']}: {e['text']}")
        lines.append("")

    lines.append("---")
    lines.append(f"pulse `{pulse['generated_at']}` · registry rev {pulse['fleet_revision']} · "
                 "composed by `aletheia.brief`")
    return "\n".join(lines)


def _project_command(body: str, now: dt.datetime) -> str | None:
    """"new project: ...", "add ... to <project>", "drop <project>" — or None.

    These are not answers to today's one thing, so they work whatever today's
    thing is. A step or a drop must name a charter that exists; "add some
    thoughts to the doc" names none and falls through to the answer logic,
    where it changes nothing.
    """
    from aletheia import charters, plans
    said = " ".join(str(body or "").split())
    m = re.fullmatch(r"new project\s*[:,\-]?\s*(.{3,}?)[.!]?", said, re.IGNORECASE)
    if m:
        charters.ask("new", text=m.group(1), via="operator-issue-comment",
                     path=BRIEF_DIR / PROJECT_ASKS_FILE, now=now)
        return (f"Got it. I'll draft {m.group(1)} and ask you here to say yes, usually within "
                "half an hour of the PC checking in.")
    m = re.fullmatch(r"add (?:a step )?(.+?) (?:to|for) (?:the |my )?(.+?)"
                     r"(?: project| charter)?[.!]?", said, re.IGNORECASE)
    if m:
        found, _why = plans.find_charter(m.group(2))
        if found is not None:
            owner = plans.infer_owner(m.group(1))
            plans.add_step(found["slug"], m.group(1), owner=owner)
            return (f"Added to {found['title']}: {m.group(1)} "
                    f"({'yours' if owner == plans.CALEB else 'mine'}).")
    m = re.fullmatch(r"(?:drop|shelve|abandon|stop working on) (?:the |my )?(.+?)"
                     r"(?: project| charter)?[.!]?", said, re.IGNORECASE)
    if m:
        found, _why = plans.find_charter(m.group(1))
        if found is not None:
            plans.set_plan(found["slug"], "dropped", because="he replied drop on the brief")
            return f"Dropped {found['title']}. The builder will leave it alone."
    return None


def reply(body: str, *, now: dt.datetime | None = None) -> str:
    """Apply his reply on the brief issue.

    Only the repository owner's comments reach here (brief-reply.yml checks
    the author). A project command works any day; otherwise only the FIRST
    WORD counts, as an answer to today's one thing. A word that answers
    nothing changes nothing and says so — a reply he meant as a note to
    himself is never read as an instruction.
    """
    now = _now(now)
    command = _project_command(body, now)
    if command is not None:
        return command
    words = str(body or "").strip().split()
    word = re.sub(r"[^a-z]", "", words[0].casefold()) if words else ""
    thing = _read_state(ONE_THING_FILE)
    kind, slug = thing.get("kind"), thing.get("slug")
    if not kind or not slug:
        return "There's no one thing on record today, so nothing changed."
    if thing.get("answered"):
        return f"Today's one thing was already answered ({thing['answered']}), so nothing changed."
    from aletheia import plans
    title = thing.get("title") or slug
    if kind == "confirm" and word in {"yes", "yep", "yeah", "sure", "start", "go"}:
        plans.confirm(slug, words=" ".join(words), via="operator-issue-comment")
        outcome = f"Started {title}. The builder takes its first step tonight."
    elif kind == "confirm" and word in {"no", "nope", "drop"}:
        plans.set_plan(slug, "dropped", because="he said no to the draft")
        outcome = f"Dropped the {title} draft. Nothing was started."
    elif kind == "step" and word in {"done", "did", "finished", "complete"}:
        plans.set_step(slug, int(thing["n"]), "done")
        journal.append("decision", f"plan:{slug}",
                       f"step {thing['n']} marked done by his reply on the brief",
                       actor="operator-issue-comment")
        nxt = plans.next_for(plans.load(slug), plans.CALEB)
        outcome = (f"Marked done: {thing.get('step')}."
                   + (f" Your next one on {title}: {nxt['text']}." if nxt
                      else f" Nothing else on {title} is yours right now."))
    elif kind == "drift" and word == "keep":
        snoozes = _read_state(SNOOZE_FILE)
        snoozes[slug] = _stamp(now + dt.timedelta(days=SNOOZE_DAYS))
        _write_state(SNOOZE_FILE, snoozes)
        journal.append("decision", f"plan:{slug}",
                       f"kept by his reply; drift check-in quiet for {SNOOZE_DAYS} days",
                       actor="operator-issue-comment")
        outcome = f"Keeping {title}. I won't ask about it again for {_days(SNOOZE_DAYS)}."
    elif kind == "drift" and word in {"drop", "kill"}:
        plans.set_plan(slug, "dropped", because="he replied drop to the drift check-in")
        outcome = f"Dropped {title}. The builder will leave it alone."
    else:
        takes = {"confirm": "yes or no", "step": "done", "drift": "keep or drop",
                 "merge": "a merge on GitHub, not a reply"}.get(kind, "a different answer")
        return f"That doesn't answer today's one thing (it takes {takes}), so nothing changed."
    _write_state(ONE_THING_FILE, {**thing, "answered": word, "answered_at": _stamp(now)})
    return outcome


def _count_new_suggestions() -> int:
    from aletheia.suggestions import SUGGESTIONS_DIR, load_verdicts
    verdicts = load_verdicts()
    n = 0
    for f in SUGGESTIONS_DIR.glob("*.json"):
        if f.stem not in verdicts:
            n += 1
    return n


def deliver_issue(text: str, day: str, repo_full: str, request=gh.request,
                  lead: str = "") -> str:
    issues = request("GET", f"/repos/{repo_full}/issues?state=open&per_page=100") or []
    existing = next((i for i in issues
                     if i.get("title", "").startswith(BRIEF_TITLE) and "pull_request" not in i), None)
    if existing is None:
        request("POST", f"/repos/{repo_full}/issues",
                {"title": BRIEF_TITLE, "body": text})
        return "opened"
    request("PATCH", f"/repos/{repo_full}/issues/{existing['number']}", {"body": text})
    # The notification shows the first line, so the one thing goes first.
    opener = f"**Your one thing today:** {lead}\n\n" if lead else ""
    request("POST", f"/repos/{repo_full}/issues/{existing['number']}/comments",
            {"body": f"{opener}Brief for **{day}**:\n\n{text}"})
    return "commented"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compose (and deliver) the morning fleet brief.")
    ap.add_argument("--repo", help="owner/name for issue delivery; omit to only write files")
    ap.add_argument("--pulse", default=str(PULSE_DIR / "latest.json"))
    ap.add_argument("--reply", metavar="BODY",
                    help="apply his reply to today's one thing and print the answer (brief-reply.yml)")
    args = ap.parse_args(argv)

    if args.reply is not None:
        print(reply(args.reply))
        return 0

    pulse = json.loads(Path(args.pulse).read_text(encoding="utf-8"))
    prev = previous_pulse(pulse)
    text = compose(pulse, prev, journal.since(24), _count_new_suggestions())
    day = pulse["generated_at"][:10]
    thing = pick_one_thing(pulse, snoozes=_read_state(SNOOZE_FILE), drafts=_drafts())
    # What "yes" or "done" in a reply will refer to. A day with nothing on it
    # is recorded too, so yesterday's thing cannot be answered by today's reply.
    _write_state(ONE_THING_FILE, {**(thing or {}), "day": day})

    (BRIEF_DIR / "history").mkdir(parents=True, exist_ok=True)
    (BRIEF_DIR / "latest.md").write_text(text + "\n", encoding="utf-8")
    (BRIEF_DIR / "history" / f"{day.replace('-', '')}.md").write_text(text + "\n", encoding="utf-8")
    journal.append("brief", "fleet", f"morning brief composed for {day}")
    print(f"brief written for {day}")

    if args.repo:
        if not gh.token():
            print("no token — brief written to state/ but not delivered as an issue", file=sys.stderr)
            return 0
        outcome = deliver_issue(text, day, args.repo, lead=(thing or {}).get("text", ""))
        print(f"brief issue: {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
