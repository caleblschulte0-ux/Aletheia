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

from aletheia import speech, voice_quality
from aletheia import proc
from aletheia import voice
from aletheia.voice import WAKE_WORDS

PRIMARY_MODEL_NAME = "vosk-model-en-us-0.22-lgraph"
PRIMARY_MODEL_URL = f"https://alphacephei.com/vosk/models/{PRIMARY_MODEL_NAME}.zip"
LEGACY_MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_DIR = Path.home() / ".aletheia" / "models"
CORE_URL = "http://127.0.0.1:8777"
SAMPLE_RATE = 16_000
VOICE_LOCK = Path.home() / ".aletheia" / "run" / "voice.lock"

# How often the room checks whether it has anything to say first. Every
# utterance would re-read the whole notification store for a question that
# is almost always "nothing"; `announce` has its own per-hour cap, so this
# is only about not doing the work, never about how often she speaks.
ANNOUNCE_EVERY_S = 20.0

AGC_TARGET_PEAK = 9000
AGC_MAX_GAIN = 40
AGC_FLOOR = 200
WAKE_GRAMMAR = '["thea", "aletheia", "hey thea", "[unk]"]'
WAKE_CONFIDENCE_MIN = 0.70
FOLLOWUP_WAIT_S = 105.0
FOLLOWUP_POLL_S = 1.0
FOLLOWUP_FAILURE = "I couldn't finish that answer. Please ask me again."
#: The room stopped WAITING; she did not stop WORKING. With the subscriptions
#: out, her own model can take minutes, the follow-up is still running, and its
#: answer lands as a notification - so "I couldn't finish" would be untrue.
FOLLOWUP_STILL_WORKING = ("This is taking me longer than I can wait for here. I'm still "
                          "working on it, and the answer will be in your notifications.")
BARE_WAKE_WINDOW_S = 8.0
OUTPUT_TAIL_S = 0.55
REPEAT_FAILURE_WINDOW_S = 20.0
# How long she may be silent before saying she is thinking. Deliberately
# measured rather than guessed: the acknowledgement fires because the reply
# IS late, not because a classifier decided the request looked hard. So a
# question `quick` answers from a file (~10ms) is never preceded by "let me
# look", and nothing has to know in advance which asks are slow.
ACK_AFTER_S = 1.2
# ...but not for a question that is about to land anyway. A fact about
# the world is one model round trip — roughly four seconds — and a flat
# 1.2s ack made her interrupt herself: "Working on it." ... "Reykjavik."
# Three seconds of silence first means most quick answers never need the
# line, and a slow one still gets acknowledged before the silence starts
# to read as "she didn't hear me". Real work keeps the short wait,
# because there she is genuinely about to go quiet for a while.
# FIVE, from his own sentence: "it should come back within five seconds
# and tell me Reykjavik." Measured, that answer takes 3.2s — so at three
# seconds she would have said "Let me look." two tenths of a second
# before saying "Reykjavik", which is the worst place to put it. Past
# five, the question really is slow and the silence needs breaking.
ACK_AFTER_QUICK_S = 5.0
STILL_AFTER_S = 12.0
# How often the waiter re-checks. Small enough that the acknowledgement
# lands on time, large enough to cost nothing.
ACK_WAIT_TICK_S = 0.1
# The three lines that only ever mean "still working". The room says one
# when the Core is slow to answer AND the Core sends one back when it hands
# the work to a followup — so both can land, and "Let me look. Let me look."
# is exactly how a thing sounds when it is stuck. Only these are
# de-duplicated: a real ANSWER repeated is him asking twice and deserving
# an answer twice.
ACK_LINES = frozenset({speech.ACK_QUESTION, speech.ACK_ACTION, speech.ACK_STILL})
REPEAT_ACK_WINDOW_S = 30.0

_OUTPUT_ACTIVE = threading.Event()
_OUTPUT_LOCK = threading.Lock()
_output_generation = 0
_ignore_audio_until = 0.0


