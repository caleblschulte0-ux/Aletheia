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
WIDGET_SELECTORS = ("#iti-", "#g-recaptcha-response", "#recaptcha",
                    # hCaptcha's hidden response field, which reached him
                    # twice on one Nitra form as "a written answer, not a
                    # fact she has on file". Nobody asked him anything.
                    "#h-captcha-response", "#hcaptcha")


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
    // The question block this one control lives in, before its placeholder.
    // Lever's custom questions ("cards[<uuid>][field0]") have no <label for>
    // and no fieldset: the question is a div.application-label beside the
    // control. Live 2026-09-13 Shield AI's went to him as "Type your
    // response" (the placeholder) and as the bare field name.
    const own = ownQuestion(el);
    if (own) return own;
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
    return ownQuestion(el);
  };
  // The heading of the smallest block that holds this question and no other.
  // Climbing stops the moment a block holds a DIFFERENT control, so a
  // fieldset's legend ("About you") never becomes the label of the seven
  // boxes inside it. An option's own text - inside a <label>, or inside the
  // list of options - is never the question.
  const ownQuestion = (el) => {
    const list = el.closest('ul, ol');
    for (let box = el.parentElement, up = 0; box && up < 7; box = box.parentElement, up++) {
      const controls = [...box.querySelectorAll('input:not([type="hidden"]), select, textarea')];
      if (new Set(controls.map(c => c.name || c.id || c)).size > 1) return '';
      for (const h of box.querySelectorAll(
             '.application-label, legend, [class*="question-label"], [class*="label"], h3, h4')) {
        if (h.contains(el) || h.closest('label') || h.querySelector('input, select, textarea')) continue;
        if (list && box.contains(list) && list !== box && list.contains(h)) continue;
        const t = (h.innerText || '').trim();
        if (t && /[a-z]/i.test(t)) return t.slice(0, 160);
      }
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
      // ...except where they do NOT. Spotify gives every option in a survey
      // its own name — surveysResponses[uuid][field0], [field1], [field2] —
      // so each radio became a group of one, which is demoted back to a
      // standalone field labelled with its only option. Live 2026-09-13 that
      // put twelve questions in front of him reading "Woman", "He/him", "EN",
      // "Any other ethnic group": every one an OPTION wearing a question's
      // clothes, and four of them things he had already answered.
      //
      // When a name is unique to one control, fall back to the nearest
      // container that holds several of them. Named groups are untouched, so
      // Greenhouse (whose radios genuinely share a name) is unaffected.
      // CLIMB to the container that holds the other options. `closest` on a
      // list of likely selectors finds the per-option <li>, which holds one
      // input — so the first version of this never fired at all, and the
      // test said so.
      let holder = null;
      for (let box = el.parentElement, up = 0; box && up < 6;
           box = box.parentElement, up++) {
        const kin = box.querySelectorAll(`input[type="${type}"]`);
        if (kin.length <= 1) continue;
        // Only when this control's own name is unique among them. A group
        // that names itself properly (Greenhouse) is already grouped by the
        // line above and must not be touched: this may only ever ADD.
        if ([...kin].filter(k => k.name === el.name).length === 1) holder = box;
        break;
      }
      if (holder) {
        if (!row.question) {
          // The heading can sit OUTSIDE the list that holds the options —
          // Spotify renders `div.field > div.label` followed by `ul > li >
          // input` — so the parent is searched too. Anything inside an <li>
          // or a <label> is an option's own text, never the question.
          for (const scope of [holder, holder.parentElement]) {
            if (!scope) continue;
            for (const h of scope.querySelectorAll(
                   'legend, .label, [class*="label"], h1, h2, h3, h4')) {
              if (h.closest('li') || h.tagName === 'LABEL') continue;
              const t = (h.innerText || '').trim();
              if (t) { row.question = t.slice(0, 110); break; }
            }
            if (row.question) break;
          }
        }
        row.group = row.question
          || ('box:' + (el.name || '').replace(/\d+\]?\]?$/, ''));
      }
    }
    if (tag === 'select') {
      row.options = Array.from(el.options)
        .map(o => ({value: o.value, text: (o.text || '').trim()}))
        // EVERY option. Palantir's university list has 3,302 and ends with
        // "Other - School Not Listed"; cut at 60 it held neither his school
        // nor the one it tells him to pick without it. What reaches a model
        // or a saved record is bounded in Python (bounded_choices), not here.
        .filter(o => o.value !== '');
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
    # ("Sex", "Are you Hispanic/Latino?") is still one - and so is one whose
    # QUESTION says nothing at all and whose options say everything.
    return bool(category_of(str(field.get("label") or ""), _choice_texts(field)))


def _choice_texts(field: dict) -> list[str]:
    if field.get("choices"):
        return [str(c) for c in field["choices"]]
    return [str(o.get("text") or o.get("label") or "") for o in field.get("options") or []
            if isinstance(o, dict)]


_ORIENTATION_OPTIONS = ("transgender", "cisgender", "heterosexual", "straight",
                        "bisexual", "gay", "lesbian", "asexual", "pansexual", "queer")
_RACE_OPTIONS = ("american indian", "alaska native", "asian", "black", "african american",
                 "white", "native hawaiian", "pacific islander", "two or more races",
                 "hispanic or latino", "middle eastern")
_GENDER_OPTIONS = ("man", "woman", "male", "female", "non binary", "nonbinary")


def category_of(label: str, choices: list[str] | None = None) -> str:
    """The self-identification category a question asks about, from its words
    or - when its words say nothing - from its options.

    Live 2026-09-13: Chime asked "I identify as:*" over Cisgender /
    Transgender / I prefer to self-describe / I don't wish to answer, and
    LeafLink asked "Please take a moment to self identify" over a list of
    races. Neither label names a category, so neither was recognised as
    protected: both went to him as "she could not tell what this is asking
    for", with his own answers (decline; White) on file since the 12th.
    The label still wins wherever it speaks.
    """
    category = _declared_category(label)
    if category or not choices:
        return category
    normed = [_norm(c) for c in choices if str(c).strip()]
    gendered = any(n in _GENDER_OPTIONS or n.split()[:1] in (["man"], ["woman"])
                   for n in normed)
    # A self-identification list is short and mostly made of the category.
    # Read WHOLE, Palantir's 3,302 universities hold "Asian Institute of
    # Technology" and "Black Hills State University", and three names in a
    # long list must not turn "which university" into a protected question.
    if not gendered and len(normed) <= 40 and \
            any(_says(w, n) for n in normed for w in _ORIENTATION_OPTIONS):
        return "self_id_decline"
    races = sum(1 for n in normed if any(_says(w, n) for w in _RACE_OPTIONS))
    if races >= 3 and races * 2 >= len(normed):
        return "race"
    return ""


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
                           "willing_to_relocate", "over_18"})

