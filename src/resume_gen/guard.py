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

from .models import (
    ApplicationEmail,
    Contact,
    CoverLetter,
    EducationItem,
    ExperienceItem,
    Link,
    Resume,
)

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|\+|x|years?|yrs?|k|months?)?", re.I)


# --------------------------------------------------------------------------- #
def _profile_skill_text(profile: dict) -> str:
    chunks: list[str] = []
    for group in (profile.get("skills") or {}).values():
        chunks.extend(group)
    return " | ".join(chunks).lower()


def _display_location(profile: dict, target_location: str = "") -> str:
    """Show the precise home city (London) only for local jobs; for jobs elsewhere
    show a broader-but-true location (e.g. 'Ontario, Canada') so applying out of
    town doesn't surface 'London'."""
    c = profile.get("contact", {})
    full = c.get("location", "")
    general = c.get("location_general", "") or full
    tl = (target_location or "").lower()
    home_city = full.split(",")[0].strip().lower() if full else ""
    if not tl:                      # no target info -> default to home
        return full
    if home_city and home_city in tl:   # job is in the home city -> show it
        return full
    return general                  # remote / elsewhere -> broader true location


def _profile_skills_flat(profile: dict) -> list[str]:
    """All profile skills as a flat, de-duplicated list, in group order."""
    out: list[str] = []
    seen: set[str] = set()
    for group in (profile.get("skills") or {}).values():
        for s in group:
            if s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
    return out


def _backfill_skills(kept: list[str], profile: dict, persona: dict | None,
                     target: int = 10) -> list[str]:
    """Ensure a usable Skills section even when the model under-produces. Tops up
    `kept` from the profile's real skills, leading with the persona's foreground
    skills so the section stays role-relevant. Never adds anything off-profile."""
    have = {s.lower() for s in kept}
    pool = [s for s in _profile_skills_flat(profile) if s.lower() not in have]

    # Order the pool so persona-relevant skills come first.
    if persona and persona.get("foreground_skills"):
        fg = re.findall(r"[a-z0-9#.+]+", persona["foreground_skills"].lower())
        fg = {t for t in fg if len(t) >= 2} - _SKILL_STOPWORDS
        def relevance(skill: str) -> int:
            toks = set(re.findall(r"[a-z0-9#.+]+", skill.lower()))
            return -len(toks & fg)  # more overlap -> earlier
        pool.sort(key=relevance)

    out = list(kept)
    for s in pool:
        if len(out) >= target:
            break
        out.append(s)
    return out


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


# Generic words that don't, on their own, tie a bullet to a real fact.
_PROSE_STOP = set(
    "a an the and or of to in for with on by at as from into using used use over under across their our we "
    "is are was were be been being able about more most than then so via per up down out this that these those it its "
    "led lead leading build built building develop developed developing development create created creating "
    "design designed designing implement implemented implementing manage managed managing work worked working "
    "deliver delivered delivering support supported supporting provide provided providing improve improved improving "
    "increase increased increasing reduce reduced reducing achieve achieved achieving enable enabled enabling "
    "new key real time end full scalable robust various multiple several including include included high low "
    "results driven proven track record passionate cutting edge level role roles responsible resulting result "
    "team teams project projects system systems application applications data customer customers user users "
    "architected pioneered directed spearheaded".split()
)


def _content_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9#.+]+", (text or "").lower())
            if len(t) >= 3 and t not in _PROSE_STOP}


def _facts_tokens(match: dict) -> set[str]:
    parts = list(match.get("facts", [])) + [match.get("role", ""), match.get("company", "")]
    parts += match.get("tags", []) or []
    return _content_tokens(" ".join(parts))


def _topup_from_facts(bullets: list[str], facts: list[str], target: int) -> list[str]:
    """Pad a thin role up to `target` bullets using its truthful profile facts that
    aren't already represented (so the resume fills the page without fabrication)."""
    out = list(bullets)
    have = [_content_tokens(b) for b in out]
    for fact in facts:
        if len(out) >= target:
            break
        ft = _content_tokens(fact)
        if any(len(ft & h) >= 3 for h in have):   # already covered by a kept bullet
            continue
        out.append(fact)
        have.append(ft)
    return out


