"""SQLite storage for the intake subsystem.

Replaces the per-file JSON stores (queue/*.json, seen.json, repeatable/*.json,
companies/*.json) with a single embedded database at ``settings.db_path``. The
public functions in ``store.py`` / ``repeatable.py`` / ``companies.py`` keep their
signatures — only their bodies now read/write here.

Design notes
------------
* SQLite is embedded (no server, stdlib ``sqlite3``); the DB is one file under
  ``data/`` which is mounted in Docker, so it persists.
* A fresh connection is opened per operation. ``sqlite3.connect`` is cheap and
  this keeps things thread-safe under FastAPI's threadpool. WAL mode + a busy
  timeout let readers and the single writer coexist.
* Records are stored as their full JSON in a ``data`` column, with a few columns
  duplicated out for indexing/sorting. Readers reconstruct from ``data``, so the
  pydantic models can evolve without a schema migration.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from ..config import settings

_INIT_LOCK = threading.Lock()
_INITIALIZED = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key_id        TEXT PRIMARY KEY,
    status        TEXT,
    applied       INTEGER DEFAULT 0,
    found_at      TEXT,
    company       TEXT,
    title         TEXT,
    contact_email TEXT,
    data          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status   ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_found_at ON jobs(found_at);

CREATE TABLE IF NOT EXISTS seen (
    key TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS repeatable_roles (
    key          TEXT PRIMARY KEY,
    status       TEXT,
    last_applied TEXT,
    updated_at   TEXT,
    data         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    slug    TEXT PRIMARY KEY,
    company TEXT,
    data    TEXT NOT NULL
);

-- Generated applications. Nothing is written to disk: the full bundle (resume,
-- cover letter, email, qa, target) lives in `data` and PDFs/DOCX are rendered
-- on demand at download time. One row per application run.
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    company    TEXT,
    title      TEXT,
    persona    TEXT,
    created_at TEXT,
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
"""


def _db_file() -> Path:
    return settings.db_path


def _ensure_init() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        _db_file().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(_db_file())
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        _INITIALIZED = True
        _migrate_json_if_needed()


