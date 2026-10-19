"""Convert a .docx to .pdf. Three engines:

- wordcraft : `wordcraft-cli convert in.docx out.pdf` (WordCraft, local Windows;
  fast enough, about 0.1s, to fit the resume against real renders).
- docx2pdf : uses Microsoft Word (Windows/Mac).
- libreoffice : `soffice --headless --convert-to pdf` (works in Docker/Linux).

`auto` tries WordCraft when installed, then Word, then LibreOffice. Whatever the
engine, the PDF's Creator and Producer entries are removed afterwards so no tool
name survives in the document metadata; only Title and Author remain."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from ..config import settings

_WORDCRAFT_DEFAULT = Path(r"C:\Program Files\WordCraft\wordcraft-cli.exe")


def wordcraft_bin() -> str | None:
    """Path to wordcraft-cli, or None when it is not installed."""
    configured = settings.wordcraft_bin
    if configured:
        return shutil.which(configured) or (configured if Path(configured).exists() else None)
    found = shutil.which("wordcraft-cli")
    if found:
        return found
    return str(_WORDCRAFT_DEFAULT) if _WORDCRAFT_DEFAULT.exists() else None


def is_fast() -> bool:
    """True when a converter is available to check the real page a few times per
    run: WordCraft (about 0.1s) or LibreOffice (a few seconds, as in Docker), so
    the page fill is measured rather than estimated."""
    engine = settings.pdf_engine
    if engine == "wordcraft" or (engine == "auto" and wordcraft_bin() is not None):
        return True
    return engine in ("libreoffice", "auto") and shutil.which(settings.libreoffice_bin) is not None


def _wordcraft(docx_path: Path, pdf_path: Path) -> Path:
    exe = wordcraft_bin()
    if not exe:
        raise RuntimeError("wordcraft-cli is not installed (set WORDCRAFT_BIN).")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [exe, "convert", str(docx_path), str(pdf_path)],
        capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode or not pdf_path.exists():
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise RuntimeError(f"WordCraft did not produce {pdf_path}: {detail}")
    return pdf_path


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


def _strip_tool_metadata(pdf_path: Path) -> None:
    """Keep only Title and Author in the document info; drop Creator, Producer
    and anything else a converter stamped in. The page content is untouched."""
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(str(pdf_path))
        info = reader.metadata or {}
        keep = {k: info[k] for k in ("/Title", "/Author") if info.get(k)}
        writer = PdfWriter(clone_from=reader)
        writer._info = None                     # start from an empty info dictionary
        writer.add_metadata(keep)
        # Converters also embed an XMP packet naming the tool; drop it.
        writer._root_object.pop("/Metadata", None)
        # Cloning copies every object, so the dropped XMP stream would linger
        # unreferenced in the file; remove orphans so its bytes go too.
        writer.compress_identical_objects(remove_identicals=False, remove_orphans=True)
        with open(pdf_path, "wb") as fh:
            writer.write(fh)
    except Exception as e:                      # a failure here must not lose the PDF
        print(f"[pdf] metadata cleanup skipped: {type(e).__name__}: {e}", flush=True)


def _convert(docx_path: Path, pdf_path: Path) -> Path:
    engine = settings.pdf_engine
    if engine == "wordcraft":
        return _wordcraft(docx_path, pdf_path)
    if engine == "libreoffice":
        return _libreoffice(docx_path, pdf_path.parent)
    if engine == "docx2pdf":
        return _docx2pdf(docx_path, pdf_path)

    # auto: every engine that is present, in order, keeping each failure so the
    # final error says what was tried rather than only the last attempt.
    errors: list[str] = []
    if wordcraft_bin():
        try:
            return _wordcraft(docx_path, pdf_path)
        except Exception as e:
            errors.append(f"wordcraft: {e}")
    if platform.system() in ("Windows", "Darwin"):
        try:
            return _docx2pdf(docx_path, pdf_path)
        except Exception as e:
            errors.append(f"word: {type(e).__name__}: {e}")
    if shutil.which(settings.libreoffice_bin):
        try:
            return _libreoffice(docx_path, pdf_path.parent)
        except Exception as e:
            errors.append(f"libreoffice: {e}")
    raise RuntimeError("No PDF converter worked. Install WordCraft, Microsoft Word or "
                       "LibreOffice, or set PDF_ENGINE. Tried: " + ("; ".join(errors) or "none found"))


def to_pdf(docx_path: Path, pdf_path: Path | None = None) -> Path:
    docx_path = Path(docx_path)
    pdf_path = Path(pdf_path) if pdf_path else docx_path.with_suffix(".pdf")
    out = _convert(docx_path, pdf_path)
    _strip_tool_metadata(Path(out))
    return out