# A sentence he would SAY about himself is not asking for a contact fact,
# whatever noun it happens to contain. Live 2026-09-13: Elastic's "I have
# experience picking up the PHONE and calling new leads" got his phone
# number, and "I'm willing and able to commute by my START DATE to the Austin
# area" got his notice period. Both went into dropdowns with no such option,
# chose nothing, and stopped the application on a question she had answered.
_ABOUT_HIMSELF = re.compile(r"^[^a-z0-9]*(?:i|i'm|i’m|i am|i have|i've)\b")
_CONTACT_FIELDS = frozenset({
    "legal_name", "first_name", "last_name", "preferred_name", "email", "phone",
    "street", "city", "state", "postal_code", "country", "linkedin", "github",
    "website", "twitter", "notice_period", "current_title", "current_employer"})
_NAME_FIELDS = frozenset({"legal_name", "first_name", "last_name", "preferred_name"})
# "Start date month" and "End date year" are the dates of a JOB on his work
# history (Coinbase, Dropbox, Impact.com), not when he could start a new one.
_EMPLOYMENT_DATE = re.compile(
    r"\b(?:start|end)(?:ing)?\s+date\s+(?:month|year)\b|\b(?:start|end)\s+(?:month|year)\b")
# "In what CITIES are you available to work?" and "In what COUNTRIES do you
# have the unrestricted right to work?" ask WHICH places, plural: not the city
# he lives in (Datadog got "Hartford") and not a yes (Elastic got "Yes").
#
# "United States" is one place, not a plural, and "authorized to work in the
# United States" must still reach his yes - hence the lookbehind.
_WHICH_PLACES = re.compile(
    r"\b(?:cities|countries|(?<!united )states|locations|regions|offices)\b"
    r"|\bavailable to work\b|\bwilling to work\b")
_WHICH_COUNTRIES = re.compile(r"\b(?:cities|countries|locations)\b")
_WHICH_AI_TOOL = re.compile(
    r"^[^a-z0-9]*(?:what|which)\s+(?:ai|a\.i\.|llm|large language|generative)"
    r"|\b(?:most familiar with|use most|prefer to use)\b")


def _says(phrase: str, text: str) -> bool:
    """The phrase as words: "city" is not in "capacity"."""
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])",
                     text) is not None


def _clean_label(label) -> str:
    """A label without the marks forms hang on it.

    Lever ends a required question with a newline and "✱" ("Current
    location\\n✱"), Greenhouse with "*", some with "(required)". Anything that
    compares a label - an anchored pattern, a stored answer, an exact choice -
    reads the question, not the decoration.
    """
    text = " ".join(str(label or "").split())
    return re.sub(r"(?:\s*(?:[*✱✳✻⁎]|\(required\)))+\s*$", "", text, flags=re.I).strip()


#: A job-alert signup beside an application ("Select how often (in days) to
#: receive an alert:" on Grainger, live 2026-09-13). It asks nothing about him.
_ALERT_WIDGET = re.compile(
    r"\b(?:receive|get|send|email)\b[^.?]{0,40}\b(?:job\s+)?alerts?\b|\bjob alerts?\b"
    r"|\balert (?:frequency|me)\b|\bhow often\b[^.?]{0,40}\balerts?\b", re.I)
#: Consent to be texted or messaged. ANSWER_BRIEF already says those are No,
#: but a form read with no model gave Epic's "SMS Consent: Do you agree to
#: receive mobile (text) messages..." his phone number instead.
_MESSAGE_OPT_IN = re.compile(
    r"\b(?:sms|text messages?|text messaging|whatsapp)\b|\(text\) messages?", re.I)
_PLAIN_NO = ("no", "no thanks", "no thank you", "i do not agree", "i don t agree",
             "do not agree", "decline")
#: "Other (School Not Listed)", the option a list tells him to pick when his
#: school is not on it.
_OTHER_NOT_LISTED = re.compile(r"\bother\b.*\bnot listed\b|\bnot listed\b.*\bother\b")

#: How many of a list's options travel in a saved question or a model's
#: context. The FIELD keeps every one, and matching reads the field.
MAX_CHOICES_KEPT = 80
#: Options kept whatever the cut: the one a list offers when the answer is not
#: on it, and the ones that decline.
_ESCAPE_OPTION = re.compile(r"\bother\b|\bnot listed\b|\bnone\b|\bdid not\b|\bprefer not\b"
                            r"|\bdecline\b|\bnot applicable\b|\bdo not wish\b|\bdon t wish\b")


def option_texts(field: dict) -> list[str]:
    """Every option a field offers, as words.

    A typeahead keeps what its open menu showed under `choices`; a <select>
    keeps its own under `options`, and its placeholder ("Select...", value "")
    is not an option."""
    if field.get("choices"):
        return [str(c).strip() for c in field["choices"] if str(c).strip()]
    return [str(o.get("text") or "").strip() for o in field.get("options") or []
            if isinstance(o, dict) and str(o.get("text") or "").strip()
            and str(o.get("value") or "").strip()]


