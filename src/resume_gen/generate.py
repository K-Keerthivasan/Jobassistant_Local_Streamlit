"""Orchestration: master profile + target role -> validated resume / cover
letter / email objects, via Ollama."""

from __future__ import annotations

from .humanize import humanize_cover_letter, humanize_email
from .llm.ollama_client import chat_structured
from .models import ApplicationEmail, CoverLetter, Resume, TargetRole
from .profile import load_profile, profile_to_prompt_block
from .prompts import (
    COVER_LETTER_SYSTEM,
    EMAIL_SYSTEM,
    RESUME_SYSTEM,
    build_user_message,
)


def _context(profile: dict | None, target: TargetRole) -> str:
    profile = profile or load_profile()
    return build_user_message(profile_to_prompt_block(profile), target)


def generate_resume(target: TargetRole, profile: dict | None = None, **kw) -> Resume:
    user = _context(profile, target)
    return chat_structured(RESUME_SYSTEM, user, Resume, **kw)


def generate_cover_letter(target: TargetRole, profile: dict | None = None, **kw) -> CoverLetter:
    user = _context(profile, target)
    # A touch more warmth/variation than the resume, so letters don't feel templated.
    kw.setdefault("temperature", 0.7)
    cl = chat_structured(COVER_LETTER_SYSTEM, user, CoverLetter, **kw)
    return humanize_cover_letter(cl)


def generate_email(target: TargetRole, profile: dict | None = None, **kw) -> ApplicationEmail:
    user = _context(profile, target)
    email = chat_structured(EMAIL_SYSTEM, user, ApplicationEmail, **kw)
    return humanize_email(email)


def generate_all(target: TargetRole, profile: dict | None = None, **kw):
    """Generate all three artifacts, reusing one loaded profile."""
    profile = profile or load_profile()
    return {
        "resume": generate_resume(target, profile, **kw),
        "cover_letter": generate_cover_letter(target, profile, **kw),
        "email": generate_email(target, profile, **kw),
    }
