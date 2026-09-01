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

Security: binds 127.0.0.1 ONLY by default — the API is the operator's own
machine talking to itself, and loopback stays unauthenticated because that
is the same trust boundary the Core has always had. Serving any other
address requires BOTH a minted access token and a TLS certificate
(`aletheia.access`, §92); without them `--host` still refuses rather than
pretending (§59 fail closed). Remote requests carry a bearer token, are
scope-checked per method, rate limited, and journaled with the token id.

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
    GET  /api/state         canonical current-state snapshot (focus/attention)
    GET  /api/notifications[?state=UNREAD]
    GET  /api/events?last=N  the local event bus, newest first
    GET  /api/watchers      durable watcher definitions + states
    GET  /api/schedules     durable schedule definitions
    GET  /api/runtime       last runtime tick summary
    GET  /api/setup         what the operator still has to supply, checked live
    GET  /api/voice/followup?id=  a slow spoken answer, non-destructive until ACK
    POST /api/voice/followup/ack  {"id": …} after the room actually speaks it
    GET  /api/computer/status
    POST /api/command       {"kind": …, …args} (+optional "operator_quote")
                            → {outcome, detail}, executed inline, journaled
    POST /api/notifications/ack  {"id": …}
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

from aletheia import access, act, capabilities, computer, followups, intercom, journal
from aletheia import liveness, policy, tasks
from aletheia import current_state, events, notifications, runtime, scheduler
from aletheia.fleet import REPO_ROOT, load_fleet
from aletheia.pulse import PULSE_DIR
from aletheia.sync import GitSync
import time

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
    heartbeat_age = liveness.age_seconds()
    return {
        "halted": policy.halted(),
        "pulse": pulse_meta,
        "liveness": {
            "heartbeat_age_s": None if heartbeat_age is None else round(heartbeat_age, 1),
            "alive": liveness.alive(),
        },
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
# When this process loaded its code. Anything under CODE_PATHS newer than
# this is code the running process is not executing.
PROCESS_STARTED_AT = time.time()
RESTART_EXIT_CODE = 42  # tells the supervisor: relaunch me, this is not a crash

# Kinds that reach a reasoning provider and therefore take tens of seconds.
# The room gets an acknowledgement now and the real sentence when it lands
# (aletheia.followups) rather than an open microphone and silence.
# setup_status makes real network attempts on purpose — an IMAP login, a
# request to the hub, a PowerShell probe — so it belongs here too. Measured
# live: 20.9s. The room gets an acknowledgement and the answer when it lands.
SLOW_KINDS = {"intent", "screen_ask", "setup_status"}


def stale_code_files(started_at: float | None = None,
                     limit: int = 5) -> list[str]:
    """Files under CODE_PATHS modified after this process loaded its code.

    Cheap: a handful of directories once a minute. Bounded: it reports the
    first few names, because the answer only has to be "yes, and here is an
    example" for the restart to be right.
    """
    started_at = PROCESS_STARTED_AT if started_at is None else started_at
    found: list[str] = []
    for entry in CODE_PATHS:
        target = REPO_ROOT / entry
        try:
            candidates = ([target] if target.is_file()
                          else sorted(target.rglob("*.py")) + sorted(target.rglob("*.json"))
                          + sorted(target.rglob("*.html")) + sorted(target.rglob("*.js")))
            for path in candidates:
                if "__pycache__" in path.parts:
                    continue
                if path.stat().st_mtime > started_at:
                    found.append(str(path.relative_to(REPO_ROOT)))
                    if len(found) >= limit:
                        return found
        except OSError:
            continue  # an unreadable path is not a reason to restart
    return found


# A subsystem that fails every beat must be said once, not sixty times an
# hour. Keyed by producer+error so a NEW failure is always heard.
_FAILURES_SEEN: dict[str, str] = {}
# How many consecutive beats a subsystem must fail before he hears about
# it. One IMAP timeout on a flaky minute is not news; two in a row is.
_FAILURE_STREAK: dict[str, int] = {}
NOTIFY_AFTER_BEATS = 2


def _surface_failures(failures: list[dict]) -> None:
    """Journal every failure; notify the operator about each new one.

    Before this, a broken subsystem was swallowed by `guarded` and counted
    as activity — it could be dead for days while the dashboard showed
    steady numbers. Silence about a failure is the failure.
    """
    from aletheia import notifications
    for failure in failures:
        producer = str(failure.get("producer", "?"))[:60]
        error = str(failure.get("error", ""))[:300]
        journal.append("alert", f"core:runtime:{producer}",
                       f"subsystem failing: {error}", actor=ACTOR)
        streak = _FAILURE_STREAK.get(producer, 0) + 1
        _FAILURE_STREAK[producer] = streak
        if streak < NOTIFY_AFTER_BEATS:
            continue  # a single blip heals more often than it matters
        if _FAILURES_SEEN.get(producer) == error:
            continue  # same failure as last beat: already said
        _FAILURES_SEEN[producer] = error
        try:
            notifications.publish(
                f"{producer} is failing",
                f"Every beat since it started: {error}. Nothing else has stopped.",
                priority="IMPORTANT", source="runtime",
                dedupe_key=f"runtime-failure:{producer}:{error[:60]}")
        except Exception:
            pass  # the journal line above is the record


def _clear_recovered(failures: list[dict]) -> None:
    """A subsystem that has started working again stops complaining.

    Making failures visible was half the job; a transient one that never
    clears is the other half. The operator's wall spent an afternoon
    headlined "Mail polling failed" over a network blip that had healed
    hours earlier — an alarm nobody can dismiss is one everybody learns to
    ignore, and then the next real one goes unread too.

    Recovery is journaled and the notification is acknowledged, never
    deleted: what happened stays on the record (§30), it just stops
    shouting.
    """
    from aletheia import notifications
    failing = {str(f.get("producer", "")) for f in failures}
    for producer in [p for p in _FAILURE_STREAK if p not in failing]:
        _FAILURE_STREAK.pop(producer, None)
        if producer not in _FAILURES_SEEN:
            continue  # it never got loud enough to need quieting
        _FAILURES_SEEN.pop(producer, None)
        journal.append("event", f"core:runtime:{producer}",
                       "recovered — working again", actor=ACTOR)
        try:
            for notice in notifications.all_notifications(state="UNREAD", limit=50):
                if str(notice.get("dedupe_key", "")).startswith(
                        f"runtime-failure:{producer}:"):
                    notifications.set_state(notice["id"], "ACKNOWLEDGED")
        except Exception:
            pass  # the journal line above is the record


_KICK_LOCK = threading.Lock()
_KICKING = False


def kick_approved_work(fleet: dict) -> bool:
    """Run the things an approval just unblocked, immediately.

    Off the sync thread on purpose: this is the same work the beat does, and
    the point is that it happens the moment he says yes rather than up to a
    minute later. One at a time — a second `approve` while the first is
    still running joins it rather than racing it, and every step is
    idempotent by state transition anyway.
    """
    global _KICKING
    with _KICK_LOCK:
        if _KICKING:
            return False
        _KICKING = True

    def run():
        global _KICKING
        try:
            for name, work in (("intents", lambda: runtime._run_approved_intents(fleet)),
                               ("errands", runtime._run_authorized_errands),
                               ("scheduling", lambda: runtime._reconcile_scheduling(
                                   dt.datetime.now(dt.timezone.utc)))):
                try:
                    work()
                except Exception as exc:
                    journal.append("event", f"core:kick:{name}",
                                   f"{type(exc).__name__}: {exc}", actor=ACTOR)
        finally:
            with _KICK_LOCK:
                _KICKING = False

    threading.Thread(target=run, name="aletheia-kick", daemon=True).start()
    return True


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
    liveness.beat(actor="core")  # never raises; see aletheia/liveness.py
    try:
        # The wall's only data source used to be a six-hourly cloud cron, so
        # a locally-running Aletheia never refreshed her own display — it was
        # measured 10.5 hours stale. This is cheap and local, every beat.
        from aletheia import presence, pulse as pulse_mod
        pulse_mod.write_local_block(presence.snapshot())
    except Exception as exc:
        journal.append("event", "core:presence",
                       f"could not refresh the wall: {type(exc).__name__}: {exc}",
                       actor=ACTOR)

    # Pull/self-update is the only part of the beat that may deliberately kill
    # this process. Reserve that short window atomically with followup.start().
    # If a spoken promise already exists, skip ONLY updating: schedules, local
    # commands, mail and the runtime still execute on every beat.
    update_window = followups.begin_update()
    keep_update_window = False
    if not update_window:
        status["update_deferred"] = {
            "voice_followups": followups.undelivered_count(),
        }
    else:
        status.pop("update_deferred", None)
        try:
            # checkpoint local run-truth FIRST so the pull rebases clean commits,
            # never a dirty journal (the exact conflict that broke a real PC)
            syncer.commit(["exchange/commands", "state/journal"], "core: state checkpoint")
            prev_pull = status.get("pull")
            before = syncer.head()
            ok, detail = syncer.pull()
            status["pull"] = {"ok": ok, "detail": detail}
            if prev_pull is not None and prev_pull.get("ok") != ok:
                journal.append("event", "core:sync",
                               f"pull {'recovered' if ok else 'failing'}: {detail}", actor=ACTOR)
                try:  # also a bus event, so watchers/rules can react to sync health
                    events.emit("core.sync_recovered" if ok else "core.sync_failed",
                                "repo:aletheia",
                                f"pull {'recovered' if ok else 'failing'}: {detail[:200]}",
                                source="core")
                except Exception:
                    pass  # the journal line above is the record; the bus is best-effort
            if ok and before:
                after = syncer.head()
                if after and after != before:
                    changed = syncer.changed_paths(before, after, CODE_PATHS)
                    status["head"] = after
                    if changed and on_code_update is not None:
                        journal.append("event", "core:sync",
                                       f"code updated ({len(changed)} file(s), now at "
                                       f"{after[:10]}) — restarting to run it", actor=ACTOR)
                        # The production callback returns True: keep the update
                        # reservation until the process exits, so no new slow
                        # promise can slip between shutdown request and exit.
                        keep_update_window = bool(on_code_update(changed))
                        return status  # restarting; skip command processing this tick
            # A pull is not the only way code changes. When the operator (or a
            # session working in this clone) commits locally, HEAD moved before the
            # Core ever looked, so `after == before` and the restart never fires.
            stale = stale_code_files()
            if stale and on_code_update is not None:
                journal.append("event", "core:sync",
                               f"code on disk is newer than this process "
                               f"({len(stale)} file(s), e.g. {stale[0]}) — restarting to run it",
                               actor=ACTOR)
                keep_update_window = bool(on_code_update(stale))
                return status
        finally:
            if not keep_update_window:
                followups.end_update()

    results = []
    try:
        results = intercom.run_pending(fleet, commands_dir=None, side="local")
    except Exception as exc:  # a broken command must not stop the loop
        journal.append("event", "core:sync",
                       f"local command processing error: {type(exc).__name__}: {exc}",
                       actor=ACTOR)
    try:
        from aletheia import mail
        if mail.available()[0]:
            for sent in mail.send_approved():
                results.append(sent)
    except Exception as exc:
        journal.append("event", "core:sync",
                       f"mail delivery error: {type(exc).__name__}: {exc}", actor=ACTOR)
    status["commands_executed"] += len(results)
    try:
        # calendar feeds: mirror the operator's ICS subscriptions at most
        # every 30 min; honest no-op when unconfigured
        from aletheia import ics
        refreshed = ics.refresh_if_due()
        if refreshed:
            status["calendar"] = refreshed
    except Exception as exc:  # a bad feed must not stop the loop
        journal.append("event", "core:sync",
                       f"calendar refresh error: {type(exc).__name__}: {exc}",
                       actor=ACTOR)
    try:
        # the local runtime: due schedules (through the same intercom gates),
        # reply expectations, bus events -> watcher/proactive notifications,
        # capability-gap reconciliation. Summarized at /api/runtime.
        summary = runtime.tick(fleet)
        failures = summary.pop("failures", [])
        interesting = {k: v for k, v in summary.items() if v}
        status["runtime"] = {"at": status["last_tick"],
                             **{k: len(v) for k, v in summary.items()},
                             # errors are their own field, never a count that
                             # reads like activity
                             "failures": failures}
        _clear_recovered(failures)
        if failures:
            _surface_failures(failures)
        if interesting.get("schedules") or interesting.get("reply_transitions"):
            journal.append("event", "core:runtime",
                           "; ".join(f"{k}: {len(v)}" for k, v in interesting.items()),
                           actor=ACTOR)
    except Exception as exc:  # runtime trouble must not stop sync
        status["runtime"] = {"at": status["last_tick"], "error": f"{type(exc).__name__}: {exc}"}
        journal.append("event", "core:runtime",
                       f"runtime tick error: {type(exc).__name__}: {exc}", actor=ACTOR)
    # Receipts push IMMEDIATELY — a relay is waiting on them. Journal-only
    # heartbeats batch: commit every tick, push at most every 10 minutes.
    # 193 heartbeat pushes landed on main in one day, each one running the
    # full CI suite; batching keeps history and Actions sane, and the
    # pending commits still ride out with the next receipt push.
    now_s = dt.datetime.now(dt.timezone.utc).timestamp()
    if not results and now_s - status.get("last_push_s", 0.0) < 600:
        syncer.commit(["exchange/commands", "state/journal"],
                      "core: state checkpoint")
        return status
    ok, detail = syncer.commit_push(
        ["exchange/commands", "state/journal"],
        f"core: {len(results)} local command receipt(s)" if results
        else "core: state checkpoint")
    prev_push = status.get("push")
    status["push"] = {"ok": ok, "detail": detail}
    if ok:
        status["last_push_s"] = now_s
    elif prev_push is None or prev_push.get("ok"):
        journal.append("event", "core:sync", f"push failing: {detail}", actor=ACTOR)
    return status


class Handler(BaseHTTPRequestHandler):
    fleet: dict = {}
    computer_backend_factory = None

    def log_message(self, fmt, *args):  # quiet by default; journal is the record
        pass

    def authorized(self) -> bool:
        """Gate every remote request; leave loopback exactly as it was.

        Loopback is the operator's own machine talking to itself — the
        Core's trust boundary since V0, unchanged here. A request from
        anywhere else must carry a bearer token that is live, unexpired
        and scoped to the method: a `read` token answers GET and cannot
        become a command channel because a phone was left unlocked.
        Refusals are quiet about WHY (a 401 that explains itself is an
        oracle) and loud in the journal.
        """
        address = self.client_address[0] if self.client_address else "?"
        if access.is_loopback(address):
            return True
        record = access.verify(access.bearer(self.headers), address)
        if record is None:
            self._json({"error": "unauthorized"}, code=401)
            return False
        if not access.scope_allows(record["scope"], self.command):
            journal.append("alert", "access",
                           f"{record['id']} ({record['scope']}) tried "
                           f"{self.command} {self.path.split('?')[0]} from {address}",
                           actor="aletheia-access")
            self._json({"error": "this token is read-only"}, code=403)
            return False
        access.note_use(record["id"])
        journal.append("event", "access",
                       f"{record['id']} {self.command} "
                       f"{self.path.split('?')[0]} from {address}",
                       actor="aletheia-access")
        return True

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
        if not self.authorized():
            return
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
        if url.path == "/api/state":
            return self._json(current_state.snapshot())
        if url.path == "/api/notifications":
            state = parse_qs(url.query).get("state", [None])[0]
            return self._json(notifications.all_notifications(state=state))
        if url.path == "/api/events":
            last = int(parse_qs(url.query).get("last", ["50"])[0])
            return self._json(events.list_events(limit=max(1, min(last, 500))))
        if url.path == "/api/watchers":
            return self._json(events.list_watchers())
        if url.path == "/api/schedules":
            return self._json(scheduler.all_schedules())
        if url.path == "/api/setup":
            from aletheia import setup as _setup
            return self._json(_setup.audit())
        if url.path == "/api/runtime":
            return self._json(SYNC_STATUS.get("runtime") or {"at": None})
        if url.path == "/api/voice/followup":
            fid = parse_qs(url.query).get("id", [""])[0]
            if not fid:
                return self._json({"state": "EXPIRED", "say": None,
                                   "detail": "id required"}, code=400)
            # Non-destructive. The listener ACKs only after it has actually
            # spoken the returned sentence.
            return self._json(followups.poll(fid))
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
        if not self.authorized():
            return
        path = urlparse(self.path).path
        if path not in ("/api/command", "/api/computer", "/api/voice",
                        "/api/notifications/ack", "/api/voice/followup/ack"):
            return self.send_error(404)
        try:
            payload = self._payload()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json({"outcome": "invalid", "detail": str(exc)}, code=400)
        if path == "/api/voice/followup/ack":
            fid = payload.get("id")
            if not isinstance(fid, str) or not fid:
                return self._json({"outcome": "invalid", "detail": "id required"}, code=400)
            return self._json(followups.acknowledge(fid))
        if path == "/api/command":
            result = run_command(payload, self.fleet)
            if payload.get("kind") in ("approve", "resume"):
                # He just said yes. Waiting up to a full sync beat to act on
                # it is the difference between an assistant and a cron job,
                # so the work he unblocked is kicked NOW — off the sync
                # thread, so a slow errand still cannot stall the beat.
                kick_approved_work(self.fleet)
            return self._json(result)
        if path == "/api/notifications/ack":
            nid = payload.get("id")
            if not isinstance(nid, str) or not nid:
                return self._json({"outcome": "invalid", "detail": "id required"}, code=400)
            try:
                return self._json(notifications.set_state(nid, "ACKNOWLEDGED"))
            except (ValueError, FileNotFoundError) as exc:
                return self._json({"outcome": "invalid", "detail": str(exc)}, code=400)
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
            quote = f"spoken to the wall: {transcript[:200]}"
            if kind in SLOW_KINDS:
                # Reasoning takes ten to thirty seconds; a person in a room
                # waits about two. Answer now, think in the background, and
                # let the listener collect the real sentence when it exists.
                fleet = self.fleet
                try:
                    slot = followups.start(
                        lambda: run_command({**cmd, "operator_quote": quote}, fleet)["detail"],
                        acknowledgement="Working on that.")
                except followups.UpdateInProgress:
                    return self._json({
                        "outcome": "busy",
                        "say": "I'm applying an update right now. Ask me again in a moment.",
                    })
                return self._json({"outcome": "thinking", "say": slot["say"],
                                   "followup_id": slot["id"]})
            result = run_command({**cmd, "operator_quote": quote}, self.fleet)
            if kind in ("approve", "resume"):
                kick_approved_work(self.fleet)  # saying yes out loud acts now too
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
                computer_backend_factory=None, tls_cert: str | None = None,
                tls_key: str | None = None) -> ThreadingHTTPServer:
    """Bind the Core. Loopback always; anywhere else only under §92's terms.

    Off-loopback used to be refused outright, because there was nothing to
    authenticate with — which is why the phone surface has never had a
    phone. `access.bind_refusal` holds the conditions now (a live token AND
    a real certificate), and it still refuses by default: nothing about
    this makes the Core reachable unless the operator has deliberately
    minted a credential and supplied TLS.
    """
    refusal = access.bind_refusal(host, tls_cert, tls_key)
    if refusal:
        raise ValueError(f"refusing to serve {host}: {refusal}")

    class BoundHandler(Handler):
        pass

    BoundHandler.fleet = load_fleet()
    BoundHandler.computer_backend_factory = (
        staticmethod(computer_backend_factory) if computer_backend_factory else None)
    server = ThreadingHTTPServer((host, port), BoundHandler)
    if tls_cert and tls_key and not access.is_loopback(host):
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(tls_cert, tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


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
    ap.add_argument("--host", default="127.0.0.1",
                    help="loopback by default; another address needs a minted "
                         "access token AND --tls-cert/--tls-key (§92)")
    ap.add_argument("--tls-cert", help="certificate for off-loopback serving")
    ap.add_argument("--tls-key", help="private key for off-loopback serving")
    ap.add_argument("--sync-interval", type=float, default=SYNC_INTERVAL_S,
                    help="seconds between pull/process/push beats (default 60)")
    ap.add_argument("--no-sync", action="store_true",
                    help="serve the API only; no git sync, no local command processing")
    args = ap.parse_args(argv)
    journal.use_pc_journal()  # this process is the PC writer
    # Before anything else: measure the gap we are coming back from. If the
    # last heartbeat is old, this start ENDED an outage, and that is a fact
    # the journal and the bus get to hear about (2026-08-27).
    liveness.note_start(actor="core", port=args.port)
    server = make_server(args.host, args.port, tls_cert=args.tls_cert,
                         tls_key=args.tls_key)
    restarting = threading.Event()

    def on_code_update(changed):
        # runs on the sync thread; shutdown() unblocks serve_forever below.
        # True tells core_tick to keep the follow-up update reservation held
        # until this process exits, closing the shutdown-request/exit race.
        restarting.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
        return True

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
