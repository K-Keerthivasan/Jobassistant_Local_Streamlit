"""Load the master profile (the truth-only CANDIDATE_PROFILE) and serialize it
into the compact text block the LLM receives."""

from __future__ import annotations

from pathlib import Path

import yaml

from .config import settings


def load_profile(path: Path | None = None) -> dict:
    path = path or settings.profile_path
    if not path.exists():
        raise FileNotFoundError(
            f"Master profile not found at {path}. Copy/edit data/profile/master_profile.yaml."
        )
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def profile_to_prompt_block(profile: dict) -> str:
    """Render the structured profile into a deterministic text block for the LLM.

    We keep YAML-ish formatting: it is compact, unambiguous, and the model has no
    trouble reading it. Crucially, this contains ONLY facts from the profile."""

    lines: list[str] = []
    add = lines.append

    add(f"FULL NAME: {profile.get('full_name', '')}")
    if profile.get("preferred_name"):
        add(f"PREFERRED NAME: {profile['preferred_name']}")

    c = profile.get("contact", {})
    add("\nCONTACT:")
    add(f"  email: {c.get('email', '')}")
    add(f"  phone: {c.get('phone', '')}")
    add(f"  location: {c.get('location', '')}")
    for link in c.get("links", []):
        add(f"  link: {link.get('label', '')} -> {link.get('url', '')}")

    if profile.get("summary_base"):
        add("\nBACKGROUND (factual, for reference — rewrite, do not copy verbatim):")
        add(f"  {profile['summary_base'].strip()}")

    add("\nSKILLS (use only these; select + order by relevance):")
    for group, items in (profile.get("skills") or {}).items():
        add(f"  {group}: {', '.join(items)}")

    add("\nEXPERIENCE (most recent first; draw bullets only from these facts):")
    for e in profile.get("experience", []):
        add(f"  - {e.get('role', '')} | {e.get('company', '')}"
            f" | {e.get('location', '')} | {e.get('start', '')} to {e.get('end', '')}")
        if e.get("tags"):
            add(f"    relevance_tags: {', '.join(e['tags'])}")
        if e.get("preserve"):
            add("    PRESERVE: keep this role's function as-is (do NOT recast it as a "
                "different field); write bullets close to these facts with minimal rephrasing.")
        for fact in e.get("facts", []):
            add(f"    fact: {fact}")

    if profile.get("projects"):
        add("\nPROJECTS (optional, include only if relevant to the role):")
        for p in profile["projects"]:
            stack = ", ".join(p.get("stack", []))
            url = f" ({p['url']})" if p.get("url") else ""
            add(f"  - {p.get('name', '')} [{stack}]{url}: {p.get('description', '')}")
            if p.get("tags"):
                add(f"    relevance_tags: {', '.join(p['tags'])}")

    add("\nEDUCATION:")
    for ed in profile.get("education", []):
        add(f"  - {ed.get('credential', '')} | {ed.get('institution', '')} | {ed.get('year', '')}")

    certs = profile.get("certifications") or []
    add("\nCERTIFICATIONS: " + (", ".join(certs) if certs else "none"))

    return "\n".join(lines)
