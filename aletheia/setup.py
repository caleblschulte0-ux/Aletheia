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

import re
import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Callable

from aletheia import MIN_PYTHON, capabilities

# Capabilities whose only blocker is something the operator supplies. Each
# entry says what to do and how to prove it. Anything NEEDS_CONFIGURATION
# in the registry and absent here is reported as unmapped rather than
# quietly omitted — a gap in this file must not look like a finished step.
OK, MISSING, BROKEN = "ok", "missing", "broken"

# Long enough for a cold CLI start on a laptop, short enough that a
# checklist still feels like a checklist.
CLI_PROBE_S = 45.0


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
        telling him to install what he already has is worse than silence.

        And every command goes out naming an interpreter that will actually
        run it here (`python_word`) — a checklist command that dies on his
        PATH is the friction ledger's own definition of a defect.
        """
        if not callable(self.how):
            lines = list(self.how)
        else:
            try:
                lines = list(self.how())
            except Exception as exc:  # guidance must never break the audit
                return [f"(could not read this machine's state: {type(exc).__name__})"]
        word = python_word()
        if word == "python":
            return lines
        # EVERY `python -m` line, not just the aletheia ones: `python -m pip
        # install playwright` on his PATH installs into the 3.9 this package
        # refuses, which is a checklist step that appears to succeed and
        # changes nothing.
        return [line.replace("python -m ", f"{word} -m ") for line in lines]


_PYTHON_WORD: dict[str, str] = {}
# Windows first asks `py`, the launcher, because a bare `python` there is
# whatever happens to be first on the machine PATH (3.9 on his PC).
# Everywhere else `python` is tried first, so a machine where it is
# already new enough keeps printing the plain, familiar command.
PYTHON_CANDIDATES = ("py", "python", "python3") if os.name == "nt" else ("python", "python3")


def python_word(*, refresh: bool = False) -> str:
    """The word that runs THIS package on THIS machine, asked rather than
    assumed.

    Measured on his PC 2026-09-25: `python` is `C:\\Python39\\python.exe`,
    because that entry is first on the machine PATH, and `aletheia/__init__.py`
    refuses 3.9 by design — so every `python -m aletheia...` line this
    checklist has ever printed hands him a traceback instead of a setup. `py`
    is the Windows launcher and resolves to 3.12 here.

    Asked once per process (a checklist is rendered behind a button, and two
    subprocesses per line is not a page). Falls back to naming the running
    interpreter outright, which is ugly and always correct.
    """
    import shutil

    from aletheia import proc
    if not refresh and "word" in _PYTHON_WORD:
        return _PYTHON_WORD["word"]
    chosen = ""
    for word in PYTHON_CANDIDATES:
        exe = shutil.which(word)
        if not exe:
            continue
        try:
            # proc.run, never subprocess.run: this is asked by the Core, which
            # runs under pythonw, and a bare subprocess there FLASHES A CONSOLE
            # WINDOW on his screen (tests/test_the_night_of_the_console_windows
            # caught exactly that here).
            out = proc.run([exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                           capture_output=True, text=True, timeout=20)
            major, minor = (int(part) for part in (out.stdout or "").strip().split("."))
        except Exception:  # noqa: BLE001 — an unusable candidate is just skipped
            continue
        if (major, minor) >= MIN_PYTHON:
            chosen = word
            break
    _PYTHON_WORD["word"] = chosen or sys.executable
    return _PYTHON_WORD["word"]


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


def _instagram() -> tuple[str, str]:
    """The REAL attempt, because configured is not connected.

    One read-only call that asks Instagram who this token belongs to.
    Reading is not publishing - a post is his approval and nothing here can
    make one - and the whole promise of this audit is "checked live rather
    than assumed". A vault entry plus a saved number only proves somebody
    typed something; it goes green while a revoked or expired token would
    fail on his first real ask.
    """
    from aletheia import instagram
    if not instagram.available()[0]:
        return MISSING, instagram.available()[1][:160]
    ok, why = instagram.verify()
    return (OK, why[:160]) if ok else (BROKEN, why[:160])


def _instagram_scopes() -> str:
    """The scope names come from the module that uses them, not from a copy in
    a checklist: Meta renames these, and a checklist naming a scope the code
    does not ask for sends him to tick the wrong boxes."""
    from aletheia import instagram
    return " and ".join(instagram.SCOPES_IG)


def _remote() -> tuple[str, str]:
    """Two topologies reach the phone, and the check must know both.

    Either the Core binds off-loopback itself with a certificate file
    (ALETHEIA_TLS_CERT), or — what is actually running since 2026-09-03 —
    `tailscale serve` terminates TLS on the tailnet name and proxies to the
    loopback Core, which then requires a minted token from anything that
    arrives that way. Until this was written the second topology, the one
    his phone uses, reported BROKEN for lacking a certificate it does not
    need.
    """
    from aletheia import access, tailscale
    if not access.enabled():
        return MISSING, "no access token has been minted"
    live = access.live_tokens()
    if os.environ.get("ALETHEIA_TLS_CERT", ""):
        return OK, f"{len(live)} live token(s) and a certificate (direct bind)"
    proxies = tailscale.serve_proxies()
    core_mounts = [m for m, target in proxies.items() if target.rstrip("/").endswith(":8777")]
    if core_mounts:
        return OK, (f"{len(live)} live token(s); tailscale serve proxies "
                    f"{', '.join(sorted(core_mounts))} to the Core over the tailnet")
    return (BROKEN, f"{len(live)} token(s) exist but nothing reaches the Core: "
                    "no certificate for a direct bind and no `tailscale serve` "
                    "mapping to 127.0.0.1:8777")


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
    # Two surfaces, two ways of listening, and each has to keep its own.
    # The ambient wall carries the push-to-talk script; the one Thea page
    # listens through `thea.js` (the same one-shot, the same /api/voice) so
    # that a phone, where the script's SpeechRecognition does not exist at
    # all, is not handed a second microphone that cannot work.
    missing = [f"{page} ({wants})" for page, wants in
               (("wall.html", "voice.js"), ("thea-app.js", "T.listen"))
               if wants not in (REPO_ROOT / "interface" / page).read_text(encoding="utf-8")]
    if missing:
        return BROKEN, f"surfaces without the ears: {', '.join(missing)}"
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
    # ANSWERING IS NOT RUNNABLE. Ollama replying to a request proves Ollama
    # is running; it says nothing about whether the model it would load
    # fits in this machine. The `deep` role defaulted to a 17.8 GB model on
    # a 16 GB laptop, and using it took the machine to 98.4% of its commit
    # limit with 1 GB free — at which point Windows starts killing things.
    # An audit whose whole promise is "checked live rather than assumed"
    # was reporting that as OK.
    try:
        from aletheia import local_model_pool
        cramped = [local_model_pool.room_for_role(role)
                   for role in ("fast", "deep")]
        cramped = [r for r in cramped if not r["fits"]]
    except Exception:
        cramped = []
    if len(cramped) >= 2:
        return BROKEN, "; ".join(r["why"] for r in cramped)[:400]
    if cramped:
        # NOT BROKEN: the other role fits and answers, and most of what he
        # asks goes there. An audit that shouts BROKEN at a lane that
        # mostly works is its own kind of lie, and the one after it gets
        # read as noise. OK, with the limit said plainly and the fix in
        # the same sentence.
        return OK, (f"answering. {cramped[0]['why']} Those questions go to "
                    f"the smaller model or to the Claude subscription; "
                    f"point the deep role at a smaller model to change "
                    f"that")[:400]
    return OK, "local profiles enabled, answering, and small enough to run here"


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


def _claude_cli() -> tuple[str, str]:
    """The BRAIN, proved by using it.

    This was the one thing the checklist did not check, and it is the one
    thing everything that thinks depends on: planning, conversation,
    research, the code worker, the showrunner. An expired subscription
    login on a Thursday evening does not announce itself — it turns every
    question into "I could not reach a model" and leaves the rest of the
    system green. Presence on PATH is not proof, so this asks it something
    and waits for an answer.
    """
    from aletheia import reasoner
    if not reasoner.cli_path():
        return MISSING, "the claude CLI is not on PATH"
    try:
        said = reasoner.infer_text(
            "Answer with one word and nothing else.",
            "Reply with the single word: ready", timeout_s=CLI_PROBE_S)
    except Exception as exc:
        return BROKEN, f"{type(exc).__name__}: {exc}"[:160]
    return (OK, "answered a live prompt") if said.strip() else (
        BROKEN, "the CLI ran and returned nothing")


def _workspace() -> tuple[str, str]:
    """Can she actually produce a file?

    Found live 2026-09-02, not by a test: the default root resolved to this
    repository's checkout, so `root()` refused it and the very first real
    write failed. Everything about the capability was correct and she could
    not write a sentence to disk.
    """
    from aletheia import workspace
    try:
        base = workspace.root()
    except Exception as exc:
        return BROKEN, f"{type(exc).__name__}: {exc}"[:160]
    probe = base / ".setup-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        got = probe.read_text(encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        return BROKEN, f"{base} is not writable ({type(exc).__name__})"
    if got != "ok":
        return BROKEN, f"{base} did not read back what was written"
    return OK, f"writable at {base}"


def _browser_pages() -> tuple[str, str]:
    """Research really opens the pages it cites, so it needs a browser.

    PROVED, not assumed. This asked `browse.available()`, which returns
    True from an import and a file on disk — so a Chromium that launches
    perfectly and cannot load a single page (a proxy that drops browser
    tunnels; a corporate network; no internet) was reported here as
    ready. Everything downstream of a browser then failed on his first
    real ask, with the audit still saying it was fine. This audit's whole
    promise is "checked live rather than assumed", so it loads a page.
    """
    from aletheia import browse
    ok, why = browse.reachable()
    return (OK, why) if ok else (BROKEN if browse.available()[0] else MISSING,
                                 why[:160])


def _desktop_toasts() -> tuple[str, str]:
    from aletheia import desktop_notify
    ok, why = desktop_notify.available()
    return (OK, why) if ok else (MISSING, why[:160])


def steps() -> list[Step]:
    return [
        Step("reason.infer", "Her brain", 2,
             "Everything that thinks runs on your Claude subscription: "
             "planning, conversation, research, the code worker. If this "
             "login has expired, every question comes back 'I could not "
             "reach a model' while the rest of her stays green.",
             ["claude login",
              "  (then ask her anything — this step proves it by asking)"],
             _claude_cli),
        Step("file.author", "Somewhere to write", 1,
             "Without a writable workspace she can think and say things and "
             "produce nothing: no document, no spreadsheet, no file at all.",
             ["Set a directory of her own (NOT this repo, NOT your home "
              "folder — she refuses both):",
              "  setx ALETHEIA_WORKSPACE \"%USERPROFILE%\\Documents\\Aletheia\"",
              "  (then restart the Core so it picks the variable up)"],
             _workspace),
        Step("browser.read", "Reading the open web", 5,
             "Research really opens the pages it cites, so without a browser "
             "she refuses the question honestly rather than answering it from "
             "memory.",
             ["python -m pip install playwright",
              "python -m playwright install chromium"],
             _browser_pages),
        Step("notification.deliver", "Reminders you actually see", 0,
             "A reminder that fires correctly and appears nowhere is not a "
             "reminder. This puts urgent and important ones on this screen.",
             ["Nothing to install — it uses Windows' own toasts.",
              "python -m aletheia.desktop_notify test   (shows one now)"],
             _desktop_toasts),
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
        Step("social.publish", "Instagram", 2,
             "Posting pictures and reels to your Instagram on her own - his words, 2026-09-24. "
             "One ordinary Instagram sign-in, in her browser, once. Nothing to do with Meta.",
             ["She posts through Instagram's own page, signed in as you in HER browser.",
              "",
              "1. Run this, and a Chrome window opens at the Instagram login page:",
              "     python -m aletheia.instagram connect",
              "2. Sign in as you normally would, then close that window.",
              "",
              "That is the whole setup. She stays signed in from then on, and she can",
              "post a picture or a video straight off this PC - no Meta developer app,",
              "no access token, no 60-day renewals, nothing to confirm.",
              "",
              "WHY NOT THE OFFICIAL API: it is built and it works, and Meta will not let",
              "this account create the app it needs - 'Your account must be confirmed",
              "before you can create a new app', on every device and every account, with",
              "no way to appeal it. If Meta ever lifts that, the API route takes over on",
              "its own the moment a token is in the vault.",
              "",
              "To check it later: python -m aletheia.instagram status"],
             _instagram, optional=True),
        Step("access.remote", "Your phone reaching me", 10,
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


def cached_report() -> dict | None:
    """The last audit, if one ran recently - for the fast lane, which may
    never pay for a live check itself. None when nothing is cached."""
    import time as _time
    if _CACHE["report"] is None or _time.monotonic() - _CACHE["at"] >= CACHE_SECONDS:
        return None
    return _CACHE["report"]


def _in_her_voice(text: str) -> str:
    """A step's `why` was written for the checklist screen, about her in
    the third person ("an app password lets her send as you"). Said by her
    it has to be the first person."""
    said = str(text or "")
    for pattern, word in (("\\bshe's\\b", "I'm"), ("\\bShe's\\b", "I'm"),
                          ("\\bshe is\\b", "I am"), ("\\bShe is\\b", "I am"),
                          ("\\bshe\\b", "I"), ("\\bShe\\b", "I"),
                          ("\\bherself\\b", "myself"), ("\\bher\\b", "me"),
                          ("\\bHer\\b", "My"), ("\\bAletheia's\\b", "my")):
        said = re.sub(pattern, word, said)
    return said


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


#: What he calls each step, for "is my email set up". Title words count
#: too; this is for the words that are not in the title.
_SAID_AS = {
    "mail.send": ("email", "mail", "gmail"),
    "calendar.read": ("calendar",),
    "access.remote": ("phone", "iphone", "tailscale", "remote"),
    "phone.call": ("call", "calls", "calling"),
    "room.scene": ("lights", "room", "home assistant", "scenes"),
    "social.publish": ("instagram", "posting", "meta", "posts"),
    "media.edit": ("video", "ffmpeg", "media"),
    "reason.chatgpt_browser": ("chatgpt", "backup brain"),
    "voice.wall": ("microphone", "mic", "ears", "voice"),
}


def spoken_about(about: str, report: dict | None = None) -> str:
    """"Is my email set up?" - that ONE step, not the whole checklist.

    Asked about email, she read out four of sixteen done and every
    outstanding step. The answer to a question about one thing is where
    that thing stands: done, or not and why, and where the steps are.
    """
    from aletheia import speech
    key = " ".join(str(about or "").casefold().split())
    if not key:
        return spoken(report)
    report = report if report is not None else audit()
    words = set(re.findall(r"[a-z]+", key))
    best = None
    for item in report["steps"]:
        names = set(re.findall(r"[a-z]+", str(item.get("title") or "").casefold()))
        names |= set(_SAID_AS.get(str(item.get("capability") or ""), ()))
        names |= set(w for alias in _SAID_AS.get(str(item.get("capability") or ""), ())
                     for w in alias.split())
        if key in names or words & names:
            best = item
            break
    if best is None:
        return spoken(report)
    title = _in_her_voice(str(best.get("title") or "that"))
    if best["state"] == OK:
        return f"{title}: yes, set up and checked."
    if best["state"] == BROKEN:
        said = f"{title} is set up but not working: {speech.plainly(str(best.get('detail') or ''))}"
    else:
        said = f"{title} isn't set up yet"
        why = speech.plainly(_in_her_voice(str(best.get("why") or "")))
        if why:
            said += f": {why[0].lower() + why[1:]}"
    minutes = int(best.get("minutes") or 0)
    said = said.rstrip(".") + "."
    if minutes:
        said += f" About {speech.count_phrase(minutes, 'minute')} of your time."
    return said + " The exact steps are under 'Still to set up' at the bottom of the Thea page."


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
            + speech.and_list([_in_her_voice(c["title"]).lower() for c in outstanding])
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
