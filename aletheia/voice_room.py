"""Room voice — "Thea" spoken into the air, no browser involved (Phase 10).

    python -m aletheia.voice_room --check    # honest readiness report
    python -m aletheia.voice_room            # listen until Ctrl+C

Ears: vosk, a local offline recognizer (no API keys, §6) reading the
default microphone through sounddevice. Mouth: Windows' own SAPI voice
(PowerShell System.Speech — stdlib-adjacent, nothing to install).
Brain and gates: every recognized sentence goes to the SAME place the
wall's browser mic goes — `voice.interpret` → `core.run_command` →
intercom grammar → policy — via POST /api/voice on the local Core. This
module adds EARS, never authority.

The wake word is checked here AND in voice.strip_wake_word server-side;
a sentence without it is dropped without being journaled (a room mic
overhears things — only addressed speech leaves this process, and audio
itself never leaves the machine or touches disk).

The recognizer model lives in ~/.aletheia/models/ (downloaded once,
~40MB, never the repo). Seams for tests: any `recognizer` yielding
transcripts and any `speaker` accepting text can replace the real ones.
"""
from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from aletheia.voice import WAKE_WORDS
from aletheia.proc import run as proc_run

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_DIR = Path.home() / ".aletheia" / "models"
CORE_URL = "http://127.0.0.1:8777"
SAMPLE_RATE = 16000


# ---------------------------------------------------------------- mouth
def sapi_speak(text: str) -> None:
    """One utterance through the default Windows voice; blocks until done."""
    script = ("Add-Type -AssemblyName System.Speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$s.Rate = 1; $s.Speak([Console]::In.ReadToEnd())")
    proc_run(["powershell", "-NoProfile", "-Command", script],
                   input=text, text=True, capture_output=True, timeout=120)


# ----------------------------------------------------------------- ears
def model_ready() -> tuple[bool, str]:
    target = MODEL_DIR / MODEL_NAME
    if (target / "am").is_dir() or (target / "conf").is_dir():
        return True, str(target)
    return False, f"model not downloaded — run --setup (fetches ~40MB to {target})"


def download_model() -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / MODEL_NAME
    if model_ready()[0]:
        return target
    archive = MODEL_DIR / f"{MODEL_NAME}.zip"
    print(f"downloading {MODEL_URL} …")
    urllib.request.urlretrieve(MODEL_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(MODEL_DIR)
    archive.unlink()
    print(f"model ready at {target}")
    return target


AGC_TARGET_PEAK = 9000   # scale speech toward this int16 level
AGC_MAX_GAIN = 40        # this laptop's array peaks ~500 raw — 20-40x needed
AGC_FLOOR = 200          # below this, treat as noise; don't amplify silence


def _auto_gain(chunk: bytes, state: dict) -> bytes:
    """Software AGC: the operator's mic array delivers speech at peak ~500
    of 32768 (found live 2026-08-26 — vosk heard NOTHING until 20x gain).
    Track a decaying peak and scale toward AGC_TARGET_PEAK."""
    import array
    samples = array.array("h", chunk)
    peak = max((abs(v) for v in samples), default=0)
    state["peak"] = max(peak, state.get("peak", 0) * 0.95)  # decay 5%/chunk
    reference = max(state["peak"], AGC_FLOOR)
    gain = min(AGC_MAX_GAIN, AGC_TARGET_PEAK / reference)
    if gain <= 1.5:
        return chunk
    boosted = array.array("h", (max(-32768, min(32767, int(v * gain)))
                                for v in samples))
    return boosted.tobytes()


WAKE_GRAMMAR = '["thea", "aletheia", "hey thea", "[unk]"]'


def microphone_recognizer():
    """Yield (wake_heard, transcript) per utterance from the microphone.

    Two decoders share the stream: the FULL model transcribes the words,
    and a GRAMMAR-constrained spotter listens only for the wake word —
    because the small model cannot spell 'Thea' in open dictation (live
    findings: 'Thea'->'yeah'/'idea', 'Aletheia status'->'everything is
    dennis'). Constrained decoding makes the name reliable; the open
    transcript still carries the command words.
    """
    import sounddevice as sd
    import vosk
    ok, where = model_ready()
    if not ok:
        raise RuntimeError(where)
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(MODEL_DIR / MODEL_NAME))
    full = vosk.KaldiRecognizer(model, SAMPLE_RATE)
    wake = vosk.KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
    audio: queue.Queue[bytes] = queue.Queue()
    agc_state: dict = {}

    def on_audio(indata, frames, time_info, status):
        audio.put(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=8000, dtype="int16",
                           channels=1, callback=on_audio):
        while True:
            data = _auto_gain(audio.get(), agc_state)
            wake.AcceptWaveform(data)
            if full.AcceptWaveform(data):
                text = json.loads(full.Result()).get("text", "").strip()
                spotted = json.loads(wake.FinalResult()).get("text", "")
                wake.Reset()
                heard_wake = any(w in spotted.split() for w in ("thea", "aletheia"))
                if text or heard_wake:
                    yield heard_wake, text


