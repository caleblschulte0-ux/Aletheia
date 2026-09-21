"""ONE list of things that genuinely need him, and one list of what she did.

Not a new system. Everything here already existed and was scattered across
five surfaces that each showed a slice: approvals lived in `policy` and
were read by the wall; work blocked on him lived in `work_engine` and was
read by the work session's report; applications stopped on a question
lived in the campaign records and were read by `current_state`; a mission
at a boundary lived in `browser_mission`; a handoff lived in `handoffs`.

Each of those is a real store with a real reader, and that was the
problem: he had to know which of five questions to ask before he could
find out whether anything needed him. "What's waiting on me" answered
from one of them and the rest stayed silent, which is worse than a long
list — a short list that is quietly incomplete teaches him to trust it.

So this module reads them all, gives every row THE SAME SHAPE, and says
three things about each:

    what        the thing itself, in his words, one sentence
    why         why it needs HIM and not her
    if_ignored  what happens if he does nothing, which is the half of
                every request that never got written down

`if_ignored` is the one that matters. "Say approve to run it" tells him
what yes does and leaves no as something he has to infer — so a safe,
reversible, deliberate "not now" feels like a thing he has forgotten. A
row that says "nothing happens until you do" is a row he can walk past.

Nothing here decides anything, grants anything, or changes any state. It
is a reader over stores that already exist; the kill switch, the approval
gates and who may approve what are all exactly as they were.
"""
from __future__ import annotations

import datetime as dt
import re

from aletheia import work_states as ws

#: Long enough that nothing real is hidden, short enough to read.
MAX_ITEMS = 25
#: One sentence. Anything longer is a paragraph he has to parse before he
#: can decide, and deciding is the whole point of the list.
MAX_WORDS_CHARS = 140


def _safe(fn, default):
    """One dead store must never hide the other four.

    This is the list that answers "is anything waiting on me". A source
    that raises has to cost its own rows and nothing else, or a broken
    calendar makes an unanswered approval invisible — and the failure
    mode of THAT is him not knowing he was asked.
    """
    try:
        return fn()
    except Exception:
        return default


def _said(text: object, limit: int = MAX_WORDS_CHARS) -> str:
    """Through the one reading door, then cut at a word boundary.

    It used to strip ids and stop there, so the activity list arrived as
    "formfill: read 35 fields on https://boards.greenhouse.io/embed/job_app
    ?for=dropbox&token=8675308002" — a tracking URL on his phone, and three
    lines of it. `speech.for_reading` is what the screen's own ribbon uses,
    and one list read two ways must be cleaned one way.
    """
    from aletheia import speech
    return speech.shorten(speech.for_reading(text), limit)


def _row(*, id: str, kind: str, what: str, why: str, if_ignored: str,
         since: str = "", how: str = "", which: str = "") -> dict:
    """One thing needing him, in the one shape.

    `which` is the half that tells two otherwise identical rows apart, and
    it is empty for almost everything. It exists because thirty-eight
    pending applications on his machine share one `what` — "It sends your
    application to this employer under your name. There is no undo." —
    which is true of every one of them and names none of them.
    """
    return {"id": str(id), "kind": kind, "what": _said(what),
            "why": _said(why, 120), "if_ignored": _said(if_ignored, 120),
            "since": str(since or ""), "how": _said(how, 90),
            "which": _said(which, 120)}


# ---------------------------------------------------------------- sources
def _approvals() -> list[dict]:
    from aletheia import intercom, policy, voice
    out = []
    for approval in policy.all_approvals():
        if approval.get("state") != "PENDING":
            continue
        tier = str(approval.get("tier") or "")
        routine = not tier or tier == intercom.TIER_ROUTINE
        out.append(_row(
            id=str(approval.get("id") or ""),
            kind="approval",
            what=voice.approval_label(approval),
            why="I need your yes before I do it",
            if_ignored="nothing happens",
            which=voice.approval_about(approval),
            since=str(approval.get("requested_at") or ""),
            how=("say approve and I'll do it" if routine
                 else "say yes on your phone or at the keyboard and I'll "
                      "do it")))
    return out


#: Work states that mean the item is sitting on HIM. BLOCKED_EXTERNAL is
#: deliberately absent: waiting on the world is not waiting on Caleb, and
#: a list that cannot tell those apart is a list he learns to skim.
HIS_STATES = (ws.BLOCKED_USER, ws.BLOCKED_LOGIN)


def _work() -> list[dict]:
    from aletheia import work_engine
    inventory = work_engine.inventory(probe=False)
    out = []
    for item in inventory.get("items") or []:
        if item.get("state") not in HIS_STATES:
            continue
        signing_in = item.get("state") == ws.BLOCKED_LOGIN
        out.append(_row(
            id=str(item.get("id") or ""),
            kind="work",
            what=item.get("title"),
            why=(item.get("reason")
                 or ("it needs you signed in" if signing_in
                     else "only you can answer this")),
            # The item's own `next` is written as what happens when he
            # acts. What he needs here is what happens when he doesn't.
            if_ignored="it stays where it is until you get to it",
            since=str(item.get("updated") or ""),
            how=str(item.get("next") or "")))
    return out


