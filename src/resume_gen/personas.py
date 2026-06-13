"""Role personas: pick a role-specific framing of the master profile and turn it
into a directive the LLM applies on top of the TRUTH-ONLY profile.

A persona never adds facts — it only reframes (headline, summary seed, which
experience to lead with, which skills to foreground, which links to show). The
truth-guard still validates everything against master_profile.yaml.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .config import ROOT, settings

_PERSONAS_PATH = (settings.profile_path.parent / "personas.yaml")
_WORD_RE = re.compile(r"[a-z0-9.+#-]+")


@lru_cache(maxsize=1)
def load_personas() -> list[dict]:
    """Load persona definitions; empty list if the file is absent."""
    path = _PERSONAS_PATH if _PERSONAS_PATH.exists() else (ROOT / "data" / "profile" / "personas.yaml")
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("personas", []) or []


def list_personas() -> list[dict]:
    """Compact list for the UI picker: [{id, label, headline}]."""
    return [
        {"id": p.get("id", ""), "label": p.get("label", p.get("id", "")),
         "headline": p.get("headline", "")}
        for p in load_personas()
    ]


def get_persona(persona_id: str | None) -> dict | None:
    if not persona_id:
        return None
    for p in load_personas():
        if p.get("id") == persona_id:
            return p
    return None


def _score(persona: dict, title: str, blob: str, title_words: set[str]) -> int:
    """Keyword overlap score. Hits in the job title count more than in the body."""
    score = 0
    for kw in persona.get("keywords", []):
        k = kw.lower().strip()
        if not k:
            continue
        if " " in k:  # phrase -> substring match
            if k in title:
                score += 3
            elif k in blob:
                score += 2
        else:          # single token -> whole-word match in title, substring in body
            if k in title_words:
                score += 3
            elif k in blob:
                score += 1
    return score


def auto_select(target) -> dict | None:
    """Best-matching persona for a target role, or None if nothing matches."""
    personas = load_personas()
    if not personas:
        return None
    title = (getattr(target, "title", "") or "").lower()
    desc = (getattr(target, "description", "") or "").lower()
    title_words = set(_WORD_RE.findall(title))
    blob = f" {title} \n {desc} "
    best, best_score = None, 0
    for p in personas:
        s = _score(p, title, blob, title_words)
        if s > best_score:
            best, best_score = p, s
    return best


def select_persona(target, override_id: str | None = None) -> dict | None:
    """Manual override wins; otherwise auto-detect from the job. 'auto'/'' = auto."""
    if override_id and override_id != "auto":
        forced = get_persona(override_id)
        if forced is not None:
            return forced
    return auto_select(target)


def persona_directive(persona: dict | None) -> str:
    """Render the persona as a framing block appended to the user message."""
    if not persona:
        return ""
    lines = [
        "\nPERSONA FRAMING (apply this lens; stay strictly within CANDIDATE_PROFILE facts —",
        "do NOT add anything not present there):",
        f"  target_persona: {persona.get('label', persona.get('id', ''))}",
    ]
    if persona.get("headline"):
        lines.append(f"  headline: use \"{persona['headline']}\" (or a close, truthful variant)")
    if persona.get("summary_seed"):
        seed = " ".join(persona["summary_seed"].split())
        lines.append(f"  summary_framing (rewrite in the candidate's voice, do not copy verbatim): {seed}")
    if persona.get("lead_with"):
        lines.append(f"  lead_with_experience: {persona['lead_with']}")
    if persona.get("foreground_skills"):
        lines.append(f"  foreground_skills: {persona['foreground_skills']} "
                     "(order the Skills section to lead with these; include 8-14 total)")
    return "\n".join(lines) + "\n"
