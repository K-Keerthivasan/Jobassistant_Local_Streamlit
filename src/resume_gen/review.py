"""Hermes-powered resume review.

This is a SEPARATE step from generation. Ollama (or whichever engine) generates
the resume; the deterministic truth-guard repairs identity/skills/metrics. This
module then asks the **Hermes agent** to *review* the finished resume against the
job description with its own LLM — a recruiter-style critique (alignment, gaps,
missing ATS keywords, actionable suggestions, and possible overclaims). It never
rewrites the resume; it only returns structured feedback.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .config import settings
from .models import CoverLetter, Resume, TargetRole


class ResumeReview(BaseModel):
    """Structured recruiter-style critique of one resume against one job."""

    overall_score: int = Field(description="0-100 overall quality for THIS role")
    jd_match_score: int = Field(description="0-100 how well the resume matches the job description")
    verdict: str = Field(description="one-sentence bottom line")
    strengths: list[str] = Field(default_factory=list, description="what works well, most important first")
    weaknesses: list[str] = Field(default_factory=list, description="what holds it back")
    missing_keywords: list[str] = Field(
        default_factory=list,
        description="important terms/skills from the job description NOT present in the resume",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="concrete, truthful edits (reorder/emphasise/clarify) — never invent facts",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="statements that look unsupported or overclaimed and should be verified",
    )
    rewrite_recommended: bool = Field(
        default=False,
        description="true ONLY if a rewrite would MATERIALLY improve this resume for the role "
        "through better wording, ordering, tightening, or surfacing skills/keywords the "
        "candidate ALREADY has. false if the resume is already strong, or if the only gaps "
        "are genuinely missing experience that cannot be fixed without inventing facts.",
    )


REVIEW_SYSTEM = """You are a senior technical recruiter and ATS expert. You REVIEW a finished resume
against one specific job description. You do NOT rewrite the resume — you return a structured critique.

You are given the TARGET_ROLE (company, title, job description) and the RESUME (already generated).

Judge:
- jd_match_score: how well the resume's skills/experience line up with what the job actually asks for.
- overall_score: recruiter-ready quality for THIS role (clarity, impact, ATS-friendliness, focus).
- strengths / weaknesses: specific, tied to the actual content — not generic platitudes.
- missing_keywords: concrete skills/tools/terms the job description emphasises that the resume does
  not surface. Only list things that would be legitimate to add IF the candidate truly has them.
- suggestions: actionable, TRUTHFUL edits — reorder, re-emphasise, tighten, surface a relevant bullet.
  NEVER suggest inventing employers, dates, titles, degrees, certifications, metrics, or skills the
  candidate does not have. If a gap is real, say so plainly rather than papering over it.
- risk_flags: any line that reads as an unsupported claim or possible exaggeration the candidate
  should double-check before sending.
- rewrite_recommended: set true ONLY when a rewrite (rewording, reordering, tightening, surfacing
  skills the candidate already has) would materially improve this resume for the role. Set false
  if it is already strong, or if the only weaknesses are missing real experience — a rewrite must
  never invent facts to close those, so it would not help.

Be concise and concrete. Cap each list at about 6 items. Scores are integers 0-100.
"""


def _resume_block(resume: Resume | dict[str, Any]) -> str:
    r = resume.model_dump() if isinstance(resume, Resume) else dict(resume or {})
    lines: list[str] = []
    if r.get("headline"):
        lines.append(f"HEADLINE: {r['headline']}")
    if r.get("summary"):
        lines.append(f"SUMMARY: {r['summary']}")
    if r.get("skills"):
        lines.append("SKILLS: " + ", ".join(map(str, r["skills"])))
    for e in r.get("experience", []) or []:
        head = f"{e.get('role','')} @ {e.get('company','')}".strip(" @")
        when = " ".join(x for x in (e.get("start", ""), e.get("end", "")) if x)
        lines.append(f"\nEXPERIENCE: {head}{(' (' + when + ')') if when else ''}")
        for b in e.get("bullets", []) or []:
            lines.append(f"  - {b}")
    edu = r.get("education", []) or []
    if edu:
        lines.append("\nEDUCATION: " + "; ".join(
            f"{x.get('credential','')} — {x.get('institution','')} {x.get('year','')}".strip()
            for x in edu
        ))
    if r.get("certifications"):
        lines.append("CERTIFICATIONS: " + ", ".join(map(str, r["certifications"])))
    if r.get("keywordsMatched"):
        lines.append("KEYWORDS_MATCHED (resume's own claim): " + ", ".join(map(str, r["keywordsMatched"])))
    return "\n".join(lines).strip()


def review_resume(
    resume: Resume | dict[str, Any],
    target: TargetRole | dict[str, Any],
    *,
    model: str | None = None,
    **kw,
) -> ResumeReview:
    """Have Hermes review `resume` against `target`. Defaults to the Hermes engine
    (the whole point of this feature); pass `model` to override."""
    t = target if isinstance(target, TargetRole) else TargetRole(**dict(target or {}))
    user = (
        "TARGET_ROLE:\n"
        f"  company: {t.company}\n  title: {t.title}\n  location: {t.location}\n"
        f"  job_description: |\n    {(t.description or '').strip()}\n\n"
        "RESUME (review this — do not rewrite it):\n"
        f"{_resume_block(resume)}\n"
    )
    # Route through the engine layer; default to Hermes so this stays an agent task.
    from .llm import chat_structured

    return chat_structured(REVIEW_SYSTEM, user, ResumeReview,
                           model=model or settings.hermes_model, **kw)


class RewriteResult(BaseModel):
    """A truth-preserving rewrite of one resume, plus a note of what changed."""

    changes: list[str] = Field(
        default_factory=list,
        description="short bullets: what you changed and why — wording/ordering/keyword "
        "surfacing only. Each item must be a presentation change, never a new fact.",
    )
    resume: Resume = Field(description="the rewritten resume, same schema as the input")


REWRITE_SYSTEM = """You REWRITE a resume to maximise alignment with one specific job — for clarity,
impact, ordering, and ATS keyword surfacing. You are NOT a fact generator.

