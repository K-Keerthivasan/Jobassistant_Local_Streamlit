"""Convert a .docx to .pdf. Two engines:

- docx2pdf : uses Microsoft Word (best fidelity on local Windows/Mac).
- libreoffice : `soffice --headless --convert-to pdf` (works in Docker/Linux).

`auto` picks docx2pdf on Windows/Mac if importable, else libreoffice."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from ..config import settings


def _libreoffice(docx_path: Path, out_dir: Path) -> Path:
    soffice = shutil.which(settings.libreoffice_bin) or settings.libreoffice_bin
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
        check=True,
        capture_output=True,
    )
    pdf = out_dir / (docx_path.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"LibreOffice did not produce {pdf}")
    return pdf


def _docx2pdf(docx_path: Path, pdf_path: Path) -> Path:
    from docx2pdf import convert  # imported lazily; Windows/Mac only

    convert(str(docx_path), str(pdf_path))
    if not pdf_path.exists():
        raise RuntimeError(f"docx2pdf did not produce {pdf_path}")
    return pdf_path


def to_pdf(docx_path: Path, pdf_path: Path | None = None) -> Path:
    docx_path = Path(docx_path)
    pdf_path = Path(pdf_path) if pdf_path else docx_path.with_suffix(".pdf")

    engine = settings.pdf_engine
    if engine == "auto":
        engine = "docx2pdf" if platform.system() in ("Windows", "Darwin") else "libreoffice"

    if engine == "docx2pdf":
        try:
            return _docx2pdf(docx_path, pdf_path)
        except Exception:
            # Fall back to LibreOffice if Word isn't available.
            if shutil.which(settings.libreoffice_bin):
                return _libreoffice(docx_path, pdf_path.parent)
            raise
    return _libreoffice(docx_path, pdf_path.parent)
