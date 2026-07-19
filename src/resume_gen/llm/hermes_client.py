"""Hermes (local agent) client — the secondary generation engine, replacing the
old Claude/Anthropic cloud path. Talks to the Hermes agent's OpenAI-compatible
gateway (`POST {HERMES_BASE_URL}/chat/completions`, default
http://localhost:8642/v1), authenticated with the gateway's API_SERVER_KEY.

Hermes is an *agent*, so its chat replies can include prose/reasoning around the
answer. We therefore ask for JSON only and extract the first balanced object,
then validate it against the pydantic schema — same contract as the Ollama and
(former) Claude clients, so the rest of the pipeline doesn't care which engine ran.

Enable it by setting HERMES_API_KEY (the gateway's API_SERVER_KEY) in .env; the
model picker then offers the Hermes engine.
"""

from __future__ import annotations

import json
import time
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel

from ..config import settings

T = TypeVar("T", bound=BaseModel)


class HermesError(RuntimeError):
    pass


# id -> friendly label, shown in the picker. Hermes is one agent; the id maps to
# the gateway's served model (API_SERVER_MODEL_NAME), defaulting to "hermes".
def HERMES_MODELS() -> list[tuple[str, str]]:
    return [(settings.hermes_model, "Hermes (agent)")]


def available() -> bool:
    """True if the Hermes gateway key is configured (so the engine can be offered).
    The gateway refuses to start without API_SERVER_KEY, so a key implies a usable
    endpoint; reachability is checked separately by `health()`."""
    return bool(settings.hermes_api_key and settings.hermes_base_url)


def list_models() -> list[str]:
    return [m for m, _ in HERMES_MODELS()] if available() else []


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if settings.hermes_api_key:
        h["Authorization"] = f"Bearer {settings.hermes_api_key}"
    return h


def _extract_json_object(text: str) -> str:
    """Return the first balanced {...} block from an agent reply (which may wrap
    the JSON in prose or ``` fences)."""
    t = (text or "").strip()
    start = t.find("{")
    if start == -1:
        raise HermesError("Hermes reply contained no JSON object.")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return t[start : i + 1]
    raise HermesError("Hermes reply had an unbalanced JSON object.")


def _chat(messages: list[dict], *, model: str, timeout: float,
          temperature: float | None = None) -> str:
    """One OpenAI-compatible chat call to the Hermes gateway; returns reply text."""
    url = f"{settings.hermes_base_url.rstrip('/')}/chat/completions"
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if temperature is not None:
        payload["temperature"] = temperature
    try:
        resp = httpx.post(url, json=payload, headers=_headers(), timeout=timeout)
        resp.raise_for_status()
    except httpx.TimeoutException as e:
        raise HermesError(
            f"Hermes timed out after {timeout:.0f}s (model={model}, url={url})."
        ) from e
    except httpx.HTTPError as e:
        raise HermesError(f"Hermes request failed ({model}): {e}") from e
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as e:
        raise HermesError(f"Hermes returned an unexpected response shape: {e}") from e


def chat_structured(
    system: str,
    user: str,
    schema: Type[T],
    *,
    model: str | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
    retries: int = 2,
    **_: object,
) -> T:
    """Call Hermes and return a validated instance of `schema`. Asks for JSON-only
    output and validates it; retries a couple of times on empty/invalid JSON."""
    if not available():
        raise HermesError("HERMES_API_KEY is not set — cannot use the Hermes engine.")
    model = model or settings.hermes_model
    timeout = settings.llm_timeout if timeout is None else timeout

    schema_json = json.dumps(schema.model_json_schema())
    sys = (
        f"{system}\n\nYou MUST respond with a single JSON object that conforms to "
        f"this JSON Schema. Output ONLY the JSON — no prose, no explanation, no "
        f"markdown code fences.\nJSON Schema:\n{schema_json}"
    )
    messages = [{"role": "system", "content": sys}, {"role": "user", "content": user}]

    last_err: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            content = _chat(messages, model=model, timeout=timeout, temperature=temperature)
            if not content.strip():
                raise HermesError("Hermes returned an empty response.")
            return schema.model_validate(json.loads(_extract_json_object(content)))
        except HermesError as e:
            if "timed out" in str(e):
                raise  # don't multiply the wait on a timeout
            last_err = e
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
    raise HermesError(
        f"Hermes failed after {retries + 1} attempts for {schema.__name__} "
        f"(model={model}): {last_err}"
    )


def health() -> bool:
    """True if the Hermes gateway is reachable."""
    try:
        r = httpx.get(f"{settings.hermes_base_url.rstrip('/')}/models",
                      headers=_headers(), timeout=5.0)
        return r.status_code < 500
    except httpx.HTTPError:
        return False


def find_jobs(role: str, location: str = "", *, limit: int = 15,
              model: str | None = None) -> list[dict]:
    """Have the Hermes agent find current job postings and return them as a list of
    dicts (company/title/location/description/apply_url/contact_email). Relies on
    whatever search/browse tools the agent has configured."""
    if not available():
        raise HermesError("HERMES_API_KEY is not set — cannot use Hermes Scraping.")
    model = model or settings.hermes_model
    where = location.strip() or "Remote"
    system = (
        "You are a job-search assistant. Find REAL, CURRENT job postings that match "
        "the request. Return ONLY a JSON array (no prose, no code fences) of up to the "
        "requested count of objects with EXACTLY these keys: company, title, location, "
        "description, apply_url, contact_email. Use the real posting URL for apply_url; "
        'leave contact_email "" unless an application email is clearly stated. Prefer '
        "postings in the requested location. Do not invent postings."
    )
    prompt = f'Find up to {limit} current "{role}" job postings in {where}.'
    start = time.perf_counter()
    try:
        content = _chat(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            model=model, timeout=settings.llm_timeout,
        )
    finally:
        _record_time(model, time.perf_counter() - start, "find_jobs")
    return _parse_jobs_json(content)


def _parse_jobs_json(text: str) -> list[dict]:
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


def _record_time(model: str, elapsed: float, label: str) -> None:
    print(f"[ai] {model} {label} took {elapsed:.1f}s", flush=True)
    try:
        from ..usage import record_time
        record_time(model, elapsed, label=label)
    except Exception:
        pass
