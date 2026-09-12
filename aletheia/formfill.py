"""Reading a form, filling what she knows, and asking about the rest.

"Half the jobs these days hand you off to an external website and make
you type in all your information again" — that is the problem, and the
packet builder solved the wrong half of it. Writing a good cover letter
is the part he could already get from any chat assistant. Retyping his
phone number into a Workday for the ninth time is the part only something
that lives on his machine can fix.

So this reads the actual form: every input, select and textarea, with the
label a human would read, whether it is required, and what its options
are. Then it maps each field to an answer in `aletheia.profile` and
produces two lists.

THE TWO LISTS ARE THE WHOLE DESIGN.

`fill` is what she knows and will type. `ask` is everything else, and it
comes back to HIM. Nothing is ever guessed, and there is no configuration
that changes that, because the failure mode is not a typo — it is a
confident wrong answer to "are you legally authorized to work in the
United States" submitted under his name to a company that keeps it.

Some fields are refused even when the profile happens to hold an answer:
protected characteristics, legal declarations, anything with a signature
or a certification checkbox. Those are `NEVER_AUTOFILL` in the profile
module, and they land in `ask` no matter what.

Nothing here presses anything. It produces a PLAN — a step list in
`browse.interact`'s own grammar — which still needs an approval bound to
that exact page and that exact plan before a single character is typed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from aletheia import journal, policy, profile, speech

ACTOR = "aletheia-formfill"

MAX_FIELDS = 120
MAX_LABEL_CHARS = 160
# Anything longer than this in a text box is a cover letter or an essay
# question, not a fact she has on file.
LONG_ANSWER_TYPES = ("textarea",)

# Field types she will never type into: a file upload is a real file
# chooser, and a password is not hers to know.
SKIP_TYPES = ("file", "password", "hidden", "submit", "button", "image",
              "reset")

# The furniture of a widget is not a question. Live 2026-09-11, four real
# applications (Stripe, Databricks, Brex, Samsara) each came back asking him
# "List of countries" - every country on earth with its dial code, offered as
# a multiple-choice question - and "Search". Both are the inside of the PHONE
# NUMBER country picker (intl-tel-input, `iti-0__*`), which opens because she
# fills the phone field. The reCAPTCHA's hidden answer box arrived the same
# way. None was required by any employer; all three were handed to him as
# things only he could answer.
#
# Matched on the SELECTOR, never the label: "Search" and "List of countries"
# are plausible words for a real question, and an employer who genuinely asks
# "which countries can you work in?" must still reach him.
WIDGET_SELECTORS = ("#iti-", "#g-recaptcha-response", "#recaptcha")


def is_widget_furniture(field: dict) -> bool:
    """The inside of a picker or a captcha, not something he was asked."""
    selector = str(field.get("selector") or "").casefold()
    if any(selector.startswith(prefix) for prefix in WIDGET_SELECTORS):
        return True
    name = str(field.get("name") or field.get("id") or "").casefold()
    return name.startswith("g-recaptcha-response")

# The JS that runs in the page. Reading a form means reading what a PERSON
# sees, so the label matters more than the name attribute: `q_31415926` is
# what Workday calls "Are you legally authorized to work?".
READ_FORM_JS = r"""() => {
  const labelFor = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && l.innerText.trim()) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap && wrap.innerText.trim()) return wrap.innerText.trim();
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const n = document.getElementById(by);
      if (n && n.innerText.trim()) return n.innerText.trim();
    }
    // The field's OWN placeholder before the group's legend. A legend
    // describes the whole fieldset — taking it made an unlabelled GitHub
    // box (name="q_8872", placeholder="GitHub URL") read as "About you",
    // so a URL she had on file came back as "she could not tell what this
    // is asking for". A placeholder is this field's text; a legend is
    // seven other fields' text.
    const hint = (el.getAttribute('placeholder') || '').trim();
    if (hint) return hint;
    const group = el.closest('fieldset');
    if (group) {
      const legend = group.querySelector('legend');
      if (legend && legend.innerText.trim()) return legend.innerText.trim();
    }
    return '';
  };
  const selectorFor = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    if (el.name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
    return null;
  };
  // A checkbox or radio is an OPTION, not a question. Its own label says
  // "Australia"; the QUESTION — "which countries do you anticipate working
  // in?" — lives on the group. Reading only the label turned one question
  // into 26 unanswerable ones on a real Stripe application.
  const questionFor = (el) => {
    const described = el.getAttribute('description');
    if (described) return described.trim();
    const group = el.closest('fieldset, [role="group"], [role="radiogroup"]');
    if (group) {
      const legend = group.querySelector('legend, .label, [class*="label"]');
      if (legend && legend.innerText.trim()) return legend.innerText.trim();
    }
    const by = el.getAttribute('aria-describedby');
    if (by) {
      const n = document.getElementById(by);
      if (n && n.innerText.trim()) return n.innerText.trim();
    }
    return '';
  };
  const out = [];
  for (const el of document.querySelectorAll('input, select, textarea')) {
    const tag = el.tagName.toLowerCase();
    const type = (tag === 'input' ? (el.type || 'text') : tag).toLowerCase();
    const selector = selectorFor(el);
    if (!selector) continue;
    const row = {
      selector, tag, type,
      name: el.name || '', id: el.id || '',
      role: el.getAttribute('role') || '',
      label: labelFor(el),
      required: !!(el.required || el.getAttribute('aria-required') === 'true'),
      value: (el.value || '').slice(0, 200),
    };
    if (type === 'checkbox' || type === 'radio') {
      // A checkbox's `value` is "on" whether or not it is ticked, so a
      // required certification box READ AS FILLED, the browser refused the
      // submit, and the run reported success while the employer received
      // nothing. Its real state is `checked`.
      row.checked = !!el.checked;
      row.value = el.checked ? 'checked' : '';
      row.option = row.label;
      row.question = questionFor(el);
      // Radios share a name; Greenhouse's checkbox groups do too.
      row.group = (el.name || '').replace(/\[\]$/, '') || row.question;
    }
    if (tag === 'select') {
      row.options = Array.from(el.options)
        .map(o => ({value: o.value, text: (o.text || '').trim()}))
        .filter(o => o.value !== '')
        .slice(0, 60);
    }
    out.push(row);
  }
  return out;
}"""


class FormError(RuntimeError):
    pass


def _haystack(field: dict) -> str:
    return " ".join(str(field.get(k, "") or "")
                    for k in ("label", "name", "id")).casefold()


def is_never_autofill(field: dict) -> bool:
    """Protected characteristics and legal declarations, always his."""
    hay = _haystack(field)
    if any(phrase in hay for phrase in profile.NEVER_AUTOFILL):
        return True
    # A protected characteristic asked in words the list does not contain
    # ("Sex", "Are you Hispanic/Latino?") is still one.
    return bool(_declared_category(str(field.get("label") or "")))


# A question he answers yes or no is not asking for his city or his job
# title, whatever words are in it. Live 2026-09-10, once those were on file:
# "employed by Coinbase in any CAPACITY" got Hartford, "are you a CURRENT
# government official" got his job title, "do you accept the salary range
# for this POSITION" got it again, and "I confirm that I reside in the
# United STATES" got SD. A sentence like that takes only a yes-or-no fact.
_YES_NO_LEAD = re.compile(
    r"^[^a-z0-9]*(?:(?:are|am|is|do|does|did|have|has|had|will|would|were|was|"
    r"can|could|should|may)\b|to your knowledge\b|please confirm\b|"
    r"i (?:confirm|understand|certify|agree|acknowledge|consent|attest)\b)")
YES_NO_FIELDS = frozenset({"work_authorization", "needs_sponsorship",
                           "willing_to_relocate"})


def _says(phrase: str, text: str) -> bool:
    """The phrase as words: "city" is not in "capacity"."""
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])",
                     text) is not None


# "require/need sponsorship", "require a visa", "need us to sponsor you" -
# the question about NEEDING it, however much authorization vocabulary the
# rest of the sentence carries.
# A question about being ALLOWED to work, however much geography it names.
_AUTHORIZED_TO_WORK = re.compile(
    r"\bauthoriz\w*\s+to\s+work\b|\bwork\s+authoriz\w*\b|\blegally\s+(?:able|allowed)"
    r"\s+to\s+work\b|\bright\s+to\s+work\b|\beligib\w*\s+to\s+work\b", re.I)

_WANTS_SPONSORSHIP = re.compile(
    r"\b(?:require|requires|requiring|need|needs|needing|seek|seeking|request"
    r"|requesting)\b[^.?]{0,60}?\b(?:sponsorship|sponsor|visa|work permit)\b"
    r"|\bsponsor(?:ship)?\s+(?:is\s+)?(?:required|needed)\b")


def match_field(field: dict) -> str | None:
    """Which profile answer this form field is asking for, if any.

    Longest phrase wins: "first name" must beat "name", or every name box
    on the internet gets his full legal name. The LABEL is what a person
    reads, so it is matched as words; a field's name and id are code
    ("postalCode", "question_8812") and are read only when nothing is
    labelled at all.
    """
    label = str(field.get("label") or "").casefold()
    # "If you're not authorized to work at the stated location, what..." asks
    # something that depends on an earlier answer, not a fact on file. Live on
    # Brex 2026-09-10 it got "Yes", and "If you have worked at Capital One..."
    # got his current employer.
    if re.match(r"^[^a-z0-9]*if\b", label):
        return None
    yes_no = bool(_YES_NO_LEAD.match(label))
    codes = " ".join(str(field.get(k) or "") for k in ("name", "id")).casefold()
    best, best_len = None, 0
    for key, spec in profile.FIELDS.items():
        if yes_no and key not in YES_NO_FIELDS:
            continue
        # "Years of experience IN sales operations" is not his total years:
        # live it got 6, counting six years of construction.
        if key == "years_experience" and re.search(
                r"experience\b.*\b(?:in|with|as|doing|using|on|at)\b", label):
            continue
        # "Please state the employee's name" is the verb: live it got "SD".
        if key == "state" and re.search(
                r"\bstate\s+(?:the|your|a|an|any|why|how|what|which|who|if|whether)\b", label):
            continue
        # THE TWO ANSWERS ARE OPPOSITES, so picking the wrong field does not
        # leave a blank - it states the reverse of the truth on a real
        # application. Live on Scale AI 2026-09-12: "Will you now or in the
        # future require company SPONSORSHIP to retain or extend your WORK
        # AUTHORIZATION...?" carries both vocabularies, longest-phrase-wins
        # chose `work authorization` (his Yes), and the form went to
        # AWAITING_YOU saying he needs sponsorship. His `needs_sponsorship`
        # was "No" the whole time and was never consulted.
        #
        # Asking whether he NEEDS something settles it, whatever other words
        # the sentence contains.
        if key == "work_authorization" and _WANTS_SPONSORSHIP.search(label):
            continue
        # "Your authorization to work in the country where you live" is a
        # question about AUTHORIZATION that happens to contain the word
        # country - and longest-phrase-wins handed it to `country`, so
        # Vercel would have been told "United States" when it asked whether
        # he may legally work. The same shape as the sponsorship bug: the
        # right words, the wrong fact. His note, 2026-09-12: "The Versa one,
        # that sounds like an issue that you need to fix."
        if key in ("country", "city", "state") and _AUTHORIZED_TO_WORK.search(label):
            continue
        for phrase in spec["asks"]:
            if len(phrase) <= best_len:
                continue
            if _says(phrase, label) or (not label.strip() and phrase in codes):
                best, best_len = key, len(phrase)
    # "In what city AND state do you reside?" is neither fact alone: live it
    # got "SD". Left for the facts step, which writes "Hartford, SD".
    if best in ("city", "state") and _says("city", label) and _says("state", label):
        return None
    return best


def _option_for(field: dict, value) -> str | None:
    """A dropdown answer, matched to one of ITS options.

    Selecting an option that does not exist silently does nothing in some
    browsers and throws in others, and either way the form is submitted
    with the field empty.
    """
    wanted = ("yes" if value is True else "no" if value is False
              else str(value)).strip().casefold()
    options = field.get("options") or []
    for option in options:
        if option["value"].strip().casefold() == wanted:
            return option["value"]
    for option in options:
        if option["text"].strip().casefold() == wanted:
            return option["value"]
    for option in options:
        text = option["text"].strip().casefold()
        if text.startswith(wanted) or wanted.startswith(text):
            return option["value"]
    return None


def _group_choices(fields: list[dict]) -> tuple[list[dict], list[dict]]:
    """Fold a group of checkboxes or radios into ONE question with options.

    A real Stripe application asks "which countries do you anticipate
    working in?" as twenty-six checkboxes. Read one at a time they became
    twenty-six required questions labelled Australia, Belgium, Brazil —
    every one of them unanswerable, and between them they buried the eight
    questions he actually had to answer.
    """
    groups: dict[str, dict] = {}
    rest = []
    for field in fields:
        if field.get("type") not in ("checkbox", "radio") or not field.get("group"):
            rest.append(field)
            continue
        held = groups.setdefault(field["group"], {
            "kind": "choice", "type": field["type"], "group": field["group"],
            "label": field.get("question") or field.get("option") or field["group"],
            "required": False, "options": [], "selector": field["selector"]})
        held["required"] = held["required"] or bool(field.get("required"))
        held["options"].append({"label": field.get("option") or "",
                                "selector": field["selector"]})
    # A "group" of one is just a checkbox — the certification tickbox, say —
    # and reads better as itself than as a question with a single option.
    singles = [g for g in groups.values() if len(g["options"]) == 1]
    for single in singles:
        groups.pop(single["group"], None)
        rest.append({"selector": single["options"][0]["selector"],
                     "label": single["label"], "name": "", "id": "",
                     "tag": "input", "type": single["type"],
                     "required": single["required"], "value": ""})
    return rest, list(groups.values())


def _from_profile(group: dict, known: dict) -> dict | None:
    """The option his profile already answers, or None.

    Matched on the option's FIRST WORD as well as the whole of it, so
    "Yes, I am authorized to work" answers "Yes" — and so that "No" does
    not quietly answer "North America", which a plain `startswith` did.
    """
    if group.get("type") != "radio" or is_never_autofill({"label": group["label"]}):
        return None
    key = match_field({"label": group["label"]})
    answer = known.get(key) if key else None
    if answer in (None, ""):
        return None
    want = str(answer).strip().casefold()
    for option in group["options"]:
        text = (option.get("label") or "").strip().casefold()
        if not text:
            continue
        head = text.split()[0].strip(",.:;!?") if text.split() else ""
        if text == want or head == want:
            return {**option, "profile_field": key}
    return None


# Categories he has declared IN HIS OWN WORDS and that may therefore be
# reused. 2026-09-12: veteran status and disability status blocked twelve of
# thirteen live applications, and he had answered both out loud - "I am not
# a protected veteran", "I have no disabilities" - with nowhere to keep it.
# Orientation and transgender resolve to a DECLINE, which is also his own
# answer: "I don't think they can ask that. If they do, but I'm not
# answering."
_ORIENTATION = re.compile(r"\b(?:sexual|orientation|transgender|lgbt)", re.I)
_VETERAN = re.compile(r"\b(?:veteran|armed forces|military)", re.I)
_DISABILITY = re.compile(r"\b(?:disabilit|disabled|chronic condition)", re.I)
_PRONOUNS = re.compile(r"\bpronoun", re.I)
_SAID_NO = ("no", "false", "not hispanic", "not hispanic or latino", "non hispanic")
_SAID_YES = ("yes", "true", "hispanic", "hispanic or latino", "latino", "latina")


def _declared_category(label: str) -> str:
    """The self-identification category a question asks about, or ""."""
    text = str(label or "")
    # Most specific first: "Are you a veteran/have you served in the
    # military?" and "gender identity survey" both mention other words.
    if _ORIENTATION.search(text):
        return "self_id_decline"
    if _VETERAN.search(text):
        return "veteran_status"
    if _DISABILITY.search(text):
        return "disability_status"
    if _PRONOUNS.search(text):
        return "pronouns"
    low = _norm(label)
    hispanic = any(_says(w, low) for w in ("hispanic", "latino", "latina", "latinx", "latine"))
    race = any(_says(w, low) for w in ("race", "racial", "ethnicity", "ethnic"))
    gender = _says("gender", low) or _says("sex", low)
    if gender and not (race or hispanic):
        return "gender"
    if race:
        return "race"
    if hispanic:
        return "hispanic_latino"
    return ""


def _his_word(stored: dict, field: str) -> str:
    row = stored.get(field)
    if isinstance(row, dict) and row.get("source") == "operator":
        return _norm(row.get("value"))
    return ""


def _hispanic_choice(options: list[str], said: str) -> str | None:
    no, yes = said in _SAID_NO, said in _SAID_YES
    if not (no or yes):
        return None
    plain = [c for c in options if _norm(c) == ("no" if no else "yes")]
    if len(plain) == 1:
        return plain[0]
    named = [c for c in options
             if (_says("hispanic", _norm(c)) or _says("latino", _norm(c)))
             and _says("not", _norm(c)) == no and not _says("decline", _norm(c))]
    return named[0] if len(named) == 1 else None


def _plain_choice(options: list[str], want: tuple[str, ...],
                  avoid: tuple[str, ...] = ()) -> str | None:
    """The one option that plainly says `want` and none of `avoid`."""
    hits = [c for c in options
            if any(_says(w, _norm(c)) for w in want)
            and not any(_says(a, _norm(c)) for a in avoid)]
    if len(hits) > 1:
        exact = [c for c in hits if _norm(c) in want]
        hits = exact or hits
    return hits[0] if len(hits) == 1 else None


_DECLINE_WORDS = ("i don't wish to answer", "i do not wish to answer",
                  "i dont wish to answer", "i prefer not to answer",
                  "i don't want to answer", "i do not want to answer",
                  "decline to self identify", "decline to answer",
                  "prefer not to say", "i don't wish to disclose")


def _decline_choice(options: list[str]) -> str | None:
    """"I don't wish to answer" - his answer to a question he won't answer."""
    for option in options:
        if _norm(option) in _DECLINE_WORDS:
            return option
    hits = [c for c in options
            if ("wish" in _norm(c) or "prefer" in _norm(c) or "decline" in _norm(c))
            and ("not" in _norm(c) or "don t" in _norm(c) or "dont" in _norm(c))]
    return hits[0] if len(hits) == 1 else None


