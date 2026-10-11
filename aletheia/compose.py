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
import re
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
# Her own model reads a far smaller prompt than a subscription does (a 4,096-token window on his
# laptop), so when it is the one writing, the sources are cut to fit it.
LOCAL_SOURCE_CHARS = 2_500
LOCAL_TIMEOUT_S = 300.0
LOCAL_NOTE = "Written with my own model because Claude and ChatGPT were out."

SYSTEM = """You are writing a document for Caleb, who asked for it in one
sentence. Produce the DOCUMENT ITSELF and nothing else: no preamble, no
"here is the summary", no commentary about what you have written, no code
fence around the whole thing.

- Write what he asked for, at the length he asked for. Three bullets means
  three bullets.
- If source files travel with the request, work from what they actually
  say. Do not invent a fact that is not in them.
- Markdown is fine when it helps and unnecessary when it does not.
- If the sources cover only part of what he asked for, write the part they
  support and say plainly, in the document, what is still missing. Partial
  and honest is the document; never refuse for want of the rest.
- If you genuinely cannot write any of it from what you were given, say so
  in one plain sentence, starting with the words CANNOT WRITE. That is the
  only case where your output is not the document."""

REFUSAL = "CANNOT WRITE"
#: A refusal whose reason is that the sources cover only PART of it - the case SYSTEM says to write.
PARTIAL = re.compile(r"\b(?:partial|partly|incomplete|only (?:some|part|a few|limited)|limited|missing|"
                     r"not (?:all|every|complete|enough))\b", re.I)
PARTIAL_NUDGE = ("The sources below are partial, and that is expected. Write the document from what they "
                 "do say, and say plainly in it what is still missing. Do not answer CANNOT WRITE because "
                 "the sources are partial.")


def small_or(read: list[dict], sources) -> list[dict]:
    """The sources cut to fit her own model, as the first ask had them."""
    small, _ = _read_sources(list(sources or []), LOCAL_SOURCE_CHARS)
    return small or read


class ComposeError(RuntimeError):
    pass


def _read_sources(sources: list[str], budget: int = MAX_SOURCE_CHARS) -> tuple[list[dict], list[str]]:
    read, missing = [], []
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

    read, missing = _read_sources(list(sources or []))
    if missing and not read:
        # Every source failed. Composing anyway would produce exactly the
        # confident placeholder this module exists to abolish.
        raise ComposeError(
            "I could not read " + "; ".join(missing)
            + " — so there is nothing to write this from. Nothing was saved.")

    try:
        said, provider = _ask(think or reasoner.subscription_text, _prompt(what, read, missing), TIMEOUT_S)
    except Exception as exc:
        why_failed = str(exc).strip() or type(exc).__name__
        if think is not None or not isinstance(exc, reasoner.ReasonerUnavailable):
            raise ComposeError(f"I could not reach a model to write it: {why_failed}. "
                               "Nothing was saved.") from None
        # Claude and ChatGPT are both out: her own model writes it, from sources cut to fit it,
        # and the receipt says whose words they are (2026-10-11: every document of the move
        # plan failed while the subscriptions rested).
        small, _ = _read_sources(list(sources or []), LOCAL_SOURCE_CHARS)
        try:
            said, provider = _ask(reasoner.local_text, _prompt(what, small, missing), LOCAL_TIMEOUT_S)
        except Exception as local_exc:
            raise ComposeError(f"I could not reach a model to write it: {why_failed}; and "
                               f"{str(local_exc).strip() or type(local_exc).__name__}. "
                               "Nothing was saved.") from None

    body = str(said or "").strip()[:MAX_OUTPUT_CHARS]
    if body.upper().startswith(REFUSAL) and read and PARTIAL.search(body):
        # "CANNOT WRITE: the sources found only partial figures" is the case the prompt says to
        # write: her own model refused the comparison three runs running for exactly that (his PC,
        # 2026-10-11). Asked once more, plainly, with its own reason in front of it.
        local = str(provider or "").startswith("ollama:")
        again = (f"{PARTIAL_NUDGE}\n\nYou answered: {body[:300]}\n\n"
                 + _prompt(what, small_or(read, sources) if local else read, missing))
        try:
            said, provider = _ask(think or (reasoner.local_text if local else reasoner.subscription_text),
                                  again, LOCAL_TIMEOUT_S if local else TIMEOUT_S)
            body = str(said or "").strip()[:MAX_OUTPUT_CHARS]
        except Exception:  # noqa: BLE001 - the first refusal stands, said as it was
            pass
    if not body:
        raise ComposeError("the model returned nothing; nothing was saved")
    if body.upper().startswith(REFUSAL):
        raise ComposeError(body[:400] + " Nothing was saved.")
    if provider.startswith("ollama:"):
        # A document he trusts as Claude's and is not is the failure he cannot detect.
        body += "\n\n_" + LOCAL_NOTE + "_"

    receipt = workspace.write(path, body, why=why or what[:100])
    journal.append("action", "compose",
                   f"wrote {receipt['path']} from {len(read)} source(s)"
                   + (f" via {provider}" if provider else ""), actor=ACTOR)
    receipt["composed_from"] = [handle["path"] for handle in read]
    receipt["unreadable"] = missing
    receipt["drafted_by"] = provider
    return receipt


def _prompt(what: str, read: list[dict], missing: list[str]) -> str:
    prompt = what
    for handle in read:
        prompt += (f"\n\n--- SOURCE: {handle['name']} (read from "
                   f"{handle['path']}) ---\n{handle['text']}")
    if missing:
        prompt += ("\n\n--- COULD NOT READ ---\n" + "\n".join(missing)
                   + "\nWrite from what you do have and do not invent the rest.")
    return prompt


def _ask(think, prompt: str, timeout_s: float) -> tuple[str, str]:
    said = think(SYSTEM, prompt, timeout_s=timeout_s)
    if isinstance(said, tuple) and len(said) == 2:
        return said[0], str(said[1] or "")
    return said, ""


def spoken(receipt: dict) -> str:
    where = str(receipt.get("path", "")).replace("\\", "/").rsplit("/", 1)[-1]
    said = (f"wrote {where} ({receipt.get('chars', 0):,} characters)"
            + ("" if receipt.get("created") else ", keeping the previous version"))
    if receipt.get("unreadable"):
        said += f" — could not read {len(receipt['unreadable'])} source(s)"
    if str(receipt.get("drafted_by") or "").startswith("ollama:"):
        said += ", written with my own model because Claude and ChatGPT are out"
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
