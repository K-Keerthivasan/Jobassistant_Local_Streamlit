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
PROFILE (the only source of truth) and a GENERATED RÉSUMÉ. Your job is QA: find every claim in the
résumé that is NOT supported by the profile, and FIX it.

Rules:
- The PROFILE is the sole source of truth. Anything in the résumé not grounded in it is a fabrication.
- Remove or soften any unsupported: employer, job title, date, degree, institution, certification,
  skill, tool, technology, metric, percentage, dollar amount, team size, or "N years of experience".
- Do NOT add anything new. Do NOT invent or embellish. Only remove/correct to match the profile.
- Keep everything that IS supported by the profile. Preserve the structure, ordering, and schema.
- A claim is supported only if the profile clearly backs it — when in doubt, soften or drop it.

Return the corrected résumé (same schema) plus an `unsupported_findings` list naming what you fixed.
"""


def qa_resume(resume, profile, *, model: str | None = None, **kw) -> tuple[Resume, dict]:
    """Run the Hermes QA pass over `resume` against `profile`.

    Returns (corrected_resume, report). The report has `ran` plus either
    `unsupported_findings` (success) or `reason`/`error` (skipped/failed). Never raises:
    on any problem it returns the input résumé unchanged so the deterministic guard
    (the backstop) still runs.
    """
    from .llm import hermes_client

    base = resume if isinstance(resume, Resume) else Resume(**dict(resume or {}))
    if not (settings.hermes_qa and hermes_client.available()):
        return base, {"ran": False, "reason": "hermes_unavailable_or_disabled"}

    user = (
        "CANDIDATE_PROFILE (the ONLY source of truth):\n"
        + profile_to_prompt_block(profile) + "\n\n"
        + "GENERATED_RESUME (audit and fix this — remove anything the profile does not support):\n"
        + json.dumps(base.model_dump(), indent=2) + "\n"
    )

    from .llm import chat_structured

    try:
        out = chat_structured(HERMES_QA_SYSTEM, user, HermesQAResult,
                              model=model or settings.hermes_model, **kw)
        return out.resume, {"ran": True, "unsupported_findings": out.unsupported_findings}
    except Exception as e:
        return base, {"ran": False, "error": str(e)}