def declared_choice(label: str, choices: list[str], *, stored: dict | None = None) -> str | None:
    """The option that says what HE said about himself, or None.

    Only from his own words (source "operator"): never read off a resume or
    a page, never a model's guess. An option that does not plainly say it
    means asking him.

    2026-09-12 this grew from three categories to seven. Thirteen live
    applications stalled at once and twelve were blocked on veteran status
    and disability - which he had already answered out loud ("I am not a
    protected veteran", "I have no disabilities") with nowhere to keep it.
    Orientation and transgender resolve to the decline HE chose: "I don't
    think they can ask that. If they do, but I'm not answering."
    """
    category = _declared_category(label)
    if not category:
        return None
    stored = profile.load() if stored is None else stored
    options = [str(c) for c in (choices or []) if str(c).strip()]
    if not options:
        return None
    if category == "self_id_decline":
        # He has to have SAID he declines; silence is still silence.
        return _decline_choice(options) if _his_word(stored, "self_id_decline") else None
    if category == "pronouns":
        said = _his_word(stored, "pronouns")
        if not said:
            return None
        want = tuple(part for part in re.split(r"[\s/,]+", said) if part)
        exact = [c for c in options if _norm(c).replace(" ", "") == said.replace(" ", "")]
        if len(exact) == 1:
            return exact[0]
        return _plain_choice(options, want, avoid=("she", "her", "hers", "they", "them", "theirs")
                             if "he" in want else ())
    if category == "veteran_status":
        said = _his_word(stored, "veteran_status")
        if not said:
            return None
        real = [c for c in options if _decline_choice([c]) is None]
        if said in _SAID_NO or "not a" in said or "not protected" in said:
            # WHAT is negated, not merely that something is. Asana offers
            # "I am not a veteran (I did not serve in the military)" AND
            # "I am a veteran and I do NOT belong to a classification of
            # protected veterans" - both contain "not", and only the first
            # says he is not one. Live 2026-09-12 a bare "not" matched both
            # and answered neither.
            hits = [c for c in real
                    if re.search(r"\bnot\s+(?:a|an)?\s*(?:protected\s+)?veteran\b",
                                 _norm(c))]
            return hits[0] if len(hits) == 1 else None
        hits = [c for c in real
                if _says("veteran", _norm(c))
                and not re.search(r"\bnot\s+(?:a|an)?\s*(?:protected\s+)?veteran\b",
                                  _norm(c))]
        return hits[0] if len(hits) == 1 else None
    if category == "disability_status":
        said = _his_word(stored, "disability_status")
        if not said:
            return None
        # "I do not want to answer" also contains "not": a decline is never
        # the same as an answer, so those come out first.
        real = [c for c in options
                if _decline_choice([c]) is None and not _says("describe", _norm(c))]
        no_disability = re.compile(
            r"\b(?:no|not|don t|dont|never)\b[^.]{0,40}\bdisabilit", re.I)
        if said in _SAID_NO or said.startswith("no") or "not" in said:
            hits = [c for c in real if no_disability.search(_norm(c))]
        else:
            hits = [c for c in real
                    if _says("yes", _norm(c)) and not no_disability.search(_norm(c))]
        return hits[0] if len(hits) == 1 else None
    if category == "gender":
        said = _his_word(stored, "gender")
        male, female = said in ("male", "man", "m"), said in ("female", "woman", "f")
        if not (male or female):
            exact = [c for c in options if _norm(c) == said] if said else []
            return exact[0] if len(exact) == 1 else None
        want = {"male", "man", "men"} if male else {"female", "woman", "women"}
        other = ({"female", "woman", "women"} if male else {"male", "man", "men"}) | {
            "trans", "transgender", "non", "nonbinary", "binary"}
        hits = [c for c in options if set(_norm(c).split()) & want
                and not set(_norm(c).split()) & other]
        if len(hits) > 1:
            hits = [c for c in hits if _norm(c) in want] or hits
        return hits[0] if len(hits) == 1 else None
    hispanic = _his_word(stored, "hispanic_latino")
    if category == "race":
        race = _his_word(stored, "race")
        if race:
            hits = [c for c in options if _says(race, _norm(c)) and not _says("two", _norm(c))]
            if len(hits) > 1 and hispanic:
                no = hispanic in _SAID_NO
                hits = [c for c in hits if _says("not", _norm(c)) == no] or hits
            if len(hits) > 1:
                hits = [c for c in hits if _norm(c) == race] or hits
            if len(hits) == 1:
                return hits[0]
        # An ethnicity-only list: "Hispanic or Latino" / "Not Hispanic or Latino".
        return _hispanic_choice(options, hispanic) if hispanic else None
    return _hispanic_choice(options, hispanic) if hispanic else None


