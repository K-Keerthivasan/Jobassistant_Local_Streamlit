"""Per-company memory + repeat-company list + the autofill apply-profile.

When the same company posts again, we reuse the details saved here (so you fill
them once). The apply-profile holds your standard answers for autofill.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
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
def _load_repeat() -> dict:
    if _REPEAT.exists():
        try:
            return json.loads(_REPEAT.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def load_repeat_companies() -> list[str]:
    return _load_repeat().get("companies", [])


def load_sectors() -> dict[str, list[str]]:
    """Map of sector name -> list of companies in it (from repeat_companies.json)."""
    sectors = _load_repeat().get("sectors", {})
    return sectors if isinstance(sectors, dict) else {}


def sector_for(company: str) -> str:
    """Best-effort sector for a company name (case-insensitive, word-ish match)."""
    c = (company or "").lower().strip()
    if not c:
        return ""
    for sector, members in load_sectors().items():
        for name in members or []:
            n = name.lower().strip()
            if n and (n == c or re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", c)):
                return sector
    return ""


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
# per-company saved details (SQLite-backed; see db.py)
#
# The old `data/companies/*.json` files are migrated into the `companies` table
# once, on first start. `_COMPANIES` is kept only so that migration can find them.
# --------------------------------------------------------------------------- #
def get_company(company: str) -> dict | None:
    from . import db

    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM companies WHERE slug = ?", (slug(company),)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def save_company(company: str, data: dict) -> dict:
    """Merge `data` into the saved record for this company (create if new) and
    stamp `updated_at` (the date the HR/company details were last changed)."""
    from . import db

    existing = get_company(company) or {"company": company}
    existing.update({k: v for k, v in (data or {}).items() if v not in (None, "")})
    existing["company"] = company
    existing["updated_at"] = datetime.now().date().isoformat()
    with db.connect() as conn:
        db._upsert_company_row(conn, slug(company), existing)
    return existing


def list_companies() -> list[dict]:
    from . import db

    out = []
    with db.connect() as conn:
        for r in conn.execute("SELECT data FROM companies ORDER BY company"):
            try:
                out.append(json.loads(r["data"]))
            except ValueError:
                continue
    return out


def find_company(company: str) -> dict | None:
    """Saved record for a company: exact slug first, else a case-insensitive
    word-ish match (so a job's 'TD' finds a saved 'TD', and vice-versa)."""
    rec = get_company(company)
    if rec:
        return rec
    c = (company or "").lower().strip()
    if not c:
        return None
    for rec in list_companies():
        n = (rec.get("company") or "").lower().strip()
        if n and (n == c or re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", c)):
            return rec
    return None


def hr_email_for(company: str) -> str:
    """Saved HR email for a company (used to auto-fill jobs with no contact email)."""
    rec = find_company(company) or {}
    return (rec.get("hr_email") or rec.get("contact_email") or "").strip()
