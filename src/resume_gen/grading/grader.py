"""Grade a posting against its lane matrix (brief section 4).

    Tier A  every Must-tier skill the posting hard-requires is `held`
    Tier B  one or two hard-required Must-tier skills are not `held`
    Tier C  three or more, or a Later-tier item is hard-required as a prerequisite

Gap flags name every unmet hard requirement. The fit sentence is assembled only
from `evidence` text of claimable skills that matched the posting, and the skill
ids it drew on are stored so the UI can show the trace. A skill at `building` or
`not_yet` can never contribute a word to it.
"""

from __future__ import annotations

import re
from datetime import datetime

from .. import lanes as lane_data
from ..lanes.schema import Lane, Skill
from .requirements import Requirements, extract_requirements
from .seniority import check_seniority

_TIER_ORDER = {"must": 0, "important": 1, "optional": 2, "later": 3, "not_required": 4}
# Evidence that names a real place or artefact ranks above bare self-assessment.
_CONCRETE = re.compile(
    r"certify|bill gosling|k2|haply|materia|fanshawe|github|k2_press|clubjunk|jkr|death bridge|"
    r"best buy|nuke|unity|unreal|n8n|ollama|hermes|repo|client|channel|pipeline|engine", re.I)
_SELF_ASSESSED = re.compile(r"self-assessed", re.I)


def _word_re(term: str) -> re.Pattern:
    """Whole-token match that survives symbols (c++, c#, node.js, ci/cd)."""
    return re.compile(rf"(?<![a-z0-9+#]){re.escape(term)}(?![a-z0-9+#])", re.I)


def _matches(skill: Skill, lines: list[str]) -> list[str]:
    hits = []
    for term in skill.match_terms():
        if len(term) < 2:
            continue
        rx = _word_re(term)
        if any(rx.search(ln) for ln in lines):
            hits.append(term)
    return hits


def _first_sentence(text: str, limit: int = 160) -> str:
    s = re.split(r"(?<=[.!?])\s+", (text or "").strip())[0] if text else ""
    s = s.strip().rstrip(".")
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0]


def _clean(text: str) -> str:
    """Canadian-plain: no em or en dashes, single spaces."""
    t = re.sub(r"\s*[–—]\s*", ", ", text or "")
    return re.sub(r"\s{2,}", " ", t).strip()


def build_fit_sentence(title: str, matched: list[dict]) -> tuple[str, list[str]]:
    """One sentence from evidence only. ``matched`` rows carry the Skill and where it
    matched. Returns (sentence, skill_ids_used). Empty when nothing traceable matched."""
    usable = [m for m in matched if m["skill"].fit_sentence_source]
    if not usable:
        return "", []

    def rank(m):
        s: Skill = m["skill"]
        concrete = 1 if _CONCRETE.search(s.evidence) else 0
        selfa = 1 if _SELF_ASSESSED.search(s.evidence) else 0
        where = {"hard": 0, "nice": 1, "context": 2}[m["where"]]
        return (where, _TIER_ORDER.get(s.tier, 9), -concrete, selfa, s.status != "held")

    usable.sort(key=rank)
    picked = usable[:3]
    parts, ids = [], []
    for m in picked:
        s: Skill = m["skill"]
        ev = _first_sentence(s.evidence)
        if not ev:
            continue
        if s.status == "partial":
            parts.append(f"{s.name} (partial: {_first_sentence(s.limit, 120).lower().rstrip('.')}): {ev}")
        else:
            parts.append(f"{s.name}: {ev}")
        ids.append(s.id)
    if not parts:
        return "", []
    names = [m["skill"].name for m in picked if m["skill"].id in ids]
    lead = ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]
    sentence = f"Matches the posting's {lead} requirement{'s' if len(names) > 1 else ''}. " + "; ".join(parts) + "."
    return _clean(sentence), ids