def _strip_experience_claims(text: str) -> str:
    """Remove fabricated 'N+ years of experience' style claims (the profile has no
    total-years figure, so any such claim is invented)."""
    t = text or ""
    t = re.sub(r"\bwith\s+\d+\s*\+?\s*years?\b[^.,|]*", "", t, flags=re.I)
    t = re.sub(r"\b\d+\s*\+?\s*years?\s+of\s+(?:[\w/&-]+\s+){0,4}experience\b", "experience", t, flags=re.I)
    t = re.sub(r"\b\d+\s*\+?\s*years?\b", "", t, flags=re.I)
    t = re.sub(r"\s+([.,;])", r"\1", t)          # no space before punctuation
    t = re.sub(r"\s{2,}", " ", t).strip(" ,;–-")
    return t


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
def enforce(resume: Resume, profile: dict, *, strict: bool = False,
            persona: dict | None = None, target_location: str = "",
            extra_skills: list[str] | None = None) -> tuple[Resume, dict]:
    """`extra_skills`: skills the USER has personally confirmed they have (via the
    skill-gap Q&A). They aren't in the master profile but the user attested to them,
    so they're treated as grounded for this run instead of being stripped."""
    report: dict = {"identity_fixed": [], "skills_dropped": [],
                    "fabricated_numbers": [], "education_replaced": False}
    _extra = {s.strip().lower() for s in (extra_skills or []) if s.strip()}

    # --- IDENTITY -----------------------------------------------------------
    true_name = profile.get("full_name", resume.fullName)
    if resume.fullName.strip() != true_name:
        report["identity_fixed"].append(f"name: '{resume.fullName}' -> '{true_name}'")
        resume.fullName = true_name

    c = profile.get("contact", {})
    resume.contact = Contact(
        email=c.get("email", ""),
        phone=c.get("phone", ""),
        location=_display_location(profile, target_location),
        links=[Link(label=l.get("label", ""), url=l.get("url", "")) for l in c.get("links", [])],
    )

    # --- HEADLINE + SUMMARY (strip invented "N years of experience" + metrics) --
    allowed_numbers = _numbers_in(_profile_number_text(profile))

    def _clean_prose(text: str) -> str:
        out = _strip_experience_claims(text)
        if strict:
            bad = [n for n in _numbers_in(out) if n not in allowed_numbers and re.search(r"\d", n)]
            if bad:
                out = _strip_metrics(out)
        return out

    new_headline = _clean_prose(resume.headline)
    if new_headline != resume.headline:
        report.setdefault("headline_fixed", []).append(f"'{resume.headline}' -> '{new_headline}'")
        resume.headline = new_headline
    new_summary = _clean_prose(resume.summary)
    if new_summary != resume.summary:
        report["summary_fixed"] = True
        resume.summary = new_summary

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
            if _grounded(atom, skill_text) or atom.lower() in _extra:
                key = atom.lower()
                if key not in seen:
                    seen.add(key)
                    kept.append(atom)
                    if not _grounded(atom, skill_text):
                        report.setdefault("skills_confirmed", []).append(atom)
            else:
                report["skills_dropped"].append(atom)

    # Backfill from the profile so a relevant Skills section always renders, even
    # when the model returned too few grounded skills.
    if len(kept) < 6:
        filled = _backfill_skills(kept, profile, persona)
        added = [s for s in filled if s not in kept]
        if added:
            report["skills_backfilled"] = added
        kept = filled
    resume.skills = kept

    # --- EXPERIENCE STRUCTURE (company/role/dates/location from profile) -----
    # The model decides WHICH roles to include and writes bullets; it must never
    # invent the company, title, dates, or location. Match each generated entry
    # back to a profile role and overwrite those fields verbatim.
    prof_exp = profile.get("experience", [])
    dropped_lower = {d.lower() for d in report["skills_dropped"] if not d.startswith("cert:")}
    kept_exp = []
    for idx, e in enumerate(resume.experience):
        match = _best_experience_match(e, prof_exp)
        if match is None:
            # Can't tie this entry to a real role -> a fabricated job. Drop it in strict.
            report.setdefault("unmatched_experience", []).append(
                {"company": e.company, "role": e.role})
            if strict:
                continue
            kept_exp.append(e)
            continue

        # company / role / dates / location are FACTS -> overwrite verbatim
        # (kills inflated titles like 'Senior Software Engineer' for an 'Associate Developer').
        fixed = []
        for fld, key in (("company", "company"), ("role", "role"),
                         ("start", "start"), ("end", "end"), ("location", "location")):
            true_val = match.get(key, "")
            if true_val and getattr(e, fld).strip() != true_val:
                fixed.append(f"{fld} '{getattr(e, fld)}' -> '{true_val}'")
                setattr(e, fld, true_val)
        if fixed:
            report.setdefault("experience_fixed", []).append(
                {"company": e.company, "changes": fixed})

        # bullets must be grounded in THIS role's facts; clean fabricated metrics
        facts_tok = _facts_tokens(match)
        kept_bullets = []
        for b in e.bullets:
            low = b.lower()
            skill_hits = [d for d in dropped_lower
                          if d and re.search(rf"(?<![a-z0-9]){re.escape(d)}(?![a-z0-9])", low)]
            grounded = len(_content_tokens(b) & facts_tok) >= 1
            if skill_hits:
                report.setdefault("ungrounded_in_bullets", []).append(
                    {"company": e.company, "terms": skill_hits, "bullet": b})
            if not grounded:
                report.setdefault("ungrounded_bullets", []).append(
                    {"company": e.company, "bullet": b})
            # In strict mode, drop a bullet that names an ungrounded skill OR that
            # doesn't connect to any of this role's real facts (likely fabricated).
            if strict and (skill_hits or not grounded):
                continue
            bad = [n for n in _numbers_in(b) if n not in allowed_numbers and re.search(r"\d", n)]
            if bad:
                report["fabricated_numbers"].append(
                    {"company": e.company, "bullet": b, "numbers": sorted(bad)})
                if strict:
                    b = _strip_metrics(b)
            kept_bullets.append(b)

        # Keep the resume full + truthful: top up thin roles from their real facts.
        # Front (most-relevant) roles get more bullets, mirroring the prompt's intent.
        facts = match.get("facts", [])
        target = (5 if idx < 2 else 3) if facts else len(kept_bullets)
        if facts and len(kept_bullets) < target:
            before = len(kept_bullets)
            kept_bullets = _topup_from_facts(kept_bullets, facts, target)
            if len(kept_bullets) > before:
                report.setdefault("bullets_from_facts", []).append(e.company)
        e.bullets = kept_bullets
        kept_exp.append(e)

    _norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

    # DEDUPE: the model sometimes emits the SAME role twice (e.g. two "Materia
    # Bioworks" blocks). Collapse duplicates by company+role, merging their bullets
    # (deduped) so no content is lost and each real job appears exactly once.
    by_role: dict = {}
    order: list = []
    for e in kept_exp:
        k = (_norm(e.company), _norm(e.role))
        if k in by_role:
            tgt = by_role[k]
            seen_b = {b.strip().lower() for b in tgt.bullets}
            for b in e.bullets:
                if b.strip().lower() not in seen_b:
                    tgt.bullets.append(b)
                    seen_b.add(b.strip().lower())
            tgt.bullets = tgt.bullets[:6]
            report.setdefault("duplicate_roles_merged", []).append(e.company)
        else:
            by_role[k] = e
            order.append(k)
    kept_exp = [by_role[k] for k in order]

    # COMPLETENESS: never silently drop a REAL role. Append any profile role the
    # model left out, with bullets straight from its facts (truthful). This keeps
    # the model's prioritised order for what it chose, then adds the omitted real
    # jobs after, so your full work history always appears (e.g. Certify).
    present = {(_norm(e.company), _norm(e.role)) for e in kept_exp}
    for i, p in enumerate(prof_exp):
        if (_norm(p.get("company", "")), _norm(p.get("role", ""))) in present:
            continue
        facts = list(p.get("facts", []))
        if not facts:
            continue
        kept_exp.append(ExperienceItem(
            company=p.get("company", ""), role=p.get("role", ""),
            location=p.get("location", ""), start=p.get("start", ""),
            end=p.get("end", ""), bullets=facts[:4]))
        report.setdefault("experience_added_from_profile", []).append(p.get("company", ""))

    resume.experience = kept_exp

    # If the model fabricated experience wholesale (nothing survived grounding),
    # rebuild a truthful experience section straight from the profile's real roles.
    if strict and not kept_exp and prof_exp:
        report["experience_rebuilt_from_profile"] = True
        resume.experience = [
            ExperienceItem(
                company=p.get("company", ""), role=p.get("role", ""),
                location=p.get("location", ""), start=p.get("start", ""),
                end=p.get("end", ""), bullets=list(p.get("facts", []))[: (5 if i < 2 else 3)],
            )
            for i, p in enumerate(prof_exp)
        ]

    return resume, report


