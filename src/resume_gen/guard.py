"""Truth-guard: cross-check generated content against the master profile and
deterministically repair the parts that must never be model-invented.

Local models will fabricate despite a strict prompt (wrong name, invented
skills, made-up metrics, scrambled schools). Structured output guarantees valid
JSON, not truthful JSON. This layer closes that gap:

- IDENTITY (name, contact, education): overwritten verbatim from the profile.
  These need no creativity, so we never let the model touch them.
- SKILLS: filtered to only those that exist in the profile.
- BULLETS: scanned for numbers/metrics not present in the source facts; such
  bullets are flagged (and, in strict mode, the fabricated figure is stripped).

Returns a QA report listing every change/violation, so nothing is silent.
"""

from __future__ import annotations

import re

from .models import Contact, EducationItem, Link, Resume

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|\+|x|years?|yrs?|k|months?)?", re.I)


# --------------------------------------------------------------------------- #
def _profile_skill_text(profile: dict) -> str:
    chunks: list[str] = []
    for group in (profile.get("skills") or {}).values():
        chunks.extend(group)
    return " | ".join(chunks).lower()


def _profile_number_text(profile: dict) -> str:
    """All source text the model is allowed to draw numbers from."""
    parts: list[str] = []
    for e in profile.get("experience", []):
        parts.extend(e.get("facts", []))
    for p in profile.get("projects", []):
        parts.append(p.get("description", ""))
    parts.append(profile.get("summary_base", ""))
    return " ".join(parts)


def _numbers_in(text: str) -> set[str]:
    return {m.group().strip().lower() for m in _NUMBER_RE.finditer(text)}


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _best_experience_match(gen, prof_exp: list[dict]) -> dict | None:
    """Match a generated experience entry to the profile role it came from, by
    token overlap on company (then role). Returns None if nothing plausibly
    matches (so we flag rather than silently mis-assign)."""
    gen_co = _tokens(gen.company) - {"company", "name"}  # ignore placeholder tokens
    gen_role = _tokens(gen.role)
    best, best_score = None, 0.0
    for p in prof_exp:
        co = _tokens(p.get("company", ""))
        role = _tokens(p.get("role", ""))
        score = len(gen_co & co) * 3 + len(gen_role & role)
        if score > best_score:
            best, best_score = p, score
    if best is None:
        return None
    # Confident if a company token matches, OR the role overlaps strongly
    # (handles placeholder/blank company like "Company Name").
    company_match = bool(_tokens(best.get("company", "")) & gen_co)
    role_match = len(_tokens(best.get("role", "")) & gen_role) >= 2
    return best if (company_match or role_match) else None


def _word_in(needle: str, haystack: str) -> bool:
    """Whole-token containment with boundaries = non-alphanumeric / string ends.
    Handles tech tokens with symbols ('c#', 'node.js', 'n8n')."""
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


# filler words that must not, on their own, ground a skill
_SKILL_STOPWORDS = {
    "integration", "design", "management", "development", "control", "version",
    "systems", "system", "tools", "tool", "framework", "frameworks", "programming",
    "software", "services", "service", "modern", "responsive", "scalable", "and",
    "with", "the", "of", "for", "based", "stack", "full", "end",
}


def _grounded(atom: str, skill_text: str) -> bool:
    """True if a skill atom is supported by the profile's skill inventory.

    Direct substring first (handles 'n8n' in 'n8n automation'); otherwise require
    a shared, meaningful token (so 'Git version control' grounds via 'git', but
    '.NET' / 'Scrum' / 'Database design' do not)."""
    t = atom.lower().split("(")[0].strip()
    if not t:
        return False
    # whole-token match (symbol-aware boundaries so 'java' != 'javascript',
    # but 'c#' and 'node.js' still match)
    if _word_in(t, skill_text) or _word_in(t.rstrip("s"), skill_text):
        return True
    profile_tokens = set(re.findall(r"[a-z0-9#.+]+", skill_text)) - _SKILL_STOPWORDS
    atom_tokens = {w for w in re.findall(r"[a-z0-9#.+]+", t) if len(w) >= 2} - _SKILL_STOPWORDS
    return bool(atom_tokens & profile_tokens)