def bounded_choices(options, *, known: dict | None = None,
                    limit: int = MAX_CHOICES_KEPT) -> list[str]:
    """A long list cut to what a question can carry, in the list's own order.

    Live 2026-09-13 Palantir's university list had 3,302 options and was read
    as its first 60: his school was not among them and neither was "Other -
    School Not Listed", so the one question his profile answers went to him.
    Cutting is right for a saved record and a model's context; cutting blindly
    is not. Kept first: an option that names a fact of his, and an option a
    list offers when the answer is not on it. The head of the list fills the
    rest.
    """
    options = [str(o).strip() for o in options or [] if str(o).strip()]
    if len(options) <= limit:
        return options
    facts = [re.compile(r"(?<![a-z0-9])" + re.escape(f) + r"(?![a-z0-9])")
             for f in {_norm(v) for v in (known or {}).values() if isinstance(v, str)}
             if 3 < len(f) <= 80]
    keep: set[int] = set()
    for i, option in enumerate(options):
        if len(keep) >= limit:
            break
        n = _norm(option)
        if _ESCAPE_OPTION.search(n) or any(p.search(n) for p in facts):
            keep.add(i)
    for i in range(len(options)):
        if len(keep) >= limit:
            break
        keep.add(i)
    return [options[i] for i in sorted(keep)]


#: A list he would be joining, not a job he would be applying for.
_LIST_SIGNUP = re.compile(
    r"\btalent (?:network|community|pool)\b|\bjob alerts?\b|\balerts?\b|\bsubscri\w*"
    r"|\bnewsletter\b|\b(?:areas?|fields?) of interest\b|\binterests\b|\bcategor(?:y|ies)\b",
    re.I)
_CONFIRM_EMAIL = re.compile(
    r"\b(?:confirm|verify|re-?enter|repeat)\w*\s*(?:your\s+)?e-?mail|\bconfirmemail\b", re.I)
#: What only an application asks. Deliberately not "address": every signup
#: has an "Email Address".
_APPLICATION_ONLY = re.compile(
    r"\bphone\b|\blinkedin\b|\bcover letter\b|\bauthori[sz]\w*|\bsponsor\w*|\bhow did you hear\b"
    r"|\bsalary\b|\bcompensation\b|\bstreet\b|\baddress line\b|\bwebsite\b|\bportfolio\b"
    r"|\bdegree\b|\buniversity\b|\bschool\b|\bemployer\b|\bgender\b|\bdisabilit\w*|\bveteran\b",
    re.I)
_RESUME_WORDS = re.compile(r"\bresume\b|\bcv\b|\bcurriculum\b|r[ée]sum[ée]", re.I)


def is_signup_list(fields: list[dict]) -> bool:
    """A talent-network or job-alert signup, not an application.

    Live 2026-09-13 Spectrum's posting page carried "Sign up for job alerts"
    twice - First Name, Last Name, Email Address, Confirm Email, a Job
    Category list, a Location list, "Are you a member of the military
    community?", "Spectrum employee" and an optional resume upload - and it was
    staged as the application for "National Account Manager, Federal
    Government". The campaign's own check was defeated by "first name".

    A resume upload he MUST give, or any question only an application asks
    (phone, LinkedIn, work authorization, a school, how he heard), means an
    application, always. Otherwise a list shows itself by what it asks: an
    area of interest or a job category, alerts, a subscription, a talent
    network - and, where it offers a resume at all, a confirm-email box.
    """
    rows = [f for f in fields or [] if isinstance(f, dict)
            and f.get("type") not in ("hidden", "submit", "button", "image", "reset")]
    if not rows:
        return False

    def hay(f):
        return " ".join(str(f.get(k) or "") for k in ("label", "question", "name", "id"))

    resumes = [f for f in rows if f.get("type") == "file" and _RESUME_WORDS.search(hay(f))]
    for f in resumes:
        label = str(f.get("label") or "")
        marked = bool(f.get("required")) or re.search(r"[*✱]|\brequired\b", label, re.I)
        if marked and not re.search(r"\boptional\b", label, re.I):
            return False
    if any(_APPLICATION_ONLY.search(hay(f)) for f in rows):
        return False
    listed = any(_LIST_SIGNUP.search(hay(f)) for f in rows)
    confirm = any(_CONFIRM_EMAIL.search(hay(f)) for f in rows)
    return (listed and confirm) if resumes else (listed or confirm)
_VOLUNTARY_SELF_ID = re.compile(r"\bi identify as\b|\bself[- ]identif", re.I)