# count-nouns that read fine as "multiple <noun>" once the fake figure is removed
_COUNT_NOUNS = (r"concurrent\s+)?(projects|clients|customers|interactions|accounts|"
                r"users|websites|sites|dashboards|applications|tickets|records|teams|"
                r"developers|engineers|people|members|staff|employees|contributors|reports|papers|publications")


def _strip_metrics(bullet: str) -> str:
    """Surgically neutralise fabricated figures while keeping the sentence intact.
    The call site only invokes this for bullets with non-profile numbers, so we
    treat every metric here as fabricated and remove it cleanly."""
    b = bullet
    # "10M+ events", "500k users", "2.5B" -> drop the suffixed figure
    b = re.sub(r"\b\d+(?:[.,]\d+)?\s*[kmb]\+?\b", "", b, flags=re.I)
    # "10+ concurrent clients" / "200 accounts" -> "multiple clients"
    b = re.sub(rf"\b\d+\s*\+?\s*({_COUNT_NOUNS})\b", r"multiple \1\2", b, flags=re.I)
    # trailing "by/to/of 40%" and bare "40%"
    b = re.sub(r"\s*\b(?:by|to|of|up to|around|over)\s+\d+(?:[.,]\d+)?\s*%", "", b)
    b = re.sub(r"\s*\d+(?:[.,]\d+)?\s*%", "", b)
    # "3+ years", "6 months", "within 24 hours", "5 days"
    b = re.sub(r"\b(?:within|in|under|over)?\s*\d+\s*\+?\s*"
               r"(?:years?|yrs?|months?|weeks?|days?|hours?|hrs?|minutes?|mins?|seconds?|secs?)\b",
               "", b, flags=re.I)
    # any leftover "N+" or standalone count
    b = re.sub(r"\b\d+\s*\+", "", b)
    # tidy punctuation/whitespace
    b = re.sub(r"\s+([,.;])", r"\1", b)
    b = re.sub(r"(,\s*)+", ", ", b)
    b = re.sub(r"\s{2,}", " ", b).strip(" ,;")
    if b and not b.endswith("."):
        b += "."
    return b


