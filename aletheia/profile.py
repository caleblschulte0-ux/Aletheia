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
    "current_title":  {"asks": ("current or previous job title",
                                "current title", "job title", "current role",
                                "position", "your title"),
                       "means": "his current job title"},
    "current_employer": {"asks": ("current or previous employer",
                                  "current employer", "previous employer",
                                  "current company", "employer", "company"),
                         "means": "his current employer"},
    "years_experience": {"asks": ("years of experience", "years experience",
                                  "how many years"),
                         "means": "years of relevant experience"},
    "school":         {"asks": ("most recent school", "school you attended",
                                "school", "university", "college",
                                "institution", "alma mater"),
                       "means": "the school he went to"},
    "degree":         {"asks": ("most recent degree", "degree you obtained",
                                "degree", "highest level of education",
                                "education level"),
                       "means": "his degree"},
    "field_of_study": {"asks": ("field of study", "major", "discipline",
                                "course of study"),
                       "means": "what he studied"},
    "graduation_year": {"asks": ("graduation year", "year of graduation",
                                 "year graduated", "end date of education"),
                        "means": "the year he finished"},
    "education":      {"asks": ("education",), "means": "his education"},
    # "Your authorization to work in the country where you live" (Vercel,
    # live 2026-09-12) contains none of the older phrases as written - it
    # says "authorization to work", not "authorized to work" - so after the
    # guard stopped `country` claiming it, nothing matched it at all. A
    # wrong answer became no answer, which is better and still not right.
    "work_authorization": {"asks": ("authorized to work", "work authorization",
                                    "authorization to work", "authorisation to work",
                                    "legally authorized", "legally authorised",
                                    "right to work", "eligible to work",
                                    "legally able to work", "work eligibility"),
                           "means": "whether he is authorized to work",
                           "sensitive": True},
    "needs_sponsorship": {"asks": ("sponsorship", "visa", "require sponsorship",
                                    "sponsor you", "sponsor", "work permit",
                                    "immigration"),
                          "means": "whether he needs visa sponsorship",
                          "sensitive": True},
    "willing_to_relocate": {"asks": ("relocate", "relocation", "willing to move",
                                     "open to relocation"),
                            "means": "whether he will relocate"},
    "notice_period":  {"asks": ("notice period", "start date", "available to start",
                                "earliest start"),
                       "means": "when he could start"},
    "desired_pay":    {"asks": ("desired salary", "salary expectation",
                                "expected compensation", "pay expectation"),
                       "means": "what he wants to be paid",
                       "sensitive": True},
    "pronouns":       {"asks": ("pronouns",), "means": "his pronouns"},
    "heard_about":    {"asks": ("how did you hear", "where did you hear",
                                "how did you find", "referral source",
                                "hear about this"),
                       "means": "how he heard about the job"},
    "twitter":        {"asks": ("twitter", "x profile", "x.com"),
                       "means": "his Twitter"},
    # Protected characteristics. Filled ONLY from what he said himself
    # (formfill.declared_choice): never from a resume, a page or a model.
    # 2026-09-11: "the gender, I'm a man. The race, I'm a white, non Hispanic."
    "gender":         {"asks": ("gender", "gender identity", "sex"),
                       "means": "his gender, as he stated it",
                       "sensitive": True, "declared": True},
    "race":           {"asks": ("race", "racial", "race/ethnicity"),
                       "means": "his race, as he stated it",
                       "sensitive": True, "declared": True},
    "hispanic_latino": {"asks": ("hispanic", "latino", "latina", "latinx", "latine"),
                        "means": "whether he is Hispanic or Latino, as he stated it",
                        "sensitive": True, "declared": True},
    # 2026-09-12. Thirteen real applications stalled at once, twelve of them
    # on these two questions - and he had already answered both, out loud:
    # "Veteran status. I am not a protected veteran. Disability status. I
    # have no disabilities." There was nowhere to keep that, so every form
    # asked him again. The rule these fields protect is "never GUESSED",
    # not "never stored": still only his own words, never a resume, never a
    # page, never a model.
    "veteran_status": {"asks": ("veteran", "protected veteran", "military service",
                                "armed forces"),
                       "means": "his veteran status, as he stated it",
                       "sensitive": True, "declared": True},
    "disability_status": {"asks": ("disability", "disabilities", "disabled",
                                   "chronic condition"),
                          "means": "his disability status, as he stated it",
                          "sensitive": True, "declared": True},
    # "Sexual orientation. I don't think they can ask that. If they do, but
    # I'm not answering." Declining IS his answer, and every one of these
    # forms offers it as an option.
    "self_id_decline": {"asks": ("sexual orientation", "orientation",
                                 "transgender", "gender identity survey"),
                        "means": "that he declines to answer self-identification",
                        "sensitive": True, "declared": True},
}

