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
# Enough of a resume to write a specific letter from. Below this she is
# guessing about him, which is the thing this whole module refuses to do.
MIN_RESUME_CHARS = 300
MAX_POSTING_CHARS = 8_000
FOLDER = "applications"

# A page has to look like a posting rather than a listing index or a blog
# post about hiring. Cheap and honest: it filters, the operator decides.
HIRING_WORDS = ("responsibilities", "qualifications", "requirements",
                "what you'll do", "what you will do", "about the role",
                "apply", "we're looking for", "we are looking for",
                "experience with", "benefits")

# Where a person's resume actually lives, in the order she should look. He
# should not have to know a path to use his own document.
RESUME_NAMES = ("resume", "cv", "curriculum-vitae", "curriculum_vitae")
RESUME_SUFFIXES = (".pdf", ".docx", ".md", ".txt", ".rtf")
# OneDrive is in here because on a normal Windows setup Desktop and
# Documents ARE the OneDrive ones — `~/Desktop` does not exist at all.
RESUME_PLACES = ("", "Documents", "Downloads", "Desktop", "Documents/Aletheia",
                 "OneDrive/Documents", "OneDrive/Downloads", "OneDrive/Desktop",
                 "OneDrive - Personal/Documents", "OneDrive/Documents/Aletheia")


def looks_like_a_resume(name: str) -> bool:
    """Nobody names it `resume.pdf`.

    His is "Caleb Schulte Resume.pdf" and the exact-name search walked
    right past it, then said she had looked in Downloads — true, and
    useless. Matched on WORDS so that "cv" does not catch every file with
    those two letters in it.
    """
    stem, _, suffix = name.rpartition(".")
    if not stem or f".{suffix.casefold()}" not in RESUME_SUFFIXES:
        return False
    words = [w for w in re.split(r"[^a-z0-9]+", stem.casefold()) if w]
    return bool({"resume", "resumé", "cv"} & set(words)) or "curriculum" in words


def find_resume(named: str = "") -> str:
    """His resume, wherever it is. Returns a path, or raises with the fix.

    `resume="resume.md"` was the default and it was a fiction: the only
    reason that file existed was that a test wrote one. His actual resume
    is a PDF in Downloads, which nothing in this system could open until
    today, and which he should not have to type the path of.
    """
    from pathlib import Path as _Path
    if named:
        for candidate in (workspace.root() / named, _Path(named).expanduser()):
            if candidate.is_file():
                return str(candidate)
        raise ApplicationError(
            f"she could not find {named}. Put it in her workspace "
            f"({workspace.root()}) or give the full path.")
    seen = []
    for place in RESUME_PLACES:
        for stem in RESUME_NAMES:
            for suffix in RESUME_SUFFIXES:
                for base in (workspace.root(), _Path.home()):
                    candidate = (base / place / f"{stem}{suffix}"
                                 if place else base / f"{stem}{suffix}")
                    seen.append(candidate)
                    if candidate.is_file():
                        return str(candidate)
    # Then by what it LOOKS like: newest first, because the one he last
    # touched is the one he means.
    found = []
    for place in RESUME_PLACES:
        for base in (workspace.root(), _Path.home()):
            folder = base / place if place else base
            try:
                entries = list(folder.iterdir())
            except Exception:
                continue
            for entry in entries:
                if entry.is_file() and looks_like_a_resume(entry.name):
                    try:
                        found.append((entry.stat().st_mtime, str(entry)))
                    except Exception:
                        continue
    if found:
        return max(found)[1]
    raise ApplicationError(
        "she could not find your resume. She looked for anything with "
        "'resume' or 'cv' in its name as .pdf, "
        ".docx, .md, .txt or .rtf in her workspace, your home folder, "
        "Documents, Downloads, Desktop and their OneDrive twins. Say "
        "`apply ... --resume <path>` or drop a "
        "copy in " + str(workspace.root()) + ".")


LETTER = (
    "Write a cover letter for the job posting below, from the person whose "
    "resume is also below. EVERY concrete claim must come from that resume: "
    "name two or three specific things he has really built or done, in his "
    "own numbers and nouns, and connect each one to something this posting "
    "actually asks for. No skill he does not list. No 'passionate about', no "
    "'I am writing to express my interest', no flattery. Four short "
    "paragraphs at most. If the posting does not say what the job is, or the "
    "resume has nothing to do with it, say CANNOT WRITE and why, rather than "
    "writing something that would fit anybody."
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


def prepare(role: str, *, count: int = 5, resume: str = "",
            where: str = "", finder=None, reader=None, writer=None) -> dict:
    """Find real postings, write a packet for each. Submits nothing."""
    role = " ".join(str(role or "").split())
    if not role:
        raise ValueError("say what kind of role")
    count = max(1, min(int(count), MAX_APPLICATIONS))
    policy.ensure_not_halted()

    # THE RESUME IS REQUIRED, AND PROVED BEFORE ANYTHING ELSE HAPPENS.
    #
    # It used to be one of two sources handed to `compose`, and compose
    # proceeds when SOME sources read — correctly, for its own purposes. So
    # an unreadable resume produced ten cover letters written from the job
    # postings alone: fluent, plausible, about nobody. "Tailored to your
    # resume" would have been a lie in every one of them, and the only way
    # to notice was to read all ten.
    resume_path = find_resume(resume)
    try:
        proof = workspace.read(resume_path, anywhere=True)
    except Exception as exc:
        raise ApplicationError(
            f"she could not read your resume ({resume_path}): {exc} Nothing "
            "was written — a cover letter with no resume behind it is not a "
            "tailored letter, it is a form letter with your name on it.")
    if len(proof.get("text", "")) < MIN_RESUME_CHARS:
        raise ApplicationError(
            f"she got only {len(proof.get('text', ''))} characters out of "
            f"{resume_path}, which is not enough to write from. Nothing was "
            "written.")

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
                sources=[resume_path, posting_path],
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
    return {"role": role, "resume": resume_path,
            "prepared": packets, "skipped": skipped,
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
    ap.add_argument("--resume", default="",
                    help="path to your resume; found automatically if omitted")
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
