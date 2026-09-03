"""Ten job applications, ready to send — and she does not send them.

"Apply to 10 jobs for me" is the sharpest test this system has been given,
because it is one sentence containing about eight hours of real work and
one irreversible act at the end of it. Run through the planner as it
stood, it came back honestly and uselessly: research the openings
(executable), a GAP saying nothing here submits an application, and a
MANUAL step reading "review the openings and submit each one yourself".

Correct on every count, and it left him with ten browser tabs.

So this does the eight hours. For each real posting it finds, it writes a
PACKET into her workspace: the posting as it actually read it, a cover
letter written against that posting and his resume, and a checklist of
what is still his to do. Then it files one task per application, so
"did I hear back from the third one?" is answerable in a fortnight.

WHY IT DOES NOT SUBMIT, which is not an apology.

Four gates already refuse this and every one of them is deliberate:

  - `errand.run` is EXPERIMENTAL, `operator_always`, and sits in
    `agenda.MONEY` — refused absolutely in an autonomous agenda, with no
    flag that turns it off.
  - `browser.interact` is `operator_always` and needs an approval bound
    to a sha256 of the exact steps, which a spoken sentence cannot carry.
  - `computer.act` refuses any control whose label commits — Submit,
    Send, Confirm — and bounces it to that same hash-bound approval.
  - the planner names the gap rather than improvising around it.

And the reason underneath all four: a submitted application is a real
message to a real employer under his name, and there is no undo. Every
other thing in this module is a file in a folder he can delete. That is
the line, and moving it is his call to make deliberately, not a
convenience this module quietly buys itself.

WHAT IT REFUSES TO FAKE. A posting it could not actually read is not
written up from the search-result blurb — it is dropped, and said out
loud. A cover letter about a job she never opened is exactly the
confident placeholder `compose` exists to abolish, and it would be
sitting in his outbox rather than in a log.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys

from aletheia import browse, compose, journal, policy, research, tasks, workspace

ACTOR = "aletheia-applications"

MAX_APPLICATIONS = 10
# Read more candidates than he asked for: search results are not all
# postings, and dropping the ones she could not read is the point.
CANDIDATE_FACTOR = 3
MIN_POSTING_CHARS = 600
MAX_POSTING_CHARS = 8_000
FOLDER = "applications"

# A page has to look like a posting rather than a listing index or a blog
# post about hiring. Cheap and honest: it filters, the operator decides.
HIRING_WORDS = ("responsibilities", "qualifications", "requirements",
                "what you'll do", "what you will do", "about the role",
                "apply", "we're looking for", "we are looking for",
                "experience with", "benefits")

LETTER = (
    "Write a cover letter from Caleb Schulte for the job posting below, "
    "using his resume. Specific, not generic: name the actual company and "
    "role, and connect two or three concrete things he has really built to "
    "what this posting actually asks for. Four short paragraphs at most, no "
    "flattery, no 'I am writing to express my interest'. If the posting does "
    "not say what the job is, say CANNOT WRITE rather than inventing a role."
)


class ApplicationError(RuntimeError):
    pass


def _slug(text: str, limit: int = 40) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", str(text).casefold()).strip("-")
    return (out[:limit].strip("-") or "posting")


def _looks_like_a_posting(page: dict, role: str) -> bool:
    text = (page.get("extract") or "").casefold()
    if len(text) < MIN_POSTING_CHARS:
        return False
    hits = sum(1 for word in HIRING_WORDS if word in text)
    role_words = [w for w in re.split(r"\W+", role.casefold()) if len(w) > 3]
    named = any(w in text or w in (page.get("title") or "").casefold()
                for w in role_words) if role_words else True
    return hits >= 2 and named


def _fingerprint(url: str) -> str:
    """Six characters of the URL, so two postings are never one packet.

    Found by the first end-to-end run: "Foundry 1" and "Foundry 2" both
    slugged to the same 32 characters, so the second packet OVERWROTE the
    first and the second `tasks.create` raised FileExistsError into a
    swallow. Two applications, one folder, one task, no error — the kind of
    quiet loss that only shows up when he wonders where the third one went.
    """
    return hashlib.sha1(str(url or "").encode("utf-8")).hexdigest()[:6]


def _packet_dir(day: str, page: dict) -> str:
    url = page.get("url") or ""
    host = re.sub(r"^www\.", "", url.split("/")[2:3][0] if "//" in url else "job")
    return (f"{FOLDER}/{day}-{_slug(host, 24)}-"
            f"{_slug(page.get('title', ''), 28)}-{_fingerprint(url)}")


def _write_posting(folder: str, page: dict) -> str:
    path = f"{folder}/posting.md"
    workspace.write(path, "\n".join([
        f"# {page.get('title') or 'Posting'}",
        "",
        f"Source: {page.get('url')}",
        f"Read: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "---",
        "",
        (page.get("extract") or "")[:MAX_POSTING_CHARS],
    ]), why="the posting as she actually read it")
    return path


def _write_checklist(folder: str, page: dict, letter_path: str | None,
                     problem: str = "") -> str:
    path = f"{folder}/checklist.md"
    lines = [
        f"# {page.get('title') or 'Application'}",
        "",
        f"- Posting: {page.get('url')}",
        f"- The posting as she read it: `{folder}/posting.md`",
    ]
    if letter_path:
        lines.append(f"- Cover letter she wrote: `{letter_path}`")
    else:
        lines.append(f"- Cover letter: NOT WRITTEN — {problem}")
    lines += [
        "",
        "## Yours to do",
        "",
        ("- [ ] Read the letter and make it sound like you." if letter_path
         else "- [ ] Write the cover letter yourself — she could not."),
        "- [ ] Open the posting and fill in the application form.",
        "- [ ] Attach your resume.",
        "- [ ] Submit it.",
        "",
        "She does not submit applications. A submitted application is a real "
        "message to a real employer under your name and there is no undo — "
        "so the last step is yours, on purpose. Everything above it is a "
        "file in a folder you can delete.",
    ]
    workspace.write(path, "\n".join(lines), why="what is still his to do")
    return path


def prepare(role: str, *, count: int = 5, resume: str = "resume.md",
            where: str = "", finder=None, reader=None, writer=None) -> dict:
    """Find real postings, write a packet for each. Submits nothing."""
    role = " ".join(str(role or "").split())
    if not role:
        raise ValueError("say what kind of role")
    count = max(1, min(int(count), MAX_APPLICATIONS))
    policy.ensure_not_halted()

    if finder is None or reader is None:
        usable, why = browse.available()
        if not usable:
            raise ApplicationError(
                f"she cannot read job postings right now: {why}. Writing "
                "applications from search-result blurbs would mean cover "
                "letters about jobs she never opened, so nothing was written.")
    finder = finder or research.find_sources
    reader = reader or research.read_sources

    query = f"{role} job openings{(' ' + where) if where else ''}"
    candidates = finder(query, limit=count * CANDIDATE_FACTOR)
    if not candidates:
        raise ApplicationError(
            f"no search results for {query!r} — say the role differently, or "
            "name a job board to look at.")
    pages, unreadable = reader(candidates[:count * CANDIDATE_FACTOR])

    day = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    packets, skipped = [], []
    for page in pages:
        if len(packets) >= count:
            break
        if not _looks_like_a_posting(page, role):
            # A search hit that is a listing index or an article about
            # hiring is not a job. Saying so beats a packet for a page
            # nobody can apply to.
            skipped.append({"url": page.get("url"),
                            "why": "did not read like an actual posting"})
            continue
        folder = _packet_dir(day, page)
        posting_path = _write_posting(folder, page)
        letter_path, problem = None, ""
        try:
            receipt = compose.compose(
                LETTER, f"{folder}/cover-letter.md",
                sources=[resume, posting_path],
                why=f"cover letter for {page.get('title', '')[:60]}",
                think=writer)
            letter_path = receipt["path"]
        except Exception as exc:
            problem = f"{type(exc).__name__}: {exc}"[:200]
        checklist = _write_checklist(folder, page, letter_path, problem)
        task_id = (f"apply-{_slug(page.get('title', ''), 26)}-"
                   f"{_fingerprint(page.get('url'))}")[:60]
        try:
            tasks.create(task_id,
                         f"Apply: {page.get('title') or role} — {page.get('url')}",
                         assigned_worker="operator")
        except FileExistsError:
            pass
        packets.append({"title": page.get("title"), "url": page.get("url"),
                        "folder": folder, "checklist": checklist,
                        "letter": letter_path, "problem": problem,
                        "task": task_id})

    if not packets:
        raise ApplicationError(
            f"found {len(pages)} page(s) for {role!r} and none of them read "
            "like an actual job posting. Nothing was written — a cover letter "
            "for a page she could not read is worse than no cover letter.")

    journal.append("action", "applications",
                   f"prepared {len(packets)} application packet(s) for {role!r} "
                   f"— submitted none", actor=ACTOR)
    return {"role": role, "prepared": packets, "skipped": skipped,
            "unreadable": unreadable, "submitted": 0,
            "note": ("Nothing was submitted. Each folder has the posting, a "
                     "cover letter and a checklist; the last step is yours.")}


def spoken(result: dict) -> str:
    n = len(result["prepared"])
    failed = sum(1 for p in result["prepared"] if p["problem"])
    said = (f"{n} application packet{'s' if n != 1 else ''} ready in her "
            f"workspace under {FOLDER}/ — posting, cover letter and a "
            f"checklist for each. I did not submit any of them; that part is "
            f"yours.")
    if failed:
        said += f" {failed} had no letter written — the folder says why."
    if result.get("skipped"):
        said += (f" {len(result['skipped'])} search result"
                 f"{'s' if len(result['skipped']) != 1 else ''} were not "
                 "actual postings and were dropped.")
    return said


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Prepare job application packets. Submits nothing.")
    ap.add_argument("role")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--where", default="")
    ap.add_argument("--resume", default="resume.md")
    args = ap.parse_args(argv)
    try:
        out = prepare(args.role, count=args.count, where=args.where,
                      resume=args.resume)
        print(spoken(out))
        print(json.dumps(out["prepared"], indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
