"""The local Core V0 — Aletheia as a persistent service (Playbook §§108–110).

Runs on the operator's Windows PC (or anywhere Python runs):

    python -m aletheia.core            # http://127.0.0.1:8777

One process, stdlib only, serving the internal API every interface uses
(§110) plus the static interfaces (the wall at `/`, the Command Center at
`/command.html`). It executes commands through the SAME grammar and
gates as the intercom — `intercom.validate_kind_args` →
`intercom.execute_command` → policy/halt/front-door checks → journal —
so voice-via-ChatGPT and the local console can never drift apart.

The repo working copy is the durable memory: the Core reads and writes
the same `state/`, `plans/`, `memory/` stores. Sync with GitHub stays
git's job (the operator pulls/pushes, or a scheduled `git pull` keeps
the mirror fresh); the Core never invents a second source of truth.

Security V0: binds 127.0.0.1 ONLY by default — the API is the
operator's own machine talking to itself. Exposing it further needs
authentication that does not exist yet; `--host` therefore refuses
non-loopback values rather than pretending (§59 fail closed).

The Core is also the PC-side half of the intercom: a background sync
loop (aletheia.sync) pulls the repo, executes commands whose kind is in
`intercom.LOCAL_KINDS` (the real browser lives here, not in Actions),
and pushes the receipts + journal back — so a voice command reaches the
PC with no human running git. `--no-sync` disables it; outside a cloned
repo it degrades honestly (loop OFF, /api/sync says why).

API:
    GET  /api/status        halt state, pulse meta, task/approval counts
    GET  /api/sync          the sync loop's live state (last tick, pull/push)
    GET  /api/tasks         every task
    GET  /api/approvals     every approval
    GET  /api/capabilities  the capability registry
    GET  /api/journal?last=N
    GET  /api/computer/status
    POST /api/command       {"kind": …, …args} (+optional "operator_quote")
                            → {outcome, detail}, executed inline, journaled
    POST /api/computer      {steps, approval_id}
                            → executes only through computer.execute gates
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aletheia import act, capabilities, computer, intercom, journal, policy, tasks
from aletheia.fleet import REPO_ROOT, load_fleet
from aletheia.pulse import PULSE_DIR
from aletheia.sync import GitSync

INTERFACE_DIR = REPO_ROOT / "interface"
ACTOR = "operator-local-core"
DEFAULT_PORT = 8777
MAX_BODY_BYTES = 64 * 1024
SYNC_INTERVAL_S = 60

# live view of the sync loop, served at /api/sync — mutated only by core_tick
SYNC_STATUS: dict = {"enabled": False, "last_tick": None, "pull": None,
                     "push": None, "commands_executed": 0}


def status_payload() -> dict:
    pulse_meta = {}
    latest = PULSE_DIR / "latest.json"
    if latest.exists():
        try:
            p = json.loads(latest.read_text(encoding="utf-8"))
            pulse_meta = {
                "generated_at": p.get("generated_at"),
                "alerts": len(p.get("alerts") or []),
                "plans_open": (p.get("plans") or {}).get("open", 0),
            }
        except json.JSONDecodeError:
            pulse_meta = {"error": "pulse unreadable"}
    all_t = tasks.all_tasks()
    return {
        "halted": policy.halted(),
        "pulse": pulse_meta,
        "tasks": {
            "total": len(all_t),
            "live": sum(1 for t in all_t
                        if t["status"] not in ("COMPLETED", "CANCELLED", "FAILED_TERMINAL")),
            "ready": [t["id"] for t in tasks.ready()],
        },
        "approvals_pending": [a["id"] for a in policy.all_approvals()
                              if a["state"] == "PENDING"],
    }


def run_command(payload: dict, fleet: dict) -> dict:
    """The Core's command path — same grammar, same gates, inline answer."""
    quote = str(payload.pop("operator_quote", "typed into the local command center"))
    problems = intercom.validate_kind_args(payload, fleet)
    if problems:
        return {"outcome": "invalid", "detail": "; ".join(problems)}
    if policy.halted() and payload["kind"] != "resume":
        return {"outcome": "halted",
                "detail": "Aletheia is halted — only a resume command executes"}
    try:
        result = {"outcome": "done",
                  "detail": intercom.execute_command(payload, fleet, quote=quote)}
    except act.Refused as exc:
        result = {"outcome": "refused", "detail": str(exc)}
    except Exception as exc:
        result = {"outcome": "error", "detail": f"{type(exc).__name__}: {exc}"}
    journal.append("action", f"core:{payload.get('kind')}",
                   f"{result['outcome']} — {result['detail']}", actor=ACTOR)
    return result


# a pulled commit touching these means the RUNNING process is now stale
CODE_PATHS = ["aletheia", "interface", "config", "requirements-optional.txt"]
RESTART_EXIT_CODE = 42  # tells the supervisor: relaunch me, this is not a crash