def voluntary_decline(label, choices, *, stored: dict | None = None) -> str | None:
    """A voluntary self-identification question's decline option, when HE has
    said he declines self-identification - or None.

    Never a fact about him: only the option that declines, only when his own
    decline is on file, and only for a question that asks him to identify
    himself. A stored answer to the exact question ("first-generation
    professional: No") is read before this and wins.
    """
    if not _VOLUNTARY_SELF_ID.search(str(label or "")):
        return None
    stored = profile.load() if stored is None else stored
    if not _his_word(stored, "self_id_decline"):
        return None
    return _decline_choice([str(c) for c in choices or [] if str(c).strip()])


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
    label = _clean_label(field.get("label")).casefold()
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
        # A signup-only fact never reaches an employer. His Google Voice
        # number exists so an ACCOUNT can be made; an application carries
        # his real number. The field also has no `asks` phrases, so this is
        # the second of two locks, not the only one.
        if key in profile.SIGNUP_ONLY:
            continue
        if yes_no and key not in YES_NO_FIELDS:
            continue
        # "Years of experience IN sales operations" is not his total years:
        # live it got 6, counting six years of construction.
        if key == "years_experience" and re.search(
                r"experience\b.*\b(?:in|with|as|doing|using|on|at)\b", label):
            continue
        # Nor is "years of CLIENT FACING experience" (AlphaSense): a kind of
        # experience is counted from the resume, not his total seven years.
        if key == "years_experience" and re.search(
                r"\byears?\s+of\s+(?!(?:total|professional|work|relevant|full[- ]time|overall|paid)\b)"
                r"[a-z0-9-]+(?:\s+[a-z0-9-]+){0,3}\s+experience\b", label):
            continue
        # "Please state the employee's name" is the verb: live it got "SD".
        if key == "state" and re.search(
                r"\bstate\s+(?:the|your|a|an|any|why|how|what|which|who|if|whether)\b", label):
            continue
        if key in _CONTACT_FIELDS and _ABOUT_HIMSELF.match(label):
            continue
        # "What is your legal MIDDLE name?" got "Caleb Schulte" on Tebra.
        if key in _NAME_FIELDS and _says("middle", label):
            continue
        if key == "notice_period" and _EMPLOYMENT_DATE.search(label):
            continue
        if key in ("city", "state", "country") and _WHICH_PLACES.search(label):
            continue
        if key == "work_authorization" and _WHICH_COUNTRIES.search(label):
            continue
        # The TOOLS he uses answer "What AI tool are you most familiar with?"
        # and nothing else: not "do you ask an AI tool for input" (a yes), not
        # "which of the following best describes how you use AI tools" (one of
        # its options), and never an essay about how he works.
        if key == "ai_tools" and not _WHICH_AI_TOOL.search(label):
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
    # A <select> gets the same reading a typeahead does: "SD" is "South
    # Dakota", and his pay lands in the one range that holds it.
    best = _best_option(value, [o["text"] for o in options])
    if best is not None:
        return next(o["value"] for o in options if o["text"] == best)
    return None


def _stand_in_option(field: dict, label: str, value) -> str | None:
    """The option a list itself offers when the answer given is not on it, or None.

    Two, and nothing else is approximated. Palantir's record held "Palantir's
    careers page" for "how did you hear" - a model's words, written when it
    was shown no options - and the list says "Palantir Website". And a school
    list tells him to pick "Other - School Not Listed" when his is not on it.
    """
    options = [o for o in field.get("options") or [] if str(o.get("value") or "").strip()]
    texts = [str(o.get("text") or "") for o in options]
    key = match_field({"label": label})
    said = None
    if key == "heard_about" and re.search(r"career|company|website|search|online|google"
                                          r"|job board", _norm(value)):
        said = heard_about_answer(str(value), texts)
    elif key == "school" or _OTHER_NOT_LISTED.search(_norm(label)):
        said = next((t for t in texts if _OTHER_NOT_LISTED.search(_norm(t))), None)
    if said is None:
        return None
    return next((o["value"] for o in options if o.get("text") == said), None)


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

#: Why an optional box she has no fact for is skipped rather than asked.
#: Said the way he would say it, because it is read out and it appears in
#: the confirmation he scans before anything is sent.
_LEAVE_IT_BLANK = "optional, and nothing on file to put in it — left blank"

#: The fields where HAVING NOTHING IS THE ANSWER. He does not have a
#: Twitter or a personal site; an optional box asking for one is complete
#: when it is empty, so stopping on it asks him to come back and type
#: nothing. Everything else that is optional and unanswered still reaches
#: him: "Desired salary" sits in an optional box on plenty of forms and is
#: a real question, and the difference between "he has no value for this"
#: and "she could not work out what this is" is the whole distinction.
_BLANK_IS_AN_ANSWER = frozenset({"website", "twitter", "github", "linkedin"})
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


