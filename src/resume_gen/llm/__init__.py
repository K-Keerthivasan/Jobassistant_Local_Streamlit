"""LLM engines. `chat_structured` routes to the right one by model id:
a `claude-*` model goes to the Anthropic (cloud) client, anything else to Ollama
(local). Both return a validated pydantic instance, so the rest of the pipeline
doesn't care which engine produced it."""

from __future__ import annotations

import time
from typing import Type, TypeVar

from pydantic import BaseModel

from ..config import settings

T = TypeVar("T", bound=BaseModel)


def chat_structured(system: str, user: str, schema: Type[T], *, model: str | None = None, **kw) -> T:
    model = model or settings.ollama_model
    kw.setdefault("timeout", settings.llm_timeout)  # cap every AI request
    start = time.perf_counter()
    try:
        if str(model).startswith("claude"):
            from . import anthropic_client
            return anthropic_client.chat_structured(system, user, schema, model=model, **kw)
        from . import ollama_client
        return ollama_client.chat_structured(system, user, schema, model=model, **kw)
    finally:
        _log_time(model, time.perf_counter() - start, schema.__name__)


def _log_time(model: str, elapsed: float, label: str) -> None:
    """Print + persist how long an AI call took (best-effort, never raises)."""
    print(f"[ai] {model} {label} took {elapsed:.1f}s", flush=True)
    try:
        from ..usage import record_time
        record_time(model, elapsed, label=label)
    except Exception:
        pass