# --------------------------------------------------------------------------- #
# Identity enforcement for cover letter + email (the resume guard above never
# touches these). Local models mangle the candidate's name (split it, use a
# nickname) and swap the sign-off with the signature; fix both deterministically.
# --------------------------------------------------------------------------- #
_SIGNOFFS = {
    "best", "best regards", "regards", "kind regards", "warm regards",
    "sincerely", "cheers", "thanks", "thank you", "many thanks", "all the best",
}


def _is_signoff(s: str) -> bool:
    return (s or "").strip().rstrip(",.").lower() in _SIGNOFFS


def _fix_name_in_text(text: str, profile: dict) -> str:
    """Replace mangled forms of the candidate's name with the canonical one.
    Handles nickname use and space-split names (e.g. 'Keerthi Vasan')."""
    full = profile.get("full_name", "")
    if not text or not full:
        return text
    pref = profile.get("preferred_name", "") or ""
    t = text
    # Space-split version of the full name: 'Keerthivasan' -> 'Keerthi vasan'.
    if pref and full.lower().startswith(pref.lower()) and len(full) > len(pref):
        rest = re.escape(full[len(pref):])
        t = re.sub(rf"\b{re.escape(pref)}\s+{rest}\b", full, t, flags=re.I)
    # Bare nickname -> full name (only when it isn't already the full name).
    if pref and pref.lower() != full.lower():
        t = re.sub(rf"\b{re.escape(pref)}\b(?!{re.escape(full[len(pref):])})", full, t, flags=re.I)
    return t


def _profile_contact_line(profile: dict, target_location: str = "") -> str:
    """The canonical one-line contact string, built from the profile only."""
    c = profile.get("contact", {})
    parts = [profile.get("full_name", ""), _display_location(profile, target_location),
             c.get("email", ""), c.get("phone", "")]
    parts += [l.get("url", "") for l in c.get("links", [])]
    return " | ".join(p for p in parts if p)


def _clean_letter_prose(text: str, profile: dict, allowed: set[str]) -> tuple[str, bool]:
    """Fix the candidate's name and strip invented years/metrics from a paragraph.
    Returns (cleaned_text, changed)."""
    t = _fix_name_in_text(text, profile)
    t = _strip_experience_claims(t)
    changed = t != text
    if {n for n in _numbers_in(t) if re.search(r"\d", n)} - allowed:
        stripped = _strip_metrics(t)
        if stripped != t:
            t, changed = stripped, True
    return t, changed


