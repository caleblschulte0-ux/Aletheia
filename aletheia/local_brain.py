"""Loopback-only JSON reasoning adapter for local Ollama models.

This layer has zero execution authority.  It accepts a caller-owned system
prompt/context and returns one JSON object; the caller still owns schema
validation and every Aletheia policy/action gate.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_S = 45.0
#: The hard ceiling on ONE call, whoever is asking. It is not a budget: the
#: budget is chosen per class of work in `work_states.LOCAL_CEILING_S` (300 s
#: attended, 1200 s background) and nothing gets the long one by default. This
#: is only the point past which a single local call is a hung process rather
#: than a slow answer. 1800 s = 30 minutes; it was 300 s, which made his
#: 2026-09-18 ruling ("like a while") inexpressible.
MAX_TIMEOUT_S = 1_800.0
#: How long Ollama keeps the model in memory after a call, by what the work is.
#: Measured on this laptop 2026-09-18: a cold load of qwen3:8b costs about
#: 25 s and a warm call about 2.4 s, so with the old single "30s" every
#: sentence he said more than half a minute after the last one paid the load
#: again - the largest single cost in her own model's latency, and not a
#: thinking cost at all. A conversation is about to get another sentence, so it
#: stays warm; a background draft that has just finished has nobody waiting on
#: it, so it lets the memory go (his laptop is 16 GB and his job loop shares it).
ATTENDED_KEEP_ALIVE = "5m"
BACKGROUND_KEEP_ALIVE = "30s"
DEFAULT_KEEP_ALIVE = ATTENDED_KEEP_ALIVE
#: A streamed call looks at `should_yield` no less often than this.
YIELD_CHECK_S = 0.5
MAX_RESPONSE_BYTES = 512 * 1024
MAX_CONTEXT_BYTES = 16 * 1024
MAX_PROMPT_CHARS = 24_000

#: A MODEL THAT NEVER SAW THE QUESTION. Ollama loads qwen3:8b with a 4096 token
#: window by default and silently DROPS whatever does not fit, oldest first -
#: which is the system prompt, the rules and the safety instructions. Nothing
#: errors; the answer just comes back having been asked something else. This
#: layer will happily build a 24,000 character prompt on top of 16 KB of
#: context, so it has to say how big a window it needs.
#:
#: Measured 2026-09-18 on his laptop, the same prompt each time: 4096 took
#: 90.1 s and held 5.94 GB, 16384 took 89.5 s and held 7.89 GB. So a bigger
#: window costs MEMORY and not time - which is why it is asked for by size
#: rather than taken always: a conversational prompt keeps the small, cheap
#: runner (and never pays a reload for a window it does not need).
CONTEXT_WINDOWS = (4096, 8192, 16384)
#: Conservative for English prose with JSON in it; under-estimating tokens per
#: character is what silently truncates.
CHARS_PER_TOKEN = 3.0
#: Room for the reply, which shares the window.
WINDOW_HEADROOM_TOKENS = 1_024


def window_for(chars: int) -> int:
    """The smallest context window that holds a prompt this long, with room to
    answer. The largest is a cap, not a promise: past it, Ollama truncates and
    the caller's own context bounds are what keep that from happening."""
    need = int(max(0, chars) / CHARS_PER_TOKEN) + WINDOW_HEADROOM_TOKENS
    for window in CONTEXT_WINDOWS:
        if need <= window:
            return window
    return CONTEXT_WINDOWS[-1]


class LocalBrainError(RuntimeError):
    pass


class LocalBrainUnavailable(LocalBrainError):
    pass


class LocalBrainProtocolError(LocalBrainError):
    pass


class LocalBrainYielded(LocalBrainUnavailable):
    """Background work gave the one Ollama queue back to a waiting conversation.

    Not a failure of the work: it is the same "try again shortly" as
    `local_lease.LeaseBusy`, raised from inside a call that was already running
    when he started talking."""


@dataclass(frozen=True)
class OllamaConfig:
    model: str
    think: bool = False
    timeout_s: float = DEFAULT_TIMEOUT_S
    base_url: str = DEFAULT_BASE_URL
    #: "" means the machine-local setting, then DEFAULT_KEEP_ALIVE.
    keep_alive: str = ""

    @classmethod
    def for_model(cls, model: str, *, think: bool = False, timeout_s: float | None = None,
                  keep_alive: str = ""):
        raw = os.environ.get("ALETHEIA_LOCAL_AI_TIMEOUT", "").strip()
        default_timeout = timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
        if raw:
            try:
                configured_timeout = float(raw)
            except ValueError as exc:
                raise ValueError("ALETHEIA_LOCAL_AI_TIMEOUT must be numeric") from exc
            # A machine-local preference may shorten a route, but it cannot
            # stretch a caller-owned latency budget.
            default_timeout = (
                min(default_timeout, configured_timeout)
                if timeout_s is not None else configured_timeout
            )
        return cls(
            model=model,
            think=bool(think),
            timeout_s=float(default_timeout),
            base_url=os.environ.get("ALETHEIA_LOCAL_AI_URL", DEFAULT_BASE_URL),
            keep_alive=str(keep_alive or ""),
        ).validated()

    def validated(self):
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.username or parsed.password:
            raise ValueError("local AI URL must be plain HTTP loopback")
        if (parsed.hostname or "").casefold() not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("local AI URL must be loopback-only")
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("local AI URL must be a plain loopback base URL")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 200:
            raise ValueError("local AI model name must be non-empty and bounded")
        if not 0.5 <= float(self.timeout_s) <= MAX_TIMEOUT_S:
            raise ValueError(f"local AI timeout must be 0.5..{MAX_TIMEOUT_S:.0f} seconds")
        return self