# The one thing she must never tick, whatever else he has allowed. His
# ruling, 2026-09-12: "the only thing that I wouldn't want you to ever auto
# click on is something like, hey. You'll go to jail if you use AI on this.
# Like, that's the only thing that you should never auto click on in my
# mind." Samsara and Anthropic both carry an "AI Policy for Application"
# box - a declaration about how the application itself was written, being
# offered to the thing writing it - and a false one is his problem, not
# hers, for as long as he works there.
_NEVER_TICK = re.compile(
    # A declaration that AI was NOT used. He is applying through an AI, so
    # this one is a lie whichever way it is worded, and it is the only AI
    # box still refused. His ruling, 2026-09-12: "if yes is an answer, just
    # hit yes. Like, why lie? Yes. We helped you, the AI, to do this."
    r"\b(?:did not|have not|didn'?t|haven'?t|without|no)\b[^.?]{0,40}"
    r"\b(?:a\.?i\.?|artificial intelligence|chatgpt|llm|large language model"
    r"|generative|automated tool)\b"
    r"|\b(?:a\.?i\.?|artificial intelligence|chatgpt|llm)\b[^.?]{0,30}"
    r"\b(?:was not|were not|not used|prohibited|not permitted)\b"
    r"|penalty of perjury|under oath|sworn|prosecut|criminal|fraud"
    r"|background check|credit check|drug (?:test|screen)", re.I)