# Never filled automatically, whatever the profile happens to contain.
# These are protected characteristics and legal declarations: an answer
# invented on his behalf is a lie in a file an employer keeps.
NEVER_AUTOFILL = ("gender", "race", "ethnicity", "veteran", "disability",
                  "felony", "convicted", "criminal", "sexual orientation",
                  "date of birth", "birth date", "social security", "ssn",
                  "salary history", "current salary", "signature", "sign here",
                  "i certify", "i agree", "terms and conditions",
                  )
# An AI POLICY box is not in that list any more, and the reason is his.
# 2026-09-12, first ruling: "the only thing that I wouldn't want you to ever
# auto click on is something like, hey. You'll go to jail if you use AI on
# this." Then, once he saw the boxes actually say "AI Policy for
# Application" with Yes/No: *"if yes is an answer, just hit yes. Like, why
# lie? Yes. We helped you, the AI, to do this."*
#
# Both rulings are the same rule underneath - never put a false statement on
# a form in his name - and they point opposite ways only because the first
# assumed the box asserts AI was NOT used. Where it does assert that,
# `formfill._NEVER_TICK` still refuses it. Where it asks him to acknowledge
# a policy, yes is simply true.

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


def asked_path():
    return stateio.private_dir("profile") / "questions.json"


def _asked_key(question: str) -> str:
    """A question by what it ASKS, so two employers wording it differently
    are one question: lowercase content words, in order, punctuation gone."""
    words = re.sub(r"[^a-z0-9 ]", " ", str(question or "").casefold()).split()
    return " ".join(w for w in words if w not in _QUESTION_FILLER)[:200]


# Words that carry no meaning in a form label. "Please tell us your notice
# period*" and "What is your notice period?" are the same question.
_QUESTION_FILLER = frozenset({
    "the", "a", "an", "your", "you", "yours", "please", "us", "we", "our",
    "is", "are", "do", "does", "did", "what", "which", "tell", "enter",
    "provide", "give", "select", "choose", "required", "optional", "field",
    "this", "that", "of", "for", "to", "in", "on", "at", "and", "or", "if",
    "me", "my", "i", "it", "be", "have", "has", "will", "would", "can"})


def remember_question(question: str, value, *, source: str = "operator") -> dict | None:
    """An answer that fits no field of hers, kept by what the question asks.

    His words, 2026-09-11: "if it don't know somthing about me it can ask 1
    time after that it should know ... don't hard code that into there". Her
    FIELDS cover the things every form asks; the long tail ("how many years
    selling into healthcare", "what is your notice period") fitted none of
    them, so the answer was used on that one form and the next employer
    asked again. This is the tail, and it is deliberately NOT a field: it is
    his answer to a question, reused only where the same question is asked.

    Declarations, signatures, certifications and protected characteristics
    are never kept here — those are his to answer on every form, which is
    his own standing rule, so they are refused at the door.
    """
    from aletheia import formfill
    text = " ".join(str(question or "").split())
    if not text or formfill.is_never_autofill({"label": text}):
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    key = _asked_key(text)
    if not key:
        return None
    asked = _load_asked()
    asked[key] = {"question": text[:MAX_VALUE_CHARS],
                  "value": value.strip()[:MAX_VALUE_CHARS],
                  "source": str(source)[:80], "at": stateio.utcnow()}
    stateio.write_json_atomic(asked_path(), asked)
    # The QUESTION, never his answer: the value is his and does not travel.
    journal.append("note", "profile", f"his answer to {text[:80]!r} is on file",
                   actor=ACTOR)
    return asked[key]


def _load_asked() -> dict:
    try:
        value = stateio.read_json(asked_path())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def answer_for(question: str) -> str:
    """What he already told her about this question, or ""."""
    held = _load_asked().get(_asked_key(question))
    return str(held.get("value") or "") if isinstance(held, dict) else ""


def questions_on_file() -> list[dict]:
    """Everything he has been asked once, for "what do you know about me"."""
    return [{"question": v.get("question", k), "value": v.get("value", ""),
             "at": v.get("at", "")}
            for k, v in sorted(_load_asked().items()) if isinstance(v, dict)]


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


