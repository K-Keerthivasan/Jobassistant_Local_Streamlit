"""Repeatable role templates: companies/roles you apply to again and again
(TD Bank · Software Developer, RBC · Data Analyst, ...).

Each template stores the latest job description plus a running count and the
folder of the last generated application, so re-applying is one click: regenerate
a freshly tuned resume/cover/email from the saved JD, download, tweak, re-submit.

Persisted in SQLite (table ``repeatable_roles``, see db.py), keyed by
slug(company + title) so each distinct role is its own template.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from pydantic import BaseModel, Field

from . import db


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def role_key(company: str, title: str) -> str:
    """Stable key for one recurring role = company + title."""
    return _slug(f"{company} {title}") or "untitled"


def _norm_tags(value) -> list[str]:
    """Accept a list or a comma/semicolon string; return clean, de-duped tags."""
    if isinstance(value, str):
        parts = re.split(r"[,;]", value)
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        return []
    out: list[str] = []
    for p in parts:
        t = str(p).strip()
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out


class RepeatableRole(BaseModel):
    """One recurring role you reapply to over time."""

    key: str = ""
    company: str = ""
    title: str = ""
    location: str = ""
    job_id: str = ""            # source posting id — avoid reapplying to the same one
    sector: str = ""            # Banking | Telecom | Retail | Insurance | Logistics | Tech | ...
    tags: list[str] = Field(default_factory=list)  # free-form filters (remote, urgent, referral…)
    status: str = "tracked"     # tracked | applied | interview | offer | closed
    description: str = ""        # latest JD — what regeneration runs against
    apply_url: str = ""
    contact_email: str = ""
    persona: str = ""           # persona id to use when regenerating ("" = auto)
    priority: bool = False      # generate with Hermes in Auto mode
    times_applied: int = 0
    last_applied: str = ""      # ISO date of the most recent regenerate
    last_folder: str = ""       # output folder of the most recent generation
    last_folder_name: str = ""
    notes: str = ""
    source: str = ""            # where it first came from (manual/collector/email/...)
    created_at: str = ""
    updated_at: str = ""


def get_role(key: str) -> RepeatableRole | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM repeatable_roles WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return None
    try:
        return RepeatableRole.model_validate_json(row["data"])
    except ValueError:
        return None


def _write(role: RepeatableRole) -> RepeatableRole:
    role.updated_at = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        db._upsert_role_row(conn, json.loads(role.model_dump_json()))
    return role


def list_roles() -> list[RepeatableRole]:
    with db.connect() as conn:
        cur = conn.execute(
            """SELECT data FROM repeatable_roles
               ORDER BY COALESCE(last_applied,'') DESC, COALESCE(updated_at,'') DESC"""
        )
        rows = cur.fetchall()
    out: list[RepeatableRole] = []
    for r in rows:
        try:
            out.append(RepeatableRole.model_validate_json(r["data"]))
        except ValueError:
            continue
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
        if k not in RepeatableRole.model_fields or v in (None, ""):
            continue
        if k == "tags":
            v = _norm_tags(v)
        setattr(role, k, v)
    # Auto-fill the sector from the known repeat-company list when not given.
    if not role.sector:
        from .companies import sector_for
        role.sector = sector_for(role.company)
    return _write(role)


def update_fields(key: str, fields: dict) -> RepeatableRole | None:
    role = get_role(key)
    if role is None:
        return None
    _EDITABLE = {"company", "title", "location", "job_id", "sector", "tags",
                 "status", "description", "apply_url", "contact_email",
                 "persona", "priority", "notes"}
    for k, v in (fields or {}).items():
        if k in _EDITABLE:
            setattr(role, k, _norm_tags(v) if k == "tags" else v)
    return _write(role)


def mark_applied(key: str, folder: str = "", folder_name: str = "") -> RepeatableRole | None:
    """Record one more application: bump the count, stamp the date + last folder."""
    role = get_role(key)
    if role is None:
        return None
    role.times_applied += 1
    role.last_applied = datetime.now().date().isoformat()
    # Advance an untouched/tracked role to "applied"; keep later statuses
    # (interview/offer/closed) the user set manually.
    if role.status in ("", "tracked"):
        role.status = "applied"
    if folder:
        role.last_folder = folder
    if folder_name:
        role.last_folder_name = folder_name
    return _write(role)


def delete_role(key: str) -> bool:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM repeatable_roles WHERE key = ?", (key,))
        return cur.rowcount > 0


def match_role(company: str, title: str) -> RepeatableRole | None:
    """Find an existing template for this exact (company, title)."""
    return get_role(role_key(company, title))


def is_repeatable(company: str, title: str) -> bool:
    return match_role(company, title) is not None
