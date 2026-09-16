"""Power awareness: is the PC on the charger, and does it stay awake while she works.

The real incident this exists for: the laptop was on battery, Windows
put it to sleep (Kernel-Power 42, "Sleep Reason: Battery"), and she was
silent for twenty-two hours. Nothing she could see said "you are on
battery", nothing held the machine awake while a batch was mid-form, and
nobody told him.

Three things, stdlib `ctypes` only:

- `status()` reads AC / battery through `GetSystemPowerStatus`.
- `keep_awake(reason)` holds `SetThreadExecutionState(ES_CONTINUOUS |
  ES_SYSTEM_REQUIRED)` ONLY while a batch or a mission is actually running,
  and releases it after. Never `ES_DISPLAY_REQUIRED`: the screen may turn
  off; the machine may not sleep under a half-filled form. The request is
  per THREAD, so it is released on the thread that took it, and nested
  holds on one thread release once, at the outermost exit. Each hold leaves
  a small marker in private state so the Core (another process) can say
  "a batch is holding the PC awake" - reading a marker never acts.
- `watch(working=...)` notifies him ONCE per battery episode when the PC is
  on battery while she works, and once when the battery is low. The dedupe
  key carries the episode's start, so plugging in and unplugging again is a
  new episode and a new notice, and sixty beats on one battery are one.

Holding the machine awake does not beat a critical battery: Windows still
hibernates or sleeps when the battery runs out, which is why the notice
says to plug it in rather than promising she will keep going.

Off Windows every function is an honest no-op: `status()` says the power
state is not known, and `keep_awake` holds nothing. Tests pass a fake
kernel32.
"""
from __future__ import annotations

import contextlib
import ctypes
import datetime as dt
import json
import os
import sys
import threading
from typing import Any, Callable, Iterator

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002   # named so a test can prove it is never asked for

AC_OFFLINE, AC_ONLINE, AC_UNKNOWN = 0, 1, 255
FLAG_HIGH, FLAG_LOW, FLAG_CRITICAL, FLAG_CHARGING = 1, 2, 4, 8
FLAG_NO_BATTERY, FLAG_UNKNOWN = 128, 255
PERCENT_UNKNOWN = 255
LIFETIME_UNKNOWN = 0xFFFFFFFF

#: At or below this, "low" whatever Windows' own flag says.
LOW_PERCENT = 25

ACTOR = "aletheia-power"


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte),
                ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong)]


#: A fake kernel32 for tests; None means the real one on Windows.
_KERNEL32: Any = None


def _kernel32(kernel32: Any = None) -> Any:
    if kernel32 is not None:
        return kernel32
    if _KERNEL32 is not None:
        return _KERNEL32
    if sys.platform != "win32":
        return None
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)   # type: ignore[attr-defined]
        k.SetThreadExecutionState.argtypes = [ctypes.c_uint]
        k.SetThreadExecutionState.restype = ctypes.c_uint
        k.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
        k.GetSystemPowerStatus.restype = ctypes.c_int
        return k
    except Exception:
        return None


