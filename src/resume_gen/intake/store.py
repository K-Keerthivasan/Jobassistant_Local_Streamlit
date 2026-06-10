"""Dedup store + review queue, persisted as JSON under settings.intake_dir.

  intake/seen.json        -> set of job keys we've already processed
  intake/queue/<key>.json -> one QueuedJob awaiting review/generation/send
"""

from __future__ import annotations

import json
from datetime import datetime

from ..config import settings
from .models import JobPosting, QueuedJob

_SEEN = settings.intake_dir / "seen.json"
_QUEUE = settings.intake_dir / "queue"


def _load_seen() -> set[str]:
    if _SEEN.exists():
        try:
            return set(json.loads(_SEEN.read_text(encoding="utf-8")))
        except ValueError:
            return set()
    return set()


def _save_seen(seen: set[str]) -> None:
    _SEEN.parent.mkdir(parents=True, exist_ok=True)
    _SEEN.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


def filter_new(jobs: list[JobPosting]) -> list[JobPosting]:
    """Keep only postings whose key we haven't seen before (dedup within the
    batch too, so the same job from two sources isn't queued twice)."""
    seen = _load_seen()
    out, batch = [], set()
    for j in jobs:
        if j.key in seen or j.key in batch:
            continue
        batch.add(j.key)
        out.append(j)
    return out


def commit(jobs: list[JobPosting]) -> list[QueuedJob]:
    """Mark jobs as seen and write each to the review queue as status='new'."""
    seen = _load_seen()
    _QUEUE.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    queued: list[QueuedJob] = []
    for j in jobs:
        q = QueuedJob(**j.model_dump(), key_id=j.key, status="new", found_at=now)
        (_QUEUE / f"{j.key}.json").write_text(q.model_dump_json(indent=2), encoding="utf-8")
        seen.add(j.key)
        queued.append(q)
    _save_seen(seen)
    return queued


def list_queue(status: str | None = None) -> list[QueuedJob]:
    if not _QUEUE.exists():
        return []
    items: list[QueuedJob] = []
    for f in _QUEUE.glob("*.json"):
        try:
            q = QueuedJob.model_validate_json(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if status is None or q.status == status:
            items.append(q)
    items.sort(key=lambda q: q.found_at, reverse=True)
    return items


def get_job(key_id: str) -> QueuedJob | None:
    f = _QUEUE / f"{key_id}.json"
    if not f.exists():
        return None
    try:
        return QueuedJob.model_validate_json(f.read_text(encoding="utf-8"))
    except ValueError:
        return None


def update_status(key_id: str, status: str, notes: str = "") -> QueuedJob | None:
    q = get_job(key_id)
    if q is None:
        return None
    q.status = status
    if notes:
        q.notes = notes
    (_QUEUE / f"{key_id}.json").write_text(q.model_dump_json(indent=2), encoding="utf-8")
    return q