def _context_json(context: dict) -> str:
    try:
        raw = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("local reasoning context must be JSON-serializable") from exc
    if len(raw.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError(f"local reasoning context exceeds {MAX_CONTEXT_BYTES} bytes")
    return raw


def _first_json_object(text: str) -> dict:
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
        if "```" in candidate:
            candidate = candidate.rsplit("```", 1)[0]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            raise LocalBrainProtocolError("local model returned no JSON object") from None
        depth = 0
        in_string = False
        escape = False
        end = None
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
        if end is None:
            raise LocalBrainProtocolError("local model returned truncated JSON") from None
        try:
            value = json.loads(candidate[start:end])
        except json.JSONDecodeError:
            raise LocalBrainProtocolError("local model returned invalid JSON") from None
    if not isinstance(value, dict):
        raise LocalBrainProtocolError("local model output must be a JSON object")
    return value


def _read_json(response) -> dict[str, Any]:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise LocalBrainProtocolError("local AI response exceeded size limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LocalBrainProtocolError("Ollama returned invalid protocol JSON") from None
    if not isinstance(value, dict):
        raise LocalBrainProtocolError("Ollama response must be an object")
    return value


def _runtime_limits(want: str = "") -> tuple[int, str]:
    """Keep local inference useful without letting it monopolize the laptop."""
    logical_cpus = max(1, os.cpu_count() or 1)
    # HALF THE MACHINE, not a quarter. Measured 2026-09-18 on his 8-thread
    # laptop, the same prompt each time: 2 threads 106.7 s, 4 threads 87.3 s,
    # 6 threads 87.3 s. Four is where it stops helping - past that it is
    # waiting on memory, not on cores - so this takes the whole of the win and
    # still leaves half the machine to him and to his job loop.
    default_threads = max(1, logical_cpus // 2)
    raw_threads = os.environ.get("ALETHEIA_LOCAL_AI_THREADS", "").strip()
    if raw_threads:
        try:
            threads = int(raw_threads)
        except ValueError as exc:
            raise ValueError("ALETHEIA_LOCAL_AI_THREADS must be an integer") from exc
        if not 1 <= threads <= logical_cpus:
            raise ValueError(
                f"ALETHEIA_LOCAL_AI_THREADS must be between 1 and {logical_cpus}"
            )
    else:
        threads = default_threads

    # A machine-local setting wins over the caller's class: it is the operator
    # saying what his memory can afford, which is not something a caller knows.
    keep_alive = (os.environ.get("ALETHEIA_LOCAL_AI_KEEP_ALIVE", "").strip()
                  or str(want or "").strip() or DEFAULT_KEEP_ALIVE)
    if len(keep_alive) > 32 or any(ch in keep_alive for ch in "\r\n\x00"):
        raise ValueError("ALETHEIA_LOCAL_AI_KEEP_ALIVE must be a short duration")
    return threads, keep_alive


def request_json(config: OllamaConfig, path: str, payload: dict | None = None) -> dict[str, Any]:
    config.validated()
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        config.base_url.rstrip("/") + path,
        data=data,
        method="GET" if payload is None else "POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_s) as response:
            return _read_json(response)
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
        raise LocalBrainUnavailable(f"local Ollama unavailable ({type(exc).__name__})") from None


def build_payload(system_prompt: str, text: str, context: dict, config: OllamaConfig) -> dict:
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ValueError("local system prompt is required")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROMPT_CHARS:
        raise ValueError("local reasoning text must be non-empty and bounded")
    ctx = _context_json(context)
    threads, keep_alive = _runtime_limits(config.keep_alive)
    return {
        "model": config.model,
        "stream": False,
        "think": config.think,
        "format": "json",
        "keep_alive": keep_alive,
        "options": {"temperature": 0, "num_thread": threads,
                    "num_ctx": window_for(len(system_prompt) + len(text) + len(ctx))},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text + ("\n\n--- UNTRUSTED CONTEXT JSON ---\n" + ctx if context else "")},
        ],
    }


def _stream_chat(config: OllamaConfig, payload: dict, should_yield) -> dict[str, Any]:
    """One chat call whose generation can be STOPPED partway through.

    Ollama has one queue on this laptop, so a twenty-minute background draft
    would sit in front of every sentence he says unless the draft can be put
    down. It can only be put down at a checkpoint, and a non-streamed call has
    none: it blocks in one read until the answer is finished. Streaming makes
    every chunk a checkpoint. The reader runs in a daemon thread and the
    checkpoint runs here, so the prompt-evaluation phase - which on a CPU can be
    a minute before the first token - is interruptible too. Closing the response
    cancels the generation at Ollama's end rather than leaving it running.

    Returns the same {"message": {...}} shape as the non-streamed call.
    """
    import queue as _queue
    import threading

    data = json.dumps({**payload, "stream": True}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        config.base_url.rstrip("/") + "/api/chat", data=data, method="POST",
        headers={"Accept": "application/x-ndjson", "Content-Type": "application/json"},
    )
    lines: _queue.Queue = _queue.Queue()
    holder: dict[str, Any] = {}
    read_bytes = 0

    def read() -> None:
        try:
            with urllib.request.urlopen(req, timeout=config.timeout_s) as response:
                holder["response"] = response
                for raw in response:
                    lines.put(raw)
        except BaseException as exc:  # noqa: BLE001 - reported through the queue
            holder["error"] = exc
        finally:
            lines.put(None)

    worker = threading.Thread(target=read, name="aletheia-local-stream", daemon=True)
    worker.start()
    deadline = time.monotonic() + float(config.timeout_s)
    content: list[str] = []
    thinking: list[str] = []
    error: str | None = None

    def close() -> None:
        response = holder.get("response")
        if response is not None:
            try:
                response.close()
            except Exception:  # noqa: BLE001
                pass

    while True:
        if should_yield():
            close()
            raise LocalBrainYielded("her own model stopped to answer the conversation")
        if time.monotonic() > deadline:
            close()
            raise LocalBrainUnavailable("local Ollama unavailable (TimeoutError)")
        try:
            raw = lines.get(timeout=YIELD_CHECK_S)
        except _queue.Empty:
            continue
        if raw is None:
            break
        read_bytes += len(raw)
        if read_bytes > MAX_RESPONSE_BYTES:
            close()
            raise LocalBrainProtocolError("local AI response exceeded size limit")
        try:
            chunk = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(chunk, dict):
            continue
        if isinstance(chunk.get("error"), str) and chunk["error"]:
            error = chunk["error"]
        message = chunk.get("message")
        if isinstance(message, dict):
            if isinstance(message.get("content"), str):
                content.append(message["content"])
            if isinstance(message.get("thinking"), str):
                thinking.append(message["thinking"])
    exc = holder.get("error")
    if exc is not None and not (content or thinking):
        if isinstance(exc, (urllib.error.URLError, TimeoutError, socket.timeout,
                            ConnectionError, OSError)):
            raise LocalBrainUnavailable(f"local Ollama unavailable ({type(exc).__name__})") from None
        raise LocalBrainUnavailable(f"local Ollama unavailable ({type(exc).__name__})") from None
    if error and not (content or thinking):
        raise LocalBrainUnavailable("configured local model is unavailable")
    return {"message": {"content": "".join(content), "thinking": "".join(thinking)}}


def infer_json(system_prompt: str, text: str, *, context: dict | None = None,
               config: OllamaConfig, should_yield=None) -> dict:
    """`should_yield` is the checkpoint: a callable asked repeatedly while the
    model is thinking, and when it says True the call is abandoned with
    `LocalBrainYielded`. Only background work passes one; a conversation is
    never interrupted, and the call it makes is unchanged (unstreamed)."""
    ctx = context or {}
    if not isinstance(ctx, dict):
        raise ValueError("local reasoning context must be an object")
    payload = build_payload(system_prompt, text, ctx, config)
    if should_yield is None:
        response = request_json(config, "/api/chat", payload)
    else:
        config.validated()
        response = _stream_chat(config, payload, should_yield)
    message = response.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        detail = response.get("error")
        if isinstance(detail, str) and detail:
            raise LocalBrainUnavailable("configured local model is unavailable")
        raise LocalBrainProtocolError("Ollama response missing message.content")
    content = message["content"]
    thinking = message.get("thinking")
    if not content.strip() and not config.think and isinstance(thinking, str) and thinking.strip():
        # A MODEL THAT CANNOT STOP THINKING. qwen3-vl:4b ignores
        # `think: false` and returns its whole reply in `thinking` with an
        # empty `content` (measured 2026-09-16, Ollama 0.34.1): every call
        # failed as "no JSON object" while the object sat one field over.
        # Only when thinking was switched OFF - then nothing in that field
        # was asked to be reasoning, and it is the answer mis-channelled.
        content = thinking
    return _first_json_object(content)


def status(config: OllamaConfig) -> dict[str, Any]:
    result = {"model": config.model, "think": config.think, "online": False, "model_available": False}
    try:
        response = request_json(config, "/api/tags")
    except LocalBrainError as exc:
        result["detail"] = str(exc)
        return result
    names = []
    for row in response.get("models", []) if isinstance(response.get("models"), list) else []:
        if isinstance(row, dict) and isinstance(row.get("name"), str):
            names.append(row["name"])
    result["online"] = True
    result["model_available"] = config.model in names
    if not result["model_available"]:
        result["detail"] = f"model not pulled: {config.model}"
    return result