ABSOLUTE TRUTH RULES (breaking any of these is a failure):
- Keep EVERY fact exactly as given: employers, job titles, dates, locations, education, degrees,
  institutions, graduation years, certifications, and any numbers/metrics. Do not add, remove,
  inflate, or invent ANY of these.
- Do NOT add skills, tools, or technologies the original resume does not already contain.
- Do NOT add metrics, percentages, dollar amounts, team sizes, or "N years of experience" that are
  not already present.
- You MAY: reword bullets for impact and clarity, reorder bullets/skills to put the most
  role-relevant first, tighten the headline/summary, and surface keywords from the job description
  ONLY where the candidate's existing facts already support them.
- If a job keyword is not supported by the candidate's real experience, leave it out — never fake it.

Output the rewritten resume in the SAME schema as the input, plus a short `changes` list describing
what you changed (presentation only). If you cannot improve it without inventing facts, return the
resume essentially unchanged with an empty/short `changes` list.
"""


def rewrite_resume(
    resume: Resume | dict[str, Any],
    target: TargetRole | dict[str, Any],
    *,
    review: ResumeReview | dict[str, Any] | None = None,
    model: str | None = None,
    **kw,
) -> RewriteResult:
    """Have Hermes rewrite `resume` for `target`, preserving every fact (the caller
    MUST still run the deterministic truth-guard on the result). Optionally feeds the
    review's suggestions + missing keywords as guidance."""
    t = target if isinstance(target, TargetRole) else TargetRole(**dict(target or {}))
    original = resume.model_dump() if isinstance(resume, Resume) else dict(resume or {})

    guidance = ""
    if review is not None:
        r = review.model_dump() if isinstance(review, ResumeReview) else dict(review)
        if r.get("missing_keywords"):
            guidance += ("\nKEYWORDS to surface ONLY where the candidate's existing facts already "
                         "support them: " + ", ".join(map(str, r["missing_keywords"])))
        if r.get("suggestions"):
            guidance += "\nREVIEW SUGGESTIONS to act on (truthfully):\n" + "\n".join(
                f"- {s}" for s in r["suggestions"])

    user = (
        "TARGET_ROLE:\n"
        f"  company: {t.company}\n  title: {t.title}\n  location: {t.location}\n"
        f"  job_description: |\n    {(t.description or '').strip()}\n\n"
        "ORIGINAL_RESUME (rewrite THIS — keep every fact; improve only presentation):\n"
        f"{json.dumps(original, indent=2)}\n"
        + guidance + "\n"
    )
    from .llm import chat_structured

    return chat_structured(REWRITE_SYSTEM, user, RewriteResult,
                           model=model or settings.hermes_model, **kw)


# --------------------------------------------------------------------------- #
# Cover letter — review + rewrite (mirrors the résumé flow)
# --------------------------------------------------------------------------- #

COVER_REVIEW_SYSTEM = """You are a senior technical recruiter. You REVIEW a finished COVER LETTER against
one specific job description. You do NOT rewrite it here — you return a structured critique using the
same schema as a resume review.

Given the TARGET_ROLE and the COVER_LETTER, judge:
- jd_match_score: how well the letter speaks to what THIS job asks for.
- overall_score: recruiter-ready quality — opening hook, specificity, relevance, concision, a clear
  ask, and professional tone. A strong cover letter is concise (fits ONE page) and never generic.
- strengths / weaknesses: specific to the actual text, not platitudes.
- missing_keywords: themes/skills the job stresses that the letter never touches (only ones the
  candidate could truthfully speak to).
- suggestions: actionable, TRUTHFUL edits — tighten, lead with impact, connect to the role. NEVER
  suggest inventing employers, dates, metrics, or skills.
- risk_flags: any sentence that reads as an unsupported claim or exaggeration.
- rewrite_recommended: true ONLY if a rewrite would materially improve the letter (clarity, focus,
  concision to one page, JD alignment) using only truthful content. False if it's already strong or
  the gaps are missing real experience.

Be concise. Cap each list at ~6 items. Scores are integers 0-100.
"""


