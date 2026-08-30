"""Loopback-only JSON reasoning adapter for local Ollama models.

This layer has zero execution authority.  It accepts a caller-owned system
prompt/context and returns one JSON object; the caller still owns schema
validation and every Aletheia policy/action gate.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_S = 45.0
MAX_RESPONSE_BYTES = 512 * 1024
MAX_CONTEXT_BYTES = 16 * 1024
MAX_PROMPT_CHARS = 24_000


class LocalBrainError(RuntimeError):
    pass


class LocalBrainUnavailable(LocalBrainError):
    pass


class LocalBrainProtocolError(LocalBrainError):
    pass


@dataclass(frozen=True)
class OllamaConfig:
    model: str
    think: bool = False
    timeout_s: float = DEFAULT_TIMEOUT_S
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def for_model(cls, model: str, *, think: bool = False, timeout_s: float | None = None):
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
        if not 0.5 <= float(self.timeout_s) <= 300:
            raise ValueError("local AI timeout must be 0.5..300 seconds")
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
    return {
        "model": config.model,
        "stream": False,
        "think": config.think,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text + ("\n\n--- UNTRUSTED CONTEXT JSON ---\n" + ctx if context else "")},
        ],
    }


def infer_json(system_prompt: str, text: str, *, context: dict | None = None,
               config: OllamaConfig) -> dict:
    ctx = context or {}
    if not isinstance(ctx, dict):
        raise ValueError("local reasoning context must be an object")
    payload = build_payload(system_prompt, text, ctx, config)
    response = request_json(config, "/api/chat", payload)
    message = response.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        detail = response.get("error")
        if isinstance(detail, str) and detail:
            raise LocalBrainUnavailable("configured local model is unavailable")
        raise LocalBrainProtocolError("Ollama response missing message.content")
    return _first_json_object(message["content"])


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