def grade(title: str, description: str, lane: Lane, *, years_line: str = "",
          fit_report_gaps: str = "") -> dict:
    """Grade one posting against one lane. Pure function of its inputs."""
    req: Requirements = extract_requirements(description)
    hard_l, nice_l, ctx_l = req.hard, req.nice, req.context
    title_l = [title or ""]

    matched: list[dict] = []
    for s in lane.skills:
        hits_hard = _matches(s, hard_l + title_l)
        hits_nice = _matches(s, nice_l) if not hits_hard else []
        hits_ctx = _matches(s, ctx_l) if not (hits_hard or hits_nice) else []
        where = "hard" if hits_hard else "nice" if hits_nice else "context" if hits_ctx else ""
        if where:
            matched.append({"skill": s, "where": where,
                            "terms": hits_hard or hits_nice or hits_ctx})

    hard_req = [m for m in matched if m["where"] == "hard"]
    must_missing = [m for m in hard_req if m["skill"].tier == "must" and m["skill"].status != "held"]
    later_prereq = [m for m in hard_req if m["skill"].tier == "later"]
    gaps = [m for m in hard_req if m["skill"].status != "held"]

    if later_prereq:
        tier, reason = "C", f"hard-requires Later-tier: {', '.join(m['skill'].name for m in later_prereq)}"
    elif not must_missing:
        tier, reason = "A", "every hard-required Must-tier skill is held" if any(m["skill"].tier == "must" for m in hard_req) else "no Must-tier skill is hard-required by the text"
    elif len(must_missing) <= 2:
        tier, reason = "B", f"{len(must_missing)} hard-required Must-tier skill(s) not held"
    else:
        tier, reason = "C", f"{len(must_missing)} hard-required Must-tier skills not held"

    gap_flags = []
    for m in gaps:
        s = m["skill"]
        gap_flags.append(f"{s.name} ({s.status.replace('_', ' ')})" if s.status != "partial"
                         else f"{s.name} (partial: {_first_sentence(s.limit, 90).rstrip('.')})")
    for m in later_prereq:
        if m["skill"].status == "held":
            continue
        tag = f"{m['skill'].name} (later tier, hard-required)"
        if tag not in gap_flags:
            gap_flags.append(tag)

    fit_sentence, evidence_ids = build_fit_sentence(title, matched)

    return {
        "lane": lane.slug,
        "lane_no": lane.lane,
        "tier": tier,
        "tier_reason": reason,
        "hard_required": [{"skill_id": m["skill"].id, "name": m["skill"].name, "tier": m["skill"].tier,
                           "status": m["skill"].status, "terms": m["terms"]} for m in hard_req],
        "nice_to_have": [{"skill_id": m["skill"].id, "name": m["skill"].name, "status": m["skill"].status,
                          "terms": m["terms"]} for m in matched if m["where"] == "nice"],
        "mentioned": [{"skill_id": m["skill"].id, "name": m["skill"].name, "status": m["skill"].status}
                      for m in matched if m["where"] == "context"],
        "gap_flags": gap_flags,
        "gap_flags_text": " | ".join(gap_flags) if gap_flags else "none",
        "must_missing": [m["skill"].name for m in must_missing],
        "later_prerequisites": [m["skill"].name for m in later_prereq],
        "fit_sentence": fit_sentence,
        "evidence_skill_ids": evidence_ids,
        "partial_limits": [{"skill_id": m["skill"].id, "name": m["skill"].name, "limit": m["skill"].limit}
                           for m in matched if m["skill"].status == "partial"],
        "never_claim": [s.name for s in lane.unclaimable_skills()
                        if any(s.id == m["skill"].id for m in matched)],
        "upstream_gap_flags": fit_report_gaps or "",
        "requirements": {"hard": len(hard_l), "nice": len(nice_l), "context": len(ctx_l)},
        "matrix_version": lane.version,
        "graded_at": datetime.now().isoformat(timespec="seconds"),
    }


def grade_job(job) -> tuple[dict, dict]:
    """Grade a QueuedJob-like object (needs title, description, lane/lane_slug, fit).
    Returns (grade, seniority). An unresolved lane yields an empty grade with a reason."""
    lane = lane_data.get_lane(getattr(job, "lane_slug", "") or "") or lane_data.resolve_lane(getattr(job, "lane", ""))
    fit = getattr(job, "fit", None) or {}
    years_line = fit.get("years_line", "") if isinstance(fit, dict) else ""
    seniority = check_seniority(getattr(job, "title", ""), getattr(job, "description", ""), years_line)
    if lane is None:
        return ({"tier": "", "tier_reason": "no lane resolved; set the lane and regrade",
                 "gap_flags": [], "gap_flags_text": "", "fit_sentence": "", "evidence_skill_ids": [],
                 "graded_at": datetime.now().isoformat(timespec="seconds")}, seniority)
    g = grade(getattr(job, "title", ""), getattr(job, "description", ""), lane,
              years_line=years_line, fit_report_gaps=fit.get("gap_flags", "") if isinstance(fit, dict) else "")
    return g, seniority
