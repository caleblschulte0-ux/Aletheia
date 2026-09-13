"""Making an account, so a form that wants one stops being a dead end.

His words, 2026-09-13: *"I need this to be able to apply to jobs any where
on the web."* Today she can apply on Greenhouse and Lever and nowhere else,
for one reason: those are the only two large systems that host the real
application form at a public URL with no account. Workday, Ashby,
SmartRecruiters, iCIMS and most company career pages want a login first,
and she had no way to make one — not because anything refused her, but
because it was never built.

WHAT THIS IS NOT. It does not solve CAPTCHAs, and it must never learn to.
Paying a solving service is spending money, which is the one permanent rule
(`webtask.would_spend`), and a CAPTCHA is a site saying in plain words that
it wants a person. `prepare()` returns CAPTCHA before anything is typed, and the
account becomes his to make.

THREE THINGS THAT ARE DELIBERATE AND SHOULD NOT BE "SIMPLIFIED":

1. **The password only ever goes to `secret_store`.** If DPAPI is not
   available, `prepare` REFUSES rather than writing a password anywhere
   else. An account whose password is in a JSON file is worse than no
   account: he would not know it was there.
2. **The phone is `signup_phone`, never his real one.** His ruling the same
   day, looking at his Google Voice tab: the account gets the Voice number,
   the application gets his real number. `profile.SIGNUP_ONLY` and this
   module are the only two places that know the signup number exists.
3. **An account is durable in a way an application is not.** A bad
   application wastes one submission; a botched account is something he has
   to go and clean up, at an employer he wanted. So `prepare` produces a
   plan and nothing more — pressing the button needs an approval, the same
   as a submitted application, and `account_alias` is stable so the second
   attempt at one employer finds the first account instead of making
   another.

The browser work is NOT here. `prepare` reads a form (via `formfill`) and
returns what to type; `apply_run`/`browse.interact` already own pressing
things under an approval bound to that exact page. This module decides.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import string
import sys

from aletheia import formfill, journal, profile, stateio

ACTOR = "aletheia-signup"

#: Where the record of "we have an account here" lives. Private state — an
#: account list is a map of where he has been looking for work.
def accounts_path():
    return stateio.private_dir("signup") / "accounts.json"


# ---------------------------------------------------------------- detection

#: A page that wants an account before it will take an application. Matched
#: on SENTENCES, never the bare word "account": "Account Executive" is a job
#: title and half of Greenhouse's listings contain it.
_WANTS_ACCOUNT = re.compile(
    r"create (?:an |your )?account|sign up to apply|register to apply"
    r"|create (?:a )?(?:candidate |job seeker )?profile"
    r"|you (?:must|need to) (?:sign in|log in|be signed in)"
    r"|already have an account\?|new to (?:this|our) site\?"
    r"|set (?:up|a) password",
    re.I)

#: A page that wants a PERSON. She stops here, always.
_CAPTCHA = re.compile(
    r"\brecaptcha\b|\bhcaptcha\b|\bcloudflare turnstile\b|\bturnstile\b"
    r"|i'?m not a robot|verify you are (?:a )?human"
    r"|complete the (?:security )?challenge|press and hold",
    re.I)

#: CAPTCHA widgets by the marks they leave in a form's own field list.
_CAPTCHA_CODES = ("g-recaptcha", "recaptcha", "h-captcha", "hcaptcha",
                  "cf-turnstile", "turnstile")

#: A sign-IN page is not a sign-UP page, and telling them apart matters:
#: filling a login form with a new password just fails, loudly, ten times.
_SIGN_IN_ONLY = re.compile(
    r"sign in to your account|welcome back|forgot (?:your )?password", re.I)

OK = "ok"
CAPTCHA = "captcha"
NO_VAULT = "no_vault"
ALREADY = "already"


def wants_an_account(text: str) -> bool:
    """Does this page require an account before it will take an application?"""
    return bool(_WANTS_ACCOUNT.search(str(text or "")))


def has_captcha(text: str = "", fields: list[dict] | None = None) -> bool:
    """A human check, by its words or by its widget.

    Both are needed: Turnstile renders no visible sentence at all, and a
    page can name reCAPTCHA in its terms without showing one — so the
    field list is the reliable half and the words are the backstop.
    """
    if _CAPTCHA.search(str(text or "")):
        return True
    for field in fields or []:
        blob = " ".join(str(field.get(k) or "") for k in
                        ("name", "id", "label", "type", "selector")).casefold()
        if any(code in blob for code in _CAPTCHA_CODES):
            return True
    return False


def looks_like_sign_in(text: str) -> bool:
    """A login page wearing a signup page's words."""
    body = str(text or "")
    return bool(_SIGN_IN_ONLY.search(body)) and not _WANTS_ACCOUNT.search(body)


