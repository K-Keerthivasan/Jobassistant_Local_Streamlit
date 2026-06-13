"""Repeatable role templates: companies/roles you apply to again and again
(TD Bank · Software Developer, RBC · Data Analyst, ...).

Each template stores the latest job description plus a running count and the
folder of the last generated application, so re-applying is one click: regenerate
a freshly tuned resume/cover/email from the saved JD, download, tweak, re-submit.

Stored one JSON per role under data/repeatable/<slug>.json. Keyed by
slug(company + title) so each distinct role is its own template.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from pydantic import BaseModel, Field

from ..config import ROOT

_DIR = ROOT / "data" / "repeatable"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def role_key(company: str, title: str) -> str:
    """Stable key for one recurring role = company + title."""
    return _slug(f"{company} {title}") or "untitled"


class RepeatableRole(BaseModel):
    """One recurring role you reapply to over time."""

    key: str = ""
    company: str = ""
    title: str = ""
    location: str = ""
    description: str = ""        # latest JD — what regeneration runs against
    apply_url: str = ""
    contact_email: str = ""
    persona: str = ""           # persona id to use when regenerating ("" = auto)
    priority: bool = False      # generate with Claude in Auto mode
    times_applied: int = 0
    last_applied: str = ""      # ISO date of the most recent regenerate
    last_folder: str = ""       # output folder of the most recent generation
    last_folder_name: str = ""
    notes: str = ""
    source: str = ""            # where it first came from (manual/collector/email/...)
    created_at: str = ""
    updated_at: str = ""


def _path(key: str):
    return _DIR / f"{key}.json"


def get_role(key: str) -> RepeatableRole | None:
    f = _path(key)
    if not f.exists():
        return None
    try:
        return RepeatableRole.model_validate_json(f.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _write(role: RepeatableRole) -> RepeatableRole:
    _DIR.mkdir(parents=True, exist_ok=True)
    role.updated_at = datetime.now().isoformat(timespec="seconds")
    _path(role.key).write_text(role.model_dump_json(indent=2), encoding="utf-8")
    return role


def list_roles() -> list[RepeatableRole]:
    if not _DIR.exists():
        return []
    out: list[RepeatableRole] = []
    for f in _DIR.glob("*.json"):
        try:
            out.append(RepeatableRole.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    # Most recently applied first, then most recently touched.
    out.sort(key=lambda r: (r.last_applied or "", r.updated_at or ""), reverse=True)
    return out


def upsert_role(company: str, title: str, **fields) -> RepeatableRole:
    """Create or update the template for (company, title). Non-empty fields win;
    counters/dates are preserved."""
    key = role_key(company, title)
    role = get_role(key) or RepeatableRole(
        key=key, company=company, title=title,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    role.company = company or role.company
    role.title = title or role.title
    for k, v in fields.items():
        if k in RepeatableRole.model_fields and v not in (None, ""):
            setattr(role, k, v)
    return _write(role)


def update_fields(key: str, fields: dict) -> RepeatableRole | None:
    role = get_role(key)
    if role is None:
        return None
    _EDITABLE = {"company", "title", "location", "description", "apply_url",
                 "contact_email", "persona", "priority", "notes"}
    for k, v in (fields or {}).items():
        if k in _EDITABLE:
            setattr(role, k, v)
    return _write(role)


def mark_applied(key: str, folder: str = "", folder_name: str = "") -> RepeatableRole | None:
    """Record one more application: bump the count, stamp the date + last folder."""
    role = get_role(key)
    if role is None:
        return None
    role.times_applied += 1
    role.last_applied = datetime.now().date().isoformat()
    if folder:
        role.last_folder = folder
    if folder_name:
        role.last_folder_name = folder_name
    return _write(role)


def delete_role(key: str) -> bool:
    f = _path(key)
    if f.exists():
        f.unlink()
        return True
    return False


def match_role(company: str, title: str) -> RepeatableRole | None:
    """Find an existing template for this exact (company, title)."""
    return get_role(role_key(company, title))


def is_repeatable(company: str, title: str) -> bool:
    return match_role(company, title) is not None
