"""Everything between "apply to this job" and one confirm.

His words, and they are the whole specification: *"If all this is is, it
comes to me and it says confirm you wanna apply to this job, that's fine.
That should be the goal. It needs to be able to handle every step in
between that could ever possibly exist."*

So the shape is: she opens the application, fills in everything she can
answer, attaches his resume, takes a picture of the filled form, and
brings him ONE decision with the whole thing visible. He says yes, and it
presses submit.

WHAT MAKES THAT SAFE RATHER THAN RECKLESS — three things, and they are
not negotiable.

**She never invents an answer.** `aletheia.formfill` splits every form
into what she knows and what she does not, and the second list comes back
to him. Anything protected or legal — self-identification, felony
questions, certifications — is his even when the profile holds something
that would fit. A staged application with an unanswered REQUIRED question
is refused outright: it would be submitted incomplete, or worse, submitted
with a blank where a "no" was expected.

**What he approves is exactly what is typed.** The approval carries a
sha256 of the page and the precise step list, and `browse.interact`
re-checks that binding itself — an approval for one plan cannot be spent
on another. He sees every field and every value before deciding, plus a
screenshot of the actual filled page.

**Submitting is a separate call with a separate consumption.** The
approval is spent once. A second submit of the same application finds it
already used and refuses, because the failure mode of a retry loop here
is five copies of his application in someone's inbox.

WHAT THIS DOES NOT YET HANDLE, said plainly rather than discovered:
account creation and logins (he signs in once himself, through
`browse.login`, and the session is reused), CAPTCHAs, and multi-page
wizards — for those it reports where it stopped instead of clicking
hopefully. Each of those is its own slice.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from aletheia import browse, formfill, journal, policy, profile, stateio

ACTOR = "aletheia-apply"

MAX_QUESTIONS_SHOWN = 12
# Words on the one button that finishes an application. Matched against
# the visible text of buttons on the page, most specific first.
SUBMIT_WORDS = ("submit application", "submit your application", "apply now",
                "submit", "send application", "finish", "apply")
# The words live in `browse` now, with their refusal counterparts. Kept
# here as a name because tests and readers reach for it.
CONFIRMED_WORDS = browse.CONFIRMED_WORDS


class ApplyError(RuntimeError):
    pass


def staged_dir():
    return stateio.private_dir("applications")


def _record_path(run_id: str):
    return staged_dir() / f"{stateio.safe_id(run_id, name='application id')}.json"


def load_run(run_id: str) -> dict:
    return stateio.read_json(_record_path(run_id))


def all_runs(state: str | None = None) -> list[dict]:
    out = []
    directory = staged_dir()
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            value = stateio.read_json(path)
        except (OSError, ValueError):
            continue
        if state is None or value.get("state") == state:
            out.append(value)
    return out


def _submit_selector(buttons: list[dict]) -> str | None:
    """The one button that finishes it, by what it SAYS.

    Most specific phrase first: a page with both "Save" and "Submit
    application" must not match "apply" on a nav link first.
    """
    for word in SUBMIT_WORDS:
        for button in buttons:
            text = (button.get("text") or "").strip().casefold()
            if text == word:
                return button["selector"]
    for word in SUBMIT_WORDS:
        for button in buttons:
            if word in (button.get("text") or "").strip().casefold():
                return button["selector"]
    return None


BUTTONS_JS = r"""() => {
  const out = [];
  const sel = (el) => el.id ? `#${CSS.escape(el.id)}`
    : (el.name ? `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]` : null);
  for (const el of document.querySelectorAll(
      'button, input[type=submit], [role=button]')) {
    const selector = sel(el) || (el.type === 'submit'
      ? `${el.tagName.toLowerCase()}[type="submit"]` : null);
    if (!selector) continue;
    out.push({selector, text: (el.innerText || el.value || '').trim().slice(0, 80)});
  }
  return out;
}"""


def _tag(url: str) -> str:
    """A short, stable mark for one application, so re-staging the same form
    after he answers its questions REPLACES it rather than leaving a second
    copy waiting for the same confirmation."""
    import hashlib
    return hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:8]


def stage(url: str, *, resume: str = "", note: str = "", extra: dict | None = None,
          reader=None, filler=None) -> dict:
    """Fill the application and bring him one decision. Submits nothing.

    `extra` is his answers to the things she could not know — they are
    applied for this application and, when they name a profile field,
    remembered so he is never asked twice.
    """
    policy.ensure_not_halted()
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://", "file://")):
        raise ApplyError("that is not a page address")

    # His answers to last round's questions go in FIRST, so the plan sees
    # them. Two kinds, because the questions are of two kinds:
    #   "phone": "..."   a fact about him — remembered, never asked again
    #   "#felony": "No"  an answer to THIS form — used here and not stored
    # The second is deliberate. "Have you been convicted of a felony" is a
    # question he answers, not a fact she files away and reuses on a form
    # that may be asking something subtly different.
    per_form = {}
    for field, value in (extra or {}).items():
        if field in profile.FIELDS:
            profile.set_answer(field, value, source="operator")
        else:
            per_form[str(field)] = value

    run_id = f"apply-{_tag(url)}"
    fields = formfill.read_form(url, reader=reader)
    plan = formfill.plan(fields)
    answered = formfill.apply_answers(plan, fields, per_form)
    steps = formfill.steps(plan["fill"]) + answered["steps"]

    blocking = [a for a in plan["ask"] if a["required"]]
    if blocking:
        # Refused, not "filled as far as possible": a form submitted with a
        # blank where a "no" was expected is worse than one not submitted.
        #
        # SAVED, though, and that was the bug. The first version returned
        # this and wrote nothing, so ten applications each waiting on the
        # same three questions left no trace to collect the questions from
        # — "apply to ten jobs" asked him nothing and produced nothing. A
        # blocked application is a real thing that is waiting.
        record = {"id": run_id, "state": "NEEDS_YOU", "url": url,
                  "approval": "", "steps": [], "resume": resume,
                  "questions": plan["ask"][:MAX_QUESTIONS_SHOWN],
                  "not_filled": plan["ask"][:MAX_QUESTIONS_SHOWN],
                  "would_fill": [{"label": f["label"], "value": f["value"]}
                                 for f in plan["fill"]],
                  "filled": [], "skipped": plan["skipped"],
                  "staged_at": stateio.utcnow(),
                  "say": (f"{len(blocking)} thing(s) on that form only you can "
                          "answer. Tell me those and I will fill the rest and "
                          "bring it back to you to confirm.")}
        stateio.write_json_atomic(_record_path(run_id), record)
        return record

    shot = staged_dir() / f"{run_id}.png"
    filled = (filler or _fill_and_capture)(url, steps, resume, shot)

    # THE PAGE'S OWN VERDICT, not hers. Staging ended at "I typed
    # everything I could" and called that ready — so on a form whose
    # work-authorization question is a pair of divs, she produced an
    # application AWAITING HIS CONFIRMATION that the browser would then
    # refuse to send: he taps Approve, submit is pressed, nothing arrives,
    # and the run reports success. Found on a fixture built to look like
    # the forms an ATS actually serves.
    stopped = [item for item in (filled.get("blocking") or [])
               if item.get("label") not in {q.get("label") for q in plan["ask"]}]
    if stopped:
        record = {"id": run_id, "state": "NEEDS_YOU", "url": url,
                  "approval": "", "steps": steps, "resume": resume,
                  "questions": (plan["ask"] + stopped)[:MAX_QUESTIONS_SHOWN],
                  "not_filled": (plan["ask"] + stopped)[:MAX_QUESTIONS_SHOWN],
                  "would_fill": [{"label": f["label"], "value": f["value"]}
                                 for f in plan["fill"]],
                  "filled": [], "skipped": plan["skipped"],
                  "screenshot": str(shot) if shot.exists() else "",
                  "staged_at": stateio.utcnow(),
                  "say": ("I filled what I could, and the form still will not "
                          "go without: "
                          + "; ".join(i["label"] for i in stopped[:5])
                          + ". Tell me those and I will finish it.")}
        stateio.write_json_atomic(_record_path(run_id), record)
        journal.append("action", "apply",
                       f"held an application at {url} — the form will not go "
                       f"yet ({len(stopped)} thing(s) outstanding)", actor=ACTOR)
        try:
            from aletheia import demand
            demand.record_attempt("application.submit", note or url,
                                  "NEEDS_YOU", source="apply")
        except Exception:
            pass
        return record

    action = browse.approval_action(url, steps)
    approval_id = f"{run_id}-submit"
    policy.request(
        approval_id, action,
        reason=(note or f"Submit an application at {url}"),
        consequence=("It sends your application to this employer under your "
                     "name. There is no undo."),
        reversible=False, capability="application.submit")

    record = {"id": run_id, "state": "AWAITING_YOU", "url": url,
              "approval": approval_id, "steps": steps,
              "filled": ([{"label": f["label"], "value": f["value"]}
                          for f in plan["fill"]] + answered["filled"]),
              "not_filled": plan["ask"], "skipped": plan["skipped"],
              "resume": resume, "screenshot": str(shot) if shot.exists() else "",
              "page_title": filled.get("title", ""),
              "staged_at": stateio.utcnow()}
    stateio.write_json_atomic(_record_path(run_id), record)
    journal.append("action", "apply",
                   f"staged an application at {url} — {len(steps)} field(s) "
                   f"filled, awaiting his confirmation", actor=ACTOR)
    return record


def _apply_steps(page, steps: list[dict]) -> None:
    """One place that knows how to perform a step.

    Staging and submitting both type the same list, and they had their own
    copies of the loop — which is how two things that must be identical
    stop being identical. It also cost the first live run: a checkbox step
    carries no `value`, and `page.fill(selector, step["value"])` raised
    KeyError in the staging copy alone.
    """
    for step in steps:
        action = step["action"]
        if action == "select":
            page.select_option(step["selector"], step["value"])
        elif action == "click":
            page.click(step["selector"])       # a checkbox is ticked, not typed
        elif action == "press":
            page.keyboard.press(str(step["value"]))
        elif action == "wait_for":
            page.wait_for_selector(step["selector"])
        else:
            page.fill(step["selector"], str(step["value"]))


def _fill_and_capture(url: str, steps: list[dict], resume: str, shot: Path) -> dict:
    """Type it all in, photograph it, and say what would still stop it.

    Presses nothing — and, since 2026-09-04, does not pretend a form is
    ready when it is not: `formfill.blocking` asks the page itself.
    """
    ok, why = browse.available()
    if not ok:
        raise ApplyError(f"she cannot open the application: {why}")
    shot.parent.mkdir(parents=True, exist_ok=True)
    with browse._Session() as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        formfill.settle(page)
        _apply_steps(page, steps)
        if resume:
            _attach_resume(page, resume)
        page.screenshot(path=str(shot), full_page=True)
        result = {"title": page.title(), "url": page.url,
                  "blocking": formfill.blocking(page)}
        page.close()
    return result


def _attach_resume(page, resume: str) -> bool:
    """Put his real resume in the upload box.

    This was on the "yours to do" list a commit ago, and it did not need
    to be: a file input takes a path, and the path is a file he already
    owns. It is still his document going to an employer, which is why it
    happens inside the same approval as everything else.
    """
    path = Path(resume).expanduser()
    if not path.is_file():
        return False
    for row in page.evaluate(formfill.READ_FORM_JS):
        if row.get("type") != "file":
            continue
        hay = " ".join(str(row.get(k, "")) for k in ("label", "name", "id")).lower()
        if any(word in hay for word in ("resume", "cv", "curriculum")):
            page.set_input_files(row["selector"], str(path))
            return True
    return False


def accept(run_id: str) -> dict:
    """Move a run to APPROVED because its approval ALREADY says so.

    Split out from `confirm` after the beat got it exactly backwards: it
    called `confirm`, which calls `policy.decide(APPROVED)` — so a run he
    had never looked at got approved BY THE THING CHECKING WHETHER HE HAD
    APPROVED IT, and one he genuinely had approved raised "already
    decided" and was reported to him as a failure. Granting and reading a
    grant are different verbs and now they are different functions.
    """
    record = load_run(run_id)
    ok, why = policy.usable(record["approval"])
    if not ok:
        raise ApplyError(why)
    record["state"] = "APPROVED"
    record["confirmed_at"] = stateio.utcnow()
    stateio.write_json_atomic(_record_path(run_id), record)
    return record


def confirm(run_id: str, *, via: str = "operator", because: str = "") -> dict:
    """He said yes here, at a keyboard. Grants the approval, sends nothing."""
    record = load_run(run_id)
    policy.decide(record["approval"], "APPROVED", via=via, because=because)
    return accept(run_id)


def submit(run_id: str, *, submitter=None) -> dict:
    """Press it. Once.

    The approval is spent here and the record moves to SUBMITTED before
    anything else can look at it, because the failure mode of a retry loop
    on this particular button is five copies of his application in
    somebody's inbox.
    """
    policy.ensure_not_halted()
    record = load_run(run_id)
    if record["state"] == "SUBMITTED":
        raise ApplyError(f"{run_id} was already submitted at "
                         f"{record.get('submitted_at')} — not sending it again")
    if record["state"] != "APPROVED":
        raise ApplyError(f"{run_id} is {record['state']}; it needs your "
                         "confirmation before anything is sent")
    ok, why = policy.usable(record["approval"])
    if not ok:
        raise ApplyError(f"{why} — nothing was sent")

    record["state"] = "SUBMITTING"
    record["submitted_at"] = stateio.utcnow()
    stateio.write_json_atomic(_record_path(record["id"]), record)

    try:
        outcome = (submitter or _refill_and_submit)(record)
    except Exception as exc:
        record["state"] = "FAILED"
        record["failure"] = f"{type(exc).__name__}: {exc}"[:300]
        stateio.write_json_atomic(_record_path(record["id"]), record)
        journal.append("alert", "apply",
                       f"{record['id']} failed to submit: {record['failure']}",
                       actor=ACTOR)
        raise

    record.update({"state": "SUBMITTED", "result": outcome})
    stateio.write_json_atomic(_record_path(record["id"]), record)
    journal.append("action", "apply",
                   f"submitted {record['id']} to {record['url']} — "
                   f"{outcome.get('verdict')}", actor=ACTOR)
    return record


def _refill_and_submit(record: dict) -> dict:
    """Re-open, re-fill exactly the approved steps, press the button.

    Re-filling rather than holding a page open for however long he takes
    to decide: a browser page waiting on a human is a resource the Core
    cannot promise, and the Core restarts itself on every code update. The
    approval is bound to the step list, so what is typed the second time is
    identical to what he saw.
    """
    ok, why = browse.available()
    if not ok:
        raise ApplyError(f"she cannot reopen the application: {why}")
    shot = staged_dir() / f"{record['id']}-submitted.png"
    with browse._Session() as ctx:
        page = ctx.new_page()
        page.goto(record["url"], wait_until="domcontentloaded")
        formfill.settle(page)
        _apply_steps(page, record["steps"])
        if record.get("resume"):
            _attach_resume(page, record["resume"])
        button = _submit_selector(page.evaluate(BUTTONS_JS))
        if button is None:
            raise ApplyError(
                "she could not find the button that submits this form — "
                "nothing was pressed. It may be a multi-step application, "
                "which she does not drive yet.")
        page.click(button)
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_timeout(1500)     # let a confirmation render
        except Exception:
            pass
        body = (page.inner_text("body") or "")[:4000]
        page.screenshot(path=str(shot), full_page=True)
        landed = page.url
        title = page.title()
        page.close()
    # Never "done" without something that says so. A click that produced
    # no confirmation is a click, not an application — and a page that
    # handed the form back is a REFUSAL, which used to read the same as
    # silence. `browse.read_outcome` is the one place that knows the
    # difference, so this and the general web loop cannot drift on it.
    return {"url": landed, "title": title,
            "evidence": body[:600], "screenshot": str(shot),
            **browse.read_outcome(body, did=record.get("button", "submit"))}


def spoken(record: dict) -> str:
    if record.get("state") == "NEEDS_YOU":
        return record["say"]
    if record.get("state") == "AWAITING_YOU":
        left = len(record.get("not_filled") or [])
        return (f"Application ready at {record['url']}: "
                f"{len(record['filled'])} field(s) filled"
                + (f", {left} left blank that you may want to look at" if left else "")
                + ". Say confirm to send it, or look at the screenshot first.")
    if record.get("state") == "SUBMITTED":
        return f"Sent. {record.get('result', {}).get('note', '')}"
    return f"{record.get('id')} is {record.get('state')}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apply, with one confirmation.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_stage = sub.add_parser("stage")
    p_stage.add_argument("url")
    p_stage.add_argument("--resume", default="")
    p_stage.add_argument("--answer", action="append", default=[],
                         metavar="FIELD=VALUE")
    sub.add_parser("pending")
    p_ok = sub.add_parser("confirm"); p_ok.add_argument("run_id")
    p_send = sub.add_parser("submit"); p_send.add_argument("run_id")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "stage":
            extra = dict(a.split("=", 1) for a in args.answer if "=" in a)
            record = stage(args.url, resume=args.resume, extra=extra)
            print(spoken(record))
            print(json.dumps(record.get("filled") or record.get("would_fill"),
                             indent=2, ensure_ascii=False))
            for q in record.get("questions") or record.get("not_filled") or []:
                print(f"  {'*' if q['required'] else ' '} {q['label']}: {q['why']}")
        elif args.cmd == "pending":
            for record in all_runs("AWAITING_YOU"):
                print(f"{record['id']}  {record['url']}")
        elif args.cmd == "confirm":
            print(spoken(confirm(args.run_id)))
        else:
            print(spoken(submit(args.run_id)))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
