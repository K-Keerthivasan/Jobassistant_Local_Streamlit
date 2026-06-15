"""LLM engines. `chat_structured` routes to the right one by model id:
a `hermes*` model goes to the Hermes (local agent) client, anything else to Ollama
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
    # "split"/"auto" are UI/pipeline meta-selections, not real model ids. pipeline.run
    # resolves them per-artifact (résumé vs letters); if one reaches here it's a
    # single-call site (e.g. a screening answer) with no artifact to split across, so
    # run it on the default local model instead of passing a bogus id to Ollama.
    if str(model).strip().lower() in ("split", "auto"):
        model = settings.ollama_model
    kw.setdefault("timeout", settings.llm_timeout)  # cap every AI request
    start = time.perf_counter()
    try:
        if str(model).startswith("hermes"):
            from . import hermes_client
            return hermes_client.chat_structured(system, user, schema, model=model, **kw)
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
