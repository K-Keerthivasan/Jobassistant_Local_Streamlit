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
    stamp `updated_at` (the date the HR/company details were last changed).

    Supports multiple HR contacts via `hr_contacts: [{name, email}]`; the first
    contact is mirrored into the legacy `hr_email`/`hr_name` (the "primary"), so
    auto-fill and `hr_email_for` keep working unchanged."""
    from . import db

    existing = get_company(company) or {"company": company}
    existing.update({k: v for k, v in (data or {}).items() if v not in (None, "")})
    # Keep the primary fields in sync with the contact list.
    contacts = existing.get("hr_contacts") or []
    if contacts:
        primary = contacts[0]
        existing["hr_email"] = (primary.get("email") or existing.get("hr_email") or "").strip()
        existing["hr_name"] = (primary.get("name") or existing.get("hr_name") or "").strip()
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
    """Primary saved HR email for a company (auto-fills jobs with no contact email)."""
    rec = find_company(company) or {}
    return (rec.get("hr_email") or rec.get("contact_email") or "").strip()


def hr_emails_for(company: str) -> list[str]:
    """All saved HR emails for a company, primary first, deduped."""
    rec = find_company(company) or {}
    out: list[str] = []
    for c in (rec.get("hr_contacts") or []):
        e = (c.get("email") or "").strip()
        if e and e not in out:
            out.append(e)
    primary = (rec.get("hr_email") or rec.get("contact_email") or "").strip()
    if primary and primary not in out:
        out.insert(0, primary)
    return out


def record_hr_followup(company: str) -> dict:
    """Append today's date to the company's HR follow-up history."""
    rec = find_company(company) or {"company": company}
    hist = list(rec.get("hr_followups") or [])
    hist.append(datetime.now().date().isoformat())
    return save_company(rec.get("company", company), {"hr_followups": hist})