# ----------------------------------------------------------------- password

#: Long enough that nothing argues, and every class present so a site's own
#: "must contain a symbol" rule is satisfied on the first try rather than
#: sending her round the loop with an error she has to read.
PASSWORD_LEN = 20
_SYMBOLS = "!@#$%^&*-_=+"


def new_password(length: int = PASSWORD_LEN) -> str:
    """A password he will never type and never has to remember.

    `secrets`, not `random` — this is a credential. Guaranteed to contain a
    lower, an upper, a digit and a symbol, because a site that silently
    requires one and rejects the form is indistinguishable from a site that
    is broken.
    """
    if length < 12:
        raise ValueError("a password shorter than 12 is not worth storing")
    alphabet = string.ascii_letters + string.digits + _SYMBOLS
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)
                and any(c in _SYMBOLS for c in pw)):
            return pw


def account_alias(host: str) -> str:
    """The vault name for one site's account. Stable, so the second visit
    to an employer finds the first account instead of making another."""
    clean = re.sub(r"^www\.", "", str(host or "").strip().casefold())
    clean = re.sub(r"[^a-z0-9.-]+", "-", clean).strip("-.")
    if not clean:
        raise ValueError("a signup needs a host to key the account on")
    return f"signup.{clean}"


# --------------------------------------------------------------- the fields

#: What a signup form asks for, by the codes and labels real ones use.
#: `formfill` deliberately SKIPS password inputs (SKIP_TYPES), which is
#: right for an application and is exactly why signup needs its own reader.
_PASSWORD_NEW = re.compile(
    r"password", re.I)
_PASSWORD_CONFIRM = re.compile(
    r"confirm|re-?enter|repeat|verify|again|retype", re.I)


def _blob(field: dict) -> str:
    return " ".join(str(field.get(k) or "")
                    for k in ("label", "name", "id", "placeholder")).strip()


def password_fields(fields: list[dict]) -> tuple[list[dict], list[dict]]:
    """(where the password goes, where it is confirmed).

    Split on the label, not on order: a form that puts "Confirm password"
    first would otherwise get the password in the confirm box and vice
    versa, and the error it returns says only "passwords do not match".
    """
    new, confirm = [], []
    for field in fields or []:
        kind = str(field.get("type") or "").casefold()
        blob = _blob(field)
        if kind != "password" and not _PASSWORD_NEW.search(blob):
            continue
        (confirm if _PASSWORD_CONFIRM.search(blob) else new).append(field)
    return new, confirm


def is_signup_form(fields: list[dict]) -> bool:
    """Is this form an ACCOUNT form rather than an application?

    Decided from the fields alone, because `formfill.read_form` returns
    fields and no page text — and this has to work on the path that reads
    them. A password box is the tell: an application form never has one,
    which is exactly why `formfill.SKIP_TYPES` drops them. Today a Workday
    login page therefore reads as an application with its only real inputs
    silently discarded, and stages a record that could never be submitted.

    A resume upload says the opposite: a page that takes his CV is an
    application, whatever else it asks for. Some sites really do put
    "create a password" at the bottom of a long application, and those
    should still be applied to.
    """
    new_pw, _ = password_fields(fields)
    if not new_pw:
        return False
    for field in fields or []:
        kind = str(field.get("type") or "").casefold()
        blob = _blob(field).casefold()
        if kind == "file" or "resume" in blob or "cv" in blob.split():
            return False
    return True


def plan(fields: list[dict], *, host: str, known: dict | None = None,
         password: str | None = None) -> dict:
    """What to type into a signup form, and what is missing.

    Reuses `formfill.match_field` for the ordinary facts, so a signup page
    and an application page read a "First name" box the same way. Two
    deliberate differences:

      * the phone is `signup_phone` — his Google Voice number, never the
        one an employer would ring;
      * password boxes are filled, which `formfill` never does.
    """
    known = dict(known if known is not None else profile.known())
    password = password or new_password()
    filled, missing = [], []

    new_pw, confirm_pw = password_fields(fields)
    handled = {id(f) for f in new_pw + confirm_pw}
    for field in new_pw + confirm_pw:
        filled.append({"field": field, "value": password, "is": "password",
                       "why": "a new password, kept in the vault"})

    for field in fields or []:
        if id(field) in handled or formfill.is_widget_furniture(field):
            continue
        key = formfill.match_field(field)
        if key is None:
            continue
        # THE ONE SUBSTITUTION. His ruling: the account gets the Voice
        # number so a signup never changes what an employer would call.
        if key == "phone":
            value = known.get("signup_phone") or ""
            if not value:
                missing.append({"field": field, "needs": "signup_phone",
                                "why": "no signup number on file — set it with "
                                       "`profile set signup_phone`, so an account "
                                       "never carries the number employers ring"})
                continue
            filled.append({"field": field, "value": value, "is": "signup_phone",
                           "why": "his signup number, not the one on his applications"})
            continue
        if formfill.is_never_autofill(field):
            continue
        value = known.get(key)
        if not value:
            missing.append({"field": field, "needs": key,
                            "why": f"she does not know {profile.FIELDS[key]['means']}"})
            continue
        filled.append({"field": field, "value": value, "is": key,
                       "why": f"his {profile.FIELDS[key]['means']}"})

    return {"host": host, "alias": account_alias(host), "password": password,
            "fill": filled, "missing": missing}