# An AI policy he ACKNOWLEDGES or discloses under is routine paperwork like
# any other: "AI Policy for Application", "AI Policy for Interviewers", "Do
# you agree to our AI policy". Answered Yes, because yes is true - the
# application really was written with AI, and he would rather say so.
_AI_POLICY = re.compile(
    r"\b(?:a\.?i\.?|artificial intelligence)\b[^.?]{0,40}\bpolic",
    re.I)

# What a routine box actually is: permission to consider his application,
# an acknowledgement that he read something, or a statement that what he
# typed is true - which HE confirms, because every application is shown to
# him before it is sent and nothing goes without his approval.
# Keyed on the SUBJECT, never on "acknowledge" or "I agree" alone. Live
# 2026-09-12 the verb-shaped version swallowed "This role requires in-office
# work three days per week. Do you acknowledge and agree to this
# requirement?" - which is not paperwork at all, it is a real commitment
# about his week, and he answers it himself.
_ROUTINE_CONSENT = re.compile(
    r"personal (?:data|information)|data (?:protection|processing)"
    r"|processing of personal|demographic data|gdpr|ccpa"
    r"|privacy (?:notice|policy|statement)|applicant privacy|candidate privacy"
    r"|privacy|arbitrat|terms and conditions"
    r"|information (?:i |you )?(?:have )?provided|information provided above"
    r"|accurate|accuracy|truthful|reviewed and confirmed"
    r"|processing my responses|assessing my candidacy|assessing your candidacy"
    # "I certify...", "I agree..." - said in the first person, which is a
    # form being signed. "Do you acknowledge and agree to work in the office
    # three days a week" is not, and stays his.
    r"|\bi (?:certify|agree|consent|acknowledge|understand|accept)\b",
    re.I)

_AFFIRMS = ("i agree", "agree", "yes", "consent", "i consent", "acknowledge",
            "acknowledge/confirm", "confirm", "i confirm", "i understand",
            "understand", "accept", "i accept")


def routine_consent(label: str, options: list[str]) -> str | None:
    """The affirmative option on a routine agreement, or None.

    2026-09-12: thirteen applications, and several were held up by boxes
    that are not questions about him at all - "may we process your data",
    "I have read the privacy notice", "I confirm the information above is
    accurate", an arbitration agreement. His ruling: *"I don't really get
    what the consent and certifications is. Just figure out a way around
    it. It's not that big a deal."* and then, on arbitration specifically:
    *"what would I ever wanna sue anthropic for? I'm just trying to apply
    my job."*

    His approval is what makes the accuracy certifications true: he reads
    every application before it is sent, and nothing is ever sent without
    him. `_NEVER_TICK` is the line he drew himself and it is not moveable
    from here.
    """
    text = str(label or "")
    if _NEVER_TICK.search(text):
        return None
    if not (_ROUTINE_CONSENT.search(text) or _AI_POLICY.search(text)):
        return None
    real = [str(c) for c in (options or []) if str(c).strip()]
    if not real:
        return None
    if len(real) == 1:
        # A lone tickbox. The LABEL already said this is paperwork; the one
        # option is just the box's own words ("Acknowledge/Confirm",
        # "Consent", "I agree", or the sentence repeated). It only has to
        # not be a refusal. Live 2026-09-12 requiring it to re-qualify left
        # "Processing of Personal Data" and Vercel's privacy notice blocking
        # real applications.
        only = _norm(real[0])
        refuses = (_decline_choice(real) is not None
                   or only in ("no", "i do not agree", "i disagree", "decline"))
        return None if refuses else real[0]
    hits = [c for c in real if _norm(c) in _AFFIRMS]
    if len(hits) == 1:
        return hits[0]
    hits = [c for c in real
            if any(_says(word, _norm(c)) for word in ("agree", "consent", "acknowledge",
                                                      "confirm", "accept", "reviewed"))
            and not _says("not", _norm(c)) and not _says("no", _norm(c))]
    return hits[0] if len(hits) == 1 else None