def _applications() -> list[dict]:
    """Applications stopped on a question only he can answer.

    Twelve of these sat unanswered once while "what do you need from me"
    said nothing was waiting, because they were in a different store from
    the one that sentence read.
    """
    from aletheia import current_state
    hunt = current_state.job_hunt()
    out = []
    for waiting in hunt.get("waiting_on_him") or []:
        questions = list(waiting.get("questions") or [])
        first = str(questions[0] or "").strip() if questions else ""
        who = current_state.said_name(str(waiting.get("company") or ""),
                                      str(waiting.get("job") or ""))
        # THE QUESTION IS THE THING. "Brex" is who is asking; what he has
        # to do is answer "Preferred shift", and a row naming only the
        # employer makes him go and look it up before he can act.
        out.append(_row(
            id=str(waiting.get("id") or ""),
            kind="application",
            what=f"{who} asks: {first}" if first else who,
            why=str(waiting.get("why") or "") or "only you can answer this",
            if_ignored="the application stays unsent",
            since=str(waiting.get("at") or ""),
            how="answer it and I'll finish the form"))
    return out


SOURCES = {"approval": _approvals, "work": _work, "application": _applications}


# ------------------------------------------------------------------ list
def _key(row: dict) -> str:
    """Two rows about the same thing, seen from two stores, are one row.

    A handoff is a work item AND an approval; an application waiting on a
    question is a work item AND a campaign record. Showing both is how a
    list of four real decisions becomes a list of nine.

    `which` is part of the key, and has to be: on his machine thirty-eight
    pending applications share one `what`, so keying on the sentence alone
    collapsed thirty-eight separate irreversible decisions into one row.
    A list that is quietly incomplete is worse than a long one — it is the
    exact failure this module's own docstring warns about.
    """
    import re
    said = str(row.get("what", "")) + " " + str(row.get("which", ""))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", said.casefold()).split())


def items(now: dt.datetime | None = None, *, limit: int = MAX_ITEMS,
          sources: dict | None = None) -> list[dict]:
    """Everything genuinely waiting on him: deduplicated, newest first."""
    del now                     # rows carry their own times; nothing is computed
    gathered: list[dict] = []
    for read in (sources or SOURCES).values():
        gathered.extend(_safe(read, []))
    seen, out = set(), []
    for row in sorted(gathered, key=lambda r: str(r.get("since") or ""),
                      reverse=True):
        key = _key(row)
        if not row["what"] or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[:max(1, int(limit))]


def spoken(rows: list[dict] | None = None) -> str:
    """The list, said out loud — the thing first, the count only if real.

    "1 waiting on you — the first is Cancel the task to call the plumber"
    is a row index read aloud: he cannot act on "the first", there is no
    second, and the one fact arrives last.
    """
    from aletheia import speech
    rows = items() if rows is None else rows
    if not rows:
        return "Nothing needs you right now."
    first = rows[0]
    # NAMING ONE OF SEVERAL HAS TO SAY SO. "3 things need you: thing 0."
    # reads as though thing 0 were the whole list.
    said = (f"One thing needs you: {first['what'].rstrip('.')}."
            if len(rows) == 1 else
            f"{speech.count_phrase(len(rows), 'thing')} need you. First: "
            f"{first['what'].rstrip('.')}.")
    if first["how"]:
        how = first["how"].rstrip(".")
        said += f" {how[0].upper()}{how[1:]}."
    if first["if_ignored"]:
        said += f" If you don't, {first['if_ignored'].rstrip('.')}."
    return said


# -------------------------------------------------------------- activity
#: What she finished, what failed, what she did without being asked — from
#: the receipts that already exist. No new store: the journal has every
#: action, `work_engine` has every item's end state, and `autonomy` has
#: the unattended ledger. A fourth copy would be a fourth thing to go
#: stale.
ACTIVITY_HOURS = 24.0


def activity(*, hours: float = ACTIVITY_HOURS, limit: int = 30) -> list[dict]:
    """One history view: {"at", "what", "outcome"}, newest first.

    `outcome` is one of "finished", "failed" or "unattended" — the three
    things he actually asks about ("what did you do", "did anything
    break", "what did you do without asking me"), each answered from the
    store that really knows.
    """
    rows: list[dict] = []
    for row in _safe(lambda: _finished_and_failed(hours), []):
        rows.append(row)
    for row in _safe(lambda: _unattended(hours, limit), []):
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    return rows[:max(1, int(limit))]


#: Journal kinds that record something GOING WRONG, and the one that
#: records something going right again. "repo health red -> green" is a
#: RECOVERY: filing it under "failed" tells him something broke at the
#: exact moment it stopped being broken, which is the opposite of the
#: truth and the kind of thing that makes a history view unreadable.
_FAILED_KINDS = frozenset({"alert", "error"})
_RECOVERED_KINDS = frozenset({"recovery"})


def _outcome_of(kind: object) -> str:
    if kind in _FAILED_KINDS:
        return "failed"
    return "recovered" if kind in _RECOVERED_KINDS else "finished"


