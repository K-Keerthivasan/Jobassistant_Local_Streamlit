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


def reset_run_metrics() -> None:
    _local.metrics = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "seconds": 0.0,
        "by_label": {},
    }


def record_run_tokens(model: str, input_tokens: int, output_tokens: int, label: str) -> None:
    if not hasattr(_local, "metrics"):
        reset_run_metrics()
    m = _local.metrics
    m["calls"] += 1
    m["input_tokens"] += int(input_tokens or 0)
    m["output_tokens"] += int(output_tokens or 0)
    b = m["by_label"].setdefault(label or "unknown", {
        "calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0,
    })
    b["calls"] += 1
    b["input_tokens"] += int(input_tokens or 0)
    b["output_tokens"] += int(output_tokens or 0)


def run_metrics() -> dict:
    m = getattr(_local, "metrics", None)
    if not m:
        reset_run_metrics()
        m = _local.metrics
    return {
        **m,
        "seconds": round(float(m["seconds"]), 3),
        "total_tokens": int(m["input_tokens"]) + int(m["output_tokens"]),
        "by_label": {k: {**v, "seconds": round(float(v["seconds"]), 3)}
                     for k, v in m["by_label"].items()},
    }


def fallbacks() -> list[str]:
    return list(getattr(_local, "fb", []))


def _record_fallback(reason: str) -> None:
    if not hasattr(_local, "fb"):
        _local.fb = []
    _local.fb.append(reason)
    # ASCII only: a Windows console (cp1252) raises on characters like an arrow,
    # which used to turn every fallback into a crash.
    print(f"[ai] Hermes unavailable -> fell back to Ollama ({reason})".encode("ascii", "replace").decode(), flush=True)


def _default_model() -> str:
    """The engine to use when a caller doesn't name one. Prefers Hermes (per
    DEFAULT_ENGINE) when it's reachable, else local Ollama."""
    if settings.default_engine == "hermes":
        from . import hermes_client
        if hermes_client.available():
            return settings.hermes_model
    return settings.ollama_model


def chat_structured(system: str, user: str, schema: Type[T], *, model: str | None = None, **kw) -> T:
    """Run one structured AI call and record it in the AI activity log."""
    requested = model or "auto"
    if not model or str(model).strip().lower() in ("split", "auto"):
        model = _default_model()
    state = {"used": model, "fallback": ""}
    tokens_before = _token_totals()
    start = time.perf_counter()
    result = None
    error: Exception | None = None
    try:
        result = _route(system, user, schema, model, state, **kw)
        return result
    except Exception as e:
        error = e
        raise
    finally:
        elapsed = time.perf_counter() - start
        _log_time(state["used"], elapsed, schema.__name__)
        tokens_after = _token_totals()
        from . import activity
        reply = ""
        if result is not None:
            try:
                reply = result.model_dump_json(indent=2)
            except Exception:
                reply = str(result)
        activity.record(
            schema=schema.__name__, requested=str(requested), used=str(state["used"]),
            seconds=elapsed, status="ok" if error is None else "error",
            error="" if error is None else f"{type(error).__name__}: {error}",
            fallback=state["fallback"],
            input_tokens=tokens_after[0] - tokens_before[0],
            output_tokens=tokens_after[1] - tokens_before[1],
            system=system, user=user, response=reply,
            keep_prompts=settings.record_prompts,
        )


def _token_totals() -> tuple[int, int]:
    m = getattr(_local, "metrics", None) or {}
    return int(m.get("input_tokens", 0)), int(m.get("output_tokens", 0))


def _route(system: str, user: str, schema: Type[T], model: str, state: dict, **kw) -> T:
    # "split"/"auto"/none were resolved by the caller to the default engine
    # (Hermes-first, Ollama fallback). pipeline.run handles real "split".
    kw.setdefault("timeout", settings.llm_timeout)  # cap every AI request
    if str(model).startswith("hermes"):
        from . import hermes_client
        try:
            return hermes_client.chat_structured(system, user, schema, model=model, **kw)
        except hermes_client.HermesRateLimitError:
            raise  # a quota wait is not permission to switch providers
        except Exception as e:
            # Hermes failed mid-call → fall back to local Ollama so the run still
            # completes, and record it for the UI notice. Without a reachable
            # Ollama, or with the fallback switched off, surface the real Hermes error.
            from . import ollama_client
            if not settings.allow_ollama_fallback:
                raise
            if not ollama_client.health():
                print(f"[ai] Hermes failed, Ollama unreachable: {e}".encode("ascii", "replace").decode(), flush=True)
                raise
            used = ollama_client.effective_model()
            state["used"] = used
            state["fallback"] = f"Hermes failed ({type(e).__name__}: {str(e)[:200]}); answered by Ollama {used}"
            _record_fallback(f"{schema.__name__}: {type(e).__name__}: {str(e)[:300]}")
            return ollama_client.chat_structured(system, user, schema, model=used, **kw)
    from . import ollama_client
    if model == settings.ollama_model:
        model = ollama_client.effective_model()
        state["used"] = model
    return ollama_client.chat_structured(system, user, schema, model=model, **kw)


def _log_time(model: str, elapsed: float, label: str) -> None:
    """Print + persist how long an AI call took (best-effort, never raises)."""
    print(f"[ai] {model} {label} took {elapsed:.1f}s", flush=True)
    if not hasattr(_local, "metrics"):
        reset_run_metrics()
    _local.metrics["seconds"] += elapsed
    b = _local.metrics["by_label"].setdefault(label or "unknown", {
        "calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0,
    })
    b["seconds"] += elapsed
    try:
        from ..usage import record_time
        record_time(model, elapsed, label=label)
    except Exception:
        pass
