"""Shorts-pipeline's three mailboxes, answered from his PC.

Shorts-pipeline files three kinds of question it cannot answer in its own
run, and since 2026-09-30 it accepts Aletheia's answers to all three
(`"by": "aletheia:<route>"`, its `docs/REVIEW_MAILBOX.md`):

    exchange/reviews/   a held render's frames + the SHOWRUNNER's grading
                        prompt; the answer is the judge's GRADES, never a
                        ship/block - Shorts' own code decides
    exchange/rewrites/  a held story's words, its data and the gate's rules;
                        the answer is new words its own validator re-checks
    exchange/asks/      a text question no backend of its own could answer

Shorts said the worker was NOT BUILT because its write grant awaited his
direct approval. He gave it, in his Claude project thread, 2026-10-07T01:22Z:

    "Alethea may write files into a shorts review, rewrite, and ask mailbox.
    ... That's certified by me. Every 30 minutes is unnecessary. We only
    post in the morning, so maybe it needs to run two, three times in the
    morning, and that's it"

So, and nothing wider:

- THE GRANT is `config/fleet.json` `repos.shorts_pipeline.front_door.answers`
  (with his words beside it), checked by `aletheia.act.check_answer_path`
  BEFORE any network call. Only answer files may be written: a path under a
  granted prefix ending in .verdict.json, .answer.json or .answers.json.
  A request, an index, a .done.json, code - all refused with no call made.
- THE SCHEDULE is his: up to three rounds a morning, at SLOTS (his clock,
  `aletheia.localtime`). The Core's beat only LAUNCHES a round (`kick`), as
  a detached `python -m aletheia.shorts_mailbox once`; the model calls run
  in that process, never inside the beat. A durable receipt per slot per
  date means a restarted Core does not run a slot twice.
- EACH ROUND IS BOUNDED: MAX_REVIEWS, MAX_REWRITES, MAX_ASKS (newest batch
  only, and only with time left), inside RUN_BUDGET_S, one round at a time.
- NOTHING MALFORMED LEAVES. A grade that fails the showrunner's own schema
  becomes a HOLD that burns the request on Shorts' side, so grades are
  validated here first (`validate_grades`, the same rules as Shorts'
  `validate_judge_response`) and anything that fails is not written. A
  rewrite is pre-checked against the request's own rules
  (`prevalidate_rewrite`); when unsure, it is skipped.
- A rewrite whose story still has an open REVIEW is skipped: new words
  applied first would upload the old video under a new title.
- Never the ChatGPT browser: the lease is dropped first thing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from aletheia import act, browser_reasoner, closed, journal, policy, proc, stateio

FLEET_KEY = "shorts_pipeline"
ACTOR = "aletheia-shorts-mailbox"
MODULE = "aletheia.shorts_mailbox"
OFF_ENV = "ALETHEIA_SHORTS_MAILBOX_OFF"

#: His mornings, on his clock: "two, three times in the morning, and that's
#: it". A slot opens at its time and stays open SLOT_WINDOW_MIN, so a PC
#: that wakes at 06:50 still runs the 06:30 round.
SLOTS = ("06:30", "08:00", "09:30")
SLOT_WINDOW_MIN = 60
MAX_RUNS_PER_MORNING = 3

MAX_REVIEWS = 4
MAX_REWRITES = 6
MAX_ASKS = 10
RUN_BUDGET_S = 75 * 60
#: Asks are the lowest priority: only begun with at least this much left.
ASKS_NEED_S = 10 * 60
STALE_LOCK_S = 3 * 3600

VISION_MODEL = "opus"
VISION_TIMEOUT_S = 600.0
TEXT_TIMEOUT_S = 240.0
MAX_IMAGES = 32
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 400_000

#: Frames and sheets live on Shorts' preview branch, and nowhere else is
#: fetched: the request is data written by a CI run, not a list of URLs to
#: trust.
MEDIA_PREFIX = "https://raw.githubusercontent.com/{full}/preview-renders/"

REVIEW_INDEX = "exchange/reviews/OPEN.json"
REWRITE_INDEX = "exchange/rewrites/OPEN.json"
ASK_INDEX = "exchange/asks/OPEN.json"


# ----------------------------------------------------------------- state

def state_dir() -> Path:
    return stateio.private_dir("shorts-mailbox")


def _receipts_dir() -> Path:
    return state_dir() / "receipts"


def _lock_path() -> Path:
    return state_dir() / "run.json"


def _latest_path() -> Path:
    return state_dir() / "latest.json"


def _utc(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(dt.timezone.utc)


def _stamp(now: dt.datetime | None = None) -> str:
    return _utc(now).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zone(tz=None):
    if tz is not None:
        return tz
    from aletheia import localtime
    return localtime.operator_tz()


# ----------------------------------------------------------------- slots

def slot_for(now: dt.datetime | None = None, tz=None) -> tuple[str, str] | None:
    """(local date YYYY-MM-DD, slot HHMM) when `now` is inside a morning slot
    on his clock, else None."""
    local = _utc(now).astimezone(_zone(tz))
    for slot in SLOTS:
        hour, minute = (int(x) for x in slot.split(":"))
        start = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= local < start + dt.timedelta(minutes=SLOT_WINDOW_MIN):
            return local.date().isoformat(), slot.replace(":", "")
    return None


def receipts_for(date: str) -> list[Path]:
    d = _receipts_dir()
    if not d.is_dir():
        return []
    return sorted(d.glob(f"{date}-*.json"))


def _receipt_path(date: str, slot: str) -> Path:
    return _receipts_dir() / f"{date}-{slot}.json"


def claim_slot(now: dt.datetime | None = None, tz=None) -> dict | None:
    """Claim this morning slot's one run, durably, or None.

    None outside a slot, when this slot already ran, and when the morning
    already had MAX_RUNS_PER_MORNING - whatever the receipts' slot names."""
    where = slot_for(now, tz)
    if where is None:
        return None
    date, slot = where
    if len(receipts_for(date)) >= MAX_RUNS_PER_MORNING:
        return None
    record = {"date": date, "slot": slot, "claimed_at": _stamp(now)}
    try:
        stateio.create_json_exclusive(_receipt_path(date, slot), record)
    except FileExistsError:
        return None
    return record


