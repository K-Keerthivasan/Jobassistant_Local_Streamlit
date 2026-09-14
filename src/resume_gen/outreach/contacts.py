"""HR contacts for outreach (table ``outreach_contacts``), sourced from File 2.

    confidence: verified | enriched | pattern_guess

Merge rules (brief 6.6): a new row never clobbers a verified address with a
guessed one; confidence only moves up, never down, without an explicit override.
A hand-entered or corrected address is `verified` and records who set it.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from ..intake import db

CONFIDENCE_RANK = {"pattern_guess": 0, "enriched": 1, "verified": 2}
_PATTERN_LOCAL = {"careers", "hr", "jobs", "recruiting", "recruitment", "talent", "hiring",
                  "info", "contact", "people", "humanresources", "apply", "resumes", "resume"}
_LEGAL = re.compile(r"\b(inc|incorporated|llc|llp|ltd|limited|corp|corporation|co|company|plc|gmbh|ulc|pvt|sa|srl)\b\.?", re.I)


def norm_company(name: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    t = _LEGAL.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def contact_id(company: str, email: str) -> str:
    raw = f"{norm_company(company)}|{(email or '').strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def infer_confidence(email: str, notes: str = "") -> str:
    """From File 2's notes column first, then the address shape."""
    n = (notes or "").lower()
    if re.search(r"\bverified\b|confirmed email|vibe.*verified", n):
        return "verified"
    if re.search(r"pattern|guess|assumed|inferred|generic (?:inbox|address)", n):
        return "pattern_guess"
    if re.search(r"enrich|vibe|apollo|hunter|linkedin recruiter|recruiter name", n):
        return "enriched"
    local = (email or "").split("@")[0].strip().lower().replace(".", "").replace("-", "").replace("_", "")
    if local in _PATTERN_LOCAL or not email:
        return "pattern_guess"
    return "enriched"


def infer_designated_status(notes: str) -> str:
    n = (notes or "").lower()
    if "designated" not in n and "aip" not in n and "rcip" not in n:
        return ""
    if re.search(r"designated[^.;|]*(confirmed|verified|listed|yes)", n) or re.search(r"(confirmed|verified) designated", n):
        return "confirmed"
    if "unconfirmed" in n or "not confirmed" in n or "tbd" in n:
        return "unconfirmed"
    return "mentioned"


def _row_to_contact(row) -> dict | None:
    try:
        return json.loads(row["data"])
    except (ValueError, TypeError):
        return None