# ----------------------------------------------------------------- loop
def is_addressed(text: str) -> bool:
    """Only speech that starts with a wake word is for Aletheia."""
    first = text.strip().lower().split(" ", 1)[0].strip(",.!?")
    return first in WAKE_WORDS


def ask_core(transcript: str, core_url: str = CORE_URL) -> str:
    req = urllib.request.Request(
        f"{core_url}/api/voice",
        data=json.dumps({"transcript": transcript}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("say") or payload.get("detail") or "done"


def _strip_leading_garbage(text: str) -> str:
    """Drop the first token when it is the open model's mangling of the
    wake word ('yeah that's going on' for 'Thea, what's going on')."""
    words = text.split()
    if words and words[0] in {"thea", "aletheia", "yeah", "idea", "hey", "the", "via", "tia"}:
        return " ".join(words[1:])
    return text


def listen_forever(recognizer=None, speaker=None, core_url: str = CORE_URL,
                   max_utterances: int | None = None, on_heard=None) -> int:
    """The room loop: wake -> command, one breath or two.

    'Thea, what's going on' handles in one utterance. A bare 'Thea'
    answers 'Yes?' and the NEXT utterance is the command, no wake word
    needed. Unaddressed speech is dropped without being journaled.
    recognizer yields (wake_heard, transcript); seams exist for tests.
    """
    recognizer = recognizer if recognizer is not None else microphone_recognizer()
    speaker = speaker or sapi_speak
    handled = 0
    awaiting_command = False
    for wake_heard, text in recognizer:
        if on_heard:
            on_heard((wake_heard, text))
        if awaiting_command:
            command = text.strip()
            awaiting_command = False
            if not command:
                continue
        elif wake_heard or is_addressed(text):
            command = _strip_leading_garbage(text) if not is_addressed(text) else                 text.split(" ", 1)[1] if " " in text else ""
            if not command.strip():
                speaker("Yes?")
                awaiting_command = True
                continue
        else:
            continue  # overheard speech: not for her, never journaled
        try:
            reply = ask_core(f"thea {command}", core_url)
        except Exception as exc:
            reply = f"I couldn't reach my Core: {type(exc).__name__}"
        speaker(reply)
        handled += 1
        if max_utterances is not None and handled >= max_utterances:
            return handled
    return handled


def check() -> int:
    """Say exactly what is and isn't ready — never pretend (§106)."""
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
        # the endpoint was found hardware-MUTED live 2026-08-26 — the same
        # silent failure that broke the browser mic. Report it, honestly.
        from comtypes import CLSCTX_ALL, CoCreateInstance
        from pycaw.constants import CLSID_MMDeviceEnumerator
        from pycaw.pycaw import EDataFlow, ERole, IAudioEndpointVolume, IMMDeviceEnumerator
        enumerator = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
        mic_dev = enumerator.GetDefaultAudioEndpoint(EDataFlow.eCapture.value, ERole.eCommunications.value)
        vol = mic_dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)
        if vol.GetMute():
            problems.append("the microphone endpoint is MUTED in Windows — unmute it "
                            "(sound settings, or the keyboard's mic-mute key)")
        else:
            print(f"mic endpoint: unmuted, level {vol.GetMasterVolumeLevelScalar():.0%}")
    except Exception:
        pass  # pycaw optional; absence of the check is not a failure
    ok, where = model_ready()
    print(f"model: {where}" if ok else f"model: MISSING — {where}")
    if not ok:
        problems.append("model not downloaded")
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia room voice (local wake word).")
    ap.add_argument("--check", action="store_true", help="report readiness honestly")
    ap.add_argument("--setup", action="store_true", help="download the recognizer model")
    ap.add_argument("--say", help="speak one sentence through the PC voice and exit")
    args = ap.parse_args(argv)
    if args.say:
        sapi_speak(args.say)
        return 0
    if args.setup:
        download_model()
        return 0
    if args.check:
        return check()
    if check() != 0:
        return 1
    from aletheia import journal
    journal.use_pc_journal()
    journal.append("event", "voice:room", "room voice listening (local wake word)",
                   actor="aletheia-voice")
    print('listening — say "Thea, …" (Ctrl+C stops)')
    try:
        listen_forever()
    except KeyboardInterrupt:
        journal.append("event", "voice:room", "room voice stopped by operator",
                       actor="aletheia-voice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
