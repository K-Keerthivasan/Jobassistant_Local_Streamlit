"""Orchestration: master profile + target role -> validated resume / cover
letter / email objects, via Ollama."""

from __future__ import annotations

import re

from .humanize import humanize_answer, humanize_cover_letter, humanize_email
from .llm import chat_structured
from .models import (
    ApplicationEmail,
    CoverLetter,
    EmailHook,
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
    EMAIL_HOOK_SYSTEM,
    EMAIL_PARSE_SYSTEM,
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


# --------------------------------------------------------------------------- #
# Application / follow-up emails — assembled from a FIXED template so the format
# is always consistent; only the role-specific "hook" line is model-generated.
# Everything else (greeting, opener, work links, sign-off) is deterministic and
# truth-only, pulled from the profile. No em dashes (humanize_email strips them).
# --------------------------------------------------------------------------- #
_HOOK_FALLBACK = (
    "I have spent the last few years running real client projects end to end, from the "
    "first brief to the thing that actually goes live, and I move fast without dropping quality."
)


def _signoff_name(profile: dict) -> str:
    contact = profile.get("contact", {}) or {}
    return (contact.get("email_signoff_name")
            or profile.get("preferred_name")
            or profile.get("full_name") or "").strip()


def _clean_url(url: str) -> str:
    """Display form of a URL: drop the scheme, www., and trailing slash."""
    u = re.sub(r"^https?://", "", (url or "").strip(), flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I)
    return u.rstrip("/")


def _profile_links(profile: dict) -> dict:
    """Resolve the candidate's portfolio / K2 / LinkedIn display URLs from the
    profile's contact.links (matched by label, scheme stripped for display)."""
    out = {"portfolio": "", "k2": "", "linkedin": ""}
    for l in (profile.get("contact", {}) or {}).get("links", []) or []:
        label, url = (l.get("label") or "").lower(), (l.get("url") or "")
        if not url:
            continue
        if "linkedin" in label:
            out["linkedin"] = _clean_url(url)
        elif "k2" in label:
            out["k2"] = _clean_url(url)
        elif any(k in label for k in ("portfolio", "website", "site", "dev")):
            out["portfolio"] = _clean_url(url)
    return out


def _portfolio_line(profile: dict, attached: bool = True) -> str:
    """Work-links sentence. `attached=True` (application email) leads with the
    resume attachment; `attached=False` (HR outreach with no attachment) doesn't."""
    L = _profile_links(profile)
    parts = []
    if L["portfolio"]:
        parts.append(f"my portfolio is at {L['portfolio']}")
    if L["k2"]:
        parts.append(f"a few client builds live at {L['k2']}")
    if not parts:
        return "My resume is attached." if attached else ""
    if attached:
        return "My resume is attached. If it is easier to just see the work, " + " and ".join(parts) + "."
    return "If you would like to see the work, " + " and ".join(parts) + "."


def _worklink_line(profile: dict) -> str:
    return _portfolio_line(profile, attached=True)


def _signoff_block(profile: dict, closing: str) -> str:
    """Letterhead sign-off: closing line, name, then 'phone | linkedin'."""
    L = _profile_links(profile)
    contact = profile.get("contact", {}) or {}
    name = _signoff_name(profile)
    line = " | ".join(p for p in [(contact.get("phone") or "").strip(), L["linkedin"]] if p)
    return "\n".join(p for p in (closing, name, line) if p)


def _short_location(profile: dict) -> str:
    """'London, ON, Canada' -> 'London, ON' (for the subject line)."""
    loc = (profile.get("contact", {}) or {}).get("location", "") or ""
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    return ", ".join(parts[:2])


def _greeting(contact_name: str) -> str:
    n = (contact_name or "").strip()
    return f"Hi {n}," if n else "Hi there,"


def generate_email(target: TargetRole, profile: dict | None = None, persona: dict | None = None,
                   *, contact_name: str = "", **kw) -> ApplicationEmail:
    """Application email. Fixed template + one model-written, role-specific hook
    line (truth-only). Greets the HR contact by name when known."""
    profile = profile or load_profile()
    role = (target.title or "the role").strip()
    # The dynamic, model-generated pieces: a role-appropriate opener + a fit hook.
    opener = hook = ""
    try:
        eh = chat_structured(EMAIL_HOOK_SYSTEM, _context(profile, target, persona), EmailHook, **kw)
        opener, hook = (eh.opener or "").strip(), (eh.hook or "").strip()
    except Exception:
        opener = hook = ""
    body = "\n\n".join([
        _greeting(contact_name),
        opener or f"Your {role} posting caught my eye, it lines up closely with what I do day to day.",
        hook or _HOOK_FALLBACK,
        _worklink_line(profile),
        "Happy to walk through any of it on a quick call whenever suits you.",
        _signoff_block(profile, "Thanks for your time,"),
    ])
    name = _signoff_name(profile)
    loc = _short_location(profile)
    tail = ", ".join(p for p in [name, loc] if p)
    subject = f"{role} application" + (f" - {tail}" if tail else "")
    return humanize_email(ApplicationEmail(subject=subject, body=body))


def generate_followup_email(target: TargetRole, profile: dict | None = None,
                            persona: dict | None = None, *, contact_name: str = "",
                            date_applied: str = "", **kw) -> ApplicationEmail:
    """A short, polite follow-up to an already-sent application. Fully template-
    driven (no model call), so it never fails or drifts off-format."""
    profile = profile or load_profile()
    role = (target.title or "the role").strip()
    company = (target.company or "your company").strip()
    when = (date_applied or "").strip() or "recently"
    body = "\n\n".join([
        _greeting(contact_name),
        f"Floating this back to the top of your inbox. I applied for the {role} role on {when} and I am still genuinely keen.",
        (f"Nothing has changed on my end except that I have read more about {company} since, and I am more "
         "interested, not less. If the role is still open I would love to be in the running. If it has already "
         "moved on, even a one line reply so I can close it out would be appreciated."),
        "Resume is attached again for convenience.",
        _signoff_block(profile, "Thanks,"),
    ])
    name = _signoff_name(profile)
    subject = f"Re: {role} application" + (f" - {name}" if name else "")
    return humanize_email(ApplicationEmail(subject=subject, body=body))


def generate_hr_followup(company: str, role_titles: list[str] | None = None, *,
                         kind: str = "first", contact_name: str = "",
                         profile: dict | None = None) -> ApplicationEmail:
    """A short HR-outreach follow-up about a company's recent posting(s). Fully
    template-driven (no model call) so it never fails; the user edits it in the
    compose box before sending. `kind` is 'first' or 'second'."""
    profile = profile or load_profile()
    company = (company or "your team").strip()
    titles = [t for t in (role_titles or []) if t]
    roles = (titles[0] if len(titles) == 1
             else (", ".join(titles[:2]) + (" and other roles" if len(titles) > 2 else ""))
             if titles else "a few roles")
    if kind == "second":
        opener = f"Circling back on my note about the {roles} opening at {company}."
        nudge = ("I am still very interested. If it is still open I would love to be considered, "
                 "and if it has moved on, a quick line so I can close it out would be great.")
    else:
        opener = f"I saw {company} recently posted {roles}, so I wanted to reach out directly."
        nudge = ("I think my background is a strong match and I have applied. I would welcome the "
                 "chance to connect about it.")
    body = "\n\n".join(p for p in [
        _greeting(contact_name),
        opener,
        nudge,
        _portfolio_line(profile, attached=False),   # HR outreach: no attachment
        _signoff_block(profile, "Thanks for your time,"),
    ] if p)
    subject = (f"Following up on {roles} at {company}" if kind == "second"
               else f"Interested in {roles} at {company}")
    return humanize_email(ApplicationEmail(subject=subject, body=body))


def generate_all(target: TargetRole, profile: dict | None = None, persona: dict | None = None,
                 *, resume_model: str | None = None, letters_model: str | None = None,
                 skills_focus: list[str] | None = None, contact_name: str = "", **kw):
    """Generate all three artifacts, reusing one loaded profile + persona.

    `resume_model` drives the résumé; `letters_model` drives the cover letter +
    email hook. Either may be None to fall back to the Ollama default.
    `skills_focus` (résumé only) re-orders and emphasises specific real skills.
    `contact_name` personalises the email greeting (the saved company HR name)."""
    profile = profile or load_profile()
    return {
        "resume": generate_resume(target, profile, persona, model=resume_model,
                                  skills_focus=skills_focus, **kw),
        "cover_letter": generate_cover_letter(target, profile, persona, model=letters_model, **kw),
        "email": generate_email(target, profile, persona, model=letters_model,
                                contact_name=contact_name, **kw),
    }
