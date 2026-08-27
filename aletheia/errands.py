"""The last mile: carrying a proposal into the world (§143, §152).

Aletheia could already PLAN everything at the edge of her reach — a cart
in `purchases`, a slot in `reservations`, a cancellation in
`subscriptions`, a scene in `room`. Each of those stopped at the same
place, and the registry said so honestly: purchase.execute,
reservation.book, subscription.cancel, NOT_BUILT. She was a very good
ledger of intentions.

§152 says what NOT to do about that: five bespoke merchant integrations
is the wrong shape, and every one of them rots the week its site
redesigns. "Prefer primitives that unlock entire classes of tasks."

So there is one primitive here, an **errand**: a hash-bound sequence of
browser steps against a named site, authorized once, executed through the
browser gate that already exists (`browse.interact`, approval-checked
before the browser even opens), and finished only on evidence. Buying,
booking and cancelling are the same errand with different kinds. So is
the next one, which nobody has thought of yet.

Three properties are what make this safe enough to exist:

**Authorization is to the exact errand.** The approval carries a sha256
of {site, kind, steps, ceiling}. Change a selector, a URL, or a price cap
after he says yes and the hash no longer matches — refused, never
adapted. Same binding ratified for computer control, email, and intents.

**Money has a ceiling, checked twice.** An errand that spends declares a
maximum, and the observed total is checked against it AFTER the page
shows a number. A page that turns out to cost more than authorized is
abandoned mid-errand, not completed and apologized for.

**The boundary is real and is honoured.** §143 lists what Aletheia does
not get to do: identity checks, signatures, biometrics, human-only
consent, sites that deliberately block automation. `BOUNDARY_SIGNALS` is
that list expressed as page evidence. When an errand hits one — a 3-D
Secure step-up, a bank OTP, a CAPTCHA, a consent form — it stops, records
exactly how far it got, and hands the operator the remainder. That is not
this module failing. It is §143 working, and "carry the task to the
boundary; minimize Caleb's remaining work" is the whole specification.

What deliberately has no path here at all: moving money directly — bank
transfers, bill payments, trades. `finance.transact` stays NOT_BUILT
because the boundary in §143 is the entire mechanism, not an obstacle in
front of one. An errand may pay a merchant's checkout page under a
ceiling; it may not reach into an account. See `finance.hand_off`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation

from aletheia import journal, policy, stateio

ACTOR = "aletheia-errand"

KINDS = {"purchase", "reservation", "cancellation", "form"}
SPENDING_KINDS = {"purchase"}

PROPOSED = "PROPOSED"
AUTHORIZED = "AUTHORIZED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
AT_BOUNDARY = "AT_BOUNDARY"
REFUSED = "REFUSED"
FAILED = "FAILED"

MAX_STEPS = 25

# §143 as page evidence. Each entry is (name, what it means for the human).
# Matching is deliberately generous: a false stop costs the operator one
# manual finish, a false continue costs him an unauthorized action.
BOUNDARY_SIGNALS: dict[str, str] = {
    r"3-?d ?secure|verified by visa|securecode|step[- ]up authentication":
        "your bank wants to verify this payment itself",
    r"one[- ]time (pass)?code|verification code|two[- ]factor|2fa|authenticator":
        "a one-time code was sent to you",
    r"captcha|recaptcha|hcaptcha|are you (a )?human|prove you.re not a robot":
        "the site is deliberately blocking automation",
    r"\bsign(ature)?\b.{0,20}\b(here|required|pad)\b|docusign|e-?sign":
        "this needs your signature",
    r"upload.{0,30}(id|licen[cs]e|passport)|identity verification|verify your identity":
        "this needs an identity document",
    r"face ?id|touch ?id|fingerprint|biometric":
        "this needs your biometrics",
    r"i (agree|consent) to|terms (and|&) conditions must be accepted|"
    r"medical (consent|authorisation|authorization)":
        "this needs your consent, which is not mine to give",
}

MONEY = re.compile(r"(?:[$£€]\s?|\b(?:usd|gbp|eur)\s+)(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
                   re.I)


def errands_dir():
    return stateio.private_dir("errands")


def _path(errand_id: str):
    return errands_dir() / f"{stateio.safe_id(errand_id, name='errand id')}.json"


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError, TypeError) as exc:
        raise ValueError(f"not an amount: {value!r}") from exc
    if amount < 0:
        raise ValueError("an amount cannot be negative")
    return amount


def fingerprint(site: str, kind: str, steps: list[dict],
                ceiling: str | None) -> str:
    """A hash of exactly what was authorized: where, what, how, how much."""
    material = {"site": site, "kind": kind, "ceiling": str(ceiling or ""),
                "steps": steps}
    return hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def boundary_in(text: str) -> tuple[str, str] | None:
    """(pattern, plain-English meaning) for the first §143 boundary seen."""
    low = " ".join(str(text or "").split()).lower()
    for pattern, meaning in BOUNDARY_SIGNALS.items():
        if re.search(pattern, low):
            return pattern, meaning
    return None


def observed_total(text: str) -> Decimal | None:
    """The largest money figure on the page — the checkout total in practice.

    Largest, not first: a basket page shows line items, shipping, tax and
    then the thing that will actually be charged. Reading the first number
    is how a ceiling gets passed by a page that says "$4.99 shipping".
    """
    amounts = []
    for raw in MONEY.findall(str(text or "")):
        try:
            amounts.append(_money(raw))
        except ValueError:
            continue
    return max(amounts) if amounts else None


def validate(site: str, kind: str, steps: list[dict],
             ceiling: str | None) -> list[str]:
    problems = []
    if kind not in KINDS:
        problems.append(f"kind must be one of {sorted(KINDS)}")
    if not isinstance(site, str) or not site.startswith(("http://", "https://")):
        problems.append("site must be an http(s) URL")
    if not isinstance(steps, list) or not steps:
        problems.append("an errand needs at least one step")
    elif len(steps) > MAX_STEPS:
        problems.append(f"at most {MAX_STEPS} steps, got {len(steps)}")
    if kind in SPENDING_KINDS:
        if ceiling is None:
            problems.append("a spending errand must declare a ceiling")
        else:
            try:
                if _money(ceiling) <= 0:
                    problems.append("a spending ceiling must be above zero")
            except ValueError as exc:
                problems.append(str(exc))
    elif ceiling is not None:
        problems.append(f"a {kind} errand does not spend and takes no ceiling")
    if steps:
        from aletheia import browse
        problems += browse.validate_steps(steps)
    return problems


def propose(errand_id: str, *, site: str, kind: str, steps: list[dict],
            ceiling: str | None = None, why: str = "",
            currency: str = "USD") -> dict:
    """Record an errand and ask for it. Nothing is executed here."""
    problems = validate(site, kind, steps, ceiling)
    if problems:
        raise ValueError("; ".join(problems))
    digest = fingerprint(site, kind, steps, ceiling)
    approval_id = f"errand-{stateio.safe_id(errand_id, name='errand id')}"
    record = {
        "id": errand_id, "state": PROPOSED, "kind": kind, "site": site,
        "steps": steps, "ceiling": str(ceiling) if ceiling is not None else None,
        "currency": currency, "why": why, "sha256": digest,
        "approval": approval_id, "proposed_at": stateio.utcnow(),
    }
    stateio.write_json_atomic(_path(errand_id), record)
    spend = (f"; up to {currency} {ceiling}" if ceiling is not None else "")
    policy.request(
        approval_id,
        requested_action=f"{kind} on {site} ({len(steps)} step(s)){spend}",
        reason=why or f"errand {errand_id}",
        consequence=("money leaves your account" if kind in SPENDING_KINDS
                     else "this changes something on someone else's system"),
        reversible=False, capability="errand.run")
    journal.append("action", f"errand:{errand_id}",
                   f"{kind} proposed on {site} sha256:{digest[:16]} — "
                   f"awaiting {approval_id}", actor=ACTOR)
    return record


def load(errand_id: str) -> dict:
    return stateio.read_json(_path(errand_id))


def all_errands(state: str | None = None) -> list[dict]:
    out = []
    directory = errands_dir()
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            record = stateio.read_json(path)
        except ValueError:
            continue
        if state is None or record.get("state") == state:
            out.append(record)
    return out


def _finish(record: dict, state: str, **fields) -> dict:
    record["state"] = state
    record["finished_at"] = stateio.utcnow()
    record.update(fields)
    stateio.write_json_atomic(_path(record["id"]), record)
    journal.append("action", f"errand:{record['id']}",
                   f"{state}: {fields.get('detail', '')}"[:400], actor=ACTOR)
    return record


def run(errand_id: str, *, reader=None, interact=None) -> dict:
    """Execute an AUTHORIZED errand, or refuse and say why.

    `reader`/`interact` are seams: real life uses aletheia.browse, whose
    `interact` refuses before opening a browser unless the approval is
    APPROVED — so this function cannot be the only thing standing between
    a proposal and someone else's system.
    """
    record = load(errand_id)
    if record["state"] not in (PROPOSED, AUTHORIZED):
        return _finish(record, REFUSED,
                       detail=f"already {record['state']} — an errand runs once")
    if policy.halted():
        return _finish(record, REFUSED, detail="Aletheia is halted")
    if not policy.is_approved(record["approval"]):
        return _finish(record, REFUSED,
                       detail=f"approval {record['approval']} is not APPROVED")
    # Re-derive from what is stored NOW: the approval authorized one errand.
    digest = fingerprint(record["site"], record["kind"], record["steps"],
                         record.get("ceiling"))
    if digest != record["sha256"]:
        return _finish(record, REFUSED,
                       detail="the errand changed after it was approved — "
                              "refusing to run something else")

    from aletheia import browse
    reader = reader or browse.read_page
    interact = interact or browse.interact

    # Look BEFORE acting. A boundary or an over-ceiling total found on the
    # landing page costs nothing; found after the click it is too late.
    try:
        page = reader(record["site"])
    except Exception as exc:
        return _finish(record, FAILED,
                       detail=f"could not read {record['site']}: "
                              f"{type(exc).__name__}: {exc}")
    text = str(page.get("text", ""))

    hit = boundary_in(text)
    if hit:
        return _finish(record, AT_BOUNDARY, boundary=hit[0],
                       detail=hit[1],
                       remaining=f"open {record['site']} and finish it yourself")

    if record.get("ceiling") is not None:
        seen = observed_total(text)
        if seen is not None and seen > _money(record["ceiling"]):
            return _finish(
                record, REFUSED, observed_total=str(seen),
                detail=(f"the page totals {record['currency']} {seen}, over the "
                        f"{record['currency']} {record['ceiling']} you authorized"))
        record["observed_total"] = str(seen) if seen is not None else None

    record["state"] = RUNNING
    stateio.write_json_atomic(_path(errand_id), record)
    try:
        result = interact(record["site"], record["steps"], record["approval"])
    except Exception as exc:
        return _finish(record, FAILED,
                       detail=f"{type(exc).__name__}: {exc}")

    after = str((result or {}).get("text", ""))
    hit = boundary_in(after)
    if hit:
        return _finish(record, AT_BOUNDARY, boundary=hit[0], detail=hit[1],
                       remaining="the site handed the last step back to you",
                       evidence=result)
    # §30: completed means evidence, not "the clicks did not raise".
    return _finish(record, COMPLETED, evidence=result,
                   detail=f"{len(record['steps'])} step(s) executed on "
                          f"{record['site']}")


def run_authorized(reader=None, interact=None) -> list[dict]:
    """Run every proposed errand the operator has since approved.

    Called from the Core's runtime tick, which is what makes "Thea,
    approve" finish the job: the approval he gives by voice is picked up
    on a later beat and the errand runs then, outside the conversation
    that proposed it (§27).
    """
    done = []
    for record in all_errands(state=PROPOSED):
        if not policy.is_approved(record.get("approval", "")):
            continue
        try:
            done.append(run(record["id"], reader=reader, interact=interact))
        except Exception as exc:  # one bad errand must not stop the beat
            done.append(_finish(record, FAILED,
                                detail=f"{type(exc).__name__}: {exc}"))
    return done


def spoken(record: dict) -> str:
    """One sentence for the room."""
    if record["state"] == AT_BOUNDARY:
        return (f"I got as far as I can — {record.get('detail', 'it needs you')}. "
                f"{record.get('remaining', '')}").strip()
    if record["state"] == COMPLETED:
        return f"Done: {record.get('detail', record['kind'])}."
    if record["state"] == PROPOSED:
        return (f"Ready to {record['kind']} on {record['site']}. "
                f"Say approve to authorize it ({record['approval']}).")
    if record["state"] == REFUSED:
        return f"I didn't: {record.get('detail', 'refused')}."
    return f"{record['kind']} is {record['state']}."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gated errands in the world.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("id")
    p.add_argument("--site", required=True)
    p.add_argument("--kind", required=True, choices=sorted(KINDS))
    p.add_argument("--steps", required=True, help="JSON list of browser steps")
    p.add_argument("--ceiling", help="maximum to spend (purchases only)")
    p.add_argument("--why", default="")
    p_run = sub.add_parser("run")
    p_run.add_argument("id")
    p_list = sub.add_parser("list")
    p_list.add_argument("--state")
    p_show = sub.add_parser("show")
    p_show.add_argument("id")
    args = ap.parse_args(argv)

    if args.cmd == "new":
        record = propose(args.id, site=args.site, kind=args.kind,
                         steps=json.loads(args.steps), ceiling=args.ceiling,
                         why=args.why)
        print(spoken(record))
        return 0
    if args.cmd == "run":
        print(spoken(run(args.id)))
        return 0
    if args.cmd == "show":
        print(json.dumps(load(args.id), indent=2))
        return 0
    rows = all_errands(state=args.state)
    for record in rows:
        print(f"{record['id']:24} {record['state']:11} {record['kind']:12} "
              f"{record['site'][:44]}")
    print(f"{len(rows)} errand(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