@contextmanager
def connect():
    """Yield a connection with row access by name. One per operation."""
    _ensure_init()
    conn = sqlite3.connect(_db_file(), timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=10000;")
        yield conn
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# One-time JSON -> SQLite migration (idempotent)
# --------------------------------------------------------------------------- #
def _migrate_json_if_needed() -> None:
    """Import the legacy JSON stores into the DB the first time the DB is empty.
    Safe to run repeatedly: it only fills tables that have no rows yet."""
    try:
        migrate_json(force=False)
    except Exception:
        # Never let a migration hiccup block startup; the app still works on an
        # empty DB and the data files are left untouched.
        pass


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def migrate_json(force: bool = False) -> dict:
    """Backfill the DB from the existing JSON files. Returns a per-table count of
    rows imported. With ``force=False`` a table is skipped if it already has rows
    (so this won't duplicate or clobber DB-native data)."""
    from .companies import _COMPANIES  # noqa: WPS437 (internal paths)

    from ..config import ROOT

    intake_dir = settings.intake_dir
    queue_dir = intake_dir / "queue"
    seen_file = intake_dir / "seen.json"
    repeat_dir = ROOT / "data" / "repeatable"  # legacy per-role JSON location
    imported = {"jobs": 0, "seen": 0, "repeatable_roles": 0, "companies": 0, "runs": 0}

    with connect() as conn:
        # jobs
        if force or _count(conn, "jobs") == 0:
            for f in sorted(queue_dir.glob("*.json")) if queue_dir.exists() else []:
                try:
                    obj = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                _upsert_job_row(conn, obj)
                imported["jobs"] += 1
        # seen
        if force or _count(conn, "seen") == 0:
            if seen_file.exists():
                try:
                    keys = json.loads(seen_file.read_text(encoding="utf-8"))
                except ValueError:
                    keys = []
                for k in keys:
                    conn.execute("INSERT OR IGNORE INTO seen(key) VALUES (?)", (k,))
                    imported["seen"] += 1
        # repeatable roles
        if force or _count(conn, "repeatable_roles") == 0:
            if repeat_dir.exists():
                for f in sorted(repeat_dir.glob("*.json")):
                    try:
                        obj = json.loads(f.read_text(encoding="utf-8"))
                    except ValueError:
                        continue
                    _upsert_role_row(conn, obj)
                    imported["repeatable_roles"] += 1
        # company memory
        if force or _count(conn, "companies") == 0:
            if _COMPANIES.exists():
                for f in sorted(_COMPANIES.glob("*.json")):
                    try:
                        obj = json.loads(f.read_text(encoding="utf-8"))
                    except ValueError:
                        continue
                    _upsert_company_row(conn, f.stem, obj)
                    imported["companies"] += 1

    # Past runs: backfill the `runs` table from any legacy output/<folder>/ dirs
    # so previously generated applications stay visible and re-downloadable.
    with connect() as conn:
        if force or _count(conn, "runs") == 0:
            imported["runs"] = _backfill_runs_from_folders(conn)
    return imported


def _backfill_runs_from_folders(conn) -> int:
    """Import legacy file-based output folders into the `runs` table. The JSON
    artifacts in each folder are read back into one run bundle; the files are
    left on disk untouched."""
    out_dir = settings.output_dir
    if not out_dir.exists():
        return 0

    def _json(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except ValueError:
            return {}

    n = 0
    for d in out_dir.iterdir():
        if not d.is_dir():
            continue
        target = _json(d / "target_role.json")
        email = {}
        et = d / "email.txt"
        if et.exists():
            raw = et.read_text(encoding="utf-8")
            subject, body = "", raw
            if raw.startswith("Subject:"):
                first, _, rest = raw.partition("\n")
                subject, body = first[len("Subject:"):].strip(), rest.lstrip("\n")
            email = {"subject": subject, "body": body}
        from datetime import datetime
        bundle = {
            "run_id": d.name,
            "created_at": datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds"),
            "target": target,
            "resume": _json(d / "resume.json"),
            "cover_letter": _json(d / "cover_letter.json"),
            "email": email,
            "qa": _json(d / "qa_report.json"),
            "persona": target.get("persona", ""),
            "persona_label": target.get("persona_label", ""),
        }
        _upsert_run_row(conn, bundle)
        n += 1
    return n


# --------------------------------------------------------------------------- #
# Row writers shared by store.py / repeatable.py / companies.py
# --------------------------------------------------------------------------- #
def _upsert_job_row(conn, obj: dict) -> None:
    conn.execute(
        """INSERT INTO jobs (key_id, status, applied, found_at, company, title,
                             contact_email, data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(key_id) DO UPDATE SET
             status=excluded.status, applied=excluded.applied,
             found_at=excluded.found_at, company=excluded.company,
             title=excluded.title, contact_email=excluded.contact_email,
             data=excluded.data""",
        (
            obj.get("key_id", ""),
            obj.get("status", "new"),
            1 if obj.get("applied") else 0,
            obj.get("found_at", ""),
            obj.get("company", ""),
            obj.get("title", ""),
            obj.get("contact_email", ""),
            json.dumps(obj, ensure_ascii=False),
        ),
    )


def _upsert_role_row(conn, obj: dict) -> None:
    conn.execute(
        """INSERT INTO repeatable_roles (key, status, last_applied, updated_at, data)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET
             status=excluded.status, last_applied=excluded.last_applied,
             updated_at=excluded.updated_at, data=excluded.data""",
        (
            obj.get("key", ""),
            obj.get("status", ""),
            obj.get("last_applied", ""),
            obj.get("updated_at", ""),
            json.dumps(obj, ensure_ascii=False),
        ),
    )


def _upsert_company_row(conn, slug: str, obj: dict) -> None:
    conn.execute(
        """INSERT INTO companies (slug, company, data) VALUES (?, ?, ?)
           ON CONFLICT(slug) DO UPDATE SET
             company=excluded.company, data=excluded.data""",
        (slug, obj.get("company", ""), json.dumps(obj, ensure_ascii=False)),
    )


def _upsert_run_row(conn, bundle: dict) -> None:
    target = bundle.get("target") or {}
    conn.execute(
        """INSERT INTO runs (run_id, company, title, persona, created_at, data)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(run_id) DO UPDATE SET
             company=excluded.company, title=excluded.title,
             persona=excluded.persona, created_at=excluded.created_at,
             data=excluded.data""",
        (
            bundle.get("run_id", ""),
            target.get("company", ""),
            target.get("title", ""),
            bundle.get("persona_label", "") or target.get("persona_label", ""),
            bundle.get("created_at", ""),
            json.dumps(bundle, ensure_ascii=False),
        ),
    )
