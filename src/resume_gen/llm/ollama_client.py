"""Thin Ollama client using the /api/chat endpoint with JSON-schema constrained
output (the `format` field). This forces the model to emit JSON matching our
pydantic schema, which we then validate — no brittle text parsing."""

from __future__ import annotations

import json
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel

from ..config import settings

T = TypeVar("T", bound=BaseModel)


class OllamaError(RuntimeError):
    pass


def _strip_code_fences(text: str) -> str:
    """Defensive: some models still wrap JSON in ``` fences despite instructions."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def chat_structured(
    system: str,
    user: str,
    schema: Type[T],
    *,
    model: str | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
    retries: int = 2,
) -> T:
    """Call Ollama and return a validated instance of `schema`.

    Some local models intermittently emit an empty body or invalid JSON under a
    schema constraint; we retry a couple of times before giving up."""
    model = model or settings.ollama_model
    temperature = settings.ollama_temperature if temperature is None else temperature
    timeout = settings.llm_timeout if timeout is None else timeout

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # Constrain output to the pydantic JSON schema.
        "format": schema.model_json_schema(),
        "options": {"temperature": temperature},
    }
    url = f"{settings.ollama_host.rstrip('/')}/api/chat"

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
            if not content.strip():
                raise OllamaError("Ollama returned an empty response.")
            data = json.loads(_strip_code_fences(content))
            return schema.model_validate(data)
        except httpx.TimeoutException as e:
            # Don't retry a timeout — that would multiply the wait. Fail fast.
            raise OllamaError(
                f"Ollama timed out after {timeout:.0f}s for {schema.__name__} (model={model})."
            ) from e
        except (httpx.HTTPError, json.JSONDecodeError, OllamaError, ValueError) as e:
            last_err = e
            # nudge variety on the retry so we don't repeat a degenerate output
            payload["options"]["temperature"] = min(0.9, temperature + 0.2 * (attempt + 1))

    raise OllamaError(
        f"Ollama failed after {retries + 1} attempts for {schema.__name__} "
        f"(model={model}): {last_err}"
    )


def health() -> bool:
    """True if the Ollama server is reachable."""
    try:
        r = httpx.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=5.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def list_models() -> list[str]:
    """Names of locally installed Ollama models (for the UI model picker)."""
    try:
        r = httpx.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=5.0)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except (httpx.HTTPError, KeyError, ValueError):
        return []