# ----------------------------------------------------------------- one at a time

def running(now: float | None = None) -> dict | None:
    """The round under way, if one is - decided by its process, not the clock
    alone (aletheia.campaign.running learned that the hard way)."""
    try:
        value = json.loads(_lock_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    now = time.time() if now is None else now
    pid = value.get("pid")
    alive = proc.pid_alive(pid, needle=MODULE) if pid else None
    if alive is False:
        return None
    try:
        age = now - float(value.get("started_epoch") or 0)
    except (TypeError, ValueError):
        age = STALE_LOCK_S
    if age < STALE_LOCK_S:
        return value
    if alive is True:
        proc.kill_tree(pid)
        journal.append("alert", "repo:shorts_pipeline",
                       "a Shorts mailbox round ran far past its time limit, so it was stopped",
                       actor=ACTOR)
    return None


def _take_lock() -> bool:
    record = {"pid": os.getpid(), "started_epoch": time.time(), "started_at": _stamp()}
    for _ in range(2):
        try:
            stateio.create_json_exclusive(_lock_path(), record)
            return True
        except FileExistsError:
            if running() is not None:
                return False
            try:
                _lock_path().unlink()
            except OSError:
                return False
    return False


def _release_lock() -> None:
    try:
        holder = json.loads(_lock_path().read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        holder = None
    if holder in (None, os.getpid()):
        try:
            _lock_path().unlink()
        except OSError:
            pass


# ----------------------------------------------------------------- the beat's half

def _granted(fleet: dict) -> bool:
    try:
        return bool(act.answer_prefixes(fleet, FLEET_KEY))
    except KeyError:
        return False


def _spawn(args: list[str]) -> int:
    from aletheia.fleet import REPO_ROOT
    state_dir().mkdir(parents=True, exist_ok=True)
    return proc.spawn_detached(args, cwd=str(REPO_ROOT), log_path=state_dir() / "run.log")


def kick(fleet: dict | None = None, *, now: dt.datetime | None = None, tz=None,
         spawner=None) -> dict:
    """The Core's beat: in a morning slot that has not run, LAUNCH a round in
    its own process and come straight back. Never runs the work inline.

    Cheap: a few stat calls, a JSON read, at most one process start."""
    if os.environ.get(OFF_ENV) or os.environ.get("ALETHEIA_REHEARSAL"):
        return {"started": False, "why": "off in this process"}
    if closed.is_closed():
        return {"started": False, "why": "closed"}
    if policy.halted() is not None:
        return {"started": False, "why": "halted"}
    if fleet is None:
        from aletheia.fleet import load_fleet
        fleet = load_fleet()
    if not _granted(fleet):
        return {"started": False, "why": "no answers grant in config/fleet.json"}
    if slot_for(now, tz) is None:
        return {"started": False, "why": "not a morning slot"}
    if running() is not None:
        return {"started": False, "why": "a round is already running"}
    record = claim_slot(now, tz)
    if record is None:
        return {"started": False, "why": "this morning's slot already ran"}
    args = [sys.executable, "-m", MODULE, "once", "--slot", f"{record['date']}-{record['slot']}"]
    path = _receipt_path(record["date"], record["slot"])
    try:
        pid = (spawner or _spawn)(args)
    except Exception:
        # Not run, so not spent: the next beat inside the window tries again.
        try:
            path.unlink()
        except OSError:
            pass
        raise
    stateio.write_json_atomic(path, {**record, "pid": pid, "launched_at": _stamp()})
    return {"started": True, "pid": pid, **record}


# ----------------------------------------------------------------- reading

def _read_json(read, path: str) -> dict | None:
    raw = read(path)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _default_reader(full: str, branch: str):
    from aletheia import project_checkout

    def read(path: str) -> str | None:
        return project_checkout.raw_file(full, branch, path, limit=MAX_REQUEST_BYTES)
    return read


def _default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "aletheia-shorts-mailbox"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image larger than the mailbox reads")
    return data


def _media_ok(url: str, full: str) -> bool:
    prefix = MEDIA_PREFIX.format(full=full)
    if not isinstance(url, str) or not url.startswith(prefix):
        return False
    rest = urllib.parse.urlsplit(url)
    return (not rest.query and not rest.fragment and ".." not in rest.path.split("/")
            and rest.path.lower().endswith((".jpg", ".jpeg", ".png")))


def fetch_images(req: dict, folder: Path, full: str, fetch=None) -> list[dict]:
    """The contact sheet and every labelled frame, saved into `folder`.
    [{"file", "label", "t"}], sheet first. Anything not on Shorts' preview
    branch is skipped, never fetched."""
    fetch = fetch or _default_fetch
    out: list[dict] = []
    sheet = req.get("sheet_url")
    if _media_ok(sheet, full):
        try:
            (folder / "sheet.jpg").write_bytes(fetch(sheet))
            out.append({"file": "sheet.jpg", "label": "contact sheet of every frame", "t": None})
        except Exception:                                            # noqa: BLE001
            pass
    for i, frame in enumerate((req.get("frames") or [])[:MAX_IMAGES]):
        if not isinstance(frame, dict) or not _media_ok(frame.get("url"), full):
            continue
        name = f"f{i:02d}.jpg"
        try:
            (folder / name).write_bytes(fetch(frame["url"]))
        except Exception:                                            # noqa: BLE001
            continue
        out.append({"file": name, "label": str(frame.get("label") or "")[:40],
                    "t": frame.get("t")})
    return out


# ----------------------------------------------------------------- grades

DIMENSIONS = {"hook": 4, "data_demo": 5, "mascot": 4, "craft": 3, "pace": 2, "payoff": 2}
CHECKS = ("junk_imagery", "decorative_mascot", "bare_number_card", "dead_air",
          "empty_void", "unreadable")
DEPICTION_KINDS = ("bespoke", "machine", "chart")
WEAKEST_TEXT = ("failure_class", "visible_evidence", "root_cause", "repair_goal")
#: A judge grades; code decides. A reply carrying a decision answered a
#: different question than the one it was asked.
FORBIDDEN = {"ship", "block", "score", "verdict", "decision"}


def _int_in(value, top: int) -> bool:
    return type(value) is int and 0 <= value <= top


def validate_grades(grades: dict) -> dict:
    """The grades, cleaned to exactly what Shorts reads, or ValueError.

    The same rules as Shorts' `showrunner_review.validate_judge_response`
    (integers, not bools or floats, in each dimension's range; all six checks
    with a boolean and non-empty evidence), plus a structured weakest scene.
    `temporal_craft` is graded by Shorts' code from measured cadence, so it is
    dropped rather than sent."""
    if not isinstance(grades, dict):
        raise ValueError("grades are not an object")
    decided = sorted(FORBIDDEN & set(grades))
    if decided:
        raise ValueError(f"grades must not decide: {decided}")
    dims = grades.get("dimensions")
    if not isinstance(dims, dict):
        raise ValueError("dimensions missing")
    clean_dims = {}
    for key, top in DIMENSIONS.items():
        if not _int_in(dims.get(key), top):
            raise ValueError(f"dimensions.{key} must be an integer 0-{top}")
        clean_dims[key] = dims[key]
    checks = grades.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("checks missing")
    clean_checks = {}
    for key in CHECKS:
        c = checks.get(key)
        if not isinstance(c, dict) or not isinstance(c.get("present"), bool):
            raise ValueError(f"checks.{key}.present must be true or false")
        evidence = c.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"checks.{key}.evidence must say what was seen")
        clean_checks[key] = {"present": c["present"], "evidence": evidence.strip()[:600]}
    ws = grades.get("weakest_scene")
    if not isinstance(ws, dict) or not isinstance(ws.get("id"), str) or not ws["id"].strip() \
            or type(ws.get("index")) is not int:
        raise ValueError("weakest_scene needs an id and an integer index")
    clean_ws = {"id": ws["id"].strip()[:40], "index": ws["index"]}
    for key in WEAKEST_TEXT:
        if not isinstance(ws.get(key), str):
            raise ValueError(f"weakest_scene.{key} must be text")
        clean_ws[key] = ws[key].strip()[:600]
    out = {"dimensions": clean_dims, "checks": clean_checks, "weakest_scene": clean_ws}
    depictions = []
    for d in grades.get("depictions") or []:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"].strip():
            continue
        if d.get("kind") not in DEPICTION_KINDS:
            continue
        if not (_int_in(d.get("bespoke"), 3) and _int_in(d.get("proves_claim"), 3)):
            continue
        depictions.append({"id": d["id"].strip()[:40], "kind": d["kind"],
                           "bespoke": d["bespoke"], "proves_claim": d["proves_claim"],
                           "note": str(d.get("note") or "")[:240]})
    if depictions:
        out["depictions"] = depictions
    out["one_line"] = str(grades.get("one_line") or "")[:400]
    for key in ("problems", "fixes"):
        rows = grades.get(key) or []
        out[key] = [str(x)[:400] for x in rows if isinstance(x, (str, int, float))][:12] \
            if isinstance(rows, list) else []
    return out


VISION_SYSTEM = (
    "You are the SHOWRUNNER's judge for a YouTube Shorts pipeline. You look at the "
    "frames you are given and grade them on the rubric in the message, exactly as it "
    "says. You grade the anchors and the hard checks only: you NEVER output ship, "
    "block, a verdict or a score - code decides those. Reply with ONLY the JSON "
    "object the message asks for: no prose, no code fence.")


def _frame_lines(images: list[dict]) -> str:
    lines = []
    for img in images:
        t = img.get("t")
        when = f" (t={float(t):.1f}s)" if isinstance(t, (int, float)) and not isinstance(t, bool) else ""
        lines.append(f"  {img['file']} - {img['label']}{when}")
    return "\n".join(lines)


def _claude_look(req: dict, folder: Path, images: list[dict]) -> dict:
    """One grade through the Claude CLI, Read tool only, in a folder holding
    nothing but these frames (the eyes.py pattern)."""
    from aletheia import reasoner
    until = reasoner.resting_until()
    if until is not None:
        raise reasoner.ClaudeResting(until)
    path = reasoner.cli_path()
    if not path:
        raise reasoner.ReasonerUnavailable("the Claude app isn't available on this PC")
    argv = [path, "-p", "--system-prompt", VISION_SYSTEM, "--tools", "Read",
            "--model", VISION_MODEL, "--output-format", "text",
            "--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config"]
    prompt = ("You are grading one rendered YouTube Short from its frames. They are image "
              "files in your working directory; Read every one of them before you grade:\n"
              f"{_frame_lines(images)}\n\nThen grade it exactly as the instructions below say."
              f"\n\n{req['prompt']}")
    try:
        done = proc.run_tree(argv, VISION_TIMEOUT_S, input=prompt, cwd=str(folder),
                             env={**os.environ, "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"},
                             creationflags=reasoner.hidden_flags())
    except Exception as exc:                                         # noqa: BLE001
        raise reasoner.ReasonerUnavailable(f"Claude could not look ({type(exc).__name__})") from None
    if done.returncode != 0:
        reasoner._raise_if_limited(f"{done.stdout or ''}\n{done.stderr or ''}")
        raise reasoner.ReasonerUnavailable(f"Claude exited {done.returncode}")
    return validate_grades(reasoner._first_json_object(done.stdout or ""))


def _codex_look(req: dict, folder: Path, images: list[dict]) -> dict:
    """One grade through Codex on his ChatGPT subscription, the frames
    attached as images in a read-only sandbox."""
    from aletheia import reasoner
    order = "\n".join(f"  {n}. {line.strip()}" for n, line in
                      enumerate(_frame_lines(images).splitlines(), 1))
    text = (f"The frames of one rendered YouTube Short are attached as images, in this "
            f"order:\n{order}\n\nGrade it exactly as the instructions below say.\n\n"
            f"{req['prompt']}")
    return reasoner.codex_json(VISION_SYSTEM, text, validator=validate_grades,
                               timeout_s=VISION_TIMEOUT_S,
                               images=[str(folder / img["file"]) for img in images])


#: Who can look, in order. There is no local vision model: if neither
#: answers, the request is left for the next round.
VISION_ROUTES = (("claude", _claude_look), ("codex", _codex_look))


def grade(req: dict, folder: Path, images: list[dict], routes=None) -> tuple[dict, str]:
    """(validated grades, route) or ReasonerUnavailable naming why nobody could."""
    from aletheia import reasoner
    why: list[str] = []
    for name, look in routes or VISION_ROUTES:
        try:
            return look(req, folder, images), name
        except reasoner.ReasonerUnavailable as exc:
            why.append(f"{name}: {exc}")
        except ValueError as exc:
            why.append(f"{name}: no usable grades ({str(exc)[:120]})")
    raise reasoner.ReasonerUnavailable("nobody could grade it: " + "; ".join(why))


# ----------------------------------------------------------------- rewrites

_NUM = re.compile(r"\d[\d,]*\.?\d*")
_MULT = (("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3))
_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
_GLUED = re.compile(r"[-‐-―]?[A-Za-z]")
_GROUPED = re.compile(r"\d,\d")
_TOL = 0.03
_SPELLED = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundred|dozen)\b", re.I)
_SENTENCES = re.compile(r"[.!?]+[\"')\]]*\s+\S")
_CAP = re.compile(r"^([A-Z][a-z][A-Za-z'\-]*)")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]+")
_STOP = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "were", "its",
         "into", "than", "then", "your", "you", "our", "has", "have", "how", "why", "what",
         "who", "when", "where", "now", "not", "but", "all", "out", "just"}


