"""Edit video and audio — trim, join, caption, convert, extract.

The last genuine zero. "I need you to edit this video" had no capability
behind it at all, not even a ticket: the registry did not mention media,
and nothing in the repo could open a video file.

This is ffmpeg, driven honestly. Three decisions worth stating:

**It never overwrites the source.** Every operation writes a NEW file in
the workspace and leaves the original exactly where it was. Video work is
where "she got it wrong" is most expensive — a re-encode is lossy and an
overwritten master is gone — so the source is read-only, always, and
there is no flag that changes that.

**It reports absence honestly.** ffmpeg is not a Python package and
cannot be pip-installed into place, so `available()` returns
`(False, why)` with the install line rather than raising, and every
caller degrades instead of pretending. That is the same contract
`sealed_observe` and `browse` use.

**It refuses what it cannot verify.** ffmpeg's own exit code is the
receipt, and a run that exits non-zero raises with the tail of stderr
rather than reporting a file that is not there. An output file that does
not exist afterwards is a failure even when ffmpeg said nothing — §30,
"command executed" is not "goal achieved".

The operations are the ones people actually ask for — cut a clip, stick
clips together, pull the audio out, burn in subtitles, make it smaller,
change the format — not a general shell. `run()` builds argument LISTS
and never a shell string, so a filename with a quote in it is a filename,
not an injection.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from aletheia import journal, policy, proc, workspace

ACTOR = "aletheia-media"

TIMEOUT_S = 1_800          # half an hour: a long export, not a hung process
MAX_INPUT_BYTES = 4_000_000_000
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass"}
MEDIA_SUFFIXES = VIDEO_SUFFIXES | AUDIO_SUFFIXES


class MediaError(RuntimeError):
    pass


def available() -> tuple[bool, str]:
    """Honest probe. ffmpeg is a program, not a package — it cannot be
    installed from inside a run, so absence is reported, never raised."""
    if not shutil.which("ffmpeg"):
        return False, ("ffmpeg is not installed. On Windows: "
                       "`winget install Gyan.FFmpeg`, then open a new terminal.")
    if not shutil.which("ffprobe"):
        return False, ("ffprobe is missing (it ships with ffmpeg) — reinstall "
                       "ffmpeg so both are on PATH.")
    return True, "ffmpeg and ffprobe are on PATH"


def _require() -> None:
    ok, why = available()
    if not ok:
        raise MediaError(why)


def _source(path: str) -> Path:
    """A file to read. Sources may live anywhere he names — reading cannot
    hurt them — but they must exist and be a media file."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = workspace.resolve(path)
    target = target.resolve()
    if not target.is_file():
        raise MediaError(f"{path} is not a file")
    if target.suffix.casefold() not in MEDIA_SUFFIXES | SUBTITLE_SUFFIXES:
        raise MediaError(f"{target.suffix or 'that'} is not a media file she "
                         "can work with")
    if target.stat().st_size > MAX_INPUT_BYTES:
        raise MediaError(f"{target.name} is larger than the input ceiling")
    return target


def _destination(path: str) -> Path:
    """Output ALWAYS lands in the workspace, and never on top of a source.

    A re-encode is lossy and an overwritten master is gone, so the source
    is read-only with no flag that changes it.
    """
    out = workspace.resolve(path)
    if out.suffix.casefold() not in MEDIA_SUFFIXES:
        raise MediaError(f"{out.suffix or 'that'} is not a media output format")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def run(args: list[str], *, what: str) -> dict:
    """One ffmpeg invocation. Argument LIST, never a shell string — a
    filename containing a quote is a filename, not an injection."""
    _require()
    policy.ensure_not_halted()
    command = ["ffmpeg", "-nostdin", "-y", *args]
    try:
        completed = proc.run(command, capture_output=True, text=True,
                             timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise MediaError(f"{what} ran past {TIMEOUT_S}s and was stopped") from None
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-6:]
        raise MediaError(f"{what} failed: " + " / ".join(tail)[:600])
    return {"ok": True, "what": what}