def core_tick(syncer: GitSync, fleet: dict, status: dict = SYNC_STATUS,
              on_code_update=None) -> dict:
    """One beat of the Core's sync loop — synchronous and fully testable.

    pull (new commands arrive) -> execute pending LOCAL kinds through the
    intercom's own gates -> push receipts + journal. Never raises: every
    failure lands in `status` (served at /api/sync) and is retried next
    tick. Journal only state CHANGES, so an offline weekend is two lines,
    not two thousand.

    Self-update: when a pull brings commits touching CODE_PATHS, the
    running process is stale — `on_code_update(changed_files)` is called
    (the Core uses it to exit RESTART_EXIT_CODE for the supervisor).
    State-only commits (pulse, receipts, journal) never trigger it.
    """
    status["last_tick"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev_pull = status.get("pull")
    before = syncer.head()
    ok, detail = syncer.pull()
    status["pull"] = {"ok": ok, "detail": detail}
    if prev_pull is not None and prev_pull.get("ok") != ok:
        journal.append("event", "core:sync",
                       f"pull {'recovered' if ok else 'failing'}: {detail}", actor=ACTOR)
    if ok and before:
        after = syncer.head()
        if after and after != before:
            changed = syncer.changed_paths(before, after, CODE_PATHS)
            status["head"] = after
            if changed and on_code_update is not None:
                journal.append("event", "core:sync",
                               f"code updated ({len(changed)} file(s), now at "
                               f"{after[:10]}) — restarting to run it", actor=ACTOR)
                on_code_update(changed)
                return status  # restarting; skip command processing this tick
    results = []
    try:
        results = intercom.run_pending(fleet, commands_dir=None, side="local")
    except Exception as exc:  # a broken command must not stop the loop
        journal.append("event", "core:sync",
                       f"local command processing error: {type(exc).__name__}: {exc}",
                       actor=ACTOR)
    if results:
        status["commands_executed"] += len(results)
        ok, detail = syncer.commit_push(
            ["exchange/commands", "state/journal"],
            f"core: {len(results)} local command receipt(s)")
        status["push"] = {"ok": ok, "detail": detail}
        if not ok:
            journal.append("event", "core:sync", f"push failed: {detail}", actor=ACTOR)
    return status


class Handler(BaseHTTPRequestHandler):
    fleet: dict = {}
    computer_backend_factory = None

    def log_message(self, fmt, *args):  # quiet by default; journal is the record
        pass

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, rel: str) -> None:
        target = (INTERFACE_DIR / rel).resolve()
        if not str(target).startswith(str(INTERFACE_DIR.resolve())) or not target.is_file():
            self.send_error(404)
            return
        ctype = {"html": "text/html", "json": "application/json",
                 "js": "text/javascript", "css": "text/css"}.get(
                     target.suffix.lstrip("."), "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _payload(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if length <= 0:
            raise ValueError("request body is empty")
        if length > MAX_BODY_BYTES:
            raise ValueError(f"request body exceeds {MAX_BODY_BYTES} bytes")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        return payload

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/status":
            return self._json(status_payload())
        if url.path == "/api/tasks":
            return self._json(tasks.all_tasks())
        if url.path == "/api/approvals":
            return self._json(policy.all_approvals())
        if url.path == "/api/capabilities":
            return self._json(capabilities.load_registry())
        if url.path == "/api/computer/status":
            ok, reason = computer.available()
            entry = capabilities.get("computer.control")
            return self._json({
                "available_locally": ok,
                "reason": reason,
                "registry_status": entry["status"],
                # what the registry says is unverified — never a frozen literal
                "registry_notes": entry.get("notes", ""),
            })
        if url.path == "/api/sync":
            return self._json(SYNC_STATUS)
        if url.path == "/api/kinds":
            # the command grammar, straight from the validator — the
            # Command Center renders THIS, never its own copy
            return self._json({k: [sorted(req), sorted(opt)]
                               for k, (req, opt) in intercom.KIND_ARGS.items()})
        if url.path == "/api/journal":
            last = int(parse_qs(url.query).get("last", ["50"])[0])
            return self._json(journal.entries()[-last:])
        if url.path.startswith("/state/pulse/"):
            # the wall fetches ../state/pulse/latest.json — serve it read-only
            target = (REPO_ROOT / url.path.lstrip("/")).resolve()
            if str(target).startswith(str((REPO_ROOT / "state").resolve())) and target.is_file():
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return self.send_error(404)
        rel = "index.html" if url.path in ("/", "/interface/", "/interface/index.html") \
            else url.path.removeprefix("/interface/").lstrip("/")
        return self._static(rel)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/command", "/api/computer", "/api/voice"):
            return self.send_error(404)
        try:
            payload = self._payload()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json({"outcome": "invalid", "detail": str(exc)}, code=400)
        if path == "/api/command":
            return self._json(run_command(payload, self.fleet))
        if path == "/api/voice":
            from aletheia import voice
            transcript = payload.get("transcript")
            if not isinstance(transcript, str) or not transcript.strip():
                return self._json({"outcome": "invalid",
                                   "detail": "transcript must be a non-empty string"},
                                  code=400)
            intent = voice.interpret(transcript)
            if intent["command"] is None:
                return self._json({"outcome": "answered", "say": intent["say"]})
            cmd = dict(intent["command"])
            kind = cmd.get("kind")
            result = run_command(
                {**cmd, "operator_quote": f"spoken to the wall: {transcript[:200]}"},
                self.fleet)
            # a fallback intent carries its own words (e.g. "no command for
            # that, journaled") — those beat the generic receipt phrasing
            say = intent["say"] or voice.spoken_reply(kind, result["outcome"],
                                                      result["detail"])
            return self._json({**result, "say": say})

        unknown = set(payload) - {"steps", "approval_id"}
        if unknown:
            return self._json(
                {"outcome": "invalid", "detail": f"unsupported fields {sorted(unknown)}"},
                code=400)
        approval_id = payload.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id:
            return self._json(
                {"outcome": "invalid", "detail": "approval_id must be a non-empty string"},
                code=400)
        try:
            result = computer.execute(
                payload.get("steps"), approval_id,
                requested_by="operator-local-core",
                backend_factory=self.computer_backend_factory)
        except computer.ApprovalRequired as exc:
            return self._json({"outcome": "refused", "detail": str(exc)}, code=403)
        except policy.Halted as exc:
            return self._json({"outcome": "halted", "detail": str(exc)}, code=409)
        except ValueError as exc:
            return self._json({"outcome": "invalid", "detail": str(exc)}, code=400)
        except RuntimeError as exc:
            return self._json(
                {"outcome": "unavailable", "detail": f"{type(exc).__name__}: {exc}"},
                code=503)
        except Exception as exc:
            return self._json(
                {"outcome": "error", "detail": f"{type(exc).__name__}: {exc}"},
                code=500)
        return self._json({"outcome": "done", "result": result})


def make_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                computer_backend_factory=None) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError(
            "the Core V0 has no authentication — it binds loopback only (§59 fail closed)")
    class BoundHandler(Handler):
        pass

    BoundHandler.fleet = load_fleet()
    BoundHandler.computer_backend_factory = (
        staticmethod(computer_backend_factory) if computer_backend_factory else None)
    return ThreadingHTTPServer((host, port), BoundHandler)


