"""Orchestration: master profile + target role -> validated resume / cover
letter / email objects, via Ollama."""

from __future__ import annotations

import re

from .humanize import humanize_answer, humanize_cover_letter, humanize_email
from .llm import chat_structured
from .models import (
    ApplicationEmail,
    CoverLetter,
    JobExtract,
    Resume,
    ScreeningAnswer,
    TargetRole,
)
from .personas import persona_directive
from .profile import load_profile, profile_to_prompt_block
from .prompts import (
    ANSWER_SYSTEM,
    COVER_LETTER_SYSTEM,
    EMAIL_PARSE_SYSTEM,
    EMAIL_SYSTEM,
    FOLLOWUP_SYSTEM,
    RESUME_SYSTEM,
    build_user_message,
)


def extract_job_from_email(text: str, *, model: str | None = None, **kw) -> JobExtract:
    """Parse a job-alert email (or pasted job text) into a structured posting."""
    user = "EMAIL / PASTED JOB TEXT:\n" + (text or "").strip() + "\n"
    return chat_structured(EMAIL_PARSE_SYSTEM, user, JobExtract, model=model, **kw)


def generate_answer(question: str, target: TargetRole | None = None, *, draft: str = "",
                    profile: dict | None = None, model: str | None = None,
                    max_words: int | None = None, **kw) -> str:
    """Answer one application screening question, grounded in the profile + job.
    If `draft` is given, the candidate's own answer is rephrased instead.
    `max_words` caps the answer length (overrides the prompt's default 35-80)."""
    profile = profile or load_profile()
    t = target or TargetRole(company="", title="", description="")
    role_block = (
        "TARGET_ROLE:\n"
        f"  company: {t.company}\n  title: {t.title}\n  location: {t.location}\n"
        f"  job_description: |\n    {(t.description or '').strip()}\n\n"
    )
    if draft.strip():
        # Rephrase mode: do NOT feed the full profile — local models will abandon the
        # user's story and substitute (or fabricate) a profile one. Keep it surgical.
        user = (
            role_block
            + "QUESTION:\n" + question.strip() + "\n\n"
            + "MY_DRAFT (rewrite THIS — keep its story and facts, only polish wording/flow):\n"
            + draft.strip() + "\n"
        )
    else:
        user = (
            "CANDIDATE_PROFILE:\n" + profile_to_prompt_block(profile) + "\n\n"
            + role_block
            + "QUESTION:\n" + question.strip() + "\n"
        )
    if max_words and max_words > 0:
        # This overrides rule 4's default length; the user message takes precedence.
        user += (
            f"\nLENGTH: Write about {max_words} words. This is a HARD MAXIMUM — do not "
            f"exceed {max_words} words. Answer the question directly and stop.\n"
        )
    text = chat_structured(ANSWER_SYSTEM, user, ScreeningAnswer, model=model, **kw).answer
    return humanize_answer(text)


def _context(profile: dict | None, target: TargetRole, persona: dict | None = None) -> str:
    profile = profile or load_profile()
    return build_user_message(
        profile_to_prompt_block(profile), target, persona_directive(persona)
    )


def generate_resume(target: TargetRole, profile: dict | None = None, persona: dict | None = None,
                    *, skills_focus: list[str] | None = None, **kw) -> Resume:
    user = _context(profile, target, persona)
    if skills_focus:
        # Per-run emphasis (e.g. from a repeatable role). Re-orders/surfaces these
        # areas; it must NOT invent — the truth-guard strips anything ungrounded.
        focus = ", ".join(s for s in skills_focus if s)
        user += (
            "\n\nSKILLS EMPHASIS: For THIS resume, prioritise and surface these areas "
            f"where the candidate genuinely has them (from CANDIDATE_PROFILE): {focus}. "
            "Order the skills list to lead with them and pick experience bullets that "
            "showcase them. Do NOT add any skill, tool, or claim the candidate does not "
            "actually have — only re-order and emphasise real ones."
        )
    return chat_structured(RESUME_SYSTEM, user, Resume, **kw)


def generate_cover_letter(target: TargetRole, profile: dict | None = None, persona: dict | None = None, **kw) -> CoverLetter:
    user = _context(profile, target, persona)
    # A touch more warmth than the resume, but NOT so hot it fabricates (0.7 was
    # inventing fake names, team sizes, and metrics).
    kw.setdefault("temperature", 0.35)
    cl = chat_structured(COVER_LETTER_SYSTEM, user, CoverLetter, **kw)
    return humanize_cover_letter(cl)