def plan(fields: list[dict], *, answers: dict | None = None) -> dict:
    """Split a form into what she can fill and what he has to answer."""
    answers = known = (answers if answers is not None else profile.known())
    fields, choices = _group_choices(list(fields)[:MAX_FIELDS])
    fill, ask, skipped = [], [], []
    for group in choices:
        if is_widget_furniture(group):
            # The phone picker's country list. Not a question anybody asked.
            skipped.append({"selector": group["selector"], "label": group["label"],
                            "required": group["required"], "type": group["type"],
                            "why": "part of a picker on the page, not a question"})
            continue
        # A SINGLE-answer question she already has on file is answered, not
        # asked. "Are you legally authorized to work in the US?" is a pair
        # of divs on a modern form and a pair of radios on an old one, and
        # either way the answer has been in his profile the whole time —
        # she was handing it back to him on every application.
        declared = declared_choice(group["label"],
                                   [o["label"] for o in group["options"] if o["label"]])
        if declared is not None:
            option = next(o for o in group["options"] if o["label"] == declared)
            fill.append({"action": "click", "selector": option["selector"],
                         "label": group["label"], "value": declared,
                         "profile_field": _declared_category(group["label"])})
            continue
        consent = routine_consent(group["label"],
                                  [o["label"] for o in group["options"] if o["label"]])
        if consent is not None:
            option = next(o for o in group["options"] if o["label"] == consent)
            fill.append({"action": "click", "selector": option["selector"],
                         "label": group["label"], "value": consent,
                         "profile_field": "routine_consent"})
            continue
        picked = _from_profile(group, known)
        if picked is not None:
            fill.append({"action": "click", "selector": picked["selector"],
                         "label": group["label"], "value": picked["label"],
                         "profile_field": picked["profile_field"]})
            continue
        # A multiple-choice question is his: which countries, which
        # locations, which of these apply to you. She has no fact on file
        # that answers it and guessing one is exactly what she must not do.
        ask.append({"selector": group["selector"], "label": group["label"],
                    "required": group["required"], "type": group["type"],
                    "choices": [o["label"] for o in group["options"] if o["label"]],
                    "option_selectors": {o["label"]: o["selector"]
                                         for o in group["options"] if o["label"]},
                    "why": "a multiple-choice question only you can answer"})
    for field in fields[:MAX_FIELDS]:
        label = (field.get("label") or field.get("name") or
                 field.get("id") or field["selector"])[:MAX_LABEL_CHARS]
        row = {"selector": field["selector"], "label": label,
               "required": bool(field.get("required")), "type": field.get("type")}
        if field.get("choices"):
            # A dropdown's own options, read off its open menu: the answer has
            # to be one of them, or the picker has nothing to click.
            row["choices"] = list(field["choices"])
        if field.get("type") in SKIP_TYPES:
            row["why"] = ("a file upload is yours to choose"
                          if field.get("type") == "file"
                          else f"she does not type into a {field.get('type')} field")
            skipped.append(row)
            continue
        if is_widget_furniture(field):
            row["why"] = "part of a picker on the page, not a question"
            skipped.append(row)
            continue
        if is_never_autofill(field):
            # Even if the profile holds it. An answer invented on his
            # behalf here is a lie in a file an employer keeps. The one
            # exception is his own words about himself (declared_choice).
            choices = ([o["text"] for o in field.get("options") or []]
                       if field.get("tag") == "select" else list(field.get("choices") or []))
            declared = declared_choice(label, choices)
            if declared is not None:
                category = _declared_category(label)
                if field.get("tag") == "select":
                    option = next((o["value"] for o in field.get("options") or []
                                   if o["text"] == declared), None)
                    if option is not None:
                        fill.append({"action": "select", "selector": field["selector"],
                                     "value": option, "label": label,
                                     "profile_field": category})
                        continue
                else:
                    fill.append({"action": "type", "selector": field["selector"],
                                 "value": declared, "label": label, "profile_field": category})
                    continue
            # Routine paperwork: "may we process your data", "I have read
            # the privacy notice", "I confirm the above is accurate", an
            # arbitration agreement. His ruling, 2026-09-12. Never an AI
            # declaration or anything with legal jeopardy - see _NEVER_TICK.
            consent = (None if field["selector"] in answers
                       else routine_consent(label, choices or [label]))
            if consent is not None:
                if field.get("tag") == "select":
                    option = next((o["value"] for o in field.get("options") or []
                                   if o["text"] == consent), None)
                    if option is not None:
                        fill.append({"action": "select", "selector": field["selector"],
                                     "value": option, "label": label,
                                     "profile_field": "routine_consent"})
                        continue
                elif field.get("type") in ("checkbox", "radio"):
                    fill.append({"action": "click", "selector": field["selector"],
                                 "label": label, "value": consent,
                                 "profile_field": "routine_consent"})
                    continue
                else:
                    fill.append({"action": "type", "selector": field["selector"],
                                 "value": consent, "label": label,
                                 "profile_field": "routine_consent"})
                    continue
            row["why"] = "this one is yours to answer, always"
            ask.append(row)
            continue
        # Paperwork that is not phrased as a certification. "Processing of
        # Personal Data", "Applicant Privacy Notice" carry none of the
        # NEVER_AUTOFILL words, so they fall past the branch above and used
        # to arrive as "she could not tell what this is asking for" -
        # blocking real applications on a box that asks nothing about him.
        # Everything protected, and every AI declaration, was taken out
        # above this line.
        # HIS ANSWER OUTRANKS THE RULE. If he has said something about this
        # box - including "no" - that is the answer, and routine paperwork
        # never ticks over the top of it. Same shape as the ChatGPT lease
        # fixed the same day: an order he gave has to beat a default.
        consent = (None if field["selector"] in answers
                   else routine_consent(label, list(field.get("choices") or []) or [label]))
        if consent is not None:
            # Live 2026-09-12: Brex, Datadog, Vercel, Samsara and Asana all
            # came back blocked on consents this rule ANSWERS correctly -
            # because Greenhouse renders them as `type=text` pickers with an
            # options list, not as checkboxes, and this hook only clicked
            # checkboxes. The predicate was right and the hand was in the
            # wrong shape.
            action = ("click" if field.get("type") in ("checkbox", "radio")
                      else "select" if field.get("tag") == "select" else "type")
            fill.append({"action": action, "selector": field["selector"],
                         "label": label, "value": consent,
                         "profile_field": "routine_consent"})
            continue
        if field.get("type") in LONG_ANSWER_TYPES and not match_field(field):
            row["why"] = "a written answer, not a fact she has on file"
            ask.append(row)
            continue
        key = match_field(field)
        if key is None:
            # He answered this exact question once, on somebody else's form.
            # Asking him again is the thing he asked not to happen: "if it
            # don't know somthing about me it can ask 1 time after that it
            # should know". Never a declaration or a protected question —
            # is_never_autofill has already taken those out above.
            told = profile.answer_for(label)
            if told:
                fill.append({"action": "type", "selector": field["selector"],
                             "value": told, "label": label,
                             "profile_field": "asked_once"})
                continue
            row["why"] = "she could not tell what this is asking for"
            ask.append(row)
            continue
        if key not in known:
            row["why"] = f"she does not know {profile.FIELDS[key]['means']}"
            row["profile_field"] = key
            ask.append(row)
            continue
        value = known[key]
        if field.get("tag") == "select":
            option = _option_for(field, value)
            if option is None:
                row["why"] = (f"none of its options match what she has "
                              f"({profile.FIELDS[key]['means']})")
                row["profile_field"] = key
                ask.append(row)
                continue
            fill.append({"action": "select", "selector": field["selector"],
                         "value": option, "label": label, "profile_field": key})
            continue
        fill.append({"action": "type", "selector": field["selector"],
                     "value": str(value), "label": label, "profile_field": key})
    return {"fill": fill, "ask": ask, "skipped": skipped}


def apply_answers(out: dict, fields: list[dict], answers: dict) -> dict:
    """His answers to THIS form's own questions, keyed by selector.

    The questions she hands back are not all facts about him. "Why do you
    want to work here" is an essay; "have you been convicted of a felony"
    is a declaration; "I certify the above is true" is a checkbox he ticks
    himself. None of those belong in a profile that gets reused on the next
    form, so they arrive here, are used once, and are not stored.

    Each answer is turned into the right ACTION for that field's real type
    — `fill` does nothing useful to a checkbox, and selecting an option a
    dropdown does not have leaves it empty.
    """
    by_selector = {f["selector"]: f for f in fields}
    steps_out, filled, refused = [], [], []
    still_asked = []
    for row in out["ask"]:
        selector = row["selector"]
        if selector not in answers:
            still_asked.append(row)
            continue
        field = by_selector.get(selector, {})
        value = answers[selector]
        label = row["label"]
        if row.get("option_selectors"):
            # A multiple-choice question: his answer names one or more of
            # its options, and each named option is ticked. An option that
            # is not on the list is refused rather than approximated —
            # "United States" is not "United Kingdom".
            wanted = ([str(v) for v in value] if isinstance(value, (list, tuple))
                      else [p.strip() for p in str(value).split(",")])
            picked, missing = [], []
            for want in [w for w in wanted if w]:
                match = next((opt for opt in row["option_selectors"]
                              if opt.strip().casefold() == want.casefold()), None)
                if match is None:
                    match = next((opt for opt in row["option_selectors"]
                                  if want.casefold() in opt.casefold()), None)
                (picked.append(match) if match else missing.append(want))
            if missing or not picked:
                row = dict(row, why=(f"{', '.join(missing) or value!r} is not "
                                     "one of its options"))
                refused.append(row)
                still_asked.append(row)
                continue
            for option in picked:
                steps_out.append({"action": "click",
                                  "selector": row["option_selectors"][option]})
            filled.append({"label": label, "value": ", ".join(picked)})
            continue
        if field.get("tag") == "select":
            option = _option_for(field, value)
            if option is None:
                row = dict(row, why=f"{value!r} is not one of its options")
                refused.append(row)
                still_asked.append(row)
                continue
            steps_out.append({"action": "select", "selector": selector,
                              "value": option})
            filled.append({"label": label, "value": option, "selector": selector})
        elif field.get("type") in ("checkbox", "radio"):
            # A checkbox is clicked, never filled — and only when he said
            # yes. "No" on a checkbox means leave it alone, not click it.
            if value is True or str(value).strip().casefold() in (
                    "yes", "true", "1", "on", "checked", "i agree"):
                steps_out.append({"action": "click", "selector": selector})
                filled.append({"label": label, "value": "ticked", "selector": selector})
            else:
                filled.append({"label": label, "value": "left unticked", "selector": selector})
        else:
            steps_out.append({"action": "type", "selector": selector,
                              "value": str(value)})
            filled.append({"label": label, "value": str(value), "selector": selector})
    out["ask"] = still_asked
    return {"steps": steps_out, "filled": filled, "refused": refused}