def probe(path: str) -> dict:
    """What a file actually IS — duration, streams, size. Read-only."""
    _require()
    source = _source(path)
    completed = proc.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(source)],
        capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        raise MediaError(f"could not read {source.name}: "
                         f"{(completed.stderr or '').strip()[:300]}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise MediaError(f"ffprobe returned nothing readable for {source.name}") from None
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    return {
        "path": str(source),
        "seconds": float(fmt.get("duration", 0) or 0),
        "bytes": int(fmt.get("size", 0) or 0),
        "video": [s.get("codec_name") for s in streams if s.get("codec_type") == "video"],
        "audio": [s.get("codec_name") for s in streams if s.get("codec_type") == "audio"],
    }


def _finish(out: Path, what: str) -> dict:
    """ffmpeg's exit code is not enough: an output that does not exist is a
    failure even when nothing complained (§30)."""
    if not out.is_file() or out.stat().st_size == 0:
        raise MediaError(f"{what} reported success but produced no file — "
                         "treating that as the failure it is")
    journal.append("action", "media", f"{what} -> {out.name} "
                   f"({out.stat().st_size:,} bytes)", actor=ACTOR)
    return {"path": str(out), "bytes": out.stat().st_size, "what": what}


def trim(source: str, out: str, *, start: str = "0", end: str | None = None,
         duration: str | None = None) -> dict:
    """Cut a clip. Times are ffmpeg's own (`12`, `1:05`, `00:01:05.5`)."""
    src, dst = _source(source), _destination(out)
    if end and duration:
        raise MediaError("give an end or a duration, not both")
    args = ["-ss", str(start), "-i", str(src)]
    if end:
        args += ["-to", str(end)]
    elif duration:
        args += ["-t", str(duration)]
    # Re-encode rather than stream-copy: a copy cuts only on keyframes, so
    # "start at 1:05" silently becomes "start at 1:03" and the clip is
    # wrong in a way nobody notices until it matters.
    args += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
    run(args, what=f"trim {src.name}")
    return _finish(dst, "trim")


def join(sources: list[str], out: str) -> dict:
    """Stick clips together, in the order given."""
    if not isinstance(sources, list) or len(sources) < 2:
        raise MediaError("joining needs at least two files")
    paths = [_source(s) for s in sources]
    dst = _destination(out)
    listing = dst.parent / f".{dst.stem}-inputs.txt"
    # ffmpeg's concat list quotes with single quotes and escapes its own.
    listing.write_text(
        "".join(f"file '{str(p).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
                for p in paths), encoding="utf-8")
    try:
        run(["-f", "concat", "-safe", "0", "-i", str(listing),
             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)],
            what=f"join {len(paths)} files")
    finally:
        listing.unlink(missing_ok=True)
    return _finish(dst, "join")


def extract_audio(source: str, out: str) -> dict:
    """Pull the sound out — for a transcript, or to keep just the audio."""
    src, dst = _source(source), _destination(out)
    if dst.suffix.casefold() not in AUDIO_SUFFIXES:
        raise MediaError("the output of extracting audio must be an audio file")
    run(["-i", str(src), "-vn", str(dst)], what=f"extract audio from {src.name}")
    return _finish(dst, "extract_audio")


def burn_subtitles(source: str, subtitles: str, out: str) -> dict:
    """Burn captions into the picture, so they survive re-uploads."""
    src, dst = _source(source), _destination(out)
    subs = _source(subtitles)
    if subs.suffix.casefold() not in SUBTITLE_SUFFIXES:
        raise MediaError("subtitles must be .srt, .vtt or .ass")
    # ffmpeg's filter grammar treats ':' and '\' specially inside the
    # subtitles= argument, and Windows paths are full of both.
    escaped = str(subs).replace("\\", "/").replace(":", "\\:")
    run(["-i", str(src), "-vf", f"subtitles='{escaped}'",
         "-c:a", "copy", str(dst)], what=f"burn subtitles into {src.name}")
    return _finish(dst, "burn_subtitles")


def convert(source: str, out: str, *, height: int | None = None) -> dict:
    """Change format, and optionally make it smaller."""
    src, dst = _source(source), _destination(out)
    args = ["-i", str(src)]
    if height is not None:
        if type(height) is not int or not 120 <= height <= 4320:
            raise MediaError("height must be a whole number of pixels, 120..4320")
        args += ["-vf", f"scale=-2:{height}"]   # -2 keeps the aspect ratio even
    args.append(str(dst))
    run(args, what=f"convert {src.name}")
    return _finish(dst, "convert")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Edit video and audio.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="is ffmpeg installed?")
    p_probe = sub.add_parser("probe"); p_probe.add_argument("source")
    p_trim = sub.add_parser("trim")
    p_trim.add_argument("source"); p_trim.add_argument("out")
    p_trim.add_argument("--start", default="0")
    p_trim.add_argument("--end"); p_trim.add_argument("--duration")
    p_join = sub.add_parser("join")
    p_join.add_argument("out"); p_join.add_argument("sources", nargs="+")
    p_aud = sub.add_parser("audio")
    p_aud.add_argument("source"); p_aud.add_argument("out")
    p_subs = sub.add_parser("subtitles")
    p_subs.add_argument("source"); p_subs.add_argument("subtitles")
    p_subs.add_argument("out")
    p_conv = sub.add_parser("convert")
    p_conv.add_argument("source"); p_conv.add_argument("out")
    p_conv.add_argument("--height", type=int)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            ok, why = available()
            print(why)
            return 0 if ok else 1
        if args.cmd == "probe":
            print(json.dumps(probe(args.source), indent=2))
        elif args.cmd == "trim":
            print(json.dumps(trim(args.source, args.out, start=args.start,
                                  end=args.end, duration=args.duration), indent=2))
        elif args.cmd == "join":
            print(json.dumps(join(args.sources, args.out), indent=2))
        elif args.cmd == "audio":
            print(json.dumps(extract_audio(args.source, args.out), indent=2))
        elif args.cmd == "subtitles":
            print(json.dumps(burn_subtitles(args.source, args.subtitles, args.out),
                             indent=2))
        else:
            print(json.dumps(convert(args.source, args.out, height=args.height),
                             indent=2))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
