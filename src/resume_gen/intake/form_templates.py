"""Remembered application forms (SQLite, table ``form_templates``).

Reading a career page's accessibility tree is the single most expensive step in
applying — tens of thousands of tokens for one posting. Employers reuse the same
form across every job they publish, so reading it again per posting is pure waste.

This store keeps the field schema for each site: selectors, labels, types,
options, and the site's own custom screening questions. A repeat application
looks the template up by host, fills straight from it, and only needs a small
verification instead of a full page read. Paired with the answers bank, the
second application to an employer needs neither a page read nor a drafted answer.

Staleness is handled honestly rather than optimistically. A template carries a
``signature`` fingerprinting its field set; the caller verifies the cached
selectors actually exist before trusting them, and re-reads the page when they
don't. A cache that silently fills the wrong boxes would be worse than no cache.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from . import db

# Fields whose presence varies per posting (a job-specific question, a honeypot,
# a tracking input) shouldn't change a form's identity.
_IGNORE_IN_SIGNATURE = ("csrf", "token", "captcha", "honeypot", "utm", "timestamp")


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).netloc or "").lower().lstrip("www.")
    except ValueError:
        return ""


def _field_key(field: dict) -> str:
    """What identifies a field across postings: its label, else its name."""
    raw = (field.get("label") or field.get("name") or field.get("id") or "").strip().lower()
    raw = re.sub(r"[^a-z0-9\s]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def signature_of(fields: list[dict]) -> str:
    """Stable fingerprint of a form's field set, order-independent."""
    keys = sorted(
        k for k in (_field_key(f) for f in fields or [])
        if k and not any(bad in k for bad in _IGNORE_IN_SIGNATURE)
    )
    return hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:16]


def _template_id(host: str, signature: str) -> str:
    return hashlib.sha1(f"{host}:{signature}".encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def _row(r) -> dict | None:
    try:
        return json.loads(r["data"])
    except ValueError:
        return None


def get_for_url(url: str) -> dict | None:
    """The best remembered form for this URL's host: the most-used one.

    Lookup is by host because that's all a URL tells us before the page is read.
    The caller must verify the returned selectors exist on the page — several
    forms can share a host, and sites do get redesigned.
    """
    host = host_of(url)
    if not host:
        return None
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT data FROM form_templates WHERE host = ?
               ORDER BY times_used DESC, last_seen DESC LIMIT 1""",
            (host,),
        ).fetchall()
    return _row(rows[0]) if rows else None


def list_templates(host: str = "") -> list[dict]:
    sql = "SELECT data FROM form_templates"
    params: list = []
    if host:
        sql += " WHERE host = ?"
        params.append(host.lower())
    sql += " ORDER BY times_used DESC, last_seen DESC"
    out = []
    with db.connect() as conn:
        for r in conn.execute(sql, params):
            t = _row(r)
            if t:
                out.append(t)
    return out


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def remember(url: str, fields: list[dict], *, ats: str = "", company: str = "") -> dict | None:
    """Record (or refresh) the form found at `url`. Returns the stored template.

    Called after a page has actually been read, so the next application to this
    employer doesn't have to read it again. A form whose signature has changed is
    stored as a **new** template rather than overwriting the old one — the site may
    serve different forms for different roles, and the most-used one wins lookups.
    """
    host = host_of(url)
    if not host or not fields:
        return None

    sig = signature_of(fields)
    tid = _template_id(host, sig)
    now = datetime.now().isoformat(timespec="seconds")

    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM form_templates WHERE id = ?", (tid,)
        ).fetchone()
    existing = _row(row) if row else None

    template = existing or {
        "id": tid,
        "host": host,
        "signature": sig,
        "first_seen": now,
        "times_used": 0,
        "companies": [],
    }
    template["ats"] = ats or template.get("ats", "")
    # Store the schema only — never a filled value. This is a map of the form,
    # not a copy of an application.
    template["fields"] = [
        {
            "selector": f.get("selector", ""),
            "name": f.get("name", ""),
            "id": f.get("id", ""),
            "label": f.get("label", ""),
            "type": f.get("type", ""),
            "required": bool(f.get("required")),
            "options": [str(o) for o in (f.get("options") or [])],
            "kind": f.get("kind", ""),
        }
        for f in fields
    ]
    template["field_count"] = len(template["fields"])
    template["questions"] = [
        f["label"] for f in template["fields"]
        if f["label"] and (f["kind"] == "screening" or f["label"].rstrip().endswith("?"))
    ]
    template["times_used"] = int(template.get("times_used") or 0) + 1
    template["last_seen"] = now
    if company and company not in (template.get("companies") or []):
        template.setdefault("companies", []).append(company)
    template["example_url"] = url

    with db.connect() as conn:
        db._upsert_form_template_row(conn, template)
    return template


def delete_template(template_id: str) -> bool:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM form_templates WHERE id = ?", (template_id,))
        return cur.rowcount > 0


def forget_host(host: str) -> int:
    """Drop every remembered form for a host (use when a site is redesigned)."""
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM form_templates WHERE host = ?", (host or "").lower())
        return cur.rowcount
