"""Turning an employer's NAME into a board she can read - no model, no search engine.

His words, 2026-09-23: *"it sounds like it's not looking on the widespread
deep corners of the internet that I want if it keeps getting cycled back to
these couple companies."* Measured that morning: 373 employers remembered,
228 of them with no domain and no board (The Muse names a company and
nothing else), and the only two lanes that could turn a name into a board
were nine model searches a day and six crawled sites a batch. A known
employer was re-read every five minutes; an unknown one was never probed.

Every public applicant-tracking system she can list (`jobs.PROVIDERS`)
addresses a board by a token that is, almost always, the company's own name
squashed: `boards.greenhouse.io/notion`, `jobs.lever.co/ramp`,
`jobs.ashbyhq.com/vanta`, `apply.workable.com/acme`,
`api.smartrecruiters.com/v1/companies/Adyen`. So a name is a handful of
candidate boards, and `jobs.prove_boards` says which of them answer with
openings. A board is kept only when it is LIVE and its published company
name is the employer's - a slug that collides with somebody else's board is
the one way this could learn a lie, and the name check is what stops it.

Bounded: `MAX_EMPLOYERS_PER_BATCH` names a batch, each probed once per
`PROBE_AGAIN_AFTER`, every request a small public JSON read. Nothing here
asks a model or a search engine.

Measured live before this landed: six names in 2.5 s, three boards - and one
of the three was a trial subdomain somebody had named "Allstate", listing
"Senior Marketer (Sample)" in Amsterdam. A board whose openings are samples
is nobody's board (`_DEMO`).
"""
from __future__ import annotations

import datetime as dt
import json
import re

from aletheia import journal, stateio

ACTOR = "aletheia-jobs"
MAX_EMPLOYERS_PER_BATCH = 6
PROBE_AGAIN_AFTER = dt.timedelta(days=30)
MAX_LEDGER = 3000
#: Words that name a kind of company, not the company.
_GENERIC = frozenset("inc llc ltd corp corporation company co group holdings labs technologies technology "
                     "software systems solutions services international global the and of".split())
#: An opening that is a system's own placeholder, not a job.
_DEMO = re.compile(r"\b(?:sample|demo|test|example|placeholder|lorem)\b", re.I)


def _ledger_path():
    return stateio.private_dir("jobs") / "probed_employers.json"


def _ledger() -> dict:
    try:
        rows = json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rows if isinstance(rows, dict) else {}


def _words(name: str) -> list[str]:
    from aletheia import employers
    return employers.name_key(name).split()