def spoken_quantities(text: str) -> list[float]:
    """The quantities a listener hears - a port of Shorts' own
    `beat_match.spoken_quantities` (years skipped, magnitude words applied,
    a digit glued to a word is part of the word)."""
    text = text or ""
    out = []
    for m in _NUM.finditer(text):
        try:
            v = float(m.group(0).replace(",", "").rstrip("."))
        except ValueError:
            continue
        if 1900 <= v <= 2100 and float(v).is_integer() and not _GROUPED.search(m.group(0)):
            continue
        before = text[:m.start()]
        if before[-1:] in "-‐‑‒–—" and before[-2:-1].isalnum():
            continue
        rest = text[m.end():]
        head = rest[:1].lower()
        if head in _SUFFIX and not rest[1:2].isalpha():
            out.append(v * _SUFFIX[head])
            continue
        if _GLUED.match(rest):
            continue
        tail = rest[:14].lstrip().lower()
        for word, mul in _MULT:
            if tail.startswith(word):
                v *= mul
                break
        out.append(v)
    return out


def _near(a: float, b: float) -> bool:
    if a == 0 or b == 0:
        return abs(a - b) < 0.05
    return abs(a - b) / max(abs(a), abs(b)) <= _TOL


def sayable(seg: dict) -> set[float]:
    """Every quantity this beat's data can show (Shorts' `beat_match.sayable`):
    a value, the value in its unit, a difference, a share, a ratio, a change."""
    data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
    unit = str(data.get("unit") or "").lower()
    scale = next((mul for word, mul in _MULT if word in unit), 1.0)
    vals = []
    for p in data.get("points") or []:
        if isinstance(p, dict) and isinstance(p.get("value"), (int, float)) \
                and not isinstance(p.get("value"), bool):
            vals.append(float(p["value"]))
    out: set[float] = set()
    total = sum(vals) or 1.0
    for a in vals:
        out.update({a, a * scale, round(a / total * 100, 1)})
        for b in vals:
            out.update({abs(a - b), abs(a - b) * scale})
            if b:
                out.update({round(a / b * 100, 1), round((a - b) / b * 100, 1)})
    return {abs(x) for x in out}


