"""Claude (Anthropic API) client — the cloud generation engine, an alternative to
local Ollama. Uses the official `anthropic` SDK's `messages.parse()` for schema-
validated structured output (returns a validated pydantic instance).

Set ANTHROPIC_API_KEY to enable it; the model picker then offers the Claude models.
"""

from __future__ import annotations

import os
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AnthropicError(RuntimeError):
    pass


# id -> friendly label, in the order shown in the picker. Opus 4.8 is the default
# (most capable); Sonnet/Haiku are cheaper, faster options.
CLAUDE_MODELS: list[tuple[str, str]] = [
    ("claude-opus-4-8", "Claude Opus 4.8 (best)"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (balanced)"),
    ("claude-haiku-4-5", "Claude Haiku 4.5 (fast)"),
]

DEFAULT_MODEL = "claude-opus-4-8"


def available() -> bool:
    """True if an API key is configured (so the cloud engine can be offered)."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def list_models() -> list[str]:
    return [m for m, _ in CLAUDE_MODELS] if available() else []


def chat_structured(
    system: str,
    user: str,
    schema: Type[T],
    *,
    model: str | None = None,
    temperature: float | None = None,  # accepted + ignored: removed on Opus 4.8/4.7
    timeout: float | None = None,
    **_: object,
) -> T:
    """Call Claude and return a validated `schema` instance via structured output."""
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise AnthropicError("The 'anthropic' package is not installed.") from e

    if not available():
        raise AnthropicError("ANTHROPIC_API_KEY is not set — cannot use the Claude engine.")

    from ..config import settings
    to = settings.llm_timeout if timeout is None else timeout
    client = anthropic.Anthropic(timeout=to)  # reads ANTHROPIC_API_KEY from the env
    model = model or DEFAULT_MODEL
    try:
        # NOTE: no temperature/top_p — Opus 4.8/4.7 reject sampling params (400).
        resp = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
    except Exception as e:  # surface a clean message to the API layer
        raise AnthropicError(f"Claude request failed ({model}): {e}") from e

    _record_usage(model, resp)
    if resp.parsed_output is None:
        raise AnthropicError(
            f"Claude returned no structured output for {schema.__name__} "
            f"(stop_reason={resp.stop_reason})."
        )
    return resp.parsed_output


def _record_usage(model: str, resp) -> None:
    try:
        from ..usage import record
        u = getattr(resp, "usage", None)
        if u is not None:
            record(model, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0)
    except Exception:
        pass


def _record_time(model: str, elapsed: float, label: str) -> None:
    """Print + persist how long a Claude call took (best-effort)."""
    print(f"[ai] {model} {label} took {elapsed:.1f}s", flush=True)
    try:
        from ..usage import record_time
        record_time(model, elapsed, label=label)
    except Exception:
        pass


def find_jobs(role: str, location: str = "", *, limit: int = 15,
              model: str | None = None) -> list[dict]:
    """Have Claude search the web for current job postings and return them as a
    list of dicts (company/title/location/description/apply_url/contact_email).

    Uses the server-side web_search tool, so Claude pulls live listings."""
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise AnthropicError("The 'anthropic' package is not installed.") from e
    if not available():
        raise AnthropicError("ANTHROPIC_API_KEY is not set — cannot use Claude Scraping.")

    from ..config import settings
    client = anthropic.Anthropic(timeout=settings.llm_timeout)
    model = model or DEFAULT_MODEL
    where = location.strip() or "Canada"
    system = (
        "You are a job-search assistant. Use web search to find REAL, CURRENT job "
        "postings that match the request. Return ONLY a JSON array (no prose, no code "
        "fences) of up to the requested count of objects with EXACTLY these keys: "
        "company, title, location, description, apply_url, contact_email. Use the real "
        "posting URL for apply_url; leave contact_email \"\" unless an application email "
        "is clearly stated. Prefer postings in the requested location/Canada. Do not "
        "invent postings — only include ones you actually found."
    )
    prompt = f"Find up to {limit} current \"{role}\" job postings in {where}."
    import time
    start = time.perf_counter()
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=8000,
            system=system,
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise AnthropicError(f"Claude job search failed ({model}): {e}") from e
    finally:
        _record_time(model, time.perf_counter() - start, "find_jobs")

    _record_usage(model, resp)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _parse_jobs_json(text)


def _parse_jobs_json(text: str) -> list[dict]:
    import json
    import re

    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    out = []
    for it in data if isinstance(data, list) else []:
        if isinstance(it, dict) and (it.get("title") or it.get("company")):
            out.append(it)
    return out