def get_contact(cid: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT data FROM outreach_contacts WHERE id = ?", (cid,)).fetchone()
    return _row_to_contact(row) if row else None


def list_contacts(company: str | None = None) -> list[dict]:
    with db.connect() as conn:
        if company:
            cur = conn.execute("SELECT data FROM outreach_contacts WHERE company_norm = ? ORDER BY confidence DESC",
                               (norm_company(company),))
        else:
            cur = conn.execute("SELECT data FROM outreach_contacts ORDER BY company, hr_email")
        return [c for c in (_row_to_contact(r) for r in cur.fetchall()) if c]


def contacts_for_company(company: str) -> list[dict]:
    return list_contacts(company)


def _write(conn, c: dict) -> None:
    conn.execute(
        """INSERT INTO outreach_contacts (id, company, company_norm, hr_email, confidence,
                                          do_not_contact, updated_at, data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             company=excluded.company, company_norm=excluded.company_norm,
             hr_email=excluded.hr_email, confidence=excluded.confidence,
             do_not_contact=excluded.do_not_contact, updated_at=excluded.updated_at,
             data=excluded.data""",
        (c["id"], c.get("company", ""), norm_company(c.get("company", "")),
         (c.get("hr_email") or "").strip().lower(), c.get("confidence", "pattern_guess"),
         1 if c.get("do_not_contact") else 0, c.get("updated_at", ""),
         json.dumps(c, ensure_ascii=False)))


def upsert_contact(*, company: str, hr_email: str = "", hr_name: str = "", hr_phone: str = "",
                   ats: str = "", careers_url: str = "", notes: str = "", source: str = "import",
                   confidence: str | None = None, verified_on: str = "",
                   designated_employer_status: str = "", set_by: str = "",
                   override: bool = False) -> tuple[dict, str]:
    """Merge one File 2 row (or a manual edit) into the contact table.

    Returns (contact, outcome) where outcome is new | upgraded | unchanged | kept_existing.
    Without ``override`` the stored confidence never moves down and a verified
    address's name/notes are not replaced by a guess."""
    email = (hr_email or "").strip().lower()
    conf = confidence or infer_confidence(email, notes)
    if conf not in CONFIDENCE_RANK:
        conf = "pattern_guess"
    cid = contact_id(company, email)
    now = datetime.now().isoformat(timespec="seconds")
    existing = get_contact(cid)
    incoming = {
        "id": cid, "company": company, "hr_name": (hr_name or "").strip(), "hr_email": email,
        "hr_phone": (hr_phone or "").strip(), "ats": (ats or "").strip().lower(),
        "careers_url": (careers_url or "").strip(), "source": source, "confidence": conf,
        "verified_on": verified_on or (now[:10] if conf == "verified" else ""),
        "designated_employer_status": designated_employer_status or infer_designated_status(notes),
        "do_not_contact": False, "notes": (notes or "").strip(), "set_by": set_by,
        "created_at": now, "updated_at": now, "history": [],
    }
    if existing is None:
        with db.connect() as conn:
            _write(conn, incoming)
        return incoming, "new"

    merged = dict(existing)
    outcome = "unchanged"
    old_rank, new_rank = CONFIDENCE_RANK.get(existing.get("confidence", "pattern_guess"), 0), CONFIDENCE_RANK[conf]
    if new_rank > old_rank or override:
        merged["confidence"] = conf
        merged["verified_on"] = incoming["verified_on"] or existing.get("verified_on", "")
        merged["set_by"] = set_by or existing.get("set_by", "")
        outcome = "upgraded" if new_rank > old_rank else "overridden"
    elif new_rank < old_rank:
        outcome = "kept_existing"
    # Fill blanks only; never blank out a value.
    for k in ("hr_name", "hr_phone", "ats", "careers_url", "designated_employer_status"):
        if incoming.get(k) and (not merged.get(k) or (override and incoming.get(k) != merged.get(k))):
            merged[k] = incoming[k]
            outcome = outcome if outcome != "unchanged" else "updated"
    if incoming["notes"] and incoming["notes"] not in (merged.get("notes") or ""):
        merged["notes"] = ((merged.get("notes") or "") + " | " + incoming["notes"]).strip(" |")
        outcome = outcome if outcome != "unchanged" else "updated"
    if outcome != "unchanged":
        merged["updated_at"] = now
        merged.setdefault("history", []).append({"at": now, "source": source, "outcome": outcome,
                                                 "confidence_in": conf})
        with db.connect() as conn:
            _write(conn, merged)
    return merged, outcome


def set_do_not_contact(cid: str, flag: bool, reason: str = "", by: str = "keerthi") -> dict | None:
    c = get_contact(cid)
    if c is None:
        return None
    c["do_not_contact"] = bool(flag)
    c["do_not_contact_reason"] = reason if flag else ""
    c["updated_at"] = datetime.now().isoformat(timespec="seconds")
    c.setdefault("history", []).append({"at": c["updated_at"], "source": by,
                                        "outcome": "do_not_contact" if flag else "contact_allowed", "reason": reason})
    with db.connect() as conn:
        _write(conn, c)
    return c


def mark_bad_address(email: str, reason: str = "bounced") -> int:
    """A bounce flags every contact row with that address as do_not_contact and bad,
    so enrichment never resurfaces it. Returns rows affected."""
    e = (email or "").strip().lower()
    if not e:
        return 0
    n = 0
    for c in list_contacts():
        if (c.get("hr_email") or "").lower() == e:
            c["do_not_contact"] = True
            c["bad_address"] = True
            c["bad_reason"] = reason
            c["updated_at"] = datetime.now().isoformat(timespec="seconds")
            with db.connect() as conn:
                _write(conn, c)
            n += 1
    return n


def companies_without_contacts(companies: list[str]) -> list[str]:
    """Work list: which of these companies have no usable contact yet."""
    have = {c.get("company_norm") or norm_company(c.get("company", ""))
            for c in list_contacts() if c.get("hr_email") and not c.get("do_not_contact")}
    return sorted({co for co in companies if norm_company(co) not in have}, key=str.lower)
