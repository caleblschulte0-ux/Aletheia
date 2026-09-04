"""Ten jobs, one sentence, one confirmation each.

*"If I say apply to ten jobs with this resume I provided you, I need to
be able to do that."*

Every piece of that existed and none of them were joined. `applications`
found postings and wrote packets it then handed back. `apply_run` filled
ONE form at ONE url he had to supply himself. `profile` knew him but
nothing taught it from the resume he actually named. Three good halves
are not a thing that works.

This is the join, and it is the whole request in one call:

  1. Read the resume HE NAMED and learn him from it — he never types his
     own phone number to apply to a job.
  2. Find real openings and read them.
  3. For each, find the page that actually takes the application. A
     posting is not a form: it is a description with an "Apply" link, and
     following that link is a step nobody was doing.
  4. Fill every form as far as it will go, attach the resume, photograph
     each one, and hold it.
  5. Ask him — ONCE for all ten — the questions only he can answer.
  6. Bring back one confirmation per job.

STEP 5 IS THE ONE THAT MAKES THIS USABLE RATHER THAN TEDIOUS. Ten
applications ask the same three or four unanswerable things: are you
authorized to work, do you need sponsorship, have you been convicted of a
felony, do you certify this is true. Asking him thirty times is not
automation, it is a worse form. They are gathered, deduplicated by what
they are actually asking, answered once, and applied to every application
that asked.

NOTHING IS SENT HERE. Each application ends as a staged run with its own
approval, bound to its own page and its own filled values, and the
existing Approve button on his phone is the confirm. That is the line he
drew himself and it is the right one: ten applications is ten real
messages to ten real employers under his name.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.parse import urljoin

from aletheia import (applications, apply_run, browse, doctext, formfill,
                      journal, jobs, policy, profile, workspace)

ACTOR = "aletheia-campaign"

MAX_JOBS = 10
CANDIDATE_FACTOR = 3

# The link on a posting that leads to the form. Ordered: an exact "apply
# for this job" beats a nav item that merely says "apply".
APPLY_WORDS = ("apply for this job", "apply now", "apply to this job",
               "apply here", "submit application", "start application",
               "apply")

APPLY_LINKS_JS = r"""() => Array.from(document.querySelectorAll('a[href]'))
  .map(a => ({href: a.href, text: (a.innerText || '').trim().slice(0, 80)}))
  .filter(a => a.href && !a.href.startsWith('javascript:'))
  .slice(0, 200)"""


class CampaignError(RuntimeError):
    pass


def _application_url(url: str, opener=None) -> tuple[str, list[dict]]:
    """The page that actually takes the application, and its fields.

    A posting is a description with an Apply link on it. Nothing was
    following that link, so "apply to ten jobs" met ten pages with no form
    on them and gave up on all ten.
    """
    open_page = opener or _open
    fields, links = open_page(url)
    if _is_application_form(fields):
        return url, fields
    for word in APPLY_WORDS:
        for link in links:
            if word in (link.get("text") or "").casefold():
                target = urljoin(url, link["href"])
                if target.rstrip("/") == url.rstrip("/"):
                    continue
                fields, _ = open_page(target)
                if _is_application_form(fields):
                    return target, fields
                break
    return "", []


def _is_application_form(fields: list[dict]) -> bool:
    """A search box is not an application. Two typed fields and a name or
    an email is the cheapest honest test."""
    usable = [f for f in fields
              if f.get("type") not in ("hidden", "submit", "button", "search")]
    if len(usable) < 3:
        return False
    hay = " ".join(_haystack(f) for f in usable)
    return ("email" in hay or "name" in hay) and "resume" in hay or len(usable) >= 6


def _haystack(field: dict) -> str:
    return " ".join(str(field.get(k, "") or "")
                    for k in ("label", "name", "id")).casefold()


def _open(url: str) -> tuple[list[dict], list[dict]]:
    ok, why = browse.available()
    if not ok:
        raise CampaignError(f"she cannot open job pages: {why}")
    with browse._Session() as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        fields = page.evaluate(formfill.READ_FORM_JS)
        links = page.evaluate(APPLY_LINKS_JS)
        page.close()
    return fields, links


def _question_key(question: dict) -> str:
    """What a question is ACTUALLY asking, so ten forms asking it become one.

    Keyed on the words of the label rather than its selector: `#felony` on
    one site and `#q_88213` on another are the same question, and he
    should answer it once.
    """
    words = re.sub(r"[^a-z0-9 ]", " ", (question.get("label") or "").casefold())
    return " ".join(sorted(set(words.split())))[:120]


def open_questions() -> list[dict]:
    """Everything waiting on him, across every staged application, once."""
    seen: dict[str, dict] = {}
    for record in apply_run.all_runs("NEEDS_YOU") + apply_run.all_runs("AWAITING_YOU"):
        for question in record.get("questions") or record.get("not_filled") or []:
            key = _question_key(question)
            held = seen.setdefault(key, {"label": question["label"],
                                         "why": question["why"],
                                         "required": question["required"],
                                         "selectors": {}, "jobs": []})
            held["selectors"][record["id"]] = question["selector"]
            held["required"] = held["required"] or question["required"]
            if record["url"] not in held["jobs"]:
                held["jobs"].append(record["url"])
    return sorted(seen.values(), key=lambda q: (not q["required"], q["label"]))


def run(role: str, *, count: int = 5, resume: str = "", where: str = "",
        finder=None, reader=None, opener=None, stager=None, writer=None,
        draft_essays_too: bool = True) -> dict:
    """Apply to `count` jobs with `resume`. Stages them all; sends nothing."""
    policy.ensure_not_halted()
    role = " ".join(str(role or "").split())
    if not role:
        raise ValueError("say what kind of role")
    count = max(1, min(int(count), MAX_JOBS))

    # 1. The resume he named — read, and LEARNED from, so he never types
    #    his own phone number to apply for a job.
    resume_path = applications.find_resume(resume)
    try:
        text = workspace.read(resume_path, anywhere=True)["text"]
    except Exception as exc:
        raise CampaignError(f"she could not read {resume_path}: {exc}")
    learned = profile.learn_from_resume(text, source=f"resume:{resume_path}")

    # 2. REAL openings, from the systems that publish them.
    #
    # This used to go through `research.find_sources`, which drives a
    # headless browser at a search engine — and a search engine answers a
    # headless browser with a challenge page. On the real internet it
    # returned ZERO jobs, so everything downstream of it was theatre. That
    # is the difference between a demo and a thing that works.
    #
    # `aletheia.jobs` reads Greenhouse and Lever, which publish their
    # boards as public JSON and host the real application form at a public
    # URL with no login. A posting she can find but not apply to is a link
    # he could have found himself.
    if finder is None:
        hits = jobs.search(role, where=where, limit=count * 2)
        pages = [{"url": j["apply_url"], "title": f"{j['title']} — {j['company']}",
                  "posting": j.get("posting_url") or j["apply_url"],
                  "direct": True} for j in hits["matches"]]
        if not pages:
            raise CampaignError(
                f"no openings matched {role!r} across {hits['searched']} "
                "board(s). Try different words, or add companies to "
                "config/job_boards.json.")
    else:
        reader = reader or applications.research.read_sources
        candidates = finder(f"{role} job openings{(' ' + where) if where else ''}",
                            limit=count * CANDIDATE_FACTOR)
        if not candidates:
            raise CampaignError(f"no openings found for {role!r}")
        found, _unreadable = reader(candidates[:count * CANDIDATE_FACTOR])
        pages = [{"url": p["url"], "title": p.get("title", ""),
                  "posting": p["url"], "direct": False} for p in found]

    staged, needs_you, failed = [], [], []
    for page in pages:
        if len(staged) + len(needs_you) >= count:
            break
        if page.get("direct"):
            # An ATS apply link IS the form; there is no posting page to
            # walk through, and pretending otherwise costs a page load per
            # job for nothing.
            form_url = page["url"]
        else:
            try:
                form_url, _fields = _application_url(page["url"], opener=opener)
            except Exception as exc:
                failed.append({"url": page["url"],
                               "why": f"{type(exc).__name__}: {exc}"[:160]})
                continue
        if not form_url:
            failed.append({"url": page["url"],
                           "why": "no application form found on it"})
            continue
        try:
            record = (stager or apply_run.stage)(
                form_url, resume=resume_path,
                note=f"Apply: {page.get('title') or role} — {page.get('posting') or page['url']}")
        except Exception as exc:
            failed.append({"url": form_url,
                           "why": f"{type(exc).__name__}: {exc}"[:160]})
            continue
        record["job_title"] = page.get("title", "")
        record["posting"] = page.get("posting") or page["url"]
        # Long-answer questions are written, not handed back. Every draft
        # shows up in the confirmation, so nothing goes out unread.
        if record["state"] == "NEEDS_YOU" and draft_essays_too:
            drafts = draft_essays(record, text, think=writer)
            if drafts:
                try:
                    record = (stager or apply_run.stage)(
                        form_url, resume=resume_path, extra=drafts,
                        note=f"Apply: {page.get('title') or role}")
                    record["job_title"] = page.get("title", "")
                    record["posting"] = page.get("posting") or page["url"]
                    record["drafted"] = len(drafts)
                except Exception:
                    pass
        (needs_you if record["state"] == "NEEDS_YOU" else staged).append(record)

    journal.append("action", "campaign",
                   f"{len(staged)} ready, {len(needs_you)} waiting on answers, "
                   f"{len(failed)} could not be reached — for {role!r}; "
                   "nothing submitted", actor=ACTOR)
    return {"role": role, "resume": resume_path, "learned": sorted(learned),
            "ready": staged, "blocked": needs_you, "failed": failed,
            "questions": open_questions(),
            "submitted": 0}


ESSAY_BRIEF = (
    "Answer this question on a job application, in the applicant's own "
    "voice, using ONLY what his resume below actually says. Two to four "
    "sentences, concrete, no filler, no 'I am passionate about'. Name real "
    "things he built. If his resume does not support an answer, reply with "
    "exactly CANNOT WRITE and nothing else — a made-up answer on a job "
    "application is worse than a blank one.\n\nTHE JOB: {job}\n\n"
    "THE QUESTION: {question}")

MAX_DRAFTS_PER_JOB = 4


def draft_essays(record: dict, resume_text: str, *, think=None) -> dict:
    """Write the long-answer questions instead of handing them back.

    "Briefly describe your experience with conversion modeling" is not a
    fact she can look up and it is not a thing he should type ten times.
    It is a question his resume already answers, so she answers it — and
    every draft is visible in the confirmation, because a drafted answer he
    has not read is exactly the thing this whole system refuses to send.

    CANNOT WRITE is a real outcome. A question his resume does not support
    comes back to him blank rather than filled with something plausible.
    """
    from aletheia import reasoner
    think = think or reasoner.subscription_text
    drafted = {}
    for question in record.get("questions") or []:
        if len(drafted) >= MAX_DRAFTS_PER_JOB:
            break
        if question.get("type") != "textarea" or question.get("choices"):
            continue
        prompt = ESSAY_BRIEF.format(job=record.get("job_title") or record["url"],
                                    question=question["label"])
        try:
            said = think(prompt, resume_text[:8000], timeout_s=120.0)
            if isinstance(said, tuple):
                said = said[0]
        except Exception:
            continue
        body = str(said or "").strip()
        if not body or body.upper().startswith("CANNOT WRITE"):
            continue
        drafted[question["selector"]] = body[:2000]
    return drafted


def answer_all(answers: dict, *, resume: str = "", stager=None) -> dict:
    """His answers, applied to every application that asked.

    Keyed by the QUESTION as he was shown it, not by a selector, so one
    "No" covers the felony question on all ten sites.
    """
    questions = {q["label"]: q for q in open_questions()}
    facts = {k: v for k, v in answers.items() if k in profile.FIELDS}
    for field, value in facts.items():
        profile.set_answer(field, value, source="operator")

    per_run: dict[str, dict] = {}
    unmatched = []
    for label, value in answers.items():
        if label in facts:
            continue
        question = questions.get(label)
        if question is None:
            unmatched.append(label)
            continue
        for run_id, selector in question["selectors"].items():
            per_run.setdefault(run_id, {})[selector] = value

    restaged, still_blocked = [], []
    for record in list(apply_run.all_runs("NEEDS_YOU")):
        extra = dict(facts)
        extra.update(per_run.get(record["id"], {}))
        try:
            fresh = (stager or apply_run.stage)(
                record["url"], resume=resume or record.get("resume", ""),
                extra=extra)
        except Exception:
            still_blocked.append(record)
            continue
        (still_blocked if fresh["state"] == "NEEDS_YOU" else restaged).append(fresh)
    return {"ready": restaged, "blocked": still_blocked,
            "unmatched": unmatched, "questions": open_questions()}


def spoken(out: dict) -> str:
    ready, blocked, failed = (len(out.get("ready", [])), len(out.get("blocked", [])),
                              len(out.get("failed", [])))
    said = []
    if ready:
        said.append(f"{ready} application{'s' if ready != 1 else ''} filled in and "
                    "waiting for you to confirm")
    if blocked:
        questions = out.get("questions") or []
        said.append(f"{blocked} more that need {len(questions)} answer"
                    f"{'s' if len(questions) != 1 else ''} from you first")
    if failed:
        said.append(f"{failed} I could not reach a form on")
    if not said:
        return "Nothing to apply to — no openings had a form she could read."
    return ". ".join(said) + ". Nothing has been sent."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apply to N jobs with one resume.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("role")
    p_run.add_argument("--count", type=int, default=5)
    p_run.add_argument("--resume", default="")
    p_run.add_argument("--where", default="")
    sub.add_parser("questions")
    p_ans = sub.add_parser("answer")
    p_ans.add_argument("pairs", nargs="+", metavar="QUESTION=ANSWER")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "run":
            out = run(args.role, count=args.count, resume=args.resume,
                      where=args.where)
            print(spoken(out))
            for q in out["questions"]:
                print(f"  {'*' if q['required'] else ' '} {q['label']}  "
                      f"({len(q['jobs'])} job(s))")
        elif args.cmd == "questions":
            for q in open_questions():
                print(f"{'*' if q['required'] else ' '} {q['label']}  "
                      f"({len(q['jobs'])} job(s))")
        else:
            answers = dict(p.split("=", 1) for p in args.pairs if "=" in p)
            out = answer_all(answers)
            print(spoken(out))
            for label in out["unmatched"]:
                print(f"  (no question matched {label!r})", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