def _unexplained(text: str, allowed: set[float], original: str) -> list[float]:
    prior = [abs(q) for q in spoken_quantities(original)]
    bad = []
    for q in spoken_quantities(text):
        q = abs(q)
        if any(_near(q, p) for p in prior) or any(_near(q, a) for a in allowed):
            continue
        bad.append(q)
    return bad


def _caps(rules: list) -> dict:
    """The word caps from the request's own PACE rule (Shorts' registry is the
    source); the 2026-10-05 values when a rule does not say."""
    caps = {"say": 16, "hook": 14, "closing": 10, "question": 8, "topic": 4}
    text = " ".join(str(r) for r in rules or [])
    for key, pattern in (("say", r"SAY is ONE spoken sentence of at most (\d+)"),
                         ("hook", r"HOOK at most (\d+)"), ("closing", r"CLOSING at most (\d+)"),
                         ("question", r"QUESTION at most (\d+)"),
                         ("topic", r"at most (\d+) words, no clause")):
        m = re.search(pattern, text, re.I)
        if m:
            caps[key] = int(m.group(1))
    return caps


def _words(text: str) -> int:
    return len(str(text or "").split())


def _bridge_words(text: str) -> set[str]:
    return {w.lower().rstrip("s") for w in _WORD.findall(text or "")
            if len(w) >= 3 and w.lower() not in _STOP}


