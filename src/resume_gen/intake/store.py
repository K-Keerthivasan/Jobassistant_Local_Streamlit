"""Dedup store + review queue, persisted in SQLite (see db.py).

Tables used:
  seen  -> set of job keys we've already processed
  jobs  -> one QueuedJob row per queued job (full model in the `data` column)

The public functions keep the signatures they had when this was JSON-backed, so
nothing in the API layer changes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from . import db
from .models import JobPosting, QueuedJob

# Repost-heavy feeds: Job Bank / RSS list the SAME role under many posting IDs, so
# the posting-id key alone doesn't dedup them. For these we also collapse by
# content identity (company + title + location). Curated sources (collector /
# manual / csv / email / hermes) are left alone — you may legitimately add the
# same company+title by hand.
_CONTENT_DEDUP_SOURCES = {"jobbank", "rss"}


def _content_id(j) -> str:
    n = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    return f"{j.source}|{n(j.company)}|{n(j.title)}|{n(j.location)}"


def _queue_content_ids() -> set[str]:
    """Content identities already in the queue (for the dedup-by-content sources),
    so a reposted role isn't queued again on the next fetch."""
    out: set[str] = set()
    with db.connect() as conn:
        for r in conn.execute("SELECT data FROM jobs"):
            try:
                d = QueuedJob.model_validate_json(r["data"])
            except ValueError:
                continue
            if d.source in _CONTENT_DEDUP_SOURCES:
                out.add(_content_id(d))
    return out


def _row_to_job(row) -> QueuedJob | None:
    try:
        return QueuedJob.model_validate_json(row["data"])
    except ValueError:
        return None


def _load_seen() -> set[str]:
    with db.connect() as conn:
        return {r["key"] for r in conn.execute("SELECT key FROM seen")}


def filter_new(jobs: list[JobPosting]) -> list[JobPosting]:
    """Keep only postings we haven't queued before. Dedups on the posting key
    (across runs via `seen`, and within the batch). For repost-heavy feeds
    (Job Bank / RSS) it ALSO collapses by content identity (company + title +
    location), keeping the freshest copy, so the same role reposted under a new
    posting id isn't queued again."""
    seen = _load_seen()
    existing_content = _queue_content_ids()
    out, batch_keys, batch_content = [], set(), set()
    # Newest-posted first so the copy we keep for a reposted role is the freshest.
    for j in sorted(jobs, key=lambda x: x.posted or "", reverse=True):
        if j.key in seen or j.key in batch_keys:
            continue
        if j.source in _CONTENT_DEDUP_SOURCES:
            cid = _content_id(j)
            if cid in existing_content or cid in batch_content:
                continue
            batch_content.add(cid)
        batch_keys.add(j.key)
        out.append(j)
    return out


def commit(jobs: list[JobPosting]) -> list[QueuedJob]:
    """Mark jobs as seen and write each to the review queue as status='new'."""
    now = datetime.now().isoformat(timespec="seconds")
    queued: list[QueuedJob] = []
    with db.connect() as conn:
        for j in jobs:
            q = QueuedJob(**j.model_dump(), key_id=j.key, status="new", found_at=now)
            db._upsert_job_row(conn, json.loads(q.model_dump_json()))
            conn.execute("INSERT OR IGNORE INTO seen(key) VALUES (?)", (j.key,))
            queued.append(q)
    return queued


def list_queue(status: str | None = None) -> list[QueuedJob]:
    with db.connect() as conn:
        if status is None:
            cur = conn.execute("SELECT data FROM jobs ORDER BY found_at DESC")
        else:
            cur = conn.execute(
                "SELECT data FROM jobs WHERE status = ? ORDER BY found_at DESC",
                (status,),
            )
        items = [j for j in (_row_to_job(r) for r in cur.fetchall()) if j is not None]
    return items


def get_job(key_id: str) -> QueuedJob | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM jobs WHERE key_id = ?", (key_id,)
        ).fetchone()
    return _row_to_job(row) if row else None


def _save(q: QueuedJob) -> QueuedJob:
    with db.connect() as conn:
        db._upsert_job_row(conn, json.loads(q.model_dump_json()))
    return q


def update_status(key_id: str, status: str, notes: str = "") -> QueuedJob | None:
    q = get_job(key_id)
    if q is None:
        return None
    q.status = status
    if notes:
        q.notes = notes
    return _save(q)


