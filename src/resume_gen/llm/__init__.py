"""LLM engines. `chat_structured` routes to the right one by model id:
a `hermes*` model goes to the Hermes (local agent) client, anything else to Ollama
(local). Both return a validated pydantic instance, so the rest of the pipeline
doesn't care which engine produced it."""

from __future__ import annotations

import threading
import time
from typing import Type, TypeVar

from pydantic import BaseModel

from ..config import settings

T = TypeVar("T", bound=BaseModel)

# Per-thread record of Hermes→Ollama fallbacks during one request/run, so the
# pipeline can tell the UI "Hermes wasn't reachable — generated with Ollama".
_local = threading.local()


def reset_fallbacks() -> None:
    _local.fb = []


def fallbacks() -> list[str]:
    return list(getattr(_local, "fb", []))


def _record_fallback(reason: str) -> None:
    if not hasattr(_local, "fb"):
        _local.fb = []
    _local.fb.append(reason)
    print(f"[ai] Hermes unavailable → fell back to Ollama ({reason})", flush=True)


def _default_model() -> str:
    """The engine to use when a caller doesn't name one. Prefers Hermes (per
    DEFAULT_ENGINE) when it's reachable, else local Ollama."""
    if settings.default_engine == "hermes":
        from . import hermes_client
        if hermes_client.available():
            return settings.hermes_model
    return settings.ollama_model


def chat_structured(system: str, user: str, schema: Type[T], *, model: str | None = None, **kw) -> T:
    # "split"/"auto"/none are meta-selections, not real model ids — resolve to the
    # default engine (Hermes-first, Ollama fallback). pipeline.run handles real "split".
    if not model or str(model).strip().lower() in ("split", "auto"):
        model = _default_model()
    kw.setdefault("timeout", settings.llm_timeout)  # cap every AI request
    start = time.perf_counter()
    used = model
    try:
        if str(model).startswith("hermes"):
            from . import hermes_client
            try:
                return hermes_client.chat_structured(system, user, schema, model=model, **kw)
            except Exception as e:
                # Hermes failed mid-call → fall back to local Ollama so the run still
                # completes, and record it for the UI notice.
                used = settings.ollama_model
                _record_fallback(f"{schema.__name__}: {type(e).__name__}")
                from . import ollama_client
                return ollama_client.chat_structured(system, user, schema, model=used, **kw)
        from . import ollama_client
        return ollama_client.chat_structured(system, user, schema, model=model, **kw)
    finally:
        _log_time(used, time.perf_counter() - start, schema.__name__)


def _log_time(model: str, elapsed: float, label: str) -> None:
    """Print + persist how long an AI call took (best-effort, never raises)."""
    print(f"[ai] {model} {label} took {elapsed:.1f}s", flush=True)
    try:
        from ..usage import record_time
        record_time(model, elapsed, label=label)
    except Exception:
        pass