def _new_entities(text: str, pool: set[str]) -> list[str]:
    out = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        for token in sentence.split()[1:]:
            m = _CAP.match(token)
            if m and m.group(1).lower() not in pool:
                out.add(m.group(1))
    return sorted(out)


def prevalidate_rewrite(req: dict, answer: dict) -> dict:
    """The rewrite's words, cleaned, or ValueError. Shorts re-validates with
    its own gate; this keeps a rewrite it would refuse from ever leaving.
    When unsure, refuse."""
    if not isinstance(answer, dict):
        raise ValueError("the rewrite is not an object")
    segs = req.get("segments") or []
    current = req.get("current") if isinstance(req.get("current"), dict) else {}
    new = answer.get("segments")
    if not isinstance(new, list) or not segs or len(new) != len(segs):
        raise ValueError(f"{len(new) if isinstance(new, list) else 0} segments for {len(segs)}")
    caps = _caps(req.get("rules"))
    clean = {}
    for key in ("title", "hook", "closing"):
        value = " ".join(str(answer.get(key) or "").split())
        if not value:
            raise ValueError(f"missing {key}")
        clean[key] = value
    clean["question"] = " ".join(str(answer.get("question") or "").split())
    for key in ("hook", "closing", "question"):
        if _words(clean[key]) > caps[key]:
            raise ValueError(f"{key} is {_words(clean[key])} words (max {caps[key]})")
    if not re.search(r"\d", clean["title"] + clean["hook"]):
        raise ValueError("neither the title nor the hook carries a number")

    original_all = " ".join([str(current.get(k) or "") for k in ("title", "hook", "closing", "question")]
                            + [f"{s.get('say') or ''} {s.get('topic') or ''}" for s in segs
                               if isinstance(s, dict)])
    pool = {w.lower() for w in _WORD.findall(original_all)}
    for s in segs:
        data = s.get("data") if isinstance(s, dict) and isinstance(s.get("data"), dict) else {}
        pool |= {w.lower() for w in _WORD.findall(str(data.get("title") or ""))}
        for p in data.get("points") or []:
            if isinstance(p, dict):
                pool |= {w.lower() for w in _WORD.findall(str(p.get("label") or ""))}
    spelled_before = {w.lower() for w in _SPELLED.findall(original_all)}
    title_words = _bridge_words(clean["title"])

    allowed_all: set[float] = set()
    out_segs = []
    for i, (seg, line) in enumerate(zip(segs, new)):
        if not isinstance(seg, dict) or not isinstance(line, dict):
            raise ValueError(f"segment {i} is not an object")
        say = " ".join(str(line.get("say") or "").split())
        topic = " ".join(str(line.get("topic") or seg.get("topic") or "").split())
        if not say or not topic:
            raise ValueError(f"segment {i} needs a topic and a say")
        if _words(say) > caps["say"]:
            raise ValueError(f"segment {i}: say is {_words(say)} words (max {caps['say']})")
        if _SENTENCES.search(say):
            raise ValueError(f"segment {i}: say is more than one sentence")
        if _words(topic) > caps["topic"]:
            raise ValueError(f"segment {i}: topic is {_words(topic)} words (max {caps['topic']})")
        if not (_bridge_words(topic) & title_words):
            raise ValueError(f"segment {i}: topic shares no word with the title")
        allowed = sayable(seg)
        allowed_all |= allowed
        bad = _unexplained(say, allowed, str(seg.get("say") or ""))
        if bad:
            raise ValueError(f"segment {i}: number(s) not in this beat's data: {bad[:3]}")
        ents = _new_entities(f"{say} {topic}", pool)
        if ents:
            raise ValueError(f"segment {i}: names something the data does not: {ents[:3]}")
        out_segs.append({"topic": topic, "say": say})
    for key in ("title", "hook", "closing", "question"):
        bad = _unexplained(clean[key], allowed_all, original_all)
        if bad:
            raise ValueError(f"{key}: number(s) not in any beat's data: {bad[:3]}")
        if key != "title":
            ents = _new_entities(clean[key], pool)
            if ents:
                raise ValueError(f"{key}: names something the data does not: {ents[:3]}")
    every = " ".join([clean[k] for k in ("title", "hook", "closing", "question")]
                     + [f"{s['say']} {s['topic']}" for s in out_segs])
    spelled = {w.lower() for w in _SPELLED.findall(every)} - spelled_before
    if spelled:
        raise ValueError(f"a number written as a word cannot be checked: {sorted(spelled)}")
    clean["segments"] = out_segs
    return clean


