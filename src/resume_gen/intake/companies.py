"""Per-company memory + repeat-company list + the autofill apply-profile.

When the same company posts again, we reuse the details saved here (so you fill
them once). The apply-profile holds your standard answers for autofill.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import ROOT

_DATA = ROOT / "data"
_COMPANIES = _DATA / "companies"
_REPEAT = _DATA / "repeat_companies.json"
_APPLY_PROFILE = _DATA / "apply_profile.json"


def slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-") or "unknown"


# --------------------------------------------------------------------------- #
# apply-profile (autofill answers)
# --------------------------------------------------------------------------- #
def load_apply_profile() -> dict:
    if _APPLY_PROFILE.exists():
        try:
            return json.loads(_APPLY_PROFILE.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


# --------------------------------------------------------------------------- #
# repeat companies
# --------------------------------------------------------------------------- #
def load_repeat_companies() -> list[str]:
    if _REPEAT.exists():
        try:
            return json.loads(_REPEAT.read_text(encoding="utf-8")).get("companies", [])
        except ValueError:
            return []
    return []


def is_repeat(company: str) -> bool:
    """True if the company matches the repeat list (case-insensitive, word-ish)."""
    c = (company or "").lower().strip()
    if not c:
        return False
    for name in load_repeat_companies():
        n = name.lower().strip()
        if n and (n == c or re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", c)):
            return True
    return False


# --------------------------------------------------------------------------- #
# per-company saved details
# --------------------------------------------------------------------------- #
def get_company(company: str) -> dict | None:
    f = _COMPANIES / f"{slug(company)}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return None


def save_company(company: str, data: dict) -> dict:
    """Merge `data` into the saved record for this company (create if new)."""
    _COMPANIES.mkdir(parents=True, exist_ok=True)
    existing = get_company(company) or {"company": company}
    existing.update({k: v for k, v in (data or {}).items() if v not in (None, "")})
    existing["company"] = company
    (_COMPANIES / f"{slug(company)}.json").write_text(
        json.dumps(existing, indent=2), encoding="utf-8"
    )
    return existing


def list_companies() -> list[dict]:
    if not _COMPANIES.exists():
        return []
    out = []
    for f in _COMPANIES.glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return out
