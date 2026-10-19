"""Integration for the regular-Chrome application engine (no generation or guessing)."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from resume_gen.intake import apply_sessions, runs, store

router = APIRouter(prefix="/application-engine")
ROOT = Path(__file__).resolve().parents[1]
_profile_lock = threading.Lock()
SENSITIVE = re.compile(r"password|passcode|one.time|captcha|consent|agree|certify|attest|privacy|terms|marketing|sms|talent.pool|disabilit|veteran|gender|race|ethnic|sexual|pronoun|demographic|indigenous|religion|date.of.birth", re.I)


def local_only(request: Request):
    if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "Application engine integration is loopback-only.")
    origin = request.headers.get("origin")
    if origin and origin != "http://127.0.0.1:8088":
        raise HTTPException(403, "Cross-origin integration request refused.")


class Prepare(BaseModel):
    job_key: str
    run_id: str


@router.post("/prepare")
def prepare(req: Prepare, request: Request):
    local_only(request)
    from resume_gen.automation import autoapply

    job = store.get_job(req.job_key)
    run = runs.get_run(req.run_id)
    if not job or job.applied or not run:
        raise HTTPException(400, "An unapplied saved job and an existing generated run are required.")
    # Match the run through Studio's own job linkage before materializing documents.
    linked = autoapply.candidates(limit=10000, include_attempted=True)
    if not any(r.get("key_id") == req.job_key and r.get("run_id") == req.run_id for r in linked):
        raise HTTPException(400, "The run must belong to this job's generated application.")
    return autoapply.prepare(job_url=job.apply_url, company=job.company, title=job.title,
                             run_id=req.run_id, fields=[], regenerate=False)


class Observed(BaseModel):
    snapshot: dict
    documents: list[dict]
    filled: list[dict] = Field(default_factory=list)
    engine_id: str
    review_hash: str


@router.get("/{session_id}/resume-history")
def resume_history(session_id: str, request: Request):
    """Use the very same generated structured resume that renders the uploaded PDF."""
    local_only(request)
    session = apply_sessions.get_session(session_id)
    if not session or session.get("status") != "prepared":
        raise HTTPException(409, "A prepared session is required.")
    run = runs.get_run(session.get("run_id", ""))
    resume = (run or {}).get("resume") or {}
    return {"experience": resume.get("experience", []), "education": resume.get("education", [])}


@router.get("/{session_id}/answer-context")
def answer_context(session_id: str, request: Request):
    local_only(request)
    session = apply_sessions.get_session(session_id)
    if not session or session.get("status") != "prepared":
        raise HTTPException(409, "A prepared session is required.")
    run = runs.get_run(session.get("run_id", ""))
    job = store.get_job(session.get("job_key", ""))
    if not run or not job or job.applied:
        raise HTTPException(409, "An unapplied job and its generated resume are required.")
    resume = run.get("resume") or {}
    # No credentials, browser state, contact details or unrelated application data.
    return {"company": session.get("company"), "title": session.get("title"),
            "description": job.description,
            "resume": {key: resume.get(key, []) for key in
                       ("summaryPoints", "experience", "education", "skills", "certifications")}}


@router.get("/{session_id}/validate")
def validate_session(session_id: str, request: Request):
    local_only(request)
    session = apply_sessions.get_session(session_id)
    job = store.get_job(session.get("job_key", "")) if session else None
    if not session or session.get("status") != "prepared" or not job or job.applied or job.status in {"applied", "sent"}:
        raise HTTPException(409, "A prepared session for a saved, unapplied job is required.")
    return session


@router.post("/{session_id}/snapshot")
def snapshot(session_id: str, req: Observed, request: Request):
    local_only(request)
    from resume_gen.automation import autoapply

    session = apply_sessions.get_session(session_id)
    if not session or session.get("status") != "prepared":
        raise HTTPException(409, "A prepared, unapproved session is required.")
    observed_host = urlsplit(req.snapshot.get("url", "")).hostname
    if not observed_host:
        raise HTTPException(400, "Observed employer URL is required.")
    fields = req.snapshot.get("fields", [])
    if any(SENSITIVE.search(str(f.get("label", ""))) and f.get("type") == "password" for f in fields):
        raise HTTPException(400, "Credential fields must never be recorded.")
    session["standard_fields"] = [
        {"label": f.get("label", ""), "selector": f.get("selector", ""),
         "value": f.get("value", ""), "profile_key": "observed_in_chrome"}
        for f in fields if f.get("value") and not SENSITIVE.search(f.get("label", ""))
    ]
    session["screening_answers"] = []  # Observed manual values are not reusable approvals.
    session["unfilled_fields"] = [f for f in fields if not f.get("value") and not f.get("files")]
    session["warnings"] = req.snapshot.get("blockers", [])
    session["browser_evidence"] = req.model_dump()
    session["summary"] = autoapply.build_summary(session)
    apply_sessions.save_session(session)
    return {"session_id": session_id, "saved": True, "summary": session["summary"]}


class ConfirmedAnswer(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=20000)
    confirmed: bool
    reuse: bool
    session_id: str | None = None


@router.post("/answers")
def save_answer(req: ConfirmedAnswer, request: Request):
    local_only(request)
    if not req.confirmed or SENSITIVE.search(req.question):
        raise HTTPException(400, "Only user-confirmed non-sensitive answers can be saved.")
    if not req.reuse and not req.session_id:
        return {"saved": False, "reason": "Reuse was not authorized."}
    if req.session_id and not apply_sessions.get_session(req.session_id):
        raise HTTPException(400, "An existing application session is required.")
    profile_path = ROOT / "data" / "apply_profile.json"
    with _profile_lock:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        answers = profile.setdefault("commonAnswers", {}) if req.reuse else profile.setdefault("applicationAnswers", {}).setdefault(req.session_id, {})
        answers[req.question] = req.answer
        if req.reuse:
            profile.setdefault('blankAnswers', {}).pop(req.question, None)
        if req.session_id:
            profile.setdefault('applicationBlankAnswers', {}).setdefault(req.session_id, {})[req.question] = False
        provenance_key = req.question if req.reuse else f"{req.session_id}:{req.question}"
        profile.setdefault("answerProvenance", {})[provenance_key] = {
            "originalQuestion": req.question, "normalizedQuestion": " ".join(req.question.casefold().split()),
            "source": "user_confirmed", "confirmedAt": datetime.now(timezone.utc).isoformat(),
            "reuseAllowed": req.reuse, "sessionId": req.session_id, "confidence": 1.0, "dataType": "string",
        }
        temporary = profile_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        temporary.replace(profile_path)
    return {"saved": True}


class BlankChoice(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str
    confirmed: Literal[True]
    reuse: bool = False


@router.post('/blank-answer')
def save_blank_choice(req: BlankChoice, request: Request):
    local_only(request)
    if SENSITIVE.search(req.question) or not apply_sessions.get_session(req.session_id):
        raise HTTPException(400, 'An existing session and non-sensitive optional question are required.')
    profile_path = ROOT / 'data' / 'apply_profile.json'
    with _profile_lock:
        profile = json.loads(profile_path.read_text(encoding='utf-8'))
        blanks = profile.setdefault('blankAnswers', {}) if req.reuse else profile.setdefault('applicationBlankAnswers', {}).setdefault(req.session_id, {})
        blanks[req.question] = True
        temporary = profile_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temporary.replace(profile_path)
    return {'saved': True}


class ConfirmedFact(BaseModel):
    key: Literal['firstName', 'lastName', 'fullName', 'preferredName', 'middleName', 'homePhone', 'omitGpa', 'omitOptionalSupervisor', 'email', 'phone',
                 'address', 'city', 'province', 'country', 'postalCode', 'linkedin', 'portfolio',
                 'github', 'workAuthorization', 'requiresSponsorship', 'experienceYears',
                 'education', 'salaryExpectation', 'availableStartDate', 'noticePeriod',
                 'willingToRelocate', 'technicalSkills', 'certifications', 'employmentHistory',
                 'educationHistory']
    value: str | bool | list[str] | list[dict[str, str]]
    confirmed: Literal[True]


@router.post('/profile-fact')
def save_fact(req: ConfirmedFact, request: Request):
    local_only(request)
    if isinstance(req.value, list) and any(
        isinstance(item, dict) and any(SENSITIVE.search(key) for key in item)
        for item in req.value
    ):
        raise HTTPException(400, 'Credential and sensitive-choice fields cannot be stored in history facts.')
    profile_path = ROOT / 'data' / 'apply_profile.json'
    with _profile_lock:
        profile = json.loads(profile_path.read_text(encoding='utf-8'))
        previous = profile.get(req.key)
        profile[req.key] = req.value
        profile.setdefault('factProvenance', {})[req.key] = {
            'source': 'user_confirmed', 'confirmedAt': datetime.now(timezone.utc).isoformat(),
            **({'previousValue': previous} if previous is not None and previous != req.value else {}),
        }
        temporary = profile_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temporary.replace(profile_path)
    return {'saved': True}