REWRITE_SYSTEM = (
    "You rewrite the WORDS of one held YouTube Shorts data-explainer story so it clears "
    "every rule you are given. The numbers are sourced: use only numbers each segment's "
    "data can show, keep every number that is already correct, and never add a country, "
    "company or person the data does not name. Same number of segments, same order. "
    "Reply with ONE JSON object: {\"title\": str, \"hook\": str, \"closing\": str, "
    "\"question\": str, \"segments\": [{\"topic\": str, \"say\": str}]} and nothing else.")


def rewrite_text(req: dict) -> str:
    rules = "\n".join(f"- {r}" for r in req.get("rules") or [])
    return (f"RULES (the gate measures the rewrite against every one):\n{rules}\n\n"
            f"{str(req.get('how_to_answer') or '')[:1500]}\n\n"
            "The story, its data and why it was held are in the context.")


def rewrite_context(req: dict) -> dict:
    return {k: req.get(k) for k in ("current", "segments", "held_for", "reasons", "judge",
                                    "prior_rejection") if req.get(k) is not None}


# ----------------------------------------------------------------- asks

ASK_SYSTEM = (
    "Another program asked a language model the question below and is waiting for its "
    "reply. Write the reply that model would give, following the program's own "
    "instruction to the letter: the same format, JSON where JSON is asked for, no "
    "commentary. Reply with ONE JSON object {\"answer\": \"<that reply, as a string>\"} "
    "and nothing else.")
MAX_ASK_TEXT = 15_000


def _ask_validator(value: dict) -> dict:
    answer = value.get("answer") if isinstance(value, dict) else None
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 60_000:
        raise ValueError("an ask's answer is one non-empty string")
    return {"answer": answer.strip()}


def merge_answers(existing: str | None, rows: dict) -> str:
    """The answers file with `rows` added and nothing already there changed."""
    try:
        doc = json.loads(existing) if existing else {}
    except ValueError:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    answers = doc.get("answers") if isinstance(doc.get("answers"), dict) else {}
    for key, row in rows.items():
        answers.setdefault(key, row)
    doc["schema"] = doc.get("schema") or "shorts-ask-answers/v1"
    doc["answers"] = answers
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------- one round

def _repo(fleet: dict) -> tuple[str, str]:
    repo = fleet["repos"][FLEET_KEY]
    return f"{fleet['owner']}/{repo['github']}", repo["default_branch"]


def commit_message(now: dt.datetime | None = None, tz=None) -> str:
    """Never `[skip ci]`: the push is what runs Shorts' claim step."""
    day = _utc(now).astimezone(_zone(tz)).strftime("%Y%m%d")
    return f"exchange: mailbox round {day} (aletheia)"


def _open(index: dict | None, schema: str) -> list[dict]:
    if not index or index.get("schema") != schema or not isinstance(index.get("open"), list):
        return []
    return [e for e in index["open"] if isinstance(e, dict)]


def _write(fleet, path, text, *, message, request, merge=None) -> dict:
    kwargs = {"message": message, "merge": merge}
    if request is not None:
        kwargs["request"] = request
    return act.put_answer(fleet, FLEET_KEY, path, text, **kwargs)


def _answered(fleet, path, request) -> bool:
    kwargs = {"request": request} if request is not None else {}
    sha, _ = act.read_answer(fleet, FLEET_KEY, path, **kwargs)
    return bool(sha)