# ------------------------------------------------------------------ the run

def _vault():
    from aletheia import secret_store
    return secret_store


def vault_ready() -> tuple[bool, str]:
    """Can a password be stored at all? Asked BEFORE anything is typed.

    INSTALLED is not WORKING: this calls the store's own live check rather
    than trusting that the module imported.
    """
    try:
        ok, why = _vault().available()
    except Exception as exc:
        return False, f"the secret vault could not be reached: {exc}"
    return bool(ok), str(why or "")


def known_account(host: str) -> dict | None:
    """The account she already made here, if any."""
    try:
        rows = stateio.read_json(accounts_path())
    except (OSError, ValueError):
        return None
    if not isinstance(rows, dict):
        return None
    return rows.get(account_alias(host))


def prepare(fields: list[dict], *, host: str, page_text: str = "",
            known: dict | None = None) -> dict:
    """Decide whether an account can be made here, and how. Types nothing.

    The order is the safety argument. A CAPTCHA is checked before anything
    else, so she never fills half a form she cannot finish; the vault is
    checked before a password exists, so one is never generated that has
    nowhere to live; and an account already on file short-circuits, so a
    second visit signs in rather than registering twice.
    """
    if has_captcha(page_text, fields):
        return {"state": CAPTCHA, "host": host,
                "why": "this page asks for a human check, so the account is "
                       "his to make — she will not try to solve it"}
    existing = known_account(host)
    if existing:
        return {"state": ALREADY, "host": host, "account": existing,
                "why": "she already has an account here"}
    ok, why = vault_ready()
    if not ok:
        return {"state": NO_VAULT, "host": host,
                "why": f"no password vault, so nowhere safe to keep it: {why}"}
    return {"state": OK, **plan(fields, host=host, known=known)}


def remember(host: str, *, username: str, password: str,
             employer: str = "", provider: str = "") -> dict:
    """Record the account and put the password in the vault.

    The password goes to `secret_store` and NOWHERE else — the record keeps
    only the alias, so reading this file tells you an account exists and
    not how to use it. The journal records that an account was made, never
    the password.
    """
    alias = account_alias(host)
    _vault().put(alias, password, provider=provider or host, kind="account")
    try:
        rows = stateio.read_json(accounts_path())
        rows = rows if isinstance(rows, dict) else {}
    except (OSError, ValueError):
        rows = {}
    record = {"alias": alias, "host": host, "username": username,
              "employer": employer, "provider": provider,
              "created": stateio.utcnow()}
    rows[alias] = record
    stateio.write_json_atomic(accounts_path(), rows)
    journal.append("action", f"{ACTOR}:{alias}",
                   f"made an account at {host} as {username}", actor=ACTOR)
    return record


def accounts() -> list[dict]:
    """Every account she has made. An empty list still proves the store."""
    try:
        rows = stateio.read_json(accounts_path())
    except (OSError, ValueError):
        return []
    return sorted((rows or {}).values(), key=lambda r: str(r.get("created") or "")) \
        if isinstance(rows, dict) else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Accounts, so a login is not a wall")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="every account she has made")
    sub.add_parser("check", help="can a password be stored on this machine?")
    p_r = sub.add_parser("read", help="decide about a signup page (types nothing)")
    p_r.add_argument("url")
    args = ap.parse_args(argv)

    if args.cmd == "check":
        ok, why = vault_ready()
        print(("ready: " if ok else "not ready: ") + (why or ""))
        have = profile.known().get("signup_phone")
        print("signup number: " + ("on file" if have else
              "NOT set — a form that requires a phone cannot be finished"))
        return 0 if ok else 1

    if args.cmd == "list":
        rows = accounts()
        if not rows:
            print("No accounts yet. (The store is there; it is empty.)")
        for row in rows:
            print(f"  {row.get('host'):32s} {row.get('username','')}")
        return 0

    import urllib.parse
    host = urllib.parse.urlparse(args.url).netloc
    fields = formfill.read_form(args.url)
    out = prepare(fields, host=host)
    print(json.dumps({k: v for k, v in out.items() if k != "password"},
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
