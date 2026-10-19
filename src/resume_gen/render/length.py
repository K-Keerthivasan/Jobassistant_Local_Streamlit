"""One-page length fitting, without rendering.

The resume standard is one full page. Two pages only when the content cannot
fit one even after trimming the least relevant material, and then page two must
be at least half full. This module decides that from an estimate of the rendered
height (Arial character widths and line heights), so it is cheap enough to run on
every generation, including fast mode where no PDF is rendered. When a PDF render
is available, render/autofit.py refines the chosen density against the real page.

Trimming only removes content (bullets, then whole roles that are not marked
`always_include`); it never adds or rewrites anything. Every trim is listed in
the report, so nothing disappears silently.
"""

from __future__ import annotations

import math
import re

from ..config import settings
from ..models import Resume

# Densities to search, tight to loose (see docx_renderer.typo).
DENSITIES = [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.30]
MIN_K, MAX_K = DENSITIES[0], DENSITIES[-1]

# Average Arial glyph width as a fraction of the font size, for mixed-case prose
# with spaces, measured from the reference resume PDF (0.447). Rounded up so a
# "fits" verdict errs safe. Bold runs are a little wider.
_CHAR_W = 0.46
_BOLD_W = 0.50
# Word's single line height for Arial, as a multiple of the font size.
_LINE_H = 1.15
# Leave a margin for estimate error so a "fits" verdict is a safe one.
_SAFETY = 0.97
# A two-page resume must fill at least this share of page two.
TWO_PAGE_MIN_FILL = 0.5
# Minimum content kept while trimming toward one page: every role keeps at least
# 4 bullets. Type shrinks (down to 10pt) before anything is trimmed.
_LEAD_MIN_BULLETS = 4
_OTHER_MIN_BULLETS = 4
_MIN_ROLES = 3
# A one-page resume should reach this share of the page; a shorter one is grown
# with more real bullets and roles from the profile.
TARGET_FILL = 0.92
_GROW_MAX_BULLETS = 6


def _page_dims() -> tuple[float, float]:
    """(width, height) in points."""
    if (settings.page_size or "letter").lower() == "a4":
        return 595.276, 841.89
    return 612.0, 792.0


def _lines(text: str, size: float, width_pt: float, bold: bool = False) -> int:
    chars_per_line = max(1.0, width_pt / (size * (_BOLD_W if bold else _CHAR_W)))
    return max(1, math.ceil(len((text or "").replace("**", "")) / chars_per_line))


def estimate_height(resume: Resume, k: float, profile: dict | None = None) -> tuple[float, float]:
    """(content height, usable page height) in points at density ``k``."""
    from .docx_renderer import _contact_line, _group_skills, typo

    t = typo(k)
    page_w, page_h = _page_dims()
    margin = t["margin_in"] * 72.0
    width = page_w - 2 * margin
    bullet_width = width - 14
    body_line = t["body"] * _LINE_H * t["line"]
    bullet_line = t["body"] * _LINE_H * t["bullet_line"]

    def heading() -> float:
        return t["head_before"] + t["heading_size"] * _LINE_H * t["line"] + t["head_after"] + 3

    def bullet(text: str) -> float:
        return _lines(text, t["body"], bullet_width) * bullet_line + t["bullet_after"]

    h = t["name_size"] * _LINE_H + 1
    h += _lines(_contact_line(resume.contact), t["contact_size"], width) * t["contact_size"] * _LINE_H + 2

    if resume.summaryPoints:
        h += heading() + sum(bullet(p) for p in resume.summaryPoints)
    elif resume.summary:
        h += heading() + _lines(resume.summary, t["body"], width) * body_line + t["after"]

    if resume.skills:
        h += heading()
        for label, items in _group_skills(resume.skills, profile):
            text = f"{label}: " + ", ".join(items)
            h += _lines(text, t["skills_size"], width) * t["skills_size"] * _LINE_H * t["line"]
            h += t["skills_after"]

    if resume.experience:
        h += heading()
        for i, e in enumerate(resume.experience):
            head = f"{e.role}  |  {e.company}    {e.dates or e.start + ' to ' + e.end}"
            h += (t["exp_before"] if i else 0) + _lines(head, t["body"], width, bold=True) * body_line + 1
            h += sum(bullet(b) for b in e.bullets)

    if resume.education:
        h += heading()
        for ed in resume.education:
            text = f"{ed.credential}  |  {ed.institution}    {ed.year}"
            h += _lines(text, t["body"], width) * body_line + 1
        if resume.licences:
            h += body_line + 3

    if resume.certifications:
        h += heading() + sum(bullet(c) for c in resume.certifications)

    return h, page_h - 2 * margin


def _fill(resume: Resume, k: float, profile: dict | None) -> float:
    """Estimated content height in pages (1.0 == exactly one full page)."""
    h, usable = estimate_height(resume, k, profile)
    return h / usable


def _best_k(resume: Resume, profile: dict | None, pages: int) -> float | None:
    """Loosest density whose estimate fits within ``pages`` pages, or None."""
    fitting = [k for k in DENSITIES if _fill(resume, k, profile) <= pages * _SAFETY]
    return max(fitting) if fitting else None


