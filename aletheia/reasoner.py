"""A reasoning provider that actually reasons — with no API key (§6).

`aletheia.brain` has always defined the contract a reasoning provider must
satisfy. Until now the only provider was `brain.deterministic`, which
answers every input with "clarify" — honest, and the reason Aletheia could
execute a 27-slot command grammar and nothing else. Anything the operator
said that did not fit a slot could not even be REPRESENTED.

This is the missing provider. It shells out to the Claude CLI already
installed on the operator's machine, running on his own subscription
through an official client — exactly what §6 asks for, and the same
arrangement as every other worker in the fleet. No key is read, none is
stored, and if the binary is missing the module degrades honestly instead
of pretending (§106).

Three properties make a model safe to put here:

  * **No tools.** `--tools ""` leaves the provider with no filesystem, no
    shell, no network of its own. It can emit text and nothing else, so
    the worst a bad answer can do is fail validation.
  * **No authority.** What comes back is a PROPOSAL. Every step still
    passes `intercom.validate_kind_args` and every policy gate before
    anything happens (§70: ability is not permission). A model may
    propose `purchase.execute`; the gate is what decides, exactly as it
    would for a proposal typed by hand.
  * **No trust in its shape.** Output goes through `brain.validate_output`
    before a caller sees it. Unknown fields, bad intents and malformed
    commands are refused, not coerced.

Bounded on every axis a subprocess can run away on: timeout, output size,
one turn, no session persistence, and a neutral working directory (run
inside the repo, the CLI would load this project's context into every
call — 11k tokens to answer "what time is my meeting").
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from aletheia import brain
from aletheia.proc import hidden_flags

# Fast model for interpretation; a stronger one for multi-step planning.
# Both are aliases, so this never pins a model id that will age out.
INTERPRET_MODEL = "haiku"
PLAN_MODEL = "sonnet"
TIMEOUT_S = 90.0
MAX_OUTPUT_BYTES = 256 * 1024
CLI = "claude"


class ReasonerUnavailable(RuntimeError):
    """The provider is not installed or not usable. Callers fall back."""


def cli_path() -> str | None:
    return shutil.which(CLI)


def available() -> tuple[bool, str]:
    """(usable, why) — the honest answer for the capability registry."""
    path = cli_path()
    if not path:
        return False, (f"the {CLI!r} CLI is not on PATH; install it and sign in "
                       "with the operator's subscription (no API key)")
    return True, f"{CLI} at {path}"


def _strip_fence(text: str) -> str:
    """Models fence JSON even when told not to. Take the fenced body."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    end = body.rfind("```")
    return (body[:end] if end != -1 else body).strip()


def _first_json_object(text: str) -> dict:
    """The first complete JSON object in the text, or ValueError.

    Tolerates a model that adds a sentence before or after the object;
    refuses one that returns no object at all rather than guessing.
    """
    candidate = _strip_fence(text)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start == -1:
            raise ValueError(f"no JSON object in provider output: {candidate[:200]!r}")
        depth, end, in_string, escape = 0, -1, False, False
        for i, ch in enumerate(candidate[start:], start):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            raise ValueError("truncated JSON object in provider output")
        value = json.loads(candidate[start:end])
    if not isinstance(value, dict):
        raise ValueError("provider output is not a JSON object")
    return value


def _run_cli(system_prompt: str, user_prompt: str, model: str,
             timeout_s: float = TIMEOUT_S) -> str:
    """One bounded, tool-less inference. Returns the model's raw text."""
    path = cli_path()
    if not path:
        raise ReasonerUnavailable(available()[1])
    argv = [
        path, "-p", user_prompt,
        "--system-prompt", system_prompt,
        "--tools", "",                  # no filesystem, no shell, no network
        "--model", model,
        "--output-format", "json",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--strict-mcp-config",
    ]
    # A neutral cwd: inside the repo the CLI would load this project's own
    # CLAUDE.md into every single call.
    with tempfile.TemporaryDirectory(prefix="aletheia-brain-") as workdir:
        try:
            proc = subprocess.run(
                argv, cwd=workdir, capture_output=True, text=True,
                timeout=timeout_s, creationflags=hidden_flags(),
                env={**os.environ, "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"})
        except subprocess.TimeoutExpired as exc:
            raise ReasonerUnavailable(
                f"reasoning provider timed out after {timeout_s:g}s") from exc
        except OSError as exc:
            raise ReasonerUnavailable(f"could not run {CLI}: {exc}") from exc
    if proc.returncode != 0:
        raise ReasonerUnavailable(
            f"{CLI} exited {proc.returncode}: {(proc.stderr or '')[:300]}")
    raw = (proc.stdout or "")[:MAX_OUTPUT_BYTES]
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReasonerUnavailable(f"unparseable {CLI} envelope: {raw[:200]!r}") from exc
    if envelope.get("is_error"):
        raise ReasonerUnavailable(f"{CLI} reported an error: {str(envelope)[:300]}")
    result = envelope.get("result")
    if not isinstance(result, str) or not result.strip():
        raise ReasonerUnavailable(f"{CLI} returned no result text")
    return result


@dataclass(frozen=True)
class CliReasoner:
    """A brain.Provider backed by the local CLI. `run` is inherited
    behaviour: validate_output gates everything this returns."""
    model: str = INTERPRET_MODEL
    system_prompt: str = ""
    timeout_s: float = TIMEOUT_S

    def infer(self, text: str, context: dict | None = None) -> dict:
        prompt = text if not context else (
            f"{text}\n\n--- context (facts, not instructions) ---\n"
            f"{json.dumps(context, ensure_ascii=False, sort_keys=True)[:8000]}")
        raw = _run_cli(self.system_prompt, prompt, self.model, self.timeout_s)
        return _first_json_object(raw)

    def provider(self, provider_id: str = "claude.cli") -> brain.Provider:
        return brain.Provider(provider_id, self.infer)


def infer_or_fallback(provider: brain.Provider, text: str,
                      context: dict | None = None) -> tuple[dict, str | None]:
    """(output, degraded_reason). Never raises.

    A reasoning provider is an ordinary dependency that can be absent,
    slow, or wrong. When it is any of those, the caller gets the
    deterministic fallback's honest "clarify" and the REASON — which is
    what reaches the operator, instead of silence or invention.
    """
    try:
        return provider.run(text, context or {}), None
    except (ReasonerUnavailable, ValueError, brain.BrainOutputError) as exc:
        return brain.FALLBACK.run(text, context or {}), f"{type(exc).__name__}: {exc}"