def _now(now: dt.datetime | None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- reading the power state --------------------------------------------------

def status(*, kernel32: Any = None) -> dict:
    """AC or battery, how much, and whether it is low. Never raises."""
    k = _kernel32(kernel32)
    if k is None:
        return {"known": False, "on_ac": None, "battery_percent": None, "has_battery": None,
                "charging": None, "low": False, "critical": False, "battery_saver": None,
                "seconds_left": None,
                "said": "the power state is not known here (it is read on Windows only)"}
    raw = SYSTEM_POWER_STATUS()
    try:
        ok = k.GetSystemPowerStatus(ctypes.byref(raw))
    except Exception as exc:  # noqa: BLE001
        ok, why = 0, type(exc).__name__
    else:
        why = "GetSystemPowerStatus returned 0"
    if not ok:
        return {"known": False, "on_ac": None, "battery_percent": None, "has_battery": None,
                "charging": None, "low": False, "critical": False, "battery_saver": None,
                "seconds_left": None, "said": f"the power state could not be read ({why})"}
    flag = int(raw.BatteryFlag)
    on_ac = {AC_ONLINE: True, AC_OFFLINE: False}.get(int(raw.ACLineStatus))
    has_battery = None if flag == FLAG_UNKNOWN else not (flag & FLAG_NO_BATTERY)
    percent = None if int(raw.BatteryLifePercent) == PERCENT_UNKNOWN else int(raw.BatteryLifePercent)
    known_flag = flag != FLAG_UNKNOWN and has_battery
    critical = bool(known_flag and flag & FLAG_CRITICAL)
    low = bool(critical or (known_flag and flag & FLAG_LOW)
               or (percent is not None and has_battery is not False and percent <= LOW_PERCENT))
    charging = None if flag == FLAG_UNKNOWN else bool(flag & FLAG_CHARGING)
    seconds = None if int(raw.BatteryLifeTime) == LIFETIME_UNKNOWN else int(raw.BatteryLifeTime)
    out = {"known": on_ac is not None, "on_ac": on_ac, "battery_percent": percent,
           "has_battery": has_battery, "charging": charging, "low": low, "critical": critical,
           "battery_saver": bool(int(raw.SystemStatusFlag) & 1), "seconds_left": seconds}
    out["said"] = words(out)
    return out


def words(state: dict) -> str:
    """The power state as he would say it."""
    if not state.get("known"):
        return str(state.get("said") or "the power state is not known")
    pct = state.get("battery_percent")
    level = f" at {pct}%" if pct is not None and state.get("has_battery") is not False else ""
    if state.get("on_ac"):
        if state.get("has_battery") is False:
            return "on mains power (no battery)"
        return "plugged in" + (f", battery{level.replace(' at', '')}" if level else "") \
            + (" and charging" if state.get("charging") else "")
    said = "on battery" + level
    if state.get("critical"):
        said += ", critically low"
    elif state.get("low"):
        said += ", low"
    if state.get("seconds_left"):
        minutes = int(state["seconds_left"]) // 60
        said += f", about {minutes} minutes left"
    return said


# ---- holding the machine awake -----------------------------------------------

_LOCAL = threading.local()


def _holds_dir():
    from aletheia import stateio
    return stateio.private_dir("power", "holds")


def _marker_path():
    return _holds_dir() / f"hold-{os.getpid()}-{threading.get_ident()}.json"


@contextlib.contextmanager
def keep_awake(reason: str, *, kernel32: Any = None, watch_power: bool = True) -> Iterator[dict]:
    """Keep the PC from sleeping while the body runs; release after.

    Yields what was held: {"held": bool, "reason", "why"}. Off Windows,
    or when the call fails, `held` is False and the body still runs - a
    missing keep-awake is a reason to tell him, never a reason not to work.
    """
    depth = int(getattr(_LOCAL, "depth", 0))
    if depth > 0:
        _LOCAL.depth = depth + 1
        try:
            yield dict(_LOCAL.hold)
        finally:
            _LOCAL.depth -= 1
        return
    k = _kernel32(kernel32)
    hold = {"held": False, "reason": " ".join(str(reason or "work").split())[:120], "why": ""}
    if k is None:
        hold["why"] = "not on Windows"
    else:
        try:
            previous = k.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            hold["held"] = bool(previous)
            if not previous:
                hold["why"] = "SetThreadExecutionState refused"
        except Exception as exc:  # noqa: BLE001
            hold["why"] = f"SetThreadExecutionState failed ({type(exc).__name__})"
    _LOCAL.depth, _LOCAL.hold = 1, hold
    marker = None
    try:
        from aletheia import stateio
        marker = _marker_path()
        stateio.write_json_atomic(marker, {"pid": os.getpid(), "thread": threading.get_ident(),
                                           "reason": hold["reason"], "held": hold["held"],
                                           "started_at": stateio.utcnow()})
    except Exception:
        marker = None
    if watch_power:
        try:
            watch(working=True, kernel32=kernel32)
        except Exception:
            pass
    try:
        yield dict(hold)
    finally:
        _LOCAL.depth = 0
        if hold["held"] and k is not None:
            try:
                k.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:
                pass
        if marker is not None:
            try:
                marker.unlink()
            except OSError:
                pass


def holds() -> list[dict]:
    """Every keep-awake a live process holds right now. Reading only: the
    marker of a process that died is ignored, not deleted."""
    from aletheia import proc
    try:
        paths = sorted(_holds_dir().glob("hold-*.json"))
    except Exception:
        return []
    out = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        pid = value.get("pid")
        if pid == os.getpid() or proc.pid_alive(pid) is not False:
            out.append({k: value.get(k) for k in ("pid", "reason", "held", "started_at")})
    return out


# ---- telling him --------------------------------------------------------------

def _state_path():
    from aletheia import stateio
    return stateio.private_dir("power") / "state.json"


def _load_state() -> dict:
    try:
        value = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def watch(*, working: bool, now: dt.datetime | None = None, kernel32: Any = None,
          publish: Callable[..., Any] | None = None) -> dict:
    """Read the power state and notify him once per episode. Returns what it
    saw and what it said. Never raises for a notification that failed."""
    from aletheia import stateio
    now = _now(now)
    state = status(kernel32=kernel32)
    remembered = _load_state()
    told: list[str] = []
    if not state["known"]:
        return {"status": state, "told": told}
    if state["on_ac"]:
        if remembered.get("battery_since"):
            try:
                stateio.write_json_atomic(_state_path(), {"battery_since": None,
                                                          "ac_since": _stamp(now)})
            except Exception:
                pass
        return {"status": state, "told": told}
    since = remembered.get("battery_since")
    if not since:
        since = _stamp(now)
        try:
            stateio.write_json_atomic(_state_path(), {"battery_since": since, "ac_since": None})
        except Exception:
            pass
    if publish is None:
        from aletheia import notifications
        publish = notifications.publish
    level = f" ({state['battery_percent']}%)" if state.get("battery_percent") is not None else ""
    if working:
        try:
            publish("The PC is on battery while I'm working",
                    f"I'm in the middle of something and the PC is {state['said']}. Plug it in: "
                    "on battery Windows can put it to sleep, and then I go silent until it wakes.",
                    priority="IMPORTANT", source="power", dedupe_key=f"power-battery:{since}")
            told.append("on_battery")
        except Exception:
            pass
    if state["low"]:
        try:
            publish("The PC's battery is low" + level,
                    f"The PC is {state['said']}. When it runs out Windows will sleep or hibernate "
                    "it and nothing I'm doing can continue. Plug it in.",
                    priority="URGENT" if state["critical"] else "IMPORTANT", source="power",
                    dedupe_key=f"power-low:{since}")
            told.append("low")
        except Exception:
            pass
    return {"status": state, "told": told, "battery_since": since}


# ---- for current_state and the header ------------------------------------------

def section(*, kernel32: Any = None) -> dict:
    """The power block of current_state. Never raises."""
    try:
        state = status(kernel32=kernel32)
    except Exception as exc:  # noqa: BLE001
        state = {"known": False, "said": f"the power state could not be read ({type(exc).__name__})"}
    try:
        held = holds()
    except Exception:
        held = []
    remembered = _load_state()
    return {**state, "battery_since": remembered.get("battery_since") if state.get("on_ac") is False else None,
            "keep_awake": {"held": any(h.get("held") for h in held), "holders": held[:5]}}


def signal(block: dict | None, *, working: bool) -> dict | None:
    """The header signal: None when the power state is not known (a
    desktop, or not Windows), because a signal that always says "unknown"
    teaches him to skip the row."""
    block = block or {}
    if not block.get("known"):
        return None
    said = str(block.get("said") or words(block))
    held = (block.get("keep_awake") or {}).get("held")
    if held:
        said += "; holding the PC awake while work runs"
    out = {"what": "power", "ok": bool(block.get("on_ac")) or not (working or block.get("low")), "said": said}
    if block.get("on_ac") is False and (working or block.get("low")):
        out["banner"] = (f"The PC is {block.get('said')}"
                         + (" while work is running" if working else "")
                         + ": plug it in, or Windows may put it to sleep.")
    return out


def main(argv: list[str] | None = None) -> int:
    print(json.dumps(section(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
