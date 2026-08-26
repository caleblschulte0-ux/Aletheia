"""Provider-neutral reasoning interface, including a future local-model slot.

Aletheia's operating system should not be welded to one model vendor. Policy,
memory, tasks, capability truth and verification stay outside the model; a
'brain' receives a bounded request and returns text + metadata. Routing respects
local-only privacy and advertised task support. This module makes no network
calls and stores no API keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

TASKS = {"classify", "plan", "reason", "write", "extract", "review"}
PRIVACY = {"local_only", "provider_ok"}
LOCALITIES = {"local", "remote"}


def validate_request(request: dict) -> None:
    allowed = {"id", "task", "prompt", "context", "privacy", "max_output_chars"}
    unknown = set(request) - allowed
    if unknown:
        raise ValueError(f"unknown brain request fields {sorted(unknown)}")
    if not isinstance(request.get("id"), str) or not request["id"]:
        raise ValueError("brain request id is required")
    if request.get("task") not in TASKS:
        raise ValueError("invalid brain task")
    if not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
        raise ValueError("brain prompt is required")
    context = request.get("context", [])
    if not isinstance(context, list) or len(context) > 100 or any(not isinstance(x, str) for x in context):
        raise ValueError("brain context must be at most 100 string references")
    if request.get("privacy", "provider_ok") not in PRIVACY:
        raise ValueError("invalid brain privacy")
    limit = request.get("max_output_chars", 12000)
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("max_output_chars must be 1..100000")


def validate_response(request: dict, response: dict) -> None:
    validate_request(request)
    required = {"request_id", "provider_id", "model_id", "text"}
    missing = required - response.keys()
    if missing:
        raise ValueError(f"brain response missing {sorted(missing)}")
    allowed = required | {"usage", "finish_reason"}
    unknown = set(response) - allowed
    if unknown:
        raise ValueError(f"unknown brain response fields {sorted(unknown)}")
    if response["request_id"] != request["id"]:
        raise ValueError("brain response request_id mismatch")
    for key in ("provider_id", "model_id", "text"):
        if not isinstance(response[key], str):
            raise ValueError(f"brain response {key} must be text")
    if len(response["text"]) > request.get("max_output_chars", 12000):
        raise ValueError("brain response exceeds requested output bound")


class BrainAdapter(Protocol):
    provider_id: str
    model_id: str
    locality: str
    tasks: set[str]

    def invoke(self, request: dict) -> dict: ...


@dataclass(frozen=True)
class AdapterInfo:
    provider_id: str
    model_id: str
    locality: str
    tasks: frozenset[str]
    priority: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("adapter provider_id is required")
        if not isinstance(self.model_id, str) or not self.model_id:
            raise ValueError("adapter model_id is required")
        if self.locality not in LOCALITIES:
            raise ValueError("adapter locality must be local or remote")
        if not self.tasks or not self.tasks.issubset(TASKS):
            raise ValueError("adapter tasks must be a non-empty subset of TASKS")
        if type(self.priority) is not int:
            raise ValueError("adapter priority must be an integer")


def info(adapter: BrainAdapter, *, priority: int = 100) -> AdapterInfo:
    return AdapterInfo(provider_id=adapter.provider_id, model_id=adapter.model_id,
                       locality=adapter.locality, tasks=frozenset(adapter.tasks),
                       priority=priority)


def _metadata_matches_adapter(metadata: AdapterInfo, adapter: BrainAdapter) -> bool:
    try:
        return (metadata.provider_id == adapter.provider_id and
                metadata.model_id == adapter.model_id and
                metadata.locality == adapter.locality and
                metadata.tasks == frozenset(adapter.tasks) and
                adapter.locality in LOCALITIES and
                frozenset(adapter.tasks).issubset(TASKS))
    except (AttributeError, TypeError):
        return False


def select(request: dict, adapters: list[tuple[AdapterInfo, BrainAdapter]]) -> BrainAdapter:
    validate_request(request)
    eligible = []
    privacy = request.get("privacy", "provider_ok")
    for position, (metadata, adapter) in enumerate(adapters):
        if not _metadata_matches_adapter(metadata, adapter):
            raise ValueError("brain adapter metadata does not match adapter identity/locality/tasks")
        if request["task"] not in metadata.tasks:
            continue
        if privacy == "local_only" and metadata.locality != "local":
            continue
        eligible.append((metadata.priority, 0 if metadata.locality == "local" else 1,
                         position, adapter))
    if not eligible:
        raise LookupError("no brain adapter satisfies task/privacy requirements")
    eligible.sort(key=lambda row: row[:3])
    return eligible[0][3]


def invoke(request: dict, adapters: list[tuple[AdapterInfo, BrainAdapter]]) -> dict:
    """Invoke only an explicitly supplied adapter and validate its envelope."""
    adapter = select(request, adapters)
    response = adapter.invoke(dict(request))
    validate_response(request, response)
    if response["provider_id"] != adapter.provider_id or response["model_id"] != adapter.model_id:
        raise ValueError("brain adapter response misidentified its provider/model")
    return response