def _always_included(profile: dict | None) -> set[str]:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return {norm(e.get("company", "")) for e in (profile or {}).get("experience", [])
            if e.get("always_include")}


def _trim_steps(resume: Resume, profile: dict | None):
    """Yield (description, trimmed copy) one trim at a time, least relevant
    first. Roles are already ordered most relevant first."""
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    keep_roles = _always_included(profile)
    r = resume.model_copy(deep=True)

    # 1. Shorten the less relevant roles, from the bottom up, one bullet at a time.
    changed = True
    while changed:
        changed = False
        for e in reversed(r.experience[1:]):
            if len(e.bullets) > _OTHER_MIN_BULLETS:
                dropped = e.bullets.pop()
                changed = True
                yield f"bullet dropped from {e.company}: {dropped}", r.model_copy(deep=True)
                break

    # 2. Shorten the lead role.
    if r.experience:
        lead = r.experience[0]
        while len(lead.bullets) > _LEAD_MIN_BULLETS:
            dropped = lead.bullets.pop()
            yield f"bullet dropped from {lead.company}: {dropped}", r.model_copy(deep=True)

    # 3. Drop whole roles that are not always included, least relevant first.
    for i in range(len(r.experience) - 1, 0, -1):
        if len(r.experience) <= _MIN_ROLES:
            break
        e = r.experience[i]
        if norm(e.company) in keep_roles:
            continue
        r.experience.pop(i)
        yield f"role omitted to fit one page: {e.company}", r.model_copy(deep=True)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9#.+]+", (text or "").lower().replace("**", "")) if len(t) >= 4}


def _grow(resume: Resume, profile: dict | None) -> tuple[Resume, list[str]]:
    """Add real content until the page fills at the loosest density: first more
    bullets from each included role's own profile facts (up to 6 a role), then
    roles left out, with 4 facts each. Only profile facts are used, never new text."""
    from ..models import ExperienceItem

    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    r = resume.model_copy(deep=True)
    added: list[str] = []
    prof_exp = (profile or {}).get("experience", []) or []
    by_company = {norm(p.get("company", "")): p for p in prof_exp}

    def full() -> bool:
        return _fill(r, MAX_K, profile) >= TARGET_FILL

    for e in r.experience:
        if full():
            break
        p = by_company.get(norm(e.company))
        if not p:
            continue
        have = [_tokens(b) for b in e.bullets]
        for fact in p.get("facts", []) or []:
            if full() or len(e.bullets) >= _GROW_MAX_BULLETS:
                break
            ft = _tokens(fact)
            if any(len(ft & h) >= 3 for h in have):
                continue                      # already said in another bullet
            e.bullets.append(fact)
            have.append(ft)
            added.append(f"bullet from profile added to {e.company}")
    present = {norm(e.company) for e in r.experience}
    for p in prof_exp:
        if full():
            break
        if norm(p.get("company", "")) in present or not p.get("facts"):
            continue
        r.experience.append(ExperienceItem(
            company=p.get("company", ""), role=p.get("role", ""), location=p.get("location", ""),
            start=p.get("start", ""), end=p.get("end", ""), dates=p.get("dates", "") or "",
            bullets=list(p["facts"])[:4]))
        added.append(f"role added from profile to fill the page: {p.get('company', '')}")
    return r, added


def fit_length(resume: Resume, profile: dict | None = None) -> tuple[Resume, float, dict]:
    """Return ``(resume, density, report)``: the resume (trimmed only if it had to
    be, to fit one page), the density to render it at, and a report with the
    target page count, the estimated fill and every trim made."""
    report: dict = {"method": "estimate", "trimmed": []}

    k = _best_k(resume, profile, 1)
    if k is not None:
        # Fits one page. If it can't fill the page even at the loosest type, add
        # real content from the profile until it does (or nothing is left).
        if k == MAX_K and _fill(resume, MAX_K, profile) < TARGET_FILL and profile:
            grown, added = _grow(resume, profile)
            gk = _best_k(grown, profile, 1)
            if added and gk is not None:
                resume, k = grown, gk
                report["grown"] = added
        report.update(pages_target=1, density=k,
                      estimated_fill=round(_fill(resume, k, profile), 3))
        return resume, k, report

    trims: list[str] = []
    for note, candidate in _trim_steps(resume, profile):
        trims.append(note)
        k = _best_k(candidate, profile, 1)
        if k is not None:
            report.update(pages_target=1, density=k, trimmed=trims,
                          estimated_fill=round(_fill(candidate, k, profile), 3))
            return candidate, k, report

    # Trimming cannot get it onto one page: two pages, untrimmed, with page two
    # at least half full. The loosest density that stays within two pages gives
    # the fullest second page.
    k = _best_k(resume, profile, 2) or MIN_K
    fill = _fill(resume, k, profile)
    report.update(pages_target=2, density=k, estimated_fill=round(fill, 3),
                  page_two_fill_ok=fill - 1 >= TWO_PAGE_MIN_FILL)
    return resume, k, report