# ------------------------------------------------------------- barge-in
# HE CAN TALK OVER HER. Until now the ears were hard-muted for as long as
# she was speaking, so a forty-word answer was forty seconds in which the
# only way to stop her was to leave the room. Everything else about the
# voice is a wording problem; this one is the difference between talking
# to her and being talked AT.
#
# The mute existed for a real reason — her own speakers wake her up — so
# barge-in keeps the guard and narrows it. While she is speaking the audio
# no longer goes to the wide recognizer; it goes to a CONSTRAINED one that
# can only hear a handful of words, and two things have to be true before
# a word counts:
#
#   * it is a word he would use to cut in — her name, or "stop"/"wait";
#   * it is NOT a word she is saying this second. Her own voice coming
#     back through the microphone can only ever repeat what she just said,
#     so the sentence in her mouth is the echo cancellation.
#
# A false positive costs him one repeated sentence. A false negative is
# the thing he is complaining about, so the bias is deliberate.
BARGE_GRAMMAR = ('["thea", "aletheia", "stop", "wait", "hold on", '
                 '"never mind", "[unk]"]')
BARGE_WORDS = frozenset({"thea", "aletheia", "stop", "wait", "hold", "on",
                         "never", "mind"})
#: Enough on its own. "on", "never" and "mind" are in the grammar so the
#: phrase is transcribable, but no single one of them may interrupt her.
BARGE_ALONE = frozenset({"thea", "aletheia", "stop", "wait"})
#: Stricter than the wake gate. The wake gate is deciding whether to
#: answer; this is deciding whether to stop mid-word, with her own
#: loudspeaker in the same room.
BARGE_CONFIDENCE_MIN = 0.85

_INTERRUPT = threading.Event()
_INTERRUPT_LOCK = threading.Lock()
_stop_sound: list = []          # cut the sound that is playing RIGHT NOW
_interrupt_pending = False      # his sentence is coming; take it
_now_saying = ""                # the echo guard: what is in her mouth


def speaking() -> bool:
    """Is she talking this second?"""
    return _OUTPUT_ACTIVE.is_set()


def barge_in_heard(result: dict, now_saying: str = "",
                   minimum: float = BARGE_CONFIDENCE_MIN) -> bool:
    """Did HE just talk over her? A pure decision, so it can be tested.

    `result` is what the constrained recognizer returned; `now_saying` is
    the sentence currently coming out of the speakers. A word she is
    saying is not evidence that he said it — it is evidence that the
    microphone can hear her, which was never in doubt.
    """
    hers = speech.bare_words(now_saying)
    words = result.get("result")
    if isinstance(words, list) and words:
        for item in words:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word", "")).casefold().strip(",.!?")
            try:
                confidence = float(item.get("conf", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if word in BARGE_ALONE and word not in hers and confidence >= minimum:
                return True
        return False
    # Older Vosk builds hand back text with no per-word confidence. Then
    # the only guard left is the echo one, so require the whole utterance
    # to be words he could plausibly have said over her.
    heard = sorted(speech.bare_words(result.get("text", "")))
    if not heard or len(heard) > 3:
        return False
    return any(w in BARGE_ALONE and w not in hers for w in heard)


def interrupt_speech() -> bool:
    """Stop talking NOW, and remember that his sentence is coming.

    Returns False when she was not speaking, so a stray detection cannot
    open a command window out of nothing.
    """
    global _interrupt_pending
    if not _OUTPUT_ACTIVE.is_set():
        return False
    _INTERRUPT.set()
    with _INTERRUPT_LOCK:
        _interrupt_pending = True
        stoppers = list(_stop_sound)
    for stop in stoppers:
        try:
            stop()
        except Exception:
            pass      # a mouth that will not shut up must not crash the ears
    return True


def take_interrupt() -> bool:
    """Was she cut off since this was last asked? Consumed once."""
    global _interrupt_pending
    with _INTERRUPT_LOCK:
        was, _interrupt_pending = _interrupt_pending, False
    return was


def _while_playing(stop) -> None:
    """Register something that can cut the current sound short."""
    with _INTERRUPT_LOCK:
        _stop_sound.append(stop)


def _done_playing(stop) -> None:
    with _INTERRUPT_LOCK:
        if stop in _stop_sound:
            _stop_sound.remove(stop)


# ---------------------------------------------------------------- mouth
def sapi_speak(text: str) -> None:
    """Fallback mouth: the local Windows SAPI voice, blocking until done.

    Spawned rather than run, so `interrupt_speech` can end it mid-word.
    A sentence that cannot be stopped is not a sentence he can talk over.
    """
    import subprocess
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = 1; $s.Speak([Console]::In.ReadToEnd())"
    )
    child = proc.popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, text=True,
    )

    def stop() -> None:
        try:
            child.kill()
        except Exception:
            pass

    _while_playing(stop)
    try:
        child.communicate(input=text, timeout=120)
    except Exception:
        stop()
    finally:
        _done_playing(stop)


