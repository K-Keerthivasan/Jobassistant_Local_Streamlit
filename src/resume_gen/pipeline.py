"""End-to-end: TargetRole -> generated + rendered artifacts on disk.

Output layout (one folder per application):
  output/<Company>_<Title>_<date>/
    resume.json          (validated schema output, for QA / re-render)
    <Company>_<Title>_KK_Resume.docx / .pdf
    <Company>_<Title>_KK_Cover.docx / .pdf
    email.txt
    target_role.json
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .config import settings
from .generate import generate_all
from .guard import enforce, enforce_cover_letter, enforce_email, has_violations
from .models import TargetRole
from .profile import load_profile
from .personas import select_persona
from .render.docx_renderer import render_cover_letter, render_resume


def _slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return s[:maxlen] or "untitled"


def _document_base(target: TargetRole) -> str:
    return f"{_slug(target.company, 18)}_{_slug(target.title, 28)}_KK"


def run(
    target: TargetRole,
    *,
    make_pdf: bool = True,
    profile: dict | None = None,
    strict: bool = False,
    persona: str | None = None,
) -> dict:
    profile = profile or load_profile()
    chosen = select_persona(target, persona)
    bundle = generate_all(target, profile, chosen)
    resume, cover, email = bundle["resume"], bundle["cover_letter"], bundle["email"]

    # Truth-guard: repair identity/education/skills, flag fabricated metrics.
    resume, qa = enforce(resume, profile, strict=strict, persona=chosen,
                         target_location=target.location)
    # Same discipline for the cover letter + email: rebuild contact line, strip
    # invented years/metrics, fix name/sign-off. Surface what was scrubbed in QA.
    cover, cover_qa = enforce_cover_letter(cover, profile, target_location=target.location)
    email, email_qa = enforce_email(email, profile)
    qa["cover_letter"] = cover_qa
    qa["email"] = email_qa

    folder = settings.output_dir / f"{_slug(target.company)}_{_slug(target.title)}_{date.today():%Y%m%d}"
    folder.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {}

    doc_base = _document_base(target)
    target_data = target.model_dump()
    target_data["persona_label"] = (chosen or {}).get("label", "")
    target_data["document_base_name"] = doc_base
    target_data["document_files"] = {
        "resume_docx": f"{doc_base}_Resume.docx",
        "resume_pdf": f"{doc_base}_Resume.pdf",
        "cover_letter_docx": f"{doc_base}_Cover.docx",
        "cover_letter_pdf": f"{doc_base}_Cover.pdf",
    }

    (folder / "target_role.json").write_text(
        json.dumps(target_data, indent=2), encoding="utf-8"
    )
    (folder / "resume.json").write_text(resume.model_dump_json(indent=2), encoding="utf-8")
    paths["resume_json"] = str(folder / "resume.json")

    # Structured cover letter too, so the UI / a re-render can read it back.
    (folder / "cover_letter.json").write_text(cover.model_dump_json(indent=2), encoding="utf-8")
    paths["cover_letter_json"] = str(folder / "cover_letter.json")

    (folder / "qa_report.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    paths["qa_report"] = str(folder / "qa_report.json")

    resume_docx = render_resume(resume, folder / f"{doc_base}_Resume.docx", profile)
    cover_docx = render_cover_letter(cover, folder / f"{doc_base}_Cover.docx")
    paths["resume_docx"] = str(resume_docx)
    paths["cover_letter_docx"] = str(cover_docx)

    email_txt = folder / "email.txt"
    email_txt.write_text(f"Subject: {email.subject}\n\n{email.body}\n", encoding="utf-8")
    paths["email_txt"] = str(email_txt)

    if make_pdf:
        from .render.pdf_export import to_pdf

        try:
            paths["resume_pdf"] = str(to_pdf(resume_docx))
            paths["cover_letter_pdf"] = str(to_pdf(cover_docx))
        except Exception as e:  # PDF is best-effort; docx always succeeds.
            paths["pdf_error"] = str(e)

    return {
        "folder": str(folder),
        "folder_name": folder.name,
        "paths": paths,
        "keywordsMatched": resume.keywordsMatched,
        "email_subject": email.subject,
        "persona": (chosen or {}).get("id", ""),
        "persona_label": (chosen or {}).get("label", ""),
        "qa": qa,
        "qa_has_violations": has_violations(qa),
        # Full generated content, so the UI can preview without re-reading files.
        "resume": resume.model_dump(),
        "cover_letter": cover.model_dump(),
        "email": email.model_dump(),
        "target": target_data,
    }
