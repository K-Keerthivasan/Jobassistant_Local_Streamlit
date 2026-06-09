"""End-to-end: TargetRole -> generated + rendered artifacts on disk.

Output layout (one folder per application):
  output/<Company>_<Title>_<date>/
    resume.json          (validated schema output, for QA / re-render)
    resume.docx / .pdf
    cover_letter.docx / .pdf
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
from .guard import enforce, has_violations
from .models import TargetRole
from .profile import load_profile
from .render.docx_renderer import render_cover_letter, render_resume


def _slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return s[:maxlen] or "untitled"


def run(
    target: TargetRole,
    *,
    make_pdf: bool = True,
    profile: dict | None = None,
    strict: bool = False,
) -> dict:
    profile = profile or load_profile()
    bundle = generate_all(target, profile)
    resume, cover, email = bundle["resume"], bundle["cover_letter"], bundle["email"]

    # Truth-guard: repair identity/education/skills, flag fabricated metrics.
    resume, qa = enforce(resume, profile, strict=strict)

    folder = settings.output_dir / f"{_slug(target.company)}_{_slug(target.title)}_{date.today():%Y%m%d}"
    folder.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {}

    (folder / "target_role.json").write_text(
        target.model_dump_json(indent=2), encoding="utf-8"
    )
    (folder / "resume.json").write_text(resume.model_dump_json(indent=2), encoding="utf-8")
    paths["resume_json"] = str(folder / "resume.json")

    (folder / "qa_report.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    paths["qa_report"] = str(folder / "qa_report.json")

    resume_docx = render_resume(resume, folder / "resume.docx")
    cover_docx = render_cover_letter(cover, folder / "cover_letter.docx")
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
        "paths": paths,
        "keywordsMatched": resume.keywordsMatched,
        "email_subject": email.subject,
        "qa": qa,
        "qa_has_violations": has_violations(qa),
    }
