"""Say something to her from a keyboard, and see what the room would hear.

Every other way in needs something: the room voice needs a microphone,
the Command Center needs a browser, the intercom needs ChatGPT. So the
one thing nobody could do was the most obvious one — sit down and TALK to
her, end to end, through the real Core, and read the actual sentence that
comes back.

That gap was not academic. Twenty minutes of doing it on 2026-09-06 found
five defects that every test in the suite was passing straight over:

    "remind me at 3 to call the dentist"  -> 03:00 TOMORROW, confirmed
                                             back as "tomorrow at 8 am"
    "am I free tomorrow afternoon"        -> "free on 2026-09-07 at
                                             09:00, 09:15, 09:30, 09:45"
    "turn off the kitchen lights"         -> "I can't do room.scene yet;
                                             filed 1 build task(s)."

None of those is a crash. Each is correct data in a sentence that fails
him, and two of them are answers to a question he did not ask. Unit tests
do not catch this class, because a unit test asserts what the author
already believed. Reading it out loud does.

    python -m aletheia.talk "am I free tomorrow afternoon"
    python -m aletheia.talk --sandbox "remind me at 3 to call the dentist"
    python -m aletheia.talk            # one line at a time, until ctrl-D

It goes through `POST /api/voice` — the same door the microphone knocks
on — so the wake word, the deterministic verbs, the fast lane and the
planner all behave exactly as they do in the room, including the
follow-up wait for a slow answer. If a Core is already running it talks
to that one; otherwise it starts a private one and shuts it down after.

`--sandbox` points private state at a throwaway directory first, so an
audit does not leave real reminders in his stores. Without it you are
talking to the real Aletheia, which is the point.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

FOLLOWUP_TIMEOUT_S = 120.0
POLL_S = 0.5

# EVERY store that lives in the repository rather than in private state,
# and that a conversation can write to. Private state moves with
# ALETHEIA_PRIVATE_STATE; these do not, and each one missed here is a
# real thing an audit leaves behind on his actual machine.
#
# This list has been wrong twice. The first version redirected only
# private state and left three build tasks and a journal line in the
# repo. The second still missed `policy.HALT_PATH` — so asking her
# "halt" in a sandbox HALTED THE REAL ALETHEIA and left her halted, with
# every subsequent question answered "only a resume command executes".
# A kill switch is exactly the thing a test must not be able to reach.
#
# `tests/test_talk_sandbox.py` holds this against the modules, so the
# next store anchored at REPO_ROOT fails the suite instead of the audit.
SANDBOX_STORES = (
    ("aletheia.policy", "HALT_PATH", "policy/halt.json"),
    ("aletheia.policy", "APPROVALS_DIR", "policy/approvals"),
    ("aletheia.tasks", "TASKS_DIR", "tasks"),
    ("aletheia.plans", "PLANS_DIR", "plans"),
    ("aletheia.brief", "BRIEF_DIR", "brief"),
    ("aletheia.pulse", "PULSE_DIR", "pulse"),
    ("aletheia.mail", "MAIL_DIR", "mail"),
    ("aletheia.journal", "REPO_JOURNAL_DIR", "journal"),
    # "remember person bob bob@example.com" writes a real file here.
    ("aletheia.memory", "MEMORY_DIR", "memory"),
    ("aletheia.suggestions", "SUGGESTIONS_DIR", "exchange/suggestions"),
    ("aletheia.suggestions", "VERDICTS_PATH", "exchange/verdicts.json"),
    ("aletheia.intercom", "COMMANDS_DIR", "exchange/commands"),
    ("aletheia.sealed_observe", "SEALED_DIR", "exchange/commands/sealed"),
    # cache/, so gitignored — but still files on his machine, and a
    # browser profile is his real signed-in session.
    ("aletheia.computer", "CAPTURE_DIR", "cache/computer-captures"),
    ("aletheia.browse", "PROFILE_DIR", "cache/browser-profile"),
    # ---- anchored at his HOME, not the repo ---------------------------
    # Same problem, different root, and the AST check below scans for both
    # now. Only the ones a CONVERSATION can write to are moved: "turn
    # announcements on" writes announce.json, and asking for standing
    # authority mints a machine key.
    ("aletheia.announce", "CONFIG_FILE", "home/announce.json"),
    ("aletheia.advisor", "CONFIG_FILE", "home/advisor.json"),
    ("aletheia.machine_binding", "KEY_PATH", "home/machine.key"),
)

# Home-anchored paths a conversation can only READ. Redirecting these
# would make the sandbox test a DIFFERENT system — one where his mail and
# calendar are unconfigured — which is worse than useless for an audit.
# Nothing here is written without an explicit setup command.
SANDBOX_READ_ONLY_HOME = {
    ("aletheia.mail", "CONFIG_FILE"),
    ("aletheia.ics", "CONFIG_FILE"),
    ("aletheia.calendar_live", "CONFIG_FILE"),
    ("aletheia.apply", "HOME_CONFIG"),
    ("aletheia.voice_quality", "MODEL_ROOT"),
    ("aletheia.voice_room", "MODEL_DIR"),
    ("aletheia.voice_room", "VOICE_LOCK"),
    # The workspace moves by environment variable instead, because
    # `workspace.root()` reads ALETHEIA_WORKSPACE at call time.
    ("aletheia.workspace", "DEFAULT_ROOT"),
}

# Repo paths a conversation can only READ. Each is here on purpose: an
# audit that redirected these would be testing an empty registry rather
# than the real one.
SANDBOX_READ_ONLY = {
    ("aletheia.jobs", "BOARDS_PATH"),
    ("aletheia.fleet", "DEFAULT_PATH"),
    ("aletheia.capabilities", "DEFAULT_PATH"),
    ("aletheia.core", "INTERFACE_DIR"),
}


def _redirect_repo_stores(room: Path) -> list[str]:
    """Point every repo-anchored store at the throwaway room.

    Done by attribute rather than by environment because these bind at
    import time; the import has already happened by now.
    """
    import importlib
    moved = []
    for module_name, attribute, relative in SANDBOX_STORES:
        module = importlib.import_module(module_name)
        target = room / relative
        (target.parent if target.suffix else target).mkdir(parents=True, exist_ok=True)
        setattr(module, attribute, target)
        moved.append(f"{module_name}.{attribute}")
    return moved


def _post(base: str, path: str, payload: dict, secret: str) -> dict:
    request = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Aletheia-Local": secret},
        method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def _running_core(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=2):
            return True
    except Exception:
        return False


def ask(base: str, sentence: str, secret: str) -> tuple[float, str]:
    """One sentence in, one spoken answer out, with the wait it really took.

    The elapsed time INCLUDES collecting a follow-up. A reply that arrives
    as "Working on that." in 40ms and the real answer twenty seconds later
    took twenty seconds, and reporting the 40ms would be measuring the
    acknowledgement rather than the answer.
    """
    from aletheia import followups
    started = time.monotonic()
    reply = _post(base, "/api/voice", {"transcript": f"thea {sentence}"}, secret)
    said = str(reply.get("say") or "")
    slot_id = reply.get("followup_id")
    if slot_id:
        deadline = time.monotonic() + FOLLOWUP_TIMEOUT_S
        while time.monotonic() < deadline:
            slot = followups.poll(slot_id)
            if slot["state"] != followups.PENDING:
                said = str(slot.get("say") or said)
                break
            time.sleep(POLL_S)
        else:
            said = f"(no answer within {FOLLOWUP_TIMEOUT_S:.0f}s) {said}"
    return time.monotonic() - started, said


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Talk to Aletheia from a terminal, through the voice door.")
    ap.add_argument("sentence", nargs="*", help="what to say; omit to sit and talk")
    ap.add_argument("--sandbox", action="store_true",
                    help="throwaway private state, so an audit leaves no trace")
    ap.add_argument("--url", default="http://127.0.0.1:8765",
                    help="a Core to talk to (default: start a private one)")
    args = ap.parse_args(argv)

    if args.sandbox:
        # BEFORE importing anything that binds a store path at import time.
        #
        # ALL of it, not just private state. The first version set only
        # ALETHEIA_PRIVATE_STATE and still left real build tasks in
        # `state/tasks/` and real lines in the repo journal — a promise of
        # "leaves no trace" that left three files behind on its first run.
        room = Path(tempfile.mkdtemp(prefix="talk-"))
        os.environ["ALETHEIA_PRIVATE_STATE"] = str(room / "private")
        os.environ["ALETHEIA_JOURNAL_PATH"] = str(room / "journal.jsonl")
        # HER WORKSPACE IS REAL FILES IN HIS DOCUMENTS FOLDER. The third
        # miss: "write a file called notes.md" in a sandbox put
        # ~/Documents/Aletheia/notes.md on the actual disk, because the
        # workspace is anchored at Path.home() and the AST check only knew
        # about REPO_ROOT.
        os.environ["ALETHEIA_WORKSPACE"] = str(room / "workspace")
        (room / "workspace").mkdir(parents=True, exist_ok=True)
        # AND THE WORLD. Moving a store does not stop an email leaving or
        # a browser pressing Submit on a real site — so on his machine,
        # with mail configured, auditing her would have SENT things.
        # `intercom.rehearsing()` refuses the world-touching tier while
        # every local step still runs for real.
        os.environ["ALETHEIA_REHEARSAL"] = "1"

    from aletheia import access, core
    if args.sandbox:
        _redirect_repo_stores(Path(os.environ["ALETHEIA_JOURNAL_PATH"]).parent)

    server = None
    base = args.url
    if not _running_core(base):
        server = core.make_server(port=0)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        threading.Thread(target=server.serve_forever, daemon=True).start()
    secret = access.local_secret()

    def say_one(sentence: str) -> None:
        try:
            took, said = ask(base, sentence, secret)
        except Exception as exc:
            took, said = -1.0, f"({type(exc).__name__}: {exc})"
        print(f"  [{took:.1f}s] {said}" if took >= 0 else f"  {said}")

    try:
        if args.sentence:
            for sentence in args.sentence:
                print(f"\n> {sentence}")
                say_one(sentence)
        else:
            print("Talking to Aletheia. Ctrl-D to stop.")
            for line in sys.stdin:
                sentence = line.strip()
                if sentence:
                    say_one(sentence)
    finally:
        if server is not None:
            server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
