"""Refine the résumé's density against a real render.

render/length.py decides the page target (one page, or two when the content
cannot fit one) and a starting density from an estimate. This module renders the
résumé to PDF a few times in a temp dir and walks the density so the real
document lands on that target: one page filled close to the bottom, or two pages
with page two at least half full. Only font size, spacing and margins change,
never content. It runs ONCE at generation; the chosen density is stored in the
run bundle and re-applied whenever the résumé is rendered for download.
Fail-safe: any error returns the starting density.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .length import DENSITIES, TWO_PAGE_MIN_FILL

_MAX_RENDERS = 4                      # cost guard (each render launches Word/LibreOffice)
# A one-page résumé should run close to the bottom of the page.
_ONE_PAGE_MIN_FILL = 0.88


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
                    # Text origin in page space: the text matrix's translation
                    # mapped through the current transformation matrix. Using
                    # tm alone is wrong for producers that set a page-level cm.
                    x, y = float(tm[4]), float(tm[5])
                    ys.append(x * float(cm[1]) + y * float(cm[3]) + float(cm[5]))
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


def _nearest_index(k: float) -> int:
    return min(range(len(DENSITIES)), key=lambda i: abs(DENSITIES[i] - k))


def fit_resume(resume, cover, doc_base: str, profile: dict, *,
               density: float = 1.0, pages_target: int = 1) -> tuple[float, dict]:
    """Return ``(density, page_report)`` for the résumé rendered at the density
    that best meets ``pages_target``, plus the cover letter's page check."""
    from .docx_renderer import render_cover_letter, render_resume, typo
    from .pagecheck import page_report
    from .pdf_export import to_pdf

    min_fill = _ONE_PAGE_MIN_FILL if pages_target == 1 else TWO_PAGE_MIN_FILL
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            cache: dict[int, tuple[int, float, Path]] = {}

            def measure(i: int):
                if i not in cache:
                    k = DENSITIES[i]
                    docx = tmpdir / f"{doc_base}_Resume_{int(round(k * 100))}.docx"
                    render_resume(resume, docx, profile, density=k)
                    pdf = Path(to_pdf(docx))
                    pages, fill = _last_page_fill(pdf, typo(k)["margin_in"])
                    cache[i] = (pages, fill, pdf)
                return cache[i]

            i = _nearest_index(density)
            pages, fill, pdf = measure(i)
            while len(cache) < _MAX_RENDERS:
                if pages > pages_target and i > 0:
                    i -= 1                                   # overflow: tighten
                elif pages == pages_target and fill < min_fill and i < len(DENSITIES) - 1:
                    np_, nf, npdf = measure(i + 1)           # sparse: loosen if it still fits
                    if np_ != pages_target:
                        break
                    i += 1
                elif pages < pages_target and i < len(DENSITIES) - 1:
                    i += 1                                   # two-page target came up short
                else:
                    break
                pages, fill, pdf = measure(i)

            cover_pdf = None
            try:
                cdocx = tmpdir / f"{doc_base}_Cover.docx"
                render_cover_letter(cover, cdocx)
                cover_pdf = to_pdf(cdocx)
            except Exception:
                cover_pdf = None
            report = page_report(resume_pdf=pdf, cover_pdf=cover_pdf)
            report["fit"] = {"method": "render", "pages_target": pages_target,
                             "density": DENSITIES[i], "pages": pages,
                             "last_page_fill": round(fill, 3)}
            return DENSITIES[i], report
    except Exception:
        return density, {}
