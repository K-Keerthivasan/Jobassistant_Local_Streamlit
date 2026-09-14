"""The lane-status guard in the generation path (brief 2.4 and section 9).

    A skill at `building` or `not_yet` never appears as experience: not in a
    resume, a cover letter, a fit sentence, a screening answer or an outreach
    email. A `partial` skill appears only with its limit honoured.

Two halves:

* ``lane_context(lane, grade)`` turns a lane (and the job's grade, when there is
  one) into the sets the pipeline needs: claimable terms, partial limits,
  forbidden terms, gap flags, positioning.
* ``apply_to_resume`` / ``scan_text`` enforce it deterministically after the
  model has written, so a fabricated claim cannot survive because a prompt was
  ignored. ``directive`` is the prompt block that tells the model the same thing
  up front.
"""

from __future__ import annotations

import re

from ..models import Resume
from .schema import Lane, Skill

# Terms that are too generic to block on their own even when they alias a gap
# skill (they appear in ordinary prose about real work).
_TOO_GENERIC = {"testing", "sql", "python", "javascript", "typescript", "excel", "cloud", "docker",
                "design", "agile", "jira", "git", "apis", "api", "r", "x", "fx", "ae", "comp", "3d",
                "lighting", "rendering", "animation", "shading", "color", "colour", "certification",
                "certified", "portfolio", "console", "simulation", "online", "physics", "menus", "hud",
                "scripting", "performance", "documentation", "reporting", "insights", "analytics",
                "communication", "presentations", "demos", "proposals", "integrations", "content"}


def _word_re(term: str) -> re.Pattern:
    return re.compile(rf"(?<![a-z0-9+#]){re.escape(term)}(?![a-z0-9+#])", re.I)


def _terms(skill: Skill, *, generic_ok: bool) -> list[str]:
    out = []
    for t in skill.match_terms():
        if len(t) < 2:
            continue
        if not generic_ok and t in _TOO_GENERIC:
            continue
        out.append(t)
    return out


def lane_context(lane: Lane | None, grade: dict | None = None) -> dict:
    """Everything the pipeline needs from the lane, precomputed."""
    if lane is None:
        return {"lane": "", "held_terms": [], "held_names": [], "partial": [], "forbidden": [],
                "forbidden_names": [], "gap_flags": [], "positioning": "", "fit_sentence": "",
                "evidence": []}
    held = [s for s in lane.skills if s.status == "held"]
    partial = [s for s in lane.skills if s.status == "partial"]
    blocked = [s for s in lane.skills if not s.claimable]
    grade = grade or {}
    # Evidence lines the model may draw on (only claimable, only real evidence).
    evidence = [{"skill": s.name, "status": s.status, "evidence": s.evidence,
                 "limit": s.limit if s.status == "partial" else ""}
                for s in lane.skills if s.fit_sentence_source]
    return {
        "lane": lane.slug,
        "lane_title": lane.title,
        "held_names": [s.name for s in held],
        "held_terms": sorted({t for s in held for t in _terms(s, generic_ok=True)}),
        "partial": [{"name": s.name, "limit": s.limit, "terms": _terms(s, generic_ok=True)} for s in partial],
        "forbidden_names": [s.name for s in blocked],
        # name -> terms, so a hit can be reported by skill name
        "forbidden": [{"name": s.name, "status": s.status, "terms": _terms(s, generic_ok=False)} for s in blocked],
        "gap_flags": list(grade.get("gap_flags") or []),
        "tier": grade.get("tier", ""),
        "fit_sentence": grade.get("fit_sentence", ""),
        "positioning": lane.positioning,
        "evidence": evidence,
    }


def scan_text(text: str, ctx: dict) -> list[dict]:
    """Forbidden-skill mentions in a piece of prose: [{name, term, snippet}]."""
    hits = []
    for f in ctx.get("forbidden") or []:
        for term in f["terms"]:
            m = _word_re(term).search(text or "")
            if m:
                s = max(0, m.start() - 40)
                hits.append({"name": f["name"], "status": f["status"], "term": term,
                             "snippet": (text or "")[s:m.end() + 40].strip()})
                break
    return hits


