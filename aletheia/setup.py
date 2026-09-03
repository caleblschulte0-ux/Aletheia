"""Your side, in one place — and proved rather than assumed.

Everything Aletheia still needs from the operator is a credential only he
can create: a calendar he consents to, a token from his own Home
Assistant, a certificate for his own machine, one supervised phone call.
Six of them, and until now they lived in four different documents with
four different shapes, each ending in "and then it should work".

Two things make that the wrong last mile. He will do three of the four and
stall on the one whose instructions were thinnest. And "it should work" is
not evidence — the registry would sit at NEEDS_CONFIGURATION while the
thing was fine, or worse, flip to AVAILABLE while it wasn't.

So this is a checklist that CHECKS. Every item names exactly what is
missing, exactly what to run, and carries a `verify()` that proves the
thing actually works before anything claims it does: a real IMAP login, a
real calendar read, a real request to the hub, a real token round-trip.
Nothing here flips a registry entry on faith (§30, §106).

It also refuses to be the one place that drifts. The list of what is
outstanding comes from `config/capabilities.json` at run time — the
registry is the source of truth for what is configured and this reads it,
rather than keeping a second copy that will disagree by Friday.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Callable

from aletheia import capabilities

# Capabilities whose only blocker is something the operator supplies. Each
# entry says what to do and how to prove it. Anything NEEDS_CONFIGURATION
# in the registry and absent here is reported as unmapped rather than
# quietly omitted — a gap in this file must not look like a finished step.
OK, MISSING, BROKEN = "ok", "missing", "broken"


@dataclass
class Step:
    capability: str
    title: str
    minutes: int
    why: str
    how: "list[str] | Callable[[], list[str]]"
    verify: Callable[[], tuple[str, str]]
    optional: bool = False
    tags: list[str] = field(default_factory=list)

    def instructions(self) -> list[str]:
        """The lines to show him now. A step whose next command depends on
        this machine computes them (`_remote_how` reads Tailscale), because
        telling him to install what he already has is worse than silence."""
        if not callable(self.how):
            return list(self.how)
        try:
            return list(self.how())
        except Exception as exc:      # guidance must never break the audit
            return [f"(could not read this machine's state: {type(exc).__name__})"]


EMPTY_CALENDAR = ("read live, and it is EMPTY (0 events in the next 60 days) — "
                  "'am I free?' will answer yes to every hour. If that is wrong, "
                  "the schedule lives on a different calendar than the feed given")


def _calendar() -> tuple[str, str]:
    """Configured is not read (§30). This fetches.

    2026-09-02: the operator connected a secret-ICS feed and this said
    "1 secret-ICS feed(s) configured" — the count of a config entry, never
    a request. A revoked URL, a typo, or an empty calendar all reported
    ok, and this module's own docstring promises "a real calendar read".
    Now it refreshes, and an empty mirror is SAID rather than passed off
    as a working calendar: answering "yes, you are free" from a calendar
    with nothing in it is the wrong-answer failure `aletheia.ics` warns
    about, not a small one.
    """
    from aletheia import calendar_live, ics
    ok, why = calendar_live.available()
    if ok:
        try:
            result = calendar_live.refresh(transport=None)
            mirrored = int((result or {}).get("mirrored", 0))
            provider = calendar_live.config()["provider"]
            if mirrored:
                return OK, f"official provider live ({provider}); {mirrored} event(s) mirrored"
            return OK, f"official provider live ({provider}); {EMPTY_CALENDAR}"
        except Exception as exc:
            return BROKEN, f"configured but failing: {type(exc).__name__}: {exc}"[:160]
    try:
        feeds = ics._config().get("feeds", [])
    except Exception:
        feeds = []
    if not feeds:
        return MISSING, why[:160]
    try:
        result = ics.refresh()
    except Exception as exc:
        return BROKEN, (f"{len(feeds)} feed(s) configured but the fetch failed: "
                        f"{type(exc).__name__}: {exc}")[:160]
    mirrored = int((result or {}).get("mirrored", 0))
    unsupported = int((result or {}).get("unsupported", 0))
    tail = f"; {unsupported} recurrence(s) this parser cannot expand" if unsupported else ""
    if mirrored:
        return OK, f"{len(feeds)} feed(s) read; {mirrored} event(s) mirrored{tail}"
    return OK, f"{len(feeds)} feed(s) {EMPTY_CALENDAR}{tail}"


def _room() -> tuple[str, str]:
    from aletheia import hass
    ok, why = hass.available()
    if not ok:
        return MISSING, why[:160]
    reachable, detail = hass.ping()
    return (OK, detail[:160]) if reachable else (BROKEN, detail[:160])


def _remote() -> tuple[str, str]:
    from aletheia import access
    if not access.enabled():
        return MISSING, "no access token has been minted"
    live = access.live_tokens()
    cert = os.environ.get("ALETHEIA_TLS_CERT", "")
    if not cert:
        return (BROKEN, f"{len(live)} token(s) exist but no TLS certificate is "
                        "configured, so the Core still refuses to listen off-loopback")
    return OK, f"{len(live)} live token(s) and a certificate"


def _remote_how() -> list[str]:
    """What is actually left for the phone to reach her, on THIS machine."""
    from aletheia import tailscale
    current = tailscale.state()
    if not current.installed:
        lines = ["winget install Tailscale.Tailscale     (not installed yet)",
                 "Sign in, then re-run this checklist for the exact cert command."]
    elif not current.ready:
        lines = [f"Tailscale is installed but {current.backend or 'not signed in'} "
                 "— open it and sign in, then re-run this checklist.",
                 tailscale.cert_command(current)]
    else:
        lines = [f"Tailscale is signed in as {current.dns_name} — that part is done.",
                 tailscale.cert_command(current)
                 + "     (run in an elevated PowerShell; writes .crt and .key here)"]
    return lines + ["python -m aletheia.apply phone-access   (mints the token and "
                    "prints the rest with your values filled in)"]


def _phone() -> tuple[str, str]:
    from aletheia import phone_windows
    report = phone_windows.preflight()
    if not report["transport_available"]:
        return MISSING, str(report["reason"])[:160]
    entry = capabilities.get("phone.call")
    if entry["status"] != "AVAILABLE":
        return (MISSING, "the machine is ready; no call has been placed, so this "
                         "stays EXPERIMENTAL until one round-trips")
    return OK, "a call has completed end to end"


def _mail() -> tuple[str, str]:
    from aletheia import mail
    ok, why = mail.available()
    if not ok:
        return MISSING, why[:160]
    try:
        mail.SmtpImapTransport().fetch_unread(1)
    except Exception as exc:
        return BROKEN, f"configured but the mailbox refused: {type(exc).__name__}"
    return OK, "a real IMAP login succeeded"


def _advisor() -> tuple[str, str]:
    from aletheia import advisor
    ok, why = advisor.available()
    return (OK, why[:160]) if ok else (MISSING, why[:160])


def _standing() -> tuple[str, str]:
    from aletheia import standing
    grant = standing.active()
    if not grant:
        return MISSING, "she still asks about every routine plan"
    return OK, f"routine tier granted until {grant['expires']}"


def _relay() -> tuple[str, str]:
    """Has a command ever actually arrived from the ChatGPT project?

    Presence of the contract file proves nothing — it ships with the repo.
    A relayed command in exchange/commands is the only evidence that the
    project was really created and really works.
    """
    from aletheia.fleet import REPO_ROOT
    directory = REPO_ROOT / "exchange" / "commands"
    if not directory.is_dir():
        return MISSING, "no command has ever been relayed"
    relayed = sorted(directory.glob("*.json"))
    if not relayed:
        return MISSING, "no command has ever been relayed"
    return OK, f"{len(relayed)} relayed command(s) on record"


def _wall_voice() -> tuple[str, str]:
    """The pages carry the ears; the microphone permission is the browser's.

    This can be checked as far as the server can see and no further — the
    grant lives in his browser, so claiming it works would be a guess.
    """
    from aletheia.fleet import REPO_ROOT
    script = REPO_ROOT / "interface" / "voice.js"
    if not script.is_file():
        return BROKEN, "interface/voice.js is missing"
    pages = [p for p in ("index.html", "command.html")
             if "voice.js" not in (REPO_ROOT / "interface" / p).read_text(encoding="utf-8")]
    if pages:
        return BROKEN, f"pages without the ears: {', '.join(pages)}"
    return MISSING, ("served and wired; the microphone permission is granted in "
                     "your browser and cannot be checked from here")


def _local_ai() -> tuple[str, str]:
    """Offline reasoning is a fallback, never an authority — see the note in
    the checklist step. Reports what the gateway ACTUALLY has, not what is
    installable."""
    from aletheia import reasoning_gateway
    try:
        status = reasoning_gateway.status()
    except Exception as exc:
        return BROKEN, f"{type(exc).__name__}: {exc}"[:160]
    local = status.get("local", {})
    if not local.get("enabled"):
        return MISSING, f"local routing disabled ({local.get('enabled_source', 'default')})"
    offline = [name for name, p in (local.get("profiles") or {}).items()
               if not p.get("online")]
    if offline:
        return BROKEN, f"enabled but these profiles are not answering: {', '.join(offline)}"
    return OK, "local profiles enabled and answering"


def _chatgpt_browser() -> tuple[str, str]:
    from aletheia import chatgpt_session
    try:
        status = chatgpt_session.status()
    except Exception as exc:
        return BROKEN, f"{type(exc).__name__}: {exc}"[:160]
    if status.get("ready"):
        return OK, "browser profile initialized and signed in"
    return MISSING, str(status.get("reason", "not ready"))[:160]


def _ffmpeg() -> tuple[str, str]:
    """ffmpeg is a program, not a package — she cannot install it herself,
    and saying so is more use than a capability quietly reading UNAVAILABLE."""
    from aletheia import media
    ok, why = media.available()
    return (OK, why) if ok else (MISSING, why[:160])


def steps() -> list[Step]:
    return [
        Step("email.read", "Email", 0,
             "She can already read headers and send with your approval.",
             ["Nothing to do — this is already configured."], _mail),
        Step("calendar.read", "Calendar", 2,
             "Without it she cannot answer 'am I free', propose meeting times, "
             "or finish a meeting negotiation.",
             ["In Google Calendar: Settings -> your calendar -> "
              "'Secret address in iCal format' -> copy.",
              "python -m aletheia.apply calendar \"<paste the URL>\"",
              "",
              "That is read-only and takes two minutes. Only if you want her to "
              "BOOK as well:",
              "python -m aletheia.calendar_auth google --enable-writes",
              "  (needs a Google Cloud OAuth client — twenty minutes of "
              "unrelated setup, so do it later or never)"],
             _calendar),
        Step("room.scene", "The room", 5,
             "Lights, scenes and media — IF you run Home Assistant. Nothing on "
             "this network answers on port 8123, so this may not apply to you "
             "at all.",
             ["Only if you already run Home Assistant:",
              "  Profile -> Long-lived access tokens -> Create.",
              "  python -m aletheia.apply room http://<hub>:8123 <token>",
              "",
              "If you do not run one, this is not a five-minute task — it is "
              "installing a home automation platform. Skip it until you want one."],
             _room, optional=True),
        Step("access.remote", "Your phone reaching her", 10,
             "The phone surface has existed since Phase 21 and no phone could "
             "load it.",
             _remote_how,
             _remote),
        Step("phone.call", "The first phone call", 5,
             "Every mechanism is verified; no call has been placed, and placing "
             "one reaches a real network.",
             ["python -m aletheia.phone_cli ready            (should say True)",
              "Pick a safe number — your own voicemail is ideal.",
              "Then ask me to walk the call plan, approval and dial with you."],
             _phone),
        Step("intercom.relay", "Talking to her through ChatGPT", 10,
             "A second way in that needs no API key: your voice through the "
             "ChatGPT app, relayed as gated commands.",
             ["Open exchange/CHATGPT_PROJECT.md and paste it into a new "
              "ChatGPT Project's instructions.",
              "Connect the GitHub connector to this repository.",
              "Then say something to it and check: python -m aletheia.intercom list"],
             _relay, optional=True),
        Step("media.edit", "Editing video and audio", 3,
             "Trimming clips, joining them, pulling the audio out, burning in "
             "captions. The code is finished; it needs the tool it drives.",
             ["winget install Gyan.FFmpeg",
              "Then open a NEW terminal (PATH only updates for new ones) and:",
              "  python -m aletheia.media check"],
             _ffmpeg, optional=True),
        Step("reason.local", "Thinking with no internet", 20,
             "Offline models so she still interprets and plans when the "
             "subscriptions are unreachable. She will NOT use them to decide "
             "anything critical or to write code — that stays on the "
             "subscriptions and fails honestly rather than quietly dropping "
             "to a smaller brain.",
             ["Install Ollama, then: python -m aletheia.local_ai",
              "It pulls the models and runs a real smoke test; local routing "
              "only turns on if that passes."],
             _local_ai, optional=True),
        Step("reason.chatgpt_browser", "Your ChatGPT as a backup brain", 5,
             "If the Claude CLI is out, she can fall back to your signed-in "
             "ChatGPT in a real browser — no API key. It is deliberately "
             "FOREGROUND-ONLY: nothing always-on (the Core, the voice room, "
             "the project loop, any scheduled job) can open a ChatGPT window "
             "on your screen while you are not there.",
             ["python -m aletheia.chatgpt_session  (opens a browser; sign in once)",
              "Then, only in a shell you started yourself:",
              "  set ALETHEIA_ALLOW_CHATGPT_BROWSER_REASONING=1"],
             _chatgpt_browser, optional=True),
        Step("voice.wall", "The wall's own ears", 1,
             "The wall and Command Center can hear 'Thea' directly in the "
             "browser — no side app.",
             ["Open http://127.0.0.1:8777/ and click 'click to give Thea ears'.",
              "Allow the microphone once; the browser remembers it."],
             _wall_voice, optional=True),
        Step("policy.delegate", "Stop being asked about trivia", 1,
             "Routine plans — reminders, tasks, notes — need a decision every "
             "time until you say yes once.",
             ["python -m aletheia.standing on"],
             _standing, optional=True),
        Step("advisor.triage", "Let her notice things", 1,
             "Off by default. Building a proactive brain is not permission to "
             "run one.",
             ["python -m aletheia.advisor configure --enable"],
             _advisor, optional=True),
    ]


# Verifying is deliberately expensive — real logins, real requests — and the
# answer changes about as often as he creates a credential. A short cache
# keeps a second question instant without ever serving a stale "done".
_CACHE: dict = {"at": 0.0, "report": None}
CACHE_SECONDS = 60.0


def audit(*, fresh: bool = False) -> dict:
    """Every step, checked live. Never claims a thing works without proof."""
    import time as _time
    if not fresh and _CACHE["report"] is not None:
        if _time.monotonic() - _CACHE["at"] < CACHE_SECONDS:
            return _CACHE["report"]
    report = _audit_now()
    _CACHE.update({"at": _time.monotonic(), "report": report})
    return report


def _audit_now() -> dict:
    checked = []
    for step in steps():
        try:
            state, detail = step.verify()
        except Exception as exc:
            state, detail = BROKEN, f"{type(exc).__name__}: {exc}"[:160]
        checked.append({"capability": step.capability, "title": step.title,
                        "state": state, "detail": detail,
                        "minutes": step.minutes, "optional": step.optional,
                        "how": step.instructions(), "why": step.why})
    mapped = {s.capability for s in steps()}
    reg = capabilities.load_registry()
    unmapped = sorted(c["id"] for c in reg["capabilities"]
                      if c["status"] == "NEEDS_CONFIGURATION" and c["id"] not in mapped)
    remaining = [c for c in checked if c["state"] != OK and not c["optional"]]
    return {
        "steps": checked,
        "unmapped_needs_configuration": unmapped,
        "done": sum(1 for c in checked if c["state"] == OK),
        "total": len(checked),
        "minutes_left": sum(c["minutes"] for c in remaining),
        "ready": not remaining,
    }


def render(report: dict) -> str:
    mark = {OK: "[x]", MISSING: "[ ]", BROKEN: "[!]"}
    lines = ["", "  YOUR SIDE", "  " + "-" * 58]
    for item in report["steps"]:
        tail = " (optional)" if item["optional"] else ""
        lines.append(f"  {mark[item['state']]} {item['title']}{tail}")
        lines.append(f"      {item['detail']}")
        if item["state"] != OK:
            lines.append(f"      why: {item['why']}")
            for line in item["how"]:
                lines.append(f"      $ {line}" if not line.startswith(" ") else f"      {line}")
        lines.append("")
    if report["unmapped_needs_configuration"]:
        lines.append("  Not covered by this checklist (tell me and I'll add them):")
        for cid in report["unmapped_needs_configuration"]:
            lines.append(f"      - {cid}")
        lines.append("")
    if report["ready"]:
        lines.append("  Everything required is configured and verified.")
    else:
        lines.append(f"  {report['done']}/{report['total']} done · "
                     f"about {report['minutes_left']} minutes of your time left")
    lines.append("")
    return "\n".join(lines)


def spoken(report: dict | None = None) -> str:
    """The checklist as one sentence, for the room."""
    from aletheia import speech
    report = report if report is not None else audit()
    if report["ready"]:
        extras = [c["title"] for c in report["steps"]
                  if c["optional"] and c["state"] != OK]
        said = "Everything I need from you is done and verified."
        if extras:
            said += (" Optional and still off: " + speech.and_list(extras) + ".")
        return said
    outstanding = [c for c in report["steps"]
                   if c["state"] != OK and not c["optional"]]
    broken = [c["title"] for c in report["steps"] if c["state"] == BROKEN]
    said = (f"{report['done']} of {report['total']} done. I still need "
            + speech.and_list([c["title"].lower() for c in outstanding])
            + f" — about {report['minutes_left']} minutes of your time.")
    if broken:
        said += (" " + speech.and_list(broken)
                 + (" is" if len(broken) == 1 else " are")
                 + " configured but failing.")
    return said


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="What Aletheia still needs from you, checked live.")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args(argv)
    report = audit()
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