def declared_choice(label: str, choices: list[str], *, stored: dict | None = None,
                    category: str = "") -> str | None:
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
    category = category or category_of(label, choices)
    if not category:
        return None
    stored = profile.load() if stored is None else stored
    options = [str(c) for c in (choices or []) if str(c).strip()]
    if not options:
        # Nothing to choose between. For every other category that means
        # there is nothing to click and the question is his — but a pronoun
        # box is routinely free TEXT: Spotify's "Write here..." beside its
        # Custom checkbox, Asana's '[Optional, if "other" is selected above]
        # My pronouns are'. He told her "he/him/his"; typing it is the whole
        # job. I first wrote this inside the pronouns branch below, where
        # this guard had already returned None — dead code, and the case
        # stayed broken while the test said FAIL.
        if category == "pronouns":
            # His OWN words, not the normalised form. `_his_word` lowercases
            # and strips punctuation for matching, which turns "he/him/his"
            # into "he him his" — fine for comparing against options, wrong
            # for typing into an employer's box. Anything a person will read
            # comes out of the store as he wrote it.
            row = stored.get("pronouns")
            said = (row or {}).get("value") if isinstance(row, dict) else None
            return str(said).strip() or None if said else None
        return None
    if category == "self_id_decline":
        # He has to have SAID he declines; silence is still silence.
        return _decline_choice(options) if _his_word(stored, "self_id_decline") else None
    if category == "pronouns":
        said = _his_word(stored, "pronouns")
        if not said:
            return None
        if not options:
            # A free-text pronoun box — Spotify's "Write here..." beside its
            # Custom checkbox, Asana's '[Optional, if "other" is selected
            # above] My pronouns are'. There is nothing to choose between,
            # and he has told her the answer: type it. Returning None here
            # sent a question back to him whose answer was on file.
            return said
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
        # "No military service" is how Robinhood and Reddit word the answer
        # he already gave, and it contains neither "not" nor "veteran" — so
        # the chooser below found nothing and the question reached him with
        # his own answer sitting on file. Live 2026-09-13.
        # One question asked in two vocabularies, and the answer is the same
        # answer. Greenhouse asks "Protected Veteran Status" and offers "I am
        # not a protected veteran"; Robinhood asks "What is your military
        # status?" and offers "No military service". This was two branches,
        # each testing HIS wording and then searching only for options in its
        # own dialect — so neither could see the other's. Live 2026-09-13,
        # with "I am not a protected veteran" sitting on file since the 12th,
        # Robinhood returned None: his word took the second branch ("not a"),
        # which looked for `not ... veteran`, found nothing among "No military
        # service / Veteran / Active duty", and RETURNED rather than falling
        # through to the branch that knew the words.
        #
        # What matters is settled once: he said no. Then read every negative
        # phrasing of it.
        if (said in _SAID_NO or "no military" in said or "never served" in said
                or "not a" in said or "not protected" in said):
            # WHAT is negated, not merely that something is. Asana offers
            # "I am not a veteran (I did not serve in the military)" AND
            # "I am a veteran and I do NOT belong to a classification of
            # protected veterans" - both contain "not", and only the first
            # says he is not one. Live 2026-09-12 a bare "not" matched both
            # and answered neither. `\bno\b` does not match "not", so the
            # first alternative cannot reach the trap option either.
            # And never an option that says he IS one. Twilio offers "I am not
            # a protected veteran" beside "I identify as a veteran but not a
            # protected veteran" - both contain "not a protected veteran", so
            # the pattern matched two and answered neither (live 2026-09-13).
            # Robinhood words his answer "I have never served in the military",
            # which the pattern did not know at all.
            says_he_is = re.compile(r"\b(?:identify as|am)\s+(?:a|an)\s+(?:\w+\s+)?veteran\b"
                                    r"|\bactive duty\b|\bnational guard\b|\breserv")
            hits = [c for c in real
                    if re.search(r"\bno\b[^.]{0,20}\b(?:military|service|served)\b"
                                 r"|\bnot\b[^.]{0,20}\b(?:a |an )?(?:protected\s+)?veteran\b"
                                 r"|\bdid not serve\b|\bnever\s+(?:served|been in)\b",
                                 _norm(c))
                    and not says_he_is.search(_norm(c))]
            if len(hits) == 1:
                return hits[0]
            # "Are you a protected veteran? Yes / No." The negative is the
            # whole option, with nothing to negate and no dialect to read.
            bare = [c for c in real if _norm(c) in _SAID_NO]
            return bare[0] if len(bare) == 1 and len(real) <= 3 else None
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
            if not hits:
                # "Do you have a disability or chronic condition? Yes / No."
                # The negation IS the option, with no noun to negate, so a
                # pattern requiring the word "disabilit" in the answer finds
                # nothing. Live 2026-09-13 this was fourteen blocked
                # questions across Vercel, Tebra, Gusto and Coinbase, with
                # his "No" on file since the 12th. Same shape as the veteran
                # dialect fix, one category over.
                hits = [c for c in real if _norm(c) in _SAID_NO]
                if len(real) > 3:
                    hits = []          # a long list means the bare word is
                    #                    one of several, not the answer
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
            # One category, two words for it. LeafLink lists "Caucasian"
            # where he said "White" (live 2026-09-13), and the list had no
            # option with his word in it at all.
            names = (race,) + {"white": ("caucasian",)}.get(race, ())
            hits = [c for c in options if any(_says(n, _norm(c)) for n in names)
                    and not _says("two", _norm(c))]
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


# Where she found a job, said the ways forms offer it. `found_on` is the
# campaign's own words for it: "the company's own careers page" or "a web
# search". True of that one job, so it is never stored as a fact about him.
_CAREERS_WORDS = ("careers page", "career page", "careers site", "career site",
                  "company website", "company site", "our website", "website",
                  "careers", "company careers")


def _options_named(told: str, options: list[str]) -> list[str]:
    """The options his earlier answer names, exactly - all of them, or none.

    "U.S. citizen" ticks "U.S. citizen". A part of his answer that is not an
    option means the question is not the one he answered, so nothing is
    ticked rather than the parts that happen to match."""
    parts = [p.strip() for p in re.split(r"[;,]", str(told or "")) if p.strip()]
    if not parts:
        return []
    by_text = {str(o).strip().casefold(): o for o in options}
    named = [by_text.get(p.casefold()) for p in parts]
    return [] if None in named else list(dict.fromkeys(named))


_SEARCH_WORDS = ("online search", "web search", "internet search", "search engine",
                 "google", "job board", "online job board", "internet", "online")


def heard_about_answer(found_on: str, choices: list[str] | None = None, *,
                       company: str = "") -> str | None:
    """The truthful answer to "how did you hear about this job", or None.

    Live 2026-09-13 it stopped Brex, Gusto, Samsara, Affirm and Grüns - and
    she knew the answer on every one, because she is how he heard: she found
    the posting herself. `ANSWER_BRIEF` already told the model so, but a form
    read with no model available, or a checkbox list the model never saw,
    still went to him. With options, only one that plainly says where she
    found it; never a person, a referral, an event or a social network.
    """
    where = _norm(found_on)
    if not where:
        return None
    careers = "career" in where or "company" in where or "website" in where
    words = _CAREERS_WORDS if careers else _SEARCH_WORDS
    options = [str(c) for c in (choices or []) if str(c).strip()]
    if not options:
        return "The company's careers page" if careers else "An online job search"
    for word in words:                     # most specific wording first
        hits = [c for c in options if _says(word, _norm(c))
                and not re.search(r"\b(?:referr|employee|friend|recruiter|event|linkedin"
                                  r"|glassdoor|indeed|facebook|instagram|twitter|podcast)",
                                  _norm(c))]
        if len(hits) > 1 and _norm(company):
            # "Palantir Website" beside another site's: the employer's own.
            hits = [c for c in hits if _says(_norm(company), _norm(c))]
        if len(hits) == 1:
            return hits[0]
    # No option names where she found it, and the list has a plain "Other":
    # that is the true one. Never a person, an event or a network.
    others = [c for c in options if _norm(c) == "other"]
    return others[0] if len(others) == 1 else None


_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|K)?")


def _amounts(text: str) -> list[float]:
    out = []
    for number, thousands in _MONEY.findall(str(text or "")):
        value = float(number.replace(",", ""))
        if thousands:
            value *= 1000
        out.append(value)
    return out