def steps(filled: list[dict]) -> list[dict]:
    """The plan in `browse.interact`'s grammar — and nothing that submits."""
    return [{"action": s["action"], "selector": s["selector"],
             "value": s["value"]} for s in filled]


# How many frames deep she will look, and how long she will wait for
# one to attach. An <iframe> attaches AFTER domcontentloaded.
MAX_FRAMES = 12
FRAME_WAIT_TRIES = 40


FRAME_RE = re.compile(r"^@frame(\d+)\|(.*)$", re.S)


def frames(page) -> list:
    """The page, and everything embedded in it.

    An application form on a company careers page is very often an
    `<iframe>` — Greenhouse and Lever both ship one as their embed, and
    it is what the "Apply" link on a real site drops you onto. Reading
    only the top document, she stood on such a page and said *"I don't
    see any form fields"* while the whole form sat one frame away. A page
    object without `.frames` (a test double, an older shape) behaves
    exactly as it did before.
    """
    got = getattr(page, "frames", None)
    if not got:
        return [page]
    try:
        return list(got)[:MAX_FRAMES]
    except TypeError:
        return [page]


def tag(index: int, selector: str) -> str:
    """A selector carries the frame it belongs to, or it is ambiguous.

    `#fn` means something different in each frame of a page, and a
    selector that does not say which one is a coin flip at replay time.
    """
    return selector if index == 0 else f"@frame{index}|{selector}"


def holds(frame, css: str) -> bool:
    """Does this frame actually contain that element right now?"""
    finder = getattr(frame, "query_selector", None)
    if finder is None:
        return True                      # a test double: index is the truth
    try:
        return finder(css) is not None
    except Exception:
        return False


def resolve(page, selector: str):
    """(where to do it, what to do it to).

    The frame INDEX is a hint; the element being there is the truth. An
    `<iframe>` attaches after `domcontentloaded` and then navigates, so
    right after a page load frame 1 exists and is still blank — the first
    version typed into it and spent twenty seconds waiting for a field
    that would never appear in that document. Real sites also reorder and
    re-attach frames between the run and the press. So: prefer the
    recorded position, accept any frame that has the element, and wait a
    bounded time for one to.
    """
    match = FRAME_RE.match(str(selector or ""))
    if not match:
        return page, selector
    index, css = int(match.group(1)), match.group(2)
    wait = getattr(page, "wait_for_timeout", None)
    for attempt in range(FRAME_WAIT_TRIES if wait else 1):
        found = frames(page)
        ordered = ([found[index]] if index < len(found) else []) + [
            f for i, f in enumerate(found) if i != index]
        for frame in ordered:
            if holds(frame, css):
                return frame, css
        if wait is None:
            break
        try:
            wait(250)
        except Exception:
            break
    found = frames(page)
    return (found[index] if index < len(found) else page), css




class Hands:
    """Act on a selector wherever it actually lives.

    Playwright's `page.fill` only reaches the top document; a frame has
    the same verbs. This is the one place that knows the difference, so
    every caller — the general web loop and the application filler —
    cannot disagree about it.
    """

    def __init__(self, page):
        self.page = page

    def fill(self, selector, value):
        target, css = resolve(self.page, selector)
        target.fill(css, str(value))

    def select_option(self, selector, value=None, *, label=None):
        target, css = resolve(self.page, selector)
        if label is not None:
            target.select_option(css, label=label)
        else:
            target.select_option(css, value)

    def check(self, selector):
        target, css = resolve(self.page, selector)
        target.check(css)

    def uncheck(self, selector):
        target, css = resolve(self.page, selector)
        target.uncheck(css)

    def set_input_files(self, selector, path):
        target, css = resolve(self.page, selector)
        target.set_input_files(css, path)

    def click(self, selector):
        target, css = resolve(self.page, selector)
        target.click(css)


SETTLE_TRIES = 34              # ~10s for a single-page application to render
SETTLE_MS = 8_000              # and how long to wait for the network to go quiet
NO_FORM_AFTER = 13             # ~4s before 'this page has no form' is believed