# What her MEMORY of him already contains, in the words this store uses.
#
# Her memory (Playbook §38-45) and this profile both ended up holding his
# name and his city, and only one of them was ever read for an answer. On
# his machine memory held "Caleb Schulte" and "Hartford, SD 57033" while
# every field here was empty, so "where do I live" came back "I don't
# have your city on file" — about a fact on the same disk — and
# `setup_status` asked him for it.
#
# Parsed, not pasted. These values are typed into form fields, and
# "Hartford, SD 57033" in a box labelled City is the same class of wrong
# as a phone number with two extra digits on the front.
_FROM_MEMORY = ("full_name", "operator_name", "home_city")


def _split_place(value: str) -> dict:
    """"Hartford, SD 57033" -> city / state / postal_code."""
    m = re.match(r"\s*(?P<city>[^,]{2,60}?)\s*,\s*(?P<state>[A-Za-z]{2})"
                 r"(?:\s+(?P<zip>[0-9]{5}(?:-[0-9]{4})?))?\s*$", str(value or ""))
    if not m:
        return {}
    out = {"city": m.group("city").strip(), "state": m.group("state").upper()}
    if m.group("zip"):
        out["postal_code"] = m.group("zip")
    return out


def _split_name(value: str) -> dict:
    words = str(value or "").split()
    if not (2 <= len(words) <= 4):
        return {}
    return {"legal_name": " ".join(words),
            "first_name": words[0], "last_name": words[-1]}


def from_memory() -> dict:
    """The overlap, translated — read-only, and never written back here.

    Copying would create the second source of truth that caused this.
    Never raises: memory being unreadable must not take the profile down
    with it, because the profile is the half he actually corrects.
    """
    try:
        from aletheia import memory
        identity = (memory.everything() or {}).get("identity") or {}
    except Exception:
        return {}
    held = {}
    for key in _FROM_MEMORY:
        entry = identity.get(key)
        value = entry.get("value") if isinstance(entry, dict) else entry
        if not value:
            continue
        if key == "home_city":
            held.update(_split_place(value))
        elif key == "full_name":
            held.update(_split_name(value))
        elif key == "operator_name":
            held.setdefault("preferred_name", str(value).strip())
    return {k: v for k, v in held.items() if k in FIELDS and v}


def answer(field: str):
    held = load().get(field)
    value = held.get("value") if isinstance(held, dict) else None
    if value in (None, ""):
        # Not "she does not know" until BOTH have been asked.
        return from_memory().get(field)
    return value


def known() -> dict:
    """Everything she can answer, this store winning where they overlap."""
    held = {k: v.get("value") for k, v in load().items()
            if isinstance(v, dict) and v.get("value") not in (None, "")}
    remembered = from_memory()
    remembered.update(held)
    return remembered


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
# A separator inside a phone number is a space, a dot or a hyphen — NEVER
# a line break, and the country code needs its plus. Without both, a line
# above his number ending in "33" was read as part of it: his real resume
# yielded "33 (605) 321-5691". `[\s.-]` matched the newline, and `\d{1,2}`
# with an optional plus was happy to call "33" a country code.
_PHONE = re.compile(r"(?<!\d)(?:\+\d{1,2}[ .\-]?)?\(?\d{3}\)?[ .\-]?"
                    r"\d{3}[ .\-]?\d{4}(?!\d)")
_LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+", re.I)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I)
_SITE = re.compile(r"https?://[\w.-]+\.[a-z]{2,}(?:/\S*)?", re.I)
_CITY_STATE = re.compile(r"\b([A-Z][a-zA-Z .'-]{2,24}),\s*([A-Z]{2})\b")


def _broken_by_spacing(words: list[str], email: str) -> bool:
    """Does his email say two of these words are one word, split by spacing?"""
    local = re.sub(r"[^a-z]", "", str(email).split("@", 1)[0].casefold())
    if len(words) < 3 or not local:
        return False
    return any(len(a + b) >= 5 and (a + b).casefold() in local
               for a, b in zip(words, words[1:]))


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
        # "Hartford, SD 57033": the ZIP is on the same line, and Samsara's
        # form asked for it live 2026-09-10 as a thing she did not know.
        zip_code = re.match(r"\s+([0-9]{5}(?:-[0-9]{4})?)\b", text[place.end():])
        if zip_code:
            found.setdefault("postal_code", zip_code.group(1))
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
            if _broken_by_spacing(words, email.group(0) if email else ""):
                # "CALEB SCHU LTE": a title letter-spaced with REAL spaces in
                # his own .docx went onto a Stripe application 2026-09-10 as
                # last name "LTE". Which spaces belong to the name is not in
                # the text, so this guess is not taken; the model's reading
                # (campaign.learn_more) or the form's own question settles it.
                break
            if line.isupper():
                words = [re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), w)
                         for w in words]
            found["legal_name"] = " ".join(words)
            found.setdefault("first_name", words[0])
            found.setdefault("last_name", words[-1])
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