def _money_choice(value, options: list[str]) -> str | None:
    """The one pay range that holds the figure he gave, or None.

    His answer is "$100,000 minimum for a nationwide or remote role; ...";
    Dutchie's dropdown offers "$90,000 - $99,999", "$100,000 - $109,999".
    The FIRST figure he gave is the one a range is chosen by, and only a
    range that plainly holds it — never the nearest, never a guess between.
    """
    wanted = _amounts(value)
    if not wanted or wanted[0] < 1000:
        return None
    want = wanted[0]
    hits = []
    for option in options:
        amounts = [a for a in _amounts(option) if a >= 1000]
        text = _norm(option)
        if len(amounts) >= 2 and amounts[0] <= want <= amounts[1]:
            hits.append(option)
        elif len(amounts) == 1 and (("+" in str(option)) or _says("above", text)
                                   or _says("or more", text) or _says("plus", text)):
            if want >= amounts[0]:
                hits.append(option)
    return hits[0] if len(hits) == 1 else None


def plan(fields: list[dict], *, answers: dict | None = None, found_on: str = "") -> dict:
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
        option_labels = [o["label"] for o in group["options"] if o["label"]]
        if group["selector"] in answers:
            # HIS ANSWER ON THIS FORM OUTRANKS ANYTHING SHE WOULD DO BY DEFAULT,
            # and it only lands through `apply_answers`, which reads `ask`.
            # Filled from the profile instead, the answer he (or the model
            # reading his facts) gave to a question she had got wrong was
            # silently thrown away on every re-stage.
            ask.append({"selector": group["selector"], "label": group["label"],
                        "required": group["required"], "type": group["type"],
                        "choices": option_labels,
                        "option_selectors": {o["label"]: o["selector"]
                                             for o in group["options"] if o["label"]},
                        "why": "answered on this form"})
            continue
        category = category_of(group["label"], option_labels)
        declared = declared_choice(group["label"], option_labels, category=category)
        if declared is not None:
            option = next(o for o in group["options"] if o["label"] == declared)
            fill.append({"action": "click", "selector": option["selector"],
                         "label": group["label"], "value": declared,
                         "profile_field": category})
            continue
        protected = is_never_autofill({"label": group["label"], "choices": option_labels})
        # Asked once is once, for a list of boxes too. Databricks' "please
        # confirm whether any of the following also applies to you" had his
        # "U.S. citizen" on file and still went to him: the asked-once store
        # was consulted for typed boxes only.
        told = "" if protected else profile.answer_for(group["label"])
        named = _options_named(told, option_labels) if told else []
        if named:
            for chosen in named:
                option = next(o for o in group["options"] if o["label"] == chosen)
                fill.append({"action": "click", "selector": option["selector"],
                             "label": group["label"], "value": chosen,
                             "profile_field": "asked_once"})
            continue
        if found_on and not protected and match_field({"label": group["label"]}) == "heard_about":
            said = heard_about_answer(found_on, option_labels)
            if said is not None:
                option = next(o for o in group["options"] if o["label"] == said)
                fill.append({"action": "click", "selector": option["selector"],
                             "label": group["label"], "value": said,
                             "profile_field": "heard_about"})
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
        offered = (option_texts(field)
                   if field.get("choices") or field.get("tag") == "select" else [])
        if offered:
            # A dropdown's own options - read off its open menu, or a <select>'s
            # - so the answer can be one of them. Palantir's "how did you hear"
            # and its university list reached the model and him with nothing to
            # choose. Bounded for the record; `field` keeps every option, and
            # every match below reads `field`.
            row["choices"] = bounded_choices(offered, known=known)
            if len(offered) > len(row["choices"]):
                row["choices_total"] = len(offered)
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
        if _ALERT_WIDGET.search(_clean_label(label)):
            row["why"] = "a job-alert signup on the page, not a question"
            skipped.append(row)
            continue
        if field["selector"] in answers:
            # An answer given for THIS box - his, or the one the model read off
            # his facts after she could not find the right option - is what
            # goes in it. Filling it from the profile again (Tebra's State got
            # "SD" every time) left that answer with nowhere to land.
            row["why"] = "answered on this form"
            ask.append(row)
            continue
        if _MESSAGE_OPT_IN.search(_clean_label(label)) and field.get("type") not in ("checkbox", "radio"):
            texts = _choice_texts(field)
            no = next((o for o in texts if _norm(o) in _PLAIN_NO), None)
            if no is not None:
                if field.get("tag") == "select":
                    value = next((o["value"] for o in field.get("options") or []
                                  if o.get("text") == no), None)
                    if value is not None:
                        fill.append({"action": "select", "selector": field["selector"],
                                     "value": value, "label": label,
                                     "profile_field": "message_opt_in"})
                        continue
                else:
                    fill.append({"action": "type", "selector": field["selector"],
                                 "value": no, "label": label,
                                 "profile_field": "message_opt_in"})
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
        if key == "heard_about" and found_on:
            options = _choice_texts(field)
            said = heard_about_answer(found_on, options)
            if said is not None:
                if field.get("tag") == "select":
                    option = next((o["value"] for o in field.get("options") or []
                                   if o.get("text") == said), None)
                    if option is not None:
                        fill.append({"action": "select", "selector": field["selector"],
                                     "value": option, "label": label,
                                     "profile_field": "heard_about"})
                        continue
                else:
                    fill.append({"action": "type", "selector": field["selector"],
                                 "value": said, "label": label, "profile_field": "heard_about"})
                    continue
        if key is None:
            # He answered this exact question once, on somebody else's form.
            # Asking him again is the thing he asked not to happen: "if it
            # don't know somthing about me it can ask 1 time after that it
            # should know". Never a declaration or a protected question —
            # is_never_autofill has already taken those out above.
            told = profile.answer_for(label)
            if told:
                if field.get("tag") == "select":
                    option = _option_for(field, told)
                    if option is not None:
                        fill.append({"action": "select", "selector": field["selector"],
                                     "value": option, "label": label,
                                     "profile_field": "asked_once"})
                        continue
                else:
                    fill.append({"action": "type", "selector": field["selector"],
                                 "value": told, "label": label,
                                 "profile_field": "asked_once"})
                    continue
            decline = voluntary_decline(label, _choice_texts(field))
            if decline is not None:
                if field.get("tag") == "select":
                    option = next((o["value"] for o in field.get("options") or []
                                   if o.get("text") == decline), None)
                    if option is not None:
                        fill.append({"action": "select", "selector": field["selector"],
                                     "value": option, "label": label,
                                     "profile_field": "self_id_decline"})
                        continue
                else:
                    fill.append({"action": "type", "selector": field["selector"],
                                 "value": decline, "label": label,
                                 "profile_field": "self_id_decline"})
                    continue
            row["why"] = "she could not tell what this is asking for"
            ask.append(row)
            continue
        if key == "preferred_name" and key not in known and known.get("first_name"):
            # Nobody goes by a name he never gave: his preferred first name is
            # his first name until he says otherwise.
            known = {**known, "preferred_name": known["first_name"]}
        if key not in known:
            if not row["required"] and key in _BLANK_IS_AN_ANSWER:
                # Twitter. Portfolio. Personal Website. He does not have
                # them, the form does not require them, and a blank optional
                # box is a complete application — so stopping on one asks him
                # to come back and type nothing.
                #
                # Narrow on purpose, and it was wider for about ten minutes:
                # skipping EVERY optional field she could not answer also
                # swallowed "Desired salary" and "Section 4b", which are real
                # questions that happen to sit in optional boxes. Two tests
                # said so by name. A thing he has no value for is not the
                # same as a thing she has no idea about.
                row["why"] = _LEAVE_IT_BLANK
                row["profile_field"] = key
                skipped.append(row)
                continue
            row["why"] = f"she does not know {profile.FIELDS[key]['means']}"
            row["profile_field"] = key
            ask.append(row)
            continue
        value = known[key]
        if field.get("tag") == "select":
            option = _option_for(field, value)
            if option is None and key == "school":
                # His school is not on the list, and the list says what to pick
                # then: "Other (School Not Listed)" (Palantir, live 2026-09-13).
                option = next((o["value"] for o in field.get("options") or []
                               if _OTHER_NOT_LISTED.search(_norm(o.get("text")))), None)
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
                option = _stand_in_option(field, label, value)
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