def _wav_seconds(path) -> float:
    """How long a rendered sentence lasts, so the wait is not a guess."""
    try:
        import wave
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate() or 1
            return handle.getnframes() / float(rate)
    except Exception:
        return 30.0     # a ceiling, not an estimate: the poll below ends it


def _play_interruptible(path) -> None:
    """Play a rendered sentence asynchronously and watch for him."""
    import winsound

    def stop() -> None:
        winsound.PlaySound(None, winsound.SND_PURGE)

    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    _while_playing(stop)
    try:
        deadline = time.monotonic() + _wav_seconds(path) + 0.2
        while time.monotonic() < deadline and not _INTERRUPT.is_set():
            time.sleep(0.05)
    finally:
        _done_playing(stop)
        if _INTERRUPT.is_set():
            try:
                stop()
            except Exception:
                pass


def say_chunk(text: str) -> None:
    """One breath, out loud, through whichever mouth is prepared."""
    if not voice_quality.piper_speak(text, player=_play_interruptible):
        sapi_speak(text)


def speak(text: str, *, chunk=None) -> None:
    """Speak once, in breaths he can talk over.

    Piper is preferred only when it was explicitly prepared. Provider failure is
    silent and falls back to SAPI; a broken mouth must not create a spoken error
    about the broken mouth and start a loop.

    Long answers are said a breath at a time so that even a mouth with no
    stop button gives him a gap every sentence or two, and so the rest of
    a paragraph he has already heard enough of is never said at all.
    """
    global _ignore_audio_until, _output_generation, _now_saying
    if not isinstance(text, str) or not text.strip():
        return
    chunk = chunk or say_chunk
    # THE LAST DOOR. Every sentence the room says comes through here,
    # whoever wrote it — her own model, a subsystem's receipt, an
    # exception somebody let through — so this is the one place that can
    # promise he will never hear a URL, a hex id or a class name.
    said = speech.for_the_room(text)
    if not said.strip():
        return
    with _OUTPUT_LOCK:
        _INTERRUPT.clear()
        _OUTPUT_ACTIVE.set()
        try:
            for breath in speech.breaths(said):
                if _INTERRUPT.is_set():
                    break
                _now_saying = breath
                chunk(breath)
        finally:
            cut = _INTERRUPT.is_set()
            _now_saying = ""
            _OUTPUT_ACTIVE.clear()
            # No deaf tail after an interruption: he is MID-SENTENCE, and
            # half a second of politeness there eats the first words of
            # the thing he stopped her to say.
            _ignore_audio_until = 0.0 if cut else time.monotonic() + OUTPUT_TAIL_S
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


