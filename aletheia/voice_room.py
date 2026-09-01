"""Room voice — "Thea" spoken into the air, no browser involved.

The room listener has one job: hear an explicitly addressed utterance and put
that utterance through the same Core/gates as every other interface. It is not a
room-transcription service and it must never become a feedback oscillator.

Three failure modes found from live use are held directly in this module:

* only one room listener may run on a machine at once;
* microphone audio is discarded while Thea is speaking and briefly afterwards,
  so her own speakers cannot wake her back up; and
* a bare "Thea" opens only a short follow-up window, not an indefinite state in
  which the next random room sentence becomes a command.

Vosk remains the local wake gate and utterance segmenter. If the optional
`aletheia.voice_quality` stack has been explicitly prepared, a wake-gated
utterance is retranscribed with local faster-whisper and spoken with local Piper
neural TTS. Missing quality packages/models degrade to Vosk + Windows SAPI.
Audio never leaves the machine or touches the repo.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from aletheia import voice_quality
from aletheia.proc import run as proc_run
from aletheia.voice import WAKE_WORDS

PRIMARY_MODEL_NAME = "vosk-model-en-us-0.22-lgraph"
PRIMARY_MODEL_URL = f"https://alphacephei.com/vosk/models/{PRIMARY_MODEL_NAME}.zip"
LEGACY_MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_DIR = Path.home() / ".aletheia" / "models"
CORE_URL = "http://127.0.0.1:8777"
SAMPLE_RATE = 16_000
VOICE_LOCK = Path.home() / ".aletheia" / "run" / "voice.lock"

AGC_TARGET_PEAK = 9000
AGC_MAX_GAIN = 40
AGC_FLOOR = 200
WAKE_GRAMMAR = '["thea", "aletheia", "hey thea", "[unk]"]'
WAKE_CONFIDENCE_MIN = 0.70
# Standard planning owns a 90-second total provider budget.  The listener must
# outwait that contract plus response/HTTP overhead or it can abandon a healthy
# answer while the Core is still doing exactly what its deadline permits.
FOLLOWUP_WAIT_S = 120.0
FOLLOWUP_POLL_S = 1.0
FOLLOWUP_EXPIRED_SAY = (
    "I couldn't deliver that answer before it expired. Please ask me again."
)
FOLLOWUP_TIMEOUT_SAY = (
    "That is taking longer than expected, and I couldn't confirm the answer."
)
BARE_WAKE_WINDOW_S = 8.0
OUTPUT_TAIL_S = 0.55
REPEAT_FAILURE_WINDOW_S = 20.0

_OUTPUT_ACTIVE = threading.Event()
_OUTPUT_LOCK = threading.Lock()
_output_generation = 0
_ignore_audio_until = 0.0


# ---------------------------------------------------------------- mouth
def sapi_speak(text: str) -> None:
    """Fallback mouth: the local Windows SAPI voice, blocking until done."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = 1; $s.Speak([Console]::In.ReadToEnd())"
    )
    proc_run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        input=text, text=True, capture_output=True, timeout=120,
    )


def speak(text: str) -> None:
    """Speak once while hard-muting the ears against our own output.

    Piper is preferred only when it was explicitly prepared. Provider failure is
    silent and falls back to SAPI; a broken mouth must not create a spoken error
    about the broken mouth and start a loop.
    """
    global _ignore_audio_until, _output_generation
    if not isinstance(text, str) or not text.strip():
        return
    with _OUTPUT_LOCK:
        _OUTPUT_ACTIVE.set()
        try:
            if not voice_quality.piper_speak(text):
                sapi_speak(text)
        finally:
            _OUTPUT_ACTIVE.clear()
            _ignore_audio_until = time.monotonic() + OUTPUT_TAIL_S
            _output_generation += 1


# ---------------------------------------------------------------- instance lock
class VoiceInstanceLock:
    """OS-held singleton lock. A stale file is harmless; the OS lock is truth."""

    def __init__(self, path: Path = VOICE_LOCK):
        self.path = Path(path)
        self.handle = None
        self.locked = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            handle.close()
            return False
        self.handle = handle
        self.locked = True
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()).encode("ascii"))
            handle.flush()
        except OSError:
            pass
        return True

    def release(self) -> None:
        if not self.locked or self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass
        try:
            self.handle.close()
        finally:
            self.handle = None
            self.locked = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


# ----------------------------------------------------------------- ears
def _model_path() -> Path | None:
    for name in (PRIMARY_MODEL_NAME, LEGACY_MODEL_NAME):
        target = MODEL_DIR / name
        if (target / "am").is_dir() or (target / "conf").is_dir():
            return target
    return None


