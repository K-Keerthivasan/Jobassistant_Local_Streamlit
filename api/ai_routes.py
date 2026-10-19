"""AI Engine view: live engine status, the generation step map, AI settings,
engine tests and the AI activity log."""

from __future__ import annotations

import time

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from resume_gen import ai_settings
from resume_gen.config import settings
from resume_gen.llm import activity, hermes_client, ollama_client

router = APIRouter(prefix="/ai", tags=["ai"])


def _timed(fn):
    start = time.perf_counter()
    try:
        ok = bool(fn())
    except Exception:
        ok = False
    return ok, round((time.perf_counter() - start) * 1000)


@router.get("/status")
def status():
    """Both engines, the defaults in force, and today's call counts."""
    hermes_configured = hermes_client.available()
    # The two engines are independent: check them at the same time.
    with ThreadPoolExecutor(max_workers=3) as pool:
        h = pool.submit(_timed, hermes_client.health) if hermes_configured else None
        o = pool.submit(_timed, ollama_client.health)
        models = pool.submit(ollama_client.list_models)
        hermes_up, hermes_ms = h.result() if h else (False, 0)
        ollama_up, ollama_ms = o.result()
        installed = models.result() if ollama_up else []
    effective = ollama_client.effective_model() if ollama_up else settings.ollama_model
    warnings = []
    if hermes_configured and not hermes_up:
        warnings.append(
            "Hermes is not answering. Start the bridge (tools/start_hermes_bridge.ps1) "
            + ("— Ollama will answer meanwhile." if settings.allow_ollama_fallback and ollama_up
               else "— nothing can generate until it is back."))
    if ollama_up and settings.ollama_model not in installed:
        warnings.append(f"Ollama model {settings.ollama_model} is not installed; {effective} is used instead. "
                        "Pick an installed model below to silence this.")
    if not ollama_up and settings.default_engine == "ollama":
        warnings.append("Ollama is the default engine but is not running.")
    return {
        "hermes": {
            "configured": hermes_configured, "reachable": hermes_up, "latency_ms": hermes_ms,
            "base_url": settings.hermes_base_url, "model": settings.hermes_model,
            "how": "Hermes is an AI agent running on this computer. The app reaches it through "
                   "the bridge on port 8642, which hands each request to the Hermes command line "
                   "as a one-shot task and returns its answer.",
        },
        "ollama": {
            "reachable": ollama_up, "latency_ms": ollama_ms, "host": settings.ollama_host,
            "configured_model": settings.ollama_model, "effective_model": effective,
            "installed": installed,
            "how": "Ollama runs open models on this computer. The app sends it the prompt and a "
                   "JSON schema, and checks the reply against that schema.",
        },
        "defaults": {
            "engine": settings.default_engine, "fast_mode": settings.hermes_fast_mode,
            "fallback": settings.allow_ollama_fallback, "timeout": settings.llm_timeout,
            "record_prompts": settings.record_prompts, "pdf_engine": settings.pdf_engine,
        },
        "warnings": warnings,
        "today": activity.summary(),
    }


@router.get("/pipeline")
def pipeline():
    up = hermes_client.health() if hermes_client.available() else False
    return {"steps": ai_settings.pipeline(hermes_up=up), "apply_steps": ai_settings.apply_pipeline()}


@router.get("/settings")
def get_settings():
    return {"settings": ai_settings.current(),
            "ollama_models": ollama_client.list_models()}


@router.post("/settings")
def post_settings(changes: dict):
    try:
        return {"settings": ai_settings.update(changes)}
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/activity")
def get_activity(limit: int = 100):
    return {"items": activity.recent(max(1, min(limit, 300))), "summary": activity.summary()}


@router.get("/activity/{entry_id}")
def get_activity_entry(entry_id: str):
    entry = activity.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No such AI call.")
    return entry


class EngineCall(BaseModel):
    """One Hermes call made by the Chrome application engine (src/ailog.ts)."""
    schema_: str = Field(alias="schema", pattern="^(NavigationAdvice|AnswerDraft|AnswerAudit)$")
    job: str = Field("", max_length=300)
    seconds: float = Field(0, ge=0, le=3600)
    status: str = Field("ok", pattern="^(ok|error)$")
    error: str = Field("", max_length=2000)
    system: str = Field("", max_length=60_000)
    user: str = Field("", max_length=200_000)
    response: str = Field("", max_length=60_000)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)


@router.post("/activity")
def post_activity(call: EngineCall, request: Request):
    """Record a call from the Chrome application engine. Loopback only: the
    engine shares this machine (or this container's network) with Studio."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Only the local application engine may report AI calls.")
    with activity.job_context(call.job):
        entry = activity.record(
            schema=call.schema_, requested=settings.hermes_model, used=settings.hermes_model,
            seconds=call.seconds, status=call.status, error=call.error,
            input_tokens=call.input_tokens, output_tokens=call.output_tokens,
            system=call.system, user=call.user, response=call.response,
            keep_prompts=settings.record_prompts)
    return {"id": entry["id"]}


@router.delete("/activity")
def clear_activity():
    activity.clear()
    return {"cleared": True}


class Ping(BaseModel):
    reply: str = ""


class TestRequest(BaseModel):
    engine: str = "hermes"


@router.post("/test")
def test_engine(req: TestRequest):
    """One short structured call to the chosen engine, logged like any other."""
    from resume_gen.llm import chat_structured

    if req.engine not in ("hermes", "ollama"):
        raise HTTPException(status_code=400, detail="engine must be hermes or ollama")
    model = settings.hermes_model if req.engine == "hermes" else ollama_client.effective_model()
    start = time.perf_counter()
    try:
        with activity.job_context("AI Engine view", "engine test"):
            out = chat_structured(
                "Reply with a JSON object whose reply field is a short greeting.",
                "Say hello in five words or fewer.", Ping, model=model, timeout=120)
        last = (activity.recent(1) or [{}])[0]
        used = last.get("engine_used") or model
        fell_back = bool(last.get("fallback"))
        return {"ok": not fell_back, "engine": used, "reply": out.reply,
                "fallback": last.get("fallback", ""),
                "seconds": round(time.perf_counter() - start, 1)}
    except Exception as e:
        return {"ok": False, "engine": model, "error": f"{type(e).__name__}: {e}"[:500],
                "seconds": round(time.perf_counter() - start, 1)}
