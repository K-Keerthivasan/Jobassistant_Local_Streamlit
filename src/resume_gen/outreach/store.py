"""Outreach message queue, audit events, suppression list and settings (SQLite).

Message status lifecycle (brief 6.1):

    draft -> queued -> approved -> sending -> sent -> replied | bounced | failed | cancelled

``approved`` is the only status dispatch will ever pick up, and only an explicit
approval by Keerthi puts a message there. Every step of a sequence is its own
message row and needs its own approval.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

from ..config import settings
from ..intake import db

STATUSES = ("draft", "queued", "approved", "sending", "sent", "replied", "bounced", "failed", "cancelled")
TERMINAL = {"replied", "bounced", "failed", "cancelled"}
PENDING = {"draft", "queued", "approved"}      # not yet handed to n8n
_TRANSITIONS = {
    "draft": {"queued", "cancelled"},
    "queued": {"approved", "cancelled", "draft"},
    "approved": {"sending", "cancelled", "queued"},
    "sending": {"sent", "failed", "bounced", "cancelled", "approved"},
    "sent": {"replied", "bounced", "failed"},
    "replied": set(), "bounced": set(), "failed": {"queued"}, "cancelled": set(),
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# messages
# --------------------------------------------------------------------------- #
def _write_message(conn, m: dict) -> None:
    conn.execute(
        """INSERT INTO outreach_messages (id, contact_id, job_id, template_id, sequence_id,
                                          sequence_step, status, scheduled_for, sent_at,
                                          created_at, updated_at, data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             contact_id=excluded.contact_id, job_id=excluded.job_id,
             template_id=excluded.template_id, sequence_id=excluded.sequence_id,
             sequence_step=excluded.sequence_step, status=excluded.status,
             scheduled_for=excluded.scheduled_for, sent_at=excluded.sent_at,
             updated_at=excluded.updated_at, data=excluded.data""",
        (m["id"], m.get("contact_id", ""), m.get("job_id", ""), m.get("template_id", ""),
         m.get("sequence_id", ""), int(m.get("sequence_step") or 1), m.get("status", "draft"),
         m.get("scheduled_for", ""), m.get("sent_at", ""), m.get("created_at", ""),
         m.get("updated_at", ""), json.dumps(m, ensure_ascii=False)))


def _row(row) -> dict | None:
    try:
        return json.loads(row["data"])
    except (ValueError, TypeError):
        return None


def get_message(mid: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT data FROM outreach_messages WHERE id = ?", (mid,)).fetchone()
    return _row(row) if row else None


def list_messages(status: str | list[str] | None = None, *, contact_id: str = "",
                  sequence_id: str = "", company: str = "", limit: int = 500) -> list[dict]:
    clauses, args = [], []
    if status:
        sts = [status] if isinstance(status, str) else list(status)
        clauses.append("status IN (%s)" % ",".join("?" * len(sts))); args += sts
    if contact_id:
        clauses.append("contact_id = ?"); args.append(contact_id)
    if sequence_id:
        clauses.append("sequence_id = ?"); args.append(sequence_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db.connect() as conn:
        cur = conn.execute(f"SELECT data FROM outreach_messages {where} ORDER BY created_at DESC LIMIT ?",
                           (*args, limit))
        out = [m for m in (_row(r) for r in cur.fetchall()) if m]
    if company:
        c = company.strip().lower()
        out = [m for m in out if (m.get("company") or "").strip().lower() == c]
    return out


def create_message(*, contact: dict, job: dict | None, template_id: str, subject: str, body: str,
                   sequence_id: str = "", sequence_step: int = 1, scheduled_for: str = "",
                   attach_resume: bool = False, run_id: str = "", meta: dict | None = None,
                   actor: str = "keerthi") -> dict:
    now = _now()
    m = {
        "id": uuid.uuid4().hex, "contact_id": contact["id"], "job_id": (job or {}).get("key_id", ""),
        "company": contact.get("company", ""), "to_email": contact.get("hr_email", ""),
        "to_name": contact.get("hr_name", ""), "contact_confidence": contact.get("confidence", ""),
        "template_id": template_id, "sequence_id": sequence_id or uuid.uuid4().hex[:12],
        "sequence_step": int(sequence_step), "subject": subject, "body": body,
        "status": "draft", "scheduled_for": scheduled_for or now, "sent_at": "",
        "provider_message_id": "", "thread_id": "", "opened_at": "", "replied_at": "",
        "reply_sentiment": "", "bounce_reason": "", "error": "",
        "attach_resume": bool(attach_resume), "run_id": run_id,
        "job_title": (job or {}).get("title", ""), "lane": (job or {}).get("lane_slug", ""),
        "tier": ((job or {}).get("grade") or {}).get("tier", ""),
        "gap_flags": ((job or {}).get("grade") or {}).get("gap_flags", []),
        "pathway": (f"{job['pathway_type']}: {job['pathway_detail']}" if job and job.get("pathway_type") else ""),
        "meta": meta or {}, "approved_by": "", "approved_at": "",
        "created_by": actor, "created_at": now, "updated_at": now, "history": [{"at": now, "status": "draft", "by": actor}],
    }
    with db.connect() as conn:
        _write_message(conn, m)
    log_event("drafted", message_id=m["id"], contact_id=m["contact_id"], actor=actor,
              data={"template_id": template_id, "step": m["sequence_step"]})
    return m


def set_status(mid: str, status: str, *, actor: str = "system", reason: str = "",
               patch: dict | None = None, force: bool = False) -> dict:
    """Move a message along the lifecycle. Illegal transitions raise ValueError."""
    m = get_message(mid)
    if m is None:
        raise KeyError(mid)
    cur = m.get("status", "draft")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    if status != cur and not force and status not in _TRANSITIONS.get(cur, set()):
        raise ValueError(f"cannot move message {mid} from {cur} to {status}")
    m["status"] = status
    m["updated_at"] = _now()
    if patch:
        m.update(patch)
    m.setdefault("history", []).append({"at": m["updated_at"], "status": status, "by": actor, "reason": reason})
    with db.connect() as conn:
        _write_message(conn, m)
    log_event(f"status:{status}", message_id=mid, contact_id=m.get("contact_id", ""), actor=actor,
              data={"from": cur, "reason": reason})
    return m


def approve(mids: list[str], actor: str = "keerthi") -> list[dict]:
    """The approval gate. queued -> approved, one row at a time, recorded with who and when."""
    out = []
    for mid in mids:
        m = get_message(mid)
        if m is None or m.get("status") != "queued":
            continue
        out.append(set_status(mid, "approved", actor=actor,
                              patch={"approved_by": actor, "approved_at": _now()}))
        log_event("approved", message_id=mid, contact_id=m.get("contact_id", ""), actor=actor, data={})
    return out


def cancel_pending_in_sequence(sequence_id: str, *, reason: str, actor: str = "system",
                               exclude: str = "") -> int:
    n = 0
    for m in list_messages(list(PENDING | {"sending"}), sequence_id=sequence_id):
        if m["id"] == exclude:
            continue
        set_status(m["id"], "cancelled", actor=actor, reason=reason)
        n += 1
    return n


def cancel_pending_for_contact(contact_id: str, *, reason: str, actor: str = "system") -> int:
    n = 0
    for m in list_messages(list(PENDING | {"sending"}), contact_id=contact_id):
        set_status(m["id"], "cancelled", actor=actor, reason=reason)
        n += 1
    return n


def sent_count_on(day: date) -> int:
    d = day.isoformat()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM outreach_messages WHERE status IN ('sending','sent','replied','bounced') "
            "AND substr(sent_at, 1, 10) = ?", (d,)).fetchone()
    return int(row[0]) if row else 0


def last_send_to_contact(contact_id: str) -> str:
    """ISO datetime of the latest message handed to n8n for this contact, or ''."""
    best = ""
    for m in list_messages(["sending", "sent", "replied", "bounced"], contact_id=contact_id):
        best = max(best, m.get("sent_at") or "")
    return best


def sends_to_address(email: str) -> int:
    e = (email or "").strip().lower()
    if not e:
        return 0
    return sum(1 for m in list_messages(["sending", "sent", "replied", "bounced", "failed"])
               if (m.get("to_email") or "").lower() == e)


def live_sequences_for_company(company: str, *, within_days: int) -> list[str]:
    """Sequence ids at this company that were handed to n8n inside the window or
    are in flight. Rows that are merely approved do not count (dispatch orders
    them and lets one through per batch), otherwise two approved sequences at
    one company would block each other forever."""
    c = (company or "").strip().lower()
    cutoff = (datetime.now() - timedelta(days=within_days)).isoformat(timespec="seconds")
    seqs: set[str] = set()
    for m in list_messages(["sending", "sent", "replied"]):
        if (m.get("company") or "").strip().lower() != c:
            continue
        if m["status"] == "sending" or (m.get("sent_at") or "") >= cutoff:
            seqs.add(m.get("sequence_id", ""))
    return sorted(seqs)


# --------------------------------------------------------------------------- #
# events (audit log)
# --------------------------------------------------------------------------- #
def log_event(kind: str, *, message_id: str = "", contact_id: str = "", actor: str = "system",
              data: dict | None = None) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO outreach_events (at, kind, message_id, contact_id, actor, data) VALUES (?, ?, ?, ?, ?, ?)",
                     (_now(), kind, message_id, contact_id, actor, json.dumps(data or {}, ensure_ascii=False)))


def events(*, message_id: str = "", kind: str = "", limit: int = 200) -> list[dict]:
    clauses, args = [], []
    if message_id:
        clauses.append("message_id = ?"); args.append(message_id)
    if kind:
        clauses.append("kind = ?"); args.append(kind)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db.connect() as conn:
        cur = conn.execute(f"SELECT id, at, kind, message_id, contact_id, actor, data FROM outreach_events {where} "
                           f"ORDER BY id DESC LIMIT ?", (*args, limit))
        out = []
        for r in cur.fetchall():
            try:
                d = json.loads(r["data"])
            except ValueError:
                d = {}
            out.append({"id": r["id"], "at": r["at"], "kind": r["kind"], "message_id": r["message_id"],
                        "contact_id": r["contact_id"], "actor": r["actor"], "data": d})
        return out


def callback_seen(message_id: str, event: str) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM outreach_events WHERE kind = ? AND message_id = ? LIMIT 1",
                           (f"callback:{event}", message_id)).fetchone()
    return bool(row)


# --------------------------------------------------------------------------- #
# suppression + state
# --------------------------------------------------------------------------- #
def suppress(key: str, kind: str, reason: str = "", by: str = "keerthi") -> None:
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO outreach_suppression (key, kind, reason, added_at, added_by) VALUES (?, ?, ?, ?, ?)",
                     (key.strip().lower(), kind, reason, _now(), by))
    log_event("suppressed", actor=by, data={"key": key, "kind": kind, "reason": reason})


def unsuppress(key: str, by: str = "keerthi") -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM outreach_suppression WHERE key = ?", (key.strip().lower(),))
    log_event("unsuppressed", actor=by, data={"key": key})


def suppression_list() -> list[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT key, kind, reason, added_at, added_by FROM outreach_suppression ORDER BY added_at DESC")]


def is_suppressed(*, email: str = "", company: str = "") -> str:
    """Returns the matching suppression key, or ''."""
    from .contacts import norm_company
    keys = {k["key"]: k["kind"] for k in suppression_list()}
    e = (email or "").strip().lower()
    if e and e in keys:
        return e
    dom = e.split("@")[-1] if "@" in e else ""
    if dom and f"@{dom}" in keys:
        return f"@{dom}"
    c = norm_company(company)
    if c and c in keys:
        return c
    return ""


def get_state(key: str, default: str = "") -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM outreach_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str, by: str = "keerthi") -> None:
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO outreach_state (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                     (key, str(value), _now(), by))
    log_event(f"state:{key}", actor=by, data={"value": value})


def kill_switch_on() -> bool:
    return get_state("kill_switch", "0") in ("1", "true", "on")


def daily_cap() -> int:
    v = get_state("daily_cap", "")
    return int(v) if v.isdigit() else settings.outreach_daily_cap


def cooldown_days() -> int:
    v = get_state("cooldown_days", "")
    return int(v) if v.isdigit() else settings.outreach_cooldown_days
