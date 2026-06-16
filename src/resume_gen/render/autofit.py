"""Auto-fit the résumé's typographic density so its REAL content fills close to
two pages — never by inventing content, only by scaling font size, line spacing
and margins (see docx_renderer.typo).

The search renders the résumé to PDF a few times in a temp dir, measures how much
of the last page is used, and walks the density up/down until the content lands
in the target fill band. It runs ONCE at generation; the chosen density is stored
in the run bundle and re-applied whenever the résumé is rendered for download, so
downloads stay fast and deterministic. Fail-safe: any error returns density 1.0.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..config import settings

# Densities to try, compact → spacious. 1.00 == the original fixed styling.
_DENSITIES = [0.92, 1.00, 1.10, 1.20, 1.30]
_BASE_INDEX = 1                       # index of 1.00
_MAX_STEPS = 3                        # extra renders beyond the first (cost guard)

# Target fill of the whole two-page area. The user wants "comfortably into page 2"
# (~75–90%): full page 1 plus roughly half-to-most of page 2.
_FILL_LO, _FILL_HI = 0.75, 0.90


def _last_page_fill(pdf_path: Path, margin_in: float) -> tuple[int, float]:
    """Return ``(page_count, fraction)`` where fraction is how much of the LAST
    page's usable height is occupied by text. 0.0 if it can't be measured."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        n = len(reader.pages)
        page = reader.pages[n - 1]
        h = float(page.mediabox.height)
        margin_pt = margin_in * 72.0
        ys: list[float] = []

        def _visit(text, cm, tm, font_dict, font_size):
            if text and text.strip():
                try:
                    ys.append(float(tm[5]))   # y translation of this text run
                except (TypeError, ValueError, IndexError):
                    pass

        page.extract_text(visitor_text=_visit)
        usable = h - 2 * margin_pt
        if not ys or usable <= 0:
            return n, 0.0
        used = (h - margin_pt) - min(ys)      # top-of-content → lowest baseline
        return n, max(0.0, min(1.0, used / usable))
    except Exception:
        return 0, 0.0


def _overall_fill(pages: int, last_fill: float) -> float:
    """Fraction of the two-page area filled."""
    if pages <= 0:
        return 0.0
    if pages == 1:
        return last_fill / 2.0
    if pages == 2:
        return (1.0 + last_fill) / 2.0
    return 1.0                                 # 3+ pages: overflowing


def fit_resume(resume, cover, doc_base: str, profile: dict) -> tuple[float, dict]:
    """Pick the résumé density that best fills ~2 pages, then build the page
    report (résumé at that density + the cover letter). Returns
    ``(density, page_report)``. Fail-safe → ``(1.0, {})`` on any error."""
    from .docx_renderer import render_cover_letter, render_resume, typo
    from .pagecheck import page_report
    from .pdf_export import to_pdf

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            cache: dict[float, tuple[int, float, Path]] = {}

            def measure(k: float):
                if k in cache:
                    return cache[k]
                docx = tmpdir / f"{doc_base}_Resume_{int(round(k * 100))}.docx"
                render_resume(resume, docx, profile, density=k)
                pdf = Path(to_pdf(docx))
                pages, fill = _last_page_fill(pdf, typo(k)["margin_in"])
                cache[k] = (pages, fill, pdf)
                return cache[k]

            i = _BASE_INDEX
            pages, fill, pdf = measure(_DENSITIES[i])
            for _ in range(_MAX_STEPS):
                overall = _overall_fill(pages, fill)
                if pages > 2 and i > 0:
                    i -= 1                                   # overflow → tighten
                elif pages < 2 and i < len(_DENSITIES) - 1:
                    i += 1                                   # under a page → loosen
                elif pages == 2 and overall < _FILL_LO and i < len(_DENSITIES) - 1:
                    ni = i + 1                               # too sparse → try looser,
                    np_, nf, npdf = measure(_DENSITIES[ni])  # but only if it stays ≤2pp
                    if np_ <= 2:
                        i, pages, fill, pdf = ni, np_, nf, npdf
                        continue
                    break
                elif pages == 2 and overall > _FILL_HI and i > 0:
                    i -= 1                                   # too dense → tighten a step
                else:
                    break                                    # in band (or can't improve)
                pages, fill, pdf = measure(_DENSITIES[i])

            density = _DENSITIES[i]
            cover_pdf = None
            try:
                cdocx = tmpdir / f"{doc_base}_Cover.docx"
                render_cover_letter(cover, cdocx)
                cover_pdf = to_pdf(cdocx)
            except Exception:
                cover_pdf = None
            return density, page_report(resume_pdf=pdf, cover_pdf=cover_pdf)
    except Exception:
        return 1.0, {}
