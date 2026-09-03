"""She writes the thing, instead of writing a description of the thing.

Found by running the sentence, 2026-09-03:

    "summarize my resume into three bullets and save it as summary.md"
      → file_write(path="summary.md",
                   text="Three-bullet summary of resume, generated from
                         the resume content retrieved above.")

That step was EXECUTABLE and validated clean, and it would have put that
exact sentence in his file. Not a summary — a note promising a summary.

The cause is structural, not a bad guess. The planner is a COMPILER: it
turns a sentence into named command slots, and `file_write(path, text)`
demands the finished text as an argument, at compile time, before
anything has been read. So a request to WRITE something has only two
outcomes available to it — a clarifying question, or a placeholder — and
which one it gets is luck. "Write me a short note about X and save it",
the most ordinary creative request there is, could not succeed.

`compose` moves the authoring to EXECUTION time, where the sources can
actually be read and a model can actually write. The planner says what
should exist and where; the prose is written when the step runs.

The boundaries are the ones that already exist, deliberately reused
rather than restated:

- It writes through `aletheia.workspace`, so it is inside her own
  directory, versioned on every overwrite, size-capped, and halted when
  she is halted. `compose` adds no reach.
- It reads sources through the same module's read half, which is wider
  than its write half on purpose, so "summarise my resume in Downloads"
  works and cannot damage the resume.
- It authors through `reasoner.subscription_text`, so it has the same two
  subscription paths as everything else and degrades honestly.

What it will not do: pretend. If the sources cannot be read, it says so
and writes nothing — a document composed from a file she failed to open
is exactly the placeholder this module exists to abolish.
"""
from __future__ import annotations

import argparse
import json
import sys

from aletheia import journal, reasoner, workspace

ACTOR = "aletheia-compose"

# The instruction, not the document. 400 was too tight the first time a
# real caller wrote a real brief (aletheia.applications: name the company,
# connect concrete work to what the posting asks, four paragraphs, and
# refuse rather than invent) — 500 characters of genuine guidance that
# silently produced NO letter at all. Still small enough that pasting a
# document in here is refused, which is what the cap is for.
MAX_WHAT_CHARS = 1_000
MAX_SOURCES = 3
# Budgeted against `brain.MAX_TEXT` (16,000) like every other prompt in the
# system: the instruction, the sources and the framing all have to fit, and
# a prompt that does not fit does not produce a worse document — it
# produces no document and an error that reads like the model is down.
MAX_SOURCE_CHARS = 9_000
MAX_OUTPUT_CHARS = 20_000
TIMEOUT_S = 180.0

SYSTEM = """You are writing a document for Caleb, who asked for it in one
sentence. Produce the DOCUMENT ITSELF and nothing else: no preamble, no
"here is the summary", no commentary about what you have written, no code
fence around the whole thing.

- Write what he asked for, at the length he asked for. Three bullets means
  three bullets.
- If source files travel with the request, work from what they actually
  say. Do not invent a fact that is not in them.
- Markdown is fine when it helps and unnecessary when it does not.
- If you genuinely cannot write it from what you were given, say so in one
  plain sentence, starting with the words CANNOT WRITE. That is the only
  case where your output is not the document."""

REFUSAL = "CANNOT WRITE"


class ComposeError(RuntimeError):
    pass


def _read_sources(sources: list[str]) -> tuple[list[dict], list[str]]:
    read, missing = [], []
    budget = MAX_SOURCE_CHARS
    for name in sources[:MAX_SOURCES]:
        try:
            got = workspace.read(name)
        except Exception:
            try:
                got = workspace.read(name, anywhere=True)
            except Exception as exc:
                missing.append(f"{name} ({exc})")
                continue
        text = str(got.get("text", ""))[:max(0, budget)]
        budget -= len(text)
        read.append({"name": name, "path": got.get("path", name), "text": text})
    return read, missing


def compose(what: str, path: str, *, sources: list[str] | None = None,
            why: str = "", think=None) -> dict:
    """Write a document and save it. Returns the workspace receipt."""
    what = " ".join(str(what or "").split())
    if not what:
        raise ValueError("say what to write")
    if len(what) > MAX_WHAT_CHARS:
        raise ValueError(f"the instruction must be under {MAX_WHAT_CHARS} characters")
    if not str(path or "").strip():
        raise ValueError("say where to save it")
    think = think or reasoner.subscription_text

    read, missing = _read_sources(list(sources or []))
    if missing and not read:
        # Every source failed. Composing anyway would produce exactly the
        # confident placeholder this module exists to abolish.
        raise ComposeError(
            "I could not read " + "; ".join(missing)
            + " — so there is nothing to write this from. Nothing was saved.")

    prompt = what
    for handle in read:
        prompt += (f"\n\n--- SOURCE: {handle['name']} (read from "
                   f"{handle['path']}) ---\n{handle['text']}")
    if missing:
        prompt += ("\n\n--- COULD NOT READ ---\n" + "\n".join(missing)
                   + "\nWrite from what you do have and do not invent the rest.")

    try:
        said = think(SYSTEM, prompt, timeout_s=TIMEOUT_S)
        provider = ""
        if isinstance(said, tuple) and len(said) == 2:
            said, provider = said
    except Exception as exc:
        why_failed = str(exc).strip() or type(exc).__name__
        raise ComposeError(f"I could not reach a model to write it: {why_failed}. "
                           "Nothing was saved.") from None

    body = str(said or "").strip()[:MAX_OUTPUT_CHARS]
    if not body:
        raise ComposeError("the model returned nothing; nothing was saved")
    if body.upper().startswith(REFUSAL):
        raise ComposeError(body[:400] + " Nothing was saved.")

    receipt = workspace.write(path, body, why=why or what[:100])
    journal.append("action", "compose",
                   f"wrote {receipt['path']} from {len(read)} source(s)"
                   + (f" via {provider}" if provider else ""), actor=ACTOR)
    receipt["composed_from"] = [handle["path"] for handle in read]
    receipt["unreadable"] = missing
    return receipt


def spoken(receipt: dict) -> str:
    where = str(receipt.get("path", "")).replace("\\", "/").rsplit("/", 1)[-1]
    said = (f"wrote {where} ({receipt.get('chars', 0):,} characters)"
            + ("" if receipt.get("created") else ", keeping the previous version"))
    if receipt.get("unreadable"):
        said += f" — could not read {len(receipt['unreadable'])} source(s)"
    return said


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write a document and save it.")
    ap.add_argument("what")
    ap.add_argument("path")
    ap.add_argument("--source", action="append", default=[])
    args = ap.parse_args(argv)
    try:
        print(json.dumps(compose(args.what, args.path, sources=args.source),
                         indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