def _reviews(fleet, entries, *, read, request, message, deadline, fetch, routes, report) -> None:
    from aletheia import reasoner
    full, _ = _repo(fleet)
    tried = 0
    for entry in entries:
        if tried >= MAX_REVIEWS or time.monotonic() >= deadline:
            break
        rid, answer_path = str(entry.get("id") or ""), str(entry.get("answer_path") or "")
        row = {"id": rid, "path": answer_path}
        report["reviews"].append(row)
        request_path = str(entry.get("request") or "")
        if not (request_path.startswith("exchange/reviews/") and request_path.endswith(".request.json")):
            row["skipped"] = "the index names no request file"
            continue
        try:
            act.check_answer_path(fleet, FLEET_KEY, answer_path)
            if _answered(fleet, answer_path, request):
                row["skipped"] = "already answered"
                continue
        except act.Refused as exc:
            row["skipped"] = f"refused: {exc}"
            continue
        req = _read_json(read, request_path)
        if not req or req.get("id") != rid or req.get("answer_path") != answer_path \
                or not re.fullmatch(r"[0-9a-f]{64}", str(req.get("video_sha256") or "")) \
                or not isinstance(req.get("prompt"), str) or not req["prompt"].strip():
            row["skipped"] = "the request could not be read, or does not match its index line"
            continue
        tried += 1
        folder = Path(tempfile.mkdtemp(prefix="aletheia-shorts-frames-"))
        try:
            images = fetch_images(req, folder, full, fetch)
            if not images:
                row["skipped"] = "none of its frames could be fetched"
                continue
            try:
                grades, route = grade(req, folder, images, routes)
            except reasoner.ReasonerUnavailable as exc:
                row["skipped"] = str(exc)[:300]
                continue
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        body = {"schema": "shorts-review-verdict/v1", "request_id": req["id"],
                "video_sha256": req["video_sha256"], "by": f"aletheia:{route}",
                "graded_at": _stamp(), "grades": grades}
        try:
            row.update(_write(fleet, answer_path, json.dumps(body, indent=1, ensure_ascii=False) + "\n",
                              message=message, request=request))
            row["route"] = route
        except Exception as exc:                                     # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"


def _rewrites(fleet, entries, *, read, request, message, deadline, think, busy_slugs, report) -> None:
    from aletheia import reasoner
    think = think or reasoner.work_json_with_provider
    tried = 0
    for entry in entries:
        if tried >= MAX_REWRITES or time.monotonic() >= deadline:
            break
        rid, slug = str(entry.get("id") or ""), str(entry.get("slug") or "")
        answer_path = str(entry.get("answer_path") or "")
        row = {"id": rid, "path": answer_path}
        report["rewrites"].append(row)
        if slug in busy_slugs:
            row["skipped"] = "its video is still waiting on a review"
            continue
        request_path = str(entry.get("request") or "")
        if not (request_path.startswith("exchange/rewrites/") and request_path.endswith(".request.json")):
            row["skipped"] = "the index names no request file"
            continue
        try:
            act.check_answer_path(fleet, FLEET_KEY, answer_path)
            if _answered(fleet, answer_path, request):
                row["skipped"] = "already answered"
                continue
        except act.Refused as exc:
            row["skipped"] = f"refused: {exc}"
            continue
        req = _read_json(read, request_path)
        if not req or req.get("schema") != "shorts-rewrite-request/v1" or req.get("id") != rid \
                or req.get("slug") != slug or req.get("answer_path") != answer_path:
            row["skipped"] = "the request could not be read, or does not match its index line"
            continue
        tried += 1
        try:
            words, provider = think(REWRITE_SYSTEM, rewrite_text(req), context=rewrite_context(req),
                                    validator=lambda v, req=req: prevalidate_rewrite(req, v),
                                    model=reasoner.PLAN_MODEL, timeout_s=TEXT_TIMEOUT_S,
                                    max_context_bytes=96 * 1024)
        except reasoner.ReasonerUnavailable as exc:
            row["skipped"] = str(exc)[:300]
            break                                    # nobody can think: the rest wait too
        except ValueError as exc:
            row["skipped"] = f"the rewrite did not pass the rules: {str(exc)[:200]}"
            continue
        route = reasoner.provider_kind(provider) or "unknown"
        body = {"schema": "shorts-rewrite-answer/v1", "request_id": rid, "slug": slug,
                "by": f"aletheia:{route}", "written_at": _stamp(), **words}
        try:
            row.update(_write(fleet, answer_path, json.dumps(body, indent=1, ensure_ascii=False) + "\n",
                              message=message, request=request))
            row["route"] = route
        except Exception as exc:                                     # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"


def _asks(fleet, entries, *, read, request, message, deadline, think, report) -> None:
    from aletheia import reasoner
    think = think or reasoner.work_json_with_provider
    batches = [e for e in entries if str(e.get("batch") or "").startswith("exchange/asks/")]
    if not batches:
        return
    newest = max(batches, key=lambda e: str(e["batch"]))
    answer_path = str(newest.get("answer_path") or "")
    row = {"batch": newest["batch"], "path": answer_path, "answered": []}
    report["asks"] = row
    try:
        act.check_answer_path(fleet, FLEET_KEY, answer_path)
    except act.Refused as exc:
        row["skipped"] = f"refused: {exc}"
        return
    batch = _read_json(read, newest["batch"])
    if not batch or batch.get("answer_path") != answer_path or not isinstance(batch.get("asks"), dict):
        row["skipped"] = "the batch could not be read, or does not match its index line"
        return
    rows = {}
    for key in [str(k) for k in newest.get("keys") or []][:MAX_ASKS]:
        if time.monotonic() >= deadline:
            break
        ask = batch["asks"].get(key)
        if not isinstance(ask, dict):
            continue
        text = (f"INSTRUCTION THE MODEL WAS GIVEN:\n{ask.get('system') or ''}\n\n"
                f"MESSAGE IT WAS SENT:\n{ask.get('user') or ''}")
        if len(text) > MAX_ASK_TEXT:
            continue
        try:
            value, provider = think(ASK_SYSTEM, text, validator=_ask_validator,
                                    model=reasoner.PLAN_MODEL, timeout_s=TEXT_TIMEOUT_S)
        except reasoner.ReasonerUnavailable:
            break
        except ValueError:
            continue
        route = reasoner.provider_kind(provider) or "unknown"
        rows[key] = {"answer": value["answer"], "by": f"aletheia:{route}", "at": _stamp()}
    if not rows:
        row["skipped"] = "nothing answered"
        return
    try:
        row.update(_write(fleet, answer_path, "", message=message, request=request,
                          merge=lambda existing: merge_answers(existing, rows)))
        row["answered"] = sorted(rows)
    except Exception as exc:                                         # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"