def model_ready() -> tuple[bool, str]:
    target = _model_path()
    if target is None:
        return False, (
            "recognizer model not downloaded — run --setup "
            f"(preferred model is ~128MB under {MODEL_DIR})"
        )
    if target.name == LEGACY_MODEL_NAME:
        return True, f"{target} (legacy 40MB model; --setup upgrades the ears)"
    return True, str(target)


def download_model() -> Path:
    """Install the better 128MB Vosk model; legacy remains a runtime fallback."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / PRIMARY_MODEL_NAME
    if (target / "am").is_dir() or (target / "conf").is_dir():
        return target
    archive = MODEL_DIR / f"{PRIMARY_MODEL_NAME}.zip"
    print(f"downloading improved recognizer {PRIMARY_MODEL_URL} ...")
    urllib.request.urlretrieve(PRIMARY_MODEL_URL, archive)
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(MODEL_DIR)
    finally:
        try:
            archive.unlink()
        except OSError:
            pass
    if not ((target / "am").is_dir() or (target / "conf").is_dir()):
        raise RuntimeError("recognizer archive extracted but the model is incomplete")
    print(f"recognizer ready at {target}")
    return target


def _auto_gain(chunk: bytes, state: dict) -> bytes:
    """Software AGC for the quiet laptop microphone array."""
    import array
    samples = array.array("h", chunk)
    peak = max((abs(v) for v in samples), default=0)
    state["peak"] = max(peak, state.get("peak", 0) * 0.95)
    reference = max(state["peak"], AGC_FLOOR)
    gain = min(AGC_MAX_GAIN, AGC_TARGET_PEAK / reference)
    if gain <= 1.5:
        return chunk
    boosted = array.array(
        "h", (max(-32768, min(32767, int(v * gain))) for v in samples)
    )
    return boosted.tobytes()


def _wake_detected(result: dict, *, minimum: float = WAKE_CONFIDENCE_MIN) -> bool:
    """Require the constrained spotter to actually hear a wake token.

    When Vosk provides word confidence, low-confidence nearest-word guesses are
    refused. `[unk]` in the grammar is important: without it unrelated room
    speech would be forced into the nearest wake phrase.
    """
    words = result.get("result")
    if isinstance(words, list) and words:
        for item in words:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word", "")).casefold()
            try:
                confidence = float(item.get("conf", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if word in {"thea", "aletheia"} and confidence >= minimum:
                return True
        return False
    # Older Vosk builds may omit word detail even after SetWords(True).
    tokens = str(result.get("text", "")).casefold().split()
    return "thea" in tokens or "aletheia" in tokens


def _drain(q: queue.Queue) -> None:
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def microphone_recognizer():
    """Yield `(wake_heard, transcript)` for local utterances.

    Vosk does the cheap continuous work: utterance segmentation plus a constrained
    wake spotter. Whisper, when prepared, only retranscribes an utterance AFTER
    that wake gate fired. This gives the better recognizer to actual commands
    without continuously transcribing private room conversation.
    """
    import sounddevice as sd
    import vosk

    ok, where = model_ready()
    if not ok:
        raise RuntimeError(where)
    model_path = _model_path()
    if model_path is None:
        raise RuntimeError(where)
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(model_path))
    full = vosk.KaldiRecognizer(model, SAMPLE_RATE)
    wake = vosk.KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
    try:
        wake.SetWords(True)
    except AttributeError:
        pass

    audio: queue.Queue[bytes] = queue.Queue(maxsize=40)
    agc_state: dict = {}
    utterance = bytearray()
    seen_generation = _output_generation

    def on_audio(indata, frames, time_info, status):
        del frames, time_info, status
        if _OUTPUT_ACTIVE.is_set() or time.monotonic() < _ignore_audio_until:
            return
        try:
            audio.put_nowait(bytes(indata))
        except queue.Full:
            # Stale audio is worse than dropped audio. Keep the newest chunk.
            try:
                audio.get_nowait()
            except queue.Empty:
                pass
            try:
                audio.put_nowait(bytes(indata))
            except queue.Full:
                pass

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16",
        channels=1, callback=on_audio,
    ):
        while True:
            if seen_generation != _output_generation:
                seen_generation = _output_generation
                _drain(audio)
                utterance.clear()
                agc_state.clear()
                full.Reset()
                wake.Reset()
            data = _auto_gain(audio.get(), agc_state)
            utterance.extend(data)
            wake.AcceptWaveform(data)
            if not full.AcceptWaveform(data):
                continue
            text = json.loads(full.Result()).get("text", "").strip()
            wake_result = json.loads(wake.FinalResult())
            wake.Reset()
            heard_wake = _wake_detected(wake_result)
            if heard_wake:
                better = voice_quality.transcribe_pcm(bytes(utterance), sample_rate=SAMPLE_RATE)
                if better:
                    text = better
            utterance.clear()
            if text or heard_wake:
                yield heard_wake, text


# ----------------------------------------------------------------- loop
def is_addressed(text: str) -> bool:
    """Only speech that starts with a wake word is for Aletheia."""
    first = text.strip().lower().split(" ", 1)[0].strip(",.!?")
    return first in WAKE_WORDS


def collect_followup(followup_id: str, core_url: str = CORE_URL,
                     wait_s: float = FOLLOWUP_WAIT_S,
                     poll_s: float = FOLLOWUP_POLL_S, sleep=None,
                     monotonic=None) -> str | None:
    """Poll without consuming; the caller ACKs only after speech succeeds."""
    import time as _time
    sleep = sleep or _time.sleep
    monotonic = monotonic or _time.monotonic
    deadline = monotonic() + wait_s
    while monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{core_url}/api/voice/followup?id={followup_id}", timeout=5
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            # A self-update or brief socket failure must not turn the promised
            # answer into silence. Keep polling within the same bounded wait.
            sleep(poll_s)
            continue
        if payload.get("state") in ("READY", "FAILED"):
            return payload.get("say")
        if payload.get("state") == "EXPIRED":
            return FOLLOWUP_EXPIRED_SAY
        sleep(poll_s)
    return FOLLOWUP_TIMEOUT_SAY


def acknowledge_followup(followup_id: str, core_url: str = CORE_URL,
                         attempts: int = 3, sleep=None) -> bool:
    """Tell the Core a finished sentence was actually spoken.

    ACK is separate from GET so a dropped response never consumes the only copy.
    It happens after the blocking speaker returns. A lost ACK response is safe to
    retry: EXPIRED means the first ACK already removed the finished slot.
    """
    import time as _time
    sleep = sleep or _time.sleep
    body = json.dumps({"id": followup_id}).encode("utf-8")
    for attempt in range(max(1, attempts)):
        req = urllib.request.Request(
            f"{core_url}/api/voice/followup/ack", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            if attempt + 1 < max(1, attempts):
                sleep(0.1)
            continue
        return payload.get("state") in ("ACKED", "EXPIRED")
    return False


def ask_core(transcript: str, core_url: str = CORE_URL) -> dict:
    req = urllib.request.Request(
        f"{core_url}/api/voice",
        data=json.dumps({"transcript": transcript}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "say": payload.get("say") or payload.get("detail") or "done",
        "followup_id": payload.get("followup_id"),
    }


def _strip_leading_garbage(text: str) -> str:
    """Drop only known wake-word mangles; never eat a legitimate first word."""
    words = text.split()
    if words and words[0].casefold() in {
        "thea", "aletheia", "yeah", "idea", "hey", "via", "tia"
    }:
        return " ".join(words[1:])
    return text


def _is_failure_line(text: str) -> bool:
    low = str(text).strip().casefold()
    return low.startswith(("i couldn't", "i could not", "i can't", "that failed", "couldn't"))


def listen_forever(recognizer=None, speaker=None, core_url: str = CORE_URL,
                   max_utterances: int | None = None, on_heard=None,
                   monotonic=time.monotonic) -> int:
    """Wake -> command, with no unsolicited speech and no indefinite follow-up.

    A bare wake word opens an eight-second follow-up window. If that expires,
    ordinary room speech is ignored again. Identical failure lines are also
    throttled briefly as a final guard against a provider/error feedback loop.
    """
    recognizer = recognizer if recognizer is not None else microphone_recognizer()
    speaker = speaker or speak
    handled = 0
    awaiting_since: float | None = None
    last_failure = ""
    last_failure_at = -1e9

    def say(line: str | None) -> None:
        nonlocal last_failure, last_failure_at
        if not line:
            return
        now = monotonic()
        normalized = " ".join(str(line).split())
        if (_is_failure_line(normalized) and normalized == last_failure
                and now - last_failure_at < REPEAT_FAILURE_WINDOW_S):
            return
        speaker(normalized)
        if _is_failure_line(normalized):
            last_failure, last_failure_at = normalized, now

    for wake_heard, text in recognizer:
        now = monotonic()
        if on_heard:
            on_heard((wake_heard, text))

        if awaiting_since is not None and now - awaiting_since <= BARE_WAKE_WINDOW_S:
            raw = text.strip()
            if not raw:
                continue
            if is_addressed(raw):
                command = raw.split(" ", 1)[1] if " " in raw else ""
            elif wake_heard:
                command = _strip_leading_garbage(raw)
            else:
                command = raw
            if not command.strip():
                say("Yes?")
                awaiting_since = monotonic()
                continue
            awaiting_since = None
        else:
            awaiting_since = None
            if not (wake_heard or is_addressed(text)):
                continue
            if is_addressed(text):
                command = text.split(" ", 1)[1] if " " in text else ""
            else:
                command = _strip_leading_garbage(text)
            if not command.strip():
                say("Yes?")
                awaiting_since = monotonic()
                continue

        try:
            answer = ask_core(f"thea {command}", core_url)
            reply = answer["say"]
            followup_id = answer.get("followup_id")
        except Exception as exc:
            reply = f"I couldn't reach my Core: {type(exc).__name__}"
            followup_id = None
        say(reply)
        if followup_id:
            later = collect_followup(followup_id, core_url)
            if later:
                # ACK only after the blocking speaker returns. If speech itself
                # fails, the finished slot remains undelivered rather than being
                # falsely marked as heard.
                say(later)
                acknowledge_followup(followup_id, core_url)
        handled += 1
        if max_utterances is not None and handled >= max_utterances:
            return handled
    return handled


# ---------------------------------------------------------------- readiness/setup
def check() -> int:
    """Report exactly what the live listener can use; quality providers optional."""
    problems = []
    try:
        import vosk  # noqa: F401
        import sounddevice as sd
        try:
            device = sd.query_devices(kind="input")["name"]
            print(f"microphone: {device}")
        except Exception as exc:
            problems.append(f"no default microphone: {exc}")
    except ImportError as exc:
        problems.append(f"missing package: {exc.name} (pip install vosk sounddevice)")

    try:
        from comtypes import CLSCTX_ALL, CoCreateInstance
        from pycaw.constants import CLSID_MMDeviceEnumerator
        from pycaw.pycaw import EDataFlow, ERole, IAudioEndpointVolume, IMMDeviceEnumerator
        enumerator = CoCreateInstance(
            CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL
        )
        mic_dev = enumerator.GetDefaultAudioEndpoint(
            EDataFlow.eCapture.value, ERole.eCommunications.value
        )
        vol = mic_dev.Activate(
            IAudioEndpointVolume._iid_, CLSCTX_ALL, None
        ).QueryInterface(IAudioEndpointVolume)
        if vol.GetMute():
            problems.append(
                "the microphone endpoint is MUTED in Windows — unmute it in Sound settings"
            )
        else:
            print(f"mic endpoint: unmuted, level {vol.GetMasterVolumeLevelScalar():.0%}")
    except Exception:
        pass

    ok, where = model_ready()
    print(f"wake/segmenter: {where}" if ok else f"wake/segmenter: MISSING — {where}")
    if not ok:
        problems.append("recognizer model not downloaded")

    q_ok, q_why = voice_quality.whisper_ready()
    print(f"command recognizer: {q_why if q_ok else 'Vosk fallback — ' + q_why}")
    t_ok, t_why = voice_quality.piper_ready()
    print(f"voice: {t_why if t_ok else 'Windows SAPI fallback — ' + t_why}")

    try:
        with urllib.request.urlopen(f"{CORE_URL}/api/status", timeout=3):
            print(f"core: answering at {CORE_URL}")
    except Exception:
        problems.append(f"core not answering at {CORE_URL}")

    if problems:
        print("NOT READY: " + "; ".join(problems))
        return 1
    print("ready — run: python -m aletheia.voice_room")
    return 0


def setup() -> int:
    """Upgrade both the required wake model and optional neural speech stack."""
    failures = 0
    try:
        download_model()
    except Exception as exc:
        print(f"recognizer setup failed: {type(exc).__name__}: {exc}")
        failures += 1
    quality = voice_quality.setup_quality(install=True)
    for name in ("packages", "piper", "whisper"):
        item = quality.get(name)
        if not item:
            continue
        print(f"{name}: {'ready' if item['ok'] else 'not ready'} — {item['detail']}")
    # Neural quality is optional: do not make the listener unusable because an
    # enhancement package failed. The required Vosk model decides setup exit.
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia room voice (local wake word).")
    ap.add_argument("--check", action="store_true", help="report readiness honestly")
    ap.add_argument("--setup", action="store_true",
                    help="upgrade recognizer and prepare local neural speech")
    ap.add_argument("--say", help="speak one sentence and exit")
    args = ap.parse_args(argv)

    if args.say:
        speak(args.say)
        return 0
    if args.setup:
        return setup()
    if args.check:
        return check()

    lock = VoiceInstanceLock()
    if not lock.acquire():
        # A repeating scheduled-task trigger or a manual launch must never make
        # a second microphone/mouth. Quiet exit is intentional under pythonw.
        print("room voice is already running — second listener refused")
        return 0
    try:
        if check() != 0:
            return 1
        from aletheia import journal
        journal.use_pc_journal()
        journal.append(
            "event", "voice:room", "room voice listening (single local wake listener)",
            actor="aletheia-voice",
        )
        print('listening — say "Thea, ..." (Ctrl+C stops)')
        try:
            listen_forever()
        except KeyboardInterrupt:
            journal.append(
                "event", "voice:room", "room voice stopped by operator",
                actor="aletheia-voice",
            )
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
