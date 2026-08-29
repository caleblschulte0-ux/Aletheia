"""Higher-quality local speech I/O for room voice.

This module is deliberately optional. Aletheia's Core stays stdlib-only and
room voice can still fall back to Vosk + Windows SAPI if these packages are not
installed. When explicitly set up on the operator's PC it adds:

* faster-whisper `base.en` for the command transcript after the local Vosk wake
  gate has already decided the utterance was addressed to Thea; and
* Piper neural TTS for the mouth, played locally through Windows winsound.

Neither provider has tools or authority. Audio remains local. Normal runtime
never installs packages or silently downloads a model; `setup_quality()` is an
explicit setup operation.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from aletheia.proc import run as proc_run

MODEL_ROOT = Path.home() / ".aletheia" / "models"
PIPER_DIR = MODEL_ROOT / "piper"
WHISPER_DIR = MODEL_ROOT / "whisper"
PIPER_VOICE = os.environ.get("ALETHEIA_PIPER_VOICE", "en_US-lessac-medium")
WHISPER_MODEL = os.environ.get("ALETHEIA_WHISPER_MODEL", "base.en")
MAX_UTTERANCE_SECONDS = 20
SAMPLE_RATE = 16_000

_whisper_model = None


def _piper_exe() -> str | None:
    return shutil.which("piper")


def _piper_paths(voice: str = PIPER_VOICE) -> tuple[Path, Path]:
    return PIPER_DIR / f"{voice}.onnx", PIPER_DIR / f"{voice}.onnx.json"


def piper_ready(voice: str = PIPER_VOICE) -> tuple[bool, str]:
    exe = _piper_exe()
    model, config = _piper_paths(voice)
    if not exe:
        return False, "piper-tts is not installed"
    if not model.is_file() or not config.is_file():
        return False, f"Piper voice {voice!r} is not downloaded"
    return True, f"Piper {voice}"


def whisper_ready(model: str = WHISPER_MODEL) -> tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as exc:
        return False, f"missing {exc.name}"
    marker = WHISPER_DIR / f"ready-{model.replace('/', '_')}.txt"
    if not marker.is_file():
        return False, f"Whisper model {model!r} is not prepared"
    return True, f"faster-whisper {model}"


def install_quality_packages() -> tuple[bool, str]:
    """Explicitly install the optional local speech packages.

    This is called only by an operator-invoked setup command, never by the
    always-on listener. A failed optional install leaves the old voice usable.
    """
    proc = proc_run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--prefer-binary",
         "piper-tts>=1.7,<2", "faster-whisper>=1.2,<2"],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "pip failed").strip()[-800:]
        return False, detail
    return True, "quality speech packages installed"


def ensure_piper_model(voice: str = PIPER_VOICE) -> tuple[bool, str]:
    exe = _piper_exe()
    if not exe:
        return False, "piper executable is not on PATH"
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    fd, wav_name = tempfile.mkstemp(prefix="aletheia-piper-setup-", suffix=".wav")
    os.close(fd)
    wav_path = Path(wav_name)
    try:
        proc = proc_run(
            [exe, "--model", voice, "--data-dir", str(PIPER_DIR),
             "--download-dir", str(PIPER_DIR), "--output_file", str(wav_path)],
            input="Voice ready.", capture_output=True, text=True, timeout=180,
        )
        ready, why = piper_ready(voice)
        if proc.returncode != 0 or not ready:
            detail = (proc.stderr or proc.stdout or why).strip()[-800:]
            return False, detail or why
        return True, why
    finally:
        try:
            wav_path.unlink()
        except OSError:
            pass


def _load_whisper(model: str = WHISPER_MODEL):
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        WHISPER_DIR.mkdir(parents=True, exist_ok=True)
        _whisper_model = WhisperModel(
            model, device="cpu", compute_type="int8", download_root=str(WHISPER_DIR)
        )
    return _whisper_model


def ensure_whisper_model(model: str = WHISPER_MODEL) -> tuple[bool, str]:
    try:
        _load_whisper(model)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    marker = WHISPER_DIR / f"ready-{model.replace('/', '_')}.txt"
    marker.write_text("prepared\n", encoding="utf-8")
    return True, f"faster-whisper {model}"


def setup_quality(*, install: bool = True) -> dict:
    """Prepare local neural speech, returning an honest structured result."""
    result = {"packages": None, "piper": None, "whisper": None}
    if install:
        ok, detail = install_quality_packages()
        result["packages"] = {"ok": ok, "detail": detail}
        if not ok:
            return result
    else:
        result["packages"] = {"ok": True, "detail": "package install skipped"}
    ok, detail = ensure_piper_model()
    result["piper"] = {"ok": ok, "detail": detail}
    ok, detail = ensure_whisper_model()
    result["whisper"] = {"ok": ok, "detail": detail}
    return result


def transcribe_pcm(pcm: bytes, *, model: str = WHISPER_MODEL,
                   sample_rate: int = SAMPLE_RATE) -> str | None:
    """Retranscribe one already wake-gated utterance with local Whisper.

    Returns None on any optional-provider failure so Vosk remains the honest
    fallback. The input is bounded before inference to keep a broken segmenter
    from turning one room-noise incident into unbounded work.
    """
    ready, _ = whisper_ready(model)
    if not ready or not pcm:
        return None
    max_bytes = MAX_UTTERANCE_SECONDS * sample_rate * 2
    pcm = pcm[:max_bytes]
    try:
        import numpy as np
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        whisper = _load_whisper(model)
        segments, _ = whisper.transcribe(
            audio, language="en", beam_size=1, vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(str(seg.text).strip() for seg in segments if str(seg.text).strip())
        return " ".join(text.split()) or None
    except Exception:
        return None


def piper_speak(text: str, *, voice: str = PIPER_VOICE, runner=proc_run,
                player=None) -> bool:
    """Speak through local Piper. Returns False without raising on fallback."""
    ready, _ = piper_ready(voice)
    if not ready or not str(text).strip():
        return False
    exe = _piper_exe()
    if not exe:
        return False
    if player is None:
        if os.name != "nt":
            return False
        import winsound
        player = lambda path: winsound.PlaySound(str(path), winsound.SND_FILENAME)
    fd, wav_name = tempfile.mkstemp(prefix="aletheia-say-", suffix=".wav")
    os.close(fd)
    wav_path = Path(wav_name)
    try:
        proc = runner(
            [exe, "--model", voice, "--data-dir", str(PIPER_DIR),
             "--download-dir", str(PIPER_DIR), "--output_file", str(wav_path)],
            input=str(text), capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size < 44:
            return False
        player(wav_path)
        return True
    except Exception:
        return False
    finally:
        try:
            wav_path.unlink()
        except OSError:
            pass
