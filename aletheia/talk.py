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

    from aletheia import access, core
    if args.sandbox:
        # `tasks` and `plans` bind REPO paths at import time, so they are
        # redirected after the import rather than by an environment
        # variable. Anything she files during an audit lands here.
        from aletheia import plans, tasks
        room = Path(os.environ["ALETHEIA_JOURNAL_PATH"]).parent
        tasks.TASKS_DIR = room / "tasks"
        plans.PLANS_DIR = room / "plans"

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