# How fast the room notices it has been closed.
CLOSED_POLL_S = 2.0


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

    barge = vosk.KaldiRecognizer(model, SAMPLE_RATE, BARGE_GRAMMAR)
    try:
        barge.SetWords(True)
    except AttributeError:
        pass

    audio: queue.Queue[bytes] = queue.Queue(maxsize=40)
    agc_state: dict = {}
    utterance = bytearray()
    seen_generation = _output_generation

    def on_audio(indata, frames, time_info, status):
        del frames, time_info, status
        if _OUTPUT_ACTIVE.is_set():
            # LISTENING FOR HIM WHILE SHE TALKS, and for nothing else.
            # This used to be `return`, which is why she could not be
            # interrupted. The constrained recognizer can only produce
            # words from BARGE_GRAMMAR, so the room's ordinary
            # conversation cannot reach it — and `barge_in_heard` throws
            # away anything she is saying herself.
            try:
                chunk = _auto_gain(bytes(indata), agc_state)
                if barge.AcceptWaveform(chunk):
                    heard = json.loads(barge.Result())
                else:
                    heard = json.loads(barge.PartialResult() or "{}")
                    heard = {"text": heard.get("partial", "")}
                if barge_in_heard(heard, _now_saying):
                    barge.Reset()
                    interrupt_speech()
            except Exception:
                pass      # a deaf half-second is not worth a dead listener
            return
        if time.monotonic() < _ignore_audio_until:
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

    from aletheia import closed
    last_closed_check = time.monotonic()
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16",
        channels=1, callback=on_audio,
    ):
        while True:
            # Checked here rather than only at startup: he closes her while
            # she is listening, and a microphone that stays on until the
            # next reboot is not a closed window. `is_closed` is a file
            # check, so it is throttled rather than run per audio block.
            now = time.monotonic()
            if now - last_closed_check >= CLOSED_POLL_S:
                last_closed_check = now
                if closed.is_closed():
                    return
            if seen_generation != _output_generation:
                seen_generation = _output_generation
                _drain(audio)
                utterance.clear()
                agc_state.clear()
                full.Reset()
                wake.Reset()
                # ...and the barge listener, so half a word left over from
                # the sentence she just finished cannot interrupt the next
                # one. Its whole job is the few seconds she is speaking.
                barge.Reset()
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
                     on_progress=None) -> str | None:
    """Wait for the answer, saying anything she reports along the way.

    A long request used to be an acknowledgement and then silence until
    the results — minutes of it, with a compiled plan sitting unsaid.
    `on_progress` is called with each new line, in order, exactly once:
    she narrates by saying the NEW ones, not by re-reading the list.
    """
    import time as _time
    sleep = sleep or _time.sleep
    deadline = _time.monotonic() + wait_s
    spoken = 0
    heard_running = False
    while _time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{core_url}/api/voice/followup?id={followup_id}", timeout=5
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            # The supervised Core can restart while an answer is running. A
            # transient refused connection is not proof the answer vanished.
            sleep(poll_s)
            continue
        if on_progress:
            lines = list(payload.get("progress") or [])
            for line in lines[spoken:]:
                try:
                    on_progress(line)
                except Exception:
                    pass      # narration must never lose the answer
            spoken = max(spoken, len(lines))
        if payload.get("state") in ("READY", "FAILED"):
            return payload.get("say")
        if payload.get("state") == "EXPIRED":
            return None
        heard_running = True
        sleep(poll_s)
    # Out of patience while the Core still reports it running: say so, and do
    # not acknowledge - the answer has not been heard yet. A Core that never
    # answered at all proves nothing is coming, so that stays a failure.
    return FOLLOWUP_STILL_WORKING if heard_running else None


def acknowledge_followup(followup_id: str, core_url: str = CORE_URL) -> bool:
    """Tell the Core the answer was actually spoken. Never raises.

    Without this every answer the ROOM speaks stays an unread IMPORTANT
    notification for ever — 80 of them had piled up on his machine, so
    "what's waiting on me" read back her own replies as though they were
    work. The wall and the audit tool both did this; the room, the
    surface he actually uses, never did.

    A failure here must not take the room down: the answer has already
    been said, and the worst case is one stale notice rather than a
    listener that died doing bookkeeping.
    """
    try:
        request = urllib.request.Request(
            f"{core_url}/api/voice/followup/ack",
            data=json.dumps({"id": followup_id}).encode("utf-8"),
            headers=_local_headers(), method="POST")
        with urllib.request.urlopen(request, timeout=5):
            return True
    except Exception:
        return False


def launch_followup(followup_id: str, core_url: str, say,
                    collector=None, acknowledge=None) -> threading.Thread:
    """Collect one promised reply without making the room deaf meanwhile."""
    collector = collector or collect_followup
    acknowledge = acknowledge or acknowledge_followup

    # Does this collector narrate? A question with an answer, so it is
    # asked once rather than by calling and seeing what breaks: a
    # try/except TypeError would call a real collector twice when the
    # error came from inside it, and would let a crash escape the guard
    # below — which it did, and a test caught it.
    try:
        import inspect
        narrates = "on_progress" in inspect.signature(collector).parameters
    except (TypeError, ValueError):
        narrates = False

    def deliver():
        try:
            # `say` is the same mouth the answer comes out of, so a plan
            # and its results cannot arrive out of order.
            later = (collector(followup_id, core_url, on_progress=say)
                     if narrates else collector(followup_id, core_url))
        except Exception:
            later = None
        say(later or FOLLOWUP_FAILURE)
        # AFTER saying it, and only if there was something to say.
        # Acknowledging a failed collection would consume an answer
        # nobody heard — the exact loss the pure-read GET exists to
        # prevent.
        if later and later != FOLLOWUP_STILL_WORKING:
            acknowledge(followup_id, core_url)

    thread = threading.Thread(target=deliver, name=f"voice-{followup_id}",
                              daemon=True)
    thread.start()
    return thread


