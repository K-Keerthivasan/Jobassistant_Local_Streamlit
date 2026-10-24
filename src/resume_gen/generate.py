"""Orchestration: master profile + target role -> validated resume / cover
letter / email objects, via Ollama."""

from __future__ import annotations

import re

from .config import settings
from .humanize import humanize_answer, humanize_cover_letter, humanize_email
from .llm import chat_structured
from .models import (
    ApplicationDraft,
    ApplicationEmail,
    CoverLetter,
    EmailHook,
    FollowupNote,
    JobExtract,
    Resume,
    ScreeningAnswer,
    ScreeningAnswers,
    TargetRole,
)
from .personas import persona_directive
from .profile import load_profile, profile_to_prompt_block
from .prompts import (
    APPLICATION_DRAFT_SYSTEM,
    ANSWER_SYSTEM,
    COVER_LETTER_SYSTEM,
    EMAIL_HOOK_SYSTEM,
    EMAIL_PARSE_SYSTEM,
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


_BATCH_ANSWER_RULE = (
    "6. OUTPUT. You are given several numbered QUESTIONS. Answer each one separately, "
    "applying rules 1 to 5 to every answer. A question that has its own MY_DRAFT follows "
    'rule 3 for that answer only. Return ONE valid JSON object: {"answers": [{"id": 1, '
    '"answer": "..."}, ...]} with exactly one entry per question id, and nothing else.'
)


def generate_answers(items: list[tuple[str, str]], target: TargetRole | None = None, *,
                     profile: dict | None = None, model: str | None = None,
                     max_words: int | None = None, **kw) -> list[str | Exception]:
    """Answer several screening questions in ONE model call.

    `items` is a list of (question, draft). The profile and job are sent once, not
    once per question, so N questions cost one call. Returns one result per item, in
    order: the answer, or the Exception that item failed with. A question the batch
    reply leaves out is retried on its own, so nothing is silently dropped."""
    if len(items) <= 1:
        out: list[str | Exception] = []
        for question, draft in items:
            try:
                out.append(generate_answer(question, target, draft=draft, profile=profile,
                                           model=model, max_words=max_words, **kw))
            except Exception as e:
                out.append(e)
        return out

    profile = profile or load_profile()
    t = target or TargetRole(company="", title="", description="")
    blocks = []
    for i, (question, draft) in enumerate(items, 1):
        block = f"[{i}] QUESTION:\n{question.strip()}\n"
        if draft.strip():
            block += ("MY_DRAFT (rewrite THIS — keep its story and facts, only polish "
                      "wording/flow):\n" + draft.strip() + "\n")
        blocks.append(block)
    user = (
        "CANDIDATE_PROFILE:\n" + profile_to_prompt_block(profile) + "\n\n"
        "TARGET_ROLE:\n"
        f"  company: {t.company}\n  title: {t.title}\n  location: {t.location}\n"
        f"  job_description: |\n    {(t.description or '').strip()}\n\n"
        "QUESTIONS:\n" + "\n".join(blocks)
    )
    if max_words and max_words > 0:
        user += (
            f"\nLENGTH: Write about {max_words} words per answer. This is a HARD MAXIMUM "
            f"for each answer. Answer each question directly and stop.\n"
        )
    system = ANSWER_SYSTEM.rsplit("6. OUTPUT.", 1)[0] + _BATCH_ANSWER_RULE

    by_id: dict[int, str] = {}
    batch_error: Exception | None = None
    try:
        reply = chat_structured(system, user, ScreeningAnswers, model=model, **kw)
        by_id = {a.id: a.answer for a in reply.answers if (a.answer or "").strip()}
    except Exception as e:
        batch_error = e

    results: list[str | Exception] = []
    for i, (question, draft) in enumerate(items, 1):
        if i in by_id:
            results.append(humanize_answer(by_id[i]))
        elif batch_error is not None:
            # The whole call failed; retrying each question would multiply the cost
            # of an outage, so report the failure for every item instead.
            results.append(batch_error)
        else:
            try:
                results.append(generate_answer(question, t, draft=draft, profile=profile,
                                               model=model, max_words=max_words, **kw))
            except Exception as e:
                results.append(e)
    return results


def _context(profile: dict | None, target: TargetRole, persona: dict | None = None,
             lane_ctx: dict | None = None, *, for_cover_letter: bool = False) -> str:
    profile = profile or load_profile()
    extra = persona_directive(persona)
    from .personas import is_visual_ai_role
    if is_visual_ai_role(target):
        extra += '''\nVISUAL AI ROLE: This is visual/video production, not LLM application engineering.
Lead with evidenced editing, compositing, VFX training and creative deliverables. Software,
n8n, MCP and coding assistants are secondary supporting skills, never substitutes for an
AI art pipeline. Do not imply experience with LoRA, generative video, character consistency,
production reels or specific image/video models unless the candidate profile evidences it.
Select relevant visual portfolio links from the profile. Keep employment titles and facts
accurate; do not reclassify developer employment as professional AI artist experience.
'''
    if lane_ctx and lane_ctx.get("lane"):
        from .lanes.guard import directive
        extra += directive(lane_ctx, for_cover_letter=for_cover_letter)
    return build_user_message(profile_to_prompt_block(profile), target, extra)


def generate_resume(target: TargetRole, profile: dict | None = None, persona: dict | None = None,
                    *, skills_focus: list[str] | None = None, lane_ctx: dict | None = None, **kw) -> Resume:
    user = _context(profile, target, persona, lane_ctx)
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


def generate_cover_letter(target: TargetRole, profile: dict | None = None, persona: dict | None = None,
                          *, lane_ctx: dict | None = None, **kw) -> CoverLetter:
    user = _context(profile, target, persona, lane_ctx, for_cover_letter=True)
    # A touch more warmth than the resume, but NOT so hot it fabricates (0.7 was
    # inventing fake names, team sizes, and metrics).
    kw.setdefault("temperature", 0.35)
    cl = chat_structured(COVER_LETTER_SYSTEM, user, CoverLetter, **kw)
    return humanize_cover_letter(cl)


def generate_application_draft(
    target: TargetRole,
    profile: dict | None = None,
    persona: dict | None = None,
    *,
    skills_focus: list[str] | None = None,
    lane_ctx: dict | None = None,
    **kw,
) -> ApplicationDraft:
    """Generate resume + cover letter together, avoiding a duplicate full context."""
    user = _context(profile, target, persona, lane_ctx, for_cover_letter=True)
    if skills_focus:
        focus = ", ".join(s for s in skills_focus if s)
        user += (
            "\n\nSKILLS EMPHASIS: Prioritise these only where they are genuinely "
            f"present in CANDIDATE_PROFILE: {focus}."
        )
    kw.setdefault("temperature", 0.25)
    draft = chat_structured(APPLICATION_DRAFT_SYSTEM, user, ApplicationDraft, **kw)
    draft.cover_letter = humanize_cover_letter(draft.cover_letter)
    return draft


# --------------------------------------------------------------------------- #
# Application / follow-up emails — assembled from a FIXED template so the format
# is always consistent; only the role-specific "hook" line is model-generated.
# Everything else (greeting, opener, work links, sign-off) is deterministic and
# truth-only, pulled from the profile. No em dashes (humanize_email strips them).
# --------------------------------------------------------------------------- #
def _plain(text: str) -> str:
    """Resume prose without the **bold** markers."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", (text or "").strip()).strip(" -\u2022")


def _first_person(line: str) -> str:
    """'Build LLM apps...' -> 'I build LLM apps...' for a summary bullet."""
    line = _plain(line).rstrip(".")
    if not line:
        return ""
    if re.match(r"(I|I'm|I've|My)\b", line):
        return line + "."
    return "I " + line[0].lower() + line[1:] + "."


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
        return "My resume is attached, and the work itself is easier to judge directly: " \
               + " and ".join(parts) + "."
    return "The work itself is easier to judge directly: " + " and ".join(parts) + "."


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
    """Shorten a comma-separated location for the subject line."""
    loc = (profile.get("contact", {}) or {}).get("location", "") or ""
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    return ", ".join(parts[:2])


def _greeting(contact_name: str) -> str:
    """Name it when we know it; otherwise "Hello," reads cleaner and less generic
    to a stranger than "Hi there,"."""
    n = (contact_name or "").strip()
    return f"Hi {n}," if n else "Hello,"


def _uses_hermes(model: str | None) -> bool:
    """Resolve whether this generation call would use the Hermes gateway."""
    if model:
        return str(model).startswith("hermes")
    return settings.default_engine == "hermes" and bool(settings.hermes_api_key)


def email_lines(target: TargetRole, profile: dict | None = None, persona: dict | None = None,
                **kw) -> EmailHook:
    """The model-written parts of the application email (why this role, proof
    points). Empty on failure; the email then falls back to the resume."""
    try:
        return chat_structured(EMAIL_HOOK_SYSTEM, _context(profile or load_profile(), target, persona),
                               EmailHook, **kw)
    except Exception:
        return EmailHook()


def generate_email(target: TargetRole, profile: dict | None = None, persona: dict | None = None,
                   *, contact_name: str = "", lines: EmailHook | None = None,
                   resume: Resume | None = None, **kw) -> ApplicationEmail:
    """Application email that says plainly why it was sent: the role applied
    for with documents attached, why this role, two or three proof points
    matched to the posting, work links and one clear ask. `lines` are the
    written parts (from the combined draft or `email_lines`); when they are
    missing, the tailored, truth-guarded `resume` supplies them."""
    profile = profile or load_profile()
    role = (target.title or "the role").strip()
    company = (target.company or "").strip()
    if lines is None:
        # In Hermes fast mode the combined draft writes these; never pay for a
        # second agent session just for the email.
        lines = EmailHook() if settings.hermes_fast_mode and _uses_hermes(kw.get("model")) \
            else email_lines(target, profile, persona, **kw)
    why = _plain(lines.why)
    points = [_plain(p) for p in (lines.proof_points or []) if _plain(p)][:3]
    if resume is not None:
        if not why and resume.summaryPoints:
            why = _first_person(resume.summaryPoints[0])
        if len(points) < 2:
            points += [_plain(e.bullets[0]) for e in (resume.experience or []) if e.bullets][:3 - len(points)]
    if not why:
        why = f"The {role} role is the same kind of work I do day to day, and the details are below."
    at = f" at {company}" if company else ""
    body = "\n\n".join(p for p in [
        _greeting(contact_name),
        f"I'm applying for the {role} position{at}".rstrip(".") + ". My resume and cover letter are attached.",
        why,
        ("What I'd bring:\n" + "\n".join(f"- {p}" for p in points)) if points else "",
        _portfolio_line(profile, attached=False),
        "Would you be open to a short call to talk about the role? I'm happy to work around your schedule.",
        _signoff_block(profile, "Best regards,"),
    ] if p)
    name = _signoff_name(profile)
    subject = f"Application for {role}{at}" + (f" - {name}" if name else "")
    return humanize_email(ApplicationEmail(subject=subject, body=body))


_FOLLOWUP_VALUE_FALLBACK = (
    "Since applying I've kept building in this space, and I'm confident I can start adding value here quickly."
)


def generate_followup_email(target: TargetRole, profile: dict | None = None,
                            persona: dict | None = None, *, contact_name: str = "",
                            date_applied: str = "", **kw) -> ApplicationEmail:
    """A follow-up that reopens the conversation: reaffirm fit in one line, add a
    FRESH value proposition (model-written, truth-only, with a fallback), then ask
    for next steps. Warm and confident, never desperate."""
    profile = profile or load_profile()
    role = (target.title or "the role").strip()
    company = (target.company or "your team").strip()
    # The one dynamic, model-generated piece: a fresh value proposition (truth-only).
    value = ""
    try:
        value = (chat_structured(FOLLOWUP_SYSTEM, _context(profile, target, persona),
                                 FollowupNote, **kw).value or "").strip()
    except Exception:
        value = ""
    body = "\n\n".join([
        _greeting(contact_name),
        f"I wanted to follow up on my application for the {role} role at {company}. I'm confident it's a strong match for what you're building.",
        value or _FOLLOWUP_VALUE_FALLBACK,
        "Would it make sense to set up a quick call to talk through how I can help? I'm happy to work around your schedule.",
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
                 skills_focus: list[str] | None = None, contact_name: str = "",
                 lane_ctx: dict | None = None, **kw):
    """Generate all three artifacts, reusing one loaded profile + persona.

    `resume_model` drives the résumé; `letters_model` drives the cover letter +
    email hook. Either may be None to fall back to the Ollama default.
    `skills_focus` (résumé only) re-orders and emphasises specific real skills.
    `contact_name` personalises the email greeting (the saved company HR name)."""
    profile = profile or load_profile()
    # Hermes is backed by a quota-bearing agent. In fast mode, one structured call
    # produces both long-form artifacts instead of sending the same ~profile/JD
    # context twice. Email remains deterministic, so a normal run is one AI call.
    if (
        settings.hermes_fast_mode
        and resume_model == letters_model
        and _uses_hermes(resume_model)
    ):
        draft = generate_application_draft(
            target, profile, persona, model=resume_model,
            skills_focus=skills_focus, lane_ctx=lane_ctx, **kw,
        )
        resume, cover, lines = draft.resume, draft.cover_letter, draft.email
    else:
        resume = generate_resume(
            target, profile, persona, model=resume_model,
            skills_focus=skills_focus, lane_ctx=lane_ctx, **kw,
        )
        cover = generate_cover_letter(
            target, profile, persona, model=letters_model, lane_ctx=lane_ctx, **kw,
        )
        lines = email_lines(target, profile, persona, model=letters_model, **kw)
    return {
        "resume": resume,
        "cover_letter": cover,
        "email_lines": lines,
        "email": generate_email(target, profile, persona, contact_name=contact_name,
                                lines=lines, resume=resume),
    }
