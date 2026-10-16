"""End-to-end: TargetRole -> one generated application, stored in the DB.

Nothing is written to disk. ``run`` returns (and persists to the ``runs`` table)
a bundle holding the validated resume/cover-letter/email JSON, the QA report, and
the target. The resume/cover DOCX + PDF are rendered on demand only when the user
downloads them (render/ondemand.py, served by the /download route).
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .config import settings
from .generate import generate_all
from .guard import enforce, enforce_cover_letter, enforce_email, has_violations
from .models import TargetRole
from .profile import load_profile
from .personas import select_persona


def _slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return s[:maxlen] or "untitled"


# Words dropped from filenames: true filler + company-name noise. Seniority/role words
# (Senior, Lead, Engineer, …) are kept so the name still identifies the job.
_FN_DROP = {"the", "and", "of", "for", "a", "an", "to", "in", "with", "at", "on", "or",
            "inc", "llc", "ltd", "limited", "corp", "co", "gmbh", "plc", "group"}


def _fn_part(text: str, maxlen: int, *, from_end: bool = False) -> str:
    """One compact filename fragment. Keep the meaningful words (filler/company-noise
    dropped), join with '_', and truncate on WHOLE-WORD boundaries to <= maxlen chars
    (never cuts a word in half). `from_end=True` keeps the LAST words — used for job
    titles so the role noun ('Engineer', 'Manager') survives instead of the seniority
    prefix."""
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    sig = [w for w in words if w.lower() not in _FN_DROP] or words
    seq = list(reversed(sig)) if from_end else sig
    out = ""
    for w in seq:
        nxt = w if not out else (f"{w}_{out}" if from_end else f"{out}_{w}")
        if len(nxt) > maxlen:
            break
        out = nxt
    if not out and sig:                       # a single word longer than maxlen → hard cap
        out = (sig[-1] if from_end else sig[0])[:maxlen]
    return out or "x"


def _initials(name: str, maxlen: int = 3) -> str:
    """Owner tag from the candidate's name: 'Jordan Sample' -> 'JS', 'Keerthivasan' -> 'K'."""
    parts = re.findall(r"[A-Za-z]+", name or "")
    return ("".join(p[0] for p in parts).upper()[:maxlen]) or "X"


def _document_base(target: TargetRole, candidate_name: str = "") -> str:
    """Document naming standard: ``kk_[Company]_[Role]`` (résumé) and
    ``kk_[Company]_[Role]_CL`` (cover letter). Company and role are compacted on
    whole-word boundaries so the name stays readable."""
    company = _fn_part(target.company, 18)
    title = _fn_part(target.title, 26, from_end=True)
    return "_".join(p for p in ("kk", company, title) if p) or "kk_Application"


def _resolve_engines(model: str | None) -> tuple[str | None, str | None]:
    """Map a requested engine selection to (resume_model, letters_model).

    - "split": résumé on local Ollama, cover letter + email on the Hermes agent.
      Falls back to all-local if Hermes isn't configured.
    - any concrete model id (e.g. "qwen3:8b" or "hermes-agent"): every artifact
      runs on that one engine.
    - None/""/"auto": the default engine for everything — Hermes when reachable
      (with automatic per-call Ollama fallback), else Ollama. See llm._default_model.
    """
    m = (model or "").strip()
    if m.lower() == "split":
        from .llm import hermes_client
        if hermes_client.available():
            return settings.ollama_model, settings.hermes_model
        return None, None  # Hermes off — quietly run everything local
    if m and m.lower() != "auto":
        return m, m
    # Default/auto → let chat_structured pick the default engine (Hermes-first) per call.
    return None, None


