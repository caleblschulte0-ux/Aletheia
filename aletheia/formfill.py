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

from aletheia import journal, policy, profile

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
    return any(phrase in hay for phrase in profile.NEVER_AUTOFILL)


def match_field(field: dict) -> str | None:
    """Which profile answer this form field is asking for, if any.

    Longest phrase wins: "first name" must beat "name", or every name box
    on the internet gets his full legal name.
    """
    hay = _haystack(field)
    best, best_len = None, 0
    for key, spec in profile.FIELDS.items():
        for phrase in spec["asks"]:
            if phrase in hay and len(phrase) > best_len:
                best, best_len = key, len(phrase)
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


def plan(fields: list[dict], *, answers: dict | None = None) -> dict:
    """Split a form into what she can fill and what he has to answer."""
    answers = known = (answers if answers is not None else profile.known())
    fields, choices = _group_choices(list(fields)[:MAX_FIELDS])
    fill, ask, skipped = [], [], []
    for group in choices:
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
        if field.get("type") in SKIP_TYPES:
            row["why"] = ("a file upload is yours to choose"
                          if field.get("type") == "file"
                          else f"she does not type into a {field.get('type')} field")
            skipped.append(row)
            continue
        if is_never_autofill(field):
            # Even if the profile holds it. An answer invented on his
            # behalf here is a lie in a file an employer keeps.
            row["why"] = "this one is yours to answer, always"
            ask.append(row)
            continue
        if field.get("type") in LONG_ANSWER_TYPES and not match_field(field):
            row["why"] = "a written answer, not a fact she has on file"
            ask.append(row)
            continue
        key = match_field(field)
        if key is None:
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
            filled.append({"label": label, "value": option})
        elif field.get("type") in ("checkbox", "radio"):
            # A checkbox is clicked, never filled — and only when he said
            # yes. "No" on a checkbox means leave it alone, not click it.
            if value is True or str(value).strip().casefold() in (
                    "yes", "true", "1", "on", "checked", "i agree"):
                steps_out.append({"action": "click", "selector": selector})
                filled.append({"label": label, "value": "ticked"})
            else:
                filled.append({"label": label, "value": "left unticked"})
        else:
            steps_out.append({"action": "type", "selector": selector,
                              "value": str(value)})
            filled.append({"label": label, "value": str(value)})
    out["ask"] = still_asked
    return {"steps": steps_out, "filled": filled, "refused": refused}


def steps(filled: list[dict]) -> list[dict]:
    """The plan in `browse.interact`'s grammar — and nothing that submits."""
    return [{"action": s["action"], "selector": s["selector"],
             "value": s["value"]} for s in filled]


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
        found = page.evaluate(READ_FORM_JS)
        page.close()
    journal.append("action", "formfill", f"read {len(found)} field(s) on {url}",
                   actor=ACTOR)
    return found


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
    said = f"{out['fields_found']} field(s) on that form. She can fill {fill}"
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