def start_sync_loop(fleet: dict, interval_s: float = SYNC_INTERVAL_S,
                    stop: threading.Event | None = None,
                    on_code_update=None) -> threading.Event:
    """Run core_tick forever in a daemon thread; returns the stop event.

    Enabled only when the working copy honestly has a usable remote —
    otherwise SYNC_STATUS says why and the Core still serves everything
    local-only, degraded rather than dead.
    """
    stop = stop or threading.Event()
    syncer = GitSync()
    ok, detail = syncer.available()
    SYNC_STATUS["enabled"] = ok
    SYNC_STATUS["remote"] = detail
    if not ok:
        journal.append("event", "core:sync",
                       f"sync loop OFF — {detail}; voice commands needing the PC "
                       "will wait until the Core runs inside a cloned repo", actor=ACTOR)
        return stop

    def loop():
        while not stop.is_set():
            core_tick(syncer, fleet, on_code_update=on_code_update)
            stop.wait(interval_s)

    threading.Thread(target=loop, name="core-sync", daemon=True).start()
    journal.append("event", "core:sync",
                   f"sync loop ON every {interval_s:g}s — {detail}", actor=ACTOR)
    return stop


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia local Core V0.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--sync-interval", type=float, default=SYNC_INTERVAL_S,
                    help="seconds between pull/process/push beats (default 60)")
    ap.add_argument("--no-sync", action="store_true",
                    help="serve the API only; no git sync, no local command processing")
    args = ap.parse_args(argv)
    server = make_server(args.host, args.port)
    restarting = threading.Event()

    def on_code_update(changed):
        # runs on the sync thread; shutdown() unblocks serve_forever below
        restarting.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    if not args.no_sync:
        start_sync_loop(load_fleet(), interval_s=args.sync_interval,
                        on_code_update=on_code_update)
    journal.append("event", "core", f"local Core up on {args.host}:{args.port}")
    print(f"Aletheia Core: http://{args.host}:{args.port}  "
          f"(wall at /, command center at /command.html) — Ctrl+C stops")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        journal.append("event", "core", "local Core stopped")
        return 0
    if restarting.is_set():
        if os.environ.get("ALETHEIA_SUPERVISED") == "1":
            # the supervisor is waiting on this exit code to relaunch us
            return RESTART_EXIT_CODE
        # started bare (old launcher, manual `python -m aletheia.core`):
        # exiting would leave NOTHING listening and a dead wall — the
        # 2026-08-26 outage. Hand off to a detached supervisor instead,
        # which starts the new code and stays to keep it alive.
        server.server_close()  # release the port before the successor binds
        journal.append("event", "core",
                       "code update while unsupervised — handing off to a "
                       "detached supervisor", actor=ACTOR)
        kwargs: dict = {}
        if os.name == "nt":
            DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP = 0x00000008, 0x00000200
            kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sys.executable, "-m", "aletheia.supervisor"],
                         cwd=str(REPO_ROOT), **kwargs)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