def enforce_cover_letter(cl: CoverLetter, profile: dict,
                         target_location: str = "") -> tuple[CoverLetter, dict]:
    report: dict = {"name_fixed": False, "signoff_fixed": False,
                    "contact_fixed": False, "claims_stripped": 0}
    name = profile.get("full_name", cl.fullName)

    if cl.fullName.strip() != name:
        report["name_fixed"] = True
    cl.fullName = name

    # Contact line: ALWAYS rebuilt from the profile — the model invents whole
    # identities (wrong name/email/phone), which _fix_name_in_text can't catch.
    true_contact = _profile_contact_line(profile, target_location)
    if true_contact and cl.contactLine.strip() != true_contact:
        report["contact_fixed"] = True
    cl.contactLine = true_contact or cl.contactLine

    cl.greeting = _fix_name_in_text(cl.greeting, profile)

    # Body: strip invented "N years", team sizes, event counts, percentages.
    allowed = _numbers_in(_profile_number_text(profile))
    new_body = []
    for p in cl.body:
        cleaned, changed = _clean_letter_prose(p, profile, allowed)
        if changed:
            report["claims_stripped"] += 1
        new_body.append(cleaned)
    cl.body = new_body

    # The model often swaps these two. The signature must be the name; the
    # sign-off must be a closing phrase.
    if _is_signoff(cl.signature) and not _is_signoff(cl.signOff):
        cl.signOff, cl.signature = cl.signature, cl.signOff
        report["signoff_fixed"] = True
    if not _is_signoff(cl.signOff):
        cl.signOff = "Best,"
        report["signoff_fixed"] = True
    if cl.signature.strip() != name:
        report["name_fixed"] = True
    cl.signature = name

    return cl, report


# A signature/contact line (email, URL, bare domain, or phone-like) — deterministic,
# truth-only data, so the prose cleaner must leave it alone (it would otherwise add a
# trailing period, strip digits as a fake "metric", or mangle a URL/handle).
_CONTACT_LINE = re.compile(
    r"@|https?://|www\.|\b[\w-]+\.(?:com|ca|io|dev|ai|org|net|co|app)\b|^\+?[\d()][\d().\s/|-]{6,}$",
    re.I,
)
# The deterministic envelope (greeting + closing) — pass through so its trailing
# comma survives the prose cleaner's strip.
_ENVELOPE_LINE = re.compile(r"^(hi|hello|dear|thanks|thank you|best|regards|cheers|sincerely)\b", re.I)


def enforce_email(email: ApplicationEmail, profile: dict) -> tuple[ApplicationEmail, dict]:
    report: dict = {"name_fixed": False, "claims_stripped": 0}
    allowed = _numbers_in(_profile_number_text(profile))
    email.subject = _fix_name_in_text(email.subject, profile)
    # Clean line-by-line so the email's paragraph + signature/letterhead newlines
    # survive (the prose cleaners squeeze runs of whitespace, which would collapse
    # every blank-line break and flatten the whole email). Pass the deterministic
    # greeting / sign-off / contact lines through untouched; only real prose (the
    # model-written hook) gets the truth-guard treatment.
    changed_any = False
    out_lines: list[str] = []
    for ln in (email.body or "").replace("\r\n", "\n").split("\n"):
        s = ln.strip()
        if not s:
            out_lines.append("")
            continue
        if _is_signoff(s) or _ENVELOPE_LINE.match(s) or _CONTACT_LINE.search(s):
            out_lines.append(ln)
            continue
        cleaned, changed = _clean_letter_prose(ln, profile, allowed)
        out_lines.append(cleaned)
        changed_any = changed_any or changed
    email.body = "\n".join(out_lines)
    if changed_any:
        report["claims_stripped"] = 1
    return email, report


def has_violations(report: dict) -> bool:
    if any(report.get(k) for k in (
        "skills_dropped", "fabricated_numbers", "identity_fixed",
        "experience_fixed", "unmatched_experience", "ungrounded_in_bullets",
        "ungrounded_bullets", "headline_fixed", "summary_fixed", "bullets_from_facts",
        "experience_rebuilt_from_profile",
    )):
        return True
    for sub in ("cover_letter", "email"):
        s = report.get(sub) or {}
        if s.get("contact_fixed") or s.get("claims_stripped") or s.get("name_fixed"):
            return True
    return False