def _cover_block(cover: CoverLetter | dict[str, Any]) -> str:
    c = cover.model_dump() if isinstance(cover, CoverLetter) else dict(cover or {})
    lines = [
        f"GREETING: {c.get('greeting','')}",
        "BODY:",
        *[f"  {p}" for p in (c.get("body") or [])],
        f"SIGN-OFF: {c.get('signOff','')}",
        f"SIGNATURE: {c.get('signature','')}",
    ]
    return "\n".join(lines).strip()


def review_cover_letter(
    cover: CoverLetter | dict[str, Any],
    target: TargetRole | dict[str, Any],
    *,
    model: str | None = None,
    **kw,
) -> ResumeReview:
    """Have Hermes critique a cover letter against the job (reuses the ResumeReview
    schema so the UI renders it the same way)."""
    t = target if isinstance(target, TargetRole) else TargetRole(**dict(target or {}))
    user = (
        "TARGET_ROLE:\n"
        f"  company: {t.company}\n  title: {t.title}\n  location: {t.location}\n"
        f"  job_description: |\n    {(t.description or '').strip()}\n\n"
        "COVER_LETTER (review this — do not rewrite it):\n"
        f"{_cover_block(cover)}\n"
    )
    from .llm import chat_structured

    return chat_structured(COVER_REVIEW_SYSTEM, user, ResumeReview,
                           model=model or settings.hermes_model, **kw)


class CoverRewriteResult(BaseModel):
    """A truth-preserving rewrite of one cover letter, plus a note of what changed."""

    changes: list[str] = Field(
        default_factory=list,
        description="short bullets: what you changed and why — wording/structure/concision only, "
        "never a new fact.",
    )
    cover_letter: CoverLetter = Field(description="the rewritten cover letter, same schema as input")


COVER_REWRITE_SYSTEM = """You REWRITE a cover letter to better fit one specific job — sharper opening,
clearer relevance, tighter prose that fits ONE page, professional tone. You are NOT a fact generator.

ABSOLUTE TRUTH RULES (breaking any is a failure):
- Keep EVERY fact: employer names, titles, dates, education, certifications, and any numbers/metrics.
  Do not add, inflate, or invent ANY of these.
- Do NOT add skills, tools, achievements, or "N years of experience" the original does not contain.
- You MAY reword, reorder, tighten, sharpen the hook, and connect existing facts to the job's needs.
- Keep the same person: same name in the signature, a professional greeting and sign-off.
- Aim for 3–4 concise paragraphs that fit on a single page.

Output the rewritten cover letter in the SAME schema as the input, plus a short `changes` list (what
you changed — presentation only). If you cannot improve it without inventing facts, return it
essentially unchanged with a short/empty `changes` list.
"""


def rewrite_cover_letter(
    cover: CoverLetter | dict[str, Any],
    target: TargetRole | dict[str, Any],
    *,
    review: ResumeReview | dict[str, Any] | None = None,
    model: str | None = None,
    **kw,
) -> CoverRewriteResult:
    """Have Hermes rewrite a cover letter for the role, preserving every fact (the
    caller MUST still run the deterministic cover-letter truth-guard on the result)."""
    t = target if isinstance(target, TargetRole) else TargetRole(**dict(target or {}))
    original = cover.model_dump() if isinstance(cover, CoverLetter) else dict(cover or {})

    guidance = ""
    if review is not None:
        r = review.model_dump() if isinstance(review, ResumeReview) else dict(review)
        if r.get("suggestions"):
            guidance += "\nREVIEW SUGGESTIONS to act on (truthfully):\n" + "\n".join(
                f"- {s}" for s in r["suggestions"])

    user = (
        "TARGET_ROLE:\n"
        f"  company: {t.company}\n  title: {t.title}\n  location: {t.location}\n"
        f"  job_description: |\n    {(t.description or '').strip()}\n\n"
        "ORIGINAL_COVER_LETTER (rewrite THIS — keep every fact; improve only presentation):\n"
        f"{json.dumps(original, indent=2)}\n"
        + guidance + "\n"
    )
    from .llm import chat_structured

    return chat_structured(COVER_REWRITE_SYSTEM, user, CoverRewriteResult,
                           model=model or settings.hermes_model, **kw)