def _email_signature(profile: dict | None) -> str:
    """Build a deterministic, truth-only sign-off from the profile's contact
    block: 'Best, <name>' then email, phone, and the portfolio/website link.
    The model is told NOT to add its own sign-off, so this is the single source."""
    profile = profile or {}
    contact = profile.get("contact", {}) or {}
    name = (contact.get("email_signoff_name")
            or profile.get("preferred_name")
            or profile.get("full_name") or "").strip()
    detail: list[str] = []
    if contact.get("email"):
        detail.append(str(contact["email"]).strip())
    if contact.get("phone"):
        detail.append(str(contact["phone"]).strip())
    # Prefer a portfolio/website/K2-style link over LinkedIn for the sign-off.
    links = contact.get("links") or []
    chosen = None
    for l in links:
        label = (l.get("label") or "").lower()
        if any(k in label for k in ("k2", "portfolio", "website", "site")):
            chosen = l
            break
    if chosen and chosen.get("url"):
        label = (chosen.get("label") or "Portfolio").strip()
        detail.append(f"{label}: {chosen['url']}")
    # One tight letterhead block: closing on its own line, name beneath it, then
    # each contact detail stacked directly under the name (no blank-line gap), so
    # it renders as a proper signature/letterhead rather than a run-on line.
    signoff = ["Best,", name] if name else ["Best,"]
    return "\n".join(signoff + detail)


def _strip_model_closing(body: str) -> str:
    """Remove any attachment line, thank-you line, and sign-off the model wrote
    anyway, so we can re-add them deterministically on their own lines. Newlines
    in the remaining body are preserved (only runs of spaces/tabs are squeezed)."""
    if not body:
        return body
    t = body
    # Trailing sign-off block: "Best, <name>" / "Regards" ... to the end.
    t = re.sub(r"\n*\s*(best regards|best wishes|best|kind regards|warm regards|"
               r"regards|sincerely|cheers|yours (?:truly|sincerely))\b[\s\S]*$",
               "", t, flags=re.I)
    # Attachment + thank-you boilerplate sentences (re-added deterministically).
    t = re.sub(r"\s*\b(i'?ve attached|i have attached|please find attached|"
               r"attached (?:are|is|you'?ll find|please find))[^.!?]*[.!?]",
               "", t, flags=re.I)
    t = re.sub(r"\s*\bthank you[^.!?]*[.!?]", "", t, flags=re.I)
    t = re.sub(r"\s*\bthanks[^.!?]*[.!?]", "", t, flags=re.I)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def generate_email(target: TargetRole, profile: dict | None = None, persona: dict | None = None, **kw) -> ApplicationEmail:
    profile = profile or load_profile()
    user = _context(profile, target, persona)
    email = chat_structured(EMAIL_SYSTEM, user, ApplicationEmail, **kw)
    email = humanize_email(email)
    # Assemble the email deterministically so the closing + signature always land
    # on their own lines, regardless of how the (local) model formatted the body.
    core = _strip_model_closing(email.body or "")
    closing = ("I've attached my resume and cover letter for your review.\n\n"
               "Thank you for your time and consideration.")
    sig = _email_signature(profile)
    email.body = "\n\n".join(p for p in (core, closing, sig) if p)
    return email


def generate_followup_email(target: TargetRole, profile: dict | None = None,
                            persona: dict | None = None, **kw) -> ApplicationEmail:
    """A short, polite follow-up to a job application that was already sent. Same
    deterministic signature + closing discipline as generate_email, minus the
    'attached resume' line (the follow-up doesn't re-attach)."""
    profile = profile or load_profile()
    user = _context(profile, target, persona)
    email = chat_structured(FOLLOWUP_SYSTEM, user, ApplicationEmail, **kw)
    email = humanize_email(email)
    name = ((profile.get("full_name") or profile.get("preferred_name") or "")).strip()
    title = (target.title or "").strip()
    email.subject = (f"Following up: {title} - {name}".strip(" -")
                     if (title or name) else (email.subject or "Following up"))
    core = _strip_model_closing(email.body or "")
    sig = _email_signature(profile)
    email.body = "\n\n".join(p for p in (core, "Thank you for your time.", sig) if p)
    return email


def generate_all(target: TargetRole, profile: dict | None = None, persona: dict | None = None,
                 *, resume_model: str | None = None, letters_model: str | None = None,
                 skills_focus: list[str] | None = None, **kw):
    """Generate all three artifacts, reusing one loaded profile + persona.

    `resume_model` drives the résumé; `letters_model` drives the cover letter +
    email. This lets callers split the work across engines (e.g. the résumé on
    local Ollama, the prose letters on the Hermes agent). Either may be None to
    fall back to the Ollama default. `skills_focus` (résumé only) re-orders and
    emphasises specific real skills for this run."""
    profile = profile or load_profile()
    return {
        "resume": generate_resume(target, profile, persona, model=resume_model,
                                  skills_focus=skills_focus, **kw),
        "cover_letter": generate_cover_letter(target, profile, persona, model=letters_model, **kw),
        "email": generate_email(target, profile, persona, model=letters_model, **kw),
    }
