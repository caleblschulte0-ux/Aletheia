"""The information he should never type again.

This is the real problem, and job applications are only where it shows up
worst. Half of them hand you off to a Workday or a Greenhouse and ask for
your name, your email, your phone, your address, your work authorization
and your last three jobs — information you have typed into a hundred
forms already, and which the machine sitting next to you has known the
whole time.

So: one place that holds his answers, and everything that fills a form
reads from it. Not job-specific. The same store answers a doctor's intake
form, a DMV renewal, a warranty registration.

THREE RULES, and the last one is the one that makes it safe to point at
a live form.

**It is private and it never enters the repository.** This is his home
address and his phone number. It lives in private state alongside the
conversation thread and the demand ledger, all of which are gitignored,
and none of it is ever committed, pushed, or put in a prompt that leaves
the machine except to fill a field he is confirming.

**It learns rather than interrogates.** His resume already contains most
of it; `learn_from_resume` reads what is really there and fills nothing
it cannot find. Being asked twelve questions before she can help is the
thing being replaced, not a smaller version of it.

**A field she does not know the answer to is a QUESTION, never a guess.**
This is the whole safety model of automatic form filling. A wrong phone
number is an annoyance; a guessed "yes" on "are you authorized to work in
the United States" or "have you been convicted of a felony" is a lie
submitted under his name to an employer. `missing()` and `unknown` exist
so those come back to him instead of being invented, and there is no
setting that turns that off.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from aletheia import journal, stateio

ACTOR = "aletheia-profile"

# What a form can ask for, what it means, and how a person says it. The
# `asks` list is matched against a field's real label, name and id.
FIELDS: dict[str, dict] = {
    "legal_name":     {"asks": ("full name", "legal name", "your name", "name"),
                       "means": "his full legal name"},
    "first_name":     {"asks": ("first name", "given name", "forename"),
                       "means": "first name"},
    "last_name":      {"asks": ("last name", "surname", "family name"),
                       "means": "last name"},
    "preferred_name": {"asks": ("preferred name", "nickname", "goes by"),
                       "means": "what he likes to be called"},
    "email":          {"asks": ("email", "e-mail", "email address"),
                       "means": "email address"},
    "phone":          {"asks": ("phone", "mobile", "telephone", "cell"),
                       "means": "phone number"},
    "street":         {"asks": ("street", "address line 1", "address1",
                                "street address", "address"),
                       "means": "street address"},
    "city":           {"asks": ("city", "town", "locality"), "means": "city"},
    "state":          {"asks": ("state", "province", "region"),
                       "means": "state or province"},
    "postal_code":    {"asks": ("zip", "postal", "postcode", "zip code"),
                       "means": "postal code"},
    "country":        {"asks": ("country", "nation"), "means": "country"},
    "linkedin":       {"asks": ("linkedin",), "means": "LinkedIn URL"},
    "github":         {"asks": ("github", "git hub"), "means": "GitHub URL"},
    "website":        {"asks": ("website", "portfolio", "personal site", "url"),
                       "means": "personal site"},
    "current_title":  {"asks": ("current title", "job title", "current role",
                                "position"),
                       "means": "his current job title"},
    "current_employer": {"asks": ("current employer", "current company",
                                  "employer", "company"),
                         "means": "his current employer"},
    "years_experience": {"asks": ("years of experience", "years experience",
                                  "how many years"),
                         "means": "years of relevant experience"},
    "education":      {"asks": ("education", "degree", "school", "university",
                                "college"),
                       "means": "his education"},
    "work_authorization": {"asks": ("authorized to work", "work authorization",
                                    "legally authorized", "right to work"),
                           "means": "whether he is authorized to work",
                           "sensitive": True},
    "needs_sponsorship": {"asks": ("sponsorship", "visa", "require sponsorship"),
                          "means": "whether he needs visa sponsorship",
                          "sensitive": True},
    "willing_to_relocate": {"asks": ("relocate", "relocation", "willing to move"),
                            "means": "whether he will relocate"},
    "notice_period":  {"asks": ("notice period", "start date", "available to start",
                                "earliest start"),
                       "means": "when he could start"},
    "desired_pay":    {"asks": ("desired salary", "salary expectation",
                                "expected compensation", "pay expectation"),
                       "means": "what he wants to be paid",
                       "sensitive": True},
    "pronouns":       {"asks": ("pronouns",), "means": "his pronouns"},
}

# Never filled automatically, whatever the profile happens to contain.
# These are protected characteristics and legal declarations: an answer
# invented on his behalf is a lie in a file an employer keeps.
NEVER_AUTOFILL = ("gender", "race", "ethnicity", "veteran", "disability",
                  "felony", "convicted", "criminal", "sexual orientation",
                  "date of birth", "birth date", "social security", "ssn",
                  "salary history", "current salary", "signature", "sign here",
                  "i certify", "i agree", "terms and conditions")

MAX_VALUE_CHARS = 400


def path():
    return stateio.private_dir("profile") / "answers.json"


def load() -> dict:
    try:
        value = stateio.read_json(path())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save(answers: dict) -> dict:
    stateio.write_json_atomic(path(), answers)
    return answers


def set_answer(field: str, value, *, source: str = "operator") -> dict:
    """One answer, with where it came from. Provenance matters here: a
    thing she read off a resume is not the same as a thing he told her."""
    field = str(field or "").strip()
    if field not in FIELDS:
        raise ValueError(f"{field!r} is not a profile field; known: "
                         f"{', '.join(sorted(FIELDS))}")
    text = value if isinstance(value, bool) else str(value)[:MAX_VALUE_CHARS]
    answers = load()
    answers[field] = {"value": text, "source": str(source)[:80],
                      "at": stateio.utcnow()}
    save(answers)
    # The VALUE is his and never travels to a log. Only that it is now known.
    journal.append("note", "profile", f"{field} is on file (from {source})",
                   actor=ACTOR)
    return answers[field]


def answer(field: str):
    held = load().get(field)
    return held.get("value") if isinstance(held, dict) else None


def known() -> dict:
    return {k: v.get("value") for k, v in load().items()
            if isinstance(v, dict) and v.get("value") not in (None, "")}


def missing(fields: list[str] | None = None) -> list[dict]:
    """What she still needs, in the words a person would use."""
    have = known()
    wanted = fields if fields is not None else list(FIELDS)
    return [{"field": f, "means": FIELDS[f]["means"]}
            for f in wanted if f in FIELDS and f not in have]


def forget(field: str) -> bool:
    answers = load()
    if field not in answers:
        return False
    del answers[field]
    save(answers)
    journal.append("note", "profile", f"{field} forgotten", actor=ACTOR)
    return True


# ---- learning it instead of asking for it --------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+", re.I)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I)
_SITE = re.compile(r"https?://[\w.-]+\.[a-z]{2,}(?:/\S*)?", re.I)
_CITY_STATE = re.compile(r"\b([A-Z][a-zA-Z .'-]{2,24}),\s*([A-Z]{2})\b")


def learn_from_resume(text: str, *, source: str = "resume") -> dict:
    """Take what is really there. Fill nothing that is not.

    Being asked twelve questions before she can help is the thing being
    replaced, not a smaller version of it — and every one of these is on
    the resume already, because he put it there for a human to read.
    """
    text = str(text or "")
    found: dict[str, str] = {}
    email = _EMAIL.search(text)
    if email:
        found["email"] = email.group(0)
    phone = _PHONE.search(text)
    if phone:
        found["phone"] = " ".join(phone.group(0).split())
    for key, pattern in (("linkedin", _LINKEDIN), ("github", _GITHUB)):
        hit = pattern.search(text)
        if hit:
            found[key] = hit.group(0)
    for hit in _SITE.finditer(text):
        url = hit.group(0)
        if "linkedin.com" in url.lower() or "github.com" in url.lower():
            continue
        found.setdefault("website", url)
        break
    place = _CITY_STATE.search(text)
    if place:
        found.setdefault("city", place.group(1).strip())
        found.setdefault("state", place.group(2))
    # The name is the first line that is a name and not a heading — the
    # weakest of these guesses, so it is only taken when it is clean.
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if not line or len(line) > 48:
            continue
        if _EMAIL.search(line) or _PHONE.search(line) or "http" in line.lower():
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[:1].isupper() for w in words if w):
            found["legal_name"] = line
            parts = line.split()
            found.setdefault("first_name", parts[0])
            found.setdefault("last_name", parts[-1])
        break

    have = known()
    written = {}
    for field, value in found.items():
        if field in have:
            continue                    # what he told her outranks what she read
        set_answer(field, value, source=source)
        written[field] = value
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="The information he should never type again.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sub.add_parser("missing")
    p_set = sub.add_parser("set")
    p_set.add_argument("field")
    p_set.add_argument("value")
    p_forget = sub.add_parser("forget")
    p_forget.add_argument("field")
    p_learn = sub.add_parser("learn", help="read a resume and take what is there")
    p_learn.add_argument("path")
    args = ap.parse_args(argv)

    if args.cmd == "show":
        print(json.dumps(known(), indent=2, ensure_ascii=False))
    elif args.cmd == "missing":
        for row in missing():
            print(f"{row['field']:20} {row['means']}")
    elif args.cmd == "set":
        set_answer(args.field, args.value)
        print(f"{args.field} is on file")
    elif args.cmd == "forget":
        print("forgotten" if forget(args.field) else "was not on file")
    else:
        from aletheia import doctext
        try:
            text = doctext.extract(args.path)["text"]
        except doctext.UnreadableDocument as exc:
            print(str(exc), file=sys.stderr)
            return 1
        got = learn_from_resume(text, source=f"resume:{args.path}")
        print(f"took {len(got)} thing(s) from it: {', '.join(sorted(got)) or 'nothing'}")
        for row in missing():
            print(f"  still needs {row['field']:18} {row['means']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