# Lever's "Current location" is the same kind of widget without the ARIA: an
# <input class="location-input"> whose suggestions are .dropdown-location rows,
# and a hidden selectedLocation that only a CLICKED suggestion sets. Typed and
# left, the text is thrown away on blur - live 2026-09-14 Palantir and Spotify
# both stopped on "Current location: Please fill out this field." with "Hartford"
# on the confirmation and nothing in the box.
COMBOBOX_JS = r"""(css) => {
  const el = document.querySelector(css);
  return !!el && (el.getAttribute('role') === 'combobox'
                  || el.getAttribute('aria-autocomplete') === 'list'
                  || el.classList.contains('location-input')
                  || !!(el.parentElement && el.parentElement.querySelector('.dropdown-results')));
}"""
OPTION_CSS = "[role=option], .dropdown-results .dropdown-location"
VISIBLE_OPTIONS_JS = r"""() => [...document.querySelectorAll('%s')]
  .filter(o => o.offsetParent !== null)
  .map(o => (o.innerText || '').trim()).filter(Boolean).slice(0, 400)""" % OPTION_CSS
# The VISIBLE option whose text is exactly the choice. A text-contains match
# found "No" inside a hidden option left over from another menu and waited
# thirty seconds to click something that could not be clicked.
FIND_OPTION_JS = r"""(text) => [...document.querySelectorAll('%s')]
  .find(o => o.offsetParent !== null && (o.innerText || '').trim() === text) || null""" % OPTION_CSS

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


def _years_range(value, options: list[str]) -> str | None:
    """A number of years, placed in the ONE range option that holds it.

    "7" against "1-2 years of experience" / "3-5 years" / "5+ years" is "5+".
    A number two options both hold ("5" in "3-5" and "5+") is not guessed.
    """
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{1,2}(?:\.\d+)?", raw):
        return None
    n = float(raw)
    hits = []
    for option in options:
        text = str(option).casefold()
        if not re.search(r"\byears?\b|\byrs?\b|\bnone\b", text):
            continue
        span = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", text)
        more = re.search(r"(\d+(?:\.\d+)?)\s*\+|(\d+(?:\.\d+)?)\s*(?:or more|and above|and up)", text)
        over = re.search(r"\b(?:more than|over)\s*(\d+(?:\.\d+)?)", text)
        under = re.search(r"\b(?:less than|under|fewer than)\s*(\d+(?:\.\d+)?)", text)
        if span:
            lo, hi = float(span.group(1)), float(span.group(2))
        elif more:
            lo, hi = float(more.group(1) or more.group(2)), 99.0
        elif over:
            lo, hi = float(over.group(1)) + 0.001, 99.0
        elif under:
            lo, hi = 0.0, float(under.group(1)) - 0.001
        elif re.search(r"\bnone\b|\bno experience\b", text):
            lo, hi = 0.0, 0.0
        else:
            continue
        if lo <= n <= hi:
            hits.append(option)
    return hits[0] if len(hits) == 1 else None


def _names_other_state(option: str, state: str) -> bool:
    """"Hartford, CT, USA" when he lives in SD."""
    for abbr in re.findall(r",\s*([A-Z]{2})\b", str(option)):
        if abbr in US_STATE_NAMES and abbr != state:
            return True
    n = _norm(option)
    return any(_says(_norm(name), n) for abbr, name in US_STATE_NAMES.items() if abbr != state)