def slugs(name: str) -> dict[str, list[str]]:
    """The tokens a name is likely to be on each system, most likely first."""
    words = _words(name)
    if not words:
        return {}
    joined = "".join(words)
    hyphen = "-".join(words)
    camel = "".join(w.capitalize() for w in words)
    lower = [t for t in dict.fromkeys((joined, hyphen)) if t]
    return {"greenhouse": lower, "lever": lower, "ashby": lower, "workable": lower,
            "recruitee": [t for t in lower if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", t)],
            "smartrecruiters": list(dict.fromkeys((camel, joined)))}


def candidates(name: str) -> list[dict]:
    from aletheia import jobs
    out = []
    for provider, tokens in slugs(name).items():
        if provider not in jobs.PROVIDERS:
            continue
        for token in tokens:
            out.append({"provider": provider, "board": token, "company": name, "found_by": "name probe"})
    return out


def same_employer(published: str, name: str) -> bool:
    """Is the board's published company name this employer's? The same name,
    or a shorter form of it - "Achieve Together" is not "Achieve", and
    "Labs" is nobody's name."""
    def distinctive(text: str) -> set[str]:
        return {w for w in _words(text) if len(w) >= 3 and w not in _GENERIC}
    a, b = distinctive(published), distinctive(name)
    if not a or not b:
        return False
    # The published name may be a shorter form of the employer's ("Notion"
    # for Notion Labs, "Adyen" for Adyen N.V.); it may not carry a word the
    # employer's name does not ("Achieve Together" is not Achieve).
    return a <= b


def pick(rows: list[dict], *, learned: set, ledger: dict, now: dt.datetime, limit: int) -> list[dict]:
    """Employers worth a probe: no board known, not probed lately."""
    from aletheia import employers
    out = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name or len(_words(name)) == 0:
            continue
        key = employers.name_key(name)
        if (str(row.get("ats") or ""), str(row.get("token") or "")) in learned or key in learned:
            continue                      # a board of this name is already read every batch
        if str(row.get("ats") or "") and str(row.get("token") or ""):
            continue                      # its board is already known
        last = str(ledger.get(key) or "")
        try:
            when = dt.datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        except ValueError:
            when = None
        if when is not None and now - when < PROBE_AGAIN_AFTER:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def probe(*, limit: int = MAX_EMPLOYERS_PER_BATCH, fetcher=None, now: dt.datetime | None = None,
          rows: list[dict] | None = None) -> dict:
    """Try the next few employers' names on every system. Never raises."""
    from aletheia import employers, jobs
    now = now or dt.datetime.now(dt.timezone.utc)
    report = {"tried": [], "found": []}
    try:
        rows = employers.all_rows() if rows is None else rows
        learned = {(r["provider"], r["token"]) for r in jobs._learned_boards()}
        learned |= {employers.name_key(r.get("company") or "") for r in jobs._learned_boards()} - {""}
        ledger = _ledger()
        chosen = pick(rows, learned=learned, ledger=ledger, now=now, limit=max(0, int(limit)))
        if not chosen:
            return report
        wanted = [c for row in chosen for c in candidates(row["name"])]
        proved = jobs.prove_boards(wanted, fetcher=_reading(fetcher))
        keep = []
        for p in proved:
            if not p.get("live") or int(p.get("count") or 0) <= 0:
                continue
            if not same_employer(str(p.get("company") or ""), str(p.get("found_for") or p.get("board") or "")) \
                    and not same_employer(str(p.get("company") or ""), _name_for(p, wanted)):
                continue
            keep.append({"provider": p["provider"], "board": p["board"], "company": p.get("company") or "",
                         "found_by": "name probe"})
        # One board per employer per system is plenty; the first live one wins.
        seen, found = set(), []
        for k in keep:
            key = (k["provider"], _name_for(k, wanted))
            if key in seen:
                continue
            seen.add(key)
            found.append(k)
        if found:
            jobs.learn_boards(found, source="name probe")
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        for row in chosen:
            ledger[employers.name_key(row["name"])] = stamp
        if len(ledger) > MAX_LEDGER:
            ledger = dict(sorted(ledger.items(), key=lambda kv: kv[1])[-MAX_LEDGER:])
        path = _ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(path, ledger)
        report["tried"] = [row["name"] for row in chosen]
        report["found"] = found
        try:
            from aletheia import speech
            names = speech.and_list([f["company"] for f in found[:4]]) if found else ""
            journal.append("action", "jobs",
                           f"tried {speech.count_phrase(len(chosen), 'employer')}' names on the job systems: "
                           + (f"{speech.count_phrase(len(found), 'board')} found ({names})" if found
                              else "no boards found"), actor=ACTOR)
        except Exception:
            pass
    except Exception:
        return report
    return report


def real_openings(rows: list[dict]) -> list[dict]:
    """The openings that are jobs: a trial board lists "Senior Marketer
    (Sample)" and answers as live."""
    return [r for r in rows or [] if isinstance(r, dict) and not _DEMO.search(str(r.get("title") or ""))]


def _reading(fetcher):
    """Each candidate read through its system, samples left out."""
    from aletheia import jobs

    def read(board: dict) -> list[dict]:
        provider = jobs.PROVIDERS.get(board.get("provider"))
        rows = (fetcher or provider)(board)
        return real_openings(rows)
    return read


def _name_for(proved: dict, wanted: list[dict]) -> str:
    """The employer name a candidate was made for (kept on the candidate)."""
    for c in wanted:
        if c["provider"] == proved.get("provider") and c["board"] == proved.get("board"):
            return str(c.get("company") or "")
    return ""