def settle(page, *, extra=None, tries: int = SETTLE_TRIES) -> None:
    """Wait for the page to actually BE there.

    `domcontentloaded` fires before a React application has rendered
    anything, and every real applicant tracking system is one. She looked
    at a careers page before its form existed, saw an empty document, and
    the only reason she did not give up was that the model happened to be
    slower than the page — a coincidence, not a design.

    The signal is FIELDS, not "something is on screen". The first version
    returned as soon as the page had any control at all, which a cookie
    banner satisfies on its own: it declared a still-loading page ready
    while the form was two seconds away. A page that genuinely has no
    form — a careers landing page with an Apply link — is let through
    once it has had a fair chance to render one and has stopped changing.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=SETTLE_MS)
    except Exception:
        pass
    wait = getattr(page, "wait_for_timeout", None)
    last, stable = object(), 0
    for round_number in range(tries):
        try:
            if read_all(page):
                return
            mark = page.evaluate(
                "() => (document.body ? document.body.innerHTML.length : 0)")
        except Exception:
            return
        stable = stable + 1 if mark == last else 0
        last = mark
        if (round_number >= NO_FORM_AFTER and stable >= 2
                and (extra is None or extra(page))):
            return
        if wait is None:
            return
        try:
            wait(300)
        except Exception:
            return


def read_all(page) -> list[dict]:
    """Every field on the page, in every frame, each selector frame-tagged."""
    rows: list[dict] = []
    for index, frame in enumerate(frames(page)):
        for script in (READ_FORM_JS, READ_ARIA_JS):
            try:
                got = frame.evaluate(script)
            except Exception:
                continue
            for row in got or []:
                row = dict(row)
                row["selector"] = tag(index, row["selector"])
                if row.get("group", "").startswith("aria:"):
                    row["group"] = f"{row['group']}@{index}"
                rows.append(row)
    return rows


MAX_DROPDOWNS_READ = 20


def read_dropdown_choices(page, fields: list[dict], *, settle_ms: int = 1500) -> None:
    """Open each search-as-you-type dropdown and note what it offers.

    Live 2026-09-10 "How did you first hear about Flexport?" stayed empty with
    the right answer in hand: the model answered in its own words and no
    option in the menu was those words. With the options in front of it, its
    answer is one of them, and the picker clicks exactly that. A menu that
    shows nothing until something is typed (a city search) gets no choices.
    """
    dropdowns = [f for f in fields if f.get("role") == "combobox"]
    dropdowns.sort(key=lambda f: not f.get("required"))
    for field in dropdowns[:MAX_DROPDOWNS_READ]:
        try:
            where, css = resolve(page, field["selector"])
            where.click(css)
            options = _visible_options(where, settle_ms)
            page.keyboard.press("Escape")
        except Exception:
            continue
        if options:
            field["choices"] = options[:80]


def read_form(url: str, *, reader=None) -> list[dict]:
    """Every field on the page, as a person would read it."""
    policy.ensure_not_halted()
    if reader is not None:
        return list(reader(url))
    from aletheia import browse
    ok, why = browse.available()
    if not ok:
        raise FormError(f"she cannot open the form: {why}")
    with browse._Session() as ctx:          # same authorized profile as read_page
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        settle(page)
        found = read_all(page)
        read_dropdown_choices(page, found)
        page.close()
    journal.append("action", "formfill", f"read {speech.count_phrase(len(found), 'field')} on {url}",
                   actor=ACTOR)
    return found


READ_ARIA_JS = r"""() => {
  // The questions the browser knows nothing about. On a modern form the
  // "Yes" you click is a <div role=radio> and the city you pick is an
  // <li role=option>: no id, no name, not an <input>, invisible to
  // `document.querySelectorAll('input, select, textarea')`. Read as one
  // option-per-row so the ordinary grouping folds them into ONE question,
  // exactly like a set of checkboxes.
  const path = (el) => {
    const bits = [];
    for (let n = el; n && n.nodeType === 1 && bits.length < 6; n = n.parentElement) {
      if (n.id) { bits.unshift(`#${CSS.escape(n.id)}`); break; }
      const t = n.tagName.toLowerCase();
      if (t === 'html' || t === 'body') break;
      const kin = n.parentElement
        ? [...n.parentElement.children].filter(c => c.tagName === n.tagName) : [n];
      bits.unshift(kin.length > 1 ? `${t}:nth-of-type(${kin.indexOf(n) + 1})` : t);
    }
    const one = bits.join(' > ');
    try { return one && document.querySelectorAll(one).length === 1 ? one : null; }
    catch (e) { return null; }
  };
  const named = (el) => {
    if (!el) return '';
    const own = el.getAttribute('aria-label');
    if (own) return own.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const n = document.getElementById(by);
      if (n && n.innerText.trim()) return n.innerText.trim();
    }
    return '';
  };
  const out = [];
  let n = 0;
  for (const group of document.querySelectorAll('[role=radiogroup], [role=listbox]')) {
    const question = named(group);
    if (!question) continue;
    const key = `aria:${n++}`;
    const required = group.getAttribute('aria-required') === 'true' || /\*/.test(question);
    for (const opt of group.querySelectorAll('[role=radio], [role=option]')) {
      const selector = path(opt);
      if (!selector) continue;
      out.push({
        selector, tag: 'aria', type: 'radio', name: '', id: '',
        group: key, question: question.slice(0, 110),
        option: (opt.innerText || '').trim().slice(0, 70),
        label: (opt.innerText || '').trim().slice(0, 70),
        required, value: '',
        checked: opt.getAttribute('aria-checked') === 'true'
                 || opt.getAttribute('aria-selected') === 'true',
      });
      if (out.length > 80) return out;
    }
  }
  return out;
}"""


READY_JS = r"""() => {
  // WILL THIS FORM ACTUALLY GO? Two different answers, because forms
  // refuse in two different ways.
  const label = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && l.innerText.trim()) return l.innerText.trim().slice(0, 90);
    }
    const wrap = el.closest('label');
    if (wrap && wrap.innerText.trim()) return wrap.innerText.trim().slice(0, 90);
    return (el.getAttribute('aria-label') || el.name || el.id || '').slice(0, 90);
  };
  const selectorFor = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    if (el.name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
    return '';
  };
  // A styled dropdown's search box has no label of its own - it says
  // "Select..." - and the question is the label in the block above it.
  // Live on Stripe's Greenhouse form 2026-09-10 these came back as three
  // questions called "a field", which he could never have answered.
  const questionAbove = (el) => {
    let box = el.parentElement;
    for (let i = 0; box && i < 6; i++, box = box.parentElement) {
      for (const l of box.querySelectorAll('label, legend')) {
        const text = (l.innerText || '').trim();
        if (text && !l.contains(el) && !l.querySelector('input, select, textarea'))
          return text.split('\n')[0].slice(0, 90);
      }
    }
    return '';
  };
  const invalid = [];
  const groupsAsked = new Set();
  for (const el of document.querySelectorAll('input, select, textarea')) {
    if (typeof el.checkValidity !== 'function') continue;
    if (el.disabled || el.type === 'hidden' || el.checkValidity()) continue;
    if (el.type === 'checkbox' && el.name) {
      // "Which countries?" is thirty required boxes sharing one name, and
      // the browser calls every unticked box invalid even after US is
      // ticked - so the form could never read as ready. One ticked box
      // answers the group; an unanswered group is ONE question.
      const mates = [...document.getElementsByName(el.name)];
      if (mates.length > 1) {
        if (mates.some(m => m.checked) || groupsAsked.has(el.name)) continue;
        groupsAsked.add(el.name);
        invalid.push({label: questionAbove(el) || label(el), name: el.name,
                      selector: selectorFor(el), why: 'pick at least one',
                      options: mates.map(m => label(m)).filter(Boolean).slice(0, 40)});
        if (invalid.length > 20) break;
        continue;
      }
    }
    invalid.push({label: label(el) || questionAbove(el), name: el.name || el.id || '',
                  selector: selectorFor(el),
                  why: (el.validationMessage || 'required').slice(0, 90)});
    if (invalid.length > 20) break;
  }
  // And the ones the browser knows nothing about: a question answered by
  // clicking a div. Required is what a PERSON reads — the asterisk on the
  // question — because these carry no `required` attribute to check.
  const groups = [];
  for (const g of document.querySelectorAll('[role=radiogroup], [role=listbox]')) {
    let question = g.getAttribute('aria-label') || '';
    const by = g.getAttribute('aria-labelledby');
    if (!question && by) {
      const n = document.getElementById(by);
      if (n) question = n.innerText.trim();
    }
    if (!question) {
      // No accessible name at all — a typeahead's dropdown usually has
      // none. Read what a PERSON reads: the first line of the block it
      // sits in, which is where the asterisk lives.
      const box = g.closest('div, section, fieldset, li');
      question = box ? (box.innerText || '').split('\n')[0].trim() : '';
    }
    const must = g.getAttribute('aria-required') === 'true' || /\*/.test(question);
    if (!must) continue;
    if (g.querySelector('[aria-checked="true"], [aria-selected="true"]')) continue;
    if (g.getAttribute('role') === 'listbox') {
      // A typeahead is ANSWERED when its box holds text. Plenty of them
      // never set aria-selected on the option you picked, and a question
      // that can never read as answered is a loop: she clicked the city,
      // was told it was still missing, and clicked it again.
      const box = g.closest('div, section, fieldset, li');
      const combo = box && box.querySelector('[role=combobox], input');
      const open = !g.hidden && !!g.offsetParent;
      // Text in the box with the list still OPEN is a half-made choice:
      // she typed "Austin" and never picked "Austin, TX", so the hidden
      // value the widget sets stayed empty and the form would bounce.
      // Text with the list CLOSED is a choice that was made.
      if (combo && (combo.value || '').trim() && !open) continue;
    }
    groups.push({question: question.slice(0, 110),
                 options: [...g.querySelectorAll('[role=radio], [role=option]')]
                            .map(o => (o.innerText || '').trim().slice(0, 60))
                            .slice(0, 12)});
    if (groups.length > 10) break;
  }
  return {invalid, groups};
}"""


def blocking(page) -> list[dict]:
    """What will stop this form going, in every frame.

    Staging used to end at "I typed everything I could" and call that
    ready. On a form whose work-authorization question is a pair of divs,
    that produced an application AWAITING HIS CONFIRMATION that the
    browser would then silently refuse to send — he taps Approve, submit
    is pressed, nothing arrives, and the run reports success. A form that
    cannot go is a QUESTION, not a pending approval.
    """
    out: list[dict] = []
    for index, frame in enumerate(frames(page)):
        try:
            got = frame.evaluate(READY_JS)
            invalid = list(got.get("invalid") or [])
            groups = list(got.get("groups") or [])
        except Exception:
            continue
        for row in invalid:
            item = {"label": row.get("label") or row.get("name") or "a field",
                    "why": row.get("why", "required"), "required": True}
            # Tagged the way `read_all` tags them, so his answer to a question
            # the page itself raised lands on the field that raised it.
            if row.get("selector"):
                item["selector"] = tag(index, row["selector"])
            if row.get("options"):
                item["options"] = list(row["options"])
            out.append(item)
        for row in groups:
            out.append({"label": row.get("question") or "a required choice",
                        "why": "nothing is selected", "required": True,
                        "options": row.get("options") or []})
    return out


# ---- search-as-you-type dropdowns -----------------------------------------------
#
# Greenhouse's current forms, and most React forms: Country, City, School,
# Degree and every yes/no question are an <input role=combobox> whose menu
# of [role=option] exists only while it is open. Typing the answer and moving
# on chooses NOTHING - the widget throws the text away - and live 2026-09-10
# a Stripe form she had "filled" still had nine required answers empty.

COMBOBOX_JS = r"""(css) => {
  const el = document.querySelector(css);
  return !!el && (el.getAttribute('role') === 'combobox'
                  || el.getAttribute('aria-autocomplete') === 'list');
}"""
VISIBLE_OPTIONS_JS = r"""() => [...document.querySelectorAll('[role=option]')]
  .filter(o => o.offsetParent !== null)
  .map(o => (o.innerText || '').trim()).filter(Boolean).slice(0, 400)"""
# The VISIBLE option whose text is exactly the choice. A text-contains match
# found "No" inside a hidden option left over from another menu and waited
# thirty seconds to click something that could not be clicked.
FIND_OPTION_JS = r"""(text) => [...document.querySelectorAll('[role=option]')]
  .find(o => o.offsetParent !== null && (o.innerText || '').trim() === text) || null"""

US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
# One country, several names. Only names that cannot mean anything else.
_SAME_COUNTRY = (
    frozenset({"united states", "united states of america", "usa", "u s a", "us", "u s"}),
    frozenset({"united kingdom", "uk", "u k", "great britain"}),
)


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).strip()


def _degree_level(value) -> str:
    """"B.B.A." is a bachelor's degree; the list says "Bachelor's Degree"."""
    v = _norm(value)
    flat = v.replace(" ", "")
    if v.startswith("bachelor") or re.fullmatch(r"b(a|s|ba|bs|sc|fa|eng|arch|ed)", flat):
        return "bachelor"
    if v.startswith("master") or re.fullmatch(r"m(a|s|ba|sc|fa|eng|ed|pa|ph)", flat):
        return "master"
    if v.startswith("associate") or re.fullmatch(r"a(a|s|as)", flat):
        return "associate"
    if v.startswith(("doctor", "phd")) or flat in ("phd", "md", "jd", "edd"):
        return "doctor"
    return ""


