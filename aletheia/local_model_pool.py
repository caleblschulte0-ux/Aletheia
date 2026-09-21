"""Two-role local reasoning pool with bounded failover and training capture."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Any

from aletheia import local_brain, model_pool_config, stateio, training_data, work_states

FAST_TIMEOUT_S = 12.0
DEEP_TIMEOUT_S = 45.0
#: The two classes of work and their per-call ceilings live in
#: `work_states.LOCAL_CEILING_S` (300 s attended, 1200 s background). Re-exported
#: here only so a caller reaching for the pool does not have to know where they
#: live; never copy the numbers.
ATTENDED = work_states.ATTENDED
BACKGROUND = work_states.BACKGROUND
FAST_SMOKE_TIMEOUT_S = 120.0
DEEP_HINTS = (
    "architecture", "root cause", "debug", "code review", "review the code",
    "tradeoff", "trade-off", "investigate", "complex plan", "reason through",
    "deep analysis", "think hard",
)


class LocalPoolUnavailable(RuntimeError):
    pass


class LocalPoolYielded(LocalPoolUnavailable):
    """Background work put her own model down so a conversation could have it.

    A reason to try again shortly, never a failure of the work - and never a
    reason to fail over to the other role, which would take the queue straight
    back off him."""


@dataclass(frozen=True)
class LocalRun:
    role: str
    model: str
    think: bool
    output: dict
    turn_id: str | None
    duration_ms: int


def choose_role(text: str, context: dict | None = None) -> str:
    lowered = str(text).casefold()
    if any(hint in lowered for hint in DEEP_HINTS):
        return "deep"
    if len(str(text)) >= 1_200:
        return "deep"
    try:
        size = len(json.dumps(context or {}, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        size = 0
    return "deep" if size >= 6_000 else "fast"


#: How long a model's size is trusted before asking Ollama again. Models
#: are pulled rarely; the machine's memory changes minute to minute, so
#: only the SIZE is cached and the room is measured every time.
_SIZES: dict[str, Any] = {"at": 0.0, "by_name": {}}
_SIZE_CACHE_S = 300.0
_SIZE_TIMEOUT_S = 4.0


def installed_sizes(*, now: float | None = None) -> dict[str, int]:
    """What each installed model weighs, from Ollama's own listing.

    Never raises: a lane that cannot say how big its models are must not
    become a lane that refuses to answer.
    """
    import time as _time
    import urllib.request

    now = _time.monotonic() if now is None else now
    if now - float(_SIZES["at"]) < _SIZE_CACHE_S and _SIZES["by_name"]:
        return dict(_SIZES["by_name"])
    sizes: dict[str, int] = {}
    try:
        base = local_brain.DEFAULT_BASE_URL
        try:
            base = local_brain.base_url()
        except Exception:
            pass
        with urllib.request.urlopen(f"{base.rstrip('/')}/api/tags",
                                    timeout=_SIZE_TIMEOUT_S) as resp:
            listed = json.loads(resp.read().decode("utf-8", "replace"))
        for entry in listed.get("models") or []:
            name = str(entry.get("name") or "")
            if name:
                sizes[name] = int(entry.get("size") or 0)
    except Exception:
        return dict(_SIZES["by_name"])
    _SIZES.update({"at": now, "by_name": sizes})
    return dict(sizes)


def room_for_role(role: str) -> dict:
    """Whether this role's model can run on this machine right now.

    THE CHECK THAT WAS MISSING. `reachable()` proves Ollama is running and
    nothing more, and the `deep` role resolves by default to
    `qwen3.6:27b` — 17.8 GB on a 16 GB machine with no discrete GPU. Any
    question `choose_role` sends to "deep" loaded it: measured live
    2026-09-09, commit charge went to 32,329 MB of a 32,841 MB limit and
    Windows began killing processes. What it killed was this repository's
    own test suite.

    A model that is not installed returns fits=True with known=False: that
    is Ollama's error to report, in Ollama's words, not a memory refusal
    wearing its coat.
    """
    from aletheia import machine

    name = str(model_pool_config.resolve(role).get("model") or "")
    size = installed_sizes().get(name, 0)
    if not size:
        return {"fits": True, "known": False, "model": name,
                "why": "size unknown", "needed": 0, "usable": 0, "total": 0}
    verdict = machine.room_for(size)
    verdict["model"] = name
    if not verdict["fits"]:
        verdict["why"] = machine.why_it_does_not_fit(name, verdict)
    return verdict


def _config(role: str, timeout_s: float | None = None,
            think_override: bool | None = None,
            attention: str = work_states.ATTENDED) -> local_brain.OllamaConfig:
    profile = model_pool_config.resolve(role)
    timeout = timeout_s if timeout_s is not None else (
        FAST_TIMEOUT_S if role == "fast" else DEEP_TIMEOUT_S
    )
    # THE CEILING IS THE CLASS OF WORK, and the class is attended unless the
    # caller said otherwise. A caller that asks for twenty minutes without
    # saying the work is background gets the five minutes conversation has
    # always had: the long budget is opt-in, never inherited, never a default.
    timeout = min(float(timeout), work_states.local_ceiling_s(attention))
    return local_brain.OllamaConfig.for_model(
        profile["model"],
        think=profile["think"] if think_override is None else think_override,
        timeout_s=timeout,
        # AND HOW LONG SHE STAYS WARM AFTERWARDS. He is about to say another
        # sentence; a finished background draft has nobody waiting on it.
        keep_alive=(local_brain.BACKGROUND_KEEP_ALIVE if attention == work_states.BACKGROUND
                    else local_brain.ATTENDED_KEEP_ALIVE),
    )


def run_json(system_prompt: str, text: str, *, context: dict | None = None,
             role: str = "fast", validator: Callable[[dict], dict] | None = None,
             timeout_s: float | None = None,
             require_enabled: bool = True,
             think_override: bool | None = None,
             attention: str = work_states.ATTENDED) -> LocalRun:
    if role not in {"fast", "deep"}:
        raise ValueError("local role must be fast or deep")
    if attention not in work_states.ATTENTION:
        raise ValueError(f"attention must be one of {sorted(work_states.ATTENTION)}")
    if require_enabled and not model_pool_config.enabled():
        raise LocalPoolUnavailable("local reasoning is disabled")
    ctx = context or {}
    if not isinstance(ctx, dict):
        raise ValueError("local context must be an object")
    # BEFORE THE MACHINE IS ASKED TO DO SOMETHING IT CANNOT DO. Loading a
    # model bigger than the memory it has does not make her slow, it makes
    # the computer start killing things — measured at 98.4% of the commit
    # limit with 1 GB free. Refusing here means the caller fails over to a
    # role that fits or to the frontier lane, which is the honest outcome:
    # she has a Claude subscription and he has one laptop.
    room = room_for_role(role)
    if not room["fits"]:
        raise LocalPoolUnavailable(room["why"])
    started = time.perf_counter()
    proposal = None
    config = None
    payload = None
    try:
        config = _config(role, timeout_s, think_override, attention)
        payload = local_brain.build_payload(system_prompt, text, ctx, config)
        # ONE LOCAL MODEL JOB AT A TIME, across her processes, conversation
        # first (aletheia.local_lease): Ollama has one queue on this laptop.
        from aletheia import local_lease
        # A background call is also PUT DOWN when he starts talking. The lease
        # keeps background work from taking the queue while a conversation
        # waits; it cannot help with the call already running, and a twenty
        # minute call already running is twenty minutes of silence in the room.
        should_yield = (local_lease.conversation_waiting
                        if attention == work_states.BACKGROUND else None)
        # ONE THING SAYS WHAT THE WORK IS. Saying BACKGROUND is also saying WORK
        # to the lease, so nothing can hold the long budget and still queue as a
        # conversation - which is what `local_repair` did, drafting code for
        # four minutes in front of the room because its think() never wrapped
        # itself in `purpose(WORK)` the way work_runners and study_reason do.
        # ATTENDED passes None and leaves whatever purpose the caller set.
        background = attention == work_states.BACKGROUND
        try:
            with local_lease.hold(what=f"{role} {config.model}", hold_s=float(config.timeout_s or 0) + 30.0,
                                  purpose_name=local_lease.WORK if background else None):
                started = time.perf_counter()
                # SEEN WHILE IT RUNS. The mark is what "what are you doing"
                # and the page read; the progress line is what the room hears
                # and the ask box shows, once, when he is waiting on it.
                _mark_busy(role, config.model, text, attention)
                if not background:
                    try:
                        from aletheia import followups, speech
                        typical = recent().get("typical_s")
                        followups.report("Thinking with my own model, which is slower"
                                         + (f", usually {speech.about_seconds(typical)}" if typical else "")
                                         + ".")
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    proposal = local_brain.infer_json(system_prompt, text, context=ctx, config=config,
                                                      should_yield=should_yield)
                finally:
                    _clear_busy()
        except local_lease.LeaseBusy as lease_busy:
            raise LocalPoolUnavailable(f"her own model is busy: {lease_busy}") from None
        output = validator(proposal) if validator else proposal
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        if config is not None:
            _remember_run(role, elapsed, False, text)
        if config is not None:
            training_data.record_turn(
                provider="ollama", model=config.model, role=role, text=text, context=ctx,
                request_payload=payload, result=proposal, status="error",
                error_type=type(exc).__name__, error=str(exc), duration_ms=elapsed,
            )
        if isinstance(exc, local_brain.LocalBrainYielded):
            raise LocalPoolYielded(str(exc)) from None
        if isinstance(exc, local_brain.LocalBrainError):
            # LocalBrainError messages are deliberately bounded diagnostics
            # containing no prompt, response body, URL path, or credentials.
            # Keep the underlying timeout/transport class useful to the
            # operator instead of collapsing every failure to one vague type.
            raise LocalPoolUnavailable(
                f"local {role} role failed: {exc}"
            ) from None
        if isinstance(exc, (ValueError, TypeError)):
            raise LocalPoolUnavailable(f"local {role} role failed ({type(exc).__name__})") from None
        raise
    elapsed = round((time.perf_counter() - started) * 1000)
    _remember_run(role, elapsed, True, text)
    turn_id = training_data.record_turn(
        provider="ollama", model=config.model, role=role, text=text, context=ctx,
        request_payload=payload, result=output, status="validated", duration_ms=elapsed,
    )
    return LocalRun(role, config.model, config.think, output, turn_id, elapsed)


def auto_json(system_prompt: str, text: str, *, context: dict | None = None,
              validator: Callable[[dict], dict] | None = None,
              preferred_role: str | None = None,
              allow_failover: bool = True,
              timeout_s: float | None = None,
              require_enabled: bool = True,
              attention: str = work_states.ATTENDED) -> LocalRun:
    first = preferred_role or choose_role(text, context)
    if first not in {"fast", "deep"}:
        raise ValueError("preferred_role must be fast or deep")
    second = "deep" if first == "fast" else "fast"
    try:
        return run_json(
            system_prompt, text, context=context, role=first,
            validator=validator, timeout_s=timeout_s,
            require_enabled=require_enabled, attention=attention,
        )
    except LocalPoolYielded:
        # He is talking. The second role would take the queue straight back.
        raise
    except LocalPoolUnavailable as first_failure:
        if not allow_failover:
            raise
        try:
            return run_json(
                system_prompt, text, context=context, role=second,
                validator=validator, timeout_s=timeout_s,
                require_enabled=require_enabled, attention=attention,
            )
        except LocalPoolYielded:
            # The same on the way back: a yield is "he is talking", and rolling
            # it into "neither local model could run" tells the caller its work
            # failed when the work is simply waiting its turn.
            raise
        except LocalPoolUnavailable as second_failure:
            # BOTH REASONS, not a shrug. "Both local reasoning roles are
            # unavailable" told him nothing and the two halves usually
            # fail for different reasons — one model too big for the
            # machine, the other Ollama not running — with different
            # fixes. Collapsing them is how an actionable failure becomes
            # a sentence he can only reply "okay" to.
            raise LocalPoolUnavailable(
                f"neither local model could run. {first} — {first_failure}; "
                f"{second} — {second_failure}") from None


# Reachability, cached: the answer changes when he starts or stops
# Ollama, not between two asks a second apart. A refusal is remembered too,
# so a dead daemon costs one 1.5 s probe a minute, not a 15 s timeout per
# ask (2026-09-04: every routine ask waited on a configured-but-stopped
# Ollama before the subscription got its turn, and a long plan lost the
# subscription's 45 s slice entirely).
REACH_CACHE_S = 60.0
REACH_TIMEOUT_S = 1.5
_REACH: dict[str, Any] = {"at": 0.0, "ok": False}


def reachable(*, now: float | None = None, probe=None) -> bool:
    """Is an Ollama actually answering at the configured address right now
    (within the last REACH_CACHE_S)? Never raises."""
    import time
    import urllib.request
    now = time.monotonic() if now is None else now
    if now - _REACH["at"] < REACH_CACHE_S:
        return bool(_REACH["ok"])
    ok = False
    try:
        base = local_brain.DEFAULT_BASE_URL
        try:
            base = local_brain.base_url()          # honours any configured address
        except Exception:
            pass
        if probe is not None:
            ok = bool(probe(base))
        else:
            with urllib.request.urlopen(f"{base.rstrip('/')}/api/tags",
                                        timeout=REACH_TIMEOUT_S) as resp:
                ok = 200 <= int(getattr(resp, "status", 200) or 200) < 300
    except Exception:
        ok = False
    _REACH.update({"at": now, "ok": ok})
    return ok


def forget_reachability() -> None:
    _REACH.update({"at": 0.0, "ok": False})


# ---- what her own model is doing, and how long it takes ---------------------------
#
# His words, 2026-09-21: he needs "a better way for me to see it's working
# and what it's doing ... mainly when it's just the local model up so I can
# make sure it's working since it is a lot slower." So every local call
# leaves a mark while it runs (what, since when, which role) and a line in a
# small ring when it ends (how long, whether it answered). `current_state`
# reads both; the page, the room and "what are you doing" say them.

BUSY_STALE_S = 40 * 60.0
RECENT_KEEP = 40


def _busy_path():
    return stateio.private_dir("local-ai") / "busy.json"


def _recent_path():
    return stateio.private_dir("local-ai") / "recent.json"


def _mark_busy(role: str, model: str, what: str, attention: str) -> None:
    import os
    try:
        stateio.write_json_atomic(_busy_path(), {
            "started_at": stateio.utcnow(), "role": role, "model": model,
            "what": " ".join(str(what or "").split())[:160], "attention": attention,
            "pid": os.getpid()})
    except Exception:  # noqa: BLE001
        pass


def _clear_busy() -> None:
    try:
        _busy_path().unlink()
    except OSError:
        pass


def busy() -> dict | None:
    """The local call running right now, or None. A mark older than
    BUSY_STALE_S is a crash's leftovers, not a call, and reads as None."""
    import datetime as dt
    try:
        value = stateio.read_json(_busy_path())
        started = dt.datetime.fromisoformat(str(value["started_at"]).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    age = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
    if age < 0 or age > BUSY_STALE_S:
        return None
    return {**value, "elapsed_s": round(age)}


def _remember_run(role: str, elapsed_ms: int, ok: bool, what: str = "") -> None:
    try:
        rows = []
        try:
            rows = list(stateio.read_json(_recent_path()).get("runs") or [])
        except Exception:  # noqa: BLE001
            rows = []
        rows.append({"at": stateio.utcnow(), "role": role, "s": round(elapsed_ms / 1000.0, 1),
                     "ok": bool(ok), "what": " ".join(str(what or "").split())[:80]})
        stateio.write_json_atomic(_recent_path(), {"runs": rows[-RECENT_KEEP:]})
    except Exception:  # noqa: BLE001
        pass


def recent(*, now=None) -> dict:
    """How her own model has been doing: answers today, the last one, and
    how long one typically takes (the median of the ones that answered)."""
    import datetime as dt
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        rows = list(stateio.read_json(_recent_path()).get("runs") or [])
    except Exception:  # noqa: BLE001
        rows = []
    floor = now.strftime("%Y-%m-%dT00:00:00Z")
    today = [r for r in rows if str(r.get("at") or "") >= floor]
    answered = [float(r["s"]) for r in rows if r.get("ok") and r.get("s") is not None]
    answered.sort()
    typical = answered[len(answered) // 2] if answered else None
    last = rows[-1] if rows else None
    return {"today": len(today), "today_ok": sum(1 for r in today if r.get("ok")),
            "typical_s": typical, "last_s": (float(last["s"]) if last and last.get("s") is not None else None),
            "last_ok": (bool(last.get("ok")) if last else None), "last_at": (last or {}).get("at"),
            "known": len(answered)}


# ---- the rung that never runs out has to actually be there ------------------
#
# His words, 2026-09-10: "something that technically will always be able to
# fix something. That'll never run out." Measured 2026-09-21: the local rung
# had never carried a request on his PC, and nothing in the repo STARTED
# Ollama or PULLED the model - activation reported "model not pulled" and
# stopped, and the bring-up turned local AI off for good on that report. So
# the pool repairs itself: Ollama not answering is started; the configured
# model not on disk is pulled, in the background, once. Rate-limited, never
# raising, and every action journaled, because a self-repair that loops is
# a new way to fill his screen with windows.

HEAL_EVERY_S = 600.0
SERVE_WAIT_S = 8.0


def _heal_path():
    return stateio.private_dir("local-ai") / "heal.json"


def _heal_state() -> dict:
    try:
        return stateio.read_json(_heal_path())
    except Exception:  # noqa: BLE001
        return {}


def _remember_heal(**changes) -> None:
    try:
        state = _heal_state()
        state.update(changes)
        stateio.write_json_atomic(_heal_path(), state)
    except Exception:  # noqa: BLE001
        pass


def ollama_binary() -> str | None:
    """Where Ollama is, or None. PATH first; the Windows installer's default
    second, because a Scheduled Task's PATH is not his terminal's."""
    import os
    import shutil
    found = shutil.which("ollama")
    if found:
        return found
    if os.name == "nt":
        for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
            for tail in (r"Programs\Ollama\ollama.exe", r"Ollama\ollama.exe"):
                path = os.path.join(base, tail) if base else ""
                if path and os.path.isfile(path):
                    return path
    return None


def _spawn_detached(args: list[str]) -> int:
    """A helper that outlives this call and shows no window."""
    import os
    import subprocess
    from aletheia import proc
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = proc.hidden_flags(0x00000008 | 0x00000200)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(args, **kwargs).pid


def ensure(*, now: float | None = None, spawner=None, binary=None,
           probe=None) -> dict[str, Any]:
    """Make her own model reachable, or say exactly why it is not. Never raises.

    - switched off -> nothing, and says so;
    - Ollama not answering -> start it (once per HEAL_EVERY_S) and wait a
      few seconds for it;
    - answering, required model not on disk -> pull it in the background
      (once; a pull already running is left to run);
    - answering with the model -> ok.
    """
    import time
    from aletheia import journal, proc
    now = time.monotonic() if now is None else now
    out: dict[str, Any] = {"enabled": model_pool_config.enabled()}
    if not out["enabled"]:
        out["why"] = "local AI is switched off"
        return out
    exe = binary if binary is not None else ollama_binary()
    state = _heal_state()
    wall = time.time()
    forget_reachability()
    if not reachable(probe=probe):
        out["reachable"] = False
        if not exe:
            out["why"] = "Ollama is not installed on this machine"
            return out
        last = float(state.get("served_at") or 0)
        if wall - last < HEAL_EVERY_S:
            out["why"] = "Ollama was started recently and is not answering yet"
            return out
        try:
            pid = (spawner or _spawn_detached)([exe, "serve"])
        except Exception as exc:  # noqa: BLE001
            out["why"] = f"could not start Ollama ({type(exc).__name__})"
            return out
        _remember_heal(served_at=wall, serve_pid=pid)
        journal.append("action", "local-ai", "started Ollama, which was not running",
                       actor="aletheia-local-ai")
        out["started"] = True
        deadline = time.monotonic() + SERVE_WAIT_S
        while time.monotonic() < deadline:
            forget_reachability()
            if reachable(probe=probe):
                break
            time.sleep(0.5)
        forget_reachability()
        out["reachable"] = reachable(probe=probe)
        if not out["reachable"]:
            out["why"] = "Ollama was started and is not answering yet"
            return out
    out["reachable"] = True
    wanted = model_pool_config.resolve("fast")["model"]
    try:
        observed = local_brain.status(_config("fast", timeout_s=4.0))
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"could not list the models ({type(exc).__name__})"
        return out
    if observed.get("model_available"):
        out["model"] = wanted
        out["ok"] = True
        return out
    pull = state.get("pull") or {}
    if pull.get("model") == wanted and proc.pid_alive(pull.get("pid")) is not False \
            and wall - float(pull.get("started_at") or 0) < 6 * 3600:
        out["pulling"] = wanted
        out["why"] = f"still downloading {wanted}"
        return out
    if not exe:
        out["why"] = f"{wanted} is not on this machine and Ollama's own command is not here to fetch it"
        return out
    try:
        pid = (spawner or _spawn_detached)([exe, "pull", wanted])
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"could not start the download of {wanted} ({type(exc).__name__})"
        return out
    _remember_heal(pull={"model": wanted, "pid": pid, "started_at": wall})
    journal.append("action", "local-ai", f"downloading my own model, {wanted}, which was not on this machine",
                   actor="aletheia-local-ai")
    out["pulling"] = wanted
    out["started_pull"] = True
    out["why"] = f"downloading {wanted}; a few minutes on a good connection"
    return out


def smoke() -> dict[str, Any]:
    """Prove the required fast route responds and both configured tags exist."""
    # Repair first, so activation on the bring-up starts what is stopped and
    # fetches what is missing rather than reporting it and giving up.
    healed = ensure()
    results: dict[str, Any] = {}
    for role in ("fast", "deep"):
        # Tag discovery is a service diagnostic, not inference. In particular,
        # do not cold-load the optional deep fallback merely to activate the
        # required routine route.
        config = _config(role, timeout_s=2.0)
        observed = local_brain.status(config)
        if not observed.get("online") or not observed.get("model_available"):
            raise LocalPoolUnavailable(
                f"local {role} model is not ready: {observed.get('detail', 'unavailable')}"
            )
        results[role] = {
            "model": config.model,
            "model_available": True,
            "response_tested": False,
        }

    def validate(value: dict) -> dict:
        if value != {"ok": True, "role": "fast"}:
            raise ValueError("local fast smoke response did not match contract")
        return value

    run = run_json(
        "Return exactly the requested JSON object. You have no tools or authority.",
        'Return exactly {"ok":true,"role":"fast"}.',
        role="fast", validator=validate, require_enabled=False,
        # Activation may cold-load the required routine model once. Normal
        # production requests retain the 12s route limit above.
        timeout_s=FAST_SMOKE_TIMEOUT_S,
        # The activation probe measures JSON transport readiness, not the
        # length of a hidden reasoning trace.
        think_override=False,
    )
    results["fast"].update({
        "duration_ms": run.duration_ms,
        "response_tested": True,
    })
    return {
        "ok": True,
        "healed": healed,
        "required_response_role": "fast",
        "roles": results,
    }


def status() -> dict[str, Any]:
    profiles = {}
    for role in ("fast", "deep"):
        profile = model_pool_config.resolve(role)
        # Status is an operator diagnostic, not inference. A sick local service
        # must not make the command wait for the models' full generation limits.
        profiles[role] = {
            **profile,
            **local_brain.status(_config(role, timeout_s=2.0)),
        }
    return {
        **model_pool_config.settings(),
        "profiles": profiles,
        "training": training_data.stats(),
    }
