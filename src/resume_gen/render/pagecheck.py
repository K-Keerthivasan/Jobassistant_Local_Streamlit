"""Deterministic page validation for rendered PDFs.

Two checks, surfaced in the QA report and the Hermes review panel:
- page COUNT vs a per-document limit (cover letter 1, résumé `RESUME_MAX_PAGES`).
- physical PAGE SIZE (Letter vs A4) vs the configured `PAGE_SIZE`.

Page geometry is read from the PDF (points = 1/72"). This is exact, unlike guessing
from word counts — it reflects exactly what LibreOffice/Word produced.
"""

from __future__ import annotations

from pathlib import Path

from ..config import settings

# Standard page sizes in PDF points.
_LETTER = (612.0, 792.0)        # 8.5 x 11 in
_A4 = (595.276, 841.89)         # 210 x 297 mm
_TOL = 6.0                      # ~0.08in tolerance for rounding


def _classify_size(w: float, h: float) -> str:
    a, b = sorted((w, h))  # portrait-normalize
    for name, dims in (("Letter", _LETTER), ("A4", _A4)):
        sa, sb = sorted(dims)
        if abs(a - sa) <= _TOL and abs(b - sb) <= _TOL:
            return name
    return "Custom"


def pdf_page_info(pdf_path: Path) -> dict:
    """{pages, page_size, width_pt, height_pt} for a PDF, or {} if unreadable."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        box = reader.pages[0].mediabox
        w, h = float(box.width), float(box.height)
        return {
            "pages": len(reader.pages),
            "page_size": _classify_size(w, h),
            "width_pt": round(w, 1),
            "height_pt": round(h, 1),
        }
    except Exception:
        return {}


def _expected_size() -> str:
    return "A4" if (settings.page_size or "letter").lower() == "a4" else "Letter"


def check_doc(pdf_path, *, limit: int, label: str) -> dict:
    """Validate one rendered PDF against its page limit + the expected page size."""
    p = Path(pdf_path) if pdf_path else None
    info = pdf_page_info(p) if (p and p.exists()) else {}
    if not info:
        return {"label": label, "available": False}
    return {
        "label": label,
        "available": True,
        "pages": info["pages"],
        "limit": limit,
        "pages_ok": info["pages"] <= limit,
        "page_size": info["page_size"],
        "expected_size": _expected_size(),
        "size_ok": info["page_size"] == _expected_size(),
    }


def page_report(resume_pdf=None, cover_pdf=None) -> dict:
    """Build the page-validation block for the QA report."""
    out: dict = {}
    if resume_pdf is not None:
        out["resume"] = check_doc(resume_pdf, limit=settings.resume_max_pages, label="Resume")
    if cover_pdf is not None:
        out["cover_letter"] = check_doc(cover_pdf, limit=settings.cover_max_pages, label="Cover letter")
    return out


def report_has_issues(report: dict) -> bool:
    """True if any available doc overflows its page limit or isn't the expected size."""
    for v in (report or {}).values():
        if isinstance(v, dict) and v.get("available") and (
            not v.get("pages_ok", True) or not v.get("size_ok", True)
        ):
            return True
    return False