def set_applied(key_id: str, applied: bool) -> QueuedJob | None:
    q = get_job(key_id)
    if q is None:
        return None
    q.applied = applied
    return _save(q)


def stamp_sent(key_id: str, to_email: str) -> QueuedJob | None:
    """Record that the application email was actually sent (production), to whom."""
    q = get_job(key_id)
    if q is None:
        return None
    q.sent_at = datetime.now().isoformat(timespec="seconds")
    q.sent_to = (to_email or "").strip()
    return _save(q)


def record_followup(key_id: str) -> QueuedJob | None:
    """Append a follow-up timestamp to the job's history."""
    q = get_job(key_id)
    if q is None:
        return None
    q.followups = list(q.followups or [])
    q.followups.append(datetime.now().isoformat(timespec="seconds"))
    return _save(q)


def set_priority(key_id: str, priority: bool) -> QueuedJob | None:
    q = get_job(key_id)
    if q is None:
        return None
    q.priority = priority
    return _save(q)


def set_priority_override(key_id: str, level: str) -> QueuedJob | None:
    """Manually pin a job's priority. `level` in {'', 'high', 'medium', 'low'};
    '' clears the pin and lets the auto-score decide."""
    q = get_job(key_id)
    if q is None:
        return None
    level = (level or "").strip().lower()
    q.priority_override = level if level in ("high", "medium", "low") else ""
    q.priority = q.priority_override == "high"   # keep legacy flag roughly in sync
    return _save(q)


def set_repeatable(key_id: str, repeatable: bool) -> QueuedJob | None:
    q = get_job(key_id)
    if q is None:
        return None
    q.repeatable = repeatable
    return _save(q)


def set_irrelevant(key_id: str, irrelevant: bool) -> QueuedJob | None:
    """Flag/unflag a job as not relevant. Irrelevant jobs are hidden from the
    active lists (queue, bulk picker, library, scraped list) but kept (and seen),
    so they don't come back on the next fetch and can be restored."""
    q = get_job(key_id)
    if q is None:
        return None
    q.irrelevant = irrelevant
    return _save(q)


def delete_job(key_id: str, *, forget_seen: bool = True) -> QueuedJob | None:
    """Remove a queued job. Optionally remove its key from `seen` so a future
    scrape can queue it again."""
    q = get_job(key_id)
    if q is None:
        return None
    with db.connect() as conn:
        conn.execute("DELETE FROM jobs WHERE key_id = ?", (key_id,))
        if forget_seen:
            conn.execute("DELETE FROM seen WHERE key = ?", (key_id,))
    return q


def dedupe_jobs() -> dict:
    """Collapse duplicate queued jobs that share company + title + location,
    keeping the most valuable copy of each (generated/applied/repeatable/priority,
    else the newest) and deleting the rest. Deleted keys stay in `seen` so they
    don't come back on the next fetch."""
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    def _score(j: QueuedJob):
        return (
            1 if j.status == "generated" else 0,
            1 if j.applied else 0,
            1 if j.repeatable else 0,
            1 if j.priority else 0,
            j.posted or "",
            j.found_at or "",
        )

    with db.connect() as conn:
        jobs = [j for j in (_row_to_job(r) for r in conn.execute("SELECT data FROM jobs")) if j]

    groups: dict[tuple, list] = {}
    for j in jobs:
        groups.setdefault((_norm(j.company), _norm(j.title), _norm(j.location)), []).append(j)

    removed = 0
    dup_groups = 0
    with db.connect() as conn:
        for g in groups.values():
            if len(g) <= 1:
                continue
            dup_groups += 1
            for j in sorted(g, key=_score, reverse=True)[1:]:   # keep best, drop rest
                conn.execute("DELETE FROM jobs WHERE key_id = ?", (j.key_id,))
                removed += 1
    return {"removed": removed, "groups": dup_groups}


_EDITABLE = {"company", "title", "location", "description", "apply_url", "contact_email"}


def update_fields(key_id: str, fields: dict) -> QueuedJob | None:
    """Edit a queued job's content fields (e.g. add an HR email)."""
    q = get_job(key_id)
    if q is None:
        return None
    for k, v in (fields or {}).items():
        if k in _EDITABLE:
            setattr(q, k, v)
    return _save(q)