def run(
    target: TargetRole,
    *,
    make_pdf: bool = True,
    profile: dict | None = None,
    strict: bool = False,
    persona: str | None = None,
    model: str | None = None,
    skills_focus: list[str] | None = None,
    lane: str | None = None,
    grade: dict | None = None,
) -> dict:
    """`lane`: the job's lane slug (from the batch import). It picks the base
    resume (persona), the portfolio links, and the matrix that filters every
    skill claim. When absent it is resolved from the title, then from the persona.
    `grade`: the job's matrix grade (tier, gap flags, fit sentence); computed here
    when the caller has none."""
    profile = profile or load_profile()
    from .llm import fallbacks, reset_fallbacks, reset_run_metrics, run_metrics
    from . import lanes as lane_data
    from .lanes.guard import lane_context
    reset_fallbacks()                       # track any Hermes→Ollama fallbacks this run
    reset_run_metrics()                     # calls/tokens/time for this generation only

    lane_obj = lane_data.get_lane(lane) if lane else None
    if lane_obj is None and lane:
        lane_obj = lane_data.resolve_lane(lane)
    if lane_obj is None:
        lane_obj = lane_data.resolve_lane(target.title)
    chosen = select_persona(target, persona, lane=lane_obj)
    if lane_obj is None and chosen:
        lane_obj = lane_data.lane_for_persona(chosen.get("id", ""))
    if lane_obj is not None and not grade:
        from .grading import grade as grade_fn
        grade = grade_fn(target.title, target.description, lane_obj)
    lane_ctx = lane_context(lane_obj, grade)
    lane_links = lane_data.portfolio_links_for(lane_obj) if lane_obj is not None else None

    resume_model, letters_model = _resolve_engines(model)
    # Personalise the email greeting with the saved company HR name, when we have one.
    from .intake.companies import find_company
    contact_name = ((find_company(target.company) or {}).get("hr_name") or "").strip()
    bundle = generate_all(target, profile, chosen,
                          resume_model=resume_model, letters_model=letters_model,
                          skills_focus=skills_focus, contact_name=contact_name,
                          lane_ctx=lane_ctx)
    resume, cover, email = bundle["resume"], bundle["cover_letter"], bundle["email"]

    # Hermes-led QA: the main truthfulness judgment, run BEFORE the deterministic
    # guard. It semantically audits every résumé claim against the profile and removes
    # what isn't supported (no-op if Hermes is off). The guard below is the hard backstop.
    from .hermes_qa import qa_resume

    resume, hermes_qa_report = qa_resume(resume, profile, persona=chosen, target=target)

    # Truth-guard (final backstop): hard-enforce identity/education/skills, strip metrics.
    resume, qa = enforce(resume, profile, strict=strict, persona=chosen,
                         target_title=target.title,
                         target_location=target.location, lane_ctx=lane_ctx,
                         links=lane_links)
    qa["hermes_qa"] = hermes_qa_report
    # Cleanup pass (after validation): drop em/en dashes and slashes from résumé prose.
    from .humanize import humanize_resume
    resume = humanize_resume(resume)
    # Same discipline for the cover letter + email: rebuild contact line, strip
    # invented years/metrics, fix name/sign-off. Surface what was scrubbed in QA.
    cover, cover_qa = enforce_cover_letter(cover, profile, target_location=target.location,
                                           lane_ctx=lane_ctx, links=lane_links)
    email, email_qa = enforce_email(email, profile)
    if lane_ctx.get("lane"):
        from .lanes.guard import scan_text
        email_qa["lane_guard"] = {"hits": scan_text(email.body, lane_ctx)}
    qa["cover_letter"] = cover_qa
    qa["email"] = email_qa

    # Nothing is written to disk. The whole application is stored in the DB
    # (table `runs`); the resume/cover PDFs + DOCX are rendered on demand only
    # when the user hits Download (see render/ondemand.py + the /download route).
    run_id = f"{_slug(target.company)}_{_slug(target.title)}_{date.today():%Y%m%d}"
    created_at = datetime.now().isoformat(timespec="seconds")

    doc_base = _document_base(target, getattr(resume, "fullName", "") or profile.get("full_name", ""))

    # Length: one full page, or two only when trimming the least relevant bullets
    # and roles cannot fit one (then page two is at least half full). Decided from
    # an estimate of the rendered height, so it runs in fast mode too. Trims only
    # remove content and are listed in the QA report.
    from .render.length import fit_length
    resume, resume_density, qa["length"] = fit_length(resume, profile)
    if make_pdf and not settings.hermes_fast_mode:
        # Refine the density against real renders (only font/spacing/margins scale).
        from .render.autofit import fit_resume
        resume_density, qa["pages"] = fit_resume(
            resume, cover, doc_base, profile, density=resume_density,
            pages_target=qa["length"].get("pages_target", 1))
    elif make_pdf:
        # Exact page fitting launches Word or LibreOffice several times. In fast mode
        # the estimated density stands; documents still render normally on download.
        qa["pages"] = {
            "deferred": True,
            "reason": "fast_mode_estimated_density",
        }

    target_data = target.model_dump()
    target_data["persona"] = (chosen or {}).get("id", "")
    target_data["persona_label"] = (chosen or {}).get("label", "")
    target_data["document_base_name"] = doc_base
    target_data["resume_density"] = resume_density   # re-applied at download render
    target_data["document_files"] = {
        "resume_docx": f"{doc_base}.docx",
        "resume_pdf": f"{doc_base}.pdf",
        "cover_letter_docx": f"{doc_base}_CL.docx",
        "cover_letter_pdf": f"{doc_base}_CL.pdf",
    }
    target_data["lane"] = lane_obj.slug if lane_obj else ""
    target_data["lane_title"] = lane_obj.title if lane_obj else ""
    target_data["matrix_version"] = lane_obj.version if lane_obj else ""
    target_data["grade"] = {k: (grade or {}).get(k) for k in
                            ("tier", "tier_reason", "gap_flags", "fit_sentence", "evidence_skill_ids")} if grade else {}
    target_data["links"] = [{"label": l.label, "url": l.url} for l in (lane_links or [])]

    from .llm import _default_model
    _eff = _default_model()                  # what None/auto actually resolved to
    fb = fallbacks()

    bundle = {
        "run_id": run_id,
        "folder": run_id,        # back-compat: callers store this in job/role notes
        "folder_name": run_id,
        "created_at": created_at,
        "keywordsMatched": resume.keywordsMatched,
        "email_subject": email.subject,
        "persona": (chosen or {}).get("id", ""),
        "persona_label": (chosen or {}).get("label", ""),
        "lane": lane_obj.slug if lane_obj else "",
        "tier": (grade or {}).get("tier", ""),
        "engines": {
            "resume": resume_model or _eff,
            "letters": letters_model or _eff,
        },
        # True if any Hermes call fell back to Ollama this run (UI surfaces a notice).
        "hermes_fallback": bool(fb),
        "engine_notes": fb,
        "performance": run_metrics(),
        "qa": qa,
        "qa_has_violations": has_violations(qa),
        # Full generated content — the only copy. Preview + on-demand render read this.
        "resume": resume.model_dump(),
        "cover_letter": cover.model_dump(),
        "email": email.model_dump(),
        "target": target_data,
    }

    from .intake import runs as runs_store

    runs_store.save_run(bundle)
    return bundle