def _written(report: dict) -> list[str]:
    paths = [r["path"] for r in report["reviews"] + report["rewrites"] if r.get("written")]
    if (report.get("asks") or {}).get("written"):
        paths.append(report["asks"]["path"])
    return paths


def once(*, force: bool = False, slot: str = "", fleet: dict | None = None,
         read=None, request=None, fetch=None, routes=None, think=None,
         budget_s: float = RUN_BUDGET_S, now: dt.datetime | None = None, tz=None) -> dict:
    """One bounded round. Returns (and saves as latest.json) what it did."""
    report: dict = {"started_at": _stamp(), "slot": slot, "force": bool(force),
                    "reviews": [], "rewrites": [], "asks": None}

    def done(outcome: str, why: str = "") -> dict:
        report.update({"outcome": outcome, "why": why, "finished_at": _stamp()})
        try:
            stateio.write_json_atomic(_latest_path(), report)
        except Exception:                                            # noqa: BLE001
            pass
        return report

    if closed.is_closed():
        return done("closed", "Aletheia is closed")
    try:
        policy.ensure_not_halted()
    except policy.Halted as exc:
        return done("halted", str(exc))
    if not force and not slot:
        return done("refused", "outside a morning slot - use --force to run one by hand")
    if fleet is None:
        from aletheia.fleet import load_fleet
        fleet = load_fleet()
    if not _granted(fleet):
        return done("refused", "config/fleet.json grants no answers on Shorts-pipeline")
    if request is None:
        from aletheia import gh
        if not gh.token():
            return done("refused", "no GitHub token on this PC (FLEET_TOKEN or the github.fleet secret)")
    full, branch = _repo(fleet)
    read = read or _default_reader(full, branch)
    if not _take_lock():
        return done("busy", "another round is running")
    try:
        deadline = time.monotonic() + budget_s
        message = commit_message(now, tz)
        reviews = _open(_read_json(read, REVIEW_INDEX), "shorts-review-index/v1")
        busy = {str(e.get("slug") or "") for e in reviews}
        _reviews(fleet, reviews, read=read, request=request, message=message,
                 deadline=deadline, fetch=fetch, routes=routes, report=report)
        rewrites = _open(_read_json(read, REWRITE_INDEX), "shorts-rewrite-index/v1")
        _rewrites(fleet, rewrites, read=read, request=request, message=message,
                  deadline=deadline, think=think, busy_slugs=busy, report=report)
        if deadline - time.monotonic() >= min(ASKS_NEED_S, budget_s / 2):
            asks = _open(_read_json(read, ASK_INDEX), "shorts-ask-index/v1")
            _asks(fleet, asks, read=read, request=request, message=message,
                  deadline=deadline, think=think, report=report)
    finally:
        _release_lock()
    written = _written(report)
    graded = sum(1 for r in report["reviews"] if r.get("written"))
    reworded = sum(1 for r in report["rewrites"] if r.get("written"))
    asked = len((report.get("asks") or {}).get("answered") or []) \
        if (report.get("asks") or {}).get("written") else 0
    said = (f"answered Shorts-pipeline's mailboxes on its main branch: {graded} review grade(s), "
            f"{reworded} rewrite(s), {asked} ask(s)")
    journal.append("event", "repo:shorts_pipeline", f"mailbox round: {said}", actor=ACTOR)
    if written:
        try:
            from aletheia import autonomy, tools
            autonomy.record(tool="shorts.mailbox.answer", args={"paths": written[:20]},
                            consequence=tools.OUTWARD, said=said, route="shorts_mailbox",
                            undo={"how": autonomy.NONE,
                                  "why": "a commit on his repository; reverting it is his call"})
        except Exception:                                            # noqa: BLE001
            pass
    return done("ok", said)


# ----------------------------------------------------------------- CLI

def status(now: dt.datetime | None = None, tz=None) -> dict:
    try:
        latest = stateio.read_json(_latest_path())
    except ValueError:
        latest = None
    local = _utc(now).astimezone(_zone(tz))
    return {"slots": list(SLOTS), "window_minutes": SLOT_WINDOW_MIN,
            "in_slot": slot_for(now, tz), "today": local.date().isoformat(),
            "rounds_today": [p.stem for p in receipts_for(local.date().isoformat())],
            "running": running(), "latest": latest}


def main(argv: list[str] | None = None) -> int:
    # Before anything else: this runs unattended, launched by the Core, and
    # must never inherit the right to open his signed-in ChatGPT.
    browser_reasoner.drop_lease()
    ap = argparse.ArgumentParser(description="Answer Shorts-pipeline's mailboxes.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("once", help="one bounded round")
    one.add_argument("--force", action="store_true", help="run now, outside a morning slot")
    one.add_argument("--slot", default="", help=argparse.SUPPRESS)
    sub.add_parser("status")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        print(json.dumps(status(), indent=1, default=str))
        return 0
    report = once(force=args.force, slot=args.slot)
    print(json.dumps({k: report.get(k) for k in ("outcome", "why")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