def _finished_and_failed(hours: float) -> list[dict]:
    from aletheia import recollection
    return [{"at": str(row.get("at") or ""), "what": _said(row.get("what")),
             "outcome": _outcome_of(row.get("kind"))}
            for row in recollection.day(hours=hours)]


def _unattended(hours: float, limit: int) -> list[dict]:
    from aletheia import autonomy
    out = []
    for row in autonomy.recent(hours=hours, limit=limit):
        said = str(row.get("said") or "").strip() or f"ran {row.get('tool')}"
        out.append({"at": str(row.get("at") or ""), "what": _said(said),
                    "outcome": "unattended",
                    "outward": bool(_safe(lambda: autonomy.is_outward(row), True))})
    return out


# ------------------------------------------------- what would not be asked now
#: A browser mission's approval id: `<mission id>--g<n>-commit-<digest>`.
_MISSION_APPROVAL = re.compile(r"^(?P<mission>.+?)--g\d+-commit-[0-9a-f]+$")
def would_not_ask_now() -> list[dict]:
    """Which PENDING approvals the loop would no longer raise, and why.

    READ ONLY, and deliberately so. It decides nothing: denying an
    approval is his, and a tool that cleared its own mistakes would be
    Aletheia approving her own approvals from the other end. This prints
    a list so he can deny them on the page in one pass.

    The judgement is the REAL rule — `page_state.control_kind`, the same
    function the loop asks — fed the evidence the mission wrote down: the
    button it stopped on, and whether it had put any of his answers into
    that page. Evidence it did NOT write down (the control's role, its
    address, its seat in the site's navigation) is assumed absent, which
    can only ever make this list SHORTER than the truth.
    """
    from aletheia import browser_loop, browser_mission, computer, page_state as ps, policy, voice
    rows = []
    for approval in _safe(policy.all_approvals, []):
        if approval.get("state") != "PENDING":
            continue
        aid = str(approval.get("id") or "")
        hit = _MISSION_APPROVAL.match(aid)
        row = {"id": aid, "what": _safe(lambda a=approval: voice.approval_label(a), aid),
               "since": str(approval.get("requested_at") or ""), "button": "", "url": "",
               "still_asked": True, "why": ""}
        if not hit or str(approval.get("capability") or "") != "web.commit":
            row["why"] = ("not the browser loop's — this one is staged by the form filler "
                          "and untouched by the new rule")
            rows.append(row)
            continue
        try:
            record = browser_mission.load(hit.group("mission"))
        except Exception:
            row["why"] = "its mission record cannot be read, so nothing here judges it"
            rows.append(row)
            continue
        gate = record.get("gate") or {}
        row["button"] = " ".join(str(gate.get("button") or "").split())
        row["url"] = str(gate.get("url") or record.get("start_url") or "")
        filled = browser_loop.she_filled_something(record)
        kind = ps.control_kind(row["button"], role="button", on_form=True, sendable=filled)
        if kind == ps.COMMIT and not filled and not computer.committing_label(row["button"]):
            # `_gate`'s own boundary, said the same way: an unknown button on
            # a page she never filled is NO_WAY_FORWARD, not an approval. A
            # button whose words DO commit is unaffected, filled or not.
            kind = ps.OTHER
        row["still_asked"] = kind in (ps.COMMIT, ps.CREATE_ACCOUNT, ps.SPEND)
        row["kind"] = kind
        if row["still_asked"]:
            row["why"] = (f"it still reads as {kind.replace('_', ' ')}"
                          + (" on a page this run had filled in" if filled else ""))
        else:
            row["why"] = ("nothing on that page held his answers, and the button's own words "
                          "do not commit anything" if not filled else
                          "the button's own words say it does not send anything")
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="What needs Caleb, and what she did.")
    ap.add_argument("what", nargs="?", default="needs",
                    choices=["needs", "activity", "say", "noise"])
    args = ap.parse_args(argv)
    if args.what == "noise":
        rows = would_not_ask_now()
        drop = [r for r in rows if not r["still_asked"]]
        keep = [r for r in rows if r["still_asked"]]
        print(f"{len(rows)} pending; {len(drop)} would no longer be raised.\n")
        print("WOULD NO LONGER BE ASKED (deny these yourself — I will not):")
        for r in drop or [{"what": "(none)", "why": "", "id": "", "url": ""}]:
            print(f"- {r['what']}")
            if r.get("why"):
                print(f"    because {r['why']}")
            if r.get("url"):
                print(f"    {r['url'][:100]}")
            if r.get("id"):
                print(f"    {r['id']}")
        print("\nSTILL ASKED:")
        for r in keep:
            print(f"- {r['what']}")
            if r.get("why"):
                print(f"    because {r['why']}")
        return 0
    if args.what == "say":
        print(spoken())
        return 0
    if args.what == "activity":
        for row in activity():
            print(f"{row['at']}  {row['outcome']:<10} {row['what']}")
        return 0
    rows = items()
    if not rows:
        print("Nothing needs you right now.")
        return 0
    for row in rows:
        print(f"- {row['what']}")
        print(f"    because {row['why']}")
        print(f"    if you ignore it: {row['if_ignored']}")
        if row["how"]:
            print(f"    to answer: {row['how']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