def apply_to_resume(resume: Resume, ctx: dict, *, strict: bool = False) -> tuple[Resume, dict]:
    """Strip forbidden skills from the Skills section; flag (strict: drop) bullets
    and summary sentences that present a forbidden skill as experience."""
    report: dict = {"lane": ctx.get("lane", ""), "skills_blocked": [], "bullets_flagged": [],
                    "bullets_dropped": [], "summary_flagged": [], "partial_used": []}
    if not ctx.get("lane"):
        return resume, report

    forbidden = ctx.get("forbidden") or []
    partial_terms = {t: p["name"] for p in ctx.get("partial") or [] for t in p["terms"]}

    def _forbidden_hit(text: str) -> str:
        for f in forbidden:
            for term in f["terms"]:
                if _word_re(term).search(text):
                    return f["name"]
        return ""

    # Skills: a blocked skill never renders, regardless of the profile inventory.
    kept = []
    for s in resume.skills:
        name = _forbidden_hit(s)
        # Exact name match on the skill string also blocks (e.g. "Tableau").
        if not name:
            for f in forbidden:
                if s.strip().lower() == f["name"].lower():
                    name = f["name"]
        if name:
            report["skills_blocked"].append({"skill": s, "matrix_skill": name})
            continue
        kept.append(s)
        low = s.lower()
        for term, pname in partial_terms.items():
            if _word_re(term).search(low) and pname not in report["partial_used"]:
                report["partial_used"].append(pname)
    resume.skills = kept

    # Bullets and summary: flag every mention; strict mode drops the bullet.
    for e in resume.experience:
        new_bullets = []
        for b in e.bullets:
            name = _forbidden_hit(b)
            if name:
                entry = {"company": e.company, "matrix_skill": name, "bullet": b}
                if strict:
                    report["bullets_dropped"].append(entry)
                    continue
                report["bullets_flagged"].append(entry)
            new_bullets.append(b)
        e.bullets = new_bullets
    name = _forbidden_hit(resume.summary or "")
    if name:
        report["summary_flagged"].append(name)
        if strict:
            # Remove the offending sentence rather than the whole summary.
            sentences = re.split(r"(?<=[.!?])\s+", resume.summary)
            resume.summary = " ".join(s for s in sentences if not _forbidden_hit(s)).strip()
    return resume, report


def directive(ctx: dict, *, for_cover_letter: bool = False) -> str:
    """Prompt block: what the matrix allows, with limits, and what it forbids."""
    if not ctx.get("lane"):
        return ""
    lines = [
        "\nLANE MATRIX (authoritative on what the candidate can claim; it never overrides CANDIDATE_PROFILE facts):",
        f"  lane: {ctx.get('lane_title') or ctx['lane']}",
    ]
    if ctx.get("held_names"):
        lines.append("  HELD (may be foregrounded where the profile supports them): " + ", ".join(ctx["held_names"]))
    if ctx.get("partial"):
        lines.append("  PARTIAL (may be mentioned ONLY with this exact limit stated in the same sentence):")
        for p in ctx["partial"]:
            lines.append(f"    - {p['name']}: {p['limit']}")
    if ctx.get("forbidden_names"):
        lines.append("  NEVER PRESENT AS EXPERIENCE (no exposure or still learning; do not list, imply or hint): "
                     + ", ".join(ctx["forbidden_names"]))
    if for_cover_letter and ctx.get("gap_flags"):
        lines.append("  GAPS THE POSTING HARD-REQUIRES (name these directly in paragraph three, never hide them): "
                     + "; ".join(ctx["gap_flags"]))
    if for_cover_letter and ctx.get("fit_sentence"):
        lines.append("  EVIDENCE-TRACED FIT (the only claims about matrix skills you may build on): " + ctx["fit_sentence"])
    return "\n".join(lines) + "\n"
