"""Render validated Resume / CoverLetter models into styled .docx files using
python-docx. Styling is defined here (acts as the template) and mirrors the
clean look of the sample resumes: centred name header, contact line, ruled
section headings, tight one-line bullets. ATS-safe (no text boxes / tables for
content, real headings, standard fonts)."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor

from ..models import CoverLetter, Resume

ACCENT = RGBColor(0x1F, 0x4E, 0x79)  # deep blue, like the samples
DARK = RGBColor(0x22, 0x22, 0x22)
MUTED = RGBColor(0x55, 0x5B, 0x66)
FONT = "Lato"  # clean, modern, ATS-safe (installed in the PDF container)

# Friendly labels for the master-profile skill groups, in display order.
SKILL_GROUP_LABELS = {
    "languages": "Languages",
    "backend_cloud": "Backend & Cloud",
    "frontend_ui": "Frontend",
    "ai_automation": "AI & Automation",
    "game_dev": "Game Development",
    "marketing": "Marketing",
    "sales_service": "Sales & Service",
    "creative_media": "Creative & Media",
    "office_admin": "Office & Admin",
    "tools_other": "Tools",
}


def _group_skills(skills, profile):
    """Bucket the resume's flat skill list into the master-profile categories,
    preserving the resume's relevance order within each category. Returns a list
    of (label, [skills]) for the categories that have any skills, plus 'Other'."""
    if not profile:
        return [("", list(skills))]
    groups = profile.get("skills") or {}
    # map each profile skill (lowercased) -> its group key
    skill_to_group = {}
    for gkey, items in groups.items():
        for it in items:
            skill_to_group[it.lower()] = gkey
    buckets: dict[str, list[str]] = {}
    other: list[str] = []
    for s in skills:
        g = skill_to_group.get(s.lower())
        if g:
            buckets.setdefault(g, []).append(s)
        else:
            other.append(s)
    out = []
    for gkey, label in SKILL_GROUP_LABELS.items():
        if buckets.get(gkey):
            out.append((label, buckets[gkey]))
    if other:
        out.append(("Other", other))
    return out


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #
def _base_styles(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(11)
    style.font.color.rgb = DARK
    pf = style.paragraph_format
    pf.space_after = Pt(3)
    pf.line_spacing = 1.12
    pf.widow_control = True  # no single orphaned line across a page break

    # 0.75" margins: comfortable, ATS-safe, and lets content breathe over two pages.
    from docx.shared import Inches

    for m in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(doc.sections[0], m, Inches(0.75))


def _bottom_border(paragraph) -> None:
    """Add a thin bottom border to a paragraph (used under section headings)."""
    p = paragraph._p
    pPr = p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), "1F4E79")
    pbdr.append(bottom)
    pPr.append(pbdr)


def _run(paragraph, text, *, bold=False, size=11, color=DARK, italic=False):
    r = paragraph.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.size = Pt(size)
    r.font.color.rgb = color
    r.font.name = FONT
    return r


def _heading(doc: Document, text: str):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True  # heading never sits alone at page bottom
    _run(p, text.upper(), bold=True, size=11.5, color=ACCENT)
    _bottom_border(p)
    return p


def _bullet(doc: Document, text: str):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Pt(14)
    p.paragraph_format.line_spacing = 1.1
    _run(p, text)
    return p


def _tab_right(paragraph) -> None:
    """Configure a right-aligned tab stop at the page width for date alignment."""
    from docx.enum.text import WD_TAB_ALIGNMENT

    section = paragraph.part.document.sections[0]
    width = section.page_width - section.left_margin - section.right_margin
    paragraph.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)


# --------------------------------------------------------------------------- #
# header (shared by resume + cover letter)
# --------------------------------------------------------------------------- #
def _header(doc: Document, full_name: str, contact, *, headline: str = "") -> None:
    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_p.paragraph_format.space_after = Pt(1)
    _run(name_p, full_name.upper(), bold=True, size=22, color=ACCENT)

    if headline:
        h = doc.add_paragraph()
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        h.paragraph_format.space_after = Pt(2)
        _run(h, headline, size=11.5, color=ACCENT)

    parts = [contact.location, contact.email, contact.phone]
    parts += [link.url for link in contact.links]
    line = "  |  ".join(p for p in parts if p)
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    c.paragraph_format.space_after = Pt(4)
    _run(c, line, size=9.5, color=DARK)


# --------------------------------------------------------------------------- #
# public: resume
# --------------------------------------------------------------------------- #
def render_resume(resume: Resume, out_path: Path, profile: dict | None = None) -> Path:
    doc = Document()
    _base_styles(doc)
    _header(doc, resume.fullName, resume.contact, headline=resume.headline)

    if resume.summary:
        _heading(doc, "Professional Summary")
        p = doc.add_paragraph()
        _run(p, resume.summary)

    if resume.skills:
        _heading(doc, "Skills")
        grouped = _group_skills(resume.skills, profile)
        if len(grouped) > 1 or (grouped and grouped[0][0]):
            # Categorized: one line per group, bold label + skills.
            for label, items in grouped:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(2)
                _run(p, f"{label}: ", bold=True, size=10.5, color=ACCENT)
                _run(p, "  •  ".join(items), size=10.5)
        else:
            p = doc.add_paragraph()
            _run(p, "  •  ".join(resume.skills))

    if resume.experience:
        _heading(doc, "Experience")
        for e in resume.experience:
            head = doc.add_paragraph()
            head.paragraph_format.space_before = Pt(7)
            head.paragraph_format.space_after = Pt(0)
            head.paragraph_format.keep_with_next = True
            _tab_right(head)
            _run(head, e.role, bold=True, size=11)
            if e.company:
                _run(head, f"  |  {e.company}", size=11)
            dates = f"{e.start} – {e.end}".strip(" –")
            _run(head, f"\t{dates}", size=10, color=ACCENT)
            if e.location:
                loc = doc.add_paragraph()
                loc.paragraph_format.space_after = Pt(2)
                loc.paragraph_format.keep_with_next = True
                _run(loc, e.location, size=9.5, italic=True)
            for b in e.bullets:
                _bullet(doc, b)

    if resume.education:
        _heading(doc, "Education")
        for ed in resume.education:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(1)
            _tab_right(p)
            _run(p, ed.credential, bold=True)
            _run(p, f"  |  {ed.institution}")
            if ed.year:
                _run(p, f"\t{ed.year}", size=10, color=ACCENT)

    if resume.certifications:
        _heading(doc, "Certifications")
        for cert in resume.certifications:
            _bullet(doc, cert)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


# --------------------------------------------------------------------------- #
# public: cover letter
# --------------------------------------------------------------------------- #
def render_cover_letter(cl: CoverLetter, out_path: Path) -> Path:
    doc = Document()
    _base_styles(doc)

    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_p.paragraph_format.space_after = Pt(1)
    _run(name_p, cl.fullName.upper(), bold=True, size=20, color=ACCENT)

    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    c.paragraph_format.space_after = Pt(10)
    _run(c, cl.contactLine, size=9.5)

    g = doc.add_paragraph()
    g.paragraph_format.space_after = Pt(6)
    _run(g, cl.greeting)

    for para in cl.body:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(8)
        _run(p, para)

    s = doc.add_paragraph()
    s.paragraph_format.space_before = Pt(6)
    _run(s, cl.signOff)
    sig = doc.add_paragraph()
    _run(sig, cl.signature)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
