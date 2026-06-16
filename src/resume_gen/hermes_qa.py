"""Hermes-led QA — a semantic truthfulness audit of a generated résumé.

This is the MAIN QA judgment, run BEFORE the deterministic truth-guard
(`guard.enforce`), which always runs last as the hard backstop. Hermes is given the
candidate's real profile (the only source of truth) and the generated résumé, and
removes/softens any claim the profile does not support — catching subtle fabrications
the regex/profile-matching guard can miss. It never adds anything.

If Hermes is unavailable or the call fails, this is a no-op: the résumé passes through
unchanged and the deterministic guard still does its job. So QA quality improves when
Hermes is on, but the truth guarantee never depends on it.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from .config import settings
from .models import Resume
from .profile import profile_to_prompt_block


class HermesQAResult(BaseModel):
    """Hermes' audit: the corrected résumé + what it found unsupported."""

    unsupported_findings: list[str] = Field(
        default_factory=list,
        description="each résumé claim NOT supported by the profile, and how you handled it "
        "(removed / softened). Empty if everything checked out.",
    )
    resume: Resume = Field(description="the corrected résumé, same schema, unsupported claims fixed")


HERMES_QA_SYSTEM = """You are a strict TRUTH AUDITOR for a résumé. You are given the candidate's REAL
PROFILE (the only source of truth), the TARGET ROLE they are applying to, and a GENERATED RÉSUMÉ.
Your job is QA: find every claim in the résumé that is NOT supported by the profile, and FIX it.

Distinguish FRAMING from FABRICATION — this is the most important rule:
- FRAMING (KEEP IT): orienting the candidate's REAL skills and experience toward the TARGET ROLE — a
  role-relevant headline and a summary that leads with the profile-backed skills most relevant to the
  job. If the APPROVED FRAMING below is supported by the profile's real skills, KEEP that direction.
  NEVER neutralise a role-targeted headline/summary back into a generic or different profession when
  the profile's skills support the target role (e.g. don't turn a "Digital Marketing" framing into
  "Backend Developer" just because the profile also has backend work).
- FABRICATION (REMOVE IT): claiming an employer, job title, date, degree, certification, metric,
  percentage, count, team size, "N years of experience", or a TOOL or specific job DUTY the profile
  does not contain (e.g. "managed a YouTube channel", "ran paid ad campaigns", "grew audience 30%"
  when no such fact exists). Cut the invented specifics, keep the truthful role framing.

Other rules:
- The PROFILE is the sole source of truth for FACTS. Do NOT add anything new. Preserve schema/structure.
- Keep everything supported by the profile. Only remove/correct what isn't.

Return the corrected résumé (same schema) plus an `unsupported_findings` list naming what you fixed.
"""


def qa_resume(resume, profile, *, persona: dict | None = None, target=None,
              model: str | None = None, **kw) -> tuple[Resume, dict]:
    """Run the Hermes QA pass over `resume` against `profile`.

    `persona` (the selected role framing) and `target` (the job) are given to Hermes
    so it preserves legitimate role-targeting of the candidate's REAL skills instead
    of neutralising it back to the profile's dominant identity.

    Returns (corrected_resume, report). The report has `ran` plus either
    `unsupported_findings` (success) or `reason`/`error` (skipped/failed). Never raises:
    on any problem it returns the input résumé unchanged so the deterministic guard
    (the backstop) still runs.
    """
    from .llm import hermes_client

    base = resume if isinstance(resume, Resume) else Resume(**dict(resume or {}))
    if not (settings.hermes_qa and hermes_client.available()):
        return base, {"ran": False, "reason": "hermes_unavailable_or_disabled"}

    # Target role + the persona's truthful framing, so Hermes keeps the role
    # orientation (it only sees the profile otherwise, and reverts to backend).
    ctx = ""
    if target is not None:
        title = getattr(target, "title", "") or ""
        desc = (getattr(target, "description", "") or "")[:600]
        ctx += f"TARGET_ROLE: {title}\n"
        if desc:
            ctx += f"TARGET_ROLE_DESCRIPTION (for relevance only):\n{desc}\n"
    if persona:
        ctx += "APPROVED_FRAMING (persona-derived, truthful — preserve this DIRECTION):\n"
        if persona.get("headline"):
            ctx += f"  headline: {persona['headline']}\n"
        if persona.get("summary_seed"):
            ctx += f"  summary direction: {' '.join(persona['summary_seed'].split())}\n"
        if persona.get("foreground_skills"):
            ctx += f"  lead skills: {persona['foreground_skills']}\n"
    if ctx:
        ctx += "\n"

    user = (
        "CANDIDATE_PROFILE (the ONLY source of truth for FACTS):\n"
        + profile_to_prompt_block(profile) + "\n\n"
        + ctx
        + "GENERATED_RESUME (audit and fix — keep truthful role FRAMING, remove only FABRICATIONS):\n"
        + json.dumps(base.model_dump(), indent=2) + "\n"
    )

    from .llm import chat_structured

    try:
        out = chat_structured(HERMES_QA_SYSTEM, user, HermesQAResult,
                              model=model or settings.hermes_model, **kw)
        return out.resume, {"ran": True, "unsupported_findings": out.unsupported_findings}
    except Exception as e:
        return base, {"ran": False, "error": str(e)}