def _local_headers() -> dict:
    """The room listener is a process on the Core's own machine, and since
    2026-09-03 a local WRITE must prove that: 127.0.0.1 proves origin, not
    authorization (a stray local process could otherwise approve or halt).
    It reads the same per-machine secret the Core injects into the pages
    it serves. Found 2026-09-04, hours before first real use: every
    "Thea, ..." said in the room was being answered 401, because this
    request carried no secret at all."""
    headers = {"Content-Type": "application/json"}
    try:
        from aletheia import access
        secret = access.local_secret()
        if secret:
            headers["X-Aletheia-Local"] = secret
    except Exception:
        pass   # the Core will refuse and the failure will be visible, not silent
    return headers


def ask_core(transcript: str, core_url: str = CORE_URL) -> dict:
    req = urllib.request.Request(
        f"{core_url}/api/voice",
        data=json.dumps({"transcript": transcript}).encode("utf-8"),
        headers=_local_headers(), method="POST",
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


def _ask_with_acknowledgement(command: str, core_url: str, say,
                              monotonic=time.monotonic) -> dict:
    """Ask the Core, and say she is thinking if it takes a human moment.

    He described the missing thing precisely: "if I give you an answer, like,
    right away, you're doing stuff — even if it's just telling me that you
    have to think a little harder." Silence from something that is supposed
    to be listening is indistinguishable from silence from something that is
    broken, and every ask paid at least one ~3.6s model round trip.

    The trigger is ELAPSED TIME, not a guess about the sentence. A request
    the fast lane answers out of a file comes back in milliseconds and
    nothing is said; one that is genuinely thinking says so; one still going
    twelve seconds later says that too. There is no classifier to be wrong,
    and no case where she claims to be working on something she is not.

    A failure inside the acknowledgement must never cost him the answer, so
    the ask runs to completion regardless.
    """
    result: dict = {}
    done = threading.Event()

    def work():
        try:
            result.update(ask_core(f"thea {command}", core_url))
        except Exception as exc:
            result.update({"say": f"I couldn't reach my Core: {type(exc).__name__}",
                           "followup_id": None})
        finally:
            done.set()

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    # How long to stay quiet before saying she is on it. A question that
    # should land in four seconds gets longer silence than a job that is
    # about to take minutes — see ACK_AFTER_QUICK_S.
    try:
        from aletheia import asking
        ack_after = (ACK_AFTER_QUICK_S
                     if asking.expectation(command) == "quick"
                     else ACK_AFTER_S)
    except Exception:
        ack_after = ACK_AFTER_S
    started = monotonic()
    said_ack = said_still = False
    while not done.wait(ACK_WAIT_TICK_S):
        waited = monotonic() - started
        # Each line at most once. A voice that narrates its own waiting
        # every twelve seconds is worse than one that waits quietly.
        if not said_ack and waited >= ack_after:
            said_ack = True
            say(speech.ack_line(command))
        elif said_ack and not said_still and waited >= STILL_AFTER_S:
            said_still = True
            say(speech.ACK_STILL)
    return result or {"say": "done", "followup_id": None}


def listen_forever(recognizer=None, speaker=None, core_url: str = CORE_URL,
                   max_utterances: int | None = None, on_heard=None,
                   monotonic=time.monotonic) -> int:
    """Wake -> command, and only the speaking he has asked for.

    A bare wake word opens an eight-second follow-up window. If that expires,
    ordinary room speech is ignored again. Identical failure lines are also
    throttled briefly as a final guard against a provider/error feedback loop.

    It also says anything `announce` has pending before handling an utterance
    (§144, speaking first) — which is OPT-IN and off by default: with
    announcements disabled the store is not even read, so this line said
    "no unsolicited speech" for as long as he leaves it that way, and says
    what he turned on when he turns it on.
    """
    recognizer = recognizer if recognizer is not None else microphone_recognizer()
    speaker = speaker or speak
    handled = 0
    awaiting_since: float | None = None
    last_failure = ""
    last_failure_at = -1e9
    last_line = ""
    last_line_at = -1e9
    last_announced = -1e9
    followup_threads: list[threading.Thread] = []
    say_lock = threading.Lock()

    def say(line: str | None) -> None:
        nonlocal last_failure, last_failure_at, last_line, last_line_at
        with say_lock:
            if not line:
                return
            now = monotonic()
            normalized = " ".join(str(line).split())
            if (_is_failure_line(normalized) and normalized == last_failure
                    and now - last_failure_at < REPEAT_FAILURE_WINDOW_S):
                return
            if (normalized in ACK_LINES and normalized == last_line
                    and now - last_line_at < REPEAT_ACK_WINDOW_S):
                return
            speaker(normalized)
            last_line, last_line_at = normalized, now
            if _is_failure_line(normalized):
                last_failure, last_failure_at = normalized, now

    for wake_heard, text in recognizer:
        now = monotonic()
        # HE TALKED OVER HER, so the sentence he is in the middle of is
        # for her, whether or not it starts with her name. He already said
        # it once — to stop her — and making him say it again is the
        # machine winning an argument it should not be having.
        if take_interrupt():
            awaiting_since = now
        # SPEAKING FIRST (§144). The capability registry has claimed since it
        # was written that this loop says pending lines before handling an
        # utterance — and it did not: `announce` was imported by nothing but
        # its own tests while an AVAILABLE entry named this function as its
        # caller. Here is the caller.
        #
        # It is quiet by construction, not by hope: `announce.pending()`
        # returns nothing unless the feature is enabled, refuses during a
        # halt and during quiet hours, caps itself per hour, and never
        # repeats a notice it has already said. A failure here must never
        # cost him the room, so nothing raises out of it.
        if now - last_announced >= ANNOUNCE_EVERY_S:
            last_announced = now
            try:
                from aletheia import announce
                announce.speak_pending(speaker=say)
            except Exception as exc:
                try:
                    from aletheia import journal
                    journal.append("event", "voice-room",
                                   "could not speak pending lines "
                                   f"({type(exc).__name__})",
                                   actor="aletheia-voice-room")
                except Exception:
                    pass
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

        # SAY NOTHING RATHER THAN "I DIDN'T CATCH THAT". A fragment the
        # wake word picked up off the room — "the", "uh", "the injuries"
        # — used to go to the planner, wait most of a minute, and come
        # back with an apology she read out loud and filed as a
        # notification. His list had a dozen of them.
        #
        # Nothing the deterministic layer understands reaches this, so
        # "stop" is never silenced. It is journaled, so a silence is
        # explainable later, and it is not counted as a turn.
        if not voice.worth_answering(command):
            try:
                from aletheia import journal
                journal.append("event", "voice-room",
                               f"heard nothing worth answering: {command[:60]!r}",
                               actor="aletheia-voice-room")
            except Exception:
                pass
            continue

        answer = _ask_with_acknowledgement(command, core_url, say,
                                           monotonic=monotonic)
        reply = answer["say"]
        followup_id = answer.get("followup_id")
        say(reply)
        if followup_id:
            followup_threads = [t for t in followup_threads if t.is_alive()]
            followup_threads.append(launch_followup(followup_id, core_url, say))
        handled += 1
        if max_utterances is not None and handled >= max_utterances:
            # Test/one-shot callers get deterministic delivery; the real
            # forever-listener never blocks its ears on these joins.
            for thread in followup_threads:
                thread.join(timeout=1.0)
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
    # Always-on, launched at logon by its own scheduled task: same inheritance
    # hazard as the project loop. The room must never be the thing that opens
    # a visible ChatGPT conversation.
    from aletheia import browser_reasoner
    browser_reasoner.drop_lease()
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

    # CLOSED MEANS CLOSED, INCLUDING THE MICROPHONE. This task has its own
    # logon trigger, so without this check "close her" stopped the Core and
    # left the room listening — and the next trigger started a fresh
    # listener while she was supposed to be shut.
    from aletheia import closed
    if closed.is_closed():
        print("Aletheia is closed — not listening. "
              "`python -m aletheia.closed open` to change that.")
        return 0

    # AND OFF IS THE DEFAULT. His ruling, 2026-09-07: "i don't want an
    # always on microphone. And if I do want that, that'll be a button I
    # press within Aletheia once she's turned on."
    #
    # This task is logon-triggered with a five-minute watchdog, so
    # without this check a microphone in his room opened itself when he
    # signed in and reopened itself whenever it stopped. The task and the
    # watchdog stay — pressing the button should start listening in
    # seconds — but they start a process that opens nothing.
    from aletheia import ears
    if not ears.listening():
        print(ears.spoken())
        print("Turn it on with: python -m aletheia.ears on")
        return 0

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
        # ONE LINE, ONCE. Not an announcement — §144 is about speaking
        # UNPROMPTED, and this is the direct answer to a button he just
        # pressed. Without it the button produces silence, and silence is
        # indistinguishable from a microphone that did not start.
        try:
            speak("I'm listening.")
        except Exception:
            pass
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
