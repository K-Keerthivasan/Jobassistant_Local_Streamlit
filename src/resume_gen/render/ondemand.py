"""Render a stored run's artifacts on demand.

Generation writes nothing to disk — the application lives in the ``runs`` table.
When the user downloads something, we materialise just that artifact: JSON/email
straight from the bundle, DOCX/PDF rendered into a temp directory, read into
bytes, and the temp directory is discarded. Nothing persists under output/.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..models import CoverLetter, Resume
from ..profile import load_profile
from .docx_renderer import render_cover_letter, render_resume

# artifact id -> (kind, what it produces). Used to validate the download route.
ARTIFACTS = {
    "resume.pdf": "Resume PDF",
    "resume.docx": "Resume DOCX",
    "cover.pdf": "Cover letter PDF",
    "cover.docx": "Cover letter DOCX",
    "resume.json": "resume.json",
    "cover_letter.json": "cover_letter.json",
    "qa_report.json": "qa_report.json",
    "target_role.json": "target_role.json",
    "email.txt": "email.txt",
}

_JSON = "application/json"
_PDF = "application/pdf"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TXT = "text/plain; charset=utf-8"


def _doc_names(bundle: dict) -> dict:
    target = bundle.get("target") or {}
    files = target.get("document_files") or {}
    base = target.get("document_base_name") or "Application_KK"
    return {
        "resume.pdf": files.get("resume_pdf", f"{base}_Resume.pdf"),
        "resume.docx": files.get("resume_docx", f"{base}_Resume.docx"),
        "cover.pdf": files.get("cover_letter_pdf", f"{base}_Cover.pdf"),
        "cover.docx": files.get("cover_letter_docx", f"{base}_Cover.docx"),
    }


def _email_text(bundle: dict) -> str:
    e = bundle.get("email") or {}
    subject, body = e.get("subject", ""), e.get("body", "")
    return f"Subject: {subject}\n\n{body}\n"


def render_artifact(bundle: dict, artifact: str) -> tuple[bytes, str, str]:
    """Return ``(content_bytes, download_filename, mime_type)`` for one artifact
    of a stored run. Raises KeyError for an unknown artifact id, ValueError if the
    run has no content to render it from."""
    if artifact not in ARTIFACTS:
        raise KeyError(artifact)

    run_id = bundle.get("run_id") or bundle.get("folder_name") or "application"
    names = _doc_names(bundle)

    # --- straight-from-bundle text/JSON ---------------------------------- #
    if artifact == "resume.json":
        return _json_bytes(bundle.get("resume")), f"{run_id}_resume.json", _JSON
    if artifact == "cover_letter.json":
        return _json_bytes(bundle.get("cover_letter")), f"{run_id}_cover_letter.json", _JSON
    if artifact == "qa_report.json":
        return _json_bytes(bundle.get("qa")), f"{run_id}_qa_report.json", _JSON
    if artifact == "target_role.json":
        return _json_bytes(bundle.get("target")), f"{run_id}_target_role.json", _JSON
    if artifact == "email.txt":
        return _email_text(bundle).encode("utf-8"), f"{run_id}_email.txt", _TXT

    # --- rendered DOCX / PDF (temp dir, discarded) ----------------------- #
    is_cover = artifact.startswith("cover")
    want_pdf = artifact.endswith(".pdf")
    data = bundle.get("cover_letter") if is_cover else bundle.get("resume")
    if not data:
        raise ValueError(f"Run {run_id} has no {'cover letter' if is_cover else 'resume'} content.")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        docx_name = names["cover.docx"] if is_cover else names["resume.docx"]
        docx_path = tmpdir / docx_name
        if is_cover:
            render_cover_letter(CoverLetter(**data), docx_path)
        else:
            # Re-apply the auto-fit density chosen at generation so the downloaded
            # résumé matches the validated ~2-page layout (default 1.0 if absent).
            density = float((bundle.get("target") or {}).get("resume_density", 1.0) or 1.0)
            render_resume(Resume(**data), docx_path, load_profile(), density=density)

        if not want_pdf:
            return docx_path.read_bytes(), docx_name, _DOCX

        from .pdf_export import to_pdf

        pdf_path = to_pdf(docx_path)
        pdf_name = names["cover.pdf"] if is_cover else names["resume.pdf"]
        return Path(pdf_path).read_bytes(), pdf_name, _PDF


def _json_bytes(obj) -> bytes:
    return json.dumps(obj or {}, indent=2, ensure_ascii=False).encode("utf-8")
