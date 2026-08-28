"""Semi-automated application attempts (SQLite, table ``apply_sessions``).

One row per attempt. It holds the form we extracted, the plan we filled it with,
and — crucially — the confirmation decision. The hard rule of this feature is
that nothing is ever submitted without the user's explicit approval *in that
session*, and this table is what makes that rule auditable after the fact rather
than a promise made in a prompt.

Status flow::

    prepared  -> the form was read and filled; waiting on the user
    approved  -> the user said yes; submission may proceed
    rejected  -> the user said no; nothing was submitted
    submitted -> the submit button was clicked and the success state verified
    failed    -> something broke (extraction, generation, or submission)

Every terminal state is logged against the job in the existing review queue, so
this table is an audit trail, never a second application tracker.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from . import db

PREPARED = "prepared"
APPROVED = "approved"
REJECTED = "rejected"
SUBMITTED = "submitted"
FAILED = "failed"

TERMINAL = {REJECTED, SUBMITTED, FAILED}


def new_session(*, job_url: str, company: str = "", title: str = "",
                job_key: str = "", run_id: str = "", **extra) -> dict:
    """Create a `prepared` session. `extra` carries the form schema + fill plan."""
    session = {
        "session_id": uuid.uuid4().hex[:16],
        "job_url": job_url,
        "company": company,
        "title": title,
        "job_key": job_key,
        "run_id": run_id,
        "status": PREPARED,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "history": [],
        **extra,
    }
    return save_session(session)


def save_session(session: dict) -> dict:
    with db.connect() as conn:
        db._upsert_apply_session_row(conn, session)
    return session


def get_session(session_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM apply_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def list_sessions(*, job_key: str = "", limit: int = 50) -> list[dict]:
    """Recent sessions, newest first; optionally only those for one job."""
    sql = "SELECT data FROM apply_sessions"
    params: list = []
    if job_key:
        sql += " WHERE job_key = ?"
        params.append(job_key)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, int(limit)))
    out = []
    with db.connect() as conn:
        for r in conn.execute(sql, params):
            try:
                out.append(json.loads(r["data"]))
            except ValueError:
                continue
    return out


def set_status(session_id: str, status: str, note: str = "", **patch) -> dict | None:
    """Advance a session's status, appending to its history. Extra keyword
    arguments are shallow-merged into the record (e.g. `submitted_at`)."""
    session = get_session(session_id)
    if session is None:
        return None
    session["status"] = status
    session.update(patch)
    session.setdefault("history", []).append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "note": note,
    })
    return save_session(session)


def delete_session(session_id: str) -> bool:
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM apply_sessions WHERE session_id = ?", (session_id,)
        )
        return cur.rowcount > 0