# --------------------------------------------------------------------------- #
def enforce(resume: Resume, profile: dict, *, strict: bool = False) -> tuple[Resume, dict]:
    report: dict = {"identity_fixed": [], "skills_dropped": [],
                    "fabricated_numbers": [], "education_replaced": False}

    # --- IDENTITY -----------------------------------------------------------
    true_name = profile.get("full_name", resume.fullName)
    if resume.fullName.strip() != true_name:
        report["identity_fixed"].append(f"name: '{resume.fullName}' -> '{true_name}'")
        resume.fullName = true_name

    c = profile.get("contact", {})
    resume.contact = Contact(
        email=c.get("email", ""),
        phone=c.get("phone", ""),
        location=c.get("location", ""),
        links=[Link(label=l.get("label", ""), url=l.get("url", "")) for l in c.get("links", [])],
    )

    # --- EDUCATION (verbatim from profile) ----------------------------------
    prof_edu = profile.get("education", [])
    if prof_edu:
        resume.education = [
            EducationItem(institution=e.get("institution", ""),
                          credential=e.get("credential", ""),
                          year=e.get("year", ""))
            for e in prof_edu
        ]
        report["education_replaced"] = True

    # --- CERTIFICATIONS -----------------------------------------------------
    true_certs = profile.get("certifications") or []
    invented_certs = [c for c in resume.certifications if c not in true_certs]
    if invented_certs:
        report["skills_dropped"].extend(f"cert:{c}" for c in invented_certs)
    resume.certifications = list(true_certs)

    # --- SKILLS (keep only those grounded in the profile) -------------------
    # Models often emit compound tokens ("JavaScript/TypeScript", "C#/.NET").
    # Split into atoms and keep only the grounded ones, so a real skill isn't
    # dropped because of formatting and an unreal one ("./NET") isn't smuggled in.
    skill_text = _profile_skill_text(profile)
    kept: list[str] = []
    seen: set[str] = set()
    for s in resume.skills:
        atoms = [a.strip() for a in re.split(r"\s*[/&,]\s*", s) if a.strip()]
        for atom in atoms:
            if _grounded(atom, skill_text):
                key = atom.lower()
                if key not in seen:
                    seen.add(key)
                    kept.append(atom)
            else:
                report["skills_dropped"].append(atom)
    resume.skills = kept

    # --- EXPERIENCE STRUCTURE (company/role/dates/location from profile) -----
    # The model decides WHICH roles to include and writes bullets; it must never
    # invent the company, title, dates, or location. Match each generated entry
    # back to a profile role and overwrite those fields verbatim.
    prof_exp = profile.get("experience", [])
    for e in resume.experience:
        match = _best_experience_match(e, prof_exp)
        if match is None:
            report.setdefault("unmatched_experience", []).append(
                {"company": e.company, "role": e.role})
            continue
        fixed = []
        if e.company.strip() != match.get("company", ""):
            fixed.append(f"company '{e.company}' -> '{match['company']}'")
            e.company = match.get("company", e.company)
        # role can be tailored, but dates/location are facts
        for fld, key in (("start", "start"), ("end", "end"), ("location", "location")):
            true_val = match.get(key, "")
            if true_val and getattr(e, fld).strip() != true_val:
                fixed.append(f"{fld} '{getattr(e, fld)}' -> '{true_val}'")
                setattr(e, fld, true_val)
        if fixed:
            report.setdefault("experience_fixed", []).append(
                {"company": e.company, "changes": fixed})

    # --- BULLET CONTENT (flag mentions of ungrounded technologies) ----------
    dropped_lower = {d.lower() for d in report["skills_dropped"]}
    if dropped_lower:
        for e in resume.experience:
            for b in e.bullets:
                hits = [d for d in dropped_lower if re.search(rf"\b{re.escape(d)}\b", b.lower())]
                if hits:
                    report.setdefault("ungrounded_in_bullets", []).append(
                        {"company": e.company, "terms": hits, "bullet": b})

    # --- BULLET METRICS (flag/strip fabricated numbers) ---------------------
    allowed_numbers = _numbers_in(_profile_number_text(profile))
    for e in resume.experience:
        new_bullets = []
        for b in e.bullets:
            bad = [n for n in _numbers_in(b) if n not in allowed_numbers and re.search(r"\d", n)]
            if bad:
                report["fabricated_numbers"].append(
                    {"company": e.company, "bullet": b, "numbers": sorted(bad)}
                )
                if strict:
                    b = _strip_metrics(b)
            new_bullets.append(b)
        e.bullets = new_bullets

    return resume, report


# count-nouns that read fine as "multiple <noun>" once the fake figure is removed
_COUNT_NOUNS = (r"concurrent\s+)?(projects|clients|customers|interactions|accounts|"
                r"users|websites|sites|dashboards|applications|tickets|records|teams")


def _strip_metrics(bullet: str) -> str:
    """Surgically neutralise fabricated figures while keeping the sentence intact.
    The call site only invokes this for bullets with non-profile numbers, so we
    treat every metric here as fabricated and remove it cleanly."""
    b = bullet
    # "10+ concurrent clients" / "200 accounts" -> "multiple clients"
    b = re.sub(rf"\b\d+\s*\+?\s*({_COUNT_NOUNS})\b", r"multiple \1\2", b, flags=re.I)
    # trailing "by/to/of 40%" and bare "40%"
    b = re.sub(r"\s*\b(?:by|to|of|up to|around|over)\s+\d+(?:[.,]\d+)?\s*%", "", b)
    b = re.sub(r"\s*\d+(?:[.,]\d+)?\s*%", "", b)
    # "3+ years", "6 months"
    b = re.sub(r"\b\d+\s*\+?\s*(?:years?|yrs?|months?)\b", "", b, flags=re.I)
    # any leftover "N+" or standalone count
    b = re.sub(r"\b\d+\s*\+", "", b)
    # tidy punctuation/whitespace
    b = re.sub(r"\s+([,.;])", r"\1", b)
    b = re.sub(r"(,\s*)+", ", ", b)
    b = re.sub(r"\s{2,}", " ", b).strip(" ,;")
    if b and not b.endswith("."):
        b += "."
    return b


def has_violations(report: dict) -> bool:
    return any(report.get(k) for k in (
        "skills_dropped", "fabricated_numbers", "identity_fixed",
        "experience_fixed", "unmatched_experience", "ungrounded_in_bullets",
    ))