_SAYS_AUTHORIZED = re.compile(
    r"\b(?:i am|i'm|i’m)\b.{0,40}?\b(?:authori[sz]ed|eligible|citizen|national|permanent resident)\b",
    re.I)
#: Anything that makes an "I am authorized" sentence not his unrestricted yes.
_RESTRICTED = re.compile(
    r"\bnot\b|\bunknown\b|\bsponsor|\bvisa\b|\bpermit\b|\bonly\b|\bpresent employer\b|"
    r"\bcurrent employer\b|\bopt\b|\bcpt\b|\bh-?1b\b|\bdaca\b|\brefugee\b|\basylee\b|"
    r"\btemporar|\bpending\b|\bexpire|\bpermanent resident\b|\bgreen card\b|\blawful\b", re.I)
_CITIZEN = re.compile(r"\bu\.?\s?s\.?(?:a\.?)?\s+citizen\b|\bcitizen of the united states\b", re.I)


def _his_citizenship(known: dict) -> bool:
    """Whether HE has said he is a U.S. citizen - his words, never a guess."""
    if _CITIZEN.search(str(known.get("citizenship") or "")):
        return True
    try:
        return any(_CITIZEN.search(str(row.get("value") or ""))
                   for row in profile.questions_on_file())
    except Exception:
        return False


def authorized_choice(options: list[str], known: dict | None = None) -> str | None:
    """His "Yes, authorized" on a list that answers in sentences, or None.

    SpaceX asks "Are you legally authorized to work in the United States?" with
    "I am authorized to work in the United States for any employer", "... for my
    present employer only", "I require sponsorship ...", "I am not authorized
    ...", "My status ... is unknown" - no option says Yes, so two applications
    waited on him for an answer that was on file. Only when he is authorized AND
    needs no sponsorship; never an option naming a restriction, a sponsorship or
    a status he has not claimed; citizenship only when he said it.
    """
    known = known or {}
    if _norm(known.get("work_authorization")) != "yes" or _norm(known.get("needs_sponsorship")) != "no":
        return None
    fits = [o for o in options if _SAYS_AUTHORIZED.search(str(o)) and not _RESTRICTED.search(str(o))]
    citizen = [o for o in fits if _CITIZEN.search(str(o)) or _says("citizen", _norm(o))]
    if citizen:
        if _his_citizenship(known) and len(citizen) == 1:
            return citizen[0]
        fits = [o for o in fits if o not in citizen]
    if len(fits) > 1:
        fits = [o for o in fits if _says("any employer", _norm(o))] or fits
    return fits[0] if len(fits) == 1 else None


def _best_option(value, options: list[str], known: dict | None = None) -> str | None:
    """The one option that IS the answer, or None. Never a guess between two."""
    known = known or {}
    v = _norm(value)
    if not v or not options:
        return None
    normed = [(o, _norm(o)) for o in options]
    his_state = str(known.get("state") or "").strip().upper()
    if his_state and v == _norm(known.get("city")):
        # His city in somebody else's state is a different place: "Hartford,
        # CT, USA" is not Hartford, South Dakota, however it starts.
        normed = [(o, n) for o, n in normed if not _names_other_state(o, his_state)]
        options = [o for o, _n in normed]
    wants = {v}
    for same in _SAME_COUNTRY:
        if v in same:
            wants |= same
    # "SD" is South Dakota. Tebra, Affirm and Instacart each list states by
    # name, and his state is on file as the two letters his resume uses, so
    # three live applications stopped on where he lives (2026-09-13).
    if str(value).strip().upper() in US_STATE_NAMES and len(str(value).strip()) == 2:
        wants.add(_norm(US_STATE_NAMES[str(value).strip().upper()]))
    money = _money_choice(value, options)
    if money is not None:
        return money
    # A number of years against a list of ranges is read as a range, and only
    # a range: "5" must not pick "5+ years" by its first word when "3-5 years"
    # holds it too.
    if re.fullmatch(r"\d{1,2}(?:\.\d+)?", str(value).strip()) and \
            any(re.search(r"\byears?\b|\byrs?\b", str(o).casefold()) for o in options):
        return _years_range(value, options)
    exact = [o for o, n in normed if n in wants]
    if exact:
        return exact[0]
    # "United States +1": the answer, then something that is not another answer.
    lead = [o for o, n in normed if any(n.startswith(w + " ") for w in wants)]
    if len(lead) == 1:
        return lead[0]
    # "(US) South Dakota": a list that puts its country in front (Instacart).
    bare = [o for o, n in normed
            if re.sub(r"^(?:us|usa|u s|united states)\s+", "", n) in wants]
    if len(bare) == 1:
        return bare[0]
    # "Yes, no restriction." beside "Yes, but I will need sponsorship in the
    # future." (Datadog): a yes that also claims a need he does not have is not
    # his yes.
    if v in ("yes", "no"):
        said = [o for o, n in normed if n == v or n.startswith(v + " ")]
        if len(said) > 1 and v == "yes" and _norm(known.get("needs_sponsorship")) == "no":
            said = [o for o in said
                    if not re.search(r"\b(?:sponsor\w*|visa|permit)\b", _norm(o))]
        if len(said) == 1:
            return said[0]
        if v == "yes" and not said:
            authorized = authorized_choice(options, known)
            if authorized is not None:
                return authorized
    # A place: the city he lives in, in the state he lives in.
    state = str(known.get("state") or "").strip().upper()
    in_state = {_norm(state), _norm(US_STATE_NAMES.get(state, ""))} - {""}
    if in_state:
        placed = [o for o, n in normed
                  if _says(v, n) and any(_says(s, n) for s in in_state)]
        # "Hartford, SD, USA" and "Hartford, South Dakota 57033" are one place:
        # the first suggestion naming his city in his state is his.
        if placed and v == _norm(known.get("city")):
            return placed[0]
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
