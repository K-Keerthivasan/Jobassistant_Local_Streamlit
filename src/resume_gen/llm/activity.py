"""AI activity log: one record per AI call, so the app can show what the AI did.

Every call through `llm.chat_structured` lands here: which task it served, which
job, which engine was asked for and which one actually answered, any Hermes to
Ollama fallback, how long it took, tokens, and whether it succeeded. When prompt
recording is on (the default), a trimmed copy of the prompt and the reply is kept
too, so the AI Engine view can show exactly what was asked and answered.

Records live in memory (the latest 300) and in data/ai_activity.jsonl, trimmed to
the newest 1,000 lines. Everything stays on this machine.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime

from ..config import ROOT

_DEFAULT_FILE = ROOT / "data" / "ai_activity.jsonl"
_FILE = _DEFAULT_FILE
_KEEP_FILE = 1000
_PREVIEW = 4000
_LOCK = threading.RLock()
_RECENT: deque = deque(maxlen=300)
_local = threading.local()
_loaded = False

# What each structured call is for, in plain words, keyed by its output schema.
TASKS: dict[str, tuple[str, str]] = {
    "ApplicationDraft": ("Write resume and cover letter", "One call writes both documents from your profile and the posting."),
    "Resume": ("Write resume", "Tailors the resume to the posting from your profile facts."),
    "CoverLetter": ("Write cover letter", "Writes the four-paragraph cover letter."),
    "EmailHook": ("Write email opener", "Writes the two personalised lines of the application email."),
    "HermesQAResult": ("Truth audit", "Checks every resume claim against your profile and removes what is unsupported."),
    "_PersonaPick": ("Choose resume version", "Picks which resume version (IT Support, Web Developer...) fits the job."),
    "ScreeningAnswer": ("Answer a screening question", "Drafts one application question answer from your profile."),
    "ScreeningAnswers": ("Answer screening questions", "Drafts several application question answers in one call."),
    "JobExtract": ("Read a job posting", "Pulls company, title and description out of pasted text or an email."),
    "FollowupNote": ("Write follow-up line", "Writes one fresh line for a follow-up message."),
    "RewriteResult": ("Rewrite resume", "Rewrites the resume for clarity without adding facts."),
    "CoverRewriteResult": ("Rewrite cover letter", "Tightens the cover letter without adding facts."),
    "ReviewResult": ("Review resume against job", "Scores fit and lists gaps for a job."),
    "Ping": ("Engine test", "A short test call from the AI Engine view."),
    "NavigationAdvice": ("Choose next button (Chrome)", "On an application page, picks which Apply or Next control leads toward the form. Never submits."),
    "AnswerDraft": ("Draft a written answer (Chrome)", "Drafts a 'why this job' style answer only from your resume evidence."),
    "AnswerAudit": ("Check a drafted answer (Chrome)", "A second Hermes pass that rejects the draft if any claim isn't backed by your evidence."),
}


def describe(schema_name: str) -> tuple[str, str]:
    return TASKS.get(schema_name, (schema_name, ""))


@contextmanager
def job_context(company: str = "", title: str = ""):
    """Tag every AI call inside the block with the job it serves."""
    prev = getattr(_local, "job", "")
    _local.job = " · ".join(p for p in (company, title) if p)
    try:
        yield
    finally:
        _local.job = prev


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        lines = _FILE.read_text(encoding="utf-8").splitlines()[-_RECENT.maxlen:]
        for line in lines:
            try:
                _RECENT.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass


def _trim(text: str) -> str:
    text = text or ""
    if len(text) <= _PREVIEW:
        return text
    half = _PREVIEW // 2
    return text[:half] + f"\n\n[... {len(text) - _PREVIEW:,} characters not kept ...]\n\n" + text[-half:]


def record(*, schema: str, requested: str, used: str, seconds: float,
           status: str, error: str = "", fallback: str = "",
           input_tokens: int = 0, output_tokens: int = 0,
           system: str = "", user: str = "", response: str = "",
           keep_prompts: bool = True) -> dict:
    """Store one AI call. Never raises: logging must not break generation."""
    task, purpose = describe(schema)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "at": datetime.now().isoformat(timespec="seconds"),
        "task": task,
        "purpose": purpose,
        "schema": schema,
        "job": getattr(_local, "job", ""),
        "engine_requested": requested,
        "engine_used": used,
        "fallback": fallback,
        "status": status,
        "error": (error or "")[:800],
        "seconds": round(float(seconds), 2),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "prompt_chars": len(system or "") + len(user or ""),
    }
    if keep_prompts:
        entry["system_prompt"] = _trim(system)
        entry["user_prompt"] = _trim(user)
        entry["response"] = _trim(response)
    try:
        with _LOCK:
            _load()
            _RECENT.append(entry)
            # Test runs exercise the AI router with fake engines; keep those calls
            # out of the real log unless a test pointed _FILE somewhere else.
            if "unittest" in sys.modules and _FILE == _DEFAULT_FILE:
                return entry
            _FILE.parent.mkdir(parents=True, exist_ok=True)
            with _FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _rotate()
    except Exception:
        pass
    return entry


def _rotate() -> None:
    try:
        if _FILE.stat().st_size < 4_000_000:
            return
        lines = _FILE.read_text(encoding="utf-8").splitlines()[-_KEEP_FILE:]
        _FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


_SUMMARY_KEYS = ("id", "at", "task", "purpose", "schema", "job", "engine_requested",
                 "engine_used", "fallback", "status", "error", "seconds",
                 "input_tokens", "output_tokens", "prompt_chars")


def recent(limit: int = 100) -> list[dict]:
    """Newest first, without the prompt and reply bodies."""
    with _LOCK:
        _load()
        items = list(_RECENT)[-limit:]
    return [{k: e.get(k) for k in _SUMMARY_KEYS} | {"has_detail": "user_prompt" in e}
            for e in reversed(items)]


def get(entry_id: str) -> dict | None:
    with _LOCK:
        _load()
        return next((e for e in reversed(_RECENT) if e.get("id") == entry_id), None)


def summary() -> dict:
    """Counts for the status cards: today's calls, failures, fallbacks, average time."""
    today = datetime.now().date().isoformat()
    with _LOCK:
        _load()
        items = [e for e in _RECENT if str(e.get("at", "")).startswith(today)]
    ok = [e for e in items if e.get("status") == "ok"]
    by_engine: dict[str, int] = {}
    for e in items:
        by_engine[e.get("engine_used") or "?"] = by_engine.get(e.get("engine_used") or "?", 0) + 1
    return {
        "calls_today": len(items),
        "failed_today": sum(1 for e in items if e.get("status") != "ok"),
        "fallbacks_today": sum(1 for e in items if e.get("fallback")),
        "avg_seconds_today": round(sum(e.get("seconds", 0) for e in ok) / len(ok), 1) if ok else 0,
        "by_engine_today": by_engine,
        "last": recent(1)[0] if _RECENT else None,
    }


def clear() -> None:
    with _LOCK:
        _RECENT.clear()
        try:
            _FILE.unlink(missing_ok=True)
        except OSError:
            pass