def _best_option(value, options: list[str], known: dict | None = None) -> str | None:
    """The one option that IS the answer, or None. Never a guess between two."""
    known = known or {}
    v = _norm(value)
    if not v or not options:
        return None
    normed = [(o, _norm(o)) for o in options]
    wants = {v}
    for same in _SAME_COUNTRY:
        if v in same:
            wants |= same
    exact = [o for o, n in normed if n in wants]
    if exact:
        return exact[0]
    # "United States +1": the answer, then something that is not another answer.
    lead = [o for o, n in normed if any(n.startswith(w + " ") for w in wants)]
    if len(lead) == 1:
        return lead[0]
    # A place: the city he lives in, in the state he lives in.
    state = str(known.get("state") or "").strip().upper()
    in_state = {_norm(state), _norm(US_STATE_NAMES.get(state, ""))} - {""}
    if in_state:
        placed = [o for o, n in normed
                  if _says(v, n) and any(_says(s, n) for s in in_state)]
        if len(placed) == 1:
            return placed[0]
    level = _degree_level(value)
    if level:
        by_level = [o for o, n in normed if _says(level, n)]
        if len(by_level) == 1:
            return by_level[0]
        plain = [o for o in by_level if not _says("of", _norm(o))]
        if len(plain) == 1:
            return plain[0]
    words = [o for o, n in normed if _says(v, n)]
    return words[0] if len(words) == 1 else None


def is_combobox(page, selector: str) -> bool:
    try:
        where, css = resolve(page, selector)
        return bool(where.evaluate(COMBOBOX_JS, css))
    except Exception:
        return False                      # a test double, or no such element


def _visible_options(where, settle_ms: int) -> list[str]:
    wait = getattr(where, "wait_for_timeout", None)
    seen: list[str] = []
    for _ in range(max(1, settle_ms // 250)):
        try:
            seen = list(where.evaluate(VISIBLE_OPTIONS_JS) or [])
        except Exception:
            return []
        if seen:
            if wait:
                wait(300)                 # a menu that fetches is still arriving
                try:
                    seen = list(where.evaluate(VISIBLE_OPTIONS_JS) or seen)
                except Exception:
                    pass
            return seen
        if wait:
            wait(250)
    return seen


def pick_option(page, selector: str, value, *, known: dict | None = None,
                settle_ms: int = 2500) -> str:
    """Choose `value` in a search-as-you-type dropdown.

    Returns the option clicked, or "" when no option clearly is the answer.
    Then it stays empty, and the page's own verdict (`blocking`) makes it a
    question for him instead of a wrong answer in his name.
    """
    known = profile.known() if known is None else known
    value = str(value or "").strip()
    if not value:
        return ""
    where, css = resolve(page, selector)
    queries = [value]
    state = str(known.get("state") or "").strip().upper()
    if state and _norm(value) == _norm(known.get("city")):
        # "Hartford" offered Connecticut, Wisconsin and Vermont, not his.
        queries.append(f"{value}, {US_STATE_NAMES.get(state, state)}")
    queries.append("")                    # the whole list: "B.B.A." vs "Bachelor's Degree"
    for query in queries:
        try:
            where.click(css)
            where.fill(css, query)
        except Exception:
            return ""
        choice = _best_option(value, _visible_options(where, settle_ms), known)
        if not choice:
            continue
        try:
            element = where.evaluate_handle(FIND_OPTION_JS, choice).as_element()
            if element is not None:
                element.click(timeout=5000)
                return choice
        except Exception:
            continue
    try:
        where.fill(css, "")
        page.keyboard.press("Escape")
    except Exception:
        pass
    return ""


def survey(url: str, *, reader=None) -> dict:
    """Read a form and say what she could fill and what she must ask."""
    fields = read_form(url, reader=reader)
    out = plan(fields)
    out["url"] = url
    out["fields_found"] = len(fields)
    return out


def spoken(out: dict) -> str:
    fill, ask = len(out["fill"]), len(out["ask"])
    required_asks = sum(1 for a in out["ask"] if a["required"])
    said = f"{speech.count_phrase(out['fields_found'], 'field')} on that form. She can fill {fill}"
    if ask:
        said += (f" and needs you for {ask}"
                 + (f" ({required_asks} of them required)" if required_asks else ""))
    said += ". Nothing is filled or submitted until you say so."
    return said


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read a form: what she can fill, what she must ask.")
    ap.add_argument("url")
    args = ap.parse_args(argv)
    try:
        out = survey(args.url)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(spoken(out))
    print(json.dumps({"fill": [{k: v for k, v in f.items() if k != "value"}
                               for f in out["fill"]],
                      "ask": out["ask"], "skipped": out["skipped"]},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
